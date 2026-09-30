# Slice 00 - Project Manager readiness gate

## Goal
You are the Project Manager. Execute this Slice yourself. Blind-audit the live repository, reconcile this handoff, resolve canonical owners and valid Workspace Task Types, then emit READY, CONTEXT_REWORK_REQUIRED, CONFLICT, or HUMAN_DECISION_REQUIRED. Do not edit product code.

## Context
The handoff was planned against main SHA 202333db5c5dea31258125a0ef296314d9b82b34 and current Jarvis Drive handoffs. The repository is active.

## Canonical Concepts
Board; Session; BoardConversationBinding; deterministic runtime; Board Brain lifecycle; single speech authority; Board-attributed notifications; Board-scoped interaction mode; jarvis-console parity.

## Scope
### In Scope
Audit Core/Brain ownership, Live/Voice session lifecycle, Control Center restart/new conversation, persistence, interaction mode, background alerts, MCP registration/catalog, top-right UI controls, and current Task Type vocabulary. Repair planning as needed.
### Out of Scope
Product implementation changes.

## Dependencies
None.

## Implementation Steps
Perform the blind audit before relying on this handoff; reconcile findings; assign valid Task Types; validate dependencies and Human-check IDs; gate dispatch on READY only. Perform a targeted freshness check before every later Slice dispatch.

## Files Likely Touched
Planning handoff files only.

## Architecture Constraints
No global intermediary LLM Brain.

## Automated Validation
Validate dependency graph, Task Types, Slice IDs, Human-check IDs and canonical references.

## Acceptance Criteria
Blind audit recorded; current owners identified; valid Task Types assigned; one readiness state recorded; no implementation dispatched below READY.

## Documentation Updates
Amend handoff docs if live repository differs.

## Handoff Notes
Every coding Slice loads /caveman and /coding-guideline; frontend also loads /impeccable and uses Claude routing when supported.
