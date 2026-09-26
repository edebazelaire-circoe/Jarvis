"""Bare Hands — balayage des migrations et dépréciations (tâche adaptative, Slice 10).

Ce que la clôture de la tâche doit pouvoir affirmer, vérifié sur les vrais
modules (contrat étendu sous node, miroirs Python) :

- **profil** : v1, v2 et v3 se lisent en v3, sans perte, côté page et côté
  serveur ; un profil d'une version inconnue est archivé, jamais écrasé ;
  l'enregistrement fusionné (décision 69) sur un profil migré ne remplace que
  ce qui est annoncé ;
- **« pas de lecteur, pas de calibration »** (décision 39) : chaque clé qui
  lève le drapeau « calibré » change le moteur effectif, et aucune métrique
  (`jitterPx`, `reachNorm`, `quality`) ne le change ni ne lève le drapeau ;
- **vocabulaire** : l'alias déprécié `barehands_tutorial` existe toujours,
  déprécié partout ; `barehands_test` est présent partout ; les listes
  d'étapes JS, Python (profil, domaine) et parcours sont les mêmes.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.domain import barehands_calibration as domain
from jarvis.domain import barehands_command as vocab
from jarvis.runtime import barehands_mcp, barehands_profile as profile, mcp_tool_meta

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
ADAPTIVE = RUNTIME / "control_center_barehands_adaptive.js"
CORE = RUNTIME / "control_center_barehands.js"
CALIBRATION = RUNTIME / "control_center_barehands_calibration.js"
COMMANDS = RUNTIME / "control_center_barehands_commands.js"


def run_node(tmp_path: Path, source: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "barehands-migration.cjs"
    script.write_text(
        f"const C=require({json.dumps(str(ADAPTIVE))});\n"
        f"const Core=require({json.dumps(str(CORE))});\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "const refused=fn=>{try{fn();return null}catch(e){return e.code||String(e)}};\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8",
                          timeout=30, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


HAND = {"pressRatio": 0.22, "releaseRatio": 0.36, "secondaryPressRatio": 0.24,
        "secondaryReleaseRatio": 0.38, "jitterPx": 2.5, "travelSlopNorm": 0.006,
        "reachNorm": {"x": 0.1, "y": 0.1, "w": 0.6, "h": 0.6}, "quality": 0.8}


def test_every_profile_version_reads_as_v3_without_loss_in_the_page(tmp_path):
    result = run_node(tmp_path, f"""
      const hand={json.dumps(HAND)};
      const read=v=>C.normalizeProfile({{schemaVersion:v,updatedAt:7,hands:{{right:hand}},
        stages:{{neutral:{{status:'ok',samples:5}}}}}});
      out({{v1:read(1),v2:read(2),v3:read(3),migrated:C.PROFILE_MIGRATED_VERSIONS,current:C.PROFILE_SCHEMA_VERSION,
        v4:refused(()=>read(4)),settings:[C.SETTINGS_SCHEMA_VERSION,C.SETTINGS_MIGRATED_VERSIONS],
        settingsV1:C.normalizeSettings({{schemaVersion:1,assistance:.7}}).assistance}});
    """)
    assert result["current"] == profile.SCHEMA_VERSION == 3
    assert result["migrated"] == list(profile.MIGRATED_SCHEMA_VERSIONS) == [1, 2]
    for version in ("v1", "v2", "v3"):
        read = result[version]
        assert read["schemaVersion"] == 3, version
        right = read["hands"]["right"]
        for key, value in HAND.items():
            assert right[key] == value, (version, key)
        assert read["calibrated"] is True and read["stages"]["neutral"]["status"] == "ok", version
        assert all(v is None for v in read["tuning"].values()), version
    assert result["v4"] == "barehands_schema_version_unsupported"
    assert result["settings"][0] == 2 and 1 in result["settings"][1]
    assert result["settingsV1"] == 0.7


def test_every_profile_version_loads_on_the_server_and_a_newer_one_is_archived():
    wire = {"press_ratio": 0.22, "release_ratio": 0.36, "jitter_px": 2.5, "travel_slop_norm": 0.006}
    for version in (1, 2, 3):
        loaded = profile.load({profile.SETTING_KEY: {"schema_version": version, "hands": {"left": wire}}})
        assert loaded["schema_version"] == 3, version
        for key, value in wire.items():
            assert loaded["hands"]["left"][key] == value, (version, key)
        assert loaded["calibrated"] is True, version
    settings = {profile.SETTING_KEY: {"schema_version": 9, "hands": {"left": wire}}}
    archived = profile.archive_unreadable(settings)
    assert archived and archived in profile.archived_keys(settings), "un profil plus récent est rangé, pas écrasé"


def test_a_merge_save_over_a_migrated_v2_profile_replaces_only_what_it_announces():
    settings = {profile.SETTING_KEY: {"schema_version": 2, "hands": {
        "left": {"press_ratio": 0.22, "release_ratio": 0.36, "jitter_px": 2.5},
        "right": {"press_ratio": 0.25, "release_ratio": 0.4}}}}
    saved = profile.apply(settings, {
        "schema_version": 3,
        "hands": {"left": {"press_ratio": 0.2, "release_ratio": 0.34}},
        "stages": {"pinch_primary": {"status": "ok", "samples": 4}},
        "replaces": {"hands": {"left": ["press_ratio", "release_ratio"]}, "stages": ["pinch_primary"]},
    })
    assert saved["schema_version"] == 3
    assert saved["hands"]["left"]["press_ratio"] == 0.2 and saved["hands"]["left"]["jitter_px"] == 2.5
    assert saved["hands"]["right"]["press_ratio"] == 0.25, "l'autre main est gardée"


def test_only_keys_with_a_runtime_reader_calibrate_and_every_one_of_them_changes_the_engine(tmp_path):
    """Décision 39, balayée clé par clé sur le vrai chemin effectif
    (`Core.composeEffective`, celui que la page pousse au moteur)."""

    result = run_node(tmp_path, f"""
      const hand={json.dumps(HAND)};
      const base={{schemaVersion:3,hands:{{left:{{pressRatio:.2,releaseRatio:.34,
        secondaryPressRatio:.2,secondaryReleaseRatio:.34}}}}}};
      const eff=p=>JSON.stringify(Core.composeEffective({{contracts:C,settings:C.SETTINGS_DEFAULTS,
        profile:C.normalizeProfile(p),viewportWidth:1440}}).layers.effective);
      const ref=eff(base);
      const moved={{}},flags={{}};
      for(const key of [...C.PROFILE_CALIBRATING_KEYS,...C.PROFILE_METRIC_KEYS]){{
        const p=JSON.parse(JSON.stringify(base));p.hands.left[key]=hand[key];
        if(key==='releaseRatio')p.hands.left.releaseRatio=.3;
        if(key==='secondaryReleaseRatio')p.hands.left.secondaryReleaseRatio=.3;
        moved[key]=eff(p)!==ref;
        const alone={{schemaVersion:3,hands:{{left:{{[key]:p.hands.left[key]}}}}}};
        if(/Ratio$/.test(key)){{const pair=key.replace('Press','Release').replace('press','release');
          const low=key.replace('Release','Press').replace('release','press');
          alone.hands.left={{[low]:.2,[pair]:.34}}}}
        flags[key]=C.normalizeProfile(alone).calibrated;
      }}
      out({{calibrating:C.PROFILE_CALIBRATING_KEYS,metrics:C.PROFILE_METRIC_KEYS,moved,flags}});
    """)
    assert set(result["calibrating"]).isdisjoint(result["metrics"])
    assert set(result["metrics"]) == {"jitterPx", "reachNorm", "quality"}
    for key in result["calibrating"]:
        assert result["moved"][key] is True, f"{key} lève « calibré » mais aucun lecteur ne le lit"
        assert result["flags"][key] is True, key
    for key in result["metrics"]:
        assert result["moved"][key] is False, f"{key} change le moteur : ce n'est plus une métrique"
        assert result["flags"][key] is False, f"{key} lève « calibré » sans lecteur"
    assert profile.METRIC_KEYS == ("jitter_px", "reach_norm", "quality")


def test_the_command_vocabulary_keeps_the_deprecated_alias_and_lists_the_tester_everywhere():
    assert "tutorial" in vocab.COMMANDS and "test" in vocab.COMMANDS
    assert barehands_mcp.TOOL_COMMANDS["barehands_tutorial"] == "tutorial"
    assert barehands_mcp.TOOL_COMMANDS["barehands_test"] == "test"
    meta = mcp_tool_meta.BAREHANDS.tools
    assert meta["barehands_tutorial"].deprecation is not None
    assert meta["barehands_tutorial"].deprecation.replacement == "barehands_calibrate"
    assert meta["barehands_test"].deprecation is None
    assert tuple(barehands_mcp.TOOL_COMMANDS) + barehands_mcp.CALIBRATION_TOOLS == barehands_mcp.TOOL_NAMES
    source = COMMANDS.read_text(encoding="utf-8")
    assert "tutorial:Object.freeze({method:'tutorial',targets:null})" in source
    assert "test:Object.freeze({method:'benchmark',targets:null})" in source


def test_the_stage_lists_agree_everywhere(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "stages.cjs"
    script.write_text(
        f"global.JarvisBarehandsContracts=require({json.dumps(str(ADAPTIVE))});\n"
        f"const K=require({json.dumps(str(CALIBRATION))});\n"
        "const C=global.JarvisBarehandsContracts;\n"
        "process.stdout.write(JSON.stringify({stages:C.STAGES,flow:K.STEPS.reduce((l,s)=>"
        "l.concat(s.subs?s.subs.map(x=>x.id):[s.id]),[])}));",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8",
                          timeout=30, check=False)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert result["stages"] == result["flow"] == list(profile.STAGES) == list(domain.STAGES)
