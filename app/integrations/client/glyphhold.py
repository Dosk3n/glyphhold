from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, request


class GlyphHoldClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class GlyphHoldClient:
    base_url: str
    api_key: str
    timeout_seconds: float = 10.0

    def _url(self, path: str) -> str:
        normalized_base = self.base_url.rstrip("/")
        normalized_path = path if path.startswith("/") else f"/{path}"
        return f"{normalized_base}{normalized_path}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        body = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = request.Request(
            self._url(path),
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GlyphHoldClientError(f"Glyph Hold returned HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise GlyphHoldClientError(f"Could not connect to Glyph Hold: {exc.reason}") from exc

        if not response_body:
            return None
        return json.loads(response_body)

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/health")

    def list_categories(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v1/categories")

    def search_memories(
        self,
        *,
        query: str,
        category: str | None = None,
        limit: int = 10,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/memories/search",
            payload={
                "query": query,
                "category": category,
                "limit": limit,
                "include_archived": include_archived,
            },
        )

    def prefetch(
        self,
        *,
        message: str,
        agent: str | None = None,
        max_memories: int = 3,
        max_chars: int = 1200,
        max_tokens: int = 300,
        summaries_only: bool = True,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/agent/prefetch",
            payload={
                "agent": agent,
                "message": message,
                "max_memories": max_memories,
                "max_chars": max_chars,
                "max_tokens": max_tokens,
                "summaries_only": summaries_only,
            },
        )

    def reveal_secret(
        self,
        name: str,
        *,
        requesting_agent: str | None = None,
        tool: str | None = None,
        purpose: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v1/secrets/{name}/reveal",
            payload={
                "requesting_agent": requesting_agent,
                "tool": tool,
                "purpose": purpose,
            },
        )
