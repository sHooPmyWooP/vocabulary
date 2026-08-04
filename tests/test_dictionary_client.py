"""Tests for dictionary_client: mocked HTTP, no live network."""
from __future__ import annotations

import httpx
import pytest

from app.dictionary_client import LookupResult, NotFound, lookup

# A trimmed but realistic multi-sense Free Dictionary API payload.
MULTISENSE_PAYLOAD = [
    {
        "word": "run",
        "phonetic": "/ɹʌn/",
        "meanings": [
            {
                "partOfSpeech": "verb",
                "definitions": [
                    {
                        "definition": "To move rapidly on foot.",
                        "example": "I run every morning.",
                    },
                    {"definition": "To operate or function."},
                ],
                "synonyms": ["sprint", "dash"],
            },
            {
                "partOfSpeech": "noun",
                "definitions": [
                    {"definition": "An act of running.", "example": "a morning run"}
                ],
                "synonyms": ["jog"],
            },
        ],
    }
]


def _client_returning(status_code: int, json_body):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=json_body)

    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport)


def test_multisense_payload_parses_all_senses():
    client = _client_returning(200, MULTISENSE_PAYLOAD)
    result = lookup("Run ", client=client)

    assert isinstance(result, LookupResult)
    assert result.word == "run"  # normalized
    assert result.payload == MULTISENSE_PAYLOAD  # full raw payload preserved
    assert len(result.senses) == 2
    verb, noun = result.senses
    assert verb.part_of_speech == "verb"
    assert verb.definitions[0].definition == "To move rapidly on foot."
    assert verb.definitions[0].example == "I run every morning."
    assert verb.synonyms == ["sprint", "dash"]
    assert noun.part_of_speech == "noun"
    assert noun.definitions[0].example == "a morning run"


def test_404_maps_to_not_found():
    client = _client_returning(404, {"title": "No Definitions Found"})
    result = lookup("asdfqwer", client=client)

    assert isinstance(result, NotFound)
    assert result.word == "asdfqwer"
