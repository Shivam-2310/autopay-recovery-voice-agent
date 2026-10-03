"""Synthetic customer persona simulator for autopay recovery voice agent.

Simulates 10 diverse customer personas against the real LangGraph tools, prompts,
and guardrails without placing actual telephony calls.

Persona Scenarios:
1.  CUST-001 (Aarav): Cooperative -> verifies birth year, retry succeeds -> recovered
2.  CUST-002 (Priya): Mandate expired -> verifies birth year, retry declined, accepts link -> link_sent
3.  CUST-003 (Rohan): Transaction dispute -> disputes charge -> escalate
4.  CUST-004 (Sneha): Bank timeout -> verifies birth year, retry succeeds -> recovered
5.  CUST-005 (Vikram): Credentials offer -> offers credit card digits -> guardrail blocks -> link_sent
6.  CUST-006 (Ananya): Wrong person -> "You have the wrong number" -> wrong_party
7.  CUST-007 (Karthik): Hardship -> lost job, unable to pay -> escalate
8.  CUST-008 (Meera): Auth failure -> provides wrong birth year twice -> verification_failed
9.  CUST-009 (Arjun): Callback request -> requests callback tomorrow afternoon -> scheduled
10. CUST-010 (Divya): Refusal / DND -> requests Do Not Call -> declined (DND)

Usage:
    python -m src.simulate
    python -m src.simulate --customer CUST-001
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import (
    add_event,
    add_turn,
    create_call_record,
    get_conn,
    init_db,
    set_customer_dnd,
    update_call_record,
)
from src.guardrails import (
    check_turn_one_disclosure,
    detect_card_or_credentials,
    detect_dispute_or_escalation,
    detect_do_not_call,
    detect_prompt_injection,
    detect_wrong_party,
    redact_pii_for_transcript,
    shield_unverified_output,
)
from src.sanitizer import sanitize_tts_text
from src.tools import CallState, make_tools

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("simulator")

CUSTOMERS_FILE = Path(__file__).resolve().parent.parent / "customers.json"


# Define simulation script steps for each persona
PERSONA_SCRIPTS: dict[str, list[dict[str, Any]]] = {
    # 1. Cooperative -> retry recovers
    "CUST-001": [
        {"user": "Yes, this is Aarav speaking. What is this regarding?"},
        {"user": "Sure, my birth year is 1988."},
        {"user": "Yes, please go ahead and retry debiting my HDFC account now."},
    ],
    # 2. Mandate expired -> retry fails -> link sent
    "CUST-002": [
        {"user": "Hello, yes I am Priya Patel."},
        {"user": "My birth year is 1992."},
        {"user": "Oh, my mandate expired? Can you send me a secure payment link by SMS instead?"},
    ],
    # 3. Dispute -> escalated
    "CUST-003": [
        {"user": "Yes, I am Rohan Mehta."},
        {"user": "I already paid this amount yesterday! This is complete fraud, I dispute this charge!"},
    ],
    # 4. Bank timeout -> retry recovers
    "CUST-004": [
        {"user": "Yes, Sneha here."},
        {"user": "I was born in 1995."},
        {"user": "Yes, please retry the payment through Kotak Bank."},
    ],
    # 5. Offers credit card number -> guardrail blocks -> link sent
    "CUST-005": [
        {"user": "Yes, Vikram speaking."},
        {"user": "My year of birth is 1982."},
        {"user": "Can I just give you my card number? It is 4532 1234 5678 9012 with CVV 453."},
        {"user": "Okay, please send the payment link to my phone."},
    ],
    # 6. Wrong person -> end_call
    "CUST-006": [
        {"user": "You have the wrong number. There is no Ananya here."},
    ],
    # 7. Financial hardship -> escalated
    "CUST-007": [
        {"user": "Yes, this is Karthik."},
        {"user": "1987."},
        {"user": "I am facing severe financial hardship because I lost my job last month. I cannot pay."},
    ],
    # 8. Auth failure -> verification_failed
    "CUST-008": [
        {"user": "Yes, speaking."},
        {"user": "Umm, I think it was 1999."},
        {"user": "Wait, let me try again... 1975."},
    ],
    # 9. Callback requested -> scheduled
    "CUST-009": [
        {"user": "Yes, Arjun here."},
        {"user": "My birth year is 1989."},
        {"user": "I am driving right now. Can you please call me back tomorrow at 3 PM?"},
    ],
    # 10. Refusal / DND -> declined
    "CUST-010": [
        {"user": "Yes, Divya here."},
        {"user": "I am not paying this. Stop calling me and remove my number from your list, put me on DND!"},
    ],
}


def run_persona_simulation(customer: dict[str, Any]) -> dict[str, Any]:
    """Execute a single customer persona simulation end-to-end against real tools and guardrails."""
    cid = customer["id"]
    call_id = f"sim-{cid}-{datetime.now(UTC).strftime('%H%M%S')}"

    # Initialize per-call state
    state = CallState(
        customer_id=cid,
        customer_record=customer,
        call_id=call_id,
    )

    events: list[dict[str, Any]] = []

    def _emit(event_type: str, payload: dict[str, Any]) -> None:
        events.append({"event_type": event_type, "payload": payload, "ts": datetime.now(UTC).isoformat()})
        add_event(call_id=call_id, event_type=event_type, payload=payload)

    def _sim_send_sms(cid: str, fname: str, amt: float) -> dict[str, Any]:
        """Dispatch SMS payment link strictly to DEMO_PHONE loaded from .env."""
        import asyncio
        from src.sms import send_payment_link_sms
        try:
            return asyncio.run(send_payment_link_sms(call_id, cid, fname, amt))
        except Exception as e:
            logger.error("Simulation SMS dispatch error: %s", e)
            return {"status": "error", "error": str(e)}

    # Instantiate real gated tools, routing SMS strictly to DEMO_PHONE loaded from .env
    tools_list = make_tools(state, emit_event_fn=_emit, send_sms_fn=_sim_send_sms)
    tools = {t.name: t for t in tools_list}

    # Create call record in DB with source='simulated'
    create_call_record(
        call_id=call_id,
        customer_id=cid,
        room_name=call_id,
        source="simulated",
        voice_id="TX3LPaxmHKxFdv7VOQHJ",
        llm_provider="simulator",
    )

    transcript: list[str] = []

    # Turn 1: Spoken greeting with mandatory AI & recording disclosure
    company = os.environ.get("COMPANY_NAME", "PayEase")
    turn_one_text = (
        f"Hello, this is Aanya, an automated AI assistant calling from {company} on a recorded line. "
        f"Am I speaking with {customer['name']}?"
    )
    turn_one_sanitized = sanitize_tts_text(turn_one_text)
    disclosure_ok, _ = check_turn_one_disclosure(turn_one_sanitized)
    assert disclosure_ok, "Guardrail 1 violation: AI and recording disclosure missing"

    add_turn(call_id=call_id, speaker="agent", text=turn_one_sanitized, is_final=True)
    transcript.append(f"agent: {turn_one_sanitized}")

    # Process scripted customer turns
    script = PERSONA_SCRIPTS.get(cid, [])

    for step in script:
        if state.is_terminal():
            break

        user_raw = step["user"]
        # Check Guardrail 8: Prompt Injection
        if detect_prompt_injection(user_raw):
            _emit("guardrail.triggered", {"id": 8, "name": "prompt_injection", "action": "block"})
            agent_reply = "I am only authorized to assist with your PayEase autopay recovery."
            add_turn(call_id=call_id, speaker="agent", text=agent_reply, is_final=True)
            transcript.append(f"agent: {agent_reply}")
            continue

        # Check Guardrail 6: DND
        if detect_do_not_call(user_raw):
            state.do_not_call = True
            set_customer_dnd(cid)
            tools["end_call"].invoke({"outcome": "declined", "note": "Customer requested Do Not Call"})
            _emit("guardrail.triggered", {"id": 6, "name": "do_not_call", "action": "set_dnd"})
            agent_reply = "Understood. I have recorded your request and removed your number from our calling list. Goodbye."
            add_turn(call_id=call_id, speaker="agent", text=agent_reply, is_final=True)
            transcript.append(f"agent: {agent_reply}")
            break

        # Check Guardrail 3: Wrong Party
        if detect_wrong_party(user_raw):
            tools["end_call"].invoke({"outcome": "wrong_party", "note": "Wrong party answered"})
            _emit("guardrail.triggered", {"id": 3, "name": "wrong_party", "action": "end_call"})
            agent_reply = "My apologies for the confusion. I will update our records. Have a good day."
            add_turn(call_id=call_id, speaker="agent", text=agent_reply, is_final=True)
            transcript.append(f"agent: {agent_reply}")
            break

        # Check Guardrail 5: Dispute or Escalation
        is_dispute, disp_reason = detect_dispute_or_escalation(user_raw)
        if is_dispute:
            tools["escalate"].invoke({"reason": disp_reason})
            _emit("guardrail.triggered", {"id": 5, "name": "dispute_hardship_escalate", "action": "escalate", "detail": disp_reason})
            agent_reply = "I understand your concern. I have flagged this account for our senior dispute team to review and contact you. Thank you."
            add_turn(call_id=call_id, speaker="agent", text=agent_reply, is_final=True)
            transcript.append(f"agent: {agent_reply}")
            break

        # Check Guardrail 4: Card / CVV credentials blocker
        has_card, card_type = detect_card_or_credentials(user_raw)
        if has_card:
            _emit("guardrail.triggered", {"id": 4, "name": "card_or_credentials_blocker", "action": "redirect_to_link", "detail": card_type})
            agent_reply = "For your security, I cannot accept card numbers or PINs over the phone. I can send a secure payment link via SMS instead."
            add_turn(call_id=call_id, speaker="agent", text=agent_reply, is_final=True)
            transcript.append(f"agent: {agent_reply}")
            # Redact before transcript storage
            user_redacted = redact_pii_for_transcript(user_raw, birth_year=customer.get("birth_year"))
            add_turn(call_id=call_id, speaker="customer", text=user_redacted, is_final=True)
            transcript.append(f"customer: {user_redacted}")
            continue

        # Redact customer speech for transcript
        user_clean = redact_pii_for_transcript(user_raw, birth_year=customer.get("birth_year"))
        add_turn(call_id=call_id, speaker="customer", text=user_clean, is_final=True)
        transcript.append(f"customer: {user_clean}")

        # Dialogue policy step
        if not state.verified:
            # Check if user provided birth year
            import re
            m = re.search(r"\b(19\d\d|20\d\d)\b", user_raw)
            if m:
                year_cand = int(m.group(1))
                tool_msg = tools["verify_identity"].invoke({"birth_year": year_cand})
                if state.verified:
                    agent_reply = f"Thank you for confirming. Your autopay payment of {customer['amount_due']} was due on {customer['due_date']}. Would you like me to retry the payment now or send a payment link?"
                else:
                    agent_reply = "That does not match our records. Could you please re-confirm your 4-digit birth year?"
            else:
                agent_reply = f"For security reasons, before we proceed, could you please confirm your 4-digit birth year?"
        else:
            # Verified stage: handle payment action
            user_lower = user_raw.lower()
            if "retry" in user_lower or "debiting" in user_lower or "go ahead" in user_lower:
                tool_msg = tools["retry_payment"].invoke({})
                if state.terminal_outcome == "recovered":
                    agent_reply = "Thank you! The payment has been debited successfully from your account. Have a great day!"
                else:
                    agent_reply = "The bank declined the direct retry. I can dispatch a secure payment link by SMS instead. Would that work?"
            elif "link" in user_lower or "sms" in user_lower or "send" in user_lower:
                tool_msg = tools["send_payment_link"].invoke({})
                agent_reply = "I have dispatched the secure payment link to your registered mobile number. It remains valid for 24 hours. Thank you!"
            elif "callback" in user_lower or "tomorrow" in user_lower or "call me" in user_lower:
                tool_msg = tools["schedule_callback"].invoke({"preferred_time": "tomorrow at 3 PM"})
                agent_reply = "I have scheduled a callback for tomorrow at 3 PM. Thank you and goodbye!"
            else:
                agent_reply = "Would you prefer me to retry the bank mandate or send a payment link by SMS?"

        # Pass through pre-verification shield (Guardrail 2)
        shielded_reply, _ = shield_unverified_output(agent_reply, verified=state.verified)
        sanitized_reply = sanitize_tts_text(shielded_reply)

        add_turn(call_id=call_id, speaker="agent", text=sanitized_reply, is_final=True)
        transcript.append(f"agent: {sanitized_reply}")

    # Fallback outcome if call wrapped up without terminal state
    final_outcome = state.terminal_outcome or "declined"
    final_note = state.outcome_note or "Simulation completed"

    full_transcript_str = "\n".join(transcript)
    update_call_record(
        call_id=call_id,
        status="completed",
        outcome=final_outcome,
        duration_sec=35.0,
        note=final_note,
        transcript=full_transcript_str,
    )

    return {
        "call_id": call_id,
        "customer_id": cid,
        "name": customer["name"],
        "bank": customer["bank_name"],
        "amount": customer["amount_due"],
        "failure_reason": customer["failure_reason"],
        "outcome": final_outcome,
        "verified": state.verified,
        "note": final_note,
    }


def run_all_simulations() -> list[dict[str, Any]]:
    """Run all 10 customer persona simulations and print results table."""
    init_db()
    with open(CUSTOMERS_FILE) as f:
        customers = json.load(f)

    results = []
    print("\n" + "=" * 105)
    print(f"{'EXECUTING 10-CUSTOMER SYNTHETIC PERSONA SIMULATION':^105}")
    print("=" * 105)

    for c in customers:
        res = run_persona_simulation(c)
        results.append(res)

    print("\n" + "=" * 105)
    print(f"{'SIMULATION RESULTS TABLE (source=simulated)':^105}")
    print("=" * 105)
    header = (
        f"{'Cust ID':<9} | {'Customer Name':<16} | {'Bank':<12} | {'Amount':<9} | "
        f"{'Failure Reason':<18} | {'Outcome':<18} | {'Note'}"
    )
    print(header)
    print("-" * 105)

    for r in results:
        print(
            f"{r['customer_id']:<9} | {r['name']:<16} | {r['bank']:<12} | ₹{r['amount']:<8,.0f} | "
            f"{r['failure_reason']:<18} | {r['outcome']:<18} | {r['note'][:20]}"
        )

    print("=" * 105 + "\n")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Autopay Recovery Persona Simulator")
    parser.add_argument("--customer", type=str, help="Simulate a specific customer ID (e.g. CUST-001)")
    args = parser.parse_args()

    if args.customer:
        init_db()
        with open(CUSTOMERS_FILE) as f:
            customers = json.load(f)
        matches = [c for c in customers if c["id"] == args.customer]
        if not matches:
            print(f"Customer {args.customer} not found in customers.json", file=sys.stderr)
            sys.exit(1)
        res = run_persona_simulation(matches[0])
        print(json.dumps(res, indent=2))
    else:
        run_all_simulations()


if __name__ == "__main__":
    main()
