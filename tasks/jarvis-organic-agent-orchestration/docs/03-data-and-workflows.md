# Data & organic execution semantics

This document deliberately avoids a fixed workflow. It defines state/data transitions and the tools that let organization emerge from the mission.

## 1. Spectrum of valid execution

### Simple / ephemeral

```text
User request
  -> one agent instance (ephemeral)
  -> direct action
  -> result
  -> instance ends
  -> no persistent constellation-history star
```

Example: “correct this file typo”.

### Complex / organic

```text
Mission Owner (Developer)
  -> discovers an uncertain technical assumption
  -> creates Research sub-mission
       -> Research Lead becomes local Mission Owner
       -> delegates Web Research + Document Research
       -> evidence conflicts
       -> creates Adversary between two competing approaches
       -> returns synthesis
  -> implementation proceeds
  -> critical section merits QA
       -> QA relation + Quality Analyst
  -> context/specialty shift
       -> Handoff to fresh Developer
  -> polished final report using appropriate prefab
```

None of those nodes need to exist when the mission starts. They appear only when an owner actually invokes them.

## 2. Mission lifecycle

Suggested semantic lifecycle (exact enums may adapt to current domain conventions):

```text
open -> completed | cancelled | failed
```

A mission lifecycle is not the same as every WorkItem's status. A mission can remain open while individual agent work completes/fails/retries.

Sub-missions have the same lifecycle and a `parent_mission_id`.

## 3. Agent instance lifecycle

Live status is always sourced from Work State:

```text
pending -> running <-> blocked -> terminal
terminal = completed | failed | cancelled | interrupted
```

Semantic invariants layered on top:

- `role_id` set once;
- `mission_id` set once for that instance's assignment (a handoff creates another instance);
- `ephemeral` set once;
- Mission Owner responsibility can be represented as an assignment to the mission; avoid silently toggling an agent between unrelated mission ownership roles.

If Mission Owner responsibility itself must transfer, record an explicit Handoff/ownership event; do not mutate history invisibly.

## 4. Relation semantics

### Delegation

**Intent:** “You own this bounded work/sub-mission for me.”

Data needs:

- delegator;
- delegatee;
- mission/sub-mission;
- objective/purpose;
- created/closed timestamps.

The delegatee can itself be a local Mission Owner.

### Communication

**Intent:** “We need an explicit coordination channel.”

Data needs:

- participating agents;
- relation board id;
- ordered explicit messages;
- optional artifact refs.

Communication may coexist with other relationships; do not force it just because agents share a parent.

### Adversary

**Intent:** “Produce/defend competing approaches and confront them.”

Characteristics:

- symmetric peer relationship;
- at least 2 participants;
- may involve identical problem statements or intentionally different alternatives;
- participants produce actual work/research, not merely commentary;
- result may be winner, synthesis, unresolved tradeoff, or escalation.

No hard-coded “round 1 blind, round 2 reveal, round 3 vote” protocol. A Work Method may recommend independence first in suitable cases, but the owner decides.

### QA

**Intent:** “Give a second critical look at this work/result.”

Characteristics:

- asymmetric;
- reviewer has QA role (or a role explicitly capable of QA if later approved);
- target agent/result/artifact is explicit;
- QA may approve, raise findings, request correction, or reject adequacy;
- QA does not become a competing producer merely by criticizing.

### Handoff

**Intent:** “Continue this mission from a fresh instance/context/specialty.”

Required packet:

- mission objective;
- completed work;
- key decisions;
- evidence/artifacts;
- open questions/risks;
- recommended next action.

A successful handoff links two immutable-role instances. The predecessor may end or remain available depending on mission needs; no universal forced shutdown.

## 5. Mission Owner decision loop

This is a **decision loop**, not a workflow plan:

```text
work on mission
    ↓
observe what is now known / unknown / risky
    ↓
judge whether current evidence/work is sufficient
    ↓
choose any useful action:
  - continue alone
  - delegate
  - create specialist
  - create peer alternative / Adversary
  - request QA
  - communicate
  - hand off
  - ask user via Interviewer
  - produce/format result
    ↓
continue until outcome quality is adequate or mission is blocked/failed/cancelled
```

The allowed set is a toolbox. There is no requirement to visit every action.

## 6. Research behavior example

User: “Find the best monitors.”

Wrong behavior: one agent reads two pages and chooses one model.

Expected capability:

- Research Lead judges breadth/depth required;
- may delegate manufacturer specs, independent reviews, pricing/availability, long-term/community feedback;
- may compare conflicting evidence;
- may create competing recommendations/Adversary where use cases produce different winners;
- may request QA on the final comparison;
- decides when evidence is sufficient;
- returns a structured comparative deliverable rather than raw notes.

The exact number of agents is not predefined.

## 7. Code behavior example

User: “Fix this bug.”

If clear and local: one ephemeral Developer may fix/test and finish.

If investigation reveals architectural uncertainty:

- Developer Mission Owner may spawn a research agent;
- may ask a second Developer to implement/argue another approach under Adversary;
- may request QA/code review for a critical change;
- may hand off to a fresh Developer after a long investigative context;
- final result includes tests and appropriate user-facing explanation.

Again, the graph emerges from actual decisions.

## 8. Interview behavior

User: “I want to make a beautiful video.”

Possible organic execution:

- Interviewer asks the highest-value missing question;
- independent research (references/assets/project context) may run in the background;
- evidence can alter the next question;
- once the mission is sufficiently understood, normal mission ownership continues under existing authority rules.

A direct “change this exact thing” request does not need the Interviewer.

## 9. Reusable Work Method candidate lifecycle

```text
Dynamic/adapted method used in real missions
  -> pattern recurs
  -> quality evidence positive (QA/user/observable criteria)
  -> candidate recorded/proposed
  -> explicit promotion
  -> reusable Work Method version
```

Promotion captures principles/heuristics, not the exact historical graph.

Never auto-promote solely because a structure happened once. Never silently rewrite an existing method.

## 10. Output delivery semantics

Before declaring the mission done, the Mission Owner checks two dimensions:

1. **Substance:** enough evidence/testing/critique for the mission's stakes.
2. **Delivery:** output is usable and appropriately presented.

Examples:

- trivial fix -> concise answer;
- technical investigation -> structured document with decisions/evidence;
- product comparison -> table prefab + concise recommendation;
- executive/research report -> polished document/report prefab, not raw text wall;
- visual deliverable -> existing richer prefab/presentation path if warranted.

No fixed report template is mandatory across all tasks.
