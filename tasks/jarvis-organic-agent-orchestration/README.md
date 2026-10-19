# JARVIS — Organic Multi-Agent Orchestration, Roles & Relations

## Purpose

Turn JARVIS sub-agents from mostly generic execution nodes into an inspectable, role-aware, organically growing team system. A mission may remain a single fast/ephemeral action, or may grow over hours/days into nested teams with research, QA, adversarial alternatives, communication, and handoffs as the work reveals that complexity.

The system must **not** pre-plan or pre-render a workflow graph. The Mission Owner decides during execution when another agent, another role, another perspective, or another quality check is warranted.

## Repository baseline

- Project: `JARVIS`
- Repository: `edebazelaire-circoe/Jarvis`
- Audited default branch: `main`
- Baseline observed while creating this handoff: `82051c3ada7a695b88042e8772e7da35bbae2513`
- Existing canonical execution truth: Core Work State (`jarvis/domain/work_state.py`, `jarvis/core/work_state.py`)
- Existing persistent visual projection: Constellation Scene (`jarvis/domain/scene.py`, `jarvis/core/scene_projector.py`, `scene.sqlite3`)
- Existing provider diagnostics: `AgentTaskTracker` / `/api/agent/tasks`
- Existing role/loadout seam: `LoadoutResolver.resolve(profile, role)` and routing hook
- Existing display system: prefab catalogue, including `jarvis.document` and `jarvis.table`

Slice 00 MUST re-audit current HEAD before dispatch. This handoff is a target contract, not permission to ignore later repository changes.

## Product model

### 1. Role

A role is the stable identity of an agent instance. It determines what the agent is for, its instruction layer, capabilities, skills/loadout, permissions, and its visual identity.

Initial role vocabulary to support includes at least:

- Interviewer
- Research Lead
- Web Research
- Document Research
- Developer
- Conceptualizer
- QA / Quality Analyst
- Finalizer / delivery role where a separate finishing instance is useful

The implementation may preserve compatibility aliases for the current `coder`, `reviewer`, and `research` routing roles, but the new canonical role IDs must be explicit data, not guessed from labels.

**Locked invariant:** an agent instance never changes role. A role change means a new instance, usually connected by a Handoff.

### 2. Mission Owner

`Mission Owner` is a responsibility/status of an instance, **not a role**. A Developer, Research Lead, Designer-like role, etc. may own a mission.

A Mission Owner owns the outcome, not merely its personal piece of work. It may:

- work directly;
- delegate bounded work;
- create specialized agents;
- create nested sub-missions with local Mission Owners;
- request a second perspective;
- create QA review;
- create an Adversary relationship;
- open a communication board between agents;
- hand work to a fresh instance;
- inspect returned evidence and decide it is insufficient;
- continue/reopen research when quality is not adequate;
- select an appropriate final delivery surface and produce a polished result.

A parent Mission Owner gives a sub-mission its objective. The local Mission Owner is autonomous in how it organizes that sub-mission. The parent keeps supervision and may redirect or stop it.

### 3. Work Method

A Work Method is separate from Role, but is **not a workflow/DAG**. It is a reusable set of heuristics, quality expectations and working reflexes.

Examples: `Quick Research`, `Deep Research`, `Comparative Research`, `Bug Investigation`.

A method may say things such as “seek independent evidence when a claim is uncertain” or “use QA for a critical step”; it must not require a fixed sequence of nodes. Agents may also adapt dynamically during a mission.

Dynamic methods that recur and produce good outcomes may become candidates for reuse, but promotion is explicit and based on repetition + quality; no silent self-modification.

### 4. Agent relationships

Relations are first-class semantic facts and first-class visual links:

- **Delegation** — parent gives bounded work/sub-mission to another agent.
- **Communication** — agents intentionally coordinate through a shared visible message board.
- **Adversary** — peer agents produce competing work/research/solutions and defend different approaches against each other.
- **QA** — asymmetric review: a Quality Analyst critiques/checks another agent's result.
- **Handoff** — directed transfer from one instance to a fresh successor, including an explicit handoff packet.

Adversary and QA MUST remain distinct. Adversary is competition between producers; QA is inspection of someone else's work.

Relations have clear semantics but must not impose rigid multi-round protocols. Their runtime behavior remains adaptable to the situation.

### 5. Ephemeral work

Some tasks are intentionally tiny: e.g. one file correction, a short note, a simple rename. They may run in a single ephemeral agent.

Ephemeral agents may be observable while live if existing Work State supports it, but **must not remain as persistent constellation/history stars after completion**. Non-ephemeral agents and their semantic relations remain inspectable after the mission ends.

### 6. Visual identity and history

The current generic star/line view is insufficient.

- Each role receives its own stable visual identity (icon + role badge + color/accent; role label remains readable; do not rely on color alone).
- Task origin/type remains visible so a user can quickly understand “this began as a code task and used three research agents, QA and a handoff”.
- Relations receive distinct rendering and affordances.
- Adversary must read visually as competition (e.g. paired/double curved link treatment).
- Communication has a message affordance at/on the relation; clicking opens the relation board.
- QA and Handoff are visually distinct and directed where appropriate.
- The graph shows **actual execution only**, live and historical. Never show speculative/planned future nodes.
- Finished non-ephemeral nodes/relations remain inspectable until the existing user disposition/archive model removes them.

### 7. Communication boards and reasoning boundary

Communication boards expose deliberate inter-agent messages: proposals, questions, decisions, critiques, result summaries and handoff content.

They MUST NOT expose hidden chain-of-thought/private model reasoning. Existing raw provider trace remains a diagnostic surface under its current policy; the new collaboration board is a separate explicit communication artifact.

### 8. Quality and final delivery

Mission completion includes both substantive correctness and delivery quality.

A Mission Owner must not stop at the first plausible information when the mission calls for deeper evidence. It must judge sufficiency, use second looks/QA/adversarial alternatives when warranted, and return a polished deliverable.

For report/comparison/document outcomes, use the existing prefab/display stack when appropriate (`jarvis.document`, `jarvis.table`, richer CIRCOE/presentation prefabs) rather than dumping an unstructured wall of text. Simple answers remain simple.

## Architecture summary

The implementation MUST extend existing canonical layers instead of creating a parallel agent/task system:

1. **Core Work State stays live execution truth.** Extend its normalized semantic fields only where necessary.
2. **A Core-owned durable mission/collaboration history** stores semantic role, mission ownership, non-ephemeral agent lineage, typed relations and explicit collaboration records. It is historical/semantic state, not a competing execution-status engine.
3. **Role registry + loadout integration** resolves prompts/skills/tools/capabilities and role visuals from explicit role IDs.
4. **Orchestration tools** let Mission Owners create/relate agents organically at runtime.
5. **SceneProjector** projects actual non-ephemeral roles/relations into the persistent constellation; it never invents future work.
6. **Control Center UI** renders role-aware stars, typed links, communication boards, task/mission identity and Settings role inspection.
7. **Output-quality policy** teaches Mission Owners to select rich prefab surfaces when a deliverable warrants them.

See `docs/02-architecture.md` and `docs/03-data-and-workflows.md`.

## Locked constraints / non-goals

- No global “complexity minimal” doctrine.
- No fixed orchestration plan generated up front.
- No future/planned nodes in the task graph.
- No rigid QA/Adversary/Communication protocol that forces a fixed number/order of rounds.
- No role mutation on a live agent instance.
- No persistent history stars for ephemeral agents.
- No inference of semantic role/relation from free-form labels in the UI.
- No second execution truth outside Core Work State.
- No hidden reasoning/chain-of-thought in communication boards.
- Do not replace the existing Agents panel, Work State, Scene, Conversation Events, or prefab system with a parallel stack.
- Do not start/restart the user's live JARVIS during implementation; follow `CLAUDE.md` and use isolated tests/worktrees.

## Implementation slices

See `slices/TODO.md`. Summary:

1. PM readiness and blind re-audit.
2. Role / Mission Owner / Work Method contracts.
3. Relation contracts and explicit communication/handoff records.
4. Live Work State + durable mission history integration.
5. Role registry, loadouts and methods.
6. Mission Owner orchestration runtime/tools.
7. Relation runtime (Communication, QA, Adversary, Handoff).
8. Interviewer + responsive/background coordination.
9. Role/relation scene projection and ephemeral exclusion.
10. Task graph UI.
11. Role Settings UI.
12. Output-quality + prefab delivery behavior.
13. Reusable Work Method candidate learning.
14. End-to-end integration, QA, rollout and docs.

## Acceptance criteria

The task is done when all of the following are true:

- A simple correction can run as one ephemeral agent without leaving a durable scene-history star.
- A complex mission can organically grow into nested, independently owned sub-missions without a predeclared workflow.
- Role IDs are explicit, immutable per instance, drive role-specific visual identity, and map to loadouts/tools.
- Mission ownership is recursive and visible/inspectable without becoming a fake role.
- Delegation, Communication, Adversary, QA and Handoff are explicit typed relations with real runtime semantics.
- Adversary can connect multiple peer producers working on competing approaches; QA remains asymmetric review.
- Communication boards are clickable from relation UI and contain only explicit inter-agent communication, never private reasoning.
- Core Work State remains the canonical live status; the durable mission graph does not contradict it.
- The constellation shows actual non-ephemeral execution history and visually distinguishes role + relationship types.
- After completion, non-ephemeral history remains inspectable; ephemeral agents do not.
- Interviewer can clarify underspecified creation work while other background research can proceed, without turning clear direct tasks into mandatory interviews.
- Mission Owners judge evidence/results before completion and can trigger research, second looks, QA, adversary or handoff when the situation calls for it.
- Serious report/comparison outcomes use an appropriate existing prefab/rich surface and pass a visual Human check; simple outcomes are not forced into heavyweight artifacts.
- Migration, restart/reconciliation, degraded-provider behavior, compatibility with current `coder/reviewer/research`, privacy and no-chain-of-thought boundaries are tested.
- Required independent QA and Human Validation checks pass.

## QA doctrine

Every implementation Slice is owned by one Work Agent. Coding work starts with `/caveman` and `/coding-guideline`; frontend work also uses `/impeccable` and routes to Claude where supported.

Independent validation is not optional:

- code: Code Review + QA Verification;
- runtime/user-facing: add Runtime Validation;
- agent/tool/MCP/prompt behavior: add Agent Trace Analysis;
- frontend slices: Human visual validation in addition to machine tests.

No Slice lands on `main` before its required independent QA is complete.

## Human validation

Human checks live in the relevant `human-validation.json` manifests and remain `pending` until a human actually executes them. Key checks include role readability, relation readability/clickability, no planned-graph leakage, ephemeral disappearance, recursive mission growth, and polished report output.

## Startup instructions for implementers

1. Start with `slices/00-project-manager-readiness` only.
2. Read `CLAUDE.md` and perform a blind current-HEAD audit before treating this handoff as truth.
3. Resolve the authoritative Workspace Task Type vocabulary. `task_type_unresolved` blocks all implementation Slices; do not invent `code` or another label.
4. Reconcile the current code with `docs/01-decisions.md` and `docs/02-architecture.md`; revise handoff instructions if repository reality changed, without changing locked product decisions silently.
5. Execute Slices in dependency order; one Work Agent per Slice; run the exact QA named in metadata.
6. Never start/restart the user's live JARVIS without explicit permission.
