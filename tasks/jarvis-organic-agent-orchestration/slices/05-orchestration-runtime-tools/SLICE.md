# Slice 05 — Mission Owner orchestration runtime & typed tools

## Goal

Give Mission Owners typed runtime capabilities to create/manage agents and sub-missions organically, with local autonomy and parent supervision.

## Dependencies

00-project-manager-readiness, 01-agent-role-mission-contracts, 02-agent-relation-contracts, 03-work-state-mission-history, 04-role-registry-loadouts-methods

## Dispatch gate

Do not start this Slice until Slice 00 is `READY` and this Slice's `metadata.json.task_type` has been replaced with an exact approved Workspace Task Type. One Work Agent owns this Slice.

## Scope — in

- Spawn/delegate agent with explicit role and mission/sub-mission identity.
- Assign local Mission Owner responsibility.
- Inspect mission/team state.
- Parent redirect/stop seam using current cancellation/intent authority.
- Capability checks from Role Registry.
- Resource-safety caps and failure semantics.
- Agent instruction layer teaching ownership of outcome/quality and organic use of orchestration tools.

## Scope — out

- Mandatory decomposition.
- Precomputed workflow plan.
- UI relation rendering.
- Automatic relation semantics beyond what is explicitly created.

## Implementation steps

1. Audit actual agent spawn/sub-agent tool path (Claude/Codex capability differences) and tool/MCP ownership.
2. Define typed orchestration service and tool schemas with Core as semantic owner.
3. Create sub-mission atomically enough that the child has role/mission metadata before it is exposed as meaningful work.
4. Support local Mission Owner autonomy with parent mission reference and intervention path.
5. Enforce role capability permissions mechanically.
6. Add bounded safety caps for recursion/team size/rate; document them as resource safety, not a “minimum complexity” policy.
7. Add Mission Owner prompt/brief guidance: judge sufficiency, use tools when warranted, own final quality.
8. Run deterministic + real-agent trace scenarios for trivial and organically growing tasks.

## Files likely touched

- agent spawn/task runtime modules found in audit
- Core mission orchestration service
- MCP/tool contract/catalogue modules
- brain/agent brief prompt layers
- tests/unit/integration/replay orchestration

## Architecture constraints

- Preserve Core Work State as canonical live execution truth.
- Preserve Scene as projection, never a second execution state machine.
- No speculative/planned future graph.
- No rigid orchestration workflow/protocol introduced under the name Work Method or Relation.
- Follow `CLAUDE.md`; do not start/restart the user's live JARVIS without explicit permission.
- Any new schema evolves through a versioned migration and schema snapshot.

## Required implementation skills

caveman; coding-guideline

## Independent QA

Required: code-review; qa-verification; runtime-validation; agent-trace-analysis.

QA is independent of the implementing Work Agent. QA cannot mark Human checks passed.

## Human Validation

- `HV-ORG-05-01` — Run one clearly trivial action and confirm JARVIS does not artificially expand it into a team solely because orchestration tools exist.

See `human-validation.json`.

## Acceptance criteria

- [ ] A role-capable Mission Owner can spawn/delegate explicit roles/sub-missions.
- [ ] A nested sub-mission owner can create its own team without parent micromanagement.
- [ ] Parent can supervise/redirect/stop using existing authority.
- [ ] A trivial task can remain one agent.
- [ ] No future/planned node is created by considering an action.
- [ ] All semantic creation is explicit and inspectable.

## Documentation updates

Update the canonical repository docs for every contract made authoritative by this Slice. Do not leave handoff-only truth after code lands.

## Readiness amendments (Slice 00, 2026-10-20)

Audited HEAD `main@336f21be`. Evidence: `references/readiness-audit.md`. These amendments override the stale parts of this Slice; they do not change any locked decision of `docs/01-decisions.md`. Task Type gate: resolved (`waived-by-agent-0`). Run the freshness check of `references/readiness-audit.md` §7 before dispatch.

- **Actual spawn path:** Core launches no agent. Agents are spawned by the Claude CLI `Agent` tool (brain or nested sub-agents); the only binding point is the `PreToolUse` hook (`jarvis/runtime/routing_hook.py`), which already rewrites `model` and signs the brief (charter, playbook, role method, loadout). Orchestration tools therefore register semantics in Core (MCP/tool path to be audited: `jarvis-tools` gateway, `jarvis/core/mcp_plugin_service.py`, `claude_local.py` `--mcp-config`) and/or are bound through the hook; they cannot replace the `Agent` call.
- **Nested spawn proven** (readiness audit §8, N3, CLI 2.1.304): sub-agent `Agent` calls work (`spawn_depth` 2, `parent_tool_use_id`), and the `PreToolUse` hook fires for them with the caller's `agent_id`. Still to confirm in the sandbox: that sub-agents see Jarvis's own MCP servers passed by `--mcp-config` (`jarvis-tools`; session-level MCP servers were visible in the probe), depth beyond 2, and custom agent types with reduced tool lists. Codex reports no subtasks (`subtasks_supported` false).
- **Role source (D25):** wire the hook as the source of the semantic facts sent to Core (contract from Slice 03); `agent_tasks.py:1011` stays diagnostic.
- I-004 decided by agent 0 (`6f2ca77d`): no precondition left. The brain prompt rule on ephemeral is changed by Slice 07, not here.
