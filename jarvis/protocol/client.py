from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
import io
import json
from typing import Any, Callable

import aiohttp

from jarvis.domain.v2 import PROTOCOL_VERSION, ProtocolEnvelope, new_id
from jarvis.protocol.scene_wire import MAX_SCENE_RESPONSE_BYTES  # module léger : ni aiohttp.web, ni domaine de scène
from jarvis.protocol.strict_json import loads_strict_json
from jarvis.v2_config import validate_loopback_host
from jarvis.domain.conversation_event_ingest import decode_append_results, encode_conversation_event_batch
from jarvis.domain.conversation_event_query import (
    MAX_WAIT_MS, check_event_id, decode_event_page, decode_event_response, decode_summary_page,
)
from jarvis.domain.conversation_event_store import (
    DEFAULT_EVENT_PAGE_LIMIT, DEFAULT_SUMMARY_PAGE_LIMIT, AppendResult, ConversationEventPage,
    ConversationEventSummaryPage, StoredConversationEvent,
)
from jarvis.domain.conversation_event_search import ConversationEventSearchPage, SearchQuery, decode_search_page
from jarvis.domain.conversation_events import ConversationEvent, ConversationVisibility
from jarvis.domain.conversation_transcript import TranscriptMode
from jarvis.domain.voice_admission import VoiceTurnAdmissionAcceptance, VoiceTurnAdmissionRequest
from jarvis.domain.v2 import AddressingDecision
from jarvis.domain.live_lifecycle import LiveCloseEvidence, LiveLifecycleState, LiveSessionRecord


class CoreProtocolError(RuntimeError):
    """Erreur rendue par Core, avec de quoi décider quoi faire.

    Hérite de `RuntimeError` pour ne rien casser des appelants existants, qui
    l'attrapaient sous cette forme. Le statut et le code sont exposés parce que
    la surface doit distinguer des situations qui n'appellent pas la même
    conduite : 404 (conversation inconnue) est définitif, 503 (`core_stopping`)
    est transitoire et rejouable avec la même corrélation.
    """

    __slots__ = ("status", "code", "message", "details")

    def __init__(self, status: int, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(f"Core protocol error {status}: {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        #: Champs de `error` autres que `code` et `message` (par exemple
        #: `scene` et `store_code` d'une scène indisponible).
        self.details: dict[str, Any] = dict(details or {})


class LocalCoreClient:
    def __init__(self, *, host: str, port: int, token: str, session: aiohttp.ClientSession | None = None) -> None:
        self.host = validate_loopback_host(host)
        self.port = port
        self.base_url = f"http://{self.host}:{self.port}"
        self.token = token
        self._session = session
        self._owns_session = session is None

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "X-Jarvis-Protocol": str(PROTOCOL_VERSION)}

    async def _http(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        return self._session

    async def health(self) -> dict[str, Any]:
        session = await self._http()
        async with session.get(self.base_url + "/v1/health", headers=self.headers) as response:
            return await self._json(response)

    async def create_conversation(self, *, device_id: str = "windows-desktop") -> dict[str, Any]:
        session = await self._http()
        async with session.post(self.base_url + "/v1/conversations", headers=self.headers, json={"device_id": device_id}) as response:
            return await self._json(response)

    async def context(self, conversation_id: str) -> dict[str, Any]:
        session = await self._http()
        async with session.get(self.base_url + f"/v1/conversations/{conversation_id}/context", headers=self.headers) as response:
            return await self._json(response)

    async def submit_back_brain_task(self, conversation_id: str, *, source_correlation_id: str | None = None,
                                     scope: str = "admitted_work", session_id: str | None = None,
                                     delegation_id: str | None = None):
        from jarvis.domain.back_brain import BackBrainSubmission, BackBrainSubmitRequest
        value = BackBrainSubmitRequest(conversation_id, source_correlation_id, scope, session_id, delegation_id)
        session = await self._http()
        async with session.post(self.base_url + f"/v1/conversations/{conversation_id}/back-brain/tasks", headers=self.headers,
                                json=value.to_payload()) as response:
            return BackBrainSubmission.from_payload(await self._json(response))

    async def back_brain_task_status(self, conversation_id: str, job_id: str):
        from jarvis.domain.back_brain import BackBrainTaskSnapshot
        from jarvis.domain.speech_presentation import speech_id
        speech_id(conversation_id, "conversation_id")
        speech_id(job_id, "job_id")
        session = await self._http()
        async with session.get(self.base_url + f"/v1/conversations/{conversation_id}/back-brain/tasks/{job_id}", headers=self.headers) as response:
            return BackBrainTaskSnapshot.from_payload(await self._json(response)).to_payload()

    async def list_back_brain_tasks(self, conversation_id: str, *, limit: int = 32):
        from jarvis.domain.back_brain import BackBrainTaskList
        from jarvis.domain.speech_presentation import speech_id
        speech_id(conversation_id, "conversation_id")
        if type(limit) is not int or not 1 <= limit <= 32:
            raise ValueError("invalid back brain list limit")
        session = await self._http()
        async with session.get(self.base_url + f"/v1/conversations/{conversation_id}/back-brain/tasks", headers=self.headers, params={"limit": limit}) as response:
            return BackBrainTaskList.from_payload(await self._json(response)).to_payload()

    async def cancel_back_brain_task(self, conversation_id: str, job_id: str):
        from jarvis.domain.back_brain import BackBrainTaskSnapshot
        from jarvis.domain.speech_presentation import speech_id
        speech_id(conversation_id, "conversation_id")
        speech_id(job_id, "job_id")
        session = await self._http()
        async with session.post(self.base_url + f"/v1/conversations/{conversation_id}/back-brain/tasks/{job_id}/cancel", headers=self.headers,
                                json={"schema_version": 1}) as response:
            return BackBrainTaskSnapshot.from_payload(await self._json(response)).to_payload()

    async def speech_context(self, conversation_id: str) -> dict[str, Any]:
        session = await self._http()
        async with session.get(self.base_url + f"/v1/conversations/{conversation_id}/speech-context", headers=self.headers) as response:
            return await self._json(response)

    async def list_brain_outcomes(self, conversation_id: str, *, limit: int = 32) -> dict[str, Any]:
        session = await self._http()
        async with session.get(self.base_url + f"/v1/conversations/{conversation_id}/outcomes", headers=self.headers, params={"limit": str(limit)}) as response:
            return await self._json(response)

    async def get_brain_outcome(self, conversation_id: str, outcome_id: str) -> dict[str, Any]:
        session = await self._http()
        async with session.get(self.base_url + f"/v1/conversations/{conversation_id}/outcomes/{outcome_id}", headers=self.headers) as response:
            return await self._json(response)

    async def select_brain_outcome(self, conversation_id: str, outcome_id: str, *, selection_id: str) -> dict[str, Any]:
        session = await self._http()
        async with session.post(self.base_url + f"/v1/conversations/{conversation_id}/outcomes/{outcome_id}/select", headers=self.headers,
                                json={"selection_id": selection_id}) as response:
            return await self._json(response)

    async def bind_voice_session(self, conversation_id: str, session_id: str) -> dict[str, Any]:
        session = await self._http()
        async with session.post(self.base_url + f"/v1/conversations/{conversation_id}/voice/session", headers=self.headers,
                                json={"session_id": session_id}) as response:
            return await self._json(response)

    async def submit_voice_observations(self, conversation_id: str, session_id: str, events: list[dict]) -> dict[str, Any]:
        session = await self._http()
        async with session.post(self.base_url + f"/v1/conversations/{conversation_id}/voice/observations", headers=self.headers,
                                json={"session_id": session_id, "events": events}) as response:
            return await self._json(response)

    async def voice_snapshot(self, conversation_id: str) -> dict[str, Any]:
        session = await self._http()
        async with session.get(self.base_url + f"/v1/conversations/{conversation_id}/voice/snapshot", headers=self.headers) as response:
            return await self._json(response)

    async def admit_voice_turn(self, conversation_id: str, *, text: str, addressing: str,
                              session_id: str, canonical_turn_id: str, transcript_id: str,
                              transcript_revision: int, provider_item_id: str) -> VoiceTurnAdmissionAcceptance:
        """Admit canonical input without backend work; Core owns source identity."""
        request = VoiceTurnAdmissionRequest(conversation_id=conversation_id, text=text,
            addressing=AddressingDecision(addressing), session_id=session_id, canonical_turn_id=canonical_turn_id,
            transcript_id=transcript_id, transcript_revision=transcript_revision, provider_item_id=provider_item_id)
        session = await self._http()
        async with session.post(self.base_url + f"/v1/conversations/{conversation_id}/voice/admitted-turns",
                                headers=self.headers, json=request.to_payload()) as response:
            return VoiceTurnAdmissionAcceptance.from_payload(await self._json(response))

    async def register_voice_speech(self, conversation_id: str, correlation: dict, intended_text: str) -> dict[str, Any]:
        session = await self._http()
        async with session.post(self.base_url + f"/v1/conversations/{conversation_id}/voice/speech", headers=self.headers,
                                json={"correlation": correlation, "intended_text": intended_text}) as response:
            return await self._json(response)

    @staticmethod
    def _live_record(payload: dict[str, Any]) -> LiveSessionRecord | None:
        if not isinstance(payload, dict) or set(payload) != {"record"}:
            raise ValueError("invalid Live lifecycle response")
        return None if payload["record"] is None else LiveSessionRecord.from_payload(payload["record"])

    async def _live_post(self, path: str, payload: dict[str, object]) -> LiveSessionRecord:
        session = await self._http()
        async with session.post(self.base_url + path, headers=self.headers, json=payload) as response:
            record = self._live_record(await self._json(response))
        if record is None:
            raise ValueError("Live lifecycle mutation returned no record")
        return record

    async def reserve_live_session(self, session_id: str, owner_incarnation_id: str) -> LiveSessionRecord:
        return await self._live_post("/v1/live/sessions/reserve", {
            "session_id": session_id, "owner_incarnation_id": owner_incarnation_id,
        })

    async def live_session_status(self, session_id: str | None = None) -> LiveSessionRecord | None:
        session = await self._http()
        path = f"/v1/live/sessions/{session_id}" if session_id is not None else "/v1/live/sessions/current"
        async with session.get(self.base_url + path, headers=self.headers) as response:
            return self._live_record(await self._json(response))

    async def bind_live_session(self, session_id: str, owner_incarnation_id: str, owner_epoch: int,
                                expected_revision: int, provider_session_id: str,
                                ) -> LiveSessionRecord:
        return await self._live_post(f"/v1/live/sessions/{session_id}/bind", {
            "owner_incarnation_id": owner_incarnation_id, "owner_epoch": owner_epoch,
            "expected_revision": expected_revision, "provider_session_id": provider_session_id,
        })

    async def mark_live_session_start(self, session_id: str, owner_incarnation_id: str,
                                      owner_epoch: int, expected_revision: int) -> LiveSessionRecord:
        return await self._live_post(f"/v1/live/sessions/{session_id}/mark-start", {
            "owner_incarnation_id": owner_incarnation_id, "owner_epoch": owner_epoch,
            "expected_revision": expected_revision,
        })

    async def heartbeat_live_session(self, session_id: str, owner_incarnation_id: str, owner_epoch: int,
                                     expected_revision: int) -> LiveSessionRecord:
        return await self._live_post(f"/v1/live/sessions/{session_id}/heartbeat", {
            "owner_incarnation_id": owner_incarnation_id, "owner_epoch": owner_epoch,
            "expected_revision": expected_revision,
        })

    async def transition_live_session(self, session_id: str, owner_incarnation_id: str, owner_epoch: int,
                                      expected_revision: int, target: LiveLifecycleState,
                                      close_reason: str | None = None) -> LiveSessionRecord:
        return await self._live_post(f"/v1/live/sessions/{session_id}/transition", {
            "owner_incarnation_id": owner_incarnation_id, "owner_epoch": owner_epoch,
            "expected_revision": expected_revision, "target": target.value,
            "close_reason": close_reason,
        })

    async def update_live_session_usage(self, session_id: str, owner_incarnation_id: str, owner_epoch: int,
                                        expected_revision: int, active_seconds: float,
                                        provider_usage_seconds: float | None,
                                        provider_usage_final: bool = False) -> LiveSessionRecord:
        return await self._live_post(f"/v1/live/sessions/{session_id}/usage", {
            "owner_incarnation_id": owner_incarnation_id, "owner_epoch": owner_epoch,
            "expected_revision": expected_revision,
            "active_seconds": active_seconds, "provider_usage_seconds": provider_usage_seconds,
            "provider_usage_final": provider_usage_final,
        })

    async def claim_live_session_reap(self, session_id: str, reaper_incarnation_id: str,
                                      expected_revision: int) -> LiveSessionRecord:
        return await self._live_post(f"/v1/live/sessions/{session_id}/claim-reap", {
            "reaper_incarnation_id": reaper_incarnation_id,
            "expected_revision": expected_revision,
        })

    async def finalize_live_session(self, session_id: str, owner_incarnation_id: str, owner_epoch: int,
                                    expected_revision: int, provider_session_id: str | None,
                                    active_seconds: float, provider_usage_seconds: float | None,
                                    close_reason: str, close_evidence: LiveCloseEvidence) -> LiveSessionRecord:
        return await self._live_post(f"/v1/live/sessions/{session_id}/finalize", {
            "owner_incarnation_id": owner_incarnation_id, "owner_epoch": owner_epoch,
            "expected_revision": expected_revision,
            "provider_session_id": provider_session_id, "active_seconds": active_seconds,
            "provider_usage_seconds": provider_usage_seconds, "close_reason": close_reason,
            "close_evidence": close_evidence.value,
        })

    async def append_turn(self, conversation_id: str, *, kind: str, content: str, correlation_id: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        session = await self._http()
        payload = {"kind": kind, "content": content, "correlation_id": correlation_id or new_id(), "metadata": metadata or {}}
        async with session.post(self.base_url + f"/v1/conversations/{conversation_id}/turns", headers=self.headers, json=payload) as response:
            return await self._json(response)

    async def submit_brain_turn(self, conversation_id: str, *, content: str, correlation_id: str | None = None, source: str = "realtime", addressing: str = "addressed", provider_item_id: str | None = None, interrupted_speech_id: str | None = None) -> dict[str, Any]:
        """Soumettre un tour utilisateur complet faisant autorité au cerveau.

        Rend l'accusé (`turn_id`, `revision`, `duplicate`, ...) sans attendre le
        modèle fort : la suite du tour arrive par `events()`. Cet appel remplace
        `append_turn()` pour les tours routés vers le cerveau ; les appeler tous
        les deux persisterait le tour deux fois.

        `correlation_id` est la clé de rejeu : un appelant qui réessaie doit
        réutiliser la même valeur, sinon Core y verra deux tours distincts. La
        valeur générée par défaut ne convient donc qu'à une première tentative.
        La déduplication côté Core est en mémoire et ne survit pas à un
        redémarrage (Décision 29, détaillée dans le docstring du endpoint).

        `addressing` dit ce que la surface a cru du tour : `"addressed"` par
        défaut, `"uncertain"` quand elle n'a pas su si la phrase lui était
        adressée et laisse la question au cerveau (Décision 44). `"ambient"`
        n'est pas une valeur soumissible : Core la refuse.

        Erreurs : `CoreProtocolError` avec `status=404` pour une conversation
        inconnue (définitif) et `status=503`, `code="core_stopping"` pour un
        Core en cours d'arrêt (transitoire, rejouable à l'identique). Un rejeu
        reconnu n'est pas une erreur : il rend 200 avec `duplicate=true`.
        """

        session = await self._http()
        payload = {
            "content": content,
            "correlation_id": correlation_id or new_id(),
            "source": source,
            "addressing": addressing,
            "provider_item_id": provider_item_id,
            "interrupted_speech_id": interrupted_speech_id,
        }
        async with session.post(self.base_url + f"/v1/conversations/{conversation_id}/brain-turns", headers=self.headers, json=payload) as response:
            return await self._json(response)

    async def cancel_brain_turn(self, conversation_id: str, *, correlation_id: str) -> dict[str, Any]:
        """Abandonner la réponse d'un tour en vol, sans annuler son travail.

        Appelée quand l'utilisateur reprend la parole pendant que le cerveau
        réfléchit : la réponse orale de ce tour-là n'a plus lieu d'être, mais
        tout ce que le tour a lancé (jobs, sous-agents) continue et rendra son
        résultat par le chemin ordinaire.

        Rend `{"cancelled": bool, ...}`. `cancelled=false` n'est pas une erreur :
        le tour s'était déjà soldé entre-temps.
        """

        session = await self._http()
        async with session.post(self.base_url + f"/v1/conversations/{conversation_id}/brain-turns/cancel",
                                headers=self.headers,
                                json={"schema_version": 1, "correlation_id": correlation_id}) as response:
            return await self._json(response)

    async def call_tool(self, name: str, arguments: dict[str, object], *, conversation_id: str | None = None) -> dict[str, Any]:
        session = await self._http()
        payload = {"name": name, "arguments": arguments, "conversation_id": conversation_id}
        async with session.post(self.base_url + "/v1/tools/call", headers=self.headers, json=payload) as response:
            return await self._json(response)

    async def confirm_action(self, action_id: str, text: str) -> dict[str, Any]:
        session = await self._http()
        async with session.post(self.base_url + f"/v1/actions/{action_id}/confirmation", headers=self.headers, json={"text": text}) as response:
            return await self._json(response)

    async def ingest_work_observations(self, batch: dict[str, Any]) -> dict[str, Any]:
        """Remettre un lot d'observations de travail (`WorkObservationBatch.to_payload()`).

        `CoreProtocolError` avec `status=400` : lot refusé, le rejouer ne
        servirait à rien ; `status=401` : jeton périmé (Core redémarré).
        """

        session = await self._http()
        async with session.post(self.base_url + "/v1/work/observations", headers=self.headers, json=batch) as response:
            return await self._json(response)

    async def append_conversation_events(self, events: Sequence[ConversationEvent]) -> tuple[AppendResult, ...]:
        """Remettre 1 à 32 Conversation Events à Core (`POST /v1/conversation-events`).

        Le lot est encodé par le codec du contrat avant tout envoi : un
        événement invalide lève `ConversationEventError` sans appel réseau.
        Rend un `AppendResult` par événement, dans l'ordre (`appended`,
        `duplicate`, `conflict`). `CoreProtocolError` : `status=400` lot refusé
        (le rejouer ne sert à rien), `status=503` stockage indisponible (rejouer
        le même lot, mêmes identifiants et `occurred_at`, est sûr).
        """

        events = tuple(events)
        # A contract-valid batch can reach 4.2 MiB: sent as a stream, since
        # aiohttp warns (ResourceWarning) that a raw body above 1 MiB may block the loop.
        body = io.BytesIO(json.dumps(encode_conversation_event_batch(events)).encode("utf-8"))
        session = await self._http()
        async with session.post(self.base_url + "/v1/conversation-events", data=body,
                                headers={**self.headers, "Content-Type": "application/json"}) as response:
            return decode_append_results(await self._json(response), events)

    # -- Conversation Event query API (Slice 04) --------------------------------
    #
    # Typed reads of `GET /v1/conversation-events...` (contract:
    # `docs/conversation-events.md`, "Query and live API"). Responses are decoded
    # strictly (`conversation_event_query`): an answer out of contract raises
    # `ValueError`. `CoreProtocolError`: 400 invalid parameter (do not retry),
    # 401 token rotated, 503 `conversation_events_unavailable` (retry later).

    async def _get_json(self, path: str, params: dict[str, object], *,
                        timeout: aiohttp.ClientTimeout | None = None) -> dict[str, Any]:
        query = {name: (value.value if isinstance(value, ConversationVisibility) else str(value))
                 for name, value in params.items() if value is not None}
        session = await self._http()
        kwargs: dict[str, Any] = {"headers": self.headers, "params": query}
        if timeout is not None:
            kwargs["timeout"] = timeout
        async with session.get(self.base_url + path, **kwargs) as response:
            return await self._json(response)

    async def list_event_conversations(self, *, before_sequence: int | None = None,
                                       limit: int = DEFAULT_SUMMARY_PAGE_LIMIT) -> ConversationEventSummaryPage:
        """Conversations by most recent activity; next page with `before_sequence=page.next_cursor`."""
        return decode_summary_page(await self._get_json("/v1/conversation-events/conversations",
                                                        {"before_sequence": before_sequence, "limit": limit}))

    async def list_event_sessions(self, conversation_id: str, *, after_sequence: int = 0,
                                  limit: int = DEFAULT_SUMMARY_PAGE_LIMIT) -> ConversationEventSummaryPage:
        return decode_summary_page(await self._get_json("/v1/conversation-events/sessions", {
            "conversation_id": conversation_id, "after_sequence": after_sequence, "limit": limit}))

    async def list_conversation_events(self, conversation_id: str, *, after_sequence: int = 0,
                                       limit: int = DEFAULT_EVENT_PAGE_LIMIT,
                                       visibility: ConversationVisibility | None = None,
                                       wait_ms: int = 0) -> ConversationEventPage:
        """Events after `after_sequence`; resume with `after_sequence=page.next_cursor`.

        `wait_ms` > 0 long-polls (at most `MAX_WAIT_MS`): the request timeout is
        extended by that wait, so the session's 10 s total never cuts it short.
        """
        if type(wait_ms) is not int or not 0 <= wait_ms <= MAX_WAIT_MS:
            raise ValueError(f"wait_ms must be an integer between 0 and {MAX_WAIT_MS}")
        timeout = aiohttp.ClientTimeout(total=10 + wait_ms / 1000) if wait_ms else None
        payload = await self._get_json("/v1/conversation-events", {
            "conversation_id": conversation_id, "after_sequence": after_sequence, "limit": limit,
            "visibility": visibility, "wait_ms": wait_ms or None}, timeout=timeout)
        return decode_event_page(payload, after_sequence=after_sequence)

    async def lookup_conversation_events(self, field: str, value: str, *, conversation_id: str | None = None,
                                         after_sequence: int = 0, limit: int = DEFAULT_EVENT_PAGE_LIMIT,
                                         visibility: ConversationVisibility | None = None) -> ConversationEventPage:
        payload = await self._get_json("/v1/conversation-events/lookup", {
            "field": field, "value": value, "conversation_id": conversation_id, "after_sequence": after_sequence,
            "limit": limit, "visibility": visibility})
        return decode_event_page(payload, after_sequence=after_sequence)

    async def get_conversation_event(self, event_id: str) -> StoredConversationEvent | None:
        """The stored event, or None (404 `conversation_event_not_found`: absent or unreadable)."""
        check_event_id(event_id)
        try:
            payload = await self._get_json(f"/v1/conversation-events/events/{event_id}", {})
        except CoreProtocolError as exc:
            if exc.status == 404 and exc.code == "conversation_event_not_found":
                return None
            raise
        return decode_event_response(payload)

    # -- Slice 06: transcript, export, search -----------------------------------

    async def stream_conversation_transcript(self, conversation_id: str, *,
                                             mode: TranscriptMode = TranscriptMode.PLAIN, utc_offset_minutes: int = 0,
                                             read_timeout_s: float = 60.0) -> AsyncIterator[bytes]:
        """Readable transcript as UTF-8 byte chunks (never held whole here).

        Errors before the first byte raise `CoreProtocolError` (413
        `transcript_too_large`, 429 `projection_busy`, 503...).
        """
        session = await self._http()
        async with session.get(self.base_url + "/v1/conversation-events/transcript", headers=self.headers,
                               params={"conversation_id": conversation_id, "mode": TranscriptMode(mode).value,
                                       "utc_offset_minutes": str(utc_offset_minutes)},
                               timeout=aiohttp.ClientTimeout(total=None, sock_read=read_timeout_s)) as response:
            if response.status >= 400:
                await self._json(response)
            if response.content_type != "text/plain":
                raise ValueError("transcript answer must be text/plain")
            async for chunk in response.content.iter_chunked(64 * 1024):
                yield chunk

    async def get_conversation_transcript(self, conversation_id: str, *,
                                          mode: TranscriptMode = TranscriptMode.PLAIN,
                                          utc_offset_minutes: int = 0) -> str:
        """Whole transcript text (tests, tools). The Control Center relays the stream instead."""
        parts = [chunk async for chunk in self.stream_conversation_transcript(
            conversation_id, mode=mode, utc_offset_minutes=utc_offset_minutes)]
        return b"".join(parts).decode("utf-8")

    async def export_conversation_events(self, conversation_id: str, *,
                                         read_timeout_s: float = 30.0) -> AsyncIterator[bytes]:
        """Stream the JSONL export as byte chunks (header first, trailer last).

        Errors before the first byte raise `CoreProtocolError`. A stream Core
        closes early raises `aiohttp.ClientPayloadError`; what was received then
        has no trailer (`read_export(...).complete` is False).
        """
        session = await self._http()
        async with session.get(self.base_url + "/v1/conversation-events/export", headers=self.headers,
                               params={"conversation_id": conversation_id},
                               timeout=aiohttp.ClientTimeout(total=None, sock_read=read_timeout_s)) as response:
            if response.status >= 400:
                await self._json(response)
            async for chunk in response.content.iter_chunked(64 * 1024):
                yield chunk

    async def search_conversation_events(self, query: str | SearchQuery, *, conversation_id: str | None = None,
                                         before_sequence: int | None = None, limit: int | None = None,
                                         visibility: ConversationVisibility | None = None,
                                         timeout_s: float = 30.0) -> ConversationEventSearchPage:
        """Newest-first hits; continue with `before_sequence=page.next_cursor` while `has_more`."""
        text = query.text if isinstance(query, SearchQuery) else SearchQuery.parse(query).text
        payload = await self._get_json("/v1/conversation-events/search", {
            "q": text, "conversation_id": conversation_id, "before_sequence": before_sequence, "limit": limit,
            "visibility": visibility}, timeout=aiohttp.ClientTimeout(total=timeout_s))
        return decode_search_page(payload)

    async def work_snapshot(self) -> dict[str, Any]:
        session = await self._http()
        async with session.get(self.base_url + "/v1/work/snapshot", headers=self.headers) as response:
            return await self._json(response)

    # ------------------------------------------------------------ scène (Slice 03)

    async def scene_snapshot(self) -> dict[str, Any]:
        """`GET /v1/scene/snapshot` : `{scene_id, epoch, revision, snapshot}` (lecture bornée)."""

        session = await self._http()
        async with session.get(self.base_url + "/v1/scene/snapshot", headers=self.headers) as response:
            return await self._bounded_json(response)

    async def scene_patches(self, *, scene_id: str, epoch: str, after: int, wait_s: float, timeout_s: float) -> dict[str, Any]:
        """`GET /v1/scene/patches` : long-poll ; `timeout_s` borne la requête entière, attente comprise."""

        session = await self._http()
        params = {"scene_id": scene_id, "epoch": epoch, "after": str(after), "wait_s": f"{wait_s:.6f}"}
        async with session.get(
            self.base_url + "/v1/scene/patches", headers=self.headers, params=params,
            timeout=aiohttp.ClientTimeout(total=timeout_s),
        ) as response:
            return await self._bounded_json(response)

    async def scene_command(
        self, command: dict[str, Any], *, connect_timeout_s: float | None = None, read_timeout_s: float | None = None,
    ) -> dict[str, Any]:
        """`POST /v1/scene/commands` : une `SceneCommand.to_payload()` ; refus du domaine = 200.

        `connect_timeout_s` borne l'obtention de la connexion (attente du pool
        comprise) : son dépassement lève `aiohttp.ConnectionTimeoutError`, la
        requête n'est **pas partie**. `read_timeout_s` borne l'attente de la
        réponse une fois la requête envoyée (`aiohttp.SocketTimeoutError` :
        issue inconnue).
        """

        session = await self._http()
        options: dict[str, Any] = {}
        if connect_timeout_s is not None or read_timeout_s is not None:
            options["timeout"] = aiohttp.ClientTimeout(total=None, connect=connect_timeout_s, sock_read=read_timeout_s)
        async with session.post(self.base_url + "/v1/scene/commands", headers=self.headers, json=command, **options) as response:
            return await self._bounded_json(response)

    async def scene_capture(self, *, connect_timeout_s: float, read_timeout_s: float) -> dict[str, Any]:
        """`POST /v1/scene/captures` (Slice 09, partie 2) : demande du cerveau, rendue quand la page a envoyé le PNG.

        Refus en `CoreProtocolError` : 409 `capture_busy`, 504 `no_visible_page`,
        503 `capture_unavailable` / `scene_unavailable` / `capture_cancelled`.
        """

        session = await self._http()
        timeout = aiohttp.ClientTimeout(total=None, connect=connect_timeout_s, sock_read=read_timeout_s)
        body = {"schema_version": 1, "actor": "brain"}
        async with session.post(self.base_url + "/v1/scene/captures", headers=self.headers, json=body, timeout=timeout) as response:
            return await self._bounded_json(response, 16_384)

    async def scene_capture_upload(
        self, capture_id: str, png: bytes, *, connect_timeout_s: float, read_timeout_s: float,
    ) -> dict[str, Any]:
        """`PUT /v1/scene/captures/<id>` : le PNG rendu par la page meneuse, relayé par le Control Center."""

        session = await self._http()
        timeout = aiohttp.ClientTimeout(total=None, connect=connect_timeout_s, sock_read=read_timeout_s)
        headers = {**self.headers, "Content-Type": "image/png"}
        # Flux plutôt qu'octets bruts : aiohttp avertit (et peut bloquer la boucle) au-delà de 1 MiB.
        async with session.put(self.base_url + f"/v1/scene/captures/{capture_id}", headers=headers, data=io.BytesIO(png),
                               timeout=timeout) as response:
            return await self._bounded_json(response, 16_384)

    async def cancel_work(
        self, *, source: str, external_id: str, connect_timeout_s: float | None = None, read_timeout_s: float | None = None,
    ) -> dict[str, Any]:
        """`POST /v1/work/cancel` (Slice 08) : arrêter le travail d'une étoile, jobs Core seulement.

        409 `not_cancellable` pour toute autre source, 404 pour un job inconnu
        (`CoreProtocolError`). Délais comme `scene_command` : connexion non
        obtenue = requête **non partie**.
        """

        session = await self._http()
        options: dict[str, Any] = {}
        if connect_timeout_s is not None or read_timeout_s is not None:
            options["timeout"] = aiohttp.ClientTimeout(total=None, connect=connect_timeout_s, sock_read=read_timeout_s)
        body = {"schema_version": 1, "source": source, "external_id": external_id}
        async with session.post(self.base_url + "/v1/work/cancel", headers=self.headers, json=body, **options) as response:
            return await self._bounded_json(response)

    @staticmethod
    async def _bounded_json(response: aiohttp.ClientResponse, limit: int = MAX_SCENE_RESPONSE_BYTES) -> dict[str, Any]:
        """Lire au plus `limit` octets puis décoder ; au-delà ou illisible : `ValueError`.

        Une erreur HTTP devient `CoreProtocolError` avec ses `details`, même
        quand le corps n'est pas du JSON (le code est alors `http_<statut>`).
        """

        if response.content_length is not None and response.content_length > limit:
            raise ValueError(f"Core response exceeds {limit} bytes")
        raw = bytearray()
        async for chunk in response.content.iter_chunked(65_536):
            raw.extend(chunk)
            if len(raw) > limit:
                raise ValueError(f"Core response exceeds {limit} bytes")
        try:
            data = loads_strict_json(bytes(raw), invalid_message="Core response is not JSON")
        except ValueError as exc:
            if response.status >= 400:
                raise CoreProtocolError(response.status, f"http_{response.status}", bytes(raw[:160]).decode("utf-8", "replace")) from exc
            raise
        if response.status >= 400:
            error = data.get("error") if isinstance(data, dict) else None
            error = error if isinstance(error, dict) else {}
            details = {key: value for key, value in error.items() if key not in ("code", "message")}
            raise CoreProtocolError(response.status, str(error.get("code", "unknown")), str(error.get("message", "")), details=details)
        if not isinstance(data, dict):
            raise TypeError("Core response must be a JSON object")
        return data

    async def events(self, *, on_connected: Callable[[], None] | None = None) -> AsyncIterator[ProtocolEnvelope]:
        session = await self._http()
        async with session.ws_connect(self.base_url.replace("http://", "ws://") + "/v1/events", headers=self.headers, heartbeat=20) as ws:
            async for message in ws:
                if message.type == aiohttp.WSMsgType.TEXT:
                    data = message.json()
                    if data.get("message_type") == "connected":
                        if on_connected is not None:
                            on_connected()
                        continue
                    if data.get("message_type") == "ack":
                        continue
                    yield ProtocolEnvelope(message_type=data["message_type"], payload=data.get("payload") or {}, correlation_id=data.get("correlation_id") or new_id(), protocol_version=int(data.get("protocol_version", PROTOCOL_VERSION)), device_id=data.get("device_id") or "windows-desktop", conversation_id=data.get("conversation_id"))
                elif message.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                    break

    async def close(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    @staticmethod
    async def _json(response: aiohttp.ClientResponse) -> dict[str, Any]:
        if response.status >= 400:
            try:
                data = await response.json()
            except (aiohttp.ContentTypeError, ValueError):
                # aiohttp itself answers some failures in text/plain (413 body
                # too large, 405...): still a Core refusal with its status.
                raise CoreProtocolError(response.status, "http_error", response.reason or "") from None
            if not isinstance(data, dict):
                raise CoreProtocolError(response.status, "http_error", response.reason or "")
            error = data.get("error") or {}
            raise CoreProtocolError(response.status, str(error.get("code", "unknown")), str(error.get("message", "")))
        return await response.json()
