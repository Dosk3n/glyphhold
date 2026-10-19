"""Verify diagnostics observe unchanged retrieval and keep private data isolated."""

import json
import sys

import pytest

from app.config import settings
from app.storage.db import connection
from app.v2 import core
from scripts.diagnose_prefetch import fixture, memory, trace_recall


def test_trace_agrees_with_core_and_does_not_export_bodies():
    original = settings.db_path
    previous = sys.getprofile()
    with fixture([memory("person", "Jess", "PRIVATE-PASSAGE-NEVER-REPORT")]) as (p, ids):
        expected = core.search(p, "Jess", recall=True, limit=5, max_chars=2400)
        observed = trace_recall(p, ids, "Jess", ["person"])
        assert [ids[k] for k in observed["returned"]] == [r["id"] for r in expected["results"]]
        assert observed["character_count"] == expected["character_count"]
        assert observed["targets"][0]["lexical_candidate"]
        assert "PRIVATE-PASSAGE-NEVER-REPORT" not in json.dumps(observed)
    assert sys.getprofile() == previous
    assert settings.db_path == original


def test_trace_and_fixture_restore_state_after_search_error():
    original = settings.db_path
    previous = sys.getprofile()
    with (
        pytest.raises(core.SpaceError),
        fixture([memory("person", "Jess", "Fiancée")]) as (p, ids),
    ):
        trace_recall(p, ids, "Jess", space_id="space_nonexistent")
    assert sys.getprofile() == previous
    assert settings.db_path == original


def test_memory_snapshot_ignores_secret_tables_and_supports_generated_columns():
    with fixture([memory("person", "Jess", "Fiancée")]), connection() as c:
        snapshot = {
            t: [dict(row) for row in c.execute("SELECT * FROM " + t)]
            for t in ["memories", "memory_categories"]
        }
    snapshot["secrets"] = [{"value": "MUST-NOT-IMPORT"}]
    with fixture(snapshot=snapshot) as (p, ids):
        with connection() as c:
            assert c.execute("SELECT count(*) FROM secrets").fetchone()[0] == 0
        result = trace_recall(p, ids, "Jess")
        assert len(result["returned"]) == 1


def test_diagnostics_are_repeatable():
    results = []
    for _ in range(2):
        with fixture([memory("person", "Jess", "Fiancée")]) as (p, ids):
            results.append(trace_recall(p, ids, "Jess", ["person"]))
    assert results[0] == results[1]
