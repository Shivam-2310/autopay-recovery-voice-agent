"""SMS dispatch and tracking service via Twilio Messages API or mock."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from datetime import UTC, datetime
from typing import Any

from src.db import add_link_event, add_message, mask_phone_number, update_message_status

logger = logging.getLogger("sms")


def generate_payment_token() -> str:
    """Generate a URL-safe random token for the mock payment portal."""
    return secrets.token_urlsafe(16)


async def send_payment_link_sms(
    call_id: str,
    customer_id: str,
    first_name: str,
    amount: float,
) -> dict[str, Any]:
    """Send payment link via Twilio SMS to DEMO_PHONE (or simulate if mock mode)."""
    demo_phone = os.environ.get("DEMO_PHONE", "+919876543210")
    masked_to = mask_phone_number(demo_phone)
    sms_mode = os.environ.get("SMS_MODE", "mock").lower()
    public_base_url = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

    token = generate_payment_token()
    pay_url = f"{public_base_url}/pay/{token}"
    body = f"Hi {first_name}, here is your secure link to complete your payment of Rs {int(amount)}: {pay_url}. PayEase"

    # 1. Record link created
    add_link_event(token=token, call_id=call_id, event_type="created")

    # 2. Check mode: Twilio vs Mock
    if sms_mode == "twilio":
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
        from_number = os.environ.get("TWILIO_NUMBER") or os.environ.get("TWILIO_PHONE_NUMBER")

        if not (account_sid and auth_token and from_number):
            logger.warning("Twilio credentials missing. Falling back to mock SMS mode.")
            sms_mode = "mock"
        else:
            try:
                from twilio.rest import Client
                client = Client(account_sid, auth_token)

                callback_url = f"{public_base_url}/api/twilio/status" if os.environ.get("PUBLIC_BASE_URL") else None

                kwargs: dict[str, Any] = {
                    "body": body,
                    "from_": from_number,
                    "to": demo_phone,
                }
                if callback_url:
                    kwargs["status_callback"] = callback_url

                message = client.messages.create(**kwargs)
                logger.info("Twilio SMS dispatched: sid=%s status=%s", message.sid, message.status)

                add_message(
                    call_id=call_id,
                    sid=message.sid,
                    to_masked=masked_to,
                    status=message.status,
                    mode="twilio",
                    error_code=str(message.error_code) if message.error_code else None,
                )
                add_link_event(token=token, call_id=call_id, event_type="sent")

                # If no public callback URL, start background polling
                if not callback_url:
                    asyncio.create_task(_poll_twilio_status(client, message.sid, call_id, token))

                return {
                    "status": "success",
                    "sid": message.sid,
                    "token": token,
                    "url": pay_url,
                    "mode": "twilio",
                    "initial_status": message.status,
                }

            except Exception as e:
                logger.error("Twilio SMS send failed: %s", e)
                error_sid = f"err_{secrets.token_hex(4)}"
                add_message(
                    call_id=call_id,
                    sid=error_sid,
                    to_masked=masked_to,
                    status="failed",
                    mode="twilio",
                    error_code="SEND_FAILED",
                )
                return {
                    "status": "error",
                    "error": str(e),
                    "sid": error_sid,
                    "mode": "twilio",
                }

    # Mock mode (deterministic, simulated lifecycle)
    mock_sid = f"SM_mock_{secrets.token_hex(8)}"
    logger.info("Mock SMS simulated: sid=%s to=%s (url: %s)", mock_sid, masked_to, pay_url)

    add_message(
        call_id=call_id,
        sid=mock_sid,
        to_masked=masked_to,
        status="sent",
        mode="mock",
    )
    add_link_event(token=token, call_id=call_id, event_type="sent")

    # Simulate delivery after 2 seconds
    asyncio.create_task(_simulate_mock_delivery(mock_sid, token, call_id))

    return {
        "status": "success",
        "sid": mock_sid,
        "token": token,
        "url": pay_url,
        "mode": "mock",
        "initial_status": "sent",
    }


async def _simulate_mock_delivery(sid: str, token: str, call_id: str) -> None:
    """Simulate mock SMS delivery event after short delay."""
    await asyncio.sleep(2.0)
    update_message_status(sid=sid, status="delivered")
    add_link_event(token=token, call_id=call_id, event_type="delivered")
    logger.info("Mock SMS delivered: sid=%s", sid)


async def _poll_twilio_status(client: Any, sid: str, call_id: str, token: str, max_duration_sec: int = 120) -> None:
    """Poll Twilio message status resource when webhook URL is not publicly reachable."""
    start_time = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start_time < max_duration_sec:
        await asyncio.sleep(5.0)
        try:
            msg = client.messages(sid).fetch()
            update_message_status(
                sid=sid,
                status=msg.status,
                error_code=str(msg.error_code) if msg.error_code else None,
                error_message=msg.error_message,
            )
            if msg.status == "delivered":
                add_link_event(token=token, call_id=call_id, event_type="delivered")
                break
            if msg.status in ("failed", "undelivered"):
                break
        except Exception as e:
            logger.warning("Error polling Twilio status for %s: %s", sid, e)
            break
