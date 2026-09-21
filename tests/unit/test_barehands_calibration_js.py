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
#: Le vocabulaire de dessin des mains (Slice 04). La page le sert **avant** la
#: calibration, qui le lit pour ses démonstrations d'étape et refuse de
#: construire un parcours sans lui ; l'installer ici dans le même ordre est ce
#: qui fait que le double tombe comme la vraie page.
HAND_ART = RUNTIME / "control_center_barehands_hand_art.js"

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
  /* Les démonstrations de main sont des **vrais** SVG de `hand_art` (Slice 06),
     et `handSvg` les crée par `createElementNS`. Un double qui ne le connaît
     pas ne pourrait pas monter la démonstration du tout — et le test dirait
     alors que le dessin manque, au lieu de le regarder. */
  createElementNS(ns,tag){const node=makeNode(tag);node.namespaceURI=String(ns);return node},
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
/* Ce que la scène **montre**, lu sur `data-bh-pose` : l'attribut que
   `hand_art` pose sur chaque SVG précisément pour qu'un test dise quelle main
   est à l'écran sans lire un pixel. */
const deep=root=>{
  const out=[];
  const walk=node=>{out.push(node);for(const child of node.children)walk(child)};
  if(root)walk(root);
  return out;
};
const posesOn=root=>deep(root).map(n=>n.getAttribute('data-bh-pose')).filter(Boolean);
/* Le bandeau de phases : le mot de chaque pastille et son état. C'est la
   moitié « où en suis-je » de la RÈGLE ZÉRO quand il n'y a pas d'échéance. */
const phaseChips=root=>deep(root).filter(n=>n.getAttribute('data-phase'))
  .map(n=>[n.getAttribute('data-phase'),n.getAttribute('data-at')]);
const ghostsOn=root=>deep(root).filter(n=>String(n.className||'')==='jf-ghost')
  .map(n=>[n.style.left,n.style.top,n.getAttribute('data-at')]);
/* Le compteur d'échéance de la coque. Vide veut dire « aucune échéance n'est
   armée », et c'est ce qu'une phase de lecture doit montrer. */
const deadlineText=root=>{
  const meta=deep(root).find(n=>String(n.className||'')==='jf-meta');
  return meta?meta.children.map(c=>c.textContent):null;
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
        f"const ART=require({json.dumps(str(HAND_ART))});\n"
        "global.JarvisBarehandsHandArt=ART;\n"
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
        /* Sous le plafond (0,014) : c'est le milieu qu'on vérifie, pas la borne. */
        marginTooWide:K.deriveTravelSlop(many(20).map(()=>.008),many(20).map(()=>.011),o),
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
    - **`document`** et **le vocabulaire de dessin** (Slice 06) : le parcours
      montre maintenant une démonstration de main à chaque étape. Sans eux, il
      s'ouvrirait sur une consigne écrite au-dessus d'un centre vide, et
      « formez un C » ne dirait jamais lequel — le défaut plausible que ce
      dépôt refuse.

    Une garantie que chaque appelant doit se rappeler de respecter n'est pas
    une garantie, c'est une convention — et une garde que personne n'exerce
    peut disparaître dans un refactor sans qu'un seul test rougisse."""

    result = run_node(tmp_path, DOM + DRIVER + """
      const whole={overlay:shellOf(),now,save:async()=>{},setInterval:()=>1,clearInterval:()=>{},document};
      const without=key=>{const d=Object.assign({},whole);delete d[key];return d};
      /* Le vocabulaire de dessin est un module de **page**, pas une dépendance
         injectée : on le retire donc là où le parcours le lit, c'est-à-dire du
         global, et on le remet aussitôt. */
      const withoutArt=()=>{
        const keep=global.JarvisBarehandsHandArt;
        global.JarvisBarehandsHandArt=undefined;
        try{return refused(()=>K.createCalibration(whole))}
        finally{global.JarvisBarehandsHandArt=keep}
      };
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
        // Slice 06 : ce qu'il faut pour **montrer**.
        noDocument:refused(()=>K.createCalibration(without('document'))),
        hollowDocument:refused(()=>K.createCalibration(Object.assign({},whole,{document:{}}))),
        noHandArt:withoutArt(),
        // Et la dérivation, elle, n'a jamais eu besoin de dessiner : elle reste
        // joignable sans coque, sans horloge et sans vocabulaire de main.
        pureStillPure:typeof K.deriveJitter==='function'&&typeof K.deriveProfile,
      });
    """, name="calibDeps")

    assert result["shipping"] is None, "le câblage complet passe : la sonde ne crie pas au loup"
    for case in ("noOverlay", "hollowOverlay", "overlayNotCallable",
                 "noSave", "saveNotCallable", "noClock",
                 "noDocument", "hollowDocument", "noHandArt"):
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


def strip_js_comments(source: str) -> str:
    """La source **sans ses commentaires**, pour les tests qui lisent le code.

    Ce dépôt commente beaucoup, et en nommant les choses : la calibration
    explique sur plusieurs paragraphes pourquoi elle n'écrit ni `manipulateBox`
    ni `combineCaptures`. Un test qui chercherait ces noms dans le fichier brut
    échouerait donc **sur l'explication elle-même** — et la seule façon de le
    faire passer serait de retirer le commentaire, c'est-à-dire exactement le
    contraire de ce qu'on veut encourager.
    """

    out: list[str] = []
    i, n = 0, len(source)
    while i < n:
        two = source[i:i + 2]
        if two == "/*":
            end = source.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif two == "//":
            end = source.find("\n", i)
            i = n if end < 0 else end
        else:
            out.append(source[i])
            i += 1
    return "".join(out)


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
/* **Le banc d'entrainement**, double (Slice 07). Il rend l'echelle de la scene
   et un journal qu'on remplit a la main : `grab()` ouvre un plan, `nudge()`
   previsualise, `drop()` relache. Ce qu'il ne fait **pas** : de la geometrie.
   Les proprietes geometriques — taille minimale, non-inversion, zones
   compatibles, main perdue — sont prouvees ailleurs, en faisant tourner le
   **vrai** moteur d'interaction contre le **vrai** bac a sable
   (`test_barehands_interaction_js.py`), parce qu'un double qui calculerait la
   geometrie prouverait le double et non le produit. */
const BOX0={x:-32,y:-20,w:64,h:40};
const benchOf=()=>{
  const state={opens:0,closes:0,mounted:null,events:[],live:false,scene:true};
  return {
    state,
    viewport(){return state.scene?{width:1280,height:720,scale:6,cx:640,cy:360}:null},
    open(mount){
      if(!state.scene)return null;
      state.opens+=1;state.mounted=mount;state.live=true;
      return {objectId:'barehands:practice-frame',box:BOX0};
    },
    drain(){const out=state.events;state.events=[];return out},
    close(){const had=state.live;state.live=false;if(had)state.closes+=1;return had},
    /* Ce que le vrai moteur ecrirait dans le journal. */
    grab(){state.events.push({type:'begin',box:BOX0})},
    nudge(box){state.events.push({type:'preview',box:box||BOX0})},
    drop(mode,over){
      const from=BOX0,box=Object.assign({},BOX0,over||{});
      state.events.push({type:'commit',mode,box,from,
        moved:box.x!==from.x||box.y!==from.y,
        sized:box.w!==from.w||box.h!==from.h});
    },
    lose(){state.events.push({type:'cancel',box:BOX0})},
  };
};
/* Le banc de la **derniere** calibration construite : les tests le pilotent par
   ce nom, comme ils pilotent `timers` et `clock`. */
let bench=null;
const calOf=extra=>{
  bench=benchOf();
  return K.createCalibration(Object.assign({
    overlay:shellOf(),now,engineDefaults:B.DEFAULTS,document,
    setInterval:(fn,ms)=>{timers.push({fn,ms});return timers.length},
    clearInterval:id=>{if(id>=1&&timers[id-1])timers[id-1]=null},
    viewport:()=>({width:1280,height:720}),
    practice:bench,
    options:{stageHoldMs:300,stageTimeoutMs:5000,stageMinSamples:10,pinchRepeats:2},
    save:async payload=>{if(failSave.at)throw new Error('le serveur a refuse');saved.push(payload)},
  },extra||{}));
};
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
  while(cal.stepId()===from&&n<(cap||1400)){
    clock+=16;cal.feed({now:clock,hands:[hand(typeof over==='function'?over(n):over)]});n+=1;
  }
  return {from,to:cal.stepId(),frames:n};
};
const pinching=key=>i=>{const o={stillness:.5};o[key]=i%10<5?.15:.6;return o};
/* **Traverser la phase de lecture sans nourrir une seule image** (Slice 06).
   C'est le geste que le produit attend de l'utilisateur pendant qu'il lit :
   les mains sur les genoux. L'horloge avance, le chien de garde bat, et c'est
   lui — et lui seul — qui fait passer l'étape en `ARMED`. */
const readOn=cal=>{clock+=K.DEFAULTS.introMs+1;beat();return cal.phase()};
/* Tenir le verdict jusqu'au bout, puis laisser le parcours avancer. Piloté à
   la main, comme tout le reste : jamais l'horloge murale. */
const verdictOver=cal=>{clock+=K.DEFAULTS.resultMs+1;beat();return cal.stepId()};
/* Passer une étape **pour de bon** : le clic la solde, le verdict se tient,
   puis on avance. Sans la seconde moitié, « passer » laisse le parcours sur la
   même étape et une boucle qui attend le changement tourne pour toujours. */
const skipStep=cal=>{press(flowRoot(),'skip');return verdictOver(cal)};
/* Un point touché : on pince, on relâche. Rendu séparément parce que l'étape
   de visée en demande maintenant trois (décision 24). */
const clickOnce=(cal,over)=>{
  feed(cal,6,Object.assign({primaryRatio:.15},over||{}));
  feed(cal,2,Object.assign({primaryRatio:.6,palmX:623},over||{}));
};
/* Jouer un temps de l'ecran de manipulation : on attrape un bord (ce qui
   **arme** — c'est une vraie prise et non un scalaire), on tire, on relache.
   `mode` est ce que `combineCaptures` aurait conclu ; `over` est ce que
   `manipulateBox` aurait calcule. */
const manipulate=(cal,mode,over)=>{
  bench.grab();cal.tick();
  feed(cal,3,{primaryRatio:.15});
  bench.nudge(Object.assign({},BOX0,over||{}));cal.tick();
  feed(cal,2,{primaryRatio:.6,palmX:700});
  bench.drop(mode,over);
  return cal.tick();
};
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
      /* Viser : la lecture d'abord, **sans une image** — mains sur les genoux,
         ce que l'utilisateur fait pendant qu'il lit — puis trois points, parce
         que la visee est l'exercice spatial (decision 24). */
      readOn(cal);
      const aimShown=cal.aim();
      clickOnce(cal);clickOnce(cal);clickOnce(cal);
      verdictOver(cal);
      visited.push(cal.stepId());
      /* **Manipulation de fenetre** (Slice 07) : un seul ecran, deux temps,
         un seul cadre. 6A l'attrape par un bord d'une main et la deplace ;
         6B reprend la **meme** fenetre par deux zones differentes et la
         redimensionne. Les deux s'arment sur une vraie prise du moteur, pas
         sur un scalaire — c'est `bench.grab()` qui les demarre. */
      readOn(cal);
      const windowScreen={practising:cal.practising(),sub:cal.sub(),
        title:text(flowRoot(),'jf-instruction')[0]};
      manipulate(cal,'move',{x:-10,y:-4});
      verdictOver(cal);
      visited.push(cal.stepId());
      const secondSub=cal.sub();
      readOn(cal);
      bench.grab();cal.tick();
      feedBoth(cal,8);
      bench.drop('resize',{w:96,h:56});
      cal.tick();
      /* Le cadre **survit** au passage de 6A a 6B : une seule ouverture pour
         les deux temps, sinon la fenetre sauterait a sa position de depart
         entre deux gestes. */
      const benchOpens=bench.state.opens;
      verdictOver(cal);
      const benchClosed=bench.state.live===false;
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
      out({started,steps:visited,recap,recapBar,aimShown,
        windowScreen,secondSub,benchOpens,benchClosed,
        beforeApply,afterApply:saved.length,rows,
        payload:saved[0]||null,closed:!flowRoot(),running:cal.isRunning()});
    """, name="fullrun")

    assert result["started"]["ok"] is True
    assert result["started"]["flow"] == "calibration"
    # Slice 07 : **six** exercices, sept écrans (le rapport est le septième),
    # sept étapes mesurées (le sixième écran en porte deux).
    assert result["started"]["steps"] == 6
    assert result["started"]["screens"] == 7
    assert result["started"]["stages"] == 7
    # La suite des étapes **mesurées** traversées est exactement celle d'avant :
    # ce sont les écrans qui ont fusionné, pas les étapes.
    assert result["steps"] == ["neutral", "c_pose", "pinch_primary", "pinch_secondary",
                               "aim", "drag", "resize"]
    # L'écran de manipulation ouvre un vrai cadre, annonce ses deux temps, et
    # n'en ouvre **qu'un** pour les deux.
    assert result["windowScreen"]["practising"] is True
    assert result["windowScreen"]["sub"] == {"at": 0, "total": 2, "id": "drag"}
    assert result["secondSub"] == {"at": 1, "total": 2, "id": "resize"}
    assert result["benchOpens"] == 1, (
        "6B reprend la fenêtre de 6A : la rouvrir la ferait sauter à sa place "
        "de départ entre deux gestes"
    )
    assert result["benchClosed"] is True, "le cadre est démonté en quittant l'écran"
    # Les cibles sont **trois**, et elles ne sont posées qu'une fois la lecture
    # passée (décision 24 : on ne demande pas de viser avant d'avoir lu).
    assert result["aimShown"] == {"points": 3, "hits": 0, "at": 0}
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
      const afterSkip=skipStep(cal);
      /* Viser : trois points. Puis 6A, ou la fenetre est bel et bien deplacee
         d'une main — c'est la moitie « glissement » de la tolerance
         clic/glissement, et elle doit encore aboutir. */
      readOn(cal);clickOnce(cal);clickOnce(cal);clickOnce(cal);verdictOver(cal);
      readOn(cal);
      manipulate(cal,'move',{x:-10,y:-4});
      verdictOver(cal);
      /* 6B : deux zones demandees, une seule main montree. L'echeance ne part
         qu'une fois l'etape **armee** — ici par une vraie prise du cadre, pas
         par un scalaire — et c'est seulement ensuite que la montre descend.
         Le motif dit **ce qui manquait**, pas « temps ecoule ». */
      const before=cal.stepId();
      readOn(cal);
      bench.grab();cal.tick();
      feed(cal,4,{});
      clock+=6000;cal.feed({now:clock,hands:[hand({})]});
      verdictOver(cal);
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
    # Slice 07 : le rapport nomme le **temps** qui a echoue, pas l'ecran. « 6A
    # a marche, 6B non » est ce que l'utilisateur doit pouvoir lire ;
    # « Manipulation de fenetre : echouee » ne dirait pas laquelle des deux.
    assert labels["6A · Déplacer"][0] == "jf-ok"
    assert labels["6B · Redimensionner"][0] == "jf-failed"
    assert "deux mains" in labels["6B · Redimensionner"][1]


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
      /* « Passer » solde l'etape, puis le verdict se tient (Slice 06) : sans
         la seconde moitie, la boucle attendrait un changement d'etape qui
         n'arrive qu'une fois la tenue echue. */
      while(cal.isRunning()&&stepActions(flowRoot()).includes('skip'))skipStep(cal);
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
      /* « Passer » solde l'etape, puis le verdict se tient (Slice 06) : sans
         la seconde moitie, la boucle attendrait un changement d'etape qui
         n'arrive qu'une fois la tenue echue. */
      while(cal.isRunning()&&stepActions(flowRoot()).includes('skip'))skipStep(cal);
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

    **Slice 06 : ce qu'il surveille a changé, pas le fait qu'il surveille.**
    L'échéance ne court plus qu'en phase de mesure, donc une étape que personne
    n'a commencée n'expire plus — elle attend, indéfiniment, et c'est la
    correction demandée. Le chien de garde garde deux emplois, tous deux
    indispensables et tous deux invisibles sans lui : c'est **lui** qui fait
    finir la phase de lecture (personne ne nourrit une étape pendant qu'on la
    lit), et c'est lui qui solde une mesure dont les mains ont disparu.

    Le seul chemin vers `NO_HAND` est donc devenu « se montrer, puis
    disparaître » — et c'est le bon : une étape jamais commencée ne reproche
    rien à personne."""

    result = run_node(tmp_path, DOM + DRIVER + """
      const cal=calOf({options:{stageHoldMs:300,stageTimeoutMs:5000,
        stageMinSamples:10,pinchRepeats:2,watchdogMs:100}});
      cal.start();
      const at=cal.stepId();
      const clocks0=clocks();
      const phase0=cal.phase();
      /* **La lecture finit sur le chien de garde.** Aucune image n'arrive tant
         que l'utilisateur lit — c'est la posture qu'on attend de lui — donc
         rien d'autre ne regarde la montre. */
      clock+=K.DEFAULTS.introMs+1;beat();
      const armed=cal.phase();
      const armedSaid=text(flowRoot(),C.DOM.flowNoteClass)[0];
      const armedMeta=deadlineText(flowRoot());
      /* **Dix fois l'échéance, sans une seule image, et rien ne se passe.**
         L'utilisateur garde les mains sur les genoux : l'étape attend, elle
         n'échoue pas, et le parcours n'a pas avancé d'un pas. */
      for(let i=0;i<10;i+=1){clock+=5000;beat()}
      const idlePhase=cal.phase(),idleStep=cal.stepId();
      const idleMeta=deadlineText(flowRoot());
      const idleReports=reportRows().length;
      /* Maintenant il se montre — l'étape s'arme — puis il retire ses mains. */
      feed(cal,2,{});
      const running=cal.phase();
      const runningMeta=deadlineText(flowRoot());
      clock+=2000;beat();
      const midStep=cal.stepId();
      const said=text(flowRoot(),C.DOM.flowNoteClass)[0];
      // L'échéance passe. Plus personne ne nourrit le parcours, il se solde.
      clock+=4000;beat();
      const after=cal.phase();
      verdictOver(cal);
      const nextStep=cal.stepId();
      const carried=text(flowRoot(),C.DOM.flowNoteClass)[0];
      /* Et il ne se solde qu'**une fois** : un chien de garde qui rejouerait
         l'échéance à chaque tour ferait défiler les sept étapes en sept
         tours. */
      beat(3);
      const idle=cal.stepId();
      /* Les six étapes restantes, chacune montrée puis abandonnée : le parcours
         va jusqu'au bout et montre son rapport. */
      /* Une main qui qualifie l'engagement des **sept** etapes a la fois : elle
         est immobile, son ecart pouce-index est dans la bande du C, et ses deux
         canaux sont fermes. On l'arme, puis on la retire. */
      const ANY={stillness:.9,gapPalms:.65,primaryRatio:.15,secondaryRatio:.15};
      const armThenVanish=()=>{
        clock+=K.DEFAULTS.introMs+1;beat();
        /* **L'ecran de manipulation ne s'arme pas sur un scalaire** (Slice 07) :
           il lui faut une vraie prise du cadre. On la fait, puis on lache
           tout — l'echeance expire alors exactement comme pour les autres, et
           c'est bien le chien de garde qui la solde, sans une image. */
        if(cal.practising()){bench.grab();cal.tick()}
        else feed(cal,2,ANY);
        clock+=6000;beat();
        verdictOver(cal);
      };
      /* Six etapes mesurees restantes apres le repos : les quatre ecrans
         intermediaires, puis les **deux temps** de la manipulation. */
      for(let i=0;i<6;i+=1)armThenVanish();
      const rows=reportRows();
      const duringRun=clocks();
      const actions=stepActions(flowRoot());
      const watchingAtRecap=cal.watching();
      cal.exit('test');
      out({at,phase0,armed,armedSaid,armedMeta,idlePhase,idleStep,idleMeta,idleReports,
        running,runningMeta,midStep,said,after,nextStep,carried,idle,rows,
        clocks0,duringRun,actions,
        watchingAtRecap,watching:cal.watching(),afterExit:clocks(),
        noClock:refused(()=>K.createCalibration({overlay:shellOf(),now,save:async()=>{}})),
        watchdogMs:K.DEFAULTS.watchdogMs});
    """, name="noHandExpiry")

    assert result["at"] == "neutral"
    # Une étape s'ouvre en **lecture**, et la lecture finit sur le chien de garde.
    assert result["phase0"] == "intro"
    assert result["armed"] == "armed"
    # **Aucune échéance n'est annoncée** tant que rien n'est mesuré : la coque
    # compte la séance, elle n'affiche pas de « X s restantes » qui mentirait.
    assert result["armedMeta"][1] == "", result["armedMeta"]
    assert "quand vous voulez" in result["armedSaid"].lower(), result["armedSaid"]
    assert "ne démarre qu" in result["armedSaid"], "elle dit que rien ne se mesure encore"
    # **Dix fois l'échéance sans une image : rien ne descend, rien n'échoue.**
    assert result["idlePhase"] == "armed" and result["idleStep"] == "neutral"
    assert result["idleMeta"][1] == "", "aucun compte à rebours n'a couru"
    assert result["idleReports"] == 0, "et aucune étape n'a été soldée"
    # Une fois armée, la mesure a bien une échéance, et elle s'affiche.
    assert result["running"] == "running"
    assert result["runningMeta"][1].endswith("restantes"), result["runningMeta"]
    # Pendant la mesure : elle court toujours, et l'écran dit ce qui manque.
    assert result["midStep"] == "neutral"
    assert "Aucune main" in result["said"]
    # L'échéance tombe sans une seule image, et le motif est celui qui aide.
    assert result["after"] == "result"
    assert result["nextStep"] == "c_pose", "l'étape armée n'expirait jamais sans image"
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
      /* Il **commence** chaque exercice — sans quoi l'étape l'attendrait
         indéfiniment et n'aurait rien à lui reprocher (Slice 06) — puis ne
         fait rien d'exploitable. Les images sont bien collectées : c'est
         exactement ce qui écrit `quality`. */
      const begin={stillness:.9,gapPalms:.65,primaryRatio:.15,secondaryRatio:.15};
      const visited=[];
      /* Sept etapes mesurees pour six ecrans (Slice 07). Les deux temps de la
         manipulation ne s'arment pas sur un scalaire : la main attrape bien le
         cadre, puis ne le bouge pas — ce qui est exactement « regarder l'ecran
         sans rien faire », sur un exercice qui demande une prise. */
      for(let i=0;i<7;i+=1){
        readOn(cal);
        if(cal.practising()){bench.grab();cal.tick()}
        else feed(cal,2,begin);
        feed(cal,4,idle);
        clock+=6000;
        cal.feed({now:clock,hands:[hand(idle)]});
        verdictOver(cal);
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
      /* Une main qui **commence** chaque exercice — sinon l'étape attendrait
         indéfiniment et la séance ne se terminerait jamais (Slice 06) — puis
         une main qui ne fait rien d'exploitable. Les sept étapes sont donc
         jouées, et les sept échouent. Les images inutiles sont bien collectées :
         c'est ce qui écrit `quality`, la clé par laquelle `calibrated` devenait
         vrai sans la moindre mesure. */
      const begin={stillness:.9,gapPalms:.65,primaryRatio:.15,secondaryRatio:.15};
      const idle={stillness:.1,primaryRatio:.9,secondaryRatio:.9,cPose:.05,
        xNorm:.42,yNorm:.40};
      /* **Sept etapes mesurees pour six ecrans** depuis la Slice 07 : le
         sixieme en porte deux. Les cinq premieres s'arment sur un scalaire ;
         les deux temps de la manipulation s'arment sur une **vraie prise**,
         qu'on simule — et qu'on ne relache jamais, ce qui les fait expirer
         exactement comme une main qui tient sans rien faire. */
      for(let i=0;i<7;i+=1){
        readOn(cal);
        if(cal.practising()){bench.grab();cal.tick()}
        else feed(cal,2,begin);
        feed(cal,4,idle);
        clock+=6000;
        cal.feed({now:clock,hands:[hand(idle)]});
        verdictOver(cal);
      }
      press(flowRoot(),'apply');
      await new Promise(r=>setImmediate(r));
      out(saved[saved.length-1]);
    """, name="failedrun")


# ------------------------------------------------- refonte Slice 05 : la coque
#
# Ce qui suit épingle le **remplacement** de la carte centrée, pas son réglage.
# L'utilisateur a refusé la composition elle-même : une carte de 560 px avec son
# fond, son ombre et son rayon de 20 px, au milieu d'un noir plat. Un test qui
# vérifierait « la carte est plus jolie » raterait le sujet ; ceux-ci vérifient
# qu'il n'y a plus de carte, que le cadre entier est la surface, et que le
# centre est **libre et nommé** pour que les Slices 06 et 07 s'y installent sans
# inventer chacune sa géométrie.


#: La composition refusée, mot pour mot. Ces déclarations **étaient** la carte :
#: si l'une revient dans la feuille, la carte est revenue avec elle.
REJECTED_CARD = (
    "max-width:560px",
    "border-radius:20px",
    "background:rgba(16,22,34,.72)",
    "box-shadow:0 24px 80px rgba(0,0,0,.55)",
)


def test_the_rejected_centred_card_is_gone_and_the_shell_is_the_whole_frame(tmp_path):
    """**Décision 18**, et c'est le cœur de cette slice.

    « Le centre est réservé à l'exercice » ne peut pas être vrai tant qu'une
    boîte de 560 px occupe ce centre. Ce test lit donc deux choses : que les
    quatre déclarations qui *faisaient* la carte ont disparu, et que ce qui les
    remplace occupe le cadre — une grille en trois rangées dont celle du milieu
    est la scène, sans fond, sans bordure et sans ombre à elle.

    Les `none`/`0` explicites de `.jf-step` ne sont pas décoratifs : ils sont la
    seule façon qu'un test distingue « la carte a été retirée » de « la règle a
    été oubliée quelque part ailleurs dans la feuille ».
    """

    result = run_node(tmp_path, DOM + """
      const shell=K.createFlowOverlay({document,now,setInterval:()=>1,clearInterval:()=>{}});
      shell.open({title:'Calibration Bare Hands',exit:()=>{}});
      shell.step({index:2,total:7,title:'Posture de réveil',
        instruction:'Formez un C.',deadlineMs:20000});
      const root=flowRoot();
      const layout=find(root,C.DOM.flowStepClass)[0];
      out({
        style:K.STYLE,
        /* L'arbre : un voile, puis la mise en page. Le voile est une **couche**
           et non un fond de la racine, sans quoi le flou s'appliquerait aussi
           au titre qu'il doit rendre lisible. */
        rootKids:root.children.map(n=>n.className||n.tagName),
        /* Les trois rangées, dans l'ordre : bandeau haut, scène au milieu,
           pied en bas. La scène est la rangée centrale — c'est la décision 19
           lue dans l'arbre et non dans une feuille. */
        layoutKids:layout.children.map(n=>n.className||n.tagName),
        /* Rien de tout cela n'a besoin d'être construit deux fois. */
        oneStage:find(root,C.DOM.flowStageClass).length,
        oneHeader:find(root,C.DOM.flowHeaderClass).length,
        /* Le rapport de fin vit **dans la scène** : à la dernière page il n'y a
           plus d'exercice, donc le centre lui revient. */
        reportInStage:find(find(root,C.DOM.flowStageClass)[0],'jf-report').length,
        /* La scène est **vide** tant qu'une étape n'y a rien monté : c'est le
           sujet de la slice, et une coque qui y dessinerait quelque chose
           d'elle-même reprendrait la place qu'elle vient de libérer. */
        demoEmpty:find(root,C.DOM.flowDemoClass)[0].children.length,
        exerciseEmpty:find(root,C.DOM.flowExerciseClass)[0].children.length,
      });
    """, name="noCard")

    style = result["style"]
    for dead in REJECTED_CARD:
        assert dead not in style, (
            f"« {dead} » faisait la carte centrée que l'utilisateur a refusée ; "
            "elle est revenue dans la feuille."
        )
    # Ce qui remplace la carte occupe le cadre, et le dit explicitement.
    assert "position:fixed;inset:0;z-index:2147482000" in style
    for gone in ("max-width:none", "background:none", "border:0",
                 "border-radius:0", "box-shadow:none"):
        assert gone in style, f"`.jf-step` doit déclarer {gone} : la carte est partie"
    assert "grid-template-rows:auto minmax(0,1fr) auto" in style, (
        "trois rangées, et c'est celle du milieu qui s'étire : le centre est à l'exercice"
    )
    # La coque est une feuille **injectée** : elle ne peut pas hériter du reset
    # de la page. Sans cette ligne, `height:100%` plus une gouttière pousse le
    # pied hors du cadre — et le compteur et la sortie sont dans le pied, donc
    # la RÈGLE ZÉRO dépendrait du reset de l'hôte.
    assert "#jarvisFlow,#jarvisFlow *{box-sizing:border-box}" in style
    assert result["rootKids"] == ["jf-veil", "jf-step"]
    assert result["layoutKids"] == [
        "jf-progress", "jf-close", "jf-header", "jf-stage", "jf-foot",
    ], "bandeau, scène, pied — et la scène est la rangée du milieu"
    assert result["oneStage"] == 1 and result["oneHeader"] == 1
    assert result["reportInStage"] == 1
    assert result["demoEmpty"] == 0 and result["exerciseEmpty"] == 0


def test_the_shell_publishes_five_named_regions_and_refuses_the_two_it_owns(tmp_path):
    """**Le livrable de cette slice**, autant que le dessin.

    Les Slices 06 et 07 montent leur contenu dans cette coque. Sans vocabulaire
    publié, chacune inventerait sa propre géométrie dans le centre laissé libre,
    et « le centre est réservé à l'exercice » redeviendrait une intention.

    Deux régions se **refusent** : `progress` est écrite par `progress()`,
    `controls` par `buttons()`, et les deux sont réécrites à chaque étape. Les y
    laisser monter serait le défaut plausible par excellence — le contenu
    disparaîtrait à l'étape suivante sans un mot, et personne ne saurait
    pourquoi. Le refus **nomme le propriétaire**, donc il enseigne.
    """

    result = run_node(tmp_path, DOM + """
      const shell=K.createFlowOverlay({document,now,setInterval:()=>1,clearInterval:()=>{}});
      /* Fermée, la coque ne rend **pas** de régions et ne se construit pas pour
         l'occasion : une image qui arrive après Échap ne doit pas faire
         réapparaître une surimpression que l'utilisateur vient de quitter. */
      const beforeOpen=shell.regions();
      shell.open({title:'Calibration Bare Hands',exit:()=>{}});
      shell.step({index:1,total:7,title:'Main au repos',instruction:'Ne bougez plus.',
        deadlineMs:20000});
      const root=flowRoot();
      const regions=shell.regions();
      const drawn=name=>{const n=document.createElement('div');n.className='mine-'+name;return n};
      const demo=shell.mount('demo',drawn('demo'));
      const exercise=shell.mount('exercise',drawn('exercise'));
      const extra=shell.mount('feedback',drawn('feedback'));
      out({
        beforeOpen,
        slots:K.FLOW_SLOTS,mountable:K.FLOW_MOUNTABLE,
        /* Les régions publiées sont **les nœuds de l'arbre**, pas des copies :
           deux chemins vers un nœud finissent toujours par diverger. */
        sameNodes:[
          regions.demo===find(root,C.DOM.flowDemoClass)[0],
          regions.exercise===find(root,C.DOM.flowExerciseClass)[0],
          regions.feedback===find(root,C.DOM.flowFeedbackClass)[0],
          regions.progress===find(root,C.DOM.flowProgressClass)[0],
          regions.controls===find(root,C.DOM.flowControlsClass)[0],
          regions.stage===find(root,C.DOM.flowStageClass)[0],
          regions.header===find(root,C.DOM.flowHeaderClass)[0],
        ],
        keys:Object.keys(regions).sort(),
        /* Ce qui est monté est **là où on l'a demandé**. */
        placed:[
          regions.demo.children.map(n=>n.className),
          regions.exercise.children.map(n=>n.className),
          regions.feedback.children.map(n=>n.className),
        ],
        returned:[demo.className,exercise.className,extra.className],
        /* Vider ne retire que ce que le parcours a posé : la ligne de
           commentaire que la coque tient dans `feedback` lui appartient. */
        clearedDemo:shell.clear('demo'),
        afterClear:regions.demo.children.length,
        noteSurvives:regions.feedback.children.map(n=>n.className),
        /* Les deux refus, et un nom inconnu. */
        unknown:refused(()=>shell.mount('milieu',drawn('x'))),
        ownedProgress:refused(()=>shell.mount('progress',drawn('x'))),
        ownedControls:refused(()=>shell.mount('controls',drawn('x'))),
        clearOwned:refused(()=>shell.clear('controls')),
        whyProgress:(()=>{try{shell.mount('progress',drawn('x'))}catch(e){return e.message}})(),
      });
    """, name="regions")

    assert result["beforeOpen"] is None, "une coque fermée n'a pas de régions"
    assert result["slots"] == ["demo", "exercise", "feedback", "progress", "controls"]
    assert result["mountable"] == ["demo", "exercise", "feedback"]
    assert result["keys"] == [
        "controls", "demo", "exercise", "feedback", "header", "progress", "stage",
    ]
    assert all(result["sameNodes"]), "les régions publiées sont les nœuds de l'arbre"
    assert result["placed"] == [
        ["mine-demo"], ["mine-exercise"], ["jf-note", "mine-feedback"],
    ]
    assert result["returned"] == ["mine-demo", "mine-exercise", "mine-feedback"]
    assert result["clearedDemo"] == 1 and result["afterClear"] == 0
    assert result["noteSurvives"] == ["jf-note", "mine-feedback"], (
        "vider « demo » ne touche pas « feedback », et rien ne touche la ligne de la coque"
    )
    assert result["unknown"] == "RangeError"
    assert result["ownedProgress"] == "RangeError"
    assert result["ownedControls"] == "RangeError"
    assert result["clearOwned"] == "RangeError"
    # Le refus **enseigne** : il nomme qui possède la région et ce qui arriverait.
    assert "progress()" in result["whyProgress"] and "buttons()" in result["whyProgress"]


def test_a_new_step_empties_the_stage_the_previous_one_filled(tmp_path):
    """Même règle que les boutons, et pour la même raison.

    Une démonstration qui survivrait à son étape montrerait la main d'une autre
    consigne — et l'utilisateur ferait le geste affiché. C'est pire que de ne
    rien montrer : c'est montrer le faux, ce que la Slice 04 vient justement de
    corriger dans l'aide.
    """

    result = run_node(tmp_path, DOM + """
      const shell=K.createFlowOverlay({document,now,setInterval:()=>1,clearInterval:()=>{}});
      shell.open({title:'Calibration Bare Hands',exit:()=>{}});
      shell.step({index:1,total:7,title:'Main au repos',instruction:'Ne bougez plus.',deadlineMs:20000});
      const node=name=>{const n=document.createElement('div');n.className=name;return n};
      const drawing=node('main-au-repos');
      shell.mount('demo',drawing);
      shell.mount('exercise',node('cible'));
      shell.mount('feedback',node('jauge'));
      shell.note('Gardez la main immobile.','');
      const before={
        demo:shell.regions().demo.children.length,
        exercise:shell.regions().exercise.children.length,
        feedback:shell.regions().feedback.children.map(n=>n.className),
        noteText:find(flowRoot(),C.DOM.flowNoteClass)[0].textContent,
      };
      shell.step({index:2,total:7,title:'Posture de réveil',instruction:'Formez un C.',deadlineMs:20000});
      out({
        before,
        after:{
          demo:shell.regions().demo.children.length,
          exercise:shell.regions().exercise.children.length,
          feedback:shell.regions().feedback.children.map(n=>n.className),
          noteText:find(flowRoot(),C.DOM.flowNoteClass)[0].textContent,
        },
        /* Détaché **pour de vrai** : le double décroche comme le vrai décroche,
           donc un nœud qui traînerait encore dans l'arbre se verrait. */
        handDetached:drawing.parent===null,
        instruction:find(flowRoot(),'jf-instruction')[0].textContent,
      });
    """, name="stageClear")

    assert result["before"]["demo"] == 1 and result["before"]["exercise"] == 1
    assert result["before"]["feedback"] == ["jf-note", "jauge"]
    assert result["before"]["noteText"] == "Gardez la main immobile."
    assert result["after"]["demo"] == 0 and result["after"]["exercise"] == 0
    assert result["after"]["feedback"] == ["jf-note"], (
        "la scène est vidée, et la ligne de commentaire de la coque reste"
    )
    assert result["after"]["noteText"] == ""
    assert result["handDetached"] is True
    assert result["instruction"] == "Formez un C."


def test_green_is_a_brief_recognition_and_never_the_ambient_colour(tmp_path):
    """**Décision 21**, et la leçon de l'ACTIVE vert retiré.

    Le bleu est la consigne ; le vert dit « ce geste vient d'être reconnu ». Une
    couleur de succès qu'on peut laisser allumée cesse de signaler un succès —
    c'est exactement pourquoi l'utilisateur a retiré l'ACTIVE vert, et le même
    instinct vaut ici.

    Il n'existe donc **aucun chemin** qui allume le vert sans échéance : une
    durée absente ou non finie se refuse, une durée trop longue est ramenée au
    plafond publié, le changement d'étape l'éteint, et la fermeture aussi. Le
    vert est lu sur l'horloge injectée, jamais sur l'attribut : « on l'a posé »
    et « il est encore vrai » sont deux faits différents.
    """

    result = run_node(tmp_path, DOM + """
      const shell=K.createFlowOverlay({document,now,setInterval:()=>1,clearInterval:()=>{}});
      shell.open({title:'Calibration Bare Hands',exit:()=>{}});
      shell.step({index:3,total:7,title:'Pincement pouce-index',
        instruction:'Pincez, puis rouvrez.',deadlineMs:20000});
      const root=flowRoot();
      const lit=()=>[root.getAttribute('data-flash'),shell.flashing()];
      const atRest=lit();
      const held=shell.flash(600);
      const justAfter=lit();
      clock+=300;
      shell.note('2 pincement(s) sur 4','');
      const halfway=lit();
      clock+=400;
      /* L'horloge de la coque l'éteint — celle qui peint déjà le compteur, et
         non un minuteur séparé qui pourrait se perdre. */
      shell.progress(.5);
      const expired=lit();
      /* Le plafond : une durée de dosage excessif est ramenée, pas levée. Lever
         au milieu d'une image **réussie** tuerait le parcours pour un geste que
         l'utilisateur a bien fait. */
      const clamped=shell.flash(999999);
      const stillOn=lit();
      /* Le vert ne traverse pas une frontière d'étape : « reconnu » parlait de
         l'étape précédente. */
      shell.step({index:4,total:7,title:'Pincement pouce-majeur',
        instruction:'Même chose avec le majeur.',deadlineMs:20000});
      const afterStep=lit();
      shell.flash(800);
      shell.close();
      out({
        atRest,held,justAfter,halfway,expired,clamped,stillOn,afterStep,
        max:K.FLASH_MAX_MS,
        afterClose:shell.flashing(),
        /* Les refus : sans échéance, le vert deviendrait la couleur ambiante. */
        noDuration:refused(()=>shell.flash()),
        zero:refused(()=>shell.flash(0)),
        negative:refused(()=>shell.flash(-5)),
        infinite:refused(()=>shell.flash(Infinity)),
        notANumber:refused(()=>shell.flash('longtemps')),
        style:K.STYLE,
      });
    """, name="flash")

    assert result["atRest"] == ["", False], "au repos la coque est bleue"
    assert result["held"] == 600
    assert result["justAfter"] == ["ok", True]
    assert result["halfway"] == ["ok", True], "il tient pendant sa durée"
    assert result["expired"] == ["", False], "et il s'éteint tout seul"
    assert result["clamped"] == result["max"] == 2000, (
        "une durée excessive est ramenée au plafond publié, pas acceptée telle quelle"
    )
    assert result["stillOn"] == ["ok", True]
    assert result["afterStep"] == ["", False], "le vert ne traverse pas une étape"
    assert result["afterClose"] is False
    for why in ("noDuration", "zero", "negative", "infinite", "notANumber"):
        assert result[why] == "RangeError", why
    # Tout ce qui verdit est sous l'attribut que seule `flash()` pose, ou bien
    # nomme un statut ponctuel (rapport de fin, note de succès). Il n'existe pas
    # de règle qui rende une surface verte en permanence.
    style = result["style"]
    for line in style.splitlines():
        if "--jf-ok" not in line:
            continue
        assert ("[data-flash=" in line
                or "--jf-ok:#" in line
                or ".jf-ok{" in line
                or '[data-kind="ok"]' in line), (
            f"« {line.strip()} » rend une surface verte hors d'un flash borné, "
            "d'un statut de rapport ou d'une note de succès"
        )


def test_the_veil_keeps_the_jarvis_scene_visible_behind_the_shell(tmp_path):
    """**Décision 18** : « flou translucide plein écran », et « moins noir mort,
    plus atmosphérique » que le fond de modale qui a été refusé.

    Le point technique qui fait la différence : l'assombrissement passe par
    `backdrop-filter: brightness()` et non par une nappe opaque. La scène JARVIS
    garde donc sa **couleur** derrière au lieu d'être recouverte de gris, et la
    nappe posée par-dessus peut rester légère. `saturate` l'empêche de virer au
    gris, la teinte bleue du haut dit que c'est un mode JARVIS et non un voile
    générique.

    Et il reste lisible **sans** `backdrop-filter` : un navigateur qui ne floute
    pas ne doit pas laisser la scène traverser le titre.
    """

    result = run_node(tmp_path, DOM + """
      const shell=K.createFlowOverlay({document,now,setInterval:()=>1,clearInterval:()=>{}});
      shell.open({title:'Calibration Bare Hands',exit:()=>{}});
      const root=flowRoot();
      const veil=find(root,C.DOM.flowVeilClass)[0];
      out({
        style:K.STYLE,
        /* Le voile est une **couche** posée avant la mise en page, donc sous
           elle : un voile qui recouvrirait le titre flouterait ce qu'il doit
           rendre lisible. */
        veilFirst:root.children.indexOf(veil)===0,
        veilHidden:veil.getAttribute('aria-hidden'),
      });
    """, name="veil")

    style = result["style"]
    assert result["veilFirst"] is True
    assert result["veilHidden"] == "true", "le voile n'est pas du contenu"
    # L'assombrissement se fait **sur ce qu'il y a derrière**, pas avec du noir.
    assert "backdrop-filter:blur(18px) saturate(118%) brightness(.76)" in style
    assert "-webkit-backdrop-filter:blur(18px) saturate(118%) brightness(.76)" in style
    # La nappe reste légère : c'est ce qui laisse la scène lisible derrière.
    assert "linear-gradient(180deg,rgba(4,9,16,.52),rgba(3,7,13,.68))" in style
    assert "rgba(6,9,16,.82)" not in style, "le fond de modale refusé, plus noir et plat"
    # Atmosphérique plutôt que plat : une teinte JARVIS et une vignette.
    assert "radial-gradient(120% 86% at 50% -8%,rgba(110,231,255,.13)" in style
    # Le voile n'avale pas les interactions ; c'est la racine qui les capte.
    assert "pointer-events:none" in style
    # Et sans flou, la nappe porte seule la lisibilité.
    assert "@supports not ((backdrop-filter:blur(1px))" in style
    assert "rgba(4,9,16,.92)" in style
    # Le suivi des mains reste **au-dessus** : on calibre avec ses mains.
    hands = BAREHANDS.read_text(encoding="utf-8")
    assert "z-index:2147483000" in hands
    assert "z-index:2147482000" in style
    assert 2147482000 < 2147483000


def test_the_shell_adapts_to_small_frames_and_stays_usable_without_motion(tmp_path):
    """Deux exigences de la slice, et elles se tiennent.

    **Adaptation** : ce n'est pas seulement la largeur. Une fenêtre *basse*
    (paysage de téléphone, moitié d'écran) manque de hauteur, et si le titre
    mangeait la scène l'exercice deviendrait injouable — ce qui est pire que de
    perdre deux tailles de police. Les deux cas ont donc leur palier.

    **Moins de mouvement** : tout ce qui bouge s'arrête, mais ce qui *portait
    l'information* est **remplacé** plutôt que supprimé. La cible ne pulse plus,
    donc elle reçoit un halo fixe plus marqué : une cible qu'on ne trouve pas
    rend l'étape injouable, et « accessible » ne peut pas vouloir dire
    « inutilisable ».
    """

    result = run_node(tmp_path, "out({style:K.STYLE});", name="adapt")
    style = result["style"]

    # --- adaptation en largeur : gouttière de 16 px, titre borné, commandes larges
    assert "@media (max-width:720px){" in style
    phone = style.split("@media (max-width:720px){")[1].split("\n}")[0]
    assert "padding:clamp(22px,5vh,44px) 16px 18px" in phone, "16 px de gouttière"
    assert "font-size:clamp(24px,7.2vw,34px)" in phone, "le titre tient dans le cadre"
    assert "jf-controls" in phone and "flex:1 1 44%" in phone
    # Au doigt, une commande se vise : 44 px de haut (13 px de gouttière
    # verticale plus la ligne), pas les 36 px qui suffisent à la souris.
    assert "padding:13px 18px" in phone
    # Et la croix de sortie ne rétrécit pas : sur un écran tactile, elle est
    # le chemin de sortie le plus direct des trois.
    assert "width:36px;height:36px" not in phone
    # --- adaptation en hauteur : le bandeau cède, la scène garde le centre
    assert "@media (max-height:560px){" in style
    short = style.split("@media (max-height:560px){")[1].split("\n}")[0]
    assert "font-size:clamp(20px,3.6vh,30px)" in short
    assert "padding-top:clamp(14px,3vh,26px)" in short
    # Aucune largeur fixe ne peut déborder le cadre : tout est borné au viewport.
    assert "width:min(580px,92vw)" in style and "max-width:min(960px,94vw)" in style

    # --- moins de mouvement
    assert "@media (prefers-reduced-motion:reduce){" in style
    calm = style.split("@media (prefers-reduced-motion:reduce){")[1].split("\n}")[0]
    for stopped in ("animation:none", "transition:none"):
        assert stopped in calm
    # La cible perd sa pulsation et **gagne** un halo : elle reste trouvable.
    assert "box-shadow:0 0 0 7px rgba(110,231,255,.3)" in calm, (
        "sans pulsation, la cible doit rester repérable autrement"
    )
    # L'entrée en fondu de la coque s'arrête aussi.
    assert "jfEnter" in style


def test_closing_the_shell_releases_every_region_and_every_resource(tmp_path):
    """Échap, la croix et `close()` laissent la page **telle qu'ils l'ont
    trouvée** — et la coque a maintenant plus de choses à rendre qu'avant.

    Ce qui est ajouté à la liste par cette slice : les nœuds que le parcours a
    montés dans la scène, la table des régions, et le vert. Un arbre de parcours
    terminé qu'une table retiendrait en vie est une fuite qu'aucun écran ne
    montre — c'est exactement l'espèce de défaut que ce dépôt veut voir tomber
    dans un test plutôt que dans six mois.
    """

    result = run_node(tmp_path, DOM + """
      const page=document.createElement('div');page.id='page';document.body.appendChild(page);
      const hands=document.createElement('div');hands.id=C.DOM.rootId;document.body.appendChild(hands);
      const cleared=[];
      const exits=[];
      const shell=K.createFlowOverlay({document,now,
        setInterval:()=>77,clearInterval:id=>cleared.push(id)});
      shell.open({title:'Calibration Bare Hands',exit:why=>exits.push(why)});
      shell.step({index:5,total:7,title:'Viser et cliquer',
        instruction:'Amenez le jeton sur le point.',deadlineMs:20000});
      const mine=document.createElement('div');mine.className='cible-dessinee';
      shell.mount('exercise',mine);
      shell.target({x:640,y:446});
      shell.flash(1500);
      const before={
        mounted:mine.parent!==null,
        target:find(flowRoot(),C.DOM.flowTargetClass).length,
        flashing:shell.flashing(),
        inerted:document.body.children.filter(n=>n.inert).map(n=>n.id),
      };
      /* Échap **puis** fermeture : le parcours décide quoi faire d'une sortie,
         la coque ne se referme pas toute seule. */
      document.fire('keydown',{key:'Escape'});
      const closed=shell.close();
      out({
        before,closed,exits,
        clearedTimers:cleared,
        stillAttached:!!flowRoot(),
        mountDetached:mine.parent===null,
        regions:shell.regions(),
        flashing:shell.flashing(),
        open:shell.isOpen(),
        listenersLeft:(document.listeners.keydown||[]).length,
        inertLeft:document.body.children.filter(n=>n.inert).map(n=>n.id),
        /* Fermée, la coque **refuse de dessiner** au lieu de se reconstruire
           sur une page que l'utilisateur vient de quitter. */
        mountAfterClose:shell.mount('demo',document.createElement('div')),
        clearAfterClose:shell.clear('demo'),
        stepAfterClose:shell.step({index:6,total:7,title:'x',instruction:'y'}),
        targetAfterClose:shell.target({x:1,y:2}),
        flashAfterClose:shell.flash(500),
        /* Et elle se rouvre proprement : la table des régions est reconstruite,
           pas ressuscitée. */
        reopened:(()=>{shell.open({title:'Tutoriel Bare Hands',exit:()=>{}});
          const r=shell.regions();
          return {ok:!!r,demoEmpty:r.demo.children.length,
            note:find(flowRoot(),C.DOM.flowNoteClass).length,
            flash:flowRoot().getAttribute('data-flash')}})(),
      });
    """, name="release")

    assert result["before"] == {
        "mounted": True, "target": 1, "flashing": True, "inerted": ["page"],
    }
    assert result["closed"] is True and result["exits"] == ["escape"]
    assert result["clearedTimers"] == [77], "la minuterie du compteur est rendue"
    assert result["stillAttached"] is False
    assert result["mountDetached"] is True, "ce que le parcours a monté est détaché"
    assert result["regions"] is None and result["flashing"] is False
    assert result["open"] is False
    assert result["listenersLeft"] == 0
    assert result["inertLeft"] == [], "la page est réarmée"
    # Fermée, elle refuse — sans lever, parce qu'une image en vol n'est pas une faute.
    assert result["mountAfterClose"] is None
    assert result["clearAfterClose"] == 0
    assert result["stepAfterClose"] is None
    assert result["targetAfterClose"] is None
    assert result["flashAfterClose"] == 0
    # Rouverte : une coque neuve, pas la précédente recollée.
    assert result["reopened"] == {"ok": True, "demoEmpty": 0, "note": 1, "flash": ""}


def test_rule_zero_still_holds_its_four_promises_in_the_new_layout(tmp_path):
    """La carte est partie ; **les quatre promesses restent**.

    C'est la contrainte la plus facile à perdre dans une refonte visuelle : le
    compteur et l'échéance vivaient dans un coin de la carte, et une mise en
    page qui les oublierait rendrait « ça attend » indiscernable de « c'est
    bloqué » — la correction la plus répétée de ce dépôt.

    Les quatre, relues dans la nouvelle mise en page :
      1. que ça tourne — le rail avance et les segments situent l'étape ;
      2. quoi — le titre et la consigne, grands et **hauts** (décision 19) ;
      3. depuis combien de temps — « 12 s » et « 8 s restantes », mot pour mot ;
      4. comment sortir — la croix permanente, au coin de l'**écran** cette
         fois, plus Échap, plus le bouton de l'étape.
    """

    result = run_node(tmp_path, DOM + """
      const exits=[];
      const shell=K.createFlowOverlay({document,now,setInterval:()=>1,clearInterval:()=>{}});
      shell.open({title:'Calibration Bare Hands',exit:why=>exits.push(why)});
      shell.step({index:2,total:7,title:'Posture de réveil',
        instruction:'Formez un C : pouce et index écartés sans se toucher.',deadlineMs:20000});
      const root=flowRoot();
      const header=find(root,C.DOM.flowHeaderClass)[0];
      const layout=find(root,C.DOM.flowStepClass)[0];
      clock+=12000;
      shell.progress(.35);
      const cross=allButtons(root).find(n=>n.getAttribute('data-flow-close')!==null);
      out({
        // 1. que ça tourne
        rail:find(root,C.DOM.flowProgressClass)[0].children[0].style.width,
        dots:find(root,'jf-dots')[0].children.map(n=>n.getAttribute('data-at')),
        // 2. quoi, et **haut** : le bandeau précède la scène dans la grille.
        headerAboveStage:layout.children.indexOf(header)
          <layout.children.indexOf(find(root,C.DOM.flowStageClass)[0]),
        kicker:header.children[0].children[0].textContent,
        title:header.children[1].textContent,
        instruction:header.children[2].textContent,
        // 3. depuis combien de temps — les mots exacts n'ont pas changé.
        clock:find(root,'jf-meta')[0].children.map(n=>n.textContent),
        // 4. comment sortir — trois chemins, dont un que le parcours ne peut effacer.
        crossLabel:cross.getAttribute('aria-label'),
        crossTitle:cross.getAttribute('title'),
        crossGlyph:cross.textContent,
        /* La croix est posée **hors** des commandes : `buttons()` vide les
           commandes à chaque étape, et une sortie qu'un parcours peut effacer
           sans le savoir n'est pas une sortie. */
        crossOutsideControls:find(root,C.DOM.flowControlsClass)[0].children.length===0,
        escape:(()=>{document.fire('keydown',{key:'Escape'});return exits.slice()})(),
        clickCross:(()=>{cross.fire('click');return exits.slice()})(),
        // Le commentaire vivant est **annoncé**, pas seulement dessiné.
        noteLive:find(root,C.DOM.flowNoteClass)[0].getAttribute('aria-live'),
        // Une racine d'accessibilité stable, et le focus qui la suit.
        role:root.getAttribute('role'),modal:root.getAttribute('aria-modal'),
        label:root.getAttribute('aria-label'),tab:root.getAttribute('tabindex'),
      });
    """, name="ruleZero")

    assert result["rail"] == "35%"
    assert result["dots"] == ["done", "now", "next", "next", "next", "next", "next"], (
        "la progression globale situe l'étape sans peser"
    )
    assert result["headerAboveStage"] is True, (
        "titre et consigne **hauts**, au-dessus de la scène (décision 19)"
    )
    assert result["kicker"] == "Étape 2 sur 7"
    assert result["title"] == "Posture de réveil"
    assert result["instruction"].startswith("Formez un C")
    assert result["clock"] == ["12 s", "8 s restantes"], (
        "« ça attend » et « c'est bloqué » doivent rester distinguables"
    )
    assert result["crossLabel"] == "Quitter ce parcours"
    assert result["crossTitle"] == "Quitter (Échap)"
    assert result["crossGlyph"] == "×"
    assert result["crossOutsideControls"] is True
    assert result["escape"] == ["escape"]
    assert result["clickCross"] == ["escape", "fermeture"]
    assert result["noteLive"] == "polite"
    assert result["role"] == "dialog" and result["modal"] == "true"
    assert result["label"] == "Calibration Bare Hands" and result["tab"] == "-1"


# ---------------------------------------- Slice 06 : lire, puis seulement après
#
# Ce qui suit épingle la correction que l'Humain a demandée mot pour mot : « le
# flux actuel commence à chronométrer pendant que l'utilisateur lit. C'est
# refusé. » Avant, une étape ouverte était une étape en cours : les vingt
# secondes partaient à l'affichage du titre, et quelqu'un qui gardait les mains
# sur les genoux échouait à une épreuve qu'il n'avait jamais commencée.
#
# Les cinq phases ne sont pas une décoration : chacune répond à « est-ce que
# quelque chose est en train de me juger en ce moment ? », et une seule répond
# oui.


def test_the_reading_delay_is_deterministic_and_costs_the_measurement_nothing(tmp_path):
    """**La phase de lecture, et le fait qu'elle ne coûte rien** (décision 22).

    Trois choses, et la troisième est celle qui compte :

    - la lecture dure `introMs`, ni plus ni moins, et c'est **l'horloge** qui la
      finit — pas une image, puisque personne n'en envoie pendant qu'on lit ;
    - pendant tout ce temps la coque n'affiche **aucun** compte à rebours, parce
      qu'il n'y en a aucun ;
    - et quand la mesure démarre enfin, elle démarre avec son échéance
      **entière**. C'est la définition littérale de « le temps de lecture n'est
      pas du temps de mesure » : trois secondes de lecture ne retirent pas trois
      secondes à l'exercice.
    """

    result = run_node(tmp_path, DOM + DRIVER + """
      const cal=calOf();
      cal.start();
      const opened={phase:cal.phase(),meta:deadlineText(flowRoot()),
        bar:find(flowRoot(),C.DOM.flowProgressClass)[0].children[0].getAttribute('data-at')};
      /* Une image **pendant** la lecture ne la raccourcit pas, et n'est pas
         mesurée : elle ne fait qu'entretenir l'écran. */
      clock+=Math.round(K.DEFAULTS.introMs/2);
      cal.feed({now:clock,hands:[hand({})]});
      const half={phase:cal.phase(),
        bar:find(flowRoot(),C.DOM.flowProgressClass)[0].children[0].getAttribute('data-at'),
        said:text(flowRoot(),C.DOM.flowNoteClass)[0]};
      // Une milliseconde avant la fin : toujours en lecture.
      clock+=K.DEFAULTS.introMs-Math.round(K.DEFAULTS.introMs/2)-1;beat();
      const justBefore=cal.phase();
      clock+=2;beat();
      const armed=cal.phase();
      /* L'engagement, puis la lecture de l'échéance : elle vaut l'échéance
         **entière**, pas ce qu'il en resterait si elle avait couru pendant la
         démonstration. */
      feed(cal,2,{});
      const running={phase:cal.phase(),meta:deadlineText(flowRoot())};
      out({opened,half,justBefore,armed,running,introMs:K.DEFAULTS.introMs});
    """, name="introDelay")

    # Une étape s'ouvre en lecture, sans échéance et avec une barre à zéro.
    assert result["opened"]["phase"] == "intro"
    assert result["opened"]["meta"][1] == "", "aucun compte à rebours à l'ouverture"
    assert result["opened"]["bar"] == "0.00"
    # À mi-lecture : toujours en lecture, la barre dit où en est **la lecture**,
    # et la phrase dit en toutes lettres que rien n'est mesuré.
    assert result["half"]["phase"] == "intro"
    assert 0.4 < float(result["half"]["bar"]) < 0.6, result["half"]["bar"]
    assert "rien n" in result["half"]["said"].lower()
    assert "mesuré" in result["half"]["said"]
    # Le délai est déterministe : une milliseconde avant, c'est encore la lecture.
    assert result["justBefore"] == "intro"
    assert result["armed"] == "armed"
    # **Et la mesure démarre avec son échéance entière** (5 000 ms ici).
    assert result["running"]["phase"] == "running"
    assert result["running"]["meta"][1] == "5 s restantes", result["running"]["meta"]


def test_an_idle_user_is_never_punished_and_a_passing_hand_never_arms_anything(tmp_path):
    """**Les deux moitiés de la correction**, et elles se tiennent.

    *Rien ne descend tant que l'utilisateur n'a pas commencé.* Mains sur les
    genoux, pendant bien plus de vingt fois l'échéance : l'étape attend, la
    consigne reste, aucune étape n'est soldée.

    *Et « commencer » ne s'attrape pas par accident.* Une main qui passe devant
    l'objectif — elle bouge, elle ne pince pas, son écart pouce-index est celui
    d'une main ouverte — ne qualifie **aucune** des quatre premières étapes.
    Sans cette moitié, le défaut d'origine serait simplement décalé de trois
    secondes : le chronomètre partirait quand même, juste un peu plus tard, et
    sur un geste que l'utilisateur n'a pas fait.
    """

    result = run_node(tmp_path, DOM + DRIVER + """
      const cal=calOf();
      cal.start();
      /* Une main qui **passe** : elle dérive vite (donc elle n'est pas posée),
         ses deux canaux sont grands ouverts (donc elle ne pince pas), et son
         écart pouce-index est celui d'une main ouverte (donc ce n'est pas un
         C). Elle est parfaitement suivie — la qualité est bonne : ce n'est pas
         un défaut de caméra, c'est quelqu'un qui bouge. */
      const wander=i=>({stillness:.05,primaryRatio:.95,secondaryRatio:.95,cPose:0,
        gapPalms:5.94,indexReachPalms:1.9,palmX:380+i*6,
        xNorm:.2+(i%40)*.01,yNorm:.3+(i%30)*.01});
      const seen=[];
      /* Les quatre étapes qui doivent attendre **indéfiniment** : repos, C, et
         les deux pincements (exigence de la slice). */
      for(let s=0;s<4;s+=1){
        readOn(cal);
        const from=cal.stepId();
        /* Vingt fois l'échéance de mesure, avec une main dans le cadre tout du
           long : ni image manquante, ni caméra coupée — juste quelqu'un qui ne
           commence pas. */
        for(let i=0;i<600;i+=1){clock+=160;cal.feed({now:clock,hands:[hand(wander(i))]});beat()}
        seen.push({step:from,after:cal.stepId(),phase:cal.phase(),
          meta:deadlineText(flowRoot()),
          bar:find(flowRoot(),C.DOM.flowProgressClass)[0].children[0].getAttribute('data-at'),
          said:text(flowRoot(),C.DOM.flowNoteClass)[0],
          exits:stepActions(flowRoot()),
          closes:allButtons(flowRoot()).filter(n=>n.getAttribute('data-flow-close')).length,
          reported:reportRows().length});
        skipStep(cal);
      }
      out({seen,open:cal.isRunning()});
    """, name="idleForever")

    assert result["open"] is True, "le parcours est toujours ouvert au bout du compte"
    assert [row["step"] for row in result["seen"]] == [
        "neutral", "c_pose", "pinch_primary", "pinch_secondary"]
    for row in result["seen"]:
        step = row["step"]
        # **Rien n'a bougé** : même étape, toujours armée, jamais soldée.
        assert row["after"] == step, step
        assert row["phase"] == "armed", step
        assert row["reported"] == 0, step
        # Aucun compte à rebours n'a couru, et la barre n'a pas avancé d'un
        # pixel : il n'y avait rien à faire descendre.
        assert row["meta"][1] == "", step
        assert row["bar"] == "0.00", step
        # RÈGLE ZÉRO, quatrième point : deux sorties de parcours plus la croix
        # permanente, à chaque instant de cette attente.
        assert row["exits"] == ["skip", "exit"], step
        assert row["closes"] == 1, step
        # Et la phrase dit ce qu'on attend de lui, sans lui reprocher quoi que
        # ce soit — pas de « aucune main vue » rouge sur quelqu'un qui est là.
        assert "quand vous voulez" in row["said"].lower(), (step, row["said"])
        assert "Aucune main" not in row["said"], step


def test_each_exercise_starts_on_its_own_signal_and_not_on_a_neighbour_s(tmp_path):
    """**« Commencer » veut dire quelque chose de précis, étape par étape.**

    Chaque prédicat ne lit que des scalaires déjà publiés et ne réemploie que
    des seuils qui existent déjà (`band`, recalculée depuis les défauts du
    moteur, et le seuil d'immobilité du maintien) : aucun modèle de geste n'est
    inventé, c'est l'exigence de la slice.

    Le test les prend **par la négative d'abord** : le signal du voisin ne doit
    pas armer. Un pincement pouce-majeur pendant l'étape pouce-index est le cas
    exact où une définition paresseuse de « l'utilisateur a commencé » ferait
    partir la mauvaise mesure sur le bon geste.
    """

    result = run_node(tmp_path, DOM + DRIVER + """
      const cal=calOf();
      cal.start();
      const rows=[];
      /* Par étape : ce qui **ne doit pas** armer, puis ce qui doit. */
      const table=[
        ['neutral',{stillness:.05},{stillness:.9}],
        // Une main ouverte n'est pas un C : son écart est hors bande.
        ['c_pose',{gapPalms:5.94},{gapPalms:.65}],
        // Le majeur qui se ferme n'ouvre pas l'étape du pouce-index.
        ['pinch_primary',{primaryRatio:.9,secondaryRatio:.15},{primaryRatio:.15}],
        // Et réciproquement.
        ['pinch_secondary',{primaryRatio:.15,secondaryRatio:.9},{secondaryRatio:.15}],
        // Viser part sur le pincement primaire (décision 28), pas sur une main
        // qui se promène au-dessus du point.
        ['aim',{primaryRatio:.9,palmX:281,palmY:259},{primaryRatio:.15}],
      ];
      for(const row of table){
        readOn(cal);
        // Bien plus que `engageFrames`, et pourtant rien ne s'arme.
        feed(cal,20,row[1]);
        const wrong={step:cal.stepId(),phase:cal.phase(),
          meta:deadlineText(flowRoot())[1]};
        feed(cal,K.DEFAULTS.engageFrames,row[2]);
        rows.push([row[0],wrong,cal.phase()]);
        skipStep(cal);
      }
      /* **L'ecran de manipulation ne s'arme sur aucun scalaire**, et c'est le
         progres de la Slice 07. Vingt images d'un pincement franc — exactement
         le signal qui armait l'ancienne etape « Faire glisser » — laissent
         l'exercice en attente : pincer dans le vide n'attrape pas de cadre. Ce
         qui l'arme est une **vraie capture** du moteur sur un bord ou un coin,
         c'est-a-dire l'engagement lui-meme et non un indice d'engagement. */
      readOn(cal);
      feed(cal,20,{primaryRatio:.15});
      const windowIdle={step:cal.stepId(),phase:cal.phase(),
        meta:deadlineText(flowRoot())[1]};
      bench.grab();cal.tick();
      const windowArmed={step:cal.stepId(),phase:cal.phase()};
      /* 6B : une seule main **commence** le second temps (sinon le motif
         « deux mains necessaires » serait injoignable), mais ne le reussit
         pas. */
      bench.drop('move',{x:-10});cal.tick();verdictOver(cal);
      const resizeRead={phase:cal.phase(),step:cal.stepId()};
      readOn(cal);
      bench.grab();cal.tick();
      const resize={phase:cal.phase(),step:cal.stepId()};
      out({rows,windowIdle,windowArmed,resizeRead,resize,
        engageFrames:K.DEFAULTS.engageFrames});
    """, name="engagement")

    assert result["engageFrames"] >= 1
    seen = {row[0]: row for row in result["rows"]}
    assert list(seen) == ["neutral", "c_pose", "pinch_primary", "pinch_secondary",
                          "aim"]
    for step, row in seen.items():
        # Vingt images du mauvais signal : l'étape attend toujours, et aucune
        # échéance n'a été armée derrière son dos.
        assert row[1]["phase"] == "armed", step
        assert row[1]["step"] == step, step
        assert row[1]["meta"] == "", step
        # Le bon signal, lui, démarre la mesure — et il suffit d'`engageFrames`.
        assert row[2] == "running", step
    # **Slice 07 : l'écran de manipulation lit une capture, pas un scalaire.**
    # Vingt images d'un pincement franc — le signal qui armait l'ancienne étape
    # « Faire glisser » — ne l'arment pas, et aucune échéance n'est partie
    # derrière le dos de l'utilisateur.
    assert result["windowIdle"] == {"step": "drag", "phase": "armed", "meta": ""}
    # Une vraie prise du cadre, elle, démarre la mesure immédiatement : il n'y a
    # pas de seuil à franchir, parce que le moteur n'ouvre un plan que lorsque
    # la main tient réellement un bord ou un coin.
    assert result["windowArmed"] == {"step": "drag", "phase": "running"}
    # 6B s'ouvre sur sa propre lecture, sans repasser par un nouvel écran…
    assert result["resizeRead"] == {"phase": "intro", "step": "resize"}
    # …et une seule main suffit à la **commencer** ; c'est la mesure qui en
    # exige deux, et son échec le dira.
    assert result["resize"] == {"phase": "running", "step": "resize"}


def test_the_two_pinches_never_look_alike_and_never_answer_for_each_other(tmp_path):
    """**Décision 26, les étapes 3 et 4.** « Même grammaire, autre doigt » n'a
    de valeur que si la différence se voit et s'applique.

    À l'écran, les deux étapes montrent deux **silhouettes** différentes : le
    pouce-index laisse le majeur dressé au-dessus du geste, le pouce-majeur
    replie l'index et n'a plus aucun doigt levé. Ce sont des postures du
    vocabulaire partagé (`hand_art`), lues ici par l'attribut que ce module pose
    précisément pour ça — `data-bh-pose` —, donc sans lire un seul pixel.

    Dans la logique, chaque étape ne compte que **son** canal : pincer du majeur
    pendant l'étape du pouce-index ne doit ni l'armer ni la faire avancer d'une
    répétition. Sinon le profil recevrait des seuils mesurés sur l'autre doigt,
    et le clic droit de l'utilisateur deviendrait son clic gauche.
    """

    result = run_node(tmp_path, DOM + DRIVER + """
      const cal=calOf();
      cal.start();
      feedUntil(cal,{});                                   // repos
      feedUntil(cal,{cPose:.9,secondaryRatio:.9});         // C
      // --- étape 3, pouce-index
      const primary={step:cal.stepId(),poses:posesOn(flowRoot())};
      readOn(cal);
      // Le majeur pince en boucle : ce n'est pas l'étape, rien ne doit bouger.
      feed(cal,60,i=>({secondaryRatio:i%10<5?.15:.6,primaryRatio:.9}));
      primary.afterWrongFinger={phase:cal.phase(),step:cal.stepId()};
      feedUntil(cal,pinching('primaryRatio'));
      // --- étape 4, pouce-majeur
      const secondary={step:cal.stepId(),poses:posesOn(flowRoot())};
      readOn(cal);
      feed(cal,60,i=>({primaryRatio:i%10<5?.15:.6,secondaryRatio:.9}));
      secondary.afterWrongFinger={phase:cal.phase(),step:cal.stepId()};
      feedUntil(cal,pinching('secondaryRatio'));
      out({primary,secondary,next:cal.stepId()});
    """, name="twoPinches")

    assert result["primary"]["step"] == "pinch_primary"
    assert result["secondary"]["step"] == "pinch_secondary"
    # **Deux dessins, deux silhouettes** : aucune posture n'est partagée.
    assert result["primary"]["poses"] == ["pinch_primary_open", "pinch_primary_closed"]
    assert result["secondary"]["poses"] == ["pinch_secondary_open", "pinch_secondary_closed"]
    assert not set(result["primary"]["poses"]) & set(result["secondary"]["poses"])
    # Et le doigt de l'autre étape n'arme rien, même répété soixante images.
    assert result["primary"]["afterWrongFinger"] == {"phase": "armed", "step": "pinch_primary"}
    assert result["secondary"]["afterWrongFinger"] == {"phase": "armed", "step": "pinch_secondary"}
    # Le bon doigt, lui, fait avancer le parcours jusqu'à la visée.
    assert result["next"] == "aim"


def test_the_target_step_shows_its_points_only_after_the_reading_and_counts_real_pinches(tmp_path):
    """**Décisions 24 et 28, l'étape 5.**

    Les points n'apparaissent qu'une fois la consigne lue : demander de viser
    sous une phrase qu'on est en train de lire, c'est demander de viser avant
    d'avoir lu. Ils sont **répartis sur la surface utile** — c'est l'exercice
    spatial, et un seul point toujours au même endroit enseignerait « pincer »
    au lieu de « viser et cliquer ».

    Et ce qui compte est un **pincement pouce-index** réel, pas une main qui
    passe au-dessus : la démonstration montre une main qui pince une mire, et
    l'exercice mesure exactement ce qu'elle montre.
    """

    result = run_node(tmp_path, DOM + DRIVER + """
      const cal=calOf();
      cal.start();
      feedUntil(cal,{});
      feedUntil(cal,{cPose:.9,secondaryRatio:.9});
      feedUntil(cal,pinching('primaryRatio'));
      feedUntil(cal,pinching('secondaryRatio'));
      const at=cal.stepId();
      /* Pendant la lecture : la démonstration est là, **les points ne sont pas
         posés**. */
      const reading={phase:cal.phase(),poses:posesOn(flowRoot()),
        live:find(flowRoot(),C.DOM.flowTargetClass).length,
        ghosts:ghostsOn(flowRoot()).map(g=>g[2])};
      readOn(cal);
      const ready={live:find(flowRoot(),C.DOM.flowTargetClass).length,
        ghosts:ghostsOn(flowRoot()),aim:cal.aim()};
      /* Une main qui se promène **sur** le point sans pincer ne vaut rien :
         ni armement, ni point marqué. */
      for(let i=0;i<40;i+=1){clock+=16;
        cal.feed({now:clock,hands:[hand({primaryRatio:.9,palmX:281,palmY:259})]})}
      const hovered={phase:cal.phase(),aim:cal.aim()};
      clickOnce(cal);
      const first={aim:cal.aim(),step:cal.stepId(),
        ghosts:ghostsOn(flowRoot()).map(g=>g[2]),
        live:find(flowRoot(),C.DOM.flowTargetClass)[0].style.left};
      clickOnce(cal);clickOnce(cal);
      const done={phase:cal.phase(),aim:cal.aim()};
      verdictOver(cal);
      out({at,reading,ready,hovered,first,done,after:cal.stepId(),
        spots:K.AIM_SPOTS,targets:K.DEFAULTS.aimTargets});
    """, name="aimField")

    assert result["at"] == "aim"
    # Pendant la lecture : la main qui **pince une mire** est montrée
    # (décision 28 — jamais un index tendu), et aucun point n'est posé.
    assert result["reading"]["phase"] == "intro"
    assert result["reading"]["poses"] == ["pinch_primary_open", "pinch_target"]
    assert result["reading"]["live"] == 0, "aucune cible sous une consigne qu'on lit"
    assert result["reading"]["ghosts"] == ["next", "next", "next"]
    # Une fois lu : un point vivant, et les autres annoncés.
    assert result["ready"]["live"] == 1
    assert result["ready"]["aim"] == {"points": 3, "hits": 0, "at": 0}
    assert [g[2] for g in result["ready"]["ghosts"]] == ["now", "next", "next"]
    # **Répartis sur la surface utile**, et pas trois fois au même endroit.
    xs = [int(g[0][:-2]) for g in result["ready"]["ghosts"]]
    ys = [int(g[1][:-2]) for g in result["ready"]["ghosts"]]
    assert len(set(xs)) == 3 and len(set(ys)) > 1, (xs, ys)
    assert min(xs) < 1280 * 0.3 and max(xs) > 1280 * 0.7, xs
    assert all(0.2 * 720 < y < 0.85 * 720 for y in ys), ys
    # Survoler n'est pas cliquer : quarante images au-dessus du point, et
    # l'étape attend toujours.
    assert result["hovered"] == {"phase": "armed", "aim": {"points": 3, "hits": 0, "at": 0}}
    # Un pincement réel marque le point, et le suivant s'allume.
    assert result["first"]["aim"] == {"points": 3, "hits": 1, "at": 1}
    assert result["first"]["step"] == "aim", "un point touché n'est pas l'étape finie"
    assert result["first"]["ghosts"] == ["done", "now", "next"]
    assert result["first"]["live"] == "%dpx" % round(1280 * 0.78)
    # Les trois points faits, l'étape rend son verdict puis avance.
    assert result["done"]["phase"] == "result"
    assert result["done"]["aim"]["hits"] == 3
    assert result["after"] == "drag"
    assert result["targets"] == 3 and len(result["spots"]) == 3


def test_every_step_shows_the_shared_hand_and_never_two_instructions_at_once(tmp_path):
    """**Décision 20 et architecture §8.** Les mains de la calibration sont
    celles du vocabulaire partagé — pas un second jeu de dessins qui dériverait
    au premier ajustement, avec pour symptôme un utilisateur qui ne reconnaît
    pas, dans la calibration, la main qu'il a apprise dans l'aide.

    Trois faits, et le deuxième a déjà coûté cher à ce dépôt : la démonstration
    vit dans la région `demo` que la coque publie ; elle **ne survit pas à son
    étape** (une main d'une autre consigne fait faire le mauvais geste) ; et
    elle n'est que de la présentation — elle ne traverse jamais `feed()` et
    n'atteint aucun profil.
    """

    result = run_node(tmp_path, DOM + DRIVER + """
      const cal=calOf();
      cal.start();
      const shown=[];
      const record=()=>shown.push({step:cal.stepId(),
        poses:posesOn(flowRoot()),
        inDemo:posesOn(find(flowRoot(),C.DOM.flowDemoClass)[0]),
        labelled:deep(flowRoot()).filter(n=>n.getAttribute('aria-label')
          &&String(n.className||'')==='jf-mime').length,
        captions:text(flowRoot(),'jf-caption'),
        strokes:deep(flowRoot()).filter(n=>n.getAttribute('data-bh-pose'))
          .map(n=>n.getAttribute('stroke')),
        mime:deep(flowRoot()).filter(n=>String(n.className||'')==='jf-mime')
          .map(n=>n.getAttribute('data-mime')),
        /* Slice 07 : deux mains se posent **cote a cote** au lieu d'etre
           empilees, et la gauche est la droite en miroir. */
        pair:deep(flowRoot()).filter(n=>String(n.className||'')==='jf-mime')
          .map(n=>n.getAttribute('data-pair')),
        mirrors:deep(flowRoot()).filter(n=>n.getAttribute('transform')).length,
        aside:deep(flowRoot()).filter(n=>String(n.className||'').includes('jf-demo-aside')).length});
      for(let i=0;i<7;i+=1){record();skipStep(cal)}
      const atRecap={poses:posesOn(flowRoot()),step:cal.stepId()};
      press(flowRoot(),'apply');
      await new Promise(r=>setImmediate(r));
      out({shown,atRecap,payload:saved[0]||null,
        styleSheets:[!!document.getElementById(C.DOM.flowStyleId),
                     !!document.getElementById(C.DOM.flowStepsStyleId)],
        separate:C.DOM.flowStyleId!==C.DOM.flowStepsStyleId});
    """, name="demos")

    poses = {row["step"]: row["poses"] for row in result["shown"]}
    assert poses["neutral"] == ["rest"]
    assert poses["c_pose"] == ["wake_c"], "décision 27 : pouce + index forment le C"
    assert poses["pinch_primary"] == ["pinch_primary_open", "pinch_primary_closed"]
    assert poses["pinch_secondary"] == ["pinch_secondary_open", "pinch_secondary_closed"]
    assert poses["aim"] == ["pinch_primary_open", "pinch_target"]
    # **Slice 07, et aucune posture nouvelle.** Saisir un bord, c'est pincer :
    # 6A est le mime du pincement primaire. 6B est le **même** pincement, deux
    # fois, dont une en miroir — ce qui est littéralement ce que fait
    # l'utilisateur. L'alphabet de `hand_art` n'a pas eu à s'allonger.
    assert poses["drag"] == ["pinch_primary_open", "pinch_primary_closed"]
    assert poses["resize"] == ["pinch_primary_closed", "pinch_primary_closed"]
    shown = {row["step"]: row for row in result["shown"]}
    # Deux mains se posent côte à côte, jamais empilées : empilées, elles se
    # liraient comme une seule main qui bouge, l'inverse du geste demandé.
    assert shown["resize"]["pair"] == ["1"] and shown["resize"]["mime"] == ["0"]
    assert shown["drag"]["pair"] == ["0"] and shown["drag"]["mime"] == ["1"]
    # La gauche est la droite retournée : un `<g>` de miroir, pas une huitième
    # posture.
    assert shown["resize"]["mirrors"] == 1, "une seule des deux mains est en miroir"
    assert shown["aim"]["mirrors"] == 0
    # Et pendant l'exercice de fenêtre la démonstration se range dans un coin :
    # le centre appartient au cadre, qui **est** l'exercice.
    assert shown["drag"]["aside"] == 1 and shown["resize"]["aside"] == 1
    assert shown["aim"]["aside"] == 0
    for row in result["shown"]:
        # **Une seule main à l'écran à la fois** : la démonstration ne survit
        # pas à l'étape qui l'a posée, et elle vit dans la région `demo`.
        assert row["inDemo"] == row["poses"], row["step"]
        # Elle trace en `currentColor` : c'est le crochet de la scène, donc le
        # bleu de la consigne et le vert bref d'une réussite sans une ligne de
        # plus.
        assert set(row["strokes"]) <= {"currentColor"}, row["step"]
        if row["poses"]:
            # Annoncée une fois, sur le groupe — pas deux fois pour deux images
            # du même geste.
            assert row["labelled"] == 1, row["step"]
            assert len(row["captions"]) == 1, row["step"]
            # Deux postures s'alternent, sauf quand ce sont deux **mains**
            # posées côte à côte (Slice 07) : celles-là ne s'alternent pas.
            expected = "1" if len(row["poses"]) == 2 and row["pair"] == ["0"] else "0"
            assert row["mime"] == [expected], row["step"]
    # Le récapitulatif ne montre aucune main : il n'y a plus de geste à faire.
    assert result["atRecap"] == {"poses": [], "step": None}
    # **La démonstration n'est jamais une entrée** : sept étapes passées, donc
    # rien de mesuré, et le profil le dit — une main dessinée n'en est pas une.
    assert result["payload"]["calibrated"] is False
    for handedness, hand in result["payload"]["hands"].items():
        assert all(value is None for value in hand.values()), (handedness, hand)
    # Deux feuilles, deux propriétaires : la coque ne sait rien des exercices.
    assert result["styleSheets"] == [True, True]
    assert result["separate"] is True


def test_rule_zero_survives_a_phase_that_has_no_deadline_to_announce(tmp_path):
    """**La question que cette slice pose à la RÈGLE ZÉRO.**

    La règle demande, à tout instant : que quelque chose tourne, quoi, depuis
    combien de temps, et comment en sortir — et elle interdit un état qui dure
    pour toujours. `ARMED` n'a **pas d'échéance**, et c'est exprès : en poser
    une serait un compte à rebours contre quelqu'un qui n'a rien commencé.

    La règle tient quand même, et autrement :

    1. *ça tourne* — le bandeau de phases montre « Prêt » allumé, et la
       démonstration continue de mimer le geste ;
    2. *quoi* — le titre, la consigne, et une phrase qui dit exactement ce qu'il
       faut faire pour démarrer ;
    3. *depuis combien de temps* — le compteur de séance de la coque continue de
       compter ; ce qui disparaît est le compte à rebours de **mesure**, parce
       qu'il n'y a pas de mesure ;
    4. *comment en sortir* — « Passer cette étape », « Quitter », la croix
       permanente, Échap.

    Et l'interdiction de l'état sans fin est respectée par sa raison d'être :
    `ARMED` n'est pas un état de travail. Rien n'y tourne qui puisse se coincer,
    et l'utilisateur en sort par ses propres commandes, à tout moment.
    """

    result = run_node(tmp_path, DOM + DRIVER + """
      const cal=calOf();
      cal.start();
      const snap=()=>({phase:cal.phase(),chips:phaseChips(flowRoot()),
        meta:deadlineText(flowRoot()),
        said:text(flowRoot(),C.DOM.flowNoteClass)[0],
        exits:stepActions(flowRoot()),
        closes:allButtons(flowRoot()).filter(n=>n.getAttribute('data-flow-close')).length,
        demo:posesOn(flowRoot()).length});
      const reading=snap();
      readOn(cal);
      const armedAt=snap();
      clock+=30000;beat();
      const armedLater=snap();
      feed(cal,2,{});
      const running=snap();
      document.fire('keydown',{key:'Escape'});
      out({reading,armedAt,armedLater,running,escape:!flowRoot()});
    """, name="ruleZeroArmed")

    reading = result["reading"]
    armed, later, running = result["armedAt"], result["armedLater"], result["running"]
    # 1 — ça tourne, et on voit **quelle** étape du geste est en cours.
    assert reading["chips"] == [["intro", "now"], ["armed", "next"], ["running", "next"]]
    assert armed["chips"] == [["intro", "done"], ["armed", "now"], ["running", "next"]]
    assert running["chips"] == [["intro", "done"], ["armed", "done"], ["running", "now"]]
    # La démonstration est là dans les trois phases : c'est le mouvement qui
    # remplace le compte à rebours pendant l'attente.
    assert reading["demo"] and armed["demo"] and running["demo"]
    # 2 — ce qu'il faut faire, en français, et sans reproche.
    assert "quand vous voulez" in armed["said"].lower(), armed["said"]
    assert "posez une main ouverte" in armed["said"]
    # 3 — le compteur de séance continue ; le compte à rebours de **mesure**
    # n'apparaît qu'avec la mesure.
    assert armed["meta"][0].endswith(" s") and armed["meta"][1] == ""
    assert int(later["meta"][0].split(" ")[0]) > int(armed["meta"][0].split(" ")[0]), (
        "le compteur de séance avance pendant l'attente : « ça attend » reste vivant"
    )
    assert later["meta"][1] == "", "et toujours aucune échéance à annoncer"
    assert running["meta"][1].endswith("restantes"), running["meta"]
    # 4 — trois sorties, à chaque instant, y compris pendant l'attente sans fin.
    for row in (reading, armed, later, running):
        assert row["exits"] == ["skip", "exit"] and row["closes"] == 1, row["phase"]
    # Et Échap sort vraiment.
    assert result["escape"] is True


# ------------------------------------ Slice 07 : l'écran de manipulation
#
# Ce que la calibration doit tenir, et qui n'est pas de la géométrie : ouvrir un
# vrai cadre au bon moment, le démonter sur **tous** les chemins de sortie, et
# refuser honnêtement quand il n'y a pas de vraie fenêtre à manipuler.


def test_the_window_screen_is_one_screen_with_two_arming_moments(tmp_path):
    """**Un écran, deux temps, un seul cadre** (décisions 26 et 29).

    Ce que ce test surveille est le **passage** de 6A à 6B, parce que c'est là
    que l'implémentation paresseuse serait visible : repasser par
    `overlay.step()` pour changer la consigne viderait la scène, donc le cadre
    que l'utilisateur tient des yeux, et le ferait sauter à sa place de départ
    entre deux gestes.

    Trois faits, donc : le titre de l'écran ne change pas, la consigne du temps
    **si**, et le cadre n'est ouvert qu'une fois pour les deux. Plus la règle
    des phases : chaque temps a sa propre lecture, et chacun arme sa mesure
    lui-même sans redessiner l'écran (`overlay.deadline()`, Slice 06).
    """

    result = run_node(tmp_path, DOM + DRIVER + """
      const cal=calOf();
      cal.start();
      for(let i=0;i<5;i+=1)skipStep(cal);
      const shot=()=>({step:cal.stepId(),phase:cal.phase(),sub:cal.sub(),
        title:text(flowRoot(),'jf-instruction')[0],
        heading:deep(flowRoot()).filter(n=>n.tagName==='H2')[0].textContent,
        say:text(flowRoot(),'jf-sub-say')[0],
        rail:deep(flowRoot()).filter(n=>n.getAttribute('data-sub'))
          .map(n=>[n.getAttribute('data-sub'),n.getAttribute('data-at')]),
        meta:deadlineText(flowRoot())[1],
        opens:bench.state.opens});
      /* Lecture de 6A : aucune echeance, et le cadre n'est pas encore la —
         decision 25, meme regle que les cibles. */
      const reading=shot();
      const mountedDuringReading=bench.state.live;
      readOn(cal);
      const armedA=shot();
      bench.grab();cal.tick();
      const runningA=shot();
      bench.drop('move',{x:-10,y:-4});cal.tick();
      const resultA=shot();
      verdictOver(cal);
      /* 6B : nouvelle lecture, meme ecran, meme cadre. */
      const readingB=shot();
      readOn(cal);
      const armedB=shot();
      bench.grab();cal.tick();
      const runningB=shot();
      out({reading,mountedDuringReading,armedA,runningA,resultA,
        readingB,armedB,runningB,
        /* Le cadre est monte dans la region `exercise` de la coque, celle que
           la Slice 05 a reservee a l'exercice — pas dans `demo`, pas dans
           `feedback`, et surtout pas dans une region qui appartient a la coque. */
        mountedIn:bench.state.mounted
          &&String(bench.state.mounted.className||''),
        timeoutMs:5000});
    """, name="windowScreen")

    # **La lecture d'abord, et rien ne descend.** Le cadre n'apparaît qu'à la
    # fin de la lecture : posé pendant qu'on lit, il serait saisi avant que la
    # consigne soit finie.
    assert result["reading"]["phase"] == "intro"
    assert result["reading"]["meta"] == "", "aucune échéance pendant la lecture"
    assert result["mountedDuringReading"] is False, (
        "le cadre est apparu au milieu d'une phrase"
    )
    assert result["armedA"]["phase"] == "armed" and result["armedA"]["opens"] == 1

    # **Premier moment d'armement** : une vraie prise, et la montre part.
    assert result["runningA"]["phase"] == "running"
    assert result["runningA"]["meta"].endswith("s restantes"), result["runningA"]["meta"]
    assert result["resultA"]["phase"] == "result"

    # **Le passage à 6B ne redessine pas l'écran.** Même titre, même consigne
    # d'écran, même cadre — seule la phrase du temps change.
    assert result["readingB"]["heading"] == result["reading"]["heading"]
    assert result["readingB"]["title"] == result["reading"]["title"]
    assert result["readingB"]["opens"] == 1, (
        "6B a rouvert le cadre : la fenêtre aurait sauté à sa place de départ"
    )
    assert result["readingB"]["say"] != result["reading"]["say"], (
        "la consigne du temps doit changer, sinon 6B demande le geste de 6A"
    )
    assert "deux zones" in result["readingB"]["say"]

    # Le rail dit lequel des deux temps est en cours, et qu'il en reste un.
    assert result["reading"]["rail"] == [["drag", "now"], ["resize", "next"]]
    assert result["readingB"]["rail"] == [["drag", "done"], ["resize", "now"]]

    # **6B a sa propre lecture et son propre armement.** Sans la seconde
    # lecture, le second temps démarrerait sa montre sur quelqu'un qui n'a pas
    # encore lu ce qu'on lui demande de différent.
    assert result["readingB"]["phase"] == "intro" and result["readingB"]["meta"] == ""
    assert result["armedB"]["phase"] == "armed" and result["armedB"]["meta"] == ""
    assert result["runningB"]["phase"] == "running"
    assert result["runningB"]["meta"].endswith("s restantes")

    # Et le cadre vit dans la région que la Slice 05 a réservée à l'exercice.
    assert "jf-exercise" in result["mountedIn"]


def test_a_scene_that_is_off_skips_the_window_step_and_names_why(tmp_path):
    """**Divergence D4, et c'est un refus assumé.**

    La calibration n'avait aucune dépendance à la scène avant cette slice ;
    l'étape de manipulation lui en donne une, parce qu'elle emprunte son
    **échelle** pour que le geste appris soit celui qui marchera. Scène
    éteinte, cette échelle vaut `null`, et les deux replis possibles sont des
    défauts plausibles : une échelle inventée fait partir le cadre six fois
    trop loin, un faux cadre fait « réussir » une étape qui n'a pas mesuré le
    vrai geste.

    Ce que ce dépôt fait à la place est écrit dans son contrat fondateur — « un
    refus codé plutôt qu'un défaut plausible » : les deux temps sont **passés**
    (pas ratés : l'utilisateur n'a rien manqué), avec un motif **nommé** ajouté
    à la liste fermée, et le parcours continue jusqu'au rapport.

    Trois façons de ne pas avoir de fenêtre, et **une seule réponse**, parce
    qu'elles disent la même chose à l'utilisateur : scène éteinte, banc absent,
    banc qui refuse d'ouvrir.
    """

    result = run_node(tmp_path, DOM + DRIVER + """
      const play=cal=>{
        cal.start();
        for(let i=0;i<5;i+=1)skipStep(cal);
        const atWindow={step:cal.stepId(),phase:cal.phase(),
          note:text(flowRoot(),C.DOM.flowNoteClass)[0],
          meta:deadlineText(flowRoot())[1]};
        /* Le verdict se tient, puis le parcours **continue** : un refus ne
           ferme pas la calibration, il passe l'etape. */
        verdictOver(cal);
        const rows=reportRows();
        const recap={step:cal.stepId(),actions:stepActions(flowRoot())};
        press(flowRoot(),'apply');
        return {atWindow,rows,recap};
      };
      /* 1. La scene est eteinte : `viewport()` rend null. */
      const off=calOf();bench.state.scene=false;
      const sceneOff=play(off);
      await new Promise(r=>setImmediate(r));
      const payload=saved[saved.length-1];
      /* 2. Aucun banc du tout : une calibration construite sans. */
      const none=calOf({practice:null});
      const noBench=play(none);
      await new Promise(r=>setImmediate(r));
      out({sceneOff,noBench,payload,
        reason:C.STAGE_REASON.SCENE_UNAVAILABLE,
        closed:!flowRoot()});
    """, name="sceneOff")

    reason = result["reason"]
    assert reason == "barehands_stage_scene_unavailable"

    for name in ("sceneOff", "noBench"):
        run = result[name]
        # L'étape se solde **tout de suite**, sans faire lire une consigne pour
        # un exercice qui ne peut pas s'ouvrir.
        assert run["atWindow"]["phase"] == "result", name
        assert run["atWindow"]["meta"] == "", (
            "aucune échéance ne descend sur une étape qui ne se jouera pas"
        )
        # **Et la cause est dite**, en français, sur la seule surface visible.
        assert "scène est éteinte" in run["atWindow"]["note"], run["atWindow"]["note"]
        assert "valeurs d" in run["atWindow"]["note"], "et que le moteur garde ses défauts"
        # Le parcours **continue** jusqu'au rapport : un refus n'est pas une
        # panne, et les cinq autres étapes n'ont besoin d'aucune scène.
        assert run["recap"]["step"] is None, name
        assert run["recap"]["actions"] == ["apply", "discard"], name
        labels = {row[0]: (row[1], row[2]) for row in run["rows"]}
        # **Passée, pas ratée** : l'utilisateur n'a rien manqué.
        assert labels["6A · Déplacer"][0] == "jf-skipped", name
        assert labels["6B · Redimensionner"][0] == "jf-skipped", name

    # Et le motif voyage jusqu'au profil, où une trace le relira tel quel.
    stages = result["payload"]["stages"]
    assert stages["drag"] == {"status": "skipped", "reason": reason, "samples": 0}
    assert stages["resize"] == {"status": "skipped", "reason": reason, "samples": 0}


def test_the_practice_frame_is_torn_down_on_every_way_out(tmp_path):
    """**Le cadre d'entraînement meurt avec son exercice, quoi qu'il arrive.**

    C'est la moitié produit du bac à sable : une fenêtre d'entraînement qui
    survivrait à la calibration flotterait au-dessus de la scène de
    l'utilisateur, et le moteur garderait une porte ouverte vers un identifiant
    qui n'existe plus. `overlay.step()` ne suffit pas à la retirer — elle n'est
    pas posée par `mount()`, c'est la page qui l'appende dans la région — donc
    le démontage est explicite, et il passe par les **deux seuls** chemins de
    sortie : `advance()` et `stop()`.

    Cinq sorties, et la première est celle qui fait peur : Échap **au milieu
    d'une capture**, c'est-à-dire pendant que la main tient le cadre.
    """

    result = run_node(tmp_path, DOM + DRIVER + """
      const upTo=cal=>{cal.start();for(let i=0;i<5;i+=1)skipStep(cal);readOn(cal)};
      /* 1. Echap **au milieu d'une capture**. */
      const a=calOf();upTo(a);
      bench.grab();a.tick();
      const holding={phase:a.phase(),live:bench.state.live};
      document.fire('keydown',{key:'Escape'});
      const escaped={live:bench.state.live,closes:bench.state.closes,
        running:a.isRunning(),practising:a.practising(),overlay:!!flowRoot()};
      /* 2. Le bouton « Quitter », meme moment. */
      const b=calOf();upTo(b);
      bench.grab();b.tick();
      press(flowRoot(),'exit');
      const quit={live:bench.state.live,closes:bench.state.closes,practising:b.practising()};
      /* 3. Les deux temps passes : on sort de l'ecran par le haut. */
      const c=calOf();upTo(c);
      skipStep(c);skipStep(c);
      const done={live:bench.state.live,closes:bench.state.closes,
        step:c.stepId(),practising:c.practising()};
      /* Le rapport reste a l'ecran tant qu'on n'a pas tranche : on le ferme,
         sinon la coque suivante n'est pas celle que `flowRoot()` trouve — la
         page, elle, refuse d'en ouvrir deux (`barehands_flow_busy`). */
      c.exit('test');
      /* 4. `exit()` par la porte publique, depuis l'exterieur. */
      const d=calOf();upTo(d);
      bench.grab();d.tick();
      d.exit('test');
      const byApi={live:bench.state.live,closes:bench.state.closes};
      /* 5. Une image **en retard** apres la sortie : elle ne doit rien
         ressusciter, ni rouvrir un cadre dans une coque fermee. */
      const e=calOf();upTo(e);
      bench.grab();e.tick();
      e.exit('test');
      bench.state.events.push({type:'commit',mode:'move',box:{x:0,y:0,w:64,h:40},
        from:{x:-32,y:-20,w:64,h:40},moved:true,sized:false});
      const late={fed:e.feed({now:clock,hands:[hand({})]}),ticked:e.tick(),
        live:bench.state.live,overlay:!!flowRoot(),opens:bench.state.opens};
      out({holding,escaped,quit,done,byApi,late});
    """, name="teardown")

    # Le cadre était bien tenu au moment de la sortie : le test porte sur le
    # cas qui fait peur, pas sur une sortie au repos.
    assert result["holding"] == {"phase": "running", "live": True}

    # **Échap au milieu d'une capture** : le cadre part, le moteur est
    # débranché, la coque est fermée, et rien ne tourne plus.
    escaped = result["escaped"]
    assert escaped["live"] is False and escaped["closes"] == 1
    assert escaped["running"] is False and escaped["practising"] is False
    assert escaped["overlay"] is False

    # Les trois autres sorties font exactement la même chose.
    assert result["quit"] == {"live": False, "closes": 1, "practising": False}
    assert result["byApi"] == {"live": False, "closes": 1}
    # Passer les deux temps quitte l'écran vers le rapport, et le cadre part
    # avec lui — sinon il flotterait au-dessus du rapport.
    assert result["done"]["live"] is False and result["done"]["closes"] == 1
    assert result["done"]["step"] is None and result["done"]["practising"] is False

    # **Une image en retard ne ressuscite rien** : c'est la même règle que
    # `regions()` qui rend `null` sur une coque fermée.
    late = result["late"]
    assert late["fed"] is None and late["ticked"] is None
    assert late["live"] is False and late["overlay"] is False
    assert late["opens"] == 1, "une image en retard a rouvert un cadre"


def test_the_window_step_only_completes_on_the_gesture_it_asks_for(tmp_path):
    """**6A et 6B ne se soldent pas l'une pour l'autre**, et le geste qui n'est
    pas le bon **se dit**.

    C'est la moitié calibration de la garantie que le moteur donne déjà : ce
    n'est pas la calibration qui décide qu'un couple de prises redimensionne
    (c'est `combineCaptures`), mais c'est elle qui décide ce qu'elle accepte
    comme réponse. Trois refus et une acceptation :

    - un relâchement **sans changement** n'est ni une réussite ni un échec — la
      fenêtre n'a pas bougé, on le dit et l'exercice continue ;
    - un **redimensionnement** pendant 6A ne la solde pas ;
    - un **déplacement** pendant 6B ne la solde pas non plus, et la phrase dit
      quoi faire de différent ;
    - et l'échéance continue de courir pendant tout cela : rien n'a été ni
      réussi ni raté.
    """

    result = run_node(tmp_path, DOM + DRIVER + """
      const cal=calOf();
      cal.start();
      for(let i=0;i<5;i+=1)skipStep(cal);
      readOn(cal);
      bench.grab();cal.tick();
      const armed=cal.phase();
      /* Relache sans avoir rien change : la fenetre n'a pas bouge. */
      bench.drop('move',{});cal.tick();
      const unchanged={phase:cal.phase(),step:cal.stepId(),
        note:text(flowRoot(),C.DOM.flowNoteClass)[0]};
      /* Un redimensionnement pendant 6A : ce n'est pas ce qu'on demande. */
      bench.grab();cal.tick();
      bench.drop('resize',{w:96});cal.tick();
      const wrongMode={phase:cal.phase(),step:cal.stepId(),
        note:text(flowRoot(),C.DOM.flowNoteClass)[0]};
      /* Le bon geste, enfin. */
      bench.grab();cal.tick();
      bench.drop('move',{x:-10});cal.tick();
      const right={phase:cal.phase(),step:cal.stepId()};
      verdictOver(cal);
      readOn(cal);
      /* 6B : un deplacement ne la solde pas. */
      bench.grab();cal.tick();
      bench.drop('move',{x:-18});cal.tick();
      const movedInB={phase:cal.phase(),step:cal.stepId(),
        note:text(flowRoot(),C.DOM.flowNoteClass)[0]};
      bench.grab();cal.tick();
      bench.drop('resize',{w:96,h:56});cal.tick();
      const sized={phase:cal.phase(),step:cal.stepId()};
      out({armed,unchanged,wrongMode,right,movedInB,sized});
    """, name="wrongGesture")

    assert result["armed"] == "running"

    # **Rien n'a bougé** : ni réussite ni échec, et la phrase dit quoi faire.
    assert result["unchanged"]["phase"] == "running"
    assert result["unchanged"]["step"] == "drag"
    assert "n’a pas bougé" in result["unchanged"]["note"], result["unchanged"]["note"]

    # **Le mauvais geste ne solde pas la sous-étape**, et l'écran ne fait pas
    # croire que le cadre ne répond pas : il vient d'obéir, à l'autre geste.
    assert result["wrongMode"]["phase"] == "running"
    assert result["wrongMode"]["step"] == "drag"
    assert "redimensionnement" in result["wrongMode"]["note"]
    assert "une seule zone" in result["wrongMode"]["note"]

    # Le bon geste, lui, la solde.
    assert result["right"] == {"phase": "result", "step": "drag"}

    # **Et symétriquement pour 6B** : déplacer la fenêtre à une main ne la
    # redimensionne pas, quoi qu'en pense l'utilisateur pressé.
    assert result["movedInB"]["phase"] == "running"
    assert result["movedInB"]["step"] == "resize"
    assert "déplacée" in result["movedInB"]["note"]
    assert "deux zones" in result["movedInB"]["note"]
    assert result["sized"] == {"phase": "result", "step": "resize"}


def test_the_window_step_still_feeds_the_click_drag_separation(tmp_path):
    """**6A nourrit encore la moitié « glissement » de `deriveTravelSlop`**, et
    6B n'y verse rien.

    La question posée par la slice était « est-ce encore honnête ? », et la
    réponse est oui pour 6A : la grandeur mesurée est exactement celle de
    l'ancienne étape `drag` — la course de la **paume** entre la fermeture et
    l'ouverture du canal, en fraction de la largeur d'image — à ceci près que
    la main tient maintenant un vrai bord au lieu de traverser le vide. Elle se
    compare donc toujours aux clics de l'étape de visée, et la dérivation n'est
    pas touchée.

    Pour 6B la réponse est non, et c'est un choix : un redimensionnement à deux
    mains fait deux courses simultanées dont aucune n'est « un glissement
    délibéré » au sens de la dérivation. Les y verser élargirait la tolérance
    de tout le monde sur une grandeur qui n'est pas celle qu'on croit mesurer.
    """

    result = run_node(tmp_path, DOM + DRIVER + """
      const cal=calOf();
      cal.start();
      for(let i=0;i<4;i+=1)skipStep(cal);
      /* Viser : trois clics courts, qui donnent la moitie « clic ». */
      readOn(cal);clickOnce(cal);clickOnce(cal);clickOnce(cal);verdictOver(cal);
      /* 6A : une prise franche, donc une course bien plus longue qu'un clic. */
      readOn(cal);
      bench.grab();cal.tick();
      feed(cal,4,{primaryRatio:.15});
      feed(cal,2,{primaryRatio:.6,palmX:980});
      bench.drop('move',{x:-24});cal.tick();
      verdictOver(cal);
      /* 6B : deux mains, et aucune course versee. */
      readOn(cal);
      bench.grab();cal.tick();
      feedBoth(cal,6);
      feed(cal,4,{primaryRatio:.15});
      feed(cal,2,{primaryRatio:.6,palmX:1100});
      bench.drop('resize',{w:96,h:56});cal.tick();
      verdictOver(cal);
      press(flowRoot(),'apply');
      await new Promise(r=>setImmediate(r));
      const payload=saved[saved.length-1];
      out({slop:payload.hands.left.travelSlopNorm,
        stages:payload.stages,
        /* La derivation elle-meme n'a pas ete touchee : on la rejoue a la main
           sur les deux moities, et elle doit rendre le meme nombre. */
        direct:K.deriveTravelSlop([.0023,.0025,.0024],[.28],K.options({}))});
    """, name="travel")

    # Les deux temps ont abouti, et la tolérance est dérivée — donc 6A a bien
    # produit un échantillon de glissement.
    assert result["stages"]["drag"]["status"] == "ok"
    assert result["stages"]["resize"]["status"] == "ok"
    assert result["slop"] is not None, (
        "6A ne nourrit plus la moitié « glissement » : la tolérance clic/"
        "glissement de tout le monde retomberait sur le défaut d'usine"
    )
    assert 0 < result["slop"] < 1
    # Et la dérivation est inchangée : elle refuse toujours, borne toujours, et
    # pose toujours le seuil entre les deux gestes.
    assert result["direct"]["ok"] is True
    assert result["direct"]["clickHigh"] < result["direct"]["dragLow"]


def test_the_window_step_measures_the_canonical_pieces_and_owns_no_geometry(tmp_path):
    """**La calibration ne réimplémente rien, et sa source le montre.**

    L'exigence de la slice est « reuse, do not reimplement », et la façon de la
    tenir n'est pas une intention : c'est que le module de calibration ne
    contienne **aucune** des quatre choses que l'architecture §10 interdit d'y
    dupliquer — `manipulateBox`, `rebaseManipulation`, l'appartenance des zones,
    la taille minimale — ni aucune règle de compatibilité de zones.

    Ce qu'il contient à la place est une **liste blanche de quatre portes** : il
    ne peut donc pas atteindre la scène même s'il le voulait, et c'est ce qui
    rend le bac à sable structurel plutôt que promis.
    """

    source = CALIBRATION.read_text(encoding="utf-8")
    # **Le code, pas les commentaires.** Ce module *parle* beaucoup de
    # `manipulateBox` et de `combineCaptures` — c'est même le sujet de la moitié
    # de ses commentaires, puisqu'il explique pourquoi il ne les réécrit pas.
    # Ce qu'on vérifie ici est qu'il ne les **contient** pas.
    logic = strip_js_comments(source.split("function createCalibration")[1])

    # **Aucune géométrie de cadre ici.** Les quatre noms que l'architecture §10
    # interdit de dupliquer n'apparaissent pas dans la logique du parcours.
    for forbidden in ("manipulateBox", "rebaseManipulation", "resizeBySides",
                      "clampBox", "MIN_SIZE", "MAX_SIZE", "SAFE_AREA"):
        assert forbidden not in logic, forbidden
    # Ni aucune table de zones ou de côtés : c'est `combineCaptures` qui décide,
    # et une seconde table ici divergerait en silence de celle du contrat.
    for forbidden in ("ZONE_SIDES", "zoneSides", "SIDE_AXIS", "top_left",
                      "bottom_right", "same_zone", "combineCaptures"):
        assert forbidden not in logic, forbidden

    # **Quatre portes, et pas une de plus.** Le parcours ne reçoit du banc que
    # ce dont il a besoin pour dire *où* et *quand* ; tout ce qui touche à la
    # scène, au DOM et à la géométrie reste de l'autre côté de la couture.
    assert "const PRACTICE_DOORS=['viewport','open','drain','close']" in source
    bare = strip_js_comments(source)
    for scene_global in ("JarvisScene", "JarvisSceneLayout", "JarvisSceneInteract"):
        assert scene_global not in bare, scene_global

    # Et ce que l'étape constate vient du moteur, pas d'une règle locale : le
    # mode est lu, jamais calculé.
    assert "done.mode===want.mode" in logic
    assert "want.mode==='resize'?done.sized:done.moved" in logic


def test_no_step_ever_prints_its_own_emphasis_markers_on_screen(tmp_path):
    """**Ce que l'utilisateur lit est ce qui est écrit.** Les consignes sont
    posées en `textContent`, jamais interprétées : un `**majeur**` glissé dans
    une chaîne pour insister ne met rien en gras, il affiche deux paires
    d'astérisques au milieu d'une phrase — et l'étape qui apprend le clic droit
    est précisément celle où l'utilisateur lit le plus attentivement, puisque
    c'est la seule qui lui demande un doigt qu'il n'a pas encore utilisé.

    Le défaut a vécu une slice entière sans qu'aucun test ne le voie, parce que
    tous lisaient les consignes comme des chaînes opaques. Celui-ci lit ce que
    la coque a réellement peint, sur les sept écrans, et refuse la syntaxe
    Markdown que le DOM ne rendra jamais.
    """

    result = run_node(tmp_path, DOM + DRIVER + """
      const cal=calOf();
      cal.start();
      const painted=[];
      for(let i=0;i<7;i+=1){
        painted.push({step:cal.stepId(),
          instruction:text(flowRoot(),'jf-instruction').join(' '),
          title:text(flowRoot(),'jf-title').join(' ')});
        skipStep(cal);
      }
      out({painted});
    """, name="emphasis")

    painted = result["painted"]
    assert len(painted) == 7, "les sept écrans publics ont été parcourus"

    # `**gras**`, `_italique_`, `` `code` `` : aucun de ces marqueurs n'a de
    # sens dans un noeud de texte. On les refuse là où l'utilisateur regarde.
    for screen in painted:
        for field in ("instruction", "title"):
            written = screen[field]
            for marker in ("**", "__", "`"):
                assert marker not in written, (
                    f"l'écran {screen['step']!r} affiche littéralement {marker!r} "
                    f"dans son champ {field} : {written!r}"
                )
