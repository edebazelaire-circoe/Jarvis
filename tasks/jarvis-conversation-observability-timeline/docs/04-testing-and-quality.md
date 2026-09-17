# Testing and Quality

Require schema/serialization tests, monotonic ordering and idempotency tests, crash/truncated-write recovery, correlation tests across user/brain/mouth/sub-agent events, and API pagination/live-stream reconnection tests. Frontend runtime validation must demonstrate overlapping events, long sessions, empty/partial sessions, interrupted speech, and sub-agent spans. Agent-trace analysis must prove that a visible timeline event can be joined to the relevant diagnostic trace without exposing hidden reasoning.

## Mandatory QA doctrine

- Every implemented Slice gets a baseline `qa-verification` pass.
- Code changes add `code-review`.
- User-visible or runtime behavior adds `runtime-validation`.
- Agent prompts, tools, routing, modules, or agent runtime add `agent-trace-analysis` with real trace evidence.
- QA agents return evidence and findings; the Project Manager decides approve, rework, continue, new Slice, Issue, or escalation.
- A regression caused by the current Slice is blocking and cannot be parked in `Issues/`.
- Human validation is never a substitute for QA. Before any Human check, escalate machine validation to the maximum reasonable level and clear everything a machine could have caught.
