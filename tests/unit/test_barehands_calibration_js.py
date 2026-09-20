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

# Le **vrai** bloc navigateur de la Slice 07, réutilisé et non recopié : c'est
# lui qui installe les six modules comme la page les insère, donc le seul
# endroit où l'on puisse vérifier que la page **branche** le chien de garde.
from test_barehands_tools_settings_js import (  # noqa: E402
    CAMERA, TIMERS, browser, run_node as run_browser,
)

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
/* Ce que le **parcours** dessine, par opposition à la sortie permanente que la
   coque pose une fois pour toutes (`data-flow-close`). Les deux vivent dans le
   même arbre et ne se lisent pas ensemble : l'une change à chaque étape,
   l'autre ne bouge jamais. */
const stepActions=root=>allButtons(root).map(n=>n.getAttribute('data-flow-action')).filter(Boolean);
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
        /* 14 : le chien de garde plus lent que l'échéance qu'il surveille
           laisse « 0 s restantes » à l'écran pendant une échéance de plus. */
        watchdogOver:refused(()=>K.options({watchdogMs:K.DEFAULTS.stageTimeoutMs*2})),
        watchdogEqual:refused(()=>K.options({watchdogMs:K.DEFAULTS.stageTimeoutMs})),
        watchdogZero:refused(()=>K.options({watchdogMs:0})),
        /* 15 : l'étape de pincement se solde à la première image, la
           dérivation n'a qu'un échantillon, et **les deux étapes de pincement
           échouent pour tout le monde** — en accusant l'utilisateur. À zéro,
           `progress(repeats/0)` vaut en plus `NaN`. */
        pinchZero:refused(()=>K.options({pinchRepeats:0})),
        pinchNegative:refused(()=>K.options({pinchRepeats:-3})),
        pinchOne:refused(()=>K.options({pinchRepeats:1})),
        // Une qualité minimale inatteignable filtre **toutes** les images.
        qualityOverOne:refused(()=>K.options({sampleQualityMin:1.2})),
        qualityNegative:refused(()=>K.options({sampleQualityMin:-.1})),
        // Une séparabilité qu'aucune main ne produit refuse toutes les mesures.
        separationOverOne:refused(()=>K.options({separationMinPalms:1.5})),
        separationZero:refused(()=>K.options({separationMinPalms:0})),
        defaults:[K.DEFAULTS.stageTimeoutMs,K.DEFAULTS.stageHoldMs,
                  K.DEFAULTS.pressAt,K.DEFAULTS.releaseAt,
                  K.DEFAULTS.travelSlopMin,K.DEFAULTS.travelSlopMax],
      });
    """)
    assert result["shipping"] is None, "le réglage d'usine passe"
    for case in ("deadlineUnderHold", "deadlineEqualHold", "pressOverRelease", "pressEqualRelease",
                 "pressAtZero", "releaseAtOne", "slopInverted", "slopEqual", "slopZero",
                 "noSamples", "marginUnderOne",
                 "watchdogOver", "watchdogEqual", "watchdogZero",
                 "pinchZero", "pinchNegative",
                 "qualityOverOne", "qualityNegative",
                 "separationOverOne", "separationZero"):
        assert result[case] == "RangeError", case
    # Et la borne est bien une borne, pas un refus déguisé : une répétition
    # unique est une calibration exigeante, pas une calibration impossible.
    assert result["pinchOne"] is None
    # Et les défauts livrés respectent les invariants qu'ils viennent de poser.
    timeout, hold, press_at, release_at, slop_min, slop_max = result["defaults"]
    assert timeout > hold and press_at < release_at and slop_min < slop_max


def test_a_calibration_without_a_shell_or_without_a_writer_is_refused_at_construction(tmp_path):
    """Les deux coutures **obligatoires** de `createCalibration`, exercées
    (constat de la Slice 11 : elles étaient refusées et jamais testées).

    - **La coque** est partagée avec le tutoriel (décision 26), elle ne se
      recrée pas ici. Absente, le parcours mesurerait sans rien montrer —
      exactement la panne que la RÈGLE ZÉRO interdit — et il la découvrirait au
      premier `start()`, c'est-à-dire devant l'utilisateur.
    - **L'écrivain** (`save`) : un parcours qui mesure sans pouvoir enregistrer
      ne dit rien à personne. Sept étapes tenues pour rien, et l'échec arrive
      au tout dernier écran.

    Une garantie que chaque appelant doit se rappeler de respecter n'est pas
    une garantie, c'est une convention — et une garde que personne n'exerce
    peut disparaître dans un refactor sans qu'un seul test rougisse."""

    result = run_node(tmp_path, DOM + DRIVER + """
      const whole={overlay:shellOf(),now,save:async()=>{},setInterval:()=>1,clearInterval:()=>{}};
      const without=key=>{const d=Object.assign({},whole);delete d[key];return d};
      out({
        shipping:refused(()=>K.createCalibration(whole)),
        noOverlay:refused(()=>K.createCalibration(without('overlay'))),
        // Une coque qui n'en est pas une : le refus porte sur la **couture**
        // (`open`), pas sur la présence d'un objet quelconque.
        hollowOverlay:refused(()=>K.createCalibration(Object.assign({},whole,{overlay:{}}))),
        overlayNotCallable:refused(()=>K.createCalibration(Object.assign({},whole,{overlay:{open:'oui'}}))),
        noSave:refused(()=>K.createCalibration(without('save'))),
        saveNotCallable:refused(()=>K.createCalibration(Object.assign({},whole,{save:{}}))),
        // Et le voisin déjà gardé, gardé au même endroit : l'horloge.
        noClock:refused(()=>K.createCalibration(without('setInterval'))),
      });
    """, name="calibDeps")

    assert result["shipping"] is None, "le câblage complet passe : la sonde ne crie pas au loup"
    for case in ("noOverlay", "hollowOverlay", "overlayNotCallable",
                 "noSave", "saveNotCallable", "noClock"):
        assert result[case] == "RangeError", case


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
      const afterRedraw=stepActions(root);

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
/* Des minuteries qu'on peut **declencher a la main**. Le chien de garde de
   l'echeance appartient au parcours (il refuse de se construire sans horloge),
   donc un double inerte le rendrait invisible : ici il est enregistre, donc
   observable et executable. */
const timers=[];
const beat=n=>{for(let i=0;i<(n||1);i+=1)for(const t of timers.slice())if(t)t.fn()};
const clocks=()=>timers.filter(Boolean).map(t=>t.ms);
const calOf=extra=>K.createCalibration(Object.assign({
  overlay:shellOf(),now,engineDefaults:B.DEFAULTS,
  setInterval:(fn,ms)=>{timers.push({fn,ms});return timers.length},
  clearInterval:id=>{if(id>=1&&timers[id-1])timers[id-1]=null},
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
      /* La phrase du récapitulatif est lue **ici**, avant « Appliquer » : elle
         s'écrivait avant `overlay.step()`, qui la remet à zéro, donc elle
         était affichée zéro milliseconde — sur la seule page qui dit à
         l'utilisateur si ses mesures ont servi. */
      const recap=text(flowRoot(),C.DOM.flowNoteClass)[0];
      /* Et la barre est **pleine** : « où en suis-je » est le troisième point
         de la RÈGLE ZÉRO, et une barre laissée à mi-course sur la dernière
         page dit qu'il reste quelque chose à faire. */
      const recapBar=find(flowRoot(),C.DOM.flowProgressClass)[0]
        .children[0].getAttribute('data-at');
      press(flowRoot(),'apply');
      await new Promise(r=>setImmediate(r));
      out({started,steps:visited,recap,recapBar,
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
    assert "mesure(s) retenue(s)" in result["recap"], result["recap"]
    assert "Rien n" in result["recap"], "et que rien n'est écrit sans qu'on le demande"
    assert result["recapBar"] == "1.00", "la barre reste à mi-course sur la page de fin"
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
      const actions=stepActions(flowRoot());
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


# ------------------------------------------ l'échéance quand personne ne nourrit


def test_a_stage_nobody_feeds_still_expires_because_a_clock_watches_it_too(tmp_path):
    """**Deux mécanismes, et c'est la RÈGLE ZÉRO.** `feed()` n'arrive que par la
    couture `deps.onMeasure`, que le contrôleur ne tire qu'en ACTIVE **et
    seulement s'il a observé une main**. L'utilisateur qui sort du cadre ou
    masque l'objectif coupait donc la seule chose qui regardait l'échéance :
    l'étape 1 sur 7 ne se soldait plus (mesuré à 200 000 ms, dix fois
    l'échéance), le compteur restait figé sur « 0 s restantes », et
    `STAGE_REASON.NO_HAND` était **injoignable dans le scénario qui porte son
    nom** — il n'était atteint que par une main mal suivie, c'est-à-dire par une
    main présente.

    Aucun `feed()` n'est appelé ici : seule l'horloge tourne, et c'est tout ce
    dont le chien de garde dispose dans la vraie page."""

    result = run_node(tmp_path, DOM + DRIVER + """
      const cal=calOf({options:{stageHoldMs:300,stageTimeoutMs:5000,
        stageMinSamples:10,pinchRepeats:2,watchdogMs:100}});
      cal.start();
      const at=cal.stepId();
      /* Le chien de garde tourne pendant que l'étape court : il **dit** ce qui
         manque plutôt que de laisser vingt secondes d'écran muet — sans quoi
         « la caméra ne me voit pas » et « le parcours est planté » sont la
         même image. */
      const clocks0=clocks();
      clock+=2000;
      beat();
      const midStep=cal.stepId();
      const said=text(flowRoot(),C.DOM.flowNoteClass)[0];
      // L'échéance passe. Personne n'a nourri le parcours, et il se solde.
      clock+=4000;
      beat();
      const after=cal.stepId();
      const carried=text(flowRoot(),C.DOM.flowNoteClass)[0];
      /* Et il ne se solde qu'**une fois** : un chien de garde qui rejouerait
         l'échéance à chaque tour ferait défiler les sept étapes en sept
         tours. */
      beat(3);
      const idle=cal.stepId();
      // Dix fois l'échéance sans une seule image : le parcours va jusqu'au
      // bout et montre son rapport au lieu de rester sur l'étape 1 sur 7.
      for(let i=0;i<7;i+=1){clock+=6000;beat()}
      const rows=reportRows();
      const duringRun=clocks();
      const actions=stepActions(flowRoot());
      const watchingAtRecap=cal.watching();
      cal.exit('test');
      out({at,midStep,said,after,carried,idle,rows,clocks0,duringRun,actions,
        watchingAtRecap,watching:cal.watching(),afterExit:clocks(),
        noClock:refused(()=>K.createCalibration({overlay:shellOf(),now,save:async()=>{}})),
        watchdogMs:K.DEFAULTS.watchdogMs});
    """, name="noHandExpiry")

    assert result["at"] == "neutral"
    # Pendant l'étape : elle court toujours, et l'écran dit pourquoi.
    assert result["midStep"] == "neutral"
    assert "Aucune main" in result["said"]
    # L'échéance tombe sans une seule image, et le motif est celui qui aide.
    assert result["after"] == "c_pose", "l'étape n'expirait jamais sans image"
    assert "aucune main vue" in result["carried"]
    assert "on continue" in result["carried"].lower(), "décision 31 : le parcours survit"
    # Trois tours de chien de garde de plus ne consomment pas l'étape suivante.
    assert result["idle"] == "c_pose"
    # Et le parcours atteint son rapport : sept étapes, toutes échouées, dites.
    assert [row[1] for row in result["rows"]] == ["jf-failed"] * 7
    assert all("aucune main vue" in row[2] for row in result["rows"][:6]), result["rows"]
    assert result["actions"] == ["apply", "discard"]
    # **L'horloge appartient au parcours**, qui l'ouvre avec lui et la referme
    # avec lui : hors parcours elle n'existe pas (décisions 27 et 30), et un
    # parcours construit sans elle se **refuse**, au lieu de se découvrir
    # devant un utilisateur immobile.
    # Une seule horloge, à la cadence que le parcours a reçue (100 ms ici), et
    # elle est posée dès `start()` — pas à la première image, qui n'arrive
    # jamais dans ce scénario.
    assert result["clocks0"] == [100]
    assert result["duringRun"] == [100], "une seule horloge pour tout le parcours"
    assert result["watchingAtRecap"] is True, "elle tourne tant que le parcours vit"
    assert result["watching"] is False and result["afterExit"] == []
    assert result["noClock"] == "RangeError"
    # Et la cadence livrée reste sous l'échéance qu'elle surveille.
    assert 0 < result["watchdogMs"] < 20000


def test_the_seam_stays_silent_when_the_camera_sees_no_hand_at_all(tmp_path):
    """**La cause exacte du blocage, mesurée sur le vrai contrôleur.** La couture
    ne tire que si `observed.length` : zéro main, et le parcours ne reçoit
    strictement rien — ce n'est pas un `feed()` avec une liste vide, c'est
    l'absence d'appel. Un test qui nourrirait `{hands:[]}` mesurerait un chemin
    que la vraie page n'emprunte jamais, et c'est exactement pour cela que
    vingt-cinq mutations ont manqué le défaut.

    Contrôle : une main **de mauvaise qualité** fait bien tirer la couture. La
    panne est donc « zéro main observée », pas « main inexploitable »."""

    result = run_node(tmp_path, WORLD + """
      const run=async landmarks=>{
        const w=world({result:landmarks
          ?{landmarks:[hand(.65,1.8)],handedness:[[{categoryName:'Left',score:.95}]]}
          :{landmarks:[],handedness:[]}});
        let calls=0,samples=0;
        w.deps.onMeasure=record=>{calls+=1;samples+=record.hands.length};
        const controller=B.createController(w.deps);
        controller.enable();
        await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));
        controller.activate();
        await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));
        w.steps(30);
        return {calls,samples,frames:w.seen(),lifecycle:controller.state()};
      };
      out({empty:await run(false),present:await run(true)});
    """, name="seamsilent")

    # **Trente images, aucun appel** : personne ne regarde l'échéance.
    assert result["empty"]["calls"] == 0
    assert result["empty"]["frames"] > 0, "la boucle tourne pourtant"
    assert result["present"]["calls"] > 0 and result["present"]["samples"] > 0


def test_the_page_cannot_open_a_calibration_without_giving_it_that_clock(tmp_path):
    """**Le module sait expirer ; encore faut-il que la page lui donne l'heure.**
    Un chien de garde posé par l'appelant serait une convention : la page qui
    l'oublie ne s'en apercevrait que devant un utilisateur sorti du cadre, et
    l'écran dirait « 0 s restantes » pour toujours. `createCalibration` **refuse
    donc de se construire sans horloge**, et ce refus est exercé ici sur la
    **vraie** page, dans le **vrai** monde navigateur.

    Le double de navigateur ne peut pas charger MediaPipe, donc la calibration
    s'arrête sur « pas de caméra » — mais le parcours, lui, est construit
    **avant** ce refus. Un code de refus qui nomme la caméra prouve donc que la
    construction est passée ; une page sans horloge lèverait à la place."""

    result = run_browser(tmp_path, CAMERA + browser() + TIMERS + """
      await openTab();
      await BAREHANDS.enable();
      await settle();
      const answer=await BAREHANDS.calibrate();
      const state=BAREHANDS.calibration();
      out({answer,state,measuring:BAREHANDS.measuring(),
        expected:window.JarvisBarehandsCalibration.DEFAULTS.watchdogMs,
        // La page passe bien **une** horloge au parcours, et c'est celle de la
        // fenêtre : une horloge qui ne serait pas celle du navigateur ne
        // tournerait pas dans le produit.
        wired:require('fs').readFileSync(SCRIPT_PATH,'utf8')
          .includes('setInterval:(fn,ms)=>window.setInterval(fn,ms)')});
    """, name="pageclock")

    # Le parcours s'est **construit** — donc la page lui a donné son horloge —
    # puis s'est arrêté sur la caméra, qui est la seule chose qui manque ici.
    assert result["answer"]["code"] == "barehands_calibration_no_camera", (
        "une page sans horloge lèverait à la construction, avant ce refus"
    )
    assert result["wired"] is True
    # Rien ne tourne pour autant : ni la couture d'images, ni l'horloge.
    assert result["state"] == {"running": False, "step": None, "watching": False,
                               "travel": result["state"]["travel"]}
    assert result["measuring"] is False


def test_every_stage_status_is_a_word_the_shell_can_draw(tmp_path):
    """**L'invariant qui ne tenait que par coïncidence.** La coque **refuse**
    désormais un statut hors de `FLOW_STATUS` (Slice 09) — c'est un bon refus,
    il a fermé un mensonge silencieux. Mais la calibration ne passe que parce
    que `STAGE_STATUS` porte exactement les trois mêmes mots, et rien ne le
    disait : une huitième issue d'étape (`unmeasured`, `partial`…) ajoutée au
    contrat ferait **lever la coque au milieu d'un parcours** que l'utilisateur
    a sous les yeux, à l'instant précis où il attend son rapport.

    Une assertion, et l'invariant cesse d'être une coïncidence."""

    result = run_node(tmp_path, DOM + """
      out({stage:C.STAGE_STATUSES,flow:K.FLOW_STATUS,
        /* Et le refus est bien celui qui compte : un mot hors vocabulaire
           lève, il ne se dessine pas sans couleur. */
        drawn:K.FLOW_STATUS.map(status=>{
          const shell=K.createFlowOverlay({document,now});
          shell.open({exit:()=>{}});
          const rows=shell.report([{label:'x',status,detail:'y'}]);
          shell.close();
          return rows;
        }),
        refused:(()=>{
          const shell=K.createFlowOverlay({document,now});
          shell.open({exit:()=>{}});
          const answer=refused(()=>shell.report([{label:'x',status:'unmeasured',detail:'y'}]));
          shell.close();
          return answer;
        })(),
      });
    """, name="statusparity")

    assert set(result["stage"]) <= set(result["flow"]), (
        "un statut d'étape que la coque ne sait pas dessiner la fait lever "
        "au milieu d'un parcours ouvert"
    )
    assert result["drawn"] == [1] * len(result["flow"]), "chaque mot du vocabulaire se dessine"
    assert result["refused"] == "RangeError", "et un mot inconnu lève au lieu de sortir sans couleur"


def test_the_shell_says_which_way_out_served_and_the_flow_logs_that_one(tmp_path):
    """La croix et Échap sont **deux** sorties, et le journal disait « échap »
    pour les deux : le parcours ignorait l'argument que la coque lui passe
    depuis la Slice 09. Une cause fausse dans le journal est pire qu'une cause
    absente — elle se croit."""

    result = run_node(tmp_path, DOM + DRIVER + """
      const said=[];
      const make=()=>calOf({log:(level,message)=>said.push(message)});
      const byCross=make();
      byCross.start();
      allButtons(flowRoot()).find(n=>n.getAttribute('data-flow-close')).fire('click');
      const cross=said.slice(-1)[0];
      said.length=0;
      const byKey=make();
      byKey.start();
      document.fire('keydown',{key:'Escape'});
      out({cross,key:said.slice(-1)[0],
        running:[byCross.isRunning(),byKey.isRunning()]});
    """, name="exitword")

    assert "croix" in result["cross"], f"la croix se journalisait « échap » : {result['cross']}"
    assert "échap" in result["key"]
    assert result["running"] == [False, False], "les deux sorties ferment bien le parcours"


def test_a_run_that_measured_nothing_does_not_claim_to_have_calibrated(tmp_path):
    """**Le profil ne ment plus sur lui-même.** `quality` est une *métrique* —
    le module le dit lui-même — et `deriveProfile` l'écrit pour tout seau de
    main ayant vu une image. Comme `calibrated` se dérivait de *toutes* les
    clés mesurables, une séance dont les sept étapes avaient échoué persistait
    `calibrated: true` : l'onglet affichait « Calibré le … », le toast annonçait
    « Bare Hands utilise vos mesures » — faux —, la branche « sans aucune
    mesure » du journal ne tirait jamais, et « Effacer le profil » s'activait
    pour un profil sans une seule mesure.

    La main est **vue** tout du long (donc `quality` est bien mesurée) et ne
    joue aucune étape : elle ne tient pas la pose, ne pince pas, ne se déplace
    pas, et reste seule. C'est le parcours d'un utilisateur qui regarde
    l'écran sans rien faire — pas une construction de laboratoire."""

    result = run_node(tmp_path, DOM + DRIVER + """
      const cal=calOf();
      cal.start();
      /* Une main immobile mais **pas tenue** (`stillness` sous le seuil), au
         ratio de repos, toujours au même endroit de l'image : aucune étape ne
         peut aboutir, et la portée reste plate — donc rien n'est dérivé. */
      const idle={stillness:.1,primaryRatio:.9,secondaryRatio:.9,cPose:.05,
        xNorm:.42,yNorm:.40};
      const visited=[];
      for(let i=0;i<7;i+=1){
        feed(cal,4,idle);
        clock+=6000;
        cal.feed({now:clock,hands:[hand(idle)]});
        visited.push(cal.stepId());
      }
      const note=text(flowRoot(),C.DOM.flowNoteClass)[0];
      const rows=reportRows();
      press(flowRoot(),'apply');
      await new Promise(r=>setImmediate(r));
      const payload=saved[saved.length-1];
      out({visited,note,rows,payload,
        hands:payload?payload.hands:null,
        calibrated:payload?payload.calibrated:null});
    """, name="nothingmeasured")

    # Les sept étapes ont échoué, et le rapport le dit.
    assert [row[1] for row in result["rows"]] == ["jf-failed"] * 7
    # La qualité **est** mesurée : la main était vue tout du long.
    left = result["hands"]["left"]
    assert left["quality"] is not None, "la métrique existe bien, c'est tout l'objet du défaut"
    # Et aucune mesure qui adapterait le moteur.
    for key in ("pressRatio", "releaseRatio", "secondaryPressRatio", "secondaryReleaseRatio",
                "jitterPx", "travelSlopNorm", "reachNorm"):
        assert left[key] is None, key
    # **Le cœur** : le profil ne se dit pas calibré.
    assert result["calibrated"] is False, (
        "un parcours qui n'a rien mesuré affichait « Calibré » et « Bare Hands "
        "utilise vos mesures »"
    )
    # Et la coque disait l'inverse du profil qu'elle venait de construire.
    assert "Aucune mesure" in result["note"], result["note"]


def payload_of_a_run_where_every_stage_failed(tmp_path) -> dict:
    """La charge utile d'une **vraie** séance dont les sept étapes ont échoué.

    Exportée pour que la route n'ait pas à s'en écrire une à la main : un
    dictionnaire écrit à la main ne porte que les clés auxquelles son auteur a
    pensé, et c'est exactement ainsi que `hands.right.quality` — la clé par
    laquelle `calibrated` devenait vrai sans mesure — a échappé au test qui
    visait ce cas. La séance ci-dessous est jouée par le **vrai** parcours, sur
    la **vraie** coque, et rendue telle que la page l'enverrait.
    """

    return run_node(tmp_path, DOM + DRIVER + """
      const cal=calOf();
      cal.start();
      const idle={stillness:.1,primaryRatio:.9,secondaryRatio:.9,cPose:.05,
        xNorm:.42,yNorm:.40};
      for(let i=0;i<7;i+=1){
        feed(cal,4,idle);
        clock+=6000;
        cal.feed({now:clock,hands:[hand(idle)]});
      }
      press(flowRoot(),'apply');
      await new Promise(r=>setImmediate(r));
      out(saved[saved.length-1]);
    """, name="failedrun")
