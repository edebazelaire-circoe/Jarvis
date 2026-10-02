"""Le rail de capture du bord gauche, mesuré dans un vrai navigateur (session-context-recording, Slice 10).

On compose la page **telle que `ControlCenter.index` la sert**, on la charge
dans Chrome sans tête à une taille imposée, et l'on relève des rectangles, des
attributs ARIA et des styles **calculés**. Le relais `/api/captures/*` est
remplacé dans la page par un double en mémoire (`window.__cap`, voir
`_capture_rail_browser.mjs`) : la chaîne réelle jusqu'à Core est prouvée par
`test_capture_relay.py` et par la validation en direct de la Slice.

Ce que ce fichier épingle :

- placement et non-recouvrement, à 1440 px et à 375 px (et entre les deux),
  Bare Hands monté (éteint ou allumé : même géométrie) ou absent : jamais sur
  la palette, le contrôle Bare Hands, le bouton de mode du bas-gauche,
  l'indication vocale, le dock, les pastilles, la carte de présentation ;
- groupe séparé : aucun `data-bh-tool` dans le rail, aucune commande de
  capture dans la palette ;
- clavier : un arrêt de tabulation, flèches, Début/Fin, Entrée et Espace ;
- un démarrage refusé revient visiblement, avec sa phrase et son code ;
- statut perdu : « état inconnu », rien d'actif, aucun démarrage ;
- audio + écran concurrents, arrêt indépendant, capture d'écran pendant les deux ;
- arrêt bloqué et interruption venue de Core visibles ;
- mouvement réduit : plus rien ne respire ni ne balaie, le chronomètre reste.
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
HARNESS = Path(__file__).parent / "_capture_rail_browser.mjs"

CHROME_CANDIDATES = (
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
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
    """La page servie, composée par la même chaîne de marqueurs que `ControlCenter.index`
    (copie délibérée de la fonction des autres harnais : un fichier de test autonome)."""

    html = (RUNTIME / "control_center.html").read_text(encoding="utf-8")
    pairs = [
        (getattr(cc, name), getattr(cc, name.replace("_MARKER", "_FILE")))
        for name in dir(cc)
        if name.endswith("_SCRIPT_MARKER") and hasattr(cc, name.replace("_MARKER", "_FILE"))
    ]
    for marker, filename in pairs:
        html = html.replace(marker, (RUNTIME / filename).read_text(encoding="utf-8"))
    assert not [m for m, _ in pairs if m in html], "marqueurs non remplacés"
    html = re.sub(r'<iframe class="face"[^>]*></iframe>', '<div class="face"></div>', html)
    out = tmp_path / "served.html"
    out.write_text(html, encoding="utf-8")
    return out


def _drive(tmp_path: Path, plan: list) -> list:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    done = subprocess.run(
        [node, str(HARNESS), str(_served_page(tmp_path)), chrome, json.dumps(plan)],
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


#: Bare Hands absent : son module ne s'est pas monté (pas de contrôle, pas de palette).
BH_ABSENT = ("document.getElementById('barehandsHud').textContent='';"
             "document.getElementById('barehandsPalette').textContent='';")
#: Bare Hands allumé : la palette perd sa veille (même géométrie, autre opacité).
BH_LIVE = "document.getElementById('barehandsPalette').setAttribute('data-bh-live','true');"


def _presentation_card() -> str:
    background = {"seq": 7, "unread": 1, "counts": {"attention": 1}, "attention": [{
        "seq": 7, "ts": "2026-09-24T10:00:00+00:00",
        "label": "Une affirmation est contredite par une source vérifiée", "detail": "2 sources · confiance élevée",
        "attention": {"attention_id": "att-1", "category": "contradiction", "severity": "warning", "band": "high",
                      "claim_id": "c", "topic_id": "t", "source_count": 2,
                      "evidence": [{"source_id": "s", "locator": "doc:x", "title": "Bilan", "resource_id": ""}],
                      "resource_ids": []}}]}
    return f"window.JarvisPresentationAttentionControl.gate({json.dumps(background)});"


def _iso(seconds_ago: int) -> str:
    return f"new Date(Date.now()-{seconds_ago * 1000}).toISOString()"


#: Attendre que le rail ait **relu** le statut (deux sondages complets après
#: la mutation du double) plutôt qu'un délai fixe : sous charge, un délai fixe
#: laissait passer la mutation entre deux sondages.
POLLED = {"eval": "(async()=>{const c=()=>window.__cap.calls.filter(x=>x.method==='GET').length;"
                  "const s=c(),t0=Date.now();while(c()<s+2&&Date.now()-t0<8000)"
                  "await new Promise(r=>setTimeout(r,50));await new Promise(r=>setTimeout(r,150))})()"}


def _open(channel: str, seconds_ago: int = 5, state: str = "active") -> str:
    return (f"window.__cap.open.push({{capture_id:'jcap_{channel}_x',channel:'{channel}',mode:'continuous',"
            f"state:'{state}',created_at:{_iso(seconds_ago + 1)},activated_at:{_iso(seconds_ago)},"
            f"stop_requested_at:null}});")


# ==========================================================================
# 1. La place
# ==========================================================================

SIZES = [(1440, 900), (1280, 720), (1280, 600), (1024, 640), (700, 600), (500, 700), (375, 667), (375, 560)]


@pytest.mark.parametrize("bare_hands", ["off", "on", "absent"])
def test_le_rail_ne_recouvre_aucune_commande_a_aucune_taille(tmp_path, bare_hands):
    setup = {"off": "", "on": BH_LIVE, "absent": BH_ABSENT}[bare_hands]
    plan = [{"width": w, "height": h, "toast": True,
             "actions": [{"eval": setup + _presentation_card()}, {"wait": 400}, {"read": "seen"}]}
            for w, h in SIZES]
    for (width, height), step in zip(SIZES, _drive(tmp_path, plan)):
        seen = step["reads"]["seen"]
        rail, where = seen["rail"], (width, height, bare_hands)
        assert rail, f"rail absent {where}"
        assert seen["fits"] == "true", (where, seen["slot"])
        assert rail["l"] >= 0 and rail["t"] >= 0, where
        assert rail["r"] <= width and rail["b"] <= height, (where, rail)
        if bare_hands == "absent":
            assert seen["slot"] == "alone" and not (seen["palette"] or {}).get("h"), where
        else:
            assert seen["palette"] and seen["bhHud"], f"Bare Hands non monté : le test ne prouve rien {where}"
            assert seen["slot"] in ("below", "beside", "beside-low"), where
        for name in ("palette", "bhHud", "modeBtn", "hint", "dock", "pills", "card"):
            # Sous ~410 px de large la pile des notifications (`.toasts`, rang 70,
            # `width:min(340px,100vw - 36px)` ancrée à droite) couvre toute la
            # largeur : la carte de présentation y passe déjà par-dessus la
            # palette (constat préexistant, 375x560). Elle est au-dessus du rail
            # et transitoire ; on n'exige donc rien d'impossible à cette largeur.
            if name == "card" and width < 412:
                continue
            assert _overlap(rail, seen.get(name)) is None, (where, name, rail, seen.get(name))
        for item in seen["topbar"]:
            assert _overlap(rail, item) is None, (where, "topbar", rail, item)
        # Le bouton de mode reste cliquable : rien ne le couvre, ni lui ni ses voisins.
        assert seen["modeBtn"], where


def test_a_pleine_largeur_le_rail_prolonge_la_colonne_sous_la_palette(tmp_path):
    seen = _drive(tmp_path, [{"width": 1440, "height": 900}])[0]["reads"]["end"]
    rail, palette, strip = seen["rail"], seen["palette"], seen["strip"]
    assert seen["slot"] == "below"
    # Même colonne : même bord gauche, même largeur que la palette.
    assert round(rail["l"]) == round(palette["l"]) == 18 and round(rail["w"]) == round(palette["w"])
    # Sous elle, séparé par le filet et un blanc franc.
    assert 8 <= rail["t"] - palette["b"] <= 14, (rail, palette)
    # Même géométrie d'icône que la palette (44 px), même bande.
    for button in seen["buttons"].values():
        assert round(button["box"]["w"]) == 44 and round(button["box"]["h"]) == 44
    assert strip["w"] == seen["paletteStrip"]["w"], (strip, seen["paletteStrip"])
    assert seen["z"] == "30"


def test_sur_ecran_etroit_les_icones_se_resserrent_comme_la_palette(tmp_path):
    seen = _drive(tmp_path, [{"width": 375, "height": 667}])[0]["reads"]["end"]
    for button in seen["buttons"].values():
        assert round(button["box"]["w"]) == 38


def test_groupe_separe_aucun_outil_bare_hands_dans_le_rail(tmp_path):
    seen = _drive(tmp_path, [{"width": 1440, "height": 900}])[0]["reads"]["end"]
    assert seen["bhToolsInRail"] == 0
    assert seen["captureInPalette"] == 0
    assert seen["toolbar"] == {"role": "toolbar", "label": "Capture : capture d’écran et enregistrements",
                               "orientation": "vertical"}
    assert sorted(seen["buttons"]) == ["audio", "screen", "screenshot"]
    for button in seen["buttons"].values():
        assert button["tag"] == "BUTTON" and button["type"] == "button"
        assert button["label"] and button["label"] == button["title"]


# ==========================================================================
# 2. Le clavier
# ==========================================================================


def test_le_clavier_traverse_le_rail_et_entree_espace_agissent(tmp_path):
    plan = [{"width": 1440, "height": 900, "actions": [
        # La palette a un arrêt de tabulation ; Tab depuis lui arrive sur le rail.
        {"eval": "document.querySelector('#barehandsPaletteStrip [tabindex=\"0\"]').focus()"},
        {"key": "Tab"}, {"read": "tab"},
        {"key": "ArrowDown"}, {"read": "down"},
        {"key": "End"}, {"read": "end"},
        {"key": "Home"}, {"read": "home"},
        {"key": "ArrowUp"}, {"read": "wrap"},
        {"key": "Home"}, {"key": "ArrowDown"}, {"key": "Enter"}, {"wait": 600}, {"read": "enter"},
        {"key": "ArrowDown"}, {"key": " "}, {"wait": 600}, {"read": "space"},
    ]}]
    r = _drive(tmp_path, plan)[0]["reads"]
    assert r["tab"]["focus"]["control"] == "screenshot"
    assert r["down"]["focus"]["control"] == "audio"
    assert r["end"]["focus"]["control"] == "screen"
    assert r["home"]["focus"]["control"] == "screenshot"
    assert r["wrap"]["focus"]["control"] == "screen"
    # Un seul arrêt de tabulation dans la barre.
    assert [b["tabindex"] for b in r["down"]["buttons"].values()].count("0") == 1
    assert r["enter"]["calls"] == ['POST /api/captures/start {"channel":"audio"}']
    assert r["enter"]["buttons"]["audio"]["pressed"] == "true"
    assert r["space"]["calls"][-1] == 'POST /api/captures/start {"channel":"screen"}'
    assert r["space"]["buttons"]["screen"]["pressed"] == "true"
    assert r["space"]["focus"]["control"] == "screen", "le focus reste où il était"


# ==========================================================================
# 3. Vérité de Core
# ==========================================================================


def test_un_demarrage_refuse_revient_visiblement_avec_sa_raison(tmp_path):
    refuse = ("window.__cap.refuse.screen={status:503,code:'source_unavailable',"
              "message:\"screen recording needs ffmpeg: install the 'capture' extra\"};"
              "window.__cap.hold.screen=true;")
    plan = [{"width": 1440, "height": 900, "actions": [
        {"eval": refuse}, {"click": "[data-capture-control=screen]"}, POLLED, {"read": "waiting"},
        {"eval": "window.__cap.release.screen()"}, {"wait": 500}, {"read": "refused"},
        {"key": "Escape"}, {"wait": 200}, {"read": "dismissed"},
    ]}]
    out = _drive(tmp_path, plan)[0]
    r = out["reads"]
    waiting = r["waiting"]["buttons"]["screen"]
    # L'attente se voit : état, balayage, compteur — et le bouton n'est PAS enfoncé.
    assert waiting["state"] == "starting" and waiting["pressed"] == "false"
    assert waiting["sweepShown"] and re.fullmatch(r"\d+ s", waiting["time"]), waiting
    refused = r["refused"]["buttons"]["screen"]
    assert refused["state"] == "error" and refused["pressed"] == "false" and refused["disabled"] == "false"
    assert refused["badge"] == "!" and refused["badgeShown"]
    assert refused["glyph"] == "screen", "pas de carré d'arrêt sur un canal fermé"
    assert refused["describedby"] == "captureRailNote"
    note = r["refused"]["note"]
    assert not note["hidden"] and note["tone"] == "bad"
    assert note["text"].startswith("Enregistrement d’écran non démarré — ffmpeg manquant")
    assert "(source_unavailable)" in note["text"]
    assert _overlap(note["box"], r["refused"]["palette"]) is None
    # Le refus est journalisé, à la console, avec son code.
    assert any("capture_rail.start_failed" in line and "source_unavailable" in line for line in out["console"])
    # Échap ferme la note et rend le bouton au repos ; le statut, lui, n'a pas bougé.
    assert r["dismissed"]["note"]["hidden"]
    assert r["dismissed"]["buttons"]["screen"]["state"] == "idle"


def test_un_refus_qui_passe_par_une_ligne_ouverte_n_est_pas_une_interruption(tmp_path):
    """Constaté en direct contre Core : un démarrage refusé crée sa ligne
    (`starting` → `stopping`) avant de finir `failed`, `start_failed`. Le
    sondage la voit passer ; la note doit rester « non démarré », pas
    « interrompu »."""

    refuse = "window.__cap.refuse.audio={status:503,code:'source_unavailable',message:'no mic',viaRow:2500};"
    plan = [{"width": 1440, "height": 900, "actions": [
        {"eval": refuse}, {"click": "[data-capture-control=audio]"}, POLLED, {"read": "during"},
        {"wait": 2500}, {"read": "after"},
    ]}]
    out = _drive(tmp_path, plan)[0]
    r = out["reads"]
    assert r["during"]["buttons"]["audio"]["state"] == "starting", "un démarrage en vol reste un démarrage"
    assert r["after"]["buttons"]["audio"]["state"] == "error"
    assert r["after"]["buttons"]["audio"]["pressed"] == "false"
    assert r["after"]["note"]["text"] == "Enregistrement audio non démarré — micro indisponible (source_unavailable)."
    assert not any("capture_interrupted" in line for line in out["console"])


def test_le_chronometre_vient_de_core_pas_du_clic(tmp_path):
    plan = [{"width": 1440, "height": 900, "actions": [
        {"eval": _open("audio", seconds_ago=125)}, POLLED, {"read": "seen"}]}]
    audio = _drive(tmp_path, plan)[0]["reads"]["seen"]["buttons"]["audio"]
    assert audio["state"] == "active" and audio["pressed"] == "true"
    assert audio["time"] in ("2:05", "2:06", "2:07", "2:08", "2:09"), audio["time"]
    # Le canal reste reconnaissable (micro), l'arrêt est une pastille lisible à part.
    assert audio["glyph"] == "audio", "un canal ouvert garde son dessin"
    assert audio["stopShown"] and round(audio["stopBox"]["w"]) >= 18, audio["stopBox"]
    assert audio["railContent"] != "none", "le rail de forme de l'ouvert"
    # La durée est dans la description, pas dans le nom (réannoncé sinon).
    assert audio["label"] == "Arrêter l’enregistrement audio"
    assert audio["describedby"] == audio["detailId"] and "en cours depuis 2:0" in audio["detail"]


def test_statut_perdu_etat_inconnu_puis_retour(tmp_path):
    plan = [{"width": 1440, "height": 900, "actions": [
        {"eval": _open("audio")}, POLLED, {"read": "live"},
        {"eval": "window.__cap.down=true"}, POLLED, {"read": "lost"},
        {"click": "[data-capture-control=screen]"}, {"wait": 300}, {"read": "clicked"},
        {"eval": "window.__cap.down=false"}, POLLED, {"read": "back"},
    ]}]
    out = _drive(tmp_path, plan)[0]
    r = out["reads"]
    assert r["live"]["buttons"]["audio"]["pressed"] == "true"
    lost = r["lost"]["buttons"]
    for name in ("audio", "screen", "screenshot"):
        assert lost[name]["state"] == "unknown", name
        assert lost[name]["pressed"] in ("false", None), name
        assert lost[name]["badge"] == "?" and lost[name]["badgeShown"], name
        assert lost[name]["border"] == "dashed", name
        assert lost[name]["time"] == "", "aucun chronomètre sans vérité"
    assert lost["screen"]["disabled"] == "true" and lost["screenshot"]["disabled"] == "true"
    # L'enregistrement que l'on savait ouvert peut encore être arrêté.
    assert lost["audio"]["disabled"] == "false" and "tenter l’arrêt" in lost["audio"]["label"]
    assert r["lost"]["caption"] == "ÉTAT ?"
    assert r["clicked"]["calls"] == [], "aucun démarrage pendant la perte"
    assert r["back"]["buttons"]["audio"]["state"] == "active"
    assert any("capture_rail.status_lost" in line for line in out["console"])
    assert any("capture_rail.status_restored" in line for line in out["console"])


def test_audio_et_ecran_concurrents_arret_independant_et_capture_pendant(tmp_path):
    plan = [{"width": 1440, "height": 900, "actions": [
        {"click": "[data-capture-control=audio]"}, {"wait": 500},
        {"click": "[data-capture-control=screen]"}, {"wait": 500}, {"read": "both"},
        {"click": "[data-capture-control=screenshot]"}, {"wait": 400}, {"read": "shot"},
        {"click": "[data-capture-control=audio]"}, {"wait": 600}, {"read": "audio_stopped"},
        {"wait": 2600}, {"read": "later"},
    ]}]
    r = _drive(tmp_path, plan)[0]["reads"]
    both = r["both"]["buttons"]
    assert both["audio"]["pressed"] == "true" and both["screen"]["pressed"] == "true"
    assert r["both"]["caption"] == "REC 2"
    # Deux canaux ouverts restent distincts : micro et écran, chacun sa pastille d'arrêt.
    assert (both["audio"]["glyph"], both["screen"]["glyph"]) == ("audio", "screen")
    assert both["audio"]["stopShown"] and both["screen"]["stopShown"]
    assert not r["both"]["buttons"]["screenshot"]["stopShown"]
    assert r["shot"]["buttons"]["screenshot"]["state"] == "done"
    assert r["shot"]["buttons"]["screenshot"]["glyph"] == "done"
    assert r["shot"]["announce"] == "Capture d’écran enregistrée."
    assert both["audio"]["pressed"] == r["shot"]["buttons"]["audio"]["pressed"] == "true"
    stopped = r["audio_stopped"]
    assert stopped["calls"][-1] == "POST /api/captures/jcap_audio_1/stop"
    assert stopped["buttons"]["audio"]["state"] == "idle" and stopped["buttons"]["audio"]["pressed"] == "false"
    assert stopped["buttons"]["screen"]["state"] == "active", "arrêter l'audio ne touche pas l'écran"
    assert r["later"]["buttons"]["screenshot"]["state"] == "idle", "la confirmation est brève"
    assert stopped["note"]["hidden"], "un arrêt demandé ici n'est pas une interruption"


def test_un_arret_bloque_se_reessaie_depuis_le_bouton(tmp_path):
    stuck = (_open("screen", state="stopping")
             + "window.__cap.stuck.push({capture_id:'jcap_screen_x',error_code:'store_unavailable',reason:'db'});")
    plan = [{"width": 1440, "height": 900, "actions": [
        {"eval": stuck}, POLLED, {"read": "stuck"},
        {"click": "[data-capture-control=screen]"}, {"wait": 600}, {"read": "retried"},
    ]}]
    r = _drive(tmp_path, plan)[0]["reads"]
    screen = r["stuck"]["buttons"]["screen"]
    assert screen["state"] == "stuck" and screen["badge"] == "!" and screen["disabled"] == "false"
    assert "arrêt bloqué (store_unavailable)" in screen["label"]
    assert r["stuck"]["caption"] == "REC 1 !", "l'enregistrement reste dit, avec la marque d'erreur"
    assert r["retried"]["calls"] == ["POST /api/captures/jcap_screen_x/stop"]
    assert r["retried"]["buttons"]["screen"]["state"] == "idle"


def test_une_interruption_venue_de_core_ne_passe_pas_en_silence(tmp_path):
    lose = ("const c=window.__cap.open.pop();window.__cap.recent.unshift(Object.assign({},c,"
            "{state:'partial',error_code:'source_lost',stop_reason:'source_lost'}));")
    plan = [{"width": 1440, "height": 900, "actions": [
        {"eval": _open("audio")}, POLLED, {"eval": lose}, POLLED, {"read": "seen"}]}]
    out = _drive(tmp_path, plan)[0]
    seen = out["reads"]["seen"]
    assert seen["buttons"]["audio"]["state"] == "error"
    assert seen["note"]["text"] == "Enregistrement audio interrompu — source perdue en cours de route (source_lost)."
    assert any("capture_rail.capture_interrupted" in line for line in out["console"])


# ==========================================================================
# 4. Mouvement réduit, contraste
# ==========================================================================


def test_le_mouvement_reduit_arrete_la_respiration_et_le_balayage(tmp_path):
    actions = [{"eval": _open("audio") + "window.__cap.hold.screen=true;"}, POLLED,
               {"click": "[data-capture-control=screen]"}, POLLED, {"read": "seen"}]
    normal, reduced = _drive(tmp_path, [
        {"width": 1440, "height": 900, "actions": actions},
        {"width": 1440, "height": 900, "reducedMotion": True, "actions": actions},
    ])
    n, r = normal["reads"]["seen"]["buttons"], reduced["reads"]["seen"]["buttons"]
    assert n["audio"]["railAnimation"] == "crBreathe" and n["screen"]["sweepAnimation"] == "crSweep"
    assert r["audio"]["railAnimation"] == "none" and r["screen"]["sweepAnimation"] == "none"
    # L'information reste : le chronomètre et la barre d'attente sont là, immobiles.
    assert r["audio"]["time"] and r["screen"]["sweepShown"] and r["screen"]["time"]


def test_en_contraste_force_les_etats_restent_lisibles(tmp_path):
    seen = _drive(tmp_path, [{"width": 1440, "height": 900, "forcedColors": True, "actions": [
        {"eval": _open("audio") + "window.__cap.down=false"}, POLLED, {"read": "seen"}]}])[0]["reads"]["seen"]
    audio = seen["buttons"]["audio"]
    assert audio["pressed"] == "true" and audio["glyph"] == "audio" and audio["railContent"] != "none"
    assert audio["stopShown"]


# ==========================================================================
# 5. Accessibilité (axe-core, si fourni)
# ==========================================================================


def test_axe_ne_trouve_aucune_violation_dans_le_rail(tmp_path):
    axe = os.environ.get("JARVIS_AXE_JS")
    if not axe or not Path(axe).is_file():
        pytest.skip("JARVIS_AXE_JS absent (axe-core n'est pas une dépendance du dépôt)")
    refuse = "window.__cap.refuse.screen={status:503,code:'source_unavailable',message:'x'};"
    plan = [{"width": w, "height": h, "actions": [
        {"axe": "idle", "file": axe},
        {"eval": _open("audio") + refuse}, POLLED, {"click": "[data-capture-control=screen]"},
        {"wait": 600}, {"axe": "busy", "file": axe},
        {"eval": "window.__cap.down=true"}, POLLED, {"axe": "unknown", "file": axe},
    ]} for w, h in ((1440, 900), (375, 667))]
    for step in _drive(tmp_path, plan):
        for name, violations in step["reads"].items():
            assert violations == [], (name, violations)


@pytest.mark.parametrize("width,height", [(1440, 900), (375, 667)])
def test_la_note_d_erreur_reste_dans_l_ecran_et_hors_du_dock(tmp_path, width, height):
    """Constaté en direct à 375 px : la note glissait sous le dock (rang 32)."""

    refuse = "window.__cap.refuse.screen={status:503,code:'source_unavailable',message:'no screen'};"
    plan = [{"width": width, "height": height, "actions": [
        {"eval": refuse}, {"click": "[data-capture-control=screen]"}, {"wait": 800}, {"read": "seen"}]}]
    seen = _drive(tmp_path, plan)[0]["reads"]["seen"]
    note = seen["note"]["box"]
    assert not seen["note"]["hidden"]
    assert note["l"] >= 0 and note["r"] <= width and note["b"] <= height, note
    for name in ("dock", "palette", "bhHud", "modeBtn"):
        assert _overlap(note, seen.get(name)) is None, (name, note, seen.get(name))


#: L'indicateur de scène (`#sceneLayer>.sc-status`) lève le bouton de mode d'un cran :
#: c'est la page du direct, où la QA a mesuré le rail mordant de 4 px sur ce bouton.
SCENE_STATUS = ("(()=>{const s=document.createElement('div');s.className='sc-status';s.textContent='Scène';"
                "s.style.cssText='position:absolute;left:18px;bottom:18px;padding:6px 10px';"
                "(document.getElementById('sceneLayer')||document.body).appendChild(s)})();")


@pytest.mark.parametrize("bare_hands", ["off", "on"])
def test_a_320_x_568_le_rail_ne_mord_pas_sur_le_bouton_de_mode(tmp_path, bare_hands):
    """MINOR-3 : 320 × 568, Bare Hands monté, indicateur de scène présent."""

    setup = {"off": "", "on": BH_LIVE}[bare_hands]
    plan = [{"width": 320, "height": 568, "actions": [
        {"eval": setup + SCENE_STATUS}, POLLED, {"eval": "window.JarvisCaptureRail.place()"}, {"read": "seen"}]}]
    out = _drive(tmp_path, plan)[0]
    seen = out["reads"]["seen"]
    assert seen["palette"] and seen["bhHud"], "Bare Hands non monté : le test ne prouve rien"
    assert seen["fits"] == "true", (seen["slot"], seen["rail"], seen["modeBtn"])
    for name in ("palette", "bhHud", "modeBtn", "hint", "dock"):
        assert _overlap(seen["rail"], seen.get(name)) is None, (name, seen["rail"], seen.get(name))
    assert seen["rail"]["t"] >= 0 and seen["rail"]["b"] <= 568
    assert not any("no_free_slot" in line for line in out["console"]), out["console"]


# ==========================================================================
# 6. La pastille d'arrêt (rework QA mineur)
# ==========================================================================

#: Le coin haut-droit de la pastille de l'audio, 3 px vers l'intérieur (dans son
#: arrondi) : qui reçoit le pointeur là, et où est le bouton du dessus.
CHIP_HIT = ("(()=>{const b=document.querySelector('#captureRail [data-capture-control=audio]');"
            "const c=b.querySelector('.cr-stop').getBoundingClientRect();"
            "const a=document.querySelector('#captureRail [data-capture-control=screenshot]').getBoundingClientRect();"
            "const k=3,el=document.elementFromPoint(c.right-k,c.top+k);"
            "const box=r=>({l:r.left,t:r.top,r:r.right,b:r.bottom,w:r.width,h:r.height});"
            "return {chip:box(c),above:box(a),button:box(b.getBoundingClientRect()),"
            "inChip:!!(el&&el.closest('.cr-stop')),"
            "control:el&&el.closest('[data-capture-control]')&&el.closest('[data-capture-control]')"
            ".getAttribute('data-capture-control')}})()")


@pytest.mark.parametrize("width,height", [(1440, 900), (375, 667)])
def test_un_clic_au_coin_de_la_pastille_arrete_la_capture(tmp_path, width, height):
    """La pastille dépasse du bouton : son coin n'est pas une zone morte, il
    arrête la capture ; elle touche le bouton du dessus sans le chevaucher ;
    pendant l'arrêt elle reste, estompée (mutant N24)."""

    plan = [{"width": width, "height": height, "actions": [
        {"eval": _open("audio") + "window.__cap.hold['stop:audio']=true;"}, POLLED,
        {"value": "hit", "expr": CHIP_HIT},
        {"corner": "#captureRail [data-capture-control=audio] .cr-stop", "inset": 3}, {"wait": 400},
        {"read": "stopping"},
        {"eval": "window.__cap.release['stop:audio']()"}, POLLED, {"read": "stopped"},
    ]}]
    r = _drive(tmp_path, plan)[0]["reads"]
    hit = r["hit"]
    assert hit["inChip"] and hit["control"] == "audio", hit
    # Hors du bouton, mais à lui : 5 ou 6 px de dépassement, selon la largeur.
    assert hit["chip"]["r"] > hit["button"]["r"] and hit["chip"]["t"] < hit["button"]["t"], hit
    assert _overlap(hit["chip"], hit["above"]) is None, hit
    assert hit["chip"]["t"] >= hit["above"]["b"] - 0.5, hit
    stopping = r["stopping"]
    assert stopping["calls"] == ["POST /api/captures/jcap_audio_x/stop"]
    audio = stopping["buttons"]["audio"]
    assert audio["state"] == "stopping" and audio["stopShown"], audio
    assert float(audio["stopOpacity"]) == pytest.approx(0.5), audio["stopOpacity"]
    done = r["stopped"]["buttons"]["audio"]
    assert done["state"] == "idle" and not done["stopShown"]


def test_statut_perdu_la_capture_connue_porte_sa_pastille_et_garde_son_point_d_interrogation(tmp_path):
    marks = ("(()=>{const b=document.querySelector('#captureRail [data-capture-control=audio]');"
             "const box=el=>{const r=el.getBoundingClientRect();return {l:r.left,t:r.top,r:r.right,b:r.bottom}};"
             "return {chip:box(b.querySelector('.cr-stop')),badge:box(b.querySelector('.cr-badge'))}})()")
    plan = [{"width": 1440, "height": 900, "actions": [
        {"eval": _open("audio")}, POLLED, {"eval": "window.__cap.down=true"}, POLLED,
        {"read": "lost"}, {"value": "marks", "expr": marks},
        {"click": "[data-capture-control=audio]"}, {"wait": 400}, {"read": "stopped"},
    ]}]
    r = _drive(tmp_path, plan)[0]["reads"]
    audio = r["lost"]["buttons"]["audio"]
    assert audio["state"] == "unknown" and audio["disabled"] == "false"
    assert audio["stopShown"], "le clic arrête : la pastille le dit"
    assert audio["badge"] == "?" and audio["badgeShown"]
    assert _overlap(r["marks"]["chip"], r["marks"]["badge"]) is None, r["marks"]
    # Le double est injoignable : l'arrêt échoue, la capture reste « connue ouverte ».
    assert r["stopped"]["calls"] == ["POST /api/captures/jcap_audio_x/stop"]
    assert r["stopped"]["buttons"]["audio"]["stopShown"]
