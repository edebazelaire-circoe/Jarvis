"""Identité de main, filtrage adaptatif et traits de mouvement (Slice 03),
exécutés par node.

Deux mains devant une caméra ne se testent pas ici. Ce qui l'est : qu'une
identité de piste survive à un croisement, à un trou d'une image et à une
étiquette de latéralité qui bascule ; qu'elle ne survive **pas** à une absence
plus longue que la grâce, ni à une boucle d'images arrêtée ; que le filtre
adaptatif gagne *à la fois* sur le tremblement du repos et sur le retard en
mouvement rapide, parce que gagner sur l'un en perdant sur l'autre est le
compromis qu'il remplace ; que vitesse et immobilité disent la vérité sur un
trajet connu ; et que la qualité de suivi note ce qu'elle promet de noter.

L'horloge est injectée : aucune attente réelle, aucun minuteur.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
SCRIPT = RUNTIME / "control_center_barehands.js"
CONTRACTS = RUNTIME / "control_center_barehands_contracts.js"
TARGET = RUNTIME / "control_center_barehands_target.js"
CALIBRATION = RUNTIME / "control_center_barehands_calibration.js"
TUTORIAL = RUNTIME / "control_center_barehands_tutorial.js"
SCENE_INTERACT = RUNTIME / "control_center_scene_interact.js"


def run_node(tmp_path: Path, source: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "barehands-tracking.cjs"
    script.write_text(
        f"const B=require({json.dumps(str(SCRIPT))});\n"
        f"const C=require({json.dumps(str(CONTRACTS))});\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "const refused=fn=>{try{fn();return null}catch(e){return e.code||e.name}};\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


#: Main synthétique repérée par le **centre de sa paume** (cx, cy), la paume
#: mesurant `palm` du poignet à la base du majeur, l'index au-dessus et le
#: pouce à `gap` paumes de l'index. Toutes les positions utilisées restent
#: loin des bords de l'image : le cadrage ne dégrade rien sauf quand un test
#: le demande explicitement.
HAND = """
function hand(cx,cy,opts){
  const o=Object.assign({gap:.5,palm:.2},opts||{});
  const lm=Array.from({length:21},()=>({x:cx,y:cy,z:0}));
  lm[0]={x:cx,y:cy+o.palm/2,z:0};
  lm[9]={x:cx,y:cy-o.palm/2,z:0};
  lm[8]={x:cx,y:cy-o.palm*1.2,z:0};
  lm[4]={x:cx+o.palm*o.gap,y:lm[8].y,z:0};
  return lm;
}
const scene=(hands,names)=>({landmarks:hands,
  handedness:(names||[]).map(n=>[{categoryName:n,score:.95}])});
const frame=now=>({viewport:{width:1000,height:800},aspect:1,now});
"""


# ------------------------------------------------------------------ identité


def test_two_hands_that_cross_keep_their_identity(tmp_path):
    """Le cas que la latéralité ne sait pas traiter. Deux mains se croisent :
    à l'image du croisement, chaque détection est **plus proche de la dernière
    position de l'autre piste** que de la sienne. Le plus-proche-voisin nu
    échange alors les deux identités au milieu du geste — c'est-à-dire les
    deux `pointerId`, les deux pincements et les deux captures.

    Ici les deux mains portent la **même** étiquette, pour que l'indice de
    latéralité ne puisse pas sauver l'association : seule la continuité
    spatiale décide, par la prédiction de vitesse."""

    result = run_node(tmp_path, HAND + """
      const t=B.createHandTracker({});
      const ids=[],xs=[];
      for(let i=0;i<6;i+=1){
        const a=.20+.12*i,b=.80-.12*i;
        const step=t.update(scene([hand(a,.5),hand(b,.5)],['Left','Left']),frame(i*33));
        ids.push(step.tokens.map(k=>k.id));
        xs.push([Number(a.toFixed(2)),Number(b.toFixed(2))]);
      }
      out({ids,xs,tracks:t.size()});
    """)
    # Les deux mains traversent bien l'une devant l'autre.
    assert result["xs"][0] == [0.2, 0.8] and result["xs"][5] == [0.8, 0.2]
    # La détection 0 est toujours la main partie de la gauche : son identité ne
    # doit pas changer quand elle passe à droite.
    assert result["ids"] == [[0, 1]] * 6, "les identités ont été échangées au croisement"
    assert result["tracks"] == 2, "personne n'a ouvert de piste supplémentaire"


def test_identity_survives_a_one_frame_dropout_but_not_a_real_absence(tmp_path):
    """Un trou d'une image est un défaut du traqueur, pas une main qui part :
    lui coûter son identité casserait la capture en cours. Une absence plus
    longue que la grâce, elle, est une vraie perte — la main suivante est une
    autre main, et prétendre le contraire lui donnerait la capture de la
    précédente.

    Au retour, l'identité tient mais la **confiance** retombe : on *suppose*
    que c'est la même main, et c'est exactement ce que `quality` doit dire."""

    result = run_node(tmp_path, HAND + """
      const t=B.createHandTracker({});
      const one=at=>t.update(scene([hand(.40,.5)],['Left']),frame(at));
      const seen=[];
      for(const at of [0,33,66])seen.push(one(at));
      t.update(scene([],[]),frame(99));                 // une image sans main
      for(const at of [132,165])seen.push(one(at));
      const short=seen.map(s=>s.tokens[0].id);
      const quality=seen.map(s=>Number(s.tokens[0].quality.toFixed(3)));

      const u=B.createHandTracker({});
      const far=[0,33,66].map(at=>u.update(scene([hand(.40,.5)],['Left']),frame(at)).tokens[0].id);
      // Plus long que `lostGraceMs` : la main d'après est une autre main.
      far.push(u.update(scene([hand(.40,.5)],['Left']),frame(66+400)).tokens[0].id);

      // Boucle d'images arrêtée (onglet en arrière-plan) : aucune image ne
      // passe pendant dix secondes, donc aucune purge ne s'exécute.
      const v=B.createHandTracker({});
      v.update(scene([hand(.40,.5)],['Left']),frame(0));
      const resurrected=v.update(scene([hand(.40,.5)],['Left']),frame(10000)).tokens[0].id;
      out({short,quality,far,resurrected,tracks:t.size()});
    """)
    assert result["short"] == [0, 0, 0, 0, 0], "un trou d'une image a coûté l'identité"
    assert result["tracks"] == 1
    # Installée avant le trou, devinée juste après : la qualité le dit.
    assert result["quality"][2] == 1
    assert result["quality"][3] == pytest.approx(1 / 3, abs=0.001)
    assert result["quality"][4] == pytest.approx(2 / 3, abs=0.001)
    assert result["far"] == [0, 0, 0, 1], "une absence longue doit donner une identité neuve"
    # Le temps non observé ne se crédite pas : une piste ne ressuscite pas
    # parce que personne n'a regardé entre-temps.
    assert result["resurrected"] == 1


def test_the_order_the_tracker_lists_its_hands_in_is_not_an_identity(tmp_path):
    """Rien ne promet que le traqueur rende ses mains dans le même ordre d'une
    image à l'autre. L'identité ne doit donc tenir ni à l'indice dans le
    tableau, ni à l'étiquette qui l'accompagne : l'appariement se fait sur
    **toutes** les paires, pas rang par rang.

    Les deux mains ne bougent pas ; seul l'ordre de la liste s'inverse. Les
    identités doivent suivre les mains, donc s'inverser dans la sortie."""

    result = run_node(tmp_path, HAND + """
      const t=B.createHandTracker({});
      const left=hand(.42,.5),right=hand(.58,.5);
      const steps=[];
      for(let i=0;i<6;i+=1){
        const flipped=i>=3;
        const step=t.update(flipped?scene([right,left],['Right','Left'])
                                   :scene([left,right],['Left','Right']),frame(i*33));
        steps.push(step.tokens.map(k=>[k.id,Math.round(k.rawX)]));
      }
      out({steps,tracks:t.size()});
    """)
    listed = result["steps"]
    # Avant le retournement : piste 0 à gauche, piste 1 à droite.
    assert listed[2][0][0] == 0 and listed[2][1][0] == 1
    # Après : la liste est inversée, les identités suivent les mains.
    assert listed[3][0][0] == 1 and listed[3][1][0] == 0
    # Et chaque identité est restée sur sa position d'écran.
    left_px = [x for step in listed for (i, x) in step if i == 0]
    assert len(set(left_px)) == 1, "la piste 0 a changé de main"
    assert result["tracks"] == 2, "personne n'a ouvert de piste supplémentaire"


#: Séparation des deux paumes, **en paumes**, de part et d'autre de la valeur
#: qui volait une identité avant la reprise de cette Slice. La prime d'accord
#: valait 0,35 paume et était soustraite au coût : deux étiquettes qui
#: basculent sur la même image payaient l'échange `(d − 0,35) × 2` contre `0`
#: pour l'appariement juste, donc **l'échange gagnait sous 0,35** (seuil mesuré
#: au millième : tenu à 0,36, volé à 0,34). Le test d'avant plaçait les mains à
#: 0,8 paume, 2,3 fois au-dessus : il ne prouvait rien là où ça mordait.
#:
#: 0,35 paume ≈ 3 cm entre deux centres de paume — deux mains qui se recouvrent,
#: c'est-à-dire exactement la seule image où MediaPipe retourne les deux
#: étiquettes à la fois.
FLIP_SEPARATIONS_PALMS = [0.8, 0.4, 0.36, 0.34, 0.3, 0.2, 0.1, 0.05, 0.02]


@pytest.mark.parametrize("separation", FLIP_SEPARATIONS_PALMS)
def test_a_handedness_label_that_flips_never_steals_an_identity(tmp_path, separation):
    """La latéralité est un **indice**, jamais une clé. Le traqueur réétiquette
    une main vue de profil d'une image à l'autre ; si l'étiquette était
    l'identité — ce qu'elle était avant cette Slice — les deux mains
    échangeaient leur pointeur sur une seule image mal lue.

    Elle départage désormais **à distance totale égale**, en clé secondaire de
    l'attribution, et ne peut donc rien renverser : à toute séparation non
    nulle, l'appariement juste coûte strictement moins cher que l'échange.
    C'est pourquoi le test balaie des séparations de part et d'autre de
    l'ancien seuil de vol au lieu de se poser confortablement au-dessus.

    Et l'étiquette de la piste, elle, se vote : une image contraire ne la
    retourne pas, trois d'affilée oui — c'est une correction d'indice, pas un
    vol d'identité."""

    result = run_node(tmp_path, HAND + """
      const t=B.createHandTracker({});
      const steps=[];
      // Deux mains séparées de `sep` paumes, les deux étiquettes basculant sur
      // la même image — ce que fait MediaPipe quand elles se recouvrent.
      const sep=%f,palm=.2,d=sep*palm/2;
      const names=i=>i<3?['Left','Right']:['Right','Left'];
      for(let i=0;i<8;i+=1){
        const step=t.update(scene([hand(.5-d,.5,{palm}),hand(.5+d,.5,{palm})],names(i)),frame(i*33));
        steps.push([step.tokens.map(k=>k.id),step.tokens.map(k=>k.handedness)]);
      }
      out({steps,tracks:t.size()});
    """ % separation)
    ids = [step[0] for step in result["steps"]]
    handedness = [step[1] for step in result["steps"]]
    assert ids == [[0, 1]] * 8, (
        f"une étiquette qui bascule a volé une identité à {separation} paume de séparation")
    assert result["tracks"] == 2
    # Trois images d'accord installent la latéralité…
    assert handedness[:3] == [["left", "right"]] * 3
    # …et une seule image contraire ne la retourne pas.
    assert handedness[3] == ["left", "right"]
    assert handedness[4] == ["left", "right"]
    # Trois images contraires d'affilée, si : l'indice se corrige, l'identité
    # de piste ne bouge toujours pas.
    assert handedness[5] == ["right", "left"]


def test_a_handedness_bonus_subtracted_from_the_cost_is_refused_at_construction(tmp_path):
    """Le réglage qui portait le défaut n'est pas laissé inerte : `options()` le
    refuse, comme `smoothing` avant lui. Un appelant qui le passe encore
    l'apprend à la construction — sinon un réglage sans effet serait
    indiscernable d'un réglage appliqué, et la question « pourquoi les deux
    mains échangent-elles encore leur pointeur ? » se poserait trois Slices
    plus loin."""

    result = run_node(tmp_path, """
      out({
        gone:B.DEFAULTS.handednessBonusPalms===undefined,
        refused:['createHandTracker','createHandTrackManager','createPointerFilter']
          .map(name=>refused(()=>B[name]({handednessBonusPalms:.35}))),
        says:(()=>{try{B.createHandTracker({handednessBonusPalms:.35})}
                   catch(e){return /distance égale/.test(e.message)}return false})(),
      });
    """)
    assert result["gone"] is True
    assert result["refused"] == ["RangeError"] * 3
    assert result["says"] is True, "le refus doit nommer ce qui remplace le réglage"


def test_the_pairing_kept_is_always_the_one_of_smallest_total_distance(tmp_path):
    """R2 : l'élagage de `assign` n'est un vrai séparation-évaluation que si les
    coûts sont **positifs ou nuls** — un total partiel doit minorer le total
    final. La prime soustraite les mettait dans [−0,35 ; 1,6], et la recherche
    jetait alors de vrais optimums : 670 attributions non minimales sur 300 000
    matrices 2×2 tirées au hasard, mesurées par la QA.

    Ce test est ce qui attrape la réintroduction d'un coût négatif, quelle
    qu'en soit la forme. Il ne lit pas le code : il tire des géométries au
    hasard, calcule la meilleure somme de distances par force brute — les sept
    attributions possibles à deux détections et deux pistes — et exige que le
    gestionnaire n'en rende jamais une moins bonne.

    Le second volet est le même échantillon lu à l'envers : **l'ordre des
    détections n'est pas une identité**. Le test dédié plus haut le montre sur
    un cas symétrique, qui passait déjà avec la recherche cassée ; celui-ci
    l'exige sur des milliers de géométries quelconques, où un appariement qui
    dépend du rang dans le tableau se voit."""

    result = run_node(tmp_path, """
      let seed=987654321;
      const rnd=()=>{seed=(seed*1103515245+12345)&0x7fffffff;return seed/0x7fffffff};
      const PALM=.2,RADIUS=1.6;
      const gap=(t,d)=>Math.hypot(t.x-d.x,t.y-d.y)/PALM;
      let nonMinimal=0,orderDependent=0,swaps=0,newTracks=0,outOfGate=0;
      for(let trial=0;trial<4000;trial+=1){
        const A={x:.3+rnd()*.4,y:.3+rnd()*.4},Bt={x:.3+rnd()*.4,y:.3+rnd()*.4};
        // Détections tirées autour des deux pistes : assez près pour que la
        // porte s'ouvre, assez loin pour que l'échange soit parfois le bon.
        const near=v=>Math.max(.02,Math.min(.98,v));
        const P={x:near(A.x+(rnd()-.5)*.9),y:near(A.y+(rnd()-.5)*.9)};
        const Q={x:near(Bt.x+(rnd()-.5)*.9),y:near(Bt.y+(rnd()-.5)*.9)};
        // Étiquettes tantôt d'accord, tantôt inversées, tantôt absentes.
        const labels=[['Left','Right'],['Right','Left'],['','']][trial%3];
        const seeded=()=>{
          const m=B.createHandTrackManager({});
          m.update({hands:[{x:A.x,y:A.y,palm:PALM,handedness:'Left',handednessConfidence:.9},
                           {x:Bt.x,y:Bt.y,palm:PALM,handedness:'Right',handednessConfidence:.9}],
                    now:0,aspect:1});
          return m;
        };
        const det=[{x:P.x,y:P.y,palm:PALM,handedness:labels[0],handednessConfidence:.9},
                   {x:Q.x,y:Q.y,palm:PALM,handedness:labels[1],handednessConfidence:.9}];
        const forward=seeded().update({hands:det,now:33,aspect:1}).map(e=>e.handTrackId);
        const backward=seeded().update({hands:[det[1],det[0]],now:33,aspect:1}).map(e=>e.handTrackId);
        // Force brute : coût d'une piste neuve = la porte, comme dans `assign`.
        const cost=(track,detection)=>{
          const g=gap(track===0?A:Bt,detection===0?P:Q);
          return g<=RADIUS?g:null;
        };
        let best=Infinity;
        for(const pair of [[0,1],[1,0],[0,-1],[1,-1],[-1,0],[-1,1],[-1,-1]]){
          const a=pair[0]<0?RADIUS:cost(pair[0],0),b=pair[1]<0?RADIUS:cost(pair[1],1);
          if(a===null||b===null)continue;
          best=Math.min(best,a+b);
        }
        const priced=(id,detection)=>{
          if(id>1)return RADIUS;                       // piste neuve
          const c=cost(id,detection);
          return c===null?RADIUS:c;
        };
        const total=priced(forward[0],0)+priced(forward[1],1);
        if(total>best+1e-9)nonMinimal+=1;
        /* La porte est une porte : une piste retenue au-delà de
           `matchRadiusPalms` n'est pas un appariement moins bon, c'est un
           appariement qui n'aurait pas dû exister. */
        forward.forEach((id,i)=>{if(id<=1&&cost(id,i)===null)outOfGate+=1});
        /* Lue à l'envers, la même géométrie doit rendre le même appariement.
           Le **numéro** d'une piste neuve, lui, suit forcément l'ordre de la
           liste — il n'est attribué qu'au moment où la détection est traitée —
           donc on compare « quelle piste installée » et non « quel numéro ».
           Toutes les pistes neuves se valent ici : aucune n'a d'histoire. */
        const settled=id=>(id>1?-1:id);
        if(!(settled(backward[0])===settled(forward[1])
            &&settled(backward[1])===settled(forward[0])))orderDependent+=1;
        if(forward[0]===1&&forward[1]===0)swaps+=1;
        if(forward[0]>1||forward[1]>1)newTracks+=1;
      }
      out({nonMinimal,orderDependent,swaps,newTracks,outOfGate});
    """)
    assert result["nonMinimal"] == 0, "la recherche a rendu une attribution non minimale"
    assert result["outOfGate"] == 0, "une détection a été appariée au-delà de la porte"
    assert result["orderDependent"] == 0, "l'appariement a dépendu de l'ordre des détections"
    # L'échantillon exerce bien les trois issues, sinon il ne prouverait rien :
    # l'appariement direct, l'échange, et la piste neuve hors de la porte.
    assert result["swaps"] > 100, result
    assert result["newTracks"] > 100, result


def test_what_breaks_a_tie_is_handedness_then_the_worst_pair_never_the_list_order(tmp_path):
    """L'autre moitié de R2. Le balayage ci-dessus tire des géométries
    quelconques, où deux attributions n'ont jamais exactement la même somme ;
    ici les sommes sont **égales par construction**, et c'est là que se voit ce
    qui départage.

    Trois clés, dans l'ordre : la somme des écarts, puis les désaccords de
    latéralité, puis les écarts triés du plus grand au plus petit. « La
    première trouvée » n'en est pas une — c'est le rang dans le tableau, et
    l'ordre où le traqueur rend ses mains n'est pas une identité. Chaque cas
    est donc joué **dans les deux sens**, et les deux lectures doivent rendre
    le même appariement.

    Les deux géométries :

    - *latéralité* — deux détections à égale distance des deux pistes, une de
      chaque côté. Seules les étiquettes peuvent trancher, et elles tranchent
      pour l'échange quand c'est l'échange qui les accorde ;
    - *pire paire* — deux détections placées à droite des deux pistes, sans
      étiquette : `0,10 + 0,10` contre `0,05 + 0,15`, même somme. On garde
      celle dont la pire paire est la moins mauvaise, parce que c'est la seule
      réponse qui ne dépende pas de l'ordre de la liste."""

    result = run_node(tmp_path, """
      const PALM=.2;
      const seeded=(a,b)=>{
        const m=B.createHandTrackManager({});
        m.update({hands:[{x:a.x,y:a.y,palm:PALM,handedness:'Left',handednessConfidence:.9},
                         {x:b.x,y:b.y,palm:PALM,handedness:'Right',handednessConfidence:.9}],
                  now:0,aspect:1});
        return m;
      };
      const both=(a,b,p,q)=>{
        const one=(first,second)=>seeded(a,b)
          .update({hands:[first,second],now:33,aspect:1}).map(e=>e.handTrackId);
        const forward=one(p,q),backward=one(q,p);
        return {forward,backward,mirrored:backward[0]===forward[1]&&backward[1]===forward[0]};
      };
      const det=(x,y,name)=>({x,y,palm:PALM,handedness:name,handednessConfidence:.9});
      /* Égalité parfaite : les deux détections sont sur la médiatrice des deux
         pistes, donc les quatre écarts sont deux à deux identiques. */
      const A={x:.4,y:.5},Bt={x:.6,y:.5};
      const agreeing=both(A,Bt,det(.5,.45,'Left'),det(.5,.55,'Right'));
      const crossed=both(A,Bt,det(.5,.45,'Right'),det(.5,.55,'Left'));
      /* Même somme, écarts différents : 0,10 + 0,10 contre 0,05 + 0,15, sans
         étiquette pour départager. */
      const C0={x:.45,y:.5},C1={x:.50,y:.5};
      const worst=both(C0,C1,det(.55,.5,''),det(.60,.5,''));
      /* Une étiquette **absente** ne vote ni pour ni contre — même règle que
         le vote de latéralité. Ici la piste de gauche n'a jamais reçu
         d'étiquette et la détection de droite n'en porte pas : compter ces
         deux inconnues comme des désaccords ferait gagner l'échange, alors
         que rien ne le dit. */
      const unlabelled=(()=>{
        const one=(first,second)=>{
          const m=B.createHandTrackManager({});
          m.update({hands:[{x:C0.x,y:C0.y,palm:PALM,handedness:'',handednessConfidence:0},
                           {x:C1.x,y:C1.y,palm:PALM,handedness:'Right',handednessConfidence:.9}],
                    now:0,aspect:1});
          return m.update({hands:[first,second],now:33,aspect:1}).map(e=>e.handTrackId);
        };
        const p=det(.55,.5,'Right'),q=det(.60,.5,'');
        const forward=one(p,q),backward=one(q,p);
        return {forward,backward,mirrored:backward[0]===forward[1]&&backward[1]===forward[0]};
      })();
      out({agreeing,crossed,worst,unlabelled});
    """)
    # Étiquettes d'accord avec la géométrie : chacun chez soi.
    assert result["agreeing"]["forward"] == [0, 1]
    assert result["agreeing"]["mirrored"] is True
    # Étiquettes croisées, distances identiques : c'est l'échange qui accorde
    # les deux, donc c'est l'échange. La latéralité tranche **ici**, et
    # seulement ici — jamais contre la géométrie.
    assert result["crossed"]["forward"] == [1, 0]
    assert result["crossed"]["mirrored"] is True
    # À somme égale et sans étiquette : la pire paire décide (0,10 plutôt que
    # 0,15), et la réponse ne change pas quand la liste s'inverse.
    assert result["worst"]["forward"] == [0, 1]
    assert result["worst"]["mirrored"] is True
    # Deux inconnues — une piste jamais étiquetée, une détection sans
    # étiquette — ne font pas deux désaccords : la clé 2 reste muette et c'est
    # la pire paire qui décide, comme au cas précédent. Les compter ferait
    # gagner l'échange sur une preuve qui n'existe pas.
    assert result["unlabelled"]["forward"] == [0, 1]
    assert result["unlabelled"]["mirrored"] is True


# -------------------------------------------------------------------- filtre


#: Le lissage exponentiel fixe d'avant la Slice 03, reconstruit ici pour que la
#: comparaison porte sur le comportement et non sur deux nombres choisis.
FIXED = """
const fixedSmoothing=alpha=>{let p=null;return x=>{p=p===null?x:p+(x-p)*alpha;return p}};
let seed=12345;
const noise=()=>{seed=(seed*1103515245+12345)&0x7fffffff;return seed/0x7fffffff*2-1};
"""


def test_the_filter_wins_at_rest_and_in_fast_motion_at_the_same_time(tmp_path):
    """Le fond de cette Slice. Un lissage à coefficient fixe ne peut pas tenir
    les deux bouts : bas, il calme le repos et traîne ; haut, il suit le geste
    et laisse passer le tremblement. `smoothing:.45` était le milieu qui rate
    les deux.

    Les deux mesures sont donc dans **le même test**, exprès : améliorer le
    repos en dégradant le retard (ou l'inverse) n'est pas un progrès, c'est le
    compromis qu'on vient de refuser. Mettre `betaCutoff` à 0 rend le filtre
    meilleur au repos et pire que le fixe en mouvement ; le monter beaucoup
    fait l'inverse. Les deux mutations font tomber ce test."""

    result = run_node(tmp_path, FIXED + """
      // Repos : main posée à (500,400) qui tremble de ±3 px.
      let f=B.createPointerFilter(),fx=fixedSmoothing(.45),fy=fixedSmoothing(.45);
      let adaptive=0,fixed=0,count=0;
      for(let i=0;i<200;i+=1){
        const x=500+noise()*3,y=400+noise()*3;
        const a=f.update({x,y},i*16);const bx=fx(x),by=fy(y);
        if(i>40){adaptive+=(a.x-500)**2+(a.y-400)**2;fixed+=(bx-500)**2+(by-400)**2;count+=1}
      }
      const restAdaptive=Math.sqrt(adaptive/count),restFixed=Math.sqrt(fixed/count);

      // Mouvement franc : 1500 px/s pendant une seconde.
      f=B.createPointerFilter();fx=fixedSmoothing(.45);
      let lagAdaptive=0,lagFixed=0;
      for(let i=0;i<60;i+=1){
        const x=100+1500*(i*16/1000);
        const a=f.update({x,y:0},i*16),b=fx(x);
        lagAdaptive=Math.abs(a.x-x);lagFixed=Math.abs(b-x);
      }
      out({restAdaptive,restFixed,lagAdaptive,lagFixed,
           restRatio:restAdaptive/restFixed,lagRatio:lagAdaptive/lagFixed});
    """)
    # Au repos : moitié moins de tremblement résiduel que le lissage fixe.
    assert result["restRatio"] < 0.7, result
    # En mouvement : moins d'un tiers du retard. Le jeton d'hier traînait de
    # presque 30 px derrière un geste franc — assez pour cliquer à côté.
    assert result["lagRatio"] < 0.5, result
    assert result["lagFixed"] > 25 and result["lagAdaptive"] < 15


def test_the_filter_refuses_to_credit_time_it_did_not_observe(tmp_path):
    """Reprise de la leçon de la Slice 02, dans un autre module. Une vitesse
    calculée à travers un trou est une invention : la main a pu aller
    n'importe où. Le filtre repart du point présent plutôt que de traverser le
    trou à grande vitesse — sans quoi la première image du retour d'un onglet
    en arrière-plan publie un jeton qui file à 40 000 px/s, et l'immobilité que
    les Slices 04-06 liront est fausse au pire moment."""

    result = run_node(tmp_path, """
      const f=B.createPointerFilter();
      f.update({x:100,y:100},0);f.update({x:104,y:100},16);
      const across=f.update({x:900,y:100},16+5000);      // 5 s sans rien voir
      const g=B.createPointerFilter();
      g.update({x:100,y:100},0);g.update({x:104,y:100},16);
      const within=g.update({x:120,y:100},32);           // image suivante, normale
      const h=B.createPointerFilter();
      h.update({x:100,y:100},0);
      const sameInstant=h.update({x:400,y:100},0);       // deux mesures, aucun temps
      out({across:[across.x,across.vxPxPerSec],
           within:[Number(within.vxPxPerSec.toFixed(0))],
           sameInstant:[sameInstant.x,sameInstant.vxPxPerSec]});
    """)
    # Le filtre repart sur le point présent, sans vitesse inventée.
    assert result["across"] == [900, 0]
    assert result["within"][0] > 0
    # Horodatage identique : ni division par zéro, ni vitesse infinie.
    assert result["sameInstant"] == [100, 0]


def test_velocity_and_stillness_are_right_on_a_known_path(tmp_path):
    """Trajet connu, à travers le traqueur complet : main posée qui tremble,
    puis main qui file à une vitesse d'écran calculable. `stillness` doit
    valoir 1 pendant le repos **malgré** le tremblement — mesurée sur le point
    brut elle vaudrait 0, un tremblement de 3 px à 60 Hz se lisant 187 px/s."""

    result = run_node(tmp_path, HAND + """
      let seed=7;const noise=()=>{seed=(seed*1103515245+12345)&0x7fffffff;return seed/0x7fffffff*2-1};
      const t=B.createHandTracker({margin:0,mirror:false});
      // Viewport 1000 px de large, marge nulle : cx .001 = 1 px d'écran.
      let last=null;
      for(let i=0;i<20;i+=1)last=t.update(scene([hand(.40+noise()*.003,.5)],['Left']),frame(i*16)).tokens[0];
      const still={stillness:last.stillness,stillMs:last.stillMs,
        speed:last.speedPxPerSec,jitterPx:Math.abs(last.rawX-last.filteredX)};
      // Puis 30 images à .015 par image = 15 px / 16 ms = 937,5 px/s.
      for(let i=0;i<30;i+=1)last=t.update(scene([hand(.40+.015*(i+1),.5)],['Left']),frame((20+i)*16)).tokens[0];
      out({still,moving:{vx:last.vxPxPerSec,vy:last.vyPxPerSec,speed:last.speedPxPerSec,
        stillness:last.stillness,stillMs:last.stillMs}});
    """)
    # Repos : immobile, et immobile depuis 19 images de 16 ms.
    assert result["still"]["stillness"] == 1
    assert result["still"]["stillMs"] == pytest.approx(19 * 16, abs=1)
    assert result["still"]["speed"] < 28
    # Le filtre travaille : le brut et le filtré ne coïncident pas au repos.
    assert result["still"]["jitterPx"] > 0
    # Mouvement : 937,5 px/s attendus, à 10 % près.
    assert result["moving"]["vx"] == pytest.approx(937.5, rel=0.1)
    assert abs(result["moving"]["vy"]) < 30
    assert result["moving"]["speed"] == pytest.approx(937.5, rel=0.1)
    # Au-dessus de `moveSpeedPx` : plus rien d'immobile, et le compteur est nul.
    assert result["moving"]["stillness"] == 0 and result["moving"]["stillMs"] == 0


def test_the_published_velocity_takes_its_time_to_admit_a_stop_or_a_reversal(tmp_path):
    """R3 : le régime établi est exact, le **transitoire** ne l'est pas, et les
    tests d'avant cette reprise ne couvraient qu'une rampe régulière et un
    repos régulier — jamais le moment où la main change d'avis.

    La vitesse publiée est lissée à `dCutoffHz` = 1 Hz, soit τ ≈ 159 ms. Ce
    n'est pas un réglage mal choisi : la même coupure basse est ce qui empêche
    le tremblement du repos de se lire comme un mouvement. Mais elle borne ce
    que les Slices 04 à 06 peuvent décider, et ce test **épingle les quatre
    nombres** que le contrat publie, pour qu'une retouche de `dCutoffHz` les
    déplace au vu de tous plutôt qu'en silence.

    Conséquence la plus utile à retenir : une main qui arrive vite et pince
    aussitôt se lit *en mouvement, `stillMs` = 0*. `stillMs` ne sait pas
    reconnaître une immobilité plus courte que ~600 ms."""

    result = run_node(tmp_path, """
      // Trajet en pixels d'écran, images de 16 ms : 900 px/s pendant 1 s, puis
      // soit l'arrêt net, soit l'inversion franche.
      const trace=reverse=>{
        const f=B.createPointerFilter(),s=B.createStillness();
        let x=100;const rows=[];
        for(let i=0;i<200;i+=1){
          const at=i*16,v=at<1000?900:(reverse?-900:0);
          x+=v*.016;
          const m=f.update({x,y:0},at);
          const st=s.update(m.speedPxPerSec,at);
          rows.push({t:at-1000,vx:m.vxPxPerSec,speed:m.speedPxPerSec,
                     stillness:st.stillness,stillMs:st.stillMs});
        }
        return rows.filter(r=>r.t>=0);
      };
      const stopped=trace(false),reversed=trace(true);
      const firstAt=(rows,ok)=>{const hit=rows.find(ok);return hit?hit.t:null};
      const wrongSign=reversed.filter(r=>r.vx>0);
      out({
        halfStillAt:firstAt(stopped,r=>r.stillness>=.5),
        fullStillAt:firstAt(stopped,r=>r.stillness>=1),
        stillMsStartsAt:firstAt(stopped,r=>r.stillMs>0),
        // La vitesse garde le signe de l'aller alors que la main est repartie
        // dans l'autre sens : le dernier instant où elle se trompe.
        wrongSignUntil:wrongSign.length?wrongSign[wrongSign.length-1].t:0,
        reaches90At:firstAt(reversed,r=>r.vx<=-810),
        // Régime établi, pour montrer que c'est bien le transitoire qui coûte.
        settled:reversed[reversed.length-1].vx,
        // Et ce que voit un pincement décidé tout de suite après l'arrêt.
        stillnessAt150:stopped.find(r=>r.t>=150).stillness,
      });
    """)
    # Arrêt net d'une main à 900 px/s : l'immobilité met une demi-seconde à se
    # dire, et `stillMs` ne commence à courir qu'à ce moment-là.
    assert result["halfStillAt"] == pytest.approx(250, abs=20)
    assert result["fullStillAt"] == pytest.approx(585, abs=25)
    assert result["stillMsStartsAt"] == result["fullStillAt"]
    # Inversion franche : la vitesse publiée se trompe de **signe** le temps
    # que le lissage tourne. Un consommateur qui en déduirait une direction
    # pendant ces images-là pousserait la fenêtre dans le mauvais sens.
    assert result["wrongSignUntil"] == pytest.approx(120, abs=20)
    assert result["reaches90At"] == pytest.approx(490, abs=30)
    assert result["settled"] == pytest.approx(-900, rel=0.02)
    # Le tapotement immédiat : 150 ms après l'arrêt, `stillness` est encore
    # sous `clickStillnessMin` (0,5), donc le contact se conclurait `drag`.
    assert result["stillnessAt150"] < 0.5


# ------------------------------------------------------------------- qualité


def test_quality_notes_what_it_promises_to_note(tmp_path):
    """`quality` vaut 0 pour une main devinée et 1 pour une main franche. Elle
    est le **minimum** de ses témoins : une moyenne laisserait trois bons
    chiffres cacher celui qui dit que la main sort du cadre."""

    result = run_node(tmp_path, HAND + """
      const q=(lm,continuity)=>Number(B.handQuality(lm,1,continuity===undefined?1:continuity).toFixed(3));
      const edged=hand(.40,.5);edged[4]={x:.995,y:edged[4].y,z:0};   // pouce presque au bord
      const outside=hand(.40,.5);outside[4]={x:1,y:outside[4].y,z:0};  // pouce sur le bord
      const holed=hand(.40,.5);for(let i=10;i<21;i+=1)holed[i]={x:NaN,y:NaN,z:0};
      out({
        clean:q(hand(.40,.5)),
        tiny:q(hand(.40,.5,{palm:.02})),
        edge:q(edged),outside:q(outside),
        holed:q(holed),
        fresh:q(hand(.40,.5),1/3),
        unusable:[B.handQuality([],1,1),B.handQuality(null,1,1)],
        floor:[B.DEFAULTS.qualityFloor,C.HAND_QUALITY_FLOOR],
        usable:[1,.5,.25,.24,0,NaN,null].map(v=>B.usableQuality(v)),
        contract:[1,.5,.25,.24,0,NaN,null].map(v=>C.isUsableQuality(v)),
      });
    """)
    assert result["clean"] == 1
    # Paume minuscule : les rapports mesurés en paumes n'ont plus de sens.
    assert result["tiny"] == 0
    # Un seul point qui approche le bord suffit à faire tomber la note sous le
    # plancher : c'est le minimum des témoins, pas leur moyenne — les trois
    # autres valent 1 ici.
    assert result["edge"] == 0.125 and result["edge"] < result["floor"][0]
    assert result["outside"] == 0
    assert result["holed"] < 0.25
    # Une main qui vient d'apparaître est devinée, mais elle compte : un
    # plancher qui l'écarterait ferait dormir une session en plein usage.
    assert result["fresh"] == pytest.approx(1 / 3, abs=0.001)
    assert result["unusable"] == [0, 0]
    # Une seule définition du plancher, des deux côtés de la frontière.
    assert result["floor"] == [0.25, 0.25]
    assert result["usable"] == [True, True, True, False, False, False, False]
    assert result["contract"] == result["usable"]


# ---------------------------------------------------- passage vers le contrat


def test_the_stable_identity_reaches_the_neutral_hand_frame_and_the_motion_sample(tmp_path):
    """Le crochet que la Slice 01 avait laissé : `handFrameFromMediapipe(result,
    {trackIds})` impose l'identité persistante au `HandFrame` neutre — `0`
    compris, ce que la reprise de la Slice 01 a corrigé exprès pour cette
    Slice. Et `motionFromCoreToken` donne aux Slices 04-06 une forme nommée
    plutôt que dix champs libres."""

    result = run_node(tmp_path, HAND + """
      const t=B.createHandTracker({margin:0,mirror:false});
      const result=scene([hand(.40,.5),hand(.70,.5)],['Left','Right']);
      const first=t.update(result,frame(0));
      const second=t.update(result,frame(16));
      const neutral=C.adapters.handFrameFromMediapipe(result,{trackIds:second.trackIds,t:16,width:640,height:480});
      const motion=second.tokens.map(C.adapters.motionFromCoreToken);
      out({
        trackIds:second.trackIds,
        frameIds:neutral.hands.map(h=>h.handTrackId),
        // `0` traverse l'adaptateur au lieu d'être remplacé par la latéralité.
        zeroSurvives:neutral.hands[0].handTrackId,
        tracker:neutral.source.tracker,
        motion:motion.map(m=>[m.kind,m.handTrackId,typeof m.rawX,typeof m.x,
          typeof m.vxPxPerSec,typeof m.stillness,typeof m.quality]),
        frozen:Object.isFrozen(motion[0]),
        // Les deux positions restent distinctes : c'est ce qui rend le filtre
        // réglable et la calibration mesurable.
        carriesBoth:motion.map(m=>[m.rawX,m.x]),
        refusals:[
          refused(()=>C.createMotionSample({rawX:1,rawY:1,x:1,y:1})),
          refused(()=>C.createMotionSample({handTrackId:0,rawX:1,rawY:1,x:1})),
          refused(()=>C.createMotionSample(null)),
        ],
        firstIds:first.tokens.map(k=>k.id),
      });
    """)
    assert result["trackIds"] == [0, 1] and result["firstIds"] == [0, 1]
    assert result["frameIds"] == ["0", "1"]
    assert result["zeroSurvives"] == "0"
    assert result["tracker"] == "mediapipe_hand_landmarker"
    assert result["motion"] == [
        ["motion", "0", "number", "number", "number", "number", "number"],
        ["motion", "1", "number", "number", "number", "number", "number"],
    ]
    assert result["frozen"] is True
    assert result["carriesBoth"][0][0] == pytest.approx(result["carriesBoth"][0][1], abs=5)
    # Un refus codé plutôt qu'un défaut plausible : sans identité, sans
    # coordonnées, ou sans objet du tout.
    assert result["refusals"] == [
        "barehands_hand_track_id_missing",
        "barehands_motion_position_missing",
        "barehands_motion_invalid",
    ]


# ------------------------------------------------------------------- refus


def test_the_tuning_refuses_what_would_silently_do_nothing(tmp_path):
    """Règle du contrat, appliquée au moteur : un réglage faux se refuse, il ne
    se remplace pas. `smoothing` en est le cas le plus traître — il a existé,
    il ne fait plus rien, et l'accepter en silence rendrait un réglage sans
    effet indiscernable d'un réglage appliqué."""

    result = run_node(tmp_path, HAND + """
      out({
        retired:refused(()=>B.createHandTracker({smoothing:.2})),
        retiredFilter:refused(()=>B.createPointerFilter({smoothing:1})),
        inverted:refused(()=>B.createStillness({stillSpeedPx:500,moveSpeedPx:100})),
        // Un point inutilisable arrive ici après `usableLandmarks` : c'est un
        // défaut de code. Le taire gèlerait le jeton sur sa dernière position,
        // un curseur immobile qu'on lit comme un plantage.
        blindPoint:refused(()=>B.createPointerFilter().update({x:NaN,y:1},0)),
        blindClock:refused(()=>B.createPointerFilter().update({x:1,y:1},NaN)),
        blindManager:refused(()=>B.createHandTrackManager({}).update({hands:[],now:'bientôt'})),
        // Au-delà de la recherche exhaustive : l'image se refuse et le dit,
        // au lieu de faire ramer la boucle sans raison visible.
        tooMany:refused(()=>B.createHandTrackManager({}).update(
          {hands:Array.from({length:5},(_v,i)=>({x:.1*i,y:.5,palm:.2})),now:0,aspect:1})),
        // Un réglage hors plage retombe sur le défaut documenté plutôt que de
        // figer le filtre sur son premier point.
        zeroCutoff:B.createPointerFilter({minCutoffHz:0})?'construit':'',
      });
    """)
    assert result["retired"] == "RangeError"
    assert result["retiredFilter"] == "RangeError"
    assert result["inverted"] == "RangeError"
    assert result["blindPoint"] == "tracking_failed"
    assert result["blindClock"] == "tracking_failed"
    assert result["blindManager"] == "tracking_failed"
    assert result["tooMany"] == "tracking_failed"
    assert result["zeroCutoff"] == "construit"


# --------------------------------------------------------------- surimpression


#: Le bloc navigateur de `control_center_barehands.js` s'exécute au `require`
#: dès qu'un `window` existe. Ces doubles sont le minimum qu'il touche à
#: l'installation ; `setTimeout` ne déclenche rien, sa suite appartient à la
#: page (réglages, `/api/barehands`).
BROWSER = """
const node=()=>{
  const classes=new Set();
  return {children:[],className:'',id:'',textContent:'',offsetWidth:1,
    style:{setProperty(k,v){this[k]=v}},
    classList:{add:c=>classes.add(c),remove:c=>classes.delete(c),
      toggle:(c,on)=>{if(on)classes.add(c);else classes.delete(c)},
      contains:c=>classes.has(c)},
    classes,
    dataset:{},attrs:{},matches:()=>false,
    getBoundingClientRect:()=>({left:0,top:0,width:0,height:0}),
    setAttribute(k,v){this.attrs[k]=String(v)},parent:null,dispatchEvent(){return true},
    appendChild(c){c.parent=this;this.children.push(c)},
    remove(){if(!this.parent)return;const at=this.parent.children.indexOf(this);
      if(at>=0)this.parent.children.splice(at,1);this.parent=null}};
};
global.window={addEventListener(){},innerWidth:1000,innerHeight:800};
global.document={createElement:node,getElementById:()=>null,
  head:node(),body:node(),
  /* Le bloc navigateur vise avec `elementFromPoint` ; `hit` est ce que le
     jeton trouve sous lui, `null` par défaut (rien à cliquer). */
  elementFromPoint:()=>global.hit||null,
  /* Slice 05 : la collecte des candidates balaie la page. Aucune ici — ces
     tests-là parlent de la surimpression, pas de la cible. */
  querySelectorAll:()=>[]};
global.hit=null;
global.navigator={mediaDevices:null};
global.performance={now:()=>0};
global.requestAnimationFrame=()=>0;global.cancelAnimationFrame=()=>{};
global.setTimeout=()=>0;
// Le chemin de compatibilité DOM du clic construit ses événements souris.
global.MouseEvent=class{constructor(type,init){Object.assign(this,init||{});this.type=type}};
global.JarvisBarehandsContracts=C;
// Slice 05 : le pointeur lit le module de cible, inséré juste avant lui dans la
// page. Dans le navigateur les deux vivent sur `window` ; ici le module lit son
// `root`, donc les contrats doivent y être aussi.
global.window.JarvisBarehandsContracts=C;
global.JarvisBarehandsTarget=require(TARGET_PATH);
/* Parcours de calibration (Slice 08) : la page l'insere entre les contrats
   et le pointeur, qui le lit pour poser `calibrate()` sur sa surface gelee. */
global.JarvisBarehandsCalibration=require(CALIBRATION_PATH);
global.JarvisBarehandsTutorial=require(TUTORIAL_PATH);
// Slice 06 : la géométrie de la scène est insérée bien avant le pointeur dans
// la page (les décisions 18 et 19 y vivent, en unités de scène). Le bloc
// navigateur la lit directement, comme les contrats et l'aperçu de cible.
global.JarvisSceneInteract=require(SCENE_INTERACT_PATH);
// Le harnais a déjà chargé le module sans `window` : le bloc navigateur ne
// s'est donc pas installé. On vide le cache pour le rejouer avec un `window`.
delete require.cache[require.resolve(SCRIPT_PATH)];
require(SCRIPT_PATH);
const overlay=window.JarvisBarehands.adapters.createOverlay();
overlay.mount();
const badge=()=>document.body.children[0].children[1].textContent;
// L'anneau de veille, la pastille et la ligne des refus (Slice 05) précèdent
// les jetons dans la surimpression.
const painted=()=>document.body.children[0].children.slice(3);
"""


def test_a_hand_the_tracker_does_not_trust_says_so_on_screen(tmp_path):
    """RÈGLE ZÉRO. La qualité change un comportement que rien ne montrait : une
    main sous le plancher n'empêche plus la veille d'arriver. Si l'écran n'en
    dit rien, l'utilisateur voit son jeton, se croit suivi, et la session
    s'endort sous ses yeux sans explication.

    Le jeton reste donc affiché — le masquer dirait « je ne te vois pas », ce
    qui est faux — mais pâle et pointillé, et la pastille compte les mains
    crues à part (« 1/2 ») au lieu d'annoncer un chiffre exact et une
    information fausse."""

    result = run_node(tmp_path, f"const SCRIPT_PATH={json.dumps(str(SCRIPT))};const TARGET_PATH={json.dumps(str(TARGET))};"
    f"const CALIBRATION_PATH={json.dumps(str(CALIBRATION))};"
    f"const TUTORIAL_PATH={json.dumps(str(TUTORIAL))};"
        f"const SCENE_INTERACT_PATH={json.dumps(str(SCENE_INTERACT))};" + BROWSER + """
      const token=(id,quality)=>({id,x:10*id,y:20,progress:0,state:'open',
        click:false,hover:false,quality});
      overlay.render([token(0,1),token(1,.05)]);
      const two=painted().map(el=>el.classList.contains('faint'));
      const mixed=badge();
      overlay.render([token(0,1)]);
      const alone=badge();
      overlay.render([token(0,1),token(1,.9)]);
      const both=badge();
      // Jeton posé à la main depuis la console : aucune mesure, donc aucune
      // raison de le dessiner pâle.
      overlay.render([{id:9,x:1,y:1,progress:0,state:'open',click:false,hover:false}]);
      const unmeasured=painted().some(el=>el.classList.contains('faint'));
      out({two,mixed,alone,both,unmeasured,
        styled:[typeof window.JarvisBarehands.diagnostics,
                window.JarvisBarehands.diagnostics().length]});
    """)
    assert result["two"] == [False, True], "la main sous le plancher doit se voir"
    assert result["mixed"] == "MAINS · 1/2"
    assert result["alone"] == "MAINS · 1"
    assert result["both"] == "MAINS · 2"
    assert result["unmeasured"] is False
    # Les traits sont lisibles sans caméra ni console de développement, et
    # vides hors interaction.
    assert result["styled"] == ["function", 0]


def test_a_hand_without_a_usable_identity_is_skipped_not_fatal(tmp_path):
    """N-B. `createSlotAllocator().slot()` était total (`String(id)`) ; la
    reprise de la Slice 01 lui a donné `trackId()`, qui **refuse** une identité
    vide — à raison, une fente de pointeur appartient à une main identifiée.
    Mais `identityOf` l'appelle par jeton et par image, dans le `try` de la
    boucle, où le refus se convertit en `tracking_failed` : session terminée,
    caméra rendue, toast de 9 s, pour un jeton sans nom.

    C'est exactement la règle que la reprise de la Slice 02 a posée côté points
    (`usableLandmarks`) et laissée ouverte côté identité : **une image
    malformée se saute, elle n'arrête rien**. La main reste suivie et dessinée,
    simplement sans pointeur — et le clic perdu se dit à la console plutôt que
    de faire passer une main pour inerte."""

    result = run_node(tmp_path, f"const SCRIPT_PATH={json.dumps(str(SCRIPT))};const TARGET_PATH={json.dumps(str(TARGET))};"
    f"const CALIBRATION_PATH={json.dumps(str(CALIBRATION))};"
    f"const TUTORIAL_PATH={json.dumps(str(TUTORIAL))};"
        f"const SCENE_INTERACT_PATH={json.dumps(str(SCENE_INTERACT))};" + BROWSER + """
      // `targetAt` écarte ce qui appartient à la surimpression : la cible
      // répond donc `null` pour ce sélecteur-là, et elle-même pour les autres.
      const target=node();target.closest=sel=>sel===C.DOM.rootSelector?null:target;
      global.hit=target;
      const interaction=window.JarvisBarehands.adapters.createInteraction();
      const token=id=>({id,x:10,y:20,progress:0,state:'open',click:false,hover:false});
      // Une image entière : une main identifiée, trois qui ne le sont pas.
      const blanks=[token(0),token('  '),token(null),token(undefined)];
      let threw=null;
      try{interaction.hover(blanks)}catch(e){threw=e.code||e.name}
      const hovered=blanks.map(t=>t.hover);
      // Le clic d'une main sans identité se perd, il ne lève pas.
      let clickThrew=null,clicked=null;
      try{clicked=[interaction.click({id:0,x:10,y:20}),interaction.click({id:'  ',x:10,y:20})]}
      catch(e){clickThrew=e.code||e.name}
      // L'image suivante, normale, retrouve son pointeur : rien n'est resté cassé.
      let after=null;
      try{interaction.hover([token(0)]);after=true}catch(e){after=e.code||e.name}
      // Le contrat, lui, continue de refuser — c'est le consommateur qui garde.
      const contract=(()=>{try{C.createSlotAllocator(2).slot('  ');return null}
        catch(e){return e.code}})();
      out({threw,hovered,clickThrew,clicked,after,contract});
    """)
    assert result["threw"] is None, "une identité vide ne doit pas tuer la session"
    # La main identifiée survole ; les autres sont suivies sans pointer, comme
    # une main surnuméraire — mieux qu'un identifiant volé à une autre main.
    assert result["hovered"] == [True, False, False, False]
    assert result["clickThrew"] is None and result["clicked"] == [True, False]
    assert result["after"] is True
    # Le refus n'a pas été affaibli là où il est juste : le contrat le tient.
    assert result["contract"] == "barehands_hand_track_id_missing"


def test_the_page_publishes_gestures_and_contacts_through_the_contract(tmp_path):
    """Slice 04. Le bloc pur porte sa forme de travail — il est chargé seul par
    node et ne peut pas lire le contrat — donc c'est la **page** qui publie, à
    travers `createGestureEvent` et `createPinchEvent`. Ce test garde le
    câblage : la fente de pointeur vient de l'allocateur de l'interaction (le
    moteur ne connaît pas les fentes, et une fente inventée volerait un
    `pointerId` à l'autre main), et les deux entrées existent sur l'API
    publique plutôt que dans une console.

    Hors interaction, tout est vide : une posture affichée pour une main que
    plus rien ne regarde serait pire qu'un écran vide."""

    result = run_node(tmp_path, f"const SCRIPT_PATH={json.dumps(str(SCRIPT))};const TARGET_PATH={json.dumps(str(TARGET))};"
    f"const CALIBRATION_PATH={json.dumps(str(CALIBRATION))};"
    f"const TUTORIAL_PATH={json.dumps(str(TUTORIAL))};"
        f"const SCENE_INTERACT_PATH={json.dumps(str(SCENE_INTERACT))};" + BROWSER + """
      const api=window.JarvisBarehands;
      const idle={gestures:api.gestures(),pinch:api.pinch()};
      const interaction=api.adapters.createInteraction();
      out({
        exposed:[typeof api.gestures,typeof api.pinch,typeof api.diagnostics],
        idle:[idle.gestures.events.length,idle.gestures.suppressed.length,
              idle.gestures.postures.length,idle.pinch.events.length,
              idle.pinch.contacts.length],
        /* La fente vient de l'allocateur, et une main inconnue n'en invente
           pas : `null` est ce que `createPinchEvent` accepte. */
        slots:[interaction.slotOf(0),interaction.slotOf(1),interaction.slotOf('  '),
               interaction.slotOf(null)],
        pointerIds:[C.pointerIdForSlot(interaction.slotOf(0)),
                    C.pointerIdForSlot(interaction.slotOf(1))],
        /* Ce que la page publierait d'un contact : la forme du contrat, avec
           l'identité de pointeur que la fente porte. */
        published:C.createPinchEvent({channel:'secondary',phase:'down',handTrackId:1,
          slot:interaction.slotOf(1),x:10,y:20,intent:'undecided'}),
      });
    """)
    assert result["exposed"] == ["function", "function", "function"]
    assert result["idle"] == [0, 0, 0, 0, 0]
    assert result["slots"] == [0, 1, None, None]
    assert result["pointerIds"] == [9001, 9002]
    assert result["published"]["pointerId"] == 9002
    assert result["published"]["channel"] == "secondary"
    assert result["published"]["intent"] == "undecided"
