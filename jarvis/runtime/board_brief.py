"""Rendu, dans la consigne de l'agent, du Board de son tour (handoff board-session, Slice 08).

Core joint à chaque tour le bloc `board` (`context.board` de
`POST /api/agent/ask`, `BrainBoardContext.to_payload()`, borné à 2 048
caractères sérialisés par Core). Le Control Center possède la formulation de
ce qu'on dit à l'agent (Décision 23) : il le rend ici en quelques lignes. C'est
ce qui **hydrate** un CLI neuf (nouvelle Session, reprise impossible) depuis
l'état durable du Board, sans rejouer d'ancienne conversation.

Lecture en liste blanche ; `board_id` reste dans la charge utile. Les valeurs
sont déjà bornées par le contrat du Board (titre ≤ 120, résumé ≤ 1 500,
références ≤ 256) ; ce rendu ne fait pas confiance à une borne distante et
retronque quand même.
"""

from __future__ import annotations

from typing import Any

_MAX_TITLE = 120
_MAX_SUMMARY = 1500
_MAX_REF = 256
_MAX_REFS = 64

#: Ce que le Board est pour le cerveau, en une ligne.
BRIEF_BOARD_SCOPE = (
    "C'est ton espace de travail pour ce tour : ne mélange pas son contexte avec celui d'un autre Board."
)

_REF_LABELS = (("task_refs", "Tâches du Board"), ("artifact_refs", "Artefacts du Board"),
               ("project_refs", "Projets du Board"))


def _text(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_board_brief(board: Any) -> list[str]:
    """Lignes du Board actif du tour ; rien quand le bloc manque ou n'a pas de titre."""

    if not isinstance(board, dict):
        return []
    title = _text(board.get("title"), _MAX_TITLE)
    if not title:
        return []
    lines = [f"Board : « {title} ». {BRIEF_BOARD_SCOPE}"]
    summary = str(board.get("context_summary") or "").strip()
    if summary:
        clipped = summary if len(summary) <= _MAX_SUMMARY else summary[: _MAX_SUMMARY - 1] + "…"
        lines.append(f"Résumé du Board : {clipped}")
    for key, label in _REF_LABELS:
        refs = board.get(key)
        if isinstance(refs, list):
            kept = [_text(ref, _MAX_REF) for ref in refs[:_MAX_REFS] if str(ref or "").strip()]
            if kept:
                lines.append(f"{label} : {', '.join(kept)}")
    omitted = board.get("omitted_refs")
    if isinstance(omitted, int) and not isinstance(omitted, bool) and omitted > 0:
        lines.append(f"({omitted} référence(s) du Board non jointe(s) : demande board_get si tu en as besoin.)")
    return lines
