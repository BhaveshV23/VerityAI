"""Replaceable local private-file storage adapter."""

from pathlib import Path
import re
from uuid import uuid4


class LocalDocumentStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve_key(self, key: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}\.(pdf|docx|txt)", key):
            raise ValueError("Invalid storage key")
        path = (self.root / key).resolve()
        if path.parent != self.root:
            raise ValueError("Storage key escapes the configured storage directory")
        return path

    def save(self, content: bytes, extension: str) -> str:
        key = f"{uuid4().hex}{extension}"
        destination = self._resolve_key(key)
        temporary = self._resolve_key(f"{uuid4().hex}{extension}")
        try:
            with temporary.open("xb") as stream:
                stream.write(content)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return key

    def read(self, key: str) -> bytes:
        return self._resolve_key(key).read_bytes()

    def delete(self, key: str) -> None:
        self._resolve_key(key).unlink(missing_ok=True)
