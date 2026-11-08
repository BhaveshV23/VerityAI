from io import BytesIO
from pathlib import Path
import shutil
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.audit.service import record_event
from app.db.transactions import transaction
from app.documents.api import get_document_service, get_tenant_scope
from app.documents.config import DocumentSettings
from app.documents.config import configured_document_scope
from app.documents.errors import DocumentInputError
from app.documents.service import KnowledgeDocumentService
from app.documents.status import transition_status
from app.documents.storage import LocalDocumentStorage
from app.documents.text_processing import chunk_text, normalize_text
from app.documents.validation import validate_document
from app.documents.errors import DocumentProcessingError
from app.main import app
from app.models import AuditEvent, KnowledgeDocument, KnowledgeDocumentChunk


@pytest.fixture
def document_storage_root():
    path = Path(__file__).resolve().parent / "_test_storage" / uuid4().hex
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def document_service(session_factory, document_storage_root):
    settings = DocumentSettings(document_storage_root / "private-store", 1_000_000, 48, 8)
    return KnowledgeDocumentService(session_factory, settings)


def _minimal_pdf(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii") if text else b""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii") + obj + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        output.extend(f"{offset:010} 00000 n \n".encode("ascii"))
    output.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode("ascii"))
    return bytes(output)


def _docx(text: str) -> bytes:
    from docx import Document

    document = Document()
    document.add_paragraph(text)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _upload(service, scope, filename, content):
    return service.upload(scope, filename, content)


def test_txt_upload_extracts_normalizes_chunks_and_audits(session_factory, tenant_pair, document_service):
    first, _ = tenant_pair
    original = b"Product   guide\r\nProvides clear support."
    document = _upload(document_service, first.scope, "guide.txt", original)

    assert document.status == "processed"
    assert document.extracted_text == "Product   guide\r\nProvides clear support."
    assert document.normalized_text == "Product guide\nProvides clear support."
    assert document.content_sha256
    assert document.storage_key and not (document_service.settings.storage_path.parent / document.storage_key).exists()
    assert (document_service.storage.root / document.storage_key).read_bytes() == original
    chunks = document_service.chunks(first.scope, document.id)
    assert chunks is not None and chunks
    assert chunks[0].content in document.normalized_text

    with session_factory() as session:
        actions = list(
            session.scalars(
                select(AuditEvent.action_key)
                .where(AuditEvent.target_id == document.id)
                .order_by(AuditEvent.created_at, AuditEvent.action_key)
            )
        )
    assert set(actions) == {
        "knowledge_document.uploaded",
        "knowledge_document.processing",
        "knowledge_document.processed",
    }


def test_pdf_upload_extracts_text(tenant_pair, document_service):
    first, _ = tenant_pair
    document = _upload(document_service, first.scope, "guide.pdf", _minimal_pdf("PDF extraction works"))
    assert document.status == "processed"
    assert "PDF extraction works" in document.normalized_text


def test_docx_upload_extracts_text(tenant_pair, document_service):
    first, _ = tenant_pair
    document = _upload(document_service, first.scope, "guide.docx", _docx("DOCX extraction works"))
    assert document.status == "processed"
    assert "DOCX extraction works" in document.normalized_text


@pytest.mark.parametrize(
    ("filename", "content", "max_bytes", "expected_code"),
    [
        ("notes.rtf", b"text", 100, "unsupported_format"),
        ("fake.pdf", b"not a pdf", 100, "invalid_file_content"),
        ("fake.docx", b"PK but not a zip", 100, "invalid_file_content"),
        ("fake.txt", b"\xff\xfe\x00", 100, "invalid_file_content"),
        ("large.txt", b"12345", 4, "file_too_large"),
        ("empty.txt", b"", 100, "empty_document"),
    ],
)
def test_invalid_uploads_are_rejected(filename, content, max_bytes, expected_code):
    with pytest.raises(DocumentInputError) as error:
        validate_document(filename, content, max_bytes)
    assert error.value.code == expected_code


def test_blank_extractable_format_is_failed_and_file_is_removed(tenant_pair, document_service):
    first, _ = tenant_pair
    document = _upload(document_service, first.scope, "blank.pdf", _minimal_pdf(""))

    assert document.status == "failed"
    assert document.processing_error_code == "empty_document"
    assert document.processing_error_message == "No readable text was found in the document."
    assert document.storage_key is None
    assert list(document_service.storage.root.iterdir()) == []


def test_normalization_and_chunk_order_overlap():
    assert normalize_text("  A\tB\r\n\r\n  C  ") == "A B\n\nC"
    chunks = chunk_text("abcdefghijklmnopqrstuvwxyz", 10, 3)
    assert [chunk.index for chunk in chunks] == [0, 1, 2, 3]
    assert [chunk.content for chunk in chunks] == ["abcdefghij", "hijklmnopq", "opqrstuvwx", "vwxyz"]
    assert all(left.end_offset > right.start_offset for left, right in zip(chunks, chunks[1:]))
    assert all(chunk.content for chunk in chunks)


def test_processing_status_transitions_are_restricted():
    document = KnowledgeDocument(status="pending")
    transition_status(document, "processing")
    assert document.status == "processing"
    transition_status(document, "failed", error=DocumentProcessingError("parse_error", "Safe message"))
    assert document.status == "failed"
    assert document.processing_error_code == "parse_error"
    assert document.storage_key is None
    with pytest.raises(ValueError, match="Invalid document status transition"):
        transition_status(document, "processing")


def test_document_api_scope_fails_closed_without_development_mode(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("DOCUMENT_TENANT_ORGANIZATION_ID", str(uuid4()))
    monkeypatch.setenv("DOCUMENT_TENANT_WORKSPACE_ID", str(uuid4()))
    monkeypatch.setenv("DOCUMENT_TENANT_MEMBERSHIP_ID", str(uuid4()))
    with pytest.raises(RuntimeError, match="disabled outside development"):
        configured_document_scope()


def test_document_and_chunk_reads_are_tenant_scoped(tenant_pair, document_service):
    first, second = tenant_pair
    document = _upload(document_service, first.scope, "private.txt", b"First tenant document text")
    assert document_service.get(first.scope, document.id) is not None
    assert document_service.get(second.scope, document.id) is None
    assert document_service.chunks(second.scope, document.id) is None
    assert document_service.list(first.scope)[0].id == document.id
    assert document_service.list(second.scope) == []


def test_database_rejects_cross_tenant_document_and_chunk_references(session_factory, tenant_pair):
    first, second = tenant_pair
    with pytest.raises(IntegrityError):
        with transaction(session_factory) as session:
            session.add(
                KnowledgeDocument(
                    id=uuid4(),
                    organization_id=first.organization_id,
                    workspace_id=second.workspace_id,
                    uploaded_by_membership_id=first.membership_id,
                    title="invalid tenant document",
                    original_filename="bad.txt",
                    file_extension=".txt",
                    detected_content_type="text/plain; charset=utf-8",
                    byte_size=3,
                    content_sha256="a" * 64,
                    status="processed",
                    normalized_text="bad",
                )
            )

    document = KnowledgeDocument(
        id=uuid4(),
        organization_id=first.organization_id,
        workspace_id=first.workspace_id,
        uploaded_by_membership_id=first.membership_id,
        title="valid parent",
        original_filename="ok.txt",
        file_extension=".txt",
        detected_content_type="text/plain; charset=utf-8",
        byte_size=3,
        content_sha256="b" * 64,
        status="processed",
        normalized_text="abc",
    )
    with transaction(session_factory) as session:
        session.add(document)

    with pytest.raises(IntegrityError):
        with transaction(session_factory) as session:
            session.add(
                KnowledgeDocumentChunk(
                    organization_id=first.organization_id,
                    workspace_id=second.workspace_id,
                    document_id=document.id,
                    chunk_index=0,
                    content="cross tenant",
                    start_offset=0,
                    end_offset=12,
                )
            )


def test_processing_failure_audit_and_state_rollback_together(session_factory, tenant_pair):
    first, _ = tenant_pair
    document_id = uuid4()
    with pytest.raises(RuntimeError, match="force rollback"):
        with transaction(session_factory) as session:
            document = KnowledgeDocument(
                id=document_id,
                organization_id=first.organization_id,
                workspace_id=first.workspace_id,
                uploaded_by_membership_id=first.membership_id,
                title="rollback.txt",
                original_filename="rollback.txt",
                file_extension=".txt",
                detected_content_type="text/plain; charset=utf-8",
                byte_size=3,
                content_sha256="c" * 64,
                status="failed",
                processing_error_code="test_failure",
                processing_error_message="Safe failure",
            )
            session.add(document)
            session.flush()
            record_event(
                session,
                first.scope,
                actor_membership_id=first.membership_id,
                action_key="knowledge_document.failed",
                target_type="knowledge_document",
                target_id=document_id,
                safe_metadata={"error_code": "test_failure"},
            )
            raise RuntimeError("force rollback")

    with session_factory() as session:
        assert session.get(KnowledgeDocument, document_id) is None
        assert session.scalar(select(AuditEvent.id).where(AuditEvent.target_id == document_id)) is None


def test_storage_rejects_path_traversal_and_response_hides_paths(tenant_pair, document_service):
    first, _ = tenant_pair
    with pytest.raises(ValueError):
        document_service.storage.read("../../outside.txt")
    document = _upload(document_service, first.scope, "..\\private.txt", b"safe display name")
    assert document.original_filename == "private.txt"
    assert document_service.storage.root in document_service.storage._resolve_key(document.storage_key).parents


def test_http_upload_and_cross_tenant_metadata_access(tenant_pair, document_service):
    first, second = tenant_pair
    app.dependency_overrides[get_tenant_scope] = lambda: first.scope
    app.dependency_overrides[get_document_service] = lambda: document_service
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/knowledge-documents",
                files={"file": ("sample.txt", b"API upload text", "application/octet-stream")},
                headers={
                    "X-Organization-ID": str(second.organization_id),
                    "X-Workspace-ID": str(second.workspace_id),
                },
            )
            assert response.status_code == 201
            payload = response.json()
            assert payload["status"] == "processed"
            assert "storage_key" not in payload and "storage_path" not in payload
            document_id = payload["id"]
            assert client.get(f"/api/v1/knowledge-documents/{document_id}/content").json()["content"] == "API upload text"
            assert client.get(f"/api/v1/knowledge-documents/{document_id}/chunks").json()

            app.dependency_overrides[get_tenant_scope] = lambda: second.scope
            assert client.get(f"/api/v1/knowledge-documents/{document_id}").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_http_upload_validation_errors(tenant_pair, document_service):
    first, _ = tenant_pair
    app.dependency_overrides[get_tenant_scope] = lambda: first.scope
    app.dependency_overrides[get_document_service] = lambda: document_service
    try:
        with TestClient(app) as client:
            unsupported = client.post("/api/v1/knowledge-documents", files={"file": ("note.rtf", b"text")})
            oversized = client.post(
                "/api/v1/knowledge-documents",
                files={"file": ("large.txt", b"x" * (document_service.settings.max_upload_bytes + 1))},
            )
            assert unsupported.status_code == 415
            assert unsupported.json()["detail"]["code"] == "unsupported_format"
            assert oversized.status_code == 413
            assert oversized.json()["detail"]["code"] == "file_too_large"
    finally:
        app.dependency_overrides.clear()
