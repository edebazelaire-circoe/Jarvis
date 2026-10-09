# Reconstructed planning session

> This is a faithful reconstruction of the relevant planning conversation, not a verbatim transcript. It exists so a fresh implementation agent does not need the original chat.

## Initial idea

The user wants Jarvis windows to support true fullscreen borderless display, especially for HTML presentation artifacts. Presentation content should feel closer to a cinematic interactive slide experience than to ordinary static slides: HTML/CSS/JS, animation, data display, and presentation-specific art direction.

The presentation is intended both for prepared talks and for Jarvis returning information. Jarvis may present the content itself, or the user may present while Jarvis follows along as a sidekick.

## Preparation matters as much as playback

The user strongly rejected a workflow where Jarvis casually generates a rough five-slide HTML deck and calls it done. For a serious presentation, Jarvis must first understand the content and intended audience, inspect available project information, locate useful files/repositories/data when accessible, and ask only the questions that remain materially unresolved.

If a visual identity exists, Jarvis should use it. If the user points Jarvis to a design system or project folder, Jarvis should inspect/refer to that material rather than make the user manually restate colors and styles. If no DA is supplied and the user does not want to spend time defining one, Jarvis should infer or invent a coherent DA from context rather than block.

For exploratory requests, the user may instead deliberately ask Jarvis to improvise, make several styles, or create something inspirational. That is a different workflow from serious near-final authoring.

## First draft quality

When the user has supplied enough context and spent time preparing the project, Jarvis is expected to go as far as possible in one shot. The first draft should already include coherent narrative, scenes, visuals, animations, script, cues, transitions and timing. Editing is expected, but editing should refine a strong result, not rescue a weak one.

For report/information display, the default expectation is even more one-shot: Jarvis should display information coherently without forcing the user into an editing session.

## Editable HTML scenes

The user wants to exploit HTML/CSS/JS specifically because it is manipulable. Presentation scenes may be authored individually and can later be retained as reusable prefabs/templates.

Common changes should use smart declared variables/controls: colors, typography, spacing, gradients, animation duration, stagger, easing, visibility, data and other scene-specific properties. The user wants conversational micro-iteration such as making a purple more intense, changing a gradient, or staggering cards one-by-one without recompiling the whole presentation.

For larger changes, Jarvis may change source code. The important product behavior is a fluid live-edit loop: patch when possible; otherwise update only the relevant scene and hot-reload/remount it while preserving the authoring context. Direct DOM mutation may be used for preview but must not become durable source state.

The user also wants human edit controls integrated into the presentation when useful, but voice remains central. The GUI and voice paths should call the same semantic operations.

## Presentation score/script

The user added that the script is essential and should be built together with the presentation. The score is not an appendix. It is part of the artifact.

It must describe who is speaking, what is being said or intended, which animation/focus happens at which cue, when Jarvis should speak, and explicitly when Jarvis should remain silent.

The user wants to rehearse with Jarvis. Jarvis should know where they are in the presentation, remind the user of the planned next point when asked, and keep presentation and score aligned as they edit.

When Jarvis presents a report/deck itself, the same score lets Jarvis narrate, reveal, focus and animate at the right moment without requiring user interaction.

## Cue model

The user accepted a mixed timing model:

- most presentation flow is cue-driven with soft/target timings;
- selected sequences may be tightly locked when exact synchronization matters;
- locked sequences are intentionally non-interactive except for emergency/explicit stop behavior;
- the rest of the presentation may pause, branch temporarily to answer/show something, and then resume from the known score position.

## User-presenter sidekick

The user wants Jarvis to follow their live speech and trigger prepared visual actions when the presentation reaches the right cue. This must remain safe with the existing rule that ambient room speech does not authorize arbitrary Jarvis actions.

The design implication is pre-authorization: only finite cues already armed by the active score can be satisfied by ambient speech, and those cues may trigger only their bound reversible presentation actions.

## Autosave and undo

The current working variant is always autosaved. Undo/redo is a short local editing history. There is no need for a large durable linear snapshot history.

## Variants instead of snapshots

The user replaced the snapshot idea with creative variants/branches.

A presentation can branch into alternative directions: visual styles, storytelling strategies, sales-oriented vs feeling-oriented versions, etc. A variant should have a short immutable numeric ID plus a human title so voice commands can say either "the 37" or "Circle Dark".

Variants should preserve parentage so the user can see how the project evolved, delete abandoned branches, resume from an older branch, or keep several directions alive.

Scene-local variants are also wanted for lighter experiments such as three different product-reveal animations without creating three top-level presentation branches.

## Variant Explorer UX

The user proposed a deliberately designed fullscreen variant browser: dark/blurred background, an evolution tree on the left, a rich preview on the right, and the ability to browse slides within the preview. Voice commands and graphical access such as right-click should both be supported.

The user also wants comparison of multiple variants, including four-up overview and two-up focused comparison, with the ability to synchronize equivalent scenes when useful.

## Mixing branches

The user accepted selective composition across variants. Example: keep the narration from one branch but take the DA and animation language from another. This should create a new child variant with explicit provenance rather than destructively merging source branches.

## Promotion to reusable templates/prefabs

A good branch, scene, visual treatment, DA or animation may be saved for later use. Promotion should parameterize or strip presentation-specific content so a reusable template/prefab is not merely a copy of one project's data.
