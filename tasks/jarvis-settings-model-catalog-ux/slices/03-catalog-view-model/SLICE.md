# Slice 03 — Create a sourced comparison view model for sub-agent and voice catalogs

## Goal

Extend live model/CLI discovery with trustworthy comparison metadata and explicit availability states for reusable catalog UIs.

## Context

`model_catalog.py` already fetches live Anthropic/OpenAI/Google model lists and roles; `cli_catalog.py` covers agent CLIs. Provider APIs do not necessarily supply prices or qualitative recommendations.

## Canonical Concepts

- stable catalog item key
- provider/model/agent identity
- usable/loaded vs available-not-configured vs requestable/known state
- capabilities/roles
- cost metadata with source/freshness
- latency/quality/recommendation tags with provenance
- install/add-model request capability

## Scope

### In Scope

- Define and implement merged view model.
- Keep live availability authoritative.
- Add metadata overlays only with provenance/freshness/unknown values.
- Define request/add workflow boundary rather than fake availability.

### Out of Scope

- Hard-coded active model allowlist.
- Unsourced benchmark league tables.

## Dependencies

01

## Implementation Steps

1. Audit fields from `ModelCatalog`, CLI catalog and routing candidates.
2. Define availability-state semantics from actual runtime/credentials/install state.
3. Add optional metadata registry/provider adapters with `source` and `updated_at`.
4. Represent unknown price/capability explicitly.
5. Expose unified APIs filtered by role (text/realtime/transcription/speech/sub-agent).
6. Add tests for stale/live/unknown/missing credentials.

## Files Likely Touched

- `jarvis/runtime/model_catalog.py`
- `jarvis/runtime/cli_catalog.py`
- `jarvis/runtime/agent_routing.py`
- `jarvis/runtime/control_center.py`
- `config/catalog metadata if justified`
- `tests/*catalog*`

## Architecture Constraints

- Never make stale curated metadata override live provider availability.
- A model that cannot be invoked must not render as usable.

## Automated Validation

- Catalog merge tests.
- Availability-state matrix.
- Stale metadata/provenance tests.
- Missing-key/CLI tests.

## Acceptance Criteria

- Catalog API can explain why an item is or is not usable.
- Every non-live comparison claim has provenance/freshness or is unknown.
- Same view model can feed text/sub-agent and voice catalogs.

## Documentation Updates

Document catalog field semantics, sources, freshness and unknown-state policy.

## Handoff Notes

Keep implementation evidence and material planning corrections in `LOG.md`. Current-Slice regressions are blocking.
