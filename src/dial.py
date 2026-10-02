"""Outbound dialer — places recovery calls strictly to DEMO_PHONE via LiveKit SIP.

Usage:
    # Dial a specific customer by ID:
    python -m src.dial --customer CUST-001

    # Dial all customers sequentially (waits for room to close between calls):
    python -m src.dial --all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

# Ensure project root is on sys.path when run directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from livekit import api

from src.db import can_dial_customer, mask_phone_number, record_dial_attempt, save_outcome
from src.models import Outcome

load_dotenv()

logger = logging.getLogger("dialer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

CUSTOMERS_PATH = Path(__file__).resolve().parent.parent / "customers.json"
AGENT_NAME = os.environ.get("LIVEKIT_AGENT_NAME", "autopay-recovery")
IST = ZoneInfo("Asia/Kolkata")

# Call window boundaries (IST)
DEFAULT_WINDOW_START_HOUR = int(os.environ.get("CALL_WINDOW_START_HOUR", "9"))
DEFAULT_WINDOW_END_HOUR = int(os.environ.get("CALL_WINDOW_END_HOUR", "20"))


def validate_demo_phone(phone: str | None) -> str:
    """Validate that DEMO_PHONE exists and matches strict E.164 format."""
    if not phone:
        logger.error(
            "FATAL: DEMO_PHONE is not set in environment. "
            "All outbound calls must route strictly to DEMO_PHONE."
        )
        sys.exit(1)

    phone_clean = phone.strip()
    if not re.match(r"^\+[1-9]\d{1,14}$", phone_clean):
        logger.error(
            "FATAL: DEMO_PHONE '%s' is not a valid E.164 phone number (e.g. +919876543210).",
            phone_clean,
        )
        sys.exit(1)

    return phone_clean


def check_call_window(demo_override: bool = False) -> tuple[bool, str]:
    """Verify that current time is within the allowed calling window (default 09:00 - 20:00 IST)."""
    now_ist = datetime.now(IST)
    current_hour = now_ist.hour
    current_minute = now_ist.minute

    if demo_override:
        return True, "DEMO_OVERRIDE active"

    if not (DEFAULT_WINDOW_START_HOUR <= current_hour < DEFAULT_WINDOW_END_HOUR):
        return (
            False,
            f"Current time ({now_ist.strftime('%H:%M')} IST) is outside the permitted calling window "
            f"({DEFAULT_WINDOW_START_HOUR:02d}:00 - {DEFAULT_WINDOW_END_HOUR:02d}:00 IST). "
            "Set DEMO_OVERRIDE=true to bypass during development/testing.",
        )

    return True, "Within calling window"


def print_demo_override_banner(masked_demo_phone: str) -> None:
    """Display prominent warning banner when DEMO_OVERRIDE is enabled."""
    banner = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                          ⚠️  DEMO OVERRIDE ACTIVE                            ║
║  • Call window ({DEFAULT_WINDOW_START_HOUR:02d}:00 - {DEFAULT_WINDOW_END_HOUR:02d}:00 IST) check: BYPASSED                     ║
║  • 1-attempt/customer/day limit check: BYPASSED                             ║
║  • Destination: ALL calls route strictly to DEMO_PHONE ({masked_demo_phone:<14})  ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
    print(banner, flush=True)


def load_customers(path: Path = CUSTOMERS_PATH) -> list[dict]:
    """Load and return customer records from JSON file."""
    if not path.exists():
        logger.error("Customers file not found at %s", path)
        sys.exit(1)
    with open(path) as f:
        customers = json.load(f)
    logger.info("Loaded %d customer records from %s", len(customers), path)
    return customers


async def wait_for_room_closed(lkapi: api.LiveKitAPI, room_name: str, timeout: float = 600.0) -> None:
    """Wait in batch mode until the room finishes and closes before dialing the next customer."""
    logger.info("Waiting for room %s to close before next call...", room_name)
    start_time = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start_time < timeout:
        try:
            res = await lkapi.room.list_participants(api.ListParticipantsRequest(room=room_name))
            if len(res.participants) == 0:
                logger.info("Room %s has no remaining participants.", room_name)
                return
        except Exception:
            # Room no longer exists on LiveKit server
            logger.info("Room %s is closed.", room_name)
            return
        await asyncio.sleep(2.0)
    logger.warning("Timeout (%ss) reached waiting for room %s to close.", timeout, room_name)


async def dial_customer(
    customer: dict,
    lkapi: api.LiveKitAPI,
    sip_trunk_id: str,
    caller_number: str,
    demo_phone: str,
    demo_override: bool = False,
) -> str | None:
    """Place an outbound call for a single customer strictly to DEMO_PHONE.

    Args:
        customer: Customer record dict.
        lkapi: Authenticated LiveKit API client.
        sip_trunk_id: ID of the outbound SIP trunk.
        caller_number: Verified Twilio caller ID.
        demo_phone: Validated E.164 destination phone number.
        demo_override: If True, bypasses 1-attempt/day limits.

    Returns:
        The room name if call was initiated, or None if skipped/blocked.
    """
    cid = customer["id"]

    # 1. Enforce DND and daily frequency limits
    can_dial, reason = can_dial_customer(cid, demo_override=demo_override)
    if not can_dial:
        logger.warning("Skipping customer %s: %s", cid, reason)
        return None

    masked_target = mask_phone_number(demo_phone)
    masked_caller = mask_phone_number(caller_number)
    room_name = f"recovery-{cid}-{uuid4().hex[:8]}"

    logger.info(
        "Initiating outbound call: customer=%s name='%s' target=%s caller=%s room=%s",
        cid,
        customer.get("name", "Unknown"),
        masked_target,
        masked_caller,
        room_name,
    )

    # 2. Record dial start in customer state
    record_dial_attempt(cid, outcome="calling")

    # 3. Explicitly create room with metadata = {"customer_id": cid} only
    metadata_json = json.dumps({"customer_id": cid})
    await lkapi.room.create_room(
        api.CreateRoomRequest(
            name=room_name,
            metadata=metadata_json,
            empty_timeout=300,
        )
    )

    # 4. Dispatch the agent worker to the room with metadata = {"customer_id": cid} only
    await lkapi.agent_dispatch.create_dispatch(
        api.CreateAgentDispatchRequest(
            agent_name=AGENT_NAME,
            room=room_name,
            metadata=metadata_json,
        )
    )

    # 5. Create SIP participant (routes strictly to DEMO_PHONE, waits until answered)
    try:
        sip_participant = await lkapi.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                sip_trunk_id=sip_trunk_id,
                sip_call_to=demo_phone,
                sip_number=caller_number,
                room_name=room_name,
                participant_identity=f"sip-{cid}",
                participant_name=customer.get("name", "Customer"),
                wait_until_answered=True,
                play_dialtone=False,
            )
        )
        logger.info(
            "SIP call answered and connected: participant_id=%s identity=%s",
            getattr(sip_participant, "participant_id", "N/A"),
            getattr(sip_participant, "participant_identity", "N/A"),
        )
        return room_name

    except Exception as e:
        logger.warning(
            "SIP call failed or was not answered for customer %s (room %s): %s",
            cid,
            room_name,
            e,
        )
        # Record outcome no_answer on failure/no-pickup
        save_outcome(
            Outcome(
                customer_id=cid,
                disposition="no_answer",
                notes=f"SIP call not answered / disconnected: {e}",
                duration_sec=0.0,
                timestamp=datetime.now(UTC),
            )
        )
        return None


async def main() -> None:
    parser = argparse.ArgumentParser(description="Outbound autopay recovery dialer (strictly routes to DEMO_PHONE)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--customer",
        type=str,
        help="Dial a specific customer by ID (e.g. CUST-001)",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Dial all customers sequentially, waiting for each room to close before the next",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=5.0,
        help="Seconds to wait between calls in --all mode (default: 5.0)",
    )
    args = parser.parse_args()

    # 1. Validate DEMO_PHONE (strict E.164, mandatory)
    raw_demo_phone = os.environ.get("DEMO_PHONE")
    demo_phone = validate_demo_phone(raw_demo_phone)
    masked_demo_phone = mask_phone_number(demo_phone)

    # 2. Check DEMO_OVERRIDE flag
    demo_override = os.environ.get("DEMO_OVERRIDE", "").lower() in ("true", "1", "yes")
    if demo_override:
        print_demo_override_banner(masked_demo_phone)
    else:
        # Enforce IST call-window guard
        in_window, window_reason = check_call_window(demo_override=False)
        if not in_window:
            logger.error("CALL WINDOW GUARD: %s", window_reason)
            sys.exit(1)
        logger.info("Call window guard check passed: %s", window_reason)

    # 3. Validate LiveKit and Twilio credentials
    for var in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "SIP_TRUNK_ID"):
        if not os.environ.get(var):
            logger.error("Missing required environment variable: %s", var)
            sys.exit(1)

    caller_number = (
        os.environ.get("TWILIO_NUMBER")
        or os.environ.get("TWILIO_PHONE_NUMBER")
        or os.environ.get("SIP_CALLER_NUMBER")
    )
    if not caller_number:
        logger.error("Missing required environment variable: TWILIO_NUMBER (or TWILIO_PHONE_NUMBER)")
        sys.exit(1)

    sip_trunk_id = os.environ["SIP_TRUNK_ID"]

    lkapi = api.LiveKitAPI(
        url=os.environ["LIVEKIT_URL"],
        api_key=os.environ["LIVEKIT_API_KEY"],
        api_secret=os.environ["LIVEKIT_API_SECRET"],
    )

    customers = load_customers()

    try:
        if args.customer:
            matches = [c for c in customers if c["id"] == args.customer]
            if not matches:
                logger.error("Customer %s not found in customers.json", args.customer)
                sys.exit(1)
            target_customer = matches[0]
            await dial_customer(
                customer=target_customer,
                lkapi=lkapi,
                sip_trunk_id=sip_trunk_id,
                caller_number=caller_number,
                demo_phone=demo_phone,
                demo_override=demo_override,
            )

        elif args.all:
            logger.info("Starting sequential dial loop for %d customers...", len(customers))
            for i, customer in enumerate(customers):
                logger.info("--- [%d/%d] Processing customer %s ---", i + 1, len(customers), customer["id"])
                room_name = await dial_customer(
                    customer=customer,
                    lkapi=lkapi,
                    sip_trunk_id=sip_trunk_id,
                    caller_number=caller_number,
                    demo_phone=demo_phone,
                    demo_override=demo_override,
                )

                # Wait for room to close before moving to next customer
                if room_name:
                    await wait_for_room_closed(lkapi, room_name)

                if i < len(customers) - 1:
                    logger.info("Waiting %.1fs delay before processing next customer...", args.delay)
                    await asyncio.sleep(args.delay)

        logger.info("Dialer execution completed.")

    finally:
        await lkapi.aclose()


if __name__ == "__main__":
    asyncio.run(main())
