# Slice 05 - Memory and knowledge reorganization

> Authored by agent 0 during Slice 00: the Drive publication of this handoff contained an empty folder for this Slice. Content is derived strictly from `docs/02`, `docs/03`, `docs/04`, `docs/06` and `docs/07`; no new product decision is introduced.

## Goal

Rehome the current `Mémoire` tab as the `Memoire & connaissances` category with task-oriented sections, and move detailed memory-leg diagnostics to Advanced.

## Context

`control_center_memory_settings.js` already renders server-described sections (`memory_settings.py`) into `#memorySettingsMount`, with its own save button and restart-required notices. The Memory Center (`control_center_memory.js`) is a separate surface with its own internal tabs; it is opened from Settings, not redesigned here.

## Canonical Concepts

- `docs/settings/memory.md`
- `docs/07-target-settings-map.md` section 3
- Slice 01 registry contract, Slice 02 shell primitives

## Scope

### In Scope

- Register sections Recall, Semantic retrieval, Consolidation, Knowledge sources, Memory Center under `memory_knowledge`.
- Keep the Tencent sidecar with Knowledge sources (it is an external retrieval source).
- Keep the per-agent knowledge/loadout summary as concise read-only context.
- Register a Memory diagnostics section under `advanced_diagnostics` for memory-leg state/degradation detail; the ordinary page keeps a short status line plus a deep link.
- Apply Slice 02 shell primitives to the rendered fields.

### Out of Scope

- Do not change `memory_settings.py`, env/file/default precedence or save payloads.
- Do not redesign the Memory Center.

## Dependencies

- `02-settings-shell-visual-redesign`

## Implementation Steps

1. Freshness-check `memory_settings.py`, `control_center_memory_settings.js` and their tests.
2. Map every server-described memory field to exactly one section.
3. Split rendering so the module mounts per section through the registry, preserving its controller lifecycle and dirty/save behavior.
4. Move memory-leg diagnostics to the Advanced section and leave a deep link.
5. Update tests.

## Files Likely Touched

- `jarvis/runtime/control_center_memory_settings.js`
- `jarvis/runtime/control_center.html`
- `tests/unit/test_control_center_memory_settings_js.py`
- `docs/settings/memory.md`

## Architecture Constraints

- Server-described schema stays authoritative; no field list copied into JS.
- One editable home per field.

## Automated Validation

- Every memory field renders in exactly one section.
- Save payload unchanged for unchanged fields; unknown fields survive unrelated saves.
- Restart-required notices still shown.
- Memory Center still opens from the category.

## Acceptance Criteria

- No top-level `Mémoire` tab remains; `Memoire & connaissances` holds every ordinary memory control.
- Detailed degradation lives under Advanced and is reachable by link.

## Documentation Updates

Update `docs/settings/memory.md` with the new destinations.

## Handoff Notes

Pure relocation: `agent-trace-analysis` is not required unless runtime recall behavior changes.
