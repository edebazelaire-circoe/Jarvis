# 02 - Target architecture

## 1. Board structured state

Extend the existing `Board` contract only where needed. Candidate additive field:

```text
board_kind: empty | meeting | presentation
```

Do not overload `interaction_mode` with Board taxonomy. `board_kind` answers "what kind of workspace is this?"; future Jarvis profile/presence answers "how is Jarvis behaving now?".

Exact wire/storage migration must be chosen after the fresh audit. Preserve backwards decoding for existing Boards.

## 2. Board memory workspace

Recommended durable layout, final root naming subject to existing local-data conventions:

```text
<data_root>/boards/<board_id>/
  memory/
    ... agent-owned free-form files ...
```

Backend owns:

- Board -> workspace locator/path derivation;
- root creation/repair policy;
- path safety;
- file metadata used by the inspector;
- audit/activity events for semantic memory operations when appropriate.

Agent owns organization under `memory/`.

Do not make one mandatory template. A Board may naturally contain `summary.md`, `research/`, `meeting.md`, `contract/`, etc., but those are conventions, not schema.

## 3. SessionContext relationship

Assuming the prerequisite task has landed:

```text
JarvisSession
  +-- one active SessionContext

Board
  +-- durable memory workspace

Board activation
  -> switch existing Board binding / conversation authority
  -> identify target Board memory
  -> hydrate the active agent with a compact Board brief + pointers
  -> expose deeper Board memory through retrieval/tools
```

Do not inject an unbounded directory or full artifact history into every turn.

A practical runtime brief may include:

- board id/title/kind;
- compact context summary/manifest;
- important refs;
- recent relevant activity cursor;
- pointers to Board memory tree/search and artifact queries.

The active agent may maintain its SessionContext freely while durable Board-specific knowledge is written deliberately into Board memory.

## 4. Historical inspection

Historical queries target explicit IDs and remain side-effect free:

```text
inspect_session(jsess_old)
inspect_board(board_old)
board_memory_tree(board_old)
board_memory_read(board_old, "notes.md")
artifact_search(board_id=board_old, ...)
```

They must not call Board switch internally.

This is the key enabling behavior for:

> "Envoie un agent vérifier ce qu'on avait sur l'ancien Board client."

The parent can delegate; the child uses read-only workspace tools against explicit IDs.

## 5. Relationship model

The inspector/API should be able to materialize a stable relationship view without a new graph database:

```text
Session
  -> active/visited Boards
  -> SessionContext(s) [prerequisite]

(Session, Board)
  -> BoardConversationBinding
      -> Core conversation_id
      -> agent_cli / agent_session_id / lifecycle

Board
  -> task_refs
  -> artifact_refs
  -> project_refs
  -> memory workspace
  -> scene ref

Artifact
  -> session_id? / context_id? / board association/index
  -> payload ref
  -> ArtifactRelation provenance edges
```

If artifact rows from the prerequisite do not yet support Board association, prefer an explicit association/index relation over copying artifact metadata into Board JSON.

## 6. Workspace service/API

Introduce a coherent service boundary rather than letting the UI browse disk directly. Candidate capabilities:

### Board/session

- list/get/create/update/archive/switch Boards;
- current/list/get Sessions;
- inspect binding/conversation/agent relations;
- list Board associations for a Session and vice versa.

### Board memory

- tree/list;
- stat/read;
- bounded search;
- create/write/patch or replace text file;
- mkdir;
- move/rename;
- delete with explicit destructive semantics;
- optional bounded diff/history only if supported by existing storage conventions.

### Artifacts/activity

- list/search artifacts by Board/Session/Context/time/kind;
- inspect one artifact;
- follow provenance relations;
- inspect relevant canonical activity/trace references.

Do not expose arbitrary filesystem globbing outside the Board root.

## 7. `jarvis-workspace` MCP server

Create a new native server registered through the existing MCP catalog metadata.

Migrate existing intents from `jarvis-console`:

```text
board_list
board_get
board_get_active
board_create
board_update
board_archive
board_switch
session_current
session_new
```

Add missing intents, exact names finalized after context-budget/tool-surface audit:

```text
session_list / session_get
workspace_inspect or relation inspection
board_memory_tree
board_memory_read
board_memory_search
board_memory_write
board_memory_move
board_memory_delete
artifact_list/search/get
artifact_relations
```

Prefer semantic tools and bounded multi-purpose reads over dozens of one-off helpers. Side-effect, idempotence, destructive classification, schemas, output budgets and availability follow `docs/mcp/tool-contract.md`.

Update native MCP launch configuration so the primary Brain and intended delegated inspection agents receive the server. Prove with real request/trace evidence rather than assuming CLI inheritance.

## 8. Human UI

### Deep manager

Add a top/settings control opening a dedicated manager with at least:

- overview/current state;
- Sessions;
- Boards;
- relationships/bindings;
- memory file tree + safe viewer/editor operations;
- artifacts + provenance;
- activity/trace links where useful.

This is an engineering/operability surface: clarity beats hiding all IDs.

### Quick Board browser

Reuse/evolve `#boardsHud` and `control_center_boards.js` for everyday Board list/create/rename/archive/switch. Show Board kind when available. Do not make the deep manager the only way to switch Boards.

## 9. Security/invariants

- no path traversal;
- no symlink escape;
- no arbitrary host file reads;
- archived/active Board rules remain enforced by the domain;
- historical reads never promote a binding;
- writes to a Board memory workspace require explicit target Board;
- destructive file deletes are clearly typed and traced;
- Session/Board IDs are validated centrally;
- UI never paints optimistic truth for switch/lifecycle state when server confirmation is authoritative.
