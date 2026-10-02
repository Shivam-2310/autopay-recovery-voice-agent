"""SQLite persistence for call outcomes, customer state, and transcripts."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.models import Outcome

DB_PATH = Path(__file__).resolve().parent.parent / "outcomes.db"
CUSTOMERS_FILE = Path(__file__).resolve().parent.parent / "customers.json"
IST = ZoneInfo("Asia/Kolkata")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outcomes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id     TEXT    NOT NULL,
    disposition     TEXT    NOT NULL,
    notes           TEXT    NOT NULL DEFAULT '',
    transcript      TEXT    NOT NULL DEFAULT '',
    duration_sec    REAL    NOT NULL DEFAULT 0.0,
    timestamp       TEXT    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS customers_state (
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


def get_conn(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Return a connection with WAL mode enabled for safe concurrent reads."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    """Create tables if they don't exist and sync customer records."""
    with get_conn(db_path) as conn:
        conn.executescript(_SCHEMA)
    sync_customers_from_json(db_path=db_path)


def mask_phone_number(phone: str) -> str:
    """Mask phone number preserving country code and last 4 digits (e.g. +91XXXXXX1234)."""
    clean = "".join(c for c in phone if c.isdigit() or c == "+")
    if not clean:
        return "+91XXXXXX1234"
    if not clean.startswith("+"):
        clean = f"+{clean}"
    if len(clean) >= 7:
        if clean.startswith("+91"):
            prefix = "+91"
        elif clean.startswith("+1"):
            prefix = "+1"
        else:
            prefix = clean[:3]
        suffix = clean[-4:]
        return f"{prefix}XXXXXX{suffix}"
    return "+91XXXXXX1234"


def sync_customers_from_json(json_path: Path = CUSTOMERS_FILE, db_path: Path = DB_PATH) -> None:
    """Seed or update customer metadata in customers_state while preserving do_not_call & call history."""
    if not json_path.exists():
        return
    with open(json_path) as f:
        customers = json.load(f)

    with get_conn(db_path) as conn:
        for c in customers:
            phone_masked = mask_phone_number(c.get("phone", "+919876543210"))
            conn.execute(
                """
                INSERT INTO customers_state (
                    id, name, phone_masked, bank_name, amount_due,
                    due_date, failure_reason, birth_year, do_not_call
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    phone_masked = excluded.phone_masked,
                    bank_name = excluded.bank_name,
                    amount_due = excluded.amount_due,
                    due_date = excluded.due_date,
                    failure_reason = excluded.failure_reason,
                    birth_year = excluded.birth_year
                """,
                (
                    c["id"],
                    c["name"],
                    phone_masked,
                    c["bank_name"],
                    c["amount_due"],
                    c["due_date"],
                    c["failure_reason"],
                    c.get("birth_year", 1990),
                    1 if c.get("do_not_call") else 0,
                ),
            )


def get_customer_state(customer_id: str, db_path: Path = DB_PATH) -> dict | None:
    """Fetch customer state record by ID."""
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM customers_state WHERE id = ?", (customer_id,)
        ).fetchone()
        return dict(row) if row else None


def can_dial_customer(customer_id: str, demo_override: bool = False, db_path: Path = DB_PATH) -> tuple[bool, str]:
    """Check if customer is eligible to be called.

    Rules:
    1. do_not_call customers can NEVER be called.
    2. Max 1 attempt per customer per day (in IST). Bypassed if demo_override is True.
    """
    state = get_customer_state(customer_id, db_path=db_path)
    if not state:
        return True, "OK"

    if state.get("do_not_call"):
        return False, f"Customer {customer_id} has requested Do Not Call (DND). Dialing blocked."

    if not demo_override and state.get("last_call_at"):
        try:
            last_call_dt = datetime.fromisoformat(state["last_call_at"])
            today_ist = datetime.now(IST).date()
            last_call_ist = last_call_dt.astimezone(IST).date()
            if today_ist == last_call_ist:
                return (
                    False,
                    f"Customer {customer_id} was already called today at {last_call_dt.strftime('%H:%M')} IST. "
                    "(Limit: 1 attempt/customer/day. Use DEMO_OVERRIDE=true to bypass.)",
                )
        except Exception:
            pass

    return True, "OK"


def record_dial_attempt(customer_id: str, outcome: str = "in_progress", db_path: Path = DB_PATH) -> None:
    """Update last_call_at and last_outcome for a customer."""
    now_iso = datetime.now(UTC).isoformat()
    with get_conn(db_path) as conn:
        conn.execute(
            """
            UPDATE customers_state
            SET last_call_at = ?, last_outcome = ?
            WHERE id = ?
            """,
            (now_iso, outcome, customer_id),
        )


def set_customer_dnd(customer_id: str, db_path: Path = DB_PATH) -> None:
    """Mark a customer as Do Not Call."""
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE customers_state SET do_not_call = 1 WHERE id = ?",
            (customer_id,),
        )


def save_outcome(outcome: Outcome, db_path: Path = DB_PATH) -> int:
    """Insert an outcome and update the customer state."""
    with get_conn(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO outcomes (customer_id, disposition, notes, transcript, duration_sec, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                outcome.customer_id,
                outcome.disposition,
                outcome.notes,
                outcome.transcript,
                outcome.duration_sec,
                outcome.timestamp.isoformat(),
            ),
        )
        row_id = cursor.lastrowid
        conn.execute(
            """
            UPDATE customers_state
            SET last_call_at = ?, last_outcome = ?
            WHERE id = ?
            """,
            (outcome.timestamp.isoformat(), outcome.disposition, outcome.customer_id),
        )
        return row_id  # type: ignore[return-value]


def get_outcomes(customer_id: str | None = None, db_path: Path = DB_PATH) -> list[dict]:
    """Fetch outcomes, optionally filtered by customer_id."""
    with get_conn(db_path) as conn:
        if customer_id:
            rows = conn.execute(
                "SELECT * FROM outcomes WHERE customer_id = ? ORDER BY id DESC",
                (customer_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM outcomes ORDER BY id DESC").fetchall()
        return [dict(row) for row in rows]


# Auto-init on import
init_db()
