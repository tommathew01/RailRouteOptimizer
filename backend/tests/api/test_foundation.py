from __future__ import annotations

import httpx


async def test_liveness(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_without_dependencies_is_ready(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


async def test_request_id_is_generated_and_echoed(client: httpx.AsyncClient) -> None:
    generated = await client.get("/api/v1/health/live")
    assert len(generated.headers["x-request-id"]) >= 8
    echoed = await client.get("/api/v1/health/live", headers={"X-Request-ID": "client-req-0001"})
    assert echoed.headers["x-request-id"] == "client-req-0001"
    unsafe = await client.get("/api/v1/health/live", headers={"X-Request-ID": "bad id\n"})
    assert unsafe.headers["x-request-id"] != "bad id\n"


async def test_security_headers_present(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health/live")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"


async def test_unknown_route_uses_error_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist", headers={"X-Request-ID": "req-abcdefgh"})
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "NOT_FOUND", "message": "Not Found", "request_id": "req-abcdefgh"}
    }


async def test_oversized_body_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/meta", content=b"x" * 70_000)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"


async def test_meta_labels_demo_mode_and_default_quota(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/v1/meta")).json()
    assert body["data_mode"] == "DEMO"
    assert body["provider"] == "MOCK"
    assert body["quota"] == {"code": "GN", "label": "General", "editable": True}
    assert body["limits"]["max_segments"] == 4
    assert any("Demo mode" in note for note in body["disclaimers"])
    assert any("separate reservation" in note for note in body["disclaimers"])
    assert {"code": "3A", "label": "AC 3 Tier", "category": "AC"} in body["supported_classes"]


async def test_openapi_is_published(client: httpx.AsyncClient) -> None:
    schema = (await client.get("/api/openapi.json")).json()
    assert schema["info"]["title"] == "RailRoute Optimizer"
    assert "/api/v1/health/live" in schema["paths"]
