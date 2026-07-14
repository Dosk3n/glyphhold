from __future__ import annotations

from fastapi.testclient import TestClient

from app.admin_cli import main, reset_password
from app.storage.repositories import auth as auth_repo
from tests.conftest import dashboard_csrf_headers


def _setup_dashboard(client: TestClient, password: str = "correct horse battery staple") -> None:
    response = client.post(
        "/dashboard/api/setup",
        json={
            "username": "admin",
            "password": password,
            "confirm_password": password,
        },
        headers=dashboard_csrf_headers(client),
    )
    assert response.status_code == 200


def test_reset_password_updates_existing_admin_login(client: TestClient) -> None:
    _setup_dashboard(client)
    client.post("/dashboard/api/logout", headers=dashboard_csrf_headers(client))

    username = reset_password(username="admin", password="new correct horse battery")
    assert username == "admin"

    old_login = client.post(
        "/dashboard/api/login",
        json={"username": "admin", "password": "correct horse battery staple"},
        headers=dashboard_csrf_headers(client),
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/dashboard/api/login",
        json={"username": "admin", "password": "new correct horse battery"},
        headers=dashboard_csrf_headers(client),
    )
    assert new_login.status_code == 200
    assert new_login.json()["user"]["username"] == "admin"


def test_reset_password_can_select_only_admin(client: TestClient) -> None:
    _setup_dashboard(client)

    username = reset_password(username=None, password="another correct horse")

    assert username == "admin"


def test_reset_password_requires_existing_admin(client: TestClient) -> None:
    assert auth_repo.list_admin_users() == []

    exit_code = main(["reset-password", "--password", "new correct horse battery"])

    assert exit_code == 1


def test_reset_password_rejects_short_password(client: TestClient) -> None:
    _setup_dashboard(client)

    exit_code = main(["reset-password", "--username", "admin", "--password", "short"])

    assert exit_code == 1
