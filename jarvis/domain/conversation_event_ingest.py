"""Wire batch for Conversation Events sent to Core by other processes (Slice 03a).

Binding contract: `docs/conversation-events.md`, section "Producers and
ingestion". Core owns the store; the voice runtime and the Control Center reach
it through `POST /v1/conversation-events` (`LocalCoreClient.append_conversation_events`).

Invariants:

- a batch is `{"schema_version": 1, "events": [1..MAX_APPEND_BATCH encoded events]}`,
  exact keys; every event goes through the Slice 01 codec. One invalid event
  rejects the whole batch (nothing is appended), like `/v1/work/observations`;
- `user.*` and `brain.*` events, and any producer in the `core` namespace, are
  Core-owned: Core emits them in process and never accepts them over the wire,
  so the single-producer rule (event identity includes the producer) cannot be
  broken by a second process;
- error messages name the event index and the codec rule, never a value.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from jarvis.domain.conversation_event_store import MAX_APPEND_BATCH, AppendResult, AppendStatus
from jarvis.domain.conversation_events import (
    ConversationActor,
    ConversationEvent,
    ConversationEventError,
    decode_conversation_event,
    encode_conversation_event,
)

CONVERSATION_EVENT_BATCH_SCHEMA_VERSION = 1
#: Request body bound Core accepts for `POST /v1/conversation-events`. The
#: largest contract-valid batch encoded with `json.dumps` (non-ASCII escaped:
#: an astral character is 1 code point but 12 bytes) is 4 446 461 bytes
#: (4.24 MiB): 32 events with content 8192, every id 256, attributes at their
#: 4096 UTF-8 byte bound (`tests/fakes/conversation_events.worst_case_ingest_batch`).
#: 6 MiB keeps ~40 % headroom for encoder whitespace; aiohttp's default (1 MiB) does not fit.
MAX_CONVERSATION_EVENT_BATCH_BODY_BYTES = 6 * 2**20
_BATCH_FIELDS = frozenset({"schema_version", "events"})
_RESULT_FIELDS = frozenset({"event_id", "sequence", "status"})

#: Actors whose events only Core produces (voice admission, Brain orchestrator).
CORE_OWNED_ACTORS = frozenset({ConversationActor.USER, ConversationActor.BRAIN})
#: Producer namespace reserved to in-process Core producers.
CORE_PRODUCER_NAMESPACE = "core"


class ConversationEventAppendResponseError(ValueError):
    """Core answered with a well-formed JSON body that does not answer the batch.

    Distinct from a transport decode error (`json.JSONDecodeError`, also a
    `ValueError`): replaying the same batch against the same Core would get the
    same answer, whereas a garbled body during a restart is worth a retry.
    """


def is_core_owned(event: ConversationEvent) -> bool:
    producer = event.producer
    return (event.actor in CORE_OWNED_ACTORS or producer == CORE_PRODUCER_NAMESPACE
            or producer.startswith(CORE_PRODUCER_NAMESPACE + "."))


def _check_batch_size(count: int) -> None:
    if not 1 <= count <= MAX_APPEND_BATCH:
        raise ConversationEventError(f"events must hold 1 to {MAX_APPEND_BATCH} conversation events")


def encode_conversation_event_batch(events: Sequence[ConversationEvent]) -> dict[str, Any]:
    """JSON body for `POST /v1/conversation-events`. Raises `ConversationEventError` before any I/O."""
    events = tuple(events)
    _check_batch_size(len(events))
    return {"schema_version": CONVERSATION_EVENT_BATCH_SCHEMA_VERSION,
            "events": [encode_conversation_event(event) for event in events]}


def decode_conversation_event_batch(payload: object) -> tuple[ConversationEvent, ...]:
    """Strict decode of an ingestion body. Raises `ConversationEventError` naming the index and rule."""
    if not isinstance(payload, Mapping):
        raise ConversationEventError("conversation event batch must be a JSON object")
    if set(payload) != _BATCH_FIELDS:
        raise ConversationEventError("conversation event batch must have exactly the fields events, schema_version")
    version = payload["schema_version"]
    if type(version) is not int or version != CONVERSATION_EVENT_BATCH_SCHEMA_VERSION:
        raise ConversationEventError(f"unsupported batch schema_version; expected {CONVERSATION_EVENT_BATCH_SCHEMA_VERSION}")
    raw = payload["events"]
    if not isinstance(raw, list):
        raise ConversationEventError("events must be a list")
    _check_batch_size(len(raw))
    decoded: list[ConversationEvent] = []
    for index, item in enumerate(raw):
        try:
            event = decode_conversation_event(item)
        except ConversationEventError as exc:
            raise type(exc)(f"events[{index}]: {exc}") from None
        if is_core_owned(event):
            raise ConversationEventError(
                f"events[{index}]: {event.event_type.value} from this producer is Core-owned and cannot be ingested")
        decoded.append(event)
    return tuple(decoded)


def encode_append_results(results: Sequence[AppendResult]) -> dict[str, Any]:
    return {"schema_version": CONVERSATION_EVENT_BATCH_SCHEMA_VERSION,
            "results": [{"event_id": item.event_id, "sequence": item.sequence, "status": item.status.value}
                        for item in results]}


def decode_append_results(payload: object, events: Sequence[ConversationEvent]) -> tuple[AppendResult, ...]:
    """Strict decode of the ingestion response; results must answer `events` one-to-one, in order."""
    if not isinstance(payload, Mapping) or set(payload) != {"schema_version", "results"}:
        raise ConversationEventAppendResponseError("conversation event append response must have exactly schema_version and results")
    if payload["schema_version"] != CONVERSATION_EVENT_BATCH_SCHEMA_VERSION or not isinstance(payload["results"], list):
        raise ConversationEventAppendResponseError("invalid conversation event append response")
    results = payload["results"]
    if len(results) != len(events):
        raise ConversationEventAppendResponseError("conversation event append response does not answer every event")
    decoded = []
    for event, item in zip(events, results):
        if not isinstance(item, Mapping) or set(item) != _RESULT_FIELDS:
            raise ConversationEventAppendResponseError("invalid conversation event append result")
        sequence = item["sequence"]
        if item["event_id"] != event.event_id or type(sequence) is not int or sequence < 1:
            raise ConversationEventAppendResponseError("conversation event append result does not match its event")
        try:
            status = AppendStatus(item["status"])
        except ValueError:
            raise ConversationEventAppendResponseError("invalid conversation event append status") from None
        decoded.append(AppendResult(event.event_id, sequence, status))
    return tuple(decoded)
