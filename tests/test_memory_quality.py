from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.storage.repositories import categories, memories
from tests.conftest import make_api_key_headers


def memory_headers() -> dict[str, str]:
    return make_api_key_headers(
        scopes=["memories:read", "memories:write"],
        actor="memory-quality-agent",
    )


def create_memory(client: TestClient, headers: dict[str, str], **overrides) -> dict:
    payload = {
        "category_id": "cat_people",
        "title": "Sample user profile",
        "summary": "Stable profile information about a sample user.",
        "body": "The sample user prefers concise answers and this profile stores stable context.",
        "tags": ["Person", " profile ", "PERSON"],
        "confidence": 5,
        "auto_prefetch_level": "normal",
    }
    payload.update(overrides)
    response = client.post("/api/v1/memories", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_tags_are_normalized_exactly_and_nullable_fields_can_be_cleared(client: TestClient) -> None:
    headers = memory_headers()
    memory = create_memory(client, headers)
    assert json.loads(memory["tags_json"]) == ["person", "profile"]
    assert [item["id"] for item in memories.list_memories(tag="person")] == [memory["id"]]
    assert memories.list_memories(tag="son") == []

    updated = client.patch(
        f"/api/v1/memories/{memory['id']}",
        headers=headers,
        json={"summary": None, "source": None},
    )
    assert updated.status_code == 200
    assert updated.json()["summary"] is None
    assert updated.json()["source"] is None


def test_search_prefers_all_terms_and_prepare_write_returns_guidance(client: TestClient) -> None:
    headers = memory_headers()
    exact = create_memory(
        client, headers, title="Application server deployment", tags=["server", "docker"]
    )
    create_memory(client, headers, title="Application profile", body="General information.", tags=["app"])

    search = client.post(
        "/api/v1/memories/search",
        headers=headers,
        json={"query": "application server deployment", "limit": 10},
    )
    assert search.status_code == 200
    assert search.json()["results"][0]["id"] == exact["id"]

    prepared = client.post(
        "/api/v1/memories/prepare-write",
        headers=headers,
        json={
            "category": "people",
            "title": "Application server deployment",
            "body": "The sample user prefers concise answers and this profile stores stable context.",
            "tags": ["server"],
        },
    )
    assert prepared.status_code == 200
    assert prepared.json()["likely_duplicates"]
    assert "server" in prepared.json()["suggested_tags"]

    prepared_by_category_id = client.post(
        "/api/v1/memories/prepare-write",
        headers=headers,
        json={
            "category": "cat_people",
            "title": "Application server deployment",
            "body": "The sample user prefers concise answers and this profile stores stable context.",
            "tags": ["server"],
        },
    )
    assert prepared_by_category_id.status_code == 200
    reasons = prepared_by_category_id.json()["likely_duplicates"][0]["match_reasons"]
    assert "category: cat_people" in reasons


def test_prefetch_honors_category_pinned_body_and_incremental_budget(client: TestClient) -> None:
    headers = memory_headers()
    excluded = create_memory(
        client,
        headers,
        category_id="cat_temporary",
        title="Temporary launch code",
        summary="temporary launch details",
        body="temporary launch details",
        auto_prefetch_level="high",
    )
    pinned = create_memory(
        client,
        headers,
        title="Always available preference",
        summary="Use concise technical answers.",
        body="Use concise technical answers and preserve API compatibility.",
        auto_prefetch_level="pinned",
    )
    create_memory(
        client,
        headers,
        title="Deployment context one",
        summary="Deployment context with enough text to consume part of the available token budget.",
        body="Deployment context one body.",
        auto_prefetch_level="high",
    )
    create_memory(
        client,
        headers,
        title="Deployment context two",
        summary="Deployment context with another block of text that should not clear prior selections.",
        body="Deployment context two body.",
        auto_prefetch_level="high",
    )

    prefetch = client.post(
        "/api/v1/agent/prefetch",
        headers=headers,
        json={"message": "temporary launch deployment context", "max_tokens": 35, "max_chars": 1200},
    )
    assert prefetch.status_code == 200
    selected_ids = [item["id"] for item in prefetch.json()["memories"]]
    assert excluded["id"] not in selected_ids
    assert pinned["id"] in selected_ids
    assert selected_ids
    assert prefetch.json()["estimated_tokens"] <= 35

    with_body = client.post(
        "/api/v1/agent/prefetch",
        headers=headers,
        json={
            "message": "always available preference",
            "summaries_only": False,
            "max_tokens": 100,
            "max_chars": 1200,
        },
    )
    assert with_body.status_code == 200
    assert with_body.json()["memories"][0]["body"].startswith("Use concise")


def test_category_agent_permissions_are_enforced_without_affecting_dashboard(client: TestClient) -> None:
    headers = memory_headers()
    category = categories.create_category(
        name="admin-only",
        agent_can_create=False,
        agent_can_write=False,
    )
    denied = client.post(
        "/api/v1/memories",
        headers=headers,
        json={"category_id": category["id"], "title": "Denied", "body": "Denied"},
    )
    assert denied.status_code == 403
    assert "cannot create" in denied.json()["detail"]
