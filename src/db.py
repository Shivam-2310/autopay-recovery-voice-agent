"""SQLite persistence for call sessions, telemetry events, transcripts, and SMS tracking.

Configured with WAL mode and busy timeouts for safe concurrent reads/writes.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.models import Outcome

DB_PATH = Path(__file__).resolve().parent.parent / "outcomes.db"
CUSTOMERS_FILE = Path(__file__).resolve().parent.parent / "customers.json"
IST = ZoneInfo("Asia/Kolkata")

_SCHEMA = """
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

CREATE TABLE IF NOT EXISTS calls (
    id              TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL REFERENCES customers_state(id),
    room_name       TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'initiated',
    source          TEXT NOT NULL DEFAULT 'live',
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    duration_sec    REAL DEFAULT 0.0,
    outcome         TEXT,
    note            TEXT,
    voice_id        TEXT,
    llm_provider    TEXT,
    transcript      TEXT DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS turns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id         TEXT NOT NULL REFERENCES calls(id),
    speaker         TEXT NOT NULL,
    text            TEXT NOT NULL,
    is_final        INTEGER NOT NULL DEFAULT 1,
    timestamp       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id         TEXT NOT NULL REFERENCES calls(id),
    event_type      TEXT NOT NULL,
    payload         TEXT NOT NULL,
    timestamp       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id         TEXT NOT NULL REFERENCES calls(id),
    sid             TEXT NOT NULL,
    to_masked       TEXT NOT NULL,
    status          TEXT NOT NULL,
    error_code      TEXT,
    error_message   TEXT,
    mode            TEXT NOT NULL DEFAULT 'mock',
    timestamp       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS link_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    token           TEXT NOT NULL,
    call_id         TEXT NOT NULL REFERENCES calls(id),
    event_type      TEXT NOT NULL,
    timestamp       TEXT NOT NULL
);

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
    """Seed or update customer metadata in customers_state."""
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


def get_all_customers(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Return all customers without exposing birth_year."""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, name, phone_masked, bank_name, amount_due, due_date,
                   failure_reason, do_not_call, last_call_at, last_outcome, created_at
            FROM customers_state
            ORDER BY id ASC
            """
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["phone"] = d["phone_masked"]
            result.append(d)
        return result


def get_customer_state(customer_id: str, db_path: Path = DB_PATH) -> dict | None:
    """Fetch customer state record by ID."""
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM customers_state WHERE id = ?", (customer_id,)
        ).fetchone()
        return dict(row) if row else None


def can_dial_customer(customer_id: str, demo_override: bool = False, db_path: Path = DB_PATH) -> tuple[bool, str]:
    """Check if customer is eligible to be called."""
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


def create_call_record(
    call_id: str,
    customer_id: str,
    room_name: str,
    source: str = "live",
    voice_id: str | None = None,
    llm_provider: str | None = None,
    db_path: Path = DB_PATH,
) -> None:
    """Insert a new call session record."""
    now_iso = datetime.now(UTC).isoformat()
    with get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO calls (id, customer_id, room_name, status, source, started_at, voice_id, llm_provider)
            VALUES (?, ?, ?, 'active', ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                room_name = excluded.room_name,
                status = excluded.status
            """,
            (call_id, customer_id, room_name, source, now_iso, voice_id, llm_provider),
        )


def update_call_record(
    call_id: str,
    status: str | None = None,
    outcome: str | None = None,
    note: str | None = None,
    duration_sec: float | None = None,
    transcript: str | None = None,
    db_path: Path = DB_PATH,
) -> None:
    """Update a call session record upon progress or termination."""
    updates = []
    params = []
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if outcome is not None:
        updates.append("outcome = ?")
        params.append(outcome)
    if note is not None:
        updates.append("note = ?")
        params.append(note)
    if duration_sec is not None:
        updates.append("duration_sec = ?")
        params.append(duration_sec)
    if transcript is not None:
        updates.append("transcript = ?")
        params.append(transcript)

    if not updates:
        return

    now_iso = datetime.now(UTC).isoformat()
    updates.append("ended_at = ?")
    params.append(now_iso)

    params.append(call_id)
    query = f"UPDATE calls SET {', '.join(updates)} WHERE id = ?"
    with get_conn(db_path) as conn:
        conn.execute(query, tuple(params))


def add_turn(call_id: str, speaker: str, text: str, is_final: bool = True, timestamp: str | None = None, db_path: Path = DB_PATH) -> int:
    """Record a spoken dialogue turn."""
    ts = timestamp or datetime.now(UTC).isoformat()
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO turns (call_id, speaker, text, is_final, timestamp) VALUES (?, ?, ?, ?, ?)",
            (call_id, speaker, text, 1 if is_final else 0, ts),
        )
        return cur.lastrowid  # type: ignore[return-value]


def add_event(call_id: str, event_type: str, payload: dict[str, Any], timestamp: str | None = None, db_path: Path = DB_PATH) -> int:
    """Record a telemetry event."""
    ts = timestamp or datetime.now(UTC).isoformat()
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO events (call_id, event_type, payload, timestamp) VALUES (?, ?, ?, ?)",
            (call_id, event_type, json.dumps(payload), ts),
        )
        return cur.lastrowid  # type: ignore[return-value]


def add_message(call_id: str, sid: str, to_masked: str, status: str, mode: str = "mock", error_code: str | None = None, db_path: Path = DB_PATH) -> int:
    """Record an outbound SMS message."""
    ts = datetime.now(UTC).isoformat()
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO messages (call_id, sid, to_masked, status, mode, error_code, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (call_id, sid, to_masked, status, mode, error_code, ts),
        )
        return cur.lastrowid  # type: ignore[return-value]


def update_message_status(sid: str, status: str, error_code: str | None = None, error_message: str | None = None, db_path: Path = DB_PATH) -> None:
    """Update message status by Twilio SID."""
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE messages SET status = ?, error_code = ?, error_message = ? WHERE sid = ?",
            (status, error_code, error_message, sid),
        )


def add_link_event(token: str, call_id: str, event_type: str, db_path: Path = DB_PATH) -> int:
    """Record payment link lifecycle event (created, sent, delivered, clicked, paid)."""
    ts = datetime.now(UTC).isoformat()
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO link_events (token, call_id, event_type, timestamp) VALUES (?, ?, ?, ?)",
            (token, call_id, event_type, ts),
        )
        return cur.lastrowid  # type: ignore[return-value]


def get_calls(limit: int = 50, customer_id: str | None = None, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Return recent call records enriched with customer state."""
    with get_conn(db_path) as conn:
        if customer_id:
            rows = conn.execute(
                """
                SELECT c.*, cs.name as customer_name, cs.phone_masked, cs.bank_name, cs.amount_due, cs.failure_reason
                FROM calls c
                LEFT JOIN customers_state cs ON c.customer_id = cs.id
                WHERE c.customer_id = ?
                ORDER BY c.started_at DESC
                LIMIT ?
                """,
                (customer_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT c.*, cs.name as customer_name, cs.phone_masked, cs.bank_name, cs.amount_due, cs.failure_reason
                FROM calls c
                LEFT JOIN customers_state cs ON c.customer_id = cs.id
                ORDER BY c.started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def get_call_details(call_id: str, db_path: Path = DB_PATH) -> dict[str, Any] | None:
    """Fetch complete call session details with turns, events, messages, and link events."""
    with get_conn(db_path) as conn:
        call = conn.execute(
            """
            SELECT c.*, cs.name as customer_name, cs.amount_due, cs.failure_reason, cs.bank_name
            FROM calls c
            LEFT JOIN customers_state cs ON c.customer_id = cs.id
            WHERE c.id = ?
            """,
            (call_id,),
        ).fetchone()
        if not call:
            return None

        turns = conn.execute(
            "SELECT speaker, text, is_final, timestamp FROM turns WHERE call_id = ? ORDER BY id ASC",
            (call_id,),
        ).fetchall()
        events = conn.execute(
            "SELECT event_type, payload, timestamp FROM events WHERE call_id = ? ORDER BY id ASC",
            (call_id,),
        ).fetchall()
        messages = conn.execute(
            "SELECT sid, to_masked, status, error_code, mode, timestamp FROM messages WHERE call_id = ? ORDER BY id ASC",
            (call_id,),
        ).fetchall()
        link_events = conn.execute(
            "SELECT token, event_type, timestamp FROM link_events WHERE call_id = ? ORDER BY id ASC",
            (call_id,),
        ).fetchall()

        parsed_events = []
        for e in events:
            ev_dict = dict(e)
            try:
                ev_dict["payload"] = json.loads(ev_dict["payload"])
            except Exception:
                pass
            parsed_events.append(ev_dict)

        result = dict(call)
        result["turns"] = [dict(t) for t in turns]
        result["events"] = parsed_events
        result["messages"] = [dict(m) for m in messages]
        result["link_events"] = [dict(l) for l in link_events]
        return result


def get_metrics(db_path: Path = DB_PATH) -> dict[str, Any]:
    """Calculate executive recovery metrics."""
    with get_conn(db_path) as conn:
        total_calls = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
        outcomes_rows = conn.execute(
            "SELECT outcome, COUNT(*) as cnt FROM calls WHERE outcome IS NOT NULL GROUP BY outcome"
        ).fetchall()
        outcomes_counts = {r["outcome"]: r["cnt"] for r in outcomes_rows}

        total_recovered = outcomes_counts.get("recovered", 0)
        retry_recovered = conn.execute(
            "SELECT COUNT(*) FROM calls WHERE outcome = 'recovered' AND (note LIKE '%retry%' OR note LIKE '%Mandate%')"
        ).fetchone()[0]
        link_recovered = conn.execute(
            "SELECT COUNT(*) FROM calls WHERE outcome = 'recovered' AND (note LIKE '%link%' OR note LIKE '%payment link%')"
        ).fetchone()[0]
        if retry_recovered + link_recovered < total_recovered:
            retry_recovered = total_recovered - link_recovered

        link_sent_count = outcomes_counts.get("link_sent", 0)
        scheduled_count = outcomes_counts.get("scheduled", 0)
        escalate_count = outcomes_counts.get("escalate", 0)
        declined_count = outcomes_counts.get("declined", 0)
        failed_count = outcomes_counts.get("verification_failed", 0)
        wrong_party_count = outcomes_counts.get("wrong_party", 0)
        no_answer_count = outcomes_counts.get("no_answer", 0)

        recovery_rate = (total_recovered / total_calls * 100) if total_calls > 0 else 0.0

        avg_dur_row = conn.execute("SELECT AVG(duration_sec) FROM calls WHERE duration_sec > 0").fetchone()
        avg_duration = round(avg_dur_row[0] or 0.0, 1)

        return {
            "total_calls": total_calls,
            "total_recovered": total_recovered,
            "recovered_count": retry_recovered,
            "paid_links_count": link_recovered,
            "link_sent_count": link_sent_count,
            "scheduled_count": scheduled_count,
            "escalated_count": escalate_count,
            "declined_count": declined_count,
            "verification_failed_count": failed_count,
            "wrong_party_count": wrong_party_count,
            "no_answer_count": no_answer_count,
            "recovery_rate": round(recovery_rate, 1),
            "average_duration_sec": avg_duration,
            "outcomes_breakdown": outcomes_counts,
        }


def save_outcome(outcome: Outcome, db_path: Path = DB_PATH) -> int:
    """Insert into legacy outcomes table and update customer state."""
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
    """Fetch legacy outcomes, optionally filtered by customer_id."""
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
