"""Small standard-library client shared by GH2 tool and native integrations."""

from __future__ import annotations

from dataclasses import replace
from urllib.parse import quote, urlencode

from glyphhold_client.client import GlyphHoldClient


class GlyphHoldV2Client(GlyphHoldClient):
    def _request(self, method, path, *, payload=None):
        client = (
            replace(self, timeout_seconds=max(self.timeout_seconds, 90.0))
            if path.startswith("/api/v2/secrets")
            else self
        )
        return GlyphHoldClient._request(client, method, path, payload=payload)

    def capabilities(self):
        return self._request("GET", "/api/v2/capabilities")

    def list_spaces(self):
        return self._request("GET", "/api/v2/spaces")

    def recall(
        self,
        query: str,
        *,
        space_id: str | None = None,
        broaden: bool = False,
        limit: int = 5,
        max_chars: int = 2400,
        session_id: str | None = None,
    ):
        return self._request(
            "POST",
            "/api/v2/recall",
            payload={
                "query": query,
                "space_id": space_id,
                "broaden": broaden,
                "limit": limit,
                "max_chars": max_chars,
                "session_id": session_id,
            },
        )

    def search_memories(
        self,
        *,
        query: str,
        space_id: str | None = None,
        broaden: bool = False,
        limit: int = 10,
        max_chars: int = 12000,
        session_id: str | None = None,
    ):
        return self._request(
            "POST",
            "/api/v2/search",
            payload={
                "query": query,
                "space_id": space_id,
                "broaden": broaden,
                "limit": limit,
                "max_chars": max_chars,
                "session_id": session_id,
            },
        )

    def prefetch(
        self,
        *,
        message: str,
        space_id: str | None = None,
        max_memories: int = 5,
        max_chars: int = 2400,
        **_,
    ):
        return self.recall(message, space_id=space_id, limit=max_memories, max_chars=max_chars)

    def get_memory(self, memory_id: str):
        return self._request("GET", "/api/v2/memories/" + quote(memory_id, safe=""))

    def create_memory(self, *, idempotency_key: str, **fields):
        return self._request(
            "POST", "/api/v2/memories", payload={**fields, "idempotency_key": idempotency_key}
        )

    def update_memory(self, memory_id: str, *, expected_version: int, **fields):
        return self._request(
            "PATCH",
            "/api/v2/memories/" + quote(memory_id, safe=""),
            payload={**fields, "expected_version": expected_version},
        )

    def revisions(self, memory_id: str):
        return self._request("GET", "/api/v2/memories/" + quote(memory_id, safe="") + "/revisions")

    def restore(self, memory_id: str, revision_id: str, *, expected_version: int):
        return self._request(
            "POST",
            "/api/v2/memories/" + quote(memory_id, safe="") + "/restore",
            payload={"revision_id": revision_id, "expected_version": expected_version},
        )

    def guidance(self, space_id: str | None = None):
        query = "?" + urlencode({"space_id": space_id}) if space_id else ""
        return self._request("GET", "/api/v2/guidance" + query)

    def create_secret(
        self,
        *,
        name: str,
        value: str,
        space_id: str,
        description: str | None = None,
        value_type: str = "text",
    ):
        return self._request(
            "POST",
            "/api/v2/secrets",
            payload={
                "name": name,
                "value": value,
                "space_id": space_id,
                "description": description,
                "value_type": value_type,
            },
        )

    def search_secrets(self, *, query: str = "", space_id: str | None = None):
        params = {"query": query}
        if space_id:
            params["space_id"] = space_id
        return self._request("GET", "/api/v2/secrets?" + urlencode(params))

    def reveal_secret(self, name: str, *, space_id: str | None = None, **_):
        query = "?" + urlencode({"space_id": space_id}) if space_id else ""
        return self._request(
            "POST", "/api/v2/secrets/" + quote(name, safe="") + "/reveal" + query, payload={}
        )

    def list_memories(
        self,
        *,
        space_id: str | None = None,
        include_archived: bool = False,
        limit: int = 100,
        offset: int = 0,
    ):
        params = {
            "include_archived": str(include_archived).lower(),
            "limit": limit,
            "offset": offset,
        }
        if space_id:
            params["space_id"] = space_id
        return self._request("GET", "/api/v2/memories?" + urlencode(params))

    def context(self, session_id: str):
        return self._request("GET", "/api/v2/context?" + urlencode({"session_id": session_id}))

    def set_context(self, session_id: str, space_id: str):
        return self._request(
            "PUT", "/api/v2/context", payload={"session_id": session_id, "space_id": space_id}
        )

    def archive_memory(self, memory_id: str, *, expected_version: int):
        return self.update_memory(memory_id, expected_version=expected_version, archived=True)

    def move_memory(self, memory_id: str, space_id: str, *, expected_version: int):
        return self._request(
            "POST",
            "/api/v2/memories/" + quote(memory_id, safe="") + "/move",
            payload={"space_id": space_id, "expected_version": expected_version},
        )
