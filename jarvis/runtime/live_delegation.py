"""Bounded GPT-Live client delegation: real brain turn, or legacy speculation."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass

from jarvis.domain.voice_events import VoiceDelegationRequested
from jarvis.domain.voice_frontend import VoiceCorrelation, VoiceOperation, VoiceOperationStatus, VoiceTextUpdate

# Le fournisseur émet la délégation dans les mêmes millisecondes que le dernier
# delta d'entrée, parfois même avec un `offset_ms` antérieur à sa fin. On laisse
# donc la queue de transcription arriver avant de lire la demande, sans jamais
# filtrer sur cet offset.
TRAILING_GRACE_S = .4


@dataclass(frozen=True, slots=True)
class _Trigger:
    session_id: str
    delegation_id: str
    context_revision: int
    offset_ms: int | None = None


class LiveDelegationController:
    """One nonblocking task per provider delegation; Core owns the work."""

    def __init__(self, session, *, max_pending: int = 4, poll_interval_s: float = .05,
                 brain_orchestration: bool = True, trailing_grace_s: float = TRAILING_GRACE_S) -> None:
        if (type(max_pending) is not int or not 1 <= max_pending <= 16
                or poll_interval_s <= 0 or trailing_grace_s < 0):
            raise ValueError("invalid Live delegation bounds")
        self.session = session
        self.max_pending, self.poll_interval_s = max_pending, poll_interval_s
        self.brain_orchestration, self.trailing_grace_s = bool(brain_orchestration), trailing_grace_s
        # Les deux chemins tracent dans le même flux : la voie doit rester
        # lisible sans deviner, un `unavailable` spéculatif ne devant jamais
        # passer pour un échec de tour cerveau.
        self._path = "brain_turn" if self.brain_orchestration else "speculative"
        self._seen: OrderedDict[tuple[str, str], None] = OrderedDict()
        self._tasks: set[asyncio.Task] = set()
        self._closed = False

    def _trace(self, status: str, *, job_id: str | None = None, offset_ms: int | None = None) -> None:
        journal = getattr(self.session, "journal", None)
        if journal is None:
            return
        try:
            journal.emit("voice.live.delegation", "Live client delegation", data={
                "status": status, "path": self._path, "job_id": job_id, "offset_ms": offset_ms,
                "session_id": self.session.session_id,
                "conversation_id": getattr(self.session, "conversation_id", None),
            })
        except Exception:
            pass

    def offer(self, event) -> bool:
        if self._closed or not isinstance(event.payload, VoiceDelegationRequested):
            return False
        delegation = event.correlation.provider_delegation_id
        if event.correlation.session_id != self.session.session_id or delegation is None:
            return False
        key = (str(event.correlation.session_id), str(delegation))
        if key in self._seen:
            return True
        if len(self._tasks) >= self.max_pending or len(self._seen) >= 128:
            self._trace("capacity")
            return False
        self._seen[key] = None
        trigger = _Trigger(*key, event.payload.context_revision, event.payload.offset_ms)
        if self.brain_orchestration:
            # La demande accumulée doit survivre à la réponse réflexe du modèle,
            # qui arrive dans la même poignée de millisecondes.
            hold = getattr(self.session, "hold_pending_request", None)
            if callable(hold):
                hold()
        runner = self._dispatch_brain_turn if self.brain_orchestration else self._submit_and_poll
        task = asyncio.create_task(runner(trigger), name=f"jarvis-live-delegation-{delegation}")
        self._tasks.add(task)
        task.add_done_callback(self._finished)
        return True

    def _finished(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled():
            task.exception()

    def _stale(self, trigger: _Trigger) -> bool:
        return self._closed or trigger.session_id != self.session.session_id

    async def _dispatch_brain_turn(self, trigger: _Trigger) -> None:
        """Route the delegation through the one authoritative brain ingress.

        Same path as `continuous_brain` (`POST /v1/conversations/{id}/brain-turns`),
        so the turn reaches the Claude CLI with its tools and its sub-agents.
        Fire-and-forget: the answer comes back as `brain.speech.requested`, which
        the SpeechScheduler already presents through the commentary channel.
        """
        try:
            # Le journal durable d'abord : Core capture sa dépendance sur des
            # observations déjà écrites, jamais sur l'état local en vol.
            await self.session.flush_observations()
            if self._stale(trigger):
                return
            if self.trailing_grace_s:
                await asyncio.sleep(self.trailing_grace_s)
            if self._stale(trigger):
                return
            await self.session.flush_observations()
            text = self.session.pending_request_text()
            if not text:
                # Aucun tour vide ne part : mieux vaut perdre une délégation
                # qu'inventer une demande que l'utilisateur n'a pas faite.
                self._trace("empty_request", offset_ms=trigger.offset_ms)
                return
            correlation_id = f"live:{self.session.conversation_id}:{trigger.delegation_id}"
            try:
                await self.session.core.submit_brain_turn(
                    self.session.conversation_id, content=text, correlation_id=correlation_id,
                    source="realtime", addressing="addressed", provider_item_id=trigger.delegation_id,
                )
            except asyncio.CancelledError:
                raise
            except Exception as failure:
                # 503 : Core s'arrête. La corrélation est déterministe, donc un
                # rejeu du même identifiant de délégation resterait unique.
                self._trace("core_stopping" if getattr(failure, "status", None) == 503 else "rejected",
                            offset_ms=trigger.offset_ms)
                return
            self._trace("brain_turn_submitted", offset_ms=trigger.offset_ms)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._trace("submission_unknown", offset_ms=trigger.offset_ms)
        finally:
            reset = getattr(self.session, "reset_pending_request", None)
            if callable(reset):
                reset()

    async def _append(self, channel: str, text: str, trigger: _Trigger) -> bool:
        if self._stale(trigger):
            return False
        if not text or len(text.encode("utf-8")) > 500:
            return False
        correlation = VoiceCorrelation(trigger.session_id, provider_delegation_id=trigger.delegation_id)
        operation = VoiceOperation(self.session.operation_id(), correlation)
        method = (self.session.frontend.append_spoken_result if channel == "commentary"
                  else self.session.frontend.append_quiet_context)
        result = await method(VoiceTextUpdate(text, trigger.context_revision), operation=operation)
        return result.status is VoiceOperationStatus.COMPLETED

    async def _submit_and_poll(self, trigger: _Trigger) -> None:
        """Legacy `brain_orchestration=false` path: speculative analysis, no tools."""
        try:
            # The delegation event and every preceding transcript fragment must
            # be durable before Core captures its immutable dependency snapshot.
            await self.session.flush_observations()
            if self._stale(trigger):
                return
            submitted = await self.session.core.submit_back_brain_task(
                self.session.conversation_id, scope="speculative_analysis",
                session_id=trigger.session_id, delegation_id=trigger.delegation_id,
            )
            if submitted.status != "accepted" or submitted.job_id is None:
                self._trace("unavailable")
                return
            self._trace("accepted", job_id=submitted.job_id)
            last_progress = None
            while not self._stale(trigger):
                try:
                    revision = getattr(self.session, "input_observation_revision", 0)
                    await self.session.flush_observations()
                    status = await self.session.core.back_brain_task_status(self.session.conversation_id, submitted.job_id)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # A Core restart does not erase its SQLite job. Keep the
                    # same stable identity and poll; never resubmit the work.
                    await asyncio.sleep(self.poll_interval_s)
                    continue
                # A Core response is only current for the local input that was
                # flushed before it. Never append across an in-flight correction.
                if revision != getattr(self.session, "input_observation_revision", 0):
                    await asyncio.sleep(self.poll_interval_s)
                    continue
                progress = status.get("progress")
                summary = progress.get("public_summary") if isinstance(progress, dict) else None
                if status.get("fresh") is True and isinstance(summary, str) and summary and summary != last_progress:
                    last_progress = summary
                    await self._append("thinking", summary, trigger)
                if revision != getattr(self.session, "input_observation_revision", 0):
                    await asyncio.sleep(self.poll_interval_s)
                    continue
                state = status.get("status")
                if state == "completed":
                    result = status.get("result")
                    text = result.get("text") if isinstance(result, dict) else None
                    if status.get("fresh") is True and isinstance(text, str):
                        acknowledged = await self._append("commentary", text, trigger)
                        self._trace("append_acknowledged" if acknowledged else "append_unconfirmed", job_id=submitted.job_id)
                    else:
                        self._trace("stale", job_id=submitted.job_id)
                    return
                if state in {"failed", "cancelled", "interrupted"}:
                    self._trace(str(state), job_id=submitted.job_id)
                    return
                await asyncio.sleep(self.poll_interval_s)
        except asyncio.CancelledError:
            raise
        except Exception:
            # No append is safer than converting an uncertain submission or a
            # stale/error result into conversational fact.
            self._trace("unknown")
            return

    async def close(self) -> None:
        self._closed = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
