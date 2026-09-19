"""Calibration Bare Hands : dérivation, coque de parcours, machine d'étapes.

Slice 08, architecture §10 et §11, décisions 26 à 32. Exécuté par node : les
contrats, le moteur et le module de calibration sont les **vrais** ; seuls le
DOM et l'horloge sont des doubles, parce que node n'en a pas.

Ce que ce fichier épingle :

- **la dérivation refuse plutôt qu'elle n'invente** : trop peu d'échantillons,
  repos et pincement inséparables, portée plate, clic et glissement qui se
  ressemblent — chacun a son motif, et aucun ne rend un nombre ;
- **le tremblement se lit sur brut↔filtré**, jamais sur le `x`/`y` du jeton,
  qui se fige sur l'ancre pendant un pincement et ne dit alors plus rien de la
  main ;
- **la coque est une coque** : elle ne sait rien de la calibration, elle tient
  la RÈGLE ZÉRO (ce qui tourne, quoi, depuis combien de temps, comment sortir)
  et elle épargne la surimpression des mains de son balayage `inert` — on
  calibre *avec ses mains* ;
- **la décision 31 par étape** : une étape ratée laisse ses clés nulles, donc le
  moteur garde ses défauts, et le profil dit laquelle ;
- **la décision 32 en structure** : ce qui traverse la couture du contrôleur est
  un enregistrement de scalaires, mesuré sur la **vraie** géométrie de main à
  travers le **vrai** traqueur — pas un tableau de valeurs écrites à la main.

Le double de DOM de ce fichier est écrit pour pouvoir **échouer comme le vrai**
(leçon des quatre défauts de réalisme de cette tâche) : `remove()` détache
vraiment, `innerHTML=''` détruit vraiment les enfants, `hidden` et `inert` sont
lus, et les nœuds portent un `nodeType`.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

# Le monde injecté du cycle de vie est **réutilisé**, pas recopié : une seconde
# version dériverait de celle que les tests de la Slice 02 tiennent, et les deux
# décriraient deux contrôleurs différents sous un seul nom.
from test_barehands_lifecycle_js import WORLD  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
CONTRACTS = RUNTIME / "control_center_barehands_contracts.js"
CALIBRATION = RUNTIME / "control_center_barehands_calibration.js"
BAREHANDS = RUNTIME / "control_center_barehands.js"

#: Un DOM assez réel pour tomber comme le vrai tombe. Les quatre défauts de
#: réalisme de cette tâche sont explicitement couverts ici : les nœuds ont un
#: `nodeType`, `remove()` détache, `innerHTML=''` détruit les enfants, et les
#: dimensions dessinées sont celles du produit.
DOM = r"""
let nextId=0;
const made=[];
function makeNode(tag){
  const el={
    nodeType:1,tagName:String(tag).toUpperCase(),children:[],parent:null,
    id:'',className:'',textContent:'',hidden:false,inert:false,
    attrs:{},style:{},listeners:{},uid:nextId+=1,
    appendChild(child){child.parent=el;el.children.push(child);return child},
    remove(){
      if(!el.parent)return;
      const at=el.parent.children.indexOf(el);
      if(at>=0)el.parent.children.splice(at,1);
      el.parent=null;
    },
    setAttribute(key,value){el.attrs[key]=String(value)},
    getAttribute(key){return el.attrs[key]===undefined?null:el.attrs[key]},
    addEventListener(type,fn){(el.listeners[type]||(el.listeners[type]=[])).push(fn)},
    removeEventListener(type,fn){
      const list=el.listeners[type]||[];
      const at=list.indexOf(fn);if(at>=0)list.splice(at,1);
    },
    fire(type,event){for(const fn of (el.listeners[type]||[]).slice())fn(Object.assign({
      preventDefault(){}},event||{}))},
    get innerHTML(){return el.children.map(child=>child.textContent).join('')},
    /* Détruire **vraiment** : un double dont `innerHTML=''` laissait les
       enfants vivants est l'un des quatre défauts de réalisme de cette tâche.
       Ici les enfants sont détachés, donc un bouton qui survit à son étape se
       voit. */
    set innerHTML(value){
      if(value!=='')throw new Error('le double de DOM ne pose pas de balisage : seul innerHTML="" est utilisé');
      for(const child of el.children.slice())child.remove();
    },
  };
  made.push(el);
  return el;
}
const body=makeNode('body'),head=makeNode('head');
global.document={
  createElement:makeNode,
  head,body,documentElement:body,
  getElementById(id){
    const found=made.find(el=>el.id===id&&el.parent);
    return found||null;
  },
  listeners:{},
  addEventListener(type,fn){(document.listeners[type]||(document.listeners[type]=[])).push(fn)},
  removeEventListener(type,fn){
    const list=document.listeners[type]||[];
    const at=list.indexOf(fn);if(at>=0)list.splice(at,1);
  },
  fire(type,event){for(const fn of (document.listeners[type]||[]).slice())fn(Object.assign({
    preventDefault(){}},event||{}))},
};
const flowRoot=()=>document.getElementById(C.DOM.flowRootId);
const find=(root,cls)=>{
  const out=[];
  const walk=node=>{
    if(String(node.className||'').split(/\s+/).includes(cls))out.push(node);
    for(const child of node.children)walk(child);
  };
  if(root)walk(root);
  return out;
};
const text=(root,cls)=>find(root,cls).map(node=>node.textContent);
const buttons=root=>find(root,'').filter(node=>node.tagName==='BUTTON');
const allButtons=root=>{
  const out=[];
  const walk=node=>{if(node.tagName==='BUTTON')out.push(node);for(const child of node.children)walk(child)};
  if(root)walk(root);
  return out;
};
const press=(root,id)=>{
  const found=allButtons(root).find(node=>node.getAttribute('data-flow-action')===id);
  if(!found)throw new Error(`bouton ${id} absent`);
  found.fire('click');
  return found;
};
let clock=0;
const now=()=>clock;
"""


def run_node(tmp_path: Path, source: str, name: str = "calib") -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"barehands-{name}.cjs"
    script.write_text(
        f"const C=require({json.dumps(str(CONTRACTS))});\n"
        "global.JarvisBarehandsContracts=C;\n"
        f"const B=require({json.dumps(str(BAREHANDS))});\n"
        f"const K=require({json.dumps(str(CALIBRATION))});\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "const refused=fn=>{try{fn();return null}catch(e){return e.code||e.name||String(e)}};\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True,
                          encoding="utf-8", timeout=40, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ------------------------------------------------------------------ dérivation


def test_every_derivation_refuses_instead_of_inventing_a_number(tmp_path):
    """« Un refus codé plutôt qu'un défaut plausible », appliqué aux mesures.

    Une calibration qui ne peut pas mesurer doit le dire : le moteur garde alors
    ses défauts (décision 31), ce qui est bon, tandis qu'un nombre inventé
    déplacerait un seuil sans que personne ne sache d'où il vient.
    """

    result = run_node(tmp_path, """
      const o=K.options({});
      const many=n=>Array.from({length:n},(_,i)=>i);
      /* Un pincement répété plausible : le rapport descend vers 0,15 et
         remonte vers 0,55. La bande vaut 0,4 paume, largement séparable. */
      const pinches=many(80).map(i=>i%20<8?.15+.01*(i%8):.55-.01*(i%12));
      const flat=many(80).map(()=>.30);          // repos et pincement confondus
      out({
        // Trop peu d'échantillons : refusé, avec le compte.
        thin:K.deriveHysteresis(pinches.slice(0,5),o),
        // Rien de lisible du tout.
        empty:K.deriveHysteresis([null,NaN,undefined],o),
        // Inséparable : le refus qu'exige la Slice, pas un seuil médiocre.
        flat:K.deriveHysteresis(flat,o),
        good:K.deriveHysteresis(pinches,o),
        // Portée plate : elle défait le repli qu'elle devait remplacer.
        flatReach:K.deriveReach(many(40).map(()=>.5),many(40).map(()=>.5),o),
        goodReach:K.deriveReach(many(40).map(i=>.2+i*.01),many(40).map(i=>.3+i*.005),o),
        thinReach:K.deriveReach([.1,.2],[.1,.2],o),
        // Clic et glissement qui se ressemblent : aucun seuil ne les sépare.
        tangled:K.deriveTravelSlop(many(20).map(()=>.05),many(20).map(()=>.04),o),
        separated:K.deriveTravelSlop(many(20).map(()=>.004),many(20).map(()=>.09),o),
        /* Le cas ou la **marge de confort depasse le glissement** : un clic
           agite (0,03) et un glissement sage (0,04). La marge voudrait 0,048,
           au-dessus du glissement — la retenir ferait d'un glissement lent un
           clic. C'est la moitie de la regle que la marge seule ne donne pas. */
        marginTooWide:K.deriveTravelSlop(many(20).map(()=>.03),many(20).map(()=>.04),o),
        noDrag:K.deriveTravelSlop(many(20).map(()=>.004),[],o),
      });
    """)
    assert result["thin"]["ok"] is False
    assert result["thin"]["reason"] == "barehands_stage_too_few_samples"
    assert result["empty"]["ok"] is False and result["empty"]["samples"] == 0
    assert result["flat"]["ok"] is False
    assert result["flat"]["reason"] == "barehands_stage_not_separable", (
        "deux états confondus ne donnent pas un seuil médiocre, ils font clignoter le contact"
    )
    # La mesure réussie : les deux seuils tombent **dans** la bande observée, et
    # dans le bon ordre — c'est l'invariant que le contrat et le moteur exigent.
    good = result["good"]
    assert good["ok"] is True
    assert good["closed"] < good["pressRatio"] < good["releaseRatio"] < good["open"]
    # Et un pincement **confortable**, pas entièrement fermé, compte : le seuil
    # d'appui vit au tiers de la bande, pas contre le pincement le plus serré.
    assert good["pressRatio"] > good["closed"] + (good["open"] - good["closed"]) * 0.2

    assert result["flatReach"]["ok"] is False
    assert result["flatReach"]["reason"] == "barehands_stage_out_of_band"
    assert result["thinReach"]["reason"] == "barehands_stage_too_few_samples"
    assert result["goodReach"]["ok"] is True
    assert result["goodReach"]["reachNorm"]["w"] > 0 and result["goodReach"]["reachNorm"]["h"] > 0

    assert result["tangled"]["ok"] is False
    assert result["tangled"]["reason"] == "barehands_stage_not_separable"
    # La tolérance retenue reste **entre** le clic le plus agité et le
    # glissement le plus sage : au-dessus, un glissement lent redeviendrait un
    # clic ; en dessous, un clic un peu vivant deviendrait un glissement.
    sep = result["separated"]
    assert sep["ok"] is True
    assert sep["clickHigh"] < sep["travelSlopNorm"] < sep["dragLow"]
    # Et quand la marge depasserait le glissement, c'est le glissement qui
    # gagne : rester en dessous prime sur le confort, sinon un glissement lent
    # redeviendrait un clic.
    wide = result["marginTooWide"]
    assert wide["ok"] is True
    assert wide["travelSlopNorm"] < wide["dragLow"], (
        "la marge de confort ne doit jamais faire passer la tolerance au-dessus du glissement"
    )
    assert wide["travelSlopNorm"] == pytest.approx((wide["clickHigh"] + wide["dragLow"]) / 2)
    assert result["noDrag"]["ok"] is True and result["noDrag"]["dragLow"] is None


def test_the_jitter_is_read_on_raw_against_filtered_and_never_on_the_token(tmp_path):
    """**La mine que la Slice 04 a déjà trouvée sur `travelPx`.**

    Pendant un pincement, `x`/`y` du jeton est l'ancre de visée **figée** : elle
    ne dit plus rien de la main. Mesurer le tremblement dessus rendrait zéro
    pour une main qui tremble, et le profil promettrait une immobilité que
    l'utilisateur n'a pas.
    """

    result = run_node(tmp_path, """
      const o=K.options({stageMinSamples:10});
      /* Une main qui tremble de ±3 px autour de sa position filtrée, pendant
         qu'elle pince : l'ancre, elle, ne bouge pas d'un pixel. */
      const samples=Array.from({length:40},(_,i)=>({
        rawX:500+(i%2?3:-3),rawY:400+(i%3?2:-2),
        filteredX:500,filteredY:400,
        x:640,y:360,               // l'ancre figée du pincement
      }));
      out({
        onRaw:K.deriveJitter(samples,o),
        // Le même calcul sur l'ancre : zéro, pour une main qui tremble.
        onAnchor:K.deriveJitter(samples.map(s=>({rawX:s.x,rawY:s.y,
          filteredX:s.x,filteredY:s.y})),o),
      });
    """)
    assert result["onRaw"]["ok"] is True
    assert result["onRaw"]["jitterPx"] > 2, "le tremblement réel se voit"
    assert result["onAnchor"]["jitterPx"] == 0, (
        "sur l'ancre figée, la même main ne tremble plus du tout — c'est la mesure à ne pas faire"
    )


def test_the_c_pose_stage_names_the_thumb_middle_gate_that_nobody_could_guess(tmp_path):
    """La Slice 04 a fait lire au score du C le **canal secondaire** : une main
    qui pince n'est pas une posture. Un C dont le majeur reste près du pouce
    marque donc zéro alors que son écart pouce-index est parfait — et
    l'utilisateur n'a aucun moyen de le deviner.

    L'étape le distingue des deux autres causes, parce que la phrase à dire
    n'est pas la même : « écartez le majeur » contre « écartez le pouce »."""

    result = run_node(tmp_path, """
      const o=K.options({stageMinSamples:5});
      const band=K.wakeBandOf(B.DEFAULTS);
      const rows=(gap,reach,cPose,secondary)=>Array.from({length:30},()=>(
        {gapPalms:gap,indexReachPalms:reach,cPose,secondaryRatio:secondary}));
      out({
        band,
        // Un C franc, au milieu de la bande : accepté.
        good:K.checkCPose(rows(.65,1.8,.9,.9),band,o),
        // Majeur collé au pouce : la vraie cause, nommée en premier.
        gated:K.checkCPose(rows(.65,1.8,0,.2),band,o),
        // Pouce et index trop proches, puis trop écartés.
        tight:K.checkCPose(rows(.40,1.8,0,.9),band,o),
        wide:K.checkCPose(rows(.95,1.8,0,.9),band,o),
        // Index replié : la portée, pas l'écart.
        curled:K.checkCPose(rows(.65,1.2,0,.9),band,o),
        thin:K.checkCPose(rows(.65,1.8,.9,.9).slice(0,2),band,o),
      });
    """)
    # La bande **effective**, recalculée depuis les défauts du moteur — jamais
    # les zéros du score, qui se trompent de 10 % sur la portée.
    assert round(result["band"]["gapMin"], 3) == 0.499
    assert round(result["band"]["gapMax"], 3) == 0.811
    assert round(result["band"]["reachMin"], 3) == 1.485
    assert result["good"]["ok"] is True
    assert result["gated"]["ok"] is False
    assert result["gated"]["cause"] == "secondary", (
        "le majeur passe avant l'écart : c'est la cause qu'on ne devine pas, "
        "et elle rend les deux autres mesures trompeuses"
    )
    assert result["gated"]["reason"] == "barehands_stage_not_separable"
    assert result["tight"]["cause"] == "gap_low" and result["wide"]["cause"] == "gap_high"
    assert result["curled"]["cause"] == "reach"
    assert result["thin"]["reason"] == "barehands_stage_too_few_samples"


def test_three_settings_pairs_that_would_fail_every_calibration_are_refused_at_construction(tmp_path):
    """Trois paires dangereuses de plus, et elles échouent toutes de la même
    façon : en silence, en retombant sur les défauts, ce qui se lit
    « l'utilisateur s'y prend mal ». C'est la classe qui est apparue huit fois
    sur cette tâche ; elle se refuse à la construction."""

    result = run_node(tmp_path, """
      out({
        shipping:refused(()=>K.options({})),
        // 9 : l'étape expire pendant que l'utilisateur tient la pose.
        deadlineUnderHold:refused(()=>K.options({stageTimeoutMs:2000,stageHoldMs:2500})),
        deadlineEqualHold:refused(()=>K.options({stageTimeoutMs:2500,stageHoldMs:2500})),
        // 10 : chaque calibration dériverait pressRatio >= releaseRatio.
        pressOverRelease:refused(()=>K.options({pressAt:.7,releaseAt:.5})),
        pressEqualRelease:refused(()=>K.options({pressAt:.5,releaseAt:.5})),
        pressAtZero:refused(()=>K.options({pressAt:0})),
        releaseAtOne:refused(()=>K.options({releaseAt:1})),
        // 11 : bornes inversées, donc la même tolérance pour tout le monde.
        slopInverted:refused(()=>K.options({travelSlopMin:.2,travelSlopMax:.1})),
        slopEqual:refused(()=>K.options({travelSlopMin:.1,travelSlopMax:.1})),
        slopZero:refused(()=>K.options({travelSlopMin:0})),
        // Et deux gardes simples du même esprit.
        noSamples:refused(()=>K.options({stageMinSamples:0})),
        marginUnderOne:refused(()=>K.options({travelSlopMargin:.5})),
        defaults:[K.DEFAULTS.stageTimeoutMs,K.DEFAULTS.stageHoldMs,
                  K.DEFAULTS.pressAt,K.DEFAULTS.releaseAt,
                  K.DEFAULTS.travelSlopMin,K.DEFAULTS.travelSlopMax],
      });
    """)
    assert result["shipping"] is None, "le réglage d'usine passe"
    for case in ("deadlineUnderHold", "deadlineEqualHold", "pressOverRelease", "pressEqualRelease",
                 "pressAtZero", "releaseAtOne", "slopInverted", "slopEqual", "slopZero",
                 "noSamples", "marginUnderOne"):
        assert result[case] == "RangeError", case
    # Et les défauts livrés respectent les invariants qu'ils viennent de poser.
    timeout, hold, press_at, release_at, slop_min, slop_max = result["defaults"]
    assert timeout > hold and press_at < release_at and slop_min < slop_max


# ------------------------------------------------------------------ la coque


def test_the_shell_holds_rule_zero_and_spares_the_hand_overlay_from_its_inert_sweep(tmp_path):
    """**Décision 26** : une coque, deux parcours. Elle ne sait rien de la
    calibration — elle affiche des étapes — et c'est ce qui permettra au
    tutoriel (Slice 09) de la reprendre sans la modifier.

    **RÈGLE ZÉRO**, les quatre points, à l'écran en même temps : que quelque
    chose tourne (l'anneau avance), quoi (la consigne en français), depuis
    combien de temps (un compteur vivant), et comment en sortir (un bouton
    *et* Échap). Plus la cinquième exigence : une étape porte une échéance
    qu'elle ne peut pas dépasser.

    Et le balayage `inert` **épargne la surimpression des mains** : on calibre
    *avec ses mains*, donc désarmer `#jarvisHands` désarmerait le parcours
    lui-même.
    """

    result = run_node(tmp_path, DOM + """
      /* La page derrière : ce que le balayage doit désarmer, et les deux
         racines Bare Hands qu'il doit épargner. */
      const page=document.createElement('div');page.id='page';document.body.appendChild(page);
      const hands=document.createElement('div');hands.id=C.DOM.rootId;document.body.appendChild(hands);
      let exits=[];
      const shell=K.createFlowOverlay({document,now,
        setInterval:()=>1,clearInterval:()=>{}});
      const opened=shell.open({title:'Calibration Bare Hands',exit:why=>exits.push(why)});
      const root=flowRoot();
      const readClock=()=>find(root,'jf-meta')[0].children.map(n=>n.textContent);

      shell.step({index:2,total:7,title:'Posture de réveil',
        instruction:'Formez un C.',deadlineMs:20000});
      const atStart=readClock();
      shell.progress(.4);
      const bar=find(root,C.DOM.flowProgressClass)[0].children[0];
      const width=bar.style.width;
      clock=7000;
      // Le compteur est **vivant** : repeint à chaque progression, et par la
      // minuterie injectée. Sans lui, « ça travaille » et « c'est bloqué »
      // s'écrivent pareil.
      shell.progress(.5);
      const later=readClock();
      const notExpired=shell.expired();
      clock=28000;
      const expired=shell.expired();

      // Échap sort, et le bouton aussi : deux chemins, pas un seul.
      document.fire('keydown',{key:'Escape'});
      shell.buttons([{id:'exit',label:'Quitter',run:()=>exits.push('bouton')}]);
      press(root,'exit');

      const inertedIds=document.body.children.filter(n=>n.inert).map(n=>n.id);
      const sparedIds=document.body.children.filter(n=>!n.inert).map(n=>n.id);

      /* Les boutons sont redessinés à chaque étape : un bouton qui survit à
         l'étape qui l'a posé déclenche ce que l'écran ne montre plus. Le double
         détruit vraiment, donc la question se pose vraiment. */
      shell.buttons([{id:'apply',label:'Appliquer',run:()=>{}}]);
      const afterRedraw=allButtons(root).map(n=>n.getAttribute('data-flow-action'));

      const closed=shell.close();
      out({
        opened,closed,exits,atStart,later,width,notExpired,expired,
        afterRedraw,inertedIds,sparedIds,
        stillAttached:!!flowRoot(),
        // Une coque sans sortie est un piège : elle se refuse.
        noExit:refused(()=>K.createFlowOverlay({document,now}).open({title:'x'})),
        noDocument:refused(()=>K.createFlowOverlay({})),
        // Après fermeture, l'écouteur de clavier est retiré : une coque fermée
        // qui répond encore à Échap agirait sur une page qu'elle ne montre plus.
        listenersLeft:(document.listeners.keydown||[]).length,
        // Le point à viser fait la taille que le produit dessine.
        targetPx:K.STYLE.includes('width:24px;height:24px'),
      });
    """, name="shell")

    assert result["opened"] is True and result["closed"] is True
    # 1. QUOI, 2. DEPUIS COMBIEN DE TEMPS, 3. QUE ÇA TOURNE, 4. COMMENT SORTIR.
    assert result["atStart"] == ["0 s", "20 s restantes"]
    assert result["later"] == ["7 s", "13 s restantes"], "le compteur avance et l'échéance descend"
    assert result["width"] == "40%", "l'anneau dit qu'il se passe quelque chose"
    assert result["notExpired"] is False and result["expired"] is True, (
        "une étape porte une échéance qu'elle ne peut pas dépasser"
    )
    assert result["exits"] == ["escape", "bouton"], "deux chemins de sortie, tous les deux vivants"
    # Le balayage désarme la page et **épargne** la surimpression des mains.
    assert result["inertedIds"] == ["page"]
    assert sorted(result["sparedIds"]) == sorted([C_ROOT_ID, "jarvisFlow"])
    assert result["afterRedraw"] == ["apply"], "les boutons d'une étape ne survivent pas à l'étape"
    assert result["stillAttached"] is False, "fermer détache vraiment"
    assert result["listenersLeft"] == 0
    assert result["noExit"] == "RangeError"
    assert result["noDocument"] == "RangeError"
    assert result["targetPx"] is True


C_ROOT_ID = "jarvisHands"


#: Le pilote du parcours : des enregistrements de **scalaires**, la seule chose
#: que la couture du contrôleur laisse passer (décision 32).
DRIVER = r"""
const shellOf=()=>K.createFlowOverlay({document,now,setInterval:()=>1,clearInterval:()=>{}});
const saved=[];const failSave={at:false};
const calOf=extra=>K.createCalibration(Object.assign({
  overlay:shellOf(),now,engineDefaults:B.DEFAULTS,
  viewport:()=>({width:1280,height:720}),
  options:{stageHoldMs:300,stageTimeoutMs:5000,stageMinSamples:10,pinchRepeats:2},
  save:async payload=>{if(failSave.at)throw new Error('le serveur a refuse');saved.push(payload)},
},extra||{}));
/* Une main plausible : le jeton tremble de deux pixels autour de sa position
   filtree, la qualite est bonne, et la paume vaut un cinquieme de l'image. */
let wobble=0;
const hand=over=>Object.assign({
  handedness:'left',quality:.9,stillness:.9,
  rawX:640+((wobble+=1)%2?2:-2),rawY:400+(wobble%3?2:-2),
  filteredX:640,filteredY:400,palmX:620,palmY:410,
  primaryRatio:.55,secondaryRatio:.55,cPose:.9,closure:.1,
  gapPalms:.65,indexReachPalms:1.8,palmNorm:.2,
  /* Une main **derive** dans les deux axes pendant une seance : la figer sur
     un point rendrait la portee plate, ce que la derivation refuse a juste
     titre — et le test mesurerait alors le refus, pas la mesure. */
  xNorm:.42+(wobble%23)*.006,yNorm:.40+(wobble%17)*.008,
  speedPxPerSec:10,
},over||{});
const feed=(cal,count,over,stepMs)=>{
  for(let i=0;i<count;i+=1){clock+=stepMs===undefined?16:stepMs;
    cal.feed({now:clock,hands:[hand(typeof over==='function'?over(i):over)]})}
};
const feedBoth=(cal,count)=>{
  for(let i=0;i<count;i+=1){clock+=16;
    cal.feed({now:clock,hands:[hand({}),hand({handedness:'right',palmX:800})]})}
};
const reportRows=()=>find(flowRoot(),'jf-report')[0].children.map(li=>
  [li.children[0].textContent,li.children[1].className,li.children[1].textContent]);
/* Nourrir **jusqu'a ce que l'etape bouge**, plutot qu'un nombre d'images
   choisi a la main : une etape qui se conclut plus tot ou plus tard n'est pas
   un defaut, et un test qui compte les images mesure la cadence du double au
   lieu de mesurer le parcours. */
const feedUntil=(cal,over,cap)=>{
  const from=cal.stepId();let n=0;
  while(cal.stepId()===from&&n<(cap||600)){
    clock+=16;cal.feed({now:clock,hands:[hand(typeof over==='function'?over(n):over)]});n+=1;
  }
  return {from,to:cal.stepId(),frames:n};
};
const pinching=key=>i=>{const o={stillness:.5};o[key]=i%10<5?.15:.6;return o};
"""


def test_a_full_run_derives_a_profile_and_nothing_is_written_until_it_is_asked(tmp_path):
    """Le parcours de bout en bout, et **l'application explicite**.

    Un parcours qui enregistre tout seul a la derniere image prend une decision
    que l'utilisateur n'a pas prise, sur des mesures qu'il n'a pas vues. Le
    rapport se montre d'abord ; « Appliquer » ecrit, « Annuler » ne touche a
    rien.
    """

    result = run_node(tmp_path, DOM + DRIVER + """
      const cal=calOf();
      const started=cal.start();
      const visited=[cal.stepId()];
      // Repos, puis la posture en C : deux poses tenues.
      visited.push(feedUntil(cal,{}).to);
      visited.push(feedUntil(cal,{cPose:.9,gapPalms:.65,indexReachPalms:1.8,secondaryRatio:.9}).to);
      // Les deux canaux de pincement, repetes.
      visited.push(feedUntil(cal,pinching('primaryRatio')).to);
      visited.push(feedUntil(cal,pinching('secondaryRatio')).to);
      // Viser : pincer sans bouger, puis relacher.
      feed(cal,6,{primaryRatio:.15});
      feed(cal,2,{primaryRatio:.6,palmX:623});
      visited.push(cal.stepId());
      // Glisser : pincer, parcourir franchement, relacher.
      feed(cal,6,{primaryRatio:.15});
      feed(cal,2,{primaryRatio:.6,palmX:1000});
      visited.push(cal.stepId());
      feedBoth(cal,60);
      const beforeApply=saved.length;
      const rows=reportRows();
      press(flowRoot(),'apply');
      await new Promise(r=>setImmediate(r));
      out({started,steps:visited,
        beforeApply,afterApply:saved.length,rows,
        payload:saved[0]||null,closed:!flowRoot(),running:cal.isRunning()});
    """, name="fullrun")

    assert result["started"]["ok"] is True
    assert result["started"]["flow"] == "calibration" and result["started"]["steps"] == 7
    assert result["steps"] == ["neutral", "c_pose", "pinch_primary", "pinch_secondary",
                               "aim", "drag", "resize"]
    assert result["beforeApply"] == 0, "le parcours n'enregistre pas tout seul"
    assert result["afterApply"] == 1
    payload = result["payload"]
    assert payload["schemaVersion"] == 2
    assert payload["calibrated"] is True
    left = payload["hands"]["left"]
    assert left["pressRatio"] is not None and left["releaseRatio"] is not None
    assert left["pressRatio"] < left["releaseRatio"], "l'invariant du moteur tient par construction"
    assert left["secondaryPressRatio"] is not None and left["secondaryReleaseRatio"] is not None
    assert left["jitterPx"] is not None and left["travelSlopNorm"] is not None
    assert left["reachNorm"] is not None and left["quality"] is not None
    assert all(report["status"] == "ok" for report in payload["stages"].values()), payload["stages"]
    assert [row[1] for row in result["rows"]] == ["jf-ok"] * 7
    assert result["closed"] is True and result["running"] is False


def test_a_failed_stage_falls_back_to_the_defaults_and_the_profile_says_which(tmp_path):
    """**Decision 31**, la moitie qui compte : une calibration partielle est
    valide. Une etape ratee laisse ses cles **nulles** — donc `profileValue`
    rend le defaut du moteur — et le rapport dit laquelle et pourquoi.

    Quatre facons de rater, **quatre motifs differents**, parce qu'elles ne
    demandent pas la meme chose a l'utilisateur : un C que son propre majeur
    etouffe, un pincement qu'on ne distingue pas du repos, une etape que
    l'utilisateur passe, une etape a deux mains qui n'en voit qu'une. « Temps
    ecoule » serait vrai des quatre et n'aiderait pour aucune."""

    result = run_node(tmp_path, DOM + DRIVER + """
      const cal=calOf();
      cal.start();
      feedUntil(cal,{});
      /* Le C etouffe par le canal secondaire : l'ecart pouce-index est
         parfait, mais le majeur reste colle au pouce, donc le score est nul —
         et l'utilisateur ne peut pas le deviner (gate de la Slice 04). */
      feedUntil(cal,{cPose:0,gapPalms:.65,indexReachPalms:1.8,secondaryRatio:.2});
      /* La phrase de l'echec est lue **apres** le changement d'etape : c'est
         la ou l'utilisateur la voit vraiment. Ecrite puis effacee par l'etape
         suivante, elle aurait ete affichee zero milliseconde. */
      const cNote=text(flowRoot(),C.DOM.flowNoteClass)[0];
      const afterC=cal.stepId();
      /* Pincement **inseparable** : le rapport traverse le seuil d'usine, donc
         les repetitions comptent, mais la bande parcourue est trop etroite
         pour qu'on puisse poser un seuil dedans. */
      feedUntil(cal,i=>({primaryRatio:i%10<5?.40:.45,stillness:.5}));
      const pinchNote=text(flowRoot(),C.DOM.flowNoteClass)[0];
      const afterPrimary=cal.stepId();
      // Le pincement secondaire, lui, l'utilisateur le passe.
      press(flowRoot(),'skip');
      const afterSkip=cal.stepId();
      feed(cal,6,{primaryRatio:.15});feed(cal,2,{primaryRatio:.6,palmX:623});
      feed(cal,6,{primaryRatio:.15});feed(cal,2,{primaryRatio:.6,palmX:1000});
      /* Deux mains demandees, une seule montree : l'echeance passe, et le
         motif dit **ce qui manquait**. */
      const before=cal.stepId();
      clock+=6000;cal.feed({now:clock,hands:[hand({})]});
      const rows=reportRows();
      press(flowRoot(),'apply');
      await new Promise(r=>setImmediate(r));
      out({cNote,pinchNote,afterC,afterPrimary,afterSkip,before,rows,payload:saved[0]||null});
    """, name="partial")

    payload = result["payload"]
    stages = payload["stages"]
    # Le C : la cause qu'on ne devine pas est **dite**, en toutes lettres.
    assert result["afterC"] == "pinch_primary"
    assert stages["c_pose"]["status"] == "failed"
    assert stages["c_pose"]["reason"] == "barehands_stage_not_separable"
    assert "majeur" in result["cNote"], "la phrase nomme le doigt, pas le score"
    # Le pincement inseparable : refuse, pas raboté.
    assert result["afterPrimary"] == "pinch_secondary"
    assert stages["pinch_primary"]["reason"] == "barehands_stage_not_separable"
    assert "se ressemblent trop" in result["pinchNote"]
    assert "valeurs d" in result["pinchNote"], "et elle dit que le moteur garde ses defauts"
    # Passee n'est pas ratee : l'utilisateur n'a rien a se reprocher.
    assert stages["pinch_secondary"]["status"] == "skipped"
    assert stages["pinch_secondary"]["reason"] is None
    # L'etape a deux mains dit **ce qui manquait**, pas « temps ecoule ».
    assert result["before"] == "resize"
    assert stages["resize"]["status"] == "failed"
    assert stages["resize"]["reason"] == "barehands_stage_needs_two_hands"
    # Ce qui a marche a bien ete mesure.
    assert stages["neutral"]["status"] == "ok" and stages["aim"]["status"] == "ok"
    # **Et les cles des etapes ratees restent nulles** : c'est ce qui fait que
    # le moteur garde ses defauts au lieu de recevoir une mesure inventee.
    left = payload["hands"]["left"]
    assert left["pressRatio"] is None and left["releaseRatio"] is None
    assert left["secondaryPressRatio"] is None and left["secondaryReleaseRatio"] is None
    assert left["jitterPx"] is not None, "ce qui a ete mesure est la"
    assert left["travelSlopNorm"] is not None, "viser et glisser ont tous deux abouti"
    # Partiel reste **calibre** : une seule mesure suffit (contrat §10).
    assert payload["calibrated"] is True
    labels = {row[0]: (row[1], row[2]) for row in result["rows"]}
    assert labels["Pincement pouce-index"][0] == "jf-failed"
    assert labels["Pincement pouce-majeur"][0] == "jf-skipped"
    assert labels["Deux mains"][0] == "jf-failed"
    assert "deux mains" in labels["Deux mains"][1]


def test_quitting_the_flow_writes_nothing_at_all(tmp_path):
    """Sortir n'est pas enregistrer. Un parcours abandonne a la cinquieme etape
    a mesure quatre choses ; les ecrire remplacerait le profil de
    l'utilisateur par une seance qu'il n'a pas voulue."""

    result = run_node(tmp_path, DOM + DRIVER + """
      const cal=calOf();
      cal.start();
      feedUntil(cal,{});
      feedUntil(cal,{cPose:.9,secondaryRatio:.9});
      const open=cal.isRunning();
      document.fire('keydown',{key:'Escape'});
      const first={open,running:cal.isRunning(),closed:!flowRoot(),written:saved.length,
        restarted:cal.start().ok,stepAfterRestart:cal.stepId()};
      /* Deuxieme passe : aller **jusqu'au rapport**, ou les mesures existent et
         sont deja derivees, puis refuser. C'est la que « annuler » coute le
         plus cher a respecter, donc c'est la qu'il faut le mesurer. */
      feedUntil(cal,{});
      while(cal.isRunning()&&allButtons(flowRoot())
        .some(n=>n.getAttribute('data-flow-action')==='skip'))press(flowRoot(),'skip');
      const derived=allButtons(flowRoot())
        .some(n=>n.getAttribute('data-flow-action')==='apply');
      press(flowRoot(),'discard');
      out(Object.assign(first,{afterReport:{derived,written:saved.length,
        closed:!flowRoot()}}));
    """, name="quit")
    assert result["open"] is True
    assert result["running"] is False and result["closed"] is True
    assert result["written"] == 0, "quitter n'ecrit rien"
    assert result["restarted"] is True and result["stepAfterRestart"] == "neutral"
    # Et **apres le rapport** non plus : c'est le moment le plus tentant, les
    # mesures existent et sont derivees. « Annuler » veut dire annuler.
    assert result["afterReport"] == {"derived": True, "written": 0, "closed": True}


def test_a_save_that_fails_keeps_the_measurements_on_screen_with_a_way_to_retry(tmp_path):
    """REGLE ZERO, et le cout particulier de cet echec : refermer la coque sur
    un enregistrement rate jetterait une minute de mesures que l'utilisateur
    devrait refaire en entier."""

    result = run_node(tmp_path, DOM + DRIVER + """
      const cal=calOf();
      cal.start();
      feedUntil(cal,{});
      while(cal.isRunning()&&allButtons(flowRoot())
        .some(n=>n.getAttribute('data-flow-action')==='skip'))press(flowRoot(),'skip');
      failSave.at=true;
      press(flowRoot(),'apply');
      await new Promise(r=>setImmediate(r));
      const note=text(flowRoot(),C.DOM.flowNoteClass)[0];
      const actions=allButtons(flowRoot()).map(n=>n.getAttribute('data-flow-action'));
      const stillOpen=!!flowRoot();
      failSave.at=false;
      press(flowRoot(),'retry');
      await new Promise(r=>setImmediate(r));
      out({note,actions,stillOpen,written:saved.length,closed:!flowRoot()});
    """, name="savefail")
    assert "Enregistrement impossible" in result["note"]
    assert "le serveur a refuse" in result["note"], "la phrase du serveur, pas une phrase inventee"
    assert result["stillOpen"] is True, "la coque reste ouverte : les mesures ne sont pas jetees"
    assert sorted(result["actions"]) == ["discard", "retry"]
    assert result["written"] == 1 and result["closed"] is True, "reessayer marche vraiment"


def test_calling_calibrate_while_it_is_already_open_confirms_instead_of_denying(tmp_path):
    """Contrat §12 : `calibrate()` doit **confirmer**. Une deuxieme demande
    pendant que la coque est a l'ecran decrit l'etat que l'appelant voulait —
    repondre « non » ferait dire a JARVIS que ca n'a pas demarre devant une
    coque ouverte."""

    result = run_node(tmp_path, DOM + DRIVER + """
      const cal=calOf();
      const first=cal.start();
      feed(cal,10);
      const second=cal.start();
      out({first,second,
        shells:document.body.children.filter(n=>n.id===C.DOM.flowRootId).length});
    """, name="twice")
    assert result["first"]["ok"] is True and result["second"]["ok"] is True
    assert result["second"]["already"] is True
    assert result["shells"] == 1, "et une seule coque, pas deux empilees"


# --------------------------------------------- la couture, mesurée pour de vrai


def test_only_scalars_cross_the_controller_seam_measured_on_real_hand_geometry(tmp_path):
    """**Décision 32 tenue en structure, et mesurée plutôt qu'affirmée.**

    « Le parcours ne conserve que des scalaires » serait une promesse sur du
    code qu'on a écrit. Ce qui la tient est ce qui **traverse la couture** : le
    contrôleur réduit chaque image à un enregistrement de nombres avant de la
    passer au parcours, qui ne peut donc pas persister une image, une vidéo ni
    un point — non parce que c'est interdit, parce qu'il n'en a jamais eu.

    Le test le mesure sur la **vraie** géométrie de main, à travers le **vrai**
    traqueur, le **vrai** filtre et le **vrai** contrôleur — pas sur des valeurs
    écrites à la main. C'est cette couture-là, et elle seule, qui décide de ce
    que le parcours reçoit, et aucun test du parcours ne peut la voir.
    """

    result = run_node(tmp_path, WORLD + """
      /* Une main en C, vue par le contrôleur entier : caméra, modèle, traqueur,
         filtre. `handedness` vient du vote du traqueur, pas d'une constante. */
      const seen=[];
      const w=world({result:{landmarks:[hand(.65,1.8)],
        handedness:[[{categoryName:'Left',score:.95}]]}});
      w.deps.onMeasure=record=>seen.push(record);
      const controller=B.createController(w.deps);
      controller.enable();
      await new Promise(r=>setImmediate(r));
      await new Promise(r=>setImmediate(r));
      controller.activate();
      await new Promise(r=>setImmediate(r));
      await new Promise(r=>setImmediate(r));
      w.steps(12);
      /* Puis un pincement franc, pour que les rapports **bougent** : une
         couture qui rendrait toujours le même nombre passerait un test qui ne
         regarde qu'une image. */
      w.state.result={landmarks:[hand(.06,1.8)],handedness:[[{categoryName:'Left',score:.95}]]};
      w.steps(12);

      const records=seen.length;
      const hands=seen.flatMap(record=>record.hands);
      /* Ce qui traverse : **rien** qui ne soit un nombre, une chaîne courte ou
         `null`. Un tableau, un objet, une chaîne longue : autant de formes qui
         pourraient porter une image ou une suite de points. */
      const shapes={};
      const offenders=[];
      for(const sample of hands){
        for(const key of Object.keys(sample)){
          const value=sample[key];
          const kind=value===null?'null':Array.isArray(value)?'array':typeof value;
          (shapes[kind]||(shapes[kind]=new Set())).add(key);
          if(kind==='array'||kind==='object')offenders.push(key);
          if(kind==='string'&&String(value).length>16)offenders.push(key);
        }
      }
      const cPose=hands.map(s=>s.cPose).filter(v=>Number.isFinite(v));
      const primary=hands.map(s=>s.primaryRatio).filter(v=>Number.isFinite(v));
      out({
        records,samples:hands.length,offenders,
        keys:Object.keys(hands[0]||{}).sort(),
        numberKeys:[...(shapes.number||[])].sort(),
        stringKeys:[...(shapes.string||[])].sort(),
        /* Les valeurs sont **vraies** : l'écart pouce-index d'un C vaut 0,65
           paume, celui d'un pincement franc 0,06 — ce sont les nombres que la
           géométrie porte, pas des constantes recopiées. */
        gapFirst:hands[0]?hands[0].gapPalms:null,
        gapLast:hands[hands.length-1]?hands[hands.length-1].gapPalms:null,
        reach:hands[0]?hands[0].indexReachPalms:null,
        palmNorm:hands[0]?hands[0].palmNorm:null,
        handedness:[...new Set(hands.map(s=>s.handedness))],
        cPoseHigh:Math.max(...cPose),cPoseLow:Math.min(...cPose),
        primaryHigh:Math.max(...primary),primaryLow:Math.min(...primary),
        // Brut et filtré voyagent **séparément** : c'est ce qui rend le
        // tremblement mesurable du bon côté.
        rawApart:hands.some(s=>s.rawX!==s.filteredX||s.rawY!==s.filteredY),
        // Et l'enregistrement porte de quoi convertir en fraction d'image.
        viewport:seen[0]?seen[0].viewport:null,
      });
    """, name="seam")

    assert result["records"] > 0, "la couture doit être appelée pendant l'interaction"
    assert result["samples"] > 0
    # **Le cœur du test** : rien de ce qui traverse ne peut porter une image.
    assert result["offenders"] == [], f"la couture laisse passer {result['offenders']}"
    assert result["stringKeys"] == ["handedness"], (
        "la seule chaîne est la latéralité, et elle vient d'un vocabulaire fermé"
    )
    assert "landmarks" not in result["keys"] and "frame" not in result["keys"]
    # Les mesures dont les étapes ont besoin sont toutes là.
    for key in ("primaryRatio", "secondaryRatio", "cPose", "closure", "gapPalms",
                "indexReachPalms", "palmNorm", "xNorm", "yNorm",
                "rawX", "rawY", "filteredX", "filteredY", "palmX", "palmY",
                "quality", "stillness", "t"):
        assert key in result["keys"], key
    # Et elles portent la **vraie** géométrie, mesurée et non recopiée.
    assert result["gapFirst"] == pytest.approx(0.65, abs=1e-6)
    assert result["gapLast"] == pytest.approx(0.06, abs=1e-6)
    assert result["reach"] == pytest.approx(1.8, abs=1e-6)
    assert 0 < result["palmNorm"] < 1
    assert result["handedness"] == ["left"], "la latéralité vient du vote du traqueur"
    # Le C marque haut, le pincement franc marque zéro : la couture suit la
    # main au lieu de rendre un nombre figé.
    assert result["cPoseHigh"] > 0.5 and result["cPoseLow"] == 0
    assert result["primaryHigh"] == pytest.approx(0.65, abs=1e-6)
    assert result["primaryLow"] == pytest.approx(0.06, abs=1e-6)
    assert result["viewport"] == {"width": 100, "height": 100}


def test_the_seam_costs_nothing_when_nobody_is_calibrating(tmp_path):
    """Le budget d'images est un acquis mesuré de la Slice 02, et la Slice 08
    n'a pas le droit de le dépenser pour une fonctionnalité qui ne tourne que
    sur demande (décision 27). Sans `onMeasure`, rien n'est calculé."""

    result = run_node(tmp_path, WORLD + """
      const run=async withSeam=>{
        const w=world({result:{landmarks:[hand(.65,1.8)],
          handedness:[[{categoryName:'Left',score:.95}]]}});
        let calls=0;
        if(withSeam)w.deps.onMeasure=()=>{calls+=1};
        const controller=B.createController(w.deps);
        controller.enable();
        await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));
        controller.activate();
        await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));
        w.steps(10);
        return {calls,frames:w.seen(),lifecycle:controller.state()};
      };
      out({without:await run(false),with:await run(true)});
    """, name="seamcost")
    assert result["without"]["calls"] == 0
    assert result["with"]["calls"] > 0
    # Le même nombre d'images dans les deux cas : la couture n'ajoute pas de
    # passe, elle réduit celle qui existe.
    assert result["without"]["frames"] == result["with"]["frames"]
    assert result["without"]["lifecycle"] == result["with"]["lifecycle"] == "active"
