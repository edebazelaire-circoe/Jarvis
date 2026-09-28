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


# ==========================================================================
# 4. Le coin bas, repris : la carte ne doit voler aucun clic
# ==========================================================================

#: Le point de clic de la pastille, releve dans le vrai arbre de rendu.
#: `elementFromPoint` est la seule mesure qui reponde a « ce bouton est-il
#: cliquable », parce qu'elle traverse les rangs d'empilement comme le curseur.
_PILL_HIT = """(function(){var p=document.querySelector('.bgpill');if(!p)return{pill:false};var r=p.getBoundingClientRect();var el=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return{pill:true,tag:el?el.tagName.toLowerCase():null,cls:el?String(el.className):null,isPill:!!(el&&el.closest&&el.closest('.bgpill'))}})()"""


@pytest.mark.parametrize("width,height", [
    # **La forme courte et large manquait a la serie d'origine**, et c'est la
    # seule qui fasse descendre les pastilles dans la bande des infusions :
    # elles suivent le CENTRE du viewport (`top:calc(50% + 193px)`) tandis que
    # le rail des infusions est ancre en BAS. Mesurer sept tailles etait juste ;
    # l'ensemble avait un trou exactement la ou ce defaut vit.
    (1440, 520), (1280, 560), (700, 600), (360, 640), (1440, 900), (820, 900),
])
def test_la_carte_ne_vole_jamais_le_clic_de_la_pastille(tmp_path, width, height):
    """**B2.** La pastille est la porte d'acquittement de l'avertissement lui-meme.

    Le commentaire de ce module dit que le point « reste compte dans la
    pastille, ou il s'acquitte par la porte existante ». Si la carte recouvre
    cette pastille, la phrase est fausse et le seul moyen d'acquitter a
    disparu — et contrairement a une infusion, qui s'efface au bout de cinq
    secondes, la carte reste jusqu'a ce qu'on l'ecarte.

    On ne mesure donc pas seulement le recouvrement : on demande au navigateur
    **quel element recevrait le clic**.
    """

    item = _attention(7)
    out = _drive(tmp_path, [
        {"a": "open", "tabs": 1, "width": width, "height": height},
        {"a": "status", "value": _status(_background(7, [item])), "waitMs": 1500},
        {"a": "read"},
        {"a": "eval", "tab": 0, "expr": _PILL_HIT},
    ])
    seen, hit = out["reads"][0][0], out["reads"][1]

    assert seen["card"], "la carte est dessinee : sans elle ce test ne prouve rien"
    assert hit["pill"] is True, "la pastille est dessinee : idem"
    assert hit["isPill"] is True, (width, height, hit, seen["card"], seen["pills"])
    assert _overlap(seen["card"], seen.get("pills")) is None, (seen["card"], seen["pills"])


@pytest.mark.parametrize("width,height,panel", [
    # 820x900 etait DANS la serie d'origine et le recouvrement de 48x32 y a
    # quand meme echappe : le seuil de relevement etait a 760 px, donc inactif.
    (820, 900, False),
    # Panneau ouvert : le rail se decale a gauche et vient sur l'indication
    # vocale centree, a la taille de bureau par defaut.
    (1440, 900, True),
    (1440, 900, False),
    (700, 600, False),
])
def test_la_carte_ne_recouvre_jamais_l_indication_vocale(tmp_path, width, height, panel):
    """Elle ne bloque aucun clic, mais elle cache l'affordance vocale de la page.

    `.voicehint` est centree en bas a **toutes** les largeurs et la page ne la
    deplace jamais. Une carte persistante posee dessus retire de l'ecran ce qui
    dit a l'utilisateur comment parler a Jarvis — pendant une presentation.
    """

    item = _attention(7)
    plan = [{"a": "open", "tabs": 1, "width": width, "height": height}]
    if panel:
        plan.append({"a": "mount", "tab": 0, "panel": True})
    plan += [{"a": "status", "value": _status(_background(7, [item])), "waitMs": 1500},
             {"a": "read"}]
    seen = _drive(tmp_path, plan)["reads"][0][0]
    assert seen["card"] and seen["hint"], seen
    assert _overlap(seen["card"], seen["hint"]) is None, (seen["card"], seen["hint"])


@pytest.mark.parametrize("width", [688, 694, 700, 706])
def test_la_carte_ne_deborde_jamais_de_la_fenetre(tmp_path, width):
    """Le seuil de 700 px est une falaise : on mesure des deux cotes.

    Entre 688 et 700 px la regle etroite s'applique alors que la largeur du
    rail est encore celle du grand ecran, et la carte debordait de douze pixels
    par la gauche.
    """

    item = _attention(7)
    seen = _drive(tmp_path, [
        {"a": "open", "tabs": 1, "width": width, "height": 800},
        {"a": "status", "value": _status(_background(7, [item])), "waitMs": 1500},
        {"a": "read"},
    ])["reads"][0][0]
    card = seen["card"]
    assert card, seen
    assert card["l"] >= 0, (width, card)
    assert card["r"] <= seen["viewport"]["w"], (width, card, seen["viewport"])


def test_echap_referme_puis_ecarte_la_carte(tmp_path):
    """Point 12 : une carte persistante doit pouvoir partir au clavier.

    Le geste est en deux temps, comme partout ailleurs dans cette page : Échap
    referme d'abord le détail, puis écarte. Et il ne dispute pas la touche au
    gestionnaire global de la page — celui-ci ferme la liste des pastilles en
    phase de capture — parce qu'on ne l'arrête que lorsqu'on a agi.
    """

    item = _attention(7)
    key = ('(function(){var c=document.querySelector(".pa-card");if(!c)return "absente";'
           'c.focus&&c.focus();'
           'c.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape",bubbles:true}));'
           'return "ok"})()')
    out = _drive(tmp_path, [
        {"a": "open", "tabs": 1, "width": 1440, "height": 900},
        {"a": "status", "value": _status(_background(7, [item])), "waitMs": 1500},
        {"a": "click", "tab": 0, "selector": ".pa-card .pa-head"},
        {"a": "read"},
        {"a": "eval", "tab": 0, "expr": key},
        {"a": "read"},
        {"a": "eval", "tab": 0, "expr": key},
        {"a": "read"},
    ])
    # `eval` pousse sa valeur brute dans `reads`, au meme titre qu'une lecture :
    # les indices alternent donc read / eval / read / eval / read.
    opened = out["reads"][0][0]["cards"][0]
    closed = out["reads"][2][0]["cards"][0]
    gone = out["reads"][4][0]["cards"]

    assert opened["bodyHidden"] is False, "le detail est bien ouvert au depart"
    assert closed["bodyHidden"] is True, "le premier Echap referme"
    assert gone == [], "le second Echap ecarte"
    # Et aucune requete n'est partie : ecarter au clavier ne touche pas plus
    # aux faits qu'ecarter a la souris.
    assert not [r for r in out["requests"] if r["path"].startswith("/api/background")]


def test_le_titre_vient_de_la_table_et_jamais_du_message_de_trace(tmp_path):
    """Point 5 : la garantie doit etre structurelle, pas conventionnelle.

    Une version precedente lisait `entry.label`, c'est-a-dire le **message brut**
    de la ligne de journal — le seul champ que le registre ne retaille pas. Elle
    tenait parce que le producteur actuel y met une phrase fixe : une convention,
    pas une garantie. Un futur producteur sur cette meme nature d'evenement
    aurait pu ecrire ce qu'il voulait sur la carte, parole de la salle comprise.

    Le test qui existait ne voyait rien, parce que son `label` de fixture etait
    justement la phrase de la table : les deux sources etaient
    indiscernables. Ici elles sont rendues differentes exprès, et c'est la seule
    facon de prouver laquelle des deux la carte lit.
    """

    marque = "PHRASE-VENUE-DE-LA-TRACE-QUI-NE-DOIT-PAS-S-AFFICHER"
    item = _attention(7)
    item["label"] = marque
    out = _drive(tmp_path, [
        {"a": "open", "tabs": 1, "width": 1440, "height": 900},
        {"a": "status", "value": _status(_background(7, [item])), "waitMs": 1500},
        {"a": "click", "tab": 0, "selector": ".pa-card .pa-head"},
        {"a": "read"},
    ])
    card = out["reads"][0][0]["cards"][0]
    whole = f"{card['title']} {card['sub']} {card['bodyText']} {card['html']}"

    assert marque not in whole, whole
    # Et la phrase de la table EST la, sinon l'assertion ci-dessus serait vraie
    # pour la mauvaise raison — une carte vide la satisferait aussi.
    assert "contredite par une source vérifiée" in card["bodyText"], card["bodyText"]


def test_la_carte_n_avale_que_la_touche_qu_elle_traite(tmp_path):
    """Elle arrete la propagation d'Echap, et d'AUCUNE autre touche.

    Survivant de mutation : remonter `stopPropagation()` au-dessus du controle
    de touche faisait avaler par la carte **toutes** les frappes tant que le
    focus y etait — les raccourcis d'interface de la page compris. Le test
    d'Echap ne voyait rien, puisqu'il n'appuie que sur Echap : une garde
    exercee sur le seul cas qu'elle doit laisser passer ne garde rien.

    On installe un temoin au niveau du document et on regarde ce qui lui
    parvient.
    """

    item = _attention(7)
    spy = ('(function(){window.__seen=[];'
           'document.addEventListener("keydown",function(e){window.__seen.push(e.key)});'
           'return "ok"})()')
    press = ('(function(k){return function(){'
             'var c=document.querySelector(".pa-card");if(!c)return "absente";'
             'c.dispatchEvent(new KeyboardEvent("keydown",{key:k,bubbles:true}));'
             'return "ok"}})')
    out = _drive(tmp_path, [
        {"a": "open", "tabs": 1, "width": 1440, "height": 900},
        {"a": "status", "value": _status(_background(7, [item])), "waitMs": 1500},
        {"a": "eval", "tab": 0, "expr": spy},
        {"a": "eval", "tab": 0, "expr": press + '("a")()'},
        {"a": "eval", "tab": 0, "expr": press + '("F9")()'},
        {"a": "eval", "tab": 0, "expr": "window.__seen"},
        {"a": "eval", "tab": 0, "expr": press + '("Escape")()'},
        {"a": "eval", "tab": 0, "expr": "window.__seen"},
    ])
    before_escape = out["reads"][3]
    after_escape = out["reads"][5]

    # Les touches ordinaires traversent : la page garde ses raccourcis.
    assert before_escape == ["a", "F9"], before_escape
    # Echap, lui, est traite ici et ne remonte pas.
    assert after_escape == ["a", "F9"], after_escape
