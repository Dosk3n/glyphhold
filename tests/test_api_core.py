from __future__ import annotations

from fastapi.testclient import TestClient

from app.storage.repositories import events
from tests.conftest import make_api_key_headers


def test_health_reports_database_and_schema(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"].startswith("req_")
    assert response.json() == {
        "status": "ok",
        "version": "1.0.1",
        "database": "ok",
        "schema_version": 4,
        "secrets_enabled": False,
    }


def test_api_key_scope_enforcement(client: TestClient) -> None:
    read_headers = make_api_key_headers(scopes=["memories:read"], actor="reader")

    categories_response = client.get("/api/v1/categories", headers=read_headers)
    assert categories_response.status_code == 200
    assert {category["name"] for category in categories_response.json()} >= {
        "people",
        "projects",
        "temporary",
    }

    create_response = client.post(
        "/api/v1/memories",
        headers=read_headers,
        json={
            "category_id": "cat_projects",
            "title": "Denied write",
            "body": "This should not be created.",
        },
    )
    assert create_response.status_code == 403


def test_api_key_auth_failures_are_logged_safely(client: TestClient) -> None:
    missing_response = client.get("/api/v1/categories")
    assert missing_response.status_code == 401

    invalid_response = client.get(
        "/api/v1/categories",
        headers={"Authorization": "Bearer gh_live_DO_NOT_LOG_THIS_SECRET_VALUE"},
    )
    assert invalid_response.status_code == 401

    auth_events = events.list_events(event_type="api_key.auth_failed", limit=10)
    assert len(auth_events) == 2
    rendered_events = "\n".join(str(event) for event in auth_events)
    assert "Missing bearer API key" in rendered_events
    assert "Invalid bearer API key" in rendered_events
    assert "gh_live_DO_NOT_LOG_THIS_SECRET_VALUE" not in rendered_events


def test_memory_lifecycle_search_prefetch_and_revisions(client: TestClient) -> None:
    headers = make_api_key_headers(
        scopes=["memories:read", "memories:write", "events:read"],
        actor="memory-agent",
    )

    create_response = client.post(
        "/api/v1/memories",
        headers=headers,
        json={
            "category_id": "cat_projects",
            "title": "Glyph Hold roadmap",
            "summary": "Glyph Hold uses FastAPI, SQLite, and deterministic search.",
            "body": "The project should avoid LLMs and vector databases.",
            "tags": ["glyphhold", "roadmap"],
            "confidence": 4,
            "auto_prefetch_level": "high",
        },
    )
    assert create_response.status_code == 201
    memory = create_response.json()

    search_response = client.post(
        "/api/v1/memories/search",
        headers=headers,
        json={"query": "glyphhold roadmap", "limit": 5},
    )
    assert search_response.status_code == 200
    assert [item["id"] for item in search_response.json()["results"]] == [memory["id"]]

    update_response = client.patch(
        f"/api/v1/memories/{memory['id']}",
        headers=headers,
        json={
            "title": "Glyph Hold alpha roadmap",
            "body": "The alpha should include tests and Docker release notes.",
            "change_reason": "tighten alpha scope",
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["title"] == "Glyph Hold alpha roadmap"

    revisions_response = client.get(f"/api/v1/memories/{memory['id']}/revisions", headers=headers)
    assert revisions_response.status_code == 200
    revisions = revisions_response.json()
    assert len(revisions) == 1
    assert revisions[0]["title"] == "Glyph Hold roadmap"
    assert revisions[0]["category_id"] == "cat_projects"
    assert revisions[0]["changed_by"] == "memory-agent"

    restore_response = client.post(
        f"/api/v1/memories/{memory['id']}/revisions/{revisions[0]['id']}/restore",
        headers=headers,
        json={"change_reason": "restore original roadmap"},
    )
    assert restore_response.status_code == 200
    restored = restore_response.json()
    assert restored["title"] == "Glyph Hold roadmap"
    assert restored["category_id"] == "cat_projects"

    revisions_after_restore_response = client.get(
        f"/api/v1/memories/{memory['id']}/revisions",
        headers=headers,
    )
    assert revisions_after_restore_response.status_code == 200
    revisions_after_restore = revisions_after_restore_response.json()
    assert len(revisions_after_restore) == 2
    assert revisions_after_restore[0]["title"] == "Glyph Hold alpha roadmap"
    assert revisions_after_restore[0]["change_reason"] == "restore original roadmap"

    prefetch_response = client.post(
        "/api/v1/agent/prefetch",
        headers=headers,
        json={"message": "What is the glyphhold alpha roadmap?"},
    )
    assert prefetch_response.status_code == 200
    prefetch = prefetch_response.json()
    assert prefetch["should_inject"] is True
    assert prefetch["memories"][0]["id"] == memory["id"]
    assert "body" not in prefetch["memories"][0]


def test_secret_storage_disabled_returns_clear_error(client: TestClient) -> None:
    headers = make_api_key_headers(scopes=["secrets:write"], actor="secret-writer")

    response = client.post(
        "/api/v1/secrets",
        headers=headers,
        json={"name": "GLYPHHOLD_TEST", "value": "hidden"},
    )

    assert response.status_code == 503
    assert "GLYPHHOLD_ENCRYPTION_KEY is not set" in response.json()["detail"]


def test_secret_metadata_reveal_and_prefetch_do_not_leak_values(secrets_client: TestClient) -> None:
    secret_headers = make_api_key_headers(
        scopes=["secrets:write", "secrets:reveal"],
        actor="secret-agent",
    )
    memory_headers = make_api_key_headers(
        scopes=["memories:read", "memories:write", "events:read"],
        actor="memory-agent",
    )

    create_response = secrets_client.post(
        "/api/v1/secrets",
        headers=secret_headers,
        json={
            "name": "GLYPHHOLD_TOKEN",
            "value": "super-secret-value",
            "description": "token used in tests",
            "scope": "tests",
            "tags": ["token"],
        },
    )
    assert create_response.status_code == 201
    assert "super-secret-value" not in create_response.text
    assert "encrypted_value" not in create_response.text

    list_response = secrets_client.get("/api/v1/secrets", headers=secret_headers)
    assert list_response.status_code == 200
    assert "super-secret-value" not in list_response.text
    assert "encrypted_value" not in list_response.text

    reveal_response = secrets_client.post(
        "/api/v1/secrets/GLYPHHOLD_TOKEN/reveal",
        headers=secret_headers,
        json={"purpose": "test reveal"},
    )
    assert reveal_response.status_code == 200
    assert reveal_response.json()["value"] == "super-secret-value"

    memory_response = secrets_client.post(
        "/api/v1/memories",
        headers=memory_headers,
        json={
            "category_id": "cat_services",
            "title": "Token service",
            "summary": "Use the token service without exposing values.",
            "body": "Token metadata is safe, secret values are not.",
            "tags": ["token"],
            "auto_prefetch_level": "high",
        },
    )
    assert memory_response.status_code == 201

    prefetch_response = secrets_client.post(
        "/api/v1/agent/prefetch",
        headers=memory_headers,
        json={"message": "token service"},
    )
    assert prefetch_response.status_code == 200
    assert "super-secret-value" not in prefetch_response.text
    assert "GLYPHHOLD_TOKEN" not in prefetch_response.text

    events_response = secrets_client.get("/api/v1/events", headers=memory_headers)
    assert events_response.status_code == 200
    assert "super-secret-value" not in events_response.text
