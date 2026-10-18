"""Local sibling-adapter conformance against the actual FastAPI app.

Each adapter is maintained in its own repository. Source-only CI can skip this
cross-repository test; the GH2 local release rehearsal must run it.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from app.core.auth import create_api_key
from app.v2 import core

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    if not path.exists():
        pytest.skip("Sibling integration checkout unavailable")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class URLResponse:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, size=-1):
        return self.response.content if size < 0 else self.response.content[:size]


def test_hermes_native_prefetch_and_tool_write_against_gh2(client, monkeypatch):
    plugin = load(ROOT.parent / "glyphhold-hermes-memory" / "__init__.py", "gh2_hermes_conformance")
    kid, key = create_api_key(
        name="Hermes work",
        actor="hermes",
        description=None,
        scopes=["memories:read", "memories:write"],
    )
    core.set_connection(
        core.ADMIN,
        kid,
        {
            "default_space_id": "space_work",
            "grants": [
                {"space_id": "space_work", "can_read": True, "can_write": True},
                {"space_id": "space_personal", "can_read": True, "can_write": True},
            ],
        },
    )

    def bridge(req, **kwargs):
        response = client.request(
            req.method,
            req.full_url.replace("http://gh", ""),
            headers=dict(req.header_items()),
            content=req.data,
        )
        assert response.status_code < 400, response.text
        return URLResponse(response)

    monkeypatch.setattr(plugin, "urlopen", bridge)
    provider = plugin.GlyphHoldMemoryProvider()
    provider.initialize(
        "chat",
        config={"GLYPHHOLD_URL": "http://gh", "GLYPHHOLD_API_KEY": key},
        agent_identity="work",
    )
    created = json.loads(
        provider.handle_tool_call(
            "create_memory",
            {
                "title": "Server route",
                "body": "Use SSH on work host",
                "idempotency_key": "hermes-one",
            },
        )
    )
    assert created["space_id"] == "space_work"
    recalled = provider.prefetch("server")
    assert created["id"] in recalled and '"version": 1' in recalled
    updated = json.loads(
        provider.handle_tool_call(
            "update_memory",
            {"memory_id": created["id"], "expected_version": 1, "body": "Use verified host"},
        )
    )
    assert updated["version"] == 2

    provider.handle_tool_call("set_memory_context", {"space_id": "space_personal"})
    personal = json.loads(
        provider.handle_tool_call(
            "create_memory",
            {
                "title": "Personal route",
                "body": "Personal fact",
                "idempotency_key": "hermes-personal",
            },
        )
    )
    assert personal["space_id"] == "space_personal"
    provider.on_session_switch("new-chat", parent_session_id="chat", reset=True)
    fresh = json.loads(
        provider.handle_tool_call(
            "create_memory",
            {
                "title": "New conversation",
                "body": "Work fact",
                "idempotency_key": "hermes-new-chat",
            },
        )
    )
    assert fresh["space_id"] == "space_work"
    provider.on_session_switch("chat")
    resumed = json.loads(provider.handle_tool_call("get_memory_context", {}))
    assert resumed["space_id"] == "space_personal"


def test_direct_mcp_async_client_against_gh2(client):
    plugin = load(
        ROOT.parent / "glyphhold-mcp" / "glyphhold_mcp" / "client.py", "gh2_mcp_conformance"
    )
    kid, key = create_api_key(
        name="MCP personal",
        actor="codex",
        description=None,
        scopes=["memories:read", "memories:write"],
    )
    core.set_connection(
        core.ADMIN,
        kid,
        {
            "default_space_id": "space_personal",
            "grants": [{"space_id": "space_personal", "can_read": True, "can_write": True}],
        },
    )

    async def run():
        adapter = plugin.GlyphHoldClient(
            base_url="http://gh", api_key=key, transport=httpx.ASGITransport(app=client.app)
        )
        created = await adapter.create_memory(
            title="Jess preference", body="A recorded preference", idempotency_key="mcp-one"
        )
        assert created["space_id"] == "space_personal"
        recalled = await adapter.prefetch_memories(message="Jess")
        assert recalled["results"][0]["id"] == created["id"]
        changed = await adapter.update_memory(
            memory_id=created["id"], expected_version=1, body="Corrected preference"
        )
        assert changed["version"] == 2
        with pytest.raises(plugin.GlyphHoldError) as error:
            await adapter.update_memory(
                memory_id=created["id"], expected_version=1, body="Lost update"
            )
        assert error.value.status_code == 409

    asyncio.run(run())


def test_nexus_tools_against_gh2(client, monkeypatch):
    import importlib
    import sys
    import types

    sibling = ROOT.parent / "nexus-tools-glyphhold"
    if not sibling.is_dir():
        pytest.skip("Sibling Nexus checkout unavailable")
    registry = types.ModuleType("nexus.tool_registry")
    registry.register_tool = lambda **kwargs: lambda fn: fn
    monkeypatch.setitem(sys.modules, "nexus", types.ModuleType("nexus"))
    monkeypatch.setitem(sys.modules, "nexus.tool_registry", registry)
    monkeypatch.syspath_prepend(str(sibling))
    api = importlib.import_module("nexus_tools_glyphhold.api")
    transport = importlib.import_module("nexus_tools_glyphhold.client")
    kid, key = create_api_key(
        name="Nexus work",
        actor="nexus",
        description=None,
        scopes=["memories:read", "memories:write"],
    )
    core.set_connection(
        core.ADMIN,
        kid,
        {
            "default_space_id": "space_work",
            "grants": [{"space_id": "space_work", "can_read": True, "can_write": True}],
        },
    )

    def bridge(req, **kwargs):
        response = client.request(
            req.method,
            req.full_url.replace("http://gh", ""),
            headers=dict(req.header_items()),
            content=req.data,
        )
        assert response.status_code < 400, response.text
        return URLResponse(response)

    monkeypatch.setattr(transport.GlyphHoldClient, "_open", lambda self, req, **kwargs: bridge(req))
    monkeypatch.setattr(
        api, "get_client", lambda: transport.GlyphHoldClient(base_url="http://gh", api_key=key)
    )
    created = api.create_memory("Work server", "Use SSH", "nexus-one")
    recalled = api.prefetch_memories("server")
    assert recalled["results"][0]["id"] == created["id"]
    changed = api.update_memory(created["id"], 1, body="Use current SSH host")
    assert changed["version"] == 2
