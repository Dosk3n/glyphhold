from __future__ import annotations

from fastapi.testclient import TestClient

from app.storage.repositories import memories, secrets


def _setup_and_login(client: TestClient) -> None:
    setup_response = client.post(
        "/setup",
        data={
            "username": "admin",
            "password": "correct horse battery staple",
            "confirm_password": "correct horse battery staple",
        },
    )
    assert setup_response.status_code == 200

    login_response = client.post(
        "/login",
        data={"username": "admin", "password": "correct horse battery staple"},
    )
    assert login_response.status_code == 200
    assert "Status" in login_response.text


def test_dashboard_memory_edit_and_delete(client: TestClient) -> None:
    _setup_and_login(client)

    create_response = client.post(
        "/dashboard/memories",
        data={
            "category_id": "cat_projects",
            "title": "Dashboard memory",
            "summary": "Original summary",
            "body": "Original body",
            "tags": "dashboard, original",
            "confidence": "3",
            "auto_prefetch_level": "normal",
        },
    )
    assert create_response.status_code == 200
    memory = memories.list_memories()[0]

    detail_response = client.get(f"/dashboard/memories/{memory['id']}")
    assert detail_response.status_code == 200
    assert "Save memory" in detail_response.text
    assert "Delete memory" in detail_response.text

    update_response = client.post(
        f"/dashboard/memories/{memory['id']}/update",
        data={
            "category_id": "cat_decisions",
            "title": "Updated dashboard memory",
            "summary": "Updated summary",
            "body": "Updated body",
            "tags": "dashboard, updated",
            "confidence": "5",
            "auto_prefetch_level": "high",
        },
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

    delete_response = client.post(f"/dashboard/memories/{memory['id']}/delete")
    assert delete_response.status_code == 200
    assert memories.get_memory(memory["id"]) is None


def test_dashboard_secret_edit_reveal_and_delete(secrets_client: TestClient) -> None:
    _setup_and_login(secrets_client)

    create_response = secrets_client.post(
        "/dashboard/secrets",
        data={
            "name": "GLYPHHOLD_DASHBOARD_TOKEN",
            "value": "original-secret-value",
            "description": "Original token",
            "value_type": "token",
            "service": "dashboard",
            "host": "local",
            "scope": "tests",
            "tags": "dashboard, token",
        },
    )
    assert create_response.status_code == 200
    created = secrets.get_secret_metadata("GLYPHHOLD_DASHBOARD_TOKEN")
    assert created is not None

    page_response = secrets_client.get("/dashboard/secrets")
    assert page_response.status_code == 200
    assert "Save secret" in page_response.text
    assert "Delete" in page_response.text
    assert "original-secret-value" not in page_response.text

    update_response = secrets_client.post(
        f"/dashboard/secrets/{created['id']}/update",
        data={
            "name": "GLYPHHOLD_DASHBOARD_TOKEN_RENAMED",
            "value": "updated-secret-value",
            "description": "Updated token",
            "value_type": "api_key",
            "service": "dashboard",
            "host": "local",
            "scope": "alpha",
            "tags": "dashboard, updated",
        },
    )
    assert update_response.status_code == 200
    assert "updated-secret-value" not in update_response.text

    reveal_response = secrets_client.post(
        "/dashboard/secrets/GLYPHHOLD_DASHBOARD_TOKEN_RENAMED/reveal"
    )
    assert reveal_response.status_code == 200
    assert "updated-secret-value" in reveal_response.text

    delete_response = secrets_client.post(
        "/dashboard/secrets/GLYPHHOLD_DASHBOARD_TOKEN_RENAMED/delete"
    )
    assert delete_response.status_code == 200
    assert secrets.get_secret_metadata("GLYPHHOLD_DASHBOARD_TOKEN_RENAMED") is None
