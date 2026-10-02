"""LiveKit agent worker for autopay recovery calls.

Wires together: Deepgram STT → LangGraph brain (via LLMAdapter) → ElevenLabs TTS.
Registers as agent_name="autopay-recovery" for explicit dispatch from dial.py.
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

from src.db import get_conn, get_outcomes, save_outcome
from src.graph import build_graph
from src.llm import get_llm_with_fallbacks
from src.models import Outcome
from src.prompts import build_system_prompt
from src.tools import ALL_TOOLS

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


def prewarm(proc: agents.JobProcess) -> None:
    """Pre-load heavyweight models into the warm worker process before any calls arrive."""
    logger.info("Pre-warming Silero VAD and tokenizers in worker process...")
    proc.userdata["vad"] = silero.VAD.load()
    try:
        import tiktoken
        tiktoken.get_encoding("cl100k_base")
    except Exception:
        pass
    logger.info("Worker pre-warmed successfully.")


def _build_session(customer: dict, vad: Any | None = None) -> tuple[AgentSession, Agent]:
    """Construct an AgentSession and Agent for a single call."""
    llm = get_llm_with_fallbacks()
    graph = build_graph(llm=llm, tools=ALL_TOOLS)

    eleven_key = os.environ.get("ELEVEN_API_KEY") or os.environ.get("ELEVENLABS_API_KEY")
    dg_model = os.environ.get("DEEPGRAM_MODEL", "nova-3")
    eleven_model = os.environ.get("ELEVENLABS_MODEL", "eleven_turbo_v2_5")
    eleven_voice = os.environ.get("ELEVENLABS_VOICE_ID", "TX3LPaxmHKxFdv7VOQHJ")
    eleven_encoding = os.environ.get("ELEVENLABS_ENCODING", "pcm_24000")
    stability = float(os.environ.get("ELEVENLABS_STABILITY", "0.75"))
    similarity = float(os.environ.get("ELEVENLABS_SIMILARITY", "0.85"))

    if vad is None:
        vad = silero.VAD.load()

    session = AgentSession(
        stt=deepgram.STT(model=dg_model),
        llm=lk_langchain.LLMAdapter(graph=graph),
        tts=elevenlabs.TTS(
            model=eleven_model,
            voice_id=eleven_voice,
            encoding=eleven_encoding,
            voice_settings=elevenlabs.VoiceSettings(
                stability=stability,
                similarity_boost=similarity,
            ),
            api_key=eleven_key,
        ),
        vad=vad,
    )

    system_prompt = build_system_prompt(customer)
    agent = Agent(instructions=system_prompt)

    return session, agent


async def entrypoint(ctx: JobContext) -> None:
    """Handle a single outbound call job.

    The customer record is passed via job metadata or room metadata (JSON) by dial.py.
    """
    await ctx.connect()

    # Extract customer context from job metadata, room metadata, or fallback to customers.json
    raw_metadata = ctx.job.metadata or ctx.room.metadata or ""
    customer: dict = {}
    if raw_metadata:
        try:
            customer = json.loads(raw_metadata)
        except json.JSONDecodeError:
            logger.warning("Could not parse JSON from metadata: %s", raw_metadata)

    if not customer.get("id"):
        room_name = ctx.room.name or ""
        logger.info("Attempting customer resolution from room name: %s", room_name)
        customers_file = Path(__file__).resolve().parent.parent / "customers.json"
        if customers_file.exists():
            try:
                with open(customers_file) as f:
                    all_customers = json.load(f)
                for c in all_customers:
                    if c.get("id") and c["id"] in room_name:
                        customer = c
                        logger.info("Resolved customer %s from customers.json", c["id"])
                        break
            except Exception as e:
                logger.error("Failed to load customers.json fallback: %s", e)

    if not customer.get("id"):
        logger.error(
            "No customer data available for job %s, room %s (raw metadata: %r)",
            ctx.job.id,
            ctx.room.name,
            raw_metadata,
        )
        return

    logger.info(
        "Starting recovery call workflow: customer=%s name=%s",
        customer["id"],
        customer.get("name", "unknown"),
    )

    # Pre-build session, LLM, graph, and VAD immediately while the phone is ringing
    vad = ctx.proc.userdata.get("vad")
    session, agent = _build_session(customer, vad=vad)

    transcript_lines: list[str] = []

    @session.on("conversation_item_added")
    def on_item_added(ev: Any) -> None:
        role = getattr(ev.item, "role", "unknown")
        text = getattr(ev.item, "text", "") or getattr(ev.item, "content", "")
        if isinstance(text, list):
            text = " ".join(str(t) for t in text)
        if text:
            logger.info("Transcript [%s]: %s", role, text)
            transcript_lines.append(f"{role}: {text}")

    @session.on("user_speech_committed")
    def on_user_speech(ev: Any) -> None:
        text = getattr(ev, "text", "") or getattr(ev, "content", "")
        if text:
            logger.info(">>> Customer spoke: %s", text)

    @session.on("agent_speech_committed")
    def on_agent_speech(ev: Any) -> None:
        text = getattr(ev, "text", "") or getattr(ev, "content", "")
        if text:
            logger.info("<<< Agent spoke: %s", text)

    @session.on("close")
    def on_close(ev: Any) -> None:
        logger.info("Session closed: reason=%s", getattr(ev, "reason", "unknown"))
        existing = get_outcomes(customer["id"])
        full_transcript = "\n".join(transcript_lines)
        if not existing:
            save_outcome(
                Outcome(
                    customer_id=customer["id"],
                    disposition="refused",
                    notes="Call ended before completion",
                    transcript=full_transcript,
                )
            )
        elif full_transcript:
            try:
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE outcomes SET transcript = ? WHERE id = ?",
                        (full_transcript, existing[0]["id"]),
                    )
            except Exception as e:
                logger.warning("Failed to save transcript: %s", e)

    # Wait for the customer to answer the ringing phone
    logger.info("Waiting for customer to answer the phone...")
    try:
        participant = await asyncio.wait_for(ctx.wait_for_participant(), timeout=45.0)
        logger.info(
            "Customer answered! Participant connected: %s (kind=%s)",
            participant.identity,
            participant.kind,
        )
    except TimeoutError:
        logger.warning("Call timed out waiting for customer to answer (45s)")
        save_outcome(
            Outcome(
                customer_id=customer["id"],
                disposition="no_answer",
                notes="No answer after 45s ringing",
            )
        )
        return
    except Exception as e:
        logger.warning("Call disconnected before answer: %s", e)
        save_outcome(
            Outcome(
                customer_id=customer["id"],
                disposition="no_answer",
                notes=f"Call disconnected before answer: {e}",
            )
        )
        return

    # Start audio session with the answering participant
    await session.start(
        agent=agent,
        room=ctx.room,
    )

    # Short pause to let cellular audio pipeline calibrate
    await asyncio.sleep(0.5)

    # Greet proactively with allow_interruptions=False so line noise doesn't swallow greeting
    company_name = os.environ.get("COMPANY_NAME", "PayEase")
    greeting = (
        f"Hello, this is an AI assistant calling from {company_name}. "
        f"Am I speaking with {customer.get('name', 'the account holder')}?"
    )
    logger.info("Speaking greeting: %s", greeting)
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
