from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.v1.analysis import router
from app.core.dependencies import get_db
from app.models import (
    AnalysisRun,
    Finding,
    MembershipRoleAssignment,
    Permission,
    Role,
    RolePermission,
)
from app.modules.submissions.services import create_submission_version
from app.modules.tenancy.schemas import TenantScope


def _tenant_headers(tenant):
    return {
        "X-Organization-ID": str(tenant.organization_id),
        "X-Workspace-ID": str(tenant.workspace_id),
        "X-User-ID": str(tenant.user_id),
    }


def _app_with_session(session_factory):
    app = FastAPI()
    app.include_router(router)

    def override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return app


def _grant_read_permission(session, tenant):
    permission = session.scalar(select(Permission).where(Permission.key == "submission.read.workspace"))
    if permission is None:
        permission = Permission(key="submission.read.workspace", description="Read workspace submissions and analysis")
        session.add(permission)
        session.flush()
    role = Role(
        organization_id=tenant.organization_id,
        key=f"analysis-reader-{tenant.workspace_id.hex[:8]}",
        display_name="Analysis Reader",
    )
    session.add(role)
    session.flush()
    session.add_all(
        [
            RolePermission(
                organization_id=tenant.organization_id,
                role_id=role.id,
                permission_id=permission.id,
                assigned_by_membership_id=tenant.membership_id,
            ),
            MembershipRoleAssignment(
                organization_id=tenant.organization_id,
                workspace_id=tenant.workspace_id,
                membership_id=tenant.membership_id,
                role_id=role.id,
                assigned_by_membership_id=tenant.membership_id,
            ),
        ]
    )
    session.flush()


def _make_version_and_run(session, tenant, *, run_number: int, version=None):
    scope = TenantScope(
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
        user_id=tenant.user_id,
        permissions={"submission.read.workspace"},
    )
    if version is None:
        version = create_submission_version(
            session,
            scope,
            submitter_id=tenant.user_id,
            source_type="text",
            submitted_text=f"Test submission for run {run_number}.",
        )
    run = AnalysisRun(
        id=uuid4(),
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
        submission_version_id=version.id,
        run_number=run_number,
        overall_state="Succeeded",
        started_at=datetime.now(timezone.utc),
    )
    session.add(run)
    session.flush()
    return version, run


def test_analysis_read_apis_return_ordered_runs_and_serialized_findings(
    session_factory, tenant_pair, monkeypatch
):
    monkeypatch.setenv("APP_ENV", "development")
    tenant, _ = tenant_pair
    with session_factory() as session:
        _grant_read_permission(session, tenant)
        version, older_run = _make_version_and_run(session, tenant, run_number=1)
        _, latest_run = _make_version_and_run(session, tenant, run_number=2, version=version)
        finding = Finding(
            id=uuid4(),
            organization_id=tenant.organization_id,
            workspace_id=tenant.workspace_id,
            analysis_run_id=latest_run.id,
            submission_version_id=latest_run.submission_version_id,
            category="Unverified claim",
            attention_label="unverified",
            explanation="No eligible evidence was matched.",
            is_unresolved=True,
        )
        session.add(finding)
        session.commit()

    app = _app_with_session(session_factory)
    with TestClient(app) as client:
        runs_response = client.get(
            f"/api/v1/organizations/{tenant.organization_id}/workspaces/{tenant.workspace_id}/submission-versions/{version.id}/analysis-runs",
            headers=_tenant_headers(tenant),
        )
        findings_response = client.get(
            f"/api/v1/organizations/{tenant.organization_id}/workspaces/{tenant.workspace_id}/analysis-runs/{latest_run.id}/findings",
            headers=_tenant_headers(tenant),
        )

    assert runs_response.status_code == 200
    assert [row["run_number"] for row in runs_response.json()] == [2, 1]
    assert runs_response.json()[0]["id"] == str(latest_run.id)
    assert older_run.id != latest_run.id
    assert findings_response.status_code == 200
    assert findings_response.json() == [
        {
            "id": str(finding.id),
            "analysis_run_id": str(latest_run.id),
            "submission_version_id": str(version.id),
            "claim_id": None,
            "category": "Unverified claim",
            "attention_label": "unverified",
            "explanation": "No eligible evidence was matched.",
            "policy_id": None,
            "policy_version_id": None,
            "evidence_record_id": None,
            "evidence_version_id": None,
            "is_unresolved": True,
            "resolution_status": "open",
            "effective_disposition": None,
            "blocks_clean_approval": True,
            "disposition_history": [],
        }
    ]


def test_analysis_read_apis_hide_cross_tenant_versions_and_runs(
    session_factory, tenant_pair, monkeypatch
):
    monkeypatch.setenv("APP_ENV", "development")
    first, second = tenant_pair
    with session_factory() as session:
        _grant_read_permission(session, first)
        second_version, second_run = _make_version_and_run(session, second, run_number=1)
        session.commit()

    app = _app_with_session(session_factory)
    with TestClient(app) as client:
        version_response = client.get(
            f"/api/v1/organizations/{first.organization_id}/workspaces/{first.workspace_id}/submission-versions/{second_version.id}/analysis-runs",
            headers=_tenant_headers(first),
        )
        run_response = client.get(
            f"/api/v1/organizations/{first.organization_id}/workspaces/{first.workspace_id}/analysis-runs/{second_run.id}/findings",
            headers=_tenant_headers(first),
        )

    assert version_response.status_code == 404
    assert run_response.status_code == 404
