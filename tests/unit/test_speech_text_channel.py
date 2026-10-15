"""Disposition `text_channel` (`docs/chat.md` › *Text disposition*, Slice 03).

Un tour écrit au Chat ne produit **aucun** `brain.speech.requested` : son issue
est retenue (`brain.message.published`), puis retenue avant la porte des Boards.
Core réel sous `tmp_path`, backend scripté, assertions sur le store d'évènements.
"""

from __future__ import annotations

import asyncio

from jarvis.core.brain_service import (
    BRAIN_SPEECH_WITHHELD_TEXT_CHANNEL_KIND, SPEECH_WITHHELD_TEXT_CHANNEL,
)
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.v2 import (
    BrainEvent, BrainEventKind, BrainRunStatus, BrainTurnInput, BrainTurnResult, BrainTurnSource, SpeechKind,
    SpeechRequest,
)
from tests.fakes.conversation_events import wait_emitter_settled


class Journal:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.entries.append({"kind": kind, "level": level, "data": dict(data or {})})

    def of(self, kind):
        return [entry["data"] for entry in self.entries if entry["kind"] == kind]


class SpeakingBackend:
    """Le cerveau parle : accusé, question, puis résultat de travail, et un résumé de tour."""

    async def run_turn(self, turn, state, emit):
        def speech(text, kind, work_id=None):
            return BrainEvent(kind=BrainEventKind.SPEECH, conversation_id=turn.conversation_id,
                              correlation_id=turn.correlation_id,
                              speech=SpeechRequest(conversation_id=turn.conversation_id,
                                                   correlation_id=turn.correlation_id, text=text, kind=kind,
                                                   work_id=work_id))
        await emit.emit(speech("Je regarde.", SpeechKind.ACK))
        await emit.emit(speech("Lequel des deux ?", SpeechKind.QUESTION))
        await emit.emit(BrainEvent(kind=BrainEventKind.ACCEPTED, conversation_id=turn.conversation_id,
                                   correlation_id=turn.correlation_id, work_id="work-1"))
        await emit.emit(speech("Le dossier est lu.", SpeechKind.RESULT, "work-1"))
        return BrainTurnResult(correlation_id=turn.correlation_id, status=BrainRunStatus.COMPLETED,
                               public_summary="Résumé du tour.")


async def start(data_root, journal: Journal | None = None) -> JarvisCoreApplication:
    core = JarvisCoreApplication(data_root=data_root, brain_backend=SpeakingBackend(), diagnostics=journal)
    await core.start()
    return core


async def settle(core: JarvisCoreApplication) -> None:
    await asyncio.wait_for(asyncio.gather(*tuple(core.brain._tasks.values()), return_exceptions=True), 5)
    await wait_emitter_settled(core.conversation_event_emitter)


async def of_correlation(core: JarvisCoreApplication, conversation_id: str, correlation_id: str):
    page = await core.conversation_events.list_conversation_events(conversation_id, limit=500)
    return [item.event for item in page.events if item.event.correlation_id == correlation_id]


def speech_requested(events):
    return [event for event in events if event.event_type is T.BRAIN_SPEECH_REQUESTED]


def published(events):
    return {event.content for event in events if event.event_type is T.BRAIN_MESSAGE_PUBLISHED}


async def foreground(core: JarvisCoreApplication) -> str:
    return (await core.sessions.current()).binding.conversation_id


async def test_text_turn_result_published_not_spoken(tmp_path):
    journal = Journal()
    core = await start(tmp_path, journal)
    try:
        conversation_id = await foreground(core)
        await core.brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Lis le dossier",
                                               correlation_id="chat:t1", source=BrainTurnSource.TEXT))
        await settle(core)
        events = await of_correlation(core, conversation_id, "chat:t1")
        assert speech_requested(events) == []
        assert {"Le dossier est lu.", "Résumé du tour."} <= published(events)
        # Accusé et question : ni dits, ni retenus comme issue (la réponse, elle, est publiée).
        assert not published(events) & {"Je regarde.", "Lequel des deux ?"}
        withheld = journal.of(BRAIN_SPEECH_WITHHELD_TEXT_CHANNEL_KIND)
        assert {line["kind"] for line in withheld} >= {"ack", "question", "result"}
        # Identifiants seulement (le puits de Core y joint le `board_id`), jamais le texte.
        assert all(set(line) - {"board_id"} == {"conversation_id", "correlation_id", "speech_id", "kind"}
                   for line in withheld)
        assert "Lequel des deux ?" not in core.brain.working_state(conversation_id).unresolved_questions
    finally:
        await core.stop()


async def test_late_work_result_after_core_restart_not_spoken(tmp_path):
    core = await start(tmp_path)
    try:
        conversation_id = await foreground(core)
        await core.brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Lance un sous-agent",
                                               correlation_id="chat:late", source=BrainTurnSource.TEXT))
        await settle(core)
    finally:
        await core.stop()
    journal = Journal()
    core = await start(tmp_path, journal)  # cache mémoire vide : seul le tour durable sait que c'était écrit
    try:
        assert core.brain._text_channel == {}
        spoken = await core.brain.announce_notice("Le sous-agent a terminé.", kind="result",
                                                  conversation_id=conversation_id, work_id="agent-7")
        await wait_emitter_settled(core.conversation_event_emitter)
        assert spoken is False
        events = await of_correlation(core, conversation_id, "chat:late")
        assert speech_requested(events) == []
        assert "Le sous-agent a terminé." in published(events)
        assert [line["correlation_id"] for line in journal.of(BRAIN_SPEECH_WITHHELD_TEXT_CHANNEL_KIND)] == ["chat:late"]
        assert journal.of("core.brain.notice_dropped") == []  # une seule ligne, pas d'alerte en double
    finally:
        await core.stop()


async def test_voice_turn_still_spoken(tmp_path):
    journal = Journal()
    core = await start(tmp_path, journal)
    try:
        conversation_id = await foreground(core)
        await core.brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Lis le dossier",
                                               correlation_id="realtime:v1"))
        await settle(core)
        events = await of_correlation(core, conversation_id, "realtime:v1")
        assert {event.content for event in speech_requested(events)} >= {"Je regarde.", "Lequel des deux ?",
                                                                         "Le dossier est lu."}
        assert journal.of(BRAIN_SPEECH_WITHHELD_TEXT_CHANNEL_KIND) == []
        assert await core.brain._text_only(conversation_id, "realtime:v1") is False
    finally:
        await core.stop()


async def test_notice_policy_unchanged(tmp_path):
    core = await start(tmp_path)
    try:
        conversation_id = await foreground(core)
        # Tour ouvert par Core (réveil) : ses relais gardent leur politique, retenus et dits.
        await core.brain.submit(BrainTurnInput(conversation_id=conversation_id, text="réveil",
                                               correlation_id="system:w1", source=BrainTurnSource.SYSTEM))
        await settle(core)
        assert await core.brain.announce_notice("Un travail a échoué.", conversation_id=conversation_id) is True
        await wait_emitter_settled(core.conversation_event_emitter)
        events = await of_correlation(core, conversation_id, "system:w1")
        assert "Un travail a échoué." in {event.content for event in speech_requested(events)}
        assert "Un travail a échoué." in published(events)
        # Un tour écrit puis un tour vocal : l'intention courante est vocale, le relais est dit.
        await core.brain.submit(BrainTurnInput(conversation_id=conversation_id, text="écrit",
                                               correlation_id="chat:n1", source=BrainTurnSource.TEXT))
        await core.brain.submit(BrainTurnInput(conversation_id=conversation_id, text="parlé",
                                               correlation_id="realtime:n2"))
        await settle(core)
        assert await core.brain.announce_notice("Fini.", conversation_id=conversation_id) is True
        assert SPEECH_WITHHELD_TEXT_CHANNEL == "text_channel"
    finally:
        await core.stop()
