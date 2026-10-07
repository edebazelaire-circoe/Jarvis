# 01 — Decision Log

## D01 — Separate UI-tool decision responsibility from Jarvis reasoning
**Status:** Locked.

A dedicated Tool Brain owns UI-tool decision-making and timing so Jarvis can focus on reasoning, context, speech and non-UI tools.

## D02 — V1 delegates UI tools only
**Status:** Locked.

Non-UI tools remain directly available to Jarvis. Broader tool delegation is a future extension.

## D03 — Jarvis knows Tool Brain exists
**Status:** Locked.

Jarvis receives an explicit architectural/capability description. It must not claim delegated UI capabilities are unavailable simply because another component executes them.

## D04 — Intent, not low-level commands
**Status:** Locked.

Jarvis publishes structured UI-relevant intentions/relevance hints. Tool Brain chooses concrete UI actions.

## D05 — Structured communication, no agent-to-agent prose protocol
**Status:** Locked.

The two brains coordinate through typed events/state, not natural-language commands.

## D06 — Speech future is generated future, not prediction
**Status:** Locked.

When Jarvis has already generated a long answer, Tool Brain may receive remaining chunks plus the current playback/chunk position so it can prepare actions ahead of speech.

## D07 — Hybrid wakeups
**Status:** Locked.

Important events cause immediate decisions; a periodic tick exists only as a fallback/safety mechanism.

## D08 — Tool Brain owns a mutable action queue
**Status:** Locked.

It may add, cancel, replace, reprioritize and reschedule queued UI actions, including actions gated on speech/event progress.

## D09 — Stale action rejection and immediate replan
**Status:** Locked.

The runtime validates preconditions against authoritative current state. Invalid actions do not force execution; they generate an invalidation result and immediate Tool Brain wakeup with fresh state.

## D10 — Near-total autonomy for reversible UI actions
**Status:** Locked.

Tool Brain may independently operate reversible UI state. Destructive or irreversible operations require explicit mechanical guardrails.

## D11 — Stable IDs for manipulable objects
**Status:** Locked.

An object keeps the same runtime identity for its lifetime. Model-visible labels may change without changing identity.

## D12 — Choice-constrained parameters
**Status:** Locked.

Where legal values are knowable, tool parameters expose runtime-generated choices rather than accepting unconstrained model-generated identifiers.

## D13 — Tool metadata is a first-class contract
**Status:** Locked.

Descriptions, parameter meaning, valid choices, human labels, current state and compatibility constraints must be available to Tool Brain through the canonical catalog/introspection path.

## D14 — Compact perception plus targeted inspection
**Status:** Locked.

Each decision receives a relevant condensed snapshot. Tool Brain can inspect a selected ID for deeper metadata rather than receiving the whole world every time.

## D15 — Perception represents the user's actual view
**Status:** Locked.

It includes active Board and scene state and, when relevant, browser/window/process state needed to interpret UI requests.

## D16 — Board switching is a Tool Brain UI operation
**Status:** Locked.

Reuse canonical Board runtime switching semantics; do not implement a second Board state machine.

## D17 — Browser actions are presentation/navigation in V1
**Status:** Locked.

Open/focus URL/window, scroll, zoom and navigation may be UI tools. Independent web research remains Jarvis-owned.

## D18 — Extend the existing observability timeline
**Status:** Locked.

Tool Brain events/tool calls/queue activity are added to the existing canonical conversation timeline rather than creating a new transcription system.

## D19 — Model choice remains pluggable
**Status:** Locked as a non-decision.

No specific Laya/Stanford/other model is selected. The runtime must permit model replacement and future training/evaluation.

## D20 — Scene/prefab/MCP contracts are reused
**Status:** Locked compatibility constraint.

This task integrates with existing and pending Jarvis scene/prefab/MCP contracts; it does not fork them.

## Provisional implementation recommendations

These are not user-locked product decisions and Slice 00 may adjust them to repository reality:

- Keep queued UI actions ephemeral in V1 and invalidate them aggressively on authority/session changes rather than persisting speculative actions across restarts.
- Introduce shadow/observe-only mode before enabling autonomous mutations.
- Prefer speech/event triggers over absolute wall-clock delays when an equivalent deterministic trigger exists.
