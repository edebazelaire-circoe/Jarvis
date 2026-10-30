# Grill Session - Reconstructed Product Intent

**Status:** reconstructed faithfully from the current user conversation; this is not a verbatim exported transcript.

## Core problem

Jarvis currently makes ordinary mouse manipulation feel secondary to Voice and Bare Hands. The user wants Voice and Bare Hands to remain useful accelerators, but not prerequisites for comfortable desktop operation.

## Mouse / organization decisions

The requested interactions are intentionally conventional and low-friction:

- resize from every edge and corner rather than only the lower-right handle;
- visually thin borders with a larger invisible hit area;
- Shift during resize to preserve proportions;
- preserve multi-selection when right-clicking a member of that selection;
- offer quick organization from context menus: horizontal, vertical, grid, custom N x M grid, alignment, distribution, same dimensions;
- keep keyboard behavior simple and discoverable;
- add a short-lived Ctrl/Cmd+Z path for geometry/organization operations.

The user explicitly values features that feel obvious once present rather than complex expert workflows.

## Viewer decisions

The viewer is a primary feature, not a small modal. Double-clicking an object should make it understandable immediately in a large, clean surface.

For images/documents:

- double-click or Enter opens a large viewer;
- a compatible multi-selection can open together, for example five images for comparison;
- the background is dark/black and blurred, with generous breathing room;
- layouts can change between horizontal, vertical, grid, custom grid and a few asymmetric comparison layouts;
- the Board stays behind and returns unchanged when the viewer closes.

This is conceptually a fullscreen-sized overlay over the Control Center, not the browser Fullscreen API contract used for presentation mode.

## Agent viewer decisions

The same large overlay should work for an agent that is still running. The user wants to double-click an agent and understand, at a high level:

- what mission it received;
- how long it has been running;
- what it is doing now;
- what it has already done;
- what it expects to do next;
- useful intermediate conclusions or notes;
- which artifacts it has produced.

The UI should be spacious and settings-like rather than dense. It should not dump raw logs or dozens of fields.

The user also wants a manual Stop action and a way to Ask the agent a question. The implementation must reuse canonical cancellation and communication paths instead of inventing new runtime ownership.

The user's research example was an agent comparing monitors across stores: the viewer should make a public plan and evolving findings legible, then allow produced comparison artifacts to be opened.

## Deferred ideas

The conversation also raised other useful directions, but the user explicitly narrowed this feature before handoff creation:

- reworking capsule/minimized representations;
- hiding stars from Appearance settings;
- automatic end-of-task report artifacts;
- persistent containers/groups;
- saving or flattening comparison layouts into composite artifacts.

These are not part of this handoff.

