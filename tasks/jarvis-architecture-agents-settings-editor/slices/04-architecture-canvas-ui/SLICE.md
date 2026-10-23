# Slice 04 - Architecture canvas UI

## Goal

Build the neon/glass 2D Architecture tab as a real graph editor surface against an adapter, with semantic nodes/ports/connections and no decorative hub logic.

## Context

The user approved `references/architecture-ui-reference.png` but explicitly corrected earlier mockups: links must represent real runtime relations, audio input/output must be visible, and a separate Brains tab is forbidden.

## Canonical Concepts

- `docs/06-functional-spec.md` sections A/B/G
- `docs/07-reference-interpretation.md`

## Scope

### In Scope

- Architecture tab shell/module.
- 2D node canvas with draggable layout.
- Nodes/endpoints from adapter snapshot.
- Directional typed connections and labels.
- Distinct locked/active/disabled/removable states using line style + icon/label, not color alone.
- Connection selection/inspection and impact text.
- Toggle/create/remove interactions against adapter.
- Keyboard/touch alternative to right click.
- Context action hook that opens Slice 05 popup component.
- Compact legend/status support that never replaces the graph.
- Loading/empty/error/revision-conflict states.

### Out of Scope

- No hard-coded runtime topology.
- No brain config fields inside this module.
- No separate Brains tab.
- No shared `control_center.html` final registration; Slice 07 owns it.

## Dependencies

### Hard `depends_on`

None after Slice 00 READY.

### Soft `requires`

- Slice 01:
  - need: graph snapshot/mutation payloads and error codes.
  - fallback: fixture + adapter matching `docs/02-architecture.md`.
  - integration_required_before: Slice 07 completion.
  - mismatch_policy: adapt transport layer/component props; do not fork graph semantics.
- Slice 05:
  - need: popup open/select interface.
  - fallback: emit `configure-brain(brain_id)` event.
  - integration_required_before: Slice 07 UI convergence.
  - mismatch_policy: preserve one contextual launch path.

### Can Start With

Approved reference image and documented fixture contract.

### Produces

- standalone Architecture UI module/component;
- graph adapter interface;
- fixture/demo state for local review;
- context/configure event contract.

### Integration Checkpoint

Slice 07 mounts the module and swaps fixtures for live routes.

## Implementation Steps

1. Build canvas/grid/layout shell in the approved visual language.
2. Render nodes/endpoints from snapshot.
3. Render semantic edges/labels/mutability states.
4. Implement node drag as layout-only persistence.
5. Implement connection inspect/toggle/create/remove UI through adapter.
6. Implement context menu plus keyboard/touch equivalent.
7. Add legend, errors and authoritative refresh behavior.
8. Verify no hard-coded future brain set.

## Files Likely Touched

Prefer a new dedicated architecture settings JS/CSS module and fixture module. Avoid shared Settings shell hot files until Slice 07.

## Architecture Constraints

Frontend is a projection/controller of runtime truth. It never invents success or persistent topology.

## Automated Validation

Frontend build/static checks, component smoke with fixture states, keyboard focus smoke, and targeted browser runtime check if available. **Do not launch the unit test suite at this Slice boundary.**

## Acceptance Criteria

- Reference visual direction is recognizable without sacrificing readability.
- Diagram is not a central Jarvis constellation.
- Nodes are draggable without changing topology.
- Locked/active/disabled connections are understandable without color alone.
- Connection actions invoke adapter and reconcile authoritative response.
- Right click and keyboard/touch both expose brain actions.

## Documentation Updates

Document architecture UI adapter/event contract if repository frontend docs require it.

## Handoff Notes

Requires `/caveman`, `/coding-guideline`, `/impeccable`; use Claude Work Agent for frontend implementation/review where supported.
