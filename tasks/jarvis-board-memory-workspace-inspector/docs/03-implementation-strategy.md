# 03 - Implementation strategy

## Dependency first

This handoff was planned against `main` before `jarvis-session-context-recording-runtime` was visible in product code. Slice 00 must inspect the real execution baseline.

If the prerequisite handoff has landed:

- reuse its durable Session semantics;
- reuse `SessionContext` lifecycle/workspace contracts;
- reuse Artifact registry/relations/activity ledger;
- add Board memory as a distinct durable workspace layer and integrate it.

If it has not landed:

- do not duplicate SessionContext/artifact contracts here;
- either block dependent Slices or execute only truly independent Board-memory contract work after the PM explicitly reconciles dependency ordering.

## Rollout order

1. Freeze domain vocabulary and Board-memory relationship contract.
2. Add filesystem/persistence primitives with safety and migration tests.
3. Integrate Board activation/hydration with SessionContext.
4. Add read/inspect APIs before mutation-heavy MCP/UI.
5. Add memory mutations and historical analysis capabilities.
6. Create/migrate `jarvis-workspace` MCP surface and prove agent/sub-agent access.
7. Build deep manager UI.
8. Refine quick Board browser.
9. Run E2E, trace and migration/compatibility rollout.

## Migration principles

- existing Board IDs remain stable;
- existing Board rows decode with default `board_kind=empty` if a new field is added;
- existing `context_summary` remains a compact per-turn summary/index, not replaced by dumping memory files;
- existing Board refs remain valid;
- existing Board UI routes keep semantics unless deliberately versioned;
- moving MCP tools between servers must avoid duplicate model-visible tools and keep clear release notes/tests;
- no data loss when creating the Board memory root for pre-existing Boards;
- no automatic rewrite of old Board summaries into invented memory content.

## Tool-surface budget

`jarvis-console` already grew from settings-only to 12 tools. The new server exists partly to keep responsibilities and context budgets coherent.

Before finalizing `jarvis-workspace` tool count:

- measure actual model-visible bytes;
- prefer compact semantic read tools;
- use typed outputs where they help;
- avoid exposing a generic raw-file API with unbounded output;
- register all metadata in the shared MCP catalog source of truth;
- update the inspector/category labels and parity gates.
