"""Cible sémantique et retour visuel de visée (Slice 05), exécutés par node.

Une main devant une caméra ne se teste pas ici. Ce qui l'est : que la région
d'un cadre se décide sur sa géométrie et non sur le pixel qu'occupe un élément ;
que la priorité coin > bord > corps tranche un **recouvrement** et ne traverse
jamais deux objets ; qu'une capsule de 24 px de haut garde un corps ; qu'une
zone prise ne se perde pas sur un pixel de tremblement ; qu'une étoile de la
scène soit une candidate alors que le sélecteur de survol historique l'ignore ;
que **rien ne soit dessiné hors intention** (décision 3), ce qui se vérifie dans
l'arbre et pas dans une feuille de style ; et que les trois couleurs de la
décision 23 sortent des jetons du contrat.

L'horloge est injectée ; le DOM est un double minimal, et un test conduit la
chaîne entière depuis des points de main.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import (
    BAREHANDS_CONTRACTS_SCRIPT_MARKER,
    BAREHANDS_SCRIPT_MARKER,
    BAREHANDS_TARGET_SCRIPT_FILE,
    BAREHANDS_TARGET_SCRIPT_MARKER,
    SCENE_PAGE_SCRIPT_MARKER,
    ControlCenter,
)

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
SCRIPT = RUNTIME / "control_center_barehands.js"
CONTRACTS = RUNTIME / "control_center_barehands_contracts.js"
TARGET = RUNTIME / "control_center_barehands_target.js"
CALIBRATION = RUNTIME / "control_center_barehands_calibration.js"
PAGE_HTML = RUNTIME / "control_center.html"
SCENE_PAGE = RUNTIME / "control_center_scene_page.js"
SCENE_INTERACT = RUNTIME / "control_center_scene_interact.js"


def run_node(tmp_path: Path, source: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "barehands-target.cjs"
    script.write_text(
        f"const SCRIPT_PATH={json.dumps(str(SCRIPT))};\n"
        f"const CALIBRATION_PATH={json.dumps(str(CALIBRATION))};\n"
        f"const TARGET_PATH={json.dumps(str(TARGET))};\n"
        f"const SCENE_INTERACT_PATH={json.dumps(str(SCENE_INTERACT))};\n"
        f"const B=require(SCRIPT_PATH);\n"
        f"const C=require({json.dumps(str(CONTRACTS))});\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "const refused=fn=>{try{fn();return null}catch(e){return e.code||e.name}};\n"
        "const resolver=o=>B.createTargetResolver(Object.assign({pickRegion:C.pickRegion},o||{}));\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


#: Candidates de résolution, telles que la collecte les rend. `boundsPx` est le
#: cadre de l'objet entier, en **pixels de la fenêtre** — jamais des unités de
#: scène (±160 × ±90), et le suffixe est là pour que la confusion se voie.
FIXTURE = """
const object=(id,x,y,w,h,opts)=>Object.assign({objectId:id,kind:'scene_object',
  representation:'window',zoned:true,actionable:true,
  boundsPx:{x,y,w,h}},opts||{});
const control=(x,y,w,h,opts)=>Object.assign({objectId:null,kind:'button',
  representation:null,zoned:false,actionable:true,
  boundsPx:{x,y,w,h}},opts||{});
const refs=list=>{list.forEach((c,i)=>{c.ref=i});return list};
const aim=(id,state,x,y,extra)=>Object.assign(
  {handTrackId:id,channel:'primary',state,x,y},extra||{});
const say=t=>t?`${t.objectId||t.kind}:${t.region}${t.zone?':'+t.zone:''}`:null;
"""


# ------------------------------------------------------------------ géométrie


def test_a_frame_offers_a_body_four_edges_and_four_corners_in_window_pixels(tmp_path):
    """Les zones se dérivent du **cadre en pixels de la fenêtre**, pas d'un
    élément ni d'une unité de scène. Dedans : les côtés dont on est à moins
    d'une bande, au plus un par axe. Dehors : les côtés franchis, ce qui donne
    naturellement le bord qu'on approche et le coin quand on approche en
    diagonale."""

    result = run_node(tmp_path, FIXTURE + """
      const box={x:100,y:100,w:200,h:120};
      const band=B.targetBand(box,{});
      const at=(x,y)=>{
        const r=B.regionAt(box,{x,y},band);
        return [r.vertical,r.horizontal,Number(r.distancePx.toFixed(2))];
      };
      /* Les quatre coins, les quatre bords, le corps — puis les mêmes vus de
         l'extérieur, où le côté franchi désigne ce qu'on approche. */
      /* Un seul côté par axe, et ce n'est pas un effet du plafond : même avec
         une bande assez large pour couvrir tout l'objet, c'est le côté le plus
         proche qui gagne. Les deux à la fois tiendraient « gauche » et
         « droite » du même point, donc un coin qui n'existe pas. */
      const tiny={x:0,y:0,w:20,h:20};
      const nearer=B.regionAt(tiny,{x:14,y:6},14);
      const nearerOther=B.regionAt(tiny,{x:6,y:14},14);
      out({band,
        oversized:[[nearer.vertical,nearer.horizontal],
                   [nearerOther.vertical,nearerOther.horizontal]],
        centre:at(200,160),
        topLeft:at(105,105),topRight:at(295,104),bottomRight:at(299,219),bottomLeft:at(101,215),
        top:at(200,108),right:at(297,160),bottom:at(200,215),left:at(103,160),
        outsideLeft:at(90,160),outsideCorner:at(92,94),outsideDiagonalFar:at(60,60),
        /* Les zones du contrat se nomment `vertical_horizontal` : un test le
           vérifie en construisant réellement la candidate. */
        corners:C.CORNERS,
        built:C.createTargetCandidate({region:'corner',zone:'top_left',objectId:'a',
          boundsPx:box,distancePx:0,representation:'window'}),
      });
    """)
    # 14 px nominaux, et 200×120 laisse la place (0,3 × 120 = 36).
    assert result["band"] == 14
    # Le plus proche des deux côtés d'un axe, jamais les deux.
    assert result["oversized"] == [["top", "right"], ["bottom", "left"]]
    assert result["centre"] == [None, None, 0.0]
    assert result["topLeft"] == ["top", "left", 0.0]
    assert result["topRight"] == ["top", "right", 0.0]
    assert result["bottomRight"] == ["bottom", "right", 0.0]
    assert result["bottomLeft"] == ["bottom", "left", 0.0]
    # Un seul côté par axe : sur un bord, l'autre axe ne dit rien.
    assert result["top"] == ["top", None, 0.0]
    assert result["right"] == [None, "right", 0.0]
    assert result["bottom"] == ["bottom", None, 0.0]
    assert result["left"] == [None, "left", 0.0]
    # Dehors, la distance au rectangle est ce que `pickRegion` lira.
    assert result["outsideLeft"] == [None, "left", 10.0]
    assert result["outsideCorner"] == ["top", "left", pytest.approx(10.0, abs=0.01)]
    assert result["outsideDiagonalFar"][0:2] == ["top", "left"]
    assert result["outsideDiagonalFar"][2] == pytest.approx(56.57, abs=0.01)
    assert result["built"]["zone"] == "top_left" and result["built"]["axes"] == ["x", "y"]
    assert set(result["corners"]) == {"top_left", "top_right", "bottom_right", "bottom_left"}


def test_a_capsule_too_short_for_its_band_still_has_a_body(tmp_path):
    """Décision 8 : BODY est de l'interaction de **contenu**. Une bande fixe de
    14 px sur une capsule de 24 px de haut prend les deux moitiés et ne laisse
    pas un seul pixel de corps — la décision 8 devient inatteignable sur l'objet
    le plus courant de la scène, et rien ne le dit. La bande est donc aussi
    bornée par une fraction du petit côté, et `targetZoneMaxRatio ≥ 0,5` se
    refuse à la construction, parce qu'à la moitié les deux bandes opposées se
    rejoignent."""

    result = run_node(tmp_path, FIXTURE + """
      const capsule={x:0,y:0,w:120,h:24};
      const band=B.targetBand(capsule,{});
      const centre=B.regionAt(capsule,{x:60,y:12},band);
      /* Sans le plafond proportionnel, la même bande vaudrait 14 et le centre
         exact de la capsule se lirait « bord haut ». */
      const naive=B.regionAt(capsule,{x:60,y:12},14);
      /* C'est la bande **large** que la fraction plafonne : c'est elle qui
         décide du corps qui reste quand la zone est tenue. La bande d'entrée
         s'en déduit, donc elle reste sous elle. */
      const held=B.targetBand(capsule,{},true);
      out({band:Number(band.toFixed(2)),held:Number(held.toFixed(2)),
        centre:[centre.vertical,centre.horizontal],naive:[naive.vertical,naive.horizontal],
        edgeStillReachable:(()=>{const r=B.regionAt(capsule,{x:60,y:3},band);
          return [r.vertical,r.horizontal]})(),
        refusedRatio:refused(()=>B.createTargetResolver({pickRegion:C.pickRegion,targetZoneMaxRatio:.5})),
        refusedRatioHigh:refused(()=>B.createTargetResolver({pickRegion:C.pickRegion,targetZoneMaxRatio:.9})),
        refusedRatioZero:refused(()=>B.createTargetResolver({pickRegion:C.pickRegion,targetZoneMaxRatio:0})),
      });
    """)
    # La bande qui **garde** vaut la fraction (0,3 × 24) ; celle qui **prend**
    # en garde le rapport des réglages (14/20). Le corps survit exactement
    # comme avant — c'est la bande large qui le décide — et l'hystérésis n'est
    # plus nulle. Avant, les deux valaient 7,2 : la zone se perdait au pixel
    # même où elle se prenait.
    assert result["held"] == 7.2
    assert result["band"] == pytest.approx(5.04, abs=0.001)
    assert result["held"] - result["band"] > 2, "une zone tenue doit être plus dure à perdre"
    assert result["centre"] == [None, None], "la capsule a perdu son corps"
    assert result["naive"] == ["top", None], "sans plafond, le centre se lit « bord »"
    # Et le bord reste atteignable : le plafond rétrécit la bande, il ne la tue pas.
    assert result["edgeStillReachable"] == ["top", None]
    for key in ("refusedRatio", "refusedRatioHigh", "refusedRatioZero"):
        assert result[key] == "RangeError", key


def test_only_a_capsule_or_a_window_has_manipulation_zones(tmp_path):
    """Décision D3 de la Slice 00 : un `point` et un `signal` ne sont pas
    redimensionnables, donc ils n'exposent que leur corps. Le contrat le dit
    (`hasManipulationZones`) ; le résolveur doit le **faire**, y compris au bord
    exact de l'objet, là où un cadre zoné rendrait un coin."""

    result = run_node(tmp_path, FIXTURE + """
      const star=object('star',100,100,26,26,{representation:'point',zoned:false,kind:'scene_object'});
      const win=object('win',100,100,26,26);
      const r=resolver({});
      const pick=cands=>say(r.update({now:0,candidates:refs(cands),
        hands:[aim(1,'pinching',101,101)]})[0]);
      const corner=pick([win]);
      r.reset();
      const body=pick([star]);
      out({corner,body,
        zoned:['capsule','window','point','signal','autre'].map(C.hasManipulationZones),
        /* Une zone sur une représentation qui n'en a pas ne se construit même
           pas côté contrat : la Slice 06 ne pourra pas la capturer. */
        candidate:C.createTargetCandidate({region:'body',objectId:'star',
          representation:'point',boundsPx:{x:0,y:0,w:2,h:2}}).zone,
      });
    """)
    assert result["corner"] == "win:corner:top_left"
    assert result["body"] == "star:body", "une étoile n'a pas de zone de manipulation"
    assert result["zoned"] == [True, True, False, False, False]
    assert result["candidate"] is None


# -------------------------------------------------------------- recouvrement


def test_priority_settles_an_overlap_inside_one_object_never_between_two(tmp_path):
    """**Le cœur de la Slice.** « En recouvrement, coin > bord > corps » est une
    règle de *recouvrement* : elle dit quoi faire quand deux régions se
    disputent le même point. Appliquée entre objets, elle fait gagner le coin
    d'un cadre situé à 11 px sur le corps du bouton que le doigt touche
    réellement — priorité 3 contre 1, et la distance n'est lue qu'en troisième.

    La résolution est donc en deux temps : le plus proche décide **quel objet**,
    `pickRegion` décide **quelle partie**. C'est la seule composition où les
    deux critères disent ce qu'ils veulent dire."""

    result = run_node(tmp_path, FIXTURE + """
      /* Le doigt est dans le bouton ; le coin bas-droit du cadre est à 11 px. */
      const button=control(100,100,80,30);
      const frame=object('win',0,0,130,110);
      const point={x:140,y:115};
      const r=resolver({});
      const chosen=say(r.update({now:0,candidates:refs([frame,button]),
        hands:[aim(1,'pinching',point.x,point.y)]})[0]);
      /* Ce que rendrait la règle appliquée à plat sur toutes les candidates des
         deux objets : exactement le défaut qu'on refuse. */
      const flat=[];
      for(const o of [frame,button]){
        const found=B.targetRegionsOf(o,point,o.zoned?B.targetBand(o.boundsPx,{}):0);
        flat.push(...found.regions);
      }
      const global=say(C.pickRegion(flat));
      /* Et dans un seul objet, la règle s'applique bien : le coin l'emporte sur
         les deux bords et sur le corps, au même point. */
      const inside=B.targetRegionsOf(frame,{x:4,y:4},B.targetBand(frame.boundsPx,{}));
      out({chosen,global,
        insideRegions:inside.regions.map(say).sort(),
        insidePick:say(C.pickRegion(inside.regions)),
        priority:C.REGION_PRIORITY,
      });
    """)
    assert result["priority"] == {"corner": 3, "edge": 2, "body": 1}
    # Toutes les régions du cadre sont candidates au même point ; la priorité du
    # contrat tranche, et elle tranche pour le coin.
    assert result["insideRegions"] == ["win:body", "win:corner:top_left", "win:edge:left", "win:edge:top"]
    assert result["insidePick"] == "win:corner:top_left"
    # Le défaut, épinglé : la même règle appliquée entre deux objets choisit le
    # coin du cadre voisin plutôt que le bouton sous le doigt.
    assert result["global"] == "win:corner:bottom_right"
    # Ce que le résolveur rend : ce qu'on touche.
    assert result["chosen"] == "button:body"


def test_the_topmost_candidate_wins_a_tie_and_elementfrompoint_is_the_hint(tmp_path):
    """Deux objets qui se recouvrent rendent la **même** distance : zéro. Sans
    autre critère, c'est l'ordre du document — l'ordre de création — qui
    tranche, c'est-à-dire pas ce que l'utilisateur voit. La collecte cite donc
    en tête celui qu'`elementFromPoint` trouve au-dessus ; le résolveur lit
    « le premier cité » comme le contrat le fait.

    `elementFromPoint` **participe** sans décider : c'est tout l'écart entre
    cette Slice et un survol de souris."""

    result = run_node(tmp_path, FIXTURE + """
      const below=object('below',0,0,200,200);
      const above=object('above',0,0,200,200);
      const r=resolver({});
      const pick=list=>say(r.update({now:0,candidates:refs(list),
        hands:[aim(1,'pinching',100,100)]})[0]);
      const first=pick([above,below]);
      r.reset();
      const second=pick([below,above]);
      /* Et l'actionnabilité passe devant la distance : une candidate qu'on ne
         peut pas actionner n'appelle aucun retour visuel (décision 3), donc
         elle ne vole pas la place de celle qui en appelle un. */
      r.reset();
      /* `dead` **contient** le point (distance 0) mais ne s'actionne pas ;
         `live` est à 1,4 px. L'actionnable gagne quand même — sans quoi on
         n'afficherait plus rien là où il y avait quelque chose à montrer. */
      const dead=object('dead',0,0,300,300,{actionable:false});
      const live=object('live',300,300,200,200);
      const overActionable=say(r.update({now:0,candidates:refs([dead,live]),
        hands:[aim(1,'pinching',299,299)]})[0]);
      r.reset();
      const distances=[dead,live].map(o=>Number(
        B.targetRegionsOf(o,{x:299,y:299},B.targetBand(o.boundsPx,{})).distancePx.toFixed(2)));
      /* **Décision 3 comme porte.** Seule sous un doigt qui pince, la
         candidate non actionnable ne se résout pas du tout — sans quoi elle
         était publiée à la Slice 06 et dessinée : un cadre bleu et un nom
         autour d'un bouton désactivé, c'est-à-dire la promesse d'une action
         qui n'arrivera pas. Et `pressed` ne la fige pas non plus : une capture
         ne peut pas s'ouvrir sur ce qui ne s'actionne pas. */
      r.reset();
      const deadAlone=say(r.update({now:0,candidates:refs([dead]),
        hands:[aim(1,'pinching',150,150)]})[0]);
      r.reset();
      const deadAlonePressed=say(r.update({now:0,candidates:refs([dead]),
        hands:[aim(1,'pressed',150,150)]})[0]);
      out({first,second,overActionable,distances,deadAlone,deadAlonePressed});
    """)
    assert result["first"] == "above:body"
    assert result["second"] == "below:body", "l'ordre cité doit trancher l'égalité"
    # Seule sous le doigt, la candidate non actionnable ne devient pas une
    # cible : elle n'est pas « classée derrière », elle est écartée.
    assert result["deadAlone"] is None
    assert result["deadAlonePressed"] is None
    # La candidate non actionnable est bien la plus proche : c'est ce qui rend
    # l'assertion suivante discriminante.
    assert result["distances"] == [0.0, pytest.approx(1.41, abs=0.01)]
    assert result["overActionable"] == "live:corner:top_left"


# --------------------------------------------------------------- assistance


def test_a_small_aiming_error_still_reaches_the_target_and_a_large_one_does_not(tmp_path):
    """« Une petite erreur de visée près d'une cible nette se résout de façon
    prévisible. » L'assistance est une portée, pas une prime : rien n'est
    soustrait à une distance — la leçon de la reprise de la Slice 03, où une
    prime soustraite au coût d'appariement renversait la géométrie. Au-delà de
    la portée, il n'y a **pas** de cible, et donc rien de dessiné."""

    result = run_node(tmp_path, FIXTURE + """
      const button=control(100,100,80,30);
      const r=resolver({});
      const at=(x,y,assistance)=>{const t=r.update({now:0,candidates:refs([button]),
        hands:[aim(1,'pinching',x,y,{assistance})]})[0];r.reset();
        return t?[say(t),Number(t.distancePx.toFixed(1))]:null};
      out({
        inside:at(140,115),
        near:at(140,95),      // 5 px au-dessus du bouton
        edgeOfReach:at(140,76),  // 24 px : la portée exacte du défaut
        beyond:at(140,70),    // 30 px : hors de portée
        noAssistance:at(140,95,0),
        doubled:at(140,70,1), // assistance 1 = double portée
        reach:[r.reach(undefined),r.reach(.5),r.reach(0),r.reach(1)],
        assistDefault:C.SETTINGS_DEFAULTS.assistance,
      });
    """)
    assert result["inside"] == ["button:body", 0.0]
    assert result["near"] == ["button:body", 5.0]
    assert result["edgeOfReach"] == ["button:body", 24.0]
    assert result["beyond"] is None, "hors de portée, il n'y a pas de cible"
    # `assistance` 0 coupe l'aide : seul ce qu'on touche compte.
    assert result["noAssistance"] is None
    # `assistance` 1 double la portée, et 0,5 — le défaut des réglages — rend
    # exactement `targetAssistPx`. C'est ce facteur qui fait que brancher le
    # réglage à la Slice 07 ne divisera pas la portée par deux en silence.
    assert result["doubled"] == ["button:body", 30.0]
    assert result["reach"] == [24, 24, 0, 48]
    assert result["assistDefault"] == 0.5


def test_a_zone_once_taken_survives_a_pixel_of_tremor(tmp_path):
    """Hystérésis, même idiome que `pressRatio`/`releaseRatio` : on **entre**
    dans une zone à `targetZonePx`, on la **garde** jusqu'à `targetZoneHoldPx`.
    Sans elle, une main qui tremble de trois pixels au bord de la bande fait
    clignoter l'aperçu entre le bord et tout le cadre — précisément là où
    l'hystérésis existe pour qu'il ne clignote pas.

    Et les deux nombres ne se règlent pas séparément : `targetZoneHoldPx` sous
    `targetZonePx` rend la zone plus facile à perdre qu'à prendre, ce qui ne
    lève rien, ne fait rien tomber, et se lit comme un tremblement de main."""

    result = run_node(tmp_path, FIXTURE + """
      const frame=object('win',0,0,200,200);
      const walk=(ys,options)=>{
        const r=resolver(options);
        return ys.map(y=>say(r.update({now:0,candidates:refs([frame]),
          hands:[aim(1,'pinching',100,y)]})[0]));
      };
      out({
        /* 14 px : on entre. 17, 19 : dans la bande large, on garde. 22 : perdu.
           Puis 15 : on ne rentre pas encore (la bande d'entrée est à 14). */
        held:walk([14,17,19,22,15,13]),
        /* Le même chemin sans hystérésis : la zone se perd dès 15 px. */
        flat:walk([14,17,19,22,15,13],{targetZoneHoldPx:14}),
        refusedInverted:refused(()=>resolver({targetZonePx:20,targetZoneHoldPx:10})),
        equalAllowed:(()=>{resolver({targetZonePx:14,targetZoneHoldPx:14});return 'construit'})(),
      });
    """)
    # Prise à 14, gardée à 17 et 19, perdue à 22 — et pas reprise à 15, parce
    # que la bande qui **prend** reste à 14.
    assert result["held"] == [
        "win:edge:top", "win:edge:top", "win:edge:top",
        "win:body", "win:body", "win:edge:top",
    ]
    # Sans hystérésis, la zone tombe dès le premier pixel au-delà de la bande.
    assert result["flat"] == [
        "win:edge:top", "win:body", "win:body",
        "win:body", "win:body", "win:edge:top",
    ]
    assert result["refusedInverted"] == "RangeError"
    assert result["equalAllowed"] == "construit"


def test_the_hysteresis_survives_at_the_size_objects_are_actually_drawn(tmp_path):
    """Le test au-dessus prouve l'hystérésis sur un objet de 200×200 — c'est-à-
    dire là où le plafond proportionnel ne mord pas. Sur **tout** objet dont le
    petit côté est sous 46,7 px, les deux bandes étaient plafonnées séparément
    par la même fraction, rendaient donc le même nombre, et l'hystérésis valait
    zéro. Ce n'est pas un cas limite : `control_center_scene_layout.js` dessine
    les capsules à partir de 24 px (`CAPSULE_MIN_HEIGHT_PX`) et une fenêtre
    compacte à 28 px — et une fenêtre compacte est zonée. L'hystérésis ne
    survivait que là où le clignotement dérange le moins.

    Une fixture doit ressembler au produit : les tailles ci-dessous sont celles
    que la scène dessine, aux deux résolutions courantes."""

    result = run_node(tmp_path, FIXTURE + """
      /* Petit côté, en pixels de la fenêtre, tel que la scène les dessine. */
      const sizes={capsuleMin:[96,30],capsuleDefault:[240,42],capsule720:[160,28],
        compactWindow:[384,28],windowDefault:[384,240]};
      const bands={},bodies={};
      for(const name of Object.keys(sizes)){
        const [w,h]=sizes[name],box={x:0,y:0,w,h},short=Math.min(w,h);
        const band=B.targetBand(box,{}),held=B.targetBand(box,{},true);
        bands[name]=[Number(band.toFixed(2)),Number(held.toFixed(2)),
          Number((held-band).toFixed(2))];
        /* Ce qui reste de corps quand la zone est **tenue** : c'est la bande
           large qui décide de cette garantie, et c'est pour cela que c'est elle
           que le plafond borne. */
        bodies[name]=Number(((short-2*held)/short).toFixed(3));
      }
      /* Le tremblement rapporté : ±0,6 px au bord de la bande d'**entrée**, sur
         la capsule par défaut. Ce qui est visé ne doit pas changer d'une image
         à l'autre — c'est le clignotement jaune/bleu que la paire existe pour
         empêcher, et qui se lit « main qui tremble ». */
      const capsule=object('cap',0,0,240,42,{representation:'capsule'});
      const tremble=options=>{
        const r=resolver(options);
        const edge=B.targetBand(capsule.boundsPx,options||{});
        return [edge-.6,edge+.6,edge-.6,edge+.6,edge-.6].map(y=>
          say(r.update({now:0,candidates:refs([capsule]),
            hands:[aim(1,'pinching',120,y)]})[0]));
      };
      out({bands,bodies,steady:tremble({}),flat:tremble({targetZoneHoldPx:14})});
    """)
    # [entrée, tenue, hystérésis]. Avant : les deux colonnes étaient égales et
    # la troisième valait 0 partout, sauf sur la grande fenêtre.
    assert result["bands"]["capsuleMin"] == [6.3, 9.0, 2.7]
    assert result["bands"]["capsuleDefault"] == [8.82, 12.6, 3.78]
    assert result["bands"]["capsule720"] == [5.88, 8.4, 2.52]
    assert result["bands"]["compactWindow"] == [5.88, 8.4, 2.52]
    # La grande fenêtre ne bouge pas d'un pixel : c'est le seul cas où le
    # plafond ne mordait pas, et il rendait déjà 14/20.
    assert result["bands"]["windowDefault"] == [14.0, 20.0, 6.0]
    for name, (band, held, gap) in result["bands"].items():
        assert band < held, name
        assert gap >= 2.5, f"{name} : une zone tenue doit rester nettement plus dure à perdre"
    # Et la raison d'être du plafond est intacte : au moins 40 % de corps sur
    # le petit côté, zone tenue comprise (décision 8).
    for name, body in result["bodies"].items():
        assert body >= 0.399, f"{name} : la capsule a perdu son corps"
    # Le tremblement ne fait plus clignoter : on entre à 8,82 et on garde
    # jusqu'à 12,6, donc ±0,6 px autour de l'entrée reste dans la bande tenue.
    assert result["steady"] == ["cap:edge:top"] * 5
    # Réglées égales, les deux bandes se confondent et le clignotement revient :
    # c'est exactement ce que toute capsule subissait.
    assert result["flat"] == ["cap:edge:top", "cap:body", "cap:edge:top",
                              "cap:body", "cap:edge:top"]


def test_a_hand_without_coordinates_aims_nowhere_not_at_the_top_left_corner(tmp_path):
    """« Sans coordonnées, un clic partait en (0,0) — le coin de l'écran, où il
    y a toujours quelque chose à cliquer. » Le contrat dit ce défaut corrigé
    pour les événements de pincement ; il vivait encore ici, sous une autre
    forme.

    `Number.isFinite(Number(v))` répond à « se convertit en nombre », pas à
    « est un nombre » : `null`, `''`, `[]` et `false` valent tous 0 et
    passaient la garde. Une main sans position visait donc le coin supérieur
    gauche, et une cible s'y trouve toujours."""

    result = run_node(tmp_path, FIXTURE + """
      const corner=object('coin',0,0,200,200);
      const aimAt=(x,y)=>{
        const r=resolver({});
        return say(r.update({now:0,candidates:refs([corner]),
          hands:[aim(1,'pinching',x,y)]})[0]);
      };
      const bad=[null,'',[],false,undefined,NaN,'abc',{}];
      out({
        valid:aimAt(10,10),
        refused:bad.map(v=>aimAt(v,10)),
        refusedY:bad.map(v=>aimAt(10,v)),
        /* La même question à la géométrie exportée, qui refusait déjà NaN. */
        region:bad.map(v=>B.regionAt({x:0,y:0,w:10,h:10},{x:v,y:5},2)),
        /* Et une main qui perd sa position **oublie** ce qu'elle tenait : elle
           ne garde pas une cible figée sur une coordonnée absente. */
        forgets:(()=>{const r=resolver({});
          const one=say(r.update({now:0,candidates:refs([corner]),
            hands:[aim(1,'pinching',10,10)]})[0]);
          const two=r.update({now:1,candidates:refs([corner]),
            hands:[aim(1,'pinching',null,10)]}).length;
          return [one,two,r.size()]})(),
      });
    """)
    assert result["valid"] == "coin:corner:top_left"
    assert result["refused"] == [None] * 8, "une coordonnée doit être un nombre"
    assert result["refusedY"] == [None] * 8
    assert result["region"] == [None] * 8
    assert result["forgets"] == ["coin:corner:top_left", 0, 0]


def test_a_zone_the_drawing_cannot_read_refuses_instead_of_guessing(tmp_path):
    """`zoneRect` terminait par un `return` inconditionnel : un côté inconnu —
    ou absent — ressortait en « bord droit ». Les trois `if` manquaient, et la
    fonction répondait quand même, avec assurance et à côté de la question.
    Le seul appel vivant est gardé en amont, donc c'était latent ; mais c'est
    une fonction exportée et testée, et la règle que ce module se donne partout
    ailleurs est de **refuser** ce qu'il n'a pas su lire (une représentation
    absente n'ouvre pas de zones, une candidate sans rectangle n'en est pas
    une). Un défaut latent est un défaut qui attend son second appelant."""

    result = run_node(tmp_path, """
      const T=require(TARGET_PATH);
      const bounds={x:0,y:0,w:200,h:100};
      const rect=(region,zone)=>T.zoneRect({boundsPx:bounds,region,zone,bandPx:10});
      const box=r=>r===null?null:[r.left,r.top,r.width,r.height];
      out({
        top:box(rect('edge','top')),bottom:box(rect('edge','bottom')),
        left:box(rect('edge','left')),right:box(rect('edge','right')),
        corner:(()=>{const r=rect('corner','bottom_right');
          return [r.corner,r.left,r.top,r.hide]})(),
        /* Ce que le dessin ne sait pas lire : pas de bord droit par défaut. */
        unknown:rect('edge','milieu'),
        absent:rect('edge',null),
        empty:rect('edge',''),
      });
    """)
    assert result["top"] == [0, 0, 200, 10]
    assert result["bottom"] == [0, 90, 200, 10]
    assert result["left"] == [0, 0, 10, 100]
    assert result["right"] == [190, 0, 10, 100]
    assert result["corner"][0] is True and result["corner"][1] == 182
    assert result["unknown"] is None, "un côté inconnu ne se dessine pas « à droite »"
    assert result["absent"] is None
    assert result["empty"] is None


def test_the_overlap_rule_is_handed_to_the_resolver_never_reinvented(tmp_path):
    """Le bloc pur est chargé seul par node : il ne peut pas lire le contrat. Il
    ne réimplante donc pas la priorité coin > bord > corps, il la **reçoit** —
    et un résolveur construit sans elle se refuse au lieu d'en inventer une
    seconde, qui divergerait en silence de celle que la Slice 06 lira."""

    result = run_node(tmp_path, FIXTURE + """
      out({
        missing:refused(()=>B.createTargetResolver({})),
        notAFunction:refused(()=>B.createTargetResolver({pickRegion:'coin'})),
        built:(()=>{resolver({});return 'construit'})(),
        /* La règle reçue est bien celle qui décide : un `pickRegion` qui
           choisit toujours le corps rend le corps. */
        overridden:(()=>{
          const r=B.createTargetResolver({pickRegion:list=>list.find(c=>c.region==='body')});
          return say(r.update({now:0,candidates:refs([object('win',0,0,200,200)]),
            hands:[aim(1,'pinching',2,2)]})[0]);
        })(),
      });
    """)
    assert result["missing"] == "RangeError" and result["notAFunction"] == "RangeError"
    assert result["built"] == "construit"
    assert result["overridden"] == "win:body"


# ------------------------------------------------- décision 3 et verrouillage


def test_a_target_is_dynamic_until_the_pinch_goes_down_and_frozen_after(tmp_path):
    """« Garder l'aperçu dynamique jusqu'à la descente, puis passer un
    descripteur de capture **stable**. » Tant que la main approche, la cible
    suit le doigt ; dès le contact, elle ne bouge plus — quoi que fasse la main,
    et même si la collecte ne voit plus l'objet. C'est ce que la Slice 06
    latchera (décision 13) ; sans le gel, un glissement de 30 px changerait
    l'objet capturé au milieu du geste."""

    result = run_node(tmp_path, FIXTURE + """
      const a=object('a',0,0,200,200),b=object('b',400,400,200,200);
      const r=resolver({});
      const step=(state,x,y,cands)=>{const t=r.update({now:0,candidates:refs(cands||[a,b]),
        hands:[aim(1,state,x,y)]})[0];return t?[say(t),t.locked]:null};
      const approachA=step('pinching',2,2);
      const approachB=step('pinching',402,402);   // dynamique : la cible suit
      const down=step('pressed',402,402);
      const dragged=step('pressed',100,100);      // en plein dans l'autre objet
      const goneFromView=step('pressed',100,100,[a]);  // b n'est plus collecté
      const released=step('open',100,100);
      const after=step('pinching',100,100);
      out({approachA,approachB,down,dragged,goneFromView,released,after});
    """)
    assert result["approachA"] == ["a:corner:top_left", False]
    assert result["approachB"] == ["b:corner:top_left", False], "l'aperçu doit suivre avant la descente"
    assert result["down"] == ["b:corner:top_left", True]
    # Figé : la main est repartie dans l'objet « a », la cible reste « b ».
    assert result["dragged"] == ["b:corner:top_left", True]
    assert result["goneFromView"] == ["b:corner:top_left", True]
    # Relâché : plus de cible du tout, et la suivante se résout à neuf.
    assert result["released"] is None
    assert result["after"] == ["a:body", False]


def test_each_channel_targets_on_its_own_and_a_lost_hand_forgets(tmp_path):
    """Le clic droit est un **canal** (décision 21), pas un appui long : la même
    main peut donc approcher un objet de l'index et un autre du majeur, et le
    gel de l'un ne gèle pas l'autre. Et une main qu'on ne revoit plus oublie ce
    qu'elle visait, sur la même horloge d'identité que partout ailleurs
    (`lostGraceMs`) — une cible qui survivrait à sa main serait rendue à la
    suivante."""

    result = run_node(tmp_path, FIXTURE + """
      const a=object('a',0,0,200,200),b=object('b',400,400,200,200);
      const r=resolver({});
      const frame=(now,hands)=>r.update({now,candidates:refs([a,b]),hands}).map(t=>
        [t.handTrackId,t.channel,say(t),t.locked]);
      const both=frame(0,[aim(1,'pressed',2,2),aim(1,'pinching',402,402,{channel:'secondary'})]);
      /* Le primaire est figé sur `a` ; le secondaire suit encore. */
      const moved=frame(16,[aim(1,'pressed',402,402),aim(1,'pinching',100,100,{channel:'secondary'})]);
      const size=r.size();
      /* Plus de main pendant plus que la grâce : tout est oublié. */
      const forgotten=frame(16+B.DEFAULTS.lostGraceMs+1,[]);
      out({both,moved,size,forgotten,left:r.size(),
        graceMs:B.DEFAULTS.lostGraceMs});
    """)
    assert result["both"] == [
        [1, "primary", "a:corner:top_left", True],
        [1, "secondary", "b:corner:top_left", False],
    ]
    assert result["moved"] == [
        [1, "primary", "a:corner:top_left", True],
        [1, "secondary", "a:body", False],
    ]
    assert result["size"] == 2, "deux canaux, deux mémoires"
    assert result["forgotten"] == []
    assert result["left"] == 0 and result["graceMs"] == 250


# ----------------------------------------------------------- de bout en bout


HAND = """
const RAD=d=>d*Math.PI/180;
const FAN={index:-25,middle:-8,ring:8,pinky:25};
function hand(opts){
  const o=Object.assign({cx:.5,cy:.5,palm:.2,index:1.85,middle:2,ring:1.85,pinky:1.7,
    pinch:'index',gap:.65,thumbAngle:-70,thumbReach:1.2},opts||{});
  const lm=Array.from({length:21},()=>({x:o.cx,y:o.cy,z:0}));
  const wrist={x:o.cx,y:o.cy+o.palm/2,z:0};
  lm[0]=wrist;lm[9]={x:o.cx,y:o.cy-o.palm/2,z:0};
  const at=(deg,reach)=>({x:wrist.x+o.palm*reach*Math.sin(RAD(deg)),
                          y:wrist.y-o.palm*reach*Math.cos(RAD(deg)),z:0});
  lm[8]=at(FAN.index,o.index);lm[12]=at(FAN.middle,o.middle);
  lm[16]=at(FAN.ring,o.ring);lm[20]=at(FAN.pinky,o.pinky);
  const anchor=o.pinch==='index'?lm[8]:o.pinch==='middle'?lm[12]:null;
  lm[4]=anchor?{x:anchor.x+o.palm*o.gap,y:anchor.y,z:0}:at(o.thumbAngle,o.thumbReach);
  return lm;
}
const PINCHING=(t,o)=>hand(Object.assign({pinch:'index',index:1.85-.5*t,gap:.65-.5*t},o||{}));
"""


def test_a_real_hand_closing_on_a_real_frame_resolves_where_it_points(tmp_path):
    """**Le test qui compte.** Tous les autres de ce fichier donnent les pixels
    à la main. Celui-ci part de points de main, traverse le traqueur et le
    filtre de la Slice 03, l'intention de pincement de la Slice 04, et n'arrive
    au résolveur qu'à travers eux — c'est la seule couture qui décide *ce que*
    le résolveur reçoit, et aucun test de résolveur ne peut la voir.

    Ce qu'il attrape, et rien d'autre ne l'attraperait : un **mélange
    d'espaces**. Si les jetons sortaient en coordonnées d'image normalisées
    (0..1), ou si les cadres arrivaient en unités de scène (±160 × ±90), tout se
    résoudrait quand même — sur la mauvaise chose, et vers le coin supérieur
    gauche de l'écran. Un leurre posé en unités de scène est donc dans la liste
    des candidates : il ne doit **jamais** gagner."""

    result = run_node(tmp_path, FIXTURE + HAND + """
      const VIEWPORT={width:1920,height:1080};
      const tracker=B.createHandTracker({}),pinch=B.createPinchIntentEngine({});
      const r=resolver({});
      /* `toScreen` applique le miroir de la caméra frontale et une marge : on ne
         calcule pas le pixel à la main, on le **lit** du premier jeton et on
         pose le cadre autour de lui. */
      const first=tracker.update({landmarks:[PINCHING(0,{cx:.62,cy:.45})]},
        {viewport:VIEWPORT,aspect:16/9,now:0});
      const seen={x:first.tokens[0].x,y:first.tokens[0].y};
      const frame=object('win',seen.x-300,seen.y-200,600,400);
      /* Le leurre : la même scène exprimée dans l'autre espace (±160 × ±90).
         Il contient l'origine, donc il gagnerait si les jetons arrivaient
         normalisés ou si quelqu'un mélangeait les deux repères. */
      const decoy=object('unites-de-scene',-160,-90,320,180);
      const steps=[],states=[],aims=[];
      for(let i=1;i<20;i+=1){
        const now=i*16;
        const t=i<4?0:i<10?(i-4)/6:1;
        const lm=PINCHING(t,{cx:.62,cy:.45});
        const step=tracker.update({landmarks:[lm]},{viewport:VIEWPORT,aspect:16/9,now});
        const tok=step.tokens[0];
        const contacts=pinch.update({hands:[{handTrackId:tok.id,landmarks:lm,
          x:tok.filteredX,y:tok.filteredY,anchorX:tok.x,anchorY:tok.y,
          palmX:tok.palmX,palmY:tok.palmY,
          stillness:tok.stillness,quality:tok.quality}],now,aspect:16/9}).contacts;
        const primary=contacts.filter(c=>c.channel==='primary');
        states.push(primary.map(c=>c.state).join(''));
        aims.push([tok.x,tok.y]);
        const hands=primary.map(c=>({handTrackId:c.handTrackId,channel:c.channel,
          state:c.state,x:tok.x,y:tok.y}));
        const resolved=r.update({now,candidates:refs([decoy,frame]),hands});
        steps.push(resolved.length?[say(resolved[0]),Number(resolved[0].distancePx.toFixed(1))]:null);
      }
      out({
        aim:[Math.round(seen.x),Math.round(seen.y)],
        inWindow:aims.every(([x,y])=>x>0&&x<VIEWPORT.width&&y>0&&y<VIEWPORT.height),
        states:[...new Set(states)].sort(),
        firstFew:steps.slice(0,2),
        targeted:[...new Set(steps.filter(Boolean).map(s=>s[0]))],
        distances:[...new Set(steps.filter(Boolean).map(s=>s[1]))],
        withIntent:steps.filter(Boolean).length,
        /* L'image suivante, dans la grâce : le contact tient, donc la cible
           aussi — la main est partie en (1,1), en plein dans le leurre. */
        locked:(()=>{const last=r.update({now:19*16,candidates:refs([decoy,frame]),
          hands:[{handTrackId:0,channel:'primary',state:'pressed',x:1,y:1}]})[0];
          return last?[say(last),last.locked]:null})(),
      });
    """)
    # Les jetons sont en pixels de la fenêtre, toute la séquence durant.
    assert result["inWindow"] is True, "les jetons ne sont pas en pixels de la fenêtre"
    assert 0 < result["aim"][0] < 1920 and 0 < result["aim"][1] < 1080
    # Rien à viser tant que les doigts ne se rapprochent pas (décision 3).
    assert result["firstFew"] == [None, None]
    assert "pinching" in result["states"] and "pressed" in result["states"]
    # Le cadre posé autour du doigt est celui qui se résout, et le leurre en
    # unités de scène ne gagne jamais.
    assert result["targeted"] == ["win:body"], result["targeted"]
    assert result["distances"] == [0.0], "le doigt doit rester dans son cadre"
    assert result["withIntent"] > 3
    # Et le gel tient à travers la chaîne : la main part en (1,1) — en plein
    # dans le leurre — et la cible ne bouge pas.
    assert result["locked"] == ["win:body", True]


# ------------------------------------------------------------ couleurs (d. 23)


def test_the_contract_owns_the_colour_rule_and_the_channel_comes_first(tmp_path):
    """Décision 23 : corps bleu, zone de manipulation jaune, clic droit rouge.
    La règle vit dans le contrat pour que le moteur, l'aperçu et les réglages en
    lisent une seule — et le **canal** passe devant la région, parce que « clic
    droit » est une intention et non une partie du cadre : un coin visé au
    pouce-majeur est rouge, pas jaune.

    « Une seule » se vérifie : `createTargetCandidate` en portait une seconde,
    aveugle au canal, que seule la réécriture du champ par l'adaptateur rendait
    inoffensive — la documentation, elle, désignait la candidate comme le cas
    primaire de `feedbackRole`, ce qui était structurellement impossible.

    Une couleur inventée dirait à l'utilisateur qu'il va faire autre chose que
    ce qu'il fait : un canal ou une région inconnus se refusent."""

    result = run_node(tmp_path, """
      out({
        primary:['body','edge','corner'].map(r=>C.feedbackRole(r,'primary')),
        secondary:['body','edge','corner'].map(r=>C.feedbackRole(r,'secondary')),
        absent:C.feedbackRole('body'),
        tokens:C.FEEDBACK_TOKENS,
        roles:C.FEEDBACK,
        /* La candidate ne porte **aucune** couleur : elle ne connaît pas le
           canal, donc elle ne peut pas répondre à la question. Elle en portait
           une — `region===body ? body : zone` — qui rendait « jaune » là où
           l'écran affichait « rouge », et que rien n'exerçait. */
        candidate:['body','edge'].map(region=>C.createTargetCandidate({region,
          zone:region==='edge'?'top':null,boundsPx:{x:0,y:0,w:10,h:10}}).feedback),
        candidateKeys:Object.keys(C.createTargetCandidate({region:'body',
          boundsPx:{x:0,y:0,w:10,h:10}})).includes('feedback'),
        /* Et la seule règle qui reste sait, elle, distinguer les deux cas que
           la copie confondait : le même coin, deux canaux, deux couleurs. */
        corner:['primary','secondary'].map(ch=>C.feedbackRole('corner',ch)),
        badChannel:refused(()=>C.feedbackRole('body','middle')),
        badRegion:refused(()=>C.feedbackRole('milieu','primary')),
      });
    """)
    assert result["primary"] == ["body", "zone", "zone"]
    assert result["secondary"] == ["secondary", "secondary", "secondary"]
    assert result["absent"] == "body", "canal absent = primaire (règle d'absence)"
    assert result["candidate"] == [None, None], "une candidate ne décide pas d'une couleur"
    assert result["candidateKeys"] is False, "le champ est retiré, pas laissé vide"
    assert result["corner"] == ["zone", "secondary"]
    assert result["roles"] == {"BODY": "body", "ZONE": "zone", "SECONDARY": "secondary"}
    assert result["tokens"]["body"]["cssVar"] == "--bh-feedback-body"
    assert result["tokens"]["zone"]["cssVar"] == "--bh-feedback-zone"
    assert result["tokens"]["secondary"]["cssVar"] == "--bh-feedback-secondary"
    assert result["badChannel"] == "barehands_pinch_channel_unknown"
    assert result["badRegion"] == "barehands_region_unknown"


def test_the_preview_style_sheet_names_the_three_feedback_variables(tmp_path):
    """Une feuille de style ne peut pas lire le contrat. Les trois variables de
    la décision 23 sont donc écrites en clair dans la feuille de l'aperçu, et ce
    test vérifie qu'elles sont bien les trois du contrat — avec leur repli, pour
    qu'un thème muet ne rende pas un aperçu invisible."""

    result = run_node(tmp_path, "out({tokens:C.FEEDBACK_TOKENS,dom:C.DOM,"
                                "sheet:require(TARGET_PATH).STYLE});")
    tokens = result
    sheet = result["sheet"]
    barehands = SCRIPT.read_text(encoding="utf-8")
    for role, token in tokens["tokens"].items():
        assert f"var({token['cssVar']},{token['fallback']})" in sheet, role
    names = tokens["dom"]
    for key in ("targetClass", "targetZoneClass"):
        assert f"{names['rootSelector']} .{names[key]}" in sheet, key
    # La ligne des refus vit avec la pastille, donc dans la feuille du pointeur.
    assert f"{names['rootSelector']} .{names['noteClass']}" in barehands
    # Et l'aperçu se dessine dans la surimpression : pas de seconde racine à
    # exempter du balayage `inert` de la page.
    assert "jarvisTargets" not in sheet


# --------------------------------------------------------------- dans le DOM

#: Double de DOM minimal, mais avec de la **géométrie** : chaque élément déclare
#: les sélecteurs qu'il satisfait et le rectangle qu'il occupe, ce qui suffit à
#: exercer la collecte, `elementFromPoint`, et l'arbre dans lequel l'aperçu se
#: dessine (ou pas — décision 3).
#: La moitié **géométrie** du double : les éléments de page, et les deux
#: lectures d'arbre dont la collecte de cible a besoin. Elle est nommée à part
#: parce que la Slice 07 en a besoin telle quelle pour prouver qu'un réglage
#: écrit à l'écran change ce que la main atteint — et qu'un quatrième double de
#: DOM aurait dérivé de celui-ci sans que rien ne le dise.
ELEMENTS = """
const registry=[];
const node=(opts)=>{
  const o=Object.assign({sel:[],rect:null,id:'',dataset:{},label:''},opts||{});
  const classes=new Set();
  const el={children:[],className:'',id:o.id,textContent:o.label,offsetWidth:1,
    sel:o.sel,dataset:o.dataset,attrs:{},parent:null,
    style:{setProperty(k,v){this[k]=v}},
    classList:{add:c=>classes.add(c),remove:c=>classes.delete(c),
      toggle:(c,on)=>{if(on)classes.add(c);else classes.delete(c)},
      contains:c=>classes.has(c)},
    classes,
    matches(sel){return String(sel).split(',').some(one=>el.sel.includes(one.trim()))},
    closest(sel){let cur=el;while(cur){if(cur.matches&&cur.matches(sel))return cur;cur=cur.parent}return null},
    getAttribute(k){return k==='aria-label'?(o.label||null):(el.attrs[k]===undefined?null:el.attrs[k])},
    setAttribute(k,v){el.attrs[k]=String(v)},
    getBoundingClientRect(){return o.rect||{left:0,top:0,width:0,height:0}},
    dispatchEvent(){return true},
    appendChild(c){c.parent=el;el.children.push(c);return c},
    remove(){if(!el.parent)return;const at=el.parent.children.indexOf(el);
      if(at>=0)el.parent.children.splice(at,1);el.parent=null}};
  registry.push(el);
  return el;
};
/* Ce que la page contient, posé par chaque test dans `global.page`. */
global.page=[];
/* Le plus profond au point visé, donc le **dernier** dans l'ordre du document
   parmi ceux qui le contiennent : c'est ce que fait le navigateur pour des
   frères absolument positionnés. */
const pageAt=(x,y)=>global.page.filter(el=>{
  const r=el.getBoundingClientRect();
  return x>=r.left&&x<=r.left+r.width&&y>=r.top&&y<=r.top+r.height}).pop()||null;
const pageQuery=sel=>global.page.filter(el=>el.matches(sel));
"""

BROWSER = ELEMENTS + """
global.window={addEventListener(){},innerWidth:1000,innerHeight:800};
global.document={createElement:()=>node(),
  getElementById:id=>registry.find(el=>el.id===id&&el.parent)||null,
  head:node(),body:node(),
  elementFromPoint:pageAt,
  querySelectorAll:pageQuery};
global.navigator={mediaDevices:null};
global.performance={now:()=>global.clock||0};
global.clock=0;
global.requestAnimationFrame=()=>0;global.cancelAnimationFrame=()=>{};
global.setTimeout=()=>0;
global.MouseEvent=class{constructor(type,init){Object.assign(this,init||{});this.type=type}};
global.JarvisBarehandsContracts=C;
global.window.JarvisBarehandsContracts=C;
global.JarvisBarehandsTarget=require(TARGET_PATH);
/* Parcours de calibration (Slice 08) : la page l'insere entre les contrats
   et le pointeur, qui le lit pour poser `calibrate()` sur sa surface gelee. */
global.JarvisBarehandsCalibration=require(CALIBRATION_PATH);
/* La géométrie de la scène est insérée bien avant le pointeur dans la page
   (Slice 06 : les décisions 18 et 19 y vivent). Le bloc navigateur la lit
   directement, comme il lit les contrats et l'aperçu de cible. */
global.JarvisSceneInteract=require(SCENE_INTERACT_PATH);
delete require.cache[require.resolve(SCRIPT_PATH)];
require(SCRIPT_PATH);
const api=window.JarvisBarehands;
/* Les instances **vivantes**, celles que le contrôleur tient : c'est la seule
   façon d'exercer `api.targets()` sans webcam. */
const overlay=api.adapters.overlay;
overlay.mount();
const interaction=api.adapters.interaction;
const root=()=>document.body.children[0];
const previews=()=>root().children.filter(el=>el.className===C.DOM.targetClass);
const star=(id,rect,representation,label)=>node({sel:['.sc-node[data-object-id]'],rect,
  dataset:{objectId:id,representation},label:label||id});
const button=(rect,label)=>node({sel:['button'],rect,label:label||''});
/* Une image : les jetons du pointeur et les contacts que la Slice 04 publie. */
const frame=(tokens,contacts)=>{
  interaction.readContacts(()=>contacts||[]);
  interaction.hover(tokens);
};
const token=(id,x,y)=>({id,x,y,progress:0,state:'open',click:false,hover:false,quality:1});
const contact=(id,state,channel)=>({handTrackId:id,channel:channel||'primary',
  state,intent:'undecided',ratio:.3,confidence:1});
"""


def test_nothing_is_drawn_until_a_hand_shows_intent(tmp_path):
    """**Décision 3 : pas de pointeur permanent.** Ce n'est pas « caché », ni
    « transparent » : tant qu'aucune main n'approche, il n'y a **aucun élément
    d'aperçu dans l'arbre**. C'est la seule forme de la règle qu'un test peut
    vérifier, et c'est celle qui ne peut pas se perdre dans une feuille de
    style.

    Et la collecte elle-même ne part pas : le coût de la lecture du DOM n'est
    jamais payé par une session au repos."""

    result = run_node(tmp_path, BROWSER + """
      const b=button({left:100,top:100,width:80,height:30},'Activer');
      global.page=[b];
      const seen=[];
      const shot=()=>seen.push([previews().length,interaction.targets().length]);
      frame([token(1,140,115)],[contact(1,'open')]);shot();
      frame([token(1,140,115)],[contact(1,'pinching')]);shot();
      frame([token(1,140,115)],[contact(1,'pressed')]);shot();
      frame([token(1,140,115)],[contact(1,'open')]);shot();
      // Aucun contact du tout (la Slice 04 n'a rien publié) : rien non plus.
      frame([token(1,140,115)],[]);shot();
      const drawn=(()=>{frame([token(1,140,115)],[contact(1,'pinching')]);
        const el=previews()[0];
        return {feedback:el.attrs['data-feedback'],region:el.attrs['data-region'],
          left:el.style.left,top:el.style.top,width:el.style.width,height:el.style.height,
          name:el.children[1].textContent,below:el.attrs['data-name-below']}})();
      /* Une cible collée en haut de la fenêtre : l'étiquette passe dessous,
         sinon la surimpression la coupe et la cible paraît sans nom. */
      const high=(()=>{const top=button({left:100,top:4,width:80,height:30},'En haut');
        global.page=[top];
        frame([token(1,140,10)],[contact(1,'pinching')]);
        const el=previews()[0];
        return [el.attrs['data-name-below'],el.children[1].textContent]})();
      /* L'arrêt rend tout : ni survol, ni cible, ni dessin. */
      interaction.clear();
      out({seen,drawn,high,afterClear:[previews().length,interaction.targets().length]});
    """)
    assert result["seen"] == [[0, 0], [1, 1], [1, 1], [0, 0], [0, 0]]
    # Ce qui est dessiné est le cadre réel du bouton, en pixels de la fenêtre.
    assert result["drawn"]["left"] == "100px" and result["drawn"]["top"] == "100px"
    assert result["drawn"]["width"] == "80px" and result["drawn"]["height"] == "30px"
    assert result["drawn"]["feedback"] == "body" and result["drawn"]["region"] == "body"
    # Rule Zero : ce qui sera saisi porte son nom.
    assert result["drawn"]["name"] == "Activer"
    assert result["drawn"]["below"] == "0"
    assert result["high"] == ["1", "En haut"]
    assert result["afterClear"] == [0, 0]


def test_a_scene_star_is_a_candidate_and_its_zones_come_from_its_representation(tmp_path):
    """Constat F4 de la Slice 00 : `.sc-node` est **absent** du sélecteur de
    survol historique, donc une étoile est cliquable aujourd'hui sans jamais
    avoir été surlignée. Elle est ici la candidate la plus intéressante de
    toutes — la seule qui ait des zones.

    Et ses zones se lisent de `data-representation`, pas de sa classe : la
    classe porte la forme **dessinée**, qui retombe en capsule puis en point
    quand la place manque. Une fenêtre dessinée en capsule perdrait ses zones
    sans que sa géométrie ait changé."""

    result = run_node(tmp_path, BROWSER + """
      const win=star('obj-1',{left:200,top:100,width:300,height:200},'window','Tâche A');
      const point=star('obj-2',{left:600,top:100,width:26,height:26},'point','Étoile B');
      global.page=[win,point];
      const shot=(x,y)=>{frame([token(1,x,y)],[contact(1,'pinching')]);
        const t=interaction.targets()[0];
        const el=previews()[0];
        return t?{id:t.objectId,region:t.region,zone:t.zone,kind:t.kind,
          representation:t.representation,feedback:t.feedback,
          zoneShown:el.children[0].style.display,name:el.children[1].textContent}:null};
      const corner=shot(203,103);
      const edge=shot(350,102);
      const body=shot(350,200);
      /* Le coin exact de l'étoile : un cadre zoné rendrait « coin haut-gauche »
         ici, et c'est précisément ce que la décision D3 interdit à un `point`.
         Probé au centre, les deux réponses se confondent. */
      const starCorner=shot(601,101);
      const starBody=shot(610,113);
      /* Le sélecteur historique du survol, lui, ne connaît toujours pas les
         étoiles : c'est bien une autre question, et l'aperçu est la réponse. */
      const legacy=win.matches('button,a[href],input,select,textarea,label,summary,[role="button"],[role="tab"],[tabindex]:not([tabindex="-1"]),.choice,.acard,.toast');
      out({corner,edge,body,starCorner,starBody,legacy,
        published:api.targets().map(t=>[t.objectId,t.region,t.zone,t.axes,t.feedback,
          t.kind,t.schemaVersion,t.handTrackId,t.locked,'element' in t])});
    """)
    assert result["legacy"] is False, "F4 : le survol historique ignore les étoiles"
    assert result["corner"] == {
        "id": "obj-1", "region": "corner", "zone": "top_left", "kind": "scene_object",
        "representation": "window", "feedback": "zone", "zoneShown": "block", "name": "Tâche A",
    }
    assert result["edge"]["region"] == "edge" and result["edge"]["zone"] == "top"
    assert result["edge"]["feedback"] == "zone"
    assert result["body"]["region"] == "body" and result["body"]["feedback"] == "body"
    assert result["body"]["zoneShown"] == "none", "un corps ne dessine pas de barre de zone"
    # Décision D3 : une étoile `point` n'a que son corps, **même sur son coin**,
    # et sa représentation est celle qu'elle déclare, pas celle qu'on devine.
    assert result["starCorner"]["region"] == "body", "un point n'a pas de zone"
    assert result["starCorner"]["zone"] is None
    assert result["starCorner"]["representation"] == "point"
    assert result["starCorner"]["zoneShown"] == "none"
    assert result["starBody"]["region"] == "body" and result["starBody"]["zone"] is None
    # Et le cadre zoné du même écran, lui, rend bien un coin au même écart :
    # c'est la représentation qui fait la différence, pas la géométrie.
    assert result["corner"]["region"] == "corner"
    # Publiée à travers le contrat : c'est ce que la Slice 06 lira.
    # Publiée **à travers le contrat** : `axes` et `schemaVersion` viennent de
    # `createTargetCandidate`, et aucun élément du DOM ne traverse (§ 6).
    assert result["published"] == [
        ["obj-2", "body", None, [], "body", "scene_object", 1, 1, False, False]
    ]


def test_the_collection_cites_the_object_on_top_first(tmp_path):
    """Deux étoiles qui se recouvrent rendent la **même** distance : zéro. Sans
    autre critère, c'est l'ordre du document — l'ordre de création — qui
    tranche, c'est-à-dire pas ce que l'utilisateur voit. `elementFromPoint` est
    là pour ça, et pour ça seulement : il dit qui est au-dessus, il ne décide
    pas de la cible."""

    result = run_node(tmp_path, BROWSER + """
      const rect={left:100,top:100,width:200,height:200};
      const below=star('dessous',rect,'window','Dessous');
      const above=star('dessus',rect,'window','Dessus');
      // Ordre du document : `dessous` d'abord, `dessus` par-dessus.
      global.page=[below,above];
      frame([token(1,200,200)],[contact(1,'pinching')]);
      const chosen=interaction.targets()[0].objectId;
      const documentOrder=document.querySelectorAll(require(TARGET_PATH).SELECTOR)
        .map(el=>el.dataset.objectId);
      const hit=document.elementFromPoint(200,200).dataset.objectId;
      const cited=require(TARGET_PATH).collect({x:200,y:200},24).map(c=>c.objectId);
      out({chosen,documentOrder,hit,cited});
    """)
    assert result["documentOrder"] == ["dessous", "dessus"], "l'ordre du document est celui-là"
    assert result["hit"] == "dessus"
    # La collecte remet celui du dessus en tête ; le résolveur lit « le premier
    # cité », comme le contrat le fait à distance égale.
    assert result["cited"] == ["dessus", "dessous"]
    assert result["chosen"] == "dessus"


def test_a_frozen_target_keeps_its_name_when_its_object_leaves_the_collection(tmp_path):
    """Le gel porte sur le **descripteur entier**, pas seulement sur sa
    géométrie. Une fois la main partie ailleurs, l'objet capturé n'est plus
    collecté du tout : relire son nom dans la collecte de l'instant rendrait
    celui d'un autre objet — silencieusement, parce que le renvoi de candidate
    est un rang dans une liste qui a changé. L'étiquette annoncerait alors ce
    qu'on ne tient pas."""

    result = run_node(tmp_path, BROWSER + """
      const b=button({left:100,top:100,width:80,height:30},'Activer');
      const other=star('obj-9',{left:600,top:600,width:120,height:80},'window','Tâche lointaine');
      global.page=[b,other];
      const look=()=>{const el=previews()[0];const t=interaction.targets()[0];
        return [t.objectId||t.kind,t.locked,el.children[1].textContent,el.style.left]};
      frame([token(1,140,115)],[contact(1,'pinching')]);
      const approaching=look();
      frame([token(1,140,115)],[contact(1,'pressed')]);
      const down=look();
      /* La main s'en va sur l'autre objet : le bouton n'est plus collecté, et
         le rang 0 de la collecte désigne maintenant l'étoile. */
      frame([token(1,650,640)],[contact(1,'pressed')]);
      const dragged=look();
      const nowCollected=require(TARGET_PATH).collect({x:650,y:640},24).map(c=>c.name);
      out({approaching,down,dragged,nowCollected});
    """)
    assert result["approaching"] == ["button", False, "Activer", "100px"]
    assert result["down"] == ["button", True, "Activer", "100px"]
    # Ce que la collecte voit maintenant — et qui ne doit pas déteindre.
    assert result["nowCollected"] == ["Tâche lointaine"]
    assert result["dragged"] == ["button", True, "Activer", "100px"]


def test_a_right_click_intent_is_red_wherever_it_points(tmp_path):
    """Décision 23, dernier tiers. Le canal secondaire (pouce-majeur,
    décision 21) est rouge — sur un corps comme sur un coin — parce que la
    couleur dit l'**intention**, pas la partie du cadre. Les deux canaux d'une
    même main peuvent donc être à l'écran en même temps, dans deux couleurs."""

    result = run_node(tmp_path, BROWSER + """
      const win=star('obj-1',{left:100,top:100,width:300,height:200},'window','Tâche A');
      global.page=[win];
      frame([token(1,250,200),token(2,103,103)],
        [contact(1,'pinching','secondary'),contact(2,'pinching','primary')]);
      const painted=previews().map(el=>[el.attrs['data-feedback'],el.attrs['data-region']]);
      const targets=interaction.targets().map(t=>[t.channel,t.region,t.feedback]);
      out({painted:painted.sort(),targets:targets.sort(),
        pulse:require(TARGET_PATH).createTargetPreview&&true});
    """)
    assert result["targets"] == [
        ["primary", "corner", "zone"],
        ["secondary", "body", "secondary"],
    ]
    assert result["painted"] == [["secondary", "body"], ["zone", "corner"]]
    # Le battement du rouge est dans la feuille, pas dans une boucle JS.
    sheet = TARGET.read_text(encoding="utf-8")
    assert 'data-feedback="secondary"' in sheet and "jhTargetPulse" in sheet
    assert "prefers-reduced-motion" in sheet


def test_the_bar_that_is_drawn_covers_exactly_the_zone_that_was_measured(tmp_path):
    """Critère d'acceptation : « le bord ou le coin exact sélectionné surligne
    seul ». Ce qui est montré doit donc être ce qui a été mesuré — le bord
    **haut** en haut, et une équerre de coin dont seuls les deux côtés tenus
    portent un trait. Une barre décorative posée au mauvais endroit dirait à
    l'utilisateur qu'il va saisir l'autre bord, et se vérifierait à l'œil une
    seule fois, devant une caméra.

    L'épaisseur suit `bandPx`, la bande que le résolveur a réellement utilisée :
    l'aperçu ne peut pas annoncer une prise plus large ou plus étroite que celle
    qui décide."""

    result = run_node(tmp_path, """
      const T=require(TARGET_PATH);
      const at=(region,zone,bandPx)=>{
        const r=T.zoneRect({boundsPx:{x:0,y:0,w:200,h:100},bandPx:bandPx||14,region,zone});
        return [r.left,r.top,r.width,r.height,r.corner?r.hide.slice().sort():null];
      };
      out({
        top:at('edge','top'),bottom:at('edge','bottom'),
        left:at('edge','left'),right:at('edge','right'),
        topLeft:at('corner','top_left'),bottomRight:at('corner','bottom_right'),
        topRight:at('corner','top_right'),bottomLeft:at('corner','bottom_left'),
        thicker:at('edge','top',30),
        /* Les côtés d'une zone viennent du contrat, jamais d'une seconde table. */
        sides:[C.zoneSides('top_left'),C.zoneSides('bottom_right')],
      });
    """)
    assert result["sides"] == [["top", "left"], ["bottom", "right"]]
    # Chaque bord colle au sien, sur toute sa longueur.
    assert result["top"] == [0, 0, 200, 14, None]
    assert result["bottom"] == [0, 86, 200, 14, None]
    assert result["left"] == [0, 0, 14, 100, None]
    assert result["right"] == [186, 0, 14, 100, None]
    # L'équerre d'un coin : posée dans son coin, et seuls ses deux côtés tenus
    # portent un trait — les deux autres sont effacés.
    assert result["topLeft"] == [0, 0, pytest.approx(25.2), pytest.approx(25.2), ["bottom", "right"]]
    assert result["bottomRight"] == [
        pytest.approx(174.8), pytest.approx(74.8),
        pytest.approx(25.2), pytest.approx(25.2), ["left", "top"],
    ]
    assert result["topRight"][0:2] == [pytest.approx(174.8), 0]
    assert result["topRight"][4] == ["bottom", "left"]
    assert result["bottomLeft"][0:2] == [0, pytest.approx(74.8)]
    assert result["bottomLeft"][4] == ["right", "top"]
    # L'épaisseur est celle qu'on a mesurée, pas une constante de dessin.
    assert result["thicker"] == [0, 0, 200, 30, None]


def test_the_preview_can_be_switched_off_without_switching_off_the_resolution(tmp_path):
    """Décision 24 : l'aperçu est **configurable**. Le réglage appartient à la
    Slice 07 ; ce qui est à nous, c'est l'interrupteur, et surtout ce qu'il
    éteint. Il éteint le **dessin**, pas la résolution : sans cette séparation,
    couper une aide visuelle couperait aussi la manipulation, ce qu'aucun
    utilisateur ne demande en décochant « aperçu de cible ».

    Et il s'applique **tout de suite** : laisser le dernier cadre à l'écran
    jusqu'à l'image suivante rendrait un réglage appliqué indiscernable d'un
    réglage sans effet."""

    result = run_node(tmp_path, BROWSER + """
      const b=button({left:100,top:100,width:80,height:30},'Activer');
      global.page=[b];
      frame([token(1,140,115)],[contact(1,'pinching')]);
      const on=[previews().length,interaction.targets().length];
      const offImmediately=[api.targetPreview(false),previews().length];
      frame([token(1,140,115)],[contact(1,'pinching')]);
      const off=[previews().length,interaction.targets().length];
      api.targetPreview(true);
      frame([token(1,140,115)],[contact(1,'pinching')]);
      const back=[previews().length,interaction.targets().length];
      out({on,offImmediately,off,back,
        settingExists:C.SETTINGS_DEFAULTS.targetPreview,
        assistance:[api.targetAssistance(0),api.targetAssistance(2),api.targetAssistance('x')]});
    """)
    assert result["on"] == [1, 1]
    # Éteint : plus rien de dessiné dès l'appel, avant même l'image suivante.
    assert result["offImmediately"] == [False, 0]
    # Mais la cible continue d'exister : la Slice 06 la reçoit toujours.
    assert result["off"] == [0, 1]
    assert result["back"] == [1, 1]
    assert result["settingExists"] is True, "décision 24 : le réglage est au contrat"
    # L'assistance se borne au lieu de se refuser : c'est un réglage stocké.
    assert result["assistance"] == [0, 1, 1]


def test_a_disabled_control_is_never_targeted_published_or_drawn(tmp_path):
    """**Décision 3, et RÈGLE ZÉRO.** « Une candidate qui ne s'actionne pas
    n'appelle aucun retour visuel » : le contrat l'écrit noir sur blanc et le
    nomme une obligation du consommateur. `actionable` servait pourtant
    uniquement à *classer* — il n'y avait d'`if` nulle part. Un bouton
    désactivé seul sous un doigt qui pince se résolvait à d=0, se publiait à
    `targets()` et recevait un cadre bleu avec son nom. Un retour visuel qui
    promet une action impossible est pire que pas de retour du tout, et il
    aurait laissé la Slice 06 ouvrir une capture dessus.

    Les trois refus du module sont du produit, pas de la théorie :
    `button.sc-view-reset:disabled` existe dans la page de scène."""

    result = run_node(tmp_path, BROWSER + """
      const shot=()=>[previews().length,interaction.targets().length];
      const probe=el=>{global.page=[el];
        frame([token(1,140,115)],[contact(1,'pinching')]);
        const seen=shot();
        interaction.clear();
        return seen};
      const off=button({left:100,top:100,width:80,height:30},'Réinitialiser');
      off.disabled=true;
      const aria=button({left:100,top:100,width:80,height:30},'Aria');
      aria.setAttribute('aria-disabled','true');
      const inside=button({left:100,top:100,width:80,height:30},'Inerte');
      node({sel:['[inert]']}).appendChild(inside);
      /* Et sous contact : une capture ne peut pas s'ouvrir sur ce qui ne
         s'actionne pas, donc la cible ne se fige pas non plus. */
      const pressed=(()=>{global.page=[off];
        frame([token(1,140,115)],[contact(1,'pressed')]);
        const seen=shot();interaction.clear();return seen})();
      /* Le voisin actionnable, lui, est visé : la porte écarte la candidate,
         elle n'éteint pas la résolution. */
      const live=button({left:100,top:100,width:80,height:30},'Activer');
      global.page=[off,live];
      frame([token(1,140,115)],[contact(1,'pinching')]);
      const both=[previews().length,interaction.targets().length,
        previews()[0]&&previews()[0].children[1].textContent];
      interaction.clear();
      out({disabled:probe(off),aria:probe(aria),inert:probe(inside),pressed,both});
    """)
    # Rien de dessiné, et rien de publié : la Slice 06 ne le voit pas non plus.
    assert result["disabled"] == [0, 0]
    assert result["aria"] == [0, 0]
    assert result["inert"] == [0, 0]
    assert result["pressed"] == [0, 0]
    # La porte écarte une candidate, elle n'éteint pas la visée.
    assert result["both"] == [1, 1, "Activer"]


def test_the_preview_refuses_on_its_own_what_it_cannot_promise(tmp_path):
    """L'aperçu est le **consommateur** que le contrat nomme, et il doit tenir
    ses deux obligations sans dépendre de qui l'appelle — le résolveur est une
    porte, pas une excuse : la Slice 06 et les tests dessinent aussi par ici.

    Deux refus. Une candidate non actionnable ne se dessine pas (décision 3).
    Et une couleur qu'on ne sait pas nommer ne se dessine pas non plus : le
    dessin lisait `target.feedback || body`, donc un descripteur sans champ —
    exactement celui que produit la fabrique du contrat depuis qu'elle n'en
    porte plus — se serait dessiné « corps normal », en bleu, pendant qu'un
    clic droit était visé. Le rôle se **redemande** au contrat, avec le canal,
    et un refus ne se dessine pas plutôt que de retomber sur une couleur."""

    result = run_node(tmp_path, BROWSER + """
      interaction.clear();
      const P=require(TARGET_PATH).createTargetPreview();
      const t=extra=>Object.assign({handTrackId:9,channel:'primary',region:'body',
        zone:null,boundsPx:{x:0,y:0,w:40,h:20},actionable:true,locked:false,
        name:'X',radiusPx:4},extra||{});
      const draw=extra=>{P.render([t(extra)]);
        const el=previews()[0];
        const seen=[previews().length,el?el.attrs['data-feedback']:null];
        P.render([]);return seen};
      out({
        actionable:draw({}),
        /* Décision 3 : le consommateur nommé la tient lui aussi. */
        notActionable:draw({actionable:false}),
        /* Sans champ `feedback`, le rôle vient de `feedbackRole(région, canal)`
           — c'est le canal qui décide, et c'est tout l'écart entre jaune et
           rouge sur un coin. */
        derivedBody:draw({feedback:null}),
        derivedZone:draw({feedback:null,region:'corner',zone:'top_left'}),
        derivedSecondary:draw({feedback:null,channel:'secondary',
          region:'corner',zone:'top_left'}),
        /* Région ou canal illisibles : refus, pas de repli en bleu. */
        badRegion:draw({feedback:null,region:'milieu'}),
        badChannel:draw({feedback:null,channel:'milieu'}),
        empty:[previews().length,P.size()],
      });
    """)
    assert result["actionable"] == [1, "body"]
    assert result["notActionable"] == [0, None]
    assert result["derivedBody"] == [1, "body"]
    assert result["derivedZone"] == [1, "zone"]
    # Le cas que la copie aveugle au canal rendait « zone » : un coin au clic
    # droit est rouge. Sans la dérivation, il se serait dessiné en bleu.
    assert result["derivedSecondary"] == [1, "secondary"]
    assert result["badRegion"] == [0, None], "pas de couleur inventée"
    assert result["badChannel"] == [0, None]
    assert result["empty"] == [0, 0]


def test_the_legacy_hover_outline_follows_an_intention_not_a_tracked_hand(tmp_path):
    """**Décision 3 tenue à l'écran, pas seulement dans le nouveau mécanisme.**
    Le contour hérité (`jarvis-hand-hover`) s'ajoutait pour tout jeton suivi
    au-dessus d'un élément interactif : pas de pincement, pas de geste, aucune
    intention. Une main qui traverse la page entourait donc chaque bouton au
    passage — exactement le curseur permanent que la décision 3 refuse. La
    preuve « aucun élément d'aperçu dans l'arbre » ne disait rien de lui :
    elle ne parle que du nouvel aperçu.

    Deux conditions désormais, et la seconde vient de la décision 23 : la main
    a une intention, **et** l'aperçu n'entoure pas déjà cet élément. Le contour
    porte la couleur d'accent ; posé autour d'un objet déjà cerclé de bleu, de
    jaune ou de rouge, il ajouterait une quatrième couleur à une règle où la
    couleur *est* le sens.

    Ce qui ne bouge pas : la mesure. Les `pointerover`/`mouseover`, les fentes
    de pointeur et le clic sont ceux d'avant — c'est de la présentation."""

    result = run_node(tmp_path, BROWSER + """
      const b=button({left:100,top:100,width:80,height:30},'Activer');
      global.page=[b];
      const lit=()=>b.classes.has(C.DOM.hoverClass);
      const seen={};
      /* Suivie, au-dessus du bouton, sans intention : rien. */
      frame([token(1,140,115)],[contact(1,'open')]);
      seen.tracked=[lit(),previews().length];
      /* Aucun contact publié du tout : rien non plus. */
      frame([token(1,140,115)],[]);
      seen.noContact=lit();
      /* Intention, aperçu allumé : c'est l'aperçu qui dit ce qui est visé. */
      frame([token(1,140,115)],[contact(1,'pinching')]);
      seen.intentWithPreview=[lit(),previews().length];
      /* Aperçu éteint (décision 24) : le chemin de clic hérité garde son
         repère, et seulement sous intention. */
      api.targetPreview(false);
      frame([token(1,140,115)],[contact(1,'pinching')]);
      seen.intentWithoutPreview=[lit(),previews().length];
      frame([token(1,140,115)],[contact(1,'open')]);
      seen.backToTracked=lit();
      frame([token(1,140,115)],[contact(1,'pressed')]);
      seen.pressed=lit();
      interaction.clear();
      seen.afterClear=lit();
      api.targetPreview(true);
      out(seen);
    """)
    # Suivie sans intention : ni contour, ni aperçu. C'est la décision 3.
    assert result["tracked"] == [False, 0]
    assert result["noContact"] is False
    # Sous intention, l'aperçu parle — et il parle seul.
    assert result["intentWithPreview"] == [False, 1]
    # Aperçu coupé : le contour hérité reprend son rôle, sous intention.
    assert result["intentWithoutPreview"] == [True, 0]
    # Et il repart avec l'intention, sans attendre que la main s'en aille.
    assert result["backToTracked"] is False
    assert result["pressed"] is True
    assert result["afterClear"] is False


def test_a_gesture_suppressed_during_a_manipulation_says_so_on_screen(tmp_path):
    """RÈGLE ZÉRO. Le contrat étouffe les gestes pendant une capture (§ 4) et
    range la raison dans `suppressed` « plutôt que de disparaître : un geste qui
    s'évanouit sans trace est indiscernable d'un geste non reconnu ». Cette
    trace n'arrivait nulle part : à l'écran, une main qui insiste sans effet et
    rien pour dire que c'est voulu.

    Elle est donc écrite sous la pastille, avec son nom exact — une raison
    inconnue s'affiche telle quelle plutôt que d'être remplacée par une phrase
    générique, parce que ce nom est la seule information que cette ligne
    transporte."""

    result = run_node(tmp_path, BROWSER + """
      const note=()=>{const el=root().children[2];
        return [el.textContent,el.style.display]};
      overlay.render([token(1,10,10)]);
      const quiet=note();
      overlay.render([token(1,10,10)],'capture_active');
      const busy=note();
      overlay.render([token(1,10,10)],'motif_inedit');
      const unknown=note();
      overlay.render([token(1,10,10)]);
      const back=note();
      out({quiet,busy,unknown,back,
        reason:C.isGestureSuppressed('clap',null,['a'])});
    """)
    assert result["quiet"] == ["", "none"]
    assert result["busy"] == ["GESTE IGNORÉ · une main manipule", "block"]
    assert result["unknown"] == ["GESTE IGNORÉ · motif_inedit", "block"]
    assert result["back"] == ["", "none"]
    # La règle qui produit ce cas vit bien au contrat (couture de la Slice 06).
    assert result["reason"] is True


# ------------------------------------------------------------------- la page


async def test_the_page_serves_the_target_module_before_the_pointer_that_reads_it(tmp_path):
    """Constat F3 de la Slice 00 : un module de page est un repère substitué par
    le serveur, et son rang est porteur. Celui-ci lit les contrats et se fait
    lire par le pointeur : il vit exactement entre les deux."""

    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    html = (await control.index(None)).text
    raw = PAGE_HTML.read_text(encoding="utf-8")
    assert BAREHANDS_TARGET_SCRIPT_MARKER in raw, "le repère vit dans la page"
    assert (
        raw.index(BAREHANDS_CONTRACTS_SCRIPT_MARKER)
        < raw.index(BAREHANDS_TARGET_SCRIPT_MARKER)
        < raw.index(BAREHANDS_SCRIPT_MARKER)
        < raw.index(SCENE_PAGE_SCRIPT_MARKER)
    )
    assert BAREHANDS_TARGET_SCRIPT_MARKER not in html, "le repère n'a pas été remplacé"
    assert "root.JarvisBarehandsTarget=api" in html
    assert "window.JarvisBarehandsTarget" not in raw, "la page ne le définit pas elle-même"
    assert (
        html.index("root.JarvisBarehandsContracts=api")
        < html.index("root.JarvisBarehandsTarget=api")
        < html.index("function installJarvisBarehands")
    )
    assert (RUNTIME / BAREHANDS_TARGET_SCRIPT_FILE).exists()
    # La métadonnée que l'aperçu lit est posée par la page de scène, à chaque
    # passe : la mémoire de contenu de `fill` ne regarde pas la représentation,
    # donc un changement à forme dessinée constante ne la rappellerait pas.
    #
    # C'est une lecture de source, et elle est plus faible que le reste de ce
    # fichier : il n'existe pas de harnais DOM pour `installJarvisScene`. Elle
    # épingle donc les trois choses qui peuvent se perdre — la garde, l'écriture
    # et la **source** de la valeur : `node.representation` (la géométrie
    # stockée) et non `node.shape` (la forme dessinée, qui retombe quand la
    # place manque). Le reste appartient à la validation runtime de la Slice 11.
    scene = SCENE_PAGE.read_text(encoding="utf-8")
    assert "record.el.dataset.representation!==node.representation" in scene
    assert "record.el.dataset.representation=node.representation" in scene
    assert "dataset.representation=node.shape" not in scene
    # Et l'attribut lu par l'aperçu est bien celui-là.
    assert "el.dataset&&el.dataset.representation" in TARGET.read_text(encoding="utf-8")


def test_the_target_module_reads_the_page_but_never_the_scene_units(tmp_path):
    """Deux espaces, jamais mélangés. Le module de cible travaille en pixels de
    la fenêtre de bout en bout ; les unités de scène (±160 × ±90) vivent dans
    `control_center_scene_interact.js` et n'entrent pas ici. Un mélange se
    déboguerait comme un défaut de géométrie dans le mauvais module — c'est la
    raison pour laquelle le contrat a renommé ses champs `boundsPx` et
    `distancePx`."""

    source = TARGET.read_text(encoding="utf-8")
    for forbidden in ("JarvisSceneLayout", "JarvisSceneInteract", "toScreen", "halfWidth", "SAFE_AREA"):
        assert forbidden not in source, forbidden
    # Il lit la page, il ne la modifie pas : aucun écouteur, aucun réseau.
    for forbidden in ("fetch(", "XMLHttpRequest", "addEventListener", "localStorage"):
        assert forbidden not in source, forbidden
    # Et il ne parle jamais d'un élément du DOM au contrat (§ 6).
    assert "element:el" in source and "element" not in run_node(
        tmp_path, "out(Object.keys(C.createTargetCandidate({region:'body',boundsPx:{x:0,y:0,w:1,h:1}})));"
    )
