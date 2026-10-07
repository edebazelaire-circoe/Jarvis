# Slice 00 — Readiness (2026-10-05)

**State: READY** for Slices 01, 02, 04, 05, 06, 07, 10, 03, 11 (in that order). **Slices 08 and 09 DEFERRED** on external dependencies.

Binding plan: `docs/06-resolved-architecture.md` and each SLICE.md's `## Slice 00 contract (binding)`. Order and QA tiers: `slices/TODO.md`.

## 1. Declared state vs repository

- The handoff says the previous Presentation task was deleted. In fact its code was merged into `main` by the Human (`9a722c0`, 2026-09-25) and is repository reality. This task is a **consolidation** (A1). The old record lives in `tasks/jarvis-presentation-interaction-mode-2026-09/`.
- Blind audit (before reading the handoff docs): `BLIND-AUDIT.md`. Headline: `DisplaySceneStager.reveal` calls `SceneDisplayTools.set_visibility`, removed by `df28431` the day after the 2026-09 close-out. The tests passed only because fakes keep the method, so revealing a prepared visual fails in production. Verified by agent 0 (`presentation_staging.py:100`; `display_mcp.py` has only `create_object` / `update_object` / `archive`).
- Other gaps, all verified against code by the Plan agent and assigned in `06` R1:
  - Voice learns the mode only while a session is ACTIVE;
  - room speech can reach the brain in an active continuous session;
  - `ASK_BRAIN` carries no presentation context;
  - 6+2 sub-agents on a low-RAM host;
  - presentation decisions are absent from the canonical timeline;
  - attention plays the failure tone;
  - room text leaks into `trace.jsonl` (`voice.transcript`, Issue 002).

## 2. External dependencies (checked 2026-10-05)

| Handoff | State | Consequence |
|---|---|---|
| `jarvis-tool-brain-ui-orchestrator` | Drive `to-do`, not started, no code | Slice 08 DEFERRED; Slice 07 adds the sink port so 08 is an adapter swap |
| `jarvis-scene-window-prefab-foundation` | Drive `current`, complete on its branch (64 commits), awaiting Human validation, **not merged** | Slice 09 DEFERRED; reveal fixed now on main's `update_object` (Slice 01) |
| `jarvis-conversation-observability-timeline` | merged | consumed by Slice 10 |
| `jarvis-board-session-context-runtime` | merged | consumed; Board kind stays metadata |
| `jarvis-session-context-recording-runtime` | merged | `transcript_tail` / `BRIEF_AMBIENT_RULE` reused by Slice 05 |

## 3. Decisions (decided by agent 0, Human delegated autonomy)

A1–A12 and P1–P10 are in `docs/06-resolved-architecture.md` R2/R3. The ones with product impact the Human should know about:

- **P2:** in PRESENTATION, a transcript reaches the brain only inside an explicit-address window (wake word or manual key) or when it starts with "Jarvis". There are no implicit follow-ups: answering a clarification needs a new address.
- **A7:** the default pool is 2 speculative sub-agents + 1 reserved explicit, configurable (was 6 + 2).
- **A8:** contradictions get a distinct, softer cue through the single `bgCue` emitter.
- **A11:** the Task Type vocabulary does not exist on this host, so it is waived as on five previous tasks; `task_type: null` stays.

## 4. Inherited test baseline (branch point `085928d`, measured by a sub-agent on 2026-10-05)

- unit: 384 files, 11 684 tests, **10 stable failures**, 12 skipped;
- integration: 72 files, 653 tests, **1 stable failure**, 23 skipped;
- no flakes, no collection errors.

The full named list is in `BASELINE.md`. It is handed to every implementer as **"not yours, do not fix"**. The one relevant here is `test_interaction_mode_hud_browser.py::test_le_mouvement_reduit_arrete_vraiment_le_halo`, which Slice 03 touches and must leave as-is or fix only if its own change is the cause.

## 5. Human gates

- Move the Drive folder `jarvis-presentation-interaction-mode` from `to-do` to `current` (the connector cannot move it).
- HV checks: `HV-PRESENTATION-MODE-UI-01` (03), `HV-PRESENTATION-ATTENTION-01` (10), `HV-PRESENTATION-E2E-01` (11, last). They supersede the six open 2026-09 HV-PRES-* checks (06 R8).
- Merging this branch, and merging the prefab and Tool Brain tasks that unblock 08/09.
