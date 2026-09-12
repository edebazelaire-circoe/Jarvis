"""Résumé Solo Owner du journal de bord (`runtime/trace.jsonl`), tâche 14.

La recette matérielle demande des chiffres, pas une lecture de 6 Mo de JSONL :
délais de confirmation du propriétaire, latence d'arrêt local au barge-in,
rejeux tronqués, entrées écartées, refus d'autorisation, contexte de travail
partagé avec l'interface. Ce module ne lit que des **scalaires** déjà présents
dans le journal : aucune transcription, aucun audio, aucune empreinte vocale
n'est lue ni affichée, même si la trace en contient par ailleurs.

    python scripts/summarize_voice_trace.py runtime/trace.jsonl
    python scripts/summarize_voice_trace.py runtime/trace.jsonl --json --since 2026-09-12

Une ligne illisible est comptée, jamais fatale : une trace en cours d'écriture
se termine souvent par une ligne partielle.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys
from typing import Any, Iterable, Iterator, Sequence

#: Évènements lus, et pour chacun les mesures résumées en percentiles.
OWNER_CANDIDATE = "voice.owner.candidate"
OWNER_CONFIRMED = "voice.owner.confirmed"
OWNER_REJECTED = "voice.owner.rejected"
OWNER_UNAVAILABLE = "voice.owner.unavailable"
OWNER_OVERRUN = "voice.owner.overrun"
OWNER_REPLAY = "voice.owner.replay"
BARGE_IN_OWNER_CONFIRMED = "voice.barge_in.owner_confirmed"
BARGE_IN_PROVIDER_ADVISORY = "voice.barge_in.provider_advisory"
BARGE_IN_AUTHORITY = "voice.barge_in.authority"
INPUT_NON_OWNER_DROPPED = "voice.input.non_owner_dropped"
AUTHORIZATION_REFUSED = "voice.authorization_refused"
AUTHORIZATION_INVALID = "voice.authorization_invalid"
BRAIN_WORK_CONTEXT = "core.brain.work_context"
WORK_ATTENTION = "core.work.attention"
WORK_UPDATED = "core.work.updated"

#: Mesures résumées par évènement : nom du champ dans `data`.
_LATENCIES: dict[str, tuple[str, ...]] = {
    OWNER_CONFIRMED: ("confirm_ms", "evidence_ms", "owner_score"),
    BARGE_IN_OWNER_CONFIRMED: (
        "confirm_ms",
        "confirm_to_stop_ms",
        "onset_to_stop_ms",
        "stop_latency_ms",
        "owner_score",
        "provider_lead_ms",
    ),
    OWNER_REPLAY: ("replay_ms", "clamped_ms", "already_sent_ms", "confirm_to_replay_ms"),
    OWNER_REJECTED: ("episode_ms", "best_score"),
    BARGE_IN_PROVIDER_ADVISORY: ("lag_ms", "replay_ms"),
}


#: Ce qu'un champ libre du journal a le droit de devenir ici : un identifiant
#: court. Même règle que `control_center._voice_capture_report`. Aucun émetteur
#: n'écrit aujourd'hui de phrase dans `reason`/`code`/`phase`/`store_id`, mais le
#: résumé promet des scalaires : il les impose plutôt que d'y compter.
_LABEL_MAX = 64
_LABEL_ALLOWED = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_./-")


def label(value: object, default: str = "?") -> str:
    """Étiquette sûre : minuscules, 64 caractères, `[a-z0-9_./-]` seulement."""

    if value is None:
        return default
    text = "".join(char for char in str(value).lower() if char in _LABEL_ALLOWED)[:_LABEL_MAX]
    return text or default


def percentile(values: Sequence[float], q: float) -> float | None:
    """Percentile par interpolation linéaire entre rangs (comme le banc d'essai)."""

    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * q / 100.0
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def summarize_values(values: Sequence[float]) -> dict[str, object]:
    return {
        "count": len(values),
        "p50": _round(percentile(values, 50)),
        "p95": _round(percentile(values, 95)),
        "max": _round(max(values)) if values else None,
    }


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 3)


def read_events(lines: Iterable[str]) -> Iterator[tuple[dict[str, Any], int]]:
    """Chaque entrée JSON du journal, et le nombre de lignes illisibles."""

    unreadable = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            unreadable += 1
            continue
        if isinstance(payload, dict) and isinstance(payload.get("kind"), str):
            yield payload, unreadable
            unreadable = 0
    if unreadable:
        yield {}, unreadable


def summarize(lines: Iterable[str], *, since: str | None = None) -> dict[str, object]:
    """Résumé Solo Owner d'une trace ; seuls des scalaires sont lus."""

    counts: Counter[str] = Counter()
    measures: dict[str, dict[str, list[float]]] = {kind: {} for kind in _LATENCIES}
    drops: Counter[str] = Counter()
    rejects: Counter[str] = Counter()
    codes: Counter[str] = Counter()
    refusals: Counter[str] = Counter()
    stores: set[str] = set()
    revisions: list[float] = []
    provider_started = 0
    clamped = 0
    unreadable = 0
    first = last = None
    for payload, bad in read_events(lines):
        unreadable += bad
        kind = payload.get("kind")
        if not isinstance(kind, str):
            continue
        stamp = payload.get("ts")
        if since is not None and isinstance(stamp, str) and stamp < since:
            continue
        if isinstance(stamp, str):
            first = stamp if first is None else min(first, stamp)
            last = stamp if last is None else max(last, stamp)
        counts[kind] += 1
        data = payload.get("data")
        data = data if isinstance(data, dict) else {}
        for field in _LATENCIES.get(kind, ()):  # scalaires seulement
            value = data.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                measures[kind].setdefault(field, []).append(float(value))
        if kind == INPUT_NON_OWNER_DROPPED:
            drops[f"{label(data.get('source'))}/{label(data.get('reason'))}"] += 1
        elif kind == OWNER_REJECTED:
            rejects[label(data.get("reason"))] += 1
        elif kind in (OWNER_UNAVAILABLE, OWNER_OVERRUN, AUTHORIZATION_INVALID):
            codes[label(data.get("code"))] += 1
        elif kind == AUTHORIZATION_REFUSED:
            refusals[f"{label(data.get('phase'))}/{label(data.get('code'))}"] += 1
        elif kind == BARGE_IN_OWNER_CONFIRMED:
            provider_started += int(bool(data.get("provider_speech_started")))
        elif kind == OWNER_REPLAY:
            value = data.get("clamped_ms")
            clamped += int(isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0)
        elif kind == BRAIN_WORK_CONTEXT:
            store = data.get("store_id")
            if isinstance(store, str):
                stores.add(label(store))
            revision = data.get("revision")
            if isinstance(revision, (int, float)) and not isinstance(revision, bool):
                revisions.append(float(revision))
    return {
        "events": {kind: counts[kind] for kind in sorted(counts) if kind.startswith(("voice.", "core."))},
        "window": {"first": first, "last": last, "unreadable_lines": unreadable},
        "owner": {
            "candidates": counts[OWNER_CANDIDATE],
            "confirmed": counts[OWNER_CONFIRMED],
            "rejected": counts[OWNER_REJECTED],
            "reject_reasons": dict(rejects),
            "confirm_ms": summarize_values(measures[OWNER_CONFIRMED].get("confirm_ms", [])),
            "owner_score": summarize_values(measures[OWNER_CONFIRMED].get("owner_score", [])),
            "unavailable_codes": dict(codes),
        },
        "barge_in": {
            "owner_cuts": counts[BARGE_IN_OWNER_CONFIRMED],
            "with_provider_speech": provider_started,
            "confirm_ms": summarize_values(measures[BARGE_IN_OWNER_CONFIRMED].get("confirm_ms", [])),
            "onset_to_stop_ms": summarize_values(measures[BARGE_IN_OWNER_CONFIRMED].get("onset_to_stop_ms", [])),
            "stop_latency_ms": summarize_values(measures[BARGE_IN_OWNER_CONFIRMED].get("stop_latency_ms", [])),
            "provider_lag_ms": summarize_values(measures[BARGE_IN_PROVIDER_ADVISORY].get("lag_ms", [])),
        },
        "replay": {
            "count": counts[OWNER_REPLAY],
            "replay_ms": summarize_values(measures[OWNER_REPLAY].get("replay_ms", [])),
            "clamped": clamped,
            "clamped_ms": summarize_values(measures[OWNER_REPLAY].get("clamped_ms", [])),
        },
        "input_gate": {"dropped": dict(drops), "refusals": dict(refusals)},
        "work_state": {
            "brain_contexts": counts[BRAIN_WORK_CONTEXT],
            "store_ids": sorted(stores),
            "revision": summarize_values(revisions),
            "attention": counts[WORK_ATTENTION],
            "updates": counts[WORK_UPDATED],
        },
    }


def render(summary: dict[str, Any]) -> str:
    """Rendu texte compact : ce qu'on lit après une session de recette."""

    owner = summary["owner"]
    barge = summary["barge_in"]
    replay = summary["replay"]
    gate = summary["input_gate"]
    work = summary["work_state"]
    window = summary["window"]
    lines = [
        f"Fenêtre : {window['first']} → {window['last']} ({window['unreadable_lines']} ligne(s) illisible(s))",
        "",
        f"Propriétaire  candidats {owner['candidates']} · confirmés {owner['confirmed']} · écartés {owner['rejected']} "
        f"{owner['reject_reasons'] or ''}",
        f"  confirmation (ms) {_fmt(owner['confirm_ms'])}",
        f"  score            {_fmt(owner['owner_score'])}",
        f"  indisponibilités {owner['unavailable_codes'] or 'aucune'}",
        "",
        f"Barge-in      coupures {barge['owner_cuts']} · avec speech_started fournisseur {barge['with_provider_speech']}",
        f"  onset → confirmation (ms) {_fmt(barge['confirm_ms'])}",
        f"  onset → arrêt local  (ms) {_fmt(barge['onset_to_stop_ms'])}",
        f"  appel d'arrêt        (ms) {_fmt(barge['stop_latency_ms'])}",
        f"  retard fournisseur   (ms) {_fmt(barge['provider_lag_ms'])}",
        "",
        f"Rejeu         {replay['count']} · tronqués {replay['clamped']}",
        f"  rejoué (ms) {_fmt(replay['replay_ms'])}",
        f"  perdu  (ms) {_fmt(replay['clamped_ms'])}",
        "",
        f"Entrée        écartées {gate['dropped'] or 'aucune'}",
        f"  refus       {gate['refusals'] or 'aucun'}",
        "",
        f"État de travail  contextes cerveau {work['brain_contexts']} · mises à jour {work['updates']} · "
        f"attention {work['attention']}",
        f"  store_id {work['store_ids'] or 'aucun'} · révision {_fmt(work['revision'])}",
    ]
    return "\n".join(lines)


def _fmt(values: dict[str, Any]) -> str:
    if not values["count"]:
        return "—"
    return f"n={values['count']} p50={values['p50']} p95={values['p95']} max={values['max']}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="summarize_voice_trace",
        description="Solo Owner summary of runtime/trace.jsonl (scalars only, never transcripts).",
    )
    parser.add_argument("trace", type=Path, nargs="?", help="Trace file (default: runtime/trace.jsonl)")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    parser.add_argument("--since", help="Keep entries whose ISO timestamp sorts at or after this prefix")
    args = parser.parse_args(argv)
    # Le rendu contient « → », « · » et « — » : sur une console cp1252
    # (git-bash, cmd.exe) l'écriture lèverait `UnicodeEncodeError` juste après
    # une session de recette. On passe la sortie en UTF-8, tolérante.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass
    path = args.trace or Path("runtime/trace.jsonl")
    try:
        with Path(path).open("r", encoding="utf-8", errors="replace") as handle:
            summary = summarize(handle, since=args.since)
    except OSError as exc:
        print(f"Trace illisible ({path}) : {type(exc).__name__} [trace_unreadable]", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2) if args.json else render(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
