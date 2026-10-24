"""Outillage de capture visuelle des Réglages (refonte-ui-settings, Slice 01).

Contrat : `docs/settings/visual-foundation.md` § « Fixtures et captures ». Ce module n'est pas un test : il
fournit aux tests navigateur des Slices 02 à 07 les mêmes fenêtres, les mêmes chemins d'ouverture et la même façon
de figer une page avant de la photographier. Il s'appuie sur le harnais CDP partagé
(`_wake_word_settings_browser.mjs`, via `drive` de `test_wake_word_settings_browser.py`) ; il n'en crée pas un second.

- `VIEWPORTS` : les deux fenêtres des maquettes (`wide` 1672×941 pour 01-03, `square` 1254×1254 pour 04-05) et une
  plus étroite (`narrow` 1280×800). `zoomed()` donne la fenêtre CSS d'une taille à 125 % de zoom.
- `VIEWS` : comment ouvrir chaque vue cible (hub, Personnalisation, Sous-agents, Architecture, Mémoire, Memory
  Center) depuis la page servie par la fixture `served`.
- `stub()` : une réponse JSON déterministe pour une route de la page (étape `stubs` du harnais), sans toucher le
  serveur ni coder une donnée de maquette dans un composant.
- `capture_steps()` : un plan qui ouvre une vue, la fige (`freeze`) et la photographie à chaque fenêtre demandée,
  avec la mesure de débordement horizontal `OVERFLOW`.

Les images vont dans `JARVIS_BROWSER_SHOTS` quand la variable est posée (preuves gardées), sinon dans le dossier
temporaire du test.
"""

from __future__ import annotations

import os
from pathlib import Path

from tests.unit.test_wake_word_settings_browser import click, eval_, open_settings, wait

#: Fenêtres de référence : nom → (largeur, hauteur) en pixels CSS.
VIEWPORTS: dict[str, tuple[int, int]] = {"wide": (1672, 941), "square": (1254, 1254), "narrow": (1280, 800)}

#: Fenêtre de référence de chaque vue cible (maquettes `tasks/refonte-ui-settings/references/ui/`).
REFERENCE_VIEWPORT: dict[str, str] = {"hub": "wide", "perso": "wide", "subagents": "wide", "architecture": "wide",
                                      "memory": "square", "memory_center": "square"}


def zoomed(size: tuple[int, int], zoom: float = 1.25) -> tuple[int, int]:
    """La fenêtre CSS d'une taille physique vue à `zoom` (125 % : 1672×941 → 1338×753)."""

    return round(size[0] / zoom), round(size[1] / zoom)


def shots_dir(tmp_path: Path, slug: str = "") -> Path:
    """`JARVIS_BROWSER_SHOTS[/slug]` quand la variable est posée, sinon le dossier temporaire du test."""

    base = os.environ.get("JARVIS_BROWSER_SHOTS")
    target = (Path(base) / slug if slug else Path(base)) if base else tmp_path
    target.mkdir(parents=True, exist_ok=True)
    return target


def stub(path: str, json: object, *, method: str = "GET", status: int = 200) -> dict:
    """Une réponse déterministe pour `path` (chemin sans requête). À passer dans `capture_steps(stubs=...)`."""

    return {"path": path, "method": method, "status": status, "json": json}


def freeze() -> dict:
    """Animations à leur état final, transitions et caret coupés : deux captures du même état sont identiques."""

    return {"a": "freeze"}


def shot(path: Path | str) -> dict:
    """Capture de la fenêtre ; une extension `.jpg` donne un JPEG (preuves plus légères)."""

    return {"a": "shot", "path": str(path)}


#: Débordement horizontal de la page et de chaque conteneur visible des Réglages (en pixels, 0 = aucun).
OVERFLOW = """(()=>{const over=e=>e?Math.max(0,e.scrollWidth-e.clientWidth):0;
  const roots=['#settingsHub','#settingsPerso','#settingsShell','#settingsMain','#modalContent','#memoryCenterMount']
    .map(s=>document.querySelector(s)).filter(e=>e&&e.getClientRects().length&&getComputedStyle(e).display!=='none');
  return {page:Math.max(0,document.documentElement.scrollWidth-innerWidth),
    containers:Object.fromEntries(roots.map(e=>[e.id,over(e)]))}})()"""

_HUB = [wait("!!document.getElementById('openSettings')"), click("#dockMore"), click("#openSettings"),
        wait("!!document.querySelector('#settingsHubGrid [data-hub-category]')")]
_SHELL = [wait("!!document.getElementById('openSettings')"), click("#dockMore"), *open_settings(),
          wait("!!document.getElementById('voiceSection_conversation')")]

#: Ouverture de chaque vue cible, à partir de la page fraîchement chargée.
VIEWS: dict[str, list[dict]] = {
    "hub": _HUB,
    "perso": [*_HUB, click("#settingsHubGrid [data-hub-category=voice_audio]"),
              wait("!!document.querySelector('#persoGrid .perso-persona')", 10000)],
    "subagents": [*_SHELL, eval_("(selectTab('subagents'),1)"),
                  wait("!!document.querySelector('[data-subagent-settings-host]')", 15000),
                  # Capture stable : la politique des rôles est lue (plus de « Lecture de la politique… »).
                  wait("!/Lecture de la politique/.test(document.querySelector('[data-subagent-settings-host]').textContent)", 15000)],
    "architecture": [*_SHELL, eval_("(selectTab('architecture'),1)"),
                     wait("!!document.querySelector('[data-architecture-page] [data-arch-node=core]')", 15000)],
    "memory": [*_SHELL, click("#settingsCategories [data-category=memory_knowledge]"),
               wait("!!document.querySelector('#memSection_recall [data-mem]')", 10000)],
    "memory_center": [*_SHELL, click("#settingsCategories [data-category=memory_knowledge]"),
                      click("#modalTabs [data-section=memory_center]"),
                      wait("!!document.querySelector('[data-mem-center]:not([disabled])')", 10000),
                      click("[data-mem-center]"),
                      wait("document.getElementById('workspaceManager').classList.contains('mc-on')", 10000)],
}


def capture_steps(open_actions: list[dict], shots: Path, name: str, *, viewports: list[str] | None = None,
                  zoom: float | None = None, stubs: list[dict] | None = None, settle_ms: int = 600,
                  ext: str = "png", extra: list[dict] | None = None) -> list[dict]:
    """Un plan du harnais : pour chaque fenêtre, ouvrir, attendre `settle_ms`, figer, mesurer, photographier.

    Le fichier s'appelle `<name>-<largeur>x<hauteur>[-z125].<ext>` ; la mesure de débordement est l'action `overflow`
    de chaque étape, `extra` des actions ajoutées juste avant la capture (une mesure propre à la page).
    """

    steps = []
    for view in viewports or list(VIEWPORTS):
        width, height = zoomed(VIEWPORTS[view], zoom) if zoom else VIEWPORTS[view]
        suffix = f"-z{round(zoom * 100)}" if zoom else ""
        steps.append({"width": width, "height": height, **({"stubs": stubs} if stubs else {}), "actions": [
            *open_actions,
            eval_(f"new Promise(r=>setTimeout(()=>r(1),{int(settle_ms)}))"),
            freeze(), *(extra or []), eval_(OVERFLOW, "overflow"),
            shot(shots / f"{name}-{width}x{height}{suffix}.{ext}"),
        ]})
    return steps
