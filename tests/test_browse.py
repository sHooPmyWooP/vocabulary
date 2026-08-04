"""Tests for the browse/manage mode HTTP endpoints (HTMX fragments)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import vocab_store
from app.db import connect, init_db
from app.main import create_app

PAYLOAD = [
    {
        "word": "run",
        "meanings": [
            {
                "partOfSpeech": "verb",
                "definitions": [{"definition": "To move rapidly."}],
                "synonyms": ["sprint"],
            }
        ],
    }
]


def make_client():
    conn = connect(":memory:")
    init_db(conn)
    app = create_app(conn)
    return TestClient(app), conn


def test_browse_lists_all_words():
    client, conn = make_client()
    vocab_store.add_entry(conn, "run", PAYLOAD)
    vocab_store.add_entry(conn, "walk", PAYLOAD)

    resp = client.get("/browse")
    assert resp.status_code == 200
    assert "run" in resp.text
    assert "walk" in resp.text


def test_browse_search_filters_the_list():
    client, conn = make_client()
    vocab_store.add_entry(conn, "running", PAYLOAD)
    vocab_store.add_entry(conn, "walk", PAYLOAD)

    resp = client.get("/browse", params={"q": "run"})
    assert resp.status_code == 200
    assert "running" in resp.text
    assert "walk" not in resp.text


def test_browse_sort_by_due_orders_soonest_first():
    client, conn = make_client()
    a = vocab_store.add_entry(conn, "alpha", PAYLOAD)
    b = vocab_store.add_entry(conn, "bravo", PAYLOAD)
    conn.execute("UPDATE entries SET due_date = ? WHERE id = ?", ("2024-05-01", a.id))
    conn.execute("UPDATE entries SET due_date = ? WHERE id = ?", ("2024-01-01", b.id))
    conn.commit()

    resp = client.get("/browse", params={"sort": "due"})
    body = resp.text
    assert body.index("bravo") < body.index("alpha")


def test_edit_entry_updates_word_and_note():
    client, conn = make_client()
    e = vocab_store.add_entry(conn, "colour", PAYLOAD)

    resp = client.post(
        f"/entry/{e.id}/edit", data={"word": "Color", "note": "US spelling"}
    )
    assert resp.status_code == 200
    assert "color" in resp.text
    assert "US spelling" in resp.text

    reloaded = vocab_store.get_by_id(conn, e.id)
    assert reloaded.word == "color"
    assert reloaded.note == "US spelling"


def test_edit_form_endpoint_returns_inputs():
    client, conn = make_client()
    e = vocab_store.add_entry(conn, "run", PAYLOAD)

    resp = client.get(f"/entry/{e.id}/edit")
    assert resp.status_code == 200
    assert 'name="word"' in resp.text
    assert 'name="note"' in resp.text
    assert "run" in resp.text


def test_delete_entry_from_browse_removes_row():
    client, conn = make_client()
    e = vocab_store.add_entry(conn, "run", PAYLOAD)

    resp = client.delete(f"/entry/{e.id}")
    assert resp.status_code == 200
    assert vocab_store.get_by_id(conn, e.id) is None
