from hashlib import sha256
from io import BytesIO
from pathlib import Path
import shutil
from uuid import UUID
from uuid import uuid4

from docx import Document
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.api.v1.submissions import router
from app.core.dependencies import get_db, get_tenant_scope
from app.models import AnalysisRun, AnalysisStageResult, Submission, SubmissionVersion, SubmissionVersionArtifact
from app.modules.analysis.orchestrator import REQUIRED_STAGE_ORDER
from app.modules.tenancy.schemas import TenantScope


@pytest.fixture
def tmp_path():
    """Use a workspace-local temp directory because the host temp ACL may be restricted."""
    path = Path(__file__).resolve().parent / "_tmp_submission_docs" / uuid4().hex
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _scope(tenant, *, organization_id=None, workspace_id=None):
    return TenantScope(
        organization_id=organization_id or tenant.organization_id,
        workspace_id=workspace_id or tenant.workspace_id,
        user_id=tenant.user_id,
        permissions={"submission.create"},
    )


def _app(session_factory, scope):
    app = FastAPI()
    app.include_router(router)

    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_tenant_scope] = lambda: scope
    return app


def _docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def _pdf_bytes(text: str = "") -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii") if text else b""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, item in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii") + item + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        output.extend(f"{offset:010} 00000 n \n".encode("ascii"))
    output.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode("ascii"))
    return bytes(output)


@pytest.mark.parametrize(
    ("filename", "content", "expected_text"),
    [
        ("campaign.pdf", _pdf_bytes("A guaranteed annual yield is 4 percent."), "A guaranteed annual yield is 4 percent."),
        ("campaign.docx", _docx_bytes("A guaranteed annual yield is 4 percent."), "A guaranteed annual yield is 4 percent."),
    ],
    ids=["pdf", "docx"],
)
def test_document_submission_persists_original_version_extraction_and_pipeline(
    session_factory, tenant_pair, monkeypatch, tmp_path, filename, content, expected_text
):
    tenant, _ = tenant_pair
    storage_root = tmp_path / "private-documents"
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(storage_root))
    monkeypatch.setenv("DOCUMENT_MAX_UPLOAD_BYTES", "1000000")
    monkeypatch.setenv("AI_ENABLED", "false")
    app = _app(session_factory, _scope(tenant))

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/organizations/{tenant.organization_id}/workspaces/{tenant.workspace_id}/submissions/documents",
            files={"file": (filename, content, "application/octet-stream")},
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["analysis_status"] == "Succeeded"
    assert body["extraction_status"] == "Succeeded"
    assert expected_text in body["extracted_text"]
    version_id, run_id = UUID(body["version_id"]), UUID(body["analysis_run_id"])

    with session_factory() as session:
        version = session.get(SubmissionVersion, version_id)
        submission = session.get(Submission, UUID(body["submission_id"]))
        run = session.get(AnalysisRun, run_id)
        stages = list(session.scalars(select(AnalysisStageResult).where(AnalysisStageResult.analysis_run_id == run_id)))
        artifact = session.scalar(
            select(SubmissionVersionArtifact).where(
                SubmissionVersionArtifact.submission_version_id == version_id,
                SubmissionVersionArtifact.analysis_run_id == run_id,
            )
        )

    assert version is not None and version.submitted_text is None
    assert version.source_type == filename.rsplit(".", 1)[-1]
    assert version.source_hash == sha256(content).hexdigest()
    assert version.original_file_key is not None
    assert Path(version.original_file_key).name == version.original_file_key
    assert submission is not None and submission.current_status == "Submitted"
    assert run is not None and run.submission_version_id == version.id and run.overall_state == "Succeeded"
    assert {stage.stage_key: stage.state for stage in stages} == {key: "Succeeded" for key in REQUIRED_STAGE_ORDER}
    assert artifact is not None and artifact.normalized_text == body["extracted_text"]
    assert artifact.checksum == sha256(body["extracted_text"].encode()).hexdigest()
    assert artifact.analysis_run_id == run.id and artifact.submission_version_id == version.id
    assert (storage_root / "submissions" / version.original_file_key).read_bytes() == content


@pytest.mark.parametrize(
    ("filename", "content", "expected_status"),
    [
        ("notes.txt", b"plain file is not accepted here", 415),
        ("campaign.pdf", b"%PDF-1.4 not a parseable PDF", 422),
        ("campaign.docx", b"PK not a valid zip archive", 422),
        ("campaign.pdf", _pdf_bytes(), 422),
        ("campaign.pdf", b"", 422),
    ],
    ids=["unsupported-format", "corrupt-pdf", "corrupt-docx", "no-extractable-text", "empty-document"],
)
def test_invalid_or_unreadable_documents_create_no_submission_or_files(
    session_factory, tenant_pair, monkeypatch, tmp_path, filename, content, expected_status
):
    tenant, _ = tenant_pair
    storage_root = tmp_path / "private-documents"
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(storage_root))
    monkeypatch.setenv("DOCUMENT_MAX_UPLOAD_BYTES", "1000000")
    app = _app(session_factory, _scope(tenant))
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/organizations/{tenant.organization_id}/workspaces/{tenant.workspace_id}/submissions/documents",
            files={"file": (filename, content, "application/octet-stream")},
        )

    assert response.status_code == expected_status, response.text
    assert response.json()["detail"]["error"]["code"]
    with session_factory() as session:
        assert session.scalar(select(Submission.id).where(
            Submission.organization_id == tenant.organization_id,
            Submission.id != tenant.submission_id,
        )) is None
        assert session.scalar(select(AnalysisRun.id).where(AnalysisRun.organization_id == tenant.organization_id)) is None
    assert not storage_root.exists() or not [path for path in storage_root.rglob("*") if path.is_file()]


def test_oversized_upload_is_rejected_before_persistence(session_factory, tenant_pair, monkeypatch, tmp_path):
    tenant, _ = tenant_pair
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(tmp_path / "private-documents"))
    monkeypatch.setenv("DOCUMENT_MAX_UPLOAD_BYTES", "16")
    app = _app(session_factory, _scope(tenant))
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/organizations/{tenant.organization_id}/workspaces/{tenant.workspace_id}/submissions/documents",
            files={"file": ("large.pdf", _pdf_bytes("more than sixteen bytes"), "application/pdf")},
        )
    assert response.status_code == 413
    with session_factory() as session:
        assert session.scalar(select(Submission.id).where(
            Submission.organization_id == tenant.organization_id,
            Submission.id != tenant.submission_id,
        )) is None
        assert session.scalar(select(AnalysisRun.id).where(AnalysisRun.organization_id == tenant.organization_id)) is None


def test_document_submission_enforces_requested_tenant_scope(session_factory, tenant_pair, monkeypatch, tmp_path):
    tenant, other_tenant = tenant_pair
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(tmp_path / "private-documents"))
    app = _app(session_factory, _scope(tenant))
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/organizations/{other_tenant.organization_id}/workspaces/{other_tenant.workspace_id}/submissions/documents",
            files={"file": ("campaign.pdf", _pdf_bytes("A factual claim."), "application/pdf")},
        )
    assert response.status_code == 403
    assert not (tmp_path / "private-documents").exists()


def test_analysis_failure_keeps_durable_document_and_reports_incomplete(
    session_factory, tenant_pair, monkeypatch, tmp_path
):
    from app.modules.analysis import orchestrator

    tenant, _ = tenant_pair
    storage_root = tmp_path / "private-documents"
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(storage_root))
    monkeypatch.setenv("DOCUMENT_MAX_UPLOAD_BYTES", "1000000")
    monkeypatch.setattr(orchestrator, "extract_claims", lambda _text: (_ for _ in ()).throw(RuntimeError("stage failure")))
    app = _app(session_factory, _scope(tenant))
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/organizations/{tenant.organization_id}/workspaces/{tenant.workspace_id}/submissions/documents",
            files={"file": ("campaign.docx", _docx_bytes("A factual claim."), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["analysis_status"] == "Incomplete"
    assert body["extraction_status"] == "Succeeded"
    with session_factory() as session:
        version = session.get(SubmissionVersion, UUID(body["version_id"]))
        run = session.get(AnalysisRun, UUID(body["analysis_run_id"]))
        assert version is not None and version.original_file_key
        assert run is not None and run.overall_state == "Incomplete"
        assert session.scalar(select(SubmissionVersionArtifact.id).where(SubmissionVersionArtifact.analysis_run_id == run.id))
        stages = list(session.scalars(select(AnalysisStageResult).where(AnalysisStageResult.analysis_run_id == run.id)))
    assert {stage.stage_key: stage.state for stage in stages}["claim_extraction"] == "Failed"
    assert (storage_root / "submissions" / version.original_file_key).exists()


def test_original_file_is_removed_if_source_version_persistence_fails(
    tenant_pair, monkeypatch, tmp_path
):
    from app.documents.config import DocumentSettings
    from app.modules.submissions import services

    tenant, _ = tenant_pair
    storage_root = tmp_path / "private-documents"
    settings = DocumentSettings(storage_root, 1000000, 1200, 150)

    def fail_persist(*_args, **_kwargs):
        raise RuntimeError("simulated persistence failure")

    monkeypatch.setattr(services, "create_submission_version", fail_persist)
    with pytest.raises(RuntimeError, match="simulated persistence failure"):
        services.create_document_submission_with_analysis(
            db=None,
            tenant_scope=_scope(tenant),
            submitter_id=tenant.user_id,
            filename="campaign.docx",
            content=_docx_bytes("A readable statement."),
            settings=settings,
        )
    assert not storage_root.exists() or not [path for path in storage_root.rglob("*") if path.is_file()]

