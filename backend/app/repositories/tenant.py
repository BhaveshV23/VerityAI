"""Tenant-scoped repository base for workspace-owned records."""

from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.tenancy.context import TenantScope

ModelT = TypeVar("ModelT")


class TenantScopedRepository(Generic[ModelT]):
    """Restrict every read and write to one explicit organization/workspace."""

    def __init__(self, model: type[ModelT]) -> None:
        self.model = model

    def get(self, session: Session, scope: TenantScope, record_id: UUID) -> ModelT | None:
        statement = select(self.model).where(
            getattr(self.model, "id") == record_id,
            getattr(self.model, "organization_id") == scope.organization_id,
            getattr(self.model, "workspace_id") == scope.workspace_id,
        )
        return session.scalar(statement)

    def list(self, session: Session, scope: TenantScope) -> list[ModelT]:
        statement = select(self.model).where(
            getattr(self.model, "organization_id") == scope.organization_id,
            getattr(self.model, "workspace_id") == scope.workspace_id,
        )
        return list(session.scalars(statement))

    def add(self, session: Session, scope: TenantScope, **values: Any) -> ModelT:
        for key, expected in (
            ("organization_id", scope.organization_id),
            ("workspace_id", scope.workspace_id),
        ):
            supplied = values.get(key)
            if supplied is not None and supplied != expected:
                raise ValueError(f"{key} must come from the explicit tenant scope")
            values[key] = expected
        record = self.model(**values)
        session.add(record)
        return record
