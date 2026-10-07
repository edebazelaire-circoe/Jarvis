# 01 - Decision Log

## D01 - Presentation artifact, not HTML export
Locked. The durable object is a structured Presentation Artifact. HTML/CSS/JS scene code is implementation material inside that artifact, not the only source of truth.

## D02 - Generic fullscreen borderless capability
Locked. Presentation needs true borderless fullscreen, and the capability should be exposed through the canonical scene/window surface so other compatible prefabs can use it too.

## D03 - Scene/Prefab foundation remains authoritative
Locked. Reuse `jarvis-scene-window-prefab-foundation`; do not create a presentation-only prefab runtime.

## D04 - Strong first draft
Locked. Serious authoring aims for a near-presentable first version, not a rough draft that requires the user to rescue it.

## D05 - Exploratory mode is intentionally different
Locked. When the user explicitly wants inspiration or is vague by choice, generate divergent directions/variants rather than over-interrogate.

## D06 - DA is mandatory
Locked. A presentation always has an art-direction profile. Source priority: provided reference -> inferred from inspectable project context -> generated from context.

## D07 - Score/script is mandatory
Locked. The presentation score is part of the artifact and includes presenter ownership, speech/intention, visual actions, animation, cues, timing and explicit silence.

## D08 - Event-driven cues with optional locked sequences
Locked. Soft semantic cues drive most flow; selected sequences may use deterministic timing.

## D09 - Ambient cue matching is pre-authorized, not general authority
Locked architectural interpretation. Ambient speech may satisfy only currently armed score cues and trigger only their bound reversible presentation actions. It cannot create arbitrary actions.

## D10 - Three playback roles
Locked. User presenter + Jarvis sidekick, Jarvis presenter, and rehearsal.

## D11 - Three edit tiers
Locked. Control/variable patch -> structural patch -> source edit/hot reload.

## D12 - Durable state never depends on direct DOM mutation
Locked. DOM mutation may preview a change, but commit must update canonical artifact/source state.

## D13 - Voice and GUI use one semantic operation layer
Locked. No separate hidden voice editor and visual editor.

## D14 - Autosave current state; short undo/redo
Locked. Active variant is continuously persisted. Undo/redo is bounded and session-oriented.

## D15 - Variants replace durable snapshot history
Locked. Creative branches are durable; linear micro-history is not.

## D16 - Whole-presentation variants and scene-local variants
Locked. Both exist, but scene variants do not clutter the top-level project tree.

## D17 - Variant Explorer is fullscreen and visual
Locked. Tree/history on one side, rich preview on the other, voice and GUI parity.

## D18 - Variant IDs and names
Locked. Each presentation variant has an immutable short numeric display ID and a human-readable title.

## D19 - Variant comparison
Locked. Support multi-variant overview and focused comparison; synchronize comparable scenes where possible.

## D20 - Selective composition creates a new variant
Locked. Mixing narration/DA/motion/content from different branches creates a new child with provenance; do not mutate source branches.

## D21 - Reusable extraction
Locked. Full presentation templates, scenes, DA profiles and motion patterns may be promoted to the shared library after parameterizing/removing project-specific material.

## D22 - No hard dependency on external video generation
Locked. Cinematic sequences are implemented in the interactive runtime; Opus-like frame-by-frame video was inspiration, not a required provider.

## D23 - Live presentation source mutation default
Provisional. Incidental playback manipulation is ephemeral; only explicit editing intent may persist a source change during live presentation. Validate during Slice 00.
