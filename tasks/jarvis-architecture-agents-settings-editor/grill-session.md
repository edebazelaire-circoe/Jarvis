# Grill Session - reconstructed

> Reconstructed faithfully from the project conversation on 2026-10-23. This is not a verbatim transcript.

## Product correction: Agents/models becomes Architecture & Agents

The user rejected a generic "Agents & models" page containing response personality controls. Tone, politeness, formality, verbosity and similar human-facing behavior belong to the Jarvis voice/personality area, not the architecture/model area.

The new page is **Architecture & Agents**.

## Architecture tab

The user wants a 2D schema made of real brain entities, not cards connected for decoration. Brain nodes are movable and visually inspectable. The architecture must represent actual calling/data relationships.

A link between two nodes means something real happens between them. Disabling an editable link must alter runtime behavior. The example given was the Voice/Core relationship: if the runtime permits that link to be disabled, Voice must then stop calling Core and handle the affected path by itself. Conversely, if a connection is structurally mandatory and cannot be removed, the UI must show that fact clearly using a distinct connection nature/style and must prevent invalid modification.

The graph therefore needs:

- real directional links;
- typed channels/purposes;
- locked mandatory links;
- editable active links;
- editable disabled links;
- connection creation/removal only when runtime compatibility rules allow it;
- visible impact/meaning, not unexplained decoration;
- audio input and audio output as first-class endpoints;
- the real current brains only by default;
- future extensibility for additional brains.

The user specifically wants the current Tool Brain visible alongside Voice/Core after the live runtime audit confirms its actual wiring.

## Brain configuration

There must not be a separate Brain tab.

Right click (or equivalent context action) on a brain opens a brain-specific configuration window over the Architecture page. The user is comfortable with a small movable floating window or an overlay/background treatment; the important point is that brain configuration is contextual, not a permanent top-level tab.

Brain configuration includes:

- model/provider selection;
- mission/responsibilities/prerogatives;
- brain-specific prompt/instructions where applicable;
- activation/deactivation only if that brain is legally mutable;
- how aggressively that brain uses sub-agents.

The delegation setting is about **when/how much to delegate**, not which concrete sub-agent is chosen. The desired scale is conceptually:

- never;
- occasional/rare;
- standard;
- proactive;
- exploratory / spread widely.

Some brains may be configured to never call sub-agents and complete all work themselves.

## Global sub-agent configuration

Exact sub-agent/model selection belongs in the global Sous-agents tab.

This area defines roles such as code/research/QA and associates each role with the actual candidate harness/model configuration, priorities/order and fallbacks. A coding role might prefer a code-specialized harness/model while research might prefer another model. The specific examples are illustrative; the live model catalog and role registry are authoritative.

The user wants a global separation:

- each brain controls **when it delegates**;
- global sub-agent configuration controls **what role/candidate is invoked**.

The current seven-role registry on main must be preserved rather than replaced with the simplified five-role set drawn by the mockup.

## Existing implementation review

The current repo already has:

- a canonical sub-agent role registry and role UI;
- ordered routing candidates and fallbacks by task profile;
- model/provider catalogs;
- prompt overrides and Work Methods;
- Tool Brain ownership/runtime concepts;
- old `Auto` / `Duplique` delegation projection.

The target should reuse the stable mechanisms but reorganize the product concepts. Old CLI command/path/permission details, re-probe actions, diagnostics and compatibility controls should not dominate this page.

## UI direction

The user approved two references for this task:

1. a neon Architecture page with a real diagram, audio endpoints, semantic arrows and a floating brain configuration panel;
2. a neon Sous-agents page with role rows, model/fallback/tool information and global policy/routing visualization.

The visual language should stay consistent with the new Settings direction: dark blurred background, neon cyan/blue/purple accents, floating translucent glass panels, readable hierarchy, modular alignment, no inspirational quote clutter.

The approved images are copied to `references/` and interpreted in `docs/07-reference-interpretation.md`.
