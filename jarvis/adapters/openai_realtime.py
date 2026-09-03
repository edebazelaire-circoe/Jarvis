from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator

import aiohttp

from jarvis.domain.v2 import ProtocolEnvelope


class OpenAIRealtimeSession:
    """OpenAI Realtime WebSocket adapter; provider JSON never enters Core contracts."""

    def __init__(self, ws: aiohttp.ClientWebSocketResponse, http: aiohttp.ClientSession, *, owns_http: bool) -> None:
        self.ws = ws
        self.http = http
        self.owns_http = owns_http

    @classmethod
    async def connect(
        cls,
        *,
        api_key: str,
        model: str,
        voice: str,
        context: dict[str, object],
        tools: list[dict[str, object]] | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> "OpenAIRealtimeSession":
        owns = session is None
        http = session or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None))
        try:
            ws = await http.ws_connect(
                f"wss://api.openai.com/v1/realtime?model={model}",
                headers={"Authorization": f"Bearer {api_key}"},
                heartbeat=20,
            )
            instance = cls(ws, http, owns_http=owns)
            instructions = (
                "You are Jarvis. Speak naturally and concisely. All actions must use the provided Core tools. "
                "Never claim an action succeeded before its tool result. If Core says confirmation is required, "
                "ask the user for an explicit yes/no and wait."
            )
            recent = context.get("recent_turns") or []
            if recent:
                instructions += "\nConversation context:\n" + "\n".join(
                    f"{item.get('kind')}: {item.get('content')}" for item in recent[-12:] if isinstance(item, dict)
                )
            await ws.send_json(
                {
                    "type": "session.update",
                    "session": {
                        "type": "realtime",
                        "instructions": instructions,
                        "output_modalities": ["audio"],
                        "audio": {
                            "input": {
                                "format": {"type": "audio/pcm", "rate": 24000},
                                "transcription": {"model": "gpt-4o-mini-transcribe"},
                                "turn_detection": {
                                    "type": "server_vad",
                                    "create_response": True,
                                    "interrupt_response": True,
                                },
                            },
                            "output": {
                                "format": {"type": "audio/pcm", "rate": 24000},
                                "voice": voice,
                            },
                        },
                        "tools": tools or [],
                        "tool_choice": "auto",
                    },
                }
            )
            return instance
        except Exception:
            if owns:
                await http.close()
            raise

    async def send_audio(self, pcm: bytes) -> None:
        await self.ws.send_json(
            {"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm).decode("ascii")}
        )

    async def send_tool_result(self, call_id: str, result: dict[str, object]) -> None:
        await self.ws.send_json(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(result, ensure_ascii=False),
                },
            }
        )
        await self.ws.send_json({"type": "response.create"})

    async def send_context(self, text: str) -> None:
        await self.ws.send_json(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                },
            }
        )
        await self.ws.send_json({"type": "response.create"})

    async def events(self) -> AsyncIterator[ProtocolEnvelope]:
        async for message in self.ws:
            if message.type != aiohttp.WSMsgType.TEXT:
                if message.type in {aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED}:
                    break
                continue
            data = message.json()
            kind = str(data.get("type") or "")
            if kind in {"response.audio.delta", "response.output_audio.delta"}:
                yield ProtocolEnvelope(message_type="realtime.audio", payload={"pcm_b64": data.get("delta", "")})
            elif kind in {
                "conversation.item.input_audio_transcription.completed",
                "input_audio_buffer.transcription.completed",
            }:
                yield ProtocolEnvelope(
                    message_type="realtime.transcript", payload={"text": data.get("transcript", "")}
                )
            elif kind in {"response.audio_transcript.done", "response.output_audio_transcript.done"}:
                yield ProtocolEnvelope(
                    message_type="realtime.assistant_transcript", payload={"text": data.get("transcript", "")}
                )
            elif kind in {"response.function_call_arguments.done", "response.output_item.done"}:
                item = data.get("item") if isinstance(data.get("item"), dict) else data
                if item.get("type") == "function_call" or kind == "response.function_call_arguments.done":
                    raw = item.get("arguments") or data.get("arguments") or "{}"
                    try:
                        arguments = json.loads(raw) if isinstance(raw, str) else dict(raw)
                    except Exception:
                        arguments = {}
                    yield ProtocolEnvelope(
                        message_type="realtime.tool_call",
                        payload={
                            "call_id": item.get("call_id") or data.get("call_id"),
                            "name": item.get("name") or data.get("name"),
                            "arguments": arguments,
                        },
                    )
            elif kind == "error":
                yield ProtocolEnvelope(message_type="realtime.error", payload={"error": data.get("error") or {}})

    async def close(self) -> None:
        if not self.ws.closed:
            await self.ws.close()
        if self.owns_http:
            await self.http.close()
