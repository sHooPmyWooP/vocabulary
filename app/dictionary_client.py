"""Dictionary lookups over two sources with automatic routing.

Single words go to the Free Dictionary API (dictionaryapi.dev). Multi-word
input (phrases, sayings, idioms) goes to the Wiktionary REST API, which
dictionaryapi.dev does not cover. Both sources normalize into the same
``LookupResult`` (senses) or an explicit ``NotFound``, so callers never see
which source answered. ``LookupResult.payload`` holds the raw API payload;
use ``to_canonical`` to get a source-agnostic dict for storage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

API_BASE = "https://api.dictionaryapi.dev/api/v2/entries/en"
WIKTIONARY_BASE = "https://en.wiktionary.org/api/rest_v1/page/definition"
WIKTIONARY_SEARCH = "https://en.wiktionary.org/w/api.php"
# Wikimedia's REST API rejects generic clients; a descriptive UA is required.
WIKTIONARY_HEADERS = {
    "User-Agent": "vocabulary-app/0.1 (self-hosted vocabulary memorization webapp)"
}


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
    source: str = ""


@dataclass(frozen=True)
class NotFound:
    word: str


@dataclass(frozen=True)
class LookupError:
    """A transient upstream failure (5xx, timeout, network error).

    Distinct from ``NotFound``: the word may well exist, the source just
    could not be reached. The UI invites the user to retry.
    """

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
    return LookupResult(
        word=word,
        senses=senses,
        payload=payload,
        source="free-dictionary-api",
    )


def to_canonical(result: LookupResult) -> dict:
    """Serialize a ``LookupResult`` into a source-agnostic canonical payload.

    This is what gets stored, so the read path never has to know which API
    produced an entry. Read it back with ``senses_from_canonical``.
    """
    return {
        "schema": "canonical/1",
        "word": result.word,
        "source": result.source,
        "senses": [
            {
                "part_of_speech": s.part_of_speech,
                "definitions": [
                    {"definition": d.definition, "example": d.example}
                    for d in s.definitions
                ],
                "synonyms": list(s.synonyms),
            }
            for s in result.senses
        ],
    }


def senses_from_canonical(payload: dict) -> list[Sense]:
    """Rebuild senses from a canonical payload produced by ``to_canonical``."""
    return [
        Sense(
            part_of_speech=s.get("part_of_speech", ""),
            definitions=[
                Definition(
                    definition=d.get("definition", ""),
                    example=d.get("example"),
                )
                for d in s.get("definitions", [])
            ],
            synonyms=list(s.get("synonyms", [])),
        )
        for s in payload.get("senses", [])
    ]


def _strip_html(html: str) -> str:
    """Flatten Wiktionary definition HTML to plain text, keeping label text."""
    return BeautifulSoup(html, "html.parser").get_text().strip()


def _parse_wiktionary(word: str, payload: Any) -> LookupResult:
    """Parse a Wiktionary REST definition payload (English senses only).

    Definitions arrive as HTML and are flattened to plain text. The first
    example, if any, is kept. Wiktionary does not return synonyms here.
    """
    senses: list[Sense] = []
    for meaning in payload.get("en", []):
        definitions: list[Definition] = []
        for d in meaning.get("definitions", []):
            text = _strip_html(d.get("definition", ""))
            if not text:
                continue
            examples = d.get("examples") or []
            example = _strip_html(examples[0]) if examples else None
            definitions.append(Definition(definition=text, example=example))
        if definitions:
            senses.append(
                Sense(
                    part_of_speech=meaning.get("partOfSpeech", "").lower(),
                    definitions=definitions,
                    synonyms=[],
                )
            )
    return LookupResult(
        word=word,
        senses=senses,
        payload=payload,
        source="wiktionary",
    )


def _lookup_dictapi(
    normalized: str, client: httpx.Client
) -> LookupResult | NotFound:
    resp = client.get(f"{API_BASE}/{quote(normalized)}")
    if resp.status_code == 404:
        return NotFound(word=normalized)
    resp.raise_for_status()
    return _parse(normalized, resp.json())


def _fetch_wiktionary(
    title: str, client: httpx.Client
) -> LookupResult | None:
    """Fetch one exact Wiktionary page title. None if missing or no senses."""
    quoted = quote(title.replace(" ", "_"))
    resp = client.get(f"{WIKTIONARY_BASE}/{quoted}", headers=WIKTIONARY_HEADERS)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    result = _parse_wiktionary(title, resp.json())
    return result if result.senses else None


def _search_wiktionary_titles(query: str, client: httpx.Client) -> list[str]:
    """Find candidate page titles for a loosely-phrased query, best first."""
    resp = client.get(
        WIKTIONARY_SEARCH,
        params={
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": 5,
            "format": "json",
        },
        headers=WIKTIONARY_HEADERS,
    )
    resp.raise_for_status()
    hits = resp.json().get("query", {}).get("search", [])
    return [h["title"] for h in hits if h.get("title")]


def _lookup_wiktionary(
    normalized: str, client: httpx.Client
) -> LookupResult | NotFound:
    """Look a phrase up in Wiktionary, resolving loose phrasing via search.

    Tries the exact title first. If that has no entry (idioms are stored
    under a canonical lemma, e.g. "cut corners" not "cut the corner"), it
    searches for the closest matching lemma and uses the first candidate
    that yields English senses. The entry is stored under that resolved
    lemma, normalized.
    """
    exact = _fetch_wiktionary(normalized, client)
    if exact is not None:
        return exact

    for title in _search_wiktionary_titles(normalized, client):
        resolved = normalize(title)
        if resolved == normalized:
            continue  # already tried as the exact title
        found = _fetch_wiktionary(resolved, client)
        if found is not None:
            return found
    return NotFound(word=normalized)


def lookup(
    word: str, *, client: httpx.Client | None = None
) -> LookupResult | NotFound:
    """Look a word or phrase up, routing by word count.

    Single words go to the Free Dictionary API; multi-word input goes to
    Wiktionary. Returns a ``LookupResult`` on success or ``NotFound`` when
    the source has no usable entry. A pre-built ``httpx.Client`` may be
    injected for testing.
    """
    normalized = normalize(word)
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=10.0)
    try:
        if len(normalized.split()) > 1:
            return _lookup_wiktionary(normalized, client)
        # Single word: try the Free Dictionary API first, then Wiktionary when
        # the first source has no entry or is temporarily unavailable.
        try:
            result = _lookup_dictapi(normalized, client)
            if not isinstance(result, NotFound):
                return result
        except httpx.HTTPError:
            pass
        return _lookup_wiktionary(normalized, client)
    except httpx.HTTPError:
        # Both sources unreachable: transient failure, not "not found".
        return LookupError(word=normalized)
    finally:
        if owns_client:
            client.close()
