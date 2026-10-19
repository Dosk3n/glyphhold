"""Observe installed Hermes pure helpers in isolation, with no model/service calls.

Reads the specified trusted Hermes source and executes only three selected functions.
Manager, text flattening and trivial-prompt dependencies are stubs: this tests input
forwarding and sidecar substitution, not Hermes's full turn loop or trivial filtering.
"""

import argparse
import ast
import contextlib
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace


def probe(source_path):
    source = source_path.read_text()
    names = {"_memory_query_text", "_memory_turn_start_and_prefetch", "substitute_api_content"}
    functions = [
        n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name in names
    ]
    if {n.name for n in functions} != names:
        raise ValueError("Installed Hermes does not expose expected helper functions")
    module = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            *functions,
        ],
        type_ignores=[],
    )
    namespace = {
        "suppress": contextlib.suppress,
        "flatten_message_text": lambda text: text if isinstance(text, str) else "",
        "is_trivial_prompt": lambda text: not text.strip(),
    }
    # This diagnostic deliberately executes selected functions from trusted installed source.
    exec(compile(ast.fix_missing_locations(module), str(source_path), "exec"), namespace)  # noqa: S102

    class Manager:
        def __init__(self):
            self.queries = []

        def on_turn_start(self, *args, **kwargs):
            pass

        def prefetch_all(self, query, **kwargs):
            self.queries.append(query)
            return "context:" + query

        def describe_recall(self):
            return ""

    manager = Manager()
    agent = SimpleNamespace(
        _memory_manager=manager,
        _user_turn_count=1,
        session_id="offline",
        _emit_status=lambda text: None,
        conversation_history=[{"role": "user", "content": "Which server runs Hermes?"}],
    )
    for query in ["Which server runs Hermes?", "And its address?", "Now tell me about Jess."]:
        namespace["_memory_turn_start_and_prefetch"](agent, query)
    old = {
        "role": "user",
        "content": "Old question",
        "api_content": "Old question\nOLD-INJECTED-MEMORY",
    }
    namespace["substitute_api_content"](old)
    return {
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "selected_functions": sorted(names),
        "forwarded_queries": manager.queries,
        "followup_includes_prior_question": manager.queries[1] != "And its address?",
        "old_sidecar_preserved": old["content"].endswith("OLD-INJECTED-MEMORY"),
        "scope": __doc__.strip(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    print(json.dumps(probe(args.source), indent=2))
