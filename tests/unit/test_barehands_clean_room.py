"""La frontière clean-room entre Bare Hands (natif) et Barehands (amont AGPL).

**Pourquoi ce fichier existe.** La frontière était vérifiée de quatre façons —
rien de l'amont n'est versionné, la branche n'a touché ni `third_party/` ni
`scripts/`, MediaPipe n'atteint la page qu'à travers une liste blanche fermée,
et trois fichiers portent la clause en toutes lettres — mais les trois clauses
de prose n'étaient tenues par **aucun test**. Un refactor pouvait les effacer
toutes les trois sans qu'une seule ligne rougisse, et c'est précisément le genre
de garantie qu'on ne redécouvre qu'au moment où elle manque, c'est-à-dire devant
un juriste. Une garde que personne n'exerce est un vœu (constat de la Slice 11).

Ce fichier ne prouve pas l'absence de copie — aucun test ne le peut. Il tient
les quatre choses **mécaniquement vérifiables** qui, ensemble, rendent une
copie difficile à faire par accident et impossible à faire en silence.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from jarvis.runtime import barehands_test_mode as barehands

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"

#: Les trois fichiers qui portent la clause, et le fragment qui la nomme. Ce
#: sont les trois seuls endroits de `jarvis/` où « AGPL » apparaît : la clause
#: y est une **déclaration de non-reprise**, jamais une attribution.
DISCLAIMERS: tuple[tuple[str, str], ...] = (
    ("barehands_test_mode.py", "(AGPL) n'est repris ici ni dans la page."),
    ("control_center_barehands.js", "AGPL repris)"),
    ("control_center_barehands_contracts.js", "aucune ligne reprise de l'amont Barehands (AGPL)"),
)


def test_the_three_clean_room_statements_are_still_there():
    """Les trois clauses, nommées une par une.

    Les compter ne suffirait pas : trois occurrences d'« AGPL » dans trois
    fichiers quelconques passeraient. Ce sont **ces** fichiers-là qui doivent la
    porter — le module serveur qui sert les assets, le moteur, et le contrat —
    parce que ce sont les trois endroits où quelqu'un serait tenté de regarder
    l'amont pour avancer plus vite.
    """

    for name, fragment in DISCLAIMERS:
        source = (RUNTIME / name).read_text(encoding="utf-8")
        assert fragment in source, (
            f"{name} a perdu sa clause clean-room. Si le texte a légitimement "
            f"changé, changez-le ici aussi — mais ne le supprimez pas sans avis "
            f"juridique : c'est une obligation de licence, pas un commentaire."
        )


def test_no_upstream_barehands_source_is_versioned():
    """Rien de l'amont n'entre dans le dépôt : seuls le verrou et le README.

    `third_party/barehands/` est téléchargé par le bootstrap et entièrement
    ignoré par git. Un fichier de l'amont qui s'y retrouverait versionné
    emporterait ses obligations AGPL dans la distribution de Jarvis.
    """

    listed = subprocess.run(["git", "ls-files", "third_party/"], cwd=ROOT,
                            capture_output=True, text=True, timeout=60, check=True)
    tracked = sorted(line for line in listed.stdout.splitlines() if line.strip())
    assert tracked == ["third_party/LOCK.json", "third_party/README.md"], tracked


def test_mediapipe_reaches_the_page_only_through_the_closed_whitelist():
    """**Six noms exacts, et aucune autre porte.**

    La liste blanche ne vaut que s'il n'existe pas un second service de fichiers
    plus permissif ailleurs. Ce test refuse donc un `FileResponse` /
    `web.static` / `StaticFiles` / `send_file` de plus sous `jarvis/` : la
    prochaine route qui sert un fichier devra s'ajouter ici et s'expliquer.
    """

    found = subprocess.run(
        ["git", "grep", "-n", "-E", r"FileResponse|web\.static|StaticFiles|send_file", "--", "jarvis/"],
        cwd=ROOT, capture_output=True, text=True, timeout=60, check=False)
    hits = [line for line in found.stdout.splitlines() if line.strip()]
    assert len(hits) == 1, (
        "une seconde façon de servir un fichier est apparue sous jarvis/ ; la "
        "liste blanche des assets ne garantit plus rien tant qu'elle n'est pas "
        f"la seule porte :\n" + "\n".join(hits)
    )
    assert "control_center.py" in hits[0], hits
    # Et c'est bien le servant d'assets Bare Hands, pas une route quelconque.
    line_number = int(hits[0].split(":")[1])
    source = (RUNTIME / "control_center.py").read_text(encoding="utf-8").splitlines()
    context = "\n".join(source[max(0, line_number - 12):line_number])
    assert "barehands_asset" in context, context

    # Les six noms sont exactement ceux que le contrat déclare servir.
    assert sorted(barehands.ASSETS) == [
        "models/hand_landmarker.task",
        "vision_bundle.mjs",
        "wasm/vision_wasm_internal.js",
        "wasm/vision_wasm_internal.wasm",
        "wasm/vision_wasm_nosimd_internal.js",
        "wasm/vision_wasm_nosimd_internal.wasm",
    ]


@pytest.mark.parametrize("name", ["control_center_barehands.js",
                                  "control_center_barehands_contracts.js",
                                  "control_center_barehands_target.js",
                                  "control_center_barehands_calibration.js",
                                  "control_center_barehands_tutorial.js",
                                  "control_center_barehands_recorder.js",
                                  "control_center_barehands_hud.js",
                                  "control_center_barehands_commands.js"])
def test_no_page_module_speaks_to_the_upstream_board(name):
    """Les huit modules de page ne connaissent **pas** le tableau amont.

    Ils partagent un nom avec lui et rien d'autre : ni port, ni jeton, ni page.
    Un module natif qui nommerait `8794` ou `X-Jarvis-Token` aurait cessé d'être
    un sous-système séparé — et personne ne s'en apercevrait avant la revue de
    licence.

    Le module **serveur** (`barehands_test_mode.py`) est volontairement hors de
    cette liste : sa docstring nomme le tableau amont et son port **pour dire
    de ne pas les confondre**, ce qui est le contraire d'une dépendance. La
    distinction est le sujet, pas le mot.

    Ce test est faible par construction — il ne connaît que les noms de l'amont
    qu'on a pensé à écrire — et il le dit. Ce qui tient vraiment la frontière
    est qu'aucune ligne de l'amont n'est **lisible** depuis ce dépôt : elle
    n'est pas versionnée, et le bootstrap la range hors de `jarvis/`.
    """

    source = (RUNTIME / name).read_text(encoding="utf-8")
    for upstream in ("stage.html", "X-Jarvis-Token", "8794"):
        assert upstream not in source, (
            f"{name} nomme « {upstream} », qui appartient au tableau amont "
            f"(Barehands, un mot) et non au sous-système natif (Bare Hands)."
        )
