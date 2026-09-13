"""One bounded Responses analysis request. No retry, conversation or execution authority."""
from __future__ import annotations

import asyncio
import json
import math
import time
import ipaddress
from typing import Callable
from urllib.parse import urlsplit

import httpx

from jarvis.domain.front_brain_hints import (
    FrontBrainHintRequest, FrontBrainHintResult, HintAnalysisStatus, decode_front_brain_hint,
)
from jarvis.domain.front_brain_prompt import FRONT_BRAIN_PROMPT_ID, build_front_brain_payload
from jarvis.domain.prompt_registry import PromptTarget
from jarvis.ports.v2 import DiagnosticSink

MAX_RESPONSE_BYTES = 65536


class LunaFrontBrainAnalyzer:
    def __init__(self, *, api_key: str, model: str = "gpt-5.6-luna", reasoning_effort: str = "low",
                 base_url: str = "https://api.openai.com/v1", timeout_s: float = 2.0,
                 max_output_tokens: int = 512, client: httpx.AsyncClient | None = None,
                 clock_ns: Callable[[], int] = time.monotonic_ns, diagnostics: DiagnosticSink | None = None,
                 prompt_overrides: object | None = None) -> None:
        if not api_key or not isinstance(model, str) or not model.strip():
            raise ValueError("analysis credentials and exact model are required")
        if reasoning_effort not in {"none", "low", "medium", "high", "xhigh", "max"}:
            raise ValueError("unsupported analysis reasoning effort")
        if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("analysis timeout must be finite and positive")
        if type(max_output_tokens) is not int or not 64 <= max_output_tokens <= 4096:
            raise ValueError("analysis output budget outside bounds")
        parsed = urlsplit(base_url)
        loopback = parsed.hostname == "localhost"
        try:
            loopback |= ipaddress.ip_address(parsed.hostname or "").is_loopback
        except ValueError:
            pass
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or not (
                parsed.scheme == "https" or parsed.scheme == "http" and loopback):
            raise ValueError("analysis URL must use HTTPS or HTTP loopback")
        self._key, self.model, self.reasoning_effort = api_key, model, reasoning_effort
        self._base_url, self._timeout_s = base_url.rstrip("/"), timeout_s
        self.max_output_tokens, self._client = max_output_tokens, client
        self._clock_ns, self._diagnostics = clock_ns, diagnostics
        from jarvis.runtime.prompt_runtime import normalize_prompt_overrides
        self._prompt_overrides = normalize_prompt_overrides(prompt_overrides)
        self.last_prompt_application: dict[str, object] | None = None
        from jarvis.runtime.prompt_runtime import resolve_prompt
        self.prompt_static_fingerprint = resolve_prompt(
            PromptTarget("analysis", "front_brain", "openai", self.model, "explicit", "hint"),
            overrides=self._prompt_overrides,
        ).static_fingerprint

    def payload(self, request: FrontBrainHintRequest) -> dict:
        payload, _ = self._resolved_payload(request)
        return payload

    def _resolved_payload(self, request: FrontBrainHintRequest):
        from jarvis.runtime.prompt_runtime import prompt_channel, resolve_prompt
        resolution = resolve_prompt(
            PromptTarget("analysis", "front_brain", "openai", self.model, "explicit", "hint"),
            overrides=self._prompt_overrides,
            variables={"observation": {
                "input": {"text": request.input.text, "revision": request.input.revision,
                          "committed": request.input.committed,
                          "commit_source": request.input.commit_source.value if request.input.commit_source else None},
                "origin_source": request.origin_source.to_payload() if request.origin_source else None,
                "context_source": request.context_source.to_payload() if request.context_source else None,
                "context": [{"role": message.role.value, "text": message.text} for message in request.context.messages],
            }},
        )
        base = build_front_brain_payload(
            request, model=self.model, reasoning_effort=self.reasoning_effort,
            max_output_tokens=self.max_output_tokens,
        )
        base["instructions"] = prompt_channel(resolution, "request.instructions")
        base["input"][0]["content"][0]["text"] = prompt_channel(resolution, "request.user_message")
        base["text"]["format"]["schema"] = json.loads(prompt_channel(resolution, "request.response_schema"))
        return base, resolution

    async def analyze(self, request: FrontBrainHintRequest) -> FrontBrainHintResult:
        if not isinstance(request, FrontBrainHintRequest):
            raise ValueError("analysis request must be typed")
        started = self._clock_ns()
        remaining = (request.deadline_monotonic_ns - started) / 1e9
        status, value, reason, usage, response_id = HintAnalysisStatus.TIMED_OUT, None, "deadline", None, None
        if remaining > 0:
            try:
                async with asyncio.timeout(min(remaining, self._timeout_s)):
                    request_payload, prompt_resolution = self._resolved_payload(request)
                    payload = await self._post(request_payload)
                    from jarvis.runtime.prompt_runtime import prompt_evidence
                    self.last_prompt_application = prompt_evidence(
                        prompt_resolution, application="sent", channel="request.instructions",
                    )
                    status, value, reason = _interpret(payload)
                    usage = _usage(payload.get("usage"))
                    reference = payload.get("id")
                    if isinstance(reference, str) and reference.isprintable() and 0 < len(reference) <= 256:
                        response_id = reference
            except (TimeoutError, httpx.TimeoutException):
                status, reason = HintAnalysisStatus.TIMED_OUT, "timeout"
            except (httpx.HTTPStatusError, httpx.RequestError):
                status, reason = HintAnalysisStatus.TRANSPORT_ERROR, "transport"
            except (ValueError, UnicodeError, RecursionError):
                status, reason = HintAnalysisStatus.INVALID_OUTPUT, "invalid_output"
        received = self._clock_ns()
        if received >= request.deadline_monotonic_ns:
            status, value, reason = HintAnalysisStatus.TIMED_OUT, None, "deadline"
        result = FrontBrainHintResult(request.request_id, status, value, received)
        if self._diagnostics is not None:
            self._diagnostics.emit("voice.hint.analysis", "Front Brain analysis completed", data={
                "request_id": request.request_id, "configuration_id": request.configuration_id,
                "session_id": request.input.correlation.session_id,
                "component_role": "analysis", "provider_id": "openai", "model_id": self.model,
                "model": self.model, "prompt_id": FRONT_BRAIN_PROMPT_ID, "reasoning_effort": self.reasoning_effort,
                "status": status.value, "reason": reason, "latency_ms": max(0, received - started) / 1e6,
                "provider_response_id": response_id, "usage": usage, "usage_source": "provider" if usage is not None else "unknown",
                **(self.last_prompt_application or {}),
            })
        return result

    async def _post(self, payload: dict) -> dict:
        if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 131072:
            raise ValueError("analysis request exceeds byte bound")
        client = self._client or httpx.AsyncClient(timeout=self._timeout_s)
        try:
            async with client.stream("POST", f"{self._base_url}/responses", json=payload,
                                     headers={"Authorization": f"Bearer {self._key}"}) as response:
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise ValueError("analysis response exceeds byte bound")
                    body.extend(chunk)
                def pairs(items):
                    result = {}
                    for key, value in items:
                        if key in result:
                            raise ValueError("duplicate analysis response key")
                        result[key] = value
                    return result
                def invalid(_value):
                    raise ValueError("nonfinite analysis response")
                def finite_float(value):
                    result = float(value)
                    if not math.isfinite(result):
                        raise ValueError("nonfinite analysis response")
                    return result
                parsed = json.loads(body, object_pairs_hook=pairs, parse_constant=invalid, parse_float=finite_float)
                if not isinstance(parsed, dict):
                    raise ValueError("analysis response must be an object")
                return parsed
        finally:
            if self._client is None:
                await client.aclose()


def _interpret(payload: dict) -> tuple:
    output = payload.get("output")
    if not isinstance(output, list):
        return HintAnalysisStatus.INVALID_OUTPUT, None, "missing_output"
    texts = []
    invalid = False
    for item in output:
        if not isinstance(item, dict):
            invalid = True
            continue
        if item.get("type") == "reasoning":
            continue  # Never retain or log model reasoning.
        if item.get("type") != "message" or item.get("role") != "assistant" or item.get("status") != "completed":
            invalid = True
        content = item.get("content", [])
        if not isinstance(content, list):
            invalid = True
            continue
        for part in content:
            if not isinstance(part, dict):
                invalid = True
            elif part.get("type") == "refusal":
                return HintAnalysisStatus.REFUSED, None, "refusal"
            elif part.get("type") == "output_text" and isinstance(part.get("text"), str):
                texts.append(part["text"])
            else:
                invalid = True
    if payload.get("status") != "completed" or payload.get("error") is not None or payload.get("incomplete_details") is not None:
        return HintAnalysisStatus.UNAVAILABLE, None, "not_completed"
    if invalid or len(texts) != 1:
        return HintAnalysisStatus.INVALID_OUTPUT, None, "ambiguous_output"
    return HintAnalysisStatus.AVAILABLE, decode_front_brain_hint(texts[0]), "available"


def _usage(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    result = {}
    for name in ("input_tokens", "output_tokens", "total_tokens"):
        count = value.get(name)
        result[name] = count if type(count) is int and 0 <= count <= 2**63 - 1 else None
    for group, field in (("input_tokens_details", "cached_tokens"), ("output_tokens_details", "reasoning_tokens")):
        details = value.get(group)
        count = details.get(field) if isinstance(details, dict) else None
        result[field] = count if type(count) is int and 0 <= count <= 2**63 - 1 else None
    return result if any(count is not None for count in result.values()) else None
