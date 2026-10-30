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
    note: str = ""


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
        note=row["note"] if "note" in row.keys() else "",
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


def update_payload(conn: sqlite3.Connection, entry_id: int, payload: Any) -> Entry:
    """Replace an entry's stored dictionary payload."""
    if get_by_id(conn, entry_id) is None:
        raise ValueError(f"no entry with id {entry_id}")
    conn.execute(
        "UPDATE entries SET payload = ? WHERE id = ?",
        (json.dumps(payload), entry_id),
    )
    conn.commit()
    return get_by_id(conn, entry_id)  # type: ignore[return-value]


def all_reviews(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every review-log row, for the stats aggregation module."""
    return conn.execute(
        "SELECT entry_id, graded_at, grade FROM review_log"
    ).fetchall()


def delete_entry(conn: sqlite3.Connection, entry_id: int) -> None:
    """Delete an entry (and its review-log rows via cascade)."""
    conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
    conn.commit()


# Browse/manage sort keys mapped to safe ORDER BY clauses (never user SQL).
_SORTS: dict[str, str] = {
    "added": "added_at DESC, id DESC",
    "due": "due_date ASC, id ASC",
    "maturity": "interval ASC, id ASC",
}


def list_entries(
    conn: sqlite3.Connection,
    *,
    search: str | None = None,
    sort: str = "added",
) -> list[Entry]:
    """List entries for the browse screen, optionally filtered and sorted.

    ``search`` filters by word (normalized substring, case-insensitive).
    ``sort`` is one of ``added`` (newest first), ``due`` (soonest first) or
    ``maturity`` (least mature first, by SM-2 interval).
    """
    clauses = _SORTS.get(sort, _SORTS["added"])
    sql = "SELECT * FROM entries"
    params: list[Any] = []
    if search and search.strip():
        sql += " WHERE word LIKE ?"
        params.append(f"%{normalize(search)}%")
    sql += f" ORDER BY {clauses}"
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_entry(r) for r in rows]


def update_entry(
    conn: sqlite3.Connection,
    entry_id: int,
    *,
    word: str | None = None,
    note: str | None = None,
) -> Entry:
    """Inline-edit an entry's word and/or note.

    The word is re-normalized (trimmed, lowercased). A blank word is rejected.
    Fields left as ``None`` are unchanged.
    """
    entry = get_by_id(conn, entry_id)
    if entry is None:
        raise ValueError(f"no entry with id {entry_id}")

    new_word = entry.word
    if word is not None:
        new_word = normalize(word)
        if not new_word:
            raise ValueError("word must not be blank")
    new_note = entry.note if note is None else note.strip()

    conn.execute(
        "UPDATE entries SET word = ?, note = ? WHERE id = ?",
        (new_word, new_note, entry_id),
    )
    conn.commit()
    return get_by_id(conn, entry_id)  # type: ignore[return-value]


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
