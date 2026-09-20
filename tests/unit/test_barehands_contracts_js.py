"""Contrats et schémas Bare Hands V1 (Slice 01), exécutés par node.

Cette Slice n'ajoute aucun moteur : elle fixe les noms. Ce qui est vérifié ici
est donc ce qu'un nom promet — l'identité de pointeur par main et sa
compatibilité avec l'unique `9001` d'hier, la neutralité du `HandFrame` vis-à-vis
de MediaPipe, les refus de schéma et leur code, la priorité d'aperçu des
régions, la décomposition de deux captures, et des réglages/profils qui
survivent au partiel. S'y ajoutent les vérifications côté serveur : le repère
est consommé, l'ordre d'insertion tient, et plus aucun module ne recopie ni
l'identifiant de pointeur ni les sélecteurs de la surimpression.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.runtime import barehands_test_mode
from jarvis.runtime.control_center import (
    BAREHANDS_CALIBRATION_SCRIPT_MARKER,
    BAREHANDS_CONTRACTS_SCRIPT_MARKER,
    BAREHANDS_SCRIPT_MARKER,
    SCENE_PAGE_SCRIPT_MARKER,
    ControlCenter,
)

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
CONTRACTS = RUNTIME / "control_center_barehands_contracts.js"
BAREHANDS = RUNTIME / "control_center_barehands.js"
SCENE_PAGE = RUNTIME / "control_center_scene_page.js"
PAGE_HTML = RUNTIME / "control_center.html"


def run_node(tmp_path: Path, source: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "barehands-contracts.cjs"
    script.write_text(
        f"const C=require({json.dumps(str(CONTRACTS))});\n"
        f"const Core=require({json.dumps(str(BAREHANDS))});\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "const refused=fn=>{try{fn();return null}catch(e){return e.code||String(e&&e.message||e)}};\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


# --------------------------------------------------------- identité de pointeur


def test_the_first_hand_keeps_todays_pointer_id_and_the_second_gets_its_own(tmp_path):
    """Constat F2 : `9001` était l'identité de *toutes* les mains. Il devient
    celle de la première, pour que l'expérience à une main soit inchangée."""

    result = run_node(tmp_path, """
      out({
        base:C.POINTER_ID_BASE,max:C.POINTER_ID_MAX,hands:C.MAX_HANDS,
        slots:[C.pointerIdForSlot(0),C.pointerIdForSlot(1)],
        mine:[9000,9001,9002,9003,'9001',null,1.5].map(C.isBareHandsPointerId),
        back:[C.slotForPointerId(9001),C.slotForPointerId(9002),C.slotForPointerId(7)],
        beyond:refused(()=>C.pointerIdForSlot(C.MAX_HANDS)),
        negative:refused(()=>C.pointerIdForSlot(-1)),
        type:C.POINTER_TYPE,
      });
    """)
    assert result["base"] == 9001 and result["max"] == 9002 and result["hands"] == 2
    assert result["slots"] == [9001, 9002]
    # Une chaîne « 9001 » est bien la nôtre (les événements DOM donnent un nombre,
    # mais un appelant distrait ne doit pas faire diverger la reconnaissance).
    assert result["mine"] == [False, True, True, False, True, False, False]
    assert result["back"] == [0, 1, None]
    assert result["beyond"] == "barehands_slot_out_of_range"
    assert result["negative"] == "barehands_slot_out_of_range"
    assert result["type"] == "mouse"


def test_a_hand_keeps_its_slot_while_it_lives_and_gives_it_back_when_it_leaves(tmp_path):
    result = run_node(tmp_path, """
      const s=C.createSlotAllocator(C.MAX_HANDS);
      const first=[s.slot('left'),s.slot('right'),s.slot('left')];
      const third=s.slot('ghost');
      s.retain(['right']);              // la gauche est partie
      const reused=s.slot('left-again');
      out({first,third,reused,pointer:s.pointerId('right'),
        afterClear:(s.clear(),s.size())});
    """)
    assert result["first"] == [0, 1, 0], "une main garde sa fente d'une image à l'autre"
    assert result["third"] is None, "au-delà de deux mains, pas de fente volée"
    assert result["reused"] == 0, "la fente d'une main partie est rendue"
    assert result["pointer"] == 9002 and result["afterClear"] == 0


def test_the_allocator_refuses_what_it_used_to_round_off(tmp_path):
    """Une capacité douteuse rendait un allocateur qui marche alors que
    l'appelant s'est trompé, et une clé non identifiée occupait une fente pour
    toujours. `forget`, le gel et la déstructuration n'étaient pas couverts."""

    result = run_node(tmp_path, """
      const s=C.createSlotAllocator(2);
      s.slot('a');s.slot('b');
      const forgotten=[s.forget('a'),s.forget('a'),s.size()];
      // Promotion : une main sans fente en reçoit une dès qu'il s'en libère,
      // et c'est bien la fente rendue, pas une nouvelle.
      const full=C.createSlotAllocator(2);
      full.slot('x');full.slot('y');
      const denied=full.slot('z');
      full.forget('x');
      const promoted=full.slot('z');
      const {pointerId}=C.createSlotAllocator(2);   // déstructuré : plus de `this`
      out({
        forgotten,denied,promoted,
        capacity:[C.createSlotAllocator().capacity,C.createSlotAllocator(1).capacity],
        occupancy:[full.size(),full.capacity],
        frozen:Object.isFrozen(s),
        destructured:pointerId('seule'),
        zero:refused(()=>C.createSlotAllocator(0)),
        text:refused(()=>C.createSlotAllocator('oops')),
        negative:refused(()=>C.createSlotAllocator(-1)),
        tooMany:refused(()=>C.createSlotAllocator(C.MAX_HANDS+1)),
        nullKey:refused(()=>C.createSlotAllocator(2).slot(null)),
        emptyKey:refused(()=>C.createSlotAllocator(2).slot('  ')),
        zeroKey:C.createSlotAllocator(2).slot(0),
      });
    """)
    assert result["forgotten"] == [True, False, 1], "`forget` rend la fente, une seule fois"
    assert result["denied"] is None and result["promoted"] == 0, "la fente rendue est reprise"
    assert result["capacity"] == [2, 1] and result["occupancy"] == [2, 2]
    assert result["frozen"] is True, "l'allocateur est gelé comme tout ce que rend le module"
    assert result["destructured"] == 9001, "`const {pointerId}=…` ne doit pas casser"
    for key in ("zero", "text", "negative", "tooMany"):
        assert result[key] == "barehands_slot_capacity_invalid", key
    assert result["nullKey"] == "barehands_hand_track_id_missing"
    assert result["emptyKey"] == "barehands_hand_track_id_missing"
    # `0` est une identité, pas une absence : c'est le premier identifiant
    # qu'émet un traqueur qui numérote ses pistes (Slice 03).
    assert result["zeroKey"] == 0


def test_no_module_outside_the_contract_still_names_the_pointer_id_or_the_overlay():
    """Critère de la Slice : plus de dépendance accidentelle à un identifiant
    de pointeur ni à un sélecteur de surimpression recopiés. Le balayage porte
    sur *tout* le runtime, pas sur trois chemins cités à la main : un module
    ajouté demain est couvert sans qu'on y pense."""

    swept = sorted(RUNTIME.glob("*.js")) + [PAGE_HTML]
    assert len(swept) > 3, "le balayage doit voir plus que les trois fichiers d'hier"
    for path in swept:
        if path == CONTRACTS:
            continue  # le contrat *possède* la plage : c'est le seul endroit où elle s'écrit
        source = path.read_text(encoding="utf-8")
        assert "9001" not in source, f"{path.name} recopie l'identifiant de pointeur"
    page = SCENE_PAGE.read_text(encoding="utf-8")
    assert "querySelector('#jarvisHands" not in page and 'querySelector("#jarvisHands' not in page


def test_the_style_sheets_agree_with_the_dom_names_the_contract_owns(tmp_path):
    """Une feuille de style ne peut pas lire le contrat : ce test le fait pour
    elle. Si un nom bouge dans le contrat sans bouger ici, la scène cesse de
    reconnaître Bare Hands en silence — ce test tombe d'abord."""

    names = run_node(tmp_path, "out(C.DOM);")
    barehands = BAREHANDS.read_text(encoding="utf-8")
    scene = SCENE_PAGE.read_text(encoding="utf-8")
    assert f"{names['rootSelector']}{{" in barehands
    # `wakeClass` (Slice 02) entre dans ce tuple plutôt que dans un test à
    # part : la dérive se prend par la comparaison contrat-feuille que ce dépôt
    # possède, pas par la coïncidence de deux littéraux Python.
    for key in ("tokenClass", "ringClass", "badgeClass", "wakeClass"):
        assert f"{names['rootSelector']} .{names[key]}" in barehands, key
    assert f".{names['hoverClass']}{{" in barehands
    # La scène décale ses indicateurs au-dessus du badge des mains.
    assert f"body:has({names['badgeSelector']}) .sc-status" in scene


# --------------------------------------------------------- HandFrame neutre


def test_a_hand_frame_is_validated_and_says_why_it_refuses(tmp_path):
    result = run_node(tmp_path, """
      const hand=(id,extra)=>Object.assign({handTrackId:id,handedness:'left',
        points:{wrist:{x:.5,y:.8},indexTip:{x:.4,y:.3},thumbTip:{x:.45,y:.33}}},extra||{});
      const frame=C.createHandFrame({t:12,source:{width:640,height:480,tracker:'test'},hands:[hand('a')]});
      out({
        version:frame.schemaVersion,t:frame.t,aspect:frame.source.aspect,tracker:frame.source.tracker,
        roles:Object.keys(frame.hands[0].points).sort(),
        handedness:frame.hands[0].handedness,quality:frame.hands[0].quality,
        unknownHandedness:C.createHandObservation(hand('b',{handedness:'gauche'})).handedness,
        clampedQuality:C.createHandObservation(hand('b',{quality:9})).quality,
        noTime:refused(()=>C.createHandFrame({source:{},hands:[]})),
        noId:refused(()=>C.createHandFrame({t:0,hands:[{points:{}}]})),
        duplicate:refused(()=>C.createHandFrame({t:0,hands:[hand('a'),hand('a')]})),
        crowd:refused(()=>C.createHandFrame({t:0,hands:[hand('a'),hand('b'),hand('c')]})),
        badPoint:refused(()=>C.createHandObservation({handTrackId:'a',points:{wrist:{x:'oui',y:1}}})),
        // `0` est une identité de piste, pas une absence.
        zeroId:C.createHandObservation({handTrackId:0,points:{}}).handTrackId,
        blankId:refused(()=>C.createHandObservation({handTrackId:'   ',points:{}})),
        nullId:refused(()=>C.createHandObservation({handTrackId:null,points:{}})),
      });
    """)
    assert result["zeroId"] == "0", "le premier identifiant d'un traqueur n'est pas une absence"
    assert result["blankId"] == "barehands_hand_track_id_missing"
    assert result["nullId"] == "barehands_hand_track_id_missing"
    assert result["version"] == 1 and result["t"] == 12
    assert result["aspect"] == pytest.approx(640 / 480) and result["tracker"] == "test"
    assert result["roles"] == ["indexTip", "thumbTip", "wrist"], "seuls les points fournis existent"
    assert result["handedness"] == "left" and result["quality"] == 1
    assert result["unknownHandedness"] == "unknown" and result["clampedQuality"] == 1
    assert result["noTime"] == "barehands_frame_time_invalid"
    assert result["noId"] == "barehands_hand_track_id_missing"
    assert result["duplicate"] == "barehands_hand_track_id_duplicate"
    assert result["crowd"] == "barehands_too_many_hands"
    assert result["badPoint"] == "barehands_point_invalid"


def test_mediapipe_indices_live_only_in_the_adapter(tmp_path):
    """Contrainte d'architecture : la donnée propre au traqueur ne traverse pas
    la frontière. Un moteur lit `points.indexTip`, jamais `landmarks[8]`."""

    result = run_node(tmp_path, """
      const lm=Array.from({length:21},(_,i)=>({x:i/21,y:.5,z:0}));
      const frame=C.adapters.handFrameFromMediapipe(
        {landmarks:[lm],handedness:[[{categoryName:'Right',score:.92}]]},
        {t:7,width:640,height:480});
      const hand=frame.hands[0];
      out({id:hand.handTrackId,handedness:hand.handedness,score:hand.handednessConfidence,
        indexTip:hand.points.indexTip.x,roles:Object.keys(hand.points).sort(),
        rawKept:hand.raw.length,tracker:frame.source.tracker,
        table:C.adapters.MEDIAPIPE_LANDMARK,
        imposed:C.adapters.handFrameFromMediapipe({landmarks:[lm,lm]},{t:0,trackIds:['h1','h2']}).hands.map(h=>h.handTrackId),
        // La Slice 03 passera des entiers : `0` est une piste, pas une absence.
        numeric:C.adapters.handFrameFromMediapipe(
          {landmarks:[lm,lm],handedness:[[{categoryName:'Left'}],[{categoryName:'Left'}]]},
          {t:0,trackIds:[0,1]}).hands.map(h=>h.handTrackId),
        // Sans identité imposée, la latéralité sert encore de repli.
        fallback:C.adapters.handFrameFromMediapipe({landmarks:[lm]},{t:0,trackIds:[null]}).hands[0].handTrackId,
        // Une troisième main se refuse ici comme dans `createHandFrame`, au
        // lieu d'être tranchée en silence par l'adaptateur.
        crowd:refused(()=>C.adapters.handFrameFromMediapipe({landmarks:[lm,lm,lm]},{t:0})),
        short:C.adapters.handFrameFromMediapipe({landmarks:[lm.slice(0,5)]},{t:0}).hands.length});
    """)
    assert result["numeric"] == ["0", "1"], "un identifiant numérique survit, y compris zéro"
    assert result["fallback"] == "hand-0"
    assert result["crowd"] == "barehands_too_many_hands"
    assert result["id"] == "right" and result["handedness"] == "right"
    assert result["score"] == pytest.approx(0.92)
    assert result["indexTip"] == pytest.approx(8 / 21), "indexTip vient du point 8, une seule fois"
    assert result["roles"] == sorted(["wrist", "thumbTip", "indexTip", "middleTip", "middleMcp", "ringMcp", "pinkyMcp"])
    assert result["rawKept"] == 21 and result["tracker"] == "mediapipe_hand_landmarker"
    assert result["table"]["indexTip"] == 8 and result["table"]["wrist"] == 0
    assert result["imposed"] == ["h1", "h2"], "la Slice 03 pourra imposer son identité"
    assert result["short"] == 0, "une main incomplète est ignorée, pas devinée"


def test_the_contract_module_touches_no_dom_network_or_clock():
    source = CONTRACTS.read_text(encoding="utf-8")
    body = source[source.index("(function(root)"):]
    for forbidden in ("document.", "window.", "fetch(", "XMLHttpRequest", "setTimeout", "Date.now", "performance.now", "localStorage"):
        assert forbidden not in body, forbidden


# --------------------------------------------------------- gestes et pincement


def test_gesture_and_pinch_events_carry_the_locked_vocabulary(tmp_path):
    result = run_node(tmp_path, """
      out({
        gestures:C.GESTURES,phases:C.GESTURE_PHASES,
        wake:C.createGestureEvent({gesture:'c_pose',phase:'hold',t:3,progress:.5,handTrackId:'a'}),
        holdMs:C.WAKE_HOLD_MS,sleepMs:C.SLEEP_TIMEOUT_MS,
        badGesture:refused(()=>C.createGestureEvent({gesture:'wave',phase:'start'})),
        badPhase:refused(()=>C.createGestureEvent({gesture:'fist',phase:'maybe'})),
        channels:C.PINCH_CHANNELS,fingers:C.PINCH_FINGERS,phasesP:C.PINCH_PHASES,
        down:C.createPinchEvent({channel:'primary',phase:'down',handTrackId:'a',slot:0,x:10,y:20,t:1}),
        right:C.createPinchEvent({channel:'secondary',phase:'down',handTrackId:'b',slot:1,x:0,y:0}),
        badChannel:refused(()=>C.createPinchEvent({channel:'middle',phase:'down',handTrackId:'a'})),
        anonymous:refused(()=>C.createPinchEvent({channel:'primary',phase:'down'})),
        scopes:C.GESTURE_SCOPES,
        // Une portée inconnue retombait sur `global`, celle qui peut voler la
        // main à une manipulation en cours : le plus dangereux des deux replis.
        badScope:refused(()=>C.createGestureEvent({gesture:'fist',phase:'end',scope:'Hand'})),
        // Un pincement sans coordonnées cliquait en (0,0) — le coin de
        // l'écran, où il y a toujours quelque chose à cliquer.
        noPoint:refused(()=>C.createPinchEvent({channel:'primary',phase:'down',handTrackId:'a'})),
        cancelHasNoPoint:C.createPinchEvent({channel:'primary',phase:'cancel',handTrackId:'a'}).x,
        zeroHand:C.createPinchEvent({channel:'primary',phase:'up',handTrackId:0,x:1,y:2}).handTrackId,
      });
    """)
    assert result["scopes"] == ["global", "hand"]
    assert result["badScope"] == "barehands_gesture_scope_unknown"
    assert result["noPoint"] == "barehands_pinch_position_missing"
    assert result["cancelHasNoPoint"] == 0, "seul `cancel` n'a rien à viser"
    assert result["zeroHand"] == "0"
    assert result["gestures"] == ["c_pose", "open_palm", "fist", "double_close", "clap"]
    assert result["phases"] == ["start", "hold", "end", "cancel"]
    assert result["wake"]["gesture"] == "c_pose" and result["wake"]["progress"] == 0.5
    assert result["wake"]["scope"] == "global" and result["wake"]["kind"] == "gesture"
    assert result["holdMs"] == 1000 and result["sleepMs"] == 30000
    assert result["badGesture"] == "barehands_gesture_unknown"
    assert result["badPhase"] == "barehands_gesture_phase_unknown"
    # Décisions 20 et 21 : pouce-index, puis pouce-majeur ; pas un appui long.
    assert result["channels"] == ["primary", "secondary"]
    assert result["fingers"] == {"primary": ["thumbTip", "indexTip"], "secondary": ["thumbTip", "middleTip"]}
    assert result["phasesP"] == ["approach", "down", "move", "up", "cancel"]
    assert result["down"]["pointerId"] == 9001 and result["down"]["progress"] == 1
    assert result["right"]["pointerId"] == 9002 and result["right"]["channel"] == "secondary"
    assert result["badChannel"] == "barehands_pinch_channel_unknown"
    assert result["anonymous"] == "barehands_hand_track_id_missing"


# --------------------------------------------------------- cibles et captures


def test_a_corner_wins_the_preview_over_an_edge_and_an_edge_over_the_body(tmp_path):
    result = run_node(tmp_path, """
      const body=C.createTargetCandidate({region:'body',kind:'window',objectId:'w'});
      const edge=C.createTargetCandidate({region:'edge',zone:'right',objectId:'w',representation:'window'});
      const corner=C.createTargetCandidate({region:'corner',zone:'bottom_right',objectId:'w'});
      out({
        priority:[C.regionPriority('corner'),C.regionPriority('edge'),C.regionPriority('body'),C.regionPriority('x')],
        picked:C.pickRegion([body,edge,corner]).zone,
        pickedWithoutCorner:C.pickRegion([body,edge]).zone,
        empty:C.pickRegion([]),
        axes:[edge.axes,corner.axes,body.axes],
        /* Le rôle de couleur se demande à `feedbackRole`, avec le canal : une
           candidate n'en porte plus, parce qu'elle ne connaît pas le canal.
           Cette ligne lisait `body.feedback`/`edge.feedback` — la copie
           aveugle au canal — et son résultat n'était jamais affirmé. */
        feedback:[C.feedbackRole(body.region,'primary'),
                  C.feedbackRole(edge.region,'primary'),
                  C.feedbackRole(corner.region,'secondary')],
        onCandidate:[body.feedback,edge.feedback,corner.feedback],
        tokens:Object.keys(C.FEEDBACK_TOKENS).sort(),
        zoned:['capsule','window','point','signal'].map(C.hasManipulationZones),
        badRegion:refused(()=>C.createTargetCandidate({region:'middle'})),
        badZone:refused(()=>C.createTargetCandidate({region:'corner',zone:'right'})),
        bodyHasNoZone:body.zone,
        // `distancePx` était porté et jamais lu : l'ordre des arguments
        // tranchait les égalités de priorité.
        nearest:C.pickRegion([{region:'edge',zone:'right',distancePx:50},
                              {region:'edge',zone:'top',distancePx:5}]).zone,
        // Une région hors table n'est pas une candidate du tout ; avant, la
        // première citée gagnait avant que la priorité soit consultée.
        bogusOnly:C.pickRegion([{region:'middle'},{region:'nulle-part'}]),
        bogusLoses:C.pickRegion([{region:'middle'},{region:'body'}]).region,
        // Décision 3 : une candidate non actionnable n'appelle aucun retour
        // visuel — la laisser gagner, c'est ne plus rien montrer.
        actionableFirst:C.pickRegion([{region:'corner',zone:'top_left',actionable:false},
                                      {region:'body',actionable:true}]).region,
        // Unités : des pixels de fenêtre, jamais des unités de scène.
        units:Object.keys(C.createTargetCandidate({region:'body'})).filter(k=>/^(bounds|distance)/.test(k)).sort(),
      });
    """)
    assert result["nearest"] == "top", "à priorité égale, la plus proche gagne"
    assert result["bogusOnly"] is None
    assert result["bogusLoses"] == "body"
    assert result["actionableFirst"] == "body"
    assert result["units"] == ["boundsPx", "distancePx"], "l'unité se lit dans le nom"
    assert result["priority"] == [3, 2, 1, 0]
    assert result["picked"] == "bottom_right" and result["pickedWithoutCorner"] == "right"
    assert result["empty"] is None
    assert result["axes"] == [["x"], ["x", "y"], []]
    # Décision 23 : corps bleu, zone jaune, clic droit rouge — par le rôle, et
    # par lui seul. Le coin est ici en `secondary` : c'est précisément le cas
    # que la copie portée par la candidate rendait « zone ».
    assert result["feedback"] == ["body", "zone", "secondary"]
    assert result["onCandidate"] == [None, None, None], "une candidate ne porte pas de couleur"
    assert result["tokens"] == ["body", "secondary", "zone"]
    # Décision D3 de la Slice 00 : seules capsule et window ont des zones.
    assert result["zoned"] == [True, True, False, False]
    assert result["badRegion"] == "barehands_region_unknown"
    assert result["badZone"] == "barehands_zone_invalid"
    assert result["bodyHasNoZone"] is None


def test_two_captures_decompose_exactly_as_the_decision_log_says(tmp_path):
    result = run_node(tmp_path, """
      const cap=(hand,region,zone,objectId)=>C.createCapture({handTrackId:hand,region,zone,
        objectId:objectId===undefined?'w':objectId});
      const edgeR=cap('a','edge','right'),edgeT=cap('b','edge','top');
      const cornerBR=cap('a','corner','bottom_right'),cornerTR=cap('b','corner','top_right');
      const cornerBL=cap('b','corner','bottom_left');
      out({
        differentObjects:C.combineCaptures(cap('a','edge','right','w1'),cap('b','edge','top','w2')),
        zoneAndBody:C.combineCaptures(edgeR,cap('b','body',null)),
        bodyAndBody:C.combineCaptures(cap('a','body',null),cap('b','body',null)),
        sameZone:C.combineCaptures(edgeR,cap('b','edge','right')),
        twoEdges:C.combineCaptures(edgeR,edgeT),
        edgeAndCorner:C.combineCaptures(edgeR,cornerTR),
        edgeApart:C.combineCaptures(edgeT,cornerBR),
        cornersSharingAnAxis:C.combineCaptures(cornerBR,cornerTR),
        oppositeCorners:C.combineCaptures(cornerBR,cap('b','corner','top_left')),
        cornersSharingX:C.combineCaptures(cornerBR,cornerBL),
        missing:C.combineCaptures(edgeR,null),
        anonymous:C.combineCaptures(cap('a','edge','right',null),cap('b','edge','top',null)),
        sameHand:C.combineCaptures(edgeR,cap('a','edge','top')),
        oneBadZone:refused(()=>C.combineCaptures(
          {handTrackId:'a',region:'corner',zone:'top_left',objectId:'w'},
          {handTrackId:'b',region:'edge',zone:'bogus',objectId:'w'})),
        bothBadZones:refused(()=>C.combineCaptures(
          {handTrackId:'a',region:'edge',zone:'ailleurs',objectId:'w'},
          {handTrackId:'b',region:'edge',zone:'nulle-part',objectId:'w'})),
        badRegion:refused(()=>C.combineCaptures({handTrackId:'a',region:'middle',objectId:'w'},edgeT)),
        anonymousHand:refused(()=>C.combineCaptures({region:'edge',zone:'right',objectId:'w'},edgeT)),
        zoneRefused:refused(()=>cap('a','edge','ailleurs')),
        badState:refused(()=>C.createCapture({handTrackId:'a',region:'edge',zone:'right',state:'releasd'})),
        badChannel:refused(()=>C.createCapture({handTrackId:'a',region:'edge',zone:'right',channel:'middle'})),
        latched:cap('a','edge','right').state,
      });
    """)
    # Décision 12 : deux mains sur deux objets restent indépendantes.
    assert result["differentObjects"]["mode"] == "independent"
    # Décision 14 : ZONE + BODY ne forme jamais un redimensionnement — et le
    # déplacement appartient à la seule main qui tient la zone (décision 10).
    assert result["zoneAndBody"] == {
        "mode": "move", "axes": ["x", "y"],
        "byHand": {"a": {"sides": ["right"], "axes": ["x", "y"]}},
        "reason": "body_is_not_a_resize_handle",
    }
    # Décision 8 : BODY est de l'interaction de contenu, pas une poignée de
    # cadre. Deux mains dans le contenu emportaient la fenêtre entière.
    assert result["bodyAndBody"] == {
        "mode": None, "axes": [], "byHand": {}, "reason": "both_captures_are_body",
    }
    # Décision 15 : la même zone deux fois est refusée, avec un motif.
    assert result["sameZone"]["mode"] is None and result["sameZone"]["reason"] == "same_zone_rejected"
    assert result["twoEdges"]["axes"] == ["x", "y"]
    assert result["twoEdges"]["byHand"] == {
        "a": {"sides": ["right"], "axes": ["x"]}, "b": {"sides": ["top"], "axes": ["y"]},
    }
    # Décision 16 : le bord possède le côté partagé, le coin ne garde que
    # l'autre. Avec la seule union d'axes, ce cas et le suivant rendaient le
    # même résultat octet pour octet, alors qu'ils demandent des attributions
    # opposées — la règle était affirmée, jamais prouvée.
    assert result["edgeAndCorner"]["axes"] == ["x", "y"]
    assert result["edgeAndCorner"]["byHand"] == {
        "a": {"sides": ["right"], "axes": ["x"]}, "b": {"sides": ["top"], "axes": ["y"]},
    }
    assert result["edgeApart"]["axes"] == ["x", "y"]
    assert result["edgeApart"]["byHand"] == {
        "b": {"sides": ["top"], "axes": ["y"]},
        "a": {"sides": ["bottom", "right"], "axes": ["x", "y"]},
    }, "un bord et un coin qui ne se recouvrent pas ne s'attribuent pas comme ceux qui se recouvrent"
    assert result["edgeAndCorner"]["byHand"] != result["edgeApart"]["byHand"]
    # Décision 17 : deux coins qui tiennent le même côté le neutralisent ; il
    # reste à chacun le côté opposé, donc un axe manipulable à deux mains.
    assert result["cornersSharingAnAxis"]["axes"] == ["y"]
    assert result["cornersSharingAnAxis"]["byHand"] == {
        "a": {"sides": ["bottom"], "axes": ["y"]}, "b": {"sides": ["top"], "axes": ["y"]},
    }
    assert result["cornersSharingX"]["axes"] == ["x"]
    # Deux coins opposés ne partagent aucun côté : le cadre suit les deux axes.
    assert result["oppositeCorners"]["axes"] == ["x", "y"]
    assert result["oppositeCorners"]["byHand"]["a"]["sides"] == ["bottom", "right"]
    assert result["missing"]["reason"] == "missing_capture"
    # Sans `objectId`, on ne peut pas dire « le même objet » : deux éléments
    # anonymes restaient un redimensionnement fantôme.
    assert result["anonymous"] == {
        "mode": "independent", "axes": [], "byHand": {}, "reason": "object_unidentified",
    }
    # `byHand` est indexé par identité : une main deux fois s'écraserait.
    assert result["sameHand"]["reason"] == "same_hand_twice"
    # Une seule zone douteuse suffisait à produire un redimensionnement sûr de
    # lui ; le refus promis par le contrat n'existait pas.
    assert result["oneBadZone"] == "barehands_zone_invalid"
    assert result["bothBadZones"] == "barehands_zone_invalid"
    assert result["badRegion"] == "barehands_region_unknown"
    assert result["anonymousHand"] == "barehands_hand_track_id_missing"
    assert result["zoneRefused"] == "barehands_zone_invalid"
    # Un état inconnu retombait sur `captured` : la capture latchait pour
    # toujours (décision 13) sans que rien ne dise pourquoi.
    assert result["badState"] == "barehands_capture_state_unknown"
    assert result["badChannel"] == "barehands_pinch_channel_unknown"
    # Décision 13 : une capture est latchée jusqu'au relâchement.
    assert result["latched"] == "captured"


def test_an_interaction_event_has_a_shape_and_refuses_what_it_cannot_carry(tmp_path):
    """`INTERACTION` n'était que dix chaînes : pas de fabrique, pas de charge
    utile, pas de refus, et aucun test. Six des sept structures de ce fichier
    ont la leur ; celle que la Slice 06 publiera l'a maintenant aussi."""

    result = run_node(tmp_path, """
      out({
        names:C.INTERACTIONS,
        scroll:C.createInteractionEvent({type:'scroll',handTrackId:'a',slot:1,x:10,y:20,
          dx:0,dy:-40,objectId:'w',channel:'secondary',tool:'pan',t:5}),
        resize:C.createInteractionEvent({type:'resize',handTrackId:0,x:1,y:2,axes:['y','x']}),
        unknown:refused(()=>C.createInteractionEvent({type:'wave',handTrackId:'a',x:0,y:0})),
        anonymous:refused(()=>C.createInteractionEvent({type:'click',x:0,y:0})),
        nowhere:refused(()=>C.createInteractionEvent({type:'click',handTrackId:'a'})),
        noDelta:refused(()=>C.createInteractionEvent({type:'scroll',handTrackId:'a',x:0,y:0})),
        badAxis:refused(()=>C.createInteractionEvent({type:'move',handTrackId:'a',x:0,y:0,axes:['z']})),
        badTool:refused(()=>C.createInteractionEvent({type:'click',handTrackId:'a',x:0,y:0,tool:'gomme'})),
        badChannel:refused(()=>C.createInteractionEvent({type:'click',handTrackId:'a',x:0,y:0,channel:'middle'})),
        frozen:Object.isFrozen(C.createInteractionEvent({type:'hover',handTrackId:'a',x:0,y:0})),
      });
    """)
    assert result["names"] == [
        "hover", "click", "context", "drag_start", "drag_move", "drag_end",
        "scroll", "select", "move", "resize",
    ]
    assert result["scroll"]["pointerId"] == 9002 and result["scroll"]["dy"] == -40
    assert result["scroll"]["channel"] == "secondary" and result["scroll"]["tool"] == "pan"
    assert result["scroll"]["kind"] == "interaction" and result["scroll"]["schemaVersion"] == 1
    assert result["resize"]["handTrackId"] == "0" and result["resize"]["axes"] == ["y", "x"]
    assert result["resize"]["pointerId"] is None, "sans fente, pas de pointeur inventé"
    assert result["unknown"] == "barehands_interaction_unknown"
    assert result["anonymous"] == "barehands_hand_track_id_missing"
    assert result["nowhere"] == "barehands_interaction_position_missing"
    assert result["noDelta"] == "barehands_interaction_delta_missing"
    assert result["badAxis"] == "barehands_axis_unknown"
    # Un événement n'est pas un réglage : `normalizeTool` tolère l'inconnu
    # parce qu'il normalise un schéma stocké, une interaction le refuse.
    assert result["badTool"] == "barehands_tool_unknown"
    assert result["badChannel"] == "barehands_pinch_channel_unknown"
    assert result["frozen"] is True


# --------------------------------------------------------- réglages et profil


def test_settings_survive_the_partial_and_carry_the_whole_widened_payload(tmp_path):
    result = run_node(tmp_path, """
      out({
        defaults:C.normalizeSettings(),
        fromNothing:C.normalizeSettings(null),
        partial:C.normalizeSettings({targetPreview:false,sensitivity:99,sleepTimeoutMs:1,tool:'gomme'}),
        junkDropped:Object.keys(C.normalizeSettings({inventé:true})).includes('inventé'),
        payload:C.toServerPayload({enabled:true,diagnostics:true,tool:'select'}),
        tools:C.TOOLS,defaultTool:C.TOOL_DEFAULT,
        version:C.SETTINGS_SCHEMA_VERSION,
        // Version 1 : la **couture de migration**. Elle ne se taisait pas
        // avant la Slice 07, elle refusait ; c'est le refus qui devient le
        // point d'entrée de la conversion le jour où une version arrive.
        migrated:C.normalizeSettings({schemaVersion:1,enabled:true,sleepTimeoutMs:45000}),
        // Le numéro de schéma était estampillé en sortie et jamais lu en
        // entrée : une v99 revenait en v1, champs inconnus jetés, en silence.
        foreign:refused(()=>C.normalizeSettings({schemaVersion:99,enabled:true,newField:1})),
        foreignProfile:refused(()=>C.normalizeProfile({schemaVersion:99})),
        // La v1 du profil, elle, se **convertit** : la Slice 08 a monté le
        // schéma, ses six mesures restent valides.
        migratedProfile:C.normalizeProfile({schemaVersion:1,hands:{left:{pressRatio:.2}}}),
        // Aller-retour complet : ce que la route rend se relit dans le
        // vocabulaire du contrat, sans qu'aucune clé ne se perde en route.
        roundTrip:C.fromServerState(C.toServerPayload({enabled:true,tool:'pan',
          sleepTimeoutMs:45000,assistance:.25,sensitivity:2,diagnostics:true,
          targetPreview:false,tutorialSeen:true,calibrationEnabled:false})),
        // Le serveur annonce sa version ; une version étrangère venue de la
        // route se refuse comme une version étrangère venue du fichier.
        foreignFromServer:refused(()=>C.fromServerState({schema_version:99,enabled:true})),
      });
    """)
    assert result["migrated"]["enabled"] is True, "une version précédente se convertit"
    assert result["migrated"]["sleepTimeoutMs"] == 45000, "et garde ce qu'elle portait"
    assert result["migrated"]["schemaVersion"] == barehands_test_mode.SCHEMA_VERSION
    assert result["foreign"] == "barehands_schema_version_unsupported"
    assert result["foreignFromServer"] == "barehands_schema_version_unsupported"
    assert result["foreignProfile"] == "barehands_schema_version_unsupported"
    assert result["migratedProfile"]["schemaVersion"] == 2
    assert result["migratedProfile"]["hands"]["left"]["pressRatio"] == 0.2
    assert result["migratedProfile"]["hands"]["left"]["travelSlopNorm"] is None, (
        "la clé que la v1 ne portait pas reste non mesurée, elle ne s'invente pas"
    )
    assert result["defaults"]["enabled"] is False, "Bare Hands reste éteint par défaut"
    assert result["defaults"]["targetPreview"] is True and result["defaults"]["sleepTimeoutMs"] == 30000
    assert result["fromNothing"] == result["defaults"]
    assert result["partial"]["targetPreview"] is False
    assert result["partial"]["sensitivity"] == 4 and result["partial"]["sleepTimeoutMs"] == 5000
    assert result["partial"]["tool"] == "pointer", "un outil inconnu retombe sur le défaut"
    assert result["junkDropped"] is False
    # Slice 07 : la route accepte les neuf réglages, en `snake_case` comme le
    # reste du Control Center, estampillés de la version que les deux côtés
    # ont montée ensemble.
    assert result["payload"] == {
        "schema_version": barehands_test_mode.SCHEMA_VERSION,
        "enabled": True, "target_preview": True, "sleep_timeout_ms": 30000,
        "tool": "select", "assistance": 0.5, "sensitivity": 1,
        "tutorial_seen": False, "calibration_enabled": True, "diagnostics": True,
    }
    assert set(result["payload"]) - {"schema_version"} == set(barehands_test_mode.SETTINGS_DEFAULTS), (
        "les deux tables des réglages nomment exactement les mêmes clés"
    )
    assert result["roundTrip"] == {
        "schemaVersion": barehands_test_mode.SCHEMA_VERSION,
        "enabled": True, "targetPreview": False, "sleepTimeoutMs": 45000,
        "tool": "pan", "assistance": 0.25, "sensitivity": 2,
        "tutorialSeen": True, "calibrationEnabled": False, "diagnostics": True,
    }
    assert result["tools"] == ["pointer", "pan", "select"]
    assert result["defaultTool"] == "pointer"
    assert result["version"] == barehands_test_mode.SCHEMA_VERSION


def test_a_tool_declares_a_capability_and_an_uninstalled_one_says_so(tmp_path):
    """Décision 25 : un outil dit « ce que la main veut dire ».

    La capacité **est** un mode de contenu du moteur, donc « installé » se lit
    sur une table et non sur un drapeau écrit à la main — un outil déclaré sans
    moteur ne peut pas ressembler à un outil qui marche.
    """

    result = run_node(tmp_path, """
      out({
        described:C.describeTools(),
        installed:C.INSTALLED_TOOLS,
        served:C.SERVED_CAPABILITIES,
        contextual:C.toolCapability('pointer'),
        unknown:refused(()=>C.toolCapability('gomme')),
        // Chaque outil de `TOOL` a une capacité et une étiquette : un outil
        // ajouté sans elles serait dessiné sans nom et gaterait sur undefined.
        everyToolHasACapability:C.TOOLS.every(t=>typeof C.TOOL_CAPABILITY[t]==='string'),
        everyToolHasALabel:C.TOOLS.every(t=>typeof C.TOOL_LABEL[t]==='string'&&C.TOOL_LABEL[t].length>0),
        // Et l'inverse : aucune capacité servie sans outil qui la demande.
        noOrphanCapability:C.SERVED_CAPABILITIES.every(
          cap=>cap===C.TOOL_CAPABILITY_CONTEXTUAL||C.TOOLS.some(t=>C.TOOL_CAPABILITY[t]===cap)),
        // Tolérance documentée : un schéma **stocké** retombe sur le défaut.
        normalized:C.normalizeTool('gomme'),
        // La couche d'annotation est hors V1 : ses deux outils ne sont plus
        // déclarés, donc ils se refusent comme n'importe quel nom inconnu.
        annotate:refused(()=>C.toolCapability('highlighter')),
        allDeclaredAreInstalled:C.TOOLS.every(C.toolInstalled),
        annotateServed:C.SERVED_CAPABILITIES.includes('annotate'),
      });
    """)
    assert result["unknown"] == "barehands_tool_unknown"
    assert result["contextual"] == "contextual"
    assert result["normalized"] == "pointer"
    assert result["everyToolHasACapability"] is True
    assert result["everyToolHasALabel"] is True
    assert result["noOrphanCapability"] is True
    assert result["installed"] == list(barehands_test_mode.INSTALLED_TOOLS)
    by_id = {tool["id"]: tool for tool in result["described"]}
    assert by_id["pointer"]["capability"] == "contextual" and by_id["pointer"]["installed"] is True
    assert by_id["pan"]["capability"] == "scroll" and by_id["pan"]["installed"] is True
    assert by_id["select"]["capability"] == "select" and by_id["select"]["installed"] is True
    # La couche d'annotation est **hors V1** : `highlighter` et `draw` ont
    # quitté la table plutôt que d'y rester déclarés et refusés. La palette
    # offre donc exactement ce qui marche.
    assert set(by_id) == {"pointer", "pan", "select"}
    assert result["annotate"] == "barehands_tool_unknown"
    assert all(tool["reason"] == "" for tool in result["described"] if tool["installed"])
    # Et ce qui reste vrai après le retrait : aucun outil déclaré n'est
    # désinstallé, et `toolInstalled` continue de **lire** la table servie
    # plutôt que d'affirmer « oui » — c'est la recette d'extension.
    assert result["allDeclaredAreInstalled"] is True
    assert result["annotateServed"] is False


def test_the_settings_bounds_are_one_table_and_refuse_an_inverted_pair(tmp_path):
    """`clamp(v, lo, hi)` rend `lo` quand `lo > hi` : une borne inversée
    épinglerait tous les réglages sur une seule valeur, sans exception ni test
    rouge. Il n'y a pas de constructeur là où vit la table — le refus se pose
    donc au chargement du module, comme `MIN_SIZE`/`MAX_SIZE` à la Slice 06."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    source = CONTRACTS.read_text(encoding="utf-8")
    broken = source.replace("sleepTimeoutMs:Object.freeze({min:5000,max:600000,step:5000})",
                            "sleepTimeoutMs:Object.freeze({min:600000,max:5000,step:5000})")
    assert broken != source, "la table des bornes a changé de forme : ce test doit suivre"
    (tmp_path / "broken.js").write_text(broken, encoding="utf-8")
    shim = tmp_path / "load-broken.cjs"
    shim.write_text(
        "try{require('./broken.js');console.log(JSON.stringify({loaded:true}))}"
        "catch(error){console.log(JSON.stringify({error:String(error.message)}))}",
        encoding="utf-8",
    )
    out = subprocess.run([node, str(shim)], capture_output=True, text=True, encoding="utf-8",
                         cwd=tmp_path, timeout=30, check=True)
    assert "le minimum doit rester sous le maximum" in json.loads(out.stdout)["error"]

    # **La seconde moitié de la garde, qui n'était pas exercée** (Slice 11) : la
    # même boucle refuse aussi un **défaut** tombé hors de ses propres bornes.
    # C'est le cas le plus probable des deux — une borne se change en pensant
    # au curseur, et le défaut qui vivait dedans se retrouve dehors. Sans ce
    # test, la table pouvait perdre cette ligne sans qu'un seul test rougisse :
    # une garde que personne n'exerce est un vœu.
    stray = source.replace("assistance:0.5,", "assistance:9,")
    assert stray != source, "le défaut visé a changé de nom : ce test doit suivre"
    (tmp_path / "stray.js").write_text(stray, encoding="utf-8")
    shim.write_text(
        "try{require('./stray.js');console.log(JSON.stringify({loaded:true}))}"
        "catch(error){console.log(JSON.stringify({error:String(error.message)}))}",
        encoding="utf-8",
    )
    out = subprocess.run([node, str(shim)], capture_output=True, text=True, encoding="utf-8",
                         cwd=tmp_path, timeout=30, check=True)
    answer = json.loads(out.stdout)
    assert answer.get("loaded") is not True, "un défaut hors de ses bornes s'est chargé sans un mot"
    assert "SETTINGS_DEFAULTS.assistance tombe hors de ses propres bornes" in answer["error"]

    result = run_node(tmp_path, """
      out({
        keys:Object.keys(C.SETTINGS_BOUNDS).sort(),
        // Les bornes du contrat sont celles que `normalizeSettings` applique :
        // une table lue par l'écran et une autre par la normalisation auraient
        // dessiné des curseurs dont les extrémités ne veulent rien dire.
        low:C.normalizeSettings({sleepTimeoutMs:-1,assistance:-1,sensitivity:-1}),
        high:C.normalizeSettings({sleepTimeoutMs:1e9,assistance:9,sensitivity:9}),
        bounds:C.SETTINGS_BOUNDS,
      });
    """)
    assert result["keys"] == ["assistance", "sensitivity", "sleepTimeoutMs"]
    for key in result["keys"]:
        assert result["low"][key] == result["bounds"][key]["min"]
        assert result["high"][key] == result["bounds"][key]["max"]
        assert result["bounds"][key]["min"] < result["bounds"][key]["max"]


def test_a_partial_calibration_is_valid_and_the_rest_falls_back(tmp_path):
    """Décisions 28, 31 et 32 : un profil visible unique, valeurs internes par
    main, partiel accepté, et aucune image conservée."""

    result = run_node(tmp_path, """
      const partial=C.normalizeProfile({hands:{left:{pressRatio:.2}}});
      out({
        empty:C.normalizeProfile(),
        partialCalibrated:partial.calibrated,
        leftPress:partial.hands.left.pressRatio,rightPress:partial.hands.right.pressRatio,
        fallback:C.profileValue(partial,'right','pressRatio',.28),
        measured:C.profileValue(partial,'left','pressRatio',.28),
        clamped:C.normalizeProfile({hands:{left:{pressRatio:99,jitterPx:-3}}}).hands.left,
        liesRefused:C.normalizeProfile({calibrated:true}).calibrated,
        keys:Object.keys(C.HAND_PROFILE_DEFAULTS).sort(),
        version:C.PROFILE_SCHEMA_VERSION,
        // `calibrated` n'inspectait que 3 des 7 clés mesurables : le drapeau
        // et la donnée se contredisaient dès qu'une autre mesure existait.
        // Depuis, l'inverse : `quality` est une **métrique** et non un seuil,
        // et elle est écrite dès qu'un seau de main a vu une image — donc un
        // parcours dont les sept étapes avaient échoué se disait « calibré ».
        eachKeyCounts:Object.fromEntries(Object.keys(C.HAND_PROFILE_DEFAULTS).map(key=>{
          const value=key==='reachNorm'?{x:0,y:0,w:.5,h:.5}:key==='quality'?.8:.3;
          return [key,C.normalizeProfile({hands:{left:{[key]:value}}}).calibrated]})),
        metricKeys:C.PROFILE_METRIC_KEYS,
        calibratingKeys:C.PROFILE_CALIBRATING_KEYS,
        // La main que le traqueur n'étiquette pas perdait sa calibration : le
        // seau `unknown` n'existait pas, alors que c'est le repli par défaut
        // de `createHandObservation`.
        buckets:Object.keys(C.normalizeProfile().hands),
        unknownHand:C.profileValue(C.normalizeProfile({hands:{unknown:{pressRatio:.2}}}),
          'unknown','pressRatio',.28),
        badHandedness:refused(()=>C.profileValue(C.normalizeProfile(),'gauche','pressRatio',.28)),
        badKey:refused(()=>C.profileValue(C.normalizeProfile(),'left','pression',.28)),
        // Mesures impossibles : un pincement qui ne peut jamais se relâcher,
        // une portée plate qui ramène tout l'écran sur un point.
        noHysteresis:refused(()=>C.normalizeProfile({hands:{left:{pressRatio:.6,releaseRatio:.1}}})),
        noHysteresis2:refused(()=>C.normalizeProfile({hands:{right:{secondaryPressRatio:.6,secondaryReleaseRatio:.1}}})),
        flatReach:refused(()=>C.normalizeProfile({hands:{left:{reachNorm:{x:0,y:0,w:0,h:0}}}})),
        goodReach:C.normalizeProfile({hands:{left:{reachNorm:{x:.1,y:.1,w:.8,h:9}}}}).hands.left.reachNorm,
      });
    """)
    assert result["empty"]["calibrated"] is False and result["empty"]["updatedAt"] is None
    assert result["partialCalibrated"] is True
    assert result["leftPress"] == pytest.approx(0.2) and result["rightPress"] is None
    assert result["fallback"] == pytest.approx(0.28), "une fonction non calibrée reprend le défaut"
    assert result["measured"] == pytest.approx(0.2)
    assert result["clamped"]["pressRatio"] == pytest.approx(0.9) and result["clamped"]["jitterPx"] == 0
    assert result["liesRefused"] is False, "« calibré » sans mesure ne vaut pas calibré"
    # Décision 32 : que des paramètres dérivés et des métriques, pas de média.
    assert "image" not in result["keys"] and "frames" not in result["keys"]
    # Unités dans le nom : pixels de fenêtre pour le tremblement, coordonnées
    # normalisées de l'image pour la portée (jamais des unités de scène).
    assert result["keys"] == sorted([
        "pressRatio", "releaseRatio", "secondaryPressRatio", "secondaryReleaseRatio",
        "jitterPx", "travelSlopNorm", "reachNorm", "quality",
    ])
    assert result["version"] == 2
    # **Chaque clé qui adapte le moteur compte pour « calibré » ; la métrique
    # qui ne l'adapte pas, non.** `quality` est écrite pour tout seau de main
    # ayant vu une image : la compter rendait `calibrated` vrai après une séance
    # où les sept étapes avaient échoué, et l'onglet affichait « Calibré » pour
    # un profil sans une seule mesure.
    assert result["metricKeys"] == ["quality"]
    assert sorted(result["calibratingKeys"]) == sorted([
        "pressRatio", "releaseRatio", "secondaryPressRatio", "secondaryReleaseRatio",
        "jitterPx", "travelSlopNorm", "reachNorm",
    ])
    for key in result["calibratingKeys"]:
        assert result["eachKeyCounts"][key] is True, key
    for key in result["metricKeys"]:
        assert result["eachKeyCounts"][key] is False, key
    # Et l'exclusion s'écrit, jamais l'inclusion : une clé ajoutée demain
    # calibre par défaut.
    assert set(result["calibratingKeys"]) | set(result["metricKeys"]) == set(result["keys"])
    assert result["buckets"] == ["left", "right", "unknown"]
    assert result["unknownHand"] == pytest.approx(0.2)
    assert result["badHandedness"] == "barehands_handedness_unknown"
    assert result["badKey"] == "barehands_profile_key_unknown"
    assert result["noHysteresis"] == "barehands_profile_thresholds_invalid"
    assert result["noHysteresis2"] == "barehands_profile_thresholds_invalid"
    assert result["flatReach"] == "barehands_profile_reach_invalid"
    assert result["goodReach"] == {"x": 0.1, "y": 0.1, "w": 0.8, "h": 1}, "0..1, bornes comprises"


def test_a_stored_profile_survives_its_own_json_round_trip(tmp_path):
    """**La mine que la Slice 08 a trouvée en persistant le profil.**

    `Number(null)` vaut `0`, qui est fini : une valeur **non mesurée** était
    donc bornée sur son minimum au lieu de rester nulle. Tant que rien ne
    relisait un profil, l'entrée venait toujours d'un objet partiel où la clé
    **manquait** (`undefined` → `NaN` → `null`) et la mine ne mordait pas. Mais
    un profil persisté est du JSON, et du JSON porte des `null` explicites :
    relire un profil vierge rendait les huit mesures « calibrées » à leur
    plancher — `pressRatio` 0,05, `travelSlopNorm` 0,002 — donc `calibrated`
    vrai sans qu'une seule mesure ait eu lieu, `updatedAt` au 1er janvier 1970,
    et `profileValue` rendant ce plancher **au lieu du défaut du moteur**. La
    décision 31 était défaite par une conversion de type.

    L'aller-retour est donc l'assertion, pas la valeur : un profil qui ne
    revient pas égal à lui-même n'est pas persistable.
    """

    result = run_node(tmp_path, """
      const round=profile=>C.normalizeProfile(JSON.parse(JSON.stringify(C.toProfilePayload(profile))));
      const blank=C.normalizeProfile();
      const measured=C.normalizeProfile({updatedAt:1700,hands:{
        left:{pressRatio:.2,releaseRatio:.4,travelSlopNorm:.1,reachNorm:{x:.1,y:.2,w:.6,h:.5}},
        right:{jitterPx:3.5,quality:.75}}});
      const withStages=C.normalizeProfile({stages:{
        neutral:{status:'ok',samples:42},
        c_pose:{status:'failed',reason:'barehands_stage_timeout',samples:3}}});
      out({
        blankStable:JSON.stringify(round(blank))===JSON.stringify(blank),
        blankCalibrated:round(blank).calibrated,
        blankUpdatedAt:round(blank).updatedAt,
        blankPress:round(blank).hands.left.pressRatio,
        // Et la conséquence directe : le défaut du moteur, pas le plancher.
        blankFallback:C.profileValue(round(blank),'left','pressRatio',.28),
        measuredStable:JSON.stringify(round(measured))===JSON.stringify(measured),
        measuredAt:round(measured).updatedAt,
        stagesStable:JSON.stringify(round(withStages).stages)===JSON.stringify(withStages.stages),
        stages:round(withStages).stages,
        /* Un `ok` qui porte un motif d'echec et un `failed` **muet** disent deux
           choses contraires. Le second est le plus dangereux : « ca n'a pas
           marche » sans raison ne se distingue pas d'une panne, et c'est tout
           le silence que cette Slice existe pour refuser. */
        okWithReason:refused(()=>C.normalizeStage({status:'ok',reason:C.STAGE_REASON.TIMEOUT})),
        failedMute:refused(()=>C.normalizeStage({status:'failed'})),
        failedNamed:C.normalizeStage({status:'failed',reason:C.STAGE_REASON.NO_HAND,samples:3}),
        skippedMute:C.normalizeStage({status:'skipped'}),
      });
    """)
    assert result["blankStable"] is True, "un profil vierge doit revenir vierge"
    assert result["blankCalibrated"] is False, "relire un profil ne le calibre pas"
    assert result["blankUpdatedAt"] is None, "ni ne le date du 1er janvier 1970"
    assert result["blankPress"] is None
    assert result["blankFallback"] == pytest.approx(0.28), (
        "une mesure absente rend le défaut du moteur, jamais le plancher de sa borne"
    )
    assert result["measuredStable"] is True and result["measuredAt"] == 1700
    assert result["stagesStable"] is True
    assert result["stages"]["neutral"] == {"status": "ok", "reason": None, "samples": 42}
    assert result["stages"]["c_pose"]["reason"] == "barehands_stage_timeout"
    assert result["stages"]["drag"]["status"] == "skipped", "ce qu'on n'a pas joué n'a pas échoué"
    assert result["okWithReason"] == "barehands_stage_report_inconsistent"
    assert result["failedMute"] == "barehands_stage_report_inconsistent", (
        "un échec sans raison ne se distingue pas d'une panne"
    )
    assert result["failedNamed"] == {
        "status": "failed", "reason": "barehands_stage_no_hand", "samples": 3}
    # `skipped` est le seul état qui ait le droit d'être muet : ne pas jouer une
    # étape n'a pas de cause à donner.
    assert result["skippedMute"] == {"status": "skipped", "reason": None, "samples": 0}


def test_nothing_but_a_derived_scalar_can_reach_a_stored_profile(tmp_path):
    """**Décision 32, tenue en structure et non en intention.**

    Deux gardes, et elles ne se doublent pas. `normalizeProfile` est une
    **liste blanche** : il reconstruit le profil clé par clé, donc une clé que
    le schéma ne nomme pas n'atteint jamais le fil — pas parce qu'on la refuse,
    parce qu'on ne la recopie pas. Ce qu'elle ne protège pas, c'est le schéma
    **lui-même** : une Slice ultérieure pouvait ajouter à
    `HAND_PROFILE_DEFAULTS` une clé acceptant un objet libre, et la décision 32
    serait tombée sans qu'une ligne change ailleurs. `assertDerivedOnly` est
    donc posée sur la **forme**, au chargement du module — même idiome que
    l'inversion de `SETTINGS_BOUNDS`. La poser aussi sur chaque charge utile
    serait la « seconde vérité » que ce dépôt refuse : elle ne pourrait pas
    échouer.
    """

    result = run_node(tmp_path, """
      const gate=value=>refused(()=>C.assertDerivedOnly(value));
      out({
        landmarks:gate({hands:{left:{landmarks:[{x:.1,y:.2}]}}}),
        emptyList:gate({samples:[]}),
        base64:gate({thumbnail:'data:image/png;base64,iVBORw0KGgo='}),
        freeText:gate({note:'la main gauche de Clarice'}),
        infinite:gate({quality:Infinity}),
        // Ce que le schéma nomme passe : nombres, booléens, `null`, et les
        // seuls mots d'un vocabulaire fermé.
        derived:gate(C.normalizeProfile({hands:{left:{pressRatio:.2}}})),
        words:gate({status:'ok',reason:'barehands_stage_timeout'}),
        /* La garde de forme tourne au chargement : si elle n'avait pas tourné,
           le module se serait chargé quand même. On la relance donc sur le
           schéma rempli pour que la ligne de chargement soit **exercée** et
           non seulement présente. */
        schemaChecked:(()=>{C.assertDerivedOnly(C.PROFILE_DEFAULTS);return true})(),
        /* Et la porte est **sur le chemin** de la persistance, pas à côté.
           Deux gardes, pas une : `normalizeProfile` est une liste blanche —
           une clé que le schéma ne nomme pas n'atteint jamais la seconde —
           et `assertDerivedOnly` vérifie ce qui a survécu. La première est ce
           qui rend la seconde inatteignable par un appelant ordinaire, et
           c'est la bonne nouvelle : la décision 32 ne dépend pas d'elle
           seule. */
        smuggled:Object.keys(C.toProfilePayload(Object.assign(
          JSON.parse(JSON.stringify(C.normalizeProfile())),
          {frames:['AAAA'],thumbnail:'data:image/png;base64,AA'}))),
        smuggledInHand:Object.keys(C.toProfilePayload({schemaVersion:2,
          hands:{left:{pressRatio:.2,landmarks:[{x:1,y:2}]}}}).hands.left),
        // `reachNorm` est la seule forme imbriquée du schéma : elle est
        // rebâtie de ses quatre nombres, donc elle ne peut pas devenir la
        // poche où tout passe.
        reachPocket:Object.keys(C.toProfilePayload({schemaVersion:2,hands:{left:{
          reachNorm:{x:0,y:0,w:1,h:1,blob:'data:image/png;base64,AA'}}}}).hands.left.reachNorm),
        reachOk:C.toProfilePayload({schemaVersion:2,hands:{left:{
          reachNorm:{x:0,y:0,w:1,h:1}}}}).hands.left.reachNorm,
      });
    """)
    for case in ("landmarks", "emptyList", "base64", "freeText", "infinite"):
        assert result[case] == "barehands_profile_not_derived", case
    assert result["derived"] is None and result["words"] is None
    # Première garde : la liste blanche. Ce que le schéma ne nomme pas n'existe
    # pas dans ce qui part sur le fil — ni au sommet, ni dans une main.
    assert sorted(result["smuggled"]) == ["calibrated", "hands", "schemaVersion", "stages", "updatedAt"]
    assert "frames" not in result["smuggled"] and "thumbnail" not in result["smuggled"]
    assert "landmarks" not in result["smuggledInHand"]
    assert sorted(result["smuggledInHand"]) == sorted([
        "pressRatio", "releaseRatio", "secondaryPressRatio", "secondaryReleaseRatio",
        "jitterPx", "travelSlopNorm", "reachNorm", "quality",
    ])
    assert sorted(result["reachPocket"]) == ["h", "w", "x", "y"], "reachNorm est rebâtie, pas recopiée"
    assert result["reachOk"] == {"x": 0, "y": 0, "w": 1, "h": 1}
    # Seconde garde : la **forme**. Le module refuse de se charger si le schéma
    # lui-même admet autre chose qu'un scalaire — c'est ce qui tient la
    # décision 32 contre la Slice suivante, et non contre l'appelant d'à côté.
    assert result["schemaChecked"] is True


# --------------------------------------------------------- compatibilité


def test_the_current_click_experiment_maps_onto_the_new_identity_unchanged(tmp_path):
    """Chemin de compatibilité : les jetons que produit `JarvisBarehandsCore`
    aujourd'hui se lisent dans le vocabulaire de la Slice 01, la première main
    gardant l'identifiant d'hier."""

    result = run_node(tmp_path, """
      const tracker=Core.createHandTracker();
      const hand=(gap,x)=>{const lm=Array.from({length:21},()=>({x:.5,y:.5,z:0}));
        lm[0]={x:.5,y:.8,z:0};lm[9]={x:.5,y:.6,z:0};lm[8]={x,y:.5,z:0};lm[4]={x:x+gap,y:.5,z:0};return lm};
      const frame=now=>({viewport:{width:1000,height:800},aspect:1,now});
      const both={landmarks:[hand(.5,.4),hand(.5,.6)],handedness:[[{categoryName:'Left'}],[{categoryName:'Right'}]]};
      const slots=C.createSlotAllocator(C.MAX_HANDS);
      const open=C.adapters.pointersFromCoreTokens(tracker.update(both,frame(0)).tokens,slots);
      // Pincement franc de la main gauche : elle clique.
      const pinched={landmarks:[hand(.02,.4),hand(.5,.6)],handedness:both.handedness};
      tracker.update(pinched,frame(20));
      const down=C.adapters.pointersFromCoreTokens(tracker.update(pinched,frame(40)).tokens,slots);
      // La main droite disparaît, puis une autre arrive : elle reprend la fente.
      const alone={landmarks:[hand(.5,.4)],handedness:[[{categoryName:'Left'}]]};
      const after=C.adapters.pointersFromCoreTokens(tracker.update(alone,frame(60)).tokens,slots);
      out({
        ids:open.map(p=>p.handTrackId),pointers:open.map(p=>p.pointerId),
        primary:open.map(p=>p.isPrimary),types:[...new Set(open.map(p=>p.pointerType))],
        phasesOpen:open.map(p=>p.phase),phasesDown:down.map(p=>p.phase),
        channels:[...new Set(down.map(p=>p.channel))],
        afterLoss:after.map(p=>p.pointerId),
        // L'allocateur n'est pas optionnel : un allocateur neuf par image
        // donne la fente 0 à qui passe en premier cette image-là, et les deux
        // mains échangent leur `pointerId` en plein glissement.
        noAllocator:refused(()=>C.adapters.pointersFromCoreTokens([{id:'x',x:1,y:2}])),
        notAnAllocator:refused(()=>C.adapters.pointersFromCoreTokens([{id:'x'}],{})),
        // Un jeton sans identité gardait la fente 0 pour toujours sous une
        // clé fantôme, et la main suivante repartait à 9002.
        anonymousToken:refused(()=>C.adapters.pointersFromCoreTokens([null],C.createSlotAllocator(2))),
        stillFirst:(()=>{const s=C.createSlotAllocator(2);
          try{C.adapters.pointersFromCoreTokens([null],s)}catch(_e){}
          return C.adapters.pointersFromCoreTokens([{id:'vraie',x:0,y:0}],s).map(p=>p.pointerId)})(),
        // `0` est une identité de piste (Slice 03), pas une absence.
        zeroToken:C.adapters.pointersFromCoreTokens([{id:0,x:0,y:0}],C.createSlotAllocator(2))
          .map(p=>[p.handTrackId,p.pointerId,p.isPrimary]),
        none:C.adapters.pointersFromCoreTokens(null,C.createSlotAllocator(2)),
      });
    """)
    # Slice 03 : l'identité d'une main est un numéro de piste stable, pas la
    # latéralité annoncée — que le traqueur réétiquette d'une image à l'autre.
    assert result["ids"] == ["0", "1"]
    assert result["pointers"] == [9001, 9002], "deux mains, deux identités"
    assert result["primary"] == [True, False] and result["types"] == ["mouse"]
    assert result["phasesOpen"] == ["up", "up"]
    assert result["phasesDown"][0] == "down" and result["phasesDown"][1] == "up"
    assert result["channels"] == ["primary"], "le pincement d'aujourd'hui est le canal primaire"
    assert result["afterLoss"] == [9001]
    assert result["noAllocator"] == "barehands_allocator_required"
    assert result["notAnAllocator"] == "barehands_allocator_required"
    assert result["anonymousToken"] == "barehands_hand_track_id_missing"
    assert result["stillFirst"] == [9001], "un jeton refusé ne vole pas la fente 0"
    assert result["zeroToken"] == [["0", 9001, True]]
    assert result["none"] == []


# --------------------------------------------------------- insertion dans la page


async def test_the_page_serves_the_contracts_before_everything_that_reads_them(tmp_path):
    """Constat F3 : un module de page est un repère substitué par le serveur, et
    son rang est porteur. Les contrats précèdent le pointeur et la scène, qui
    les lisent tous deux."""

    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    html = (await control.index(None)).text
    raw = PAGE_HTML.read_text(encoding="utf-8")
    assert BAREHANDS_CONTRACTS_SCRIPT_MARKER in raw, "le repère vit dans la page"
    assert raw.index(BAREHANDS_CONTRACTS_SCRIPT_MARKER) < raw.index(BAREHANDS_SCRIPT_MARKER)
    assert raw.index(BAREHANDS_SCRIPT_MARKER) < raw.index(SCENE_PAGE_SCRIPT_MARKER)
    assert BAREHANDS_CONTRACTS_SCRIPT_MARKER not in html, "le repère n'a pas été remplacé"
    assert "root.JarvisBarehandsContracts=api" in html
    assert "window.JarvisBarehandsContracts" not in raw, "la page ne le définit pas elle-même"
    # Inséré avant ses deux lecteurs, et avant le balayage `inert` qui l'appelle.
    assert (
        html.index("root.JarvisBarehandsContracts=api")
        < html.index("function installJarvisBarehands")
        < html.index("function installJarvisScene")
    )
    assert "JarvisBarehandsContracts.isOverlayRoot(el)" in html


async def test_the_server_announces_the_settings_schema_version(tmp_path):
    state = barehands_test_mode.describe({}, tmp_path)
    assert state["schema_version"] == barehands_test_mode.SCHEMA_VERSION
    assert state["enabled"] is False and state["status"] == "experimental"


async def test_the_page_serves_the_calibration_before_the_pointer_that_reads_it(tmp_path):
    """Constat F3 : un module de page est un repère substitué par le serveur, et
    son rang est porteur. Celui-ci est lu par `control_center_barehands.js`
    pour poser `JarvisBarehands.calibrate()` sur sa surface — **gelée**, donc
    impossible à compléter après coup. Servi trop tard, la page casserait à
    l'insertion et non trois clics plus tard, ce qui est le but.

    L'ordre est asserté **par index dans la page servie**, pas par la présence
    des repères : deux modules peuvent être présents et mal ordonnés."""

    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    html = (await control.index(None)).text
    raw = PAGE_HTML.read_text(encoding="utf-8")

    assert BAREHANDS_CALIBRATION_SCRIPT_MARKER in raw, "le repère vit dans la page"
    assert BAREHANDS_CALIBRATION_SCRIPT_MARKER not in html, "le repère a été remplacé"
    # Dans la source : contrats → cible → calibration → pointeur.
    assert (raw.index(BAREHANDS_CONTRACTS_SCRIPT_MARKER)
            < raw.index(BAREHANDS_CALIBRATION_SCRIPT_MARKER)
            < raw.index(BAREHANDS_SCRIPT_MARKER))
    # Et dans la page **servie**, sur le code lui-même.
    assert (html.index("root.JarvisBarehandsContracts=api")
            < html.index("root.JarvisBarehandsCalibration=api")
            < html.index("function installJarvisBarehands"))
    assert "window.JarvisBarehandsCalibration" not in raw, "la page ne le définit pas elle-même"
    # Le module refuse de se charger sans les contrats : l'ordre casse à
    # l'insertion, comme pour l'aperçu de cible et le canal de commandes.
    assert "les contrats Bare Hands doivent être insérés avant ce module" in html


def test_the_calibration_stylesheet_agrees_with_the_dom_names_the_contract_owns(tmp_path):
    """Meme regle que pour la surimpression des mains : le contrat possede les
    noms du DOM, la feuille les dessine. Une classe renommee d'un cote sort ici
    au lieu de produire une coque invisible.

    La feuille est lue **produite** et non dans la source : elle est composee a
    partir des noms du contrat, donc relire le fichier ne montrerait que les
    interpolations — c'est le texte rendu qui doit porter les vrais noms.
    """

    result = run_node(tmp_path, """
      const K=require(%s);
      out({dom:C.DOM,style:K.STYLE,styleId:K.STYLE_ID});
    """ % json.dumps(str(RUNTIME / "control_center_barehands_calibration.js")))
    names, style = result["dom"], result["style"]

    assert result["styleId"] == names["flowStyleId"]
    assert f"#{names['flowRootId']}{{" in style
    for key in ("flowStepClass", "flowProgressClass", "flowNoteClass", "flowTargetClass"):
        assert f"#{names['flowRootId']} .{names[key]}" in style, key
    # La coque vit **sous** la surimpression des mains : l'utilisateur calibre
    # avec ses mains, donc son jeton doit rester visible par-dessus.
    hands = (RUNTIME / "control_center_barehands.js").read_text(encoding="utf-8")
    assert "z-index:2147483000" in hands, "la surimpression des mains, inchangee"
    assert "z-index:2147482000" in style
    assert 2147482000 < 2147483000
    # Et la cible a la taille que le produit dessine : 24 px, pas une capsule
    # de confort qu'aucune main n'aurait a viser (lecon des fixtures de la tache).
    assert "width:24px;height:24px" in style
    # Le mouvement se coupe quand l'utilisateur l'a demande au systeme.
    assert "prefers-reduced-motion" in style


def test_the_calibration_constants_are_pinned_like_every_other_engine_table(tmp_path):
    """Une table que personne n'affirme se mute sans rien faire tomber. Les
    réglages du parcours, ses étapes et le vocabulaire du rapport sont épinglés
    ici, comme `DEFAULTS` l'est pour le moteur."""

    result = run_node(tmp_path, """
      const K=require(%s);
      out({
        defaults:Object.keys(K.DEFAULTS).sort().map(k=>[k,K.DEFAULTS[k]]),
        steps:K.STEPS.map(s=>[s.id,s.hold===true,s.needs]),
        stages:C.STAGES,statuses:C.STAGE_STATUSES,reasons:C.STAGE_REASONS,
        profileVersion:C.PROFILE_SCHEMA_VERSION,
        measured:C.PROFILE_MEASURED_KEYS,
      });
    """ % json.dumps(str(RUNTIME / "control_center_barehands_calibration.js")))

    assert result["defaults"] == [
        ["pinchRepeats", 4],
        ["pressAt", 0.35],
        ["releaseAt", 0.65],
        ["sampleQualityMin", 0.4],
        ["separationMinPalms", 0.12],
        ["stageHoldMs", 2500],
        ["stageMinSamples", 20],
        ["stageTimeoutMs", 20000],
        ["travelSlopMargin", 1.6],
        ["travelSlopMax", 0.15],
        ["travelSlopMin", 0.002],
        # Le chien de garde de la page : c'est lui qui fait qu'une étape que
        # personne ne nourrit expire quand même. Publié ici pour que la paire
        # dangereuse `watchdogMs < stageTimeoutMs` ait ses deux nombres au même
        # endroit, comme celle du tutoriel.
        ["watchdogMs", 500],
    ]
    assert dict(result["defaults"])["watchdogMs"] < dict(result["defaults"])["stageTimeoutMs"]
    # Les sept étapes du contrat, dans l'ordre, avec ce que chacune exige.
    assert result["steps"] == [
        ["neutral", True, 1], ["c_pose", True, 1],
        ["pinch_primary", False, 1], ["pinch_secondary", False, 1],
        ["aim", False, 1], ["drag", False, 1], ["resize", False, 2],
    ]
    assert [step[0] for step in result["steps"]] == result["stages"], (
        "les étapes du parcours sont celles que le profil persiste, pas une seconde liste"
    )
    assert result["statuses"] == ["ok", "failed", "skipped"]
    assert result["reasons"] == [
        "barehands_stage_no_hand", "barehands_stage_timeout",
        "barehands_stage_too_few_samples", "barehands_stage_not_separable",
        "barehands_stage_out_of_band", "barehands_stage_needs_two_hands",
        "barehands_stage_cancelled",
    ]
    assert result["profileVersion"] == 2
    assert sorted(result["measured"]) == sorted([
        "pressRatio", "releaseRatio", "secondaryPressRatio", "secondaryReleaseRatio",
        "jitterPx", "travelSlopNorm", "reachNorm", "quality",
    ])


def test_the_module_refuses_to_load_if_the_schema_itself_admits_an_image(tmp_path):
    """**La garde de forme, exercee pour de vrai.**

    `assertDerivedOnly` tourne au chargement du module et sonde chaque cle
    mesurable. Tant qu'aucune cle ne fuit, la retirer ne fait rien tomber — ce
    qui est exactement le cas d'un garde-fou tourne vers l'avenir. On le
    mesure donc comme il se mesure : en **ecrivant la Slice future**, c'est-a-
    dire en ajoutant au contrat une cle qui recopie son entree, et en
    verifiant que le module refuse alors de se charger.
    """

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    source = CONTRACTS.read_text(encoding="utf-8")
    leaky = source.replace(
        "    quality:null,                            // 0..1, confiance de la mesure\n  });",
        "    quality:null,\n    sampleFrames:null,\n  });", 1)
    before = leaky
    leaky = leaky.replace(
        "      quality:ratio(source.quality,0,1),\n    });",
        "      quality:ratio(source.quality,0,1),\n"
        "      sampleFrames:source.sampleFrames||null,\n    });", 1)
    assert leaky != before and leaky != source, "les deux ancres de la mutation doivent exister"

    victim = tmp_path / "leaky-contracts.js"
    victim.write_text(leaky, encoding="utf-8")
    script = tmp_path / "leak.cjs"
    script.write_text(
        f"try{{require({json.dumps(str(victim))});process.stdout.write('LOADED')}}"
        "catch(e){process.stdout.write(String(e&&e.code||e))}",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True,
                          encoding="utf-8", timeout=30, check=False)
    assert done.returncode == 0, done.stderr
    assert done.stdout == "barehands_profile_not_derived", (
        "une cle du profil qui recopie son entree doit faire refuser le chargement du module"
    )

    # Et le contrat **reel**, lui, se charge : la sonde ne crie pas au loup.
    ok = tmp_path / "ok.cjs"
    ok.write_text(
        f"require({json.dumps(str(CONTRACTS))});process.stdout.write('LOADED')",
        encoding="utf-8")
    done = subprocess.run([node, str(ok)], capture_output=True, text=True,
                          encoding="utf-8", timeout=30, check=False)
    assert done.stdout == "LOADED"


def _module_load(tmp_path: Path, source: str, name: str) -> str:
    """Charger une copie du contrat et rendre le code de refus, ou `LOADED`."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    victim = tmp_path / f"{name}-contracts.js"
    victim.write_text(source, encoding="utf-8")
    script = tmp_path / f"{name}.cjs"
    script.write_text(
        f"try{{require({json.dumps(str(victim))});process.stdout.write('LOADED')}}"
        "catch(e){process.stdout.write(String(e&&e.code||e))}",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True,
                          encoding="utf-8", timeout=30, check=False)
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_the_gate_reaches_the_nested_pocket_and_the_only_free_string(tmp_path):
    """**Les deux champs que la décision 32 nomme comme le risque, et que la
    sonde n'atteignait pas.**

    Un refus de la normalisation est une réponse sûre — la valeur n'est pas
    passée — mais ce n'est pas une couverture, et le `catch(_refused){continue}`
    de la sonde avalait précisément les deux qui comptent : une `reachNorm`
    portant une sonde brute dégénère (`w`/`h` à zéro) et se fait refuser avant
    le gate, et `reason` était toujours accompagné de `status:'ok'`, ce qui rend
    le rapport incohérent et le fait refuser lui aussi. Le contrat annonçait
    pourtant « chaque champ d'étape ».

    On le mesure comme la garde de forme se mesure : en **écrivant la Slice
    future** de chaque côté, et en vérifiant que le module refuse alors de se
    charger."""

    source = CONTRACTS.read_text(encoding="utf-8")

    # 1. `reachNorm` cesse d'être rebâtie de ses quatre nombres et recopie son
    #    entrée : la seule poche imbriquée du schéma devient celle où tout passe.
    leaky_reach = source.replace(
        "    const reachNorm=given?Object.freeze({x:unit(given.x,0),y:unit(given.y,0),\n"
        "      w:unit(given.w,0),h:unit(given.h,0)}):null;",
        "    const reachNorm=given?Object.freeze({...given}):null;", 1)
    assert leaky_reach != source, "l'ancre de la mutation doit exister"
    assert _module_load(tmp_path, leaky_reach, "reach") == "barehands_profile_not_derived", (
        "une reachNorm qui recopie son entrée doit faire refuser le chargement"
    )

    # 2. `reason` cesse d'être borné à la liste fermée : le seul champ en forme
    #    de texte libre redevient un commentaire libre.
    leaky_reason = source.replace(
        "    const reason=STAGE_REASONS.includes(source.reason)?source.reason:null;",
        "    const reason=source.reason===undefined?null:source.reason;", 1)
    assert leaky_reason != source, "l'ancre de la mutation doit exister"
    assert _module_load(tmp_path, leaky_reason, "reason") == "barehands_profile_not_derived", (
        "un motif d'étape en texte libre doit faire refuser le chargement"
    )

    # Et le contrat réel se charge : la sonde ne crie pas au loup.
    assert _module_load(tmp_path, source, "real") == "LOADED"
