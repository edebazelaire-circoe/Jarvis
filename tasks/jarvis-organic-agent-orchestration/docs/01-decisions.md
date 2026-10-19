# Locked decisions

This document is the product contract. If current code makes a decision impossible, Slice 00 records a conflict; implementers do not silently reinterpret it.

## D01 — Role is a first-class immutable identity

**Decision:** every agent instance has an explicit `role_id`; it never changes during that instance's lifetime.

**Rejected:** mutating an existing agent from Researcher to Developer in place.

**Why:** stable semantics, reliable loadouts/permissions, readable execution history, and role-specific visual identity.

## D02 — Role identity is visual per role

**Decision:** visual identity is defined per role, not only by broad family. Use redundant cues (icon/badge/label/accent), not color alone.

**Why:** the user must understand the execution strategy at a glance.

## D03 — Mission Owner is a responsibility, not a role

**Decision:** an instance may carry Mission Owner responsibility while retaining its functional role (`Developer`, `Research Lead`, etc.).

**Why:** orchestration is part of owning a mission, not a reason to replace specialist identity with a generic “Orchestrator”.

## D04 — Mission ownership is recursive

**Decision:** a delegated sub-mission may have its own Mission Owner, which can organize its own team. Parent owns the higher-level outcome and may supervise/redirect/stop.

## D05 — Complexity is organic

**Decision:** the Mission Owner decides during execution how much organization is warranted.

**Rejected:** “always minimize agents”, “always decompose”, fixed workflow templates, and up-front graph plans.

**Why:** actual difficulty often emerges after investigation begins.

## D06 — Work Method is heuristic, not a DAG

**Decision:** Work Methods encode habits, quality bars and decision heuristics. They may guide dynamic orchestration but do not prescribe a fixed sequence.

## D07 — Direct/ephemeral work remains valid

**Decision:** some tasks legitimately run in one short-lived agent. Multi-agent behavior is a capability, not a mandatory ceremony.

## D08 — Ephemeral agents are not retained in persistent constellation history

**Decision:** ephemeral work may be observable live, but completed ephemeral agents do not remain as durable stars/history nodes.

**Why:** avoid visual/history noise from trivial operations.

## D09 — Relations are first-class semantic objects

**Decision:** support at least `delegation`, `communication`, `adversary`, `qa`, `handoff` as explicit relationship types. UI must not infer them after the fact from text labels.

## D10 — Adversary means peer competition

**Decision:** two or more producer agents work on competing approaches/results and defend them against each other.

**Rejected:** using “Adversary” as a synonym for reviewer/critic.

## D11 — QA is asymmetric review

**Decision:** Quality Analyst examines another agent's result. QA is both a role identity and a typed relationship.

## D12 — Relations have semantics, not rigid protocols

**Decision:** a relation can provide helper behavior/default expectations, but it must not force a fixed number/order of rounds. Mission context controls how the relationship plays out.

## D13 — Communication is explicit and inspectable

**Decision:** agents that intentionally coordinate can get a relation-scoped communication board/chat. A relation affordance opens it.

**Privacy boundary:** board entries are explicit messages/proposals/decisions/critiques/summaries. Hidden chain-of-thought/private reasoning is never copied into it.

## D14 — Handoff creates a fresh instance

**Decision:** Handoff transfers mission context/results/artifacts to a successor instance. Role change or deliberate context refresh uses a new instance rather than mutating the old one.

## D15 — Graph shows actual execution, never a speculative plan

**Decision:** task/constellation UI is an execution history and live topology. Future nodes/relations are never displayed merely because an agent is considering them.

## D16 — Core Work State remains live execution truth

**Decision:** extend existing `WorkStateStore`; do not create a second status/state machine for agent execution.

**Why:** brain and UI already share this normalized truth.

## D17 — Scene remains a projection

**Decision:** persistent constellation visualizes the actual mission graph but is not the authoritative execution state. Runtime projector remains the owner of execution topology writes.

## D18 — Durable semantic mission history is Core-owned

**Decision:** role/ownership/typed relation/explicit collaboration history that must survive Work State eviction/restart is owned by Core and projected to Scene/UI. It must not redefine live execution status.

**Implementation seam:** Slice 00/03 must confirm the best existing store boundary and migrate safely.

## D19 — Interviewer is selective

**Decision:** vague/underspecified creation work may launch an Interviewer; clear direct actions may go straight to their specialist. Interviewing is not a mandatory preflight for every request.

## D20 — Interview and background work may coexist

**Decision:** questions to the user must remain responsive while independent useful background research/sub-agents run. New evidence can influence later questions.

## D21 — No new universal interview-to-execution approval gate

**Decision:** preserve current authority/confirmation rules. If implementation requires a new global gate, stop for a Human decision instead of inventing one.

## D22 — Mission Owner is accountable for quality before return

**Decision:** do not stop merely because one plausible answer exists. The Mission Owner decides whether evidence/results are sufficient and may add research, second looks, QA, adversary or handoff.

## D23 — Delivery format is part of quality

**Decision:** when the output is a serious report/comparison/document, select an appropriate existing rich prefab/display surface and make it readable/polished. Do not default to an ugly raw text dump. Simple outputs may remain simple.

## D24 — Dynamic methods can become reusable candidates

**Decision:** an organic strategy may be proposed as a reusable Work Method after repeated use **and** positive quality evidence. Promotion is explicit; it is never silently installed.

## D25 — Existing provider diagnostics stay diagnostic

**Decision:** raw Claude/Codex/provider trace remains non-authoritative diagnostic data. New role/relation semantics belong in Core contracts, not provider-only parsing.
