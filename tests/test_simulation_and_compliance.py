"""Compliance, safety, and simulation unit tests (Step 9).

Verifies:
1. One outcome per call (terminal disposition cannot be overwritten).
2. Zero financial disclosure before identity verification (amount/date suppressed).
3. Wrong party leaks zero financial or account data.
4. Card numbers / credentials never echoed or stored unmasked in transcripts.
5. End-to-end persona simulation runs cleanly and records to DB.
"""

from __future__ import annotations

import os
import pytest

from src.db import create_call_record, get_call_details, init_db
from src.guardrails import (
    detect_card_or_credentials,
    detect_wrong_party,
    redact_pii_for_transcript,
    shield_unverified_output,
)
from src.simulate import run_persona_simulation
from src.tools import CallState, make_tools


@pytest.fixture(autouse=True)
def setup_env():
    os.environ["DEMO_PHONE"] = "+919876543210"
    os.environ["DEMO_OVERRIDE"] = "true"
    init_db()


@pytest.fixture
def mock_customer():
    return {
        "id": "CUST-COMPLIANCE",
        "name": "Ananya Roy",
        "phone": "+919876543210",
        "mandate_id": "MND-2026-TEST",
        "amount_due": 3499.00,
        "currency": "INR",
        "due_date": "2026-09-28",
        "failure_reason": "insufficient_funds",
        "bank_name": "State Bank of India",
        "last_4_digits": "9904",
        "birth_year": 1990,
        "do_not_call": False,
    }


def test_one_outcome_per_call_first_wins(mock_customer):
    state = CallState(customer_id="CUST-COMPLIANCE", customer_record=mock_customer, verified=True)
    tools = {t.name: t for t in make_tools(state)}

    # Step 1: Retry payment succeeds -> outcome = 'recovered'
    res1 = tools["retry_payment"].invoke({})
    assert "succeeded" in res1.lower()
    assert state.terminal_outcome == "recovered"

    # Step 2: Attempting another terminal tool call must be blocked
    res2 = tools["end_call"].invoke({"outcome": "declined", "note": "Should not overwrite"})
    assert "already finalized" in res2
    assert state.terminal_outcome == "recovered"

    # Step 3: Attempting schedule_callback must be blocked
    res3 = tools["schedule_callback"].invoke({"preferred_time": "tomorrow"})
    assert "already finalized" in res3
    assert state.terminal_outcome == "recovered"


def test_no_amount_or_due_date_before_verification(mock_customer):
    # Unverified state
    state = CallState(customer_id="CUST-COMPLIANCE", customer_record=mock_customer, verified=False)

    # Attempting to talk about balance before verification
    unshielded_text = "Your pending autopay amount of ₹3,499 was due on 2026-09-28."
    shielded, triggered = shield_unverified_output(unshielded_text, verified=state.verified)

    assert triggered is True
    assert "3,499" not in shielded
    assert "3499" not in shielded
    assert "2026-09-28" not in shielded
    assert "birth year" in shielded.lower()


def test_wrong_party_leaks_nothing(mock_customer):
    customer_speech = "No, you have the wrong number. Who is this?"
    assert detect_wrong_party(customer_speech) is True

    state = CallState(customer_id="CUST-COMPLIANCE", customer_record=mock_customer, verified=False)
    tools = {t.name: t for t in make_tools(state)}

    # Agent calls end_call with wrong_party
    res = tools["end_call"].invoke({"outcome": "wrong_party", "note": "Wrong party answered"})
    assert state.terminal_outcome == "wrong_party"

    # Ensure zero financial or sensitive data in response
    assert "₹" not in res
    assert "3499" not in res
    assert "State Bank" not in res
    assert "1990" not in res


def test_card_numbers_never_echoed_and_redacted_in_transcripts():
    user_spoke = "My card is 4532 1234 5678 9012 and security code is 884."
    detected, cred_type = detect_card_or_credentials(user_spoke)
    assert detected is True

    # PII Redaction
    redacted = redact_pii_for_transcript(user_spoke, birth_year=1990)
    assert "4532" not in redacted
    assert "5678" not in redacted
    assert "9012" not in redacted
    assert "884" not in redacted
    assert "[CARD NUMBER REDACTED]" in redacted
    assert "[CREDENTIALS REDACTED]" in redacted


def test_persona_simulation_execution(mock_customer):
    res = run_persona_simulation(mock_customer)
    assert res["customer_id"] == "CUST-COMPLIANCE"
    assert res["outcome"] in ("recovered", "link_sent", "scheduled", "escalate", "declined", "verification_failed", "wrong_party")

    # Verify DB call record exists with source='simulated'
    details = get_call_details(res["call_id"])
    assert details is not None
    assert details["source"] == "simulated"
    assert len(details["turns"]) >= 1
    # Verify birth year never in transcript
    assert "1990" not in details["transcript"]
