"""SQLAlchemy relational model for the Milestone 2 data foundation.

This module defines persistence structure only. It does not implement
authentication or feature workflows.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    select,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, object_session, relationship

from app.db.base import Base


def uuid_column() -> Mapped[UUID]:
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)


def timestamp_column() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[UUID] = uuid_column()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="active")
    created_at: Mapped[datetime] = timestamp_column()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_workspaces_id_org"),
        UniqueConstraint("organization_id", "slug", name="uq_workspaces_org_slug"),
        ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="active")
    created_at: Mapped[datetime] = timestamp_column()


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = uuid_column()
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = timestamp_column()
    # Login identifiers and credentials are deliberately outside this milestone.


class WorkspaceMembership(Base):
    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", "workspace_id", name="uq_memberships_id_tenant"),
        UniqueConstraint("id", "organization_id", name="uq_memberships_id_org"),
        UniqueConstraint("id", "user_id", "organization_id", "workspace_id", name="uq_memberships_user_tenant_ref"),
        UniqueConstraint("organization_id", "workspace_id", "user_id", name="uq_memberships_scope_user"),
        ForeignKeyConstraint(
            ["workspace_id", "organization_id"],
            ["workspaces.id", "workspaces.organization_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="active")
    created_at: Mapped[datetime] = timestamp_column()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_roles_id_org"),
        UniqueConstraint("organization_id", "key", name="uq_roles_org_key"),
        ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_predefined: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="active")
    created_at: Mapped[datetime] = timestamp_column()


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[UUID] = uuid_column()
    key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(String(300), nullable=False)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permissions_pair"),
        ForeignKeyConstraint(
            ["role_id", "organization_id"],
            ["roles.id", "roles.organization_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["assigned_by_membership_id", "organization_id"],
                             ["workspace_memberships.id", "workspace_memberships.organization_id"], ondelete="RESTRICT"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    role_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    permission_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    assigned_by_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = timestamp_column()


class MembershipRoleAssignment(Base):
    __tablename__ = "membership_role_assignments"
    __table_args__ = (
        ForeignKeyConstraint(["membership_id", "organization_id", "workspace_id"],
                             ["workspace_memberships.id", "workspace_memberships.organization_id", "workspace_memberships.workspace_id"],
                             ondelete="RESTRICT"),
        ForeignKeyConstraint(["role_id", "organization_id"], ["roles.id", "roles.organization_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["assigned_by_membership_id", "organization_id", "workspace_id"],
                             ["workspace_memberships.id", "workspace_memberships.organization_id", "workspace_memberships.workspace_id"],
                             ondelete="RESTRICT"),
        ForeignKeyConstraint(["workspace_id", "organization_id"],
                             ["workspaces.id", "workspaces.organization_id"], ondelete="RESTRICT"),
        Index("uq_membership_role_active", "membership_id", "role_id", unique=True,
              postgresql_where=text("revoked_at IS NULL")),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    role_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    assigned_by_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    assigned_at: Mapped[datetime] = timestamp_column()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvidenceRecord(Base):
    __tablename__ = "evidence_records"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", "workspace_id", name="uq_evidence_records_id_tenant"),
        UniqueConstraint("id", "organization_id", "workspace_id", "current_version_id",
                         name="uq_evidence_records_current_ref"),
        ForeignKeyConstraint(["workspace_id", "organization_id"],
                             ["workspaces.id", "workspaces.organization_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["owner_membership_id", "organization_id", "workspace_id"],
                             ["workspace_memberships.id", "workspace_memberships.organization_id", "workspace_memberships.workspace_id"],
                             ondelete="RESTRICT"),
        ForeignKeyConstraint(["current_version_id", "id", "organization_id", "workspace_id"],
                             ["evidence_versions.id", "evidence_versions.evidence_record_id", "evidence_versions.organization_id", "evidence_versions.workspace_id"],
                             name="fk_evidence_records_current_version", use_alter=True, ondelete="RESTRICT"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    owner_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    current_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    primary_lifecycle_state: Mapped[str] = mapped_column(String(30), nullable=False, server_default="Uploaded")
    is_inactive: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = timestamp_column()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class EvidenceVersion(Base):
    __tablename__ = "evidence_versions"
    __table_args__ = (
        UniqueConstraint("id", "evidence_record_id", "organization_id", "workspace_id",
                         name="uq_evidence_versions_record_ref"),
        UniqueConstraint("evidence_record_id", "version_number", name="uq_evidence_versions_number"),
        ForeignKeyConstraint(["evidence_record_id", "organization_id", "workspace_id"],
                             ["evidence_records.id", "evidence_records.organization_id", "evidence_records.workspace_id"],
                             ondelete="RESTRICT"),
        ForeignKeyConstraint(["created_by_membership_id", "organization_id", "workspace_id"],
                             ["workspace_memberships.id", "workspace_memberships.organization_id", "workspace_memberships.workspace_id"],
                             ondelete="RESTRICT"),
        CheckConstraint("version_number > 0", name="positive_version_number"),
        Index("ix_evidence_versions_tenant_created", "organization_id", "workspace_id", "created_at"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    evidence_record_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(Text)
    private_file_key: Mapped[str | None] = mapped_column(String(500))
    extracted_text: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    owner_snapshot: Mapped[str | None] = mapped_column(String(300))
    created_by_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    pending_reapproval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    checksum: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = timestamp_column()
    conflict_sources: Mapped[list[EvidenceConflictSource]] = relationship(
        back_populates="evidence_version", overlaps="conflict,sources"
    )

    @property
    def has_open_manual_conflict(self) -> bool:
        return any(source.conflict.state == "open" for source in self.conflict_sources)

    @property
    def is_pending_reapproval(self) -> bool:
        """Derive the exact-version gate from append-only approval events.

        ``pending_reapproval`` is an immutable version-time marker. Clearing a
        gate is represented by a later ``version_reapproved`` event rather than
        updating the evidence-version row.
        """
        if not self.pending_reapproval:
            return False
        session = object_session(self)
        if session is None:
            return True
        cleared = session.scalar(
            select(EvidenceStateEvent.id)
            .where(
                EvidenceStateEvent.evidence_version_id == self.id,
                EvidenceStateEvent.evidence_record_id == self.evidence_record_id,
                EvidenceStateEvent.organization_id == self.organization_id,
                EvidenceStateEvent.workspace_id == self.workspace_id,
                EvidenceStateEvent.event_type == "version_reapproved",
            )
            .limit(1)
        )
        return cleared is None


class EvidenceConflict(Base):
    __tablename__ = "evidence_conflicts"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", "workspace_id", name="uq_evidence_conflicts_id_tenant"),
        ForeignKeyConstraint(["workspace_id", "organization_id"], ["workspaces.id", "workspaces.organization_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["reported_by_membership_id", "organization_id", "workspace_id"],
                             ["workspace_memberships.id", "workspace_memberships.organization_id", "workspace_memberships.workspace_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["resolved_by_membership_id", "organization_id", "workspace_id"],
                             ["workspace_memberships.id", "workspace_memberships.organization_id", "workspace_memberships.workspace_id"], ondelete="RESTRICT"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reported_by_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(30), nullable=False, server_default="open")
    resolved_by_membership_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    resolution_rationale: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = timestamp_column()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sources: Mapped[list[EvidenceConflictSource]] = relationship(
        back_populates="conflict", overlaps="evidence_version,conflict_sources"
    )


class EvidenceConflictSource(Base):
    __tablename__ = "evidence_conflict_sources"
    __table_args__ = (
        UniqueConstraint("conflict_id", "evidence_version_id", name="uq_evidence_conflict_sources_pair"),
        ForeignKeyConstraint(["conflict_id", "organization_id", "workspace_id"],
                             ["evidence_conflicts.id", "evidence_conflicts.organization_id", "evidence_conflicts.workspace_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["evidence_version_id", "evidence_record_id", "organization_id", "workspace_id"],
                             ["evidence_versions.id", "evidence_versions.evidence_record_id", "evidence_versions.organization_id", "evidence_versions.workspace_id"], ondelete="RESTRICT"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    conflict_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    evidence_record_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    evidence_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    evidence_version: Mapped[EvidenceVersion] = relationship(
        back_populates="conflict_sources", overlaps="conflict,sources"
    )
    conflict: Mapped[EvidenceConflict] = relationship(
        back_populates="sources", overlaps="evidence_version,conflict_sources"
    )


class EvidenceStateEvent(Base):
    __tablename__ = "evidence_state_events"
    __table_args__ = (
        ForeignKeyConstraint(["evidence_record_id", "organization_id", "workspace_id"],
                             ["evidence_records.id", "evidence_records.organization_id", "evidence_records.workspace_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["evidence_version_id", "evidence_record_id", "organization_id", "workspace_id"],
                             ["evidence_versions.id", "evidence_versions.evidence_record_id", "evidence_versions.organization_id", "evidence_versions.workspace_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["actor_membership_id", "organization_id", "workspace_id"],
                             ["workspace_memberships.id", "workspace_memberships.organization_id", "workspace_memberships.workspace_id"], ondelete="RESTRICT"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    evidence_record_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    evidence_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    actor_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = timestamp_column()


class Policy(Base):
    __tablename__ = "policies"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", "workspace_id", name="uq_policies_id_tenant"),
        UniqueConstraint("id", "organization_id", "workspace_id", "current_version_id", name="uq_policies_current_ref"),
        ForeignKeyConstraint(["workspace_id", "organization_id"], ["workspaces.id", "workspaces.organization_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["created_by_membership_id", "organization_id", "workspace_id"],
                             ["workspace_memberships.id", "workspace_memberships.organization_id", "workspace_memberships.workspace_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["current_version_id", "id", "organization_id", "workspace_id"],
                             ["policy_versions.id", "policy_versions.policy_id", "policy_versions.organization_id", "policy_versions.workspace_id"],
                             name="fk_policies_current_version", use_alter=True, ondelete="RESTRICT"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="Draft")
    current_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_by_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    updated_by_membership_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = timestamp_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class PolicyVersion(Base):
    __tablename__ = "policy_versions"
    __table_args__ = (
        UniqueConstraint("id", "policy_id", "organization_id", "workspace_id", name="uq_policy_versions_policy_ref"),
        UniqueConstraint("policy_id", "version_number", name="uq_policy_versions_number"),
        ForeignKeyConstraint(["policy_id", "organization_id", "workspace_id"],
                             ["policies.id", "policies.organization_id", "policies.workspace_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["created_by_membership_id", "organization_id", "workspace_id"],
                             ["workspace_memberships.id", "workspace_memberships.organization_id", "workspace_memberships.workspace_id"], ondelete="RESTRICT"),
        CheckConstraint("version_number > 0", name="positive_version_number"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_text: Mapped[str] = mapped_column(Text, nullable=False)
    rule_type: Mapped[str] = mapped_column(String(80), nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status_snapshot: Mapped[str] = mapped_column(String(30), nullable=False)
    created_by_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = timestamp_column()


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        CheckConstraint(
            "current_status IN ('Draft', 'Submitted', 'Analysis blocked', 'In review', "
            "'Changes requested', 'Approved', 'Approved with documented exceptions', 'Rejected')",
            name="valid_current_status",
        ),
        UniqueConstraint("id", "organization_id", "workspace_id", name="uq_submissions_id_tenant"),
        ForeignKeyConstraint(["workspace_id", "organization_id"], ["workspaces.id", "workspaces.organization_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["created_by_membership_id", "organization_id", "workspace_id"],
                             ["workspace_memberships.id", "workspace_memberships.organization_id", "workspace_memberships.workspace_id"], ondelete="RESTRICT"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_by_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    current_status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="Draft")
    created_at: Mapped[datetime] = timestamp_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class SubmissionVersion(Base):
    __tablename__ = "submission_versions"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", "workspace_id", name="uq_submission_versions_id_tenant"),
        UniqueConstraint("id", "submission_id", "organization_id", "workspace_id", name="uq_submission_versions_parent_ref"),
        UniqueConstraint("submission_id", "version_number", name="uq_submission_versions_number"),
        ForeignKeyConstraint(["submission_id", "organization_id", "workspace_id"],
                             ["submissions.id", "submissions.organization_id", "submissions.workspace_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["submitter_membership_id", "organization_id", "workspace_id"],
                             ["workspace_memberships.id", "workspace_memberships.organization_id", "workspace_memberships.workspace_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["prior_version_id", "submission_id", "organization_id", "workspace_id"],
                             ["submission_versions.id", "submission_versions.submission_id", "submission_versions.organization_id", "submission_versions.workspace_id"], ondelete="RESTRICT"),
        CheckConstraint("version_number > 0", name="positive_version_number"),
        CheckConstraint("source_type IN ('text', 'pdf', 'docx')", name="valid_source_type"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    submission_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    submitted_text: Mapped[str | None] = mapped_column(Text)
    original_file_key: Mapped[str | None] = mapped_column(String(500))
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    submitter_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    submitted_at: Mapped[datetime] = timestamp_column()
    prior_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        CheckConstraint("overall_state IN ('Running', 'Succeeded', 'Incomplete')", name="valid_overall_state"),
        UniqueConstraint("id", "organization_id", "workspace_id", name="uq_analysis_runs_id_tenant"),
        UniqueConstraint("id", "submission_version_id", "organization_id", "workspace_id", name="uq_analysis_runs_version_ref"),
        UniqueConstraint("submission_version_id", "run_number", name="uq_analysis_runs_number"),
        ForeignKeyConstraint(["submission_version_id", "organization_id", "workspace_id"],
                             ["submission_versions.id", "submission_versions.organization_id", "submission_versions.workspace_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["triggered_by_membership_id", "organization_id", "workspace_id"],
                             ["workspace_memberships.id", "workspace_memberships.organization_id", "workspace_memberships.workspace_id"], ondelete="RESTRICT"),
        CheckConstraint("run_number > 0", name="positive_run_number"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    submission_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    overall_state: Mapped[str] = mapped_column(String(30), nullable=False, server_default="Running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    triggered_by_membership_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    configuration_reference: Mapped[str | None] = mapped_column(String(200))


class AnalysisStageResult(Base):
    __tablename__ = "analysis_stage_results"
    __table_args__ = (
        CheckConstraint(
            "state IN ('Not started', 'Running', 'Succeeded', 'Failed', 'Not run')",
            name="valid_stage_state",
        ),
        UniqueConstraint("id", "organization_id", "workspace_id", name="uq_stage_results_id_tenant"),
        UniqueConstraint("analysis_run_id", "stage_key", "attempt_number", name="uq_stage_results_attempt"),
        ForeignKeyConstraint(["analysis_run_id", "organization_id", "workspace_id"],
                             ["analysis_runs.id", "analysis_runs.organization_id", "analysis_runs.workspace_id"], ondelete="RESTRICT"),
        CheckConstraint("attempt_number > 0", name="positive_attempt_number"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    analysis_run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    stage_key: Mapped[str] = mapped_column(String(80), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False, server_default="Not started")
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_reference: Mapped[str | None] = mapped_column(Text)
    output_reference: Mapped[str | None] = mapped_column(Text)
    safe_error_code: Mapped[str | None] = mapped_column(String(100))
    safe_error_message: Mapped[str | None] = mapped_column(String(500))
    error_message: Mapped[str | None] = mapped_column(String(500))
    dependency_reason: Mapped[str | None] = mapped_column(Text)


class SubmissionVersionArtifact(Base):
    __tablename__ = "submission_version_artifacts"
    __table_args__ = (
        ForeignKeyConstraint(["submission_version_id", "organization_id", "workspace_id"],
                             ["submission_versions.id", "submission_versions.organization_id", "submission_versions.workspace_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["analysis_run_id", "submission_version_id", "organization_id", "workspace_id"],
                             ["analysis_runs.id", "analysis_runs.submission_version_id", "analysis_runs.organization_id", "analysis_runs.workspace_id"], ondelete="RESTRICT"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    submission_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    analysis_run_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    artifact_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    private_file_key: Mapped[str | None] = mapped_column(String(500))
    normalized_text: Mapped[str | None] = mapped_column(Text)
    checksum: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = timestamp_column()


class ExtractedClaim(Base):
    __tablename__ = "extracted_claims"
    __table_args__ = (
        CheckConstraint("candidate_kind IN ('factual', 'promotional')", name="valid_candidate_kind"),
        CheckConstraint("start_offset >= 0 AND end_offset > start_offset", name="valid_claim_offsets"),
        UniqueConstraint("id", "analysis_run_id", "submission_version_id", "organization_id", "workspace_id", name="uq_claims_run_ref"),
        ForeignKeyConstraint(["analysis_run_id", "submission_version_id", "organization_id", "workspace_id"],
                             ["analysis_runs.id", "analysis_runs.submission_version_id", "analysis_runs.organization_id", "analysis_runs.workspace_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["stage_result_id", "organization_id", "workspace_id"],
                             ["analysis_stage_results.id", "analysis_stage_results.organization_id", "analysis_stage_results.workspace_id"], ondelete="RESTRICT"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    analysis_run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    submission_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    text_span: Mapped[str] = mapped_column(Text, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    stage_result_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))


class EvidenceMatchCandidate(Base):
    __tablename__ = "evidence_match_candidates"
    __table_args__ = (
        UniqueConstraint("claim_id", "evidence_version_id", "analysis_run_id", name="uq_match_candidate_once"),
        ForeignKeyConstraint(["claim_id", "analysis_run_id", "submission_version_id", "organization_id", "workspace_id"],
                             ["extracted_claims.id", "extracted_claims.analysis_run_id", "extracted_claims.submission_version_id", "extracted_claims.organization_id", "extracted_claims.workspace_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["evidence_version_id", "evidence_record_id", "organization_id", "workspace_id"],
                             ["evidence_versions.id", "evidence_versions.evidence_record_id", "evidence_versions.organization_id", "evidence_versions.workspace_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["analysis_run_id", "submission_version_id", "organization_id", "workspace_id"],
                             ["analysis_runs.id", "analysis_runs.submission_version_id", "analysis_runs.organization_id", "analysis_runs.workspace_id"], ondelete="RESTRICT"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    analysis_run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    submission_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    claim_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    evidence_record_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    evidence_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    eligibility_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    match_explanation: Mapped[str | None] = mapped_column(Text)
    candidate_ordering: Mapped[int | None] = mapped_column(Integer)


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint("id", "analysis_run_id", "submission_version_id", "organization_id", "workspace_id", name="uq_findings_run_ref"),
        ForeignKeyConstraint(["analysis_run_id", "submission_version_id", "organization_id", "workspace_id"],
                             ["analysis_runs.id", "analysis_runs.submission_version_id", "analysis_runs.organization_id", "analysis_runs.workspace_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["claim_id", "analysis_run_id", "submission_version_id", "organization_id", "workspace_id"],
                             ["extracted_claims.id", "extracted_claims.analysis_run_id", "extracted_claims.submission_version_id", "extracted_claims.organization_id", "extracted_claims.workspace_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["evidence_version_id", "evidence_record_id", "organization_id", "workspace_id"],
                             ["evidence_versions.id", "evidence_versions.evidence_record_id", "evidence_versions.organization_id", "evidence_versions.workspace_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["policy_version_id", "policy_id", "organization_id", "workspace_id"],
                             ["policy_versions.id", "policy_versions.policy_id", "policy_versions.organization_id", "policy_versions.workspace_id"], ondelete="RESTRICT"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    analysis_run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    submission_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    claim_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    attention_label: Mapped[str | None] = mapped_column(String(80))
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    policy_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    policy_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    evidence_record_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    evidence_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    is_unresolved: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = timestamp_column()


class GeneratedSuggestion(Base):
    __tablename__ = "generated_suggestions"

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    finding_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    analysis_run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    submission_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    proposed_text: Mapped[str] = mapped_column(Text, nullable=False)
    is_suggestion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    origin_identifier: Mapped[str | None] = mapped_column(String(200))
    generated_at: Mapped[datetime] = timestamp_column()
    __table_args__ = (
        ForeignKeyConstraint(["finding_id", "analysis_run_id", "submission_version_id", "organization_id", "workspace_id"],
                             ["findings.id", "findings.analysis_run_id", "findings.submission_version_id", "findings.organization_id", "findings.workspace_id"], ondelete="RESTRICT"),
    )


class HumanDisposition(Base):
    __tablename__ = "human_dispositions"
    __table_args__ = (
        UniqueConstraint("finding_id", "sequence_number", name="uq_human_dispositions_finding_sequence"),
        CheckConstraint("length(trim(rationale)) > 0", name="nonempty_rationale"),
        ForeignKeyConstraint(["finding_id", "analysis_run_id", "submission_version_id", "organization_id", "workspace_id"],
                             ["findings.id", "findings.analysis_run_id", "findings.submission_version_id", "findings.organization_id", "findings.workspace_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["reviewer_membership_id", "organization_id", "workspace_id"],
                             ["workspace_memberships.id", "workspace_memberships.organization_id", "workspace_memberships.workspace_id"], ondelete="RESTRICT"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    finding_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    analysis_run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    submission_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reviewer_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    disposition: Mapped[str] = mapped_column(String(100), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = timestamp_column()


class ReviewDecision(Base):
    __tablename__ = "review_decisions"
    __table_args__ = (
        CheckConstraint(
            "decision = 'Approved' OR (rationale IS NOT NULL AND length(trim(rationale)) > 0)",
            name="required_rationale_unless_clean_approval",
        ),
        ForeignKeyConstraint(["submission_version_id", "organization_id", "workspace_id"],
                             ["submission_versions.id", "submission_versions.organization_id", "submission_versions.workspace_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["reviewer_membership_id", "organization_id", "workspace_id"],
                             ["workspace_memberships.id", "workspace_memberships.organization_id", "workspace_memberships.workspace_id"], ondelete="RESTRICT"),
        CheckConstraint("decision IN ('Approved', 'Approved with documented exceptions', 'Rejected', 'Changes requested')", name="valid_decision"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    submission_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reviewer_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = timestamp_column()


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        ForeignKeyConstraint(["workspace_id", "organization_id"], ["workspaces.id", "workspaces.organization_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["actor_membership_id", "organization_id", "workspace_id"],
                             ["workspace_memberships.id", "workspace_memberships.organization_id", "workspace_memberships.workspace_id"], ondelete="RESTRICT"),
        Index("ix_audit_events_tenant_time", "organization_id", "workspace_id", "created_at"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    action_key: Mapped[str] = mapped_column(String(120), nullable=False)
    target_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    safe_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = timestamp_column()


class Report(Base):
    """Immutable report snapshot tied to one exact submission version and run."""

    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", "workspace_id", name="uq_reports_id_tenant"),
        UniqueConstraint(
            "id", "submission_version_id", "analysis_run_id", "organization_id", "workspace_id",
            name="uq_reports_analysis_ref",
        ),
        UniqueConstraint(
            "submission_version_id", "analysis_run_id", name="uq_reports_version_analysis_run"
        ),
        ForeignKeyConstraint(
            ["submission_version_id", "organization_id", "workspace_id"],
            ["submission_versions.id", "submission_versions.organization_id", "submission_versions.workspace_id"],
            name="fk_report_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["analysis_run_id", "submission_version_id", "organization_id", "workspace_id"],
            ["analysis_runs.id", "analysis_runs.submission_version_id", "analysis_runs.organization_id", "analysis_runs.workspace_id"],
            name="fk_report_analysis_run",
            ondelete="RESTRICT",
        ),
        CheckConstraint("report_version > 0", name="positive_report_version"),
        Index("ix_reports_tenant_generated", "organization_id", "workspace_id", "generated_at"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    submission_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    analysis_run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    report_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    content_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    generated_at: Mapped[datetime] = timestamp_column()
    created_at: Mapped[datetime] = timestamp_column()


class ReportNarrativeArtifact(Base):
    """Idempotent Gemini narrative and private PDF associated with one snapshot."""

    __tablename__ = "report_narrative_artifacts"
    __table_args__ = (
        UniqueConstraint("report_id", name="uq_report_narrative_artifacts_report"),
        ForeignKeyConstraint(
            ["report_id", "organization_id", "workspace_id"],
            ["reports.id", "reports.organization_id", "reports.workspace_id"],
            name="fk_report_narrative_artifact_report",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('pending', 'generating', 'completed', 'failed')",
            name="valid_status",
        ),
        CheckConstraint("report_version > 0", name="positive_report_version"),
        CheckConstraint("generation_attempts >= 0", name="nonnegative_generation_attempts"),
        CheckConstraint(
            "status != 'completed' OR (content IS NOT NULL AND pdf_storage_key IS NOT NULL AND generated_at IS NOT NULL)",
            name="completed_artifact_has_report_and_pdf",
        ),
        Index("ix_report_narrative_artifacts_tenant_status", "organization_id", "workspace_id", "status"),
    )

    id: Mapped[UUID] = uuid_column()
    report_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    report_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    content: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    pdf_storage_key: Mapped[str | None] = mapped_column(String(64))
    generation_error: Mapped[str | None] = mapped_column(String(500))
    generation_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = timestamp_column()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PaymentTransaction(Base):
    """One server-priced PayPal Sandbox purchase attempt for a report."""

    __tablename__ = "payment_transactions"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", "workspace_id", name="uq_payment_transactions_id_tenant"),
        UniqueConstraint(
            "id", "report_id", "organization_id", "workspace_id", "purchaser_user_id",
            name="uq_payment_transactions_entitlement_ref",
        ),
        UniqueConstraint("paypal_order_id", name="uq_payment_transactions_paypal_order"),
        UniqueConstraint("paypal_capture_id", name="uq_payment_transactions_paypal_capture"),
        UniqueConstraint(
            "organization_id", "workspace_id", "purchaser_user_id", "idempotency_key",
            name="uq_payment_transactions_idempotency",
        ),
        ForeignKeyConstraint(
            ["report_id", "organization_id", "workspace_id"],
            ["reports.id", "reports.organization_id", "reports.workspace_id"],
            name="fk_pay_tx_report",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["purchaser_membership_id", "purchaser_user_id", "organization_id", "workspace_id"],
            ["workspace_memberships.id", "workspace_memberships.user_id", "workspace_memberships.organization_id", "workspace_memberships.workspace_id"],
            name="fk_pay_tx_purchaser_membership",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["purchaser_user_id"], ["users.id"], name="fk_pay_tx_purchaser_user", ondelete="RESTRICT"
        ),
        CheckConstraint("provider = 'paypal_sandbox'", name="valid_provider"),
        CheckConstraint("status IN ('pending', 'provider_approved', 'capture_verified', 'failed', 'cancelled')", name="valid_status"),
        CheckConstraint("expected_amount > 0", name="positive_expected_amount"),
        CheckConstraint("currency = 'USD'", name="supported_currency"),
        CheckConstraint(
            "status != 'capture_verified' OR (paypal_order_id IS NOT NULL AND paypal_capture_id IS NOT NULL AND captured_at IS NOT NULL AND verified_at IS NOT NULL)",
            name="verified_capture_has_provider_reference",
        ),
        Index(
            "uq_payment_transactions_active_report_user",
            "report_id", "purchaser_user_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'provider_approved')"),
        ),
        Index("ix_payment_transactions_tenant_report", "organization_id", "workspace_id", "report_id"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    report_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    purchaser_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    purchaser_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, server_default="paypal_sandbox")
    paypal_order_id: Mapped[str | None] = mapped_column(String(128))
    paypal_capture_id: Mapped[str | None] = mapped_column(String(128))
    expected_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="USD")
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="pending")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = timestamp_column()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReportEntitlement(Base):
    """Report access granted only after independently verified capture."""

    __tablename__ = "report_entitlements"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", "workspace_id", name="uq_report_entitlements_id_tenant"),
        UniqueConstraint("report_id", "purchaser_user_id", name="uq_report_entitlements_report_user"),
        UniqueConstraint("payment_transaction_id", name="uq_report_entitlements_transaction"),
        ForeignKeyConstraint(
            ["report_id", "organization_id", "workspace_id"],
            ["reports.id", "reports.organization_id", "reports.workspace_id"],
            name="fk_entitlement_report",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["payment_transaction_id", "report_id", "organization_id", "workspace_id", "purchaser_user_id"],
            ["payment_transactions.id", "payment_transactions.report_id", "payment_transactions.organization_id", "payment_transactions.workspace_id", "payment_transactions.purchaser_user_id"],
            name="fk_entitlement_payment",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["purchaser_user_id"], ["users.id"], name="fk_entitlement_purchaser_user", ondelete="RESTRICT"
        ),
        CheckConstraint("status IN ('active', 'revoked')", name="valid_status"),
        Index("ix_report_entitlements_tenant_user", "organization_id", "workspace_id", "purchaser_user_id"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    report_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    purchaser_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    payment_transaction_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    granted_at: Mapped[datetime] = timestamp_column()


class PayPalWebhookEvent(Base):
    """Minimal webhook receipt record; no raw body or payment secrets are stored."""

    __tablename__ = "paypal_webhook_events"
    __table_args__ = (
        UniqueConstraint("paypal_event_id", name="uq_paypal_webhook_events_event_id"),
        CheckConstraint("processing_state IN ('received', 'processed', 'failed')", name="valid_processing_state"),
        Index("ix_paypal_webhook_events_received", "received_at"),
    )

    id: Mapped[UUID] = uuid_column()
    paypal_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    paypal_order_id: Mapped[str | None] = mapped_column(String(128))
    paypal_capture_id: Mapped[str | None] = mapped_column(String(128))
    signature_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    processing_state: Mapped[str] = mapped_column(String(20), nullable=False, server_default="received")
    received_at: Mapped[datetime] = timestamp_column()
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    safe_error_code: Mapped[str | None] = mapped_column(String(100))


class KnowledgeDocument(Base):
    """Tenant-owned uploaded knowledge source and its current processing result."""

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", "workspace_id", name="uq_knowledge_documents_id_tenant"),
        UniqueConstraint("storage_key", name="uq_knowledge_documents_storage_key"),
        ForeignKeyConstraint(
            ["workspace_id", "organization_id"],
            ["workspaces.id", "workspaces.organization_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["uploaded_by_membership_id", "organization_id", "workspace_id"],
            ["workspace_memberships.id", "workspace_memberships.organization_id", "workspace_memberships.workspace_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("status IN ('pending', 'processing', 'processed', 'failed')", name="knowledge_document_status"),
        CheckConstraint("byte_size >= 0", name="knowledge_document_byte_size"),
        Index("ix_knowledge_documents_tenant_created", "organization_id", "workspace_id", "created_at"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    uploaded_by_membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_extension: Mapped[str] = mapped_column(String(10), nullable=False)
    detected_content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    extracted_text: Mapped[str | None] = mapped_column(Text)
    normalized_text: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(20))
    processing_error_code: Mapped[str | None] = mapped_column(String(80))
    processing_error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = timestamp_column()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeDocumentChunk(Base):
    """Ordered, tenant-scoped excerpt derived from a knowledge document."""

    __tablename__ = "knowledge_document_chunks"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", "workspace_id", name="uq_knowledge_document_chunks_id_tenant"),
        UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_document_chunks_index"),
        ForeignKeyConstraint(
            ["document_id", "organization_id", "workspace_id"],
            ["knowledge_documents.id", "knowledge_documents.organization_id", "knowledge_documents.workspace_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("chunk_index >= 0", name="knowledge_document_chunk_index"),
        CheckConstraint("start_offset >= 0 AND end_offset > start_offset", name="knowledge_document_chunk_offsets"),
        Index("ix_knowledge_document_chunks_tenant_doc", "organization_id", "workspace_id", "document_id", "chunk_index"),
    )

    id: Mapped[UUID] = uuid_column()
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = timestamp_column()
