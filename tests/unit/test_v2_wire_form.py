from __future__ import annotations

import json

from jarvis.domain.v2 import (
    BrainTurnAcceptance,
    BrainTurnInput,
    Conversation,
    ProtocolEnvelope,
    SpeechKind,
    SpeechPriority,
    SpeechRequest,
    declared_wire_form,
    jsonable,
)

# Clés exigées par docs/handoff-realtime-brain/docs/05-event-contracts.md pour
# `brain.speech.requested`.
DOC_SPEECH_KEYS = {
    "speech_id",
    "text",
    "kind",
    "priority",
    "work_id",
    "supersedes_key",
    "interruptible",
    "expires_at",
    "provenance",
}


def speech() -> SpeechRequest:
    return SpeechRequest(
        conversation_id="conv-1",
        text="J'ai trouvé le fil concerné.",
        kind=SpeechKind.RESULT,
        priority=SpeechPriority.NORMAL,
        work_id="work-1",
    )


def test_generic_serializer_uses_the_declared_wire_form():
    """Les deux chemins de sérialisation doivent converger.

    Régression : `jsonable()` projetait les champs bruts, donc `id` au lieu de
    `speech_id` et une priorité entière (`SpeechPriority` est un `IntEnum`).
    Tout code publiant un envelope avec `jsonable(request)` violait alors le
    contrat de `docs/05-event-contracts.md` sans le moindre signal.
    """

    request = speech()
    assert jsonable(request) == request.to_payload()


def test_speech_wire_form_matches_the_documented_contract():
    wire = jsonable(speech())
    assert DOC_SPEECH_KEYS <= set(wire)
    assert "id" not in wire
    assert wire["speech_id"]
    assert wire["priority"] == "normal"
    assert wire["kind"] == "result"
    assert wire["provenance"] == "brain.speech"
    assert json.loads(json.dumps(wire)) == wire


def test_all_domain_types_declaring_a_wire_form_delegate_to_it():
    turn = BrainTurnInput(conversation_id="conv-1", text="Regarde les mails de Paul.", provider_item_id="item_42")
    acceptance = BrainTurnAcceptance(turn_id="turn-1", conversation_id="conv-1", correlation_id="corr-1", revision=3)
    for value in (speech(), turn, acceptance):
        assert jsonable(value) == value.to_payload(), type(value).__name__


def test_declared_wire_form_applies_through_nesting():
    """La délégation doit survivre à l'imbrication.

    Un envelope transporte la demande de parole dans sa charge utile : si la
    projection générique aplatissait l'objet imbriqué avant de le voir, la forme
    déclarée serait perdue là même où elle sert.
    """

    request = speech()
    envelope = ProtocolEnvelope(
        message_type="brain.speech.requested",
        payload={"speech": request},
        conversation_id=request.conversation_id,
    )
    wire = json.loads(json.dumps(jsonable(envelope)))
    assert wire["payload"]["speech"] == request.to_payload()
    assert SpeechRequest.from_payload(wire["payload"]["speech"]) == request


def test_types_without_a_declared_wire_form_keep_the_generic_projection():
    conversation = Conversation(id="conv-1")
    wire = jsonable(conversation)
    assert wire["id"] == "conv-1"
    assert wire["status"] == "active"
    assert declared_wire_form(conversation) is None


def test_declared_wire_form_ignores_classes_and_plain_values():
    assert declared_wire_form(SpeechRequest) is None
    assert declared_wire_form("texte") is None
    assert declared_wire_form(None) is None
