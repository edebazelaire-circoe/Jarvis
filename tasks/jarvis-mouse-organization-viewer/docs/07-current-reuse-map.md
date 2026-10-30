# 07 - Current Reuse Map

Planning-time map only. Slice 00 revalidates every item at current HEAD.

| Need | Existing source to reuse | Planning observation |
| --- | --- | --- |
| Multi-selection | `control_center_scene_page.js`, `scene-selection-batch` | Already implemented |
| Group drag | `control_center_scene_interact.js`, `translate_selection` | Already atomic |
| Edge-side resize math | `resizeBySides()` / `manipulateBox()` | Exists, currently used by Bare Hands |
| Mouse resize | `resizeBox()` + `.sc-grip` | Currently bottom-right only |
| Keyboard move/resize/menu | `keyIntent()` / scene page key handlers | Already implemented |
| Context-menu selection | `onContextMenu()` | Currently collapses multi-selection |
| Batch scene mutation | `scene_batch.py`, `SceneBatchReport` | Reuse semantics; arbitrary target boxes are the missing piece |
| True browser fullscreen | `surface_fullscreen.py`, `control_center_fullscreen.js` | Do not repurpose for viewer |
| Public live agent state | `work_state.py` | Status/activity/summary/progress/timestamps/counters |
| Durable mission context | mission history domain/routes/view | Objective/role/instances/relations |
| Produced content | scene/artifact relations and Board artifact links | Reuse canonical IDs/relations |
| Generic prefab/window rendering | active prefab foundation task | Consume; do not duplicate |
| Chat question ingress | active unified chat task / current brain ingress | Reuse for Ask fallback |

