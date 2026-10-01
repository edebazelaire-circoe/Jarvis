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
    # Le nom ne porte pas la durée (il serait réannoncé chaque seconde) : la description, si.
    assert v["label"] == "Arrêter l’enregistrement audio"
    assert v["detail"] == "en cours depuis 1:00"
    assert v["stopMark"] is True
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
    ("core_unreachable", "audio", "Core de Jarvis injoignable"),
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


def test_les_phrases_composees_ne_bafouillent_pas(tmp_path):
    """MINOR-4 : pas de verbe répété, pas de parenthèses accolées."""

    v = run(tmp_path, r"""
      const ch=['audio','screen','screenshot'],all={};
      for(const code of Object.keys(M.TEXT))for(const c of ch)for(const verb of ['non démarré','interrompu','échouée'])
        all[`${code}|${c}|${verb}`]=M.noteText(c,verb,code,'');
      out({all,
        partial:M.noteText('audio','interrompu','recoverable_partial',''),
        nothing:M.noteText('screen','interrompu','capture_interrupted',''),
        denied:M.noteText('screen','non démarré','permission_denied',''),
        none:M.noteText('audio','interrompu',null,'')});
    """)
    assert v["partial"] == "Enregistrement audio interrompu — fichier partiel récupéré (recoverable_partial)."
    assert v["nothing"] == "Enregistrement d’écran interrompu — rien de récupérable (capture_interrupted)."
    assert v["denied"] == ("Enregistrement d’écran non démarré — accès à l’écran refusé, "
                           "session peut-être verrouillée (permission_denied).")
    assert v["none"] == "Enregistrement audio interrompu — cause inconnue."
    for key, text in v["all"].items():
        verb = key.split("|")[2]
        assert ") (" not in text and "?)" not in text, (key, text)
        assert text.count(verb) == 1, (key, text)


def test_une_interruption_ne_parle_pas_d_un_essai_jamais_fait(tmp_path):
    v = run(tmp_path, r"""
      const s=st();
      out({ended:M.viewOf({status:s,reachable:true,now:NOW,failure:{audio:{code:'source_lost',
          text:'source perdue en cours de route',verb:'interrompu'}}}).controls.audio.label,
        tried:M.viewOf({status:s,reachable:true,now:NOW,failure:{audio:{code:'source_unavailable',
          text:'micro indisponible'}}}).controls.audio.label});
    """)
    assert v["ended"] == "Démarrer l’enregistrement audio — précédent interrompu : source perdue en cours de route"
    assert "dernier essai" not in v["ended"]
    assert v["tried"] == "Démarrer l’enregistrement audio — dernier essai : micro indisponible"


def test_un_enregistrement_reste_dit_quand_une_autre_commande_est_en_erreur(tmp_path):
    v = run(tmp_path, r"""
      out([M.viewOf({status:st([cap('audio','active')]),reachable:true,now:NOW,
          failure:{screen:{code:'x',text:'t'}}}).caption,
        M.viewOf({status:st([cap('screen','stopping')],[{capture_id:'jcap_screen',error_code:'e'}]),
          reachable:true,now:NOW}).caption,
        M.viewOf({status:st(),reachable:true,now:NOW,failure:{screen:{code:'x',text:'t'}}}).caption]);
    """)
    assert v == ["REC 1 !", "REC 1 !", "ERREUR"]


def test_un_canal_ouvert_garde_son_dessin_et_porte_la_pastille_d_arret(tmp_path):
    v = run(tmp_path, r"""
      const both=M.viewOf({status:st([cap('audio','active'),cap('screen','stopping')]),reachable:true,now:NOW}).controls;
      const stuck=M.viewOf({status:st([cap('screen','stopping')],[{capture_id:'jcap_screen',error_code:'e'}]),
        reachable:true,now:NOW}).controls.screen;
      const known=M.viewOf({reachable:false,now:NOW,known:{audio:{capture_id:'jcap_audio'}}}).controls.audio;
      out({glyphs:[M.glyphOf(both.audio),M.glyphOf(both.screen)],marks:[both.audio.stopMark,both.screen.stopMark],
        stuck:[M.glyphOf(stuck),stuck.stopMark],known:known.stopMark,art:Object.keys(M.ART)});
    """)
    assert v["glyphs"] == ["audio", "screen"], "deux canaux ouverts restent distincts"
    assert v["marks"] == [True, True]
    assert v["stuck"] == ["screen", False], "le coin porte le « ! » d'un arrêt bloqué"
    assert v["known"] is False, "statut perdu : rien n'est peint ouvert"
    assert "stop" not in v["art"]


def test_la_capture_d_ecran_ne_ressemble_pas_a_l_outil_select(tmp_path):
    hud = RUNTIME / "control_center_barehands_hud.js"
    select = re.search(r"\[BH\.TOOL\.SELECT\]:Object\.freeze\(\{\s*paths:Object\.freeze\(\[(.*?)\]\)",
                       hud.read_text(encoding="utf-8"), re.S).group(1)
    v = run(tmp_path, "out(M.ART.screenshot.paths)")
    # Les équerres de visée du `select` (`M4.7 9.2V6.1…`) n'ont pas d'équivalent ici :
    # aucun tracé du rail ne commence par un coin ouvert.
    assert not any(re.match(r"M\S+ \S+V", path) for path in v), v
    assert "V6.1" in select
    assert any("h2.4l1.5-2.2" in path for path in v), "le boîtier d'un appareil photo"


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


def test_a_320_le_rail_remonte_au_dessus_du_bouton_de_mode(tmp_path):
    """MINOR-3 : mesures du direct (QA) à 320 × 568, indicateur de scène présent :
    le bouton de mode, levé, commence à y 394 ; le rail à côté finissait à 398."""

    s = _slot(tmp_path, {"vw": 320, "vh": 568, "rail": {"w": 64, "h": 155},
                         "column": {"left": 10, "top": 243, "right": 74, "bottom": 490},
                         "base": {"left": 10, "top": 243}, "obstacles": [
                             {"left": 84, "top": 394, "right": 261, "bottom": 454},
                             {"left": 258, "top": 72, "right": 310, "bottom": 496}]})
    assert s["mode"] == "beside-up" and s["fits"] is True, s
    assert s["left"] == 74 and s["top"] + 155 <= 394 - 8, s


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


# ==========================================================================
# Le contrôleur, DOM factice et horloge factice (reprise QA de la Slice 10)
# ==========================================================================
#
# Repris des sondes de la QA (`probe.js`, `probe2.js`) : `createCaptureRail`
# monté sur un DOM minimal, un `fetch` dont chaque réponse a son délai, et une
# horloge qui n'avance que quand le test le dit. Chaque test ci-dessous tue un
# mutant précis : retrait du vol unique, cadence cachée ignorée, échéance
# 6 s → 60 s, arrêt en attente peint en démarrage, relecture périmée après
# écriture, minuterie orpheline après un réveil, recul absent.

CONTROLLER = r"""
function fakeDoc(){
  const mk=tag=>{const el={tagName:tag,children:[],attrs:{},style:{},hidden:false,offsetTop:0,listeners:{},_text:'',
    sets:{},
    setAttribute(k,v){this.attrs[k]=String(v);this.sets[k]=(this.sets[k]||0)+1},
    getAttribute(k){return k in this.attrs?this.attrs[k]:null},removeAttribute(k){delete this.attrs[k]},
    appendChild(c){this.children.push(c);return c},append(...c){this.children.push(...c)},
    addEventListener(t,f){(this.listeners[t]=this.listeners[t]||[]).push(f)},focus(){},
    set textContent(v){this._text=v;this.children=[]},get textContent(){return this._text}};return el};
  return {createElement:mk,createElementNS:(_ns,t)=>mk(t),getElementById:()=>null,head:mk('head'),mk};
}
function harness(opts){
  let clock=Date.parse('2026-10-01T10:00:00Z');const timers=new Map();let seq=0;
  const later=(fn,ms)=>{const id=++seq;timers.set(id,{at:clock+ms,fn,every:0});return id};
  const unlater=id=>timers.delete(id);
  const every=(fn,ms)=>{const id=++seq;timers.set(id,{at:clock+ms,fn,every:ms});return id};
  const calls=[];let hidden=false;
  const fetch=(url,init)=>{calls.push({t:clock,url,method:init.method||'GET'});
    const isStatus=url.startsWith('/api/captures/status');
    const r=isStatus?opts.status():(opts.write?opts.write(url,init)
      :{status:201,body:{capture:{capture_id:'c1',state:'active'}}});
    return new Promise((resolve,reject)=>{
      const deliver=()=>{if(r.throw)reject(new TypeError('Failed to fetch'));
        else resolve({ok:r.ok!==false,status:r.status||200,text:async()=>JSON.stringify(r.body)})};
      if(r.delay)later(deliver,r.delay);else deliver();
      if(init.signal)init.signal.addEventListener('abort',
        ()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'})));});};
  const doc=fakeDoc();const host=doc.mk('div');
  const logs=[],paints=[];let rail=null;
  rail=M.createCaptureRail({document:doc,host,fetch,now:()=>clock,setTimeout:later,clearTimeout:unlater,
    setInterval:every,clearInterval:unlater,hidden:()=>hidden,log:(l,e,d)=>logs.push(e),
    onPaint:v=>paints.push({audio:v.controls.audio.state,screen:v.controls.screen.state,
      shot:v.controls.screenshot.state,pressed:v.controls.audio.pressed,
      note:rail&&rail.note()?rail.note().tone+':'+rail.note().control:null})});
  const flush=async()=>{for(let i=0;i<4;i+=1)await new Promise(r=>setImmediate(r))};
  async function advance(ms){const end=clock+ms;
    for(;;){await flush();let next=null;
      for(const [id,t] of timers)if(t.at<=end&&(!next||t.at<timers.get(next).at))next=id;
      if(!next)break;const t=timers.get(next);clock=t.at;if(t.every)t.at+=t.every;else timers.delete(next);
      t.fn();await flush();}
    clock=end;await flush();}
  const gets=()=>calls.filter(c=>c.method==='GET').length;
  const pollTimers=()=>[...timers.values()].filter(t=>!t.every).length;
  return {rail,calls,gets,advance,setHidden:h=>{hidden=h},timers,pollTimers,logs,paints,host,clock:()=>clock};
}
const iso=ms=>new Date(ms).toISOString();
const row=(ch,state,x)=>Object.assign({capture_id:'jcap_'+ch,channel:ch,mode:'continuous',state,
  created_at:'2026-10-01T09:59:00Z',activated_at:'2026-10-01T09:59:01Z',stop_requested_at:null},x||{});
const ok=(captures,recent,delay)=>({status:200,body:{captures:captures||[],stuck:[],recent:recent||[]},delay});
const button=(h,id)=>h.host.children.find(c=>c.id==='captureRailStrip').children
  .find(b=>b.attrs['data-capture-control']===id);
"""


def ctl(tmp_path: Path, body: str):
    return run(tmp_path, CONTROLLER + "(async()=>{\n" + body
               + "\n})().catch(e=>{console.error(e);process.exit(1)});")


def test_apres_un_demarrage_aucun_repos_perime(tmp_path):
    """MAJOR-2 : statut lent (900 ms), écriture rapide (100 ms). La lecture en
    vol pendant l'écriture revient **après** elle avec l'état d'avant."""

    v = ctl(tmp_path, r"""
      let open=false;
      const h=harness({status:()=>ok(open?[row('audio','active')]:[],[],900),
        write:()=>{open=true;return {status:201,body:{capture:row('audio','active')},delay:100}}});
      h.rail.start();await h.advance(1100);
      const before=h.rail.view().controls.audio.state;
      // Cliquer pendant qu'une lecture de cadence est en vol.
      const n=h.gets();while(h.gets()===n)await h.advance(10);
      h.paints.length=0;h.rail.act('audio');const seen=[];
      for(let i=0;i<30;i+=1){await h.advance(100);seen.push(h.rail.view().controls.audio.state)}
      out({before,seen,paints:h.paints.map(p=>p.audio)});
    """)
    assert v["before"] == "idle"
    seen = v["seen"]
    first_active = seen.index("active")
    assert set(seen[:first_active]) == {"starting"}, seen
    assert set(seen[first_active:]) == {"active"}, seen
    paints = v["paints"]
    assert "idle" not in paints[:paints.index("active")], paints


def test_apres_un_arret_aucun_actif_perime(tmp_path):
    v = ctl(tmp_path, r"""
      let open=true;
      const h=harness({status:()=>ok(open?[row('audio','active')]:[],open?[]:[row('audio','complete')],900),
        write:()=>{open=false;return {status:200,body:{capture:row('audio','complete')},delay:100}}});
      h.rail.start();await h.advance(1100);
      const before=h.rail.view().controls.audio.state;
      const n=h.gets();while(h.gets()===n)await h.advance(10);
      h.rail.act('audio');const seen=[];
      for(let i=0;i<30;i+=1){await h.advance(100);const c=h.rail.view().controls.audio;
        seen.push(c.state+(c.pressed?'*':''))}
      const b=button(h,'audio');
      out({before,seen,note:h.rail.note(),pressed:b.attrs['aria-pressed']});
    """)
    assert v["before"] == "active"
    seen = v["seen"]
    done = seen.index("idle")
    assert done > 0 and all(s.startswith("stopping") for s in seen[:done]), seen
    assert set(seen[done:]) == {"idle"}, seen
    assert v["pressed"] == "false"
    assert v["note"] is None, "un arrêt demandé ici n'est pas une interruption"


def test_un_seul_sondage_a_la_fois(tmp_path):
    v = ctl(tmp_path, r"""
      const h=harness({status:()=>ok([],[],500)});
      const a=h.rail.poll(),b=h.rail.poll(),c=h.rail.poll();
      await h.advance(600);
      out({gets:h.gets(),same:a===b&&b===c,url:h.calls[0].url});
    """)
    assert v["gets"] == 1 and v["same"] is True
    assert v["url"] == "/api/captures/status?recent=3"


def test_la_cadence_suit_la_decision_pm(tmp_path):
    """1 s capture ouverte, 3 s au repos, 20 s onglet caché."""

    v = ctl(tmp_path, r"""
      let open=false;
      const h=harness({status:()=>ok(open?[row('audio','active')]:[]),
        write:()=>{open=true;return {status:201,body:{capture:row('audio','active')}}}});
      h.rail.start();await h.advance(100);
      let n=h.gets();await h.advance(30000);const idle=h.gets()-n;
      h.setHidden(true);await h.advance(3000);n=h.gets();await h.advance(60000);const hidden=h.gets()-n;
      h.setHidden(false);await h.rail.wake();
      await h.rail.act('audio');await h.advance(15000);n=h.gets();await h.advance(10000);const recording=h.gets()-n;
      open=false;await h.advance(5000);n=h.gets();await h.advance(30000);const back=h.gets()-n;
      out({idle,hidden,recording,back,timers:h.pollTimers()});
    """)
    assert 9 <= v["idle"] <= 11, v
    assert 2 <= v["hidden"] <= 4, v
    assert 9 <= v["recording"] <= 11, "capture ouverte : 1 s, même 15 s après l'écriture"
    assert 9 <= v["back"] <= 11, v
    assert v["timers"] == 1


def test_une_ecriture_garde_la_cadence_rapide_dix_secondes(tmp_path):
    v = ctl(tmp_path, r"""
      const h=harness({status:()=>ok([]),
        write:()=>({ok:false,status:503,body:{error:{code:'source_unavailable',message:'no mic'}}})});
      h.rail.start();await h.advance(100);
      await h.rail.act('audio');let n=h.gets();await h.advance(9500);const fast=h.gets()-n;
      await h.advance(1000);n=h.gets();await h.advance(12000);const slow=h.gets()-n;
      out({fast,slow});
    """)
    assert 8 <= v["fast"] <= 10, v
    assert 3 <= v["slow"] <= 5, v


def test_une_ecriture_en_vol_passe_tout_de_suite_a_la_seconde(tmp_path):
    """Un démarrage que Core met 5 s à accepter : le rail relit chaque seconde
    pendant l'attente, sans attendre la fin du pas de repos (3 s)."""

    v = ctl(tmp_path, r"""
      const h=harness({status:()=>ok([]),write:()=>({status:201,body:{capture:row('audio','active')},delay:5000})});
      h.rail.start();await h.advance(100);
      h.rail.act('audio');const n=h.gets();await h.advance(4500);
      out(h.gets()-n);
    """)
    assert v >= 4, v


def test_l_echeance_de_lecture_est_de_six_secondes(tmp_path):
    v = ctl(tmp_path, r"""
      let hang=false;
      const h=harness({status:()=>hang?ok([],[],60000):ok([row('audio','active')])});
      h.rail.start();await h.advance(1500);hang=true;
      const seq=[];for(let i=0;i<9;i+=1){await h.advance(1000);seq.push(h.rail.view().controls.audio.state)}
      out(seq);
    """)
    # La lecture qui pend part dans la seconde : à 7 s au plus, l'état est inconnu.
    assert v[0] == "active"
    assert "unknown" in v[:7], v
    assert v[-1] == "unknown"


def test_statut_perdu_recul_jusqu_a_quinze_secondes_puis_retour(tmp_path):
    v = ctl(tmp_path, r"""
      let down=true;
      const h=harness({status:()=>down?{throw:true}:ok([])});
      h.rail.start();await h.advance(90000);
      const at=h.calls.map(c=>c.t);
      const delays=at.slice(1).map((t,i)=>t-at[i]);
      down=false;await h.advance(16000);const back=h.rail.view().reachable;
      await h.advance(3500);const n=h.gets();await h.advance(30000);
      out({delays,back,after:h.gets()-n,lostLogs:h.logs.filter(e=>e.endsWith('status_lost')).length,
        restored:h.logs.includes('capture_rail.status_restored')});
    """)
    assert v["delays"][:5] == [1000, 2000, 4000, 8000, 15000], v["delays"]
    assert set(v["delays"][4:]) == {15000}, v["delays"]
    assert v["back"] is True and v["restored"] is True
    assert 9 <= v["after"] <= 11, "retour à la cadence de repos au premier succès"
    assert v["lostLogs"] == 1, "une perte se journalise une fois, pas à chaque essai"


def test_un_reveil_pendant_une_lecture_ne_laisse_pas_de_minuterie_orpheline(tmp_path):
    v = ctl(tmp_path, r"""
      const h=harness({status:()=>ok([],[],400)});
      h.rail.start();await h.advance(500);
      for(let k=0;k<4;k+=1){const n=h.gets();while(h.gets()===n)await h.advance(10);h.rail.wake();await h.advance(50)}
      await h.advance(1000);
      const timers=h.pollTimers();
      const n=h.gets();await h.advance(30000);
      const polls=h.gets()-n;h.rail.destroy();const m=h.gets();await h.advance(30000);
      out({timers,polls,afterDestroy:h.gets()-m});
    """)
    assert v["timers"] == 1, v
    assert 8 <= v["polls"] <= 10, "une seule boucle de sondage (3 s + 0,4 s de lecture)"
    assert v["afterDestroy"] == 0


def test_onglet_cache_vingt_secondes(tmp_path):
    v = ctl(tmp_path, r"""
      const h=harness({status:()=>ok([row('audio','active')])});
      h.setHidden(true);h.rail.start();await h.advance(100);
      const n=h.gets();await h.advance(100000);
      out({gets:h.gets()-n,delay:h.rail.nextDelay()});
    """)
    assert v["delay"] == 20000
    assert 4 <= v["gets"] <= 6, v


def test_un_arret_en_attente_reste_un_arret_quand_le_statut_tombe(tmp_path):
    v = ctl(tmp_path, r"""
      let down=false;
      const h=harness({status:()=>down?{throw:true}:ok([row('audio','active')]),
        write:()=>({status:200,body:{capture:row('audio','complete')},delay:20000})});
      h.rail.start();await h.advance(1500);
      down=true;await h.advance(1500);
      const lost=h.rail.view().controls.audio;
      h.rail.act('audio');await h.advance(3000);
      const c=h.rail.view().controls.audio;
      out({lost:[lost.state,lost.action],during:[c.state,c.pressed,c.action],
        pure:M.viewOf({reachable:false,now:0,pending:{audio:{kind:'stop',since:0,captureId:'x'}}}).controls.audio.state});
    """)
    assert v["lost"] == ["unknown", "stop"]
    assert v["during"] == ["stopping", False, None]
    assert v["pure"] == "stopping"


def test_un_refus_ne_montre_jamais_l_attente_a_cote_de_la_note(tmp_path):
    """MINOR-2 : la note d'échec n'est jamais peinte pendant que le bouton
    dit encore « démarrage… » / « en cours… »."""

    v = ctl(tmp_path, r"""
      const h=harness({status:()=>ok([],[],300),
        write:url=>({ok:false,status:503,body:{error:{code:url.endsWith('screenshot')?'permission_denied':'source_unavailable',
          message:'no source'}},delay:200})});
      h.rail.start();await h.advance(500);
      h.rail.act('screen');await h.advance(2000);
      const screen=h.paints.filter(p=>p.note==='bad:screen').map(p=>p.screen);
      h.paints.length=0;
      h.rail.act('screenshot');await h.advance(2000);
      out({screen,shot:h.paints.filter(p=>p.note==='bad:screenshot').map(p=>p.shot),note:h.rail.note().text});
    """)
    assert v["screen"] and "starting" not in v["screen"], v["screen"]
    assert v["shot"] and "busy" not in v["shot"], v["shot"]
    assert v["note"] == ("Capture d’écran échouée — accès à l’écran refusé, session peut-être verrouillée "
                         "(permission_denied).")


def test_le_nom_accessible_ne_bouge_pas_chaque_seconde(tmp_path):
    """MINOR-5 : le chronomètre vit dans la description, pas dans le nom."""

    v = ctl(tmp_path, r"""
      const h=harness({status:()=>ok([row('audio','active',{activated_at:'2026-10-01T09:59:55Z'})])});
      h.rail.start();await h.advance(1200);
      const b=button(h,'audio');
      const sets=b.sets['aria-label'];const detail=b.children.find(c=>c.className==='cr-sr');const d1=detail.textContent;
      await h.advance(5000);
      out({label:b.attrs['aria-label'],title:b.attrs.title,grew:b.sets['aria-label']-sets,
        describedby:b.attrs['aria-describedby'],detailId:detail.id,d1,d2:detail.textContent,
        stop:b.attrs['data-cr-stop'],glyph:b.children[0].children[0].attrs['data-cr-glyph']});
    """)
    assert v["label"] == v["title"] == "Arrêter l’enregistrement audio"
    assert v["grew"] == 0, "aria-label réécrit pendant que le chronomètre tourne"
    assert v["describedby"] == v["detailId"] == "captureRailDetail-audio"
    assert v["d1"] == "en cours depuis 0:06" and v["d2"] == "en cours depuis 0:11"
    # MAJOR-1 : le canal reste reconnaissable, l'arrêt est une pastille à part.
    assert v["glyph"] == "audio" and v["stop"] == "true"
