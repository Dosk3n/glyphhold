from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import signal
import tempfile
import time
from pathlib import Path

from app.advanced.models import RunnerOutput
from app.config import settings


class CodexError(RuntimeError):
    pass


class CodexRunner:
    """Official CLI only; isolated login, no API keys, no shell or connected tools."""

    def __init__(self, data_dir: Path | None = None, executable: str = "codex"):
        self.data_dir = data_dir
        self.executable = executable
        self.login_task: asyncio.Task | None = None
        self.login_process: asyncio.subprocess.Process | None = None
        self.run_process: asyncio.subprocess.Process | None = None
        self.catalog: list[dict] = []
        self.catalog_checked_at = 0.0
        self.login = {"state": "idle", "message": "Not signing in", "url": None, "code": None}

    @property
    def home(self) -> Path:
        return self.data_dir or settings.db_path.parent / "advanced" / "codex"

    def environment(self) -> dict:
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.home.chmod(0o700)
        self.own(self.home)
        # Deliberately do not inherit API credentials, proxy tokens, user skills or MCP config.
        allowed = ("PATH", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS")
        env = {key: os.environ[key] for key in allowed if key in os.environ}
        env.update(
            CODEX_HOME=str(self.home.resolve()),
            HOME=str(self.home.resolve()),
            NO_COLOR="1",
            TERM="dumb",
        )
        return env

    def process_identity(self) -> dict:
        uid = os.environ.get("GLYPHHOLD_WORKER_UID")
        gid = os.environ.get("GLYPHHOLD_WORKER_GID")
        if uid is None:
            return {}
        uid = int(uid)
        gid = int(gid or uid)
        if os.geteuid() != 0:
            if os.geteuid() != uid:
                raise CodexError("Cannot drop Codex worker privileges with this container user")
            return {}
        return {"user": uid, "group": gid, "extra_groups": []}

    def own(self, path: Path) -> None:
        identity = self.process_identity()
        if identity:
            os.chown(path, identity["user"], identity["group"])

    def installed(self) -> bool:
        return bool(shutil.which(self.executable))

    async def authentication(self) -> dict:
        if not self.installed():
            return {"installed": False, "authenticated": False, "auth_mode": None}
        try:
            process = await asyncio.create_subprocess_exec(
                self.executable,
                "login",
                "status",
                env=self.environment(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
                **self.process_identity(),
            )
            try:
                out, err = await asyncio.wait_for(process.communicate(), 10)
            except TimeoutError:
                await self.terminate(process)
                return {"installed": True, "authenticated": False, "auth_mode": None}
            message = (out + err).decode(errors="replace").lower()
            subscription = process.returncode == 0 and "chatgpt" in message
            return {
                "installed": True,
                "authenticated": subscription,
                "auth_mode": "chatgpt" if subscription else None,
            }
        except (OSError, ValueError, NotImplementedError):
            return {
                "installed": self.installed(),
                "authenticated": False,
                "auth_mode": None,
                "runner_error": "Codex cannot start with this server runtime; use the supported image with the standard asyncio event loop",
            }

    def models(self) -> list[dict]:
        result = [{"id": "", "label": "Codex account default", "reasoning_levels": []}]
        if self.catalog:
            return result + self.catalog
        # CLI maintains this supported catalog; avoid claiming account access to a hardcoded model.
        try:
            cache = json.loads((self.home / "models_cache.json").read_text())
            for model in cache.get("models", []):
                if model.get("visibility") == "hide":
                    continue
                model_id = model.get("slug") or model.get("id")
                if not isinstance(model_id, str):
                    continue
                levels = [
                    level.get("effort")
                    for level in model.get("supported_reasoning_levels", [])
                    if isinstance(level, dict) and level.get("effort")
                ]
                result.append(
                    {
                        "id": model_id,
                        "label": model.get("display_name", model_id),
                        "reasoning_levels": levels,
                    }
                )
        except (OSError, ValueError, TypeError):
            pass
        return result

    async def refresh_models(self) -> None:
        """Read the official app-server model catalog, without starting a model turn."""
        if self.catalog_checked_at and time.monotonic() - self.catalog_checked_at < 900:
            return
        self.catalog_checked_at = time.monotonic()
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                self.executable,
                "app-server",
                "--listen",
                "stdio://",
                "-c",
                'forced_login_method="chatgpt"',
                env=self.environment(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
                **self.process_identity(),
            )

            async def request():
                messages = [
                    {
                        "id": 1,
                        "method": "initialize",
                        "params": {"clientInfo": {"name": "glyphhold", "version": "2.0.0"}},
                    },
                ]
                process.stdin.write((json.dumps(messages[0]) + "\n").encode())
                await process.stdin.drain()
                size = 0
                while line := await process.stdout.readline():
                    size += len(line)
                    if size > 2_000_000:
                        return
                    response = json.loads(line)
                    if response.get("id") == 1:
                        process.stdin.write(b'{"method":"initialized"}\n')
                        process.stdin.write(
                            b'{"id":2,"method":"model/list","params":{"limit":100}}\n'
                        )
                        await process.stdin.drain()
                    if response.get("id") == 2:
                        rows = (response.get("result") or {}).get("data", [])
                        self.catalog = [
                            {
                                "id": row.get("model") or row["id"],
                                "label": row.get("displayName") or row.get("model") or row["id"],
                                "reasoning_levels": [
                                    effort["reasoningEffort"]
                                    for effort in row.get("supportedReasoningEfforts", [])
                                ],
                            }
                            for row in rows
                            if isinstance(row, dict) and (row.get("model") or row.get("id"))
                        ]
                        return

            await asyncio.wait_for(request(), 20)
        except (OSError, TimeoutError, ValueError, KeyError, TypeError):
            # A failed metadata lookup must not initiate inference or block core memory.
            return
        finally:
            await self.terminate(process)

    async def begin_login(self) -> dict:
        if not self.installed():
            raise CodexError("Codex CLI is not installed in this image")
        if self.login_task and not self.login_task.done():
            return dict(self.login)
        self.login = {
            "state": "starting",
            "message": "Starting official device sign-in",
            "url": None,
            "code": None,
        }
        self.login_task = asyncio.create_task(self._login())
        return dict(self.login)

    async def _login(self) -> None:
        try:
            self.login_process = await asyncio.create_subprocess_exec(
                self.executable,
                "login",
                "--device-auth",
                env=self.environment(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
                **self.process_identity(),
            )

            async def read() -> None:
                text = ""
                while True:
                    line = await self.login_process.stdout.readline()
                    if not line:
                        break
                    text = (text + line.decode(errors="replace"))[-16000:]
                    clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
                    urls = re.findall(
                        r"https://(?:auth\.openai\.com|chatgpt\.com)/[^\s<>\x1b]+", clean
                    )
                    codes = re.findall(r"\b[A-Z0-9]{4,6}-[A-Z0-9]{4,6}\b", clean)
                    if urls:
                        self.login.update(
                            state="waiting",
                            message="Open the official link and enter the device code",
                            url=urls[-1],
                            code=codes[-1] if codes else None,
                        )
                await self.login_process.wait()

            await asyncio.wait_for(read(), 900)
            auth = await self.authentication()
            if auth["authenticated"]:
                self.login = {
                    "state": "authenticated",
                    "message": "Signed in with ChatGPT",
                    "url": None,
                    "code": None,
                }
            else:
                self.login = {
                    "state": "failed",
                    "message": "Device sign-in failed or expired. Enable device-code sign-in in your account if required, then try again.",
                    "url": None,
                    "code": None,
                }
        except asyncio.CancelledError:
            await self.terminate(self.login_process)
            self.login = {
                "state": "cancelled",
                "message": "Sign-in cancelled",
                "url": None,
                "code": None,
            }
            raise
        except (TimeoutError, OSError, ValueError, NotImplementedError):
            await self.terminate(self.login_process)
            self.login = {
                "state": "failed",
                "message": "Unable to complete device sign-in",
                "url": None,
                "code": None,
            }
        finally:
            self.login_process = None

    async def cancel_login(self) -> None:
        if self.login_task and not self.login_task.done():
            self.login_task.cancel()
            await asyncio.gather(self.login_task, return_exceptions=True)

    async def logout(self) -> None:
        await self.cancel_login()
        self.catalog = []
        self.catalog_checked_at = 0
        if self.installed():
            process = await asyncio.create_subprocess_exec(
                self.executable,
                "logout",
                env=self.environment(),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
                **self.process_identity(),
            )
            try:
                await asyncio.wait_for(process.wait(), 10)
            except TimeoutError:
                await self.terminate(process)
        self.login = {"state": "idle", "message": "Signed out", "url": None, "code": None}

    @staticmethod
    async def terminate(process) -> None:
        if process is None or process.returncode is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), 3)
        except TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()

    async def execute(self, prompt: str, config: dict, cancelled) -> RunnerOutput:
        self.last_usage = None
        if not (await self.authentication())["authenticated"]:
            raise CodexError(
                "Codex requires ChatGPT subscription sign-in; paid API fallback is disabled"
            )
        with tempfile.TemporaryDirectory(prefix="gh2-maintenance-") as tmp:
            directory = Path(tmp)
            schema = directory / "output-schema.json"
            output = directory / "result.json"
            contract = RunnerOutput.model_json_schema()

            def strict(node):
                if isinstance(node, dict):
                    if node.get("type") == "object":
                        node["additionalProperties"] = False
                        node["required"] = list(node.get("properties", {}))
                    for value in node.values():
                        strict(value)
                elif isinstance(node, list):
                    for value in node:
                        strict(value)

            strict(contract)
            schema.write_text(json.dumps(contract))
            self.own(directory)
            self.own(schema)
            args = [
                self.executable,
                "--ask-for-approval",
                "never",
                "exec",
                "--ignore-user-config",
                "--ignore-rules",
                "--skip-git-repo-check",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--color",
                "never",
                "--json",
                "--output-schema",
                str(schema),
                "--output-last-message",
                str(output),
                "--cd",
                str(directory),
                "-c",
                'web_search="disabled"',
                "-c",
                'forced_login_method="chatgpt"',
            ]
            for feature in (
                "shell_tool",
                "unified_exec",
                "apps",
                "browser_use",
                "computer_use",
                "code_mode",
                "multi_agent",
                "memories",
            ):
                args += ["--disable", feature]
            if config["model"]:
                args += ["--model", config["model"]]
            if config["reasoning"] != "default":
                args += ["-c", "model_reasoning_effort=" + json.dumps(config["reasoning"])]
            args += ["-"]
            self.run_process = await asyncio.create_subprocess_exec(
                *args,
                env=self.environment(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
                **self.process_identity(),
            )
            process = self.run_process
            # Bound output in memory; raw agent events are never persisted or returned to clients.
            usage = None

            async def drain(stream, events=False):
                nonlocal usage
                size = 0
                tail = b""
                pending = b""
                while chunk := await stream.read(8192):
                    size += len(chunk)
                    if size > 2_000_000:
                        raise CodexError("Codex output exceeded the run limit")
                    tail = (tail + chunk)[-32000:]
                    if events:
                        pending += chunk
                        lines = pending.split(b"\n")
                        pending = lines.pop()
                        for line in lines:
                            try:
                                event = json.loads(line)
                                if event.get("type") == "turn.completed":
                                    usage = event.get("usage")
                            except (ValueError, AttributeError):
                                pass
                return tail

            async def communicate():
                process.stdin.write(prompt.encode())
                await process.stdin.drain()
                process.stdin.close()
                stdout, stderr = await asyncio.gather(
                    drain(process.stdout, True), drain(process.stderr)
                )
                await process.wait()
                return stdout, stderr

            task = asyncio.create_task(communicate())
            started = asyncio.get_running_loop().time()
            try:
                while not task.done():
                    if cancelled():
                        raise CodexError("Run cancelled or settings changed")
                    if asyncio.get_running_loop().time() - started > config["timeout_seconds"]:
                        raise CodexError("Codex run exceeded the configured time limit")
                    await asyncio.sleep(0.25)
                stdout, stderr = await task
                if process.returncode:
                    message = (stdout + stderr).decode(errors="replace").lower()
                    if any(
                        word in message
                        for word in ("quota", "usage limit", "rate limit", "limit reached")
                    ):
                        raise CodexError(
                            "Codex subscription allowance unavailable; run paused until you resume"
                        )
                    if "model" in message and any(
                        word in message for word in ("support", "available", "invalid")
                    ):
                        raise CodexError(
                            "Selected model or reasoning level is unavailable for this account; adjust Settings"
                        )
                    raise CodexError(
                        "Codex execution failed. Check subscription sign-in, selected model and server connectivity; no API fallback was attempted"
                    )
                if not output.exists() or output.stat().st_size > 512000:
                    raise CodexError("Codex did not return a bounded structured result")
                result = RunnerOutput.model_validate_json(output.read_text())
                self.last_usage = usage
                return result
            finally:
                await self.terminate(process)
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                self.run_process = None
