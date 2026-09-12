"""Les chiffres du banc publiés dans la documentation sortent des JSON publiés.

Chaque test ci-dessous relit un fichier de `docs/results/speaker-benchmark/` par
`scripts/speaker_benchmark_figures.py` et vérifie que la page qui le cite affiche
exactement cette valeur. Aucun chiffre recopié à la main ne survit à une
re-génération du banc : si un résultat change et qu'une page ne suit pas, ce
fichier échoue et nomme la clé fautive.

Les tableaux sont comparés **cellule par cellule, en position** : une colonne de
moteur permutée, une ligne entière substituée ou un seul décompte retouché font
échouer le test, alors qu'une recherche « la chaîne apparaît quelque part dans la
page » laissait passer les trois (défaut R2 de la revue 2).

Rappel d'honnêteté : ces résultats sont synthétiques (voix de synthèse Windows)
et ne valident aucun seuil de production — les tests ci-dessous vérifient la
concordance page ↔ artefact, pas la validité de la mesure. Ce qui reste hors
garde est nommé dans le paragraphe « What is not » du README des résultats : les
ordres de grandeur écrits avec `≈` ou sous forme d'intervalle.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
import json
from pathlib import Path

import pytest

from scripts.speaker_benchmark_figures import figures

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "docs" / "results" / "speaker-benchmark"
README = RESULTS / "README.md"
REPORT = ROOT / "docs" / "fixes" / "solo-owner-duplex" / "final-implementation-report.md"
OPERATIONS = ROOT / "docs" / "OPERATIONS.md"

BASELINE = "campplus-zh-en-advanced"
CANDIDATE = "eres2net-en-voxceleb"
GATE_THRESHOLDS = ("0.45", "0.50", "0.55", "0.60", "0.65", "0.70", "0.75")
#: Les huit moteurs de la campagne 2026-09-11, dans l'ordre du tableau publié.
ENGINES_2026_09_11 = (
    "campplus-zh-en-advanced",
    "campplus-zh-cn-common",
    "campplus-en-voxceleb",
    "eres2net-en-voxceleb",
    "eres2net-base-200k-zh-cn",
    "eres2net-base-3dspeaker",
    "eres2netv2-zh-cn",
    "wespeaker-resnet34-en-voxceleb",
)


@pytest.fixture(scope="module")
def values() -> dict[str, str]:
    derived = figures(RESULTS)
    assert derived, "aucun résultat publié : la documentation citerait des chiffres sans source"
    return derived


def read(page: Path) -> str:
    return page.read_text(encoding="utf-8")


def flowed(page: Path) -> str:
    """Le texte sans ses retours à la ligne ni son gras : une phrase coupée reste comparable."""

    return " ".join(read(page).replace("**", "").split())


def section(page: Path, heading: str) -> str:
    """Le corps d'une section `##`, pour ne pas confondre deux campagnes qui citent les mêmes moteurs."""

    body = read(page).split(heading, 1)
    assert len(body) == 2, heading
    return body[1].split("\n## ", 1)[0]


def cells(line: str) -> list[str]:
    """Les cellules d'une ligne de tableau Markdown, gras retiré, dans l'ordre."""

    return [cell.strip() for cell in line.replace("**", "").strip().strip("|").split("|")]


def table(text: str, first_header_cell: str) -> tuple[list[str], list[list[str]]]:
    """L'en-tête et les lignes du tableau dont la première colonne s'appelle ainsi.

    Retourner les cellules *en position* est tout l'intérêt : une assertion « la
    valeur est quelque part dans la page » ne voit pas une permutation de
    colonnes ni une ligne déplacée.
    """

    lines = text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.startswith("|") and cells(line)[:1] == [first_header_cell]),
        None,
    )
    assert start is not None, f"tableau « {first_header_cell} » introuvable"
    header = cells(lines[start])
    assert set(cells(lines[start + 1])) == {"---"}, "la ligne de séparation attendue manque"
    rows = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        rows.append(cells(line))
    assert rows, f"tableau « {first_header_cell} » sans ligne"
    return header, rows


def grouped_ms(value: str) -> str:
    """Une durée en ms comme la page la groupe : « 11 100 », « 700 »."""

    return f"{int(float(value)):,}".replace(",", " ")


def rounded(value: str, digits: int) -> str:
    """La valeur arrondie comme une main l'arrondit : demi vers le haut, en décimal.

    Les colonnes entières du tableau 2026-09-11 réduisent une mesure déjà arrondie
    au dixième (186.5 → 187). Passer par `float` la rendrait à `186` : le binaire
    et l'arrondi banquier de Python ne sont pas la règle appliquée à la page.
    """

    quantum = Decimal(1).scaleb(-digits)
    return str(Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP))


def engine_of(cell: str) -> str:
    """Le nom du moteur d'une cellule « campplus-… (192, production baseline) »."""

    return cell.split()[0]


# --------------------------------------------------------------------------- #
# Les artefacts eux-mêmes
# --------------------------------------------------------------------------- #


def test_the_result_files_the_docs_name_are_all_there():
    for name in ("2026-09-12-synthetic", "2026-09-12-synthetic-settled", "2026-09-11-synthetic", "2026-09-11-synthetic-settled"):
        for suffix in (".json", ".csv", ".md"):
            assert (RESULTS / f"{name}{suffix}").is_file(), f"{name}{suffix}"


def test_every_synthetic_result_keeps_its_disclaimer():
    """Un chiffre synthétique publié sans son avertissement serait pire qu'un chiffre faux."""

    for path in RESULTS.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["evidence"] == "synthetic"
        assert "NOT evidence for production thresholds" in (payload["disclaimer"] or "")
    for page in (read(README), read(REPORT)):
        assert "SYNTHETIC" in page or "synthetic" in page


def test_a_missing_metric_is_an_error_not_a_zero(tmp_path):
    """`_number((row.get(k) or 0) * 100)` transformait une clé absente en « 0.0 »."""

    payload = json.loads((RESULTS / "2026-09-12-synthetic-settled.json").read_text(encoding="utf-8"))
    payload["engines"][0]["resources"].pop("cpu_pct_one_core")
    (tmp_path / "2026-09-12-synthetic-settled.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(KeyError, match="cpu_pct_one_core"):
        figures(tmp_path)


# --------------------------------------------------------------------------- #
# Campagne 2026-09-12 : tableau de porte, tableau de coût
# --------------------------------------------------------------------------- #


def test_the_gate_table_of_the_readme_matches_the_strict_gate_sweep_cell_by_cell(values):
    """Les sept lignes, les neuf colonnes, en position : rien n'est cherché « quelque part »."""

    body = section(README, "\n## 2026-09-12 — synthetic")
    header, rows = table(body, "Engine")
    assert header == [
        "Engine",
        "Thr.",
        "Hop FAR / FRR (strict)",
        "EER strict / settled",
        "Gate: owner turns forwarded",
        "Gate: openings (false)",
        "Gate: non-owner events opened",
        "Gate: leaked ms (max run)",
        "Gate: confirm P50 / P95",
    ]
    expected_rows = (
        (BASELINE, "0.50"),
        (BASELINE, "0.55"),
        (BASELINE, "0.60"),
        (BASELINE, "0.65"),
        (CANDIDATE, "0.50"),
        (CANDIDATE, "0.60"),
        (CANDIDATE, "0.65"),
    )
    assert len(rows) == len(expected_rows)
    seen: set[str] = set()
    for row, (engine, threshold) in zip(rows, expected_rows, strict=True):
        at = f"strict.{engine}@{threshold}"
        assert engine_of(row[0]) == engine, row
        assert row[1].split()[0] == f"{float(threshold):g}", row
        assert row[2] == f"{values[f'{at}.far_pct']} % / {values[f'{at}.frr_pct']} %", at
        # L'EER ne dépend pas du seuil : la page ne l'écrit qu'une fois par moteur.
        if engine in seen:
            assert row[3] == "—", at
        else:
            assert row[3] == f"{values[f'strict.{engine}.eer_pct']} % / {values[f'settled.{engine}.eer_pct']} %", at
            seen.add(engine)
        forwarded = f"{values[f'{at}.owner_events_forwarded']}/{values[f'{at}.owner_events']}"
        miss = values[f"{at}.owner_gate_miss_pct"]
        assert row[4] == (forwarded if miss == "0.0" else f"{forwarded} (miss {miss} %)"), at
        assert row[5] == f"{values[f'{at}.openings']} ({values[f'{at}.false_opens']})", at
        assert row[6] == f"{values[f'{at}.non_owner_events_opened']}/{values[f'{at}.non_owner_events']}", at
        leaked = grouped_ms(values[f"{at}.non_owner_forwarded_ms"])
        run_max = grouped_ms(values[f"{at}.non_owner_run_ms_max"])
        assert row[7] == f"{leaked} ({run_max})", at
        assert row[8] == f"{values[f'{at}.gate_confirm_ms_p50']} / {values[f'{at}.gate_confirm_ms_p95']}", at


#: Ligne du tableau de coût → clé de `figures()` et forme imprimée.
COST_ROWS = {
    "Scoring hop P50 (`scoring_hop_ms.p50`)": ("scoring_hop_ms_p50", "{} ms"),
    "CPU, share of one core (`cpu_pct_one_core`)": ("cpu_pct_one_core", "{} %"),
    "Model load (`model_load_ms`)": ("model_load_ms", "{} ms"),
    "Steady RSS delta (`rss_steady_delta_mb`)": ("rss_steady_delta_mb", "+{} MB"),
}


def test_the_cost_table_of_the_readme_is_anchored_per_row_and_per_engine_column(values):
    """Permuter les deux colonnes de moteurs doit échouer, pas passer inaperçu."""

    header, rows = table(section(README, "\n## 2026-09-12 — synthetic"), "Figure (`resources` key)")
    assert header[1:] == [BASELINE, CANDIDATE], header
    assert [row[0] for row in rows] == list(COST_ROWS), rows
    for row in rows:
        key, shape = COST_ROWS[row[0]]
        for column, engine in enumerate(header[1:], start=1):
            assert row[column] == shape.format(values[f"settled.{engine}.{key}"]), (row[0], engine)


def test_the_strict_run_is_quoted_as_an_order_of_magnitude_with_its_own_numbers(values):
    page = flowed(README)
    loads = " / ".join(f"{values[f'strict.{engine}.model_load_ms']} ms" for engine in (BASELINE, CANDIDATE))
    rss = " / ".join(f"+{values[f'strict.{engine}.rss_steady_delta_mb']} MB" for engine in (BASELINE, CANDIDATE))
    assert f"reports {loads} for the load" in page
    assert f"and {rss} of RSS" in page


def test_the_cost_cells_of_the_final_report_are_anchored_per_row(values):
    """Le tableau du rapport : une ligne par moteur, chaque cellule vérifiée."""

    header, rows = table(section(REPORT, "\n## Benchmark results"), "Engine")
    assert header == [
        "Engine",
        "EER strict / settled",
        "Gate at 0.5",
        "Gate at 0.6",
        "Gate at 0.65",
        "Cost (settled)",
    ]
    assert [engine_of(row[0]) for row in rows] == [BASELINE, CANDIDATE], rows
    for row in rows:
        engine = engine_of(row[0])
        assert row[1] == f"{values[f'strict.{engine}.eer_pct']} % / {values[f'settled.{engine}.eer_pct']} %"
        for column, threshold in ((2, "0.50"), (3, "0.60"), (4, "0.65")):
            at = f"strict.{engine}@{threshold}"
            assert f"{values[f'{at}.false_opens']} false opens" in row[column], at
            assert f"{values[f'{at}.non_owner_events_opened']}/{values[f'{at}.non_owner_events']}" in row[column], at
            assert f"{values[f'{at}.non_owner_forwarded_s']} s" in row[column], at
            miss = values[f"{at}.owner_gate_miss_pct"]
            if miss != "0.0":
                assert f"miss {miss} %" in row[column], at
        cost = row[5]
        assert f"{values[f'settled.{engine}.scoring_hop_ms_p50']} ms/scoring hop" in cost
        assert f"{values[f'settled.{engine}.cpu_pct_one_core']} % core" in cost
        assert f"load {values[f'settled.{engine}.model_load_ms']} ms" in cost
        assert f"RSS +{values[f'settled.{engine}.rss_steady_delta_mb']} MB" in cost


def test_the_confirmation_latency_series_is_published_in_full(values):
    """« 1,6 s à tous les seuils » était faux : la série entière est publiée, dans l'ordre."""

    for page in (flowed(README), flowed(REPORT)):
        for engine in (BASELINE, CANDIDATE):
            series = [values[f"strict.{engine}@{t}.gate_confirm_ms_p50"] for t in GATE_THRESHOLDS]
            assert len({*series}) > 1  # la série n'est pas plate : la publier en entier a un sens
            assert ", ".join(series) in page


def test_the_short_reply_counts_are_the_published_ones_not_just_the_word(values):
    """R2 : comparer les décomptes. « only one … none » doit échouer, pas passer."""

    low = {values[f"strict.{BASELINE}@{t}.short_confirmations"] for t in ("0.45", "0.50", "0.55", "0.60", "0.65")}
    high = {values[f"strict.{BASELINE}@{t}.short_confirmations"] for t in ("0.70", "0.75")}
    assert len(low) == 1 and len(high) == 1, "la phrase publiée suppose deux paliers constants"
    assert low != high, "sans palier distinct la phrase n'aurait rien à dire"
    baseline = f"{low.pop()} from 0.45 to 0.65 and {high.pop()} at 0.70–0.75"
    candidate = (
        f"ERes2Net-VoxCeleb is already at {values[f'strict.{CANDIDATE}@0.60.short_confirmations']}"
        f" at the 0.6 default and at {values[f'strict.{CANDIDATE}@0.75.short_confirmations']} at 0.75"
    )
    for page in (flowed(README), flowed(REPORT)):
        assert baseline in page
        assert candidate in page
    for threshold in GATE_THRESHOLDS:
        for engine in (BASELINE, CANDIDATE):
            assert values[f"strict.{engine}@{threshold}.replays_clamped"] == "0"
    for page in (flowed(README), flowed(REPORT)):
        assert "replays_clamped` is 0 at every" in page


def test_the_owner_side_cost_of_the_new_default_is_published(values):
    """NB15 : le taux de rejet par fenêtre au seuil retenu ne doit pas disparaître derrière les 7,7 %."""

    page = read(REPORT)
    assert f"{values[f'strict.{BASELINE}.at_engine.frr_pct']} % strict" in page
    assert f"{values[f'settled.{BASELINE}.at_engine.frr_pct']} % settled" in page
    assert f"{values[f'strict.{BASELINE}@0.60.owner_gate_miss_pct']} %" in page
    assert f"{values[f'strict.{BASELINE}@0.60.owner_forwarded_pct']} %" in page
    # Et le libellé provisoire reste.
    assert "provisional pending real owner data" in page


def test_the_decision_paragraph_of_the_readme_quotes_the_gate_sweep(values):
    """Les chiffres du choix de seuil : 0.5 → 0.6, le repli 0.55, le rejet de 0.65."""

    page = flowed(README)
    low, default = f"strict.{BASELINE}@0.50", f"strict.{BASELINE}@0.60"
    high, fallback = f"strict.{BASELINE}@0.65", f"strict.{BASELINE}@0.55"
    assert f"during {values[f'{low}.non_owner_events_opened']} of the {values[f'{low}.non_owner_events']} colleague turns" in page
    assert f"forwarded {values[f'{low}.non_owner_forwarded_s']} s of their speech" in page
    assert f"with {values[f'{low}.false_opens']} openings" in page
    assert (
        f"drops to {values[f'{default}.non_owner_events_opened']} turn,"
        f" {values[f'{default}.non_owner_forwarded_s']} s and {values[f'{default}.false_opens']} such openings" in page
    )
    assert f"P50 moving from {values[f'{low}.gate_confirm_ms_p50']} to {values[f'{default}.gate_confirm_ms_p50']} ms" in page
    assert f"({values[f'{high}.owner_gate_miss_pct']} %)" in page
    assert f"loses {values[f'{high}.owner_start_lost_s_p95']} s of sentence start" in page
    assert f"(miss {values[f'{fallback}.owner_gate_miss_pct']} %, {values[f'{fallback}.owner_forwarded_pct']} % of his audio forwarded)" in page
    assert f"at {values[f'{fallback}.non_owner_run_s_max']} s instead of {values[f'{default}.non_owner_run_s_max']} s" in page
    assert f"the baseline reads {values[f'strict.{BASELINE}.at_engine.far_pct']} % / {values[f'strict.{BASELINE}.at_engine.frr_pct']} % at 0.6" in page
    assert f"at the gate, {values[f'{default}.owner_forwarded_pct']} % of his owner-only audio" in page
    # Le repli 0.55 résume le même gain en une flèche : elle aussi sort du balayage.
    assert (
        f"colleague turns opened ({values[f'{low}.non_owner_events_opened']}"
        f" → {values[f'{fallback}.non_owner_events_opened']})" in page
    )


def test_the_owner_cost_paragraph_of_the_readme_restates_only_published_figures(values):
    """R3 : les rappels en prose du FRR et des tours perdus sont comparés, pas seulement leur première occurrence."""

    page = flowed(README)
    default = f"strict.{BASELINE}@0.60"
    frr = values[f"strict.{BASELINE}.at_engine.frr_pct"]
    assert f"{frr} % is real." in page
    assert f"read {frr} % as the margin being spent" in page
    events = values[f"{default}.owner_events"]
    never = int(events) - int(values[f"{default}.owner_events_forwarded"])
    assert (
        f"{never} of his {events} turns are never forwarded at all"
        f" (miss {values[f'{default}.owner_gate_miss_pct']} %)" in page
    )


def test_the_cpu_ratio_between_the_two_engines_is_derived_not_eyeballed(values):
    """« 2.4× le CPU » est un rapport de deux mesures publiées, pas un chiffre rond."""

    ratio = values[f"settled.{CANDIDATE}.cpu_ratio_vs_baseline"]
    assert f"for {ratio}× the CPU" in flowed(README)
    assert f"at {ratio}× less CPU than ERes2Net-VoxCeleb" in flowed(REPORT)


def test_the_noise_figure_of_the_final_report_names_both_campaigns(values):
    page = flowed(REPORT)
    strict = f"strict.{BASELINE}.at_engine"
    settled = f"settled.{BASELINE}.at_engine"
    assert f"= {values[f'{strict}.noise_hops_accepted']} of {values[f'{strict}.noise_hops']} strict" in page
    assert f"/ {values[f'{settled}.noise_hops']} settled" in page
    assert f"produced {values[f'strict.{BASELINE}@0.60.noise_forwarded_ms']} ms of forwarded noise at 0.6" in page


# --------------------------------------------------------------------------- #
# Campagne 2026-09-11 : les huit moteurs, les huit colonnes
# --------------------------------------------------------------------------- #


def test_the_2026_09_11_table_matches_its_own_settled_json_row_by_row(values):
    """Les huit lignes entières : substituer la ligne `wespeaker` doit échouer."""

    header, rows = table(section(README, "\n## 2026-09-11 — synthetic"), "Engine (dim)")
    assert header == [
        "Engine (dim)",
        "EER strict / settled",
        "FAR / FRR @ 0.5 (settled)",
        "Confirm P50 / P95 @ 0.5",
        "Zero-FA thr. (settled) → FRR, miss, P95",
        "Scoring hop P50 ms*",
        "CPU % core*",
        "Load ms*",
    ]
    assert [engine_of(row[0]) for row in rows] == list(ENGINES_2026_09_11), rows
    for row in rows:
        engine = engine_of(row[0])
        run = f"settled-2026-09-11.{engine}"
        at = f"{run}@0.50"
        assert f"({values[f'{run}.embedding_dim']}" in row[0], engine
        assert row[1] == f"{values[f'strict-2026-09-11.{engine}.eer_pct']} % / {values[f'{run}.eer_pct']} %", engine
        assert row[2] == f"{values[f'{at}.far_pct']} % / {values[f'{at}.frr_pct']} %", engine
        assert row[3] == f"{values[f'{at}.confirm_ms_p50']} / {values[f'{at}.confirm_ms_p95']}", engine
        zero = f"{run}.zero_false_accept"
        frr = values[f"{zero}.frr_pct"]
        if frr == "100.0":
            # Aucun seuil balayé n'est utilisable : la page le dit au lieu d'imprimer un seuil.
            assert row[4] == f"none usable (FRR {frr} %)", engine
        else:
            assert row[4] == (
                f"{values[f'{zero}.threshold']} → {frr} %,"
                f" {values[f'{zero}.owner_miss_pct']} %, {values[f'{zero}.confirm_ms_p95']} ms"
            ), engine
        # Colonnes de coût : la page les arrondit à l'unité (et au dixième pour le CPU).
        assert row[5] == rounded(values[f"{run}.scoring_hop_ms_p50"], 0), engine
        assert row[6] == rounded(values[f"{run}.cpu_pct_one_core"], 1), engine
        assert row[7] == rounded(values[f"{run}.model_load_ms"], 0), engine


def test_the_confirmation_latency_observation_no_longer_claims_a_flat_p50(values):
    """R2 : « P50 = 1,6 s pour tous les moteurs » sous-entendait l'indépendance au seuil."""

    page = flowed(README)
    baseline = f"settled-2026-09-11.{BASELINE}"
    # La série réfute la lecture « indépendant du seuil » : elle doit bouger.
    p50 = [values[f"{baseline}@{t}.confirm_ms_p50"] for t in ("0.50", "0.75", "0.80", "0.90")]
    assert len({*p50}) > 1
    assert f"P50 = 1.6 s at 0.5 for every engine" in page
    assert f"baseline {values[f'{baseline}@0.75.confirm_ms_p50']} ms at 0.75 and at 0.80" in page
    assert values[f"{baseline}@0.75.confirm_ms_p50"] == values[f"{baseline}@0.80.confirm_ms_p50"]
    assert f"{values[f'{baseline}@0.90.confirm_ms_p50']} ms at 0.90" in page
    zh_cn = f"settled-2026-09-11.campplus-zh-cn-common@0.80.confirm_ms_p50"
    v2 = f"settled-2026-09-11.eres2netv2-zh-cn@0.85.confirm_ms_p50"
    assert f"campplus-zh-cn-common {values[zh_cn]} ms at 0.80" in page
    assert f"eres2netv2-zh-cn {values[v2]} ms at 0.85" in page
    p95 = [values[f"{baseline}@{t}.confirm_ms_p95"] for t in ("0.50", "0.65", "0.85")]
    assert f"baseline {p95[0]} ms at 0.5, {p95[1]} ms at 0.65, {p95[2]} ms at 0.85" in page


def test_the_noise_observation_is_true_of_all_eight_engines(values):
    """« 0 sur 354 pour les huit », et les seuls seuils balayés qui acceptent du bruit."""

    page = flowed(README)
    accepted_below: dict[str, float] = {}
    for engine in ENGINES_2026_09_11:
        run = f"settled-2026-09-11.{engine}"
        assert values[f"{run}.at_engine.noise_hops_accepted"] == "0", engine
        assert values[f"{run}.at_engine.noise_hops"] == values[f"settled-2026-09-11.{BASELINE}.at_engine.noise_hops"]
        for key, value in values.items():
            if key.startswith(f"{run}@") and key.endswith(".noise_hops_accepted") and value != "0":
                threshold = float(key.split("@", 1)[1].split(".noise", 1)[0])
                accepted_below[engine] = max(accepted_below.get(engine, 0.0), threshold)
                assert value == "11", key  # « 11 hops each »
    assert set(accepted_below) == {"campplus-zh-en-advanced", "campplus-en-voxceleb", "wespeaker-resnet34-en-voxceleb"}
    assert accepted_below == {
        "campplus-zh-en-advanced": 0.10,
        "campplus-en-voxceleb": 0.35,
        "wespeaker-resnet34-en-voxceleb": 0.05,
    }
    hops = values[f"settled-2026-09-11.{BASELINE}.at_engine.noise_hops"]
    assert f"= 0 of {hops} for all eight" in page
    # R3 : les seuils étaient vérifiés contre le JSON mais jamais contre la page.
    assert f"Only swept thresholds ≤ {max(accepted_below.values()):.2f} accept any at all" in page
    assert f"CAM++ zh-en advanced (≤ {accepted_below['campplus-zh-en-advanced']:.2f})" in page
    assert f"CAM++ VoxCeleb (≤ {accepted_below['campplus-en-voxceleb']:.2f})" in page
    assert f"ResNet34 (≤ {accepted_below['wespeaker-resnet34-en-voxceleb']:.2f}) — 11 hops each" in page


def test_the_overlap_confirmation_count_comes_from_the_sweep(values):
    """R3 : « All 9 overlap events were confirmed » n'avait aucune clé derrière lui."""

    page = flowed(README)
    baseline = f"settled-2026-09-11.{BASELINE}"
    events = {values[f"{baseline}@{t}.overlap_events"] for t in ("0.50", "0.65")}
    assert len(events) == 1, "la phrase publiée suppose le même décompte aux deux seuils"
    count = events.pop()
    for threshold in ("0.50", "0.65"):
        assert values[f"{baseline}@{threshold}.overlap_events_confirmed"] == count, threshold
    assert f"All {count} overlap events were confirmed by the baseline at 0.5 and at 0.65" in page


def test_the_first_two_observations_quote_the_artifacts_they_summarise(values):
    """Coût par hop, moteur le plus lent, faux accepts au seuil du moteur, taille du jeu."""

    page = flowed(README)
    assert f"one scoring hop ≈ {rounded(values[f'settled-2026-09-11.{BASELINE}.scoring_hop_ms_p50'], 0)} ms" in page
    slow = "eres2netv2-zh-cn"
    settled_p50 = rounded(values[f"settled-2026-09-11.{slow}.scoring_hop_ms_p50"], 0)
    strict_p50 = rounded(values[f"strict-2026-09-11.{slow}.scoring_hop_ms_p50"], 0)
    assert f"({settled_p50}–{strict_p50} ms per scoring hop" in page
    at_engine = f"settled-2026-09-11.{BASELINE}.at_engine"
    assert (
        f"(baseline: {values[f'{at_engine}.non_owner_events_false_accepted']} of"
        f" {values[f'{at_engine}.non_owner_events']} non-owner events)" in page
    )
    assert f"With a 1.5 s window, {values[f'settled-2026-09-11.{BASELINE}.zero_false_accept.threshold']} is the lowest" in page
    assert f"{values['settled-2026-09-11.manifest.scenarios']} scenarios" in page
    assert f"{rounded(values['settled-2026-09-11.manifest.audio_s'], 0)} s" in page


def test_the_scenario_scores_quoted_in_the_observations_come_from_the_scenarios_block(values):
    """Les scores par scénario étaient recopiés à la main : ils sortent maintenant du JSON."""

    page = flowed(README)
    run = f"settled-2026-09-11.{BASELINE}"
    overlap = values[f"{run}.scenario.hortense.overlap_3s.non_owner_score_max"]
    far = values[f"{run}.scenario.hortense.non_owner_far.non_owner_score_max"]
    assert f"up to {overlap} in a 3 s overlap, {far} far-field with reverberation" in page
    mean = values[f"{run}.tag.owner_far.owner_score_mean"]
    minimum = values[f"{run}.tag.owner_far.owner_score_min"]
    assert f"(mean ≈ {mean}, minimum {minimum})" in page


# --------------------------------------------------------------------------- #
# OPERATIONS.md
# --------------------------------------------------------------------------- #


def test_the_threshold_paragraph_of_operations_matches_the_gate_sweep(values):
    page = read(OPERATIONS)
    low, default = f"strict.{BASELINE}@0.50", f"strict.{BASELINE}@0.60"
    assert f"{values[f'{low}.non_owner_events_opened']} of 24 colleague" in page
    assert f"{values[f'{low}.non_owner_forwarded_s']} s" in page
    assert f"{values[f'{default}.non_owner_forwarded_s']} s" in page
    assert f"{values[f'{default}.gate_confirm_ms_p50']} ms instead of {values[f'{low}.gate_confirm_ms_p50']} ms" in page
    assert f"{values[f'{default}.owner_gate_miss_pct']} %" in page


def test_the_operations_cost_paragraph_comes_from_the_settled_json(values):
    page = flowed(OPERATIONS)
    assert f"{values[f'settled.{BASELINE}.scoring_hop_ms_p50']} ms p50" in page
    assert f"{values[f'settled.{BASELINE}.scoring_hop_ms_p95']} ms p95" in page
    assert f"a hop without scoring {values[f'settled.{BASELINE}.hop_ms_p50']} ms p50" in page
    assert f"{values[f'settled.{BASELINE}.cpu_pct_one_core']} % of one core" in page
    assert (
        f"model load {values[f'settled.{BASELINE}.model_verify_ms']}"
        f" + {values[f'settled.{BASELINE}.model_load_ms']} ms once" in page
    )
    assert f"+{values[f'settled.{BASELINE}.rss_steady_delta_mb']} MB" in page
    # La valeur « sous contention » est celle de la campagne 2026-09-11, pas une estimation.
    assert f"up to {values[f'settled-2026-09-11.{BASELINE}.model_load_ms']} ms of load under contention" in page
