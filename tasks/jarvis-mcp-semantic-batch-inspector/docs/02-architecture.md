# Target architecture


## SceneSelection
Own a strict serializable selection contract in the scene domain. Required vocabulary: explicit ids; `kind` and plural `kinds`; category; origin; visibility; exec_state; work; constellation root with optional depth; group membership; near; small bounded exclusion if needed. Filters combine deterministically and are bounded.


## Canonical constellation
1. Every active explicit `SceneRelation` connects both endpoints for traversal regardless of direction.
2. Runtime attention signals gain a virtual edge to their canonical owner when `signal_owners(snapshot)` can determine one, including work-ref fallback.
3. Archived objects never participate.
4. Optional depth counts graph hops; absent means the whole connected component.
5. Ordering is deterministic.


Python domain is authoritative. Browser local logic may remain for instant UX only if conformance fixtures prevent semantic drift.


## Atomic operations
Implement selection-native patch/update, translate, pin/unpin, and generic archive. The reducer resolves selection from the exact snapshot it mutates, validates the full target set before mutation, and either emits one patch/revision or rejects with none.


### Translation
Accept relative `dx/dy`. Determine one common effective vector legal for all selected placed objects. Never independently clamp members. If full movement is impossible, deterministically clamp/scale the vector as a group and return requested/effective deltas. Prefer atomic refusal for unplaced targets unless the contract deliberately chooses another deterministic behavior.


## MCP adapter
Scene MCP tools map one-to-one to semantic domain operations. No per-target adapter loop for conceptual batches. Exact names follow repository conventions. Redundant granular aliases should be removed/deprecated rather than accumulated.


## Canonical MCP catalog
Every inspector-visible tool has: wire name, server, semantic category, human label, summary/description, input schema, output schema, parameter required/optional/default/constraints, side-effect class, atomicity note, availability state, deprecation info. Prefer direct safe FastMCP introspection or shared descriptors consumed by registration. Hand-maintained frontend copies are forbidden. Replace opaque `dict[str, Any]` results where a concrete schema is known.


## Control Center catalog API
Provide read-only list/detail operations analogous to `list_tools()` and `get_tool(name)`. They are internal catalog operations, not automatically MCP tools. Report known/configured/advertised/disabled/deprecated states where provable without invoking tools. Never expose secrets, token paths or credential/env values.


## Inspector UI
Add `MCP` to `ERR / TRC / LAB / CNV / SET / AGT`. Open a dedicated modal/full-screen surface with status summary, search, tabs General / Stars / Scène / Settings / Bare Hands, compact cards by default, per-card/global detail expansion, parameter table, readable nested output schema, secondary raw schema disclosure, keyboard/focus/responsive support. No arbitrary tool execution in this task.