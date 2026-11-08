"""Authorization-aware tenant context resolved for one request."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TenantScope:
    organization_id: UUID
    workspace_id: UUID
    user_id: UUID
    permissions: set[str]
