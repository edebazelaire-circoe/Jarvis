"""Ce que le Control Center doit rendre visible.

Deux angles morts constatés à l'usage :

* `calendar_create` renvoyait un succès indiscernable d'un vrai rendez-vous
  alors que Core était retombé sur son agenda en mémoire, relié à rien ;
* la console de l'agent Claude local n'affichait que des blocs `stream-json`
  bruts, illisibles.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.adapters.fake_calendar import InMemoryCalendarBackend
from jarvis.core.calendar_service import CalendarService
from jarvis.core.v2_tools import CoreToolRouter
from jarvis.core.v2_services import SchedulerService
from jarvis.runtime.claude_local import ClaudeLocalAgent
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.journal import read_jsonl_tail


CONTROL_CENTER_HTML = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center.html"


class PersistentCalendarBackend(InMemoryCalendarBackend):
    name = "google"
    persistent = True


def _router(backend) -> CoreToolRouter:  # noqa: ANN001
    return CoreToolRouter(scheduler=None, calendar=CalendarService(backend), timezone="Europe/Paris")


async def test_calendar_create_says_where_the_event_actually_landed():
    """Le cas vécu : « JARVIS dit que c'est créé, mon agenda est vide »."""
    router = _router(InMemoryCalendarBackend())

    result = await router.call(
        "calendar_create",
        {"title": "Rendez-vous", "start_at": "2026-09-08T14:30:00+02:00", "end_at": "2026-09-08T15:00:00+02:00"},
        conversation_id=None,
    )

    assert result["executed"] is True
    assert result["calendar"] == {"backend": "in-memory", "persisted": False}


async def test_a_real_calendar_is_reported_as_persisted():
    router = _router(PersistentCalendarBackend())

    result = await router.call(
        "calendar_create",
        {"title": "Rendez-vous", "start_at": "2026-09-08T14:30:00+02:00", "end_at": "2026-09-08T15:00:00+02:00"},
        conversation_id=None,
    )

    assert result["calendar"] == {"backend": "google", "persisted": True}


async def test_calendar_reads_also_carry_the_storage_identity():
    router = _router(InMemoryCalendarBackend())

    result = await router.call(
        "calendar_list",
        {"start_at": "2026-09-08T00:00:00+02:00", "end_at": "2026-09-09T00:00:00+02:00"},
        conversation_id=None,
    )

    assert result["calendar"]["persisted"] is False


def test_core_start_warns_when_no_real_calendar_is_configured(tmp_path):
    from jarvis.app import _announce_calendar_backend

    class FakeCore:
        calendar = CalendarService(InMemoryCalendarBackend())

    _announce_calendar_backend(FakeCore(), tmp_path)

    entry = read_jsonl_tail(tmp_path / "trace.jsonl")[-1]
    assert entry["kind"] == "calendar.backend"
    assert entry["level"] == "warning"
    assert entry["data"]["code"] == "calendar_backend_in_memory"
    assert "JARVIS_CALENDAR_PROVIDER=google" in entry["message"]


def test_core_start_confirms_a_connected_calendar(tmp_path):
    from jarvis.app import _announce_calendar_backend

    class FakeCore:
        calendar = CalendarService(PersistentCalendarBackend())

    _announce_calendar_backend(FakeCore(), tmp_path)

    entry = read_jsonl_tail(tmp_path / "trace.jsonl")[-1]
    assert entry["level"] == "info"
    assert entry["data"] == {"backend": "google", "persisted": True}


def _agent(tmp_path: Path) -> ClaudeLocalAgent:
    return ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path)


def test_transcript_turns_stream_json_into_a_readable_transcript(tmp_path):
    agent = _agent(tmp_path)
    agent._record({"type": "system", "subtype": "init", "model": "claude-opus-5", "cwd": "C:\\Projects\\jarvis"})
    agent._record({"type": "user", "message": {"role": "user", "content": "Liste les fichiers"}})
    agent._record({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "thinking", "thinking": "Je vais lister le dossier."},
        {"type": "text", "text": "Je regarde."},
        {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
    ]}})
    agent._record({"type": "result", "subtype": "success", "result": "Terminé", "duration_ms": 1588, "total_cost_usd": 0.0806})

    console = agent.transcript()

    assert [e["role"] for e in console] == ["system", "user", "assistant", "result"]
    assert console[0]["text"] == "claude-opus-5 · C:\\Projects\\jarvis"
    assert console[1]["title"] == "Vous"
    assert console[1]["text"] == "Liste les fichiers"
    assert "[réflexion] Je vais lister le dossier." in console[2]["text"]
    assert '[outil] Bash {"command": "ls"}' in console[2]["text"]
    assert console[3]["status"] == "ok"
    assert "1588 ms" in console[3]["text"] and "$0.0806" in console[3]["text"]
    # Le JSON complet reste disponible au dépliage.
    assert console[2]["raw"]["message"]["content"][0]["type"] == "thinking"


def test_transcript_marks_failures_and_stderr(tmp_path):
    agent = _agent(tmp_path)
    agent._record({"type": "stderr", "text": "command not found"})
    agent._record({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "boom"})

    console = agent.transcript()

    assert console[0]["status"] == "bad" and console[0]["title"] == "stderr"
    assert console[1]["status"] == "bad" and console[1]["title"] == "Échec du tour"


def test_transcript_renders_a_tool_result_block(tmp_path):
    agent = _agent(tmp_path)
    agent._record({"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "content": "a.py\nb.py", "is_error": False},
    ]}})

    assert "[résultat] a.py\nb.py" in agent.transcript()[0]["text"]


def test_transcript_keeps_unknown_events_without_losing_them(tmp_path):
    agent = _agent(tmp_path)
    agent._record({"type": "stream_event", "delta": {"text": "partiel"}})

    entry = agent.transcript()[0]
    assert entry["title"] == "stream_event"
    assert entry["raw"]["delta"] == {"text": "partiel"}


@pytest.mark.asyncio
async def test_agent_transcript_endpoint_exposes_the_conversation(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    control.agent._record({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Bonjour"}]}})

    payload = json.loads((await control.agent_transcript(QueryRequest({}))).text)

    assert payload["state"] == "stopped"
    assert payload["command"] == control.agent.command
    assert [e["text"] for e in payload["events"]] == ["Bonjour"]


@pytest.mark.asyncio
async def test_agent_transcript_limit_is_clamped(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    for index in range(10):
        control.agent._record({"type": "stdout", "text": str(index)})

    payload = json.loads((await control.agent_transcript(QueryRequest({"limit": "3"}))).text)

    assert [e["text"] for e in payload["events"]] == ["7", "8", "9"]


def test_trace_entries_are_expandable_with_icon_and_status():
    html = CONTROL_CENTER_HTML.read_text(encoding="utf-8")
    assert "<details class=\"entry" in html
    assert "function iconFor(kind)" in html
    assert "function statusFor(x)" in html
    assert "class=\"dot ${statusFor(x)}\"" in html
    assert "--warn:#ffb85c" in html and ".dot.warn{background:var(--warn)}" in html


def test_agents_panel_exposes_the_real_console_and_the_transcript():
    html = CONTROL_CENTER_HTML.read_text(encoding="utf-8")
    assert "/api/agent/console/open" in html
    assert "/api/agent/console/close" in html
    assert "/api/agent/transcript" in html
    assert "Console Windows" in html
    assert "id=\"agentConsoleBtn\"" in html
    assert "← Contrôles" in html


class QueryRequest:
    def __init__(self, query: dict[str, str]) -> None:
        self.query = query
