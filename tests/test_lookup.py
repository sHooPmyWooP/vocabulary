"""Tests for the lookup mode HTTP endpoints (HTMX fragments)."""
from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from app import dictionary_client
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


def make_client(tmp_path, monkeypatch, status=200, body=None):
    conn = connect(":memory:")
    init_db(conn)

    def fake_lookup(word, *, client=None):
        if status == 404:
            return dictionary_client.NotFound(word=dictionary_client.normalize(word))
        return dictionary_client._parse(dictionary_client.normalize(word), body or PAYLOAD)

    monkeypatch.setattr("app.main.dictionary_client.lookup", fake_lookup)
    monkeypatch.setattr("app.main.translation_client.translate", lambda result: None)
    monkeypatch.setattr(
        "app.main.translation_client.generate_lookup", lambda word: None
    )
    app = create_app(conn)
    return TestClient(app), conn


def test_lookup_success_shows_senses_and_autoadds(tmp_path, monkeypatch):
    client, conn = make_client(tmp_path, monkeypatch)
    resp = client.post("/lookup", data={"word": "Run "})

    assert resp.status_code == 200
    body = resp.text
    assert "To move rapidly." in body
    assert "verb" in body
    assert "sprint" in body
    assert "Source: Free Dictionary API" in body
    # Auto-added exactly one row.
    assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 1
    # Undo affordance present.
    assert "undo" in body.lower() or "remove" in body.lower()


def test_lookup_renders_and_stores_german_translation(tmp_path, monkeypatch):
    client, conn = make_client(tmp_path, monkeypatch)
    generated = dictionary_client._parse("run", PAYLOAD)
    from app import translation_client

    monkeypatch.setattr(
        "app.main.translation_client.translate",
        lambda result: translation_client.TranslationResult(
            language="de",
            senses=[
                translation_client.SenseTranslation(
                    translation="laufen",
                    explanation="Sich schnell zu Fuß bewegen.",
                )
            ],
        ),
    )

    resp = client.post("/lookup", data={"word": generated.word})

    assert "Deutsch: laufen" in resp.text
    assert "Sich schnell zu Fuß bewegen." in resp.text
    stored = conn.execute("SELECT payload FROM entries").fetchone()[0]
    assert '"translation": "laufen"' in stored


def test_dictionary_miss_uses_foundry_fallback(tmp_path, monkeypatch):
    client, conn = make_client(tmp_path, monkeypatch, status=404)
    from app import translation_client

    generated_result = dictionary_client.LookupResult(
        word="spill the tea",
        senses=[
            dictionary_client.Sense(
                part_of_speech="idiom",
                definitions=[
                    dictionary_client.Definition(
                        definition="To share gossip.",
                        example="Come on, spill the tea.",
                    )
                ],
                synonyms=["gossip"],
            )
        ],
        payload={},
        source="azure-ai-foundry",
    )
    calls = 0

    def generate(word):
        nonlocal calls
        calls += 1
        return translation_client.GeneratedLookup(
            result=generated_result,
            translation=translation_client.TranslationResult(
                language="de",
                senses=[
                    translation_client.SenseTranslation(
                        "auspacken", "Klatsch oder Geheimnisse erzählen."
                    )
                ],
            ),
        )

    monkeypatch.setattr("app.main.translation_client.generate_lookup", generate)

    resp = client.post("/lookup", data={"word": "spill the tea"})
    repeated = client.post("/lookup", data={"word": "SPILL THE TEA"})

    assert "To share gossip." in resp.text
    assert "Deutsch: auspacken" in resp.text
    assert "Source: Azure AI Foundry" in resp.text
    assert "AI-generated definition" in resp.text
    stored = conn.execute("SELECT word, payload FROM entries").fetchone()
    assert stored["word"] == "spill the tea"
    assert '"generated": true' in stored["payload"]
    assert "Deutsch: auspacken" in repeated.text
    assert calls == 1


def test_lookup_404_shows_not_found_and_adds_nothing(tmp_path, monkeypatch):
    client, conn = make_client(tmp_path, monkeypatch, status=404)
    resp = client.post("/lookup", data={"word": "asdfqwer"})

    assert resp.status_code == 200
    assert "not found" in resp.text.lower()
    assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0


def test_repeat_lookup_dedupes_and_increments(tmp_path, monkeypatch):
    client, conn = make_client(tmp_path, monkeypatch)
    client.post("/lookup", data={"word": "run"})
    resp = client.post("/lookup", data={"word": "RUN "})

    assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 1
    count = conn.execute("SELECT lookup_count FROM entries").fetchone()[0]
    assert count == 2
    # Surfaces that it was already known.
    assert "2" in resp.text


def test_remove_deletes_entry(tmp_path, monkeypatch):
    client, conn = make_client(tmp_path, monkeypatch)
    client.post("/lookup", data={"word": "run"})
    entry_id = conn.execute("SELECT id FROM entries").fetchone()[0]

    resp = client.delete(f"/entry/{entry_id}")
    assert resp.status_code == 200
    assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0


def test_lookup_page_has_focused_search_box(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    resp = client.get("/lookup")
    assert resp.status_code == 200
    assert "autofocus" in resp.text.lower()
    assert 'name="word"' in resp.text
