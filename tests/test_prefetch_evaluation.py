"""Safety/reproducibility checks for the evaluation harness, not quality targets."""

import json
from pathlib import Path

import pytest

from app.config import settings
from scripts.evaluate_prefetch import evaluate


@pytest.fixture
def restore_settings():
    original = settings.db_path
    try:
        yield
    finally:
        object.__setattr__(settings, "db_path", original)


def test_offline_evaluation_is_isolated_and_repeatable(tmp_path, restore_settings):
    sentinel = tmp_path / "must-not-open.sqlite"
    sentinel.write_bytes(b"Existing database must remain untouched")
    object.__setattr__(settings, "db_path", sentinel)
    corpus = json.loads(Path("evaluations/prefetch/corpus.json").read_text())
    first = evaluate(corpus)
    second = evaluate(corpus)
    assert settings.db_path == sentinel
    assert sentinel.read_bytes() == b"Existing database must remain untouched"
    assert first["synthetic_only"]
    assert len(first["measurements"]) == len(corpus["cases"]) * 5
    assert first["diagnostics"]["restricted_broaden_respects_grants"]
    for result in (first, second):
        for summary in result["summary"].values():
            summary.pop("median_local_retrieval_ms")
        for measurement in result["measurements"]:
            measurement.pop("retrieval_ms")
    assert first == second


def test_evaluation_restores_database_setting_after_invalid_fixture(tmp_path, restore_settings):
    original = tmp_path / "existing.sqlite"
    object.__setattr__(settings, "db_path", original)
    with pytest.raises(KeyError):
        evaluate({"memories": [{"title": "Missing fixture key"}]})
    assert settings.db_path == original
    assert not original.exists()
