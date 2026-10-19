"""Automatic-recall behaviour, evidence preservation and permission boundaries."""

import json

import pytest

from app.storage.db import connection
from app.storage.repositories.categories import create_category
from app.v2 import core, retrieval
from scripts.diagnose_prefetch import fixture, memory


def recall(p, query, **kwargs):
    return core.search(p, query, recall=True, limit=5, max_chars=2400, **kwargs)


def test_conversational_entity_and_repeated_filler_preserve_answer():
    with fixture(
        [
            memory("food", "Tess dining preferences", "Tess avoids almonds and enjoys Thai food."),
            memory("plan", "General planning", "I can check the plan for you and work on it."),
            memory("long", "Storage preparation", "Inventory and recovery preparation. " * 250),
        ]
    ) as (p, ids):
        for query in [
            "Tess food preferences",
            "Please tell me what food Tess enjoys for dinner.",
            "Tess food preferences " + "to " * 20,
        ]:
            result = recall(p, query)
            assert result["results"][0]["id"] == ids["food"]
            assert all(row["id"] not in {ids["long"], ids["plan"]} for row in result["results"])


@pytest.mark.parametrize("query", ["quasars", "Calculate 27 times 14.", "Explain photosynthesis."])
def test_unrelated_questions_abstain_despite_task_pin(query):
    with fixture(
        [memory("backup", "Server backups", "Backups run nightly.", auto_prefetch_level="pinned")]
    ) as (p, _):
        result = recall(p, query)
        assert result["results"] == [] and result["context"]["abstained"]


def test_global_pin_bounded_and_never_displaces_topical_record():
    with fixture(
        [
            memory("fact", "Router address", "Router address is 10.20.30.40."),
            memory(
                "pref",
                "Global preference",
                "Use concise UK English. " * 80,
                space_id="space_general",
                auto_prefetch_level="pinned",
            ),
        ]
    ) as (p, ids):
        result = recall(p, "Router address")
        assert result["results"][0]["id"] == ids["fact"]
        assert len(json.dumps(result["results"][-1], ensure_ascii=False)) <= 480
        tiny = core.search(p, "Router address", recall=True, limit=1, max_chars=800)
        assert [r["id"] for r in tiny["results"]] == [ids["fact"]]


@pytest.mark.parametrize("query", ["10.20.30.40", "https://panel.example.test/settings"])
def test_exact_identifiers_reject_neighbours_and_accept_sentence_punctuation(query):
    with fixture(
        [
            memory(
                "target", "Dashboard endpoint", "Use 10.20.30.40. Visit https://panel.example.test."
            ),
            memory("other", "DNS endpoint", "DNS is at 10.20.30.41. Visit other.example.test."),
        ]
    ) as (p, ids):
        result = recall(p, query)
        assert [r["id"] for r in result["results"]] == [ids["target"]]


def test_name_is_not_a_prefix_of_another_person():
    with fixture(
        [
            memory("person", "Tess", "Tess enjoys cycling."),
            memory("other", "Tessa", "Tessa likes painting."),
        ]
    ) as (p, ids):
        assert [r["id"] for r in recall(p, "Tess")["results"]] == [ids["person"]]


def test_ipv6_uses_address_identity_rather_than_format_or_shared_groups():
    with fixture(
        [
            memory("target", "IPv6 gateway", "Gateway is 2001:0db8:0000:0000:0000:0000:0000:0001."),
            memory("other", "IPv6 DNS", "DNS is 2001:db8::2."),
            memory("local", "Loopback", "Loopback is ::1."),
        ]
    ) as (p, ids):
        assert [r["id"] for r in recall(p, "2001:db8::1")["results"]] == [ids["target"]]
        assert [r["id"] for r in recall(p, "::1")["results"]] == [ids["local"]]


def test_exclusions_and_category_gate_do_not_prevent_explicit_search():
    with fixture(
        [
            memory("archived", "Router archive", "Router retired.", archived=True),
            memory("never", "Router scratchpad", "Router notes.", auto_prefetch_level="never"),
        ]
    ) as (p, _):
        category = create_category(name="Manual recall only", allow_auto_prefetch=False)
        record = core.create_memory(
            core.ADMIN,
            {
                "title": "Router procedure",
                "body": "Router verified setup.",
                "space_id": "space_personal",
                "category_id": category["id"],
            },
            "manual",
        )
        assert recall(p, "Router")["results"] == []
        assert record["id"] in {r["id"] for r in core.search(p, "Router")["results"]}


def test_priority_orders_otherwise_equivalent_relevant_records():
    with fixture(
        [
            memory(
                "low",
                "Router access",
                "Router uses the verified procedure.",
                auto_prefetch_level="low",
            ),
            memory(
                "high",
                "Router access",
                "Router uses the verified procedure.",
                auto_prefetch_level="high",
            ),
        ]
    ) as (p, ids):
        assert recall(p, "Router access")["results"][0]["id"] == ids["high"]


@pytest.mark.parametrize("budget", [256, 550, 900, 2400])
def test_budget_includes_serialized_metadata_and_escaped_content(budget):
    with fixture(
        [memory("long", 'Runbook "quoted"', 'Runbook "content"\n' * 300 + "FINAL-COMMAND")]
    ) as (p, _):
        result = core.search(p, "Runbook", recall=True, max_chars=budget, limit=5)
        used = sum(len(json.dumps(r, ensure_ascii=False)) for r in result["results"])
        assert used == result["character_count"] <= budget


def test_matching_passage_and_conclusion_survive_in_a_long_record():
    with fixture(
        [
            memory(
                "long",
                "Router recovery runbook",
                "Inventory preparation. " * 160
                + "Recovery command is RESTORE-VERIFIED. "
                + "Safety checks. " * 160
                + "Final note: verify the restored files.",
            )
        ]
    ) as (p, ids):
        row = recall(p, "Router recovery command")["results"][0]
        assert row["id"] == ids["long"] and row["excerpted"] and row["truncated"]
        assert "RESTORE-VERIFIED" in row["body"] and "verify the restored files" in row["body"]


def test_long_early_record_cannot_consume_later_evidence_budget():
    with fixture(
        [
            memory("long", "Router operation runbook", "Router operation " * 400),
            memory("short", "Router operation schedule", "Router operation starts at 03:15."),
        ]
    ) as (p, ids):
        rows = recall(p, "Router operation")["results"]
        assert {r["id"] for r in rows} == set(ids.values())
        assert any("03:15" in row.get("body", "") for row in rows)


def test_aliases_boost_subjects_only_within_authorized_scope():
    with fixture([]) as (p, _):
        subject = core.create_subject(
            core.ADMIN, {"space_id": "space_personal", "name": "Tess", "aliases": ["my fiancée"]}
        )
        row = core.create_memory(
            core.ADMIN,
            {
                "title": "Tess preferences",
                "body": "Tess prefers Thai food.",
                "space_id": "space_personal",
                "subject_ids": [subject["id"]],
            },
            "subject",
        )
        # Alias matching must also provide lexical candidate terms, not just a ranking boost.
        result = recall(p, "What food does my fiancée enjoy?")
        assert result["results"][0]["id"] == row["id"]
        explicit = recall(p, "dinner", subject_ids=[subject["id"]])
        assert explicit["results"][0]["id"] == row["id"]


def test_authorization_precedes_all_candidate_metadata():
    with fixture(
        [
            memory("work", "Atlas server", "Work server.", space_id="space_work"),
            memory("home", "Atlas server", "Private server."),
        ]
    ) as (p, ids):
        core.set_connection(
            core.ADMIN,
            p.key_id,
            {
                "default_space_id": "space_work",
                "grants": [{"space_id": "space_work", "can_read": True, "can_write": True}],
            },
        )
        result = recall(p, "Atlas", broaden=True)
        assert [r["id"] for r in result["results"]] == [ids["work"]]
        assert result["context"]["candidate_count"] == 1
        with pytest.raises(core.SpaceError):
            recall(p, "Atlas", space_id="space_personal")


def test_archived_and_superseded_facts_still_excluded():
    with fixture(
        [
            memory("old", "Current resolver", "Resolver old address."),
            memory("new", "Resolver migration", "Resolver new address."),
        ]
    ) as (p, ids):
        with connection() as c:
            c.execute("UPDATE memories SET superseded_by=? WHERE id=?", (ids["new"], ids["old"]))
        assert [r["id"] for r in recall(p, "resolver")["results"]] == [ids["new"]]


def test_filler_removed_before_cap_and_fts_operators_are_literal():
    assert retrieval.prepare("please " * 100 + "Tess")[0] == ["tess"]
    with fixture([memory("fact", "Tess", "Tess cycles.")]) as (p, ids):
        rows = recall(p, '" OR (Tess NEAR NOT:*)')["results"]
        assert rows and rows[0]["id"] == ids["fact"]


def test_application_phrase_keeps_scope_word_and_beats_unrelated_assistant():
    with fixture(
        [
            memory("app", "Home Assistant integration", "Home Assistant controls the porch lamp."),
            memory(
                "other", "Assistant identity", "The assistant can help with lights and cameras."
            ),
        ]
    ) as (p, ids):
        result = recall(p, "Check my home assistant lamp please")
        assert result["results"][0]["id"] == ids["app"]


def test_split_prefix_does_not_recall_unrelated_pre_roll_document():
    with fixture(
        [
            memory(
                "video",
                "Video redaction",
                "Keep API keys out of ordinary memory. "
                + "Camera video details. " * 5
                + "Use 1.5 seconds of pre-roll.",
            )
        ]
    ) as (p, _):
        assert recall(p, "How does it know what memory to pre fetch?")["results"] == []
