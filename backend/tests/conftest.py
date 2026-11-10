"""PostgreSQL-only test fixtures with transaction-isolated synthetic tenants."""

import os
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.models import EvidenceRecord, Organization, Policy, Submission, User, Workspace, WorkspaceMembership
from app.tenancy.context import TenantScope


@dataclass(frozen=True)
class SyntheticTenant:
    organization_id: UUID
    workspace_id: UUID
    user_id: UUID
    membership_id: UUID
    submission_id: UUID
    evidence_record_id: UUID
    policy_id: UUID
    scope: TenantScope


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.fail("Set TEST_DATABASE_URL to the dedicated verityai_test PostgreSQL database")
    if not url.startswith("postgresql"):
        pytest.fail("Backend integration tests require PostgreSQL")
    if (make_url(url).database or "").casefold() != "verityai_test":
        pytest.fail("Database-backed tests are restricted to a database named verityai_test")
    return url


@pytest.fixture(scope="session")
def engine(database_url: str):
    test_engine = create_engine(database_url, pool_pre_ping=True)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def session_factory(engine):
    """Use an outer connection transaction so each test can freely commit/rollback."""
    connection = engine.connect()
    outer_transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        class_=Session,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    yield factory
    outer_transaction.rollback()
    connection.close()


@pytest.fixture
def tenant_pair(session_factory) -> tuple[SyntheticTenant, SyntheticTenant]:
    tenants: list[SyntheticTenant] = []
    with session_factory() as session:
        with session.begin():
            for suffix in ("north", "south"):
                org_id, workspace_id, user_id, membership_id, submission_id, evidence_id, policy_id = (
                    uuid4() for _ in range(7)
                )
                organization = Organization(id=org_id, name=f"Synthetic {suffix.title()} Org", slug=f"synthetic-{suffix}")
                workspace = Workspace(id=workspace_id, organization_id=org_id, name=f"{suffix.title()} Workspace", slug=suffix)
                user = User(id=user_id, display_name=f"{suffix.title()} Test Member")
                membership = WorkspaceMembership(
                    id=membership_id,
                    organization_id=org_id,
                    workspace_id=workspace_id,
                    user_id=user_id,
                )
                submission = Submission(
                    id=submission_id,
                    organization_id=org_id,
                    workspace_id=workspace_id,
                    created_by_membership_id=membership_id,
                )
                session.add(organization)
                session.flush()
                session.add_all([workspace, user])
                session.flush()
                session.add(membership)
                session.flush()
                session.add(
                    EvidenceRecord(
                        id=evidence_id,
                        organization_id=org_id,
                        workspace_id=workspace_id,
                        owner_membership_id=membership_id,
                    )
                )
                session.add(
                    Policy(
                        id=policy_id,
                        organization_id=org_id,
                        workspace_id=workspace_id,
                        name=f"{suffix.title()} synthetic policy",
                        category="demo",
                        created_by_membership_id=membership_id,
                    )
                )
                session.flush()
                session.add(submission)
                session.flush()
                tenants.append(
                    SyntheticTenant(
                        organization_id=org_id,
                        workspace_id=workspace_id,
                        user_id=user_id,
                        membership_id=membership_id,
                        submission_id=submission_id,
                        evidence_record_id=evidence_id,
                        policy_id=policy_id,
                        scope=TenantScope(org_id, workspace_id, membership_id),
                    )
                )
    return tenants[0], tenants[1]
