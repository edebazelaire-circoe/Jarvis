"""Registry of application-controlled model-visible prompt material.

Descriptors import the production constants/builders that own each value.  The
registry performs no provider, CLI, settings, or device I/O.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Mapping

from jarvis.adapters import openai_realtime
from jarvis.domain import agent_charter, conversation_prompt, front_brain_prompt, live_prompt, work_attention_prompt
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
        _descriptor("backend.claude.conversation.display", claude_local, "BRAIN_DISPLAY_PROMPT",
                    claude_local.BRAIN_DISPLAY_PROMPT, apply_policy="read_only"),
        # Lecture structurée (Slice 09, scene_get / scene_query) : même programme.
        _descriptor("backend.claude.conversation.scene_read", claude_local, "BRAIN_SCENE_READ_PROMPT",
                    claude_local.BRAIN_SCENE_READ_PROMPT, apply_policy="read_only"),
        # Artefacts groupés après un travail terminé (Slice 07) : même programme.
        _descriptor("backend.claude.conversation.artifacts", claude_local, "BRAIN_ARTIFACT_PROMPT",
                    claude_local.BRAIN_ARTIFACT_PROMPT, apply_policy="read_only"),
        # Consigne Bare Hands (Slice 12) : seulement dans les programmes dont le
        # nom porte `barehands`, choisis quand `barehands_test_mode.enabled` est
        # vrai. Indépendante de la scène — les deux interrupteurs ne sont pas liés.
        _descriptor("backend.claude.conversation.barehands", claude_local, "BRAIN_BAREHANDS_PROMPT",
                    claude_local.BRAIN_BAREHANDS_PROMPT, apply_policy="read_only"),
        _descriptor("backend.claude.job_result.system", claude_local, "JOB_RESULT_SYSTEM_PROMPT",
                    claude_local.JOB_RESULT_SYSTEM_PROMPT, apply_policy="read_only"),
        _descriptor("backend.claude.speculative.system", claude_local, "SPECULATIVE_SYSTEM_PROMPT",
                    claude_local.SPECULATIVE_SYSTEM_PROMPT, apply_policy="read_only"),
        _descriptor("backend.system.addition", _THIS_MODULE, "BACKEND_SYSTEM_ADDITION",
                    BACKEND_SYSTEM_ADDITION, editable=True, apply_policy="next_session"),
        _descriptor("backend.turn.addition", _THIS_MODULE, "BACKEND_TURN_ADDITION",
                    BACKEND_TURN_ADDITION, editable=True, apply_policy="next_invocation"),
        _descriptor("backend.turn.brief", control_center, "build_agent_brief", "Runtime Core context and admitted request",
                    variables=("context", "request_text"), dynamic=True, apply_policy="read_only"),
        # Charte apposée par le hook d'aiguillage sur la consigne de chaque
        # sous-agent (`routing_hook.charter_input`). Elle est déclarée ici parce
        # qu'elle est visible du modèle ; elle n'est appliquée par aucun
        # programme, le hook étant un processus court qui lit la constante.
        _descriptor("agent.task.charter", agent_charter, "AGENT_TASK_CHARTER",
                    agent_charter.AGENT_TASK_CHARTER, variables=("brief",), apply_policy="read_only"),
        # Consigne du tour que Core ouvre seul sur un changement de travail de
        # fond. Elle voyage comme le texte d'un tour, donc par `backend.*.turn` ;
        # elle est déclarée ici parce qu'elle est visible du modèle.
        _descriptor("core.work_attention.wake", work_attention_prompt, "WORK_ATTENTION_WAKE_PROMPT",
                    work_attention_prompt.WORK_ATTENTION_WAKE_PROMPT, editable=True,
                    apply_policy="next_invocation"),
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

    def backend_session(program_id: str, invocation: str, *, display: bool = False, hands: bool = False) -> PromptProgram:
        """La consigne système du cerveau conversationnel, composée de ses capacités **déclarées**.

        Deux interrupteurs indépendants (`scene.enabled`, `barehands_test_mode.enabled`)
        donnent quatre programmes ; ils sont construits ici plutôt que recopiés,
        pour qu'un bloc corrigé le soit dans les quatre. L'ordre est celui d'avant
        la Slice 12 : écran d'abord, mains ensuite, ajout de l'utilisateur en dernier.
        """

        steps = [PromptStep("backend.claude.conversation.system", "cli.append_system_prompt")]
        if display:
            steps += [
                PromptStep("backend.claude.conversation.display", "cli.append_system_prompt", separator="\n"),
                # Sans séparateur : la ligne prolonge la liste « ÉCRAN ».
                PromptStep("backend.claude.conversation.scene_read", "cli.append_system_prompt"),
                PromptStep("backend.claude.conversation.artifacts", "cli.append_system_prompt", separator="\n"),
            ]
        if hands:
            steps.append(PromptStep("backend.claude.conversation.barehands", "cli.append_system_prompt", separator="\n"))
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
        backend_session("backend.claude.conversation.session", "conversation_session"),
        backend_session("backend.claude.conversation.display_session", "conversation_display_session",
                        display=True),
        backend_session("backend.claude.conversation.barehands_session", "conversation_barehands_session",
                        hands=True),
        backend_session("backend.claude.conversation.display_barehands_session",
                        "conversation_display_barehands_session", display=True, hands=True),
        PromptProgram("backend.claude.job_result.session",
                      PromptTarget("backend", None, "claude", None, None, "job_result_session"), (
                          PromptStep("backend.claude.job_result.system", "cli.append_system_prompt"),
                      )),
        PromptProgram("backend.claude.speculative.session",
                      PromptTarget("backend", None, "claude", None, None, "speculative_session"), (
                          PromptStep("backend.claude.speculative.system", "cli.system_prompt", PromptOperation.REPLACE),
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
    )
    return PromptRegistry(descriptors, programs, renderers={
        "voice.recent_context": _recent_context,
        "voice.initial_context": _initial_context,
        "realtime.reflex.response": _reflex,
        "front_brain.analysis.input": _front_brain_input,
        "backend.turn.brief": _backend_brief,
    })
