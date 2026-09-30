# MCP tool contract and catalog

Handoff `tasks/jarvis-mcp-semantic-batch-inspector/`, Slice 01 (contract).
**Status: catalog, shared metadata and typed schemas implemented by Slice 04
(§10); `jarvis-display` migrated to the target list (§6) by Slice 05 (§10.5).**
Slice 06 exposed the read-only Control Center catalog API (§10.6), Slice 07 the
inspector (§10.7). Server behaviour: [../scene-model.md](../scene-model.md) › *Brain
tool mapping* and [../ARCHITECTURE.md](../ARCHITECTURE.md) › *Brain display MCP*.
Scene selection and batch semantics: [../scene-selection-batch.md](../scene-selection-batch.md).
Historical plan: [plan-outils-interface.md](plan-outils-interface.md).

**Amendment `jarvis-generic-mcp-plugin-runtime` (Slice 01, 2026-09-30).
Status: implemented (Slices 02–08; release facts in §10.10). Implemented by
Slice 04: `jarvis-tools` in the catalog (§1, §3, §5.3), the external descriptor
and the merged `GET /api/mcp/tools` (§2, §8), the plugin availability fact
(§4.3). Implemented by Slice 05: `jarvis-tools` declared to the Claude
conversation brain and to Codex, `advertised` from both snapshots.
Implemented by Slice 06: the plugin management routes and the OAuth callback
of the Control Center (§8, §10.6) and the « Plugins externes » tab of the MCP
dialog (§10.7).** Managed
external MCP plugins and the model-facing discovery server `jarvis-tools`
join this catalog; their contract is [plugins.md](plugins.md). Paragraphs
marked *(plugin amendment)* below describe that contract, now shipped;
everything else is unchanged and shipped.

## 1. Surfaces

| Server | Module | Tools today | Declared to the brain when | Reaches |
| --- | --- | ---: | --- | --- |
| `jarvis-display` | `jarvis/runtime/display_mcp.py:2208` (`build_server`) | 13 | `scene.enabled` true and Core target known (`control_center.py:1212-1224`) | Core `/v1/scene/*`, actor `brain` |
| `jarvis-console` | `jarvis/runtime/settings_mcp.py:972` (`build_server`) | 12 | always (no switch: it carries the other switches, `control_center.py:1241-1247`) | Control Center settings API; `/api/boards*`, `/api/sessions*` (Boards and Sessions, §10.9) |
| `jarvis-barehands` | `jarvis/runtime/barehands_mcp.py:475` (`build_server`) | 16 | `barehands.enabled` true (`control_center.py:1225-1240`) | Control Center `/api/barehands/commands` (five lifecycle tools, `barehands_test`, ten `calibration_*` tools, §6) |
| `jarvis-drive` | `jarvis/runtime/drive_mcp.py:65` (`build_server`) | 7 | never by Jarvis: registered by the operator (`claude mcp add … --scope user`, `docs/OPERATIONS.md:1475-1486`) | Google Drive |
| `jarvis-tools` *(plugin amendment, implemented by Slice 04; declared from Slice 05)* | `jarvis/runtime/tools_gateway_mcp.py` (`build_server`) | 2 | conversation profile of Claude, always (no switch); Codex, every turn ([plugins.md](plugins.md) §10) | native catalog in-process; Core `/v1/mcp/tools`, `/v1/mcp/tools/call` |

Each native server is written to its own `--mcp-config` file at brain launch
(`claude_local.py:777-782`, helpers `_barehands_mcp_args` / `_console_mcp_args` /
`_display_mcp_args` :893-974), conversation profile only; a change of switch
takes effect at the next brain (re)start. The switches are applied to the agent
by `_configure_agent` (`control_center.py:1205`, called from
`_apply_agent_settings` :1194).

*(Plugin amendment.)* Managed external plugins are **not** servers declared to
the brain: their tools are reached only through `jarvis-tools` `call_tool`
(Core executes them). In merged catalog views each plugin appears as one
server `server = plugin_id`, `registration = "managed"`, category `external`.

## 2. Catalog descriptor

Every inspector-visible tool has exactly one descriptor. Fields:

| Field | Type | Source | Rule |
| --- | --- | --- | --- |
| `name` | str | introspection | wire name, e.g. `scene_update_many` |
| `server` | str | introspection | e.g. `jarvis-display` |
| `qualified_name` | str | derived | `mcp__<server>__<name>` (the CLI's name, `claude_local.py:287-289`) |
| `category` | enum §3 | metadata | exactly one |
| `label` | str ≤ 48 | metadata | French human label, e.g. « Masquer, réafficher, étiqueter un ensemble » |
| `summary` | str | introspection | first line of the tool description |
| `description` | str | introspection | full description as advertised |
| `input_schema` | JSON Schema | introspection | as advertised, after the strict hardening (`additionalProperties: false`, `display_mcp.py:2237-2246`) |
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

*(Plugin amendment.)* A managed external tool has the same descriptor, built by
`mcp_catalog.describe_external_tool()` from Core's `ExternalToolDescriptor`
([plugins.md](plugins.md) §5), with:

| Field | Value for an external tool |
| --- | --- |
| `server` | `plugin_id` (slug, never `jarvis-*`) |
| `qualified_name` | `tool_id` = `<plugin_id>.<name>` — **not** `mcp__…`: the CLI never sees the tool, `call_tool` does |
| `tool_id`, `plugin_id` | as above |
| `invocation` | `managed_external` (native tools listed by `list_tools` are `direct_native`) |
| `category` | `external` |
| `label` | remote `title` or `name`, ≤ 48 |
| `parameters` | `parameters_of(input_schema)` (`mcp_catalog.py:137`) |
| `parameter_rules` | `[]` |
| `context_bytes` | `model_visible_bytes(name, description, input_schema)` (`mcp_catalog.py:160`): what the tool would cost if it were recommended by `list_tools` |
| `output` | `{format: "structured"` if the remote `outputSchema` was kept, else `"untyped"`, …}` |
| `side_effect`, `idempotent`, `atomicity` | from the remote annotations (MCP default `destructive`), `atomicity = "external"` |
| `deprecation` | `null` |

Its server carries `registration = "managed"` (`mcp_tool_meta.Registration`
becomes `jarvis | operator | managed`; `managed` is never used in `SERVERS`),
`module = null`, `condition = null`. The no-secret rule above applies to
plugins too: no endpoint credential, token, `credential_ref` or auth header
ever enters a descriptor.

## 3. Human categories

| `category` | Tab label | Tools |
| --- | --- | --- |
| `general` | Général | overview tab: servers, counts, availability, context budget, policies. Hosts cross-domain tools: `jarvis-tools` `list_tools` + `call_tool` *(plugin amendment, implemented by Slice 04)*; every other native tool belongs to a domain |
| `scene` | Étoiles / Scène | all `jarvis-display` tools |
| `settings` | Réglages et Boards | `settings_describe`, `settings_get`, `settings_set`; the nine Board/Session tools (§10.9) — the category is per server, and `jarvis-console` is one server |
| `barehands` | Bare Hands | all 16 `jarvis-barehands` tools (`barehands_*` and `calibration_*`, §6) |
| `external` | Externe | `jarvis-drive` (decision below); *(plugin amendment, implemented by Slice 04)* every managed plugin server |

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

`best_effort` is not a value (removed from the `Atomicity` literal by Slice 05).

### 4.3 Availability

Computed by the Control Center from what it already holds; **never by invoking
a tool, starting a server or reading user CLI config**. Three independent facts,
then one displayed state:

| Fact | Values | Definition | How it is proven |
| --- | --- | --- | --- |
| `condition` | setting id \| `null` | the switch that gates the server's declaration (static) | `jarvis-display` → `scene.enabled`; `jarvis-barehands` → `barehands.enabled`; `jarvis-console` → `null` (never gated); `jarvis-drive` → `null` (not declared by Jarvis) |
| `condition_value` | `true` \| `false` \| `null` | current value of that switch in the settings, **displayed only** (it does not decide `next_launch`); `null` when the server has no condition | `load_scene_gate` (environment override included), `barehands.load` |
| `next_launch` | `configured` \| `disabled` \| `null` | whether the next brain launch will declare the server: `configured` = the active agent holds the server target; `disabled` otherwise (switch off, target absent, or an agent that never receives native servers — Codex); `null` for `jarvis-drive` (Jarvis never declares it) | **agent-0 amendment F1 (Slice 06 review):** read from what the launch really uses — `agent.display_mcp` / `barehands_mcp` / `console_mcp` not `None` (set by `_apply_agent_settings` when settings are saved through the Control Center), never recomputed from the settings file; a missing target is already journaled (`scene.display_mcp_unconfigured`, `barehands.mcp_unconfigured`) |
| `advertised` | `true` \| `false` \| `null` | the running brain process was launched with this server's `--mcp-config`; `null` when unknowable (`jarvis-drive`: user-scope registration outside Jarvis; a running Claude snapshot without the flag; a snapshot that failed) | agent snapshot flags `display_tools`, `barehands_tools`, `console_tools` (`ClaudeLocalAgent.snapshot()`, set from `display_args` / `barehands_args` / `console_args` at each launch — Slice 06); `false` when the brain is not running; **`false` in every state for an agent that never receives native Jarvis servers** (Codex: no `display_mcp` attribute — agent-0 decision C1, Slice 06 review) |

`pending_restart = live and advertised is not None and next_launch is not None and advertised != (next_launch == "configured")`
(the switch changed since the brain was launched; effective at next restart).
**Agent-0 amendment (Slice 06 review):** `live` = a brain session is alive,
hence restartable to pick up the change — Claude `running`, Codex `running` or
`ready` (Codex runs one process per turn and stays `ready` between turns). A
stopped or exited brain has nothing pending: its next start uses the current
configuration.
**Agent-0 amendment (Slice 04 review):** the `next_launch is not None` term —
an unknown next launch cannot prove a pending restart. And `next_launch` is
`disabled` as soon as the target is absent, whatever the switch (known or not):
no launch can declare a server without its target.

Displayed `state` — an enum, first rule that matches wins:

| Precedence | `state` | When |
| ---: | --- | --- |
| 1 | `advertised` | `advertised is true` |
| 2 | `configured` | `next_launch == "configured"` (not advertised now: brain stopped, or switch just turned on while it runs → `pending_restart`) |
| 3 | `disabled` | `next_launch == "disabled"` (an advertised server whose switch was just turned off stays `advertised` by rule 1, with `pending_restart: true`) |
| 4 | `known` | nothing else is provable (`jarvis-drive`: defined in code, `next_launch` and `advertised` both `null`) |

Every descriptor's tools are at least `known` (present in introspection of
`build_server(...)` with an inert target / fake backend); `known` is displayed
only when nothing more specific is provable.

Shape: `{state: "advertised"|"configured"|"disabled"|"known", condition: str|null,
condition_value: bool|null, next_launch: "configured"|"disabled"|null, advertised: bool|null,
pending_restart: bool}`. "Conditional" is not a state: the UI derives it from
`condition != null`. "Advertised" means declared to the CLI; what the CLI then
shows the model (deferred tool list) is observed only in traces (Slice 08), never
claimed by the catalog.

Deprecation is not an availability state: a deprecated tool is still `advertised`
and carries `deprecation`.

**Plugin amendment — Codex exception to agent-0 decision C1 (implemented,
Slice 05).** "Codex
never receives native Jarvis servers" stays true for `jarvis-display`,
`jarvis-console` and `jarvis-barehands`, and becomes **false for
`jarvis-tools` only**: Codex receives the gateway through
`-c mcp_servers.jarvis-tools.*` overrides at every turn
([plugins.md](plugins.md) §10). For `jarvis-tools`, the Codex rule of the
table above is replaced by: `next_launch = "configured"` when the gateway
target is set on the agent, `advertised` = `CodexLocalAgent.snapshot()["tools_gateway"]`.
Codex runs one process per turn, so a `ready` snapshot is a live session:
`advertised` is read on `running` **or** `ready` (Claude is never `ready`).
For both agents the snapshot flag is `tools_gateway`
(`AGENT_SNAPSHOT_FLAGS["jarvis-tools"]`), and the Control Center maps
`jarvis-tools` to the agent attribute `tools_mcp` like `jarvis-console`
(no switch, `condition = null`).

**Plugin amendment — availability of a managed plugin server (implemented by
Slice 04, `mcp_catalog.plugin_availability`).** No
new state enum; the inspector badges are reused. A plugin's facts come from
Core (`GET /v1/mcp/tools`), never from invoking a tool:

```text
{"state": "advertised" if enabled and connection_status == "connected"
          else ("disabled" if not enabled else "known"),
 "condition": null, "condition_value": null, "next_launch": null,
 "advertised": null, "pending_restart": false,
 "enabled": bool, "connection_status": str, "auth_status": str}
```

For a plugin, `advertised` **as a state** means "offered by `list_tools` and
callable through `call_tool` now", not "declared to the CLI" (a plugin is never
declared to the CLI); the `advertised` fact stays `null`. Core unreachable ⇒ the
plugin servers are absent and the catalog carries one `unavailable` entry
`{"server": "plugins", "category": "external", "error": "core_unreachable"}`;
native servers are unaffected.

## 5. Source of truth, schemas, context

### 5.1 One source, parity-tested

- **Introspection is the source** of `name`, `description`, `input_schema`,
  `output_schema` (when structured) and annotations: `build_server(tools=Fake…)`
  (display, console, Bare Hands accept injected tools; `build_server(DisplayMcpTarget("127.0.0.1", 1, …))`
  already works in tests, `tests/unit/test_display_mcp.py:483`) and `list_tools()`.
- **One shared metadata module** (Slice 04: `jarvis/runtime/mcp_tool_meta.py`, §10.1)
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
| `scene_inspect`, `scene_query`, `scene_get` | `json_text` | a JSON Schema of the **parsed text**, kept in the metadata module, **not** advertised. Before Slice 04 they returned `str` with FastMCP's default structured output (`outputSchema {result: string}`, text block + `structuredContent.result`), and the CLI hands the model the `structuredContent`, so the brain read `{"result":"<escaped JSON>"}` (§10.3). **Slice 04 set `structured_output=False` on these three**, and on `settings_describe` for the same reason |
| `settings_describe` | `text_lines` | `{"type": "string"}` + a line grammar note: `- id · label = value [choices]`, optional `(lecture seule)` (`_describe_line`, `settings_mcp.py:937-946`) |
| `scene_capture` | `json_text+image` | schema of the JSON text block (`path`, `width`, `height`, `bytes`, `duration_ms`, `note`) + "PNG image block" |
| `drive_*` | `untyped` | whatever introspection yields; shown as untyped |

Decision for `inspect/query/get`: they stay compact, byte-budgeted JSON strings
(`MAX_INSPECT_BYTES` / `MAX_GET_BYTES` = 20 000, `display_mcp.py:158,165`).
Structured output would make FastMCP emit a second serialization and break the
budget and the row contract. Their schema describes the parsed text: header
object, `o` rows as positional arrays (`prefixItems`, one titled column each),
`r` rows, optional `truncated`. **The column list is defined once in code** and
both `OBJECT_ROW_LEGEND` (`display_mcp.py:2036`) and the schema derive from it,
so the legend the model reads and the schema the human reads cannot drift.

Refusals are **tool errors** (`isError`, text with `outcome`, `reason`, one
sentence), unchanged; output schemas describe success results only
(`applied` / `duplicate`).

Scene mutation result shapes (Slice 04 types, Slice 05 fills the batch ones):

| Shape | Fields |
| --- | --- |
| `SceneCommandResult` | `outcome` (`applied`\|`duplicate`), `revision`, `object_id?`, `relation_id?`, `command?`, `note?`, `scene_changed?`, tool extras (`scene_add_artifact`: `target_id`, `action`, `category`, `items`, `rule`, `ignored?`, `grouping_note?`) |
| `SceneBatchResult` | `op`, `outcome`, `revision`, `matched_count`, `changed_count`, `unchanged_count`, `skipped_count`, `matched_ids`, `changed_ids`, `unchanged_ids`, `skipped` [{id, reason}], `hidden_count` (always present — Slice 05 — and in particular whenever the selection has a `constellation` scope; members hidden before the command), `cascade_ids?` (archive), `delta?` {requested {dx, dy}, effective {dx, dy}, clamped} (move), `pinned?` (pin), `note?`, `scene_changed?`; id lists ≤ 20 (`MAX_BULK_REPORTED_IDS`) |

### 5.3 Model-context policy

- *(Plugin amendment, implemented by Slice 04 — replaces "no catalog meta-tool
  is advertised to the model".)* Exactly **one** discovery server is advertised to the model,
  `jarvis-tools`, and it exposes **exactly two** catalog tools: `list_tools`
  and `call_tool`. No other server may expose a catalog meta-tool, and there
  is no `get_tool` / `describe_tools`: `list_tools(intent)` returns the FULL
  description and input schema of its recommended tools (≤ 5, recommended part
  ≤ 16 KiB), a compact bounded remainder, and a cursor; the whole response is
  ≤ 24 576 bytes. It may be called repeatedly in one reasoning chain. Budgets
  of the two tools: name + description + input schema ≤ 2 500 B, server
  instructions ≤ 1 200 B. Contract: [plugins.md](plugins.md) §6–§7.
  The gate `test_no_catalog_meta_tool_is_advertised_and_the_scene_stays_within_thirteen`
  (`tests/unit/test_mcp_catalog.py:188-195`) is amended in Slice 04 to exempt
  `jarvis-tools` only. Other catalog helpers stay Control Center functions and
  HTTP routes.
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
| 6 | `scene_update_object` | edit **one** object: text, absolute place, shape, layer, visibility, label | `set_*` / `patch_object` | write / single_command | yes | typed result; keeps `visibility` (the QA live run showed the model reaches for it, `ARCHITECTURE.md:2510`) |
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

`jarvis-console`: generic settings (`settings_describe/get/set`); typed outputs
only. Idempotent: all three (`settings_set` with the same value re-reads the same
state). Board and Session tools added by the board-session handoff: §10.9. The inspector may render per-setting rows from `settings_describe` data at
the catalog layer; no per-setting wire tool.

`jarvis-barehands` (16 tools, §1): the five lifecycle tools `barehands_activate`,
`barehands_deactivate`, `barehands_calibrate`, `barehands_tutorial`,
`barehands_exit_overlay` unchanged; then `barehands_test` and the ten
calibration tools `calibration_status`, `calibration_record_feedback`,
`calibration_propose_hypothesis`, `calibration_prepare_trial`,
`calibration_commit_proposal`, `calibration_resolve_trial`,
`calibration_rollback_trial`, `calibration_accept_trial`,
`calibration_rerun_exercise`, `calibration_next_exercise`, both described
below. Idempotent: `barehands_activate`,
`barehands_deactivate`, `barehands_exit_overlay` yes (target state); `barehands_calibrate`,
`barehands_tutorial` no (each call (re)starts a guided flow). `jarvis-drive`:
`drive_search/get/read/update/delete/share` yes, `drive_create` no. `barehands_tutorial` is already
deprecated (opens calibration): descriptor `deprecation = {replacement:
"barehands_calibrate", removal_condition: see docs/legacy/barehands-tutorial-retirement.md
(next Bare Hands command-contract change, three tables in one commit),
legacy_doc: that file}`. Not removed here (no Bare Hands contract change in scope).

`jarvis-barehands`, `barehands_test` (Bare Hands adaptive-calibration task,
Slice 10): opens the read-only **Tester** start screen through the same gate as
its « Tester… » button (`JarvisBarehands.benchmark()`); no run starts, no
setting changes. Command `test`, typed output `BarehandsCommandResult`, not
idempotent (a second call reports `duplicate`), side effect `write` (opens an
overlay). From Slice 10, the entry-gate refusals of the flow tools travel with
their own code and page sentence (closed list `FLOW_GATE_CODES`, mirrored JS ↔
Python): `barehands_flow_busy`, `barehands_calibration_disabled|lifecycle_off|no_camera`,
`barehands_benchmark_unavailable|lifecycle_off|no_camera`; any other flow refusal
stays `barehands_flow_unconfirmed`. The lifecycle receipt shape (≤ 1 KiB,
`{outcome, lifecycle, code, reason}`) is unchanged.

`jarvis-barehands`, calibration tools (Bare Hands adaptive-calibration task, Slice 06;
canonical contract `docs/barehands-contracts.md` §17, decisions 50–55, proposals of 28/09): ten tools
declared with the server and refused with `barehands_calibration_inactive` outside a
calibration session open on the page — `calibration_status` (read, `none`),
`calibration_record_feedback`, `calibration_propose_hypothesis`,
`calibration_prepare_trial` (a visible proposal, nothing applied), `calibration_commit_proposal`
(applies it only on the user's verified consent, as one page transaction with engine readback),
`calibration_resolve_trial`, `calibration_rollback_trial`,
`calibration_accept_trial`, `calibration_rerun_exercise`, `calibration_next_exercise`
(write, `single_request`, not idempotent). Unlike the five lifecycle tools they take
**closed** arguments (unknown argument refused, vocabularies as enums mirrored from the
page contract under a parity test) and return typed structured results
(`mcp_results.Calibration*Result`) whose nested rows are validated by the Control
Center against one closed schema per command (`jarvis/domain/barehands_calibration.py`).
Arguments are snake_case like every Jarvis tool; results keep the session-contract
field names (`trialRef`, `evidenceRefs`…).
Slice 07 (decisions 56–59): `calibration_next_exercise` takes an optional closed
`reason` (`not_relevant`, `cannot_perform`, `tracking`, `later`) — without it, it
validates a successful exercise review; with it, it skips the exercise (measurement not
kept), and skipping an unfinished or failed exercise without a reason is refused
`barehands_calibration_skip_reason_required`; its result carries `decision`
(`validated` | `skipped`, `CalibrationNextResult`), and it is refused
`barehands_calibration_trial_pending` while a trial awaits its measurement on the
exercise on screen;
`calibration_status` adds `reviews` (last review decisions) and a session-clock `t`
on every measurement row.

## 7. Migration and deprecation

Rules:

- A removed or renamed tool gets **no alias by default**. The only callers are the
  brain (fresh `tools/list` at every launch) and tests/docs. A resumed
  conversation (`--resume`) keeps its old system prompt (`claude_local.py:398-400`)
  and may name `scene_set_visibility`: the call fails with a visible unknown-tool
  error and the model has the new list — accepted, logged in Slice 08 traces.
- A temporary alias is allowed only with: a `deprecation` descriptor, a
  `docs/legacy/*.md` entry, a code comment, and a removal condition that is an
  observable event (not a date). It does not count toward the ≤ 13 target, and
  Slice 08 fails if one is still advertised after its removal condition is met.
- Removing a tool in Slice 05 updates, in the same change, every reference below.

Reference inventory at `ddcdb71` (historical: every row was updated by Slice 05; outside `tasks/`; files only — Slice 05 greps
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
by nothing user-controlled); availability recomputed per request. Errors use the
Control Center's coded JSON refusal `{ok: false, code, error}` (there is no
`send_error_response` helper in this repository), and the inspector shows them.
Delivered shape: §10.6.

**Plugin amendment — merged view implemented by Slice 04; management routes
implemented by Slice 06.** The catalog routes above stay GET-only; `GET
/api/mcp/tools` is the merged view (Slice 04:
`ControlCenter._mcp_merged`, Core read through `CoreSessionTransport.mcp_tools`,
cached by revision; Core unreachable, slower than 2 s or not configured ⇒ the
`plugins` entry `described: false`, `error: "core_unreachable"`,
`registration: "managed"`, availability `known`, journaled once per outage
`mcp.plugins_unreachable` then `mcp.plugins_restored`)
`list_view(merge_external(cached_catalog(), <Core GET /v1/mcp/tools>))` (Core
timeout 2 s), and `GET /api/mcp/tools/{server}/{name}` also answers for
`server = plugin_id`. Plugin **management** routes are separate, relayed to
Core by `jarvis/runtime/mcp_plugin_routes.py` (pattern `board_routes.py`;
status and JSON body verbatim; Core unreachable ⇒ `503 core_unreachable`):

| Control Center route | Core route | Guard |
| --- | --- | --- |
| `GET /api/mcp/plugins` | `GET /v1/mcp/plugins` | `READ_GUARDED_ROUTES` (endpoints are private data) |
| `POST /api/mcp/plugins` | `POST /v1/mcp/plugins` | guarded |
| `PATCH /api/mcp/plugins/{id}` | `PATCH /v1/mcp/plugins/{id}` | guarded |
| `POST /api/mcp/plugins/{id}/connect` | `POST /v1/mcp/plugins/{id}/connect` | guarded |
| `PUT /api/mcp/plugins/{id}/credential` | `PUT /v1/mcp/plugins/{id}/credential` | guarded; body never journaled |
| `POST /api/mcp/plugins/{id}/disconnect`, `/refresh` | same under `/v1/mcp/plugins/{id}` | guarded |
| `DELETE /api/mcp/plugins/{id}` | `DELETE /v1/mcp/plugins/{id}` | guarded |
| `GET /api/mcp/oauth/callback?code&state&iss&error` | `POST /v1/mcp/oauth/callback` | **not** read-guarded (the authorization server's redirect is a cross-site navigation); loopback Host only; single-use `state`; static HTML answer, `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, never echoes `code`/`state` |

`_mcp_json_errors` (`control_center.py`) keeps the "read-only (GET)" 405
wording and the `404 mcp_tool_unknown` answer for the rest of `/api/mcp`
(`/api/mcp/tools*`, `/api/mcp`, any other unmatched path); under
`/api/mcp/plugins*` and `/api/mcp/oauth*` it delegates to
`McpPluginRoutes.refusal`: a 405 says `method_not_allowed` with the real
`Allow`, an unknown sub-path `404 not_found`, and an id that cannot be a
plugin id (outside `^[a-z0-9][a-z0-9-]{0,31}$`) `404 mcp_plugin_unknown`
without reaching Core — never echoed. These three answers use Core's
envelope `{"error": {"code", "message"}}`, like every relayed answer; the
guard's refusal keeps its own `{ok: false, code: "forbidden_origin", error}`.
Delivered detail: §10.6. **Invariant restated: no
tool-execution route exists in the Control Center.** `call_tool` is served by
Core only (`POST /v1/mcp/tools/call`), reached by the `jarvis-tools` gateway;
the inspector module keeps its GET-only client (§10.7).

## 9. Open points

- Whether the Claude CLI forwards `outputSchema` / annotations to the model:
  **measured by Slice 04: it does not** (§10.3); **confirmed by Slice 08** on the
  final surface, with deferred tool search on the real API (§10.8).
- `jarvis-drive` import without Google dependencies: **verified by Slice 04: it
  imports and introspects** (§10.4); the "descriptor unavailable" fallback of §3
  stays for a broken import.
- `drive_update` idempotency key (`drive_mcp.py:103`): already filed in
  `tasks/jarvis-mcp-semantic-batch-inspector/Issues/01-*`; out of scope.

## 10. Implementation facts (Slice 04)

### 10.1 Modules

| Module | Holds | Imports |
| --- | --- | --- |
| `jarvis/runtime/mcp_tool_meta.py` | the **only** copy of per-tool `label`, `side_effect`, `idempotent`, `atomicity`, `output_format`, `parameter_rules`, `output_notes`, `deprecation`, and per-server `category`, `condition`, `registration`. `tool_names(server)` (registration order), `annotation_hints` / `tool_annotations` (§4.1) | pure (no `mcp`, no `pydantic`, no server module) |
| `jarvis/runtime/mcp_results.py` | pydantic result models: `SceneObjectResult`, `SceneRelationResult`, `SceneArtifactResult` (together the `SceneCommandResult` of §5.2), `SceneBatchResult` (defined, filled by Slice 05), `SettingsGetResult`, `SettingsSetResult`, `BarehandsCommandResult`; `output_contract_fields` / `OUTPUT_CONTRACT_MESSAGE` | `pydantic`, loaded by `build_server` and the catalog only |
| `jarvis/runtime/mcp_catalog.py` | `build_catalog()` / `cached_catalog()` (descriptors §2, order §8), `describe_tool`, `parameters_of(input_schema)`, `list_server_tools(server)`, `build_introspection_server(server)`, `availability(...)`, `advertised_from_agent_snapshot(...)`, `model_visible_bytes(...)` | `mcp` at call time |
| `jarvis/runtime/display_mcp.py` | `OBJECT_ROW_COLUMNS`, `NEAR_ROW_COLUMNS`, `RELATION_ROW_COLUMNS` (`RowColumn`: name, legend word, JSON schema); `OBJECT_ROW_LEGEND` / `RELATION_ROW_LEGEND` / `NEAR_ROW_LEGEND` derive from them (byte-identical to before, tested); `text_output_schemas()` for `inspect/query/get/capture` (all four JSON-text schemas together, as plain JSON Schema dicts: `capture_text_schema()` describes the dict `_capture` builds; `scene_query` rows are `oneOf` exactly 14 or 16 columns; `scene_get` details declare the `_fit_detail` markers `items_omitted`, `summary_truncated`) | — |

Registration consumes the metadata: every `@mcp.tool(...)` of the four servers
passes `annotations=tool_annotations(SERVER_NAME, name)`; `TOOL_NAMES` of
display / console / Bare Hands is `tool_names(SERVER_NAME)`; `READ_TOOL_NAMES`
is the `read` class; `DISPLAY_TOOLS` (`claude_local.py`) still derives from
`display_mcp.TOOL_NAMES`. Tool **descriptions and input schemas are unchanged**
(prompt fingerprint tests untouched).

Descriptor shape (`describe_tool`): the §2 fields, plus `annotations` (as
introspected), `context_bytes` (§5.3 cost) and `output = {format, schema,
advertised_schema, notes}`; `parameters[]` entries are `{name, type, required,
has_default, default?, constraints, description}` — `default` is present only
when the schema has one (absent ≠ `null`); `constraints` carries `enum`,
bounds, lengths, item counts, `pattern`, nested `keys` (with `required`) and
`closed` for `additionalProperties: false`. `availability` is not in the
descriptor: Slice 06 calls `availability(server, condition_value=…,
target_present=…, advertised=advertised_from_agent_snapshot(server, snapshot))`
per request. An unknown fact stays `None`, never guessed: `next_launch` is
`null` when the switch value or the target is unknown.

Introspection safety: `build_introspection_server` injects `_Inert` backends
(any attribute access raises) into display / console / Bare Hands, and
`drive_mcp.build_server()` builds its Google backend only inside a tool call.
No tool runs, no socket opens, no environment value or token path is read
(tested with sentinel environment values).

Typed outputs: success results are closed models (`additionalProperties:
false`); an optional field absent from the dict stays absent from
`structuredContent` (no invented `null`), and field order follows the order in
which the tool builds its dict. Because the CLI shows the model the
`structuredContent` (§10.3): for the **display mutations** (which already
returned `dict[str, Any]`, hence structured) the bytes the brain reads are
unchanged, except `scene_link`'s already-present path, which now carries
`revision` like every other command result; **`settings_get`, `settings_set`
and the five `barehands_*`** returned a bare `dict` (no output schema, text
block only, indented JSON) and now reach the model as **compact JSON**, same
keys, same order. A result that fails its own schema is a tool error that
says the action **may have been applied** (`OUTPUT_CONTRACT_MESSAGE`), never
"rien n'a été envoyé" (the argument-error sentence); display journals it as
`display.tool_failed` with code `output_contract`.

Slice 05 closed the transition: the four set tools are `atomic_batch` with a
`structured` `SceneBatchResult`, `scene_set_visibility` is gone (no alias, so no
deprecation descriptor either), and `best_effort` is no longer an `Atomicity`
value (§10.5).

### 10.2 Adding or changing a tool

1. Add its `ToolMeta` to the server in `mcp_tool_meta.py`, **at its
   registration position** (label ≤ 48, class, idempotent, atomicity, output
   format, rules, deprecation).
2. Register it with `annotations=tool_annotations(SERVER_NAME, "<name>")`. A
   structured success result gets a model in `mcp_results.py` whose field order
   matches the dict the tool builds; a compact JSON text gets
   `structured_output=False` and a schema in `display_mcp.text_output_schemas()`.
3. Run `tests/unit/test_mcp_catalog.py` (parity both ways and in order,
   annotations, `tools/list` equality, completeness, real outputs × schemas,
   no leak, no meta-tool except `jarvis-tools` (§5.3 amendment), scene ≤ 13) and the server's own tests; a prompt that
   names the tool updates the `claude_local` fingerprint tests.

### 10.3 Measured: what the Claude CLI shows the model

Claude Code **2.1.282**, 2026-09-25. Method: `claude -p` against a local fake
Messages endpoint (`ANTHROPIC_BASE_URL` on 127.0.0.1, dummy key, isolated
`CLAUDE_CONFIG_DIR`, `--strict-mcp-config` with the real `jarvis-display` and
`jarvis-console` servers built on inert backends, then `jarvis-barehands` on a
fake page for a tool round trip). Request **bodies** recorded, never headers; no
real API call; the user's Jarvis untouched.

- **Tool definitions** sent to the model carry exactly `name`, `description`,
  `input_schema`. No `outputSchema`, no annotations (`readOnlyHint`… absent from
  the whole request). Descriptions and input schemas are the advertised ones,
  byte for byte, in the normal (non `--bare`) mode, so the §5.3 cost is exactly
  `model_visible_bytes`, and typed output schemas and annotations cost **zero**
  model context: they are kept on every typed tool, no fallback needed.
  (`--bare`, which Jarvis does not use, truncates descriptions to their first
  paragraph.)
- **Tool results**: for a result whose text block differs from its
  `structuredContent`, the model received the **`structuredContent` as compact
  JSON**, not the text block. Consequences: (1) before this slice the brain read
  `scene_inspect/query/get` and `settings_describe` as `{"result":"…escaped…"}`,
  whose wrapper and escaping inflated the 20 KB budgets; `structured_output=False`
  restores the raw text; (2) typed models must neither inject `null`s nor
  reorder keys (done; tested by JSON string equality).
- **Deferred tool loading** is observable locally with `ENABLE_TOOL_SEARCH=true`
  (without it, a third-party base URL disables tool search and every MCP tool
  is inline): the MCP definitions then carry `name`, `description`,
  `input_schema` and `defer_loading` only; `ToolSearch` answers with
  `tool_reference` blocks; still no annotations nor `outputSchema`, and the
  result shapes are those of the inline run (raw text for `scene_inspect`,
  compact typed JSON for mutations). Evidence: Slice 04 QA
  `slices/04-mcp-catalog-typed-schemas/qa/agent-trace-analysis.md`. Confirmed
  on the real API by Slice 08 (§10.8).

Baseline model-visible cost (`context_bytes` = name + description + input
schema, at this slice): `jarvis-display` 33 090 B (13 tools), `jarvis-console`
2 918 B, `jarvis-barehands` 4 107 B, `jarvis-drive` 2 126 B. Slices 05 and 08
must not exceed the display baseline without a written reason.

### 10.5 Slice 05 — `jarvis-display` on the target surface

Advertised, in registration order (13): `scene_inspect`, `scene_query`,
`scene_get`, `scene_create_object`, `scene_update_object`, `scene_update_many`,
`scene_move`, `scene_archive`, `scene_pin`, `scene_link`, `scene_unlink`,
`scene_add_artifact`, `scene_capture`. Metadata (`mcp_tool_meta.DISPLAY`):
`scene_update_many` write / idempotent / `atomic_batch`; `scene_move` write /
**not** idempotent / `atomic_batch`; `scene_archive` destructive / idempotent /
`atomic_batch`; `scene_pin` write / idempotent / `atomic_batch`; all four
`structured` (`SceneBatchResult`). `TOOL_NAMES`, `READ_TOOL_NAMES` and
`claude_local.DISPLAY_TOOLS` derive from it unchanged.

- **Selectors.** `select` (the filters of `scene_query`, `SelectArg`, closed:
  `kind`, `kinds`, `category`, `exec_state`, `exec_states`, `origin`,
  `visibility`, `text`, `work`, `explains`, `constellation {object_id,
  depth?}`, `group`, `near {object_id, radius}`, `include_hidden`, `exclude`)
  XOR `object_ids` (1–512). `connected` is gone without alias: it is an
  unknown key, refused by the schema. `scene_query` takes the same filters as
  flat arguments.
- **One call → one command.** Each set tool builds one `SceneSelection` and
  posts one selection command; the result is Core's `batch` report mapped to
  `SceneBatchResult`. Refusals are tool errors naming every offender, with
  « Rien n'a été appliqué (lot atomique : tout ou rien) ». A transport failure
  is one tool error ending with `BATCH_TRANSPORT_NOTE`. Details:
  [../scene-selection-batch.md](../scene-selection-batch.md) › *Implementation
  facts (Slice 05)*.
- **`scene_move`** (`dx`, `dy` required numbers; `select` \| `object_ids`;
  `pin?`): `translate_selection`; `delta` reports requested, effective and
  clamped.
- **Kept safety rule.** `scene_update_many` still refuses, before sending,
  hiding ≥ half of the visible objects (≥ 3) without `confirm=true`
  (`selection_too_broad`); computed with the domain resolver.
- **Context cost** (`model_visible_bytes`, sum over the server): **33 090 B
  before, 31 833 B after (31 864 B after the rework wording)**. The display server's `list_tools` now drops the
  `title` keywords pydantic derives from names (« Object Id », « SelectArg »;
  ~3.6 KB, never a property named `title`), which pays for `scene_move`, the
  richer `SelectArg` (repeated in the four set tools' `$defs`) and the
  flat `scene_query` filters. Gate: `test_the_display_context_cost_stays_within_the_slice_04_baseline`.
- **Prompt.** `BRAIN_DISPLAY_PROMPT` lists `scene_move` instead of
  `scene_set_visibility` and gains one line: a set is one call (all or
  nothing), how to select a constellation, move a group with `scene_move`,
  what `hidden_count` means. Fingerprint `BASE_DISPLAY_SHA256` updated
  deliberately (`tests/unit/test_scene_artifacts.py`). Server instructions gain
  the same « one call per set » sentence.
- `mcp_results.SceneBatchDelta` carries `requested` / `effective` as
  `SceneOffset {dx, dy}` (the wire shape of `BatchDelta.to_payload`), not lists.
- Rework (review M1–M3): `hidden_count` is **required** in `SceneBatchResult`
  (members hidden before the command; the prompt asks for « dont N masqués »
  only after `scene_move`, `scene_archive` or on a constellation, since for
  « réaffiche tout » it equals the shown count); `scene_move pin=false` is an
  `invalid_argument` (the domain only knows `pin: true`; unpin with
  `scene_pin`), nothing sent.

### 10.4 `jarvis-drive`

`jarvis.runtime.drive_mcp` imports, and `build_server().list_tools()` runs, with
every `google*` module import blocked (meta-path blocker): the adapter imports
the Google libraries lazily. It is described by introspection like the native
servers (category `external`, outputs `untyped`, availability always `known`);
its annotations come from the same metadata (`openWorldHint: true`;
`drive_update` and `drive_delete` destructive).

### 10.6 Slice 06 — Control Center catalog API

Routes (`control_center.py`, `MCP_TOOLS_ROUTE`), **GET only** (405 on any other
method; a test pins the method set under `/api/mcp`); same rule as `/api/catalog`
and `/api/agent` (not in `READ_GUARDED_ROUTES`: nothing private, nothing
consumed). Views are pure functions of `mcp_catalog`:

- `GET /api/mcp/tools` → `list_view`: `{ok, categories[{category, label}],
  servers[{server, category, category_label, condition, registration, described,
  error, tool_count, context_bytes, availability{state, condition, next_launch,
  advertised, pending_restart}}], tools[{server, name, qualified_name, category,
  label, summary, side_effect, atomicity, idempotent, availability (state
  string), deprecated, parameter_count, required_count, context_bytes}]}`
  (`availability` of a server also carries `condition_value`, §4.3).
  Order: servers by §3 category then name; tools in catalog order (category,
  server, registration). A server whose introspection fails (import or any
  other exception) stays in `servers` with `described: false`, `error` =
  exception **class**, no card; the other servers are still served. Only the
  parity guard (a registered tool without metadata) fails the whole catalog.
- `GET /api/mcp/tools/{server}/{name}` → `detail_view`: `{ok, tool}` = the
  `describe_tool` descriptor (§10.1) + `availability` object.

Stable errors: `404 {ok: false, code: "mcp_tool_unknown", error: "unknown MCP
tool"}` (the requested segments are never echoed) — for an unknown tool **and**
for any unmatched path under `/api/mcp` (middleware `_mcp_json_errors`, this
prefix only; since plugin Slice 06, `/api/mcp/plugins*` and `/api/mcp/oauth*`
answer their own 404/405, see the plugin paragraph below); `405 {ok: false, code: "method_not_allowed", error}` with `Allow`
for any non-GET method; `503 mcp_server_unavailable`
(`server` + error class) for a tool of an undescribable server; `503
mcp_catalog_unavailable` (error class only, `mcp.catalog_failed` journaled at
error) when `cached_catalog()` raises. `mcp.catalog_built` (info) once per
process.

Availability facts (`ControlCenter._mcp_availability`, per request, pure
`availability(server, condition_value=, declared=, advertised=, live=)`):
`condition_value` from `load_scene_gate(settings)` (environment override
included) and `barehands.load(settings)`, displayed only; `declared` = the
active agent's `display_mcp` / `barehands_mcp` / `console_mcp` is not `None`
(Codex has none: `declared` and `advertised` both `false`); `advertised` =
`advertised_from_agent_snapshot` on `agent.snapshot()`, whose `barehands_tools`
/ `console_tools` flags this slice added (`ClaudeLocalAgent`, same lifecycle as
`display_tools`); `live` = snapshot `state` in `running` / `ready`. A snapshot
that raises → `advertised` and `live` unknown, `mcp.availability_failed`
(warning, class only), never a 500. `jarvis-drive` stays `known`.

Security: responses carry descriptors and availability only — no target
(host, port, token file), no environment value, no settings value, no path
(tested with sentinel environment values, a stored credential, the temp
runtime path and the user home). Model-visible surface unchanged
(`jarvis-display` `context_bytes` 31 864 B, 13 tools, tested).
Tests: `tests/unit/test_control_center_mcp_api.py`.

**Plugin management routes (generic-mcp-plugin-runtime, Slice 06).** Module
`jarvis/runtime/mcp_plugin_routes.py` (`McpPluginRoutes`), registered by the
`ControlCenter` constructor, transport read at each request
(`CoreSessionTransport.forward`, which gained an optional `timeout_s`;
`LocalCoreClient.forward_json` relays `/v1/mcp/plugins*` and
`/v1/mcp/oauth/callback` besides Boards/Sessions — never `/v1/mcp/tools*`,
`FORWARDABLE_PREFIXES`). The exact route and method set under `/api/mcp` is
pinned by `test_only_get_routes_exist_under_the_catalog_and_the_plugin_set_is_pinned`
(catalog GET-only; plugins: list/create, get/patch/delete, connect,
disconnect, refresh, credential; callback GET without HEAD, so a bodiless
request never consumes a `state`).

- **Relay.** Core status and JSON verbatim. Delays: 10 s (client default)
  for list/create/get/patch/credential; **35 s** (`LONG_TIMEOUT_S`) for
  connect, disconnect, refresh and delete (Core waits up to 20 s for a
  connection, 5 s + 10 s for a disconnect with revocation); **25 s**
  (`CALLBACK_TIMEOUT_S`) for the callback. Body ≤ 256 KiB, read in a bounded
  loop (a chunked body without `Content-Length` is bounded too) ⇒ `400
  mcp_plugin_invalid`. Transport failure ⇒ `503 core_unreachable` (journaled
  once per outage `mcp.plugin.core_unreachable`, then
  `mcp.plugin.core_restored`); timeout ⇒ `504 core_timeout` ("the outcome of
  this write is unknown"); no Core ⇒ `503 core_unconfigured`; Core without
  JSON ⇒ `http_error`. Writes journal `mcp.plugin.relayed` (action,
  `plugin_id`, status, code — never a body); reads are not journaled one by
  one (the UI polls them every 2 s during an authorization). **Only the
  method, path, query and body cross the relay**: no browser header reaches
  Core — not `Authorization`, `Cookie`, `Proxy-*`, nor any hop-by-hop header
  (`Connection` and what it names, `Keep-Alive`, `TE`, `Upgrade`); the
  transport sets its own `Authorization: Bearer <core token>` and
  `X-Jarvis-Protocol`. Structural: `CoreSessionTransport.forward` takes no
  headers (QA S6 M12, tested against a recording fake Core).
- **Guard.** `/api/mcp/plugins` is in `READ_GUARDED_ROUTES`: every method,
  reads included, needs a loopback Host, a loopback Origin when present, and
  no `Sec-Fetch-Site: cross-site` ⇒ else `403 forbidden_origin` before any
  relay.
- **OAuth callback** `GET /api/mcp/oauth/callback?state&code&iss&error`
  (outside the guard): Host must be loopback (`403` page `forbidden_host`);
  `state` missing or empty ⇒ `400` page `mcp_oauth_state_invalid` without
  Core; any parameter > 4 096 chars ⇒ `400 mcp_plugin_invalid`; other
  parameters (`error_description`, `session_state`…) are dropped. Relays
  `POST /v1/mcp/oauth/callback {state, code?, iss?, error?}` and answers a
  static French page: « Autorisation reçue, vous pouvez fermer cet onglet. »
  (200) or « L’autorisation n’a pas abouti. » with a sentence and the stable
  code (Core's status, 503/504 on transport failure). A sentence names the
  button the card really shows then — « Relancer l’autorisation » after an
  unknown/expired `state` or a refusal on the AS page, « Reconnecter » when
  the service asks for a new authorization — with non-breaking spaces inside
  « ». Headers:
  `Cache-Control: no-store`, `Referrer-Policy: no-referrer`,
  `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline';
  base-uri 'none'; form-action 'none'; frame-ancestors 'none'`. No script;
  `code`, `state`, `iss` and the AS `error` text are never echoed.
  `mcp.oauth.callback` journals status, code and `plugin_id` only.

Tests: `tests/unit/test_control_center_mcp_plugins_api.py` (recording
transport for the exact route mapping, and a real chain Control Center →
`CoreSessionTransport` → Core `LocalProtocolServer` with a scripted
connector for the lifecycle, the OAuth round trip and its replay, and the
secret sentinel in every response and journal line).

### 10.7 Slice 07 — Control Center inspector

Module `jarvis/runtime/control_center_mcp_inspector.js`, injected at
`/*__CONTROL_CENTER_MCP_INSPECTOR_JS__*/` (`MCP_INSPECTOR_SCRIPT_FILE` /
`_MARKER`, `control_center.py`), after the Test Lab. Dock button
`#openMcpInspector` (`MCP`, between `SET` and `AGT`; in the Cosmos toolbar it
keeps the same neighbour, right after `SET`: AGT, CNV, LAB, TRC, SET, MCP,
ERR), dialog `#mcpInspector`
(same full-screen shell as the timeline and the Test Lab, rank 55). No panel
registry: dedicated button + dedicated dialog (READINESS §3.4).

- **Read-only by construction.** `createClient` is the only network path; it
  refuses any path other than `/api/mcp/tools` or exactly two non-empty
  segments below it (no `.`/`..`, even encoded; no query) before the network,
  and sends `GET` only; detail URLs are two segments, each
  `encodeURIComponent`-ed. No tool
  name literal in the module (§5.1, tested against `build_catalog()`).
- **Data.** Tabs from `categories[]` (API labels); server strip from
  `servers[]` (state, condition, `context_bytes`, `pending_restart` → notice
  "À prendre en compte au prochain (re)démarrage du brain"); rows from
  `tools[]`. **The list (servers + availability) is re-read on every open**;
  descriptors are fetched lazily on expand (at most 4 in flight) and cached
  until "Actualiser" or until the list's tool set changes. Detail requests
  carry a generation: a response that returns after "Actualiser" is dropped,
  and expanded rows are re-read once the list has resolved. The first search
  fetches all descriptors so parameter names (and nested `constraints.keys`)
  are searchable; a descriptor in error is not retried by that index (only by
  its "Réessayer" or "Actualiser"), and the status says how many failed. A
  failed refresh keeps the last list and shows the coded error with
  "Réessayer" in the notice slot.
- **General tab.** Overview (servers table, badge legend, policy line) plus
  a cross-domain sentence built from the catalog (count of `general` tools,
  other category labels from `categories[]`); `general` tools render below.
- **Card badges.** `side_effect`, `atomic_batch`, `idempotent`, `deprecated`;
  the server state only when it is not `advertised`.
- **Detail.** First description paragraph dropped when it equals the summary;
  facts (qualified name, §4.1 class, §4.2 atomicity, idempotence, context
  bytes); parameter table from `parameters[]` (Type column in the same
  vocabulary as the tree — "liste de string, ou null" — with the wire form in
  its tooltip; `default` shown only when `has_default`, an explicit `null`
  muted; nested structure rendered from the parameter's input schema);
  `parameter_rules`; output `format` sentence, `notes`, readable schema tree
  (root model named, `$ref` → `$defs`, `anyOf` with `null` → ", ou null",
  `prefixItems` → numbered titled columns, `oneOf` → "l’une de N formes",
  `enum` values, "aucune autre clé acceptée" for closed objects, maps; cycle
  and depth guard); raw input/output JSON last, in a `<details>` closed by
  default and kept open across re-renders.
- **States.** Skeleton + label + elapsed seconds while loading; 15 s deadline
  (`timeout`); coded errors show title, server message, `code · HTTP status`,
  a recovery hint and "Réessayer"; empty search explains and points to tabs
  that match; an undescribable server is said, never guessed.
- **A11y.** `role=dialog` + `aria-modal`, tablist with roving `tabindex`
  (arrows, Home/End), row toggles are `<button aria-expanded aria-controls>`
  (Enter/Space), arrows between rows, `/` focuses search, Escape (document
  capture listener, works with focus on `<body>`) closes and returns focus to
  the dock button, focus trap, rest of the page `inert`, keyboard focus kept
  across every re-render (stable ids, saved before any HTML swap; a background
  descriptor updates tab counts only during a search), elapsed seconds outside
  live regions, search announcement debounced (400 ms),
  page shortcuts suspended while open, `prefers-reduced-motion` honoured, page
  tokens only, stacked parameter table under 700 px.

Tests: `tests/unit/test_control_center_mcp_inspector_js.py` (node, real API
payloads from a real `ControlCenter`).

**Plugin tab (generic-mcp-plugin-runtime, Slice 06).** The same dock button
(label « MCP · outils du brain et plugins externes ») opens the same dialog,
which now has a two-tab switch in its header (`#mcpViewTabs`, roving
`tabindex`, arrows/Home/End): « Exposition interne » (this inspector,
unchanged, `#mcpiMain`) and « Plugins externes » (`#mcpPlugins`, module
`control_center_mcp_plugins.js`, injected at
`/*__CONTROL_CENTER_MCP_PLUGINS_JS__*/` right after this module). Choosing
the plugin tab sets `data-view="plugins"` on the dialog, which hides the
inspector's search, buttons, status, notice and body by CSS — the inspector
keeps running untouched. The inspector module gained **one** export,
`toolRowsHtml(tools, {idPrefix, expanded, details, now, rawOpen})`: the rows
and details of any tool list rendered by `cardHtml`, ids under a separate
prefix. It still has no write path and no second `fetch`; its client stays the
only one that reads `/api/mcp/tools*`, and the plugin tab uses that same
read-only client for a plugin's tools. Contract of the tab:
[plugins.md](plugins.md) §9.

### 10.8 Slice 08 — integration measurements (final surface)

Claude Code 2.1.282, 2026-09-25, isolated Core/Control Center, evidence in
`tasks/jarvis-mcp-semantic-batch-inspector/slices/08-integration-release-qa/qa/`.

- **Real API, real brain** (`ClaudeLocalAgent`, `jarvis-display` +
  `jarvis-console`): the brain loads display and console tools through
  `ToolSearch select:` (`tool_reference` blocks); reads (`scene_inspect`,
  `scene_query`, `settings_describe`) reach it as raw text, never
  `{"result":…}`; mutations as compact typed JSON (`structuredContent`).
  Every set operation was one tool call, one Core command, one revision.
- **Tool definitions** (fake Messages endpoint, all three native servers):
  keys `name`, `description`, `input_schema` only; no `outputSchema`, no
  annotations anywhere in the request. The CLI rewrites `…` (U+2026) to `...`
  (same byte count) in descriptions and schemas it sends, so the model reads
  `...` where the catalog shows `…`; `context_bytes` stays exact.
- **Parity**: for `jarvis-display` (13), `jarvis-console` (3),
  `jarvis-barehands` (5) and — when the operator declares it — `jarvis-drive`
  (7), the tool names and counts of `GET /api/mcp/tools` equal the CLI's
  `system/init`, and every `GET /api/mcp/tools/{server}/{name}` input schema and
  description equals the definition the model received (modulo the rewrite
  above).
- **Context budget**: display 31 864 B (13 tools, ≤ the 33 090 B baseline),
  console 2 918 B, Bare Hands 4 107 B, drive 2 126 B; 21 Jarvis-declared tools,
  no catalog meta-tool, no alias.

### 10.9 Board-session handoff, Slice 05 — Board and Session tools on `jarvis-console`

Handoff `tasks/jarvis-board-session-context-runtime/`, contract
[../boards.md](../boards.md) › *MCP tools*. Nine tools registered after the
three settings tools (registration order = `mcp_tool_meta.CONSOLE`), logic in
`jarvis/runtime/console_boards.py` (`ConsoleBoardTools`, reached as
`ConsoleSettingsTools.boards`: same aiohttp session, journal and
`ConsoleToolError`). They call the Control Center's `/api/boards*` and
`/api/sessions*` — the routes the UI calls — never Core.

| Tool | Route(s) | Class / idempotent | Result (`mcp_results`) |
| --- | --- | --- | --- |
| `board_list` | `GET /api/boards[?include_archived=true]` | read / yes | `BoardListResult {active_board_id, boards[BoardSummary]}` |
| `board_get` | `GET /api/boards/{id}` | read / yes | `BoardResult` |
| `board_get_active` | `GET /api/boards/active` | read / yes | `BoardResult` |
| `board_create` | `POST /api/boards` | write / no | `BoardResult` |
| `board_update` | `PATCH /api/boards/{id}` | write / yes | `BoardResult` |
| `board_archive` | `POST /api/boards/{id}/archive` | destructive / yes | `BoardResult` |
| `board_switch` | `GET /api/boards/{id}` (+ `GET /api/boards/pending` when the target is active), then `POST /api/boards/switch {board_id, origin:"brain"}` | write / yes | `BoardSwitchResult {status: applied \| scheduled \| unchanged \| unknown, board_id, title, previous_board_id?, replaced_board_id?, note}` |
| `session_current` | `GET /api/sessions/current` | read / yes | `SessionCurrentResult` |
| `session_new` | `GET /api/sessions/current`, then `POST /api/sessions/new {origin:"brain", expected_session_id}` | write / no | `SessionNewResult {status: applied \| scheduled \| unknown, closed_session_id, board_id, jarvis_session_id?, merged, note}` |

Writes are `single_request`, reads `none`; all `structured`. `BoardResult` is
the Board as the screen shows it: `board_id, title, status, active,
interaction_mode, last_opened_at, context_summary, task_refs, artifact_refs,
project_refs, updated_at` (no `scene_ref`, `runtime_metadata`,
`interaction_mode_origin`: runtime fields). No low-level voice, brain-binding
or speech-authority tool, and `origin` is never a model argument.

- **Input schemas.** `board_id` pattern `^(default|board_[A-Za-z0-9_-]+)$`
  (≤ 80); `title` 1–120; `context_summary` ≤ 1 500; each `*_refs` ≤ 64 items of
  1–256 chars (bounds imported from `jarvis/domain/workspace_board.py`; Core
  revalidates). Since this slice the console server refuses **unknown
  arguments** at call time for every tool, settings included (« Arguments
  inconnus refusés, rien n'a été envoyé »), and a pydantic argument error is
  « Argument invalide, rien n'a été envoyé : … », as on `jarvis-barehands`.
- **Deferral.** During a brain turn the Control Center answers 202 `scheduled`
  (`board_routes.py`); the tool returns `status: "scheduled"`. Outside a turn:
  `applied`. `board_switch` first reads the target: archived →
  `board_archived`, nothing posted (a deferred refusal would only reach the
  journal); already active → `unchanged` **unless** a switch to another Board
  is pending (`GET /api/boards/pending`), in which case it is sent and replaces
  it (Slice 05 QA rework, B3). Same turn, second call (B1): a second
  `session_new` is **merged** by the Control Center with the pending one
  (`merged: true`, one Session opens, `board.request.deferred_merged`); a
  second `board_switch` **replaces** the pending one (`replaced_board_id`,
  the last wins). Outside a turn `session_new` names the Session it read as
  `expected_session_id`, so a stale call is refused by Core (`session_closed`)
  instead of opening two Sessions; a deferred one that turns stale is
  `board.request.deferred_stale` (info), never an error.
- **Unknown outcome (QA 06/07 rework, point 3).** Immediate transitions wait
  `console_boards.TRANSITION_TIMEOUT_S` = `CORE_TRANSITION_TIMEOUT_S` + 20 s
  (170 s; was 45 s, below the 60 s host activation), so the relay always
  answers first. Its 504 `core_transition_timeout` is not a refusal: the tool
  returns `status: "unknown"` with the note « Je vérifie si c'est fait. »
  (journal `board.tool_unknown`, warning); the brain re-reads
  `session_current`. A 504 on a read stays a coded tool error.
- **Voice replies (B2).** `note` is one short sentence to say as is, no
  internal vocabulary: « Passage sur « X » à la fin de ta réponse. », « Tu es
  sur « X ». », « Déjà sur « X ». », « Tu restes sur « X ». », « Nouvelle
  session à la fin de ta réponse. », « Nouvelle session ouverte. ». The facts
  (the current answer is still spoken here; conversation and voice move at the
  end of the turn; the left Board keeps its background work) are in the tool
  descriptions and `_SERVER_INSTRUCTIONS`, which ask for one short spoken
  sentence.
- **Errors.** The relay envelope `{"error": {code, message}}` becomes a tool
  error `Refus <code> : <sentence> (<source> : <message>)`, code kept, source
  `Core` for a Core code and `Control Center` for the relay's own codes
  (`console_boards.RELAY_CODES`) or a body without the envelope (B3);
  `binding_not_found` / `binding_conflict` say what to do next
  (`ConsoleToolError.code`, journal `board.tool_failed`, warning):
  `board_not_found`, `board_archived`, `board_is_active`, `session_closed`,
  `session_not_found`, `binding_not_found`, `binding_conflict`,
  `brain_not_foreground`, `board_activation_failed`,
  `board_switch_rolled_back`, `invalid_title`, `context_summary_too_long`,
  `invalid_board`, `invalid_session`, `invalid_binding`, `invalid_request`,
  `core_unreachable`, `core_unconfigured`, `core_unavailable`,
  `core_transition_timeout` (`console_boards.ERROR_SENTENCES`); an unknown code keeps its name, a body
  without envelope is `http_<status>`; transport: `control_center_unreachable`,
  `control_center_timeout`, `control_center_bad_response`. Success journaled
  `board.tool` (info).
- **Context cost.** `jarvis-console` tools 2 918 B → **9 616 B** (12 tools,
  after the Slice 05 QA rework) **+ server instructions
  (`_SERVER_INSTRUCTIONS`) 1 326 B = 10 942 B** model-visible. Written reason:
  nine new tools, one per V1 Board/Session action of the Control Center.
  Gates in `tests/unit/test_mcp_catalog.py`: tools
  `CONSOLE_CONTEXT_BUDGET_BYTES = 10 000`, instructions
  `CONSOLE_INSTRUCTIONS_BUDGET_BYTES = 1 500`. The display baseline is
  untouched.
- **Inspector.** No code change: tools render from the API; the `settings` tab
  label becomes « Réglages et Boards » (`CATEGORY_LABELS`). No test caps the
  console tool count; `jarvis-display` stays capped at 13.

Tests: `tests/unit/test_settings_mcp.py` (catalog, fake Control Center for every
tool and every code, `scheduled`, route parity with `BoardSessionRoutes`, real
Control Center + real Core including the in-turn deferral),
`tests/unit/test_mcp_catalog.py` (console `tools/list` == catalog, in order;
cost gate).

### 10.10 Generic MCP plugin runtime, Slice 08 — implementation facts (release)

Handoff `tasks/jarvis-generic-mcp-plugin-runtime/`, Slice 08 phase A
(2026-09-30). Contract: [plugins.md](plugins.md); binding design: that
handoff's `docs/06-resolved-architecture.md` (ARCH), errata E1–E23.

- **Catalog surface.** Five catalog servers: `jarvis-display` (13 tools),
  `jarvis-console` (12), `jarvis-barehands` (16), `jarvis-drive` (7,
  `operator`, never in `list_tools`) and `jarvis-tools` (2: `list_tools`,
  `call_tool`, the only discovery meta-tools). Plugin servers are merged into
  `GET /api/mcp/tools` with registration `managed` (§2, §8); their availability
  follows §4.3 (`advertised` = enabled ∧ connected, E5/E11).
- **Measured model-context cost** (`context_bytes`, same formula as §10.3,
  2026-09-30): `jarvis-display` 31 864 B (baseline 33 090 B, unchanged),
  `jarvis-console` 9 616 B (budget 10 000 B, unchanged), `jarvis-barehands`
  20 515 B, `jarvis-drive` 2 126 B, `jarvis-tools` **1 544 B** (`list_tools`
  923 B + `call_tool` 621 B; bound 2 500 B) + server instructions 584 B
  (bound 1 200 B). Tests: `test_mcp_catalog.py` (display/console gates,
  unchanged), `test_tools_gateway_mcp.py::test_s8_context_cost_of_the_final_gateway_surface`.
- **`list_tools` response** (bound 24 576 B, plugins.md §6.3): with the three
  natives a Claude conversation declares at most and 500 heavy plugin tools
  (8 described properties each), the first page measures 15 609–20 501 B over
  five intents and every cursor page stays ≤ 20 501 B; the domain worst case
  (descriptions at the 4 096 B bound) peaks at 23 469 B. Realistic catalog
  (three mail tools): 669–5 561 B. Tests:
  `test_tool_discovery.py::test_s8_*`, `test_tools_gateway_mcp.py::test_s8_*`.
  The real Circuit Toolbox catalog is measured in phase B (live login).
- **Secrets.** `tests/unit/test_mcp_secret_sentinel.py` drives a sentinel
  credential (bearer and OAuth) through the Control Center relay, Core, the
  fake remote server and the gateway: absent from every `/api/*` and
  `/v1/mcp/*` response, every model-facing result, `tools-mcp.json`, the Codex
  overrides, `trace.jsonl`/`errors.jsonl` and every file of the run; present in
  `jarvis.sqlite3` only sealed. A redaction mutation makes it fail.
- **Restart.** `tests/integration/test_mcp_plugin_restart.py`: after a Core
  restart, registry rows, `enabled` flags and sealed blobs are byte-identical;
  enabled OAuth, bearer and unauthenticated plugins reconnect with no UI and no
  new authorization; an OAuth token expired without refresh shows `expired`
  with **no** network request; a disabled plugin stays disconnected and
  untouched; a Control Center restart changes nothing.
- **Inspector accessibility.** The two « Schéma brut (JSON) » `<pre>` blocks
  scroll with a long plugin schema: they are keyboard-focusable
  (`tabindex="0"`), named regions (`role="region"`, `aria-label`) with a
  `:focus-visible` ring (axe `scrollable-region-focusable`).
- **Known pre-existing fact, not this handoff's.** The Claude conversation
  brain is launched **without** `--strict-mcp-config` (`claude_local.py`, only
  `RESTRICTED_PROFILES` pass it), so the user-level MCP servers of the operator
  (`jarvis-drive`, claude.ai connectors, `claude-in-chrome`) load next to the
  four Jarvis `--mcp-config` servers. `list_tools` never lists them (ARCH C8);
  the model still reaches them through ToolSearch.
