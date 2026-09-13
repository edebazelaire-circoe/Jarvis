"""Durable input admission shared by direct conversation and backend ingress.

The checkpoint, history and source stores are separate recovery steps, not a
cross-service transaction. Stable identities make each step safe to retry.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable
import asyncio

from jarvis.core.brain_outcomes import BrainOutcomeService, stable_identity
from jarvis.core.v2_services import ConversationService, CoreEventBus
from jarvis.core.voice_ledger import VoiceLedgerService
from jarvis.domain.speech_presentation import SpeechSource
from jarvis.domain.voice_state import VoiceTurnOrder
from jarvis.domain.v2 import AddressingDecision, BrainTurnInput, BrainTurnSource, ConversationTurn, ProtocolEnvelope, TurnKind
from jarvis.domain.voice_admission import (
    BRAIN_SOURCE_CHANGED, VOICE_TURN_ADMITTED, VoiceTurnAdmissionAcceptance, VoiceTurnAdmissionRequest,
    admission_correlation_id,
)
from jarvis.ports.v2 import DiagnosticSink


@dataclass(frozen=True, slots=True)
class PersistedInput:
    turn: ConversationTurn
    source: SpeechSource
    duplicate: bool


class VoiceTurnAdmissionService:
    def __init__(self, conversations: ConversationService, outcomes: BrainOutcomeService,
                 events: CoreEventBus, diagnostics: DiagnosticSink, *, lock: asyncio.Lock,
                 ledger: VoiceLedgerService | None = None,
                 on_activated: Callable[[BrainTurnInput, SpeechSource], None] | None = None) -> None:
        self.conversations, self.outcomes = conversations, outcomes
        self.events, self.diagnostics = events, diagnostics
        self.lock, self.ledger, self.on_activated = lock, ledger, on_activated
        self.stopping = False

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
