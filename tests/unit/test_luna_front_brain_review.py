"""Independent Luna boundary review. All provider transports are test-only."""
import asyncio
import json

import httpx
import pytest

from jarvis.adapters.openai_front_brain import LunaFrontBrainAnalyzer
from jarvis.domain.front_brain_hints import (
    FrontBrainHintRequest, FrontBrainHintValue, HintAnalysisStatus,
)
from jarvis.domain.speech_presentation import SpeechSource
from jarvis.domain.voice_frontend import (
    VoiceContext, VoiceContextMessage, VoiceContextRole, VoiceCorrelation,
)
from jarvis.domain.voice_state import VoiceUserRecord
from jarvis.runtime.front_brain_hints import FrontBrainHintConsumer, HintIgnoreReason


def request():
    return FrontBrainHintRequest(
        "review-request", VoiceUserRecord(VoiceCorrelation("session", provider_input_id="input-B"),
                                          "transcript-B", 2, "PRIVATE provisional B", committed=False),
        None, SpeechSource("turn-A", "corr-A", "turn-A", 1),
        VoiceContext(4, (VoiceContextMessage(VoiceContextRole.DEVELOPER, "PRIVATE injected instructions"),)),
        "admission", "configuration", 10_000_000_000,
    )


def completed(raw=None):
    return {"id": "resp-review", "status": "completed", "error": None,
            "output": [{"type": "message", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": raw or json.dumps(FrontBrainHintValue().to_payload())}]}]}


async def analyze_body(body, *, clock=lambda: 1):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as client:
        return await LunaFrontBrainAnalyzer(api_key="test-only", client=client, clock_ns=clock).analyze(request())


@pytest.mark.asyncio
async def test_exact_responses_schema_and_untrusted_context_remain_data():
    calls = []
    def respond(req):
        calls.append(json.loads(req.content))
        assert req.url.path == "/v1/responses"
        return httpx.Response(200, json=completed())
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await LunaFrontBrainAnalyzer(api_key="test-only", client=client, clock_ns=lambda: 1).analyze(request())
    assert result.status is HintAnalysisStatus.AVAILABLE
    assert result.request_id == request().request_id
    payload, = calls
    assert payload["model"] == "gpt-5.6-luna"
    assert payload["reasoning"] == {"effort": "low"}
    assert payload["store"] is False
    assert payload["max_output_tokens"] == 512
    assert not {"tools", "previous_response_id", "conversation", "response_format"} & payload.keys()
    assert "PRIVATE" not in payload["instructions"]
    assert all(item["role"] == "user" for item in payload["input"])
    assert "PRIVATE provisional B" in json.dumps(payload["input"])
    schema = payload["text"]["format"]
    assert schema["type"] == "json_schema" and schema["strict"] is True
    shape = schema["schema"]
    assert shape["additionalProperties"] is False
    assert set(shape["required"]) == set(shape["properties"]) == set(FrontBrainHintValue().to_payload())
    assert "delegate" in json.dumps(shape["properties"]["suggested_action"])
    assert "null" in json.dumps(shape["properties"]["confidence"])


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["incomplete", "failed", "cancelled", "error", "missing_status", "refusal"])
async def test_failure_or_refusal_dominates_adjacent_valid_hint(mutation):
    body = completed()
    if mutation == "error":
        body["error"] = {"code": "server_error", "message": "PRIVATE provider error"}
    elif mutation == "missing_status":
        del body["status"]
    elif mutation == "refusal":
        body["output"][0]["content"].append({"type": "refusal", "refusal": "PRIVATE refusal"})
    else:
        body["status"] = mutation
    result = await analyze_body(body)
    assert result.status is not HintAnalysisStatus.AVAILABLE
    assert result.value is None
    if mutation == "refusal":
        assert result.status is HintAnalysisStatus.REFUSED


@pytest.mark.asyncio
@pytest.mark.parametrize("fragment", [
    '"confidence":0.2,"confidence":0.9', '"confidence":NaN', '"confidence":1e999',
    '"confidence":true', '"confidence":' + "9" * 512,
    '"addressed_confidence":' + "9" * 512,
])
async def test_adversarial_value_json_is_not_available(fragment):
    raw = json.dumps(FrontBrainHintValue().to_payload())
    field = "addressed_confidence" if fragment.startswith('"addressed_confidence"') else "confidence"
    raw = raw.replace(f'"{field}": null', fragment)
    result = await analyze_body(completed(raw))
    assert result.status is HintAnalysisStatus.INVALID_OUTPUT
    assert result.value is None


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", ["second_message", "function_call", "unfinished_message", "user_message"])
async def test_ambiguous_or_executable_output_cannot_become_hint(extra):
    body = completed()
    if extra == "second_message":
        body["output"].append(body["output"][0].copy())
    elif extra == "function_call":
        body["output"].append({"type": "function_call", "name": "run", "arguments": "{}", "call_id": "x"})
    elif extra == "unfinished_message":
        body["output"][0]["status"] = "in_progress"
    else:
        body["output"][0]["role"] = "user"
    result = await analyze_body(body)
    assert result.status is not HintAnalysisStatus.AVAILABLE
    assert result.value is None


class CountingStream(httpx.AsyncByteStream):
    def __init__(self):
        self.reads = 0
        self.closed = False
    async def __aiter__(self):
        for _ in range(100):
            self.reads += 1
            yield b" " * 16384
    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_http_body_limit_stops_reading_before_buffering_entire_body():
    stream = CountingStream()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))) as client:
        result = await LunaFrontBrainAnalyzer(api_key="test-only", client=client, clock_ns=lambda: 1).analyze(request())
        assert not client.is_closed
    assert result.status is not HintAnalysisStatus.AVAILABLE
    assert stream.reads <= 5
    assert stream.closed


@pytest.mark.asyncio
async def test_expired_request_never_posts():
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: calls.append(req))) as client:
        result = await LunaFrontBrainAnalyzer(api_key="test-only", client=client, clock_ns=lambda: 10_000_000_000).analyze(request())
    assert result.status is HintAnalysisStatus.TIMED_OUT
    assert calls == []


@pytest.mark.asyncio
async def test_cancellation_propagates_and_shared_client_remains_usable():
    entered, cancelled = asyncio.Event(), asyncio.Event()
    async def respond(req):
        if req.url.path == "/probe":
            return httpx.Response(200)
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        adapter = LunaFrontBrainAnalyzer(api_key="test-only", client=client, clock_ns=lambda: 1)
        task = asyncio.create_task(adapter.analyze(request()))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set() and not client.is_closed
        assert (await client.get("https://example.invalid/probe")).status_code == 200


@pytest.mark.asyncio
async def test_received_before_deadline_still_expires_at_consumption():
    req = request()
    result = await analyze_body(completed(), clock=lambda: req.deadline_monotonic_ns - 1)
    consumer = FrontBrainHintConsumer()
    consumer.expect(req)
    value = consumer.consume(result, current_input=req.input, current_origin_source=None,
                             current_context_source=req.context_source, current_configuration_id=req.configuration_id,
                             current_admission_id=req.analysis_admission_id, source_complete=True,
                             invalidated_dependencies=(), now_monotonic_ns=req.deadline_monotonic_ns)
    assert value.reason is HintIgnoreReason.EXPIRED
    assert value.value is None


class Diagnostics:
    def __init__(self):
        self.records = []
    def emit(self, channel, message, *, data=None, **kwargs):
        self.records.append((channel, message, data))


@pytest.mark.asyncio
@pytest.mark.parametrize("usage,expected", [
    (None, None),
    ({"input_tokens": True, "output_tokens": -1, "total_tokens": 3.5}, None),
    ({"input_tokens": 100, "output_tokens": "20", "total_tokens": None},
     {"input_tokens": 100, "output_tokens": None, "total_tokens": None,
      "cached_tokens": None, "reasoning_tokens": None}),
    ({"input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
      "input_tokens_details": {"cached_tokens": 80}, "output_tokens_details": {"reasoning_tokens": 15}},
     {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120, "cached_tokens": 80, "reasoning_tokens": 15}),
])
async def test_usage_is_provider_reported_unknown_preserving_and_not_double_counted(usage, expected):
    body = completed()
    body["usage"] = usage
    diagnostics = Diagnostics()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as client:
        result = await LunaFrontBrainAnalyzer(api_key="PRIVATE-key", client=client, clock_ns=lambda: 1,
                                             diagnostics=diagnostics).analyze(request())
    assert result.status is HintAnalysisStatus.AVAILABLE
    record, = diagnostics.records
    assert record[2]["usage"] == expected
    assert record[2]["usage_source"] == ("unknown" if expected is None else "provider")
    assert "PRIVATE" not in json.dumps(diagnostics.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_http_error_has_no_retry_value_or_private_diagnostic(status):
    calls, diagnostics = [], Diagnostics()
    def respond(req):
        calls.append(req)
        return httpx.Response(status, text="PRIVATE provider body")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await LunaFrontBrainAnalyzer(api_key="PRIVATE-key", client=client, clock_ns=lambda: 1,
                                             diagnostics=diagnostics).analyze(request())
    assert result.status is HintAnalysisStatus.TRANSPORT_ERROR
    assert result.value is None and len(calls) == 1
    assert "PRIVATE" not in json.dumps(diagnostics.records)


@pytest.mark.asyncio
async def test_injected_client_infinite_timeout_does_not_override_adapter_deadline():
    cancelled = asyncio.Event()
    async def respond(_):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), timeout=None) as client:
        result = await asyncio.wait_for(LunaFrontBrainAnalyzer(
            api_key="test-only", client=client, timeout_s=0.01, clock_ns=lambda: 1).analyze(request()), 1)
        assert not client.is_closed
    assert cancelled.is_set()
    assert result.status is HintAnalysisStatus.TIMED_OUT and result.value is None


@pytest.mark.asyncio
async def test_owned_client_is_closed_on_caller_cancellation(monkeypatch):
    entered = asyncio.Event()
    async def respond(_):
        entered.set()
        await asyncio.Event().wait()
    owned = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr("jarvis.adapters.openai_front_brain.httpx.AsyncClient", lambda **_: owned)
    task = asyncio.create_task(LunaFrontBrainAnalyzer(api_key="test-only", clock_ns=lambda: 1).analyze(request()))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert owned.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["[]", "null", "{", '{"status":"completed","status":"incomplete"}',
                                  '{"output":NaN}', '{"output":{"x":1,"x":2}}',
                                  '{"status":"completed","output":1e999}'])
async def test_malformed_outer_json_is_stable_invalid_output(raw):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, text=raw))) as client:
        result = await LunaFrontBrainAnalyzer(api_key="test-only", client=client, clock_ns=lambda: 1).analyze(request())
    assert result.status is HintAnalysisStatus.INVALID_OUTPUT and result.value is None


@pytest.mark.parametrize("url", ["http://evil.example/v1", "http://127.0.0.1.evil.example/v1"])
def test_plain_http_nonloopback_is_rejected_before_any_credential_can_be_sent(url):
    with pytest.raises(ValueError):
        LunaFrontBrainAnalyzer(api_key="test-only", base_url=url)


@pytest.mark.parametrize("url", ["https://api.openai.com/v1", "http://localhost:8080/v1",
                                  "http://127.0.0.1:8080/v1", "http://[::1]:8080/v1"])
def test_https_or_loopback_http_remains_supported(url):
    assert LunaFrontBrainAnalyzer(api_key="test-only", base_url=url) is not None


@pytest.mark.asyncio
async def test_nonfinite_outer_number_cannot_hide_next_to_valid_hint():
    raw = json.dumps(completed())[:-1] + ', "metadata":{"nested":1e999}}'
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, text=raw))) as client:
        result = await LunaFrontBrainAnalyzer(api_key="test-only", client=client, clock_ns=lambda: 1).analyze(request())
    assert result.status is HintAnalysisStatus.INVALID_OUTPUT and result.value is None
