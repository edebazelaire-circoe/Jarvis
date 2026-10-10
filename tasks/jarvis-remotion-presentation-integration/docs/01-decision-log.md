# 01 - Chronological decisions (confirmed vs inferred)

## Earlier confirmed Presentation Studio decisions (2026-10-07)

D01 Presentation is a durable editable object, not a static HTML/MP4/PDF delivery. D02 Generic borderless fullscreen, retaining ordinary prefab/window support. D03 Reuse Scene/Prefab foundation. D04 High-quality one-shot report; serious presentation should begin near complete, exploratory requests intentionally differ. D05 Structured art direction always available and may be inferred/generated. D06 Script/score required: presenter, text/note, visual/cue/motion, timing and silence. D07 Soft semantic cues plus deterministic locked sequences; audience-room text cannot create arbitrary commands. D08 Human presenter/agent sidekick, Jarvis presenter and rehearsal. D09 Live control patches, structural edits and subagent recoding with hot reload. D10 Autosave active document, bounded undo, creative branches and per-scene alternatives, not unbounded snapshots. D11 Fullscreen Variant Explorer, branch naming/numeric IDs, multiple comparisons and explicit mix into a new variant. D12 Voice-first and GUI parity. D13 Only explicit prefab/template promotion.

## Later confirmed Remotion and library decisions (2026-10-08)

D14 Keep existing Slidecar implementation; prioritize Remotion for real use and testing instead of replacing foundational domain/score/variants. D15 **Remotion forced default**; agent has no engine selection autonomy; Slidecar available only through explicit experimental human control; no auto fallback if Remotion breaks. D16 Local Remotion installed once and managed by Jarvis plugin/capability; no terminal steps for user, no fresh dependency tree per slide. D17 Show live Remotion preview in Jarvis, Studio launch optional, use fast props for small edits and agent/source/HMR for large changes; export only on demand. D18 Live Board assets during editing, self-contained captured content at freeze/share/export. D19 Editable presentation source is logical parent, exports (MP4, PDF, images) are derived artifacts and must retain parent/variant/version provenance; Board context holds links. D20 Shared prefab marketplace with semantic categories Component/Composition/Page/Presentation/Asset across engines and tech stacks, without a translation dictionary by renderer. D21 Explicit typed parameters exposed in details; compatibility declared and unsupported engine cases refused rather than misleading. D22 Immutable pinned prefab version; newer versions notified but never auto-adopted; upgrade via trial variant. D23 External source and dependencies/license/provenance tracked. D24 Publish globally only on explicit request; project-local experimentation is not a published prefab.

## Explicitly provisional / not user decisions

P01 Whether to extend the immutable Artifact evidence kind for editable presentation sources or to create a stable catalog link to the mutable Presentation aggregate is a repository compatibility decision for Slice 07. Both must meet D19 without violating evidence immutability.
P02 Exact Node binary distribution/caching policy and plugin UI packaging must follow the installed host's permissions and current runtime capabilities (Slices 03/04).
P03 Remotion SDK/codemods APIs are experimental; pin a tested version and isolate adapter assumptions, not a blanket API commitment.
P04 The exact native vs adapter-compatible limits for importing HTML into Remotion rendering or rendering Remotion inside Slidecar require proof; treat compatibility as capability-specific.
P05 Initial deployment target is the Jarvis local Control Center platform documented by the repository; operating-system requirements must be resolved at the readiness gate.
P06 Legacy Slidecar live edit during audience playback was not expressly finalized beyond existing defaults; preserve existing behavior until a separate confirmed change is requested.

## Non-goals / prohibitions

No change to active agent's branch before finish; no Remotion fallback; no unsolicited global prefab publication; no guessed compatible engine; no fresh presentation source that is only an MP4 or PDF; no extra standalone Board state machine, plugin credential store or Scene renderer; no licensing assumptions.
