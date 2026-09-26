"""Résumés du banc d'essai Bare Hands : la liste blanche côté serveur, et le rangement.

Tâche ``jarvis-bare-hands-adaptive-calibration-benchmark``, Slice 08
(`docs/barehands-contracts.md` § 17, décisions 40, 41 et 64).

**Ce qui se range : des résultats de banc du contrat, rien d'autre.** Un
résultat porte, par exercice, les métriques **brutes** que le déroulé a
mesurées (des nombres ou ``null``), la graine, la classe de plan, l'instant du
run et l'identité du profil mesuré (source, essai, empreinte). Jamais une
image, un point de main, une trace, un score : les dimensions et le score se
recalculent dans la page (`scoreResult`) — les ranger ferait une seconde
vérité (décision 40).

**Pourquoi ce miroir.** La décision 42 le promettait « avec son premier
lecteur » : l'avant/après doit survivre au rechargement de la page, donc le
serveur range, et une route ouverte ne peut pas se fier à la bonne volonté de
l'appelant. Même partage des rôles que `barehands_trace` : le serveur
**reconstruit** chaque clé depuis une valeur lue par un lecteur typé, et
**refuse** une clé qu'il ne connaît pas avec un code (``X-Jarvis-Error-Code``).
Les tables (exercices, métriques, bornes, sources, classes) sont tenues en
parité avec `control_center_barehands_contracts.js` par un test sous node.

Rangement : ``<runtime_root>/barehands-benchmarks.json``, au plus
``SUMMARY_MAX`` résumés (les plus anciens par ``runAt`` sortent), écriture
atomique. ``DELETE`` efface tout (l'utilisateur peut toujours reprendre ce qui
a été rangé sur lui).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
STORE_SCHEMA = "jarvis.barehands.benchmarks"
STORE_SCHEMA_VERSION = 1
STORE_FILENAME = "barehands-benchmarks.json"
#: Au plus vingt résumés : de quoi comparer un avant et plusieurs après sur
#: plusieurs calibrations, pas un historique de la personne.
SUMMARY_MAX = 20

PLAN_CLASSES = ("bh-bench-1",)
PLAN_CLASS = PLAN_CLASSES[0]
PROFILE_SOURCES = ("defaults", "saved", "trial")
EXERCISES_MAX = 24
TRIALS_MAX = 50

#: Les métriques brutes de chaque exercice (`BENCHMARK_EXERCISE_METRICS`).
EXERCISE_METRICS: dict[str, tuple[str, ...]] = {
    "target_acquisition": ("acquisition_ms", "missed_click_count", "wrong_target_count",
                           "reacquisition_count", "press_latency_ms"),
    "no_click_tracking": ("false_click_count", "false_press_rate", "false_secondary_press_rate",
                          "unintended_target_rate", "unintended_pointer_rate", "pointer_jitter_px"),
    "nearby_targets": ("acquisition_ms", "wrong_target_count", "target_ambiguity", "reacquisition_count"),
    "drag_drop": ("drag_success_rate", "premature_drop_count", "placement_error_px", "release_latency_ms"),
    "moving_target": ("acquisition_ms", "pointer_lag_ms", "missed_click_count", "reacquisition_count"),
    "chained": ("transition_ms", "missed_click_count", "wrong_target_count", "premature_drop_count",
                "release_latency_ms"),
}

#: Bornes de valeur de chaque métrique de banc (`CALIBRATION_METRIC`) :
#: ``(min, max | None, entier, par essai)``.
METRIC_BOUNDS: dict[str, tuple[float, float | None, bool, bool]] = {
    "press_latency_ms": (-2000, 5000, False, False),
    "release_latency_ms": (-2000, 5000, False, False),
    "false_press_rate": (0, None, False, False),
    "false_secondary_press_rate": (0, None, False, False),
    "unintended_target_rate": (0, None, False, False),
    "unintended_pointer_rate": (0, None, False, False),
    "pointer_jitter_px": (0, None, False, False),
    "pointer_lag_ms": (0, None, False, False),
    "acquisition_ms": (0, None, False, False),
    "missed_click_count": (0, None, True, True),
    "wrong_target_count": (0, None, True, True),
    "false_click_count": (0, None, True, False),
    "premature_drop_count": (0, None, True, True),
    "reacquisition_count": (0, None, True, False),
    "placement_error_px": (0, None, False, False),
    "target_ambiguity": (0, 1, False, False),
    "drag_success_rate": (0, 1, False, False),
    "transition_ms": (0, None, False, False),
}

RESULT_KEYS = ("schemaVersion", "kind", "ref", "seed", "planClass", "runAt", "profileSource", "trialRef",
               "profileFingerprint", "exercises")
EXERCISE_KEYS = ("ref", "kind", "trials", "metrics")
REF_PATTERN = re.compile(r"^([a-z]{2})-(\d{1,9})$")
FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{8,64}$")
SEED_MAX = 4294967295


class BarehandsBenchmarkError(ValueError):
    """Un résumé refusé, avec le code que l'en-tête et le journal portent."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _reject(code: str, message: str) -> None:
    raise BarehandsBenchmarkError(code, message)


def _describe(raw: Any) -> str:
    """Ce qu'un refus dit d'une valeur venue de l'appelant : borné (patron
    `barehands_trace._describe`)."""

    if raw is None:
        return "absent"
    if isinstance(raw, bool):
        return "un booléen"
    if isinstance(raw, (int, float)):
        return f"« {raw!s} »"
    if isinstance(raw, str):
        return f"« {raw} »" if len(raw) <= 48 else f"une chaîne de {len(raw)} caractères"
    if isinstance(raw, list):
        return f"une liste de {len(raw)} éléments"
    if isinstance(raw, dict):
        return f"un objet de {len(raw)} clés"
    return f"une valeur de type {type(raw).__name__}"


def _number(raw: Any) -> float | None:
    """Un nombre fini, ou ``None`` ; ``bool`` n'est pas un nombre ici."""

    if raw is None or isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    return None if math.isnan(value) or math.isinf(value) else value


def _only_keys(source: dict, allowed: tuple[str, ...], label: str) -> None:
    unknown = sorted(key for key in source if key not in allowed)
    if unknown:
        _reject("barehands_session_key_unknown",
                f"{label} : clé(s) inconnue(s) {', '.join(_describe(k) for k in unknown[:4])}.")


def _integer(raw: Any, code: str, label: str, low: int, high: int) -> int:
    value = _number(raw)
    if value is None or not float(value).is_integer() or not low <= value <= high:
        _reject(code, f"{label} : entier de {low} à {high} attendu, reçu {_describe(raw)}.")
    return int(value)


def _ref(raw: Any, kind: str, label: str) -> str:
    match = REF_PATTERN.match(raw) if isinstance(raw, str) else None
    if not match or match.group(1) != kind:
        _reject("barehands_session_ref_invalid", f"{label} : référence « {kind}-N » attendue, reçu {_describe(raw)}.")
    return raw


def _metrics(raw: Any, kind: str, trials: int) -> dict[str, float | int | None]:
    if not isinstance(raw, dict):
        _reject("barehands_benchmark_invalid", "metrics : objet attendu.")
    expected = EXERCISE_METRICS[kind]
    _only_keys(raw, expected, f"metrics de {kind}")
    out: dict[str, float | int | None] = {}
    for name in expected:
        if name not in raw:
            _reject("barehands_benchmark_metric_missing",
                    f"{kind} rend {name} (null si non mesurée) : deux résultats doivent avoir la même forme.")
        given = raw[name]
        if given is None:
            out[name] = None
            continue
        value = _number(given)
        low, high, integer, per_trial = METRIC_BOUNDS[name]
        if value is None or value < low or (high is not None and value > high):
            _reject("barehands_benchmark_invalid", f"{name} : valeur hors bornes ({_describe(given)}).")
        if integer and not value.is_integer():
            _reject("barehands_benchmark_invalid", f"{name} : un compte est entier.")
        if per_trial and value > trials:
            _reject("barehands_benchmark_invalid", f"{name} = {_describe(given)} dépasse les {trials} essais.")
        out[name] = int(value) if integer else value
    return out


def normalize(payload: Any) -> dict[str, Any]:
    """Reconstruire un résultat de banc **clé par clé**, ou refuser avec un code.

    Même verdict que `createBenchmarkResult` (test de parité) : clé inconnue,
    métrique manquante, borne, compte, essai, graine, profil.
    """

    if not isinstance(payload, dict):
        _reject("barehands_benchmark_invalid", "Résultat de banc attendu sous forme d'objet JSON.")
    _only_keys(payload, RESULT_KEYS, "Résultat de banc")
    version = payload.get("schemaVersion")
    if version is not None and (isinstance(version, bool) or version != SCHEMA_VERSION):
        _reject("barehands_schema_version_unsupported",
                f"Résultat de banc en version {_describe(payload.get('schemaVersion'))} ; ce Jarvis lit la version {SCHEMA_VERSION}.")
    if payload.get("kind") not in (None, "benchmark_result"):
        _reject("barehands_benchmark_invalid", "Résultat : kind vaut « benchmark_result ».")
    seed = _integer(payload.get("seed"), "barehands_benchmark_seed_invalid", "seed", 0, SEED_MAX)
    plan_class = payload.get("planClass")
    if plan_class is None:
        plan_class = PLAN_CLASS
    elif plan_class not in PLAN_CLASSES:
        _reject("barehands_benchmark_invalid", f"planClass inconnue : {_describe(plan_class)}.")
    run_at = _integer(payload.get("runAt"), "barehands_benchmark_invalid", "runAt", 0, 2**53 - 1)
    source = payload.get("profileSource")
    if source not in PROFILE_SOURCES:
        _reject("barehands_benchmark_invalid", f"profileSource inconnue : {_describe(source)}.")
    trial_ref = payload.get("trialRef")
    trial_ref = None if trial_ref is None else _ref(trial_ref, "tr", "Essai mesuré")
    if (source == "trial") != (trial_ref is not None):
        _reject("barehands_benchmark_profile_invalid",
                "trialRef est exigé pour un profil « trial », et seulement pour lui.")
    fingerprint = payload.get("profileFingerprint")
    if fingerprint is not None and not (isinstance(fingerprint, str) and FINGERPRINT_PATTERN.match(fingerprint)):
        _reject("barehands_benchmark_profile_invalid",
                "profileFingerprint : 8 à 64 caractères hexadécimaux minuscules.")
    exercises_raw = payload.get("exercises")
    if not isinstance(exercises_raw, list) or not exercises_raw:
        _reject("barehands_benchmark_invalid", "Résultat de banc : au moins un exercice.")
    if len(exercises_raw) > EXERCISES_MAX:
        _reject("barehands_benchmark_invalid", f"Résultat de banc : {EXERCISES_MAX} exercices au plus.")
    seen: set[str] = set()
    exercises = []
    for item in exercises_raw:
        if not isinstance(item, dict):
            _reject("barehands_benchmark_invalid", "Exercice : objet attendu.")
        _only_keys(item, EXERCISE_KEYS, "Exercice")
        ref = _ref(item.get("ref"), "ex", "Exercice")
        if ref in seen:
            _reject("barehands_session_ref_duplicate", f"Exercice {ref} en double.")
        seen.add(ref)
        kind = item.get("kind")
        if kind not in EXERCISE_METRICS:
            _reject("barehands_benchmark_exercise_unknown", f"Exercice de banc inconnu : {_describe(kind)}.")
        trials = _integer(item.get("trials"), "barehands_benchmark_invalid", "trials", 1, TRIALS_MAX)
        exercises.append({"ref": ref, "kind": kind, "trials": trials,
                          "metrics": _metrics(item.get("metrics"), kind, trials)})
    return {"schemaVersion": SCHEMA_VERSION, "kind": "benchmark_result",
            "ref": _ref(payload.get("ref"), "bm", "Résultat de banc"),
            "seed": seed, "planClass": plan_class, "runAt": run_at, "profileSource": source,
            "trialRef": trial_ref, "profileFingerprint": fingerprint, "exercises": exercises}


def summary_id(result: dict[str, Any]) -> str:
    """L'identifiant d'un résumé : l'empreinte de son contenu canonique. Un
    même run posté deux fois n'est rangé qu'une fois."""

    text = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def store_path(runtime_root: Path) -> Path:
    return Path(runtime_root) / STORE_FILENAME


def _read(runtime_root: Path) -> tuple[list[dict[str, Any]], int]:
    """Les résumés rangés, relus par la même liste blanche. Une entrée
    illisible est **écartée et comptée** (jamais recopiée) ; un fichier
    illisible vaut « rien de rangé »."""

    path = store_path(runtime_root)
    if not path.is_file():
        return [], 0
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], 1
    if not isinstance(document, dict) or document.get("schema") != STORE_SCHEMA:
        return [], 1
    entries, skipped = [], 0
    for entry in document.get("results") if isinstance(document.get("results"), list) else []:
        try:
            result = normalize(entry.get("result") if isinstance(entry, dict) else None)
        except BarehandsBenchmarkError:
            skipped += 1
            continue
        entries.append({"id": summary_id(result), "result": result})
    return entries, skipped


def _write(runtime_root: Path, entries: list[dict[str, Any]]) -> None:
    path = store_path(runtime_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps({"schema": STORE_SCHEMA, "schemaVersion": STORE_SCHEMA_VERSION,
                                "results": entries}, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temp, path)


def load(runtime_root: Path) -> dict[str, Any]:
    """``{results: [{id, result}], skipped}``, du plus ancien au plus récent."""

    entries, skipped = _read(runtime_root)
    entries.sort(key=lambda entry: (entry["result"]["runAt"], entry["id"]))
    return {"results": entries, "skipped": skipped, "max": SUMMARY_MAX}


def store(runtime_root: Path, payload: Any) -> dict[str, Any]:
    """Ranger un résumé (refus codé sinon). Rend ``{id, stored, dropped,
    duplicate}`` : ``dropped`` compte les plus anciens sortis du plafond."""

    result = normalize(payload)
    entries, _skipped = _read(runtime_root)
    ident = summary_id(result)
    duplicate = any(entry["id"] == ident for entry in entries)
    if not duplicate:
        entries.append({"id": ident, "result": result})
    entries.sort(key=lambda entry: (entry["result"]["runAt"], entry["id"]))
    dropped = max(0, len(entries) - SUMMARY_MAX)
    entries = entries[dropped:]
    _write(runtime_root, entries)
    return {"id": ident, "stored": len(entries), "dropped": dropped, "duplicate": duplicate}


def clear(runtime_root: Path) -> dict[str, Any]:
    """Tout effacer. Rend le nombre de résumés qui étaient rangés."""

    entries, skipped = _read(runtime_root)
    path = store_path(runtime_root)
    if path.exists():
        path.unlink()
    return {"cleared": len(entries) + skipped}
