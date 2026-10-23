# 02 - Target Architecture

## 1. Canonical runtime graph

The Architecture tab must render a server/runtime-owned graph snapshot. A proposed contract shape is below; exact module names may change after Slice 00, but the semantics are locked.

```text
ArchitectureSnapshot
  revision
  nodes[]
  ports[]
  connections[]
  layout_revision (optional, UI-only)
```

### Brain/node

A brain node needs at least:

- stable `brain_id`;
- display label/type;
- runtime availability/health;
- active/enabled state;
- whether activation itself is mutable;
- capabilities/ports exposed for architecture wiring;
- config capability descriptor (what fields are editable for this brain);
- optional immutable/system flag.

External endpoints (Audio Input, Audio Output, possibly Wake Word or other ingress/egress) use the same graph model or a compatible endpoint kind. They are not fake brains.

### Port

A port must make connection compatibility explicit:

- stable port id;
- source or target direction;
- channel/data kind (audio, text/request, response, tool request/result, event/impulse, etc.);
- cardinality if relevant;
- required/optional constraints;
- compatibility family.

### Connection

A connection must include:

- stable id;
- source node + source port;
- target node + target port;
- direction;
- semantic channel/purpose;
- `enabled` state;
- mutability: `required_locked`, `toggleable`, `creatable_removable` (or equivalent canonical values);
- a human-readable reason/impact summary;
- runtime binding identity so a mutation cannot become UI-only state.

## 2. Mutation invariants

A graph write is a runtime transaction, not a canvas edit.

- Locked links reject disable/delete with a stable error code and reason.
- New links are accepted only when source/target ports are compatible and the runtime can actually bind them.
- Disabling a valid toggleable link must alter the real dispatch/call path.
- Failed runtime application must roll back or leave the stored topology unchanged.
- The returned snapshot after a write is the authoritative state; the browser does not assume success optimistically forever.
- Layout position changes are stored separately from topology so drag/drop cannot change behavior.

## 3. Baseline graph

Slice 00 must re-audit `main` and build the default graph from actual runtime wiring. The user expects, at minimum when still present:

- Audio Input;
- Voice Brain;
- Core Brain;
- Tool Brain;
- Audio Output.

Do not add Routing/Reflex/Vision/Task brains merely because an earlier mockup contained them. They appear only when they exist as real runtime nodes.

## 4. Brain configuration contract

Brain configuration is generic and data-driven so future brains can participate without a page rewrite.

Proposed shared fields:

- `brain_id` / immutable identity;
- display name where editable;
- provider/model (from live catalog and capability-filtered);
- mission/responsibilities/prerogatives;
- brain-specific instructions/prompt override when supported;
- active/enabled when runtime allows it;
- delegation tendency: `never`, `rare`, `standard`, `proactive`, `exploratory`;
- read-only connection summary and link to graph editing;
- validation/readiness diagnostics needed to explain why a field cannot be changed.

Connection mutation remains canonical on the graph. The popup may summarize connections but must not create a second persistence contract.

## 5. Delegation versus role routing

A brain emits a delegation request according to its own tendency/mission. It should identify the required role/capability, not pick a hard-coded provider/model.

The global sub-agent resolver then maps that role to ordered available candidates.

```text
Brain policy -> role request -> role routing policy -> candidate selection -> sub-agent instance
```

This boundary lets one brain delegate frequently and another never delegate while both share the same canonical Code/Research/QA candidate configuration.

## 6. Sub-agent role policy

Build on existing `SubagentRole`, `CandidateRef`, model catalog and fallback mechanics.

Target role policy needs:

- `role_id` (must resolve through the canonical role registry);
- ordered preferred candidates (`harness/agent + model`);
- candidate availability/readiness reason;
- fallback candidate/order semantics;
- compatibility/inheritance from the role's current `default_profile` while migrating;
- role tools/skills/loadout/Work Methods and instructions from canonical role data, not duplicated fields.

The current task-profile routing policy may remain as a compatibility layer during migration, but the new ordinary UI is role-oriented.

## 7. Ownership boundaries

To allow parallel implementation, Slices 01-03 build services/handlers in separate modules but do **not** all patch `control_center.py` concurrently. Slice 07 owns final route registration and hot-file integration.

Likewise, frontend Slices build separate modules/components and defer shared Settings shell wiring to Slice 07.
