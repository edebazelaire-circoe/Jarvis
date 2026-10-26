# Product edition (contract)

Canonical contract, documentation **Level 3**: vocabulary, contract, one
reusable policy implementation and conformance tests. Handoff
`tasks/jarvis-presentation-edition-v1/` (Slice 01). Board vocabulary:
[boards.md](boards.md) › *Board type*.

| What | Code | Proof |
| --- | --- | --- |
| Edition values, policy, resolution, availability payload | `jarvis/domain/product_edition.py` | `tests/unit/test_product_edition.py` |
| Core admission (create, switch, `ensure_default`) | `jarvis/core/board_service.py` | same, plus `test_board_service.py` (full edition unchanged) |
| Startup restore fallback | `jarvis/core/session_manager.py` (`_start_board`, `_edition_fallback_board`) | same, plus `test_session_manager.py` |
| Protocol and relay | `GET /v1/boards/edition` (`jarvis/protocol/server.py`), `GET /api/boards/edition` (`jarvis/runtime/board_routes.py`) | same, plus `test_board_protocol.py` |
| MCP `jarvis-workspace` | `jarvis/runtime/workspace_mcp.py` (`build_server(edition=…)`, `mcp_config`), `jarvis/runtime/workspace_boards.py` (`switch_board` pre-check) | same, plus `test_workspace_mcp.py` |
| Brain prompt | `jarvis/runtime/claude_local.py` (`workspace_prompt_for`), renderer `prompt_catalog._brain_workspace` | same, plus `test_prompt_registry.py` |

## Editions

A JARVIS process runs **one** product edition. It decides which Board types
(`BoardKind`) can be created and activated. It is a policy over shared code:
no Board type is deleted from the code base.

| Edition | Available Board kinds | Default kind (create without `board_kind`, Board `default`) | Use |
| --- | --- | --- | --- |
| `full` | `assistant`, `presentation`, `meeting` | `assistant` | development; the repository default; behaviour identical to before this contract |
| `presentation` | `presentation` | `presentation` | Presentation Edition V1 (distributed product) |

Two axes stay separate: **availability** (this contract: can a Board of this
kind be created/activated) and **behaviour maturity** (`InteractionModeStatus`
READY/PLANNED of the derived mode, [interaction-mode.md](interaction-mode.md)).
In `full`, a Réunion Board is available while its behaviour is still
`planned` (it behaves as assistant).

## Selection

`resolve_product_edition(environ, installed_default=None)`:

1. `JARVIS_PRODUCT_EDITION` (`full` | `presentation`, trimmed, case-insensitive);
2. else `installed_default` — reserved for the installed product, which will
   fix `presentation` (Slice 02 of the handoff owns installed identity);
3. else `full`.

An empty value counts as absent. An unknown value raises `ConfigurationError`:
Core refuses to start (resolved in `app.py:_run_core_v2` before anything is
written). It never falls back to `full`, which would reopen the locked kinds.

The value is read from the environment by every process that needs it: Core
(admission, the authority), the Control Center (brain prompt variable, the
`--mcp-config` document) and the `jarvis-workspace` MCP server. The Control
Center writes it **explicitly** into `runtime/workspace-mcp.json`
(`env.JARVIS_PRODUCT_EDITION`), so the tool schema the brain sees follows the
Control Center's edition whatever the CLI's environment. Core stays the
authority: a process started with another edition can show a wider schema, it
cannot create or activate a refused kind.

## Availability

`ProductEditionPolicy.to_payload()` is the only availability table. Nothing
else (UI, MCP, prompt) keeps its own list:

```json
{"edition": "presentation", "default_board_kind": "presentation",
 "board_kinds": [
   {"board_kind": "assistant", "availability": "unavailable", "available": false, "behavior_status": "ready"},
   {"board_kind": "presentation", "availability": "available", "available": true, "behavior_status": "ready"},
   {"board_kind": "meeting", "availability": "unavailable", "available": false, "behavior_status": "planned"}]}
```

Served by Core `GET /v1/boards/edition` (no query; a fixed segment before
`/v1/boards/{board_id}`, like `active`) and relayed unchanged by the Control
Center `GET /api/boards/edition`. A product UI shows `unavailable` kinds as
« À venir / indisponible » and offers no action on them; it reads a Board's
availability from its `board_kind` and this payload.

## Refusal

`board_kind_unavailable` (`BoardErrorCode`, HTTP **409**, the same family as
`board_kind_immutable`). Raised by `ProductEditionPolicy.ensure_available`:

| Path | When | Effect |
| --- | --- | --- |
| `BoardService.create` (`POST /v1/boards`, `POST /api/boards`, MCP `board_create`) | requested kind not available; `empty` (deprecated alias of `assistant`) included | nothing written; trace `core.board.kind_unavailable_refused` (warning, `action: create`) |
| `BoardService.switch` (`POST /v1/boards/switch`, `/api/boards/switch`, MCP and Tool Brain `board_switch`) | target Board's kind not available — checked after `board_not_found` / `board_archived`, before the no-op branch and before any host activation | nothing written, active Board unchanged; trace `core.board.kind_unavailable_refused` (`action: switch`, `origin`) |
| MCP `board_switch` (`BoardTools.switch_board`) | the Board read before sending has an unavailable kind | refused **before** sending, like an archived Board: a brain switch deferred during a turn would only report Core's refusal to the journal; trace `board.tool_failed` |

The brain reads `ERROR_SENTENCES["board_kind_unavailable"]`: not available in
this edition, nothing written, do not offer it again, `board_inspect` to look
at an old Board of that kind.

## Startup restore

Core has no « no Board » state: Voice needs a conversation of truth, so a
Session is always open on an active Board. With an edition that restricts
kinds:

1. `ensure_default` (empty table) creates the `default` Board with the
   edition's default kind (`presentation`). An existing `default` is never
   rewritten.
2. `SessionManager._start_board` (resume of the open Session, or a new
   Session after a closed one) keeps the last active Board only if it is
   active **and** available. Otherwise (trace
   `core.session.last_board_unavailable`, `reason: kind_unavailable`):
   - the available Board opened most recently (`last_opened_at`, then
     `created_at`) is chosen;
   - none: a new Board titled « Présentation » of the edition's default kind is
     created (`BoardService.create`).
   Trace `core.session.edition_fallback` (`created: true|false`). Replayable:
   the next start finds that Board.
3. A resumed Session visits the fallback Board like a switch; the legacy Board
   stays in `visited_board_ids`, its binding is reconciled as for an archived
   active Board.

In `full`, `_start_board` is unchanged (last active Board, else `default`, else
the first active Board).

## Legacy Boards

Boards of an unavailable kind (written by a `full` JARVIS, or before an edition
switch) are **preserved intact**: never rewritten, re-typed, deleted or
archived by the edition. They stay listed, readable (`board_get`,
`board_inspect`, memory reads), editable (title, summary, refs) and archivable.
They can never become active through Core, the protocol, the relay or MCP.
Running the same data root again in `full` makes them usable again: the edition
changes no stored data, so no schema migration exists for it.

## Brain prompt

The Boards instruction (`BRAIN_WORKSPACE_PROMPT`) carries one line about Board
kinds. The conversation launch passes the edition as prompt variable
`product_edition`; the renderer `backend.claude.conversation.workspace`
(`prompt_catalog._brain_workspace` → `claude_local.workspace_prompt_for`)
replaces that line by `BRAIN_WORKSPACE_PRESENTATION_KINDS_LINE` when the
edition restricts kinds: every Board is a Presentation Board, Assistant and
Réunion are not offered, an old Board of another kind does not open
(`board_kind_unavailable`). `full`, absent or unknown: the prompt is byte for
byte the previous one. The MCP schema of `board_create` follows the same
edition: with a single available kind it has **no** `board_kind` argument (an
attempt is « Arguments inconnus », nothing sent) and the tool sends that kind.

## Out of scope (later Slices)

- installed identity and the `presentation` default for the installed product
  (Slice 02);
- product UI for unavailable kinds (Slice 08); the current Boards control still
  offers the three kinds in `full` and gets the 409 in `presentation`;
- agent confinement (Slice 04).
