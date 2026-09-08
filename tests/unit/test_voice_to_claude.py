"""La boucle fondamentale : voix → Claude → retour vocal.

JARVIS est une interface vocale vers un agent capable d'agir sur le PC. Le
modèle Realtime ne répond donc pas de lui-même aux demandes portant sur la
machine : il appelle `claude_task`, qui est intercepté avant Core et transmis à
l'agent Claude local. Le texte que Claude renvoie est ce que JARVIS prononce.

Une panne de Claude ne doit jamais casser le tour vocal : elle revient sous
forme de phrase prononçable.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from aiohttp import web

from jarvis.adapters.openai_realtime import OPERATING_RULES
from jarvis.domain.v2 import ProtocolEnvelope
from jarvis.runtime.claude_gateway import ClaudeGateway
from jarvis.runtime.claude_local import ClaudeLocalAgent
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.journal import read_jsonl_tail
from jarvis.runtime.realtime_audio import CLAUDE_TOOL, RealtimeConversationBridge
from jarvis.runtime.realtime_tools import REALTIME_TOOLS


# --------------------------------------------------------------------------
# L'outil et les instructions


def test_claude_task_is_offered_to_the_realtime_model():
    tool = next(t for t in REALTIME_TOOLS if t["name"] == CLAUDE_TOOL)

    assert tool["parameters"]["required"] == ["request"]
    description = str(tool["description"]).lower()
    assert "agent local" in description
    # Le modèle doit comprendre que c'est la voie des actions sur la machine.
    assert "commandes" in description and "fichiers" in description


def test_the_persona_forbids_answering_local_requests_alone():
    assert "claude_task" in OPERATING_RULES
    assert "Tu ne réponds jamais de toi-même" in OPERATING_RULES
    # Les rappels et l'agenda gardent leurs outils Core dédiés.
    assert "pas par claude_task" in OPERATING_RULES


# --------------------------------------------------------------------------
# ask() : l'aller-retour complet


class FakeStdin:
    def __init__(self) -> None:
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        return None


class FakeProcess:
    pid = 1234

    def __init__(self) -> None:
        self.stdin = FakeStdin()
        self.returncode = None

    def terminate(self) -> None:
        self.returncode = 1

    def kill(self) -> None:
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode or 0


def _running_agent(tmp_path: Path) -> ClaudeLocalAgent:
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path)
    agent.process = FakeProcess()  # type: ignore[assignment]
    return agent


async def test_ask_returns_the_answer_of_the_completed_turn(tmp_path):
    agent = _running_agent(tmp_path)

    async def reply() -> None:
        await asyncio.sleep(0)
        agent._resolve_pending({
            "type": "result", "subtype": "success", "result": "Le notepad est ouvert.",
            "session_id": "sid-1", "duration_ms": 2100, "total_cost_usd": 0.01,
        })

    asyncio.get_running_loop().create_task(reply())
    result = await agent.ask("ouvre un notepad", timeout_s=5)

    assert result["ok"] is True
    assert result["text"] == "Le notepad est ouvert."
    assert result["duration_ms"] == 2100
    sent = json.loads(agent.process.stdin.written[0].decode("utf-8"))
    assert sent["message"]["content"] == "ouvre un notepad"


async def test_ask_reports_a_failed_turn_rather_than_a_false_success(tmp_path):
    agent = _running_agent(tmp_path)

    async def reply() -> None:
        await asyncio.sleep(0)
        agent._resolve_pending({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "boom"})

    asyncio.get_running_loop().create_task(reply())
    result = await agent.ask("casse tout", timeout_s=5)

    assert result["ok"] is False
    assert result["error"] == "boom"
    assert read_jsonl_tail(tmp_path / "errors.jsonl")[-1]["kind"] == "agent.ask"


async def test_ask_gives_up_instead_of_hanging_the_voice_turn(tmp_path):
    agent = _running_agent(tmp_path)

    result = await agent.ask("une tâche interminable", timeout_s=0.05)

    assert result["ok"] is False
    assert result["code"] == "claude_timeout"
    assert read_jsonl_tail(tmp_path / "errors.jsonl")[-1]["kind"] == "agent.ask_timeout"


async def test_a_dead_agent_unblocks_the_caller_immediately(tmp_path):
    """Sans cela un `ask` en vol attendrait le délai complet pour rien."""
    agent = _running_agent(tmp_path)
    agent._pending_result = asyncio.get_running_loop().create_future()
    agent.process.returncode = 1  # type: ignore[attr-defined]

    agent._resolve_pending({"code": "claude_exited", "error": "L'agent Claude s'est arrêté (code 1)."})
    event = await asyncio.wait_for(agent._pending_result, timeout=1)

    assert event["code"] == "claude_exited"


# --------------------------------------------------------------------------
# La passerelle HTTP utilisée par le processus Voice


async def _serve(handler) -> tuple[ClaudeGateway, web.AppRunner]:
    app = web.Application()
    app.add_routes([web.post("/api/agent/ask", handler)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    return ClaudeGateway(base_url=f"http://127.0.0.1:{port}", timeout_s=5), runner


async def test_gateway_carries_the_request_and_returns_what_to_speak():
    seen: dict = {}

    async def handler(request):
        seen.update(await request.json())
        return web.json_response({"ok": True, "text": "C'est fait.", "duration_ms": 900})

    gateway, runner = await _serve(handler)
    try:
        result = await gateway.ask("ouvre un notepad")
    finally:
        await gateway.close()
        await runner.cleanup()

    assert seen["text"] == "ouvre un notepad"
    assert result == {"ok": True, "spoken": "C'est fait.", "duration_ms": 900, "permission_denials": []}


async def test_gateway_turns_an_agent_failure_into_something_speakable():
    async def handler(request):
        del request
        return web.json_response({"ok": False, "error": "Claude n'a pas répondu.", "code": "claude_timeout"})

    gateway, runner = await _serve(handler)
    try:
        result = await gateway.ask("une tâche")
    finally:
        await gateway.close()
        await runner.cleanup()

    assert result["ok"] is False
    assert result["code"] == "claude_timeout"
    assert result["spoken"] == "Claude n'a pas répondu."


async def test_gateway_survives_an_unreachable_control_center():
    gateway = ClaudeGateway(base_url="http://127.0.0.1:1", timeout_s=2)
    try:
        result = await gateway.ask("ouvre un notepad")
    finally:
        await gateway.close()

    assert result["ok"] is False
    assert result["code"] == "claude_unreachable"
    assert "pas joignable" in result["spoken"]


async def test_gateway_refuses_an_empty_request_without_a_round_trip():
    gateway = ClaudeGateway(base_url="http://127.0.0.1:1")
    try:
        assert (await gateway.ask("   "))["code"] == "empty_request"
    finally:
        await gateway.close()


# --------------------------------------------------------------------------
# Le bridge : claude_task est intercepté avant Core


class RecordingClaude:
    def __init__(self, answer: dict) -> None:
        self.answer = answer
        self.asked: list[str] = []

    async def ask(self, request: str) -> dict:
        self.asked.append(request)
        return self.answer


class RecordingCore:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call_tool(self, name, arguments, *, conversation_id):  # noqa: ANN001
        self.calls.append(name)
        return {"disposition": "execute", "executed": True}

    async def append_turn(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return {}


class ToolCallSession:
    """Session Realtime minimale qui émet un seul appel d'outil."""

    def __init__(self, name: str, arguments: dict) -> None:
        self.name = name
        self.arguments = arguments
        self.results: list[tuple[str, dict]] = []

    async def events(self):
        yield ProtocolEnvelope(
            message_type="realtime.tool_call",
            payload={"call_id": "call_1", "name": self.name, "arguments": self.arguments},
        )

    async def send_tool_result(self, call_id: str, result: dict) -> None:
        self.results.append((call_id, result))

    async def send_audio(self, raw: bytes) -> None:
        return None


class SilentAudio:
    input_device = output_device = None
    sample_rate = 24000
    captured_bytes = sent_bytes = 0

    async def start(self) -> None:
        return None

    async def pump_input(self, session) -> None:  # noqa: ANN001
        await asyncio.Event().wait()

    async def close(self) -> None:
        return None


async def _run_bridge(tool_name: str, arguments: dict, claude, core) -> ToolCallSession:  # noqa: ANN001
    session = ToolCallSession(tool_name, arguments)
    bridge = RealtimeConversationBridge(
        core=core,
        session=session,
        conversation_id="conv-1",
        audio=SilentAudio(),
        on_addressed=lambda: None,
        on_mute=lambda: None,
        claude=claude,
    )
    await bridge.run()
    return session


async def test_claude_task_is_routed_to_claude_and_never_to_core():
    claude = RecordingClaude({"ok": True, "spoken": "Notepad ouvert."})
    core = RecordingCore()

    session = await _run_bridge(CLAUDE_TOOL, {"request": "ouvre un notepad"}, claude, core)

    assert claude.asked == ["ouvre un notepad"]
    assert core.calls == []
    assert session.results[0][1] == {"ok": True, "spoken": "Notepad ouvert."}


async def test_other_tools_still_go_to_core():
    claude = RecordingClaude({"ok": True, "spoken": "x"})
    core = RecordingCore()

    await _run_bridge("reminder_create", {"message": "m", "due_at": "d"}, claude, core)

    assert core.calls == ["reminder_create"]
    assert claude.asked == []


async def test_a_missing_gateway_answers_something_speakable():
    session = await _run_bridge(CLAUDE_TOOL, {"request": "ouvre un notepad"}, None, RecordingCore())

    result = session.results[0][1]
    assert result["ok"] is False
    assert result["code"] == "claude_not_configured"
    assert "n'est pas configuré" in result["spoken"]


# --------------------------------------------------------------------------
# L'endpoint que consomme la passerelle


@pytest.mark.asyncio
async def test_control_center_ask_endpoint_requires_text(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)

    with pytest.raises(web.HTTPBadRequest):
        await control.agent_ask(JsonRequest({"text": "  "}))


@pytest.mark.asyncio
async def test_control_center_ask_endpoint_returns_the_agent_answer(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)

    async def fake_ask(text: str, *, timeout_s: float) -> dict:
        return {"ok": True, "text": f"réponse à {text}", "timeout_s": timeout_s}

    control.agent.ask = fake_ask  # type: ignore[assignment]
    response = await control.agent_ask(JsonRequest({"text": "salut", "timeout_s": 4000}))

    payload = json.loads(response.text)
    assert payload["text"] == "réponse à salut"
    # Le délai est borné pour qu'un appelant ne puisse pas figer un tour vocal.
    assert payload["timeout_s"] == 1800.0


class JsonRequest:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def json(self) -> object:
        return self.payload


# --------------------------------------------------------------------------
# Autorisations : sans elles, l'agent ne peut rien faire en vocal


def test_permissions_default_to_fully_allowed(tmp_path):
    """En vocal personne ne peut approuver : demander une autorisation revient
    à refuser l'action. Le défaut doit donc être « tout autorisé »."""
    from jarvis.runtime.claude_local import DEFAULT_PERMISSION_MODE, ClaudeLocalAgent

    assert DEFAULT_PERMISSION_MODE == "bypassPermissions"
    assert ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path).permission_mode == "bypassPermissions"


def test_an_unknown_permission_mode_falls_back_instead_of_crashing(tmp_path):
    from jarvis.runtime.claude_local import ClaudeLocalAgent, normalize_permission_mode

    assert normalize_permission_mode("nimporte quoi") == "bypassPermissions"
    assert normalize_permission_mode("acceptEdits") == "acceptEdits"
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path, permission_mode="plan")
    assert agent.permission_mode == "plan"


@pytest.mark.asyncio
async def test_settings_expose_and_validate_the_permission_mode(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)

    exposed = json.loads((await control.get_settings(None)).text)
    assert exposed["claude_permission_mode"] == "bypassPermissions"
    assert "acceptEdits" in exposed["claude_permission_modes"]

    saved = json.loads((await control.save_settings(JsonRequest({"claude_permission_mode": "acceptEdits"}))).text)
    assert saved["claude_permission_mode"] == "acceptEdits"
    assert control.agent.permission_mode == "acceptEdits"

    with pytest.raises(web.HTTPBadRequest):
        await control.save_settings(JsonRequest({"claude_permission_mode": "yolo"}))


def test_settings_panel_offers_the_permission_mode():
    html = (Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center.html").read_text(encoding="utf-8")

    assert 'name="claude_permission_mode"' in html
    assert "Tout autoriser (aucune demande)" in html


# --------------------------------------------------------------------------
# Ce qui a réellement cassé le 8 septembre à 13:13


async def test_stopping_the_agent_unblocks_a_waiting_voice_turn(tmp_path):
    """L'incident : ouvrir la console pendant une tâche vocale tuait l'agent, et
    le tour vocal attendait 180 s un résultat devenu impossible. `stop()` annule
    la tâche de lecture, donc le déblocage de fin de flux ne s'exécutait jamais."""
    from jarvis.runtime.claude_local import ClaudeLocalAgent

    agent = _running_agent(tmp_path)
    waiting = asyncio.get_running_loop().create_task(agent.ask("une longue tâche", timeout_s=30))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    await ClaudeLocalAgent.stop(agent)
    result = await asyncio.wait_for(waiting, timeout=5)

    assert result["ok"] is False
    assert result["code"] == "claude_stopped"
    assert "arrêté avant de répondre" in result["error"]


async def test_opening_the_console_says_it_interrupts_the_running_task(tmp_path, monkeypatch):
    from jarvis.runtime import claude_local

    agent = _running_agent(tmp_path)
    monkeypatch.setattr(claude_local.os, "name", "nt")
    monkeypatch.setattr(claude_local.subprocess, "Popen", lambda command, **kw: _FakeConsole())
    monkeypatch.setattr(claude_local, "raise_console_window", lambda pid: True)

    waiting = asyncio.get_running_loop().create_task(agent.ask("une longue tâche", timeout_s=30))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await agent.open_console()
    result = await asyncio.wait_for(waiting, timeout=5)

    assert result["code"] == "claude_handover"
    kinds = [e["kind"] for e in read_jsonl_tail(tmp_path / "trace.jsonl")]
    assert "agent.console_interrupt" in kinds
    warning = next(e for e in read_jsonl_tail(tmp_path / "trace.jsonl") if e["kind"] == "agent.console_interrupt")
    assert warning["level"] == "warning"


async def test_a_late_result_is_not_handed_to_the_next_question(tmp_path):
    """Après un délai dépassé, le `result` en retard ne doit pas devenir la
    réponse de la question suivante."""
    agent = _running_agent(tmp_path)

    first = await agent.ask("question abandonnée", timeout_s=0.05)
    assert first["code"] == "claude_timeout"

    # Le résultat tardif du premier tour arrive maintenant.
    agent._resolve_pending({"type": "result", "subtype": "success", "result": "réponse en retard"})

    async def answer_second() -> None:
        await asyncio.sleep(0)
        agent._resolve_pending({"type": "result", "subtype": "success", "result": "la bonne réponse"})

    asyncio.get_running_loop().create_task(answer_second())
    second = await agent.ask("nouvelle question", timeout_s=5)

    assert second["text"] == "la bonne réponse"


class _FakeConsole:
    pid = 999

    def poll(self):
        return None

    def terminate(self) -> None:
        return None

    def wait(self) -> int:
        return 0


async def test_a_long_claude_task_is_not_mistaken_for_inactivity():
    """L'incident : le délai d'activité utile (90 s) coupait la session vocale
    pendant qu'une tâche Claude tournait, et le résultat n'avait plus où revenir."""
    from jarvis.runtime.realtime_audio import RealtimeConversationBridge

    activity: list[int] = []
    released = asyncio.Event()

    class SlowClaude:
        async def ask(self, request: str) -> dict:
            del request
            await released.wait()
            return {"ok": True, "spoken": "terminé"}

    session = ToolCallSession(CLAUDE_TOOL, {"request": "une tâche longue"})
    bridge = RealtimeConversationBridge(
        core=RecordingCore(),
        session=session,
        conversation_id="conv-1",
        audio=SilentAudio(),
        on_addressed=lambda: activity.append(1),
        on_mute=lambda: None,
        claude=SlowClaude(),
    )
    bridge.CLAUDE_KEEPALIVE_S = 0.01

    running = asyncio.get_running_loop().create_task(bridge.run())
    await asyncio.sleep(0.1)
    beats_during = len(activity)
    released.set()
    await asyncio.wait_for(running, timeout=5)

    # Le compteur d'activité utile a été rafraîchi pendant l'attente.
    assert beats_during >= 3
    assert session.results[0][1]["ok"] is True


async def test_the_keepalive_stops_once_claude_has_answered():
    from jarvis.runtime.realtime_audio import RealtimeConversationBridge

    activity: list[int] = []
    session = ToolCallSession(CLAUDE_TOOL, {"request": "rapide"})
    bridge = RealtimeConversationBridge(
        core=RecordingCore(),
        session=session,
        conversation_id="conv-1",
        audio=SilentAudio(),
        on_addressed=lambda: activity.append(1),
        on_mute=lambda: None,
        claude=RecordingClaude({"ok": True, "spoken": "fait"}),
    )
    bridge.CLAUDE_KEEPALIVE_S = 0.01

    await bridge.run()
    settled = len(activity)
    await asyncio.sleep(0.08)

    assert len(activity) == settled, "le battement continue après la réponse"


async def test_a_lost_realtime_connection_ends_the_turn_instead_of_killing_voice(tmp_path):
    """L'incident du 8 septembre à 13:17:59 : la tâche venait de RÉUSSIR, puis
    le websocket Realtime — silencieux pendant 81 s — s'est fermé. L'exception
    remontait jusqu'à tuer tout le processus Voice."""
    from jarvis.runtime.journal import RuntimeJournal
    from jarvis.runtime.realtime_audio import RealtimeConversationBridge

    class DisconnectingSession(ToolCallSession):
        async def send_tool_result(self, call_id: str, result: dict) -> None:
            raise ConnectionResetError("Cannot write to closing transport")

    session = DisconnectingSession(CLAUDE_TOOL, {"request": "une tâche"})
    bridge = RealtimeConversationBridge(
        core=RecordingCore(),
        session=session,
        conversation_id="conv-1",
        audio=SilentAudio(),
        on_addressed=lambda: None,
        on_mute=lambda: None,
        claude=RecordingClaude({"ok": True, "spoken": "c'est fait"}),
        journal=RuntimeJournal(tmp_path),
    )

    await bridge.run()  # ne doit pas lever

    entry = next(e for e in read_jsonl_tail(tmp_path / "trace.jsonl") if e["kind"] == "provider.disconnected")
    assert entry["level"] == "warning"
    assert entry["data"]["code"] == "realtime_disconnected"
    # Une connexion perdue n'est pas une erreur : rien ne doit atterrir dans
    # la liste d'erreurs du Control Center.
    assert read_jsonl_tail(tmp_path / "errors.jsonl") == []


async def test_a_provider_error_is_still_raised():
    """La déconnexion devient bénigne, mais une vraie erreur du fournisseur
    doit continuer de remonter."""
    from jarvis.runtime.realtime_audio import RealtimeConversationBridge

    class ErrorSession(ToolCallSession):
        async def events(self):
            yield ProtocolEnvelope(
                message_type="realtime.error",
                payload={"error": {"code": "invalid_request", "message": "mauvaise requête"}},
            )

    bridge = RealtimeConversationBridge(
        core=RecordingCore(),
        session=ErrorSession("x", {}),
        conversation_id="conv-1",
        audio=SilentAudio(),
        on_addressed=lambda: None,
        on_mute=lambda: None,
    )

    with pytest.raises(RuntimeError, match="invalid_request"):
        await bridge.run()


async def test_the_session_is_pinged_while_claude_works():
    """Sans ping, le websocket reste muet pendant toute la tâche et se ferme."""
    from jarvis.runtime.realtime_audio import RealtimeConversationBridge

    released = asyncio.Event()

    class PingingSession(ToolCallSession):
        def __init__(self) -> None:
            super().__init__(CLAUDE_TOOL, {"request": "longue tâche"})
            self.pings = 0

        async def keepalive(self) -> None:
            self.pings += 1

    class SlowClaude:
        async def ask(self, request: str) -> dict:
            del request
            await released.wait()
            return {"ok": True, "spoken": "fini"}

    session = PingingSession()
    bridge = RealtimeConversationBridge(
        core=RecordingCore(),
        session=session,
        conversation_id="conv-1",
        audio=SilentAudio(),
        on_addressed=lambda: None,
        on_mute=lambda: None,
        claude=SlowClaude(),
    )
    bridge.CLAUDE_KEEPALIVE_S = 0.01

    running = asyncio.get_running_loop().create_task(bridge.run())
    await asyncio.sleep(0.1)
    pings_during = session.pings
    released.set()
    await asyncio.wait_for(running, timeout=5)

    assert pings_during >= 3
