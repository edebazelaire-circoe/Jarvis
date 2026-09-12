#!/usr/bin/env python3
"""Chiffres publiés du banc d'essai, re-dérivés des résultats JSON.

    python scripts/speaker_benchmark_figures.py            # tous les chiffres cités
    python scripts/speaker_benchmark_figures.py --scenarios  # + le détail par scénario
    python scripts/speaker_benchmark_figures.py --key strict.campplus-zh-en-advanced.eer_pct

Aucun chiffre du banc n'est recopié à la main dans la documentation : chaque
valeur citée par `docs/results/speaker-benchmark/README.md`,
`docs/fixes/solo-owner-duplex/final-implementation-report.md` et
`docs/OPERATIONS.md` sort d'ici, et
`tests/unit/test_published_benchmark_figures.py` échoue si une page et son JSON
divergent. Les clés sont `<run>.<moteur>.<mesure>` ; chaque ligne imprimée dit
son fichier source et le chemin JSON exact.

Règle de sûreté : une mesure absente du JSON lève `KeyError` au lieu de se
formater en « 0.0 ». Un chiffre publié doit venir d'une clé réellement présente,
sinon la garde validerait un zéro inventé.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "docs" / "results" / "speaker-benchmark"

#: Les campagnes publiées, du nom court utilisé dans les clés vers leur fichier.
#: Le bloc de porte (`gate_*`) n'existe que dans la campagne stricte : c'est elle
#: qui a été lancée avec `--gate-thresholds`.
RUNS = {
    "strict": "2026-09-12-synthetic.json",
    "settled": "2026-09-12-synthetic-settled.json",
    "strict-2026-09-11": "2026-09-11-synthetic.json",
    "settled-2026-09-11": "2026-09-11-synthetic-settled.json",
}

#: Le moteur de production : les ratios de coût publiés le prennent pour référence.
BASELINE_ENGINE = "campplus-zh-en-advanced"

#: Mesures de `resources` publiées telles quelles, avec leur arrondi d'affichage.
RESOURCE_FIGURES = {
    "scoring_hop_ms_p50": (("scoring_hop_ms", "p50"), 1),
    "scoring_hop_ms_p95": (("scoring_hop_ms", "p95"), 1),
    "hop_ms_p50": (("hop_ms", "p50"), 2),
    "hop_ms_p95": (("hop_ms", "p95"), 1),
    "cpu_pct_one_core": (("cpu_pct_one_core",), 2),
    "model_verify_ms": (("model_verify_ms",), 1),
    "model_load_ms": (("model_load_ms",), 1),
    "rss_steady_delta_mb": (("rss_steady_delta_mb",), 1),
}

#: Scores par scénario (et par étiquette) cités dans les observations de la page.
SCENARIO_SCORES = ("owner_score_mean", "owner_score_min", "non_owner_score_mean", "non_owner_score_max")
#: Comment agréger chaque score sur tous les scénarios portant la même étiquette.
TAG_AGGREGATES = {
    "owner_score_mean": lambda xs: sum(xs) / len(xs),
    "owner_score_min": min,
    "non_owner_score_mean": lambda xs: sum(xs) / len(xs),
    "non_owner_score_max": max,
}

#: Mesures du bloc de porte citées seuil par seuil.
GATE_FIGURES = (
    "owner_events",
    "non_owner_events",
    "gate_confirm_ms_p50",
    "gate_confirm_ms_p95",
    "owner_events_forwarded",
    "owner_gate_miss_rate",
    "owner_forwarded_ratio",
    "openings",
    "false_opens",
    "non_owner_events_opened",
    "non_owner_forwarded_ms",
    "non_owner_run_ms_max",
    "noise_forwarded_ms",
    "short_confirmations",
    "owner_start_lost_ms_p95",
    "replays_clamped",
)

#: Taux par fenêtre cités seuil par seuil (balayage : score de fenêtre pleine).
SWEEP_RATES = ("far", "frr", "owner_miss_rate")
#: Latences de confirmation du vérificateur seul, seuil par seuil.
SWEEP_LATENCIES = ("confirm_ms_p50", "confirm_ms_p95")
#: Décomptes bruts du balayage cités dans les observations (bruit accepté,
#: événements de chevauchement confirmés).
SWEEP_COUNTS = ("noise_hops", "noise_hops_accepted", "overlap_events", "overlap_events_confirmed")
#: Décomptes du bloc `at_engine_threshold` cités dans les observations.
AT_ENGINE_COUNTS = ("noise_hops", "noise_hops_accepted", "non_owner_events", "non_owner_events_false_accepted")
#: Mesures du point de fonctionnement « zéro fausse acceptation », colonne par colonne.
ZERO_FA_FIGURES = {
    "threshold": ("threshold", 2, False),
    "frr_pct": ("frr", 1, True),
    "owner_miss_pct": ("owner_miss_rate", 1, True),
    "confirm_ms_p95": ("confirm_ms_p95", 0, False),
}


def _number(value: object, digits: int) -> str:
    """Chiffre formaté comme la documentation l'imprime (jamais de zéro perdu)."""

    if value is None:
        return "—"
    if digits == 0:
        return f"{float(value):.0f}"
    return f"{float(value):.{digits}f}"


def _dig(mapping: object, path: tuple[str, ...], source: str) -> object:
    """Descend un chemin JSON. Clé absente → `KeyError` : jamais un zéro inventé."""

    value = mapping
    for step in path:
        if not isinstance(value, dict) or step not in value:
            raise KeyError(f"{source}: {'.'.join(path)} absent du résultat publié")
        value = value[step]
    return value


def _pct(mapping: object, key: str, digits: int, source: str) -> str:
    """Un taux 0–1 imprimé en pourcentage ; `None` reste « — », l'absence lève."""

    value = _dig(mapping, (key,), source)
    return "—" if value is None else _number(float(value) * 100, digits)


def figures(results_dir: Path = RESULTS) -> dict[str, str]:
    """`<campagne>.<moteur>.<mesure>` → valeur formatée, lue dans les JSON publiés."""

    out: dict[str, str] = {}
    for run, filename in RUNS.items():
        path = results_dir / filename
        if not path.is_file():
            continue
        result = json.loads(path.read_text(encoding="utf-8"))
        out[f"{run}.manifest.scenarios"] = str(result["manifest"]["scenarios"])
        out[f"{run}.manifest.audio_s"] = _number(result["manifest"]["audio_ms"] / 1000.0, 1)
        cpu: dict[str, float] = {}
        for engine in result["engines"]:
            name = engine["name"]
            prefix = f"{run}.{name}"
            src = f"{filename} engines[{name}]"
            resources = engine.get("resources") or {}
            if resources:
                for key, (path_in_json, digits) in RESOURCE_FIGURES.items():
                    out[f"{prefix}.{key}"] = _number(_dig(resources, path_in_json, src), digits)
                cpu[name] = float(_dig(resources, ("cpu_pct_one_core",), src))
            out[f"{prefix}.embedding_dim"] = str(_dig(engine, ("engine", "embedding_dim"), src))
            eer = engine.get("eer") or {}
            if eer:
                out[f"{prefix}.eer_pct"] = _pct(eer, "eer", 1, src)
            engine_block = engine.get("at_engine_threshold") or {}
            if engine_block:
                out[f"{prefix}.at_engine.threshold"] = _number(_dig(engine_block, ("threshold",), src), 2)
                out[f"{prefix}.at_engine.far_pct"] = _pct(engine_block, "far", 1, src)
                out[f"{prefix}.at_engine.frr_pct"] = _pct(engine_block, "frr", 1, src)
                for key in AT_ENGINE_COUNTS:
                    out[f"{prefix}.at_engine.{key}"] = _number(_dig(engine_block, (key,), src), 0)
            zero_fa = (engine.get("operating_points") or {}).get("zero_false_accept")
            for key, (json_key, digits, is_rate) in ZERO_FA_FIGURES.items():
                if not zero_fa:
                    # Aucun seuil balayé n'atteint zéro fausse acceptation : la page
                    # écrit « none usable », pas un chiffre. On publie le tiret.
                    out[f"{prefix}.zero_false_accept.{key}"] = "—"
                elif is_rate:
                    out[f"{prefix}.zero_false_accept.{key}"] = _pct(zero_fa, json_key, digits, src)
                else:
                    out[f"{prefix}.zero_false_accept.{key}"] = _number(_dig(zero_fa, (json_key,), src), digits)
            for row in engine.get("sweep") or ():
                at = f"{prefix}@{_number(row['threshold'], 2)}"
                for key in SWEEP_RATES:
                    out[f"{at}.{key}_pct"] = _pct(row, key, 1, src)
                for key in SWEEP_LATENCIES:
                    out[f"{at}.{key}"] = _number(_dig(row, (key,), src), 0)
                for key in SWEEP_COUNTS:
                    out[f"{at}.{key}"] = _number(_dig(row, (key,), src), 0)
            for row in engine.get("gate_sweep") or ():
                at = f"{prefix}@{_number(row['threshold'], 2)}"
                for key in GATE_FIGURES:
                    value = _dig(row, (key,), src)
                    digits = 0 if key.endswith(("_ms", "_ms_p50", "_ms_p95", "_max")) or isinstance(value, int) else 1
                    out[f"{at}.{key}"] = _number(value, digits)
                out[f"{at}.owner_gate_miss_pct"] = _pct(row, "owner_gate_miss_rate", 1, src)
                out[f"{at}.owner_forwarded_pct"] = _pct(row, "owner_forwarded_ratio", 1, src)
                out[f"{at}.non_owner_forwarded_s"] = _number(_dig(row, ("non_owner_forwarded_ms",), src) / 1000.0, 1)
                out[f"{at}.non_owner_run_s_max"] = _number(_dig(row, ("non_owner_run_ms_max",), src) / 1000.0, 1)
                out[f"{at}.owner_start_lost_s_p95"] = _number(_dig(row, ("owner_start_lost_ms_p95",), src) / 1000.0, 2)
            out.update(_scenario_figures(engine.get("scenarios") or (), prefix, src))
        # Le coût relatif publié (« 2.4× le CPU du moteur de production ») sort des
        # deux mesures, pas d'une division faite à la main dans la page.
        baseline_cpu = cpu.get(BASELINE_ENGINE)
        if baseline_cpu:
            for name, value in cpu.items():
                out[f"{run}.{name}.cpu_ratio_vs_baseline"] = _number(value / baseline_cpu, 1)
    return out


def _scenario_figures(scenarios: object, prefix: str, source: str) -> dict[str, str]:
    """Scores par scénario, plus leur agrégat par étiquette (`tags`).

    La page cite les deux : « 0.65 dans un chevauchement de 3 s » est un scénario
    nommé, « moyenne ≈ 0.75 » est l'agrégat de l'étiquette `owner_far` sur les
    trois profils. Les deux doivent sortir du JSON, pas d'une lecture à l'œil.
    """

    out: dict[str, str] = {}
    grouped: dict[str, dict[str, list[float]]] = {}
    for scenario in scenarios:
        name = _dig(scenario, ("name",), source)
        for key in SCENARIO_SCORES:
            value = _dig(scenario, (key,), source)
            out[f"{prefix}.scenario.{name}.{key}"] = _number(value, 2)
            if value is None:
                continue
            for tag in scenario.get("tags") or ():
                grouped.setdefault(tag, {}).setdefault(key, []).append(float(value))
    for tag, measures in grouped.items():
        for key, values in measures.items():
            out[f"{prefix}.tag.{tag}.{key}"] = _number(TAG_AGGREGATES[key](values), 2)
    return out


def series(key: str, *, run: str, engine: str, thresholds: list[float], results_dir: Path = RESULTS) -> list[str]:
    """La même mesure sur plusieurs seuils, dans l'ordre : utile aux phrases du rapport."""

    values = figures(results_dir)
    return [values[f"{run}.{engine}@{_number(t, 2)}.{key}"] for t in thresholds]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results-dir", type=Path, default=RESULTS, help="dossier des résultats publiés")
    parser.add_argument("--key", action="append", help="n'imprimer que ces clés (répétable)")
    parser.add_argument(
        "--scenarios",
        action="store_true",
        help="inclure le détail scénario par scénario (39 par moteur), sinon seuls les agrégats",
    )
    args = parser.parse_args(argv)
    # Sortie lisible aussi dans une console cp1252 (git-bash, cmd.exe).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    values = figures(args.results_dir)
    if not values:
        print(f"aucun résultat dans {args.results_dir}", file=sys.stderr)
        return 2
    listed = sorted(values) if args.scenarios else sorted(k for k in values if ".scenario." not in k)
    wanted = args.key or listed
    missing = [key for key in wanted if key not in values]
    if missing:
        print(f"clés inconnues : {missing}", file=sys.stderr)
        return 2
    current = None
    for key in wanted:
        run = key.split(".", 1)[0]
        if run != current:
            current = run
            print(f"\n# {run} — {RUNS.get(run, '?')}")
        print(f"{key} = {values[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
