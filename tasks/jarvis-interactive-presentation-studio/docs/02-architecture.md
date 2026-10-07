# 02 - Target Architecture

## 1. Presentation Artifact domain

Conceptual shape; exact names must follow repository conventions after Slice 01.

```json
{
  "presentation_id": "...",
  "title": "...",
  "active_variant_id": "...",
  "variant_graph_ref": "...",
  "resource_refs": [],
  "metadata": {}
}
```

A Presentation Variant owns or references:

- narrative intent and audience/purpose metadata;
- ArtDirectionProfile;
- ordered scene definitions;
- PresentationScore;
- content/data/resource references;
- reusable asset references;
- edit-control values and scene source revision pointers;
- provenance relative to parent/source variants.

Runtime-only DOM handles, browser objects, process handles and transient playback state must not enter canonical artifact persistence.

## 2. Scene module boundary

A presentation scene consumes the shared Scene/Prefab foundation. Do not duplicate prefab identity, lifecycle, input validation or event bridging.

The presentation layer adds only presentation-specific metadata such as:

- logical scene id/title/role;
- order/section membership;
- score anchors;
- editable presentation controls;
- presentation-specific preview metadata;
- scene-local variant references.

Scene code may be authored independently. A practical implementation may use one source module/directory per scene, but that filesystem shape is not locked until repository audit.

## 3. Semantic control surface

Every scene may expose typed controls. Examples:

- visual tokens: accent, background, gradient, typography scale;
- layout: spacing, alignment, density, card gap;
- motion: duration, stagger, easing, sequence mode;
- content/data references;
- visibility/focus toggles.

Controls should be intentionally curated, not an unbounded dump of every CSS property. The same control metadata powers agent edit tools and the human inspector.

## 4. Edit planner and mutation tiers

```text
spoken/GUI edit intent
      |
      v
Semantic Edit API
      |
      +-- declared control available? --> control patch, no rebuild
      |
      +-- structured scene mutation? ---> structural patch + scene remount if needed
      |
      `-- arbitrary change -------------> source edit + scene-local HMR/remount
```

Every committed edit updates canonical state/source and triggers autosave. Preview-only DOM mutations must either be committed through the semantic API or discarded.

## 5. Hot reload / state preservation

Source updates should refresh only the affected scene when technically possible. Preserve:

- active presentation variant;
- selected scene;
- score/cue position;
- editor selection when compatible;
- presentation playback paused/running state where safe.

If a source edit invalidates the current scene state, remount the scene deterministically and report the reset in authoring/rehearsal mode. Never silently continue with mismatched score state.

## 6. Fullscreen host

Expose a canonical surface mode such as `fullscreen_borderless` through the current scene/window contract, names to be reconciled.

Required behavior:

- selected display is fully occupied;
- Jarvis/window chrome is hidden;
- safe exit restores prior layout/focus;
- presentation can temporarily show auxiliary prefabs/resources and return;
- no CSS-only fake fullscreen when the desktop host supports real borderless fullscreen;
- multi-monitor behavior is explicit and testable.

## 7. ArtDirectionProfile

A structured, reusable profile should cover more than colors:

- palette and gradients;
- typography;
- spacing/density;
- radii/shapes;
- image/illustration/icon language;
- data-visualization treatment;
- motion language;
- example/reference resources;
- provenance: provided, inferred, generated.

The profile must be consumable by scene authoring and by variant comparison/mixing.

## 8. PresentationScore

Model the presentation as multiple coordinated tracks rather than a single text script:

```text
USER SPEECH    -----------      -------
JARVIS SPEECH             -----
VISUAL          *----*--*---------*
MOTION          ^    ^  ^         ^
CUES            A    B  C         D
```

A score item can include:

- scene/section;
- presenter: user | jarvis | none;
- speech text or intent notes;
- cue predicate/reference;
- bound visual/motion action IDs;
- target duration;
- timing policy: soft | locked;
- allowed interruption/recovery behavior;
- next state.

Explicit silence is a first-class state.

## 9. Cue arming and ambient safety

At playback start, the runtime arms only the next finite set of eligible cues. Ambient transcript is matched against those cues. A successful match emits a typed `score.cue_satisfied` event carrying the known cue ID. The action executor resolves the pre-authored bound action from canonical score state.

Ambient text itself must never be converted into an arbitrary tool request.

## 10. Playback Runtime

State machine should track at minimum:

- playback role: user_presenter | jarvis_presenter | rehearsal;
- active scene;
- active score item / cue set;
- revealed elements / deterministic sequence position where needed;
- paused / detour / resuming state;
- auxiliary resource display stack;
- currently speaking actor;
- locked-sequence ownership.

It should be possible to ask "where are we?" and obtain a useful, bounded answer without replaying the whole presentation.

## 11. Variant graph

Presentation variants form a rooted DAG/tree for ordinary use. Each node needs:

- stable machine ID;
- immutable monotonic short display number;
- human title;
- parent/source IDs;
- creation rationale;
- optional provenance links for cross-branch composition;
- preview/thumbnail handle;
- creation metadata;
- deletion/archive state.

A branch deletion operation may remove a node and descendants only through the existing destructive-action policy/confirmation boundary.

## 12. Scene-local variants

Each logical scene may have a lightweight local variant set with its own labels/preview and selected variant. Scene variants remain inside the presentation variant unless explicitly promoted or used to create a top-level presentation variant.

## 13. Variant Explorer / comparison

A dedicated fullscreen UI consumes the graph model. It must support:

- tree navigation;
- preview of selected branch;
- slide/scene browsing inside preview;
- select as active;
- branch/delete/rename operations;
- compare two or four variants;
- focused 50/50 comparison;
- synchronized logical-scene navigation where mapping exists.

## 14. Selective composition

Composition is semantic, not textual merge. Jarvis creates a new child variant by explicitly sourcing dimensions from retained variants, for example:

- narrative from `#29`;
- DA from `#37`;
- scene 6 motion from `#41`.

Provenance should remain inspectable and source variants untouched.

## 15. Authoring planner

The authoring planner decides which workflow is active:

- one-shot information display;
- directed/serious presentation;
- exploratory creative directions.

Before asking questions it should inspect available project references through existing agent/tool capabilities. It should ask only questions whose answers materially change narrative, DA, audience/purpose, evidence or output constraints.

For directed work, the first build should include the score and DA, not append them later.

## 16. Tool Brain / agent boundary

If the repository exposes the Tool Brain contract, presentation runtime emits semantic intents and consumes its concrete UI decisions. If it does not, expose semantic presentation operations through the canonical scene/agent tool surface without creating a second scheduler.

Agent operations should reference stable IDs and constrained choices from current state wherever possible.
