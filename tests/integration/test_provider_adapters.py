from __future__ import annotations

import io
import json
import wave

import httpx
import pytest

from jarvis.adapters.openai_agent import OpenAIAgentBackend
from jarvis.adapters.openai_transcription import OpenAITranscriptionBackend
from jarvis.adapters.openai_tts import OpenAITTSBackend
from jarvis.core.tools import ToolRegistry
from jarvis.domain.errors import ProviderError
from jarvis.domain.messages import AudioClip, CancellationToken, ToolOutput, UserTurn


def wav_fixture() -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 3200)
    return out.getvalue()


@pytest.mark.asyncio
async def test_transcription_contract_and_auth_header():
    seen = {}

    def handler(request: httpx.Request):
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        seen["content_type"] = request.headers.get("content-type")
        body = request.read()
        assert b'gpt-4o-transcribe' in body
        assert b'speech.wav' in body
        return httpx.Response(200, json={"text": "bonjour", "usage": {"type": "tokens", "total_tokens": 7}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend = OpenAITranscriptionBackend(api_key="secret", model="gpt-4o-transcribe", client=client)
    result = await backend.transcribe(AudioClip(wav_fixture()))
    await client.aclose()
    assert result.text == "bonjour"
    assert result.provider == "openai"
    assert result.diagnostics["total_tokens"] == 7
    assert seen["path"] == "/v1/audio/transcriptions"
    assert seen["auth"] == "Bearer secret"
    assert "multipart/form-data" in seen["content_type"]


@pytest.mark.asyncio
async def test_responses_function_call_and_local_continuation_are_typed():
    payloads = []
    responses = [
        {
            "output": [
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "memory_search",
                    "arguments": json.dumps({"query": "Jarvis"}),
                }
            ],
            "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        },
        {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Ton projet Jarvis est local et modulaire."}],
                }
            ]
        },
    ]

    def handler(request: httpx.Request):
        payload = json.loads(request.read())
        payloads.append(payload)
        assert payload["store"] is False
        assert payload["include"] == ["reasoning.encrypted_content"]
        return httpx.Response(200, json=responses.pop(0))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend = OpenAIAgentBackend(api_key="secret", model="test-model", client=client)
    tools = ToolRegistry()
    first = await backend.respond(UserTurn("t1", text="Quel est mon projet Jarvis ?"), tools)
    assert first.tool_calls[0].name == "memory_search"
    assert first.tool_calls[0].arguments == {"query": "Jarvis"}
    assert first.continuation_token
    second = await backend.respond(
        UserTurn(
            "t1",
            continuation_token=first.continuation_token,
            tool_outputs=(ToolOutput("call_1", "memory_search", {"hits": [{"title": "Jarvis V1"}]}),),
        ),
        tools,
    )
    await client.aclose()
    assert "local et modulaire" in second.text
    call_outputs = [i for i in payloads[1]["input"] if i.get("type") == "function_call_output"]
    assert call_outputs[0]["call_id"] == "call_1"
    assert "Jarvis V1" in call_outputs[0]["output"]


@pytest.mark.asyncio
async def test_invalid_provider_tool_arguments_do_not_escape_as_provider_types():
    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={
                "output": [{"type": "function_call", "call_id": "c", "name": "memory_search", "arguments": "not-json"}]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend = OpenAIAgentBackend(api_key="secret", model="test", client=client)
    result = await backend.respond(UserTurn("t", text="x"), ToolRegistry())
    await client.aclose()
    assert result.tool_calls[0].arguments == {}
    assert result.diagnostics["invalid_tool_argument_count"] == 1


class FakePlayback:
    def __init__(self):
        self.audio = b""

    async def play_wav(self, wav_bytes: bytes, *, interrupt: CancellationToken):
        self.audio = wav_bytes
        return 11, interrupt.cancelled


@pytest.mark.asyncio
async def test_tts_contract_binary_response_and_configurable_voice():
    seen = {}

    def handler(request: httpx.Request):
        seen.update(json.loads(request.read()))
        return httpx.Response(200, content=wav_fixture(), headers={"content-type": "audio/wav"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    playback = FakePlayback()
    backend = OpenAITTSBackend(
        api_key="secret",
        model="gpt-4o-mini-tts",
        voice="cedar",
        instructions="Parle clairement",
        client=client,
        playback=playback,
    )
    result = await backend.speak("Bonjour", interrupt=CancellationToken())
    await client.aclose()
    assert seen["voice"] == "cedar"
    assert seen["response_format"] == "wav"
    assert seen["instructions"] == "Parle clairement"
    assert playback.audio.startswith(b"RIFF")
    assert result.provider == "openai"


@pytest.mark.asyncio
async def test_tts_splits_text_longer_than_provider_input_limit():
    inputs = []

    def handler(request: httpx.Request):
        payload = json.loads(request.read())
        inputs.append(payload["input"])
        return httpx.Response(200, content=wav_fixture(), headers={"content-type": "audio/wav"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend = OpenAITTSBackend(
        api_key="secret",
        model="gpt-4o-mini-tts",
        voice="cedar",
        client=client,
        playback=FakePlayback(),
    )
    result = await backend.speak("x" * 8001, interrupt=CancellationToken())
    await client.aclose()
    assert len(inputs) == 3
    assert all(0 < len(value) <= backend.MAX_CHARS_PER_REQUEST for value in inputs)
    assert "".join(inputs) == "x" * 8001
    assert result.diagnostics["chunk_count"] == 3


@pytest.mark.asyncio
async def test_provider_429_maps_to_retryable_typed_error():
    def handler(request: httpx.Request):
        return httpx.Response(429, json={"error": {"message": "rate"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend = OpenAITranscriptionBackend(api_key="secret", model="test", client=client)
    with pytest.raises(ProviderError) as exc:
        await backend.transcribe(AudioClip(wav_fixture()))
    await client.aclose()
    assert exc.value.provider == "openai"
    assert exc.value.operation == "transcription"
    assert exc.value.retryable is True

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "item",
    [
        {"type": "function_call", "name": "memory_search", "arguments": "{}"},
        {"type": "function_call", "call_id": "call_1", "arguments": "{}"},
    ],
)
async def test_malformed_provider_function_call_is_rejected_before_broker(item):
    def handler(request: httpx.Request):
        return httpx.Response(200, json={"output": [item]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend = OpenAIAgentBackend(api_key="secret", model="test", client=client)
    with pytest.raises(ProviderError, match="Malformed Responses API function call"):
        await backend.respond(UserTurn("t", text="x"), ToolRegistry())
    await client.aclose()
