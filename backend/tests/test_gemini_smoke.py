import json
from types import SimpleNamespace

import httpx
import pytest
from google.genai.errors import ServerError

from app.modules.reports import gemini_smoke, narrative


def _configure(monkeypatch, response=None, error=None):
    monkeypatch.setattr(gemini_smoke, "load_dotenv", lambda: None)
    monkeypatch.setattr(narrative, "_settings", lambda: ("synthetic-key", "smoke-model", 90))
    calls = []

    class Client:
        class Models:
            def generate_content(self, **kwargs):
                calls.append(kwargs)
                if error:
                    raise error
                return response

        models = Models()

        def close(self):
            pass

    monkeypatch.setattr(
        narrative,
        "_create_gemini_client",
        lambda *_: (Client(), SimpleNamespace(GenerateContentConfig=lambda **kwargs: kwargs)),
    )
    return calls


def test_smoke_accepts_valid_sdk_parsed_structured_json_without_reading_text(monkeypatch):
    class ParsedResponse:
        parsed = {"status": "ok"}

        @property
        def text(self):
            raise AssertionError("text fallback should not be accessed when parsed is populated")

    _configure(monkeypatch, response=ParsedResponse())

    assert gemini_smoke.run_smoke_test() == ("smoke-model", True)


def test_smoke_accepts_valid_json_text_when_sdk_did_not_parse(monkeypatch):
    calls = _configure(monkeypatch, response=SimpleNamespace(parsed=None, text='{"status":"ok"}'))

    assert gemini_smoke.run_smoke_test() == ("smoke-model", True)
    assert calls[0]["config"]["response_mime_type"] == "application/json"
    assert calls[0]["config"]["response_json_schema"] == gemini_smoke.SMOKE_SCHEMA
    assert calls[0]["config"]["max_output_tokens"] == gemini_smoke.SMOKE_MAX_OUTPUT_TOKENS
    assert calls[0]["contents"] == 'Return exactly this JSON object: {"status":"ok"}.'


def test_smoke_distinguishes_empty_response(monkeypatch):
    _configure(monkeypatch, response=SimpleNamespace(parsed=None, text="  "))

    with pytest.raises(gemini_smoke.GeminiSmokeFailure) as error:
        gemini_smoke.run_smoke_test()
    assert error.value.stage == "empty_response"
    assert error.value.response_diagnostics["response_text_exists"] is True
    assert error.value.response_diagnostics["response_text_length_chars"] == 2
    assert error.value.response_diagnostics["response_parsed_exists"] is False


def test_smoke_distinguishes_missing_response_text(monkeypatch):
    _configure(monkeypatch, response=SimpleNamespace(parsed=None, text=None))

    with pytest.raises(gemini_smoke.GeminiSmokeFailure) as error:
        gemini_smoke.run_smoke_test()
    assert error.value.stage == "missing_response_text"


def test_max_tokens_is_reported_as_incomplete_generation(monkeypatch, capsys):
    response = SimpleNamespace(
        parsed=None,
        text=None,
        candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")],
    )
    _configure(monkeypatch, response=response)

    with pytest.raises(gemini_smoke.GeminiSmokeFailure) as error:
        gemini_smoke.run_smoke_test()
    assert error.value.stage == "incomplete_generation"
    assert error.value.response_diagnostics["finish_reason"] == "MAX_TOKENS"
    assert error.value.response_diagnostics["response_parsed_exists"] is False
    assert error.value.response_diagnostics["response_text_exists"] is False

    monkeypatch.setattr(gemini_smoke, "run_smoke_test", lambda: (_ for _ in ()).throw(error.value))
    assert gemini_smoke.main() == 1
    output = capsys.readouterr().err
    assert "failure_stage=incomplete_generation" in output
    assert "finish_reason=MAX_TOKENS" in output


def test_smoke_identifies_application_json_decode_failure_without_content(monkeypatch, capsys):
    raw_text = "not json private response"
    response = SimpleNamespace(
        parsed=None,
        text=raw_text,
        candidates=[SimpleNamespace(finish_reason="STOP")],
        sdk_http_response=SimpleNamespace(headers={"content-type": "application/json; charset=utf-8"}),
    )
    _configure(monkeypatch, response=response)

    with pytest.raises(gemini_smoke.GeminiSmokeFailure) as error:
        gemini_smoke.run_smoke_test()
    assert error.value.stage == "malformed_json"
    assert isinstance(error.value.cause, ValueError)
    assert "private response" not in str(error.value)
    assert error.value.response_diagnostics == {
        "response_text_exists": True,
        "response_text_length_chars": len(raw_text),
        "response_parsed_exists": False,
        "candidate_count": 1,
        "finish_reason": "STOP",
        "response_mime_type": "application/json",
        "configured_response_mime_type": "application/json",
        "json_error_position": 0,
        "json_error_category": "Expecting value",
    }

    monkeypatch.setattr(gemini_smoke, "run_smoke_test", lambda: (_ for _ in ()).throw(error.value))
    assert gemini_smoke.main() == 1
    output = capsys.readouterr().err
    assert "response_text_exists=True" in output
    assert f"response_text_length_chars={len(raw_text)}" in output
    assert "response_parsed_exists=False" in output
    assert "candidate_count=1" in output
    assert "finish_reason=STOP" in output
    assert "response_mime_type=application/json" in output
    assert "json_error_position=0" in output
    assert "json_error_category=Expecting value" in output
    assert raw_text not in output


def test_smoke_reports_sdk_server_error_as_provider_request_failure(monkeypatch, capsys):
    provider_error = ServerError(
        503,
        {"error": {"status": "UNAVAILABLE", "message": "private response content"}},
        httpx.Response(503),
    )
    _configure(monkeypatch, error=provider_error)

    with pytest.raises(gemini_smoke.GeminiSmokeFailure) as error:
        gemini_smoke.run_smoke_test()
    assert error.value.stage == "provider_request"
    assert error.value.cause is provider_error

    monkeypatch.setattr(gemini_smoke, "run_smoke_test", lambda: (_ for _ in ()).throw(error.value))
    assert gemini_smoke.main() == 1
    output = capsys.readouterr().err
    assert "failure_stage=provider_request" in output
    assert "http_status=503" in output
    assert "provider_status=UNAVAILABLE" in output
    assert "private response content" not in output


def test_smoke_distinguishes_sdk_http_body_json_decode_failure(monkeypatch):
    _configure(monkeypatch, error=json.JSONDecodeError("private body", "secret response", 0))

    with pytest.raises(gemini_smoke.GeminiSmokeFailure) as error:
        gemini_smoke.run_smoke_test()
    assert error.value.stage == "sdk_response_body_json"
    assert error.value.cause.__class__ is json.JSONDecodeError
    assert "secret response" not in str(error.value)


def test_smoke_distinguishes_valid_json_with_schema_validation_failure(monkeypatch):
    _configure(monkeypatch, response=SimpleNamespace(parsed={"unexpected": "field"}))

    with pytest.raises(gemini_smoke.GeminiSmokeFailure) as error:
        gemini_smoke.run_smoke_test()
    assert error.value.stage == "schema_validation"
