# Testing and Quality

## Global QA doctrine

- Every implemented Slice gets `qa-verification`.
- Code changes add `code-review`.
- Runtime/user-visible behavior adds `runtime-validation`.
- Agent prompt/tool/routing/runtime changes add `agent-trace-analysis` with real trace evidence.
- Slice-caused regressions are blocking.
- Human validation follows maximum reasonable machine validation; it never substitutes for it.

## Regression baseline

Before implementation, Slice 00 records a clean baseline. Include relevant existing suites for `test_v2_wake_backends.py`, `test_v2_voice_toggle.py`, `test_realtime_audio_lifecycle.py`, `test_voice_duplex.py`, `test_voice_runtime.py`, `test_voice_production_composition.py`, `test_background_events.py`, `test_control_center_mvp.py`, Control Center voice architecture tests, prompt runtime wiring, Scene unit tests and scene transport integration.

## Required new test families

### Interaction mode contract/control plane
Parse/default/unknown mode; Simple default after migration; live revision/change events; Meeting visible but rejected; no collision with voice architecture Simple or `conversation_mode`.

### UI selector
Pure view-model tests under Node; canonical status not optimistic local state; keyboard/focus; failed change rollback; Meeting future/unavailable.

### Audio fan-out
Exactly one physical input owner in Presentation; bounded subscriber queues; no raw audio persistence; shared-PCM wake detector; manual key independent from backlog; bounded pre-roll; safe shutdown/restart.

### Ambient lane
Ambient observation cannot become authorized action; backlog does not delay explicit trigger; segment revision/dedupe; bounded transcript tail; stale ambient work cancellable/evictable.

### Response disposition
Visual command can complete with zero SpeechRequest; question can speak; ambient cannot spontaneously speak; Simple preserves behavior; errors/confirmations preserve safety.

### Working set/preparation
Bounded capacity and eviction; provenance preserved; duplicate research coalesced; hidden staged objects remain hidden until policy/action; fresh transcript beats stale prepared references.

### Fact-check attention
Confidence/evidence gated; failed search never contradiction; one new event -> one UI alert + at most one sound; polling/reload no replay; no automatic TTS.

### Priority and latency
Use deterministic artificial ambient backlog and slow speculative workers. Prove explicit-address trigger admission and priority path begin without waiting for ambient jobs. Record trigger-to-admission and trigger-to-first-visible/audible telemetry. Do not invent a user latency target before Slice 00 checks existing budgets.

## Human validation

Human checks focus on workstation realities unit/integration tests cannot prove: microphone ownership, wake/manual timing while speaking continuously, perceived alert volume, selector placement, and absence of unwanted filler speech.
