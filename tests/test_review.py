"""Tests for the review mode HTTP endpoints (HTMX fragments)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import dictionary_client, vocab_store
from app.db import connect, init_db
from app.main import create_app

PAYLOAD = [
    {
        "word": "run",
        "meanings": [
            {
                "partOfSpeech": "verb",
                "definitions": [
                    {"definition": "To move rapidly.", "example": "I run daily."}
                ],
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


def test_review_shows_due_card_front_with_word():
    client, conn = make_client()
    vocab_store.add_entry(conn, "run", PAYLOAD)

    resp = client.get("/review")
    assert resp.status_code == 200
    body = resp.text
    # Front shows the English word.
    assert "run" in body
    assert "Source: Free Dictionary API" in body
    # Four grade buttons present.
    for label in ("Again", "Hard", "Good", "Easy"):
        assert label in body
    # Back content (definition/example/synonyms) is rendered for the flip.
    assert "To move rapidly." in body
    assert "sprint" in body


def test_review_shows_stored_german_translation():
    client, conn = make_client()
    canonical = {
        "schema": "canonical/1",
        "word": "run",
        "source": "azure-ai-foundry",
        "generated": True,
        "senses": [
            {
                "part_of_speech": "verb",
                "definitions": [{"definition": "To move rapidly.", "example": None}],
                "synonyms": [],
            }
        ],
        "translations": {
            "de": {
                "provider": "azure-ai-foundry",
                "senses": [
                    {
                        "translation": "laufen",
                        "explanation": "Sich schnell zu Fuß bewegen.",
                    }
                ],
            }
        },
    }
    vocab_store.add_entry(conn, "run", canonical)

    resp = client.get("/review")

    assert "Deutsch: laufen" in resp.text
    assert "Sich schnell zu Fuß bewegen." in resp.text
    assert "Source: Azure AI Foundry" in resp.text
    assert "AI-generated definition" in resp.text


def test_review_shows_wiktionary_source():
    client, conn = make_client()
    canonical = {
        "schema": "canonical/1",
        "word": "kick the bucket",
        "source": "wiktionary",
        "senses": [
            {
                "part_of_speech": "idiom",
                "definitions": [{"definition": "To die.", "example": None}],
                "synonyms": [],
            }
        ],
    }
    vocab_store.add_entry(conn, "kick the bucket", canonical)

    resp = client.get("/review")

    assert "Source: Wiktionary" in resp.text


def test_review_empty_state_when_nothing_due():
    client, _ = make_client()
    resp = client.get("/review")
    assert resp.status_code == 200
    assert "caught up" in resp.text.lower() or "no cards" in resp.text.lower()


def test_grading_reschedules_and_logs_and_advances():
    client, conn = make_client()
    e1 = vocab_store.add_entry(conn, "run", PAYLOAD)
    vocab_store.add_entry(conn, "walk", PAYLOAD)

    resp = client.post(f"/review/{e1.id}/grade", data={"grade": "good"})
    assert resp.status_code == 200

    # A review-log row was appended.
    assert conn.execute("SELECT COUNT(*) FROM review_log").fetchone()[0] == 1
    # The graded card is no longer due today (interval 1 -> tomorrow).
    updated = vocab_store.get_by_id(conn, e1.id)
    assert updated.repetitions == 1
    assert updated.due_date > updated.added_at[:10]
    # The next due card ("walk") is served.
    assert "walk" in resp.text


def test_grading_last_card_shows_done():
    client, conn = make_client()
    e1 = vocab_store.add_entry(conn, "run", PAYLOAD)

    resp = client.post(f"/review/{e1.id}/grade", data={"grade": "easy"})
    assert resp.status_code == 200
    assert "caught up" in resp.text.lower() or "no cards" in resp.text.lower()


def test_home_due_count_reflects_real_due_cards():
    client, conn = make_client()
    vocab_store.add_entry(conn, "run", PAYLOAD)
    vocab_store.add_entry(conn, "walk", PAYLOAD)

    resp = client.get("/")
    assert resp.status_code == 200
    assert 'data-testid="due-today">2<' in resp.text
