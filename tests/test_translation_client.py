"""Tests for Azure AI Foundry translation and canonical persistence."""
from __future__ import annotations

import json

import httpx

from app import dictionary_client, translation_client


RESULT = dictionary_client.LookupResult(
    word="run",
    senses=[
        dictionary_client.Sense(
            part_of_speech="verb",
            definitions=[
                dictionary_client.Definition(
                    definition="To move rapidly on foot.",
                    example="I run every morning.",
                )
            ],
        ),
        dictionary_client.Sense(
            part_of_speech="verb",
            definitions=[dictionary_client.Definition(definition="To operate.")],
        ),
    ],
    payload={},
)


def test_translate_calls_foundry_and_preserves_sense_order():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["authorization"]
        body = json.loads(request.content)
        seen["model"] = body["model"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "language": "de",
                                    "senses": [
                                        {
                                            "index": 1,
                                            "translation": "betreiben",
                                            "explanation": "Etwas ausführen oder bedienen.",
                                        },
                                        {
                                            "index": 0,
                                            "translation": "laufen",
                                            "explanation": "Sich schnell zu Fuß bewegen.",
                                        },
                                    ],
                                }
                            )
                        }
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = translation_client.translate(
        RESULT,
        api_key="secret",
        base_url="https://example.test/openai/v1",
        model="gpt-test",
        client=client,
    )

    assert result is not None
    assert [sense.translation for sense in result.senses] == ["laufen", "betreiben"]
    assert seen == {
        "url": "https://example.test/openai/v1/chat/completions",
        "authorization": "Bearer secret",
        "model": "gpt-test",
    }


def test_translate_without_key_is_disabled(monkeypatch):
    monkeypatch.delenv("AZURE_MODEL_FOUNDRY_KEY", raising=False)
    assert translation_client.translate(RESULT) is None


def test_malformed_or_failed_response_does_not_break_lookup():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"choices": []})
        )
    )
    assert translation_client.translate(RESULT, api_key="secret", client=client) is None


def test_generate_lookup_builds_english_and_german_senses():
    model_content = {
        "recognized": True,
        "word": "spill the tea",
        "senses": [
            {
                "part_of_speech": "idiom",
                "definitions": [
                    {
                        "definition": "To disclose gossip or private information.",
                        "example": "She spilled the tea about the meeting.",
                    }
                ],
                "synonyms": ["gossip"],
                "german_translation": "auspacken",
                "german_explanation": "Klatsch oder private Informationen erzählen.",
            }
        ],
    }
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": json.dumps(model_content)}}
                    ]
                },
            )
        )
    )

    generated = translation_client.generate_lookup(
        "Spill the Tea ", api_key="secret", client=client
    )

    assert generated is not None
    assert generated.result.word == "spill the tea"
    assert generated.result.source == "azure-ai-foundry"
    assert generated.result.senses[0].definitions[0].definition.startswith("To disclose")
    assert generated.result.senses[0].synonyms == ["gossip"]
    assert generated.translation.senses[0].translation == "auspacken"


def test_generate_lookup_prompt_accepts_understandable_informal_formations():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system_prompt = body["messages"][0]["content"]
        assert "slang" in system_prompt
        assert "productive formations" in system_prompt
        assert "-ish" in system_prompt
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "recognized": True,
                                    "word": "assholish",
                                    "senses": [
                                        {
                                            "part_of_speech": "adjective",
                                            "definitions": [
                                                {
                                                    "definition": "Rude or obnoxious in an asshole-like way.",
                                                    "example": "That was an assholish thing to say.",
                                                }
                                            ],
                                            "synonyms": ["obnoxious"],
                                            "german_translation": "arschlochhaft",
                                            "german_explanation": "Unhöflich oder unangenehm.",
                                        }
                                    ],
                                }
                            )
                        }
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    generated = translation_client.generate_lookup(
        "assholish", api_key="secret", client=client
    )

    assert generated is not None
    assert generated.result.word == "assholish"
    assert generated.translation.senses[0].translation == "arschlochhaft"


def test_generate_lookup_rejects_unrecognized_input():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {"recognized": False, "word": "", "senses": []}
                                )
                            }
                        }
                    ]
                },
            )
        )
    )
    assert (
        translation_client.generate_lookup(
            "asdfqwer", api_key="secret", client=client
        )
        is None
    )


def test_translation_round_trips_through_canonical_payload():
    canonical = dictionary_client.to_canonical(RESULT)
    translated = translation_client.TranslationResult(
        language="de",
        senses=[
            translation_client.SenseTranslation("laufen", "Sich zu Fuß bewegen."),
            translation_client.SenseTranslation("betreiben", "Etwas ausführen."),
        ],
    )
    translation_client.add_to_canonical(canonical, translated)

    restored = translation_client.from_canonical(canonical)
    assert restored == translated.senses
    assert canonical["translations"]["de"]["provider"] == "azure-ai-foundry"
