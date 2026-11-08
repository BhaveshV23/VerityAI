import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.dependencies import get_db, get_tenant_scope, require_permission
from app.models import MembershipRoleAssignment, Permission, Role, RolePermission
from app.modules.tenancy.schemas import TenantScope
from app.scripts.bootstrap_development_tenant import USER_ID, initialize_development_tenant


def _scope_app(session_factory):
    test_app = FastAPI()

    def override_get_db():
        with session_factory() as session:
            yield session

    test_app.dependency_overrides[get_db] = override_get_db

    @test_app.get("/scope")
    def scope_endpoint(scope: TenantScope = Depends(get_tenant_scope)):
        return {
            "organization_id": str(scope.organization_id),
            "workspace_id": str(scope.workspace_id),
            "user_id": str(scope.user_id),
            "permissions": sorted(scope.permissions),
        }

    @test_app.get("/protected")
    def protected_endpoint(scope: TenantScope = Depends(require_permission("documents.read"))):
        return {"user_id": str(scope.user_id), "allowed": True}

    return test_app


def _tenant_headers(organization_id, workspace_id, user_id):
    return {
        "X-Organization-ID": str(organization_id),
        "X-Workspace-ID": str(workspace_id),
        "X-User-ID": str(user_id),
    }


def test_falls_back_to_seeded_development_tenant_without_headers(session_factory, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    tenant = initialize_development_tenant(session_factory)
    test_app = _scope_app(session_factory)

    with TestClient(test_app) as client:
        response = client.get("/scope")

    assert response.status_code == 200
    assert response.json() == {
        "organization_id": tenant.organization_id,
        "workspace_id": tenant.workspace_id,
        "user_id": str(USER_ID),
        "permissions": [],
    }


def test_resolves_explicit_valid_headers_to_active_membership(session_factory, tenant_pair, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    first, _ = tenant_pair
    test_app = _scope_app(session_factory)

    with TestClient(test_app) as client:
        response = client.get(
            "/scope",
            headers=_tenant_headers(first.organization_id, first.workspace_id, first.user_id),
        )

    assert response.status_code == 200
    assert response.json() == {
        "organization_id": str(first.organization_id),
        "workspace_id": str(first.workspace_id),
        "user_id": str(first.user_id),
        "permissions": [],
    }


def test_permission_dependency_allows_member_with_active_permission(
    session_factory, tenant_pair, monkeypatch
):
    monkeypatch.setenv("APP_ENV", "development")
    first, _ = tenant_pair
    with session_factory() as session:
        with session.begin():
            role = Role(
                organization_id=first.organization_id,
                key="documents-reader",
                display_name="Documents Reader",
            )
            permission = Permission(key="documents.read", description="Read knowledge documents")
            session.add_all([role, permission])
            session.flush()
            session.add(
                RolePermission(
                    organization_id=first.organization_id,
                    role_id=role.id,
                    permission_id=permission.id,
                    assigned_by_membership_id=first.membership_id,
                )
            )
            session.add(
                MembershipRoleAssignment(
                    organization_id=first.organization_id,
                    workspace_id=first.workspace_id,
                    membership_id=first.membership_id,
                    role_id=role.id,
                    assigned_by_membership_id=first.membership_id,
                )
            )

    test_app = _scope_app(session_factory)
    with TestClient(test_app) as client:
        response = client.get(
            "/protected",
            headers=_tenant_headers(first.organization_id, first.workspace_id, first.user_id),
        )

    assert response.status_code == 200
    assert response.json()["allowed"] is True


def test_permission_dependency_returns_required_403_shape_for_missing_permission(
    session_factory, tenant_pair, monkeypatch
):
    monkeypatch.setenv("APP_ENV", "development")
    first, _ = tenant_pair
    test_app = _scope_app(session_factory)

    with TestClient(test_app) as client:
        response = client.get(
            "/protected",
            headers=_tenant_headers(first.organization_id, first.workspace_id, first.user_id),
        )

    assert response.status_code == 403
    assert response.json() == {
        "detail": {
            "error": {
                "code": "FORBIDDEN",
                "message": "Permission 'documents.read' required",
            }
        }
    }


def test_partial_tenant_headers_are_rejected(session_factory, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    test_app = _scope_app(session_factory)
    with TestClient(test_app) as client:
        response = client.get("/scope", headers={"X-Organization-ID": "00000000-0000-0000-0000-000000000000"})
    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "INVALID_TENANT_HEADERS"
