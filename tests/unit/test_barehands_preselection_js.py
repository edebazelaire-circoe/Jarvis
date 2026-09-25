"""Présélection bornée des cibles (tâche adaptative, Slice 05), par node.

Décision 49 : avant le pincement, la main qui **vise** voit quelle cible serait
prise — étoiles comprises, sans qu'aucune étoile devienne une zone de
manipulation —, et cette cible est **la même décision** que celle que la
descente fige. L'assistance est bornée par l'ambiguïté entre voisines, une
hystérésis de sélection empêche l'aperçu de clignoter entre deux voisines, et
les trois nombres se règlent par le chemin d'essai unique (décision 48).

Ce qui est vérifié ici, sur le **vrai** résolveur et la vraie page (double de
DOM de l'aperçu) : aperçu === prise sous intention stable (une propriété sur
des tirages, plus le chemin de la page) ; l'intérieur d'une cible gagne
toujours ; entre deux voisines équidistantes, rien ; l'hystérésis tient et
coupée elle clignote ; une étoile se présélectionne sans zone ; un bouton se
présélectionne sous intention de pointer seulement ; le jeton n'est jamais
déplacé ; un essai d'assistance change la portée et se défait exactement ; la
télémétrie ne porte que des scalaires ; l'exercice de sélection de l'étape de
visée compte ses erreurs dans une ligne de mesures du contrat.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from test_barehands_calibration_js import DOM, DRIVER  # noqa: E402
from test_barehands_target_js import BROWSER, HAND, run_node as run_page  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
BAREHANDS = RUNTIME / "control_center_barehands.js"
CONTRACTS = RUNTIME / "control_center_barehands_contracts.js"
RECORDER = RUNTIME / "control_center_barehands_recorder.js"
CALIBRATION = RUNTIME / "control_center_barehands_calibration.js"
HAND_ART = RUNTIME / "control_center_barehands_hand_art.js"
TARGET = RUNTIME / "control_center_barehands_target.js"
DOC = ROOT / "docs" / "barehands-contracts.md"


def run_node(tmp_path: Path, source: str, name: str = "preselect") -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"barehands-{name}.cjs"
    script.write_text(
        f"const C=require({json.dumps(str(CONTRACTS))});\n"
        "global.JarvisBarehandsContracts=C;\n"
        f"const R=require({json.dumps(str(RECORDER))});\n"
        "global.JarvisBarehandsRecorder=R;\n"
        f"const B=require({json.dumps(str(BAREHANDS))});\n"
        f"global.JarvisBarehandsHandArt=require({json.dumps(str(HAND_ART))});\n"
        f"const K=require({json.dumps(str(CALIBRATION))});\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "const refused=fn=>{try{fn();return null}catch(e){return e.code||e.name||String(e)}};\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True,
                          encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


#: Des étoiles (`point`, sans zones) et un résolveur réel. `walk` rejoue une
#: suite d'images pour une main et rend l'identité visée à chacune.
PURE = """
const resolver=o=>B.createTargetResolver(Object.assign({pickRegion:C.pickRegion},o||{}));
const starAt=(id,cx,cy,size)=>({objectId:id,kind:'scene_object',representation:'point',
  zoned:false,actionable:true,boundsPx:{x:cx-size/2,y:cy-size/2,w:size,h:size}});
const refs=list=>list.map((c,i)=>Object.assign({},c,{ref:i}));
const step=(r,list,state,x,y,assistance)=>r.update({now:0,candidates:refs(list),
  hands:[{handTrackId:1,channel:'primary',state,x,y,assistance}]})[0]||null;
const walk=(r,list,frames)=>frames.map(([state,x,y])=>{const t=step(r,list,state,x,y);return t?t.objectId:null});
"""


# ------------------------------------------------------------------ une décision


def test_the_previewed_target_is_the_captured_target_under_stable_intent(tmp_path):
    """**Une seule décision.** L'aperçu (survol puis approche) et la prise (la
    descente) sont rendus par le **même** résolveur, sous la même tenue. La
    propriété exacte : quelle qu'ait été l'histoire du jeton (tremblement,
    passages entre voisines), **au même point** la descente rend la cible que
    l'aperçu montrait — la décision est idempotente sous sa propre mémoire.
    Vérifiée sur 400 tirages de voisines (tailles, écarts, point visé, histoire
    tremblée de ±3 px), puis la cible figée ne bouge plus."""

    result = run_node(tmp_path, PURE + """
      let seed=7;const rnd=()=>{seed=(seed*1103515245+12345)%2147483648;return seed/2147483648};
      let cases=0,equal=0,previewed=0;const broken=[];
      for(let n=0;n<400;n+=1){
        const size=10+Math.round(rnd()*20),gap=2+Math.round(rnd()*40);
        const a=starAt('a',300,300,size),b=starAt('b',300+size+gap,300,size);
        const c=starAt('c',300+size/2+gap/2,300+size+gap+rnd()*gap,size);
        const list=[a,b,c];
        const r=resolver({});
        const x0=300+rnd()*(size+gap),y0=300+(rnd()-.5)*size*2;
        const jitter=()=>(rnd()-.5)*6;
        for(let i=0;i<6;i+=1)step(r,list,'hover',x0+jitter(),y0+jitter());
        const last=step(r,list,'hover',x0,y0);
        const shown=last?last.objectId:null;
        const approach=step(r,list,'pinching',x0,y0);
        const down=step(r,list,'pressed',x0,y0);
        const held=step(r,list,'pressed',x0+60,y0+60);
        cases+=1;if(shown!==null)previewed+=1;
        const got=down?down.objectId:null;
        if(got===shown&&(approach?approach.objectId:null)===shown&&(!down||down.locked&&held&&held.objectId===got))equal+=1;
        else broken.push({size,gap,x0,y0,shown,got});
      }
      out({cases,equal,previewed,broken:broken.slice(0,3)});
    """)
    assert result["cases"] == 400
    assert result["broken"] == []
    assert result["equal"] == 400
    # Les tirages ne sont pas tous ambigus : la propriété porte sur de vraies
    # présélections, pas sur « rien montré, rien pris ».
    assert result["previewed"] > 250


def test_a_steady_hand_does_not_flicker_between_well_separated_neighbours(tmp_path):
    """Le tremblement réel d'une main posée (±2 px) près du milieu de deux
    voisines séparées de 40 px : la bande de tenue (`[0,8 ; 1,25]` en rapport
    de distances, 4,4 px de large ici) l'absorbe — aucune bascule sur 300
    images. La largeur de cette bande est `écart / 9`, au plus
    `targetSwitchPx` : sous ~20 px d'écart, un tremblement de ±2 px peut
    basculer, et c'est le prix de ne jamais voler la voisine (reprise QA)."""

    result = run_node(tmp_path, PURE + """
      let seed=5;const rnd=()=>{seed=(seed*1103515245+12345)%2147483648;return seed/2147483648};
      const A=starAt('a',100,100,20),Bx=starAt('b',160,100,20);   // écart 40 px (110 → 150)
      const r=resolver({});
      step(r,[A,Bx],'hover',120,100);
      let switches=0;const seen=new Set();
      for(let i=0;i<300;i+=1){
        const t=step(r,[A,Bx],'hover',130+(rnd()-.5)*4,100+(rnd()-.5)*4);
        if(r.decisions()[0].switched)switches+=1;seen.add(t?t.objectId:null);
      }
      out({switches,seen:[...seen]});
    """)
    assert result == {"switches": 0, "seen": ["a"]}


def test_the_aimed_target_wins_when_the_fingertip_drifts_during_the_approach(tmp_path):
    """**Reprise QA, MAJEUR 1.** Pendant l'approche (rapport qui descend,
    contact encore ouvert), le bout de l'index dérive vers le pouce. Le jeton
    le suivait, la présélection passait sur la voisine B et la gardait ;
    au passage à `pinching` le jeton revenait d'un bond sur A — et la descente
    prenait B. Deux corrections, deux preuves :

    1. le **traqueur** publie le point tenu dès que le rapport descend : pas
       un pixel de dérive entre la dernière posture ouverte et le contact ;
    2. même si un jeton dérivait, la **tenue bornée** ne garde plus la
       voisine : la séquence rejouée (dérive puis saut de retour) prend A,
       comme avant la Slice 05."""

    result = run_page(tmp_path, HAND + """
      const VIEWPORT={width:1920,height:1080};
      const tracker=B.createHandTracker({});
      const frames=[];
      for(let i=0;i<=10;i+=1)frames.push(tracker.update({landmarks:[PINCHING(Math.min(1,i/6),{cx:.5,cy:.45})]},
        {viewport:VIEWPORT,aspect:16/9,now:i*16}).tokens[0]);
      const far=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y);
      const firstClosed=frames.findIndex(t=>t.state!=='open');
      const tip=far({x:frames[firstClosed].filteredX,y:frames[firstClosed].filteredY},{x:frames[0].filteredX,y:frames[0].filteredY});
      const drift=Math.max(...frames.map(t=>far(t,frames[0])));
      /* La séquence du constat, sur le résolveur seul. */
      const r=B.createTargetResolver({pickRegion:C.pickRegion});
      const st=(id,cx,cy,s)=>({objectId:id,kind:'scene_object',representation:'point',zoned:false,actionable:true,
        boundsPx:{x:cx-s/2,y:cy-s/2,w:s,h:s}});
      const L=[st('A',100,100,16),st('B',100,130,16)].map((c,i)=>({...c,ref:i}));
      const f=(state,y)=>{const t=r.update({now:0,candidates:L,hands:[{handTrackId:1,channel:'primary',state,x:100,y,assistance:.5}]})[0];return t?t.objectId:null};
      const replay=[f('hover',113),f('hover',113),f('hover',117),f('hover',121),f('hover',124),
        f('pinching',113),f('pinching',113),f('pressed',113),f('pressed',140)];
      out({tip:Number(tip.toFixed(1)),drift:Number(drift.toFixed(3)),states:[frames[0].state,frames[firstClosed].state],replay});
    """)
    assert result["tip"] > 10, "le bout de l'index a bien bougé en se refermant"
    assert result["drift"] == 0.0, "le jeton ne montre aucune dérive pendant l'approche"
    assert result["replay"] == ["A", "A", "B", "B", "B", "A", "A", "A", "A"]


def test_the_page_shows_the_star_it_will_take_and_takes_it_without_moving_the_token(tmp_path):
    """Le chemin de la page, image par image : une main qui **vise**
    (`pointing: true`) survole deux étoiles voisines ; l'anneau se pose sur la
    plus proche, discret (`data-hover="1"`), nommé dessous ; elle pince ; la
    cible publiée puis figée est **celle** de l'anneau. Et le jeton reste où
    la main l'a mis : la présélection montre, elle ne déplace rien."""

    result = run_page(tmp_path, BROWSER + """
      const a=star('obj-a',{left:300,top:300,width:20,height:20},'point','Étoile A');
      const b=star('obj-b',{left:336,top:300,width:20,height:20},'point','Étoile B');
      global.page=[a,b];
      const aim=(x,y)=>Object.assign(token(1,x,y),{pointing:true});
      const look=()=>{const el=previews()[0];
        return el?{host:el.parent&&el.parent.dataset&&el.parent.dataset.objectId,hover:el.attrs['data-hover'],
          representation:el.attrs['data-representation'],region:el.attrs['data-region'],
          zone:el.children[0].style.display,name:el.children[1].textContent}:null};
      const t1=aim(324,310);
      frame([t1],[contact(1,'open')]);
      const hovered={look:look(),published:interaction.targets().length,token:[t1.x,t1.y]};
      const t2=aim(325,311);
      frame([t2],[contact(1,'pinching')]);
      const approaching={look:look(),target:interaction.targets()[0]&&interaction.targets()[0].objectId};
      const t3=aim(324,310);
      frame([t3],[contact(1,'pressed')]);
      const down=interaction.targets()[0];
      out({hovered,approaching,down:{id:down.objectId,locked:down.locked,region:down.region,zone:down.zone},
        token:[t3.x,t3.y]});
      interaction.clear();
    """)
    hovered = result["hovered"]
    assert hovered["look"] == {"host": "obj-a", "hover": "1", "representation": "point",
                               "region": "body", "zone": "none", "name": "Étoile A"}
    # Un survol se montre, il ne se publie pas : `targets()` reste l'intention.
    assert hovered["published"] == 0
    assert hovered["token"] == [324, 310]
    assert result["approaching"]["target"] == "obj-a"
    assert result["approaching"]["look"]["hover"] == "0"
    assert result["down"] == {"id": "obj-a", "locked": True, "region": "body", "zone": None}
    assert result["token"] == [324, 310], "le jeton n'est jamais déplacé vers la cible"


# ------------------------------------------------------------ bornes et tenue


def test_neighbours_bound_the_assistance_and_the_inside_always_wins(tmp_path):
    """L'assistance est une portée, **bornée par l'ambiguïté** : une étoile
    seule à 20 px se prend ; la même avec une voisine à 22 px ne se prend pas
    (20/22 > 0,8) ; au milieu exact de deux voisines, rien ; deux fois plus
    près de l'une (10 contre 20 px), elle. Une cible **tenue** reste dans la
    bande ambiguë, cède dès que la voisine est une prise franche, et ne vole
    jamais celle qu'on touche. Et quand une étoile est posée sur une fenêtre
    tenue, entrer dans l'étoile la prend : l'intérieur gagne, le dessus
    d'abord."""

    result = run_node(tmp_path, PURE + """
      const A=starAt('a',100,100,20),Bx=starAt('b',150,100,20);
      const one=r=>{const t=r;return t?[t.objectId,Number(t.ambiguity.toFixed(3))]:null};
      const alone=one(step(resolver({}),[A],'pinching',130,100));
      const crowded=one(step(resolver({}),[A,starAt('n',162,100,20)],'pinching',130,100));
      const decisions=(()=>{const r=resolver({});step(r,[A,starAt('n',162,100,20)],'pinching',130,100);
        return r.decisions().map(d=>[d.reason,Number(d.ambiguity.toFixed(3)),d.key])})();
      const middle=one(step(resolver({}),[A,Bx],'pinching',125,100));
      const nearA=one(step(resolver({}),[A,Bx],'pinching',120,100));
      const cutBound=one(step(resolver({targetAmbiguityMax:1}),[A,Bx],'pinching',125,100));
      /* Tenue : A prise à 118 ; à 126 (16 contre 14 px, rapport 1,14) A reste ;
         à 128 (18 contre 12, rapport 1,5 : B serait une prise franche) B ; puis
         retour à 124 : B tenue. */
      const r=resolver({});
      const held=walk(r,[A,Bx],[['hover',118,100],['hover',124,100],['hover',126,100],['hover',128,100],['hover',124,100]]);
      /* Le constat QA : tenue réglée au plus large, le jeton à 1 px de B. */
      const wide=(()=>{const r=resolver({targetSwitchPx:12,targetAmbiguityMax:.5});
        return walk(r,[A,Bx],[['hover',100,100],['hover',120,100],['hover',130,100],['hover',139,100]])})();
      /* Une étoile posée sur une fenêtre, citée en tête (celle du dessus). */
      const W={objectId:'w',kind:'scene_object',representation:'window',zoned:true,actionable:true,boundsPx:{x:0,y:0,w:300,h:200}};
      const S=starAt('s',150,100,20);
      const over=(()=>{const r=resolver({});return walk(r,[S,W],[['hover',60,60],['hover',150,100]])})();
      out({alone,crowded,decisions,middle,nearA,cutBound,held,wide,over,
        search:[resolver({}).reach(.5),resolver({}).searchRadius(.5),resolver({targetAmbiguityMax:.5}).searchRadius(1)]});
    """)
    assert result["alone"] == ["a", 0]
    assert result["crowded"] is None, "une voisine presque aussi proche interdit la prise hors cadre"
    assert result["decisions"] == [["ambiguous", 0.909, None]]
    assert result["middle"] is None
    assert result["nearA"] == ["a", 0.5]
    # La borne coupée (1), la plus proche gagne même au milieu (première citée).
    assert result["cutBound"][0] == "a"
    assert result["held"] == ["a", "a", "a", "b", "b"]
    # Même au plus large, la tenue ne garde pas A à 1 px de B.
    assert result["wide"] == ["a", "a", "a", "b"]
    assert result["over"] == ["w", "s"], "l'intérieur de l'étoile du dessus gagne sur la fenêtre tenue"
    # La collecte cherche les voisines au-delà de la portée : portée / borne.
    assert result["search"] == [24, 30, 96]


def test_the_hold_rule_at_its_bounds(tmp_path):
    """Les bornes exactes de la tenue, portée étendue (assistance 1 → 48 px) :

    - rapport à la borne (`d(voisine) = 0,8 × d(tenue)`, 28 contre 35) et
      écart sous `targetSwitchPx` (7 < 8) : A tenue, ambiguïté rendue **1**
      (bornée, la voisine est plus proche) ;
    - un pixel de plus vers B (27 contre 35) : B, prise franche ;
    - écart **égal** à `targetSwitchPx` (32 contre 40, rapport à la borne) : B ;
    - tenue hors de portée (26 px, assistance 0,5 → 24) même dans la bande : A
      n'est plus tenue, et B (21/26 = 0,81) est ambiguë : rien.
    Plus : une candidate en double (même identité) n'est pas une voisine ; la
    borne d'ambiguïté se borne à [0,5 ; 1] ; `configure` garde les options
    courantes."""

    result = run_node(tmp_path, PURE + """
      const box=(id,x,w)=>({objectId:id,kind:'scene_object',representation:'point',zoned:false,actionable:true,
        boundsPx:{x,y:90,w,h:20}});
      const seq=(Bx,x,assistance)=>{const r=resolver({});const A=box('a',0,20);const B=box('b',Bx,20);
        step(r,[A,B],'hover',10,100,assistance);const t=step(r,[A,B],'hover',x,100,assistance);
        return t?[t.objectId,Number(t.ambiguity.toFixed(3))]:null};
      const out1={
        atBound:seq(83,55,1),        // dA 35, dB 28
        pastBound:seq(82,55,1),      // dA 35, dB 27
        atSwitch:seq(92,60,1),       // dA 40, dB 32
        heldOutOfReach:seq(67,46,.5),// dA 26, dB 21
      };
      const dup=(()=>{const A1=box('a',0,20),A2=box('a',40,20);
        const t=step(resolver({}),[A1,A2],'pinching',30,100);return t?t.objectId:null})();
      const clamps=[resolver({targetAmbiguityMax:.2}).options().targetAmbiguityMax,
        resolver({targetAmbiguityMax:3}).options().targetAmbiguityMax];
      const r=resolver({targetAmbiguityMax:.6,targetSwitchPx:3});r.configure({targetZonePx:10});
      out({...out1,dup,clamps,kept:[r.options().targetAmbiguityMax,r.options().targetSwitchPx,r.options().targetZonePx]});
    """)
    assert result["atBound"] == ["a", 1]
    assert result["pastBound"] == ["b", pytest.approx(0.771, abs=1e-3)]
    assert result["atSwitch"] == ["b", 0.8]
    assert result["heldOutOfReach"] is None
    assert result["dup"] == "a", "la même cible collectée deux fois n'est pas sa propre voisine"
    assert result["clamps"] == [0.5, 1]
    assert result["kept"] == [0.6, 3, 10]


def test_the_selection_hysteresis_holds_between_neighbours_and_flickers_when_cut(tmp_path):
    """Un jeton qui oscille dans la bande ambiguë de deux voisines : avec la
    tenue, l'aperçu reste sur la première prise ; tenue et borne coupées
    (`targetSwitchPx: 0`, `targetAmbiguityMax: 1`), il bascule à chaque
    image — le clignotement que la tenue existe pour empêcher. Les bascules
    sont comptées par la décision elle-même."""

    result = run_node(tmp_path, PURE + """
      const A=starAt('a',100,100,20),Bx=starAt('b',150,100,20);
      const path=[['hover',121,100],['hover',126,100],['hover',123,100],['hover',126,100],['hover',123,100],['hover',126,100]];
      const count=r=>{let n=0;return {ids:path.map(([s,x,y])=>{const t=step(r,[A,Bx],s,x,y);
        if(r.decisions()[0].switched)n+=1;return t?t.objectId:null}),get switches(){return n}}};
      const steady=count(resolver({}));
      const steadyIds=steady.ids,steadySwitches=steady.switches;
      const flat=count(resolver({targetAmbiguityMax:1,targetSwitchPx:0}));
      out({steady:[steadyIds,steadySwitches],flat:[flat.ids,flat.switches]});
    """)
    assert result["steady"] == [["a"] * 6, 0]
    assert result["flat"] == [["a", "b", "a", "b", "a", "b"], 5]


def test_oversized_containers_never_preview_and_never_shadow_their_controls(tmp_path):
    """**Reprise QA, MINEUR 7.** Un grand élément focalisable (`tabindex`,
    1440 × 807, comme le fil de temps) : au survol d'une main qui vise, **pas**
    de cadre pâle autour ; un bouton qu'il contient, à 10 px du jeton, reçoit
    l'assistance au lieu d'être masqué par « l'intérieur gagne » ; sous
    pincement, loin de tout bouton, le conteneur reste une cible de repli.
    La règle de taille : ni bouton, ni lien, ni onglet, ni objet de scène, et
    au moins 48 000 px²."""

    result = run_page(tmp_path, BROWSER + """
      const big=node({sel:['[tabindex]:not([tabindex="-1"])'],rect:{left:0,top:60,width:1440,height:807},label:'Fil'});
      const b=button({left:600,top:300,width:80,height:30},'Lire');
      global.page=[big,b];
      const T=require(TARGET_PATH);
      const aim=(x,y)=>Object.assign(token(1,x,y),{pointing:true});
      const shot=(x,y,state)=>{frame([aim(x,y)],[contact(1,state)]);const el=previews()[0];
        const t=interaction.targets()[0];
        return {drawn:previews().length,host:el?el.attrs['data-hover']:null,
          target:t?(t.container?'container':t.kind):null}};
      const survey=T.survey().map(c=>[c.kind,c.container]);
      const far=shot(200,700,'open');
      const nearButton=shot(640,340,'open');
      const nearButtonPinch=shot(640,340,'pinching');
      interaction.clear();
      const fallback=shot(200,700,'pinching');
      interaction.clear();
      out({survey,far,nearButton,nearButtonPinch,fallback,
        rule:[T.CONTAINER_MIN_AREA_PX,T.isContainer('control',{w:300,h:160}),T.isContainer('control',{w:299,h:160}),
          T.isContainer('button',{w:2000,h:900}),T.isContainer('scene_object',{w:900,h:600})]});
    """)
    assert result["survey"] == [["control", True], ["button", False]]
    assert result["far"]["drawn"] == 0, "aucun cadre pâle autour d'un conteneur"
    assert result["nearButton"]["drawn"] == 1 and result["nearButton"]["host"] == "1"
    assert result["nearButtonPinch"]["target"] == "button"
    assert result["fallback"]["target"] == "container"
    assert result["rule"] == [48000, True, False, False, False]


# ------------------------------------------------------- ce qui se présélectionne


def test_stars_and_buttons_preview_only_under_pointing_intent_and_stars_get_no_zones(tmp_path):
    """Une étoile `point` se présélectionne **par son corps** — même visée au
    coin, aucune barre de zone — et seulement sous intention de pointer
    (`pointing: true`). Un bouton aussi, sans nom (il porte le sien). Une main
    qui ne vise pas (`pointing: false`) ne montre rien ; un jeton sans
    `pointing` (console, doubles) garde la règle d'avant : un bouton reste
    sombre. Une fenêtre, elle, garde son survol de zones."""

    result = run_page(tmp_path, BROWSER + """
      const s=star('obj-s',{left:200,top:200,width:26,height:26},'point','Étoile S');
      const sig=star('obj-g',{left:400,top:200,width:26,height:26},'signal','Signal G');
      const b=button({left:600,top:200,width:80,height:30},'Activer');
      global.page=[s,sig,b];
      const shot=(x,y,pointing)=>{const t=token(1,x,y);if(pointing!==undefined)t.pointing=pointing;
        frame([t],[contact(1,'open')]);const el=previews()[0];
        return el?[el.attrs['data-region'],el.children[0].style.display,el.attrs['data-hover'],
          el.attrs['data-representation'],el.children[1].textContent,el.children[1].style.display]:null};
      out({
        starCorner:shot(201,201,true),
        signal:shot(413,213,true),
        button:shot(640,215,true),
        notPointing:[shot(213,213,false),shot(640,215,false)],
        legacy:[shot(213,213),shot(640,215)],
        published:interaction.targets().length,
      });
      interaction.clear();
    """)
    assert result["starCorner"] == ["body", "none", "1", "point", "Étoile S", "block"]
    assert result["signal"] == ["body", "none", "1", "signal", "Signal G", "block"]
    # Le bouton : présélectionné, discret, sans étiquette.
    assert result["button"] == ["body", "none", "1", "", "", "none"]
    assert result["notPointing"] == [None, None]
    assert result["legacy"] == [None, None]
    assert result["published"] == 0


def test_the_star_ring_sits_around_the_star_and_names_it_below(tmp_path):
    """La forme de l'aperçu d'une étoile : un anneau posé **autour** (inset
    négatif, sans fond) et le nom **dessous** — un cadre posé sur une étoile de
    8 px cacherait ce qu'il désigne. Les règles sont dans la feuille de
    l'aperçu, portées par `data-representation`."""

    sheet = TARGET.read_text(encoding="utf-8")
    for representation in ("point", "signal"):
        assert f'.jh-target[data-nested="1"][data-representation="{representation}"]' in sheet
    assert "left:-5px;top:-5px;right:-5px;bottom:-5px;border-radius:50%;background:none" in sheet


# ----------------------------------------------------------- réglage par essai


TRIAL = """
/* Le chemin unique (décision 48) sur un **vrai** résolveur : l'interaction de
   la page est réduite à ce que la composition lui pousse et à ce qu'elle
   relit. Le contrôleur n'a rien à tenir ici — ses clés ne sont pas essayées —
   mais il doit se relire (`readback`). */
const r=B.createTargetResolver({pickRegion:C.pickRegion});
let assistance=.5;
const interaction={configureTargets(n){r.configure(n)},targetOptions:()=>({assistance,...r.options()}),
  setTool(){},showTargets(){},setAssistance(v){assistance=v}};
const controller={configure(){},options:()=>({readback:{}})};
const settings=C.normalizeSettings({});
const path=B.createEffectivePath({contracts:C,controller:()=>controller,interaction,
  overlay:{showDiagnostics(){}},settings:()=>settings,profile:()=>C.normalizeProfile({}),
  viewportWidth:()=>1280,now:()=>1000});
path.apply(settings);
const T=path.trials;
const starAt=(id,cx,cy,size)=>({objectId:id,kind:'scene_object',representation:'point',
  zoned:false,actionable:true,ref:0,boundsPx:{x:cx-size/2,y:cy-size/2,w:size,h:size}});
const takes=(x)=>{r.reset();const t=r.update({now:0,candidates:[starAt('a',100,100,20)],
  hands:[{handTrackId:1,channel:'primary',state:'pinching',x,y:100,assistance}]})[0];return t?t.objectId:null};
"""


def test_an_assistance_trial_changes_the_reach_and_rolls_back_exactly(tmp_path):
    """Un essai d'assistance passe par le chemin unique, se **relit** chez le
    résolveur (`targetOptions()`) et change ce que la main atteint : à 40 px
    d'une étoile, rien à 0,5 (24 px), l'étoile à 1 (48 px). Le retour arrière
    rend exactement l'état d'avant. Les deux clés de présélection se règlent
    et se relisent de la même façon, et leurs bornes se refusent nommément."""

    result = run_node(tmp_path, TRIAL + """
      const before={reach:r.reach(assistance),takes:takes(150)};
      const applied=T.apply({assistance:1});
      const during={reach:r.reach(assistance),takes:takes(150),applied:applied.applied};
      const back=T.rollback();
      const after={reach:r.reach(assistance),takes:takes(150),ok:back.ok,applied:back.applied};
      const tuned=T.apply({targetSwitchPx:2,targetAmbiguityMax:.6});
      const tunedRead={...r.options()};
      const undone=T.rollback();
      out({before,during,after,tuned:[tuned.ok,tuned.applied],tunedRead:[tunedRead.targetSwitchPx,tunedRead.targetAmbiguityMax],
        undone:[undone.ok,undone.applied],
        refusals:[T.apply({targetSwitchPx:13}).code,T.apply({targetAmbiguityMax:.45}).code],
        keys:['targetSwitchPx','targetAmbiguityMax'].map(k=>[k,C.TRIAL_KEYS[k].family,C.TRIAL_KEYS[k].min,
          C.TRIAL_KEYS[k].max,C.TRIAL_KEYS[k].default,C.TRIAL_KEYS[k].store,C.TRIAL_ADVERTISED_KEYS.includes(k)]),
        defaults:[B.DEFAULTS.targetSwitchPx,B.DEFAULTS.targetAmbiguityMax],
        tuning:[C.PROFILE_TUNING_BOUNDS.targetSwitchPx,C.PROFILE_TUNING_BOUNDS.targetAmbiguityMax]});
    """)
    assert result["before"] == {"reach": 24, "takes": None}
    assert result["during"]["reach"] == 48 and result["during"]["takes"] == "a"
    assert result["during"]["applied"] == {"assistance": 1}
    assert result["after"] == {"reach": 24, "takes": None, "ok": True, "applied": {"assistance": 0.5}}
    assert result["tuned"] == [True, {"targetSwitchPx": 2, "targetAmbiguityMax": 0.6}]
    assert result["tunedRead"] == [2, 0.6]
    assert result["undone"] == [True, {"targetSwitchPx": 8, "targetAmbiguityMax": 0.8}]
    assert result["refusals"] == ["barehands_trial_value_out_of_bounds"] * 2
    assert result["keys"] == [
        # Plafond 12 px (reprise QA) : au-delà, la tenue couvrirait presque tout l'écart
        # entre deux étoiles de la scène.
        ["targetSwitchPx", "target", 0, 12, 8, {"kind": "tuning", "key": "targetSwitchPx"}, True],
        ["targetAmbiguityMax", "target", 0.5, 1, 0.8, {"kind": "tuning", "key": "targetAmbiguityMax"}, True],
    ]
    assert result["defaults"] == [8, 0.8]
    assert result["tuning"] == [{"min": 0, "max": 12, "default": 8, "integer": False},
                                {"min": 0.5, "max": 1, "default": 0.8, "integer": False}]


def test_the_python_profile_mirror_stores_the_two_new_keys():
    """Le miroir Python du bloc `tuning` range les deux clés, aux mêmes bornes
    (le test de parité général compare les tables entières)."""

    from jarvis.runtime import barehands_profile as profile

    assert profile.TUNING_BOUNDS["target_switch_px"] == (0, 12, 8, False)
    assert profile.TUNING_BOUNDS["target_ambiguity_max"] == (0.5, 1, 0.8, False)


# ------------------------------------------------------------------ télémétrie


def test_the_preselection_telemetry_is_scalar_only(tmp_path):
    """Les décisions deviennent des événements de séance **aux transitions**
    (aperçu acquis, bascule, sélection figée), et chacun traverse la liste
    blanche de l'enregistreur tel quel : canal, fente, région, distance,
    ambiguïté (`score`), type de cible, cible attendue. Jamais d'`objectId`,
    de clé de page ni de libellé."""

    result = run_node(tmp_path, PURE + """
      const A=starAt('a',100,100,20),Bx=starAt('b',150,100,20);
      const r=resolver({});
      const tel=B.createTargetTelemetry({expectedOf:key=>key==='o:b'?true:key==='o:a'?false:null});
      const events=[];
      const go=(state,x,t)=>{step(r,[A,Bx],state,x,100);
        for(const e of tel.update(r.decisions().map(d=>({...d,slot:0})),t))events.push(e)};
      go('hover',118,1);go('hover',119,2);go('hover',150,3);go('pinching',150,4);go('pressed',150,5);go('pressed',150,6);
      const samples=events.map((e,i)=>R.validateSessionSample(R.readSessionSample({ref:`se-${i+1}`,t:e.t,event:e})));
      out({kinds:events.map(e=>[e.kind,e.expected,e.targetKind,Number(e.score.toFixed(3)),e.distancePx]),
        wire:samples.map(s=>s.event),
        leaked:JSON.stringify(samples).match(/obj-|o:a|o:b|objectId|handTrackId|"key"/g)});
    """)
    assert result["kinds"] == [
        ["target_preview", False, "scene_object", 0.364, 8],
        ["target_changed", True, "scene_object", 0, 0],
        ["capture_start", True, "scene_object", 0, 0],
    ]
    assert result["leaked"] is None
    assert set(result["wire"][0]) == {"kind", "channel", "slot", "falseKind", "region", "distancePx",
                                      "latencyMs", "score", "ref", "targetKind", "expected"}
    assert result["wire"][2]["expected"] is True and result["wire"][2]["slot"] == 0


# ----------------------------------------------------------- l'exercice


def test_the_selection_observer_turns_decisions_into_facts(tmp_path):
    """Le banc lit les décisions du vrai résolveur : une descente sur l'étoile
    attendue, sur une voisine, dans le vide ; une bascule ; un refus pour
    ambiguïté. Un fait est un mot et des nombres."""

    result = run_node(tmp_path, PURE + """
      const A=starAt('a',100,100,20),Bx=starAt('b',150,100,20);
      const obs=B.createSelectionObserver();
      obs.arm({'o:a':false,'o:b':true});
      const r=resolver({});
      const go=(state,x,t)=>{step(r,[A,Bx],state,x,100);obs.update(r.decisions(),t)};
      go('hover',125,1);                 // milieu : refus pour ambiguïté
      go('hover',112,2);go('hover',150,3); // A, puis bascule vers B
      go('pressed',150,4);go('pressed',150,5);go('hover',150,6);
      go('pressed',100,7);go('hover',100,8);
      go('pressed',300,9);
      out({facts:obs.drain().map(f=>[f.type,f.outcome===undefined?f.toExpected:f.outcome,f.t]),
        expected:[obs.expected('o:b'),obs.expected('o:a'),obs.expected('o:x')],after:obs.drain().length});
    """)
    assert result["facts"] == [
        ["ambiguous", None, 1],
        ["switch", True, 3],
        ["press", "expected", 4],
        ["press", "other", 7],
        ["switch", False, 7],
        ["press", "none", 9],
    ]
    assert result["expected"] == [True, False, None]
    assert result["after"] == 0


def test_the_selection_exercise_counts_errors_into_a_contract_measurement(tmp_path):
    """Le compte pur : la progression au relâchement, la manche passée après
    trois ratés, et une ligne que `createMeasurementSet` accepte."""

    result = run_node(tmp_path, """
      const X=K.createSelectionExercise({attemptsMax:3});
      const press=(outcome,t,ambiguity)=>{X.fact({type:'press',t,outcome,ambiguity});return X.release()};
      X.open(0);
      const r1=press('expected',400,.1);
      X.open(1000);
      const r2=[press('other',1200,.9),press('expected',1900,.4)];
      X.open(2000);
      X.fact({type:'switch',t:2100});X.fact({type:'ambiguous',t:2200});
      const r3=[press('none',2300,null),press('none',2400,null),press('other',2500,.7)];
      X.open(3000);
      const r4=press('expected',3600,.2);
      const row=X.row();
      out({r1,r2,r3,r4,done:X.done(),summary:X.summary(),row,
        set:C.createMeasurementSet({'ex-1':row})['ex-1'],
        rounds:K.SELECTION_ROUNDS.map(r=>[r.id,r.stars.length,r.stars.filter(s=>s.expected).length,
          r.stars.some(s=>s.moving)]),
        stars:K.selectionStars(1,{width:1000,height:1000})});
    """)
    assert result["r1"] == {"outcome": "expected", "next": True, "skipped": False}
    assert result["r2"] == [{"outcome": "other", "next": False, "skipped": False},
                            {"outcome": "expected", "next": True, "skipped": False}]
    assert result["r3"][2] == {"outcome": "other", "next": True, "skipped": True}
    assert result["done"] is True
    assert result["summary"] == {"hits": 3, "wrong": 2, "missed": 2, "switches": 1, "ambiguous": 1,
                                 "skipped": 1, "rounds": 4}
    assert result["row"] == {"wrong_target_count": 2, "missed_click_count": 2,
                             "target_ambiguity": pytest.approx((0.1 + 0.9 + 0.4 + 0.7 + 0.2) / 5),
                             "reacquisition_count": 1, "acquisition_ms": 600}
    assert result["set"] == result["row"]
    # Quatre manches : petite, voisines, groupe, mobile — une seule attendue chacune.
    assert result["rounds"] == [["small", 1, 1, False], ["nearby", 2, 1, False],
                                ["cluster", 4, 1, False], ["moving", 2, 1, True]]
    # En pixels de la fenêtre, autour d'un emplacement de visée.
    assert result["stars"] == [{"x": 764, "y": 360, "size": 20, "expected": False, "moving": False},
                               {"x": 796, "y": 360, "size": 20, "expected": True, "moving": False}]


AIM = DOM + DRIVER + """
/* Le banc de sélection, double : il rend ses manches posées et un journal de
   faits qu'on remplit à la main — ce que le vrai résolveur aurait décidé est
   prouvé plus haut, sur le vrai résolveur. */
const selectionOf=()=>{const state={opens:[],closes:0,facts:[],live:false};
  return {state,
    open(mount,stars){state.opens.push(stars.map(s=>[s.size,s.expected,s.moving]));state.live=!!mount;return {openedAt:clock,count:stars.length}},
    drain(){const f=state.facts;state.facts=[];return f},
    close(){const had=state.live;state.live=false;if(had)state.closes+=1;return had}}};
const toAim=cal=>{cal.start();for(let i=0;i<4;i+=1)skipStep(cal);return cal.stepId()};
"""


def test_the_aim_stage_plays_the_selection_rounds_and_records_the_row(tmp_path):
    """L'étape de visée, avec un banc de sélection : les étoiles se posent à la
    fin de la lecture (pas de points), une manche avance au relâchement de la
    bonne prise, une mauvaise étoile reste sur la manche et le dit, trois
    ratés passent la manche ; à la fin, la ligne `ex-1` est dans la séance,
    les événements de cible observés portent l'exercice, et le rapport dit
    les erreurs en clair. La course du clic n'est mesurée que sur une bonne
    prise."""

    result = run_node(tmp_path, AIM + """
      const sb=selectionOf();
      const cal=calOf({selection:sb});
      const at=toAim(cal);
      const reading={opens:sb.state.opens.length,aim:cal.aim()};
      readOn(cal);
      const armed={opens:sb.state.opens.slice(),aim:cal.aim(),ghosts:find(flowRoot(),'jf-ghost').length};
      const fact=(outcome,ambiguity)=>sb.state.facts.push({type:'press',t:clock,outcome,distancePx:3,ambiguity});
      const pinch=()=>{feed(cal,3,{primaryRatio:.15});feed(cal,2,{primaryRatio:.6,palmX:623})};
      feed(cal,3,{primaryRatio:.15});            // arme l'étape
      fact('expected',.1);feed(cal,2,{primaryRatio:.6,palmX:623});
      const afterFirst=cal.aim();
      fact('other',.8);pinch();
      const wrongNote=find(flowRoot(),C.DOM.flowNoteClass).map(n=>n.textContent).join(' ');
      const afterWrong=cal.aim();
      fact('expected',.3);pinch();
      sb.state.facts.push({type:'switch',t:clock,toExpected:true});
      fact('none',null);pinch();fact('none',null);pinch();fact('other',.9);pinch();
      const afterSkip=cal.aim();
      cal.observe({kind:'capture_start',t:clock,channel:'primary',slot:0,region:'body',distancePx:2,
        score:.2,targetKind:'scene_object',expected:true,objectId:'barehands:select-1-0',handTrackId:1});
      fact('expected',.2);pinch();
      const s=cal.session();
      out({at,reading,armed,afterFirst,wrongNote,afterWrong,afterSkip,phase:cal.phase(),
        row:s.measurements['ex-1'],closes:sb.state.closes,
        observed:s.samples.filter(x=>x.event&&x.event.kind==='capture_start').map(x=>[x.stage,x.exerciseRef,
          x.event.expected,x.event.targetKind,x.event.score,JSON.stringify(x).includes('select-1')])});
    """)
    assert result["at"] == "aim"
    assert result["reading"] == {"opens": 0, "aim": None}, "rien n'est posé pendant la lecture"
    assert result["armed"]["opens"] == [[[12, True, False]]]
    assert result["armed"]["ghosts"] == 0, "pas de points de visée quand les étoiles sont là"
    assert result["armed"]["aim"]["mode"] == "selection" and result["armed"]["aim"]["at"] == 0
    assert result["afterFirst"]["at"] == 1 and result["afterFirst"]["hits"] == 1
    assert "voisine" in result["wrongNote"]
    assert result["afterWrong"]["at"] == 1
    assert result["afterSkip"]["at"] == 3, "trois ratés passent la manche"
    assert result["phase"] == "result"
    row = dict(result["row"])
    # Médiane des temps d'acquisition des trois bonnes prises, à l'horloge du
    # double (de l'ouverture de la manche au fait de descente).
    assert row.pop("acquisition_ms") > 0
    assert row == {"wrong_target_count": 2, "missed_click_count": 2,
                   "target_ambiguity": pytest.approx((0.1 + 0.8 + 0.3 + 0.9 + 0.2) / 5),
                   "reacquisition_count": 1}
    assert result["closes"] >= 1
    assert result["observed"] == [["aim", "ex-1", True, "scene_object", 0.2, False]]


def test_without_a_selection_bench_the_aim_stage_keeps_its_points(tmp_path):
    """Sans banc (et c'est le cas de tous les tests historiques), l'étape de
    visée joue ses trois points d'avant : l'exercice de sélection est une
    extension, pas un remplacement silencieux."""

    result = run_node(tmp_path, AIM + """
      const cal=calOf();
      toAim(cal);readOn(cal);
      out({aim:cal.aim(),ghosts:find(flowRoot(),'jf-ghost').length>0});
    """)
    assert result["aim"] == {"points": 3, "hits": 0, "at": 0}
    assert result["ghosts"] is True


def test_the_page_bench_mounts_real_star_nodes_without_zones(tmp_path):
    """Le banc de la page pose de vrais nœuds de scène `point` (donc sans
    zones), l'attendue avec son repère en pointillé, la mobile avec sa
    classe, **sans nom** ; il allume l'aperçu s'il était éteint et le rend
    tel quel ; il se démonte entièrement."""

    result = run_page(tmp_path, BROWSER + """
      const sel=api.adapters.selection;
      const mount=node();
      const logged=[];console.info=line=>logged.push(String(line).split(' ')[1]);
      api.targetPreview(false);
      const opened=sel.open(mount,[{x:100,y:100,size:12,expected:true,moving:false},
        {x:140,y:100,size:18,expected:false,moving:true}]);
      const layer=mount.children[0];
      const stars=layer.children.map(el=>[el.className,el.attrs['data-representation'],el.attrs['aria-label'],
        el.style.width,el.style.transform,el.children.map(c=>c.className)]);
      const id=layer.children[0].attrs['data-object-id'];
      const expectedKnown=[sel.expected('o:'+id),sel.expected('o:nope')];
      const forced=interaction.targetsShown();
      const closed=sel.close();
      const restored=interaction.targetsShown();
      api.targetPreview(true);
      out({logged,forced,restored,opened:opened&&opened.count,layer:layer.className,hidden:layer.attrs['aria-hidden'],stars,expectedKnown,closed,
        left:mount.children.length,again:sel.close(),zoned:C.hasManipulationZones('point')});
    """)
    assert result["opened"] == 2
    assert result["layer"] == "scene jf-practice jf-select"
    # Aucun libellé : l'anneau seul dit laquelle serait prise, rien ne donne la
    # réponse (reprise QA) ; la couche gestuelle est cachée des lecteurs d'écran.
    assert result["hidden"] == "true"
    assert result["forced"] is True and result["restored"] is False
    assert result["logged"] == ["calibration.selection_preview_forced", "calibration.selection_preview_restored"]
    assert result["stars"][0] == ["sc-node sc-point sc-tone-agent", "point", None, "12px",
                                  "translate(94px,94px)", ["sc-mark", "jf-select-cue"]]
    assert result["stars"][1][0] == "sc-node sc-point sc-tone-agent jf-select-moving"
    assert result["stars"][1][2] is None
    assert result["expectedKnown"] == [True, None]
    assert result["closed"] is True and result["left"] == 0 and result["again"] is False
    assert result["zoned"] is False


def test_dom_controls_are_held_and_reported_by_their_page_key(tmp_path):
    """Un contrôle du DOM n'a pas d'`objectId` : la tenue et la télémétrie le
    suivent par sa **clé de page** (`e:<n>`), et un objet de scène par
    `o:<objectId>` — la même forme que `targetIdentity` et que les clés du banc
    de sélection."""

    result = run_node(tmp_path, PURE + """
      const ctl=(key,x)=>({objectId:null,key,kind:'button',representation:null,zoned:false,actionable:true,
        boundsPx:{x,y:90,w:20,h:20}});
      const P=ctl('e:1',90),Q=ctl('e:2',140);
      const r=resolver({});
      const kinds=[];const tel=B.createTargetTelemetry({});
      const go=(x,t)=>{const got=step(r,[P,Q],'hover',x,100);for(const e of tel.update(r.decisions(),t))kinds.push(e.kind);
        return got?got.key:null};
      const held=[go(118,1),go(126,2),go(128,3)];
      out({held,kinds,ids:[B.targetIdentity({objectId:'obj-1'}),B.targetIdentity({objectId:null,key:'e:7'}),
        B.targetIdentity({objectId:null})]});
    """)
    assert result["held"] == ["e:1", "e:1", "e:2"]
    assert result["kinds"] == ["target_preview", "target_changed"]
    assert result["ids"] == ["o:obj-1", "e:7", None]


def test_the_page_survey_keys_match_the_engine_identity(tmp_path):
    """La collecte pose `o:<objectId>` sur une étoile (la clé que le banc arme
    et que `targetIdentity` rend) et une clé stable par élément sur un
    contrôle : deux balayages, la même clé ; deux boutons, deux clés."""

    result = run_page(tmp_path, BROWSER + """
      const T=require(TARGET_PATH);
      const s=star('obj-1',{left:10,top:10,width:26,height:26},'point','S');
      const b1=button({left:100,top:10,width:40,height:20},'Un'),b2=button({left:200,top:10,width:40,height:20},'Deux');
      global.page=[s,b1,b2];
      const first=T.survey().map(c=>c.key),second=T.survey().map(c=>c.key);
      out({first,same:JSON.stringify(first)===JSON.stringify(second),identity:B.targetIdentity({objectId:'obj-1'})});
    """)
    assert result["first"][0] == "o:obj-1" == result["identity"]
    assert result["first"][1].startswith("e:") and result["first"][1] != result["first"][2]
    assert result["same"] is True


def test_telemetry_events_carry_exactly_the_scalar_fields(tmp_path):
    """À la source, un événement de présélection porte **exactement** ces
    champs — ni `handTrackId`, ni clé de page, ni `objectId` : la liste
    blanche de l'enregistreur n'est pas la seule barrière."""

    result = run_node(tmp_path, PURE + """
      const r=resolver({});const tel=B.createTargetTelemetry({expectedOf:()=>true});
      step(r,[starAt('a',100,100,20)],'hover',100,100);
      const e=tel.update(r.decisions().map(d=>({...d,slot:1})),5)[0];
      out(Object.keys(e).sort());
    """)
    assert result == sorted(["kind", "t", "channel", "slot", "region", "distancePx", "score",
                             "targetKind", "expected"])


def test_the_selection_observer_reads_the_primary_channel_only(tmp_path):
    """Un clic droit (canal secondaire) sur une étoile n'est pas une sélection
    de l'exercice : aucun fait."""

    result = run_node(tmp_path, """
      const obs=B.createSelectionObserver();obs.arm({'o:a':true});
      const rec=(channel,state,switched)=>({handTrackId:1,channel,state,key:'o:a',reason:'inside',
        distancePx:0,ambiguity:0,switched:!!switched});
      obs.update([rec('secondary','hover')],1);obs.update([rec('secondary','pressed',true)],2);
      const secondary=obs.drain().length;
      obs.update([rec('primary','hover')],3);obs.update([rec('primary','pressed')],4);
      out({secondary,primary:obs.drain().map(f=>[f.type,f.outcome])});
    """)
    assert result == {"secondary": 0, "primary": [["press", "expected"]]}


def test_the_star_name_never_covers_a_neighbour(tmp_path):
    """**Reprise QA, MINEUR 4.** Le nom d'une étoile se pose dessous ; s'il y
    couvrirait une autre candidate, dessus ; si les deux côtés sont pris, pas
    de nom — l'anneau seul. Et le survol d'une étoile se voit : trait plein à
    90 % et liseré sombre, sans l'opacité réduite du survol ordinaire."""

    result = run_page(tmp_path, BROWSER + """
      const T=require(TARGET_PATH);
      const b={x:100,y:100,w:20,h:20};
      const other=(x,y)=>({boundsPx:{x,y,w:20,h:20}});
      const sides={alone:T.nameSide(b,'Étoile',[]),
        below:T.nameSide(b,'Étoile',[other(100,135)]),
        both:T.nameSide(b,'Étoile',[other(100,135),other(100,65)]),
        self:T.nameSide(b,'Étoile',[{boundsPx:{...b}}]),
        empty:T.nameSide(b,'',[])};
      /* La page : l'étoile fixe sous la visée, une voisine juste dessous. */
      const a=star('obj-a',{left:300,top:300,width:20,height:20},'point','Étoile A');
      const n=star('obj-n',{left:300,top:334,width:20,height:20},'point','Étoile N');
      const u=star('obj-u',{left:300,top:266,width:20,height:20},'point','Étoile U');
      const look=()=>{const el=previews()[0];return el?[el.attrs['data-name-side'],el.children[1].textContent]:null};
      global.page=[a,n];
      frame([Object.assign(token(1,310,310),{pointing:true})],[contact(1,'open')]);
      const oneNeighbour=look();
      global.page=[a,n,u];interaction.clear();
      frame([Object.assign(token(1,310,310),{pointing:true})],[contact(1,'open')]);
      const boxed=look();
      interaction.clear();
      out({sides,oneNeighbour,boxed});
    """)
    assert result["sides"] == {"alone": "below", "below": "above", "both": None, "self": "below", "empty": None}
    assert result["oneNeighbour"] == ["above", "Étoile A"]
    assert result["boxed"] == ["below", ""], "pris des deux côtés : l'anneau seul"
    sheet = TARGET.read_text(encoding="utf-8")
    assert '.jh-target[data-hover="1"][data-representation="point"]' in sheet
    assert "border:2px solid color-mix(in srgb,currentColor 90%,transparent)" in sheet
    assert "box-shadow:0 0 0 1px rgba(0,0,0,.6)" in sheet


def test_the_exercise_keeps_its_row_on_timeout_counts_clicks_on_good_picks_and_respects_reduced_motion(tmp_path):
    """L'échéance rend quand même la ligne de mesures (des erreurs sont une
    mesure) ; la course du clic n'est comptée que sur une **bonne** prise ;
    sous « mouvement réduit », l'étoile mobile s'arrête (règle **après**
    l'animation, sinon l'animation gagne)."""

    result = run_node(tmp_path, AIM + """
      const sb=selectionOf();
      const cal=calOf({selection:sb});
      toAim(cal);readOn(cal);
      const fact=(outcome)=>sb.state.facts.push({type:'press',t:clock,outcome,distancePx:3,ambiguity:.5});
      feed(cal,3,{primaryRatio:.15});
      fact('other');feed(cal,2,{primaryRatio:.6,palmX:700});
      const afterWrong=cal.aim().clicks;
      fact('expected');feed(cal,3,{primaryRatio:.15});feed(cal,2,{primaryRatio:.6,palmX:640});
      const afterGood=cal.aim().clicks;
      clock+=6000;beat();
      out({afterWrong,afterGood,phase:cal.phase(),row:cal.session().measurements['ex-1']||null});
    """)
    assert result["afterWrong"] == 0 and result["afterGood"] == 1
    assert result["phase"] == "result"
    assert result["row"]["wrong_target_count"] == 1 and result["row"]["missed_click_count"] == 0
    sheet = CALIBRATION.read_text(encoding="utf-8")
    moving = sheet.index("${R} .jf-select .jf-select-moving{animation:jfSelectDrift")
    reduced = sheet.index("@media (prefers-reduced-motion:reduce){${R} .jf-select .jf-select-moving{animation:none}}")
    assert reduced > moving


def test_the_contract_document_records_decision_49():
    doc = DOC.read_text(encoding="utf-8")
    section = doc[doc.index("## 17. Calibration adaptative"):]
    assert "Décision 49" in section
    for name in ("targetSwitchPx", "targetAmbiguityMax", "decideTarget", "createSelectionObserver",
                 "createTargetTelemetry", "createSelectionExercise"):
        assert f"`{name}`" in section, name
