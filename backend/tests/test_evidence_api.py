from io import BytesIO
from pathlib import Path
import shutil
from uuid import uuid4

from docx import Document
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.v1.evidence import router
from app.core.dependencies import get_db, get_tenant_scope
from app.documents.config import DocumentSettings
from app.models import EvidenceRecord, EvidenceVersion
from app.modules.tenancy.schemas import TenantScope


def _storage_path() -> Path:
    path = Path(__file__).resolve().parent / "_test_storage" / uuid4().hex
    path.mkdir(parents=True)
    return path


def _docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _pdf_bytes(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
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
    ("filename", "content", "content_type", "expected_text"),
    [
        ("schedule.docx", _docx_bytes("The annual yield is 4 percent."), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "The annual yield is 4 percent."),
        ("schedule.pdf", _pdf_bytes("Annual yield is 4 percent."), "application/pdf", "Annual yield is 4 percent."),
    ],
    ids=["docx", "pdf"],
)
def test_upload_parses_and_persists_tenant_scoped_evidence(
    session_factory,
    tenant_pair,
    monkeypatch,
    filename,
    content,
    content_type,
    expected_text,
):
    tenant, other_tenant = tenant_pair
    storage_root = _storage_path()
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(storage_root / "private"))
    monkeypatch.setenv("DOCUMENT_MAX_UPLOAD_BYTES", "1000000")
    app = FastAPI()
    app.include_router(router)

    def override_db():
        with session_factory() as session:
            yield session

    scope = TenantScope(
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
        user_id=tenant.user_id,
        permissions={"evidence.manage", "evidence.read.workspace"},
    )
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_tenant_scope] = lambda: scope

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/organizations/{tenant.organization_id}/workspaces/{tenant.workspace_id}/evidence",
            data={"title": "Deposit schedule", "valid_from": "2026-01-01", "valid_until": "2026-12-31"},
            files={"file": (filename, content, content_type)},
        )
        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["primary_lifecycle_state"] == "Uploaded"
        assert payload["valid_from"] == "2026-01-01"
        assert payload["valid_until"] == "2026-12-31"
        assert expected_text.lower() in payload["extracted_text"].lower()
        evidence_id = payload["id"]
        version_id = payload["version_id"]

        listing = client.get(
            f"/api/v1/organizations/{tenant.organization_id}/workspaces/{tenant.workspace_id}/evidence"
        )
        assert listing.status_code == 200
        assert any(item["id"] == evidence_id for item in listing.json())
        cross_tenant = client.get(
            f"/api/v1/organizations/{other_tenant.organization_id}/workspaces/{other_tenant.workspace_id}/evidence"
        )
        assert cross_tenant.status_code == 404

    with session_factory() as session:
        record = session.get(EvidenceRecord, evidence_id)
        version = session.get(EvidenceVersion, version_id)
        assert record is not None
        assert record.organization_id == tenant.organization_id
        assert record.workspace_id == tenant.workspace_id
        assert record.current_version_id == version.id
        assert record.primary_lifecycle_state == "Uploaded"
        assert version.version_number == 1
        assert version.extracted_text.lower() == expected_text.lower()
        assert version.private_file_key.endswith("." + filename.rsplit(".", 1)[1])

    app.dependency_overrides.clear()
    shutil.rmtree(storage_root, ignore_errors=True)
