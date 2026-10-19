# 02 — Target architecture

## 1. Product state

```text
BoardService / Board store
  Board
    id
    title
    type/kind: assistant | presentation | meeting   <-- authoritative product type
    status
    context summary / refs / memory root
    ...

          switch active Board
                 |
                 v
       Board behavior resolver
          assistant -> assistant policy
          presentation -> presentation policy
          meeting -> meeting capability if available,
                     otherwise explicit safe/planned fallback
                 |
                 v
       Core / Voice / UI projections
```

There must be no ordinary flow where the user is on Board A and independently picks a different product mode for Board A.

If `InteractionModeService` remains temporarily because Presentation runtime code consumes it, it becomes a **derived implementation seam** driven by Board activation/type, not a separate stored user preference.

## 2. Shell ownership

```text
left edge       -> orbital tool wheel
bottom-left     -> active Board switcher card
centre          -> scene / Board
right           -> existing active workspace rail
full workspace  -> Dossier overlay/surface when opened
transient HUD   -> recording/error/safety cues only while relevant
```

Do not create a second Board picker or second Settings launcher while migrating controls. If an existing top-right Settings route remains canonical, the wheel's Paramètres entry should open that same surface and redundant permanent entry should be removed only if doing so does not hide unrelated critical controls.

## 3. Wheel

The wheel surface is still a reusable controller. Its primary slots change to product categories:

```text
JARVIS
  -> status/actions supported by canonical runtime owner

SÉLECTION
  -> input selection mode (Mouse / Bare Hands where relevant)
  -> selected-object / scene operations

DOSSIER
  -> open Dossier
  -> ranger selected content when eligible
  -> recent/relevant documentary shortcuts (optional, contextual)

CAPTURE
  -> screenshot
  -> screen/video recording
  -> audio recording
  -> target/device submenu from Core capability data

PARAMÈTRES
  -> open existing canonical settings surface
```

Only one submenu tree may be open at a time. The existing reducer/sub-arc mechanics may be reused, but the graphics and primary-slot model must be redesigned.

## 4. Dossier data model: projection, not duplicate database

Existing canonical pieces at planning time:

- Board memory: free-form files under the Board's memory root, with `summary.md` convention.
- Artifact registry: durable media/derived payloads + provenance, linked to Boards.
- Scene: active visual representations with visibility and archive history.
- SessionContext: session-scoped cognitive workspace, explicitly separate from Board memory.

Target:

```text
DossierEntry (projection/view model)
  id / stable locator
  board_id
  title
  kind: document | note | report | image | media | resource | memory_summary | ...
  source:
    board_memory_path | artifact_id | presentation/source ref | supported existing source
  provenance
  human_status: draft | validated | provisional (only if a canonical status exists)
  modified_at
  preview/open capability
```

Do not persist a second copy of the underlying content just to make it appear in Dossier.

### Human vs advanced agent view

Default view shows curated content and understandable metadata. Advanced view can expose:

- provenance;
- linked task/work references;
- Jarvis-generated summaries;
- agent-maintained memory/log material;
- raw IDs only when useful for diagnosis.

The existing technical Workspace manager can remain for deep debugging. Dossier is a separate user-facing projection and may reuse its data clients/routes where appropriate.

## 5. Semantic operations

### `Masquer`

- input: scene selection
- operation: canonical `visibility = hidden`
- persistent content: unchanged
- Dossier: unchanged
- recoverable by contextual “Afficher masqués”.

### `Réduire` / `Étoile`

- input: scene selection
- operation: canonical representation update (`point` / `capsule` / `window` vocabulary at current HEAD)
- content: unchanged.

### `Retirer du Board`

- input: scene representation(s)
- operation: archive/remove representation from active scene using canonical archive semantics
- durable source: unchanged if one exists.

### `Ranger`

Transactional intent, even if implemented as explicit steps with compensation:

1. Resolve selected scene objects.
2. For each eligible object, identify durable backing (Board-memory document, linked Artifact, supported source).
3. If no durable backing exists but the object contains user/Jarvis content worth preserving, materialize it once into an appropriate canonical Board-memory/Artifact representation with provenance.
4. Ensure the durable item is associated with the active Board and appears in Dossier.
5. Only after durability is confirmed, archive/remove the scene representation.
6. Return per-item result/refusal; do not silently discard unsupported work nodes.

No “ranger” operation may destroy the only copy of content.

### `Afficher sur le Board`

1. Resolve Dossier entry.
2. Create/reuse a scene representation that references the same durable source.
3. Choose requested representation (window/capsule/point) and layout.
4. Underlying content stays single-source.

## 6. Voice/agent integration

The human must be able to say things such as:

- “Montre-moi le rapport de la dernière réunion.”
- “Ouvre les trois documents qui expliquent cette décision.”
- “Range ça dans le Dossier.”
- “Sors ces deux documents sur le Board.”
- “Qu'est-ce qui a changé dans le Dossier ?”

Agent/tool routing must call the same semantic Dossier/scene services as manual UI. Do not implement a second path that writes arbitrary files or bypasses scene authority.

Because these commands affect agent-visible context, Slice 05/07/08 require `agent-trace-analysis` in addition to runtime validation.

## 7. Layering / shell contract

Any moved/new surface must update `docs/control-center-shell.md`, the layer registry mirror in `control_center.html`, `JarvisShell.ZONES`/tokens where applicable, and conformance/browser tests in the same Slice.

The Dossier full-screen surface must define focus trapping/escape/back behaviour and must not accidentally leave the scene interactable underneath when modal/full-screen.
