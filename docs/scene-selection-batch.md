# Scene selection and atomic batches

Handoff `tasks/jarvis-mcp-semantic-batch-inspector/`, Slice 01 (contract).
**Status: target contract.** Nothing here is implemented at Slice 01. Slice 02
implements `SceneSelection` and the canonical constellation, Slice 03 the atomic
selection commands (reducer, Core, wire, page drag), Slice 05 the `jarvis-display`
migration. Until each lands, the current behaviour described in
[scene-model.md](scene-model.md) › *Brain tool mapping* stays true (best-effort
per-object loops in `display_mcp.py`). MCP tool surface and catalog:
[mcp/tool-contract.md](mcp/tool-contract.md).

Mental model: `intent (user / brain / page / future Bare Hands) → SceneSelection →
one selection command → Core resolves + validates + applies on one snapshot → one
ScenePatch / one revision, or a refusal with none`.

The Python domain (`jarvis/domain/scene.py` or an adjacent `scene_selection.py`)
is authoritative.

> **Implementation facts (Slice 02, 2026-09-25)** — §1–§3 resolution and §2 are
> implemented in `jarvis/domain/scene_selection.py`: `SceneSelection`
> (`from_payload` / `to_payload`, canonical form emits the plural `kinds` /
> `exec_states`), `ConstellationScope`, `NearScope`, `constellation_of(snapshot,
> root, depth=None)`, `resolve_selection(snapshot, selection, *,
> require_placed=False) -> SelectionResolution` (`matched_ids`, `skipped`,
> `refused`, `archived_ids`, `hidden_count`, `eligible_ids`,
> `refusals(archived_ok=)`, `reason(archived_ok=)`), constants
> `MAX_SELECTION_IDS`, `MAX_CONSTELLATION_DEPTH`. New refusal token
> `SceneRefusal.INVALID_SELECTION` (`group` reference that is not a group).
> Shared parity fixtures: `tests/fixtures/scene_constellation_cases.json`
> (Python `tests/unit/test_scene_constellation.py`, JS `constellationOf` by
> node in the same file); selection tests `tests/unit/test_scene_selection.py`.
> The filter predicates (`text_matches`, `work_matches`, `box_distance`) now
> live in that module and `display_mcp.py` imports them; its selectors and
> `_connected_ids` are otherwise unchanged until Slice 05. Not wired into any
> command yet (Slice 03). The browser keeps local copies only for instant UX, pinned by
shared fixtures (see *Parity*).

> **Implementation facts (Slice 03, 2026-09-25)** — §3–§5 are implemented.
> `SceneOp.PATCH_SELECTION` / `TRANSLATE_SELECTION` / `PIN_SELECTION` /
> `UNPIN_SELECTION` / `ARCHIVE_SELECTION` (wire `patch_selection`,
> `translate_selection`, `pin_selection`, `unpin_selection`,
> `archive_selection`; set `SELECTION_OPS` in `jarvis/domain/scene.py`).
> `SceneCommand` gains `selection` (`SceneSelection`), `changes`
> (`SelectionChanges`), `delta` (`SceneDelta`) and `pin` (`true` only); wire
> `{"op": "translate_selection", "selection": {...}, "delta": {"dx", "dy"}, "pin": true}`.
> Planners, report and group clamp live in `jarvis/domain/scene_batch.py`
> (`apply_selection_command`, `SceneBatchReport`, `BatchDelta`, `group_delta`),
> reached from `apply_scene_command`; they reuse `_plan_object_write`,
> `_with_cascade` and `_archive_ops` (same per-field authority, same cascade).
> `SceneUpdate.batch` is the report; `scene_wire.command_body` adds it as
> `batch` (absent for other ops); `cascade_ids` is emitted for
> `archive_selection` only, `delta` for `translate_selection` only; a
> member-level refusal entry omits `field` in filter mode. With no placed member
> a translate reports `effective {0, 0}`, `clamped: false`. `clamped` is true
> only when the bound cut the requested delta before rounding (`group_clamp`;
> `2.37 → 2.3` and `0.05 → 0` are not clamped; the page's `groupDelta` returns
> the same flag). Selection planners are `_plan_*_selection`; pin/unpin reuse
> the single-object `_plan_pin` per member. The Control Center
> proxy (`CoreSceneView.command`, `_LARGE_PATCH_OPS`) relays these commands with
> `patch_omitted`. `parse_enum` names `SceneOp` instead of listing its 18 values
> (bounded message). Page: `groupDelta` / `groupMove` / `commitTranslation`
> in `control_center_scene_interact.js` (parity with `group_delta` tested),
> used by `commitGroupMove` in `control_center_scene_page.js`. Tests:
> `tests/unit/test_scene_batch.py`, `tests/unit/test_scene_group_drag_js.py`,
> selection branch of the parity generator in
> `tests/unit/test_scene_transport_client.py`, `tests/integration/test_scene_transport.py`.

## 1. SceneSelection

A strict, serializable domain value. Two mutually exclusive **modes**:

- **explicit** — `ids` given, no filter field;
- **filter** — at least one filter field, no `ids`.

Reason for exclusivity: explicit ids and filters follow different ineligibility
rules (§3); mixing them would make the rule ambiguous. Same rule as today's
`select` XOR `object_ids` (`display_mcp.py:1003`, `:1124`).

### 1.1 Fields

| Field | Type | Domain / bounds | Match rule |
| --- | --- | --- | --- |
| `ids` | list[str] | 1–`MAX_SELECTION_IDS` (= 512), unique, each `check_id` | exactly these objects |
| `kind` | str | `SceneObjectKind` | `item.kind == kind` |
| `kinds` | list[str] | 1–6 unique `SceneObjectKind` | `item.kind in kinds` |
| `category` | str | `check_token`, ≤ 32 | case-insensitive equality (as `_select`, `display_mcp.py:1580`) |
| `origin` | str | `runtime` \| `brain` \| `user` | `item.origin == origin` |
| `visibility` | str | `visible` \| `hidden` | `item.visibility == visibility` |
| `exec_state` | str | `ExecState` | `item.exec_state == exec_state` |
| `exec_states` | list[str] | 1–8 unique `ExecState` | `item.exec_state in exec_states` |
| `text` | str | 1–160 chars (`MAX_FILTER_CHARS`) | case-insensitive substring of title, id or annotation (`_text_matches`, `display_mcp.py:593`) |
| `work` | str | 1–160 chars | `source`, `external_id`, `work_id` or `source:external_id`, exact (`_work_matches`, `:623`) |
| `explains` | str | active object id | objects with an `explains` relation **to** it (`:1566-1569`) |
| `constellation` | `{object_id, depth?}` | root active; `depth` int 1–6 | member of the canonical constellation (§2) |
| `group` | str | active object of kind `group` (else `invalid / invalid_selection`) | `to_id` of every `groups` relation whose `from_id` is this object; the group itself is **not** included |
| `near` | `{object_id, radius}` | reference active **and placed** (unplaced reference → `invalid / unplaced`); `radius` finite, 0–100 000 | edge-to-edge distance ≤ radius; reference, unplaced objects excluded; hidden excluded unless `include_hidden` or a `visibility` filter (`:1596-1600`) |
| `include_hidden` | bool (strict) | only with `near` | see `near` |
| `exclude` | list[str] | 1–32 unique active ids; filter mode only | removed from the result after every filter |

Decisions:

- **`kind`/`kinds`, `exec_state`/`exec_states`**: the singular is sugar for a
  one-element list; giving both is a validation error. `exec_states` exists
  because "archive/hide finished work" is four terminal states
  (`TERMINAL_EXEC_STATES`, `scene.py:1495`); without it, one intent = four calls.
- **`connected` is renamed `constellation`** (object `{object_id, depth?}`, same
  shape as today's `ConnectedArg`, `display_mcp.py:2358`). No alias: selectors are
  never persisted by any caller; only prompts, tests and docs name the key
  (inventory in [mcp/tool-contract.md](mcp/tool-contract.md) §7).
- **`group`** is new: "hide the members of this group" is a real intent, and
  `constellation` on a group also takes everything linked to each member.
- **`exclude`** is the only negation, bounded to 32 ids, for "everything except
  this" ("masque tout sauf ça"). Excluded ids must be active objects (a typo must
  not silently keep the wrong object) → otherwise `invalid / unknown_object` or
  `object_archived`.
- No boolean DSL, no OR across fields, no negated filter besides `exclude`.
- There is no "all" field: "everything" is `kinds` with the six kinds.

### 1.2 Composition

- **AND across fields, OR within a list field** (`kinds`, `exec_states`).
- `constellation`, `near`, `explains` and `group` are each computed on the
  **whole active snapshot**, then intersected with the other filters (e.g.
  `constellation` + `kind: artifact` = the artifacts of that constellation, even
  when the path to them goes through stars).
- `exclude` applies last.
- Filters never exclude hidden objects, except `near` (rendering-based, current
  rule kept).

### 1.3 Deterministic order

The resolved member list has one canonical order, used for the report and for
the order of patch ops:

1. explicit mode: the caller's order. Duplicate `ids` are refused at decode
   (domain and wire); the MCP adapter de-duplicates `object_ids` (first
   occurrence kept) before building the selection (Slice 05), as it does today
   (`dict.fromkeys`, `display_mcp.py:1152`);
2. filter mode with `near`: ascending distance, ties by snapshot order;
3. filter mode with `constellation` (and no `near`): constellation order (§2.4);
4. otherwise: snapshot object order (`SceneSnapshot.objects`, the replay order).

Read tools may re-sort for presentation (`scene_query` sorts brain, user,
runtime for its byte budget, `display_mcp.py:1608`); that is a projection, not
the selection order.

### 1.4 Size bound

**One bound: `MAX_SELECTION_IDS = MAX_SCENE_OBJECTS = 512` members**, for every
actor and every selection command. It replaces today's 32 (`MAX_BATCH_TARGETS`,
`display_mcp.py:173`), 128 (`MAX_DISPOSE_TARGETS` / `MAX_BULK_TARGETS`, `:162`,
`:180`) and coincides with 512 (`MAX_ARCHIVE_MANY_IDS`, `scene.py:94`).

- A filter selection can never exceed it: a snapshot holds at most 512 active
  objects (`scene.py:81`). The bound only bites on explicit `ids`.
- **Patch size is safe by construction**: a selection command emits at most one
  `put_object` or `archive_object` per member and cascade signal (each an active
  object, ≤ 512 total) plus one `delete_relation` per relation touched
  (≤ `MAX_SCENE_RELATIONS` = 1 024) → ≤ `MAX_PATCH_OPS` = 1 536 (`scene.py:92`).
  The planner asserts it; no refusal token is needed.
- The **wire** bound still holds: a command body ≤ 64 KiB
  (`scene_wire.MAX_SCENE_COMMAND_BYTES`). 512 ids of 128 chars do not fit;
  such a command is refused before sending (`payload_too_large`, nothing sent).
  An atomic batch is never split into chunks: use a filter instead.
- The 15 s bulk deadline (`BULK_DEADLINE_S`) disappears with the loops: one
  command, one `COMMAND_TIMEOUT_S` bound.
- `MAX_GET_IDS` (8) is a read/context budget, not a selection bound; unchanged.

### 1.5 Validation errors (decode time)

Refused before any snapshot is read (Core: 400; MCP: `invalid_argument`,
"nothing sent"): unknown key; both modes or neither; empty or duplicate list;
list over its bound; `kind`+`kinds` or `exec_state`+`exec_states` together;
enum value unknown; string empty or over bound; `depth` outside 1–6 or not a
strict int; `radius` not finite or outside 0–100 000; `include_hidden` without
`near`; `exclude` in explicit mode. References (`constellation.object_id`, `near.object_id`, `explains`,
`group`, `exclude[]`) are checked against the snapshot at resolution (§3), not
at decode.

Wire form (inside a command, key `selection`):

```json
{"constellation": {"object_id": "codex:42"}, "kinds": ["artifact", "attention"]}
{"ids": ["brain-artifact-1a2b", "codex:42"]}
```

## 2. Canonical constellation

`constellation_of(snapshot, root, depth=None) -> tuple[str, ...]`, pure, in the
domain. Same word, same set, for MCP, page and future Bare Hands.

### 2.1 Graph

- Nodes: active objects only. Archived objects are not in the snapshot and no
  relation can touch them (`scene.py:771-773`), so they never participate.
- Edges, **undirected**:
  1. every `SceneRelation` in the snapshot, whatever its kind and direction;
  2. a **virtual edge signal → owner** for every entry of
     `signal_owners(snapshot)` whose owner is not `None` (`scene.py:1498-1526`):
     live signal → its star; retired signal (no link) → the first execution node
     with the same `(source, external_id)` work. This is what today's MCP
     `_connected_ids` lacks (`display_mcp.py:600-620`) and the page already does
     (`constellationOf`, `control_center_scene_interact.js:454-471`).
- Duplicate edges (a live signal's relation and its virtual edge) are harmless.

### 2.2 Hidden objects

**Included.** Hiding is not archiving (Decision 13): "show this constellation
again" must find its hidden members, and today's MCP already includes them. The
page's `selectConstellation` filter to rendered nodes
(`control_center_scene_page.js:2663`, `.filter(memberId=>nodes.has(memberId))`)
is a **UI projection** — you cannot drag what is not drawn — and stays in the
page, documented as such; it never feeds a domain command as "the
constellation".

### 2.3 Depth

- Absent: the whole connected component (the page's only mode today).
- Present: integer 1–6 (`MAX_CONNECTED_DEPTH`, `display_mcp.py:188`, kept);
  counts hops, a virtual signal edge counts one hop. 1 = root + direct
  neighbours. Why 6: current MCP contract; beyond it a scene figure is in
  practice the whole component, and the bound keeps the schema honest.

### 2.4 Order

Root first, then **breadth-first discovery order**. Adjacency is built by
walking `snapshot.relations` in order (each relation appends `to` to `from`'s
list and `from` to `to`'s), then `signal_owners` in snapshot object order;
neighbours are visited in list order. This is exactly the page's algorithm
(`tie()` over `state.relations` then `signalOwners`); both keep insertion order
across patches (`apply_scene_patch` keeps a replaced object/relation in place,
`scene.py:1112-1149`; JS `Map.set` does too).

Root unknown or archived → the selection is refused (`invalid / unknown_object`
or `object_archived`), like today's `_require_reference` (`display_mcp.py:1538`).
An isolated root yields `[root]`.

### 2.5 Parity

- Python is the source. The page keeps `constellationOf` for instant selection.
- Slice 02 adds **shared fixtures** (one JSON file of `{snapshot, root, depth?,
  expected}` cases) run by a Python test against `constellation_of` and by a
  node-driven pytest against `constellationOf` (depth-absent cases), plus the
  first unit test of `constellationOf` (it has none today). Mandatory cases:
  both directions of each relation kind; live signal; retired signal found by
  work fallback; orphan signal (owner `None`) stays alone; hidden member
  included; depth 1 and 2; order.
- `signalOwners` parity with `signal_owners` already exists; kept.

## 3. Resolution and eligibility

Resolution happens **inside the reducer, on the exact snapshot it mutates**
(Core `SceneService._apply_serialized`, under its lock, `core/scene_service.py:273-304`).

### 3.1 Today's per-object refusal reasons, and their batch rule

Inventory of `SceneRefusal` (`scene.py:1169-1218`) as they can arise for a
selection command issued by `brain` or `user`:

| Reason | Where today | Batch rule |
| --- | --- | --- |
| `op_not_allowed` | matrix, `scene.py:1294` | whole command `rejected_authority` (runtime has no selection op) |
| `unknown_object` | `_require_active` `:1345`, `_plan_object_write` `:1375` | explicit id or any reference → whole command `invalid`, `refused` lists it |
| `object_archived` | same | explicit id or reference → whole command `invalid`; **except `archive_selection`**: an explicitly named, already archived id is `unchanged` (as `_plan_archive` `:1622` and `archive_many` `:1641`) |
| `unplaced` | `_plan_pin` `:1486` | pin / translate only. Explicit id → whole command `invalid`. Filter member → **skipped** and reported (§3.2) |
| `pinned_by_user` | `_check_write_authority` `:1430` | **never arises**: a pin resists only `placed_by=resolver` (`scene.py:1424-1431`, 19/09/2026 rule). Selection commands never carry `resolver`, so pinned objects are updated, moved, pinned, archived like others |
| `explicit_placement`, `resolver_actor` | `:1432-1437`, `:1461` | never arise (no resolver placement in selection commands) |
| `execution_truth` | `:1418-1421` | never arises: `exec_state` / `work_ref` are not batch changes |
| `kind_immutable`, `incomplete_object`, `scene_full`, `execution_node`, `reserved_id` | creation paths | never arise: selection commands never create |
| `relation_*`, `runtime_owned`, `signal_shape` | link / unlink | never arise: selection commands never link; archive deletes relations by cascade, which is allowed today |
| `not_bulk_archivable` | `archive_many` `:1646` | only `archive_many` (unchanged, §5.4); not a rule of `archive_selection` |
| `runtime_kind/composition/relation/origin` | runtime paths | never arise (runtime is refused first) |
| `revision_exhausted` | `:1302` | whole command `invalid` |
| `payload_too_large` | `patch_selection` (Slice 03 review, 2026-09-25) | a member whose payload would exceed `MAX_PAYLOAD_BYTES` (16 KiB) once `annotation` is merged → whole command `invalid`, in **both** modes, offenders listed (never a 400, nothing persisted) |

### 3.2 Explicit ids vs filters

| Case | Explicit mode | Filter mode |
| --- | --- | --- |
| id / reference unknown | refuse all, `unknown_object` | a reference (`constellation`, `near`, `explains`, `group`, `exclude`) unknown → refuse all |
| archived | refuse all, `object_archived` (archive: `unchanged`) | cannot match (not in snapshot); archived reference → refuse all |
| member ineligible for the op (`unplaced` for pin / translate) | refuse all, `unplaced`, ids listed | **skip** the member, report `{id, reason: "unplaced"}` |
| annotation would overflow the member's payload (`patch_selection`) | refuse all, `payload_too_large`, ids listed | **refuse all** too, `payload_too_large` (no `field`): skipping would silently leave the member un-annotated |
| member already in target state | `unchanged` | `unchanged` |
| pinned by user | eligible | eligible |
| hidden | eligible | eligible (except `near` default) |

Reasons. Explicit: the caller named the object; dropping it silently would lie
about what was done (same stance as `archive_many`, `scene.py:1630-1638`).
Filter: the caller named a *set*, and "unplaced" is a transient state owned by
the AutoResolver (Decision 9) with no selector to exclude it; skipping is
deterministic, computed before any mutation, and always reported — it is not
best-effort. Any future op-level ineligibility must be added to this table
before code.

## 4. Atomic batch semantics

For every selection command:

1. decode + validate (§1.5) — refusal: 400 / `invalid_argument`, nothing read;
2. authority matrix (`ALLOWED_SCENE_OPS`);
3. resolve the selection on the snapshot (§1–§3) and evaluate **all** references
   and members — never stop at the first problem. `refused` lists every offending
   id in canonical order: references first (`constellation` root, `near`,
   `explains`, `group`, then `exclude` ids, in that order), then explicit members
   in the caller's order. The command-level `reason` is the reason of the first
   entry. Implemented by Slice 02 as `SelectionResolution.refusals(archived_ok=)`
   / `.reason(archived_ok=)` (`jarvis/domain/scene_selection.py`); when a
   reference fails, filter members are not evaluated (the set is undefined);
4. plan every member; any member-level refusal refuses the whole command, with
   the same listing rule;
5. if no member changes → `duplicate`, **no revision, no patch**;
6. else **exactly one `ScenePatch`**, `revision + 1`, ops in canonical member order
   (cascade signals before their star, as `_with_cascade`, `scene.py:1605`).

Never `best_effort`, never partial, never several revisions. A refused command
leaves the revision untouched (Decision 20, `scene.py:38-39`).

### 4.1 Result (domain `SceneBatchReport`, on the wire as `batch`)

`SceneUpdate` gains `batch: SceneBatchReport | None`, present exactly for
selection commands (applied, duplicate or refused). Core's command response
carries it as `batch` next to `outcome`, `reason`, `revision`, `patch`.

| Field | Type | Meaning |
| --- | --- | --- |
| `mode` | `explicit` \| `filter` | |
| `matched_ids` | list[str] | resolved members, canonical order (after `exclude`); for `archive_selection`, explicit ids already archived are included (as `unchanged`) at their place in `ids` order — Slice 03 merges Slice 02's `archived_ids` back in `selection.ids` order |
| `hidden_count` | int | matched members that are hidden (Slice 02 `SelectionResolution.hidden_count`) |
| `changed_ids` | list[str] | members the patch rewrites (any field, position or pin flag) |
| `unchanged_ids` | list[str] | members already in the target state |
| `skipped` | list[{id, reason}] | filter-mode members excluded by §3.2 |
| `refused` | list[{id, reason, field?}] | offending ids / references; non-empty only when refused |
| `cascade_ids` | list[str] | archive only: runtime signals taken along |
| `delta` | {requested:{dx,dy}, effective:{dx,dy}, clamped: bool} | translate only |

Invariants: when applied or duplicate, `changed ∪ unchanged ∪ skipped.id` =
`matched`, pairwise disjoint; `outcome = applied` ⇔ `changed_ids` non-empty; a filter matching nothing → `duplicate` with empty
lists (truthful no-op, the adapter adds a one-line note). The domain report is
complete (≤ 512 ids per list); the MCP result caps each id list at
`MAX_BULK_REPORTED_IDS` (20) with exact counts (§6).

## 5. Operations

New `SceneOp` values (Slice 03). Names follow the existing verb style; the
matrix needs no edit: `ALLOWED_SCENE_OPS` gives `brain` and `user` every op
(`scene.py:274-280`) and `runtime` an explicit subset that excludes them.

| Op | Required args | Optional | Effect per member |
| --- | --- | --- | --- |
| `patch_selection` | `selection`, `changes` | — | apply `changes` |
| `translate_selection` | `selection`, `delta` `{dx, dy}` | `pin` (only `true`) | move by the common effective delta |
| `pin_selection` | `selection` | — | `pinned_by_user = true` |
| `unpin_selection` | `selection` | — | `pinned_by_user = false` |
| `archive_selection` | `selection` | — | archive, star takes its runtime signals |

Authority per actor:

| Op | runtime | brain | user |
| --- | --- | --- | --- |
| all five | ✘ `op_not_allowed` | ✔ | ✔ |

Consistent with current truth: the brain has the user's hand, pin and archive
included (`scene.py:263-273`); the docstring at `scene.py:31` ("seul `user`
archive") is stale and Slice 03 fixes it.

### 5.1 `patch_selection`

`changes` is a strict object, at least one key:

| Key | Type | Notes |
| --- | --- | --- |
| `visibility` | `visible` \| `hidden` | |
| `representation` | `point` \| `capsule` \| `window` | no geometry change (as today's batch, `display_mcp.py:1064`) |
| `category` | token ≤ 32 | |
| `layer` | int 0–1000 | |
| `order` | int ±1 000 000 | |
| `annotation` | str ≤ 60, one printable line, `""` removes | merged into the current payload; title/summary/items untouched |

Not batchable, by design: `title`, `summary`, `items` (no real intent sets the
same content on many objects), `geometry` (absolute: use translate), `exec_state`,
`work_ref`, `kind`. Same authority per field as `_plan_object_write`
(`scene.py:1354-1408`). The MCP adapter keeps its **hide guard** (`confirm` when
hiding ≥ half of the visible objects, ≥ 3; `display_mcp.py:1286-1296`) as an
advisory pre-check computed with the **domain resolver** on the snapshot it
already reads; nothing is sent when it trips. It is a brain-safety heuristic, not
a domain rule.

### 5.2 `translate_selection` (rigid group move)

- `delta.dx`, `delta.dy`: finite numbers, |value| ≤ 100 000 (`MAX_SCENE_EXTENT`).
  `(0, 0)` is refused at decode (invalid argument: a move of nothing is a caller
  bug, not a no-op).
- Members: resolved selection; unplaced members per §3.2 (explicit → refuse all;
  filter → skipped). Placed members form the group, **hidden members included**:
  they are in the group's bounding box and move with it (a hidden member is still
  part of the figure and reappears at its moved place).
- **One common effective delta**, never a per-member clamp. Bounds `B` =
  `SCENE_SAFE_AREA` (`scene.py:116`) **widened to include the group's current
  bounding box** (never-worse rule: a group already outside is never forced to
  move, and can never be pushed further out). Per axis, with the group bbox
  `[x0, x1]`: `effective = clamp(requested, min(0, B.x0 - x0), max(0, B.x1 - x1))`;
  same for y. Clamp per axis (not a proportional scale): it keeps the most
  movement and matches a single-object drag against a wall. Consequence: a group
  wider (taller) than the safe area cannot move on that axis at all (its widened
  `B` equals its own bbox there); the other axis still moves.
- `effective` is quantised to 0.1 unit **toward zero** (the page's `QUANTUM`, so
  the result never crosses a bound); every member: `x += edx`, `y += edy`, size
  unchanged, `placed_by = actor`. Relative offsets are exactly preserved.
- `requested`, `effective`, `clamped` are returned (`delta` in the report).
- a requested non-zero delta clamped to `effective == (0, 0)` with no pin change
  → `duplicate` (`clamped: true` in the report).
- `pin: true` also sets `pinned_by_user` on every placed member in the same
  patch. It exists for the page: a user drag pins what it moves today
  (`geometrySteps`, `control_center_scene_interact.js:820-823`); with the flag the
  drag stays one revision instead of two to three commands per object.
- Pinned members move (explicit command). Domain coordinate bounds (±100 000)
  hold because `B` ⊂ bounds or never-worse.
- **Page drag (decision).** Today each carried member's drop is converted by
  `placeOf` (`control_center_scene_page.js:2062-2074`, `:2494-2496`), which
  "unturns" an orbiting member (`L.orbitTrack`, `control_center_scene_layout.js:899`;
  `L.orbitUnturn`) so its stored place matches where the rotating field drew it.
  That is per-member and breaks the common delta. **For a multi-object drag,
  `delta` = the pointer displacement converted to scene units (`I.pxToUnits`),
  with no per-member orbit unturn and no per-member clamp**; the preview uses the
  same group clamp as the domain. Orbiting members therefore re-seat visibly on
  their orbit after the drop (their stored place moved by exactly `delta`; the
  field keeps turning them) — accepted: rigid stored offsets beat a per-member
  correction that would silently deform the figure. **A single-object drag keeps
  today's behaviour** (`placeOf` unturn, `orbitClamp`, `commitUserGeometry`).

### 5.3 `pin_selection` / `unpin_selection`

`_plan_pin` per member (`scene.py:1481-1489`): already pinned/unpinned →
`unchanged`; pinning an unplaced member → §3.2.

### 5.4 `archive_selection` and `archive_many`

- `archive_selection` archives every member with the existing cascade
  (`_with_cascade` + `_archive_ops`, `scene.py:1588-1616`): each execution star
  takes its runtime signals, every relation touching an archived object is
  deleted once. No content rule: active, hidden, pinned, running work included —
  exactly the reach of today's `scene_archive` (`display_mcp.py:1243-1257`),
  now in one revision. Explicitly named ids already archived → `unchanged`.
- `archive_many` **stays unchanged**: the page's "archive finished work" flow
  (`bulkSelection`, confirmed count) whose content rule `bulk_archivable`
  (`scene.py:1540-1567`) is the point. It is not deprecated in this task; its
  refusal `not_bulk_archivable` is not a rule of `archive_selection`.
- A signal already in the selection and also a cascade member appears once
  (`matched_ids`, not `cascade_ids`).

## 6. MCP and page consumers (implemented later)

- **MCP (Slice 05)**: each selection-native tool builds one `SceneSelection` from
  `select` (filters) or `object_ids` and sends **one** command; no per-target
  loop, no `atomicity` field, no `remaining` / `deadline_reached`. The result is
  the report with id lists capped at 20 (`*_count` exact), `outcome`, `reason`,
  `revision`, `scene_changed` hint. When the selection has a `constellation`
  scope, the result always carries `hidden_count` (members hidden on screen), so
  the brain can say "including N hidden" instead of promising what is visible. A transport failure is one tool error
  ("outcome unknown, re-read the scene"), never a partial count. Target tool list:
  [mcp/tool-contract.md](mcp/tool-contract.md) §6.
- **Page (Slice 03)**: the multi-object drag commits **one**
  `translate_selection` (`ids` = carried members with a committed geometry,
  `delta` = the previewed common delta, `pin: true`) instead of one
  `commitUserGeometry` per member (`control_center_scene_page.js:2491-2501`);
  one optimistic layer, one revision, one refusal path. Unplaced carried members
  (no committed geometry) are not sent: after the drop they **snap back** to the
  resolver's place (logged `scene.user_drag_unplaced_skipped`), which is visible
  and honest — the resolver owns unplaced objects (Decision 9). A single-object drag or a resize keeps its
  current path. The Control Center proxy's `patch_omitted` relay for
  `archive_many` (scene-model.md › *Bulk archive answer*) extends to selection
  commands.
- **Bare Hands**: no new binding in this task; a future group move uses
  `translate_selection` (debt noted in `docs/barehands-contracts.md:3771-3774`).

## 7. Tests required by this contract (owners)

| Claim | Slice |
| --- | --- |
| field validation, composition AND/OR, order, `exclude`, `group`, plural kinds/states | 02 |
| constellation: undirected, signal fallback, archived excluded, hidden included, depth, order, JS fixtures parity | 02 |
| failed batch leaves revision untouched; applied batch = exactly +1 and one patch; all-no-op = duplicate | 03 |
| explicit vs filter ineligibility table (§3.2), archived explicit id in archive | 03 |
| translate: offsets preserved, common delta, never-worse clamp, quantisation, pin flag, unplaced | 03 |
| JS applier parity on selection patches; page drag = one command | 03 |
| one MCP call → one Core command POST → one revision; no `best_effort` | 05 |
