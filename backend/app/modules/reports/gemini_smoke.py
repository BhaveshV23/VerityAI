"""Standalone, non-sensitive Gemini structured-output connectivity check.

Run from ``backend`` with ``python -m app.modules.reports.gemini_smoke``.
This module does not import database or report-generation services.
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, ValidationError

from app.modules.reports import narrative


SMOKE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"status": {"type": "STRING", "enum": ["ok"]}},
    "required": ["status"],
}
SMOKE_MAX_OUTPUT_TOKENS = 32


class SmokeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"]


class GeminiSmokeFailure(RuntimeError):
    """Safe smoke-test failure with a fixed, non-sensitive stage label."""

    def __init__(
        self,
        stage: str,
        cause: Exception | None = None,
        response_diagnostics: dict[str, object] | None = None,
    ):
        self.stage = stage
        self.cause = cause
        self.response_diagnostics = response_diagnostics or {}
        super().__init__(stage)


def _safe_label(value: object) -> str | None:
    if hasattr(value, "value"):
        value = value.value
    if not isinstance(value, str):
        return None
    label = value.rsplit(".", 1)[-1].upper()
    return label if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", label) else None


def _safe_mime_type(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    media_type = value.split(";", 1)[0].strip().lower()
    if re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", media_type):
        return media_type
    return None


def _response_diagnostics(response: Any, text: object, parsed: object) -> dict[str, object]:
    """Return only safe response shape metadata; never serialize the response."""
    candidates = getattr(response, "candidates", None)
    candidate_count = len(candidates) if isinstance(candidates, (list, tuple)) else None
    first_candidate = candidates[0] if isinstance(candidates, (list, tuple)) and candidates else None
    finish_reason = _safe_label(getattr(first_candidate, "finish_reason", None))

    response_mime_type = None
    sdk_http_response = getattr(response, "sdk_http_response", None)
    headers = getattr(sdk_http_response, "headers", None)
    if isinstance(headers, dict):
        for key, value in headers.items():
            if isinstance(key, str) and key.lower() == "content-type":
                response_mime_type = _safe_mime_type(value)
                break
    if response_mime_type is None:
        content = getattr(first_candidate, "content", None)
        parts = getattr(content, "parts", None)
        if isinstance(parts, (list, tuple)):
            for part in parts:
                for data_name in ("inline_data", "file_data"):
                    data = getattr(part, data_name, None)
                    response_mime_type = _safe_mime_type(getattr(data, "mime_type", None))
                    if response_mime_type is not None:
                        break
                if response_mime_type is not None:
                    break

    return {
        "response_text_exists": text is not None,
        "response_text_length_chars": len(text) if isinstance(text, str) else None,
        "response_parsed_exists": parsed is not None,
        "candidate_count": candidate_count,
        "finish_reason": finish_reason,
        "response_mime_type": response_mime_type or "unavailable",
        "configured_response_mime_type": "application/json",
    }


def _json_error_category(error: json.JSONDecodeError) -> str:
    known_categories = (
        "Expecting value",
        "Expecting property name enclosed in double quotes",
        "Unterminated string starting at",
        "Extra data",
        "Invalid control character",
        "Expecting ':' delimiter",
        "Expecting ',' delimiter",
    )
    for category in known_categories:
        if error.msg.startswith(category):
            return category
    return "other_json_decode_error"


def run_smoke_test() -> tuple[str, bool]:
    """Send a tiny structured request using the app's configured key/model."""
    load_dotenv()
    api_key, model, timeout_seconds = narrative._settings()
    client, genai_types = narrative._create_gemini_client(api_key, timeout_seconds)
    try:
        try:
            response = client.models.generate_content(
                model=model,
                contents='Return exactly this JSON object: {"status":"ok"}.',
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=SMOKE_SCHEMA,
                    max_output_tokens=SMOKE_MAX_OUTPUT_TOKENS,
                ),
            )
        except Exception as exc:
            stage = "sdk_response_body_json" if isinstance(exc, json.JSONDecodeError) else "provider_request"
            raise GeminiSmokeFailure(stage, exc) from exc

        parsed: Any = getattr(response, "parsed", None)
        candidates = getattr(response, "candidates", None)
        first_candidate = candidates[0] if isinstance(candidates, (list, tuple)) and candidates else None
        finish_reason = _safe_label(getattr(first_candidate, "finish_reason", None))
        if finish_reason == "MAX_TOKENS":
            try:
                partial_text = getattr(response, "text", None)
            except Exception:
                partial_text = None
            raise GeminiSmokeFailure(
                "incomplete_generation",
                response_diagnostics=_response_diagnostics(response, partial_text, parsed),
            )
        if parsed is None:
            try:
                text = getattr(response, "text", None)
            except Exception as exc:
                raise GeminiSmokeFailure("response_text_access", exc) from exc
            if text is None:
                raise GeminiSmokeFailure(
                    "missing_response_text",
                    response_diagnostics=_response_diagnostics(response, text, parsed),
                )
            if not isinstance(text, str) or not text.strip():
                raise GeminiSmokeFailure(
                    "empty_response",
                    response_diagnostics=_response_diagnostics(response, text, parsed),
                )
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                response_diagnostics = _response_diagnostics(response, text, parsed)
                response_diagnostics["json_error_position"] = exc.pos
                response_diagnostics["json_error_category"] = _json_error_category(exc)
                raise GeminiSmokeFailure("malformed_json", exc, response_diagnostics) from exc
        try:
            result = SmokeResponse.model_validate(parsed)
        except ValidationError as exc:
            raise GeminiSmokeFailure("schema_validation", exc) from exc
        return model, result.status == "ok"
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def main() -> int:
    try:
        model, succeeded = run_smoke_test()
    except GeminiSmokeFailure as exc:
        # Allowlisted metadata only; never print provider messages, headers, or credentials.
        underlying = exc.cause or exc
        diagnostics = narrative.gemini_failure_diagnostics(underlying)
        print(
            "Gemini smoke test failed "
            f"(model={os.getenv('GEMINI_MODEL', 'gemini-3.8-flash').strip()}, "
            f"failure_stage={exc.stage}, "
            f"exception_class={diagnostics.exception_class}, "
            f"http_status={diagnostics.http_status}, "
            f"provider_status={diagnostics.provider_status}).",
            file=sys.stderr,
        )
        if exc.response_diagnostics:
            safe_fields = " ".join(
                f"{key}={value}" for key, value in exc.response_diagnostics.items()
            )
            print(f"Gemini smoke response metadata ({safe_fields}).", file=sys.stderr)
        return 1
    except Exception as exc:
        # Configuration and unexpected local failures also get type-only reporting.
        print(
            "Gemini smoke test failed "
            f"(failure_stage=configuration_or_local, exception_class={type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1
    if not succeeded:
        print(f"Gemini smoke test returned an unexpected status (model={model}).", file=sys.stderr)
        return 1
    print(f"Gemini structured-output smoke test succeeded (model={model}).")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a CLI
    raise SystemExit(main())
