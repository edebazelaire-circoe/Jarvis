"""Duplex GPT-Live composition over the canonical VoiceFrontend port."""
from __future__ import annotations

import asyncio
import base64
from collections import OrderedDict, deque
import uuid

from jarvis.adapters.openai_live_frontend import OpenAILiveFrontend, aiohttp_live_connector
from jarvis.domain.live_prompt import LIVE_OPERATING_RULES
from jarvis.domain.prompt_registry import PromptTarget
from jarvis.domain.v2 import PlaybackCursor, ProtocolEnvelope, SpeechRequest
from jarvis.domain.voice_architecture import DuplexVoiceConfig, VoiceModelRef
from jarvis.domain.voice_events import (
    AssistantAudioChunk, AssistantPlaybackEvidence, AssistantTranscriptDelta,
    UserTranscriptDelta, VoiceDelegationRequested,
    VoiceFrontendFailed, VoicePlaybackStatus, VoiceUsageSource, VoiceUsageUpdated,
)
from jarvis.domain.voice_frontend import (
    FrontendState, VoiceAudioChunk, VoiceCorrelation, VoiceFrontendConfig,
    VoiceOperation, VoiceOperationResult, VoiceOperationStatus, VoicePcmFormat, VoiceStopReason,
    VoiceTextUpdate,
)
from jarvis.runtime.conversation_context import selected_voice_context
from jarvis.runtime.live_delegation import LiveDelegationController
from jarvis.runtime.live_primary_owner import DurableLiveSessionOwner
from jarvis.runtime.voice_observations import VoiceObservationDispatcher


MAX_REQUEST_UTF8 = 8192
MAX_REQUEST_DELTAS = 256
#: Silence de l'utilisateur (entre deux mots transcrits) au-delà duquel, si le
#: modèle a parlé entretemps, la demande précédente est close : il y a répondu
#: seul. En deçà, c'est une pause au milieu d'une phrase, que la demande garde.
REQUEST_STALE_GAP_S = 8.0
# MAX_APPEND_UTF8 vaut 500 côté adaptateur : on découpe sous cette borne pour
# qu'un résultat de cerveau, régulièrement plus long, reste prononçable.
MAX_APPEND_CHUNK_UTF8 = 450
MAX_APPEND_CHUNKS = 12
_BOUNDARIES = (".!?…", ";:", ",")
_WHITESPACE = " \n\t"

#: Crête (PCM16) en dessous de laquelle un bloc de sortie Live est du silence.
#: GPT-Live diffuse un bloc de 100 ms toutes les 100 ms pendant toute la
#: session, qu'il parle ou non (sonde du fournisseur réel, 21/09/2026) : au
#: repos ce sont des zéros exacts, les fins de fondu montent à 8, et les pauses
#: à l'intérieur d'une phrase gardent une crête de 34 ou plus. 16 laisse de la
#: marge des deux côtés.
SILENT_OUTPUT_PEAK = 16


def is_silent_pcm16(pcm: bytes, peak: int = SILENT_OUTPUT_PEAK) -> bool:
    """Vrai quand aucun échantillon PCM16 (little-endian) ne dépasse `peak`."""
    samples = memoryview(pcm)[:len(pcm) - len(pcm) % 2].cast("h")
    return not samples or (max(samples) <= peak and min(samples) >= -peak)


def _head(rest: str, limit: int) -> str:
    """Longest prefix under the byte bound, cut at the latest natural boundary."""
    head = rest.encode("utf-8")[:limit].decode("utf-8", "ignore")
    if len(head) == len(rest):
        return head
    for group in _BOUNDARIES:
        index = max((head.rfind(mark) for mark in group), default=-1)
        if index > 0:
            return head[:index + 1]
    index = max((head.rfind(mark) for mark in _WHITESPACE), default=-1)
    # index 0 ne progresserait pas : on coupe alors au milieu du jeton, ce qui
    # reste préférable à une boucle sans fin ou à un texte muet.
    return head[:index] if index > 0 else head


def append_segments(text: str, limit: int = MAX_APPEND_CHUNK_UTF8) -> list[str]:
    """Ordered speakable segments; one segment for anything already short."""
    segments: list[str] = []
    rest = text.strip()
    while rest and len(rest.encode("utf-8")) > limit:
        head = _head(rest, limit)
        chunk = head.strip()
        if chunk:
            segments.append(chunk)
        rest = rest[len(head):].lstrip()
    if rest:
        segments.append(rest)
    return segments


class LiveFrontendSession:
    """Migration facade for the existing device bridge; canonical Core remains primary."""

    canonical_history = True
    audio_observation_starts_output = True
    requires_local_quiescence_without_output_final = True

    def __init__(self, frontend: OpenAILiveFrontend, session_id: str, *, poll_interval_s: float = .05,
                 lifecycle_owner: DurableLiveSessionOwner | None = None, prompt_evidence=None,
                 brain_orchestration: bool = True) -> None:
        self.frontend, self.session_id = frontend, session_id
        self._poll_interval_s = poll_interval_s
        self.core = None
        self.conversation_id: str | None = None
        self._dispatcher: VoiceObservationDispatcher | None = None
        self._delegations: LiveDelegationController | None = None
        self._outputs: OrderedDict[str, VoiceCorrelation] = OrderedDict()
        self._declared_outputs: set[str] = set()
        self._played_ms: dict[str, int] = {}
        self._settled_outputs: set[str] = set()
        self._reading = False
        self._reader_ended = asyncio.Event()
        self._reader_ended.set()
        self._close_task: asyncio.Task | None = None
        self._closed = False
        self.stop_result = None
        self.journal = None
        self.input_observation_revision = 0
        self._playback_suppressed = False
        #: Position du flux au moment du verrou, et position au-delà de laquelle l'audio est celui d'une parole
        #: demandée APRÈS le verrou (accusé ordonné de son append) : voir `suppress_playback_until_session_end`.
        self._latch_sequence: int | None = None
        self._resume_after: int | None = None
        self._dropped_while_suppressed = 0
        self._request_deltas: deque[str] = deque()
        self._request_bytes = 0
        self._request_held = False
        self._request_last_input_ns: int | None = None
        self._request_model_spoke = False
        self._request_model_delta = ""
        self.request_stale_gap_s = REQUEST_STALE_GAP_S
        self._brain_orchestration = brain_orchestration
        self._lifecycle_owner = lifecycle_owner
        self.prompt_applications = [dict(prompt_evidence)] if isinstance(prompt_evidence, dict) else []

    @classmethod
    async def connect(cls, *, api_key: str, voice: str, context: dict[str, object],
                      architecture_config: DuplexVoiceConfig | None = None,
                      connector=None, poll_interval_s: float = .05,
                      start_timeout_s: float = 15.0, ack_timeout_s: float = 15.0,
                      close_timeout_s: float = 5.0, queue_limit: int = 256,
                      core=None, prompt_overrides=None, **_unused):
        mode = architecture_config or DuplexVoiceConfig(VoiceModelRef("openai", "gpt-live-1"))
        from jarvis.runtime.prompt_runtime import prompt_channel, prompt_evidence, resolve_prompt
        resolution = resolve_prompt(
            PromptTarget("conversation", "duplex", "openai", mode.conversation_model.model_id, "explicit", "session"),
            overrides=prompt_overrides,
            variables={"context": context},
        )
        session_id = str(uuid.uuid4())
        owner = DurableLiveSessionOwner(core, session_id) if core is not None else None
        frontend = OpenAILiveFrontend(
            connector or aiohttp_live_connector(api_key), voice=voice,
            start_timeout_s=start_timeout_s, ack_timeout_s=ack_timeout_s,
            close_timeout_s=close_timeout_s, queue_limit=queue_limit,
            lifecycle_hooks=owner,
        )
        session = cls(frontend, session_id, poll_interval_s=poll_interval_s,
                      lifecycle_owner=owner,
                      prompt_evidence=prompt_evidence(resolution, application="sent", channel="session.instructions"),
                      brain_orchestration=mode.brain_orchestration)
        if owner is not None:
            owner.set_fenced_callback(session._on_fenced)
        config = VoiceFrontendConfig(mode, initial_context=selected_voice_context(context),
                                     instructions=prompt_channel(resolution, "session.instructions"),
                                     input_format=VoicePcmFormat(24000))
        operation = session._operation()
        # No durable lease and no provider socket exist until the exact bounded
        # startup payload has passed validation.
        frontend.validate_start(config, operation)
        if owner is not None:
            await owner.reserve()
        try:
            result = await frontend.start(config, operation=operation)
            session._require(result)
            return session
        except BaseException as failure:
            # ``start`` is shielded by the adapter and can outlive this caller.
            # Keep a facade-owned cleanup task until that owner settles, then
            # stop the resulting incarnation and wait for transport cleanup.
            cleanup = asyncio.create_task(
                session._cleanup_failed_connect(config), name="jarvis-live-connect-cleanup",
            )
            cancelled = isinstance(failure, asyncio.CancelledError)
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    cancelled = True
                except BaseException:
                    break
            if not cleanup.cancelled():
                try:
                    cleanup.result()
                except BaseException:
                    pass
            if cancelled:
                raise asyncio.CancelledError from None
            raise

    async def _cleanup_failed_connect(self, config: VoiceFrontendConfig) -> None:
        # Latch stop before joining the shielded start owner. If it is blocked
        # in provider-ID binding, the bind may complete for recovery but its
        # following ACTIVE transition is fenced.
        if self._lifecycle_owner is not None:
            try:
                await self._lifecycle_owner.begin_stop(VoiceStopReason.CANCELLED.value)
            except BaseException:
                pass
        try:
            await self.frontend.start(config, operation=self._operation())
        except BaseException:
            pass
        try:
            await self.frontend.stop(VoiceStopReason.CANCELLED, operation=self._operation())
        except BaseException:
            pass
        if self._lifecycle_owner is not None and self.frontend.state is not FrontendState.STOPPED:
            try:
                await self._lifecycle_owner.mark_unknown("connect_cleanup_unconfirmed")
            except BaseException:
                pass
        try:
            await self.frontend.wait_transport_closed()
        except BaseException:
            pass
        if self._lifecycle_owner is not None:
            try:
                await self._lifecycle_owner.close()
            except BaseException:
                pass

    async def _on_fenced(self) -> None:
        # Do not call back into the heartbeat owner task. A separate stop owner
        # performs urgent provider close even though further CAS is fenced.
        if self._close_task is None:
            self._close_task = asyncio.create_task(
                self._close(VoiceStopReason.ERROR), name="jarvis-live-fenced-stop",
            )

    def operation_id(self) -> str:
        return str(uuid.uuid4())

    def _operation(self, correlation: VoiceCorrelation | None = None) -> VoiceOperation:
        return VoiceOperation(self.operation_id(), correlation or VoiceCorrelation(self.session_id))

    @staticmethod
    def _require(result) -> None:
        if result.status not in {VoiceOperationStatus.ACCEPTED, VoiceOperationStatus.COMPLETED}:
            raise RuntimeError(result.error.code.value if result.error else "voice_operation_failed")

    async def attach_core(self, core, conversation_id: str, *, on_failure=None, journal=None) -> None:
        self.core, self.conversation_id = core, conversation_id
        self.journal = journal
        self._dispatcher = VoiceObservationDispatcher(core, conversation_id, self.session_id,
                                                      on_failure=on_failure, journal=journal)
        await self._dispatcher.start()
        if journal is not None:
            for item in self.prompt_applications:
                journal.emit("voice.prompt", "Prompt application recorded", data=dict(item))
        self._delegations = LiveDelegationController(self, poll_interval_s=self._poll_interval_s,
                                                     brain_orchestration=self._brain_orchestration)

    def _note_request_delta(self, delta: str) -> None:
        """Rebuild the current spoken request from word-level input fragments.

        The Live API publishes no input final: the delegation is the de-facto
        end of the request, so the only text a delegation can carry is what the
        session accumulated. Bounded on both sides, oldest first.
        """
        if not delta:
            return
        self._request_deltas.append(delta)
        self._request_bytes += len(delta.encode("utf-8"))
        while len(self._request_deltas) > MAX_REQUEST_DELTAS or self._request_bytes > MAX_REQUEST_UTF8:
            self._request_bytes -= len(self._request_deltas.popleft().encode("utf-8"))

    def _continue_request(self, observed_ns: int) -> None:
        """Keep the request across model speech, unless the user moved on.

        Only a long silence on the user's side, with the model speaking in
        between, closes the previous request: the model then answered it alone.
        """
        last, self._request_last_input_ns = self._request_last_input_ns, observed_ns
        spoke, model_delta = self._request_model_spoke, self._request_model_delta
        self._request_model_spoke, self._request_model_delta = False, ""
        if not spoke or not self._request_deltas or self._request_held:
            return
        gap_s = (observed_ns - last) / 1e9 if last is not None else None
        expired = gap_s is not None and gap_s > self.request_stale_gap_s
        text = self.pending_request_text() or ""
        if expired:
            self._request_deltas.clear()
            self._request_bytes = 0
        self._trace_request("expired" if expired else "kept_over_model_speech", text, gap_s, model_delta)

    def _trace_request(self, decision: str, text: str, gap_s: float | None, model_delta: str) -> None:
        # Diagnostic des coupures de parole : ce que le modèle a dit pendant la
        # demande, la pause de l'utilisateur, et ce que la demande est devenue.
        if self.journal is None:
            return
        try:
            self.journal.emit("voice.live.request_boundary", "Live pending request crossed model speech", data={
                "session_id": self.session_id, "conversation_id": self.conversation_id,
                "decision": decision, "user_gap_s": None if gap_s is None else round(gap_s, 3),
                "stale_gap_s": self.request_stale_gap_s, "chars": len(text), "text": text[:2000],
                "model_delta": model_delta[:200],
            })
        except Exception:
            pass

    def hold_pending_request(self) -> None:
        """Keep the accumulated request while a delegation is being dispatched.

        The model answers "je m'en charge" within the same few milliseconds:
        without the hold, its own transcript would erase the request text that
        the delegation is about to carry.
        """
        self._request_held = True

    def reset_pending_request(self) -> None:
        self._request_deltas.clear()
        self._request_bytes = 0
        self._request_held = False
        self._request_model_spoke, self._request_model_delta = False, ""

    def pending_request_text(self) -> str | None:
        text = " ".join("".join(self._request_deltas).split())
        return text or None

    def take_pending_request(self) -> str | None:
        """Read and remove exactly the request a delegation carries.

        Words heard while the brain turn is being submitted belong to the next
        request: `reset_pending_request` after the submission erased them.
        """
        text = self.pending_request_text()
        self._request_deltas.clear()
        self._request_bytes = 0
        self._request_model_spoke, self._request_model_delta = False, ""
        return text

    def release_pending_request(self) -> None:
        self._request_held = False

    async def flush_observations(self) -> None:
        if self._dispatcher is None:
            raise RuntimeError("Live Core observation dispatcher is not attached")
        await self._dispatcher.flush()

    @property
    def active_output_id(self) -> str | None:
        return next(reversed(self._outputs), None) if self._outputs else None

    async def send_audio(self, pcm: bytes) -> None:
        if self._lifecycle_owner is not None:
            self._lifecycle_owner.assert_active()
        for offset in range(0, len(pcm), 48000):
            chunk = pcm[offset:offset + 48000]
            if chunk:
                self._require(await self.frontend.send_audio(VoiceAudioChunk(chunk), operation=self._operation()))

    async def finish_input(self) -> bool:
        return False

    async def send_tool_result(self, call_id: str, result: dict[str, object]) -> None:
        del call_id, result
        raise RuntimeError("voice_operation_unsupported")

    async def send_context(self, text: str) -> None:
        if self._lifecycle_owner is not None:
            self._lifecycle_owner.assert_active()
        await self._append_chunked("thinking", text, VoiceCorrelation(self.session_id))

    async def keepalive(self) -> None:
        return None

    async def speak_reserved(self, request: SpeechRequest, *, output_id: str) -> str:
        return await self.speak(request, output_id=output_id)

    async def speak(self, request: SpeechRequest, *, output_id: str | None = None) -> str:
        if self._lifecycle_owner is not None:
            self._lifecycle_owner.assert_active()
        correlation = VoiceCorrelation(self.session_id, speech_id=request.id, output_id=output_id,
                                       source_correlation_id=request.correlation_id, backend_work_id=request.work_id)
        if self._dispatcher is not None:
            await self._dispatcher.register_speech(correlation, request.text)
        await self._append_chunked("commentary", request.text, correlation)
        return output_id or str(uuid.uuid4())

    async def _append_chunked(self, channel: str, text: str, correlation: VoiceCorrelation) -> None:
        """Append one bounded segment at a time; the first one keeps the old contract.

        The provider refuses anything above MAX_APPEND_UTF8, so a whole brain
        answer used to be dropped without a word. Segments go out in order and
        stop as soon as the session can no longer speak: a half-said result is
        better than a wrong one, and what was dropped is traced, never silent.
        """
        method = (self.frontend.append_spoken_result if channel == "commentary"
                  else self.frontend.append_quiet_context)
        segments = append_segments(text)
        spoken = 0
        for index, chunk in enumerate(segments[:MAX_APPEND_CHUNKS]):
            if index and (self._closed or self.playback_suppressed):
                break
            operation = self._operation(correlation)
            result = await method(VoiceTextUpdate(chunk), operation=operation)
            if channel == "commentary":
                self.note_spoken_ack(operation.operation_id)
            if not index:
                self._require(result)
            elif result.status not in {VoiceOperationStatus.ACCEPTED, VoiceOperationStatus.COMPLETED}:
                break
            spoken = index + 1
        dropped = sum(len(chunk.encode("utf-8")) for chunk in segments[spoken:])
        if dropped and self.journal is not None:
            try:
                self.journal.emit("voice.live.speech_truncated", "Live append truncated", data={
                    "session_id": self.session_id, "conversation_id": self.conversation_id,
                    "channel": channel, "chunks": spoken, "segments": len(segments),
                    "dropped_bytes": dropped,
                })
            except Exception:
                pass

    async def cancel_output(self, cursor: PlaybackCursor | None = None) -> None:
        del cursor  # Device suppression happens first; Live has no exact native cancel.
        self.suppress_playback_until_session_end()

    @property
    def playback_suppressed(self) -> bool:
        return self._playback_suppressed

    def suppress_playback_until_session_end(self) -> None:
        """Couper l'audio de la réponse en cours, jusqu'à la prochaine parole demandée.

        Le fournisseur n'a aucun moyen d'annuler une réponse ni aucune frontière native entre l'ancienne et la
        nouvelle : son reste arrive après la coupure. Le verrou jette donc tout l'audio, la queue comprise. Il ne
        dure plus jusqu'à la fin de la session (la réponse du cerveau, demandée ensuite, restait alors muette pour
        tout le reste de la session) : l'accusé d'un append de parole envoyé après le verrou est une frontière
        ORDONNÉE du flux. Tout ce qui le précède est la queue de l'ancienne réponse, tout ce qui le suit est la
        nouvelle parole (`note_spoken_ack`, `_try_resume`). Ni une entrée, ni un transcript, ni un nouvel
        identifiant de sortie ne lèvent le verrou : un identifiant neuf peut encore être une queue.
        Le pont l'appelle de façon synchrone avant d'attendre l'arrêt du périphérique.
        """
        if not self._playback_suppressed:
            self._latch_sequence = getattr(self.frontend, "last_sequence", None)
            self._resume_after = None
            self._dropped_while_suppressed = 0
            self._trace_playback("voice.live.playback_suppressed", "Live playback fenced by an interruption", {
                "latch_sequence": self._latch_sequence})
        self._playback_suppressed = True

    def note_spoken_ack(self, operation_id: object) -> None:
        """L'accusé de l'append de parole `operation_id` est arrivé : lire son rang dans le flux, une seule fois."""
        reader = getattr(self.frontend, "ack_boundary", None)
        boundary = reader(operation_id) if callable(reader) else None
        if boundary is None or not self._playback_suppressed:
            return
        if self._latch_sequence is not None and boundary <= self._latch_sequence:
            return  # Accusé traité avant le verrou : ce qui le suit peut encore être la queue coupée.
        self._resume_after = boundary if self._resume_after is None else max(self._resume_after, boundary)

    def _try_resume(self, event) -> bool:
        """Lever le verrou à la première trame audio postérieure à l'accusé d'une parole demandée après lui."""
        if self._resume_after is None or event.sequence <= self._resume_after:
            return False
        self._playback_suppressed = False
        dropped, self._dropped_while_suppressed = self._dropped_while_suppressed, 0
        self._resume_after = self._latch_sequence = None
        self._trace_playback("voice.live.playback_resumed", "Live playback resumed after a spoken-result boundary", {
            "dropped_chunks": dropped})
        return True

    def _trace_playback(self, kind: str, message: str, data: dict[str, object]) -> None:
        if self.journal is None:
            return
        try:
            self.journal.emit(kind, message, data={"session_id": self.session_id,
                                                   "conversation_id": self.conversation_id, **data})
        except Exception:
            pass

    async def truncate(self, cursor: PlaybackCursor) -> None:
        del cursor  # No alignment primitive exists for Live.

    async def invalidate_unstarted_output(self, output_id: str) -> None:
        del output_id

    def set_back_brain_presenter(self, presenter) -> None:
        del presenter  # Live commentary append is the result presentation path.

    def observe_playback(self, payload: dict, *, played_ms: int | None,
                         written_ms: int | None, terminal: bool = False) -> None:
        if self._dispatcher is None:
            return
        key = str(payload.get("output_id"))
        correlation = self._outputs.get(key)
        if correlation is None:
            return
        if played_ms is not None and played_ms > 0:
            status = VoicePlaybackStatus.UNKNOWN if terminal else VoicePlaybackStatus.PARTIAL
        elif written_ms == 0:
            status, played_ms = VoicePlaybackStatus.UNPLAYED, 0
        else:
            status = VoicePlaybackStatus.UNKNOWN
        if played_ms is not None:
            self._played_ms[key] = max(played_ms, self._played_ms.get(key, 0))
        if terminal:
            self._settled_outputs.add(key)
        self._dispatcher.local(AssistantPlaybackEvidence(status, played_ms, confirmed_text=None), correlation)

    def _settle_previous_outputs(self) -> None:
        """Live emits no response final, so Core would keep every speech GENERATING.

        A new output id only appears after an observed input/output alternation:
        earlier outputs can no longer grow. Settle them as UNKNOWN (no delivery
        claim) at the last lower bound already sent, which is not a regression.
        """
        if self._dispatcher is None:
            return
        for key, correlation in self._outputs.items():
            if key in self._settled_outputs:
                continue
            self._settled_outputs.add(key)
            self._dispatcher.local(AssistantPlaybackEvidence(
                VoicePlaybackStatus.UNKNOWN, self._played_ms.get(key), confirmed_text=None), correlation)

    def _observe(self, event) -> None:
        if isinstance(event.payload, UserTranscriptDelta):
            self.input_observation_revision += 1
            self._continue_request(event.observation.monotonic_ns)
            self._note_request_delta(event.payload.delta)
        elif isinstance(event.payload, AssistantTranscriptDelta) and not self._request_held and self._request_deltas:
            # Le modèle a parlé pendant la demande. Ce n'est pas une fin de
            # demande : un « mm » ou une relance pendant une pause de
            # l'utilisateur effaçait ici le début de sa phrase, que le cerveau
            # ne recevait jamais. On décide à la reprise de l'utilisateur.
            if not self._request_model_spoke:
                self._request_model_spoke = True
                self._request_model_delta = event.payload.delta
        if event.correlation.output_id:
            key = str(event.correlation.output_id)
            if key not in self._outputs:
                self._settle_previous_outputs()
            self._outputs[key] = event.correlation
            while len(self._outputs) > 128:
                expired, _ = self._outputs.popitem(last=False)
                self._declared_outputs.discard(expired)
                self._played_ms.pop(expired, None)
                self._settled_outputs.discard(expired)
        if isinstance(event.payload, VoiceUsageUpdated) and self.journal is not None:
            try:
                self.journal.emit("voice.live.usage", "Live session usage updated", data={
                    "session_id": self.session_id,
                    "seconds": event.payload.duration_s,
                    "source": event.payload.source.value,
                    "usage_type": (
                        "final" if event.payload.source is VoiceUsageSource.PROVIDER_FINAL else "cumulative"
                    ),
                })
            except Exception:
                pass
        if self._dispatcher is not None:
            self._dispatcher.observe(event)
        if isinstance(event.payload, VoiceDelegationRequested) and self._delegations is not None:
            self._delegations.offer(event)

    def _legacy_events(self, event):
        payload, correlation = event.payload, event.correlation
        output_id = str(correlation.output_id) if correlation.output_id else None
        common = {"output_id": output_id, "response_id": None, "item_id": None,
                  "speech_id": correlation.speech_id}
        if isinstance(payload, AssistantAudioChunk):
            if self.playback_suppressed and not self._try_resume(event):
                self._dropped_while_suppressed += 1
                return  # Canonical received evidence remains, never playback.
            if is_silent_pcm16(payload.audio.pcm):
                # Le silence que GPT-Live diffuse entre deux paroles n'est pas
                # une parole. Remis au bridge, chaque bloc rallumait « JARVIS
                # parle » et la file de lecture ne se vidait jamais : l'orbe
                # restait orange du réveil à la fin de la session, et la fin de
                # parole (quiescence locale) ne pouvait pas survenir. L'audio
                # reçu reste observé ci-dessus (`_observe`) ; il n'est
                # simplement ni joué ni annoncé. Le haut-parleur ne perd rien :
                # sans bloc à jouer il se tait, ce que ces zéros disaient.
                return
            if output_id not in self._declared_outputs:
                self._declared_outputs.add(output_id)
                yield ProtocolEnvelope(message_type="realtime.output_started", payload=common)
            yield ProtocolEnvelope(message_type="realtime.audio", payload={**common,
                "pcm_b64": base64.b64encode(payload.audio.pcm).decode("ascii")})
        elif isinstance(payload, AssistantTranscriptDelta):
            yield ProtocolEnvelope(message_type="realtime.assistant_transcript_delta",
                                   payload={**common, "text": payload.delta})
        elif isinstance(payload, UserTranscriptDelta):
            yield ProtocolEnvelope(message_type="realtime.transcript_delta",
                                   payload={"text": payload.delta, "item_id": None})
        elif isinstance(payload, VoiceDelegationRequested):
            # Le fournisseur confie un vrai travail au client : le cerveau s'y
            # met. C'est le seul signal de finalité exploitable du fil Live, et
            # donc la seule chose qui puisse annoncer la réflexion à l'écran.
            # Le vocabulaire legacy porte ce fait par `realtime.transcript` et
            # `realtime.input_committed`, qu'un fil Live n'émet jamais : sans
            # cette traduction, l'orbe ne passe jamais au violet en duplex.
            yield ProtocolEnvelope(message_type="realtime.brain_pending",
                                   payload={**common, "pending": True})
        elif isinstance(payload, VoiceFrontendFailed):
            yield ProtocolEnvelope(message_type="realtime.error", payload={"error": {
                "code": payload.error.code.value, "message": payload.error.safe_message or payload.error.code.value}})

    async def events(self):
        self._reading = True
        self._reader_ended.clear()
        try:
            async for event in self.frontend.events():
                self._observe(event)
                for converted in self._legacy_events(event):
                    yield converted
        finally:
            self._reading = False
            self._reader_ended.set()

    async def stop(self, reason: VoiceStopReason = VoiceStopReason.USER) -> VoiceOperationResult:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(reason), name="jarvis-live-session-close")
        return await asyncio.shield(self._close_task)

    async def close(self, reason: VoiceStopReason = VoiceStopReason.USER) -> VoiceOperationResult:
        return await self.stop(reason)

    async def _close(self, reason: VoiceStopReason) -> VoiceOperationResult:
        if self._closed:
            return self.stop_result
        if self._delegations is not None:
            await self._delegations.close()
        if self._lifecycle_owner is not None:
            persistence = self._lifecycle_owner.request_stop(reason.value)
            try:
                await asyncio.wait_for(asyncio.shield(persistence), timeout=.05)
            except BaseException:
                # The owned Core mutation continues. Storage latency/failure
                # never suppresses the urgent provider close.
                pass
        self.stop_result = await self.frontend.stop(reason, operation=self._operation())
        if (self._lifecycle_owner is not None
                and self.stop_result.status is not VoiceOperationStatus.COMPLETED):
            uncertain = self._lifecycle_owner.request_unknown(
                f"{reason.value}_close_unconfirmed",
            )
            try:
                await asyncio.wait_for(asyncio.shield(uncertain), timeout=.05)
            except BaseException:
                pass
        if self._reading:
            try:
                await asyncio.wait_for(self._reader_ended.wait(), 2)
            except TimeoutError:
                pass
        if not self._reading:
            # Bridge cancellation may release the subscription before stop.
            # Drain canonical lifecycle/failure evidence without playing audio.
            async for event in self.frontend.events():
                self._observe(event)
        if self._dispatcher is not None:
            await self._dispatcher.close()
        if self._lifecycle_owner is not None:
            await self._lifecycle_owner.close()
        self._closed = True
        return self.stop_result
