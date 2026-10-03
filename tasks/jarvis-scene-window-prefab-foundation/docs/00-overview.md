# 00 — Overview

## Goal

Give Jarvis a reusable, evolvable vocabulary of scene objects instead of forcing either hardcoded UI families or fresh HTML/CSS/JS generation for every visual need.

The foundation must support:

1. **Reusable prefab definitions** with template, style, behavior, metadata, inputs, outputs/events, provenance, and version identity.
2. **Window families as first-class prefabs**, based on the already-defined Rework FENETRES direction rather than inventing unrelated window models.
3. **Runtime instances** that are parameterized and stateful without mutating their base definitions.
4. **Structured inputs** for lists/objects, enabling checklists, tables, cards, and similar data-driven elements.
5. **Agent authoring operations** to inspect, reuse, instantiate, fork, create, validate, preview, and save prefabs.
6. **Safety boundaries** between generated UI behavior and Jarvis runtime/tools.
7. **A shared library management surface** with clear base/variant/custom provenance.

## Mental model

```text
Brain / task agent
      |
      | declarative scene operation
      v
Scene manager / scene contract
      |
      | instantiate/update/show/hide/destroy
      v
Prefab instance
  - prefab id + version
  - props / structured data
  - instance state
  - scene layout / ownership
      |
      v
Prefab runtime
  - template
  - scoped style
  - behavior lifecycle
  - controlled events
      |
      v
DOM / SVG / Canvas inside the object's owned surface
```

The prefab is the reusable definition. The scene object is the live instance. The Brain talks to the scene/object contract; it does not need to hand-edit DOM for ordinary use.

## Scope

### In scope

- Existing window-family migration/audit.
- Prefab metadata/schema and registry.
- Dynamic discovery/loading instead of a hand-maintained per-prefab core table.
- Primitive and structured inputs.
- Instance lifecycle and local state.
- Controlled event bridge from prefab behavior to Jarvis.
- Fork/save-as-new-prefab workflow.
- Explicit protection policy for base/system prefabs.
- Shared prefab library browsing/inspection/preview.
- Agent-facing operations suitable for MCP/tool exposure.
- Tests, conformance gates, documentation.

### Non-goals

- Redesigning Session / Board / Context.
- Redefining how a board enters Presentation mode.
- Implementing the presentation conductor, ambient listening, vocal initiative, or presentation settings.
- Letting prefab JavaScript directly call arbitrary Jarvis tools, filesystem APIs, or agent runtimes.
- Introducing a frontend framework/bundler solely for this feature unless the audited Jarvis repository already requires one.
- Automatically rewriting base prefabs as a side effect of normal runtime customization.

## Success condition

A fresh Jarvis agent can ask the library for a suitable object, instantiate a window/checklist/etc. with data and variables, interact with it through a controlled event contract, fork or create a new prefab when necessary, and save that new prefab for future reuse — without editing core scene code for each new object type.
