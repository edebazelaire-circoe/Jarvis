"""Rail de capture du bord gauche, modèle pur exécuté par node (session-context-recording, Slice 10).

Ce que ce fichier épingle :

- **un état peint par situation** de chaque canal — repos, démarrage, actif,
  arrêt, arrêt bloqué, erreur, inconnu — et pour la capture d'écran repos,
  en cours, faite, erreur, inconnu ;
- **seul Core peut peindre un canal actif** : une demande en vol, un refus,
  une capture « connue » d'avant la perte du statut n'enfoncent jamais un
  bouton (`aria-pressed`) ;
- le chronomètre part de `activated_at` rendu par Core, pas de l'heure locale ;
  il se fige à `stop_requested_at` ;
- audio et écran sont **indépendants** ;
- statut perdu : « état inconnu », aucun démarrage, mais l'arrêt d'une capture
  que l'on savait ouverte reste proposé ;
- les textes d'erreur sont courts, en français, et gardent leur code ;
- le placement : sous la colonne Bare Hands quand ça tient, à côté sinon, en
  haut de la colonne quand Bare Hands est absent ;
- le module est inséré dans la page servie, son emplacement est déclaré après
  la palette et **hors** d'elle, et il n'emprunte rien à `BH.TOOL`.

Le DOM et le réseau sont prouvés dans Chrome par `test_capture_rail_browser.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import (
    BAREHANDS_HUD_SCRIPT_MARKER,
    CAPTURE_RAIL_SCRIPT_FILE,
    CAPTURE_RAIL_SCRIPT_MARKER,
    INTERACTION_MODE_SCRIPT_MARKER,
)

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
MODULE = RUNTIME / CAPTURE_RAIL_SCRIPT_FILE
PAGE_HTML = RUNTIME / "control_center.html"
SCENE_PAGE = RUNTIME / "control_center_scene_page.js"

T0 = "2026-10-01T10:00:00+00:00"
NOW = "Date.parse('2026-10-01T10:01:05Z')"


def run(tmp_path: Path, body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "rail.js"
    script.write_text(
        f"const M=require({json.dumps(str(MODULE))});\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        f"const NOW={NOW};\n"
        "const cap=(channel,state,extra)=>Object.assign({capture_id:'jcap_'+channel,channel,mode:'continuous',"
        f"state,created_at:'{T0}',activated_at:'2026-10-01T10:00:05+00:00',stop_requested_at:null}},extra||{{}});\n"
        "const st=(captures,stuck,recent)=>({captures:captures||[],stuck:stuck||[],recent:recent||[]});\n"
        + body,
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8",
                          timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ------------------------------------------------------------ états des canaux


def test_un_canal_au_repos_propose_de_demarrer_et_n_est_pas_enfonce(tmp_path):
    v = run(tmp_path, "out(M.viewOf({status:st(),reachable:true,now:NOW}).controls)")
    for channel in ("audio", "screen"):
        assert v[channel]["state"] == "idle"
        assert v[channel]["pressed"] is False
        assert v[channel]["action"] == "start"
        assert v[channel]["timer"] == ""
    assert v["audio"]["label"] == "Démarrer l’enregistrement audio"
    assert v["screen"]["label"] == "Démarrer l’enregistrement d’écran"
    # La capture d'écran est momentanée : pas d'état enfoncé du tout.
    assert v["screenshot"]["pressed"] is None and v["screenshot"]["action"] == "shot"


def test_l_actif_vient_de_core_et_son_chronometre_de_activated_at(tmp_path):
    v = run(tmp_path, "out(M.viewOf({status:st([cap('audio','active')]),reachable:true,now:NOW}).controls.audio)")
    assert v["state"] == "active" and v["pressed"] is True and v["action"] == "stop"
    # 10:00:05 -> 10:01:05 : une minute, quelle que soit l'heure du clic.
    assert v["seconds"] == 60 and v["timer"] == "1:00"
    assert v["label"] == "Arrêter l’enregistrement audio — en cours depuis 1:00"
    assert v["captureId"] == "jcap_audio"


def test_sans_activated_at_le_chronometre_part_de_created_at(tmp_path):
    v = run(tmp_path, "out(M.viewOf({status:st([cap('screen','active',{activated_at:null})]),"
                      "reachable:true,now:NOW}).controls.screen)")
    assert v["seconds"] == 65 and v["timer"] == "1:05"


def test_une_demande_en_vol_ne_peint_jamais_un_canal_actif(tmp_path):
    v = run(tmp_path, "out(M.viewOf({status:st(),reachable:true,now:NOW,"
                      "pending:{audio:{kind:'start',since:NOW-3000}}}).controls.audio)")
    assert v["state"] == "starting"
    assert v["pressed"] is False, "le clic n'est pas la vérité"
    assert v["action"] is None
    # RÈGLE ZÉRO : l'attente dit depuis combien de temps elle dure.
    assert v["timer"] == "3 s"


def test_core_gagne_sur_une_demande_en_vol(tmp_path):
    v = run(tmp_path, "out(M.viewOf({status:st([cap('audio','active')]),reachable:true,now:NOW,"
                      "pending:{audio:{kind:'start',since:NOW}}}).controls.audio)")
    assert v["state"] == "active" and v["pressed"] is True


def test_un_demarrage_refuse_revient_au_repos_avec_la_marque_d_erreur(tmp_path):
    v = run(tmp_path, "out(M.viewOf({status:st(),reachable:true,now:NOW,"
                      "failure:{screen:{code:'source_unavailable',text:'écran indisponible'}}}).controls.screen)")
    assert v["state"] == "error"
    assert v["pressed"] is False
    assert v["action"] == "start", "réessayer = redémarrer"
    assert v["code"] == "source_unavailable"
    assert "dernier essai : écran indisponible" in v["label"]


def test_l_arret_en_cours_fige_le_chronometre(tmp_path):
    v = run(tmp_path, "out(M.viewOf({status:st([cap('audio','stopping',"
                      "{stop_requested_at:'2026-10-01T10:00:35+00:00'})]),reachable:true,now:NOW}).controls.audio)")
    assert v["state"] == "stopping" and v["pressed"] is True and v["action"] is None
    assert v["seconds"] == 30


def test_un_arret_demande_ici_se_voit_avant_la_reponse(tmp_path):
    v = run(tmp_path, "out(M.viewOf({status:st([cap('audio','active')]),reachable:true,now:NOW,"
                      "pending:{audio:{kind:'stop',since:NOW,captureId:'jcap_audio'}}}).controls.audio)")
    assert v["state"] == "stopping" and v["action"] is None


def test_un_arret_bloque_est_une_erreur_dont_le_remede_est_d_arreter_encore(tmp_path):
    v = run(tmp_path, "out(M.viewOf({status:st([cap('screen','stopping')],"
                      "[{capture_id:'jcap_screen',error_code:'store_unavailable',reason:'db'}]),"
                      "reachable:true,now:NOW}).controls.screen)")
    assert v["state"] == "stuck"
    assert v["action"] == "stop"
    assert v["code"] == "store_unavailable"
    assert "arrêt bloqué" in v["label"] and "réessayer l’arrêt" in v["label"]


def test_un_demarrage_par_le_cerveau_se_voit_aussi(tmp_path):
    v = run(tmp_path, "out(M.viewOf({status:st([cap('audio','starting')]),reachable:true,now:NOW}).controls.audio)")
    assert v["state"] == "starting" and v["pressed"] is True and v["action"] == "stop"


# ------------------------------------------------------------ concurrence


def test_audio_et_ecran_sont_independants(tmp_path):
    v = run(tmp_path, r"""
      const both=M.viewOf({status:st([cap('audio','active'),cap('screen','active',
        {activated_at:'2026-10-01T10:00:45+00:00'})]),reachable:true,now:NOW});
      const audioOnly=M.viewOf({status:st([cap('audio','active')]),reachable:true,now:NOW});
      out({both:both.controls,caption:both.caption,recording:both.recording,audioOnly:audioOnly.controls});
    """)
    assert v["both"]["audio"]["state"] == v["both"]["screen"]["state"] == "active"
    assert v["both"]["audio"]["timer"] == "1:00" and v["both"]["screen"]["timer"] == "0:20"
    assert v["recording"] == 2 and v["caption"] == "REC 2"
    # Arrêter l'un ne touche pas l'autre : c'est Core qui le dit, canal par canal.
    assert v["audioOnly"]["audio"]["state"] == "active" and v["audioOnly"]["screen"]["state"] == "idle"
    # La capture d'écran reste une action indépendante, disponible pendant les deux.
    assert v["both"]["screenshot"]["action"] == "shot"


def test_une_capture_d_ecran_ponctuelle_n_occupe_pas_le_canal_ecran(tmp_path):
    v = run(tmp_path, "out(M.viewOf({status:st([cap('screen','active',{mode:'one_shot'})]),"
                      "reachable:true,now:NOW}).controls.screen)")
    assert v["state"] == "idle"


# ------------------------------------------------------------ statut perdu


def test_statut_perdu_etat_inconnu_sans_demarrage_ni_faux_actif(tmp_path):
    v = run(tmp_path, "const r=M.viewOf({status:st([cap('audio','active')]),reachable:false,now:NOW});"
                      "out({c:r.controls,caption:r.caption})")
    for name in ("audio", "screen", "screenshot"):
        assert v["c"][name]["state"] == "unknown", name
        assert v["c"][name]["pressed"] in (False, None), name
        assert v["c"][name]["action"] in (None, "stop"), name
    assert v["c"]["audio"]["timer"] == ""
    assert "état inconnu" in v["c"]["audio"]["label"]
    assert v["caption"] == "ÉTAT ?"


def test_statut_perdu_l_arret_d_une_capture_connue_reste_propose(tmp_path):
    v = run(tmp_path, "out(M.viewOf({status:null,reachable:false,now:NOW,"
                      "known:{audio:{capture_id:'jcap_audio'}}}).controls)")
    assert v["audio"]["state"] == "unknown" and v["audio"]["pressed"] is False
    assert v["audio"]["action"] == "stop" and v["audio"]["captureId"] == "jcap_audio"
    assert "tenter l’arrêt" in v["audio"]["label"]
    assert v["screen"]["action"] is None


def test_la_capture_d_ecran_confirme_brievement_puis_revient(tmp_path):
    v = run(tmp_path, r"""
      const s=st();
      out({busy:M.viewOf({status:s,reachable:true,now:NOW,pending:{screenshot:{since:NOW-1000}}}).controls.screenshot,
        done:M.viewOf({status:s,reachable:true,now:NOW,shotAt:NOW-1000}).controls.screenshot,
        after:M.viewOf({status:s,reachable:true,now:NOW,shotAt:NOW-M.TIMING.doneMs-1}).controls.screenshot,
        error:M.viewOf({status:s,reachable:true,now:NOW,failure:{screenshot:{code:'permission_denied',text:'x'}}}).controls.screenshot});
    """)
    assert v["busy"]["state"] == "busy" and v["busy"]["action"] is None and v["busy"]["timer"] == "1 s"
    assert v["done"]["state"] == "done" and v["done"]["label"].startswith("Capture d’écran enregistrée")
    assert v["after"]["state"] == "idle"
    assert v["error"]["state"] == "error" and v["error"]["action"] == "shot"


# ------------------------------------------------------------ textes


@pytest.mark.parametrize("code,control,expected", [
    ("source_unavailable", "audio", "micro indisponible"),
    ("source_unavailable", "screen", "écran indisponible"),
    ("permission_denied", "audio", "accès au micro refusé par Windows"),
    ("already_active", "screen", "déjà en cours"),
    ("storage_full", "audio", "disque plein"),
    ("core_unreachable", "audio", "Jarvis (Core) injoignable"),
    ("core_timeout", "screen", "pas de réponse à temps, issue inconnue"),
    ("unsupported_source", "screen", "aucune source de capture installée"),
    ("brand_new_code", "audio", "échec (brand_new_code)"),
])
def test_les_codes_deviennent_des_phrases_courtes(tmp_path, code, control, expected):
    said = run(tmp_path, f"out(M.refusalText({json.dumps(code)},'',{json.dumps(control)}))")
    assert said == expected


def test_ffmpeg_manquant_dit_comment_l_installer(tmp_path):
    said = run(tmp_path, "out(M.noteText('screen','non démarré','source_unavailable',"
                         "\"screen recording needs ffmpeg: install the 'capture' extra\"))")
    assert said.startswith("Enregistrement d’écran non démarré — ffmpeg manquant")
    assert "JARVIS_FFMPEG_EXE" in said and "(source_unavailable)" in said


def test_les_durees_s_ecrivent_en_minutes_puis_en_heures(tmp_path):
    v = run(tmp_path, "out([M.clock(0),M.clock(59),M.clock(61),M.clock(3600),M.clock(3725),"
                      "M.elapsedOf('nonsense',null,NOW)])")
    assert v == ["0:00", "0:59", "1:01", "1:00:00", "1:02:05", None]


# ------------------------------------------------------------ placement


def _slot(tmp_path, m: dict):
    return run(tmp_path, f"out(M.slotOf({json.dumps(m)}))")


COLUMN = {"left": 18, "top": 76, "right": 82, "bottom": 345}


def test_le_rail_se_pose_sous_la_colonne_quand_la_place_existe(tmp_path):
    s = _slot(tmp_path, {"vw": 1440, "vh": 900, "rail": {"w": 64, "h": 186}, "column": COLUMN,
                         "base": {"left": 18, "top": 76}, "obstacles": [
                             {"left": 18, "top": 818, "right": 195, "bottom": 878}]})
    assert s == {"mode": "below", "left": 18, "top": 355, "fits": True, "score": 0}


def test_un_ecran_court_le_fait_passer_a_cote_plutot_que_sur_le_bouton_de_mode(tmp_path):
    s = _slot(tmp_path, {"vw": 1280, "vh": 600, "rail": {"w": 64, "h": 186}, "column": COLUMN,
                         "base": {"left": 18, "top": 76}, "obstacles": [
                             {"left": 18, "top": 518, "right": 195, "bottom": 578}]})
    assert s["mode"] == "beside" and s["left"] == 82 and s["top"] == 76 and s["fits"]


def test_bare_hands_absent_le_rail_prend_le_haut_de_la_colonne(tmp_path):
    s = _slot(tmp_path, {"vw": 1440, "vh": 900, "rail": {"w": 64, "h": 186}, "column": None,
                         "base": {"left": 18, "top": 76}, "obstacles": []})
    assert s["mode"] == "alone" and (s["left"], s["top"]) == (18, 76)


def test_sans_aucune_place_libre_le_moindre_mal_est_choisi_et_dit(tmp_path):
    s = _slot(tmp_path, {"vw": 300, "vh": 240, "rail": {"w": 64, "h": 186}, "column": COLUMN,
                         "base": {"left": 18, "top": 76}, "obstacles": []})
    assert s["fits"] is False


# ------------------------------------------------------------ insertion


def test_le_module_est_servi_et_son_emplacement_est_frere_de_la_palette():
    html = PAGE_HTML.read_text(encoding="utf-8")
    assert CAPTURE_RAIL_SCRIPT_MARKER in html
    assert html.index(BAREHANDS_HUD_SCRIPT_MARKER) < html.index(CAPTURE_RAIL_SCRIPT_MARKER)
    assert html.index(INTERACTION_MODE_SCRIPT_MARKER) < html.index(CAPTURE_RAIL_SCRIPT_MARKER)
    assert '<div id="captureRail"></div>' in html
    # Après la palette, hors d'elle : un frère, pas un enfant.
    assert html.index('<div id="barehandsPalette"></div>') < html.index('<div id="captureRail"></div>')


def test_le_rail_n_emprunte_rien_aux_outils_bare_hands(tmp_path):
    source = MODULE.read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    for forbidden in ("data-bh-tool", "describeTools", "BH.TOOL", "barehandsPaletteStrip", "JarvisBarehands.tool"):
        assert forbidden not in code, forbidden
    # Le contrat Bare Hands n'a pas bougé : toujours exactement trois outils.
    contracts = RUNTIME / "control_center_barehands_contracts.js"
    tools = run(tmp_path, f"const B=require({json.dumps(str(contracts))});"
                          "out(B.describeTools().map(t=>t.id))")
    assert tools == ["pointer", "pan", "select"]


def test_la_scene_mesure_le_rail_comme_une_commande():
    page = SCENE_PAGE.read_text(encoding="utf-8")
    selector = re.search(r"const CONTROL_SELECTOR='([^']+)'", page).group(1)
    assert "#captureRail" in selector.split(",")
    assert "#barehandsPalette" in selector.split(",")


def test_le_rail_est_au_rang_de_la_palette(tmp_path):
    style = run(tmp_path, "out(M.STYLE)")
    assert re.search(r"#captureRail\{position:absolute;z-index:30;", style)
    # Mouvement réduit : la respiration et le balayage s'arrêtent dans la feuille.
    reduced = style[style.index("prefers-reduced-motion"):]
    assert "animation:none" in reduced


def test_un_demarrage_en_vol_que_core_referme_reste_un_demarrage(tmp_path):
    v = run(tmp_path, "out(M.viewOf({status:st([cap('audio','stopping',{activated_at:null})]),reachable:true,now:NOW,"
                      "pending:{audio:{kind:'start',since:NOW-2000}}}).controls.audio)")
    assert v["state"] == "starting" and v["action"] is None and v["timer"] == "2 s"
