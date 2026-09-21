# -*- coding: utf-8 -*-
"""Les docs decrivent desormais Reglages > Apparence, plus le bouton flottant."""
from pathlib import Path

BASE = Path(r"D:\Projects\CIRCOE\Jarvis")


def sub(path, old, new):
    p = BASE / path
    s = p.read_text(encoding="utf-8")
    assert s.count(old) == 1, (path, s.count(old), old[:80])
    p.write_text(s.replace(old, new), encoding="utf-8")
    print("ok", path)


sub(
    "docs/ARCHITECTURE.md",
    "**Display preferences** (Slice 12, `control_center_scene_view.js`). A 34 px\n"
    "button at the bottom right of the scene (inside the container, so the gate takes\n"
    "it away with everything else) opens a small dialog that tunes how the\n"
    "constellation *looks*, without ever touching the scene: star size, halo size,",
    "**Display preferences** (Slice 12, `control_center_scene_view.js`; moved\n"
    "2026-09-20). A section of **Settings \u203a Appearance**, under the Cosmos version,\n"
    "tunes how the constellation *looks*, without ever touching the scene: star size,\n"
    "halo size,",
)

sub(
    "docs/ARCHITECTURE.md",
    "Slice 12: the settings behind the \u00ab Affichage des \u00e9toiles \u00bb button \u2014 fields,",
    "Slice 12: the settings in the \u00ab \u00c9toiles et orbites \u00bb section of Settings \u203a Appearance \u2014 fields,",
)

sub(
    "docs/scene-model.md",
    "The viewer's own display preferences (star size, halo, gravity, threads \u2014 the\n"
    "\u00ab Affichage des \u00e9toiles \u00bb button, `ARCHITECTURE.md` \u203a *Display preferences*) are",
    "The viewer's own display preferences (star size, halo, gravity, threads \u2014 the\n"
    "\u00ab \u00c9toiles et orbites \u00bb section of Settings \u203a Appearance, `ARCHITECTURE.md` \u203a\n"
    "*Display preferences*) are",
)

sub(
    "docs/OPERATIONS.md",
    "**Affichage des \u00e9toiles** (petit bouton en forme d'\u00e9toile, en bas \u00e0 droite de\n"
    "l'\u00e9cran, d\u00e8s que la sc\u00e8ne est allum\u00e9e). Il ouvre une fen\u00eatre qui r\u00e8gle *comment*\n"
    "la constellation se montre ; chaque changement se voit tout de suite et reste\n"
    "enregistr\u00e9 dans ce navigateur.",
    "**\u00c9toiles et orbites** (**R\u00e9glages \u203a Apparence**, sous la version Cosmos ; avant\n"
    "le 2026-09-20, un petit bouton en forme d'\u00e9toile en bas \u00e0 droite de l'\u00e9cran).\n"
    "Cette section r\u00e8gle *comment* la constellation se montre ; chaque changement se\n"
    "voit tout de suite et reste enregistr\u00e9 dans ce navigateur. Elle est l\u00e0 m\u00eame quand\n"
    "la sc\u00e8ne est \u00e9teinte : c'est un r\u00e9glage d'apparence, pas un interrupteur.",
)

sub(
    "docs/mcp/plan-outils-interface.md",
    "| R\u00e9gler l'affichage des \u00e9toiles : `size`, `halo`, `breathe`, `orbit`, `spread`, `speed`, `links`, et \u00ab R\u00e9initialiser \u00bb | \u2014 (**`localStorage` `jarvis.scene.view`**) | `control_center_scene_view.js:24-44`, `scene_page.js:1090` |",
    "| R\u00e9gler les \u00e9toiles et les orbites (R\u00e9glages \u203a Apparence) : `size`, `halo`, `breathe`, `orbit`, `spread`, `speed`, `links`, et \u00ab R\u00e9initialiser \u00bb | \u2014 (**`localStorage` `jarvis.scene.view`**) | `control_center_scene_view.js:24-44`, `scene_page.js` \u203a `buildViewSection` |",
)
