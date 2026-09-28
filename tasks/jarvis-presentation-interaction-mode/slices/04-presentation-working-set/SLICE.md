# Slice 04 - Add Presentation session working set and transcript-tail contracts

## Goal
Create bounded ephemeral state that lets Presentation remember current topics/resources and resolve commands against freshest speech when enrichment lags.

## Context
This is not long-term memory. Ambient analysis can lag, so a separate fresh transcript-tail concept is required.

## Canonical Concepts
Presentation session working set; recent transcript tail; prepared resource lifecycle hot/warm/discardable; provenance/source binding.

## Scope
### In Scope
- Typed models for topics, entities, claims/facts, sources, prepared resources, unresolved items and attention items.
- Bounded in-memory/session-scoped store owned by Core or Core service.
- Explicit count/size/age budgets and deterministic eviction.
- Dedup/coalescing keys.
- Recent transcript tail with bounded time/text capacity and order/revision.
- Atomic snapshot combining committed working set + fresh tail for priority lane.
- Privacy rules: no raw audio persistence and no accidental trace widening.
### Out of Scope
Ambient producers, sub-agent execution, UI rendering, automatic long-term memory writes.

## Dependencies
Slices 01 and 02.

## Implementation Steps
1. Load `/caveman` and `/coding-guideline`.
2. Define types/bounds/provenance/eviction.
3. Implement store/snapshot API.
4. Add recent-tail append/revision independent from enrichment.
5. Reset/retire on Presentation session end/mode change.
6. Add unit tests for bounds, eviction, stale refs, dedupe, snapshots, privacy.

## Files Likely Touched
New domain/core presentation modules; state/service composition; tests; docs.

## Architecture Constraints
Session state is not canonical memory; raw audio never enters working set; prepared resources are explicit typed references, not executable payloads.

## Automated Validation
Focused unit tests plus Core state/brain context regressions.

## Acceptance Criteria
Working set deterministic/bounded; transcript tail independently fresh/bounded; one safe context snapshot; leaving Presentation follows documented lifecycle.

## Documentation Updates
Document ownership, fields, limits, lifecycle and privacy.

## Handoff Notes
Slice 06 writes observations/tail; Slices 08/10 consume snapshots/resources.
