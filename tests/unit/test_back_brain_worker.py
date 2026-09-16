"""Owned wrappers with controlled subprocesses; never invokes an installed CLI."""
import asyncio
import json
from pathlib import Path

import pytest

from jarvis.domain.back_brain import BackBrainProvenance, BackBrainWorkPayload
from jarvis.domain.speech_presentation import SpeechSource
from jarvis.domain.v2 import Job
from jarvis.runtime import cli_catalog
from jarvis.runtime.agent_settings import resolve_agent_execution, resolve_agent_settings
from jarvis.runtime.back_brain_worker import BackBrainJobWorker, BackBrainWorkerError, create_job_agent
from jarvis.runtime.claude_local import BRAIN_SYSTEM_PROMPT, JOB_RESULT_SYSTEM_PROMPT
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.journal import read_jsonl_tail


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0)


class Stream:
    def __init__(self):
        self.queue = asyncio.Queue()

    async def readline(self):
        return await self.queue.get()

    def emit(self, event):
        self.queue.put_nowait(json.dumps(event).encode() + b"\n")

    def eof(self):
        self.queue.put_nowait(b"")


class Process:
    pid = 4321

    def __init__(self):
        self.stdout, self.stderr = Stream(), Stream()
        self.stdin = self
        self.input = b""
        self.returncode = None
        self.exited = asyncio.Event()
        self.terminate_calls = 0
        self.fail_close = False

    def write(self, value):
        self.input += value

    async def drain(self):
        pass

    def close(self):
        pass  # Closing stdin does not finish the controlled provider.

    async def wait(self):
        await self.exited.wait()
        return self.returncode

    def terminate(self):
        self.terminate_calls += 1
        if self.fail_close:
            raise OSError("controlled close failure")
        self.finish(-15)

    def kill(self):
        self.finish(-9)

    def finish(self, code=0):
        if self.returncode is None:
            self.returncode = code
            self.stdout.eof()
            self.stderr.eof()
            self.exited.set()

    def result(self, provider, text, *, usage=None):
        if provider == "claude":
            message = json.loads(self.input.decode())
            self.stdout.emit({"type": "result", "subtype": "success", "result": text,
                              "session_id": "job-session", "user_message_uuids": [message["uuid"]],
                              "usage": usage})
        else:
            self.stdout.emit({"type": "thread.started", "thread_id": "job-session"})
            self.stdout.emit({"type": "item.completed", "item": {"type": "agent_message", "text": text}})
            self.stdout.emit({"type": "turn.completed", "usage": usage})
            self.finish()


@pytest.fixture
def harness(tmp_path, monkeypatch):
    class ControlledTree:
        creationflags = 0x08000004

        def __init__(self):
            self.pid = None
            controlled.trees.append(self)
        def attach_and_resume(self, pid):
            self.pid = pid
            if controlled.tree_failure:
                raise OSError("controlled attach or resume failure")
        def terminate(self):
            pass
        def close_if_empty(self):
            return not controlled.tree_pending

    monkeypatch.setattr("jarvis.runtime.owned_process_tree.OwnedProcessTree", ControlledTree)
    class Harness:
        processes = []
        calls = []
        spawn_gate = None
        trees = []
        tree_failure = False
        tree_pending = False

        async def spawn(self, *argv, **kwargs):
            self.calls.append((argv, kwargs))
            if self.spawn_gate is not None:
                await self.spawn_gate.wait()
            process = Process()
            self.processes.append(process)
            return process

        def settings(self, provider, *, behavior=False):
            payload = {"agent_cli": provider, "agent_cli_settings": {provider: {
                "command": f"{provider}.exe", "model": "chosen-model", "permission_mode": "read-only" if provider == "codex" else "dontAsk",
            }}}
            if behavior:
                payload["agent_behavior"] = {
                    "response_verbosity": "concise", "politeness_formality": "courteous",
                }
            return resolve_agent_execution(payload, cwd=tmp_path, runtime_root=tmp_path, environ={})

        def worker(self, provider, **kwargs):
            return BackBrainJobWorker(lambda: self.settings(provider), **kwargs)

    controlled = Harness()
    async def probe(command):
        return {"available": True, "version": "controlled"}
    monkeypatch.setattr(asyncio, "create_subprocess_exec", controlled.spawn)
    monkeypatch.setattr(cli_catalog, "probe", probe)
    monkeypatch.setattr(cli_catalog, "resolve_command", lambda command: command)
    # Wrappers import this helper directly.
    monkeypatch.setattr("jarvis.runtime.claude_local.resolve_command", lambda command: command)
    monkeypatch.setattr("jarvis.runtime.codex_local.resolve_command", lambda command: command)
    return controlled


def job(job_id="job-a"):
    provenance = BackBrainProvenance("conversation", SpeechSource("core-turn", "source-corr", "intent", 1),
                                     "voice-session", "canonical-turn", "transcript", 1, "provider-input", 1)
    payload = BackBrainWorkPayload("Do the admitted task", "Selected context", provenance)
    return Job(id=job_id, kind="back_brain", requested_by_conversation_id="conversation", payload=payload.to_payload())


@pytest.mark.parametrize("provider", ["claude", "codex"])
@pytest.mark.parametrize("verbosity", ["inherit", "concise"])
async def test_owned_agent_behavior_preserves_inherit_and_composes_explicit_choice(
    tmp_path, provider, verbosity,
):
    captured = []

    class Agent:
        started = asyncio.Event()

        async def ask(self, text, *, timeout_s):
            del timeout_s
            captured.append(text)
            self.started.set()
            return {"ok": True, "text": "complete", "session_id": "owned"}

        async def wait_started(self):
            await self.started.wait()

        async def close_owned(self):
            return True

    settings = resolve_agent_execution(
        {"agent_cli": provider, "agent_behavior": {
            "response_verbosity": verbosity, "politeness_formality": "inherit",
        }},
        cwd=tmp_path, runtime_root=tmp_path, environ={},
    )
    worker = BackBrainJobWorker(lambda: settings, agent_factory=lambda *_args, **_kwargs: Agent())

    await worker.execute(job())

    original = json.dumps(
        {"request": "Do the admitted task", "context_data": "Selected context"}, ensure_ascii=False,
    )
    if verbosity == "inherit":
        assert captured == [original]
    else:
        assert "Réponds de façon concise" in captured[0]
        assert captured[0].endswith("[Demande]\n" + original)


@pytest.mark.parametrize("provider", ["claude", "codex"])
async def test_owned_real_agents_emit_bounded_prompt_evidence_for_behavior(harness, tmp_path, provider):
    created = []

    def factory(settings, job_id):
        agent = create_job_agent(settings, job_id)
        created.append(agent)
        return agent

    worker = BackBrainJobWorker(lambda: harness.settings(provider, behavior=True), agent_factory=factory)
    running = asyncio.create_task(worker.execute(job()))
    try:
        await until(lambda: harness.processes and harness.processes[0].input)
        harness.processes[0].result(provider, "complete")
        await asyncio.wait_for(running, 2)

        events = read_jsonl_tail(tmp_path / "trace.jsonl", limit=300)
        prompt_events = [
            event for event in events
            if event["kind"] == "job.agent.prompt"
            and event["data"].get("program_id") == f"backend.{provider}.turn"
        ]
        assert len(prompt_events) == 1
        event = prompt_events[0]
        assert event["level"] == "info"
        assert event["data"]["job_id"] == "job-a"
        assert event["data"]["program_id"] == f"backend.{provider}.turn"
        assert event["data"]["channel"] == "stdin.user_message"
        assert event["data"]["application"] == "sent"
        assert event["data"]["static_fingerprint"]
        assert "Réponds de façon concise" not in json.dumps(event)
        assert "Réponds de façon concise" in harness.processes[0].input.decode("utf-8")
        assert "Réponds de façon concise" not in json.dumps(created[0].snapshot(), ensure_ascii=False)
        turn_evidence = [
            item for item in created[0].prompt_applications
            if item.get("program_id") == f"backend.{provider}.turn"
        ]
        assert len(turn_evidence) == 1
        assert turn_evidence[0]["render_fingerprint"] == event["data"]["render_fingerprint"]
    finally:
        await worker.cancel_owned("job-a")
        await asyncio.gather(running, return_exceptions=True)


@pytest.mark.parametrize("provider", ["claude", "codex"])
async def test_job_owns_a_fresh_wrapper_and_returns_only_full_terminal_result(harness, tmp_path, provider):
    worker = harness.worker(provider)
    class Progress:
        values = []
        async def emit(self, job_id, value):
            self.values.append((job_id, value))
    progress = Progress()
    running = asyncio.create_task(worker.execute_with_progress(job(), progress))
    try:
        await until(lambda: harness.processes and harness.processes[0].input)
        process = harness.processes[0]
        argv, kwargs = harness.calls[0]
        assert kwargs["cwd"] == str(tmp_path)
        assert kwargs["creationflags"] == 0x08000004  # Both CLIs are suspended and hidden until assigned.
        assert "chosen-model" in argv
        assert "--resume" not in argv and "resume" not in argv
        if provider == "claude":
            assert "--chrome" not in argv
            assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
            assert argv[argv.index("--append-system-prompt") + 1] == JOB_RESULT_SYSTEM_PROMPT
            assert BRAIN_SYSTEM_PROMPT not in argv
            hook = json.loads(argv[argv.index("--settings") + 1])
            assert str(tmp_path) in hook["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
            process.stdout.emit({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Preamble is not a result"}]}})
        else:
            assert "sandbox_mode=read-only" in argv
            process.stdout.emit({"type": "item.started", "item": {"type": "agent_message", "text": "Preamble"}})
        for _ in range(5):
            await asyncio.sleep(0)
        assert not running.done()
        full = "Complete factual result\n" * 300
        process.result(provider, full, usage={"input_tokens": 10, "output_tokens": 2,
                                              "ignored_text": "must not escape"})
        result = await asyncio.wait_for(running, 2)
        assert result == {"schema_version": 1, "text": full, "provider": "anthropic" if provider == "claude" else "openai",
                          "model": "chosen-model", "session_id": "job-session", "code": "completed"}
        assert process.returncode is not None and not worker.active_job_ids
        assert [(key, value.phase, value.public_summary, value.fraction) for key, value in progress.values] == [
            ("job-a", "agent_started", "", None), ("job-a", "finalizing", "", None)]
        events = read_jsonl_tail(tmp_path / "trace.jsonl", limit=300)
        assert any(e["kind"] == "job.agent.closed" for e in events)
        assert any(e["kind"] == "job.agent.result" for e in events)
        usage_events = [e for e in events if e["kind"] == "core.back_brain.provider_usage"]
        assert len(usage_events) == 1
        assert usage_events[0]["data"]["correlation_id"] == "source-corr"
        assert usage_events[0]["data"]["work_id"] == "job-a"
        assert usage_events[0]["data"]["usage"] == {"input_tokens": 10, "output_tokens": 2}
        assert "ignored_text" not in json.dumps(usage_events)
        assert "Do the admitted task" not in json.dumps(events)
        assert "Complete factual" not in json.dumps(events)
        assert not any("speech" in e["kind"] for e in events)
    finally:
        await worker.cancel_owned("job-a")
        await asyncio.gather(running, return_exceptions=True)


@pytest.mark.parametrize("provider", ["claude", "codex"])
async def test_cancel_during_spawn_retains_owner_then_closes_exact_process(harness, provider):
    harness.spawn_gate = asyncio.Event()
    worker = harness.worker(provider, cleanup_timeout_s=.01)
    running = asyncio.create_task(worker.execute(job()))
    try:
        await until(lambda: harness.calls)
        assert await worker.cancel_owned("job-a") is False
        assert worker.active_job_ids == ("job-a",)
        with pytest.raises(BackBrainWorkerError, match="worker_busy"):
            await worker.execute(job("job-b"))
        assert len(harness.calls) == 1
        harness.spawn_gate.set()
        await until(lambda: harness.processes and harness.processes[0].returncode is not None)
        assert await worker.cancel_owned("job-a") is True
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(running, 2)
        assert harness.processes[0].terminate_calls == 1
        assert await worker.cancel_owned("job-a") is True
        assert not worker.active_job_ids
    finally:
        harness.spawn_gate.set()
        await worker.cancel_owned("job-a")
        await asyncio.gather(running, return_exceptions=True)


@pytest.mark.parametrize("provider", ["claude", "codex"])
async def test_external_cancellation_repeated_during_spawn_keeps_cleanup_owned(harness, provider):
    harness.spawn_gate = asyncio.Event()
    worker = harness.worker(provider, cleanup_timeout_s=.1)
    running = asyncio.create_task(worker.execute(job()))
    try:
        await until(lambda: harness.calls)
        running.cancel()
        await asyncio.sleep(0)
        running.cancel()
        await asyncio.sleep(0)
        harness.spawn_gate.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(running, 2)
        await until(lambda: not worker.active_job_ids)
        assert harness.processes[0].terminate_calls == 1
    finally:
        harness.spawn_gate.set()
        await worker.cancel_owned("job-a")
        await asyncio.gather(running, return_exceptions=True)


@pytest.mark.parametrize("provider", ["claude", "codex"])
async def test_failure_to_close_retains_slot_until_retry_and_does_not_touch_another_job(harness, provider):
    worker = harness.worker(provider)
    running = asyncio.create_task(worker.execute(job()))
    await until(lambda: harness.processes and harness.processes[0].input)
    first = harness.processes[0]
    try:
        first.fail_close = True
        assert await worker.cancel_owned("job-a") is False
        assert worker.active_job_ids == ("job-a",)
        first.fail_close = False
        assert await worker.cancel_owned("job-a") is True
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(running, 2)
        second = asyncio.create_task(worker.execute(job("job-b")))
        try:
            await until(lambda: len(harness.processes) == 2 and harness.processes[1].input)
            assert await worker.cancel_owned("job-a") is True
            assert harness.processes[1].returncode is None
            harness.processes[1].result(provider, "B result")
            assert (await asyncio.wait_for(second, 2))["text"] == "B result"
        finally:
            await worker.cancel_owned("job-b")
            await asyncio.gather(second, return_exceptions=True)
    finally:
        first.fail_close = False
        await worker.cancel_owned("job-a")
        await asyncio.gather(running, return_exceptions=True)


@pytest.mark.parametrize("provider", ["claude", "codex"])
async def test_timeout_closes_process_before_reporting_failure(harness, provider):
    worker = harness.worker(provider, timeout_s=.02)
    with pytest.raises(BackBrainWorkerError, match="timeout|execution_failed"):
        await asyncio.wait_for(worker.execute(job()), 2)
    assert harness.processes[0].returncode is not None
    assert not worker.active_job_ids


async def test_unsupported_speculation_refuses_before_factory_or_spawn(harness):
    worker = harness.worker("codex")
    speculative = Job(kind="back_brain", payload={"scope": "speculative_analysis"})
    with pytest.raises(BackBrainWorkerError, match="speculative_unavailable"):
        await worker.execute(speculative)
    assert not harness.calls


@pytest.mark.parametrize("provider", ["claude", "codex"])
async def test_attachment_failure_closes_suspended_process_and_tree_without_result(harness, provider):
    harness.tree_failure = True
    worker = harness.worker(provider)
    with pytest.raises(BackBrainWorkerError):
        await asyncio.wait_for(worker.execute(job()), 2)
    assert harness.processes[0].returncode is not None
    assert harness.processes[0].input == b""
    assert not worker.active_job_ids


@pytest.mark.parametrize("provider", ["claude", "codex"])
async def test_root_exit_without_empty_tree_stays_pending_and_releases_only_after_membership_proof(harness, tmp_path, provider):
    harness.tree_pending = True
    worker = harness.worker(provider, cleanup_timeout_s=.01)
    running = asyncio.create_task(worker.execute(job()))
    try:
        await until(lambda: harness.processes and harness.processes[0].input)
        assert await worker.cancel_owned("job-a") is False
        assert harness.processes[0].returncode is not None
        assert worker.active_job_ids == ("job-a",)
        harness.tree_pending = False
        await until(lambda: not worker.active_job_ids)
        assert await worker.cancel_owned("job-a") is True
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(running, 2)
        assert sum(e["kind"] == "job.agent.stop" for e in read_jsonl_tail(tmp_path / "trace.jsonl")) == 1
    finally:
        harness.tree_pending = False
        await worker.cancel_owned("job-a")
        await asyncio.gather(running, return_exceptions=True)


@pytest.mark.parametrize("provider", ["claude", "codex"])
async def test_oversized_result_is_rejected_without_truncating_or_publishing_success(harness, tmp_path, provider):
    worker = harness.worker(provider)
    running = asyncio.create_task(worker.execute(job()))
    try:
        await until(lambda: harness.processes and harness.processes[0].input)
        harness.processes[0].result(provider, "x" * 16385)
        with pytest.raises(BackBrainWorkerError, match="invalid_result"):
            await asyncio.wait_for(running, 2)
        assert not worker.active_job_ids
        assert not any(e["kind"] == "job.agent.result" for e in read_jsonl_tail(tmp_path / "trace.jsonl"))
    finally:
        await worker.cancel_owned("job-a")
        await asyncio.gather(running, return_exceptions=True)


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_control_center_and_job_share_exact_settings_precedence(tmp_path, monkeypatch, provider):
    monkeypatch.setenv("JARVIS_CLAUDE_CLI", "env-command")
    monkeypatch.setenv("JARVIS_CLAUDE_MODEL", "env-model")
    monkeypatch.setenv("JARVIS_CLAUDE_PERMISSION_MODE", "manual")
    settings = {"agent_cli": provider, "claude_cli": "old-command", "claude_permission_mode": "acceptEdits",
                "agent_cli_settings": {provider: {"command": "saved-command", "model": "saved-model", "permission_mode": "read-only" if provider == "codex" else "dontAsk"}}}
    ui = ControlCenter._agent_settings(object(), settings, provider)
    execution = resolve_agent_execution(settings, cwd=tmp_path, runtime_root=tmp_path / "runtime")
    assert ui == {"command": execution.command, "model": execution.model, "permission_mode": execution.permission_mode}
    assert execution.cwd == tmp_path and execution.runtime_root == tmp_path / "runtime"
    assert execution.command == "saved-command" and execution.model == "saved-model"
    settings.pop("agent_cli_settings")
    legacy = resolve_agent_settings(settings, "claude")
    assert legacy == {"command": "old-command", "model": "env-model", "permission_mode": "acceptEdits"}


async def test_core_composition_keeps_startup_profile_for_a_job_accepted_behind_a_running_job(harness, tmp_path, monkeypatch):
    from jarvis import app
    from jarvis.core.v2_app import JarvisCoreApplication
    from jarvis.v2_config import V2Settings, VoiceArchitecture
    from tests.unit.test_back_brain_tasks import admitted, submit, settle

    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    config_path = runtime_root / "control-center-settings.json"
    config_path.write_text(json.dumps({"agent_cli": "claude", "agent_cli_settings": {"claude": {
        "command": "claude.exe", "model": "accepted-model", "permission_mode": "dontAsk"}}}))
    settings = V2Settings(tmp_path / "data", runtime_root, "127.0.0.1", 0, "Europe/Paris",
                         runtime_root / "core.token", 12, 0, "unused", "cedar", True, VoiceArchitecture.LEGACY)
    monkeypatch.setattr(V2Settings, "load", classmethod(lambda cls: settings))
    monkeypatch.setattr(app, "_calendar_backend_from_env", lambda: None)
    monkeypatch.setattr(app, "_drive_backend_from_env", lambda: None)
    monkeypatch.setenv("JARVIS_WINDOWS_NOTIFICATIONS", "0")

    class Backend:
        base_url = "http://controlled.invalid"
        async def close(self):
            pass
        async def run_turn(self, turn, sink):
            raise AssertionError("job worker never calls the conversational backend")
    monkeypatch.setattr(app, "_brain_backend_from_env", Backend)

    async def drive(core):
        request, first = await admitted(core)
        a = await submit(core, first)
        await until(lambda: harness.processes and harness.processes[0].input)
        _, second = await admitted(core, conversation_id=request.conversation_id, item="b", text="Second admitted job")
        b = await submit(core, second)
        assert (await core.state.get_job(b.job_id)).status.value == "pending"
        config_path.write_text(json.dumps({"agent_cli": "codex", "agent_cli_settings": {"codex": {
            "command": "changed-command", "model": "changed-model", "permission_mode": "danger-full-access"}}}))
        harness.processes[0].result("claude", "First complete result")
        await settle(core, a.job_id)
        await until(lambda: len(harness.processes) == 2 and harness.processes[1].input)
        argv, kwargs = harness.calls[1]
        assert argv[0] == "claude.exe"
        assert argv[argv.index("--model") + 1] == "accepted-model"
        assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
        assert kwargs["cwd"] == str(app.ROOT)
        harness.processes[1].result("claude", "Second complete result")
        await settle(core, b.job_id)
        assert (await core.state.get_job(b.job_id)).result["provider"] == "anthropic"
        assert (await core.state.get_job(b.job_id)).result["model"] == "accepted-model"

    monkeypatch.setattr(JarvisCoreApplication, "wait", drive)
    assert await asyncio.wait_for(app._run_core_v2(), 5) == 0


async def test_real_worker_retains_result_until_native_cleanup_then_core_completes(harness, tmp_path):
    from jarvis.core.v2_app import JarvisCoreApplication
    from tests.unit.test_back_brain_tasks import admitted, submit, settle
    worker = harness.worker("claude", cleanup_timeout_s=.01)
    core = JarvisCoreApplication(data_root=tmp_path / "data", workers={"back_brain": worker})
    await core.start()
    core.jobs.progress_min_interval_s = 0
    harness.tree_pending = True
    try:
        _, admission = await admitted(core)
        accepted = await submit(core, admission)
        await until(lambda: harness.processes and harness.processes[0].input)
        harness.processes[0].result("claude", "EXACT FINISHED RESULT")
        async with asyncio.timeout(2):
            while (job := await core.state.get_job(accepted.job_id)).progress is None or job.progress["phase"] != "cleanup_pending":
                await asyncio.sleep(.002)
        assert job.status.value == "running" and job.result is None
        assert worker.active_job_ids == (accepted.job_id,)
        assert await worker.cleanup_owned(accepted.job_id) is False
        harness.tree_pending = False
        await settle(core, accepted.job_id)
        job = await core.state.get_job(accepted.job_id)
        assert job.status.value == "completed" and job.result["text"] == "EXACT FINISHED RESULT"
        assert not worker.active_job_ids
    finally:
        harness.tree_pending = False
        await core.stop()


@pytest.mark.parametrize("provider", ["claude", "codex"])
@pytest.mark.parametrize("valid", [True, False])
async def test_unavailable_journal_never_changes_wrapper_or_worker_outcome(harness, monkeypatch, provider, valid):
    from jarvis.runtime.journal import RuntimeJournal
    observed = []
    def broken(self, kind, *args, **kwargs):
        observed.append(kind)
        raise OSError("controlled journal unavailable")
    monkeypatch.setattr(RuntimeJournal, "emit", broken)
    worker = harness.worker(provider)
    run = asyncio.create_task(worker.execute(job()))
    await until(lambda: harness.processes and harness.processes[0].input)
    harness.processes[0].result(provider, "EXACT RESULT" if valid else "")
    if valid:
        assert (await asyncio.wait_for(run, 2))["text"] == "EXACT RESULT"
        assert "job.agent.result" in observed
        assert "job.agent.finalizing" in observed
    else:
        with pytest.raises(BackBrainWorkerError, match="back_brain_invalid_result"):
            await asyncio.wait_for(run, 2)
        assert "job.agent.failed" in observed
    assert "job.agent.owned" in observed and "job.agent.closed" in observed
    assert not worker.active_job_ids
