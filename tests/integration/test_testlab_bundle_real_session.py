"""Opt-in smoke: capture a DiagnosticBundle from the real local Jarvis session evidence.

Skipped unless `JARVIS_TESTLAB_REAL_SESSION=1` (repository opt-in convention). It
reads the live `runtime/trace.jsonl` (bounded) and the Core state database
**strictly read-only** (`StateDatabaseEventSource`: sqlite `mode=ro` URI and
`PRAGMA query_only`), picks the most recent conversation with speech in the
journal tail, and prints counts only (never content). The bundle is stored in a
temporary directory, never under `runtime/`.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import pytest

from jarvis.testlab.bundle import DiagnosticBundle
from jarvis.testlab.bundle_builder import SessionSelector
from jarvis.testlab.bundle_capture import StateDatabaseEventSource, capture_diagnostic_bundle
from jarvis.testlab.filesystem_bundle_store import FilesystemBundleStore
from jarvis.testlab.store import BundlePutStatus
from jarvis.testlab.validation import to_event_time

ROOT = Path(__file__).resolve().parents[2]
TRACE = ROOT / "runtime" / "trace.jsonl"
STATE_DB = ROOT / "data" / "state" / "jarvis.sqlite3"
REPORTS = ROOT / "runtime" / "benchmarks" / "voice-sessions"
TAIL_BYTES = 4 * 1024 * 1024

pytestmark = pytest.mark.skipif(os.environ.get("JARVIS_TESTLAB_REAL_SESSION") != "1" or not TRACE.is_file(),
                                reason="opt-in: set JARVIS_TESTLAB_REAL_SESSION=1 with a local runtime/trace.jsonl")


def _tail_entries() -> list[dict]:
    with open(TRACE, "rb") as handle:
        size = handle.seek(0, os.SEEK_END)
        handle.seek(max(0, size - TAIL_BYTES))
        handle.readline()
        entries = []
        for raw in handle:
            try:
                entry = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(entry, dict):
                entries.append(entry)
    return entries


def _latest_conversation(entries: list[dict]) -> str:
    for entry in reversed(entries):
        data = entry.get("data")
        if (isinstance(entry.get("kind"), str) and entry["kind"].startswith("voice.speech.")
                and isinstance(data, dict) and isinstance(data.get("conversation_id"), str)):
            return data["conversation_id"]
    pytest.skip("no conversation with speech in the journal tail")


async def test_capture_real_session_bundle(tmp_path):
    entries = _tail_entries()
    selector = SessionSelector(conversation_id=_latest_conversation(entries))
    captured_at = to_event_time(datetime.now(timezone.utc))
    store = FilesystemBundleStore(tmp_path / "testlab")
    result = await capture_diagnostic_bundle(selector, captured_at=captured_at, trace_path=TRACE,
                                             event_source=StateDatabaseEventSource(STATE_DB),
                                             reports_directory=REPORTS, store=store)
    bundle = result.bundle
    assert result.put.status is BundlePutStatus.STORED
    assert DiagnosticBundle.decode(store.get_bundle(bundle.bundle_id).encode()) == bundle

    encoded = bundle.encode().decode("utf-8")
    messages = {entry["message"] for entry in entries
                if isinstance(entry.get("message"), str) and len(entry["message"]) >= 24}
    leaked = [message for message in messages if message in encoded]
    assert not leaked, f"{len(leaked)} journal message(s) copied into the bundle"

    document = bundle.to_dict()
    coverage = document["coverage"]
    findings = Counter(item["rule_id"] for item in document["anomalies"]["findings"])
    summary = {
        "bundle_bytes": len(encoded),
        "coverage": {name: coverage[name]["status"] for name in
                     ("conversation_events", "runtime_journal", "voice_session_reports")},
        "coverage_reasons": {name: coverage[name]["reason"] for name in
                             ("conversation_events", "runtime_journal", "voice_session_reports")},
        "journal": {key: coverage["runtime_journal"][key] for key in
                    ("lines_in_window", "lines_selected", "corrupt_lines", "oversized_lines", "truncated",
                     "stopped_by")},
        "sections": {name: len(document[name]) for name in
                     ("turns", "speech", "playback", "barge_in", "provider", "latency")},
        "speech_outcomes": dict(Counter(item["outcome"] for item in document["speech"])),
        "barge_in_outcomes": dict(Counter(item["outcome"] for item in document["barge_in"])),
        "rules_evaluated": sum(row["evaluated"] for row in document["anomalies"]["rules"]),
        "findings": dict(sorted(findings.items())),
        "content_items": coverage["content"]["items"],
        "segments": coverage["segments"]["count"],
        "warnings": list(coverage["warnings"]),
        "journal_flags": {key: coverage["runtime_journal"][key] for key in ("torn_tail", "window_open")},
        "new_sections": {name: len(document[name]) for name in ("user_activity", "lifecycle", "brain", "usage")},
    }
    print("\nREAL SESSION BUNDLE SUMMARY " + json.dumps(summary, sort_keys=True))
