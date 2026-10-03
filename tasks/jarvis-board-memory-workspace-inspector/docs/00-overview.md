# 00 - Overview

## Goal

Implement a coherent durable memory layer for Boards and make the complete Session/Board/memory/artifact relationship inspectable and manageable by both the human operator and Jarvis agents.

## Scope

### In scope

- a free-form filesystem workspace owned by each Board;
- structured indexing/identity/lifecycle for that workspace in backend persistence;
- integration between active SessionContext and Board memory on Board activation/revisit;
- historical read/inspection without foreground activation;
- Board kind metadata (`empty | meeting | presentation`) if absent on the execution baseline;
- Board/session/binding/conversation/agent relationship inspection;
- artifact/provenance inspection through the prerequisite generic artifact registry;
- safe Board-memory tree/read/search/write/move/delete operations;
- complete Board semantic management: list/get/create/update/rename/archive/switch;
- Session history inspection in addition to current/new;
- dedicated `jarvis-workspace` MCP server and MCP catalog registration;
- proof that intended delegated agents can use workspace inspection tools;
- deep Control Center Sessions & Boards Manager from top/settings controls;
- lightweight Board list/switcher, preferably by evolving existing `#boardsHud`;
- browser/integration/E2E/real-agent validation and canonical documentation.

### Non-goals

- Meeting/Presentation live start/end implementation;
- OFF/SLEEP wake policy;
- audio/capture implementation itself;
- a rigid universal memory schema inside a Board workspace;
- storing large artifact media in SQLite;
- raw arbitrary SQL access from UI or MCP;
- unrestricted host filesystem access from memory tools;
- a second artifact registry;
- automatic semantic merging of two unrelated Boards;
- graph-database introduction merely to draw relationships;
- deleting or rewriting historical Sessions just to make the manager look tidy.

## Product outcome

A user can open a manager and answer, without guessing:

- Which Session is open?
- Which Board is active?
- Which Boards exist and what kind are they?
- Which conversation/agent binding belongs to a Session/Board?
- What memory files does a Board contain?
- Which tasks/artifacts/projects are referenced?
- Which artifacts were derived from which evidence?
- What is foreground vs historical/background?
- Where is the actual data stored?

Jarvis can answer the same questions using MCP and can inspect an old Board through a sub-agent without switching the user's active Board.
