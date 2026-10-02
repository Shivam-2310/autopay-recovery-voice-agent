"""SQLite persistence for call outcomes and transcripts."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.models import Outcome

DB_PATH = Path(__file__).resolve().parent.parent / "outcomes.db"

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
"""


def get_conn(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Return a connection with WAL mode enabled for safe concurrent reads."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    """Create the outcomes table if it doesn't exist."""
    with get_conn(db_path) as conn:
        conn.executescript(_SCHEMA)


def save_outcome(outcome: Outcome, db_path: Path = DB_PATH) -> int:
    """Insert an outcome and return the row ID."""
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
        return cursor.lastrowid  # type: ignore[return-value]


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
