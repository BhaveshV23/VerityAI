"""Tenant scope values and database validation helpers."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Workspace, WorkspaceMembership


class InvalidTenantScope(ValueError):
    """Raised when a requested organization/workspace pair is inconsistent."""


@dataclass(frozen=True, slots=True)
class TenantScope:
    organization_id: UUID
    workspace_id: UUID
    membership_id: UUID | None = None


def validate_tenant_scope(session: Session, scope: TenantScope) -> None:
    workspace_exists = session.scalar(
        select(Workspace.id).where(
            Workspace.id == scope.workspace_id,
            Workspace.organization_id == scope.organization_id,
        )
    )
    if workspace_exists is None:
        raise InvalidTenantScope("Workspace does not belong to the supplied organization")

    if scope.membership_id is not None:
        membership_exists = session.scalar(
            select(WorkspaceMembership.id).where(
                WorkspaceMembership.id == scope.membership_id,
                WorkspaceMembership.organization_id == scope.organization_id,
                WorkspaceMembership.workspace_id == scope.workspace_id,
            )
        )
        if membership_exists is None:
            raise InvalidTenantScope("Membership does not belong to the supplied tenant scope")
