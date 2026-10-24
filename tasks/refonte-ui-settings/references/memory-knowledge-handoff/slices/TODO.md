# Slice Graph / TODO

Slice order is for identification/readability only. It is **not a serial execution mandate**.

## Readiness gate

- `00-project-manager` — no dependencies. Must reach `READY` before implementation dispatch.

## Initial parallel ready set after READY

| Slice | Hard depends_on | Main output |
| --- | --- | --- |
| 01 Memory preferences UI | none | User-facing recall/semantic/consolidation surface |
| 02 Knowledge/loadouts UI | none | Source status + editable agent knowledge access |
| 03 Memory Center UI | none | Redesigned dedicated inspection/decision workspace |
| 04 Memory advanced diagnostics | none | Advanced destination for raw tuning/Tencent/health details |

## Convergence

- `05-settings-integration-migration` depends on **01, 02, 03, 04**. It owns shared navigation/mount wiring, legacy Memory-tab cleanup and single-home guarantees.
- `06-final-integration-e2e-qa` depends on **05** and owns the full unit + integration + E2E campaign.

## Main hard chain

`00 -> {01,02,03,04} -> 05 -> 06`

## External coordination

Coordinate with `jarvis-settings-ui-reorganization`: this handoff supersedes only that task's Memory & Knowledge Slice, not its shell or unrelated categories.
