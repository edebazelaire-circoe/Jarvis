"""Slice 09 (jarvis-wake-word) - l'outil de mesure de HV-WAKEWORD-MIC-01 lit un journal synthétique.

`scripts/measure_wake_word_validation.py` lit `runtime/trace.jsonl` en lecture
seule. Chaque test écrit un journal fabriqué à la main (jamais un vrai journal du
poste, jamais un micro) et vérifie un chiffre calculable de tête.
"""

from __future__ import annotations

import ast
import getpass
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "measure_wake_word_validation.py"
BASE = datetime(2026, 10, 8, 9, 0, 0, tzinfo=timezone.utc)


def load_tool():
    spec = importlib.util.spec_from_file_location("measure_wake_word_validation_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tool():
    return load_tool()


def at(seconds: float) -> str:
    return (BASE + timedelta(seconds=seconds)).isoformat()


def row(seconds: float, kind: str, level: str = "info", **data) -> dict:
    return {"ts": at(seconds), "kind": kind, "level": level, "message": "x", "data": data}


def detection(seconds: float, *, mode: str = "simple", provider: str = "openwakeword", score=0.8, threshold=0.5) -> dict:
    kind = "wake.own_stream.detected" if mode == "simple" else "wake.shared_pcm.detected"
    return row(seconds, kind, keyword="hey_jarvis", provider=provider, score=score, threshold=threshold)


def activation(seconds: float, *, source: str = "wake_word", connect: float = 0.1, active: float = 0.4,
               provider: str = "openwakeword") -> list[dict]:
    return [
        row(seconds, "voice.wake", source=source, keyword="hey_jarvis", provider=provider, state_before="background"),
        row(seconds + connect, "voice.connecting", source=source),
        row(seconds + active, "voice.active", conversation_id="c1"),
        row(seconds + active + 0.01, "voice.wake.outcome", source=source, state_before="background", state_after="active"),
    ]


def write(path: Path, rows: list[dict], *, raw_lines: list[str] | None = None) -> Path:
    lines = [json.dumps(r) for r in rows] + list(raw_lines or [])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def measure(tool, tmp_path, rows, *, raw_lines=None, since=None, until=None, **options):
    trace = write(tmp_path / "trace.jsonl", rows, raw_lines=raw_lines)
    return tool.build_report(
        trace,
        since=None if since is None else tool.parse_instant(since),
        until=None if until is None else tool.parse_instant(until),
        **options,
    )


# ------------------------------------------------------------------ latence


def test_latency_is_the_gap_between_wake_and_active(tool, tmp_path):
    rows = [detection(10.0), *activation(10.05, active=0.45, connect=0.1)]
    report = measure(tool, tmp_path, rows)
    active = report["latency_ms"]["voice_wake_to_active_by_source"]["wake_word"]
    assert active["n"] == 1 and active["median"] == 450.0
    assert report["latency_ms"]["voice_wake_to_connecting_by_source"]["wake_word"]["median"] == 100.0
    assert report["latency_ms"]["detection_to_voice_wake_by_mode"]["simple"]["median"] == 50.0


def test_median_and_p95_are_computed_over_the_series_and_p95_is_flagged_when_short(tool, tmp_path):
    rows = []
    for index in range(20):
        rows += activation(100.0 * index, active=0.2 + 0.01 * index)  # 200 .. 390 ms
    report = measure(tool, tmp_path, rows)
    stats = report["latency_ms"]["voice_wake_to_active_by_source"]["wake_word"]
    assert stats["n"] == 20 and stats["min"] == 200.0 and stats["max"] == 390.0
    assert stats["median"] == 295.0 and stats["p95"] == 380.0 and stats["p95_reliable"] is True
    short = measure(tool, tmp_path, rows[:8])
    assert short["latency_ms"]["voice_wake_to_active_by_source"]["wake_word"]["p95_reliable"] is False


def test_the_wake_word_median_is_compared_with_the_f9_median(tool, tmp_path):
    rows = [*activation(0, source="wake_word", active=0.5), *activation(100, source="manual_key", active=0.3)]
    report = measure(tool, tmp_path, rows)
    assert report["latency_ms"]["median_wake_word_minus_manual_key_to_active"] == 200.0


def test_a_wake_that_never_activates_and_a_detection_without_wake_are_counted(tool, tmp_path):
    rows = [
        row(0, "voice.wake", source="wake_word", provider="openwakeword"),
        row(5, "voice.background"),
        detection(100),  # personne ne l'a relayée
    ]
    report = measure(tool, tmp_path, rows)
    assert report["latency_ms"]["voice_wake_without_activation"] == 1
    assert report["latency_ms"]["detections_without_voice_wake"] == 1


# ------------------------------------------------------------------- comptes


def test_counts_are_split_by_source(tool, tmp_path):
    rows = [*activation(0, source="wake_word"), *activation(50, source="wake_word"), *activation(100, source="manual_key")]
    wake = measure(tool, tmp_path, rows)["detections"]["voice_wake_by_source_and_provider"]
    assert wake["wake_word"]["openwakeword"] == 2 and wake["manual_key"]["openwakeword"] == 1


def test_counts_are_split_by_mode_and_provider(tool, tmp_path):
    rows = [
        detection(1, mode="simple"), detection(2, mode="simple"),
        detection(3, mode="presentation"),
        detection(4, mode="simple", provider="porcupine", score=None, threshold=None),
    ]
    detections = measure(tool, tmp_path, rows)["detections"]
    assert detections["total"] == 4
    assert detections["by_mode_and_provider"] == {
        "simple": {"openwakeword": 2, "porcupine": 1}, "presentation": {"openwakeword": 1}}


def test_scores_and_thresholds_are_summarised_per_mode_and_provider(tool, tmp_path):
    rows = [detection(1, score=0.6, threshold=0.5), detection(2, score=0.9, threshold=0.5), detection(3, score=0.75, threshold=0.4)]
    detections = measure(tool, tmp_path, rows)["detections"]
    stats = detections["scores_by_mode_and_provider"]["simple"]["openwakeword"]
    assert stats["n"] == 3 and stats["min"] == 0.6 and stats["max"] == 0.9 and stats["median"] == 0.75
    assert detections["thresholds_by_mode_and_provider"]["simple"]["openwakeword"] == {"0.5": 2, "0.4": 1}


def test_a_nan_or_non_numeric_score_is_ignored_counted_and_never_printed_as_nan(tool, tmp_path):
    raw = [
        '{"ts": "%s", "kind": "wake.own_stream.detected", "data": {"provider": "openwakeword", "score": NaN, "threshold": 0.5}}' % at(1),
        '{"ts": "%s", "kind": "wake.own_stream.detected", "data": {"provider": "openwakeword", "score": "0.9", "threshold": true}}' % at(2),
        '{"ts": "%s", "kind": "wake.own_stream.detected", "data": {"provider": "openwakeword", "score": Infinity, "threshold": 0.5}}' % at(3),
    ]
    report = measure(tool, tmp_path, [detection(4, score=0.7)], raw_lines=raw)
    detections = report["detections"]
    assert detections["total"] == 4
    assert detections["scores_by_mode_and_provider"]["simple"]["openwakeword"]["n"] == 1
    assert detections["lines_with_invalid_score_or_threshold"] == 3
    encoded = json.dumps(report, allow_nan=False)  # lèverait sur NaN / Infinity
    assert "NaN" not in encoded and "Infinity" not in encoded


# -------------------------------------------------------------- plage et tri


def test_since_and_until_bound_the_counts_and_until_is_exclusive(tool, tmp_path):
    rows = [detection(0), detection(10), detection(20), detection(30)]
    report = measure(tool, tmp_path, rows, since=at(10), until=at(30))
    assert report["detections"]["total"] == 2


def test_events_before_since_still_serve_as_anchors_for_the_echo_hint(tool, tmp_path):
    rows = [row(5, SPEECH_END), detection(12)]
    report = measure(tool, tmp_path, rows, since=at(10), until=at(60))
    assert report["echo_hint"]["detections_within_window_after_speech_end"] == 1


SPEECH_END = "voice.speech.completed"


def test_lines_out_of_order_in_the_file_are_sorted_by_timestamp(tool, tmp_path):
    rows = [row(10.4, "voice.active"), row(10.1, "voice.connecting"), row(10.0, "voice.wake", source="wake_word", provider="openwakeword"),
            detection(9.95)]
    report = measure(tool, tmp_path, rows)
    assert report["latency_ms"]["voice_wake_to_active_by_source"]["wake_word"]["median"] == 400.0
    assert report["latency_ms"]["detection_to_voice_wake_by_mode"]["simple"]["median"] == 50.0


def test_z_suffix_naive_and_offset_timestamps_are_read_and_bad_ones_counted(tool, tmp_path):
    raw = [
        '{"ts": "2026-10-08T09:00:01Z", "kind": "wake.own_stream.detected", "data": {"provider": "openwakeword"}}',
        '{"ts": "2026-10-08T09:00:02", "kind": "wake.own_stream.detected", "data": {"provider": "openwakeword"}}',
        '{"ts": "2026-10-08T11:00:03+02:00", "kind": "wake.own_stream.detected", "data": {"provider": "openwakeword"}}',
        '{"ts": "hier", "kind": "wake.own_stream.detected", "data": {"provider": "openwakeword"}}',
        '{"kind": "wake.own_stream.detected", "data": {}}',
    ]
    report = measure(tool, tmp_path, [], raw_lines=raw)
    assert report["detections"]["total"] == 3 and report["reading"]["lines_without_timestamp"] == 2


# ------------------------------------------------------------ journaux abîmés


def test_an_empty_or_truncated_trace_is_reported_not_crashed(tool, tmp_path, capsys):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert tool.main(["--trace", str(empty)]) == 0
    assert "Détections : 0" in capsys.readouterr().out

    truncated = tmp_path / "cut.jsonl"
    truncated.write_text(json.dumps(detection(1)) + "\n" + '{"ts": "2026-10-08T09:00:02+00:00", "kind": "wake.own', encoding="utf-8")
    assert tool.main(["--trace", str(truncated), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["detections"]["total"] == 1 and report["reading"]["invalid_lines"] == 1


def test_corrupt_lines_and_non_object_rows_are_counted_and_skipped(tool, tmp_path):
    report = measure(tool, tmp_path, [detection(1)], raw_lines=["not json", "[1, 2]", "42", "null", '{"kind": 3}', "\x00\x01"])
    assert report["detections"]["total"] == 1
    assert report["reading"]["invalid_lines"] >= 4


def test_a_missing_trace_is_a_clear_exit_not_a_traceback(tool, tmp_path, capsys):
    assert tool.main(["--runtime-dir", str(tmp_path)]) == 2
    assert "introuvable" in capsys.readouterr().err


def test_an_enormous_line_is_skipped_without_loading_it_and_reading_goes_on(tool, tmp_path):
    trace = tmp_path / "trace.jsonl"
    with trace.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(detection(1)) + "\n")
        handle.write('{"ts": "x", "data": "' + "a" * (tool.MAX_LINE_BYTES * 3) + '"}\n')
        handle.write(json.dumps(detection(2)) + "\n")
    report = tool.build_report(trace, since=None, until=None)
    assert report["detections"]["total"] == 2 and report["reading"]["oversize_lines"] == 1


# --------------------------------------------------------------------- écho


def test_detections_shortly_after_the_end_of_jarvis_speech_are_an_echo_hint(tool, tmp_path):
    rows = [row(0, SPEECH_END), detection(20), detection(200), row(300, SPEECH_END), detection(310)]
    report = measure(tool, tmp_path, rows)
    echo = report["echo_hint"]
    assert echo["detections_within_window_after_speech_end"] == 2
    assert echo["seconds_after_speech_end"] == [10.0, 20.0]
    wide = measure(tool, tmp_path, rows, echo_window_s=250.0)
    assert wide["echo_hint"]["detections_within_window_after_speech_end"] == 3


def test_detections_inside_a_session_or_its_tail_are_listed_separately(tool, tmp_path):
    rows = [row(0, "voice.active"), detection(5, mode="presentation"), row(10, "voice.background"),
            detection(13, mode="presentation"), detection(16, mode="presentation")]
    echo = measure(tool, tmp_path, rows)["echo_hint"]
    assert echo["detections_during_session_or_tail"] == 2
    assert measure(tool, tmp_path, rows, tail_s=10.0)["echo_hint"]["detections_during_session_or_tail"] == 3


# ---------------------------------------------------------- faux positifs/h


def test_detections_outside_the_test_window_are_false_positive_candidates(tool, tmp_path):
    rows = [detection(100), detection(200), detection(3000, mode="presentation"), detection(7000)]
    windows = [(tool.parse_instant(at(50)), tool.parse_instant(at(150)))]
    report = measure(tool, tmp_path, rows, since=at(0), until=at(7200), deliberate_windows=windows)
    fp = report["false_positive_candidates"]
    assert fp["count"] == 3 and fp["by_mode"] == {"simple": 2, "presentation": 1}
    assert fp["span_hours"] == 2.0 and fp["per_hour"] == 1.5


def test_a_declared_silent_hour_counts_every_detection_and_a_clean_hour_says_zero(tool, tmp_path):
    rows = [detection(10), detection(1000)]
    fp = measure(tool, tmp_path, rows, since=at(0), until=at(3600), no_deliberate=True)["false_positive_candidates"]
    assert fp["count"] == 2 and fp["per_hour"] == 2.0
    clean = measure(tool, tmp_path, [row(5, "voice.background")], since=at(0), until=at(3600), no_deliberate=True)
    assert clean["false_positive_candidates"]["count"] == 0 and clean["false_positive_candidates"]["per_hour"] == 0.0


def test_without_a_declaration_nothing_is_called_a_false_positive(tool, tmp_path):
    fp = measure(tool, tmp_path, [detection(10)], since=at(0), until=at(3600))["false_positive_candidates"]
    assert fp["declared_no_deliberate_activation"] is False and fp["count"] is None and fp["per_hour"] is None


def test_without_a_range_the_span_is_the_observed_one_and_says_so(tool, tmp_path):
    rows = [detection(0), detection(3600)]
    fp = measure(tool, tmp_path, rows, no_deliberate=True)["false_positive_candidates"]
    assert fp["span_hours"] == 1.0 and "observée" in fp["span_origin"]


# ------------------------------------------------------------------- pannes


def _failed(seconds, suppressed=0, mode="simple"):
    kind = "wake.own_stream.failed" if mode == "simple" else "wake.shared_pcm.failed"
    data = {"code": "wake_engine_unavailable", "cause_code": "wake_model_missing"}
    if suppressed:
        data["suppressed"] = suppressed
    return row(seconds, kind, level="error", **data)


def test_failures_are_grouped_by_code_and_the_suppressed_repeats_are_added(tool, tmp_path):
    report = measure(tool, tmp_path, [_failed(0), _failed(61, suppressed=20), _failed(5, mode="presentation")])
    rows = {(r["mode"], r["code"], r["cause_code"]): r for r in report["failures"]["rows"]}
    simple = rows[("simple", "wake_engine_unavailable", "wake_model_missing")]
    assert simple["lines"] == 2 and simple["suppressed"] == 20 and simple["occurrences"] == 22
    assert simple["max_lines_in_one_minute"] == 1 and report["failures"]["dedupe_respected"] is True
    assert ("presentation", "wake_engine_unavailable", "wake_model_missing") in rows


def test_two_identical_failure_lines_within_a_minute_break_the_dedupe_rule(tool, tmp_path):
    report = measure(tool, tmp_path, [_failed(0), _failed(10)])
    assert report["failures"]["rows"][0]["max_lines_in_one_minute"] == 2
    assert report["failures"]["dedupe_respected"] is False


# ----------------------------------------------------------- rechargement


def test_the_rearm_after_mute_is_measured_as_signed_started_to_background_and_next_detection(tool, tmp_path):
    rows = [
        row(0, "wake.own_stream.started"), detection(1), *activation(1.05),
        row(2, "wake.own_stream.stopped"), row(20, "wake.own_stream.started"),
        row(20.3, "voice.background"), detection(23.3),
    ]
    rearm = measure(tool, tmp_path, rows)["engine_rearm"]
    assert rearm["stream_started"] == 2 and rearm["stream_stopped"] == 1
    assert rearm["started_to_background_ms_signed"]["median"] == pytest.approx(300.0, abs=0.5)
    assert rearm["background_to_next_detection_s"]["min"] == pytest.approx(3.0, abs=0.01)


# ------------------------------------------------------ vie privée / sortie


def test_the_output_contains_no_speech_text_and_no_personal_path(tool, tmp_path, capsys):
    user = getpass.getuser()
    home = str(Path.home())
    secrets = ["mon mot de passe est rouge", f"{home}\\Documents\\x.wav", f"/home/{user}/audio.wav", user]
    rows = [
        {"ts": at(1), "kind": "wake.own_stream.detected", "level": "info",
         "message": secrets[0], "data": {"provider": f"{home}\\modele", "score": 0.8, "threshold": 0.5,
                                         "keyword": secrets[2], "transcript": secrets[0], "path": secrets[1]}},
        {"ts": at(2), "kind": "voice.wake", "message": secrets[0],
         "data": {"source": secrets[1], "provider": "openwakeword", "keyword": secrets[2]}},
        {"ts": at(3), "kind": "wake.own_stream.failed", "level": "error", "message": secrets[1],
         "data": {"code": secrets[1], "cause_code": secrets[2], "message": secrets[3]}},
        {"ts": at(4), "kind": "voice.transcript", "message": secrets[0], "data": {"text": secrets[0]}},
    ]
    trace = write(tmp_path / "trace.jsonl", rows)
    assert tool.main(["--trace", str(trace), "--output-json", str(tmp_path / "out.json")]) == 0
    printed = capsys.readouterr().out
    assert tool.main(["--trace", str(trace), "--json"]) == 0
    printed += capsys.readouterr().out + (tmp_path / "out.json").read_text(encoding="utf-8")
    for secret in (*secrets, str(tmp_path), "trace.jsonl"):
        assert secret.lower() not in printed.lower(), secret


def test_the_output_says_what_it_cannot_measure(tool, tmp_path, capsys):
    trace = write(tmp_path / "trace.jsonl", [detection(1)])
    assert tool.main(["--trace", str(trace)]) == 0
    text = capsys.readouterr().out
    assert "ne peut pas mesurer" in text.lower() or "ne peut PAS mesurer" in text
    assert "Faux négatifs" in text and "décompte des essais du Human" in text
    assert "latence acoustique" in text.lower()
    assert tool.NOT_MEASURABLE and all(line in text for line in tool.NOT_MEASURABLE)


def test_the_text_report_is_in_french_and_the_json_report_has_every_section(tool, tmp_path, capsys):
    trace = write(tmp_path / "trace.jsonl", [detection(0), *activation(0.05), _failed(30)])
    assert tool.main(["--trace", str(trace)]) == 0
    text = capsys.readouterr().out
    for fragment in ("Détections : 1", "Latences", "Indice d'écho", "Faux positifs", "Pannes du détecteur", "Réarmement"):
        assert fragment in text
    assert tool.main(["--trace", str(trace), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert {"reading", "range", "detections", "latency_ms", "echo_hint", "false_positive_candidates", "failures",
            "engine_rearm", "not_measurable"} <= set(report)


def test_runtime_dir_and_environment_locate_the_trace(tool, tmp_path, monkeypatch, capsys):
    write(tmp_path / "trace.jsonl", [detection(1)])
    assert tool.main(["--runtime-dir", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["detections"]["total"] == 1
    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(tmp_path))
    assert tool.main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["detections"]["total"] == 1


@pytest.mark.parametrize("argv", [["--since", "pas une date"], ["--since", "2026-10-08T10:00", "--until", "2026-10-08T09:00"],
                                  ["--echo-window-s", "nan"], ["--deliberate-window", "2026-10-08T10:00", "2026-10-08T09:00"]])
def test_bad_options_are_refused_with_a_message(tool, tmp_path, argv):
    trace = write(tmp_path / "trace.jsonl", [])
    with pytest.raises(SystemExit) as stop:
        tool.main(["--trace", str(trace), *argv])
    assert stop.value.code not in (0, None)


def test_the_tool_never_modifies_the_trace(tool, tmp_path):
    trace = write(tmp_path / "trace.jsonl", [detection(1), *activation(2)])
    before = trace.read_bytes()
    stamp = trace.stat().st_mtime_ns
    tool.build_report(trace, since=None, until=None)
    assert trace.read_bytes() == before and trace.stat().st_mtime_ns == stamp


def test_the_tool_opens_no_audio_device():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint({"sounddevice", "pvporcupine", "pyaudio", "jarvis", "openwakeword", "onnxruntime", "numpy"}), imported
    source = SCRIPT.read_text(encoding="utf-8")
    assert "RawInputStream" not in source and "InputStream(" not in source


def test_running_the_tool_never_touches_a_sound_device_module(tool, tmp_path, monkeypatch):
    class Tripwire:
        def __getattr__(self, name):
            raise AssertionError(f"audio touché : {name}")

    monkeypatch.setitem(sys.modules, "sounddevice", Tripwire())
    trace = write(tmp_path / "trace.jsonl", [detection(1), *activation(2)])
    assert tool.main(["--trace", str(trace), "--json"]) == 0
