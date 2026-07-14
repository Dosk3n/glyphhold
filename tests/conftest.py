from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.core.auth import create_api_key


@pytest.fixture
def client_factory(tmp_path: Path) -> Callable[..., TestClient]:
    counter = 0

    def make_client(*, encryption_key: str | None = None) -> TestClient:
        nonlocal counter
        counter += 1
        object.__setattr__(settings, "db_path", tmp_path / f"glyphhold-{counter}.sqlite")
        object.__setattr__(settings, "encryption_key", encryption_key)
        object.__setattr__(settings, "log_format", "json")

        from app.main import create_app

        return TestClient(create_app())

    return make_client


@pytest.fixture
def client(client_factory: Callable[..., TestClient]) -> TestClient:
    return client_factory()


@pytest.fixture
def secrets_client(client_factory: Callable[..., TestClient]) -> TestClient:
    return client_factory(encryption_key="test-encryption-key")


def make_api_key_headers(*, scopes: list[str], actor: str = "test-agent") -> dict[str, str]:
    _, api_key = create_api_key(
        name=f"{actor} key",
        actor=actor,
        description="test key",
        scopes=scopes,
    )
    return {"Authorization": f"Bearer {api_key}"}


def dashboard_csrf_headers(client: TestClient) -> dict[str, str]:
    if not client.cookies.get("glyphhold_csrf"):
        response = client.get("/dashboard/api/session")
        assert response.status_code == 200
    token = client.cookies.get("glyphhold_csrf")
    assert token
    return {"X-CSRF-Token": token}
