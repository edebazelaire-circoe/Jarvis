# Testing and Quality

Require settings migration/backward compatibility tests, catalog availability-state tests, stale/live source behavior, sorting/filtering/comparison tests, and runtime UI validation at multiple viewport sizes. Frontend QA must use `/impeccable` and Claude routing where supported. Human validation checks that the new IA is materially easier to navigate, that technical controls are immediately visible, and that no unavailable model appears selectable as if usable.

## Mandatory QA doctrine

- Every implemented Slice gets a baseline `qa-verification` pass.
- Code changes add `code-review`.
- User-visible or runtime behavior adds `runtime-validation`.
- Agent prompts, tools, routing, modules, or agent runtime add `agent-trace-analysis` with real trace evidence.
- QA agents return evidence and findings; the Project Manager decides approve, rework, continue, new Slice, Issue, or escalation.
- A regression caused by the current Slice is blocking and cannot be parked in `Issues/`.
- Human validation is never a substitute for QA. Before any Human check, escalate machine validation to the maximum reasonable level and clear everything a machine could have caught.
