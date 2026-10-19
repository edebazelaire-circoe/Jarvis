# Target architecture

## 1. Existing seams to extend

Repository audit at handoff creation found mature infrastructure that this task must reuse:

| Existing subsystem | Current role | Required evolution |
| --- | --- | --- |
| `jarvis/domain/work_state.py` + `jarvis/core/work_state.py` | canonical live normalized work truth | add explicit semantic metadata needed by mission orchestration without turning it into durable history |
| `AgentTaskTracker` + `TrackerWorkObserver` | provider observation / diagnostic | emit explicit role/mission metadata when known; never become canonical semantic store |
| `BrainContext.work` + `work_brief.py` | lets Brain see same work as UI | expose bounded role/mission/relationship summaries needed for supervision |
| `jarvis/domain/scene.py` + `SceneProjector` | persistent visual projection of work stars, parent links | project role identity and typed actual relations; exclude completed ephemeral nodes from durable history |
| `control_center_work.js` / Agents panel | task cards from Core | show role, ownership and relation summaries without changing source of truth |
| `LoadoutResolver.resolve(profile, role)` / routing hook | role-like loadout seam (`coder`, `reviewer`, `research`) | introduce canonical Role Registry and compatibility mapping |
| Conversation Events | durable redacted user/brain/subagent event record | add semantic mission/relation events only if needed for timeline/audit; do not store hidden reasoning |
| Prefab system | `jarvis.document`, `jarvis.table`, CIRCOE visual surfaces | become a preferred delivery path for serious reports/comparisons |

## 2. Layered model

```text
User turn / Brain decision
          │
          ▼
   Mission Runtime (Core-owned semantics)
   ├─ Mission / Sub-mission identities
   ├─ Mission Owner responsibility
   ├─ Role Registry + Work Method metadata
   ├─ Typed relations + explicit relation records
   └─ Orchestration capability surface
          │
          ├──────────────► agent provider / runtime (spawn work)
          │                         │
          │                         ▼ observations
          │                 Core Work State
          │                 (LIVE EXECUTION TRUTH)
          │                         │
          │                         ├──► Brain work context
          │                         ├──► Agents panel
          │                         └──► Scene projector
          │
          └──────────────► Durable Mission History
                            (semantic/history truth only)
                                      │
                                      ├──► Scene role/relation projection
                                      ├──► relation communication views
                                      └──► post-run inspection
```

### Non-negotiable ownership rule

`WorkStatus`, progress, active/ended state and provider observation remain owned by Work State. Durable Mission History may remember that Agent A had role X, owned Mission M, communicated with B, was in an Adversary relation, or handed off to C. It does **not** invent/rewrite A's execution status.

## 3. New domain concepts

### AgentRoleDefinition

Recommended pure domain shape (exact naming may adapt to current conventions):

```text
role_id                 stable token
name                    user-facing label
summary                 short purpose
prompt_layer            reusable instruction/prompt reference
allowed_profiles        compatibility with routing profiles
loadout_role            key/alias for LoadoutResolver
skills                   declared reusable skills
capabilities             orchestration/operational capabilities
visual                   icon, accent/category, badge/short label
work_methods             allowed/default heuristic method ids
can_own_mission          bool/capability
can_spawn                bool/capability
```

Role definitions should be inspectable and centrally registered. Do not scatter visual/color logic through frontend conditionals.

### Mission

A mission is an objective with a stable id and optional parent mission. It is not necessarily long-running. A sub-mission records its parent mission and its current/initial owner instance.

Recommended fields:

```text
mission_id
parent_mission_id?
root_mission_id
title / objective (bounded)
origin_task_kind?        e.g. code/research/design/general where known
owner_agent_instance_id
created_at / closed_at?
```

Do not encode a planned node sequence.

### AgentInstanceSemantic

Semantic record linked to live provider work identity:

```text
agent_instance_id
source + external_id / WorkItem identity
role_id                 immutable
ephemeral                immutable classification for history policy
mission_id
mission_owner            responsibility for this mission
parent_agent_instance_id?
created_at
```

Execution status is read from Work State, not duplicated as authoritative state here.

### WorkMethodDefinition

Heuristic guidance only:

```text
method_id
name
role_ids / applicability
principles[]
quality_checks[]
useful_relations[]       suggestions/capabilities, not ordered steps
promotion_provenance
version
```

No ordered DAG field in V1.

### AgentRelation

Recommended core shape:

```text
relation_id
kind = delegation | communication | adversary | qa | handoff
mission_id
participants[] or from/to endpoints according to kind
created_at / closed_at?
label / purpose (bounded)
board_id?                communication-capable relations
handoff_record_id?       handoff only
metadata                  strict per-kind schema, not arbitrary provider JSON
```

Adversary may need N participants. If Scene's relation model remains binary, represent the semantic relation as one mission relation with deterministic pairwise projected links or introduce a relation-group projection; do not distort the canonical semantic model merely to fit current binary rendering.

### RelationMessage

Explicit collaboration record:

```text
message_id
relation_id
author_agent_instance_id
audience participant ids
type = message | proposal | critique | decision | result_summary | question | handoff_note
text (bounded)
created_at
artifact_refs[]
```

No `reasoning`, `thinking`, hidden prompt, raw provider event or chain-of-thought field.

### HandoffPacket

Bounded structured transfer:

```text
handoff_id
relation_id
from_agent_instance_id
to_agent_instance_id
mission_id
objective
completed_work
key_decisions
open_points
artifact_refs
evidence_refs
recommended_next_action
created_at
```

## 4. Persistence

### Target

Use a Core-owned durable store for Mission History because the existing Work State is intentionally in-memory/short-retention and the user explicitly wants completed non-ephemeral topology to remain inspectable.

Preferred implementation if no equivalent store already exists at Slice 00:

- versioned additive tables in `jarvis.sqlite3` through `jarvis/adapters/sqlite_state.py`;
- Core service/port around those tables;
- follow `CLAUDE.md`: backup + `_MIGRATIONS` + `_SCHEMA_VERSION` + schema snapshot test;
- strict bounded payloads; no raw model/provider blob columns.

The PM must check current HEAD first. If an existing durable mission/history aggregate already landed, reuse it rather than adding tables.

### Ephemeral policy

Ephemeral instances are not persisted as durable history nodes after completion. Implementation must choose a race-safe behavior:

- while active: optional live Work State/Agents visibility is allowed;
- Scene/history: either never persist a scene star for an ephemeral instance, or ensure the runtime projection is non-durable and leaves no archived/history row. The simpler verifiable approach is preferred.

Do not silently delete unrelated scene objects to achieve this.

## 5. Orchestration capability surface

Mission Owners need typed capabilities, not prose-only conventions. Exact MCP/tool names should match current tool architecture, but the semantic operations are:

```text
spawn_agent(role_id, mission/objective, ephemeral?, owner_of_sub_mission?)
delegate(...)
create_relation(kind, participants, purpose)
open_communication(...)
post_relation_message(...)
request_qa(target, focus?)
create_adversary(participants/alternative briefs)
handoff(to_role, packet, ...)
inspect_mission(...)
inspect_relation(...)
close_relation(...)
```

A helper like `request_qa` may compile to `spawn_agent(role=qa)` + relation creation. There must still be one canonical semantic record, not parallel ad-hoc mechanisms.

Agents should be taught **when these tools can help**, not a fixed sequence in which they must use them.

## 6. Interviewer integration

Interviewer is an ordinary role with a specialized method:

- determine missing information that would materially change the work;
- ask concise questions progressively;
- consume evidence already available rather than re-asking;
- allow independent background investigation to proceed when useful;
- update the mission context from user answers;
- do not force an interview for an already clear direct action.

The Core/Brain decides whether to route a request through Interviewer using explicit role semantics, current task intent and existing authority rules.

## 7. Scene projection

Current scene already persists agent/job stars and `parent_of`. Extend it without moving execution truth into Scene.

### Node projection

For non-ephemeral agent instances:

- `SceneObject.kind = agent` remains;
- role identity is projected explicitly. If `category` can safely hold canonical role IDs, use it with a visual registry; otherwise add a backward-compatible role field to payload/scene domain rather than overloading free-form label text;
- title/summary remain bounded;
- Mission Owner gets a secondary badge/indicator, not a new node kind.

### Relations

Current `SceneRelation.kind` is closed to `parent_of`, `explains`, `groups`; extend with semantic projected kinds or a typed style field as proven safest by Slice 02/08. Required visible semantics: delegation, communication, adversary, qa, handoff.

Runtime projector remains authoritative for execution-topology relations. User/brain may compose placement but must not counterfeit execution/relationship facts.

### History

Only actual relations that were created are projected. No “next planned step”. After completion, non-ephemeral nodes/relations remain until the existing archive/disposition mechanism removes them.

## 8. Control Center UI

### Task/constellation view

- role-specific star identity;
- Mission Owner badge;
- origin task/mission kind visible in mission summary/header;
- typed relation styles;
- communication relation message button opens side panel/dialog;
- click relation for semantic details, participants and explicit messages;
- actual history persists; no forecast layer;
- dense graphs remain readable at zoom and responsive sizes.

### Settings

Add a role catalogue surface showing, per role:

- name + visual identity;
- mission/purpose;
- instruction/prompt source;
- skills/loadout;
- capabilities (mission ownership, spawn, QA/adversary/handoff availability, etc.);
- allowed/default Work Methods.

MVP requires inspectability and a polished readable layout. Editing should only be added where current Settings/config architecture has a safe canonical write path; otherwise explicitly read-only first.

## 9. Delivery quality / prefab selection

Add a mission-completion guidance layer available to Mission Owners:

- determine intended audience/use;
- choose output surface based on content shape;
- serious long-form report -> document/rich report prefab;
- structured comparison -> table/comparison prefab plus narrative when needed;
- visual executive outcome -> richer CIRCOE/presentation surface when available;
- do not force heavyweight output for a one-line/simple result.

Reuse `PrefabService` / existing brain display tools; do not build a new report renderer in this task.

## 10. Compatibility and failure semantics

- Current agents without new semantic metadata still appear with a safe `unknown/general` role projection; do not infer a false role from arbitrary text.
- Current `coder/reviewer/research` role markers map explicitly into the new registry during migration/compatibility.
- A missing role definition must degrade visibly (`role_unknown`) but must not stop the work.
- Mission-history persistence failure must not corrupt live Work State; diagnose and degrade history/UI.
- Scene failure remains a projection failure and must not stop work.
- Communication-board persistence failure must be visible to participants; never pretend a message was shared if it was not durably accepted.
- Handoff creation is transactional enough that a successor never claims an incomplete packet as complete.
