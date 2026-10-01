"""Rendu, dans la consigne de l'agent, du Context actif de sa Session (handoff session-context-recording, Slice 03).

Core joint à chaque tour le bloc `session_context` (`context.session_context`
de `POST /api/agent/ask`, `BrainSessionContext.to_payload()`, borné par Core :
`summary.md` ≤ 2 048 octets, au plus 8 dormants par id et titre). Le Control
Center possède la formulation (Décision 23) : il le rend ici en quelques
lignes sous l'en-tête « Contexte actif ».

C'est la seule hydratation du cerveau depuis un Context : son dossier absolu,
les règles d'écriture, le `summary.md` borné. Jarvis n'injecte jamais le
contenu d'un Context dormant : il n'apparaît que par son id et son titre
(D03). Le fil du CLI, lui, est celui de la Session (D-THREAD) et peut se
souvenir de tours antérieurs. Lecture
en liste blanche ; ce rendu ne fait pas confiance à une borne distante et
retronque quand même.

`sessions_root(block)` rend le dossier que le Control Center accorde au CLI
(`--add-dir`, `jarvis/runtime/control_center.py`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: Mêmes bornes que Core (`jarvis/domain/brain_context.py`), reprises ici sans
#: l'importer : le Control Center ne fait pas confiance au contenu reçu.
_MAX_SUMMARY_BYTES = 2_048
_MAX_DORMANT = 8
_MAX_TITLE = 120
_MAX_ID = 128
_MAX_PATH = 1_024

#: La règle, mot pour mot : le dossier actif est le seul espace implicite.
BRIEF_CONTEXT_RULE = (
    "C'est ton seul espace de travail implicite ; ne modifie pas les Contexts dormants sauf demande explicite."
)
#: Écritures dans le Context, en une ligne (décision PM, reprise QA Slice 03) :
#: un tour vocal ne tient pas de comptabilité. `summary.md` est lisible ; sa
#: tenue reviendra au worker d'enrichissement (Slice 08).
BRIEF_WRITE_RULE = (
    "Tu peux lire `summary.md` ; n'écris dans ce dossier que si l'utilisateur le demande "
    "ou pour y ranger un travail substantiel."
)


def _text(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _path(value: object) -> str:
    text = str(value or "").strip()
    return text if 0 < len(text) <= _MAX_PATH and "\n" not in text and "\r" not in text else ""


def _clip_bytes(text: str, limit: int) -> str:
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    return data[: limit - 3].decode("utf-8", errors="ignore") + "…"


def render_session_context_brief(block: Any) -> list[str]:
    """Lignes du Context actif du tour ; rien quand le bloc manque ou est hors contrat."""

    if not isinstance(block, dict):
        return []
    context_id = _text(block.get("context_id"), _MAX_ID)
    session_id = _text(block.get("jarvis_session_id"), _MAX_ID)
    workspace = _path(block.get("workspace_path"))
    if not context_id or not session_id or not workspace:
        return []
    title = _text(block.get("title"), _MAX_TITLE)
    named = f" « {title} »" if title else ""
    lines = ["[Contexte actif]", f"Session : {session_id} — Context : {context_id}{named}."]
    error = _text(block.get("workspace_error"), 64)
    if error:
        lines.append(f"Dossier de travail : {workspace} — INDISPONIBLE ({error}) : n'y écris rien pour ce tour, "
                     "dis-le si la demande en a besoin.")
    else:
        lines.append(f"Dossier de travail : {workspace}")
        lines.append(BRIEF_CONTEXT_RULE)
        lines.append(BRIEF_WRITE_RULE)
    summary = str(block.get("summary") or "").strip()
    if summary:
        lines.append("Résumé du Context (summary.md" + (", coupé" if block.get("summary_clipped") else "") + ") :")
        lines.append(_clip_bytes(summary, _MAX_SUMMARY_BYTES))
    dormant = block.get("dormant")
    if isinstance(dormant, list) and dormant:
        named_dormant = []
        for item in dormant[:_MAX_DORMANT]:
            if isinstance(item, dict) and item.get("context_id"):
                item_title = _text(item.get("title"), _MAX_TITLE)
                named_dormant.append(_text(item.get("context_id"), _MAX_ID) + (f" « {item_title} »" if item_title else ""))
        omitted = block.get("omitted_dormant")
        more = f" (+{omitted} autres)" if isinstance(omitted, int) and not isinstance(omitted, bool) and omitted > 0 else ""
        if named_dormant:
            lines.append(f"Contexts dormants (lecture seule, sur demande) : {', '.join(named_dormant)}{more}")
    return lines


def sessions_root(block: Any) -> Path | None:
    """Le dossier `<data_root>/sessions` du bloc, s'il est absolu ; sinon `None`."""

    if not isinstance(block, dict):
        return None
    text = _path(block.get("sessions_root"))
    if not text:
        return None
    path = Path(text)
    return path if path.is_absolute() else None
