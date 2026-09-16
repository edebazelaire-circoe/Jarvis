# Constellation scene model

Handoff `tasks/jarvis-constellation-scene-runtime/`, Slice 01 (domain contract).
Pure types and rules live in `jarvis/domain/scene.py`; the conformance suite is
`tests/unit/test_scene_contracts.py`. No I/O, no Core, adapter or runtime import:
the future `SceneStore` (Slice 02) applies these rules, persists the patch and
publishes it; transport (03), runtime projection (04), renderer (05) and the
brain display MCP (06) all speak this vocabulary.

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
| `exec_state` | `WorkStatus` values plus `unknown`. Secondary cue only (halo, ring, badge), never colour. `unknown`: no Core work behind it, or not re-observed yet after a restart. |
| `representation` | `point` \| `capsule` \| `window` (decision 6). |
| `geometry` | `{x, y, w, h}` in scene units, or `null` = **unplaced** (the browser AutoResolver places it). `abs(x)`, `abs(y)` ≤ 100 000, `0 < w, h ≤ 100 000`. Cannot be cleared once set. |
| `layer` | integer 0–1000, stacking inside the scene container. |
| `order` | integer tiebreak within a layer (±1 000 000). |
| `visibility` | `visible` \| `hidden`. |
| `disposition` | `active` in every snapshot; `archived` only on the history form carried by an `archive_object` patch op (see below). |
| `constraints` | `placed_by` (`runtime` \| `brain` \| `user` \| `resolver`) and `pinned_by_user`. Set by the reducer only. |
| `work_ref` | `{source, external_id, work_id?}` — the Core `WorkItem` identity the node projects. |
| `payload` | `{title ≤ 160, summary ≤ 2 000 (multi-line), items ≤ 32 [{label, ref, url}]}`; `url` is `http(s)` only; compact UTF-8 JSON ≤ 16 KiB. |

## Relations

`SceneRelation {relation_id, kind, from_id, to_id, layer = 50}`, directed, two
distinct **active** objects.

| Kind | Typical use |
| --- | --- |
| `parent_of` | execution topology (parent sub-agent/job → child), written by runtime |
| `explains` | artifact → star it explains; also signal → node it is attached to |
| `groups` | group → member |

A signal (`attach_signal`) has exactly one target; its `explains` relation
carries the signal's own id as `relation_id`.

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

The brain and the user may change layers afterwards; runtime never does.

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
| `link` | `relation` | add a relation, or change the layer of the same relation |
| `unlink` | `relation_id` | remove a relation (absent → `duplicate`) |
| `archive` | `object_id` | user disposition |
| `attach_signal` | `object_id`, `fields`, `target_id` | create/update an `attention` object and its `explains` relation |

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
| `attach_signal` | ✔ | ✔ | ✔ |

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
  `visibility` (`runtime_composition`); links and unlinks only `parent_of`
  between execution nodes (`runtime_relation`); attaches signals only to
  execution nodes. It never creates or edits artifacts.
- **Execution nodes**: only runtime creates an `agent` or `job` object;
  brain and user get `execution_node` (decisions 3, 4, 17 — a star comes from
  an execution fact, never from composition). Brain and user may still compose
  existing stars (category, payload, layout, visibility, links). `attention`
  signals are creatable by all three actors: runtime for execution facts, brain
  to point at something worth a look, user to mark something for themselves.
- **Execution truth**: only runtime changes `exec_state` or `work_ref`
  (`execution_truth`, decision 17).
- **Pins**: a `pinned_by_user` object is moved or resized by the user only
  (`pinned_by_user`), and never by a resolver placement even when a user
  command carries it. `pin`/`unpin` are user-only because the flag records a
  user decision and a brain `unpin` would bypass the protection.
- **Resolver** (`set_geometry` with `placed_by = resolver`) only places an
  unplaced object or nudges one it placed itself (`explicit_placement`,
  decision 9).
- `placed_by` becomes the actor (or `resolver`) whenever geometry changes; on
  creation it is the creating actor.

## Outcomes, revision and patches

`apply_scene_command(snapshot, command) -> SceneUpdate {outcome, snapshot, patch, reason}`.

| Outcome | When | Revision | Patch |
| --- | --- | --- | --- |
| `applied` | something changed | `+1` | yes |
| `duplicate` | nothing would change (replay, echo, unlink of an absent relation) | unchanged | no |
| `rejected_authority` | matrix or effect rule (`op_not_allowed`, `runtime_kind`, `runtime_composition`, `runtime_relation`, `execution_node`, `execution_truth`, `pinned_by_user`, `explicit_placement`) | unchanged | no |
| `invalid` | well-formed but inapplicable: `unknown_object`, `object_archived`, `kind_immutable`, `incomplete_object`, `unplaced`, `scene_full`, `relation_limit`, `relation_conflict` | unchanged | no |

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

## Bounds and wire form

| Bound | Value |
| --- | --- |
| active objects per snapshot | 512 — creation beyond is `invalid` (`scene_full`); archiving frees a slot |
| tombstones (`archived_ids`) | 4 096 — the oldest are dropped deterministically |
| relations per snapshot | 1 024 |
| ops per patch | 1 025 (an archive: the object plus all its relations) |
| payload | 16 KiB compact UTF-8 JSON |

Validation refuses what exceeds; nothing is silently truncated. Snapshot,
command and patch payloads carry `schema_version: 1`. Decoding checks the
version first and raises `UnsupportedSceneSchemaVersion` (a `ValueError`) for a
missing, unknown or newer version, then rejects unknown keys at every level,
missing stored keys, wrong types and unknown enum values; list lengths are
checked before decoding.

Validation:

```powershell
.venv/Scripts/python.exe -W error::ResourceWarning -m pytest -q -p no:cacheprovider tests/unit/test_scene_contracts.py
```
