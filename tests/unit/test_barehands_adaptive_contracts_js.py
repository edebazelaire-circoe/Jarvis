"""Contrats de la calibration adaptative et du banc d'essai (§ 12 du contrat, § 17 du doc).

Tâche `jarvis-bare-hands-adaptive-calibration-benchmark`, Slice 01. Aucune
conduite ne change : ce qui est vérifié ici est ce que chaque forme **refuse**
(clé hors schéma, valeur recopiée, point de main, image, référence d'une autre
nature) et ce que chaque table **promet** (un lecteur moteur par clé d'essai,
des bornes dans celles du rangement, des invariants que le moteur accepte).
Exécuté par node sur les vrais modules, comme `test_barehands_contracts_js`.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.runtime import barehands_profile
from jarvis.runtime import settings_mcp

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
CONTRACTS = RUNTIME / "control_center_barehands_contracts.js"
#: Le contrat étendu du § 12 (Slice 10) : tous les noms du contrat, plus la
#: calibration adaptative et le banc — ce que lisent les modules de page.
ADAPTIVE = RUNTIME / "control_center_barehands_adaptive.js"
RECORDER = RUNTIME / "control_center_barehands_recorder.js"
BAREHANDS = RUNTIME / "control_center_barehands.js"
DOC = ROOT / "docs" / "barehands-contracts.md"


def run_node(tmp_path: Path, source: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "barehands-adaptive.cjs"
    script.write_text(
        f"const C=require({json.dumps(str(ADAPTIVE))});\n"
        f"const R=require({json.dumps(str(RECORDER))});\n"
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
    assert "recorder_not_installed" not in completed.stderr, completed.stderr
    return json.loads(completed.stdout)


# ------------------------------------------------------------ paramètres d'essai


def test_every_trial_key_names_its_unit_bounds_and_engine_reader(tmp_path):
    """Décision 39 : une clé d'essai a des bornes, une unité et un lecteur — ou
    `reader: null`, et alors elle n'est ni annoncée ni acceptée (READINESS D4)."""

    result = run_node(tmp_path, "out({keys:C.TRIAL_KEYS,advertised:C.TRIAL_ADVERTISED_KEYS})")
    core_source = BAREHANDS.read_text(encoding="utf-8")
    assert set(result["advertised"]) == {k for k, v in result["keys"].items() if v["reader"] is not None}
    unwired = sorted(set(result["keys"]) - set(result["advertised"]))
    assert unwired == ["jitterPx"]
    for key, spec in result["keys"].items():
        assert spec["min"] < spec["max"] and spec["step"] > 0, key
        assert spec["unit"] and spec["family"], key
        if spec["reader"] is None:
            continue
        # Le lecteur nommé existe vraiment dans le moteur.
        names = re.findall(r"\b(create[A-Z]\w+|bandFor)\b", spec["reader"])
        assert names, key
        for name in names:
            assert re.search(rf"function {name}\(", core_source), (key, name)


def test_trial_defaults_are_the_engine_defaults_and_the_engine_accepts_both_extremes(tmp_path):
    """Recopie tenue par parité (le bloc pur se charge seul), et les bornes ne
    sortent pas de ce que `options()` accepte : les minima ensemble et les
    maxima ensemble respectent les invariants de paire, donc le moteur se
    construit aux deux extrémités."""

    result = run_node(tmp_path, """
      const engine=Object.keys(C.TRIAL_KEYS).filter(k=>k in Core.DEFAULTS);
      const pick=side=>Object.fromEntries(engine.map(k=>[k,C.TRIAL_KEYS[k][side]]));
      const build=o=>refused(()=>{
        Core.createPinchChannel('primary',o);Core.createPointerFilter(o);Core.createStillness(o);
        Core.createWakeDetector(o);Core.createTargetResolver({...o,pickRegion:C.pickRegion});
        Core.createPointingIntent(o);
      });
      out({
        engine,
        mismatched:engine.filter(k=>C.TRIAL_KEYS[k].default!==Core.DEFAULTS[k]),
        secondary:[C.TRIAL_KEYS.secondaryPressRatio.default===Core.DEFAULTS.pressRatio,
          C.TRIAL_KEYS.secondaryReleaseRatio.default===Core.DEFAULTS.releaseRatio],
        assistance:C.TRIAL_KEYS.assistance.default===C.SETTINGS_DEFAULTS.assistance,
        atMin:build(pick('min')),atMax:build(pick('max')),
      });
    """)
    assert len(result["engine"]) >= 18
    assert result["mismatched"] == []
    assert result["secondary"] == [True, True] and result["assistance"] is True
    assert result["atMin"] is None, result["atMin"]
    assert result["atMax"] is None, result["atMax"]


def test_trial_values_that_would_be_persisted_fit_inside_the_stores_bounds(tmp_path):
    """Une valeur acceptée se range dans le profil (bornes serveur de
    `barehands_profile.HAND_BOUNDS`) ou dans les réglages : l'essai ne peut pas
    proposer ce que le rangement refuserait."""

    result = run_node(tmp_path, "out({keys:C.TRIAL_KEYS,settings:C.SETTINGS_BOUNDS})")
    stored = {k: v for k, v in result["keys"].items() if v["store"]}
    # Slice 04 adaptative (décision 48) : le bloc `tuning` du profil v3 range
    # toute clé lue par le moteur qui n'est ni un seuil de main ni un réglage.
    assert {v["store"]["kind"] for v in stored.values()} == {"profile", "settings", "tuning"}
    for key, spec in stored.items():
        if spec["store"]["kind"] == "profile":
            wire = barehands_profile.HAND_WIRE_KEYS[spec["store"]["key"]]
            low, high = barehands_profile.HAND_BOUNDS[wire]
        elif spec["store"]["kind"] == "tuning":
            wire = "".join("_" + c.lower() if c.isupper() else c for c in spec["store"]["key"])
            low, high, _default, _integer = barehands_profile.TUNING_BOUNDS[wire]
        else:
            bound = result["settings"][spec["store"]["key"]]
            low, high = bound["min"], bound["max"]
        assert low <= spec["min"] and spec["max"] <= high, key


def test_a_trial_patch_reports_every_fault_with_a_named_code(tmp_path):
    result = run_node(tmp_path, """
      const V=C.validateTrialPatch;
      out({
        good:V({releaseMs:120,pressFrames:3}),
        many:V({pressRatio:.5,jitterPx:3,nope:1,pressFrames:2.5,releaseMs:'60'}),
        inverted:V({clickSlopPx:30}),
        invertedByBase:V({pressRatio:.35},{releaseRatio:.3}),
        fixedByPatch:V({pressRatio:.35,releaseRatio:.45},{releaseRatio:.3}),
        untouchedPairIgnored:V({releaseMs:100},{clickSlopPx:30,dragSlopPx:26}),
        empty:V({}),notObject:V([1]),wide:V({pressRatio:.2,releaseRatio:.5,pressFrames:2,releaseFrames:2,
          releaseMs:60,releaseDeltaRatio:.15,releaseDoubtMaxMs:400,clickMaxMs:400,clickStillnessMin:.5}),
        partners:[C.trialPartners('clickSlopPx'),C.trialPartners('releaseMs')],
      });
    """)
    assert result["good"] == {"ok": True, "code": None, "errors": [], "value": {"releaseMs": 120, "pressFrames": 3}}
    codes = {e["key"]: e["code"] for e in result["many"]["errors"]}
    assert result["many"]["ok"] is False and result["many"]["value"] is None
    assert codes == {
        "pressRatio": "barehands_trial_value_out_of_bounds",
        "jitterPx": "barehands_trial_key_not_wired",
        "nope": "barehands_trial_key_unknown",
        "pressFrames": "barehands_trial_value_invalid",
        "releaseMs": "barehands_trial_value_invalid",
    }
    assert result["inverted"]["code"] == "barehands_trial_invariant_violated"
    assert result["invertedByBase"]["code"] == "barehands_trial_invariant_violated"
    assert result["fixedByPatch"]["ok"] is True
    assert result["untouchedPairIgnored"]["ok"] is True
    assert result["empty"]["code"] == "barehands_trial_patch_empty"
    assert result["notObject"]["code"] == "barehands_trial_patch_invalid"
    assert result["wide"]["code"] == "barehands_trial_patch_too_wide"
    assert result["partners"] == [["dragSlopPx"], []]


# --------------------------------------------------------------- épisodes et négatifs


EPISODE = {
    "ref": "ep-1", "channel": "primary", "slot": 0, "handedness": "right", "stage": "pinch_primary",
    "startT": 1000, "endT": 1300, "closingMs": 80, "minimumMs": 60, "openingMs": 90,
    "baselineBefore": 0.8, "baselineAfter": 0.75, "minRatio": 0.12,
    "closingVelocity": 8.5, "openingVelocity": 7.0,
    "pressLatencyMs": -12, "releaseLatencyMs": 70, "travelPx": 4, "stillness": 0.9, "quality": 0.95,
    "complete": True,
}


def test_a_pinch_episode_is_a_checked_fact_not_a_free_record(tmp_path):
    result = run_node(tmp_path, f"""
      const E={json.dumps(EPISODE)};
      const make=patch=>refused(()=>C.createPinchEpisode({{...E,...patch}}));
      const ok=C.createPinchEpisode(E);
      out({{
        ok,again:refused(()=>C.createPinchEpisode(ok)),
        missed:C.createPinchEpisode({{...E,pressLatencyMs:null,releaseLatencyMs:null}}).pressLatencyMs,
        phases:C.EPISODE_PHASE_SEQUENCE,
        landmarks:make({{landmarks:[[.1,.2]]}}),
        backwards:make({{endT:900}}),
        badDuration:make({{durationMs:12}}),
        phasesTooLong:make({{closingMs:400}}),
        minAbove:make({{minRatio:.9}}),
        zeroInvented:make({{travelPx:undefined}}),
        channel:make({{channel:'middle'}}),
        ref:make({{ref:'fb-1'}}),
        latency:make({{pressLatencyMs:99999}}),
        version:make({{schemaVersion:2}}),
      }});
    """)
    assert result["ok"]["durationMs"] == 300 and result["ok"]["pressLatencyMs"] == -12
    assert result["again"] is None, "une sortie se relit : la fabrique est un point fixe"
    assert result["missed"] is None
    assert result["phases"] == ["open_baseline", "closing", "minimum", "opening", "open_baseline"]
    assert result["landmarks"] == "barehands_session_key_unknown"
    for key in ("backwards", "badDuration", "phasesTooLong", "minAbove"):
        assert result[key] == "barehands_episode_inconsistent", key
    assert result["zeroInvented"] == "barehands_episode_invalid"
    assert result["channel"] == "barehands_pinch_channel_unknown"
    assert result["ref"] == "barehands_session_ref_invalid"
    assert result["latency"] == "barehands_episode_invalid"
    assert result["version"] == "barehands_schema_version_unsupported"


def test_negative_examples_have_a_closed_vocabulary_and_point_at_their_evidence(tmp_path):
    result = run_node(tmp_path, """
      const ok=C.createFalseEvent({ref:'ng-4',falseKind:'unintended_wake',t:1200,slot:1,
        stage:'neutral',exerciseRef:'ex-2',sampleRef:'se-40'});
      out({
        kinds:C.FALSE_EVENTS,ok,
        unknown:refused(()=>C.createFalseEvent({ref:'ng-1',falseKind:'false_drag',t:1})),
        slot:refused(()=>C.createFalseEvent({ref:'ng-1',falseKind:'false_press',t:1,slot:2})),
        payload:refused(()=>C.createFalseEvent({ref:'ng-1',falseKind:'false_press',t:1,frame:{}})),
        wrongRef:refused(()=>C.createFalseEvent({ref:'ng-1',falseKind:'false_press',t:1,sampleRef:'ep-1'})),
      });
    """)
    assert result["kinds"] == ["false_press", "false_secondary_press", "unintended_wake", "unintended_target",
                              "unintended_pointer"]
    assert result["ok"]["sampleRef"] == "se-40"
    assert result["unknown"] == "barehands_false_event_unknown"
    assert result["slot"] == "barehands_slot_out_of_range"
    assert result["payload"] == "barehands_session_key_unknown"
    assert result["wrongRef"] == "barehands_session_ref_invalid"


# ------------------------------------------------------------------ retour utilisateur


def test_user_feedback_keeps_the_words_and_classifies_them_in_a_closed_taxonomy(tmp_path):
    result = run_node(tmp_path, """
      const F=patch=>refused(()=>C.createUserFeedback({ref:'fb-1',categories:['release_sticky'],
        text:'le release colle',source:'voice',t:10,...patch}));
      out({
        taxonomy:C.USER_FEEDBACKS,
        causes:C.FEEDBACK_CAUSES,
        ok:C.createUserFeedback({ref:'fb-2',categories:['laggy','hard_to_aim'],
          text:'  ça lag, je me suis repris  ',source:'voice',t:12,stage:'aim',exerciseRef:'ex-3'}),
        button:C.createUserFeedback({ref:'fb-3',categories:['fine'],source:'ui',t:14}),
        voiceNoText:F({text:''}),
        contradictory:F({categories:['fine','laggy']}),
        unknown:F({categories:['too_slow']}),
        none:F({categories:[]}),
        long:F({text:'x'.repeat(C.FEEDBACK_TEXT_MAX+1)}),
        source:F({source:'email'}),
        setting:F({pressRatio:.3}),
      });
    """)
    assert result["taxonomy"] == [
        "fine", "press_missed", "false_click", "release_sticky", "release_early",
        "drag_starts_too_early", "drag_hard_to_start", "hard_to_aim", "wrong_target",
        "jumpy_pointer", "laggy", "pointer_unwanted", "wake_hard", "unclear",
    ]
    assert set(result["causes"]) == set(result["taxonomy"])
    assert result["ok"]["text"] == "ça lag, je me suis repris"
    assert result["ok"]["categories"] == ["laggy", "hard_to_aim"]
    assert result["button"]["text"] == "" and result["button"]["source"] == "ui"
    assert result["voiceNoText"] == "barehands_feedback_invalid"
    assert result["contradictory"] == "barehands_feedback_contradictory"
    assert result["unknown"] == "barehands_feedback_category_unknown"
    assert result["none"] == "barehands_feedback_invalid"
    assert result["long"] == "barehands_feedback_text_too_long"
    assert result["source"] == "barehands_feedback_source_unknown"
    assert result["setting"] == "barehands_session_key_unknown", "un retour n'est jamais un réglage"


# ------------------------------------------------- preuve, hypothèse, issue d'essai


def test_evidence_cites_measurements_and_never_carries_a_value(tmp_path):
    result = run_node(tmp_path, """
      const V=patch=>refused(()=>C.createEvidence({ref:'ev-1',metric:'release_latency_ms',aggregate:'p95',
        sourceRefs:['ep-1','ep-2'],...patch}));
      out({
        ok:C.createEvidence({ref:'ev-1',metric:'release_latency_ms',aggregate:'p95',sourceRefs:['ep-1','ep-2']}),
        feedbackOnly:C.createEvidence({ref:'ev-2',feedbackRefs:['fb-1']}),
        value:V({value:240}),values:V({values:[240]}),
        unsourced:V({sourceRefs:[]}),
        feedbackAsMeasure:V({sourceRefs:['fb-1']}),
        duplicate:V({sourceRefs:['ep-1','ep-1']}),
        metric:V({metric:'vibes'}),
        aggregate:V({aggregate:'median'}),
        nothing:refused(()=>C.createEvidence({ref:'ev-3'})),
      });
    """)
    assert result["ok"]["sourceRefs"] == ["ep-1", "ep-2"] and "value" not in result["ok"]
    assert result["feedbackOnly"]["metric"] is None
    assert result["value"] == "barehands_evidence_value_embedded"
    assert result["values"] == "barehands_evidence_value_embedded"
    assert result["unsourced"] == "barehands_evidence_unsourced"
    assert result["feedbackAsMeasure"] == "barehands_session_ref_invalid"
    assert result["duplicate"] == "barehands_session_ref_duplicate"
    assert result["metric"] == "barehands_metric_unknown"
    assert result["aggregate"] == "barehands_metric_aggregate_unknown"
    assert result["nothing"] == "barehands_evidence_unsourced"


def test_a_hypothesis_is_sourced_bounded_and_cannot_change_status_without_a_reason(tmp_path):
    result = run_node(tmp_path, """
      const H=patch=>refused(()=>C.createHypothesis({ref:'hy-1',cause:'release_confirmation_too_slow',
        confidence:.6,status:'open',evidenceRefs:['ev-1'],...patch}));
      out({
        statuses:C.HYPOTHESIS_STATUSES,
        ok:H({}),rejectedByTrial:H({status:'rejected',confidence:.1,trialRefs:['tr-2']}),
        fromFeedback:H({evidenceRefs:[],feedbackRefs:['fb-1']}),
        supportedByFeedbackOnly:H({status:'supported',evidenceRefs:[],feedbackRefs:['fb-1']}),
        weakenedWithoutReason:H({status:'weakened',evidenceRefs:[],feedbackRefs:['fb-1']}),
        fromNothing:H({evidenceRefs:[]}),
        confidence:H({confidence:1.2}),
        cause:H({cause:'bad_luck'}),
        status:H({status:'proven'}),
        causeKeys:C.HYPOTHESIS_CAUSE_KEYS,advertised:C.TRIAL_ADVERTISED_KEYS,
      });
    """)
    assert result["statuses"] == ["open", "supported", "weakened", "rejected"]
    assert result["ok"] is None and result["rejectedByTrial"] is None and result["fromFeedback"] is None
    assert result["supportedByFeedbackOnly"] == "barehands_hypothesis_unsourced"
    assert result["weakenedWithoutReason"] == "barehands_hypothesis_unsourced"
    assert result["fromNothing"] == "barehands_hypothesis_unsourced"
    assert result["confidence"] == "barehands_hypothesis_confidence_invalid"
    assert result["cause"] == "barehands_hypothesis_cause_unknown"
    assert result["status"] == "barehands_hypothesis_status_unknown"
    for cause, keys in result["causeKeys"].items():
        assert set(keys) <= set(result["advertised"]), cause


def test_the_agent_cites_a_trial_outcome_and_the_code_computes_its_deltas(tmp_path):
    """Rework QA n° 3 : l'issue écrite par l'agent ne porte aucun nombre ; les
    deltas viennent d'un jeu de mesures, les références d'avant et d'après ne
    se recouvrent pas, et un verdict contredit par les deltas se refuse."""

    result = run_node(tmp_path, """
      const o={trialRef:'tr-1',verdict:'improved',comparisons:[{metric:'release_latency_ms',aggregate:'p95'}],
        beforeRefs:['ep-1','ep-2'],afterRefs:['ep-3','ep-4'],hypothesisRefs:['hy-1']};
      const m={'ep-1':{release_latency_ms:200},'ep-2':{release_latency_ms:240},
        'ep-3':{release_latency_ms:120},'ep-4':{release_latency_ms:null}};
      const ctx={hypotheses:[{ref:'hy-1',cause:'release_confirmation_too_slow',confidence:.6,status:'open',
        evidenceRefs:['ev-1']}]};
      const O=patch=>refused(()=>C.createTrialOutcome({...o,...patch}));
      const S=(patch,set)=>refused(()=>C.resolveTrialOutcome({...o,...patch},set||m,ctx));
      out({
        verdicts:C.TRIAL_VERDICTS,
        resolved:C.resolveTrialOutcome(o,m,ctx),
        numbers:O({deltas:[{before:1,after:2}]}),
        numberInComparison:O({comparisons:[{metric:'release_latency_ms',aggregate:'p95',before:240}]}),
        overlap:O({afterRefs:['ep-2','ep-3']}),
        same:O({afterRefs:['ep-1','ep-2']}),
        opinion:O({comparisons:[]}),
        felt:O({comparisons:[],beforeRefs:[],afterRefs:[],feedbackRefs:['fb-4']}),
        silentInconclusive:O({verdict:'inconclusive',comparisons:[],beforeRefs:[],afterRefs:[]}),
        verdict:O({verdict:'better'}),
        contradicted:S({verdict:'worse'}),
        unsupported:S({},{...m,'ep-3':{release_latency_ms:240},'ep-4':{release_latency_ms:200}}),
        missing:S({},{'ep-1':{release_latency_ms:200}}),
        invented:S({},{...m,'ep-9':{release_latency_ms:'fast'}}),
        foreignMetric:S({},{...m,'ep-9':{score:1}}),
        rateGone:O({comparisons:[{metric:'false_press_rate',aggregate:'rate'}]}),
        count:C.aggregateMetric('release_latency_ms','count',['ep-1','ep-4'],C.createMeasurementSet(m)),
        mean:C.aggregateMetric('release_latency_ms','mean',['ep-1','ep-2'],C.createMeasurementSet(m)),
      });
    """)
    assert result["verdicts"] == ["improved", "no_change", "worse", "inconclusive"]
    delta = result["resolved"]["deltas"][0]
    assert delta == {"metric": "release_latency_ms", "aggregate": "p95", "before": 238, "after": 120,
                     "delta": -118, "direction": "better"}
    assert "deltas" not in result["resolved"]["outcome"]
    assert result["numbers"] == "barehands_evidence_value_embedded"
    assert result["numberInComparison"] == "barehands_evidence_value_embedded"
    assert result["overlap"] == "barehands_trial_refs_overlap"
    assert result["same"] == "barehands_trial_refs_overlap"
    assert result["opinion"] == "barehands_evidence_unsourced"
    assert result["felt"] is None and result["silentInconclusive"] is None
    assert result["verdict"] == "barehands_trial_verdict_unknown"
    assert result["contradicted"] == "barehands_trial_verdict_contradicted"
    assert result["unsupported"] == "barehands_trial_verdict_unsupported", "delta nul : rien ne soutient improved"
    assert result["missing"] == "barehands_measurement_missing"
    assert result["invented"] == "barehands_measurement_invalid"
    assert result["foreignMetric"] == "barehands_session_key_unknown"
    assert result["rateGone"] == "barehands_metric_aggregate_unknown"
    assert result["count"] == 1 and result["mean"] == 220


# ------------------------------------------------------------------------ banc


def test_the_benchmark_schema_links_every_dimension_to_raw_metrics_and_holds_no_formula(tmp_path):
    result = run_node(tmp_path, """
      const plan=C.createBenchmarkPlan({seed:42,exercises:[{ref:'ex-1',kind:'target_acquisition',trials:5},
        {ref:'ex-2',kind:'drag_drop',trials:3}]});
      const metricsOf=kind=>Object.fromEntries(C.BENCHMARK_EXERCISE_METRICS[kind].map(m=>[m,null]));
      const result=(seed,patch)=>({ref:'bm-1',seed,runAt:1758800000000,profileSource:'saved',exercises:plan.exercises.map(e=>({...e,
        metrics:{...metricsOf(e.kind),...(patch&&patch[e.kind]||{})}}))});
      const before=result(42,{target_acquisition:{acquisition_ms:900},drag_drop:{drag_success_rate:.6}});
      const after={...result(7,{drag_drop:{drag_success_rate:.9}}),profileSource:'trial',trialRef:'tr-2',
        runAt:1758800600000};
      out({
        kinds:C.BENCHMARK_EXERCISES,dims:C.BENCHMARK_DIMENSION_METRICS,produced:C.BENCHMARK_EXERCISE_METRICS,
        metric:C.CALIBRATION_METRIC,
        ok:C.createBenchmarkResult(before),
        comparable:C.benchmarkComparable(before,after),
        notComparable:C.benchmarkComparable(before,{...after,exercises:after.exercises.slice(0,1)}),
        missing:refused(()=>C.createBenchmarkResult({...before,exercises:[{...before.exercises[0],metrics:{acquisition_ms:1}}]})),
        foreign:refused(()=>C.createBenchmarkResult({...before,exercises:[{...before.exercises[0],
          metrics:{...before.exercises[0].metrics,score:99}}]})),
        rate:refused(()=>C.createBenchmarkResult(result(1,{drag_drop:{drag_success_rate:1.5}}))),
        setting:refused(()=>C.createBenchmarkResult({...before,settings:{assistance:1}})),
        seed:refused(()=>C.createBenchmarkPlan({seed:-1,exercises:plan.exercises})),
        kind:refused(()=>C.createBenchmarkPlan({seed:1,exercises:[{ref:'ex-1',kind:'arcade',trials:1}]})),
        dup:refused(()=>C.createBenchmarkPlan({seed:1,exercises:[plan.exercises[0],plan.exercises[0]]})),
      });
    """)
    assert result["kinds"] == [
        "target_acquisition", "no_click_tracking", "nearby_targets", "drag_drop", "moving_target", "chained",
    ]
    produced = {m for ms in result["produced"].values() for m in ms}
    scored = {m for ms in result["dims"].values() for m in ms}
    assert produced == scored
    assert all(result["metric"][m]["better"] in ("lower", "higher", None) for m in produced)
    assert "score" not in json.dumps(result["ok"])
    assert result["ok"]["exercises"][0]["metrics"]["acquisition_ms"] == 900
    assert result["comparable"] is True and result["notComparable"] is False
    assert result["missing"] == "barehands_benchmark_metric_missing"
    assert result["foreign"] == "barehands_session_key_unknown"
    assert result["rate"] == "barehands_benchmark_invalid"
    assert result["setting"] == "barehands_session_key_unknown"
    assert result["seed"] == "barehands_benchmark_seed_invalid"
    assert result["kind"] == "barehands_benchmark_exercise_unknown"
    assert result["dup"] == "barehands_session_ref_duplicate"


# ------------------------------------------------------- télémétrie de séance


def test_session_telemetry_reuses_the_trace_whitelist_and_refuses_raw_input(tmp_path):
    """Décision 34 : un échantillon est valide s'il est un point fixe de la
    liste blanche de l'enregistreur. Points de main, images et charges libres
    ne le sont jamais."""

    result = run_node(tmp_path, """
      const frame=R.readSessionSample({ref:'se-1',t:30,stage:'aim',exerciseRef:'ex-1',trialRef:'tr-1',
        frame:{t:30,lifecycle:'active',hands:[{slot:0,handedness:'left',primaryRatio:.3,quality:.9,
          landmarks:[{x:.1,y:.2}]}],candidates:[{kind:'scene_object',region:'body',boundsPx:{x:1,y:2,w:3,h:4},
          objectId:'secret-star'}],events:[{type:'click',channel:'primary',objectId:'x',axes:[]}],gestures:[]}});
      const event=R.readSessionSample({ref:'se-2',t:31,event:{kind:'feedback',ref:'fb-1',text:'le release colle'}});
      const V=raw=>refused(()=>R.validateSessionSample(raw));
      out({
        frame,event,
        frameOk:V(frame),eventOk:V(event),
        sameShapes:JSON.stringify(Object.keys(frame.frame.hands[0]).sort())===JSON.stringify(Object.keys(R.BLANK_HAND).sort()),
        landmarks:V({...frame,frame:{...frame.frame,hands:[{...frame.frame.hands[0],landmarks:[[.1,.2]]}]}}),
        pointsAsValue:V({...frame,frame:{...frame.frame,hands:[{...frame.frame.hands[0],primaryRatio:[{x:1,y:2}]}]}}),
        image:V({...event,image:'data:image/png;base64,iVBORw0KGgo='}),
        imageAsWord:V({...frame,stage:'data:image/png;base64,iVBORw0KGgo='}),
        nested:V({...event,event:{...event.event,payload:{anything:1}}}),
        text:V({...event,event:{...event.event,ref:'le release colle'}}),
        both:V({...frame,event:event.event}),
        neither:V({...frame,frame:null}),
        noRef:V({...event,ref:null}),
        unknownKind:V({...event,event:{...event.event,kind:'screenshot'}}),
        events:C.SESSION_EVENTS,
      });
    """)
    assert result["frameOk"] is None and result["eventOk"] is None and result["sameShapes"] is True
    hand = result["frame"]["frame"]["hands"][0]
    assert "landmarks" not in hand and hand["primaryRatio"] == 0.3
    candidate = result["frame"]["frame"]["candidates"][0]
    assert "objectId" not in candidate and candidate["x"] == 1
    assert result["event"]["event"]["ref"] == "fb-1" and "text" not in result["event"]["event"]
    assert result["landmarks"] == "barehands_session_key_unknown"
    assert result["pointsAsValue"] == "barehands_session_not_derived"
    assert result["image"] == "barehands_session_key_unknown"
    assert result["imageAsWord"] == "barehands_session_not_derived"
    assert result["nested"] == "barehands_session_key_unknown"
    assert result["text"] == "barehands_session_not_derived"
    assert result["both"] == "barehands_session_not_derived"
    assert result["neither"] == "barehands_session_sample_invalid"
    assert result["noRef"] == "barehands_session_ref_invalid"
    assert result["unknownKind"] == "barehands_session_event_unknown"
    assert "feedback" in result["events"] and "false_event" in result["events"]


def test_check_schema_turns_a_refusal_into_a_verdict_without_hiding_programming_errors(tmp_path):
    result = run_node(tmp_path, """
      out({
        ok:C.checkSchema(C.createFalseEvent,{ref:'ng-1',falseKind:'false_press',t:0}),
        ko:C.checkSchema(C.createFalseEvent,{ref:'ng-1',falseKind:'nope',t:0}),
        bug:refused(()=>C.checkSchema(()=>{throw new TypeError('boom')})),
      });
    """)
    assert result["ok"]["ok"] is True and result["ok"]["code"] is None
    assert result["ko"]["ok"] is False and result["ko"]["code"] == "barehands_false_event_unknown"
    assert result["ko"]["errors"][0]["code"] == "barehands_false_event_unknown"
    assert result["bug"] == "boom"


# ---------------------------------------------------------------- documentation


def test_the_contract_document_names_what_the_code_names(tmp_path):
    """§ 17 : chaque clé d'essai, catégorie de retour, rétention et décision
    34 à 42 est écrite ; les dérives D5 sont corrigées."""

    result = run_node(tmp_path, """
      out({keys:C.TRIAL_KEY_NAMES,feedback:C.USER_FEEDBACKS,retention:C.DATA_RETENTION,
        exercises:C.BENCHMARK_EXERCISES,dims:C.BENCHMARK_DIMENSIONS,causes:C.HYPOTHESIS_CAUSES})
    """)
    doc = DOC.read_text(encoding="utf-8")
    section = doc[doc.index("## 17. Calibration adaptative"):]
    for group in ("keys", "feedback", "exercises", "dims", "causes"):
        for name in result[group]:
            assert f"`{name}`" in section, (group, name)
    for name, retention in result["retention"].items():
        assert re.search(rf"\| `{name}` \|[^\n]*\b{retention}\b", section), name
    for number in range(34, 43):
        assert f"décision {number}" in section.lower() or f"décisions {number}" in section.lower(), number
    # D5 : relâchement relatif documenté dans la section du pincement, plage
    # réelle de travelSlopNorm.
    pinch = doc[doc.index("## 5. Intention de pincement"):doc.index("## 6. Cible et régions")]
    assert "`releaseDeltaRatio`" in pinch and "0,15" in pinch
    assert "| `travelSlopNorm` | **fraction de la largeur de l'image** (0..1) | 0,002 – 0,014 |" in doc
    assert barehands_profile.HAND_BOUNDS["travel_slop_norm"] == (0.002, 0.014)


def test_the_sensitivity_help_says_what_the_setting_does():
    """D5 : `sensitivity` divise les tolérances clic/glissement ; ce n'est pas
    un facteur de déplacement du pointeur."""

    option = next(o for o in settings_mcp.BAREHANDS_OPTIONS if o["key"] == "sensitivity")
    assert "pointeur" not in option["help"]
    assert "divise" in option["help"].lower() and "glissement" in option["help"]
    # Rework QA n° 10 : « 1 = défauts du moteur » était faux avec un
    # `travelSlopNorm` calibré.
    assert "défauts du moteur" not in option["help"] and "calibration" in option["help"]


# ------------------------------------------------------------ reprise après QA


PROTOTYPE_NAMES = ["toString", "constructor", "valueOf", "hasOwnProperty", "__defineGetter__",
                   "isPrototypeOf", "__proto__"]


def test_inherited_prototype_names_are_never_known_keys(tmp_path):
    """Rework QA n° 1 et 2 : `clé in table` et `table[clé]` trouvaient les noms
    hérités d'`Object.prototype`. Ni un patch d'essai, ni un échantillon de
    séance, ni une mesure ne les accepte."""

    result = run_node(tmp_path, f"""
      const names={json.dumps(PROTOTYPE_NAMES)};
      const own=(k,v)=>{{const o={{}};Object.defineProperty(o,k,{{value:v,enumerable:true}});return o}};
      const v=R.readSessionSample({{ref:'se-1',t:1,event:{{kind:'click'}}}});
      const withOwn=(base,k,val)=>Object.assign(own(k,val),base);
      const qa={{...v,constructor:[[.1,.2,.3]],toString:'là ça a merdé',
        hasOwnProperty:'data:image/png;base64,iVBORw0KGgo=',event:{{...v.event,valueOf:{{landmarks:[[1,2,3]]}}}}}};
      out({{
        patch:names.map(k=>C.validateTrialPatch(own(k,1)).code),
        base:C.validateTrialPatch({{releaseRatio:.44}},own('constructor',.1)).ok,
        sample:names.map(k=>refused(()=>R.validateSessionSample(withOwn(v,k,'x')))),
        event:names.map(k=>refused(()=>R.validateSessionSample({{...v,event:withOwn(v.event,k,'x')}}))),
        qa:refused(()=>R.validateSessionSample(qa)),
        qaEventOnly:refused(()=>R.validateSessionSample({{...v,event:{{...v.event,valueOf:{{landmarks:[[1,2,3]]}}}}}})),
        measurement:names.map(k=>refused(()=>C.createMeasurementSet({{'ep-1':own(k,1)}}))),
        benchmark:refused(()=>C.createBenchmarkResult(withOwn({{ref:'bm-1',seed:1,runAt:1,profileSource:'saved',
          exercises:[{{ref:'ex-1',kind:'chained',trials:1,metrics:withOwn({{transition_ms:null,missed_click_count:null,
          wrong_target_count:null,premature_drop_count:null,release_latency_ms:null}},'toString',1)}}]}},'valueOf',1))),
        evidence:refused(()=>C.createEvidence(withOwn({{ref:'ev-1',feedbackRefs:['fb-1']}},'hasOwnProperty',1))),
      }});
    """)
    assert result["patch"] == ["barehands_trial_key_unknown"] * len(PROTOTYPE_NAMES)
    assert result["base"] is True, "une ancre héritée dans `base` n'est pas lue"
    assert result["sample"] == ["barehands_session_key_unknown"] * len(PROTOTYPE_NAMES)
    assert result["event"] == ["barehands_session_key_unknown"] * len(PROTOTYPE_NAMES)
    assert result["qa"] == "barehands_session_key_unknown"
    assert result["qaEventOnly"] == "barehands_session_key_unknown"
    assert result["measurement"] == ["barehands_session_key_unknown"] * len(PROTOTYPE_NAMES)
    assert result["benchmark"] == "barehands_session_key_unknown"
    assert result["evidence"] == "barehands_session_key_unknown"


def test_a_session_sample_missing_a_key_or_carrying_too_long_a_list_is_refused(tmp_path):
    result = run_node(tmp_path, """
      const frame=R.readSessionSample({ref:'se-1',t:1,frame:{t:1,candidates:[]}});
      const drop=(o,k)=>{const c={...o};delete c[k];return c};
      const many=n=>Array.from({length:n},(_,i)=>({...R.BLANK_CANDIDATE,ref:i,kind:'button'}));
      const read=R.readSessionSample({ref:'se-2',t:1,frame:{t:1,candidates:many(40)}});
      const h=R.createSessionHistory(2);
      for(let i=1;i<=3;i+=1)h.push(R.readSessionSample({ref:'se-'+i,t:i,event:{kind:'click'}}));
      out({
        missingTop:refused(()=>R.validateSessionSample(drop(frame,'stage'))),
        missingHand:refused(()=>R.validateSessionSample({...frame,frame:drop(frame.frame,'gestures')})),
        tooMany:refused(()=>R.validateSessionSample({...frame,frame:{...frame.frame,candidates:many(40)}})),
        truncated:read.frame.candidates.length,max:R.SESSION_LIST_MAX,
        history:[h.size(),h.dropped(),h.samples().map(x=>x.ref)],
        historyRefuses:refused(()=>h.push({ref:'se-9',t:1,event:{kind:'click'},landmarks:[]})),
        historyMax:R.SESSION_HISTORY_MAX,
        historyTooBig:refused(()=>R.createSessionHistory(R.SESSION_HISTORY_MAX+1)),
      });
    """)
    assert result["missingTop"] == "barehands_session_key_missing"
    assert result["missingHand"] == "barehands_session_key_missing"
    assert result["tooMany"] == "barehands_session_list_too_long"
    assert result["truncated"] == result["max"] == 32
    assert result["history"] == [2, 1, ["se-2", "se-3"]]
    assert result["historyRefuses"] == "barehands_session_key_unknown"
    assert result["historyMax"] == 3000
    assert "capacité" in result["historyTooBig"]


def test_pair_rules_pin_equality_where_the_engine_allows_it_and_guard_the_wake_band(tmp_path):
    """Rework QA n° 8 et 9 : `≤` (pas `<`) pour clic/glissement et
    zone/maintien, comme `options()` ; et `releaseRatio < wakeGapMin`, ancre
    recopiée du moteur."""

    result = run_node(tmp_path, """
      const V=C.validateTrialPatch;
      out({
        slopEqual:V({clickSlopPx:20,dragSlopPx:20}).ok,
        zoneEqual:V({targetZonePx:20,targetZoneHoldPx:20}).ok,
        pressEqual:V({pressRatio:.3,releaseRatio:.3}).code,
        stillEqual:V({stillSpeedPx:80,moveSpeedPx:80}).ok,
        wake:V({releaseRatio:.5}).code,wakeEdge:V({releaseRatio:.46}).code,
        wakeRaised:V({releaseRatio:.5},{wakeGapMin:.6}).ok,
        anchor:C.TRIAL_ANCHORS.wakeGapMin.default===Core.DEFAULTS.wakeGapMin,
        partners:C.trialPartners('releaseRatio'),
      });
    """)
    assert result["slopEqual"] is True and result["zoneEqual"] is True
    assert result["pressEqual"] == "barehands_trial_invariant_violated"
    assert result["stillEqual"] is False
    assert result["wake"] == "barehands_trial_invariant_violated"
    assert result["wakeEdge"] == "barehands_trial_invariant_violated"
    assert result["wakeRaised"] is True and result["anchor"] is True
    assert result["partners"] == ["pressRatio", "wakeGapMin"]


def test_pointing_intent_is_measurable_and_now_tunable(tmp_path):
    result = run_node(tmp_path, """
      out({events:C.SESSION_EVENTS,falseKinds:C.FALSE_EVENTS,metric:C.CALIBRATION_METRIC.unintended_pointer_rate,
        noClick:C.BENCHMARK_EXERCISE_METRICS.no_click_tracking,dims:C.BENCHMARK_DIMENSION_METRICS.false_positive_resistance,
        cause:C.HYPOTHESIS_CAUSE_KEYS.pointer_shown_without_intent,
        sample:refused(()=>R.validateSessionSample(R.readSessionSample({ref:'se-1',t:1,event:{kind:'pointer_shown',slot:0}}))),
        episode:C.createPinchEpisode({ref:'ep-1',channel:'primary',exerciseRef:'ex-2',trialRef:'tr-3',startT:0,endT:10,
          closingMs:1,minimumMs:1,openingMs:1,baselineBefore:.8,baselineAfter:.8,minRatio:.1,closingVelocity:1,
          openingVelocity:1,travelPx:0,stillness:1,quality:1,complete:true})});
    """)
    for name in ("pointing_intent_start", "pointing_intent_end", "pointer_shown", "pointer_hidden"):
        assert name in result["events"]
    assert "unintended_pointer" in result["falseKinds"]
    assert result["metric"]["unit"] == "per_min" and result["metric"]["better"] == "lower"
    assert "unintended_pointer_rate" in result["noClick"] and "unintended_pointer_rate" in result["dims"]
    # Slice 03 : la cause a maintenant ses clés d'essai — l'entrée de
    # l'intention de pointer (décision 46).
    assert result["cause"] == ["pointingEnterScore", "pointingEnterMs", "pointingMotionFloor"]
    assert result["sample"] is None
    assert result["episode"]["exerciseRef"] == "ex-2" and result["episode"]["trialRef"] == "tr-3"
    source = ADAPTIVE.read_text(encoding="utf-8")
    assert "n'en inventent pas" not in source and "Règle d'extension" in source


def test_feedback_categories_are_deduplicated_and_capped(tmp_path):
    result = run_node(tmp_path, """
      const F=categories=>refused(()=>C.createUserFeedback({ref:'fb-1',categories,text:'x',source:'voice',t:1}));
      out({max:C.FEEDBACK_CATEGORIES_MAX,
        dup:C.createUserFeedback({ref:'fb-1',categories:['laggy','laggy','laggy','laggy'],text:'x',source:'ui',t:1}).categories,
        four:F(['laggy','hard_to_aim','jumpy_pointer','wrong_target']),
        flood:F(Array(100).fill('laggy'))});
    """)
    assert result["max"] == 3 and result["dup"] == ["laggy"]
    assert result["four"] == "barehands_feedback_too_many_categories"
    assert result["flood"] == "barehands_session_list_too_long"


def test_benchmark_values_respect_their_metric_and_the_profile_is_identified(tmp_path):
    result = run_node(tmp_path, """
      const base=(metrics,extra)=>({ref:'bm-1',seed:1,runAt:1758800000000,profileSource:'saved',...extra,
        exercises:[{ref:'ex-1',kind:'chained',trials:4,metrics:{transition_ms:null,missed_click_count:null,
          wrong_target_count:null,premature_drop_count:null,release_latency_ms:null,timeout_count:null,...metrics}}]});
      const B=(m,e)=>refused(()=>C.createBenchmarkResult(base(m,e)));
      out({
        negativeLatency:B({release_latency_ms:-30}),
        tooNegative:B({release_latency_ms:-3000}),
        fractionalCount:B({missed_click_count:1.5}),
        overTrials:B({missed_click_count:5}),
        atTrials:B({missed_click_count:4}),
        trialNoRef:B({},{profileSource:'trial'}),
        savedWithRef:B({},{trialRef:'tr-1'}),
        fingerprint:B({},{profileFingerprint:'deadbeef'}),
        badFingerprint:B({},{profileFingerprint:'Hello World'}),
        noRunAt:refused(()=>{const r=base({});delete r.runAt;C.createBenchmarkResult(r)}),
      });
    """)
    assert result["negativeLatency"] is None
    assert result["tooNegative"] == "barehands_benchmark_invalid"
    assert result["fractionalCount"] == "barehands_benchmark_invalid"
    assert result["overTrials"] == "barehands_benchmark_invalid"
    assert result["atTrials"] is None
    assert result["trialNoRef"] == "barehands_benchmark_profile_invalid"
    assert result["savedWithRef"] == "barehands_benchmark_profile_invalid"
    assert result["fingerprint"] is None
    assert result["badFingerprint"] == "barehands_benchmark_profile_invalid"
    assert result["noRunAt"] == "barehands_benchmark_invalid"


def test_the_replay_metrics_and_the_calibration_metrics_are_mapped_not_duplicated(tmp_path):
    """Rework QA n° 7 : deux tables pour deux questions (rejeu hors ligne,
    séance en direct), une correspondance écrite, testée contre le rejeu, et un
    seul quantile."""

    result = run_node(tmp_path, """
      out({map:C.REPLAY_METRIC_EQUIVALENTS,replay:R.METRIC_KEYS,metrics:C.CALIBRATION_METRICS,
        sameQuantile:R.quantile===C.quantile,q:C.quantile([1,2,3,4],.95)});
    """)
    for name, entry in result["map"].items():
        assert name in result["metrics"], name
        assert entry["replay"] in result["replay"], entry
        assert entry["conversion"]
    assert result["sameQuantile"] is True and abs(result["q"] - 3.85) < 1e-9
    doc = DOC.read_text(encoding="utf-8")
    for name, entry in result["map"].items():
        assert f"`{name}`" in doc and f"`{entry['replay']}`" in doc


# --------------------------------------------- seconde reprise : retours cités


def test_a_cited_feedback_supports_a_verdict_only_if_it_exists_is_fresh_and_agrees(tmp_path):
    """Seconde reprise QA : `improved`/`worse` ne passaient plus seulement
    parce qu'un `feedbackRefs` était cité. Le résolveur lit les
    enregistrements : un retour absent, antérieur à l'essai ou contraire au
    verdict se refuse, et rien de mesuré ni de dit ne soutient un verdict
    muet."""

    result = run_node(tmp_path, """
      const hy={ref:'hy-1',cause:'release_threshold_too_far',confidence:.6,status:'open',evidenceRefs:['ev-1']};
      const fb=(ref,categories,t)=>({ref,categories,text:'x',source:'voice',t});
      const feedback=[fb('fb-1',['release_sticky'],500),fb('fb-2',['fine'],1500),fb('fb-3',['release_sticky'],1600),
        fb('fb-4',['jumpy_pointer'],1700),fb('fb-5',['unclear'],1800)];
      const ctx={appliedAt:1000,feedback,hypotheses:[hy]};
      const base={trialRef:'tr-1',hypothesisRefs:['hy-1']};
      const m={'ep-1':{release_latency_ms:200},'ep-2':{release_latency_ms:null}};
      const R_=(o,c,set)=>refused(()=>C.resolveTrialOutcome({...base,...o},set||m,c===undefined?ctx:c));
      const cmp=[{metric:'release_latency_ms',aggregate:'p95'}];
      out({
        /* Les trois cas de la QA. */
        complaintAsImproved:R_({verdict:'improved',feedbackRefs:['fb-3']}),
        unmeasuredAfter:R_({verdict:'improved',comparisons:cmp,beforeRefs:['ep-1'],afterRefs:['ep-2']}),
        countOnly:R_({verdict:'improved',comparisons:[{metric:'release_latency_ms',aggregate:'count'}],
          beforeRefs:['ep-1'],afterRefs:['ep-2']}),
        /* Ce qui soutient vraiment. */
        fine:R_({verdict:'improved',feedbackRefs:['fb-2']}),
        otherComplaint:R_({verdict:'improved',feedbackRefs:['fb-4']}),
        unclearAlone:R_({verdict:'improved',feedbackRefs:['fb-5']}),
        worse:R_({verdict:'worse',feedbackRefs:['fb-3']}),
        worseButFine:R_({verdict:'worse',feedbackRefs:['fb-2']}),
        worseOtherComplaint:R_({verdict:'worse',feedbackRefs:['fb-4']}),
        /* Les références doivent se retrouver, et dater d'après l'essai. */
        stale:R_({verdict:'worse',feedbackRefs:['fb-1']}),
        missing:R_({verdict:'improved',feedbackRefs:['fb-9']}),
        noAppliedAt:R_({verdict:'improved',feedbackRefs:['fb-2']},{feedback,hypotheses:[hy]}),
        hypothesisMissing:R_({verdict:'improved',feedbackRefs:['fb-2']},{appliedAt:1000,feedback}),
        noHypothesisAnyComplaint:refused(()=>C.resolveTrialOutcome({trialRef:'tr-1',verdict:'improved',
          feedbackRefs:['fb-4']},m,ctx)),
        badContext:R_({verdict:'inconclusive'},{appliedAt:1000,notes:'x'}),
        inconclusive:R_({verdict:'inconclusive',feedbackRefs:['fb-3']}),
      });
    """)
    assert result["complaintAsImproved"] == "barehands_trial_feedback_contradicts"
    assert result["unmeasuredAfter"] == "barehands_trial_verdict_unsupported"
    assert result["countOnly"] == "barehands_trial_verdict_unsupported"
    assert result["fine"] is None
    assert result["otherComplaint"] is None, "le symptôme visé a disparu"
    assert result["unclearAlone"] == "barehands_trial_verdict_unsupported"
    assert result["worse"] is None
    assert result["worseButFine"] == "barehands_trial_feedback_contradicts"
    assert result["worseOtherComplaint"] == "barehands_trial_verdict_unsupported"
    assert result["stale"] == "barehands_trial_feedback_stale"
    assert result["missing"] == "barehands_trial_feedback_missing"
    assert result["noAppliedAt"] == "barehands_trial_applied_at_missing"
    assert result["hypothesisMissing"] == "barehands_trial_hypothesis_missing"
    assert result["noHypothesisAnyComplaint"] == "barehands_trial_feedback_contradicts"
    assert result["badContext"] == "barehands_session_key_unknown"
    assert result["inconclusive"] is None


def test_a_count_in_a_measurement_set_must_be_a_whole_number(tmp_path):
    result = run_node(tmp_path, """
      const M=v=>refused(()=>C.createMeasurementSet({'bm-1':{missed_click_count:v}}));
      out({whole:M(2),fraction:M(1.5),negative:M(-1),notCount:refused(()=>C.createMeasurementSet({'ep-1':{release_latency_ms:12.5}}))});
    """)
    assert result["whole"] is None and result["notCount"] is None
    assert result["fraction"] == "barehands_measurement_invalid"
    assert result["negative"] == "barehands_measurement_invalid"


def test_the_document_says_only_a_resolved_outcome_may_be_stored():
    doc = DOC.read_text(encoding="utf-8")
    section = doc[doc.index("## 17. Calibration adaptative"):]
    assert "`resolveTrialOutcome(issue, mesures, contexte)`" in section
    assert "seule qu'on ait le droit de ranger" in section



# ------------------------------------------------ module séparé (Slice 10)


def test_the_adaptive_module_extends_the_contract_without_copying_or_shadowing_it(tmp_path):
    """Slice 10 : le § 12 vit dans son module. Il **étend** le contrat : mêmes
    objets pour les noms du contrat (identité, pas copie), ses propres noms en
    plus, aucun recouvrement, objet gelé, et le contrat seul ne porte plus
    aucun nom du § 12."""

    result = run_node(tmp_path, f"""
      const K=require({json.dumps(str(CONTRACTS))});
      const own=C.ADAPTIVE_NAMES;
      out({{
        frozen:Object.isFrozen(C),baseFrozen:Object.isFrozen(K),
        sameBase:Object.keys(K).every(name=>C[name]===K[name]),
        leaked:own.filter(name=>Object.prototype.hasOwnProperty.call(K,name)),
        count:own.length,
        keys:Object.keys(C).length===Object.keys(K).length+own.length+1,
        global:globalThis.JarvisBarehandsAdaptive===C,
        refusalClass:(()=>{{try{{C.validateTrialPatch({{toString:1}});return null}}
          catch(e){{return e instanceof K.BareHandsSchemaError}}}})(),
        patch:C.validateTrialPatch({{toString:1}},{{}}).ok,
        schemaHelpers:Object.keys(K.schema).sort(),
      }});
    """)
    assert result["frozen"] and result["baseFrozen"]
    assert result["sameBase"], "les noms du contrat sont les mêmes objets, pas des copies"
    assert result["leaked"] == [], "le contrat seul ne porte plus de nom du § 12"
    assert result["count"] >= 80 and result["keys"]
    assert result["global"]
    assert result["patch"] is False
    assert result["schemaHelpers"] == ["finiteOr", "reject", "requireSchemaVersion", "unit", "values"]


def test_the_adaptive_module_refuses_to_load_without_the_contract(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    victim = tmp_path / "control_center_barehands_adaptive.js"
    victim.write_text(ADAPTIVE.read_text(encoding="utf-8"), encoding="utf-8")
    completed = subprocess.run([node, "-e", f"require({json.dumps(str(victim))})"],
                               capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
    assert completed.returncode != 0
    assert "doit être chargé avant ce module" in completed.stderr or "Cannot find module" in completed.stderr


def test_the_adaptive_module_touches_no_dom_network_or_clock():
    source = ADAPTIVE.read_text(encoding="utf-8")
    body = source[source.index("(function(root)"):]
    for forbidden in ("document.", "window.", "fetch(", "XMLHttpRequest", "setTimeout", "Date.now",
                      "performance.now", "localStorage"):
        assert forbidden not in body, forbidden


async def test_the_page_serves_the_adaptive_module_right_after_the_contract(tmp_path):
    """Un repère de page de plus, et son rang est porteur : juste après le
    contrat qu'il étend, avant l'enregistreur, la calibration, l'agent, le banc
    et le pointeur qui le lisent au chargement."""

    from jarvis.runtime.control_center import (
        BAREHANDS_ADAPTIVE_SCRIPT_MARKER, BAREHANDS_CALIBRATION_AGENT_SCRIPT_MARKER,
        BAREHANDS_BENCHMARK_SCRIPT_MARKER, BAREHANDS_CALIBRATION_SCRIPT_MARKER,
        BAREHANDS_CONTRACTS_SCRIPT_MARKER, BAREHANDS_RECORDER_SCRIPT_MARKER,
        BAREHANDS_SCRIPT_MARKER, ControlCenter,
    )

    raw = (RUNTIME / "control_center.html").read_text(encoding="utf-8")
    order = [raw.index(marker) for marker in (
        BAREHANDS_CONTRACTS_SCRIPT_MARKER, BAREHANDS_ADAPTIVE_SCRIPT_MARKER,
        BAREHANDS_CALIBRATION_SCRIPT_MARKER, BAREHANDS_RECORDER_SCRIPT_MARKER,
        BAREHANDS_CALIBRATION_AGENT_SCRIPT_MARKER, BAREHANDS_BENCHMARK_SCRIPT_MARKER,
        BAREHANDS_SCRIPT_MARKER)]
    assert order == sorted(order)
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    html = (await control.index(None)).text
    assert BAREHANDS_ADAPTIVE_SCRIPT_MARKER not in html, "le repère a été remplacé"
    assert (html.index("root.JarvisBarehandsContracts=api")
            < html.index("root.JarvisBarehandsAdaptive=api")
            < html.index("root.JarvisBarehandsCalibration=api")
            < html.index("function installJarvisBarehands"))


def test_a_name_on_both_sides_refuses_to_load(tmp_path):
    """Survivant B1 (QA Slice 10) : étendre, jamais recouvrir. Un nom du
    contrat recopié dans l'export du module adaptatif fait refuser le
    chargement, en le nommant."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    source = ADAPTIVE.read_text(encoding="utf-8")
    anchor = "    SESSION_SCHEMA_VERSION,SESSION_REF,"
    assert anchor in source, "l'ancre de la mutation doit exister"
    clashing = source.replace(anchor, "    STAGES,SESSION_SCHEMA_VERSION,SESSION_REF,", 1)
    victim = tmp_path / "clashing-adaptive.js"
    victim.write_text(clashing, encoding="utf-8")
    completed = subprocess.run(
        [node, "-e", f"require({json.dumps(str(CONTRACTS))});require({json.dumps(str(victim))})"],
        capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
    assert completed.returncode != 0
    assert "recouvre le contrat : STAGES" in completed.stderr


def test_the_adaptive_marker_sits_immediately_after_the_contract_marker():
    """Survivant B3 (QA Slice 10) : « juste après » veut dire **immédiatement** :
    entre les deux repères il n'y a qu'un commentaire, aucun autre module."""

    import re as _re

    from jarvis.runtime.control_center import BAREHANDS_ADAPTIVE_SCRIPT_MARKER, BAREHANDS_CONTRACTS_SCRIPT_MARKER

    raw = (RUNTIME / "control_center.html").read_text(encoding="utf-8")
    start = raw.index(BAREHANDS_CONTRACTS_SCRIPT_MARKER) + len(BAREHANDS_CONTRACTS_SCRIPT_MARKER)
    between = raw[start:raw.index(BAREHANDS_ADAPTIVE_SCRIPT_MARKER)]
    assert _re.sub(r"/\*.*?\*/", "", between, flags=_re.S).strip() == ""
