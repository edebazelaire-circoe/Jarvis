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


def test_no_module_outside_the_contract_still_names_the_pointer_id_or_the_overlay():
    """Critère de la Slice : plus de dépendance accidentelle à un identifiant
    de pointeur ni à un sélecteur de surimpression recopiés."""

    for path in (BAREHANDS, SCENE_PAGE, PAGE_HTML):
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
    for key in ("tokenClass", "ringClass", "badgeClass"):
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
      });
    """)
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
        short:C.adapters.handFrameFromMediapipe({landmarks:[lm.slice(0,5)]},{t:0}).hands.length});
    """)
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
      });
    """)
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
        feedback:[body.feedback,edge.feedback,C.FEEDBACK.SECONDARY],
        tokens:Object.keys(C.FEEDBACK_TOKENS).sort(),
        zoned:['capsule','window','point','signal'].map(C.hasManipulationZones),
        badRegion:refused(()=>C.createTargetCandidate({region:'middle'})),
        badZone:refused(()=>C.createTargetCandidate({region:'corner',zone:'right'})),
        bodyHasNoZone:body.zone,
      });
    """)
    assert result["priority"] == [3, 2, 1, 0]
    assert result["picked"] == "bottom_right" and result["pickedWithoutCorner"] == "right"
    assert result["empty"] is None
    assert result["axes"] == [["x"], ["x", "y"], []]
    # Décision 23 : corps bleu, zone jaune, clic droit rouge — par le rôle.
    assert result["feedback"] == ["body", "zone", "secondary"]
    assert result["tokens"] == ["body", "secondary", "zone"]
    # Décision D3 de la Slice 00 : seules capsule et window ont des zones.
    assert result["zoned"] == [True, True, False, False]
    assert result["badRegion"] == "barehands_region_unknown"
    assert result["badZone"] == "barehands_zone_invalid"
    assert result["bodyHasNoZone"] is None


def test_two_captures_decompose_exactly_as_the_decision_log_says(tmp_path):
    result = run_node(tmp_path, """
      const cap=(hand,region,zone,objectId)=>C.createCapture({handTrackId:hand,region,zone,objectId:objectId||'w'});
      const edgeR=cap('a','edge','right'),edgeT=cap('b','edge','top');
      const cornerBR=cap('a','corner','bottom_right'),cornerTR=cap('b','corner','top_right');
      const cornerBL=cap('b','corner','bottom_left');
      out({
        differentObjects:C.combineCaptures(cap('a','edge','right','w1'),cap('b','edge','top','w2')),
        zoneAndBody:C.combineCaptures(edgeR,cap('b','body',null)),
        sameZone:C.combineCaptures(edgeR,cap('b','edge','right')),
        twoEdges:C.combineCaptures(edgeR,edgeT),
        edgeAndCorner:C.combineCaptures(edgeR,cornerTR),
        cornersSharingAnAxis:C.combineCaptures(cornerBR,cornerTR),
        oppositeCorners:C.combineCaptures(cornerBR,cap('b','corner','top_left')),
        cornersSharingX:C.combineCaptures(cornerBR,cornerBL),
        missing:C.combineCaptures(edgeR,null),
        unknownZone:C.combineCaptures({region:'edge',zone:'ailleurs',objectId:'w'},{region:'edge',zone:'nulle-part',objectId:'w'}),
        zoneRefused:refused(()=>cap('a','edge','ailleurs')),
        latched:cap('a','edge','right').state,
      });
    """)
    # Décision 12 : deux mains sur deux objets restent indépendantes.
    assert result["differentObjects"]["mode"] == "independent"
    # Décision 14 : ZONE + BODY ne forme jamais un redimensionnement.
    assert result["zoneAndBody"] == {"mode": "move", "axes": ["x", "y"], "reason": "body_is_not_a_resize_handle"}
    # Décision 15 : la même zone deux fois est refusée, avec un motif.
    assert result["sameZone"]["mode"] is None and result["sameZone"]["reason"] == "same_zone_rejected"
    assert result["twoEdges"] == {"mode": "resize", "axes": ["x", "y"], "reason": None}
    # Décision 16 : le bord tient l'axe partagé, le coin garde le reste.
    assert result["edgeAndCorner"]["mode"] == "resize" and result["edgeAndCorner"]["axes"] == ["x", "y"]
    # Décision 17 : deux coins qui partagent un axe le neutralisent.
    assert result["cornersSharingAnAxis"] == {"mode": "resize", "axes": ["y"], "reason": None}
    assert result["cornersSharingX"] == {"mode": "resize", "axes": ["x"], "reason": None}
    # Deux coins opposés ne partagent aucun côté : le cadre suit les deux axes.
    assert result["oppositeCorners"] == {"mode": "resize", "axes": ["x", "y"], "reason": None}
    assert result["missing"]["reason"] == "missing_capture"
    assert result["unknownZone"]["reason"] == "zone_unknown"
    assert result["zoneRefused"] == "barehands_zone_invalid"
    # Décision 13 : une capture est latchée jusqu'au relâchement.
    assert result["latched"] == "captured"


# --------------------------------------------------------- réglages et profil


def test_settings_survive_the_partial_and_never_widen_the_server_payload(tmp_path):
    result = run_node(tmp_path, """
      out({
        defaults:C.normalizeSettings(),
        fromNothing:C.normalizeSettings(null),
        partial:C.normalizeSettings({targetPreview:false,sensitivity:99,sleepTimeoutMs:1,tool:'gomme'}),
        junkDropped:Object.keys(C.normalizeSettings({inventé:true})).includes('inventé'),
        payload:C.toServerPayload({enabled:true,diagnostics:true,tool:'draw'}),
        tools:C.TOOLS,defaultTool:C.TOOL_DEFAULT,
        version:C.SETTINGS_SCHEMA_VERSION,
      });
    """)
    assert result["defaults"]["enabled"] is False, "Bare Hands reste éteint par défaut"
    assert result["defaults"]["targetPreview"] is True and result["defaults"]["sleepTimeoutMs"] == 30000
    assert result["fromNothing"] == result["defaults"]
    assert result["partial"]["targetPreview"] is False
    assert result["partial"]["sensitivity"] == 4 and result["partial"]["sleepTimeoutMs"] == 5000
    assert result["partial"]["tool"] == "pointer", "un outil inconnu retombe sur le défaut"
    assert result["junkDropped"] is False
    # La route `/api/barehands` ne connaît que `enabled` : ne rien lui envoyer d'autre.
    assert result["payload"] == {"enabled": True}
    assert result["tools"] == ["pointer", "pan", "highlighter", "draw", "select"]
    assert result["defaultTool"] == "pointer"
    assert result["version"] == barehands_test_mode.SCHEMA_VERSION


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
        clamped:C.normalizeProfile({hands:{left:{pressRatio:99,jitter:-3}}}).hands.left,
        liesRefused:C.normalizeProfile({calibrated:true}).calibrated,
        keys:Object.keys(C.HAND_PROFILE_DEFAULTS).sort(),
        version:C.PROFILE_SCHEMA_VERSION,
      });
    """)
    assert result["empty"]["calibrated"] is False and result["empty"]["updatedAt"] is None
    assert result["partialCalibrated"] is True
    assert result["leftPress"] == pytest.approx(0.2) and result["rightPress"] is None
    assert result["fallback"] == pytest.approx(0.28), "une fonction non calibrée reprend le défaut"
    assert result["measured"] == pytest.approx(0.2)
    assert result["clamped"]["pressRatio"] == pytest.approx(0.9) and result["clamped"]["jitter"] == 0
    assert result["liesRefused"] is False, "« calibré » sans mesure ne vaut pas calibré"
    # Décision 32 : que des paramètres dérivés et des métriques, pas de média.
    assert "image" not in result["keys"] and "frames" not in result["keys"]
    assert result["version"] == 1


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
        noAllocator:C.adapters.pointersFromCoreTokens([{id:'x',x:1,y:2}]).map(p=>p.pointerId),
        none:C.adapters.pointersFromCoreTokens(null),
      });
    """)
    assert result["ids"] == ["left", "right"]
    assert result["pointers"] == [9001, 9002], "deux mains, deux identités"
    assert result["primary"] == [True, False] and result["types"] == ["mouse"]
    assert result["phasesOpen"] == ["up", "up"]
    assert result["phasesDown"][0] == "down" and result["phasesDown"][1] == "up"
    assert result["channels"] == ["primary"], "le pincement d'aujourd'hui est le canal primaire"
    assert result["afterLoss"] == [9001]
    assert result["noAllocator"] == [9001]
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
