"""SQLite database lifecycle and schema bootstrapping."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

# Default location; overridable via env for the container's mounted volume.
DEFAULT_DB_PATH = os.environ.get("VOCAB_DB_PATH", "data/vocab.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    word          TEXT    NOT NULL UNIQUE,
    payload       TEXT    NOT NULL,
    added_at      TEXT    NOT NULL,
    lookup_count  INTEGER NOT NULL DEFAULT 1,
    ease_factor   REAL    NOT NULL DEFAULT 2.5,
    interval      INTEGER NOT NULL DEFAULT 0,
    repetitions   INTEGER NOT NULL DEFAULT 0,
    due_date      TEXT    NOT NULL,
    state         TEXT    NOT NULL DEFAULT 'new'
);

CREATE TABLE IF NOT EXISTS review_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id   INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    graded_at  TEXT    NOT NULL,
    grade      TEXT    NOT NULL
);
"""


def connect(db_path: str | os.PathLike[str] = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a SQLite connection with sensible defaults and row access by name."""
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables if they do not yet exist."""
    conn.executescript(SCHEMA)
    conn.commit()
