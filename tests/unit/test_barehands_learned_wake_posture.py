"""La posture de réveil **apprise sur la main de l'utilisateur** (30/09/2026).

Retour utilisateur, pendant l'étape « Posture de réveil » de la calibration :
« c'est pas à moi de me conformer à la posture de réveil […] c'est moi qui te
montre ce que je fais pour réveiller le truc […] c'est ça qu'il faut
retrouver ». Son C naturel — écart pouce-index 0,511 paume, index « pas assez
déplié », trois autres doigts à 1,817 paume — échouait contre le C d'usine, et
aucun réglage de seuil ne l'atteignait sans ouvrir le réveil aux mains
ouvertes.

Ce que l'utilisateur doit constater, et ce que ce fichier mesure :

1. l'étape relève **sa** posture et la retient (au lieu de lui demander de
   replier les doigts) ;
2. ensuite, sa posture réveille la veille en une seconde et fait apparaître le
   viseur ;
3. sa main au repos, les mains ouvertes, les poings et les pincements des
   dix-sept vraies mains photographiées ne réveillent rien ;
4. la posture relevée traverse l'enregistrement du profil (page et serveur)
   sans image ni point de main (décision 32).

La main de l'utilisateur est reconstruite depuis une **vraie** main passée au
vrai MediaPipe (`tests/fixtures/barehands_learned_wake_proof.cjs`) ; le même
script, lancé contre les modules d'avant le correctif, rend l'échec vécu
(étape refusée, aucun réveil, rien à relever).
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.runtime import barehands_profile as profile

ROOT = Path(__file__).resolve().parents[2]
PROOF = ROOT / "tests" / "fixtures" / "barehands_learned_wake_proof.cjs"
RUNTIME = ROOT / "jarvis" / "runtime"


def node_or_skip() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    return node


def run_proof() -> dict:
    done = subprocess.run([node_or_skip(), str(PROOF), str(ROOT)], capture_output=True, text=True,
                          encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def run_node(tmp_path: Path, source: str) -> dict:
    script = tmp_path / "learned-wake.cjs"
    script.write_text(
        f"const C=require({json.dumps(str(RUNTIME / 'control_center_barehands_adaptive.js'))});\n"
        "global.JarvisBarehandsContracts=C;\n"
        f"const B=require({json.dumps(str(RUNTIME / 'control_center_barehands.js'))});\n"
        f"const K=require({json.dumps(str(RUNTIME / 'control_center_barehands_calibration.js'))});\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "const refused=fn=>{try{fn();return null}catch(e){return e.code||e.name||String(e)}};\n"
        + source,
        encoding="utf-8",
    )
    done = subprocess.run([node_or_skip(), str(script)], capture_output=True, text=True,
                          encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_users_own_posture_is_recorded_and_then_wakes_without_waking_on_anything_else():
    report = run_proof()
    factory = report["factory"]
    # La main reconstruite est bien la sienne : les trois nombres de sa séance.
    assert abs(factory["measured"]["gap"] - 0.511) < 0.02
    assert factory["measured"]["index"] < 1.485, "index « pas assez déplié » pour le C d'usine"
    assert abs(factory["measured"]["fold"] - 1.817) < 0.01, "trois autres doigts « trop dépliés »"
    # L'échec vécu, que le C d'usine rend toujours (rien ne l'a assoupli).
    assert factory["step"]["ok"] is False
    assert factory["wakesAfter3s"] is False

    learned = report["learned"]
    assert learned is not None, "la calibration ne sait pas relever une posture"
    assert learned["ok"] is True, learned
    assert learned["restShare"] == 0, "sa main au repos n'atteint pas la posture relevée"
    # Sa posture réveille, au bout du maintien d'usine, et montre le viseur.
    assert learned["userWakesWithin"] is not None and learned["userWakesWithin"] <= 1200
    assert learned["userPointing"] >= 0.5
    # Rien d'autre ne réveille : sa main au repos, ni aucune des 17 vraies mains.
    assert learned["restWakes"] is False
    woke = [o["photo"] for o in learned["others"] if o["wakes"]]
    assert woke == [], f"réveils intempestifs : {woke}"
    shown = [o["photo"] for o in learned["others"] if o["pointing"] >= 0.5]
    assert shown == [], f"viseur montré sans visée : {shown}"
    # Et un pincement de sa main, depuis cette posture, ne réveille pas.
    assert learned["pinchGap"] < 0.28
    assert learned["pinchWakes"] is False


def test_a_posture_the_resting_hand_already_reaches_is_refused_with_its_reason(tmp_path):
    result = run_node(tmp_path, """
      const doc=require(%s);
      const open=doc.hands.find(h=>h.photo==='open_palm_03.jpg');
      const pub=h=>({stillness:.9,quality:.9,gapPalms:.6,secondaryRatio:.9,
        ...B.wakeSignatureFields(h.landmarks,h.aspect)});
      const frames=Array.from({length:30},()=>pub(open));
      const band=K.wakeBandOf(B.DEFAULTS),o=K.options({});
      const rest=K.deriveWakePosture(frames,frames,band,o);
      // Un pincement montré comme « posture » : c'est un clic, pas un réveil.
      const pinch=doc.hands.find(h=>h.photo==='pinch_01.jpg');
      const clicked=K.deriveWakePosture(Array.from({length:30},()=>pub(pinch)),[],band,o);
      out({rest:{ok:rest.ok,cause:rest.cause},clicked:{ok:clicked.ok,cause:clicked.cause}});
    """ % json.dumps(str(ROOT / "tests" / "fixtures" / "barehands_real_hands.v1.json")))
    assert result["rest"] == {"ok": False, "cause": "rest"}
    assert result["clicked"] == {"ok": False, "cause": "pinch"}


def test_the_learned_posture_survives_the_page_contract_and_carries_no_image(tmp_path):
    result = run_node(tmp_path, """
      const posture={gap:.51,index:1.47,middle:1.82,ring:1.75,pinky:1.55,indexMiddle:.7,tolerance:.15};
      const merged=C.mergeProfile(null,{schemaVersion:C.PROFILE_SCHEMA_VERSION,updatedAt:1,hands:{},stages:{
        c_pose:{status:'ok',reason:null,samples:30}},replaces:{stages:['c_pose'],wakePosture:true},wakePosture:posture});
      const kept=C.mergeProfile(merged,{schemaVersion:C.PROFILE_SCHEMA_VERSION,updatedAt:2,hands:{},stages:{
        neutral:{status:'ok',reason:null,samples:30}},replaces:{stages:['neutral']}});
      out({merged:merged.wakePosture,calibrated:merged.calibrated,kept:kept.wakePosture,
        undeclared:refused(()=>C.mergeProfile(null,{schemaVersion:3,stages:{c_pose:{status:'ok',samples:1}},
          replaces:{stages:['c_pose']},wakePosture:posture})),
        leak:C.normalizeProfile({schemaVersion:3,wakePosture:{...posture,image:'data:image/png;base64,AAAA'}}).wakePosture,
        list:C.normalizeProfile({schemaVersion:3,wakePosture:[posture]}).wakePosture,
        engine:B.composeEffective({contracts:C,profile:C.normalizeProfile({schemaVersion:3,wakePosture:posture})}).engine.wakeTemplate,
        session:B.composeEffective({contracts:C,profile:null,session:{wakePosture:posture}}).engine.wakeTemplate,
        none:B.composeEffective({contracts:C,profile:null}).engine.wakeTemplate,
        badTemplate:refused(()=>B.wakePostureScore([],1,{wakeTemplate:{gap:1}}))});
    """)
    assert result["merged"]["tolerance"] == 0.15 and result["calibrated"] is True
    assert result["kept"] == result["merged"], "une calibration qui ne relève rien la garde"
    assert result["undeclared"] == "barehands_profile_replaces_mismatch"
    # Décision 32 : ni texte libre ni liste n'y entrent — la posture ne se relit
    # que comme sept nombres, ou pas du tout.
    assert set(result["leak"]) == {"gap", "index", "middle", "ring", "pinky", "indexMiddle", "tolerance"}
    assert result["list"] is None
    assert result["engine"]["gap"] == 0.51 and result["session"]["gap"] == 0.51
    assert result["none"] is None
    assert result["badTemplate"] == "RangeError"


def test_the_server_stores_the_learned_posture_merges_it_and_refuses_anything_else():
    posture = {"gap": 0.51, "index": 1.47, "middle": 1.82, "ring": 1.75, "pinky": 1.55,
               "index_middle": 0.7, "tolerance": 0.15}
    settings: dict = {}
    saved = profile.apply(settings, {
        "schema_version": 3, "updated_at": 1, "hands": {},
        "stages": {"c_pose": {"status": "ok", "reason": None, "samples": 30}},
        "replaces": {"stages": ["c_pose"], "wake_posture": True}, "wake_posture": posture})
    assert saved["wake_posture"] == posture and saved["calibrated"] is True
    # Une calibration suivante qui ne la relève pas la garde.
    kept = profile.apply(settings, {
        "schema_version": 3, "updated_at": 2, "hands": {},
        "stages": {"neutral": {"status": "ok", "reason": None, "samples": 30}},
        "replaces": {"stages": ["neutral"]}, "wake_posture": None})
    assert kept["wake_posture"] == posture
    assert profile.load(settings)["wake_posture"] == posture
    with pytest.raises(profile.BarehandsProfileError) as leak:
        profile.apply({}, {"schema_version": 3, "wake_posture": {**posture, "photo": "data:image/png;base64,AA"}})
    assert leak.value.code == "barehands_profile_not_derived"
    with pytest.raises(profile.BarehandsProfileError) as wide:
        profile.apply({}, {"schema_version": 3, "wake_posture": {**posture, "tolerance": 0.9}})
    assert wide.value.code == "barehands_profile_out_of_range"
    with pytest.raises(profile.BarehandsProfileError) as silent:
        profile.apply({}, {"schema_version": 3, "hands": {}, "stages": {},
                           "replaces": {"stages": [], "wake_posture": True}})
    assert silent.value.code == "barehands_profile_replaces_mismatch"


def test_server_and_page_bound_the_learned_posture_identically(tmp_path):
    result = run_node(tmp_path, "out({bounds:C.WAKE_POSTURE_BOUNDS,wire:C.WAKE_POSTURE_WIRE_KEYS});")
    page = {result["wire"][key]: tuple(bounds) for key, bounds in result["bounds"].items()}
    assert page == profile.WAKE_POSTURE_BOUNDS
