"""Unit tests for CallState and make_tools factory (Step 2)."""

from __future__ import annotations

import pytest

from src.tools import CallState, make_tools


@pytest.fixture
def sample_customer():
    return {
        "id": "CUST-001",
        "name": "Aarav Sharma",
        "phone": "+919876543210",
        "mandate_id": "MND-20260801-001",
        "amount_due": 2499.00,
        "currency": "INR",
        "due_date": "2026-09-25",
        "failure_reason": "insufficient_funds",
        "bank_name": "HDFC Bank",
        "last_4_digits": "4532",
        "birth_year": 1988,
        "do_not_call": False,
    }


def test_payment_tools_blocked_before_verification(sample_customer):
    state = CallState(customer_id="CUST-001", customer_record=sample_customer)
    tools = {t.name: t for t in make_tools(state)}

    # retry_payment should fail before verification
    res = tools["retry_payment"].invoke({})
    assert "Identity is not verified" in res

    # send_payment_link should fail before verification
    res_link = tools["send_payment_link"].invoke({})
    assert "Identity is not verified" in res_link


def test_verify_identity_success_returns_spoken_details(sample_customer):
    state = CallState(customer_id="CUST-001", customer_record=sample_customer)
    tools = {t.name: t for t in make_tools(state)}

    res = tools["verify_identity"].invoke({"birth_year": 1988})
    assert state.verified is True
    assert state.stage == "verified"
    # Must contain spoken numbers
    assert "two thousand four hundred ninety-nine rupees" in res
    assert "the twenty-fifth of September" in res
    assert "HDFC Bank" in res


def test_verify_identity_max_two_attempts(sample_customer):
    state = CallState(customer_id="CUST-001", customer_record=sample_customer)
    tools = {t.name: t for t in make_tools(state)}

    # Attempt 1: wrong year
    res1 = tools["verify_identity"].invoke({"birth_year": 1999})
    assert state.verified is False
    assert state.verification_attempts == 1
    assert "attempt 2 of 2" in res1
    assert state.terminal_outcome is None

    # Attempt 2: wrong year again -> terminal outcome verification_failed
    res2 = tools["verify_identity"].invoke({"birth_year": 2000})
    assert state.verified is False
    assert state.verification_attempts == 2
    assert state.terminal_outcome == "verification_failed"
    assert "Verification failed twice" in res2


def test_retry_payment_succeeds_for_insufficient_funds(sample_customer):
    sample_customer["failure_reason"] = "insufficient_funds"
    state = CallState(customer_id="CUST-001", customer_record=sample_customer, verified=True)
    tools = {t.name: t for t in make_tools(state)}

    res = tools["retry_payment"].invoke({})
    assert "succeeded" in res.lower()
    assert state.terminal_outcome == "recovered"


def test_retry_payment_succeeds_for_bank_timeout(sample_customer):
    sample_customer["failure_reason"] = "bank_timeout"
    state = CallState(customer_id="CUST-001", customer_record=sample_customer, verified=True)
    tools = {t.name: t for t in make_tools(state)}

    res = tools["retry_payment"].invoke({})
    assert "succeeded" in res.lower()
    assert state.terminal_outcome == "recovered"


def test_retry_payment_fails_for_mandate_expired(sample_customer):
    sample_customer["failure_reason"] = "mandate_expired"
    state = CallState(customer_id="CUST-001", customer_record=sample_customer, verified=True)
    tools = {t.name: t for t in make_tools(state)}

    res = tools["retry_payment"].invoke({})
    assert "declined" in res.lower() or "expired" in res.lower()
    assert state.terminal_outcome is None  # Does not set terminal; offers link/callback


def test_first_terminal_outcome_wins(sample_customer):
    state = CallState(customer_id="CUST-001", customer_record=sample_customer, verified=True)
    tools = {t.name: t for t in make_tools(state)}

    # First action: send payment link
    tools["send_payment_link"].invoke({})
    assert state.terminal_outcome == "link_sent"

    # Second action: try to call end_call with declined
    res = tools["end_call"].invoke({"outcome": "declined", "note": "Trying to overwrite"})
    assert "already finalized" in res
    assert state.terminal_outcome == "link_sent"  # Unchanged!


def test_customer_id_never_an_llm_argument(sample_customer):
    state = CallState(customer_id="CUST-001", customer_record=sample_customer)
    tools = make_tools(state)

    for t in tools:
        # Inspect args schema
        args = t.args
        assert "customer_id" not in args, f"Tool {t.name} must not accept customer_id from LLM"
