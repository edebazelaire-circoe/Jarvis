"""Tâche 09 Solo Owner : banc d'essai des vérificateurs de locuteur.

Tout est déterministe et se passe de modèle : métriques calculées sur des
fenêtres construites à la main, rejeu d'un vérificateur scripté, moteur
factice à bandes spectrales pour la chaîne complète (manifeste → résultats).
Le test du moteur réel, en fin de fichier, est sauté sans sherpa-onnx, sans
modèle ou sans synthèse vocale Windows ; aucun audio n'est versionné.
"""

from __future__ import annotations

import csv
from dataclasses import replace
import io
import json
import math
from pathlib import Path
import sys
import textwrap
import wave

import numpy as np
import pytest

from jarvis.adapters import sherpa_model_catalog as catalog
from jarvis.adapters import sherpa_speaker_embedder as sherpa
from jarvis.adapters.fake_speaker_verifier import ScriptedSpeakerVerifier
from jarvis.audio.speaker_benchmark import (
    GATE_METRIC_KEYS,
    METRIC_KEYS,
    RESULT_SCHEMA,
    RESULT_SCHEMA_VERSION,
    BenchmarkError,
    EmbeddingBenchmarkEngine,
    EvaluationConfig,
    HopRecord,
    Interval,
    Label,
    Preprocessing,
    VerifierParams,
    classify_hop,
    coverage,
    equal_error_rate,
    in_transition,
    intersect_spans,
    label_trace,
    merge_spans,
    metrics_at,
    percentile,
    prepare_pcm,
    replay,
    score_sets,
    threshold_sweep,
    thresholds_from_range,
    zero_false_accept_point,
    _truth,
)
from jarvis.domain.speaker import SpeakerVerification, VerificationStatus
from jarvis.runtime import speaker_benchmark as bench
from jarvis.runtime import speaker_benchmark_fixtures as fixtures

ROOT = Path(__file__).resolve().parents[2]
RATE = 16_000
OWNER_HZ = 300.0
STRANGER_HZ = 2600.0


# ===========================================================================
# Aides
# ===========================================================================


def hop(start: int, status: str = "ok", score: float | None = 0.8, detected: bool | None = None, *, threshold: float = 0.5) -> HopRecord:
    if status != "ok":
        score = None
    if detected is None:
        detected = score is not None and score >= threshold
    return HopRecord(start, start + 100, status, score, detected, 0, 1.0)


def hops_from(scores: list[float | None], *, threshold: float = 0.5) -> list[HopRecord]:
    return [
        hop(index * 100, "ok" if value is not None else "insufficient_audio", value, threshold=threshold)
        for index, value in enumerate(scores)
    ]


def iv(start: int, end: int, label: str, speaker: str | None = None) -> Interval:
    return Interval(start, end, Label(label), speaker)


CONFIG = EvaluationConfig()


# ===========================================================================
# Percentiles, taux, EER
# ===========================================================================


def test_percentile_uses_linear_interpolation_like_numpy():
    assert percentile([], 50) is None
    assert percentile([5.0], 95) == 5.0
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([1, 2, 3, 4], 95) == pytest.approx(3.85)
    values = list(np.random.default_rng(3).uniform(0, 3000, size=57))
    for q in (0, 5, 50, 95, 100):
        assert percentile(values, q) == pytest.approx(float(np.percentile(values, q)))
    with pytest.raises(ValueError):
        percentile([1.0], 101)


def test_eer_perfectly_separable_reversed_and_empty():
    assert equal_error_rate([0.8, 0.9], [0.1, 0.2])["eer"] == 0.0
    assert equal_error_rate([0.1, 0.2], [0.8, 0.9])["eer"] == 1.0
    empty = equal_error_rate([], [0.3])
    assert empty == {"eer": None, "threshold": None, "genuine_hops": 0, "impostor_hops": 1}


def test_eer_exact_crossing_and_interpolated_crossing():
    exact = equal_error_rate([0.4, 0.6, 0.8], [0.2, 0.5, 0.7])
    assert exact["eer"] == pytest.approx(1 / 3, abs=1e-4) and exact["threshold"] == pytest.approx(0.6)
    # FAR − FRR change de signe entre 0,55 (+1/6) et 0,6 (−1/3) : interpolation à 1/3 du pas.
    interpolated = equal_error_rate([0.5, 0.6, 0.9], [0.1, 0.55])
    assert interpolated["eer"] == pytest.approx(1 / 3, abs=1e-4)
    assert interpolated["threshold"] == pytest.approx(0.55 + 0.05 / 3, abs=1e-4)


def test_eer_matches_a_brute_force_grid_on_overlapping_distributions():
    rng = np.random.default_rng(7)
    genuine = list(np.clip(rng.normal(0.7, 0.1, 400), 0, 1))
    impostor = list(np.clip(rng.normal(0.4, 0.1, 600), 0, 1))
    grid = np.linspace(0, 1, 20001)
    gaps = [
        (abs(np.mean(np.array(impostor) >= t) - np.mean(np.array(genuine) < t)), (np.mean(np.array(impostor) >= t) + np.mean(np.array(genuine) < t)) / 2)
        for t in grid
    ]
    brute = min(gaps)[1]
    assert equal_error_rate(genuine, impostor)["eer"] == pytest.approx(brute, abs=0.01)


def test_thresholds_range_list_and_diagnostics():
    assert thresholds_from_range("0.2:0.4:0.1") == [0.2, 0.3, 0.4]
    assert thresholds_from_range("0.3:0.8:0.025")[-1] == 0.8
    for bad in ("0.2:0.4", "a:b:c", "0.4:0.2:0.1", "0.1:0.3:0", "0:0.2:0.1", "0.5:1.5:0.5"):
        with pytest.raises(BenchmarkError) as error:
            thresholds_from_range(bad)
        assert error.value.code == "thresholds_invalid"


# ===========================================================================
# Étiquettes et chevauchements
# ===========================================================================


def test_span_helpers():
    assert merge_spans([(500, 900), (0, 300), (300, 400)]) == [(0, 400), (500, 900)]
    assert merge_spans([(0, 300), (500, 900)], gap_ms=200) == [(0, 900)]
    assert intersect_spans([(0, 1000)], [(200, 300), (900, 1500)]) == [(200, 300), (900, 1000)]
    assert coverage([(0, 50)], 0, 100) == 0.5
    assert coverage([], 0, 100) == 0.0


def test_hop_classes_priority_and_derived_overlap():
    truth = _truth([iv(0, 1000, "non_owner"), iv(600, 2000, "owner"), iv(2000, 3000, "noise"), iv(3000, 3200, "overlap")])
    classify = lambda s: classify_hop(truth, s, s + 100, 0.5)  # noqa: E731
    assert classify(100) is Label.NON_OWNER
    assert classify(700) is Label.OVERLAP  # propriétaire et autre voix mélangés
    assert classify(1500) is Label.OWNER
    assert classify(2500) is Label.NOISE
    assert classify(3100) is Label.OVERLAP  # étiquette explicite
    assert classify(4000) is Label.SILENCE
    # Frontière 50/50 entre deux locuteurs successifs : propriétaire (jamais une fausse acceptation).
    boundary = _truth([iv(0, 1050, "non_owner"), iv(1050, 2000, "owner")])
    assert classify_hop(boundary, 1000, 1100, 0.5) is Label.OWNER
    # La parole l'emporte sur le bruit étiqueté dessous.
    assert classify_hop(_truth([iv(0, 5000, "noise"), iv(1000, 2000, "owner")]), 1000, 1100, 0.5) is Label.OWNER


def test_transition_guard_excludes_hops_whose_recent_audio_straddles_a_boundary():
    boundaries = [1000, 3000]
    assert not in_transition(boundaries, 1100, 0)
    assert in_transition(boundaries, 1100, 500)
    assert in_transition(boundaries, 2400, 1500)
    assert not in_transition(boundaries, 2600, 1500)
    assert not in_transition(boundaries, 1000, 500)  # la frontière n'est pas encore dans la fenêtre


def test_owner_events_merge_short_gaps_and_flag_overlap():
    intervals = [iv(0, 1000, "owner"), iv(1500, 2500, "owner"), iv(5000, 6000, "owner"), iv(5500, 7000, "non_owner"), iv(8000, 9000, "non_owner")]
    trace = label_trace("t", hops_from([None] * 90), intervals, CONFIG)
    assert [(e.onset_ms, e.end_ms, e.overlapped) for e in trace.owner_events] == [(0, 2500, False), (5000, 6000, True)]
    assert trace.non_owner_events == ((5500, 9000),)  # 1 s d'écart : un seul événement


# ===========================================================================
# Métriques et balayage
# ===========================================================================


def scenario_trace():
    """1 s d'autre voix puis 2 s de propriétaire ; 30 fenêtres de 100 ms."""

    scores: list[float | None] = [None] * 5 + [0.3, 0.3, 0.6, 0.3, 0.3]  # autre voix : une fenêtre à 0,6
    scores += [0.4, 0.4] + [None] * 3 + [0.8] * 15  # propriétaire : preuve qui traîne, puis confirmé
    intervals = [iv(0, 1000, "non_owner", "b"), iv(1000, 3000, "owner", "a")]
    return label_trace("s", hops_from(scores), intervals, CONFIG, tags=("transition",))


def test_metrics_far_frr_latency_and_events_at_a_threshold():
    trace = scenario_trace()
    m = metrics_at([trace], 0.5, CONFIG)
    assert list(m) == list(METRIC_KEYS)
    assert (m["non_owner_hops"], m["non_owner_hops_judged"], m["non_owner_hops_accepted"]) == (10, 5, 1)
    assert m["far"] == 0.2
    assert (m["owner_hops"], m["owner_hops_judged"], m["owner_hops_rejected"]) == (20, 17, 2)
    assert m["frr"] == round(2 / 17, 4) and m["owner_judged_ratio"] == 0.85
    # Première fenêtre acceptée dans l'événement : fin à 1600 ms → 600 ms après l'arrivée du propriétaire.
    assert (m["owner_events"], m["owner_events_confirmed"], m["confirm_ms_p50"], m["owner_miss_rate"]) == (1, 1, 600.0, 0.0)
    assert (m["non_owner_events"], m["non_owner_events_false_accepted"], m["false_accept_event_rate"]) == (1, 1, 1.0)
    strict = metrics_at([trace], 0.7, CONFIG)
    assert strict["far"] == 0.0 and strict["non_owner_events_false_accepted"] == 0


def test_engine_decision_uses_the_engines_own_flag():
    hops = [HopRecord(0, 100, "ok", 0.9, False, 0, 1.0), HopRecord(100, 200, "ok", 0.2, True, 0, 1.0)]
    trace = label_trace("e", hops, [iv(0, 200, "non_owner")], CONFIG)
    assert metrics_at([trace], None, CONFIG)["non_owner_hops_accepted"] == 1
    assert metrics_at([trace], 0.5, CONFIG)["non_owner_hops_accepted"] == 1
    assert metrics_at([trace], 0.95, CONFIG)["non_owner_hops_accepted"] == 0


def test_miss_overlap_noise_and_guard_accounting():
    scores: list[float | None] = [0.2] * 10 + [0.9] * 10 + [0.95, 0.2, 0.2]
    intervals = [iv(0, 1000, "owner"), iv(1000, 2000, "non_owner"), iv(1500, 2000, "owner"), iv(2000, 2300, "noise")]
    separate = EvaluationConfig(event_merge_gap_ms=0, confirm_grace_ms=0)
    trace = label_trace("m", hops_from(scores), intervals, separate)
    m = metrics_at([trace], 0.5, separate)
    assert m["owner_events"] == 2 and m["owner_events_confirmed"] == 1 and m["owner_miss_rate"] == 0.5
    assert (m["overlap_events"], m["overlap_events_confirmed"], m["overlap_confirm_ms_p50"]) == (1, 1, 100.0)
    assert (m["overlap_hops"], m["overlap_hops_accepted"], m["overlap_accept_rate"]) == (5, 5, 1.0)
    assert (m["noise_hops"], m["noise_hops_accepted"]) == (3, 1)
    assert label_trace("m", trace.hops, intervals, CONFIG).owner_events[0].end_ms == 2000  # 500 ms d'écart : fusionnés
    guarded = metrics_at([label_trace("m", trace.hops, intervals, EvaluationConfig(transition_guard_ms=300))], 0.5, CONFIG)
    assert guarded["excluded_hops"] > 0
    assert guarded["non_owner_hops"] + guarded["excluded_hops"] + guarded["owner_hops"] + guarded["overlap_hops"] + guarded["noise_hops"] == 23


def test_sweep_is_sorted_deduplicated_monotonic_and_consistent():
    trace = scenario_trace()
    sweep = threshold_sweep([trace], [0.7, 0.3, 0.5, 0.5, 0.9], CONFIG)
    assert [row["threshold"] for row in sweep] == [0.3, 0.5, 0.7, 0.9]
    assert sweep[1] == metrics_at([trace], 0.5, CONFIG)
    far = [row["far"] for row in sweep]
    frr = [row["frr"] for row in sweep]
    assert far == sorted(far, reverse=True) and frr == sorted(frr)
    point = zero_false_accept_point(sweep)
    assert point is not None and point["threshold"] == 0.7
    assert zero_false_accept_point(sweep[:2]) is None
    genuine, impostor = score_sets([trace])
    assert len(genuine) == 17 and len(impostor) == 5


def test_aggregation_pools_scenarios():
    a, b = scenario_trace(), scenario_trace()
    pooled = metrics_at([a, b], 0.5, CONFIG)
    single = metrics_at([a], 0.5, CONFIG)
    assert pooled["non_owner_hops_judged"] == 2 * single["non_owner_hops_judged"]
    assert pooled["far"] == single["far"] and pooled["owner_events"] == 2


# ===========================================================================
# Rejeu
# ===========================================================================


def test_replay_feeds_contiguous_hops_and_records_verdicts():
    verifier = ScriptedSpeakerVerifier([None, 0.4, 0.9, VerificationStatus.ERROR], threshold=0.5)
    pcm = np.zeros(RATE * 450 // 1000, dtype="<i2")  # 4,5 fenêtres : la partielle est ignorée
    result = replay(verifier, pcm, RATE, 100)
    assert verifier.resets == 1 and [calls for calls in verifier.calls] == [(3200, RATE)] * 4
    assert [(h.start_ms, h.status, h.score, h.detected) for h in result.hops] == [
        (0, "insufficient_audio", None, False),
        (100, "ok", 0.4, False),
        (200, "ok", 0.9, True),
        (300, "error", None, False),
    ]
    assert result.lag_ms == () and all(h.scored is None for h in result.hops)


def test_replay_realtime_waits_for_each_hop_and_measures_lag():
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(round(seconds, 3))
        now[0] += seconds

    class Slow(ScriptedSpeakerVerifier):
        def process(self, pcm, sample_rate):  # noqa: ANN001, ANN201
            now[0] += 0.15 if len(self.calls) == 1 else 0.01
            return super().process(pcm, sample_rate)

    result = replay(Slow([0.9] * 3), np.zeros(RATE * 3 // 10, dtype="<i2"), RATE, 100, realtime=True, clock=lambda: now[0], sleep=sleep)
    assert slept == [0.1, 0.09]  # chaque fenêtre n'existe qu'à sa fin ; la 3e est déjà en retard
    # 2e fenêtre : 150 ms de calcul ; la 3e hérite de 60 ms de retard.
    assert list(result.lag_ms) == pytest.approx([10.0, 150.0, 60.0])
    assert [h.wall_ms for h in result.hops] == pytest.approx([10.0, 150.0, 10.0])


def test_replay_rejects_a_non_verdict():
    class Broken(ScriptedSpeakerVerifier):
        def process(self, pcm, sample_rate):  # noqa: ANN001, ANN201
            return {"score": 1.0}

    with pytest.raises(BenchmarkError) as error:
        replay(Broken(), np.zeros(RATE, dtype="<i2"), RATE, 100)
    assert error.value.code == "engine_invalid_verdict"


# ===========================================================================
# Moteur factice, manifestes et chaîne complète
# ===========================================================================


class BandEmbedder:
    """Empreinte = énergie de 16 bandes spectrales : deux « voix » = deux tons."""

    model_id = "fake-bands"
    dim = 16
    sample_rate = 16_000

    def __init__(self) -> None:
        self.loaded = 0
        self.closed = 0

    def load(self) -> None:
        self.loaded += 1

    def close(self) -> None:
        self.closed += 1

    def embed(self, samples: np.ndarray) -> np.ndarray:
        spectrum = np.abs(np.fft.rfft(samples.astype(np.float64))) ** 2
        return np.sqrt(np.array([band.sum() for band in np.array_split(spectrum[1:], self.dim)]))


def tone(freq: float, ms: int, amplitude: float = 0.3) -> np.ndarray:
    t = np.arange(RATE * ms // 1000) / RATE
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def silence(ms: int) -> np.ndarray:
    return np.zeros(RATE * ms // 1000, dtype=np.float32)


def write(path: Path, samples: np.ndarray) -> Path:
    fixtures.write_wav(path, samples, RATE)
    return path


def make_fixture(tmp_path: Path, **overrides) -> Path:  # noqa: ANN003
    """Deux scénarios à tons : propriétaire seul, puis étranger → propriétaire."""

    write(tmp_path / "enroll.wav", tone(OWNER_HZ, 12_000))
    write(tmp_path / "owner.wav", np.concatenate([silence(1000), tone(OWNER_HZ, 3000), silence(1000)]))
    write(tmp_path / "mixed.wav", np.concatenate([silence(500), tone(STRANGER_HZ, 3000), tone(OWNER_HZ, 3000), silence(500)]))
    manifest = {
        "schema": bench.MANIFEST_SCHEMA,
        "schema_version": 1,
        "name": "tones",
        "evidence": "synthetic",
        "thresholds": [0.3, 0.5, 0.7, 0.9],
        "profiles": {"owner": {"enroll": ["enroll.wav"]}},
        "engines": [{"name": "bands", "kind": "factory", "factory": "fake_bands:create", "threshold": 0.5}],
        "scenarios": [
            {"name": "owner", "profile": "owner", "audio": "owner.wav", "intervals": [{"start_ms": 1000, "end_ms": 4000, "label": "owner"}]},
            {
                "name": "mixed",
                "profile": "owner",
                "audio": "mixed.wav",
                "tags": ["transition"],
                "intervals": [
                    {"start_ms": 500, "end_ms": 3500, "label": "non_owner", "speaker": "b"},
                    {"start_ms": 3500, "end_ms": 6500, "label": "owner", "speaker": "a"},
                ],
            },
        ],
    }
    manifest.update(overrides)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def fake_resolver(spec, model_dir):  # noqa: ANN001, ANN201
    del model_dir
    if spec.kind == "factory" and spec.factory == "fake_bands:create":
        return EmbeddingBenchmarkEngine(BandEmbedder(), engine_id="fake-bands/1", description={"library": "numpy", "model_license": "n/a"})
    return bench.resolve_engine(spec, Path("does-not-exist"))


def test_manifest_round_trip_and_path_resolution(tmp_path):
    manifest = bench.load_manifest(make_fixture(tmp_path))
    assert manifest.name == "tones" and manifest.evidence == "synthetic"
    assert manifest.profiles["owner"] == (tmp_path.resolve() / "enroll.wav",)
    assert manifest.scenarios[1].intervals[0] == Interval(500, 3500, Label.NON_OWNER, "b")
    assert manifest.thresholds == (0.3, 0.5, 0.7, 0.9)
    assert manifest.sha256 and len(manifest.sha256) == 64
    again = bench.parse_manifest(manifest.payload(), base_dir=tmp_path)
    assert again.scenarios == manifest.scenarios and again.engines == manifest.engines


def test_toml_manifest_and_audacity_labels(tmp_path):
    write(tmp_path / "a.wav", tone(OWNER_HZ, 2000))
    (tmp_path / "a.labels.txt").write_text("0.5\t1.5\towner\n\\\t300.0\t3000.0\n1.5\t1.9\tnon_owner:bob\n", encoding="utf-8")
    (tmp_path / "m.toml").write_text(
        textwrap.dedent(
            """
            schema = "jarvis.speaker_benchmark.manifest"
            schema_version = 1
            name = "toml"
            thresholds = "0.4:0.6:0.1"
            [profiles.owner]
            enroll = ["a.wav"]
            [[scenarios]]
            name = "a"
            profile = "owner"
            audio = "a.wav"
            labels = "a.labels.txt"
            """
        ),
        encoding="utf-8",
    )
    manifest = bench.load_manifest(tmp_path / "m.toml")
    assert manifest.evidence == "real" and manifest.thresholds == (0.4, 0.5, 0.6)
    assert manifest.scenarios[0].intervals == (Interval(500, 1500, Label.OWNER), Interval(1500, 1900, Label.NON_OWNER, "bob"))


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"schema_version": 2}, "manifest_schema_mismatch"),
        ({"schema": "other"}, "manifest_schema_mismatch"),
        ({"typo": 1}, "manifest_invalid"),
        ({"evidence": "maybe"}, "manifest_invalid"),
        ({"scenarios": []}, "manifest_invalid"),
        ({"thresholds": [0.5, 1.5]}, "thresholds_invalid"),
        ({"engines": [{"name": "x", "kind": "magic"}]}, "manifest_invalid"),
        ({"engines": [{"name": "x", "kind": "sherpa-onnx"}]}, "manifest_invalid"),
        ({"engines": [{"name": "x", "kind": "factory", "factory": "no-colon"}]}, "manifest_invalid"),
        ({"engines": [{"name": "x", "model": "m", "threshold": 0}]}, "manifest_invalid"),
        ({"engines": [{"name": "x", "model": "m"}, {"name": "x", "model": "m"}]}, "manifest_duplicate_name"),
    ],
)
def test_bad_manifest_diagnostics(tmp_path, change, code):
    with pytest.raises(BenchmarkError) as error:
        bench.load_manifest(make_fixture(tmp_path, **change))
    assert error.value.code == code


def test_bad_scenario_diagnostics(tmp_path):
    def scenario(**fields):  # noqa: ANN003, ANN202
        base = {"name": "s", "profile": "owner", "audio": "owner.wav", "intervals": [{"start_ms": 0, "end_ms": 100, "label": "owner"}]}
        return {"scenarios": [{**base, **fields}]}

    cases = [
        (scenario(profile="ghost"), "manifest_unknown_profile"),
        (scenario(intervals=[{"start_ms": 500, "end_ms": 100, "label": "owner"}]), "manifest_interval_invalid"),
        (scenario(intervals=[{"start_ms": 0, "end_ms": 100, "label": "boss"}]), "manifest_invalid"),
        (scenario(name="bad name!"), "manifest_invalid"),
        (scenario(labels="x.txt"), "manifest_invalid"),  # intervals et labels à la fois
    ]
    for change, code in cases:
        with pytest.raises(BenchmarkError) as error:
            bench.load_manifest(make_fixture(tmp_path, **change))
        assert error.value.code == code, change


def test_missing_files_are_all_listed_at_once(tmp_path):
    path = make_fixture(tmp_path)
    (tmp_path / "owner.wav").unlink()
    (tmp_path / "enroll.wav").unlink()
    with pytest.raises(BenchmarkError) as error:
        bench.load_manifest(path)
    assert error.value.code == "manifest_missing_file"
    assert "owner.wav" in str(error.value) and "enroll.wav" in str(error.value)
    with pytest.raises(BenchmarkError) as unreadable:
        bench.load_manifest(tmp_path / "nope.json")
    assert unreadable.value.code == "manifest_unreadable"
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    with pytest.raises(BenchmarkError) as broken:
        bench.load_manifest(tmp_path / "broken.json")
    assert broken.value.code == "manifest_invalid_json"


def test_audio_checks_before_any_engine(tmp_path):
    manifest = bench.load_manifest(make_fixture(tmp_path))
    bad_sha = replace(manifest, scenarios=(replace(manifest.scenarios[0], sha256="0" * 64),))
    with pytest.raises(BenchmarkError) as error:
        bench.load_audio(bad_sha)
    assert error.value.code == "audio_sha_mismatch"
    late = replace(manifest, scenarios=(replace(manifest.scenarios[0], intervals=(Interval(9000, 9500, Label.OWNER),)),))
    with pytest.raises(BenchmarkError) as out_of_range:
        bench.load_audio(late)
    assert out_of_range.value.code == "scenario_interval_out_of_range"
    (tmp_path / "owner.wav").write_bytes(b"not a wav")
    with pytest.raises(BenchmarkError) as unreadable:
        bench.load_audio(manifest)
    assert unreadable.value.code == "audio_unreadable"


def run_fake(tmp_path, **kwargs):  # noqa: ANN001, ANN003, ANN201
    manifest = bench.load_manifest(make_fixture(tmp_path))
    return bench.run_benchmark(manifest, resolver=fake_resolver, **kwargs)


def test_end_to_end_with_a_fake_engine(tmp_path):
    result = run_fake(tmp_path)
    engine = result["engines"][0]
    assert engine["status"] == "ok", engine["message"]
    m = engine["at_engine_threshold"]
    assert m["threshold"] == 0.5 and m["far"] == 0.0 and m["owner_events"] == 2 and m["owner_events_confirmed"] == 2
    assert m["non_owner_events"] == 1 and m["non_owner_events_false_accepted"] == 0
    assert 0 < m["confirm_ms_p50"] <= m["confirm_ms_max"] <= 2500  # au plus 1,5 s de preuve voisée + fenêtres
    owner_only = engine["scenarios"][0]["at_engine_threshold"]
    assert 1500 <= owner_only["confirm_ms_p50"] <= 1800  # seul : il faut toute la fenêtre de preuve
    assert [row["threshold"] for row in engine["sweep"]] == [0.3, 0.5, 0.7, 0.9]
    # Notation stricte : juste après l'étranger, la fenêtre de preuve le contient encore → EER > 0.
    assert 0.0 < engine["eer"]["eer"] < 0.2
    settled = bench.run_benchmark(
        bench.load_manifest(make_fixture(tmp_path, evaluation={"transition_guard_ms": 1500})), resolver=fake_resolver
    )["engines"][0]
    # 14 fenêtres parlées après chacune des 3 frontières de parole (1000, 500 et 3500 ms).
    assert settled["eer"]["eer"] == 0.0 and settled["at_engine_threshold"]["excluded_hops"] == 42
    assert engine["enrollment"]["owner"]["voiced_ms"] >= 10_000
    assert "embedding" not in json.dumps(engine["enrollment"])
    res = engine["resources"]
    assert res["hops"] == 120 and res["scoring_hops"] > 0 and res["model_load_ms"] is not None
    assert res["scoring_hop_ms"]["count"] == res["scoring_hops"]
    assert engine["engine"]["id"] == "fake-bands/1" and engine["engine"]["embedding_dim"] == 16
    assert [s["name"] for s in engine["scenarios"]] == ["owner", "mixed"]
    assert engine["scenarios"][1]["owner_score_mean"] > engine["scenarios"][1]["non_owner_score_max"]
    assert result["disclaimer"] and "NOT evidence" in result["disclaimer"]


# ===========================================================================
# Porte d'entrée Solo Owner (production complète)
# ===========================================================================


def make_gate_fixture(tmp_path: Path, *, engine: dict | None = None) -> Path:  # noqa: ANN003
    """Trois scénarios : réponse brève du propriétaire, étranger seul, relais sans silence."""

    write(tmp_path / "enroll.wav", tone(OWNER_HZ, 12_000))
    write(tmp_path / "short.wav", np.concatenate([silence(1000), tone(OWNER_HZ, 800), silence(2000)]))
    write(tmp_path / "stranger.wav", np.concatenate([silence(500), tone(STRANGER_HZ, 4000), silence(1500)]))
    write(tmp_path / "handover.wav", np.concatenate([silence(500), tone(OWNER_HZ, 4000), tone(STRANGER_HZ, 4000), silence(1500)]))
    manifest = {
        "schema": bench.MANIFEST_SCHEMA,
        "schema_version": 1,
        "name": "gate",
        "evidence": "synthetic",
        "thresholds": [0.5],
        "profiles": {"owner": {"enroll": ["enroll.wav"]}},
        "engines": [{"name": "bands", "kind": "factory", "factory": "fake_bands:create", **(engine or {})}],
        "scenarios": [
            {
                "name": "short_reply",
                "profile": "owner",
                "audio": "short.wav",
                "intervals": [{"start_ms": 1000, "end_ms": 1800, "label": "owner"}],
            },
            {
                "name": "stranger_alone",
                "profile": "owner",
                "audio": "stranger.wav",
                "intervals": [{"start_ms": 500, "end_ms": 4500, "label": "non_owner", "speaker": "b"}],
            },
            {
                "name": "handover",
                "profile": "owner",
                "audio": "handover.wav",
                "intervals": [
                    {"start_ms": 500, "end_ms": 4500, "label": "owner"},
                    {"start_ms": 4500, "end_ms": 8500, "label": "non_owner", "speaker": "b"},
                ],
            },
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def gate_rows(tmp_path: Path, **engine) -> dict[str, dict]:  # noqa: ANN003
    manifest = bench.load_manifest(make_gate_fixture(tmp_path, engine=engine))
    result = bench.run_benchmark(manifest, resolver=fake_resolver)
    outcome = result["engines"][0]
    assert outcome["status"] == "ok", outcome["message"]
    return {row["name"]: row["gate"] for row in outcome["scenarios"]} | {"_engine": outcome}


def test_the_gate_replay_forwards_the_owner_and_never_a_stranger_turn(tmp_path):
    rows = gate_rows(tmp_path)

    stranger = rows["stranger_alone"]
    assert stranger["openings"] == 0 and stranger["false_opens"] == 0
    assert stranger["non_owner_events_opened"] == 0 and stranger["non_owner_forwarded_ms"] == 0
    assert stranger["drops"] == 1  # un candidat refermé, jamais reconnu
    handover = rows["handover"]
    assert handover["owner_events_forwarded"] == 1 and handover["owner_forwarded_ratio"] > 0.5
    # Relais sans silence : ce qui fuit est borné (fenêtre récente + foulée), jamais tout l'étranger.
    assert 0 < handover["non_owner_run_ms_max"] <= 1500 and handover["non_owner_events_opened"] == 0


def test_a_short_owner_reply_is_confirmed_at_the_end_of_its_candidate(tmp_path):
    """La règle des réponses brèves (tâche 07) est ce que la porte mesure, pas la fenêtre glissante."""

    with_rule = gate_rows(tmp_path)["short_reply"]
    without = gate_rows(tmp_path / "off", short_evidence_ms=0)["short_reply"]

    assert with_rule["short_confirmations"] == 1 and with_rule["owner_events_forwarded"] == 1
    assert with_rule["owner_forwarded_ratio"] == 1.0 and with_rule["drops"] == 0
    # 800 ms de parole : la fenêtre de preuve (1500 ms) ne juge jamais.
    assert without["short_confirmations"] == 0 and without["owner_events_forwarded"] == 0
    assert without["drops"] == 1


def test_a_buffer_too_short_loses_the_beginning_of_the_sentence_and_says_so(tmp_path):
    roomy = gate_rows(tmp_path, owner_buffer_ms=2500)["handover"]
    tight = gate_rows(tmp_path / "tight", owner_buffer_ms=500)["handover"]

    assert roomy["replays_clamped"] == 0 and roomy["owner_start_lost_ms_max"] == 0
    assert tight["replays_clamped"] == 1 and tight["clamped_ms_max"] > 0
    assert tight["owner_start_lost_ms_max"] > roomy["owner_start_lost_ms_max"]
    assert tight["owner_forwarded_ratio"] < roomy["owner_forwarded_ratio"]


def test_the_gate_replay_can_be_skipped_or_swept_on_its_own_thresholds(tmp_path):
    manifest = bench.load_manifest(make_gate_fixture(tmp_path))
    skipped = bench.run_benchmark(manifest, resolver=fake_resolver, gate_thresholds=[])["engines"][0]
    swept = bench.run_benchmark(manifest, resolver=fake_resolver, gate_thresholds=[0.4, 0.8])["engines"][0]

    assert skipped["gate_sweep"] == [] and skipped["gate_at_engine_threshold"] is None
    assert skipped["operating_points"]["gate_zero_false_open"] is None
    assert skipped["sweep"] and skipped["scenarios"][0]["gate"] is None
    # Le seuil propre du moteur est toujours mesuré, même absent du balayage demandé.
    assert [row["threshold"] for row in swept["gate_sweep"]] == sorted({0.4, 0.8, sherpa.DEFAULT_THRESHOLD})
    assert swept["gate_at_engine_threshold"]["threshold"] == sherpa.DEFAULT_THRESHOLD


def test_the_handover_rule_only_lowers_a_window_score_never_raises_it():
    """Le score balayé reste celui de la fenêtre complète : discrimination pure.

    Comparaison fenêtre par fenêtre de `score` (décision de production, règle du
    passage de relais appliquée) avec `window_score` (fenêtre de preuve entière,
    ce que balayent les seuils et l'EER).
    """

    preprocessing = Preprocessing()
    engine = EmbeddingBenchmarkEngine(BandEmbedder(), engine_id="fake-bands/1", description={"library": "numpy", "model_license": "n/a"})
    engine.load()
    reference, _ = engine.enroll([(tone(OWNER_HZ, 12_000), RATE)])
    verifier = engine.open_verifier(
        reference, profile_id="owner", params=VerifierParams(threshold=0.5), preprocessing=preprocessing
    )
    # Relais sans silence : la fenêtre glissante garde la voix du propriétaire
    # alors que la parole la plus récente est déjà celle de l'étranger.
    handover = np.concatenate([silence(500), tone(OWNER_HZ, 4000), tone(STRANGER_HZ, 4000), silence(500)])
    pcm = prepare_pcm(handover, RATE, preprocessing)
    hops = [
        h
        for h in replay(verifier, pcm, preprocessing.capture_rate, preprocessing.hop_ms).hops
        if h.score is not None and h.window_score is not None
    ]

    assert hops  # des fenêtres jugées existent
    assert all(h.score <= h.window_score for h in hops)
    # Et la règle a bien joué : sinon l'inégalité ci-dessus ne prouverait rien.
    assert any(h.score < h.window_score for h in hops)
    engine.close()


def test_result_schema_is_stable(tmp_path):
    """Clés figées : les changer impose d'incrémenter RESULT_SCHEMA_VERSION et de mettre à jour ce test."""

    assert RESULT_SCHEMA == "jarvis.speaker_benchmark.result" and RESULT_SCHEMA_VERSION == 2
    result = run_fake(tmp_path, include_hops=True)
    assert list(result) == [
        "schema", "schema_version", "generated_at", "evidence", "disclaimer", "mode", "ablation", "manifest",
        "host", "preprocessing", "evaluation", "thresholds", "engines",
    ]  # fmt: skip
    assert list(result["manifest"]) == ["name", "path", "sha256", "profiles", "scenarios", "audio_ms", "notes"]
    engine = result["engines"][0]
    assert tuple(engine) == bench.ENGINE_RESULT_KEYS == (
        "name", "status", "code", "message", "engine", "verifier", "preprocessing", "ablation", "resources",
        "enrollment", "at_engine_threshold", "sweep", "eer", "operating_points", "gate_at_engine_threshold",
        "gate_sweep", "scenarios",
    )  # fmt: skip
    assert METRIC_KEYS == (
        "threshold", "far", "frr", "non_owner_hops", "non_owner_hops_judged", "non_owner_hops_accepted",
        "owner_hops", "owner_hops_judged", "owner_hops_rejected", "owner_judged_ratio", "overlap_hops",
        "overlap_hops_judged", "overlap_hops_accepted", "overlap_accept_rate", "noise_hops", "noise_hops_accepted",
        "excluded_hops", "owner_events", "owner_events_confirmed", "owner_miss_rate", "confirm_ms_p50",
        "confirm_ms_p95", "confirm_ms_max", "overlap_events", "overlap_events_confirmed", "overlap_confirm_ms_p50",
        "overlap_confirm_ms_p95", "non_owner_events", "non_owner_events_false_accepted", "false_accept_event_rate",
    )  # fmt: skip
    assert list(engine["at_engine_threshold"]) == list(METRIC_KEYS)
    assert all(list(row) == list(METRIC_KEYS) for row in engine["sweep"])
    assert tuple(engine["resources"]) == bench.RESOURCE_KEYS
    assert set(bench.ENGINE_DESCRIPTION_KEYS) <= set(engine["engine"])
    assert list(engine["eer"]) == ["eer", "threshold", "genuine_hops", "impostor_hops"]
    assert list(engine["operating_points"]) == ["zero_false_accept", "gate_zero_false_open"]
    assert list(engine["verifier"]) == [
        "threshold", "evidence_ms", "stride_ms", "max_gap_ms", "short_evidence_ms", "short_margin", "owner_buffer_ms",
    ]  # fmt: skip
    assert GATE_METRIC_KEYS == (
        "threshold", "owner_events", "owner_events_forwarded", "owner_gate_miss_rate", "gate_confirm_ms_p50",
        "gate_confirm_ms_p95", "gate_confirm_ms_max", "short_confirmations", "owner_start_lost_ms_p95",
        "owner_start_lost_ms_max", "owner_forwarded_ratio", "openings", "false_opens", "non_owner_events",
        "non_owner_events_opened", "non_owner_forwarded_ms", "non_owner_forwarded_ratio", "non_owner_run_ms_max",
        "noise_forwarded_ms", "replays_clamped", "clamped_ms_max", "drops", "drops_short_not_owner",
    )  # fmt: skip
    assert list(engine["gate_at_engine_threshold"]) == list(GATE_METRIC_KEYS)
    assert all(list(row) == list(GATE_METRIC_KEYS) for row in engine["gate_sweep"])
    assert list(engine["scenarios"][0]) == [
        "name", "profile", "tags", "gain_db", "duration_ms", "at_engine_threshold", "owner_score_mean",
        "owner_score_min", "non_owner_score_mean", "non_owner_score_max", "hops", "gate",
    ]  # fmt: skip
    assert list(engine["scenarios"][0]["gate"]) == list(GATE_METRIC_KEYS)
    assert tuple(engine["scenarios"][0]["at_engine_threshold"]) == bench.SCENARIO_METRIC_KEYS
    assert engine["scenarios"][0]["hops"][0] == [0, "silence", "insufficient_audio", None, False, 0]
    json.dumps(result)  # sérialisable tel quel


def test_csv_and_markdown_outputs(tmp_path):
    result = run_fake(tmp_path)
    paths = bench.write_outputs(result, tmp_path / "out", "run")
    assert sorted(p.name for p in paths.values()) == ["run.csv", "run.json", "run.md"]
    rows = list(csv.DictReader(io.StringIO(paths["csv"].read_text(encoding="utf-8"))))
    assert tuple(rows[0]) == bench.CSV_COLUMNS
    assert [row["decision"] for row in rows] == ["engine", *["sweep"] * 4, *["gate"] * 4]
    assert rows[0]["engine_name"] == "bands" and rows[0]["schema_version"] == "2" and rows[2]["threshold"] == "0.5"
    gate = [row for row in rows if row["decision"] == "gate"]
    assert gate[0]["openings"] and gate[0]["far"] == ""  # la porte a ses colonnes, pas celles des fenêtres
    assert json.loads(paths["json"].read_text(encoding="utf-8"))["schema_version"] == 2
    text = paths["md"].read_text(encoding="utf-8")
    assert "| bands |" in text and "NOT evidence" in text
    assert "Solo Owner input gate" in text


def test_missing_and_failing_engines_are_reported_not_faked(tmp_path, monkeypatch):
    monkeypatch.setattr(sherpa, "engine_installed", lambda: True)
    base = bench.load_manifest(make_fixture(tmp_path))

    class Exploding:
        def __init__(self) -> None:
            self.inner = EmbeddingBenchmarkEngine(BandEmbedder(), engine_id="boom/1")

        def __getattr__(self, name):  # noqa: ANN001, ANN204
            return getattr(self.inner, name)

        def open_verifier(self, reference, **kwargs):  # noqa: ANN001, ANN003, ANN201
            return ScriptedSpeakerVerifier([0.9, RuntimeError("engine crashed")])

    def resolver(spec, model_dir):  # noqa: ANN001, ANN202
        if spec.name == "boom":
            return Exploding()
        if spec.kind == "factory" and spec.factory == "fake_bands:create":
            return fake_resolver(spec, model_dir)
        return bench.resolve_engine(spec, tmp_path / "models")

    specs = [
        bench._engine({"name": "unknown-model", "model": "no-such-model"}, "t"),
        bench._engine({"name": "no-file", "model": catalog.BASELINE_KEY}, "t"),
        bench._engine({"name": "no-module", "kind": "factory", "factory": "no_such_module_xyz:create"}, "t"),
        bench._engine({"name": "no-attr", "kind": "factory", "factory": "json:no_such_function"}, "t"),
        bench._engine({"name": "boom", "kind": "factory", "factory": "x:y"}, "t"),
        base.engines[0],
    ]
    result = bench.run_benchmark(replace(base, engines=tuple(specs)), resolver=resolver)
    outcome = {engine["name"]: (engine["status"], engine["code"]) for engine in result["engines"]}
    assert outcome == {
        "unknown-model": ("unavailable", "engine_unknown_model"),
        "no-file": ("unavailable", "engine_model_missing"),
        "no-module": ("unavailable", "engine_not_installed"),
        "no-attr": ("unavailable", "engine_factory_invalid"),
        "boom": ("error", "engine_process_failed"),
        "bands": ("ok", None),
    }
    for engine in result["engines"][:5]:
        assert tuple(engine) == bench.ENGINE_RESULT_KEYS and engine["at_engine_threshold"] is None and engine["sweep"] == []
    assert "models --download" in result["engines"][1]["message"]
    rows = bench.csv_rows(result)
    assert [row["status"] for row in rows[:5]] == ["unavailable"] * 4 + ["error"]
    assert "unavailable: `engine_unknown_model`" in bench.markdown_summary(result)


def test_sherpa_engine_not_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(sherpa, "engine_installed", lambda: False)
    with pytest.raises(bench.EngineUnavailable) as error:
        bench.resolve_engine(bench._engine({"name": "x", "model": catalog.BASELINE_KEY}, "t"), tmp_path)
    assert error.value.code == "engine_not_installed"


def test_factory_engine_is_loaded_by_dotted_path(tmp_path, monkeypatch):
    (tmp_path / "plug").mkdir()
    (tmp_path / "plug" / "vendor_engine.py").write_text(
        textwrap.dedent(
            """
            from jarvis.audio.speaker_benchmark import EmbeddingBenchmarkEngine
            import numpy as np

            class Flat:
                model_id = "flat"; dim = 2; sample_rate = 16000
                def embed(self, samples):
                    return np.array([1.0, 0.0])

            def create(options, *, model_dir, num_threads):
                assert options == {"key": "v"} and num_threads == 2
                return EmbeddingBenchmarkEngine(Flat(), engine_id="vendor/9", description={"model_license": "commercial"})
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path / "plug"))
    spec = bench._engine({"name": "vendor", "kind": "factory", "factory": "vendor_engine:create", "options": {"key": "v"}, "num_threads": 2}, "t")
    engine = bench.resolve_engine(spec, tmp_path)
    assert engine.describe()["id"] == "vendor/9"


def test_ablation_must_be_explicit(tmp_path):
    base = bench.load_manifest(make_fixture(tmp_path))
    spec = replace(base.engines[0], preprocessing={"capture_rate": 16000})
    manifest = replace(base, engines=(spec,))
    with pytest.raises(BenchmarkError) as error:
        bench.run_benchmark(manifest, resolver=fake_resolver)
    assert error.value.code == "ablation_required"
    result = bench.run_benchmark(manifest, resolver=fake_resolver, ablation=True)
    assert result["ablation"] is True and result["engines"][0]["preprocessing"]["capture_rate"] == 16000
    assert result["preprocessing"]["capture_rate"] == 24000


def test_same_preprocessing_recorded_for_every_engine(tmp_path):
    base = bench.load_manifest(make_fixture(tmp_path))
    twin = replace(base.engines[0], name="bands-2", params=VerifierParams(threshold=0.7, evidence_ms=1000))
    result = bench.run_benchmark(replace(base, engines=(base.engines[0], twin)), resolver=fake_resolver)
    first, second = result["engines"]
    assert first["preprocessing"] == second["preprocessing"] == result["preprocessing"] == Preprocessing().payload()
    assert second["verifier"]["evidence_ms"] == 1000
    assert second["at_engine_threshold"]["confirm_ms_p50"] < first["at_engine_threshold"]["confirm_ms_p50"]


def test_cli_diagnostics_and_model_listing(tmp_path, capsys):
    path = make_fixture(tmp_path)
    (tmp_path / "owner.wav").unlink()
    assert bench.main(["run", str(path)]) == 2
    assert "[manifest_missing_file]" in capsys.readouterr().err
    write(tmp_path / "owner.wav", tone(OWNER_HZ, 1000))
    assert bench.main(["run", str(path), "--capture-rate", "16000", "--no-isolate"]) == 2
    assert "[ablation_required]" in capsys.readouterr().err
    assert bench.main(["run", str(path), "--thresholds", "0.5", "--threshold-range", "0.1:0.2:0.1"]) == 2
    assert bench.main(["run", str(path), "--engine", "ghost"]) == 2
    assert "[engine_unknown]" in capsys.readouterr().err
    assert bench.main(["models", "--model-dir", str(tmp_path)]) == 0
    listing = capsys.readouterr().out
    assert all(spec.key in listing for spec in catalog.MODELS) and "missing" in listing


def test_cli_expands_engine_variants(tmp_path):
    manifest = bench.load_manifest(make_fixture(tmp_path))
    args = bench.build_parser().parse_args(
        ["run", "m.json", "--sherpa-model", "eres2netv2-zh-cn", "--evidence-ms", "1000,2000", "--threshold", "0.6"]
    )
    expanded = bench._expand_engines(manifest, args, tmp_path)
    assert [(e.name, e.params.evidence_ms, e.params.threshold) for e in expanded.engines] == [
        ("bands@ev1000", 1000, 0.6),
        ("bands@ev2000", 2000, 0.6),
        ("eres2netv2-zh-cn@ev1000", 1000, 0.6),
        ("eres2netv2-zh-cn@ev2000", 2000, 0.6),
    ]
    downloaded = bench._expand_engines(manifest, bench.build_parser().parse_args(["run", "m.json", "--sherpa-model", "downloaded"]), tmp_path)
    assert [e.name for e in downloaded.engines] == ["bands"]  # aucun modèle dans tmp_path
    assert downloaded.evaluation.transition_guard_ms == 0
    guarded = bench._expand_engines(manifest, bench.build_parser().parse_args(["run", "m.json", "--transition-guard-ms", "1500"]), tmp_path)
    assert guarded.evaluation.transition_guard_ms == 1500 and guarded.preprocessing == manifest.preprocessing
    with pytest.raises(BenchmarkError):
        bench._expand_engines(manifest, bench.build_parser().parse_args(["run", "m.json", "--transition-guard-ms", "-1"]), tmp_path)


def test_isolated_engine_runs_in_a_fresh_process(tmp_path, monkeypatch):
    (tmp_path / "plug").mkdir()
    (tmp_path / "plug" / "fake_bands.py").write_text(
        textwrap.dedent(
            """
            import numpy as np
            from jarvis.audio.speaker_benchmark import EmbeddingBenchmarkEngine

            class BandEmbedder:
                model_id = "fake-bands"; dim = 16; sample_rate = 16000
                def embed(self, samples):
                    spectrum = np.abs(np.fft.rfft(samples.astype(np.float64))) ** 2
                    return np.sqrt(np.array([band.sum() for band in np.array_split(spectrum[1:], self.dim)]))

            def create(options, *, model_dir, num_threads):
                return EmbeddingBenchmarkEngine(BandEmbedder(), engine_id="fake-bands/1")
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "plug"))
    manifest = bench.load_manifest(make_fixture(tmp_path))
    result = bench.run_benchmark(manifest, isolate=True)
    engine = result["engines"][0]
    assert engine["status"] == "ok", engine["message"]
    assert engine["resources"]["isolated"] is True and engine["at_engine_threshold"]["owner_events_confirmed"] == 2


def test_an_isolated_engine_that_hangs_is_killed_and_reported(tmp_path, monkeypatch):
    """Un enfant bloqué (chargement ONNX sans retour) doit échouer, pas figer la campagne."""

    seen: dict[str, object] = {}

    def hang(command, **kwargs):  # noqa: ANN001, ANN003
        seen.update(kwargs)
        raise bench.subprocess.TimeoutExpired(command, kwargs["timeout"], stderr="")

    monkeypatch.setattr(bench.subprocess, "run", hang)
    manifest = bench.load_manifest(make_fixture(tmp_path))
    engine = bench.run_benchmark(manifest, isolate=True)["engines"][0]

    assert engine["status"] == "error" and engine["code"] == "engine_subprocess_failed"
    assert "délai dépassé" in engine["message"]
    # Le délai est dérivé de l'audio rejoué, pas d'une constante magique.
    audio = bench.load_audio(manifest)
    audio_ms = sum(audio[scenario.audio].duration_ms for scenario in manifest.scenarios)
    assert seen["timeout"] == bench.isolated_timeout_s(audio_ms, passes=1 + len(manifest.thresholds))
    assert bench.isolated_timeout_s(516_200, passes=8) > bench.isolated_timeout_s(516_200, passes=2) > 0


def test_the_catalog_table_of_the_docs_matches_the_code():
    """`docs/SPEAKER_BENCHMARK.md` publie le hachage épinglé : il sort du catalogue, pas d'un copier-coller."""

    page = (ROOT / "docs" / "SPEAKER_BENCHMARK.md").read_text(encoding="utf-8")
    for spec in catalog.MODELS:
        row = next((line for line in page.splitlines() if line.startswith(f"| `{spec.key}` ")), None)
        assert row is not None, f"modèle absent du tableau : {spec.key}"
        assert f"`{spec.sha256}`" in row, spec.key
        assert f"{spec.size:,}".replace(",", " ") in row, spec.key
        assert f"| {spec.dim} |" in row and spec.license in row, spec.key


def test_example_manifest_in_docs_is_valid():
    manifest = bench.load_manifest(ROOT / "docs" / "speaker-benchmark-manifest.example.json", check_files=False)
    assert manifest.evidence == "real" and [e.kind for e in manifest.engines] == ["sherpa-onnx", "sherpa-onnx", "factory"]
    assert all(catalog.find_model(e.model) for e in manifest.engines if e.kind == "sherpa-onnx")


# ===========================================================================
# Catalogue sherpa-onnx
# ===========================================================================


def test_catalog_is_pinned_and_consistent_with_the_baseline():
    keys = [spec.key for spec in catalog.MODELS]
    assert len(set(keys)) == len(keys) and catalog.BASELINE_KEY in keys
    for spec in catalog.MODELS:
        assert len(spec.sha256) == 64 and int(spec.sha256, 16) >= 0
        assert spec.size > 1_000_000 and spec.dim in {192, 256, 512} and spec.sample_rate == 16_000
        assert spec.license in {"Apache-2.0", "CC-BY-4.0"} and spec.license_source
        assert spec.url.endswith(spec.filename)
    base = catalog.find_model(catalog.BASELINE_KEY)
    assert (base.model_id, base.sha256, base.size, base.dim) == (sherpa.MODEL_ID, sherpa.MODEL_SHA256, sherpa.MODEL_SIZE, sherpa.MODEL_DIM)
    assert catalog.find_model(sherpa.MODEL_ID + ".onnx") is base and catalog.find_model("nope") is None


def test_catalog_embedder_uses_the_spec_and_verification_is_strict(tmp_path):
    spec = catalog.find_model("eres2net-base-200k-zh-cn")
    embedder = catalog.CatalogSherpaEmbedder(spec, tmp_path, num_threads=2)
    assert (embedder.model_id, embedder.dim, embedder.sample_rate, embedder.num_threads) == (spec.model_id, 512, 16_000, 2)
    assert embedder.model_file == tmp_path / spec.filename and embedder.verify is False
    assert sherpa.SherpaSpeakerEmbedder.dim == sherpa.MODEL_DIM  # le moteur de production n'a pas changé
    with pytest.raises(sherpa.SpeakerModelError) as missing:
        catalog.verify_spec(spec, tmp_path)
    assert missing.value.code == "speaker_model_missing"
    (tmp_path / spec.filename).write_bytes(b"x" * 10)
    with pytest.raises(sherpa.SpeakerModelError) as mismatch:
        catalog.verify_spec(spec, tmp_path)
    assert mismatch.value.code == "speaker_model_mismatch"


# ===========================================================================
# Jeux d'essai synthétiques (sans synthèse vocale)
# ===========================================================================


def test_voice_selection_counts_each_speaker_once():
    listed = [
        {"engine": "sapi", "name": "Microsoft Hortense Desktop", "lang": "fr-FR", "gender": "Female"},
        {"engine": "onecore", "name": "Microsoft Hortense", "lang": "fr-FR", "gender": "Female"},
        {"engine": "sapi", "name": "Microsoft Zira Desktop", "lang": "en-US", "gender": "Female"},
        {"engine": "onecore", "name": "Microsoft Paul", "lang": "fr-FR", "gender": "Male"},
    ]
    voices = fixtures.select_voices(listed)
    assert [(v.key, v.engine) for v in voices] == [("hortense", "onecore"), ("paul", "onecore"), ("zira", "sapi")]


def test_prepare_utterance_trims_levels_and_aligns():
    speech = np.concatenate([silence(333), tone(OWNER_HZ, 1234, amplitude=0.05), silence(500)])
    out = fixtures.prepare_utterance(speech)
    assert out.size % (RATE // 10) == 0 and abs(out.size - RATE * 1.3) <= RATE * 0.02
    rms = 20 * math.log10(float(np.sqrt(np.mean(out[: RATE] ** 2))))
    assert rms == pytest.approx(fixtures.SPEECH_RMS_DB, abs=0.5)


@pytest.mark.parametrize("kind", list(fixtures.SCENARIOS))
def test_every_synthetic_scenario_builds_valid_labelled_audio(kind):
    def utter(speaker: str, sentence: int) -> np.ndarray:
        return fixtures.prepare_utterance(tone(OWNER_HZ if speaker == "owner" else STRANGER_HZ + 100 * sentence, 3000))

    mix = fixtures.build_scenario(kind, "owner", ["b", "c", "d"], utter, np.random.default_rng(1))
    intervals = [Interval(i["start_ms"], i["end_ms"], Label(i["label"]), i.get("speaker")) for i in mix.intervals]
    assert intervals and all(i.end_ms <= mix.end_ms for i in intervals)
    assert np.max(np.abs(mix.audio)) < 1.5
    owner = merge_spans((i.start_ms, i.end_ms) for i in intervals if i.label is Label.OWNER)
    other = merge_spans((i.start_ms, i.end_ms) for i in intervals if i.label is Label.NON_OWNER)
    both = sum(end - start for start, end in intersect_spans(owner, other))
    if kind.startswith("overlap_"):
        assert both == int(kind.split("_")[1].rstrip("s")) * 1000
    else:
        assert both == 0
    if kind in {"keyboard_desk", "owner_with_keyboard", "low_noise"}:
        assert any(i.label is Label.NOISE for i in intervals)
    if kind.startswith("non_owner_") and kind != "non_owner_then_owner":
        assert not owner


# ===========================================================================
# Moteur réel (sauté sans moteur, modèle ou synthèse vocale Windows)
# ===========================================================================


@pytest.mark.skipif(not sherpa.engine_installed(), reason="extra speaker absent (sherpa-onnx)")
@pytest.mark.skipif(not sherpa.model_path(bench.default_model_dir()).is_file(), reason="modèle absent : jarvis owner-voice download-model")
@pytest.mark.skipif(sys.platform != "win32", reason="synthèse vocale Windows seulement")
def test_real_engine_benchmark_on_a_tiny_generated_scenario(tmp_path):
    try:
        voices = fixtures.select_voices(fixtures.list_voices(tmp_path))
    except fixtures.FixtureError as exc:
        pytest.skip(f"synthèse vocale indisponible : {exc}")
    french = [v for v in voices if v.lang.lower().startswith("fr")]
    others = [v for v in voices if v not in french]
    if not french or not others:
        pytest.skip("il faut une voix française et une autre voix")
    manifest_path = fixtures.generate_synthetic(
        tmp_path / "fixture",
        owners=1,
        voice_keys=[french[0].key, others[0].key],
        only=["owner_alone", "non_owner_conversation", "overlap_2s"],
    )
    manifest = bench.load_manifest(manifest_path)
    assert manifest.evidence == "synthetic" and all(s.sha256 for s in manifest.scenarios)
    result = bench.run_benchmark(manifest, thresholds=[0.3, 0.5, 0.7])
    engine = result["engines"][0]
    assert engine["status"] == "ok", engine["message"]
    assert engine["engine"]["id"].startswith("sherpa-onnx/") and engine["engine"]["model_sha256"] == sherpa.MODEL_SHA256
    m = engine["at_engine_threshold"]
    assert m["owner_events"] == 3 and m["owner_events_confirmed"] >= 2
    assert m["non_owner_hops_judged"] > 0 and engine["eer"]["eer"] is not None
    owner_alone = next(s for s in engine["scenarios"] if s["name"].endswith("owner_alone"))
    conversation = next(s for s in engine["scenarios"] if s["name"].endswith("non_owner_conversation"))
    assert owner_alone["owner_score_mean"] > conversation["non_owner_score_mean"]
    assert engine["resources"]["scoring_hops"] > 0 and engine["resources"]["model_load_ms"] > 0
    assert list(tmp_path.glob("**/*.onnx")) == []  # le banc ne copie jamais de modèle
