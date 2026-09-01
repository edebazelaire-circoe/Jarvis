from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jarvis.domain.actions import ActionKind, ActionRequest
from jarvis.domain.messages import ToolCall
from jarvis.domain.tools import ToolDefinition
from jarvis.domain.errors import ActionPolicyError
from jarvis.security.policy import V1_ACTION_POLICY, FORBIDDEN_TOOL_NAMES


@dataclass(frozen=True, slots=True)
class ToolSpec:
    definition: ToolDefinition
    kind: ActionKind


class ToolRegistry:
    """Closed V1 registry. Text from the model can choose a tool, never create one."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {
            "memory_search": ToolSpec(
                ToolDefinition(
                    name="memory_search",
                    description="Search the user's local Markdown memory for relevant facts.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "minLength": 1},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                ),
                ActionKind.MEMORY_SEARCH,
            ),
            "memory_append": ToolSpec(
                ToolDefinition(
                    name="memory_append",
                    description="Append a durable Markdown note to local memory. Requires user confirmation.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "minLength": 1, "maxLength": 160},
                            "body": {"type": "string", "minLength": 1, "maxLength": 12000},
                        },
                        "required": ["title", "body"],
                        "additionalProperties": False,
                    },
                ),
                ActionKind.MEMORY_APPEND,
            ),
            "board_present": ToolSpec(
                ToolDefinition(
                    name="board_present",
                    description="Present an ephemeral text card on the local Barehands board.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "minLength": 1, "maxLength": 160},
                            "body": {"type": "string", "minLength": 1, "maxLength": 6000},
                            "x": {"type": "number", "minimum": 0.08, "maximum": 0.92},
                            "y": {"type": "number", "minimum": 0.08, "maximum": 0.92},
                        },
                        "required": ["title", "body"],
                        "additionalProperties": False,
                    },
                ),
                ActionKind.BOARD_PRESENT,
            ),
        }
        if set(self._specs) & FORBIDDEN_TOOL_NAMES:
            raise RuntimeError("Forbidden tool accidentally registered")

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(spec.definition for spec in self._specs.values())

    def to_action(self, call: ToolCall) -> ActionRequest:
        spec = self._specs.get(call.name)
        if spec is None:
            raise ActionPolicyError(f"Outil non autorise: {call.name}")
        payload = self._validate(call.name, call.arguments)
        policy = V1_ACTION_POLICY[spec.kind]
        if spec.kind == ActionKind.MEMORY_SEARCH:
            summary = f"Rechercher dans la memoire: {payload['query']}"
        elif spec.kind == ActionKind.MEMORY_APPEND:
            preview = payload["body"].replace("\n", " ").strip()
            if len(preview) > 180:
                preview = preview[:177] + "..."
            summary = f"Memoriser la note '{payload['title']}': {preview}"
        else:
            summary = f"Afficher sur le board: {payload['title']}"
        return ActionRequest(
            kind=spec.kind,
            summary=summary,
            risk=policy.risk,
            payload=payload,
            requires_confirmation=policy.requires_confirmation,
        )

    def _validate(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(args, dict):
            raise ActionPolicyError(f"Arguments invalides pour {name}")
        if name == "memory_search":
            allowed = {"query", "limit"}
            self._reject_extra(name, args, allowed)
            query = args.get("query")
            limit = args.get("limit", 5)
            if not isinstance(query, str) or not query.strip():
                raise ActionPolicyError("memory_search.query invalide")
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 10:
                raise ActionPolicyError("memory_search.limit invalide")
            return {"query": query.strip(), "limit": limit}
        if name == "memory_append":
            allowed = {"title", "body"}
            self._reject_extra(name, args, allowed)
            title, body = args.get("title"), args.get("body")
            if not isinstance(title, str) or not title.strip() or len(title) > 160:
                raise ActionPolicyError("memory_append.title invalide")
            if not isinstance(body, str) or not body.strip() or len(body) > 12000:
                raise ActionPolicyError("memory_append.body invalide")
            return {"title": title.strip(), "body": body.strip()}
        if name == "board_present":
            allowed = {"title", "body", "x", "y"}
            self._reject_extra(name, args, allowed)
            title, body = args.get("title"), args.get("body")
            if not isinstance(title, str) or not title.strip() or len(title) > 160:
                raise ActionPolicyError("board_present.title invalide")
            if not isinstance(body, str) or not body.strip() or len(body) > 6000:
                raise ActionPolicyError("board_present.body invalide")
            clean: dict[str, Any] = {"title": title.strip(), "body": body.strip()}
            for key in ("x", "y"):
                if key in args:
                    value = args[key]
                    if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0.08 <= float(value) <= 0.92:
                        raise ActionPolicyError(f"board_present.{key} invalide")
                    clean[key] = float(value)
            return clean
        raise ActionPolicyError(f"Outil non autorise: {name}")

    @staticmethod
    def _reject_extra(name: str, args: dict[str, Any], allowed: set[str]) -> None:
        extra = set(args) - allowed
        if extra:
            raise ActionPolicyError(f"Arguments inattendus pour {name}: {sorted(extra)}")
