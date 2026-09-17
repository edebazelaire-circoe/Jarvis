# Constellation scene model

Handoff `tasks/jarvis-constellation-scene-runtime/`, Slice 01 (domain contract).
Pure types and rules live in `jarvis/domain/scene.py`; the conformance suite is
`tests/unit/test_scene_contracts.py`. No I/O, no Core, adapter or runtime import:
Core's `SceneService` (Slice 02, see *Storage and revision continuity* below)
applies these rules, persists the result and keeps the patch for transport;
transport (03), runtime projection (04), renderer (05) and the brain display MCP
(06) all speak this vocabulary.

The scene is a **projection**. Core work state (`jarvis/domain/work_state.py`,
see `ARCHITECTURE.md` › *Core work state*) stays the execution truth
(decision 17). The scene adds what Core does not own: identity on screen,
composition, user constraints and the user's disposition of finished work.

## Objects

`SceneObject` — one stable identity for its whole life.

| Field | Meaning |
| --- | --- |
| `object_id` | stable id (≤ 128 chars, no surrounding spaces). Never changes, whatever the representation. |
| `kind` | closed: `agent`, `job` (execution nodes, "stars"), `artifact`, `attention` (signals), `window`, `group`. Immutable once created. |
| `category` | short token (`research`, `error`, `castor`…, ≤ 32). **Primary colour source** (decision 7). |
| `exec_state` | `WorkStatus` values plus `unknown`. Secondary cue only (halo, ring, badge), never colour. `unknown`: on an artifact/window/group/brain or user attention, no Core work behind it; on an execution node (`agent`/`job`), **not re-observed yet after a Core restart** (see *Execution state after a Core restart*). |
| `representation` | `point` \| `capsule` \| `window` (decision 6). |
| `geometry` | `{x, y, w, h}` in scene units (top-left corner and size, see *Coordinate frame*), or `null` = **unplaced** (the browser AutoResolver places it). `abs(x)`, `abs(y)` ≤ 100 000, `0 < w, h ≤ 100 000`. Cannot be cleared once set. |
| `layer` | integer 0–1000, stacking inside the scene container. |
| `order` | integer tiebreak within a layer (±1 000 000). |
| `visibility` | `visible` \| `hidden`. |
| `disposition` | `active` in every snapshot; `archived` only on the history form carried by an `archive_object` patch op (see below). |
| `constraints` | `placed_by` (`runtime` \| `brain` \| `user` \| `resolver`) and `pinned_by_user`. Set by the reducer only. |
| `origin` | actor that created the object (`runtime` \| `brain` \| `user`). Set once by the reducer, never writable, on the wire. An `agent`/`job` always has `origin = runtime`. |
| `work_ref` | `{source, external_id, work_id?}` — the Core `WorkItem` identity the node projects. |
| `payload` | `{title ≤ 160, summary ≤ 2 000 (multi-line), items ≤ 32 [{label, ref, url}]}`; `url` is `http(s)` only; compact UTF-8 JSON ≤ 16 KiB. `title`, `label`, `ref`, `url` are single printable lines; `summary` accepts `\n` and `\t` but no other C0 control character. |

## Relations

`SceneRelation {relation_id, kind, from_id, to_id, layer = 50}`, directed, two
distinct **active** objects.

| Kind | Typical use |
| --- | --- |
| `parent_of` | execution topology (parent sub-agent/job → child), written by runtime |
| `explains` | artifact → star (or object) it explains, written with the artifact by `attach_artifact` (Slice 07); also signal → node it is attached to |
| `groups` | group → member |

A signal (`attach_signal`) has exactly one target; its `explains` relation
carries the signal's own id as `relation_id` (`is_signal_relation`). A signal is
**live** exactly while that relation exists (`is_live_signal`); see *Runtime
signal lifecycle* below.

Only signals have that shape: `attach_artifact` requires `relation_id ≠
object_id` (the brain tool derives `brain-explains-<sha256(from\nto)[:16]>`), and
a brain/user `link` of `explains` with `relation_id == from_id` from a source that
is not `attention` is refused `signal_shape` (Slice 07 QA rework). An artifact
link is therefore never read as a signal, never `runtime_owned`, and brain or user
may unlink it. See *Semantic artifacts* below.

## Layers

Any integer in 0–1000 is valid; overlap is not forbidden (decision 8). The
bands 50/100/120/150/220/300 are conventions. When a command creates an object
without an explicit layer, the reducer uses `DEFAULT_LAYERS`:

| Kind | Default layer |
| --- | --- |
| `group` | 50 (relations also default to 50) |
| `agent`, `job` | 100 |
| `artifact` | 120 |
| `window` | 220 |
| `attention` | 300 |

The brain and the user may change object and relation layers afterwards;
runtime never announces a layer. A runtime `link` must carry the default
relation layer (50), which means "not announced": a new relation gets 50, an
existing relation keeps the layer the brain or user chose, and any other layer
is `rejected_authority` (`runtime_composition`).

## Visibility vs disposition

- **Completion is not removal** (decision 12): an `exec_state` change never
  touches `visibility` or `disposition`. A completed, unreviewed star stays
  active and visible.
- **Hidden** = active but not rendered; recoverable (decision 13).
- **Archived** = out of the active scene, kept for history. Only `user` archives
  (decision 14). Archiving removes the object from `SceneSnapshot.objects`,
  deletes every relation that touches it, and appends its id to
  `SceneSnapshot.archived_ids` (a **tombstone**). The patch carries the full
  object with `disposition = archived` (`archive_object` op) so the store can
  write it to history.
- `SceneSnapshot.objects` is exactly the active scene: every object in it is
  `active`, and relations only link those objects. `Disposition` stays in the
  model because the history form of an object needs it; there is no
  `active_objects` view any more, it would equal `objects`.

### Tombstones

`archived_ids` keeps archived ids in archive order so that a late runtime update
(or any command) cannot resurrect an archived star: every command that targets a
tombstoned id is `invalid` (`object_archived`), **including a creating
`upsert_object`** and a signal or relation pointing at it. Archiving a tombstoned
id again is a `duplicate`.

- Tombstones do **not** count against the 512 active objects: archiving frees a
  slot, so a long-lived scene never fills up with history.
- They are bounded to `MAX_ARCHIVED_IDS` = 4 096. When an archive exceeds the
  bound, the oldest tombstones are dropped, inside `apply_scene_patch`, so the
  same patch replayed on the same snapshot drops exactly the same ids.
- Why forgetting is acceptable: Core work state is memory-only per session (at
  most 64 items, a new `store_id` on each start) and provider/job ids are not
  reused, so the work behind an id archived more than 4 096 archives ago is not
  re-observed in practice.
- **Residual risk:** once its tombstone is dropped, an id is free again. A
  runtime update for that very work (for example a reconciliation replaying an
  old item) would create a new active star, and a brain/user object reusing that
  id would be accepted. Conversely, while the tombstone lives, an id cannot be
  reused: the brain must choose a fresh id for a new object after the user
  archived an old one.

## Commands

`SceneCommand {op, actor, …arguments}`. The shape is validated at construction
(missing or extra argument → `ValueError`); the reducer only sees well-formed
commands.

| Op | Arguments | Effect |
| --- | --- | --- |
| `upsert_object` | `object_id`, `fields` | create (`kind` + `category` required) or merge the announced fields |
| `patch_object` | `object_id`, `fields` | merge into an existing object |
| `set_geometry` | `object_id`, `geometry`, `placed_by?` (`resolver` only) | move/resize |
| `set_representation` | `object_id`, `representation`, `geometry?` | change form, optionally with its new size |
| `set_visibility` | `object_id`, `visibility` | hide/show |
| `pin` / `unpin` | `object_id` | set/clear `pinned_by_user` (pin needs a placed object) |
| `link` | `relation` | add a relation, or change the layer of the same relation (brain/user; runtime never changes a layer); brain/user never create a `parent_of` between execution nodes (`runtime_owned`) |
| `unlink` | `relation_id` | remove a relation (absent → `duplicate`); for runtime, also how it retires its own signal; brain/user cannot remove runtime topology or signal links (`runtime_owned`) |
| `archive` | `object_id` | user disposition; an execution star takes its runtime signals (cascade, Slice 08) |
| `archive_many` | `object_ids` (1–512, unique) | user bulk disposition of terminal execution stars and their runtime signals, all or nothing, one revision (Slice 08) |
| `attach_signal` | `object_id`, `fields`, `target_id` | create/update an `attention` object and its `explains` relation |
| `attach_artifact` | `object_id`, `fields`, `target_id`, `relation_id` (≠ `object_id`) | create/update an `artifact` object **and** its `explains` relation to `target_id`, one patch, all or nothing (Slice 07) |

`fields` (`SceneObjectFields`) lists what the command announces; `null` means
"not announced, unchanged". It cannot carry `constraints` or `disposition`.

## Authority matrix

Enforced by `apply_scene_command`, not by callers or tool catalogues.

Operation level (`ALLOWED_SCENE_OPS`):

| Op | runtime | brain | user |
| --- | --- | --- | --- |
| `upsert_object` | ✔ | ✔ | ✔ |
| `patch_object` | ✔ | ✔ | ✔ |
| `set_geometry` | ✘ | ✔ | ✔ |
| `set_representation` | ✘ | ✔ | ✔ |
| `set_visibility` | ✘ | ✔ | ✔ |
| `pin` | ✘ | ✘ | ✔ |
| `unpin` | ✘ | ✘ | ✔ |
| `link` | ✔ | ✔ | ✔ |
| `unlink` | ✔ | ✔ | ✔ |
| `archive` | ✘ | ✘ | ✔ |
| `archive_many` | ✘ | ✘ | ✔ |
| `attach_signal` | ✔ | ✔ | ✔ |
| `attach_artifact` | ✘ | ✔ | ✔ |

Effect level (checked on what actually changes, so echoing a known value is
never a violation).

Creation by actor and kind:

| Kind | runtime | brain | user |
| --- | --- | --- | --- |
| `agent`, `job` | ✔ | ✘ `execution_node` | ✘ `execution_node` |
| `attention` | ✔ | ✔ | ✔ |
| `artifact`, `window`, `group` | ✘ `runtime_kind` | ✔ | ✔ |

Rules:

- **runtime** writes only `agent`/`job`/`attention` objects (`runtime_kind`),
  never a composition field — `representation`, `geometry`, `layer`, `order`,
  `visibility` — nor a relation layer (`runtime_composition`); links only
  `parent_of` between execution nodes; unlinks only a `parent_of` between two
  runtime execution nodes, or a relation **shaped like a signal link**
  (`explains` whose `relation_id` equals its `from_id`) from a runtime
  `attention` object to a runtime execution node — the retirement of a signal,
  Slice 04 (`runtime_relation` otherwise, `runtime_origin` when an endpoint is
  a brain or user object). Relations carry no origin: whoever created such a
  relation, runtime may remove it (see *Runtime signal lifecycle* › residual
  risks); attaches signals only to execution nodes. It never creates or
  edits artifacts, and never archives, hides or places anything, its own
  signals included.
- **Origin**: runtime patches, upserts, reuses as a signal id, attaches to, or
  links/unlinks only objects whose `origin` is `runtime` (`runtime_origin`). A
  note the brain or user created as `attention` is theirs: runtime cannot
  rewrite it, even with `attach_signal` on the same id. Brain and user keep
  their rights on runtime-created objects.
- **Execution nodes**: only runtime creates an `agent` or `job` object;
  brain and user get `execution_node` (decisions 3, 4, 17 — a star comes from
  an execution fact, never from composition). Brain and user may still compose
  existing stars (category, payload, layout, visibility, links). `attention`
  signals are creatable by all three actors: runtime for execution facts, brain
  to point at something worth a look, user to mark something for themselves.
- **Execution truth**: only runtime changes `exec_state` or `work_ref`
  (`execution_truth`, decision 17).
- **Runtime-owned relations** (Slice 06 QA rework, decisions 3 and 17): brain
  and user never `unlink` a `parent_of` between two execution nodes, nor a
  signal-shaped `explains` (`relation_id == from_id`) from a runtime `attention`
  to an execution node (`runtime_owned`, `is_runtime_owned_relation`). The rule is
  on shape and endpoints (relations have no origin). Brain and user cannot
  **create** a `parent_of` between two execution nodes either (`runtime_owned`
  at `link`, Slice 06 final follow-up): such a link could never be removed
  again, so a brain mistake would leave false topology. What stays open: the
  user dismisses by archiving the star or the signal (archive removes the object's
  relations); brain and user may hide the signal object (`set_visibility`) and
  change a runtime relation's layer (`link` on the same id and endpoints).
- **Signal shape** (Slice 07 QA rework): brain and user never create an `explains`
  whose `relation_id` equals its `from_id` unless the source is an `attention`
  object (`signal_shape`); relayering an existing relation stays allowed.
- **Reserved ids** (same rework): brain and user never create an object or a
  relation whose id has the form the runtime projector builds
  (`is_runtime_reserved_id`: any `:` as in `<source>:<external_id>` and its
  hashed form, or a `attention!` / `attention#` / `parent_of!` / `parent_of#`
  head): `reserved_id`. Otherwise an object or relation created first under such
  an id would stop the projector from placing the star, the `parent_of` link or
  the failure signal (`relation_conflict`, `projection_conflict`). Composing what
  runtime created under those ids (patch, hide, relayer an existing relation)
  stays allowed; re-attaching a retired runtime signal (`attach_signal` creating
  its relation again) is the runtime's.
- **Pins**: a `pinned_by_user` object is moved or resized by the user only
  (`pinned_by_user`), and never by a resolver placement even when a user
  command carries it. `pin`/`unpin` are user-only because the flag records a
  user decision and a brain `unpin` would bypass the protection.
- **Resolver** (`set_geometry` with `placed_by = resolver`) is accepted from
  actor `user` only, because the browser AutoResolver commits through the
  Control Center user proxy; from brain it is `resolver_actor` (runtime has no
  `set_geometry` at all). It only places an unplaced object or nudges one it
  placed itself (`explicit_placement`, decision 9).
- `placed_by` becomes the actor (or `resolver`) whenever geometry changes; on
  creation it is the creating actor.
- **Artifacts** (Slice 07, decision 5): runtime has no `attach_artifact`
  (`op_not_allowed`): an artifact is a brain selection, never a raw event. The
  command applies the `upsert_object` rules to the artifact (reserved id,
  `kind_immutable`, `scene_full`, `pinned_by_user` on a geometry change, execution
  truth) and the `link` rules to its relation (target active, `reserved_id`,
  `relation_conflict`, `relation_limit`); any refusal refuses both.

## Outcomes, revision and patches

`apply_scene_command(snapshot, command) -> SceneUpdate {outcome, snapshot, patch, reason}`.

| Outcome | When | Revision | Patch |
| --- | --- | --- | --- |
| `applied` | something changed | `+1` | yes |
| `duplicate` | nothing would change (replay, echo, unlink of an absent relation) | unchanged | no |
| `rejected_authority` | matrix or effect rule (`op_not_allowed`, `runtime_kind`, `runtime_composition`, `runtime_relation`, `runtime_origin`, `runtime_owned`, `reserved_id`, `signal_shape`, `resolver_actor`, `execution_node`, `execution_truth`, `pinned_by_user`, `explicit_placement`) | unchanged | no |
| `invalid` | well-formed but inapplicable: `unknown_object`, `object_archived`, `kind_immutable`, `incomplete_object`, `unplaced`, `scene_full`, `relation_limit`, `relation_conflict`, `not_bulk_archivable` (`archive_many`, Slice 08), `revision_exhausted` | unchanged | no |

`reason` (`SceneRefusal`) is a stable token for the journal and for tool errors
surfaced to the brain. Refused and duplicate updates return the very snapshot
they received.

`ScenePatch {revision, ops}` is the exact state delta from `revision − 1`:
`put_object` (full active object), `archive_object` (full object with
`disposition = archived`: removes it, adds its tombstone), `put_relation` (full
relation), `delete_relation` (`relation_id`). `apply_scene_patch(previous, patch)`
reproduces the new snapshot, tombstone eviction included, and raises on a
revision gap, a `put_object` of a tombstoned id, or an unknown archive or
deletion — the consumer then re-reads the snapshot (decision 20).

## Runtime signal lifecycle

Slice 04 (PM amendment F1, reviewed domain change). The runtime projector
(`jarvis/core/scene_projector.py`, `ARCHITECTURE.md` › *Runtime scene
projection*) raises a signal when a piece of work becomes `failed`,
`interrupted` or `blocked`, and must be able to retire it when the work leaves
that state, without receiving archive or layout rights.

Rule:

- **one signal per work item**, id `attention!<star id>`, created and then
  updated in place by `attach_signal` (`category` and `exec_state` = the work
  status, `payload.title` = `error_class` or the status, bounded message);
- **live** = its `explains` relation (`relation_id` = signal id, from the signal
  to its star) exists. `is_live_signal(snapshot, object_id)` is the only
  definition consumers use (renderer, brain inspection);
- **retire** = runtime `unlink` of that relation, then `patch_object` of the
  signal's `exec_state` to the status the work reached (`running`,
  `completed`…). The attention object stays in the scene, not live, one per
  star at most; `attach_signal` on the same id makes it live again;
- `failed` and `interrupted` that stay terminal keep their signal live;
  `completed` and `cancelled` never raise one.

Domain change in `_plan_unlink`: runtime may now also delete a relation for
which `is_signal_relation` holds (`explains` whose `relation_id` equals its
`from_id`) when the source is an `attention` object of `origin = runtime` and
the target an `agent` / `job` of `origin = runtime`. The check is on the
relation's **shape and endpoints**, not on who created the relation, because
relations have no `origin`. Everything else is unchanged:

| Runtime `unlink` of… | Before Slice 04 | Now |
| --- | --- | --- |
| `parent_of` between runtime execution nodes | applied | applied |
| its own signal relation (runtime attention → runtime star) | `rejected_authority` / `runtime_relation` | **applied** (`delete_relation`) |
| a brain or user signal on a runtime star | `runtime_relation` | `runtime_origin` |
| a relation named like a signal but of another kind, or from an artifact, or towards an artifact | `runtime_relation` | `runtime_relation` |
| any `explains` whose id is not its source (artifact explanations) | `runtime_relation` | `runtime_relation` |

Rejected alternatives: a new `retire_signal` op (new vocabulary in the command
wire, the matrix and every future tool catalog for one runtime-only effect); a
new object-deletion patch op (a patch wire change, hence a schema bump for the
browser applier and the store); runtime `set_visibility` or `archive` (layout and
disposition rights decision 3 withholds, and an archived id could never signal
again); keeping the relation and marking only `exec_state` (a stale `explains`
edge would still be drawn and read as live).

Residual risks (accepted by the PM after Slice 04 QA):

- **relations have no origin.** A brain or user relation that has the same
  shape and endpoints as a runtime link is removable by runtime: an `explains`
  from a runtime signal to its runtime star named after the signal (for example a
  user who re-attached a retired signal by hand), and any `parent_of` between two
  runtime stars (runtime owns execution topology). Brain and user relations that
  touch a brain or user object, or of any other shape, stay untouchable. Adding
  an origin to relations would be a wire and storage schema change;
- a **retired signal keeps its last `category`** (`failed`, `blocked`…) and
  payload; only `exec_state` records the new status. Consumers must use
  `is_live_signal`, not the category;
- runtime cannot delete objects, so a retired signal occupies an object slot as
  long as its star lives. Before Slice 08, a user archive of a star left its
  attention object behind (one leaked slot per archived star with a signal).
  Since Slice 08 the archive cascade takes the star's runtime signals with it, and
  `archive_many` accepts the orphan signals older scenes still hold (see
  *Archive cascade and bulk archive*);
- `parent_of` **cycles** are not validated (Slice 01) and can appear from
  producer data or brain/user links; renderers walking parents must guard
  against them (Slice 05: the AutoResolver's anchor walk stops at the first
  repeated id).

## Execution state after a Core restart

Slice 10. Core work state lives in memory; the scene is durable. At Core start
the runtime projector marks every active runtime execution node whose
`exec_state` is not terminal (`pending`, `running`, `blocked`, or already
`unknown`) as `unknown`, with one runtime `patch_object`. Semantics of
`unknown` on an execution node:

- **not running, not failed**: Core no longer knows; a producer may still
  report it. Renderers show a quiet secondary cue (« état inconnu depuis le
  redémarrage »), never the running animation nor an alert;
- **not terminal**: `archive_many` never takes it (`bulk_archivable` requires a
  terminal state), a user archive is still possible;
- **re-observation** of the same `(source, external_id)` writes the real
  status; after a grace (`RESTART_GRACE_S` = 60 s by default) a still-`unknown`
  node becomes `interrupted` with one runtime signal whose `payload.title` is
  `core_restarted_unobserved` (signal written before the node's state), retired
  as usual if the work is reported later.

Domain: no change was needed. Runtime already may write `exec_state` (including
`unknown`) on its own execution nodes; brain and user writing it stay
`rejected_authority/execution_truth`, runtime on a non-runtime object stays
`runtime_origin`/`runtime_kind` (test
`test_runtime_may_write_unknown_on_its_own_execution_star_and_nobody_else_may`).
Nothing else changes at restart: no deletion, no disposition, visibility,
geometry, pin or relation write, and a `store_id` change during Core's life marks
nothing. Details and restart paths: `ARCHITECTURE.md` › *Runtime scene
projection* › *Restart reconciliation*.

## Archive cascade and bulk archive

Slice 08 (PM amendment on capacity; `ARCHITECTURE.md` › *Scene user
interaction*). Runtime cannot delete objects, so before this change a user
archive of a star left its signal behind (one leaked slot per archived star with
a signal, towards 512).

**Signal owner** (`signal_owners(snapshot)`, one pass): for each `attention`
object of `origin = runtime`, the target of its live signal link when that
target is an execution node, else the first active execution node with the same
`work_ref` `(source, external_id)` (`work_id` may be set later), else `None`
(orphan). Retired signals, which have no link, are found by their `work_ref`.

**Cascade** (`archive`, user): archiving an execution star also archives every
runtime signal it owns (`runtime_signals_of`), in the same patch and revision,
signals first then the star, then one `delete_relation` per relation touching any
of them. The star's tombstone is therefore the newest and the last to be
evicted. Brain and user `attention` objects are never cascaded; archiving a signal
alone keeps its star.

**`archive_many`** (user only): `object_ids`, 1 to `MAX_ARCHIVE_MANY_IDS` (512)
unique ids, list length checked before decoding. Rule (`bulk_archivable(snapshot,
id, selected)`):

- an `agent` / `job` whose `exec_state` is terminal (`TERMINAL_EXEC_STATES`:
  `completed`, `cancelled`, `failed`, `interrupted`); never `running`,
  `pending`, `blocked` or `unknown`. Core work never leaves a terminal status
  (`ALLOWED_WORK_TRANSITIONS`), so a terminal star cannot be running again
  within its store;
- a runtime signal whose owner is in the selection and terminal, or an orphan
  runtime signal;
- an **orphan artifact** (Slice 07 QA rework, `is_orphan_artifact`: no `explains`
  relation from it), never an artifact still linked;
- nothing else (other brain or user objects, windows, groups).

Already archived ids are skipped (another tab was faster); if nothing remains,
`duplicate`. An unknown id is `invalid/unknown_object`, any other id outside the
rule `invalid/not_bulk_archivable`, and **the whole command is refused**: the user
confirmed counts, so a selection that became wrong is recomputed and confirmed
again instead of applying part of it. Otherwise one revision archives the
selection with each star's cascade. The patch uses the existing op kinds, so the
wire and storage schema do not change; only `MAX_PATCH_OPS` grows to
`MAX_SCENE_OBJECTS + MAX_SCENE_RELATIONS` (1 536). Readers written before
Slice 08 (`ScenePatch.from_payload`) refuse a patch above 1 025 ops; the only
readers are this repository's Core, Control Center and browser client (which has
no op bound), updated together.

The projector never resurrects: it reads `archived_ids` before writing a star
and skips the star and its signal (`skipped_archived`), whatever work update or
reconciliation follows (test
`test_an_archived_failed_star_and_its_signal_never_resurrect_after_more_work_updates`,
browser run: `skipped_archived` 0 → 1, no refusal journaled).

## Semantic artifacts

Slice 07, decisions 5, 6 and 12. An **artifact** (`kind = artifact`) is a
brain-selected, grouped explanation of finished work: one research artifact for
every URL visited, one files artifact for a set of modified files, one email or
roadmap artifact for what was sent or changed. Never one object per low-level
action; no runtime auto-artifact.

- **Write.** `attach_artifact` creates or updates the artifact and its `explains`
  relation to the target (usually the sub-agent's star) in one patch. A refused
  link leaves no orphan artifact; replaying the command is `duplicate`. Why a
  domain op rather than `upsert_object` then `link`: the brain cannot delete or
  archive (decision 14), so a compensation for a refused link does not exist for
  it, and a pre-check before two commands still races with the user.
- **Grouping rule** (tool side, `scene_add_artifact`): one active artifact per
  target and category (category stored lowercase, compared without case). A new
  call with the same target and category completes the first such artifact
  instead of creating another: payload only (title replaced, summary kept unless
  given, items merged, an item with the same URL updated in place, otherwise
  deduplicated on label and ref, or the list replaced with `items_mode=replace`);
  never its representation or geometry. Parallel calls for the same pair are
  serialised per display-MCP process. An artifact the user archived is never
  revived (its tombstone refuses it; the tool then creates a new one once).
- **Payload.** Bounds of *Objects*: title ≤ 160, summary ≤ 2 000, at most 32
  items `{label, ref, url}`, `url` `http(s)` only, 16 KiB. Artifact text is data
  for the brain, never an instruction.
- **Categories.** Open token list, validated for shape only (`check_token`, ≤ 32).
  Recommended set, shared by the brain prompt, the tool description and the
  renderer colour map (`RECOMMENDED_ARTIFACT_CATEGORIES` in
  `jarvis/runtime/display_mcp.py`, `ARTIFACT_CATEGORIES` in
  `control_center_scene_layout.js`, parity test):

  | Category | Use | Colour family |
  | --- | --- | --- |
  | `research` | links and facts found | research |
  | `fichiers` | files created or modified | code |
  | `tests` | test runs and results | code |
  | `api` | API calls and their outcomes | code |
  | `roadmap` | roadmap or Trello changes | comms |
  | `email` | emails sent or drafted | comms |
  | `document` | document produced | doc |
  | `autre` | anything else worth keeping | doc |

  Any other token gets a stable hashed colour.
- **Representation.** Created as a `capsule` (category and title near its star)
  unless the brain asks otherwise; `window` is the inspection view (summary,
  items, link back to the star). Same identity in every form (decision 6).
- **Lifecycle.** An artifact stays until the user disposes of it (decision 12).
  Archiving its star does not cascade to it (the cascade takes runtime signals
  only); the relation goes with the star and the artifact stays, unlinked: an
  **orphan artifact** (`is_orphan_artifact`: no `explains` relation from it, so no
  link to any active object). `archive_many` (user only) takes an artifact **only
  when it is orphan**, re-validated by the reducer; an artifact still linked is
  `not_bulk_archivable`, the brain is `op_not_allowed`. The page offers « Archiver
  les artefacts orphelins (N)… » as its own confirmed action, and both archive
  confirmations say what stays. An artifact the brain created without ever linking
  it counts as orphan too.

## Coordinate frame

Slice 05 (`ARCHITECTURE.md` › *Scene renderer*). Geometry is in scene units and
stays authoritative (decision 10): the renderer maps it to the window and never
rewrites it.

| Item | Rule |
| --- | --- |
| Origin | (0, 0) is the centre of the window (the scene container) |
| Axes | x grows to the right, y grows downwards |
| Box | `geometry {x, y}` is the top-left corner, `{w, h}` the size, same units |
| Reference frame | x ∈ [−160, 160], y ∈ [−90, 90] (`SCENE_FRAME_HALF_WIDTH` = 160, `SCENE_FRAME_HALF_HEIGHT` = 90): always entirely visible |
| Mapping | uniform scale `s = min(W / 320, H / 180)` pixels per unit, centred; no distortion |
| Other aspect ratios | the long axis shows extra scene (visible x ∈ ±W/(2s), y ∈ ±H/(2s)); never bars |
| Outside the window | the object stays in the scene, clipped at the window edge, counted "hors champ"; never moved |
| Representation | a `point` is drawn at its box centre; `capsule` and `window` fill their box |
| Composition safe area | x ∈ [−152, 138], y ∈ [−72, 68] (`SCENE_SAFE_AREA`): no control of the page covers it at 1280 × 720 in either theme; a box is safe when `x0 ≤ x`, `y0 ≤ y`, `x + w ≤ x1`, `y + h ≤ y1`. Beyond it, up to the frame edges, controls (top bar, docks, voice hint, status chips) may cover the object |
| Unplaced | `geometry = null`: the browser AutoResolver places it inside the safe area and commits `set_geometry` with `placed_by = resolver` once |

Examples: top left ≈ (−150, −70); bottom right: `x + w ≤ 138`, `y + h ≤ 68`;
the centre, where JARVIS's face sits, is (0, 0); a readable note ≈ 60 × 36. At 1920 × 1080, one unit is 6 px; at
1280 × 720, 4 px.

The brain reads this frame and the safe area in the `scene_inspect` legend
(`frame`), in the `geometry` argument description, and in one line of its
display prompt. On small windows the page may draw a window as a capsule, or a
capsule as a point, without changing the representation stored in the scene.

## Bounds and wire form

| Bound | Value |
| --- | --- |
| active objects per snapshot | 512 — creation beyond is `invalid` (`scene_full`); archiving frees a slot |
| tombstones (`archived_ids`) | 4 096 — the oldest are dropped deterministically |
| relations per snapshot | 1 024 |
| ops per patch | 1 536 (Slice 08: a bulk archive of the whole scene plus all relations; before, 1 025) |
| ids per `archive_many` | 512 |
| payload | 16 KiB compact UTF-8 JSON |
| revision | 0 … 2^63 − 1 (SQLite INTEGER); a change at the last revision is `invalid` (`revision_exhausted`) |
| raw value echoed in an error message | 80 characters, then `…` |

Validation refuses what exceeds; nothing is silently truncated. Snapshot,
command and patch payloads carry `schema_version: 1`. Decoding checks the
version first and raises `UnsupportedSceneSchemaVersion` (a `ValueError`) for a
missing, unknown or newer version, then rejects unknown keys at every level,
missing stored keys, wrong types and unknown enum values; list lengths are
checked before decoding. Decoding raises only `ValueError` or `TypeError`: a
400-digit JSON integer in a geometry, layer, order or revision is a
`ValueError`, never an `OverflowError`. Error messages never echo more than 80
characters of a received value.

Text, token and identifier checks are shared with `work_state` through the
private module `jarvis/domain/_checks.py` (same rules, same messages).

## Storage and revision continuity

Slice 02 (`ARCHITECTURE.md` › *Constellation scene store*). Core's `SceneService`
applies commands with `apply_scene_command`, persists the resulting state to
`data/state/scene.sqlite3`, then keeps the patch in a bounded ring and wakes
`wait_for_revision` waiters. The scene is never published on `CoreEventBus`
(that bus is relayed unfiltered to Voice over `/v1/events`). The `scene_id` is created
once and kept; the revision continues from its stored value across restarts and
never regresses (a commit is refused unless the stored revision is the one the
patch starts from). Archived objects leave `SceneSnapshot.objects` but their
archived form stays queryable through `SceneReader.archived_history`; tombstones
are stored and evicted exactly as `apply_scene_patch` does. The store keeps
state, not a log of patches, so nothing stored is replayed through
`apply_scene_patch`. Any change to the wire or storage shape requires bumping
`SCENE_SCHEMA_VERSION` (stored as `wire_schema_version`) or the file's
`schema_version`; a reader refuses any version it does not know.

## Transport

Slice 03 (`ARCHITECTURE.md` › *Scene transport*). The wire forms above travel
unchanged: `GET /v1/scene/snapshot` wraps `SceneSnapshot.to_payload()` with
`scene_id`, `epoch` and `revision`; `GET /v1/scene/patches` returns
`ScenePatch.to_payload()` items strictly consecutive from `after + 1`, or
`resync_required` (another epoch or scene, `after` ahead of Core, ring too
short) and never a snapshot; `POST /v1/scene/commands` takes one
`SceneCommand.to_payload()` and returns the `SceneUpdate` as `{outcome, reason,
revision, patch}` — refusals are outcomes, not HTTP errors.

- **Epoch**: `SceneService.epoch`, new at every `start()`. A consumer keys its
  cache on `(scene_id, epoch, revision)`; any other epoch means refetch.
- **Bulk archive answer at the Control Center** (Slice 08, QA rework): Core's
  answer carries the patch as for any command; the Control Center validates it
  and then relays an `archive_many` answer to the page with `patch: null` and
  `patch_omitted: true` (up to ~8 MiB otherwise). The page reads the outcome and
  revision, and receives the patch through the long-poll; the brain tools talk to
  Core directly and are unaffected.
- **Actors over HTTP**: `brain` and `user` only; `runtime` is 403. The Control
  Center proxy forces `user`. The actor is declared, not authenticated: the
  brain shares the OS user and could read the token, so decision 14 holds
  through the tool catalog and the reducer, not through the transport.
- **Browser applier**: `jarvis/runtime/control_center_scene.js` mirrors
  `apply_scene_patch` (same order, same refusals, same eviction) and signals a
  resync on a gap, a refused patch, another epoch or scene, or
  `resync_required`. Its parity with the Python reducer is a test.
- **Bounds**: command body 64 KiB (413), patch response 1 MiB with `more`,
  client read of any scene response 16 MiB; responses are compact UTF-8 JSON
  (a worst-case snapshot stays under 11 MiB).

## Brain tool mapping

Slice 06 (`ARCHITECTURE.md` › *Brain display MCP*). The brain's MCP tools
(`jarvis/runtime/display_mcp.py`) speak this vocabulary as actor `brain`, one
`SceneCommand` per call, never `placed_by`, never `archive` / `pin` / `unpin`.

| Tool | Arguments | Command sent | Typical refusals surfaced |
| --- | --- | --- | --- |
| `scene_inspect` | `kind?`, `category?`, `text?` | `GET /v1/scene/snapshot` (read only) | — (transport errors only) |
| `scene_query` (Slice 09) | at least one of `kind?`, `category?` (no case), `exec_state?`, `origin?`, `visibility?`, `text?`, `work?` (`source` / `external_id` / `work_id` / `source:external_id`), `explains?` (object id), `near?` `{object_id, radius}` | `GET /v1/scene/snapshot` (read only); inspect rows, `distance` column with `near`, ≤ 20 000 bytes | `unknown_object`, `object_archived` (reference of `explains`/`near`), `unplaced` (`near` reference without committed geometry); nothing sent |
| `scene_get` (Slice 09) | `object_ids` (1–8) | `GET /v1/scene/snapshot` (read only); full payload (items with `host`), `work_ref`, composition, constraints, relations in/out, `explained_by`, `explains`, `signals`/`live_signal`, ≤ 20 000 bytes | — (`not_found` list, transport errors only) |
| `scene_create_object` | `kind` ∈ artifact/window/group/attention, `category`, `title?`, `summary?`, `items?`, `representation?`, `geometry?`, `layer?`, `order?` | `upsert_object` on a fresh id `brain-<kind>-<hex>`; unset fields are not announced (kind default layer applies) | `scene_full`, `object_archived` |
| `scene_update_object` | `object_id`, `category?`, `title?`, `summary?`, `items?`, `representation?`, `geometry?`, `layer?`, `order?`, `visibility?` | geometry only → `set_geometry`; representation (± geometry) only → `set_representation`; visibility only → `set_visibility`; otherwise one `patch_object` with every given field (payload merged with the current one) | `pinned_by_user`, `unknown_object`, `object_archived` |
| `scene_set_visibility` | `object_id` + `visibility`, or `scope="all_hidden"` + `visibility="visible"` | `set_visibility`; with the scope, one `set_visibility` per object hidden in the current snapshot (≤ 128 per call, 15 s budget), counts and ids returned | `unknown_object`, `object_archived` (counted per object with the scope) |
| `scene_link` | `from_id`, `to_id`, `kind`, `relation_id?` (`brain-…` only), `layer?` | `link`; `layer` key omitted unless given (never a default of 50); an existing identical relation without a layer is a local `duplicate`, nothing sent | `relation_conflict`, `relation_limit`, `unknown_object`, `object_archived`, `reserved_id` (domain side), `runtime_owned` (`parent_of` between execution nodes) |
| `scene_unlink` | `relation_id` | `unlink` (absent → `duplicate`) | `runtime_owned` |
| `scene_add_artifact` | `target_id`, `category`, `title`, `summary?`, `items?`, `items_mode?` (`append` default \| `replace`), `representation?`, `geometry?` (both applied on creation only) | one `attach_artifact`, under a per-(target, category) lock: on the first active artifact of that category already explaining the target (`action = updated`, payload merged, `ignored` lists a representation or geometry not applied), else on a fresh `brain-artifact-<hex>` with relation `brain-explains-<hash>` (`action = created`, capsule by default); `rule` is the short code `un_par_cible_et_categorie` | `object_archived` / `unknown_object` for the target (checked before sending, nothing sent), `pinned_by_user`, `scene_full`, `relation_limit`, `relation_conflict` |

Artifact updates that are not grouping (retitle, move, hide, show as window) go
through `scene_update_object`; there is no separate update tool.

The read tools (`scene_inspect`, `scene_query`, `scene_get`) never send a
command and mark only the objects they return as seen.

Refusals come back as MCP tool errors carrying `outcome`, `reason` (the
`SceneRefusal` token) and one explanatory sentence. Unknown arguments are refused
by name. Mutating results carry `scene_changed` when the scene moved since the
brain's last `scene_inspect`. Relations have no origin: a `parent_of` the brain
draws between two runtime stars may be removed by the runtime and not by the
brain (runtime-owned shape).

Validation:

```powershell
.venv/Scripts/python.exe -W error::ResourceWarning -m pytest -q -p no:cacheprovider tests/unit/test_scene_contracts.py tests/unit/test_work_state_contracts.py tests/unit/test_v2_architecture.py tests/unit/test_sqlite_scene.py tests/unit/test_scene_service.py tests/integration/test_v2_core_recovery.py tests/unit/test_scene_view.py tests/unit/test_scene_transport_client.py tests/integration/test_scene_transport.py tests/unit/test_scene_projector.py tests/integration/test_scene_projection_protocol.py tests/unit/test_display_mcp.py tests/unit/test_scene_settings.py tests/unit/test_scene_renderer_logic.py tests/unit/test_scene_artifacts.py tests/unit/test_scene_query_tools.py
.venv/Scripts/python.exe scripts/verify_release.py
```
