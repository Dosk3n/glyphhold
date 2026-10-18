from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from app.advanced.models import AdvancedSettings
from app.advanced.schedule import next_occurrence
from app.storage.db import connection


def now() -> str:
    return datetime.now(UTC).isoformat()


def decode(row) -> dict | None:
    if row is None:
        return None
    result = dict(row)
    for key in ("config", "evidence", "result", "payload"):
        if key in result:
            result[key] = json.loads(result[key]) if result[key] else None
    return result


def initialize() -> None:
    with connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS advanced_state (
          id INTEGER PRIMARY KEY CHECK(id=1), config TEXT NOT NULL,
          generation INTEGER NOT NULL DEFAULT 1, next_run TEXT, paused_reason TEXT
        );
        CREATE TABLE IF NOT EXISTS advanced_jobs (
          id TEXT PRIMARY KEY, state TEXT NOT NULL, created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL, trigger TEXT NOT NULL, full_review INTEGER NOT NULL,
          generation INTEGER NOT NULL, config TEXT NOT NULL, evidence TEXT,
          lease_owner TEXT, lease_until TEXT, error TEXT, result TEXT,
          prompt_version TEXT NOT NULL DEFAULT 'gh2-maintenance-1', attempts INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS advanced_processed (
          memory_id TEXT PRIMARY KEY, version INTEGER NOT NULL, reviewed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS advanced_proposals (
          id TEXT PRIMARY KEY, job_id TEXT NOT NULL, state TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          payload TEXT NOT NULL, result TEXT, error TEXT,
          FOREIGN KEY(job_id) REFERENCES advanced_jobs(id)
        );
        """)
        conn.execute(
            "INSERT OR IGNORE INTO advanced_state(id,config) VALUES(1,?)",
            (AdvancedSettings().model_dump_json(),),
        )
        if "guidance_hash" not in {r[1] for r in conn.execute("PRAGMA table_info(advanced_state)")}:
            conn.execute(
                "ALTER TABLE advanced_state ADD COLUMN guidance_hash TEXT NOT NULL DEFAULT ''"
            )


def placement_context(config: dict) -> tuple[list[dict], str]:
    from app.v2 import core

    permitted = set(config["space_ids"])
    guidance = [item for item in core.guidance(core.ADMIN) if item["space_id"] in permitted]
    subjects = [item for item in core.subjects(core.ADMIN) if item["space_id"] in permitted]
    spaces = [item for item in core.list_spaces(core.ADMIN) if item["id"] in permitted]
    text = json.dumps(
        {
            "guidance": guidance,
            "subjects": subjects,
            "spaces": spaces,
            "configured": config.get("guidance", []),
        },
        sort_keys=True,
    )
    return guidance, hashlib.sha256(text.encode()).hexdigest()


def settings() -> dict:
    initialize()
    with connection() as conn:
        row = conn.execute("SELECT * FROM advanced_state WHERE id=1").fetchone()
    result = json.loads(row["config"])
    result.update(
        next_run=row["next_run"], generation=row["generation"], paused_reason=row["paused_reason"]
    )
    return result


def save_settings(config: AdvancedSettings) -> dict:
    initialize()
    upcoming = next_occurrence(config.model_dump()).isoformat() if config.enabled else None
    with connection() as conn:
        previous = json.loads(
            conn.execute("SELECT config FROM advanced_state WHERE id=1").fetchone()[0]
        )
        if (
            previous.get("space_ids") != config.space_ids
            or previous.get("guidance") != config.guidance
        ):
            conn.execute("DELETE FROM advanced_processed")
        conn.execute(
            """UPDATE advanced_state SET config=?,generation=generation+1,
                     next_run=?,paused_reason=NULL WHERE id=1""",
            (config.model_dump_json(), upcoming),
        )
        # Any scope/policy edit invalidates running snapshots, not just disablement.
        conn.execute(
            """UPDATE advanced_jobs SET state='cancelled', updated_at=?,
                     error='Settings changed; run again with current policy'
                     WHERE state IN ('queued','running')""",
            (now(),),
        )
    return settings()


def enqueue(full_review: bool = False, trigger: str = "manual") -> dict:
    config = settings()
    if not config["enabled"]:
        raise ValueError("Enable Advanced Memory before starting a run")
    guidance, guidance_hash = placement_context(config)
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM advanced_jobs WHERE state IN ('queued','running')"
            " ORDER BY created_at LIMIT 1"
        ).fetchone()
        if existing:
            return decode(existing)
        job_id = "adv_" + (
            hashlib.sha256((trigger + str(config["generation"])).encode()).hexdigest()
            if trigger.startswith("scheduled:")
            else uuid.uuid4().hex
        )
        clean = AdvancedSettings.model_validate(
            {k: config[k] for k in AdvancedSettings.model_fields}
        )
        timestamp = now()
        snapshot = clean.model_dump() | {
            "confirmed_guidance": guidance,
            "guidance_hash": guidance_hash,
        }
        from app.v2 import core

        snapshot["subjects"] = [
            {key: item.get(key) for key in ("id", "space_id", "name", "kind", "aliases")}
            for item in core.subjects(core.ADMIN)
            if item["space_id"] in clean.space_ids
        ]
        previous_hash = conn.execute(
            "SELECT guidance_hash FROM advanced_state WHERE id=1"
        ).fetchone()[0]
        if full_review or previous_hash != guidance_hash:
            # A full review resets the scoped backlog once; every run remains bounded.
            for space_id in clean.space_ids:
                conn.execute(
                    "DELETE FROM advanced_processed WHERE memory_id IN (SELECT id FROM memories WHERE space_id=?)",
                    (space_id,),
                )
        conn.execute("UPDATE advanced_state SET guidance_hash=? WHERE id=1", (guidance_hash,))
        conn.execute(
            """INSERT OR IGNORE INTO advanced_jobs
            (id,state,created_at,updated_at,trigger,full_review,generation,config)
            VALUES(?,'queued',?,?,?,?,?,?)""",
            (
                job_id,
                timestamp,
                timestamp,
                trigger,
                int(full_review),
                config["generation"],
                json.dumps(snapshot),
            ),
        )
        conn.execute("UPDATE advanced_state SET paused_reason=NULL WHERE id=1")
    return get_job(job_id)


def get_job(job_id: str) -> dict | None:
    with connection() as conn:
        return decode(conn.execute("SELECT * FROM advanced_jobs WHERE id=?", (job_id,)).fetchone())


def list_jobs(limit: int = 50) -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM advanced_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [{k: v for k, v in decode(row).items() if k != "evidence"} for row in rows]


def claim(owner: str) -> dict | None:
    config = settings()
    if not config["enabled"] or config["paused_reason"]:
        return None
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        # Expired execution is paused for explicit retry; never duplicate a live Codex invocation.
        conn.execute(
            """UPDATE advanced_jobs SET state='paused',error='Worker lease expired; resume explicitly',
                        updated_at=? WHERE state='running' AND lease_until<?""",
            (now(), now()),
        )
        if conn.execute("SELECT 1 FROM advanced_jobs WHERE state='running'").fetchone():
            return None
        row = conn.execute(
            "SELECT * FROM advanced_jobs WHERE state='queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        lease = (datetime.now(UTC) + timedelta(seconds=config["timeout_seconds"] + 120)).isoformat()
        conn.execute(
            "UPDATE advanced_jobs SET state='running',lease_owner=?,lease_until=?,"
            "attempts=attempts+1,updated_at=? WHERE id=?",
            (owner, lease, now(), row["id"]),
        )
    return get_job(row["id"])


def update_job(job_id: str, state: str, *, evidence=None, result=None, error=None) -> None:
    with connection() as conn:
        conn.execute(
            """UPDATE advanced_jobs SET state=?,updated_at=?,evidence=COALESCE(?,evidence),
                    result=COALESCE(?,result),error=?,lease_until=CASE WHEN ?='running' THEN lease_until ELSE NULL END WHERE id=?""",
            (
                state,
                now(),
                json.dumps(evidence) if evidence is not None else None,
                json.dumps(result) if result is not None else None,
                error,
                state,
                job_id,
            ),
        )


def cancellation(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise ValueError("Run not found")
    if job["state"] in {"queued", "running", "paused"}:
        update_job(job_id, "cancelled", error="Cancelled by administrator")
    return get_job(job_id)


def resume(job_id: str) -> dict:
    job = get_job(job_id)
    if not job or job["state"] not in {"paused", "failed", "cancelled"}:
        raise ValueError("Only paused, failed or cancelled runs can resume")
    return enqueue(full_review=bool(job["full_review"]), trigger="resume:" + job_id)


def processed() -> dict[str, int]:
    with connection() as conn:
        return {
            r["memory_id"]: r["version"] for r in conn.execute("SELECT * FROM advanced_processed")
        }


def finish(
    job_id: str, evidence: list[dict], proposals: list[dict], notes: str, *, usage=None
) -> list[dict]:
    """Persist proposals and processed versions with completion, once per job."""
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        job = conn.execute("SELECT * FROM advanced_jobs WHERE id=?", (job_id,)).fetchone()
        state = conn.execute("SELECT * FROM advanced_state WHERE id=1").fetchone()
        if not job or job["state"] != "running" or job["generation"] != state["generation"]:
            raise ValueError("Run cancelled or policy changed before results arrived")
        created = []
        for index, payload in enumerate(proposals):
            pid = f"{job_id}_{index}"
            conn.execute(
                "INSERT INTO advanced_proposals VALUES(?,?,'pending',?,?,?,NULL,NULL)",
                (pid, job_id, now(), now(), json.dumps(payload)),
            )
            created.append(pid)
        for item in evidence:
            conn.execute(
                "INSERT OR REPLACE INTO advanced_processed VALUES(?,?,?)",
                (item["id"], item["version"], now()),
            )
        conn.execute(
            "UPDATE advanced_jobs SET state='completed',updated_at=?,lease_until=NULL,"
            "result=? WHERE id=?",
            (now(), json.dumps({"proposal_ids": created, "notes": notes, "usage": usage}), job_id),
        )
    return list_proposals(job_id)


def list_proposals(job_id: str | None = None) -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM advanced_proposals "
            + ("WHERE job_id=? " if job_id else "")
            + "ORDER BY CASE WHEN state='pending' THEN 0 ELSE 1 END, created_at DESC LIMIT 200",
            (job_id,) if job_id else (),
        ).fetchall()
    return [decode(row) for row in rows]


def pending_approval_count() -> int:
    with connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM advanced_proposals "
            "WHERE state='pending' AND COALESCE(json_extract(payload, '$.operation'), '') != 'question'"
        ).fetchone()[0]


def pause(reason: str) -> None:
    with connection() as conn:
        conn.execute("UPDATE advanced_state SET paused_reason=? WHERE id=1", (reason,))


def schedule_due() -> dict | None:
    config = settings()
    if not config["enabled"] or config["paused_reason"] or not config["next_run"]:
        return None
    if datetime.fromisoformat(config["next_run"]) > datetime.now(UTC):
        return None
    # enqueue deduplicates manual/scheduled overlap; advance after downtime in one step.
    job = enqueue(trigger="scheduled:" + config["next_run"])
    with connection() as conn:
        conn.execute(
            "UPDATE advanced_state SET next_run=? WHERE id=1",
            (next_occurrence(config).isoformat(),),
        )
    return job
