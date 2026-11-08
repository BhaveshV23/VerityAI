"""Claim extraction adapter with a deterministic local demonstration mode.

No external provider is called here. Both AI_ENABLED modes return the same
structured shape so the claim extraction workflow can be wired independently
of a provider decision.
"""

import os
import re


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


def extract_claims(text: str) -> list[dict]:
    """Extract claim-like sentence spans and return structured offsets.

    ``AI_ENABLED=true`` selects a deterministic mocked structured response;
    it does not activate a network call or transmit user content.
    """
    if not text:
        return []
    if os.getenv("AI_ENABLED", "false").strip().lower() == "true":
        return _structured_demo_claims(text)
    return _structured_demo_claims(text)
