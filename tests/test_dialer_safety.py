"""Unit tests for Step 1 safety rules and dialer constraints.

Verifies:
1. DEMO_PHONE validation (strict E.164, cannot be omitted or malformed).
2. DEMO_OVERRIDE banner & bypass behavior.
3. IST call-window guard (default 09:00 - 20:00 IST).
4. Do Not Call (DND) blocking.
5. Max 1 attempt/customer/day enforcement.
6. Phone number masking in logs and displays.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from src.db import can_dial_customer, get_conn, mask_phone_number, set_customer_dnd, sync_customers_from_json
from src.dial import check_call_window, validate_demo_phone

IST = ZoneInfo("Asia/Kolkata")


def test_validate_demo_phone_valid():
    assert validate_demo_phone("+919876543210") == "+919876543210"
    assert validate_demo_phone("+14155550100") == "+14155550100"


def test_validate_demo_phone_invalid():
    with pytest.raises(SystemExit):
        validate_demo_phone(None)

    with pytest.raises(SystemExit):
        validate_demo_phone("")

    # Missing '+' prefix
    with pytest.raises(SystemExit):
        validate_demo_phone("919876543210")

    # Non-digit characters
    with pytest.raises(SystemExit):
        validate_demo_phone("+91-9876-543210")


def test_mask_phone_number():
    assert mask_phone_number("+919876543210") == "+91XXXXXX3210"
    assert mask_phone_number("+14155550199") == "+1XXXXXX0199"
    assert mask_phone_number("123") == "+91XXXXXX1234"


def test_call_window_guard():
    # Outside window simulation (e.g. 02:00 IST)
    with patch("src.dial.datetime") as mock_dt:
        mock_now = datetime(2026, 10, 3, 2, 30, tzinfo=IST)
        mock_dt.now.return_value = mock_now

        in_window, reason = check_call_window(demo_override=False)
        assert in_window is False
        assert "outside the permitted calling window" in reason

        # When DEMO_OVERRIDE is True, outside window is allowed
        override_ok, override_msg = check_call_window(demo_override=True)
        assert override_ok is True
        assert "DEMO_OVERRIDE" in override_msg

    # Inside window simulation (e.g. 14:00 IST)
    with patch("src.dial.datetime") as mock_dt:
        mock_now = datetime(2026, 10, 3, 14, 0, tzinfo=IST)
        mock_dt.now.return_value = mock_now

        in_window, _ = check_call_window(demo_override=False)
        assert in_window is True


def test_can_dial_customer_dnd_and_daily_limit(tmp_path: Path):
    db_file = tmp_path / "test_safety.db"
    
    # Initialize schema in temp DB
    with sqlite3.connect(str(db_file)) as conn:
        conn.executescript(
            """
            CREATE TABLE customers_state (
                id              TEXT PRIMARY KEY,
                name            TEXT NOT NULL,
                phone_masked    TEXT NOT NULL,
                bank_name       TEXT NOT NULL,
                amount_due      REAL NOT NULL,
                due_date        TEXT NOT NULL,
                failure_reason  TEXT NOT NULL,
                birth_year      INTEGER NOT NULL,
                do_not_call     INTEGER NOT NULL DEFAULT 0,
                last_call_at    TEXT,
                last_outcome    TEXT,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        conn.execute(
            """
            INSERT INTO customers_state (id, name, phone_masked, bank_name, amount_due, due_date, failure_reason, birth_year, do_not_call)
            VALUES ('CUST-TEST', 'Test User', '+91XXXXXX1234', 'HDFC Bank', 1000.0, '2026-09-25', 'insufficient_funds', 1990, 0)
            """
        )

    # 1. Fresh customer can be dialed
    ok, msg = can_dial_customer("CUST-TEST", demo_override=False, db_path=db_file)
    assert ok is True

    # 2. Record call today -> cannot be dialed again without DEMO_OVERRIDE
    now_iso = datetime.now(UTC).isoformat()
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("UPDATE customers_state SET last_call_at = ? WHERE id = 'CUST-TEST'", (now_iso,))

    ok_today, msg_today = can_dial_customer("CUST-TEST", demo_override=False, db_path=db_file)
    assert ok_today is False
    assert "already called today" in msg_today

    # 3. With DEMO_OVERRIDE=True, daily limit is bypassed
    ok_bypassed, _ = can_dial_customer("CUST-TEST", demo_override=True, db_path=db_file)
    assert ok_bypassed is True

    # 4. If customer is marked Do Not Call, they CANNOT be dialed even with DEMO_OVERRIDE
    set_customer_dnd("CUST-TEST", db_path=db_file)
    ok_dnd, msg_dnd = can_dial_customer("CUST-TEST", demo_override=True, db_path=db_file)
    assert ok_dnd is False
    assert "Do Not Call" in msg_dnd
