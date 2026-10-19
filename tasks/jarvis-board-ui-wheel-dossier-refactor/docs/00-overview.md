# 00 — Overview

## Problem

The current Control Center contains several layers of historical UI that no longer match the intended Jarvis mental model:

- a mutable interaction-mode selector (SIMPLE / PRESENTATION / REUNION);
- a separate Board selector in top-left chrome;
- persistent voice/model status text;
- a permanent hidden-object affordance/count;
- an orbital wheel whose first-level entries are a mixture of input/capture operations rather than stable product categories;
- a technical workspace/memory inspector that is not the human documentary workspace the user wants.

Adding more controls to this shell would worsen the problem. The task is a **replacement and consolidation refactor**.

## Target outcome

### Main Board view

The Board view stays the spatial working surface. The central scene and right active-workspace/presentation rail are not redesigned wholesale by this task unless their safe-area layout must move around the new controls.

Persistent main-shell controls should be sparse:

- left-edge wheel anchor;
- compact bottom-left Board card;
- existing top-right global launcher only for genuinely global functions still owned there;
- transient recording indicators while recording;
- right workspace rail where applicable;
- Chat access.

### Fixed Board type

User-facing types:

- **Assistant**
- **Présentation**
- **Réunion**

The type is chosen at Board creation and is not an ordinary mutable field afterward. Jarvis derives behaviour from the active Board's type. The legacy independent `InteractionMode` may remain internally only as a compatibility/runtime policy implementation detail if current Presentation code requires it; it must not remain a second user-controlled truth.

### Orbital wheel

Primary categories:

1. JARVIS
2. Sélection
3. Dossier
4. Capture
5. Paramètres

The selected category opens one contextual second-level radial layer. Switching category replaces it. Closing the wheel removes it. There is no simultaneous pile of second-level panels.

### Dossier

Dossier is the human-facing documentary projection of the active Board. It must combine, without duplicating truth unnecessarily:

- Board memory files / summaries / plans / decisions;
- linked Artifacts and their provenance;
- useful document/media representations;
- curated context status and optional advanced Jarvis memory/provenance views.

It must support both manual interaction and Jarvis-guided navigation.

## Non-goals

- Implementing a new Meeting runtime from scratch.
- Replacing Core as capture truth.
- Replacing canonical scene/selection/visibility models.
- Rewriting the right workspace rail unrelated to this IA.
- Building a new generic file database parallel to Board memory and Artifacts.
- Implementing the completed-task lifecycle follow-up in this task.
- Cosmetic cloning of the generated reference image.

## Planning reference

Observed repository head at planning: `cd5dfa47c53e6d8c7baa39892a5f0ffbe225bef5` on `main`.

The Project Manager must re-read HEAD before work. In particular, the planning audit found the current Board contract explicitly says Board kind and interaction mode are independent; that statement is now contrary to the locked human intent and must be migrated deliberately rather than silently ignored.
