"""Tests for vocab_store: temp SQLite DB, public-interface assertions."""
from __future__ import annotations

import json
from datetime import date, timedelta

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


def _set_due(conn, entry_id, due):
    conn.execute(
        "UPDATE entries SET due_date = ? WHERE id = ?", (due, entry_id)
    )
    conn.commit()


def test_newly_added_word_is_due_today(conn):
    vocab_store.add_entry(conn, "run", PAYLOAD)
    due = vocab_store.due_cards(conn, today=date.today())
    assert [e.word for e in due] == ["run"]


def test_due_cards_excludes_future_and_orders_by_due_date(conn):
    today = date(2024, 1, 10)
    a = vocab_store.add_entry(conn, "alpha", PAYLOAD)
    b = vocab_store.add_entry(conn, "bravo", PAYLOAD)
    c = vocab_store.add_entry(conn, "charlie", PAYLOAD)
    _set_due(conn, a.id, "2024-01-05")  # oldest due first
    _set_due(conn, b.id, "2024-01-09")
    _set_due(conn, c.id, "2024-01-20")  # future, excluded

    due = vocab_store.due_cards(conn, today=today)
    assert [e.word for e in due] == ["alpha", "bravo"]


def test_new_card_daily_limit_is_respected(conn):
    for i in range(5):
        vocab_store.add_entry(conn, f"word{i}", PAYLOAD)

    due = vocab_store.due_cards(conn, today=date.today(), new_limit=3)
    assert len(due) == 3
    assert vocab_store.due_count(conn, today=date.today(), new_limit=3) == 3


def test_new_limit_does_not_cap_reviewed_cards(conn):
    # Two cards already in review (not 'new') plus three fresh new cards.
    reviewed = [vocab_store.add_entry(conn, f"seen{i}", PAYLOAD) for i in range(2)]
    for e in reviewed:
        vocab_store.record_review(conn, e.id, "good", today=date(2024, 1, 1))
        _set_due(conn, e.id, "2024-01-01")  # force back to due
    for i in range(3):
        f = vocab_store.add_entry(conn, f"fresh{i}", PAYLOAD)
        _set_due(conn, f.id, "2024-01-01")

    due = vocab_store.due_cards(conn, today=date(2024, 1, 1), new_limit=1)
    # 2 reviewed (uncapped) + 1 new (capped) == 3
    assert len(due) == 3


def test_record_review_reschedules_and_logs(conn):
    entry = vocab_store.add_entry(conn, "run", PAYLOAD)
    updated = vocab_store.record_review(conn, entry.id, "good", today=date(2024, 1, 1))

    assert updated.repetitions == 1
    assert updated.interval == 1
    assert updated.due_date == "2024-01-02"
    assert updated.state == "learning"

    log = conn.execute("SELECT entry_id, grade FROM review_log").fetchone()
    assert log["entry_id"] == entry.id
    assert log["grade"] == "good"


def test_record_review_again_resets_and_keeps_due(conn):
    entry = vocab_store.add_entry(conn, "run", PAYLOAD)
    vocab_store.record_review(conn, entry.id, "good", today=date(2024, 1, 1))
    vocab_store.record_review(conn, entry.id, "good", today=date(2024, 1, 2))
    lapsed = vocab_store.record_review(conn, entry.id, "again", today=date(2024, 1, 8))

    assert lapsed.repetitions == 0
    assert lapsed.interval == 1
    assert conn.execute("SELECT COUNT(*) FROM review_log").fetchone()[0] == 3


# --- Browse / manage --------------------------------------------------------


def test_list_entries_returns_all(conn):
    vocab_store.add_entry(conn, "run", PAYLOAD)
    vocab_store.add_entry(conn, "walk", PAYLOAD)
    vocab_store.add_entry(conn, "jump", PAYLOAD)

    words = {e.word for e in vocab_store.list_entries(conn)}
    assert words == {"run", "walk", "jump"}


def test_list_entries_search_filters_case_insensitively(conn):
    vocab_store.add_entry(conn, "running", PAYLOAD)
    vocab_store.add_entry(conn, "runner", PAYLOAD)
    vocab_store.add_entry(conn, "walk", PAYLOAD)

    hits = {e.word for e in vocab_store.list_entries(conn, search="RUN")}
    assert hits == {"running", "runner"}


def test_list_entries_sort_by_added_is_newest_first(conn):
    a = vocab_store.add_entry(conn, "alpha", PAYLOAD)
    b = vocab_store.add_entry(conn, "bravo", PAYLOAD)
    # Force a stable added_at ordering independent of clock resolution.
    conn.execute("UPDATE entries SET added_at = ? WHERE id = ?", ("2024-01-01T00:00:00+00:00", a.id))
    conn.execute("UPDATE entries SET added_at = ? WHERE id = ?", ("2024-02-01T00:00:00+00:00", b.id))
    conn.commit()

    ordered = [e.word for e in vocab_store.list_entries(conn, sort="added")]
    assert ordered == ["bravo", "alpha"]


def test_list_entries_sort_by_due_date_ascending(conn):
    a = vocab_store.add_entry(conn, "alpha", PAYLOAD)
    b = vocab_store.add_entry(conn, "bravo", PAYLOAD)
    _set_due(conn, a.id, "2024-03-10")
    _set_due(conn, b.id, "2024-01-05")

    ordered = [e.word for e in vocab_store.list_entries(conn, sort="due")]
    assert ordered == ["bravo", "alpha"]


def test_list_entries_sort_by_maturity(conn):
    new = vocab_store.add_entry(conn, "newbie", PAYLOAD)
    learning = vocab_store.add_entry(conn, "midway", PAYLOAD)
    mature = vocab_store.add_entry(conn, "veteran", PAYLOAD)
    conn.execute("UPDATE entries SET interval = 0 WHERE id = ?", (new.id,))
    conn.execute("UPDATE entries SET interval = 5 WHERE id = ?", (learning.id,))
    conn.execute("UPDATE entries SET interval = 40 WHERE id = ?", (mature.id,))
    conn.commit()

    ordered = [e.word for e in vocab_store.list_entries(conn, sort="maturity")]
    assert ordered == ["newbie", "midway", "veteran"]


def test_update_entry_edits_word_and_note(conn):
    entry = vocab_store.add_entry(conn, "colour", PAYLOAD)
    updated = vocab_store.update_entry(conn, entry.id, word="Color", note="US spelling")

    assert updated.word == "color"  # re-normalized
    assert updated.note == "US spelling"
    # Round-trips from the store.
    reloaded = vocab_store.get_by_id(conn, entry.id)
    assert reloaded.word == "color"
    assert reloaded.note == "US spelling"


def test_update_entry_rejects_blank_word(conn):
    entry = vocab_store.add_entry(conn, "run", PAYLOAD)
    with pytest.raises(ValueError):
        vocab_store.update_entry(conn, entry.id, word="   ")


def test_update_entry_missing_id_raises(conn):
    with pytest.raises(ValueError):
        vocab_store.update_entry(conn, 999, note="nope")


def test_delete_entry_via_browse_removes_row(conn):
    e = vocab_store.add_entry(conn, "run", PAYLOAD)
    vocab_store.delete_entry(conn, e.id)
    assert vocab_store.list_entries(conn) == []
