"""JSONL export format and offline importer (Slice 06).

Contract: `docs/conversation-events.md`, "JSONL export". Pure functions only; the
streaming routes are covered in `tests/integration/test_conversation_event_projections_protocol.py`.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.domain.conversation_event_export import (
    EXPORT_FORMAT, ExportFormatError, encode_export_line, export_filename, export_header,
    export_trailer, read_export, reconstruct_export, transcript_from_export,
)
from jarvis.domain.conversation_event_query import encode_stored_event
from jarvis.domain.conversation_event_store import ConversationEventExtent, StoredConversationEvent
from jarvis.domain.conversation_events import encode_conversation_event, reconstruct_conversation
from jarvis.domain.conversation_transcript import TranscriptMode, render_transcript
from tests.fakes.conversation_events import BASE, make_event, transcript_scenario

ROOT = Path(__file__).resolve().parents[2]
EXPORTED_AT = datetime(2026, 9, 17, 8, 30, tzinfo=timezone.utc)


def stored_scenario() -> list[StoredConversationEvent]:
    return [StoredConversationEvent(index + 1, BASE, event) for index, event in enumerate(transcript_scenario())]


def export_lines(stored: list[StoredConversationEvent], *, skipped_rows: int = 0, trailer: bool = True) -> list[bytes]:
    extent = ConversationEventExtent(len(stored) + skipped_rows, 1, len(stored) + skipped_rows)
    lines = [encode_export_line(export_header("conv-t", exported_at=EXPORTED_AT, extent=extent))]
    lines += [encode_export_line(encode_stored_event(item)) for item in stored]
    if trailer:
        lines.append(encode_export_line(export_trailer(events=len(stored), skipped_rows=skipped_rows)))
    return lines


def test_event_lines_are_exactly_the_codec_output_with_sequence_and_recorded_at():
    stored = stored_scenario()
    lines = export_lines(stored)
    header = json.loads(lines[0])
    assert header == {"format": EXPORT_FORMAT, "export_version": 1, "schema_version": 1, "conversation_id": "conv-t",
                      "exported_at": "2026-09-17T08:30:00.000Z", "through_sequence": 25,
                      "counts": {"stored_rows": 25, "first_sequence": 1, "last_sequence": 25}}
    first = json.loads(lines[1])
    assert set(first) == {"sequence", "recorded_at", "event"}
    assert first["event"] == encode_conversation_event(stored[0].event)
    assert json.loads(lines[-1]) == {"format": EXPORT_FORMAT, "complete": True,
                                     "counts": {"events": 25, "skipped_rows": 0}}
    assert all(line.endswith(b"\n") and line.count(b"\n") == 1 for line in lines)


def test_export_reimports_to_the_same_events_reconstruction_and_transcript():
    stored = stored_scenario()
    result = read_export(export_lines(stored, skipped_rows=2))
    assert result.complete and not result.invalid_lines and result.skipped_rows == 2
    assert result.events == tuple(stored)
    assert reconstruct_export(result) == reconstruct_conversation([s.event for s in stored])
    for mode in TranscriptMode:
        assert transcript_from_export(result, mode=mode) == render_transcript(
            [s.event for s in stored], conversation_id="conv-t", mode=mode, skipped_rows=2)


def test_a_file_without_trailer_is_incomplete_but_still_readable():
    stored = stored_scenario()
    result = read_export(export_lines(stored, trailer=False))
    assert not result.complete and len(result.events) == 25 and result.skipped_rows == 0


def test_invalid_lines_are_skipped_and_reported_without_values():
    stored = stored_scenario()
    lines = export_lines(stored)
    secret = "SECRET-VALUE-42"
    forged = json.loads(lines[3])
    forged["event"]["attributes"]["prompt"] = secret  # forbidden key: codec refuses it
    other = json.loads(lines[4])
    other["event"]["conversation_id"] = "conv-other"
    doctored = [lines[0], lines[1], b'{"torn": ' + secret.encode() + b"\n", lines[2],
                (json.dumps(forged) + "\n").encode(), (json.dumps(other) + "\n").encode(), lines[2], b"\n",
                b"x" * (1024 * 1024 + 1) + b"\n", *lines[5:], b'{"after": 1}\n']
    result = read_export(doctored)
    reasons = [(error.line, error.reason) for error in result.invalid_lines]
    assert (3, "invalid_json") in reasons and (5, "invalid_event") in reasons and (6, "other_conversation") in reasons
    assert (7, "sequence_out_of_order") in reasons and (9, "oversized_line") in reasons
    assert reasons[-1][1] == "after_trailer"
    assert secret not in json.dumps([error.detail for error in result.invalid_lines])
    assert not result.complete  # counts no longer match what was read
    assert [s.sequence for s in result.events] == [1, 2] + list(range(5, 26))


@pytest.mark.parametrize("first", [b"", b"not json\n", b'{"format": "other"}\n',
                                   b'{"format": "jarvis.conversation-events.export", "export_version": 2}\n'])
def test_a_file_that_is_not_an_export_is_refused_as_a_whole(first):
    with pytest.raises(ExportFormatError):
        read_export([first] if first else [])


def test_an_empty_conversation_exports_header_and_trailer_only():
    header = export_header("conv-empty", exported_at=EXPORTED_AT, extent=None)
    assert header["through_sequence"] == 0 and header["counts"] == {"stored_rows": 0, "first_sequence": None,
                                                                    "last_sequence": None}
    result = read_export([encode_export_line(header), encode_export_line(export_trailer(events=0, skipped_rows=0))])
    assert result.complete and result.events == ()
    assert transcript_from_export(result).endswith("(aucun échange public enregistré)\n")


def test_download_names_are_safe_and_the_page_uses_the_same_rule(tmp_path):
    ids = ["conv-1", "a/b é.c", "..__..", "../../etc/passwd", "x" * 300, "C:\\Users\\éè"]
    names = [export_filename(value) for value in ids]
    assert names[0] == "conversation-conv-1.events.jsonl" and names[2] == "conversation-sans-id.events.jsonl"
    assert all("/" not in n and "\\" not in n and not n.startswith("conversation-.") for n in names)
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    module = ROOT / "jarvis" / "runtime" / "control_center_timeline.js"
    script = tmp_path / "names.cjs"
    script.write_text(f"const TL=require({json.dumps(str(module))});process.stdout.write(JSON.stringify("
                      f"{json.dumps(ids)}.map(TL.exportFilename)));", encoding="utf-8")
    completed = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60,
                               check=False, env={**os.environ})
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == names



def test_a_utf8_bom_before_the_header_is_accepted():
    lines = export_lines(stored_scenario())
    result = read_export([b"\xef\xbb\xbf" + lines[0], *lines[1:]])
    assert result.complete and len(result.events) == 25
    with pytest.raises(ExportFormatError):
        read_export([lines[1], lines[0]])  # a BOM is tolerated, a misplaced header is not


def test_offline_reproduction_takes_the_same_offset_input():
    stored = stored_scenario()
    result = read_export(export_lines(stored))
    for offset in (0, 120, -300):
        assert transcript_from_export(result, utc_offset_minutes=offset) == render_transcript(
            [s.event for s in stored], conversation_id="conv-t", utc_offset_minutes=offset)


def test_non_ascii_ids_keep_distinct_download_names():
    names = {export_filename(value) for value in ("réunion", "rèunion", "r_union", "r?union")}
    assert len(names) == 4 and export_filename("r_union") == "conversation-r_union.events.jsonl"
