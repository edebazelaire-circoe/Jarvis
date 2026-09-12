"""Banc d'essai des vérificateurs de locuteur : manifeste, moteurs, résultats (tâche 09).

Assemble ce que `jarvis/audio/speaker_benchmark.py` laisse neutre :

- le manifeste de scénarios (JSON ou TOML, schéma versionné) : fichiers WAV,
  intervalles étiquetés, enregistrements d'enrôlement par profil, moteurs,
  seuils — les enregistrements privés restent hors de Git, le manifeste peut
  pointer n'importe où ;
- la résolution des moteurs : `sherpa-onnx` (catalogue épinglé
  `jarvis/adapters/sherpa_model_catalog.py`) ou `factory` (« module:fonction »
  qui rend un `BenchmarkEngine` : un moteur commercial s'ajoute ainsi sans
  toucher au banc) ;
- mémoire du processus, temps de chargement, CPU ;
- résultats JSON + CSV + résumé Markdown, schéma versionné ;
- la ligne de commande (`scripts/benchmark_speaker_verification.py`).

Aucun audio ni empreinte n'entre dans les résultats : scores, décisions,
durées et métadonnées seulement. Mode d'emploi : `docs/SPEAKER_BENCHMARK.md`.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field, replace
import datetime as _dt
import gc
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time
import tomllib
from typing import Any, Callable, Mapping, Sequence

from jarvis.audio.speaker_benchmark import (
    GATE_METRIC_KEYS,
    METRIC_KEYS,
    RESULT_SCHEMA,
    RESULT_SCHEMA_VERSION,
    BenchmarkEngine,
    BenchmarkError,
    EmbeddingBenchmarkEngine,
    EvaluationConfig,
    GateTrace,
    Interval,
    Label,
    LabelledTrace,
    Preprocessing,
    VerifierParams,
    check_thresholds,
    equal_error_rate,
    gate_metrics,
    gate_zero_false_open_point,
    label_trace,
    metrics_at,
    prepare_pcm,
    replay,
    replay_gate,
    score_sets,
    threshold_sweep,
    thresholds_from_range,
    timing_summary,
    zero_false_accept_point,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_SCHEMA = "jarvis.speaker_benchmark.manifest"
MANIFEST_SCHEMA_VERSION = 1
EVIDENCE_KINDS = ("synthetic", "real")
#: Balayage par défaut : large, les échelles cosinus diffèrent d'un modèle à l'autre.
DEFAULT_THRESHOLDS = tuple(round(0.05 * step, 2) for step in range(1, 20))
SYNTHETIC_DISCLAIMER = (
    "SYNTHETIC TTS VOICES - NOT evidence for production thresholds. Windows TTS voices are far more "
    "separable than real people in a real office; Task 14 must re-run this benchmark on the owner's own "
    "recordings and real office background speech before choosing an engine, threshold or evidence window."
)
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@+-]{0,63}$")
_TOP_KEYS = {
    "schema", "schema_version", "name", "evidence", "notes", "preprocessing", "evaluation",
    "thresholds", "profiles", "engines", "scenarios",
}  # fmt: skip
_ENGINE_KEYS = {
    "name", "kind", "model", "factory", "options", "threshold", "evidence_ms", "stride_ms",
    "max_gap_ms", "short_evidence_ms", "short_margin", "owner_buffer_ms", "num_threads",
    "preprocessing", "notes",
}  # fmt: skip
_SCENARIO_KEYS = {"name", "profile", "audio", "sha256", "gain_db", "tags", "intervals", "labels", "notes"}
ENGINE_KINDS = ("sherpa-onnx", "factory")
#: Clés garanties du bloc `engine` d'un résultat (None si le moteur ne les donne pas).
ENGINE_DESCRIPTION_KEYS: tuple[str, ...] = (
    "id", "kind", "library", "library_version", "library_license", "model_id", "model_file",
    "model_sha256", "model_size", "model_license", "model_license_source", "model_card", "model_url",
    "embedding_dim", "model_sample_rate", "num_threads", "family", "notes",
)  # fmt: skip
ENGINE_RESULT_KEYS: tuple[str, ...] = (
    "name", "status", "code", "message", "engine", "verifier", "preprocessing", "ablation",
    "resources", "enrollment", "at_engine_threshold", "sweep", "eer", "operating_points",
    "gate_at_engine_threshold", "gate_sweep", "scenarios",
)  # fmt: skip
RESOURCE_KEYS: tuple[str, ...] = (
    "isolated", "rss_method", "model_verify_ms", "model_load_ms", "enroll_ms_total",
    "rss_before_mb", "rss_after_load_mb", "rss_after_run_mb", "rss_load_delta_mb", "rss_steady_delta_mb",
    "peak_rss_mb", "audio_ms", "hops", "scoring_hops", "cpu_ms_total", "cpu_ms_per_hop_mean",
    "cpu_ms_per_scoring_hop_mean", "cpu_pct_one_core", "hop_ms", "scoring_hop_ms", "realtime_lag_ms",
)  # fmt: skip
SCENARIO_METRIC_KEYS: tuple[str, ...] = (
    "far", "frr", "non_owner_hops_judged", "non_owner_hops_accepted", "owner_hops_judged",
    "owner_hops_rejected", "overlap_hops_judged", "overlap_hops_accepted", "noise_hops",
    "noise_hops_accepted", "owner_events", "owner_events_confirmed", "confirm_ms_p50", "confirm_ms_max",
    "non_owner_events", "non_owner_events_false_accepted",
)  # fmt: skip
CSV_COLUMNS: tuple[str, ...] = (
    "schema_version", "manifest", "evidence", "engine_name", "status", "code", "engine_id", "model_id",
    "model_sha256", "evidence_ms", "engine_threshold", "decision", "threshold", "far", "frr", "eer",
    "eer_threshold", "owner_miss_rate", "confirm_ms_p50", "confirm_ms_p95", "overlap_accept_rate",
    "overlap_events", "overlap_events_confirmed", "non_owner_events", "non_owner_events_false_accepted",
    "false_accept_event_rate", "owner_hops_judged", "non_owner_hops_judged", "noise_hops_accepted",
    "cpu_ms_per_scoring_hop_mean", "scoring_hop_ms_p50", "scoring_hop_ms_p95", "cpu_pct_one_core",
    "model_load_ms", "rss_steady_delta_mb",
    "owner_events_forwarded", "owner_gate_miss_rate", "gate_confirm_ms_p50", "gate_confirm_ms_p95",
    "short_confirmations", "owner_forwarded_ratio", "openings", "false_opens", "non_owner_events_opened",
    "non_owner_forwarded_ms", "non_owner_run_ms_max", "noise_forwarded_ms", "replays_clamped", "clamped_ms_max",
)  # fmt: skip


class ManifestError(BenchmarkError):
    """Manifeste illisible, invalide, ou fichier introuvable."""


class EngineUnavailable(BenchmarkError):
    """Moteur non installé, modèle absent ou fabrique introuvable : jamais de résultat inventé."""


# -- manifeste -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EngineSpec:
    name: str
    kind: str
    params: VerifierParams
    model: str | None = None
    factory: str | None = None
    options: Mapping[str, object] = field(default_factory=dict)
    num_threads: int = 1
    preprocessing: Mapping[str, object] | None = None

    def payload(self) -> dict[str, object]:
        out: dict[str, object] = {"name": self.name, "kind": self.kind, **self.params.payload(), "num_threads": self.num_threads}
        if self.model is not None:
            out["model"] = self.model
        if self.factory is not None:
            out["factory"] = self.factory
        if self.options:
            out["options"] = dict(self.options)
        if self.preprocessing is not None:
            out["preprocessing"] = dict(self.preprocessing)
        return out


@dataclass(frozen=True, slots=True)
class ScenarioSpec:
    name: str
    profile: str
    audio: Path
    intervals: tuple[Interval, ...]
    gain_db: float = 0.0
    tags: tuple[str, ...] = ()
    sha256: str | None = None

    def payload(self) -> dict[str, object]:
        out: dict[str, object] = {
            "name": self.name,
            "profile": self.profile,
            "audio": str(self.audio),
            "gain_db": self.gain_db,
            "tags": list(self.tags),
            "intervals": [
                {"start_ms": i.start_ms, "end_ms": i.end_ms, "label": i.label.value, **({"speaker": i.speaker} if i.speaker else {})}
                for i in self.intervals
            ],
        }
        if self.sha256:
            out["sha256"] = self.sha256
        return out


@dataclass(frozen=True, slots=True)
class Manifest:
    name: str
    evidence: str
    preprocessing: Preprocessing
    evaluation: EvaluationConfig
    thresholds: tuple[float, ...]
    profiles: Mapping[str, tuple[Path, ...]]
    engines: tuple[EngineSpec, ...]
    scenarios: tuple[ScenarioSpec, ...]
    path: Path | None = None
    sha256: str | None = None
    notes: str = ""

    def payload(self) -> dict[str, object]:
        """Manifeste effectif (chemins absolus) : relu par les sous-processus d'isolation."""

        pre = self.preprocessing
        return {
            "schema": MANIFEST_SCHEMA,
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "name": self.name,
            "evidence": self.evidence,
            "notes": self.notes,
            "preprocessing": {
                "capture_rate": pre.capture_rate,
                "hop_ms": pre.hop_ms,
                "gate_margin_db": pre.gate_margin_db,
                "gate_absolute_min_db": pre.gate_absolute_min_db,
                "gate_history_frames": pre.gate_history_frames,
            },
            "evaluation": self.evaluation.payload(),
            "thresholds": list(self.thresholds),
            "profiles": {key: {"enroll": [str(path) for path in paths]} for key, paths in self.profiles.items()},
            "engines": [engine.payload() for engine in self.engines],
            "scenarios": [scenario.payload() for scenario in self.scenarios],
        }


def _fail(message: str, code: str = "manifest_invalid") -> ManifestError:
    return ManifestError(code, message)


def _mapping(value: object, where: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _fail(f"{where} : objet attendu.")
    return value


def _unknown_keys(value: Mapping[str, object], allowed: set[str], where: str) -> None:
    unknown = sorted(key for key in value if key not in allowed and not str(key).startswith("_"))
    if unknown:
        raise _fail(f"{where} : clé(s) inconnue(s) {unknown} (commentaires : préfixe « _ »).")


def _int(value: object, where: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise _fail(f"{where} : entier >= {minimum} attendu, reçu {value!r}.")
    return value


def _number(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _fail(f"{where} : nombre attendu, reçu {value!r}.")
    return float(value)


def _name(value: object, where: str) -> str:
    if not isinstance(value, str) or not _NAME.match(value):
        raise _fail(f"{where} : nom de 1 à 64 caractères [A-Za-z0-9_.@+-] attendu, reçu {value!r}.")
    return value


def _path(value: object, base_dir: Path, where: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise _fail(f"{where} : chemin attendu.")
    path = Path(os.path.expandvars(value.strip())).expanduser()
    return path if path.is_absolute() else (base_dir / path)


def read_audacity_labels(path: Path) -> list[Interval]:
    """Pistes d'étiquettes Audacity (« début<TAB>fin<TAB>étiquette », en secondes).

    L'étiquette est `owner`, `non_owner`, `overlap`, `noise` ou `silence`,
    éventuellement suivie de `:locuteur` (ex. `non_owner:collegue`).
    """

    intervals: list[Interval] = []
    try:
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise _fail(f"{path} : {exc}", "manifest_missing_file") from None
    for number, line in enumerate(lines, 1):
        if not line.strip() or line.startswith("\\"):
            continue
        parts = line.split("\t") if "\t" in line else line.split()
        if len(parts) < 3:
            raise _fail(f"{path}:{number} : « début fin étiquette » attendu.")
        try:
            start, end = float(parts[0]), float(parts[1])
        except ValueError:
            raise _fail(f"{path}:{number} : temps invalides.") from None
        label, _, speaker = parts[2].strip().partition(":")
        intervals.append(_interval({"start_ms": round(start * 1000), "end_ms": round(end * 1000), "label": label, "speaker": speaker or None}, f"{path}:{number}"))
    return intervals


def _interval(value: object, where: str) -> Interval:
    item = _mapping(value, where)
    try:
        label = Label(str(item.get("label")))
    except ValueError:
        raise _fail(f"{where} : étiquette {item.get('label')!r} inconnue ({', '.join(label.value for label in Label)}).") from None
    speaker = item.get("speaker")
    try:
        return Interval(
            start_ms=_int(item.get("start_ms"), f"{where}.start_ms"),
            end_ms=_int(item.get("end_ms"), f"{where}.end_ms"),
            label=label,
            speaker=None if speaker in (None, "") else str(speaker),
        )
    except ValueError as exc:
        raise _fail(f"{where} : {exc}.", "manifest_interval_invalid") from None


def _preprocessing(value: object, where: str, base: Preprocessing | None = None) -> Preprocessing:
    item = _mapping(value or {}, where)
    allowed = {"capture_rate", "hop_ms", "gate_margin_db", "gate_absolute_min_db", "gate_history_frames"}
    _unknown_keys(item, allowed, where)
    base = base or Preprocessing()
    try:
        return Preprocessing(
            capture_rate=_int(item.get("capture_rate", base.capture_rate), f"{where}.capture_rate", minimum=1),
            hop_ms=_int(item.get("hop_ms", base.hop_ms), f"{where}.hop_ms", minimum=1),
            gate_margin_db=_number(item.get("gate_margin_db", base.gate_margin_db), f"{where}.gate_margin_db"),
            gate_absolute_min_db=_number(item.get("gate_absolute_min_db", base.gate_absolute_min_db), f"{where}.gate_absolute_min_db"),
            gate_history_frames=_int(item.get("gate_history_frames", base.gate_history_frames), f"{where}.gate_history_frames", minimum=10),
        )
    except ValueError as exc:
        raise _fail(f"{where} : {exc}.") from None


def default_short_evidence_ms(evidence_ms: int) -> int | None:
    """Règle de production : `min(600, preuve − 100)`, désactivé sous le minimum."""

    from jarvis.v2_config import DEFAULT_OWNER_SHORT_EVIDENCE_MS, MIN_OWNER_SHORT_EVIDENCE_MS

    value = min(DEFAULT_OWNER_SHORT_EVIDENCE_MS, int(evidence_ms) - 100)
    return None if value < MIN_OWNER_SHORT_EVIDENCE_MS else value


def _engine(value: object, where: str) -> EngineSpec:
    from jarvis.adapters.sherpa_speaker_embedder import DEFAULT_THRESHOLD
    from jarvis.domain.speaker import DEFAULT_OWNER_BUFFER_MS
    from jarvis.runtime.owner_voice import DEFAULT_STRIDE_MS
    from jarvis.v2_config import DEFAULT_OWNER_EVIDENCE_MS, DEFAULT_OWNER_SHORT_MARGIN

    item = _mapping(value, where)
    _unknown_keys(item, _ENGINE_KEYS, where)
    name = _name(item.get("name"), f"{where}.name")
    kind = item.get("kind", "sherpa-onnx")
    if kind not in ENGINE_KINDS:
        raise _fail(f"{where}.kind : {kind!r} inconnu ({', '.join(ENGINE_KINDS)}).")
    evidence_ms = _int(item.get("evidence_ms", DEFAULT_OWNER_EVIDENCE_MS), f"{where}.evidence_ms")
    raw_short = item.get("short_evidence_ms")
    short_evidence_ms = (
        default_short_evidence_ms(evidence_ms)
        if raw_short is None
        else (None if _int(raw_short, f"{where}.short_evidence_ms") == 0 else _int(raw_short, f"{where}.short_evidence_ms"))
    )
    try:
        params = VerifierParams(
            threshold=_number(item.get("threshold", DEFAULT_THRESHOLD), f"{where}.threshold"),
            evidence_ms=evidence_ms,
            stride_ms=_int(item.get("stride_ms", DEFAULT_STRIDE_MS), f"{where}.stride_ms"),
            max_gap_ms=_int(item.get("max_gap_ms", 600), f"{where}.max_gap_ms"),
            short_evidence_ms=short_evidence_ms,
            short_margin=_number(item.get("short_margin", DEFAULT_OWNER_SHORT_MARGIN), f"{where}.short_margin"),
            owner_buffer_ms=_int(item.get("owner_buffer_ms", DEFAULT_OWNER_BUFFER_MS), f"{where}.owner_buffer_ms"),
        )
    except ValueError as exc:
        raise _fail(f"{where} : {exc}.") from None
    model = item.get("model")
    factory = item.get("factory")
    if kind == "sherpa-onnx" and not isinstance(model, str):
        raise _fail(f"{where}.model : identifiant de modèle du catalogue attendu pour sherpa-onnx.")
    if kind == "factory" and (not isinstance(factory, str) or ":" not in factory):
        raise _fail(f"{where}.factory : « module:fonction » attendu.")
    options = item.get("options", {})
    pre = item.get("preprocessing")
    return EngineSpec(
        name=name,
        kind=str(kind),
        params=params,
        model=model if isinstance(model, str) else None,
        factory=factory if isinstance(factory, str) else None,
        options=dict(_mapping(options, f"{where}.options")),
        num_threads=_int(item.get("num_threads", 1), f"{where}.num_threads", minimum=1),
        preprocessing=None if pre is None else dict(_mapping(pre, f"{where}.preprocessing")),
    )


def parse_manifest(
    data: object, *, base_dir: Path, path: Path | None = None, sha256: str | None = None, check_files: bool = True
) -> Manifest:
    """Valider un manifeste déjà décodé ; tous les fichiers manquants sont listés d'un coup."""

    top = _mapping(data, "manifeste")
    if top.get("schema") != MANIFEST_SCHEMA or top.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise _fail(
            f"schéma {top.get('schema')!r} v{top.get('schema_version')!r} ; attendu {MANIFEST_SCHEMA!r} "
            f"v{MANIFEST_SCHEMA_VERSION}.",
            "manifest_schema_mismatch",
        )
    _unknown_keys(top, _TOP_KEYS, "manifeste")
    evidence = top.get("evidence", "real")
    if evidence not in EVIDENCE_KINDS:
        raise _fail(f"evidence : {evidence!r} ; attendu {' ou '.join(EVIDENCE_KINDS)}.")
    evaluation_raw = _mapping(top.get("evaluation", {}), "evaluation")
    _unknown_keys(evaluation_raw, set(EvaluationConfig().payload()), "evaluation")
    try:
        evaluation = EvaluationConfig(**dict(evaluation_raw))  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise _fail(f"evaluation : {exc}.") from None
    thresholds_raw = top.get("thresholds", list(DEFAULT_THRESHOLDS))
    if isinstance(thresholds_raw, str):
        thresholds = thresholds_from_range(thresholds_raw)
    elif isinstance(thresholds_raw, list):
        thresholds = check_thresholds(_number(value, "thresholds[]") for value in thresholds_raw)
    else:
        raise _fail("thresholds : liste ou « début:fin:pas » attendu.")
    profiles: dict[str, tuple[Path, ...]] = {}
    for key, value in _mapping(top.get("profiles", {}), "profiles").items():
        item = _mapping(value, f"profiles.{key}")
        _unknown_keys(item, {"enroll", "notes"}, f"profiles.{key}")
        clips = item.get("enroll")
        if not isinstance(clips, list) or not clips:
            raise _fail(f"profiles.{key}.enroll : liste non vide de fichiers WAV attendue.")
        profiles[_name(key, "profiles")] = tuple(_path(clip, base_dir, f"profiles.{key}.enroll[]") for clip in clips)
    engines: list[EngineSpec] = []
    for index, value in enumerate(top.get("engines", []) or []):
        engines.append(_engine(value, f"engines[{index}]"))
    scenarios: list[ScenarioSpec] = []
    raw_scenarios = top.get("scenarios")
    if not isinstance(raw_scenarios, list) or not raw_scenarios:
        raise _fail("scenarios : liste non vide attendue.")
    for index, value in enumerate(raw_scenarios):
        where = f"scenarios[{index}]"
        item = _mapping(value, where)
        _unknown_keys(item, _SCENARIO_KEYS, where)
        name = _name(item.get("name"), f"{where}.name")
        profile = _name(item.get("profile"), f"{where}.profile")
        if profile not in profiles:
            raise _fail(f"{where}.profile : profil {profile!r} non déclaré dans profiles.", "manifest_unknown_profile")
        if "intervals" in item and "labels" in item:
            raise _fail(f"{where} : intervals ou labels, pas les deux.")
        if "labels" in item:
            labels_path = _path(item["labels"], base_dir, f"{where}.labels")
            intervals = read_audacity_labels(labels_path) if (labels_path.is_file() or check_files) else []
        else:
            raw_intervals = item.get("intervals")
            if not isinstance(raw_intervals, list) or not raw_intervals:
                raise _fail(f"{where}.intervals : liste non vide attendue (ou labels : fichier Audacity).")
            intervals = [_interval(entry, f"{where}.intervals[{n}]") for n, entry in enumerate(raw_intervals)]
        tags = item.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise _fail(f"{where}.tags : liste de chaînes attendue.")
        sha = item.get("sha256")
        scenarios.append(
            ScenarioSpec(
                name=name,
                profile=profile,
                audio=_path(item.get("audio"), base_dir, f"{where}.audio"),
                intervals=tuple(intervals),
                gain_db=_number(item.get("gain_db", 0.0), f"{where}.gain_db"),
                tags=tuple(tags),
                sha256=str(sha).lower() if sha else None,
            )
        )
    for kind, names in (("engines", [e.name for e in engines]), ("scenarios", [s.name for s in scenarios])):
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise _fail(f"{kind} : nom(s) en double {duplicates}.", "manifest_duplicate_name")
    manifest = Manifest(
        name=_name(top.get("name", "benchmark"), "name"),
        evidence=str(evidence),
        preprocessing=_preprocessing(top.get("preprocessing"), "preprocessing"),
        evaluation=evaluation,
        thresholds=tuple(thresholds),
        profiles=profiles,
        engines=tuple(engines),
        scenarios=tuple(scenarios),
        path=path,
        sha256=sha256,
        notes=str(top.get("notes", "")),
    )
    if check_files:
        missing = [str(p) for p in _manifest_files(manifest) if not p.is_file()]
        if missing:
            raise _fail("fichier(s) introuvable(s) :\n  " + "\n  ".join(missing), "manifest_missing_file")
    return manifest


def _manifest_files(manifest: Manifest) -> list[Path]:
    files = [path for paths in manifest.profiles.values() for path in paths]
    files += [scenario.audio for scenario in manifest.scenarios]
    return list(dict.fromkeys(files))


def load_manifest(path: Path, *, check_files: bool = True) -> Manifest:
    """Lire un manifeste JSON ou TOML ; chemins relatifs = relatifs au manifeste."""

    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise _fail(f"{path} : {exc}", "manifest_unreadable") from None
    try:
        data = tomllib.loads(raw.decode("utf-8")) if path.suffix.lower() == ".toml" else json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, tomllib.TOMLDecodeError) as exc:
        raise _fail(f"{path} : {exc}", "manifest_invalid_json") from None
    return parse_manifest(
        data, base_dir=path.resolve().parent, path=path, sha256=hashlib.sha256(raw).hexdigest(), check_files=check_files
    )


# -- audio ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Audio:
    samples: Any
    rate: int

    @property
    def duration_ms(self) -> int:
        return int(self.samples.size * 1000 // self.rate)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_audio(manifest: Manifest) -> dict[Path, _Audio]:
    """Lire (et contrôler) tous les fichiers du manifeste avant le premier moteur."""

    from jarvis.audio.owner_verifier import EnrollmentError
    from jarvis.runtime.owner_voice import read_wav

    audio: dict[Path, _Audio] = {}
    for path in _manifest_files(manifest):
        try:
            samples, rate = read_wav(path)
        except EnrollmentError as exc:
            raise ManifestError("audio_unreadable", f"{path} : {exc}") from None
        audio[path] = _Audio(samples, int(rate))
    for scenario in manifest.scenarios:
        if scenario.sha256 and _sha256_file(scenario.audio) != scenario.sha256:
            raise ManifestError("audio_sha_mismatch", f"{scenario.audio} : SHA-256 différent de celui du manifeste.")
        duration = audio[scenario.audio].duration_ms
        late = [i for i in scenario.intervals if i.start_ms >= duration or i.end_ms > duration + manifest.preprocessing.hop_ms]
        if late:
            raise ManifestError(
                "scenario_interval_out_of_range",
                f"{scenario.name} : intervalle(s) au-delà de la fin du fichier ({duration} ms) : "
                f"{[(i.start_ms, i.end_ms, i.label.value) for i in late[:3]]}",
            )
    return audio


# -- moteurs ---------------------------------------------------------------------------


def default_runtime_root() -> Path:
    raw = os.getenv("JARVIS_RUNTIME_DIR")
    if not raw:
        return ROOT / "runtime"
    path = Path(raw).expanduser()
    return path if path.is_absolute() else ROOT / path


def default_model_dir() -> Path:
    from jarvis.v2_config import SPEAKER_VERIFICATION_DIRNAME

    return default_runtime_root() / SPEAKER_VERIFICATION_DIRNAME / "models"


EngineResolver = Callable[[EngineSpec, Path], BenchmarkEngine]


def resolve_engine(spec: EngineSpec, model_dir: Path) -> BenchmarkEngine:
    """Construire le moteur décrit ; `EngineUnavailable` s'il ne peut pas tourner ici."""

    if spec.kind == "factory":
        module_name, _, attr = str(spec.factory).partition(":")
        try:
            factory = getattr(importlib.import_module(module_name), attr)
        except ImportError as exc:
            raise EngineUnavailable("engine_not_installed", f"{spec.factory} : module introuvable ({exc}).") from None
        except AttributeError:
            raise EngineUnavailable("engine_factory_invalid", f"{spec.factory} : fonction introuvable.") from None
        try:
            return factory(dict(spec.options), model_dir=model_dir, num_threads=spec.num_threads)
        except BenchmarkError as exc:
            raise EngineUnavailable(exc.code, str(exc)) from None
        except ImportError as exc:
            raise EngineUnavailable("engine_not_installed", f"{spec.factory} : {exc}") from None
    from jarvis.adapters import sherpa_model_catalog as catalog
    from jarvis.adapters import sherpa_speaker_embedder as sherpa

    model = catalog.find_model(str(spec.model))
    if model is None:
        known = ", ".join(item.key for item in catalog.MODELS)
        raise EngineUnavailable("engine_unknown_model", f"Modèle sherpa-onnx {spec.model!r} inconnu du catalogue ({known}).")
    if not sherpa.engine_installed():
        raise EngineUnavailable("engine_not_installed", 'sherpa-onnx n\'est pas installé : pip install -e ".[speaker]".')
    if not model.path(model_dir).is_file():
        raise EngineUnavailable(
            "engine_model_missing",
            f"Modèle absent ({model.path(model_dir)}) : python scripts/benchmark_speaker_verification.py models --download {model.key}",
        )
    embedder = catalog.CatalogSherpaEmbedder(model, model_dir, num_threads=spec.num_threads)
    version = sherpa.engine_version()
    return EmbeddingBenchmarkEngine(
        embedder,
        engine_id=sherpa.engine_id(),
        description={
            **model.payload(),
            "kind": "sherpa-onnx",
            "library": sherpa.ENGINE_NAME,
            "library_version": version,
            "library_license": "Apache-2.0",
            "num_threads": spec.num_threads,
        },
        verify=lambda: catalog.verify_spec(model, model_dir),
    )


# -- mémoire -------------------------------------------------------------------------


def _windows_memory() -> tuple[int, int] | None:
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    kernel32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = Counters()
    counters.cb = ctypes.sizeof(Counters)
    if not kernel32.K32GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return None
    return int(counters.WorkingSetSize), int(counters.PeakWorkingSetSize)


def process_memory() -> tuple[str | None, int | None, int | None]:
    """(méthode, RSS courant, RSS de pointe) en octets ; au mieux, None si inconnu."""

    try:
        if sys.platform == "win32":
            found = _windows_memory()
            return ("GetProcessMemoryInfo", *found) if found else (None, None, None)
        statm = Path("/proc/self/statm")
        if statm.is_file():
            pages = int(statm.read_text().split()[1])
            import resource

            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
            return "/proc/self/statm", pages * os.sysconf("SC_PAGE_SIZE"), peak
    except (OSError, ValueError, AttributeError):
        pass
    return None, None, None


def _mb(value: int | None) -> float | None:
    return None if value is None else round(value / (1024 * 1024), 1)


def _delta_mb(after: int | None, before: int | None) -> float | None:
    return None if after is None or before is None else round((after - before) / (1024 * 1024), 1)


# -- exécution -------------------------------------------------------------------------


def _empty_engine_result(spec: EngineSpec, preprocessing: Preprocessing, ablation: bool) -> dict[str, object]:
    return {
        "name": spec.name,
        "status": "ok",
        "code": None,
        "message": None,
        "engine": {key: None for key in ENGINE_DESCRIPTION_KEYS} | {"kind": spec.kind, "num_threads": spec.num_threads},
        "verifier": spec.params.payload(),
        "preprocessing": preprocessing.payload(),
        "ablation": ablation,
        "resources": {key: None for key in RESOURCE_KEYS},
        "enrollment": {},
        "at_engine_threshold": None,
        "sweep": [],
        "eer": None,
        "operating_points": {"zero_false_accept": None, "gate_zero_false_open": None},
        "gate_at_engine_threshold": None,
        "gate_sweep": [],
        "scenarios": [],
    }


def engine_preprocessing(manifest: Manifest, spec: EngineSpec, *, ablation: bool) -> Preprocessing:
    if spec.preprocessing is None:
        return manifest.preprocessing
    if not ablation:
        raise BenchmarkError(
            "ablation_required",
            f"Le moteur {spec.name} change le prétraitement : comparaison injuste, relancez avec --ablation.",
        )
    return _preprocessing(spec.preprocessing, f"engines[{spec.name}].preprocessing", manifest.preprocessing)


def _score_stats(trace: LabelledTrace) -> dict[str, object]:
    genuine, impostor = score_sets([trace])

    def mean(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 4) if values else None

    return {
        "owner_score_mean": mean(genuine),
        "owner_score_min": round(min(genuine), 4) if genuine else None,
        "non_owner_score_mean": mean(impostor),
        "non_owner_score_max": round(max(impostor), 4) if impostor else None,
    }


def run_engine(
    manifest: Manifest,
    spec: EngineSpec,
    *,
    thresholds: Sequence[float],
    audio: Mapping[Path, _Audio] | None = None,
    realtime: bool = False,
    include_hops: bool = False,
    ablation: bool = False,
    model_dir: Path | None = None,
    resolver: EngineResolver = resolve_engine,
    isolated: bool = False,
    gate_thresholds: Sequence[float] | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Un moteur sur tout le manifeste. Toute panne devient un statut, jamais un chiffre.

    Deux rejeux : le vérificateur seul (fenêtre par fenêtre, coût mesuré), puis
    — sauf `gate_thresholds=()` — la porte Solo Owner complète (capture,
    candidats acoustiques, réponses brèves, tampon de rejeu), qui dit ce que le
    fournisseur recevrait vraiment, à chaque seuil demandé.
    """

    say = progress or (lambda message: None)
    preprocessing = engine_preprocessing(manifest, spec, ablation=ablation)
    result = _empty_engine_result(spec, preprocessing, ablation)
    resources: dict[str, object] = result["resources"]  # type: ignore[assignment]
    resources["isolated"] = isolated
    audio = audio if audio is not None else load_audio(manifest)
    gc.collect()
    method, rss_before, _ = process_memory()
    resources["rss_method"] = method
    resources["rss_before_mb"] = _mb(rss_before)

    def failed(status: str, code: str, message: str) -> dict[str, object]:
        result.update(status=status, code=code, message=message)
        say(f"  {spec.name} : {status} [{code}] {message}")
        return result

    try:
        engine = resolver(spec, Path(model_dir or default_model_dir()))
    except EngineUnavailable as exc:
        return failed("unavailable", exc.code, str(exc))
    description = dict(engine.describe())
    result["engine"] = (
        {key: description.get(key) for key in ENGINE_DESCRIPTION_KEYS}
        | {"kind": spec.kind, "num_threads": description.get("num_threads", spec.num_threads)}
        | ({"extra": {k: v for k, v in description.items() if k not in ENGINE_DESCRIPTION_KEYS}} if set(description) - set(ENGINE_DESCRIPTION_KEYS) else {})
    )
    try:
        started = time.perf_counter()
        try:
            engine.verify()
        except Exception as exc:  # noqa: BLE001 - un modèle refusé est un état du moteur
            return failed("unavailable", getattr(exc, "code", "engine_model_mismatch"), str(exc))
        resources["model_verify_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
        started = time.perf_counter()
        try:
            engine.load()
        except Exception as exc:  # noqa: BLE001
            return failed("error", getattr(exc, "code", "engine_load_failed"), f"{type(exc).__name__}: {exc}")
        resources["model_load_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
        _, rss_load, _ = process_memory()
        resources["rss_after_load_mb"] = _mb(rss_load)
        resources["rss_load_delta_mb"] = _delta_mb(rss_load, rss_before)

        used = list(dict.fromkeys(scenario.profile for scenario in manifest.scenarios))
        references: dict[str, Any] = {}
        enroll_ms = 0.0
        for profile in used:
            clips = [(audio[path].samples, audio[path].rate) for path in manifest.profiles[profile]]
            started = time.perf_counter()
            try:
                references[profile], meta = engine.enroll(clips)
            except Exception as exc:  # noqa: BLE001
                return failed("error", getattr(exc, "code", "enrollment_failed"), f"profil {profile} : {exc}")
            enroll_ms += (time.perf_counter() - started) * 1000.0
            result["enrollment"][profile] = dict(meta)  # type: ignore[index]
        resources["enroll_ms_total"] = round(enroll_ms, 1)

        traces: list[LabelledTrace] = []
        scenario_rows: list[dict[str, object]] = []
        prepared: dict[str, Any] = {}
        cpu_ms = 0.0
        hop_ms: list[float] = []
        scoring_ms: list[float] = []
        lags: list[float] = []
        audio_ms = 0
        for profile in used:
            try:
                verifier = engine.open_verifier(
                    references[profile], profile_id=profile, params=spec.params, preprocessing=preprocessing
                )
            except Exception as exc:  # noqa: BLE001
                return failed("error", getattr(exc, "code", "engine_open_failed"), f"profil {profile} : {exc}")
            try:
                for scenario in (s for s in manifest.scenarios if s.profile == profile):
                    clip = audio[scenario.audio]
                    pcm = prepare_pcm(clip.samples, clip.rate, preprocessing, gain_db=scenario.gain_db)
                    prepared[scenario.name] = pcm
                    try:
                        replayed = replay(verifier, pcm, preprocessing.capture_rate, preprocessing.hop_ms, realtime=realtime)
                    except BenchmarkError as exc:
                        return failed("error", exc.code, f"{scenario.name} : {exc}")
                    except Exception as exc:  # noqa: BLE001 - un moteur qui lève est en panne
                        return failed("error", "engine_process_failed", f"{scenario.name} : {type(exc).__name__}: {exc}")
                    trace = label_trace(scenario.name, replayed.hops, scenario.intervals, manifest.evaluation, tags=scenario.tags)
                    traces.append(trace)
                    cpu_ms += replayed.cpu_ms
                    hop_ms += [hop.wall_ms for hop in replayed.hops]
                    scoring_ms += [hop.wall_ms for hop in replayed.hops if hop.scored]
                    lags += list(replayed.lag_ms)
                    audio_ms += len(replayed.hops) * preprocessing.hop_ms
                    single = metrics_at([trace], None, manifest.evaluation)
                    row: dict[str, object] = {
                        "name": scenario.name,
                        "profile": profile,
                        "tags": list(scenario.tags),
                        "gain_db": scenario.gain_db,
                        "duration_ms": clip.duration_ms,
                        "at_engine_threshold": {key: single[key] for key in SCENARIO_METRIC_KEYS},
                        **_score_stats(trace),
                    }
                    if include_hops:
                        row["hops"] = [
                            [h.start_ms, c.value, h.status, None if h.score is None else round(h.score, 4), h.detected, h.evidence_ms]
                            for h, c in zip(trace.hops, trace.classes)
                        ]
                    scenario_rows.append(row)
                    say(f"  {spec.name} · {scenario.name} : {len(replayed.hops)} fenêtres")
            finally:
                close = getattr(verifier, "close", None)
                if callable(close):
                    close()
        _, rss_run, peak = process_memory()

        # Porte Solo Owner : ce que le fournisseur recevrait vraiment, seuil par
        # seuil. Les empreintes sont mémorisées d'un seuil à l'autre (même
        # audio) ; le coût mesuré plus haut, lui, reste celui du moteur seul.
        wanted = list(thresholds if gate_thresholds is None else gate_thresholds)
        if wanted:
            wanted.append(float(spec.params.threshold))
        engine_threshold = round(float(spec.params.threshold), 6)
        gate_rows: list[dict[str, object]] = []
        gate_scenarios: dict[str, dict[str, object]] = {}
        memoize = getattr(engine, "memoize", None)
        if callable(memoize):
            memoize(True)
        try:
            for value in sorted({round(float(item), 6) for item in wanted}):
                params = replace(spec.params, threshold=value)
                gate_traces: list[GateTrace] = []
                for profile in used:
                    for scenario in (s for s in manifest.scenarios if s.profile == profile):
                        verifier = engine.open_verifier(
                            references[profile], profile_id=profile, params=params, preprocessing=preprocessing
                        )
                        gate_traces.append(
                            replay_gate(
                                verifier,
                                prepared[scenario.name],
                                preprocessing.capture_rate,
                                hop_ms=preprocessing.hop_ms,
                                owner_buffer_ms=params.owner_buffer_ms,
                                name=scenario.name,
                                intervals=scenario.intervals,
                                tags=scenario.tags,
                            )
                        )
                gate_rows.append(gate_metrics(gate_traces, value, manifest.evaluation))
                if value == engine_threshold:
                    gate_scenarios = {
                        trace.name: gate_metrics([trace], value, manifest.evaluation) for trace in gate_traces
                    }
                say(f"  {spec.name} · porte au seuil {value}")
        except BenchmarkError as exc:
            return failed("error", exc.code, f"porte : {exc}")
        except Exception as exc:  # noqa: BLE001 - un moteur qui lève est en panne
            return failed("error", "gate_replay_failed", f"porte : {type(exc).__name__}: {exc}")
        finally:
            if callable(memoize):
                memoize(False)
        for row in scenario_rows:
            row["gate"] = gate_scenarios.get(str(row["name"]))
    finally:
        try:
            engine.close()
        except Exception:  # noqa: BLE001 - fermeture au mieux
            pass

    hops = len(hop_ms)
    scoring = len(scoring_ms) if any(t.hops and t.hops[0].scored is not None for t in traces) else None
    resources.update(
        rss_after_run_mb=_mb(rss_run),
        rss_steady_delta_mb=_delta_mb(rss_run, rss_before),
        peak_rss_mb=_mb(peak),
        audio_ms=audio_ms,
        hops=hops,
        scoring_hops=scoring,
        cpu_ms_total=round(cpu_ms, 1),
        cpu_ms_per_hop_mean=round(cpu_ms / hops, 3) if hops else None,
        cpu_ms_per_scoring_hop_mean=round(cpu_ms / scoring, 2) if scoring else None,
        cpu_pct_one_core=round(100.0 * cpu_ms / audio_ms, 2) if audio_ms else None,
        hop_ms=timing_summary(hop_ms),
        scoring_hop_ms=timing_summary(scoring_ms) if scoring is not None else None,
        realtime_lag_ms=timing_summary(lags) if realtime else None,
    )
    sweep = threshold_sweep(traces, thresholds, manifest.evaluation)
    result.update(
        at_engine_threshold=metrics_at(traces, None, manifest.evaluation) | {"threshold": spec.params.threshold},
        sweep=sweep,
        eer=equal_error_rate(*score_sets(traces)),
        operating_points={
            "zero_false_accept": zero_false_accept_point(sweep),
            "gate_zero_false_open": gate_zero_false_open_point(gate_rows),
        },
        gate_at_engine_threshold=next(
            (row for row in gate_rows if row["threshold"] == round(engine_threshold, 4)), None
        ),
        gate_sweep=gate_rows,
        scenarios=scenario_rows,
    )
    return result


def _host() -> dict[str, object]:
    import numpy

    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
        "numpy": numpy.__version__,
    }


def _display_path(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return Path(path).name


def run_benchmark(
    manifest: Manifest,
    *,
    thresholds: Sequence[float] | None = None,
    realtime: bool = False,
    include_hops: bool = False,
    ablation: bool = False,
    isolate: bool = False,
    model_dir: Path | None = None,
    resolver: EngineResolver = resolve_engine,
    gate_thresholds: Sequence[float] | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Tous les moteurs du manifeste, sur le même audio et le même prétraitement."""

    say = progress or (lambda message: None)
    if not manifest.engines:
        raise ManifestError("manifest_no_engine", "Aucun moteur à comparer (engines vide, ni --sherpa-model).")
    sweep = check_thresholds(thresholds if thresholds is not None else manifest.thresholds)
    for spec in manifest.engines:
        engine_preprocessing(manifest, spec, ablation=ablation)  # refus d'une ablation implicite, avant tout calcul
    audio = load_audio(manifest)
    engines: list[dict[str, object]] = []
    for spec in manifest.engines:
        say(f"{spec.name} ({spec.kind}{' ' + spec.model if spec.model else ''})…")
        started = time.perf_counter()
        if isolate:
            outcome = _run_isolated(
                manifest, spec, thresholds=sweep, realtime=realtime, include_hops=include_hops, ablation=ablation,
                model_dir=model_dir, gate_thresholds=gate_thresholds,
                audio_ms=sum(audio[s.audio].duration_ms for s in manifest.scenarios),
            )  # fmt: skip
        else:
            outcome = run_engine(
                manifest, spec, thresholds=sweep, audio=audio, realtime=realtime, include_hops=include_hops,
                ablation=ablation, model_dir=model_dir, resolver=resolver, gate_thresholds=gate_thresholds,
                progress=progress,
            )  # fmt: skip
        engines.append(outcome)
        say(f"{spec.name} : {outcome['status']} en {time.perf_counter() - started:.1f} s")
    synthetic = manifest.evidence == "synthetic"
    return {
        "schema": RESULT_SCHEMA,
        "schema_version": RESULT_SCHEMA_VERSION,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        "evidence": manifest.evidence,
        "disclaimer": SYNTHETIC_DISCLAIMER if synthetic else None,
        "mode": "realtime" if realtime else "offline",
        "ablation": ablation,
        "manifest": {
            "name": manifest.name,
            "path": _display_path(manifest.path),
            "sha256": manifest.sha256,
            "profiles": len(manifest.profiles),
            "scenarios": len(manifest.scenarios),
            "audio_ms": sum(audio[s.audio].duration_ms for s in manifest.scenarios),
            "notes": manifest.notes,
        },
        "host": _host(),
        "preprocessing": manifest.preprocessing.payload(),
        "evaluation": manifest.evaluation.payload(),
        "thresholds": sweep,
        "engines": engines,
    }


#: Temps fixe accordé à un moteur isolé quelle que soit la durée de l'audio :
#: démarrage de l'interpréteur, vérification SHA-256, chargement du modèle et
#: enrôlement (~10 s observées, marge large pour un disque froid).
ISOLATED_TIMEOUT_BASE_S = 300.0
#: Multiple de la durée d'audio accordé à chaque passe de rejeu (notation, puis
#: une passe de porte par seuil). Le rejeu hors ligne est bien plus rapide que
#: le temps réel (~0,05 × sur le portable de référence) : ×2 laisse 40 fois la
#: marge, ×4 en mode temps réel où la passe dure au moins l'audio lui-même.
ISOLATED_TIMEOUT_PER_AUDIO_OFFLINE = 2.0
ISOLATED_TIMEOUT_PER_AUDIO_REALTIME = 4.0


def isolated_timeout_s(audio_ms: int, *, realtime: bool = False, passes: int = 1) -> float:
    """Délai maximal d'un moteur isolé, dérivé de l'audio à rejouer.

    Large mais fini : un enfant bloqué (chargement ONNX qui ne rend jamais la
    main) doit être tué et rapporté `engine_subprocess_failed`, pas figer la
    campagne en silence — `capture_output=True` masque toute trace de vie.
    """

    audio_s = max(0.0, float(audio_ms) / 1000.0)
    factor = ISOLATED_TIMEOUT_PER_AUDIO_REALTIME if realtime else ISOLATED_TIMEOUT_PER_AUDIO_OFFLINE
    return ISOLATED_TIMEOUT_BASE_S + max(1, int(passes)) * audio_s * factor


def _run_isolated(
    manifest: Manifest,
    spec: EngineSpec,
    *,
    thresholds: Sequence[float],
    realtime: bool,
    include_hops: bool,
    ablation: bool,
    model_dir: Path | None,
    gate_thresholds: Sequence[float] | None = None,
    audio_ms: int = 0,
) -> dict[str, object]:
    """Un moteur dans un processus neuf : mémoire et temps de chargement non pollués par les autres."""

    with tempfile.TemporaryDirectory(prefix="jarvis-speaker-bench-") as tmp:
        effective = Path(tmp) / "manifest.json"
        effective.write_text(json.dumps(replace(manifest, engines=(spec,)).payload(), ensure_ascii=False), encoding="utf-8")
        out = Path(tmp) / "engine.json"
        command = [
            sys.executable, "-m", "jarvis.runtime.speaker_benchmark", "run", str(effective),
            "--engine-json", str(out), "--no-isolate", "--thresholds", ",".join(str(t) for t in thresholds),
        ]  # fmt: skip
        command += ["--realtime"] * realtime + ["--include-hops"] * include_hops + ["--ablation"] * ablation
        if model_dir is not None:
            command += ["--model-dir", str(model_dir)]
        if gate_thresholds is not None:
            command += ["--gate-thresholds", ",".join(str(value) for value in gate_thresholds) or "none"]
        gate_passes = len(thresholds) if gate_thresholds is None else len(gate_thresholds)
        timeout = isolated_timeout_s(audio_ms, realtime=realtime, passes=1 + gate_passes)
        try:
            completed = subprocess.run(
                command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
            )  # fmt: skip
        except subprocess.TimeoutExpired as expired:
            # L'enfant est déjà tué par `run`. Même statut qu'un enfant mort :
            # le moteur est rapporté en panne, jamais inventé.
            result = _empty_engine_result(spec, manifest.preprocessing, ablation)
            stderr = expired.stderr if isinstance(expired.stderr, str) else ""
            result.update(
                status="error",
                code="engine_subprocess_failed",
                message=f"délai dépassé après {timeout:.0f} s: {stderr.strip()[-600:]}",
            )
            return result
        if out.is_file():
            outcome = json.loads(out.read_text(encoding="utf-8"))
            outcome["resources"]["isolated"] = True
            return outcome
        result = _empty_engine_result(spec, manifest.preprocessing, ablation)
        result.update(
            status="error",
            code="engine_subprocess_failed",
            message=f"exit {completed.returncode}: {(completed.stderr or '').strip()[-600:]}",
        )
        return result


# -- résultats ----------------------------------------------------------------------------


def _cell(value: object) -> object:
    return "" if value is None else value


def csv_rows(result: Mapping[str, object]) -> list[dict[str, object]]:
    """Une ligne par (moteur, décision) : `engine` = seuil propre du moteur, `sweep` = seuil balayé."""

    rows: list[dict[str, object]] = []
    for engine in result["engines"]:  # type: ignore[union-attr]
        desc = engine["engine"]
        resources = engine["resources"]
        eer = engine["eer"] or {}
        scoring = resources.get("scoring_hop_ms") or {}
        base = {
            "schema_version": result["schema_version"],
            "manifest": result["manifest"]["name"],  # type: ignore[index]
            "evidence": result["evidence"],
            "engine_name": engine["name"],
            "status": engine["status"],
            "code": engine["code"],
            "engine_id": desc.get("id"),
            "model_id": desc.get("model_id"),
            "model_sha256": desc.get("model_sha256"),
            "evidence_ms": engine["verifier"]["evidence_ms"],
            "engine_threshold": engine["verifier"]["threshold"],
            "eer": eer.get("eer"),
            "eer_threshold": eer.get("threshold"),
            "cpu_ms_per_scoring_hop_mean": resources.get("cpu_ms_per_scoring_hop_mean"),
            "scoring_hop_ms_p50": scoring.get("p50"),
            "scoring_hop_ms_p95": scoring.get("p95"),
            "cpu_pct_one_core": resources.get("cpu_pct_one_core"),
            "model_load_ms": resources.get("model_load_ms"),
            "rss_steady_delta_mb": resources.get("rss_steady_delta_mb"),
        }
        blocks: list[tuple[str, Mapping[str, object], tuple[str, ...]]] = []
        if engine["at_engine_threshold"]:
            blocks.append(("engine", engine["at_engine_threshold"], METRIC_KEYS))
        blocks += [("sweep", row, METRIC_KEYS) for row in engine["sweep"]]
        blocks += [("gate", row, GATE_METRIC_KEYS) for row in engine.get("gate_sweep") or []]
        if not blocks:
            rows.append({column: _cell(base.get(column)) for column in CSV_COLUMNS})
            continue
        for decision, metrics, keys in blocks:
            merged = {**base, **{key: metrics.get(key) for key in keys}, "decision": decision}
            rows.append({column: _cell(merged.get(column)) for column in CSV_COLUMNS})
    return rows


def csv_text(result: Mapping[str, object]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(CSV_COLUMNS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(csv_rows(result))
    return buffer.getvalue()


def _fmt(value: object, digits: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _pct(value: object) -> str:
    return "—" if value is None else f"{100.0 * float(value):.1f} %"  # type: ignore[arg-type]


def markdown_summary(result: Mapping[str, object]) -> str:
    """Résumé lisible (anglais, comme la documentation d'exploitation)."""

    manifest = result["manifest"]
    lines = [f"# Speaker verification benchmark — {manifest['name']}", ""]  # type: ignore[index]
    if result.get("disclaimer"):
        lines += [f"> **{result['disclaimer']}**", ""]
    host = result["host"]
    lines += [
        f"- Generated: {result['generated_at']} · schema `{result['schema']}` v{result['schema_version']} · mode "
        f"{result['mode']} · evidence **{result['evidence']}**" + (" · **ABLATION**" if result["ablation"] else ""),
        f"- Manifest: `{manifest['path']}` (SHA-256 `{str(manifest['sha256'])[:12]}…`), {manifest['profiles']} "  # type: ignore[index]
        f"profile(s), {manifest['scenarios']} scenario(s), {int(manifest['audio_ms']) / 1000:.0f} s of audio",  # type: ignore[index]
        f"- Host: {host['platform']} · {host['processor']} · {host['cpu_count']} logical CPUs · Python {host['python']}",  # type: ignore[index]
        f"- Preprocessing (identical for all engines): capture {result['preprocessing']['capture_rate']} Hz, "  # type: ignore[index]
        f"{result['preprocessing']['hop_ms']} ms hops, energy gate +{result['preprocessing']['gate_margin_db']} dB "  # type: ignore[index]
        f"over floor (min {result['preprocessing']['gate_absolute_min_db']} dBFS), no AEC / noise reduction",  # type: ignore[index]
        f"- Scoring: {json.dumps(result['evaluation'])}",
        "",
        "## Engines at their configured threshold",
        "",
        "| Engine | Model (dim) | Thr. | FAR | FRR | Owner miss | Confirm P50 / P95 ms | Overlap confirmed | "
        "Non-owner FA events | EER (thr.) | Zero-FA thr. → FRR, P95 | Scoring hop P50 / P95 ms | CPU % core | Load ms | RSS Δ MB |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for engine in result["engines"]:  # type: ignore[union-attr]
        desc, res = engine["engine"], engine["resources"]
        if engine["status"] != "ok":
            lines.append(f"| {engine['name']} | {_fmt(desc.get('model_id'))} | — | {engine['status']}: `{engine['code']}` |" + " — |" * 11)
            continue
        m = engine["at_engine_threshold"]
        eer = engine["eer"] or {}
        zero = engine["operating_points"]["zero_false_accept"]
        scoring = res.get("scoring_hop_ms") or {}
        zero_text = "none in sweep" if zero is None else f"{zero['threshold']} → {_pct(zero['frr'])}, {_fmt(zero['confirm_ms_p95'], 0)}"
        lines.append(
            f"| {engine['name']} | {desc.get('model_id')} ({desc.get('embedding_dim')}) | {m['threshold']} | {_pct(m['far'])} | "
            f"{_pct(m['frr'])} | {_pct(m['owner_miss_rate'])} | {_fmt(m['confirm_ms_p50'], 0)} / {_fmt(m['confirm_ms_p95'], 0)} | "
            f"{m['overlap_events_confirmed']}/{m['overlap_events']} | {m['non_owner_events_false_accepted']}/{m['non_owner_events']} | "
            f"{_pct(eer.get('eer'))} ({_fmt(eer.get('threshold'))}) | {zero_text} | "
            f"{_fmt(scoring.get('p50'), 1)} / {_fmt(scoring.get('p95'), 1)} | {_fmt(res.get('cpu_pct_one_core'), 1)} | "
            f"{_fmt(res.get('model_load_ms'), 0)} | {_fmt(res.get('rss_steady_delta_mb'), 1)} |"
        )
    gate_engines = [engine for engine in result["engines"] if engine.get("gate_at_engine_threshold")]  # type: ignore[union-attr]
    if gate_engines:
        lines += [
            "",
            "## Solo Owner input gate (what the provider would really receive)",
            "",
            "| Engine | Thr. | Owner turns forwarded | Miss | Confirm P50 / P95 ms | Short replies | Start lost P95 ms | "
            "Owner audio forwarded | Openings (false) | Non-owner events opened | Non-owner leaked ms (max run) | "
            "Noise ms | Replays clamped | Zero-false-open thr. |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for engine in gate_engines:
            g = engine["gate_at_engine_threshold"]
            zero = engine["operating_points"].get("gate_zero_false_open")
            zero_text = "none in sweep" if zero is None else f"{zero['threshold']} → miss {_pct(zero['owner_gate_miss_rate'])}"
            lines.append(
                f"| {engine['name']} | {g['threshold']} | {g['owner_events_forwarded']}/{g['owner_events']} | "
                f"{_pct(g['owner_gate_miss_rate'])} | {_fmt(g['gate_confirm_ms_p50'], 0)} / {_fmt(g['gate_confirm_ms_p95'], 0)} | "
                f"{g['short_confirmations']} | {_fmt(g['owner_start_lost_ms_p95'], 0)} | {_pct(g['owner_forwarded_ratio'])} | "
                f"{g['openings']} ({g['false_opens']}) | {g['non_owner_events_opened']}/{g['non_owner_events']} | "
                f"{g['non_owner_forwarded_ms']} ({g['non_owner_run_ms_max']}) | {g['noise_forwarded_ms']} | "
                f"{g['replays_clamped']} | {zero_text} |"
            )
        lines += [
            "",
            "Gate replay = the production path (near-end candidates, rolling verification, end-of-candidate short "
            "replies, handover sub-window, owner replay ring), JARVIS silent. A false open is a flow opening whose "
            "replayed span holds no owner speech; leaked ms are non-owner-only audio forwarded after a handover.",
        ]
    lines += [
        "",
        "FAR = accepted / judged hops where only another voice speaks; FRR = rejected / judged hops where only the "
        "owner speaks; owner miss = owner events never confirmed; confirm = first accepted hop end − owner onset; "
        "EER from all judged hop scores; zero-FA thr. = lowest swept threshold with no false accept at all "
        "(hops, events, noise). Definitions: `docs/SPEAKER_BENCHMARK.md`.",
        "",
    ]
    return "\n".join(lines)


def write_outputs(result: Mapping[str, object], out_dir: Path, basename: str) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {kind: out_dir / f"{basename}.{kind}" for kind in ("json", "csv", "md")}
    paths["json"].write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths["csv"].write_text(csv_text(result), encoding="utf-8", newline="")
    paths["md"].write_text(markdown_summary(result), encoding="utf-8")
    return paths


# -- ligne de commande ---------------------------------------------------------------------


def _parse_threshold_list(text: str) -> list[float]:
    try:
        return check_thresholds(float(part) for part in text.split(",") if part.strip())
    except ValueError:
        raise BenchmarkError("thresholds_invalid", f"Liste de seuils invalide « {text} ».") from None


def _expand_engines(manifest: Manifest, args: argparse.Namespace, model_dir: Path) -> Manifest:
    from jarvis.adapters import sherpa_model_catalog as catalog

    engines = list(manifest.engines)
    for requested in args.sherpa_model or []:
        if requested in {"all", "downloaded"}:
            keys = [m.key for m in catalog.MODELS if requested == "all" or m.path(model_dir).is_file()]
        else:
            model = catalog.find_model(requested)
            keys = [model.key if model else requested]
        for key in keys:
            if all(engine.name != key for engine in engines):
                engines.append(_engine({"name": key, "kind": "sherpa-onnx", "model": key}, f"--sherpa-model {key}"))
    if args.engine:
        unknown = sorted(set(args.engine) - {engine.name for engine in engines})
        if unknown:
            raise BenchmarkError("engine_unknown", f"Moteur(s) absent(s) du manifeste : {unknown}.")
        engines = [engine for engine in engines if engine.name in set(args.engine)]
    if args.evidence_ms:
        values = [int(part) for part in args.evidence_ms.split(",") if part.strip()]
        engines = [
            replace(
                engine,
                name=f"{engine.name}@ev{value}",
                params=replace(
                    engine.params,
                    evidence_ms=value,
                    # La règle brève suit la production : min(600, preuve − 100).
                    short_evidence_ms=(
                        None
                        if engine.params.short_evidence_ms is None
                        else min(engine.params.short_evidence_ms, max(0, value - 100)) or None
                    ),
                ),
            )
            for engine in engines
            for value in values
        ]
    if args.short_evidence_ms is not None:
        value = int(args.short_evidence_ms)
        engines = [
            replace(engine, params=replace(engine.params, short_evidence_ms=value or None)) for engine in engines
        ]
    if args.short_margin is not None:
        engines = [replace(engine, params=replace(engine.params, short_margin=float(args.short_margin))) for engine in engines]
    if args.owner_buffer_ms is not None:
        engines = [replace(engine, params=replace(engine.params, owner_buffer_ms=int(args.owner_buffer_ms))) for engine in engines]
    if args.threshold is not None:
        engines = [replace(engine, params=replace(engine.params, threshold=float(args.threshold))) for engine in engines]
    preprocessing = manifest.preprocessing
    if args.capture_rate:
        if not args.ablation:
            raise BenchmarkError("ablation_required", "--capture-rate change le prétraitement : ajoutez --ablation.")
        preprocessing = replace(preprocessing, capture_rate=int(args.capture_rate))
    evaluation = manifest.evaluation
    if args.transition_guard_ms is not None:
        # Notation seulement (l'audio rejoué ne change pas) : pas une ablation.
        try:
            evaluation = replace(evaluation, transition_guard_ms=int(args.transition_guard_ms))
        except ValueError as exc:
            raise BenchmarkError("manifest_invalid", f"--transition-guard-ms : {exc}.") from None
    return replace(manifest, engines=tuple(engines), preprocessing=preprocessing, evaluation=evaluation)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="benchmark_speaker_verification",
        description="Repeatable speaker-verification benchmark (JARVIS Solo Owner, Task 09).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Replay a scenario manifest through one or more engines")
    run.add_argument("manifest", type=Path)
    run.add_argument("--engine", action="append", help="Only this manifest engine (repeatable)")
    run.add_argument("--sherpa-model", action="append", help="Add a catalog model (key, 'downloaded' or 'all')")
    run.add_argument("--thresholds", help="Comma-separated threshold list for the sweep")
    run.add_argument("--threshold-range", help="Sweep start:stop:step (inclusive)")
    run.add_argument("--threshold", type=float, help="Override every engine's own decision threshold")
    run.add_argument("--evidence-ms", help="Comma-separated evidence windows: one engine variant per value")
    run.add_argument(
        "--transition-guard-ms", type=int, help="Scoring: exclude hops whose last N ms straddle a label change (0 = strict)"
    )
    run.add_argument(
        "--gate-thresholds",
        help="Solo Owner gate replay thresholds ('none' to skip it; default: the swept thresholds)",
    )
    run.add_argument("--short-evidence-ms", help="Short-reply / handover window per engine ('0' disables the rule)")
    run.add_argument("--short-margin", type=float, help="Short-reply and handover margin around the threshold")
    run.add_argument("--owner-buffer-ms", type=int, help="Owner replay buffer of the capture (gate replay)")
    run.add_argument("--realtime", action="store_true", help="Feed hops at real-time cadence (default: accelerated)")
    run.add_argument("--ablation", action="store_true", help="Allow per-engine / global preprocessing changes")
    run.add_argument("--capture-rate", type=int, help="Ablation: capture rate instead of the manifest's")
    run.add_argument("--include-hops", action="store_true", help="Keep per-hop scores in the JSON")
    run.add_argument("--no-isolate", dest="isolate", action="store_false", help="Run every engine in this process")
    run.add_argument("--model-dir", type=Path, help="Model directory (default: runtime/speaker-verification/models)")
    run.add_argument("--out-dir", type=Path, help="Output directory (default: runtime/speaker-verification/benchmark/results)")
    run.add_argument("--basename", help="Output file stem (default: <date>-<manifest name>)")
    run.add_argument("--quiet", action="store_true")
    run.add_argument("--engine-json", type=Path, help=argparse.SUPPRESS)
    gen = sub.add_parser("generate-synthetic", help="Generate redistributable TTS fixtures + manifest (Windows)")
    gen.add_argument("--out", type=Path, help="Output directory (default: runtime/speaker-verification/benchmark/synthetic)")
    gen.add_argument("--owners", type=int, default=3, help="Number of voices used in turn as the owner")
    gen.add_argument("--seed", type=int, default=20260911, help="Seed for noise, clicks and reverberation")
    gen.add_argument("--voices", help="Comma-separated voice keys to use (default: every installed voice)")
    gen.add_argument("--only", help="Comma-separated scenario kinds (default: all)")
    models = sub.add_parser("models", help="List catalog models, or download them (SHA-256 checked)")
    models.add_argument("--download", action="append", help="Model key to download ('all' for every model)")
    models.add_argument("--model-dir", type=Path)
    return parser


def _run_command(args: argparse.Namespace) -> int:
    say = (lambda message: None) if args.quiet else (lambda message: print(message, file=sys.stderr, flush=True))
    model_dir = Path(args.model_dir) if args.model_dir else default_model_dir()
    manifest = _expand_engines(load_manifest(args.manifest), args, model_dir)
    thresholds: list[float] | None = None
    if args.thresholds and args.threshold_range:
        raise BenchmarkError("thresholds_invalid", "--thresholds ou --threshold-range, pas les deux.")
    if args.thresholds:
        thresholds = _parse_threshold_list(args.thresholds)
    elif args.threshold_range:
        thresholds = thresholds_from_range(args.threshold_range)
    gate_thresholds: list[float] | None = None
    if args.gate_thresholds:
        gate_thresholds = [] if args.gate_thresholds.strip().lower() == "none" else _parse_threshold_list(args.gate_thresholds)
    if args.engine_json:
        # Sous-processus d'isolation : un seul moteur, résultat brut.
        if len(manifest.engines) != 1:
            raise BenchmarkError("engine_unknown", "--engine-json attend exactement un moteur.")
        outcome = run_engine(
            manifest, manifest.engines[0], thresholds=check_thresholds(thresholds or manifest.thresholds),
            realtime=args.realtime, include_hops=args.include_hops, ablation=args.ablation, model_dir=model_dir,
            isolated=True, gate_thresholds=gate_thresholds, progress=say,
        )  # fmt: skip
        args.engine_json.write_text(json.dumps(outcome, ensure_ascii=False), encoding="utf-8")
        return 0
    result = run_benchmark(
        manifest, thresholds=thresholds, realtime=args.realtime, include_hops=args.include_hops,
        ablation=args.ablation, isolate=args.isolate, model_dir=model_dir, gate_thresholds=gate_thresholds,
        progress=say,
    )  # fmt: skip
    out_dir = args.out_dir or default_runtime_root() / "speaker-verification" / "benchmark" / "results"
    basename = args.basename or f"{_dt.date.today().isoformat()}-{manifest.name}"
    paths = write_outputs(result, out_dir, basename)
    print(markdown_summary(result))
    for kind, path in paths.items():
        print(f"{kind}: {path}")
    return 0 if all(engine["status"] == "ok" for engine in result["engines"]) else 1  # type: ignore[union-attr]


def _models_command(args: argparse.Namespace) -> int:
    from jarvis.adapters import sherpa_model_catalog as catalog

    model_dir = Path(args.model_dir) if args.model_dir else default_model_dir()
    wanted = args.download or []
    if wanted:
        specs = list(catalog.MODELS) if "all" in wanted else [catalog.find_model(key) for key in wanted]
        if any(spec is None for spec in specs):
            raise BenchmarkError("engine_unknown_model", f"Modèle(s) inconnu(s) : {wanted}.")
        for spec in specs:
            path = catalog.download_spec(spec, model_dir)  # type: ignore[arg-type]
            print(f"ok  {spec.key}: {path} (SHA-256 {spec.sha256[:12]}…, {spec.license})")  # type: ignore[union-attr]
        return 0
    for spec in catalog.MODELS:
        present = "present" if spec.path(model_dir).is_file() else "missing"
        print(f"{spec.key:32} {present:8} dim {spec.dim:4} {spec.size / 1e6:6.1f} MB  {spec.license:10} {spec.model_id}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "run":
            return _run_command(args)
        if args.command == "models":
            return _models_command(args)
        from jarvis.runtime.speaker_benchmark_fixtures import generate_synthetic

        out = args.out or default_runtime_root() / "speaker-verification" / "benchmark" / "synthetic"
        manifest = generate_synthetic(
            Path(out),
            owners=args.owners,
            seed=args.seed,
            voice_keys=[key.strip() for key in args.voices.split(",") if key.strip()] if args.voices else None,
            only=[kind.strip() for kind in args.only.split(",") if kind.strip()] if args.only else None,
            progress=lambda message: print(message, file=sys.stderr),
        )
        print(f"manifest: {manifest}")
        return 0
    except BenchmarkError as exc:
        print(f"{exc} [{exc.code}]", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - erreurs de modèle (code stable) comprises
        code = getattr(exc, "code", None)
        if code is None:
            raise
        print(f"{exc} [{code}]", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
