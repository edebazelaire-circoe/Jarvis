# Slice Execution Order

1. `00-project-manager` — readiness gate, blind repository audit and cross-handoff reconciliation
2. `01-runtime-contract-audit` — recover canonical scene/Board/speech/event/MCP/timeline contracts
3. `02-ui-tool-choice-contract` — stable selectable IDs, dynamic parameter choices and Tool Brain tool manifest
4. `03-perception-world-model` — compact user-visible world snapshot plus targeted inspection
5. `04-jarvis-intent-speech-contract` — Jarvis capability awareness, UI intentions and response/chunk progress events
6. `05-tool-brain-runtime` — provider-neutral decision runtime, hybrid wakeups and shadow mode
7. `06-action-queue-revalidation` — scheduled queue, cancellation/replacement, preconditions and immediate replan
8. `07-ui-capability-adapters` — scene, Board, process/agent and browser/display UI operations
9. `08-autonomy-ownership-guardrails` — single UI decision owner, reversible autonomy and destructive-action gates
10. `09-observability-timeline-extension` — add Tool Brain decisions/tool calls/queue state to existing live timeline
11. `10-e2e-rollout-hardening` — replay/evals, performance baseline, migration to default ownership and final regression pass

Do not dispatch implementation work until Slice 00 reports `READY`.
