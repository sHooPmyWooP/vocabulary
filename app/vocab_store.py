"""Persistence boundary over SQLite for vocabulary entries.

Stores the full dictionary JSON payload plus SM-2 scheduling fields, dedupes
on the normalized word, and increments the lookup count on repeat lookups.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.dictionary_client import normalize


@dataclass(frozen=True)
class Entry:
    id: int
    word: str
    payload: str
    added_at: str
    lookup_count: int
    ease_factor: float
    interval: int
    repetitions: int
    due_date: str
    state: str


def _row_to_entry(row: sqlite3.Row) -> Entry:
    return Entry(
        id=row["id"],
        word=row["word"],
        payload=row["payload"],
        added_at=row["added_at"],
        lookup_count=row["lookup_count"],
        ease_factor=row["ease_factor"],
        interval=row["interval"],
        repetitions=row["repetitions"],
        due_date=row["due_date"],
        state=row["state"],
    )


def get_by_word(conn: sqlite3.Connection, word: str) -> Entry | None:
    """Return the entry matching the normalized word, or None."""
    row = conn.execute(
        "SELECT * FROM entries WHERE word = ?", (normalize(word),)
    ).fetchone()
    return _row_to_entry(row) if row else None


def get_by_id(conn: sqlite3.Connection, entry_id: int) -> Entry | None:
    row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    return _row_to_entry(row) if row else None


def add_entry(conn: sqlite3.Connection, word: str, payload: Any) -> Entry:
    """Insert a new entry, or bump the lookup count of an existing one.

    Dedupes on the normalized word. New words are due the same day they are
    added. The full dictionary JSON payload is stored verbatim.
    """
    normalized = normalize(word)
    existing = get_by_word(conn, normalized)
    if existing is not None:
        conn.execute(
            "UPDATE entries SET lookup_count = lookup_count + 1 WHERE id = ?",
            (existing.id,),
        )
        conn.commit()
        return get_by_id(conn, existing.id)  # type: ignore[return-value]

    now = datetime.now(timezone.utc).isoformat()
    due = now[:10]
    cur = conn.execute(
        """
        INSERT INTO entries (word, payload, added_at, lookup_count, due_date, state)
        VALUES (?, ?, ?, 1, ?, 'new')
        """,
        (normalized, json.dumps(payload), now, due),
    )
    conn.commit()
    return get_by_id(conn, cur.lastrowid)  # type: ignore[return-value]


def delete_entry(conn: sqlite3.Connection, entry_id: int) -> None:
    """Delete an entry (and its review-log rows via cascade)."""
    conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
    conn.commit()
