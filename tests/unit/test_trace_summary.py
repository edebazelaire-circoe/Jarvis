"""Tâche 14 : résumé Solo Owner d'une trace, pour la recette matérielle.

Déterministe et hors ligne : une trace fabriquée ici, jamais un vrai journal.
Le test tient aussi la promesse de confidentialité du résumé — aucun texte de
transcription, aucune empreinte, même si la trace en contient.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import sys

import pytest

from jarvis.runtime import trace_summary
from jarvis.runtime.trace_summary import main, percentile, render, summarize


def entry(kind: str, *, ts: str = "2026-09-12T10:00:00+00:00", **data: object) -> str:
    return json.dumps({"ts": ts, "kind": kind, "level": "info", "message": "m", "data": data}, ensure_ascii=False)


TRACE = [
    entry("voice.owner.candidate", far_end=True),
    entry("voice.owner.confirmed", confirm_ms=1600, owner_score=0.82, evidence_ms=1500),
    entry("voice.owner.confirmed", confirm_ms=2000, owner_score=0.74, evidence_ms=1500, verdict="candidate_end"),
    entry("voice.owner.confirmed", confirm_ms=2400, owner_score=0.91, evidence_ms=1500),
    entry("voice.owner.rejected", reason="non_owner", episode_ms=3200, best_score=0.31),
    entry("voice.owner.rejected", reason="short_not_owner", episode_ms=700, best_score=0.55),
    entry(
        "voice.barge_in.owner_confirmed",
        confirm_ms=1700,
        confirm_to_stop_ms=120,
        onset_to_stop_ms=1820,
        stop_latency_ms=8.5,
        owner_score=0.88,
        provider_speech_started=False,
    ),
    entry(
        "voice.barge_in.owner_confirmed",
        confirm_ms=2100,
        confirm_to_stop_ms=140,
        onset_to_stop_ms=2240,
        stop_latency_ms=11.0,
        owner_score=0.79,
        provider_speech_started=True,
        provider_lead_ms=-300,
    ),
    entry("voice.barge_in.provider_advisory", relation="after_owner_stop", lag_ms=420, replay_ms=1800),
    entry("voice.owner.replay", replay_ms=1650, clamped_ms=0, already_sent_ms=0, buffer_ms=2500),
    entry("voice.owner.replay", replay_ms=2500, clamped_ms=350, already_sent_ms=0, buffer_ms=2500),
    entry("voice.input.non_owner_dropped", source="capture", reason="non_owner", candidate_ms=2600, best_score=0.42),
    entry("voice.input.non_owner_dropped", source="capture", reason="short_not_owner", candidate_ms=800),
    entry("voice.input.non_owner_dropped", source="provider", reason="transcript_unverified", code="x"),
    entry("voice.owner.unavailable", code="verifier_not_ready"),
    entry("voice.authorization_refused", phase="activation", code="solo_owner_unavailable"),
    entry("core.brain.work_context", store_id="store-1", revision=12, listed=3),
    entry("core.brain.work_context", store_id="store-1", revision=18, listed=4),
    entry("core.work.attention", source="claude", status="failed"),
    entry("core.work.updated", revision=18),
    entry("voice.transcript", text="ceci ne doit jamais ressortir du résumé"),
    "   ",
    "{ligne tronquée",
]


def test_the_summary_counts_events_and_reports_latencies():
    summary = summarize(TRACE)

    owner = summary["owner"]
    assert (owner["candidates"], owner["confirmed"], owner["rejected"]) == (1, 3, 2)
    assert owner["reject_reasons"] == {"non_owner": 1, "short_not_owner": 1}
    assert owner["confirm_ms"] == {"count": 3, "p50": 2000.0, "p95": 2360.0, "max": 2400.0}
    assert owner["unavailable_codes"] == {"verifier_not_ready": 1}
    barge = summary["barge_in"]
    assert (barge["owner_cuts"], barge["with_provider_speech"]) == (2, 1)
    assert barge["onset_to_stop_ms"]["p50"] == 2030.0 and barge["stop_latency_ms"]["max"] == 11.0
    assert barge["provider_lag_ms"]["count"] == 1
    replay = summary["replay"]
    assert (replay["count"], replay["clamped"]) == (2, 1) and replay["clamped_ms"]["max"] == 350.0
    assert summary["input_gate"]["dropped"] == {
        "capture/non_owner": 1,
        "capture/short_not_owner": 1,
        "provider/transcript_unverified": 1,
    }
    assert summary["input_gate"]["refusals"] == {"activation/solo_owner_unavailable": 1}
    work = summary["work_state"]
    assert work["store_ids"] == ["store-1"] and work["revision"]["max"] == 18.0
    assert (work["attention"], work["updates"], work["brain_contexts"]) == (1, 1, 2)
    assert summary["window"]["unreadable_lines"] == 1
    assert summary["events"]["voice.owner.confirmed"] == 3


def test_no_transcript_or_unknown_payload_reaches_the_summary():
    summary = summarize(TRACE)

    text = json.dumps(summary, ensure_ascii=False)
    assert "ceci ne doit jamais" not in text
    # Le compteur d'évènements cite les noms d'évènements, jamais leur contenu.
    assert "best_score" not in text and "far_end" not in text and "verdict" not in text
    assert render(summary).count("ceci") == 0


def test_the_window_can_be_narrowed_and_an_empty_trace_is_not_an_error():
    late = summarize(TRACE + [entry("voice.owner.confirmed", ts="2026-09-13T08:00:00+00:00", confirm_ms=900)],
                     since="2026-09-13")

    assert late["owner"]["confirmed"] == 1 and late["owner"]["confirm_ms"]["max"] == 900.0
    empty = summarize([])
    assert empty["owner"]["confirmed"] == 0 and empty["owner"]["confirm_ms"]["count"] == 0
    assert "—" in render(empty)


def test_percentiles_match_the_benchmark_definition():
    assert percentile([], 50) is None
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.5
    assert percentile([1.0, 2.0, 3.0, 4.0], 95) == pytest.approx(3.85)


def test_the_command_line_reads_a_file_and_reports_a_missing_one(tmp_path, capsys):
    path = tmp_path / "trace.jsonl"
    path.write_text("\n".join(TRACE), encoding="utf-8")

    assert main([str(path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["owner"]["confirmed"] == 3

    assert main([str(path)]) == 0
    assert "Barge-in" in capsys.readouterr().out

    assert main([str(tmp_path / "absent.jsonl")]) == 2
    assert "trace_unreadable" in capsys.readouterr().err


def test_free_text_fields_are_clamped_to_short_identifiers():
    """Le résumé promet des scalaires : il les impose, il ne fait pas confiance à l'émetteur."""

    trace = [
        entry("voice.owner.rejected", reason="L'utilisateur a dit « bonjour JARVIS » puis s'est tu pendant 4 s"),
        entry("voice.owner.unavailable", code="X" * 200),
        entry("voice.authorization_refused", phase="session", code="a b c/d"),
        entry("voice.input.non_owner_dropped", source="capture", reason="NON_OWNER"),
        entry("core.brain.work_context", store_id="Store Un « privé »", revision=1),
    ]

    summary = summarize(trace)

    assert summary["owner"]["reject_reasons"] == {"lutilisateuraditbonjourjarvispuissesttupendant4s": 1}
    assert list(summary["owner"]["unavailable_codes"]) == ["x" * 64]
    assert summary["input_gate"]["refusals"] == {"session/abc/d": 1}
    assert summary["input_gate"]["dropped"] == {"capture/non_owner": 1}
    assert summary["work_state"]["store_ids"] == ["storeunpriv"]
    text = json.dumps(summary, ensure_ascii=False)
    assert "bonjour JARVIS" not in text and " " not in "".join(summary["owner"]["reject_reasons"])


def test_the_summary_prints_on_a_console_that_cannot_encode_its_arrows(tmp_path, monkeypatch):
    """git-bash / cmd.exe en cp1252 : « → · — » ne doit pas tuer l'outil après une recette."""

    path = tmp_path / "trace.jsonl"
    path.write_text("\n".join(TRACE), encoding="utf-8")
    console = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict", newline="")
    monkeypatch.setattr(sys, "stdout", console)

    assert main([str(path)]) == 0

    console.flush()
    assert b"Barge-in" in console.buffer.getvalue()


def test_the_script_entry_point_exists():
    script = Path(trace_summary.__file__).resolve().parents[2] / "scripts" / "summarize_voice_trace.py"
    assert script.is_file() and "trace_summary" in script.read_text(encoding="utf-8")
