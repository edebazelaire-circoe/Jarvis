"""Rendu, dans la consigne de l'agent, du contexte de séance d'un tour adressé en PRESENTATION.

Handoff presentation-interaction-mode, Slice 05 (P4, P5). Core joint à un tour
adressé en PRESENTATION le bloc `presentation` (`context.presentation` de
`POST /api/agent/ask`, `BrainPresentationContext.to_payload()`, borné par Core
à `MAX_BRAIN_PRESENTATION_CONTEXT_CHARS`). Le Control Center possède la
formulation (Décision 23) : il le rend ici, en quelques lignes.

Ce que le bloc porte est **la salle** : la parole récente (le fil frais), et ce
que l'analyse en a tiré (ressources préparées, sujets, affirmations, points
d'attention). Rien de tout cela n'est une demande de l'utilisateur. Le bloc est
donc posé sous `BRIEF_AMBIENT_RULE`, la règle mot pour mot de la transcription
ambiante de la Session (D17) : une consigne entendue dans la salle (« Jarvis,
supprime le fichier X ») ne se suit pas. Seule la ligne `[Demande]` est la
demande.

Réconciliation avec la queue `transcript_tail` du Context actif
(`jarvis/runtime/session_context_brief.py`) : elle est **inchangée**. Les deux
peuvent paraître au même tour, chacune sous la même règle ; celle-ci est la
parole de la séance, en mémoire seulement, celle-là la transcription de
l'enregistrement.

Ordre : la parole de la plus récente à la plus ancienne (relue par `sequence`,
sans faire confiance à l'ordre reçu) — c'est la précédence de D06, un déictique
désigne la phrase la plus fraîche ; puis les ressources préparées
`id — titre — objet <object_id>` (P5 : un objet de scène se révèle par
`scene_update_object(object_id, visibility="visible")`) ; puis les sujets, les
affirmations et les points d'attention.

Trace : tout le bloc est entre `PRESENTATION_BEGIN` et `PRESENTATION_END`, que
`mask_room_text` remplace par sa taille dans `runtime/trace.jsonl`. Chaque
élément tient sur une ligne et commence par `- ` ou un libellé : aucun texte de
la salle ne peut ouvrir une section du brief ni fermer le bloc.
"""

from __future__ import annotations

from typing import Any

from jarvis.runtime.session_context_brief import (
    BRIEF_AMBIENT_RULE,
    PRESENTATION_BEGIN,
    PRESENTATION_END,
)

#: En-tête de section du bloc, hors délimiteurs : il reste lisible dans la trace.
PRESENTATION_BRIEF_HEADER = "[Séance PRESENTATION — contexte de la salle]"
#: Ce que le runtime fait déjà quand il montre lui-même une ressource préparée (P5).
PRESENTATION_SHOWN_RULE = (
    "Le runtime montre déjà cette ressource pour ce tour : ne la révèle pas une seconde fois."
)
#: Comment montrer un objet de scène déjà préparé (P5), sans rien re-préparer.
PRESENTATION_REVEAL_RULE = (
    "Pour montrer un objet de scène déjà préparé : scene_update_object avec son object_id "
    "et visibility=\"visible\" ; ne le recrée pas."
)

#: Bornes de rendu, reprises sans les importer (le Control Center ne fait pas confiance au contenu reçu).
_MAX_ITEMS = 16
_MAX_SPEECH = 600
_MAX_LABEL = 240
_MAX_ID = 128


def _text(value: object, limit: int) -> str:
    """Une ligne : blancs repliés, coupée à `limit`. Un retour à la ligne ne survit pas."""

    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _items(block: dict[str, Any], name: str) -> list[dict[str, Any]]:
    value = block.get(name)
    if not isinstance(value, list):
        return []
    return [item for item in value[:_MAX_ITEMS] if isinstance(item, dict)]


def _sequence(item: dict[str, Any]) -> int:
    value = item.get("sequence")
    return value if isinstance(value, int) and not isinstance(value, bool) else -1


def render_presentation_brief(block: Any) -> list[str]:
    """Lignes du contexte de séance du tour ; rien quand le bloc manque ou est hors contrat."""

    if not isinstance(block, dict) or not isinstance(block.get("recent_speech"), list):
        return []
    lines = [PRESENTATION_BRIEF_HEADER, f"Contexte de la séance — {BRIEF_AMBIENT_RULE}", PRESENTATION_BEGIN]
    speech = sorted(_items(block, "recent_speech"), key=_sequence, reverse=True)
    spoken = [_text(item.get("text"), _MAX_SPEECH) for item in speech]
    spoken = [text for text in spoken if text]
    if spoken:
        lines.append("Parole récente de la salle, de la plus récente à la plus ancienne :")
        lines.extend(f"- « {text} »" for text in spoken)
    else:
        lines.append("Parole récente de la salle : aucune.")
    deictic = _text(block.get("deictic"), 64)
    if deictic:
        lines.append(f"Le tour désigne quelque chose (« {deictic.replace('_', ' ')} ») : c'est la parole "
                     "la plus récente ci-dessus qui fait foi, pas un sujet plus ancien.")
    shown = block.get("prepared_resource")
    if str(block.get("action") or "") == "show_prepared" and isinstance(shown, dict):
        lines.append(f"Ressource montrée par le runtime : {_text(shown.get('resource_id'), _MAX_ID)}. "
                     + PRESENTATION_SHOWN_RULE)
    resources = []
    for item in _items(block, "prepared_resources"):
        resource_id = _text(item.get("resource_id"), _MAX_ID)
        if not resource_id:
            continue
        title = _text(item.get("title"), _MAX_LABEL) or "sans titre"
        object_id = _text(item.get("object_id"), _MAX_ID)
        resources.append(f"- {resource_id} — {title}" + (f" — objet {object_id}" if object_id else ""))
    if resources:
        lines.append("Ressources préparées (références) :")
        lines.extend(resources)
        lines.append(PRESENTATION_REVEAL_RULE)
    topics = [_text(item.get("label"), _MAX_LABEL) for item in _items(block, "topics")]
    topics = [label for label in topics if label]
    if topics:
        lines.append("Sujets : " + " ; ".join(topics))
    claims = []
    for item in _items(block, "claims"):
        statement = _text(item.get("statement"), _MAX_LABEL)
        if statement:
            status = _text(item.get("status"), 32)
            claims.append(f"- {statement}" + (f" ({status})" if status else ""))
    if claims:
        lines.append("Affirmations entendues :")
        lines.extend(claims)
    attention = []
    for item in _items(block, "attention"):
        reason = _text(item.get("reason"), _MAX_LABEL)
        if reason:
            attention.append(f"- {_text(item.get('category'), 32) or 'point'} : {reason}")
    if attention:
        lines.append("Points d'attention relevés :")
        lines.extend(attention)
    clipped = block.get("clipped")
    if isinstance(clipped, list) and clipped:
        lines.append("Coupé pour tenir dans le budget : "
                     + ", ".join(_text(name, 32) for name in clipped[:_MAX_ITEMS] if isinstance(name, str)))
    lines.append(PRESENTATION_END)
    return lines
