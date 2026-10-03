# 02 — Target Architecture

## 1. Four layers

### A. Scene contract

The public contract used by the Brain/task agents. It should remain declarative and object-oriented rather than DOM-oriented.

Target capabilities, names to be reconciled with the real repository during Slice 00:

- list available scene objects
- create/instantiate an object from a prefab
- update instance props/data/state
- show/hide/focus/reorder
- destroy instance
- inspect instance provenance and owner

The scene contract owns placement, z-order/layering, sizing, visibility, and task/agent ownership.

### B. Prefab catalog

Canonical shared definitions. Each entry needs enough metadata for discovery and safe reuse:

- stable prefab id
- version
- title/description/search aliases
- family/category/tags
- base/system/custom classification
- mutability/protection policy
- source/provenance
- template/style/behavior references
- input schema
- emitted/accepted event contract
- optional child/composition dependencies
- compatibility/runtime requirements

The catalog must be dynamically discoverable. Adding a valid prefab must not require editing a central switch/table for ordinary registration.

### C. Prefab runtime

Responsible for:

- resolving definition + exact version
- validating inputs
- creating an isolated instance
- applying styles without leaking globally
- mounting behavior
- providing a local event bus/bridge
- cleanup on unmount
- exposing instance update hooks
- preventing arbitrary authority escalation

### D. Authoring/promotion flow

Jarvis needs two authoring modes:

1. **Instance adaptation** — cheap, normal, does not mutate catalog source.
2. **Definition authoring** — fork/create/save a reusable prefab, validated before publication.

Base/system definitions have a stronger mutation gate: direct edit requires explicit user intent.

## 2. Instance shape

Exact field names must follow the repository's conventions, but the conceptual instance needs:

```json
{
  "instance_id": "...",
  "prefab": {"id": "shared.checklist", "version": "1.2.0"},
  "owner": {"board_id": "...", "task_id": "...", "agent_id": "..."},
  "props": {"accent": "...", "title": "..."},
  "data": {"items": []},
  "state": {},
  "layout": {},
  "visibility": "visible"
}
```

Do not persist implementation-only DOM handles in canonical state.

## 3. Input schema

Primitive inputs remain useful, but the schema must also support structured data.

Minimum conceptual types:

- string
- number
- boolean
- color
- enum
- object
- array
- asset/reference if an existing Jarvis contract already exists for assets
- prefab/child reference if composition already exists

Structured types should have nested schemas/defaults rather than arbitrary unvalidated blobs when practical.

## 4. Behavior and event bridge

Prefab JavaScript may:

- react to local clicks/keyboard/input
- update local instance UI/state through the prefab runtime
- emit semantic events such as `checklist:item-toggled`
- request a higher-level action through a controlled bridge

It may not directly:

- invoke arbitrary tools
- access unrestricted filesystem APIs
- mutate unrelated scene objects by DOM reach-through
- bypass agent/runtime permission checks

High-level action path:

```text
user interaction
 -> prefab semantic event
 -> scene/object bridge
 -> Brain/task agent decision
 -> permitted tool/runtime action
 -> result
 -> explicit scene/prefab instance update
```

## 5. Window families

Do not invent a new window taxonomy during implementation. Slice 01 must recover the already-agreed Rework FENETRES families from the repository/docs/task history and convert those into prefab bases.

Each family should expose only the variables that are genuinely variable. Shared shell behavior should be composed/inherited rather than copied.

## 6. Versioning and provenance

A live instance should be able to answer:

- which prefab and version created me?
- am I a base, fork, or custom definition?
- what parent/source did I derive from?
- which agent/task created this instance?
- has the instance diverged from the saved prefab definition?

Saving a modified object as a new prefab should preserve derivation metadata where the existing project conventions support it.
