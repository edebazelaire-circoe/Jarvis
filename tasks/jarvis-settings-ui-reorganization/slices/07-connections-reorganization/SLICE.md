# Slice 07 - Connections reorganization

> Authored by agent 0 during Slice 00: the Drive publication of this handoff contained an empty folder for this Slice. Content is derived strictly from `docs/02`, `docs/03`, `docs/04`, `docs/06` and `docs/07`; no new product decision is introduced.

## Goal

Turn `API Keys` into the provider-centric `Connexions` category.

## Context

`tabKeys()` in `control_center.html` lists saved credentials by provider, the active binding, a masked hint, add/delete and environment fallback. Values are never read back by the page.

## Canonical Concepts

- `docs/07-target-settings-map.md` section 5
- credential store contract (server side) and its tests

## Scope

### In Scope

- One card per provider/service: identity, configured/not-configured status, active binding, add/replace/delete, environment fallback indication.
- A short contextual note of which Jarvis capability uses the provider, sourced from server metadata when available; otherwise omitted rather than hard-coded.
- Register under `connections` with Slice 02 primitives.

### Out of Scope

- No OAuth-style semantics for API-key providers.
- No change to credential storage, APIs or masking.

## Dependencies

- `02-settings-shell-visual-redesign`

## Implementation Steps

1. Freshness-check credential API and `tabKeys()`.
2. Re-render as provider cards via the registry.
3. Keep immediate-save behavior and status/error live regions.
4. Update tests.

## Files Likely Touched

- `jarvis/runtime/control_center.html`
- credential/keys UI tests

## Architecture Constraints

- Never reveal a secret; no provider list copied into JS if the server already describes it.

## Automated Validation

- No response or DOM contains a full credential value.
- Add/delete/bind requests unchanged.
- Environment fallback still displayed.

## Acceptance Criteria

- No top-level `API Keys` tab; `Connexions` covers every credential action.

## Documentation Updates

`docs/settings/INDEX.md`: Connexions destination.

## Handoff Notes

Small Slice; may run in parallel with 05/06 only if the files touched do not overlap (they share `control_center.html`: serialize by default).
