"""Lecture des intentions d'interface de Jarvis par le Tool Brain (Slice 4) : refs, ancrage, péremption.

Contrat : `docs/tool-brain-contracts.md` §11. Deux fonctions pures, aucun état, aucune écriture :

- `check_intent_refs(draft, state)` : chaque id visé est-il un choix **légal maintenant** (fournisseurs S2,
  mêmes codes de refus que le validateur) ? Core ne lit pas l'état à la publication (une intention est un
  indice, pas un droit) : c'est le Tool Brain qui juge, au moment de décider, une intention devenue périmée ;
- `intent_status(draft, correlation_id, speech)` : où en est la parole que l'intention accompagne, d'après la
  projection de progression de la parole (`tool_brain_speech`, jamais le planificateur) :
  `due` (l'écran peut agir), `pending` (pas encore), `obsolete` (la parole visée ne sera pas dite : annuler),
  `unanchored` (aucune parole de ce tour dans la file : attendre ou laisser tomber).

Le paragraphe `p` d'une intention est l'index du morceau (`SpeechChunk.index`) ; `anchor_chunk_id` calcule
l'id canonique du morceau (`presentation_chunk_ids`) quand le texte de la réponse est connu.
"""

from __future__ import annotations

from typing import Any, Mapping

from jarvis.domain.speech_presentation import presentation_chunk_ids, semantic_text_spans
from jarvis.domain.ui_intent import PROVIDER_OF_REF, UiIntentDraft, UiIntentTiming
from jarvis.runtime.tool_brain_choices import PROVIDERS, Refusal, UiState

DUE, PENDING, OBSOLETE, UNANCHORED = "due", "pending", "obsolete", "unanchored"


def check_intent_refs(draft: UiIntentDraft, state: UiState) -> tuple[Refusal, ...]:
    """Refus (codes des propriétaires) des refs qui ne sont pas des choix légaux de `state` ; vide : tout est valide."""

    legal: dict[str, set[str]] = {}
    refusals: list[Refusal] = []
    for ref in draft.refs:
        provider_id = PROVIDER_OF_REF[ref.kind]
        provider = PROVIDERS[provider_id]
        if provider.needs_scene and state.scene is None:
            refusals.append(Refusal("scene_unavailable", "refs", ref.id, "la scène n'est pas servie par Core"))
            continue
        if provider_id not in legal:
            legal[provider_id] = {choice.value for choice in provider.list_choices(state)}
        if ref.id not in legal[provider_id]:
            code = provider.refusal(state, ref.id)
            refusals.append(Refusal(code, "refs", ref.id, f"{ref.kind.value} n'est pas un choix légal ({provider_id})"))
    return tuple(refusals)


def anchor_chunk_id(draft: UiIntentDraft, request_id: str, text: str) -> str | None:
    """Id canonique du morceau que `draft.paragraph` vise, ou `None` (sans ancrage, ou paragraphe hors réponse)."""

    if draft.paragraph is None:
        return None
    spans = semantic_text_spans(text)
    ids = presentation_chunk_ids(request_id, spans)
    return ids[draft.paragraph] if draft.paragraph < len(ids) else None


def _chain(speech: Mapping[str, Any], correlation_id: str) -> Mapping[str, Any] | None:
    chains = [chain for chain in speech.get("chains", ()) if chain.get("corr") == correlation_id]
    # Plusieurs chaînes pour un tour (réponse puis relais) : la plus vive, déjà triée par `observe`.
    return chains[0] if chains else None


def intent_status(draft: UiIntentDraft, correlation_id: str, speech: Mapping[str, Any]) -> str:
    """`due | pending | obsolete | unanchored` pour une intention, d'après `SpeechProgress.data` (jamais écrit ici)."""

    if draft.timing is UiIntentTiming.NOW:
        return DUE
    chain = _chain(speech, correlation_id)
    if chain is None:
        return UNANCHORED
    phases: str = chain.get("phases", "")
    if draft.timing is UiIntentTiming.AFTER_SPEECH:
        if chain["state"] == "done":
            return DUE
        return OBSOLETE if chain["state"] == "interrupted" or "o" in phases else PENDING
    if draft.paragraph is None:
        started = any(letter in phases for letter in "Phiu")
        if started:
            return DUE
        return OBSOLETE if chain["state"] == "interrupted" else PENDING
    if draft.paragraph >= len(phases):
        return OBSOLETE  # le paragraphe visé n'existe pas dans la réponse : jamais dit
    letter = phases[draft.paragraph]
    if letter in "Phiu":
        return DUE  # commencé (même coupé) : l'utilisateur a entendu le début de ce paragraphe
    return OBSOLETE if letter == "o" else PENDING


__all__ = ["DUE", "OBSOLETE", "PENDING", "UNANCHORED", "anchor_chunk_id", "check_intent_refs", "intent_status"]
