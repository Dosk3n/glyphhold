import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.config import settings
from app.core.auth import create_api_key
from app.storage.migrations import apply_migrations
from app.v2 import core


@pytest.fixture
def setup(tmp_path, monkeypatch):
    original = settings.db_path
    object.__setattr__(settings, "db_path", tmp_path / "gh2.sqlite")
    apply_migrations()
    core.ensure_schema()
    kid, _ = create_api_key(
        name="work laptop",
        actor="worker",
        description=None,
        scopes=["memories:read", "memories:write"],
    )
    core.set_connection(
        core.ADMIN,
        kid,
        {
            "default_space_id": "space_work",
            "grants": [
                {"space_id": "space_work", "can_read": True, "can_write": True},
                {"space_id": "space_general", "can_read": True, "can_write": False},
            ],
        },
    )
    yield core.Principal(kid, "worker", {"memories:read", "memories:write"})
    object.__setattr__(settings, "db_path", original)


def make(p, key="one", **fields):
    return core.create_memory(
        p, {"title": "Check server", "body": "The server runs Linux"} | fields, key
    )


def test_permissions_defaults_and_broaden(setup):
    p = setup
    mine = make(p)
    personal = make(
        core.ADMIN, "personal", space_id="space_personal", title="Check server", body="Private host"
    )
    general = make(
        core.ADMIN, "general", space_id="space_general", title="Server preference", body="Use SSH"
    )
    assert mine["space_id"] == "space_work"
    recalled = core.search(p, "server", recall=True)
    assert {m["id"] for m in recalled["results"]} == {mine["id"], general["id"]}
    assert personal["id"] not in {
        m["id"] for m in core.search(p, "server", broaden=True)["results"]
    }
    with pytest.raises(core.SpaceError) as e:
        core.get_memory(p, personal["id"])
    assert e.value.status == 404
    with pytest.raises(core.SpaceError):
        make(p, "wrong", space_id="space_personal")
    assert core.default_space(p) == "space_work"


def test_idempotency_and_changed_content(setup):
    p = setup
    a = make(p)
    b = make(p)
    assert a == b
    with pytest.raises(core.SpaceError) as e:
        make(p, body="different")
    assert e.value.status == 409
    assert len(core.list_memories(p)) == 1


def test_concurrent_compare_and_swap_and_restore(setup):
    p = setup
    m = make(p)

    def update(title):
        try:
            return core.update_memory(p, m["id"], {"title": title}, 1)
        except core.SpaceError as e:
            return e.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, ["First", "Second"]))
    assert sum(isinstance(r, dict) for r in results) == 1
    assert 409 in results
    revisions = core.revisions(p, m["id"])
    assert len(revisions) == 1 and revisions[0]["snapshot"]["title"] == "Check server"
    restored = core.restore(p, m["id"], revisions[0]["id"], 2)
    assert restored["title"] == "Check server" and restored["version"] == 3


def test_evidence_is_same_space_and_stale_profile_hidden(setup):
    p = setup
    fact = make(p)
    profile = make(
        p,
        "profile",
        title="Server profile",
        record_type="profile",
        source_refs=[{"id": fact["id"], "version": 1}],
    )
    assert profile["id"] in {m["id"] for m in core.search(p, "server")["results"]}
    core.update_memory(p, fact["id"], {"body": "Changed host"}, 1)
    assert core.get_memory(p, profile["id"])["stale"]
    assert profile["id"] not in {m["id"] for m in core.search(p, "server")["results"]}
    private = make(core.ADMIN, "private", space_id="space_personal")
    with pytest.raises(core.SpaceError):
        make(
            core.ADMIN,
            "leak",
            space_id="space_general",
            record_type="profile",
            source_refs=[{"id": private["id"], "version": 1}],
        )


def test_move_revision_visibility_and_grant_revocation(setup):
    p = setup
    m = make(p)
    moved = core.update_memory(core.ADMIN, m["id"], {"space_id": "space_personal"}, 1)
    assert moved["id"] == m["id"]
    with pytest.raises(core.SpaceError):
        core.get_memory(p, m["id"])
    # Idempotent replay cannot leak a previous snapshot after current record moves.
    with pytest.raises(core.SpaceError):
        make(p)


def test_import_preview_repeatability_relationships_and_revisions(setup):
    payload = {
        "namespace": "old-home",
        "space_id": "space_personal",
        "document": {
            "memories": [
                {
                    "id": "old",
                    "title": "Old server",
                    "body": "Old address",
                    "category_id": "cat_server",
                    "superseded_by": "new",
                    "created_at": "2020-01-01T00:00:00Z",
                },
                {
                    "id": "new",
                    "title": "New server",
                    "body": "New address",
                    "category_id": "cat_server",
                },
            ],
            "revisions": [
                {
                    "id": "r1",
                    "memory_id": "old",
                    "title": "Original title",
                    "body": "Original body",
                    "created_at": "2019-01-01T00:00:00Z",
                }
            ],
        },
    }
    assert core.import_preview(core.ADMIN, payload)["new"] == 2
    first = core.import_apply(core.ADMIN, payload)
    second = core.import_apply(core.ADMIN, payload)
    assert second["existing"] == 2 and second["new"] == 0
    old = core.get_memory(core.ADMIN, first["mappings"]["old"])
    assert old["superseded_by"] == first["mappings"]["new"]
    assert old["created_at"] == "2020-01-01T00:00:00Z"
    assert len(core.revisions(core.ADMIN, old["id"])) == 1
    payload["document"]["memories"][0]["body"] = "Changed original"
    assert core.import_preview(core.ADMIN, payload)["conflicts"] == ["old"]
    with pytest.raises(core.SpaceError):
        core.import_apply(core.ADMIN, payload)


def test_guard_and_callback_are_atomic(setup):
    p = setup
    m = make(p)

    def reject(c):
        raise core.SpaceError(409, "Disabled job")

    with pytest.raises(core.SpaceError):
        core.update_memory(p, m["id"], {"body": "changed"}, 1, guard=reject)
    assert core.get_memory(p, m["id"])["version"] == 1

    def fail_commit(c, result):
        raise RuntimeError("failure")

    with pytest.raises(RuntimeError):
        core.update_memory(p, m["id"], {"body": "changed"}, 1, on_commit=fail_commit)
    assert core.get_memory(p, m["id"])["version"] == 1
    assert core.revisions(p, m["id"]) == []


def test_subject_guidance_and_export_no_secrets(setup):
    p = setup
    subject = core.create_subject(p, {"name": "Jess", "kind": "person", "space_id": "space_work"})
    item = core.create_guidance(
        core.ADMIN,
        {
            "space_id": "space_work",
            "subject_id": subject["id"],
            "statement": "This is explicitly confirmed",
        },
    )
    assert core.guidance(p)[0]["id"] == item["id"]
    with pytest.raises(core.SpaceError):
        core.create_guidance(p, {"statement": "guessed"})
    exported = core.export_memories(core.ADMIN)
    assert "secrets" not in exported
    assert len(exported["subjects"]) == 1


def test_api_contract_csrf_and_ownership(client):
    # The app bootstraps GH2 before the session begins.
    from tests.conftest import dashboard_csrf_headers

    h = dashboard_csrf_headers(client)
    r = client.post(
        "/dashboard/api/setup",
        headers=h,
        json={
            "username": "owner",
            "password": "A-strong-local-password-2026",
            "confirm_password": "A-strong-local-password-2026",
        },
    )
    assert r.status_code == 200
    assert client.post("/api/v2/spaces", json={"name": "Friends"}).status_code == 403
    h = dashboard_csrf_headers(client)
    assert client.get("/api/v2/capabilities").status_code == 200
    created = client.post(
        "/api/v2/memories",
        headers=h,
        json={
            "title": "Home preference",
            "body": "Use ssh",
            "space_id": "space_personal",
            "idempotency_key": "api-one",
        },
    )
    assert created.status_code == 201, created.text
    m = created.json()
    assert (
        client.patch("/api/v2/memories/" + m["id"], headers=h, json={"body": "new"}).status_code
        == 422
    )
    updated = client.patch(
        "/api/v2/memories/" + m["id"], headers=h, json={"body": "new", "expected_version": 1}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    assert (
        client.patch(
            "/api/v2/memories/" + m["id"], headers=h, json={"body": "lost", "expected_version": 1}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v2/recall", headers=h, json={"query": "preference", "space_id": "space_personal"}
        ).json()["results"][0]["id"]
        == m["id"]
    )


def test_moved_evidence_redacts_stale_profile(setup):
    p = setup
    fact = make(p)
    profile = make(
        p,
        "profile",
        title="Secret project profile",
        record_type="profile",
        source_refs=[{"id": fact["id"], "version": 1}],
    )
    core.update_memory(core.ADMIN, fact["id"], {"space_id": "space_personal"}, 1)
    stale = core.get_memory(p, profile["id"])
    assert stale["stale"] and stale["body"] == "" and stale["title"] == "Profile requires refresh"


def test_session_context_precedence_and_connection_isolation(setup):
    p = setup
    core.set_context(p, "chat-1", "space_general")
    assert core.get_context(p, "chat-1")["space_id"] == "space_general"
    assert core.resolve_space(p, "space_work", session_id="chat-1") == "space_work"
    assert core.resolve_space(p, session_id="chat-2") == "space_work"
    assert core.resolve_space(core.ADMIN, session_id="chat-1") == "space_personal"
    with pytest.raises(core.SpaceError):
        make(p, "general-in-session", session_id="chat-1")
    assert (
        core.search(p, "server", session_id="chat-1")["context"]["active_space_id"]
        == "space_general"
    )


def test_inplace_legacy_revision_upgrade_and_restore(setup):
    from app.storage.db import connection
    from app.storage.repositories import memories

    with connection() as c:
        category_id = c.execute("SELECT id FROM memory_categories LIMIT 1").fetchone()[0]
    old = memories.create_memory(
        category_id=category_id, title="Legacy title", body="Original legacy fact"
    )
    memories.update_memory(old["id"], title="Updated legacy title", changed_by="old-agent")
    core.ensure_schema()
    history = core.revisions(core.ADMIN, old["id"])
    assert len(history) == 1 and history[0]["snapshot"]["title"] == "Legacy title"
    restored = core.restore(core.ADMIN, old["id"], history[0]["id"], 1)
    assert restored["title"] == "Legacy title" and restored["version"] == 2


def test_v2_import_preserves_subject_links_and_guidance(setup):
    subject = core.create_subject(
        core.ADMIN, {"space_id": "space_personal", "name": "Jess", "kind": "person"}
    )
    core.create_guidance(
        core.ADMIN,
        {
            "space_id": "space_personal",
            "subject_id": subject["id"],
            "statement": "Confirmed personal association",
        },
    )
    original = make(
        core.ADMIN, "original-subject", space_id="space_personal", subject_ids=[subject["id"]]
    )
    export = core.export_memories(core.ADMIN)
    result = core.import_apply(
        core.ADMIN, {"namespace": "another-system", "space_id": "space_work", "document": export}
    )
    imported = core.get_memory(core.ADMIN, result["mappings"][original["id"]])
    assert len(imported["subject_ids"]) == 1 and imported["subject_ids"][0] != subject["id"]
    assert any(
        item["subject_id"] == imported["subject_ids"][0]
        for item in core.guidance(core.ADMIN, "space_work")
    )


def test_transactional_activity_memory_lifecycle_content_free(setup):
    from app.storage.db import connection

    p = setup
    sensitive = "private fact text should never appear in activity"
    memory = make(
        p,
        "activity",
        title=sensitive,
        body=sensitive,
        summary=sensitive,
        metadata={"private": sensitive},
    )
    assert (
        make(
            p,
            "activity",
            title=sensitive,
            body=sensitive,
            summary=sensitive,
            metadata={"private": sensitive},
        )["id"]
        == memory["id"]
    )
    updated = core.update_memory(
        p, memory["id"], {"body": "changed " + sensitive}, 1, reason=sensitive
    )
    original_revision = core.revisions(p, memory["id"])[0]["id"]
    moved = core.update_memory(
        core.ADMIN, memory["id"], {"space_id": "space_personal"}, updated["version"]
    )
    archived = core.update_memory(core.ADMIN, memory["id"], {"archived": True}, moved["version"])
    restored = core.restore(core.ADMIN, memory["id"], original_revision, archived["version"])
    with connection() as c:
        events = [
            dict(r)
            for r in c.execute(
                "SELECT * FROM event_log WHERE target_id=? ORDER BY created_at,rowid",
                (memory["id"],),
            )
        ]
    assert [e["event_type"] for e in events] == [
        "memory.create",
        "memory.update",
        "memory.move",
        "memory.archive",
        "memory.restore",
    ]
    assert sensitive not in json.dumps(events)
    assert events[0]["actor"] == p.actor
    assert all(e["request_id"].startswith("op_") for e in events)
    assert json.loads(events[-1]["metadata_json"])["version"] == restored["version"]
    with pytest.raises(core.SpaceError):
        core.update_memory(p, memory["id"], {"body": "stale"}, 1)
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) FROM event_log WHERE target_id=?", (memory["id"],)
            ).fetchone()[0]
            == 5
        )


def test_activity_grants_and_guidance_do_not_copy_freeform_text(setup):
    from app.storage.db import connection

    p = setup
    statement = "private classification statement"
    item = core.create_guidance(core.ADMIN, {"space_id": "space_work", "statement": statement})
    core.delete_guidance(core.ADMIN, item["id"])
    core.delete_guidance(core.ADMIN, item["id"])
    core.set_connection(core.ADMIN, p.key_id, {"default_space_id": None, "grants": []})
    with connection() as c:
        events = [dict(r) for r in c.execute("SELECT * FROM event_log")]
    guidance_events = [e for e in events if e["target_id"] == item["id"]]
    assert [e["event_type"] for e in guidance_events] == ["guidance.create", "guidance.delete"]
    assert statement not in json.dumps(events)
    grant_event = next(e for e in reversed(events) if e["event_type"] == "connection.grants_update")
    assert json.loads(grant_event["metadata_json"]) == {"default_space_id": None, "grants": []}


def test_activity_and_memory_rollback_together(setup, monkeypatch):
    from app.storage.db import connection

    p = setup
    memory = make(p)
    with connection() as c:
        before = c.execute("SELECT count(*) FROM event_log").fetchone()[0]

    def failing_audit(*args, **kwargs):
        raise RuntimeError("audit write failed")

    with monkeypatch.context() as patch:
        patch.setattr(core, "_audit", failing_audit)
        with pytest.raises(RuntimeError):
            core.update_memory(p, memory["id"], {"body": "must roll back"}, 1)
        with pytest.raises(RuntimeError):
            make(p, "rollback-create", title="must roll back")
    assert core.get_memory(p, memory["id"])["version"] == 1
    assert core.revisions(p, memory["id"]) == []
    assert len(core.list_memories(p)) == 1
    with connection() as c:
        assert c.execute("SELECT count(*) FROM event_log").fetchone()[0] == before


def test_legacy_history_export_does_not_duplicate_backfilled_snapshots(setup):
    from app.storage.db import connection
    from app.storage.repositories import memories

    with connection() as c:
        category_id = c.execute("SELECT id FROM memory_categories LIMIT 1").fetchone()[0]
    original = memories.create_memory(category_id=category_id, title="Original", body="Source fact")
    memories.update_memory(original["id"], title="Changed", changed_by="legacy")
    core.ensure_schema()
    document = core.export_memories(core.ADMIN)
    assert len(document["revisions"]) == 1 and document["v2_revisions"] == []
    result = core.import_apply(
        core.ADMIN, {"namespace": "copy", "space_id": "space_personal", "document": document}
    )
    assert len(core.revisions(core.ADMIN, result["mappings"][original["id"]])) == 1


def test_retrieval_baseline_scope_evaluation_without_projects(setup):
    """Small deterministic corpus measures scope behaviour, not semantic recall."""
    from app.storage.repositories import memories as legacy

    p = setup
    core.set_connection(
        core.ADMIN,
        p.key_id,
        {
            "default_space_id": "space_work",
            "grants": [
                {"space_id": "space_work", "can_read": True, "can_write": True},
                {"space_id": "space_personal", "can_read": True, "can_write": True},
                {"space_id": "space_general", "can_read": True, "can_write": False},
            ],
        },
    )
    work = make(
        p, "work-server", title="Atlas server", body="Work Atlas server uses the office network"
    )
    home = make(
        core.ADMIN,
        "home-server",
        space_id="space_personal",
        title="Atlas server",
        body="Home Atlas server uses the private network",
    )
    general = make(
        core.ADMIN,
        "general-pref",
        space_id="space_general",
        title="Communication preferences",
        body="Prefer concise answers to research questions",
    )
    make(
        core.ADMIN,
        "personal-pref",
        space_id="space_personal",
        title="Jess preferences",
        body="Personal recorded preferences",
    )
    research = make(
        p, "backup-research", title="Backup research", body="Research backup options for the server"
    )
    allowed = {"space_work", "space_general"}
    legacy_wrong = v2_wrong = 0
    for query, expected in [
        ("server", {work["id"], research["id"]}),
        ("preferences", {general["id"]}),
        ("research", {general["id"], research["id"]}),
        ("volcanoes", set()),
    ]:
        before = legacy.search_memories(query=query, limit=20)
        after = core.search(p, query, recall=True, limit=20)["results"]
        legacy_wrong += sum(row["space_id"] not in allowed for row in before)
        v2_wrong += sum(row["space_id"] not in allowed for row in after)
        assert {row["id"] for row in after} == expected
    assert legacy_wrong == 2 and v2_wrong == 0
    explicit = core.search(p, "Atlas", space_id="space_personal")["results"]
    assert [row["id"] for row in explicit] == [home["id"]]
    assert core.default_space(p) == "space_work"


def test_indexed_retrieval_filters_before_shortlist_and_quotes_query(setup):
    p = setup
    work = make(p, "allowed", title="Server", body="Allowed server")
    for index in range(70):
        make(
            core.ADMIN,
            "hidden-" + str(index),
            space_id="space_personal",
            title="Server server server",
            body="Server " * 20,
        )
    assert core.search(p, "server", limit=1)["results"][0]["id"] == work["id"]
    make(p, "substring", title="Word boundary", body="concatenate")
    assert core.search(p, "cat")["results"] == []
    # Operators are ordinary quoted terms, not user-controlled MATCH syntax.
    assert any(
        row["id"] == work["id"] for row in core.search(p, '" OR (server NEAR NOT:*)')["results"]
    )


def test_recall_budget_includes_oversized_summary_title_and_lineage(setup):
    p = setup
    source = make(p, "budget-source", title="Budget source", body="Original fact")
    profile = make(
        p,
        "budget-profile",
        title="Profile " + ("Long title " * 40),
        body="Full profile " * 500,
        summary='Very large summary with escaped "quotes"\n' * 200,
        record_type="profile",
        source_refs=[{"id": source["id"], "version": 1}] * 20,
    )
    response = core.search(p, "Profile", max_chars=900, limit=1)
    assert response["results"][0]["id"] == profile["id"]
    item = response["results"][0]
    assert item["truncated"] and item["source_refs_truncated"] and item["source_refs_count"] == 20
    assert response["character_count"] == sum(
        len(json.dumps(row, ensure_ascii=False)) for row in response["results"]
    )
    assert response["character_count"] <= 900


def test_api_move_explicitly_replaces_space_owned_subject_links(client):
    kid, token = create_api_key(
        name="Moving agent",
        actor="test",
        description="",
        scopes=["memories:read", "memories:write"],
    )
    core.set_connection(
        core.ADMIN,
        kid,
        {
            "default_space_id": "space_work",
            "grants": [
                {"space_id": "space_work", "can_read": True, "can_write": True},
                {"space_id": "space_personal", "can_read": True, "can_write": True},
            ],
        },
    )
    p = core.Principal(kid, "test", {"memories:read", "memories:write"})
    subject = core.create_subject(
        p, {"space_id": "space_work", "name": "Test person", "kind": "person"}
    )
    record = make(p, "subject-move", subject_ids=[subject["id"]])
    headers = {"Authorization": "Bearer " + token}
    rejected = client.post(
        "/api/v2/memories/" + record["id"] + "/move",
        headers=headers,
        json={"space_id": "space_personal", "expected_version": 1},
    )
    assert rejected.status_code == 400
    moved = client.post(
        "/api/v2/memories/" + record["id"] + "/move",
        headers=headers,
        json={"space_id": "space_personal", "expected_version": 1, "subject_ids": []},
    )
    assert moved.status_code == 200 and moved.json()["subject_ids"] == []
    assert moved.json()["id"] == record["id"]
    history = core.revisions(core.ADMIN, record["id"])
    assert history[0]["snapshot"]["subject_ids"] == [subject["id"]]
