"""LiveKit agent worker for autopay recovery calls.

Wires together: Deepgram STT (tuned endpointing) → LangGraph brain (via LLMAdapter)
→ TTS Spoken Sanitizer → ElevenLabs TTS.
Registers as agent_name="autopay-recovery" for explicit dispatch from dial.py / API.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path when run directly (python src/agent.py dev)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentSession, JobContext
from livekit.plugins import deepgram, elevenlabs, silero
from livekit.plugins import langchain as lk_langchain

import re
import requests
from langchain_core.messages import ToolMessage, ToolMessageChunk

from src.graph import build_graph
from src.guardrails import (
    check_duration_limit,
    detect_card_or_credentials,
    detect_dispute_or_escalation,
    detect_do_not_call,
    detect_prompt_injection,
    detect_wrong_party,
    redact_pii_for_transcript,
    shield_unverified_output,
)
from src.llm import get_llm_with_fallbacks
from src.prompts import build_system_prompt
from src.sanitizer import tts_sanitizer_transform
from src.tools import CallState, make_tools

load_dotenv()

logger = logging.getLogger("agent")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "secret_internal_token_change_me")


def _post_internal_event(call_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """Send telemetry or turn event to FastAPI backend via internal endpoint."""
    url = f"{API_BASE_URL}/internal/events"
    headers = {
        "X-Internal-Secret": INTERNAL_SECRET,
        "Content-Type": "application/json",
    }
    body = {
        "call_id": call_id,
        "event_type": event_type,
        "payload": payload,
    }
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=2.0)
        if resp.status_code != 200:
            logger.debug("Internal event %s returned HTTP %s", event_type, resp.status_code)
    except Exception as e:
        logger.debug("Failed to post internal event %s: %s", event_type, e)


def _send_sms_via_api(
    call_id: str,
    customer_id: str,
    first_name: str,
    amount: float,
    phone_number: str | None = None,
) -> dict[str, Any]:
    """Request FastAPI backend to dispatch payment link SMS, falling back to direct dispatch if API is down."""
    url = f"{API_BASE_URL}/internal/sms"
    headers = {
        "X-Internal-Secret": INTERNAL_SECRET,
        "Content-Type": "application/json",
    }
    body = {
        "call_id": call_id,
        "customer_id": customer_id,
        "first_name": first_name,
        "amount": amount,
        "phone_number": phone_number,
    }
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=5.0)
        if resp.status_code == 200:
            return resp.json()
        logger.warning("Internal SMS dispatch returned HTTP %s: %s", resp.status_code, resp.text)
    except Exception as e:
        logger.info("Internal SMS endpoint unreachable (%s), falling back to in-process dispatch", e)

    # In-process direct fallback using send_payment_link_sms_sync
    try:
        from src.sms import send_payment_link_sms_sync
        return send_payment_link_sms_sync(call_id, customer_id, first_name, amount, to_phone=phone_number)
    except Exception as direct_err:
        logger.error("In-process SMS dispatch failed: %s", direct_err)
        return {"status": "error", "error": str(direct_err)}


def prewarm(proc: agents.JobProcess) -> None:
    """Pre-load heavyweight models into the warm worker process before calls arrive."""
    logger.info("Pre-warming Silero VAD in worker process...")
    proc.userdata["vad"] = silero.VAD.load()
    try:
        import tiktoken
        tiktoken.get_encoding("cl100k_base")
    except Exception:
        pass
    logger.info("Worker pre-warmed successfully.")


class SafeLangGraphStream(lk_langchain.langgraph.LangGraphStream):
    """Filters out ToolMessages and non-chatbot nodes so internal tool returns are never streamed as spoken assistant chunks."""

    async def _run(self) -> None:
        state = self._chat_ctx_to_state()
        try:
            aiter = self._graph.astream(
                state,
                self._config,
                context=self._context,
                stream_mode=self._stream_mode,
                subgraphs=self._subgraphs,
            )
        except TypeError:
            aiter = self._graph.astream(
                state,
                self._config,
                stream_mode=self._stream_mode,
            )

        async for item in aiter:
            if isinstance(item, tuple) and len(item) == 2:
                token, meta = item
                # NEVER yield tool messages or chunks from the tools node as assistant speech!
                if isinstance(token, (ToolMessage, ToolMessageChunk)) or getattr(token, "type", None) == "tool":
                    continue
                if isinstance(meta, dict) and meta.get("langgraph_node") == "tools":
                    continue
                token_like = lk_langchain.langgraph._extract_message_chunk(item)
                if token_like is None or isinstance(token_like, (ToolMessage, ToolMessageChunk)) or getattr(token_like, "type", None) == "tool":
                    continue
                chat_chunk = lk_langchain.langgraph._to_chat_chunk(token_like)
                if chat_chunk:
                    self._event_ch.send_nowait(chat_chunk)
            else:
                token_like = lk_langchain.langgraph._extract_message_chunk(item)
                if token_like is None or isinstance(token_like, (ToolMessage, ToolMessageChunk)) or getattr(token_like, "type", None) == "tool":
                    continue
                chat_chunk = lk_langchain.langgraph._to_chat_chunk(token_like)
                if chat_chunk:
                    self._event_ch.send_nowait(chat_chunk)


class SafeLLMAdapter(lk_langchain.LLMAdapter):
    """LangGraph LLMAdapter that uses SafeLangGraphStream to completely isolate tool outputs from spoken speech."""

    def chat(self, *, chat_ctx, tools=None, conn_options=None, **kwargs):
        return SafeLangGraphStream(
            self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            graph=self._graph,
            conn_options=conn_options or lk_langchain.langgraph.DEFAULT_API_CONNECT_OPTIONS,
            config=self._config,
            context=self._context,
            subgraphs=self._subgraphs,
            stream_mode=self._stream_mode,
        )


def _build_session(
    customer: dict,
    state: CallState,
    emit_fn: Any = None,
    vad: Any | None = None,
    phone_number: str | None = None,
) -> tuple[AgentSession, Agent]:
    """Construct an AgentSession and Agent for a single call."""
    llm = get_llm_with_fallbacks()
    tools = make_tools(
        state,
        emit_event_fn=emit_fn,
        send_sms_fn=lambda cid, fname, amt: _send_sms_via_api(state.call_id, cid, fname, amt, phone_number=phone_number),
    )
    graph = build_graph(llm=llm, tools=tools)

    # 1. ElevenLabs configuration strictly from env
    eleven_key = os.environ.get("ELEVEN_API_KEY") or os.environ.get("ELEVENLABS_API_KEY")
    eleven_model = os.environ.get("ELEVEN_MODEL") or os.environ.get("ELEVENLABS_MODEL", "eleven_turbo_v2_5")
    eleven_voice = os.environ.get("ELEVEN_VOICE_ID") or os.environ.get("ELEVENLABS_VOICE_ID", "TX3LPaxmHKxFdv7VOQHJ")
    eleven_encoding = os.environ.get("ELEVENLABS_ENCODING", "pcm_24000")
    stability = float(os.environ.get("ELEVEN_STABILITY") or os.environ.get("ELEVENLABS_STABILITY", "0.50"))
    similarity = float(os.environ.get("ELEVEN_SIMILARITY") or os.environ.get("ELEVENLABS_SIMILARITY", "0.75"))
    style = float(os.environ.get("ELEVEN_STYLE", "0.0"))
    speed = float(os.environ.get("ELEVEN_SPEED", "1.0"))

    # 2. Deepgram STT with tuned endpointing for snappy phone turn-taking (300ms default)
    dg_model = os.environ.get("DEEPGRAM_MODEL", "nova-3")
    dg_endpointing = int(os.environ.get("DEEPGRAM_ENDPOINTING_MS", "300"))

    if vad is None:
        vad = silero.VAD.load()

    session = AgentSession(
        stt=deepgram.STT(
            model=dg_model,
            endpointing_ms=dg_endpointing,
        ),
        llm=SafeLLMAdapter(graph=graph),
        tts=elevenlabs.TTS(
            model=eleven_model,
            voice_id=eleven_voice,
            encoding=eleven_encoding,
            voice_settings=elevenlabs.VoiceSettings(
                stability=stability,
                similarity_boost=similarity,
                style=style,
                speed=speed,
                use_speaker_boost=True,
            ),
            api_key=eleven_key,
        ),
        tts_text_transforms=[tts_sanitizer_transform],
        vad=vad,
    )

    system_prompt = build_system_prompt(customer)
    agent = Agent(instructions=system_prompt)

    return session, agent


async def _delayed_disconnect(ctx: JobContext, delay: float = 3.0) -> None:
    """Cleanly disconnect the room after agent finishes speaking its final turn."""
    await asyncio.sleep(delay)
    try:
        await ctx.room.disconnect()
    except Exception as e:
        logger.debug("Delayed disconnect error: %s", e)


async def entrypoint(ctx: JobContext) -> None:
    """Handle a single outbound call job."""
    await ctx.connect()

    # Extract customer context from metadata = {"customer_id": cid}
    raw_metadata = ctx.job.metadata or ctx.room.metadata or ""
    metadata_dict: dict = {}
    if raw_metadata:
        try:
            metadata_dict = json.loads(raw_metadata)
        except json.JSONDecodeError:
            logger.warning("Could not parse JSON from metadata: %s", raw_metadata)

    cid = metadata_dict.get("customer_id") or metadata_dict.get("id")
    customer: dict = {}

    customers_file = Path(__file__).resolve().parent.parent / "customers.json"
    if customers_file.exists():
        try:
            with open(customers_file) as f:
                all_customers = json.load(f)
            if cid:
                for c in all_customers:
                    if c.get("id") == cid:
                        customer = c
                        break
            if not customer:
                room_name = ctx.room.name or ""
                for c in all_customers:
                    if c.get("id") and c["id"] in room_name:
                        customer = c
                        break
        except Exception as e:
            logger.error("Failed to load customers.json: %s", e)

    if not customer and metadata_dict.get("name"):
        customer = metadata_dict

    if not customer.get("id"):
        logger.error("No customer data available for job %s, room %s", ctx.job.id, ctx.room.name)
        return

    call_id = ctx.room.name or f"call-{customer['id']}"
    logger.info("Initializing call session %s for customer: %s (%s)", call_id, customer["id"], customer.get("name", "Unknown"))

    call_state = CallState(
        customer_id=customer["id"],
        customer_record=customer,
        call_id=call_id,
    )

    def _on_event(event_type: str, payload: dict) -> None:
        logger.info("Agent Event [%s]: %s", event_type, payload)
        _post_internal_event(call_id, event_type, payload)

    vad = ctx.proc.userdata.get("vad")
    target_phone = metadata_dict.get("phone_number")
    session, agent = _build_session(customer, call_state, emit_fn=_on_event, vad=vad, phone_number=target_phone)

    transcript_lines: list[str] = []
    seen_turns: set[str] = set()
    call_start_time = asyncio.get_event_loop().time()

    def record_turn(speaker: str, text: str) -> None:
        """Unified turn recording with deduplication and guardrail checking."""
        clean_text = (text or "").strip()
        if speaker == "agent":
            clean_text = re.sub(r"\[INTERNAL[^\]]*\]\s*", "", clean_text)
            clean_text = re.sub(r"Account data:\s*Autopay payment of[^.]*\.\s*", "", clean_text)
            clean_text = re.sub(r"\[[^\]]*\]\s*", "", clean_text).strip()
        if not clean_text:
            return
        dedup_key = f"{speaker}:{clean_text.lower()}"
        if dedup_key in seen_turns:
            return
        seen_turns.add(dedup_key)

        logger.info(">>> [%s] %s", speaker.upper(), clean_text)
        _post_internal_event(call_id, "turn", {"speaker": speaker, "text": clean_text, "is_final": True})

        # Append to in-memory transcript (redacted)
        redacted = redact_pii_for_transcript(clean_text, birth_year=customer.get("birth_year"))
        transcript_lines.append(f"{speaker}: {redacted}")

        if speaker == "customer":
            # Check guardrails on user input
            if detect_do_not_call(clean_text):
                call_state.do_not_call = True
                logger.warning("Guardrail 6 (DND) triggered: customer requested Do Not Call")
                _post_internal_event(call_id, "guardrail.triggered", {"id": 6, "name": "do_not_call", "action": "set_dnd"})
                _post_internal_event(call_id, "state.update", {"customer_id": customer["id"], "do_not_call": True})

            has_creds, cred_type = detect_card_or_credentials(clean_text)
            if has_creds:
                logger.warning("Guardrail 4 (Credentials Blocker) triggered: %s", cred_type)
                _post_internal_event(call_id, "guardrail.triggered", {"id": 4, "name": "card_or_credentials_blocker", "action": "block_and_redirect", "detail": cred_type})

            is_dispute, dispute_reason = detect_dispute_or_escalation(clean_text)
            if is_dispute:
                logger.info("Guardrail 5 (Dispute/Escalate) triggered: %s", dispute_reason)
                _post_internal_event(call_id, "guardrail.triggered", {"id": 5, "name": "dispute_hardship_escalate", "action": "flag_escalation", "detail": dispute_reason})

            if detect_wrong_party(clean_text):
                logger.info("Guardrail 3 (Wrong Party) triggered")
                _post_internal_event(call_id, "guardrail.triggered", {"id": 3, "name": "wrong_party", "action": "end_call"})

            if detect_prompt_injection(clean_text):
                logger.warning("Guardrail 8 (Prompt Injection) blocked adversarial input")
                _post_internal_event(call_id, "guardrail.triggered", {"id": 8, "name": "prompt_injection", "action": "block"})

    @session.on("user_input_transcribed")
    def on_user_transcribed(ev: Any) -> None:
        """Fires on every STT transcript. We forward final transcripts."""
        transcript = getattr(ev, "transcript", "")
        is_final = getattr(ev, "is_final", False)
        if not transcript or not is_final:
            return
        record_turn("customer", transcript)

    @session.on("conversation_item_added")
    def on_item_added(ev: Any) -> None:
        """Fires when any completed message (user or assistant) is committed to chat history."""
        item = getattr(ev, "item", None)
        if item is None:
            return
        role = getattr(item, "role", None)

        # Extract text — item.text_content strips tool markup in v1.8
        text = getattr(item, "text_content", None)
        if text is None:
            text = getattr(item, "raw_text_content", None)
        if text is None:
            content = getattr(item, "content", [])
            if isinstance(content, list):
                text = " ".join(str(c) for c in content if isinstance(c, str))
            else:
                text = str(content) if content else ""

        if not text or not text.strip():
            return

        if role == "assistant":
            record_turn("agent", text)
            # If terminal outcome was reached, schedule clean room disconnect after speaking
            if call_state.is_terminal():
                logger.info("Terminal outcome reached (%s). Closing room in 3s...", call_state.terminal_outcome)
                asyncio.create_task(_delayed_disconnect(ctx, delay=3.0))
        elif role == "user":
            record_turn("customer", text)

    @session.on("close")
    def on_close(ev: Any) -> None:
        reason = getattr(ev, "reason", "unknown")
        logger.info("Call session closed: reason=%s", reason)
        duration = asyncio.get_event_loop().time() - call_start_time
        full_transcript = "\n".join(transcript_lines)

        final_outcome = call_state.terminal_outcome or "declined"
        note = call_state.outcome_note or "Call ended before terminal resolution"

        _post_internal_event(call_id, "call.ended", {
            "customer_id": customer["id"],
            "final_outcome": final_outcome,
            "outcome_note": note,
            "duration_sec": round(duration, 2),
            "transcript": full_transcript,
        })

    # Wait for phone to be answered
    logger.info("Waiting for customer to answer the phone (45s timeout)...")
    try:
        participant = await asyncio.wait_for(ctx.wait_for_participant(), timeout=45.0)
        logger.info("Customer answered: %s (kind=%s)", participant.identity, participant.kind)
    except TimeoutError:
        logger.warning("Call timed out waiting for customer to answer")
        _post_internal_event(call_id, "call.ended", {
            "customer_id": customer["id"],
            "final_outcome": "no_answer",
            "outcome_note": "No answer after 45s ringing",
            "duration_sec": 0,
            "transcript": "",
        })
        return
    except Exception as e:
        logger.warning("Call disconnected before answer: %s", e)
        _post_internal_event(call_id, "call.ended", {
            "customer_id": customer["id"],
            "final_outcome": "no_answer",
            "outcome_note": f"Disconnected before answer: {e}",
            "duration_sec": 0,
            "transcript": "",
        })
        return

    # Start audio session with the answering participant
    await session.start(agent=agent, room=ctx.room)
    await asyncio.sleep(0.5)

    # First turn greeting with mandatory AI & recording disclosure
    company_name = os.environ.get("COMPANY_NAME", "PayEase")
    greeting = (
        f"Hello, this is Aanya, an automated AI assistant calling from {company_name} on a recorded line. "
        f"Am I speaking with {customer.get('name', 'the account holder')}?"
    )
    logger.info("Speaking first turn greeting: %s", greeting)
    _post_internal_event(call_id, "guardrail.triggered", {"id": 1, "name": "ai_and_recording_disclosure", "action": "spoken_turn_one"})
    record_turn("agent", greeting)
    await session.say(greeting, allow_interruptions=False)


if __name__ == "__main__":
    agent_name = os.environ.get("LIVEKIT_AGENT_NAME", "autopay-recovery")
    agents.cli.run_app(
        agents.WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            agent_name=agent_name,
            num_idle_processes=1,
            initialize_process_timeout=60.0,
        ),
    )
