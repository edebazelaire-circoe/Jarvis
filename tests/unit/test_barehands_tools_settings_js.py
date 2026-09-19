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
SCENE_INTERACT = RUNTIME / "control_center_scene_interact.js"


def run_node(tmp_path: Path, source: str, name: str = "tools") -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"barehands-{name}.cjs"
    script.write_text(
        f"const SCRIPT_PATH={json.dumps(str(SCRIPT))};\n"
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
const bodyRun=(tool,kind,scrollable,extra)=>{
  const dom=makeDom(scrollable?[kind]:[]);
  const e=engineOf({dom:dom.api,slotOf:()=>0});
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

    Le réglage le refuse et la palette le grise, mais ce moteur est
    **injectable** : il ne suppose pas que son appelant a filtré (même raison
    que `target_not_actionable`, Slice 06). Il refuse donc partout — corps
    **et** zone —, parce qu'un outil indisponible n'a pas de cible privilégiée.
    """

    result = run_node(tmp_path, FIXTURE + """
      const zoneRun=tool=>{
        const e=engineOf({dom:makeDom([]).api,world:makeWorld({A:{box:{x:0,y:0,w:64,h:40},
          representation:'window'}}),slotOf:()=>0});
        if(tool)e.setTool(tool);
        const s=e.update({now:0,tokens:[tok(1,400,300)],
          targets:[tgt(1,'A','edge','right')],events:[ev(1,'down',400,300)],
          contacts:[held(1,'undecided')]});
        return {refusals:s.refusals.map(r=>r.reason),captures:s.captures.length};
      };
      out({
        body:bodyRun('highlighter','button',false),
        draw:bodyRun('draw','card',true),
        zone:zoneRun('highlighter'),
        zoneWithPointer:zoneRun('pointer'),
        unknown:refused(()=>engineOf({}).setTool('gomme')),
        // Une palette et un moteur qui ne s'accordent pas sur « installé »
        // donneraient un outil choisissable et sans effet.
        installed:C.INSTALLED_TOOLS,
      });
    """)
    assert result["body"]["dom"] == [] and result["body"]["refusals"] == ["tool_not_installed"]
    assert result["draw"]["dom"] == [] and result["draw"]["refusals"] == ["tool_not_installed"]
    assert result["zone"] == {"refusals": ["tool_not_installed"], "captures": 0}
    assert result["zoneWithPointer"] == {"refusals": [], "captures": 1}
    assert result["unknown"] == "barehands_tool_unknown"
    assert result["installed"] == list(barehands.INSTALLED_TOOLS)


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
BROWSER = r"""
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
    set innerHTML(html){this._html=html;
      if(this.registers){live.length=0;for(const n of parse(html))live.push(n)}},
    get innerHTML(){return this._html},
  };
};
const modalContent=makeNode('div',{id:'modalContent'});
modalContent.registers=true;
const fixed={modalContent,modalSave:makeNode('div',{id:'modalSave'}),
  modalSub:makeNode('div',{id:'modalSub'})};
global.window={addEventListener(){},innerWidth:1000,innerHeight:800};
global.document={createElement:tag=>makeNode(tag,{},''),
  head:makeNode('head',{},''),body:makeNode('body',{},''),
  activeElement:null,
  getElementById:id=>fixed[id]||live.find(n=>n.id===id)||null,
  querySelector:sel=>(global.document.querySelectorAll(sel)[0]||null),
  querySelectorAll:sel=>{
    const m=/^\[([-\w]+)(?:="([^"]*)")?\]$/.exec(sel);
    if(!m)return [];
    return live.filter(n=>n.attrs[m[1]]!==undefined&&(m[2]===undefined||n.attrs[m[1]]===m[2]));
  },
  elementFromPoint:()=>null};
global.navigator={mediaDevices:null};
global.performance={now:()=>0};
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
global.JarvisSceneInteract=require(SCENE_INTERACT_PATH);

/* Le serveur : la **même** forme que la vraie route — il range ce qu'on lui
   envoie et le rend à plat. Ce qui lie ce double au vrai gestionnaire est un
   test de parité à part
   (`test_the_payload_the_page_builds_is_accepted_by_the_real_route`). */
const server={state:C.toServerPayload({}),calls:[],fail:null};
global.api=async(path,opts)=>{
  server.calls.push({path,body:opts&&opts.body?JSON.parse(opts.body):null});
  if(!opts||opts.method!=='POST')
    return Object.assign({},server.state,{assets:{installed:true,missing:[]}});
  if(server.fail)throw Object.assign(new Error(server.fail),{status:400});
  server.state=Object.assign({},server.state,JSON.parse(opts.body));
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

delete require.cache[require.resolve(SCRIPT_PATH)];
require(SCRIPT_PATH);
const BAREHANDS=window.JarvisBarehands;
const settle=async()=>{for(let i=0;i<12;i+=1)await new Promise(r=>setImmediate(r))};
const openTab=async()=>{await settle();await renderTab();await settle()};
const byAttr=(name,value)=>live.find(n=>n.attrs[name]===value)||null;
"""


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
    assert result["logged"] == 4, "chaque ecriture reussie laisse une ligne"
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
         palette et sautent les outils sans moteur — s'arrêter sur l'un d'eux
         serait un cul-de-sac que la souris ne rencontre jamais. */
      /* Tel que la page l'a **écrit**, avant tout rafraîchissement. */
      const firstPaint=(modalContent.innerHTML.match(/<button[^>]*data-barehands-tool[^>]*>/g)||[])
        .filter(tag=>/tabindex="0"/.test(tag))
        .map(tag=>(tag.match(/data-barehands-tool="([^"]+)"/)||[])[1]);
      const focusable=()=>live.filter(n=>n.attrs['data-barehands-tool'])
        .map(n=>[n.attrs['data-barehands-tool'],n.attrs.tabindex,n.disabled]);
      const stops=focusable();
      /* `pan` est suivi de `highlighter` dans la palette, et `highlighter` n'a
         pas de moteur : c'est la seule paire qui distingue « la flèche saute
         ce qui est désarmé » de « la flèche avance d'un rang ». */
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
    # parcours, et les deux sans moteur sont désarmés.
    assert [row[1] for row in result["stops"]] == ["-1", "-1", "-1", "-1", "0"], result["stops"]
    assert [row[0] for row in result["stops"] if row[2]] == ["highlighter", "draw"]
    # La flèche saute les deux outils désarmés au lieu de s'y arrêter : un
    # cul-de-sac au clavier que la souris ne rencontre jamais, puisqu'elle voit
    # tout de suite qu'ils sont grisés.
    assert result["skipped"] == "select", "la flèche saute `highlighter`"
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


# --------------------------------------------------------- page et vraie route


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
    assert "les parcours ne sont pas encore installés" in served
    # Le sous-titre de l'onglet reste celui que `control_center_scene_settings`
    # remplace ensuite : l'ordre d'injection est intact (constat F5).
    assert served.index("TABS.push({id:TAB_ID,label:'Expérimental'") < served.index("function installSection()")
