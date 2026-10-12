# Slice 10 — Variants control audit

Base `33015379` (Slices 00–09). Grounded in screenshot 2 (`../../evidence/02-variants-screen-base.png`, the visual base kept), the live
DOM read in headless Chrome on the base (`evidence/before-33015379-inventory.json`: every visible control with its name, state, effective
opacity, inertness and box, at 800×600, 1280×720, 1920×1080 and during a run) and the code. Contract: `docs/presentation-studio.md` § 6
(target inventory), § 4.15, § 4.16, PX-1, PX-11, PX-12, PX-17, and the Slice 02 inventory (`../02-product-experience-contract/UI-INVENTORY.md`).
Line numbers are the explorer's at the Slice 10 code commit (`control_center_presentation_studio_explorer.js` = `explorer.js`).

**Kinds.** *Primary*: what a viewer of the video reaches first (play, position, fullscreen). *Secondary*: authoring, graph, help, status.
*Obsolete*: gone, or forbidden.

## 1. Screenshot 2 against the code on the base

Screenshot 2 was taken on another machine. Its lower row (`|◀ ◀◀ ▶ ▶▶ ▶|`, `6/9 · 2 s / 8 s`, « 8 s par slide », loop, a second
fullscreen, the hint « → suivante · ← début … »), the inner bar `rs-bar` (« Lecture », `x s / 30 s`), the ‹ › above the strip and
« Jouer cette slide » / « Tout jouer » are not in the code on the base (Slices 01, 06, 09 removed or never had them): the base DOM has none
of them at any size (`before-…-inventory.json`, `rsBars: 0`, `forbidden: []`). What screenshot 2 still shows, the base still had:

| Seen on the base | Problem | Decision |
| --- | --- | --- |
| the transport row also carried the scene title, « Scène n sur N » and « Présenter » | the slider got **64 px** at 1280×720 and 59 px at 800×600 (`before-…-inventory.json`): the one scrub was the smallest control of the row | two rows (Slice 02 inventory § 2): transport alone, then the scene row |
| during a run the actions were `aria-disabled` at 0.5 opacity, exactly like « Activer » on the active variant when idle; the tree was inert at full opacity | inert controls that look usable (Slice 09 flag) | `data-run` dims the tree and the actions below the idle-disabled look, the reason under the actions |
| `1/64` chip beside « ÉVOLUTION » | reads like a position (« 1 of 64 ») | « 1 / 64 variantes » |
| the variant bar (hidden with one variant, a row of chips with two or more) | a second place to choose a variant (§ 6 #8) | removed; `[` `]` stay |
| the tree hint line | a second key list, partial (§ 6 #6) | the keyboard sheet; the line only says « Touche ? : raccourcis clavier » |
| no `?` sheet, no « Raccourcis clavier » in « ⋯ » | § 4.15 / § 6 #20 promised it | added |
| at ≤ 820 px wide the « Plein écran » label hides and the button had no name (`aria-label` absent) | PX-17 | `aria-label` follows the label |
| « Fermer l'explorateur de variantes », « l'explorateur reste ouvert … » | PX-1 | « Fermer Variantes », « Variantes reste ouvert … » |

## 2. Per control

| # (§ 6) | Control / panel | Kind | Owner (file:line) | Decision |
| --- | --- | --- | --- | --- |
| 1 | title « Variantes », subtitle (presentation, counts) | secondary (status) | `explorer.js:298-299` | keep |
| 2 | mode chip « Fenêtré » / « Plein écran » | secondary (status) | `explorer.js:303`, `renderHeader` | keep |
| 3 | header « Plein écran » / « Quitter le plein écran » (`F`) | **primary**, the one fullscreen | `explorer.js:304`, name in `renderHeader` | keep; `aria-label` added (name at every width) |
| 4 | « Fermer » (`Échap`, nested) | secondary | `explorer.js:307` | keep; name « Fermer Variantes » (PX-1) |
| — | notice (floating message) | secondary (status) | `explorer.js:310` | keep |
| 5 | « ÉVOLUTION » and its count | secondary (authoring metadata) | `explorer.js:322`, `renderHeader` | keep; « n / 64 variantes » |
| — | chip « Présentation en cours » (run) | secondary (status) | `explorer.js:325` | keep (not dimmed: it is the reason) |
| — | « Comparer » bar (marked variants, `Maj+C`) | secondary (graph) | `explorer_compare.js:56` `buildBar` | keep |
| 5 | tree (select, fold, menu, `A` `N` `F2` `Suppr` `R` `C`, type-ahead) | secondary (graph) | `explorer.js:327` | keep; dimmed and inert during a run |
| 6 | tree hint « ↑ ↓ → ← parcourir · … » | obsolete | `explorer.js:343` (was) | **merged** into the keyboard sheet; one text line points to `?` |
| 7 | « Archivées (n) » | secondary (graph) | `explorer.js:333` | keep |
| 8 | variant bar (chips above the preview) | obsolete | `renderVariantBar` (was) | **removed**; `[` `]` (`liveNodes`, `stepVariant`, `explorer.js:498-502`) stay |
| 9 | stage (the Variants Player) | **primary** | `explorer.js:349` | keep |
| — | failure veil (« Réessayer », « Scène suivante »), wait pill « Chargement de la scène n sur N · s », sound pill | primary (state of the video) | `explorer.js:353`, `358`, `362` | keep (labelled readouts) |
| 10 | inner bar `rs-bar` | obsolete | (gone since Slice 06) | absent, asserted |
| 11 | scene ‹ › above the strip | obsolete | (gone) | absent; transport ⏮ ⏭ |
| 15 | ▶ « Lire » / « Pause » / « Rejouer » (`Espace`) | **primary** | `explorer.js:711` | keep, once |
| 16 | ⏮ ⏭ « Scène précédente / suivante » (`←` `→`) — « Élément … » in a run | **primary** | `explorer.js:710`, `714` | keep, once |
| 17 | slider « Position dans la vidéo » with scene ticks | **primary** | `explorer.js:715` | keep, once; now gets the row's width |
| 18 | readout `0:12 / 1:14` (composition time `f / L`) | **primary** (readout) | `explorer.js:724`, `renderScrub` `:943` | keep; the only time readout |
| 19 | « Son » (`M`) | primary | `explorer.js:725` | keep |
| 20 | « ⋯ » « Lire seulement cette scène », « Revenir au début », **« Raccourcis clavier »** (run: « Premier / Dernier élément ») | secondary | `explorer.js:727`, `openPlaybackMenu :841` | « Raccourcis clavier » added |
| — | keyboard sheet (`?`) | secondary (help) | `openShortcuts :869`; rows `stage_media.js` `shortcutRows`; tree keys `explorer_core.js` `TREE_SHORTCUTS` | **added**, derived from the one key map |
| 12 | « Scène n sur N », scene title, role, local-variant badge | secondary (where the video is) | `explorer.js:370-375` | moved to its own row under the transport; hidden in a run (the presenter strip says it) |
| 21 | « Présenter ▾ » (Vous / Jarvis / Répétition) | secondary (starts a run) | `explorer.js:729`, `openPresentMenu :1818` | moved out of the playback toolbar to the scene row |
| — | « Arrêter » (run only, also in fullscreen) | primary during a run | `explorer.js:731` | keep, once, in the transport |
| — | presenter strip (role, phase, scene/item, next, voice, « Partition » score time, « Sortir de la séquence ») | secondary (run status) | `buildPresenter`, `explorer.js:1770-1795` | keep; its score time is labelled « Partition » (the § 6 exception) |
| 23 | scene strip `01 … 09` (listbox) | primary (navigation) | `explorer.js:381` | keep; highlight follows `f` |
| 24 | metadata (`#n`, title, parent, date, scenes, chips, palette, note) | secondary (authoring metadata) | `explorer.js:384` | keep |
| 25 | « Activer », « Brancher d'ici… », « Renommer… », « Archiver… » (« Restaurer ») | secondary (graph) | `explorer.js:385`, `actionModel :546` | keep, separate from playback; **dimmed** + reason (`ui.runNote`, `:387`) during a run, never removed |
| 27 | newer-version notice, « Essayer dans une nouvelle variante » | secondary | `explorer.js:390` (`explorer_upgrades.js:83`) | keep; dimmed in a run |
| 22 | « Remotion Studio » | — | — | Slice 11 |
| 28 | lower row of screenshot 2 (dwell « 8 s par slide », loop, second fullscreen, `6/9 · 2 s / 8 s`) | obsolete, forbidden | not in the repository | absent, asserted at three sizes |
| 13, 14 | « Tout jouer », « Jouer cette slide » | obsolete | (gone since Slice 06/09) | absent, asserted; « Lire seulement cette scène » in « ⋯ » |

## 3. Readouts (SLICE step 6)

| Readout | Source | Verdict |
| --- | --- | --- |
| `0:12 / 1:14` (transport) | the sequencer's `f` over `L`; in a run the run Player's frame through the composition-clock map | canonical Player time |
| slider `aria-valuetext` « Scène 3 sur 9, 0:12 sur 1:14 » | same `f` | canonical |
| « Scène n sur N » (scene row) | the scene the sequencer shows (follows `f`) | canonical position |
| « Partition 00:02 / 00:08 » (presenter strip) | the run's item time | score time, labelled « Partition », titled « … jamais le temps de la vidéo » |
| « Chargement de la scène n sur N · s » | wait counter | labelled wait (RULE ZERO) |
| « Relecture… 3 s » (header busy) | operation counter | labelled |
| « n / 64 variantes » | the graph | authoring metadata, labelled |
| « à l'instant · système · 9 scènes », « Créée … par … », « 9 scènes » | the graph / variant | authoring metadata |

No other number pair or duration is drawn in Variants (real-Chrome scan `READOUT_SCAN`, idle and in a run).

## 4. Decisions

- **Two rows under the stage** instead of one — *decided by agent 0's Work Agent* (closest to the Slice 02 inventory drawing, § 2, and to
  SLICE step 2): the one-row layout of Slice 06 gave the slider 60 px. Cost: one row (about 38 px); on short windows paid back by tighter
  gaps (the stage keeps ≥ 300 px at 800×600, an existing test).
- **« Présenter » leaves the playback toolbar** for the scene row — *decided by agent 0's Work Agent*: it starts a run, it does not play
  the video; the toolbar now holds playback controls only. « Arrêter » stays in the toolbar (it must remain reachable in the fullscreen).
- **Dim, never remove** the graph actions during a run — *decided by agent 0's Work Agent*: SLICE acceptance « all original variant graph
  actions remain available »; the hand finds them where it expects them, and a line says why they wait.
- **Tree hint → one text line pointing to `?`** rather than deleting it outright — *decided by agent 0's Work Agent*: keeps
  discoverability without a second control (§ 6 « each control once »).
- **PX-1 wording** fixed on the Variants surface, the inspector's door and the page refusals relayed by MCP; code identifiers
  (`explorer_*`) keep their names.
- Left rail geometry untouched (agent 0); Workspace Task Type waived (agent 0); no schema change.
