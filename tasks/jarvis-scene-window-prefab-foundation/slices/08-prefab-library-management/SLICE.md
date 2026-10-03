# Slice 08 — Shared Prefab Library Management

## Goal

Provide a clear management surface for the shared prefab library so humans and Jarvis can understand what exists, where it came from, and what may safely be changed.

## Context

The user wants the library maintained for everyone to reuse. It must make base/system definitions distinct from custom/forked ones and support preview/inspection rather than becoming an opaque folder of code.

## Canonical Concepts

Shared prefab library, base prefab, fork/custom prefab, provenance, preview.

## Scope

### In Scope

- Browse/search/filter prefab definitions.
- Preview with defaults/sample data.
- Inspect inputs/events/version/provenance/usage where available.
- Distinguish base/system vs custom/fork visually and semantically.
- Save-as-new flow.
- Explicit base-edit affordance with strong wording/gate.
- Refresh/update after an agent creates a prefab.

### Out of Scope

- Global product settings unrelated to prefabs.
- Presentation-board settings.

## Dependencies

- `07-agent-prefab-operations`

## Implementation Steps

1. Integrate with the existing Jarvis settings/library navigation rather than adding a parallel admin shell.
2. Use the canonical catalog as the only source of prefab identities.
3. Build preview from validated runtime defaults.
4. Surface provenance/version/parent relationships.
5. Add explicit actions for instantiate/test/fork/save-as-new; protect base edit.
6. Ensure agent-created prefabs appear without manual page code changes.

## Files Likely Touched

Prefab/library frontend, shared settings/navigation integration, catalog endpoints, browser/visual tests.

## Architecture Constraints

The UI renders backend/catalog truth; it does not author a second hand-maintained prefab list.

## Automated Validation

- Search/filter/preview tests.
- Dynamic new-prefab visibility.
- Base/custom action gating.
- Browser interaction and visual regression coverage.

## Acceptance Criteria

- A user can understand available prefabs and their provenance.
- A newly saved prefab appears through catalog refresh/discovery.
- Base prefab modification is visibly distinct from instance/fork editing.

## Documentation Updates

Document library management workflow and ownership.

## Handoff Notes

Use `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude agent when supported.

## Slice 00 contract (binding)

Create / touch:
- `jarvis/runtime/control_center_prefabs.js` (`window.JarvisPrefabLibrary`; pure parts exported for node: filtering, sorting, provenance chain, badge model).
- `control_center.html`: dock button `PFB` (`id="openPrefabs"`, aria like `openMcpInspector`), dialog `.pfb`, marker `/*__CONTROL_CENTER_PREFABS_JS__*/`, z-index rank as `.mcpi`.
- `control_center.py` splice; `jarvis/runtime/prefab_relay.py`: `POST /api/prefabs` (fork/save-as-new, actor user).
- UI per 06 D-UI: list (search, family, class filter base/custom, badges base / base-edited / fork / custom / revision), detail (inputs tree, events with class, versions, provenance chain with `derived_from` links, base-edit history with quoted request), preview (host `preview` mode with sample, events shown in a local log), "Place on scene" (scene command as user with `prefab` block and `sample` data), "Fork as new prefab" form (id, title, description; validation errors from Core shown inline). Refresh on dialog open and after save; agent-created prefabs appear with no page change.
- `docs/ARCHITECTURE.md` quotes `POST /api/prefabs`; `docs/OPERATIONS.md` short "Prefab library" usage section; `docs/prefabs.md`.

Acceptance:
- Node: filter/search/provenance model tests; static test: no `innerHTML` in `control_center_prefabs.js`.
- Relay test: fork from UI → origin `fork`, actor `user`; `jarvis.*` id in the form → `base_protected` shown.
- Browser: open PFB, search "check", preview the checklist, place on scene, fork as `team.checklist-red`, see it listed with fork badge and parent link; a prefab saved through MCP appears after reopen; keyboard and screen-reader names; both themes.

Depends on: 07.
QA: qa-verification + code-review + runtime-validation. Frontend: /impeccable, Claude agent. Human: HV-PREFAB-LIBRARY-01.
