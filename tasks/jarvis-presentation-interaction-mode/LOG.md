# Execution Log

Reserved for implementation agents. Record durable execution notes, decisions caused by repository drift, validation evidence references, and cross-slice handoffs here. Do not use this file for ephemeral scratch notes.

---

## 2026-09-23 — Slice 00, Project Manager readiness gate (agent 0)

**Outcome: `READY`, conditional on Human decisions W1 and D15.** Full record in
`slices/00-project-manager/READINESS.md`.

- Branch `task/jarvis-presentation-interaction-mode` created from `main` @ `ddcdb71`, which is
  exactly `task.json.source_snapshot.sha`. **Zero snapshot drift.**
- Handoff mirrored from Drive into `tasks/jarvis-presentation-interaction-mode/`: 48 files,
  every byte size matching its Drive source, all 25 JSON files parsed. Committed as S0.
- Blind repository audit performed by a sub-agent forbidden from opening `tasks/`, dispatched
  before any handoff conclusion was read. It confirmed every Level-0 claim in
  `docs/05-documentation-levels.md` independently.
- Regression baseline: 248 unit test files, **7022 collected, 6994 passed, 26 failed, 2 skipped**.
  The 26 are pre-existing at the branch point and listed by name in `READINESS.md` §4. Every
  implementer receives that list as "not yours, do not fix".
- **21 of the 26 are in Scene**, the reuse surface for Slices 08 and 09. Those two Slices get a
  narrower named green subset as their gate, and the Scene failure set is re-measured
  immediately before their dispatch.

### Gaps found by the audit, now binding constraints

| id | Gap | Slices |
| --- | --- | --- |
| G1 | Two voice-architecture axes coexist (`voice_arch` legacy/continuous_brain **and** typed `voice_architecture`); `_apply_voice` is a three-way exclusive branch that deletes `voice_architecture` | 01, 02 |
| G2 | `Disposition` is already taken by `jarvis/domain/scene.py` — use `OutputDisposition` | 01 |
| G3 | `PERSISTABLE_OPTION_IDS` is a 47-entry allow-list; a control absent from it fails to save *silently* | 02, 03 |
| G4 | `configuration_id` restart semantics undecided — escalated as **D15** | 02 |
| G5 | The work lane has no priority field at all; P0-P4 must live in the new speculative path, never on canonical `WorkItem` | 08, 10 |
| G6 | No generic UI seam and no framework; `openLifecycleSeam` is Bare Hands-specific; the z-index registry comment is test-asserted | 03 |
| G7 | `AddressingDecision` is closed, wire-encoded and persisted — do not widen it | 06 |

### Human decisions, both answered 2026-09-23

- **W1 — waived.** Workspace Task Type vocabulary does not exist in this environment; the Human
  granted the same waiver as for the four previous tasks. `task_type: null` stands everywhere.
- **D15 — decided: keep it out.** Interaction mode does not enter
  `VoiceComposition.configuration_id`. Core owns the effective live mode plus a revision counter;
  Voice consumes it through an explicit live event and never restarts on a mode change. Slice 02
  must carry a test asserting a mode change produces **no** `voice.switch.requested`.

Slice 00 is `READY`. Implementation dispatch is open.

### Lifecycle state

Drive folder is still in `to-do`. It must be moved to `current` by the Human before the first
implementation Slice is dispatched; the Drive connector available here can create, read and
update but cannot move folders.
