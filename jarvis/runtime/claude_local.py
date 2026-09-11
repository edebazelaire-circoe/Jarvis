from __future__ import annotations

import asyncio
import ctypes
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from jarvis.runtime.agent_tasks import AgentTaskTracker
from jarvis.runtime.cli_catalog import resolve_command
from jarvis.runtime.journal import RuntimeJournal


# Donne au processus enfant sa propre fenêtre console, au lieu de partager
# celle du parent (ou de n'en avoir aucune, comme l'agent piloté par pipes).
CREATE_NEW_CONSOLE = 0x00000010

# Modes d'autorisation acceptés par le CLI. En headless personne ne peut
# répondre à une demande d'approbation : sans `bypassPermissions`, Claude
# demande la permission d'écrire et le tour vocal se solde par un refus poli.
PERMISSION_MODES = ("bypassPermissions", "acceptEdits", "dontAsk", "auto", "manual", "plan")
DEFAULT_PERMISSION_MODE = "bypassPermissions"


def normalize_permission_mode(value: object) -> str:
    mode = str(value or "").strip()
    return mode if mode in PERMISSION_MODES else DEFAULT_PERMISSION_MODE


def raise_console_window(pid: int) -> bool:
    """Ramener au premier plan la fenêtre console d'un processus.

    Best effort : selon l'hôte console (conhost ou Windows Terminal) la fenêtre
    n'appartient pas toujours au processus lui-même. Un échec n'est pas une
    erreur, seulement une fenêtre à retrouver à la main.
    """
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
    except OSError:
        return False
    found: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def visit(hwnd, _param):  # noqa: ANN001
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(ctypes.c_void_p(hwnd)):
            found.append(hwnd)
            return False
        return True

    try:
        user32.EnumWindows(visit, None)
        if not found:
            return False
        user32.ShowWindow(ctypes.c_void_p(found[0]), 9)  # SW_RESTORE
        user32.SetForegroundWindow(ctypes.c_void_p(found[0]))
        return True
    except OSError:
        return False


class ClaudeLocalAgent:
    def __init__(
        self,
        *,
        runtime_root: Path,
        cwd: Path,
        command: str = "claude",
        permission_mode: str = DEFAULT_PERMISSION_MODE,
        model: str = "",
    ) -> None:
        self.runtime_root = runtime_root
        self.cwd = cwd
        self.command = command
        self.permission_mode = normalize_permission_mode(permission_mode)
        # Vide = on laisse le CLI choisir son modèle par défaut. Une chaîne
        # vide passée à `--model` serait refusée par le CLI, d'où le filtrage.
        self.model = str(model or "").strip()
        self.journal = RuntimeJournal(runtime_root)
        self.process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        # Événements du brain seul, avec leur heure de réception (ms epoch).
        # Ceux des sous-agents vivent dans `subtasks`, tâche par tâche.
        self._events: list[dict[str, Any]] = []
        self._event_times: list[int] = []
        self.subtasks = AgentTaskTracker(provider="claude", journal=self.journal, formatter=self._transcript_entry)
        self._lock = asyncio.Lock()
        # Identifiant de la conversation en cours : c'est lui qui permet à la
        # console de debug de reprendre *la même* conversation.
        self.session_id: str | None = None
        self._console: subprocess.Popen | None = None
        # Un tour Claude se termine par un événement `result`. `ask()` attend
        # celui-ci; le verrou garantit qu'une seule question est en vol, sinon
        # deux appelants se partageraient la même réponse.
        self._pending_result: asyncio.Future[dict[str, Any]] | None = None
        self._ask_lock = asyncio.Lock()
        # Nombre de tours dont on n'attend plus la réponse : leur `result`
        # arrivera en retard et doit être ignoré, pas attribué au suivant.
        self._abandoned = 0

    @property
    def state(self) -> str:
        if self.process is None:
            return "stopped"
        if self.process.returncode is None:
            return "running"
        return "exited"

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": "Claude",
            "state": self.state,
            "pid": self.process.pid if self.process and self.process.returncode is None else None,
            "returncode": self.process.returncode if self.process else None,
            "events": self._events[-80:],
            "session_id": self.session_id,
            "permission_mode": self.permission_mode,
            "model": self.model,
            "console": self.console_snapshot(),
        }

    def _record(self, event: dict[str, Any]) -> None:
        session = event.get("session_id")
        if isinstance(session, str) and session:
            self.session_id = session
        now_ms = self.subtasks.now_ms()
        try:
            self.subtasks.observe_claude(event, now_ms=now_ms)
        except Exception as exc:  # noqa: BLE001
            # La voix ne doit jamais dépendre du suivi des sous-tâches : levée
            # ici, l'exception tuerait la lecture de stdout, le `result` du tour
            # ne serait plus livré et `ask()` attendrait son délai — brain sourd.
            self.subtasks.report_failure(exc, event)
        if not AgentTaskTracker.belongs_to_brain(event):
            # Un sous-agent actif produit des centaines d'événements : mêlés à
            # ceux du brain, ils chasseraient son historique hors de la fenêtre.
            return
        self._events.append(event)
        self._event_times.append(now_ms)
        if len(self._events) > 500:
            del self._events[:-500]
            del self._event_times[:-500]

    def tasks_snapshot(self) -> dict[str, Any]:
        """Le brain et ses sous-tâches, pour `/api/agent/tasks`."""
        return self.subtasks.payload(state=self.state, session_id=self.session_id, configured_model=self.model)

    def task_trace(self, task_id: str, *, limit: int = 300) -> dict[str, Any] | None:
        """Trace d'une sous-tâche, ou du brain (`"brain"`) ; None si inconnue."""
        if task_id == "brain":
            brain = self.subtasks.brain_snapshot(state=self.state, session_id=self.session_id, configured_model=self.model)
            return {"task": brain, "entries": self.transcript(limit=limit)}
        return self.subtasks.trace(task_id, limit=limit)

    def console_snapshot(self) -> dict[str, Any]:
        process = self._console
        running = process is not None and process.poll() is None
        return {
            "open": running,
            "pid": process.pid if running and process is not None else None,
            "session_id": self.session_id,
            "supported": os.name == "nt",
        }

    async def open_console(self) -> dict[str, Any]:
        """Ouvrir la véritable console Windows sur la conversation en cours.

        L'agent piloté par pipes est arrêté au passage : une même session Claude
        ne peut pas être écrite à la fois par lui et par la console interactive.
        C'est une passation de main assumée — la console est un mode de debug.
        """
        if os.name != "nt":
            raise RuntimeError("La console de debug n'est disponible que sous Windows")

        existing = self._console
        if existing is not None and existing.poll() is None:
            raised = raise_console_window(existing.pid)
            self.journal.emit(
                "agent.console_focus",
                "Console Claude déjà ouverte",
                data={"pid": existing.pid, "raised": raised},
            )
            return {**self.console_snapshot(), "already_open": True, "raised": raised, "handover": False}

        session_id = self.session_id
        handover = self.state == "running"
        if handover:
            if self._pending_result is not None and not self._pending_result.done():
                self.journal.emit(
                    "agent.console_interrupt",
                    "La console de debug interrompt la tâche vocale en cours.",
                    level="warning",
                    data={"code": "claude_handover", "session_id": session_id},
                )
                self._abort_pending(
                    "La console de debug a pris la main : la tâche en cours a été interrompue.",
                    "claude_handover",
                )
            await self.stop()
        command = [
            resolve_command(self.command),
            "--permission-mode",
            self.permission_mode,
            *(["--model", self.model] if self.model else []),
            *(["--resume", session_id] if session_id else []),
        ]
        try:
            self._console = subprocess.Popen(
                command,
                cwd=str(self.cwd),
                creationflags=CREATE_NEW_CONSOLE,
                close_fds=True,
            )
        except OSError as exc:
            self.journal.emit(
                "agent.console_failed",
                f"Impossible d'ouvrir la console Claude: {exc}",
                level="error",
                data={"command": command, "code": "claude_console_spawn_failed"},
            )
            raise RuntimeError(f"Impossible d'ouvrir la console Claude: {exc}") from exc
        self.journal.emit(
            "agent.console_open",
            "Console Claude de debug ouverte" + (" (conversation reprise)" if session_id else " (nouvelle conversation)"),
            data={"pid": self._console.pid, "session_id": session_id, "handover": handover},
        )
        return {**self.console_snapshot(), "already_open": False, "raised": True, "handover": handover}

    async def close_console(self) -> dict[str, Any]:
        process, self._console = self._console, None
        if process is None or process.poll() is not None:
            return self.console_snapshot()
        process.terminate()
        try:
            await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=5)
        except asyncio.TimeoutError:
            process.kill()
        self.journal.emit("agent.console_close", "Console Claude de debug fermée", data={"pid": process.pid})
        return self.console_snapshot()

    def transcript(self, *, limit: int = 200) -> list[dict[str, Any]]:
        """Traduire le flux `stream-json` du CLI en historique lisible.

        C'est une *représentation* de la conversation, pas la console : la
        véritable console Windows s'ouvre avec `open_console()`.

        Les événements bruts sont des blocs JSON de plusieurs kilo-octets : tels
        quels ils sont illisibles. Chaque entrée renvoyée porte un rôle, un titre
        court, le détail à déplier et son heure de réception (`ts_ms`).

        Seul le brain y figure : les messages des sous-agents se consultent
        tâche par tâche, via `task_trace()`.
        """
        events = self._events[-limit:]
        times = self._event_times[-limit:]
        return [{**self._transcript_entry(event), "ts_ms": ts} for event, ts in zip(events, times)]

    @staticmethod
    def _transcript_entry(event: dict[str, Any]) -> dict[str, Any]:
        kind = str(event.get("type") or "event")
        entry: dict[str, Any] = {"role": kind, "title": kind, "text": "", "status": "ok", "raw": event}

        if kind == "system" and str(event.get("subtype") or "").startswith("task_"):
            entry.update(ClaudeLocalAgent._task_entry(event))
        elif kind == "system":
            entry["title"] = f"Session {event.get('subtype') or 'system'}"
            entry["text"] = " · ".join(
                part for part in (str(event.get("model") or ""), str(event.get("cwd") or "")) if part
            )
        elif kind in {"assistant", "user"}:
            message = event.get("message") if isinstance(event.get("message"), dict) else {}
            entry["role"], entry["title"] = kind, "Claude" if kind == "assistant" else "Vous"
            entry["text"] = ClaudeLocalAgent._message_text(message)
        elif kind == "result":
            entry["role"] = "result"
            failed = bool(event.get("is_error")) or event.get("subtype") != "success"
            entry["status"] = "bad" if failed else "ok"
            entry["title"] = "Échec du tour" if failed else "Tour terminé"
            cost, duration = event.get("total_cost_usd"), event.get("duration_ms")
            details = [str(event.get("result") or "")]
            if duration is not None:
                details.append(f"{duration} ms")
            if cost is not None:
                details.append(f"${float(cost):.4f}")
            entry["text"] = " · ".join(part for part in details if part)
        elif kind == "stderr":
            entry["role"], entry["status"] = "stderr", "bad"
            entry["title"], entry["text"] = "stderr", str(event.get("text") or "")
        elif kind == "stdout":
            entry["title"], entry["text"] = "stdout", str(event.get("text") or "")
        elif kind == "rate_limit_event":
            info = event.get("rate_limit_info") if isinstance(event.get("rate_limit_info"), dict) else {}
            status = str(info.get("status") or "")
            entry["role"] = "notice"
            entry["status"] = "warn" if status != "allowed" else "ok"
            entry["title"] = "Quota"
            entry["text"] = f"{status} · utilisation {info.get('utilization')}"
        return entry

    @staticmethod
    def _task_entry(event: dict[str, Any]) -> dict[str, Any]:
        """Jalons d'une sous-tâche (`task_started`, `task_notification`...)."""
        subtype = str(event.get("subtype") or "")
        description = str(event.get("description") or "")
        if subtype == "task_started":
            task_type = str(event.get("task_type") or "")
            title = {"local_agent": "Sous-agent lancé", "local_bash": "Commande lancée"}.get(task_type, "Tâche lancée")
            text = "\n".join(part for part in (description, str(event.get("prompt") or "")) if part)
            return {"role": "system", "title": title, "text": text, "status": "busy"}
        if subtype == "task_progress":
            usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
            details = [description]
            if usage.get("tool_uses") is not None:
                details.append(f"{usage.get('tool_uses')} outils")
            if usage.get("total_tokens") is not None:
                details.append(f"{usage.get('total_tokens')} jetons")
            return {"role": "system", "title": "Avancement", "text": " · ".join(part for part in details if part), "status": "busy"}
        if subtype == "task_notification":
            status = str(event.get("status") or "")
            titles = {"completed": "Tâche terminée", "failed": "Tâche en échec", "killed": "Tâche tuée", "stopped": "Tâche arrêtée"}
            return {
                "role": "system",
                "title": titles.get(status, f"Tâche : {status}" if status else "Tâche notifiée"),
                "text": str(event.get("summary") or ""),
                "status": "bad" if status == "failed" else "warn" if status in {"killed", "stopped"} else "ok",
            }
        patch = event.get("patch") if isinstance(event.get("patch"), dict) else {}
        text = " · ".join(f"{key} = {value}" for key, value in patch.items())
        return {"role": "system", "title": "Tâche mise à jour" if subtype == "task_updated" else f"Tâche {subtype}", "text": text}

    @staticmethod
    def _message_text(message: dict[str, Any]) -> str:
        content = message.get("content")
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                parts.append(str(block.get("text") or ""))
            elif block_type == "thinking":
                parts.append(f"[réflexion] {block.get('thinking') or ''}")
            elif block_type == "tool_use":
                parts.append(f"[outil] {block.get('name')} {json.dumps(block.get('input') or {}, ensure_ascii=False)}")
            elif block_type == "tool_result":
                payload = block.get("content")
                text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, default=str)
                marker = "[résultat erreur]" if block.get("is_error") else "[résultat]"
                parts.append(f"{marker} {text}")
        return "\n".join(part for part in parts if part.strip())

    async def start(self, *, resume: bool = True) -> dict[str, Any]:
        async with self._lock:
            if self.process is not None and self.process.returncode is None:
                return self.snapshot()
            # Deux processus ne peuvent pas écrire la même session Claude. Mais
            # la voix est la fonction fondamentale de JARVIS : elle ne doit
            # jamais être otage d'un outil de debug. Si la console occupe la
            # conversation, l'agent vocal en ouvre simplement une nouvelle.
            console = self._console
            console_holds_session = console is not None and console.poll() is None
            env = os.environ.copy()
            env.setdefault("PYTHONUNBUFFERED", "1")
            # Reprendre la conversation permet de retrouver le fil après un
            # passage par la console de debug.
            if console_holds_session and self.session_id:
                self.journal.emit(
                    "agent.session_forked",
                    "La console de debug occupe la conversation : l'agent démarre une nouvelle session.",
                    level="warning",
                    data={"code": "claude_console_holds_session", "held_session_id": self.session_id},
                )
                self.session_id = None
            resume_args = ["--resume", self.session_id] if resume and self.session_id else []
            permission_args = ["--permission-mode", self.permission_mode]
            model_args = ["--model", self.model] if self.model else []
            try:
                self.process = await asyncio.create_subprocess_exec(
                    resolve_command(self.command),
                    "-p",
                    "--input-format",
                    "stream-json",
                    "--output-format",
                    "stream-json",
                    "--verbose",
                    *permission_args,
                    *model_args,
                    *resume_args,
                    cwd=str(self.cwd),
                    env=env,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as exc:
                self.journal.emit("agent.start", "Claude CLI not found", level="error", data={"command": self.command})
                raise RuntimeError("Claude CLI not found; install Claude Code and ensure `claude` is in PATH") from exc
            self.subtasks.process_started()
            self.journal.emit("agent.start", "Claude local agent started", data={"pid": self.process.pid, "resumed": bool(resume_args), "permission_mode": self.permission_mode, "model": self.model or "(défaut du CLI)"})
            self._reader_task = asyncio.create_task(self._read_stdout(), name="jarvis-claude-stdout")
            self._stderr_task = asyncio.create_task(self._read_stderr(), name="jarvis-claude-stderr")
            return self.snapshot()

    async def send(self, text: str) -> dict[str, Any]:
        text = text.strip()
        if not text:
            raise ValueError("message cannot be empty")
        if self.process is None or self.process.returncode is not None:
            await self.start()
        assert self.process is not None and self.process.stdin is not None
        payload = {"type": "user", "message": {"role": "user", "content": text}}
        # Avant l'écriture : pendant `drain()`, la lecture de stdout peut déjà
        # traiter les premiers événements du tour.
        self.subtasks.turn_started()
        self.process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        await self.process.stdin.drain()
        # Le CLI ne réémet pas l'entrée : sans cet écho la console n'afficherait
        # que les réponses, sans la question qui les a provoquées.
        self._record(payload)
        self.journal.emit("agent.input", text)
        return self.snapshot()

    async def ask(self, text: str, *, timeout_s: float = 180.0) -> dict[str, Any]:
        """Poser une question et attendre la réponse complète du tour.

        C'est le point d'entrée de la boucle vocale : la voix a besoin d'un
        texte à prononcer, donc d'un aller-retour, là où `send()` ne fait que
        déposer un message.
        """
        async with self._ask_lock:
            loop = asyncio.get_running_loop()
            self._pending_result = loop.create_future()
            try:
                await self.send(text)
            except (RuntimeError, ValueError) as exc:
                self._pending_result = None
                return {"ok": False, "text": "", "error": str(exc), "code": "claude_unavailable"}
            try:
                event = await asyncio.wait_for(self._pending_result, timeout=timeout_s)
            except asyncio.TimeoutError:
                self._abandoned += 1
                self.journal.emit(
                    "agent.ask_timeout",
                    f"Claude n'a pas répondu en {timeout_s:.0f} s",
                    level="error",
                    data={"code": "claude_timeout", "timeout_s": timeout_s},
                )
                return {"ok": False, "text": "", "error": f"Claude n'a pas répondu en {timeout_s:.0f} secondes.", "code": "claude_timeout"}
            finally:
                self._pending_result = None

        if event.get("type") != "result":
            # Événement synthétique : agent arrêté, passation à la console, sortie.
            return {"ok": False, "text": "", "error": str(event.get("error") or ""), "code": str(event.get("code") or "claude_unavailable")}
        failed = bool(event.get("is_error")) or event.get("subtype") != "success"
        answer = str(event.get("result") or "")
        denials = event.get("permission_denials") or []
        self.journal.emit(
            "agent.ask",
            answer[:300] or "(réponse vide)",
            level="error" if failed else "info",
            data={
                "session_id": event.get("session_id"),
                "duration_ms": event.get("duration_ms"),
                "cost_usd": event.get("total_cost_usd"),
                "permission_denials": denials,
                "subtype": event.get("subtype"),
            },
        )
        return {
            "ok": not failed,
            "text": answer,
            "session_id": event.get("session_id"),
            "duration_ms": event.get("duration_ms"),
            "cost_usd": event.get("total_cost_usd"),
            "permission_denials": denials,
            "error": None if not failed else (answer or "Le tour Claude a échoué."),
        }

    def _resolve_pending(self, event: dict[str, Any]) -> None:
        if self._abandoned and event.get("type") == "result":
            # Ce résultat appartient à un tour abandonné (délai dépassé) :
            # le livrer à la question suivante mélangerait deux réponses.
            self._abandoned -= 1
            return
        pending = self._pending_result
        if pending is not None and not pending.done():
            pending.set_result(event)

    def _abort_pending(self, reason: str, code: str) -> None:
        """Débloquer immédiatement un `ask()` qui n'aura jamais son résultat."""
        pending = self._pending_result
        if pending is not None and not pending.done():
            pending.set_result({"code": code, "error": reason})

    async def restart(self) -> dict[str, Any]:
        await self.stop()
        return await self.start()

    async def stop(self) -> dict[str, Any]:
        # Avant toute chose : la tâche de lecture va être annulée, donc le code
        # qui débloque un `ask()` en fin de flux ne s'exécutera jamais. Sans
        # cela l'appelant attend le délai complet pour rien.
        self._abort_pending("L'agent Claude a été arrêté avant de répondre.", "claude_stopped")
        async with self._lock:
            process = self.process
            if process is None:
                return self.snapshot()
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=3)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            for task in (self._reader_task, self._stderr_task):
                if task is not None:
                    task.cancel()
            await asyncio.gather(*(t for t in (self._reader_task, self._stderr_task) if t is not None), return_exceptions=True)
            self._reader_task = self._stderr_task = None
            # Les sous-agents vivaient dans le processus arrêté : ils sont
            # interrompus, pas « en cours » pour toujours.
            self.subtasks.process_stopped()
            self.journal.emit("agent.stop", "Claude local agent stopped", data={"returncode": process.returncode})
            return self.snapshot()

    async def _read_stdout(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        while True:
            raw = await self.process.stdout.readline()
            if not raw:
                break
            text = raw.decode("utf-8", errors="replace").rstrip()
            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                event = {"type": "stdout", "text": text}
            if isinstance(event, dict):
                self._record(event)
                if event.get("type") == "result":
                    self._resolve_pending(event)
                self.journal.emit("agent.event", str(event.get("type") or "event"), data=event)
        if self.process is not None:
            await self.process.wait()
            # Un `ask()` en vol ne recevra jamais son `result` : le débloquer
            # plutôt que de le laisser expirer au bout de plusieurs minutes.
            self._resolve_pending({
                "code": "claude_exited",
                "error": f"L'agent Claude s'est arrêté (code {self.process.returncode}).",
            })
            self.subtasks.process_stopped()
            self.journal.emit("agent.exit", "Claude local agent exited", level="error" if self.process.returncode else "info", data={"returncode": self.process.returncode})

    async def _read_stderr(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        while True:
            raw = await self.process.stderr.readline()
            if not raw:
                break
            text = raw.decode("utf-8", errors="replace").rstrip()
            self._record({"type": "stderr", "text": text})
            self.journal.emit("agent.stderr", text, level="error")
