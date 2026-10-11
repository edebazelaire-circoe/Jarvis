# Slice 02: UI inventory for Human sign-off (HV-RFX-02-01)

The normative contract is `docs/presentation-studio.md` › *Presentation experience contract (Level 2, 2026-10)*. This page is a non-clickable picture of it, for review. It changes nothing by itself: if the Human disagrees, the contract is amended first.

## 1. Two names

| The user sees | It is | Never called |
| --- | --- | --- |
| **Remotion Studio** | the native Remotion editor, opened on one scene in its own tab, after the « hors du bac à sable » confirmation | « Studio » alone |
| **Variantes** | the Jarvis screen: variant history, the only video player, branch / activate / compare / rename / archive | « Studio », « Explorateur » in a button label |

Rail menu (the wording only; the rail **layout** waits for your sketch):
- « Ouvrir les variantes »
- « Remotion Studio… »
- « Présenter »
- « Masquer / Afficher »
- « Renommer… »
- « Supprimer… »

## 2. Target Variants screen (windowed)

```
+-- Variantes -- <titre de la présentation> · 3 variantes -------- [Fenêtré] [Plein écran] [Fermer] --+
| ÉVOLUTION            1/64 |  +-------------------------------------------------------------------+  |
| #1 Diaporama ...   ACTIF  |  |                                                                   |  |
|   `- #2 Variante ...      |  |              STAGE  (the one Remotion Player)                     |  |
|   `- #3 Variante ...      |  |              no bar inside, no second transport                   |  |
|                           |  |                                                                   |  |
|                           |  +-------------------------------------------------------------------+  |
|                           |  [|<] [ > Lire ] [>|]  ===o====|=====|=====|=====|====  0:12 / 1:30  [Son] [...] |
|                           |  Scène 6 sur 9 · Mode Présentation : slides...   [Remotion Studio] [Présenter v] |
|                           |  [01][02][03][04][05][*06*][07][08][09]      (click = start of that scene)  |
| > Archivées (0)           |  #1 Titre · Issue de ... · Créée hier par Jarvis · 9 scènes                 |
|                           |  (Variante active) (Partition liée) (DA ■■■■)   note                        |
|                           |  [Activer] [Brancher d'ici…] [Renommer…] [Archiver…]   [Comparer]           |
+-----------------------------------------------------------------------------------------------------+
  [...] overflow  = Lire seulement cette scène · Revenir au début · Raccourcis clavier (?)
  [Présenter v]   = Vous présentez · Jarvis présente · Répétition
  At the end:  [ > Lire ] becomes [ ↺ Rejouer ]; the last image stays on screen.
```

During a presenter run (windowed), a **presenter strip** replaces the scene line:

```
  Vous présentez · En cours   Scène 3/9 · élément 5/16   Ensuite : « ... »   Suivi vocal indisponible (...)
  Élément 0:10 (cible 0:15, temps de partition)                    [Sortir de la séquence (S)] [Arrêter]
```

In fullscreen (« Plein écran » or `F`), only the stage shows, with a transport overlay that hides itself. The tree, the metadata and the actions stay out of fullscreen.

## 3. Controls, once each

| Control | Key | Note |
| --- | --- | --- |
| Lire / Pause / Rejouer | `Space` | continuous video, authored durations, holds the final image |
| Scène précédente / suivante | `←` `→` `PageUp` `PageDown` | goes to the first frame of that scene |
| Global scrub (ticks at scenes) | slider keys | moves the Player, the strip, the title and the time together |
| Time `0:12 / 1:30` | (none) | the whole presentation's time, the only time readout |
| Son | `M` | muted at opening |
| Plein écran (header) | `F` | the only fullscreen; needs your click (voice only arms it) |
| Fermer | `Échap` | nested: menu, dialog, fullscreen, then the screen |
| Présenter ▾ | (none) | presenter run in this screen; never a floating window |
| Remotion Studio | (none) | opens the scene on screen in the native editor |
| ⋯ | `?` (sheet) | Lire seulement cette scène · Revenir au début · Raccourcis |
| scene strip | arrows | click = start of the scene |
| tree, Activer / Brancher / Renommer / Archiver / Restaurer, Comparer | `A` `N` `F2` `Suppr` `R` `Maj+C`, `[` `]` | unchanged |

**Removed:**
- the floating STUDIO_STAGE window and the bottom band (screenshot 1);
- the bar inside the image (« Lecture », its scrub, `x s / 30 s`);
- the separate ‹ › above the strip;
- « Jouer cette slide » and « Tout jouer » as buttons;
- the variant chip bar (the tree does it);
- the window host opened by the rail.

**Forbidden:**
- « 8 s par slide », or any time-per-slide setting, for video;
- a second transport row;
- loop / repeat;
- a second fullscreen button;
- any button that closes the screen in order to play.

## 4. Points to confirm (agent 0 chose; you may overturn)

1. **Fullscreen shows the stage only**, not the whole Variants screen (today the whole explorer goes fullscreen).
2. **« Jouer cette slide » survives only in the ⋯ menu**, as « Lire seulement cette scène ».
3. **`Échap` no longer pauses** a presentation; `Space` does. `Échap` leaves fullscreen, then closes.
4. **The variant chip bar is merged into the tree.**
5. **External screen:** move the window to the projector, then « Plein écran ». No separate presenter view with notes on the laptop in this task.
6. **Screenshot 2's lower row** (« 8 s par slide », loop, `2 s / 8 s`) is not in the repository. It comes from unpushed work on another machine. Recommendation: discard it.
7. **Detours** (auxiliary scenes) appear **inside** Variants. The rail shows only an indicator while an agent works; nothing opens by itself.
