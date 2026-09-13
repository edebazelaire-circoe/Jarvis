"""Core-owned canonical voice ingress and the sole confirmed-history projection."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
import hashlib

from jarvis.core.v2_services import ConversationService
from jarvis.core.voice_state import VoiceConversationState
from jarvis.domain.v2 import utc_now
from jarvis.domain.voice_event_codec import decode_voice_correlation, decode_voice_event
from jarvis.domain.voice_events import VoicePlaybackStatus
from jarvis.domain.voice_frontend import FrontendState
from jarvis.domain.voice_state import VoiceSpeechRecord, VoiceSpeechState, VoiceTurnOrder, state_id
from jarvis.domain.voice_admission import VoiceTurnAdmissionRequest
from jarvis.ports.v2 import DiagnosticSink


@dataclass(slots=True)
class _ConversationLedger:
    state: VoiceConversationState
    projected: dict[str, int] = field(default_factory=dict)


class VoiceLedgerService:
    """One reducer per conversation, owned by JarvisCoreApplication.

    Never accepts client snapshots, copies user history, or dispatches work.
    A ledger transaction lock spans projection and registry eviction, preventing
    overlapping prefixes or eviction races. Awaited storage does not block Core
    jobs/brain execution, which have separate ownership.
    """

    def __init__(self, conversations: ConversationService, *, diagnostics: DiagnosticSink | None = None, max_conversations: int = 128) -> None:
        if type(max_conversations) is not int or not 1 <= max_conversations <= 128:
            raise ValueError("invalid voice ledger conversation limit")
        self._conversations = conversations
        self._diagnostics = diagnostics
        self._max_conversations = max_conversations
        self._ledgers: dict[str, _ConversationLedger] = {}
        self._lock = asyncio.Lock()
        self.diagnostic_failures = 0

    async def has_ledger(self, conversation_id: str) -> bool:
        return conversation_id in self._ledgers or await self._conversations.state.get_voice_snapshot(conversation_id) is not None

    async def _known_conversation(self, conversation_id: str) -> None:
        state_id(conversation_id, "conversation_id")
        if await self._conversations.state.get_conversation(conversation_id) is None:
            raise KeyError("unknown conversation")

    async def _ledger(self, conversation_id: str, *, create: bool = False) -> _ConversationLedger | None:
        """Called only within the ledger transaction lock."""
        ledger = self._ledgers.get(conversation_id)
        if ledger is not None:
            return ledger
        stored = await self._conversations.state.get_voice_snapshot(conversation_id)
        if stored is None and not create:
            return None
        if len(self._ledgers) >= self._max_conversations:
            evictable = next(((key, value) for key, value in self._ledgers.items()
                              if value.state.snapshot.lifecycle == FrontendState.STOPPED
                              and not value.state.active_tasks
                              and not any(s.active for s in value.state.snapshot.speeches)), None)
            if evictable is None:
                raise ValueError("voice ledger active conversation capacity reached")
            key, value = evictable
            # Failure leaves the live ledger untouched and propagates; no false
            # successful eviction or loss of heard/task evidence is possible.
            await self._conversations.state.save_voice_snapshot(value.state.snapshot)
            del self._ledgers[key]
        state = VoiceConversationState.from_snapshot(stored, diagnostics=self._diagnostics) if stored else VoiceConversationState(conversation_id, diagnostics=self._diagnostics)
        ledger = _ConversationLedger(state)
        self._ledgers[conversation_id] = ledger
        return ledger

    @staticmethod
    def _response(conversation_id: str, ledger: _ConversationLedger, **values) -> dict:
        return {"conversation_id": conversation_id, "session_id": ledger.state.snapshot.current_session_id,
                "revision": ledger.state.snapshot.revision, **values}

    async def bind_session(self, conversation_id: str, session_id: str) -> dict:
        await self._known_conversation(conversation_id)
        state_id(session_id, "session_id")
        async with self._lock:
            ledger = await self._ledger(conversation_id, create=True)
            result = ledger.state.bind_session(session_id)
            return self._response(conversation_id, ledger, result=asdict(result))

    async def ingest(self, conversation_id: str, session_id: str, payloads: object) -> dict:
        await self._known_conversation(conversation_id)
        state_id(session_id, "session_id")
        if not isinstance(payloads, list) or not 1 <= len(payloads) <= 32:
            raise ValueError("voice observation batch must contain 1 to 32 events")
        # Validate the whole transport batch before applying any observation.
        observations = [decode_voice_event(payload) for payload in payloads]
        if any(event.correlation.session_id != session_id for event in observations):
            raise ValueError("voice observation session does not match batch")
        async with self._lock:
            ledger = await self._ledger(conversation_id)
            if ledger is None:
                raise ValueError("voice session must be bound before observations")
            results = [asdict(ledger.state.apply(event)) for event in observations]
            updates = await self._project(conversation_id, ledger)
            if ledger.state.snapshot.lifecycle == FrontendState.STOPPED:
                await self._conversations.state.save_voice_snapshot(ledger.state.snapshot)
            return self._response(conversation_id, ledger, results=results, history_updates=updates)

    async def register_speech(self, conversation_id: str, correlation: object, intended_text: object) -> dict:
        await self._known_conversation(conversation_id)
        decoded = decode_voice_correlation(correlation)
        if not isinstance(intended_text, str) or len(intended_text) > 8192:
            raise ValueError("intended speech must be bounded text")
        async with self._lock:
            ledger = await self._ledger(conversation_id)
            if ledger is None:
                raise ValueError("voice session must be bound before speech registration")
            result = ledger.state.queue_speech(decoded, intended_text)
            return self._response(conversation_id, ledger, result=asdict(result))

    async def snapshot(self, conversation_id: str, *, checkpoint: bool = False) -> dict:
        await self._known_conversation(conversation_id)
        async with self._lock:
            ledger = await self._ledger(conversation_id)
            if checkpoint and ledger is not None:
                await self._conversations.state.save_voice_snapshot(ledger.state.snapshot)
            return {"conversation_id": conversation_id, "snapshot": ledger.state.snapshot.to_dict() if ledger else None}

    async def checkpoint_admitted_input(self, request: VoiceTurnAdmissionRequest) -> VoiceTurnOrder:
        """Validate server-owned canonical evidence and checkpoint before admission.

        No client snapshot is accepted. A crash after this checkpoint but before
        USER/source persistence leaves evidence that the same request can retry.
        The ledger lock prevents an older checkpoint overwriting newer evidence.
        """
        if not isinstance(request, VoiceTurnAdmissionRequest):
            raise ValueError("voice admission requires a typed request")
        await self._known_conversation(request.conversation_id)
        async with self._lock:
            ledger = await self._ledger(request.conversation_id)
            if ledger is None or ledger.state.snapshot.current_session_id != request.session_id:
                raise ValueError("voice admission session has no current canonical evidence")
            record = next((item for item in ledger.state.snapshot.users
                           if item.correlation.session_id == request.session_id
                           and item.correlation.turn_id == request.canonical_turn_id
                           and item.transcript_id == request.transcript_id), None)
            if (record is None or not record.committed or record.revision != request.transcript_revision
                    or record.text != request.text or record.correlation.provider_input_id != request.provider_item_id):
                raise ValueError("voice admission does not match committed canonical input")
            order = next((turn for turn in ledger.state.snapshot.turns
                          if turn.session_id == request.session_id and turn.turn_id == request.canonical_turn_id), None)
            if order is None:
                raise ValueError("voice admission has no canonical turn order")
            await self._conversations.state.save_voice_snapshot(ledger.state.snapshot)
            return order

    async def context(self, conversation_id: str) -> dict | None:
        """Keep the legacy context untouched until a canonical ledger is bound."""
        await self._known_conversation(conversation_id)
        async with self._lock:
            ledger = await self._ledger(conversation_id)
            if ledger is None:
                return None
            snapshot = ledger.state.snapshot
            context = ledger.state.recent_context()
            return {
                "conversation_id": conversation_id, "summary": "",
                "recent_turns": [{"kind": message.role.value, "content": message.text, "created_at": None} for message in context.messages],
                "voice_ledger": {"session_id": snapshot.current_session_id, "revision": snapshot.revision},
            }

    async def back_brain_projection(self, conversation_id: str, *, binding=None, session_id=None) -> dict:
        """Capture server evidence under the same observation barrier, not client context."""
        from jarvis.domain.voice_admission import admission_correlation_id, canonical_input_matches
        await self._known_conversation(conversation_id)
        async with self._lock:
            ledger = await self._ledger(conversation_id)
            if ledger is None:
                raise ValueError("canonical source projection unavailable")
            snapshot = ledger.state.snapshot
            if binding is not None and not canonical_input_matches(snapshot, binding):
                raise ValueError("canonical source projection does not match admission")
            if session_id is not None and snapshot.current_session_id != session_id:
                raise ValueError("advisory session is not current")
            # Persist exactly the server snapshot used to construct provenance.
            await self._conversations.state.save_voice_snapshot(snapshot)
            from jarvis.domain.back_brain import BackBrainContextDependency
            turns = await self._conversations.state.list_turns(conversation_id, limit=16)
            lines, dependencies, used = [], [], 0
            for turn in reversed(turns):
                if binding is not None and turn.correlation_id == admission_correlation_id(binding):
                    continue
                try:
                    dependency = BackBrainContextDependency.from_turn(turn)
                except ValueError:
                    continue  # Only immutable admitted USER or confirmed heard ranges enter context.
                line = f"{turn.kind.value}: {turn.content}"
                if used + len(line) + 1 > 8192:
                    continue
                lines.append(line)
                dependencies.append(dependency)
                used += len(line) + 1
            context = "\n".join(reversed(lines))
            inputs = [{"session_id": item.correlation.session_id, "transcript_id": item.transcript_id,
                             "revision": item.revision, "provider_item_id": item.correlation.provider_input_id,
                             "committed": item.committed, "text": item.text} for item in snapshot.users[-8:]]
            complete = all(any(d["session_id"] == item.correlation.session_id and d["transcript_id"] == item.transcript_id for d in inputs)
                           for item in snapshot.users if item.correlation.session_id == snapshot.current_session_id and not item.committed)
            return {"revision": snapshot.revision, "context_text": context, "context_dependencies": tuple(reversed(dependencies)),
                    "dependencies": inputs, "dependencies_complete": complete}

    @staticmethod
    def _output_key(conversation_id: str, speech: VoiceSpeechRecord) -> str:
        correlation = speech.correlation
        # Prefer app speech identity, stable before provider output identity is
        # learned. Autonomous outputs use the separate local output identity.
        identity = correlation.speech_id or correlation.output_id or correlation.provider_output_id
        raw = "\0".join((conversation_id, correlation.session_id, identity))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def _project(self, conversation_id: str, ledger: _ConversationLedger) -> int:
        updates = 0
        retained = set()
        for speech in sorted(ledger.state.snapshot.speeches, key=lambda s: s.first_played_order or 0):
            key = self._output_key(conversation_id, speech)
            retained.add(key)
            if not speech.confirmed_text or not speech.played_ms:
                continue
            start = ledger.projected.get(key, 0)
            end = len(speech.confirmed_text)
            if start >= end:
                ledger.projected[key] = start
                continue
            correlation = speech.correlation
            metadata = {
                "voice_evidence": True, "output_key": key,
                "session_id": correlation.session_id, "speech_id": correlation.speech_id,
                "output_id": correlation.output_id, "provider_output_id": correlation.provider_output_id,
                "turn_id": correlation.turn_id, "task_id": correlation.task_id,
                "source_correlation_id": correlation.source_correlation_id,
                "backend_work_id": correlation.backend_work_id,
                "played_ms": speech.played_ms,
                "first_played_order": speech.first_played_order,
                "delivery": "complete" if speech.playback_status == VoicePlaybackStatus.COMPLETE and speech.state == VoiceSpeechState.COMPLETE else "partial",
                "speech_state": speech.state.value, "playback_status": speech.playback_status.value,
            }
            try:
                offset, completed = await self._conversations.project_confirmed_voice_text(
                    conversation_id, key, speech.confirmed_text,
                    correlation_id=correlation.source_correlation_id or correlation.turn_id or correlation.speech_id or correlation.output_id or correlation.provider_output_id,
                    reference_id=correlation.speech_id or correlation.output_id or correlation.provider_output_id,
                    metadata=metadata, created_at=utc_now(),
                )
            except Exception:
                # Durable failure must remain retryable. Do not advance cursor;
                # retry uses the same range ID through existing idempotent stores.
                self._diagnose("voice.ledger.projection_failed", "error",
                               {"code": "voice_history_projection_failed", "conversation_id": conversation_id,
                                "session_id": correlation.session_id, "speech_id": correlation.speech_id})
                raise
            ledger.projected[key] = offset
            updates += completed
            self._diagnose("voice.ledger.projected", "info", {
                    "conversation_id": conversation_id, "session_id": correlation.session_id,
                    "speech_id": correlation.speech_id, "confirmed_start": start, "confirmed_end": end,
                    "delivery": metadata["delivery"],
                })
        # The indexed durable cursor can recover evicted cursors; this cache stays at
        # the reducer's bounded speech retention size.
        ledger.projected = {key: value for key, value in ledger.projected.items() if key in retained}
        return updates

    def _diagnose(self, kind: str, level: str, data: dict) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, "Canonical voice history projection", level=level, data=data)
        except Exception:
            # A broken diagnostic sink cannot invalidate a durable range or
            # hide the original storage exception. The host can inspect count.
            self.diagnostic_failures += 1
