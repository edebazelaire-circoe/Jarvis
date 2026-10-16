"""Slice 09 — parcours navigateur réel sur une pile isolée, puis analyse de la trace (agent-trace-analysis).

    PYTHONPATH=<worktree> python journey.py <dossier de sortie>

Pile : `RealStack` de `tests/integration/test_chat_end_to_end.py` (Core et Control Center de production en
sous-processus, racine de données courte sous le temp du système, ports éphémères, vrai CLI `claude`). Le
navigateur (Chrome sans tête, CDP) suit `journey.mjs`. Sortie : `journey.json` (DOM), `analysis.json`
(trace : coûts, outils, parole, fuites) et les captures. La racine de données est supprimée à la fin ; rien
n'est écrit dans le dépôt hors du dossier de sortie.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT))

from tests.integration.test_chat_end_to_end import (  # noqa: E402
    PDF_SECRET, PNG_TEXT, RealStack, cli_user_messages, short_root, text_pdf, text_png,
)
from jarvis.runtime.attachments_brief import BRIEF_ATTACHMENTS_HEADER  # noqa: E402
from jarvis.runtime.control_center import BRIEF_TEXT_CHANNEL  # noqa: E402


def blocks(entry: dict) -> list[dict]:
    message = (entry.get("data") or {}).get("message") or {}
    return [b for b in (message.get("content") or []) if isinstance(b, dict)]


def analyse(trace: list[dict], events: list[dict], files: dict[str, str]) -> dict:
    asks = [e for e in trace if e["kind"] == "agent.ask"]
    sessions: dict[str, float] = {}
    for ask in asks:  # `total_cost_usd` est cumulé par session du CLI : le maximum de chaque session
        data = ask.get("data") or {}
        sessions[data.get("session_id")] = max(sessions.get(data.get("session_id"), 0.0), float(data.get("cost_usd") or 0))
    tools = [(b.get("name"), {k: str(v)[:160] for k, v in (b.get("input") or {}).items() if k in (
        "file_path", "description", "subagent_type", "run_in_background", "command", "pattern", "path")})
             for e in trace if e["kind"] == "agent.event" for b in blocks(e) if b.get("type") == "tool_use"]
    briefs = [m for sid in sessions for m in cli_user_messages(sid)] if sessions else []
    chat_briefs = [b for b in briefs if "[Demande]" in b]
    encoded_events = json.dumps(events, ensure_ascii=False)
    encoded_trace = json.dumps(trace, ensure_ascii=False)
    by_type: dict[str, int] = {}
    for row in events:
        by_type[row["event"]["event_type"]] = by_type.get(row["event"]["event_type"], 0) + 1
    return {
        "cost_usd_by_session": sessions, "cost_usd_total": round(sum(sessions.values()), 4),
        "turns": [{"duration_ms": (a.get("data") or {}).get("duration_ms"), "subtype": (a.get("data") or {}).get("subtype"),
                   "denials": len((a.get("data") or {}).get("permission_denials") or [])} for a in asks],
        "tool_calls": tools,
        "briefs_with_text_channel_line": sum(BRIEF_TEXT_CHANNEL in b for b in chat_briefs),
        "briefs_total": len(chat_briefs),
        "briefs_with_attachments_block": sum(BRIEF_ATTACHMENTS_HEADER in b for b in chat_briefs),
        "event_types": by_type,
        "speech_requested": by_type.get("brain.speech.requested", 0),
        "withheld_text_channel": sum(e["kind"] == "core.brain.speech_withheld_text_channel" for e in trace),
        "notice_relayed": sum(e["kind"] == "core.brain.notice_relayed" for e in trace),
        "unsolicited_results": sum(e["kind"] == "agent.unsolicited_result" for e in trace),
        "subagent_kinds": sorted({e["kind"] for e in trace if "subagent" in e["kind"] or "subtask" in e["kind"]}),
        "turn_failed": [((e.get("data") or {}).get("code")) for e in trace if e["kind"] == "core.brain.turn_failed"],
        "errors": sorted({e["kind"] for e in trace if e.get("level") == "error"}),
        "leaks_in_events": {k: (v in encoded_events) for k, v in files.items()},
        "names_in_trace": {k: (v in encoded_trace) for k, v in files.items() if k.endswith("_name")},
        "secret_in_trace": PDF_SECRET[:24] in encoded_trace,
        "trace_unparsable_lines": None,
    }


async def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    root = short_root("jarvis-s9j-")
    inputs = root / "in"
    inputs.mkdir()
    pdf, png = inputs / "note-de-test.pdf", inputs / "etiquette-de-test.png"
    pdf.write_bytes(text_pdf(["Document de test Jarvis.", PDF_SECRET]))
    png.write_bytes(text_png(PNG_TEXT))
    report: dict = {}
    try:
        async with RealStack(root / "stack") as real:
            report["ports"] = [real.core_port, real.ui_port]
            info = {"cc": real.cc, "out": str(out), "pdf": str(pdf), "png": str(png)}
            node = await asyncio.create_subprocess_exec("node", str(HERE / "journey.mjs"), json.dumps(info))
            report["node_exit"] = await asyncio.wait_for(node.wait(), 1500)
            status, state = await real.request("GET", "/api/chat/state")
            events = await real.chat_rows(state["conversation_id"], projection=None)
            lines = (real.runtime / "trace.jsonl").read_text(encoding="utf-8", errors="replace").splitlines()
            trace = real.trace()
            report["analysis"] = analyse(trace, events, {
                "pdf_name": "note-de-test", "png_name": "etiquette-de-test", "payload_pdf": "upload.pdf",
                "payload_png": "upload.png", "artifacts_path": str(real.data / "artifacts")})
            report["analysis"]["trace_unparsable_lines"] = len(lines) - len(trace)
        report["feedback_removed"] = real.feedback_removed
    finally:
        shutil.rmtree(root, ignore_errors=True)
        leftovers = subprocess.run(["powershell", "-NoProfile", "-c",
                                    f"(Get-CimInstance Win32_Process | Where-Object {{ $_.CommandLine -match "
                                    f"'{root.name}' -and $_.Name -ne 'powershell.exe' }}).ProcessId"], capture_output=True, text=True).stdout.split()
        report["leftover_processes"] = leftovers
        (out / "analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=1)[:6000])


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
