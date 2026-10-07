"""Décideurs du Tool Brain : un modèle remplaçable et une règle déterministe (handoff jarvis-tool-brain-ui-orchestrator, S5).

Contrat : `docs/tool-brain-contracts.md` §13. Le port est `jarvis/ports/tool_brain.py` ; le runtime n'en connaît que lui.

- `ModelToolBrainDecider` : texte en entrée, JSON en sortie, **aucun outil**. Il réutilise le modèle texte déjà
  construit pour le worker d'enrichissement (`ClaudeCliEnrichmentModel` : CLI Claude en profil restreint
  `speculative_analysis`, `--tools ""`, sans MCP, sans session) ; seul le nom du modèle change :
  `JARVIS_TOOL_BRAIN_MODEL`, sinon `DEFAULT_TOOL_BRAIN_MODEL`. Remplacer le fournisseur = fournir un autre
  `TextModel` (même forme que `ContextEnrichmentModel`), sans toucher perception, manifeste ni validateur.
  Sans CLI Claude natif : le fournisseur rend `None`, le runtime dit `unavailable` et attend (backoff), l'interface
  ne bouge pas.
- `RuleToolBrainDecider` : décideur de référence, **sans modèle** (tests, traces hors ligne,
  `JARVIS_TOOL_BRAIN_DECIDER=rule`). Il traduit une intention valide en appel proposé ; il n'est pas un
  substitut de jugement.

Aucun des deux n'a accès aux services : ils renvoient un plan (`ToolBrainReply`), le runtime le valide.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from jarvis.ports.context_enrichment import (
    MODEL_TIMEOUT, MODEL_UNAVAILABLE, ContextEnrichmentModel, EnrichmentModelError,
)
from jarvis.ports.tool_brain import (
    DECIDER_FAILED, DECIDER_INVALID_OUTPUT, DECIDER_TIMEOUT, DECIDER_UNAVAILABLE, DeciderError, InspectionRequest,
    ProposedAction, ToolBrainDecider, ToolBrainReply, ToolBrainRequest, reply_from_payload,
)
from jarvis.runtime.context_enrichment_model import ClaudeCliEnrichmentModel
from jarvis.runtime.tool_brain_perception import INSPECTION_READS

TOOL_BRAIN_MODEL_ENV = "JARVIS_TOOL_BRAIN_MODEL"
TOOL_BRAIN_DECIDER_ENV = "JARVIS_TOOL_BRAIN_DECIDER"
#: Alias du CLI Claude : rapide et bon marché pour un choix borné parmi des valeurs données (changeable par env).
DEFAULT_TOOL_BRAIN_MODEL = "haiku"
MAX_PROMPT_BYTES = 96_000

INSTRUCTIONS = """You are the Tool Brain of a voice assistant: you decide what the screen (scene and boards) should \
show while the assistant talks. You never run anything: you answer ONE JSON object, nothing else.

Schema: {"inspections": [{"read": <one of READS>, "id": <id from perception or choices>}], \
"actions": [{"server": ..., "tool": ..., "arguments": {...}, "reason": <one short line>, "intent_id": <optional>}], \
"rationale": <one short line>}

Rules:
- Use ONLY tools listed in the manifest. Every id argument must be copied from manifest.choices or the perception: \
never invent an id.
- Prefer doing nothing (empty actions) to guessing. Never propose an irreversible tool unless an intent asks for it.
- "inspections" asks for targeted reads when you need detail the perception lacks (it already says what is visible, \
hidden and where); you get at most `inspections_left` more rounds. `inspection_results` already holds the read of every \
object a valid intent names, plus your earlier reads: never ask again for a read already answered. Do NOT read an object just to show, hide, move or pin \
it: acting needs no read; read only to learn content that changes WHAT to show. When inspections_left is 0, or you \
have enough, answer with actions only.
- Intents come from the assistant and say what the user should SEE (a hint, never a command). Honour valid ones \
(ref_refusals empty, status not "obsolete"); ignore the others. An "obsolete" intent is bound to speech that will never be said (cut off): do not act on it.
- Timing: an intent whose timing is "with_speech" or "after_speech" must NOT act now: tie its action with \
{"type":"intent","intent_id":<that intent>} so it fires when the speech reaches it. Omit "trigger" (act now) only for \
timing "now". Prefer tying an action to the speech or to a fact over a clock: {"type":"speech_chunk","chunk_id":<id from perception.speech>} (when that chunk starts), {"type":"speech","correlation_id":..,"when":"start"|"end","paragraph":<n, with start>}, {"type":"intent","intent_id":..}, {"type":"event","name":<fact name>}; {"type":"delay","seconds":<=120} only when nothing semantic fits. Actions bound to speech that gets interrupted are dropped by the runtime. The queue is perception.queue (ids, status); cancel or replace what is no longer wanted instead of stacking duplicates.
- The reads are: """


def tool_brain_model_name(environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    return str(env.get(TOOL_BRAIN_MODEL_ENV, "") or "").strip() or DEFAULT_TOOL_BRAIN_MODEL


def build_prompt(request: ToolBrainRequest) -> str:
    """Consigne + requête compacte (JSON canonique) ; borné, jamais de parole de la salle."""

    body = {"decision_id": request.decision_id, "round": request.round, "inspections_left": request.inspections_left,
            "trigger": request.trigger, "perception": request.perception, "intents": list(request.intents),
            "inspection_results": list(request.inspections), "manifest": request.manifest}
    text = (INSTRUCTIONS + ", ".join(INSPECTION_READS) + ".\n\nINPUT:\n"
            + json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    if len(text.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise DeciderError(DECIDER_FAILED, f"the decision input exceeds {MAX_PROMPT_BYTES} bytes")
    return text


def parse_plan(text: str) -> Any:
    """Premier objet JSON d'une réponse de modèle (clôtures ```json tolérées) ; sinon `DECIDER_INVALID_OUTPUT`."""

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        cleaned = cleaned.rsplit("```", 1)[0]
    start = cleaned.find("{")
    if start < 0:
        raise DeciderError(DECIDER_INVALID_OUTPUT, "no JSON object in the model answer")
    try:
        value, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    except ValueError as exc:
        raise DeciderError(DECIDER_INVALID_OUTPUT, f"the model answer is not valid JSON: {exc}") from None
    return value


class ModelToolBrainDecider:
    """Décideur sur un modèle texte sans outil (`ContextEnrichmentModel`, forme inchangée)."""

    def __init__(self, model: ContextEnrichmentModel) -> None:
        self._model = model
        self.name = f"model:{model.model}"

    async def decide(self, request: ToolBrainRequest, *, timeout_s: float) -> ToolBrainReply:
        prompt = build_prompt(request)
        try:
            raw = await self._model.complete(prompt, timeout_s=timeout_s)
        except EnrichmentModelError as exc:
            code = {MODEL_UNAVAILABLE: DECIDER_UNAVAILABLE, MODEL_TIMEOUT: DECIDER_TIMEOUT}.get(exc.code, DECIDER_FAILED)
            raise DeciderError(code, exc.detail) from exc
        return reply_from_payload(parse_plan(raw.text), model=raw.model or self._model.model, cost_usd=raw.cost_usd,
                                  duration_ms=raw.duration_ms, usage=raw.usage)


class RuleToolBrainDecider:
    """Référence déterministe : une intention valide devient un appel proposé. Pas de modèle, pas d'état."""

    name = "rule"

    async def decide(self, request: ToolBrainRequest, *, timeout_s: float) -> ToolBrainReply:
        usable = [item for item in request.intents if not item.get("ref_refusals") and item.get("kind") in
                  {"reveal", "attention"} and item.get("refs")]
        if not usable:
            return ToolBrainReply(rationale="no valid intent to honour", model=self.name)
        objects = [ref["id"] for item in usable for ref in item["refs"] if ref.get("kind") == "object"]
        if objects and request.inspections_left > 0 and not request.inspections:
            return ToolBrainReply((InspectionRequest("get_information_on", objects[0]),), rationale="look first",
                                  model=self.name)
        actions: list[ProposedAction] = []
        for item in usable:
            ids = [ref["id"] for ref in item["refs"] if ref.get("kind") == "object"]
            boards = [ref["id"] for ref in item["refs"] if ref.get("kind") == "board"]
            if ids:
                actions.append(ProposedAction("jarvis-display", "scene_get", {"object_ids": ids[:8]},
                                              "read what Jarvis wants shown", item.get("intent_id")))
            if boards:
                actions.append(ProposedAction("jarvis-workspace", "board_switch", {"board_id": boards[0]},
                                              "show the board Jarvis refers to", item.get("intent_id")))
        return ToolBrainReply(actions=tuple(actions[:6]), rationale="honour valid intents", model=self.name)


def tool_brain_decider_provider(control_settings: Callable[[], Mapping[str, object]], *, cwd: Path,
                                runtime_root: Path, environ: Mapping[str, str] | None = None
                                ) -> Callable[[], ToolBrainDecider | None]:
    """Décideur du moment (relu à chaque décision) ou `None` : `rule` sur demande, sinon le CLI Claude natif.

    Même condition que le worker d'enrichissement (CLI réglé = Claude, exécutable natif) : sinon `None`, le runtime
    reste `unavailable` avec son backoff et ne plante rien.
    """

    env = os.environ if environ is None else environ

    def provide() -> ToolBrainDecider | None:
        if str(env.get(TOOL_BRAIN_DECIDER_ENV, "") or "").strip().lower() == "rule":
            return RuleToolBrainDecider()
        from jarvis.runtime.agent_settings import resolve_agent_execution
        from jarvis.runtime.back_brain_worker import BackBrainJobWorker
        from jarvis.runtime.cli_catalog import resolve_command

        settings = resolve_agent_execution(control_settings(), cwd=cwd, runtime_root=runtime_root)
        if settings.agent_cli != "claude":
            return None
        if not BackBrainJobWorker._supports_speculative_settings(settings, resolve_command(settings.command)):
            return None
        return ModelToolBrainDecider(_ToolBrainCliModel(settings, tool_brain_model_name(env)))

    return provide


class _ToolBrainCliModel(ClaudeCliEnrichmentModel):
    """Même CLI restreint, mais l'empreinte de consigne d'enrichissement ne lui appartient pas : pas d'empreinte."""

    supports_images = False

    def _evidence(self, images: tuple) -> None:  # type: ignore[override]
        return None


__all__ = [
    "DEFAULT_TOOL_BRAIN_MODEL", "ModelToolBrainDecider", "RuleToolBrainDecider", "TOOL_BRAIN_DECIDER_ENV",
    "TOOL_BRAIN_MODEL_ENV", "build_prompt", "parse_plan", "tool_brain_decider_provider", "tool_brain_model_name",
]
