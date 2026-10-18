from __future__ import annotations

import json

from app.advanced import store
from app.advanced.models import Proposal
from app.advanced.prompt import build_prompt
from app.storage.db import connection
from app.v2 import core


def scoped_evidence(memory: dict, permitted: set[str], seen: set[str] | None = None) -> bool:
    """Admin prepares jobs, but must not expose a moved source through old derived text."""
    if memory["space_id"] not in permitted:
        return False
    seen = set() if seen is None else seen
    if memory["id"] in seen:
        return False
    seen = seen | {memory["id"]}
    for ref in memory.get("source_refs") or []:
        try:
            source = core.get_memory(core.ADMIN, ref["id"])
        except core.SpaceError:
            return False
        if source["space_id"] != memory["space_id"] or not scoped_evidence(source, permitted, seen):
            return False
    return True


def job_records(job: dict) -> tuple[list[dict], list[dict]]:
    config = job["config"]
    permitted = set(config["space_ids"])
    spaces = [space for space in core.list_spaces(core.ADMIN) if space["id"] in permitted]
    if {s["id"] for s in spaces} != permitted:
        raise ValueError("One or more configured spaces no longer exist")
    reviewed = store.processed()
    selected = []
    context_chars = len(build_prompt(job, [], spaces))
    evidence_budget = config["max_context_chars"] - context_chars - 100
    if evidence_budget < 512:
        raise ValueError(
            "Context limit is too small for the maintenance instructions and placement guidance"
        )
    # Oldest updates first prevents a busy account starving its backlog.
    with connection() as conn:
        rows = conn.execute("SELECT id,version FROM memories ORDER BY updated_at,id").fetchall()
    for row in rows:
        if reviewed.get(row["id"]) == row["version"]:
            continue
        memory = core.get_memory(core.ADMIN, row["id"])
        if not scoped_evidence(memory, permitted):
            continue
        # Derived records are context, not independent evidence feeding back into itself.
        if memory.get("record_type", "fact") != "fact":
            continue
        # Never expose different ownership spaces to the same model inference.
        if selected and memory["space_id"] != selected[0]["space_id"]:
            continue
        if not selected:
            context_chars = len(build_prompt(job, [], spaces, source_space_id=memory["space_id"]))
            evidence_budget = config["max_context_chars"] - context_chars - 100
            if evidence_budget < 512:
                raise ValueError("Context limit is too small for this space's guidance and identities")
        item = {
            key: memory.get(key)
            for key in (
                "id",
                "version",
                "space_id",
                "title",
                "summary",
                "body",
                "source",
                "created_at",
                "updated_at",
                "last_verified_at",
                "record_type",
                "source_refs",
                "archived",
                "merged_into",
                "superseded_by",
                "subject_ids",
                "stale",
            )
        }
        size = len(json.dumps(item, ensure_ascii=False))
        if size > evidence_budget:
            raise ValueError(
                f"Memory {memory['id']} exceeds the context limit; increase the limit or shorten this record"
            )
        if (
            context_chars + size > config["max_context_chars"]
            or len(selected) >= config["batch_size"]
        ):
            break
        selected.append(item)
        context_chars += size + 2
    if not selected:
        return [], spaces
    # Add bounded context: existing profiles/summaries and prior facts sharing explicit subjects.
    subjects = {subject for item in selected for subject in (item.get("subject_ids") or [])}
    selected_ids = {item["id"] for item in selected}
    for sid in {selected[0]["space_id"]}:
        offset = 0
        while context_chars < config["max_context_chars"]:
            records = core.list_memories(core.ADMIN, space_id=sid, limit=100, offset=offset)
            if not records:
                break
            for memory in records:
                if memory["id"] in selected_ids:
                    continue
                if not scoped_evidence(memory, permitted):
                    continue
                if memory.get("record_type") == "fact" and not subjects.intersection(
                    memory.get("subject_ids") or []
                ):
                    continue
                item = {
                    key: memory.get(key)
                    for key in (
                        "id",
                        "version",
                        "space_id",
                        "title",
                        "summary",
                        "body",
                        "source",
                        "created_at",
                        "updated_at",
                        "last_verified_at",
                        "record_type",
                        "source_refs",
                        "subject_ids",
                        "stale",
                    )
                }
                size = len(json.dumps(item, ensure_ascii=False))
                if context_chars + size <= config["max_context_chars"]:
                    item["context_only"] = True
                    selected.append(item)
                    context_chars += size + 2
                    selected_ids.add(memory["id"])
            offset += len(records)
            if len(records) < 100:
                break
    # Include original support for supplied profiles. Refreshes can then preserve facts
    # without treating the existing profile as an independent factual source.
    for item in list(selected):
        if item.get("record_type") == "fact":
            continue
        for ref in item.get("source_refs") or []:
            if ref["id"] in selected_ids:
                continue
            try:
                original = core.get_memory(core.ADMIN, ref["id"])
            except core.SpaceError:
                continue
            if not scoped_evidence(original, permitted):
                continue
            support = {
                key: original.get(key)
                for key in (
                    "id",
                    "version",
                    "space_id",
                    "title",
                    "body",
                    "summary",
                    "record_type",
                    "source",
                    "source_refs",
                    "archived",
                    "merged_into",
                    "superseded_by",
                    "stale",
                )
            }
            size = len(json.dumps(support, ensure_ascii=False))
            if context_chars + size <= config["max_context_chars"]:
                support["context_only"] = True
                selected.append(support)
                selected_ids.add(support["id"])
                context_chars += size + 2
    return selected, spaces


def validate_proposal(job: dict, proposal: Proposal, *, current: bool = False) -> None:
    permitted = set(job["config"]["space_ids"])
    if proposal.space_id not in permitted:
        raise ValueError("Proposal exceeds the job's permitted spaces")
    if proposal.destination_space_id and proposal.destination_space_id not in permitted:
        raise ValueError("Move destination exceeds the job's permitted spaces")
    evidence = {item["id"]: item for item in (job.get("evidence") or [])}
    subjects = {item["id"]: item for item in job["config"].get("subjects", [])}
    subject_space = (
        proposal.destination_space_id if proposal.operation == "move" else proposal.space_id
    )
    if any(
        subject not in subjects or subjects[subject]["space_id"] != subject_space
        for subject in proposal.subject_ids
    ):
        raise ValueError("Subject links must use supplied identities in the owning space")
    for ref in proposal.source_refs:
        source = evidence.get(ref.id)
        if not source or source["version"] != ref.version:
            raise ValueError("Proposal cites evidence outside its supplied snapshot")
        if source["space_id"] != proposal.space_id:
            raise ValueError("Source evidence cannot be copied across spaces")
        if proposal.operation in {"profile", "summary", "update"} and any(
            source.get(key) for key in ("archived", "merged_into", "superseded_by")
        ):
            raise ValueError("Inactive sources cannot support a current profile or summary")
        if current:
            memory = core.get_memory(core.ADMIN, ref.id)
            if memory["version"] != ref.version or memory["space_id"] != proposal.space_id:
                raise ValueError("Source evidence changed; request a fresh review")
    if proposal.target_id:
        target = evidence.get(proposal.target_id)
        if not target or target["space_id"] != proposal.space_id:
            raise ValueError("Target was not supplied as evidence in this space")
        if proposal.expected_version != target["version"]:
            raise ValueError("Target version is required and must match the evidence")
    elif proposal.operation not in {"profile", "summary", "question"}:
        raise ValueError("This operation requires a target memory")
    if proposal.operation in {"merge", "supersede"}:
        replacement = evidence.get(proposal.replacement_id)
        if (
            not replacement
            or replacement["id"] == proposal.target_id
            or replacement["space_id"] != proposal.space_id
        ):
            raise ValueError("Merge/supersede needs a distinct replacement in the same space")
        if proposal.replacement_id not in {ref.id for ref in proposal.source_refs}:
            raise ValueError("Replacement must be cited as evidence")
    if proposal.operation == "move" and not proposal.destination_space_id:
        raise ValueError("A move needs a destination space")
    if proposal.operation in {"profile", "summary", "update"} and (
        not proposal.body or not proposal.title
    ):
        raise ValueError("Profile and summary changes need a title and body")
    if proposal.operation == "update" and evidence[proposal.target_id].get("record_type") == "fact":
        raise ValueError(
            "Maintenance must preserve original factual records; propose a derived summary instead"
        )
    if (
        proposal.operation in {"profile", "summary"}
        and proposal.target_id
        and evidence[proposal.target_id].get("record_type") == "fact"
    ):
        raise ValueError("Original facts cannot be overwritten as profiles")
    if proposal.operation in {"profile", "summary", "update"}:
        if proposal.target_id in {ref.id for ref in proposal.source_refs}:
            raise ValueError("A derived record cannot cite itself")
        # At least one original fact is necessary; summary echoes add no independent evidence.
        if not any(
            evidence[ref.id].get("record_type", "fact") == "fact" for ref in proposal.source_refs
        ):
            raise ValueError("Derived output needs original fact evidence")


def decide(proposal_id: str, approve: bool, *, automatic: bool = False) -> dict:
    with connection() as conn:
        row = conn.execute("SELECT * FROM advanced_proposals WHERE id=?", (proposal_id,)).fetchone()
    if row is None:
        raise ValueError("Proposal not found")
    proposal_row = store.decode(row)
    if proposal_row["state"] != "pending":
        return proposal_row
    job = store.get_job(proposal_row["job_id"])
    if not approve:
        with connection() as conn:
            conn.execute(
                "UPDATE advanced_proposals SET state='rejected',updated_at=? WHERE id=? AND state='pending'",
                (store.now(), proposal_id),
            )
        return next(item for item in store.list_proposals(job["id"]) if item["id"] == proposal_id)
    proposal = Proposal.model_validate(proposal_row["payload"])
    if proposal.operation == "question":
        raise ValueError(
            "Resolve this question through confirmed guidance, then reject it or run another review"
        )
    if automatic and (proposal.operation == "move" or proposal.uncertainty):
        return proposal_row
    validate_proposal(job, proposal, current=True)

    def guard(conn):
        state = conn.execute("SELECT * FROM advanced_state WHERE id=1").fetchone()
        config = json.loads(state["config"])
        if not config["enabled"] or state["generation"] != job["generation"]:
            raise ValueError("Advanced Memory settings changed; request a fresh review")
        if store.placement_context(config)[1] != job["config"].get("guidance_hash"):
            raise ValueError("Confirmed placement guidance changed; request a fresh review")
        saved = conn.execute(
            "SELECT state FROM advanced_proposals WHERE id=?", (proposal_id,)
        ).fetchone()
        if saved["state"] != "pending":
            raise ValueError("Proposal has already been processed")
        # These checks share the memory write transaction, including merge and move operations.
        for ref in proposal.source_refs:
            source = conn.execute(
                "SELECT version,space_id FROM memories WHERE id=?", (ref.id,)
            ).fetchone()
            if (
                not source
                or source["version"] != ref.version
                or source["space_id"] != proposal.space_id
            ):
                raise ValueError("Source evidence changed; request a fresh review")
        current_scope = set(config["space_ids"])
        if proposal.space_id not in current_scope or (
            proposal.destination_space_id and proposal.destination_space_id not in current_scope
        ):
            raise ValueError("Proposal exceeds current maintenance permissions")

    def on_commit(conn, result):
        conn.execute(
            "UPDATE advanced_proposals SET state='applied',updated_at=?,result=?,error=NULL WHERE id=?",
            (
                store.now(),
                json.dumps({"memory_id": result["id"], "version": result["version"]}),
                proposal_id,
            ),
        )

    def apply_update(data):
        # A repeated recommendation with identical fields must not create an endless
        # version-change/review cycle. This is equality, not a semantic merge decision.
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            guard(conn)
            row = conn.execute(
                "SELECT * FROM memories WHERE id=?", (proposal.target_id,)
            ).fetchone()
            if row and row["version"] == proposal.expected_version:
                existing = core.decode(row)
                if all(existing.get(key) == value for key, value in data.items()):
                    on_commit(conn, existing)
                    return
        core.update_memory(
            core.ADMIN,
            proposal.target_id,
            data,
            proposal.expected_version,
            "Advanced Memory: " + proposal.reason,
            guard=guard,
            on_commit=on_commit,
        )

    refs = [ref.model_dump() for ref in proposal.source_refs]
    if proposal.operation in {"profile", "summary", "update"}:
        data = {
            "title": proposal.title,
            "body": proposal.body,
            "summary": proposal.summary,
            "source_refs": refs,
            "stale": False,
            "subject_ids": proposal.subject_ids,
        }
        if proposal.operation != "update":
            data["record_type"] = proposal.operation
        if proposal.target_id:
            apply_update(data)
        else:
            data.update(
                space_id=proposal.space_id,
                source="Advanced Memory",
                metadata={"advanced_job_id": job["id"], "prompt_version": job["prompt_version"]},
            )
            core.create_memory(
                core.ADMIN, data, "advanced:" + proposal_id, guard=guard, on_commit=on_commit
            )
    else:
        data = (
            {"space_id": proposal.destination_space_id, "subject_ids": proposal.subject_ids}
            if proposal.operation == "move"
            else {
                "merged_into"
                if proposal.operation == "merge"
                else "superseded_by": proposal.replacement_id
            }
        )
        apply_update(data)
    return next(item for item in store.list_proposals(job["id"]) if item["id"] == proposal_id)
