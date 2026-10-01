# Slice 00 - Project Manager readiness gate

## Goal

You are the Project Manager. Execute this Slice yourself. Blind-audit the **live** repository before relying on planning conclusions, reconcile the handoff with current `main`, resolve canonical owners and valid Workspace Task Types, then emit exactly one readiness state: `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, or `HUMAN_DECISION_REQUIRED`. Do not edit product code.

## Context

The handoff was prepared from `main` SHA `96a93963a6faf0723be5839e89545e64546ccdb7` on 2026-10-01. Jarvis is active and the current Board/Session, audio, capture, data-root, MCP and Control Center implementations may have moved.

## Blind audit protocol

Before reading `docs/01-decision-log.md`, `docs/02-architecture.md` or implementation conclusions:

1. Inspect current Session lifecycle and startup behavior.
2. Inspect current persistence/migration ownership and local data root.
3. Inspect current microphone ownership, ambient transcription and any new recording code.
4. Inspect generic/scene/desktop capture capabilities and retention.
5. Inspect current conversation-event vs runtime-journal boundaries.
6. Inspect current MCP/API tool ownership/catalog.
7. Inspect the left floating Control Center toolbar/palette and scene safe-area rules.
8. Inspect current Workspace Task Type vocabulary and agent routing rules.
9. Record factual findings with exact files/symbols/current SHA.

Only then reconcile with this handoff.

## Locked product intent to reconcile

- Session persists across runtime restart and closes only on explicit new-session.
- One active free-form Context; dormant Contexts are not implicitly mutated.
- New Context/Capture design is not Board-scoped; wholesale Board removal is out of scope.
- Capture tools are independent of interaction modes and Brain lifecycle.
- Explicit raw audio is durable and canonical transcript cannot depend on lossy `drop_oldest` queues.
- Generic desktop screenshot and screen recording are in scope; camera is not.
- Artifact management is structured; Context memory remains free-form.
- Recording controls use the existing floating left toolbar/palette, but are not Bare Hands radio tools.

## Scope

### In scope

Reconcile contracts, split/merge/reorder Slices if current code requires it, resolve migration strategy and capture-process boundary, assign valid Task Types, validate dependency graph and Human-check IDs, and update this handoff if facts changed.

### Out of scope

Any product implementation or opportunistic refactor.

## Acceptance criteria

- Blind-audit evidence is recorded before handoff reconciliation.
- Current owners and conflicting contracts are named precisely.
- Task Types use current Workspace vocabulary, with no invented/default values.
- Every Slice dependency and Human-check ID is valid/unique.
- Capture continuity guarantee states the exact process boundary it can survive.
- Board compatibility impact of changing Session restart semantics is explicitly resolved.
- One readiness state is recorded.
- No implementation is dispatched unless readiness is `READY`.

## QA / handoff

Validate planning consistency locally. Before every later Slice dispatch, repeat a targeted freshness check. Every coding Slice loads `/caveman` and `/coding-guideline`; frontend work also loads `/impeccable` and uses Claude routing when supported.
