"""`barehands.input_quality` : rejouer la trace d'or et mesurer ce qui en sort.

Slice 10, architecture §12.

**Ce que ce diagnostic mesure, et ce qu'il ne mesure pas.** Il mesure la
**chaîne de traitement** de Bare Hands — filtre du pointeur, hystérésis de
pincement, résolveur de cible — sur une séance enregistrée une fois pour
toutes. Il ne mesure ni caméra, ni MediaPipe, ni la main de personne : la trace
d'or est **synthétique**, produite par le vrai enregistreur à partir d'une
séance écrite à la main, et une trace d'or versionnée dans un dépôt ne doit être
la séance de personne.

C'est ce qui le rend `virtual` au sens du Test Lab : aucune capacité requise,
aucun coût, aucun réseau, aucun périphérique. Et c'est ce qui le rend utile
comme garde-fou : un changement de filtre ou de seuil qui dégrade le pointeur
tombe ici, sans qu'un humain refasse le geste.

**Node absent n'est pas une mesure à zéro.** Le rejeu se fait avec les *vrais*
moteurs, qui vivent en JavaScript ; sans node, le runner lève
`MeasurementUnavailable` plutôt que de rendre des métriques vides, parce qu'une
mesure qu'on n'a pas pu prendre et une mesure prise à zéro ne sont pas la même
chose.
"""

from __future__ import annotations

import json
from pathlib import Path

from jarvis.runtime import barehands_replay
from jarvis.testlab.diagnostics import MetricValue
from jarvis.testlab.runners import MeasurementUnavailable, RunContext, RunOutcome
from jarvis.testlab.runs import ArtifactKind

#: La trace d'or, livrée avec le dépôt. Lue depuis le paquet et non depuis
#: `RunContext.data_root`, qui est un bac à sable propre par exécution : la
#: trace est une **entrée** du diagnostic, pas un artefact qu'il produit.
GOLDEN_TRACE = Path(__file__).resolve().parents[1] / "fixtures" / "barehands" / "golden.v1.json"


class InputQualityRunner:
    """Rejoue la trace d'or sous la configuration décrite par les paramètres."""

    async def run(self, context: RunContext) -> RunOutcome:
        if not GOLDEN_TRACE.is_file():
            raise MeasurementUnavailable(
                f"trace d'or absente ({GOLDEN_TRACE}) : sans elle il n'y a rien à rejouer, "
                "et rendre des métriques vides ferait passer une absence de mesure pour une mesure"
            )
        config = {
            "filter": {
                "minCutoffHz": float(context.parameters["filter.min_cutoff_hz"]),
                "betaCutoff": float(context.parameters["filter.beta_cutoff"]),
            },
            "thresholds": {
                "pressRatio": float(context.parameters["pinch.press_ratio"]),
                "releaseRatio": float(context.parameters["pinch.release_ratio"]),
            },
            "assistance": float(context.parameters["target.assistance"]),
        }
        context.log(f"barehands replay config: {json.dumps(config, sort_keys=True)}")
        try:
            rows = barehands_replay.replay(
                GOLDEN_TRACE, [{"name": "run", "config": config}])
        except barehands_replay.ReplayUnavailable as exc:
            raise MeasurementUnavailable(str(exc)) from exc
        except barehands_replay.ReplayFailed as exc:
            # Un rejeu qui refuse est un **échec de mesure**, pas une mesure
            # mauvaise : le distinguer est tout l'objet de ces deux exceptions.
            raise MeasurementUnavailable(f"le rejeu a refusé : {exc}") from exc
        measured = rows[0]["metrics"]
        # Une mesure absente reste absente : `None` n'est pas rapporté, il n'est
        # pas converti en zéro. Le Test Lab lit ce qui est là, et l'assertion
        # bloquante sur `replay.frames_count` dit si « là » veut dire quelque
        # chose.
        metrics: dict[str, MetricValue] = {
            key: value for key, value in measured.items() if value is not None
        }
        context.log(f"barehands metrics: {json.dumps(measured, sort_keys=True)}")
        # La trace rejouée et ses mesures, attachées à l'exécution : sans elles,
        # « cette configuration est moins bonne » n'est qu'un nombre sans
        # l'objet qu'il décrit.
        artifact = context.put_artifact(
            "barehands-replay.json", kind=ArtifactKind.REPORT, media_type="application/json",
            data=json.dumps({"config": config, "metrics": measured,
                             "trace": GOLDEN_TRACE.name}, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        return RunOutcome(metrics=metrics, artifacts=(artifact,))
