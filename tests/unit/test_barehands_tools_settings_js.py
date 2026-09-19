"""Outils et réglages Bare Hands (Slice 07, décisions 24 et 25), par node.

Ce que ce fichier épingle :

- **l'outil dit ce que la main veut dire** et rien d'autre : le pointeur reste
  contextuel, `pan` et `select` imposent un sens, et une cible qui ne peut pas
  l'honorer est **refusée avec un motif à l'écran** — jamais une main qui se
  pose et ne fait rien ;
- un outil déclaré **sans moteur** refuse partout, y compris sur une zone : le
  moteur est injectable et ne suppose pas que son appelant a filtré ;
- l'outil ne prend ni un bord, ni un coin, ni le corps d'une étoile déplaçable
  seulement — ce sont des **poignées de cadre**, pas du contenu ;
- les réglages atteignent réellement le moteur : `sleepTimeoutMs` ramène en
  veille au temps demandé, `sensitivity` déplace le seuil de glissement, et la
  paire dangereuse `sleepTimeoutMs <= wakeHoldMs` se refuse **là où elle
  arrive** (construction *et* reconfiguration) ;
- l'écran : la palette, les curseurs et les cases sont dessinés à partir des
  tables du contrat, écrivent ce qu'on touche, et **rendent l'ancienne valeur
  au moteur** quand l'enregistrement échoue ;
- la charge utile que la page construit est acceptée par la **vraie** route
  `POST /api/barehands`, et la version de schéma est la même des deux côtés.

Les contrats, la géométrie et le moteur ne sont pas simulés : ce sont les vrais
modules. Seuls la scène, le DOM et le réseau sont des doubles — ce que node
n'a pas.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.runtime import barehands_test_mode as barehands
from jarvis.runtime.control_center import ControlCenter

# Le monde injecte du cycle de vie (horloge, video, camera, boucle d'images)
# est **reutilise**, pas recopie : une seconde version deriverait de celle que
# les tests de la Slice 02 tiennent, et les deux decriraient deux controleurs
# differents sous un seul nom.
from test_barehands_lifecycle_js import WORLD  # noqa: E402
from test_barehands_gestures_js import HAND as GESTURE_GEOMETRY  # noqa: E402

# Les elements de page et leur geometrie : le meme double que la Slice 05, pas
# une copie. Un reglage qui agit sur ce que la main **atteint** ne se prouve
# que sur un arbre qui a des rectangles.
from test_barehands_target_js import ELEMENTS  # noqa: E402

#: La geometrie de main de la Slice 04, enfermee dans une fermeture pour n'en
#: sortir que `PINCHING` : elle definit un `hand()` qui n'est pas celui du
#: monde injecte, et deux `hand` dans une meme source se marcheraient dessus
#: en silence.
PINCH_GEOMETRY = "const PINCHING=(()=>{" + GESTURE_GEOMETRY + "\nreturn PINCHING})();\n"

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
SCRIPT = RUNTIME / "control_center_barehands.js"
CONTRACTS = RUNTIME / "control_center_barehands_contracts.js"
TARGET = RUNTIME / "control_center_barehands_target.js"
CALIBRATION = RUNTIME / "control_center_barehands_calibration.js"
SCENE_INTERACT = RUNTIME / "control_center_scene_interact.js"


def run_node(tmp_path: Path, source: str, name: str = "tools") -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"barehands-{name}.cjs"
    script.write_text(
        f"const SCRIPT_PATH={json.dumps(str(SCRIPT))};\n"
        f"const CALIBRATION_PATH={json.dumps(str(CALIBRATION))};\n"
        f"const TARGET_PATH={json.dumps(str(TARGET))};\n"
        f"const SCENE_INTERACT_PATH={json.dumps(str(SCENE_INTERACT))};\n"
        f"const CONTRACTS_PATH={json.dumps(str(CONTRACTS))};\n"
        "const B=require(SCRIPT_PATH);\n"
        "const C=require(CONTRACTS_PATH);\n"
        "const G=require(SCENE_INTERACT_PATH);\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "const refused=fn=>{try{fn();return null}catch(e){return e.code||e.name||String(e)}};\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=40, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


#: Le moteur avec les **vrais** contrats et la **vraie** géométrie ; seuls le
#: monde et le DOM sont des doubles. Même forme qu'à la Slice 06, pour que les
#: deux fichiers décrivent le même moteur.
FIXTURE = """
const makeDom=(scrollable)=>{
  const log=[];
  return {log,api:{
    scrollable(target){return (scrollable||[]).includes(String(target&&target.kind))},
    emit(event){log.push({type:event.type,tool:event.tool,dx:event.dx,dy:event.dy})},
  }};
};
const makeWorld=objects=>({
  begin(id){const o=objects[id];return o?{objectId:id,box:Object.assign({},o.box),
    representation:o.representation}:null},
  preview(){},commit(){},cancel(){},viewport(){return {scale:6}},
});
const engineOf=o=>B.createInteractionEngine(Object.assign({contracts:C,geometry:G},o||{}));
const tok=(id,x,y)=>({id,x,y,palmX:x,palmY:y});
const tgt=(id,objectId,region,zone,extra)=>Object.assign({
  handTrackId:id,channel:'primary',locked:true,objectId,region,zone,
  kind:'scene_object',representation:'window',actionable:true,
  boundsPx:{x:0,y:0,w:600,h:400},distancePx:0},extra||{});
const ev=(id,phase,x,y)=>({handTrackId:id,channel:'primary',phase,
  x:x===undefined?null:x,y:y===undefined?null:y});
const held=(id,intent)=>({handTrackId:id,channel:'primary',state:'pressed',intent:intent||'drag'});

/* Une prise de corps, tirée sur trois images, avec l'outil demandé. Rend ce
   que le DOM a reçu et ce que le moteur a refusé : les deux, parce qu'un outil
   qui ne s'applique pas doit produire **un refus** et non un silence. */
const bodyRun=(tool,kind,scrollable,extra,contracts)=>{
  const dom=makeDom(scrollable?[kind]:[]);
  const e=engineOf({dom:dom.api,slotOf:()=>0,contracts:contracts||C});
  if(tool)e.setTool(tool);
  const target=Object.assign(tgt(1,null,'body',null),{kind,representation:null},extra||{});
  let refusals=[];
  const step=(k,x,events,contacts)=>{
    const s=e.update({now:16*k,tokens:[tok(1,x,300)],targets:[target],
      events:events||[],contacts:contacts||[]});
    if(s.refusals.length)refusals=refusals.concat(s.refusals.map(r=>r.reason));
    return s;
  };
  step(0,400,[ev(1,'down',400,300)],[held(1,'undecided')]);
  for(let k=1;k<=2;k+=1)step(k,400+40*k,[],[held(1,'drag')]);
  const last=e.update({now:64,tokens:[tok(1,480,300)],targets:[],
    events:[ev(1,'up',480,300)],contacts:[]});
  if(last.refusals.length)refusals=refusals.concat(last.refusals.map(r=>r.reason));
  return {dom:dom.log.map(d=>[d.type,d.tool]),refusals,
    semantics:last.interactions.map(i=>i.type)};
};
"""


# ------------------------------------------------------------------- outils


def test_the_pointer_tool_stays_contextual_and_decides_from_what_is_under_the_hand(tmp_path):
    """**Décision 25 et critère d'acceptation** : « l'interaction par défaut
    reste contextuelle ». Le pointeur n'impose rien — c'est la sémantique de la
    cible qui décide, exactement comme avant la Slice 07. Un outil par défaut
    qui forcerait le glissement rendrait tout le reste de la Slice invisible."""

    result = run_node(tmp_path, FIXTURE + """
      out({
        button:bodyRun(null,'button',false),
        field:bodyRun(null,'field',false),
        scroller:bodyRun(null,'card',true),
        // Explicitement choisi, le pointeur fait exactement la même chose que
        // l'outil par défaut : sans ça, « par défaut » et « pointeur » seraient
        // deux comportements pour un seul nom.
        chosen:bodyRun('pointer','button',false),
        defaultTool:engineOf({}).tool(),
      });
    """)
    assert [row[0] for row in result["button"]["dom"]] == ["drag_start", "drag_move", "drag_end"]
    assert [row[0] for row in result["field"]["dom"]] == ["select"]
    assert [row[0] for row in result["scroller"]["dom"]] == ["scroll"]
    assert result["chosen"]["dom"] == result["button"]["dom"]
    assert result["defaultTool"] == "pointer"
    assert all(not row["refusals"] for row in
               (result["button"], result["field"], result["scroller"], result["chosen"]))
    # L'outil actif voyage avec l'événement (contrat § 7) : un consommateur doit
    # pouvoir distinguer un défilement de contenu d'un défilement demandé.
    assert {row[1] for row in result["button"]["dom"]} == {"pointer"}


def test_a_tool_that_forces_a_meaning_refuses_a_target_that_cannot_honour_it(tmp_path):
    """Critère d'acceptation : « les combinaisons outil/cible non prises en
    charge sont sûres et compréhensibles ».

    Sûres : rien ne se produit sur la cible. Compréhensibles : le motif remonte
    dans `refusals`, donc sur la ligne que la surimpression affiche déjà. Une
    main qui se pose et ne fait rien, sans un mot, est indiscernable d'une
    panne — c'est exactement ce que ce test interdit."""

    result = run_node(tmp_path, FIXTURE + """
      out({
        // `pan` sur ce qui défile : le contenu suit la main.
        panScroller:bodyRun('pan','card',true),
        // `pan` sur un bouton qui ne défile pas : refusé, et dit.
        panButton:bodyRun('pan','button',false),
        // `select` sur un champ : désigné et sélectionné.
        selectField:bodyRun('select','field',false),
        // `select` sur une carte : rien à sélectionner, refusé, et dit.
        selectCard:bodyRun('select','card',false),
        // `select` force le sens **contre** la sémantique contextuelle : une
        // zone qui défile se sélectionne quand on l'a demandé.
        selectScroller:bodyRun('select','scene_object',true),
      });
    """)
    assert [row[0] for row in result["panScroller"]["dom"]] == ["scroll"]
    assert result["panScroller"]["refusals"] == []
    assert {row[1] for row in result["panScroller"]["dom"]} == {"pan"}

    assert result["panButton"]["dom"] == [], "rien ne doit arriver à la cible"
    assert result["panButton"]["refusals"] == ["tool_target_unsupported"]

    assert [row[0] for row in result["selectField"]["dom"]] == ["select"]
    assert result["selectField"]["refusals"] == []

    assert result["selectCard"]["dom"] == []
    assert result["selectCard"]["refusals"] == ["tool_target_unsupported"]

    # Et le sens forcé l'emporte sur le sens contextuel : sans outil, une étoile
    # qui défile se sélectionnerait déjà ; c'est la carte ci-dessus qui montre
    # que `select` impose quelque chose que le contexte n'aurait pas choisi.
    assert [row[0] for row in result["selectScroller"]["dom"]] == ["select"]


def test_a_tool_declared_without_an_engine_refuses_every_capture(tmp_path):
    """Un outil sans moteur ne ressemble jamais à un outil qui marche.

    **La couche d'annotation est hors V1** : `highlighter` et `draw` ont quitté
    la table des outils, donc aucun nom du produit n'atteint plus ce refus. Il
    reste la recette d'extension — et une recette qu'aucun test n'exerce est un
    souhait. On déclare donc ici l'outil que la Slice qui rouvrira le sujet
    déclarera : une capacité `annotate` que `SERVED_CAPABILITIES` ne sert pas,
    injectée par la **vraie** couture `contracts` du moteur.

    Le moteur est injectable et ne suppose pas que son appelant a filtré (même
    raison que `target_not_actionable`, Slice 06) : il refuse donc partout —
    corps **et** zone —, parce qu'un outil indisponible n'a pas de cible
    privilégiée.
    """

    result = run_node(tmp_path, FIXTURE + """
      /* La table des outils d'une V2 possible : un outil de plus, sa capacité
         `annotate`, et rien qui la serve. Tout le reste du contrat est le vrai
         — c'est `toolCapability` seul qui est élargi, exactement ce qu'une
         entrée de plus dans `TOOL_CAPABILITY` produirait. */
      const FUTURE=Object.assign({},C,{
        toolCapability:name=>String(name)==='ink'?'annotate':C.toolCapability(name),
      });
      const zoneRun=(tool,contracts)=>{
        const e=engineOf({dom:makeDom([]).api,world:makeWorld({A:{box:{x:0,y:0,w:64,h:40},
          representation:'window'}}),slotOf:()=>0,contracts:contracts||C});
        if(tool)e.setTool(tool);
        const s=e.update({now:0,tokens:[tok(1,400,300)],
          targets:[tgt(1,'A','edge','right')],events:[ev(1,'down',400,300)],
          contacts:[held(1,'undecided')]});
        return {refusals:s.refusals.map(r=>r.reason),captures:s.captures.length};
      };
      out({
        body:bodyRun('ink','button',false,null,FUTURE),
        onScroller:bodyRun('ink','card',true,null,FUTURE),
        zone:zoneRun('ink',FUTURE),
        zoneWithPointer:zoneRun('pointer'),
        unknown:refused(()=>engineOf({}).setTool('gomme')),
        // Et les deux noms retirés ne sont plus « déclarés sans moteur » : ils
        // sont inconnus, comme n'importe quel nom qui n'est pas au contrat.
        retired:refused(()=>engineOf({}).setTool('highlighter')),
        // Une palette et un moteur qui ne s'accordent pas sur « installé »
        // donneraient un outil choisissable et sans effet.
        installed:C.INSTALLED_TOOLS,
        declared:C.TOOLS,
      });
    """)
    assert result["body"]["dom"] == [] and result["body"]["refusals"] == ["tool_not_installed"]
    assert result["onScroller"]["dom"] == [] and result["onScroller"]["refusals"] == ["tool_not_installed"]
    assert result["zone"] == {"refusals": ["tool_not_installed"], "captures": 0}
    assert result["zoneWithPointer"] == {"refusals": [], "captures": 1}
    assert result["unknown"] == "barehands_tool_unknown"
    assert result["retired"] == "barehands_tool_unknown"
    assert result["installed"] == list(barehands.INSTALLED_TOOLS)
    assert result["declared"] == list(barehands.TOOLS) == ["pointer", "pan", "select"]


def test_a_tool_never_takes_a_frame_handle_nor_the_only_grip_of_a_move_only_star(tmp_path):
    """L'outil change le sens du **contenu**, pas celui d'un cadre.

    Un bord et un coin restent des poignées (décisions 9 à 11) quel que soit
    l'outil : les rendre à l'outil actif ferait disparaître le redimensionnement
    dès qu'on choisit la Main. Et le corps d'une étoile `point`/`signal` est sa
    **seule** prise (décision D3) — la lui prendre la rendrait immobile sous
    tout autre outil, en silence."""

    result = run_node(tmp_path, FIXTURE + """
      const world=makeWorld({A:{box:{x:0,y:0,w:64,h:40},representation:'window'},
                             S:{box:{x:0,y:0,w:6,h:6},representation:'point'}});
      const run=(tool,target)=>{
        const dom=makeDom([]);
        const e=engineOf({dom:dom.api,world,slotOf:()=>0});
        if(tool)e.setTool(tool);
        const s0=e.update({now:0,tokens:[tok(1,400,300)],targets:[target],
          events:[ev(1,'down',400,300)],contacts:[held(1,'undecided')]});
        const s1=e.update({now:16,tokens:[tok(1,460,300)],targets:[target],
          events:[],contacts:[held(1,'drag')]});
        return {refusals:s0.refusals.concat(s1.refusals).map(r=>r.reason),
          drove:e.drivenHands(),dom:dom.log.map(d=>d.type)};
      };
      const zone=tgt(1,'A','edge','right');
      const star=Object.assign(tgt(1,'S','body',null),{representation:'point'});
      out({
        panOnZone:run('pan',zone),
        selectOnZone:run('select',zone),
        pointerOnZone:run('pointer',zone),
        panOnStar:run('pan',star),
        pointerOnStar:run('pointer',star),
      });
    """)
    # Une zone se conduit pareil sous les trois outils installés.
    for key in ("panOnZone", "selectOnZone", "pointerOnZone"):
        assert result[key]["refusals"] == [], key
        assert result[key]["drove"] == ["1"], key
        assert result[key]["dom"] == [], "une zone n'émet aucune séquence de pointeur"
    # Le corps d'une étoile déplaçable seulement reste sa prise, même sous `pan`
    # — qui refuserait n'importe quel autre corps non défilant.
    assert result["panOnStar"]["refusals"] == []
    assert result["panOnStar"]["drove"] == ["1"]
    assert result["panOnStar"] == result["pointerOnStar"]


# ------------------------------------------------------------------ réglages


def test_a_sleep_timeout_under_the_wake_hold_is_refused_where_it_arrives(tmp_path):
    """Septième paire dangereuse, et la première que les **réglages** rendent
    atteignable.

    Sous `wakeHoldMs`, la seconde de posture en C coûte plus cher que tout le
    temps qu'elle achète : on réveille, et la veille a déjà repris la main à
    l'image suivante. La session cycle — réveil, veille, réveil — en détruisant
    à chaque tour les identités de piste et les fentes de pointeur. Rien ne
    lève, rien ne tombe : le réveil a simplement l'air de ne pas tenir.

    Elle se refuse à la construction **et** à la reconfiguration : une paire
    gardée au seul constructeur est une paire sans garde dès qu'un réglage
    existe."""

    result = run_node(tmp_path, WORLD + """
      const ctrl=()=>B.createController(world({options:{sleepTimeoutMs:30000,wakeHoldMs:1000}}).deps);
      out({
        built:refused(()=>B.createController(world({options:{sleepTimeoutMs:900,wakeHoldMs:1000}}).deps)),
        equal:refused(()=>B.createController(world({options:{sleepTimeoutMs:1000,wakeHoldMs:1000}}).deps)),
        fine:B.createController(world({options:{sleepTimeoutMs:1001,wakeHoldMs:1000}}).deps)
          .configure({}).sleepTimeoutMs,
        // Le plancher du contrat est cinq fois au-dessus : un réglage venu de
        // l'écran ne peut pas atteindre la zone dangereuse. C'est justement
        // pour ça qu'il faut la refuser ici plutôt que d'y compter.
        floorIsSafe:C.SETTINGS_BOUNDS.sleepTimeoutMs.min>C.WAKE_HOLD_MS,
        configured:refused(()=>ctrl().configure({sleepTimeoutMs:500})),
        // Et le moteur garde ce qu'il avait : `options()` lève **avant** qu'on
        // garde quoi que ce soit, donc un réglage refusé ne laisse pas le
        // contrôleur à moitié changé.
        kept:(()=>{const c=ctrl();
          try{c.configure({sleepTimeoutMs:500})}catch(_e){}
          return c.configure({}).sleepTimeoutMs})(),
        // Et les surcharges s'accumulent : deux réglages qui ne voyagent pas
        // ensemble ne se défont pas l'un l'autre.
        accumulated:(()=>{const c=ctrl();
          c.configure({sleepTimeoutMs:45000});
          const after=c.configure({dragSlopPx:52,clickSlopPx:24});
          return [after.sleepTimeoutMs,after.dragSlopPx]})(),
      });
    """, name="pairs")
    assert result["built"] == "RangeError"
    assert result["equal"] == "RangeError", "un réveil qui dure exactement sa propre posture n'en est pas un"
    assert result["fine"] == 1001
    assert result["floorIsSafe"] is True
    assert result["configured"] == "RangeError"
    assert result["kept"] == 30000
    assert result["accumulated"] == [45000, 52]


def test_the_sleep_timeout_setting_really_brings_the_session_back_to_sleep(tmp_path):
    """`sleepTimeoutMs` était exposé, normalisé, persisté — et **inerte** : le
    contrôleur lisait la constante `SLEEP_TIMEOUT_MS`. Ce test est ce qui
    interdit d'y revenir, et il compte le temps du monde injecté plutôt que de
    relire le réglage qu'on vient d'écrire — relire un champ ne prouve rien.

    Cinq secondes est la borne basse du contrat : c'est donc le réglage le plus
    court qu'un utilisateur puisse réellement demander."""

    result = run_node(tmp_path, WORLD + """
      const run=async(timeout,waitS)=>{
        const w=world({result:{landmarks:[hand(.2)]},options:{sleepTimeoutMs:30000}});
        const c=B.createController(w.deps);
        await c.enable();await c.activate();
        c.configure({sleepTimeoutMs:timeout});
        w.steps(3,1000);                       // une main vue, le délai se réarme
        w.state.result=NO_HAND;
        w.steps(waitS,1000);
        return c.state();
      };
      out({
        // Réglé à 5 s : endormi au bout de 5 s, pas des 30 s d'usine.
        shortBefore:await run(5000,4),
        shortAfter:await run(5000,5),
        // Et le contraire : réglé à 120 s, toujours actif là où l'usine aurait
        // déjà rendu la main.
        longAtThirtyOne:await run(120000,31),
        longAtHundredTwenty:await run(120000,120),
        // Sans réglage, la constante du contrat reste le défaut.
        factory:await (async()=>{
          const w=world({result:{landmarks:[hand(.2)]},options:{sleepTimeoutMs:C.SLEEP_TIMEOUT_MS}});
          const c=B.createController(w.deps);
          await c.enable();await c.activate();
          w.steps(3,1000);w.state.result=NO_HAND;w.steps(30,1000);
          return c.state()})(),
      });
    """, name="sleep")
    assert result["shortBefore"] == "active", "quatre secondes ne suffisent pas à un réglage de cinq"
    assert result["shortAfter"] == "sleep", "le réglage raccourcit vraiment le retour en veille"
    assert result["longAtThirtyOne"] == "active", "le réglage allonge vraiment le délai d'usine"
    assert result["longAtHundredTwenty"] == "sleep"
    assert result["factory"] == "sleep"


def test_sensitivity_moves_the_drag_threshold_and_keeps_the_click_under_it(tmp_path):
    """`sensitivity` **divise** les deux tolérances de déplacement du moteur.

    Les deux par le même facteur, donc l'invariant `clickSlopPx <= dragSlopPx`
    (cinquième paire dangereuse, Slice 04) traverse intact quel que soit le
    réglage — et le réglage est mesuré sur ce qu'il change vraiment : la même
    main, le même déplacement, un clic d'un côté et un glissement de l'autre.

    1 rend **exactement** les défauts du moteur : règle de la Slice 05 — quand
    un réglage stocké multiplie une constante, son défaut doit rendre le défaut
    du moteur, sans quoi brancher le champ serait à soi seul une régression
    invisible."""

    result = run_node(tmp_path, """
      /* Un contact franc, tiré sur `travel` pixels de paume, avec la
         sensibilité demandée. Le canal est le **vrai** : c'est lui qui décide
         clic ou glissement (Slice 04). */
      const intentOf=(sensitivity,travel)=>{
        const ch=B.createPinchChannel('primary',{
          clickSlopPx:B.DEFAULTS.clickSlopPx/sensitivity,
          dragSlopPx:B.DEFAULTS.dragSlopPx/sensitivity});
        const at=(now,x,ratio)=>ch.update({handTrackId:1,ratio,other:1,confidence:1,
          quality:1,stillness:1,now,x,y:0,palmX:x,palmY:0,anchorX:x,anchorY:0});
        at(0,0,.6);at(16,0,.1);at(32,0,.1);       // descente (pressFrames)
        at(48,travel,.1);                          // la main parcourt `travel`
        const produced=at(64,travel,.9);           // relâchement
        const up=produced.find(e=>e.phase==='up');
        return up?up.intent:null;
      };
      out({
        near:[.25,.5,1,2,4].map(s=>intentOf(s,8)),
        far:[.25,.5,1,2,4].map(s=>intentOf(s,30)),
        // Divisées par le même facteur, les deux tolérances gardent leur ordre :
        // aucune sensibilité ne peut produire la paire que la Slice 04 refuse.
        ordered:[.25,.5,1,2,4].every(s=>{
          try{B.createPinchChannel('primary',{clickSlopPx:B.DEFAULTS.clickSlopPx/s,
            dragSlopPx:B.DEFAULTS.dragSlopPx/s});return true}catch(_e){return false}}),
        // Et l'ordre inverse se refuse toujours, là où il se lit.
        inverted:refused(()=>B.createPinchChannel('primary',{clickSlopPx:100})),
        defaults:[B.DEFAULTS.clickSlopPx,B.DEFAULTS.dragSlopPx],
      });
    """, name="sensitivity")
    # Huit pixels de paume : un clic tant que la tolérance de clic reste
    # au-dessus, un glissement dès que la sensibilité la fait passer dessous.
    assert result["near"] == ["click", "click", "click", "drag", "drag"]
    # Trente pixels : le seuil de glissement lui-même se déplace.
    assert result["far"] == ["click", "drag", "drag", "drag", "drag"]
    assert result["ordered"] is True
    assert result["inverted"] == "RangeError"
    assert result["defaults"] == [12, 26]


def test_sensitivity_reaches_a_hand_that_is_already_being_tracked(tmp_path):
    """Le test qui manquait, et que trois mutants ont trouvé avant lui.

    Le précédent pilotait un canal de pincement construit à la main : il
    prouvait que les seuils font ce qu'ils disent, pas que le **réglage** les
    atteint. Trois lignes pouvaient disparaître sans rien faire tomber — le
    contrôleur ne transmettant plus rien au moteur de pincement, et le moteur
    ne transmettant plus rien aux mains déjà suivies.

    Celui-ci part d'une vraie géométrie de main, passe par le traqueur, le
    filtre et les deux moteurs de la Slice 04, **à travers le contrôleur
    entier** — et il change le réglage alors que la main est déjà là depuis
    huit images. C'est le seul montage où « la main qui est sous la caméra au
    moment du changement » existe."""

    result = run_node(tmp_path, WORLD + PINCH_GEOMETRY + """
      /* Une main posée qui glisse d'un dixième de pour-cent d'image par image,
         puis pince et relâche. Mesuré : 10,1 px de paume parcourus — entre la
         tolérance de clic d'usine (12) et celle d'une sensibilité double (6). */
      const pinchAt=async sensitivity=>{
        const w=world({result:{landmarks:[PINCHING(0,1,{palm:.16})]}});
        w.deps.viewport=()=>({width:1920,height:1080});
        const c=B.createController(w.deps);
        await c.enable();await c.activate();
        // Huit images main ouverte : la piste **et ses deux canaux** existent
        // avant le réglage.
        for(let i=0;i<8;i+=1){w.state.result={landmarks:[PINCHING(0,1,{palm:.16})]};w.step(16)}
        if(sensitivity!==null)c.configure({
          clickSlopPx:B.DEFAULTS.clickSlopPx/sensitivity,
          dragSlopPx:B.DEFAULTS.dragSlopPx/sensitivity});
        const ups=[];
        for(let i=0;i<26;i+=1){
          const t=i<6?0:i<12?(i-6)/6:i<22?1:0;
          w.state.result={landmarks:[PINCHING(t,1,{cx:.5+.01*i/25,palm:.16})]};
          w.step(16);
          for(const e of c.semantics().pinch.events)
            if(e.phase==='up')ups.push([e.intent,Number(e.travelPx.toFixed(1))]);
        }
        return ups;
      };
      out({
        factory:await pinchAt(null),
        neutral:await pinchAt(1),
        doubled:await pinchAt(2),
        quadrupled:await pinchAt(4),
        halved:await pinchAt(.5),
      });
    """, name="chain")
    # Sans réglage, et avec le réglage neutre : le même verdict. Brancher le
    # champ ne change rien par lui-même (règle de la Slice 05).
    assert result["factory"] == [["click", 10.1]]
    assert result["neutral"] == result["factory"]
    assert result["halved"] == result["factory"]
    # Le même geste, la même main, déjà suivie : le réglage le fait basculer.
    assert result["doubled"] == [["drag", 10.1]]
    assert result["quadrupled"] == [["drag", 10.1]]


# ------------------------------------------------------------------- l'écran


#: Le bloc navigateur et l'onglet Expérimental, avec un DOM juste assez réel
#: pour **échouer** comme le vrai : `innerHTML` construit des éléments à partir
#: du balisage que la page écrit vraiment, les sélecteurs cherchent dans ces
#: éléments, et les écouteurs se déclenchent. Un double qui ne peut pas échouer
#: comme le vrai ne prouve rien (leçon de la reprise de la Slice 06).

#: À préfixer à `BROWSER` pour que le double de navigateur ait une caméra : sans
#: elle, `enable()` refuse sur `camera_unsupported` avant même de charger le
#: modèle et le contrôleur ne peut jamais être engagé.
CAMERA = "var WANT_CAMERA=true;\n"

BROWSER_HEAD = ELEMENTS + r"""
const live=[];
const parse=html=>{
  const found=[];
  const re=/<(input|button|strong|div|section)\b([^>]*)>/g;
  let m;
  while((m=re.exec(html))!==null){
    const tag=m[1],raw=m[2],attrs={};
    const ar=/([a-zA-Z_:][-\w:.]*)(?:="([^"]*)")?/g;
    let a;
    while((a=ar.exec(raw))!==null)attrs[a[1]]=a[2]===undefined?'':a[2];
    const text=tag==='strong'?(html.slice(re.lastIndex).match(/^([^<]*)/)||['',''])[1]:'';
    found.push(makeNode(tag,attrs,text));
  }
  return found;
};
const makeNode=(tag,attrs,text)=>{
  attrs=attrs||{};
  const classes=new Set(String(attrs.class||'').split(/\s+/).filter(Boolean));
  const listeners={};
  return {
    tag,attrs,id:attrs.id||'',textContent:text||'',className:attrs.class||'',
    checked:'checked' in attrs,disabled:'disabled' in attrs,
    value:attrs.value===undefined?'':attrs.value,
    offsetWidth:1,registers:false,_html:'',
    style:{setProperty(k,v){this[k]=v}},dataset:{},children:[],parent:null,
    classList:{add:c=>classes.add(c),remove:c=>classes.delete(c),
      toggle:(c,on)=>{if(on)classes.add(c);else classes.delete(c)},contains:c=>classes.has(c)},
    classes,listeners,
    getAttribute(k){return this.attrs[k]===undefined?null:this.attrs[k]},
    setAttribute(k,v){this.attrs[k]=String(v)},
    matches:()=>false,getBoundingClientRect:()=>({left:0,top:0,width:0,height:0}),
    dispatchEvent(){return true},
    addEventListener(type,fn){(listeners[type]=listeners[type]||[]).push(fn)},
    fire(type,event){for(const fn of (listeners[type]||[]).slice())fn(Object.assign({target:this,preventDefault(){}},event||{}))},
    appendChild(c){c.parent=this;this.children.push(c)},
    remove(){if(!this.parent)return;const at=this.parent.children.indexOf(this);
      if(at>=0)this.parent.children.splice(at,1);this.parent=null},
    /* Seul `#modalContent` réenregistre : c'est lui que la page réécrit en
       entier. Les petits blocs que `refreshPanel` rafraîchit (statut, cycle de
       vie, assets) ne doivent surtout pas effacer la liste des contrôles — le
       faire aurait rendu le harnais incapable de voir le rafraîchissement, ce
       que le vrai DOM ne fait pas. */
    /* Écrire `innerHTML` **détruit** les enfants : c'est ce que fait le vrai
       DOM, et c'est exactement ce que le constat F5 redoute (une section
       ajoutée par un autre module emportée par une réécriture). Le double ne
       le faisait pas — il ne pouvait donc pas échouer comme le vrai. Le
       compteur, lui, rend la réécriture **observable** : « le panneau n'est
       pas réécrit » est une affirmation qu'un test peut tenir. */
    set innerHTML(html){this._html=html;this.htmlWrites=(this.htmlWrites||0)+1;
      for(const child of this.children.splice(0))child.parent=null;
      if(this.registers){live.length=0;for(const n of parse(html))live.push(n)}},
    get innerHTML(){return this._html},
  };
};
/* Ce que la page **crée** elle-même (la surimpression, l'hôte de l'aperçu)
   vit dans l'arbre de `document.body`, pas dans le balisage que l'onglet vient
   d'écrire : `getElementById` doit donc chercher dans les deux, comme le vrai.
   Sans cela `createTargetPreview` ne trouve jamais son hôte et ne dessine
   rien — un double qui ne peut pas réussir comme le vrai ne prouve pas plus
   qu'un double qui ne peut pas échouer. */
const deep=(root,id)=>{
  for(const child of root.children){
    if(child.id===id)return child;
    const found=deep(child,id);
    if(found)return found;
  }
  return null;
};
const modalContent=makeNode('div',{id:'modalContent'});
modalContent.registers=true;
const fixed={modalContent,modalSave:makeNode('div',{id:'modalSave'}),
  modalSub:makeNode('div',{id:'modalSub'})};
global.window={addEventListener(){},innerWidth:1000,innerHeight:800};
global.document={createElement:tag=>makeNode(tag,{},''),
  head:makeNode('head',{},''),body:makeNode('body',{},''),
  activeElement:null,
  getElementById:id=>fixed[id]||live.find(n=>n.id===id)||deep(global.document.body,id)||null,
  querySelector:sel=>(global.document.querySelectorAll(sel)[0]||null),
  /* Deux arbres dans un seul document, et c'est le vrai qui décide lequel :
     les **contrôles** de l'onglet sont ceux que `innerHTML` vient d'écrire (on
     les cherche par attribut), et le reste de la **page** — ce qu'une main
     peut viser — est posé par le test dans `global.page`, avec sa géométrie.
     Sans le second, aucun réglage qui agit sur la résolution de cible
     (`assistance`, `targetPreview`, l'outil) n'a de comportement observable
     ici : la collecte rendrait toujours une liste vide. */
  querySelectorAll:sel=>{
    const m=/^\[([-\w]+)(?:="([^"]*)")?\]$/.exec(sel);
    if(!m)return pageQuery(sel);
    return live.filter(n=>n.attrs[m[1]]!==undefined&&(m[2]===undefined||n.attrs[m[1]]===m[2]));
  },
  elementFromPoint:pageAt};
/* **Pas de caméra par défaut** : node n'en a pas, et plusieurs tests décrivent
   précisément ce refus de démarrage (`camera_unsupported`), y compris ceux du
   canal de commandes de la Slice 12. Un test qui a besoin d'un contrôleur
   **engagé** — la seule façon d'observer « décocher libère la caméra » —
   préfixe sa source par la constante `CAMERA`.

   `global.navigator=...` ne prend pas : node 21+ en expose un en lecture
   seule, et l'affectation échouait **en silence**, le double héritant du
   navigateur de node sans que rien ne le dise. */
const cameraDouble=(typeof WANT_CAMERA!=='undefined'&&WANT_CAMERA)
  ?{getUserMedia:async()=>({getTracks:()=>[],getVideoTracks:()=>[]})}:null;
Object.defineProperty(global,'navigator',{configurable:true,writable:true,
  value:{mediaDevices:cameraDouble}});
global.performance={now:()=>global.clock||0};
global.clock=0;
global.requestAnimationFrame=()=>0;global.cancelAnimationFrame=()=>{};
/* La page installe son onglet dans un `setTimeout(...,0)` : l'exécuter tout de
   suite est ce que fait le navigateur une image plus tard, et c'est la seule
   façon d'exercer le **vrai** chemin d'installation plutôt qu'un appel direct
   à une fonction interne. */
global.setTimeout=fn=>{fn();return 0};
global.setInterval=()=>0;global.clearInterval=()=>{};
global.MouseEvent=class{constructor(type,init){Object.assign(this,init||{});this.type=type}};
global.esc=v=>String(v).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
global.JarvisBarehandsContracts=C;
global.window.JarvisBarehandsContracts=C;
global.JarvisBarehandsTarget=require(TARGET_PATH);
/* Parcours de calibration (Slice 08) : la page l'insere entre les contrats
   et le pointeur, qui le lit pour poser `calibrate()` sur sa surface gelee. */
global.JarvisBarehandsCalibration=require(CALIBRATION_PATH);
global.JarvisSceneInteract=require(SCENE_INTERACT_PATH);

/* Le serveur : la **même** forme que la vraie route — il range ce qu'on lui
   envoie et le rend à plat. Ce qui lie ce double au vrai gestionnaire est un
   test de parité à part
   (`test_the_payload_the_page_builds_is_accepted_by_the_real_route`). */
/* L'état de départ est celui d'une installation neuve, **tel que le vrai
   `describe()` le rend** : les trois champs que la page lit pour distinguer
   « des défauts parce qu'illisible » de « des défauts parce que neuf » en font
   partie. Un double qui ne les porte pas ne peut pas tomber comme le vrai. */
const server={state:Object.assign(C.toServerPayload({}),
    {stored_schema_version:null,unreadable:false,archived:[]}),
  calls:[],fail:null,gate:null,hangGet:false,foreignVersion:3,profileFail:null};
/* Le profil de calibration (Slice 08) a sa **propre** route, comme le vrai
   serveur : l'ecrire ne revalide pas les neuf reglages, et la relire ne passe
   pas par le meme bloc. Un double qui les confondrait cacherait exactement ce
   que la separation existe pour garantir. */
server.profile={schema_version:2,calibrated:false,updated_at:null,
  hands:{left:{},right:{},unknown:{}},
  stages:{},stored_schema_version:null,unreadable:false,archived:[]};
const emptyHand=()=>({press_ratio:null,release_ratio:null,
  secondary_press_ratio:null,secondary_release_ratio:null,
  jitter_px:null,travel_slop_norm:null,reach_norm:null,quality:null});
const profileState=()=>({...server.profile,
  hands:Object.fromEntries(['left','right','unknown'].map(h=>
    [h,Object.assign(emptyHand(),server.profile.hands[h]||{})])),
  stages:Object.fromEntries(['neutral','c_pose','pinch_primary','pinch_secondary',
    'aim','drag','resize'].map(k=>[k,server.profile.stages[k]
      ||{status:'skipped',reason:null,samples:0}])),
  calibrated:['left','right','unknown'].some(h=>Object.values(server.profile.hands[h]||{})
    .some(v=>v!==null&&v!==undefined))});
global.api=async(path,opts)=>{
  server.calls.push({path,body:opts&&opts.body?JSON.parse(opts.body):null});
  if(String(path).endsWith('/profile')){
    if(server.profileFail)throw Object.assign(new Error(server.profileFail),{status:400});
    const method=(opts&&opts.method)||'GET';
    if(method==='POST'){
      const body=JSON.parse(opts.body);
      server.profile={...server.profile,hands:body.hands,stages:body.stages,
        updated_at:body.updated_at};
    }else if(method==='DELETE'){
      server.profile={...server.profile,hands:{left:{},right:{},unknown:{}},
        stages:{},updated_at:null};
    }
    return profileState();
  }
  if(!opts||opts.method!=='POST'){
    /* Une lecture qui ne revient pas : c'est la seule façon de tenir le
       contrôleur en `starting` sans caméra, puisque le chargement du modèle
       commence par relire `/api/barehands`. */
    if(server.hangGet)return new Promise(()=>{});
    return Object.assign({},server.state,{assets:{installed:true,missing:[]}});
  }
  // Une écriture qu'on peut retenir : deux écritures concurrentes n'existent
  // que si la première est encore en vol quand la seconde part.
  if(server.gate)await server.gate;
  if(server.fail)throw Object.assign(new Error(server.fail),{status:400});
  server.state=Object.assign({},server.state,JSON.parse(opts.body));
  /* Comme le vrai `apply` : un bloc illisible est rangé sous sa clé de version
     **avant** d'être remplacé, et la réponse suivante n'est plus « illisible »
     mais « une archive existe ». Un double qui garderait `unreadable` vrai
     après l'écriture rendrait le bandeau de retour intestable. */
  if(server.state.unreadable){
    server.state=Object.assign({},server.state,{unreadable:false,
      stored_schema_version:C.SETTINGS_SCHEMA_VERSION,
      archived:server.state.archived.concat([`barehands_test_mode_archived_v${server.foreignVersion}`])});
  }
  return Object.assign({},server.state,{assets:{installed:true,missing:[]}});
};
/* Le journal de la page, capture plutot que laisse partir sur la sortie : il
   fait partie du contrat (le chemin **normal** se journalise, pas seulement
   l'echec), donc les tests l'affirment au lieu de le subir. */
const logged=[];
const realConsole=console;
global.console=Object.assign(Object.create(realConsole),{
  info:(...a)=>logged.push(['info',a.map(String).join(' ')]),
  warn:(...a)=>logged.push(['warn',a.map(String).join(' ')]),
  error:(...a)=>realConsole.error(...a)});
global.toast=(t)=>{toasts.push(t&&t.kind)};
const toasts=[];
global.say=()=>{};
global.confirmDialog=async()=>true;
global.TABS=[];
global.renderTab=async()=>'base';
global.SET={open:true,tab:'experimental',data:{}};
global.modalSave=fixed.modalSave;
global.modalSub=fixed.modalSub;
global.modalContent=modalContent;

"""

#: Ce que le fichier de réglages contient **avant** que la page ne se charge.
#: La page relit `/api/barehands` dès son démarrage, donc un test qui configure
#: le double après coup décrit une situation qui n'arrive jamais : le serveur
#: aurait changé d'avis entre le chargement et la première image. Tout ce qui
#: doit être vrai *à l'ouverture de l'onglet* s'écrit ici.
BROWSER_TAIL = r"""
delete require.cache[require.resolve(SCRIPT_PATH)];
require(SCRIPT_PATH);
const BAREHANDS=window.JarvisBarehands;
const settle=async()=>{for(let i=0;i<12;i+=1)await new Promise(r=>setImmediate(r))};
const openTab=async()=>{await settle();await renderTab();await settle()};
const byAttr=(name,value)=>live.find(n=>n.attrs[name]===value)||null;
"""

BROWSER = BROWSER_HEAD + BROWSER_TAIL


def browser(setup: str = "") -> str:
    """Le monde navigateur, avec un état de serveur posé avant le chargement."""

    return BROWSER_HEAD + setup + BROWSER_TAIL


def test_the_tab_draws_two_surfaces_and_writes_what_is_touched(tmp_path):
    """**Décision 25, à l'écran** : Outils et Réglages sont deux sections, et
    ce que l'on touche part sur la route et atteint le moteur.

    La palette est dessinée à partir de la table du contrat, pas d'une liste
    recopiée : un outil ajouté au contrat apparaît, un outil sans moteur est
    dessiné et **désarmé** — le retirer ferait croire qu'il n'existe pas."""

    result = run_node(tmp_path, BROWSER + """
      await openTab();
      const html=modalContent.innerHTML;
      const tools=live.filter(n=>n.attrs['data-barehands-tool']);
      const before=tools.map(n=>[n.attrs['data-barehands-tool'],n.disabled,n.attrs['aria-checked']]);
      // Choisir un outil installé : il s'enregistre et atteint le moteur.
      byAttr('data-barehands-tool','pan').fire('click');
      await settle();
      const afterTool=live.filter(n=>n.attrs['data-barehands-tool'])
        .map(n=>[n.attrs['data-barehands-tool'],n.attrs['aria-checked']]);
      // Décocher l'aperçu de cible : décision 24.
      const preview=byAttr('data-barehands-check','targetPreview');
      preview.checked=false;preview.fire('change');
      await settle();
      // Tirer un curseur : `input` dit le chiffre, `change` enregistre.
      const range=byAttr('data-barehands-range','sleepTimeoutMs');
      range.value='120000';range.fire('input');
      const shown=live.find(n=>n.attrs['data-barehands-value']==='sleepTimeoutMs').textContent;
      range.fire('change');
      await settle();
      /* Le reglage a-t-il atteint le **moteur** ? On le demande a l'adaptateur
         d'apercu, pas a `view.settings` : relire ce qu'on vient d'ecrire ne
         prouve rien. Lu maintenant, avant la reinitialisation qui le rendra. */
      const previewReached=BAREHANDS.targetPreview();
      const toolReached=BAREHANDS.adapters.interaction.tool();
      // Reinitialiser : les valeurs d'usine reviennent, l'interrupteur NON.
      const wasEnabled=BAREHANDS.settings().enabled;
      document.getElementById('barehandsReset').fire('click');
      await settle();
      out({
        sections:[/id="barehandsTools"/.test(html),/id="barehandsSettings"/.test(html)],
        // Le reglage atteint le moteur, il n'est pas seulement enregistre :
        // l'apercu se relit sur l'adaptateur, pas sur `view.settings`.
        previewReached,toolReached,
        reset:[BAREHANDS.settings().sleepTimeoutMs,BAREHANDS.settings().tool,
               BAREHANDS.settings().targetPreview,BAREHANDS.settings().enabled,wasEnabled],
        radiogroup:/role="radiogroup"/.test(html),
        before,afterTool,shown,
        // Chaque case et chaque curseur porte un `label for` : un réglage sans
        // étiquette cliquable n'est pas utilisable au clavier.
        labelled:['targetPreview','diagnostics','calibrationEnabled','tutorialSeen',
                  'assistance','sensitivity','sleepTimeoutMs']
          .every(k=>html.includes(`for="bh_${k}"`)&&html.includes(`id="bh_${k}"`)),
        // Les bornes des curseurs viennent de la table du contrat.
        bounds:['assistance','sensitivity','sleepTimeoutMs'].map(k=>
          [html.includes(`min="${C.SETTINGS_BOUNDS[k].min}"`),
           html.includes(`max="${C.SETTINGS_BOUNDS[k].max}"`)]),
        writes:server.calls.filter(c=>c.body).map(c=>[c.body.tool,c.body.target_preview,c.body.sleep_timeout_ms]),
        engine:BAREHANDS.settings(),
        tool:BAREHANDS.adapters.interaction.tool(),
        // Le chemin **normal** se journalise aussi : « rien dans le journal »
        // ne doit pas vouloir dire a la fois « tout va bien » et « mort ».
        logged:logged.filter(l=>l[0]==='info').length,
      });
    """, name="tab")
    assert result["sections"] == [True, True], "deux surfaces distinctes, pas une liste fondue"
    assert result["radiogroup"] is True
    assert result["labelled"] is True
    assert result["bounds"] == [[True, True], [True, True], [True, True]]
    # Les cinq outils du contrat sont dessinés ; les deux sans moteur sont désarmés.
    assert [row[0] for row in result["before"]] == list(barehands.TOOLS)
    for tool, disabled, _checked in result["before"]:
        assert disabled is (tool not in barehands.INSTALLED_TOOLS), tool
    assert result["before"][0][2] == "true", "le pointeur est l'outil actif au départ"
    assert dict(result["afterTool"])["pan"] == "true"
    assert dict(result["afterTool"])["pointer"] == "false"
    # Trois écritures, chacune portant ce qui a été touché dans la charge utile
    # complète que `toServerPayload` construit.
    assert result["writes"] == [
        ["pan", True, 30000],
        ["pan", False, 30000],
        ["pan", False, 120000],
        ["pointer", True, 30000],
    ]
    assert result["shown"] == "120 s", "le chiffre suit le curseur pendant qu'on le tire"
    # Le reglage a vraiment atteint l'apercu, et pas seulement le fichier.
    assert result["previewReached"] is False
    # Reinitialiser rend les valeurs d'usine et **ne touche pas** a
    # l'interrupteur : un bouton qui coupe la webcam sans l'annoncer n'est pas
    # une reinitialisation, c'est une extinction deguisee.
    sleep_ms, tool, preview, enabled, was_enabled = result["reset"]
    assert (sleep_ms, tool, preview) == (30000, "pointer", True)
    assert enabled is was_enabled
    # Quatre ecritures reussies, plus la relecture du profil de calibration au
    # demarrage (Slice 08) : le chemin **normal** se journalise aussi, sans quoi
    # « rien dans le journal » voudrait dire a la fois « tout va bien » et « mort ».
    assert result["logged"] == 5, "chaque ecriture reussie laisse une ligne, et la relecture du profil aussi"
    # L'outil aussi atteint le moteur : apres la reinitialisation, la palette
    # et le moteur de captures disent la meme chose.
    assert result["tool"] == "pointer"
    assert result["toolReached"] == "pan", "l'outil choisi atteint le moteur de captures"


def test_resetting_the_settings_never_turns_the_camera_off(tmp_path):
    """Réinitialiser, c'est rendre leur valeur d'usine aux **réglages**.

    L'interrupteur n'en est pas un comme les autres : il tient la caméra. Le
    remettre à son défaut (« éteint ») au passage couperait la webcam sans que
    rien ne l'annonce — ce n'est pas une réinitialisation, c'est une extinction
    déguisée, et c'est précisément la forme de défaut que cette tâche a
    rencontrée sous d'autres noms."""

    result = run_node(tmp_path, BROWSER + """
      await openTab();
      // Allumer, puis s'écarter des valeurs d'usine, puis réinitialiser.
      document.getElementById('f_barehands').checked=true;
      document.getElementById('f_barehands').fire('change');
      await settle();
      byAttr('data-barehands-tool','select').fire('click');
      await settle();
      /* Au clavier : un seul arrêt de tabulation, les flèches parcourent la
         palette et sautent ce qui est désarmé — s'arrêter sur un bouton
         qu'on ne peut pas choisir est un cul-de-sac que la souris ne
         rencontre jamais. Depuis que la couche d'annotation est hors V1, le
         seul désarmement atteignable est celui d'une écriture en vol. */
      /* Tel que la page l'a **écrit**, avant tout rafraîchissement. */
      const firstPaint=(modalContent.innerHTML.match(/<button[^>]*data-barehands-tool[^>]*>/g)||[])
        .filter(tag=>/tabindex="0"/.test(tag))
        .map(tag=>(tag.match(/data-barehands-tool="([^"]+)"/)||[])[1]);
      const focusable=()=>live.filter(n=>n.attrs['data-barehands-tool'])
        .map(n=>[n.attrs['data-barehands-tool'],n.attrs.tabindex,n.disabled]);
      const stops=focusable();
      /* La palette n'offre plus que ce qui marche : `pan` est suivi de
         `select`, et la flèche y va. */
      byAttr('data-barehands-tool','pan').fire('keydown',{key:'ArrowRight'});
      await settle();
      const skipped=BAREHANDS.settings().tool;
      byAttr('data-barehands-tool','select').fire('keydown',{key:'ArrowRight'});
      await settle();
      const wrapped=BAREHANDS.settings().tool;
      byAttr('data-barehands-tool','pointer').fire('keydown',{key:'ArrowLeft'});
      await settle();
      const backwards=BAREHANDS.settings().tool;
      /* La sensibilité maximale doit s'appliquer : les deux tolérances sont
         divisées par le **même** facteur, donc `clickSlopPx <= dragSlopPx`
         tient. N'en diviser qu'une produirait la paire que la Slice 04 refuse,
         et le réglage serait refusé au lieu d'être appliqué. */
      const loud=byAttr('data-barehands-range','sensitivity');
      loud.value=String(C.SETTINGS_BOUNDS.sensitivity.max);loud.fire('change');
      await settle();
      const before=[BAREHANDS.settings().enabled,BAREHANDS.settings().tool,
        BAREHANDS.settings().sensitivity];
      document.getElementById('barehandsReset').fire('click');
      await settle();
      const after=BAREHANDS.settings();
      out({before,
        after:[after.enabled,after.tool,after.assistance,after.sensitivity],
        // Et le serveur a bien reçu « toujours allumé », pas « éteint » :
        // c'est la charge utile qui décide, pas seulement l'écran.
        lastWrite:server.calls.filter(c=>c.body).slice(-1)[0].body.enabled,
        toggle:document.getElementById('f_barehands').checked,
        stops,skipped,wrapped,backwards,firstPaint,
      });
    """, name="reset")
    assert result["before"] == [True, "select", 4], (
        "la sensibilité maximale s'applique, elle ne se refuse pas"
    )
    assert result["after"] == [True, "pointer", 0.5, 1], "tout revient d'usine, sauf l'interrupteur"
    assert result["lastWrite"] is True, "la charge utile de la réinitialisation garde l'interrupteur"
    assert result["toggle"] is True
    # Un seul arrêt de tabulation, sur l'outil actif ; les autres sont hors du
    # parcours. Aucun n'est désarmé : la palette n'offre plus que ce qui marche.
    assert [row[0] for row in result["stops"]] == ["pointer", "pan", "select"]
    assert [row[1] for row in result["stops"]] == ["-1", "-1", "0"], result["stops"]
    assert [row[0] for row in result["stops"] if row[2]] == []
    assert result["skipped"] == "select"
    # Depuis le dernier outil installé, elle revient au premier.
    assert result["wrapped"] == "pointer"
    assert result["backwards"] == "select"
    # Et le **premier** dessin porte déjà l'arrêt de tabulation unique : le
    # rafraîchissement n'arrive qu'après la relecture de `/api/barehands`, qui
    # peut échouer. Un seul `tabindex="0"`, sur l'outil actif.
    assert result["firstPaint"] == ["pointer"]


def test_a_refused_write_gives_the_engine_and_the_screen_their_previous_value_back(tmp_path):
    """RÈGLE ZÉRO, et le piège de l'affichage optimiste : appliquer au moteur
    avant d'enregistrer fait suivre la main sans attendre le réseau — mais si
    l'écriture échoue, laisser le moteur sur la valeur refusée ferait mentir la
    case qu'on vient de décocher. Vu, journalisé, relâché, **et rendu**."""

    result = run_node(tmp_path, BROWSER + """
      await openTab();
      server.fail='réglages indisponibles';
      const preview=byAttr('data-barehands-check','targetPreview');
      preview.checked=false;preview.fire('change');
      await settle();
      const after=BAREHANDS.settings();
      const box=byAttr('data-barehands-check','targetPreview');
      const banner=modalContent.innerHTML;
      out({
        kept:after.targetPreview,
        boxRestored:box.checked,
        released:!byAttr('data-barehands-range','sleepTimeoutMs').disabled,
        warned:logged.filter(l=>l[0]==='warn').length,
        toasted:toasts,
        // Le bandeau du panneau porte la phrase du serveur, pas une phrase
        // générique : c'est la seule information que cette ligne transporte.
        said:/Réglage non enregistré/.test(document.getElementById('barehandsStatus')
          ?document.getElementById('barehandsStatus').innerHTML:banner),
        // Et un refus de schéma **ne s'applique pas** : le contrat lève avant
        // que quoi que ce soit change.
        foreign:(()=>{try{C.fromServerState({schema_version:99});return null}
          catch(e){return e.code}})(),
      });
    """, name="refused")
    assert result["kept"] is True, "le moteur revient à la valeur enregistrée"
    assert result["boxRestored"] is True, "et la case aussi"
    assert result["released"] is True, "aucun contrôle ne reste désarmé après l'échec"
    assert result["said"] is True
    assert result["warned"] >= 1, "et la console garde la cause"
    assert result["toasted"] == ["bad"], "un seul avertissement, du bon genre"
    assert result["foreign"] == "barehands_schema_version_unsupported"


def test_a_refused_tool_says_which_rule_refused_it(tmp_path):
    """RÈGLE ZÉRO. Un refus qui remonte dans `refusals` mais s'affiche « geste
    ignoré » ne transporte plus rien : la seule information de cette ligne est
    **laquelle** des règles a parlé. C'est la même exigence que la Slice 05 a
    posée pour les gestes étouffés et la Slice 06 pour les prises refusées."""

    result = run_node(tmp_path, BROWSER + """
      const overlay=BAREHANDS.adapters.overlay;
      overlay.mount();
      const root=document.body.children[document.body.children.length-1];
      const note=()=>root.children.find(c=>c.className===C.DOM.noteClass);
      const say=reason=>{overlay.render([],reason);const n=note();
        return [n.textContent,n.style.display]};
      out({
        unsupported:say('tool_target_unsupported'),
        notInstalled:say('tool_not_installed'),
        // Les refus des Slices précédentes gardent les leurs, mot pour mot.
        sameZone:say('same_zone_rejected'),
        // Et un motif **inconnu** s'affiche tel quel : le nom exact est la
        // seule information que cette ligne existe pour transporter.
        unknown:say('quelque_chose_de_neuf'),
        silent:say(''),
      });
    """, name="note")
    assert "OUTIL INAPPLICABLE" in result["unsupported"][0]
    assert "OUTIL INDISPONIBLE" in result["notInstalled"][0]
    assert result["unsupported"][0] != result["notInstalled"][0], (
        "deux règles différentes ne peuvent pas rendre la même phrase"
    )
    assert "GESTE IGNOR" not in result["unsupported"][0]
    assert "deux mains sur la même zone" in result["sameZone"][0]
    assert "quelque_chose_de_neuf" in result["unknown"][0]
    assert result["silent"] == ["", "none"]


def test_the_target_preview_and_the_diagnostics_readout_obey_their_settings(tmp_path):
    """**Décision 24** : éteindre l'aperçu retire ce qui est dessiné tout de
    suite, et ne touche **pas** à la résolution de cible — la cible continue
    d'être choisie, seul le dessin disparaît.

    Même forme pour la lecture de diagnostic : elle n'est pas transparente
    quand elle est éteinte, elle est **absente** de l'arbre. C'est la seule
    forme d'un réglage qu'un test puisse affirmer, et la Slice 05 a posé la
    règle pour l'aperçu."""

    result = run_node(tmp_path, BROWSER + """
      const overlay=BAREHANDS.adapters.overlay;
      overlay.mount();
      const root=document.body.children[document.body.children.length-1];
      const diagCount=()=>root.children.filter(c=>c.className===C.DOM.diagClass).length;
      const token=id=>({id,x:10,y:20,progress:0,state:'open',click:false,hover:false,
        quality:.9,speedPxPerSec:42,stillness:.8});
      overlay.render([token(0)]);
      const off=diagCount();
      overlay.showDiagnostics(true);
      const onAtOnce=diagCount();
      const line=root.children.find(c=>c.className===C.DOM.diagClass).textContent;
      overlay.render([token(0),token(1)]);
      const lines=root.children.find(c=>c.className===C.DOM.diagClass).textContent.split('\\n').length;
      overlay.showDiagnostics(false);
      const backOff=diagCount();
      out({off,onAtOnce,line,lines,backOff,
        preview:[BAREHANDS.targetPreview(false),BAREHANDS.targetPreview(true)],
        assistance:[BAREHANDS.targetAssistance(0),BAREHANDS.targetAssistance(1)]});
    """, name="diag")
    assert result["off"] == 0, "éteinte, la lecture est absente de l'arbre, pas transparente"
    assert result["onAtOnce"] == 1, "allumée, elle paraît tout de suite — pas à l'image suivante"
    assert "q 0.90" in result["line"] and "42 px/s" in result["line"] and "imm 0.80" in result["line"]
    assert result["lines"] == 2, "une ligne par main suivie"
    assert result["backOff"] == 0
    assert result["preview"] == [False, True]
    assert result["assistance"] == [0, 1]


# ------------------------------------------- du réglage écrit au comportement

# Les six tests qui suivent ferment le trou que la reprise de la Slice 07 a
# trouvé : les réglages **étaient** branchés, et pourtant cinq lignes de
# `applyToEngine` pouvaient disparaître sans qu'un seul test tombe. La cause
# n'est pas la couverture, c'est le point d'entrée : les tests appelaient la
# porte du moteur (`overlay.showDiagnostics(true)`, `BAREHANDS.targetAssistance(0)`,
# `controller.configure({...})`), ce qui prouve la **méthode** et jamais le
# **câblage**. Ici, rien n'est appelé sur le moteur : on écrit le réglage là où
# l'utilisateur l'écrit — une case, un curseur, un bouton de palette — et on
# regarde ce que la main fait ensuite.


def test_a_slider_written_on_the_screen_is_what_the_engine_then_obeys(tmp_path):
    """`sleepTimeoutMs` et `sensitivity` ne se lisent pas dans le fichier : ils
    se lisent **dans le moteur**, puis se vérifient sur un vrai contrôleur et un
    vrai canal de pincement.

    C'est le test qui tue les deux mutants les plus silencieux : `sleepTimeoutMs`
    revenu à la constante (le réglage redevient inerte, exactement la panne que
    la Slice 07 existait pour fermer) et `sensitivity` qui ne divise qu'une des
    deux tolérances (l'invariant de la Slice 04 se met alors à refuser le tiers
    inférieur du curseur que l'écran propose)."""

    result = run_node(tmp_path, BROWSER + WORLD + """
      await openTab();
      const slide=async(key,value)=>{
        const range=byAttr('data-barehands-range',key);
        range.value=String(value);range.fire('change');
        await settle();
        return BAREHANDS.engine();
      };
      /* Ce que le moteur dit appliquer, rendu à un **vrai** contrôleur : il
         s'endort dessus, ou il ne s'endort pas. Le nombre ne se relit pas, il
         se subit. */
      const sleepsAfter=async(options,waitS)=>{
        const w=world({result:{landmarks:[hand(.2)]},options:{sleepTimeoutMs:C.SLEEP_TIMEOUT_MS}});
        const c=B.createController(w.deps);
        await c.enable();await c.activate();
        c.configure({sleepTimeoutMs:options.sleepTimeoutMs});
        w.steps(3,1000);w.state.result=NO_HAND;w.steps(waitS,1000);
        return c.state();
      };
      /* Et le même pour la sensibilité : le canal de la Slice 04 construit sur
         ce que le moteur applique, la même main, le même déplacement. */
      const verdict=(options,travel)=>{
        const ch=B.createPinchChannel('primary',
          {clickSlopPx:options.clickSlopPx,dragSlopPx:options.dragSlopPx});
        const at=(now,x,ratio)=>ch.update({handTrackId:1,ratio,other:1,confidence:1,
          quality:1,stillness:1,now,x,y:0,palmX:x,palmY:0,anchorX:x,anchorY:0});
        at(0,0,.6);at(16,0,.1);at(32,0,.1);at(48,travel,.1);
        const up=at(64,travel,.9).find(e=>e.phase==='up');
        return up?up.intent:null;
      };
      const factory=BAREHANDS.engine();
      const short=await slide('sleepTimeoutMs',5000);
      const shortAtFour=await sleepsAfter(short,4),shortAtFive=await sleepsAfter(short,5);
      const long=await slide('sleepTimeoutMs',120000);
      const longAtThirtyOne=await sleepsAfter(long,31);
      const loud=await slide('sensitivity',2);
      const quiet=await slide('sensitivity',C.SETTINGS_BOUNDS.sensitivity.min);
      out({
        // Le moteur applique le nombre du curseur, pas la constante d'usine.
        factory:[factory.sleepTimeoutMs,factory.clickSlopPx,factory.dragSlopPx],
        short:short.sleepTimeoutMs,long:long.sleepTimeoutMs,
        shortAtFour,shortAtFive,longAtThirtyOne,
        // Les deux tolérances divisées par le **même** facteur.
        loud:[loud.clickSlopPx,loud.dragSlopPx],
        quiet:[quiet.clickSlopPx,quiet.dragSlopPx],
        // Et le verdict change avec le curseur : huit pixels de paume sont un
        // clic d'usine et un glissement à sensibilité double.
        verdicts:[verdict(factory,8),verdict(loud,8),verdict(quiet,30)],
        // Le moteur et le fichier disent la même chose, et c'est vérifiable.
        agree:BAREHANDS.settings().sensitivity===C.SETTINGS_BOUNDS.sensitivity.min
          &&BAREHANDS.engine().sleepTimeoutMs===BAREHANDS.settings().sleepTimeoutMs,
        // Aucune de ces écritures n'a été refusée.
        banner:/refusé/.test(document.getElementById('barehandsStatus').innerHTML),
      });
    """, name="obeys")
    assert result["factory"] == [30000, 12, 26], "sans réglage, le moteur garde ses défauts"
    assert (result["short"], result["long"]) == (5000, 120000)
    # Le nombre écrit à l'écran endort vraiment une session, au temps demandé.
    assert result["shortAtFour"] == "active" and result["shortAtFive"] == "sleep"
    assert result["longAtThirtyOne"] == "active", "le réglage long tient là où l'usine aurait lâché"
    assert result["loud"] == [6, 13], "les deux tolérances, divisées par le même facteur"
    assert result["quiet"] == [48, 104]
    assert result["verdicts"] == ["click", "drag", "click"]
    assert result["agree"] is True
    assert result["banner"] is False


def test_no_slider_position_the_screen_offers_is_refused_by_the_engine(tmp_path):
    """Le balayage, **par l'écran** cette fois. Le contrat sait déjà qu'aucune
    valeur légale ne construit une paire dangereuse ; ce que ce test ajoute est
    que le chemin qui va du curseur au moteur préserve cette propriété.

    C'est la mesure exacte du coût du mutant « ne diviser qu'une tolérance » :
    il transforme le tiers inférieur du curseur de sensibilité — sa position
    minimale comprise — en « Réglage refusé » sur une position que l'écran
    lui-même propose."""

    result = run_node(tmp_path, BROWSER + """
      await openTab();
      const sweep=async key=>{
        const b=C.SETTINGS_BOUNDS[key];
        const seen=[];
        for(let i=0;b.min+i*b.step<=b.max+1e-9;i+=1){
          const value=Number((b.min+i*b.step).toFixed(6));
          const range=byAttr('data-barehands-range',key);
          range.value=String(value);range.fire('change');
          await settle();
          const engine=BAREHANDS.engine();
          seen.push({value,
            refused:/Réglage refusé/.test(document.getElementById('barehandsStatus').innerHTML),
            saved:BAREHANDS.settings()[key],
            ordered:engine.clickSlopPx<=engine.dragSlopPx});
        }
        return seen;
      };
      const report=async key=>{
        const seen=await sweep(key);
        return {count:seen.length,
          refused:seen.filter(s=>s.refused).map(s=>s.value),
          missed:seen.filter(s=>s.saved!==s.value).map(s=>s.value),
          disordered:seen.filter(s=>!s.ordered).map(s=>s.value)};
      };
      const sensitivity=await report('sensitivity');
      const assistance=await report('assistance');
      const sleep=await report('sleepTimeoutMs');
      out({sensitivity,assistance,sleep,
        writes:server.calls.filter(c=>c.body).length});
    """, name="sweep")
    for key in ("sensitivity", "assistance", "sleep"):
        assert result[key]["refused"] == [], f"{key} : une position offerte et refusée"
        assert result[key]["missed"] == [], f"{key} : une position offerte et non appliquée"
        assert result[key]["disordered"] == [], f"{key} : clickSlopPx passé au-dessus de dragSlopPx"
    assert result["sensitivity"]["count"] == 76
    assert result["assistance"]["count"] == 21
    assert result["sleep"]["count"] == 120
    # Chaque position a vraiment voyagé : aucune écriture avalée en route.
    assert result["writes"] == 76 + 21 + 120


def test_the_diagnostics_box_adds_and_removes_the_readout_from_the_tree(tmp_path):
    """**Décision 24, prise par le bon bout.** Le test précédent appelait
    `overlay.showDiagnostics(true)` : il prouvait que la surimpression sait
    dessiner une lecture, pas que la case la commande. Supprimer la ligne de
    câblage laissait passer les deux.

    Ici, on coche la case de l'onglet et on regarde l'arbre."""

    result = run_node(tmp_path, BROWSER + """
      await openTab();
      const overlay=BAREHANDS.adapters.overlay;
      overlay.mount();
      const root=document.body.children[document.body.children.length-1];
      const diag=()=>root.children.filter(c=>c.className===C.DOM.diagClass).length;
      const token=id=>({id,x:10,y:20,progress:0,state:'open',click:false,hover:false,
        quality:.9,speedPxPerSec:42,stillness:.8});
      const check=async(key,value)=>{
        const box=byAttr('data-barehands-check',key);
        box.checked=value;box.fire('change');
        await settle();
      };
      overlay.render([token(0)]);
      const before=diag();
      await check('diagnostics',true);
      overlay.render([token(0)]);
      const on=diag();
      const line=root.children.find(c=>c.className===C.DOM.diagClass).textContent;
      await check('diagnostics',false);
      overlay.render([token(0)]);
      const off=diag();
      out({before,on,off,line,
        // Et ce que le serveur a reçu, pour que « à l'écran » et « enregistré »
        // ne puissent pas se séparer en silence.
        wire:server.calls.filter(c=>c.body).map(c=>c.body.diagnostics)});
    """, name="diagbox")
    assert result["before"] == 0, "éteinte par défaut, la lecture est absente de l'arbre"
    assert result["on"] == 1, "cocher la case la fait paraître"
    assert "q 0.90" in result["line"] and "42 px/s" in result["line"]
    assert result["off"] == 0, "la décocher la retire"
    assert result["wire"] == [True, False]


def test_the_aiming_assistance_written_on_the_screen_widens_what_the_hand_reaches(tmp_path):
    """`assistance` est le réglage dont la suppression du câblage était la plus
    invisible : le moteur garde alors 0,5, qui est **le défaut**, donc tout ce
    qui ne déplace pas explicitement le curseur continue de marcher.

    Ce que le réglage change vraiment est la portée hors du cadre : à quelle
    distance une visée approximative attrape quand même. On la mesure sur une
    vraie cible, avec un vrai résolveur, en poussant le curseur de l'onglet."""

    result = run_node(tmp_path, BROWSER + """
      await openTab();
      const interaction=BAREHANDS.adapters.interaction;
      /* Un bouton à 40 px du jeton : hors de portée au réglage d'usine
         (24 px), dedans à l'assistance maximale (48 px). */
      const target=node({sel:['button'],rect:{left:100,top:100,width:80,height:30},
        dataset:{},label:'Allumer'});
      global.page=[target];
      const aim=()=>{
        interaction.readContacts(()=>[{handTrackId:1,channel:'primary',state:'pinching',
          intent:'undecided',ratio:.3,confidence:1}]);
        interaction.hover([{id:1,x:60,y:115,progress:0,state:'open',click:false,
          hover:false,quality:1}]);
        return BAREHANDS.targets().length;
      };
      const slide=async value=>{
        const range=byAttr('data-barehands-range','assistance');
        range.value=String(value);range.fire('change');
        await settle();
        return aim();
      };
      const factory=aim();
      const none=await slide(0);
      const full=await slide(1);
      const shown=live.find(n=>n.attrs['data-barehands-value']==='assistance').textContent;
      const back=await slide(.5);
      out({factory,none,full,back,shown,
        });
    """, name="assist")
    assert result["factory"] == 0, "à 0,5, quarante pixels sont hors de portée"
    assert result["none"] == 0, "assistance coupée : rien n'est rattrapé"
    assert result["full"] == 1, "assistance maximale : la visée approximative attrape"
    assert result["back"] == 0, "et revenir au défaut rend sa portée d'usine"
    assert "48" in result["shown"], "le chiffre affiché est la portée réelle"


def test_the_tool_chosen_on_the_palette_decides_what_a_grab_means(tmp_path):
    """L'outil, par le comportement et non par le relecteur : `pan` sur ce qui
    ne défile pas est **refusé**, donc aucune capture ne s'ouvre, là où le
    pointeur contextuel en ouvre une. Relire `interaction.tool()` prouvait que
    la page a posé une valeur ; ceci prouve que le moteur de captures l'applique."""

    result = run_node(tmp_path, BROWSER + """
      await openTab();
      const interaction=BAREHANDS.adapters.interaction;
      const target=node({sel:['button'],rect:{left:200,top:100,width:120,height:40},
        dataset:{},label:'Bouton'});
      global.page=[target];
      const token=(x,y,px)=>({id:1,x,y,palmX:px===undefined?x:px,palmY:y,
        progress:0,state:'pressed',click:false,hover:false,quality:1});
      const contact=intent=>({handTrackId:1,channel:'primary',state:'pressed',
        intent:intent||'undecided',ratio:.3,confidence:1});
      const shot=(now,tokens,contacts,events)=>{global.clock=now;
        interaction.readContacts(()=>contacts||[]);
        interaction.readPinch(()=>events||[]);
        interaction.hover(tokens);};
      /* Une prise de corps complète, du contact au relâchement. */
      const grab=base=>{
        shot(base,[token(260,120)],[contact()],
          [{handTrackId:1,channel:'primary',phase:'down',x:260,y:120}]);
        const held=interaction.captures().length;
        shot(base+16,[token(260,120,320)],[contact('drag')],[]);
        shot(base+32,[token(260,120,320)],[],
          [{handTrackId:1,channel:'primary',phase:'up',x:260,y:120}]);
        shot(base+48,[],[],[]);
        return held;
      };
      const pick=async tool=>{
        byAttr('data-barehands-tool',tool).fire('click');
        await settle();
      };
      const contextual=grab(0);
      await pick('pan');
      const panned=grab(1000);
      await pick('pointer');
      const again=grab(2000);
      out({contextual,panned,again,
        engine:BAREHANDS.adapters.interaction.tool(),
        wire:server.calls.filter(c=>c.body).map(c=>c.body.tool)});
    """, name="palette")
    assert result["contextual"] == 1, "le pointeur ouvre la prise sur un bouton"
    assert result["panned"] == 0, "`pan` sur ce qui ne défile pas est refusé, pas ignoré"
    assert result["again"] == 1, "et revenir au pointeur la rouvre"
    assert result["engine"] == "pointer"
    assert result["wire"] == ["pan", "pointer"]


def test_a_write_the_server_refuses_gives_the_engine_its_previous_numbers_back(tmp_path):
    """Le contrat de la Slice 07 dit qu'un échec d'écriture rend l'ancienne
    valeur au moteur **et** à l'écran. Il était vérifié sur l'aperçu de cible,
    qui se relit par une porte ; le mutant qui supprimait `applyToEngine(previous)`
    du chemin d'échec réseau survivait donc. Ici, ce sont les nombres que le
    moteur applique qu'on relit — et le refus de schéma, lui, n'atteint jamais
    le moteur."""

    result = run_node(tmp_path, BROWSER + """
      await openTab();
      const range=byAttr('data-barehands-range','sensitivity');
      range.value='2';range.fire('change');
      await settle();
      const saved=BAREHANDS.engine();
      server.fail='réglages indisponibles';
      const next=byAttr('data-barehands-range','sensitivity');
      next.value='4';next.fire('change');
      await settle();
      const after=BAREHANDS.engine();
      out({
        saved:[saved.clickSlopPx,saved.dragSlopPx],
        after:[after.clickSlopPx,after.dragSlopPx],
        settings:BAREHANDS.settings().sensitivity,
        said:/Réglage non enregistré/.test(document.getElementById('barehandsStatus').innerHTML),
        // Et le curseur revient à la position que le moteur applique : un
        // curseur qui reste à 4 pendant que la main obéit à 2 ferait deux
        // réponses à l'écran pour un seul réglage.
        slider:byAttr('data-barehands-range','sensitivity').value,
      });
    """, name="revert")
    assert result["saved"] == [6, 13]
    assert result["after"] == [6, 13], "le moteur reprend les nombres de la valeur enregistrée"
    assert result["settings"] == 2
    assert result["said"] is True
    assert result["slider"] == "2"


def test_switching_the_preview_off_on_the_screen_stops_the_drawing_not_the_resolution(tmp_path):
    """**Décision 24, par l'arbre.** La case ne coupe pas la résolution de
    cible : elle coupe le **dessin**. Les deux se distinguent en regardant ce
    que la surimpression contient pendant que `targets()` continue de répondre
    — et c'est la seule forme qu'un mutant qui supprime le câblage ne peut pas
    imiter."""

    result = run_node(tmp_path, BROWSER + """
      await openTab();
      const interaction=BAREHANDS.adapters.interaction;
      BAREHANDS.adapters.overlay.mount();
      const drawn=()=>document.body.children.reduce((n,c)=>
        n+c.children.filter(k=>k.className===C.DOM.targetClass).length,0);
      const target=node({sel:['button'],rect:{left:100,top:100,width:80,height:30},
        dataset:{},label:'Allumer'});
      global.page=[target];
      const aim=()=>{
        interaction.readContacts(()=>[{handTrackId:1,channel:'primary',state:'pinching',
          intent:'undecided',ratio:.3,confidence:1}]);
        interaction.hover([{id:1,x:140,y:115,progress:0,state:'open',click:false,
          hover:false,quality:1}]);
        return [BAREHANDS.targets().length,drawn()];
      };
      const on=aim();
      const box=byAttr('data-barehands-check','targetPreview');
      box.checked=false;box.fire('change');
      await settle();
      // Le dessin part **tout de suite**, sans attendre l'image suivante.
      const atOnce=drawn();
      const off=aim();
      const back=byAttr('data-barehands-check','targetPreview');
      back.checked=true;back.fire('change');
      await settle();
      const again=aim();
      out({on,atOnce,off,again});
    """, name="preview")
    assert result["on"] == [1, 1], "aperçu allumé : la cible est résolue et dessinée"
    assert result["atOnce"] == 0, "décocher retire le dessin sans attendre l'image suivante"
    assert result["off"] == [1, 0], "aperçu éteint : la cible est toujours résolue, rien n'est dessiné"
    assert result["again"] == [1, 1]


# --------------------------------------------------- ce qu'un refus doit dire


def test_an_unknown_tool_is_refused_and_never_normalised_into_the_pointer(tmp_path):
    """**R2.** `normalizeTool` retombe sur « pointeur » pour tout nom inconnu :
    c'est sa tolérance documentée, et elle est juste pour **relire un schéma
    stocké**. Sur le chemin d'**écriture**, elle produisait le pire silence de
    la Slice : `tool('ciseaux')` changeait l'outil pour Pointeur, envoyait au
    serveur la valeur déjà normalisée — donc son refus `barehands_tool_unknown`
    était inatteignable depuis la page —, ne montrait ni bandeau ni toast, et
    journalisait « réglage enregistré ».

    C'est la porte que le canal de commandes de la voix (Slice 12) emprunte :
    un nom mal transcrit repartait en « j'ai bien changé d'outil »."""

    result = run_node(tmp_path, BROWSER + """
      await openTab();
      byAttr('data-barehands-tool','select').fire('click');
      await settle();
      const writes=()=>server.calls.filter(c=>c.body).length;
      const before=writes();
      const refused=await BAREHANDS.tool('ciseaux');
      const after=writes();
      const banner=document.getElementById('barehandsStatus').innerHTML;
      const said=toasts.slice();
      /* `highlighter` a quitté la table avec la couche d'annotation : il se
         refuse désormais **ici**, comme n'importe quel nom inconnu, et ne part
         plus sur le fil. La porte du serveur reste, pour l'outil qu'une Slice
         future déclarerait sans le servir. */
      const retired=await BAREHANDS.tool('highlighter');
      const retiredBanner=document.getElementById('barehandsStatus').innerHTML;
      out({
        refused,retired,retiredBanner,
        wrote:after-before,
        sentToServer:server.calls.filter(c=>c.body).map(c=>c.body.tool),
        // L'outil n'a pas bougé, ni à l'écran ni dans le moteur.
        tool:BAREHANDS.settings().tool,
        engineTool:BAREHANDS.adapters.interaction.tool(),
        // Vu : le nom exact, qui est la seule information de cette ligne.
        banner,said,
        // Journalisé : avec son code, jamais « enregistré ».
        warned:logged.filter(l=>l[0]==='warn').map(l=>l[1]),
        saved:logged.filter(l=>l[0]==='info'&&/enregistré/.test(l[1])).length,
      });
    """, name="unknowntool")
    assert result["refused"] is None, "un outil inconnu ne rend pas des réglages"
    assert result["wrote"] == 0, "et ne part jamais sur le fil, fût-il normalisé"
    assert result["tool"] == "select" and result["engineTool"] == "select", (
        "ni l'écran ni le moteur ne retombent sur le pointeur"
    )
    assert "Outil Bare Hands inconnu" in result["banner"]
    assert "ciseaux" in result["banner"], "le nom refusé est dans la phrase"
    assert result["said"][-1] == "bad"
    assert any("barehands_tool_unknown" in line for line in result["warned"])
    # Une écriture réussie par outil installé, et aucune pour le refus.
    assert result["saved"] == 1, "seule l'écriture acceptée est journalisée"
    # Un nom retiré de la table se refuse comme un nom inconnu, et ne part pas
    # sur le fil : `select` reste le dernier outil écrit.
    assert result["retired"] is None
    assert result["sentToServer"][-1] == "select"
    assert "highlighter" in result["retiredBanner"], "le nom retiré est dans la phrase"


def test_a_switch_off_the_server_refuses_leaves_the_screen_saying_what_the_camera_did(tmp_path):
    """**R3.** `enabled` est le seul réglage dont l'état moteur ne passe pas par
    `applyToEngine` : décocher libère la caméra **avant** l'écriture, exprès.
    L'échec rendait alors « l'ancienne valeur » à l'écran, donc recochait la
    case — pendant que la caméra, elle, restait éteinte. Case cochée, serveur
    allumé, caméra éteinte : il fallait basculer deux fois pour en sortir.

    On ne rallume pas : rouvrir la caméra parce qu'un **enregistrement** a
    échoué ferait faire à la machine ce que personne n'a demandé. L'écran suit
    donc le moteur, et ce qui reste divergent — le serveur — est nommé."""

    result = run_node(tmp_path, CAMERA + BROWSER + """
      await openTab();
      /* Allumer pour de bon : le contrôleur part, et la lecture qui ne revient
         pas le laisse en `starting`, c'est-à-dire engagé — la caméra est
         demandée, il y a donc quelque chose à libérer. */
      server.hangGet=true;
      const toggle=document.getElementById('f_barehands');
      toggle.checked=true;toggle.fire('change');
      await settle();
      const started=BAREHANDS.state().controller;
      // Puis le serveur tombe, et l'utilisateur décoche.
      server.fail='réglages indisponibles';
      toasts.length=0;
      const box=document.getElementById('f_barehands');
      box.checked=false;box.fire('change');
      await settle();
      out({started,
        controller:BAREHANDS.state().controller,
        checkbox:document.getElementById('f_barehands').checked,
        enabled:BAREHANDS.state().enabled,
        // Le serveur, lui, n'a pas changé d'avis : c'est la divergence qui
        // reste, et c'est celle que l'écran doit nommer.
        serverStillEnabled:server.state.enabled,
        banner:document.getElementById('barehandsStatus').innerHTML,
        toasts,
        warned:logged.filter(l=>l[0]==='warn').length,
      });
    """, name="offrefused")
    assert result["started"] == "starting", "la caméra a bien été demandée"
    assert result["controller"] == "off", "décocher libère la caméra sans attendre le réseau"
    assert result["serverStillEnabled"] is True, "et le serveur, lui, n'a rien enregistré"
    # L'écran suit le moteur : la case dit ce que la caméra fait.
    assert result["checkbox"] is False, "la case ne se recoche pas sur une caméra éteinte"
    assert result["enabled"] is False
    # Et la divergence qui reste est écrite en toutes lettres.
    assert "Réglage non enregistré" in result["banner"]
    assert "caméra a bien été libérée" in result["banner"]
    assert "prochain chargement" in result["banner"]
    # Trois phrases pour trois faits, et aucune n'est la répétition d'une
    # autre : le cycle de vie annonce l'extinction (toast déjà en place), puis
    # l'échec d'écriture dit sa cause, puis la divergence qui reste dit ce que
    # l'utilisateur retrouvera au prochain chargement. La dernière est la
    # seule qui n'avait aucun canal : le panneau peut être fermé (la voix de
    # la Slice 12 passe par la même porte), et le bandeau n'est alors lu par
    # personne.
    assert result["toasts"] == ["warn", "bad", "warn"], result["toasts"]
    assert result["warned"] >= 1


def test_a_write_dropped_because_another_is_in_flight_says_so(tmp_path):
    """**R4.** `if(view.busy)return null` rendait `null` — le même `null` qu'un
    refus — sans un mot nulle part. Les contrôles de l'écran sont désarmés
    pendant l'attente, donc seul un appelant **sans écran** peut y arriver :
    la voix (Slice 12) et la console, c'est-à-dire exactement celui à qui un
    abandon muet ne laisse rien à lire."""

    result = run_node(tmp_path, BROWSER + """
      await openTab();
      let release;
      server.gate=new Promise(r=>{release=r});
      const first=BAREHANDS.settings({assistance:.25});
      const dropped=await BAREHANDS.settings({assistance:.75});
      const banner=document.getElementById('barehandsStatus').innerHTML;
      release();server.gate=null;
      await first;
      await settle();
      out({dropped,banner,toasts,
        // Une seule écriture est partie, et c'est la première.
        writes:server.calls.filter(c=>c.body).map(c=>c.body.assistance),
        settings:BAREHANDS.settings().assistance,
        warned:logged.filter(l=>l[0]==='warn').map(l=>l[1]),
        // Et le bandeau ne reste pas : l'écriture qui a abouti le remplace.
        after:document.getElementById('barehandsStatus').innerHTML,
      });
    """, name="busy")
    assert result["dropped"] is None
    assert result["writes"] == [0.25], "la seconde écriture est perdue — mais plus en silence"
    assert result["settings"] == 0.25
    assert "déjà en cours" in result["banner"]
    assert result["toasts"] == ["warn"]
    assert any("écriture en cours" in line for line in result["warned"])
    assert "déjà en cours" not in result["after"], "le bandeau part avec la cause"


def test_refreshing_the_panel_never_rewrites_the_body_of_the_tab(tmp_path):
    """**Constat F5, par le comportement.** L'ordre d'insertion des modules est
    vérifié sur la source servie ; ce qu'aucune lecture de source ne peut voir,
    c'est une évolution où `refreshPanel()` se mettrait à réécrire
    `modalContent.innerHTML` — ce qui emporterait la section Scène que
    `control_center_scene_settings` place en tête du même onglet.

    Le mécanisme tient à une propriété vérifiable ici : le corps de l'onglet
    n'est écrit qu'au dessin de l'onglet, jamais par un rafraîchissement. Tout
    ce que la Slice 07 fait vivre — écriture, refus, échec réseau, bascule
    d'outil, cycle de vie — passe par `refreshPanel()` et ne doit pas
    l'incrémenter. (La vérification des deux modules dans un seul DOM reste
    une vérification d'exécution : ce double n'a pas `prepend`.)"""

    result = run_node(tmp_path, BROWSER + """
      await openTab();
      const written=()=>modalContent.htmlWrites;
      const atPaint=written();
      // Une écriture qui réussit.
      byAttr('data-barehands-tool','pan').fire('click');
      await settle();
      const afterTool=written();
      // Un curseur, une case, l'interrupteur.
      const range=byAttr('data-barehands-range','assistance');
      range.value='0.75';range.fire('change');
      await settle();
      const box=byAttr('data-barehands-check','diagnostics');
      box.checked=true;box.fire('change');
      await settle();
      const toggle=document.getElementById('f_barehands');
      toggle.checked=true;toggle.fire('change');
      await settle();
      // Un refus de contrat, puis un échec réseau.
      await BAREHANDS.tool('ciseaux');
      server.fail='réglages indisponibles';
      const last=byAttr('data-barehands-range','assistance');
      last.value='0.25';last.fire('change');
      await settle();
      const afterAll=written();
      // Et un second dessin d'onglet, lui, réécrit bien le corps.
      await renderTab();await settle();
      out({atPaint,afterTool,afterAll,afterRender:written(),
        // Le panneau a pourtant bien été rafraîchi entre-temps.
        refreshed:document.getElementById('barehandsStatus').innerHTML.length>0});
    """, name="f5")
    assert result["atPaint"] == 1, "le corps de l'onglet est écrit une fois, au dessin"
    assert result["afterTool"] == 1
    assert result["afterAll"] == 1, (
        "aucun rafraîchissement ne réécrit le corps de l'onglet : c'est ce qui "
        "laisse vivre la section Scène du module voisin (constat F5)"
    )
    assert result["refreshed"] is True
    assert result["afterRender"] == 2, "redessiner l'onglet, en revanche, le réécrit"


# --------------------------------------------------------- page et vraie route


def test_settings_written_by_a_newer_jarvis_are_named_on_screen_not_silently_replaced(tmp_path):
    """**Constat R6, côté écran.** Le serveur les gardait, l'écran se taisait.

    Un utilisateur revenu en arrière voit ses réglages revenus d'usine sans un
    mot : ni ce qui s'est passé, ni où sont passés les siens. Un retour à
    l'usine indiscernable d'une perte est une perte.
    """

    result = run_node(tmp_path, browser("""
      /* Ce que le serveur rend quand il a lu un bloc qu'il ne sait pas lire :
         les défauts, **et** de quoi le dire. Posé **avant** le chargement de
         la page, parce que c'est ainsi que ça arrive : le bloc étranger est
         déjà dans le fichier quand l'onglet s'ouvre. */
      server.state=Object.assign({},server.state,
        {unreadable:true,stored_schema_version:3,archived:[]});
    """) + """
      await openTab();
      const warned=document.getElementById('barehandsStatus').innerHTML;
      /* Et les réglages appliqués sont bien ceux d'usine : le bandeau dit ce
         que le moteur fait, il ne le décrit pas de travers. */
      const applied=[BAREHANDS.settings().tool,BAREHANDS.settings().sensitivity];
      // Recocher : c'est l'écriture qui aurait détruit le bloc.
      document.getElementById('f_barehands').checked=true;
      document.getElementById('f_barehands').fire('change');
      await settle();
      const after=document.getElementById('barehandsStatus').innerHTML;
      out({warned,applied,after,
        sent:server.calls.filter(c=>c.body).length,
        archived:server.state.archived});
    """, name="foreign")

    # Vu : la version lue, ce que cette version écrit, et ce qui va arriver au
    # bloc — pas « erreur » ni le silence d'avant.
    assert "version plus récente" in result["warned"]
    assert "schéma 3" in result["warned"]
    assert "clé d’archive" in result["warned"], "l'écran dit que rien ne sera écrasé"
    assert result["applied"] == ["pointer", 1], "les valeurs d'usine s'appliquent vraiment"

    # Après l'écriture : plus d'avertissement, et la clé où le bloc est rangé
    # est **nommée**. « Ils ont survécu » sans dire où n'est pas une réponse.
    assert result["sent"] == 1
    assert result["archived"] == ["barehands_test_mode_archived_v3"]
    assert "version plus récente" not in result["after"]
    assert "barehands_test_mode_archived_v3" in result["after"]
    assert "rien n’a été détruit" in result["after"]


def test_a_fresh_tab_says_nothing_about_a_version_it_never_read(tmp_path):
    """L'autre moitié : un bandeau toujours là ne dit rien de plus qu'aucun.

    Un premier lancement rend exactement les mêmes réglages qu'un bloc
    illisible — c'est le fond du constat —, donc le bandeau doit être absent
    ici et présent là, sans quoi il ne distingue rien."""

    result = run_node(tmp_path, BROWSER + """
      await openTab();
      out({status:document.getElementById('barehandsStatus').innerHTML,
        stored:[server.state.unreadable,server.state.stored_schema_version]});
    """, name="freshtab")
    assert result["stored"] == [False, None]
    assert "version plus récente" not in result["status"]
    assert "conservé" not in result["status"]


def test_the_payload_the_page_builds_is_accepted_by_the_real_route(tmp_path):
    """La boucle fermée : la charge utile que `toServerPayload` construit part
    dans le **vrai** gestionnaire de route, est écrite dans le **vrai** fichier
    de réglages, et revient par `GET /api/barehands`.

    C'est ce test qui interdit que les deux moitiés du schéma dérivent : une
    clé renommée d'un côté sort ici en `barehands_unknown_field`."""

    import asyncio

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "payload.cjs"
    script.write_text(
        f"const C=require({json.dumps(str(CONTRACTS))});\n"
        "process.stdout.write(JSON.stringify(C.toServerPayload("
        "{enabled:true,tool:'select',sleepTimeoutMs:45000,assistance:.25,"
        "sensitivity:2,targetPreview:false,diagnostics:true,tutorialSeen:true,"
        "calibrationEnabled:false})));",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8",
                          timeout=30, check=False)
    assert done.returncode == 0, done.stderr
    payload = json.loads(done.stdout)

    class JsonRequest:
        def __init__(self, body): self.body = body
        async def json(self): return self.body

    control = ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path,
                            barehands_vendor_root=tmp_path / "vendor")
    saved = json.loads(asyncio.run(control.save_barehands(JsonRequest(payload))).text)
    assert saved["tool"] == "select" and saved["sleep_timeout_ms"] == 45000
    assert saved["assistance"] == 0.25 and saved["sensitivity"] == 2
    assert saved["target_preview"] is False and saved["diagnostics"] is True
    assert saved["schema_version"] == barehands.SCHEMA_VERSION
    assert saved["installed_tools"] == list(barehands.INSTALLED_TOOLS)

    reread = json.loads(asyncio.run(control.get_barehands(None)).text)
    assert {key: reread[key] for key in barehands.SETTINGS_DEFAULTS} == {
        key: saved[key] for key in barehands.SETTINGS_DEFAULTS
    }

    # Et ce que le contrat relit de la réponse est ce qu'on avait écrit.
    back = tmp_path / "back.cjs"
    back.write_text(
        f"const C=require({json.dumps(str(CONTRACTS))});\n"
        f"const state={json.dumps(reread)};\n"
        "process.stdout.write(JSON.stringify(C.fromServerState(state)));",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(back)], capture_output=True, text=True, encoding="utf-8",
                          timeout=30, check=False)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {
        "schemaVersion": barehands.SCHEMA_VERSION, "enabled": True, "targetPreview": False,
        "sleepTimeoutMs": 45000, "tool": "select", "assistance": 0.25, "sensitivity": 2,
        "tutorialSeen": True, "calibrationEnabled": False, "diagnostics": True,
    }


def test_the_server_double_of_these_tests_carries_every_field_the_real_route_sends(tmp_path):
    """**La leçon des doubles**, appliquée au double de serveur de ce fichier.

    Quatre défauts de réalisme ont déjà coûté cher sur cette tâche. Celui-ci
    serait le cinquième : un double qui ne porte pas `unreadable`,
    `stored_schema_version` ni `archived` ne peut pas tomber comme le vrai
    serveur tombe, et un bandeau qui les lit se testerait contre du vide.
    """

    import asyncio

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    control = ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path,
                            barehands_vendor_root=tmp_path / "vendor")
    real = json.loads(asyncio.run(control.get_barehands(None)).text)

    script = tmp_path / "double.cjs"
    script.write_text(
        f"const C=require({json.dumps(str(CONTRACTS))});\n"
        "const server={state:Object.assign(C.toServerPayload({}),"
        "{stored_schema_version:null,unreadable:false,archived:[]})};\n"
        "process.stdout.write(JSON.stringify(Object.assign({},server.state,"
        "{assets:{installed:true,missing:[]}})));",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8",
                          timeout=30, check=False)
    assert done.returncode == 0, done.stderr
    double = json.loads(done.stdout)

    # `status` et `tools`/`installed_tools` sont les seuls champs que le double
    # n'a jamais portés : la page ne les lit pas. Tout le reste doit coïncider,
    # sinon le double ment sur ce qui arrive à la page.
    missing = set(real) - set(double) - {"status", "tools", "installed_tools"}
    assert missing == set(), f"le double de serveur ne porte pas {sorted(missing)}"
    for key in ("unreadable", "stored_schema_version", "archived"):
        assert double[key] == real[key], key


def test_the_page_serves_the_two_surfaces_and_never_a_dead_control(tmp_path):
    """Le balisage que la page sert vraiment : deux sections nommées, une
    palette d'outils, les sept réglages, et **aucun bouton qui ne ferait
    rien** — la calibration et le tutoriel sont dits en toutes lettres comme
    non installés plutôt que promis par un contrôle inerte."""

    import asyncio

    control = ControlCenter(runtime_root=tmp_path / "runtime", project_root=tmp_path,
                            barehands_vendor_root=tmp_path / "vendor")
    served = asyncio.run(control.index(None)).text

    assert 'id="barehandsTools"' in served and 'id="barehandsSettings"' in served
    assert 'role="radiogroup"' in served
    assert "data-barehands-tool=" in served
    for key in ("targetPreview", "diagnostics", "calibrationEnabled", "tutorialSeen"):
        assert f"checkHtml('{key}'" in served, key
    for key in ("assistance", "sensitivity", "sleepTimeoutMs"):
        assert f"rangeHtml('{key}'" in served, key
    assert "barehandsReset" in served
    # **Slice 08** : la calibration a maintenant un parcours, donc un bouton —
    # et c'est le seul contrôle de cet onglet qui ait cessé d'être une phrase.
    assert 'id="barehandsCalibration"' in served
    assert "barehandsCalibrate" in served and "barehandsProfileReset" in served
    # Le tutoriel, lui, est toujours dit en toutes lettres plutôt que promis
    # par un contrôle inerte (Slice 09).
    assert "Le tutoriel n’est pas encore installé" in served
    assert "aucune image ni vidéo" in served, "la décision 32 est dite à l'utilisateur, pas seulement tenue"
    # Le sous-titre de l'onglet reste celui que `control_center_scene_settings`
    # remplace ensuite : l'ordre d'injection est intact (constat F5).
    assert served.index("TABS.push({id:TAB_ID,label:'Expérimental'") < served.index("function installSection()")


# ------------------------------------------- le profil atteint vraiment la main


def test_a_calibrated_profile_reaches_the_engine_hand_by_hand_and_pixel_by_pixel(tmp_path):
    """**La regle de la Slice 07, appliquee au profil** : un reglage lu sur
    l'objet qu'on vient d'ecrire ne prouve rien ; il faut le lire sur ce que le
    moteur applique. Un profil par main est plus invisible encore, puisque rien
    a l'ecran ne le montre — d'ou `engine().hands`.

    Trois choses a la fois, parce qu'elles se cassent separement : les seuils
    **par main** atteignent le canal qui va bien, la tolerance de deplacement
    **echelle avec la fenetre** (c'est le reglement du residu de la Slice 04),
    et une demi-hysteresis est **ignoree** plutot que composee avec un defaut
    du moteur — ce qui produirait la paire que `options()` refuse.
    """

    result = run_node(tmp_path, browser("""
      server.profile={...server.profile,
        hands:{
          left:{press_ratio:.18,release_ratio:.5,
                secondary_press_ratio:.22,secondary_release_ratio:.55,
                travel_slop_norm:.02},
          /* La main droite n'a qu'une **moitie** d'hysteresis : mesuree seule,
             elle formerait avec le defaut du moteur une paire que le moteur
             refuse a la construction. */
          right:{press_ratio:.6},
          unknown:{}},
        stages:{}};
    """) + """
      await openTab();
      const engine=BAREHANDS.engine();
      const before=[engine.clickSlopPx,engine.dragSlopPx];
      out({
        left:engine.hands.left,right:engine.hands.right,unknown:engine.hands.unknown,
        defaults:[C.normalizeSettings().sensitivity,
          BAREHANDS.core.DEFAULTS.pressRatio,BAREHANDS.core.DEFAULTS.releaseRatio,
          BAREHANDS.core.DEFAULTS.clickSlopPx,BAREHANDS.core.DEFAULTS.dragSlopPx],
        width:window.innerWidth,
        slop:before,
        travel:BAREHANDS.calibration().travel,
        profileCalibrated:BAREHANDS.profile().calibrated,
      });
    """, name="profileengine")

    sensitivity, press, release, click_px, drag_px = result["defaults"]
    # La main gauche applique **ses** mesures, sur les deux canaux.
    assert result["left"]["primary"] == {"pressRatio": 0.18, "releaseRatio": 0.5}
    assert result["left"]["secondary"] == {"pressRatio": 0.22, "releaseRatio": 0.55}
    # La main droite n'a qu'une moitie : le moteur garde ses deux defauts.
    assert result["right"]["primary"] == {"pressRatio": press, "releaseRatio": release}
    assert result["unknown"]["primary"] == {"pressRatio": press, "releaseRatio": release}
    # La tolerance **echelle avec la fenetre** : c'est ce qui fait qu'un meme
    # geste vaut le meme nombre de pixels a toutes les resolutions.
    assert result["width"] == 1000
    assert result["slop"][0] == pytest.approx(0.02 * 1000 / sensitivity)
    # Le rapport d'usine entre les deux tolerances est conserve, donc
    # l'invariant `clickSlopPx <= dragSlopPx` traverse intact.
    assert result["slop"][1] == pytest.approx(result["slop"][0] * drag_px / click_px)
    assert result["slop"][0] <= result["slop"][1]
    assert result["travel"]["calibrated"] is True
    assert result["profileCalibrated"] is True


def test_without_a_profile_the_engine_keeps_exactly_its_factory_thresholds(tmp_path):
    """L'autre moitie : sans mesure, rien ne bouge. Sans ce test, « le profil
    est applique » serait aussi vrai d'un moteur qui applique n'importe quoi."""

    result = run_node(tmp_path, BROWSER + """
      await openTab();
      const engine=BAREHANDS.engine();
      out({hands:engine.hands,slop:[engine.clickSlopPx,engine.dragSlopPx],
        defaults:[BAREHANDS.core.DEFAULTS.pressRatio,BAREHANDS.core.DEFAULTS.releaseRatio,
          BAREHANDS.core.DEFAULTS.clickSlopPx,BAREHANDS.core.DEFAULTS.dragSlopPx],
        calibrated:BAREHANDS.profile().calibrated,
        travel:BAREHANDS.calibration().travel});
    """, name="noprofile")
    press, release, click_px, drag_px = result["defaults"]
    for handedness in ("left", "right", "unknown"):
        for channel in ("primary", "secondary"):
            assert result["hands"][handedness][channel] == {
                "pressRatio": press, "releaseRatio": release}, (handedness, channel)
    assert result["slop"] == [click_px, drag_px]
    assert result["calibrated"] is False and result["travel"]["calibrated"] is False


def test_calibration_switched_off_refuses_the_flow_and_says_so_on_screen(tmp_path):
    """**Decision 27**, et le contrat § 12. `calibrationEnabled` etait persiste
    et decoratif depuis la Slice 07 ; il commande maintenant une porte. Le refus
    doit etre un **non** (`ok` faux), sans quoi le canal annoncerait a
    l'utilisateur un parcours qui n'a pas demarre."""

    result = run_node(tmp_path, BROWSER + """
      await openTab();
      byAttr('data-barehands-check','calibrationEnabled').checked=false;
      byAttr('data-barehands-check','calibrationEnabled').fire('change');
      await settle();
      const answer=await BAREHANDS.calibrate();
      out({answer,said:toasts.slice(-1)[0],
        banner:document.getElementById('barehandsStatus').innerHTML,
        warned:logged.filter(l=>l[0]==='warn').map(l=>l[1]).slice(-1)[0],
        // Aucune coque ne s'est ouverte.
        shell:document.body.children.filter(n=>n.id==='jarvisFlow').length,
        running:BAREHANDS.calibration().running});
    """, name="calibdisabled")
    assert result["answer"]["ok"] is False, (
        "un refus doit etre un non : `{ok:true}` ferait annoncer un parcours qui n'a pas demarre"
    )
    assert result["answer"]["code"] == "barehands_calibration_disabled"
    assert result["shell"] == 0 and result["running"] is False
    assert "desactivee" in result["said"] or result["said"] == "warn"
    assert "Proposer la calibration" in result["banner"]
    assert result["warned"] is not None
