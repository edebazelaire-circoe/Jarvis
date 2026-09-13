"""Adversarial checks for the restricted speculative worker boundary."""
import asyncio
from dataclasses import replace
import os

import pytest

from jarvis.domain.back_brain import (
    BackBrainAdvisoryDependency,
    BackBrainSpeculativeProvenance,
    BackBrainWorkPayload,
    speculative_job_id,
)
from jarvis.domain.v2 import Job
from jarvis.runtime.agent_settings import AgentExecutionSettings
from jarvis.runtime.back_brain_worker import BackBrainJobWorker, BackBrainWorkerError
from jarvis.runtime.claude_local import ClaudeLocalAgent, SPECULATIVE_SYSTEM_PROMPT
from tests.unit.test_back_brain_worker import harness, until


def speculative_job() -> Job:
    proof = BackBrainSpeculativeProvenance(
        "conversation", "live-session", "delegation", 1,
        (BackBrainAdvisoryDependency("live-session", "input", 1, None, False, "Compare 2 and 3."),),
    )
    identifier = speculative_job_id(proof.conversation_id, proof.session_id, proof.delegation_id)
    payload = BackBrainWorkPayload("Compare 2 and 3.", "", proof, scope="speculative_analysis")
    return Job(id=identifier, kind="back_brain", requested_by_conversation_id="conversation",
               idempotency_key=identifier, payload=payload.to_payload())


@pytest.mark.parametrize("command", ["claude.cmd", "claude.bat", "claude.ps1", "claude"])
@pytest.mark.skipif(os.name != "nt", reason="Windows CreateProcess native/shim boundary")
async def test_windows_shims_and_unresolved_command_never_reach_factory(tmp_path, monkeypatch, command):
    settings = AgentExecutionSettings("claude", "anthropic", command, "model", "dontAsk", tmp_path, tmp_path)
    calls = []
    worker = BackBrainJobWorker(lambda: settings, agent_factory=lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr("jarvis.runtime.cli_catalog.resolve_command", lambda value: value)

    with pytest.raises(BackBrainWorkerError, match="speculative_unavailable"):
        await worker.execute(speculative_job())

    assert calls == []


async def test_execution_uses_one_validated_settings_snapshot(tmp_path, monkeypatch):
    safe = AgentExecutionSettings("claude", "anthropic", "claude.exe", "safe-model", "dontAsk", tmp_path, tmp_path)
    changed = replace(safe, agent_cli="codex", provider="openai", command="codex.exe", model="changed-model")
    selected = iter((safe, changed))
    factory_calls = []

    class Agent:
        async def ask(self, text, *, timeout_s):
            return {"ok": True, "text": "bounded result", "session_id": "owned-session"}

        async def wait_started(self):
            return None

        async def close_owned(self):
            return True

    def factory(settings, job_id, *, speculative=False):
        factory_calls.append((settings, job_id, speculative))
        return Agent()

    monkeypatch.setattr("jarvis.runtime.cli_catalog.resolve_command", lambda value: value)
    worker = BackBrainJobWorker(lambda: next(selected), agent_factory=factory)

    result = await worker.execute(speculative_job())

    assert result["provider"] == "anthropic" and result["model"] == "safe-model"
    assert len(factory_calls) == 1 and factory_calls[0][0] is safe and factory_calls[0][2] is True


async def test_speculative_claude_argv_is_exact_and_inherits_no_hooks(harness):
    worker = harness.worker("claude")
    running = asyncio.create_task(worker.execute(speculative_job()))
    try:
        await until(lambda: harness.processes and harness.processes[0].input)
        argv, _ = harness.calls[0]
        assert argv == (
            "claude.exe", "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--restricted", "--tools", "", "--strict-mcp-config", "--safe-mode", "--no-chrome",
            "--disable-slash-commands", "--permission-prompts", "none", "--no-session-persistence",
            "--permission-mode", "dontAsk", "--system-prompt", SPECULATIVE_SYSTEM_PROMPT,
            "--model", "chosen-model",
        )
        harness.processes[0].result("claude", "bounded result")
        assert (await running)["text"] == "bounded result"
    finally:
        await worker.cancel_owned(speculative_job().id)
        await asyncio.gather(running, return_exceptions=True)


@pytest.mark.skipif(os.name != "nt", reason="Windows CreateProcess native/shim boundary")
async def test_direct_speculative_agent_also_rejects_powershell_shim(harness, tmp_path):
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="claude.ps1",
                             execution_profile="speculative_analysis")

    with pytest.raises(RuntimeError, match="direct native argv"):
        await agent.start()

    assert harness.calls == []
