"""FastAPI application for autopay recovery voice agent.

Provides:
- REST API for dashboard and control operations
- WebSocket endpoint /ws for real-time telemetry streaming
- Protected /internal/events and /internal/sms endpoints for LiveKit agent worker
- LiveKit listen-token generation for hidden, subscribe-only audio monitoring
- Mock Razorpay payment portal at /pay/{token}
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, Form, Header, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from livekit import api
from src.db import (
    add_event,
    add_link_event,
    add_message,
    add_turn,
    can_dial_customer,
    create_call_record,
    get_all_customers,
    get_call_details,
    get_calls,
    get_conn,
    get_customer_state,
    get_metrics,
    init_db,
    mask_phone_number,
    set_customer_dnd,
    update_call_record,
    update_message_status,
)
from src.dial import check_call_window, dial_customer, load_customers, validate_demo_phone
from src.sms import send_payment_link_sms

load_dotenv()

logger = logging.getLogger("api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "secret_internal_token_change_me")


# ── WebSocket Manager ─────────────────────────────────────────────────────────
class WebSocketManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("WebSocket client connected (total: %d)", len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info("WebSocket client disconnected (total: %d)", len(self.active_connections))

    async def broadcast(self, message: dict[str, Any]) -> None:
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)


ws_manager = WebSocketManager()


# ── Active Batch Tracking ─────────────────────────────────────────────────────
_active_batches: dict[str, dict[str, Any]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Database initialized. FastAPI service started on 127.0.0.1:8000")
    yield


app = FastAPI(
    title="Autopay Recovery Voice Agent API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS restricted strictly to localhost dashboard dev servers
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic Request Models ───────────────────────────────────────────────────
class CallRequest(BaseModel):
    customer_id: str


class BatchCallRequest(BaseModel):
    customer_ids: list[str] | None = None
    delay_sec: float = Field(default=5.0, ge=1.0, le=60.0)


class InternalEventRequest(BaseModel):
    call_id: str
    event_type: str
    payload: dict[str, Any] = {}
    timestamp: str | None = None


class InternalSmsRequest(BaseModel):
    call_id: str
    customer_id: str
    first_name: str
    amount: float


# ── Security Dependency ───────────────────────────────────────────────────────
def verify_internal_secret(x_internal_secret: str | None = Header(None)) -> None:
    if not x_internal_secret or x_internal_secret != INTERNAL_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized: invalid internal secret header")


# ── Health & System Config ────────────────────────────────────────────────────
@app.get("/api/health")
def get_health() -> dict[str, str]:
    return {"status": "ok", "timestamp": datetime.now(UTC).isoformat()}


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    raw_demo = os.environ.get("DEMO_PHONE", "+919876543210")
    demo_override = os.environ.get("DEMO_OVERRIDE", "").lower() in ("true", "1", "yes")
    in_window, window_reason = check_call_window(demo_override=demo_override)

    return {
        "demo_phone_masked": mask_phone_number(raw_demo),
        "demo_override": demo_override,
        "in_call_window": in_window,
        "call_window_status": window_reason,
        "sms_mode": os.environ.get("SMS_MODE", "mock"),
        "voice_id": os.environ.get("ELEVEN_VOICE_ID") or os.environ.get("ELEVENLABS_VOICE_ID", "TX3LPaxmHKxFdv7VOQHJ"),
        "llm_provider": os.environ.get("LLM_PROVIDER", "groq"),
        "livekit_url": os.environ.get("LIVEKIT_URL", "wss://livekit.cloud"),
    }


# ── Customer Data ─────────────────────────────────────────────────────────────
@app.get("/api/customers")
def list_customers() -> list[dict[str, Any]]:
    # strictly omits birth_year
    return get_all_customers()


# ── Call Dispatch Endpoints ───────────────────────────────────────────────────
async def _execute_single_call(customer_id: str) -> dict[str, Any]:
    demo_phone = validate_demo_phone(os.environ.get("DEMO_PHONE"))
    demo_override = os.environ.get("DEMO_OVERRIDE", "").lower() in ("true", "1", "yes")

    customers = load_customers()
    matches = [c for c in customers if c["id"] == customer_id]
    if not matches:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

    customer = matches[0]
    can_dial, reason = can_dial_customer(customer_id, demo_override=demo_override)
    if not can_dial:
        raise HTTPException(status_code=400, detail=reason)

    caller_number = (
        os.environ.get("TWILIO_NUMBER")
        or os.environ.get("TWILIO_PHONE_NUMBER")
        or os.environ.get("SIP_CALLER_NUMBER")
    )
    if not caller_number:
        raise HTTPException(status_code=500, detail="TWILIO_NUMBER not configured")

    sip_trunk_id = os.environ.get("SIP_TRUNK_ID", "")
    lkapi = api.LiveKitAPI(
        url=os.environ.get("LIVEKIT_URL", ""),
        api_key=os.environ.get("LIVEKIT_API_KEY", ""),
        api_secret=os.environ.get("LIVEKIT_API_SECRET", ""),
    )

    try:
        room_name = await dial_customer(
            customer=customer,
            lkapi=lkapi,
            sip_trunk_id=sip_trunk_id,
            caller_number=caller_number,
            demo_phone=demo_phone,
            demo_override=demo_override,
        )
        if not room_name:
            raise HTTPException(status_code=500, detail="SIP call dispatch failed or was not answered")

        call_id = room_name
        create_call_record(
            call_id=call_id,
            customer_id=customer_id,
            room_name=room_name,
            source="live",
            voice_id=os.environ.get("ELEVEN_VOICE_ID", "TX3LPaxmHKxFdv7VOQHJ"),
            llm_provider=os.environ.get("LLM_PROVIDER", "groq"),
        )

        await ws_manager.broadcast({
            "type": "call.status",
            "call_id": call_id,
            "customer_id": customer_id,
            "status": "active",
            "timestamp": datetime.now(UTC).isoformat(),
        })

        return {"call_id": call_id, "room_name": room_name, "status": "active"}

    finally:
        await lkapi.aclose()


@app.post("/api/calls")
async def trigger_call(req: CallRequest) -> dict[str, Any]:
    return await _execute_single_call(req.customer_id)


@app.post("/api/calls/batch")
async def trigger_batch_calls(req: BatchCallRequest, bg_tasks: BackgroundTasks) -> dict[str, Any]:
    batch_id = f"batch_{secrets_token := uuid4().hex[:8]}"
    customers = load_customers()
    target_ids = req.customer_ids or [c["id"] for c in customers]

    _active_batches[batch_id] = {
        "status": "running",
        "total": len(target_ids),
        "completed": 0,
        "cancelled": False,
    }

    async def _batch_worker():
        for i, cid in enumerate(target_ids):
            if _active_batches.get(batch_id, {}).get("cancelled"):
                logger.info("Batch %s cancelled.", batch_id)
                break
            try:
                await _execute_single_call(cid)
            except Exception as e:
                logger.warning("Batch %s: Call for %s failed: %s", batch_id, cid, e)

            _active_batches[batch_id]["completed"] = i + 1
            await ws_manager.broadcast({
                "type": "batch.progress",
                "batch_id": batch_id,
                "completed": i + 1,
                "total": len(target_ids),
            })
            if i < len(target_ids) - 1:
                await asyncio.sleep(req.delay_sec)

        _active_batches[batch_id]["status"] = "finished"

    bg_tasks.add_task(_batch_worker)
    return {"batch_id": batch_id, "status": "started", "total_queued": len(target_ids)}


@app.post("/api/batch/{batch_id}/cancel")
def cancel_batch(batch_id: str) -> dict[str, str]:
    if batch_id in _active_batches:
        _active_batches[batch_id]["cancelled"] = True
        return {"status": "cancelled", "batch_id": batch_id}
    raise HTTPException(status_code=404, detail="Batch not found")


@app.post("/api/calls/{call_id}/end")
async def force_end_call(call_id: str) -> dict[str, str]:
    lkapi = api.LiveKitAPI(
        url=os.environ.get("LIVEKIT_URL", ""),
        api_key=os.environ.get("LIVEKIT_API_KEY", ""),
        api_secret=os.environ.get("LIVEKIT_API_SECRET", ""),
    )
    try:
        await lkapi.room.delete_room(api.DeleteRoomRequest(room=call_id))
        update_call_record(call_id=call_id, status="completed", outcome="declined", note="Manually ended from dashboard")
        await ws_manager.broadcast({
            "type": "call.status",
            "call_id": call_id,
            "status": "completed",
            "outcome": "declined",
        })
        return {"status": "terminated", "call_id": call_id}
    except Exception as e:
        logger.warning("Could not terminate room %s: %s", call_id, e)
        return {"status": "closed", "note": str(e)}
    finally:
        await lkapi.aclose()


# ── Call Logs, Details & Metrics ──────────────────────────────────────────────
@app.get("/api/calls")
def list_calls(limit: int = 50) -> list[dict[str, Any]]:
    return get_calls(limit=limit)


@app.get("/api/calls/{call_id}")
def get_call(call_id: str) -> dict[str, Any]:
    details = get_call_details(call_id)
    if not details:
        raise HTTPException(status_code=404, detail="Call record not found")
    return details


@app.get("/api/calls/{call_id}/listen-token")
def get_live_listen_token(call_id: str) -> dict[str, str]:
    """Issue a hidden, subscribe-only LiveKit token for the web dashboard."""
    api_key = os.environ.get("LIVEKIT_API_KEY")
    api_secret = os.environ.get("LIVEKIT_API_SECRET")
    livekit_url = os.environ.get("LIVEKIT_URL", "")

    if not (api_key and api_secret):
        raise HTTPException(status_code=500, detail="LiveKit credentials not configured")

    participant_identity = f"listen-{uuid4().hex[:6]}"
    token = (
        api.AccessToken(api_key=api_key, api_secret=api_secret)
        .with_identity(participant_identity)
        .with_name("Dashboard Listener")
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=call_id,
                can_publish=False,
                can_subscribe=True,
                can_publish_data=False,
                hidden=True,
            )
        )
        .to_jwt()
    )

    return {
        "token": token,
        "url": livekit_url,
        "room": call_id,
    }


@app.get("/api/metrics")
def metrics() -> dict[str, Any]:
    return get_metrics()


@app.get("/api/voices")
def get_voices() -> list[dict[str, Any]]:
    """List available ElevenLabs voices with accent, gender, and recommended status."""
    default_voices = [
        {
            "name": "Aanya (Default)",
            "voice_id": os.environ.get("ELEVEN_VOICE_ID", "TX3LPaxmHKxFdv7VOQHJ"),
            "gender": "Female",
            "accent": "Indian English",
            "use_case": "Customer Service & Autopay Recovery",
            "recommended": True,
        },
        {
            "name": "Aditi",
            "voice_id": "bIHbv24MWmeRgasZH58o",
            "gender": "Female",
            "accent": "Indian English",
            "use_case": "Conversational & Empathetic",
            "recommended": True,
        },
        {
            "name": "Rachel",
            "voice_id": "21m00Tcm4TlvDq8ikWAM",
            "gender": "Female",
            "accent": "American",
            "use_case": "Calm & Professional",
            "recommended": False,
        },
        {
            "name": "Drew",
            "voice_id": "29vD33N1CtxCmqQRPOHJ",
            "gender": "Male",
            "accent": "American",
            "use_case": "Authoritative & Formal",
            "recommended": False,
        },
    ]

    api_key = os.environ.get("ELEVEN_API_KEY") or os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        return default_voices

    active_id = os.environ.get("ELEVEN_VOICE_ID") or os.environ.get("ELEVENLABS_VOICE_ID", "TX3LPaxmHKxFdv7VOQHJ")
    try:
        import requests
        resp = requests.get(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": api_key},
            timeout=3.0,
        )
        if resp.status_code == 200:
            data = resp.json().get("voices", [])
            results = []
            for v in data:
                labels = v.get("labels", {})
                accent = labels.get("accent", "")
                gender = labels.get("gender", labels.get("accent_gender", "N/A"))
                use_case = labels.get("use_case", labels.get("description", "general"))
                is_rec = (v.get("voice_id") == active_id) or ("indian" in accent.lower()) or ("india" in v.get("name", "").lower())
                results.append({
                    "name": v.get("name", "Unknown"),
                    "voice_id": v.get("voice_id", ""),
                    "gender": gender,
                    "accent": accent or "Standard",
                    "use_case": use_case,
                    "recommended": is_rec,
                })
            if results:
                # Ensure at least one voice has recommended=True
                if not any(r["recommended"] for r in results):
                    results[0]["recommended"] = True
                results.sort(key=lambda x: not x["recommended"])
                return results
    except Exception as e:
        logger.warning("Could not fetch remote voices: %s", e)

    return default_voices


# ── Twilio Status Webhook (for Live SMS Delivery Tracking) ───────────────────
@app.post("/api/twilio/status")
async def twilio_status_webhook(
    request: Request,
    message_sid: str = Form(None, alias="MessageSid"),
    message_status: str = Form(None, alias="MessageStatus"),
    error_code: str = Form(None, alias="ErrorCode"),
    error_message: str = Form(None, alias="ErrorMessage"),
) -> Response:
    """Receive Twilio message status callbacks and broadcast to dashboard."""
    if not message_sid:
        return Response(content="<Response></Response>", media_type="text/xml")

    # Optional signature verification
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    sig = request.headers.get("X-Twilio-Signature")
    if auth_token and sig:
        try:
            from twilio.request_validator import RequestValidator
            validator = RequestValidator(auth_token)
            form_data = await request.form()
            url = str(request.url)
            if not validator.validate(url, dict(form_data), sig):
                logger.warning("Invalid Twilio signature on status webhook")
                raise HTTPException(status_code=403, detail="Invalid signature")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("Twilio signature validation error: %s", e)

    update_message_status(
        sid=message_sid,
        status=message_status or "unknown",
        error_code=error_code,
        error_message=error_message,
    )

    if message_status == "delivered":
        with get_conn() as conn:
            row = conn.execute("SELECT call_id FROM messages WHERE sid = ? LIMIT 1", (message_sid,)).fetchone()
            if row:
                cid = row["call_id"]
                conn.execute(
                    "INSERT INTO link_events (token, call_id, event_type, timestamp) "
                    "SELECT token, call_id, 'delivered', CURRENT_TIMESTAMP FROM link_events "
                    "WHERE call_id = ? AND event_type = 'sent' LIMIT 1",
                    (cid,),
                )

    await ws_manager.broadcast({
        "type": "message.status",
        "sid": message_sid,
        "status": message_status,
        "error_code": error_code,
        "timestamp": datetime.now(UTC).isoformat(),
    })

    return Response(content="<Response></Response>", media_type="text/xml")


# ── Internal Worker Communication (Protected by Shared Secret) ───────────────
@app.post("/internal/events")
async def receive_worker_event(
    req: InternalEventRequest,
    _: None = Depends(verify_internal_secret),
) -> dict[str, str]:
    # Persist turn or telemetry event
    ts = req.timestamp or datetime.now(UTC).isoformat()

    if req.event_type == "turn":
        speaker = req.payload.get("speaker", "agent")
        text = req.payload.get("text", "")
        is_final = req.payload.get("is_final", True)
        add_turn(call_id=req.call_id, speaker=speaker, text=text, is_final=is_final, timestamp=ts)
    else:
        add_event(call_id=req.call_id, event_type=req.event_type, payload=req.payload, timestamp=ts)

    if req.event_type == "state.update":
        outcome = req.payload.get("terminal_outcome")
        note = req.payload.get("outcome_note")
        if outcome:
            update_call_record(call_id=req.call_id, outcome=outcome, note=note)
        if req.payload.get("do_not_call"):
            cid = req.payload.get("customer_id")
            if cid:
                set_customer_dnd(cid)

    if req.event_type == "call.ended":
        duration = req.payload.get("duration_sec", 0.0)
        outcome = req.payload.get("final_outcome")
        transcript = req.payload.get("transcript", "")
        update_call_record(call_id=req.call_id, status="completed", outcome=outcome, duration_sec=duration, transcript=transcript)

    # Broadcast to all connected WebSockets
    await ws_manager.broadcast({
        "type": req.event_type,
        "call_id": req.call_id,
        "payload": req.payload,
        "timestamp": ts,
    })

    return {"status": "received"}


@app.post("/internal/sms")
async def dispatch_worker_sms(
    req: InternalSmsRequest,
    _: None = Depends(verify_internal_secret),
) -> dict[str, Any]:
    res = await send_payment_link_sms(
        call_id=req.call_id,
        customer_id=req.customer_id,
        first_name=req.first_name,
        amount=req.amount,
    )
    # Broadcast to dashboard
    await ws_manager.broadcast({
        "type": "message.status",
        "call_id": req.call_id,
        "sid": res.get("sid"),
        "status": res.get("initial_status", "sent"),
        "url": res.get("url"),
        "timestamp": datetime.now(UTC).isoformat(),
    })
    return res


# ── Mock Razorpay Payment Page & Completion ──────────────────────────────────
@app.get("/pay/{token}", response_class=HTMLResponse)
async def mock_payment_page(token: str) -> str:
    """Razorpay-styled mock payment page."""
    with get_conn() as conn:
        row = conn.execute("SELECT call_id FROM link_events WHERE token = ? LIMIT 1", (token,)).fetchone()
        call_id = row["call_id"] if row else "unknown"

    add_link_event(token=token, call_id=call_id, event_type="clicked")
    await ws_manager.broadcast({
        "type": "link.event",
        "token": token,
        "call_id": call_id,
        "event": "clicked",
        "timestamp": datetime.now(UTC).isoformat(),
    })

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PayEase — Secure Payment</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: #f4f6f9;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      margin: 0;
    }}
    .card {{
      background: #ffffff;
      border-radius: 12px;
      box-shadow: 0 10px 25px rgba(0,0,0,0.08);
      width: 100%;
      max-width: 420px;
      padding: 32px;
      text-align: center;
    }}
    .badge {{
      display: inline-block;
      background: #eff6ff;
      color: #1d4ed8;
      font-size: 12px;
      font-weight: 600;
      padding: 4px 10px;
      border-radius: 20px;
      margin-bottom: 20px;
    }}
    h1 {{
      font-size: 22px;
      color: #1e293b;
      margin-bottom: 8px;
    }}
    p {{
      color: #64748b;
      font-size: 14px;
      margin-bottom: 24px;
      line-height: 1.5;
    }}
    .pay-btn {{
      background: #0284c7;
      color: white;
      border: none;
      padding: 14px 28px;
      font-size: 16px;
      font-weight: 600;
      border-radius: 8px;
      cursor: pointer;
      width: 100%;
      transition: background 0.2s;
    }}
    .pay-btn:hover {{
      background: #0369a1;
    }}
    .success-box {{
      display: none;
      background: #ecfdf5;
      border: 1px solid #10b981;
      color: #065f46;
      border-radius: 8px;
      padding: 16px;
      margin-top: 20px;
      font-weight: 600;
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="badge">⚡ FDE Assignment Demonstration Mock</div>
    <h1>Complete Autopay Recovery</h1>
    <p>This is a simulated Razorpay-style payment portal. Click below to simulate an immediate successful recovery.</p>
    <button class="pay-btn" id="payBtn" onclick="submitPayment()">Pay Now</button>
    <div class="success-box" id="successBox">✓ Payment Successful! Autopay recovered.</div>
  </div>

  <script>
    async function submitPayment() {{
      const btn = document.getElementById('payBtn');
      btn.disabled = true;
      btn.innerText = 'Processing...';

      try {{
        const res = await fetch('/pay/{token}/complete', {{ method: 'POST' }});
        if (res.ok) {{
          btn.style.display = 'none';
          document.getElementById('successBox').style.display = 'block';
        }} else {{
          btn.disabled = false;
          btn.innerText = 'Payment Failed - Try Again';
        }}
      }} catch (e) {{
        btn.disabled = false;
        btn.innerText = 'Error - Try Again';
      }}
    }}
  </script>
</body>
</html>"""
    return html_content


@app.post("/pay/{token}/complete")
async def complete_mock_payment(token: str) -> dict[str, str]:
    """Mark link paid and upgrade call outcome to recovered (via link)."""
    # Find call_id associated with this token
    from src.db import get_conn
    with get_conn() as conn:
        row = conn.execute("SELECT call_id FROM link_events WHERE token = ? LIMIT 1", (token,)).fetchone()
        call_id = row["call_id"] if row else "unknown"

    add_link_event(token=token, call_id=call_id, event_type="paid")

    if call_id != "unknown":
        update_call_record(call_id=call_id, outcome="recovered", note="recovered via link")

    await ws_manager.broadcast({
        "type": "link.event",
        "token": token,
        "call_id": call_id,
        "event": "paid",
        "timestamp": datetime.now(UTC).isoformat(),
    })

    return {"status": "paid", "token": token}


# ── WebSocket Telemetry Stream ────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_telemetry(websocket: WebSocket) -> None:
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keepalive receiver
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
