"""Enregistrement, rejeu et mesures Bare Hands (Slice 10, architecture §12).

Exécuté par node : les contrats, l'enregistreur, le bloc pur du moteur et la
page sont les **vrais** ; seuls le DOM, l'horloge et le réseau sont des doubles,
parce que node n'en a pas.

Ce que ce fichier épingle :

- **une trace ne porte ni point de main, ni image, ni identifiant**, et ce n'est
  pas une promesse : la couture réduit avant que l'enregistreur ne voie quoi que
  ce soit, la liste blanche reconstruit clé par clé, et une garde pilotée par le
  schéma tourne **au chargement du module** — on lui présente des points, une
  image en base64 et un objet libre, y compris par des **jumelles bien formées**
  qu'aucun lecteur ne peut refuser en chemin ;
- **rien ne coûte rien quand personne n'enregistre** : hors enregistrement et
  hors calibration la couture de mesures n'existe pas, et le budget d'images est
  exactement celui d'avant — mesuré sur le vrai contrôleur ;
- **un enregistrement finit** : il s'arrête tout seul sur son échéance et sur
  son plafond d'images, et il le dit dans les deux cas ;
- **le rejeu est déterministe**, et changer un axe change les nombres — sans
  quoi « comparer deux configurations » ne voudrait rien dire ;
- **une mesure absente est `null`, jamais zéro** ;
- **les constantes sont épinglées** : le vocabulaire du module JS, celui du
  miroir Python et celui du contrat ne peuvent pas diverger en silence.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from test_barehands_tools_settings_js import (  # noqa: E402
    CAMERA, CALIBRATION, CONTRACTS, RECORDER, SCENE_INTERACT, SCRIPT, TARGET, TIMERS,
    TUTORIAL, browser,
)

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
GOLDEN = ROOT / "jarvis" / "testlab" / "fixtures" / "barehands" / "golden.v1.json"
CONTRACT_DOC = ROOT / "docs" / "barehands-contracts.md"


def run_node(tmp_path: Path, source: str, name: str = "rec") -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"barehands-recorder-{name}.cjs"
    script.write_text(
        f"const C=require({json.dumps(str(CONTRACTS))});\n"
        "global.JarvisBarehandsContracts=C;\n"
        f"const R=require({json.dumps(str(RECORDER))});\n"
        f"const Core=require({json.dumps(str(SCRIPT))});\n"
        f"const T=require({json.dumps(str(TARGET))});\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "const refused=fn=>{try{fn();return null}catch(e){return e.code||e.name||String(e)}};\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True,
                          encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def run_page(tmp_path: Path, source: str, name: str) -> object:
    """Le **vrai** bloc navigateur du pointeur, avec le double de la Slice 07."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"barehands-recorder-page-{name}.cjs"
    script.write_text(
        f"const SCRIPT_PATH={json.dumps(str(SCRIPT))};\n"
        f"const CALIBRATION_PATH={json.dumps(str(CALIBRATION))};\n"
        f"const TUTORIAL_PATH={json.dumps(str(TUTORIAL))};\n"
        f"const RECORDER_PATH={json.dumps(str(RECORDER))};\n"
        f"const TARGET_PATH={json.dumps(str(TARGET))};\n"
        f"const SCENE_INTERACT_PATH={json.dumps(str(SCENE_INTERACT))};\n"
        f"const CONTRACTS_PATH={json.dumps(str(CONTRACTS))};\n"
        "const C=require(CONTRACTS_PATH);\n"
        "const G=require(SCENE_INTERACT_PATH);\n"
        "const R=require(RECORDER_PATH);\n"
        "const out=v=>process.stdout.write(JSON.stringify(v),()=>process.exit(0));\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True,
                          encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


#: Un enregistreur piloté à la main : horloge et minuteries injectées, rien
#: n'avance tout seul. Le double **échoue comme la vraie chose** : `setTimeout`
#: rend un identifiant distinct par appel et `clearTimeout` ne retire que
#: celui-là, seule façon de voir qu'une seconde séance n'arme pas deux
#: échéances.
HARNESS = r"""
let clock=1000;
const wiring=extra=>{
  const w={timers:new Map(),seq:0};
  w.deps=Object.assign({
    now:()=>clock,
    setTimeout:(fn,ms)=>{const id=++w.seq;w.timers.set(id,{fn,at:clock+ms});return id},
    clearTimeout:id=>w.timers.delete(id),
  },extra||{});
  /* Faire passer le temps **pour de vrai** : les échéances dues se déclenchent,
     les autres non. Une minuterie qui se déclencherait à chaque tour ne
     pourrait pas montrer qu'une échéance arrive au bon moment. */
  w.advance=ms=>{
    clock+=ms;
    for(const [id,timer] of [...w.timers.entries()])
      if(timer.at<=clock){w.timers.delete(id);timer.fn()}
    return w.timers.size;
  };
  w.armed=()=>w.timers.size;
  return w;
};
const recWith=extra=>{const w=wiring(extra);w.rec=R.createRecorder(w.deps);return w};
/* Ce que l'enregistreur ne doit **jamais** retenir, présenté exprès à chaque
   image : les vingt et un points d'une main, une image en base64, un objet
   libre, un identifiant de suivi et un identifiant d'objet. */
const POISONED={
  handTrackId:'hand-3f9a',
  landmarks:Array.from({length:21},(_,i)=>({x:i/21,y:i/42,z:0.01*i})),
  snapshot:'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB',
  raw:{frame:{width:640,height:480},pixels:[1,2,3]},
  label:'Mot de passe de Clarice',
};
const handAt=(x,y,ratio,still)=>Object.assign({
  handedness:'left',primaryRatio:ratio,secondaryRatio:0.9,
  cPose:0.2,closure:0.3,gapPalms:0.6,indexReachPalms:1.4,palmNorm:1,
  rawX:x,rawY:y,filteredX:x,filteredY:y,palmX:x,palmY:y,
  quality:0.9,stillness:still,speedPxPerSec:still>0.8?2:300,
},POISONED);
const frameAt=(x,y,ratio,still,extra)=>Object.assign({
  lifecycle:'active',
  hands:[handAt(x,y,ratio,still)],
  candidates:[Object.assign({kind:'button',region:'body',actionable:true,
    objectId:'sc-node-42',boundsPx:{x:600,y:300,w:140,h:44}},POISONED)],
  events:[],gestures:[],
},extra||{});
"""


# ------------------------------------------------------------------ la vie privée


def test_a_recorded_trace_carries_no_landmark_no_image_and_no_identifier(tmp_path):
    """**La garantie centrale de la Slice, et elle est structurelle.**

    Une suite de points de main est une **reconstruction de la main de
    l'utilisateur** : c'est la chose la plus dangereuse que cette tâche ait
    proposé d'enregistrer. Elle n'entre pas, et pas parce qu'on la refuse — on
    ne la recopie pas.

    On présente donc à l'enregistreur, à chaque image, exactement ce qu'il ne
    doit pas retenir : vingt et un points, une image en base64, un objet libre,
    un identifiant de suivi de main et un identifiant d'objet de scène. La
    trace complète est ensuite relue **sérialisée**, parce qu'une assertion clé
    par clé ne verrait pas une fuite dans une poche imbriquée."""

    result = run_node(tmp_path, HARNESS + """
      const w=recWith({options:{maxDurationMs:20000,maxFrames:100}});
      w.rec.start({viewport:{width:1280,height:720}});
      for(let i=0;i<30;i+=1){
        w.advance(16);
        w.rec.feed(frameAt(500+i,360,i>10&&i<20?0.15:0.85,i<10?0.95:0.2,{
          events:[Object.assign({type:'click',channel:'primary',objectId:'sc-node-42',axes:[]},POISONED)],
          gestures:[Object.assign({name:'open_palm',phase:'start',suppressed:true},POISONED)],
        }));
      }
      const trace=w.rec.stop();
      const text=JSON.stringify(trace);
      out({frames:trace.frames.length,
        text,
        handKeys:Object.keys(trace.frames[0].hands[0]),
        candidateKeys:Object.keys(trace.frames[0].candidates[0]),
        eventKeys:Object.keys(trace.frames[0].events[0]||{}),
        gestureKeys:Object.keys(trace.frames[0].gestures[0]||{}),
        /* Ce que la trace dit d'un objet : un **booléen**, jamais lequel. */
        onObject:trace.frames.map(f=>f.events.map(e=>e.onObject)).flat(),
        slots:[...new Set(trace.frames.map(f=>f.hands.map(h=>h.slot)).flat())],
        refs:[...new Set(trace.frames.map(f=>f.candidates.map(c=>c.ref)).flat())]});
    """, "privacy")

    text = result["text"]
    # Rien de ce qu'on a présenté ne ressort, sous aucune forme.
    # Les sondes sont des **clés JSON** : chercher « raw » nu trouverait
    # `rawX`, qui est une mesure légitime, et le test accuserait à tort.
    for leak in ('"landmarks"', '"snapshot"', '"handTrackId"', "hand-3f9a", "sc-node-42",
                 "data:image", '"pixels"', "Mot de passe", '"label"', '"raw"'):
        assert leak not in text, f"la trace transporte « {leak} »"
    # Et ce qu'elle porte est exactement le schéma, clé pour clé.
    assert set(result["handKeys"]) == {
        "slot", "handedness", "primaryRatio", "secondaryRatio", "cPose", "closure",
        "gapPalms", "indexReachPalms", "palmNorm", "rawX", "rawY", "filteredX",
        "filteredY", "palmX", "palmY", "quality", "stillness", "speedPxPerSec"}
    assert set(result["candidateKeys"]) == {
        "ref", "kind", "region", "representation", "actionable", "x", "y", "w", "h"}
    assert set(result["eventKeys"]) == {"type", "channel", "onObject", "axes"}
    assert set(result["gestureKeys"]) == {"name", "phase", "suppressed"}
    # L'identité d'une main est une **fente**, celle d'une candidate un **rang**.
    assert result["slots"] == [0] and result["refs"] == [0]
    # Qu'il y avait un objet est vrai ; lequel n'est nulle part.
    assert all(result["onObject"])


def test_the_shape_guard_runs_at_module_load_and_a_leaking_schema_never_installs(tmp_path):
    """**On épingle l'installation, pas la fonction.**

    La Slice 09 a payé cette leçon : son test appelait `assertTeachingOnly()`
    explicitement, ce qui prouvait la fonction et jamais son installation —
    commenter l'appel laissait tout au vert. Ici on écrit la Slice future qui
    ferait la faute : une copie du module où la liste blanche laisse passer une
    clé libre. Elle ne doit **pas** s'installer, ni comme global ni comme export
    node, et le vrai module doit continuer de s'installer — une garde qui crie
    au loup ne vaut pas mieux qu'une garde absente.

    Et la levée reste **contenue** : la page servie n'a qu'une balise
    `<script>`, donc une levée non rattrapée au chargement y avorterait la
    scène, la timeline et le Test Lab. Le module attrape la sienne, journalise
    la cause, et ne s'installe pas."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    source = RECORDER.read_text(encoding="utf-8")
    anchor_blank = "const BLANK_HAND=Object.freeze({slot:0,handedness:null,"
    anchor_read = "      slot:count(slot),"
    assert source.count(anchor_blank) == 1 and source.count(anchor_read) == 1
    victim_text = (source
                   .replace(anchor_blank, anchor_blank + "sampleFrames:null,")
                   .replace(anchor_read, anchor_read + "\n      sampleFrames:source.sampleFrames||null,"))
    victim = tmp_path / "leaking_recorder.js"
    victim.write_text(victim_text, encoding="utf-8")

    script = tmp_path / "barehands-recorder-guard.cjs"
    script.write_text(
        f"const C=require({json.dumps(str(CONTRACTS))});\n"
        "global.JarvisBarehandsContracts=C;\n"
        "const load=path=>{try{const m=require(path);"
        "return {installed:!!m&&Object.keys(m).length>0,"
        "global:typeof globalThis.JarvisBarehandsRecorder!=='undefined'}}"
        "catch(e){return {threw:String(e&&e.code||e.name||e)}}};\n"
        f"const bad=load({json.dumps(str(victim))});\n"
        "delete globalThis.JarvisBarehandsRecorder;\n"
        f"const good=load({json.dumps(str(RECORDER))});\n"
        "process.stdout.write(JSON.stringify({bad,good}));",
        encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True,
                          encoding="utf-8", timeout=40, check=False)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)

    # La copie qui fuit ne s'installe pas — ni export node, ni global.
    assert result["bad"]["installed"] is False, (
        "un schéma qui laisse passer une clé libre s'est installé quand même"
    )
    assert result["bad"]["global"] is False
    # La cause part dans la console, avec son nom.
    assert "recorder_not_installed" in (done.stderr or ""), done.stderr
    # Et le vrai module, lui, s'installe : la sonde ne crie pas au loup.
    assert result["good"]["installed"] is True and result["good"]["global"] is True


def test_the_guard_presents_its_poison_to_every_key_and_by_a_twin_that_cannot_be_refused(tmp_path):
    """**Une sonde refusée en chemin mesure le chemin, pas la porte.**

    C'est la leçon de la reprise de la Slice 08, dont la garde avalait
    précisément les deux champs que la décision 32 nomme comme le risque. La
    garde d'ici porte donc, à côté du balayage clé par clé, trois formes
    **valides** — une main, une candidate avec sa poche imbriquée `boundsPx`,
    un geste — qu'aucun lecteur ne peut rejeter avant la garde, et qui portent
    le poison en clé supplémentaire.

    On le vérifie sans appeler la garde : on lui donne les mêmes formes et on
    lit ce qui en ressort."""

    result = run_node(tmp_path, """
      const poisons=[[{x:.1,y:.2,z:.3}],'data:image/png;base64,iVBORw0KGgo=',{blob:'AAAA'}];
      const rows=[];
      for(const poison of poisons){
        /* Les **jumelles** : toutes bien formées, donc aucune ne peut être
           écartée avant d'atteindre la liste blanche. */
        const frame=R.readFrame({t:12,lifecycle:'active',
          hands:[{handedness:'left',primaryRatio:.4,quality:.9,leak:poison}],
          candidates:[{kind:'button',region:'body',
            boundsPx:{x:1,y:2,w:3,h:4,leak:poison},leak:poison}],
          events:[{type:'click',channel:'primary',axes:[],leak:poison}],
          gestures:[{name:'open_palm',phase:'start',suppressed:true,leak:poison}]});
        rows.push(JSON.stringify(frame));
        /* Et la poche imbriquée elle-même, qui est « la seule poche où tout
           pourrait passer » (même formulation qu'au § 10 pour `reachNorm`). */
        rows.push(JSON.stringify(R.readCandidate({kind:'button',region:'body',boundsPx:poison},0)));
      }
      out({rows,
        /* La garde tourne, et rend vrai : on la rappelle explicitement pour
           montrer qu'elle passe sur le schéma réel — l'épinglage de son
           **installation** est le test d'à côté. */
        guard:R.assertDerivedOnly(),
        /* Le schéma est la seule source de vérité du balayage : les clés
           balayées sont exactement celles des formes publiées. */
        shapes:{hand:Object.keys(R.BLANK_HAND),candidate:Object.keys(R.BLANK_CANDIDATE),
          event:Object.keys(R.BLANK_EVENT),gesture:Object.keys(R.BLANK_GESTURE),
          frame:Object.keys(R.BLANK_FRAME)}});
    """, "twins")

    assert result["guard"] is True
    for row in result["rows"]:
        for leak in ("leak", "blob", "data:image", '"z"'):
            assert leak not in row, f"une jumelle bien formée a fait passer « {leak} » : {row}"
    # Le balayage suit le schéma : une clé ajoutée à une forme y passe sans
    # qu'on y repense, et une clé ajoutée ailleurs ne passe nulle part.
    assert set(result["shapes"]["frame"]) == {"t", "lifecycle", "hands", "candidates",
                                              "events", "gestures"}


def test_reading_a_trace_twice_gives_the_same_trace(tmp_path):
    """**Une liste blanche qui ne sait pas se relire est un convertisseur.**

    La page envoie la géométrie d'une candidate dans `boundsPx` et une issue
    avec son `objectId` et sa liste d'axes ; une trace, elle, porte la
    géométrie à plat, un booléen et un compte. Le rejeu relit une trace **déjà
    normalisée** — c'est ce qui fait que la même liste blanche protège la page,
    le disque et le réseau. Une lecture qui ne connaîtrait que la première
    forme rendrait donc quatre `null` de géométrie et un `onObject` faux.

    Mesuré avant correction : le résolveur ne voyait plus **aucune** cible sur
    la trace d'or, et `click.target_success_ratio` valait 0 — une mesure qui
    disait « aucun clic n'a atteint sa cible » d'une séance où tous l'avaient
    atteinte. Le pire genre de nombre : faux, et crédible."""

    result = run_node(tmp_path, """
      const fromPage={t:12,lifecycle:'active',
        hands:[{handedness:'left',primaryRatio:.4,rawX:10,rawY:20,quality:.9}],
        candidates:[{kind:'button',region:'body',actionable:true,
          objectId:'sc-node-42',boundsPx:{x:600,y:300,w:140,h:44}}],
        events:[{type:'drag_move',channel:'primary',objectId:'star-7',axes:['x','y']}],
        gestures:[{name:'open_palm',phase:'start',suppressed:true}]};
      const once=R.readFrame(fromPage);
      const twice=R.readFrame(once);
      const thrice=R.readFrame(twice);
      out({once,twice,thrice});
    """, "idempotent")

    once, twice = result["once"], result["twice"]
    assert once == twice == result["thrice"], (
        "relire une trace déjà normalisée ne rend pas la même trace : "
        f"{once} puis {twice}"
    )
    # Et ce qui devait survivre a survécu, dans les deux formes.
    candidate = twice["candidates"][0]
    assert (candidate["x"], candidate["y"], candidate["w"], candidate["h"]) == (600, 300, 140, 44)
    assert twice["events"][0]["onObject"] is True
    assert twice["events"][0]["axes"] == 2


def test_a_recorder_refuses_any_dependency_that_is_not_in_its_contract(tmp_path):
    """**Une liste blanche, pas une liste noire.**

    La question n'est pas « ce nom est-il interdit ? » mais « ce nom est-il au
    contrat ? », et la réponse pour tout ce qui n'y est pas est non — y compris
    pour le nom que personne n'a encore inventé. Aucune des six dépendances
    permises ne peut transporter une image, une vidéo ni un point de main.

    Et l'échéance est **exigée** : un enregistrement qui ne peut pas s'arrêter
    tout seul dure tant que personne n'y pense, et ce qui observe sans fin est
    exactement ce que la décision 32 interdit d'installer."""

    result = run_node(tmp_path, HARNESS + """
      const refusals={};
      for(const name of ['video','canvas','landmarks','frame','image','getUserMedia',
                         'landmarker','stream','capture','save','profile','onMeasure'])
        refusals[name]=refused(()=>R.createRecorder(wiring({[name]:()=>{}}).deps));
      const ok=!!R.createRecorder(wiring().deps);
      // Sans horloge d'arrêt, pas d'enregistreur.
      const noClock=refused(()=>R.createRecorder({now:()=>0}));
      const halfClock=refused(()=>R.createRecorder({setTimeout:()=>1}));
      // `undefined` n'est pas une couture : la liste blanche ne doit pas être
      // plus stricte que la lecture.
      const undef=refused(()=>R.createRecorder(wiring({video:undefined}).deps));
      out({refusals,ok,noClock,halfClock,undef,allowed:Object.keys(wiring().deps).sort()});
    """, "deps")

    for name, code in result["refusals"].items():
        assert code == "barehands_trace_cannot_carry_raw_input", name
    assert result["ok"] is True
    assert result["noClock"] == "RangeError" and result["halfClock"] == "RangeError"
    assert result["undef"] is None


def test_the_two_dangerous_pairs_are_refused_at_construction_in_both_directions(tmp_path):
    """**Quinzième et seizième paires dangereuses de la tâche.**

    Toutes deux échouent de la façon qui se lit « l'utilisateur s'y prend
    mal » — c'est ce qui les rend pires qu'une exception :

    - `sampleEveryMs >= maxDurationMs` : l'enregistrement dit qu'il tourne, dure
      son temps, et rend **une seule image**. Chaque mesure du rejeu serait
      nulle ou dégénérée, et le banc d'essai accuserait une configuration là où
      rien n'a été mesuré ;
    - `maxFrames` en dessous de ce que l'échéance annoncée réclame : l'écran
      promet deux minutes, le plafond tombe au bout de vingt secondes, et la
      trace se relit comme une séance courte. Même espèce que
      `watchdogMs >= stepTimeoutMs` : le budget accordé doit couvrir le temps
      exigé.

    Les deux directions sont épinglées : ce qui doit passer passe."""

    result = run_node(tmp_path, HARNESS + """
      const at=options=>refused(()=>R.createRecorder(wiring({options}).deps));
      out({
        // Paire 15 : la cadence au-dessus, puis à égalité, puis en dessous.
        sampleAbove:at({sampleEveryMs:30000,maxDurationMs:20000,maxFrames:9000}),
        sampleEqual:at({sampleEveryMs:20000,maxDurationMs:20000,maxFrames:9000}),
        sampleBelow:at({sampleEveryMs:200,maxDurationMs:20000,maxFrames:9000}),
        // Paire 16 : le plafond juste en dessous, puis juste au niveau.
        ceilingShort:at({sampleEveryMs:100,maxDurationMs:20000,maxFrames:199}),
        ceilingExact:at({sampleEveryMs:100,maxDurationMs:20000,maxFrames:200}),
        // Et les bornes simples, qui ne sont pas des paires.
        zeroDuration:at({maxDurationMs:0}),
        negativeSample:at({sampleEveryMs:-1}),
        fractionalCeiling:at({maxFrames:12.5}),
        notANumber:at({maxFrames:'beaucoup'}),
        defaults:R.options({}),
      });
    """, "pairs")

    assert result["sampleAbove"] == "RangeError"
    assert result["sampleEqual"] == "RangeError", (
        "l'égalité est déjà la panne : une cadence égale à l'échéance ne retient qu'une image"
    )
    assert result["sampleBelow"] is None
    assert result["ceilingShort"] == "RangeError"
    assert result["ceilingExact"] is None, "le budget exact doit passer, pas seulement le large"
    assert result["zeroDuration"] == "RangeError"
    assert result["negativeSample"] == "RangeError"
    assert result["fractionalCeiling"] == "RangeError"
    assert result["notANumber"] == "RangeError"
    # Et les défauts publiés satisfont eux-mêmes les deux paires.
    assert result["defaults"] == {"maxDurationMs": 120000, "sampleEveryMs": 0, "maxFrames": 9000}


# ------------------------------------------------------------------ un enregistrement finit


def test_a_recording_stops_by_itself_on_its_deadline_and_on_its_frame_ceiling(tmp_path):
    """**Un enregistrement qui ne finit pas est la panne que la RÈGLE ZÉRO
    interdit**, et il l'est deux fois quand ce qui dure est une observation.

    Deux fins automatiques, et chacune **le dit** : l'échéance, qui ne dépend
    pas des images (une caméra figée laisserait sinon l'enregistrement « en
    cours » pour toujours), et le plafond d'images, qui **arrête** au lieu de
    tronquer en silence — une trace coupée sans le dire se relit comme une
    séance courte, et on conclurait sur ce que l'utilisateur n'a pas fait."""

    result = run_node(tmp_path, HARNESS + """
      // 1. L'échéance, sans qu'aucune image n'arrive : caméra figée.
      const stops=[];
      const a=recWith({options:{maxDurationMs:2000,maxFrames:500},
        onStop:trace=>stops.push(trace.stoppedBecause)});
      a.rec.start({viewport:{width:1280,height:720}});
      const armedWhileRecording=a.armed();
      a.advance(1000);
      const midway=a.rec.state();
      a.advance(1500);
      const afterDeadline={recording:a.rec.isRecording(),armed:a.armed(),
        frames:a.rec.state().frames};
      // Une image de plus après la fin ne compte pas.
      const acceptedAfter=a.rec.feed(frameAt(1,1,0.9,0.9));

      // 2. Le plafond d'images.
      const b=recWith({options:{maxDurationMs:60000,maxFrames:5},
        onStop:trace=>stops.push(trace.stoppedBecause)});
      b.rec.start({viewport:{width:1280,height:720}});
      let taken=0;
      for(let i=0;i<12;i+=1){b.advance(16);if(b.rec.feed(frameAt(i,i,0.9,0.9)))taken+=1}
      const atCeiling={recording:b.rec.isRecording(),frames:b.rec.trace().frames.length,
        dropped:b.rec.trace().droppedFrames,observed:b.rec.trace().observedFrames,
        armed:b.armed()};

      // 3. L'échantillonnage : une image sur N, et le compte le dit.
      const c=recWith({options:{maxDurationMs:60000,sampleEveryMs:100,maxFrames:600}});
      c.rec.start({viewport:{width:1280,height:720}});
      let kept=0;
      for(let i=0;i<60;i+=1){c.advance(16);if(c.rec.feed(frameAt(i,i,0.9,0.9)))kept+=1}
      const sampled={kept,observed:c.rec.state().observed,frames:c.rec.state().frames};
      out({stops,armedWhileRecording,midway,afterDeadline,acceptedAfter,taken,atCeiling,sampled});
    """, "ends")

    # L'échéance est armée pendant, et rendue après.
    assert result["armedWhileRecording"] == 1
    assert result["afterDeadline"] == {"recording": False, "armed": 0, "frames": 0}
    # Ce que l'écran affiche pendant : RÈGLE ZÉRO, trois des quatre points.
    assert result["midway"]["recording"] is True
    assert result["midway"]["elapsedMs"] == 1000
    assert result["midway"]["remainingMs"] == 1000
    # Après la fin, plus rien n'est retenu.
    assert result["acceptedAfter"] is False
    # Le plafond arrête, et la trace dit les trois nombres : vues, retenues, refusées.
    assert result["taken"] == 5
    assert result["atCeiling"]["recording"] is False
    assert result["atCeiling"]["frames"] == 5
    assert result["atCeiling"]["dropped"] == 1
    assert result["atCeiling"]["observed"] == 6
    assert result["atCeiling"]["armed"] == 0, "l'échéance doit être rendue quand le plafond arrête"
    # Les deux fins se nomment, et différemment.
    assert result["stops"] == ["deadline", "max_frames"]
    # L'échantillonnage retient une image sur ~6 à 16 ms de cadence.
    assert result["sampled"]["observed"] == 60
    # 60 images de 16 ms = 960 ms, une retenue toutes les 100 ms à partir de la
    # première : neuf. Le nombre exact, pas un intervalle — un intervalle
    # passerait aussi pour un échantillonnage qui ne marche pas.
    assert result["sampled"]["kept"] == result["sampled"]["frames"] == 9


# ------------------------------------------------------------------ le rejeu


def test_a_replay_is_deterministic_and_changing_one_axis_changes_the_numbers(tmp_path):
    """**Le critère d'acceptation de la Slice**, épinglé des deux côtés.

    Déterminisme : le rejeu n'a ni horloge, ni hasard, ni réseau, ni DOM — deux
    exécutions de la même trace sous la même configuration rendent des nombres
    **identiques**, comparés ici sérialisés.

    Et comparabilité : changer un axe change les nombres. Sans cette seconde
    moitié, un rejeu parfaitement déterministe qui ignorerait sa configuration
    passerait le premier test les yeux fermés — c'est exactement la forme
    « le test conduit autre chose que ce qu'il croit » que cette tâche a payée
    six fois."""

    trace = json.loads(GOLDEN.read_text(encoding="utf-8"))
    result = run_node(tmp_path, """
      const trace=%s;
      const deps={core:Core};
      const once=R.metricsOf(R.replay(trace,{},deps));
      const twice=R.metricsOf(R.replay(trace,{},deps));
      const rows=R.compare(trace,[
        {name:'usine',config:{}},
        {name:'filtre-doux',config:{filter:{minCutoffHz:0.3}}},
        {name:'seuils-hauts',config:{thresholds:{pressRatio:0.40,releaseRatio:0.50}}},
      ],deps);
      // Et comparer une seule configuration est refusé : cela ne dit rien.
      const alone=refused(()=>R.compare(trace,[{name:'seule',config:{}}],deps));
      out({once,twice,rows,alone,keys:R.METRIC_KEYS,axes:R.REPLAY_AXES});
    """ % json.dumps(trace), "replay")

    # Déterminisme, octet pour octet.
    assert json.dumps(result["once"], sort_keys=True) == json.dumps(result["twice"], sort_keys=True)
    assert result["alone"] == "RangeError"
    rows = {row["name"]: row["metrics"] for row in result["rows"]}
    assert set(rows) == {"usine", "filtre-doux", "seuils-hauts"}
    # Toutes les mesures du contrat sont rendues par chaque configuration.
    for name, metrics in rows.items():
        assert set(metrics) == set(result["keys"]), name
    # **L'axe du filtre change le pointeur.**
    assert rows["filtre-doux"]["pointer.stationary_jitter_p95_norm"] != \
        rows["usine"]["pointer.stationary_jitter_p95_norm"], \
        "changer le filtre ne change rien : le rejeu n'applique pas sa configuration"
    # **L'axe des seuils change le pincement**, et pas le pointeur.
    assert rows["seuils-hauts"]["interaction.latency_p50_ms"] != \
        rows["usine"]["interaction.latency_p50_ms"], \
        "changer les seuils ne change rien : l'hystérésis n'a pas reçu sa configuration"
    assert rows["seuils-hauts"]["pointer.error_p50_norm"] == rows["usine"]["pointer.error_p50_norm"]
    # Le nombre d'images mesurées, lui, ne dépend d'aucun réglage.
    assert len({row["metrics"]["replay.frames_count"] for row in result["rows"]}) == 1


def test_each_metric_means_what_its_name_says(tmp_path):
    """**Une mesure que personne n'épingle est une mesure qui dérive.**

    Les tests d'à côté vérifient qu'un rejeu est déterministe et qu'un axe
    change les nombres — mais un rejeu parfaitement déterministe dont le « 95e
    centile » serait une médiane, dont un « par seconde » serait un par
    milliseconde, dont le « tremblement au repos » compterait aussi les images
    où la main court, et qui ne retiendrait qu'une main sur deux, les passerait
    tous. Quatre mutations l'ont montré en survivant.

    Ce test-ci ne mesure donc pas une valeur, il mesure une **définition**, sur
    une trace construite pour que chacune ait une réponse connue :

    - une durée et un nombre de gestes étouffés connus : le taux doit être
      exactement leur quotient **en secondes** ;
    - de l'immobilité puis du mouvement franc : le tremblement au repos doit
      rester **sous** l'erreur générale, ce qui est faux s'il ne filtre pas ;
    - un 95e centile strictement au-dessus de la médiane ;
    - deux mains à chaque image de redimensionnement : la stabilité vaut 1, ce
      qui est faux si la seconde main n'est pas retenue."""

    result = run_node(tmp_path, """
      const H=(x,y,still)=>({handedness:'left',primaryRatio:.9,secondaryRatio:.9,
        rawX:x,rawY:y,quality:.9,stillness:still,speedPxPerSec:still>0.8?2:600});
      const frames=[];
      let t=0;
      /* Quarante images **immobiles** : la main tremble de deux pixels. */
      for(let i=0;i<40;i+=1){
        frames.push({t,lifecycle:'active',hands:[H(500+(i%3)-1,400,0.95)],
          candidates:[],events:[],gestures:[]});
        t+=16;
      }
      /* Vingt images de **course** : la main traverse l'écran, et le filtre
         traîne donc beaucoup plus. Ces images-là ne sont pas du tremblement. */
      for(let i=0;i<20;i+=1){
        frames.push({t,lifecycle:'active',hands:[H(500+40*i,400,0.05)],
          candidates:[],events:[],gestures:[]});
        t+=16;
      }
      /* Dix images de redimensionnement, **deux mains à chaque fois**. */
      for(let i=0;i<10;i+=1){
        frames.push({t,lifecycle:'active',
          hands:[H(300+i,200,0.5),H(700-i,240,0.5)],
          candidates:[],
          events:[{type:'resize',channel:'primary',objectId:'o',axes:['x','y']}],
          gestures:i<3?[{name:'open_palm',phase:'start',suppressed:true}]:[]});
        t+=16;
      }
      const durationMs=t-16;
      const trace={schema:'jarvis.barehands.trace',schemaVersion:1,
        viewport:{width:1000,height:600},durationMs,frames};
      const m=R.metricsOf(R.replay(trace,{},{core:Core}));
      out({m,durationMs,suppressed:3,frames:frames.length,
        hands:R.replay(trace,{},{core:Core}).frames.slice(-1)[0].hands.length});
    """, "definitions")

    m = result["m"]
    # **Deux mains sont retenues.** Une seule ferait tomber la stabilité à zéro.
    assert result["hands"] == 2
    assert m["resize.two_hand_stability_ratio"] == 1, (
        "chaque image de redimensionnement avait ses deux mains : la stabilité "
        "vaut 1, et 0 voudrait dire qu'une main sur deux n'est pas retenue"
    )
    # **Un taux est par seconde**, et c'est exactement le quotient.
    expected_hz = result["suppressed"] / (result["durationMs"] / 1000)
    assert m["gesture.false_positive_hz"] == pytest.approx(expected_hz, rel=1e-9), (
        "le taux de faux gestes n'est pas le nombre d'événements par seconde : "
        f"{m['gesture.false_positive_hz']} au lieu de {expected_hz}"
    )
    # **Le 95e centile est au-dessus de la médiane**, strictement : une main
    # immobile et une main qui court ne produisent pas la même erreur.
    assert m["pointer.error_p95_norm"] > m["pointer.error_p50_norm"], (
        "le 95e centile vaut la médiane : ce n'est pas un centile, c'est une moyenne déguisée"
    )
    # **Le tremblement au repos ne compte que les images immobiles.** Sans ce
    # filtre il inclurait la traversée d'écran, et vaudrait l'erreur générale.
    assert m["pointer.stationary_jitter_p95_norm"] < m["pointer.error_p95_norm"], (
        "le tremblement au repos vaut l'erreur générale : il ne filtre pas sur "
        "l'immobilité, et une main rapide se lit comme une main qui tremble"
    )
    # Et il reste une mesure, pas une absence.
    assert m["pointer.stationary_jitter_p95_norm"] > 0
    assert m["replay.frames_count"] == result["frames"]


def test_an_unknown_trace_version_is_refused_rather_than_guessed(tmp_path):
    """**Des nombres faux sont pires que pas de nombres.**

    Une trace d'une version que ce Jarvis ne lit pas se **refuse**, avec un
    code. Rejouée au jugé, elle rendrait des mesures qui n'ont aucun rapport
    avec ce qui a été enregistré — et elles seraient crues, parce qu'elles ont
    la forme de mesures. C'est la règle de ce dépôt (un refus codé plutôt qu'un
    défaut plausible), appliquée à un banc d'essai."""

    result = run_node(tmp_path, """
      const base={schema:'jarvis.barehands.trace',schemaVersion:1,
        viewport:{width:1280,height:720},durationMs:100,frames:[]};
      const deps={core:Core};
      out({
        current:!!R.replay(base,{},deps),
        future:refused(()=>R.replay({...base,schemaVersion:2},{},deps)),
        past:refused(()=>R.replay({...base,schemaVersion:0},{},deps)),
        other:refused(()=>R.replay({...base,schema:'autre.chose'},{},deps)),
        nothing:refused(()=>R.replay(null,{},deps)),
        noCore:refused(()=>R.replay(base,{},{})),
        /* **Le moteur à moitié là** (constat de la Slice 11). `{}` trébuche sur
           la garde d'au-dessus : elle ne nomme que `createPointerFilter` et
           `createPinchChannel`, si bien que la troisième exigence — le
           résolveur de cible — n'était jamais atteinte par un test. Un cœur
           partiel, lui, la touche. Sans résolveur, « combien de candidates
           existaient » se compterait pour « combien ont été résolues », et le
           taux de clics visés vaudrait 1 sans que rien ne l'ait mesuré : un
           nombre faux, avec la forme d'une mesure. */
        halfCore:refused(()=>R.replay(base,{},{core:{
          createPointerFilter:Core.createPointerFilter,
          createPinchChannel:Core.createPinchChannel,
          PINCH_CHANNEL:Core.PINCH_CHANNEL}})),
        version:R.TRACE_SCHEMA_VERSION,schema:R.TRACE_SCHEMA});
    """, "version")

    assert result["current"] is True
    assert result["future"] == "barehands_trace_version_unsupported"
    assert result["past"] == "barehands_trace_version_unsupported"
    assert result["other"] == "barehands_trace_schema_unknown"
    assert result["nothing"] == "barehands_trace_schema_unknown"
    # Et un rejeu sans les vrais moteurs est refusé : il mesurerait une copie.
    assert result["noCore"] == "RangeError"
    # Et un coeur qui a deux moteurs sur trois est refuse par la troisieme garde,
    # celle que `{}` n'atteignait jamais : un rejeu sans resolveur rendrait un
    # taux de clics vises de 1 que personne n'a mesure.
    assert result["halfCore"] == "RangeError"
    assert result["version"] == 1 and result["schema"] == "jarvis.barehands.trace"


def test_a_measurement_that_could_not_be_taken_is_null_and_never_zero(tmp_path):
    """**`Number(null) === 0` a déjà coûté une lecture fausse sur cette tâche**,
    où une valeur absente s'est lue comme une mesure au plancher. Un banc
    d'essai est l'endroit où cette confusion coûte le plus cher : « zéro faux
    pincement » et « on n'a pas pu compter les pincements » mènent à deux
    décisions opposées.

    Une trace vide rend donc `null` partout où il n'y avait rien à mesurer —
    et `0` là où il y avait quelque chose à compter et que le compte est zéro."""

    result = run_node(tmp_path, """
      const deps={core:Core};
      const empty=R.metricsOf(R.replay({schema:'jarvis.barehands.trace',schemaVersion:1,
        viewport:{width:1280,height:720},durationMs:0,frames:[]},{},deps));
      /* Une trace **sans largeur d'image** : les distances ne sont pas
         mesurables, et les rendre en pixels sous un nom normalisé serait un
         mensonge d'unité. */
      const noViewport=R.metricsOf(R.replay({schema:'jarvis.barehands.trace',schemaVersion:1,
        viewport:{width:0,height:0},durationMs:160,
        frames:[{t:0,lifecycle:'active',hands:[{handedness:'left',rawX:10,rawY:10,
          quality:.9,stillness:.9,primaryRatio:.9}],candidates:[],events:[],gestures:[]}]},{},deps));
      out({empty,noViewport});
    """, "nulls")

    empty = result["empty"]
    # Ce qui se compte vaut zéro ; ce qui se mesure vaut `null`.
    assert empty["replay.frames_count"] == 0
    for key in ("click.target_success_ratio", "pointer.error_p50_norm",
                "pointer.error_p95_norm", "pointer.stationary_jitter_p95_norm",
                "interaction.latency_p50_ms", "hand.loss_recovery_p95_ms",
                "drag.continuity_ratio", "resize.two_hand_stability_ratio",
                "pinch.false_primary_hz", "pinch.false_secondary_hz",
                "gesture.false_positive_hz"):
        assert empty[key] is None, f"{key} vaut {empty[key]!r} au lieu de null sur une trace vide"
    # Sans largeur d'image, aucune distance n'est rendue — pas même zéro.
    assert result["noViewport"]["pointer.error_p50_norm"] is None
    assert result["noViewport"]["replay.frames_count"] == 1


# ------------------------------------------------------------------ le coût


def test_recording_costs_nothing_when_nobody_records(tmp_path):
    """**Le budget d'images est exactement celui d'avant**, et c'est la
    contrainte dure de cette Slice.

    La couture de mesures est **posée sur les dépendances du contrôleur**, pas
    dans une branche qu'il évaluerait : hors enregistrement et hors calibration
    la clé n'existe pas, donc aucun enregistrement de scalaires n'est construit.
    Une fonction toujours présente qui rendrait tout de suite aurait fait payer
    à chaque session le coût d'une fonctionnalité que personne n'a lancée.

    Et la couture est **relisible** : `measureSeam()` dit qui écoute. Sans
    cette lecture, « l'enregistreur écoute » et « quelqu'un a fermé la couture
    sous lui » s'écriraient pareil — la Slice 09 a ajouté `measuring()` pour
    exactement cette raison, après qu'une mutation eut survécu."""

    result = run_page(tmp_path, CAMERA + browser() + TIMERS + """
      await openTab();
      await BAREHANDS.enable();
      await settle();
      const atRest={measuring:BAREHANDS.measuring(),seam:BAREHANDS.measureSeam(),
        recording:BAREHANDS.record.state().recording};
      // Soixante images d'interaction sans enregistrement : rien n'est mesuré.
      const frames=BAREHANDS.adapters.interaction;
      for(let i=0;i<60;i+=1)frames.hover([]);
      const stillAtRest={measuring:BAREHANDS.measuring(),seam:BAREHANDS.measureSeam()};
      // On enregistre : la couture s'ouvre, et elle dit qui l'a ouverte.
      const started=BAREHANDS.record.start({options:{maxDurationMs:60000,maxFrames:400}});
      const during={measuring:BAREHANDS.measuring(),seam:BAREHANDS.measureSeam(),
        recording:BAREHANDS.record.state().recording};
      const stopped=BAREHANDS.record.stop();
      const after={measuring:BAREHANDS.measuring(),seam:BAREHANDS.measureSeam(),
        recording:BAREHANDS.record.state().recording};
      /* **Et la fin d'un parcours n'emporte pas l'enregistrement.**
         `exitOverlay()` appelle `stopMeasuring()` : tant que la couture était
         une clé unique posée et **supprimée** par son dernier utilisateur,
         fermer une surimpression aurait coupé une séance en cours sans que
         rien ne le dise — l'enregistreur aurait continué de se croire en
         train d'enregistrer, et la trace se serait arrêtée à l'image où
         quelqu'un a appuyé sur Échap. C'est le chemin exact, joué ici sur la
         vraie page. */
      BAREHANDS.record.start({options:{maxDurationMs:60000,maxFrames:400}});
      await BAREHANDS.tutorial();
      const duringFlow=BAREHANDS.measureSeam();
      await BAREHANDS.exitOverlay();
      const afterFlow={seam:BAREHANDS.measureSeam(),
        recording:BAREHANDS.record.state().recording};
      BAREHANDS.record.stop();
      out({atRest,stillAtRest,started,during,stopped,after,duringFlow,afterFlow,
        finalSeam:BAREHANDS.measureSeam(),
        /* Et `stopMeasuring` ferme bien une couture **nommée** plutôt que de
           supprimer la clé : c'est ce qui rend l'assertion ci-dessus autre
           chose qu'une coïncidence d'ordre. */
        named:require('fs').readFileSync(SCRIPT_PATH,'utf8')
          .includes("closeMeasureSeam('calibration')")});
    """, "cost")

    # Au repos, personne n'écoute : la clé n'existe pas.
    assert result["atRest"] == {"measuring": False, "seam": [], "recording": False}
    assert result["stillAtRest"] == {"measuring": False, "seam": []}
    # Pendant, l'enregistreur écoute — et il est nommé.
    assert result["started"]["ok"] is True
    assert result["during"] == {"measuring": True, "seam": ["recorder"], "recording": True}
    # Après, plus personne.
    assert result["stopped"]["ok"] is True
    assert result["after"] == {"measuring": False, "seam": [], "recording": False}
    # Un parcours ouvert par-dessus ne prend pas la couture à l'enregistreur…
    assert result["duringFlow"] == ["recorder"]
    # …et sa fermeture, qui appelle `stopMeasuring()`, ne l'emporte pas.
    assert result["afterFlow"]["seam"] == ["recorder"], (
        "fermer une surimpression a emporté la couture de l'enregistreur : "
        "la séance se serait arrêtée à cette image sans que rien ne le dise"
    )
    assert result["afterFlow"]["recording"] is True
    assert result["named"] is True, (
        "`stopMeasuring` supprime la clé au lieu de fermer une couture nommée : "
        "l'assertion du dessus ne tiendrait que par l'ordre des appels"
    )
    assert result["finalSeam"] == []


def test_the_screen_says_a_recording_is_running_and_how_to_get_out(tmp_path):
    """**RÈGLE ZÉRO, appliquée à une fonctionnalité qui observe.** Ce qui
    observe sans le dire est ce que personne n'accepte.

    L'écran doit dire **que** ça tourne, **quoi**, **depuis combien de temps**,
    et **comment en sortir**. Les trois premiers sont dans la ligne d'état, le
    quatrième est le bouton « Arrêter ». Et il doit dire, en toutes lettres, ce
    qui n'est pas retenu."""

    result = run_page(tmp_path, CAMERA + browser() + TIMERS + """
      await openTab();
      const section=()=>{const el=document.getElementById('barehandsRecordState');
        return el?el.innerHTML:''};
      const idle=section();
      await BAREHANDS.enable();
      await settle();
      // Éteint, la porte refuse et le dit.
      await BAREHANDS.disable();
      await settle();
      const offRefusal=BAREHANDS.record.start();
      await BAREHANDS.enable();
      await settle();
      BAREHANDS.record.start({options:{maxDurationMs:60000,maxFrames:400}});
      const running=section();
      const stopButton=document.getElementById('barehandsRecordStop');
      const startButton=document.getElementById('barehandsRecordStart');
      const buttons={stopEnabled:!stopButton.disabled,startDisabled:!!startButton.disabled};
      BAREHANDS.record.stop();
      out({idle,offRefusal,running,buttons,
        afterStop:{stop:!!document.getElementById('barehandsRecordStop').disabled,
          start:!document.getElementById('barehandsRecordStart').disabled}});
    """, "screen")

    # Au repos, l'écran dit ce qu'un enregistrement retient — et ce qu'il ne
    # retient pas, ce qui est la phrase qui compte.
    assert "Rien n’est enregistré" in result["idle"]
    assert "jamais une image" in result["idle"] and "points de votre main" in result["idle"]
    # Éteint, la porte refuse avec son code et sa phrase.
    assert result["offRefusal"]["ok"] is False
    assert result["offRefusal"]["code"] == "barehands_recorder_disabled"
    assert "Activer Barehands" in result["offRefusal"]["reason"]
    # Pendant : que ça tourne, combien, depuis quand, et jusqu'à quand.
    assert "Enregistrement en cours" in result["running"]
    assert "image(s) retenue(s)" in result["running"]
    assert "écoulée(s)" in result["running"]
    assert "il s’arrête tout seul dans" in result["running"]
    # Et la sortie : le bouton « Arrêter » est armé pendant, et seulement pendant.
    assert result["buttons"] == {"stopEnabled": True, "startDisabled": True}
    assert result["afterStop"] == {"stop": True, "start": True}


# ------------------------------------------------------------------ les épinglages


def test_the_page_inserts_the_recorder_after_the_tutorial_and_before_the_pointer(tmp_path):
    """Constat F3 de la Slice 00 : un module de page ajouté déplace l'ordre
    d'insertion, et l'ordre est un contrat. L'enregistreur lit les contrats, et
    le pointeur le lit pour poser `record` sur une surface **gelée** : il vient
    donc après les premiers et avant le second.

    Servi, le repère a disparu — une balise laissée en place serait un module
    absent que personne ne verrait, la page n'ayant qu'un seul `<script>`."""

    from jarvis.runtime.control_center import (
        BAREHANDS_CALIBRATION_SCRIPT_MARKER, BAREHANDS_COMMANDS_SCRIPT_MARKER,
        BAREHANDS_CONTRACTS_SCRIPT_MARKER, BAREHANDS_RECORDER_SCRIPT_MARKER,
        BAREHANDS_SCRIPT_MARKER, BAREHANDS_TARGET_SCRIPT_MARKER,
        BAREHANDS_TUTORIAL_SCRIPT_MARKER, SCENE_PAGE_SCRIPT_MARKER, ControlCenter,
    )

    import asyncio

    raw = (RUNTIME / "control_center.html").read_text(encoding="utf-8")
    control = ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path,
                            barehands_vendor_root=tmp_path / "vendor")
    served = asyncio.run(control.index(None)).text

    order = [BAREHANDS_CONTRACTS_SCRIPT_MARKER, BAREHANDS_TARGET_SCRIPT_MARKER,
             BAREHANDS_CALIBRATION_SCRIPT_MARKER, BAREHANDS_TUTORIAL_SCRIPT_MARKER,
             BAREHANDS_RECORDER_SCRIPT_MARKER, BAREHANDS_SCRIPT_MARKER,
             BAREHANDS_COMMANDS_SCRIPT_MARKER, SCENE_PAGE_SCRIPT_MARKER]
    places = [raw.index(marker) for marker in order]
    assert places == sorted(places), "l'ordre d'insertion documenté n'est pas celui de la page"
    assert BAREHANDS_RECORDER_SCRIPT_MARKER not in served, "le repère n'a pas été remplacé"
    assert served.index("root.JarvisBarehandsTutorial=api") \
        < served.index("root.JarvisBarehandsRecorder=api") \
        < served.index("window.JarvisBarehands=Object.freeze(")


def test_every_recorder_constant_is_pinned_against_its_counterpart(tmp_path):
    """**Une constante nouvelle sans test de parité est une constante qui
    dérive.** Il y a ici trois miroirs, et aucun ne peut bouger seul :

    - le vocabulaire de types de cible de la trace contre celui que le module
      de cible collecte réellement (`JarvisBarehandsTarget.KINDS`) — la trace le
      ferme parce que le contrat le laisse en texte libre, et un type ajouté
      d'un côté seulement deviendrait `other` sans que personne ne le voie ;
    - les mesures et la version du schéma contre le miroir Python, qui est ce
      que le Test Lab et la route lisent ;
    - les vocabulaires fermés contre ceux du contrat."""

    result = run_node(tmp_path, """
      out({kinds:R.TRACE_KINDS,other:R.TRACE_KIND_OTHER,
        collected:T.KINDS.map(entry=>entry.kind),
        metrics:R.METRIC_KEYS,axes:R.REPLAY_AXES,version:R.TRACE_SCHEMA_VERSION,
        schema:R.TRACE_SCHEMA,
        contracts:{handedness:C.HANDEDNESSES,lifecycles:C.LIFECYCLES,
          interactions:C.INTERACTIONS,channels:C.PINCH_CHANNELS,regions:C.REGIONS,
          representations:C.ZONED_REPRESENTATIONS,gestures:C.GESTURES,
          phases:C.GESTURE_PHASES}});
    """, "parity")

    from jarvis.runtime import barehands_replay, barehands_trace

    # Le vocabulaire de la trace couvre exactement ce que la page collecte,
    # plus `unknown` (le contrat le produit) et `other` (le repli de la trace).
    assert set(result["collected"]) | {"unknown", result["other"]} == set(result["kinds"])
    assert result["other"] == "other" and result["other"] in result["kinds"]
    # Les mesures et la version : JS et Python disent la même chose.
    assert tuple(result["metrics"]) == barehands_replay.METRIC_KEYS, (
        "le module JS et son miroir Python ne nomment pas les mêmes mesures, "
        "ou pas dans le même ordre : une colonne de banc d'essai décalée est "
        "pire qu'une colonne absente"
    )
    assert tuple(result["axes"]) <= tuple(barehands_replay.REPLAY_AXES)
    assert result["version"] == barehands_trace.SCHEMA_VERSION
    assert result["schema"] == barehands_trace.TRACE_SCHEMA
    # Les vocabulaires fermés : contrat JS, miroir Python.
    assert tuple(result["contracts"]["handedness"]) == barehands_trace.HANDEDNESSES
    assert tuple(result["contracts"]["lifecycles"]) == barehands_trace.LIFECYCLES
    assert tuple(result["contracts"]["interactions"]) == barehands_trace.INTERACTIONS
    assert tuple(result["contracts"]["channels"]) == barehands_trace.PINCH_CHANNELS
    assert tuple(result["contracts"]["regions"]) == barehands_trace.REGIONS
    assert tuple(result["contracts"]["representations"]) == barehands_trace.REPRESENTATIONS
    assert tuple(result["contracts"]["gestures"]) == barehands_trace.GESTURES
    assert tuple(result["contracts"]["phases"]) == barehands_trace.GESTURE_PHASES
    assert tuple(result["kinds"]) == barehands_trace.TRACE_KINDS


def test_the_contract_document_lists_the_same_metrics_and_axes_as_the_code():
    """**Une table de contrat qui dérive est pire qu'une table absente**, parce
    qu'un lecteur l'utilise. Le § 14 nomme les douze mesures, les quatre axes de
    rejeu et les trois codes de refus ; ce sont ceux du code, ou ce test tombe.

    Même épinglage que la table des dix étapes du § 13."""

    from jarvis.runtime import barehands_replay, barehands_trace

    text = CONTRACT_DOC.read_text(encoding="utf-8")
    assert "## 14. Enregistrement, rejeu et mesures" in text
    section = text[text.index("## 14. Enregistrement"):]
    section = section[:section.index("\n## ") if "\n## " in section else len(section)]

    for key in barehands_replay.METRIC_KEYS:
        assert f"`{key}`" in section, (
            f"la table du § 14 ne nomme pas « {key} » : une table de contrat qui "
            "abrège est une table qu'un lecteur complète de travers"
        )
    for axis in barehands_replay.REPLAY_AXES:
        assert f"`{axis}`" in section, axis
    for code in ("barehands_trace_schema_unknown", "barehands_trace_version_unsupported",
                 "barehands_trace_invalid", "barehands_trace_cannot_carry_raw_input"):
        assert code in section, code
    # Les deux paires dangereuses, nommées par leur rang dans la tâche.
    assert "quinzième et seizième" in section
    assert "sampleEveryMs >= maxDurationMs" in section
    # Et la phrase qui porte la décision : ce qu'une trace ne contient pas.
    assert "Aucun point de main. Aucune image. Aucune vidéo. Aucun identifiant." in section
    # Le schéma et sa version disent la même chose que le code.
    assert barehands_trace.TRACE_DIRNAME in section
    # Les six dépendances permises de `createRecorder`, nommées une à une.
    for dependency in ("options", "now", "log", "onStop", "setTimeout", "clearTimeout"):
        assert f"`{dependency}`" in section, dependency
