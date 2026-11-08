"""Runtime settings for the synchronous MVP document pipeline."""

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.tenancy.context import TenantScope


@dataclass(frozen=True, slots=True)
class DocumentSettings:
    storage_path: Path
    max_upload_bytes: int
    chunk_size: int
    chunk_overlap: int

    @classmethod
    def from_environment(cls) -> "DocumentSettings":
        storage_path = Path(os.getenv("DOCUMENT_STORAGE_PATH", "var/knowledge-documents")).expanduser()
        max_upload_bytes = int(os.getenv("DOCUMENT_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
        chunk_size = int(os.getenv("DOCUMENT_CHUNK_SIZE", "1200"))
        chunk_overlap = int(os.getenv("DOCUMENT_CHUNK_OVERLAP", "150"))
        if max_upload_bytes <= 0:
            raise ValueError("DOCUMENT_MAX_UPLOAD_BYTES must be positive")
        if chunk_size <= 0 or chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("Document chunk overlap must be non-negative and smaller than the chunk size")
        return cls(storage_path, max_upload_bytes, chunk_size, chunk_overlap)


def configured_document_scope() -> TenantScope:
    """Resolve one server-bound local demo tenant; callers cannot choose a tenant."""
    if os.getenv("APP_ENV", "").lower() != "development":
        raise RuntimeError("Knowledge document API is disabled outside development until authentication is implemented")
    try:
        organization_id = UUID(os.environ["DOCUMENT_TENANT_ORGANIZATION_ID"])
        workspace_id = UUID(os.environ["DOCUMENT_TENANT_WORKSPACE_ID"])
        membership_id = UUID(os.environ["DOCUMENT_TENANT_MEMBERSHIP_ID"])
    except (KeyError, ValueError) as exc:
        raise RuntimeError("Knowledge document tenant scope is not configured") from exc
    return TenantScope(organization_id, workspace_id, membership_id)
