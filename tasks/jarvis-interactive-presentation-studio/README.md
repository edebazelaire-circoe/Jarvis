# Jarvis Interactive Presentation Studio

## Project

- Project: **Jarvis**
- Canonical handoff slug: `jarvis-interactive-presentation-studio`
- Local handoff: `tasks/jarvis-interactive-presentation-studio/`
- Drive destination: `Jarvis/task/to-do/jarvis-interactive-presentation-studio/`
- Repository: `edebazelaire-circoe/Jarvis`

## Goal

Implement a first-class **interactive presentation artifact and authoring studio** for Jarvis: fullscreen borderless display, HTML/CSS/JS scene modules, strong one-shot presentation generation, live semantic editing, mandatory art direction and presentation score/script, cue-driven playback, rehearsal, Jarvis-as-presenter, user-as-presenter sidekick behavior, presentation and scene variants, visual variant exploration/comparison, and promotion of reusable results into the shared prefab/template library.

The product target is not "generate an HTML deck". It is a living artifact that Jarvis can understand, edit, rehearse, present, navigate, compare, branch, and reuse while preserving precise control for the user.

## Existing repository / project evidence

Planning-time evidence was checked against the live `main` branch and Drive handoffs:

- The repository already implements `PRESENTATION` as an interaction mode. Its ambient lane and bounded presentation working set are documented under `docs/presentation-*.md` and must be reused rather than duplicated.
- Ambient presentation speech is currently contextual and non-authoritative. This task introduces only a narrow exception: a pre-authored, pre-armed score cue may use ambient speech to trigger the already-authorized reversible visual action bound to that cue. Ambient speech still cannot create arbitrary actions.
- `Jarvis/task/current/jarvis-scene-window-prefab-foundation/` is the active lower-level dependency for reusable HTML/CSS/JavaScript prefabs, declared inputs, scene ownership, runtime identity, and agent-facing scene operations. Do not build a second prefab runtime.
- A Tool Brain planning handoff exists in legacy project storage. If a canonical Tool Brain UI-intent contract is present in the repository when this task runs, integrate with it. If not, keep presentation operations semantic and do not invent a second competing UI scheduler.
- Board / Session / Context and recording semantics are existing contracts and are out of scope for redesign.

## Locked product intent

1. **Real fullscreen borderless display.** Presentation surfaces and, where the canonical scene/window contract permits it, ordinary Jarvis windows/prefabs can occupy a selected display with no Jarvis chrome, like a video player. CSS-only fake fullscreen is not sufficient when the host can provide real borderless fullscreen.
2. **Presentation is a reusable artifact, not a static export.** It owns scenes, content references, art direction, score/script, runtime metadata, and edit controls while delegating generic rendering/scene lifecycle to the shared Scene/Prefab foundation.
3. **HTML/CSS/JS remains editable.** Each scene should be independently addressable and reusable. Common changes use declared controls/variables; arbitrary changes may modify source and hot-swap only the affected scene.
4. **The first draft must aim high.** For serious, well-briefed work, Jarvis should return a near-presentable first version: narrative, scenes, DA, content, animations, script, cues, transitions and timing already coherent. A user should not have to enter edit mode merely to make the result respectable.
5. **Exploratory work is different.** When the user is deliberately vague and asks for inspiration, Jarvis may generate multiple lighter, divergent creative directions instead of pretending one direction is final.
6. **Art direction is mandatory.** It may be provided, inferred from project assets/references, or generated from context. Jarvis should inspect available sources before asking the user to restate information it can discover itself.
7. **A presentation score/script is mandatory.** It describes who speaks, what is said or intended, visual focus, animation, cues, transitions and timing. Explicit `Jarvis speech: none` is meaningful because the score tells Jarvis when to stay silent.
8. **Cues are event-driven by default.** Most of the presentation follows semantic cues and soft target timings. Selected passages may become locked deterministic sequences for exact voice/animation timing.
9. **Three playback roles are supported.** Jarvis presents; the user presents with Jarvis as a sidekick; or user and Jarvis rehearse together.
10. **Presentation deviations are recoverable.** Explicit questions or requests may pause the score, show another resource/prefab, navigate backward, then resume at a known score position.
11. **Editing has three cost tiers.** Declared variable/control patch; structural scene patch; source/code edit with scene-local hot reload. Direct DOM mutation is preview-only, never the durable source of truth.
12. **Voice-first, not voice-only.** The same semantic edit/navigation operations drive Jarvis voice commands and human GUI controls. Do not maintain separate edit systems.
13. **Autosave is continuous.** The active variant is always durably saved. Undo/redo is intentionally short-lived and bounded; losing the undo ring after restart is acceptable because the current state is already saved.
14. **No linear snapshot history.** Durable creative exploration uses variants/branches instead.
15. **Presentation variants are first-class.** They have an immutable short numeric display ID, a human title, parentage, rationale and preview. The user can switch, branch, delete abandoned branches and continue from any retained variant.
16. **Scene-local variants are first-class but lightweight.** Exploring three versions of one scene must not create three top-level presentation branches.
17. **Variant Explorer is a designed fullscreen experience.** Dark/blurred background, branch tree on the left, rich presentation preview on the right, keyboard/mouse/context-menu and voice parity.
18. **Comparison is first-class.** Compare two or four variants, enlarge selected candidates, and synchronize equivalent scene navigation where possible.
19. **Selective branch composition is supported.** A user may ask for the narration from one variant and the DA/motion from another. Jarvis creates a new child variant with explicit provenance; this is not a raw Git merge.
20. **Reusable work can be promoted.** A presentation variant, scene, DA, motion pattern, or other reusable presentation pattern may be extracted as a template/prefab after content-specific material is removed or parameterized.

## Important compatibility rule: ambient speech and cue execution

The existing Presentation contract says ambient room speech has no general action authority. Keep that rule.

A score cue is different because its target action is authored and armed before playback. During active score playback, ambient speech may only satisfy one of the finite currently-armed cue predicates and trigger that cue's pre-authorized reversible presentation action. It may not synthesize a new tool call, edit, filesystem operation, or arbitrary UI intent from ambient words.

## Explicit non-goals

- Do not redesign `SIMPLE`, `PRESENTATION`, `REUNION`, Board, Session, Context, memory, or recording.
- Do not create a second scene renderer or prefab catalog.
- Do not require Opus or any frame-by-frame video-generation product. Cinematic HTML sequences are in scope; external video generation is future/optional.
- Do not lock the implementation to a specific frontend framework, bundler, HMR library, or scene DSL before the repository audit.
- Do not make a generic presentation-folder/card shell the focus of this task; the user explicitly deprioritized that UI question.
- Do not preserve an unbounded historical snapshot chain.

## One planning assumption to validate in Slice 00

Incidental runtime actions during a live audience presentation (focus, temporary reveal, navigation, auxiliary prefab display) should be ephemeral. A clearly explicit edit instruction may pause playback and commit a real edit to the active variant, but live playback must never mutate source merely because the user navigated or improvised. The user did not explicitly lock this distinction, so Slice 00 must verify it against repository behavior and raise it only if implementation requires a product decision.

## Start here

The receiving agent is the Project Manager and orchestrator. Open `slices/TODO.md`, then execute Slice `00-project-manager` itself. Do not dispatch implementation work until Slice 00 reaches `READY`.

## Required coding skills

Every coding Slice must load `/caveman` and `/coding-guideline`. Every frontend Slice must additionally load `/impeccable` and use a Claude agent when the host supports that routing rule.

## QA doctrine

- Every implemented Slice gets a baseline `qa-verification` pass.
- Code changes add `code-review`.
- User-visible or runtime behavior adds `runtime-validation`.
- Agent prompts, tools, routing, modules, score execution, cue matching, or agent runtime add `agent-trace-analysis` with real trace evidence.
- QA agents return evidence and findings; the Project Manager decides approve, rework, continue, add a Slice, create an Issue, or escalate.
- A regression caused by the current Slice is blocking and cannot be parked in `Issues/`.
- Human validation never substitutes for machine validation. Exhaust deterministic simulation, replay and automated runtime checks before asking a human to validate audiovisual feel or physical fullscreen behavior.

## Planning blocker

The current Workspace Task Type vocabulary is not exposed in this task-creation environment. Slice metadata therefore uses `task_type: null` plus `task_type_resolution_required: true`. Slice 00 must resolve every implementation Slice to an existing valid Workspace Task Type before dispatch and must not invent labels.
