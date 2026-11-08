from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import (
    AuditEvent,
    EvidenceConflict,
    EvidenceConflictSource,
    EvidenceRecord,
    EvidenceStateEvent,
    EvidenceVersion,
)
from app.api.v1.evidence import router
from app.core.dependencies import get_db, get_tenant_scope
from app.modules.evidence.lifecycle import (
    revise_evidence_validity,
    set_evidence_inactive,
    transition_evidence,
)
from app.modules.evidence.services import derive_evidence_eligibility
from app.modules.tenancy.schemas import TenantScope


def _scope(tenant, permissions=None):
    return TenantScope(
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
        user_id=tenant.user_id,
        permissions=set(permissions or {"evidence.manage", "evidence.read.workspace"}),
    )


def _versioned_evidence(session, tenant, *, state="Uploaded", valid_from=None, valid_until=None):
    record = session.get(EvidenceRecord, tenant.evidence_record_id)
    assert record is not None
    record.primary_lifecycle_state = state
    version = EvidenceVersion(
        id=uuid4(),
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
        evidence_record_id=record.id,
        version_number=1,
        title="Synthetic evidence schedule",
        source_reference="synthetic.pdf",
        private_file_key="private/synthetic.pdf",
        extracted_text="Synthetic evidence text.",
        valid_from=valid_from,
        valid_until=valid_until,
        created_by_membership_id=tenant.membership_id,
        checksum="a" * 64,
    )
    session.add(version)
    session.flush()
    record.current_version_id = version.id
    session.flush()
    session.commit()
    return record, version


def test_lifecycle_requires_uploaded_reviewed_approved_sequence_and_audits(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    with session_factory() as session:
        scope = _scope(tenant)
        record, version = _versioned_evidence(session, tenant)

        with pytest.raises(HTTPException) as invalid:
            transition_evidence(session, scope, record.id, target_state="Approved")
        assert invalid.value.status_code == 409
        assert record.primary_lifecycle_state == "Uploaded"

        transition_evidence(session, scope, record.id, target_state="Reviewed", reason="Source checked.")
        transition_evidence(session, scope, record.id, target_state="Approved", reason="Approved for use.")

        events = list(session.scalars(select(EvidenceStateEvent).where(
            EvidenceStateEvent.evidence_record_id == record.id
        ).order_by(EvidenceStateEvent.occurred_at, EvidenceStateEvent.id)))
        audits = list(session.scalars(select(AuditEvent).where(
            AuditEvent.target_id == record.id,
            AuditEvent.action_key.in_(["evidence.reviewed", "evidence.approved"]),
        )))
        assert record.primary_lifecycle_state == "Approved"
        assert [event.new_value for event in events] == ["Reviewed", "Approved"]
        assert all(event.actor_membership_id == tenant.membership_id for event in events)
        assert {event.action_key for event in audits} == {"evidence.reviewed", "evidence.approved"}
        assert all(event.target_id == record.id for event in audits)
        assert version.id == record.current_version_id


def test_inactive_is_independent_and_blocks_eligibility(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    with session_factory() as session:
        scope = _scope(tenant)
        record, version = _versioned_evidence(
            session, tenant, state="Approved", valid_from=date(2026, 1, 1), valid_until=date(2027, 1, 1)
        )
        set_evidence_inactive(session, scope, record.id, reason="Source withdrawn by owner.")
        result = derive_evidence_eligibility(record, version, datetime(2026, 6, 1, tzinfo=timezone.utc))

        event = session.scalar(select(EvidenceStateEvent).where(
            EvidenceStateEvent.evidence_record_id == record.id
        ))
        audit = session.scalar(select(AuditEvent).where(
            AuditEvent.target_id == record.id, AuditEvent.action_key == "evidence.inactivated"
        ))
        assert record.primary_lifecycle_state == "Approved"
        assert record.is_inactive is True
        assert result["is_eligible"] is False
        assert event is not None and event.new_value == "inactive:true"
        assert audit is not None


def test_validity_edit_creates_version_and_exact_version_reapproval_gate(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    with session_factory() as session:
        scope = _scope(tenant)
        record, old_version = _versioned_evidence(
            session, tenant, state="Approved", valid_from=date(2025, 1, 1), valid_until=date(2025, 12, 31)
        )
        revised = revise_evidence_validity(
            session, scope, record.id,
            valid_from=date(2026, 1, 1), valid_until=date(2026, 12, 31),
            update_from=True, update_until=True,
        )
        result_before = derive_evidence_eligibility(
            record, revised, datetime(2026, 6, 1, tzinfo=timezone.utc)
        )
        old_event_count = session.scalar(select(EvidenceStateEvent.id).where(
            EvidenceStateEvent.evidence_record_id == record.id
        ))
        assert record.primary_lifecycle_state == "Approved"
        assert record.current_version_id == revised.id
        assert old_version.version_number == 1 and old_version.valid_until == date(2025, 12, 31)
        assert revised.version_number == 2 and revised.pending_reapproval is True
        assert revised.is_pending_reapproval is True
        assert result_before["is_eligible"] is False

        transition_evidence(session, scope, record.id, target_state="Approved", reason="Reviewed revised validity.")
        result_after = derive_evidence_eligibility(
            record, revised, datetime(2026, 6, 1, tzinfo=timezone.utc)
        )
        events = list(session.scalars(select(EvidenceStateEvent).where(
            EvidenceStateEvent.evidence_record_id == record.id
        )))
        audit = session.scalar(select(AuditEvent).where(
            AuditEvent.target_id == record.id, AuditEvent.action_key == "evidence.version_reapproved"
        ))
        assert revised.pending_reapproval is True
        assert revised.is_pending_reapproval is False
        assert result_after["is_eligible"] is True
        assert record.primary_lifecycle_state == "Approved"
        assert old_version.id != revised.id
        assert len(events) == 2 and old_event_count is not None
        assert events[-1].event_type == "version_reapproved"
        assert audit is not None


def test_approval_of_revised_reviewed_version_clears_gate_in_same_transition(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    with session_factory() as session:
        scope = _scope(tenant)
        record, _ = _versioned_evidence(
            session, tenant, state="Reviewed", valid_from=date(2025, 1, 1), valid_until=date(2025, 12, 31)
        )
        revised = revise_evidence_validity(
            session, scope, record.id,
            valid_from=date(2026, 1, 1), valid_until=date(2026, 12, 31),
            update_from=True, update_until=True,
        )
        transition_evidence(session, scope, record.id, target_state="Approved")

        assert record.primary_lifecycle_state == "Approved"
        assert revised.is_pending_reapproval is False
        assert session.scalar(select(AuditEvent.id).where(
            AuditEvent.target_id == record.id,
            AuditEvent.action_key == "evidence.version_reapproved",
        )) is not None


def test_validity_revision_preserves_open_conflict_condition(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    with session_factory() as session:
        scope = _scope(tenant)
        record, old_version = _versioned_evidence(
            session, tenant, state="Approved", valid_from=date(2025, 1, 1), valid_until=date(2025, 12, 31)
        )
        conflict = EvidenceConflict(
            id=uuid4(),
            organization_id=tenant.organization_id,
            workspace_id=tenant.workspace_id,
            reported_by_membership_id=tenant.membership_id,
            rationale="Conflicting source values require human review.",
            state="open",
        )
        session.add(conflict)
        session.flush()
        session.add(EvidenceConflictSource(
            organization_id=tenant.organization_id,
            workspace_id=tenant.workspace_id,
            conflict_id=conflict.id,
            evidence_record_id=record.id,
            evidence_version_id=old_version.id,
        ))
        session.commit()

        revised = revise_evidence_validity(
            session, scope, record.id,
            valid_from=date(2026, 1, 1), valid_until=date(2026, 12, 31),
            update_from=True, update_until=True,
        )
        transition_evidence(session, scope, record.id, target_state="Approved")
        result = derive_evidence_eligibility(
            record, revised, datetime(2026, 6, 1, tzinfo=timezone.utc)
        )
        sources = list(session.scalars(select(EvidenceConflictSource).where(
            EvidenceConflictSource.conflict_id == conflict.id
        )))

        assert len(sources) == 2
        assert revised.has_open_manual_conflict is True
        assert revised.is_pending_reapproval is False
        assert result["is_eligible"] is False


def test_validity_revision_rejects_reversed_dates_and_unauthorized_changes(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    with session_factory() as session:
        scope = _scope(tenant)
        record, _ = _versioned_evidence(session, tenant)
        with pytest.raises(HTTPException) as invalid_range:
            revise_evidence_validity(
                session, scope, record.id,
                valid_from=date(2026, 2, 1), valid_until=date(2026, 1, 1),
                update_from=True, update_until=True,
            )
        assert invalid_range.value.status_code == 422

        unauthorized = _scope(tenant, permissions={"evidence.read.workspace"})
        with pytest.raises(HTTPException) as forbidden:
            transition_evidence(session, unauthorized, record.id, target_state="Reviewed")
        assert forbidden.value.status_code == 403
        assert record.primary_lifecycle_state == "Uploaded"
        assert record.current_version_id is not None


def test_evidence_lifecycle_operations_are_tenant_scoped(session_factory, tenant_pair):
    tenant, other = tenant_pair
    with session_factory() as session:
        record, _ = _versioned_evidence(session, tenant)
        with pytest.raises(HTTPException) as error:
            transition_evidence(session, _scope(other), record.id, target_state="Reviewed")
        assert error.value.status_code == 404
        assert record.primary_lifecycle_state == "Uploaded"


def test_evidence_api_exposes_actions_and_versioned_transition_history(session_factory, tenant_pair):
    tenant, other = tenant_pair
    with session_factory() as session:
        record, version = _versioned_evidence(session, tenant)
        session.add(EvidenceStateEvent(
            organization_id=tenant.organization_id,
            workspace_id=tenant.workspace_id,
            evidence_record_id=record.id,
            evidence_version_id=version.id,
            actor_membership_id=tenant.membership_id,
            event_type="uploaded",
            new_value="Uploaded",
        ))
        session.commit()

    app = FastAPI()
    app.include_router(router)

    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_tenant_scope] = lambda: _scope(tenant)
    base = f"/api/v1/organizations/{tenant.organization_id}/workspaces/{tenant.workspace_id}/evidence"
    with TestClient(app) as client:
        before = client.get(f"{base}/{record.id}")
        assert before.status_code == 200
        assert before.json()["evidence"]["available_actions"] == ["review", "mark_inactive", "update_validity"]
        assert before.json()["evidence"]["is_eligible"] is False
        assert "must be Approved" in before.json()["evidence"]["eligibility_reasons"][0]
        assert client.post(f"{base}/{record.id}/review", json={"reason": "Source inspected."}).status_code == 200
        approved = client.post(f"{base}/{record.id}/approve", json={"reason": "Approved for use."})
        assert approved.status_code == 200
        revised_response = client.post(
            f"{base}/{record.id}/validity",
            json={"valid_from": "2026-01-01", "valid_until": "2026-12-31"},
        )
        assert revised_response.status_code == 200
        assert revised_response.json()["version_number"] == 2
        assert revised_response.json()["pending_reapproval"] is True
        assert revised_response.json()["primary_lifecycle_state"] == "Approved"
        reapproved = client.post(f"{base}/{record.id}/approve", json={"reason": "Reviewed revised dates."})
        assert reapproved.status_code == 200
        assert reapproved.json()["pending_reapproval"] is False
        history = client.get(f"{base}/{record.id}")
        assert history.status_code == 200
        assert history.json()["evidence"]["primary_lifecycle_state"] == "Approved"
        assert {row["event_type"] for row in history.json()["lifecycle_events"]} == {
            "lifecycle_transition", "uploaded", "validity_version_created", "version_reapproved"
        }
        assert len(history.json()["lifecycle_events"]) == 5
        current, historical = history.json()["versions"]
        assert current["is_current_version"] is True and current["is_eligible"] is True
        assert historical["is_current_version"] is False and historical["is_eligible"] is False
        cross_tenant = client.get(f"{base}/{other.evidence_record_id}")
        assert cross_tenant.status_code == 404

    app.dependency_overrides.clear()
