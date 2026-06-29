from __future__ import annotations

import json
from typing import Any

from glyphhold_client import GlyphHoldClient


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_client_uses_public_api_and_bearer_auth(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["authorization"] = req.get_header("Authorization")
        captured["content_type"] = req.get_header("Content-type")
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse({"results": [{"id": "mem_1"}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    client = GlyphHoldClient("http://glyphhold:5995/", "gh_live_test", timeout_seconds=2)
    result = client.search_memories(query="alpha", limit=3)

    assert result == {"results": [{"id": "mem_1"}]}
    assert captured == {
        "url": "http://glyphhold:5995/api/v1/memories/search",
        "method": "POST",
        "authorization": "Bearer gh_live_test",
        "content_type": "application/json",
        "body": {
            "query": "alpha",
            "category": None,
            "limit": 3,
            "include_archived": False,
        },
        "timeout": 2,
    }


def test_client_prefetch_and_secret_reveal_paths(monkeypatch) -> None:
    captured = []

    def fake_urlopen(req, timeout):
        captured.append(
            {
                "url": req.full_url,
                "method": req.get_method(),
                "body": json.loads(req.data.decode("utf-8")),
            }
        )
        return FakeResponse({"ok": True})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    client = GlyphHoldClient("http://localhost:5995", "gh_live_test")

    assert client.prefetch(message="project context", agent="codex") == {"ok": True}
    assert client.reveal_secret("GLYPHHOLD_TOKEN", purpose="deploy") == {"ok": True}
    assert captured == [
        {
            "url": "http://localhost:5995/api/v1/agent/prefetch",
            "method": "POST",
            "body": {
                "agent": "codex",
                "message": "project context",
                "max_memories": 3,
                "max_chars": 1200,
                "max_tokens": 300,
                "summaries_only": True,
            },
        },
        {
            "url": "http://localhost:5995/api/v1/secrets/GLYPHHOLD_TOKEN/reveal",
            "method": "POST",
            "body": {
                "requesting_agent": None,
                "tool": None,
                "purpose": "deploy",
            },
        },
    ]


def test_client_memory_and_secret_write_helpers(monkeypatch) -> None:
    captured = []

    def fake_urlopen(req, timeout):
        captured.append(
            {
                "url": req.full_url,
                "method": req.get_method(),
                "body": json.loads(req.data.decode("utf-8")),
            }
        )
        return FakeResponse({"ok": True})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    client = GlyphHoldClient("http://localhost:5995", "gh_live_test")

    assert client.create_memory(
        category_id="cat_projects",
        title="Project fact",
        summary="Short summary",
        body="Longer body",
        tags=["project"],
        source="agent",
        confidence=4,
        auto_prefetch_level="high",
    ) == {"ok": True}
    assert client.create_secret(
        name="CUSTOM_API_KEY_HERE",
        value="secret-value",
        value_type="token",
        scope="deploy",
        allowed_agents=["codex"],
    ) == {"ok": True}
    assert client.reveal_env(scope="deploy", requesting_agent="codex", purpose="deployment") == {
        "ok": True
    }

    assert captured == [
        {
            "url": "http://localhost:5995/api/v1/memories",
            "method": "POST",
            "body": {
                "category_id": "cat_projects",
                "title": "Project fact",
                "summary": "Short summary",
                "body": "Longer body",
                "tags": ["project"],
                "metadata": {},
                "source": "agent",
                "confidence": 4,
                "auto_prefetch_level": "high",
            },
        },
        {
            "url": "http://localhost:5995/api/v1/secrets",
            "method": "POST",
            "body": {
                "name": "CUSTOM_API_KEY_HERE",
                "value": "secret-value",
                "description": None,
                "value_type": "token",
                "service": None,
                "host": None,
                "scope": "deploy",
                "tags": [],
                "allowed_agents": ["codex"],
                "allowed_tools": [],
            },
        },
        {
            "url": "http://localhost:5995/api/v1/secrets/env",
            "method": "POST",
            "body": {
                "scope": "deploy",
                "requesting_agent": "codex",
                "purpose": "deployment",
            },
        },
    ]
