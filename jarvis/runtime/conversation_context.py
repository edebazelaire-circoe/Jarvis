"""Bounded history projection used by conversation initialization and analysis."""
from jarvis.domain.voice_frontend import VoiceContext, VoiceContextMessage, VoiceContextRole


def selected_voice_context(context: dict) -> VoiceContext:
    selected, size = [], 0
    for item in reversed(context.get("recent_turns", [])[-8:]):
        if not isinstance(item, dict) or item.get("kind") not in ("user", "assistant"):
            continue
        if item.get("kind") == "assistant" and "voice_ledger" not in context:
            continue  # Legacy partial intended text is not confirmed heard context.
        text = item.get("content")
        if not isinstance(text, str) or len(text) > 8192 or size + len(text) > 8192:
            continue
        selected.append(VoiceContextMessage(VoiceContextRole(item["kind"]), text))
        size += len(text)
    selected = list(reversed(selected))
    task_context = context.get("switch_task_context")
    if isinstance(task_context, str) and 0 < len(task_context) <= 4096:
        selected.append(VoiceContextMessage(VoiceContextRole.DEVELOPER, task_context))
    return VoiceContext(messages=tuple(selected))
