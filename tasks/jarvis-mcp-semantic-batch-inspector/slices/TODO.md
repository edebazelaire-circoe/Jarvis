# Execution order
| Slice | Title | Depends on |
| --- | --- | --- |
| 00 | Project Manager readiness gate | — |
| 01 | Canonical semantic contracts | 00 |
| 02 | SceneSelection and canonical constellation | 01 |
| 03 | Atomic scene batch operations | 02 |
| 04 | Canonical MCP catalog and typed schemas | 01 |
| 05 | Semantic jarvis-display migration | 03, 04 |
| 06 | Control Center MCP catalog API | 04, 05 |
| 07 | Human MCP inspector UI | 06 |
| 08 | Integration, migration and release QA | 02–07 |


Before every Slice, perform a targeted freshness check of files/contracts it depends on and amend stale instructions before dispatch.