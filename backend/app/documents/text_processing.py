"""Deterministic normalization and character-based chunk boundaries."""

import re
import unicodedata
from dataclasses import dataclass


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[\t\f\v ]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(lines).strip()


@dataclass(frozen=True, slots=True)
class TextChunk:
    index: int
    content: str
    start_offset: int
    end_offset: int


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[TextChunk]:
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("Chunk overlap must be non-negative and smaller than chunk size")
    chunks: list[TextChunk] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        left = start
        right = end
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
        if left < right:
            chunks.append(TextChunk(len(chunks), text[left:right], left, right))
        if end == len(text):
            break
        next_start = max(start + 1, end - overlap)
        while next_start < len(text) and text[next_start].isspace():
            next_start += 1
        start = next_start
    return chunks
