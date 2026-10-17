# Slice execution order

Do not skip Slice 00. The current repository already contains merged versions of earlier Board/wheel/memory work, and the fixed Board-type requirement changes a canonical contract.

Revised by Slice 00 on 2026-10-17 against HEAD `2fb66040` (see `../docs/08-readiness-audit.md`): Slice 01 split into 01a/01b, Slice 05 no longer waits for the wheel, Slice 06 serialized after Slice 04.

| Slice | Goal | Depends on |
| --- | --- | --- |
| 00 | Project Manager readiness, blind audit, task-type resolution, conflict reconciliation | — |
| 01a (`01-board-type-contract-migration`) | Board type authoritative/immutable (`assistant\|presentation\|meeting`), v9 data migration of `work_boards.data`, Core derives the live mode from the active Board's type | 00 |
| 01b (`01b-derived-interaction-mode`) | Retire every user/agent mode writer (CC route + replay, global key, `settings_set`, prompt, Core `POST` restricted to Studio runs) | 01a |
| 02 | Remove obsolete chrome (top-left Board + `.state`, mode HUD, eye) and deliver the bottom-left Board card carrying the Voice presence report | 01b |
| 03 | Redesign orbital wheel graphics + IA to JARVIS/Sélection/Dossier/Capture/Paramètres | 02 |
| 04 | Wire JARVIS (status-only) + Capture submenu, move `#recIndicators` top-left, Paramètres, fold `SET` into « Plus d’outils » | 03 |
| 05 | Define/implement Dossier projection and the five missing semantic operations | 01a |
| 06 | Wire scene selection actions: ranger, masquer, representations, show hidden (re-expose the eye machinery), remove from Board | 04, 05 |
| 07 | Build full-screen human Dossier UI + manual/Jarvis-guided navigation | 05, 06 |
| 08 | Cross-cutting integration, accessibility, agent traces, regression and documentation closure | 04, 07 |
| 09 | Final human acceptance and release/rollback evidence (incl. still-valid orbital-ui checks) | 08 |

Parallelism: Slice 05 may run beside 01b-04 (backend only, no shared code file); keep at most 3 agents on this machine and one writer per worktree. Slices 02, 03, 04, 06 all edit `control_center.html` and the shell registry: strictly sequential. Slice 08 integrates all streams.

Interim states accepted inside the task branch (never merged half-way): between Slice 02 and Slice 06 the hidden-object eye is gone and hidden objects can be re-shown only by Jarvis (scene tools, `set_visibility`), not from the page; between Slice 02 and Slice 04 the wake-key hint is not visible on screen (kept accessible) and the recording chips stay in the status centre.
