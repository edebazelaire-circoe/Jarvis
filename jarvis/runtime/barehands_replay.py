"""Rejeu déterministe d'une trace Bare Hands, et les mesures qui en sortent.

Slice 10, architecture §12.

**Ce module ne mesure rien lui-même, et c'est le point.** Le filtre du
pointeur, l'hystérésis de pincement et le résolveur de cible vivent dans
`control_center_barehands.js` et `control_center_barehands_recorder.js` ; les
rejouer ici en Python serait une **seconde implantation**, et le jour où les
deux divergeraient c'est le banc d'essai qui aurait raison contre le produit —
la panne la plus coûteuse possible pour un outil de réglage. Python **pilote
node** sur les vrais modules, exactement comme le fait le harnais de tests de
cette tâche (`tests/unit/test_barehands_*_js.py`).

**Déterminisme.** Le rejeu n'a ni horloge, ni hasard, ni réseau, ni DOM : il lit
les horodatages de la trace. Deux exécutions de la même trace sous la même
configuration rendent des nombres identiques, ce qu'un test affirme en les
comparant octet pour octet.

**Node absent** n'est pas un résultat nul : `ReplayUnavailable` le dit. Une
mesure qu'on n'a pas pu prendre et une mesure prise à zéro ne sont pas la même
chose — c'est la leçon `Number(null) === 0` de cette tâche.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from jarvis.runtime import barehands_trace

RUNTIME = Path(__file__).resolve().parent
CONTRACTS = RUNTIME / "control_center_barehands_contracts.js"
RECORDER = RUNTIME / "control_center_barehands_recorder.js"
CORE = RUNTIME / "control_center_barehands.js"

#: Les axes qu'une configuration de rejeu peut faire varier. Fermé, et publié :
#: un banc d'essai qui accepterait n'importe quelle clé laisserait une
#: configuration silencieusement sans effet, et deux colonnes identiques se
#: liraient « ce réglage ne change rien ».
REPLAY_AXES = ("filter", "thresholds", "assistance", "resolver")

#: Les mesures, dans l'ordre où elles se lisent. Miroir de `METRIC_KEYS` du
#: module JS ; un test de parité les compare.
METRIC_KEYS = (
    "replay.frames_count",
    "click.target_success_ratio",
    "pointer.error_p50_norm",
    "pointer.error_p95_norm",
    "pointer.stationary_jitter_p95_norm",
    "pinch.false_primary_hz",
    "pinch.false_secondary_hz",
    "gesture.false_positive_hz",
    "interaction.latency_p50_ms",
    "hand.loss_recovery_p95_ms",
    "drag.continuity_ratio",
    "resize.two_hand_stability_ratio",
)

#: Le temps qu'on laisse à node. Une borne, parce qu'un rejeu qui ne rend jamais
#: la main est la panne que la RÈGLE ZÉRO interdit, y compris hors écran.
TIMEOUT_S = 120


class ReplayUnavailable(RuntimeError):
    """Le rejeu n'a pas pu être exécuté — ce n'est pas une mesure à zéro."""


class ReplayFailed(RuntimeError):
    """Le rejeu a été exécuté et a refusé, en portant sa cause."""


_DRIVER = """
const C=require({contracts});
global.JarvisBarehandsContracts=C;
const R=require({recorder});
const Core=require({core});
const trace=JSON.parse(require('fs').readFileSync({trace},'utf8'));
const configs=JSON.parse(require('fs').readFileSync({configs},'utf8'));
const rows=configs.map(entry=>{{
  const replayed=R.replay(trace,entry.config,{{core:Core}});
  return {{name:entry.name,config:replayed.config,
    metrics:R.metricsOf(replayed,entry.spec||null)}};
}});
process.stdout.write(JSON.stringify({{schemaVersion:R.TRACE_SCHEMA_VERSION,rows}}));
"""


def _check_config(config: Mapping[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(config) - set(REPLAY_AXES))
    if unknown:
        raise ReplayFailed(
            f"axe de rejeu inconnu : {', '.join(unknown)}. Les axes sont {', '.join(REPLAY_AXES)} — "
            "accepter une clé sans effet ferait lire deux colonnes identiques comme « ce réglage "
            "ne change rien »."
        )
    return dict(config)


def replay(trace: Mapping[str, Any] | Path,
           configs: Sequence[Mapping[str, Any]],
           *, node: str | None = None) -> list[dict[str, Any]]:
    """Rejouer une trace sous plusieurs configurations et rendre leurs mesures.

    `configs` est une suite de ``{"name": str, "config": {...}}``. La trace est
    relue par `barehands_trace.normalize` **avant** d'atteindre node : un
    fichier n'est pas plus digne de confiance qu'une requête, et une version
    inconnue se refuse ici plutôt que de produire des nombres au jugé.
    """

    document = (barehands_trace.load(trace) if isinstance(trace, (str, Path))
                else barehands_trace.normalize(trace))
    if len(configs) < 1:
        raise ReplayFailed("rejouer sans configuration ne mesure rien")
    prepared = [{"name": str(entry.get("name") or f"config{index}"),
                 "config": _check_config(entry.get("config") or {}),
                 "spec": entry.get("spec") or None}
                for index, entry in enumerate(configs)]
    # `node` donné est **résolu** comme n'importe quel autre : un nom qui
    # n'existe pas doit dire « node est absent », pas exploser en
    # `FileNotFoundError` trois couches plus bas.
    binary = shutil.which(node) if node else shutil.which("node")
    if binary is None:
        raise ReplayUnavailable(
            "node est absent : le rejeu se fait avec les **vrais** moteurs du produit "
            "(filtre, hystérésis, résolveur), qui vivent en JavaScript. Une réimplantation "
            "Python mesurerait une copie, et une copie qui diverge donne raison au banc "
            "d'essai contre le produit."
        )
    with tempfile.TemporaryDirectory(prefix="barehands-replay-") as tmp:
        folder = Path(tmp)
        trace_path = folder / "trace.json"
        trace_path.write_text(json.dumps(document), encoding="utf-8")
        configs_path = folder / "configs.json"
        configs_path.write_text(json.dumps(prepared), encoding="utf-8")
        script = folder / "replay.cjs"
        script.write_text(_DRIVER.format(
            contracts=json.dumps(str(CONTRACTS)), recorder=json.dumps(str(RECORDER)),
            core=json.dumps(str(CORE)), trace=json.dumps(str(trace_path)),
            configs=json.dumps(str(configs_path))), encoding="utf-8")
        done = subprocess.run([binary, str(script)], capture_output=True, text=True,
                              encoding="utf-8", timeout=TIMEOUT_S, check=False)
    if done.returncode != 0:
        raise ReplayFailed(
            f"le rejeu a refusé (code {done.returncode}) : {(done.stderr or '').strip()[:2000]}")
    try:
        answer = json.loads(done.stdout)
    except ValueError as exc:
        raise ReplayFailed(f"le rejeu n'a pas rendu de mesures lisibles : {exc}") from exc
    rows = answer.get("rows")
    if not isinstance(rows, list) or len(rows) != len(prepared):
        raise ReplayFailed("le rejeu n'a pas rendu une ligne par configuration")
    for row in rows:
        missing = sorted(set(METRIC_KEYS) - set(row.get("metrics") or {}))
        if missing:
            raise ReplayFailed(
                f"mesures manquantes dans « {row.get('name')} » : {', '.join(missing)}. "
                "Une mesure absente doit être `null`, jamais omise : omise, elle se lirait "
                "comme une mesure qu'on n'a pas pensé à prendre."
            )
    return rows


def compare(trace: Mapping[str, Any] | Path,
            configs: Sequence[Mapping[str, Any]],
            *, node: str | None = None) -> dict[str, Any]:
    """Le critère d'acceptation de la Slice, en une fonction.

    « Un développeur peut rejouer la même séance enregistrée sous au moins deux
    configurations et comparer des mesures objectives. » Moins de deux
    configurations est donc refusé : comparer une configuration à elle-même ne
    dit rien, et c'est exactement ce que cette Slice existe pour remplacer.
    """

    if len(configs) < 2:
        raise ReplayFailed(
            "comparer exige au moins deux configurations : une configuration comparée à "
            "elle-même ne dit rien, et c'est le réglage à l'estime que cette Slice remplace."
        )
    rows = replay(trace, configs, node=node)
    #: Les mesures qui **diffèrent** d'une configuration à l'autre, nommées.
    #: Sans elles, deux colonnes identiques et un axe sans effet se lisent
    #: pareil, et on conclurait « ce réglage ne change rien » d'un réglage qui
    #: n'a pas été appliqué.
    changed = sorted(
        key for key in METRIC_KEYS
        if len({json.dumps(row["metrics"][key]) for row in rows}) > 1
    )
    return {"rows": rows, "changed": changed,
            "identical": not changed,
            "metrics": list(METRIC_KEYS)}
