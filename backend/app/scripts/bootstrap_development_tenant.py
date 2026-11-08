"""Create one idempotent local development tenant, never production seed data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


ORGANIZATION_SLUG = "verityai-local-dev"
WORKSPACE_SLUG = "development"
USER_ID = uuid5(NAMESPACE_URL, "verityai.local-development/bootstrap-user/v1")
ORGANIZATION_NAME = "VerityAI Local Development"
WORKSPACE_NAME = "Development Workspace"
USER_DISPLAY_NAME = "VerityAI Local Development Operator"


class DevelopmentEnvironmentRequired(RuntimeError):
    """Raised unless APP_ENV is explicitly set to development in the process."""


@dataclass(frozen=True, slots=True)
class DevelopmentTenantIds:
    organization_id: str
    workspace_id: str
    membership_id: str


def require_development_environment() -> None:
    if os.environ.get("APP_ENV", "").strip().lower() != "development":
        raise DevelopmentEnvironmentRequired(
            "Refusing tenant bootstrap: explicitly set APP_ENV=development in this process."
        )


def initialize_development_tenant(
    session_factory: sessionmaker[Session] | None = None,
) -> DevelopmentTenantIds:
    """Create or reuse the local organisation, workspace, operator, and membership atomically."""
    require_development_environment()

    from dotenv import load_dotenv

    load_dotenv()
    if session_factory is None:
        from app.db.session import get_session_factory

        session_factory = get_session_factory()

    # Import only after the environment guard; use the same mapped entities as the app.
    from app.models import Organization, User, Workspace, WorkspaceMembership
    from app.tenancy.context import TenantScope, validate_tenant_scope

    with session_factory() as session:
        with session.begin():
            organization = session.scalar(
                select(Organization).where(Organization.slug == ORGANIZATION_SLUG)
            )
            if organization is None:
                organization = Organization(name=ORGANIZATION_NAME, slug=ORGANIZATION_SLUG)
                session.add(organization)
                session.flush()
            elif organization.name != ORGANIZATION_NAME or organization.status != "active":
                raise RuntimeError("The reserved development organization slug is already in use.")

            workspace = session.scalar(
                select(Workspace).where(
                    Workspace.organization_id == organization.id,
                    Workspace.slug == WORKSPACE_SLUG,
                )
            )
            if workspace is None:
                workspace = Workspace(
                    organization_id=organization.id,
                    name=WORKSPACE_NAME,
                    slug=WORKSPACE_SLUG,
                )
                session.add(workspace)
                session.flush()
            elif workspace.name != WORKSPACE_NAME or workspace.status != "active":
                raise RuntimeError("The reserved development workspace slug is already in use.")

            user = session.get(User, USER_ID)
            if user is None:
                user = User(id=USER_ID, display_name=USER_DISPLAY_NAME)
                session.add(user)
                session.flush()
            elif user.display_name != USER_DISPLAY_NAME:
                raise RuntimeError("The reserved development operator ID is already in use.")

            membership = session.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.organization_id == organization.id,
                    WorkspaceMembership.workspace_id == workspace.id,
                    WorkspaceMembership.user_id == user.id,
                )
            )
            if membership is None:
                membership = WorkspaceMembership(
                    organization_id=organization.id,
                    workspace_id=workspace.id,
                    user_id=user.id,
                )
                session.add(membership)
                session.flush()
            elif membership.status != "active":
                raise RuntimeError("The existing development membership is not active; no changes were made.")

            validate_tenant_scope(
                session,
                TenantScope(organization.id, workspace.id, membership.id),
            )

            result = DevelopmentTenantIds(
                organization_id=str(organization.id),
                workspace_id=str(workspace.id),
                membership_id=str(membership.id),
            )
    return result


def main() -> None:
    require_development_environment()
    try:
        result = initialize_development_tenant()
    except Exception as exc:
        raise SystemExit(f"Development tenant bootstrap failed; its transaction was rolled back ({type(exc).__name__}).") from None
    print(json.dumps(asdict(result), indent=2))


if __name__ == "__main__":
    main()
