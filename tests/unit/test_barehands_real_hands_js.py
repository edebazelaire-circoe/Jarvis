"""Le réveil et l'affichage du pointeur, mesurés sur de **vraies mains**.

Les autres tests Bare Hands construisent leurs mains. Celui-ci non : il rejoue
des points produits par le **vrai** MediaPipe — le module et le modèle
vendorisés sous `third_party/barehands/vendor`, exécutés dans un Chrome sans
tête — sur **dix-sept mains photographiées**. Le harnais qui les a produits est
`runtime/handproof/` ; le relancer ne demande qu'une caméra absente et un
réseau présent.

Pourquoi ce fichier existe. Une main synthétique dit ce que son auteur a cru
qu'une main faisait : c'est un bon outil pour vérifier une rampe, et un mauvais
témoin pour décider d'une posture. La preuve en est le défaut que ce fichier
verrouille — une paume grande ouverte, photographiée, marquait **1,000** au
score de réveil, le maximum, alors qu'aucune main synthétique du dépôt ne
l'avait jamais fait. L'écart pouce-index d'une main ouverte tombe en plein
milieu de la bande du C, et rien ne regardait les autres doigts.

Les postures du jeu, par préfixe de photographie :
`open` main ouverte ou détendue · `fist` poing · `pinch` pouce et index qui se
touchent, les trois autres doigts tendus (le geste OK) · `cpinch` pouce et index
écartés, index tendu, autres doigts repliés — l'amorce de la visée ·
`narrowc` le C étroit du pouce et de l'index, autres doigts repliés.

Fusion du 28/09 (tâche adaptive-calibration-benchmark). Ce fichier est né sur
le correctif 89388a0, qui plaçait le témoin des autres doigts **dans**
`cPoseScore` et montrait le pointeur par un portillon propre (`aimScore`,
`createAimGate`). La tâche avait, en parallèle, le même concept sous sa forme
canonique (décision 46) : le repli `otherFingersFolded` **composé** par-dessus
le C (`wakePostureScore` — la bande publiée de `cPoseScore` reste la
géométrie seule) et l'intention de pointer (`pointingPostureScore`,
`createPointingIntent`). Un seul mécanisme a été gardé, celui de la tâche ; ce
fichier en interroge donc les noms, sans rien changer à ce qu'il exige : une
main ouverte ne réveille pas et ne montre rien, un poing non plus, un contact
tenu garde son pointeur, et le répit finit.
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
FIXTURE = ROOT / "tests" / "fixtures" / "barehands_real_hands.v1.json"


def hands():
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert doc["schema"] == "jarvis.barehands.realhands"
    return doc["hands"]


def by_posture(name):
    chosen = [h for h in hands() if h["posture"] == name]
    if not chosen:
        pytest.skip(f"aucune main réelle de posture {name} dans le jeu")
    return chosen


def measure(tmp_path):
    """Les scores du **vrai** module, main réelle par main réelle."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "real-hands.cjs"
    script.write_text(
        f"const B=require({json.dumps(str(SCRIPT))});\n"
        f"const doc=require({json.dumps(str(FIXTURE))});\n"
        "const out=doc.hands.map(h=>{\n"
        "  const k=h.aspect,lm=h.landmarks;\n"
        "  const d=(a,b)=>Math.hypot((a.x-b.x)*k,a.y-b.y);\n"
        "  const palm=d(lm[0],lm[9]);\n"
        # `cPose` est ce que la veille **tient** (`wakePostureScore` : le C
        # composé du repli des trois autres doigts) ; `cGeometry` le C seul,
        # dont la bande publiée ne change pas. `aim` est la posture de visée,
        # `shown` ce qu'en fait la machine d'intention quand la main reste
        # immobile, croyable et non engagée pendant une demi-seconde (plus que
        # `pointingEnterMs`) : sans intention, rien ne se dessine.
        "  const aim=B.pointingPostureScore(lm,k);\n"
        "  const m=B.createPointingIntent();let shown=false;\n"
        "  for(let t=0;t<=500;t+=16){const r=m.update({now:t,hands:[{handTrackId:1,posture:aim,\n"
        "    stillness:1,quality:1,engaged:false}]});shown=r.hands[0].pointing}\n"
        "  return {photo:h.photo,hand:h.hand,posture:h.posture,\n"
        "    cGeometry:B.cPoseScore(lm,k),cPose:B.wakePostureScore(lm,k),aim,\n"
        "    gap:d(lm[4],lm[8])/palm,indexReach:d(lm[0],lm[8])/palm,\n"
        "    middleReach:d(lm[0],lm[12])/palm,\n"
        "    otherReach:Math.max(d(lm[0],lm[12]),d(lm[0],lm[16]),d(lm[0],lm[20]))/palm,\n"
        "    shown};\n"
        "});\n"
        "process.stdout.write(JSON.stringify({rows:out,defaults:B.DEFAULTS}));",
        encoding="utf-8",
    )
    done = subprocess.run(
        [node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def rows_of(tmp_path, posture):
    data = measure(tmp_path)
    chosen = [r for r in data["rows"] if r["posture"] == posture]
    if not chosen:
        pytest.skip(f"aucune main réelle de posture {posture} dans le jeu")
    return chosen, data["defaults"]


# --------------------------------------------------------------------------
# 1. Le réveil : la posture, et ce qu'elle refuse
# --------------------------------------------------------------------------

def test_the_open_palm_that_used_to_wake_barehands_by_itself(tmp_path):
    """**Le défaut, nommé.** `open_palm_03` est une paume grande ouverte,
    doigts écartés, photographiée. Sa géométrie de C est *parfaite* — écart et
    portée d'index tous deux au cœur de la bande documentée — et c'est bien le
    problème : sans un témoin sur les autres doigts, une main simplement
    ouverte **est** un C, et réveille au bout d'une seconde.

    Ce test tient les deux moitiés ensemble, et c'est ce qui le rend utile :
    la géométrie reste dans la bande (donc élargir ou déplacer la bande ne
    répare rien, et ce n'est pas par là qu'on a corrigé), et le score final est
    tombé à zéro (donc le témoin fait bien son travail). Retirer le repli de
    `wakePostureScore` rallumerait ce test.

    Fusion du 28/09 : `cPose` est ici la posture **du réveil**
    (`wakePostureScore`), celle que le guetteur tient ; le C géométrique seul
    (`cGeometry`) vaut toujours 1 sur cette main, et c'est la prémisse.
    """
    data = measure(tmp_path)
    o = data["defaults"]
    palm = next(r for r in data["rows"] if r["photo"] == "open_palm_03.jpg")

    soft = (o["wakeGapMax"] - o["wakeGapMin"]) * o["wakeSoft"]
    assert o["wakeGapMin"] + soft * o["wakeScore"] <= palm["gap"] <= o["wakeGapMax"] - soft * o["wakeScore"], (
        "la paume ouverte doit rester dans la bande d'écart du C : c'est la "
        "prémisse du défaut, pas un détail"
    )
    assert palm["indexReach"] >= o["wakeIndexMin"] * (1 + o["wakeSoft"] * o["wakeScore"])
    assert palm["middleReach"] >= o["fingerExtendedPalms"], "majeur tendu : la main est ouverte"
    assert palm["cGeometry"] == 1, "prémisse : la géométrie du C seule accepte cette main"
    assert palm["cPose"] == 0, "une main ouverte ne réveille pas"


def test_no_real_hand_that_is_not_a_pinch_of_thumb_and_index_ever_wakes(tmp_path):
    """Aucune main ouverte, aucun poing, aucun geste OK du jeu ne tient le
    score de réveil. C'est la forme générale du test précédent : le défaut
    n'était pas propre à une photographie."""
    data = measure(tmp_path)
    o = data["defaults"]
    guilty = [
        (r["photo"], r["hand"], r["cPose"])
        for r in data["rows"]
        if r["posture"] in ("open", "fist", "pinch") and r["cPose"] >= o["wakeScore"]
    ]
    assert guilty == [], f"ces mains réelles réveilleraient Bare Hands sans qu'on le demande : {guilty}"


def test_the_middle_finger_separates_the_two_families_of_real_hands(tmp_path):
    """Le témoin choisi tient parce que la mesure le porte, pas parce qu'il
    arrange le code : sur les dix-sept mains, la portée du majeur d'une main
    ouverte et celle d'une main en visée ne se recouvrent pas, et les deux
    constantes qui nomment déjà « replié » et « tendu » tombent dans
    l'intervalle vide. Si une main réelle venait un jour combler ce trou, ce
    test le dirait avant que l'utilisateur ne le découvre devant sa caméra."""
    data = measure(tmp_path)
    o = data["defaults"]
    opened = [r["middleReach"] for r in data["rows"] if r["posture"] in ("open", "pinch")]
    closed = [r["middleReach"] for r in data["rows"] if r["posture"] in ("cpinch", "fist", "narrowc")]
    assert opened and closed
    assert max(closed) < min(opened), (
        f"recouvrement : main fermée jusqu'à {max(closed):.3f}, main ouverte dès {min(opened):.3f}"
    )
    assert max(closed) < o["fingerCurledPalms"] < o["fingerExtendedPalms"] < min(opened)


def test_the_canonical_fold_witness_separates_them_too(tmp_path):
    """Le témoin **canonique** (fusion du 28/09) n'est pas le majeur seul mais
    le plus loin des trois bouts — majeur, annulaire, auriculaire — contre la
    rampe `pointingFoldStartPalms` → `pointingFoldEndPalms` (décision 46). Il
    doit tenir sur les mêmes vraies mains : aucun recouvrement, et la rampe
    entière dans l'intervalle vide."""
    data = measure(tmp_path)
    o = data["defaults"]
    opened = [r["otherReach"] for r in data["rows"] if r["posture"] in ("open", "pinch")]
    closed = [r["otherReach"] for r in data["rows"] if r["posture"] in ("cpinch", "fist", "narrowc")]
    assert opened and closed
    assert max(closed) < o["pointingFoldStartPalms"] < o["pointingFoldEndPalms"] < min(opened), (
        f"main fermée jusqu'à {max(closed):.3f}, main ouverte dès {min(opened):.3f}"
    )


# --------------------------------------------------------------------------
# 2. L'affichage : rien ne se montre tant que la main ne vise pas
# --------------------------------------------------------------------------

def test_a_hand_that_merely_passes_in_front_of_the_camera_draws_nothing(tmp_path):
    """L'exigence de l'utilisateur, dans ses termes : « tant que je fais pas ce
    signe-là, je veux pas voir du hand tracking ». Une main ouverte, une main
    détendue, un poing — tout ce qu'une main fait quand elle ne demande rien —
    n'ouvre pas le portillon d'affichage. Ni jeton en interaction, ni anneau en
    veille : c'est le même portillon des deux côtés."""
    data = measure(tmp_path)
    visible = [
        (r["photo"], r["hand"], r["posture"], round(r["aim"], 3))
        for r in data["rows"]
        if r["posture"] in ("open", "fist") and r["shown"]
    ]
    assert visible == [], f"ces mains réelles feraient apparaître le pointeur sans qu'on le demande : {visible}"


def test_a_held_contact_keeps_its_pointer_even_when_the_index_curls_out_of_band(tmp_path):
    """Le répit, et pourquoi il n'est pas décoratif. En refermant la pince,
    l'index se courbe : sur `pinch_02`, une vraie main, sa portée tombe à
    1,203 paume, sous la bande de visée. Une règle purement géométrique ferait
    donc disparaître le pointeur **au moment du clic**. Un contact tenu vaut
    visée par lui-même, et c'est ce que ce test fixe.

    Fusion du 28/09 : le portillon du correctif (`createAimGate`,
    `aimGraceMs` 400 ms) s'est fondu dans la machine d'intention — le contact
    est l'**engagement** (`engaged` : contact `pinching`/`pressed` ou
    capture), le répit est `pointingExitMs` (300 ms, clé d'essai)."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "held.cjs"
    script.write_text(
        f"const B=require({json.dumps(str(SCRIPT))});\n"
        f"const doc=require({json.dumps(str(FIXTURE))});\n"
        "const h=doc.hands.find(x=>x.photo==='pinch_02.jpg');\n"
        "const k=h.aspect,lm=h.landmarks;\n"
        "const d=(a,b)=>Math.hypot((a.x-b.x)*k,a.y-b.y);\n"
        "const palm=d(lm[0],lm[9]);\n"
        "const score=B.pointingPostureScore(lm,k);\n"
        "const exit=B.DEFAULTS.pointingExitMs;\n"
        "const frame=(m,now,engaged)=>m.update({now,hands:[{handTrackId:1,posture:score,\n"
        "  stillness:1,quality:1,engaged}]}).hands[0].pointing;\n"
        "const released=at=>{const m=B.createPointingIntent();frame(m,0,true);frame(m,16,false);\n"
        "  return frame(m,16+at,false)};\n"
        "process.stdout.write(JSON.stringify({\n"
        "  indexReach:d(lm[0],lm[8])/palm,score,\n"
        "  geometryAlone:(()=>{const m=B.createPointingIntent();let p=false;\n"
        "    for(let t=0;t<=500;t+=16)p=frame(m,t,false);return p})(),\n"
        "  held:frame(B.createPointingIntent(),0,true),\n"
        "  graceKeepsIt:released(exit-1),\n"
        "  graceRunsOut:released(exit)}));",
        encoding="utf-8",
    )
    done = subprocess.run(
        [node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
    )
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout)

    assert got["indexReach"] < 1.35, "prémisse : l'index replié sort de la bande de visée"
    assert got["geometryAlone"] is False, "la géométrie seule perdrait cette main"
    assert got["held"] is True, "un contact tenu garde son pointeur"
    assert got["graceKeepsIt"] is True, "le répit couvre la traversée du pincement"
    assert got["graceRunsOut"] is False, "et il finit, sinon le pointeur ne s'éteindrait jamais"


def test_the_pointer_shows_while_the_thumb_and_index_close_in(tmp_path):
    """« Il devrait juste suivre quand je commence à faire le geste, quand je
    rapproche mon pouce et mon index. » Le portillon s'ouvre donc **avant** le
    pincement franc et **avant** la bande du réveil : une main réelle en visée,
    qu'on referme progressivement, allume le pointeur en chemin, et bien avant
    que le C ne compte."""
    rows, o = rows_of(tmp_path, "cpinch")
    assert o["aimGapMax"] >= o["wakeGapMax"], (
        "la visée doit s'ouvrir avant le C, sinon l'anneau de réveil serait "
        "caché au moment même où il compte"
    )
    # Le seuil d'apparition est plus tolérant que celui du clic, par construction.
    assert o["aimGapMax"] > o["releaseRatio"] > o["pressRatio"]


def test_the_narrow_c_of_thumb_and_index_both_wakes_and_shows(tmp_path):
    """Le cas positif, sur une vraie main : le geste que l'utilisateur décrit —
    « un C avec le doigt et le pouce », les trois autres doigts hors du chemin
    — doit à la fois **montrer** le pointeur et **tenir** le score de réveil.
    Sans lui, tout ce qui précède ne prouverait qu'une chose : qu'on a rendu le
    réveil plus difficile."""
    rows, o = rows_of(tmp_path, "narrowc")
    shown = [r for r in rows if r["shown"]]
    assert shown, f"aucune main en C étroit ne montre le pointeur : {[(r['photo'], round(r['aim'], 3)) for r in rows]}"
    woken = [r for r in rows if r["cPose"] >= o["wakeScore"]]
    assert woken, f"aucune main en C étroit ne tient le score de réveil : {[(r['photo'], round(r['cPose'], 3), round(r['gap'], 3), round(r['indexReach'], 3)) for r in rows]}"


# --------------------------------------------------------------------------
# 3. Ce que l'écran reçoit vraiment, sur une vraie main
# --------------------------------------------------------------------------

#: Le monde injecté, réduit à ce que cette question demande : une caméra, un
#: modèle qui rend **les points d'une vraie photographie**, et une
#: surimpression qui note ce qu'on lui donne à peindre. C'est le seul endroit
#: où l'exigence de l'utilisateur se mesure telle qu'il la vit — non pas « quel
#: score a cette posture », mais « combien de pointeurs arrivent à l'écran ».
WORLD = """
function world(landmarks,aspect,options){
  const log=[],frames=new Map();let frameId=0;
  const state={now:0,videoTime:0,result:{landmarks:landmarks?[landmarks]:[]}};
  const track={stopped:false,addEventListener(){},stop(){this.stopped=true}};
  const stream={getTracks:()=>[track],getVideoTracks:()=>[track]};
  const deps={
    options:options||{},
    getUserMedia:async()=>stream,
    createLandmarker:async()=>({detectForVideo:()=>state.result,close(){}}),
    /* Les points viennent d'une photographie : le rapport d'image doit être
       celui de cette photographie, sinon les distances horizontales seraient
       lues sous un autre objectif que celui qui les a produites. */
    attachVideo:async()=>({element:{},width:Math.round(1000*aspect),height:1000,
      currentTime:()=>state.videoTime,dispose(){}}),
    /* Fusion du 28/09 : la surimpression reçoit toutes les mains suivies
       (la pastille les compte, la lecture de diagnostic les liste) et ne
       **dessine** que celles qui pointent (`token.shown`, décision 46) ; le
       survol n'allume un bord que pour elles (`token.pointing`). On compte
       donc ce qui se dessine et ce qui peut survoler. */
    overlay:{mount(){},unmount(){},
      render(t){log.push('render:'+t.filter(x=>x.shown).length)},
      watch(w){log.push('watch:'+(w?(w.present?'1':'0'):'off'))}},
    interaction:{hover(t){log.push('hover:'+t.filter(x=>x.pointing).length)},click(){},clear(){},
      takeClicks:()=>[],refusal:()=>''},
    requestFrame:fn=>{const id=++frameId;frames.set(id,fn);return id},
    cancelFrame:id=>frames.delete(id),
    now:()=>state.now,viewport:()=>({width:1000,height:1000}),
    onStatus:()=>{},
  };
  const step=()=>{state.now+=16;state.videoTime+=1;
    const pending=[...frames.values()];frames.clear();pending.forEach(fn=>fn())};
  const steps=n=>{for(let i=0;i<n;i+=1)step()};
  return {deps,log,steps};
}
function painted(landmarks,aspect){
  return (async()=>{
    const w=world(landmarks,aspect);
    const c=B.createController(w.deps);
    await c.enable();
    w.steps(12);
    const sleep=w.log.filter(l=>l==='watch:1').length;
    c.activate();
    w.log.length=0;
    w.steps(12);
    const drawn=w.log.filter(l=>l.startsWith('render:')).map(l=>Number(l.slice(7)));
    const hovered=w.log.filter(l=>l.startsWith('hover:')).map(l=>Number(l.slice(6)));
    c.disable();
    return {ringShown:sleep,tokensDrawn:Math.max(0,...drawn),hovered:Math.max(0,...hovered)};
  })();
}
"""


def paint(tmp_path, photo):
    """Ce que la surimpression reçoit quand cette photographie est devant la
    caméra : l'anneau de veille, les jetons, le survol."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chosen = [h for h in hands() if h["photo"] == photo]
    if not chosen:
        pytest.skip(f"{photo} absente du jeu de mains réelles")
    hand = chosen[0]
    script = tmp_path / "painted.cjs"
    script.write_text(
        f"const B=require({json.dumps(str(SCRIPT))});\n"
        f"const doc=require({json.dumps(str(FIXTURE))});\n"
        + WORLD
        + f"const h=doc.hands.find(x=>x.photo==={json.dumps(photo)});\n"
        "painted(h.landmarks,h.aspect).then(v=>process.stdout.write(JSON.stringify(v)))"
        ".catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run(
        [node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
    )
    assert done.returncode == 0, done.stderr
    assert hand["landmarks"], photo
    return json.loads(done.stdout)


def test_an_open_hand_in_front_of_the_camera_paints_nothing_at_all(tmp_path):
    """**L'exigence, mesurée là où l'utilisateur la vit.** Une paume ouverte —
    une main qui passe, qui tape, qui tient quelque chose — est mise devant la
    caméra, en veille puis en interaction. La surimpression ne doit recevoir
    **aucun** anneau et **aucun** jeton : « tant que je fais pas ce signe-là,
    je veux pas voir du hand tracking ».

    Avant le portillon, cette même main peignait un anneau à chaque image de
    veille et un jeton à chaque image d'interaction — c'est le « tracker qui se
    balade partout »."""
    got = paint(tmp_path, "open_palm_03.jpg")
    assert got["ringShown"] == 0, "aucun anneau de veille sur une main qui ne demande rien"
    assert got["tokensDrawn"] == 0, "aucun jeton en interaction sur une main qui ne demande rien"
    assert got["hovered"] == 0, "et rien à survoler : un clic sans pointeur visible n'a pas d'auteur"


def test_a_real_open_c_at_0_6_palm_is_refused_for_its_fingers_not_its_gap(tmp_path):
    """Retour du 28/09/2026 : un C « ouvert » refusé à 0,56 – 0,63 paume, et
    l'utilisateur demandait d'« augmenter l'écart autorisé ». Sur une vraie
    main de même écart (`open_palm_03`, 0,613 paume), le C seul marque 1 : ce
    n'est pas l'écart qui refuse, c'est le repli des trois autres doigts — et
    l'étape du C le dit, bout le plus loin compris."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    contracts = RUNTIME / "control_center_barehands_contracts.js"
    calibration = RUNTIME / "control_center_barehands_calibration.js"
    script = tmp_path / "open-c.cjs"
    script.write_text(
        f"global.JarvisBarehandsContracts=require({json.dumps(str(contracts))});\n"
        f"const B=require({json.dumps(str(SCRIPT))});\n"
        f"const K=require({json.dumps(str(calibration))});\n"
        f"const doc=require({json.dumps(str(FIXTURE))});\n"
        "const h=doc.hands.find(x=>x.photo==='open_palm_03.jpg');\n"
        "const p=B.handPosture(h.landmarks,h.aspect);\n"
        "const s={gapPalms:p.gapPalms,indexReachPalms:p.reach.index,\n"
        "  otherFingersPalms:Math.max(p.reach.middle,p.reach.ring,p.reach.pinky),\n"
        "  cPose:B.cPoseScore(h.landmarks,h.aspect),wakePose:B.wakePostureScore(h.landmarks,h.aspect),secondaryRatio:.9};\n"
        "const band=K.wakeBandOf(B.DEFAULTS);\n"
        "const r=K.checkCPose(Array.from({length:30},()=>s),band,K.options({}));\n"
        "process.stdout.write(JSON.stringify({s,band,cause:r.cause,fold:r.fold,\n"
        "  pointing:B.pointingPostureScore(h.landmarks,h.aspect)}));\n",
        encoding="utf-8")
    out = json.loads(subprocess.run([node, str(script)], capture_output=True, text=True, check=True).stdout)
    assert out["band"]["gapMin"] <= out["s"]["gapPalms"] <= out["band"]["gapMax"]
    assert out["s"]["cPose"] == 1, "l'écart et l'index suffisent au C seul"
    assert out["s"]["wakePose"] == 0 and out["pointing"] == 0, "ni réveil ni curseur"
    assert out["cause"] == "fingers"
    assert out["fold"] > out["band"]["foldHeld"]
