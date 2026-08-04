"""Tests for vocab_store: temp SQLite DB, public-interface assertions."""
from __future__ import annotations

import json

import pytest

from app import vocab_store
from app.db import connect, init_db


@pytest.fixture()
def conn():
    c = connect(":memory:")
    init_db(c)
    yield c
    c.close()


PAYLOAD = [{"word": "run", "meanings": [{"partOfSpeech": "verb"}]}]


def test_add_entry_stores_full_payload_and_normalizes(conn):
    entry = vocab_store.add_entry(conn, "Run ", PAYLOAD)

    assert entry.word == "run"
    assert entry.lookup_count == 1
    assert entry.state == "new"
    # Full dictionary JSON payload round-trips.
    assert json.loads(entry.payload) == PAYLOAD
    # New words are due the same day they are added.
    assert entry.due_date == entry.added_at[:10]


def test_dedupe_on_normalized_word_no_duplicate_row(conn):
    first = vocab_store.add_entry(conn, "Run", PAYLOAD)
    second = vocab_store.add_entry(conn, "  run  ", PAYLOAD)

    assert first.id == second.id
    count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    assert count == 1


def test_repeat_lookup_increments_lookup_count(conn):
    vocab_store.add_entry(conn, "run", PAYLOAD)
    again = vocab_store.add_entry(conn, "RUN", PAYLOAD)

    assert again.lookup_count == 2
    third = vocab_store.add_entry(conn, "run ", PAYLOAD)
    assert third.lookup_count == 3


def test_get_by_word_returns_existing_or_none(conn):
    assert vocab_store.get_by_word(conn, "run") is None
    added = vocab_store.add_entry(conn, "Run", PAYLOAD)
    found = vocab_store.get_by_word(conn, " RUN ")
    assert found is not None and found.id == added.id


def test_delete_entry_removes_row(conn):
    entry = vocab_store.add_entry(conn, "run", PAYLOAD)
    vocab_store.delete_entry(conn, entry.id)

    assert vocab_store.get_by_word(conn, "run") is None
    count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    assert count == 0
