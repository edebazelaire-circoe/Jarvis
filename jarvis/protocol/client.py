from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
import io
import json
from typing import Any, Callable
from urllib.parse import quote

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


#: Préfixes que `LocalCoreClient.forward_json` accepte de relayer tels quels
#: pour le Control Center. `/v1/mcp/tools*` n'y est pas : l'exécution d'un
#: outil n'est jamais relayée par le Control Center. Contexts, captures,
#: Artifacts et activité (session-context-recording, Slice 09) : ajoutés
#: **délibérément** pour l'interface et `jarvis-capture` (`capture_routes.py`).
#: Inspection du workspace (board-memory-workspace-inspector, Slice 04,
#: `workspace_routes.py`) : lecture seule, pour l'interface et `jarvis-workspace`.
#: Catalogue des prefabs (jarvis-scene-window-prefab-foundation, Slice 03,
#: `prefab_routes.py`) : pour le runtime des cadres et la bibliothèque.
#: Presentations du Studio (jarvis-interactive-presentation-studio, Slice 05, `presentation_studio_relay.py`) : le
#: relais n'en expose qu'une partie (lectures + `.../edits`, acteur forcé à `user`) ; la liste vit dans le relais.
FORWARDABLE_PREFIXES = ("/v1/boards", "/v1/sessions", "/v1/mcp/plugins", "/v1/mcp/oauth/callback",
                        "/v1/contexts", "/v1/captures", "/v1/artifacts", "/v1/activity", "/v1/workspace/",
                        "/v1/prefabs", "/v1/presentation-studio/presentations", "/v1/presentation-studio/playback",
                        "/v1/presentation-studio/authoring", "/v1/presentation-studio/templates",
                        "/v1/presentation-studio/engine",  # vue du moteur, lecture seule (remotion-integration S20)
                        "/v1/memory/", "/v1/remotion/",
                        # Carte Remotion du Control Center (jarvis-remotion-presentation-integration, Slice 11) : l'état de la capacité et le
                        # Studio optionnel ; le relais (`remotion_studio_relay.py`) n'appelle que six adresses, jamais l'installation.
                        "/v1/local-capabilities/remotion")
#: Seule route relayée en octets (`forward_bytes`) : le payload d'un Artifact, pour l'interface.
PAYLOAD_ROUTE_SUFFIX = "/payload"
#: Paramètres de requête relayés : un mapping, ou des paires (un paramètre répété garde chaque valeur).
QueryParams = Mapping[str, str] | Sequence[tuple[str, str]]
#: Une edition de source attend la rafale (secondes), la publication et le rapport de montage de l'hote (8 s) : la
#: reponse de Core peut venir bien apres 10 s ; au-dela, la requete est abandonnee et le resultat reste dans `/reloads`.
SOURCE_EDIT_TIMEOUT_S = 40.0
STUDIO_PREFIX = "/v1/presentation-studio/presentations"  # = un élément de FORWARDABLE_PREFIXES (testé)
PLAYBACK_PREFIX = "/v1/presentation-studio/playback"  # lecture (Slice 12) : aussi dans FORWARDABLE_PREFIXES
TEMPLATES_PREFIX = "/v1/presentation-studio/templates"  # modeles reutilisables (Slice 20) : aussi dans FORWARDABLE_PREFIXES
AUTHORING_PREFIX = "/v1/presentation-studio/authoring"  # planificateur d'ecriture (Slice 11) : aussi dans FORWARDABLE_PREFIXES
#: Plus grande réponse binaire relayée : la borne par réponse de Core (`MAX_PAYLOAD_CHUNK_BYTES`).
MAX_FORWARDED_PAYLOAD_BYTES = 8 * 1024 * 1024
#: En-têtes de la réponse binaire de Core rendus tels quels par le relais.
FORWARDED_PAYLOAD_HEADERS = ("Content-Type", "Content-Range", "Accept-Ranges", "Content-Disposition",
                             "Cache-Control", "X-Content-Type-Options")


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

    async def submit_brain_turn(self, conversation_id: str, *, content: str, correlation_id: str | None = None, source: str = "realtime", addressing: str = "addressed", provider_item_id: str | None = None, interrupted_speech_id: str | None = None, presentation_context: Mapping[str, Any] | None = None) -> dict[str, Any]:
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

        `presentation_context` (handoff presentation-interaction-mode, Slice 05,
        P4) : la projection d'un tour adressé en PRESENTATION
        (`AddressedTurnContext.to_brain_context()`). La clé n'entre dans le corps
        **que si elle est donnée** : sans elle, le corps est celui d'avant, octet
        pour octet. Core la valide (400 hors forme), la remet au backend de ce
        tour seulement, et ne la persiste pas ; un rejeu reconnu comme doublon
        ne la réapplique pas.
        """

        session = await self._http()
        payload: dict[str, Any] = {
            "content": content,
            "correlation_id": correlation_id or new_id(),
            "source": source,
            "addressing": addressing,
            "provider_item_id": provider_item_id,
            "interrupted_speech_id": interrupted_speech_id,
        }
        if presentation_context is not None:
            payload["presentation_context"] = dict(presentation_context)
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

    # --------------------------------------------- mode d'interaction (Slice 02)

    async def interaction_mode(self) -> dict[str, Any]:
        """`GET /v1/interaction-mode` : mode effectif, révision, modes annoncés."""

        session = await self._http()
        async with session.get(self.base_url + "/v1/interaction-mode", headers=self.headers) as response:
            return await self._json(response)

    async def set_interaction_mode(self, mode: str, *, source: str | None = None) -> dict[str, Any]:
        """`POST /v1/interaction-mode` : demander un mode à Core.

        Un refus arrive en `CoreProtocolError` avec le code stable de Core
        (`interaction_mode_not_implemented`, `interaction_mode_unknown`) :
        l'appelant le relaie tel quel, il ne le retraduit pas.
        """

        session = await self._http()
        body: dict[str, Any] = {"mode": mode}
        if source is not None:
            body["source"] = source
        async with session.post(self.base_url + "/v1/interaction-mode", headers=self.headers, json=body) as response:
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

    async def publish_ui_intent(self, intent: dict[str, Any], *, connect_timeout_s: float | None = None,
                                read_timeout_s: float | None = None) -> dict[str, Any]:
        """`POST /v1/ui-intents` (Tool Brain, Slice 4) : `{accepted, intent_id, ...}` ou, refusée, `{accepted: false, code}`.

        Un refus attribué (409 `no_turn_in_flight`, `too_many_intents`) est rendu comme une réponse, pas levé :
        l'appelant le dit au modèle. Toute autre erreur HTTP lève `CoreProtocolError`.
        """

        session = await self._http()
        options: dict[str, Any] = {}
        if connect_timeout_s is not None or read_timeout_s is not None:
            options["timeout"] = aiohttp.ClientTimeout(total=None, connect=connect_timeout_s, sock_read=read_timeout_s)
        async with session.post(self.base_url + "/v1/ui-intents", headers=self.headers,
                                json={"schema_version": 1, "intent": intent}, **options) as response:
            if response.status == 409:
                return await self._bounded_json_any(response)
            return await self._bounded_json(response)

    @staticmethod
    async def _bounded_json_any(response: aiohttp.ClientResponse, limit: int = 65_536) -> dict[str, Any]:
        """Corps JSON d'un refus attribué (statut ignoré) ; illisible -> `ValueError`."""

        raw = await response.content.read(limit + 1)
        if len(raw) > limit:
            raise ValueError(f"Core response exceeds {limit} bytes")
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError("Core refusal must be a JSON object")
        return body

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

    # --------------------------------------------- Boards (handoff board-session, Slice 02)
    # Refus en `CoreProtocolError` avec le code stable de `BoardErrorCode`
    # (`board_not_found` 404, `board_archived` / `board_is_active` 409, ...).

    async def list_boards(self, *, include_archived: bool = False) -> dict[str, Any]:
        """`GET /v1/boards` : `{boards: [...], active_board_id}`."""

        session = await self._http()
        params = {"include_archived": "true"} if include_archived else None
        async with session.get(self.base_url + "/v1/boards", headers=self.headers, params=params) as response:
            return await self._json(response)

    async def active_board(self) -> dict[str, Any]:
        """`GET /v1/boards/active` : `{board, active: true}`."""

        session = await self._http()
        async with session.get(self.base_url + "/v1/boards/active", headers=self.headers) as response:
            return await self._json(response)

    async def get_board(self, board_id: str) -> dict[str, Any]:
        session = await self._http()
        async with session.get(self.base_url + f"/v1/boards/{quote(board_id, safe='')}", headers=self.headers) as response:
            return await self._json(response)

    async def create_board(self, fields: dict[str, Any]) -> dict[str, Any]:
        session = await self._http()
        async with session.post(self.base_url + "/v1/boards", headers=self.headers, json=fields) as response:
            return await self._json(response)

    async def update_board(self, board_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        session = await self._http()
        async with session.patch(self.base_url + f"/v1/boards/{quote(board_id, safe='')}", headers=self.headers,
                                 json=fields) as response:
            return await self._json(response)

    async def archive_board(self, board_id: str) -> dict[str, Any]:
        session = await self._http()
        async with session.post(self.base_url + f"/v1/boards/{quote(board_id, safe='')}/archive",
                                headers=self.headers) as response:
            return await self._json(response)

    async def current_session(self) -> dict[str, Any]:
        """`GET /v1/sessions/current` : `{session, binding}` (Slice 03).

        Un Core antérieur aux Sessions répond 404 `http_error` (route absente) :
        c'est à l'appelant d'y voir « non pris en charge ».
        """

        session = await self._http()
        async with session.get(self.base_url + "/v1/sessions/current", headers=self.headers) as response:
            return await self._json(response)

    async def list_sessions(self, *, limit: int | None = None) -> dict[str, Any]:
        """`GET /v1/sessions[?limit=N]` : `{sessions: [...]}`, la plus récente d'abord."""

        session = await self._http()
        params = {"limit": str(limit)} if limit is not None else None
        async with session.get(self.base_url + "/v1/sessions", headers=self.headers, params=params) as response:
            return await self._json(response)

    async def new_session(self, *, expected_session_id: str | None = None,
                          timeout_s: float | None = None) -> dict[str, Any]:
        """`POST /v1/sessions/new` : `{session, binding, closed_session}` ; 409 `session_closed` si la Session attendue est close.

        `timeout_s` remplace le délai de la session HTTP (10 s) : la transaction
        de Core attend l'hôte des cerveaux (`CORE_TRANSITION_TIMEOUT_S`).
        """

        session = await self._http()
        body = {} if expected_session_id is None else {"expected_session_id": expected_session_id}
        options: dict[str, Any] = {}
        if timeout_s is not None:
            options["timeout"] = aiohttp.ClientTimeout(total=timeout_s)
        async with session.post(self.base_url + "/v1/sessions/new", headers=self.headers, json=body,
                                **options) as response:
            return await self._json(response)

    async def switch_board(self, board_id: str) -> dict[str, Any]:
        """`POST /v1/boards/switch` `{board_id}` : `{session, binding, board, previous_board_id, changed}` (Slice 04b)."""

        session = await self._http()
        async with session.post(self.base_url + "/v1/boards/switch", headers=self.headers,
                                json={"board_id": board_id}) as response:
            return await self._json(response)

    # Presentations du Studio (jarvis-interactive-presentation-studio, Slice 02) : accès typé à
    # `/v1/presentation-studio/presentations*` (`presentation_studio_routes.py`). Un refus de Core
    # lève `CoreProtocolError` avec son statut et son code `presentation_studio_*` ; jamais relayé tel quel.

    async def _studio(self, method: str, suffix: str, *, body: Any = None,
                      params: Mapping[str, str] | None = None) -> dict[str, Any]:
        session = await self._http()
        options: dict[str, Any] = {} if body is None else {"json": body}
        async with session.request(method, f"{self.base_url}{STUDIO_PREFIX}{suffix}", headers=self.headers,
                                   params=params, **options) as response:
            return await self._json(response)

    async def presentation_studio_list(self, *, limit: int | None = None) -> dict[str, Any]:
        """`GET .../presentations` : `{presentations: [résumé], problems: [{presentation_id, code, message}]}`."""

        return await self._studio("GET", "", params=None if limit is None else {"limit": str(limit)})

    async def presentation_studio_create(self, title: str) -> dict[str, Any]:
        """`POST .../presentations` `{title}` : `{presentation, variants}` (variante n° 1 active)."""

        return await self._studio("POST", "", body={"title": title})

    async def presentation_studio_get(self, presentation_id: str) -> dict[str, Any]:
        return await self._studio("GET", f"/{quote(presentation_id, safe='')}")

    async def presentation_studio_save(self, presentation_id: str, update: Mapping[str, Any]) -> dict[str, Any]:
        """`PUT .../presentations/{id}` `{expected_revision, title, active_variant_id, resources}` : le document `presentation`."""

        return await self._studio("PUT", f"/{quote(presentation_id, safe='')}", body=dict(update))

    async def presentation_studio_variant(self, presentation_id: str, variant_id: str) -> dict[str, Any]:
        return await self._studio("GET", f"/{quote(presentation_id, safe='')}/variants/{quote(variant_id, safe='')}")

    async def presentation_studio_save_variant(self, presentation_id: str, variant_id: str,
                                               update: Mapping[str, Any]) -> dict[str, Any]:
        """`PUT .../variants/{id}` `{expected_revision, title, scenes, art_direction_id, score_id}` : le document `variant`."""

        return await self._studio("PUT", f"/{quote(presentation_id, safe='')}/variants/{quote(variant_id, safe='')}",
                                  body=dict(update))

    async def presentation_studio_scene_controls(self, presentation_id: str, variant_id: str,
                                                 scene_id: str) -> dict[str, Any]:
        """`GET .../variants/{id}/scenes/{scene_id}/controls` : ce qui s'édite sur la scène (contrôles résolus, ancres, budget)."""

        return await self._studio(
            "GET", f"/{quote(presentation_id, safe='')}/variants/{quote(variant_id, safe='')}"
                   f"/scenes/{quote(scene_id, safe='')}/controls")

    async def presentation_studio_art_direction(self, presentation_id: str, variant_id: str) -> dict[str, Any]:
        """`GET .../variants/{id}/art-direction` (Slice 09) : `{art_direction}`. 404 `presentation_studio_unknown_art_direction` s'il n'y en a pas."""

        return await self._studio("GET", self._art_direction_suffix(presentation_id, variant_id))

    async def presentation_studio_create_art_direction(self, presentation_id: str, variant_id: str,
                                                       body: Mapping[str, Any]) -> dict[str, Any]:
        """`POST .../art-direction` `{expected_variant_revision, profile}` : la variante reçoit `art_direction_id`."""

        return await self._studio("POST", self._art_direction_suffix(presentation_id, variant_id), body=dict(body))

    async def presentation_studio_save_art_direction(self, presentation_id: str, variant_id: str,
                                                     body: Mapping[str, Any]) -> dict[str, Any]:
        """`PUT .../art-direction` `{expected_revision, profile}` : remplacement, `stale_revision` si périmé."""

        return await self._studio("PUT", self._art_direction_suffix(presentation_id, variant_id), body=dict(body))

    async def presentation_studio_fallback_art_direction(self, presentation_id: str, variant_id: str,
                                                         body: Mapping[str, Any]) -> dict[str, Any]:
        """`POST .../art-direction/fallback` `{expected_variant_revision, seed_context?}` : crée la DA générée de repli."""

        return await self._studio("POST", self._art_direction_suffix(presentation_id, variant_id) + "/fallback",
                                  body=dict(body))

    async def presentation_studio_art_direction_candidates(self, presentation_id: str, variant_id: str,
                                                           body: Mapping[str, Any]) -> dict[str, Any]:
        """`POST .../art-direction/candidates` `{count, seed_context?}` : `{base, base_profile, candidates}`, calculé, rien d'écrit."""

        return await self._studio("POST", self._art_direction_suffix(presentation_id, variant_id) + "/candidates",
                                  body=dict(body))

    @staticmethod
    def _art_direction_suffix(presentation_id: str, variant_id: str) -> str:
        return f"/{quote(presentation_id, safe='')}/variants/{quote(variant_id, safe='')}/art-direction"

    async def presentation_studio_score(self, presentation_id: str, variant_id: str) -> dict[str, Any]:
        """`GET .../variants/{id}/score` (Slice 10) : `{score, problems}`. 404 `presentation_studio_unknown_score` si la variante n'en a pas."""

        return await self._studio("GET", self._score_suffix(presentation_id, variant_id))

    async def presentation_studio_create_score(self, presentation_id: str, variant_id: str,
                                               body: Mapping[str, Any]) -> dict[str, Any]:
        """`POST .../variants/{id}/score` `{expected_variant_revision, start_item_id, items, cues, sequences, recovery_points}`."""

        return await self._studio("POST", self._score_suffix(presentation_id, variant_id), body=dict(body))

    async def presentation_studio_save_score(self, presentation_id: str, variant_id: str,
                                             body: Mapping[str, Any]) -> dict[str, Any]:
        """`PUT .../variants/{id}/score` `{expected_revision, ...contenu}` : remplacement, `stale_revision` si périmé."""

        return await self._studio("PUT", self._score_suffix(presentation_id, variant_id), body=dict(body))

    @staticmethod
    def _score_suffix(presentation_id: str, variant_id: str) -> str:
        return f"/{quote(presentation_id, safe='')}/variants/{quote(variant_id, safe='')}/score"
    async def presentation_studio_suggest_controls(self, presentation_id: str, variant_id: str,
                                                   scene_id: str) -> dict[str, Any]:
        """`GET .../scenes/{scene_id}/control-suggestions` : contrôles proposés (rien n'est écrit) et l'opération `apply` prête."""

        return await self._studio(
            "GET", f"/{quote(presentation_id, safe='')}/variants/{quote(variant_id, safe='')}"
                   f"/scenes/{quote(scene_id, safe='')}/control-suggestions")

    async def presentation_studio_edit(self, presentation_id: str, variant_id: str,
                                       request: Mapping[str, Any]) -> dict[str, Any]:
        """`POST .../variants/{id}/edits` `{actor, mode, basis, ops}` : le résultat d'édition, **tel que Core le rend pour
        les trois issues** (`applied`, `refused`, `stale` : le statut HTTP est dans le résultat, `status` dit laquelle).
        Une enveloppe d'erreur nue (requête mal formée, variante inconnue, panne) lève `CoreProtocolError`."""

        session = await self._http()
        path = f"{STUDIO_PREFIX}/{quote(presentation_id, safe='')}/variants/{quote(variant_id, safe='')}/edits"
        async with session.request("POST", self.base_url + path, headers=self.headers, json=dict(request)) as response:
            if response.status in (400, 404, 409):
                try:
                    data = await response.json()
                except (aiohttp.ContentTypeError, ValueError):
                    data = None  # argued: not a result, `_json` raises the coded refusal below
                if isinstance(data, dict) and data.get("status") in ("refused", "stale"):
                    return data
            return await self._json(response)

    async def presentation_studio_source_edit(self, presentation_id: str, variant_id: str,
                                              request: Mapping[str, Any]) -> dict[str, Any]:
        """`POST .../variants/{id}/source-edits` `{actor, basis, scene_id, files, request_id?, allow_state_reset?}` : le
        resultat du rechargement a chaud, **tel que Core le rend pour toutes ses issues** (`reloaded`, `reloaded_state_reset`,
        `repinned`, `pending_mount`, `refused_validation`, `stale`, `rolled_back` : le statut HTTP est dans le resultat). Une
        enveloppe d'erreur nue (requete mal formee, scene inconnue, panne) leve `CoreProtocolError`."""

        session = await self._http()
        path = f"{STUDIO_PREFIX}/{quote(presentation_id, safe='')}/variants/{quote(variant_id, safe='')}/source-edits"
        async with session.request("POST", self.base_url + path, headers=self.headers, json=dict(request),
                                   timeout=aiohttp.ClientTimeout(total=SOURCE_EDIT_TIMEOUT_S)) as response:
            if response.status in (200, 202, 400, 409):
                try:
                    data = await response.json()
                except (aiohttp.ContentTypeError, ValueError):
                    data = None  # argued: not a result, `_json` raises the coded refusal below
                if isinstance(data, dict) and isinstance(data.get("status"), str) and "prefab" in data:
                    return data
            return await self._json(response)

    async def presentation_studio_reloads(self, presentation_id: str) -> dict[str, Any]:
        """`GET .../presentations/{id}/reloads` : `{reloads, pending, stats}` (derniers rechargements, scenes non confirmees)."""

        return await self._studio("GET", f"/{quote(presentation_id, safe='')}/reloads")

    #: Les issues d'un annuler/rétablir (Slice 08) : un résultat complet, pas une enveloppe d'erreur nue.
    _HISTORY_OUTCOMES = ("history_unavailable", "nothing_to_undo", "nothing_to_redo", "stale", "refused")

    async def presentation_studio_history(self, presentation_id: str, variant_id: str) -> dict[str, Any]:
        """`GET .../variants/{id}/history` (Slice 08) : ce qui s'annulerait/rétablirait, les bornes, ce qui a été évincé. Lecture seule."""

        return await self._studio("GET", f"/{quote(presentation_id, safe='')}/variants/{quote(variant_id, safe='')}/history")

    async def presentation_studio_undo(self, presentation_id: str, variant_id: str,
                                       request: Mapping[str, Any]) -> dict[str, Any]:
        """`POST .../variants/{id}/undo` `{actor, expected_entry_id?}` : le résultat d'historique, **tel que Core le rend pour
        toutes les issues** (`applied`, `history_unavailable`, `nothing_to_undo`, `stale`, `refused`) ; `status` dit laquelle.
        Une enveloppe d'erreur nue (requête mal formée, variante inconnue, panne) lève `CoreProtocolError`."""

        return await self._studio_history_step(presentation_id, variant_id, "undo", request)

    async def presentation_studio_redo(self, presentation_id: str, variant_id: str,
                                       request: Mapping[str, Any]) -> dict[str, Any]:
        """`POST .../variants/{id}/redo` : comme `presentation_studio_undo`, pour rétablir (`nothing_to_redo`)."""

        return await self._studio_history_step(presentation_id, variant_id, "redo", request)

    async def _studio_history_step(self, presentation_id: str, variant_id: str, verb: str,
                                   request: Mapping[str, Any]) -> dict[str, Any]:
        session = await self._http()
        path = f"{STUDIO_PREFIX}/{quote(presentation_id, safe='')}/variants/{quote(variant_id, safe='')}/{verb}"
        async with session.request("POST", self.base_url + path, headers=self.headers, json=dict(request)) as response:
            if response.status in (400, 404, 409):
                try:
                    data = await response.json()
                except (aiohttp.ContentTypeError, ValueError):
                    data = None  # argued: not a result, `_json` raises the coded refusal below
                if isinstance(data, dict) and data.get("status") in self._HISTORY_OUTCOMES:
                    return data
            return await self._json(response)

    # ---- planificateur d'écriture (Slice 11) : `presentation_studio_authoring_routes.py`

    async def presentation_studio_authoring_check(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """`POST .../authoring/check` `{actor?, brief, draft}` : `{status: "checked", ok, workflow, report}`. N'écrit rien ;
        un brouillon qui échoue la porte est `ok: false` (HTTP 200), l'enveloppe d'erreur nue (corps mal formé) lève `CoreProtocolError`."""

        return await self._studio_authoring("check", request)

    async def presentation_studio_authoring_assemble(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """`POST .../authoring/assemble` : le résultat **tel que Core le rend pour les deux issues** : `delivered` (201, ids,
        rapport, provenance) ou `refused` (400, le rapport complet et `error.code` `presentation_studio_draft_refused`; rien n'est écrit).
        Une enveloppe d'erreur nue (corps mal formé, panne de disque) lève `CoreProtocolError`."""

        return await self._studio_authoring("assemble", request)

    async def presentation_studio_authoring_finalize(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """`POST .../authoring/finalize` `{presentation_id, variant_id, actor?, activate?}` : `finalized` (200) or `refused` (400, the report),
        both returned as results. The `directed` gate on a stored variant (an exploratory candidate becomes the deck only through it)."""

        return await self._studio_authoring("finalize", request)

    async def presentation_studio_authoring_reconcile(self) -> dict[str, Any]:
        """`GET .../authoring/reconcile` : what an interrupted assembly can leave (`unreferenced_prefabs`, `unreadable_presentations`). Read only."""

        session = await self._http()
        async with session.get(f"{self.base_url}{AUTHORING_PREFIX}/reconcile", headers=self.headers) as response:
            return await self._json(response)

    async def _studio_authoring(self, verb: str, request: Mapping[str, Any]) -> dict[str, Any]:
        session = await self._http()
        async with session.request("POST", f"{self.base_url}{AUTHORING_PREFIX}/{verb}", headers=self.headers,
                                   json=dict(request)) as response:
            if response.status == 400:
                try:
                    data = await response.json()
                except (aiohttp.ContentTypeError, ValueError):
                    data = None  # argued: not a result, `_json` raises the coded refusal below
                if isinstance(data, dict) and data.get("status") == "refused":
                    return data
            return await self._json(response)

    # ---- lecture d'une Presentation (Slice 12) : état en mémoire de Core, jamais un document

    async def presentation_studio_playback_state(self) -> dict[str, Any]:
        """`GET .../playback` : `{state}` (« où en est-on », borné)."""

        return await self._playback("GET", "")

    async def presentation_studio_playback_armed(self) -> dict[str, Any]:
        """`GET .../playback/armed` : l'ensemble de cues armées (ids + phrases normalisées + run + génération + expiration).
        **Pour le suiveur de cues** (Slice 13) ; la lire renouvelle son autorité. Jamais relayée à la page."""

        return await self._playback("GET", "/armed")

    async def presentation_studio_playback(self, verb: str, request: Mapping[str, Any]) -> dict[str, Any]:
        """`POST .../playback/{verb}` : le résultat de la commande **tel que Core le rend pour ses trois issues**
        (`applied`, `refused`, `stage_failed` : `status` dit laquelle). Une enveloppe d'erreur nue lève `CoreProtocolError`."""

        session = await self._http()
        path = f"{PLAYBACK_PREFIX}/{quote(verb, safe='')}"
        async with session.request("POST", self.base_url + path, headers=self.headers, json=dict(request)) as response:
            if response.status in (409, 500):
                try:
                    data = await response.json()
                except (aiohttp.ContentTypeError, ValueError):
                    data = None  # argued: not a result, `_json` raises the coded refusal below
                if isinstance(data, dict) and data.get("status") in ("refused", "stage_failed"):
                    return data
            return await self._json(response)

    async def presentation_studio_report_cue(self, run_id: str, generation: int, cue_id: str) -> dict[str, Any]:
        """`POST .../cues/satisfied` : le rapport typé du suiveur (jamais de texte). Rend `fired` ou le refus **tel quel**
        (`stale_run`, `stale_generation`, `armed_set_expired`, `cue_not_armed`, `rate_limited` : `status: refused`, `code`)."""

        session = await self._http()
        body = {"run_id": run_id, "generation": generation, "cue_id": cue_id}
        async with session.request("POST", f"{self.base_url}/v1/presentation-studio/cues/satisfied",
                                   headers=self.headers, json=body) as response:
            if response.status in (409, 429):
                try:
                    data = await response.json()
                except (aiohttp.ContentTypeError, ValueError):
                    data = None  # argued: not a result, `_json` raises the coded refusal below
                if isinstance(data, dict) and data.get("status") == "refused":
                    return data
            return await self._json(response)

    async def _playback(self, method: str, suffix: str) -> dict[str, Any]:
        session = await self._http()
        async with session.request(method, f"{self.base_url}{PLAYBACK_PREFIX}{suffix}", headers=self.headers) as response:
            return await self._json(response)

    async def presentation_studio_validate(self, documents: Mapping[str, Any]) -> dict[str, Any]:
        """`POST .../validate` `{presentation, variants}` : `{ok, errors}` ; rien n'est écrit."""

        return await self._studio("POST", "/validate", body=dict(documents))

    # Graphe des variantes (Slice 16, `presentation_studio_variants_routes.py`) : un refus de Core lève `CoreProtocolError`
    # avec son code `presentation_studio_*` (dont `..._confirmation_required` / `..._confirmation_stale` / `..._active_variant_protected`).

    @staticmethod
    def _variant_path(presentation_id: str, variant_id: str | None = None, tail: str = "") -> str:
        base = f"/{quote(presentation_id, safe='')}"
        return base + (f"/variants/{quote(variant_id, safe='')}" if variant_id is not None else "/variants") + tail

    async def presentation_studio_graph(self, presentation_id: str, *, archived: bool = False,
                                        check: bool = False) -> dict[str, Any]:
        """`GET .../presentations/{id}/graph` : les noeuds (vivants, plus les archivés avec `archived`), l'actif, le compteur, le dernier bilan de reconciliation."""

        params = {name: "1" for name, on in (("archived", archived), ("check", check)) if on}
        return await self._studio("GET", f"/{quote(presentation_id, safe='')}/graph", params=params or None)

    async def presentation_studio_create_branch(self, presentation_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        """`POST .../presentations/{id}/variants` `{title, rationale?, source_variant_id?, activate?, actor?, expected_revision?}` : la branche creee."""

        return await self._studio("POST", self._variant_path(presentation_id), body=dict(body))

    async def presentation_studio_activate(self, presentation_id: str, variant_id: str,
                                           body: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return await self._studio("POST", self._variant_path(presentation_id, variant_id, "/activate"), body=dict(body or {}))

    async def presentation_studio_rename(self, presentation_id: str, variant_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        return await self._studio("POST", self._variant_path(presentation_id, variant_id, "/rename"), body=dict(body))

    async def presentation_studio_archive_plan(self, presentation_id: str, variant_id: str,
                                               body: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """`POST .../variants/{id}/archive-plan` : l'ensemble exact qu'un archivage toucherait + le jeton de confirmation. N'ecrit rien."""

        return await self._studio("POST", self._variant_path(presentation_id, variant_id, "/archive-plan"), body=dict(body or {}))

    async def presentation_studio_archive(self, presentation_id: str, variant_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        """`POST .../variants/{id}/archive` `{confirmation, activate_variant_id?, ...}` : exige le jeton du plan courant."""

        return await self._studio("POST", self._variant_path(presentation_id, variant_id, "/archive"), body=dict(body))

    async def presentation_studio_restore(self, presentation_id: str, variant_id: str,
                                          body: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return await self._studio("POST", self._variant_path(presentation_id, variant_id, "/restore"), body=dict(body or {}))

    # Comparaison et composition de variantes (Slice 19, `presentation_studio_compose_routes.py`). Une composition refusee leve
    # `CoreProtocolError` (409, `presentation_studio_composition_refused`) dont `details["conflicts"]` liste chaque conflit type.

    async def presentation_studio_compare(self, presentation_id: str) -> dict[str, Any]:
        """`GET .../presentations/{id}/compare` : la vue de l'ensemble de comparaison (vide : `active: false`)."""

        return await self._studio("GET", f"/{quote(presentation_id, safe='')}/compare")

    async def presentation_studio_compare_op(self, presentation_id: str, op: str, body: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """`POST .../compare/{op}` avec `op` dans `select`, `pair`, `mode`, `navigate`, `links`, `links/remove`, `clear`."""

        return await self._studio("POST", f"/{quote(presentation_id, safe='')}/compare/{op}", body=dict(body or {}))

    async def presentation_studio_composition_plan(self, presentation_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        """`POST .../compositions/plan` : `{ok, dry_run, conflicts, composition}`. N'ecrit rien."""

        return await self._studio("POST", f"/{quote(presentation_id, safe='')}/compositions/plan", body=dict(body))

    async def presentation_studio_compose(self, presentation_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        """`POST .../compositions` : la variante composee (reponse d'une branche + `composition`)."""

        return await self._studio("POST", f"/{quote(presentation_id, safe='')}/compositions", body=dict(body))

    async def presentation_studio_composition(self, presentation_id: str, variant_id: str) -> dict[str, Any]:
        """`GET .../variants/{id}/composition` : `{composition}`, la provenance ecrite."""

        return await self._studio("GET", self._variant_path(presentation_id, variant_id, "/composition"))

    # Variantes locales d'une scene (Slice 17, `presentation_studio_scene_variants_routes.py`). Creer, renommer, choisir et
    # supprimer sont des operations d'edition (`scene_variant.*` dans `presentation_studio_edit`), pas des routes.

    @staticmethod
    def _scene_variants_path(presentation_id: str, variant_id: str, scene_id: str, tail: str = "") -> str:
        return (f"/{quote(presentation_id, safe='')}/variants/{quote(variant_id, safe='')}"
                f"/scenes/{quote(scene_id, safe='')}/scene-variants{tail}")

    async def presentation_studio_scene_variants(self, presentation_id: str, variant_id: str, scene_id: str) -> dict[str, Any]:
        """`GET .../scenes/{scene_id}/scene-variants` : les variantes locales de la scene (sans contenu) et leurs bornes."""

        return await self._studio("GET", self._scene_variants_path(presentation_id, variant_id, scene_id))

    async def presentation_studio_scene_variant_preview(self, presentation_id: str, variant_id: str, scene_id: str,
                                                        scene_variant_id: str, body: Mapping[str, Any] | None = None
                                                        ) -> dict[str, Any]:
        """`POST .../scene-variants/{id}/preview` `{actor?, stage?, timeout_s?}` : la scene rendue en memoire. N'ecrit rien."""

        return await self._studio("POST", self._scene_variants_path(
            presentation_id, variant_id, scene_id, f"/{quote(scene_variant_id, safe='')}/preview"), body=dict(body or {}))

    async def presentation_studio_scene_variant_cancel_preview(self, presentation_id: str,
                                                               body: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """`POST .../presentations/{id}/scene-variants/preview/cancel` : rend la fenetre de scene a la scene canonique."""

        return await self._studio("POST", f"/{quote(presentation_id, safe='')}/scene-variants/preview/cancel",
                                  body=dict(body or {}))

    async def presentation_studio_scene_variant_promote(self, presentation_id: str, variant_id: str, scene_id: str,
                                                        scene_variant_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        """`POST .../scene-variants/{id}/promote` `{title, rationale?, activate?, ...}` : une variante de presentation neuve."""

        return await self._studio("POST", self._scene_variants_path(
            presentation_id, variant_id, scene_id, f"/{quote(scene_variant_id, safe='')}/promote"), body=dict(body))

    # ---- modeles reutilisables (Slice 20) : `presentation_studio_template_routes.py`

    async def presentation_studio_template_plan(self, presentation_id: str, variant_id: str,
                                                body: Mapping[str, Any]) -> dict[str, Any]:
        """`POST .../variants/{id}/templates/plan` : le plan d'une promotion (`ok`, `scenes`, `findings`, `would_publish`). N'ecrit rien."""

        return await self._studio("POST", f"/{quote(presentation_id, safe='')}/variants/{quote(variant_id, safe='')}/templates/plan",
                                  body=dict(body))

    async def presentation_studio_template_promote(self, presentation_id: str, variant_id: str,
                                                   body: Mapping[str, Any]) -> dict[str, Any]:
        """`POST .../variants/{id}/templates` : publie dans la bibliotheque partagee puis ecrit la composition (201)."""

        return await self._studio("POST", f"/{quote(presentation_id, safe='')}/variants/{quote(variant_id, safe='')}/templates",
                                  body=dict(body))

    async def _template(self, method: str, suffix: str, *, body: Any = None,
                        params: Mapping[str, str] | None = None) -> dict[str, Any]:
        session = await self._http()
        options: dict[str, Any] = {} if body is None else {"json": body}
        async with session.request(method, f"{self.base_url}{TEMPLATES_PREFIX}{suffix}", headers=self.headers, params=params,
                                   **options) as response:
            return await self._json(response)

    async def presentation_studio_templates(self, kind: str | None = None) -> dict[str, Any]:
        """`GET /v1/presentation-studio/templates[?kind=]` : `{templates, count, problems, limit}`."""

        return await self._template("GET", "", params=None if kind is None else {"kind": kind})

    async def presentation_studio_template(self, template_id: str) -> dict[str, Any]:
        """`GET .../templates/{id}` : `{template, summary, prefab_availability}`."""

        return await self._template("GET", f"/{quote(template_id, safe='')}")

    async def presentation_studio_template_instantiate(self, template_id: str,
                                                       body: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """`POST .../templates/{id}/instantiate` : 201, selon le genre (nouvelle Presentation, scene ajoutee, direction artistique)."""

        return await self._template("POST", f"/{quote(template_id, safe='')}/instantiate", body=dict(body or {}))

    async def forward_json(self, method: str, path: str, *, params: QueryParams | None = None,
                           body: bytes | None = None, timeout_s: float | None = None) -> tuple[int, Any]:
        """Relais transparent d'une requête `/v1/boards*`, `/v1/sessions*` (proxy du Control Center, Slice 04b)
        ou de gestion des plugins MCP `/v1/mcp/plugins*`, `/v1/mcp/oauth/callback` (generic-mcp-plugin-runtime,
        Slice 06).

        Rend le statut HTTP de Core et son corps JSON tel quel (enveloppe
        d'erreur `{"error": {code, message}}` comprise), `None` si le corps
        n'est pas du JSON (réponse texte d'aiohttp). Lève seulement sur une
        panne de transport : l'appelant la rend 503 (504 sur un délai d'une
        transition). `timeout_s` remplace le délai de la session HTTP (10 s).
        `/v1/mcp/tools*` n'est **jamais** relayé : aucune route d'exécution
        d'outil n'existe au Control Center (`docs/mcp/tool-contract.md` §8).
        """

        if not path.startswith(FORWARDABLE_PREFIXES):
            raise ValueError(f"forward_json only relays board, session, MCP plugin, context, capture, artifact, "
                             f"activity, workspace and prefab routes, not {path[:80]!r}")
        session = await self._http()
        headers = {**self.headers, "Content-Type": "application/json"} if body is not None else self.headers
        options: dict[str, Any] = {}
        if timeout_s is not None:
            options["timeout"] = aiohttp.ClientTimeout(total=timeout_s)
        async with session.request(method, self.base_url + path, headers=headers, params=params,
                                   data=body, **options) as response:
            try:
                payload = await response.json(content_type=None)
            except ValueError:
                payload = None  # argued: the proxy answers the status with its own envelope
            return response.status, payload

    async def forward_bytes(self, path: str, *, range_header: str | None = None,
                            timeout_s: float | None = None) -> tuple[int, dict[str, str], bytes]:
        """Relais binaire de `GET /v1/artifacts/{id}/payload` (Slice 09) : statut, en-têtes utiles, octets.

        Seul ce chemin : rien d'autre ne sort en octets bruts. Corps lu au plus
        `MAX_FORWARDED_PAYLOAD_BYTES` (+1) : au-delà, `ValueError` (le relais
        répond 502, rien n'est rendu à moitié). Un refus de Core est rendu tel
        quel (corps JSON codé dans les octets, `Content-Type` JSON).
        """

        parts = path.split("/")
        if len(parts) != 5 or path[:13] != "/v1/artifacts" or "/" + parts[4] != PAYLOAD_ROUTE_SUFFIX:
            raise ValueError(f"forward_bytes only relays artifact payloads, not {path[:80]!r}")
        session = await self._http()
        headers = dict(self.headers)
        if range_header:
            headers["Range"] = range_header
        options: dict[str, Any] = {}
        if timeout_s is not None:
            options["timeout"] = aiohttp.ClientTimeout(total=timeout_s)
        async with session.get(self.base_url + path, headers=headers, **options) as response:
            if response.content_length is not None and response.content_length > MAX_FORWARDED_PAYLOAD_BYTES:
                raise ValueError(f"Core payload response exceeds {MAX_FORWARDED_PAYLOAD_BYTES} bytes")
            raw = bytearray()
            async for chunk in response.content.iter_chunked(65_536):
                raw.extend(chunk)
                if len(raw) > MAX_FORWARDED_PAYLOAD_BYTES:
                    raise ValueError(f"Core payload response exceeds {MAX_FORWARDED_PAYLOAD_BYTES} bytes")
            kept = {name: response.headers[name] for name in FORWARDED_PAYLOAD_HEADERS if name in response.headers}
            return response.status, kept, bytes(raw)

    async def report_binding_agent(self, *, jarvis_session_id: str, board_id: str, agent_cli: str,
                                   agent_session_id: str | None) -> dict[str, Any]:
        """`POST /v1/sessions/bindings/report` : le CLI réel d'une liaison et son identifiant de reprise (Slice 04a).

        Rend `{binding}`. Un Core antérieur répond 404 `http_error` (route absente).
        """

        session = await self._http()
        body = {"jarvis_session_id": jarvis_session_id, "board_id": board_id, "agent_cli": agent_cli,
                "agent_session_id": agent_session_id}
        async with session.post(self.base_url + "/v1/sessions/bindings/report", headers=self.headers,
                                json=body) as response:
            return await self._json(response)

    # --------------------------------------------- MCP plugins (generic-mcp-plugin-runtime, Slice 02)
    # Refus en `CoreProtocolError` avec le code stable de `docs/mcp/plugins.md`
    # §8.2 (`mcp_plugin_unknown` 404, `mcp_plugin_duplicate` 409, ...).

    def _mcp_plugin_url(self, plugin_id: str, suffix: str = "") -> str:
        return self.base_url + f"/v1/mcp/plugins/{quote(plugin_id, safe='')}{suffix}"

    async def list_mcp_plugins(self) -> dict[str, Any]:
        """`GET /v1/mcp/plugins` : `{plugins, vault_available, catalog_revision}`."""

        session = await self._http()
        async with session.get(self.base_url + "/v1/mcp/plugins", headers=self.headers) as response:
            return await self._json(response)

    async def create_mcp_plugin(self, endpoint: str, *, display_name: str | None = None) -> dict[str, Any]:
        """`POST /v1/mcp/plugins` : `{plugin}` (201)."""

        body: dict[str, Any] = {"endpoint": endpoint}
        if display_name is not None:
            body["display_name"] = display_name
        session = await self._http()
        async with session.post(self.base_url + "/v1/mcp/plugins", headers=self.headers, json=body) as response:
            return await self._json(response)

    async def get_mcp_plugin(self, plugin_id: str) -> dict[str, Any]:
        session = await self._http()
        async with session.get(self._mcp_plugin_url(plugin_id), headers=self.headers) as response:
            return await self._json(response)

    async def update_mcp_plugin(self, plugin_id: str, *, enabled: bool | None = None,
                                display_name: str | None = None) -> dict[str, Any]:
        """`PATCH /v1/mcp/plugins/{id}` : seuls les champs passés changent."""

        body: dict[str, Any] = {}
        if enabled is not None:
            body["enabled"] = enabled
        if display_name is not None:
            body["display_name"] = display_name
        session = await self._http()
        async with session.patch(self._mcp_plugin_url(plugin_id), headers=self.headers, json=body) as response:
            return await self._json(response)

    async def set_mcp_plugin_credential(self, plugin_id: str, *, strategy: str, value: str,
                                        header_name: str | None = None) -> dict[str, Any]:
        """`PUT /v1/mcp/plugins/{id}/credential` : la valeur est scellée par Core, jamais renvoyée."""

        body: dict[str, Any] = {"strategy": strategy, "value": value}
        if header_name is not None:
            body["header_name"] = header_name
        session = await self._http()
        async with session.put(self._mcp_plugin_url(plugin_id, "/credential"), headers=self.headers,
                               json=body) as response:
            return await self._json(response)

    async def disconnect_mcp_plugin(self, plugin_id: str) -> dict[str, Any]:
        session = await self._http()
        async with session.post(self._mcp_plugin_url(plugin_id, "/disconnect"), headers=self.headers) as response:
            return await self._json(response)

    async def delete_mcp_plugin(self, plugin_id: str) -> dict[str, Any]:
        """`DELETE /v1/mcp/plugins/{id}` : `{removed: id}`."""

        session = await self._http()
        async with session.delete(self._mcp_plugin_url(plugin_id), headers=self.headers) as response:
            return await self._json(response)

    async def connect_mcp_plugin(self, plugin_id: str, *, strategy: str | None = None) -> dict[str, Any]:
        """`POST /v1/mcp/plugins/{id}/connect` (Slice 03) : `{status: "connected", plugin}` (200) ou
        `{status: "authorizing", authorization_url, plugin}` (202)."""

        body = {} if strategy is None else {"strategy": strategy}
        session = await self._http()
        async with session.post(self._mcp_plugin_url(plugin_id, "/connect"), headers=self.headers,
                                json=body) as response:
            return await self._json(response)

    async def refresh_mcp_plugin(self, plugin_id: str) -> dict[str, Any]:
        """`POST /v1/mcp/plugins/{id}/refresh` (Slice 03) : relit la liste d'outils, `{plugin}`."""

        session = await self._http()
        async with session.post(self._mcp_plugin_url(plugin_id, "/refresh"), headers=self.headers) as response:
            return await self._json(response)

    # ------------------- Capacités locales installables (jarvis-remotion-presentation-integration, Slice 04)
    # `docs/local-capabilities.md` §7. Refus en `CoreProtocolError` (`local_capability_*`) ; un échec d'opération est la vue.

    async def list_local_capabilities(self) -> dict[str, Any]:
        """`GET /v1/local-capabilities` : `{capabilities}`."""

        session = await self._http()
        async with session.get(self.base_url + "/v1/local-capabilities", headers=self.headers) as response:
            return await self._json(response)

    async def local_capability_action(self, capability_id: str, operation: str) -> dict[str, Any]:
        """`POST /v1/local-capabilities/{id}/{operation}` : `{capability}` (200 finie, 202 en cours : relire par `GET`)."""

        session = await self._http()
        url = self.base_url + f"/v1/local-capabilities/{quote(capability_id, safe='')}/{quote(operation, safe='')}"
        async with session.post(url, headers=self.headers) as response:
            return await self._json(response)

    async def complete_mcp_oauth(self, *, state: str, code: str | None = None, iss: str | None = None,
                                 error: str | None = None) -> dict[str, Any]:
        """`POST /v1/mcp/oauth/callback` (Slice 03) : retour du navigateur relayé par le CC, `{plugin}`."""

        body: dict[str, Any] = {"state": state}
        for key, value in (("code", code), ("iss", iss), ("error", error)):
            if value is not None:
                body[key] = value
        session = await self._http()
        async with session.post(self.base_url + "/v1/mcp/oauth/callback", headers=self.headers,
                                json=body) as response:
            return await self._json(response)

    async def list_mcp_tools(self, *, since_revision: int | None = None,
                             timeout_s: float | None = None) -> dict[str, Any]:
        """`GET /v1/mcp/tools` (Slice 04) : `{catalog_revision, unchanged, plugins, tools}`.

        `timeout_s` remplace le délai de la session HTTP (le Control Center
        n'attend Core que 2 s pour sa vue fusionnée).
        """

        params = {} if since_revision is None else {"since_revision": str(since_revision)}
        options: dict[str, Any] = {} if timeout_s is None else {"timeout": aiohttp.ClientTimeout(total=timeout_s)}
        session = await self._http()
        async with session.get(self.base_url + "/v1/mcp/tools", headers=self.headers, params=params,
                               **options) as response:
            return await self._json(response)

    async def call_mcp_tool(self, tool_id: str, arguments: dict[str, Any], *, caller: dict[str, Any],
                            timeout_s: float | None = None) -> dict[str, Any]:
        """`POST /v1/mcp/tools/call` (Slice 04) : `ToolCallOutcome`. Refus en `CoreProtocolError` codée.

        Le délai HTTP couvre celui de l'outil (60 s par défaut, 120 s au plus)
        plus une marge : la session par défaut (10 s) couperait un appel légitime.
        """

        body: dict[str, Any] = {"tool_id": tool_id, "arguments": arguments, "caller": caller}
        if timeout_s is not None:
            body["timeout_s"] = timeout_s
        http_timeout = aiohttp.ClientTimeout(total=(60.0 if timeout_s is None else timeout_s) + 15.0)
        session = await self._http()
        async with session.post(self.base_url + "/v1/mcp/tools/call", headers=self.headers, json=body,
                                timeout=http_timeout) as response:
            return await self._json(response)

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
            raise CoreProtocolError(response.status, str(error.get("code", "unknown")), str(error.get("message", "")),
                                    details={k: v for k, v in error.items() if k not in ("code", "message")})
        return await response.json()
