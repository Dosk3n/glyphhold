from __future__ import annotations

import asyncio
import uuid

from app.advanced import service, store
from app.advanced.codex import CodexRunner
from app.advanced.prompt import build_prompt
from app.v2 import core


class AdvancedWorker:
    def __init__(self, runner=None):
        self.runner = runner or CodexRunner()
        self.owner = uuid.uuid4().hex
        self.task: asyncio.Task | None = None
        self.stopping = False

    async def start(self):
        store.initialize()
        self.stopping = False
        if not self.task or self.task.done():
            self.task = asyncio.create_task(self.loop())

    async def stop(self):
        self.stopping = True
        await self.runner.cancel_login()
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        await self.runner.terminate(self.runner.run_process)

    async def loop(self):
        while not self.stopping:
            try:
                store.schedule_due()
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - isolate scheduler failures without leaking evidence
                # No source content, credentials or raw CLI output belongs in application logs.
                await asyncio.sleep(3)
            await asyncio.sleep(2)

    async def run_once(self) -> dict | None:
        job = store.claim(self.owner)
        if not job:
            return None
        try:
            evidence, spaces = service.job_records(job)
            if not evidence:
                store.update_job(
                    job["id"],
                    "skipped",
                    result={"reason": "No changed source memories; no AI call"},
                )
                return store.get_job(job["id"])
            store.update_job(job["id"], "running", evidence=evidence)
            job = store.get_job(job["id"])
            # update_job clears leases on terminal transitions only.
            prompt = build_prompt(job, evidence, spaces)

            def cancelled():
                current = store.get_job(job["id"])
                return self.stopping or not current or current["state"] != "running"

            output = await self.runner.execute(prompt, job["config"], cancelled)
            if cancelled():
                return store.get_job(job["id"])
            for proposal in output.proposals:
                service.validate_proposal(job, proposal)
            sources = [item for item in evidence if not item.get("context_only")]
            proposals = store.finish(
                job["id"],
                sources,
                [item.model_dump() for item in output.proposals],
                output.notes,
                usage=getattr(self.runner, "last_usage", None),
            )
            if job["config"]["execution_policy"] == "automatic":
                for proposal in proposals:
                    try:
                        service.decide(proposal["id"], True, automatic=True)
                    except (ValueError, core.SpaceError) as exc:
                        with store.connection() as conn:
                            conn.execute(
                                "UPDATE advanced_proposals SET error=? WHERE id=?",
                                (str(exc), proposal["id"]),
                            )
            return store.get_job(job["id"])
        except asyncio.CancelledError:
            current = store.get_job(job["id"])
            if current and current["state"] == "running":
                store.update_job(
                    job["id"], "paused", error="Worker stopped; resume the run when ready"
                )
            raise
        except Exception as exc:  # noqa: BLE001 - persist a safe failed-job outcome
            current = store.get_job(job["id"])
            if current and current["state"] == "running":
                # Only our bounded exceptions are safe to show; no raw subprocess stderr.
                from app.advanced.codex import CodexError

                message = (
                    str(exc)
                    if isinstance(exc, (CodexError, ValueError, core.SpaceError))
                    else "Maintenance failed safely; review configuration and retry"
                )
                store.update_job(job["id"], "paused", error=message)
                store.pause(message)
            return store.get_job(job["id"])


worker = AdvancedWorker()
