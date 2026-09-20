"""Vocabulaire de dessin des mains schématiques Bare Hands, exécuté par node.

Ce fichier est **le contrat que la Slice 06 hérite**, et pas une suggestion.
La calibration doit pouvoir dessiner ses mains virtuelles sans redessiner un
second jeu de mains ; ce qui rend cela possible est épinglé ici :

- les sept postures existent, sous ces noms-là et dans cet ordre ;
- `rest` reproduit **exactement** le dessin servi depuis la Slice 01, donc
  sortir le tracé du module du HUD n'a rien changé à l'écran ;
- ouvrir et fermer un pincement ne bouge **que les deux doigts qui pincent** —
  sans cet invariant, une animation ferait bouger toute la main et le regard
  perdrait ce qu'il doit suivre ;
- le primaire et le secondaire sont **visiblement distincts** : ce n'est pas le
  point de contact qui change, c'est le doigt qui y va et la silhouette ;
- l'ouverture du C se situe **entre** celle d'un pincement ouvert et celle
  d'une main ouverte, ce qui est exactement ce que `cPoseScore` mesure ;
- une posture inconnue se **refuse** au lieu de retomber sur la main au repos.

Le module est pur : ni DOM, ni réseau, ni horloge. `handSvg` demande un
document, et ce fichier lui en fabrique un minuscule — c'est la seule chose que
node n'a pas.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
HAND_ART = RUNTIME / "control_center_barehands_hand_art.js"
HUD = RUNTIME / "control_center_barehands_hud.js"
CONTRACTS = RUNTIME / "control_center_barehands_contracts.js"

#: Un document minuscule, juste assez pour `handSvg` : créer un nœud dans un
#: espace de noms, lui poser des attributs, l'empiler. Il est écrit ici plutôt
#: qu'emprunté au double du HUD parce que ce module ne dépend de rien, et son
#: fichier de test ne doit pas non plus.
DOM = r"""
const mkNode=(ns,tag)=>({
  namespaceURI:ns,tag,attrs:{},children:[],textContent:'',
  setAttribute(k,v){this.attrs[k]=String(v)},
  getAttribute(k){return this.attrs[k]===undefined?null:this.attrs[k]},
  appendChild(child){this.children.push(child);return child},
});
const document={createElementNS:(ns,tag)=>mkNode(ns,tag)};
/* Les formes d'un arbre SVG, à plat et dans l'ordre du document : c'est la
   seule façon de comparer un nœud et une chaîne sans lire des pixels. */
const flatten=node=>{
  const out=[];
  const walk=n=>{
    for(const child of n.children){
      out.push({tag:child.tag,attrs:child.attrs,text:child.textContent});
      walk(child);
    }
  };
  walk(node);
  return out;
};
const ART=require(HAND_ART_PATH);
const tipOf=(pose,digit)=>{const p=ART.pose(pose).digits[digit];return p[p.length-1]};
const gap=(pose,a,b)=>{
  const one=tipOf(pose,a),two=tipOf(pose,b);
  return Math.round(Math.hypot(one[0]-two[0],one[1]-two[1])*100)/100;
};
"""


def run_node(tmp_path: Path, source: str, name: str = "handart") -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"barehands-{name}.cjs"
    script.write_text(
        f"const HAND_ART_PATH={json.dumps(str(HAND_ART))};\n"
        f"const HUD_PATH={json.dumps(str(HUD))};\n"
        f"const CONTRACTS_PATH={json.dumps(str(CONTRACTS))};\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "(async()=>{" + DOM + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_seven_poses_exist_under_these_names_and_in_this_order(tmp_path):
    """**Le catalogue que la Slice 06 appelle.** Les noms sont le contrat : la
    calibration demandera `wake_c` et `pinch_secondary_closed`, pas « la
    troisième » ni « celle avec le pouce en haut ».

    Chaque posture déclare ses cinq doigts et ses cinq articulations. Une
    posture à quatre doigts serait une main mutilée qu'aucun test de
    comportement n'attraperait."""

    result = run_node(tmp_path, r"""
      const poses=ART.POSE_ORDER;
      const shape=poses.map(id=>{
        const p=ART.pose(id);
        const s=ART.handShapes({pose:id});
        return {id,
          digits:Object.keys(p.digits).sort(),
          joints:Object.keys(p.joints).sort(),
          /* Deux à quatre points par doigt : un os droit, ou un doigt qui plie
             une ou deux fois. Zéro ou un point ne serait pas un trait. */
          spans:ART.DIGIT_ORDER.map(d=>p.digits[d].length),
          labelled:!!p.label&&!!p.summary,
          paths:s.paths.length,dots:s.dots.length,rings:s.rings.length};
      });
      out({poses,shape,digits:ART.DIGIT_ORDER,
        viewBox:ART.VIEWBOX,stroke:ART.STROKE_WIDTH});
    """, name="catalogue")

    assert result["poses"] == [
        "rest", "wake_c",
        "pinch_primary_open", "pinch_primary_closed",
        "pinch_secondary_open", "pinch_secondary_closed",
        "pinch_target",
    ]
    # L'ordre de tracé est celui de la Slice 01, et il est porteur : c'est lui
    # qui fait que `rest` produit le même document SVG que l'icône déjà servie.
    assert result["digits"] == ["index", "middle", "ring", "pinky", "thumb"]
    assert result["viewBox"] == "0 0 24 24" and result["stroke"] == 1.5
    every = ["index", "middle", "pinky", "ring", "thumb"]
    for pose in result["shape"]:
        assert pose["digits"] == every, pose["id"]
        assert pose["joints"] == every, pose["id"]
        assert all(2 <= n <= 4 for n in pose["spans"]), pose["id"]
        assert pose["labelled"], pose["id"]
        # Paume + jointures + cinq doigts = sept tracés au minimum ; un point
        # plein par doigt, toujours cinq.
        assert pose["paths"] >= 7 and pose["dots"] == 5, pose["id"]


def test_the_resting_hand_is_byte_for_byte_the_drawing_already_served(tmp_path):
    """**Sortir le tracé du module du HUD n'a rien changé à l'écran.**

    C'est la condition pour que cette Slice ait le droit de généraliser plutôt
    que d'ajouter un second illustrateur : `rest` doit être *le* dessin de la
    Slice 01 — même châssis de paume, mêmes cinq os, mêmes cinq points aux
    mêmes endroits, dans le même ordre — et le bouton doit continuer à le
    produire par `handIcon`, dont la signature n'a pas bougé.

    Les valeurs ci-dessous sont recopiées du commit de la Slice 01, pas lues du
    module : un test qui lirait la même source que le code ne prouverait rien.
    """

    result = run_node(tmp_path, r"""
      const rest=ART.handShapes({pose:ART.POSE.REST});
      /* Et par la porte du HUD, qui est celle que la page appelle vraiment.
         Il lit les contrats **et** ce module au chargement, donc les deux sont
         posés d'abord — c'est l'ordre que `control_center.py` sert. */
      global.window=global;
      require(CONTRACTS_PATH);
      const H=require(HUD_PATH);
      const icon=H.handIcon(document,34);
      out({paths:rest.paths,dots:rest.dots.map(d=>[d.cx,d.cy,d.r]),
        rings:rest.rings.length,
        icon:{tag:icon.tag,attrs:icon.attrs,
          shapes:flatten(icon).map(n=>n.tag+':'+(n.attrs.d||`${n.attrs.cx},${n.attrs.cy},${n.attrs.r}`))}});
    """, name="rest")

    # Le châssis de paume, mot pour mot celui de la Slice 01.
    assert result["paths"][0] == (
        "M6.5 12.6v4.2a3.8 3.8 0 0 0 3.8 3.8h3.9a3.9 3.9 0 0 0 3.9-3.9v-4.1"
    )
    assert result["paths"][1] == "M6.5 12.6h11.6", "la ligne des jointures"
    # Les cinq os. La Slice 01 les écrivait en commandes courtes (`V`, un `M`
    # implicite) ; la polyligne générique dit la même géométrie en `L`. C'est
    # le même trait à l'écran, et c'est la seule chose qui compte.
    assert result["paths"][2:] == [
        "M9 12.4L9 6.7",        # index
        "M12 12.1L12 5.2",      # majeur
        "M15 12.4L15 6.7",      # annulaire
        "M17.7 12.6L17.7 8.7",  # auriculaire
        "M7 13.5L4.7 10.8",     # pouce
    ]
    assert result["dots"] == [
        [9, 9.4, 0.95], [12, 8.5, 0.95], [15, 9.4, 0.95],
        [17.7, 10.5, 0.95], [5.85, 11.95, 0.95],
    ]
    assert result["rings"] == 0, "la main au repos ne touche rien, donc n'annonce rien"
    # Le bouton du haut-gauche produit toujours exactement ce dessin, à sa
    # taille, sous sa classe, et décoratif — il vit à côté de son étiquette.
    icon = result["icon"]
    assert icon["tag"] == "svg"
    assert icon["attrs"]["class"] == "bh-hud-icon"
    assert icon["attrs"]["width"] == "34" and icon["attrs"]["height"] == "34"
    assert icon["attrs"]["aria-hidden"] == "true" and icon["attrs"]["focusable"] == "false"
    assert icon["attrs"]["stroke"] == "currentColor" and icon["attrs"]["fill"] == "none"
    assert icon["attrs"]["data-bh-pose"] == "rest"
    assert len(icon["shapes"]) == 12, "sept tracés et cinq points, comme avant"


def test_opening_and_closing_a_pinch_moves_only_the_two_fingers_that_pinch(tmp_path):
    """**L'invariant d'animation, et c'est lui que la Slice 06 achète.**

    Elle doit montrer un pincement qui se ferme puis se rouvre. Si les deux
    postures différaient ailleurs que sur les deux doigts concernés, la main
    entière sauterait d'une image à l'autre et l'utilisateur ne saurait pas
    quoi regarder. Deux dessins faits à la main auraient dérivé sur ce point
    précis sans que rien ne tombe ; une table le rend vérifiable.

    Le contact est en plus **au même endroit** pour les deux canaux : ce qui
    distingue un pincement de l'autre est le chemin, donc le doigt, donc le
    sens — pas un point d'arrivée différent."""

    result = run_node(tmp_path, r"""
      const pairs=[
        {name:'primary',open:'pinch_primary_open',shut:'pinch_primary_closed',
         moving:['thumb','index']},
        {name:'secondary',open:'pinch_secondary_open',shut:'pinch_secondary_closed',
         moving:['thumb','middle']},
      ];
      const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
      out({pairs:pairs.map(pair=>{
        const o=ART.pose(pair.open),s=ART.pose(pair.shut);
        const moved=ART.DIGIT_ORDER.filter(d=>!same(o.digits[d],s.digits[d]));
        return {name:pair.name,moved:moved.slice().sort(),
          expected:pair.moving.slice().sort(),
          /* L'articulation suit son doigt : un point qui resterait où il était
             flotterait à côté d'un os qui a bougé. */
          jointsMoved:ART.DIGIT_ORDER.filter(d=>!same(o.joints[d],s.joints[d])).slice().sort(),
          openGap:(()=>{const t=pair.moving;return gapOf(pair.open,t[0],t[1])})(),
          shutGap:(()=>{const t=pair.moving;return gapOf(pair.shut,t[0],t[1])})(),
          contact:tipOf(pair.shut,'thumb'),
          /* Fermé, une marque de contact — et une seule. */
          rings:ART.handShapes({pose:pair.shut}).rings.length,
          openRings:ART.handShapes({pose:pair.open}).rings.length};
      })});
      function gapOf(pose,a,b){return gap(pose,a,b)}
    """, name="pairs")

    for pair in result["pairs"]:
        assert pair["moved"] == pair["expected"], pair["name"]
        assert pair["jointsMoved"] == pair["expected"], pair["name"]
        # Ouvert, les deux bouts sont franchement séparés ; fermé, ils se
        # touchent. L'écart d'un ordre de grandeur est ce qui rend « pris » et
        # « pas encore pris » lisibles sans légende.
        assert pair["openGap"] > 2.5, pair["name"]
        assert pair["shutGap"] < 0.5, pair["name"]
        assert pair["openGap"] > pair["shutGap"] * 5, pair["name"]
        assert pair["rings"] == 1 and pair["openRings"] == 0, pair["name"]
    # Même point de contact pour les deux canaux.
    assert result["pairs"][0]["contact"] == result["pairs"][1]["contact"]


def test_the_two_pinches_are_siblings_and_still_unmistakably_different(tmp_path):
    """**« Même grammaire, visiblement distinct »**, vérifié plutôt que promis.

    Frères : même paume, même ligne de jointures, même pouce, même contact.
    Distincts : le primaire garde le majeur **dressé** au-dessus du geste, le
    secondaire replie l'index et fait descendre le majeur. Les deux silhouettes
    n'ont donc aucun doigt long en commun, ce qui est la différence qu'un œil
    attrape avant de lire la légende."""

    result = run_node(tmp_path, r"""
      const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
      const P=ART.pose('pinch_primary_closed'),S=ART.pose('pinch_secondary_closed');
      const rest=ART.pose('rest');
      out({
        sharedThumb:same(P.digits.thumb,S.digits.thumb),
        /* Le majeur du primaire est celui de la main au repos : tendu, hors du
           geste. Celui du secondaire pince. */
        primaryMiddleStraight:same(P.digits.middle,rest.digits.middle),
        secondaryMiddleStraight:same(S.digits.middle,rest.digits.middle),
        /* L'index du secondaire est replié, celui du primaire pince. */
        differing:ART.DIGIT_ORDER.filter(d=>!same(P.digits[d],S.digits[d])).sort(),
        /* Le pouce-index et le pouce-majeur du contrat, traduits en dessin :
           c'est le doigt nommé par `PINCH_FINGERS` qui descend. */
        primaryIndexMoves:!same(P.digits.index,rest.digits.index),
        secondaryIndexMoves:!same(S.digits.index,rest.digits.index),
      });
    """, name="siblings")

    assert result["sharedThumb"] is True, "un seul pouce fermé pour les deux canaux"
    assert result["primaryMiddleStraight"] is True
    assert result["secondaryMiddleStraight"] is False
    assert result["differing"] == ["index", "middle"]
    assert result["primaryIndexMoves"] is True
    assert result["secondaryIndexMoves"] is True


def test_the_c_is_made_of_thumb_and_index_and_opens_wider_than_any_pinch(tmp_path):
    """**Décision 27**, et elle est mesurable.

    Le C est dessiné par le pouce et l'index, et par eux seuls : les trois
    autres doigts sont repliés, sans quoi un C tracé au milieu d'une main
    ouverte se lirait « main ouverte ».

    Son ouverture est **entre** celle d'un pincement ouvert et celle d'une main
    ouverte, et ce n'est pas une coquetterie : c'est exactement ce que
    `cPoseScore` mesure — en dessous de `wakeGapMin` c'est un pincement en
    cours, au-dessus de `wakeGapMax` c'est une main ouverte. Le dessin ment
    s'il sort de cette bande."""

    result = run_node(tmp_path, r"""
      const rest=ART.pose('rest'),c=ART.pose('wake_c');
      const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
      out({
        /* Les deux doigts du C ont bougé ; les trois autres sont repliés,
           c'est-à-dire ni au repos ni en train de pincer. */
        drawnBy:ART.DIGIT_ORDER.filter(d=>!same(c.digits[d],rest.digits[d])).sort(),
        folded:['middle','ring','pinky'].filter(d=>!same(c.digits[d],rest.digits[d])),
        cGap:gap('wake_c','index','thumb'),
        openPinch:gap('pinch_primary_open','index','thumb'),
        openSecondary:gap('pinch_secondary_open','middle','thumb'),
        shutPinch:gap('pinch_primary_closed','index','thumb'),
        openHand:gap('rest','index','thumb'),
        /* Un C n'annonce rien : ni contact, ni cible. */
        rings:ART.handShapes({pose:'wake_c'}).rings.length,
      });
    """, name="wake")

    assert result["drawnBy"] == ["index", "middle", "pinky", "ring", "thumb"]
    assert result["folded"] == ["middle", "ring", "pinky"]
    assert result["rings"] == 0
    # La bande, dans l'ordre : doigts joints « pincement ouvert « C « main
    # ouverte. C'est la mesure de `cPoseScore` rendue en dessin.
    assert result["shutPinch"] < result["openPinch"] < result["cGap"] < result["openHand"]
    assert result["openSecondary"] < result["cGap"]


def test_the_aimed_pinch_is_the_pinch_plus_a_target_and_nothing_else(tmp_path):
    """**Décision 28** : la calibration de cible montre un **pincement**, pas un
    doigt qui pointe.

    La composition est littérale et c'est ce qui la rend sûre : cette posture
    est le primaire fermé, doigt pour doigt, plus un anneau. Le contact reste
    un trait plein — un fait constaté — et la mire est en pointillés — une
    région visée. Le même vocabulaire discontinu que l'icône d'outil sans
    moteur de la palette, et pas un troisième langage de trait."""

    result = run_node(tmp_path, r"""
      const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
      const P=ART.pose('pinch_primary_closed'),T=ART.pose('pinch_target');
      const rings=ART.handShapes({pose:'pinch_target'}).rings;
      out({
        identical:ART.DIGIT_ORDER.every(d=>same(P.digits[d],T.digits[d])),
        sameJoints:ART.DIGIT_ORDER.every(d=>same(P.joints[d],T.joints[d])),
        rings:rings.map(r=>[r.cx,r.cy,r.r,r.dashed]),
        /* Aucun doigt tendu vers la cible : le majeur est celui du repos, il
           ne désigne rien. */
        pointing:!same(T.digits.index,P.digits.index),
      });
    """, name="target")

    assert result["identical"] is True and result["sameJoints"] is True
    assert result["pointing"] is False
    contact, target = result["rings"]
    assert contact[3] is False, "le contact est un trait plein : un fait"
    assert target[3] is True, "la mire est en pointillés : une région"
    assert (contact[0], contact[1]) == (target[0], target[1]), "concentriques"
    assert target[2] > contact[2], "la mire entoure le contact"
    # La mire reste au-dessus de la ligne des jointures (12.6) : un premier jet
    # la faisait descendre dessus, et deux traits qui se touchent sans le
    # vouloir se lisent comme un seul dessin raté.
    assert target[1] + target[2] < 12.6


def test_an_unknown_pose_is_refused_by_name_instead_of_drawing_a_plausible_hand(tmp_path):
    """« Un refus codé plutôt qu'un défaut plausible » (contrat, § en tête).

    Une posture inconnue ne retombe **pas** sur la main au repos. Un écran qui
    montre une main ouverte là où on attendait un pincement enseigne le mauvais
    geste, et rien ne le signale — c'est exactement la panne qui disparaît.

    Trois refus, trois noms : la posture, le document, la marque."""

    result = run_node(tmp_path, r"""
      const caught=fn=>{try{fn();return null}catch(e){return e.code||String(e.message)}};
      out({
        pose:caught(()=>ART.pose('poing')),
        shapes:caught(()=>ART.handShapes({pose:'poing'})),
        markup:caught(()=>ART.handMarkup({pose:'poing'})),
        svg:caught(()=>ART.handSvg(null,{pose:'rest'})),
        notADoc:caught(()=>ART.handSvg({},{pose:'rest'})),
        /* Et l'absence, elle, reste permise : ne rien demander donne la main
           au repos, parce que personne n'a rien dit. */
        blank:ART.handShapes({}).id,
        listed:caught(()=>ART.pose('poing')),
        says:(()=>{try{ART.pose('poing')}catch(e){return e.message.indexOf('rest')>=0}})(),
      });
    """, name="refusals")

    assert result["pose"] == "barehands_hand_pose_unknown"
    assert result["shapes"] == "barehands_hand_pose_unknown"
    assert result["markup"] == "barehands_hand_pose_unknown"
    assert result["svg"] == "barehands_hand_document_missing"
    assert result["notADoc"] == "barehands_hand_document_missing"
    assert result["blank"] == "rest", "l'absence prend le défaut documenté"
    # Le refus dit ce qui existe : un code seul n'apprend pas quoi écrire.
    assert result["says"] is True


def test_the_markup_and_the_nodes_are_two_serialisers_of_one_drawing(tmp_path):
    """`handSvg` construit des nœuds, `handMarkup` rend une chaîne. Les deux
    lisent `handShapes` et **ne peuvent donc pas diverger** — c'est la raison
    pour laquelle il y a deux sorties et un seul dessin. Ce test les compare
    forme par forme ; sans lui, rien n'empêcherait l'une d'être corrigée seule.

    Le retournement vit dans un `<g>` interne et non sur la racine : posé sur
    la racine, il emporterait aussi le `<title>`, qui n'a pas de géométrie."""

    result = run_node(tmp_path, r"""
      const spec={pose:'pinch_target',size:48,title:'Pincer la cible'};
      const node=ART.handSvg(document,spec);
      const text=ART.handMarkup(spec);
      const shapes=ART.handShapes(spec);
      /* Les `d` et les cercles de la chaîne, dans l'ordre où elle les écrit. */
      const inText=(text.match(/<path d="[^"]*"|<circle [^/]*/g)||[]).map(s=>
        s.startsWith('<path')?s.slice(9,-1)
          :[/cx="([^"]*)"/,/cy="([^"]*)"/,/r="([^"]*)"/].map(re=>(s.match(re)||[])[1]).join(','));
      const inNode=flatten(node).filter(n=>n.tag==='path'||n.tag==='circle').map(n=>
        n.tag==='path'?n.attrs.d:[n.attrs.cx,n.attrs.cy,n.attrs.r].join(','));
      const mirrored=ART.handSvg(document,{pose:'rest',mirror:true,title:'Main gauche'});
      const flat=flatten(mirrored);
      out({
        agree:JSON.stringify(inText)===JSON.stringify(inNode),
        count:inNode.length,
        /* Annoncée : un `title`, donc `role=img` et surtout **pas**
           `aria-hidden` — les deux ne peuvent pas être vrais ensemble. */
        role:node.attrs.role,hidden:node.attrs['aria-hidden']===undefined,
        titled:flatten(node).filter(n=>n.tag==='title').map(n=>n.text),
        textTitled:text.indexOf('<title>Pincer la cible</title>')>0,
        size:[node.attrs.width,node.attrs.height],
        dashed:text.indexOf('stroke-dasharray')>0,
        /* Retournée : un `<g>` porte la transformation, et le `<title>` reste
           dehors, au même rang que lui. */
        mirrorNode:flat[0].tag,mirrorTransform:flat.filter(n=>n.tag==='g')[0].attrs.transform,
        titleOutside:flat[0].tag==='title',
        rootTransform:mirrored.attrs.transform===undefined,
        pose:shapes.id,label:shapes.label.length>0,
      });
    """, name="serialisers")

    assert result["agree"] is True, "deux sérialiseurs, un seul dessin"
    # Sept tracés, cinq points, et les deux anneaux du pincement visé.
    assert result["count"] == 14
    assert result["role"] == "img" and result["hidden"] is True
    assert result["titled"] == ["Pincer la cible"] and result["textTitled"] is True
    assert result["size"] == ["48", "48"]
    assert result["dashed"] is True, "la mire garde son pointillé dans les deux sorties"
    assert result["titleOutside"] is True, "le titre n'est pas retourné avec la main"
    assert result["mirrorTransform"] == "translate(24,0) scale(-1,1)"
    assert result["rootTransform"] is True, "la racine ne porte aucune transformation"
    assert result["pose"] == "pinch_target" and result["label"] is True


def test_the_drawing_module_knows_nothing_about_gestures(tmp_path):
    """**La frontière qui protège la Slice 04 d'elle-même.**

    Ce module est un alphabet de formes. Il ne lit pas les contrats, il ne
    nomme aucun `GESTURE`, et il ne dit à personne ce qu'une posture
    *déclenche*. Lier une posture à une action est le travail de qui affiche —
    la carte d'aide le fait depuis les contrats, la calibration depuis ses
    étapes.

    Si le dessin connaissait les gestes, l'aide aurait un second contrat de
    gestes, et c'est précisément ce que cette Slice existe pour empêcher. Le
    test est grossier et il l'assume : il lit le fichier. C'est justement
    parce qu'aucun test de comportement n'attrape une dépendance ajoutée un
    jour de fatigue."""

    # Les commentaires sont retirés : ce fichier **parle** des gestes en long
    # et en large, et c'est son sujet. Ce qui est interdit, c'est que le
    # **code** en connaisse un seul.
    source = HAND_ART.read_text(encoding="utf-8")
    body = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    for forbidden in ("JarvisBarehandsContracts", "GESTURE", "INTERACTION",
                      "PINCH_CHANNEL", "LIFECYCLE", "require("):
        assert forbidden not in body, forbidden
    # Et il n'a aucune dépendance de page du tout : ni document ni fenêtre pris
    # dans un global. La seule mention de `window` est la dernière ligne, celle
    # qui choisit où poser le global — et elle la nomme deux fois.
    lines = [line for line in body.splitlines() if line.strip()]
    head, closing = "\n".join(lines[:-1]), lines[-1]
    assert closing.strip() == "})(typeof window!=='undefined'?window:globalThis);"
    assert "window" not in head, "aucune fenêtre lue depuis l'intérieur"
    assert "document" not in head.replace("doc", ""), "le document est toujours passé"
