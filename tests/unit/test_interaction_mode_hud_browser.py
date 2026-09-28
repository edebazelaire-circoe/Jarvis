"""Le contrôle de mode d'interaction, mesuré dans un vrai navigateur.

**Pourquoi ce fichier existe.** Trois défauts de cette Slice ont survécu à des
tests qui lisaient la feuille de style comme du texte : la règle y était,
nommait le bon sélecteur, et la cascade faisait le contraire. Le dernier en date
— le halo qui continuait de respirer sous `prefers-reduced-motion` — perdait par
spécificité contre une règle écrite vingt lignes plus haut, et le test passait
parce que le nom `.im-mark::after` apparaissait bien dans le bloc.

Ici on ne lit rien : on compose la page **telle que `ControlCenter.index` la
sert**, on la charge dans Chrome sans tête, on impose une taille, et on relève
des rectangles et des styles **calculés**. C'est le seul niveau auquel « le
bouton ne recouvre pas la palette » et « le halo s'arrête » veulent dire quelque
chose.

Ce que ce fichier épingle :

- sous 700 px de large, le bouton ne recouvre plus la palette Bare Hands —
  le défaut qui rendait son outil du bas incliquable, puisque le bouton est au
  rang 32 et la palette au rang 30 ;
- à pleine largeur, rien n'a bougé ;
- `prefers-reduced-motion` arrête vraiment le halo, la barre de balayage et les
  transitions.

Le test se saute proprement si Chrome est absent ; il ne se saute pas en
silence si la page ne se compose pas.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

import jarvis.runtime.control_center as cc

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"

#: Chrome, aux emplacements où Windows le pose. Absent, les tests se sautent —
#: mais ils ne mentent pas : rien ici ne « passe » sans navigateur.
CHROME_CANDIDATES = (
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
)


def _chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("chrome") or shutil.which("google-chrome")
    if found:
        return found
    pytest.skip("Chrome absent")


def _served_page(tmp_path: Path) -> Path:
    """La page **servie**, composée comme `ControlCenter.index` la compose.

    `index` est une chaîne de remplacements de marqueurs littéraux : la même
    chaîne sur les mêmes fichiers produit le même document, sans serveur. On
    découvre les paires marqueur/fichier depuis le module lui-même, pour qu'un
    module ajouté plus tard entre ici sans que personne n'y pense.
    """

    page = RUNTIME / "control_center.html"
    html = page.read_text(encoding="utf-8")
    pairs = [
        (getattr(cc, name), getattr(cc, name.replace("_MARKER", "_FILE")))
        for name in dir(cc)
        if name.endswith("_SCRIPT_MARKER") and hasattr(cc, name.replace("_MARKER", "_FILE"))
    ]
    assert pairs, "aucun module de page découvert"
    for marker, filename in pairs:
        html = html.replace(marker, (RUNTIME / filename).read_text(encoding="utf-8"))
    left = [marker for marker, _ in pairs if marker in html]
    assert not left, f"marqueurs non remplacés : {left}"
    html = re.sub(r'<iframe class="face"[^>]*></iframe>', '<div class="face"></div>', html)
    out = tmp_path / "served.html"
    out.write_text(html, encoding="utf-8")
    return out


#: Le harnais CDP, en JavaScript parce que c'est là que vit le WebSocket de node.
HARNESS = (Path(__file__).parent / "_interaction_mode_browser.mjs")


def _drive(tmp_path: Path, plan: list) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    page = _served_page(tmp_path)
    done = subprocess.run(
        [node, str(HARNESS), str(page), chrome, json.dumps(plan)],
        capture_output=True, text=True, encoding="utf-8", timeout=180, check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _overlap(a: dict, b: dict) -> tuple[int, int] | None:
    if not a or not b:
        return None
    wide = min(a["r"], b["r"]) - max(a["l"], b["l"])
    high = min(a["b"], b["b"]) - max(a["t"], b["t"])
    return (round(wide), round(high)) if wide > 0 and high > 0 else None


@pytest.mark.parametrize("width,height", [(700, 600), (700, 750), (700, 900), (500, 700)])
def test_sous_700px_le_bouton_ne_recouvre_plus_la_palette_bare_hands(tmp_path, width, height):
    """Le défaut mesuré : 64x46 à 700x600, et pas seulement sur un écran court.

    Sous 700 px la colonne Bare Hands devient relative au centre et la hauteur
    de sa palette dépend du nombre d'outils installés : aucune règle verticale
    ne peut calculer ce dégagement, et le relevement du rail rendait la chose
    pire en enfonçant le bouton plus loin dedans. Le bouton étant au rang 32 et
    la palette au rang 30, c'est l'outil du bas qui devenait incliquable — une
    régression de Bare Hands causée par ce contrôle, contre la contrainte
    explicite de cette Slice.

    La sortie est horizontale : on passe à droite d'une colonne dont la largeur,
    elle, est fixe."""

    seen = _drive(tmp_path, [{"width": width, "height": height, "mountPalette": True,
                              "toast": True}])[0]
    button, palette = seen["modeBtn"], seen["palette"]
    assert palette, "la palette est bien montée : sans elle ce test ne prouve rien"
    # **Aucun recouvrement**, ni partiel ni total.
    assert _overlap(button, palette) is None, (button, palette)
    # Et il est bien passé à DROITE d'elle, pas au-dessus : c'est ce qui rend la
    # promesse indépendante du nombre d'outils installés.
    assert button["l"] >= palette["r"], (button, palette)
    # Les autres occupants de ce coin, mesurés aussi : la marque des mains et
    # l'indicateur de scène partagent le rail, l'indication vocale est centrée,
    # les infusions montent depuis le bas.
    for name in ("hint", "toast", "dock", "pills", "bhHud"):
        assert _overlap(button, seen.get(name)) is None, (name, button, seen.get(name))


def test_a_pleine_largeur_le_controle_ne_bouge_pas(tmp_path):
    """La correction est bornée au petit écran ; le grand est déjà mesuré bon."""

    seen = _drive(tmp_path, [{"width": 1440, "height": 900, "mountPalette": True,
                              "toast": True}])[0]
    button = seen["modeBtn"]
    # Toujours sur le rail gauche, à son offset d'origine.
    assert round(button["l"]) == 18
    for name in ("palette", "bhHud", "hint", "toast", "dock", "pills"):
        assert _overlap(button, seen.get(name)) is None, (name, button, seen.get(name))


def test_le_mouvement_reduit_arrete_vraiment_le_halo(tmp_path):
    """La règle existait, nommait le bon sélecteur, et perdait dans la cascade.

    `#hôte[data-im-tone=presentation] .im-mark::after` vaut (1,2,1) ; la règle
    d'arrêt écrite `#hôte .im-mark::after` ne vaut que (1,1,1). Le halo
    continuait donc de respirer sous `prefers-reduced-motion`, pendant qu'un
    test lisant la feuille comme du texte trouvait bien `.im-mark::after` dans
    le bloc et passait. On relève ici l'animation **calculée**."""

    plan = [
        {"width": 1440, "height": 900, "tone": "presentation", "reducedMotion": False},
        {"width": 1440, "height": 900, "tone": "presentation", "reducedMotion": True},
    ]
    normal, reduced = _drive(tmp_path, plan)

    # Au repos, le halo respire vraiment : sans cela l'assertion suivante serait
    # vraie pour la mauvaise raison.
    assert normal["motion"]["halo"] != "none", normal["motion"]
    assert "imBreathe" in normal["motion"]["halo"]
    assert normal["motion"]["sweep"] != "none"

    # Mouvement réduit : les trois s'arrêtent.
    assert reduced["motion"]["halo"] == "none", reduced["motion"]
    assert reduced["motion"]["sweep"] == "none", reduced["motion"]
    assert reduced["motion"]["popAnimation"] == "none", reduced["motion"]
    assert reduced["motion"]["buttonTransition"] in ("none", "all 0s ease 0s", ""), \
        reduced["motion"]
