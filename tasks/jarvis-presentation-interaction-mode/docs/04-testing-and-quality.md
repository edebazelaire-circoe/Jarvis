# Testing and quality

## QA doctrine

- every implemented Slice gets `qa-verification`;
- code changes add `code-review`;
- user-visible/runtime behavior adds `runtime-validation`;
- agent prompts, routing, tools, Presentation policy, Tool Brain integration or runtime orchestration add `agent-trace-analysis` with real trace evidence;
- regressions caused by this task are blocking and cannot be deferred to Issues;
- human validation occurs only after maximum reasonable automated validation.

## Deterministic scenario matrix

The implementation must support replay/fake-driven tests for at least these scenarios:

1. **ambient monologue only** — transcript updates context, no assistant response/action;
2. **deictic visual command** — "montre-moi ça" resolves against fresh recent context and creates a display intent with no filler speech;
3. **knowledge question** — explicit question preempts background work and may produce speech + display intent;
4. **background preload** — ambient context triggers preparation; user never asks for it; nothing is manifested;
5. **background hit** — prepared resource is reused instantly when later requested;
6. **stale context** — old enriched context may not override newer transcript-tail evidence;
7. **contradiction** — relevant/high-confidence contradiction yields discreet attention, not unsolicited explanation;
8. **false/weak contradiction** — below-threshold candidate remains internal;
9. **explicit interruption** — explicit turn cancels/deprioritizes speculative work and stale queued display actions;
10. **mode exit** — switching back to SIMPLE stops Presentation-only ambient interpretation/preparation cleanly;
11. **recording boundary** — Presentation mode alone does not create durable recording artifacts;
12. **restart/recovery** — effective mode/session continuity follows canonical runtime contracts without treating old ambient speech as a new command.

## Performance expectations

- ambient processing must not materially increase explicit-turn latency;
- fresh transcript-tail updates should be available before slower enrichment;
- background concurrency must be bounded;
- Tool Brain intent publication should be lightweight and non-blocking;
- Presentation disable/exit must promptly stop speculative scheduling.

## Trace assertions

For representative flows, automated or trace-analysis QA must prove:

- ambient segment was classified non-authoritative;
- background job lifecycle is traceable;
- explicit turn preempted speculative work where expected;
- manifestation policy chose speech/display/none for a recorded reason;
- UI action, when used, came through the canonical Tool Brain path;
- scene/prefab resource references point to canonical runtime objects.
