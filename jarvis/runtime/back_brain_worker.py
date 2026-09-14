"""One independent CLI owner per admitted Core job; no presentation authority."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import math
import os
from typing import Callable, Protocol

from jarvis.domain.back_brain import BackBrainResult, BackBrainWorkPayload
from jarvis.domain.v2 import Job, JobProgress
from jarvis.runtime.agent_settings import AgentExecutionSettings
from jarvis.runtime.journal import RuntimeJournal


class BackBrainWorkerError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class OwnedLocalAgent(Protocol):
    async def ask(self, text: str, *, timeout_s: float) -> dict: ...
    async def close_owned(self) -> bool: ...
    async def wait_started(self) -> None: ...


class _NullProgress:
    async def emit(self, job_id: str, progress: JobProgress) -> None:
        pass


class _JobJournal:
    """Wrapper lifecycle only: raw CLI events/prompts never enter job logs."""
    def __init__(self, journal: RuntimeJournal, job_id: str):
        self.journal, self.job_id = journal, job_id

    def emit(self, kind, message, *, level="info", data=None):
        del message
        if kind == "agent.prompt" and isinstance(data, dict):
            allowed = {key: data.get(key) for key in (
                "program_id", "prompt_ids", "layer_revisions", "static_fingerprint",
                "render_fingerprint", "channel", "application", "resumed",
            )}
            try:
                self.journal.emit("job.agent.prompt", kind, level=level,
                                  data={"job_id": self.job_id, **allowed})
            except Exception:
                pass
            return
        if kind in {"agent.start", "agent.stop", "agent.exit", "agent.ask_timeout", "agent.error"}:
            try:
                self.journal.emit("job." + kind, kind, level=level, data={"job_id": self.job_id})
            except Exception:
                pass  # Diagnostic sink failure cannot break the CLI reader; no recursive logging.


def create_job_agent(settings: AgentExecutionSettings, job_id: str, *, speculative: bool = False) -> OwnedLocalAgent:
    from jarvis.runtime.claude_local import ClaudeLocalAgent
    from jarvis.runtime.codex_local import CodexLocalAgent
    kwargs = dict(runtime_root=settings.runtime_root, cwd=settings.cwd, command=settings.command,
                  model=settings.model, permission_mode=settings.permission_mode,
                  prompt_overrides=settings.prompt_overrides)
    if settings.agent_cli == "claude":
        agent = ClaudeLocalAgent(**kwargs, execution_profile="speculative_analysis" if speculative else "job_result")
    elif settings.agent_cli == "codex":
        if speculative:
            raise BackBrainWorkerError("back_brain_speculative_unavailable")
        agent = CodexLocalAgent(**kwargs, execution_profile="job_result")
    else:
        raise BackBrainWorkerError("back_brain_provider_unavailable")
    journal = _JobJournal(RuntimeJournal(settings.runtime_root), job_id)
    agent.journal = journal
    agent.subtasks.journal = journal
    return agent


@dataclass(slots=True)
class _Owner:
    job: Job
    settings: AgentExecutionSettings
    agent: OwnedLocalAgent
    run: asyncio.Task
    source_correlation_id: str | None
    voice_session_id: str
    cleanup: asyncio.Task | None = None
    cancelled: bool = False
    closed: bool = False
    cleanup_reported: bool = False
    cleanup_failed_reported: bool = False


class BackBrainJobWorker:
    """Core owns queuing/durability. A retained cleanup owner keeps this slot busy."""
    def __init__(self, settings: Callable[[], AgentExecutionSettings], *,
                 agent_factory: Callable[[AgentExecutionSettings, str], OwnedLocalAgent] = create_job_agent,
                 timeout_s: float = 900.0, cleanup_timeout_s: float = 3.5):
        for value in (timeout_s, cleanup_timeout_s):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError("job timeouts must be positive finite numbers")
        self._settings, self._factory = settings, agent_factory
        self.timeout_s, self.cleanup_timeout_s = timeout_s, cleanup_timeout_s
        self._owners: dict[str, _Owner] = {}

    @property
    def active_job_ids(self) -> tuple[str, ...]:
        return tuple(self._owners)

    def supports_speculative_analysis(self) -> bool:
        from jarvis.runtime.cli_catalog import resolve_command
        selected = self._settings()
        return self._supports_speculative_settings(selected, resolve_command(selected.command))

    @staticmethod
    def _supports_speculative_settings(settings: AgentExecutionSettings, resolved_command: str) -> bool:
        if settings.agent_cli != "claude":
            return False
        suffix = os.path.splitext(resolved_command)[1].lower()
        # CreateProcess receives argv directly. Windows shell/script shims can
        # reinterpret or lose the deliberately empty ``--tools`` value.
        return suffix in {".exe", ".com"} if os.name == "nt" else suffix not in {".cmd", ".bat", ".ps1"}

    @staticmethod
    def _emit(owner: _Owner, kind: str, *, code: str | None = None, level: str = "info",
              extra: dict[str, object] | None = None) -> None:
        try:
            RuntimeJournal(owner.settings.runtime_root).emit(kind, kind, level=level, data={
                "job_id": owner.job.id, "conversation_id": owner.job.requested_by_conversation_id,
                "work_id": owner.job.id, "correlation_id": owner.source_correlation_id,
                "provider": owner.settings.provider, "model": owner.settings.model, "code": code,
                "source_correlation_id": owner.source_correlation_id,
                **(extra or {}),
            })
        except Exception:
            pass  # Diagnostics do not own execution/results and cannot log their own failure recursively.

    async def execute(self, job: Job) -> dict[str, object]:
        return await self.execute_with_progress(job, _NullProgress())

    async def execute_with_progress(self, job: Job, progress) -> dict[str, object]:
        if job.kind != "back_brain":
            raise BackBrainWorkerError("back_brain_invalid_kind")
        speculative = isinstance(job.payload, dict) and job.payload.get("scope") == "speculative_analysis"
        settings = self._settings()
        if speculative:
            from jarvis.runtime.cli_catalog import resolve_command
            if not self._supports_speculative_settings(settings, resolve_command(settings.command)):
                raise BackBrainWorkerError("back_brain_speculative_unavailable")
        payload = BackBrainWorkPayload.from_payload(job.payload)
        if payload.provenance.conversation_id != job.requested_by_conversation_id:
            raise BackBrainWorkerError("back_brain_source_mismatch")
        if self._owners:
            raise BackBrainWorkerError("back_brain_worker_busy")
        agent = self._factory(settings, job.id, speculative=True) if speculative else self._factory(settings, job.id)
        # JSON distinguishes admitted task from contextual data without promoting
        # any contextual instruction into the result-only system profile.
        prompt = json.dumps({"request": payload.request_text, "context_data": payload.context_text}, ensure_ascii=False)
        from jarvis.runtime.prompt_runtime import compose_agent_turn
        prompt, evidence = compose_agent_turn(
            agent_id=settings.agent_cli, model=settings.model or None, request_text=prompt,
            overrides=settings.prompt_overrides, behavior_active=settings.behavior_active,
        )
        from jarvis.runtime.prompt_runtime import accepts_prompt_evidence
        ask_kwargs: dict[str, object] = {"timeout_s": self.timeout_s}
        if evidence is not None and accepts_prompt_evidence(agent.ask):
            ask_kwargs["prompt_evidence"] = evidence
        run = asyncio.create_task(agent.ask(prompt, **ask_kwargs), name=f"back-brain-agent-{job.id}")
        owner = _Owner(job, settings, agent, run,
                       None if speculative else payload.provenance.source.correlation_id,
                       payload.provenance.session_id)
        self._owners[job.id] = owner
        self._emit(owner, "job.agent.owned")
        try:
            # No caller cancellation may abandon a native spawn before its
            # handle has been published and closed by the dedicated owner.
            async with asyncio.timeout(self.timeout_s):
                await self._observe_start(owner, progress)
                raw = await asyncio.shield(run)
            if owner.cancelled:
                raise asyncio.CancelledError
            if not isinstance(raw, dict) or raw.get("ok") is not True:
                raise BackBrainWorkerError("back_brain_execution_failed")
            usage = self._bounded_usage(raw.get("usage"))
            if usage:
                self._emit(owner, "core.back_brain.provider_usage",
                           extra={"component_role": "backend", "usage_source": "provider",
                                  "session_id": owner.voice_session_id, "usage": usage})
            result = BackBrainResult(text=raw.get("text"), provider=settings.provider,
                                     model=settings.model, session_id=raw.get("session_id"))
            self._emit(owner, "job.agent.finalizing")
            await self._progress(owner, progress, "finalizing")
        except asyncio.CancelledError:
            owner.cancelled = True
            await self._cleanup_preserving_cancellation(owner)
            raise
        except Exception as exc:
            await self._finish_cleanup(owner, progress)
            code = ("back_brain_timeout" if isinstance(exc, TimeoutError) else
                    exc.code if isinstance(exc, BackBrainWorkerError) else "back_brain_invalid_result")
            self._emit(owner, "job.agent.failed", code=code, level="error")
            raise BackBrainWorkerError(code) from exc
        await self._finish_cleanup(owner, progress)
        if owner.cancelled:
            raise asyncio.CancelledError
        self._emit(owner, "job.agent.result", code="completed")
        return result.to_payload()

    @staticmethod
    def _bounded_usage(value: object) -> dict[str, int]:
        if not isinstance(value, dict):
            return {}
        bounded: dict[str, int] = {}
        for name in ("input_tokens", "output_tokens", "total_tokens", "cached_tokens", "reasoning_tokens"):
            token_count = value.get(name)
            if type(token_count) is int and 0 <= token_count <= 2**63 - 1:
                bounded[name] = token_count
        return bounded

    async def _observe_start(self, owner: _Owner, progress) -> None:
        started = asyncio.create_task(owner.agent.wait_started(), name=f"back-brain-started-{owner.job.id}")
        try:
            done, _ = await asyncio.wait((owner.run, started), return_when=asyncio.FIRST_COMPLETED)
            if started in done:
                await started
                self._emit(owner, "job.agent.started")
                await self._progress(owner, progress, "agent_started")
        finally:
            started.cancel()
            await asyncio.gather(started, return_exceptions=True)

    async def _progress(self, owner: _Owner, progress, phase: str) -> None:
        try:
            await progress.emit(owner.job.id, JobProgress(phase=phase))
        except Exception:
            self._emit(owner, "job.agent.progress", code="back_brain_progress_unavailable", level="warning")

    async def _finish_cleanup(self, owner: _Owner, progress) -> None:
        reported = False
        try:
            while not await self._cleanup(owner):
                if not reported:
                    reported = True
                    await self._progress(owner, progress, "cleanup_pending")
                await asyncio.sleep(.1)
        except asyncio.CancelledError:
            owner.cancelled = True
            await self._cleanup_preserving_cancellation(owner)
            raise

    async def _close(self, owner: _Owner) -> bool:
        try:
            while not await owner.agent.close_owned():
                # TerminateJobObject is asynchronous. Keep the single cleanup
                # task while membership drains; caller wait remains bounded.
                await asyncio.sleep(.01)
            # Native shutdown first. Cancelling ask before that can deadlock
            # its stdout/stderr/process finalizer or lose an in-flight spawn.
            if not owner.run.done():
                owner.run.cancel()
            await asyncio.gather(owner.run, return_exceptions=True)
            owner.closed = True
            if self._owners.get(owner.job.id) is owner:
                del self._owners[owner.job.id]
            self._emit(owner, "job.agent.closed")
            return True
        except Exception as exc:
            if not owner.cleanup_failed_reported:
                owner.cleanup_failed_reported = True
                self._emit(owner, "job.agent.cleanup", code="back_brain_cleanup_failed", level="warning")
            return False  # Owner retained for an explicit retry; no false closed state.

    async def _cleanup_preserving_cancellation(self, owner: _Owner) -> bool:
        cancelled = False
        deadline = asyncio.get_running_loop().time() + self.cleanup_timeout_s
        while True:
            try:
                remaining = max(0.0, deadline - asyncio.get_running_loop().time())
                result = await self._cleanup(owner, timeout_s=remaining)
                break
            except asyncio.CancelledError:
                cancelled = True
                owner.cancelled = True
        if cancelled:
            raise asyncio.CancelledError
        return result

    async def _cleanup(self, owner: _Owner, *, timeout_s: float | None = None) -> bool:
        if owner.closed:
            return True
        if owner.cleanup is None or (owner.cleanup.done() and not owner.cleanup.result()):
            owner.cleanup = asyncio.create_task(self._close(owner), name=f"back-brain-close-{owner.job.id}")
        try:
            return await asyncio.wait_for(asyncio.shield(owner.cleanup), timeout=self.cleanup_timeout_s if timeout_s is None else timeout_s)
        except TimeoutError:
            if not owner.cleanup_reported:
                owner.cleanup_reported = True
                self._emit(owner, "job.agent.cleanup", code="back_brain_cleanup_pending", level="warning")
            return False

    async def cleanup_owned(self, job_id: str) -> bool:
        """Neutral cleanup observation/retry, never an execution cancellation."""
        owner = self._owners.get(job_id)
        return True if owner is None else await self._cleanup(owner)

    async def cancel_owned(self, job_id: str) -> bool:
        owner = self._owners.get(job_id)
        if owner is None:
            return True  # This worker has no process or pending spawn for this ID.
        owner.cancelled = True
        return await self._cleanup(owner)

    async def cancel(self, job_id: str) -> None:
        await self.cancel_owned(job_id)
