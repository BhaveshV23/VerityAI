from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.v1.governance import router
from app.core.dependencies import get_db
from app.models import (
    AnalysisRun,
    Finding,
    MembershipRoleAssignment,
    Permission,
    Policy,
    PolicyVersion,
    Role,
    RolePermission,
)
from app.modules.submissions.services import create_submission_version
from app.modules.tenancy.schemas import TenantScope


def _headers(tenant):
    return {
        "X-Organization-ID": str(tenant.organization_id),
        "X-Workspace-ID": str(tenant.workspace_id),
        "X-User-ID": str(tenant.user_id),
    }


def _make_app(session_factory):
    app = FastAPI()
    app.include_router(router)

    def override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return app


def _grant_insight_read(session, tenant):
    permission = session.scalar(select(Permission).where(Permission.key == "insight.read"))
    if permission is None:
        permission = Permission(key="insight.read", description="Read workspace governance metrics")
        session.add(permission)
        session.flush()
    role = Role(
        organization_id=tenant.organization_id,
        key=f"insight-reader-{tenant.workspace_id.hex[:8]}",
        display_name="Insight Reader",
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


def test_governance_endpoint_returns_workspace_metrics_and_recurring_count_two(
    session_factory, tenant_pair, monkeypatch
):
    monkeypatch.setenv("APP_ENV", "development")
    tenant, _ = tenant_pair
    with session_factory() as session:
        _grant_insight_read(session, tenant)
        scope = TenantScope(
            organization_id=tenant.organization_id,
            workspace_id=tenant.workspace_id,
            user_id=tenant.user_id,
            permissions={"insight.read"},
        )
        submission_version = create_submission_version(
            session,
            scope,
            submitter_id=tenant.user_id,
            source_type="text",
            submitted_text="The annual fee is 5%.",
        )
        run = AnalysisRun(
            id=uuid4(),
            organization_id=tenant.organization_id,
            workspace_id=tenant.workspace_id,
            submission_version_id=submission_version.id,
            run_number=1,
            overall_state="Succeeded",
            started_at=datetime.now(timezone.utc),
        )
        policy = Policy(
            id=uuid4(),
            organization_id=tenant.organization_id,
            workspace_id=tenant.workspace_id,
            name="Fee policy",
            category="fees",
            status="Active",
            created_by_membership_id=tenant.membership_id,
        )
        session.add_all([run, policy])
        session.flush()
        policy_version = PolicyVersion(
            id=uuid4(),
            organization_id=tenant.organization_id,
            workspace_id=tenant.workspace_id,
            policy_id=policy.id,
            version_number=1,
            rule_text="fees must be substantiated",
            rule_type="prohibited_term",
            status_snapshot="Active",
            created_by_membership_id=tenant.membership_id,
        )
        session.add(policy_version)
        session.flush()
        session.add_all(
            [
                Finding(
                    id=uuid4(),
                    organization_id=tenant.organization_id,
                    workspace_id=tenant.workspace_id,
                    analysis_run_id=run.id,
                    submission_version_id=submission_version.id,
                    category="Policy finding",
                    explanation="First recurring finding.",
                    policy_id=policy.id,
                    policy_version_id=policy_version.id,
                    is_unresolved=True,
                ),
                Finding(
                    id=uuid4(),
                    organization_id=tenant.organization_id,
                    workspace_id=tenant.workspace_id,
                    analysis_run_id=run.id,
                    submission_version_id=submission_version.id,
                    category="Policy finding",
                    explanation="Second recurring finding.",
                    policy_id=policy.id,
                    policy_version_id=policy_version.id,
                    is_unresolved=True,
                ),
            ]
        )
        session.commit()

    with TestClient(_make_app(session_factory)) as client:
        response = client.get(
            f"/api/v1/organizations/{tenant.organization_id}/workspaces/{tenant.workspace_id}/governance-metrics",
            headers=_headers(tenant),
        )

    assert response.status_code == 200
    metrics = response.json()
    assert metrics["period_days"] == 30
    assert metrics["submissions_count"] == 1
    assert len(metrics["recurring_policy_findings"]) == 1
    assert metrics["recurring_policy_findings"][0] == {
        "policy_version_id": str(policy_version.id),
        "count": 2,
    }
    assert set(metrics["review_decision_trends"]) == {
        "Approved",
        "Approved with documented exceptions",
        "Changes requested",
        "Rejected",
    }
    assert "evidence_attention" in metrics


def test_governance_endpoint_returns_404_for_cross_tenant_workspace(
    session_factory, tenant_pair, monkeypatch
):
    monkeypatch.setenv("APP_ENV", "development")
    first, second = tenant_pair
    with session_factory() as session:
        _grant_insight_read(session, first)
        session.commit()

    with TestClient(_make_app(session_factory)) as client:
        response = client.get(
            f"/api/v1/organizations/{second.organization_id}/workspaces/{second.workspace_id}/governance-metrics",
            headers=_headers(first),
        )

    assert response.status_code == 404
