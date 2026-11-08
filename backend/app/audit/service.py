"""Audit event insertion that participates in the caller's transaction."""

from collections.abc import Callable
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AnalysisRun,
    AnalysisStageResult,
    AuditEvent,
    EvidenceConflict,
    EvidenceConflictSource,
    EvidenceMatchCandidate,
    EvidenceRecord,
    EvidenceStateEvent,
    EvidenceVersion,
    ExtractedClaim,
    Finding,
    GeneratedSuggestion,
    KnowledgeDocument,
    HumanDisposition,
    MembershipRoleAssignment,
    Organization,
    Policy,
    PolicyVersion,
    ReviewDecision,
    Role,
    RolePermission,
    Submission,
    SubmissionVersion,
    SubmissionVersionArtifact,
    User,
    Workspace,
    WorkspaceMembership,
)
from app.tenancy.context import TenantScope

ResultT = TypeVar("ResultT")


class AuditTargetNotFound(ValueError):
    """Raised when an audit target is outside the supplied tenant scope."""


_TENANT_TARGETS = {
    "membership": WorkspaceMembership,
    "membership_role_assignment": MembershipRoleAssignment,
    "evidence_record": EvidenceRecord,
    "evidence_version": EvidenceVersion,
    "evidence_conflict": EvidenceConflict,
    "evidence_conflict_source": EvidenceConflictSource,
    "evidence_state_event": EvidenceStateEvent,
    "policy": Policy,
    "policy_version": PolicyVersion,
    "submission": Submission,
    "submission_version": SubmissionVersion,
    "submission_version_artifact": SubmissionVersionArtifact,
    "analysis_run": AnalysisRun,
    "analysis_stage_result": AnalysisStageResult,
    "extracted_claim": ExtractedClaim,
    "evidence_match_candidate": EvidenceMatchCandidate,
    "finding": Finding,
    "generated_suggestion": GeneratedSuggestion,
    "human_disposition": HumanDisposition,
    "review_decision": ReviewDecision,
    "knowledge_document": KnowledgeDocument,
}


def _validate_audit_target(session: Session, scope: TenantScope, target_type: str, target_id: UUID) -> None:
    if target_type == "organization":
        exists = session.scalar(
            select(Organization.id).where(
                Organization.id == target_id,
                Organization.id == scope.organization_id,
            )
        )
    elif target_type == "workspace":
        exists = session.scalar(
            select(Workspace.id).where(
                Workspace.id == target_id,
                Workspace.organization_id == scope.organization_id,
                Workspace.id == scope.workspace_id,
            )
        )
    elif target_type == "role":
        exists = session.scalar(
            select(Role.id).where(
                Role.id == target_id,
                Role.organization_id == scope.organization_id,
            )
        )
    elif target_type == "role_permission":
        exists = session.scalar(
            select(RolePermission.id).where(
                RolePermission.id == target_id,
                RolePermission.organization_id == scope.organization_id,
            )
        )
    elif target_type == "user":
        exists = session.scalar(
            select(User.id)
            .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
            .where(
                User.id == target_id,
                WorkspaceMembership.organization_id == scope.organization_id,
                WorkspaceMembership.workspace_id == scope.workspace_id,
            )
        )
    else:
        model = _TENANT_TARGETS.get(target_type)
        if model is None:
            raise ValueError(f"Unsupported audit target type: {target_type}")
        exists = session.scalar(
            select(model.id).where(
                model.id == target_id,
                model.organization_id == scope.organization_id,
                model.workspace_id == scope.workspace_id,
            )
        )
    if exists is None:
        raise AuditTargetNotFound("Audit target does not exist in the supplied tenant scope")


def record_event(
    session: Session,
    scope: TenantScope,
    *,
    actor_membership_id: UUID,
    action_key: str,
    target_type: str,
    target_id: UUID,
    safe_metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    """Add, but never independently commit, a tenant-scoped audit event."""
    _validate_audit_target(session, scope, target_type, target_id)
    event = AuditEvent(
        organization_id=scope.organization_id,
        workspace_id=scope.workspace_id,
        actor_membership_id=actor_membership_id,
        action_key=action_key,
        target_type=target_type,
        target_id=target_id,
        safe_metadata=safe_metadata or {},
    )
    session.add(event)
    return event


def apply_audited_change(
    session: Session,
    scope: TenantScope,
    *,
    actor_membership_id: UUID,
    action_key: str,
    target_type: str,
    target_id: UUID,
    change: Callable[[Session], ResultT],
    safe_metadata: dict[str, Any] | None = None,
) -> ResultT:
    """Apply a state change and append its audit row in the same transaction.

    The caller owns transaction commit/rollback and must pass the same Session
    to the mutation. No audit payload may contain source content or secrets.
    """
    result = change(session)
    record_event(
        session,
        scope,
        actor_membership_id=actor_membership_id,
        action_key=action_key,
        target_type=target_type,
        target_id=target_id,
        safe_metadata=safe_metadata,
    )
    return result
