"""Readable transcript renderer (Slice 06): golden texts, rules, and JS collapse parity.

Contract: `docs/conversation-events.md`, "Readable transcript". The renderer is
pure (`jarvis/domain/conversation_transcript.py`); the duplicate-message collapse
must keep exactly the semantics of the timeline's `collapseMessages`
(`jarvis/runtime/control_center_timeline.js`), checked here by running the JS
module under node on the same events.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import json
import os
from pathlib import Path
import random
import shutil
import subprocess

import pytest

from jarvis.domain.conversation_events import (
    ConversationEventError, ConversationEventType as T, decode_conversation_event, encode_conversation_event,
)
from jarvis.domain.conversation_transcript import (
    DETAILED_EVENT_TYPES, PLAIN_EVENT_TYPES, TranscriptBuilder, TranscriptMode, TranscriptTooLargeError,
    format_duration_ms, render_transcript, transcript_entries,
)
from tests.fakes.conversation_events import BASE, make_event, transcript_scenario

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "conversation_events"
MODULE = ROOT / "jarvis" / "runtime" / "control_center_timeline.js"


def golden(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------ golden texts

def test_plain_transcript_matches_the_golden_text():
    assert render_transcript(transcript_scenario(), conversation_id="conv-t") == golden("transcript_plain.txt")


def test_detailed_transcript_matches_the_golden_text():
    text = render_transcript(transcript_scenario(), conversation_id="conv-t", mode=TranscriptMode.DETAILED,
                             skipped_rows=2)
    assert text == golden("transcript_detailed.txt")


def test_store_order_and_page_boundaries_never_change_the_bytes():
    events = transcript_scenario()
    reference = render_transcript(events, conversation_id="conv-t", mode=TranscriptMode.DETAILED)
    for seed in range(5):
        shuffled = events[:]
        random.Random(seed).shuffle(shuffled)
        builder = TranscriptBuilder("conv-t", mode=TranscriptMode.DETAILED)
        for index, event in enumerate(shuffled):
            builder.add(event)
            if index % 7 == 0:
                builder.note_skipped_rows(0)
        assert builder.render() == reference


def test_plain_mode_keeps_only_what_can_pair_into_public_items_and_that_changes_nothing():
    events = transcript_scenario()
    kept = [event for event in events if event.event_type in PLAIN_EVENT_TYPES]
    assert len(kept) < len(events)
    assert render_transcript(kept, conversation_id="conv-t").splitlines()[5:] == \
        render_transcript(events, conversation_id="conv-t").splitlines()[5:]
    assert T.MOUTH_SPEECH_QUEUED not in DETAILED_EVENT_TYPES and T.SUBAGENT_STARTED in DETAILED_EVENT_TYPES


# ------------------------------------------------------------------ rules

def lines(text: str) -> list[str]:
    return text.splitlines()


def test_interrupted_speech_states_only_the_heard_duration_the_events_carry():
    voice = "voice.speech_scheduler"
    ids = dict(speech_id="sp", span_id="sp", correlation_id="c")
    started = make_event(T.MOUTH_SPEECH_STARTED, "sp", producer=voice, ms=0, content="Une longue phrase.", **ids)
    with_played = make_event(T.MOUTH_SPEECH_INTERRUPTED, "sp", producer=voice, ms=3000, attributes={"played_ms": 1420},
                             **ids)
    text = render_transcript([started, with_played], conversation_id="conv-a")
    assert "Jarvis [interrompu après 1,4 s entendues] : Une longue phrase." in text
    unknown = replace(with_played, attributes={"reason": "voice_background"})
    text = render_transcript([started, unknown], conversation_id="conv-a")
    assert "Jarvis [interrompu, durée entendue inconnue] : Une longue phrase." in text


def test_reflex_and_missing_text_are_labelled_never_invented():
    voice = "voice.speech_scheduler"
    reflex = make_event(T.MOUTH_REFLEX_STARTED, "x", producer=voice, correlation_id="c", attributes={"output_id": "o"})
    started = make_event(T.MOUTH_SPEECH_STARTED, "sp", producer=voice, ms=10, speech_id="sp", span_id="sp")
    text = render_transcript([reflex, started], conversation_id="conv-a")
    assert "[10:00:00.000] Jarvis (réflexe) : (texte non enregistré)" in text
    assert "[10:00:00.010] Jarvis [en cours] : (texte non enregistré)" in text


def test_diagnostic_items_never_reach_the_plain_transcript():
    text = render_transcript(transcript_scenario(), conversation_id="conv-t")
    for private in ("Rassemble les vols", "Recherche des vols", "get_time", "brain_backend_exception",
                    "Autre annonce jamais dite", " -- "):
        assert private not in text
    detailed = render_transcript(transcript_scenario(), conversation_id="conv-t", mode=TranscriptMode.DETAILED)
    assert "-- Sous-agent « Rassemble les vols » : terminé en 1 min 34 s" in detailed


def test_anomalies_are_named_in_detailed_mode_only():
    ids = dict(speech_id="s", span_id="s", correlation_id="c")
    voice = "voice.speech_scheduler"
    opened = make_event(T.MOUTH_SPEECH_STARTED, "a", producer=voice, ms=100, content="Texte.", **ids)
    early = make_event(T.MOUTH_SPEECH_COMPLETED, "b", producer=voice, ms=50, **ids)
    plain = render_transcript([opened, early], conversation_id="conv-a")
    detailed = render_transcript([opened, early], conversation_id="conv-a", mode=TranscriptMode.DETAILED)
    assert "anomalies" not in plain
    assert "Jarvis [anomalies : close_before_open] : Texte." in detailed


def test_empty_and_unknown_conversations_render_an_explicit_empty_state():
    assert render_transcript([], conversation_id="conv-empty").endswith("\n(aucun échange public enregistré)\n")
    only_diag = [make_event(T.BRAIN_TURN_ACCEPTED, "c", conversation_id="conv-d")]
    assert render_transcript(only_diag, conversation_id="conv-d").endswith("(aucun échange public enregistré)\n")
    assert "-- Brain : tour accepté" in render_transcript(only_diag, conversation_id="conv-d",
                                                         mode=TranscriptMode.DETAILED)


def test_builder_refuses_other_conversations_and_bounds_memory():
    builder = TranscriptBuilder("conv-a", max_events=2)
    with pytest.raises(ConversationEventError):
        builder.add(make_event(T.USER_TRANSCRIPT_ACCEPTED, "x", conversation_id="conv-b"))
    with pytest.raises(ConversationEventError):
        builder.add({"event_type": "user.transcript.accepted"})  # type: ignore[arg-type]
    builder.add(make_event(T.BRAIN_TURN_ACCEPTED, "not-kept"))  # plain mode: counted, not held
    builder.add(make_event(T.USER_TRANSCRIPT_ACCEPTED, "u1"))
    builder.add(make_event(T.USER_TRANSCRIPT_ACCEPTED, "u2", ms=1))
    with pytest.raises(TranscriptTooLargeError):
        builder.add(make_event(T.USER_TRANSCRIPT_ACCEPTED, "u3", ms=2))
    assert builder.event_count == 4


@pytest.mark.parametrize(("ms", "text"), [(0, "0 ms"), (999.4, "999 ms"), (1000, "1,0 s"), (1449, "1,4 s"),
                                          (1450, "1,5 s"), (59_949, "59,9 s"), (59_950, "1 min 00 s"),
                                          (125_000, "2 min 05 s"), (3_720_000, "1 h 02 min"), (-5, "0 ms")])
def test_durations_use_one_fixed_format(ms, text):
    assert format_duration_ms(ms) == text


def test_times_are_utc_whatever_the_event_offset_was():
    event = make_event(T.USER_TRANSCRIPT_ACCEPTED, "u", content="Salut.")
    assert event.occurred_at.utcoffset() == timedelta(0)
    assert "[10:00:00.000] Utilisateur : Salut." in render_transcript([event], conversation_id="conv-a")


# ------------------------------------------------------ collapse parity with the JS

def message(source: str, ms: int, text: str, correlation: str = "corr-1"):
    return make_event(T.BRAIN_MESSAGE_PUBLISHED, source, producer="core.brain_outcomes", ms=ms, content=text,
                      correlation_id=correlation)


def collapse_cases() -> dict[str, list]:
    golden_events = [decode_conversation_event(row["event"]) for row in json.loads(
        (FIXTURES / "overlapping_conversation.json").read_text(encoding="utf-8"))["events"]]
    return {
        "scenario": transcript_scenario(),
        "golden_fixture": golden_events,
        "a_a_b_a_and_other_correlation": [
            message("m1", 0, "Les tests passent."), message("m2", 10, "Les tests passent."),
            message("m3", 20, "Autre chose."), message("m4", 30, "Les tests passent."),
            message("m5", 40, "Autre chose.", correlation="corr-2"),
            make_event(T.USER_TRANSCRIPT_ACCEPTED, "u", producer="core.voice_admission", ms=5,
                       correlation_id="corr-1"),
        ],
        "same_text_separated_by_other_items": [
            message("m1", 0, "Prêt."), make_event(T.MOUTH_SPEECH_STARTED, "s", producer="voice.speech_scheduler",
                                                  ms=5, speech_id="s", span_id="s", correlation_id="corr-1",
                                                  content="Prêt."),
            message("m2", 10, "Prêt."), message("m3", 20, "Prêt."), message("m4", 30, "prêt."),
        ],
        "equal_times_order_by_event_id": [message("z", 0, "Même."), message("a", 0, "Même."), message("m", 0, "Même.")],
    }


def run_node_collapse(tmp_path: Path, cases: dict[str, list]) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    data = tmp_path / "collapse.json"
    data.write_text(json.dumps({name: [encode_conversation_event(e) for e in events]
                                for name, events in cases.items()}), encoding="utf-8")
    script = tmp_path / "collapse.cjs"
    script.write_text(
        f"const TL=require({json.dumps(str(MODULE))});\n"
        f"const DATA=JSON.parse(require('node:fs').readFileSync({json.dumps(str(data))},'utf8'));\n"
        "const out={};for(const [name,events] of Object.entries(DATA)){\n"
        "  out[name]=TL.collapseMessages(TL.reconstruct(events)).map(i=>[i.item_id,i.collapsed.map(c=>c.item_id)]);}\n"
        "process.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
    completed = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60,
                               check=False, env={**os.environ, "TZ": "UTC"})
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_python_collapse_keeps_exactly_the_timeline_semantics(tmp_path):
    cases = collapse_cases()
    js = run_node_collapse(tmp_path, cases)
    for name, events in cases.items():
        python = [[entry.item.item_id, [item.item_id for item in entry.collapsed]] for entry in transcript_entries(events)]
        assert python == js[name], name
    # The cases really exercise the rule.
    collapsed = {name: sum(len(c) for _, c in rows) for name, rows in js.items()}
    assert collapsed["scenario"] == 1 and collapsed["a_a_b_a_and_other_correlation"] == 1
    assert collapsed["same_text_separated_by_other_items"] == 2 and collapsed["equal_times_order_by_event_id"] == 2


# ------------------------------------------------------------ Slice 06 rework

def test_a_text_budget_refuses_as_soon_as_it_is_passed():
    builder = TranscriptBuilder("conv-a", max_content_bytes=3 * 1024)
    text = "é" * 600  # 1 200 UTF-8 bytes
    builder.add(make_event(T.USER_TRANSCRIPT_ACCEPTED, "u1", content=text))
    builder.add(make_event(T.USER_TRANSCRIPT_ACCEPTED, "u2", ms=1, content=text))
    with pytest.raises(TranscriptTooLargeError, match="MiB"):
        builder.add(make_event(T.USER_TRANSCRIPT_ACCEPTED, "u3", ms=2, content=text))
    assert builder.content_bytes > 3 * 1024 and len(builder._kept) == 2
    from jarvis.domain.conversation_transcript import MAX_TRANSCRIPT_CONTENT_BYTES
    assert MAX_TRANSCRIPT_CONTENT_BYTES == 16 * 1024 * 1024
    builder = TranscriptBuilder("conv-a", max_content_bytes=64)
    builder.add(make_event(T.BRAIN_TURN_ACCEPTED, "diag", ms=3))  # plain mode does not hold it: no budget used
    assert builder.content_bytes == 0


def test_an_explicit_local_offset_shifts_times_and_days_and_is_stated():
    events = transcript_scenario()
    paris = render_transcript(events, conversation_id="conv-t", utc_offset_minutes=120)
    assert "Mode : simple · heures UTC+02:00 · 25 événements lus" in paris
    assert "[12:00:00.000] Utilisateur : Jarvis, prépare le dossier de vol de Paul." in paris
    assert "— 2026-09-17 —\n[12:00:05.000] Jarvis [en cours]" in paris
    late = make_event(T.USER_TRANSCRIPT_ACCEPTED, "late", ms=15 * 3600 * 1000, content="Tard.")  # 01:00 UTC next day
    assert "— 2026-09-16 —\n[19:30:00.000] Utilisateur : Tard." in render_transcript(
        [late], conversation_id="conv-a", utc_offset_minutes=-330)
    assert "heures UTC-05:30" in render_transcript([late], conversation_id="conv-a", utc_offset_minutes=-330)
    for bad in (15 * 60, -841, 1.5, True, "60"):
        with pytest.raises(ValueError, match="utc_offset_minutes"):
            TranscriptBuilder("conv-a", utc_offset_minutes=bad)  # type: ignore[arg-type]


def test_usage_never_reported_is_not_printed():
    events = [make_event(T.SUBAGENT_STARTED, "t", correlation_id=None, content="Cherche"),
              make_event(T.SUBAGENT_FINISHED, "t", ms=1000, correlation_id=None,
                         attributes={"status": "completed", "tokens": 0, "tool_uses": 0, "model": "claude-sonnet-5"})]
    detailed = render_transcript(events, conversation_id="conv-a", mode=TranscriptMode.DETAILED)
    assert "Sous-agent « Cherche » : terminé en 1,0 s · modèle claude-sonnet-5\n" in detailed
    [line] = [row for row in detailed.splitlines() if "Sous-agent" in row]
    assert "jetons" not in line and "outils" not in line
