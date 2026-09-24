"""L'avertissement de vérification, mesuré dans un vrai navigateur (Slice 09).

**Pourquoi ce fichier existe.** La Slice 03 a livré trois tests qui lisaient la
source comme du texte et ont manqué les trois défauts qu'ils existaient pour
attraper. Le LOG du handoff en fait une règle pour cette Slice-ci :
*« Slice 09 doit affirmer sur le comportement ou le style calculé, jamais sur le
texte de la source. »*

Ce fichier ne lit rien. Il compose la page **telle que `ControlCenter.index` la
sert**, la fait servir en HTTP par un petit serveur local qui répond aussi
`/api/status`, ouvre un ou deux onglets de Chrome sans tête, et relève des
rectangles, des styles calculés, du texte rendu, des requêtes réseau réelles et
**le nombre d'oscillateurs WebAudio créés**.

L'HTTP n'est pas du zèle : deux onglets ne partagent un `localStorage` que
s'ils partagent une origine, et `file://` n'en donne pas d'utilisable. « Deux
onglets, un seul son » n'est démontrable qu'à ce niveau-là.

Ce que ce fichier épingle :

- une contradiction produit **exactement une carte** et **au plus un signal** ;
- le sondage qui continue ne rejoue rien ;
- un rechargement ne rejoue rien ;
- **deux onglets sonnent une fois**, pas deux ;
- écarter la carte **n'émet aucune requête**, donc ne peut toucher aucun fait ;
- la carte ne recouvre ni la palette Bare Hands, ni le contrôle de mode, ni
  l'indication vocale, à pleine largeur comme sous 760 px ;
- la confiance est montrée en **mots**, jamais en chiffres ;
- `prefers-reduced-motion` arrête vraiment l'entrée de la carte.

Le test se saute proprement si Chrome ou node est absent ; il ne se saute pas
en silence si la page ne se compose pas.
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

#: Chrome, aux emplacements où Windows le pose. Même table que le harnais de la
#: Slice 03 : absent, les tests se sautent, mais rien n'y « passe » sans
#: navigateur.
CHROME_CANDIDATES = (
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
)

HARNESS = Path(__file__).parent / "_presentation_attention_browser.mjs"


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

    Les paires marqueur/fichier sont découvertes depuis le module lui-même —
    même technique que le harnais de la Slice 03 — de sorte qu'un module ajouté
    plus tard entre ici sans que personne n'y pense. La copie de cette fonction
    est délibérée : la garder autonome évite de faire dépendre un fichier de
    test d'un autre, ce qui casserait dès qu'on en exécute un seul.
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


def _drive(tmp_path: Path, plan: list) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    page = _served_page(tmp_path)
    done = subprocess.run(
        [node, str(HARNESS), str(page), chrome, json.dumps(plan)],
        capture_output=True, text=True, encoding="utf-8", timeout=300, check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _overlap(a: dict | None, b: dict | None) -> tuple[int, int] | None:
    if not a or not b:
        return None
    wide = min(a["r"], b["r"]) - max(a["l"], b["l"])
    high = min(a["b"], b["b"]) - max(a["t"], b["t"])
    return (round(wide), round(high)) if wide > 0 and high > 0 else None


def _background(seq: int, items: list[dict]) -> dict:
    return {
        "seq": seq,
        "unread": len(items),
        "counts": {"attention": len(items)} if items else {},
        "attention": items,
    }


def _attention(seq: int, attention_id: str = "att-1", category: str = "contradiction") -> dict:
    return {
        "seq": seq,
        "ts": "2026-09-24T10:00:00+00:00",
        "label": "Une affirmation est contredite par une source vérifiée",
        "detail": "2 sources · confiance élevée",
        "attention": {
            "attention_id": attention_id,
            "category": category,
            "severity": "warning",
            "band": "high",
            "claim_id": "claim-1",
            "topic_id": "topic-1",
            "source_count": 2,
            "evidence": [
                {"source_id": "src-1", "locator": "https://exemple.test/rapport",
                 "title": "Rapport trimestriel 2026", "resource_id": "res-1"},
                {"source_id": "src-2", "locator": "doc:interne/bilan",
                 "title": "Bilan interne", "resource_id": ""},
            ],
            "resource_ids": ["res-1"],
        },
    }


def _status(background: dict) -> dict:
    return {
        "agent": {"name": "test", "state": "stopped"}, "agent_cli": "test",
        "error_count": 0, "voice_state": "idle", "voice_online": False,
        "background": background,
    }


# ==========================================================================
# 1. Une contradiction : une carte, un signal, et pas un de plus
# ==========================================================================


def test_une_contradiction_donne_une_carte_et_au_plus_un_signal(tmp_path):
    """Le critère d'acceptation de la Slice, mesuré et non raisonné.

    Le sondage continue pendant quatre battements après la hausse : c'est
    précisément là qu'un rejeu se verrait, puisque la page relit le même statut
    chaque seconde. On compte les oscillateurs WebAudio réellement créés — deux
    par signal, `bgCue` jouant deux notes — et les appels à `bgCue`.
    """

    item = _attention(7)
    out = _drive(tmp_path, [
        {"a": "open", "tabs": 1, "width": 1440, "height": 900},
        # Un premier statut sans rien : c'est lui qui arme la règle de hausse.
        {"a": "status", "value": _status(_background(3, []))},
        {"a": "status", "value": _status(_background(7, [item])), "waitMs": 1500},
        {"a": "read"},
        # Le sondage continue sur le MÊME statut : rien ne doit rejouer.
        {"a": "status", "value": _status(_background(7, [item])), "waitMs": 3500},
        {"a": "read"},
    ])
    first, second = out["reads"][0][0], out["reads"][1][0]

    assert first["installed"] is True, "le module ne s'est pas installé"
    assert len(first["cards"]) == 1, first["cards"]
    card = first["cards"][0]
    assert card["id"] == "att-1"
    assert card["tone"] == "warn"
    assert card["title"] == "Contradiction"
    assert card["role"] == "status" and card["live"] == "polite"

    # Au plus un signal, et le compte ne bouge plus ensuite.
    assert first["probe"]["cues"] == 1, first["probe"]
    assert second["probe"]["cues"] == 1, second["probe"]
    assert len(second["cards"]) == 1, second["cards"]
    # Deux notes par signal quand le contexte audio s'ouvre ; zéro s'il refuse.
    assert second["probe"]["osc"] in (0, 2), second["probe"]


def test_le_sondage_ne_rejoue_ni_carte_ni_signal_apres_un_rechargement(tmp_path):
    """Rouvrir la page ne doit pas sonner pour du passé.

    Deux ceintures se recouvrent ici et le test les traverse toutes les deux :
    `BG.armed`, qui refuse le premier sondage d'une page neuve, et la borne
    haute partagée que la Slice 09 range dans `localStorage`, qui survit au
    rechargement. La carte, elle, **revient** : elle décrit un fait non acquitté
    et le cacher serait perdre l'avertissement.
    """

    item = _attention(7)
    out = _drive(tmp_path, [
        {"a": "open", "tabs": 1, "width": 1440, "height": 900},
        {"a": "status", "value": _status(_background(3, []))},
        {"a": "status", "value": _status(_background(7, [item])), "waitMs": 1500},
        {"a": "read"},
        {"a": "reload", "tab": 0},
        {"a": "status", "value": _status(_background(7, [item])), "waitMs": 2500},
        {"a": "read"},
    ])
    before, after = out["reads"][0][0], out["reads"][1][0]
    assert before["probe"]["cues"] == 1, before["probe"]
    # Le compteur est reparti de zéro avec la page : c'est bien ZÉRO signal
    # après le rechargement, et non « le même qu'avant ».
    assert after["probe"]["cues"] == 0, after["probe"]
    assert after["probe"]["osc"] == 0, after["probe"]
    assert len(after["cards"]) == 1, after["cards"]


def test_deux_onglets_ne_sonnent_qu_une_fois(tmp_path):
    """Le trou que cette Slice bouche, et le seul qui demandait du neuf.

    Les deux onglets partagent une origine HTTP, donc un `localStorage`. Chacun
    sonde à 1 Hz et chacun voit la hausse. Sans arbitrage, chacun sonne : c'est
    exactement ce que faisait la page avant cette Slice.

    On somme les deux compteurs : un total de 1 est la promesse. Un total de 2
    serait le défaut. Un total de 0 serait pire encore, et c'est pourquoi le
    test des deux côtés est une **égalité** et non une borne supérieure.
    """

    item = _attention(7)
    out = _drive(tmp_path, [
        {"a": "open", "tabs": 2, "width": 1280, "height": 900},
        {"a": "status", "value": _status(_background(3, []))},
        {"a": "status", "value": _status(_background(7, [item])), "waitMs": 3000},
        {"a": "read"},
    ])
    tabs = out["reads"][0]
    assert len(tabs) == 2
    total = sum(tab["probe"]["cues"] for tab in tabs)
    assert total == 1, [tab["probe"] for tab in tabs]
    # Les deux onglets montrent quand même l'avertissement : c'est le son qui
    # est arbitré, pas l'information.
    for tab in tabs:
        assert len(tab["cards"]) == 1, tab["cards"]


# ==========================================================================
# 2. Écarter ne touche aucun fait
# ==========================================================================


def test_ecarter_l_avertissement_n_emet_aucune_requete(tmp_path):
    """« Un acquittement change l'état de l'interface, jamais l'ensemble de travail. »

    La preuve la plus forte disponible depuis le navigateur est l'absence de
    requête : sans appel réseau, aucun fait ne peut bouger, puisque l'ensemble
    de travail vit dans un autre processus. On relève **toutes** les requêtes
    du serveur entre deux marqueurs, et on n'y admet que le sondage de statut.
    """

    item = _attention(7)
    out = _drive(tmp_path, [
        {"a": "open", "tabs": 1, "width": 1440, "height": 900},
        {"a": "status", "value": _status(_background(7, [item])), "waitMs": 1500},
        {"a": "mark", "name": "avant"},
        {"a": "click", "tab": 0, "selector": ".pa-card .pa-close"},
        {"a": "mark", "name": "apres"},
        {"a": "read"},
    ])
    marks = [i for i, r in enumerate(out["requests"]) if r["method"] == "MARK"]
    assert len(marks) == 2, out["requests"]
    between = out["requests"][marks[0] + 1:marks[1]]
    assert all(r["path"] == "/api/status" and r["method"] == "GET" for r in between), between
    # Et surtout : rien vers le registre d'arrière-plan, sur toute la course.
    assert not [r for r in out["requests"] if r["path"].startswith("/api/background")], \
        out["requests"]
    # La carte est bien partie.
    assert out["reads"][0][0]["cards"] == [], out["reads"][0][0]["cards"]


def test_la_carte_s_ouvre_sur_ses_preuves(tmp_path):
    """Ignorable, ou ouvrable : la seconde moitié de `HV-PRES-ALERT-01`.

    Ce qui s'ouvre porte les **sources** — un lien cliquable pour ce qu'un
    navigateur sait ouvrir, un texte pour une référence interne — et jamais une
    phrase venue de la salle, que le Core ne fait pas descendre dans la trace.
    """

    item = _attention(7)
    out = _drive(tmp_path, [
        {"a": "open", "tabs": 1, "width": 1440, "height": 900},
        {"a": "status", "value": _status(_background(7, [item])), "waitMs": 1500},
        {"a": "read"},
        {"a": "click", "tab": 0, "selector": ".pa-card .pa-head"},
        {"a": "read"},
    ])
    closed, opened = out["reads"][0][0]["cards"][0], out["reads"][1][0]["cards"][0]

    assert closed["bodyHidden"] is True and closed["expanded"] == "false"
    assert opened["bodyHidden"] is False and opened["expanded"] == "true"

    sources = opened["sources"]
    assert [s["tag"] for s in sources] == ["a", "span"], sources
    assert sources[0]["href"] == "https://exemple.test/rapport"
    assert "noopener" in sources[0]["rel"] and "noreferrer" in sources[0]["rel"]
    assert sources[0]["text"] == "Rapport trimestriel 2026"
    # Une référence interne n'est pas un lien mort : elle est montrée en clair.
    assert sources[1]["href"] == "" and sources[1]["text"] == "Bilan interne"
    assert "Jarvis ne le dira pas de lui-même" in opened["bodyText"]


def test_la_confiance_est_montree_en_mots_jamais_en_chiffres(tmp_path):
    """Les quatre confiances de la voie ambiante ne sont pas étalonnées.

    `docs/presentation-ambient-lane.md` §11 le dit : codées en dur, non
    calibrées. Les afficher comme un nombre leur donnerait l'autorité d'une
    mesure. On lit donc tout le texte rendu de la carte, ouverte, et on refuse
    tout chiffre qui ressemblerait à une confiance.
    """

    item = _attention(7)
    out = _drive(tmp_path, [
        {"a": "open", "tabs": 1, "width": 1440, "height": 900},
        {"a": "status", "value": _status(_background(7, [item])), "waitMs": 1500},
        {"a": "click", "tab": 0, "selector": ".pa-card .pa-head"},
        {"a": "read"},
    ])
    card = out["reads"][0][0]["cards"][0]
    text = f"{card['title']} {card['sub']} {card['bodyText']}"
    assert "confiance élevée" in text, text
    # Ni 0,82 ni 0.82 ni 82 % : aucune forme numérique de confiance.
    assert not re.search(r"\d\s*[,.]\s*\d|\d\s*%", text), text


# ==========================================================================
# 3. La place, mesurée plutôt que promise
# ==========================================================================


@pytest.mark.parametrize("width,height", [(1440, 900), (1024, 768), (760, 700), (500, 700)])
def test_la_carte_ne_recouvre_aucun_occupant_du_bas(tmp_path, width, height):
    """Le coin bas de cette page est disputé : on le mesure, on ne le suppose pas.

    Trois occupants comptent, et le premier a déjà coûté un blocage à la
    Slice 03 : la palette Bare Hands (rang 30, hauteur dépendant du nombre
    d'outils), le contrôle de mode (rang 32) et l'indication vocale centrée.
    La palette est montée avec cinq outils, ce qui est au-dessus du plancher de
    trois utilisé par le harnais de la Slice 03.

    Deux infusions sont posées en plus : la carte partage leur pile, donc elle
    doit rester en bas et elles doivent monter au-dessus d'elle — ce qui est
    aussi ce que vérifie le test suivant.
    """

    item = _attention(7)
    out = _drive(tmp_path, [
        {"a": "open", "tabs": 1, "width": width, "height": height},
        {"a": "mount", "tab": 0, "palette": True, "toasts": 2},
        {"a": "status", "value": _status(_background(7, [item])), "waitMs": 1500},
        {"a": "read"},
    ])
    seen = out["reads"][0][0]
    card = seen["card"]
    assert card, "la carte n'est pas dessinée : sans elle ce test ne prouve rien"
    assert seen["palette"], "la palette est bien montée : sans elle ce test ne prouve rien"
    for name in ("palette", "modeBtn", "hint"):
        assert _overlap(card, seen.get(name)) is None, (name, card, seen.get(name))
    # Et elle tient dans la fenêtre : une carte poussée hors écran serait un
    # avertissement perdu, ce qui est le défaut que D11 interdit.
    assert card["t"] >= 0 and card["b"] <= seen["viewport"]["h"], (card, seen["viewport"])
    assert card["l"] >= 0 and card["r"] <= seen["viewport"]["w"], (card, seen["viewport"])


def test_la_carte_reste_la_plus_basse_de_la_pile(tmp_path):
    """`toast()` fait un `appendChild` : sans `order`, une infusion passerait dessous.

    La carte doit rester au plus près du coin — c'est ce qui la rend visible
    quoi qu'il arrive. On relève l'ordre calculé **et** la position réelle des
    deux boîtes, parce que l'un sans l'autre ne prouve rien : une propriété
    peut être posée et perdue dans la cascade, et c'est exactement ce que la
    Slice 03 a payé trois fois.
    """

    item = _attention(7)
    out = _drive(tmp_path, [
        {"a": "open", "tabs": 1, "width": 1440, "height": 900},
        {"a": "status", "value": _status(_background(7, [item])), "waitMs": 1500},
        # Les infusions arrivent APRÈS la carte : c'est le cas qui casse.
        {"a": "mount", "tab": 0, "toasts": 2},
        {"a": "read"},
    ])
    seen = out["reads"][0][0]
    card, toast = seen["card"], seen["toast"]
    assert card and toast, seen
    assert card["order"] == "1", card
    assert card["t"] > toast["b"], (card, toast)
    assert card["pointerEvents"] == "auto", card


def test_le_mouvement_reduit_arrete_l_entree_de_la_carte(tmp_path):
    """La règle existe ; seul le style calculé dit si la cascade l'a gardée.

    C'est la leçon du halo de la Slice 03 : la feuille nommait le bon sélecteur
    et le navigateur faisait le contraire. On relève donc l'animation calculée
    de la carte elle-même, dans les deux régimes.
    """

    item = _attention(7)
    plan = lambda reduced: [
        {"a": "open", "tabs": 1, "width": 1440, "height": 900, "reducedMotion": reduced},
        {"a": "status", "value": _status(_background(7, [item])), "waitMs": 1500},
        {"a": "read"},
    ]
    normal = _drive(tmp_path, plan(False))["reads"][0][0]["card"]
    reduced = _drive(tmp_path, plan(True))["reads"][0][0]["card"]
    # Au repos la carte entre vraiment : sans cela l'assertion suivante serait
    # vraie pour la mauvaise raison.
    assert normal["animation"] != "none" and "paIn" in normal["animation"], normal
    assert reduced["animation"] == "none", reduced


def test_aucun_texte_recu_ne_devient_du_balisage(tmp_path):
    """Le domaine ne nettoie délibérément pas ses textes ; la page doit le faire.

    `bounded_text` n'a **aucune** règle de balisage — la Slice 04 l'a écrit noir
    sur blanc, parce que « la marge < 10 % » est une phrase française ordinaire
    et que la refuser avec un code parlant d'une ressource avait déjà cassé la
    Slice 06. L'échappement appartient donc à la surface.

    On envoie une charge utile hostile dans chaque champ que la carte affiche,
    et on vérifie dans un vrai analyseur HTML que rien n'a été interprété.
    """

    hostile = '<img src=x onerror="window.__pwned=1">'
    item = _attention(7)
    item["label"] = f"contredite {hostile}"
    item["detail"] = f"2 sources {hostile}"
    item["attention"]["category"] = hostile
    item["attention"]["evidence"] = [
        {"source_id": "src-1", "locator": "https://exemple.test/x",
         "title": hostile, "resource_id": ""},
    ]
    out = _drive(tmp_path, [
        {"a": "open", "tabs": 1, "width": 1440, "height": 900},
        {"a": "status", "value": _status(_background(7, [item])), "waitMs": 1500},
        {"a": "click", "tab": 0, "selector": ".pa-card .pa-head"},
        {"a": "read"},
        {"a": "eval", "tab": 0,
         "expr": "({pwned:window.__pwned===undefined?null:window.__pwned,"
                 "imgs:document.querySelectorAll('.pa-card img').length})"},
    ])
    card = out["reads"][0][0]["cards"][0]
    probe = out["reads"][1]

    assert probe["pwned"] is None, probe
    assert probe["imgs"] == 0, probe
    assert "<img" not in card["html"], card["html"]
    assert "&lt;img" in card["html"], card["html"]
    # Le texte est bien là, échappé, et non simplement supprimé : une carte
    # vide passerait ce test pour la mauvaise raison.
    assert hostile in card["bodyText"], card["bodyText"]
    # Une catégorie que cette page ne connaît pas reste neutre.
    assert card["tone"] == "info" and card["title"] == "À vérifier"
