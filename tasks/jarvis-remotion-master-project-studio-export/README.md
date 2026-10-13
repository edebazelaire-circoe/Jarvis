# Jarvis Remotion Master Project + Whole-Video Export

**Project:** Jarvis  
**Repository:** `edebazelaire-circoe/Jarvis`  
**Task slug:** `jarvis-remotion-master-project-studio-export`  
**Drive target:** `Jarvis/task/to-do/jarvis-remotion-master-project-studio-export/`  
**Planning reference:** GitHub `main` at `d101d88740c4cf10c2da8114384d0148ec05c3ff` on 2026-10-13; freshness check is mandatory before every Slice.  
**Origin:** user review of the post-`jarvis-remotion-native-studio-playback-fix` architecture and screenshot of Variants / Remotion Studio.  
**Nature:** additive architectural correction, deliberately limited to phases **A + B**: master Remotion project, full Remotion Studio project view, whole-video export, and voice-compatible regeneration.  
**Status:** planned; current scene-based presentation runtime remains supported and must not be destructively replaced by this task.

## Executive objective

Restore Remotion as the primary video architecture instead of treating every scene as an independent mini-video that Jarvis later stitches together with its own multi-Player runtime.

For this task, a Jarvis Presentation Variant gains a **derived Remotion master project** containing the variant's ordered scene sources and a real master Remotion Composition for the whole video. That master project must be usable by native Remotion Studio and by the guarded Remotion render path to export the whole variant, including scene media/audio. Voice-driven generation and source edits must continue to work without requiring the user to edit files in Remotion Studio: the existing durable scene/version model remains canonical for now, and the master project is regenerated from it.

This task does **not** replace the current Variants Player, composition-clock/sequencer, presenter runtime, scene-level Studio publish round trip, or variant graph. Those are intentionally kept as compatibility paths while the master path proves itself.

## Product principle

**Remotion is the base. Jarvis augments it; Jarvis must not unnecessarily reimplement, narrow, or fragment Remotion's native video model.**

The immediate goal is not to redesign the whole presentation system. It is to make the common workflow simple and native:

1. user speaks with Jarvis and asks for a video/presentation;
2. Jarvis creates versioned Remotion scene sources as it already can;
3. the active variant deterministically materializes as one Remotion project with one master composition;
4. Remotion Studio opens the whole project, not one scene masquerading as the project;
5. export renders the whole master composition, including audio/video media;
6. user asks by voice for an edit; Jarvis publishes a new scene source version and the master project/export reflects it automatically;
7. direct live editing/publishing of arbitrary master-project files can be designed later.

## Start here

1. Read `slices/TODO.md` and execute `slices/00-project-manager/SLICE.md` yourself. Do not delegate Slice 00.
2. Independently inspect current `main`, current docs, current tests and current runtime ownership before accepting this handoff's diagnosis.
3. Reconcile that audit with `docs/01-decision-log.md` and `docs/02-architecture.md`.
4. Report exactly one readiness state: `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, or `HUMAN_DECISION_REQUIRED`.
5. Dispatch nothing below `READY`.
6. Immediately before every Slice dispatch, refresh the exact implementation owners and contracts on the actual HEAD.

## Locked scope

- **A — Master project:** derive one normal Remotion project/master composition from one Presentation Variant.
- **B — Studio + export:** open that whole project in native Remotion Studio and render/export the whole variant through the existing guarded Remotion renderer.
- Keep voice-native creation and re-edit viable without Remotion Studio: edits continue through the existing source/version path and automatically regenerate the master view.
- Preserve current Presentation/Variant/Scene identity, exact prefab/version pins, rollback, branching, score/cues, Board/Artifact provenance, sandboxing and security boundaries unless a Slice explicitly proves a compatible additive change.
- Do not delete, silently migrate, or rewrite the stable scene-based Variants playback path in this task.
- Do not silently fall back to Slidecar or to pre-rendered per-scene clips when the master path is incompatible. Say why and leave the existing path intact.
- Do not modify the user's live Core/data during automated verification. Use isolated roots, ports, fixtures and test browsers.

## Explicit non-goals

- Replacing the Variants multi-Player runtime with one master Remotion Player (future phase C).
- Making the generated master workspace the canonical editable source of truth.
- Publishing arbitrary edits made to `Root.tsx`, master orchestration, shared modules or top-level project files back into Jarvis data.
- Deleting the existing scene-level Remotion Studio round trip.
- General dependency/package-manager liberalization. Existing trust/security policy remains the floor; this task must not add narrower restrictions accidentally.
- A broad UI redesign.
- Solving every historical mixed-FPS/mixed-dimension presentation by mutation. Legacy incompatibility must fail closed and preserve the current path.

## QA doctrine

- Every implemented Slice gets an independent `qa-verification` pass.
- Every code Slice additionally gets `code-review`.
- Every user-visible or runtime Slice additionally gets `runtime-validation` with real evidence where feasible.
- Any Slice changing agent prompts, MCP tools, routing, authoring policy or agent runtime additionally gets `agent-trace-analysis` with real trace evidence.
- QA agents return evidence/findings; the Project Manager decides approve, rework, continue, create a new Slice/Issue, or escalate.
- A regression caused by the current Slice is blocking and cannot be parked in `Issues/`.
- Human validation never substitutes for machine QA. Exhaust machine validation before asking for a Human check.
- Coding Slices require `/caveman` and `/coding-guideline`.
- Frontend Slices additionally require `/impeccable` and a Claude frontend Work Agent when the host supports that routing rule.
- Every Slice must resolve a valid current Workspace Task Type at runtime. Never invent one and never default blindly to `code`.

## Important current-state facts to re-check

At the planning reference commit:

- `jarvis/domain/remotion_studio.py::plan_workspace` generates a scene-only `studio-root.tsx` and `jarvis-studio-scene` package.
- `jarvis/core/remotion_studio_service.py` opens/syncs one `StudioPin` (one source version) at a time.
- `docs/remotion-render.md` explicitly says one scene per export; `presentation_render.scene_target` refuses a multi-scene snapshot without an explicit `scene_id`.
- `PresentationStudioCompositionClock` builds a Jarvis interval map over per-scene Remotion compositions; the visible full-deck video in Variants is not itself a native Remotion Composition.
- `presentation_source read/write/preview` is scene-scoped, which is acceptable for this task as the canonical write path so long as the master project automatically reflects those version changes.
- The recently merged `jarvis-remotion-native-studio-playback-fix` is valuable and should be treated as the compatibility baseline, not discarded.

## Handoff inventory

- `docs/00-overview.md`: goal, scope, mental model and user journey.
- `docs/01-decision-log.md`: locked decisions vs provisional technical choices.
- `docs/02-architecture.md`: target boundaries and data flow.
- `docs/03-implementation-strategy.md`: additive rollout and rollback plan.
- `docs/04-testing-and-quality.md`: regression and real-runtime gates.
- `docs/05-documentation-levels.md`: current/required documentation maturity.
- `slices/`: dependency-ordered implementation plan.
- `Issues/`: meaningful discoveries outside the current Slice.
- `LOG.md`: implementation agents append durable execution notes here; it is intentionally not pre-populated with fictional progress.
