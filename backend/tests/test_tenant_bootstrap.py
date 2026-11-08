import pytest
from sqlalchemy import select, func
from uuid import UUID

from app.models import Organization, User, Workspace, WorkspaceMembership
from app.scripts.bootstrap_development_tenant import (
    DevelopmentEnvironmentRequired,
    initialize_development_tenant,
    require_development_environment,
)


def test_bootstrap_is_idempotent_and_creates_valid_relationships(session_factory, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")

    first = initialize_development_tenant(session_factory)
    second = initialize_development_tenant(session_factory)

    assert first == second
    with session_factory() as session:
        organization = session.get(Organization, UUID(first.organization_id))
        workspace = session.get(Workspace, UUID(first.workspace_id))
        membership = session.get(WorkspaceMembership, UUID(first.membership_id))
        assert organization is not None
        assert workspace is not None and workspace.organization_id == organization.id
        assert membership is not None
        assert membership.organization_id == organization.id
        assert membership.workspace_id == workspace.id
        assert session.get(User, membership.user_id) is not None
        assert session.scalar(
            select(func.count()).select_from(Organization).where(Organization.slug == "verityai-local-dev")
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(Workspace).where(
                Workspace.organization_id == organization.id,
                Workspace.slug == "development",
            )
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(WorkspaceMembership).where(
                WorkspaceMembership.organization_id == organization.id,
                WorkspaceMembership.workspace_id == workspace.id,
                WorkspaceMembership.user_id == membership.user_id,
            )
        ) == 1


@pytest.mark.parametrize("app_env", [None, "production", "test"])
def test_bootstrap_refuses_unapproved_environment_before_database_access(app_env, monkeypatch):
    if app_env is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", app_env)
    with pytest.raises(DevelopmentEnvironmentRequired, match="explicitly set APP_ENV=development"):
        require_development_environment()
