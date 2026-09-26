"""Bare Hands — l'enregistrement fusionné du profil de calibration (tâche
adaptative, Slice 09, décision 69, décision 31 amendée).

Une calibration ne remplace plus le profil entier : elle **annonce** ce qu'elle
remplace (`replaces`), et seules ces valeurs changent. Une étape passée (bouton
ou voix, quelle que soit la raison) ou échouée garde ce qui était enregistré ;
l'autre main est gardée ; `tuning` suit son propre chemin (décision 48).

Ce que ces tests tiennent :

- la reproduction de la QA : main droite enregistrée (pincement primaire et
  secondaire, tremblement, tolérance clic/glissement, un réglage accepté),
  puis une calibration du seul pincement primaire → seuls les seuils primaires
  changent ;
- l'autre main, une étape ratée, une étape passée à la voix : gardées ;
- le rapport dit « avant → après » et « Conservé » ;
- la parité stricte du contrat (`mergeProfile`) et de la route
  (`barehands_profile.apply` avec `replaces`) ;
- l'ancien sens (sans `replaces`, profil entier) reste, et c'est celui de
  l'acceptation d'un essai.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jarvis.runtime import barehands_profile as profile  # noqa: E402
from test_barehands_calibration_js import DOM, DRIVER, run_node  # noqa: E402

#: Le profil enregistré avant la séance, sur le fil (snake_case).
SAVED_WIRE = {
    "schema_version": 3,
    "updated_at": 1_700_000_000_000,
    "hands": {
        "right": {"press_ratio": 0.2, "release_ratio": 0.4, "secondary_press_ratio": 0.22,
                  "secondary_release_ratio": 0.44, "jitter_px": 1.5, "travel_slop_norm": 0.006,
                  "quality": 0.8},
        "left": {"press_ratio": 0.25, "release_ratio": 0.45, "quality": 0.7},
    },
    "tuning": {"release_ms": 90},
    "stages": {"neutral": {"status": "ok", "reason": None, "samples": 40},
               "c_pose": {"status": "ok", "reason": None, "samples": 30},
               "pinch_primary": {"status": "ok", "reason": None, "samples": 6},
               "pinch_secondary": {"status": "ok", "reason": None, "samples": 6},
               "aim": {"status": "ok", "reason": None, "samples": 3},
               "drag": {"status": "ok", "reason": None, "samples": 1}},
}

WIRE_OF = profile.HAND_WIRE_KEYS


def to_wire(payload: dict) -> dict:
    """Ce que fait `toProfileWire` de la page : clés de main au nom du fil,
    `replaces` aussi."""

    wire = {"schema_version": payload["schemaVersion"], "updated_at": payload.get("updatedAt"),
            "hands": {h: {WIRE_OF.get(k, k): v for k, v in hand.items()} for h, hand in payload["hands"].items()},
            "stages": payload["stages"]}
    if "tuning" in payload:
        wire["tuning"] = payload["tuning"]
    if "replaces" in payload:
        extra = {k: v for k, v in payload["replaces"].items() if k not in ("hands", "stages")}
        wire["replaces"] = {**extra, "hands": {h: [WIRE_OF.get(k, k) for k in keys]
                                      for h, keys in payload["replaces"].get("hands", {}).items()},
                            "stages": payload["replaces"].get("stages", [])}
    return wire


def saved_settings() -> dict:
    settings: dict = {}
    profile.apply(settings, json.loads(json.dumps(SAVED_WIRE)))
    return settings


#: Le profil enregistré, dans la forme du contrat, pour la page.
SAVED_JS = r"""
const SAVED={schemaVersion:3,updatedAt:1700000000000,
  hands:{right:{pressRatio:.2,releaseRatio:.4,secondaryPressRatio:.22,secondaryReleaseRatio:.44,jitterPx:1.5,
    travelSlopNorm:.006,quality:.8},left:{pressRatio:.25,releaseRatio:.45,quality:.7}},
  tuning:{releaseMs:90},
  stages:{neutral:{status:'ok',reason:null,samples:40},c_pose:{status:'ok',reason:null,samples:30},
    pinch_primary:{status:'ok',reason:null,samples:6},pinch_secondary:{status:'ok',reason:null,samples:6},
    aim:{status:'ok',reason:null,samples:3},drag:{status:'ok',reason:null,samples:1}}};
const right=f=>i=>Object.assign(f(i),{handedness:'right'});
"""


def test_calibrating_only_the_primary_pinch_changes_only_the_primary_thresholds(tmp_path):
    """La reproduction de la QA, sur une **vraie** séance : repos passé au
    bouton, posture en C ratée, pincement primaire réussi (main droite), tout
    le reste passé **à la voix**. Enregistrer ne change que les seuils
    primaires de la main droite (et sa qualité de séance) ; le secondaire, le
    tremblement, la tolérance, le réglage accepté, la main gauche et l'état des
    étapes passées ou ratées restent."""

    result = run_node(tmp_path, DOM + DRIVER + SAVED_JS + """
      const cal=calOf({savedProfile:()=>SAVED});
      cal.start();
      skipStep(cal);                                         // repos : passé au bouton
      const cFailed=feedUntil(cal,right(()=>({cPose:0,gapPalms:.65,indexReachPalms:1.8,secondaryRatio:.2})));
      const primary=feedUntil(cal,right(pinching('primaryRatio')));
      const voice=[];
      for(let i=0;i<20&&!cal.concluded();i+=1)voice.push(cal.next('not_relevant').decision);
      const r=cal.result();
      const willSave=deep(flowRoot()).filter(n=>n.getAttribute&&n.getAttribute('data-will-save')==='1')
        .flatMap(n=>n.children.map(c=>c.textContent));
      const kept=deep(flowRoot()).filter(n=>n.getAttribute&&n.getAttribute('data-kept-values')==='1')
        .flatMap(n=>n.children.map(c=>c.textContent));
      const note=text(flowRoot(),C.DOM.flowNoteClass)[0];
      press(flowRoot(),'apply');
      await new Promise(r=>setImmediate(r));
      out({cStatus:cFailed.review&&cFailed.review.status,primary:primary.review&&primary.review.status,voice,
        payload:r.payload,merged:r.profile,willSave,kept,note,sent:saved[0]||null});
    """, name="qarepro")

    assert result["cStatus"] == "failed" and result["primary"] == "ok"
    assert set(result["voice"]) == {"skipped"}
    payload = result["payload"]
    assert payload["replaces"] == {"hands": {"right": ["pressRatio", "releaseRatio", "quality"]},
                                   "stages": ["pinch_primary"]}
    assert result["sent"] == payload, "ce qui part est ce que le rapport a dérivé"

    settings = saved_settings()
    written = profile.apply(settings, to_wire(payload))
    before = SAVED_WIRE["hands"]["right"]
    right = written["hands"]["right"]
    assert right["press_ratio"] != before["press_ratio"] and right["release_ratio"] != before["release_ratio"]
    assert right["press_ratio"] < right["release_ratio"]
    for key in ("secondary_press_ratio", "secondary_release_ratio", "jitter_px", "travel_slop_norm"):
        assert right[key] == before[key], key
    # L'autre main : intacte.
    assert written["hands"]["left"]["press_ratio"] == 0.25 and written["hands"]["left"]["quality"] == 0.7
    # Le réglage accepté : gardé (la charge utile de la calibration n'en porte pas).
    assert written["tuning"]["release_ms"] == 90
    # Les étapes : seule celle qui a réussi change ; la ratée (c_pose), la
    # passée au bouton (neutral) et les passées à la voix gardent leur état.
    assert written["stages"]["pinch_primary"]["status"] == "ok"
    for stage in ("neutral", "c_pose", "pinch_secondary", "aim", "drag"):
        assert written["stages"][stage] == SAVED_WIRE["stages"][stage], stage
    # Le contrat rend exactement le même profil que la route.
    merged = result["merged"]
    assert merged["hands"]["right"]["pressRatio"] == right["press_ratio"]
    assert merged["hands"]["right"]["secondaryPressRatio"] == 0.22
    # Le rapport dit ce qui change (avant → après) et ce qui reste.
    assert len(result["willSave"]) == 2
    assert all("→" in line and "main droite" in line for line in result["willSave"])
    assert any(line.startswith("seuil d’appui du pincement pouce-index (main droite) : 0,20 →")
               for line in result["willSave"])
    assert any("pouce-majeur (main droite) : 0,22" in line for line in result["kept"])
    assert any("tolérance entre clic et glissement (main droite)" in line for line in result["kept"])
    assert any("main gauche" in line for line in result["kept"])
    assert "le reste de votre profil est gardé" in result["note"]


def test_a_session_that_measured_nothing_offers_no_save_and_sends_nothing(tmp_path):
    """Rien de calibrant mesuré : pas d'« Enregistrer », rien d'envoyé, le
    profil fusionné est le profil d'avant."""

    result = run_node(tmp_path, DOM + DRIVER + SAVED_JS + """
      const cal=calOf({savedProfile:()=>SAVED});
      cal.start();
      for(let i=0;i<20&&!cal.concluded();i+=1)cal.next('later');
      const r=cal.result();
      out({actions:stepActions(flowRoot()),payload:r.payload,measured:r.measuredCount,
        same:r.profile.hands.right.pressRatio===.2&&r.profile.stages.neutral.status==='ok',saved:saved.length});
    """, name="nothing")

    assert result["actions"] == ["discard"]
    assert result["measured"] == 0 and result["saved"] == 0
    assert result["payload"]["replaces"] == {"hands": {}, "stages": []}
    assert result["same"] is True


PARITY = [
    ("valid", {"hands": {"right": {"pressRatio": 0.3, "releaseRatio": 0.5}},
               "stages": {"pinch_primary": {"status": "ok", "reason": None, "samples": 4}},
               "replaces": {"hands": {"right": ["pressRatio", "releaseRatio"]}, "stages": ["pinch_primary"]}}),
    ("stage_only", {"hands": {}, "stages": {"c_pose": {"status": "ok", "reason": None, "samples": 9}},
                    "replaces": {"hands": {}, "stages": ["c_pose"]}}),
    ("unannounced_value", {"hands": {"right": {"pressRatio": 0.3, "releaseRatio": 0.5, "jitterPx": 2}},
                           "stages": {}, "replaces": {"hands": {"right": ["pressRatio", "releaseRatio"]}}}),
    ("announced_without_value", {"hands": {"right": {"pressRatio": 0.3}}, "stages": {},
                                 "replaces": {"hands": {"right": ["jitterPx"]}}}),
    ("half_pair", {"hands": {"right": {"pressRatio": 0.3}}, "stages": {},
                   "replaces": {"hands": {"right": ["pressRatio"]}}}),
    ("unknown_key", {"hands": {}, "stages": {}, "replaces": {"hands": {"right": ["bogus"]}}}),
    ("unknown_field", {"hands": {}, "stages": {}, "replaces": {"hands": {}, "mode": "all"}}),
    ("duplicate", {"hands": {"right": {"jitterPx": 2}}, "stages": {},
                   "replaces": {"hands": {"right": ["jitterPx", "jitterPx"]}}}),
    ("empty", {"hands": {}, "stages": {}, "replaces": {"hands": {}, "stages": []}}),
    ("stages_differ", {"hands": {}, "stages": {"aim": {"status": "ok", "reason": None, "samples": 3}},
                       "replaces": {"stages": ["c_pose"]}}),
    ("unknown_stage", {"hands": {}, "stages": {}, "replaces": {"stages": ["dance"]}}),
    ("inverted_pair", {"hands": {"right": {"pressRatio": 0.5, "releaseRatio": 0.3}}, "stages": {},
                       "replaces": {"hands": {"right": ["pressRatio", "releaseRatio"]}}}),
]


def test_the_contract_and_the_route_merge_the_same_way(tmp_path):
    """Parité : pour chaque cas, même refus (même code) ou même profil
    fusionné, côté contrat (`mergeProfile`) et côté route (`apply`)."""

    cases = json.dumps([[name, {"schemaVersion": 3, "updatedAt": 1_800_000_000_000, **payload}]
                        for name, payload in PARITY])
    js = run_node(tmp_path, SAVED_JS + f"""
      const out2=[];
      for(const [name,payload] of {cases}){{
        try{{const m=C.mergeProfile(SAVED,payload);
          out2.push([name,null,{{hands:m.hands,stages:m.stages,tuning:m.tuning.releaseMs,calibrated:m.calibrated}}])}}
        catch(e){{out2.push([name,e.code||String(e),null])}}
      }}
      out(out2);
    """, name="parity")
    for name, code, merged in js:
        payload = dict(PARITY)[name]
        wire = to_wire({"schemaVersion": 3, "updatedAt": 1_800_000_000_000, **payload})
        settings = saved_settings()
        try:
            written = profile.apply(settings, wire)
            py_code = None
        except profile.BarehandsProfileError as exc:
            written, py_code = None, exc.code
        assert py_code == code, (name, py_code, code)
        if written is None:
            continue
        assert written["calibrated"] == merged["calibrated"], name
        assert written["tuning"]["release_ms"] == merged["tuning"], name
        for handedness, hand in merged["hands"].items():
            for js_key, value in hand.items():
                assert written["hands"][handedness][WIRE_OF[js_key]] == value, (name, handedness, js_key)
        assert written["stages"] == merged["stages"], name
    codes = {name: code for name, code, _ in js}
    assert codes["valid"] is None and codes["stage_only"] is None
    assert codes["unannounced_value"] == "barehands_profile_replaces_mismatch"
    assert codes["announced_without_value"] == "barehands_profile_replaces_mismatch"
    assert codes["half_pair"] == "barehands_profile_thresholds_incomplete"
    assert codes["unknown_key"] == "barehands_profile_replaces_invalid"
    assert codes["unknown_field"] == "barehands_profile_replaces_invalid"
    assert codes["duplicate"] == "barehands_profile_replaces_invalid"
    assert codes["empty"] == "barehands_profile_replaces_empty"
    assert codes["stages_differ"] == "barehands_profile_replaces_mismatch"
    assert codes["unknown_stage"] == "barehands_profile_replaces_invalid"
    assert codes["inverted_pair"] == "barehands_profile_thresholds_invalid"


def test_without_replaces_a_write_still_replaces_the_whole_profile():
    """L'ancien sens reste, documenté : sans `replaces`, le profil est remplacé
    en entier — c'est l'acceptation d'un essai, qui envoie un profil complet."""

    settings = saved_settings()
    written = profile.apply(settings, {"schema_version": 3, "hands": {"right": {"jitter_px": 3.0}}})
    assert written["hands"]["right"]["press_ratio"] is None
    assert written["hands"]["left"]["press_ratio"] is None
    assert written["hands"]["right"]["jitter_px"] == 3.0


def test_a_merged_write_refused_writes_nothing():
    settings = saved_settings()
    before = json.dumps(settings, sort_keys=True)
    with pytest.raises(profile.BarehandsProfileError):
        profile.apply(settings, {"schema_version": 3, "hands": {"right": {"press_ratio": 0.3}},
                                 "replaces": {"hands": {"right": ["press_ratio"]}}})
    assert json.dumps(settings, sort_keys=True) == before
