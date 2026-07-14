from __future__ import annotations

from fastapi.testclient import TestClient

from app.storage.repositories import auth as auth_repo
from app.storage.repositories import events
from app.storage.repositories import memories, secrets
from tests.conftest import dashboard_csrf_headers


def _setup_dashboard(client: TestClient) -> None:
    session_before_setup = client.get("/dashboard/api/session")
    assert session_before_setup.status_code == 200
    assert session_before_setup.json() == {"has_admin": False, "user": None}

    setup_response = client.post(
        "/dashboard/api/setup",
        json={
            "username": "admin",
            "password": "correct horse battery staple",
            "confirm_password": "correct horse battery staple",
        },
        headers=dashboard_csrf_headers(client),
    )
    assert setup_response.status_code == 200
    assert setup_response.json()["user"]["username"] == "admin"

    session_after_setup = client.get("/dashboard/api/session")
    assert session_after_setup.status_code == 200
    assert session_after_setup.json()["user"]["username"] == "admin"


def test_dashboard_setup_and_login_state_errors(client: TestClient) -> None:
    csrf_headers = dashboard_csrf_headers(client)
    login_before_setup = client.post(
        "/dashboard/api/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=csrf_headers,
    )
    assert login_before_setup.status_code == 404
    assert login_before_setup.json()["detail"] == "Dashboard setup is required"

    short_setup = client.post(
        "/dashboard/api/setup",
        json={"username": "admin", "password": "short", "confirm_password": "short"},
        headers=csrf_headers,
    )
    assert short_setup.status_code == 400
    assert short_setup.json()["detail"] == "Password must be at least 12 characters."

    _setup_dashboard(client)

    duplicate_setup = client.post(
        "/dashboard/api/setup",
        json={
            "username": "second",
            "password": "correct horse battery staple",
            "confirm_password": "correct horse battery staple",
        },
        headers=dashboard_csrf_headers(client),
    )
    assert duplicate_setup.status_code == 409
    assert duplicate_setup.json()["detail"] == "Dashboard user already exists"

    client.post("/dashboard/api/logout", headers=dashboard_csrf_headers(client))
    bad_login = client.post(
        "/dashboard/api/login",
        json={"username": "admin", "password": "wrong password"},
        headers=dashboard_csrf_headers(client),
    )
    assert bad_login.status_code == 401
    assert bad_login.json()["detail"] == "Invalid username or password."


def test_dashboard_spa_routes_are_served(client: TestClient) -> None:
    dashboard_response = client.get("/dashboard")
    memory_response = client.get("/dashboard/memories/mem_example")

    assert dashboard_response.status_code == 200
    assert 'id="root"' in dashboard_response.text
    assert memory_response.status_code == 200
    assert 'id="root"' in memory_response.text


def test_dashboard_memory_edit_and_delete(client: TestClient) -> None:
    _setup_dashboard(client)

    create_response = client.post(
        "/dashboard/api/memories",
        json={
            "category_id": "cat_projects",
            "title": "Dashboard memory",
            "summary": "Original summary",
            "body": "Original body",
            "tags": ["dashboard", "original"],
            "confidence": 3,
            "auto_prefetch_level": "normal",
        },
        headers=dashboard_csrf_headers(client),
    )
    assert create_response.status_code == 201
    memory = create_response.json()
    assert memory["tags"] == ["dashboard", "original"]

    detail_response = client.get(f"/dashboard/api/memories/{memory['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["memory"]["title"] == "Dashboard memory"

    update_response = client.patch(
        f"/dashboard/api/memories/{memory['id']}",
        json={
            "category_id": "cat_decisions",
            "title": "Updated dashboard memory",
            "summary": "Updated summary",
            "body": "Updated body",
            "tags": ["dashboard", "updated"],
            "confidence": 5,
            "auto_prefetch_level": "high",
        },
        headers=dashboard_csrf_headers(client),
    )
    assert update_response.status_code == 200
    updated = memories.get_memory(memory["id"])
    assert updated is not None
    assert updated["title"] == "Updated dashboard memory"
    assert updated["category_name"] == "decisions"
    assert updated["confidence"] == 5

    revisions = memories.list_revisions(memory["id"])
    assert len(revisions) == 1
    assert revisions[0]["title"] == "Dashboard memory"
    assert revisions[0]["changed_by"] == "admin"

    restore_response = client.post(
        f"/dashboard/api/memories/{memory['id']}/revisions/{revisions[0]['id']}/restore",
        headers=dashboard_csrf_headers(client),
    )
    assert restore_response.status_code == 200
    restored = memories.get_memory(memory["id"])
    assert restored is not None
    assert restored["title"] == "Dashboard memory"
    assert restored["category_name"] == "projects"

    blocked_delete_response = client.request(
        "DELETE",
        f"/dashboard/api/memories/{memory['id']}",
        json={"confirm_title": ""},
        headers=dashboard_csrf_headers(client),
    )
    assert blocked_delete_response.status_code == 400
    assert "Dashboard memory" in blocked_delete_response.json()["detail"]
    assert memories.get_memory(memory["id"]) is not None

    delete_response = client.request(
        "DELETE",
        f"/dashboard/api/memories/{memory['id']}",
        json={"confirm_title": "Dashboard memory"},
        headers=dashboard_csrf_headers(client),
    )
    assert delete_response.status_code == 200
    assert memories.get_memory(memory["id"]) is None


def test_dashboard_secret_edit_reveal_and_delete(secrets_client: TestClient) -> None:
    _setup_dashboard(secrets_client)

    create_response = secrets_client.post(
        "/dashboard/api/secrets",
        json={
            "name": "DASHBOARD_TOKEN",
            "value": "original-secret-value",
            "description": "Original token",
            "value_type": "token",
            "service": "dashboard",
            "host": "local",
            "scope": "tests",
            "tags": ["dashboard", "token"],
            "allowed_agents": ["codex"],
            "allowed_tools": ["glyphhold_mcp"],
        },
        headers=dashboard_csrf_headers(secrets_client),
    )
    assert create_response.status_code == 201
    assert "original-secret-value" not in create_response.text
    created = secrets.get_secret_metadata("DASHBOARD_TOKEN")
    assert created is not None

    list_response = secrets_client.get("/dashboard/api/secrets")
    assert list_response.status_code == 200
    assert "original-secret-value" not in list_response.text
    assert list_response.json()["secrets"][0]["name"] == "DASHBOARD_TOKEN"
    assert list_response.json()["secrets"][0]["allowed_agents"] == ["codex"]
    assert list_response.json()["secrets"][0]["allowed_agents_text"] == "codex"
    assert list_response.json()["secrets"][0]["allowed_tools"] == ["glyphhold_mcp"]
    assert list_response.json()["secrets"][0]["allowed_tools_text"] == "glyphhold_mcp"

    update_response = secrets_client.patch(
        f"/dashboard/api/secrets/{created['id']}",
        json={
            "name": "DASHBOARD_TOKEN_RENAMED",
            "value": "updated-secret-value",
            "description": "Updated token",
            "value_type": "api_key",
            "service": "dashboard",
            "host": "local",
            "scope": "beta",
            "tags": ["dashboard", "updated"],
            "allowed_agents": [],
            "allowed_tools": [],
        },
        headers=dashboard_csrf_headers(secrets_client),
    )
    assert update_response.status_code == 200
    assert "updated-secret-value" not in update_response.text
    assert update_response.json()["allowed_agents"] == []
    assert update_response.json()["allowed_tools"] == []

    reveal_response = secrets_client.post(
        "/dashboard/api/secrets/DASHBOARD_TOKEN_RENAMED/reveal",
        headers=dashboard_csrf_headers(secrets_client),
    )
    assert reveal_response.status_code == 200
    assert reveal_response.json() == {
        "name": "DASHBOARD_TOKEN_RENAMED",
        "value": "updated-secret-value",
    }

    blocked_delete_response = secrets_client.request(
        "DELETE",
        "/dashboard/api/secrets/DASHBOARD_TOKEN_RENAMED",
        json={"confirm_name": ""},
        headers=dashboard_csrf_headers(secrets_client),
    )
    assert blocked_delete_response.status_code == 400
    assert "DASHBOARD_TOKEN_RENAMED" in blocked_delete_response.json()["detail"]
    assert secrets.get_secret_metadata("DASHBOARD_TOKEN_RENAMED") is not None

    delete_response = secrets_client.request(
        "DELETE",
        "/dashboard/api/secrets/DASHBOARD_TOKEN_RENAMED",
        json={"confirm_name": "DASHBOARD_TOKEN_RENAMED"},
        headers=dashboard_csrf_headers(secrets_client),
    )
    assert delete_response.status_code == 200
    assert secrets.get_secret_metadata("DASHBOARD_TOKEN_RENAMED") is None


def test_dashboard_api_key_disable_requires_confirmation(client: TestClient) -> None:
    _setup_dashboard(client)

    create_response = client.post(
        "/dashboard/api/api-keys",
        json={
            "name": "Local agent",
            "actor": "local-agent",
            "description": "local agent",
            "scopes": ["memories:read", "memories:write"],
        },
        headers=dashboard_csrf_headers(client),
    )
    assert create_response.status_code == 200
    assert create_response.json()["value"].startswith("gh_live_")

    key = auth_repo.list_api_keys()[0]
    assert key["enabled"] == 1

    list_response = client.get("/dashboard/api/api-keys")
    assert list_response.status_code == 200
    assert list_response.json()["keys"][0]["scopes"] == ["memories:read", "memories:write"]

    blocked_disable_response = client.post(
        f"/dashboard/api/api-keys/{key['id']}/disable",
        json={"confirm_name": ""},
        headers=dashboard_csrf_headers(client),
    )
    assert blocked_disable_response.status_code == 400
    assert "Local agent" in blocked_disable_response.json()["detail"]
    assert auth_repo.get_api_key_metadata(key["id"])["enabled"] == 1

    disable_response = client.post(
        f"/dashboard/api/api-keys/{key['id']}/disable",
        json={"confirm_name": "Local agent"},
        headers=dashboard_csrf_headers(client),
    )
    assert disable_response.status_code == 200
    assert auth_repo.get_api_key_metadata(key["id"])["enabled"] == 0

    enable_response = client.post(
        f"/dashboard/api/api-keys/{key['id']}/enable",
        headers=dashboard_csrf_headers(client),
    )
    assert enable_response.status_code == 200
    assert auth_repo.get_api_key_metadata(key["id"])["enabled"] == 1

    event_types = [event["event_type"] for event in events.list_events(limit=10)]
    assert "api_key.disable" in event_types
    assert "api_key.enable" in event_types
