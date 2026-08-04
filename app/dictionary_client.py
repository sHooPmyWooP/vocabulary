"""Wraps the Free Dictionary API (dictionaryapi.dev).

Input: a raw word. Output: a normalized ``LookupResult`` containing all
senses plus the full raw JSON payload, or an explicit ``NotFound``.
HTTP, response parsing and the 404 case are all hidden behind ``lookup``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

API_BASE = "https://api.dictionaryapi.dev/api/v2/entries/en"


def normalize(word: str) -> str:
    """Normalize a word for matching/dedupe: trimmed and lowercased."""
    return word.strip().lower()


@dataclass(frozen=True)
class Definition:
    definition: str
    example: str | None = None


@dataclass(frozen=True)
class Sense:
    part_of_speech: str
    definitions: list[Definition]
    synonyms: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LookupResult:
    word: str
    senses: list[Sense]
    payload: Any


@dataclass(frozen=True)
class NotFound:
    word: str


def _parse(word: str, payload: Any) -> LookupResult:
    senses: list[Sense] = []
    for entry in payload:
        for meaning in entry.get("meanings", []):
            definitions = [
                Definition(
                    definition=d.get("definition", ""),
                    example=d.get("example"),
                )
                for d in meaning.get("definitions", [])
            ]
            senses.append(
                Sense(
                    part_of_speech=meaning.get("partOfSpeech", ""),
                    definitions=definitions,
                    synonyms=list(meaning.get("synonyms", [])),
                )
            )
    return LookupResult(word=word, senses=senses, payload=payload)


def lookup(
    word: str, *, client: httpx.Client | None = None
) -> LookupResult | NotFound:
    """Look a word up in the Free Dictionary API.

    Returns a ``LookupResult`` on success or ``NotFound`` on 404.
    A pre-built ``httpx.Client`` may be injected for testing.
    """
    normalized = normalize(word)
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=10.0)
    try:
        resp = client.get(f"{API_BASE}/{normalized}")
        if resp.status_code == 404:
            return NotFound(word=normalized)
        resp.raise_for_status()
        return _parse(normalized, resp.json())
    finally:
        if owns_client:
            client.close()
