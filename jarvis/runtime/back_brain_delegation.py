"""Bounded direct-conversation tool ingress, bound to an admitted operation."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
import json
import uuid

from jarvis.domain.speech_presentation import SpeechSource
from jarvis.domain.voice_admission import VoiceTurnAdmissionAcceptance
from jarvis.domain.voice_events import AssistantGenerationStarted, VoiceToolCallRequested
from jarvis.domain.voice_frontend import VoiceCorrelation
from jarvis.domain.v2 import SpeechRequest, SpeechKind, SpeechProvenance

BACK_BRAIN_DELEGATE = "back_brain_delegate"


def conversation_tools() -> list[dict]:
    return [{"type": "function", "name": BACK_BRAIN_DELEGATE,
             "description": "Submit the current application-admitted request as independent background work. No arguments; Core supplies the exact request and authority.",
             "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}}]


@dataclass(slots=True)
class _Operation:
    correlation: VoiceCorrelation
    source: SpeechSource
    response_id: str | None = None
    invalidated: bool = False


class BackBrainDelegationController:
    def __init__(self, session):
        self.session = session
        self.operations: OrderedDict[str, _Operation] = OrderedDict()
        self.calls: dict[str, object] = {}
        self.dispatched: set[str] = set()
        self.tasks: set[asyncio.Task] = set()
        self.closed = False
        self.presenter = None
        self.presented: set[tuple[str, str, str | None]] = set()
        self.journal = None

    def _trace(self, status: str, *, source=None, job_id=None) -> None:
        try:
            if self.journal is not None:
                self.journal.emit("voice.back_brain.delegation", "Independent work delegation", data={
                    "status": status, "source_correlation_id": source.correlation_id if source else None,
                    "job_id": job_id, "session_id": getattr(self.session, "session_id", None),
                    "conversation_id": getattr(self.session, "conversation_id", None)})
        except Exception:
            pass  # Diagnostic delivery is never authority over an accepted job.

    def _present(self, conversation_id, source, result) -> None:
        if source is None or self.presenter is None or self.closed:
            return
        key = (source.correlation_id, result["status"], result.get("task_id"))
        if key in self.presented or len(self.presented) >= 128:
            return
        self.presented.add(key)
        accepted = result["status"] == "accepted"
        text = ("Je m’en occupe." if accepted else
                "Je ne peux pas confirmer la prise en charge pour le moment." if result.get("reason") == "back_brain_submission_unknown" else
                "Je ne peux pas lancer ce travail en arrière-plan pour le moment.")
        request = SpeechRequest(conversation_id=conversation_id,
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, "jarvis-delegation:" + json.dumps(key))),
            text=text,
            kind=SpeechKind.ACK, provenance=SpeechProvenance.SYSTEM_NOTIFICATION,
            correlation_id=source.correlation_id, source=source,
            work_id=result.get("task_id") if accepted else None).with_default_ttl()
        self.presenter(request)

    def reserve(self, correlation: VoiceCorrelation, source: SpeechSource) -> None:
        self.operations[correlation.output_id] = _Operation(correlation, source)
        while len(self.operations) > 128:
            self.operations.popitem(last=False)

    def invalidate(self, output_id: str | None) -> None:
        operation = self.operations.get(output_id)
        if operation:
            operation.invalidated = True

    def observe(self, event) -> None:
        operation = self.operations.get(event.correlation.output_id)
        if isinstance(event.payload, AssistantGenerationStarted) and operation is not None:
            response = event.correlation.provider_output_id
            if operation.response_id is not None and operation.response_id != response:
                operation.invalidated = True
            elif response:
                operation.response_id = response
        elif isinstance(event.payload, VoiceToolCallRequested) and event.payload.name == BACK_BRAIN_DELEGATE:
            # Keep the first canonical call identity. Reuse never replaces its source.
            if event.payload.call_id not in self.calls and len(self.calls) < 128:
                self.calls[event.payload.call_id] = event

    def _source(self, event):
        operation = self.operations.get(event.correlation.output_id)
        if operation is None or operation.invalidated or not operation.response_id:
            return None
        actual, expected = event.correlation, operation.correlation
        if (actual.session_id != expected.session_id or actual.turn_id != expected.turn_id
                or actual.provider_input_id != expected.provider_input_id
                or actual.source_correlation_id != expected.source_correlation_id
                or actual.provider_output_id != operation.response_id):
            return None
        return operation.source

    def offer(self, core, conversation_id: str, call_id: str) -> bool:
        if self.closed:
            return False
        if call_id in self.dispatched:
            return True
        event = self.calls.get(call_id)
        if event is None or len(self.tasks) >= 4:
            return False
        self.dispatched.add(call_id)
        task = asyncio.create_task(self._submit(core, conversation_id, event), name=f"back-brain-submit-{call_id}")
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return True

    async def _submit(self, core, conversation_id: str, event) -> None:
        source = self._source(event)
        result = {"status": "unavailable", "reason": "back_brain_source_unavailable"}
        try:
            if json.loads(event.payload.arguments_json) != {}:
                result["reason"] = "back_brain_arguments_forbidden"
            elif source is not None and not self.closed:
                acceptance = VoiceTurnAdmissionAcceptance(conversation_id, source.turn_id, source.correlation_id, source, False)
                async with asyncio.timeout(10):
                    submitted = await self.session.submit_back_brain(core, conversation_id, acceptance)
                # Expose task identity/status only; no raw request, result or action power.
                result = {"status": submitted.status, "task_id": submitted.job_id, "reason": submitted.reason}
        except asyncio.CancelledError:
            raise
        except Exception:
            result = {"status": "unavailable", "reason": "back_brain_submission_unknown"}
        self._trace(result["status"], source=source, job_id=result.get("task_id"))
        # This is a controller acknowledgement of acceptance, never job speech.
        # Scheduler source/expiry/first-write admission remain authoritative.
        try:
            self._present(conversation_id, source, result)
        except Exception:
            self._trace("presentation_unavailable", source=source, job_id=result.get("task_id"))
        try:
            if not self.closed:
                await self.session.send_back_brain_tool_result(event.payload.call_id, result)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Provider may close after durable acceptance. Core retains the job;
            # never retry it under a new source or cancel work due to lost ACK.
            pass

    async def close(self) -> None:
        self.closed = True
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
