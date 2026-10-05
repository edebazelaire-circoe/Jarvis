# Slice 09 — Integrate prepared/on-demand visuals with Scene & Prefab runtime

## Goal

Make Presentation visual results reusable, referenceable scene resources using the canonical Scene/Prefab foundation.

## Context

The scene/window/prefab task owns reusable visual definitions, runtime instances, lifecycle and Jarvis-facing operations. Presentation should exploit prepared resources instead of regenerating ad hoc UI each time.

## Canonical Concepts

Prefab definition, prefab instance, scene object, prepared resource reference, visual data payload, instance lifecycle.

## Scope

### In Scope

- Freshness-audit the Scene/Prefab public contract.
- Represent Presentation-prepared visuals using canonical prefab/scene references where appropriate.
- Support on-demand creation/population from research/data results.
- Register reusable prepared resource handles in the Presentation working set.
- Allow Tool Brain to manifest/focus/hide/replace the resource through canonical scene operations.
- Preserve data/provenance references used to build the visual.

### Out of Scope

- Reimplementing prefab registry/runtime.
- Presentation-specific renderer technology.
- Direct DOM manipulation by Presentation policy.

## Dependencies

- `05-presentation-working-set`
- `08-tool-brain-integration`
- External: `jarvis-scene-window-prefab-foundation` public runtime contract available/stable enough for integration.

## Implementation Steps

1. Audit the current scene/prefab API.
2. Define minimal prepared-visual adapter/resource reference.
3. Integrate creation/population/reuse lifecycle.
4. Ensure invalid/stale resource references fail cleanly and can be regenerated.
5. Add integration tests with representative checklist/table/chart/report-style visuals if supported by the foundation.

## Files Likely Touched

Presentation resource adapter, scene/prefab integration glue, tests, docs.

## Architecture Constraints

Scene/runtime owns placement/lifecycle; prefab runtime owns rendering; Presentation owns semantic preparation only.

## Automated Validation

Contract tests for create/reuse/stale reference behavior, runtime validation of multiple representative visual outputs, no direct DOM path from Presentation.

## Acceptance Criteria

A visual prepared from ambient/background work can be reused instantly when requested and manifested through Tool Brain + canonical scene/prefab APIs.

## Documentation Updates

Document resource-reference lifecycle and ownership.

## Handoff Notes

Frontend/runtime coding Slice: load `/caveman`, `/coding-guideline`, `/impeccable`; use Claude when supported.
