"""Agent Codex local, pilote alternatif de la boucle vocale.

Codex ne se pilote pas comme Claude. `claude -p --input-format stream-json`
tient un processus ouvert dans lequel on écrit tour après tour ; `codex exec`
est one-shot : un processus par question, et la continuité du fil passe par
`codex exec resume <thread_id>`.

Cette classe expose malgré tout la même surface que `ClaudeLocalAgent`, parce
que c'est elle que le Control Center et la passerelle vocale appellent. Ce qui
n'existe pas chez Codex est déclaré absent plutôt que simulé : il n'y a pas de
PID permanent, et la console interactive n'est pas une passation de main.

Le format d'événements ci-dessous est celui réellement émis par
`codex exec --json` (JSONL : thread.started, turn.started, item.completed,
turn.completed / turn.failed), pas une supposition.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any

from jarvis.runtime.cli_stream import MAX_LINE_BYTES, OversizeLine, clip_text, iter_lines, journal_view, may_carry_media, redact_media
from jarvis.runtime.agent_tasks import AgentTaskTracker, describe_tool
from jarvis.runtime.claude_local import CREATE_NEW_CONSOLE, raise_console_window
from jarvis.runtime.cli_catalog import CODEX_SANDBOX_MODES, resolve_command
from jarvis.runtime.journal import RuntimeJournal

DEFAULT_SANDBOX_MODE = "danger-full-access"


def normalize_sandbox_mode(value: object) -> str:
    mode = str(value or "").strip()
    return mode if mode in CODEX_SANDBOX_MODES else DEFAULT_SANDBOX_MODE


class CodexLocalAgent:
    def __init__(
        self,
        *,
        runtime_root: Path,
        cwd: Path,
        command: str = "codex",
        permission_mode: str = DEFAULT_SANDBOX_MODE,
        model: str = "",
        execution_profile: str = "conversation",
        prompt_overrides: object | None = None,
    ) -> None:
        self.runtime_root = runtime_root
        self.cwd = cwd
        self.command = command
        # Nommé `permission_mode` comme chez Claude : c'est le champ que le
        # Control Center écrit. Chez Codex il désigne le bac à sable.
        self.permission_mode = normalize_sandbox_mode(permission_mode)
        self.model = str(model or "").strip()
        from jarvis.runtime.prompt_runtime import normalize_prompt_overrides
        self._prompt_overrides = normalize_prompt_overrides(prompt_overrides)
        self.prompt_applications: list[dict[str, object]] = []
        self._next_prompt_evidence: dict[str, object] | None = None
        self.journal = RuntimeJournal(runtime_root)
        self.process: asyncio.subprocess.Process | None = None
        self.session_id: str | None = None
        self._events: list[dict[str, Any]] = []
        self._event_times: list[int] = []
        # Même suivi que chez Claude, réduit au brain : aucun format de
        # sous-tâche Codex n'a été relevé, rien n'est donc déduit du flux.
        # `busy` suit le processus du tour, le seul signal certain.
        self.subtasks = AgentTaskTracker(provider="codex", journal=self.journal, formatter=self._transcript_entry)
        self._started = False
        self._turn_lock = asyncio.Lock()
        self._console: subprocess.Popen | None = None
        self._background: asyncio.Task[None] | None = None
        self._last_returncode: int | None = None
        self._process_lock = asyncio.Lock()
        self._owned_closed = False
        self._owned_root_closed = False
        self._job_started = asyncio.Event()
        if execution_profile not in {"conversation", "job_result"}:
            raise ValueError("unknown Codex execution profile")
        self._process_tree = None
        if execution_profile == "job_result":
            from jarvis.runtime.owned_process_tree import OwnedProcessTree
            self._process_tree = OwnedProcessTree()

    # ------------------------------------------------------------------ état

    @property
    def state(self) -> str:
        if self.process is not None and self.process.returncode is None:
            return "running"
        return "ready" if self._started else "stopped"

    def snapshot(self) -> dict[str, Any]:
        running = self.process is not None and self.process.returncode is None
        return {
            "name": "Codex",
            "state": self.state,
            "pid": self.process.pid if running and self.process else None,
            "returncode": self._last_returncode,
            "events": self._events[-80:],
            "session_id": self.session_id,
            "permission_mode": self.permission_mode,
            "model": self.model,
            "console": self.console_snapshot(),
        }

    def console_snapshot(self) -> dict[str, Any]:
        process = self._console
        running = process is not None and process.poll() is None
        return {
            "open": running,
            "pid": process.pid if running and process is not None else None,
            "session_id": self.session_id,
            "supported": os.name == "nt",
        }

    def _record(self, event: dict[str, Any]) -> None:
        thread_id = event.get("thread_id")
        if isinstance(thread_id, str) and thread_id:
            self.session_id = thread_id
        try:
            self._note_activity(event)
        except Exception as exc:  # noqa: BLE001
            # Comme chez Claude : la lecture du tour ne doit jamais mourir pour
            # une activité affichée dans le panneau Agents.
            self.subtasks.report_failure(exc, event)
        self._events.append(event)
        self._event_times.append(self.subtasks.now_ms())
        if len(self._events) > 500:
            del self._events[:-500]
            del self._event_times[:-500]

    def _note_activity(self, event: dict[str, Any]) -> None:
        """Dernière action du tour, lue sur les éléments déjà rendus par le transcript."""
        if event.get("type") != "item.completed" or not isinstance(event.get("item"), dict):
            return
        item = event["item"]
        item_type = item.get("type")
        if item_type == "command_execution":
            self.subtasks.note_brain_activity(describe_tool("Commande", {"command": str(item.get("command") or "")}))
        elif item_type == "mcp_tool_call":
            self.subtasks.note_brain_activity(f"Outil · {item.get('server') or ''} {item.get('tool') or ''}".strip())
        elif item_type == "file_change":
            self.subtasks.note_brain_activity("Fichiers modifiés")

    def tasks_snapshot(self) -> dict[str, Any]:
        """Même forme que chez Claude : le brain, et aucune sous-tâche connue."""
        return self.subtasks.payload(state=self.state, session_id=self.session_id, configured_model=self.model)

    def task_trace(self, task_id: str, *, limit: int = 300) -> dict[str, Any] | None:
        if task_id == "brain":
            brain = self.subtasks.brain_snapshot(state=self.state, session_id=self.session_id, configured_model=self.model)
            return {"task": brain, "entries": self.transcript(limit=limit)}
        return self.subtasks.trace(task_id, limit=limit)

    # ------------------------------------------------------------- historique

    def transcript(self, *, limit: int = 200) -> list[dict[str, Any]]:
        events = self._events[-limit:]
        times = self._event_times[-limit:]
        return [{**self._transcript_entry(event), "ts_ms": ts} for event, ts in zip(events, times)]

    @staticmethod
    def _transcript_entry(event: dict[str, Any]) -> dict[str, Any]:
        kind = str(event.get("type") or "event")
        entry: dict[str, Any] = {"role": kind, "title": kind, "text": "", "status": "ok", "raw": event}

        if kind == "thread.started":
            entry["role"], entry["title"] = "system", "Fil Codex"
            entry["text"] = str(event.get("thread_id") or "")
        elif kind == "turn.started":
            entry["role"], entry["title"], entry["status"] = "system", "Tour démarré", "busy"
        elif kind in {"item.completed", "item.started", "item.updated"}:
            item = event.get("item") if isinstance(event.get("item"), dict) else {}
            entry.update(CodexLocalAgent._item_entry(item))
            entry["raw"] = event
        elif kind == "turn.completed":
            usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
            entry["role"], entry["title"] = "result", "Tour terminé"
            tokens = [
                f"{usage.get('input_tokens')} entrée",
                f"{usage.get('output_tokens')} sortie",
            ]
            entry["text"] = " · ".join(part for part in tokens if "None" not in part)
        elif kind == "turn.failed":
            error = event.get("error") if isinstance(event.get("error"), dict) else {}
            entry["role"], entry["status"], entry["title"] = "result", "bad", "Échec du tour"
            entry["text"] = str(error.get("message") or event.get("message") or "")
        elif kind == "user":
            entry["role"], entry["title"] = "user", "Vous"
            entry["text"] = str(event.get("text") or "")
        elif kind == "stderr":
            entry["role"], entry["status"] = "stderr", "bad"
            entry["title"], entry["text"] = "stderr", str(event.get("text") or "")
        elif kind == "stdout":
            entry["title"], entry["text"] = "stdout", str(event.get("text") or "")
        elif kind == "error":
            entry["role"], entry["status"], entry["title"] = "result", "bad", "Erreur Codex"
            entry["text"] = str(event.get("message") or "")
        return entry

    @staticmethod
    def _item_entry(item: dict[str, Any]) -> dict[str, Any]:
        item_type = str(item.get("type") or "item")
        if item_type == "agent_message":
            return {"role": "assistant", "title": "Codex", "text": str(item.get("text") or ""), "status": "ok"}
        if item_type == "reasoning":
            return {
                "role": "assistant",
                "title": "Réflexion",
                "text": str(item.get("text") or item.get("summary") or ""),
                "status": "ok",
            }
        if item_type == "command_execution":
            failed = item.get("exit_code") not in (0, None)
            return {
                "role": "assistant",
                "title": "Commande",
                "text": str(item.get("command") or ""),
                "status": "bad" if failed else "ok",
            }
        if item_type == "file_change":
            changes = item.get("changes") if isinstance(item.get("changes"), list) else []
            return {
                "role": "assistant",
                "title": "Fichiers",
                "text": ", ".join(str(c.get("path")) for c in changes if isinstance(c, dict)),
                "status": "ok",
            }
        if item_type == "mcp_tool_call":
            return {
                "role": "assistant",
                "title": f"Outil {item.get('server') or ''} {item.get('tool') or ''}".strip(),
                "text": str(item.get("status") or ""),
                "status": "bad" if item.get("status") == "failed" else "ok",
            }
        if item_type == "error":
            return {"role": "result", "title": "Erreur", "text": str(item.get("message") or ""), "status": "bad"}
        return {
            "role": "assistant",
            "title": item_type,
            "text": str(item.get("text") or item.get("message") or ""),
            "status": "ok",
        }

    # ------------------------------------------------------------- exécution

    def _turn_command(self, *, resume: bool) -> list[str]:
        argv = [resolve_command(self.command), "exec"]
        if resume and self.session_id:
            argv += ["resume", self.session_id]
        # Pas de `-C` : le répertoire de travail est celui du processus, et
        # `codex exec resume` n'accepte pas ce drapeau.
        argv += ["--json", "--skip-git-repo-check"]
        if self.model:
            argv += ["-m", self.model]
        if self.permission_mode == "danger-full-access":
            # En vocal personne ne peut répondre à une demande d'approbation :
            # ce drapeau est le seul qui supprime aussi les confirmations.
            argv.append("--dangerously-bypass-approvals-and-sandbox")
        else:
            # `-s` n'existe que sur `codex exec` ; l'override de configuration,
            # lui, est accepté par les deux formes.
            argv += ["-c", f"sandbox_mode={self.permission_mode}"]
        # `-` fait lire l'instruction sur stdin : une question vocale peut
        # contenir des guillemets ou des sauts de ligne qu'un argv abîmerait.
        argv.append("-")
        return argv

    async def start(self, *, resume: bool = True) -> dict[str, Any]:
        """Codex n'a pas de processus permanent : « démarrer » = vérifier le CLI."""
        del resume
        from jarvis.runtime.cli_catalog import probe

        detection = await probe(self.command)
        if self._owned_closed:
            raise RuntimeError("owned_agent_closed")
        if not detection.get("available"):
            self._started = False
            self.journal.emit(
                "agent.start",
                f"Codex CLI indisponible : {detection.get('error')}",
                level="error",
                data={"command": self.command, "code": "codex_cli_not_found"},
            )
            raise RuntimeError(f"Codex CLI indisponible : {detection.get('error')}")
        if not self._started:
            # Pas de processus permanent : « démarré » date du moment où
            # l'agent a été armé, pas d'un tour en particulier.
            self.subtasks.process_started()
        self._started = True
        self.journal.emit(
            "agent.start",
            "Agent Codex prêt",
            data={
                "command": self.command,
                "version": detection.get("version"),
                "sandbox_mode": self.permission_mode,
                "model": self.model or "(défaut du CLI)",
            },
        )
        return self.snapshot()

    async def _run_turn(
        self,
        text: str,
        *,
        timeout_s: float,
        prompt_evidence: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        if not self._started:
            await self.start()
        argv = self._turn_command(resume=True)
        started = time.perf_counter()
        try:
            async with self._process_lock:
                if self._owned_closed:
                    raise RuntimeError("owned_agent_closed")
                self.process = await asyncio.create_subprocess_exec(
                    *argv,
                    cwd=str(self.cwd),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env={**os.environ, "PYTHONUNBUFFERED": "1"},
                    **({"creationflags": self._process_tree.creationflags} if self._process_tree else {}),
                )
                if self._process_tree:
                    self._process_tree.attach_and_resume(self.process.pid)
                self._job_started.set()
        except OSError as exc:
            self._next_prompt_evidence = None
            self.journal.emit(
                "agent.start", f"Impossible de lancer Codex : {exc}", level="error",
                data={"command": argv, "code": "codex_spawn_failed"},
            )
            return {"ok": False, "text": "", "error": str(exc), "code": "codex_spawn_failed"}
        except BaseException:
            self._next_prompt_evidence = None
            raise

        process = self.process
        self.subtasks.turn_started()
        assert process.stdin is not None
        try:
            process.stdin.write(text.encode("utf-8"))
            await process.stdin.drain()
            if prompt_evidence is not None:
                self.prompt_applications.append(dict(prompt_evidence))
                self.journal.emit("agent.prompt", "Prompt application recorded", data=dict(prompt_evidence))
            process.stdin.close()
        except (BrokenPipeError, ConnectionResetError, OSError):
            self._next_prompt_evidence = None

        stderr_task = asyncio.create_task(self._read_stderr(process), name="jarvis-codex-stderr")
        try:
            outcome = await asyncio.wait_for(self._read_stdout(process), timeout=timeout_s)
        except asyncio.TimeoutError:
            # Tuer d'abord : attendre un processus vivant dont personne ne lit plus
            # stdout bloquerait sur un tube plein (reprise QA Slice 09).
            self._kill(process)
            self.journal.emit(
                "agent.ask_timeout",
                f"Codex n'a pas répondu en {timeout_s:.0f} s",
                level="error",
                data={"code": "codex_timeout", "timeout_s": timeout_s},
            )
            outcome = {
                "ok": False,
                "text": "",
                "error": f"Codex n'a pas répondu en {timeout_s:.0f} secondes.",
                "code": "codex_timeout",
            }
        except Exception as exc:  # noqa: BLE001 - un défaut de lecture devient un tour raté dit, jamais un ask pendu
            self._kill(process)
            self.journal.emit("agent.read_failed", f"Lecture de Codex interrompue : {type(exc).__name__}", level="error",
                              data={"code": "codex_read_failed", "error": str(exc)[:300]})
            outcome = {"ok": False, "text": "", "error": f"Lecture de la réponse de Codex impossible ({type(exc).__name__}).",
                       "code": "codex_read_failed"}
        finally:
            # stdout se ferme souvent avant que la tâche stderr n'ait été
            # planifiée. L'annuler ici perdrait précisément les lignes qui
            # expliquent un tour raté ; le flux étant clos, elle finit seule.
            try:
                await asyncio.wait_for(asyncio.shield(stderr_task), timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)
            # Jamais d'attente sans borne d'un processus encore vivant : tué d'abord.
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._kill(process)
                await process.wait()
            self._last_returncode = process.returncode
            self.process = None
            self.subtasks.turn_finished()

        duration_ms = int((time.perf_counter() - started) * 1000)
        if outcome.get("ok") is None:
            failed = self._last_returncode not in (0, None)
            outcome = {
                "ok": not failed,
                "text": outcome.get("text") or "",
                "error": None if not failed else f"Codex s'est arrêté (code {self._last_returncode}).",
                "code": None if not failed else "codex_exited",
            }
        result = {**outcome, "session_id": self.session_id, "duration_ms": duration_ms}
        self.journal.emit(
            "agent.ask",
            str(result.get("text") or "")[:300] or "(réponse vide)",
            level="info" if result.get("ok") else "error",
            data={
                "session_id": self.session_id,
                "duration_ms": duration_ms,
                "returncode": self._last_returncode,
                "code": result.get("code"),
            },
        )
        return result

    @staticmethod
    def _kill(process: asyncio.subprocess.Process) -> None:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass  # intentional: it exited between the check and the kill; nothing left to stop

    def _report_long_line(self, stream: str, size: int) -> None:
        self.journal.emit("agent.stream_line_too_long", f"Ligne {stream} de Codex trop longue, ignorée", level="error",
                          data={"stream": stream, "limit_bytes": MAX_LINE_BYTES, "bytes": size})

    async def _read_stdout(self, process: asyncio.subprocess.Process) -> dict[str, Any]:
        assert process.stdout is not None
        answer = ""
        outcome: dict[str, Any] = {"ok": None, "text": ""}
        async for raw in iter_lines(process.stdout):
            if isinstance(raw, OversizeLine):
                self._report_long_line("stdout", raw.size)
                continue
            line = raw.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                event = {"type": "stdout", "text": clip_text(line)}
            if not isinstance(event, dict):
                continue
            if may_carry_media(raw):
                event = redact_media(event)
            self._record(event)
            self.journal.emit("agent.event", str(event.get("type") or "event"), data=journal_view(event, size=len(raw)))
            kind = str(event.get("type") or "")
            if kind == "item.completed":
                item = event.get("item") if isinstance(event.get("item"), dict) else {}
                if item.get("type") == "agent_message":
                    # Le dernier message de l'agent est la réponse : un tour peut
                    # en produire plusieurs, seul le dernier conclut.
                    answer = str(item.get("text") or "")
            elif kind == "turn.completed":
                outcome = {"ok": True, "text": answer, "usage": event.get("usage")}
            elif kind in {"turn.failed", "error"}:
                error = event.get("error") if isinstance(event.get("error"), dict) else {}
                outcome = {
                    "ok": False,
                    "text": answer,
                    "error": str(error.get("message") or event.get("message") or "Le tour Codex a échoué."),
                    "code": "codex_turn_failed",
                }
        if outcome.get("ok") is True:
            outcome["text"] = answer
        elif outcome.get("ok") is None:
            outcome["text"] = answer
        return outcome

    async def _read_stderr(self, process: asyncio.subprocess.Process) -> None:
        assert process.stderr is not None
        async for raw in iter_lines(process.stderr):
            if isinstance(raw, OversizeLine):
                self._report_long_line("stderr", raw.size)
                continue
            text = clip_text(raw.decode("utf-8", errors="replace").rstrip())
            if not text:
                continue
            self._record({"type": "stderr", "text": text})
            self.journal.emit("agent.stderr", text, level="error")

    async def ask(self, text: str, *, timeout_s: float = 180.0,
                  prompt_evidence: dict[str, object] | None = None,
                  input_text: str | None = None) -> dict[str, Any]:
        evidence = dict(prompt_evidence) if prompt_evidence is not None else self._next_prompt_evidence
        # Consume legacy one-shot state before validation/start so an empty or
        # failed turn cannot lend its identity to a later prompt.
        self._next_prompt_evidence = None
        message = text.strip()
        visible_message = message if input_text is None else str(input_text).strip()
        if not message:
            return {"ok": False, "text": "", "error": "message cannot be empty", "code": "codex_empty"}
        async with self._turn_lock:
            self._record({"type": "user", "text": visible_message})
            self.journal.emit("agent.input", visible_message)
            return await self._run_turn(message, timeout_s=timeout_s, prompt_evidence=evidence)

    def set_next_prompt_evidence(self, evidence: dict[str, object]) -> None:
        self._next_prompt_evidence = dict(evidence)

    def set_prompt_overrides(self, overrides: object | None) -> None:
        from jarvis.runtime.prompt_runtime import normalize_prompt_overrides
        self._prompt_overrides = normalize_prompt_overrides(overrides)

    async def send(
        self,
        text: str,
        *,
        prompt_evidence: dict[str, object] | None = None,
        input_text: str | None = None,
    ) -> dict[str, Any]:
        """Déposer un message sans attendre : le tour part en arrière-plan.

        Chez Claude, `send` écrit dans un processus déjà là. Ici il faut en
        lancer un ; la panneau Agents rafraîchit ensuite l'historique tout seul.
        """
        evidence = dict(prompt_evidence) if prompt_evidence is not None else self._next_prompt_evidence
        self._next_prompt_evidence = None
        message = text.strip()
        visible_message = message if input_text is None else str(input_text).strip()
        if not message:
            raise ValueError("message cannot be empty")
        if self._background is not None and not self._background.done():
            raise RuntimeError("Un tour Codex est déjà en cours.")
        self._background = asyncio.create_task(
            self._background_turn(
                message,
                prompt_evidence=evidence,
                input_text=visible_message,
            ),
            name="jarvis-codex-turn",
        )
        return self.snapshot()

    async def _background_turn(
        self,
        message: str,
        *,
        prompt_evidence: dict[str, object] | None = None,
        input_text: str | None = None,
    ) -> None:
        try:
            await self.ask(
                message,
                timeout_s=900.0,
                prompt_evidence=prompt_evidence,
                input_text=input_text,
            )
        except Exception as exc:  # noqa: BLE001 - une tâche orpheline ne doit jamais mourir en silence
            self.journal.emit(
                "agent.error", f"Tour Codex interrompu : {exc}", level="error",
                data={"code": "codex_background_failed", "exception_type": type(exc).__name__},
            )

    async def restart(self) -> dict[str, Any]:
        await self.stop()
        # Repartir de zéro veut dire un nouveau fil : sinon « redémarrer » ne
        # ferait rien de visible, faute de processus à relancer.
        self.session_id = None
        self._events.clear()
        self._event_times.clear()
        return await self.start()

    async def stop(self) -> dict[str, Any]:
        task, self._background = self._background, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        process = self.process
        if process is not None and process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass  # The owned Windows job may have already terminated it.
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
            self._last_returncode = process.returncode
        self.process = None
        self._started = False
        self.subtasks.process_stopped()
        self.journal.emit("agent.stop", "Agent Codex arrêté", data={"returncode": self._last_returncode})
        return self.snapshot()

    async def close_owned(self) -> bool:
        """Join a pending spawn before terminating this dedicated job process."""
        self._owned_closed = True
        async with self._process_lock:
            if self._process_tree:
                self._process_tree.terminate()
            if not self._owned_root_closed:
                await self.stop()
                self._owned_root_closed = self.process is None or self.process.returncode is not None
        root_closed = self.process is None or self.process.returncode is not None
        return root_closed and self._process_tree is not None and self._process_tree.close_if_empty()

    async def wait_started(self) -> None:
        await self._job_started.wait()

    # ---------------------------------------------------------------- console

    async def open_console(self) -> dict[str, Any]:
        if os.name != "nt":
            raise RuntimeError("La console de debug n'est disponible que sous Windows")
        existing = self._console
        if existing is not None and existing.poll() is None:
            raised = raise_console_window(existing.pid)
            return {**self.console_snapshot(), "already_open": True, "raised": raised, "handover": False}
        # Aucune passation : `codex exec` ne tient pas le fil entre deux tours,
        # la console interactive peut donc l'ouvrir en parallèle.
        executable = resolve_command(self.command)
        argv = [executable, "resume", self.session_id] if self.session_id else [executable]
        try:
            self._console = subprocess.Popen(
                argv, cwd=str(self.cwd), creationflags=CREATE_NEW_CONSOLE, close_fds=True
            )
        except OSError as exc:
            self.journal.emit(
                "agent.console_failed", f"Impossible d'ouvrir la console Codex: {exc}",
                level="error", data={"command": argv, "code": "codex_console_spawn_failed"},
            )
            raise RuntimeError(f"Impossible d'ouvrir la console Codex: {exc}") from exc
        self.journal.emit(
            "agent.console_open", "Console Codex ouverte",
            data={"pid": self._console.pid, "session_id": self.session_id, "handover": False},
        )
        return {**self.console_snapshot(), "already_open": False, "raised": True, "handover": False}

    async def close_console(self) -> dict[str, Any]:
        process, self._console = self._console, None
        if process is None or process.poll() is not None:
            return self.console_snapshot()
        process.terminate()
        try:
            await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=5)
        except asyncio.TimeoutError:
            process.kill()
        self.journal.emit("agent.console_close", "Console Codex fermée", data={"pid": process.pid})
        return self.console_snapshot()
