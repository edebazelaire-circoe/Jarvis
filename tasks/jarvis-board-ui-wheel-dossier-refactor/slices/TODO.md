# Slice execution order

Do not skip Slice 00. The current repository already contains merged versions of earlier Board/wheel/memory work, and the fixed Board-type requirement changes a canonical contract.

| Slice | Goal | Depends on |
| --- | --- | --- |
| 00 | Project Manager readiness, blind audit, task-type resolution, conflict reconciliation | — |
| 01 | Make Board type authoritative/immutable; migrate/retire independent user interaction mode | 00 |
| 02 | Remove obsolete chrome and deliver bottom-left Board switcher/create flow | 01 |
| 03 | Redesign orbital wheel graphics + IA to JARVIS/Sélection/Dossier/Capture/Paramètres | 02 |
| 04 | Wire canonical JARVIS runtime + Capture submenu and transient recording indicators | 03 |
| 05 | Define/implement Dossier projection and semantic durability/presentation operations | 01, 03 |
| 06 | Wire scene selection actions: ranger, masquer, representations, show hidden, remove from Board | 05 |
| 07 | Build full-screen human Dossier UI + manual/Jarvis-guided navigation | 05, 06 |
| 08 | Cross-cutting integration, accessibility, agent traces, regression and documentation closure | 04, 07 |
| 09 | Final human acceptance and release/rollback evidence | 08 |

Parallelism: after Slice 03, Slice 04 and Slice 05 may run in parallel only if the Project Manager confirms they do not touch the same shell/module files without coordination. Slice 06 waits for Dossier semantics. Slice 08 integrates all streams.
