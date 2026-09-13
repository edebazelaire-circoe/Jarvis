# Task09 — Front Brain advisory hint contract

The sidecar analyzes an application-selected input snapshot and returns optional
advice. Task09 defines immutable values, a small port, a deterministic consumer
and a permanent test fake. It adds no model call, worker, queue, provider reader,
Core ingress, executor or speech-producing path.

## Ownership and API

| Owner | File / API |
| --- | --- |
| Neutral request/value/result, strict value JSON | `jarvis/domain/front_brain_hints.py` |
| Optional asynchronous analysis boundary | `jarvis/ports/front_brain.py::FrontBrainAnalyzer.analyze(request)` |
| One expected request and deterministic advisory consumption | `jarvis/runtime/front_brain_hints.py::FrontBrainHintConsumer` |
| Controlled test-only analyzer | `tests/fakes/front_brain.py::FakeFrontBrainAnalyzer` |
| Contract, fake, authority and journal tests | `tests/unit/test_front_brain_hints.py` |
| Independent review cases | `tests/unit/test_front_brain_hint_review.py` |

`FrontBrainHintRequest` contains exactly these application-owned fields:

| Field | Type / meaning |
| --- | --- |
| `request_id` | Fresh opaque analysis request identity, assigned by the future Task10 factory |
| `input` | `VoiceUserRecord`: full current text, canonical correlation, transcript ID/revision, committed phase and explicit commit source |
| `origin_source` | `SpeechSource | None`: actual originating Core turn, when known |
| `context_source` | `SpeechSource | None`: committed Core intent selected as analysis context |
| `context` | Bounded `VoiceContext`; its revision is a captured watermark, not a universal equality condition |
| `analysis_admission_id` | Opaque application-owned analysis-admission scope identity; no tool/job/output permission |
| `configuration_id` | Exact analysis configuration incarnation, including relevant model/prompt changes |
| `deadline_monotonic_ns` | Original process-local exclusive deadline; a reply cannot renew it |
| `schema_version` | Integer1, rejecting booleans and unknown versions |

These request/result envelopes are process-local typed values. Task09 does not
provide snapshot rehydration or a model JSON codec for their clocks, IDs or
admission fields. The provider receives the selected projection in Task10; it
does not author validity metadata. Existing `FrontBrainVoiceConfig` remains the
only model/role selection config.

## Provisional origin B is not committed context A

A provisional input B can have `origin_source=None`, `context_source=A`, and its
own canonical transcript identity/revision. A's Core turn or epoch must never be
borrowed as B's origin. A canonical committed record is also not automatically a
Core admission. Even when both identities exist, Core turn IDs and canonical
voice turn IDs are different namespaces and are not compared for equality.

Only an explicit `VoiceCorrelation.source_correlation_id` linkage, when present,
is checked against `origin_source.correlation_id`. Both then denote the same
Core correlation namespace. Task08's `SpeechSource` and exact
`SpeechDependency(work_id, source_correlation_id)` are reused unchanged.

The selected input is a full replacement snapshot per analysis request, not a
second accumulator of provider deltas. Assistant context must be selected from
confirmed playback evidence; generated/intended text is not heard context.
The request never owns or rewrites the canonical ledger.

## Hint value and JSON

`FrontBrainHintValue` has nullable fields:

- `suggested_action: ReflexAction | None` — WAIT, BACKCHANNEL, SPEAK, PREAMBLE or DELEGATE.
- `intent_hypothesis: str | None` — a short optional interpretation.
- `addressed_confidence: float | None` and `confidence: float | None`.
- `likely_backend_needed: bool | None`.
- `urgency: SpeechPriority | None`.

Unknown remains null; it is not zero, false or WAIT. An available value with
`suggested_action=None` produces `NO_SUGGESTION`, preserving any other advisory
fields without fabricating an action. No conversation-phase field is added in
v1 because no identified controller consumer requires it.

`encode_front_brain_hint(value) -> dict` and
`decode_front_brain_hint(raw_json: str) -> FrontBrainHintValue` use this exact
schema, including all nullable keys:

```json
{
  "schema_version": 1,
  "suggested_action": null,
  "intent_hypothesis": null,
  "addressed_confidence": null,
  "confidence": null,
  "likely_backend_needed": null,
  "urgency": null
}
```

Unknown/missing fields, unrecognized enums, nested substitute objects, duplicate
JSON keys at any depth, NaN/infinity/exponent overflow, malformed JSON and
excessive nesting are rejected with `ValueError`. Confidence is finite in
`[0,1]`; booleans and huge integers are rejected without numeric-conversion
overflow. Urgency uses the existing lowercase priority labels. There is no
reasoning/reason text, speech text, tool name/arguments or executable plan.
Any later `ReflexDecision` adaptation must use an application-owned reason such
as `front_brain_advisory`, not model reasoning copied into logs or policy.

Bounds: current text8192 characters; at most eight selected context messages;
16384 aggregate current+context characters; hypothesis512 characters; printable
IDs256 characters; raw hint JSON8192 UTF-8 bytes. Context roles must be typed
USER, ASSISTANT or DEVELOPER. These are memory/schema bounds, not provider token
budgets or timing defaults.

## Result and consumption

`FrontBrainHintResult(request_id, status, value, received_monotonic_ns,
schema_version=1)` binds the response to the original application request.
`HintAnalysisStatus` distinguishes AVAILABLE, UNAVAILABLE, REFUSED, TIMED_OUT,
INVALID_OUTPUT and TRANSPORT_ERROR. AVAILABLE requires a typed value; other
statuses require `value=None`. A provider refusal/incomplete response must be
classified before constructing an available hint. Cancellation propagates as
`CancelledError`; it is not a fabricated model WAIT.

The consumer's constructor accepts only an optional `DiagnosticSink`.

```python
consumer.expect(request)
decision = consumer.consume(
    result,
    current_input=current_input,
    current_origin_source=current_origin_source,
    current_context_source=current_context_source,
    current_configuration_id=current_configuration_id,
    current_admission_id=current_admission_id,
    source_complete=source_complete,
    invalidated_dependencies=invalidated_dependencies,
    now_monotonic_ns=now_monotonic_ns,
    useful_ready=useful_ready,
)
```

`expect` replaces the sole expected request. Identical re-registration returns
false without changing its consumed flag; changed binding/deadline under the
same ID raises `ValueError`. `invalidate` consumes that single slot while
retaining its ID, so re-registration cannot resurrect it. The Task10 factory
must never recycle old IDs after another request replaces the slot; Task09 does
not introduce an unbounded global tombstone registry.

`consume` returns immutable `HintConsumption(disposition, reason, value,
analysis_status)`. A wrong-ID reply leaves the newer expectation intact. A
matching terminal result is consumed once, including unavailable, stale or
expired results. Consumption compares the current session, exact input record
(including text, revision, commit phase/source), configuration, admission,
origin and selected context source, plus relevant revoked dependencies. An
incomplete Task08 source projection cannot certify eligibility. Unrelated global
snapshot revisions and unrelated work generations do not invalidate the hint.

The consumer checks both receipt evidence and **current consumption time**.
`now_monotonic_ns >= deadline_monotonic_ns` expires a result even if it arrived
earlier. Duplicate/late hints do not renew TTL or queue speech. These clocks
must belong to the same process-local clock domain and never be rehydrated as
durable authority. Current-state arguments are validated typed application
evidence, not model-supplied fields.

When useful direct content is ready, WAIT/BACKCHANNEL/PREAMBLE suggestions are
ignored with `useful_content_ready`. An available PREAMBLE does not attest work;
Task06 still requires actual admitted work and applies its existing policy.
SPEAK still needs eligible existing content through Task08. DELEGATE remains
advisory and cannot submit a turn, Job or tool. Confidence does not establish
owner identity, confirmation or upload permission. No result can overwrite
committed user text, heard words or invalidated output admission.

## Fake, observability and tests

The permanent fake accepts a supplied value/status, controlled `asyncio.Event`
gate, optional injected exception and injected nanosecond clock. It has no
autonomous task or timer. Its caller owns and joins the task; cancellation
propagates and releases active-call bookkeeping. Retained request inventory is
bounded32. It is neither imported by production nor a provider simulator.

The consumer emits normal info-level `voice.hint.expected`,
`voice.hint.invalidated`, `voice.hint.consumed` and `voice.hint.ignored` through
the existing `DiagnosticSink`/`RuntimeJournal`. Correlation includes request ID,
frontend session, transcript group/revision and committed flag when matching.
Decision/outcome/reason values are stable enums. Raw input, hypotheses,
context, secrets and model reasoning are absent. Expected timeout/refusal/stale
outcomes are not logged as critical failures. Task10 owns adapter transport
failure diagnostics and request/token/latency counters.

The contract/fake suite exercises strict codecs and bounds, distinct identity
namespaces, provisional-to-committed invalidation, consumption-time expiry,
same-ID registration, late replies under a newer expectation, exact dependency
revocation, unrelated state updates, configured unavailability, controlled
cancellation and real RuntimeJournal records. The project journal reader
`read_jsonl_tail` verifies normal events and privacy; no separate LogBroker CLI
is available in this repository. Independent review adds malformed nested JSON,
nonfinite/huge numbers, subscription-independent state changes and authority
checks.

After review fixes, combined Task09 suites: **128 passed in0.40s**, `-W error`.
Parent independent gate: **284 passed in6.70s**, `-W error`, including Task09,
architecture/config, canonical state04, reflex06 and presentation/scheduler08.
Global diff checks were clean. These are deterministic contract proofs, not
live model quality, billing, hardware or latency claims. Parent owns acceptance.

## Task10 handoff

Implement one optional analyzer worker with one in-flight request and one latest
replaceable pending snapshot; reuse the existing canonical event reader/fan-out.
Do not open a second `VoiceFrontend.events()` reader or provider socket consumer.
The current compatibility frontend forwards user records to Core only after
admission, so speculative fan-out needs explicit bounded ownership and closure
of rejected groups. Analysis admission must preserve the existing pre-upload
owner boundary; uncertain addressing is not permission to upload rejected input.

Task10 owns model/config/prompt fingerprinting, structured output/refusal
mapping, projection building, debounce/coalescing, call/token budgets, deadlines,
cancellation and lifecycle integration. Preserve original request bindings on
retry; invalidate them on session/config/admission changes. Recheck consumption
eligibility immediately before handing advisory evidence to existing policy.
Task11 alone adds admitted execution and irreversible-action authority; Task09
does not provide that capability.
