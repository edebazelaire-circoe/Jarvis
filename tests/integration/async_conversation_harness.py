"""Harnais d'intégration de la conversation asynchrone (tâche 11).

Ce module ne contient aucun test : il monte, en mémoire et hors réseau, la
pile complète que les scénarios de `test_v2_async_conversation.py` mettent à
l'épreuve.

    micro factice -> RealtimeConversationBridge -> LocalCoreClient
        -> HTTP loopback -> LocalProtocolServer -> JarvisCoreApplication
        -> BrainOrchestrator -> backend cerveau scripté
        -> /v1/events (websocket réel) -> SpeechScheduler -> session factice

Seuls trois points sont des doubles, et ce sont exactement les trois que la
Décision 20 et la spec §11 réservent à la recette poste de travail :

- la **session Realtime**, remplacée par `FakeRealtimeSession`, qui parle le
  vocabulaire d'évènements provider-neutre du bridge et rend un identifiant de
  sortie sur `speak()` ;
- le **périphérique audio**, remplacé par `FakeAudio`, qui garde toute la
  comptabilité de lecture de `SoundDeviceRealtimeAudio` mais n'ouvre aucun flux
  PortAudio ;
- le **modèle fort**, remplacé par `ScriptedBrainBackend`, qui ne rend jamais
  la main tant que le test ne l'a pas décidé.

Tout le reste est le code de production : le protocole local HTTP/WebSocket,
`BrainOrchestrator`, `SpeechScheduler`, `PersistentVoiceRuntime` et le bridge.

Déterminisme
------------
Aucun `sleep` ne sert de synchronisation. Le test avance sur des évènements :
`ScriptedBrainBackend.next_turn()` attend une file, `RecordingJournal.wait_until`
attend un jalon journalisé, et `wait_until()` est une attente de condition
bornée par un délai — jamais une pause fixe censée « laisser le temps ».
"""

from __future__ import annotations

import asyncio
import base64
import socket
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from aiohttp import web

import jarvis.protocol.server as protocol_server
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.v2 import (
    BrainEvent,
    BrainEventKind,
    BrainRunStatus,
    BrainTurnInput,
    BrainTurnResult,
    BrainWorkingState,
    PlaybackCursor,
    ProtocolEnvelope,
    SpeechKind,
    SpeechPriority,
    SpeechRequest,
    VoiceLifecycleState,
    utc_now,
)
from jarvis.protocol.client import LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.realtime_audio import SoundDeviceRealtimeAudio
from jarvis.runtime.speech_scheduler import SpeechScheduler
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.v2_config import VoiceArchitecture

TOKEN = "i" * 48

# Généreux à dessein : ces scénarios traversent un vrai websocket de boucle
# locale. Le délai n'est jamais une attente réelle — il ne sert qu'à faire
# échouer un test bloqué plutôt qu'à le suspendre indéfiniment.
TIMEOUT_S = 10.0

# Reconnexion de l'ordonnanceur de parole ramenée à une valeur imperceptible.
# La valeur de production (2 s) n'est pas une règle métier : c'est un
# anti-emballement. La raccourcir accélère le test sans rien changer de la
# séquence prouvée.
FAST_RECONNECT_DELAY_S = 0.05


class FastShutdownRunner(web.AppRunner):
    """`AppRunner` de test qui n'attend pas la fin d'un websocket ouvert.

    Le délai d'extinction d'aiohttp vaut soixante secondes : un abonné
    `/v1/events` toujours connecté ferait donc durer une minute chaque arrêt de
    serveur, y compris la coupure volontaire du scénario de reconnexion. Ce
    délai n'est pas un contrat de Jarvis — la production garde le sien.
    """

    def __init__(self, app, **kwargs) -> None:  # noqa: ANN001
        kwargs.setdefault("shutdown_timeout", 0.05)
        super().__init__(app, **kwargs)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def wait_until(predicate, *, timeout: float = TIMEOUT_S, message: str = "") -> None:
    """Attendre une condition, sans supposer combien de tours de boucle il faut."""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        if predicate():
            return
        if loop.time() >= deadline:
            raise AssertionError(f"condition jamais atteinte: {message or predicate}")
        await asyncio.sleep(0.005)


# ---------------------------------------------------------------------------
# Doubles d'infrastructure
# ---------------------------------------------------------------------------


class FakeClock:
    """Horloge pilotée : même forme que dans les tests unitaires du mode continu."""

    def __init__(self) -> None:
        self.value = utc_now()

    def now(self) -> datetime:
        return self.value

    async def sleep(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


class RecordingJournal:
    """`RuntimeJournal` de test (Décision 27 : c'est le support d'observabilité)."""

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.changed = asyncio.Event()

    def emit(self, kind: str, message: str, *, level: str = "info", data=None) -> None:  # noqa: ANN001
        self.events.append({"kind": kind, "message": message, "level": level, "data": data or {}})
        self.changed.set()

    def count(self, kind: str) -> int:
        return sum(1 for event in self.events if event["kind"] == kind)

    def of(self, kind: str) -> list[dict[str, object]]:
        return [event for event in self.events if event["kind"] == kind]

    async def wait_until(self, predicate, *, timeout: float = TIMEOUT_S) -> None:
        """Attendre qu'un jalon soit journalisé, sans dormir en temps réel.

        Le délai est **global**, pas remis à zéro à chaque évènement : une
        boucle de reconnexion qui journalise sans relâche ferait sinon attendre
        indéfiniment un jalon qui n'arrivera jamais.
        """

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            self.changed.clear()
            if predicate():
                return
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise AssertionError(f"jalon jamais journalisé: {predicate}")
            await asyncio.wait_for(self.changed.wait(), timeout=remaining)


class RecordingSignals:
    def __init__(self) -> None:
        self.states: list[str] = []
        self.alerts: list[str | None] = []

    def state(self, value: str) -> None:
        self.states.append(value)

    def alert(self, message: str | None) -> None:
        self.alerts.append(message)

    def heartbeat(self) -> None:
        return None

    def offline(self) -> None:
        return None


class FakeWakeWord:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.suspensions = 0
        self.resumptions = 0
        self.closed = False

    async def detections(self):
        while not self.closed:
            yield await self.queue.get()

    async def suspend(self) -> None:
        return None

    async def suspend_for_active_session(self) -> None:
        self.suspensions += 1

    async def resume(self) -> None:
        self.resumptions += 1

    async def close(self) -> None:
        self.closed = True


class FakeAudio(SoundDeviceRealtimeAudio):
    """Périphérique sans PortAudio, mais avec la vraie comptabilité de lecture.

    Deux choses sont conservées de la classe de production, parce que le
    barge-in en dépend : les époques de sortie et le crédit des octets écrits.
    C'est ce qui donne un `played_ms` non nul, donc une troncature exacte et un
    tour assistant marqué « partiellement entendu » (Décision 36).
    """

    instances: list["FakeAudio"] = []
    pcm = b"\x01\x00" * 2400

    def __init__(self, *, input_device=None, output_device=None, **rates) -> None:  # noqa: ANN001
        super().__init__(input_device=input_device, output_device=output_device, **rates)
        self.stop_output_calls = 0
        self.stop_input_calls = 0
        self.closed = False
        self.__class__.instances.append(self)

    async def start(self) -> None:
        self._enqueue(self.pcm)

    async def stop_input(self) -> None:
        self.stop_input_calls += 1
        await super().stop_input()

    async def stop_output(self) -> None:
        self.stop_output_calls += 1
        await super().stop_output()

    async def play_b64(self, value: str) -> None:
        """Créditer ce qui aurait été joué, bloc par bloc, sans périphérique.

        Reproduit la boucle de `_write_output` : l'époque de lecture est relue à
        chaque bloc, si bien qu'un `stop_output()` concurrent arrête le crédit
        au bloc suivant exactement comme en production.
        """

        if not value:
            return
        pcm = base64.b64decode(value)
        with self._cursor_lock:
            epoch, playback_epoch = self._output_epoch, self._playback_epoch
        step = self.OUTPUT_CHUNK_FRAMES * self._BYTES_PER_FRAME
        for offset in range(0, len(pcm), step):
            with self._cursor_lock:
                if playback_epoch != self._playback_epoch:
                    return
            self._credit_written(epoch, len(pcm[offset:offset + step]))
            # Rendre la main entre deux blocs : le vrai `play_b64` passe par un
            # thread, donc la boucle asyncio n'est jamais monopolisée.
            await asyncio.sleep(0)

    async def close(self) -> None:
        self.closed = True


def audio_chunk_b64(chunks: int = 1) -> str:
    """Bloc PCM d'une durée connue : un bloc de sortie vaut 100 ms à 24 kHz."""

    frames = SoundDeviceRealtimeAudio.OUTPUT_CHUNK_FRAMES * chunks
    return base64.b64encode(b"\x01\x00" * frames).decode()


CHUNK_MS = 100


# ---------------------------------------------------------------------------
# Surface Realtime factice
# ---------------------------------------------------------------------------


class FakeRealtimeSession:
    """Session Realtime déterministe : `RealtimeSession` + `RealtimeOutputControl`.

    Elle ne décide rien toute seule. Le test pousse les évènements du
    fournisseur (`user_says`, `interrupt`, `surface_reflex`) et l'ordonnanceur
    de parole déclenche `speak()` ; une sortie ne se termine que lorsque le test
    ou l'annulation la termine. C'est ce qui permet d'observer la file pendant
    que JARVIS parle, et d'interrompre au milieu d'une phrase.

    Fidélité assumée sur un point : `cancel_output()` clôt la sortie active avec
    le statut `cancelled`, comme le fournisseur qui confirme l'annulation. Sans
    cela, l'ordonnanceur attendrait indéfiniment une fin de sortie qui ne
    viendrait jamais.
    """

    def __init__(self, *, name: str = "session") -> None:
        self.name = name
        self.inbox: asyncio.Queue[ProtocolEnvelope | None] = asyncio.Queue()
        self.spoken: list[SpeechRequest] = []
        self.cancelled_cursors: list[PlaybackCursor | None] = []
        self.truncated_cursors: list[PlaybackCursor] = []
        self.tool_results: list[tuple[str, dict[str, object]]] = []
        self.contexts: list[str] = []
        self.audio_bytes = 0
        self.finish_calls = 0
        self.closed = False
        self.active_output_id: str | None = None
        self.active_speech_id: str | None = None
        self._outputs = 0
        self._items = 0

    # -- RealtimeSession ----------------------------------------------------

    async def send_audio(self, pcm: bytes) -> None:
        self.audio_bytes += len(pcm)

    async def finish_input(self) -> bool:
        self.finish_calls += 1
        return True

    async def send_tool_result(self, call_id: str, result: dict[str, object]) -> None:
        self.tool_results.append((call_id, dict(result)))

    async def send_context(self, text: str) -> None:
        self.contexts.append(text)

    async def keepalive(self) -> None:
        return None

    async def events(self):
        while True:
            event = await self.inbox.get()
            if event is None:
                return
            yield event

    async def close(self) -> None:
        self.closed = True
        await self.inbox.put(None)

    # -- RealtimeOutputControl ---------------------------------------------

    async def speak(self, request: SpeechRequest) -> str:
        """Restituer la demande du cerveau et ouvrir la sortie correspondante."""

        self.spoken.append(request)
        self._outputs += 1
        output_id = f"{self.name}-out-{self._outputs}"
        self.active_output_id = output_id
        self.active_speech_id = request.id
        await self.push(
            "realtime.output_started",
            output_id=output_id,
            speech_id=request.id,
            response_id=f"{output_id}-resp",
        )
        return output_id

    async def cancel_output(self, cursor: PlaybackCursor | None = None) -> None:
        self.cancelled_cursors.append(cursor)
        output_id, self.active_output_id = self.active_output_id, None
        self.active_speech_id = None
        if output_id is not None:
            await self.push("realtime.response_done", output_id=output_id, status="cancelled")

    async def truncate(self, cursor: PlaybackCursor) -> None:
        self.truncated_cursors.append(cursor)

    # -- pilotage par le test ----------------------------------------------

    async def push(self, message_type: str, **payload: object) -> None:
        await self.inbox.put(ProtocolEnvelope(message_type=message_type, payload=payload))

    async def play_audio(self, *, chunks: int = 1) -> None:
        """Jouer `chunks` blocs de 100 ms pour la sortie ouverte."""

        await self.push(
            "realtime.audio",
            pcm_b64=audio_chunk_b64(chunks),
            output_id=self.active_output_id,
            speech_id=self.active_speech_id,
            item_id=f"{self.active_output_id}-item",
        )

    async def finish_output(self, *, status: str = "completed", transcript: str | None = None) -> None:
        """Clore la sortie ouverte comme le ferait `response.done`."""

        output_id, self.active_output_id = self.active_output_id, None
        speech_id, self.active_speech_id = self.active_speech_id, None
        if transcript is not None:
            await self.push("realtime.assistant_transcript", text=transcript, speech_id=speech_id or "")
        await self.push("realtime.audio_done", output_id=output_id)
        await self.push("realtime.response_done", output_id=output_id, status=status)

    async def surface_reflex(self, text: str, *, chunks: int = 1) -> None:
        """Réflexe de surface : la surface répond d'elle-même, sans le cerveau.

        Aucun `speech_id` : ce n'est pas de la parole du cerveau, et c'est ce
        qui la fait persister avec la provenance `surface.reflex` (spec §15).
        """

        self._outputs += 1
        output_id = f"{self.name}-reflex-{self._outputs}"
        self.active_output_id = output_id
        self.active_speech_id = None
        await self.push("realtime.output_started", output_id=output_id, response_id=f"{output_id}-resp")
        await self.push("realtime.audio", pcm_b64=audio_chunk_b64(chunks), output_id=output_id)
        await self.finish_output(transcript=text)

    async def user_says(self, text: str, *, item_id: str | None = None) -> str:
        """Tour utilisateur complet : commit du VAD serveur puis transcript final."""

        self._items += 1
        item = item_id or f"{self.name}-item-{self._items}"
        await self.push("realtime.input_committed", item_id=item)
        await self.push("realtime.transcript", text=text, item_id=item)
        return item

    async def ambient(self, text: str) -> None:
        """Bruit de fond : entendu, jamais adressé (Décision 10)."""

        await self.push("realtime.transcript", text=text)

    async def interrupt(self) -> None:
        """Le VAD serveur détecte que l'utilisateur reprend la parole."""

        await self.push("realtime.speech_started")

    async def tool_call(self, name: str, arguments: dict[str, object] | None = None, *, call_id: str = "call-1") -> None:
        await self.push("realtime.tool_call", call_id=call_id, name=name, arguments=arguments or {})

    def texts(self) -> list[str]:
        return [request.text for request in self.spoken]


# ---------------------------------------------------------------------------
# Backend cerveau scripté
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class BrainTurnHandle:
    """Un tour cerveau en vol, piloté depuis le test.

    Le backend est volontairement **lent** : `run_turn` ne rend la main que sur
    `finish()`. Tout ce qui se passe entre-temps — travail démarré, progression,
    question, résultat, annulation — est émis à la demande du test, ce qui rend
    les scénarios asynchrones reproductibles sans une seule pause.
    """

    turn: BrainTurnInput
    state: BrainWorkingState
    emit: object
    release: asyncio.Event = field(default_factory=asyncio.Event)
    result: BrainTurnResult | None = None

    @property
    def conversation_id(self) -> str:
        return self.turn.conversation_id

    @property
    def correlation_id(self) -> str:
        return self.turn.correlation_id

    async def _emit(self, event: BrainEvent) -> None:
        await self.emit.emit(event)  # type: ignore[attr-defined]

    async def start_work(self, work_id: str, *, label: str = "") -> None:
        await self._emit(
            BrainEvent(
                kind=BrainEventKind.ACCEPTED,
                conversation_id=self.conversation_id,
                correlation_id=self.correlation_id,
                work_id=work_id,
                public_summary=label,
            )
        )

    async def report_progress(self, work_id: str, summary: str) -> None:
        await self._emit(
            BrainEvent(
                kind=BrainEventKind.PROGRESS,
                conversation_id=self.conversation_id,
                correlation_id=self.correlation_id,
                work_id=work_id,
                public_summary=summary,
            )
        )

    async def complete_work(self, work_id: str, *, summary: str = "") -> None:
        await self._emit(
            BrainEvent(
                kind=BrainEventKind.COMPLETED,
                conversation_id=self.conversation_id,
                correlation_id=self.correlation_id,
                work_id=work_id,
                public_summary=summary,
            )
        )

    async def supersede_work(self, work_id: str) -> None:
        await self._emit(
            BrainEvent(
                kind=BrainEventKind.SUPERSEDED,
                conversation_id=self.conversation_id,
                correlation_id=self.correlation_id,
                work_id=work_id,
            )
        )

    async def cancel_work(self, work_id: str) -> None:
        await self._emit(
            BrainEvent(
                kind=BrainEventKind.CANCELLED,
                conversation_id=self.conversation_id,
                correlation_id=self.correlation_id,
                work_id=work_id,
            )
        )

    async def say(
        self,
        text: str,
        *,
        kind: SpeechKind = SpeechKind.PROGRESS,
        work_id: str | None = None,
        priority: SpeechPriority | None = None,
        supersedes_key: str | None = None,
        expires_at: datetime | None = None,
    ) -> SpeechRequest:
        """Demander à la surface de dire une phrase, et rendre la demande émise.

        Le test récupère l'objet pour connaître le `speech_id` : c'est lui qui
        relie la parole coupée, la troncature et le tour suivant.
        """

        request = SpeechRequest(
            conversation_id=self.conversation_id,
            text=text,
            kind=kind,
            priority=priority or (SpeechPriority.HIGH if kind is SpeechKind.QUESTION else SpeechPriority.NORMAL),
            correlation_id=self.correlation_id,
            work_id=work_id,
            supersedes_key=supersedes_key,
            expires_at=expires_at,
        )
        await self._emit(
            BrainEvent(
                kind=BrainEventKind.SPEECH,
                conversation_id=self.conversation_id,
                correlation_id=self.correlation_id,
                work_id=work_id,
                speech=request,
            )
        )
        return request

    async def resend(self, request: SpeechRequest) -> None:
        """Réémettre une demande de parole déjà émise, à l'identique.

        Sert à jouer le doublon : Core republie, et rien ne doit être dit deux
        fois côté surface.
        """

        await self._emit(
            BrainEvent(
                kind=BrainEventKind.SPEECH,
                conversation_id=self.conversation_id,
                correlation_id=self.correlation_id,
                work_id=request.work_id,
                speech=request,
            )
        )

    def finish(self, *, public_summary: str = "", status: BrainRunStatus = BrainRunStatus.COMPLETED, error: str | None = None) -> None:
        """Rendre la main : `run_turn` retourne enfin."""

        self.result = BrainTurnResult(
            correlation_id=self.correlation_id,
            status=status,
            public_summary=public_summary,
            error=error,
        )
        self.release.set()


class ScriptedBrainBackend:
    """`BrainBackend` lent et déterministe, entièrement piloté par le test."""

    def __init__(self) -> None:
        self.handles: list[BrainTurnHandle] = []
        self._arrivals: asyncio.Queue[BrainTurnHandle] = asyncio.Queue()

    async def run_turn(self, turn: BrainTurnInput, state: BrainWorkingState, emit) -> BrainTurnResult:  # noqa: ANN001
        handle = BrainTurnHandle(turn=turn, state=state, emit=emit)
        self.handles.append(handle)
        self._arrivals.put_nowait(handle)
        await handle.release.wait()
        return handle.result or BrainTurnResult(correlation_id=turn.correlation_id)

    async def next_turn(self, *, timeout: float = TIMEOUT_S) -> BrainTurnHandle:
        """Attendre le prochain tour confié au modèle fort."""

        return await asyncio.wait_for(self._arrivals.get(), timeout=timeout)


# ---------------------------------------------------------------------------
# Observation du bus Core
# ---------------------------------------------------------------------------


class CoreEventRecorder:
    """Abonné de contrôle sur `CoreEventBus`, pour observer ce que Core publie.

    Distinct du chemin de la voix : la surface consomme `/v1/events` par
    websocket. Cet abonné-ci sert au test à vérifier ce que Core a **émis**,
    y compris pendant que la voix est au fond.
    """

    def __init__(self, core: JarvisCoreApplication) -> None:
        self.core = core
        self.events: list[ProtocolEnvelope] = []
        self._queue = core.events.subscribe()
        self._task = asyncio.create_task(self._drain(), name="jarvis-test-event-recorder")

    async def _drain(self) -> None:
        while True:
            self.events.append(await self._queue.get())

    def of(self, message_type: str) -> list[ProtocolEnvelope]:
        return [event for event in self.events if event.message_type == message_type]

    def types(self) -> list[str]:
        return [event.message_type for event in self.events]

    async def wait_for(self, message_type: str, *, count: int = 1, timeout: float = TIMEOUT_S) -> ProtocolEnvelope:
        await wait_until(
            lambda: len(self.of(message_type)) >= count,
            timeout=timeout,
            message=f"{message_type} x{count}",
        )
        return self.of(message_type)[count - 1]

    async def close(self) -> None:
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self.core.events.unsubscribe(self._queue)


# ---------------------------------------------------------------------------
# Pile complète
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class VoiceStack:
    """Tout ce que le test pilote : Core, protocole, voix, et leurs doubles."""

    core: JarvisCoreApplication
    server: LocalProtocolServer
    client: LocalCoreClient
    port: int
    runtime: PersistentVoiceRuntime
    wakeword: FakeWakeWord
    backend: ScriptedBrainBackend
    journal: RecordingJournal
    core_journal: RecordingJournal
    signals: RecordingSignals
    events: CoreEventRecorder
    sessions: list[FakeRealtimeSession]
    clock: FakeClock | None
    run_task: asyncio.Task[None] | None = None

    @property
    def session(self) -> FakeRealtimeSession:
        """Session Realtime courante : une nouvelle naît à chaque activation."""

        return self.sessions[-1]

    @property
    def audio(self) -> FakeAudio:
        return FakeAudio.instances[-1]

    @property
    def conversation_id(self) -> str:
        conversation_id = self.runtime.runtime.conversation_id
        assert conversation_id is not None, "aucune conversation n'a encore été ouverte"
        return conversation_id

    async def wake(self, *, keyword: str = "f9") -> None:
        """Réveiller la voix et attendre que la session soit vraiment ouverte."""

        opened = len(self.sessions)
        started = self.journal.count("audio.start")
        await self.wakeword.queue.put(keyword)
        await self.journal.wait_until(lambda: self.journal.count("audio.start") > started)
        await wait_until(lambda: len(self.sessions) > opened, message="session Realtime ouverte")
        # L'ordonnanceur doit être abonné avant que le test ne pousse un tour,
        # sinon la parole du cerveau partirait dans le vide (Décision 31 : rien
        # n'est rejoué).
        await wait_until(
            lambda: self.core.events.subscriber_count >= self._expected_subscribers(),
            message="ordonnanceur de parole abonné à /v1/events",
        )

    def _expected_subscribers(self) -> int:
        # Core lui-même (boucle de notifications), l'observateur du test, et
        # l'ordonnanceur de parole de la session active.
        return 3

    async def wait_background(self) -> None:
        """Attendre un retour au fond **complet**, abonnement `/v1/events` compris.

        Se contenter de l'état vocal laisserait le websocket de la session
        précédente ouvert : la réactivation verrait alors deux abonnés, et le
        test repartirait sur une pile qui n'est pas celle qu'il croit.
        """

        await wait_until(
            lambda: self.runtime.runtime.state is VoiceLifecycleState.BACKGROUND,
            message="retour au fond",
        )
        await wait_until(
            lambda: self.core.events.subscriber_count <= self._expected_subscribers() - 1,
            message="abonnement /v1/events refermé",
        )

    async def user_says(self, text: str, *, item_id: str | None = None) -> BrainTurnHandle:
        """Dire une phrase adressée et rendre le tour reçu par le modèle fort."""

        submitted = self.journal.count("voice.brain_turn_submitted")
        await self.session.user_says(text, item_id=item_id)
        await self.journal.wait_until(lambda: self.journal.count("voice.brain_turn_submitted") > submitted)
        return await self.backend.next_turn()

    async def wait_spoken(self, count: int, *, timeout: float = TIMEOUT_S) -> None:
        await wait_until(
            lambda: len(self.session.spoken) >= count,
            timeout=timeout,
            message=f"{count} parole(s) prononcée(s)",
        )

    async def speak_and_finish(self, *, chunks: int = 1, transcript: str | None = None) -> None:
        """Laisser la sortie ouverte se jouer jusqu'au bout."""

        await self.session.play_audio(chunks=chunks)
        await self.session.finish_output(transcript=transcript)

    async def assistant_turns(self) -> list[object]:
        turns = await self.core.state.list_turns(self.conversation_id, limit=50)
        return [turn for turn in turns if turn.kind.value == "assistant"]

    async def wait_for_assistant_turns(self, count: int, *, timeout: float = TIMEOUT_S) -> list[object]:
        """Attendre que l'historique ait rattrapé la parole.

        La persistance suit la prononciation : l'ordonnanceur écrit le tour une
        fois la sortie soldée. Lire le magasin sans attendre observerait donc
        l'historique d'avant la dernière phrase.
        """

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            turns = await self.assistant_turns()
            if len(turns) >= count:
                return turns
            if loop.time() >= deadline:
                raise AssertionError(f"seulement {len(turns)} tour(s) assistant persisté(s) sur {count}")
            await asyncio.sleep(0.005)

    async def user_turns(self) -> list[object]:
        turns = await self.core.state.list_turns(self.conversation_id, limit=50)
        return [turn for turn in turns if turn.kind.value == "user"]


@asynccontextmanager
async def voice_stack(
    tmp_path,
    monkeypatch,
    *,
    clock: FakeClock | None = None,
    active_timeout_s: float = 90.0,
):
    """Monter la pile complète, la réveiller, puis tout démonter proprement.

    Le contrat de démontage compte autant que le montage : une session Realtime
    laissée ouverte ou un abonnement `/v1/events` non fermé transformeraient le
    scénario suivant en course.
    """

    import jarvis.runtime.realtime_audio as realtime_audio

    FakeAudio.instances.clear()
    monkeypatch.setattr(realtime_audio, "SoundDeviceRealtimeAudio", FakeAudio)
    monkeypatch.setattr(SpeechScheduler, "RECONNECT_DELAY_S", FAST_RECONNECT_DELAY_S)
    monkeypatch.setattr(protocol_server.web, "AppRunner", FastShutdownRunner)

    backend = ScriptedBrainBackend()
    journal = RecordingJournal()
    core_journal = RecordingJournal()
    signals = RecordingSignals()
    sessions: list[FakeRealtimeSession] = []

    port = free_port()
    core = JarvisCoreApplication(data_root=tmp_path, brain_backend=backend, diagnostics=core_journal)
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    client = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
    recorder = CoreEventRecorder(core)

    async def factory(context):
        del context
        session = FakeRealtimeSession(name=f"s{len(sessions) + 1}")
        sessions.append(session)
        return session

    wakeword = FakeWakeWord()
    runtime = PersistentVoiceRuntime(
        wakeword=wakeword,  # type: ignore[arg-type]
        core=client,
        realtime_factory=factory,  # type: ignore[arg-type]
        active_timeout_s=active_timeout_s,
        clock=clock,  # type: ignore[arg-type]
        signals=signals,  # type: ignore[arg-type]
        journal=journal,  # type: ignore[arg-type]
        auto_turn=True,
        voice_arch=VoiceArchitecture.CONTINUOUS_BRAIN,
    )
    stack = VoiceStack(
        core=core,
        server=server,
        client=client,
        port=port,
        runtime=runtime,
        wakeword=wakeword,
        backend=backend,
        journal=journal,
        core_journal=core_journal,
        signals=signals,
        events=recorder,
        sessions=sessions,
        clock=clock,
    )
    run_task = asyncio.create_task(runtime.run(), name="jarvis-test-voice-runtime")
    stack.run_task = run_task
    try:
        yield stack
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)
        # Libérer les tours cerveau encore en vol : un backend qui attend
        # toujours son `release` empêcherait `core.stop()` de se solder.
        for handle in backend.handles:
            handle.release.set()
        await recorder.close()
        await client.close()
        # `stack.server` et non `server` : un scénario peut avoir coupé puis
        # remonté le protocole, et c'est le serveur vivant qu'il faut arrêter.
        await stack.server.stop()
        await core.stop()
