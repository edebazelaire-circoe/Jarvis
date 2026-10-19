# Documentation levels & source-of-truth matrix

## Existing Level-3-ish/canonical contracts to preserve

| Concern | Existing canonical documentation/code | This task |
| --- | --- | --- |
| Core work truth | `docs/ARCHITECTURE.md` “Core work state”; `jarvis/domain/work_state.py`; `jarvis/core/work_state.py` | extend, do not replace |
| Agents panel | `docs/ARCHITECTURE.md` “Task visualization”; `control_center_work.js`; `work_view.py` | add role/mission/relation summaries |
| Conversation events | `docs/conversation-events.md`; domain/store/forwarders | add only necessary semantic audit events |
| Scene model | `docs/scene-model.md`; `jarvis/domain/scene.py`; `scene_service.py` | add role-aware/titled relation projection safely |
| Runtime scene projection | `docs/ARCHITECTURE.md` “Runtime scene projection”; `scene_projector.py` | project semantic actual relations + ephemeral policy |
| Skills/loadouts | `docs/skills-and-loadouts.md`; loadout resolver + routing hook | introduce canonical role registry & compatibility aliases |
| Prefabs | `docs/prefabs.md`; `docs/prefabs-style-guide.md`; `PrefabService` | reuse for polished mission output |
| Repo migration policy | `CLAUDE.md` | mandatory for any DB schema change |

## New canonical docs this task should produce/update

The final implementation should either create a dedicated canonical page or extend an existing one for each concern below. Slice 00 decides file placement after current-HEAD audit.

1. **Agent roles & Mission ownership** — role schema, immutability, role registry, recursive Mission Owner semantics, ephemeral classification.
2. **Agent relationships** — Delegation, Communication, Adversary, QA, Handoff; explicit message privacy boundary.
3. **Mission history** — persistent semantic ownership vs live Work State authority.
4. **Work Methods** — heuristic model and candidate promotion; explicit statement that methods are not DAG workflows.
5. **Task graph UI** — role visual identity, relation visual grammar, actual-vs-planned invariant, ephemeral retention.
6. **Settings roles surface** — inspectable role configuration and authority boundaries.
7. **Mission delivery quality** — how serious outputs select/use existing prefabs without making every task heavyweight.

## Documentation-level requirements by Slice

- Contract Slices (01–02) must reach the repo's strongest pure-domain/documentation level before runtime code relies on them.
- Persistence/runtime Slices (03–08) update `docs/ARCHITECTURE.md` and the dedicated contract pages in the same Slice that makes code authoritative.
- UI Slices (09–10) update `docs/control-center-shell.md` / `docs/OPERATIONS.md` and any scene/UI contract.
- Output Slice (11) updates prefab/agent operation docs rather than inventing a second report system.
- Learning Slice (12) documents candidate/promotion semantics and storage.
- Integration Slice (13) reconciles final docs, acceptance status, runbook, rollback, and known gaps.

## Known documentation traps

- Do not describe Scene as execution truth.
- Do not call provider raw trace authoritative.
- Do not describe Work Methods as plans/workflows after the user's correction.
- Do not call QA “Adversary”.
- Do not describe Mission Owner as a role.
- Do not promise that all tasks become multi-agent.
- Do not promise that every collaboration exchange reveals internal reasoning.
- Do not claim ephemeral agents persist in the completed constellation.
