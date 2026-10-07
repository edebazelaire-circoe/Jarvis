"""Mesure des contrôles automatisables de HV-WAKEWORD-MIC-01 à partir de `runtime/trace.jsonl`.

Outil de la Slice 09 de `jarvis-wake-word`. Lecture seule du journal : il
n'ouvre ni micro ni haut-parleur (aucun import audio), ne persiste rien (sauf
`--output-json` si on le demande) et n'importe rien de `jarvis/`.

    python scripts/measure_wake_word_validation.py
    python scripts/measure_wake_word_validation.py --since 2026-10-08T09:00 --until 2026-10-08T10:00
    python scripts/measure_wake_word_validation.py --since ... --until ... --no-deliberate-activation
    python scripts/measure_wake_word_validation.py --json --runtime-dir <dossier runtime>

Une « série » du Human (20 essais, une heure de salle) = une plage `--since` /
`--until` : lancer l'outil une fois par série. Les instants sans fuseau sont lus
en UTC (le journal est en UTC ISO). `--until` est exclusif.

Vie privée : seules des valeurs numériques et des codes à forme fixe sortent du
journal. Aucun texte de parole, aucun message, aucun chemin ; le rapport ne
cite pas le chemin du journal.

Ce que l'outil NE PEUT PAS mesurer : voir `NOT_MEASURABLE` (faux négatifs,
latence acoustique, durée de rechargement du moteur, cooldowns ignorés...).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

#: Une ligne du journal plus longue que ceci est sautée sans être chargée en entier.
MAX_LINE_BYTES = 1 << 20
#: Au-delà, une détection sans `voice.wake` n'est plus appariée à un `voice.wake` tardif.
PAIR_MAX_S = 10.0
#: Fenêtre par défaut d'« écho » après une fin de parole de Jarvis (HV-e : une minute).
DEFAULT_ECHO_WINDOW_S = 60.0
#: Queue après `voice.background` pour la règle de la fiche HV-e (5 s).
DEFAULT_TAIL_S = 5.0
#: Fenêtre du dédoublonnage des pannes (une ligne identique par minute).
FAILURE_WINDOW_S = 60.0

DETECTED = {"wake.own_stream.detected": "simple", "wake.shared_pcm.detected": "presentation"}
FAILED = {"wake.own_stream.failed": "simple", "wake.shared_pcm.failed": "presentation"}
STARTED = "wake.own_stream.started"
STOPPED = "wake.own_stream.stopped"
SPEECH_END = "voice.speech.completed"
F9_KINDS = ("voice.manual_cancel", "voice.manual_submit", "voice.presentation_address_key")
RELEVANT = frozenset(
    {*DETECTED, *FAILED, STARTED, STOPPED, SPEECH_END, *F9_KINDS,
     "voice.wake", "voice.wake.outcome", "voice.connecting", "voice.active", "voice.background",
     "presentation.runtime.entered", "wake.shared_pcm.started", "wake.shared_pcm.stopped"}
)

#: Valeurs textuelles admises dans le rapport : formes fixes, jamais du texte libre.
_LABEL = re.compile(r"[a-z0-9][a-z0-9_.\-]{0,31}")
_CODE = re.compile(r"wake_[a-z_]{1,60}")

NOT_MEASURABLE = (
    "Faux négatifs (« Hey Jarvis » dit et non reconnu) : un échec ne laisse aucune ligne dans le journal. "
    "Il faut le décompte des essais du Human (protocole HV-WAKEWORD-MIC-01-a et -d) ; l'outil ne donne que les réussites.",
    "Latence acoustique (fin de l'énoncé jusqu'à la détection) : invisible dans la trace ; "
    "les latences mesurées ici commencent à la détection.",
    "Durée du rechargement du moteur au mute() : le début de resume() n'est pas tracé ; seul l'écart signé "
    "wake.own_stream.started -> voice.background et le délai retour au repos -> détection suivante sont observables.",
    "Cooldowns ignorés : le compteur du moteur n'est pas écrit dans le journal.",
    "Le micro ouvert ou non quand enabled=false : voir `python -m jarvis wake-word status` et "
    "scripts/check_wake_word_disabled.py (HV-WAKEWORD-MIC-01-i).",
    "Qu'une détection soit voulue ou non : l'outil ne le sait pas. Les « faux positifs candidats » ne valent "
    "que si le Human déclare ne pas avoir parlé (--no-deliberate-activation ou --deliberate-window).",
)


# ----------------------------------------------------------------------------- lecture


def parse_instant(value: object) -> float | None:
    """Epoch (secondes) d'un horodatage ISO ; sans fuseau = UTC ; `None` si illisible."""

    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    try:
        return moment.timestamp()
    except (OverflowError, OSError, ValueError):
        return None


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _label(value: object, fallback: str = "inconnu") -> str:
    if isinstance(value, str) and _LABEL.fullmatch(value):
        return value
    return fallback if value in (None, "") else "autre"


def _code(value: object) -> str | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, str) and _CODE.fullmatch(value) else "autre"


def _count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 10**9:
        return 0
    return value


def _keep(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    """Les seuls champs lus pour un événement : numériques ou à forme fixe."""

    if kind in DETECTED or kind == "voice.wake":
        kept: dict[str, Any] = {"provider": _label(data.get("provider"))}
        for field in ("score", "threshold"):
            number = _finite(data.get(field))
            kept[field] = number
            if data.get(field) is not None and number is None:
                kept[field + "_invalid"] = True
        if kind == "voice.wake":
            kept["source"] = _label(data.get("source"), "sans_source")
        return kept
    if kind in FAILED:
        return {"code": _code(data.get("code")) or "sans_code", "cause_code": _code(data.get("cause_code")),
                "suppressed": _count(data.get("suppressed"))}
    if kind == "presentation.runtime.entered":
        owners = data.get("physical_input_owners")
        return {"owners": owners if isinstance(owners, int) and not isinstance(owners, bool) and 0 <= owners < 1000 else None}
    return {}


def read_events(
    path: Path, *, since: float | None, until: float | None, margin_s: float
) -> tuple[list[tuple[float, int, str, dict[str, Any]]], dict[str, int]]:
    """Événements utiles triés par horodatage (ordre du fichier à égalité) et compteurs de lecture."""

    stats = {"lines": 0, "invalid_lines": 0, "oversize_lines": 0, "lines_without_timestamp": 0, "irrelevant_lines": 0}
    events: list[tuple[float, int, str, dict[str, Any]]] = []
    low = None if since is None else since - margin_s
    high = None if until is None else until + margin_s
    with path.open("rb") as handle:
        sequence = 0
        while True:
            raw = handle.readline(MAX_LINE_BYTES + 1)
            if not raw:
                break
            if len(raw) > MAX_LINE_BYTES and not raw.endswith(b"\n"):
                while True:  # vider le reste de la ligne sans le garder
                    rest = handle.readline(MAX_LINE_BYTES)
                    if not rest or rest.endswith(b"\n"):
                        break
                stats["lines"] += 1
                stats["oversize_lines"] += 1
                continue
            if not raw.strip():
                continue
            stats["lines"] += 1
            try:
                row = json.loads(raw)
            except (ValueError, RecursionError):
                stats["invalid_lines"] += 1
                continue
            if not isinstance(row, dict):
                stats["invalid_lines"] += 1
                continue
            kind = row.get("kind")
            if kind not in RELEVANT:
                stats["irrelevant_lines"] += 1
                continue
            moment = parse_instant(row.get("ts"))
            if moment is None:
                stats["lines_without_timestamp"] += 1
                continue
            if (low is not None and moment < low) or (high is not None and moment >= high):
                continue
            data = row.get("data")
            events.append((moment, sequence, kind, _keep(kind, data if isinstance(data, dict) else {})))
            sequence += 1
    events.sort(key=lambda event: (event[0], event[1]))
    return events, stats


# ----------------------------------------------------------------------------- calculs


def _percentile(ordered: list[float], fraction: float) -> float:
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def summarize(values: list[float], *, digits: int = 1) -> dict[str, Any]:
    """n, min, médiane, p95, max ; `p95_reliable` faux sous vingt valeurs."""

    if not values:
        return {"n": 0}
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "min": round(ordered[0], digits),
        "median": round(statistics.median(ordered), digits),
        "p95": round(_percentile(ordered, 0.95), digits),
        "max": round(ordered[-1], digits),
        "p95_reliable": len(ordered) >= 20,
    }


def _nested(table: dict[str, dict[str, Any]], first: str, second: str, default: Any) -> Any:
    return table.setdefault(first, {}).setdefault(second, default)


def analyse(
    events: list[tuple[float, int, str, dict[str, Any]]],
    *,
    since: float | None,
    until: float | None,
    echo_window_s: float = DEFAULT_ECHO_WINDOW_S,
    tail_s: float = DEFAULT_TAIL_S,
    deliberate_windows: list[tuple[float, float]] | None = None,
    no_deliberate: bool = False,
) -> dict[str, Any]:
    def inside(moment: float) -> bool:
        return (since is None or moment >= since) and (until is None or moment < until)

    counted = [event for event in events if inside(event[0])]
    detections_by: dict[str, dict[str, int]] = {}
    scores_by: dict[str, dict[str, list[float]]] = {}
    thresholds_by: dict[str, dict[str, dict[str, int]]] = {}
    invalid_scores = 0
    wake_by_source: dict[str, dict[str, int]] = {}
    detections: list[tuple[float, str, str]] = []  # (ts, mode, provider)
    failures: dict[tuple[str, str, str | None], list[float]] = {}
    suppressed: dict[tuple[str, str, str | None], int] = {}
    f9: dict[str, int] = {kind: 0 for kind in F9_KINDS}
    owners_seen: list[int] = []
    starts = stops = backgrounds = 0

    for moment, _, kind, data in counted:
        if kind in DETECTED:
            mode, provider = DETECTED[kind], data["provider"]
            _nested(detections_by, mode, provider, 0)
            detections_by[mode][provider] += 1
            detections.append((moment, mode, provider))
            if data.get("score_invalid") or data.get("threshold_invalid"):
                invalid_scores += 1
            if data["score"] is not None:
                scores_by.setdefault(mode, {}).setdefault(provider, []).append(data["score"])
            if data["threshold"] is not None:
                label = format(data["threshold"], "g")
                bucket = thresholds_by.setdefault(mode, {}).setdefault(provider, {})
                bucket[label] = bucket.get(label, 0) + 1
        elif kind == "voice.wake":
            _nested(wake_by_source, data["source"], data["provider"], 0)
            wake_by_source[data["source"]][data["provider"]] += 1
        elif kind in FAILED:
            key = (FAILED[kind], data["code"], data["cause_code"])
            failures.setdefault(key, []).append(moment)
            suppressed[key] = suppressed.get(key, 0) + data["suppressed"]
        elif kind in f9:
            f9[kind] += 1
        elif kind == "presentation.runtime.entered" and data["owners"] is not None:
            owners_seen.append(data["owners"])
        elif kind in (STARTED, "wake.shared_pcm.started"):
            starts += 1
        elif kind in (STOPPED, "wake.shared_pcm.stopped"):
            stops += 1
        elif kind == "voice.background":
            backgrounds += 1

    # --- latences, par parcours de tous les événements (appariement hors plage possible) ---
    det_to_wake: dict[str, list[float]] = {}
    wake_to_connecting: dict[str, list[float]] = {}
    wake_to_active: dict[str, list[float]] = {}
    unpaired_detections = 0
    wakes_without_activation = 0
    started_to_background: list[float] = []
    background_to_detection: list[float] = []
    pending_det: tuple[float, str] | None = None
    pending_wake: dict[str, Any] | None = None
    last_started: float | None = None
    last_background: float | None = None

    def close_wake() -> None:
        nonlocal wakes_without_activation
        if pending_wake is not None and pending_wake["counted"]:
            wakes_without_activation += 1

    for moment, _, kind, data in events:
        if kind in DETECTED:
            if pending_det is not None and inside(pending_det[0]):
                unpaired_detections += 1
            pending_det = (moment, DETECTED[kind])
            if last_background is not None and inside(moment):
                background_to_detection.append(moment - last_background)
            last_background = None
        elif kind == "voice.wake":
            if pending_det is not None and moment - pending_det[0] <= PAIR_MAX_S:
                if inside(pending_det[0]):
                    det_to_wake.setdefault(pending_det[1], []).append((moment - pending_det[0]) * 1000)
            elif pending_det is not None and inside(pending_det[0]):
                unpaired_detections += 1
            pending_det = None
            close_wake()
            pending_wake = {"ts": moment, "source": data["source"], "counted": inside(moment), "connecting": False}
        elif kind == "voice.connecting" and pending_wake is not None and not pending_wake["connecting"]:
            pending_wake["connecting"] = True
            if pending_wake["counted"]:
                wake_to_connecting.setdefault(pending_wake["source"], []).append((moment - pending_wake["ts"]) * 1000)
        elif kind == "voice.active":
            if pending_wake is not None:
                if pending_wake["counted"]:
                    wake_to_active.setdefault(pending_wake["source"], []).append((moment - pending_wake["ts"]) * 1000)
                pending_wake = None
            last_started = None
        elif kind in (STARTED,):
            last_started = moment
        elif kind == "voice.background":
            close_wake()
            pending_wake = None
            if last_started is not None and inside(moment):
                started_to_background.append((moment - last_started) * 1000)
            last_started = None
            last_background = moment
    if pending_det is not None and inside(pending_det[0]):
        unpaired_detections += 1
    close_wake()

    medians = {source: statistics.median(values) for source, values in wake_to_active.items() if values}
    delta = None
    if "wake_word" in medians and "manual_key" in medians:
        delta = round(medians["wake_word"] - medians["manual_key"], 1)

    # --- écho : indice, pas preuve ---
    speech_ends = [event[0] for event in events if event[2] == SPEECH_END]
    sessions: list[tuple[float, float]] = []
    opened: float | None = None
    for moment, _, kind, _ in events:
        if kind == "voice.active" and opened is None:
            opened = moment
        elif kind == "voice.background" and opened is not None:
            sessions.append((opened, moment + tail_s))
            opened = None
    if opened is not None:
        sessions.append((opened, float("inf")))
    after_speech: list[float] = []
    in_session = 0
    for moment, _, _ in detections:
        previous = [end for end in speech_ends if end <= moment]
        if previous and moment - previous[-1] <= echo_window_s:
            after_speech.append(round(moment - previous[-1], 2))
        if any(start <= moment <= end for start, end in sessions):
            in_session += 1

    # --- faux positifs candidats ---
    windows = deliberate_windows or []
    declared = no_deliberate or bool(windows)
    candidates: list[tuple[float, str, str]] = []
    if declared:
        candidates = [d for d in detections if not any(a <= d[0] < b for a, b in windows)]
    span_s: float | None = None
    span_origin = "indéterminée"
    if since is not None and until is not None and until > since:
        span_s, span_origin = until - since, "plage --since/--until"
    elif counted:
        span_s, span_origin = counted[-1][0] - counted[0][0], "étendue observée des événements utiles (sans --since/--until)"
    hours = span_s / 3600 if span_s and span_s > 0 else None
    per_mode: dict[str, int] = {}
    for _, mode, _ in candidates:
        per_mode[mode] = per_mode.get(mode, 0) + 1

    # --- pannes et dédoublonnage ---
    failure_rows = []
    for key in sorted(failures, key=lambda k: (k[0], k[1], k[2] or "")):
        stamps = sorted(failures[key])
        worst, low = 0, 0
        for high, stamp in enumerate(stamps):
            while stamp - stamps[low] >= FAILURE_WINDOW_S:
                low += 1
            worst = max(worst, high - low + 1)
        failure_rows.append({
            "mode": key[0], "code": key[1], "cause_code": key[2], "lines": len(stamps),
            "suppressed": suppressed[key], "occurrences": len(stamps) + suppressed[key],
            "max_lines_in_one_minute": worst,
        })

    return {
        "detections": {
            "by_mode_and_provider": detections_by,
            "total": len(detections),
            "voice_wake_by_source_and_provider": wake_by_source,
            "scores_by_mode_and_provider": {
                mode: {prov: summarize(vals, digits=4) for prov, vals in sorted(provs.items())}
                for mode, provs in sorted(scores_by.items())
            },
            "thresholds_by_mode_and_provider": thresholds_by,
            "lines_with_invalid_score_or_threshold": invalid_scores,
        },
        "latency_ms": {
            "detection_to_voice_wake_by_mode": {m: summarize(v) for m, v in sorted(det_to_wake.items())},
            "voice_wake_to_connecting_by_source": {s: summarize(v) for s, v in sorted(wake_to_connecting.items())},
            "voice_wake_to_active_by_source": {s: summarize(v) for s, v in sorted(wake_to_active.items())},
            "median_wake_word_minus_manual_key_to_active": delta,
            "detections_without_voice_wake": unpaired_detections,
            "voice_wake_without_activation": wakes_without_activation,
        },
        "echo_hint": {
            "window_s": echo_window_s,
            "tail_after_background_s": tail_s,
            "speech_end_anchor": SPEECH_END,
            "detections_within_window_after_speech_end": len(after_speech),
            "seconds_after_speech_end": sorted(after_speech),
            "detections_during_session_or_tail": in_session,
            "speech_end_events_seen": len(speech_ends),
        },
        "false_positive_candidates": {
            "declared_no_deliberate_activation": declared,
            "count": len(candidates) if declared else None,
            "by_mode": per_mode if declared else None,
            "span_hours": None if hours is None else round(hours, 3),
            "span_origin": span_origin,
            "per_hour": None if not declared or hours is None else round(len(candidates) / hours, 2),
        },
        "failures": {"rows": failure_rows, "dedupe_respected": all(r["max_lines_in_one_minute"] <= 1 for r in failure_rows)},
        "engine_rearm": {
            "stream_started": starts, "stream_stopped": stops, "voice_background": backgrounds,
            "started_to_background_ms_signed": summarize(started_to_background),
            "background_to_next_detection_s": summarize(background_to_detection, digits=2),
        },
        "f9_and_address_key_events": f9,
        "presentation_physical_input_owners_seen": sorted(set(owners_seen)),
    }


# ----------------------------------------------------------------------------- sortie


def _fmt(stats: dict[str, Any], unit: str = "ms") -> str:
    if not stats.get("n"):
        return "aucune mesure"
    note = "" if stats["p95_reliable"] else " (p95 peu fiable : moins de 20 mesures)"
    return (f"n={stats['n']} min={stats['min']} médiane={stats['median']} p95={stats['p95']} "
            f"max={stats['max']} {unit}{note}")


def render_text(report: dict[str, Any]) -> str:
    out: list[str] = ["Mesure HV-WAKEWORD-MIC-01 à partir du journal (lecture seule)"]
    reading, window = report["reading"], report["range"]
    out.append(f"Plage : de {window['since'] or 'début'} à {window['until'] or 'fin'} (UTC, fin exclue).")
    out.append(
        f"Lignes lues : {reading['lines']} ; illisibles : {reading['invalid_lines']} ; "
        f"trop longues : {reading['oversize_lines']} ; sans horodatage valide : {reading['lines_without_timestamp']}."
    )
    det = report["detections"]
    out += ["", f"Détections : {det['total']}"]
    for mode, providers in sorted(det["by_mode_and_provider"].items()):
        label = "SIMPLE (flux propre)" if mode == "simple" else "PRESENTATION (PCM partagé)"
        for provider, n in sorted(providers.items()):
            out.append(f"  {label}, fournisseur {provider} : {n}")
    for source, providers in sorted(det["voice_wake_by_source_and_provider"].items()):
        for provider, n in sorted(providers.items()):
            out.append(f"  voice.wake source={source}, fournisseur {provider} : {n}")
    for mode, providers in det["scores_by_mode_and_provider"].items():
        for provider, stats in providers.items():
            thresholds = det["thresholds_by_mode_and_provider"].get(mode, {}).get(provider, {})
            out.append(f"  scores {mode}/{provider} : {_fmt(stats, '')}; seuils : {thresholds or 'aucun'}")
    if det["lines_with_invalid_score_or_threshold"]:
        out.append(f"  lignes au score ou seuil non numérique (ignorés) : {det['lines_with_invalid_score_or_threshold']}")
    lat = report["latency_ms"]
    out += ["", "Latences (à partir de la détection ; la latence acoustique n'est pas mesurable)"]
    for name, title in (("detection_to_voice_wake_by_mode", "détection -> voice.wake"),
                        ("voice_wake_to_connecting_by_source", "voice.wake -> voice.connecting"),
                        ("voice_wake_to_active_by_source", "voice.wake -> voice.active")):
        if not lat[name]:
            out.append(f"  {title} : aucune mesure")
        for key, stats in lat[name].items():
            out.append(f"  {title} [{key}] : {_fmt(stats)}")
    if lat["median_wake_word_minus_manual_key_to_active"] is not None:
        out.append(f"  médiane mot d'éveil moins médiane F9 (voice.wake -> voice.active) : "
                   f"{lat['median_wake_word_minus_manual_key_to_active']} ms")
    out.append(f"  détections sans voice.wake apparié : {lat['detections_without_voice_wake']} ; "
               f"voice.wake sans activation : {lat['voice_wake_without_activation']}")
    echo = report["echo_hint"]
    out += ["", f"Indice d'écho (un indice, pas une preuve : un énoncé volontaire compte aussi)",
            f"  détections dans les {echo['window_s']:g} s après une fin de parole de Jarvis "
            f"({echo['speech_end_anchor']}) : {echo['detections_within_window_after_speech_end']}",
            f"  détections entre voice.active et {echo['tail_after_background_s']:g} s après voice.background : "
            f"{echo['detections_during_session_or_tail']}"]
    fp = report["false_positive_candidates"]
    out.append("")
    if not fp["declared_no_deliberate_activation"]:
        out.append("Faux positifs : non évalués (ni --no-deliberate-activation ni --deliberate-window déclarés).")
    else:
        rate = "indéterminé" if fp["per_hour"] is None else f"{fp['per_hour']} par heure"
        out.append(f"Faux positifs candidats : {fp['count']} (par mode : {fp['by_mode']}) sur "
                   f"{fp['span_hours']} h [{fp['span_origin']}] : {rate}.")
        out.append("  Une plage mélangeant deux modes donne un taux global : lancer une série par mode.")
    out.append("")
    if not report["failures"]["rows"]:
        out.append("Pannes du détecteur : aucune.")
    else:
        out.append("Pannes du détecteur (lignes écrites + répétitions tues, 'suppressed') :")
        for row in report["failures"]["rows"]:
            cause = f"/{row['cause_code']}" if row["cause_code"] else ""
            out.append(f"  {row['mode']} {row['code']}{cause} : {row['lines']} ligne(s) + {row['suppressed']} tue(s) "
                       f"= {row['occurrences']} ; max {row['max_lines_in_one_minute']} ligne(s) par minute")
        out.append("  Dédoublonnage (au plus une ligne par minute) : "
                   + ("respecté." if report["failures"]["dedupe_respected"] else "NON RESPECTÉ."))
    rearm = report["engine_rearm"]
    out += ["", f"Réarmement du moteur : {rearm['stream_started']} démarrage(s), {rearm['stream_stopped']} arrêt(s), "
            f"{rearm['voice_background']} retour(s) au repos",
            f"  wake.own_stream.started -> voice.background (signé : le moteur est rechargé AVANT la ligne de repos) : "
            f"{_fmt(rearm['started_to_background_ms_signed'])}",
            f"  voice.background -> détection suivante (réussite) : {_fmt(rearm['background_to_next_detection_s'], 's')}"]
    f9 = report["f9_and_address_key_events"]
    out.append("")
    out.append("Événements de touche : " + ", ".join(f"{k}={v}" for k, v in f9.items()))
    owners = report["presentation_physical_input_owners_seen"]
    out.append(f"physical_input_owners à l'entrée en PRESENTATION : {owners if owners else 'aucune ligne'}")
    out += ["", "Ce que cet outil ne peut PAS mesurer :"] + [f"  - {line}" for line in report["not_measurable"]]
    return "\n".join(out)


def default_trace(runtime_dir: str | None) -> Path:
    raw = runtime_dir or os.getenv("JARVIS_RUNTIME_DIR")
    if raw:
        base = Path(raw).expanduser()
        base = base if base.is_absolute() else ROOT / base
    else:
        base = ROOT / "runtime"
    return base / "trace.jsonl"


def _bound(value: str | None, flag: str) -> float | None:
    if value is None:
        return None
    moment = parse_instant(value)
    if moment is None:
        raise SystemExit(f"{flag} : horodatage ISO illisible.")
    return moment


def build_report(
    path: Path, *, since: float | None, until: float | None, echo_window_s: float = DEFAULT_ECHO_WINDOW_S,
    tail_s: float = DEFAULT_TAIL_S, deliberate_windows: list[tuple[float, float]] | None = None,
    no_deliberate: bool = False,
) -> dict[str, Any]:
    margin = max(echo_window_s, tail_s, PAIR_MAX_S, 120.0)
    events, reading = read_events(path, since=since, until=until, margin_s=margin)
    report = analyse(events, since=since, until=until, echo_window_s=echo_window_s, tail_s=tail_s,
                     deliberate_windows=deliberate_windows, no_deliberate=no_deliberate)

    def iso(moment: float | None) -> str | None:
        return None if moment is None else datetime.fromtimestamp(moment, timezone.utc).isoformat()

    return {"reading": reading, "range": {"since": iso(since), "until": iso(until)}, **report,
            "not_measurable": list(NOT_MEASURABLE)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Contrôles automatisables de HV-WAKEWORD-MIC-01 (journal en lecture seule).")
    parser.add_argument("--runtime-dir", help="Dossier runtime (défaut : JARVIS_RUNTIME_DIR, sinon runtime/ du dépôt).")
    parser.add_argument("--trace", help="Journal à lire à la place de <runtime>/trace.jsonl.")
    parser.add_argument("--since", help="Début de plage (ISO, UTC si sans fuseau), inclus.")
    parser.add_argument("--until", help="Fin de plage (ISO, UTC si sans fuseau), exclue.")
    parser.add_argument("--echo-window-s", type=float, default=DEFAULT_ECHO_WINDOW_S,
                        help="Fenêtre après une fin de parole de Jarvis (défaut 60 s).")
    parser.add_argument("--tail-s", type=float, default=DEFAULT_TAIL_S,
                        help="Queue après voice.background (défaut 5 s, règle de la fiche HV-e).")
    parser.add_argument("--no-deliberate-activation", action="store_true",
                        help="Le Human déclare n'avoir rien dit : toute détection de la plage est un faux positif candidat.")
    parser.add_argument("--deliberate-window", nargs=2, action="append", metavar=("DEBUT", "FIN"),
                        help="Intervalle d'essais volontaires (répétable) ; les détections hors de ces intervalles sont candidates.")
    parser.add_argument("--json", action="store_true", help="JSON sur stdout au lieu du texte.")
    parser.add_argument("--output-json", help="Écrit aussi le rapport JSON dans ce fichier.")
    args = parser.parse_args(argv)

    if not (math.isfinite(args.echo_window_s) and args.echo_window_s >= 0 and math.isfinite(args.tail_s) and args.tail_s >= 0):
        raise SystemExit("--echo-window-s et --tail-s doivent être des nombres finis >= 0.")
    since, until = _bound(args.since, "--since"), _bound(args.until, "--until")
    if since is not None and until is not None and until <= since:
        raise SystemExit("--until doit être postérieur à --since.")
    windows: list[tuple[float, float]] = []
    for start_text, end_text in args.deliberate_window or []:
        start, end = _bound(start_text, "--deliberate-window"), _bound(end_text, "--deliberate-window")
        if start is None or end is None or end <= start:
            raise SystemExit("--deliberate-window : DEBUT < FIN attendus.")
        windows.append((start, end))
    path = Path(args.trace) if args.trace else default_trace(args.runtime_dir)
    if not path.is_file():
        print("Journal introuvable (runtime/trace.jsonl) : rien à mesurer. Vérifiez --runtime-dir ou --trace.", file=sys.stderr)
        return 2
    report = build_report(path, since=since, until=until, echo_window_s=args.echo_window_s, tail_s=args.tail_s,
                          deliberate_windows=windows, no_deliberate=args.no_deliberate_activation)
    encoded = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output_json:
        Path(args.output_json).write_text(encoded + "\n", encoding="utf-8")
    print(encoded if args.json else render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
