"""Résumés du banc d'essai Bare Hands : la liste blanche côté serveur, et le rangement.

Tâche ``jarvis-bare-hands-adaptive-calibration-benchmark``, Slice 08
(`docs/barehands-contracts.md` § 17, décisions 40, 41 et 64).

**Ce qui se range : des résultats de banc du contrat, rien d'autre.** Un
résultat porte, par exercice, les métriques **brutes** que le déroulé a
mesurées (des nombres ou ``null``) et, depuis la reprise QA, leurs
**échantillons scalaires** (au plus ``SAMPLES_MAX`` nombres par métrique : une
valeur par essai, par épisode ou par point visé) — ce qui permet un intervalle
de confiance entre deux runs rechargés. Plus la graine, la classe de plan, la
fenêtre, l'instant du run et l'identité du profil mesuré. Jamais une image, un
point de main, une trace, ni un score : les dimensions et le score se
recalculent dans la page (`scoreResult`) — les ranger ferait une seconde
vérité (décision 40).

**Pourquoi ce miroir.** L'avant/après doit survivre au rechargement de la
page, donc le serveur range, et une route ouverte ne peut pas se fier à la
bonne volonté de l'appelant. Même partage des rôles que `barehands_trace` : le
serveur **reconstruit** chaque clé depuis une valeur lue par un lecteur typé,
et **refuse** une clé qu'il ne connaît pas, ou une valeur d'un autre type, avec
un code (``X-Jarvis-Error-Code``) — jamais une exception non codée. Les tables
sont tenues en parité avec `control_center_barehands_contracts.js` par un test
sous node.

Rangement : ``<runtime_root>/barehands-benchmarks.json``, au plus
``SUMMARY_MAX`` résumés (les plus anciens par ``runAt`` sortent), écriture
atomique. Un fichier illisible n'est jamais écrasé en silence : il est d'abord
copié à côté (``barehands-benchmarks.unreadable-N.json``, ``BACKUP_MAX`` au
plus). ``DELETE`` efface tout.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
STORE_SCHEMA = "jarvis.barehands.benchmarks"
STORE_SCHEMA_VERSION = 1
STORE_FILENAME = "barehands-benchmarks.json"
BACKUP_PATTERN = "barehands-benchmarks.unreadable-{n}.json"
#: Au plus vingt résumés : de quoi comparer un avant et plusieurs après sur
#: plusieurs calibrations, pas un historique de la personne.
SUMMARY_MAX = 20
#: Au plus trois copies d'un fichier illisible : de quoi le diagnostiquer,
#: pas une accumulation.
BACKUP_MAX = 3

PLAN_CLASSES = ("bh-bench-1",)
PLAN_CLASS = PLAN_CLASSES[0]
PROFILE_SOURCES = ("defaults", "saved", "trial")
EXERCISES_MAX = 24
TRIALS_MAX = 50
SAMPLES_MAX = 64

#: Les métriques brutes de chaque exercice (`BENCHMARK_EXERCISE_METRICS`).
EXERCISE_METRICS: dict[str, tuple[str, ...]] = {
    "target_acquisition": ("acquisition_ms", "missed_click_count", "wrong_target_count",
                           "reacquisition_count", "press_latency_ms", "timeout_count", "release_latency_ms"),
    "no_click_tracking": ("false_click_count", "false_press_rate", "false_secondary_press_rate",
                          "unintended_target_rate", "unintended_pointer_rate", "pointer_jitter_px"),
    "nearby_targets": ("acquisition_ms", "wrong_target_count", "target_ambiguity", "reacquisition_count",
                       "timeout_count", "release_latency_ms"),
    "drag_drop": ("drag_success_rate", "premature_drop_count", "placement_error_px", "release_latency_ms"),
    "moving_target": ("acquisition_ms", "pointer_lag_ms", "missed_click_count", "reacquisition_count",
                      "timeout_count"),
    "chained": ("transition_ms", "missed_click_count", "wrong_target_count", "premature_drop_count",
                "release_latency_ms", "timeout_count"),
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
    "timeout_count": (0, None, True, True),
}

RESULT_KEYS = ("schemaVersion", "kind", "ref", "seed", "planClass", "runAt", "profileSource", "trialRef",
               "profileFingerprint", "viewport", "exercises")
EXERCISE_KEYS = ("ref", "kind", "trials", "metrics", "samples")
VIEWPORT_KEYS = ("width", "height", "scale")
REF_PATTERN = re.compile(r"^([a-z]{2})-(\d{1,9})$")
FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{8,64}$")
SEED_MAX = 4294967295
RUN_AT_MAX = 2**53 - 1


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
    if isinstance(raw, int):
        text = str(raw) if abs(raw) < 10**15 else f"un entier de {len(str(abs(raw)))} chiffres"
        return f"« {text} »"
    if isinstance(raw, float):
        return f"« {raw!s} »"
    if isinstance(raw, str):
        return f"« {raw} »" if len(raw) <= 48 else f"une chaîne de {len(raw)} caractères"
    if isinstance(raw, list):
        return f"une liste de {len(raw)} éléments"
    if isinstance(raw, dict):
        return f"un objet de {len(raw)} clés"
    return f"une valeur de type {type(raw).__name__}"


def _number(raw: Any) -> float | None:
    """Un nombre fini, ou ``None`` ; ``bool`` n'est pas un nombre ici, et un
    entier trop grand pour un flottant non plus (jamais d'``OverflowError``)."""

    if raw is None or isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    try:
        value = float(raw)
    except OverflowError:
        return None
    return None if math.isnan(value) or math.isinf(value) else value


def _word(raw: Any, vocabulary: tuple[str, ...]) -> str | None:
    """Un mot d'un vocabulaire fermé ; une valeur d'un autre type (liste,
    objet) n'est jamais comparée — elle ne l'est simplement pas."""

    return raw if isinstance(raw, str) and raw in vocabulary else None


def _object(raw: Any, label: str) -> dict:
    if not isinstance(raw, dict):
        _reject("barehands_benchmark_invalid", f"{label} : objet attendu, reçu {_describe(raw)}.")
    return raw


def _only_keys(source: dict, allowed: tuple[str, ...], label: str) -> None:
    unknown = sorted(str(key) for key in source if key not in allowed)
    if unknown:
        _reject("barehands_session_key_unknown",
                f"{label} : clé(s) inconnue(s) {', '.join(_describe(k) for k in unknown[:4])}.")


def _integer(raw: Any, code: str, label: str, low: int, high: int) -> int:
    value = _number(raw)
    if value is None or not float(value).is_integer() or not low <= value <= high:
        _reject(code, f"{label} : entier de {low} à {high} attendu, reçu {_describe(raw)}.")
    return int(value)


def _bounded(raw: Any, label: str, low: float, high: float | None) -> float:
    value = _number(raw)
    if value is None or value < low or (high is not None and value > high):
        _reject("barehands_benchmark_invalid", f"{label} : valeur hors bornes ({_describe(raw)}).")
    return value


def _ref(raw: Any, kind: str, label: str) -> str:
    match = REF_PATTERN.match(raw) if isinstance(raw, str) else None
    if not match or match.group(1) != kind:
        _reject("barehands_session_ref_invalid", f"{label} : référence « {kind}-N » attendue, reçu {_describe(raw)}.")
    return raw


def _metrics(raw: Any, kind: str, trials: int) -> dict[str, float | int | None]:
    raw = _object(raw, "metrics")
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
        low, high, integer, per_trial = METRIC_BOUNDS[name]
        value = _bounded(given, name, low, high)
        if integer and not value.is_integer():
            _reject("barehands_benchmark_invalid", f"{name} : un compte est entier.")
        if per_trial and value > trials:
            _reject("barehands_benchmark_invalid", f"{name} = {_describe(given)} dépasse les {trials} essais.")
        out[name] = int(value) if integer else value
    return out


def _samples(raw: Any, kind: str) -> dict[str, list[float]] | None:
    """Les échantillons, facultatifs : au plus ``SAMPLES_MAX`` nombres par
    métrique de l'exercice, chacun dans les bornes de sa métrique (un compte
    par essai n'a pas de plafond d'essais ici : c'est une valeur d'un essai)."""

    if raw is None:
        return None
    raw = _object(raw, "samples")
    _only_keys(raw, EXERCISE_METRICS[kind], f"samples de {kind}")
    out: dict[str, list[float]] = {}
    for name, values in raw.items():
        if not isinstance(values, list) or len(values) > SAMPLES_MAX:
            _reject("barehands_benchmark_invalid", f"samples.{name} : liste de {SAMPLES_MAX} nombres au plus.")
        low, high, integer, per_trial = METRIC_BOUNDS[name]
        out[name] = [_bounded(v, f"samples.{name}", 0 if integer else low,
                              None if high is None or per_trial else high) for v in values]
    return out


def _viewport(raw: Any) -> dict[str, float] | None:
    if raw is None:
        return None
    raw = _object(raw, "viewport")
    _only_keys(raw, VIEWPORT_KEYS, "viewport")
    return {"width": _bounded(raw.get("width"), "viewport.width", 1, 100000),
            "height": _bounded(raw.get("height"), "viewport.height", 1, 100000),
            "scale": _bounded(raw.get("scale"), "viewport.scale", .01, 1000)}


def normalize(payload: Any) -> dict[str, Any]:
    """Reconstruire un résultat de banc **clé par clé**, ou refuser avec un code.

    Même verdict que `createBenchmarkResult` (test de parité) : clé inconnue,
    métrique manquante, borne, compte, essai, graine, profil, fenêtre,
    échantillons — et toute valeur d'un type inattendu, refusée avec un code.
    """

    payload = _object(payload, "Résultat de banc")
    _only_keys(payload, RESULT_KEYS, "Résultat de banc")
    version = payload.get("schemaVersion")
    if version is not None and (isinstance(version, bool) or _number(version) != SCHEMA_VERSION):
        _reject("barehands_schema_version_unsupported",
                f"Résultat de banc en version {_describe(version)} ; ce Jarvis lit la version {SCHEMA_VERSION}.")
    if payload.get("kind") is not None and payload.get("kind") != "benchmark_result":
        _reject("barehands_benchmark_invalid", "Résultat : kind vaut « benchmark_result ».")
    seed = _integer(payload.get("seed"), "barehands_benchmark_seed_invalid", "seed", 0, SEED_MAX)
    plan_class = payload.get("planClass")
    if plan_class is None:
        plan_class = PLAN_CLASS
    elif _word(plan_class, PLAN_CLASSES) is None:
        _reject("barehands_benchmark_invalid", f"planClass inconnue : {_describe(plan_class)}.")
    run_at = _integer(payload.get("runAt"), "barehands_benchmark_invalid", "runAt", 0, RUN_AT_MAX)
    source = _word(payload.get("profileSource"), PROFILE_SOURCES)
    if source is None:
        _reject("barehands_benchmark_invalid", f"profileSource inconnue : {_describe(payload.get('profileSource'))}.")
    trial_ref = payload.get("trialRef")
    trial_ref = None if trial_ref is None else _ref(trial_ref, "tr", "Essai mesuré")
    if (source == "trial") != (trial_ref is not None):
        _reject("barehands_benchmark_profile_invalid",
                "trialRef est exigé pour un profil « trial », et seulement pour lui.")
    fingerprint = payload.get("profileFingerprint")
    if fingerprint is not None and not (isinstance(fingerprint, str) and FINGERPRINT_PATTERN.match(fingerprint)):
        _reject("barehands_benchmark_profile_invalid",
                "profileFingerprint : 8 à 64 caractères hexadécimaux minuscules.")
    viewport = _viewport(payload.get("viewport"))
    exercises_raw = payload.get("exercises")
    if not isinstance(exercises_raw, list) or not exercises_raw:
        _reject("barehands_benchmark_invalid", "Résultat de banc : au moins un exercice.")
    if len(exercises_raw) > EXERCISES_MAX:
        _reject("barehands_benchmark_invalid", f"Résultat de banc : {EXERCISES_MAX} exercices au plus.")
    seen: set[str] = set()
    exercises = []
    for item in exercises_raw:
        item = _object(item, "Exercice")
        _only_keys(item, EXERCISE_KEYS, "Exercice")
        ref = _ref(item.get("ref"), "ex", "Exercice")
        if ref in seen:
            _reject("barehands_session_ref_duplicate", f"Exercice {ref} en double.")
        seen.add(ref)
        kind = _word(item.get("kind"), tuple(EXERCISE_METRICS))
        if kind is None:
            _reject("barehands_benchmark_exercise_unknown", f"Exercice de banc inconnu : {_describe(item.get('kind'))}.")
        trials = _integer(item.get("trials"), "barehands_benchmark_invalid", "trials", 1, TRIALS_MAX)
        exercise: dict[str, Any] = {"ref": ref, "kind": kind, "trials": trials,
                                    "metrics": _metrics(item.get("metrics"), kind, trials)}
        samples = _samples(item.get("samples"), kind)
        if samples is not None:
            exercise["samples"] = samples
        exercises.append(exercise)
    return {"schemaVersion": SCHEMA_VERSION, "kind": "benchmark_result",
            "ref": _ref(payload.get("ref"), "bm", "Résultat de banc"),
            "seed": seed, "planClass": plan_class, "runAt": run_at, "profileSource": source,
            "trialRef": trial_ref, "profileFingerprint": fingerprint, "viewport": viewport,
            "exercises": exercises}


def summary_id(result: dict[str, Any]) -> str:
    """L'identifiant d'un résumé : l'empreinte de son contenu canonique. Un
    même run posté deux fois n'est rangé qu'une fois."""

    text = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def store_path(runtime_root: Path) -> Path:
    return Path(runtime_root) / STORE_FILENAME


def _read(runtime_root: Path) -> tuple[list[dict[str, Any]], int, bool]:
    """Les résumés rangés, relus par la même liste blanche.

    Rend ``(entrées, écartées, fichier_illisible)`` : une entrée illisible est
    écartée et comptée (jamais recopiée) ; un fichier illisible vaut « rien de
    lisible », et le dit.
    """

    path = store_path(runtime_root)
    if not path.is_file():
        return [], 0, False
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], 1, True
    if not isinstance(document, dict) or document.get("schema") != STORE_SCHEMA:
        return [], 1, True
    entries, skipped = [], 0
    results = document.get("results")
    for entry in results if isinstance(results, list) else []:
        try:
            result = normalize(entry.get("result") if isinstance(entry, dict) else None)
        except BarehandsBenchmarkError:
            skipped += 1
            continue
        entries.append({"id": summary_id(result), "result": result})
    return entries, skipped, False


def _backup_unreadable(runtime_root: Path) -> str | None:
    """Copier le fichier illisible avant qu'une écriture ne le remplace : au
    plus ``BACKUP_MAX`` copies, la plus ancienne remplacée en premier."""

    path = store_path(runtime_root)
    root = path.parent
    candidates = [root / BACKUP_PATTERN.format(n=n) for n in range(1, BACKUP_MAX + 1)]
    free = [c for c in candidates if not c.exists()]
    target = free[0] if free else min(candidates, key=lambda c: c.stat().st_mtime)
    shutil.copyfile(path, target)
    return target.name


def _write(runtime_root: Path, entries: list[dict[str, Any]]) -> None:
    path = store_path(runtime_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps({"schema": STORE_SCHEMA, "schemaVersion": STORE_SCHEMA_VERSION,
                                "results": entries}, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temp, path)


def _ordered(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(entries, key=lambda entry: (entry["result"]["runAt"], entry["id"]))


def load(runtime_root: Path) -> dict[str, Any]:
    """``{results: [{id, result}], skipped, max}``, du plus ancien au plus récent."""

    entries, skipped, _unreadable = _read(runtime_root)
    return {"results": _ordered(entries), "skipped": skipped, "max": SUMMARY_MAX}


def store(runtime_root: Path, payload: Any) -> dict[str, Any]:
    """Ranger un résumé (refus codé sinon). Rend ``{id, stored, dropped,
    duplicate, skipped, backup}`` : ``dropped`` compte les plus anciens sortis
    du plafond, ``skipped`` les entrées illisibles non recopiées, ``backup`` la
    copie d'un fichier illisible faite avant de l'écraser."""

    result = normalize(payload)
    entries, skipped, unreadable = _read(runtime_root)
    backup = _backup_unreadable(runtime_root) if unreadable or skipped else None
    ident = summary_id(result)
    duplicate = any(entry["id"] == ident for entry in entries)
    if not duplicate:
        entries.append({"id": ident, "result": result})
    entries = _ordered(entries)
    dropped = max(0, len(entries) - SUMMARY_MAX)
    entries = entries[dropped:]
    _write(runtime_root, entries)
    return {"id": ident, "stored": len(entries), "dropped": dropped, "duplicate": duplicate,
            "skipped": skipped, "backup": backup}


def clear(runtime_root: Path) -> dict[str, Any]:
    """Tout effacer. Rend le nombre de résumés qui étaient rangés."""

    entries, skipped, _unreadable = _read(runtime_root)
    path = store_path(runtime_root)
    if path.exists():
        path.unlink()
    return {"cleared": len(entries) + skipped}
