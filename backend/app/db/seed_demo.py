"""Idempotently provision synthetic Apex demo data in development databases."""

from __future__ import annotations

from datetime import date
import json
import os
from typing import Callable
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


ORGANIZATION_SLUG = "apex-financial"
WORKSPACE_SLUG = "marketing-content"
DEFAULT_USER_EMAIL = "dev-user@apex.com"


class DevelopmentEnvironmentRequired(RuntimeError):
    """Raised if the synthetic seed is invoked outside explicit development mode."""


def _stable_id(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"verityai:demo-seed:v1:{name}")


def _require_development() -> None:
    if os.environ.get("APP_ENV", "").strip().lower() != "development":
        raise DevelopmentEnvironmentRequired(
            "Refusing to seed demo data: set APP_ENV=development in this process."
        )


def seed_development_data(
    session_factory: Callable[[], Session] | sessionmaker[Session] | None = None,
) -> dict[str, str]:
    """Create or reuse the Apex organization, workspace, grants, policies, and evidence."""
    _require_development()
    if session_factory is None:
        from app.db.session import get_session_factory

        session_factory = get_session_factory()

    from app.models import (
        EvidenceRecord,
        EvidenceVersion,
        MembershipRoleAssignment,
        Organization,
        Permission,
        Policy,
        PolicyVersion,
        Role,
        RolePermission,
        User,
        Workspace,
        WorkspaceMembership,
    )

    with session_factory() as session:
        with session.begin():
            organization = session.scalar(
                select(Organization).where(Organization.slug == ORGANIZATION_SLUG)
            )
            if organization is None:
                organization = Organization(
                    id=_stable_id("organization"),
                    name="Apex Financial Services",
                    slug=ORGANIZATION_SLUG,
                )
                session.add(organization)
                session.flush()
            elif organization.name != "Apex Financial Services" or organization.status != "active":
                raise RuntimeError("The Apex organization slug is already used by different data.")

            workspace = session.scalar(
                select(Workspace).where(
                    Workspace.organization_id == organization.id,
                    Workspace.slug == WORKSPACE_SLUG,
                )
            )
            if workspace is None:
                workspace = Workspace(
                    id=_stable_id("workspace"),
                    organization_id=organization.id,
                    name="Marketing Content Review",
                    slug=WORKSPACE_SLUG,
                )
                session.add(workspace)
                session.flush()
            elif workspace.name != "Marketing Content Review" or workspace.status != "active":
                raise RuntimeError("The Apex workspace slug is already used by different data.")

            user = session.scalar(
                select(User).where(User.display_name == DEFAULT_USER_EMAIL).order_by(User.id).limit(1)
            )
            if user is None:
                user = User(
                    id=_stable_id("default-user"),
                    display_name=DEFAULT_USER_EMAIL,
                )
                session.add(user)
                session.flush()

            membership = session.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.organization_id == organization.id,
                    WorkspaceMembership.workspace_id == workspace.id,
                    WorkspaceMembership.user_id == user.id,
                )
            )
            if membership is None:
                membership = WorkspaceMembership(
                    id=_stable_id("default-membership"),
                    organization_id=organization.id,
                    workspace_id=workspace.id,
                    user_id=user.id,
                    status="active",
                )
                session.add(membership)
                session.flush()
            elif membership.status != "active":
                raise RuntimeError("The existing Apex development membership is not active.")

            permission_descriptions = {
                "submission.create": "Create workspace submissions",
                "submission.read.workspace": "Read workspace submissions and analysis",
                "review.decide": "Record workspace review decisions",
                "insight.read": "Read workspace governance insights",
                "evidence.read.workspace": "Read workspace evidence",
                "evidence.manage": "Upload and manage workspace evidence",
                "policy.read.workspace": "Read workspace policies",
            }
            permissions: dict[str, Permission] = {}
            for key, description in permission_descriptions.items():
                permission = session.scalar(select(Permission).where(Permission.key == key))
                if permission is None:
                    permission = Permission(key=key, description=description)
                    session.add(permission)
                    session.flush()
                permissions[key] = permission

            role_specs = {
                "creator": {
                    "name": "Creator",
                    "permissions": ("submission.create", "submission.read.workspace"),
                },
                "compliance_reviewer": {
                    "name": "Compliance Reviewer",
                    "permissions": (
                        "submission.read.workspace",
                        "review.decide",
                        "insight.read",
                        "evidence.read.workspace",
                        "evidence.manage",
                        "policy.read.workspace",
                    ),
                },
            }
            roles: dict[str, Role] = {}
            for role_key, specification in role_specs.items():
                role = session.scalar(
                    select(Role).where(
                        Role.organization_id == organization.id,
                        Role.key == role_key,
                    )
                )
                if role is None:
                    role = Role(
                        id=_stable_id(f"role:{role_key}"),
                        organization_id=organization.id,
                        key=role_key,
                        display_name=specification["name"],
                        is_predefined=True,
                        status="active",
                    )
                    session.add(role)
                    session.flush()
                elif role.status != "active":
                    raise RuntimeError(f"The Apex {role_key} role is not active.")
                roles[role_key] = role

                for permission_key in specification["permissions"]:
                    permission = permissions[permission_key]
                    role_permission = session.scalar(
                        select(RolePermission).where(
                            RolePermission.organization_id == organization.id,
                            RolePermission.role_id == role.id,
                            RolePermission.permission_id == permission.id,
                        )
                    )
                    if role_permission is None:
                        session.add(
                            RolePermission(
                                id=_stable_id(f"role-permission:{role_key}:{permission_key}"),
                                organization_id=organization.id,
                                role_id=role.id,
                                permission_id=permission.id,
                                assigned_by_membership_id=membership.id,
                            )
                        )
                assignment = session.scalar(
                    select(MembershipRoleAssignment).where(
                        MembershipRoleAssignment.organization_id == organization.id,
                        MembershipRoleAssignment.workspace_id == workspace.id,
                        MembershipRoleAssignment.membership_id == membership.id,
                        MembershipRoleAssignment.role_id == role.id,
                        MembershipRoleAssignment.revoked_at.is_(None),
                    )
                )
                if assignment is None:
                    session.add(
                        MembershipRoleAssignment(
                            id=_stable_id(f"membership-role:{role_key}"),
                            organization_id=organization.id,
                            workspace_id=workspace.id,
                            membership_id=membership.id,
                            role_id=role.id,
                            assigned_by_membership_id=membership.id,
                        )
                    )

            policy_specs = (
                {
                    "key": "yield-apy-guidance",
                    "name": "Yield & APY Promotional Guidance",
                    "category": "yield-and-apy",
                    "rule_text": "Do not describe yield or APY as guaranteed.",
                    "term": "guaranteed",
                },
                {
                    "key": "zero-fee-standard",
                    "name": "Zero-Fee Claims Standard",
                    "category": "fees",
                    "rule_text": "Do not claim an account has zero fees without qualification.",
                    "term": "zero fees",
                },
            )
            policy_ids: dict[str, UUID] = {}
            for spec in policy_specs:
                policy = session.scalar(
                    select(Policy).where(
                        Policy.organization_id == organization.id,
                        Policy.workspace_id == workspace.id,
                        Policy.name == spec["name"],
                    )
                )
                if policy is None:
                    policy = Policy(
                        id=_stable_id(f"policy:{spec['key']}"),
                        organization_id=organization.id,
                        workspace_id=workspace.id,
                        name=spec["name"],
                        category=spec["category"],
                        status="Active",
                        created_by_membership_id=membership.id,
                        updated_by_membership_id=membership.id,
                    )
                    session.add(policy)
                    session.flush()
                elif policy.status != "Active":
                    raise RuntimeError(f"The seeded policy {spec['name']} is not active.")

                policy_version = session.scalar(
                    select(PolicyVersion).where(
                        PolicyVersion.policy_id == policy.id,
                        PolicyVersion.version_number == 1,
                    )
                )
                if policy_version is None:
                    policy_version = PolicyVersion(
                        id=_stable_id(f"policy-version:{spec['key']}:1"),
                        organization_id=organization.id,
                        workspace_id=workspace.id,
                        policy_id=policy.id,
                        version_number=1,
                        rule_text=spec["rule_text"],
                        rule_type="prohibited_term",
                        configuration={"term": spec["term"]},
                        status_snapshot="Active",
                        created_by_membership_id=membership.id,
                    )
                    session.add(policy_version)
                    session.flush()
                if policy.current_version_id is None:
                    policy.current_version_id = policy_version.id
                elif policy.current_version_id != policy_version.id:
                    raise RuntimeError(f"The seeded policy {spec['name']} has a different current version.")
                policy_ids[spec["key"]] = policy.id

            evidence_specs = (
                {
                    "key": "rate-schedule-2026",
                    "title": "2026 Deposit Interest Rate Schedule",
                    "valid_from": date(2026, 1, 1),
                    "valid_until": date(2026, 12, 31),
                },
                {
                    "key": "legacy-fee-schedule-2024",
                    "title": "Legacy Fee Schedule 2024",
                    "valid_from": date(2024, 1, 1),
                    "valid_until": date(2024, 12, 31),
                },
            )
            evidence_ids: dict[str, UUID] = {}
            for spec in evidence_specs:
                record_id = _stable_id(f"evidence-record:{spec['key']}")
                record = session.get(EvidenceRecord, record_id)
                if record is None:
                    record = EvidenceRecord(
                        id=record_id,
                        organization_id=organization.id,
                        workspace_id=workspace.id,
                        owner_membership_id=membership.id,
                        primary_lifecycle_state="Approved",
                        is_inactive=False,
                    )
                    session.add(record)
                    session.flush()
                version_id = _stable_id(f"evidence-version:{spec['key']}:1")
                version = session.get(EvidenceVersion, version_id)
                if version is None:
                    version = EvidenceVersion(
                        id=version_id,
                        organization_id=organization.id,
                        workspace_id=workspace.id,
                        evidence_record_id=record.id,
                        version_number=1,
                        title=spec["title"],
                        source_reference=f"synthetic:apex-demo/{spec['key']}",
                        valid_from=spec["valid_from"],
                        valid_until=spec["valid_until"],
                        owner_snapshot="Apex Financial Services",
                        created_by_membership_id=membership.id,
                        pending_reapproval=False,
                    )
                    session.add(version)
                    session.flush()
                elif (
                    version.evidence_record_id != record.id
                    or version.title != spec["title"]
                    or version.valid_from != spec["valid_from"]
                    or version.valid_until != spec["valid_until"]
                ):
                    raise RuntimeError(f"The seeded evidence version {spec['title']} does not match its seed definition.")
                if record.current_version_id is None:
                    record.current_version_id = version.id
                elif record.current_version_id != version.id:
                    raise RuntimeError(f"The seeded evidence record {spec['title']} has a different current version.")
                evidence_ids[spec["key"]] = record.id

            result = {
                "organization_id": str(organization.id),
                "workspace_id": str(workspace.id),
                "user_id": str(user.id),
                "membership_id": str(membership.id),
                "creator_role_id": str(roles["creator"].id),
                "compliance_reviewer_role_id": str(roles["compliance_reviewer"].id),
                "yield_policy_id": str(policy_ids["yield-apy-guidance"]),
                "zero_fee_policy_id": str(policy_ids["zero-fee-standard"]),
                "rate_schedule_evidence_id": str(evidence_ids["rate-schedule-2026"]),
                "legacy_fee_evidence_id": str(evidence_ids["legacy-fee-schedule-2024"]),
            }
    return result


def main() -> None:
    try:
        result = seed_development_data()
    except Exception as exc:
        raise SystemExit(
            f"Demo seed failed; its transaction was rolled back ({type(exc).__name__})."
        ) from None
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
