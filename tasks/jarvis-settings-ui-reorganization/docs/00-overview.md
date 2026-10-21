# Overview

## Goal

Replace the current implementation-shaped Settings navigation with a six-category information architecture and a more legible Jarvis Settings shell, while preserving the semantics of existing settings.

## Scope

- Build a canonical Settings section registry with exactly six top-level categories.
- Replace the current dense modal/top-tab shell with the new Jarvis Settings shell.
- Move Voice + wake-word ordinary controls into `Voix & audio`.
- Move agent/model/sub-agent ordinary controls into `Agents & modeles`.
- Keep memory and knowledge as a first-class category.
- Merge appearance, shortcuts, and normal Bare Hands interaction preferences into `Interface & interactions`.
- Turn API-key management into provider-centric `Connexions`.
- Gather prompt editing, architecture/compatibility, low-level CLI/runtime, diagnostics, test/recording and experimental tooling into a structured `Avance & diagnostic` category.
- Preserve supported legacy tab IDs through explicit aliases until cleanup is complete.
- Update tests and durable documentation to make the six-category model canonical.

## Non-goals

- Do not redesign backend persistence just to match the new page structure.
- Do not rename stored keys merely for UI consistency.
- Do not duplicate server-side enums, ranges, model catalogs, credential providers, or voice schemas in JavaScript.
- Do not remove diagnostics or developer tools solely because they leave normal Settings.
- Do not turn `Avance & diagnostic` into a new unstructured junk drawer; it needs explicit sub-sections.
- Do not redesign the Memory Center, model catalog component, role registry, wake-word runtime, Bare Hands engine, or Voice runtime beyond what relocation requires.
- Do not add new model/provider semantics that the runtime cannot enforce.

## Mental model

Settings should answer: **what is the user trying to change?**

A provider module may still own validation and persistence, but it no longer owns a top-level navigation slot. Modules contribute one or more sections to the canonical Settings registry. A section declares a destination category, a stable section ID, a user-facing label, ordering metadata, and how it mounts/destroys its controller. The six category definitions are fixed; feature modules may not create category seven.

The Settings shell owns navigation, lifecycle, dirty-state coordination, focus restoration, close behavior, and global layout. Feature modules own the controls and runtime-specific validation.
