from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.advanced import service, store
from app.advanced.codex import CodexRunner
from app.advanced.models import AdvancedSettings, Proposal, RunnerOutput
from app.advanced.schedule import next_occurrence
from app.advanced.worker import AdvancedWorker
from app.config import settings
from app.storage.migrations import apply_migrations
from app.v2 import core


@pytest.fixture
def advanced(tmp_path, monkeypatch):
    original_path = settings.db_path
    object.__setattr__(settings, "db_path", tmp_path / "advanced.sqlite")
    apply_migrations()
    core.ensure_schema()
    store.initialize()
    yield tmp_path
    object.__setattr__(settings, "db_path", original_path)


def enabled(**overrides):
    return store.save_settings(
        AdvancedSettings(enabled=True, space_ids=["space_personal"], **overrides)
    )


def fact(body="Jess is the owner's fiancée", space="space_personal", **extra):
    import uuid

    return core.create_memory(
        core.ADMIN, {"space_id": space, "title": "Jess", "body": body, **extra}, uuid.uuid4().hex
    )


def proposal(memory, **extra):
    return Proposal(
        operation="profile",
        space_id=memory["space_id"],
        title="Jess profile",
        body=memory["body"],
        source_refs=[{"id": memory["id"], "version": memory["version"]}],
        reason="The saved fact explicitly identifies the relationship",
        **extra,
    )


class FakeRunner:
    def __init__(self, output=None, callback=None):
        self.calls = 0
        self.output = output or RunnerOutput()
        self.callback = callback
        self.run_process = None
        self.login = {}

    async def execute(self, prompt, config, cancelled):
        self.calls += 1
        self.prompt = prompt
        if self.callback:
            self.callback()
        return self.output

    async def cancel_login(self):
        pass

    async def terminate(self, process):
        pass


def test_off_default_and_no_dispatch(advanced):
    assert store.settings()["enabled"] is False
    fact()
    runner = FakeRunner()
    assert asyncio.run(AdvancedWorker(runner).run_once()) is None
    assert runner.calls == 0
    with pytest.raises(ValueError, match="Enable"):
        store.enqueue()


def test_schedule_gap_fold_weekly_and_hourly():
    config = AdvancedSettings(frequency="daily", hour=1, minute=30).model_dump()
    # UK spring gap: 01:30 doesn't exist; advance to the first valid local minute, 02:00.
    assert next_occurrence(config, datetime(2026, 3, 29, 0, 0, tzinfo=UTC)) == datetime(
        2026, 3, 29, 1, 0, tzinfo=UTC
    )
    # UK autumn fold: after the first 01:30, do not run a second occurrence.
    assert next_occurrence(config, datetime(2026, 10, 25, 0, 40, tzinfo=UTC)) == datetime(
        2026, 10, 26, 1, 30, tzinfo=UTC
    )
    config.update(frequency="weekly", weekday=0, hour=9, minute=0)
    assert next_occurrence(config, datetime(2026, 10, 18, 12, tzinfo=UTC)) == datetime(
        2026, 10, 19, 8, tzinfo=UTC
    )
    config.update(frequency="hourly", minute=15)
    assert next_occurrence(config, datetime(2026, 10, 18, 12, 20, tzinfo=UTC)) == datetime(
        2026, 10, 18, 13, 15, tzinfo=UTC
    )


def test_changed_only_one_job_and_no_summary_feedback(advanced):
    enabled()
    memory = fact()
    runner = FakeRunner(RunnerOutput(proposals=[proposal(memory)]))
    worker = AdvancedWorker(runner)
    first = store.enqueue()
    assert store.enqueue()["id"] == first["id"]
    result = asyncio.run(worker.run_once())
    assert result["state"] == "completed"
    pending = store.list_proposals()[0]
    applied = service.decide(pending["id"], True)
    assert applied["state"] == "applied"
    assert service.decide(pending["id"], True)["state"] == "applied"
    records = core.list_memories(core.ADMIN, space_id="space_personal")
    assert len(records) == 2
    profile = next(item for item in records if item["record_type"] == "profile")
    assert profile["source_refs"] == [{"id": memory["id"], "version": 1}]
    store.enqueue()
    assert asyncio.run(worker.run_once())["state"] == "skipped"
    assert runner.calls == 1
    updated = core.update_memory(
        core.ADMIN, memory["id"], {"body": "Jess is the owner's fiancée and likes Italian food"}, 1
    )
    assert core.get_memory(core.ADMIN, profile["id"])["stale"]
    # New source version makes the next run actionable; summary itself does not trigger it.
    runner.output = RunnerOutput()
    store.enqueue()
    assert asyncio.run(worker.run_once())["state"] == "completed"
    assert updated["body"] in runner.prompt
    assert runner.calls == 2


def test_source_change_rejects_stale_proposal(advanced):
    enabled()
    memory = fact()
    store.enqueue()
    asyncio.run(AdvancedWorker(FakeRunner(RunnerOutput(proposals=[proposal(memory)]))).run_once())
    core.update_memory(core.ADMIN, memory["id"], {"body": "Corrected fact"}, 1)
    with pytest.raises(ValueError, match="changed"):
        service.decide(store.list_proposals()[0]["id"], True)
    assert len(core.list_memories(core.ADMIN, space_id="space_personal")) == 1


def test_disable_during_execution_cannot_stage_or_apply(advanced):
    enabled()
    memory = fact()
    store.enqueue()
    runner = FakeRunner(
        RunnerOutput(proposals=[proposal(memory)]),
        callback=lambda: store.save_settings(AdvancedSettings()),
    )
    assert asyncio.run(AdvancedWorker(runner).run_once())["state"] == "cancelled"
    assert store.list_proposals() == []


def test_outside_evidence_and_cross_space_rejected(advanced):
    enabled()
    personal = fact()
    work = fact("Work private information", "space_work")
    job = store.enqueue()
    job["evidence"] = [personal, work]
    invalid = Proposal.model_validate(
        proposal(personal).model_dump() | {"source_refs": [{"id": work["id"], "version": 1}]}
    )
    with pytest.raises(ValueError, match="across spaces"):
        service.validate_proposal(job, invalid)
    invalid = proposal(personal).model_copy(update={"space_id": "space_general"})
    with pytest.raises(ValueError, match="permitted"):
        service.validate_proposal(job, invalid)


def test_move_always_review_and_original_facts_preserved(advanced):
    store.save_settings(
        AdvancedSettings(
            enabled=True, space_ids=["space_personal", "space_work"], execution_policy="automatic"
        )
    )
    memory = fact()
    move = Proposal(
        operation="move",
        space_id="space_personal",
        destination_space_id="space_work",
        target_id=memory["id"],
        expected_version=1,
        source_refs=[{"id": memory["id"], "version": 1}],
        reason="Proposed placement based on explicit applicability",
    )
    store.enqueue()
    asyncio.run(AdvancedWorker(FakeRunner(RunnerOutput(proposals=[move]))).run_once())
    item = store.list_proposals()[0]
    assert item["state"] == "pending"
    assert core.get_memory(core.ADMIN, memory["id"])["space_id"] == "space_personal"
    service.decide(item["id"], True)
    assert core.get_memory(core.ADMIN, memory["id"])["space_id"] == "space_work"
    assert core.revisions(core.ADMIN, memory["id"])


def test_failed_run_pauses_and_explicit_resume(advanced):
    enabled()
    memory = fact()
    from app.advanced.codex import CodexError

    class FailingRunner(FakeRunner):
        async def execute(self, *args):
            raise CodexError("Subscription allowance unavailable")

    job = store.enqueue()
    result = asyncio.run(AdvancedWorker(FailingRunner()).run_once())
    assert result["state"] == "paused"
    assert store.settings()["paused_reason"]
    assert store.claim("another") is None
    resumed = store.resume(job["id"])
    assert resumed["id"] != job["id"]
    assert not store.settings()["paused_reason"]
    result = asyncio.run(AdvancedWorker(FakeRunner()).run_once())
    assert result["state"] == "completed"
    assert store.processed()[memory["id"]] == 1


def test_codex_isolated_cli_structured_result_no_api_fallback(advanced, monkeypatch):
    executable = advanced / "fake-codex"
    executable.write_text("""#!/usr/bin/env python3
import sys, json, os
from pathlib import Path
args = sys.argv[1:]
if args[:2] == ['login','status']:
    print('Logged in using ChatGPT')
    raise SystemExit(0)
assert 'OPENAI_API_KEY' not in os.environ
assert '--ignore-user-config' in args
assert '--ephemeral' in args
assert args[args.index('--sandbox')+1] == 'read-only'
assert 'shell_tool' in args and 'unified_exec' in args
assert args[args.index('--model')+1] == 'chosen-model'
assert 'model_reasoning_effort="low"' in args
schema = json.loads(Path(args[args.index('--output-schema')+1]).read_text())
assert set(schema['required']) == set(schema['properties'])
assert 'bounded test evidence' in sys.stdin.read()
Path(args[args.index('--output-last-message')+1]).write_text(json.dumps({'proposals': [], 'notes': 'Reviewed without changes'}))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':10,'output_tokens':5}}))
""")
    executable.chmod(0o700)
    monkeypatch.setenv("OPENAI_API_KEY", "must-never-be-used")
    runner = CodexRunner(advanced / "dedicated-auth", str(executable))
    config = AdvancedSettings(model="chosen-model").model_dump()
    result = asyncio.run(runner.execute("bounded test evidence", config, lambda: False))
    assert result.notes == "Reviewed without changes"
    assert runner.home != Path.home() / ".codex"
    assert runner.home.stat().st_mode & 0o777 == 0o700
    executable.write_text("#!/usr/bin/env python3\nprint('Logged in using API key')\n")
    assert not asyncio.run(runner.authentication())["authenticated"]


def test_confirmed_guidance_invalidates_pending_and_rechecks_sources(advanced):
    enabled()
    memory = fact()
    store.enqueue()
    asyncio.run(AdvancedWorker(FakeRunner(RunnerOutput(proposals=[proposal(memory)]))).run_once())
    pending = store.list_proposals()[0]
    core.create_guidance(
        core.ADMIN, {"space_id": "space_personal", "statement": "Jess is the owner's fiancée"}
    )
    with pytest.raises(ValueError, match="guidance changed"):
        service.decide(pending["id"], True)
    runner = FakeRunner()
    store.enqueue()
    assert asyncio.run(AdvancedWorker(runner).run_once())["state"] == "completed"
    assert "fiancée" in runner.prompt


def test_inactive_source_cannot_be_resurrected_in_profile(advanced):
    enabled()
    memory = fact()
    memory = core.update_memory(core.ADMIN, memory["id"], {"archived": True}, 1)
    job = store.enqueue()
    job["evidence"] = [memory]
    with pytest.raises(ValueError, match="Inactive sources"):
        service.validate_proposal(job, proposal(memory))


def test_backlog_bounded_and_initial_review_reset(advanced):
    enabled(batch_size=1)
    first = fact("First fact")
    second = fact("Second fact")
    runner = FakeRunner()
    worker = AdvancedWorker(runner)
    store.enqueue(full_review=True)
    assert asyncio.run(worker.run_once())["state"] == "completed"
    assert len(store.processed()) == 1
    store.enqueue()
    assert asyncio.run(worker.run_once())["state"] == "completed"
    assert set(store.processed()) == {first["id"], second["id"]}
    assert runner.calls == 2


def test_catalog_uses_app_server_metadata_without_model_turn(advanced, monkeypatch):
    monkeypatch.setattr("app.advanced.codex.time.monotonic", lambda: 100.0)
    executable = advanced / "catalog-codex"
    executable.write_text("""#!/usr/bin/env python3
import sys,json
assert sys.argv[1] == 'app-server'
for line in sys.stdin:
    request=json.loads(line)
    if request.get('method') == 'initialize':
        print(json.dumps({'id':1,'result':{}}),flush=True)
    elif request.get('method') == 'model/list':
        print(json.dumps({'id':2,'result':{'data':[{'id':'small','model':'small-model','displayName':'Small model','supportedReasoningEfforts':[{'reasoningEffort':'low'}]}]}}),flush=True)
    else:
        assert request.get('method') == 'initialized'
""")
    executable.chmod(0o700)
    runner = CodexRunner(advanced / "model-auth", str(executable))
    asyncio.run(runner.refresh_models())
    assert runner.models()[1] == {
        "id": "small-model",
        "label": "Small model",
        "reasoning_levels": ["low"],
    }


def test_job_scope_cannot_leak_moved_sources_through_stale_profiles(advanced):
    enabled()
    private = fact("Only-this-sensitive-detail belongs to a different scope")
    profile = core.create_memory(
        core.ADMIN,
        {
            "space_id": "space_personal",
            "title": "Old profile",
            "body": private["body"],
            "record_type": "profile",
            "source_refs": [{"id": private["id"], "version": 1}],
        },
        "old-profile",
    )
    core.update_memory(core.ADMIN, private["id"], {"space_id": "space_work"}, 1)
    fact("A new permitted personal fact")
    job = store.enqueue()
    evidence, _spaces = service.job_records(job)
    assert profile["id"] not in {item["id"] for item in evidence}
    assert "Only-this-sensitive-detail" not in str(evidence)


def test_available_usage_is_saved_in_run_history(advanced):
    enabled()
    fact()
    runner = FakeRunner()
    runner.last_usage = {"input_tokens": 120, "output_tokens": 40}
    store.enqueue()
    result = asyncio.run(AdvancedWorker(runner).run_once())
    assert result["result"]["usage"] == runner.last_usage


def test_review_badge_counts_all_pending_approvals_and_queue_prioritizes_them(advanced):
    import json

    from app.storage.db import connection

    enabled()
    job = store.enqueue()
    with connection() as conn:
        conn.executemany(
            "INSERT INTO advanced_proposals VALUES(?,?,?,?,?,?,NULL,NULL)",
            [(f"completed-{i}", job["id"], "applied", "2026-10-18T12:00:00Z", "2026-10-18T12:00:00Z", json.dumps({"operation": "profile"})) for i in range(205)]
            + [("pending-one", job["id"], "pending", "2026-10-18T10:00:00Z", "2026-10-18T10:00:00Z", json.dumps({"operation": "profile"})),
               ("pending-two", job["id"], "pending", "2026-10-18T10:00:00Z", "2026-10-18T10:00:00Z", json.dumps({"operation": "move"})),
               ("question", job["id"], "pending", "2026-10-18T10:00:00Z", "2026-10-18T10:00:00Z", json.dumps({"operation": "question"})),
               ("rejected", job["id"], "rejected", "2026-10-18T12:00:00Z", "2026-10-18T12:00:00Z", json.dumps({"operation": "profile"}))],
        )
    assert store.pending_approval_count() == 2
    assert {row["id"] for row in store.list_proposals()[:3]} == {"pending-one", "pending-two", "question"}


def test_maintenance_batches_never_mix_private_spaces(advanced):
    from app.advanced.prompt import build_prompt

    store.save_settings(AdvancedSettings(enabled=True, space_ids=["space_personal", "space_work"]))
    personal = fact("Private personal fact")
    work = fact("Work confidential sentinel", space="space_work")
    core.create_guidance(core.ADMIN, {"space_id": "space_work", "statement": "Private work guidance sentinel"})
    core.create_subject(core.ADMIN, {"space_id": "space_work", "name": "Private work identity sentinel", "kind": "person"})
    job = store.enqueue()
    records, spaces = service.job_records(job)
    assert {item["space_id"] for item in records} == {"space_personal"}
    text = build_prompt(job, records, spaces)
    assert "Work confidential sentinel" not in text
    assert "Private work guidance sentinel" not in text
    assert "Private work identity sentinel" not in text
    assert personal["id"] in text
    with pytest.raises(ValueError, match="one ownership space"):
        build_prompt(job, [personal, work], spaces)


def test_codex_model_cannot_be_an_option(advanced):
    with pytest.raises(ValueError):
        AdvancedSettings(model="--dangerously-bypass-approvals-and-sandbox")
