# 04 - Testing and quality

## Global QA doctrine

Every implemented Slice receives `qa-verification`.

Add:

- `code-review` for code changes;
- `runtime-validation` for user-visible or runtime behavior;
- `agent-trace-analysis` for MCP tools, prompts, routing, native server advertisement, sub-agent access or agent runtime changes.

QA agents return evidence and findings. The Project Manager owns the decision: approve, rework, continue, add a Slice, create an Issue, or escalate.

A regression caused by the current Slice is blocking and cannot be parked in `Issues/`.

## Required automated coverage

### Domain/persistence

- Board kind backwards compatibility if added;
- Board workspace root derivation;
- path traversal rejection (`..`, absolute paths, encoded variants);
- symlink escape rejection;
- atomic/consistent file mutations where feasible;
- Board archive/active invariants unchanged;
- historical reads have zero Board-switch side effects;
- restart/reopen persistence;
- concurrent/duplicate requests where relevant.

### SessionContext integration

- switching A -> B -> A hydrates the right Board state;
- no memory cross-contamination between Boards;
- historical inspection of B while A is active leaves A foreground;
- restart reconstructs current Session/Context according to prerequisite semantics;
- compact hydration does not inject unbounded memory trees.

### Artifact relations

- Board/Session/Context filters return correct artifacts;
- provenance edges are preserved and traversable;
- missing/partial payloads are represented honestly;
- artifact inspection never mutates foreground state.

### API/MCP

- UI and MCP route/service parity;
- strict argument schemas and unknown-argument refusal;
- read/write/destructive annotations;
- context-budget gates;
- catalog parity with actual `tools/list`;
- `jarvis-workspace` advertised to the main Brain;
- real delegated-agent trace proving historical Board inspection without switch;
- migration removes duplicate Board tools from `jarvis-console` when workspace server is active.

### UI/browser

- deep manager renders large but bounded histories without freezing;
- stable loading/empty/error states;
- file tree cannot escape Board root;
- relationships show IDs and states correctly;
- quick Board switch retains current server-confirmed semantics and timeout handling;
- browser tests for create/rename/archive/switch and manager inspection.

## Human validation

Human checks are only for interaction quality that automated/runtime/browser evidence cannot establish, such as whether the deep manager is actually understandable at a glance and whether the quick Board browser remains pleasant to use.

Before asking for Human validation, exhaust machine checks and fix machine-detectable defects.
