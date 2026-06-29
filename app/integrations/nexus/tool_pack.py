from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol


class NexusClient(Protocol):
    def search_memories(self, *, query: str, limit: int = 10) -> dict[str, Any]:
        ...

    def reveal_secret(self, name: str, *, purpose: str | None = None) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class NexusGlyphHoldToolPack:
    client: NexusClient

    def tools(self) -> dict[str, Callable[..., Any]]:
        return {
            "glyphhold_search_memories": self.search_memories,
            "glyphhold_reveal_secret": self.reveal_secret,
        }

    def search_memories(self, query: str, limit: int = 10) -> dict[str, Any]:
        return self.client.search_memories(query=query, limit=limit)

    def reveal_secret(self, name: str, purpose: str | None = None) -> dict[str, Any]:
        return self.client.reveal_secret(name, purpose=purpose)
