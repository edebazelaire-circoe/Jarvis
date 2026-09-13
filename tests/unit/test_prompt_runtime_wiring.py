"""Task15B: resolved prompt material is the material written to real adapter boundaries."""
from __future__ import annotations

import asyncio
import json

import pytest

from jarvis.adapters.openai_front_brain import LunaFrontBrainAnalyzer
from jarvis.adapters.openai_realtime import OpenAIRealtimeSession
from jarvis.domain.front_brain_hints import FrontBrainHintRequest
from jarvis.domain.live_prompt import LIVE_OPERATING_RULES
from jarvis.domain.speech_presentation import SpeechSource
from jarvis.domain.v2 import SpeechKind, SpeechRequest
from jarvis.domain.voice_architecture import DuplexVoiceConfig, VoiceModelRef
from jarvis.domain.voice_frontend import VoiceContext, VoiceContextMessage, VoiceContextRole, VoiceCorrelation
from jarvis.domain.voice_state import VoiceUserRecord
from jarvis.runtime.live_frontend_session import LiveFrontendSession
from jarvis.runtime.prompt_catalog import default_prompt_registry


def override(identifier: str, text: str) -> dict:
    descriptor = default_prompt_registry().require(identifier)
    return {"schema_version": 1, "overrides": {
        identifier: {"base_revision": descriptor.default_revision, "text": text},
    }}


class Wire:
    def __init__(self):
        self.sent = []
        self.incoming = asyncio.Queue()

    async def send_json(self, value):
        self.sent.append(value)

    async def receive_json(self):
        return await self.incoming.get()

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_realtime_response_uses_resolved_persona_and_records_no_prompt_text():
    wire = Wire()
    secret = "PRIVATE OVERRIDDEN PERSONA"
    session = OpenAIRealtimeSession(wire, object(), owns_http=False,
                                    prompt_overrides=override("voice.persona", secret))
    await session.speak_reflex(transcript="PRIVATE transcript", avoid=("PRIVATE prior",))
    assert wire.sent[-1]["response"]["instructions"].startswith(secret + "\n")
    evidence = session.prompt_applications[-1]
    assert evidence["program_id"] == "realtime.reflex.response"
    assert evidence["application"] == "sent"
    assert secret not in json.dumps(evidence)
    assert "PRIVATE transcript" not in json.dumps(evidence)

    await session.speak(SpeechRequest(conversation_id="conversation", text="Exact result", kind=SpeechKind.RESULT))
    assert "Exact result" in wire.sent[-1]["response"]["instructions"]
    assert session.prompt_applications[-1]["program_id"] == "realtime.verbatim.response"


def hint_request() -> FrontBrainHintRequest:
    return FrontBrainHintRequest(
        "request", VoiceUserRecord(VoiceCorrelation("session", provider_input_id="input"),
                                    "transcript", 1, "PRIVATE observation", committed=False),
        None, SpeechSource("turn", "correlation", "turn", 1),
        VoiceContext(1, (VoiceContextMessage(VoiceContextRole.USER, "PRIVATE context"),)),
        "admission", "configuration", 10_000_000_000,
    )


def test_luna_payload_uses_analysis_addition_without_moving_observation_out_of_data():
    addition = "Return the most conservative valid classification."
    analyzer = LunaFrontBrainAnalyzer(
        api_key="test-only",
        prompt_overrides=override("front_brain.analysis.addition", addition),
    )
    payload = analyzer.payload(hint_request())
    assert payload["instructions"].endswith("\n" + addition)
    assert "PRIVATE observation" not in payload["instructions"]
    assert "PRIVATE observation" in payload["input"][0]["content"][0]["text"]


@pytest.mark.asyncio
async def test_live_start_sends_resolved_addition_and_keeps_only_fingerprints_as_evidence():
    wire = Wire()
    addition = "Use a restrained speaking style."
    task = asyncio.create_task(LiveFrontendSession.connect(
        api_key="test", voice="marin", context={},
        architecture_config=DuplexVoiceConfig(VoiceModelRef("openai", "gpt-live-1")),
        connector=lambda: asyncio.sleep(0, result=wire),
        prompt_overrides=override("live.duplex.addition", addition),
    ))
    while not wire.sent:
        await asyncio.sleep(0)
    assert wire.sent[0]["session"]["instructions"] == LIVE_OPERATING_RULES + "\n" + addition
    wire.incoming.put_nowait({"type": "session.started", "session": {"id": "provider", "status": "active"}})
    session = await task
    evidence = session.prompt_applications[0]
    assert evidence["program_id"] == "voice.duplex.openai.session"
    assert addition not in json.dumps(evidence)
    closing = asyncio.create_task(session.close())
    while not any(item.get("type") == "session.close" for item in wire.sent):
        await asyncio.sleep(0)
    wire.incoming.put_nowait({"type": "session.closed", "session": {"id": "provider", "status": "closed"},
                              "usage": {"seconds": 0.0}})
    await closing
