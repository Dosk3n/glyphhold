"""Read-only MCP tools backed by a disposable synthetic Glyph Hold fixture."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server.fastmcp import FastMCP

from app.v2 import core
from scripts.diagnose_prefetch import fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--space", default="space_personal")
    args = parser.parse_args()
    corpus = json.loads(args.corpus.read_text())
    with fixture(memories=corpus["memories"]) as (principal, _):
        server = FastMCP("Glyph Hold evaluation")

        @server.tool()
        def search_memories(query: str, broaden: bool = False, limit: int = 8) -> dict:
            """Search durable memory. Try shorter terms or synonyms if needed.

            Automatic recall is selective: missing context can still exist here.
            Broaden explicitly to search other permitted spaces.
            """
            return core.search(
                principal, query, space_id=args.space, broaden=broaden,
                limit=min(20, max(1, limit)), max_chars=16000,
            )

        @server.tool()
        def get_memory(memory_id: str) -> dict:
            """Read the complete record when an excerpt omits required information."""
            return core.get_memory(principal, memory_id)

        server.run()


if __name__ == "__main__":
    main()
