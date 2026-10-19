# 06 — UI / visual specification

This file carries the design detail that must survive implementation. It is intentionally more prescriptive about **visual hierarchy and removals** than a typical backend handoff because this task is principally an UI refactor.

## A. Main Board shell — resting state

The default scene should feel calmer than `assets/current-ui-before.png`.

### Left edge

Only the wheel's subtle edge anchor / hub affordance is visible when closed. It may retain a small Jarvis luminous cue but should not occupy a tall toolbar while closed.

### Bottom-left Board card

Compact dark-glass card, approximately one or two text rows:

```text
[ type icon ]  PRÉSENTATION
               Présentation Jarvis      ▴
```

or equivalent hierarchy.

Requirements:

- type is a short uppercase/small-cap label + distinct icon/accent;
- Board title is the primary readable text;
- click opens Board switcher/create flow;
- type is not editable in the normal “edit Board” flow;
- active state comes from canonical Board status, not local click state;
- when switching takes time, the card can show a bounded progress/substatus without becoming a permanent status panel.

Suggested type visuals (exact colours may use current design tokens):

- Assistant: cyan/blue;
- Présentation: magenta/violet accent;
- Réunion: warm amber/green variant if it remains distinguishable and accessible.

Do not rely on colour alone; use icons/labels.

### Top-left

No ordinary Board selector. No persistent “VOICE SLEEP / CLAUDE RUNNING” badge. Critical errors or active capture cues may transiently use this area.

### Hidden objects

No permanent hidden count/pill. A count may be shown inside a contextual submenu, e.g. `Afficher les masqués (52)`, only when the user opens the relevant management action.

## B. Orbital wheel — visual target

Reference: `assets/style-reference-radial-ui.png`.

### Geometry

- anchored to the left viewport edge;
- large semi-circular/layered arc, not a conventional rectangle menu;
- primary categories arranged along one clear radial band;
- selected primary category expands/opens one adjacent second radial band/curved glass surface toward the workspace;
- submenu should read as geometrically connected to its parent sector;
- selected submenu must never overlap a second category's submenu because only one is mounted/visible.

Preserve enough of current wheel geometry/input math to avoid unnecessary regression, but **the visual silhouette should visibly change** from the current four equal icon wedges.

### Styling

- background: near-black / deep navy translucent glass;
- borders: thin cyan/blue-grey strokes, low alpha when inactive;
- selected sector: brighter cyan contour + restrained inner fill + small soft outer halo;
- other categories: quieter, readable icon + label, no competing glow;
- secondary categories may use restrained semantic accent colours but not rainbow decoration;
- typography: current Jarvis mono/geometric language; small uppercase section labels + human-readable action labels;
- icons: consistent 24px-ish line icon family, 1.5–1.8 stroke, round caps/joins;
- micro-grids/ticks/rings allowed as texture only, not interactive-looking noise;
- animation: short radial reveal/fade/translation, ~120–180ms current shell token range; reduced-motion becomes near-instant/fade-only.

### Primary wheel order

Top-to-bottom / clockwise should be stable:

1. JARVIS
2. Sélection
3. Dossier
4. Capture
5. Paramètres

No `Boards`, `Fichiers`, `Recherche`, `Outils`, `Vidéo`, `Screenshot`, `Audio` as primary sectors.

## C. JARVIS submenu

Purpose: answer “how is Jarvis behaving / what can I manually control?”.

Show only canonical runtime facts/actions. Planning examples:

- Voice/listening state;
- sleep / wake if a canonical lifecycle gate exists;
- model/brain runtime state as status-only if it is not user-switchable;
- manual focus/thinking/autonomy control only if current product contract exposes one — do not invent it from the concept image.

Visual rows should distinguish:

- action;
- selected/current state;
- status-only telemetry;
- unavailable/refused/unknown.

The submenu vanishes/replaces when another primary category is selected.

## D. Sélection submenu

First level can retain current selection input choices such as Mouse / Bare Hands if still canonical. Once scene objects are selected, contextual operations become available:

- Ranger dans le Dossier (eligible content only);
- Masquer;
- Afficher / Afficher les masqués;
- Réduire / capsule;
- Étoile / point;
- Fenêtre;
- Retirer du Board / Archiver la représentation;
- destructive content delete only where a durable source is actually selected and after explicit confirmation.

Do not label a non-destructive scene archive as “Supprimer le document”.

## E. Capture submenu + transient HUD

Second-level actions:

- Capture d'écran;
- Enregistrer l'écran / vidéo;
- Enregistrer l'audio;
- target/device selection only from Core-advertised targets.

### While recording

Screen/video:

```text
● REC  00:12:34   [Stop]
```

Small, red, top-left safe area or adjacent non-overlapping top region. It appears only when Core reports an open recording.

Audio:

- small animated orb/wave/microphone cue;
- duration + Stop available on focus/click/keyboard;
- may coexist with video REC indicator.

Do not show a fake Pause action if CaptureService has no canonical pause state/API.

Screenshot is a momentary action: use existing preview/toast behavior if useful, not a permanent “capture active” indicator.

## F. Paramètres

Wheel action opens the canonical settings surface. If another permanent Settings button exists solely for the same destination, evaluate removal to avoid duplicate entry points; do not remove distinct global diagnostics/functions under the guise of “cleanup”.

## G. Dossier full-screen surface

Dossier is a **full working interface**, not a popover.

Suggested large-screen layout:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ DOSSIER · [Board type] Board title                Search     View     Close │
├───────────────┬───────────────────────────────────────────┬─────────────────┤
│ ORGANISATION  │ WORKSPACE / VIEWER                        │ CONTEXTE        │
│               │                                           │ (collapsible)   │
│ Overview      │ document / image / PDF / media            │ summary         │
│ Synthèses     │ one or several tabs/panes                 │ provenance      │
│ Rapports      │ compare / annotate / edit                 │ linked tasks    │
│ Décisions     │                                           │ Jarvis actions  │
│ Ressources    │                                           │                 │
│ Médias        │                                           │                 │
│ ... folders   │                                           │                 │
├───────────────┴───────────────────────────────────────────┴─────────────────┤
│ Ask Jarvis / voice cue / selected-document actions                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Left: organization

- folder/collection tree built from Board memory and supported Dossier entries;
- recent/important sections if useful;
- counts subtle, not dominant;
- internal search/filter;
- drag/drop/reorder only if backed by canonical move operations and within scope.

### Centre: viewer/workspace

- comfortable reading area;
- document text with real typography, not monospace debug dump;
- image/media/PDF viewers using existing safe preview routes where possible;
- tabs/panes for multiple opened items;
- compare two/three sources side-by-side when space allows;
- actions: edit/annotate where supported, `Afficher sur le Board`, change representation, close/ranger.

### Right: context (collapsible)

Default collapsed or narrow enough not to harm reading. Shows understandable metadata:

- concise summary;
- source / last modified;
- linked Board work/tasks/artifacts;
- provenance;
- “used by Jarvis / relevant to context” only if the backend can truthfully expose it.

Advanced section may expose raw IDs, agent memory/log notes and diagnostics. Never make that the default user view.

### Jarvis-assisted navigation

Voice/chat commands should visibly move/open the same UI rather than answering only in text when the user's intent is to inspect material. Manual navigation remains fully available.

### Responsive

At narrower sizes:

- organization can become a slide-in drawer;
- context panel collapses;
- centre viewer remains priority;
- multi-pane compare falls back to tabs/stack;
- full-screen Dossier must remain keyboard escapable and focus-safe.

## H. Visual anti-goals

- No two expanded category panels simultaneously.
- No generic rectangular settings dashboard pasted over the wheel as the primary visual solution.
- No excessive glow that reduces text contrast.
- No decorative “Iron Man” rings unrelated to controls.
- No primary `Recherche`, `Outils` or `Boards` categories.
- No raw debug tree as the Dossier home screen.
- No duplicate Board/mode selectors in different corners.
- No permanent capture controls when nothing is recording.
