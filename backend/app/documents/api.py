"""Tenant-bound development API for knowledge document ingestion."""

from collections.abc import Generator
from ipaddress import ip_address
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_session_factory
from app.documents.config import DocumentSettings, configured_document_scope
from app.documents.errors import DocumentInputError
from app.documents.service import KnowledgeDocumentService
from app.models import KnowledgeDocument, KnowledgeDocumentChunk
from app.tenancy.context import InvalidTenantScope, TenantScope, validate_tenant_scope

router = APIRouter(prefix="/api/v1/knowledge-documents", tags=["knowledge documents"])


class DocumentResponse(BaseModel):
    id: UUID
    title: str
    original_filename: str
    file_extension: str
    detected_content_type: str
    byte_size: int
    content_sha256: str
    status: str
    language: str | None
    processing_error_code: str | None
    processing_error_message: str | None
    created_at: str
    processed_at: str | None


class ChunkResponse(BaseModel):
    id: UUID
    chunk_index: int
    content: str
    start_offset: int
    end_offset: int


def get_request_session() -> Generator[Session, None, None]:
    with get_session_factory()() as session:
        yield session


def get_tenant_scope(request: Request, session: Session = Depends(get_request_session)) -> TenantScope:
    host = request.client.host if request.client else ""
    if host != "testclient":
        try:
            is_loopback = ip_address(host).is_loopback
        except ValueError:
            is_loopback = False
        if not is_loopback:
            raise HTTPException(status_code=403, detail="Knowledge document API is available only from this machine.")
    try:
        scope = configured_document_scope()
        validate_tenant_scope(session, scope)
        return scope
    except (RuntimeError, InvalidTenantScope) as exc:
        raise HTTPException(status_code=503, detail="Knowledge document service is not configured for this workspace.") from exc


def get_document_service() -> KnowledgeDocumentService:
    try:
        return KnowledgeDocumentService(get_session_factory(), DocumentSettings.from_environment())
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Knowledge document service is not configured.") from exc


def _document_response(document: KnowledgeDocument) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        title=document.title,
        original_filename=document.original_filename,
        file_extension=document.file_extension,
        detected_content_type=document.detected_content_type,
        byte_size=document.byte_size,
        content_sha256=document.content_sha256,
        status=document.status,
        language=document.language,
        processing_error_code=document.processing_error_code,
        processing_error_message=document.processing_error_message,
        created_at=document.created_at.isoformat(),
        processed_at=document.processed_at.isoformat() if document.processed_at else None,
    )


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    scope: TenantScope = Depends(get_tenant_scope),
    service: KnowledgeDocumentService = Depends(get_document_service),
) -> DocumentResponse:
    try:
        content = bytearray()
        while block := await file.read(64 * 1024):
            content.extend(block)
            if len(content) > service.settings.max_upload_bytes:
                raise DocumentInputError("file_too_large", "The document exceeds the configured upload size limit.", 413)
        document = service.upload(scope, file.filename, bytes(content))
    except DocumentInputError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc
    finally:
        await file.close()
    return _document_response(document)


@router.get("", response_model=list[DocumentResponse])
def list_documents(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    scope: TenantScope = Depends(get_tenant_scope),
    service: KnowledgeDocumentService = Depends(get_document_service),
) -> list[DocumentResponse]:
    return [_document_response(row) for row in service.list(scope, limit, offset)]


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: UUID,
    scope: TenantScope = Depends(get_tenant_scope),
    service: KnowledgeDocumentService = Depends(get_document_service),
) -> DocumentResponse:
    document = service.get(scope, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found.")
    return _document_response(document)


@router.get("/{document_id}/content")
def get_document_content(
    document_id: UUID,
    scope: TenantScope = Depends(get_tenant_scope),
    service: KnowledgeDocumentService = Depends(get_document_service),
) -> dict[str, str | None]:
    document = service.get(scope, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found.")
    if document.status != "processed":
        raise HTTPException(status_code=409, detail="Extracted content is not available for this document.")
    return {"document_id": str(document.id), "status": document.status, "language": document.language, "content": document.normalized_text}


@router.get("/{document_id}/chunks", response_model=list[ChunkResponse])
def get_document_chunks(
    document_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    scope: TenantScope = Depends(get_tenant_scope),
    service: KnowledgeDocumentService = Depends(get_document_service),
) -> list[ChunkResponse]:
    chunks = service.chunks(scope, document_id, limit, offset)
    if chunks is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found.")
    return [
        ChunkResponse(
            id=row.id,
            chunk_index=row.chunk_index,
            content=row.content,
            start_offset=row.start_offset,
            end_offset=row.end_offset,
        )
        for row in chunks
    ]
