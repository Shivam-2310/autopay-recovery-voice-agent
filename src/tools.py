"""In-process tools for the autopay recovery agent.

Each tool writes to SQLite and returns a confirmation string that the LLM
speaks back to the customer. All tools are LangChain @tool functions.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from langchain_core.tools import tool

from src.db import save_outcome
from src.models import Outcome

logger = logging.getLogger(__name__)


@tool
def send_payment_link(customer_id: str) -> str:
    """Send a secure payment link via SMS to the customer.

    Call this when the customer agrees to pay via a payment link.

    Args:
        customer_id: The customer's unique identifier.

    Returns:
        Confirmation message to speak to the customer.
    """
    logger.info("Tool: send_payment_link for customer %s", customer_id)
    # In production this would call an SMS API. Here we simulate.
    save_outcome(
        Outcome(
            customer_id=customer_id,
            disposition="payment_link_sent",
            notes="Payment link sent via SMS",
            timestamp=datetime.now(UTC),
        )
    )
    return (
        "Payment link has been sent to the customer's registered mobile number. "
        "Let them know it's valid for 24 hours."
    )


@tool
def schedule_callback(customer_id: str, preferred_time: str) -> str:
    """Schedule a callback for the customer at their preferred time.

    Call this when the customer asks to be called back later.

    Args:
        customer_id: The customer's unique identifier.
        preferred_time: When the customer wants to be called back (e.g. "tomorrow at 3 PM").

    Returns:
        Confirmation message to speak to the customer.
    """
    logger.info(
        "Tool: schedule_callback for customer %s at %s", customer_id, preferred_time
    )
    save_outcome(
        Outcome(
            customer_id=customer_id,
            disposition="callback_requested",
            notes=f"Callback requested for: {preferred_time}",
            timestamp=datetime.now(UTC),
        )
    )
    return f"Callback has been scheduled for {preferred_time}. Confirm this with the customer."


@tool
def mark_refused(customer_id: str, reason: str) -> str:
    """Record that the customer explicitly refused to pay or requested no further calls.

    Call this when the customer declines all options or says "do not call".

    Args:
        customer_id: The customer's unique identifier.
        reason: Why the customer refused (e.g. "do_not_call", "will_not_pay", "disputed").

    Returns:
        Confirmation message.
    """
    logger.info("Tool: mark_refused for customer %s reason=%s", customer_id, reason)
    save_outcome(
        Outcome(
            customer_id=customer_id,
            disposition="refused",
            notes=f"Customer refused: {reason}",
            timestamp=datetime.now(UTC),
        )
    )
    return "Customer's refusal has been recorded. Wrap up the call politely."


@tool
def end_call(customer_id: str, disposition: str, notes: str) -> str:
    """Finalize the call and save the outcome.

    MUST be called as the very last action in every conversation. This records
    the final disposition and any summary notes.

    Args:
        customer_id: The customer's unique identifier.
        disposition: Final outcome — one of: payment_link_sent, callback_requested, refused, voicemail, no_answer, error.
        notes: Brief summary of what happened in the call.

    Returns:
        Confirmation that the call has been finalized.
    """
    logger.info(
        "Tool: end_call for customer %s disposition=%s", customer_id, disposition
    )
    save_outcome(
        Outcome(
            customer_id=customer_id,
            disposition=disposition,  # type: ignore[arg-type]
            notes=notes,
            timestamp=datetime.now(UTC),
        )
    )
    return "Call has been finalized and outcome recorded. You may now say goodbye."


# Convenience list for graph.py
ALL_TOOLS = [send_payment_link, schedule_callback, mark_refused, end_call]
