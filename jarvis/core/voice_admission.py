"""Durable input admission shared by direct conversation and backend ingress.

The checkpoint, history and source stores are separate recovery steps, not a
cross-service transaction. Stable identities make each step safe to retry.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Callable
import asyncio

from jarvis.core.brain_outcomes import BrainOutcomeService, stable_identity
from jarvis.core.conversation_event_emitter import PRODUCER_VOICE_ADMISSION, NullConversationEventEmitter
from jarvis.core.v2_services import ConversationService, CoreEventBus
from jarvis.core.voice_ledger import VoiceLedgerService
from jarvis.domain.conversation_events import ConversationEventType
from jarvis.domain.speech_presentation import SpeechSource
from jarvis.domain.voice_state import VoiceTurnOrder
from jarvis.domain.v2 import AddressingDecision, BrainTurnInput, BrainTurnSource, ConversationTurn, ProtocolEnvelope, TurnKind
from jarvis.domain.voice_admission import (
    BRAIN_SOURCE_CHANGED, VOICE_TURN_ADMITTED, VoiceTurnAdmissionAcceptance, VoiceTurnAdmissionRequest,
    admission_correlation_id,
)
from jarvis.ports.v2 import ConversationEventRecorder, ConversationEventStore, DiagnosticSink

#: Start-up backfill of `user.transcript.accepted` (docs/conversation-events.md,
#: "Start-up backfill"): only user turns created at or after the store's latest
#: `recorded_at` minus this margin, at most `USER_EVENT_BACKFILL_LIMIT` per start.
USER_EVENT_BACKFILL_MARGIN = timedelta(minutes=10)
USER_EVENT_BACKFILL_LIMIT = 256
USER_EVENT_BACKFILL_KIND = "core.conversation_events.user_backfill"
USER_EVENT_BACKFILL_FAILED_KIND = "core.conversation_events.user_backfill_failed"


@dataclass(frozen=True, slots=True)
class PersistedInput:
    turn: ConversationTurn
    source: SpeechSource
    duplicate: bool


class VoiceTurnAdmissionService:
    def __init__(self, conversations: ConversationService, outcomes: BrainOutcomeService,
                 events: CoreEventBus, diagnostics: DiagnosticSink, *, lock: asyncio.Lock,
                 ledger: VoiceLedgerService | None = None,
                 on_activated: Callable[[BrainTurnInput, SpeechSource], None] | None = None,
                 conversation_events: ConversationEventRecorder | None = None) -> None:
        self.conversations, self.outcomes = conversations, outcomes
        self.events, self.diagnostics = events, diagnostics
        self.lock, self.ledger, self.on_activated = lock, ledger, on_activated
        self.conversation_events = conversation_events or NullConversationEventEmitter()
        self.stopping = False

    def record_user_turn_accepted(self, record: ConversationTurn, *, session_id: str | None = None) -> str | None:
        """Single `user.transcript.accepted` producer (docs/conversation-events.md, Producers).

        Called once the user turn is durable and before any backend work: from
        `persist_turn` (voice admission and `/brain-turns`) for a new admission
        only, and from the legacy `/turns` ingress for a user turn. A duplicate
        admission is not a new fact and is not recorded. Core-opened turns
        (`source=system`, the work-attention wake prompt) are not user speech.
        Never raises; the event id is derived from the durable turn id, and
        `occurred_at` is the turn's creation time, so a repair replay rebuilds
        the identical event.
        """
        if record.kind is not TurnKind.USER or record.metadata.get("source") == BrainTurnSource.SYSTEM.value:
            return None
        attributes = {key: record.metadata[key] for key in ("source", "addressing")
                      if isinstance(record.metadata.get(key), str)}
        return self.conversation_events.record(
            ConversationEventType.USER_TRANSCRIPT_ACCEPTED, producer=PRODUCER_VOICE_ADMISSION,
            conversation_id=record.conversation_id, source_ids=(record.id,), occurred_at=record.created_at,
            session_id=session_id, turn_id=record.id, correlation_id=record.correlation_id,
            content=record.content, attributes=attributes)

    async def backfill_user_turns_accepted(self, store: ConversationEventStore, *,
                                           margin: timedelta = USER_EVENT_BACKFILL_MARGIN,
                                           limit: int = USER_EVENT_BACKFILL_LIMIT) -> int:
        """Re-record recent durable user turns whose event a crash may have lost (Core start).

        The rebuilt event is byte-identical to the original (same id, turn
        `created_at`, content, attributes and session), so the store answers
        `duplicate` for what was already committed and `appended` for what the
        crash lost. Pre-feature history is never backfilled: nothing when the
        store is empty, and only turns created at or after the latest
        `recorded_at` minus `margin`. Bounded by `limit` (newest kept). Returns
        the number of events enqueued; a failure is diagnosed, never raised.
        """
        try:
            latest = await store.latest_recorded_at()
            if latest is None:
                self.diagnostics.emit(USER_EVENT_BACKFILL_KIND, "no conversation event yet: nothing to backfill",
                                      data={"candidates": 0, "recorded": 0, "reason": "empty_store"})
                return 0
            turns = await self.outcomes.repository.list_turns_since(latest - margin, kind=TurnKind.USER.value,
                                                                     limit=limit)
        except Exception as exc:
            # Legal capture: the backfill is observability repair; Core must start anyway.
            self.diagnostics.emit(USER_EVENT_BACKFILL_FAILED_KIND, "user event backfill failed", level="error",
                                  data={"code": "conversation_events_backfill_failed", "error_class": type(exc).__name__})
            return 0
        recorded = 0
        for turn in turns:
            binding = turn.metadata.get("voice_admission")
            session_id = binding.get("session_id") if isinstance(binding, dict) else None
            if self.record_user_turn_accepted(turn, session_id=session_id if isinstance(session_id, str) else None):
                recorded += 1
        self.diagnostics.emit(USER_EVENT_BACKFILL_KIND, "recent user turns re-recorded as conversation events", data={
            "candidates": len(turns), "recorded": recorded, "limit": limit, "capped": len(turns) >= limit,
            "margin_s": int(margin.total_seconds())})
        return recorded

    async def persist_turn(self, turn: BrainTurnInput, *, binding: dict | None = None,
                           canonical_order: VoiceTurnOrder | None = None) -> PersistedInput:
        """Caller holds the shared admission/brain lock; does not activate/execute."""
        repository = self.outcomes.repository
        await self.outcomes.known_conversation(turn.conversation_id)
        turn_id = "brain-turn-" + stable_identity(turn.conversation_id, turn.correlation_id)
        source = await repository.get_brain_source(turn.conversation_id, turn.correlation_id)
        record = await repository.get_turn(turn_id)
        if source is not None and (source.turn_id != turn_id or record is None):
            raise ValueError("admitted source has no matching durable user turn")
        duplicate = source is not None
        metadata = {"authoritative": True, "final": True, "source": turn.source.value,
                    "addressing": turn.addressing.value, "provider_item_id": turn.provider_item_id,
                    "interrupted_speech_id": turn.interrupted_speech_id}
        if binding is not None:
            if (not isinstance(canonical_order, VoiceTurnOrder) or canonical_order.session_id != binding["session_id"]
                    or canonical_order.turn_id != binding["canonical_turn_id"]):
                raise ValueError("direct admission requires server canonical order")
            metadata["voice_admission"] = binding
            metadata["voice_admission_order"] = {"schema_version": 1, **asdict(canonical_order)}
        if record is not None:
            if (record.kind is not TurnKind.USER or record.conversation_id != turn.conversation_id
                    or record.correlation_id != turn.correlation_id or record.content != turn.text
                    or any(record.metadata.get(key) != metadata[key] for key in ("source", "addressing", "provider_item_id"))
                    or (binding is not None and (record.metadata.get("voice_admission") != binding
                        or record.metadata.get("voice_admission_order") != metadata["voice_admission_order"]))):
                raise ValueError("admission identity conflicts with durable input")
            metadata = record.metadata
        # Replaying the same immutable turn repairs an interrupted history write;
        # both SQLite and the archive already deduplicate by this exact turn ID.
        record = await self.conversations.append_turn(
            turn.conversation_id, TurnKind.USER, turn.text, correlation_id=turn.correlation_id,
            turn_id=turn_id, created_at=record.created_at if record is not None else None, metadata=metadata,
        )
        if source is None:
            source = await repository.allocate_brain_source(turn.conversation_id, turn_id, turn.correlation_id)
        if not duplicate:
            self.record_user_turn_accepted(record, session_id=binding["session_id"] if binding is not None else None)
        return PersistedInput(record, source, duplicate)

    async def claim_backend_dispatch(self, admitted: PersistedInput) -> bool:
        """Reserve a direct admission for subsequent execution once, before launch.

        Historical backend ingresses without a direct-admission marker retain
        their existing durable duplicate behavior. A crash after reservation is
        not retried as a new execution; Task11 owns explicit job recovery.
        """
        record = admitted.turn
        if admitted.duplicate and ("voice_admission" not in record.metadata or record.metadata.get("backend_dispatch_reserved") is True):
            return False
        if "voice_admission" in record.metadata:
            return await self.outcomes.repository.claim_admitted_backend_dispatch(record.id)
        return True

    async def admit_voice_turn(self, request: VoiceTurnAdmissionRequest) -> VoiceTurnAdmissionAcceptance:
        if not isinstance(request, VoiceTurnAdmissionRequest):
            raise ValueError("voice admission requires a typed request")
        async with self.lock:
            if self.stopping:
                raise RuntimeError("voice admission is stopping")
            if self.ledger is None:
                raise RuntimeError("canonical voice ledger is unavailable")
            canonical_order = await self.ledger.checkpoint_admitted_input(request)
            correlation_id = admission_correlation_id(request)
            turn = BrainTurnInput(conversation_id=request.conversation_id, correlation_id=correlation_id,
                                  text=request.text, source=BrainTurnSource.REALTIME,
                                  addressing=request.addressing, provider_item_id=request.provider_item_id)
            admitted = await self.persist_turn(turn, binding=request.to_payload(), canonical_order=canonical_order)
            activated = False
            if request.addressing is AddressingDecision.ADDRESSED:
                activated = await self.outcomes.repository.activate_brain_source(request.conversation_id, admitted.source)
                if activated and self.on_activated is not None:
                    self.on_activated(turn, admitted.source)
            acceptance = VoiceTurnAdmissionAcceptance(request.conversation_id, admitted.turn.id, correlation_id,
                                                      admitted.source, admitted.duplicate)
            await self.events.publish(ProtocolEnvelope(message_type=VOICE_TURN_ADMITTED, payload=acceptance.to_payload(),
                                                       conversation_id=request.conversation_id, correlation_id=correlation_id))
            # The source may already be durable after a previous publication
            # failed. Re-publish its current projection idempotently, never an
            # older source that has since been superseded.
            if await self.outcomes.repository.get_current_brain_source(request.conversation_id) == admitted.source:
                await self.events.publish(ProtocolEnvelope(message_type=BRAIN_SOURCE_CHANGED,
                    payload=await self.outcomes.context(request.conversation_id),
                    conversation_id=request.conversation_id, correlation_id=correlation_id))
            self.diagnostics.emit("core.voice.turn_admitted", "Canonical user input admitted without execution",
                                  data={"conversation_id": request.conversation_id, "correlation_id": correlation_id,
                                        "session_id": request.session_id, "turn_id": admitted.turn.id,
                                        "duplicate": admitted.duplicate, "source_activated": activated})
            return acceptance
