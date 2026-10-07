# 05 - Documentation Levels

Planning-time estimates only. Slice 00/01 must replace these with evidence from the live repository.

| Concept | Planning-time level | Required level | Requirement |
| --- | ---: | ---: | --- |
| Interaction mode PRESENTATION | 3 | 3 | Reuse current canonical contract; no redesign |
| Presentation ambient lane / working set | 3 | 3 | Preserve authority/privacy and extend only through armed cue consumption |
| Scene / Prefab foundation | active external handoff, expected 2-3 | 3 | Consume canonical schema/runtime/tool API |
| Generic fullscreen borderless surface | unknown | 3 | Contract + implementation + restore tests |
| Presentation Artifact | 0 | 3 | Schema, persistence, validator, tests |
| Presentation scene metadata/control surface | 0-1 | 3 | Typed controls + semantic edit operations + conformance tests |
| Live edit / scene-local hot reload | 0 | 3 | Deterministic patch tiers + failure/rollback tests |
| Autosave / bounded undo | 0-1 | 3 | Atomic durable current state + bounded local history |
| ArtDirectionProfile | 0 | 3 | Structured contract + source provenance + authoring integration |
| PresentationScore | 0 | 3 | Multi-track contract + validators + runtime |
| Armed ambient cue authority | 0 | 3 | Explicit safety contract + trace tests |
| Playback runtime | 0 | 3 | State machine + role/recovery tests |
| Rehearsal workflow | 0 | 3 | User-visible runtime + state/recovery tests |
| Presentation variant graph | 0 | 3 | Persistence/model + operations + tests |
| Scene-local variants | 0 | 3 | Local model + preview/select/promote tests |
| Variant Explorer | 0 | 3 | Production UI + runtime validation |
| Variant comparison / semantic mix | 0 | 3 | Operation contract + UI + provenance tests |
| Template/prefab promotion | Scene foundation direction exists | 3 | Reuse shared authoring/promotion contract |
| Tool Brain UI intent seam | planned/unknown live status | 2-3 | Integrate if canonical; never duplicate |
| Agent presentation operations | 0-1 | 3 | Stable-ID tools + constrained choices + trace tests |

## Prerequisite rule

If Scene/Prefab or another required canonical concept is below Level 2 when this task starts, repair/finish that contract before dependent behavior. If an equivalent Level 3 contract already exists, remove redundant planned work instead of building a second system.
