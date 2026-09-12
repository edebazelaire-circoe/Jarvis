"""Ordonnancement de la parole du cerveau (Tâche 08).

Ce fichier prouve la politique de `SpeechScheduler` : qui parle, dans quel
ordre, et surtout ce qui n'est **jamais** prononcé — parole périmée, parole
d'une autre conversation, parole rattrapée par une révision d'intention, ou
résultat arrivé après que l'utilisateur a coupé la voix (Décision 33).

Ce qui n'est **pas** prouvé ici : la fidélité acoustique de la restitution. Le
texte part tel quel vers `speak()` (Décision 13) et les tests le vérifient mot
pour mot, mais ce que le fournisseur prononce réellement ne peut être constaté
que sur un poste réel.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from jarvis.domain.v2 import (
    PlaybackCursor,
    ProtocolEnvelope,
    SpeechKind,
    SpeechPriority,
    SpeechProvenance,
    SpeechRequest,
    VoiceLifecycleState,
    utc_now,
)
from jarvis.runtime.realtime_audio import SoundDeviceRealtimeAudio
from jarvis.runtime.speech_scheduler import SpeechScheduler
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.v2_config import VoiceArchitecture

CONVERSATION = "conversation-1"
TIMEOUT_S = 2.0
# Origine des horodatages fabriqués par les fixtures. Ancrée sur l'heure
# courante et non sur une date en dur : depuis la correction B, une parole
# transitoire sans échéance en reçoit une, et une progression datée d'un jour
# figé serait périmée avant d'atteindre la file dès que le test utilise
# l'horloge système. Les assertions restent relatives à cette origine, donc
# rien de leur sens ne dépend de la date.
ORIGIN = utc_now()


@pytest.fixture(autouse=True)
def _origin_of_this_test():
    """Réancrer l'origine au début de chaque test, pas à l'import du module.

    Ancrée à la collecte, elle vieillit avec la suite : une suite complète qui
    atteint ce fichier plus de 60 s après la collecte (TTL des paroles
    transitoires) fabriquait des progressions déjà périmées, et neuf tests
    échouaient alors qu'ils passaient seuls.
    """

    global ORIGIN
    ORIGIN = utc_now()


class FakeClock:
    def __init__(self) -> None:
        self.value = ORIGIN

    def now(self) -> datetime:
        return self.value

    async def sleep(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


class RecordingJournal:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.changed = asyncio.Event()

    def emit(self, kind: str, message: str, *, level: str = "info", data=None) -> None:
        self.events.append({"kind": kind, "message": message, "level": level, "data": data or {}})
        self.changed.set()

    def count(self, kind: str) -> int:
        return sum(1 for event in self.events if event["kind"] == kind)

    def of(self, kind: str) -> list[dict[str, object]]:
        return [event for event in self.events if event["kind"] == kind]

    async def wait_until(self, predicate) -> None:
        while True:
            self.changed.clear()
            if predicate():
                return
            await asyncio.wait_for(self.changed.wait(), timeout=TIMEOUT_S)


class FakeCore:
    """Core vu de la surface : un flux d'évènements et l'API de tour normale."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[ProtocolEnvelope | None] = asyncio.Queue()
        self.turns: list[dict[str, object]] = []
        self.subscriptions = 0
        self.closed = False

    async def events(self):
        self.subscriptions += 1
        while True:
            event = await self.queue.get()
            if event is None:
                # Fermeture silencieuse : c'est exactement ce que voit un
                # abonné évincé par le bus (Décision 25) — pas d'erreur, juste
                # un flux qui se tait.
                return
            yield event

    async def publish(self, envelope: ProtocolEnvelope) -> None:
        await self.queue.put(envelope)

    async def close_stream(self) -> None:
        await self.queue.put(None)

    async def append_turn(self, conversation_id: str, *, kind: str, content: str, correlation_id=None, metadata=None):  # noqa: ANN001
        self.turns.append(
            {
                "conversation_id": conversation_id,
                "kind": kind,
                "content": content,
                "correlation_id": correlation_id,
                "metadata": metadata or {},
            }
        )
        return {"id": f"turn-{len(self.turns)}"}

    async def create_conversation(self) -> dict[str, str]:
        return {"id": CONVERSATION}

    async def context(self, conversation_id: str) -> dict[str, object]:
        del conversation_id
        return {}

    async def submit_brain_turn(self, conversation_id: str, **kwargs):  # noqa: ANN001
        del conversation_id, kwargs
        return {"turn_id": "turn-x", "revision": 1, "duplicate": False}

    async def call_tool(self, name: str, arguments: dict[str, object], *, conversation_id: str):
        del name, arguments, conversation_id
        return {"ok": True}

    async def close(self) -> None:
        self.closed = True


class FakeVoiceSession:
    """Surface vocale de test : transport `RealtimeSession` + contrôles de sortie.

    `speak()` ne se termine pas toute seule : c'est le test qui décide quand la
    sortie se clôt, ce qui permet d'observer la file pendant que JARVIS parle.
    """

    def __init__(self) -> None:
        self.inbox: asyncio.Queue[ProtocolEnvelope | None] = asyncio.Queue()
        self.spoken: list[SpeechRequest] = []
        self.active_output_id: str | None = None
        self.live_speaks = 0
        self.max_live_speaks = 0
        self.closed = False

    # -- RealtimeSession
    async def send_audio(self, pcm: bytes) -> None:
        del pcm

    async def finish_input(self) -> bool:
        return True

    async def send_tool_result(self, call_id: str, result: dict[str, object]) -> None:
        del call_id, result

    async def send_context(self, text: str) -> None:
        del text

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

    async def push(self, message_type: str, **payload: object) -> None:
        await self.inbox.put(ProtocolEnvelope(message_type=message_type, payload=payload))

    # -- RealtimeOutputControl
    async def speak(self, request: SpeechRequest) -> str:
        self.spoken.append(request)
        self.live_speaks += 1
        self.max_live_speaks = max(self.max_live_speaks, self.live_speaks)
        output_id = f"out-{len(self.spoken)}"
        self.active_output_id = output_id
        return output_id

    async def cancel_output(self, cursor: PlaybackCursor | None = None) -> None:
        del cursor

    async def truncate(self, cursor: PlaybackCursor) -> None:
        del cursor

    def texts(self) -> list[str]:
        return [request.text for request in self.spoken]


class FakeAudio(SoundDeviceRealtimeAudio):
    instances: list["FakeAudio"] = []
    pcm = b"\x01\x00" * 2400

    def __init__(self, *, input_device=None, output_device=None, **rates) -> None:  # noqa: ANN001
        super().__init__(input_device=input_device, output_device=output_device, **rates)
        self.__class__.instances.append(self)

    async def start(self) -> None:
        self._enqueue(self.pcm)

    async def play_b64(self, value: str) -> None:
        del value

    async def close(self) -> None:
        return None


class FakeWakeWord:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.closed = False

    async def detections(self):
        while not self.closed:
            yield await self.queue.get()

    async def suspend(self) -> None:
        return None

    async def suspend_for_active_session(self) -> None:
        return None

    async def resume(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True


async def wait_for(predicate, *, timeout: float = TIMEOUT_S) -> None:
    """Attendre une condition sans supposer combien de tours de boucle il faut."""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition jamais atteinte")


def speech_envelope(
    text: str,
    *,
    kind: SpeechKind = SpeechKind.PROGRESS,
    priority: SpeechPriority = SpeechPriority.NORMAL,
    work_id: str | None = None,
    supersedes_key: str | None = None,
    correlation_id: str = "corr-1",
    speech_id: str | None = None,
    conversation_id: str = CONVERSATION,
    created_offset_s: float = 0.0,
    ttl_s: float | None = None,
) -> ProtocolEnvelope:
    created_at = ORIGIN + timedelta(seconds=created_offset_s)
    request = SpeechRequest(
        conversation_id=conversation_id,
        text=text,
        kind=kind,
        priority=priority,
        id=speech_id or f"speech-{text[:8]}-{created_offset_s}",
        correlation_id=correlation_id,
        work_id=work_id,
        supersedes_key=supersedes_key,
        created_at=created_at,
        expires_at=created_at + timedelta(seconds=ttl_s) if ttl_s else None,
    )
    return ProtocolEnvelope(
        message_type="brain.speech.requested",
        payload=request.to_payload(),
        correlation_id=request.correlation_id,
        conversation_id=request.conversation_id,
    )


def brain_envelope(message_type: str, payload: dict[str, object], *, correlation_id: str = "corr-1") -> ProtocolEnvelope:
    return ProtocolEnvelope(
        message_type=message_type,
        payload={"conversation_id": CONVERSATION, **payload},
        correlation_id=correlation_id,
        conversation_id=CONVERSATION,
    )


def build_scheduler(core, session, *, journal=None, clock=None, on_brain_activity=None, output_timeout_s=5.0, transient_ttl_s=None):
    return SpeechScheduler(
        core=core,
        conversation_id=CONVERSATION,
        session=session,
        journal=journal,
        clock=clock,
        on_brain_activity=on_brain_activity,
        reconnect_delay_s=0.0,
        output_timeout_s=output_timeout_s,
        transient_ttl_s=transient_ttl_s,
    )


async def busy_surface(scheduler: SpeechScheduler, *, output_id: str = "out-surface") -> str:
    """Occuper le fournisseur pour que la file s'accumule au lieu d'être vidée."""

    await scheduler.note_output_event(
        ProtocolEnvelope(message_type="realtime.output_started", payload={"output_id": output_id})
    )
    return output_id


async def release_surface(scheduler: SpeechScheduler, output_id: str, *, status: str = "completed") -> None:
    await scheduler.note_output_event(
        ProtocolEnvelope(
            message_type="realtime.response_done", payload={"output_id": output_id, "status": status}
        )
    )


async def finish_speech(scheduler: SpeechScheduler, session: FakeVoiceSession, *, status: str = "completed") -> None:
    output_id = session.active_output_id
    assert output_id is not None
    session.active_output_id = None
    session.live_speaks = max(0, session.live_speaks - 1)
    await release_surface(scheduler, output_id, status=status)


# ---------------------------------------------------------------------------
# Politique de file
# ---------------------------------------------------------------------------


async def test_speech_from_another_conversation_is_never_spoken():
    """Filtrage par conversation : une session ne parle que pour la sienne."""

    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler = build_scheduler(core, session, journal=journal)
    await scheduler.start()
    try:
        await core.publish(speech_envelope("Pas pour cette session.", conversation_id="conversation-2"))
        await journal.wait_until(lambda: journal.count("voice.speech.ignored") == 1)
        await asyncio.sleep(0.02)
        assert session.spoken == []
    finally:
        await scheduler.stop()


async def test_priority_orders_the_queue_and_fifo_breaks_ties():
    """Priorité décroissante d'abord, ordre d'arrivée ensuite."""

    core, session = FakeCore(), FakeVoiceSession()
    scheduler = build_scheduler(core, session)
    await scheduler.start()
    try:
        held = await busy_surface(scheduler)
        await core.publish(speech_envelope("basse", priority=SpeechPriority.LOW, created_offset_s=1))
        await core.publish(speech_envelope("normale-1", created_offset_s=2))
        await core.publish(
            speech_envelope("urgente", priority=SpeechPriority.IMMEDIATE, kind=SpeechKind.QUESTION, created_offset_s=3)
        )
        await core.publish(speech_envelope("normale-2", created_offset_s=4))
        await wait_for(lambda: scheduler.pending_count == 4)

        await release_surface(scheduler, held)
        for _ in range(4):
            await wait_for(lambda: session.active_output_id is not None)
            await finish_speech(scheduler, session)

        assert session.texts() == ["urgente", "normale-1", "normale-2", "basse"]
    finally:
        await scheduler.stop()


async def test_expired_speech_is_dropped_instead_of_spoken():
    """TTL : une parole dont l'échéance est passée n'est pas rattrapée."""

    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    clock = FakeClock()
    scheduler = build_scheduler(core, session, journal=journal, clock=clock)
    await scheduler.start()
    try:
        held = await busy_surface(scheduler)
        await core.publish(speech_envelope("Je cherche encore.", ttl_s=5))
        await core.publish(speech_envelope("Voici la réponse.", kind=SpeechKind.RESULT, created_offset_s=1))
        await wait_for(lambda: scheduler.pending_count == 2)

        clock.advance(30)
        await release_surface(scheduler, held)
        await wait_for(lambda: session.active_output_id is not None)
        await finish_speech(scheduler, session)

        assert session.texts() == ["Voici la réponse."]
        expired = journal.of("voice.speech.expired")
        assert [event["data"]["reason"] for event in expired] == ["ttl"]
    finally:
        await scheduler.stop()


async def test_a_result_supersedes_the_stale_progress_of_the_same_work():
    """Spec §6 : le résultat final chasse la progression du même travail."""

    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler = build_scheduler(core, session, journal=journal)
    await scheduler.start()
    try:
        held = await busy_surface(scheduler)
        await core.publish(speech_envelope("Je regarde les messages.", work_id="work-1", created_offset_s=1))
        await wait_for(lambda: scheduler.pending_count == 1)
        await core.publish(
            speech_envelope(
                "Trois messages attendent une réponse.",
                kind=SpeechKind.RESULT,
                work_id="work-1",
                created_offset_s=2,
            )
        )
        await wait_for(lambda: scheduler.pending_count == 1)

        await release_surface(scheduler, held)
        await wait_for(lambda: session.active_output_id is not None)
        await finish_speech(scheduler, session)

        assert session.texts() == ["Trois messages attendent une réponse."]
        superseded = journal.of("voice.speech.superseded")
        assert superseded[0]["data"]["reason"] == "superseded"
        assert superseded[0]["message"] == "Je regarde les messages."
    finally:
        await scheduler.stop()


async def test_a_question_preempts_a_low_priority_progress():
    """Une question bloque l'utilisateur : elle passe devant une progression."""

    core, session = FakeCore(), FakeVoiceSession()
    scheduler = build_scheduler(core, session)
    await scheduler.start()
    try:
        held = await busy_surface(scheduler)
        await core.publish(
            speech_envelope("Je continue de chercher.", priority=SpeechPriority.LOW, work_id="work-1", created_offset_s=1)
        )
        await core.publish(
            speech_envelope(
                "Dois-je inclure les archives ?",
                kind=SpeechKind.QUESTION,
                priority=SpeechPriority.HIGH,
                work_id="work-2",
                created_offset_s=2,
            )
        )
        await wait_for(lambda: scheduler.pending_count == 2)

        await release_surface(scheduler, held)
        await wait_for(lambda: session.active_output_id is not None)
        assert session.texts() == ["Dois-je inclure les archives ?"]
    finally:
        await scheduler.stop()


async def test_progress_queued_before_an_intent_revision_is_abandoned():
    """Un nouveau tour utilisateur périme la progression de l'intention précédente."""

    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler = build_scheduler(core, session, journal=journal)
    await scheduler.start()
    try:
        held = await busy_surface(scheduler)
        await core.publish(speech_envelope("Je lis tous les courriels.", work_id="work-1", created_offset_s=1))
        await core.publish(
            speech_envelope(
                "Trois messages attendent une réponse.",
                kind=SpeechKind.RESULT,
                work_id="work-9",
                created_offset_s=1.5,
            )
        )
        await wait_for(lambda: scheduler.pending_count == 2)

        await core.publish(brain_envelope("brain.turn.accepted", {"turn_id": "turn-2", "revision": 2}, correlation_id="corr-2"))
        await wait_for(lambda: scheduler.pending_count == 1)

        await release_surface(scheduler, held)
        await wait_for(lambda: session.active_output_id is not None)
        await finish_speech(scheduler, session)

        # La progression disparaît ; le résultat, lui, est une vérité que seul
        # le cerveau peut retirer (Décisions 14 et 16).
        assert session.texts() == ["Trois messages attendent une réponse."]
        dropped = journal.of("voice.speech.superseded")
        assert dropped[0]["data"]["reason"] == "intent_revised"
    finally:
        await scheduler.stop()


async def test_speech_of_superseded_or_cancelled_work_is_dropped_by_designation():
    """Tâche 09b : Core désigne le travail dont la parole n'est plus vraie.

    Différence avec la règle précédente : celle-ci emporte aussi une parole
    **durable** — un résultat —, parce que c'est le cerveau qui la retire
    (Décision 14) et non une heuristique de surface. Le travail gardé n'est,
    lui, pas touché.
    """

    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler = build_scheduler(core, session, journal=journal)
    await scheduler.start()
    try:
        held = await busy_surface(scheduler)
        for work_id, text in (("work-1", "Je lis les mails."), ("work-2", "Le dossier est prêt."), ("work-3", "Trois réponses attendent.")):
            await core.publish(
                speech_envelope(text, kind=SpeechKind.RESULT, work_id=work_id, created_offset_s=1)
            )
        await wait_for(lambda: scheduler.pending_count == 3)

        await core.publish(
            brain_envelope(
                "brain.intent.revised",
                {
                    "revision": 2,
                    "previous_revision": 1,
                    "superseded_work_ids": ["work-1"],
                    "cancelled_work_ids": ["work-2"],
                    "retained_work_ids": ["work-3"],
                },
                correlation_id="corr-2",
            )
        )
        await wait_for(lambda: scheduler.pending_count == 1)

        await release_surface(scheduler, held)
        await wait_for(lambda: session.active_output_id is not None)
        await finish_speech(scheduler, session)

        assert session.texts() == ["Trois réponses attendent."]
        reasons = {event["data"]["reason"] for event in journal.of("voice.speech.superseded")}
        assert reasons == {"work_superseded", "work_cancelled"}
    finally:
        await scheduler.stop()


async def test_a_revision_without_work_lists_still_drops_stale_progress():
    """Rétention par défaut : sans désignation, seule la parole transitoire tombe."""

    core, session = FakeCore(), FakeVoiceSession()
    scheduler = build_scheduler(core, session)
    await scheduler.start()
    try:
        held = await busy_surface(scheduler)
        await core.publish(speech_envelope("Je lis les mails.", work_id="work-1", created_offset_s=1))
        await core.publish(
            speech_envelope("Trois réponses attendent.", kind=SpeechKind.RESULT, work_id="work-1", created_offset_s=1.5)
        )
        await wait_for(lambda: scheduler.pending_count == 1)

        await core.publish(
            brain_envelope(
                "brain.intent.revised",
                {
                    "revision": 2,
                    "previous_revision": 1,
                    "superseded_work_ids": [],
                    "cancelled_work_ids": [],
                    "retained_work_ids": ["work-1"],
                },
                correlation_id="corr-2",
            )
        )
        await release_surface(scheduler, held)
        await wait_for(lambda: session.active_output_id is not None)
        await finish_speech(scheduler, session)

        # Le travail est gardé : son résultat reste vrai et se dit.
        assert session.texts() == ["Trois réponses attendent."]
    finally:
        await scheduler.stop()


async def test_only_one_brain_output_is_active_at_a_time():
    """Spec §6 : `speak()` ne repart jamais avant la fin de la sortie précédente."""

    core, session = FakeCore(), FakeVoiceSession()
    scheduler = build_scheduler(core, session)
    await scheduler.start()
    try:
        await core.publish(speech_envelope("Première phrase.", created_offset_s=1))
        await core.publish(speech_envelope("Deuxième phrase.", created_offset_s=2))
        await wait_for(lambda: len(session.spoken) == 1)
        await asyncio.sleep(0.05)

        assert session.texts() == ["Première phrase."]
        await finish_speech(scheduler, session)
        await wait_for(lambda: len(session.spoken) == 2)
        assert session.max_live_speaks == 1
    finally:
        await scheduler.stop()


# ---------------------------------------------------------------------------
# Échecs du cerveau
# ---------------------------------------------------------------------------


async def test_the_surface_never_turns_a_work_failure_into_speech():
    """Correction d'orchestrateur A : la décision de parler appartient à Core.

    Remplace `test_the_two_failure_events_of_one_turn_are_spoken_once`, qui
    prouvait l'inverse : l'ordonnanceur fabriquait lui-même une phrase d'erreur
    à partir du `public_summary` de `brain.work.failed`, ce qui remettait de la
    politique de parole dans la surface (Décision 13). Ce repli est retiré ;
    `brain.work.*` est désormais un fait, jamais une parole. La preuve que Core
    prend le relais est dans `test_v2_brain_orchestrator.py`.
    """

    core, session = FakeCore(), FakeVoiceSession()
    scheduler = build_scheduler(core, session)
    await scheduler.start()
    try:
        payload = {
            "job_id": None,
            "error_class": "provider_unavailable",
            "public_summary": "Je n'ai pas pu joindre la messagerie.",
        }
        await core.publish(brain_envelope("brain.work.failed", {"work_id": "work-1", **payload}))
        await core.publish(brain_envelope("brain.work.failed", {"work_id": None, **payload}))
        await asyncio.sleep(0.05)

        assert session.spoken == []
    finally:
        await scheduler.stop()


async def test_the_same_speech_request_is_never_spoken_twice():
    """Déduplication résiduelle après la correction A.

    Core n'émet normalement chaque parole qu'une fois, mais un doublon — une
    republication, un backend maladroit — ne doit pas faire répéter Jarvis. La
    clé est le `speech_id`, pas le texte : deux phrases identiques
    délibérément distinctes restent deux prises de parole.
    """

    core, session = FakeCore(), FakeVoiceSession()
    scheduler = build_scheduler(core, session)
    await scheduler.start()
    try:
        envelope = speech_envelope(
            "Je n'ai pas pu joindre la messagerie.",
            kind=SpeechKind.ERROR,
            priority=SpeechPriority.HIGH,
            work_id="work-1",
            speech_id="speech-error-1",
        )
        await core.publish(envelope)
        await wait_for(lambda: len(session.spoken) == 1)
        await finish_speech(scheduler, session)
        await core.publish(envelope)
        await asyncio.sleep(0.05)

        assert session.texts() == ["Je n'ai pas pu joindre la messagerie."]
        assert session.spoken[0].kind is SpeechKind.ERROR
    finally:
        await scheduler.stop()


async def test_a_transient_speech_without_ttl_gets_the_scheduler_fallback():
    """Correction d'orchestrateur B, côté surface : défense en profondeur.

    Core date lui-même la péremption de la parole transitoire. Ce filet couvre
    le backend futur qui l'oublierait : une progression sans `expires_at` ne
    doit pas rester prononçable indéfiniment (Décision 31).
    """

    clock = FakeClock()
    core, session = FakeCore(), FakeVoiceSession()
    scheduler = build_scheduler(core, session, clock=clock, transient_ttl_s=30.0)
    busy = await busy_surface(scheduler)
    await scheduler.start()
    try:
        await core.publish(speech_envelope("Je consulte encore les mails."))
        await wait_for(lambda: scheduler.pending_count == 1)
        queued = scheduler._pending[0]
        assert queued.expires_at == queued.created_at + timedelta(seconds=30.0)

        clock.advance(31.0)
        await release_surface(scheduler, busy)
        await asyncio.sleep(0.05)
        assert session.spoken == []
    finally:
        await scheduler.stop()


async def test_an_explicit_ttl_is_never_overwritten_by_the_fallback():
    """L'échéance rédigée par le cerveau prime sur le filet de la surface."""

    clock = FakeClock()
    core, session = FakeCore(), FakeVoiceSession()
    scheduler = build_scheduler(core, session, clock=clock, transient_ttl_s=30.0)
    busy = await busy_surface(scheduler)
    await scheduler.start()
    try:
        await core.publish(speech_envelope("Je consulte encore les mails.", ttl_s=5.0))
        await wait_for(lambda: scheduler.pending_count == 1)
        queued = scheduler._pending[0]
        assert queued.expires_at == queued.created_at + timedelta(seconds=5.0)
    finally:
        await release_surface(scheduler, busy)
        await scheduler.stop()


async def test_a_result_never_receives_a_default_ttl():
    """Un résultat reste vrai : il n'a pas de péremption par défaut."""

    clock = FakeClock()
    core, session = FakeCore(), FakeVoiceSession()
    scheduler = build_scheduler(core, session, clock=clock, transient_ttl_s=30.0)
    busy = await busy_surface(scheduler)
    await scheduler.start()
    try:
        await core.publish(speech_envelope("Trois messages attendent une réponse.", kind=SpeechKind.RESULT))
        await wait_for(lambda: scheduler.pending_count == 1)
        assert scheduler._pending[0].expires_at is None
    finally:
        await release_surface(scheduler, busy)
        await scheduler.stop()


# ---------------------------------------------------------------------------
# Reconnexion (Décision 31)
# ---------------------------------------------------------------------------


async def test_an_output_that_never_ends_does_not_mute_the_scheduler_forever():
    """Une fin de sortie perdue ne doit pas condamner la file au silence.

    Le fournisseur peut ouvrir une réponse et ne jamais annoncer sa fin. Le
    délai ne conclut rien tout seul : c'est la comptabilité de la session qui
    tranche, et si elle dit que plus rien ne joue, la file repart.
    """

    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler = build_scheduler(core, session, journal=journal, output_timeout_s=0.05)
    await scheduler.start()
    try:
        await busy_surface(scheduler, output_id="out-perdue")
        await core.publish(speech_envelope("Voici la réponse.", kind=SpeechKind.RESULT))
        await wait_for(lambda: len(session.spoken) == 1)

        stalled = journal.of("voice.speech.output_stalled")[0]
        assert stalled["level"] == "warning"
        assert stalled["data"]["code"] == "speech_surface_stalled"
        assert stalled["data"]["live_outputs"] == ["out-perdue"]
    finally:
        await scheduler.stop()


async def test_a_silent_stream_close_triggers_a_resubscription():
    """Décision 25 : un abonné évincé ne voit rien d'autre qu'un flux qui se tait."""

    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler = build_scheduler(core, session, journal=journal)
    await scheduler.start()
    try:
        await wait_for(lambda: core.subscriptions == 1)
        await core.close_stream()
        await journal.wait_until(lambda: journal.count("voice.speech.stream_closed") == 1)
        await wait_for(lambda: core.subscriptions == 2)

        closure = journal.of("voice.speech.stream_closed")[0]
        assert closure["level"] == "warning"
        assert closure["data"]["code"] == "core_event_stream_closed"

        # L'abonnement est réellement vivant : la parole publiée après la
        # reconnexion est bien prononcée.
        await core.publish(speech_envelope("Reconnecté.", kind=SpeechKind.RESULT))
        await wait_for(lambda: session.texts() == ["Reconnecté."])
    finally:
        await scheduler.stop()


async def test_stale_progress_is_not_replayed_after_a_reconnection():
    """Décision 31 : on périme, on ne rejoue pas."""

    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler = build_scheduler(core, session, journal=journal)
    await scheduler.start()
    try:
        held = await busy_surface(scheduler)
        await core.publish(speech_envelope("Je cherche encore.", work_id="work-1", created_offset_s=1))
        await wait_for(lambda: scheduler.pending_count == 1)

        await core.close_stream()
        await wait_for(lambda: core.subscriptions == 2)
        assert scheduler.pending_count == 0

        await release_surface(scheduler, held)
        await asyncio.sleep(0.05)
        assert session.spoken == []
        assert journal.of("voice.speech.superseded")[0]["data"]["reason"] == "stream_gap"
    finally:
        await scheduler.stop()


async def test_a_revision_gap_drops_the_speech_that_may_no_longer_be_true():
    """`brain.state.updated` porte une révision monotone : un saut est un trou."""

    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler = build_scheduler(core, session, journal=journal)
    await scheduler.start()
    try:
        held = await busy_surface(scheduler)
        await core.publish(brain_envelope("brain.state.updated", {"revision": 4}))
        await core.publish(speech_envelope("Je continue.", work_id="work-1", created_offset_s=1))
        await wait_for(lambda: scheduler.pending_count == 1)

        await core.publish(brain_envelope("brain.state.updated", {"revision": 7}))
        await journal.wait_until(lambda: journal.count("voice.speech.revision_gap") == 1)

        gap = journal.of("voice.speech.revision_gap")[0]
        assert gap["level"] == "warning"
        assert gap["data"]["expected_revision"] == 5
        assert gap["data"]["received_revision"] == 7
        assert scheduler.pending_count == 0

        await release_surface(scheduler, held)
        await asyncio.sleep(0.05)
        assert session.spoken == []
    finally:
        await scheduler.stop()



async def test_an_uncertain_turn_repeating_a_revision_is_not_a_gap():
    """Décision 44 : un tour incertain accuse sans réviser, puis révise s'il est pris.

    L'ordonnanceur voit donc deux fois le même numéro — `brain.turn.accepted`
    porte la révision courante, inchangée — avant que la promotion ne reprenne
    la suite. Répéter n'est pas sauter : aucun `voice.speech.revision_gap` ne
    doit être journalisé, sans quoi la moitié aval de la Décision 44
    déclencherait un abandon de parole à chaque phrase captée à côté.
    """

    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler = build_scheduler(core, session, journal=journal)
    await scheduler.start()
    try:
        # Tour adressé : accusé, révision, état — tout à 1.
        await core.publish(brain_envelope("brain.turn.accepted", {"turn_id": "turn-1", "revision": 1}))
        await core.publish(brain_envelope("brain.state.updated", {"revision": 1}))
        # Tour incertain : accusé seul, révision inchangée.
        await core.publish(
            brain_envelope("brain.turn.accepted", {"turn_id": "turn-2", "revision": 1}, correlation_id="corr-2")
        )
        # Le cerveau prend le tour : la révision reprend la suite.
        await core.publish(
            brain_envelope(
                "brain.intent.revised",
                {"revision": 2, "previous_revision": 1, "retained_work_ids": [], "superseded_work_ids": [], "cancelled_work_ids": []},
                correlation_id="corr-2",
            )
        )
        await core.publish(brain_envelope("brain.state.updated", {"revision": 2}, correlation_id="corr-2"))
        await core.publish(speech_envelope("Le plombier est prévenu.", work_id="work-1", correlation_id="corr-2"))
        await wait_for(lambda: session.spoken != [])

        assert journal.count("voice.speech.revision_gap") == 0
        assert session.texts() == ["Le plombier est prévenu."]
    finally:
        await scheduler.stop()

# ---------------------------------------------------------------------------
# Provenance, télémétrie, activité utile
# ---------------------------------------------------------------------------


async def test_brain_speech_is_persisted_with_its_provenance():
    """Spec §15 : le tour assistant dit d'où vient ce que l'utilisateur a entendu."""

    core, session = FakeCore(), FakeVoiceSession()
    scheduler = build_scheduler(core, session)
    await scheduler.start()
    try:
        await core.publish(
            speech_envelope(
                "Trois messages attendent une réponse.",
                kind=SpeechKind.RESULT,
                work_id="work-1",
                correlation_id="corr-42",
                speech_id="speech-42",
            )
        )
        await wait_for(lambda: len(session.spoken) == 1)
        assert core.turns == []  # rien n'est persisté avant que ce soit dit

        await finish_speech(scheduler, session)
        await wait_for(lambda: len(core.turns) == 1)

        turn = core.turns[0]
        assert turn["kind"] == "assistant"
        assert turn["content"] == "Trois messages attendent une réponse."
        assert turn["correlation_id"] == "corr-42"
        assert turn["metadata"]["provenance"] == SpeechProvenance.BRAIN.value
        assert turn["metadata"]["speech_id"] == "speech-42"
        assert turn["metadata"]["work_id"] == "work-1"
        assert turn["metadata"]["speech_kind"] == SpeechKind.RESULT.value
    finally:
        await scheduler.stop()


@pytest.mark.parametrize("missing_completion", ["no_response", "lost_completion", "missing_status"])
async def test_unconfirmed_speech_is_not_persisted_and_the_queue_continues(missing_completion):
    """Ni refus asynchrone ni fin perdue ne prouvent que le texte a été entendu."""

    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler = build_scheduler(core, session, journal=journal, output_timeout_s=0.02)
    await scheduler.start()
    try:
        await core.publish(speech_envelope("Phrase non confirmée.", kind=SpeechKind.RESULT, speech_id="unconfirmed"))
        await wait_for(lambda: len(session.spoken) == 1)
        first_output = session.active_output_id
        assert first_output is not None
        if missing_completion == "lost_completion":
            await scheduler.note_output_event(
                ProtocolEnvelope(message_type="realtime.output_started", payload={"output_id": first_output})
            )
            await scheduler.note_output_event(
                ProtocolEnvelope(message_type="realtime.audio", payload={"output_id": first_output, "speech_id": "unconfirmed"})
            )
        session.active_output_id = None
        session.live_speaks = 0
        if missing_completion == "missing_status":
            await scheduler.note_output_event(
                ProtocolEnvelope(message_type="realtime.response_done", payload={"output_id": first_output})
            )
        await core.publish(speech_envelope("Réponse suivante.", kind=SpeechKind.RESULT, speech_id="confirmed"))
        await wait_for(lambda: len(session.spoken) == 2)

        assert core.turns == []
        assert journal.of("voice.speech.completed") == []
        interrupted = journal.of("voice.speech.interrupted")
        assert len(interrupted) == 1
        assert interrupted[0]["data"]["status"] == "unknown"
        assert interrupted[0]["data"]["speech_id"] == "unconfirmed"
        if missing_completion != "missing_status":
            stalled = journal.of("voice.speech.output_stalled")
            assert stalled[-1]["data"]["code"] == "speech_output_stalled"
            assert stalled[-1]["data"]["still_active"] is False
        # Une notification tardive de l'ancienne sortie ne termine pas la suivante.
        await release_surface(scheduler, first_output, status="failed")
        assert core.turns == []
        await finish_speech(scheduler, session)
        await wait_for(lambda: len(core.turns) == 1)
        assert core.turns[0]["content"] == "Réponse suivante."
        assert core.turns[0]["metadata"]["speech_id"] == "confirmed"
        assert len(journal.of("voice.speech.completed")) == 1
    finally:
        await scheduler.stop()


@pytest.mark.parametrize("alive_source", ["provider", "local_playback"])
async def test_missing_completion_keeps_waiting_while_output_is_alive(alive_source):
    """Le délai sonde la lecture ; une phrase longue n'est pas abandonnée."""

    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler = build_scheduler(core, session, journal=journal, output_timeout_s=0.02)
    await scheduler.start()
    try:
        await core.publish(speech_envelope("Longue phrase.", kind=SpeechKind.RESULT, speech_id="long"))
        await wait_for(lambda: len(session.spoken) == 1)
        output_id = session.active_output_id
        if alive_source == "local_playback":
            session.active_output_id = None
            scheduler.output_alive = lambda candidate: candidate == output_id
        await core.publish(speech_envelope("À la suite.", kind=SpeechKind.RESULT, speech_id="next"))
        await journal.wait_until(lambda: journal.count("voice.speech.output_stalled") > 0)
        assert journal.of("voice.speech.output_stalled")[-1]["data"]["still_active"] is True
        assert len(session.spoken) == 1
        assert core.turns == []
        assert journal.of("voice.speech.interrupted") == []
        session.active_output_id = None
        session.live_speaks = 0
        scheduler.output_alive = None
        await release_surface(scheduler, output_id)
        await wait_for(lambda: len(session.spoken) == 2)
        assert [turn["content"] for turn in core.turns] == ["Longue phrase."]
    finally:
        await scheduler.stop()


async def test_an_interrupted_output_is_not_persisted_as_heard():
    """Une réponse qui ne s'est pas terminée n'a pas été entendue en entier.

    Ici le fournisseur seul annonce `cancelled`, sans qu'aucun curseur ne dise
    ce qui a été joué : rien n'a été entendu de façon prouvable, donc rien n'est
    persisté. Le cas symétrique — une phrase coupée par la parole de
    l'utilisateur, avec ses millisecondes — est dans `test_v2_barge_in.py`.
    """

    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler = build_scheduler(core, session, journal=journal)
    await scheduler.start()
    try:
        await core.publish(speech_envelope("Je regarde.", kind=SpeechKind.PROGRESS))
        await wait_for(lambda: len(session.spoken) == 1)
        await finish_speech(scheduler, session, status="cancelled")
        await journal.wait_until(lambda: journal.count("voice.speech.interrupted") == 1)

        assert core.turns == []
        assert journal.of("voice.speech.interrupted")[0]["data"]["status"] == "cancelled"
    finally:
        await scheduler.stop()


async def test_delivery_telemetry_reaches_the_journal():
    """docs/05 : la télémétrie de livraison est journalisée localement."""

    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler = build_scheduler(core, session, journal=journal)
    await scheduler.start()
    try:
        await core.publish(speech_envelope("Voici la réponse.", kind=SpeechKind.RESULT, work_id="work-1"))
        await wait_for(lambda: len(session.spoken) == 1)
        await finish_speech(scheduler, session)
        await journal.wait_until(lambda: journal.count("voice.speech.completed") == 1)

        kinds = [event["kind"] for event in journal.events if str(event["kind"]).startswith("voice.speech.")]
        assert kinds[:3] == ["voice.speech.queued", "voice.speech.started", "voice.speech.completed"]
        queued = journal.of("voice.speech.queued")[0]
        assert queued["data"]["work_id"] == "work-1"
        assert queued["data"]["kind"] == "result"
        assert queued["data"]["priority"] == "normal"
        assert queued["message"] == "Voici la réponse."
    finally:
        await scheduler.stop()


async def test_every_brain_event_rearms_the_useful_activity_timeout():
    """Décision 32 : le travail du cerveau est de l'activité utile."""

    core, session = FakeCore(), FakeVoiceSession()
    rearms: list[str] = []

    async def on_brain_activity() -> None:
        rearms.append("brain")

    scheduler = build_scheduler(core, session, on_brain_activity=on_brain_activity)
    await scheduler.start()
    try:
        await core.publish(brain_envelope("brain.turn.accepted", {"turn_id": "turn-1", "revision": 1}))
        await core.publish(brain_envelope("brain.work.started", {"work_id": "work-1", "public_label": "Recherche"}))
        await core.publish(brain_envelope("brain.work.progress", {"work_id": "work-1", "public_summary": "en cours"}))
        await wait_for(lambda: len(rearms) == 3)

        # Un évènement d'une autre conversation ne prolonge rien.
        await core.publish(
            ProtocolEnvelope(
                message_type="brain.work.progress",
                payload={"conversation_id": "conversation-2", "work_id": "work-9"},
                conversation_id="conversation-2",
            )
        )
        await asyncio.sleep(0.05)
        assert len(rearms) == 3
    finally:
        await scheduler.stop()


# ---------------------------------------------------------------------------
# Mute et retour au fond (Décision 33)
# ---------------------------------------------------------------------------


async def test_stopping_expires_the_queued_speech():
    """Mute pendant qu'une parole est en file : elle périme, elle n'attend pas."""

    core, session, journal = FakeCore(), FakeVoiceSession(), RecordingJournal()
    scheduler = build_scheduler(core, session, journal=journal)
    await scheduler.start()
    await busy_surface(scheduler)
    await core.publish(speech_envelope("Voici la réponse.", kind=SpeechKind.RESULT))
    await wait_for(lambda: scheduler.pending_count == 1)

    await scheduler.stop()

    assert session.spoken == []
    assert scheduler.pending_count == 0
    assert scheduler.running is False
    expired = journal.of("voice.speech.expired")[0]
    assert expired["data"]["reason"] == "voice_background"


async def test_stopping_while_an_output_is_being_written_persists_nothing():
    """Mute pendant l'écriture d'une sortie : pas de tour fantôme.

    Le tour assistant n'est écrit qu'après une fin de sortie confirmée. Couper
    au milieu ne doit donc rien laisser derrière : ce que l'utilisateur n'a pas
    fini d'entendre n'est pas archivé comme entendu.
    """

    core, session = FakeCore(), FakeVoiceSession()
    scheduler = build_scheduler(core, session)
    await scheduler.start()
    await core.publish(speech_envelope("Une phrase très longue.", kind=SpeechKind.RESULT))
    await wait_for(lambda: len(session.spoken) == 1)

    await scheduler.stop()

    assert core.turns == []
    assert scheduler.running is False


# ---------------------------------------------------------------------------
# Câblage dans le runtime vocal
# ---------------------------------------------------------------------------


def _runtime(monkeypatch, *, journal, clock=None, timeout_s=90.0):
    import jarvis.runtime.realtime_audio as realtime_audio

    FakeAudio.instances.clear()
    monkeypatch.setattr(realtime_audio, "SoundDeviceRealtimeAudio", FakeAudio)

    core = FakeCore()
    session = FakeVoiceSession()
    wakeword = FakeWakeWord()

    async def factory(context):
        del context
        return session

    runtime = PersistentVoiceRuntime(
        wakeword=wakeword,  # type: ignore[arg-type]
        core=core,  # type: ignore[arg-type]
        realtime_factory=factory,  # type: ignore[arg-type]
        active_timeout_s=timeout_s,
        clock=clock,
        journal=journal,  # type: ignore[arg-type]
        auto_turn=True,
        voice_arch=VoiceArchitecture.CONTINUOUS_BRAIN,
    )
    return runtime, wakeword, core, session


async def _wake(runtime, wakeword, journal):
    run_task = asyncio.create_task(runtime.run())
    await wakeword.queue.put("f9")
    await journal.wait_until(lambda: journal.count("audio.start") == 1)
    return run_task


async def test_nothing_is_spoken_once_voice_returned_to_background(monkeypatch):
    """Décision 33 : un résultat arrivé après le mute ne réveille pas la surface."""

    journal = RecordingJournal()
    runtime, wakeword, core, session = _runtime(monkeypatch, journal=journal)
    run_task = await _wake(runtime, wakeword, journal)
    try:
        # Une sortie de surface occupe le fournisseur : la parole reste en file.
        await session.push("realtime.output_started", output_id="out-surface")
        await journal.wait_until(lambda: journal.count("voice.output_started") == 1)
        await core.publish(speech_envelope("Le travail est fini.", kind=SpeechKind.RESULT))
        await journal.wait_until(lambda: journal.count("voice.speech.queued") == 1)

        await runtime.mute()
        assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND
        assert journal.of("voice.speech.expired")[0]["data"]["reason"] == "voice_background"

        # Le cerveau termine après le retour au fond : personne ne l'entend, et
        # rien n'est prononcé sans une nouvelle activation.
        await core.publish(speech_envelope("Et voici le détail.", kind=SpeechKind.RESULT, created_offset_s=5))
        await asyncio.sleep(0.05)
        assert session.spoken == []
        assert core.turns == []
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


async def test_brain_work_rearms_the_inactivity_timeout(monkeypatch):
    """Décision 32, câblée : le cerveau qui travaille garde la session ouverte."""

    journal = RecordingJournal()
    clock = FakeClock()
    runtime, wakeword, core, session = _runtime(monkeypatch, journal=journal, clock=clock, timeout_s=10)
    run_task = await _wake(runtime, wakeword, journal)
    try:
        clock.advance(8)
        assert runtime.activity.expired() is False

        await core.publish(brain_envelope("brain.work.progress", {"work_id": "work-1", "public_summary": "en cours"}))
        await core.publish(speech_envelope("Je regarde les messages.", created_offset_s=1))
        await journal.wait_until(lambda: journal.count("voice.speech.started") == 1)

        clock.advance(3)
        assert runtime.activity.expired() is False
        assert await runtime.check_timeout() is False
        assert runtime.runtime.state is VoiceLifecycleState.ACTIVE

        # Le délai repart du dernier évènement cerveau : un cerveau muet finit
        # par rendre la session au fond.
        clock.advance(20)
        assert await runtime.check_timeout() is True
        assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


async def test_the_bridge_does_not_persist_the_transcript_of_brain_speech(monkeypatch):
    """Un seul tour assistant par parole du cerveau, avec la bonne provenance.

    Le fournisseur transcrit ce qu'il prononce ; ce transcript porte le
    `speech_id` de la demande. Le persister ici aussi écrirait le même tour deux
    fois, dont une sous `surface.reflex` (spec §15).
    """

    journal = RecordingJournal()
    runtime, wakeword, core, session = _runtime(monkeypatch, journal=journal)
    run_task = await _wake(runtime, wakeword, journal)
    try:
        await session.push("realtime.assistant_transcript", text="Trois messages.", speech_id="speech-42", output_id="out-1")
        await journal.wait_until(lambda: journal.count("voice.assistant") == 1)
        await asyncio.sleep(0.02)
        assert core.turns == []

        # Un réflexe de surface, lui, reste persisté et étiqueté comme tel.
        await session.push("realtime.assistant_transcript", text="Oui.", speech_id=None, output_id="out-2")
        await wait_for(lambda: len(core.turns) == 1)
        assert core.turns[0]["metadata"]["provenance"] == SpeechProvenance.SURFACE_REFLEX.value
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)
