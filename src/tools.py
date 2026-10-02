"""Stateful in-process tools for the autopay recovery agent.

Tools are instantiated per-call via `make_tools(state, emit_event_fn)` and bind
strictly to the call's `CallState`. `customer_id` is NEVER an LLM argument.
Enforces the first-terminal-outcome-wins rule and blocks payment tools before identity verification.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Literal

from langchain_core.tools import tool

from src.models import Disposition
from src.spoken_numbers import amount_to_spoken_inr, date_to_spoken

logger = logging.getLogger("tools")

_FAILURE_REASON_SPOKEN = {
    "insufficient_funds": "insufficient funds in the account",
    "bank_timeout": "a temporary bank server timeout during processing",
    "mandate_expired": "the recurring autopay mandate having expired",
    "bank_decline": "a decline by the issuing bank",
}


@dataclass
class CallState:
    """Per-call runtime state container."""

    customer_id: str
    customer_record: dict[str, Any]
    call_id: str = ""
    stage: str = "init"  # init | identifying | verified | offering | resolved | terminal
    verified: bool = False
    verification_attempts: int = 0
    max_verification_attempts: int = 2
    offers_made: int = 0
    max_offers: int = 2
    terminal_outcome: Disposition | None = None
    outcome_note: str = ""
    do_not_call: bool = False
    sms_sent: bool = False
    turns_count: int = 0

    def is_terminal(self) -> bool:
        return self.terminal_outcome is not None


def make_tools(
    state: CallState,
    emit_event_fn: Callable[[str, dict[str, Any]], None] | None = None,
) -> list[Any]:
    """Factory creating per-call tools bound to the active CallState."""

    def _emit(event_type: str, payload: dict[str, Any]) -> None:
        if emit_event_fn:
            try:
                emit_event_fn(event_type, payload)
            except Exception as e:
                logger.warning("Failed to emit event %s: %s", event_type, e)

    @tool
    def verify_identity(birth_year: int) -> str:
        """Verify the customer's identity using their 4-digit birth year.

        Must be called before discussing any account balance, amounts, or payment options.

        Args:
            birth_year: The 4-digit year of birth provided by the customer (e.g. 1988).

        Returns:
            Instructions for the model including spoken account details on success.
        """
        logger.info("Tool: verify_identity called for customer %s", state.customer_id)
        if state.is_terminal():
            return "Call outcome has already been decided. Politely conclude the call."

        state.verification_attempts += 1
        expected_year = state.customer_record.get("birth_year")

        if expected_year and birth_year == int(expected_year):
            state.verified = True
            state.stage = "verified"
            _emit("state.update", {
                "stage": state.stage,
                "verified": state.verified,
                "verification_attempts": state.verification_attempts,
            })

            # Format amount and date into spoken English
            amt_spoken = amount_to_spoken_inr(state.customer_record.get("amount_due", 0.0))
            date_spoken = date_to_spoken(state.customer_record.get("due_date", ""))
            reason_raw = state.customer_record.get("failure_reason", "insufficient_funds")
            reason_spoken = _FAILURE_REASON_SPOKEN.get(reason_raw, "a processing issue")
            bank = state.customer_record.get("bank_name", "your bank")

            return (
                f"Identity verified successfully. The account details are: "
                f"autopay payment of {amt_spoken} scheduled for {date_spoken} could not be completed "
                f"due to {reason_spoken} from {bank}. "
                f"Now politely explain this failure and offer to retry the payment or send a secure link."
            )

        # Verification failed
        if state.verification_attempts < state.max_verification_attempts:
            _emit("state.update", {
                "stage": state.stage,
                "verified": False,
                "verification_attempts": state.verification_attempts,
            })
            return (
                "The birth year provided does not match our records. "
                "Politely ask the customer to re-confirm their 4-digit birth year (attempt 2 of 2)."
            )

        # Reached max attempts -> terminal failure
        state.terminal_outcome = "verification_failed"
        state.outcome_note = "Identity verification failed after 2 attempts"
        state.stage = "terminal"
        _emit("state.update", {
            "stage": state.stage,
            "verified": False,
            "terminal_outcome": state.terminal_outcome,
            "outcome_note": state.outcome_note,
        })
        return (
            "Verification failed twice. For privacy and security reasons, inform the customer "
            "that you cannot proceed without verification, thank them politely, and end the call."
        )

    @tool
    def retry_payment() -> str:
        """Retry the failed autopay mandate debit immediately against the bank.

        Can ONLY be called after identity is verified.
        Succeeds for 'insufficient_funds' and 'bank_timeout'.
        Fails for 'mandate_expired' and 'bank_decline'.

        Returns:
            Result of the retry attempt.
        """
        logger.info("Tool: retry_payment called for customer %s", state.customer_id)
        if not state.verified:
            return "Error: Identity is not verified. You must verify identity with birth year first."
        if state.is_terminal():
            return "Call outcome is already finalized. Conclude the conversation."

        reason = state.customer_record.get("failure_reason", "")
        if reason in ("insufficient_funds", "bank_timeout"):
            state.terminal_outcome = "recovered"
            state.outcome_note = f"Mandate retry succeeded ({reason})"
            state.stage = "terminal"
            _emit("state.update", {
                "stage": state.stage,
                "terminal_outcome": state.terminal_outcome,
                "outcome_note": state.outcome_note,
            })
            return (
                "Payment retry succeeded! The payment has been successfully debited from the customer's account. "
                "Confirm this success with the customer, thank them, and politely say goodbye."
            )

        # Cannot retry for expired mandates or bank declines
        return (
            "The direct payment retry was declined by the bank or the mandate is no longer active. "
            "Explain this to the customer and offer to send a secure payment link via SMS instead."
        )

    @tool
    def send_payment_link() -> str:
        """Send a secure payment link via SMS to the customer's registered mobile number.

        Can ONLY be called after identity is verified.

        Returns:
            Confirmation of SMS delivery request.
        """
        logger.info("Tool: send_payment_link called for customer %s", state.customer_id)
        if not state.verified:
            return "Error: Identity is not verified. You must verify identity with birth year first."
        if state.is_terminal():
            return "Call outcome is already finalized. Conclude the conversation."

        state.offers_made += 1
        state.sms_sent = True
        state.terminal_outcome = "link_sent"
        state.outcome_note = "Payment link sent via SMS"
        state.stage = "terminal"

        _emit("state.update", {
            "stage": state.stage,
            "offers_made": state.offers_made,
            "terminal_outcome": state.terminal_outcome,
            "outcome_note": state.outcome_note,
        })
        _emit("tool.call", {
            "tool": "send_payment_link",
            "status": "success",
            "customer_id": state.customer_id,
        })

        return (
            "The payment link has been dispatched to the customer's registered phone number via SMS. "
            "Inform them that the link is valid for 24 hours, ask if they have any other questions, "
            "and politely conclude the call."
        )

    @tool
    def schedule_callback(preferred_time: str) -> str:
        """Schedule a follow-up callback at the customer's requested time.

        Args:
            preferred_time: The date and time requested by customer (e.g. 'tomorrow at 3 PM').

        Returns:
            Confirmation that callback was scheduled.
        """
        logger.info("Tool: schedule_callback called for %s at %s", state.customer_id, preferred_time)
        if state.is_terminal():
            return "Call outcome is already finalized. Conclude the conversation."

        state.offers_made += 1
        state.terminal_outcome = "scheduled"
        state.outcome_note = f"Callback scheduled for: {preferred_time}"
        state.stage = "terminal"

        _emit("state.update", {
            "stage": state.stage,
            "offers_made": state.offers_made,
            "terminal_outcome": state.terminal_outcome,
            "outcome_note": state.outcome_note,
        })

        return (
            f"Callback has been successfully scheduled for {preferred_time}. "
            f"Confirm this appointment with the customer, thank them, and politely conclude the call."
        )

    @tool
    def escalate(reason: str) -> str:
        """Escalate the call to a human specialist for disputes, distress, or complaints.

        Args:
            reason: Specific reason for escalation (e.g. 'Customer disputes transaction', 'Financial hardship').

        Returns:
            Instructions on how to wrap up and transfer/escalate.
        """
        logger.info("Tool: escalate called for %s reason: %s", state.customer_id, reason)
        if state.is_terminal():
            return "Call outcome is already finalized. Conclude the conversation."

        state.terminal_outcome = "escalate"
        state.outcome_note = f"Escalated: {reason}"
        state.stage = "terminal"

        _emit("state.update", {
            "stage": state.stage,
            "terminal_outcome": state.terminal_outcome,
            "outcome_note": state.outcome_note,
        })

        return (
            "The account has been flagged for immediate senior support review. "
            "Reassure the customer with empathy that a senior specialist will follow up personally, "
            "thank them, and end the call."
        )

    @tool
    def end_call(outcome: Literal["declined", "wrong_party"], note: str) -> str:
        """Finalize the call when customer declines all options or is the wrong party.

        Args:
            outcome: 'declined' if customer refuses to pay, 'wrong_party' if wrong person or answering machine.
            note: Brief summary note.

        Returns:
            Wrap up instruction.
        """
        logger.info("Tool: end_call called for %s outcome: %s", state.customer_id, outcome)
        if state.is_terminal():
            return "Call outcome is already finalized. Conclude the conversation."

        state.terminal_outcome = outcome
        state.outcome_note = note or f"Call finalized with disposition: {outcome}"
        state.stage = "terminal"

        _emit("state.update", {
            "stage": state.stage,
            "terminal_outcome": state.terminal_outcome,
            "outcome_note": state.outcome_note,
        })

        return "Call outcome recorded. Say a brief, courteous goodbye and disconnect."

    return [
        verify_identity,
        retry_payment,
        send_payment_link,
        schedule_callback,
        escalate,
        end_call,
    ]
