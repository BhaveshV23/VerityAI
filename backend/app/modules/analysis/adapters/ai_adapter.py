"""Claim extraction providers used by the analysis pipeline.

The deterministic provider is the local/test default. Gemini is opt-in via
``AI_PROVIDER=gemini`` and never silently falls back after an API or response
failure.
"""

from __future__ import annotations

import os
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ClaimExtractionError(RuntimeError):
    """Base error for safe claim-extraction failure handling."""


class ClaimExtractionConfigurationError(ClaimExtractionError):
    """Provider configuration is missing or invalid."""


class ClaimExtractionProviderError(ClaimExtractionError):
    """The configured claim extraction provider failed."""


class ClaimExtractionResponseError(ClaimExtractionError):
    """Provider output did not satisfy the source-grounded schema."""


class ClaimSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    candidate_kind: Literal["factual", "promotional"]


class ClaimExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[ClaimSpan]


_GEMINI_UNSUPPORTED_SCHEMA_KEYS = frozenset({"additionalProperties", "minLength"})


def _gemini_response_json_schema() -> dict[str, Any]:
    """Return a Gemini-compatible copy of the strict Pydantic JSON Schema.

    Gemini's JSON Schema subset does not accept ``additionalProperties`` or
    ``minLength``. The original Pydantic models still enforce both policies
    locally: extra fields are forbidden and claim text must be non-empty.
    """
    def sanitize(node: Any) -> Any:
        if isinstance(node, dict):
            return {
                key: sanitize(value)
                for key, value in node.items()
                if key not in _GEMINI_UNSUPPORTED_SCHEMA_KEYS
            }
        if isinstance(node, list):
            return [sanitize(value) for value in node]
        return node

    return sanitize(ClaimExtractionResponse.model_json_schema())


_RELEVANT_CONTENT = re.compile(
    r"%|\bguaranteed\b|\bfees?\b|\b\d+(?:\.\d+)?\b",
    flags=re.IGNORECASE,
)
_PROMOTIONAL = re.compile(
    r"\b(guaranteed|free|save|best|up to|risk[- ]free)\b",
    flags=re.IGNORECASE,
)


def _structured_demo_claims(text: str) -> list[dict]:
    claims: list[dict] = []
    for match in re.finditer(r"[^.!?\n]+(?:[.!?]+|$)", text):
        raw_span = match.group(0)
        leading_whitespace = len(raw_span) - len(raw_span.lstrip())
        trailing_trimmed = raw_span.rstrip()
        span = trailing_trimmed.lstrip()
        if not span or _RELEVANT_CONTENT.search(span) is None:
            continue
        start = match.start() + leading_whitespace
        end = match.start() + len(trailing_trimmed)
        claims.append(
            {
                "text": span,
                "start_offset": start,
                "end_offset": end,
                "candidate_kind": "promotional" if _PROMOTIONAL.search(span) else "factual",
            }
        )
    return claims


def _validated_source_spans(text: str, payload: ClaimExtractionResponse) -> list[dict]:
    """Map verbatim model spans back to source offsets; reject invented text."""
    results: list[dict] = []
    search_from = 0
    for claim in payload.claims:
        start = text.find(claim.text, search_from)
        if start < 0:
            raise ClaimExtractionResponseError(
                "Gemini returned a claim span that is not an exact substring of the submitted source."
            )
        end = start + len(claim.text)
        results.append(
            {
                "text": claim.text,
                "start_offset": start,
                "end_offset": end,
                "candidate_kind": claim.candidate_kind,
            }
        )
        search_from = end
    return results


def _gemini_settings() -> tuple[str, str, int]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ClaimExtractionConfigurationError("GEMINI_API_KEY is required when AI_PROVIDER=gemini.")
    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
    if not model:
        raise ClaimExtractionConfigurationError("GEMINI_MODEL must not be empty.")
    raw_timeout = os.getenv("GEMINI_TIMEOUT_SECONDS", "30").strip()
    try:
        timeout_seconds = int(raw_timeout)
    except ValueError as exc:
        raise ClaimExtractionConfigurationError("GEMINI_TIMEOUT_SECONDS must be a positive integer.") from exc
    if timeout_seconds < 1:
        raise ClaimExtractionConfigurationError("GEMINI_TIMEOUT_SECONDS must be a positive integer.")
    return api_key, model, timeout_seconds


def _create_gemini_client(api_key: str, timeout_seconds: int):
    """Create the official Google GenAI client lazily for testability."""
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise ClaimExtractionConfigurationError(
            "The google-genai dependency is required when AI_PROVIDER=gemini."
        ) from exc
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=timeout_seconds * 1000),
    ), types


def _extract_with_gemini(text: str) -> list[dict]:
    api_key, model, timeout_seconds = _gemini_settings()
    client, genai_types = _create_gemini_client(api_key, timeout_seconds)
    prompt = (
        "Identify factual or promotional claims made by the supplied content. "
        "Return only claims that are relevant to a reader's decision, including claims about "
        "performance, outcomes, prices, fees, guarantees, quantified results, and benefits. "
        "For each claim, copy an exact, verbatim, contiguous substring from SOURCE_TEXT; "
        "preserve punctuation and spacing exactly. Do not paraphrase, infer facts, or add "
        "evidence or quotations that are not present. Keep claims in source order. Set "
        "candidate_kind to factual or promotional. An empty claims list is valid when there "
        "are no such claims.\n\nSOURCE_TEXT:\n" + text
    )
    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=_gemini_response_json_schema(),
                max_output_tokens=4096,
            ),
        )
    except Exception as exc:
        raise ClaimExtractionProviderError("Gemini claim extraction failed.") from exc
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                # A cleanup error must not replace the provider's actual result.
                pass

    try:
        parsed = getattr(response, "parsed", None)
        if parsed is not None:
            claims_response = ClaimExtractionResponse.model_validate(parsed)
        else:
            response_text = getattr(response, "text", None)
            if not isinstance(response_text, str) or not response_text.strip():
                raise ClaimExtractionResponseError("Gemini returned an empty structured response.")
            claims_response = ClaimExtractionResponse.model_validate_json(response_text)
        return _validated_source_spans(text, claims_response)
    except ClaimExtractionResponseError:
        raise
    except (ValidationError, ValueError, TypeError) as exc:
        raise ClaimExtractionResponseError("Gemini returned an invalid structured claim response.") from exc


def extract_claims(text: str) -> list[dict]:
    """Extract ordered claim spans using the configured provider.

    ``AI_PROVIDER`` is ``deterministic`` by default for local development and
    tests. Set it to ``gemini`` to make a real Gemini API call. Empty or
    whitespace-only input returns no claims without a provider call.
    """
    if not isinstance(text, str):
        raise TypeError("Claim extraction input must be text.")
    if not text.strip():
        return []

    provider = os.getenv("AI_PROVIDER", "deterministic").strip().lower()
    if provider == "deterministic":
        return _structured_demo_claims(text)
    if provider == "gemini":
        return _extract_with_gemini(text)
    raise ClaimExtractionConfigurationError(
        "AI_PROVIDER must be either 'deterministic' or 'gemini'."
    )
