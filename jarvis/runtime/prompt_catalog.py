"""Registry of application-controlled model-visible prompt material.

Descriptors import the production constants/builders that own each value.  The
registry performs no provider, CLI, settings, or device I/O.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Mapping

from jarvis.adapters import global_context, openai_realtime
from jarvis.domain import (
    agenda_reminders, agent_charter, context_enrichment_prompt, conversation_prompt, front_brain_prompt, live_prompt,
    work_attention_prompt,
)
from jarvis.domain.prompt_registry import (
    PromptDescriptor,
    PromptOperation,
    PromptProgram,
    PromptRegistry,
    PromptStep,
    PromptTarget,
)
from jarvis.runtime import back_brain_delegation, claude_local, control_center, realtime_tools


VOICE_CONVERSATION_ADDITION = ""
FRONT_BRAIN_ANALYSIS_ADDITION = ""
LIVE_DUPLEX_ADDITION = ""
BACKEND_SYSTEM_ADDITION = ""
BACKEND_TURN_ADDITION = ""
_THIS_MODULE = sys.modules[__name__]


def _path(module) -> str:
    return str(Path(module.__file__).resolve())


def _descriptor(identifier: str, module, symbol: str, text: str, **kwargs) -> PromptDescriptor:
    return PromptDescriptor(identifier, _path(module), symbol, text, **kwargs)


def _recent_context(values: Mapping[str, object]) -> str:
    context = values.get("context")
    recent = context.get("recent_turns") or [] if isinstance(context, dict) else []
    lines = [f"{item.get('kind')}: {item.get('content')}" for item in recent[-12:] if isinstance(item, dict)]
    return "\nConversation context:\n" + "\n".join(lines) if lines else ""


def _initial_context(values: Mapping[str, object]) -> str:
    from jarvis.runtime.conversation_context import selected_voice_context

    raw = values.get("context")
    selected = selected_voice_context(raw if isinstance(raw, dict) else {})
    return json.dumps(
        [{"role": item.role.value, "text": item.text} for item in selected.messages],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _reflex(values: Mapping[str, object]) -> str:
    transcript = values.get("transcript")
    avoid = values.get("avoid")
    return openai_realtime.build_reflex_instruction(
        transcript if isinstance(transcript, str) else "",
        tuple(item for item in avoid if isinstance(item, str)) if isinstance(avoid, (list, tuple)) else (),
        persona=values.get("persona") if isinstance(values.get("persona"), str) else openai_realtime.JARVIS_PERSONA,
    )


def _front_brain_input(values: Mapping[str, object]) -> str:
    observation = values.get("observation")
    if isinstance(observation, str):
        return observation
    return json.dumps(observation if isinstance(observation, dict) else {}, ensure_ascii=False, separators=(",", ":"))


def _backend_brief(values: Mapping[str, object]) -> str:
    context = values.get("context")
    request_text = values.get("request_text")
    return control_center.build_agent_brief(
        context if isinstance(context, dict) else {},
        request_text if isinstance(request_text, str) else "",
    )


def conversation_session_name(*, tools: bool, display: bool, hands: bool) -> str:
    """Suffixe du programme de conversation Claude : une capacité réellement déclarée = un segment.

    `session`, `display_session`, …, `tools_display_barehands_session` ; l'invocation
    est `conversation_<nom>` et le programme `backend.claude.conversation.<nom>`.
    """

    return "{}{}{}session".format("tools_" if tools else "", "display_" if display else "",
                                  "barehands_" if hands else "")


def _global_context(values: Mapping[str, object]) -> str:
    # Sans variable déclarée : un appelant qui ne fournit pas le dossier (tests,
    # aperçu du Control Center) obtient une couche vide, pas une consigne non résolue.
    return global_context.render_global_context_prompt(values.get("global_context"))


def _request_text(values: Mapping[str, object]) -> str:
    request_text = values.get("request_text")
    return request_text if isinstance(request_text, str) else ""


def _static_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def default_prompt_registry() -> PromptRegistry:
    """Return a fresh deterministic registry backed by current source values."""
    descriptors = (
        _descriptor("voice.persona", openai_realtime, "JARVIS_PERSONA", openai_realtime.JARVIS_PERSONA,
                    editable=True, apply_policy="next_session"),
        _descriptor("voice.rules.legacy", openai_realtime, "OPERATING_RULES", openai_realtime.OPERATING_RULES,
                    apply_policy="read_only"),
        _descriptor("voice.rules.continuous", openai_realtime, "CONTINUOUS_BRAIN_OPERATING_RULES",
                    openai_realtime.CONTINUOUS_BRAIN_OPERATING_RULES, apply_policy="read_only"),
        _descriptor("voice.rules.conversation", conversation_prompt, "CONVERSATION_OPERATING_RULES",
                    conversation_prompt.CONVERSATION_OPERATING_RULES, apply_policy="read_only"),
        _descriptor("voice.conversation.addition", _THIS_MODULE, "VOICE_CONVERSATION_ADDITION",
                    VOICE_CONVERSATION_ADDITION, editable=True, apply_policy="next_session"),
        _descriptor("voice.recent_context", openai_realtime, "build_session_instructions",
                    "Runtime selected recent conversation data", variables=("context",), dynamic=True,
                    apply_policy="read_only"),
        _descriptor("voice.initial_context", __import__("jarvis.runtime.conversation_context", fromlist=["x"]),
                    "selected_voice_context", "Runtime selected confirmed conversation messages",
                    variables=("context",), dynamic=True, apply_policy="read_only"),
        _descriptor("voice.tools.legacy", realtime_tools, "tools_for", _static_json(realtime_tools.tools_for(continuous_brain=False)),
                    apply_policy="read_only"),
        _descriptor("voice.tools.continuous", realtime_tools, "tools_for", _static_json(realtime_tools.tools_for(continuous_brain=True)),
                    apply_policy="read_only"),
        _descriptor("voice.tools.conversation", back_brain_delegation, "conversation_tools",
                    _static_json(back_brain_delegation.conversation_tools()), apply_policy="read_only"),
        _descriptor("realtime.reflex.response", openai_realtime, "build_reflex_instruction",
                    openai_realtime.REFLEX_INSTRUCTION, variables=("transcript", "avoid"), dynamic=True,
                    apply_policy="read_only", dependencies=(("persona", "voice.persona"),)),
        _descriptor("realtime.verbatim.response", openai_realtime, "VERBATIM_SPEECH_INSTRUCTION",
                    openai_realtime.VERBATIM_SPEECH_INSTRUCTION, variables=("text",),
                    apply_policy="read_only"),
        _descriptor("front_brain.analysis.instructions", front_brain_prompt, "FRONT_BRAIN_INSTRUCTIONS",
                    front_brain_prompt.FRONT_BRAIN_INSTRUCTIONS, apply_policy="read_only"),
        _descriptor("front_brain.analysis.addition", _THIS_MODULE, "FRONT_BRAIN_ANALYSIS_ADDITION",
                    FRONT_BRAIN_ANALYSIS_ADDITION, editable=True, apply_policy="next_invocation"),
        _descriptor("front_brain.analysis.input", front_brain_prompt, "build_front_brain_payload",
                    "Runtime observation JSON", variables=("observation",), dynamic=True, apply_policy="read_only"),
        _descriptor("front_brain.analysis.schema", front_brain_prompt, "front_brain_schema",
                    _static_json(front_brain_prompt.front_brain_schema()), apply_policy="read_only"),
        _descriptor("live.duplex.instructions", live_prompt, "LIVE_OPERATING_RULES", live_prompt.LIVE_OPERATING_RULES,
                    apply_policy="read_only"),
        _descriptor("live.duplex.addition", _THIS_MODULE, "LIVE_DUPLEX_ADDITION", LIVE_DUPLEX_ADDITION,
                    editable=True, apply_policy="next_session"),
        _descriptor("backend.claude.conversation.system", claude_local, "BRAIN_SYSTEM_PROMPT",
                    claude_local.BRAIN_SYSTEM_PROMPT, apply_policy="read_only"),
        # Consigne d'affichage (Slice 06) : seulement dans le programme
        # `conversation_display_session`, choisi quand `scene.enabled` est vrai.
        # Consigne des réglages (20/09/2026) : dans **les quatre** programmes de
        # conversation, parce que `jarvis-console` est déclaré sans interrupteur.
        _descriptor("backend.claude.conversation.settings", claude_local, "BRAIN_SETTINGS_PROMPT",
                    claude_local.BRAIN_SETTINGS_PROMPT, apply_policy="read_only"),
        # Captures et preuves (session-context-recording, Slice 09) : dans tous les
        # programmes de conversation, `jarvis-capture` étant déclaré sans interrupteur.
        _descriptor("backend.claude.conversation.capture", claude_local, "BRAIN_CAPTURE_PROMPT",
                    claude_local.BRAIN_CAPTURE_PROMPT, apply_policy="read_only"),
        # Boards, Sessions et mémoire (board-memory-workspace-inspector, Slice 06) : dans tous les
        # programmes de conversation, `jarvis-workspace` étant déclaré sans interrupteur.
        _descriptor("backend.claude.conversation.workspace", claude_local, "BRAIN_WORKSPACE_PROMPT",
                    claude_local.BRAIN_WORKSPACE_PROMPT, apply_policy="read_only"),
        # Passerelle `jarvis-tools` (plugins MCP, Slice 05 ; ARCH E20) : composée
        # **seulement** quand la passerelle est réellement déclarée — les programmes
        # Claude `tools_*` (fichier `--mcp-config` écrit) et le tour Codex
        # `tools_turn` (overrides passés et bac à sable `danger-full-access`).
        _descriptor("backend.conversation.tools", claude_local, "BRAIN_TOOLS_PROMPT",
                    claude_local.BRAIN_TOOLS_PROMPT, apply_policy="read_only"),
        _descriptor("backend.claude.conversation.display", claude_local, "BRAIN_DISPLAY_PROMPT",
                    claude_local.BRAIN_DISPLAY_PROMPT, apply_policy="read_only"),
        # Lecture structurée (Slice 09, scene_get / scene_query) : même programme.
        _descriptor("backend.claude.conversation.scene_read", claude_local, "BRAIN_SCENE_READ_PROMPT",
                    claude_local.BRAIN_SCENE_READ_PROMPT, apply_policy="read_only"),
        # Artefacts groupés après un travail terminé (Slice 07) : même programme.
        _descriptor("backend.claude.conversation.artifacts", claude_local, "BRAIN_ARTIFACT_PROMPT",
                    claude_local.BRAIN_ARTIFACT_PROMPT, apply_policy="read_only"),
        # Fenêtres prefab (prefab-foundation, Slice 07) : même programme, après les artefacts.
        # Drive en lecture seule (2026-10-07) : dans tous les programmes, `jarvis-drive` étant déclaré sans interrupteur.
        _descriptor("backend.claude.conversation.drive", claude_local, "BRAIN_DRIVE_PROMPT",
                    claude_local.BRAIN_DRIVE_PROMPT, apply_policy="read_only"),
        _descriptor("backend.claude.conversation.prefabs", claude_local, "BRAIN_PREFAB_PROMPT",
                    claude_local.BRAIN_PREFAB_PROMPT, apply_policy="read_only"),
        # Consigne Bare Hands (Slice 12) : seulement dans les programmes dont le
        # nom porte `barehands`, choisis quand `barehands_test_mode.enabled` est
        # vrai. Indépendante de la scène — les deux interrupteurs ne sont pas liés.
        _descriptor("backend.claude.conversation.barehands", claude_local, "BRAIN_BAREHANDS_PROMPT",
                    claude_local.BRAIN_BAREHANDS_PROMPT, apply_policy="read_only"),
        # Contexte global (`<data_root>/CONTEXT_GLOBAL/`, docs/context-global.md) :
        # règles fixes du dossier puis fichiers listés par `base_context.yaml`,
        # assemblés par `ClaudeLocalAgent.start` à chaque lancement du CLI.
        _descriptor("backend.claude.conversation.global_context", global_context, "render_global_context_prompt",
                    "Runtime CONTEXT_GLOBAL rules and files assembled from base_context.yaml",
                    dynamic=True, apply_policy="read_only"),
        _descriptor("backend.claude.job_result.system", claude_local, "JOB_RESULT_SYSTEM_PROMPT",
                    claude_local.JOB_RESULT_SYSTEM_PROMPT, apply_policy="read_only"),
        _descriptor("backend.claude.speculative.system", claude_local, "SPECULATIVE_SYSTEM_PROMPT",
                    claude_local.SPECULATIVE_SYSTEM_PROMPT, apply_policy="read_only"),
        # Preparation speculative de PRESENTATION (Slice 11) : consigne propre,
        # parce que celle de `speculative` interdit explicitement les outils.
        _descriptor("backend.claude.presentation_preparation.system", claude_local,
                    "PRESENTATION_PREPARATION_SYSTEM_PROMPT",
                    claude_local.PRESENTATION_PREPARATION_SYSTEM_PROMPT, apply_policy="read_only"),
        _descriptor("backend.system.addition", _THIS_MODULE, "BACKEND_SYSTEM_ADDITION",
                    BACKEND_SYSTEM_ADDITION, editable=True, apply_policy="next_session"),
        _descriptor("backend.turn.addition", _THIS_MODULE, "BACKEND_TURN_ADDITION",
                    BACKEND_TURN_ADDITION, editable=True, apply_policy="next_invocation"),
        # Mode calibration (Slice 06 adaptative) : apposé au tour par
        # `build_agent_brief` pendant une séance déclarée par la page.
        _descriptor("backend.turn.calibration_mode", control_center, "BRIEF_CALIBRATION_MODE",
                    control_center.BRIEF_CALIBRATION_MODE, apply_policy="read_only"),
        _descriptor("backend.turn.brief", control_center, "build_agent_brief", "Runtime Core context and admitted request",
                    variables=("context", "request_text"), dynamic=True, apply_policy="read_only"),
        # Tour Codex sans contexte ni comportement mais avec la passerelle (E20) :
        # la demande part telle quelle, sans l'en-tête du brief.
        _descriptor("backend.turn.request", _THIS_MODULE, "_request_text", "Runtime admitted request, unchanged",
                    variables=("request_text",), dynamic=True, apply_policy="read_only"),
        # Charte apposée par le hook d'aiguillage sur la consigne de chaque
        # sous-agent (`routing_hook.charter_input`). Elle est déclarée ici parce
        # qu'elle est visible du modèle ; elle n'est appliquée par aucun
        # programme, le hook étant un processus court qui lit la constante.
        _descriptor("agent.task.charter", agent_charter, "AGENT_TASK_CHARTER",
                    agent_charter.AGENT_TASK_CHARTER, variables=("brief",), apply_policy="read_only"),
        # Consigne du tour que Core ouvre seul sur un changement de travail de
        # fond. Elle voyage comme le texte d'un tour, donc par `backend.*.turn` ;
        # elle est déclarée ici parce qu'elle est visible du modèle.
        # Worker d'enrichissement du Context actif (session-context, Slice 08) : tête du
        # message du modèle sans outil (`speculative_analysis`), résumé puis description.
        _descriptor("core.context_enrichment.summary", context_enrichment_prompt, "SUMMARY_INSTRUCTIONS",
                    context_enrichment_prompt.SUMMARY_INSTRUCTIONS, apply_policy="read_only"),
        _descriptor("core.context_enrichment.describe", context_enrichment_prompt, "DESCRIBE_INSTRUCTIONS",
                    context_enrichment_prompt.DESCRIBE_INSTRUCTIONS, apply_policy="read_only"),
        _descriptor("core.work_attention.wake", work_attention_prompt, "WORK_ATTENTION_WAKE_PROMPT",
                    work_attention_prompt.WORK_ATTENTION_WAKE_PROMPT, editable=True,
                    apply_policy="next_invocation"),
        # Tête de la consigne du tour de rappel d'agenda (`core.agenda_reminders`) :
        # suivie des rendez-vous, données de l'agenda. Visible du modèle, non éditable.
        _descriptor("core.agenda_reminder.wake", agenda_reminders, "AGENDA_REMINDER_PROMPT_HEAD",
                    agenda_reminders.AGENDA_REMINDER_PROMPT_HEAD, apply_policy="read_only"),
    )

    def session(program_id: str, target: PromptTarget, rules: str, tools: str,
                *, context: str = "voice.recent_context", addition: str = "voice.conversation.addition") -> PromptProgram:
        steps = [
            PromptStep("voice.persona", "session.instructions"),
            PromptStep(rules, "session.instructions", separator=" "),
            PromptStep(addition, "session.instructions", separator="\n"),
        ]
        if context:
            steps.append(PromptStep(context, "session.instructions" if context == "voice.recent_context" else "session.initial_context",
                                    PromptOperation.APPEND if context == "voice.recent_context" else PromptOperation.MESSAGE))
        steps.append(PromptStep(tools, "session.tools", PromptOperation.REPLACE))
        return PromptProgram(program_id, target, tuple(steps))

    def backend_session(program_id: str, invocation: str, *, display: bool = False, hands: bool = False,
                        tools: bool = False) -> PromptProgram:
        """La consigne système du cerveau conversationnel, composée de ses capacités **déclarées**.

        Deux interrupteurs indépendants (`scene.enabled`, `barehands_test_mode.enabled`)
        et la passerelle `jarvis-tools` (déclarée ou non à ce lancement, ARCH E20)
        donnent huit programmes ; ils sont construits ici plutôt que recopiés,
        pour qu'un bloc corrigé le soit dans tous. L'ordre est celui d'avant
        la Slice 12 : écran d'abord, mains ensuite, ajout de l'utilisateur en dernier.
        """

        steps = [
            PromptStep("backend.claude.conversation.system", "cli.append_system_prompt"),
            # Les réglages viennent juste après le socle, avant l'écran et les
            # mains : c'est la seule capacité des quatre programmes, et la
            # placer en tête évite qu'elle passe pour une annexe de l'une des
            # deux autres.
            PromptStep("backend.claude.conversation.settings", "cli.append_system_prompt", separator="\n"),
            # Captures et preuves (Slice 09) : juste après les réglages, même raison.
            PromptStep("backend.claude.conversation.capture", "cli.append_system_prompt", separator="\n"),
            # Boards, Sessions et mémoire (Slice 06 board-memory) : même raison.
            PromptStep("backend.claude.conversation.workspace", "cli.append_system_prompt", separator="\n"),
            PromptStep("backend.claude.conversation.drive", "cli.append_system_prompt", separator="\n"),
        ]
        if tools:
            # La passerelle suit les réglages, quand son `--mcp-config` a bien été écrit.
            steps.append(PromptStep("backend.conversation.tools", "cli.append_system_prompt", separator="\n"))
        if display:
            steps += [
                PromptStep("backend.claude.conversation.display", "cli.append_system_prompt", separator="\n"),
                # Sans séparateur : la ligne prolonge la liste « ÉCRAN ».
                PromptStep("backend.claude.conversation.scene_read", "cli.append_system_prompt"),
                PromptStep("backend.claude.conversation.artifacts", "cli.append_system_prompt", separator="\n"),
                # Fenêtres prefab (prefab-foundation, Slice 07) : outils `prefab_*` du même serveur.
                PromptStep("backend.claude.conversation.prefabs", "cli.append_system_prompt", separator="\n"),
            ]
        if hands:
            steps.append(PromptStep("backend.claude.conversation.barehands", "cli.append_system_prompt", separator="\n"))
        # Le contexte global vient après les capacités : la personnalité et la
        # mémoire que l'agent s'écrit ne réécrivent pas ses règles de fonctionnement.
        steps.append(PromptStep("backend.claude.conversation.global_context", "cli.append_system_prompt",
                                separator="\n\n"))
        steps.append(PromptStep("backend.system.addition", "cli.append_system_prompt", separator="\n"))
        return PromptProgram(program_id, PromptTarget("backend", None, "claude", None, None, invocation), tuple(steps))

    programs = (
        session("voice.simple.openai.session",
                PromptTarget("conversation", "simple", "openai", None, "explicit", "session"),
                "voice.rules.conversation", "voice.tools.conversation", context="voice.initial_context"),
        session("voice.front_brain.openai.session",
                PromptTarget("conversation", "front_brain", "openai", None, "explicit", "session"),
                "voice.rules.conversation", "voice.tools.conversation", context="voice.initial_context"),
        session("voice.legacy.openai.session",
                PromptTarget("conversation", "simple", "openai", None, "legacy", "session"),
                "voice.rules.legacy", "voice.tools.legacy"),
        session("voice.legacy.google.session",
                PromptTarget("conversation", "simple", "google", None, "legacy", "session"),
                "voice.rules.legacy", "voice.tools.legacy"),
        session("voice.continuous.openai.session",
                PromptTarget("conversation", "simple", "openai", None, "continuous_brain", "session"),
                "voice.rules.continuous", "voice.tools.continuous"),
        PromptProgram("voice.duplex.openai.session",
                      PromptTarget("conversation", "duplex", "openai", None, "explicit", "session"), (
                          PromptStep("live.duplex.instructions", "session.instructions", PromptOperation.REPLACE),
                          PromptStep("live.duplex.addition", "session.instructions", separator="\n"),
                          PromptStep("voice.initial_context", "session.initial_context", PromptOperation.MESSAGE),
                      )),
        PromptProgram("realtime.reflex.response",
                      PromptTarget("reflex", None, "openai", None, None, "reflex"), (
                          PromptStep("realtime.reflex.response", "response.instructions", PromptOperation.REPLACE),
                      )),
        PromptProgram("realtime.verbatim.response",
                      PromptTarget("speech", None, "openai", None, None, "verbatim"), (
                          PromptStep("realtime.verbatim.response", "response.instructions", PromptOperation.REPLACE),
                      )),
        PromptProgram("front_brain.openai.analysis",
                      PromptTarget("analysis", "front_brain", "openai", None, "explicit", "hint"), (
                          PromptStep("front_brain.analysis.instructions", "request.instructions", PromptOperation.REPLACE),
                          PromptStep("front_brain.analysis.addition", "request.instructions", separator="\n"),
                          PromptStep("front_brain.analysis.input", "request.user_message", PromptOperation.MESSAGE),
                          PromptStep("front_brain.analysis.schema", "request.response_schema", PromptOperation.REPLACE),
                      )),
        *(backend_session(f"backend.claude.conversation.{name}", f"conversation_{name}",
                          display=display, hands=hands, tools=tools)
          for tools in (False, True) for hands in (False, True) for display in (False, True)
          for name in [conversation_session_name(tools=tools, display=display, hands=hands)]),
        PromptProgram("backend.claude.job_result.session",
                      PromptTarget("backend", None, "claude", None, None, "job_result_session"), (
                          PromptStep("backend.claude.job_result.system", "cli.append_system_prompt"),
                      )),
        PromptProgram("backend.claude.speculative.session",
                      PromptTarget("backend", None, "claude", None, None, "speculative_session"), (
                          PromptStep("backend.claude.speculative.system", "cli.system_prompt", PromptOperation.REPLACE),
                      )),
        PromptProgram("backend.claude.presentation_preparation.session",
                      PromptTarget("backend", None, "claude", None, None, "presentation_preparation_session"), (
                          PromptStep("backend.claude.presentation_preparation.system", "cli.system_prompt",
                                     PromptOperation.REPLACE),
                      )),
        PromptProgram("backend.claude.context_enrichment.summary_turn",
                      PromptTarget("backend", None, "claude", None, None, "context_enrichment_summary_turn"), (
                          PromptStep("core.context_enrichment.summary", "stdin.user_message"),
                      )),
        PromptProgram("backend.claude.context_enrichment.describe_turn",
                      PromptTarget("backend", None, "claude", None, None, "context_enrichment_describe_turn"), (
                          PromptStep("core.context_enrichment.describe", "stdin.user_message"),
                      )),
        PromptProgram("backend.claude.turn",
                      PromptTarget("backend", None, "claude", None, None, "turn"), (
                          PromptStep("backend.turn.addition", "stdin.user_message"),
                          PromptStep("backend.turn.brief", "stdin.user_message", separator="\n"),
                      )),
        PromptProgram("backend.codex.turn",
                      PromptTarget("backend", None, "codex", None, None, "turn"), (
                          PromptStep("backend.turn.addition", "stdin.user_message"),
                          PromptStep("backend.turn.brief", "stdin.user_message", separator="\n"),
                      )),
        # Codex n'a pas de consigne système : la passerelle se dit au tour, et
        # seulement quand ce tour la déclare et peut appeler `call_tool` (E20).
        PromptProgram("backend.codex.tools_turn",
                      PromptTarget("backend", None, "codex", None, None, "tools_turn"), (
                          PromptStep("backend.turn.addition", "stdin.user_message"),
                          PromptStep("backend.conversation.tools", "stdin.user_message", separator="\n"),
                          PromptStep("backend.turn.brief", "stdin.user_message", separator="\n"),
                      )),
        # Le raccourci « texte brut » de `compose_agent_turn`, quand le tour déclare
        # la passerelle : seule la couche outils s'ajoute à la demande (E20).
        PromptProgram("backend.codex.tools_plain_turn",
                      PromptTarget("backend", None, "codex", None, None, "tools_plain_turn"), (
                          PromptStep("backend.conversation.tools", "stdin.user_message"),
                          PromptStep("backend.turn.request", "stdin.user_message", separator="\n"),
                      )),
    )
    return PromptRegistry(descriptors, programs, renderers={
        "voice.recent_context": _recent_context,
        "voice.initial_context": _initial_context,
        "realtime.reflex.response": _reflex,
        "front_brain.analysis.input": _front_brain_input,
        "backend.turn.brief": _backend_brief,
        "backend.turn.request": _request_text,
        "backend.claude.conversation.global_context": _global_context,
    })
