# Implementation order

The Project Manager owns ordering, readiness checks, dependency refresh, delegation and QA arbitration. Start with Slice 00 and do not delegate implementation until it returns `READY`.

| Order | Slice | Purpose | Depends on |
| --- | --- | --- | --- |
| 00 | `00-project-manager` | blind audit, reconcile plan, resolve Task Type, gate execution | none |
| 01 | `01-shell-contract-and-design-system` | canonical UI shell/layer/design contract | 00 |
| 02 | `02-orbital-tool-wheel` | retractable radial wheel + Mouse/keyboard/Bare Hands reveal | 01 |
| 03 | `03-selection-input-arbitration` | Mouse/Bare Hands selector + intelligent takeover + new icon | 02 |
| 04 | `04-capture-wheel-migration` | migrate Audio/Video/Screenshot controls without new state owner | 02,03 |
| 05 | `05-screenshot-preview` | non-blocking screenshot preview and quick actions | 04 |
| 06 | `06-bottom-status-and-hidden-toggle` | notification center, recording indicators, eye toggle, remove F9 capsule | 01,04 |
| 07 | `07-right-active-workspace-rail` | rich right-side presentation/workspace rail | 01 |
| 08 | `08-global-chrome-and-context-zone` | simplify top/right chrome; preserve mode + Board access | 01,06,07 |
| 09 | `09-integration-responsive-accessibility` | layering, Studio/Variantes, responsive, keyboard/a11y, visual polish | 03-08 |
| 10 | `10-release-and-human-acceptance` | full QA evidence, documentation closeout, human acceptance | 09 |

## Parallelization

After Slice 01, Slice 02 and the data/model preparation portion of Slice 07 may run in parallel if their files and layer contracts do not overlap. Slice 08 should wait until the main replacement surfaces are stable; otherwise it will move controls twice.

## Freshness gate before every dispatch

PM re-checks:

- current HEAD and conflicts with active PRs/tasks;
- canonical docs referenced by the Slice;
- source files likely touched;
- current Workspace Task Type vocabulary;
- neighboring task folders in `task/current` and `task/to-do`;
- z-index/layer contract after any previous merged slice.
