"""Pydantic models for customer records and call outcomes."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class FailureReason(StrEnum):
    INSUFFICIENT_FUNDS = "insufficient_funds"
    BANK_TIMEOUT = "bank_timeout"
    MANDATE_EXPIRED = "mandate_expired"
    BANK_DECLINE = "bank_decline"


class Customer(BaseModel):
    """A customer with a failed autopay mandate."""

    id: str
    name: str
    phone: str = Field(description="Fictional customer phone number")
    mandate_id: str = Field(description="Autopay mandate reference")
    amount_due: float
    currency: str = "INR"
    due_date: str = Field(description="ISO-8601 date string")
    failure_reason: FailureReason
    bank_name: str
    last_4_digits: str = Field(description="Last 4 digits of card/account")
    birth_year: int = Field(description="Year of birth for identity verification")
    do_not_call: bool = Field(default=False, description="Whether customer requested no further calls")


Disposition = Literal[
    "recovered",
    "link_sent",
    "scheduled",
    "escalate",
    "declined",
    "verification_failed",
    "wrong_party",
    "no_answer",
]


class Outcome(BaseModel):
    """Result of an outbound recovery call."""

    customer_id: str
    disposition: Disposition
    notes: str = ""
    transcript: str = ""
    duration_sec: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
