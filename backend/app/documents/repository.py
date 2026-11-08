"""Persistence boundary for tenant-scoped knowledge documents and chunks."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KnowledgeDocument, KnowledgeDocumentChunk
from app.tenancy.context import TenantScope


class KnowledgeDocumentRepository:
    def get(self, session: Session, scope: TenantScope, document_id: UUID) -> KnowledgeDocument | None:
        return session.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.id == document_id,
                KnowledgeDocument.organization_id == scope.organization_id,
                KnowledgeDocument.workspace_id == scope.workspace_id,
            )
        )

    def list(self, session: Session, scope: TenantScope, limit: int, offset: int) -> list[KnowledgeDocument]:
        return list(
            session.scalars(
                select(KnowledgeDocument)
                .where(
                    KnowledgeDocument.organization_id == scope.organization_id,
                    KnowledgeDocument.workspace_id == scope.workspace_id,
                )
                .order_by(KnowledgeDocument.created_at.desc(), KnowledgeDocument.id)
                .limit(limit)
                .offset(offset)
            )
        )

    def chunks(
        self,
        session: Session,
        scope: TenantScope,
        document_id: UUID,
        limit: int,
        offset: int,
    ) -> list[KnowledgeDocumentChunk]:
        return list(
            session.scalars(
                select(KnowledgeDocumentChunk)
                .where(
                    KnowledgeDocumentChunk.document_id == document_id,
                    KnowledgeDocumentChunk.organization_id == scope.organization_id,
                    KnowledgeDocumentChunk.workspace_id == scope.workspace_id,
                )
                .order_by(KnowledgeDocumentChunk.chunk_index)
                .limit(limit)
                .offset(offset)
            )
        )

    @staticmethod
    def add(session: Session, document: KnowledgeDocument) -> None:
        session.add(document)

    @staticmethod
    def add_chunks(session: Session, chunks: list[KnowledgeDocumentChunk]) -> None:
        session.add_all(chunks)
