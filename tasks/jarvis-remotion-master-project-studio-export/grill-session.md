# Reconstructed planning session

> This is a faithful reconstruction of the relevant conversation, not a byte-for-byte transcript export. Repository facts were checked against GitHub `main` during planning; implementation agents must refresh them.

## User problem statement

The user observed that Jarvis's presentation experience shows several ordered scenes/slides and can play them like one video, yet clicking **Remotion Studio** opens only the currently selected scene. The user's intended model is a normal Remotion workflow: one project for the full video/presentation, with scenes, animation, sound and export managed as one video composition. Jarvis may add versioning, voice control, research, variants and other capabilities, but should not constrain what an agent can natively do with Remotion.

The user compared the desired experience to opening Claude Code in a folder with Remotion installed, asking for a video, and getting a complete editable/renderable Remotion project.

## Diagnosis reached in the discussion

Repository inspection showed that the current behavior is architectural, not just UI:

- each Jarvis Studio scene is an independently versioned Remotion source/composition;
- Remotion Studio materializes only one selected scene source at a time;
- Variants builds a global Jarvis composition clock over several per-scene Players;
- the guarded export path currently renders one scene, not a full multi-scene variant;
- native authoring improved significantly in the recent task, but is still scene-scoped.

The existing architecture had defensible reasons (per-scene sandbox/failure isolation, pins, rollback, hot reload) and currently works fairly well. The user explicitly does **not** want to destabilize it with an immediate total rewrite.

## Migration sizing discussion

The migration was split into three conceptual levels:

- **A:** derive a full Remotion project/master composition from a variant;
- **B:** make native Remotion Studio open that whole project and support whole-video render/export;
- **C:** later, optionally replace the Variants multi-Player runtime and/or make the project workspace canonical.

The user approved doing **A + B now** and deferring C.

## User correction / simplification

The user said the project had likely tried to do too much too early. The current architecture should be put to the side rather than broken: it is useful, can remain as a compatibility layer, and may be revisited later.

The focus is Remotion itself: easy video and audio behavior, easy full exports, fast edits, and the ability to ask Jarvis by voice to regenerate or modify the video. The user does **not** require direct live file editing in Remotion Studio as part of this task if voice edits can publish new versions and regenerate the full video correctly.

## Resulting task mandate

Create an additive master-project path derived from the existing versioned scene sources. Preserve current scene-level runtime behavior while proving a native full-video Remotion project, Studio view and export. Voice source edits remain canonical and should automatically invalidate/rebuild the master project. Do not widen the task into the later phase-C Player/runtime migration.
