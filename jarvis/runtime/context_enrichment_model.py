"""Modèle du worker d'enrichissement : le CLI Claude en profil restreint, sans outil (Slice 08).

Audit (handoff session-context-recording, Slice 08) : le mécanisme canonique
d'un appel de modèle d'arrière-plan dans ce dépôt est un `ClaudeLocalAgent`
**possédé** et restreint (`back_brain_worker.create_job_agent`). Le profil
`speculative_analysis` est exactement « texte en entrée, texte en sortie » :
`--restricted --tools ""` (zéro outil), `--strict-mcp-config` (aucun MCP),
`--no-session-persistence`, consigne système **remplacée**, entrée et réponse
jamais recopiées dans `runtime/trace.jsonl` (la parole de la salle n'y entre
pas, D13/D17). Un processus neuf par appel, fermé ensuite (`close_owned`) :
aucun fil de conversation ne s'accumule entre deux tours d'enrichissement.

Coût : `total_cost_usd` rendu par le CLI (coût fournisseur, pas de table de
prix embarquée). Modèle : `JARVIS_CONTEXT_ENRICHMENT_MODEL`, sinon
`DEFAULT_ENRICHMENT_MODEL` (alias CLI `haiku`, le moins cher qui lit les
images). Aucun rôle « modèle d'arrière-plan » n'existe dans les réglages : le
modèle du cerveau (souvent plus cher) n'est pas repris.

Réflexion coupée (décision PM, coût) : le processus reçoit
`MAX_THINKING_TOKENS=0` (`ENRICHMENT_ENVIRONMENT`) ; les jetons de réflexion
rendus par le CLI sont remontés (`usage.thinking_tokens`) pour le vérifier.
Consignes : registre de prompts (`backend.claude.context_enrichment.*`) ;
chaque appel journalise l'empreinte du programme (`agent.prompt`), jamais le
texte rempli. Trace du profil restreint : métadonnées seulement
(`cli_stream.restricted_event_view`).

Disponible seulement quand le CLI réglé est Claude **et** un exécutable natif
(même règle que le spéculatif du back-brain : un shim `.cmd` perd l'argument
vide de `--tools`). Sinon `None` : le worker reste `unavailable`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Mapping

from jarvis.ports.context_enrichment import (
    MODEL_FAILED, MODEL_TIMEOUT, EnrichmentImage, EnrichmentModelError, EnrichmentReply,
)
from jarvis.runtime.agent_settings import AgentExecutionSettings, resolve_agent_execution

ENRICHMENT_MODEL_ENV = "JARVIS_CONTEXT_ENRICHMENT_MODEL"
#: Environnement ajouté au CLI d'enrichissement : aucune réflexion payée pour un résumé.
ENRICHMENT_ENVIRONMENT = {"MAX_THINKING_TOKENS": "0"}
#: Profil du CLI : sans outil, sans MCP, sans session (épinglé par un test).
ENRICHMENT_PROFILE = "speculative_analysis"
#: Invocations du registre de prompts : résumé (texte) et description (image jointe).
SUMMARY_INVOCATION = "context_enrichment_summary_turn"
DESCRIBE_INVOCATION = "context_enrichment_describe_turn"
#: Alias du CLI Claude : Haiku, multimodal, le moins cher de la gamme.
DEFAULT_ENRICHMENT_MODEL = "haiku"


def enrichment_model_name(environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    return str(env.get(ENRICHMENT_MODEL_ENV, "") or "").strip() or DEFAULT_ENRICHMENT_MODEL


class ClaudeCliEnrichmentModel:
    """`ContextEnrichmentModel` sur un `ClaudeLocalAgent` `speculative_analysis` neuf par appel."""

    supports_images = True

    def __init__(self, settings: AgentExecutionSettings, model: str, *,
                 agent_factory: Callable[..., Any] | None = None) -> None:
        self._settings = settings
        self.model = model
        self._factory = agent_factory

    def _agent(self) -> Any:
        if self._factory is not None:
            return self._factory(self._settings, self.model)
        from jarvis.runtime.claude_local import ClaudeLocalAgent

        return ClaudeLocalAgent(runtime_root=self._settings.runtime_root, cwd=self._settings.cwd,
                                command=self._settings.command, model=self.model,
                                execution_profile=ENRICHMENT_PROFILE,
                                prompt_overrides=self._settings.prompt_overrides,
                                environment=ENRICHMENT_ENVIRONMENT)

    def _evidence(self, images: tuple[EnrichmentImage, ...]) -> dict[str, object] | None:
        """Empreinte du programme de consigne de cet appel (aucun texte) ; `None` si irrésoluble."""

        from jarvis.domain.prompt_registry import PromptError, PromptTarget
        from jarvis.runtime.prompt_runtime import prompt_evidence, resolve_prompt

        invocation = DESCRIBE_INVOCATION if images else SUMMARY_INVOCATION
        try:
            resolution = resolve_prompt(PromptTarget("backend", None, "claude", None, None, invocation))
        except PromptError:
            return None  # argued: identity only; the call itself does not depend on it
        return prompt_evidence(resolution, application="sent", channel="stdin.user_message")

    async def complete(self, prompt: str, *, timeout_s: float,
                       images: tuple[EnrichmentImage, ...] = ()) -> EnrichmentReply:
        agent = self._agent()
        evidence = self._evidence(images)
        extra: dict[str, Any] = {"images": tuple((i.media_type, i.data) for i in images)} if images else {}
        if evidence is not None:
            extra["prompt_evidence"] = evidence
        try:
            raw = await agent.ask(prompt, timeout_s=timeout_s, **extra)
        finally:
            try:
                await agent.close_owned()
            except Exception:  # noqa: BLE001 - argued: the owned process tree is killed by its Job Object anyway
                pass
        if not isinstance(raw, dict):
            raise EnrichmentModelError(MODEL_FAILED, "the CLI returned no result")
        if raw.get("ok") is not True:
            code = str(raw.get("code") or "")
            detail = str(raw.get("error") or code or "CLI turn failed")
            raise EnrichmentModelError(MODEL_TIMEOUT if code == "claude_timeout" else MODEL_FAILED, detail)
        cost = raw.get("cost_usd")
        duration = raw.get("duration_ms")
        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        return EnrichmentReply(
            text=str(raw.get("text") or ""), model=self.model,
            cost_usd=float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None,
            duration_ms=int(duration) if isinstance(duration, int) and not isinstance(duration, bool) else None,
            usage=_usage(usage))


def _usage(usage: Mapping[str, Any]) -> dict[str, int]:
    """Jetons rendus par le CLI, réflexion comprise (`output_tokens_details.thinking_tokens`)."""

    kept = {key: usage[key] for key in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                        "cache_creation_input_tokens")
            if isinstance(usage.get(key), int) and not isinstance(usage.get(key), bool)}
    details = usage.get("output_tokens_details")
    thinking = details.get("thinking_tokens") if isinstance(details, Mapping) else usage.get("thinking_tokens")
    if isinstance(thinking, int) and not isinstance(thinking, bool):
        kept["thinking_tokens"] = thinking
    return kept


def enrichment_model_provider(control_settings: Callable[[], Mapping[str, object]], *, cwd: Path,
                              runtime_root: Path) -> Callable[[], ClaudeCliEnrichmentModel | None]:
    """Fournisseur relu à chaque tour (réglages du Control Center) ; `None` sans CLI Claude natif."""

    def provide() -> ClaudeCliEnrichmentModel | None:
        from jarvis.runtime.back_brain_worker import BackBrainJobWorker
        from jarvis.runtime.cli_catalog import resolve_command

        settings = resolve_agent_execution(control_settings(), cwd=cwd, runtime_root=runtime_root)
        if settings.agent_cli != "claude":
            return None
        if not BackBrainJobWorker._supports_speculative_settings(settings, resolve_command(settings.command)):
            return None
        return ClaudeCliEnrichmentModel(settings, enrichment_model_name())

    return provide


__all__ = ["ClaudeCliEnrichmentModel", "DEFAULT_ENRICHMENT_MODEL", "ENRICHMENT_ENVIRONMENT", "ENRICHMENT_MODEL_ENV",
           "ENRICHMENT_PROFILE",
           "enrichment_model_name", "enrichment_model_provider"]
