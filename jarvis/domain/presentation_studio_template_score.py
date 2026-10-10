"""Squelette de partition d'un modele de presentation (handoff jarvis-remotion-presentation-integration, Slice 19).

Pur. Contrat : `docs/presentation-studio.md` > *Template and prefab promotion contract* > *Score skeleton*. Avant la Slice 19 un modele
ne portait pas la partition (limite connue de `presentation-studio-release.md`) : une presentation instanciee demandait une partition
ecrite a la main. Une partition d'un projet est pourtant presque entierement du **contenu** : la parole (`text`, `note`, `label`), les
reperes parles (`cues`, leurs phrases), les sequences verrouillees (leurs etapes parlees) et les valeurs de controle (`control_set`).
Le squelette garde donc ce qui est de la **structure** et jamais le reste :

| Gardé | Retiré (compté dans le rapport) |
| --- | --- |
| ordre, présentateur, genre, durée visée, politique de temps, interruption, boucles déclarées, `scene_goto` de l'item | `label`, `text`, `note` (remplacés par l'espace réservé `[intention]`, toujours dans `note`, jamais dans `text` qui serait dit mot pour mot), `cue_id` et tous les repères |
| scène de l'item (par emplacement du modèle, jamais l'id d'une scène du projet) | séquences (l'item hôte redevient un item ordinaire, durée gardée), points de reprise, actions `control_set` / `reveal` / `hide` / `sequence` |

Le résultat se relit par `parse_content` (le validateur de la partition) : un squelette qui ne tiendrait pas debout n'est jamais écrit.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any

from jarvis.domain.presentation_studio_score import (
    ActionKind, Presenter, Recovery, TimingPolicy, new_score_item_id, parse_content,
)

NOTE_PLACEHOLDER = "[intention]"


def skeleton_item_id(template_id: str, index: int) -> str:
    """Un `psi_` stable de l'enregistrement (jamais l'id d'un item du projet) ; l'instanciation en donne des neufs."""

    return "psi_" + hashlib.sha256(f"{template_id}:item:{index}".encode()).hexdigest()[:12]


def score_skeleton(score: Mapping[str, Any], *, slot_of: Mapping[str, str], template_id: str) -> tuple[dict[str, Any], dict[str, int]]:
    """`(squelette, comptes retires)` d'un document de partition (`Score.to_document()`). `slot_of` : id de scene du projet -> emplacement
    du modele. Une scene de la partition sans emplacement est une erreur de l'appelant (`KeyError`)."""

    items = list(score["items"])
    ids = {item["item_id"]: skeleton_item_id(template_id, n) for n, item in enumerate(items)}
    dropped = {"cues": len(score.get("cues", [])), "sequences": len(score.get("sequences", [])),
               "recovery_points": len(score.get("recovery_points", [])), "actions": 0, "speech": 0}
    rows: list[dict[str, Any]] = []
    for item in items:
        slot = slot_of[item["scene_id"]]
        silent = item["presenter"] == Presenter.NONE.value
        kept_visual = [{"kind": ActionKind.SCENE_GOTO.value, "scene_id": slot}
                       for a in item["visual"] if a["kind"] == ActionKind.SCENE_GOTO.value]
        dropped["actions"] += len(item["visual"]) + len(item["motion"]) - len(kept_visual)
        if not silent:
            dropped["speech"] += 1
        # A locked-sequence host loses its sequence: an ordinary item again (timing soft), the target duration is kept.
        row = {
            "item_id": ids[item["item_id"]], "scene_id": slot, "presenter": item["presenter"], "kind": item["kind"],
            "label": "", "text": "", "note": "", "cue_id": None, "visual": kept_visual, "motion": [],
            "target_duration_ms": item["target_duration_ms"], "timing": TimingPolicy.SOFT.value,
            "interruption": item["interruption"], "recovery": item["recovery"], "recovery_point_id": item["recovery_point_id"],
            "next_item_id": ids.get(item["next_item_id"]) if item["next_item_id"] else None,
            "loop": None if item["loop"] is None else {"to_item_id": ids[item["loop"]["to_item_id"]],
                                                       "max_repeats": item["loop"]["max_repeats"]}}
        if row["recovery"] == Recovery.RECOVERY_POINT.value:
            row["recovery"], row["recovery_point_id"] = Recovery.CONTINUE_ITEM.value, None
        if not silent:
            row["note"] = NOTE_PLACEHOLDER  # never `text`: a placeholder in `text` would be spoken aloud word for word
        rows.append(row)
    start = score.get("start_item_id")
    skeleton = {"start_item_id": ids[start] if start else None, "items": rows, "cues": [], "sequences": [], "recovery_points": []}
    parse_content(skeleton)  # raises PresentationStudioError: a skeleton that does not stand is never stored
    return skeleton, dropped


def instantiate_score(skeleton: Mapping[str, Any], scene_ids: Mapping[str, str]) -> dict[str, Any]:
    """Le contenu de partition d'une presentation neuve : emplacements -> ids de scene neufs, ids d'item neufs."""

    fresh = {item["item_id"]: new_score_item_id() for item in skeleton["items"]}

    def swap(value: Any) -> Any:
        if isinstance(value, str):
            return fresh.get(value) or scene_ids.get(value) or value
        if isinstance(value, list):
            return [swap(v) for v in value]
        if isinstance(value, dict):
            return {k: swap(v) for k, v in value.items()}
        return value

    content = swap(dict(skeleton))
    parse_content(content)
    return content
