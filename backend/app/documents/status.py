"""Guard the document-processing state machine and safe failure metadata."""

from datetime import UTC, datetime

from app.documents.errors import DocumentProcessingError
from app.models import KnowledgeDocument

_TRANSITIONS = {
    "pending": {"processing", "failed"},
    "processing": {"processed", "failed"},
    "processed": set(),
    "failed": set(),
}


def transition_status(
    document: KnowledgeDocument,
    target: str,
    *,
    error: DocumentProcessingError | None = None,
) -> None:
    if target not in _TRANSITIONS.get(document.status, set()):
        raise ValueError(f"Invalid document status transition: {document.status} -> {target}")
    if target == "failed" and error is None:
        raise ValueError("Failed status requires a safe processing error")
    document.status = target
    if target == "failed":
        document.processing_error_code = error.code
        document.processing_error_message = error.message
        document.storage_key = None
    elif target == "processed":
        document.processing_error_code = None
        document.processing_error_message = None
    if target in {"failed", "processed"}:
        document.processed_at = datetime.now(UTC)
