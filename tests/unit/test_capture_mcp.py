"""Serveur MCP `jarvis-capture` (session-context-recording, Slice 09) contre un vrai Control Center et un vrai Core.

Contrat : `docs/mcp/tool-contract.md` §10.11, `jarvis/runtime/capture_mcp.py`. Ce
qui doit tenir : chaque outil passe par `/api/...` du Control Center (jamais
Core), son résultat valide le schéma annoncé, le statut rendu est celui du
`CaptureService`, une transcription est rendue avec sa note non adressée,
jamais d'octets de média ni de chemin absolu, refus codés, arguments inconnus
refusés avant tout envoi.
"""

from __future__ import annotations

import inspect
import json
import socket

import jsonschema
import pytest

from jarvis.runtime import capture_mcp
from jarvis.runtime.claude_local import launched_append_prompt
from jarvis.runtime.capture_mcp import (
    AMBIENT_NOTE, CONFIG_FILE_NAME, SERVER_NAME, TOOL_NAMES, CaptureTools, CaptureToolError, build_server,
    mcp_config, write_mcp_config,
)
from jarvis.runtime.settings_mcp import ConsoleMcpTarget
from tests.fakes.capture_stack import TOKEN, CaptureStack, until


def test_the_mcp_config_launches_this_server_and_carries_no_secret(tmp_path):
    target = ConsoleMcpTarget("127.0.0.1", 17654, tmp_path)
    document = mcp_config(target, python="python.exe")
    server = document["mcpServers"][SERVER_NAME]
    assert server["args"] == ["-m", "jarvis", "capture-mcp"]
    assert server["env"]["JARVIS_CONTROL_CENTER_PORT"] == "17654"
    path = write_mcp_config(target, tmp_path)
    assert path.name == CONFIG_FILE_NAME and json.loads(path.read_text(encoding="utf-8")) == mcp_config(target)
    assert "token" not in path.read_text(encoding="utf-8").lower()


def test_no_tool_ever_reads_payload_bytes_or_deletes():
    source = inspect.getsource(capture_mcp).replace(capture_mcp.__doc__ or "", "")
    assert "/payload" not in source and '"DELETE"' not in source and "/abandon" not in source
    assert TOOL_NAMES == ("context_status", "context_switch", "capture_status", "capture_start", "capture_stop",
                          "screenshot_take", "artifact_search", "artifact_get", "transcript_read")


class Brain:
    """Le serveur réel, en mémoire, sur le vrai Control Center d'une `CaptureStack`."""

    def __init__(self, stack: CaptureStack) -> None:
        self.stack = stack
        self.tools = CaptureTools(ConsoleMcpTarget("127.0.0.1", stack.cc_port, None))
        self.server = build_server(tools=self.tools)
        self.schemas: dict = {}

    async def __aenter__(self) -> "Brain":
        from mcp.shared.memory import create_connected_server_and_client_session

        self.schemas = {tool.name: tool.outputSchema for tool in await self.server.list_tools()}
        self._session_cm = create_connected_server_and_client_session(self.server)
        self.session = await self._session_cm.__aenter__()
        return self

    async def __aexit__(self, *exc) -> None:
        await self._session_cm.__aexit__(*exc)
        await self.tools.close()

    async def call(self, name: str, arguments: dict | None = None) -> dict:
        result = await self.session.call_tool(name, arguments or {})
        assert result.isError is False, result.content[0].text
        jsonschema.validate(result.structuredContent, self.schemas[name])
        text = json.dumps(result.structuredContent, ensure_ascii=False)
        assert TOKEN not in text and str(self.stack.tmp_path) not in text
        assert str(self.stack.tmp_path).replace("\\", "\\\\") not in text
        return result.structuredContent

    async def refused(self, name: str, arguments: dict | None = None) -> str:
        result = await self.session.call_tool(name, arguments or {})
        assert result.isError is True
        return result.content[0].text


async def test_recording_cycle_through_the_brain_tools_matches_the_capture_owner(tmp_path):
    async with CaptureStack(tmp_path) as stack, Brain(stack) as brain:
        assert (await brain.call("capture_status"))["recordings"] == []
        started = await brain.call("capture_start", {"channel": "audio"})
        assert started["state"] == "active" and started["note"] == "L'enregistrement audio tourne."
        status = await brain.call("capture_status")
        truth = stack.core.captures.status().captures
        assert [r["capture_id"] for r in status["recordings"]] == [r.capture_id for r in truth]
        assert status["recordings"][0]["transcription"]["state"] in {"running", "complete"}
        row = await stack.core.captures.get(started["capture_id"])
        assert dict(row.data) == {"origin": "brain"}

        refusal = await brain.refused("capture_start", {"channel": "audio"})
        assert refusal.startswith("Refus already_active : ") and "(Core : " in refusal

        stopped = await brain.call("capture_stop")
        assert stopped["state"] == "complete" and stopped["capture_id"] == started["capture_id"]
        nothing = await brain.call("capture_stop")
        assert nothing == {"state": "none", "note": "Aucun enregistrement en cours."}
        again = await brain.call("capture_stop", {"capture_id": started["capture_id"]})
        assert again["state"] == "complete"  # idempotent

        async def transcribed() -> bool:
            return (await stack.core.capture_api.capture(started["capture_id"]))["capture"]["transcription"][
                "state"] == "complete"

        await until(transcribed)
        tail = await brain.call("transcript_read", {"capture_id": started["capture_id"]})
        assert [s["text"] for s in tail["segments"]] == ["phrase 1", "phrase 2", "phrase 3"]
        assert tail["segments"][0]["at"] == "00:00" and tail["note"] == AMBIENT_NOTE
        follow = await brain.call("transcript_read", {"artifact_id": started["artifact_id"], "after_seq": 2})
        assert [s["seq"] for s in follow["segments"]] == [3]
        recent = (await brain.call("capture_status"))["recent"]
        assert recent[0]["capture_id"] == started["capture_id"] and recent[0]["transcription"]["segments"] == 3


async def test_two_open_recordings_need_a_channel_to_stop(tmp_path):
    async with CaptureStack(tmp_path) as stack, Brain(stack) as brain:
        await brain.call("capture_start", {"channel": "audio"})
        screen = await brain.call("capture_start", {"channel": "screen", "display": "default"})
        refusal = await brain.refused("capture_stop")
        assert "Plusieurs enregistrements" in refusal
        stopped = await brain.call("capture_stop", {"channel": "screen"})
        assert stopped["capture_id"] == screen["capture_id"]
        assert [r.channel.value for r in stack.core.captures.status().captures] == ["audio"]


async def test_screenshot_search_and_get_never_return_bytes(tmp_path):
    async with CaptureStack(tmp_path) as stack, Brain(stack) as brain:
        shot = await brain.call("screenshot_take")
        assert shot["state"] == "complete" and shot["width"] == 1
        found = await brain.call("artifact_search", {"kind": ["screenshot"]})
        assert found["scope"] == "active_context" and [i["artifact_id"] for i in found["items"]] == [shot["artifact_id"]]
        detail = await brain.call("artifact_get", {"artifact_id": shot["artifact_id"]})
        assert detail["kind"] == "screenshot" and detail["mime_type"] == "image/png" and "note" not in detail
        assert detail["origins"] == [] and "payload_ref" not in detail
        recent = await brain.call("artifact_search", {"scope": "session", "since_minutes": 5, "limit": 1})
        assert len(recent["items"]) == 1


async def test_contexts_status_and_switch(tmp_path):
    async with CaptureStack(tmp_path) as stack, Brain(stack) as brain:
        first = await brain.call("context_status")
        first_id = first["active"]["context_id"]
        assert first["dormant"] == [] and first["active"]["workspace_ref"].startswith("sessions/")
        created = await brain.call("context_switch", {"title": "Revue release", "handoff_summary": "Export PDF.",
                                                      "carry_from_current": True})
        assert created["status"] == "created" and created["previous_context_id"] == first_id
        assert created["handoff_written"] is True and created["note"] == "Nouveau contexte « Revue release »."
        status = await brain.call("context_status")
        assert status["active"]["title"] == "Revue release" and status["dormant"][0]["context_id"] == first_id
        back = await brain.call("context_switch", {"context_id": first_id})
        assert back["status"] == "activated" and back["previous_context_id"] == created["context_id"]
        same = await brain.call("context_switch", {"context_id": first_id})
        assert same["status"] == "unchanged"
        mixed = await brain.refused("context_switch", {"context_id": first_id, "title": "x"})
        assert "context_id réactive" in mixed
        # Trace réelle : un appel vide (outil différé appelé sans son schéma) ne doit rien ouvrir.
        empty = await brain.refused("context_switch", {})
        assert "Donne title" in empty
        assert len((await brain.call("context_status"))["dormant"]) == 1
        missing = await brain.refused("context_switch", {"context_id": "jctx_missing"})
        assert missing.startswith("Refus context_not_found : ")
        events = [e for e in stack.trace() if e.get("kind") == "capture.tool"]
        assert events == []  # le journal du serveur n'est écrit que par le processus MCP réel (journal absent ici)


async def test_arguments_are_checked_before_anything_is_sent(tmp_path):
    async with CaptureStack(tmp_path) as stack, Brain(stack) as brain:
        extra = await brain.refused("capture_start", {"channel": "audio", "path": "C:/x"})
        assert "Arguments inconnus refusés, rien n'a été envoyé : path" in extra
        bad = await brain.refused("capture_start", {"channel": "camera"})
        assert bad.startswith("Argument invalide, rien n'a été envoyé")
        bad_display = await brain.refused("screenshot_take", {"display": "C:/x"})
        assert bad_display.startswith("Argument invalide")
        both = await brain.refused("transcript_read", {"capture_id": "jcap_a", "artifact_id": "jart_b"})
        assert "un seul" in both
        too_long = await brain.refused("transcript_read", {"capture_id": "jcap_a", "max_chars": 4001})
        assert too_long.startswith("Argument invalide")
        assert stack.core.captures.status().captures == ()


async def test_an_unreachable_control_center_is_a_coded_tool_error():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    tools = CaptureTools(ConsoleMcpTarget("127.0.0.1", port, None))
    try:
        with pytest.raises(CaptureToolError) as caught:
            await tools.capture_status()
        assert caught.value.code == "control_center_unreachable"
    finally:
        await tools.close()


async def test_tool_journal_lines_carry_codes_never_text(tmp_path):
    from jarvis.runtime.journal import RuntimeJournal

    async with CaptureStack(tmp_path) as stack:
        runtime = tmp_path / "mcp-runtime"
        tools = CaptureTools(ConsoleMcpTarget("127.0.0.1", stack.cc_port, runtime), journal=RuntimeJournal(runtime))
        try:
            await tools.capture_start("audio", None)
            with pytest.raises(CaptureToolError):
                await tools.capture_start("audio", None)
        finally:
            await tools.close()
        lines = [json.loads(line) for line in (runtime / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
        kinds = [line["kind"] for line in lines]
        assert "capture.tool" in kinds and "capture.tool_failed" in kinds
        failed = next(line for line in lines if line["kind"] == "capture.tool_failed")
        assert failed["data"]["code"] == "already_active" and failed["data"]["source"] == "Core"


# ------------------------------------------------------------------ déclaration au cerveau Claude


async def test_the_conversation_brain_declares_jarvis_capture_and_the_gateway_lists_it(monkeypatch, tmp_path):
    """`--mcp-config` de `jarvis-capture` après la console, avant la passerelle ; natif listable ; consigne au socle."""

    from jarvis.runtime import claude_local
    from jarvis.runtime.claude_local import BRAIN_CAPTURE_PROMPT, ClaudeLocalAgent
    from jarvis.runtime.tools_gateway_mcp import ENV_NATIVE_SERVERS, ToolsGatewayTarget
    from tests.unit.test_claude_tools_gateway_args import SENTINEL, _config_paths, _Process

    runtime = tmp_path / "runtime"
    token = tmp_path / "core.token"
    token.write_text(SENTINEL, encoding="utf-8")
    agent = ClaudeLocalAgent(runtime_root=runtime, cwd=tmp_path,
                             console_mcp=ConsoleMcpTarget("127.0.0.1", 47002, runtime),
                             capture_mcp=ConsoleMcpTarget("127.0.0.1", 47002, runtime),
                             tools_mcp=ToolsGatewayTarget("127.0.0.1", 47001, token, runtime))
    started: list[list[str]] = []

    async def fake_exec(*args, **kwargs):  # noqa: ANN002, ANN003
        started.append([str(arg) for arg in args])
        return _Process()

    monkeypatch.setattr(claude_local.asyncio, "create_subprocess_exec", fake_exec)
    if agent._process_tree is not None:
        monkeypatch.setattr(agent._process_tree, "attach_and_resume", lambda pid: None)
    await agent.start()
    assert agent.snapshot()["capture_tools"] is True
    agent.process.returncode = 0  # type: ignore[union-attr]
    assert agent.snapshot()["capture_tools"] is False
    await agent.stop()
    argv = started[0]
    paths = _config_paths(argv)
    assert [path.name for path in paths] == ["console-mcp.json", CONFIG_FILE_NAME, "tools-mcp.json"]
    capture = json.loads(paths[1].read_text(encoding="utf-8"))["mcpServers"][SERVER_NAME]
    assert capture["args"] == ["-m", "jarvis", "capture-mcp"] and SENTINEL not in paths[1].read_text(encoding="utf-8")
    gateway = json.loads(paths[2].read_text(encoding="utf-8"))["mcpServers"]["jarvis-tools"]
    assert gateway["env"][ENV_NATIVE_SERVERS] == "jarvis-console,jarvis-capture"
    assert BRAIN_CAPTURE_PROMPT.strip() in launched_append_prompt(argv)


async def test_a_capture_config_that_cannot_be_written_is_said_and_the_brain_still_starts(monkeypatch, tmp_path):
    from jarvis.runtime.claude_local import ClaudeLocalAgent
    from jarvis.runtime.journal import read_jsonl_tail

    agent = ClaudeLocalAgent(runtime_root=tmp_path / "runtime", cwd=tmp_path,
                             capture_mcp=ConsoleMcpTarget("127.0.0.1", 47002, tmp_path / "runtime"))

    def refuse(*args, **kwargs):  # noqa: ANN002, ANN003
        raise OSError("disk refused")

    monkeypatch.setattr(capture_mcp, "write_mcp_config", refuse)
    assert agent._capture_mcp_args() == []
    errors = [e for e in read_jsonl_tail(tmp_path / "runtime" / "trace.jsonl", limit=10)
              if e["kind"] == "agent.capture_mcp_failed"]
    assert errors and errors[0]["data"]["code"] == "capture_mcp_config_write_failed"


# ------------------------------------------------------------------ rework QA Slice 09


async def test_an_origin_refusal_of_the_control_center_is_a_stable_code_for_the_brain(tmp_path):
    import aiohttp

    async with CaptureStack(tmp_path) as stack:
        tools = CaptureTools(ConsoleMcpTarget("127.0.0.1", stack.cc_port, None),
                             session_factory=lambda: aiohttp.ClientSession(headers={"Origin": "https://evil.example"}))
        try:
            with pytest.raises(CaptureToolError) as caught:
                await tools.capture_status()
        finally:
            await tools.close()
        assert caught.value.code == "forbidden_origin", caught.value
        assert str(caught.value).startswith("Refus forbidden_origin : Le Control Center refuse cette origine")
        assert "(Control Center : " in str(caught.value)


async def test_the_session_scope_asks_core_for_the_current_session(tmp_path, monkeypatch):
    """Mutant M9-21 : `scope=session` doit filtrer sur la Session ouverte, pas tout lire."""

    async with CaptureStack(tmp_path) as stack, Brain(stack) as brain:
        await brain.call("screenshot_take")
        seen: list[tuple[str, object]] = []
        forward = stack.sessions.forward_once

        async def spy(method, path, **kwargs):  # noqa: ANN001, ANN003, ANN202
            seen.append((path, kwargs.get("params")))
            return await forward(method, path, **kwargs)

        monkeypatch.setattr(stack.sessions, "forward_once", spy)
        for scope, expected in (("session", ("jarvis_session_id", "current")), ("active_context", ("context_id", "active"))):
            seen.clear()
            await brain.call("artifact_search", {"scope": scope})
            assert seen and expected in list(seen[-1][1]), seen
        seen.clear()
        await brain.call("artifact_search", {"scope": "all"})
        assert not {key for key, _ in seen[-1][1]} & {"jarvis_session_id", "context_id"}


async def test_char_offset_goes_with_after_seq(tmp_path):
    async with CaptureStack(tmp_path) as stack, Brain(stack) as brain:
        alone = await brain.refused("transcript_read", {"capture_id": "jcap_a", "char_offset": 3})
        assert "char_offset va avec after_seq" in alone
        assert stack.core.captures.status().captures == ()
