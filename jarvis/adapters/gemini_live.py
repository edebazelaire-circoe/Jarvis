"""Adaptateur Gemini Live (API BidiGenerateContent de Google).

Il implémente le même port `RealtimeSession` que l'adaptateur OpenAI et émet
les mêmes enveloppes `realtime.*`. Le pont de conversation ne sait donc pas
quel fournisseur parle — c'est ce qui rend le choix de la pile vocale possible
sans toucher à la boucle.

Deux différences de protocole méritent d'être connues :

* Google veut du PCM 16 kHz en entrée et rend du 24 kHz en sortie, là où OpenAI
  travaille en 24 kHz des deux côtés. `SoundDeviceRealtimeAudio` ouvre donc
  deux flux de fréquences différentes.
* Les transcriptions arrivent en fragments pendant que la phrase se construit.
  Le pont attend une phrase entière par tour (il la range dans l'historique et
  s'en sert pour décider si JARVIS est concerné) : les fragments sont donc
  accumulés ici et publiés une seule fois, à la fin du tour.
"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator
import json
from typing import Any

import aiohttp

from jarvis.adapters.openai_realtime import JARVIS_PERSONA, OPERATING_RULES
from jarvis.domain.v2 import ProtocolEnvelope

LIVE_ENDPOINT = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)

INPUT_SAMPLE_RATE = 16000
OUTPUT_SAMPLE_RATE = 24000
INPUT_MIME = f"audio/pcm;rate={INPUT_SAMPLE_RATE}"


def _tools_payload(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Traduire les outils du format Realtime OpenAI vers celui de Gemini.

    Les deux décrivent la même chose (nom, description, schéma JSON) mais
    OpenAI les met à plat et Google les regroupe sous `functionDeclarations`.
    """
    declarations: list[dict[str, Any]] = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name") or "")
        if not name:
            continue
        declaration: dict[str, Any] = {"name": name, "description": str(tool.get("description") or "")}
        parameters = tool.get("parameters")
        if isinstance(parameters, dict) and parameters.get("properties"):
            declaration["parameters"] = parameters
        declarations.append(declaration)
    return [{"functionDeclarations": declarations}] if declarations else []


class GeminiLiveSession:
    """Adaptateur Gemini Live ; le JSON du fournisseur ne sort jamais d'ici."""

    MIN_INPUT_BYTES = INPUT_SAMPLE_RATE * 2 // 10  # 100 ms de PCM16 mono

    def __init__(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        http: aiohttp.ClientSession,
        *,
        owns_http: bool,
        auto_turn: bool,
    ) -> None:
        self.ws = ws
        self.http = http
        self.owns_http = owns_http
        self.auto_turn = auto_turn
        self._pending_audio_bytes = 0
        self._activity_open = False
        self._input_text: list[str] = []
        self._output_text: list[str] = []
        self._turn_taken = False
        self._speech_signalled = False

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
        input_transcription: bool = True,
        output_transcription: bool = True,
        start_sensitivity: str = "LOW",
        end_sensitivity: str = "LOW",
        prefix_padding_ms: int = 300,
        silence_duration_ms: int = 1500,
        session: aiohttp.ClientSession | None = None,
    ) -> "GeminiLiveSession":
        owns = session is None
        http = session or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None))
        try:
            ws = await http.ws_connect(f"{LIVE_ENDPOINT}?key={api_key}", heartbeat=20)
            instance = cls(ws, http, owns_http=owns, auto_turn=auto_turn)

            instructions = JARVIS_PERSONA + " " + OPERATING_RULES
            recent = context.get("recent_turns") or []
            if recent:
                instructions += "\nConversation context:\n" + "\n".join(
                    f"{item.get('kind')}: {item.get('content')}" for item in recent[-12:] if isinstance(item, dict)
                )

            if auto_turn:
                detection: dict[str, Any] = {
                    "disabled": False,
                    "startOfSpeechSensitivity": f"START_SENSITIVITY_{start_sensitivity}",
                    "endOfSpeechSensitivity": f"END_SENSITIVITY_{end_sensitivity}",
                    "prefixPaddingMs": int(prefix_padding_ms),
                    "silenceDurationMs": int(silence_duration_ms),
                }
            else:
                # En mode manuel c'est la touche de réveil qui clôt le tour :
                # laisser la détection automatique active enverrait la réponse
                # avant l'appui, et les deux se contrediraient.
                detection = {"disabled": True}

            setup: dict[str, Any] = {
                "model": model if model.startswith("models/") else f"models/{model}",
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
                },
                "systemInstruction": {"parts": [{"text": instructions}]},
                "realtimeInputConfig": {"automaticActivityDetection": detection},
            }
            declarations = _tools_payload(list(tools or []))
            if declarations:
                setup["tools"] = declarations
            if input_transcription:
                setup["inputAudioTranscription"] = {}
            if output_transcription:
                setup["outputAudioTranscription"] = {}

            await ws.send_json({"setup": setup})
            return instance
        except Exception:
            if owns:
                await http.close()
            raise

    # ------------------------------------------------------------------ envoi

    async def send_audio(self, pcm: bytes) -> None:
        if not pcm:
            return
        if not self.auto_turn and not self._activity_open:
            # Détection automatique désactivée : Google exige un marqueur de
            # début d'activité, sinon l'audio est reçu mais jamais attribué.
            await self.ws.send_json({"realtimeInput": {"activityStart": {}}})
            self._activity_open = True
        await self.ws.send_json(
            {
                "realtimeInput": {
                    "audio": {"data": base64.b64encode(pcm).decode("ascii"), "mimeType": INPUT_MIME}
                }
            }
        )
        self._pending_audio_bytes += len(pcm)

    async def finish_input(self) -> bool:
        if self._pending_audio_bytes < self.MIN_INPUT_BYTES:
            return False
        if self._activity_open:
            await self.ws.send_json({"realtimeInput": {"activityEnd": {}}})
            self._activity_open = False
        else:
            await self.ws.send_json({"realtimeInput": {"audioStreamEnd": True}})
        self._pending_audio_bytes = 0
        return True

    async def send_tool_result(self, call_id: str, result: dict[str, object]) -> None:
        await self.ws.send_json(
            {
                "toolResponse": {
                    "functionResponses": [
                        {"id": call_id, "response": {"result": result}},
                    ]
                }
            }
        )

    async def keepalive(self) -> None:
        """Tenir la connexion pendant qu'un outil lent travaille.

        Après la fin du tour plus rien n'est écrit : une tâche Claude d'une
        minute laisserait le websocket silencieux assez longtemps pour être
        fermé, et le résultat n'aurait plus où revenir.
        """
        await self.ws.ping()

    async def send_context(self, text: str) -> None:
        await self.ws.send_json(
            {
                "clientContent": {
                    "turns": [{"role": "user", "parts": [{"text": text}]}],
                    "turnComplete": True,
                }
            }
        )

    # -------------------------------------------------------------- réception

    async def events(self) -> AsyncIterator[ProtocolEnvelope]:
        async for message in self.ws:
            if message.type == aiohttp.WSMsgType.BINARY:
                try:
                    data = json.loads(message.data.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
            elif message.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(message.data)
                except json.JSONDecodeError:
                    continue
            else:
                if message.type in {aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED}:
                    break
                continue
            if not isinstance(data, dict):
                continue
            for envelope in self._translate(data):
                yield envelope

    def _translate(self, data: dict[str, Any]) -> list[ProtocolEnvelope]:
        out: list[ProtocolEnvelope] = []

        if "setupComplete" in data:
            return out

        tool_call = data.get("toolCall")
        if isinstance(tool_call, dict):
            for call in tool_call.get("functionCalls") or []:
                if not isinstance(call, dict):
                    continue
                arguments = call.get("args")
                out.append(
                    ProtocolEnvelope(
                        message_type="realtime.tool_call",
                        payload={
                            "call_id": str(call.get("id") or call.get("name") or ""),
                            "name": str(call.get("name") or ""),
                            "arguments": arguments if isinstance(arguments, dict) else {},
                        },
                    )
                )

        server = data.get("serverContent")
        if isinstance(server, dict):
            out.extend(self._translate_server_content(server))

        go_away = data.get("goAway")
        if isinstance(go_away, dict):
            out.append(
                ProtocolEnvelope(
                    message_type="realtime.error",
                    payload={
                        "error": {
                            "code": "gemini_go_away",
                            "message": f"Google va fermer la session (temps restant : {go_away.get('timeLeft')}).",
                        }
                    },
                )
            )

        error = data.get("error")
        if isinstance(error, dict):
            out.append(
                ProtocolEnvelope(
                    message_type="realtime.error",
                    payload={
                        "error": {
                            "code": str(error.get("status") or error.get("code") or "gemini_error"),
                            "message": str(error.get("message") or error),
                        }
                    },
                )
            )
        return out

    def _translate_server_content(self, server: dict[str, Any]) -> list[ProtocolEnvelope]:
        out: list[ProtocolEnvelope] = []

        transcription = server.get("inputTranscription")
        if isinstance(transcription, dict) and transcription.get("text"):
            self._input_text.append(str(transcription["text"]))
            if not self._speech_signalled:
                self._speech_signalled = True
                out.append(ProtocolEnvelope(message_type="realtime.speech_started", payload={}))

        output_transcription = server.get("outputTranscription")
        if isinstance(output_transcription, dict) and output_transcription.get("text"):
            self._output_text.append(str(output_transcription["text"]))

        model_turn = server.get("modelTurn")
        audio_parts: list[str] = []
        if isinstance(model_turn, dict):
            for part in model_turn.get("parts") or []:
                if not isinstance(part, dict):
                    continue
                inline = part.get("inlineData")
                if isinstance(inline, dict) and inline.get("data"):
                    audio_parts.append(str(inline["data"]))
                elif part.get("text"):
                    self._output_text.append(str(part["text"]))

        # Le premier signe que le modèle a pris la main est aussi le seul signal
        # fiable que Google donne de la clôture du tour utilisateur : l'API Live
        # n'émet pas d'équivalent de `input_audio_buffer.committed`.
        model_started = bool(audio_parts) or bool(output_transcription) or bool(server.get("generationComplete"))
        if model_started and not self._turn_taken:
            self._turn_taken = True
            out.append(ProtocolEnvelope(message_type="realtime.input_committed", payload={}))
            out.extend(self._flush_input_transcript())

        for chunk in audio_parts:
            out.append(ProtocolEnvelope(message_type="realtime.audio", payload={"pcm_b64": chunk}))

        if server.get("interrupted"):
            out.append(ProtocolEnvelope(message_type="realtime.audio_done", payload={}))

        if server.get("turnComplete"):
            # Une réponse purement textuelle (rare, mais possible sur erreur de
            # configuration) n'a jamais déclenché le commit : ne pas laisser le
            # pont attendre indéfiniment un tour qui est déjà fini.
            if not self._turn_taken:
                self._turn_taken = True
                out.append(ProtocolEnvelope(message_type="realtime.input_committed", payload={}))
                out.extend(self._flush_input_transcript())
            out.extend(self._flush_output_transcript())
            out.append(ProtocolEnvelope(message_type="realtime.audio_done", payload={}))
            out.append(
                ProtocolEnvelope(message_type="realtime.response_done", payload={"status": "completed"})
            )
            self._turn_taken = False
            self._speech_signalled = False
        return out

    def _flush_input_transcript(self) -> list[ProtocolEnvelope]:
        text = "".join(self._input_text).strip()
        self._input_text.clear()
        if not text:
            return []
        return [ProtocolEnvelope(message_type="realtime.transcript", payload={"text": text})]

    def _flush_output_transcript(self) -> list[ProtocolEnvelope]:
        text = "".join(self._output_text).strip()
        self._output_text.clear()
        if not text:
            return []
        return [ProtocolEnvelope(message_type="realtime.assistant_transcript", payload={"text": text})]

    async def close(self) -> None:
        if not self.ws.closed:
            await self.ws.close()
        if self.owns_http:
            await self.http.close()
