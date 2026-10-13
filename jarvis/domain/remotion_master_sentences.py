"""The user's words for a master-project plan, and the compact view the agent reads (`docs/remotion-master-project.md` § 3 and § 12;
handoff jarvis-remotion-master-project-studio-export, Slice 07). Pure.

- `REASON_SENTENCES`: the « Sentence shown to the user » column of § 3, one per `MasterReason`, word for word (the docs test compares them),
  with typographic apostrophes (’) like every user-facing string of the Variants page.
  Two carry a placeholder the plan's `detail` fills: the scene position (« scène n ») and the colliding path (« x »).
- `agent_view(wire)`: the compact `master` block of `presentation_inspect` (target variant), `presentation_source` write/preview and
  `presentation_draft_assemble`: status, reason + sentence, `project_key`, scene count, duration. It PROJECTS the plan view of § 2 that
  `MasterProjectReader.live_plan` computed; it never decides readiness itself.
"""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from jarvis.domain.remotion_master_project import MasterReason

REASON_SENTENCES: dict[MasterReason, str] = {
    MasterReason.EMPTY: "La variante n’a aucune scène : pas de vidéo entière à construire.",
    MasterReason.ENGINE_NOT_REMOTION: "Une scène n’est pas une scène Remotion : la vidéo entière n’est pas disponible.",
    MasterReason.SOURCE_UNAVAILABLE: "La source d’une scène est introuvable ou altérée (scène n) : la vidéo entière n’est pas disponible.",
    MasterReason.ENGINE_MISMATCH: "Les scènes n’ont pas toutes été écrites pour la même version de Remotion.",
    MasterReason.FPS_MISMATCH: ("Les scènes n’ont pas toutes la même cadence (images par seconde) : la vidéo entière n’est pas disponible ; "
                                "chaque scène reste lisible."),
    MasterReason.DIMENSIONS_MISMATCH: ("Les scènes n’ont pas toutes la même taille d’image : la vidéo entière n’est pas disponible ; "
                                       "chaque scène reste lisible."),
    MasterReason.SOURCE_IMPORT_REFUSED: "Une scène importe un module qui n’est pas le sien : la vidéo entière n’est pas disponible.",
    MasterReason.INPUT_PROPS_READER: "Une scène lit les paramètres d’entrée de la vidéo : elle ne peut pas être assemblée.",
    MasterReason.PUBLIC_ASSET_COLLISION: "Deux scènes utilisent le même nom de fichier « x » pour des contenus différents.",
    MasterReason.PROJECT_TOO_LARGE: "Le projet de la vidéo entière dépasse 400 fichiers ou 64 Mio.",
    MasterReason.TOO_LONG: "La vidéo entière dépasse 9 000 images (5 min à 30 i/s).",
}
#: An unknown reason (a newer Core than this agent layer): said as such, never re-labelled as another reason.
UNKNOWN_REASON_SENTENCE = "La vidéo entière n’est pas disponible pour cette variante."

_SCENE_POSITION = re.compile(r"\bscene (\d{1,3})\b")
_LEADING_PATH = re.compile(r"\A(public/[^\s:(]{1,160})")


def reason_sentence(reason: object, detail: object = "") -> str:
    """The § 3 sentence of `reason`, its placeholder filled from `detail` when the detail names it (else the generic wording stays)."""

    try:
        known = MasterReason(str(reason))
    except ValueError:
        return UNKNOWN_REASON_SENTENCE
    sentence = REASON_SENTENCES[known]
    text = detail if isinstance(detail, str) else ""
    if known is MasterReason.SOURCE_UNAVAILABLE:
        found = _SCENE_POSITION.search(text)
        sentence = sentence.replace("(scène n)", f"(scène {found.group(1)})" if found else "").replace("  :", " :")
    elif known is MasterReason.PUBLIC_ASSET_COLLISION:
        found = _LEADING_PATH.search(text)
        sentence = sentence.replace("« x »", f"« {found.group(1)} »" if found else "")
        sentence = sentence.replace("fichier  pour", "fichier pour")
    return sentence


def agent_view(wire: Mapping[str, Any]) -> dict[str, Any]:
    """The compact `master` block from the plan view of § 2 (ready: key, scene count, duration, spec; incompatible: reason, sentence,
    bounded English detail, involved scene ids). Nothing here re-checks the plan."""

    status = wire.get("status")
    view: dict[str, Any] = {"status": status, "variant_revision": wire.get("variant_revision")}
    if status == "ready":
        composition = wire.get("composition") if isinstance(wire.get("composition"), Mapping) else {}
        fps = composition.get("fps")
        frames = composition.get("duration_in_frames")
        view.update(project_key=wire.get("project_key"), scenes=len(wire.get("scenes") or []),
                    duration_s=round(frames / fps, 1) if isinstance(frames, int) and isinstance(fps, int) and fps > 0 else None,
                    spec=f"{composition.get('width')}x{composition.get('height')}@{fps}" if composition else None)
        return {k: v for k, v in view.items() if v is not None}
    view.update(reason=wire.get("reason"), say=reason_sentence(wire.get("reason"), wire.get("detail")),
                detail=wire.get("detail") or None, scene_ids=list(wire.get("scene_ids") or [])[:12] or None)
    return {k: v for k, v in view.items() if v is not None}


__all__ = ["REASON_SENTENCES", "UNKNOWN_REASON_SENTENCE", "agent_view", "reason_sentence"]
