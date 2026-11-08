"""Permission lookup from active workspace role assignments."""

from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models import (
    MembershipRoleAssignment,
    Permission,
    Role,
    RolePermission,
    WorkspaceMembership,
)


def load_active_permissions(
    session: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    membership_id: UUID,
) -> set[str]:
    """Resolve permission keys from active membership assignments and active roles."""
    statement = (
        select(Permission.key)
        .select_from(MembershipRoleAssignment)
        .join(
            WorkspaceMembership,
            and_(
                WorkspaceMembership.id == MembershipRoleAssignment.membership_id,
                WorkspaceMembership.organization_id == MembershipRoleAssignment.organization_id,
                WorkspaceMembership.workspace_id == MembershipRoleAssignment.workspace_id,
            ),
        )
        .join(
            Role,
            and_(
                Role.id == MembershipRoleAssignment.role_id,
                Role.organization_id == MembershipRoleAssignment.organization_id,
            ),
        )
        .join(
            RolePermission,
            and_(
                RolePermission.role_id == Role.id,
                RolePermission.organization_id == Role.organization_id,
            ),
        )
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(
            MembershipRoleAssignment.membership_id == membership_id,
            MembershipRoleAssignment.organization_id == organization_id,
            MembershipRoleAssignment.workspace_id == workspace_id,
            MembershipRoleAssignment.revoked_at.is_(None),
            WorkspaceMembership.status == "active",
            Role.status == "active",
        )
    )
    return set(session.scalars(statement))
