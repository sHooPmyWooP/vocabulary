"""Persistence boundary over SQLite for vocabulary entries.

Stores the full dictionary JSON payload plus SM-2 scheduling fields, dedupes
on the normalized word, and increments the lookup count on repeat lookups.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from app import scheduler
from app.dictionary_client import normalize

DEFAULT_NEW_CARD_LIMIT = 20


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


def _today_iso(today: date | str | None) -> str:
    if today is None:
        return date.today().isoformat()
    return today.isoformat() if isinstance(today, date) else today


def due_cards(
    conn: sqlite3.Connection,
    *,
    today: date | str | None = None,
    new_limit: int = DEFAULT_NEW_CARD_LIMIT,
) -> list[Entry]:
    """Return all cards due on or before ``today``.

    Ordered by due date ascending, then randomised within the same due bucket.
    Reviewed cards have no cap; brand-new (never-reviewed) cards are limited to
    ``new_limit`` per session so a big reading day cannot bury future reviews.
    """
    today_s = _today_iso(today)
    rows = conn.execute(
        "SELECT * FROM entries WHERE due_date <= ? ORDER BY due_date ASC, RANDOM()",
        (today_s,),
    ).fetchall()

    result: list[Entry] = []
    new_seen = 0
    for row in rows:
        entry = _row_to_entry(row)
        if entry.state == "new":
            if new_seen >= new_limit:
                continue
            new_seen += 1
        result.append(entry)
    return result


def due_count(
    conn: sqlite3.Connection,
    *,
    today: date | str | None = None,
    new_limit: int = DEFAULT_NEW_CARD_LIMIT,
) -> int:
    """Number of cards that would appear in today's review session."""
    return len(due_cards(conn, today=today, new_limit=new_limit))


def record_review(
    conn: sqlite3.Connection,
    entry_id: int,
    grade: str,
    *,
    today: date | str | None = None,
) -> Entry:
    """Grade a card: reschedule it (SM-2) and append a review-log row."""
    entry = get_by_id(conn, entry_id)
    if entry is None:
        raise ValueError(f"no entry with id {entry_id}")

    today_date = date.today() if today is None else (
        today if isinstance(today, date) else date.fromisoformat(today)
    )
    state = scheduler.SchedulingState(
        ease_factor=entry.ease_factor,
        interval=entry.interval,
        repetitions=entry.repetitions,
    )
    outcome = scheduler.schedule(state, grade, today=today_date)

    conn.execute(
        """
        UPDATE entries
        SET ease_factor = ?, interval = ?, repetitions = ?, due_date = ?, state = ?
        WHERE id = ?
        """,
        (
            outcome.ease_factor,
            outcome.interval,
            outcome.repetitions,
            outcome.due_date.isoformat(),
            outcome.state,
            entry_id,
        ),
    )
    conn.execute(
        "INSERT INTO review_log (entry_id, graded_at, grade) VALUES (?, ?, ?)",
        (entry_id, datetime.now(timezone.utc).isoformat(), grade),
    )
    conn.commit()
    return get_by_id(conn, entry_id)  # type: ignore[return-value]
