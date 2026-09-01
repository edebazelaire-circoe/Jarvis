from __future__ import annotations

import base64
import json
import time
from typing import Any
import httpx

from jarvis.domain.errors import ProviderError
from jarvis.domain.messages import ToolCall, UserTurn
from jarvis.domain.results import AgentResult
from jarvis.domain.tools import ToolCatalog
from .openai_http import OpenAIHTTP


_SYSTEM_INSTRUCTIONS = """You are Jarvis, a local personal assistant prototype.
Reply in the user's language, optimized for speech: concise, direct, natural sentences.
You have exactly three local tools: memory_search, memory_append, board_present.
Use memory_search for remembered/personal facts when useful. Use board_present when the user asks to show/display something.
Use memory_append only when the user explicitly asks to remember/save a fact. The runtime will ask for confirmation before writing.
Never claim to have executed a tool until its tool output confirms success. Never invent or request shell/system tools.
Prefer at most one tool call per response unless multiple read-only memory searches are truly necessary.
"""


class OpenAIAgentBackend:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_s: float = 45.0,
        client: httpx.AsyncClient | None = None,
        instructions: str = _SYSTEM_INSTRUCTIONS,
    ) -> None:
        self.model = model
        self.instructions = instructions
        self.http = OpenAIHTTP(api_key=api_key, base_url=base_url, timeout_s=timeout_s, client=client)

    async def respond(self, turn: UserTurn, tools: ToolCatalog) -> AgentResult:
        started = time.perf_counter()
        if turn.continuation_token:
            history = self._decode_continuation(turn.continuation_token)
            input_items = list(history)
            input_items.extend(
                {
                    "type": "function_call_output",
                    "call_id": output.call_id,
                    "output": json.dumps(
                        {"ok": not output.is_error, "result": output.output},
                        ensure_ascii=False,
                        default=str,
                    ),
                }
                for output in turn.tool_outputs
            )
        else:
            input_items = [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": turn.text}],
                }
            ]

        provider_tools = [
            {
                "type": "function",
                "name": definition.name,
                "description": definition.description,
                "parameters": definition.parameters,
                # Core validation is authoritative; false avoids provider-side
                # schema-version brittleness for optional fields in V1.
                "strict": False,
            }
            for definition in tools.definitions()
        ]
        payload: dict[str, Any] = {
            "model": self.model,
            "instructions": self.instructions,
            "input": input_items,
            "tools": provider_tools,
            "tool_choice": "auto",
            "store": False,
            # Stateless Responses tool loops with reasoning models need the
            # encrypted reasoning item returned so it can be replayed with
            # the function_call_output on the next request.
            "include": ["reasoning.encrypted_content"],
        }
        response = await self.http.post_json("/responses", payload, operation="agent")
        try:
            data = response.json()
            output_items = data.get("output") or []
            if not isinstance(output_items, list):
                raise TypeError("output is not a list")
        except Exception as exc:
            raise ProviderError("openai", "agent", "Invalid Responses API payload") from exc

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        invalid_args = 0
        for item in output_items:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "message":
                for content in item.get("content") or []:
                    if isinstance(content, dict) and content.get("type") == "output_text":
                        value = content.get("text")
                        if isinstance(value, str):
                            text_parts.append(value)
            elif item.get("type") == "function_call":
                name = str(item.get("name") or "").strip()
                call_id = str(item.get("call_id") or item.get("id") or "").strip()
                if not name or not call_id:
                    raise ProviderError(
                        "openai",
                        "agent",
                        "Malformed Responses API function call",
                    )
                raw_args = item.get("arguments", "{}")
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    if not isinstance(args, dict):
                        raise TypeError
                except (json.JSONDecodeError, TypeError):
                    args = {}
                    invalid_args += 1
                tool_calls.append(ToolCall(call_id=call_id, name=name, arguments=args))

        continuation = None
        if tool_calls:
            continuation = self._encode_continuation(input_items + output_items)
        duration_ms = int((time.perf_counter() - started) * 1000)
        usage = data.get("usage") if isinstance(data, dict) else None
        diagnostics: dict[str, Any] = {
            "http_status": response.status_code,
            "tool_call_count": len(tool_calls),
            "invalid_tool_argument_count": invalid_args,
        }
        if isinstance(usage, dict):
            diagnostics.update({
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "total_tokens": usage.get("total_tokens"),
            })
        return AgentResult(
            text="\n".join(part.strip() for part in text_parts if part.strip()).strip(),
            tool_calls=tuple(tool_calls),
            provider="openai",
            model=self.model,
            duration_ms=duration_ms,
            continuation_token=continuation,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _encode_continuation(history: list[Any]) -> str:
        raw = json.dumps(history, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii")

    @staticmethod
    def _decode_continuation(token: str) -> list[Any]:
        try:
            raw = base64.urlsafe_b64decode(token.encode("ascii"))
            value = json.loads(raw)
            if not isinstance(value, list):
                raise TypeError
            return value
        except Exception as exc:
            raise ProviderError("openai", "agent", "Invalid continuation state") from exc
