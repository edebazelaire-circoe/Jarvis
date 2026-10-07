# 04 — Testing and Quality

## Mandatory QA composition

- Every implemented Slice: `qa-verification`.
- Any code change: `code-review`.
- User-visible/runtime behavior: `runtime-validation`.
- Tool Brain prompts, model adapter, MCP/tool metadata, routing, event contracts or agent runtime: `agent-trace-analysis` with real trace evidence.
- Frontend timeline changes require browser/runtime validation in addition to ordinary tests.

A regression introduced by the current Slice is blocking and cannot be deferred to `Issues/`.

## Contract tests

### Stable identity

- IDs remain stable while objects exist.
- Removed objects disappear from valid choices.
- Labels can change without changing identity.
- Duplicate/ambiguous labels do not affect ID resolution.

### Dynamic choices

- Every constrained parameter returns only currently legal values.
- Choice responses carry enough label/type/status metadata for model selection.
- Choice generation and mutation validation use compatible state revisions.
- Invalid/fabricated IDs are rejected deterministically.

### Perception

- Snapshot contains the active Board and currently relevant visible objects.
- Snapshot is bounded in size and omits irrelevant bulk metadata.
- Targeted inspection returns richer data for a chosen ID.
- Sensitive/unrelated state is not dumped merely because it exists.

### Speech synchronization

- Current and upcoming response chunks are correlated to one response ID.
- Chunk progress survives normal timing variation.
- User interruption invalidates obsolete future speech-bound actions.

### Queue / validator

- now/event/speech triggers execute in the expected order.
- cancel/replace/reprioritize/reschedule are deterministic.
- stale preconditions cause `action_invalidated`, not forced mutation.
- invalidation produces an immediate replan wake.
- Board switch/authority change invalidates incompatible actions.

## Agent trace scenarios

At minimum capture real traces for:

1. **Show + analyze** — user asks Jarvis to show one process and start a non-UI analysis; Tool Brain handles display while Jarvis handles analysis.
2. **Long response** — Jarvis has a long generated response; Tool Brain prepares/focuses visuals when their speech chunks arrive.
3. **Interruption** — user changes subject mid-response; queued obsolete actions are cancelled.
4. **Stale object** — selected object disappears before execution; action is rejected and replanned.
5. **Board switch** — UI context changes using canonical Board semantics, without granting the wrong Board speech authority.
6. **Browser display** — Jarvis references a URL/page; Tool Brain opens/focuses/scrolls it as presentation, without performing independent research.
7. **Invalid choice attack/test** — decision output supplies an ID not in the current choice set; runtime refuses it.
8. **Decision model outage** — UI remains safe and observable without uncontrolled fallback execution.

## Performance / responsiveness

Instrument at least:

- trigger -> Tool Brain start;
- decision inference duration;
- decision -> queued action;
- trigger condition -> execution start;
- tool execution duration;
- invalidation -> replan start.

Do not hide latency behind a fixed multi-second tick. Critical events must use the event-driven path. Establish a measured product latency budget during Slice 10 using representative hardware/model configuration rather than inventing a number in planning.

## Human validation

Human checks occur only after all reasonable machine checks pass. The final validation focuses on perceived synchronization and debuggability, not on discovering basic functional defects that automation should catch.
