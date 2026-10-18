"""Regression coverage for scoped memory metadata and global category ownership."""

import pytest

from app.config import settings
from app.core.auth import create_api_key, create_session_value
from app.storage.repositories import auth as auth_repo
from app.storage.repositories import categories
from app.v2 import core
from tests.conftest import dashboard_csrf_headers


def scoped_headers(scopes):
    key_id, value = create_api_key(
        name="security review", actor="security-review", description=None, scopes=scopes
    )
    core.set_connection(
        core.ADMIN,
        key_id,
        {
            "default_space_id": "space_work",
            "grants": [{"space_id": "space_work", "can_read": True, "can_write": True}],
        },
    )
    return {"Authorization": "Bearer " + value}


@pytest.mark.parametrize("scopes", [[], ["secrets:reveal"], ["memories:write"]])
@pytest.mark.parametrize("endpoint", ["subjects", "guidance", "context"])
def test_memory_metadata_requires_memory_read_scope(client, scopes, endpoint):
    headers = scoped_headers(scopes)
    core.create_subject(core.ADMIN, {"space_id": "space_work", "name": "Private person"})
    core.create_guidance(
        core.ADMIN, {"space_id": "space_work", "statement": "Confidential placement rule"}
    )
    response = client.get("/api/v2/" + endpoint + "?session_id=review", headers=headers)
    assert response.status_code == 403
    assert "Private person" not in response.text
    assert "Confidential placement rule" not in response.text
    if endpoint == "context":
        assert (
            client.put(
                "/api/v2/context",
                headers=headers,
                json={"session_id": "review", "space_id": "space_work"},
            ).status_code
            == 403
        )


def test_metadata_reads_preserve_space_boundaries(client):
    headers = scoped_headers(["memories:read"])
    work = core.create_subject(core.ADMIN, {"space_id": "space_work", "name": "Work person"})
    core.create_subject(core.ADMIN, {"space_id": "space_personal", "name": "Personal person"})
    core.create_guidance(core.ADMIN, {"space_id": "space_work", "statement": "Work rule"})
    core.create_guidance(core.ADMIN, {"space_id": "space_personal", "statement": "Personal rule"})
    result = client.get("/api/v2/subjects", headers=headers)
    assert result.status_code == 200
    assert [row["id"] for row in result.json()["subjects"]] == [work["id"]]
    assert (
        client.get("/api/v2/guidance", headers=headers).json()["guidance"][0]["statement"]
        == "Work rule"
    )
    assert client.get("/api/v2/context?session_id=review", headers=headers).status_code == 200
    assert (
        client.get("/api/v2/subjects?space_id=space_personal", headers=headers).status_code == 404
    )
    assert (
        client.put(
            "/api/v2/context",
            headers=headers,
            json={"session_id": "review", "space_id": "space_personal"},
        ).status_code
        == 404
    )


@pytest.mark.parametrize("scopes", [["memories:read", "memories:write"], ["admin"]])
def test_bearer_cannot_mutate_global_categories_without_grants(client, scopes, monkeypatch):
    monkeypatch.setitem(settings.__dict__, "allow_legacy_api", False)
    _, value = create_api_key(name="ungranted", actor="ungranted", description=None, scopes=scopes)
    headers = {"Authorization": "Bearer " + value}
    empty_category = categories.create_category(name="Unused owner category")
    assert (
        client.post(
            "/api/v1/categories", headers=headers, json={"name": "Agent global category"}
        ).status_code
        == 403
    )
    assert (
        client.patch(
            "/api/v1/categories/cat_facts", headers=headers, json={"name": "Renamed by agent"}
        ).status_code
        == 403
    )
    assert (
        client.delete("/api/v1/categories/" + empty_category["id"], headers=headers).status_code
        == 403
    )
    assert categories.get_category("cat_facts")["name"] == "facts"
    assert categories.get_category(empty_category["id"]) is not None


def test_category_catalogue_does_not_expose_global_counts(client, monkeypatch):
    monkeypatch.setitem(settings.__dict__, "allow_legacy_api", False)
    core.create_memory(
        core.ADMIN,
        {"title": "Hidden example", "body": "Private content", "space_id": "space_personal"},
        "security-review-hidden",
    )
    _, value = create_api_key(
        name="reader", actor="reader", description=None, scopes=["memories:read"]
    )
    headers = {"Authorization": "Bearer " + value}
    response = client.get("/api/v1/categories", headers=headers)
    assert response.status_code == 200
    assert response.json()
    assert all("memory_count" not in row for row in response.json())
    assert client.get("/api/v1/categories/cat_facts", headers=headers).status_code == 200
    assert "memory_count" not in client.get("/api/v1/categories/cat_facts", headers=headers).json()


def test_dashboard_category_mutations_require_admin_and_csrf(client):
    uid = auth_repo.create_dashboard_user("category-owner", "unused-test-hash")
    client.cookies.set(settings.session_cookie_name, create_session_value(uid))
    assert client.post("/api/v1/categories", json={"name": "Owner category"}).status_code == 403
    csrf = dashboard_csrf_headers(client)
    response = client.post("/api/v1/categories", headers=csrf, json={"name": "Owner category"})
    assert response.status_code == 201
    category_id = response.json()["id"]
    assert (
        client.patch(
            "/api/v1/categories/" + category_id, headers=csrf, json={"name": "Owner renamed"}
        ).status_code
        == 200
    )
    assert client.delete("/api/v1/categories/" + category_id, headers=csrf).status_code == 204
    nonadmin = auth_repo.create_dashboard_user("ordinary-user", "unused-test-hash", is_admin=False)
    client.cookies.set(settings.session_cookie_name, create_session_value(nonadmin))
    assert (
        client.post(
            "/api/v1/categories", headers=csrf, json={"name": "Nonadmin category"}
        ).status_code
        == 403
    )
