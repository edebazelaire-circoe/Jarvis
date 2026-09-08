from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator

import aiohttp

from jarvis.domain.v2 import ProtocolEnvelope


JARVIS_PERSONA = (
    "Tu es JARVIS, l'assistant personnel de l'utilisateur, dans l'esprit de l'IA d'Iron Man. "
    "Ton timbre est grave, posé et assuré; ta diction est nette et sans emphase. "
    "Tu es courtois et sobre, avec une pointe d'humour pince-sans-rire très discrète. "
    "Vouvoie l'utilisateur et appelle-le « Monsieur » avec parcimonie, jamais à chaque phrase. "
    "Réponds dans la langue de l'utilisateur, en français par défaut. "
    "Sois bref : une à trois phrases, sauf demande explicite de détail. "
    "Ne joue pas la comédie et n'ajoute pas de didascalies."
)

OPERATING_RULES = (
    "Tu es la voix d'un agent local, Claude, qui exécute les actions sur cet ordinateur. "
    "Tu ne réponds jamais de toi-même à une demande portant sur cette machine, ce projet, "
    "le code, les fichiers, les applications ou une commande à exécuter : tu appelles "
    "l'outil claude_task en lui transmettant la demande au plus près des mots de l'utilisateur. "
    "Avant de l'appeler, dis une phrase courte pour signaler que tu t'en occupes, car la "
    "réponse peut prendre du temps. Quand le résultat arrive, restitue-le à voix haute de "
    "façon fidèle et concise, sans lire de code, de chemins ni de mise en forme. "
    "Si le résultat indique un échec, dis-le simplement sans inventer de succès. "
    "Les rappels et l'agenda passent par les outils Core dédiés, pas par claude_task. "
    "N'annonce jamais qu'une action a réussi avant d'avoir reçu son résultat d'outil. "
    "Si Core demande une confirmation, pose une question fermée oui/non et attends la réponse."
)

# Server-side voice activity detection: the turn ends on silence and the
# response starts on its own, so the wake key never has to be pressed twice.
SERVER_VAD = {
    "type": "server_vad",
    "threshold": 0.55,
    "prefix_padding_ms": 300,
    "silence_duration_ms": 800,
    "create_response": True,
    "interrupt_response": True,
}


class OpenAIRealtimeSession:
    """OpenAI Realtime WebSocket adapter; provider JSON never enters Core contracts."""

    # The configured input is 24 kHz, mono PCM16; commits require 100 ms.
    MIN_INPUT_BYTES = 24000 * 2 // 10

    def __init__(self, ws: aiohttp.ClientWebSocketResponse, http: aiohttp.ClientSession, *, owns_http: bool) -> None:
        self.ws = ws
        self.http = http
        self.owns_http = owns_http
        self._pending_audio_bytes = 0

    @classmethod
    async def connect(
        cls,
        *,
        api_key: str,
        model: str,
        voice: str,
        context: dict[str, object],
        tools: list[dict[str, object]] | None = None,
        auto_turn: bool = True,
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
            instructions = JARVIS_PERSONA + " " + OPERATING_RULES
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
                                "turn_detection": dict(SERVER_VAD) if auto_turn else None,
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
        if not pcm:
            return
        await self.ws.send_json(
            {"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm).decode("ascii")}
        )
        self._pending_audio_bytes += len(pcm)

    async def finish_input(self) -> bool:
        if self._pending_audio_bytes < self.MIN_INPUT_BYTES:
            return False
        await self.ws.send_json({"type": "input_audio_buffer.commit"})
        self._pending_audio_bytes = 0
        await self.ws.send_json({"type": "response.create"})
        return True

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

    async def keepalive(self) -> None:
        """Ping le websocket pendant qu'un outil lent travaille.

        Après le commit du micro, plus rien n'est écrit sur la connexion : une
        tâche Claude d'une minute la laisse silencieuse assez longtemps pour
        qu'elle soit fermée, et le résultat n'a alors plus où revenir.
        """
        await self.ws.ping()

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
            elif kind in {"response.audio.done", "response.output_audio.done"}:
                yield ProtocolEnvelope(message_type="realtime.audio_done", payload={})
            elif kind == "response.done":
                response = data.get("response") if isinstance(data.get("response"), dict) else {}
                yield ProtocolEnvelope(
                    message_type="realtime.response_done",
                    payload={"status": response.get("status")},
                )
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
            elif kind == "input_audio_buffer.speech_started":
                yield ProtocolEnvelope(message_type="realtime.speech_started", payload={})
            elif kind == "input_audio_buffer.speech_stopped":
                yield ProtocolEnvelope(message_type="realtime.speech_stopped", payload={})
            elif kind == "input_audio_buffer.committed":
                yield ProtocolEnvelope(
                    message_type="realtime.input_committed",
                    payload={"item_id": data.get("item_id")},
                )
            elif kind == "error":
                yield ProtocolEnvelope(message_type="realtime.error", payload={"error": data.get("error") or {}})

    async def close(self) -> None:
        if not self.ws.closed:
            await self.ws.close()
        if self.owns_http:
            await self.http.close()
