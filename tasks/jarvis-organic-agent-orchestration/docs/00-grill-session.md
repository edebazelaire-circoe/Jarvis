# Reconstructed design session

**Status:** reconstructed from the conversation because the input was conversational/voice-transcribed rather than a pre-existing formal spec. This is not claimed as a word-for-word transcript. Product decisions are normalized in `01-decisions.md`.

## Starting problem

The user described a recurring failure mode: JARVIS sometimes treats an early idea as an immediate execution order, becomes slow/unresponsive while launching a long action, and only afterward discovers that the user was still defining what they wanted.

Wanted behavior:

- clear direct action (“there is a bug, fix it”) can go straight to the appropriate agent;
- vague creative/conceptual work (“I want to make a good video”) should be clarified by an Interviewer;
- interviews/questions should remain responsive while useful research/sub-agents can run in the background;
- the Core Brain should understand types of sub-agent roles and choose/use them appropriately.

## Roles and methods

The user then clarified that a role is insufficient on its own. An agent also needs a **method of working**.

Example: a research lead should not merely open two pages and announce a winner. Its job is often to organize a real investigation: split useful lines of inquiry, launch parallel research, compare evidence, decide whether the result is sufficient, and continue if it is not.

The same applies to code: a lead can split work, ask for a second implementation, request critique, or hand part of the work to another specialist.

## Relations between agents

The user asked for relationships to become explicit and visible rather than generic lines.

### Adversary

Adversary means **competition between peer producers**, not “review this other agent”. Two or more agents can work on the same problem or comparable alternatives, arrive at different solutions/research results, defend their positions, and confront the alternatives.

The user specifically separated this from QA.

### QA

QA is asymmetric. A Quality Analyst looks at another agent's result, checks/criticizes it, challenges weaknesses and provides a second look. QA should exist both as a recognizable role and as a typed relation from the reviewed work/agent to the reviewer.

### Communication

When two agents genuinely need to coordinate, they should have an explicit communication relationship with a small shared board/chat. The task graph should show a message affordance on the relation; the user can click it to read the deliberate exchange.

### Handoff

An agent can pass the torch to a fresh instance when continuity, specialization or context freshness calls for it. The handoff must be visible and carry the useful state/results rather than forcing the successor to reconstruct everything.

### Delegation

Parent/child delegation remains a core relationship: a Mission Owner can assign bounded work or a sub-mission to another agent.

## Visual identity

The user repeatedly emphasized that current UI does not make the nature of work legible enough. A task should reveal its execution history at a glance: e.g. an original code task that used three research agents, a QA review, an adversarial branch and a handoff.

The identity should be **per role**, not merely per broad family. Stars/nodes should make Research, Document Research, Developer, QA, Interviewer, etc. immediately distinguishable.

Relations should also be visually distinctive. Adversary can use paired/curved/double lines; Communication has a message affordance; QA and Handoff have their own recognizable treatment.

## Role immutability

The user approved the rule that an agent instance keeps the same role for its entire life. A change of responsibility that implies another role creates a new instance and an explicit relationship such as Handoff.

## Role vs Work Method

The user approved separating Role and Work Method. However, the user later corrected an overly rigid interpretation:

- a Work Method must not be a predeclared workflow/DAG;
- no “plan” should be drawn before execution;
- no universal “complexity minimal” doctrine should push the system toward fewer agents;
- complexity should emerge organically from the problem.

A mission can be a single ephemeral correction or a multi-day coordinated team effort. The responsible agent decides while working when more structure is useful.

## Mission Owner

The user approved making “Mission Owner” a status/responsibility, not a special Orchestrator role.

A Mission Owner is responsible for the mission result. It can create and manage an agent team, decide the mission's evolving complexity, request research/QA/adversarial alternatives/handoffs, and ensure quality before returning the result.

Mission ownership is recursive. A parent can delegate a significant sub-mission to a Research Lead or Developer, which becomes the local owner of that sub-mission and can create its own team. The parent keeps supervision and intervention rights without micromanaging every child.

## Organic complexity — final correction

The user explicitly rejected the framing “tasks should stay at minimum complexity.” The correct framing is:

- tasks span a spectrum from one ephemeral agent to long-running teams;
- JARVIS gives Mission Owners **tools** to add complexity when the work reveals a need;
- the Mission Owner decides when to create an adversary, request QA, delegate research, communicate, or hand off;
- the agent should not stop at the first available information; it is responsible for judging result quality;
- the final presentation also matters: use prefabs and produce polished reports/comparisons instead of ugly raw text dumps when the mission warrants it.

## Persistence

The user approved keeping completed execution history visible **except ephemeral agents**. Ephemeral one-shot agents should not clutter persistent history.

## Reusable methods

The user approved allowing dynamically adapted working approaches to become reusable Work Method candidates when they recur and are validated by quality, but this must remain explicit rather than silent self-modification. After the final correction, these stored methods are heuristics/reflexes, not fixed sequences.
