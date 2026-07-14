from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from fastapi.testclient import TestClient

from app.admin_cli import reset_password
from app.config import settings
from app.storage.db import connection
from app.storage.repositories import events
from tests.conftest import dashboard_csrf_headers, make_api_key_headers


@contextmanager
def changed_setting(name: str, value: object) -> Iterator[None]:
    original = getattr(settings, name)
    object.__setattr__(settings, name, value)
    try:
        yield
    finally:
        object.__setattr__(settings, name, original)


def setup_dashboard(client: TestClient) -> None:
    response = client.post(
        "/dashboard/api/setup",
        headers=dashboard_csrf_headers(client),
        json={
            "username": "admin",
            "password": "correct horse battery staple",
            "confirm_password": "correct horse battery staple",
        },
    )
    assert response.status_code == 200


def test_dashboard_csrf_and_legacy_form_routes(client: TestClient) -> None:
    rejected = client.post(
        "/dashboard/api/setup",
        json={"username": "admin", "password": "long-enough-password", "confirm_password": "long-enough-password"},
    )
    assert rejected.status_code == 403
    assert "security token" in rejected.json()["detail"]

    legacy = client.post(
        "/setup",
        data={"username": "admin", "password": "long-enough-password"},
    )
    assert legacy.status_code == 405


def test_security_headers_cover_dashboard_and_sensitive_responses(client: TestClient) -> None:
    response = client.get("/dashboard")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "strict-transport-security" not in response.headers


def test_failed_dashboard_logins_are_rate_limited(client: TestClient) -> None:
    setup_dashboard(client)
    client.post("/dashboard/api/logout", headers=dashboard_csrf_headers(client))

    with changed_setting("dashboard_login_attempts", 2):
        with changed_setting("dashboard_login_window_seconds", 60):
            for _ in range(2):
                response = client.post(
                    "/dashboard/api/login",
                    headers=dashboard_csrf_headers(client),
                    json={"username": "admin", "password": "wrong-password"},
                )
                assert response.status_code == 401
            limited = client.post(
                "/dashboard/api/login",
                headers=dashboard_csrf_headers(client),
                json={"username": "admin", "password": "wrong-password"},
            )

    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0
    assert len(events.list_events(event_type="dashboard.login_failed")) == 2


def test_invalid_api_keys_are_limited_without_blocking_valid_keys(client: TestClient) -> None:
    valid_headers = make_api_key_headers(scopes=["memories:read"], actor="valid-agent")
    invalid_headers = {"Authorization": "Bearer gh_live_invalid"}

    with changed_setting("invalid_api_key_attempts", 2):
        with changed_setting("invalid_api_key_window_seconds", 60):
            for _ in range(2):
                response = client.get("/api/v1/categories", headers=invalid_headers)
                assert response.status_code == 401
            limited = client.get("/api/v1/categories", headers=invalid_headers)
            valid = client.get("/api/v1/categories", headers=valid_headers)

    assert limited.status_code == 429
    assert valid.status_code == 200


def test_request_and_memory_limits_return_actionable_errors(client: TestClient) -> None:
    headers = make_api_key_headers(scopes=["memories:write"], actor="writer")
    with changed_setting("max_request_bytes", 100):
        oversized_request = client.post(
            "/api/v1/memories",
            headers=headers,
            json={"category_id": "cat_people", "title": "Profile", "body": "x" * 200},
        )
    assert oversized_request.status_code == 413
    assert "split it across multiple memories" in oversized_request.json()["detail"]

    with changed_setting("max_memory_body_chars", 10):
        oversized_memory = client.post(
            "/api/v1/memories",
            headers=headers,
            json={"category_id": "cat_people", "title": "Profile", "body": "x" * 11},
        )
    assert oversized_memory.status_code == 422
    assert "split it into multiple focused memories" in oversized_memory.text


def test_password_reset_invalidates_existing_dashboard_session(client: TestClient) -> None:
    setup_dashboard(client)
    assert client.get("/dashboard/api/session").json()["user"]["username"] == "admin"

    reset_password(username="admin", password="new correct horse battery")

    assert client.get("/dashboard/api/session").json()["user"] is None


def test_event_retention_removes_old_and_excess_rows(client: TestClient) -> None:
    for index in range(4):
        events.record_event(
            request_id=f"req_{index}",
            event_type="retention.test",
            success=True,
        )
    with connection() as conn:
        conn.execute(
            "UPDATE event_log SET created_at = ? WHERE request_id = ?",
            ("2000-01-01T00:00:00.000Z", "req_0"),
        )

    with changed_setting("event_retention_days", 1):
        with changed_setting("max_event_rows", 2):
            deleted = events.prune_events()

    assert deleted == 2
    retained = events.list_events(event_type="retention.test", limit=10)
    assert len(retained) == 2
