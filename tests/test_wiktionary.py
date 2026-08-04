"""Tests for phrase lookups via Wiktionary and canonical storage.

All HTTP is mocked; no live network. Covers routing (multi-word ->
Wiktionary), HTML stripping, the 404/empty-> NotFound collapse, and the
canonical payload round-trip used by the store/review read path.
"""
from __future__ import annotations

import httpx

from app import dictionary_client
from app.dictionary_client import (
    LookupError,
    LookupResult,
    NotFound,
    lookup,
    senses_from_canonical,
    to_canonical,
)

# Trimmed but realistic Wiktionary REST definition payload with HTML markup.
WIKTIONARY_PAYLOAD = {
    "en": [
        {
            "partOfSpeech": "Verb",
            "definitions": [
                {
                    "definition": '<span class="usage-label-sense">(idiomatic)</span> To <a href="/wiki/die">die</a>.',
                    "examples": ["The old horse finally <b>kicked the bucket</b>."],
                },
                {
                    "definition": "To break down beyond repair.",
                },
            ],
        }
    ],
    # A non-English section that must be ignored.
    "de": [{"partOfSpeech": "Verb", "definitions": [{"definition": "sterben"}]}],
}


def _client_returning(status_code: int, json_body):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=json_body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _routed_client(*, definitions: dict, search: list[str]):
    """Mock that routes definition-title fetches and search separately.

    ``definitions`` maps a page title (underscored) to its JSON payload; a
    missing title 404s. ``search`` is the ordered list of candidate titles
    the search endpoint returns.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/page/definition/" in url:
            title = url.rsplit("/", 1)[1]
            if title in definitions:
                return httpx.Response(200, json=definitions[title])
            return httpx.Response(404, json={})
        # Search endpoint.
        hits = [{"title": t} for t in search]
        return httpx.Response(200, json={"query": {"search": hits}})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_multiword_routes_to_wiktionary_and_strips_html():
    client = _client_returning(200, WIKTIONARY_PAYLOAD)
    result = lookup("Kick the Bucket ", client=client)

    assert isinstance(result, LookupResult)
    assert result.word == "kick the bucket"  # normalized, spaces kept
    assert len(result.senses) == 1
    sense = result.senses[0]
    assert sense.part_of_speech == "verb"
    # HTML flattened, usage label text kept.
    assert sense.definitions[0].definition == "(idiomatic) To die."
    assert sense.definitions[0].example == "The old horse finally kicked the bucket."
    assert sense.definitions[1].definition == "To break down beyond repair."
    assert sense.definitions[1].example is None
    # English-only: German section ignored.
    assert all("sterben" not in d.definition for d in sense.definitions)


def test_wiktionary_targets_underscore_title():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=WIKTIONARY_PAYLOAD)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    lookup("break a leg", client=client)
    assert seen["url"].endswith("/break_a_leg")


def test_wiktionary_404_is_not_found():
    # Exact title missing and search finds nothing.
    client = _routed_client(definitions={}, search=[])
    result = lookup("no such idiom here", client=client)
    assert isinstance(result, NotFound)
    assert result.word == "no such idiom here"


def test_wiktionary_empty_english_is_not_found():
    client = _routed_client(
        definitions={
            "phrase_francaise_ici": {
                "fr": [{"partOfSpeech": "Noun", "definitions": []}]
            }
        },
        search=[],
    )
    result = lookup("phrase francaise ici", client=client)
    assert isinstance(result, NotFound)


def test_loose_phrasing_resolves_via_search_to_lemma():
    # Typed phrase 404s; search points at the canonical lemma which has senses.
    client = _routed_client(
        definitions={"cut_corners": WIKTIONARY_PAYLOAD},
        search=["cut off a corner", "cut corners"],
    )
    result = lookup("cut the corner", client=client)
    assert isinstance(result, LookupResult)
    # Stored under the resolved lemma, not the typed phrase.
    assert result.word == "cut corners"
    assert result.senses[0].definitions[0].definition == "(idiomatic) To die."


def test_upstream_5xx_is_lookup_error_not_not_found():
    # dictapi 502 AND Wiktionary unreachable -> LookupError (not "not found").
    client = _client_returning(502, {})
    result = lookup("dogs", client=client)
    assert isinstance(result, LookupError)
    assert result.word == "dogs"


def test_single_word_falls_back_to_wiktionary_when_dictapi_down():
    # dictapi 502 on a single word, but Wiktionary has it -> use Wiktionary.
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "dictionaryapi.dev" in url:
            return httpx.Response(502, json={})
        if "/page/definition/" in url:
            return httpx.Response(200, json=WIKTIONARY_PAYLOAD)
        return httpx.Response(200, json={"query": {"search": []}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = lookup("discombobulate", client=client)
    assert isinstance(result, LookupResult)
    assert result.senses[0].part_of_speech == "verb"


def test_single_word_404_does_not_fall_back():
    # A genuine 404 from dictapi must stay NotFound, no Wiktionary fallback.
    def handler(request: httpx.Request) -> httpx.Response:
        if "dictionaryapi.dev" in str(request.url):
            return httpx.Response(404, json={})
        raise AssertionError("must not call Wiktionary on a 404")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = lookup("asdfqwer", client=client)
    assert isinstance(result, NotFound)


def test_canonical_round_trip_preserves_senses():
    src = _parse_result()
    canonical = to_canonical(src)
    assert canonical["schema"] == "canonical/1"
    senses = senses_from_canonical(canonical)
    assert len(senses) == 1
    assert senses[0].part_of_speech == "verb"
    assert senses[0].definitions[0].definition == "(idiomatic) To die."
    assert senses[0].definitions[0].example == "The old horse finally kicked the bucket."


def _parse_result() -> LookupResult:
    client = _client_returning(200, WIKTIONARY_PAYLOAD)
    result = lookup("kick the bucket", client=client)
    assert isinstance(result, LookupResult)
    return result
