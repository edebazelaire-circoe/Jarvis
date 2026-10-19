# Testing & quality plan

## 1. Automated contract tests

### Role / mission

- role IDs strict and centrally registered;
- role immutable after instance creation;
- unknown role degrades explicitly, not guessed;
- current `coder`, `reviewer`, `research` compatibility mapping is deterministic;
- Mission Owner is independent of role;
- recursive sub-mission ownership creates no cycles;
- parent supervision metadata remains available.

### Work Method

- parser rejects workflow-only/DAG fields if the V1 schema intentionally omits them;
- method principles/quality criteria are bounded and versioned;
- candidate promotion requires repetition + positive quality evidence + explicit promotion.

### Relations

- type schemas strict;
- Delegation direction valid;
- Communication participants valid and messages ordered;
- Adversary requires >=2 peer participants and does not masquerade as QA;
- QA reviewer/target direction enforced;
- Handoff references two distinct instances and a complete bounded packet;
- relation messages reject hidden reasoning/raw provider payload fields.

## 2. Persistence / migration tests

If new Core DB tables are required:

- additive migration only;
- backup occurs before migration;
- schema snapshot updated as required by `CLAUDE.md`;
- old DB migrates forward;
- newer schema refuses cleanly;
- interrupted migration cannot half-create semantic records;
- no local user database is touched by tests.

Mission-history tests:

- non-ephemeral role/relation history survives Core restart;
- Work State reset/replay cannot rewrite immutable semantic role;
- late provider observation cannot resurrect deleted/ephemeral history;
- history-store outage leaves live Work State functional and diagnoses degradation.

## 3. Orchestration runtime tests

Use scripted/fake agent providers for deterministic tests:

1. Direct one-agent ephemeral correction.
2. Mission Owner delegates one sub-mission.
3. Nested local Mission Owner creates its own team.
4. Owner creates Adversary after discovering conflicting evidence.
5. Owner requests QA only after a critical result appears.
6. Owner performs Handoff to a fresh role/instance.
7. Owner opens Communication board and exchanges explicit messages.
8. Owner continues research after finding insufficient/conflicting evidence.
9. No relation/node is created merely because the prompt mentions a possible plan.
10. Parent redirects/stops a sub-mission without corrupting unrelated children.

## 4. Interview / responsiveness tests

- clear direct action routes without mandatory interview;
- vague creation triggers Interviewer;
- Interviewer asks one high-value question at a time;
- background research can run while waiting for the user's answer;
- returned evidence is available to later interview turns;
- a user interruption/clarification remains responsive while background work exists;
- no new execution-approval rule bypasses or duplicates existing confirmation policy.

## 5. Scene projection tests

- role -> visual category/icon contract deterministic;
- Mission Owner badge projected but role remains unchanged;
- typed actual relations projected from Core semantic facts;
- no planned/future relation can enter Scene;
- `parent_of` compatibility preserved;
- Adversary/QA/Communication/Handoff links survive reload for non-ephemeral history;
- completed ephemeral agent leaves no persistent scene object/history row;
- scene saturation/degradation does not stop mission execution;
- archive/disposition keeps existing user authority semantics.

## 6. UI tests

### Task graph

Automated browser tests across supported viewport/zoom matrix:

- role is recognizable without opening details;
- color is not the only cue;
- relation styles are distinct;
- message affordance is keyboard/focus accessible;
- relation detail opens correct participants/messages;
- dense graph does not make labels/control surfaces unreadable;
- no future/planned nodes appear;
- finished history remains inspectable;
- ephemeral completed nodes are absent.

### Settings

- role catalogue lists exact registry state;
- role detail displays prompt source, skills/loadout, capabilities and Work Methods;
- unknown/degraded role/loadout states are visible;
- if editing is out of scope, UI is explicitly read-only and has no fake save control.

## 7. Output quality tests

Deterministic policy tests:

- short/simple answer is not forced into a prefab;
- comparison request prefers a structured table/comparison display;
- serious report prefers a document/rich report surface;
- unavailable prefab degrades to a structured fallback without pretending success;
- Mission Owner only marks delivery complete after display action acknowledges success where a display was requested.

Human visual review is still required for “beautiful/polished”; unit tests cannot prove aesthetics.

## 8. Privacy / reasoning boundary

Tests must plant a unique private-reasoning sentinel in provider `thinking`/raw trace and explicit normal messages in collaboration. Verify:

- sentinel may remain only in existing raw diagnostic trace where current policy permits;
- sentinel does NOT appear in relation messages, durable mission history, Scene payloads, communication board UI, conversation public transcript or final report;
- explicit deliberate inter-agent message does appear in the board/history.

## 9. Agent Trace Analysis scenarios

Run the real supported local agent in an isolated sandbox/worktree, never the user's live JARVIS.

Required traces:

1. trivial correction remains one ephemeral agent;
2. complex research organically creates multiple roles after evidence need emerges;
3. adversary is peer competition, not reviewer;
4. QA examines existing result;
5. nested Mission Owner organizes local team;
6. handoff creates fresh instance and transfers bounded packet;
7. serious comparison produces a polished prefab output;
8. ambiguous creation uses Interviewer while background research proceeds;
9. agent does not create future “plan nodes”.

Agent Trace Analysis judges actual tool use and semantics, not hidden chain-of-thought.

## 10. Fault injection

- Core Work State temporarily unavailable to UI;
- durable mission-history write fails;
- Scene unavailable;
- relation message persistence fails;
- successor spawn fails during handoff;
- provider loses a subagent process;
- Control Center restarts and provider replays work observations;
- role registry/loadout snapshot stale/unreadable;
- prefab display fails/refuses.

Every fault must have visible, bounded degradation and no contradictory canonical state.

## 11. Performance / bounds

Measure at least:

- Work State update latency unchanged within existing order of magnitude;
- scene projection under a mission with dozens of non-ephemeral agents/relations;
- relation board with bounded message history;
- Settings role catalogue load;
- brain context budget after role/mission summaries are added;
- no unbounded recursion/team explosion: enforce system safety caps without turning them into a product “minimum complexity” policy.

Caps are resource safety, not behavioral doctrine.

## 12. Human Validation overview

Relevant Slice manifests contain the executable Human checks. Human must verify:

- role identity legibility;
- relation legibility + communication click target;
- no plan/future graph;
- completed ephemeral disappearance;
- real organic growth from simple to complex mission;
- QA vs Adversary visually/semantically distinct;
- polished report/comparison output;
- restart persistence of non-ephemeral history.
