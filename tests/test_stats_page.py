"""Tests for the stats screen HTTP endpoint (renders the pure aggregation)."""
from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app import vocab_store
from app.db import connect, init_db
from app.main import create_app

PAYLOAD = [
    {
        "word": "run",
        "meanings": [
            {"partOfSpeech": "verb", "definitions": [{"definition": "To move."}]}
        ],
    }
]


def make_client():
    conn = connect(":memory:")
    init_db(conn)
    app = create_app(conn)
    return TestClient(app), conn


def _number(body: str, testid: str) -> str:
    m = re.search(rf'data-testid="{testid}"[^>]*>\s*([\d.]+)', body)
    assert m, f"{testid} not found"
    return m.group(1)


def test_stats_zero_state():
    client, _ = make_client()
    resp = client.get("/stats")
    assert resp.status_code == 200
    body = resp.text
    assert _number(body, "total-words") == "0"
    assert _number(body, "due-today") == "0"
    assert 'data-testid="reviews-chart"' in body


def test_stats_reflects_words_and_reviews():
    client, conn = make_client()
    vocab_store.add_entry(conn, "run", PAYLOAD)
    vocab_store.add_entry(conn, "walk", PAYLOAD)
    # One review of a card.
    entry = vocab_store.get_by_word(conn, "run")
    vocab_store.record_review(conn, entry.id, "good")

    resp = client.get("/stats")
    body = resp.text
    assert _number(body, "total-words") == "2"
    # Two new words become due same day; one got reviewed and rescheduled out.
    assert 'data-testid="maturity"' in body
    assert _number(body, "accuracy") == "100.0"


def test_stats_chart_has_thirty_bars():
    client, _ = make_client()
    resp = client.get("/stats")
    bars = resp.text.count('class="bar-col"')
    assert bars == 30
