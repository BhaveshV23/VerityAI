"""FastAPI dependencies for development tenant scope and permission checks."""

from collections.abc import Generator
from ipaddress import ip_address
import os
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_session_factory
from app.models import Organization, User, Workspace, WorkspaceMembership
from app.modules.authorization.permissions import load_active_permissions
from app.modules.tenancy.schemas import TenantScope
from app.scripts.bootstrap_development_tenant import (
    ORGANIZATION_SLUG,
    USER_ID,
    WORKSPACE_SLUG,
)


DEVELOPMENT_MODES = {"development", "dev", "local"}


def get_db() -> Generator[Session, None, None]:
    with get_session_factory()() as session:
        yield session


def _http_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message}},
    )


def _development_fallback(session: Session) -> tuple[UUID, UUID, UUID, UUID]:
    statement = (
        select(
            Organization.id.label("organization_id"),
            Workspace.id.label("workspace_id"),
            User.id.label("user_id"),
            WorkspaceMembership.id.label("membership_id"),
        )
        .join(Workspace, Workspace.organization_id == Organization.id)
        .join(
            WorkspaceMembership,
            (WorkspaceMembership.organization_id == Organization.id)
            & (WorkspaceMembership.workspace_id == Workspace.id),
        )
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(
            Organization.slug == ORGANIZATION_SLUG,
            Organization.status == "active",
            Workspace.slug == WORKSPACE_SLUG,
            Workspace.status == "active",
            User.id == USER_ID,
            WorkspaceMembership.status == "active",
        )
    )
    row = session.execute(statement).first()
    if row is None:
        raise _http_error(
            503,
            "DEVELOPMENT_TENANT_NOT_INITIALIZED",
            "The seeded development tenant is not initialized.",
        )
    organization_id, workspace_id, user_id, membership_id = row
    return organization_id, workspace_id, user_id, membership_id


def _explicit_scope(
    session: Session,
    organization_id: UUID,
    workspace_id: UUID,
    user_id: UUID,
) -> tuple[UUID, UUID, UUID, UUID]:
    statement = (
        select(
            Organization.id.label("organization_id"),
            Workspace.id.label("workspace_id"),
            User.id.label("user_id"),
            WorkspaceMembership.id.label("membership_id"),
        )
        .join(Workspace, Workspace.organization_id == Organization.id)
        .join(
            WorkspaceMembership,
            (WorkspaceMembership.organization_id == Organization.id)
            & (WorkspaceMembership.workspace_id == Workspace.id),
        )
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(
            Organization.id == organization_id,
            Organization.status == "active",
            Workspace.id == workspace_id,
            Workspace.status == "active",
            User.id == user_id,
            WorkspaceMembership.status == "active",
        )
    )
    row = session.execute(statement).first()
    if row is None:
        # Do not distinguish a missing tenant from a user without membership.
        raise _http_error(403, "FORBIDDEN", "The user is not an active member of this workspace.")
    return row.organization_id, row.workspace_id, row.user_id, row.membership_id


def _require_local_request(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host == "testclient":
        return
    try:
        is_loopback = ip_address(host).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise _http_error(
            403,
            "DEVELOPMENT_IDENTITY_DISABLED",
            "Development tenant identity is available only from this machine.",
        )


def get_tenant_scope(request: Request, session: Session = Depends(get_db)) -> TenantScope:
    """Resolve identity and permissions for the requested active workspace membership.

    Header-based identity is a local development convenience, not production
    authentication. It is rejected outside development/local modes.
    """
    app_env = os.getenv("APP_ENV", "").strip().lower()
    is_development = app_env in DEVELOPMENT_MODES
    if is_development:
        _require_local_request(request)
    raw_headers = (
        request.headers.get("X-Organization-ID"),
        request.headers.get("X-Workspace-ID"),
        request.headers.get("X-User-ID"),
    )
    supplied = tuple(value is not None for value in raw_headers)

    if any(supplied) and not all(supplied):
        raise _http_error(
            400,
            "INVALID_TENANT_HEADERS",
            "X-Organization-ID, X-Workspace-ID, and X-User-ID must be supplied together.",
        )

    if all(supplied):
        if not is_development:
            raise _http_error(
                403,
                "DEVELOPMENT_IDENTITY_DISABLED",
                "Header-based development identity is disabled outside development/local mode.",
            )
        try:
            organization_id, workspace_id, user_id = (UUID(value) for value in raw_headers if value is not None)
        except ValueError as exc:
            raise _http_error(400, "INVALID_TENANT_HEADERS", "Tenant headers must contain valid UUIDs.") from exc
        organization_id, workspace_id, user_id, membership_id = _explicit_scope(
            session, organization_id, workspace_id, user_id
        )
    elif is_development:
        organization_id, workspace_id, user_id, membership_id = _development_fallback(session)
    else:
        raise _http_error(
            400,
            "TENANT_HEADERS_REQUIRED",
            "Tenant identity headers are required outside development/local mode.",
        )

    permissions = load_active_permissions(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        membership_id=membership_id,
    )
    return TenantScope(
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=user_id,
        permissions=permissions,
    )


def require_permission(permission_key: str):
    """Return a FastAPI dependency that denies scopes missing a permission key."""
    def permission_dependency(scope: TenantScope = Depends(get_tenant_scope)) -> TenantScope:
        if permission_key not in scope.permissions:
            raise _http_error(
                403,
                "FORBIDDEN",
                f"Permission '{permission_key}' required",
            )
        return scope

    return permission_dependency
