# Documentation levels

| Concept | Current evidence | Current level | Required for V1.2 | Gap / owner |
| --- | --- | ---: | ---: | --- |
| Board/Session/Board memory/Dossier | `docs/boards.md` + domain/store/API/MCP/tests | 3 | 3 | Reuse; do not fork |
| Organic agent roles | `subagent_roles.py`, role routing, tests/docs | 3 | 3 | Reuse; Presentation policy changes exposure only |
| Work Methods / agent relations | `work_methods.py`, relations runtime/MCP | 3 | 3 | Reuse; enrich research heuristics if needed |
| Presentation product brain scope | Parent V1 planning + generic current brain | 1–2 | 3 | Slice 01: canonical policy + enforcement + conformance tests |
| Board-as-project continuity convention | Board memory exists; no Presentation-specific semantic contract | 1 | 3 | Slice 02: `summary.md` semantics + resume behavior/tests |
| Research reuse/freshness | Some “prefer recent sources” heuristics, no reuse/freshness contract | 1 | 3 | Slice 03 |
| Durable research project documents | Board memory/Dossier are reusable, no standard research-output contract | 1 | 3 | Slice 04 |
| Voice Off/Sleep/Active product lifecycle | Voice/mode/wake pieces exist; product launch contract requires audit | 1–2 | 3 | Slice 05 |
| Novice product shell with full debug Settings retained | Settings and Presentation UI exist; amendment changes disclosure policy | 1 | 3 | Slice 06 |
| Bug-report diagnostic bundle | Existing diagnostics/logs; no end-user bundle/send contract found in audit | 0–1 | 3 | Slice 07 |
| Cross-platform logical data roots | Dev data root + Windows V1 target exist; mac installed identity not canonical | 1 | 3 | Slice 08 coordinated with parent storage/packaging work |
| macOS package/build validation | no current release pipeline established in parent audit | 0–1 | 3 | Slice 08 + real-device acceptance |

A documentation-level gap becomes a prerequisite behavior/contract Slice; do not paper over it with prompt text alone when hard enforcement or persistence is required.