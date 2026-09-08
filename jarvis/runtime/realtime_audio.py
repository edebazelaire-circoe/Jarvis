from __future__ import annotations

import asyncio
import base64
import json
import threading
from collections.abc import Callable

from jarvis.domain.v2 import AddressingDecision
from jarvis.ports.v2 import RealtimeSession
from jarvis.protocol.client import LocalCoreClient
from jarvis.runtime.journal import RuntimeJournal


# Cet outil ne va pas à Core : il est intercepté et transmis à l'agent Claude.
CLAUDE_TOOL = "claude_task"


class ConservativeAddressingClassifier:
    FOLLOWUPS = ("oui", "non", "yes", "no", "ok", "d'accord", "et ", "mais ", "alors ", "continue", "pourquoi", "comment", "quand", "où", "qui", "quoi")

    def classify(self, text: str, *, active: bool) -> AddressingDecision:
        normalized = " ".join(text.casefold().strip().split())
        if not normalized:
            return AddressingDecision.AMBIENT
        if normalized.startswith("jarvis"):
            return AddressingDecision.ADDRESSED
        if not active:
            return AddressingDecision.AMBIENT
        if normalized.endswith("?") or normalized.startswith(self.FOLLOWUPS) or len(normalized.split()) <= 8:
            return AddressingDecision.ADDRESSED
        return AddressingDecision.UNCERTAIN


class SoundDeviceRealtimeAudio:
    """24 kHz mono PCM bridge. Raw audio is memory-only and never persisted.

    Toute la difficulté est la fermeture. `asyncio.to_thread` n'interrompt pas
    le thread qu'il a lancé : annuler la tâche du bridge (F9 pendant que JARVIS
    parle) rend la main immédiatement alors que PortAudio écrit toujours dans le
    flux. Fermer celui-ci à cet instant libère la mémoire sous les pieds de
    PortAudio — c'est une violation d'accès (0xC0000005) qui tue le processus
    sans qu'aucun `except` ne puisse s'exécuter. Le verrou ci-dessous est donc
    la seule chose qui garantit qu'aucun thread n'est dans PortAudio au moment
    où le flux est libéré.
    """

    # La lecture est découpée pour que la fermeture n'attende jamais plus d'un
    # bloc : l'interruption reste réactive sans jamais couper une écriture.
    OUTPUT_CHUNK_FRAMES = 2400  # 100 ms à 24 kHz
    _BYTES_PER_FRAME = 2  # int16 mono

    def __init__(self, *, input_device: int | str | None = None, output_device: int | str | None = None, sample_rate: int = 24000) -> None:
        self.input_device = input_device
        self.output_device = output_device
        self.sample_rate = sample_rate
        self.captured_bytes = 0
        self.sent_bytes = 0
        self._input = None
        self._output = None
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=64)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._output_lock = threading.Lock()
        self._closing = False

    async def start(self) -> None:
        try:
            import sounddevice as sd  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Realtime audio requires sounddevice") from exc
        self._loop = asyncio.get_running_loop()

        def callback(indata, frames, time_info, status) -> None:  # noqa: ANN001
            del frames, time_info, status
            loop = self._loop
            if loop is None or self._closing:
                return
            try:
                loop.call_soon_threadsafe(self._enqueue, bytes(indata))
            except RuntimeError:
                # La boucle se ferme : les derniers blocs n'ont plus de
                # destinataire, et lever ici ferait tomber le flux PortAudio.
                pass

        def open_streams():
            input_stream = sd.RawInputStream(samplerate=self.sample_rate, channels=1, dtype="int16", device=self.input_device, blocksize=1200, callback=callback)
            try:
                output_stream = sd.RawOutputStream(samplerate=self.sample_rate, channels=1, dtype="int16", device=self.output_device)
                input_stream.start(); output_stream.start()
            except Exception:
                self._shutdown_stream(input_stream, abort=True)
                raise
            return input_stream, output_stream

        try:
            # L'ouverture PortAudio coûte plusieurs centaines de millisecondes :
            # la laisser sur la boucle gèle le clavier et les signaux visuels.
            self._input, self._output = await asyncio.to_thread(open_streams)
        except Exception as exc:
            await self.close()
            raise RuntimeError(f"Impossible d'ouvrir les périphériques audio Voice: {type(exc).__name__}") from exc

    def _enqueue(self, raw: bytes) -> None:
        self.captured_bytes += len(raw)
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self._queue.put_nowait(raw)

    async def pump_input(self, session: RealtimeSession) -> None:
        while True:
            raw = await self._queue.get()
            if raw is None:
                return
            await session.send_audio(raw)
            self.sent_bytes += len(raw)

    async def stop_input(self) -> None:
        stream, self._input = self._input, None
        if stream is not None:
            # Volontairement synchrone : stop() attend la fin des callbacks en
            # vol, et rester sur la boucle garantit que tout ce qu'ils y ont
            # planifié est déjà en file avant le marqueur ci-dessous. Le passer
            # dans un thread ferait perdre les derniers blocs capturés.
            self._shutdown_stream(stream, abort=False)
        # PortAudio has stopped, but its final thread callbacks may still be
        # scheduled on this loop. Enqueue them before the end-of-input marker.
        await asyncio.sleep(0)
        await self._queue.put(None)

    async def play_b64(self, value: str) -> None:
        if not value:
            return
        await asyncio.to_thread(self._write_output, base64.b64decode(value))

    def _write_output(self, pcm: bytes) -> None:
        """Écrire la réponse par blocs, verrou tenu.

        Ce thread survit à l'annulation de la tâche qui l'a lancé : le verrou
        est ce qui empêche `close()` de libérer le flux pendant qu'il écrit.
        """
        step = self.OUTPUT_CHUNK_FRAMES * self._BYTES_PER_FRAME
        for offset in range(0, len(pcm), step):
            with self._output_lock:
                stream = self._output
                if stream is None or self._closing:
                    return
                stream.write(pcm[offset:offset + step])

    async def close(self) -> None:
        # Signalé avant de prendre le verrou : une lecture en cours s'arrête au
        # prochain bloc au lieu de faire attendre la fermeture jusqu'au bout.
        self._closing = True
        input_stream, self._input = self._input, None
        output_stream, self._output = self._output, None
        if input_stream is None and output_stream is None:
            return
        await asyncio.to_thread(self._shutdown, input_stream, output_stream)

    def _shutdown(self, input_stream, output_stream) -> None:  # noqa: ANN001
        if input_stream is not None:
            self._shutdown_stream(input_stream, abort=False)
        if output_stream is not None:
            # abort() coupe la lecture en cours au lieu de vider le tampon, ce
            # qu'on veut pour une interruption ; le verrou garantit qu'aucun
            # thread n'est alors à l'intérieur de PortAudio.
            with self._output_lock:
                self._shutdown_stream(output_stream, abort=True)

    @staticmethod
    def _shutdown_stream(stream, abort: bool) -> None:  # noqa: ANN001
        try:
            stream.abort() if abort else stream.stop()
            stream.close()
        except Exception:
            # Audio-device teardown is best effort; session shutdown still proceeds.
            pass


class RealtimeConversationBridge:
    # Nettement sous le délai d'activité utile le plus court accepté (5 s),
    # pour qu'une tâche longue ne puisse jamais être prise pour un silence.
    CLAUDE_KEEPALIVE_S = 3.0

    def __init__(
        self,
        *,
        core: LocalCoreClient,
        session: RealtimeSession,
        conversation_id: str,
        audio: SoundDeviceRealtimeAudio,
        on_addressed: Callable[[], object],
        on_mute: Callable[[], object],
        on_listening: Callable[[], object] | None = None,
        on_thinking: Callable[[], object] | None = None,
        on_speaking: Callable[[], object] | None = None,
        on_response_done: Callable[[], object] | None = None,
        auto_turn: bool = False,
        classifier: ConservativeAddressingClassifier | None = None,
        journal: RuntimeJournal | None = None,
        claude=None,
    ) -> None:
        self.core = core
        self.session = session
        self.conversation_id = conversation_id
        self.audio = audio
        self.on_addressed = on_addressed
        self.on_mute = on_mute
        self.on_listening = on_listening
        self.on_thinking = on_thinking
        self.on_speaking = on_speaking
        self.on_response_done = on_response_done
        self.auto_turn = auto_turn
        self.classifier = classifier or ConservativeAddressingClassifier()
        self.journal = journal
        # Passerelle vers l'agent Claude local. Absente, l'outil `claude_task`
        # répond une indisponibilité prononçable au lieu d'échouer le tour.
        self.claude = claude
        self._pending_action_id: str | None = None
        self._input_task: asyncio.Task[None] | None = None
        self._input_submitted = False
        self._response_had_audio = False

    async def _call(self, callback: Callable[[], object] | None) -> None:
        if callback is None:
            return
        value = callback()
        if hasattr(value, "__await__"):
            await value

    def _trace(self, kind: str, message: str, *, level: str = "info", data: dict[str, object] | None = None) -> None:
        if self.journal is not None:
            self.journal.emit(kind, message, level=level, data=data)

    async def _call_claude(self, arguments: dict[str, object]) -> dict[str, object]:
        """Router la demande vers Claude, qui est l'agent capable d'agir sur le PC.

        Une panne de Claude ne doit pas casser le tour vocal : elle revient sous
        forme de texte que JARVIS peut prononcer.
        """
        request = str(arguments.get("request") or "").strip()
        if self.claude is None:
            return {"ok": False, "spoken": "L'agent Claude n'est pas configuré sur cette installation.", "code": "claude_not_configured"}
        await self._call(self.on_thinking)
        # Une tâche Claude de plusieurs minutes n'est pas de l'inactivité : sans
        # ce battement, le délai d'activité utile coupe la session vocale avant
        # que le résultat n'ait un endroit où revenir.
        keepalive = asyncio.create_task(self._keep_session_active(), name="jarvis-claude-keepalive")
        try:
            result = await self.claude.ask(request)
        finally:
            keepalive.cancel()
            await asyncio.gather(keepalive, return_exceptions=True)
        self._trace(
            "claude.answer" if result.get("ok") else "claude.failed",
            str(result.get("spoken") or "")[:300],
            level="info" if result.get("ok") else "error",
            data={"code": result.get("code"), "duration_ms": result.get("duration_ms"), "request": request},
        )
        return result

    async def _keep_session_active(self) -> None:
        while True:
            await asyncio.sleep(self.CLAUDE_KEEPALIVE_S)
            await self._call(self.on_addressed)
            keepalive = getattr(self.session, "keepalive", None)
            if keepalive is None:
                continue
            try:
                await keepalive()
            except Exception:
                # La connexion est déjà perdue : le tour se terminera proprement
                # à la sortie de l'outil, inutile de bruiter ici.
                return

    async def _close_input(self) -> None:
        """Stop capturing and drain the pump so no block is lost or sent late."""
        await self.audio.stop_input()
        input_task, self._input_task = self._input_task, None
        if input_task is not None:
            await input_task

    async def submit_input(self) -> bool:
        if self._input_submitted:
            return False
        if self._input_task is None:
            self._trace(
                "voice.input_skipped",
                "Microphone input is not ready for submission",
                level="warning",
                data={"conversation_id": self.conversation_id, "code": "audio_input_not_ready"},
            )
            return False
        self._input_submitted = True
        self._trace(
            "voice.input_submit_requested",
            "Manual input submission requested",
            data={"conversation_id": self.conversation_id},
        )
        await self._call(self.on_thinking)
        await self._close_input()
        metrics = {
            "conversation_id": self.conversation_id,
            "input_device": self.audio.input_device,
            "captured_bytes": self.audio.captured_bytes,
            "sent_bytes": self.audio.sent_bytes,
            "sent_duration_ms": round(self.audio.sent_bytes * 1000 / (self.audio.sample_rate * 2), 1),
        }
        if not await self.session.finish_input():
            self._trace(
                "voice.input_skipped",
                "Recorded input is too short to submit",
                level="warning",
                data={**metrics, "code": "audio_input_too_short"},
            )
            return False
        self._trace(
            "voice.input_submitted",
            "Manual input commit and response request sent",
            data=metrics,
        )
        return True

    async def _consume(self, events) -> None:  # noqa: ANN001
        """Traiter le flux du fournisseur.

        Une connexion perdue est une fin de vie normale, pas une panne : le
        websocket Realtime peut être fermé pendant qu'un outil lent travaille.
        Laisser l'exception remonter tuait tout le processus Voice alors que le
        tour venait de réussir.
        """
        try:
            async for event in events:
                if event.message_type == "realtime.audio":
                    self._response_had_audio = True
                    await self._call(self.on_speaking)
                    await self.audio.play_b64(str(event.payload.get("pcm_b64") or ""))
                elif event.message_type == "realtime.audio_done":
                    if self.on_response_done is None:
                        await self._call(self.on_listening)
                elif event.message_type == "realtime.response_done":
                    response_had_audio, self._response_had_audio = self._response_had_audio, False
                    if self._input_submitted and response_had_audio:
                        await self._call(self.on_response_done)
                elif event.message_type == "realtime.speech_started":
                    if self.auto_turn and not self._input_submitted:
                        self._trace(
                            "voice.speech_started",
                            "Speech detected by server VAD",
                            data={"conversation_id": self.conversation_id},
                        )
                elif event.message_type == "realtime.input_committed":
                    if self.auto_turn and not self._input_submitted:
                        self._input_submitted = True
                        # The provider already holds the turn; releasing the microphone
                        # here keeps the speakers from feeding the next VAD segment.
                        await self._close_input()
                        self._trace(
                            "voice.input_submitted",
                            "Server VAD closed the turn and requested a response",
                            data={
                                "conversation_id": self.conversation_id,
                                "input_device": self.audio.input_device,
                                "captured_bytes": self.audio.captured_bytes,
                                "sent_bytes": self.audio.sent_bytes,
                                "sent_duration_ms": round(
                                    self.audio.sent_bytes * 1000 / (self.audio.sample_rate * 2), 1
                                ),
                            },
                        )
                        await self._call(self.on_thinking)
                elif event.message_type == "realtime.transcript":
                    text = str(event.payload.get("text") or "").strip()
                    decision = self.classifier.classify(text, active=True)
                    self._trace("voice.transcript", text or "<empty>", data={"addressing": decision.value})
                    if decision is not AddressingDecision.ADDRESSED:
                        continue
                    normalized = " ".join(text.casefold().replace(",", " ").split())
                    if normalized == "jarvis mute":
                        await self._call(self.on_mute)
                        break
                    await self.core.append_turn(self.conversation_id, kind="user", content=text)
                    await self._call(self.on_thinking)
                    if self._pending_action_id is not None and normalized in {"oui", "non", "yes", "no"}:
                        result = await self.core.confirm_action(self._pending_action_id, text)
                        if result.get("disposition") != "confirm":
                            self._pending_action_id = None
                        await self.session.send_context("Jarvis Core confirmation result: " + str(result))
                    await self._call(self.on_addressed)
                elif event.message_type == "realtime.assistant_transcript":
                    text = str(event.payload.get("text") or "").strip()
                    if text:
                        self._trace("voice.assistant", text)
                        await self.core.append_turn(self.conversation_id, kind="assistant", content=text)
                        await self._call(self.on_addressed)
                elif event.message_type == "realtime.tool_call":
                    call_id = str(event.payload.get("call_id") or "")
                    name = str(event.payload.get("name") or "")
                    arguments = event.payload.get("arguments") if isinstance(event.payload.get("arguments"), dict) else {}
                    self._trace("tool.call", name, data={"call_id": call_id, "arguments": arguments})
                    if name == CLAUDE_TOOL:
                        result = await self._call_claude(arguments)
                    else:
                        result = await self.core.call_tool(name, arguments, conversation_id=self.conversation_id)
                    self._trace("tool.result", name, data={"call_id": call_id, "result": result})
                    action_id = result.get("action_id")
                    self._pending_action_id = str(action_id) if result.get("disposition") == "confirm" and action_id else None
                    await self.session.send_tool_result(call_id, result)
                elif event.message_type == "realtime.error":
                    error = event.payload.get("error") or {}
                    if isinstance(error, dict):
                        code = str(error.get("code") or "unknown_error")
                        message = str(error.get("message") or error)
                    else:
                        code = "unknown_error"
                        message = str(error)
                    self._trace("provider.error", message, level="error", data={"code": code})
                    raise RuntimeError(f"Realtime provider error [{code}]: {message}")
        except ConnectionError as exc:
            self._trace(
                "provider.disconnected",
                f"Connexion Realtime perdue: {exc}",
                level="warning",
                data={"code": "realtime_disconnected", "conversation_id": self.conversation_id},
            )

    async def run(self) -> None:
        await self.audio.start()
        self._trace(
            "audio.start",
            "Realtime microphone and speaker opened",
            data={"input_device": self.audio.input_device, "output_device": self.audio.output_device},
        )
        self._input_task = asyncio.create_task(self.audio.pump_input(self.session), name="jarvis-realtime-mic")
        try:
            await self._call(self.on_listening)
            await self._consume(self.session.events())
        finally:
            input_task, self._input_task = self._input_task, None
            if input_task is not None:
                input_task.cancel()
                await asyncio.gather(input_task, return_exceptions=True)
            await self.audio.close()
            self._trace("audio.stop", "Realtime microphone and speaker closed")
