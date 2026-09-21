"""La couleur d'état de l'agent ne sort pas de la boule lumineuse.

Ce que l'utilisateur a demandé, dans ses mots : « c'est l'agent Jarvis qui doit
changer de couleur selon ses états, ce ne sont pas les outils ; l'agent, c'est
juste la boule lumineuse de Jarvis ». Autrement dit il y a **deux** couleurs
dans cette page et elles ont deux rôles :

- ``--cosmos-accent`` est la couleur de l'**agent**. `control_center_work.js` la
  republie sur ``document.documentElement`` à chaque changement d'état vocal,
  depuis ``STATE_COLORS`` — bleu au repos, vert à l'écoute, **orange** quand
  JARVIS parle, violet quand il réfléchit.
- ``--accent`` est la couleur de l'**interface** : le bleu #6ee7ff, constant.

Le défaut que ce fichier empêche de revenir n'était pas une teinte mal choisie,
c'était un **abonnement** : la pastille d'état, les boutons de la barre
d'outils, la carte de thème, la colonne Bare Hands, sa palette, le jeton de
main et la surimpression de calibration lisaient tous la couleur de l'agent.
Tant que la voix était poussée au bouton, l'état dominant était ``idle`` et
l'interface paraissait bleue ; depuis que le duplex GPT-Live parle en continu,
l'état dominant est ``speaking`` et l'ambiance entière de la page virait à
l'orange au rythme de la parole.

La règle est donc négative, et c'est exprès : **personne ne lit
``--cosmos-accent``**. Une règle formulée ainsi se vérifie sur l'ensemble des
fichiers servis, y compris ceux qui n'existent pas encore — alors qu'un test
qui épinglerait la couleur de chaque élément un par un laisserait passer le
prochain élément ajouté.

Un commentaire disant la même chose aurait été moins cher et n'aurait rien
garanti : la première fois que ce défaut est apparu, la doctrine « jamais un
hexadécimal nu, toujours le jeton suivi de son repli » était déjà écrite en
toutes lettres au-dessus de la ligne fautive.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"

#: Le nom de la couleur d'agent. Il n'apparaît qu'ici pour que le test dise de
#: quoi il parle même quand il échoue loin de son contexte.
AGENT_COLOUR = "--cosmos-accent"

#: Le seul fichier autorisé à *écrire* la couleur d'agent : celui qui dessine
#: l'orbe. Personne n'est autorisé à la **lire**, lui compris — l'orbe peint son
#: canevas avec `STATE_COLORS` en JavaScript, pas à travers une variable CSS.
PUBLISHER = "control_center_work.js"

#: Toutes les façons de **lire** la couleur d'agent. Le `var(...)` couvre le CSS
#: (y compris à l'intérieur d'un `color-mix`), les deux `getPropertyValue`
#: couvrent le détour par JavaScript qui contournerait le premier.
READERS = (
    re.compile(r"var\(\s*" + re.escape(AGENT_COLOUR)),
    re.compile(r"getPropertyValue\(\s*['\"]" + re.escape(AGENT_COLOUR)),
)


def served_files() -> list[Path]:
    """Les fichiers que `ControlCenter.index` assemble et sert au navigateur."""
    files = sorted(RUNTIME.glob("*.js")) + sorted(RUNTIME.glob("*.html"))
    assert files, f"aucun fichier servi trouvé sous {RUNTIME}"
    return files


def test_nothing_outside_the_orb_reads_the_agent_state_colour():
    """Aucune surface de l'interface ne se peint avec l'état de l'agent.

    L'échec nomme le fichier, la ligne et le texte fautif : « quelque chose lit
    la couleur de l'agent » est inutile si le lecteur doit ensuite la chercher.
    """
    offenders: list[str] = []
    for path in served_files():
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            for reader in READERS:
                if reader.search(line):
                    offenders.append(f"{path.name}:{number}: {line.strip()[:120]}")
    assert not offenders, (
        "la couleur d'état de l'agent doit rester sur la boule lumineuse ; "
        f"ces surfaces s'y abonnent encore et vireront à l'orange dès que JARVIS parle, "
        f"elles doivent lire `--accent` :\n  " + "\n  ".join(offenders)
    )


def test_the_orb_still_publishes_its_state_colour():
    """La règle ne doit pas pouvoir être satisfaite en éteignant l'orbe.

    Supprimer la publication ferait passer le test précédent tout en retirant à
    JARVIS la seule chose que l'utilisateur veut voir changer de couleur. Les
    deux assertions ne tiennent donc de sens qu'ensemble.
    """
    source = (RUNTIME / PUBLISHER).read_text(encoding="utf-8")
    assert f"setProperty('{AGENT_COLOUR}'" in source, (
        f"{PUBLISHER} ne publie plus la couleur d'état de l'agent : la boule "
        "lumineuse ne changerait plus de couleur selon ce que fait JARVIS."
    )
    for state in ("idle", "listening", "speaking", "thinking"):
        assert re.search(rf"\b{state}\s*:\s*\[", source), (
            f"l'état « {state} » n'a plus de couleur dans STATE_COLORS"
        )


@pytest.mark.parametrize(
    "surface",
    [
        "control_center_barehands_hud.js",
        "control_center_barehands.js",
        "control_center_barehands_calibration.js",
        "control_center_work.js",
    ],
)
def test_the_chassis_takes_the_interface_blue(surface: str):
    """Le châssis prend le bleu de l'interface, et le dit.

    Les quatre fichiers nommés sont ceux qui portaient l'abonnement : la colonne
    Bare Hands et sa palette, le jeton de main, la coque de calibration, et le
    châssis Cosmos. Les nommer un par un ici est délibéré — c'est la liste de ce
    qui a réellement viré à l'orange sous les yeux de l'utilisateur, et elle
    doit rester vraie même si le test générique ci-dessus était un jour
    contourné par une écriture qu'il ne reconnaît pas.
    """
    text = (RUNTIME / surface).read_text(encoding="utf-8")
    assert "var(--accent,#6ee7ff)" in text, (
        f"{surface} ne prend pas le bleu d'interface `var(--accent,#6ee7ff)`"
    )
