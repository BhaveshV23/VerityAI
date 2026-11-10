from uuid import uuid4

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.audit.service import AuditTargetNotFound, apply_audited_change, record_event
from app.db.transactions import transaction
from app.models import AuditEvent, EvidenceVersion, PolicyVersion, Submission, SubmissionVersion, Workspace
from app.repositories.tenant import TenantScopedRepository


def _rename_workspace(session, workspace_id):
    workspace = session.get(Workspace, workspace_id)
    assert workspace is not None
    workspace.name = "North Workspace Updated"
    return workspace


def test_fresh_migration_contains_expected_relational_tables(engine):
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {
        "organizations",
        "workspaces",
        "users",
        "workspace_memberships",
        "roles",
        "permissions",
        "role_permissions",
        "membership_role_assignments",
        "evidence_records",
        "evidence_versions",
        "policies",
        "policy_versions",
        "submissions",
        "submission_versions",
        "analysis_runs",
        "analysis_stage_results",
        "findings",
        "review_decisions",
        "human_dispositions",
        "audit_events",
        "knowledge_documents",
        "knowledge_document_chunks",
    } <= tables
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "7ad3a10c8421"


def test_repository_reads_are_limited_to_explicit_tenant_scope(session_factory, tenant_pair):
    first, second = tenant_pair
    repository = TenantScopedRepository(Submission)
    with session_factory() as session:
        assert repository.get(session, first.scope, first.submission_id) is not None
        assert repository.get(session, first.scope, second.submission_id) is None
        assert [row.id for row in repository.list(session, first.scope)] == [first.submission_id]


def test_database_rejects_cross_tenant_workspace_reference(session_factory, tenant_pair):
    first, second = tenant_pair
    with pytest.raises(IntegrityError):
        with transaction(session_factory) as session:
            session.add(
                Submission(
                    id=uuid4(),
                    organization_id=first.organization_id,
                    workspace_id=second.workspace_id,
                    created_by_membership_id=first.membership_id,
                )
            )


def test_database_rejects_cross_tenant_submission_parent_reference(session_factory, tenant_pair):
    first, second = tenant_pair
    with pytest.raises(IntegrityError):
        with transaction(session_factory) as session:
            session.add(
                SubmissionVersion(
                    id=uuid4(),
                    organization_id=first.organization_id,
                    workspace_id=first.workspace_id,
                    submission_id=second.submission_id,
                    version_number=1,
                    source_type="text",
                    submitted_text="synthetic source",
                    source_hash="a" * 64,
                    submitter_membership_id=first.membership_id,
                )
            )


def test_database_rejects_cross_tenant_evidence_version_parent(session_factory, tenant_pair):
    first, second = tenant_pair
    with pytest.raises(IntegrityError):
        with transaction(session_factory) as session:
            session.add(
                EvidenceVersion(
                    id=uuid4(),
                    organization_id=first.organization_id,
                    workspace_id=first.workspace_id,
                    evidence_record_id=second.evidence_record_id,
                    version_number=1,
                    title="cross tenant reference",
                    created_by_membership_id=first.membership_id,
                )
            )


def test_database_rejects_cross_tenant_policy_version_parent(session_factory, tenant_pair):
    first, second = tenant_pair
    with pytest.raises(IntegrityError):
        with transaction(session_factory) as session:
            session.add(
                PolicyVersion(
                    id=uuid4(),
                    organization_id=first.organization_id,
                    workspace_id=first.workspace_id,
                    policy_id=second.policy_id,
                    version_number=1,
                    rule_text="synthetic rule",
                    rule_type="demo",
                    status_snapshot="Draft",
                    created_by_membership_id=first.membership_id,
                )
            )


def test_transaction_rolls_back_state_and_audit_together(session_factory, tenant_pair):
    first, _ = tenant_pair
    with pytest.raises(RuntimeError, match="abort the transaction"):
        with transaction(session_factory) as session:
            workspace = session.get(Workspace, first.workspace_id)
            assert workspace is not None
            workspace.name = "Must roll back"
            apply_audited_change(
                session,
                first.scope,
                actor_membership_id=first.membership_id,
                action_key="test.workspace.rename",
                target_type="workspace",
                target_id=first.workspace_id,
                change=lambda active_session: workspace,
            )
            raise RuntimeError("abort the transaction")

    with session_factory() as session:
        workspace = session.get(Workspace, first.workspace_id)
        assert workspace is not None and workspace.name == "North Workspace"
        assert session.scalar(
            select(AuditEvent.id).where(AuditEvent.target_id == first.workspace_id)
        ) is None


def test_audit_event_commits_with_the_associated_state_change(session_factory, tenant_pair):
    first, _ = tenant_pair
    with transaction(session_factory) as session:
        apply_audited_change(
            session,
            first.scope,
            actor_membership_id=first.membership_id,
            action_key="test.workspace.rename",
            target_type="workspace",
            target_id=first.workspace_id,
            change=lambda active_session: _rename_workspace(active_session, first.workspace_id),
            safe_metadata={"field": "name"},
        )

    with session_factory() as session:
        workspace = session.get(Workspace, first.workspace_id)
        event = session.scalar(select(AuditEvent).where(AuditEvent.target_id == first.workspace_id))
        assert workspace is not None and workspace.name == "North Workspace Updated"
        assert event is not None
        assert event.action_key == "test.workspace.rename"
        assert event.organization_id == first.organization_id
        assert event.workspace_id == first.workspace_id
        assert event.safe_metadata == {"field": "name"}


def test_audit_service_rejects_a_cross_tenant_target(session_factory, tenant_pair):
    first, second = tenant_pair
    with pytest.raises(AuditTargetNotFound):
        with transaction(session_factory) as session:
            record_event(
                session,
                first.scope,
                actor_membership_id=first.membership_id,
                action_key="test.cross_tenant_attempt",
                target_type="submission",
                target_id=second.submission_id,
            )


def test_audit_events_are_append_only(session_factory, tenant_pair):
    first, _ = tenant_pair
    event_id = uuid4()
    with transaction(session_factory) as session:
        event = record_event(
            session,
            first.scope,
            actor_membership_id=first.membership_id,
            action_key="test.append_only",
            target_type="workspace",
            target_id=first.workspace_id,
        )
        event.id = event_id

    with pytest.raises(DBAPIError):
        with transaction(session_factory) as session:
            event = session.get(AuditEvent, event_id)
            assert event is not None
            event.action_key = "test.overwrite"


def test_submitted_versions_are_immutable_and_prior_references_survive(session_factory, tenant_pair):
    first, _ = tenant_pair
    version_id = uuid4()
    with transaction(session_factory) as session:
        session.add(
            SubmissionVersion(
                id=version_id,
                organization_id=first.organization_id,
                workspace_id=first.workspace_id,
                submission_id=first.submission_id,
                version_number=1,
                source_type="text",
                submitted_text="immutable synthetic text",
                source_hash="b" * 64,
                submitter_membership_id=first.membership_id,
            )
        )

    with pytest.raises(DBAPIError):
        with transaction(session_factory) as session:
            version = session.get(SubmissionVersion, version_id)
            assert version is not None
            version.submitted_text = "attempted overwrite"

    with session_factory() as session:
        version = session.get(SubmissionVersion, version_id)
        assert version is not None
        assert version.submitted_text == "immutable synthetic text"
