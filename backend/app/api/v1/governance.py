"""Workspace governance metrics endpoint."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_permission
from app.modules.governance.services import get_workspace_metrics
from app.modules.tenancy.schemas import TenantScope


router = APIRouter(tags=["governance"])


@router.get("/api/v1/organizations/{org_id}/workspaces/{workspace_id}/governance-metrics")
def read_governance_metrics(
    org_id: UUID,
    workspace_id: UUID,
    db: Session = Depends(get_db),
    scope: TenantScope = Depends(require_permission("insight.read")),
) -> dict:
    if org_id != scope.organization_id or workspace_id != scope.workspace_id:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return get_workspace_metrics(db, scope)
