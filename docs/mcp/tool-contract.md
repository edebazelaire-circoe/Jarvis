# MCP tool contract and catalog

Handoff `tasks/jarvis-mcp-semantic-batch-inspector/`, Slice 01 (contract).
**Status: target contract.** Slice 04 builds the catalog and typed schemas,
Slice 05 migrates `jarvis-display` to the target list (§6), Slice 06 exposes the
read-only Control Center catalog API, Slice 07 the inspector. Until then the
servers behave as documented in [../scene-model.md](../scene-model.md) › *Brain
tool mapping* and [../ARCHITECTURE.md](../ARCHITECTURE.md) › *Brain display MCP*.
Scene selection and batch semantics: [../scene-selection-batch.md](../scene-selection-batch.md).
Historical plan: [plan-outils-interface.md](plan-outils-interface.md).

## 1. Surfaces

| Server | Module | Tools today | Declared to the brain when | Reaches |
| --- | --- | ---: | --- | --- |
| `jarvis-display` | `jarvis/runtime/display_mcp.py:114` | 13 | `scene.enabled` true and Core target known (`control_center.py:759-770`) | Core `/v1/scene/*`, actor `brain` |
| `jarvis-console` | `jarvis/runtime/settings_mcp.py:59` | 3 | always (no switch: it carries the other switches, `control_center.py:611-614`) | Control Center settings API |
| `jarvis-barehands` | `jarvis/runtime/barehands_mcp.py:77` | 5 | `barehands.enabled` true (`control_center.py:775-779`) | Control Center `/api/barehands/commands` |
| `jarvis-drive` | `jarvis/runtime/drive_mcp.py:62` | 7 | never by Jarvis: registered by the operator (`claude mcp add … --scope user`, `docs/OPERATIONS.md:1139-1148`) | Google Drive |

Each native server is written to its own `--mcp-config` file at brain launch
(`claude_local.py:766-847`), conversation profile only; a change of switch takes
effect at the next brain (re)start.

## 2. Catalog descriptor

Every inspector-visible tool has exactly one descriptor. Fields:

| Field | Type | Source | Rule |
| --- | --- | --- | --- |
| `name` | str | introspection | wire name, e.g. `scene_update_many` |
| `server` | str | introspection | e.g. `jarvis-display` |
| `qualified_name` | str | derived | `mcp__<server>__<name>` (the CLI's name, `claude_local.py:216`) |
| `category` | enum §3 | metadata | exactly one |
| `label` | str ≤ 48 | metadata | French human label, e.g. « Masquer, réafficher, étiqueter un ensemble » |
| `summary` | str | introspection | first line of the tool description |
| `description` | str | introspection | full description as advertised |
| `input_schema` | JSON Schema | introspection | as advertised, after the strict hardening (`additionalProperties: false`, `display_mcp.py:2311-2315`) |
| `parameters[]` | list | derived from `input_schema` | per parameter: `name`, `type` (rendered), `required`, `default` (absent ≠ `null`), `constraints` (enum, min/max, min/maxLength, min/maxItems, pattern, nested object keys), `description` |
| `parameter_rules` | list[str] | metadata | cross-parameter rules JSON Schema does not carry here (e.g. "`select` XOR `object_ids`", "`include_hidden` only with `near`") |
| `output` | object | metadata + introspection | `{format, schema, notes}`, §5.2 |
| `side_effect` | `read` \| `write` \| `destructive` | metadata | §4.1 |
| `idempotent` | bool | metadata | same arguments twice ⇒ second is a no-op |
| `atomicity` | enum §4.2 | metadata | |
| `availability` | object | runtime, §4.3 | computed per request, never stored |
| `deprecation` | null \| `{replacement, removal_condition, since, legacy_doc}` | metadata | §7 |

The descriptor never contains: environment values, token or config file paths,
command lines, `mcp_config()` content, credentials, Drive ids, or any value read
from the user's Claude configuration.

## 3. Human categories

| `category` | Tab label | Tools |
| --- | --- | --- |
| `general` | Général | overview tab: servers, counts, availability, context budget, policies. Hosts cross-domain tools; **none today** — every native tool belongs to a domain |
| `scene` | Étoiles / Scène | all `jarvis-display` tools |
| `settings` | Réglages | `settings_describe`, `settings_get`, `settings_set` |
| `barehands` | Bare Hands | the five `barehands_*` tools |
| `external` | Externe | `jarvis-drive` (decision below) |

**`jarvis-drive` is shown, as `external`.** Its schemas are describable reliably:
`drive_mcp.build_server()` registers its seven tools without touching the Drive
backend (the backend is built lazily inside each tool, `drive_mcp.py:62-110`), so
introspection is safe. Its **availability is not provable** (user-scope CLI
registration outside Jarvis; reading the user's Claude config is forbidden), so it
is always `known`, `registration: "operator"`, `advertised: null` (unknown), and
the tab says so. Its untyped outputs are shown as such, not embellished. If the
module cannot be imported (optional Google dependencies), the category shows one
"descriptor unavailable" entry with the import error class — never a guess.

## 4. Classes and states

### 4.1 Side-effect class

| Class | Definition | MCP annotation (set at registration from the same metadata) |
| --- | --- | --- |
| `read` | changes no Jarvis, Core or external state. Writing a diagnostic artifact (capture PNG, journal line) does not count | `readOnlyHint: true` |
| `write` | changes state that the same surface can put back (hide ↔ show, pin ↔ unpin, link ↔ unlink, setting ↔ setting, UI mode) | `readOnlyHint: false, destructiveHint: false` |
| `destructive` | removes or overwrites state that the surface cannot restore (archive: tombstone, id never reusable; Drive delete / overwrite) | `readOnlyHint: false, destructiveHint: true` |

`idempotentHint` = descriptor `idempotent`; `openWorldHint` = true only for
`external`.

### 4.2 Atomicity note

| Value | Meaning |
| --- | --- |
| `none` | read tool |
| `single_command` | one Core scene command: all or nothing, at most one revision |
| `atomic_batch` | one selection command over a set: all or nothing, at most one revision ([scene-selection-batch.md](../scene-selection-batch.md) §4) |
| `single_request` | one Control Center request (settings write read back; Bare Hands command answered by the page within `COMMAND_DEADLINE_S`) |
| `external` | no Jarvis guarantee |

`best_effort` is not a value: no tool may advertise it after Slice 05.

### 4.3 Availability

Computed by the Control Center from what it already holds; **never by invoking
a tool, starting a server or reading user CLI config**. Three independent facts,
then one displayed state:

| Fact | Values | Definition | How it is proven |
| --- | --- | --- | --- |
| `condition` | setting id \| `null` | the switch that gates the server's declaration (static) | `jarvis-display` → `scene.enabled`; `jarvis-barehands` → `barehands.enabled`; `jarvis-console` → `null` (never gated); `jarvis-drive` → `null` (not declared by Jarvis) |
| `next_launch` | `configured` \| `disabled` \| `null` | whether the next brain launch will declare the server: `configured` = condition true (or none) **and** the server target exists; `disabled` otherwise; `null` for `jarvis-drive` (Jarvis never declares it) | current Control Center settings (`load_scene_gate`, `barehands.load`) + `ControlCenter.display_mcp` / `barehands_mcp` / `console_mcp` not `None`; a missing target is already journaled (`scene.display_mcp_unconfigured`, `barehands.mcp_unconfigured`) |
| `advertised` | `true` \| `false` \| `null` | the running brain process was launched with this server's `--mcp-config`; `null` when unknowable (`jarvis-drive`: user-scope registration outside Jarvis; any native server before Slice 06 adds its flag) | agent snapshot flags: `display_tools` exists (`claude_local.py:392`); Slice 06 adds `barehands_tools` and `console_tools` set from `barehands_args` / `console_args` exactly like `_display_tools_active` (`:748`); `false` when the brain is not running |

`pending_restart = advertised is not None and advertised != (next_launch == "configured")`
(the switch changed since the brain was launched; effective at next restart).

Displayed `state` — an enum, first rule that matches wins:

| Precedence | `state` | When |
| ---: | --- | --- |
| 1 | `advertised` | `advertised is true` |
| 2 | `configured` | `next_launch == "configured"` (not advertised now: brain stopped, or switch just turned on → `pending_restart`) |
| 3 | `disabled` | `next_launch == "disabled"` (an advertised server whose switch was just turned off stays `advertised` by rule 1, with `pending_restart: true`) |
| 4 | `known` | nothing else is provable (`jarvis-drive`: defined in code, `next_launch` and `advertised` both `null`) |

Every descriptor's tools are at least `known` (present in introspection of
`build_server(...)` with an inert target / fake backend); `known` is displayed
only when nothing more specific is provable.

Shape: `{state: "advertised"|"configured"|"disabled"|"known", condition: str|null,
next_launch: "configured"|"disabled"|null, advertised: bool|null,
pending_restart: bool}`. "Conditional" is not a state: the UI derives it from
`condition != null`. "Advertised" means declared to the CLI; what the CLI then
shows the model (deferred tool list) is observed only in traces (Slice 08), never
claimed by the catalog.

Deprecation is not an availability state: a deprecated tool is still `advertised`
and carries `deprecation`.

## 5. Source of truth, schemas, context

### 5.1 One source, parity-tested

- **Introspection is the source** of `name`, `description`, `input_schema`,
  `output_schema` (when structured) and annotations: `build_server(tools=Fake…)`
  (display, console, Bare Hands accept injected tools; `build_server(DisplayMcpTarget("127.0.0.1", 1, …))`
  already works in tests, `tests/unit/test_display_mcp.py:481`) and `list_tools()`.
- **One shared metadata module** (Slice 04, e.g. `jarvis/runtime/mcp_catalog.py`)
  holds what introspection cannot: `category`, `label`, `side_effect`,
  `idempotent`, `atomicity`, `parameter_rules`, `output.format`/text schemas,
  `deprecation`, server `condition`. **Registration consumes it** (annotations are
  derived from it at `@mcp.tool(annotations=…)`; mcp 1.30 supports `title`,
  `annotations`, `structured_output`).
- **Forbidden**: a hand-maintained tool list or schema copy in the frontend. The
  inspector JS renders what the API returns and contains no tool name literal
  (test: grep the inspector module).
- **Parity gates** (Slice 04): (1) metadata keys == introspected tool names, per
  server, both directions; (2) advertised annotations == derived from metadata;
  (3) the catalog builder's output == an in-memory client `tools/list`
  (`mcp.shared.memory.create_connected_server_and_client_session`) for every
  native server; (4) `TOOL_NAMES`, `READ_TOOL_NAMES`, `DISPLAY_TOOLS` derive from
  or are checked against the same metadata; (5) every documented output schema
  validates real outputs of fixture calls.

### 5.2 Output schema policy

| Tool family | `output.format` | Schema |
| --- | --- | --- |
| scene mutations, `settings_get`, `settings_set`, `barehands_*` | `structured` | concrete typed result (TypedDict / pydantic) → FastMCP `outputSchema` + `structuredContent`; replaces today's open objects (`dict[str, Any]` / `dict` advertise `{"type": "object", "additionalProperties": true}`) |
| `scene_inspect`, `scene_query`, `scene_get` | `json_text` | a JSON Schema of the **parsed text**, kept in the metadata module, **not** advertised. Today they return `str` with FastMCP's default structured output, so they already advertise `outputSchema {result: string}` and send the text twice (text block + `structuredContent.result`); **Slice 04 sets `structured_output=False` on these three** |
| `settings_describe` | `text_lines` | `{"type": "string"}` + a line grammar note: `- id · label = value [choices]`, optional `(lecture seule)` (`_describe_line`, `settings_mcp.py:787-795`) |
| `scene_capture` | `json_text+image` | schema of the JSON text block (`path`, `width`, `height`, `bytes`, `duration_ms`, `note`) + "PNG image block" |
| `drive_*` | `untyped` | whatever introspection yields; shown as untyped |

Decision for `inspect/query/get`: they stay compact, byte-budgeted JSON strings
(`MAX_INSPECT_BYTES` / `MAX_GET_BYTES` = 20 000, `display_mcp.py:148-155`).
Structured output would make FastMCP emit a second serialization and break the
budget and the row contract. Their schema describes the parsed text: header
object, `o` rows as positional arrays (`prefixItems`, one titled column each),
`r` rows, optional `truncated`. **The column list is defined once in code** and
both `OBJECT_ROW_LEGEND` (`display_mcp.py:2250`) and the schema derive from it,
so the legend the model reads and the schema the human reads cannot drift.

Refusals are **tool errors** (`isError`, text with `outcome`, `reason`, one
sentence), unchanged; output schemas describe success results only
(`applied` / `duplicate`).

Scene mutation result shapes (Slice 04 types, Slice 05 fills the batch ones):

| Shape | Fields |
| --- | --- |
| `SceneCommandResult` | `outcome` (`applied`\|`duplicate`), `revision`, `object_id?`, `relation_id?`, `command?`, `note?`, `scene_changed?`, tool extras (`scene_add_artifact`: `target_id`, `action`, `category`, `items`, `rule`, `ignored?`, `grouping_note?`) |
| `SceneBatchResult` | `op`, `outcome`, `revision`, `matched_count`, `changed_count`, `unchanged_count`, `skipped_count`, `matched_ids`, `changed_ids`, `unchanged_ids`, `skipped` [{id, reason}], `hidden_count` (always present when the selection has a `constellation` scope), `cascade_ids?`, `delta?` {requested, effective, clamped}, `pinned?`, `note?`, `scene_changed?`; id lists ≤ 20 (`MAX_BULK_REPORTED_IDS`) |

### 5.3 Model-context policy

- No catalog meta-tool (`list_tools`, `get_tool`, `describe_tools`…) is advertised
  to the model. Catalog helpers are Control Center functions and HTTP routes.
- The model-visible cost of a tool is measured as the bytes of `name` +
  `description` + `input_schema` (what the Messages API tool definition carries).
  Slice 04 records the baseline per server; Slice 05 and 08 must not exceed the
  baseline of `jarvis-display` without a written reason.
- **Slice 04 measures now** whether the Claude CLI forwards `outputSchema` (and
  annotations) to the model: one brain turn with the current servers, the CLI's
  request / debug trace inspected for the tool definitions. If it forwards them,
  their bytes count in the budget above and Slice 04 keeps typed output schemas
  only where they pay (mutations), catalog-side for the rest. Slice 08 re-checks
  on the final surface.
- Annotations are protocol-native and small; they are the only new per-tool
  metadata on the wire.
- Any prompt or description change updates the `claude_local` prompt fingerprint
  tests and `DISPLAY_TOOLS` (READINESS §3.3).

## 6. Target `jarvis-display` surface (Slice 05)

**13 tools stay 13**: `scene_set_visibility` goes, `scene_move` comes. One user
intent → one tool; one call → one Core command (reads: none).

| # | Tool | Intent | Domain command | Class / atomicity | Idempotent | Change vs today |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | `scene_inspect` | « qu'est-ce qui est affiché » | — | read / none | yes | output schema documented (json_text) |
| 2 | `scene_query` | find objects | — | read / none | yes | filters = `SceneSelection` filter fields: `connected` → `constellation`, + `kinds`, `exec_states`, `group`, `exclude`; constellation gains signal-owner edges |
| 3 | `scene_get` | read one object's content | — | read / none | yes | output schema documented |
| 4 | `scene_capture` | « regarde l'écran » | capture | read / none | yes (new file, same content) | output schema documented |
| 5 | `scene_create_object` | create a note, window, group | `upsert_object` | write / single_command | no (fresh id per call) | typed result |
| 6 | `scene_update_object` | edit **one** object: text, absolute place, shape, layer, visibility, label | `set_*` / `patch_object` | write / single_command | yes | typed result; keeps `visibility` (the QA live run showed the model reaches for it, `ARCHITECTURE.md:2093`) |
| 7 | `scene_update_many` | hide / show / fold / label / layer / recategorise **a set**, incl. « réaffiche tout » (`select {visibility: hidden}`, `visibility: visible`) | `patch_selection` | write / atomic_batch | yes | atomic; absorbs `scene_set_visibility` `scope=all_hidden`; bound 512; `confirm` guard kept |
| 8 | `scene_move` | « déplace la constellation / ces objets vers la gauche » | `translate_selection` | write / atomic_batch | **no** (relative) | **new**: `select`\|`object_ids`, `dx`, `dy`, `pin?`; returns requested vs effective delta |
| 9 | `scene_archive` | « supprime / archive » one or many | `archive_selection` | destructive / atomic_batch | yes (second call: `unchanged`) | atomic; bound 512 |
| 10 | `scene_pin` | pin / unpin one or many | `pin_selection` / `unpin_selection` | write / atomic_batch | yes | atomic; bound 512 |
| 11 | `scene_link` | relate two objects | `link` | write / single_command | yes (derived id → `duplicate`) | typed result |
| 12 | `scene_unlink` | remove a relation | `unlink` | write / single_command | yes | typed result |
| 13 | `scene_add_artifact` | file a finished work's result | `attach_artifact` | write / single_command | yes (grouping rule, merge without duplicates) | typed result |
| — | ~~`scene_set_visibility`~~ | — | — | — | — | **removed** (one object: #6; a set or everything hidden: #7) |

Why this cut: `scene_update_many` + `scene_set_visibility` covered the same
intent (show/hide a set) with two tools and two loops; translate is the one
missing intent (the page can already drag a group). Single-object edit stays
separate from set edits because it carries content and absolute geometry, which
are never batch changes. Merging pin into `scene_update_many` was rejected: pin is
a constraint command in the domain, and one call must stay one command.

Selectors on #2 and #7–#10 are exactly `SceneSelection`: `select` = filter mode,
`object_ids` = explicit mode (1–512), never both.

`jarvis-console`: unchanged, generic (`settings_describe/get/set`); typed outputs
only. Idempotent: all three (`settings_set` with the same value re-reads the same
state). The inspector may render per-setting rows from `settings_describe` data at
the catalog layer; no per-setting wire tool.

`jarvis-barehands`: the five tools unchanged. Idempotent: `barehands_activate`,
`barehands_deactivate`, `barehands_exit_overlay` yes (target state); `barehands_calibrate`,
`barehands_tutorial` no (each call (re)starts a guided flow). `jarvis-drive`:
`drive_search/get/read/update/delete/share` yes, `drive_create` no. `barehands_tutorial` is already
deprecated (opens calibration): descriptor `deprecation = {replacement:
"barehands_calibrate", removal_condition: see docs/legacy/barehands-tutorial-retirement.md
(next Bare Hands command-contract change, three tables in one commit),
legacy_doc: that file}`. Not removed here (no Bare Hands contract change in scope).

## 7. Migration and deprecation

Rules:

- A removed or renamed tool gets **no alias by default**. The only callers are the
  brain (fresh `tools/list` at every launch) and tests/docs. A resumed
  conversation (`--resume`) keeps its old system prompt (`claude_local.py:302-305`)
  and may name `scene_set_visibility`: the call fails with a visible unknown-tool
  error and the model has the new list — accepted, logged in Slice 08 traces.
- A temporary alias is allowed only with: a `deprecation` descriptor, a
  `docs/legacy/*.md` entry, a code comment, and a removal condition that is an
  observable event (not a date). It does not count toward the ≤ 13 target, and
  Slice 08 fails if one is still advertised after its removal condition is met.
- Removing a tool in Slice 05 updates, in the same change, every reference below.

Reference inventory at `ddcdb71` (outside `tasks/`; files only — Slice 05 greps
again before editing):

| Old name / key | Files |
| --- | --- |
| `scene_set_visibility` (tool, `scope=all_hidden`, `MAX_BULK_TARGETS`, `BULK_DEADLINE_S`) | `jarvis/runtime/display_mcp.py`, `jarvis/runtime/claude_local.py` (`BRAIN_DISPLAY_PROMPT`), `tests/unit/test_display_mcp.py` (whole `all_hidden` block: `test_show_all_hidden_unhides_everything_hidden_now_including_new_objects`, `test_show_all_hidden_counts_refusals_and_is_bounded`, `test_bulk_visibility_is_only_show_all`, `test_show_all_hidden_goes_through_the_mcp_schema`, `test_show_all_hidden_stops_at_its_deadline_and_reports_the_rest`, plus the schema-refusal case on `scene_set_visibility`), `tests/unit/test_scene_batch_tools.py`, `docs/scene-model.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, `docs/mcp/plan-outils-interface.md` |
| `scene_update_many` (semantics, `MAX_BATCH_TARGETS`, `atomicity: best_effort`) | `jarvis/runtime/display_mcp.py`, `jarvis/runtime/claude_local.py`, `tests/unit/test_scene_batch_tools.py`, `tests/unit/test_scene_query_tools.py`, `docs/scene-model.md`, `docs/ARCHITECTURE.md` |
| `scene_archive`, `scene_pin` (semantics, `MAX_DISPOSE_TARGETS`, best-effort loop) | `jarvis/runtime/display_mcp.py`, `jarvis/runtime/claude_local.py`, `jarvis/runtime/settings_mcp.py` (history docstring), `tests/unit/test_display_mcp.py`, `tests/unit/test_scene_capture.py`, `docs/scene-model.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, `docs/SECURITY.md`, `docs/mcp/plan-outils-interface.md` |
| `connected` selector key, `MAX_CONNECTED_DEPTH`, `_connected_ids` | `jarvis/runtime/display_mcp.py`, `tests/unit/test_scene_query_tools.py`, `tests/unit/test_scene_batch_tools.py`, `docs/scene-model.md`, `docs/ARCHITECTURE.md` (Brain display MCP section) |
| tool-name lists (`TOOL_NAMES`, `READ_TOOL_NAMES`, `DISPLAY_TOOLS`) | `jarvis/runtime/display_mcp.py`, `jarvis/runtime/claude_local.py`, `tests/unit/test_scene_query_tools.py` (asserts 11: stale), `tests/unit/test_scene_capture.py` (asserts no archive/pin tool: stale), `tests/unit/test_scene_artifacts.py`, `tests/unit/test_display_mcp.py` |
| prompts naming tools | `jarvis/runtime/claude_local.py`, `jarvis/runtime/prompt_catalog.py`; tests pinning them: `tests/unit/test_display_mcp.py`, `tests/unit/test_scene_query_tools.py`, `tests/unit/test_scene_settings.py`, `tests/unit/test_scene_artifacts.py`, `tests/unit/test_scene_renderer_logic.py`, `tests/unit/test_barehands_command_channel.py` |

The stale tests above are realigned by their owning slice (READINESS §5 H2).

## 8. Control Center catalog API (shape for Slice 06)

Read-only, no execution route.

| Route | Returns |
| --- | --- |
| `GET /api/mcp/tools` | `{servers: [{server, category, condition, availability, tool_count}], tools: [{server, name, category, label, summary, side_effect, atomicity, availability.state, deprecated}]}`, deterministic order: category order of §3, then server, then registration order |
| `GET /api/mcp/tools/{server}/{name}` | the full descriptor (§2); unknown → 404 with a stable code `mcp_tool_unknown` |

Built from introspection + metadata at request time (cached per process, keyed
by nothing user-controlled); availability recomputed per request. Errors follow
the Control Center error contract (`send_error_response`), and the inspector
shows them.

## 9. Open points

- Whether the Claude CLI forwards `outputSchema` / annotations to the model:
  measured by Slice 04 (§5.3), re-checked by Slice 08.
- `jarvis-drive` import without Google dependencies: verified by Slice 04; the
  "descriptor unavailable" fallback of §3 applies otherwise.
- `drive_update` idempotency key (`drive_mcp.py:100`): already filed in
  `tasks/jarvis-mcp-semantic-batch-inspector/Issues/01-*`; out of scope.
