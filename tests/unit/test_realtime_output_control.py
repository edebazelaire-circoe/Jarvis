from __future__ import annotations

import base64

import aiohttp
import pytest

from jarvis.adapters.gemini_live import GeminiLiveSession
from jarvis.adapters.openai_realtime import (
    OUTPUT_ID_METADATA_KEY,
    SPEECH_ID_METADATA_KEY,
    OpenAIRealtimeSession,
)
from jarvis.domain.v2 import PlaybackCursor, SpeechKind, SpeechRequest
from jarvis.ports.v2 import RealtimeSession, supports_output_control


class FakeWebSocket:
    """Websocket deterministe : il enregistre les sorties et rejoue une trame."""

    def __init__(self, inbound: list[dict[str, object]] | None = None) -> None:
        self.sent: list[dict[str, object]] = []
        self.inbound = inbound or []
        self.closed = False

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        async def stream():
            for frame in self.inbound:
                yield _Message(frame)

        return stream()


class _Message:
    type = aiohttp.WSMsgType.TEXT

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


ONE_SECOND_B64 = base64.b64encode(bytes(48000)).decode()


def make_session(inbound: list[dict[str, object]] | None = None) -> OpenAIRealtimeSession:
    websocket = FakeWebSocket(inbound)
    return OpenAIRealtimeSession(websocket, object(), owns_http=False)  # type: ignore[arg-type]


def speech(text: str = "Le rapport est prêt.") -> SpeechRequest:
    return SpeechRequest(conversation_id="conversation-1", text=text, kind=SpeechKind.RESULT)


async def drain(session: OpenAIRealtimeSession) -> list[tuple[str, dict[str, object]]]:
    return [(event.message_type, event.payload) async for event in session.events()]


def test_openai_session_satisfies_both_realtime_ports():
    """Decision 22 : la capacite de controle s'ajoute sans elargir RealtimeSession."""

    session = make_session()
    assert supports_output_control(session) is True
    missing = [name for name in dir(RealtimeSession) if not name.startswith("_") and not hasattr(session, name)]
    assert missing == []


def test_gemini_live_stays_on_the_legacy_path():
    """Decision 21 : Gemini n'annonce pas la capacite de controle de sortie."""

    assert supports_output_control(GeminiLiveSession) is False
    assert not hasattr(GeminiLiveSession, "speak")


async def test_speak_emits_a_single_response_create_without_a_fake_user_turn():
    session = make_session()
    request = speech("Trois fichiers ont changé.")

    output_id = await session.speak(request)

    assert session.ws.sent == [
        {
            "type": "response.create",
            "response": {
                "instructions": session.ws.sent[0]["response"]["instructions"],  # type: ignore[index]
                "input": [],
                "output_modalities": ["audio"],
                "metadata": {
                    OUTPUT_ID_METADATA_KEY: output_id,
                    SPEECH_ID_METADATA_KEY: request.id,
                },
            },
        }
    ]
    instructions = session.ws.sent[0]["response"]["instructions"]  # type: ignore[index]
    assert "Trois fichiers ont changé." in instructions
    assert "mot pour mot" in instructions
    # Aucun element de conversation n'est fabrique : pas de faux tour user.
    assert all(frame["type"] != "conversation.item.create" for frame in session.ws.sent)
    assert session.output_for_speech(request.id) is not None


async def test_a_commanded_response_never_takes_the_conversation_as_its_prompt():
    """La conversation du fournisseur n'entre pas dans une réponse commandée.

    Avec elle en contexte, un préambule coupé au barge-in — élément audio dont
    la troncature a retiré le transcript — passe pour un tour inachevé : le
    modèle le reprend, puis répond de lui-même au lieu de lire le texte du
    cerveau. Contre le vrai fournisseur, 0 lecture fidèle sur 5 dans cette
    séquence, 5 sur 5 avec un contexte d'entrée vide.
    """

    session = make_session()

    await session.speak(speech("Trois fichiers ont changé."))
    await session.speak_reflex(transcript="Pousse les commits")

    assert [frame["type"] for frame in session.ws.sent] == ["response.create", "response.create"]
    assert [frame["response"]["input"] for frame in session.ws.sent] == [[], []]  # type: ignore[index]


async def test_send_context_still_uses_the_legacy_user_item_path():
    """Le chemin legacy reste intact : c'est bien speak() qui s'en distingue."""

    session = make_session()
    await session.send_context("contexte legacy")

    assert [frame["type"] for frame in session.ws.sent] == [
        "conversation.item.create",
        "response.create",
    ]
    assert session.ws.sent[0]["item"]["role"] == "user"  # type: ignore[index]


async def test_events_bind_provider_ids_to_the_spoken_output():
    session = make_session()
    request = speech()
    output_id = await session.speak(request)
    session.ws.inbound = [
        {
            "type": "response.created",
            "response": {
                "id": "resp-1",
                "metadata": {OUTPUT_ID_METADATA_KEY: output_id, SPEECH_ID_METADATA_KEY: request.id},
            },
        },
        {
            "type": "response.output_item.added",
            "response_id": "resp-1",
            "item": {"id": "item-audio", "type": "message"},
        },
        {"type": "response.output_audio.delta", "response_id": "resp-1", "item_id": "item-audio", "delta": "AAA"},
        {"type": "response.output_audio.done", "response_id": "resp-1", "item_id": "item-audio"},
        {
            "type": "response.output_audio_transcript.done",
            "response_id": "resp-1",
            "item_id": "item-audio",
            "transcript": "Le rapport est prêt.",
        },
        {"type": "response.done", "response": {"id": "resp-1", "status": "completed"}},
    ]

    events = await drain(session)

    assert [name for name, _ in events] == [
        "realtime.output_started",
        "realtime.audio",
        "realtime.audio_done",
        "realtime.assistant_transcript",
        "realtime.response_done",
    ]
    for _, payload in events:
        assert payload["output_id"] == output_id
        assert payload["speech_id"] == request.id
        assert payload["response_id"] == "resp-1"
    assert events[1][1]["pcm_b64"] == "AAA"
    assert events[1][1]["item_id"] == "item-audio"
    assert events[-1][1]["status"] == "completed"
    # La sortie n'est plus active une fois la reponse terminee.
    assert session.active_output_id is None


async def test_surface_initiated_response_still_gets_a_trackable_output():
    """Un tour cree par le VAD serveur reste pilotable, sans speech_id."""

    session = make_session(
        [
            {"type": "response.created", "response": {"id": "resp-vad"}},
            {"type": "response.output_audio.delta", "response_id": "resp-vad", "item_id": "item-vad", "delta": "B"},
        ]
    )

    events = await drain(session)

    assert [name for name, _ in events] == ["realtime.output_started", "realtime.audio"]
    assert events[0][1]["speech_id"] is None
    assert events[0][1]["output_id"] == events[1][1]["output_id"]
    assert session.active_output_id == events[0][1]["output_id"]


async def test_input_transcription_delta_and_completed_carry_the_provider_item_id():
    session = make_session(
        [
            {
                "type": "conversation.item.input_audio_transcription.delta",
                "item_id": "item-user",
                "content_index": 0,
                "delta": "ouvre le ",
            },
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "item_id": "item-user",
                "content_index": 0,
                "transcript": "ouvre le rapport",
            },
        ]
    )

    events = await drain(session)

    assert events == [
        ("realtime.transcript_delta", {"text": "ouvre le ", "item_id": "item-user", "content_index": 0}),
        ("realtime.transcript", {"text": "ouvre le rapport", "item_id": "item-user", "content_index": 0}),
    ]


async def test_tool_call_events_expose_provider_ids_and_stay_deduplicated():
    session = make_session(
        [
            {
                "type": "response.function_call_arguments.done",
                "response_id": "resp-2",
                "item_id": "item-call",
                "call_id": "call-1",
                "name": "claude_task",
                "arguments": '{"prompt": "liste"}',
            },
            {
                "type": "response.output_item.done",
                "response_id": "resp-2",
                "item": {"id": "item-call", "type": "function_call", "call_id": "call-1", "name": "claude_task"},
            },
        ]
    )

    events = await drain(session)

    assert [name for name, _ in events] == ["realtime.tool_call"]
    assert events[0][1]["call_id"] == "call-1"
    assert events[0][1]["response_id"] == "resp-2"
    assert events[0][1]["item_id"] == "item-call"


async def test_cancel_output_targets_the_bound_response():
    session = make_session([{"type": "response.created", "response": {"id": "resp-3"}}])
    await drain(session)
    session.ws.sent.clear()

    await session.cancel_output()

    assert session.ws.sent == [{"type": "response.cancel", "response_id": "resp-3"}]


async def test_cancel_output_resolves_the_response_from_the_cursor_speech_id():
    session = make_session()
    request = speech()
    output_id = await session.speak(request)
    session.ws.inbound = [
        {
            "type": "response.created",
            "response": {"id": "resp-4", "metadata": {OUTPUT_ID_METADATA_KEY: output_id}},
        }
    ]
    await drain(session)
    session.ws.sent.clear()

    await session.cancel_output(PlaybackCursor(speech_id=request.id, played_ms=420))

    assert session.ws.sent == [{"type": "response.cancel", "response_id": "resp-4"}]


async def test_cancel_output_is_a_no_op_when_nothing_is_playing():
    session = make_session()

    await session.cancel_output()
    await session.cancel_output(PlaybackCursor(speech_id="inconnu"))

    assert session.ws.sent == []


async def test_truncate_uses_the_played_position_of_the_bound_item():
    session = make_session()
    request = speech()
    output_id = await session.speak(request)
    session.ws.inbound = [
        {
            "type": "response.created",
            "response": {"id": "resp-5", "metadata": {OUTPUT_ID_METADATA_KEY: output_id}},
        },
        {
            "type": "response.output_item.added",
            "response_id": "resp-5",
            "item": {"id": "item-spoken", "type": "message"},
        },
    ]
    await drain(session)
    session.ws.sent.clear()

    await session.truncate(PlaybackCursor(speech_id=request.id, played_ms=1500))

    assert session.ws.sent == [
        {
            "type": "conversation.item.truncate",
            "item_id": "item-spoken",
            "content_index": 0,
            "audio_end_ms": 1500,
        }
    ]


async def test_truncate_accepts_provider_ids_carried_by_the_cursor():
    """Decision 24 : le runtime peut n'avoir observe que les evenements normalises."""

    session = make_session()

    await session.truncate(
        PlaybackCursor(speech_id="speech-inconnu", played_ms=900, provider_item_id="item-externe")
    )

    assert session.ws.sent == [
        {
            "type": "conversation.item.truncate",
            "item_id": "item-externe",
            "content_index": 0,
            "audio_end_ms": 900,
        }
    ]


async def test_cancel_output_resolves_a_known_item_id_carried_by_the_cursor():
    session = make_session(
        [
            {"type": "response.created", "response": {"id": "resp-7"}},
            {"type": "response.output_audio.delta", "response_id": "resp-7", "item_id": "item-7", "delta": "D"},
        ]
    )
    await drain(session)
    session.ws.sent.clear()

    await session.cancel_output(PlaybackCursor(speech_id="autre", provider_item_id="item-7"))

    assert session.ws.sent == [{"type": "response.cancel", "response_id": "resp-7"}]


async def test_truncate_refuses_to_guess_when_no_item_is_known():
    session = make_session()

    with pytest.raises(ValueError, match="no provider item to truncate"):
        await session.truncate(PlaybackCursor(speech_id="speech-inconnu", played_ms=120))

    assert session.ws.sent == []


async def test_output_tracking_is_bounded():
    """Une session longue ne doit pas accumuler indefiniment les sorties."""

    session = make_session()
    for index in range(session.MAX_TRACKED_OUTPUTS + 5):
        await session.speak(speech(f"message {index}"))

    assert len(session._outputs) == session.MAX_TRACKED_OUTPUTS
    assert len(session._output_by_speech) == session.MAX_TRACKED_OUTPUTS


async def test_barge_in_sequence_emits_cancel_then_truncate():
    """Spec section 12, etapes 3 et 4 : annuler puis aligner l'historique."""

    session = make_session()
    request = speech()
    output_id = await session.speak(request)
    session.ws.inbound = [
        {
            "type": "response.created",
            "response": {"id": "resp-6", "metadata": {OUTPUT_ID_METADATA_KEY: output_id}},
        },
        # Une seconde d'audio reçue : la troncature à 640 ms reste dans l'élément.
        {"type": "response.output_audio.delta", "response_id": "resp-6", "item_id": "item-6", "delta": ONE_SECOND_B64},
    ]
    await drain(session)
    session.ws.sent.clear()
    cursor = PlaybackCursor(speech_id=request.id, played_ms=640)

    await session.cancel_output(cursor)
    await session.truncate(cursor)

    assert session.ws.sent == [
        {"type": "response.cancel", "response_id": "resp-6"},
        {
            "type": "conversation.item.truncate",
            "item_id": "item-6",
            "content_index": 0,
            "audio_end_ms": 640,
        },
    ]
