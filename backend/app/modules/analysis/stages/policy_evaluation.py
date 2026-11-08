"""Deterministic evaluation of active policy versions."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Policy, PolicyVersion
from app.modules.tenancy.schemas import TenantScope


def evaluate_policies(
    db: Session,
    tenant_scope: TenantScope,
    analysis_run,
    text: str,
) -> list[dict]:
    """Return active prohibited-term rules triggered by the supplied text."""
    policies = db.execute(
        select(Policy, PolicyVersion)
        .join(
            PolicyVersion,
            (PolicyVersion.policy_id == Policy.id)
            & (PolicyVersion.organization_id == Policy.organization_id)
            & (PolicyVersion.workspace_id == Policy.workspace_id),
        )
        .where(
            Policy.organization_id == tenant_scope.organization_id,
            Policy.workspace_id == tenant_scope.workspace_id,
            Policy.status == "Active",
            PolicyVersion.organization_id == tenant_scope.organization_id,
            PolicyVersion.workspace_id == tenant_scope.workspace_id,
        )
        .order_by(Policy.id, PolicyVersion.version_number)
    ).all()
    normalized_text = text.casefold()
    violations: list[dict] = []
    for policy, version in policies:
        if version.rule_type.casefold() != "prohibited_term":
            continue
        config_term = version.configuration.get("term") if version.configuration else None
        term = str(config_term or version.rule_text).strip()
        if not term or term.casefold() not in normalized_text:
            continue
        violations.append(
            {
                "policy_id": policy.id,
                "policy_version_id": version.id,
                "explanation": f"Text contains prohibited term '{term}'.",
            }
        )
    return violations
