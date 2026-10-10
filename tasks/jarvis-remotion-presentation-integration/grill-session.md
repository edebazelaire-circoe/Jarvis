# Reconstructed decision record (not verbatim)

**Source**: user discussion from 2026-10-07 to 2026-10-08, plus supplied active GitHub branch link. The exact audio/chat transcript is not packaged verbatim. Wording below is faithfully reconstructed; no additional approvals are implied.

## Original interactive presentation design

User wanted true borderless full-screen, an HTML/CSS/JS slide system with independent editable scenes, good one-shot reports vs substantial iterative presentation authoring, a mandatory art direction (provided/inferred/generated) and presentation script, cue-aware spoken pacing, Jarvis either presenting or silently assisting a human, locked timing for selected passages, rehearse/return/recover, live variable edits and slower subagent recoding for major edits. All active content must stay source-editable and not be flattened into a video. There must be variants of full presentations and local slides, visual branch explorer, compare multiple branches, mix their dimensions into a new variant, undo/autosave. Reusable material goes into the common prefab library only if the user explicitly requests promotion.

## Remotion re-evaluation (after original task started)

User tested an Opus-based Remotion workflow and wants a Remotion-first implementation inside Jarvis. Jarvis manages Node/NPX/install/runtime/Studio preview/Player, controls and export via one installable capability with no manual terminal actions. Remotion is the forced default. The already-built HTML engine is called **Slidecar** and remains a human-only EXPERIMENTAL selection. Agents must not choose between them; Remotion errors are reported and fixed, not hidden by fallback.

Existing Board/InfoBoard content is referenced live while authoring; freezing/exporting a presentation must package required assets self-contained. An editable presentation source is the logical parent artifact; MP4/PDF/stills and other exports are derivations with provenance. Project/board context stores discoverable links to content without copying every folder into a Board. Installation should be once per runtime environment, not once per scene.

## Prefab library refinements

One shared marketplace-like library for Slidecar and Remotion content. `Prefab` remains an umbrella, while `Component`, `Composition`, `Page`, `Presentation` and `Asset` are semantic categories throughout the app. Display technical stack, capabilities, compatibility and supported parameters on detail view. No mandatory up-front parameter dump. A version pinned into a presentation never silently updates. New upstream version notices are informational; trials of a new version happen in a new presentation variant. External imports trace original source, license, dependency versions and whether made locally in live edit or downloaded. Reusable items are promoted only at an explicit user command.

## Final trigger

User: `@Create Task` with branch https://github.com/edebazelaire-circoe/Jarvis/tree/task/jarvis-interactive-presentation-studio; agent is still close to finishing. Request: inspect branch, check conformity to all above, create implementation-ready follow-up. No permission to disrupt the current branch.
