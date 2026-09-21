"""Core authority for durable Live lifecycle ownership and fencing."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

from jarvis.domain.live_lifecycle import (
    MAX_LEASE_SECONDS, LiveCloseEvidence, LiveLifecycleConflict, LiveLifecycleOperation,
    LiveLifecycleState, LiveOwnerKind, LiveSessionRecord,
    live_id, live_seconds, live_time,
)


class _SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class LiveLifecycleService:
    def __init__(self, repository, diagnostics=None, *, clock=None,
                 lease_seconds: float = 30.0, accepting_new=None) -> None:
        try:
            valid_lease = (not isinstance(lease_seconds, bool)
                           and isinstance(lease_seconds, (int, float))
                           and math.isfinite(lease_seconds)
                           and 1 <= lease_seconds <= MAX_LEASE_SECONDS)
        except OverflowError:
            valid_lease = False
        if not valid_lease:
            raise ValueError("invalid Live lease duration")
        self.repository = repository
        self.diagnostics = diagnostics
        self.clock = clock or _SystemClock()
        self.lease_seconds = float(lease_seconds)
        self.accepting_new = accepting_new or (lambda: True)

    def _require_accepting(self) -> None:
        if self.accepting_new() is not True:
            raise LiveLifecycleConflict("live_core_not_accepting")

    def _now(self) -> datetime:
        return live_time(self.clock.now(), "Core clock")

    def _deadline(self, now: datetime) -> datetime:
        return now + timedelta(seconds=self.lease_seconds)

    def _emit(self, kind: str, message: str, record: LiveSessionRecord | None = None,
              *, code: str | None = None, level: str = "info") -> None:
        if self.diagnostics is None:
            return
        data: dict[str, object] = {"code": code} if code else {}
        if record is not None:
            data.update({
                "session_id": record.session_id, "state": record.state.value,
                "owner_epoch": record.owner_epoch, "owner_kind": record.owner_kind.value,
                "revision": record.revision,
                "last_operation": record.last_operation.value,
                "start_may_have_been_sent": record.start_may_have_been_sent,
                "active_seconds": record.active_seconds,
                "provider_usage_seconds": record.provider_usage_seconds,
                "close_evidence": record.close_evidence.value if record.close_evidence else None,
            })
        try:
            self.diagnostics.emit(kind, message, level=level, data=data)
        except Exception:
            pass

    async def _load(self, session_id: str) -> LiveSessionRecord:
        live_id(session_id, "session_id")
        try:
            record = await self.repository.get_live_session(session_id)
        except Exception as exc:
            self._emit("live.lifecycle.persistence_failed", "Live lifecycle storage failed",
                       code=type(exc).__name__, level="error")
            raise
        if record is None:
            raise LiveLifecycleConflict("live_session_not_found")
        return record

    def _owned(self, record: LiveSessionRecord, owner: str, epoch: int,
               expected_revision: int) -> None:
        self._validate_fencing(owner, epoch, expected_revision)
        if record.owner_incarnation_id != owner or record.owner_epoch != epoch:
            raise LiveLifecycleConflict("live_stale_owner")
        if record.revision != expected_revision:
            raise LiveLifecycleConflict("live_stale_revision")

    @staticmethod
    def _validate_fencing(owner: str, epoch: int, expected_revision: int) -> None:
        live_id(owner, "owner_incarnation_id")
        if type(epoch) is not int or not 1 <= epoch <= 2**63 - 1:
            raise ValueError("invalid owner_epoch")
        if type(expected_revision) is not int or not 1 <= expected_revision <= 2**63 - 1:
            raise ValueError("invalid expected_revision")

    @staticmethod
    def _fresh_time(record: LiveSessionRecord, at: datetime) -> None:
        if at < record.updated_at:
            raise ValueError("lifecycle timestamp cannot move backwards")

    async def _cas(self, candidate: LiveSessionRecord, expected_revision: int,
                   action: str) -> LiveSessionRecord:
        try:
            stored, changed = await self.repository.cas_live_session(candidate, expected_revision=expected_revision)
        except LiveLifecycleConflict as exc:
            self._emit("live.lifecycle.rejected", "Live lifecycle mutation rejected",
                       candidate, code=exc.code)
            raise
        except Exception as exc:
            self._emit("live.lifecycle.persistence_failed", "Live lifecycle storage failed",
                       candidate, code=type(exc).__name__, level="error")
            raise
        if changed:
            self._emit(f"live.lifecycle.{action}", "Live lifecycle updated", stored)
        return stored

    async def reserve(self, session_id: str, owner_incarnation_id: str) -> LiveSessionRecord:
        self._require_accepting()
        session_id = live_id(session_id, "session_id")
        owner = live_id(owner_incarnation_id, "owner_incarnation_id")
        heartbeat = self._now()
        deadline = self._deadline(heartbeat)
        candidate = LiveSessionRecord(
            session_id=session_id, provider_session_id=None,
            owner_incarnation_id=owner, owner_epoch=1,
            owner_kind=LiveOwnerKind.PRIMARY, state=LiveLifecycleState.STARTING,
            start_may_have_been_sent=False,
            heartbeat_at=heartbeat, lease_deadline=deadline,
            created_at=heartbeat, updated_at=heartbeat, state_entered_at=heartbeat,
            activated_at=None, stopped_at=None, active_seconds=0.0,
            provider_usage_seconds=None, provider_usage_final=False,
            close_reason=None, close_evidence=None,
            last_operation=LiveLifecycleOperation.RESERVE, revision=1,
        )
        try:
            stored, created = await self.repository.reserve_live_session(candidate)
        except LiveLifecycleConflict as exc:
            self._emit("live.lifecycle.rejected", "Live reservation rejected",
                       candidate, code=exc.code)
            raise
        except Exception as exc:
            self._emit("live.lifecycle.persistence_failed", "Live lifecycle storage failed",
                       candidate, code=type(exc).__name__, level="error")
            raise
        if created:
            self._emit("live.lifecycle.reserved", "Live session reserved", stored)
        return stored

    async def mark_start(self, session_id: str, owner_incarnation_id: str, owner_epoch: int,
                         expected_revision: int) -> LiveSessionRecord:
        self._require_accepting()
        self._validate_fencing(owner_incarnation_id, owner_epoch, expected_revision)
        at = self._now()
        record = await self._load(session_id)
        if (record.owner_incarnation_id == owner_incarnation_id
                and record.owner_epoch == owner_epoch
                and record.revision == expected_revision + 1
                and record.state is LiveLifecycleState.STARTING
                and record.provider_session_id is None
                and record.last_operation is LiveLifecycleOperation.MARK_START
                and record.start_may_have_been_sent):
            return record
        self._owned(record, owner_incarnation_id, owner_epoch, expected_revision)
        self._fresh_time(record, at)
        if (record.state is not LiveLifecycleState.STARTING
                or record.owner_kind is not LiveOwnerKind.PRIMARY
                or record.start_may_have_been_sent):
            raise LiveLifecycleConflict("live_invalid_transition")
        return await self._cas(record.next(start_may_have_been_sent=True, updated_at=at,
                                           last_operation=LiveLifecycleOperation.MARK_START),
                               expected_revision, "start_marked")

    async def bind(self, session_id: str, owner_incarnation_id: str, owner_epoch: int,
                   expected_revision: int, provider_session_id: str) -> LiveSessionRecord:
        provider = live_id(provider_session_id, "provider_session_id")
        self._validate_fencing(owner_incarnation_id, owner_epoch, expected_revision)
        at = self._now()
        record = await self._load(session_id)
        if (record.owner_incarnation_id == owner_incarnation_id
                and record.owner_epoch == owner_epoch
                and record.revision == expected_revision + 1
                and record.state is LiveLifecycleState.STARTING
                and record.last_operation is LiveLifecycleOperation.BIND
                and record.provider_session_id == provider):
            return record
        self._owned(record, owner_incarnation_id, owner_epoch, expected_revision)
        self._fresh_time(record, at)
        if not record.start_may_have_been_sent or record.provider_session_id is not None:
            raise LiveLifecycleConflict("live_identity_conflict")
        return await self._cas(record.next(provider_session_id=provider, updated_at=at,
                                           last_operation=LiveLifecycleOperation.BIND),
                               expected_revision, "bound")

    async def heartbeat(self, session_id: str, owner_incarnation_id: str, owner_epoch: int,
                        expected_revision: int) -> LiveSessionRecord:
        self._validate_fencing(owner_incarnation_id, owner_epoch, expected_revision)
        at = self._now()
        deadline = self._deadline(at)
        record = await self._load(session_id)
        if (record.owner_incarnation_id == owner_incarnation_id
                and record.owner_epoch == owner_epoch
                and record.revision == expected_revision + 1
                and record.last_operation is LiveLifecycleOperation.HEARTBEAT
                and record.state is not LiveLifecycleState.STOPPED):
            return record
        self._owned(record, owner_incarnation_id, owner_epoch, expected_revision)
        self._fresh_time(record, at)
        if record.state is LiveLifecycleState.STOPPED:
            raise LiveLifecycleConflict("live_invalid_transition")
        return await self._cas(record.next(heartbeat_at=at, lease_deadline=deadline, updated_at=at,
                                           last_operation=LiveLifecycleOperation.HEARTBEAT),
                               expected_revision, "heartbeat")

    async def transition(self, session_id: str, owner_incarnation_id: str, owner_epoch: int,
                         expected_revision: int, target: LiveLifecycleState,
                         close_reason: str | None = None) -> LiveSessionRecord:
        if not isinstance(target, LiveLifecycleState):
            raise ValueError("invalid Live lifecycle target")
        if target is LiveLifecycleState.ACTIVE:
            self._require_accepting()
        self._validate_fencing(owner_incarnation_id, owner_epoch, expected_revision)
        at = self._now()
        reason = live_id(close_reason, "close_reason") if close_reason is not None else None
        closing = target in {LiveLifecycleState.STOPPING, LiveLifecycleState.UNKNOWN_REAP_REQUIRED}
        if closing and reason is None:
            raise ValueError("closing or uncertain transition requires close_reason")
        if not closing and reason is not None:
            raise ValueError("non-closing transition cannot include close_reason")
        record = await self._load(session_id)
        if (record.owner_incarnation_id == owner_incarnation_id
                and record.owner_epoch == owner_epoch
                and record.revision == expected_revision + 1
                and record.state is target
                and record.last_operation is LiveLifecycleOperation.TRANSITION
                and record.close_reason == reason):
            return record
        self._owned(record, owner_incarnation_id, owner_epoch, expected_revision)
        self._fresh_time(record, at)
        if target is LiveLifecycleState.STOPPED or not record.permits(target):
            raise LiveLifecycleConflict("live_invalid_transition")
        if (record.state is LiveLifecycleState.UNKNOWN_REAP_REQUIRED
                and target is LiveLifecycleState.STOPPING
                and record.provider_session_id is None):
            raise LiveLifecycleConflict("live_invalid_transition")
        if target in {LiveLifecycleState.ACTIVE, LiveLifecycleState.IDLE_CANDIDATE} and record.provider_session_id is None:
            raise LiveLifecycleConflict("live_invalid_transition")
        activated = at if target is LiveLifecycleState.ACTIVE and record.activated_at is None else record.activated_at
        return await self._cas(record.next(
            state=target, state_entered_at=at, updated_at=at,
            activated_at=activated, close_reason=reason or record.close_reason,
            last_operation=LiveLifecycleOperation.TRANSITION,
        ), expected_revision, target.value)

    async def usage(self, session_id: str, owner_incarnation_id: str, owner_epoch: int,
                    expected_revision: int, active_seconds: float,
                    provider_usage_seconds: float | None,
                    provider_usage_final: bool = False) -> LiveSessionRecord:
        at = self._now()
        active = live_seconds(active_seconds, "active_seconds")
        provider = live_seconds(provider_usage_seconds, "provider_usage_seconds", optional=True)
        if type(provider_usage_final) is not bool:
            raise ValueError("invalid provider_usage_final")
        if provider_usage_final:
            raise ValueError("final provider usage is reserved for finalize")
        self._validate_fencing(owner_incarnation_id, owner_epoch, expected_revision)
        record = await self._load(session_id)
        if record.state is LiveLifecycleState.STOPPED:
            raise LiveLifecycleConflict("live_invalid_transition")
        if (record.owner_incarnation_id == owner_incarnation_id and record.owner_epoch == owner_epoch
                and record.revision == expected_revision + 1
                and record.last_operation is LiveLifecycleOperation.USAGE
                and record.active_seconds == active and record.provider_usage_seconds == provider
                and record.provider_usage_final == provider_usage_final):
            return record
        self._owned(record, owner_incarnation_id, owner_epoch, expected_revision)
        self._fresh_time(record, at)
        if active < record.active_seconds:
            raise ValueError("active_seconds cannot decrease")
        if (record.provider_usage_seconds is not None
                and (provider is None or provider < record.provider_usage_seconds)):
            raise ValueError("provider_usage_seconds cannot decrease")
        if record.provider_usage_final and not provider_usage_final:
            raise ValueError("final provider usage cannot become cumulative")
        return await self._cas(record.next(
            active_seconds=active, provider_usage_seconds=provider,
            provider_usage_final=provider_usage_final, updated_at=at,
            last_operation=LiveLifecycleOperation.USAGE,
        ), expected_revision, "usage")

    async def status(self, session_id: str | None = None) -> LiveSessionRecord | None:
        try:
            if session_id is None:
                return await self.repository.get_unresolved_live_session()
            return await self.repository.get_live_session(live_id(session_id, "session_id"))
        except Exception as exc:
            self._emit("live.lifecycle.persistence_failed", "Live lifecycle storage failed",
                       code=type(exc).__name__, level="error")
            raise

    async def claim_reap(self, session_id: str, reaper_incarnation_id: str,
                         expected_revision: int) -> LiveSessionRecord:
        reaper = live_id(reaper_incarnation_id, "reaper_incarnation_id")
        if type(expected_revision) is not int or not 1 <= expected_revision <= 2**63 - 1:
            raise ValueError("invalid expected_revision")
        at = self._now()
        deadline = self._deadline(at)
        record = await self._load(session_id)
        if (record.owner_incarnation_id == reaper
                and record.owner_kind is LiveOwnerKind.REAPER
                and record.state is LiveLifecycleState.UNKNOWN_REAP_REQUIRED
                and record.last_operation is LiveLifecycleOperation.CLAIM_REAP
                and record.revision == expected_revision + 1):
            return record
        if type(expected_revision) is not int or record.revision != expected_revision:
            raise LiveLifecycleConflict("live_stale_revision")
        self._fresh_time(record, at)
        if record.state is LiveLifecycleState.STOPPED:
            raise LiveLifecycleConflict("live_reap_not_eligible")
        eligible_unknown_primary = (
            record.state is LiveLifecycleState.UNKNOWN_REAP_REQUIRED
            and record.owner_kind is LiveOwnerKind.PRIMARY
        )
        if not eligible_unknown_primary and record.lease_deadline > at:
            raise LiveLifecycleConflict("live_reap_not_eligible")
        candidate = record.next(
            owner_incarnation_id=reaper, owner_epoch=record.owner_epoch + 1,
            owner_kind=LiveOwnerKind.REAPER,
            state=LiveLifecycleState.UNKNOWN_REAP_REQUIRED,
            heartbeat_at=at, lease_deadline=deadline, updated_at=at, state_entered_at=at,
            close_reason=record.close_reason or "lease_expired",
            last_operation=LiveLifecycleOperation.CLAIM_REAP,
        )
        return await self._cas(candidate, expected_revision, "reap_claimed")

    async def finalize(self, session_id: str, owner_incarnation_id: str, owner_epoch: int,
                       expected_revision: int, provider_session_id: str | None,
                       active_seconds: float, provider_usage_seconds: float | None,
                       close_reason: str, close_evidence: LiveCloseEvidence) -> LiveSessionRecord:
        at = self._now()
        provider_id = (live_id(provider_session_id, "provider_session_id")
                       if provider_session_id is not None else None)
        active = live_seconds(active_seconds, "active_seconds")
        usage = live_seconds(provider_usage_seconds, "provider_usage_seconds", optional=True)
        reason = live_id(close_reason, "close_reason")
        if not isinstance(close_evidence, LiveCloseEvidence):
            raise ValueError("invalid close_evidence")
        self._validate_fencing(owner_incarnation_id, owner_epoch, expected_revision)
        record = await self._load(session_id)
        if (record.owner_incarnation_id == owner_incarnation_id and record.owner_epoch == owner_epoch
                and record.revision == expected_revision + 1
                and record.last_operation is LiveLifecycleOperation.FINALIZE
                and record.state is LiveLifecycleState.STOPPED):
            if (record.provider_session_id == provider_id and record.active_seconds == active
                    and record.close_reason == reason and record.close_evidence is close_evidence
                    and record.provider_usage_seconds == usage
                    and record.provider_usage_final == (usage is not None)):
                return record
            raise LiveLifecycleConflict("live_identity_conflict")
        self._owned(record, owner_incarnation_id, owner_epoch, expected_revision)
        self._fresh_time(record, at)
        if record.state not in {LiveLifecycleState.STOPPING, LiveLifecycleState.UNKNOWN_REAP_REQUIRED}:
            raise LiveLifecycleConflict("live_invalid_transition")
        provider_closed = close_evidence is LiveCloseEvidence.PROVIDER_SESSION_CLOSED
        never_started = close_evidence is LiveCloseEvidence.START_NOT_SENT
        expired = close_evidence is LiveCloseEvidence.PROVIDER_SESSION_EXPIRED
        if expired and (not record.start_may_have_been_sent
                        or record.provider_session_id is None or provider_id is None
                        or record.provider_session_id != provider_id):
            raise LiveLifecycleConflict("live_identity_conflict")
        # L'expiration n'est pas un reçu : elle ne peut pas apporter d'usage
        # final, sinon on inventerait une facture que le fournisseur n'a jamais
        # confirmée.
        if expired and usage is not None:
            raise LiveLifecycleConflict("live_close_unconfirmed")
        if provider_closed and (not record.start_may_have_been_sent
                                or record.provider_session_id is None or provider_id is None
                                or record.provider_session_id != provider_id):
            raise LiveLifecycleConflict("live_identity_conflict")
        if provider_closed and usage is None:
            raise LiveLifecycleConflict("live_close_unconfirmed")
        if never_started and (record.start_may_have_been_sent or record.provider_session_id is not None
                              or provider_id is not None or usage is not None or active != 0
                              or record.provider_usage_seconds is not None or record.provider_usage_final):
            raise LiveLifecycleConflict("live_close_unconfirmed")
        if active < record.active_seconds or (usage is not None and record.provider_usage_seconds is not None
                                               and usage < record.provider_usage_seconds):
            raise ValueError("final usage cannot decrease")
        final_usage = usage if usage is not None else record.provider_usage_seconds
        candidate = record.next(
            state=LiveLifecycleState.STOPPED, state_entered_at=at, updated_at=at,
            stopped_at=at, active_seconds=active, provider_usage_seconds=final_usage,
            provider_usage_final=(usage is not None), close_reason=reason,
            close_evidence=close_evidence, last_operation=LiveLifecycleOperation.FINALIZE,
        )
        return await self._cas(candidate, expected_revision, "stopped")
