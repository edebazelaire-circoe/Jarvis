"""The committed folder of the handoff jarvis-remotion-master-project-studio-export keeps no local identity (Slice 09).

Real agent traces (Slice 07 run `t1`, Slice 09 run `trace-t2`), real-runtime summaries and screenshots notes are committed. The sweep is the
repository's `tests/replay/evidence_privacy.py`: its targets are DERIVED AT RUNTIME (home folder in every spelling, OS user names, this
checkout's path, the temp root, secret-looking environment values) plus shapes (provider keys, bearer tokens, the Claude CLI `init` event,
a Claude session id in a `session_id` / `sessionId` field). Nothing identifying is written in this module.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from tests.replay import evidence_privacy as privacy

TASK = Path(__file__).resolve().parents[2] / "tasks" / "jarvis-remotion-master-project-studio-export"
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
ALLOWED_EMAILS = {"noreply@anthropic.com"}

pytestmark = pytest.mark.skipif(not TASK.is_dir(), reason="handoff folder archived elsewhere")


def test_no_committed_text_file_of_the_task_keeps_a_local_identity_a_secret_or_a_session_id():
    assert any(TASK.rglob("*.jsonl")), "the real traces are part of the swept folder"
    assert privacy.sweep(TASK) == []


def test_no_committed_text_file_of_the_task_keeps_an_email_address():
    found = {}
    for path in sorted(TASK.rglob("*")):
        if path.is_file() and path.suffix.lower() in privacy.TEXT_SUFFIXES:
            emails = {m for m in EMAIL.findall(path.read_text("utf-8", errors="ignore")) if m.lower() not in ALLOWED_EMAILS}
            if emails:
                found[str(path.relative_to(TASK))] = len(emails)
    assert found == {}


def test_the_redaction_replaces_a_session_id_everywhere_and_keeps_each_json_line_valid(tmp_path):
    session = "8f0e2b1c-1234-4abc-9def-0123456789ab"
    lines = [{"type": "assistant", "sessionId": session, "cwd": str(privacy.REPO)},
             {"kind": "brain.result", "session_id": session, "transcript": f"projects/x/{session}.jsonl"},
             {"tool": "Read", "input": json.dumps({"file_path": str(privacy.REPO / "docs" / "OPERATIONS.md")})}]
    trace = tmp_path / "trace.jsonl"
    trace.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    kinds = {finding.split(": ", 1)[1] for finding in privacy.sweep(tmp_path)}
    assert {"repo", "shape claude_session_id"} <= kinds
    assert privacy.redact_in_place(tmp_path) == 1
    assert privacy.sweep(tmp_path) == []
    text = trace.read_text(encoding="utf-8")
    assert session not in text and text.count(privacy.SESSION_PLACEHOLDER) == 3
    assert [json.loads(line)["sessionId" if n == 0 else "session_id"] for n, line in enumerate(text.splitlines()[:2])] == \
        [privacy.SESSION_PLACEHOLDER] * 2
    assert "<repo>" in json.loads(text.splitlines()[2])["input"], "a path nested in a JSON string is redacted too"
