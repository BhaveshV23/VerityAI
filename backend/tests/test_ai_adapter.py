import json
from types import SimpleNamespace

import pytest

from app.modules.analysis.adapters import ai_adapter


class FakeGenerateContentConfig:
    def __init__(self, **kwargs):
        self.values = kwargs


class FakeGenAITypes:
    GenerateContentConfig = FakeGenerateContentConfig


class FakeModels:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.kwargs = None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, response=None, error=None):
        self.models = FakeModels(response=response, error=error)
        self.closed = False

    def close(self):
        self.closed = True


def _mock_gemini(monkeypatch, response=None, error=None):
    client = FakeClient(response=response, error=error)
    monkeypatch.setattr(
        ai_adapter,
        "_create_gemini_client",
        lambda _api_key, _timeout: (client, FakeGenAITypes),
    )
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-a-secret")
    return client


def test_gemini_valid_structured_response_preserves_source_spans(monkeypatch):
    source = "Campaign says:\nEarn 4% APY today!"
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    client = _mock_gemini(
        monkeypatch,
        response=SimpleNamespace(
            parsed={"claims": [{"text": "Earn 4% APY today!", "candidate_kind": "promotional"}]},
            text=None,
        ),
    )

    claims = ai_adapter.extract_claims(source)

    start = source.index("Earn")
    assert claims == [{
        "text": "Earn 4% APY today!",
        "start_offset": start,
        "end_offset": len(source),
        "candidate_kind": "promotional",
    }]
    assert client.models.kwargs["model"] == "gemini-3.5-flash-lite"
    config = client.models.kwargs["config"].values
    assert config["response_json_schema"] == ai_adapter._gemini_response_json_schema()
    assert "response_schema" not in config
    assert client.closed


def _contains_schema_key(node, key):
    if isinstance(node, dict):
        return key in node or any(_contains_schema_key(value, key) for value in node.values())
    if isinstance(node, list):
        return any(_contains_schema_key(value, key) for value in node)
    return False


def test_gemini_schema_copy_omits_unsupported_keywords_and_preserves_structure():
    original = ai_adapter.ClaimExtractionResponse.model_json_schema()
    provider_schema = ai_adapter._gemini_response_json_schema()

    assert _contains_schema_key(original, "additionalProperties")
    assert _contains_schema_key(original, "minLength")
    assert not _contains_schema_key(provider_schema, "additionalProperties")
    assert not _contains_schema_key(provider_schema, "minLength")
    assert ai_adapter.ClaimExtractionResponse.model_config["extra"] == "forbid"
    assert ai_adapter.ClaimSpan.model_config["extra"] == "forbid"

    assert provider_schema["type"] == "object"
    assert set(provider_schema["properties"]) == {"claims"}
    assert provider_schema["required"] == ["claims"]
    claims_schema = provider_schema["properties"]["claims"]
    assert claims_schema["type"] == "array"
    assert claims_schema["items"] == {"$ref": "#/$defs/ClaimSpan"}
    claim_schema = provider_schema["$defs"]["ClaimSpan"]
    assert claim_schema["type"] == "object"
    assert set(claim_schema["properties"]) == {"text", "candidate_kind"}
    assert claim_schema["required"] == ["text", "candidate_kind"]
    assert claim_schema["properties"]["text"]["type"] == "string"
    assert claim_schema["properties"]["candidate_kind"]["enum"] == ["factual", "promotional"]
    # Sanitization returns an independent object and leaves Pydantic's schema intact.
    assert _contains_schema_key(ai_adapter.ClaimExtractionResponse.model_json_schema(), "additionalProperties")


def test_installed_google_sdk_accepts_the_provider_json_schema():
    from google.genai import types

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=ai_adapter._gemini_response_json_schema(),
    )

    assert config.response_json_schema["properties"]["claims"]["items"] == {
        "$ref": "#/$defs/ClaimSpan"
    }


def test_gemini_parses_json_text_when_sdk_has_no_parsed_value(monkeypatch):
    source = "A fee of $12 applies."
    _mock_gemini(
        monkeypatch,
        response=SimpleNamespace(
            parsed=None,
            text=json.dumps({"claims": [{"text": source, "candidate_kind": "factual"}]}),
        ),
    )

    assert ai_adapter.extract_claims(source)[0]["text"] == source


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(parsed={"claims": [{"text": "Claim", "candidate_kind": "opinion"}]}, text=None),
        SimpleNamespace(parsed={"unexpected": []}, text=None),
        SimpleNamespace(parsed={"claims": [{"text": "Claim", "candidate_kind": "factual", "other": True}]}, text=None),
        SimpleNamespace(parsed={"claims": [{"text": "", "candidate_kind": "factual"}]}, text=None),
        SimpleNamespace(parsed={"claims": [{"text": 12, "candidate_kind": "factual"}]}, text=None),
        SimpleNamespace(parsed=None, text="not-json"),
        SimpleNamespace(parsed=None, text=None),
    ],
)
def test_gemini_invalid_or_incomplete_response_fails_closed(monkeypatch, response):
    _mock_gemini(monkeypatch, response=response)

    with pytest.raises(ai_adapter.ClaimExtractionResponseError):
        ai_adapter.extract_claims("A claim with 12 units.")


def test_gemini_rejects_claim_not_present_verbatim_in_source(monkeypatch):
    _mock_gemini(
        monkeypatch,
        response=SimpleNamespace(
            parsed={"claims": [{"text": "We guarantee 99% returns.", "candidate_kind": "promotional"}]},
            text=None,
        ),
    )

    with pytest.raises(ai_adapter.ClaimExtractionResponseError, match="exact substring"):
        ai_adapter.extract_claims("Our product may perform well.")


def test_gemini_missing_api_key_is_configuration_error(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(ai_adapter.ClaimExtractionConfigurationError, match="GEMINI_API_KEY"):
        ai_adapter.extract_claims("A claim with 12 units.")


def test_gemini_provider_failure_is_not_replaced_by_deterministic_claims(monkeypatch):
    client = _mock_gemini(monkeypatch, error=TimeoutError("provider detail"))

    with pytest.raises(ai_adapter.ClaimExtractionProviderError, match="Gemini claim extraction failed"):
        ai_adapter.extract_claims("A claim with 12 units.")

    assert client.closed


def test_empty_document_input_does_not_call_gemini(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    assert ai_adapter.extract_claims(" \n\t ") == []


def test_deterministic_provider_remains_available_for_local_tests(monkeypatch):
    source = "Our plan is guaranteed to save 20%. Ordinary description."
    monkeypatch.setenv("AI_PROVIDER", "deterministic")

    claims = ai_adapter.extract_claims(source)

    assert len(claims) == 1
    claim = claims[0]
    assert claim["candidate_kind"] == "promotional"
    assert source[claim["start_offset"]:claim["end_offset"]] == claim["text"]


def test_unknown_provider_fails_instead_of_silently_using_demo(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "misspelled")

    with pytest.raises(ai_adapter.ClaimExtractionConfigurationError, match="AI_PROVIDER"):
        ai_adapter.extract_claims("A claim with 12 units.")
