"""Pydantic models for customer records and call outcomes."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class FailureReason(StrEnum):
    INSUFFICIENT_FUNDS = "insufficient_funds"
    EXPIRED_CARD = "expired_card"
    BANK_DECLINED = "bank_declined"
    ACCOUNT_CLOSED = "account_closed"
    LIMIT_EXCEEDED = "limit_exceeded"


class Customer(BaseModel):
    """A customer with a failed autopay mandate."""

    id: str
    name: str
    phone: str = Field(description="E.164 phone number")
    mandate_id: str = Field(description="Autopay mandate reference")
    amount_due: float
    currency: str = "INR"
    due_date: str = Field(description="ISO-8601 date string")
    failure_reason: FailureReason
    bank_name: str
    last_4_digits: str = Field(description="Last 4 digits of card/account")


Disposition = Literal[
    "payment_link_sent",
    "callback_requested",
    "refused",
    "voicemail",
    "no_answer",
    "error",
]


class Outcome(BaseModel):
    """Result of an outbound recovery call."""

    customer_id: str
    disposition: Disposition
    notes: str = ""
    transcript: str = ""
    duration_sec: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
