# Jarvis Presentation: Remotion-first Integration and Compliance Follow-up

## Project and handoff identity

- Canonical project: **Jarvis**
- Repository: `edebazelaire-circoe/Jarvis`
- Branch being inspected: `task/jarvis-interactive-presentation-studio` (https://github.com/edebazelaire-circoe/Jarvis/tree/task/jarvis-interactive-presentation-studio)
- Static planning snapshot: `16e3dc585a29a767af26440e5a4364c8d57d9065` (2026-10-08; later commits/worktrees are not in the review).
- Existing in-flight handoff: `jarvis-interactive-presentation-studio` (do not change, supersede, or stop its active implementation).
- New task slug: `jarvis-remotion-presentation-integration`
- Local: `tasks/jarvis-remotion-presentation-integration/`
- Drive: `Jarvis/task/to-do/jarvis-remotion-presentation-integration/`

## Purpose

First, independently and thoroughly verify the finished existing Presentation Studio branch against the ORIGINAL handoff and all SUBSEQUENT user decisions, without assuming its initial implementation is final. Next, integrate Remotion as the **forced default** motion/preview/export engine via an install-once Jarvis capability. Keep the existing HTML engine, canonically named **Slidecar** (not Sidecar), intact behind a deliberate experimental user-only selection. Never silently fall back from Remotion to Slidecar; a Remotion failure is a visible failure to fix.

This is a follow-up to active implementation, NOT a request to rewrite its original 23 Slices, and NOT permission to edit the in-flight branch now.

## Key findings from static review

- The existing branch already delivers much of the complex Slidecar foundation (document, scenes, parameter controls, DA, score/cues, playback, reload, autosave, variants); do not rebuild these.
- At snapshot the old `slices/TODO.md` shows 00-14, 16,17 as checked, with 15 and 18-22 unchecked. Its LOG says 16,739 passed, 10 baseline failed, 40 skipped in an integrated sweep. This is a **reported** result, not a test run by the handoff author.
- The branch is divergent from `main` (at audit: 129 ahead, 85 behind). A fresh exact-SHA and integration audit is mandatory.
- Remotion is absent from the inspected Presentation Studio code/docs. Its runtime/Player/Studio and editor operations need integration; no parallel remake of existing Jarvis score/cues/variants.
- `Presentation` currently stores documents under `<data_root>/presentations/` and documentation says it is not an `Artifact`. The existing Artifact registry has closed kinds, terminal acquisition state, board-link relations and a separate payload store. User later required a logical editable parent source, final derivatives and board visibility; model reconciliation is a prerequisite, not a file move.
- Existing Jarvis `plugin` UI registers **remote MCP servers**; it is not a local Node/npm lifecycle manager. Remotion provisioning needs a coherent local capability installer without changing external MCP semantics.
- Browser fullscreen needs a user gesture and has outstanding physical multimonitor checks; do not claim system-wide voice-only fullscreen unless a native host is actually provided.

Detailed evidence: `docs/06-branch-compliance-audit.md` and `docs/07-evidence-index.md`.

## Non-negotiable decisions

1. Remotion is the **default and enforced** engine in ordinary authoring/playback/export while this phase is tested. No autonomous agent engine choice, no silent Slidecar fallback.
2. Slidecar is an explicit HUMAN experimental option, preserving its sources, data, controls, score and history. An opt-in experiment must be observable in diagnostics.
3. Reuse Jarvis architecture: Core owns document state, Scene/Prefab authority stays canonical, Tool Brain's existing authority boundaries and PRESENTATION ambient rules remain intact.
4. Install/provision Remotion only ONCE per Jarvis runtime profile, with pinned compatible versions, health/repair and managed local process lifecycle. Do not make a fresh `node_modules` tree per slide/project.
5. Voice-first creation and editing: Jarvis directs safe parameter patches or dispatches subagents for source edits; the user need not type code. Studio can be opened alongside Jarvis on request, not forced on every preview.
6. Keep readable, reusable source; live props edits and HMR do not render a fresh MP4. Export is separate.
7. During editing assets refer to Boards/InfoBoards by validated live references. On freeze/share/export create a self-contained immutable package; source is the logical parent and MP4/still/PDF derivatives link back to it with version/variant provenance.
8. Maintain a single user-visible Prefab library across engines and source types. `Prefab` is the umbrella; `Component`, `Composition`, `Page`, `Presentation`, `Asset` are consistent semantic categories, not names translated per engine.
9. Each published prefab declares editable parameters explicitly, shown in details on demand; type, tech stack, engine compatibility, upstream provenance, source, dependency versions and licenses are recorded. Unsupported uses are visible, not guessed; native/adapter/unsupported is the default compatibility triage.
10. Pin the exact prefab version in a presentation; detect new versions without auto-upgrading. Updates are tested first in a new variant. Promotion to the global prefab library happens ONLY on explicit user request, whether from a full presentation, scene or component.
11. Art direction and PresentationScore/script are first-class required presentation metadata. Preserve user-presenter sidekick, Jarvis-presenter, rehearsal, event-driven cues and selectively locked sequences.
12. Do not modify the current implementer's branch/task until it has finished and the owner has provided an integration-ready branch. New task 00 gates all dispatch.

## Start here

1. Read `slices/TODO.md` and execute `slices/00-project-manager/SLICE.md` yourself as Project Manager; no delegation for Slice 00.
2. Independently audit HEAD/rebase situation, branch/docs/contracts/tests and remaining original Slices before reading the pre-audit in `docs/06-branch-compliance-audit.md`.
3. Compare independent findings with the recorded snapshot and adjust the task. Report exactly one readiness state: `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, or `HUMAN_DECISION_REQUIRED`. Do NOT dispatch work below `READY`.
4. Confirm whether original implementation has been finalized and whether it is safe to start this follow-up. If not, record an external dependency and leave the task queued.
5. Resolve each Slice Task Type from the CURRENT Workspace vocabulary. Never invent a Task Type or default to `code`.

## Coding / frontend doctrine

- All coding Slices use `/caveman` and `/coding-guideline` before making changes.
- Frontend Slices use `/impeccable` and a Claude agent if host routing permits.
- Every Slice gets `qa-verification`. Code changes additionally get `code-review`. User-visible/runtime behavior adds `runtime-validation`. Agent prompting/tool/routing changes add `agent-trace-analysis` with real traces.
- QA supplies evidence; the PM decides approve, rework, continue, new Slice, Issue or Human escalation. Current-Slice regressions cannot be parked as Issues.
- Machine validation must be maximized before any Human validation. Evidence and Human checks remain separate.
- Never claim Remotion install/playback/export or real microphone/multimonitor behavior passed without running a test in an authorized target environment.
