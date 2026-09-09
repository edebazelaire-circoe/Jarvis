"""L'adaptateur Gemini Live doit être indiscernable de celui d'OpenAI.

Le pont de conversation ne connaît que les enveloppes `realtime.*`. Tout
l'intérêt de la seconde pile vocale tient donc à une chose : traduire le
protocole BidiGenerateContent vers exactement les mêmes événements, dans le
même ordre, avec les mêmes garanties — notamment une transcription **complète**
par tour, alors que Google l'envoie en fragments.
"""

from __future__ import annotations

import base64
import json

import pytest

from jarvis.adapters.gemini_live import INPUT_MIME, GeminiLiveSession, _tools_payload
from jarvis.runtime.realtime_tools import REALTIME_TOOLS


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.closed = False
        self.pings = 0

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def ping(self) -> None:
        self.pings += 1

    async def close(self) -> None:
        self.closed = True


def session(*, auto_turn: bool = True) -> tuple[GeminiLiveSession, FakeWebSocket]:
    ws = FakeWebSocket()
    return GeminiLiveSession(ws, None, owns_http=False, auto_turn=auto_turn), ws


def kinds(envelopes) -> list[str]:  # noqa: ANN001
    return [envelope.message_type for envelope in envelopes]


def test_the_tools_are_translated_into_googles_shape():
    payload = _tools_payload(list(REALTIME_TOOLS))

    assert len(payload) == 1
    names = {declaration["name"] for declaration in payload[0]["functionDeclarations"]}
    assert "claude_task" in names, "l'outil qui fait agir Claude doit survivre à la traduction"
    for declaration in payload[0]["functionDeclarations"]:
        assert "description" in declaration


def test_a_tool_without_parameters_does_not_declare_an_empty_schema():
    """Google refuse un schéma de paramètres vide, là où OpenAI l'accepte."""
    payload = _tools_payload([{"name": "ping", "description": "test", "parameters": {"type": "object", "properties": {}}}])
    assert "parameters" not in payload[0]["functionDeclarations"][0]


async def test_audio_is_sent_at_the_rate_google_imposes():
    live, ws = session()
    await live.send_audio(b"\x01\x00" * 100)

    audio = ws.sent[0]["realtimeInput"]["audio"]
    assert audio["mimeType"] == INPUT_MIME == "audio/pcm;rate=16000"
    assert base64.b64decode(audio["data"]) == b"\x01\x00" * 100


async def test_a_turn_shorter_than_a_tenth_of_a_second_is_never_submitted():
    """Même garde que côté OpenAI : un fournisseur qui reçoit un tampon quasi
    vide répond à côté, ou pas du tout."""
    live, ws = session(auto_turn=False)
    await live.send_audio(b"\x00" * 100)

    assert await live.finish_input() is False
    assert not any("activityEnd" in json.dumps(message) for message in ws.sent)


async def test_manual_turn_mode_frames_the_speech_with_activity_markers():
    live, ws = session(auto_turn=False)
    await live.send_audio(b"\x00" * 8000)

    assert ws.sent[0] == {"realtimeInput": {"activityStart": {}}}
    assert await live.finish_input() is True
    assert ws.sent[-1] == {"realtimeInput": {"activityEnd": {}}}


async def test_automatic_turn_mode_sends_no_activity_marker():
    """Avec la détection automatique active, Google refuse ces marqueurs."""
    live, ws = session(auto_turn=True)
    await live.send_audio(b"\x00" * 8000)

    assert "activityStart" not in json.dumps(ws.sent)


def test_the_user_transcript_is_published_once_and_whole():
    """Le pont range la transcription dans l'historique et s'en sert pour
    décider si JARVIS est concerné : la livrer en fragments créerait une
    dizaine de faux tours par phrase."""
    live, _ = session()

    assert kinds(live._translate({"serverContent": {"inputTranscription": {"text": "Range "}}})) == [
        "realtime.speech_started"
    ]
    assert kinds(live._translate({"serverContent": {"inputTranscription": {"text": "le bureau"}}})) == []

    events = live._translate({"serverContent": {"modelTurn": {"parts": [{"inlineData": {"data": "AAA="}}]}}})

    assert kinds(events) == ["realtime.input_committed", "realtime.transcript", "realtime.audio"]
    assert events[1].payload["text"] == "Range le bureau"
    assert events[2].payload["pcm_b64"] == "AAA="


def test_the_turn_is_only_committed_once_however_many_audio_chunks_arrive():
    live, _ = session()
    first = live._translate({"serverContent": {"modelTurn": {"parts": [{"inlineData": {"data": "AAA="}}]}}})
    second = live._translate({"serverContent": {"modelTurn": {"parts": [{"inlineData": {"data": "BBB="}}]}}})

    assert kinds(first) == ["realtime.input_committed", "realtime.audio"]
    assert kinds(second) == ["realtime.audio"]


def test_the_end_of_turn_publishes_the_assistant_transcript_then_closes():
    live, _ = session()
    live._translate({"serverContent": {"modelTurn": {"parts": [{"inlineData": {"data": "AAA="}}]}}})
    live._translate({"serverContent": {"outputTranscription": {"text": "C'est "}}})
    live._translate({"serverContent": {"outputTranscription": {"text": "fait."}}})

    events = live._translate({"serverContent": {"turnComplete": True}})

    assert kinds(events) == [
        "realtime.assistant_transcript",
        "realtime.audio_done",
        "realtime.response_done",
    ]
    assert events[0].payload["text"] == "C'est fait."


def test_a_second_turn_starts_from_a_clean_slate():
    live, _ = session()
    live._translate({"serverContent": {"inputTranscription": {"text": "premier"}}})
    live._translate({"serverContent": {"modelTurn": {"parts": [{"inlineData": {"data": "AAA="}}]}}})
    live._translate({"serverContent": {"turnComplete": True}})

    events = live._translate({"serverContent": {"inputTranscription": {"text": "second"}}})

    assert kinds(events) == ["realtime.speech_started"]
    flush = live._translate({"serverContent": {"generationComplete": True}})
    assert flush[1].payload["text"] == "second"


def test_a_text_only_answer_still_ends_the_turn():
    """Sans commit, le pont attendrait indéfiniment un tour déjà terminé."""
    live, _ = session()
    events = live._translate({"serverContent": {"turnComplete": True}})
    assert kinds(events)[0] == "realtime.input_committed"
    assert "realtime.response_done" in kinds(events)


def test_a_tool_call_carries_the_identifier_the_answer_will_need():
    live, _ = session()
    events = live._translate(
        {"toolCall": {"functionCalls": [{"id": "call-1", "name": "claude_task", "args": {"request": "range"}}]}}
    )

    assert kinds(events) == ["realtime.tool_call"]
    assert events[0].payload == {"call_id": "call-1", "name": "claude_task", "arguments": {"request": "range"}}


async def test_a_tool_result_is_returned_under_that_same_identifier():
    live, ws = session()
    await live.send_tool_result("call-1", {"ok": True, "text": "fini"})

    response = ws.sent[0]["toolResponse"]["functionResponses"][0]
    assert response["id"] == "call-1"
    assert response["response"]["result"]["text"] == "fini"


def test_an_announced_disconnection_surfaces_as_an_error():
    live, _ = session()
    events = live._translate({"goAway": {"timeLeft": "10s"}})

    assert kinds(events) == ["realtime.error"]
    assert events[0].payload["error"]["code"] == "gemini_go_away"


def test_a_provider_error_keeps_its_status_as_a_code():
    live, _ = session()
    events = live._translate({"error": {"status": "INVALID_ARGUMENT", "message": "modèle inconnu"}})

    assert events[0].payload["error"] == {"code": "INVALID_ARGUMENT", "message": "modèle inconnu"}


def test_setup_completion_is_swallowed_rather_than_forwarded():
    live, _ = session()
    assert live._translate({"setupComplete": {}}) == []


async def test_a_long_tool_call_can_keep_the_socket_alive():
    live, ws = session()
    await live.keepalive()
    assert ws.pings == 1


@pytest.mark.parametrize("payload", [{"realtimeInput": None}, {}, {"unknown": 1}])
def test_unknown_messages_are_ignored_instead_of_crashing_the_turn(payload):
    live, _ = session()
    assert live._translate(payload) == []
