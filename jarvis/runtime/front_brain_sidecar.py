"""Session-owned optional analysis: one worker, one in-flight, one latest pending.

No speech or execution handles. Reservations are conservative local accounting
units, not measured model tokens; cancellation never refunds a dispatched call.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import math
import time
from typing import Callable
from uuid import uuid4

from jarvis.domain.front_brain_hints import FrontBrainHintRequest, FrontBrainHintResult, HintAnalysisStatus
from jarvis.domain.speech_presentation import SpeechDependency, SpeechSource
from jarvis.domain.voice_events import (
    UserTranscriptCommitted, UserTranscriptDelta, UserTranscriptRevised, VoiceEvent,
)
from jarvis.domain.voice_frontend import VoiceContext, VoiceContextMessage
from jarvis.domain.voice_state import VoiceUserRecord
from jarvis.ports.front_brain import FrontBrainAnalyzer
from jarvis.ports.v2 import DiagnosticSink
from jarvis.runtime.front_brain_hints import FrontBrainHintConsumer


@dataclass(frozen=True, slots=True)
class FrontBrainSidecarConfig:
    debounce_s: float = .15
    min_interval_s: float = .3
    deadline_s: float = 2.0
    max_calls_per_turn: int = 3
    max_partial_calls: int = 2
    reservation_per_call: int = 135168  # 131072 request bytes + maximum 4096 output tokens.
    turn_reservation_budget: int = 405504
    max_items: int = 64
    speculative_deltas: bool = True

    def __post_init__(self) -> None:
        for name in ("debounce_s", "min_interval_s", "deadline_s"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 30:
                raise ValueError("invalid sidecar timing")
        if self.deadline_s <= 0:
            raise ValueError("analysis needs a positive deadline")
        for name in ("max_calls_per_turn", "max_partial_calls", "reservation_per_call", "turn_reservation_budget", "max_items"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError("sidecar budgets must be positive integers")
        if self.max_partial_calls >= self.max_calls_per_turn or self.max_calls_per_turn > 16 or self.max_items > 256:
            raise ValueError("sidecar must reserve a final call within bounded capacity")
        if self.turn_reservation_budget < self.reservation_per_call * self.max_calls_per_turn:
            raise ValueError("reservation budget must cover configured calls including final")
        if self.reservation_per_call < 135168:
            raise ValueError("reservation must cover the fixed request/output ceiling")
        if type(self.speculative_deltas) is not bool:
            raise ValueError("speculation must be boolean")


@dataclass(slots=True)
class _Item:
    record: VoiceUserRecord | None = None
    permission: str | None = None
    origin: SpeechSource | None = None
    rejected: bool = False
    calls: int = 0
    partial_calls: int = 0
    reservation: int = 0
    final_dispatched: bool = False


class FrontBrainSidecar:
    def __init__(self, analyzer: FrontBrainAnalyzer, *, session_id: str, configuration_id: str,
                 config: FrontBrainSidecarConfig = FrontBrainSidecarConfig(),
                 diagnostics: DiagnosticSink | None = None, clock_ns: Callable[[], int] = time.monotonic_ns) -> None:
        self._analyzer, self.session_id, self.configuration_id = analyzer, session_id, configuration_id
        self.config, self._diagnostics, self._clock = config, diagnostics, clock_ns
        self._consumer = FrontBrainHintConsumer(diagnostics)
        self._items: dict[str, _Item] = {}
        self._context = VoiceContext()
        self._source: SpeechSource | None = None
        self._source_complete = False
        self._dependencies: tuple[SpeechDependency, ...] = ()
        self._pending: tuple[str, FrontBrainHintRequest, int] | None = None
        self._wake = asyncio.Event()
        self._worker: asyncio.Task | None = None
        self._flight: asyncio.Task | None = None
        self._flight_item: str | None = None
        self._closed = False
        self._disabled = False
        self._last_dispatch_ns = 0

    def start(self) -> None:
        if not self._closed and self._worker is None:
            self._worker = asyncio.create_task(self._run(), name="front-brain-sidecar")

    def _item(self, item_id: str) -> _Item | None:
        if self._closed or self._disabled or not item_id:
            return None
        if item_id not in self._items:
            if len(self._items) >= self.config.max_items:
                self.revoke_all("retention_capacity")
                self._disabled = True
                return None
            self._items[item_id] = _Item()
        return self._items[item_id]

    def observe(self, event: VoiceEvent) -> None:
        if event.correlation.session_id != self.session_id:
            return
        payload = event.payload
        if not isinstance(payload, (UserTranscriptDelta, UserTranscriptRevised, UserTranscriptCommitted)):
            return
        item_id = event.correlation.provider_input_id
        item = self._item(item_id) if item_id else None
        if item is None or item.rejected:
            return
        prior = item.record
        if prior is not None:
            if payload.transcript_id != prior.transcript_id:
                self.reject_item(item_id, "transcript_identity_changed")
                return
            if payload.revision < prior.revision:
                return
            if payload.revision == prior.revision and not (isinstance(payload, UserTranscriptCommitted) and not prior.committed):
                return
            if prior.committed:
                return
        if isinstance(payload, UserTranscriptDelta):
            # Deltas append; a gap cannot reconstruct the missing hypothesis.
            if (prior is None and payload.revision not in (0, 1)) or (prior and payload.revision != prior.revision + 1):
                self.reject_item(item_id, "revision_gap")
                return
            text = (prior.text if prior else "") + payload.delta
        else:
            text = payload.text
        try:
            item.record = VoiceUserRecord(event.correlation, payload.transcript_id, payload.revision, text,
                isinstance(payload, UserTranscriptCommitted), payload.source if isinstance(payload, UserTranscriptCommitted) else None)
        except ValueError:
            self.reject_item(item_id, "input_bound")
            return
        if item.record.committed and self._flight_item == item_id and self._flight is not None:
            self._consumer.invalidate()
            self._flight.cancel()  # Finality supersedes speculation even before Core source arrives.
        self._queue(item_id, item)

    def allow_item(self, provider_input_id: str, analysis_admission_id: str) -> None:
        item = self._item(provider_input_id)
        if item is not None and not item.rejected and item.permission is None:
            item.permission = analysis_admission_id
            self._queue(provider_input_id, item)

    def reject_item(self, provider_input_id: str, reason: str) -> None:
        item = self._item(provider_input_id)
        if item is None:
            return
        item.rejected, item.permission = True, None
        item.record = None  # Tombstone retains rejection, not private text.
        current = self._flight_item == provider_input_id
        if self._pending is not None and self._pending[0] == provider_input_id:
            current = True
            self._pending = None
        if self._flight_item == provider_input_id and self._flight is not None:
            self._flight.cancel()
        if current:
            self._consumer.invalidate()
        self._trace("voice.hint.revoked", reason, provider_input_id)
        self._wake.set()

    def admit_item(self, provider_input_id: str, source: SpeechSource) -> None:
        item = self._item(provider_input_id)
        if item is not None and not item.rejected:
            item.origin = source
            self._queue(provider_input_id, item)

    def update_context(self, context: VoiceContext, *, source: SpeechSource | None, source_complete: bool,
                       invalidated_dependencies: tuple[SpeechDependency, ...] = ()) -> None:
        changed = (self._context, self._source, self._source_complete, self._dependencies) != (context, source, source_complete, invalidated_dependencies)
        self._context, self._source = context, source
        self._source_complete, self._dependencies = source_complete, invalidated_dependencies
        if changed:
            self._consumer.invalidate()

    def remember_context(self, message: VoiceContextMessage) -> None:
        messages = list(self._context.messages) + [message]
        while messages and (len(messages) > 8 or sum(len(item.text) for item in messages) > 8192):
            messages.pop(0)
        self._context = VoiceContext(self._context.revision + 1, tuple(messages))
        self._consumer.invalidate()

    def update_source(self, *, source: SpeechSource | None, source_complete: bool,
                      invalidated_dependencies: tuple[SpeechDependency, ...] = ()) -> None:
        self.update_context(self._context, source=source, source_complete=source_complete,
                            invalidated_dependencies=invalidated_dependencies)
        # Build a final only after the actual Core projection catches up. An
        # acceptance returns its origin, not authority to replace a newer intent.
        finals = [(key, item) for key, item in self._items.items() if item.origin is not None
                  and item.record is not None and item.record.committed and not item.final_dispatched and not item.rejected]
        if finals:
            key, item = max(finals, key=lambda pair: pair[1].origin.intent_epoch)
            self._queue(key, item)

    def _queue(self, item_id: str, item: _Item) -> None:
        record = item.record
        if self._closed or self._disabled or item.rejected or not item.permission or record is None or not record.text.strip():
            return
        if record.committed:
            if item.origin is None or item.final_dispatched:
                return
            if not self._source_complete or self._source is None or self._source.intent_epoch < item.origin.intent_epoch:
                return
            if self._source != item.origin:
                self.reject_item(item_id, "stale_origin")
                return
        elif not self.config.speculative_deltas or item.partial_calls >= self.config.max_partial_calls:
            return
        if item.calls >= self.config.max_calls_per_turn:
            return
        now = self._clock()
        try:
            request = FrontBrainHintRequest(str(uuid4()), record, item.origin, self._source, self._context,
                item.permission, self.configuration_id, now + int(self.config.deadline_s * 1e9))
        except ValueError:
            self.reject_item(item_id, "request_bound")
            return
        due = now if record.committed else now + int(self.config.debounce_s * 1e9)
        self._pending = item_id, request, due
        self._consumer.invalidate()
        if record.committed and self._flight_item == item_id and self._flight is not None:
            self._flight.cancel()
        self._wake.set()

    def revoke_all(self, reason: str) -> None:
        for item in self._items.values():
            item.rejected, item.permission, item.record = True, None, None
        self._pending = None
        self._consumer.invalidate()
        if self._flight is not None:
            self._flight.cancel()
        self._wake.set()
        self._trace("voice.hint.revoked", reason)

    async def close(self) -> None:
        self._closed = True
        self.revoke_all("closed")
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None

    async def _run(self) -> None:
        try:
            while not self._closed:
                self._wake.clear()
                pending = self._pending
                if pending is None:
                    await self._wake.wait()
                    continue
                item_id, request, due = pending
                wait_ns = max(due, self._last_dispatch_ns + int(self.config.min_interval_s * 1e9)) - self._clock()
                if wait_ns > 0:
                    try:
                        await asyncio.wait_for(self._wake.wait(), wait_ns / 1e9)
                    except TimeoutError:
                        pass
                    continue
                self._pending = None
                item = self._items[item_id]
                if item.rejected or item.record != request.input or item.permission != request.analysis_admission_id:
                    continue
                if self._clock() >= request.deadline_monotonic_ns:
                    self._trace("voice.hint.skipped", "pending_expired", item_id)
                    continue
                if item.reservation + self.config.reservation_per_call > self.config.turn_reservation_budget:
                    self._trace("voice.hint.skipped", "reservation_budget", item_id)
                    continue
                item.calls += 1
                item.partial_calls += int(not request.input.committed)
                item.final_dispatched |= request.input.committed
                item.reservation += self.config.reservation_per_call
                self._last_dispatch_ns = self._clock()
                self._consumer.expect(request)
                self._trace("voice.hint.dispatched", "final" if request.input.committed else "provisional", item_id,
                            calls=item.calls, reserved_units=item.reservation)
                self._flight_item = item_id
                self._flight = asyncio.create_task(self._analyzer.analyze(request), name="front-brain-analysis")
                try:
                    remaining = (request.deadline_monotonic_ns - self._clock()) / 1e9
                    result = await asyncio.wait_for(self._flight, max(0, remaining))
                except asyncio.CancelledError:
                    if self._closed or asyncio.current_task().cancelling():
                        raise
                    continue
                except TimeoutError:
                    result = FrontBrainHintResult(request.request_id, HintAnalysisStatus.TIMED_OUT, None, self._clock())
                except Exception as exc:
                    self._trace("voice.hint.failed", "analyzer_failure", item_id, error_class=type(exc).__name__)
                    result = FrontBrainHintResult(request.request_id, HintAnalysisStatus.TRANSPORT_ERROR, None, self._clock())
                finally:
                    self._flight, self._flight_item = None, None
                if item.record is not None:
                    self._consumer.consume(result, current_input=item.record, current_origin_source=item.origin,
                        current_context_source=self._source, current_configuration_id=self.configuration_id,
                        current_admission_id=item.permission, source_complete=self._source_complete,
                        invalidated_dependencies=self._dependencies, now_monotonic_ns=self._clock())
        finally:
            if self._flight is not None:
                self._flight.cancel()
                try:
                    await self._flight
                except asyncio.CancelledError:
                    pass
                self._flight = None

    def _trace(self, kind: str, reason: str, item_id: str | None = None, **data) -> None:
        if self._diagnostics is not None:
            self._diagnostics.emit(kind, "Front Brain optional analysis", data={"session_id": self.session_id,
                "configuration_id": self.configuration_id, "provider_input_id": item_id, "reason": reason, **data})
