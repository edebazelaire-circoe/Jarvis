"""Les messages qui envoient quelque part dans les Réglages nomment une destination qui existe (passe de finitions avant
la Slice 10 de jarvis-settings-ui-reorganization ; QA Slice 09, N2, mutations Q6-Q8).

Les catégories et les sections sont lues dans la page servie, telles que le registre vivant les tient (un vrai Chrome
contre un vrai Control Center isolé : aucune liste recopiée ici). Chaque « Réglages › Catégorie [› Section] » écrit dans
le code servi ou les messages du serveur doit y correspondre ; un message coupé en fin de ligne doit être le début d'un
libellé réel. Les messages corrigés par la Slice 09 (erreurs de Voice, refus de présentation, refus du tableau) sont
comptés : les remettre sur un onglet disparu fait échouer ce test.

Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit.test_wake_word_settings_browser import click, drive, eval_, got, served, wait  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
SOURCES = sorted([*ROOT.joinpath("jarvis").rglob("*.py"), *ROOT.joinpath("jarvis", "runtime").glob("*.js"),
                  ROOT / "jarvis" / "runtime" / "control_center.html"])
#: Messages corrigés par la Slice 09, et combien de fois chaque fichier nomme une destination des Réglages.
CORRECTED = {
    "jarvis/app.py": 3,  # architecture vocale illisible, clé manquante, Gemini Live hors continuous_brain
    "jarvis/runtime/presentation_runtime.py": 2,  # LEGACY_REFUSAL_MESSAGE, DUPLEX_REFUSAL_MESSAGE
    "jarvis/runtime/control_center_boards.js": 1,  # refus du mode PRESENTATION
}
LIVE = """(()=>{const R=window.JarvisSettingsRegistry;
  return R.CATEGORIES.map(c=>({id:c.id,label:c.label,sections:R.page.sections(c.id).map(s=>s.label)}))})()"""
MARK = "Réglages › "


def destinations(text: str):
    """Chaque mention, avec le reste de sa ligne."""
    for match in re.finditer(re.escape(MARK), text):
        end = text.find("\n", match.end())
        yield text[match.end(): end if end >= 0 else len(text)]


def check(rest: str, live: list[dict]) -> str | None:
    """`None` si la mention correspond au registre vivant, sinon la raison."""
    category = next((c for c in live if rest.startswith(c["label"])), None)
    if category is None:
        return "catégorie inconnue"
    after = rest[len(category["label"]):]
    if not after.startswith(" › "):
        return None
    tail = after[3:]
    if any(tail.startswith(label) for label in category["sections"]):
        return None
    cut = tail.rstrip().rstrip("\"'`").rstrip()
    if cut and tail.strip().rstrip("\"'`") == cut and any(label.startswith(cut) for label in category["sections"]):
        return None  # message coupé en fin de ligne : le début d'un libellé réel
    return "section inconnue dans " + category["label"]


async def test_every_settings_destination_named_in_messages_exists(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        wait("!!window.JarvisSettingsRegistry&&window.JarvisSettingsRegistry.page.sections('advanced_diagnostics').length>3", 8000),
        eval_(LIVE, "live"),
    ]}])
    live = got(out["steps"][0], "live")
    assert len(live) == 6 and all(c["sections"] for c in live), live
    wrong, counts = [], {}
    for path in SOURCES:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT).as_posix()
        for rest in destinations(text):
            counts[rel] = counts.get(rel, 0) + 1
            reason = check(rest, live)
            if reason:
                wrong.append((rel, rest[:90], reason))
    assert wrong == [], wrong
    for rel, expected in CORRECTED.items():
        assert counts.get(rel, 0) == expected, (rel, counts.get(rel, 0))
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert not re.search(r"onglet (« )?(Mode vocal|API Keys|Expérimental)", text), rel
    assert out["console"] == [], out["console"]


def test_the_checker_refuses_a_removed_tab_and_an_unknown_section():
    live = [{"id": "advanced_diagnostics", "label": "Avancé & diagnostic", "sections": ["Architecture & compatibilité"]},
            {"id": "connections", "label": "Connexions", "sections": ["Fournisseurs"]}]
    assert check("Avancé & diagnostic › Architecture & compatibilité, puis relancez Voice.", live) is None
    assert check("Avancé & diagnostic › Architecture &", live) is None  # coupé en fin de ligne
    assert check("Connexions du Control Center, ", live) is None
    assert check("Mode vocal", live) == "catégorie inconnue"
    assert check("Avancé & diagnostic › Mode vocal", live) == "section inconnue dans Avancé & diagnostic"
