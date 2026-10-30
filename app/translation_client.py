"""German translations generated through an Azure AI Foundry model.

Dictionary results remain authoritative when available. This module adds one
context-aware German translation per sense and can generate a complete labeled
entry when both dictionary providers fail. Missing configuration or upstream
failures are deliberately non-fatal.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

from app.dictionary_client import Definition, LookupResult, Sense, normalize

DEFAULT_BASE_URL = "https://ddas-foundry-test.services.ai.azure.com/openai/v1"
DEFAULT_MODEL = "gpt-4.1-mini"


@dataclass(frozen=True)
class SenseTranslation:
    translation: str
    explanation: str


@dataclass(frozen=True)
class TranslationResult:
    language: str
    senses: list[SenseTranslation]


@dataclass(frozen=True)
class GeneratedLookup:
    result: LookupResult
    translation: TranslationResult


def _request_payload(result: LookupResult, model: str) -> dict[str, Any]:
    source_senses = []
    for index, sense in enumerate(result.senses):
        source_senses.append(
            {
                "index": index,
                "part_of_speech": sense.part_of_speech,
                "definitions": [d.definition for d in sense.definitions],
                "examples": [d.example for d in sense.definitions if d.example],
            }
        )

    return {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You translate English vocabulary into natural German. "
                    "Return JSON only. Preserve the supplied sense indexes. "
                    "For each sense, provide the best concise German translation "
                    "for that specific meaning and a short German explanation. "
                    "Do not add senses or omit senses."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "word": result.word,
                        "senses": source_senses,
                        "required_output": {
                            "language": "de",
                            "senses": [
                                {
                                    "index": "integer",
                                    "translation": "string",
                                    "explanation": "string",
                                }
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }


def _parse_response(payload: Any, expected_senses: int) -> TranslationResult:
    content = payload["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    raw_senses = parsed.get("senses", [])
    by_index: dict[int, SenseTranslation] = {}
    for item in raw_senses:
        index = int(item["index"])
        translation = str(item["translation"]).strip()
        explanation = str(item["explanation"]).strip()
        if not translation or not explanation or index in by_index:
            raise ValueError("invalid translation response")
        by_index[index] = SenseTranslation(translation, explanation)

    if set(by_index) != set(range(expected_senses)):
        raise ValueError("translation response does not match source senses")
    return TranslationResult(
        language="de",
        senses=[by_index[index] for index in range(expected_senses)],
    )


def translate(
    result: LookupResult,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    client: httpx.Client | None = None,
) -> TranslationResult | None:
    """Translate all senses to German, or return ``None`` when unavailable.

    Configuration uses the same variable names as the Mealie agent:
    ``AZURE_MODEL_FOUNDRY_KEY``, ``AZURE_FOUNDRY_BASE_URL``, and
    ``AZURE_FOUNDRY_MODEL``. The key is required; endpoint and model have the
    same defaults as that project.
    """
    api_key = api_key or os.environ.get("AZURE_MODEL_FOUNDRY_KEY")
    if not api_key or not result.senses:
        return None
    base_url = (base_url or os.environ.get("AZURE_FOUNDRY_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    model = model or os.environ.get("AZURE_FOUNDRY_MODEL") or DEFAULT_MODEL

    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=30.0)
    try:
        response = client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "api-key": api_key,
                "Content-Type": "application/json",
            },
            json=_request_payload(result, model),
        )
        response.raise_for_status()
        return _parse_response(response.json(), len(result.senses))
    except (httpx.HTTPError, IndexError, KeyError, TypeError, ValueError):
        return None
    finally:
        if owns_client:
            client.close()


def generate_lookup(
    word: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    client: httpx.Client | None = None,
) -> GeneratedLookup | None:
    """Generate a dictionary entry and German translation as a final fallback.

    The model accepts established vocabulary as well as understandable slang,
    vulgar language, and productive informal word formations. It rejects only
    input with no plausible English meaning. Generated English definitions are
    explicitly marked at the canonical storage layer by the caller.
    """
    api_key = api_key or os.environ.get("AZURE_MODEL_FOUNDRY_KEY")
    normalized = normalize(word)
    if not api_key or not normalized:
        return None
    base_url = (base_url or os.environ.get("AZURE_FOUNDRY_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    model = model or os.environ.get("AZURE_FOUNDRY_MODEL") or DEFAULT_MODEL
    request_payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a careful English-German lexicographer. Determine whether "
                    "the input has a plausible meaning in English. Accept established words, "
                    "inflections, idioms, meaningful phrases, slang, vulgar expressions, "
                    "regional usage, and understandable productive formations such as adding "
                    "-ish, -y, -ness, or similar affixes. A term does not need to appear in a "
                    "traditional dictionary if an English speaker could reasonably understand "
                    "it from normal word formation. Reject only random gibberish, an accidental "
                    "misspelling with no plausible intended meaning, or a standalone proper noun "
                    "with no lexical meaning. Return JSON only. If recognized is true, provide "
                    "a canonical lowercase English expression and one or more distinct senses. "
                    "Every sense needs an English part of speech, concise English definitions, "
                    "optional examples and synonyms, plus a context-specific German translation "
                    "and short German explanation. Label vulgar meanings neutrally and accurately. "
                    "Do not invent facts."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "input": normalized,
                        "required_output": {
                            "recognized": "boolean",
                            "word": "canonical lowercase English expression",
                            "senses": [
                                {
                                    "part_of_speech": "string",
                                    "definitions": [
                                        {"definition": "string", "example": "string or null"}
                                    ],
                                    "synonyms": ["string"],
                                    "german_translation": "string",
                                    "german_explanation": "string",
                                }
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }

    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=30.0)
    try:
        response = client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "api-key": api_key,
                "Content-Type": "application/json",
            },
            json=request_payload,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        if parsed.get("recognized") is not True:
            return None

        resolved_word = normalize(str(parsed["word"]))
        if not resolved_word:
            return None
        senses: list[Sense] = []
        translated_senses: list[SenseTranslation] = []
        for item in parsed.get("senses", []):
            definitions = [
                Definition(
                    definition=str(definition["definition"]).strip(),
                    example=(
                        str(definition["example"]).strip()
                        if definition.get("example")
                        else None
                    ),
                )
                for definition in item.get("definitions", [])
                if str(definition.get("definition", "")).strip()
            ]
            translation = str(item["german_translation"]).strip()
            explanation = str(item["german_explanation"]).strip()
            if not definitions or not translation or not explanation:
                raise ValueError("incomplete generated sense")
            senses.append(
                Sense(
                    part_of_speech=str(item.get("part_of_speech", "")).strip(),
                    definitions=definitions,
                    synonyms=[str(value).strip() for value in item.get("synonyms", []) if str(value).strip()],
                )
            )
            translated_senses.append(SenseTranslation(translation, explanation))
        if not senses:
            return None
        return GeneratedLookup(
            result=LookupResult(
                word=resolved_word,
                senses=senses,
                payload=parsed,
                source="azure-ai-foundry",
            ),
            translation=TranslationResult(language="de", senses=translated_senses),
        )
    except (httpx.HTTPError, IndexError, KeyError, TypeError, ValueError):
        return None
    finally:
        if owns_client:
            client.close()


def add_to_canonical(payload: dict[str, Any], translation: TranslationResult) -> None:
    """Attach a generated translation to a canonical dictionary payload."""
    payload.setdefault("translations", {})[translation.language] = {
        "provider": "azure-ai-foundry",
        "senses": [
            {
                "translation": sense.translation,
                "explanation": sense.explanation,
            }
            for sense in translation.senses
        ],
    }


def from_canonical(payload: Any, language: str = "de") -> list[SenseTranslation]:
    """Read translations from stored canonical JSON, returning an empty list."""
    if not isinstance(payload, dict):
        return []
    raw = payload.get("translations", {}).get(language, {}).get("senses", [])
    try:
        return [
            SenseTranslation(
                translation=str(item["translation"]),
                explanation=str(item["explanation"]),
            )
            for item in raw
        ]
    except (KeyError, TypeError):
        return []
