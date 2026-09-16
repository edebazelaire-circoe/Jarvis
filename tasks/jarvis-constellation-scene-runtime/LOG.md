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

### 2026-09-16 — Slice 01 — QA rework (QA on `22bdd2a`, agent 0 decisions)

- **M1 runtime relation layer** — `_plan_link`: a runtime link must carry `DEFAULT_RELATION_LAYER`, otherwise `rejected_authority/runtime_composition` (new or existing relation). The default means "not announced": an existing relation keeps the brain/user layer (`duplicate`). Docs: Layers section and `link` row. Tests: `test_runtime_never_announces_a_relation_layer`, `test_runtime_relink_keeps_the_layer_the_brain_chose`.
- **M2 `OverflowError`** — `SceneGeometry` converts with `float()` inside `try` and raises `ValueError("… is out of range")`; layer/order/revision are int-bounded. Test: `test_hostile_numbers_raise_value_errors_only` (400-digit int in geometry x/w, layer, order, snapshot and patch revision, schema_version).
- **m1 origin** — `SceneObject.origin: SceneActor`, required, set by the reducer at creation, not a command field, on the wire; `agent`/`job` must have `origin = runtime`. Runtime may write, reuse as a signal id, attach to, link or unlink only runtime-origin objects: new reason **`runtime_origin`** (checked after `runtime_kind`/`runtime_relation`, in `_check_runtime_reach`). Brain/user rights unchanged. Tests: `test_runtime_cannot_rewrite_or_reuse_brain_or_user_attention` (incl. runtime `attach_signal` reusing a user attention id), `test_origin_is_set_once_at_creation_and_travels_on_the_wire`, creation cells assert `origin`.
- **F2 resolver provenance** — `set_geometry(placed_by=resolver)` from a non-user actor is `rejected_authority/resolver_actor` (new reason; checked before the target lookup). Runtime still hits `op_not_allowed` first. Test: `test_resolver_placement_is_accepted_from_the_user_proxy_only`.
- **m2 bounded messages** — `_checks.preview()` (80 chars + `…`, containers summarized by type/length, huge-int repr guarded) used by enum decoding (custom message instead of `Enum`'s) and `UnsupportedSceneSchemaVersion`. Other messages only name fields or echo already-bounded ids/keys. Test: `test_error_messages_never_echo_unbounded_input` (1 MB op, actor, schema_version string/list, object_id, key, nested kind, summary, patch op → < 300 chars).
- **n1 revision** — `MAX_REVISION = 2**63 - 1` for snapshot (0..) and patch (1..); a change at the last revision is `invalid/revision_exhausted` (new reason) instead of an exception. Test: `test_revision_is_bounded_to_a_signed_64_bit_integer`.
- **n2 control characters** — `summary` rejects C0 controls other than `\n`/`\t` (`\r` included); `title`/`label` (and `ref`/`url`) were already single printable lines, which rejects every control including tab. Tests: `test_payload_text_rejects_control_characters`, `test_summary_keeps_newlines_and_tabs`.
- **m3 canonical reuse** — new private `jarvis/domain/_checks.py` (`MAX_ID_CHARS`, `TOKEN`, `check_text`, `check_token`, `check_id`, `preview`); `work_state.py` imports them under its former private names (`MAX_ID_CHARS` re-exported), behaviour and messages identical (`test_work_state_contracts.py` unchanged, green). `scene.py` uses them (empty category now says "category is required"). `_plan_relation_put` is shared by `_plan_link` and `_plan_attach_signal` (existing/conflict/limit, layer kept unless announced).
- **m4 test precision** — `match=` on every case of `test_malformed_commands_do_not_build`, `test_snapshot_decoding_is_strict`, `test_command_decoding_is_strict`, `test_patch_refuses_gaps_and_unknown_deletions`; allowed matrix cells assert patch op kinds (`MATRIX_PATCH_OPS`).
- **n4** — `docs/scene-model.md` Validation block lists `scripts/verify_release.py`.
- Not done, per agent 0: n3, n5, F1 (runtime retiring its own signals → Slice 04 contract, `origin` now makes it grantable).
- QA fuzz (`fuzz.py`, seed 20260916 × 6 000 commands and seed 7 × 12 000): **violations: none** (M1 and m1 oracles at 0).

## 2026-09-16 — Slice 01 PM decision: APPROVED

- Commits: `c4a7b48`, `22bdd2a` (PM review rework: runtime-only execution nodes, tombstone archive), `3018cbd` (QA rework).
- QA (qa-verification + code-review): first pass REWORK (M1 runtime relation layer, M2 OverflowError, m1–m4, n1, n2, n4, F2); re-verification APPROVE with evidence: 490 targeted tests passed; `verify_release.py` 3656 passed / 9 skipped; seeded fuzz 36 000 commands, 0 violations; lockstep old/new reducer diff over 36 591 commands, only intended divergences; `work_state.py` refactor behaviour-identical (0 diffs over 20 014 helper values and 20 000 observation payloads).
- Remaining nits routed: immutable-field guard on patch replay + schema bump rule → Slice 02 contract; bidi/zero-width text neutralisation → Slice 05; relation layer default and refusal surfacing → Slice 06; runtime signal lifecycle (F1) → Slice 04; snapshot size (F3) → Slice 03; doc message-bound overstatement → `Issues/01-scene-doc-message-bound.md`.
- runtime-validation / agent-trace-analysis not applicable (pure domain, nothing wired).

## 2026-09-16 — Slice 02 — implementation notes (agent 01)

Delivered `jarvis/ports/scene.py`, `jarvis/adapters/sqlite_scene.py`, `jarvis/core/scene_service.py`, wiring in `jarvis/core/v2_app.py` (`JarvisCoreApplication.scene`), tests `tests/unit/test_sqlite_scene.py`, `tests/unit/test_scene_service.py`, two scene tests appended to `tests/integration/test_v2_core_recovery.py`; docs: `ARCHITECTURE.md` › *Constellation scene store* (+ *Persistence*), `OPERATIONS.md` › *Scène constellation : fichier et refus*, `scene-model.md` › *Storage and revision continuity*.

Decisions taken inside the contract (reviewable by PM):

- **State, not a patch log.** `commit(previous, patch, result)` applies the patch ops to state tables (`scene_objects`, `scene_relations`, `scene_tombstones`, `scene_meta`, `scene_history`) in one `BEGIN IMMEDIATE` transaction; load decodes rows with the strict domain decoders. Nothing stored is replayed through `apply_scene_patch`, so the amendment's immutable-field guard is **not** added and `jarvis/domain/scene.py` is **unchanged**.
- **Order is persisted** (`position` columns) so a reloaded `SceneSnapshot` is `==` to the in-memory one (tuple order included); a replaced row keeps its position, a new one is appended, tombstone eviction keeps the newest `MAX_ARCHIVED_IDS` exactly like `apply_scene_patch`.
- **Two version guards** (amendment "any wire/storage change requires a bump"): file `schema_version` (table layout, = 1) and `scene_meta.wire_schema_version` (= `SCENE_SCHEMA_VERSION` of the JSON columns). Newer → `schema_newer`; missing/unreadable/older/other/foreign DB → `schema_unknown`; not-a-DB, `quick_check`, missing table, row that does not decode or whose key differs from its payload, rows without meta → `corrupted`; open/lock/rights → `storage_io`. Checks are read-only: a refused file is byte-identical afterwards (tested).
- **Commit guards**: stored `(scene_id, revision)` must equal Core's `previous` (CAS), deletes/archives must hit exactly one row, and row counts must equal the resulting snapshot, else `revision_conflict` and rollback. `synchronous=FULL` because a published revision must survive a power cut.
- **Stable error surface** in the port: `SceneStoreError(code)` with `SceneStoreErrorCode` {`schema_newer`, `schema_unknown`, `corrupted`, `storage_io`, `revision_conflict`, `unavailable`}; service raises `SceneUnavailableError` / `ScenePersistenceError`. Domain refusals are **not** errors (returned `SceneUpdate`), journaled once per actor/op/outcome/reason (`core.scene.command_refused`, info); duplicates silent.
- **Failure semantics**: commit failure → no revision advance, no ring entry, no publish, `core.scene.persist_failed` (error), `ScenePersistenceError` from the original exception; a transient failure lets the next command reuse the same revision. `revision_conflict` (or repository closed underneath) additionally makes the scene `unavailable` until restart (memory and disk disagree). Publish failure after commit → revision kept, `core.scene.publish_failed` (error).
- **Cancellation**: `apply` runs the critical section in a shielded task; a cancelled caller cannot leave disk ahead of memory (tested).
- **Start never raises**: `SceneService.start()` captures any exception (not only `SceneStoreError`, argued in the docstring: the scene is a projection and must not stop Core), journals `core.scene.unavailable` (error, reaches `runtime/errors.jsonl` / ERR panel) with the real type and message, closes the repository, and Core continues (`health.ready` stays true; tested in integration and in a real process). A second `start()` does not silently retry.
- **Patch ring** 512 (`patch_ring_size` injectable ≤ 512 for tests). `patches_since(revision, scene_id=None)` → `ScenePatchWindow(scene_id, revision, patches, resync_required)`; resync when revision < 0, > current, ring does not reach `revision + 1` (always after restart), or `scene_id` differs.
- **History**: `archived_history(object_id=None, limit ≤ 1000)` newest first; key `(object_id, revision)` because an id whose tombstone was evicted can be recreated and archived again. **Not pruned in V1** (one row per user archive; documented).
- **Bus payload** `{"scene_id", "revision", "patch": ScenePatch.to_payload()}`; event name `CORE_SCENE_UPDATED` lives in `scene_service.py`, mirroring `CORE_WORK_UPDATED` in `work_state.py` (not in `v2_services.py`).
- **Lifecycle**: `scene.start()` right after `jarvis.sqlite3` initializes; `scene.close()` in `stop()` after brain/scheduler, before the back-brain/jobs early returns (so the file is always closed), and in the start-failure path.

Deviations (with reasons):

1. **Composition-root exception extended.** `jarvis/core/v2_app.py` imports `jarvis.adapters.sqlite_scene`, added to `CORE_ADAPTER_IMPORT_EXCEPTIONS` in `tests/unit/test_v2_architecture.py` (the test says new adapters there need discussion — this is that flag). Reason: the brief asks to compose "following how the jobs SQLite store is composed", and every existing `JarvisCoreApplication(data_root=...)` must get a scene without app.py-only injection. `scene_service.py` itself imports ports only. Alternative if PM prefers: inject a repository factory from `jarvis/app.py` and leave the scene disabled when none is given. `v2_app` also accepts `scene_repository=` (test injection only).
2. **Shared helper extracted.** `SQLiteStateRepository._thread` body moved verbatim to module-level `run_sqlite_in_thread` in `sqlite_state.py` (the staticmethod delegates) so both SQLite adapters share the uncancellable-thread rule instead of duplicating it. Behaviour identical.
3. `jarvis/app.py` / `v2_config.py` untouched: the path derives from `data_root` like `jarvis.sqlite3`.

Risks for later Slices: `core.scene.updated` goes to every `/v1/events` subscriber (Voice included) and a patch may carry up to 1 025 ops; a burst from the projector (04) could fill a non-lossy 128-slot subscriber queue and evict it — Slice 03/04 should size/coalesce. Scene unavailability is visible in the journal and `JarvisCoreApplication.scene.availability`, not yet in `/v1/health` (transport is Slice 03).

Evidence: see the Slice 02 report (targeted tests, `verify_release.py`, real `python -m jarvis core` restart in scratch roots: revision 7 and identical snapshot after a hard kill; corrupted file → Core `ready`, `core.scene.unavailable` in `errors.jsonl`, file byte-identical).
