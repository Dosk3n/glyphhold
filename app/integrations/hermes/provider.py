from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class PrefetchClient(Protocol):
    def prefetch(self, *, message: str, agent: str | None = None) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class HermesGlyphHoldProvider:
    client: PrefetchClient
    agent_name: str = "hermes"

    def prefetch_context(self, message: str) -> list[dict[str, Any]]:
        result = self.client.prefetch(message=message, agent=self.agent_name)
        return list(result.get("memories", []))
