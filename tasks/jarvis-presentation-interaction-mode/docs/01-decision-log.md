# Decision log

## D1 — Separate foundation from Presentation

The window/prefab rework and Presentation mode are separate tasks. The lower-level scene/prefab foundation is reusable across the product; Presentation consumes it.

## D2 — Presentation is an interaction mode, not a voice architecture

SIMPLE/PRESENTATION/REUNION describe product behavior. Existing voice architecture choices remain orthogonal and should expose the same Presentation behavior where technically possible.

## D3 — Ambient speech has no action authority

Room speech is contextual evidence. It cannot directly authorize tool execution or become an addressed conversation turn merely because it was transcribed.

## D4 — Explicit address wins immediately

Wake/manual explicit address changes the lane from passive observation to an addressed Jarvis interaction. That work has absolute priority over speculative/background Presentation work.

## D5 — Fresh and enriched context are separate

A small recent transcript tail is optimized for temporal/deictic correctness. A slower bounded working set stores semantic topics, claims, sources, prepared artifacts and unresolved items. Never replace the fresh tail with only the enriched representation.

## D6 — Background preparation is encouraged but bounded

Presentation may proactively research, fact-check, resolve documents and prepare visuals. Work must be cancellable/deprioritizable and cannot consume the critical path for explicit requests.

## D7 — External manifestation is conservative

The target is "work a lot, manifest little". Ambient context alone should usually produce no visible/audible output.

## D8 — Visual commands are normally silent

An explicit display/navigation command should normally produce the requested visual effect without filler TTS.

## D9 — Questions may speak

A genuine addressed knowledge question may receive a useful spoken answer. Supporting visuals may also be prepared/shown when useful.

## D10 — Contradictions use discreet attention in V1

A sufficiently relevant/confident ambient contradiction may create a small fact-check/attention signal and discreet cue. Jarvis does not unsolicitedly speak the explanation.

## D11 — Tool Brain owns concrete UI execution

Presentation emits semantic UI intentions and urgency/timing constraints. Tool Brain owns concrete scene/browser/window tool choice, queueing, scheduling and cancellation.

## D12 — Scene/Prefab owns reusable visuals

Presentation does not define new rendering primitives. It requests/uses reusable visual objects through the current scene/prefab contract.

## D13 — Recording remains explicit and orthogonal

Ambient Presentation listening follows its existing privacy/freshness semantics. Durable audio/screen recording is an explicit capture feature and is not silently activated by Presentation mode.

## D14 — Canonical observability remains shared

Presentation events and decisions enrich the canonical event/timeline system; no separate presentation log becomes source of truth.
