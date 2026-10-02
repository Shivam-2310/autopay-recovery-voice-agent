"""Outbound dialer — reads customers.json and places calls via LiveKit SIP.

Usage:
    # Dial a single test number (overrides customer phone):
    python -m src.dial --phone +1XXXXXXXXXX

    # Dial all customers from the file:
    python -m src.dial --all

    # Dial a specific customer by ID:
    python -m src.dial --customer CUST-001
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from uuid import uuid4

# Ensure project root is on sys.path when run directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from livekit import api

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

CUSTOMERS_PATH = Path(__file__).resolve().parent.parent / "customers.json"
AGENT_NAME = os.environ.get("LIVEKIT_AGENT_NAME", "autopay-recovery")


def load_customers(path: Path = CUSTOMERS_PATH) -> list[dict]:
    """Load and return customer records from JSON file."""
    with open(path) as f:
        customers = json.load(f)
    logger.info("Loaded %d customers from %s", len(customers), path)
    return customers


async def dial_customer(
    customer: dict,
    lkapi: api.LiveKitAPI,
    sip_trunk_id: str,
    phone_override: str | None = None,
) -> str:
    """Place an outbound call to a single customer.

    Args:
        customer: Customer record dict.
        lkapi: Authenticated LiveKit API client.
        sip_trunk_id: ID of the outbound SIP trunk.
        phone_override: If set, dial this number instead of customer's phone.

    Returns:
        The room name used for this call.
    """
    phone = phone_override or customer["phone"]
    # Normalize to E.164 format
    clean_phone = "".join(c for c in phone if c.isdigit() or c == "+")
    if not clean_phone.startswith("+"):
        if len(clean_phone) == 10 and clean_phone[0] in "6789":
            clean_phone = f"+91{clean_phone}"
        else:
            clean_phone = f"+{clean_phone}"
    phone = clean_phone
    masked_phone = (
        phone[:4] + "*" * (len(phone) - 6) + phone[-2:]
        if len(phone) >= 7
        else "***"
    )
    room_name = f"recovery-{customer['id']}-{uuid4().hex[:8]}"

    logger.info(
        "Dialing customer=%s phone=%s room=%s",
        customer["id"],
        masked_phone,
        room_name,
    )

    # 1. Explicitly create the room with customer metadata
    await lkapi.room.create_room(
        api.CreateRoomRequest(
            name=room_name,
            metadata=json.dumps(customer),
            empty_timeout=300,
        )
    )

    # 2. Dispatch the agent to the room
    await lkapi.agent_dispatch.create_dispatch(
        api.CreateAgentDispatchRequest(
            agent_name=AGENT_NAME,
            room=room_name,
            metadata=json.dumps(customer),
        )
    )

    # 3. Create the SIP participant (places the actual call)
    caller_number = (
        os.environ.get("TWILIO_PHONE_NUMBER")
        or os.environ.get("SIP_CALLER_NUMBER")
    )
    if not caller_number:
        logger.error(
            "Missing caller phone number. Please set TWILIO_PHONE_NUMBER or SIP_CALLER_NUMBER in .env"
        )
        return ""

    sip_participant = await lkapi.sip.create_sip_participant(
        api.CreateSIPParticipantRequest(
            sip_trunk_id=sip_trunk_id,
            sip_call_to=phone,
            sip_number=caller_number,
            room_name=room_name,
            participant_identity=f"sip-{customer['id']}",
            participant_name=customer.get("name", "Customer"),
            play_dialtone=True,
        )
    )
    logger.info(
        "SIP participant created: id=%s identity=%s",
        getattr(sip_participant, "participant_id", "N/A"),
        getattr(sip_participant, "participant_identity", "N/A"),
    )

    logger.info("Call placed: customer=%s room=%s", customer["id"], room_name)
    return room_name


async def main() -> None:
    parser = argparse.ArgumentParser(description="Outbound autopay recovery dialer")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--phone",
        type=str,
        help="Override phone number — dial first customer to this number",
    )
    group.add_argument(
        "--customer",
        type=str,
        help="Dial a specific customer by ID (e.g. CUST-001)",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Dial all customers sequentially",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=5.0,
        help="Seconds to wait between calls in --all mode (default: 5)",
    )
    args = parser.parse_args()

    # Validate env
    for var in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "SIP_TRUNK_ID"):
        if not os.environ.get(var):
            logger.error("Missing required env var: %s", var)
            sys.exit(1)

    if not (os.environ.get("TWILIO_PHONE_NUMBER") or os.environ.get("SIP_CALLER_NUMBER")):
        logger.error("Missing required env var: TWILIO_PHONE_NUMBER (or SIP_CALLER_NUMBER)")
        sys.exit(1)

    sip_trunk_id = os.environ["SIP_TRUNK_ID"]
    lkapi = api.LiveKitAPI(
        url=os.environ["LIVEKIT_URL"],
        api_key=os.environ["LIVEKIT_API_KEY"],
        api_secret=os.environ["LIVEKIT_API_SECRET"],
    )

    customers = load_customers()

    try:
        if args.phone:
            # Dial first customer to the override number
            customer = customers[0]
            await dial_customer(customer, lkapi, sip_trunk_id, phone_override=args.phone)

        elif args.customer:
            # Find and dial a specific customer
            matches = [c for c in customers if c["id"] == args.customer]
            if not matches:
                logger.error("Customer %s not found in customers.json", args.customer)
                sys.exit(1)
            await dial_customer(matches[0], lkapi, sip_trunk_id)

        elif args.all:
            # Dial all customers sequentially
            for i, customer in enumerate(customers):
                await dial_customer(customer, lkapi, sip_trunk_id)
                if i < len(customers) - 1:
                    logger.info("Waiting %.1fs before next call...", args.delay)
                    await asyncio.sleep(args.delay)

        logger.info("Dialing complete.")
    finally:
        await lkapi.aclose()


if __name__ == "__main__":
    asyncio.run(main())
