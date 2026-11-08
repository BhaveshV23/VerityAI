from sqlalchemy import func, select

from app.db.seed_demo import seed_development_data
from app.models import Organization, Policy, PolicyVersion, Workspace


def test_seed_provisions_apex_policies_and_is_idempotent(
    session_factory, monkeypatch
):
    monkeypatch.setenv("APP_ENV", "development")

    first = seed_development_data(session_factory)
    second = seed_development_data(session_factory)

    assert first == second
    with session_factory() as session:
        organization = session.scalar(
            select(Organization).where(Organization.slug == "apex-financial")
        )
        assert organization is not None
        assert organization.name == "Apex Financial Services"
        workspace = session.scalar(
            select(Workspace).where(
                Workspace.organization_id == organization.id,
                Workspace.slug == "marketing-content",
            )
        )
        assert workspace is not None
        assert workspace.name == "Marketing Content Review"
        assert session.scalar(
            select(func.count(Policy.id)).where(
                Policy.organization_id == organization.id,
                Policy.workspace_id == workspace.id,
                Policy.status == "Active",
            )
        ) == 2
        assert session.scalar(
            select(func.count(PolicyVersion.id))
            .join(Policy, Policy.id == PolicyVersion.policy_id)
            .where(
                Policy.organization_id == organization.id,
                Policy.workspace_id == workspace.id,
            )
        ) == 2
