# Jarvis Category 2 Test Lab

## Purpose

Build a native Jarvis diagnostic subsystem called the Category 2 Test Lab. It is not a CI suite and it does not contain an intelligent debugging agent. It is a deterministic, instrumented laboratory that exposes diagnostics to humans, Jarvis itself, coding/debug agents, and later an optional MCP facade.

The Test Lab exists for selective investigation after a symptom is observed. A caller should be able to capture a real session, inspect normalized evidence, choose one or a few targeted diagnostics, simulate or replay interaction, score results, compare runs, sweep isolated parameters, and promote a useful ad-hoc experiment into a permanent diagnostic.

## Project identity

- Project: `Jarvis`
- Repository: `edebazelaire-circoe/Jarvis`
- Planning snapshot: `main@c33207281a5b6a10a6630b8914f19855ea096473`
- Snapshot date: `2026-09-12`
- Drive destination: `Jarvis/task/to-do/jarvis-category2-test-lab/`

The live repository must be audited again by Slice 00 before implementation. The 2026-09-12 voice transcript is evidence for seed diagnostics, not a frozen statement of current runtime behavior. Main already changed after that session, including barge-in/provider-VAD handling.

## Locked product decisions

1. Category 2 is a native Jarvis subsystem, not a new pytest family.
2. One diagnostic identity may have specialized execution profiles: `virtual`, `audio`, `live`, `hardware:auto`, `hardware:guided`.
3. The Test Lab has no embedded intelligence. It measures, executes, scores, compares, stores, and exposes tools. Humans or external agents reason over the results.
4. The canonical contract is a native internal API with thin adapters. MCP is optional and not foundational.
5. Every execution creates a persistent, replayable, comparable `TestRun`.
6. Test runs are isolated by default. Real providers/devices are reserved only by profiles that require them.
7. Each diagnostic owns its metrics, assertions, thresholds, and score contract. Global scores are secondary UI summaries.
8. Permanent diagnostics coexist with safe ad-hoc scenarios composed from controlled primitives.
9. Test runs may apply isolated overrides and parameter sweeps but never mutate permanent Jarvis configuration automatically.
10. Real sessions enter the Test Lab through a normalized first-class `DiagnosticBundle` rather than repeated LLM reading of raw logs.
11. `hardware:guided` is a supported mode in which the human is an explicit scenario actor.
12. Official diagnostics use a declarative manifest plus specialized implementation code where necessary.
13. Runs execute in supervised isolated workers, not in the Control Center process.
14. Cost/capability permission gates are mechanical: cheap virtual work can run freely; live/provider/hardware/human profiles require the declared resources/authorization.

## Existing repository leverage

The task should reuse rather than replace existing foundations:

- `tests/integration/async_conversation_harness.py` already mounts most of the production path in memory with controlled Realtime, audio, and brain doubles.
- `tests/integration/test_v2_async_conversation.py` already exercises interruption timing, stale speech rejection, and conversation races.
- `jarvis/runtime/realtime_audio.py` owns continuous Realtime input/output and barge-in behavior.
- `jarvis/runtime/speech_scheduler.py` already owns brain speech queuing, delivery telemetry, interruption notification, TTL/supersession, and reflex scheduling.
- `jarvis/runtime/journal.py` already writes structured JSONL diagnostics.
- `jarvis/runtime/audio_devices.py` already provides user-facing input/output diagnostics using the same `sounddevice` path.
- `jarvis/runtime/control_center.py` already exposes local HTTP APIs and audio-test endpoints suitable for a future Test Lab panel.
- `docs/handoff-realtime-brain/docs/04-testing-and-quality.md` already establishes the key doctrine: deterministic tests without microphone/provider first, workstation/provider acceptance as a separate layer.
- `docs/handoff-realtime-brain/docs/05-event-contracts.md` defines stable IDs and voice delivery telemetry that Test Lab evidence should preserve.

## Project Manager start

Open `slices/TODO.md`, then execute `slices/00-project-manager/SLICE.md` yourself. Slice 00 is the readiness/orchestration gate and must not be delegated.

No implementation Slice may be dispatched until Slice 00 declares `READY`.

The Workspace Task Type vocabulary was not exposed to the task creator. Later Slice metadata therefore has `task_type: null` plus a blocker. Slice 00 must resolve valid existing Task Types before dispatch; do not invent them.

## Mandatory QA doctrine

Apply this to every implemented Slice:

- Every implemented Slice gets a baseline `qa-verification` pass.
- Code changes add `code-review`.
- User-visible or runtime behavior adds `runtime-validation`.
- Agent prompts, tools, routing, modules, or agent runtime add `agent-trace-analysis` with real trace evidence.
- QA agents return evidence and findings; the Project Manager decides approve, rework, continue, new Slice, Issue, or escalation.
- A regression caused by the current Slice is blocking and cannot be parked in `Issues/`.
- Human validation never substitutes for machine QA. Before a Human check, escalate machine validation to the maximum reasonable level and clear everything a machine could have caught.

## Human validation doctrine

Human checks are intentionally limited to behavior that cannot be fully proven in deterministic automation, especially actual workstation acoustics and usability of the Test Lab UI/guided flow. Every such check has an explicit manifest in the relevant Slice.

## Global non-goals

- Do not make Category 2 part of every normal CI/release run.
- Do not add an autonomous LLM agent inside Test Lab.
- Do not make MCP the core contract or require MCP for internal callers.
- Do not allow arbitrary Python execution inside ad-hoc scenario definitions.
- Do not let experiments write permanent settings automatically.
- Do not persist hidden chain-of-thought.
- Do not retain unlimited raw audio by default.
- Do not rewrite current voice/barge-in behavior merely to match the 2026-09-12 incident transcript; reproduce current failures first.
