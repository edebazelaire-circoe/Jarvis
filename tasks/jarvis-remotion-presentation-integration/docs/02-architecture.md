# 02 - Target architecture

```
User voice / Control Center UI
        |
Jarvis authoring brain + Tool Brain (existing ownership, permissions)
        |
Presentation Service (existing Core writer)
  | ArtDirection + Score/Cues + Variants + Scene IDs
  | Semantic Edit API + bounded undo + source version pins
  | Engine policy: remotion (forced), slidecar (explicit experimental only)
        |
PresentationEngine interface (small, versioned)
  +-- Remotion adapter (new; default)
  |    | Remotion Player embedded preview; Studio managed side window
  |    | React/TSX source, props/schema, protected bundler and HMR
  |    | frame/sequence executor for locked timing
  |    +-- export job to MP4/still/PDF (not the source)
  +-- Slidecar adapter (existing; selected experimentally by human only)
        |
Shared Scene/Window/Prefab host and fullscreen control
        |
Core document store + Artifact discoverability + Board artifact links
        |
Source (mutable canonical) ----> frozen self-contained snapshot
                                       +--> derivative renders with provenance
```

## Ownership boundaries

- Core remains the only document/variant/score writer, with existing revision CAS and serialized updates. No renderer writes Board memory or artifact registry directly.
- Keep `SceneService`, `PrefabService`, `PresentationStudioService` and `ToolBrain` canonical. Remotion is an adapter and a managed local process, not a second independent Presentation domain.
- Remotion tooling must not inherit arbitrary local process/file/network rights from Jarvis just because it runs generated React/TSX. Restrict roots, dependencies, asset URLs, ports, download origins and execution privileges. Validate untrusted sources; add adequate process isolation and bounded resource controls.
- Native live HTML and Remotion React may share data/props contracts, but do NOT claim equivalent semantics for DOM handlers, async data, CSS animations, frame determinism, sound or generated PDF. A prefab declares per-engine support and any adapter requirements.
- Jarvis's existing external MCP `Plugin` registry is a URL-based remote server system. A local Remotion capability is not an arbitrary external MCP server; unify the User Experience only after the native lifecycle contract is defined.

## Engine policy

- Current default engine is Remotion, globally for ordinary creative work. No autonomous selection from an engine menu.
- Human diagnostic/experimental Slidecar selection is explicit, visible and reversible. Failed Remotion requests return typed errors and repair guidance, **never** a Slidecar result.
- Unsupported a prefab in Remotion: report missing capability, offer to adapt (with explicit source change) or decline; never quietly flatten to a screenshot when editability was requested.

## Document + artifacts

- Active presentation aggregate remains mutable and independently recoverable. The registry makes it discoverable as the logical source parent and allows navigation from a Board.
- A frozen version must include manifest, scenes, score, DA, pinned prefab code, required local assets, dependency manifest, engine/version and provenance; use content hashes and safe paths, not raw machine absolute paths or expiring signed URLs.
- MP4, PDF and stills are children of one precise frozen source version/variant; Artifact relations are immutable, cyclic relations forbidden, automatic active-Board links and explicit cross-Board links follow the current WorkspaceService.
- The choice of store mapping is a prerequisite because current Artifact records are terminal evidence and presentation sources are mutable.

## Editor + preview

- Editing voice request -> Core semantic operation -> (a) props patch and live Player inputProps update OR (b) source-edit job under lock/revision validation -> HMR/scene remount -> acknowledgement. A preview-only DOM/props change cannot be mistaken for a saved source.
- Keep user presenter/agent presenter/rehearsal, cue order, locked timing and silence authority from existing Score. Remotion's frame count is a rendering mechanism, not the master choreography.
- Opening Remotion Studio is optional alongside Jarvis. It is one local managed server, not mandatory output. Jarvis/Tool Brain and subagents use one edit route; concurrent updates have expected revisions.

## Prefab marketplace

- `Prefab` is the umbrella type. Semantic subtypes: Component, Composition, Page, Presentation, Asset. This vocabulary remains unchanged across engine types.
- Cards show title, visual preview, type, summary and visual tags. Details show source/upstream/license, parameters with types/defaults/ranges, engines and capabilities, dependencies, versions and provenance.
- Version pin immutable; newer version badge/notice, update review under a fresh variant. Never auto rewrite or replace original version.
- Promotion requires explicit user command. Do not publish every new scene or reused asset by default; do not fork an upstream license unexamined.
