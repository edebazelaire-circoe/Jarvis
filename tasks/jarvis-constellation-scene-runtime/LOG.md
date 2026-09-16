# Execution log

Reserved for implementation agents and the Project Manager to record durable execution notes, decisions discovered during implementation, and links to verification evidence. No implementation progress has been pre-populated by task creation.

## 2026-09-16 — Slice 00 readiness audit (agent 0 / Project Manager)

Readiness state: `HUMAN_DECISION_REQUIRED`.

### Lifecycle setup

- Handoff origin: remote (Drive `Jarvis/task/to-do/jarvis-constellation-scene-runtime`, folder id `1BvWTHGcoUh4sEtDnE5kYgXxo77O2K2Zy`). Unpacked verbatim under `tasks/jarvis-constellation-scene-runtime/`.
- `docs/workflows/AGENT_TASK_LIFECYCLE.md` referenced by the `handle-task` skill does not exist in this repository; the skill's inline rules were followed.
- No `dev` branch exists (only `main`). Branch `task/jarvis-constellation-scene-runtime` created from freshly fetched `origin/main` in lent worktree `sub-agents/jarvis-agent-01` (upstream unset to avoid pushes to `main`).
- Drive move `to-do` → `current` **not performed**: the `jarvis-drive` MCP exposes search/get/read/create/update/delete/share but no move/reparent. Pending Human decision.

### Live repository reconciliation

- Audited SHA: `7ed67bb09f4f9e1d63df793a23777904f6c63d13` = `origin/main` = handoff reviewed SHA. Handoff is fresh with respect to the repository.
- Blind audit performed with three read-only explorers (Control Center/transport, work/agent tracking, brain tools/MCP/persistence) without reading `tasks/`; conclusions and decisions made by the PM.
- Baseline (targeted, read-only): 16 files covering agent tasks, work ingress/state/view, background events, Control Center MVP/appearance/Barehands, documented routes, drive MCP, routing hook, debug console, work-state protocol, UI projection, Core recovery — **400 passed** in 17.7 s (`.venv` Python, `-W error::ResourceWarning`, cache disabled).

### Findings that shape the plan

- **Transport:** the Control Center browser polls full snapshots over HTTP (1 s). No WebSocket/SSE. Revision guard (`store_id`+`revision`) and long-poll (`/api/agent/notices`) precedents exist. → Decision 20 is realised as snapshot + long-poll patches, not a new socket stack.
- **Work truth:** Core `WorkStateStore` (memory-only, new `store_id` per start, one global revision, `core.work.updated` on `CoreEventBus` with evictable subscribers). Statuses include `blocked`. Items carry `parent_external_id`. → Scene projector lives in Core and subscribes to the bus with snapshot resync.
- **Producers:** only the Claude CLI brain's sub-tasks (via `TrackerWorkObserver` → `WorkIngressForwarder`) and Core jobs reach Core. Codex brain and back-brain job-internal sub-agents do not. No link from a job to Claude sub-agents it spawns.
- **Persistence:** durable Core state is `data/state/jarvis.sqlite3` with `schema_version=1` and no migration framework. → Scene uses a separate `scene.sqlite3` following the same adapter conventions.
- **Brain tools:** the continuous brain is the Claude Code CLI subprocess; no repo-wired MCP, the only in-repo MCP (`drive_mcp.py`) is registered manually at user scope. Core is reachable by bearer token from `runtime/core.token`. → Display MCP is a FastMCP stdio server wired through `--mcp-config` in `ClaudeLocalAgent`, excluded from `speculative_analysis`. The brain is launched with `--permission-mode bypassPermissions` (security-relevant for any new write-capable tool; SECURITY.md update required).
- **Stop capability:** individual Claude sub-agents cannot be stopped; Core jobs can be cancelled. → Slice 08 offers stop only for job-backed stars.
- **Rendering:** vanilla JS injected at markers, pure logic tested with node; two themes (ai-visualizer iframe default, Omega canvas); ad-hoc z-index values, no SVG overlay, no drag/resize. → Theme-independent scene container between face and chrome.
- **Screenshot:** no capability in the codebase. → Slice 09 starts with a PM-approved spike.
- **Docs gaps:** background badges and theme API undocumented; OPERATIONS.md mentions a stale "Config" settings tab.

### Planning repair

- Drive shipped Slices 01–11 as empty folders (no SLICE.md). The PM wrote contracts for all eleven from the decision log, grilling session and this audit, keeping order and dependencies from `slices/TODO.md`. No locked decision was altered.
- PM decisions recorded in contracts (reviewable by Human): scene owned by Core; separate SQLite file; long-poll transport; display tools target the Claude CLI brain only (legacy realtime tool catalog and V1 `board_present` out of scope); resolver placements committed as `placed_by=resolver`; projector runs regardless of the feature flag while renderer/MCP are gated; restart grace window before marking unobserved nodes interrupted.

### Workspace Task Type blocker

- No Workspace Task Type vocabulary found in the repository, the skills library (`C:\DevTools\skills-lib`), Drive handoff, or available tools. `local_agent`/`local_bash` are runtime event kinds; QA labels are requirements, not Task Types. Same finding as `jarvis-settings-model-catalog-ux` (2026-09-14), where the Human waived the gate.
- Per Slice 00, no implementation Slice has been dispatched.

### Missing input

- The "uploaded visual-direction document" named as aesthetic North Star is not in the handoff bundle. Blocks nothing before Slice 05; needed for Slice 05/08 design fidelity.

### Freshness check (run before every Slice dispatch)

1. `git fetch origin`; compare `origin/main` to the task branch base; if moved, `git diff --stat <base> origin/main` on the Slice's "Files Likely Touched" and rebase decision by PM.
2. Re-grep the Slice's anchors (e.g. `CORE_WORK_UPDATED`, `TrackerWorkObserver`, `WorkIngressForwarder`, `build_server` in `drive_mcp.py`, the `claude -p` argument list in `claude_local.py`, marker injection in `control_center.py`, `_SCHEMA_VERSION` in `sqlite_state.py`) and confirm the contract's Context still holds.
3. Re-run the Slice's listed baseline tests; a red baseline blocks dispatch.
4. Confirm previous Slices' contracts the Slice depends on are merged on the task branch and QA-approved.

### 2026-09-16 — Human decisions and READY

- Human waived the Workspace Task Type dispatch gate for this task (same as `jarvis-settings-model-catalog-ux`). `task_type` stays `null`; nothing is fabricated.
- Human chose to leave the Drive handoff in `to-do`; the local copy under `tasks/` is the working source. Queue placement is to be handled manually by the Human.
- Slice 00 state: **`READY`**.
- Freshness check before Slice 01: `origin/main` still `7ed67bb`; anchors `jarvis/domain/work_state.py` (`WorkStatus`, `ALLOWED_WORK_TRANSITIONS`, `apply_observation`) present; baseline green.

## 2026-09-16 — Slice 01 — implementation notes (agent 01)

Delivered `jarvis/domain/scene.py` (pure, imports only stdlib + `jarvis.domain.work_state` bounds), `tests/unit/test_scene_contracts.py`, `docs/scene-model.md` (linked from `docs/ARCHITECTURE.md` › Core contracts and `docs/state-model.md`).

Decisions taken inside the contract (reviewable by PM):

- **`pin`/`unpin` are user-only.** The contract says brain "may do everything except archive and cannot move/resize a pinned object". A brain `unpin` followed by `set_geometry` would bypass that protection, and a brain `pin` would write a flag named `pinned_by_user`. Matrix: runtime {upsert, patch, link, unlink, attach_signal}; brain = all − {archive, pin, unpin}; user = all.
- **Runtime never writes composition fields** (`representation`, `geometry`, `layer`, `order`, `visibility`), not only "never geometry of a pinned object". Reason: Decision 3 (narrow runtime authority) and Slice 04 ("no geometry beyond unplaced"); it also makes "completion never hides" structural. Runtime-created objects get `DEFAULT_LAYERS[kind]` (group 50, agent/job 100, artifact 120, window 220, attention 300 — conventions, overridable by brain/user).
- **`exec_state` and `work_ref` are runtime-only** (`execution_truth` refusal for brain/user), from Decision 17. Echoing the known value is not a change and is accepted.
- **Authority is checked on the effective change**, not on announced values: re-sending the current geometry of a pinned object is a `duplicate`, not a refusal. Op-level matrix is checked first, so brain `archive` is refused even on an unknown object.
- **Upsert/patch merge** announced fields (`SceneObjectFields`, `None` = unchanged) so a runtime refresh never resets brain/user composition. `constraints` and `disposition` are not command fields; the reducer sets `placed_by` (creator, then author of each geometry change) and only `pin`/`unpin`/`archive` change the rest.
- **Resolver placements** go through `set_geometry(placed_by=resolver)` from any actor with the op (Slice 05/08 commit path is user); refused on a pinned object (`pinned_by_user`) and on an explicitly placed one (`explicit_placement`). Unplaced = `geometry is None`; `placed_by = runtime` then just records the creator.
- ~~Archive keeps the object in `SceneSnapshot.objects`~~ — replaced after agent 0 review, see the rework entry below.
- **Signals:** `attach_signal` upserts an `attention` object and an `explains` relation whose `relation_id` is the signal id (one target per signal; retargeting is `relation_conflict`). Runtime may attach only to `agent`/`job`.
- **Patches are state deltas** (`put_object`, `put_relation`, `delete_relation`), not replayed commands; `apply_scene_patch(previous, patch)` reproduces the new snapshot and raises on gaps. No command id / dedup cache: `duplicate` means "no effect", so replays are idempotent (unlink of an absent relation is `duplicate`).
- **Refusal reasons** are a closed `SceneRefusal` token enum (for journal and MCP tool errors).
- **Wire:** snapshot, command and patch carry `schema_version: 1`, checked before any other key (`UnsupportedSceneSchemaVersion`, a `ValueError`, for missing/unknown/newer/non-int); decoding is strict at every level (unknown keys rejected). Payload `url` restricted to http(s) because the renderer will put it in the DOM.
- Relation-kind semantics beyond runtime rules (e.g. `groups` must start at a `group`) and `parent_of` cycles are **not** validated in V1.

No deviation from the locked decisions. No temporary/mock behaviour.

### 2026-09-16 — Slice 01 rework after agent 0 review of `c4a7b48`

1. **Execution nodes are runtime-only at creation.** A brain/user `upsert_object` creating `agent`/`job` is `rejected_authority/execution_node` (new `SceneRefusal.EXECUTION_NODE`; `exec_state` staying at its default no longer lets a fake star through). Brain/user still compose existing stars. `attention` stays creatable by all actors (runtime: execution facts; brain: "worth a look"; user: marking for themselves) — consistent with `attach_signal` being open to all in the matrix. Tests cover every actor × kind creation cell.
2. **Archive → tombstone (replaces note 6).** Archiving removes the object from `SceneSnapshot.objects`, deletes its relations and appends its id to `SceneSnapshot.archived_ids`. The patch carries the full history form through the new `PatchOpKind.ARCHIVE_OBJECT` (`disposition = archived`), for Slice 02 to write to history. Tombstones do not count against `MAX_SCENE_OBJECTS` (archiving frees a slot); they are bounded by `MAX_ARCHIVED_IDS = 4096`, kept in archive order, and the oldest are dropped inside `apply_scene_patch` so replay stays exact. Every command on a tombstoned id, creating upsert included, is `invalid/object_archived`. Justification: Core work state is memory-only per session (64 items, new `store_id` per start) and provider/job ids are not reused. Residual risk (documented in `docs/scene-model.md`): an id whose tombstone was dropped is free again and could be recreated by a replayed old work item; while the tombstone lives, the brain cannot reuse an archived id.
3. **`Disposition` kept, `active_objects` removed.** A snapshot now holds active objects only (validated), so `active_objects` would equal `objects`. `archived` still carries meaning on the history form: `put_object` must carry an active object, `archive_object` an archived one. `SceneSnapshot.is_archived(object_id)` added. Snapshot wire form gains a required `archived_ids` list (bounded before decoding); `schema_version` stays 1 (nothing persisted yet).
