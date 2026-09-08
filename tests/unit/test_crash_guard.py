"""Un crash natif ou une exception orpheline doit laisser une trace exploitable.

Ces cas sont exactement ceux qu'un `try/except` applicatif ne peut pas voir :
la couverture porte donc sur le décodage du code de sortie, la réinjection du
dump laissé par un processus mort, et la journalisation des exceptions qui
n'atteignaient jusqu'ici que la console.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
import sys

import pytest

from jarvis.runtime.crash_guard import (
    crash_log_path,
    describe_exit_code,
    install_asyncio_crash_guard,
    install_crash_guard,
    report_fatal,
    report_previous_crash,
    take_crash_log,
)
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail


ROOT = Path(__file__).resolve().parents[2]


def test_access_violation_exit_code_is_decoded():
    """-1073741819 est le code remonté par Windows pour 0xC0000005."""
    detail = describe_exit_code(-1073741819)

    assert detail["ntstatus"] == "0xC0000005"
    assert detail["native_crash"] is True
    assert detail["fatal"] is True
    assert "ACCESS_VIOLATION" in detail["label"]


def test_clean_and_ordinary_exit_codes_are_not_reported_as_crashes():
    assert describe_exit_code(0)["fatal"] is False
    assert describe_exit_code(None)["fatal"] is False
    ordinary = describe_exit_code(2)
    assert ordinary["fatal"] is True
    assert ordinary["native_crash"] is False


@pytest.mark.skipif(sys.platform == "win32", reason="signals are POSIX-only")
def test_posix_fatal_signal_is_decoded():
    detail = describe_exit_code(-11)

    assert detail["signal"] == "SIGSEGV"
    assert detail["native_crash"] is True


def test_crash_dump_is_taken_once_and_archived(tmp_path):
    crash_log_path(tmp_path, "voice").write_text("Windows fatal exception: access violation\n", encoding="utf-8")

    first = take_crash_log(tmp_path, "voice")
    second = take_crash_log(tmp_path, "voice")

    assert first is not None and "access violation" in first
    # Un même crash ne doit pas être journalisé deux fois quand le superviseur
    # et le processus relancé le voient tous les deux.
    assert second is None
    assert list((tmp_path / "crashes").glob("voice-*.log"))


def test_previous_crash_reaches_the_error_journal(tmp_path):
    journal = RuntimeJournal(tmp_path)
    crash_log_path(tmp_path, "voice").write_text(
        "Windows fatal exception: access violation\n\nCurrent thread 0x1 (most recent call first):\n  File \"sd.py\", line 1 in start\n",
        encoding="utf-8",
    )

    assert report_previous_crash(journal, tmp_path, "voice") is True

    errors = read_jsonl_tail(journal.error_path)
    assert errors[-1]["kind"] == "process.crashed"
    assert errors[-1]["data"]["code"] == "process_native_crash"
    assert "access violation" in errors[-1]["data"]["traceback"]


def test_previous_crash_is_silent_without_a_dump(tmp_path):
    journal = RuntimeJournal(tmp_path)

    assert report_previous_crash(journal, tmp_path, "voice") is False
    assert read_jsonl_tail(journal.error_path) == []


def test_install_crash_guard_arms_faulthandler_and_routes_uncaught_exceptions(tmp_path):
    import faulthandler

    journal = install_crash_guard(runtime_root=tmp_path, role="voice")
    try:
        assert faulthandler.is_enabled()
        assert crash_log_path(tmp_path, "voice").exists()
        assert read_jsonl_tail(journal.trace_path)[-1]["kind"] == "process.start"

        report_fatal(RuntimeError("boom"), context={"source": "test"})
    finally:
        faulthandler.disable()

    errors = read_jsonl_tail(journal.error_path)
    assert errors[-1]["kind"] == "process.failed"
    assert errors[-1]["message"] == "RuntimeError: boom"
    assert errors[-1]["data"]["role"] == "voice"
    assert errors[-1]["data"]["source"] == "test"


def test_asyncio_guard_journals_orphan_task_failures(tmp_path):
    import faulthandler

    async def scenario() -> None:
        install_crash_guard(runtime_root=tmp_path, role="voice")
        install_asyncio_crash_guard(asyncio.get_running_loop())
        asyncio.get_running_loop().call_exception_handler(
            {"message": "Task exception was never retrieved", "exception": ValueError("orpheline")}
        )

    try:
        asyncio.run(scenario())
    finally:
        faulthandler.disable()

    errors = read_jsonl_tail(RuntimeJournal(tmp_path).error_path)
    assert errors[-1]["kind"] == "process.failed"
    assert errors[-1]["data"]["source"] == "asyncio"


def test_long_running_roles_arm_the_crash_capture():
    """Chaque rôle supervisé doit armer la capture : c'est ce qui manquait."""
    from jarvis.app import _SUPERVISED_ROLES

    assert _SUPERVISED_ROLES["voice"] == "voice"
    assert _SUPERVISED_ROLES["core"] == "core"
    # Le rôle "ui" doit porter le même nom côté superviseur pour que le dump de
    # crash et l'entrée de journal se rejoignent.
    assert _SUPERVISED_ROLES["control-center"] == "ui"

    source = (ROOT / "jarvis" / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    amain = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "_amain")
    assert any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_arm_crash_capture"
        for node in ast.walk(amain)
    )


def test_the_same_exception_is_not_journaled_twice(tmp_path):
    """Une exception remontant de `main()` repasse par sys.excepthook : sans
    garde, chaque panne apparaissait deux fois dans la liste d'erreurs."""
    import faulthandler

    journal = install_crash_guard(runtime_root=tmp_path, role="voice")
    try:
        boom = ConnectionResetError("Cannot write to closing transport")
        report_fatal(boom, context={"source": "cli"})
        report_fatal(boom, context={"source": "sys.excepthook"})
        report_fatal(ConnectionResetError("une autre panne"))
    finally:
        faulthandler.disable()

    errors = read_jsonl_tail(journal.error_path)
    assert [e["message"] for e in errors] == [
        "ConnectionResetError: Cannot write to closing transport",
        "ConnectionResetError: une autre panne",
    ]
