"""Le superviseur doit raconter la mort de ses enfants, et l'UI doit permettre
de nettoyer les erreurs traitées sans les perdre."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.supervisor_v2 as supervisor_v2
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.crash_guard import crash_log_path
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail


CONTROL_CENTER_HTML = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center.html"


class FakeProcess:
    def __init__(self, returncode: int | None, pid: int = 4242) -> None:
        self.returncode = returncode
        self.pid = pid
        self.stderr = None


def _supervisor(tmp_path: Path) -> supervisor_v2.Supervisor:
    return supervisor_v2.Supervisor(journal=RuntimeJournal(tmp_path), runtime_root=tmp_path)


def test_supervisor_captures_child_stderr_rather_than_losing_it_to_the_console():
    source = (Path(supervisor_v2.__file__)).read_text(encoding="utf-8")
    assert "stderr=asyncio.subprocess.PIPE" in source
    assert "_pump_stderr" in source


async def test_supervisor_journals_a_native_crash_with_diagnosis(tmp_path):
    """La panne observée : le rôle voice meurt sur 0xC0000005, sans un mot."""
    supervisor = _supervisor(tmp_path)
    supervisor.children["voice"] = FakeProcess(-1073741819)
    supervisor._tails["voice"] = supervisor_v2.deque(["Traceback (most recent call last):", "  sd.RawInputStream(...)"])
    crash_log_path(tmp_path, "voice").write_text("Windows fatal exception: access violation\n", encoding="utf-8")

    report = await supervisor._exit_report("voice")
    supervisor._journal_exit("voice", report)

    errors = read_jsonl_tail(supervisor.journal.error_path)
    assert len(errors) == 1
    entry = errors[-1]
    assert entry["kind"] == "supervisor.child_failed"
    assert entry["data"]["code"] == "supervisor_child_crash"
    assert entry["data"]["ntstatus"] == "0xC0000005"
    assert entry["data"]["role"] == "voice"
    assert "access violation" in entry["data"]["traceback"]
    assert "RawInputStream" in entry["data"]["stderr"]
    assert "ACCESS_VIOLATION" in entry["message"]


async def test_supervisor_does_not_flag_a_clean_child_exit(tmp_path):
    supervisor = _supervisor(tmp_path)
    supervisor.children["ui"] = FakeProcess(0)

    supervisor._journal_exit("ui", await supervisor._exit_report("ui"))

    assert read_jsonl_tail(supervisor.journal.error_path) == []
    assert read_jsonl_tail(supervisor.journal.trace_path)[-1]["kind"] == "supervisor.child_exit"


async def test_supervisor_stops_restarting_a_crash_loop_and_says_so(tmp_path):
    supervisor = _supervisor(tmp_path)

    allowed = [supervisor._may_restart("voice") for _ in range(supervisor_v2.MAX_RESTARTS_PER_WINDOW + 1)]

    assert allowed[:-1] == [True] * supervisor_v2.MAX_RESTARTS_PER_WINDOW
    assert allowed[-1] is False
    errors = read_jsonl_tail(supervisor.journal.error_path)
    assert errors[-1]["kind"] == "supervisor.giveup"
    assert errors[-1]["data"]["code"] == "supervisor_restart_budget_exhausted"


def test_archiving_moves_errors_out_of_the_active_list(tmp_path):
    journal = RuntimeJournal(tmp_path)
    journal.emit("voice.failure", "boom", level="error", data={"code": "bad"})
    journal.emit("voice.start", "started")

    assert journal.archive_errors() == 1

    assert read_jsonl_tail(journal.error_path) == []
    archived = read_jsonl_tail(journal.archive_path)
    assert [item["kind"] for item in archived] == ["voice.failure"]
    assert archived[0]["archived_at"]
    # La trace reste intacte : archiver nettoie le badge, pas l'historique.
    assert [item["kind"] for item in read_jsonl_tail(journal.trace_path)] == ["voice.failure", "voice.start"]


def test_archiving_accumulates_and_is_safe_when_empty(tmp_path):
    journal = RuntimeJournal(tmp_path)
    journal.emit("first.error", "one", level="error")
    journal.archive_errors()
    journal.emit("second.error", "two", level="error")
    journal.archive_errors()

    assert journal.archive_errors() == 0
    assert [item["kind"] for item in read_jsonl_tail(journal.archive_path)] == ["first.error", "second.error"]


@pytest.mark.asyncio
async def test_control_center_archives_errors_and_clears_the_badge(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    control.journal.emit("voice.failure", "boom", level="error")

    assert json.loads((await control.status(None)).text)["error_count"] == 1

    response = await control.archive_errors(None)

    assert json.loads(response.text) == {"ok": True, "archived": 1}
    assert json.loads((await control.status(None)).text)["error_count"] == 0


@pytest.mark.asyncio
async def test_control_center_serves_archived_errors_on_demand(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    control.journal.emit("voice.failure", "boom", level="error")
    await control.archive_errors(None)
    control.journal.emit("provider.error", "fresh", level="error")

    active = json.loads((await control.errors(QueryRequest({}))).text)
    archived = json.loads((await control.errors(QueryRequest({"archived": "1"}))).text)

    assert [item["message"] for item in active] == ["fresh"]
    assert [item["message"] for item in archived] == ["boom"]


def test_control_center_exposes_archive_controls():
    html = CONTROL_CENTER_HTML.read_text(encoding="utf-8")
    assert "/api/errors/archive" in html
    assert "id=\"archiveErrors\"" in html
    assert "id=\"toggleErrors\"" in html
    assert "Erreurs archivées" in html
    assert "?archived=1" in html


class QueryRequest:
    def __init__(self, query: dict[str, str]) -> None:
        self.query = query
