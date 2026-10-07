# Jarvis Wake Word

Project: Jarvis

This task implements local wake-word activation with "Hey Jarvis" while preserving F9 as a manual fallback. The initial provider is openWakeWord, isolated behind a replaceable provider contract.

Start with `slices/TODO.md`, then execute Slice 00 before dispatching any implementation Slice.

The consolidated product/technical handoff is `HANDOFF.md`.

## Global QA doctrine

- Every implemented Slice gets a baseline `qa-verification` pass.
- Code changes add `code-review`.
- User-visible or runtime behavior adds `runtime-validation`.
- Agent prompts, tools, routing, modules, or agent runtime add `agent-trace-analysis` with real trace evidence when applicable.
- QA agents return evidence and findings; the Project Manager decides approve, rework, continue, new Slice, Issue, or escalation.
- A regression caused by the current Slice is blocking and cannot be parked in `Issues/`.
- Human validation never substitutes for machine QA. Exhaust reasonable automated/runtime validation first.

Repository-specific file names and Task Types are intentionally unresolved until Slice 00 performs a blind repository audit.
