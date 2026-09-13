# Task10 — Luna adapter preparation and independent review

Preparation only, 2026-09-12. No provider call, credential read, production change or claim of account entitlement. The implementation lead owns the adapter/composition; independent QA owns `tests/unit/test_luna_front_brain_review.py`. This document does not advance slice acceptance.

## Existing production seams

- `jarvis/adapters/openai_http.py::OpenAIHTTP.post_json` already sends Responses-compatible JSON through HTTPX. Constructor injection accepts `httpx.AsyncClient`; the helper closes only clients it creates. Preserve that ownership. `pyproject.toml` declares HTTPX and aiohttp, neither OpenAI SDK nor tiktoken. Installed metadata confirms HTTPX 0.28.1/aiohttp 3.14.3 and neither optional package. No SDK dependency is needed for this adapter.
- `jarvis/adapters/openai_agent.py::OpenAIAgentBackend` demonstrates `/responses`, `instructions`, user `input_text` and `store:false`. Reuse its transport idiom, not its tool loop, continuation state, encrypted reasoning replay or permissive response parser. Analysis has no tools or execution handles.
- `jarvis/runtime/credentials.py::secret_for` resolves provider binding, sole provider credential, legacy flat key, then provider environment. Resolve the configured analysis provider independently from the conversational stack. Missing credentials means unavailable analysis, not a substitute model or blocked conversation. Never log settings, keys or error bodies.
- `jarvis/config.py` supplies the existing `OPENAI_BASE_URL` and `OPENAI_TIMEOUT_S` conventions. Do not load its complete legacy model/TTS configuration merely to obtain these settings. Preserve HTTPS/loopback URL policy through a narrow composition resolver. Validate local timeout as finite and positive.
- `FrontBrainVoiceConfig` already separates reflex/analysis models and has `reasoning_effort="low"`. `voice_capabilities.py` identifies Luna's text/structured-output capabilities. Configuration, implementation readiness and account availability remain different facts.
- `ports/front_brain.py::FrontBrainAnalyzer.analyze(request)` is the only execution port. Request/result/value are the strict Task09 types in `domain/front_brain_hints.py`. The adapter does not select current intent, commit input, speak, delegate or persist a backend outcome.

## Minimal request and prompt contract

Preserve `gpt-5.6-luna`; its verified Responses/structured-output support and reasoning-effort values are recorded in [verified provider contracts](verified-provider-contracts.md). Low remains a configured initial choice, not measured optimal latency. [Official model page](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

Use nonstreaming `POST /responses`, `model`, fixed application-owned versioned `instructions`, one user data item, `reasoning.effort`, `store:false`, and `text.format` with `type:json_schema`, `name:jarvis_front_brain_hint`, `strict:true`. No tools, previous response ID, provider conversation, executable output or hidden reasoning storage. Responses uses `text.format`; nullable fields are still required properties. [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

The exact Task09 object has `additionalProperties:false` and these seven required keys:

| Key | JSON schema shape |
| --- | --- |
| schema_version | integer, enum `[1]` |
| suggested_action | string or null; enum wait/backchannel/speak/preamble/delegate/null |
| intent_hypothesis | string or null, maximum 512 characters |
| addressed_confidence | number or null, minimum 0, maximum 1 |
| confidence | number or null, minimum 0, maximum 1 |
| likely_backend_needed | boolean or null |
| urgency | string or null; enum low/normal/high/immediate/null |

Keep schema construction next to the Task09 contract or derive its enum values from that contract; no divergent adapter-only value model. Always run `decode_front_brain_hint` on raw returned JSON even with strict provider schema. It rejects duplicates, extras, nonfinite numbers, invalid enums, boolean confidences and oversized UTF-8 values. Provider schema compliance is not authorization or truth.

The prompt asks only for revisable advisory classification, permits null/unknown, and explicitly distinguishes a provisional input's unknown origin from the known source of older context. Serialize selected input/revision/commit state and bounded context as JSON data. Do not interpolate transcript/context into instructions or forward a selected context message's DEVELOPER role as a new provider instruction. Do not include credentials, PCM, whole Core snapshots, tool catalogs, durable archives or raw diagnostic traces. A WAIT hint cannot delay useful speech; PREAMBLE does not attest work; DELEGATE cannot execute work. No response text or tool arguments belong in the hint schema.

## Deadline, outcome and resource ownership

Compute remaining time from `request.deadline_monotonic_ns` before dispatch. Already expired requests produce TIMED_OUT without POST. Enforce the smaller of remaining request time and configured transport timeout around the complete operation. The existing helper only configures timeouts on clients it creates; an injected client's default cannot replace the absolute request deadline. Check receipt against the same original deadline; the consumer independently checks time again at consumption.

| Observation | Result / behavior |
| --- | --- |
| completed response, exactly one valid hint JSON value | AVAILABLE, app-owned request ID and monotonic receipt |
| explicit refusal, even beside otherwise valid JSON | REFUSED, no value |
| incomplete/failed/cancelled provider response | UNAVAILABLE, bounded diagnostic reason; no partial hint |
| no valid output, malformed JSON, multiple ambiguous values, unexpected executable output | INVALID_OUTPUT, no value |
| outer deadline or HTTPX timeout cause | TIMED_OUT, no value |
| sanitized HTTP/network failure | TRANSPORT_ERROR or documented UNAVAILABLE classification, no body exposure |
| caller cancellation | propagate CancelledError; close owned resources, never turn cancellation into WAIT |

Require top-level completion and appropriate assistant output content before success parsing; absence of a completed status must not silently count as success. Known reasoning records may be skipped without retaining their content. Do not accept a function call as analysis output. No automatic retry of the same speculative request: a retry may already be stale or consume a second budget reservation.

`OpenAIHTTP` preserves timeout/network causes but `ProviderError` has no structured HTTP status property. Do not infer authentication from arbitrary provider text. If richer classification becomes necessary, add a narrow typed transport result rather than regex over messages. Local HTTP cancellation is not evidence that the remote request stopped processing or was free.

## Honest budget boundary

Task09 currently limits input to 8,192 characters, selected history to eight messages, combined selected text to 16,384 characters and hint JSON to 8,192 UTF-8 bytes. These are text/memory bounds, not token counts. Budget the complete serialized request, including fixed prompt and schema overhead, rather than transcript alone.

`max_output_tokens` bounds visible output plus reasoning. Usage reports optional input/output/total counts and cached/reasoning details; reasoning is not an extra quantity to add to output tokens. Missing usage is unknown, never zero. Automatic input truncation may discard selected evidence; avoid it. [Official Responses reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create).

Before claiming a hard per-turn token guarantee, the lead must choose and document a verified counter or a defensible conservative reservation covering the serialized request and model overhead. There is no installed tokenizer; characters/4 is not a hard bound. A simple implementation may enforce request count and text/byte limits plus provider output cap, recording actual tokens, but must label an input-token estimate as an estimate. If conservative reservation is used, do not release it on timeout or missing usage as though no tokens were spent. Token-count preflight over the network would be another owned, timed, budgeted call and must not become an audio dependency.

The coalescer, one-active/latest-pending ownership, per-turn reservations and final-revision allowance belong to Task10 runtime composition. The adapter receives a bounded request and output cap; it does not create an independent worker or silently restart a turn budget. Defaults must be named/configured and recorded with the prompt version, rather than an unexplained timer in the adapter. Full monetary aggregation belongs to Task18.

## Diagnostics and bounded parsing

Emit request/config/model/prompt version, latency, terminal status, safe reason and validated provider-reported usage with explicit provenance. Receipt IDs are application-owned; provider response ID is a separate bounded reference useful for usage deduplication. Validate counters as nonnegative integers excluding bool; preserve missing components, avoid counting cached input or reasoning twice. Never emit transcript, hypothesis, refusal body, authorization header or whole HTTP response.

The existing helper buffers the response body. A post-parse hint size limit is not a network download memory cap. If a strict response byte bound is part of acceptance, the implementation needs a narrow streaming/read limit before JSON decoding; document the actual bound and exercise it. This requires no provider SSE or new client framework.

## Independent acceptance tests

Use injected HTTPX MockTransport/controlled async client only; no live API, real credential lookup or shared fixture modifications. Agree exact constructor/diagnostic seams with the lead before adding the isolated review test file.

1. Inspect exact request: configured Luna/effort, Responses schema with all required nullable fields, bounded data projection, no tool/continuation fields, no promotion of untrusted selected context to instructions.
2. Valid typed hint remains advisory. Null action is no suggestion. Provisional B under context A retains origin unknown; adapter cannot manufacture Core IDs.
3. Refusal/incomplete/error wins over any adjacent valid JSON. Duplicate keys, NaN/Infinity/1e999, huge integer confidences, boolean confidences, extra authority fields, multiple documents and invalid shape never escape as AVAILABLE.
4. Expired-before-start makes zero requests. A delayed response cannot reset the original deadline. Caller cancellation during blocked POST propagates and closes only owned resources; injected shared client remains usable.
5. HTTP timeout/network/401/429/malformed outer JSON produce stable sanitized outcomes. No retry storm. Missing or malformed usage stays unknown without falsifying zero cost; output reasoning/cached subsets are not double counted.
6. ASCII, multibyte text, serialization overhead and response-body limits are tested separately from token reservations. Missing usage/timeouts keep a conservative budget charge until explicit reconciliation.
7. Integration owner separately proves coalesced deltas, final replacement, consumed-time freshness, admission revocation, no audio-path wait and no speech/Job authority. Adapter tests alone do not establish that production composition works.

Preparation evidence: source inspection and dependency metadata only; tests await lead API. Model account access, live latency and measured token cost remain untested.
