"""Tenant-scoped persistence and synchronous document-processing workflow."""

import hashlib
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.audit.service import record_event
from app.db.transactions import transaction
from app.documents.config import DocumentSettings
from app.documents.errors import DocumentProcessingError
from app.documents.extraction import extract_text
from app.documents.repository import KnowledgeDocumentRepository
from app.documents.storage import LocalDocumentStorage
from app.documents.status import transition_status
from app.documents.text_processing import chunk_text, normalize_text
from app.documents.validation import validate_document
from app.models import KnowledgeDocument, KnowledgeDocumentChunk
from app.tenancy.context import TenantScope


class KnowledgeDocumentService:
    def __init__(self, session_factory: sessionmaker[Session], settings: DocumentSettings) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.storage = LocalDocumentStorage(settings.storage_path)
        self.repository = KnowledgeDocumentRepository()

    def upload(self, scope: TenantScope, filename: str | None, content: bytes) -> KnowledgeDocument:
        validated = validate_document(filename, content, self.settings.max_upload_bytes)
        storage_key = self.storage.save(content, validated.extension)
        document_id = uuid4()
        try:
            with transaction(self.session_factory) as session:
                document = KnowledgeDocument(
                    id=document_id,
                    organization_id=scope.organization_id,
                    workspace_id=scope.workspace_id,
                    uploaded_by_membership_id=scope.membership_id,
                    title=PurePosixPath(validated.original_filename).stem[:300] or "Untitled document",
                    original_filename=validated.original_filename,
                    file_extension=validated.extension,
                    detected_content_type=validated.detected_content_type,
                    byte_size=validated.byte_size,
                    content_sha256=hashlib.sha256(content).hexdigest(),
                    storage_key=storage_key,
                    status="pending",
                )
                self.repository.add(session, document)
                session.flush()
                record_event(
                    session,
                    scope,
                    actor_membership_id=scope.membership_id,
                    action_key="knowledge_document.uploaded",
                    target_type="knowledge_document",
                    target_id=document.id,
                    safe_metadata={"file_extension": validated.extension, "byte_size": validated.byte_size},
                )
        except Exception:
            self.storage.delete(storage_key)
            raise

        with transaction(self.session_factory) as session:
            document = self._get_or_raise(session, scope, document_id)
            transition_status(document, "processing")
            record_event(
                session,
                scope,
                actor_membership_id=scope.membership_id,
                action_key="knowledge_document.processing",
                target_type="knowledge_document",
                target_id=document.id,
            )

        try:
            extracted = extract_text(validated)
            normalized = normalize_text(extracted)
            if not normalized:
                raise DocumentProcessingError("empty_document", "No readable text was found in the document.")
            chunks = chunk_text(normalized, self.settings.chunk_size, self.settings.chunk_overlap)
            if not chunks:
                raise DocumentProcessingError("empty_document", "No readable text was found in the document.")
        except DocumentProcessingError as exc:
            self._mark_failed(scope, document_id, exc.code, exc.message, storage_key)
        except Exception:
            self._mark_failed(
                scope,
                document_id,
                "processing_failed",
                "The document could not be processed. Try another file or contact an administrator.",
                storage_key,
            )
        else:
            with transaction(self.session_factory) as session:
                document = self._get_or_raise(session, scope, document_id)
                document.extracted_text = extracted
                document.normalized_text = normalized
                document.language = "en"
                transition_status(document, "processed")
                self.repository.add_chunks(session, [
                    KnowledgeDocumentChunk(
                        organization_id=scope.organization_id,
                        workspace_id=scope.workspace_id,
                        document_id=document.id,
                        chunk_index=chunk.index,
                        content=chunk.content,
                        start_offset=chunk.start_offset,
                        end_offset=chunk.end_offset,
                    )
                    for chunk in chunks
                ])
                record_event(
                    session,
                    scope,
                    actor_membership_id=scope.membership_id,
                    action_key="knowledge_document.processed",
                    target_type="knowledge_document",
                    target_id=document.id,
                    safe_metadata={"chunk_count": len(chunks)},
                )

        with self.session_factory() as session:
            return self._get_or_raise(session, scope, document_id)

    def _mark_failed(
        self,
        scope: TenantScope,
        document_id: UUID,
        code: str,
        message: str,
        storage_key: str,
    ) -> None:
        with transaction(self.session_factory) as session:
            document = self._get_or_raise(session, scope, document_id)
            transition_status(document, "failed", error=DocumentProcessingError(code, message))
            record_event(
                session,
                scope,
                actor_membership_id=scope.membership_id,
                action_key="knowledge_document.failed",
                target_type="knowledge_document",
                target_id=document.id,
                safe_metadata={"error_code": code},
            )
        self.storage.delete(storage_key)

    @staticmethod
    def _get_or_raise(session: Session, scope: TenantScope, document_id: UUID) -> KnowledgeDocument:
        document = KnowledgeDocumentRepository().get(session, scope, document_id)
        if document is None:
            raise LookupError("Knowledge document was not found")
        return document

    def get(self, scope: TenantScope, document_id: UUID) -> KnowledgeDocument | None:
        with self.session_factory() as session:
            return self.repository.get(session, scope, document_id)

    def list(self, scope: TenantScope, limit: int = 50, offset: int = 0) -> list[KnowledgeDocument]:
        with self.session_factory() as session:
            return self.repository.list(session, scope, limit, offset)

    def chunks(self, scope: TenantScope, document_id: UUID, limit: int = 100, offset: int = 0) -> list[KnowledgeDocumentChunk] | None:
        with self.session_factory() as session:
            if self._get_or_none(session, scope, document_id) is None:
                return None
            return self.repository.chunks(session, scope, document_id, limit, offset)

    @staticmethod
    def _get_or_none(session: Session, scope: TenantScope, document_id: UUID) -> KnowledgeDocument | None:
        return KnowledgeDocumentRepository().get(session, scope, document_id)
