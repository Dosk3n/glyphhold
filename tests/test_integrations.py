from __future__ import annotations

import json
from typing import Any

from app.integrations.client import GlyphHoldClient
from app.integrations.hermes import HermesGlyphHoldProvider
from app.integrations.nexus import NexusGlyphHoldToolPack


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


def test_hermes_provider_returns_prefetched_memories() -> None:
    class FakeClient:
        def prefetch(self, *, message: str, agent: str | None = None) -> dict[str, Any]:
            assert message == "need project context"
            assert agent == "hermes"
            return {"memories": [{"id": "mem_1", "title": "Project"}]}

    provider = HermesGlyphHoldProvider(FakeClient())

    assert provider.prefetch_context("need project context") == [
        {"id": "mem_1", "title": "Project"}
    ]


def test_nexus_tool_pack_exposes_search_and_secret_tools() -> None:
    class FakeClient:
        def search_memories(self, *, query: str, limit: int = 10) -> dict[str, Any]:
            return {"query": query, "limit": limit}

        def reveal_secret(self, name: str, *, purpose: str | None = None) -> dict[str, Any]:
            return {"name": name, "purpose": purpose}

    tool_pack = NexusGlyphHoldToolPack(FakeClient())
    tools = tool_pack.tools()

    assert sorted(tools) == ["glyphhold_reveal_secret", "glyphhold_search_memories"]
    assert tools["glyphhold_search_memories"]("alpha", limit=2) == {
        "query": "alpha",
        "limit": 2,
    }
    assert tools["glyphhold_reveal_secret"]("GLYPHHOLD_TOKEN", purpose="test") == {
        "name": "GLYPHHOLD_TOKEN",
        "purpose": "test",
    }
