"""Télémétrie de latence et portes de déploiement (tâche 12a).

Ce fichier prouve trois choses, et rien d'autre.

1. Les **six** mesures de `docs/handoff-realtime-brain/docs/04-testing-and-quality.md`
   (section « Latency telemetry ») sont réellement émises, chacune avec une clé
   de jointure — `correlation_id`, `speech_id` ou `work_id` — sans quoi le
   chiffre ne se rattache à rien et ne sert à rien.
2. Aucune d'elles ne porte de corps de transcription, d'invite ou de résumé
   rédigé : la section « Privacy tests » du même document est un contrat, pas
   une intention. Le test cherche le texte réel employé par le scénario dans la
   sérialisation complète de l'évènement, message compris.
3. La porte de la Décision 34 tient : `legacy` reste le défaut tant qu'un
   bloqueur subsiste, l'opt-in continu et le retour arrière fonctionnent.

Ce qui n'est **pas** prouvé ici, et ne peut l'être que sur poste réel : que les
millisecondes mesurées correspondent à ce que l'oreille perçoit. Aucun
périphérique audio n'est dans la boucle.
"""

from __future__ import annotations

import asyncio
import base64
import json

import pytest

from jarvis.adapters.jsonl_history import JsonlHistoryStore
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.brain_service import (
    BRAIN_FIRST_PROGRESS_LATENCY_KIND,
    BRAIN_WORK_COMPLETED_LATENCY_KIND,
    BrainOrchestrator,
)
from jarvis.core.latency import (
    BRAIN_TURN_ACCEPTED,
    FIRST_BRAIN_AUDIO,
    FIRST_PUBLIC_PROGRESS,
    LATENCY_MEASURES,
    LOCAL_OUTPUT_STOPPED,
    SURFACE_FIRST_AUDIO,
    WORK_COMPLETED,
    LatencyTracker,
)
from jarvis.core.v2_services import ConversationService, CoreEventBus
from jarvis.domain.v2 import (
    BrainEvent,
    BrainEventKind,
    BrainTurnInput,
    BrainTurnResult,
    ProtocolEnvelope,
    SpeechKind,
    SpeechProvenance,
    SpeechRequest,
)
from jarvis.runtime.realtime_audio import (
    LATENCY_BRAIN_TURN_ACCEPTED_KIND,
    LATENCY_SURFACE_FIRST_AUDIO_KIND,
    RealtimeConversationBridge,
    SoundDeviceRealtimeAudio,
)
from jarvis.runtime.speech_scheduler import (
    LATENCY_FIRST_BRAIN_AUDIO_KIND,
    SpeechScheduler,
)
from jarvis.v2_config import (
    ConfigurationError,
    V2Settings,
    VoiceArchitecture,
    continuous_brain_default_blockers,
    default_voice_arch,
    parse_voice_arch,
)

CONVERSATION = "conv-latency"
CHUNK_FRAMES = SoundDeviceRealtimeAudio.OUTPUT_CHUNK_FRAMES

# Textes du scénario. Ils ne doivent apparaître dans **aucun** évènement de
# latence : c'est exactement ce que la recherche de confidentialité traque.
USER_TEXT = "Jarvis, supprime le rapport trimestriel confidentiel du Drive"
BRAIN_TEXT = "Le rapport trimestriel confidentiel a été mis à la corbeille."
WORK_LABEL = "Suppression du rapport trimestriel confidentiel"

# Les six kinds d'évènement, dans l'ordre des six mesures.
LATENCY_KINDS = {
    SURFACE_FIRST_AUDIO: LATENCY_SURFACE_FIRST_AUDIO_KIND,
    BRAIN_TURN_ACCEPTED: LATENCY_BRAIN_TURN_ACCEPTED_KIND,
    FIRST_BRAIN_AUDIO: LATENCY_FIRST_BRAIN_AUDIO_KIND,
    LOCAL_OUTPUT_STOPPED: "voice.barge_in",
    FIRST_PUBLIC_PROGRESS: BRAIN_FIRST_PROGRESS_LATENCY_KIND,
    WORK_COMPLETED: BRAIN_WORK_COMPLETED_LATENCY_KIND,
}


# --- doubles -----------------------------------------------------------------


class RecordingJournal:
    """Journal de test : même signature que `RuntimeJournal.emit`."""

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, kind: str, message: str, *, level: str = "info", data=None) -> None:  # noqa: ANN001
        self.events.append({"kind": kind, "message": message, "level": level, "data": data or {}})

    def of(self, kind: str) -> list[dict[str, object]]:
        return [event for event in self.events if event["kind"] == kind]

    def measures(self) -> set[str]:
        """Les mesures effectivement observées, quelle qu'en soit la source."""

        return {
            str(event["data"].get("measure"))  # type: ignore[union-attr]
            for event in self.events
            if isinstance(event["data"], dict) and event["data"].get("measure")
        }


class RecordingCore:
    """Core vu de la surface : ingress cerveau et tours."""

    def __init__(self) -> None:
        self.brain_turns: list[dict[str, object]] = []
        self.turns: list[dict[str, object]] = []

    async def submit_brain_turn(
        self,
        conversation_id: str,
        *,
        content: str,
        correlation_id: str,
        source: str = "realtime",
        addressing: str = "addressed",
        provider_item_id=None,  # noqa: ANN001
        interrupted_speech_id=None,  # noqa: ANN001
    ) -> dict[str, object]:
        self.brain_turns.append({"conversation_id": conversation_id, "content": content, "correlation_id": correlation_id})
        return {"turn_id": f"turn-{len(self.brain_turns)}", "revision": len(self.brain_turns), "duplicate": False}

    async def append_turn(self, conversation_id: str, *, kind: str, content: str, correlation_id=None, metadata=None):  # noqa: ANN001
        self.turns.append({"conversation_id": conversation_id, "kind": kind, "content": content})
        return {"id": f"turn-{len(self.turns)}"}

    async def events(self):  # pragma: no cover - les tests appellent handle_core_event
        return
        yield


class SilentSession:
    """Pile vocale de test : `RealtimeOutputControl` sans périphérique."""

    def __init__(self) -> None:
        self.spoken: list[SpeechRequest] = []
        self.active_output_id: str | None = None

    async def send_audio(self, pcm: bytes) -> None:
        del pcm

    async def finish_input(self) -> bool:
        return True

    async def send_tool_result(self, call_id: str, result: dict[str, object]) -> None:
        del call_id, result

    async def send_context(self, text: str) -> None:
        del text

    async def events(self):  # pragma: no cover - les tests injectent les évènements
        return
        yield

    async def close(self) -> None:
        return None

    async def speak(self, request: SpeechRequest) -> str:
        self.spoken.append(request)
        self.active_output_id = f"out-{len(self.spoken)}"
        return self.active_output_id

    async def cancel_output(self, cursor=None) -> None:  # noqa: ANN001
        del cursor

    async def truncate(self, cursor) -> None:  # noqa: ANN001
        del cursor


class DevicelessAudio(SoundDeviceRealtimeAudio):
    """Comptabilise la lecture sans jamais toucher PortAudio."""

    async def play_b64(self, value: str) -> None:
        self._credit_written(self._output_epoch, len(base64.b64decode(value)))

    async def stop_output(self) -> None:
        await super().stop_output()

    async def close(self) -> None:
        return None


class WorkingBackend:
    """Cerveau factice : accepte un travail, progresse, puis termine."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def run_turn(self, turn: BrainTurnInput, state, emit) -> BrainTurnResult:  # noqa: ANN001
        del state
        for kind in (BrainEventKind.ACCEPTED, BrainEventKind.PROGRESS):
            await emit.emit(
                BrainEvent(
                    kind=kind,
                    conversation_id=turn.conversation_id,
                    correlation_id=turn.correlation_id,
                    work_id="work-1",
                    public_summary=WORK_LABEL,
                )
            )
        final = BrainEventKind.FAILED if self.fail else BrainEventKind.COMPLETED
        await emit.emit(
            BrainEvent(
                kind=final,
                conversation_id=turn.conversation_id,
                correlation_id=turn.correlation_id,
                work_id="work-1",
                public_summary=WORK_LABEL,
                error="drive_unavailable" if self.fail else None,
            )
        )
        return BrainTurnResult(correlation_id=turn.correlation_id)


# --- utilitaires -------------------------------------------------------------


def pcm_b64(chunks: int = 1) -> str:
    return base64.b64encode(b"\x01\x00" * (CHUNK_FRAMES * chunks)).decode()


def audio_delta(**payload: object) -> ProtocolEnvelope:
    return ProtocolEnvelope(message_type="realtime.audio", payload={"pcm_b64": pcm_b64(), **payload})


def transcript(text: str, *, item_id: str = "item-1") -> ProtocolEnvelope:
    return ProtocolEnvelope(message_type="realtime.transcript", payload={"text": text, "item_id": item_id})


def speech_started() -> ProtocolEnvelope:
    return ProtocolEnvelope(message_type="realtime.speech_started", payload={})


def build_bridge(*, core, journal, audio=None, session=None, continuous: bool = True):  # noqa: ANN001
    return RealtimeConversationBridge(
        core=core,
        session=session or SilentSession(),
        conversation_id=CONVERSATION,
        audio=audio or DevicelessAudio(),
        on_addressed=lambda: None,
        on_mute=lambda: None,
        auto_turn=True,
        continuous=continuous,
        journal=journal,
    )


async def feed(bridge: RealtimeConversationBridge, events: list[ProtocolEnvelope]) -> None:
    async def stream():
        for event in events:
            yield event

    await bridge._consume(stream())


def assert_free_of_content(events: list[dict[str, object]], *forbidden: str) -> None:
    """Aucun corps de transcription ni de parole dans la sérialisation complète.

    Le message est inclus dans la recherche à dessein : le journal l'écrit au
    même titre que `data`, et c'est par lui que les fuites passent d'habitude.
    """

    assert events, "aucun évènement à contrôler : le test ne prouverait rien"
    for event in events:
        blob = json.dumps(event, ensure_ascii=False, default=str)
        for text in forbidden:
            assert text not in blob, f"{event['kind']} porte du contenu: {text!r}"
        for word in ("rapport", "trimestriel", "confidentiel"):
            assert word not in blob.casefold(), f"{event['kind']} porte un fragment de contenu: {word!r}"


# --- LatencyTracker ----------------------------------------------------------


def test_tracker_measures_only_a_mark_it_actually_opened():
    ticks = iter([1.0, 1.25, 5.0])
    journal = RecordingJournal()
    tracker = LatencyTracker(journal, clock=lambda: next(ticks))

    tracker.mark(SURFACE_FIRST_AUDIO, "seg-1")
    assert tracker.measure(SURFACE_FIRST_AUDIO, "seg-1", kind="voice.latency.test") == 250.0
    # Marque consommée : une seconde borne d'arrivée n'invente pas de chiffre.
    assert tracker.measure(SURFACE_FIRST_AUDIO, "seg-1", kind="voice.latency.test") is None
    assert len(journal.events) == 1
    assert journal.events[0]["data"] == {"measure": SURFACE_FIRST_AUDIO, "elapsed_ms": 250.0}


def test_tracker_forgets_and_stays_bounded():
    tracker = LatencyTracker(None, pending_limit=2, clock=lambda: 0.0)

    tracker.mark(WORK_COMPLETED, "work-1")
    tracker.forget(WORK_COMPLETED, "work-1")
    assert tracker.measure(WORK_COMPLETED, "work-1", kind="core.brain.latency.test") is None

    for index in range(5):
        tracker.mark(WORK_COMPLETED, f"work-{index}")
    # Une borne d'arrivée peut ne jamais venir : la mémoire reste bornée.
    assert tracker.pending_count == 2
    assert tracker.measure(WORK_COMPLETED, "work-0", kind="core.brain.latency.test") is None


def test_tracker_message_is_built_here_so_no_caller_can_leak_through_it():
    journal = RecordingJournal()
    tracker = LatencyTracker(journal, clock=lambda: 0.0)
    tracker.mark(BRAIN_TURN_ACCEPTED, CONVERSATION)
    tracker.measure(BRAIN_TURN_ACCEPTED, CONVERSATION, kind="voice.latency.test", data={"correlation_id": "corr-1"})

    assert journal.events[0]["message"] == f"Latence {BRAIN_TURN_ACCEPTED}: 0.0 ms"


def test_the_six_documented_measures_are_all_declared():
    """`04-testing-and-quality.md` en liste six : aucune ne doit disparaître."""

    assert len(LATENCY_MEASURES) == 6
    assert len(set(LATENCY_MEASURES)) == 6
    assert set(LATENCY_KINDS) == set(LATENCY_MEASURES)


# --- mesures 1, 2 et 4 : la surface vocale -----------------------------------


async def test_first_audio_after_user_speech_is_timed_and_joinable():
    """Mesure 1 : `speech_started -> surface_first_audio`, jointe par `segment_id`."""

    journal = RecordingJournal()
    bridge = build_bridge(core=RecordingCore(), journal=journal)

    await feed(bridge, [speech_started(), audio_delta(output_id="out-1"), audio_delta(output_id="out-1")])

    emitted = journal.of(LATENCY_SURFACE_FIRST_AUDIO_KIND)
    # Un seul évènement bien que deux blocs audio soient arrivés : c'est le
    # *premier* son qui mesure l'attente, pas chacun d'eux.
    assert len(emitted) == 1
    data = emitted[0]["data"]
    assert data["measure"] == SURFACE_FIRST_AUDIO
    assert isinstance(data["elapsed_ms"], float)
    assert data["segment_id"]
    assert data["conversation_id"] == CONVERSATION
    # Sans `speech_id`, le son vient d'un réflexe de surface, pas du cerveau.
    assert data["speech_id"] is None
    assert data["source"] == SpeechProvenance.SURFACE_REFLEX.value


async def test_first_audio_without_a_user_segment_invents_nothing():
    journal = RecordingJournal()
    bridge = build_bridge(core=RecordingCore(), journal=journal)

    await feed(bridge, [audio_delta(output_id="out-1")])

    assert journal.of(LATENCY_SURFACE_FIRST_AUDIO_KIND) == []


async def test_brain_turn_acceptance_is_timed_and_joins_on_correlation():
    """Mesure 2 : `transcript_completed -> brain_turn_accepted`."""

    core = RecordingCore()
    journal = RecordingJournal()
    bridge = build_bridge(core=core, journal=journal)

    await feed(bridge, [speech_started(), transcript(USER_TEXT)])

    emitted = journal.of(LATENCY_BRAIN_TURN_ACCEPTED_KIND)
    assert len(emitted) == 1
    data = emitted[0]["data"]
    assert data["measure"] == BRAIN_TURN_ACCEPTED
    assert isinstance(data["elapsed_ms"], float)
    # Clé de jointure : la corrélation que Core a réellement acceptée.
    assert data["correlation_id"] == core.brain_turns[0]["correlation_id"]
    assert data["turn_id"] == "turn-1"
    # Et le segment de parole ouvert par le VAD relie cette mesure à la
    # mesure 1 du même tour, dont c'est la clé de jointure.
    assert data["segment_id"] == bridge._speech_segment_id
    assert data["segment_id"]


async def test_a_refused_brain_turn_leaves_no_latency_behind():
    """Un tour refusé n'a pas de latence d'acceptation : rien n'est émis."""

    class RefusingCore(RecordingCore):
        async def submit_brain_turn(self, conversation_id: str, **kwargs):  # noqa: ANN001, ANN003
            del conversation_id, kwargs
            raise RuntimeError("core down")

    journal = RecordingJournal()
    bridge = build_bridge(core=RefusingCore(), journal=journal)

    await feed(bridge, [speech_started(), transcript(USER_TEXT)])

    assert journal.of(LATENCY_BRAIN_TURN_ACCEPTED_KIND) == []
    # La marque est abandonnée, pas seulement inexploitée : le tour suivant ne
    # peut donc pas hériter du chronomètre de celui-ci.
    assert bridge._latency.measure(BRAIN_TURN_ACCEPTED, CONVERSATION, kind="voice.latency.test") is None


async def test_surface_latency_events_carry_no_transcript_body():
    """« Privacy tests » : identifiants, horodatages, types et tailles seulement."""

    journal = RecordingJournal()
    bridge = build_bridge(core=RecordingCore(), journal=journal)

    await feed(bridge, [speech_started(), audio_delta(output_id="out-1"), transcript(USER_TEXT)])

    assert_free_of_content(
        journal.of(LATENCY_SURFACE_FIRST_AUDIO_KIND) + journal.of(LATENCY_BRAIN_TURN_ACCEPTED_KIND),
        USER_TEXT,
    )


async def test_barge_in_names_the_interrupt_measure_it_has_always_carried():
    """Mesure 4 : posée par la tranche 09c, seul son nom manquait.

    L'évènement n'est pas dupliqué : `stop_latency_ms` existait déjà et reste
    la vérité du chiffre. `measure` et `elapsed_ms` le rendent seulement
    trouvable comme les cinq autres.
    """

    journal = RecordingJournal()
    audio = DevicelessAudio()
    bridge = build_bridge(core=RecordingCore(), journal=journal, audio=audio)

    await feed(
        bridge,
        [
            ProtocolEnvelope(message_type="realtime.output_started", payload={"output_id": "out-1", "speech_id": "sp-1"}),
            audio_delta(output_id="out-1", speech_id="sp-1"),
            speech_started(),
        ],
    )

    events = journal.of("voice.barge_in")
    assert len(events) == 1
    data = events[0]["data"]
    assert data["measure"] == LOCAL_OUTPUT_STOPPED
    assert data["elapsed_ms"] == data["stop_latency_ms"]
    # Clé de jointure : la parole qui jouait au moment de la coupure.
    assert data["speech_id"] == "sp-1"


# --- mesure 3 : l'ordonnanceur de parole -------------------------------------


def brain_speech_envelope(speech_id: str = "sp-1") -> ProtocolEnvelope:
    request = SpeechRequest(
        conversation_id=CONVERSATION,
        text=BRAIN_TEXT,
        kind=SpeechKind.RESULT,
        correlation_id="corr-1",
        work_id="work-1",
    )
    payload = {**request.to_payload(), "speech_id": speech_id, "conversation_id": CONVERSATION}
    return ProtocolEnvelope(
        message_type="brain.speech.requested",
        payload=payload,
        conversation_id=CONVERSATION,
        correlation_id="corr-1",
    )


async def test_first_brain_audio_is_timed_and_joins_on_speech_id():
    """Mesure 3 : `brain_speech_requested -> first_brain_audio`."""

    journal = RecordingJournal()
    scheduler = SpeechScheduler(
        core=RecordingCore(),
        conversation_id=CONVERSATION,
        session=SilentSession(),
        journal=journal,
    )
    envelope = brain_speech_envelope()
    speech_id = str(envelope.payload["speech_id"])

    await scheduler.handle_core_event(envelope)
    await scheduler.note_output_event(audio_delta(output_id="out-1", speech_id=speech_id))

    emitted = journal.of(LATENCY_FIRST_BRAIN_AUDIO_KIND)
    assert len(emitted) == 1
    data = emitted[0]["data"]
    assert data["measure"] == FIRST_BRAIN_AUDIO
    assert data["speech_id"] == speech_id
    assert data["output_id"] == "out-1"
    assert isinstance(data["elapsed_ms"], float)
    assert_free_of_content(emitted, BRAIN_TEXT)


async def test_surface_reflex_audio_does_not_close_a_brain_measure():
    """Un son sans `speech_id` est un réflexe : il ne mesure aucune demande."""

    journal = RecordingJournal()
    scheduler = SpeechScheduler(
        core=RecordingCore(),
        conversation_id=CONVERSATION,
        session=SilentSession(),
        journal=journal,
    )

    await scheduler.handle_core_event(brain_speech_envelope())
    await scheduler.note_output_event(audio_delta(output_id="out-9"))

    assert journal.of(LATENCY_FIRST_BRAIN_AUDIO_KIND) == []


async def test_the_bridge_relays_only_the_first_audio_block_of_an_output():
    """Le relais est ce qui rend la mesure 3 possible ; il doit rester unique.

    Le bridge est le seul lecteur du flux fournisseur : sans ce relais, aucune
    borne d'arrivée n'atteindrait l'ordonnanceur. À cinquante blocs par seconde,
    le relayer à chaque bloc coûterait une notification par bloc pour un chiffre
    qui ne se mesure qu'une fois.
    """

    relayed: list[ProtocolEnvelope] = []
    bridge = RealtimeConversationBridge(
        core=RecordingCore(),
        session=SilentSession(),
        conversation_id=CONVERSATION,
        audio=DevicelessAudio(),
        on_addressed=lambda: None,
        on_mute=lambda: None,
        auto_turn=True,
        continuous=True,
        journal=RecordingJournal(),
        on_output_event=relayed.append,
    )

    await feed(
        bridge,
        [
            audio_delta(output_id="out-1", speech_id="sp-1"),
            audio_delta(output_id="out-1", speech_id="sp-1"),
            audio_delta(output_id="out-1", speech_id="sp-1"),
        ],
    )

    assert [event.message_type for event in relayed] == ["realtime.audio"]


# --- mesures 5 et 6 : le cerveau possédé par Core ----------------------------


async def build_orchestrator(tmp_path, backend, diagnostics):  # noqa: ANN001
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    conversations = ConversationService(state, JsonlHistoryStore(tmp_path / "history"))
    brain = BrainOrchestrator(
        conversations=conversations,
        events=CoreEventBus(),
        backend=backend,
        diagnostics=diagnostics,
    )
    conversation = await conversations.create()
    return brain, state, conversation.id


async def wait_idle(brain: BrainOrchestrator) -> None:
    async def loop() -> None:
        while brain.active_turn_count:
            await asyncio.sleep(0)

    await asyncio.wait_for(loop(), timeout=5)


async def test_brain_work_latencies_are_timed_and_join_on_work_id(tmp_path):
    """Mesures 5 et 6 : `brain_work_started -> first_public_progress / completed`."""

    journal = RecordingJournal()
    brain, state, conversation_id = await build_orchestrator(tmp_path, WorkingBackend(), journal)

    await brain.submit(BrainTurnInput(conversation_id=conversation_id, text=USER_TEXT))
    await wait_idle(brain)
    await state.close()

    for kind, measure in (
        (BRAIN_FIRST_PROGRESS_LATENCY_KIND, FIRST_PUBLIC_PROGRESS),
        (BRAIN_WORK_COMPLETED_LATENCY_KIND, WORK_COMPLETED),
    ):
        emitted = journal.of(kind)
        assert len(emitted) == 1, kind
        data = emitted[0]["data"]
        assert data["measure"] == measure
        assert data["work_id"] == "work-1"
        assert data["conversation_id"] == conversation_id
        assert isinstance(data["elapsed_ms"], float)

    # Le libellé public du travail est du texte rédigé : il n'a rien à faire
    # dans une latence.
    assert_free_of_content(
        journal.of(BRAIN_FIRST_PROGRESS_LATENCY_KIND) + journal.of(BRAIN_WORK_COMPLETED_LATENCY_KIND),
        WORK_LABEL,
        USER_TEXT,
    )


async def test_failed_work_produces_no_completion_latency(tmp_path):
    """Une panne n'est pas une durée d'exécution : elle ne mesure rien."""

    journal = RecordingJournal()
    brain, state, conversation_id = await build_orchestrator(tmp_path, WorkingBackend(fail=True), journal)

    await brain.submit(BrainTurnInput(conversation_id=conversation_id, text=USER_TEXT))
    await wait_idle(brain)
    await state.close()

    assert journal.of(BRAIN_WORK_COMPLETED_LATENCY_KIND) == []
    # La progression, elle, a bien eu lieu avant l'échec.
    assert len(journal.of(BRAIN_FIRST_PROGRESS_LATENCY_KIND)) == 1


async def test_every_documented_measure_is_reachable_in_one_pass(tmp_path):
    """Les six mesures, observées ensemble, dans un seul scénario continu.

    C'est le garde-fou d'ensemble : chaque test ci-dessus prouve une mesure,
    celui-ci prouve qu'il n'en manque aucune. Une mesure supprimée par mégarde
    fait tomber ce test même si son test dédié a été supprimé avec elle.
    """

    journal = RecordingJournal()

    # Surface : mesures 1, 2 et 4.
    bridge = build_bridge(core=RecordingCore(), journal=journal)
    await feed(
        bridge,
        [
            # Une sortie qui joue, coupée par la parole de l'utilisateur.
            ProtocolEnvelope(message_type="realtime.output_started", payload={"output_id": "out-1", "speech_id": "sp-1"}),
            audio_delta(output_id="out-1", speech_id="sp-1"),
            speech_started(),
            # Puis le tour que cette interruption a ouvert, jusqu'au transcript.
            speech_started(),
            audio_delta(output_id="out-2"),
            transcript(USER_TEXT),
        ],
    )

    # Ordonnanceur de parole : mesure 3.
    scheduler = SpeechScheduler(
        core=RecordingCore(),
        conversation_id=CONVERSATION,
        session=SilentSession(),
        journal=journal,
    )
    envelope = brain_speech_envelope(speech_id="sp-2")
    await scheduler.handle_core_event(envelope)
    await scheduler.note_output_event(audio_delta(output_id="out-2", speech_id=str(envelope.payload["speech_id"])))

    # Core : mesures 5 et 6.
    brain, state, conversation_id = await build_orchestrator(tmp_path, WorkingBackend(), journal)
    await brain.submit(BrainTurnInput(conversation_id=conversation_id, text=USER_TEXT))
    await wait_idle(brain)
    await state.close()

    assert journal.measures() == set(LATENCY_MEASURES)
    # Et pas une ligne de contenu dans l'ensemble de la télémétrie de latence.
    assert_free_of_content(
        [event for event in journal.events if str(event["kind"]).startswith(("voice.latency.", "core.brain.latency."))],
        USER_TEXT,
        BRAIN_TEXT,
        WORK_LABEL,
    )


# --- portes de déploiement (Décision 34, Décision 20) ------------------------


def test_the_decision_34_gate_is_what_holds_the_default_on_legacy(monkeypatch):
    """Ce que ce test prouve : le contenu exact de la porte, et qu'elle est lue vive.

    Décision 34 : le mode continu ne peut pas devenir le défaut tant que l'accès
    du cerveau au calendrier et aux rappels n'est pas confirmé.

    La version précédente comparait `continuous_brain_default_blockers()` à
    `CONTINUOUS_BRAIN_DEFAULT_BLOCKERS` alors que la fonction n'est qu'un `return`
    de cette constante : une tautologie, verte même si la porte avait été vidée.
    On épingle donc le contenu attendu, puis on vérifie que l'accesseur relit
    l'attribut de module à chaque appel. C'est cette indirection — et elle seule —
    qui fait de « vider la liste » l'acte qui bascule le défaut, ce que le test
    suivant enchaîne.
    """

    assert continuous_brain_default_blockers() == (
        "brain_calendar_access_unverified",
        "brain_reminder_access_unverified",
    )
    assert default_voice_arch() is VoiceArchitecture.LEGACY

    monkeypatch.setattr("jarvis.v2_config.CONTINUOUS_BRAIN_DEFAULT_BLOCKERS", ("porte_de_test",))
    assert continuous_brain_default_blockers() == ("porte_de_test",)


def test_clearing_the_gate_is_the_only_thing_that_flips_the_default(monkeypatch):
    monkeypatch.setattr("jarvis.v2_config.CONTINUOUS_BRAIN_DEFAULT_BLOCKERS", ())
    assert default_voice_arch() is VoiceArchitecture.CONTINUOUS_BRAIN
    assert parse_voice_arch(None) is VoiceArchitecture.CONTINUOUS_BRAIN


def test_continuous_mode_stays_opt_in_and_the_rollback_path_works(monkeypatch, tmp_path):
    """Décision 20 : une ligne de `.env` et un redémarrage suffisent à revenir."""

    monkeypatch.setenv("JARVIS_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(tmp_path))

    monkeypatch.delenv("JARVIS_VOICE_ARCH", raising=False)
    assert V2Settings.load().voice_arch is VoiceArchitecture.LEGACY

    monkeypatch.setenv("JARVIS_VOICE_ARCH", "continuous_brain")
    assert V2Settings.load().voice_arch is VoiceArchitecture.CONTINUOUS_BRAIN

    # Retour arrière explicite...
    monkeypatch.setenv("JARVIS_VOICE_ARCH", "legacy")
    assert V2Settings.load().voice_arch is VoiceArchitecture.LEGACY

    # ... et retour arrière par suppression de la variable, qui doit ramener au
    # défaut gardé par la porte plutôt qu'à la dernière valeur utilisée.
    monkeypatch.delenv("JARVIS_VOICE_ARCH")
    assert V2Settings.load().voice_arch is VoiceArchitecture.LEGACY


def test_an_unknown_architecture_is_refused_rather_than_guessed():
    with pytest.raises(ConfigurationError, match="JARVIS_VOICE_ARCH"):
        parse_voice_arch("continuous")
