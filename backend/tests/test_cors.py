from fastapi.testclient import TestClient

from app.main import app


def test_cors_allows_configured_local_vite_origin() -> None:
    response = TestClient(app).options(
        "/api/v1/organizations/example/workspaces/example/submissions",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-organization-id",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-credentials" not in response.headers


def test_cors_does_not_allow_unconfigured_origin() -> None:
    response = TestClient(app).options(
        "/api/v1/organizations/example/workspaces/example/submissions",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
