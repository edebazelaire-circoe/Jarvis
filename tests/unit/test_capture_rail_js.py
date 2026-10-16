"""Contrôleur de capture et ses vues pures, exécutés par node.

Né avec le rail de gauche (session-context-recording, Slice 10) ; depuis la
Slice 04 de `jarvis-board-orbital-ui-workspace-rail` le contrôleur ne dessine
plus rien (`control_center_capture_rail.js`) et ses vues sont la roue d'outils
et les indicateurs (`control_center_capture_wheel.js`). Les tests du
contrôleur sont gardés tels quels ; les parties de vue (hôte, placement,
dessin) ont migré vers les vues pures ci-dessous et vers
`test_capture_wheel_browser.py`.

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
- plusieurs captures par canal (un écran par enregistrement) : chacune
  listée, chacune arrêtable, même quand le statut tombe ;
- les vues pures : l'état projeté sur un secteur, une puce par capture
  ouverte au nom stable, le sous-arc des cibles réelles (règle de l'entrée
  unique, aucune cible inventée) ;
- les modules sont insérés dans la page servie (contrôleur, roue, vues, dans
  cet ordre), l'hôte des indicateurs est déclaré, l'ancien rail ne l'est plus,
  et rien n'emprunte à `BH.TOOL`.

Le DOM et le réseau sont prouvés dans Chrome par `test_capture_wheel_browser.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import (
    CAPTURE_RAIL_SCRIPT_FILE,
    CAPTURE_RAIL_SCRIPT_MARKER,
    CAPTURE_WHEEL_SCRIPT_FILE,
    CAPTURE_WHEEL_SCRIPT_MARKER,
    INPUT_ARBITRATION_SCRIPT_MARKER,
    TOOL_WHEEL_SCRIPT_FILE,
    TOOL_WHEEL_SCRIPT_MARKER,
)

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
MODULE = RUNTIME / CAPTURE_RAIL_SCRIPT_FILE
VIEWS = RUNTIME / CAPTURE_WHEEL_SCRIPT_FILE
WHEEL = RUNTIME / TOOL_WHEEL_SCRIPT_FILE
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
        f"const V=require({json.dumps(str(VIEWS))});\n"
        f"const W=require({json.dumps(str(WHEEL))});\n"
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


def test_un_canal_ouvert_garde_son_dessin_et_porte_la_marque_d_arret(tmp_path):
    """Migré (Slice 04) : deux canaux ouverts restent distincts — une puce
    par capture, chacune de son canal (le REC de l'écran, le micro de
    l'audio) — et la marque d'arrêt suit l'action, comme sur l'ancien rail."""

    v = run(tmp_path, r"""
      const both=M.viewOf({status:st([cap('audio','active'),cap('screen','stopping')]),reachable:true,now:NOW});
      const stuck=M.viewOf({status:st([cap('screen','stopping')],[{capture_id:'jcap_screen',error_code:'e'}]),
        reachable:true,now:NOW}).controls.screen;
      const known=M.viewOf({reachable:false,now:NOW,known:{audio:{capture_id:'jcap_audio'}}}).controls.audio;
      out({chips:V.chipsOf(both).map(c=>[c.channel,c.state,c.action]),marks:[both.controls.audio.stopMark,
        both.controls.screen.stopMark],stuck:[stuck.state,stuck.stopMark],known:known.stopMark,
        art:Object.keys(W.ART)});
    """)
    assert v["chips"] == [["screen", "stopping", None], ["audio", "active", "stop"]]
    assert v["marks"] == [True, True]
    assert v["stuck"] == ["stuck", False], "un arrêt bloqué porte « ! », pas la marque d'arrêt"
    assert v["known"] is True, "statut perdu : la capture connue ouverte s'arrête encore"
    for glyph in ("video", "screenshot", "audio", "stop", "done"):
        assert glyph in v["art"], glyph


def test_la_capture_d_ecran_ne_ressemble_pas_a_l_outil_select(tmp_path):
    hud = RUNTIME / "control_center_barehands_hud.js"
    select = re.search(r"\[BH\.TOOL\.SELECT\]:Object\.freeze\(\{\s*paths:Object\.freeze\(\[(.*?)\]\)",
                       hud.read_text(encoding="utf-8"), re.S).group(1)
    v = run(tmp_path, "out(W.ART.screenshot.paths)")
    # Les équerres de visée du `select` (`M4.7 9.2V6.1…`) n'ont pas d'équivalent ici :
    # aucun tracé de la capture d'écran ne commence par un coin ouvert.
    assert not any(re.match(r"M\S+ \S+V", path) for path in v), v
    assert "V6.1" in select
    assert any("h2.4l1.5-2.2" in path for path in v), "le boîtier d'un appareil photo"


def test_les_durees_s_ecrivent_en_minutes_puis_en_heures(tmp_path):
    v = run(tmp_path, "out([M.clock(0),M.clock(59),M.clock(61),M.clock(3600),M.clock(3725),"
                      "M.elapsedOf('nonsense',null,NOW)])")
    assert v == ["0:00", "0:59", "1:01", "1:00:00", "1:02:05", None]


# ------------------------------------------------------------ insertion
#
# Le placement mesuré du rail (sous la colonne Bare Hands, à côté, seul) n'a
# plus d'objet : la roue a son ancre au bord gauche et les indicateurs leur
# place au rang 40 (`test_capture_wheel_browser.py` mesure leur non-recouvrement).


def test_les_modules_sont_servis_dans_l_ordre_et_l_hote_des_indicateurs_est_declare():
    html = PAGE_HTML.read_text(encoding="utf-8")
    order = [html.index(m) for m in (CAPTURE_RAIL_SCRIPT_MARKER, TOOL_WHEEL_SCRIPT_MARKER,
                                     CAPTURE_WHEEL_SCRIPT_MARKER, INPUT_ARBITRATION_SCRIPT_MARKER)]
    assert order == sorted(order), "contrôleur, roue, vues de capture, puis Sélection"
    assert re.search(r'<div id="recIndicators" data-shell-control hidden></div>', html)
    # L'ancien rail de gauche n'est plus déclaré : ses commandes sont dans la roue.
    assert 'id="captureRail"' not in html
    assert '<div id="toolWheel" data-shell-control hidden></div>' in html


def test_le_rail_n_emprunte_rien_aux_outils_bare_hands(tmp_path):
    for module in (MODULE, VIEWS):
        code = re.sub(r"/\*.*?\*/", "", module.read_text(encoding="utf-8"), flags=re.S)
        for forbidden in ("data-bh-tool", "describeTools", "BH.TOOL", "barehandsPaletteStrip", "JarvisBarehands.tool"):
            assert forbidden not in code, (module.name, forbidden)
    # Le contrat Bare Hands n'a pas bougé : toujours exactement trois outils.
    contracts = RUNTIME / "control_center_barehands_contracts.js"
    tools = run(tmp_path, f"const B=require({json.dumps(str(contracts))});"
                          "out(B.describeTools().map(t=>t.id))")
    assert tools == ["pointer", "pan", "select"]


def test_la_scene_mesure_les_indicateurs_et_la_roue_comme_des_commandes():
    """Migré (Slice 04) : l'hôte mesuré n'est plus `#captureRail` mais la roue
    (ancre) et les indicateurs ; la conformité complète (chaque hôte, la copie
    de repli identique) est dans `test_control_center_shell_layers.py`."""

    html = PAGE_HTML.read_text(encoding="utf-8")
    for host in ("toolWheel", "recIndicators"):
        assert re.search(rf'<div id="{host}"[^>]*\bdata-shell-control\b', html), host
    page = SCENE_PAGE.read_text(encoding="utf-8")
    assert "SHELL.CONTROL_SELECTOR" in page
    shell = (RUNTIME / "control_center_shell.js").read_text(encoding="utf-8")
    assert "const CONTROL_SELECTOR=`[${CONTROL_ATTRIBUTE}],#sceneLayer>.sc-status`" in shell
    assert "selector:'#recIndicators',zone:'bottom-centre'" in shell
    assert "#captureRail" not in shell


def test_les_indicateurs_sont_au_rang_du_centre_d_etat(tmp_path):
    html = PAGE_HTML.read_text(encoding="utf-8")
    assert re.search(r"#recIndicators\{position:absolute;z-index:40;", html)
    assert "@shell-layer 40: #bgPills, #recIndicators" in html
    source = VIEWS.read_text(encoding="utf-8")
    style = source[source.index("const STYLE=`"):source.index("/* ------------------------------------------------- le bloc navigateur")]
    assert "z-index" not in style, "le rang vit dans la page et au registre, pas dans la feuille du module"
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
# Repris des sondes de la QA (`probe.js`, `probe2.js`) : le contrôleur
# (`createCaptureController`, sans DOM depuis la Slice 04 de l'orbital UI), un
# `fetch` dont chaque réponse a son délai, et une
# horloge qui n'avance que quand le test le dit. Chaque test ci-dessous tue un
# mutant précis : retrait du vol unique, cadence cachée ignorée, échéance
# 6 s → 60 s, arrêt en attente peint en démarrage, relecture périmée après
# écriture, minuterie orpheline après un réveil, recul absent.

CONTROLLER = r"""
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
  const logs=[],paints=[];let rail=null;
  rail=M.createCaptureController({fetch,now:()=>clock,setTimeout:later,clearTimeout:unlater,
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
  return {rail,calls,gets,advance,setHidden:h=>{hidden=h},timers,pollTimers,logs,paints,clock:()=>clock};
}
const iso=ms=>new Date(ms).toISOString();
const row=(ch,state,x)=>Object.assign({capture_id:'jcap_'+ch,channel:ch,mode:'continuous',state,
  created_at:'2026-10-01T09:59:00Z',activated_at:'2026-10-01T09:59:01Z',stop_requested_at:null},x||{});
const ok=(captures,recent,delay)=>({status:200,body:{captures:captures||[],stuck:[],recent:recent||[]},delay});
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
      out({before,seen,note:h.rail.note(),pressed:String(h.rail.view().controls.audio.pressed)});
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
    """MINOR-5, migré (Slice 04) : le chronomètre vit dans la description de la
    puce, pas dans son nom ; le canal reste reconnaissable, l'arrêt est dit à
    part (action `stop`)."""

    v = ctl(tmp_path, r"""
      const h=harness({status:()=>ok([row('audio','active',{activated_at:'2026-10-01T09:59:55Z'})])});
      const names=[],details=[];
      h.rail.subscribe(view=>{const c=V.chipsOf(view).find(x=>x.channel==='audio');
        if(c){names.push(c.name);details.push(c.detail)}});
      h.rail.start();await h.advance(1200);
      const d1=details[details.length-1];
      await h.advance(5000);
      const chip=V.chipsOf(h.rail.view()).find(x=>x.channel==='audio');
      out({names:[...new Set(names)],d1,d2:details[details.length-1],chip:[chip.channel,chip.action,chip.timer],
        wedge:V.wedgeStatusOf(h.rail.view().controls.audio)});
    """)
    assert v["names"] == ["Arrêter l’enregistrement audio"], "nom réécrit pendant que le chronomètre tourne"
    assert v["d1"] == "en cours depuis 0:06" and v["d2"] == "en cours depuis 0:11"
    assert v["chip"] == ["audio", "stop", "0:11"]
    # Le secteur est coché, sans compteur dans son texte (il rejoint son nom accessible).
    assert v["wedge"] == {"text": "en cours", "checked": True}


# ==========================================================================
# Rework QA mineur de la Slice 10 : la pastille suit l'action d'arrêt, un
# clic relit un statut inconnu, un arrêt accepté oublie la capture connue,
# et les mutants survivants N22 / N26.
# ==========================================================================


def test_la_pastille_d_arret_suit_l_action_d_arret(tmp_path):
    v = run(tmp_path, r"""
      const c=(o)=>M.viewOf(Object.assign({now:NOW},o)).controls.audio;
      const pick=x=>({state:x.state,action:x.action,stop:x.stopMark,label:x.label});
      out({
        ownStart:pick(c({status:st([cap('audio','starting',{activated_at:null})]),reachable:true,
          pending:{audio:{kind:'start',since:NOW-1000}}})),
        refusing:pick(c({status:st([cap('audio','stopping',{activated_at:null})]),reachable:true,
          pending:{audio:{kind:'start',since:NOW-1000}}})),
        noRow:pick(c({status:st(),reachable:true,pending:{audio:{kind:'start',since:NOW}}})),
        coreStart:pick(c({status:st([cap('audio','starting')]),reachable:true})),
        stopping:pick(c({status:st([cap('audio','stopping')]),reachable:true})),
        lostStop:pick(c({reachable:false,pending:{audio:{kind:'stop',since:NOW,captureId:'x'}}})),
        lostKnown:pick(c({reachable:false,known:{audio:{capture_id:'jcap_audio'}}})),
        lostBare:pick(c({reachable:false})),
        idle:pick(c({status:st(),reachable:true})),
      });
    """)
    # Notre démarrage en vol, Core tient la ligne `starting` : l'arrêt est offert, la pastille le dit.
    assert v["ownStart"] == {"state": "starting", "action": "stop", "stop": True,
                             "label": "Enregistrement audio : démarrage… — arrêter"}
    # Core referme déjà la ligne (refus de la source) : rien à arrêter, pas de pastille.
    assert v["refusing"]["action"] is None and v["refusing"]["stop"] is False
    assert v["noRow"] == {"state": "starting", "action": None, "stop": False,
                          "label": "Enregistrement audio : démarrage…"}
    assert v["coreStart"]["action"] == "stop" and v["coreStart"]["stop"] is True
    # Pendant l'arrêt, la pastille reste (estompée par la feuille), sans action.
    assert v["stopping"]["action"] is None and v["stopping"]["stop"] is True
    assert v["lostStop"]["state"] == "stopping" and v["lostStop"]["stop"] is True
    assert v["lostKnown"]["action"] == "stop" and v["lostKnown"]["stop"] is True
    assert v["lostBare"]["action"] is None and v["lostBare"]["stop"] is False
    assert v["idle"]["stop"] is False


def test_un_arret_part_pendant_notre_demarrage_en_vol(tmp_path):
    """Core accepte l'arrêt d'une ligne `starting` : la page l'envoie, et la fin
    en échec du démarrage ainsi interrompu n'est pas affichée comme un refus."""

    v = ctl(tmp_path, r"""
      // Démarrage refusé à 2,6 s (l'arrêt l'a interrompu) ; arrêt accepté à 3,6 s ;
      // Core montre la ligne `starting` jusqu'à ce que l'arrêt aboutisse.
      let opened=false,stopAt=0;const stopped=()=>stopAt&&h.clock()>=stopAt+2000;
      const h=harness({status:()=>ok(opened&&!stopped()?[row('audio','starting',{activated_at:null})]:[],
          stopped()?[row('audio','complete')]:[]),
        write:url=>{if(url.endsWith('/stop')){stopAt=h.clock();return {status:200,body:{capture:row('audio','complete')},delay:2000}}
          opened=true;return {ok:false,status:409,body:{error:{code:'capture_interrupted',message:'stopped'}},delay:2500}}});
      h.rail.start();await h.advance(100);
      h.rail.act('audio');await h.advance(1500);
      const offered=h.rail.view().controls.audio;
      const disabled=String(!offered.action),chip=String(offered.stopMark);
      h.rail.act('audio');await h.advance(100);
      const during=h.rail.view().controls.audio.state;
      // La fin du démarrage (2,6 s) ne doit pas effacer l'arrêt encore en vol.
      await h.advance(1200);
      const stillStopping=h.rail.view().controls.audio.state;
      await h.advance(6000);
      const end=h.rail.view().controls.audio;
      out({offered:[offered.state,offered.action,offered.captureId],disabled,chip,during,stillStopping,
        end:[end.state,end.stopMark],note:h.rail.note(),
        posts:h.calls.filter(c=>c.method==='POST').map(c=>c.url),
        superseded:h.logs.includes('capture_rail.start_superseded')});
    """)
    assert v["offered"] == ["starting", "stop", "jcap_audio"]
    assert v["disabled"] == "false" and v["chip"] == "true"
    assert v["during"] == v["stillStopping"] == "stopping"
    assert v["posts"] == ["/api/captures/start", "/api/captures/jcap_audio/stop"]
    assert v["end"] == ["idle", False]
    assert v["note"] is None, "le démarrage arrêté par l'utilisateur n'est pas un refus"
    assert v["superseded"] is True


def test_statut_inconnu_un_clic_relit_tout_de_suite_sans_rien_demarrer(tmp_path):
    v = ctl(tmp_path, r"""
      const h=harness({status:()=>({throw:true})});
      h.rail.start();await h.advance(20000);
      const delay=h.rail.nextDelay();
      const n=h.gets();await h.rail.act('screen');const afterScreen=h.gets()-n;
      await h.rail.act('screenshot');await h.rail.act('audio');
      out({delay,afterScreen,afterAll:h.gets()-n,posts:h.calls.filter(c=>c.method==='POST').length,
        timers:h.pollTimers(),state:h.rail.view().controls.screen.state});
    """)
    assert v["delay"] == 15000, "le recul est au plus long : le clic ne l'attend pas"
    assert v["afterScreen"] == 1 and v["afterAll"] == 3
    assert v["posts"] == 0, "aucun démarrage tant que le statut est inconnu"
    assert v["timers"] == 1 and v["state"] == "unknown"


def test_statut_perdu_un_arret_accepte_oublie_la_capture_connue(tmp_path):
    v = ctl(tmp_path, r"""
      let down=false;
      const h=harness({status:()=>down?{throw:true}:ok([row('audio','active')]),
        write:()=>({status:200,body:{capture:row('audio','complete')}})});
      h.rail.start();await h.advance(1500);
      down=true;await h.advance(1500);
      const before=h.rail.view().controls.audio;
      await h.rail.act('audio');await h.advance(100);
      const after=h.rail.view().controls.audio;
      await h.rail.act('audio');
      out({before:[before.state,before.action,before.stopMark],
        after:[after.state,after.action,after.stopMark,after.label],
        stops:h.calls.filter(c=>c.method==='POST').length});
    """)
    assert v["before"] == ["unknown", "stop", True]
    assert v["after"] == ["unknown", None, False, "Enregistrement audio : état inconnu, Jarvis injoignable"]
    assert v["stops"] == 1, "rien à réarrêter : la capture n'est plus « connue ouverte »"


def test_un_arret_refuse_ne_montre_jamais_l_attente_a_cote_de_la_note(tmp_path):
    """Mutant N26 : l'attente d'arrêt tombe avant la note « non arrêté »."""

    v = ctl(tmp_path, r"""
      const h=harness({status:()=>ok([row('audio','active')],[],300),
        write:()=>({ok:false,status:503,body:{error:{code:'core_unreachable',message:'down'}},delay:200})});
      h.rail.start();await h.advance(500);
      h.paints.length=0;h.rail.act('audio');await h.advance(3000);
      const c=h.rail.view().controls.audio;
      out({withNote:h.paints.filter(p=>p.note==='bad:audio').map(p=>p.audio),
        end:[c.state,c.action,c.stopMark],note:h.rail.note().text});
    """)
    assert v["withNote"] and "stopping" not in v["withNote"], v["withNote"]
    assert v["end"] == ["active", "stop", True]
    assert v["note"] == "Enregistrement audio non arrêté — Core de Jarvis injoignable (core_unreachable)."


def test_une_fin_venue_d_ailleurs_dit_precedent_interrompu(tmp_path):
    """Mutant N22 : le contrôleur, pas seulement le modèle, porte le verbe."""

    v = ctl(tmp_path, r"""
      let open=true;
      const h=harness({status:()=>open?ok([row('audio','active')])
        :ok([],[row('audio','partial',{error_code:'source_lost',stop_reason:'source_lost'})])});
      h.rail.start();await h.advance(1500);
      open=false;await h.advance(1500);
      const c=h.rail.view().controls.audio;
      out({state:c.state,label:c.label,note:h.rail.note().text});
    """)
    assert v["state"] == "error"
    assert v["label"] == "Démarrer l’enregistrement audio — précédent interrompu : source perdue en cours de route"
    assert "dernier essai" not in v["label"]
    assert v["note"] == "Enregistrement audio interrompu — source perdue en cours de route (source_lost)."


# ==========================================================================
# Slice 04 de l'orbital UI : API du contrôleur pour la roue, plusieurs
# captures par canal, vues pures (secteur, puces, sous-arc des cibles).
# ==========================================================================


def test_plusieurs_ecrans_chaque_capture_listee_et_arretable_meme_statut_perdu(tmp_path):
    v = ctl(tmp_path, r"""
      let down=false;
      const two=[row('screen','active',{capture_id:'jcap_a',device:'default',created_at:'2026-10-01T09:59:00Z'}),
        row('screen','active',{capture_id:'jcap_b',device:'display2',created_at:'2026-10-01T09:59:30Z',
          activated_at:'2026-10-01T09:59:31Z'})];
      let open=two.slice();
      const h=harness({status:()=>down?{throw:true}:ok(open),
        write:url=>{const id=decodeURIComponent(url.split('/')[3]);open=open.filter(r=>r.capture_id!==id);
          return {status:200,body:{capture:{capture_id:id,state:'complete'}},delay:500}}});
      h.rail.start();await h.advance(1500);
      const live=h.rail.view().controls.screen;
      down=true;await h.advance(1500);
      const lost=h.rail.view().controls.screen;
      // Statut perdu : chacune s'arrête encore (vie privée d'abord), par son id.
      const first=h.rail.stop('jcap_a');await h.advance(50);
      const during=h.rail.view().controls.screen.captures.map(c=>[c.captureId,c.state,c.action]);
      await h.advance(600);await first;
      const after=h.rail.view().controls.screen.captures.map(c=>[c.captureId,c.state,c.action]);
      const unknownId=await h.rail.stop('jcap_zz');
      out({live:[live.state,live.captureId,live.captures.map(c=>[c.captureId,c.device,c.state,c.timer])],
        lost:[lost.state,lost.action,lost.captures.map(c=>[c.captureId,c.device,c.state,c.action])],
        during,after,unknownId,posts:h.calls.filter(c=>c.method==='POST').map(c=>c.url)});
    """)
    # La plus récente décrit le canal ; toutes sont listées, la plus ancienne d'abord.
    assert v["live"][0:2] == ["active", "jcap_b"]
    assert v["live"][2] == [["jcap_a", "default", "active", "1:00"], ["jcap_b", "display2", "active", "0:30"]]
    assert v["lost"][0:2] == ["unknown", "stop"]
    assert v["lost"][2] == [["jcap_a", "default", "unknown", "stop"], ["jcap_b", "display2", "unknown", "stop"]]
    assert v["during"] == [["jcap_a", "stopping", None], ["jcap_b", "unknown", "stop"]]
    assert v["after"] == [["jcap_b", "unknown", "stop"]], "l'arrêt accepté oublie celle-là, pas l'autre"
    assert v["unknownId"] is None
    assert v["posts"] == ["/api/captures/jcap_a/stop"], "un id que personne ne connaît n'est pas envoyé"


def test_deux_arrets_partent_sans_s_attendre(tmp_path):
    """Vie privée d'abord : arrêter deux enregistrements d'un même canal ne
    fait pas attendre le second derrière le premier."""

    v = ctl(tmp_path, r"""
      const rows=[row('screen','active',{capture_id:'jcap_a'}),row('screen','active',{capture_id:'jcap_b',device:'display2'})];
      const h=harness({status:()=>ok(rows),write:()=>({status:200,body:{capture:{state:'complete'}},delay:3000})});
      h.rail.start();await h.advance(1500);
      h.rail.stop('jcap_a');h.rail.stop('jcap_b');h.rail.stop('jcap_b');await h.advance(100);
      out(h.calls.filter(c=>c.method==='POST').map(c=>c.url));
    """)
    assert v == ["/api/captures/jcap_a/stop", "/api/captures/jcap_b/stop"]


def test_un_demarrage_sur_une_cible_choisie_porte_son_appareil_et_le_simple_non(tmp_path):
    v = ctl(tmp_path, r"""
      const bodies=[];
      const h=harness({status:()=>ok([]),write:(url,init)=>{bodies.push(url+' '+init.body);
        return url.endsWith('screenshot')
          ?{status:201,body:{capture:{capture_id:'jcap_s',mode:'one_shot',state:'complete'},artifact:{artifact_id:'jart_s',kind:'screenshot'}}}
          :{status:201,body:{capture:row('screen','active')}}}});
      h.rail.start();await h.advance(200);
      await h.rail.act('screen');
      await h.rail.startChannel('screen',{device:'display2'});
      await h.rail.startChannel('audio',{device:'default'});
      const shot=await h.rail.screenshot({device:'display2'});
      const simple=await h.rail.act('screenshot');
      out({bodies,shot,last:h.rail.lastShot(),view:h.rail.view().shot,simple});
    """)
    assert v["bodies"] == [
        '/api/captures/start {"channel":"screen"}',
        '/api/captures/start {"channel":"screen","options":{"device":"display2"}}',
        '/api/captures/start {"channel":"audio"}',
        '/api/captures/screenshot {"options":{"device":"display2"}}',
        "/api/captures/screenshot {}",
    ]
    # Le résultat entier, pour l'aperçu de la Slice 05 : rendu et publié.
    assert v["shot"] == {"capture": {"capture_id": "jcap_s", "mode": "one_shot", "state": "complete"},
                         "artifact": {"artifact_id": "jart_s", "kind": "screenshot"}}
    assert v["simple"]["artifact"]["artifact_id"] == "jart_s"
    assert v["view"]["artifact"]["artifact_id"] == "jart_s" and v["view"]["device"] == "default"


def test_statut_inconnu_ni_demarrage_ni_capture_d_ecran_et_la_raison_est_dite(tmp_path):
    v = ctl(tmp_path, r"""
      const h=harness({status:()=>({throw:true})});
      h.rail.start();await h.advance(3000);
      const n=h.gets();
      const a=await h.rail.startChannel('audio',{device:'x'});const b=await h.rail.screenshot({});
      out({a,b,posts:h.calls.filter(c=>c.method==='POST').length,reads:h.gets()-n,note:h.rail.note(),
        logs:h.logs.filter(e=>e.endsWith('_refused'))});
    """)
    assert v["a"] is None and v["b"] is None and v["posts"] == 0
    assert v["reads"] == 2, "chaque demande relit le statut tout de suite"
    assert v["note"]["text"] == ("Capture d’écran non prise — état des captures inconnu, Jarvis injoignable "
                                 "(status_unknown).")
    assert v["logs"] == ["capture_rail.start_refused", "capture_rail.screenshot_refused"]


def test_les_cibles_sont_lues_chez_core_et_un_echec_garde_son_code(tmp_path):
    v = ctl(tmp_path, r"""
      let fail=false;
      const listing={screen:{available:true,devices:[{token:'default',label:'Écran principal'}]},
        audio:{available:false,devices:[],code:'unsupported_source'}};
      const h=harness({status:()=>ok([]),write:url=>fail
        ?{ok:false,status:503,body:{error:{code:'core_unreachable',message:'down'}}}:{status:200,body:listing}});
      h.rail.start();await h.advance(200);
      const got=await h.rail.targets();
      fail=true;let code=null;
      try{await h.rail.targets()}catch(e){code=e.code}
      out({got,code,urls:h.calls.filter(c=>c.url.includes('targets')).map(c=>c.method+' '+c.url),
        logs:h.logs.filter(e=>e.includes('targets'))});
    """)
    assert v["got"]["screen"]["devices"][0]["token"] == "default"
    assert v["code"] == "core_unreachable"
    assert v["urls"] == ["GET /api/captures/targets", "GET /api/captures/targets"]
    assert v["logs"] == ["capture_rail.targets_read", "capture_rail.targets_failed"]


def test_le_secteur_dit_l_etat_du_canal_sans_compteur(tmp_path):
    v = run(tmp_path, r"""
      const s=(o)=>V.wedgeStatusOf(M.viewOf(Object.assign({now:NOW},o)).controls.audio);
      const shot=(o)=>V.wedgeStatusOf(M.viewOf(Object.assign({now:NOW},o)).controls.screenshot);
      out({idle:s({status:st(),reachable:true}),active:s({status:st([cap('audio','active')]),reachable:true}),
        starting:s({status:st(),reachable:true,pending:{audio:{kind:'start',since:NOW}}}),
        error:s({status:st(),reachable:true,failure:{audio:{code:'source_unavailable',text:'micro indisponible'}}}),
        stuck:s({status:st([cap('audio','stopping')],[{capture_id:'jcap_audio',error_code:'store_unavailable'}]),reachable:true}),
        lostKnown:s({reachable:false,known:{audio:{capture_id:'jcap_audio'}}}),lost:s({reachable:false}),
        shotIdle:shot({status:st(),reachable:true}),shotBusy:shot({status:st(),reachable:true,pending:{screenshot:{since:NOW}}}),
        shotLost:shot({reachable:false})});
    """)
    assert v["idle"] == {"checked": False}
    assert v["active"] == {"text": "en cours", "checked": True}
    assert v["starting"] == {"tone": "wait", "text": "démarrage…", "checked": False}
    assert v["error"] == {"tone": "error", "text": "échec (source_unavailable)", "checked": False}
    assert v["stuck"] == {"tone": "error", "text": "arrêt bloqué (store_unavailable)", "checked": True}
    # Statut perdu : « ? » (n'alarme pas l'ancre), jamais coché ; l'arrêt possible est dit.
    assert v["lostKnown"] == {"tone": "unknown", "text": "état inconnu — arrêt possible", "checked": False}
    assert v["lost"]["tone"] == "unknown" and v["lost"]["checked"] is False
    assert v["shotIdle"] is None and v["shotBusy"]["tone"] == "wait" and v["shotLost"]["tone"] == "unknown"


def test_une_puce_par_capture_une_attente_et_la_capture_d_ecran(tmp_path):
    v = run(tmp_path, r"""
      const view=M.viewOf({status:st([cap('screen','active',{device:'display2'}),cap('audio','active')]),reachable:true,
        now:NOW,pending:{screenshot:{since:NOW-2000}}});
      const waiting=M.viewOf({status:st(),reachable:true,now:NOW,pending:{audio:{kind:'start',since:NOW-3000,device:'Casque-USB'}}});
      const done=M.viewOf({status:st(),reachable:true,now:NOW,shotAt:NOW-500});
      const pick=c=>[c.channel,c.state,c.action,c.timer,c.name,c.tag];
      out({view:V.chipsOf(view).map(pick),waiting:V.chipsOf(waiting).map(pick),done:V.chipsOf(done).map(pick),
        idle:V.chipsOf(M.viewOf({status:st(),reachable:true,now:NOW})).length});
    """)
    assert v["view"] == [
        ["screen", "active", "stop", "1:00", "Arrêter l’enregistrement d’écran (écran 2)", "écran 2"],
        ["audio", "active", "stop", "1:00", "Arrêter l’enregistrement audio", ""],
        ["screenshot", "busy", None, "2 s", "Capture d’écran en cours…", ""],
    ]
    assert v["waiting"] == [["audio", "starting", None, "3 s", "Enregistrement audio : démarrage… (Casque-USB)",
                             "Casque-USB"]]
    assert v["done"] == [["screenshot", "done", None, "", "Capture d’écran enregistrée", ""]]
    assert v["idle"] == 0, "rien à dire : aucune puce"


def test_le_sous_arc_ne_propose_que_des_cibles_reelles_et_l_entree_unique_le_dit(tmp_path):
    v = run(tmp_path, r"""
      const idle=M.viewOf({status:st(),reachable:true,now:NOW}).controls;
      const rec=M.viewOf({status:st([cap('screen','active')]),reachable:true,now:NOW}).controls;
      const lost=M.viewOf({reachable:false,now:NOW,known:{screen:{capture_id:'jcap_screen'}}}).controls;
      const one={available:true,devices:[{token:'default',label:'Écran principal',primary:true,width:1920,height:1080}]};
      const two={available:true,devices:[...one.devices,{token:'display2',label:'Écran 2',primary:false,width:1280,height:1024}]};
      const pick=items=>items.map(i=>[i.kind,i.label,(i.kind==='stop'?i.captureId:i.device)||null,!!i.disabled]);
      const err=Object.assign(new Error('x'),{code:'core_unreachable'});
      out({single:pick(V.targetItemsOf('screen',idle.screen,one,null,true)),
        shot:pick(V.targetItemsOf('screenshot',idle.screenshot,two,null,true)),
        recording:pick(V.targetItemsOf('screen',rec.screen,two,null,true)),
        lost:pick(V.targetItemsOf('screen',lost.screen,two,null,false)),
        failed:pick(V.targetItemsOf('audio',idle.audio,null,err,true,c=>M.refusalText(c,'',null))),
        none:pick(V.targetItemsOf('audio',idle.audio,{available:false,devices:[],code:'unsupported_source'},null,true)),
        unreadable:V.targetItemsOf('screen',idle.screen,{available:true,code:'targets_unreadable',devices:one.devices},null,true)[0].detail});
    """)
    # Une seule cible : une entrée, qui le dit — jamais omise, jamais un faux choix.
    assert v["single"] == [["target", "Écran principal — seule cible disponible", "default", False]]
    assert v["shot"] == [["target", "Écran principal", "default", False], ["target", "Écran 2", "display2", False]]
    # Un écran qui enregistre : son arrêt en tête, sa cible non proposée une seconde fois.
    assert v["recording"] == [["stop", "Arrêter — écran principal", "jcap_screen", False],
                              ["target", "Écran principal", "default", True], ["target", "Écran 2", "display2", False]]
    # Statut perdu : l'arrêt reste offert, aucun démarrage.
    assert v["lost"] == [["stop", "Arrêter — écran principal", "jcap_screen", False],
                         ["target", "Écran principal", "default", True], ["target", "Écran 2", "display2", True]]
    assert v["failed"] == [["none", "Cibles illisibles", None, True]]
    assert v["none"] == [["none", "Aucune cible", None, True]]
    assert "targets_unreadable" in v["unreadable"]
