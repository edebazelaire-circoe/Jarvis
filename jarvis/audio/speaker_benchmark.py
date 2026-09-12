"""Banc d'essai des vérificateurs de locuteur, indépendant du moteur (tâche 09).

Ce module ne connaît aucun moteur : il rejoue du PCM dans un `SpeakerVerifier`
(le port de production) en fenêtres de 100 ms, étiquette chaque fenêtre avec la
vérité terrain du manifeste et calcule les métriques de choix (D12) :

- taux de fausse acceptation (FAR) sur les fenêtres « autre locuteur » ;
- taux de faux rejet (FRR) sur les fenêtres « propriétaire » ;
- délai de confirmation du propriétaire depuis le début de sa parole (P50/P95) ;
- chevauchements propriétaire + autre voix ;
- balayage de seuils et taux d'égale erreur (EER).

Définitions exactes : `docs/SPEAKER_BENCHMARK.md`. L'assemblage des moteurs,
le manifeste et les fichiers de résultats vivent dans
`jarvis/runtime/speaker_benchmark.py`.

Un moteur à empreinte vocale s'y branche par `EmbeddingBenchmarkEngine` (même
fenêtre glissante, même porte de parole que la production) ; un moteur
commercial à décision native implémente directement `BenchmarkEngine`.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import math
import time
from typing import Any, Protocol

import numpy as np

from jarvis.audio.duplex import FRAME_MS, CaptureProcessor
from jarvis.audio.owner_verifier import EmbeddingSpeakerVerifier, SpeakerEmbedder, SpeechGate, enroll_embedding, resample
from jarvis.audio.speaker_shadow import SpeakerVerificationWorker
from jarvis.domain.speaker import (
    MAX_OWNER_BUFFER_MS,
    MIN_OWNER_BUFFER_MS,
    OwnerState,
    OwnerStateSnapshot,
    SpeakerVerification,
    VerificationStatus,
)
from jarvis.ports.speaker import SpeakerVerifier

#: Identifiant et version du format de résultat. Toute clé retirée ou dont le
#: sens change incrémente la version ; une clé ajoutée aussi, pour que les
#: comparaisons entre deux campagnes restent explicites.
RESULT_SCHEMA = "jarvis.speaker_benchmark.result"
RESULT_SCHEMA_VERSION = 2


class BenchmarkError(Exception):
    """Diagnostic du banc d'essai, avec un code stable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# -- vérité terrain ------------------------------------------------------------


class Label(StrEnum):
    """Étiquette d'un intervalle du manifeste, et classe d'une fenêtre."""

    #: Le propriétaire enrôlé parle seul.
    OWNER = "owner"
    #: Une autre voix (collègue, synthèse d'un autre locuteur) parle seule.
    NON_OWNER = "non_owner"
    #: Propriétaire et autre voix en même temps.
    OVERLAP = "overlap"
    #: Bruit sans parole (clavier, choc, souffle) : toute acceptation est fausse.
    NOISE = "noise"
    #: Rien d'étiqueté : ignoré par les taux (le verdict d'avant peut y traîner).
    SILENCE = "silence"


@dataclass(frozen=True, slots=True)
class Interval:
    """Intervalle étiqueté, en millisecondes depuis le début du fichier."""

    start_ms: int
    end_ms: int
    label: Label
    speaker: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.label, Label):
            raise TypeError("label must be a Label")
        for name in ("start_ms", "end_ms"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative int")
        if self.end_ms <= self.start_ms:
            raise ValueError("an interval must end after it starts")


@dataclass(frozen=True, slots=True)
class EvaluationConfig:
    """Règles de notation, enregistrées telles quelles dans le résultat."""

    #: Une confirmation arrivant jusqu'à ce délai après la fin de la parole du
    #: propriétaire compte encore (quantification des fenêtres de 100 ms).
    confirm_grace_ms: int = 200
    #: Fenêtres exclues des taux par fenêtre quand une frontière d'étiquette
    #: tombe dans les `transition_guard_ms` d'audio qui les précèdent (0 =
    #: notation stricte : la preuve qui traîne d'un locuteur à l'autre compte).
    transition_guard_ms: int = 0
    #: Part minimale de la fenêtre couverte par une étiquette pour qu'elle s'applique.
    min_label_coverage: float = 0.5
    #: Deux paroles du même rôle séparées de moins que cela forment un seul événement.
    event_merge_gap_ms: int = 1000

    def __post_init__(self) -> None:
        for name in ("confirm_grace_ms", "transition_guard_ms", "event_merge_gap_ms"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative int")
        if not 0.0 < float(self.min_label_coverage) <= 1.0:
            raise ValueError("min_label_coverage must lie in ]0, 1]")

    def payload(self) -> dict[str, object]:
        return {
            "confirm_grace_ms": self.confirm_grace_ms,
            "transition_guard_ms": self.transition_guard_ms,
            "min_label_coverage": self.min_label_coverage,
            "event_merge_gap_ms": self.event_merge_gap_ms,
        }


Span = tuple[int, int]


def merge_spans(spans: Iterable[Span], *, gap_ms: int = 0) -> list[Span]:
    """Union triée d'intervalles ; ceux séparés de `gap_ms` au plus fusionnent."""

    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start - merged[-1][1] <= gap_ms:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def intersect_spans(left: Sequence[Span], right: Sequence[Span]) -> list[Span]:
    """Intersection de deux unions triées (sorties de `merge_spans`)."""

    out: list[Span] = []
    i = j = 0
    while i < len(left) and j < len(right):
        start = max(left[i][0], right[j][0])
        end = min(left[i][1], right[j][1])
        if start < end:
            out.append((start, end))
        if left[i][1] < right[j][1]:
            i += 1
        else:
            j += 1
    return out


def coverage(spans: Sequence[Span], start_ms: int, end_ms: int) -> float:
    """Part de [start_ms, end_ms[ couverte par une union triée."""

    length = end_ms - start_ms
    if length <= 0:
        return 0.0
    covered = 0
    for span_start, span_end in spans:
        if span_end <= start_ms:
            continue
        if span_start >= end_ms:
            break
        covered += min(span_end, end_ms) - max(span_start, start_ms)
    return covered / length


@dataclass(frozen=True, slots=True)
class _Truth:
    owner: list[Span]  # propriétaire, seul ou en chevauchement
    other: list[Span]  # autre voix, seule ou en chevauchement
    both: list[Span]
    noise: list[Span]
    boundaries: list[int]


def _truth(intervals: Sequence[Interval]) -> _Truth:
    def spans(*labels: Label) -> list[Span]:
        return merge_spans((item.start_ms, item.end_ms) for item in intervals if item.label in labels)

    owner = spans(Label.OWNER, Label.OVERLAP)
    other = spans(Label.NON_OWNER, Label.OVERLAP)
    boundaries = sorted(
        {edge for item in intervals if item.label is not Label.SILENCE for edge in (item.start_ms, item.end_ms)}
    )
    return _Truth(owner, other, intersect_spans(owner, other), spans(Label.NOISE), boundaries)


def classify_hop(truth: _Truth, start_ms: int, end_ms: int, min_coverage: float) -> Label:
    """Classe d'une fenêtre : chevauchement > propriétaire / autre > bruit > silence.

    Égalité propriétaire/autre sur une frontière : propriétaire (le cas compte
    alors en faux rejet possible, jamais en fausse acceptation).
    """

    if coverage(truth.both, start_ms, end_ms) >= min_coverage:
        return Label.OVERLAP
    owner = coverage(truth.owner, start_ms, end_ms)
    other = coverage(truth.other, start_ms, end_ms)
    if max(owner, other) >= min_coverage:
        return Label.OWNER if owner >= other else Label.NON_OWNER
    if coverage(truth.noise, start_ms, end_ms) >= min_coverage:
        return Label.NOISE
    return Label.SILENCE


def in_transition(boundaries: Sequence[int], end_ms: int, guard_ms: int) -> bool:
    """Une frontière d'étiquette tombe-t-elle dans ]end_ms - guard_ms, end_ms[ ?"""

    if guard_ms <= 0:
        return False
    low = bisect_right(boundaries, end_ms - guard_ms)
    high = bisect_left(boundaries, end_ms)
    return high > low


@dataclass(frozen=True, slots=True)
class OwnerEvent:
    """Prise de parole du propriétaire : le délai de confirmation part de `onset_ms`."""

    onset_ms: int
    end_ms: int
    #: Une autre voix parle pendant une partie de l'événement.
    overlapped: bool


@dataclass(frozen=True, slots=True)
class HopRecord:
    """Ce que le vérificateur a rendu pour une fenêtre (métadonnées seules)."""

    start_ms: int
    end_ms: int
    status: str
    score: float | None
    #: Décision du moteur à son propre seuil (`owner_detected`).
    detected: bool
    evidence_ms: int
    #: Durée murale de l'appel `process` (≈ CPU : un seul fil de calcul).
    wall_ms: float
    #: Une empreinte a été calculée pour cette fenêtre (inconnu : None).
    scored: bool | None = None
    #: Score de la fenêtre de preuve complète, avant la règle du passage de
    #: relais (tâche 07) : c'est lui que balayent les seuils et l'EER, pour
    #: que les taux par fenêtre mesurent la seule discrimination du moteur.
    #: `None` quand le moteur ne l'expose pas : `score` sert alors.
    window_score: float | None = None

    @property
    def judged(self) -> bool:
        return self.status == VerificationStatus.OK.value and self.score is not None

    @property
    def sweep_score(self) -> float | None:
        """Score utilisé par le balayage et l'EER."""

        return self.score if self.window_score is None else self.window_score


@dataclass(frozen=True, slots=True)
class LabelledTrace:
    """Un scénario rejoué et étiqueté, prêt pour la notation."""

    name: str
    hops: tuple[HopRecord, ...]
    classes: tuple[Label, ...]
    excluded: tuple[bool, ...]
    owner_events: tuple[OwnerEvent, ...]
    non_owner_events: tuple[Span, ...]
    tags: tuple[str, ...] = ()


def label_trace(
    name: str,
    hops: Sequence[HopRecord],
    intervals: Sequence[Interval],
    config: EvaluationConfig,
    *,
    tags: Sequence[str] = (),
) -> LabelledTrace:
    """Associer chaque fenêtre rejouée à sa vérité terrain."""

    truth = _truth(intervals)
    classes = tuple(classify_hop(truth, hop.start_ms, hop.end_ms, config.min_label_coverage) for hop in hops)
    excluded = tuple(in_transition(truth.boundaries, hop.end_ms, config.transition_guard_ms) for hop in hops)
    owner_events = tuple(
        OwnerEvent(start, end, overlapped=bool(intersect_spans([(start, end)], truth.other)))
        for start, end in merge_spans(truth.owner, gap_ms=config.event_merge_gap_ms)
    )
    non_owner = merge_spans(
        ((item.start_ms, item.end_ms) for item in intervals if item.label is Label.NON_OWNER),
        gap_ms=config.event_merge_gap_ms,
    )
    return LabelledTrace(name, tuple(hops), classes, excluded, owner_events, tuple(non_owner), tuple(tags))


# -- métriques -------------------------------------------------------------------


def percentile(values: Sequence[float], q: float) -> float | None:
    """Percentile par interpolation linéaire entre rangs (méthode par défaut de numpy)."""

    if not values:
        return None
    if not 0.0 <= q <= 100.0:
        raise ValueError("q must lie in [0, 100]")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * q / 100.0
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _accepted(hop: HopRecord, threshold: float | None) -> bool:
    if threshold is None:
        return hop.detected
    return hop.judged and float(hop.sweep_score) >= threshold  # type: ignore[arg-type]


#: Clés d'un bloc de métriques, dans l'ordre du résultat (schéma versionné).
METRIC_KEYS: tuple[str, ...] = (
    "threshold",
    "far",
    "frr",
    "non_owner_hops",
    "non_owner_hops_judged",
    "non_owner_hops_accepted",
    "owner_hops",
    "owner_hops_judged",
    "owner_hops_rejected",
    "owner_judged_ratio",
    "overlap_hops",
    "overlap_hops_judged",
    "overlap_hops_accepted",
    "overlap_accept_rate",
    "noise_hops",
    "noise_hops_accepted",
    "excluded_hops",
    "owner_events",
    "owner_events_confirmed",
    "owner_miss_rate",
    "confirm_ms_p50",
    "confirm_ms_p95",
    "confirm_ms_max",
    "overlap_events",
    "overlap_events_confirmed",
    "overlap_confirm_ms_p50",
    "overlap_confirm_ms_p95",
    "non_owner_events",
    "non_owner_events_false_accepted",
    "false_accept_event_rate",
)


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(float(value), digits)


def metrics_at(traces: Sequence[LabelledTrace], threshold: float | None, config: EvaluationConfig) -> dict[str, object]:
    """Métriques regroupées sur des scénarios, au seuil donné.

    `threshold=None` : décision du moteur lui-même (`owner_detected`) ; sinon
    une fenêtre est acceptée quand elle est jugée et que `owner_score >= threshold`.
    """

    count: dict[str, int] = {
        key: 0
        for key in (
            "non_owner_hops", "non_owner_hops_judged", "non_owner_hops_accepted",
            "owner_hops", "owner_hops_judged", "owner_hops_rejected",
            "overlap_hops", "overlap_hops_judged", "overlap_hops_accepted",
            "noise_hops", "noise_hops_accepted", "excluded_hops",
            "non_owner_events", "non_owner_events_false_accepted",
        )
    }  # fmt: skip
    confirm: list[float] = []
    overlap_confirm: list[float] = []
    owner_events = overlap_events = 0
    for trace in traces:
        accepted = [_accepted(hop, threshold) for hop in trace.hops]
        for hop, klass, excluded, ok in zip(trace.hops, trace.classes, trace.excluded, accepted):
            if klass is Label.SILENCE:
                continue
            if excluded:
                count["excluded_hops"] += 1
                continue
            prefix = {
                Label.OWNER: "owner",
                Label.NON_OWNER: "non_owner",
                Label.OVERLAP: "overlap",
                Label.NOISE: "noise",
            }[klass]
            count[f"{prefix}_hops"] += 1
            if klass is Label.NOISE:
                count["noise_hops_accepted"] += int(ok)
                continue
            if hop.judged:
                count[f"{prefix}_hops_judged"] += 1
                if klass is Label.OWNER:
                    count["owner_hops_rejected"] += int(not ok)
                else:
                    count[f"{prefix}_hops_accepted"] += int(ok)
        for event in trace.owner_events:
            owner_events += 1
            overlap_events += int(event.overlapped)
            for hop, ok in zip(trace.hops, accepted):
                if ok and event.onset_ms < hop.end_ms <= event.end_ms + config.confirm_grace_ms:
                    latency = float(hop.end_ms - event.onset_ms)
                    confirm.append(latency)
                    if event.overlapped:
                        overlap_confirm.append(latency)
                    break
        for start, end in trace.non_owner_events:
            eligible = [
                ok
                for hop, klass, excluded, ok in zip(trace.hops, trace.classes, trace.excluded, accepted)
                if klass is Label.NON_OWNER and not excluded and hop.start_ms < end and hop.end_ms > start
            ]
            if eligible:
                count["non_owner_events"] += 1
                count["non_owner_events_false_accepted"] += int(any(eligible))
    owner_rejected = count["owner_hops_rejected"]
    values: dict[str, object] = {
        "threshold": _round(threshold, 4),
        "far": _round(ratio(count["non_owner_hops_accepted"], count["non_owner_hops_judged"]), 4),
        "frr": _round(ratio(owner_rejected, count["owner_hops_judged"]), 4),
        **{key: count[key] for key in ("non_owner_hops", "non_owner_hops_judged", "non_owner_hops_accepted")},
        **{key: count[key] for key in ("owner_hops", "owner_hops_judged", "owner_hops_rejected")},
        "owner_judged_ratio": _round(ratio(count["owner_hops_judged"], count["owner_hops"]), 4),
        **{key: count[key] for key in ("overlap_hops", "overlap_hops_judged", "overlap_hops_accepted")},
        "overlap_accept_rate": _round(ratio(count["overlap_hops_accepted"], count["overlap_hops_judged"]), 4),
        "noise_hops": count["noise_hops"],
        "noise_hops_accepted": count["noise_hops_accepted"],
        "excluded_hops": count["excluded_hops"],
        "owner_events": owner_events,
        "owner_events_confirmed": len(confirm),
        "owner_miss_rate": _round(ratio(owner_events - len(confirm), owner_events), 4),
        "confirm_ms_p50": _round(percentile(confirm, 50), 1),
        "confirm_ms_p95": _round(percentile(confirm, 95), 1),
        "confirm_ms_max": _round(max(confirm) if confirm else None, 1),
        "overlap_events": overlap_events,
        "overlap_events_confirmed": len(overlap_confirm),
        "overlap_confirm_ms_p50": _round(percentile(overlap_confirm, 50), 1),
        "overlap_confirm_ms_p95": _round(percentile(overlap_confirm, 95), 1),
        "non_owner_events": count["non_owner_events"],
        "non_owner_events_false_accepted": count["non_owner_events_false_accepted"],
        "false_accept_event_rate": _round(
            ratio(count["non_owner_events_false_accepted"], count["non_owner_events"]), 4
        ),
    }
    return {key: values[key] for key in METRIC_KEYS}


def threshold_sweep(
    traces: Sequence[LabelledTrace], thresholds: Iterable[float], config: EvaluationConfig
) -> list[dict[str, object]]:
    """Métriques à chaque seuil fourni (trié, dédoublonné).

    Valable pour tout moteur dont le score ne dépend pas de son propre seuil
    (c'est le cas d'`EmbeddingSpeakerVerifier`) : un seul rejeu suffit.
    """

    return [metrics_at(traces, value, config) for value in sorted({round(float(t), 6) for t in thresholds})]


def score_sets(traces: Sequence[LabelledTrace]) -> tuple[list[float], list[float]]:
    """Scores jugés (propriétaire seul, autre voix seule), hors fenêtres exclues."""

    genuine: list[float] = []
    impostor: list[float] = []
    for trace in traces:
        for hop, klass, excluded in zip(trace.hops, trace.classes, trace.excluded):
            if excluded or not hop.judged:
                continue
            if klass is Label.OWNER:
                genuine.append(float(hop.sweep_score))  # type: ignore[arg-type]
            elif klass is Label.NON_OWNER:
                impostor.append(float(hop.sweep_score))  # type: ignore[arg-type]
    return genuine, impostor


def equal_error_rate(genuine: Sequence[float], impostor: Sequence[float]) -> dict[str, object]:
    """Taux d'égale erreur, par fenêtre, sans dépendre des seuils balayés.

    FAR(t) = part des scores imposteurs >= t ; FRR(t) = part des scores du
    propriétaire < t. On parcourt les scores observés comme seuils candidats ;
    au premier où FAR <= FRR, on interpole linéairement avec le candidat
    précédent le point où les deux courbes se croisent.
    """

    base: dict[str, object] = {"eer": None, "threshold": None, "genuine_hops": len(genuine), "impostor_hops": len(impostor)}
    if not genuine or not impostor:
        return base
    gen = np.sort(np.asarray(genuine, dtype=np.float64))
    imp = np.sort(np.asarray(impostor, dtype=np.float64))
    candidates = np.unique(np.concatenate([gen, imp, [1.0 + 1e-9]]))

    def rates(threshold: float) -> tuple[float, float]:
        far = (imp.size - np.searchsorted(imp, threshold, side="left")) / imp.size
        frr = np.searchsorted(gen, threshold, side="left") / gen.size
        return float(far), float(frr)

    previous: tuple[float, float, float] | None = None
    for threshold in candidates:
        far, frr = rates(float(threshold))
        if far <= frr:
            if previous is None or far == frr:
                eer, at = (far + frr) / 2.0, float(threshold)
            else:
                t0, far0, frr0 = previous
                d0, d1 = far0 - frr0, far - frr
                alpha = d0 / (d0 - d1)
                eer = (far0 + alpha * (far - far0) + frr0 + alpha * (frr - frr0)) / 2.0
                at = t0 + alpha * (float(threshold) - t0)
            return {**base, "eer": round(eer, 4), "threshold": round(min(at, 1.0), 4)}
        previous = (float(threshold), far, frr)
    return base


def zero_false_accept_point(sweep: Sequence[Mapping[str, object]]) -> dict[str, object] | None:
    """Plus petit seuil balayé sans aucune fausse acceptation (fenêtres, événements, bruit)."""

    for row in sorted(sweep, key=lambda item: float(item["threshold"])):  # type: ignore[arg-type]
        if (
            row["non_owner_hops_accepted"] == 0
            and row["non_owner_events_false_accepted"] == 0
            and row["noise_hops_accepted"] == 0
        ):
            return {
                key: row[key]
                for key in ("threshold", "frr", "owner_miss_rate", "confirm_ms_p50", "confirm_ms_p95", "overlap_events_confirmed")
            }
    return None


def thresholds_from_range(spec: str) -> list[float]:
    """« début:fin:pas » (bornes incluses) → liste de seuils dans ]0, 1]."""

    try:
        start, stop, step = (float(part) for part in str(spec).split(":"))
    except ValueError:
        raise BenchmarkError("thresholds_invalid", f"Plage de seuils invalide « {spec} » : début:fin:pas attendu.") from None
    if step <= 0 or stop < start:
        raise BenchmarkError("thresholds_invalid", f"Plage de seuils invalide « {spec} » : pas > 0 et fin >= début.")
    count = int(math.floor((stop - start) / step + 1e-9)) + 1
    return check_thresholds(round(start + index * step, 6) for index in range(count))


def check_thresholds(values: Iterable[float]) -> list[float]:
    out = sorted({round(float(value), 6) for value in values})
    if not out:
        raise BenchmarkError("thresholds_invalid", "Aucun seuil à balayer.")
    bad = [value for value in out if not 0.0 < value <= 1.0]
    if bad:
        raise BenchmarkError("thresholds_invalid", f"Seuils hors de ]0, 1] : {bad}.")
    return out


# -- prétraitement et rejeu ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Preprocessing:
    """Chaîne commune à tous les moteurs comparés (sauf ablation explicite).

    Fichier → mono flottant → gain du scénario → rééchantillonnage FFT à
    `capture_rate` (fréquence de capture de la voix) → PCM int16 → fenêtres de
    `hop_ms`. La porte de parole est celle d'`EmbeddingSpeakerVerifier`.
    """

    capture_rate: int = 24_000
    hop_ms: int = 100
    gate_margin_db: float = 10.0
    gate_absolute_min_db: float = -55.0
    gate_history_frames: int = 250

    def __post_init__(self) -> None:
        if not 8_000 <= int(self.capture_rate) <= 96_000:
            raise ValueError("capture_rate must lie in [8000, 96000]")
        if not 10 <= int(self.hop_ms) <= 1000 or (int(self.capture_rate) * int(self.hop_ms)) % 1000:
            raise ValueError("hop_ms must lie in [10, 1000] and hold a whole number of samples")

    @property
    def hop_samples(self) -> int:
        return self.capture_rate * self.hop_ms // 1000

    def gate(self) -> SpeechGate:
        return SpeechGate(
            margin_db=self.gate_margin_db,
            absolute_min_db=self.gate_absolute_min_db,
            history_frames=self.gate_history_frames,
        )

    def payload(self) -> dict[str, object]:
        return {
            "capture_rate": self.capture_rate,
            "hop_ms": self.hop_ms,
            "gate_margin_db": self.gate_margin_db,
            "gate_absolute_min_db": self.gate_absolute_min_db,
            "gate_history_frames": self.gate_history_frames,
            "pcm": "int16 mono",
            "resampler": "FFT (owner_verifier.resample): whole file to capture_rate, evidence window to model rate",
            "aec": "none (offline replay, no far-end signal)",
            "noise_reduction": "none",
            "enrollment": "read_wav -> enroll_embedding (energy gate, 3 s segments, mean of unit embeddings)",
        }


def prepare_pcm(samples: np.ndarray, rate: int, preprocessing: Preprocessing, *, gain_db: float = 0.0) -> np.ndarray:
    """Audio flottant d'un fichier → PCM int16 à la fréquence de capture."""

    mono = np.asarray(samples, dtype=np.float32).reshape(-1)
    if gain_db:
        mono = mono * np.float32(10.0 ** (float(gain_db) / 20.0))
    mono = resample(mono, int(rate), preprocessing.capture_rate)
    return (np.clip(mono, -1.0, 1.0) * 32767.0).astype("<i2")


@dataclass(frozen=True, slots=True)
class ReplayResult:
    hops: tuple[HopRecord, ...]
    #: Temps CPU du processus pendant les appels (granularité ~15,6 ms sous
    #: Windows : juste en cumul, pas fenêtre par fenêtre).
    cpu_ms: float
    wall_ms: float
    #: Retard sur la cadence temps réel après chaque fenêtre (mode temps réel seulement).
    lag_ms: tuple[float, ...] = ()


def replay(
    verifier: SpeakerVerifier,
    pcm: np.ndarray,
    rate: int,
    hop_ms: int,
    *,
    realtime: bool = False,
    clock: Callable[[], float] = time.perf_counter,
    cpu_clock: Callable[[], float] = time.process_time,
    sleep: Callable[[float], None] = time.sleep,
) -> ReplayResult:
    """Rejouer un scénario comme le fil du vérificateur : `reset`, puis une fenêtre par appel.

    Mode accéléré par défaut ; `realtime=True` attend que chaque fenêtre soit
    « arrivée » (fin de fenêtre sur l'horloge murale) avant de la donner, et
    mesure le retard pris. La fenêtre partielle finale est ignorée.
    """

    hop = int(rate) * int(hop_ms) // 1000
    if hop <= 0:
        raise ValueError("hop too short")
    verifier.reset()
    computed = getattr(verifier, "embeddings_computed", None)
    records: list[HopRecord] = []
    lags: list[float] = []
    cpu_start = cpu_clock()
    wall_start = clock()
    for index, offset in enumerate(range(0, pcm.size - hop + 1, hop)):
        if realtime:
            wait = wall_start + (index + 1) * hop_ms / 1000.0 - clock()
            if wait > 0:
                sleep(wait)
        chunk = pcm[offset : offset + hop].tobytes()
        before = clock()
        verdict = verifier.process(chunk, int(rate))
        elapsed = clock() - before
        if not isinstance(verdict, SpeakerVerification):
            raise BenchmarkError("engine_invalid_verdict", f"process() a rendu {type(verdict).__name__}, SpeakerVerification attendu")
        scored: bool | None = None
        if isinstance(computed, int):
            now = getattr(verifier, "embeddings_computed", computed)
            scored, computed = now > computed, now
        if realtime:
            lags.append(max(0.0, (clock() - (wall_start + (index + 1) * hop_ms / 1000.0)) * 1000.0))
        window_score = getattr(verifier, "last_window_score", None)
        records.append(
            HopRecord(
                start_ms=index * int(hop_ms),
                end_ms=(index + 1) * int(hop_ms),
                status=verdict.status.value,
                score=None if verdict.owner_score is None else float(verdict.owner_score),
                detected=bool(verdict.owner_detected),
                evidence_ms=int(verdict.evidence_ms),
                wall_ms=elapsed * 1000.0,
                scored=scored,
                window_score=None if window_score is None else float(window_score),
            )
        )
    return ReplayResult(
        hops=tuple(records),
        cpu_ms=(cpu_clock() - cpu_start) * 1000.0,
        wall_ms=(clock() - wall_start) * 1000.0,
        lag_ms=tuple(lags),
    )


# -- porte d'entrée Solo Owner (production complète) --------------------------------
#
# Le rejeu ci-dessus mesure le vérificateur seul, fenêtre par fenêtre. La porte
# d'entrée de production décide autre chose : ce qui atteint réellement le
# fournisseur. Elle fait intervenir, en plus du verdict, le candidat acoustique
# du `NearEndDetector`, le verdict de fin de candidat des réponses brèves et le
# tampon de rejeu (tâches 04, 06 et 07). Le rejeu « porte » assemble donc les
# vrais composants — `CaptureProcessor`, `SpeakerVerificationWorker`,
# `ShadowOwnerTelemetry` — et rejoue le rôle du pont : ouvrir le flux à la
# confirmation, le refermer au rejet ou à la fin du candidat. JARVIS est
# silencieux (pas de référence lointaine) : hors ligne, aucun écho n'est modélisé.

#: Bloc de capture du rejeu « porte » : celui de Voice (1200 échantillons à
#: 24 kHz). Une commande de flux décidée pendant un bloc s'applique au suivant,
#: comme dans la capture réelle.
GATE_BLOCK_MS = 50


@dataclass(frozen=True, slots=True)
class OwnerOpening:
    """Une ouverture du flux : ce que le fournisseur a reçu et depuis quand."""

    candidate_onset_ms: int
    owner_onset_ms: int
    confirmed_ms: int
    owner_score: float | None
    #: Reconnu à la fermeture du candidat (réponse brève, tâche 07).
    short: bool
    #: Rejeu effectivement envoyé (horloge de capture) et ce qui manquait.
    replay_from_ms: int | None = None
    replay_ms: int = 0
    clamped_ms: int = 0


@dataclass(frozen=True, slots=True)
class OwnerDrop:
    """Un candidat refermé sans jamais avoir été reconnu : rien n'en est parti."""

    candidate_ms: int
    reason: str
    best_score: float | None


@dataclass(frozen=True, slots=True)
class GateTrace:
    """Ce que la porte Solo Owner a laissé passer pour un scénario."""

    name: str
    #: Intervalles d'audio d'entrée transmis au fournisseur (direct + rejeu).
    forwarded: tuple[Span, ...]
    openings: tuple[OwnerOpening, ...]
    drops: tuple[OwnerDrop, ...]
    duration_ms: int
    intervals: tuple[Interval, ...] = ()
    tags: tuple[str, ...] = ()


class _GateDiagnostics:
    """Journal en mémoire : seules les fins de candidat nous intéressent."""

    def __init__(self) -> None:
        self.short_ends: list[int] = []
        self.drops: list[OwnerDrop] = []

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict | None = None) -> None:
        payload = data or {}
        if kind == "voice.owner.confirmed" and payload.get("verdict") == "candidate_end":
            self.short_ends.append(int(payload.get("confirm_ms", 0)))
        elif kind == "voice.input.non_owner_dropped" and payload.get("source") == "capture":
            score = payload.get("best_score")
            self.drops.append(
                OwnerDrop(
                    candidate_ms=int(payload.get("candidate_ms", 0)),
                    reason=str(payload.get("reason", "")),
                    best_score=None if score is None else float(score),  # type: ignore[arg-type]
                )
            )


class _GateTap:
    """Observateur intercalé : note si chaque trame est partie, puis passe la main au fil."""

    def __init__(self, worker: object) -> None:
        self.worker = worker
        self.live: list[bool] = []

    def observe(self, frame: bytes, context: object) -> None:
        self.live.append(bool(getattr(context, "gate_open", False)))
        self.worker.observe(frame, context)  # type: ignore[attr-defined]

    def reset(self) -> None:
        self.worker.reset()  # type: ignore[attr-defined]

    def close(self) -> None:
        self.worker.close()  # type: ignore[attr-defined]


def replay_gate(
    verifier: SpeakerVerifier,
    pcm: np.ndarray,
    rate: int,
    *,
    hop_ms: int,
    owner_buffer_ms: int,
    name: str = "",
    intervals: Sequence[Interval] = (),
    tags: Sequence[str] = (),
) -> GateTrace:
    """Rejouer un scénario à travers la capture et la porte Solo Owner de production.

    Assemble `CaptureProcessor` (tampon de rejeu du propriétaire, garde
    confiée au propriétaire), `SpeakerVerificationWorker` (masquage, fenêtres,
    fil dédié) et `ShadowOwnerTelemetry` (candidats acoustiques, fin de
    candidat, `voice.input.non_owner_dropped`), et tient le rôle du pont :
    confirmation → `open_owner_flow`, rejet ou fin de candidat →
    `close_owner_flow`. Rend les intervalles d'entrée réellement transmis.
    """

    diagnostics = _GateDiagnostics()
    worker = SpeakerVerificationWorker(
        verifier,
        sample_rate=int(rate),
        diagnostics=diagnostics,
        hop_ms=int(hop_ms),
        # Le banc rejoue hors ligne, fenêtre par fenêtre : rien ne doit être
        # jeté faute de temps réel, et chaque évènement doit être vu.
        max_pending_ms=1 << 20,
        max_events_per_minute=1 << 30,
        enforce=True,
    )
    tap = _GateTap(worker)
    capture = CaptureProcessor(
        capture_rate=int(rate),
        render_rate=int(rate),
        canceller=None,
        observer=tap,
        owner_buffer_ms=int(owner_buffer_ms),
    )
    openings: list[list[object]] = []

    def on_state(snapshot: OwnerStateSnapshot) -> None:
        # Rôle du pont (`RealtimeConversationBridge._on_owner_state`), JARVIS
        # silencieux : rien à couper, seule la porte s'ouvre ou se referme.
        if snapshot.state is OwnerState.OWNER_CONFIRMED and snapshot.owner_onset_ms is not None:
            capture.open_owner_flow(snapshot.owner_onset_ms, candidate_onset_ms=snapshot.candidate_onset_ms)
            openings.append([snapshot, None])
        elif snapshot.state in (OwnerState.IDLE, OwnerState.REJECTED):
            capture.close_owner_flow()

    remove = worker.add_owner_listener(on_state)
    replays: list[object] = []
    try:
        capture.reset()
        worker.flush()
        capture.set_owner_gate(True)
        block = max(1, int(rate) * GATE_BLOCK_MS // 1000)
        for offset in range(0, pcm.size - block + 1, block):
            capture.process(pcm[offset : offset + block].tobytes())
            worker.flush()
            replays.extend(capture.take_owner_replays())
    finally:
        remove()
        worker.close()
    # Chaque ouverture acceptée par la capture produit un rapport de rejeu, dans
    # l'ordre ; une ouverture sur un flux déjà ouvert n'en produit pas.
    for index, report in enumerate(replays):
        if index < len(openings):
            openings[index][1] = report
    forwarded = merge_spans(
        [(index * FRAME_MS, (index + 1) * FRAME_MS) for index, sent in enumerate(tap.live) if sent]
        + [(int(report.from_ms), int(report.until_ms)) for report in replays if getattr(report, "replay_ms", 0)]
    )
    short_ends = list(diagnostics.short_ends)
    accepted: list[OwnerOpening] = []
    for snapshot, report in ((item[0], item[1]) for item in openings):
        candidate_onset = int(snapshot.candidate_onset_ms or 0)
        confirmed = int(snapshot.confirmed_ms or snapshot.stream_ms)
        short = confirmed - candidate_onset in short_ends
        if short:
            short_ends.remove(confirmed - candidate_onset)
        accepted.append(
            OwnerOpening(
                candidate_onset_ms=candidate_onset,
                owner_onset_ms=int(snapshot.owner_onset_ms or 0),
                confirmed_ms=confirmed,
                owner_score=None if snapshot.owner_score is None else float(snapshot.owner_score),
                short=short,
                replay_from_ms=None if report is None else int(report.from_ms),
                replay_ms=0 if report is None else int(report.replay_ms),
                clamped_ms=0 if report is None else int(report.clamped_ms),
            )
        )
    return GateTrace(
        name=name,
        forwarded=tuple(forwarded),
        openings=tuple(accepted),
        drops=tuple(diagnostics.drops),
        duration_ms=int(pcm.size * 1000 // int(rate)),
        intervals=tuple(intervals),
        tags=tuple(tags),
    )


#: Clés du bloc « porte » d'un résultat (schéma versionné).
GATE_METRIC_KEYS: tuple[str, ...] = (
    "threshold",
    "owner_events",
    "owner_events_forwarded",
    "owner_gate_miss_rate",
    "gate_confirm_ms_p50",
    "gate_confirm_ms_p95",
    "gate_confirm_ms_max",
    "short_confirmations",
    "owner_start_lost_ms_p95",
    "owner_start_lost_ms_max",
    "owner_forwarded_ratio",
    "openings",
    "false_opens",
    "non_owner_events",
    "non_owner_events_opened",
    "non_owner_forwarded_ms",
    "non_owner_forwarded_ratio",
    "non_owner_run_ms_max",
    "noise_forwarded_ms",
    "replays_clamped",
    "clamped_ms_max",
    "drops",
    "drops_short_not_owner",
)

#: Part de parole du propriétaire sous laquelle une ouverture est « fausse » :
#: le fournisseur a reçu une prise de parole qui n'était pas la sienne.
FALSE_OPEN_OWNER_COVERAGE = 0.2


def gate_metrics(traces: Sequence[GateTrace], threshold: float, config: EvaluationConfig) -> dict[str, object]:
    """Ce que la porte Solo Owner laisse passer, agrégé sur des scénarios."""

    owner_events = forwarded_events = 0
    confirm: list[float] = []
    start_lost: list[float] = []
    short = openings = false_opens = 0
    non_owner_events = non_owner_opened = 0
    owner_ms = owner_forwarded_ms = 0
    other_ms = other_forwarded_ms = noise_forwarded_ms = 0
    run_max = 0
    clamped = 0
    clamped_max = 0
    drops = 0
    drops_short = 0
    for trace in traces:
        truth = _truth(trace.intervals)
        owner_only = _difference(truth.owner, truth.other)
        other_only = _difference(truth.other, truth.owner)
        events = merge_spans(truth.owner, gap_ms=config.event_merge_gap_ms)
        for start, end in events:
            owner_events += 1
            inside = intersect_spans(trace.forwarded, [(start, end + config.confirm_grace_ms)])
            if not inside:
                continue
            forwarded_events += 1
            start_lost.append(float(max(0, inside[0][0] - start)))
            opening = next(
                (item for item in trace.openings if start <= item.confirmed_ms <= end + config.confirm_grace_ms + 1000),
                None,
            )
            if opening is not None:
                confirm.append(float(opening.confirmed_ms - start))
        for item in trace.openings:
            openings += 1
            short += int(item.short)
            clamped += int(item.clamped_ms > 0)
            clamped_max = max(clamped_max, int(item.clamped_ms))
            start, end = item.owner_onset_ms, max(item.confirmed_ms, item.owner_onset_ms + FRAME_MS)
            if coverage(truth.owner, start, end) < FALSE_OPEN_OWNER_COVERAGE:
                false_opens += 1
        for start, end in merge_spans(
            ((item.start_ms, item.end_ms) for item in trace.intervals if item.label is Label.NON_OWNER),
            gap_ms=config.event_merge_gap_ms,
        ):
            non_owner_events += 1
            non_owner_opened += int(
                any(start <= item.confirmed_ms <= end + config.confirm_grace_ms for item in trace.openings)
            )
        owner_ms += _span_ms(owner_only)
        owner_forwarded_ms += _span_ms(intersect_spans(trace.forwarded, owner_only))
        other_ms += _span_ms(other_only)
        leaked = intersect_spans(trace.forwarded, other_only)
        other_forwarded_ms += _span_ms(leaked)
        run_max = max([run_max, *(end - start for start, end in merge_spans(leaked))])
        noise_forwarded_ms += _span_ms(intersect_spans(trace.forwarded, _difference(truth.noise, truth.owner)))
        drops += len(trace.drops)
        drops_short += sum(1 for drop in trace.drops if drop.reason == "short_not_owner")
    values: dict[str, object] = {
        "threshold": _round(threshold, 4),
        "owner_events": owner_events,
        "owner_events_forwarded": forwarded_events,
        "owner_gate_miss_rate": _round(ratio(owner_events - forwarded_events, owner_events), 4),
        "gate_confirm_ms_p50": _round(percentile(confirm, 50), 1),
        "gate_confirm_ms_p95": _round(percentile(confirm, 95), 1),
        "gate_confirm_ms_max": _round(max(confirm) if confirm else None, 1),
        "short_confirmations": short,
        "owner_start_lost_ms_p95": _round(percentile(start_lost, 95), 1),
        "owner_start_lost_ms_max": _round(max(start_lost) if start_lost else None, 1),
        "owner_forwarded_ratio": _round(ratio(owner_forwarded_ms, owner_ms), 4),
        "openings": openings,
        "false_opens": false_opens,
        "non_owner_events": non_owner_events,
        "non_owner_events_opened": non_owner_opened,
        "non_owner_forwarded_ms": other_forwarded_ms,
        "non_owner_forwarded_ratio": _round(ratio(other_forwarded_ms, other_ms), 4),
        "non_owner_run_ms_max": run_max,
        "noise_forwarded_ms": noise_forwarded_ms,
        "replays_clamped": clamped,
        "clamped_ms_max": clamped_max,
        "drops": drops,
        "drops_short_not_owner": drops_short,
    }
    return {key: values[key] for key in GATE_METRIC_KEYS}


def gate_zero_false_open_point(sweep: Sequence[Mapping[str, object]]) -> dict[str, object] | None:
    """Plus petit seuil de la porte sans **aucune ouverture fausse**.

    Une ouverture fausse est une ouverture du flux dont le préfixe rejoué ne
    contient pas de parole du propriétaire : le fournisseur reçoit alors une
    prise de parole qui n'est pas la sienne. Les deux autres compteurs ne font
    pas partie du critère : `non_owner_events_opened` compte aussi les
    confirmations légitimes pendant qu'un collègue parle encore
    (chevauchement), et le bruit transmis sous la parole du propriétaire part
    avec son tour — « le bruit seul n'a jamais été pris pour le propriétaire »
    se lit dans `noise_hops_accepted` et `operating_points.zero_false_accept`.
    """

    for row in sorted(sweep, key=lambda item: float(item["threshold"])):  # type: ignore[arg-type]
        if row["false_opens"] == 0:
            return {
                key: row[key]
                for key in (
                    "threshold",
                    "owner_gate_miss_rate",
                    "gate_confirm_ms_p50",
                    "gate_confirm_ms_p95",
                    "owner_forwarded_ratio",
                    "non_owner_forwarded_ms",
                    "short_confirmations",
                )
            }
    return None


def _difference(spans: Sequence[Span], other: Sequence[Span]) -> list[Span]:
    """Ce que `spans` couvre et que `other` ne couvre pas (unions triées)."""

    out: list[Span] = []
    for start, end in spans:
        cursor = start
        for other_start, other_end in other:
            if other_end <= cursor:
                continue
            if other_start >= end:
                break
            if other_start > cursor:
                out.append((cursor, min(other_start, end)))
            cursor = max(cursor, other_end)
            if cursor >= end:
                break
        if cursor < end:
            out.append((cursor, end))
    return out


def _span_ms(spans: Sequence[Span]) -> int:
    return sum(end - start for start, end in spans)


def timing_summary(values: Sequence[float]) -> dict[str, object]:
    return {
        "count": len(values),
        "mean": _round(sum(values) / len(values), 3) if values else None,
        "p50": _round(percentile(values, 50), 3),
        "p95": _round(percentile(values, 95), 3),
        "max": _round(max(values), 3) if values else None,
    }


# -- moteurs ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VerifierParams:
    """Réglages du vérificateur et de la porte d'entrée, comme en production.

    Les quatre premiers gouvernent la fenêtre glissante et le seuil ; les deux
    suivants la règle des réponses brèves et du passage de relais (tâche 07) ;
    `owner_buffer_ms` est le tampon de rejeu de la capture (tâche 06), qui ne
    change aucun verdict mais décide du début de phrase réellement transmis.
    """

    threshold: float = 0.5
    evidence_ms: int = 1500
    stride_ms: int = 500
    max_gap_ms: int = 600
    short_evidence_ms: int | None = 600
    short_margin: float = 0.1
    owner_buffer_ms: int = 2500

    def __post_init__(self) -> None:
        if isinstance(self.threshold, bool) or not 0.0 < float(self.threshold) <= 1.0:
            raise ValueError("threshold must lie in ]0, 1]")
        for name in ("evidence_ms", "stride_ms", "max_gap_ms"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 20:
                raise ValueError(f"{name} must be an int >= 20")
        short = self.short_evidence_ms
        if short is not None and (isinstance(short, bool) or not isinstance(short, int) or not 20 <= short < self.evidence_ms):
            raise ValueError("short_evidence_ms must be an int in [20, evidence_ms[ or None")
        if isinstance(self.short_margin, bool) or not 0.0 <= float(self.short_margin) <= 0.5:
            raise ValueError("short_margin must lie in [0, 0.5]")
        if (
            isinstance(self.owner_buffer_ms, bool)
            or not isinstance(self.owner_buffer_ms, int)
            or not MIN_OWNER_BUFFER_MS <= self.owner_buffer_ms <= MAX_OWNER_BUFFER_MS
        ):
            raise ValueError(f"owner_buffer_ms must be an int in [{MIN_OWNER_BUFFER_MS}, {MAX_OWNER_BUFFER_MS}]")

    def payload(self) -> dict[str, object]:
        return {
            "threshold": self.threshold,
            "evidence_ms": self.evidence_ms,
            "stride_ms": self.stride_ms,
            "max_gap_ms": self.max_gap_ms,
            "short_evidence_ms": self.short_evidence_ms,
            "short_margin": self.short_margin,
            "owner_buffer_ms": self.owner_buffer_ms,
        }


class BenchmarkEngine(Protocol):
    """Ce qu'un moteur doit fournir pour entrer au banc d'essai.

    - `describe()` : métadonnées publiques (identifiant « nom/version » du port,
      bibliothèque, modèle, SHA-256, licence…), jamais d'empreinte ;
    - `verify()` : contrôle d'intégrité du modèle (chronométré à part), peut ne rien faire ;
    - `load()` : chargement du modèle (chronométré : temps de chargement) ;
    - `enroll(clips)` : référence opaque du propriétaire + métadonnées publiques ;
    - `open_verifier(...)` : un `SpeakerVerifier` (le port de production) ;
    - `close()` : libère le moteur.
    """

    def describe(self) -> Mapping[str, object]: ...

    def verify(self) -> None: ...

    def load(self) -> None: ...

    def enroll(self, clips: Sequence[tuple[np.ndarray, int]]) -> tuple[Any, Mapping[str, object]]: ...

    def open_verifier(
        self, reference: Any, *, profile_id: str, params: VerifierParams, preprocessing: Preprocessing
    ) -> SpeakerVerifier: ...

    def close(self) -> None: ...


class _SharedEmbedder:
    """Le moteur partagé par les vérificateurs d'un même banc : `close` n'y touche pas.

    `EmbeddingSpeakerVerifier.close()` ferme son moteur ; ici le banc ouvre un
    vérificateur par profil et garde le modèle chargé jusqu'au bout.
    """

    #: Empreintes mémorisées au plus (quelques dizaines de mégaoctets) : le
    #: rejeu « porte » repasse le même audio à chaque seuil balayé.
    MAX_CACHED_EMBEDDINGS = 20_000

    def __init__(self, embedder: SpeakerEmbedder) -> None:
        self._embedder = embedder
        self.model_id = embedder.model_id
        self.dim = embedder.dim
        self.sample_rate = embedder.sample_rate
        self._cache: dict[bytes, np.ndarray] | None = None

    def memoize(self, enabled: bool) -> None:
        """Mémoriser les empreintes par contenu audio (rejeux répétés seulement).

        Jamais pendant la mesure du coût : le banc chronomètre le moteur, pas
        un cache. Les rejeux « porte » d'un seuil à l'autre voient exactement
        le même audio et n'ont pas à le recalculer.
        """

        self._cache = {} if enabled else None

    def load(self) -> None:
        load = getattr(self._embedder, "load", None)
        if callable(load):
            load()

    def embed(self, samples: np.ndarray) -> np.ndarray:
        cache = self._cache
        if cache is None:
            return self._embedder.embed(samples)
        key = hashlib.blake2b(np.ascontiguousarray(samples, dtype=np.float32).tobytes(), digest_size=16).digest()
        found = cache.get(key)
        if found is None:
            found = self._embedder.embed(samples)
            if len(cache) >= self.MAX_CACHED_EMBEDDINGS:
                cache.clear()
            cache[key] = found
        return found

    def close(self) -> None:
        """Rien : le banc ferme le moteur lui-même (`EmbeddingBenchmarkEngine.close`)."""


class EmbeddingBenchmarkEngine:
    """`BenchmarkEngine` pour tout `SpeakerEmbedder` : même vérificateur que la production."""

    def __init__(
        self,
        embedder: SpeakerEmbedder,
        *,
        engine_id: str,
        description: Mapping[str, object] | None = None,
        verify: Callable[[], None] | None = None,
    ) -> None:
        self._embedder = embedder
        self._shared = _SharedEmbedder(embedder)
        self.engine_id = engine_id
        self._description = dict(description or {})
        self._verify = verify

    def describe(self) -> dict[str, object]:
        return {
            "id": self.engine_id,
            "model_id": self._embedder.model_id,
            "embedding_dim": int(self._embedder.dim),
            "model_sample_rate": int(self._embedder.sample_rate),
            **self._description,
        }

    def verify(self) -> None:
        if self._verify is not None:
            self._verify()

    def load(self) -> None:
        self._shared.load()

    def enroll(self, clips: Sequence[tuple[np.ndarray, int]]) -> tuple[tuple[float, ...], dict[str, object]]:
        enrollment = enroll_embedding(self._embedder, clips)
        return enrollment.embedding, {
            "voiced_ms": enrollment.voiced_ms,
            "segments": enrollment.segments,
            "consistency": enrollment.consistency,
        }

    def open_verifier(
        self, reference: Any, *, profile_id: str, params: VerifierParams, preprocessing: Preprocessing
    ) -> SpeakerVerifier:
        return EmbeddingSpeakerVerifier(
            self._shared,
            reference,
            engine=self.engine_id,
            profile_id=profile_id,
            threshold=params.threshold,
            evidence_ms=params.evidence_ms,
            stride_ms=params.stride_ms,
            max_gap_ms=params.max_gap_ms,
            gate=preprocessing.gate(),
            short_evidence_ms=params.short_evidence_ms,
            short_margin=params.short_margin,
        )

    def memoize(self, enabled: bool) -> None:
        """Mémoriser les empreintes entre deux rejeux identiques (hors mesure de coût)."""

        self._shared.memoize(enabled)

    def close(self) -> None:
        close = getattr(self._embedder, "close", None)
        if callable(close):
            close()
