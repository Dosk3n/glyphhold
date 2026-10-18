import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.api import health
from app.config import settings
from app.core.rate_limit import FailureRateLimiter
from tests.conftest import dashboard_csrf_headers, make_api_key_headers


@pytest.fixture
def set_setting():
    originals = {}

    def update(name, value):
        originals.setdefault(name, getattr(settings, name))
        object.__setattr__(settings, name, value)

    try:
        yield update
    finally:
        for name, value in originals.items():
            object.__setattr__(settings, name, value)


def test_rotating_unknown_usernames_share_an_ip_login_budget(client, set_setting):
    csrf = dashboard_csrf_headers(client)
    assert client.post(
        "/dashboard/api/setup",
        headers=csrf,
        json={"username": "admin", "password": "correct horse battery staple", "confirm_password": "correct horse battery staple"},
    ).status_code == 200
    client.post("/dashboard/api/logout", headers=csrf)
    set_setting("dashboard_login_attempts", 2)

    for username in ("unknown-one", "unknown-two"):
        response = client.post("/dashboard/api/login", headers=csrf, json={"username": username, "password": "wrong"})
        assert response.status_code == 401
    blocked = client.post("/dashboard/api/login", headers=csrf, json={"username": "unknown-three", "password": "wrong"})
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0


@pytest.mark.parametrize("invalid_headers", [{}, {"Authorization": "Basic invalid"}, {"Authorization": "Bearer"}])
def test_v2_missing_or_malformed_auth_is_limited_without_blocking_valid_key(client, set_setting, invalid_headers):
    headers = make_api_key_headers(scopes=["memories:read"])
    set_setting("invalid_api_key_attempts", 2)
    assert client.get("/api/v2/spaces", headers=invalid_headers).status_code == 401
    assert client.get("/api/v2/spaces", headers=invalid_headers).status_code == 401
    assert client.get("/api/v2/spaces", headers=invalid_headers).status_code == 429
    assert client.get("/api/v2/spaces", headers=headers).status_code == 200


def test_failure_limiter_bounds_and_expires_inactive_buckets(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("app.core.rate_limit.time.monotonic", lambda: now[0])
    limiter = FailureRateLimiter(max_keys=3)
    for index in range(10):
        limiter.add_failure(f"attacker-{index}", window_seconds=60)
        assert len(limiter._attempts) <= 3
    assert limiter.retry_after("attacker-9", limit=1, window_seconds=60) == 60
    now[0] += 61
    assert limiter.retry_after("new-client", limit=1, window_seconds=60) == 0
    assert not limiter._attempts


def test_failure_limiter_checks_do_not_create_empty_buckets():
    limiter = FailureRateLimiter(max_keys=3)
    for index in range(100):
        assert limiter.retry_after(f"unused-{index}", limit=1, window_seconds=60) == 0
    assert not limiter._attempts


def test_health_snapshot_coalesces_simultaneous_integrity_scans(monkeypatch):
    started, finish = threading.Event(), threading.Event()
    scans = []

    def integrity_check():
        scans.append(1)
        started.set()
        assert finish.wait(timeout=5)
        return True

    monkeypatch.setattr(health, "database_ok", integrity_check)
    monkeypatch.setattr(health, "current_schema_version", lambda: 6)
    snapshot = health.HealthSnapshot()
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(snapshot.read) for _ in range(8)]
        assert started.wait(timeout=5)
        finish.set()
        results = [future.result(timeout=5) for future in futures]
    assert len(scans) == 1
    assert all(result["status"] == "ok" for result in results)


def test_health_cache_refresh_detects_failure_and_returns_503(client, monkeypatch):
    now, checks, healthy = [100.0], [], [True]
    monkeypatch.setattr(health.time, "monotonic", lambda: now[0])

    def integrity_check():
        checks.append(1)
        return healthy[0]

    monkeypatch.setattr(health, "database_ok", integrity_check)
    client.app.state.health_snapshot = health.HealthSnapshot(interval=60)
    assert client.get("/api/v1/health").status_code == 200
    healthy[0] = False
    now[0] += 59
    assert client.get("/api/v1/health").status_code == 200
    assert len(checks) == 1
    now[0] += 2
    response = client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json()["database"] == "error"
    assert response.json()["schema_version"] is None
    assert len(checks) == 2
    assert client.get("/api/v1/health").status_code == 503
    assert len(checks) == 2


@pytest.mark.parametrize("enabled", [False, True])
def test_api_documentation_requires_explicit_opt_in(client_factory, set_setting, enabled):
    set_setting("expose_api_docs", enabled)
    client = client_factory()
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == (200 if enabled else 404)
