"""Module JavaScript de la carte « Présentations · moteur » (Slice 20) : logique pure exécutée par node, et la page servie.

Le rendu et le flux de confirmation dans un vrai Chrome : `test_control_center_presentation_studio_engine_browser.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.runtime.control_center import STUDIO_ENGINE_SCRIPT_MARKER
from tests.unit.test_control_center_mcp_plugins_api import RecordingCore, _center

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "jarvis" / "runtime" / "control_center_presentation_studio_engine.js"
PAGE = ROOT / "jarvis" / "runtime" / "control_center.html"


def run_node(tmp_path: Path, source: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "sve-test.cjs"
    script.write_text(f"const C=require({json.dumps(str(MODULE))});const out=v=>process.stdout.write(JSON.stringify(v));\n"
                      "(async()=>{" + source + "})().then(v=>out(v===undefined?null:v)).catch(e=>{process.stderr.write(String(e&&e.stack||e));process.exit(1)});",
                      encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def diagnose(tmp_path, remotion, capability=None):
    return run_node(tmp_path, f"return C.diagnose({json.dumps(remotion)},{json.dumps(capability)});")


NOT_READY = {"ready": False, "reason": "the Remotion capability is not_installed; install or repair it", "repair": "install it"}


def test_a_ready_remotion_has_no_diagnosis(tmp_path):
    assert diagnose(tmp_path, {"ready": True, "reason": "", "repair": ""}) is None
    assert diagnose(tmp_path, None) is None


def test_every_failure_kind_has_its_own_guidance_and_only_the_repairable_ones_offer_a_button(tmp_path):
    missing = diagnose(tmp_path, NOT_READY, {"status": "not_installed"})
    assert missing["kind"] == "runtime_missing" and missing["action"] == "install" and "270 Mo" in missing["steps"][0]
    broken = diagnose(tmp_path, NOT_READY, {"status": "repair_needed", "last_error_code": "local_capability_health_failed"})
    assert broken["kind"] == "runtime_broken" and broken["action"] == "repair" and "refait depuis le verrou" in broken["steps"][0]
    failed = diagnose(tmp_path, NOT_READY, {"status": "install_failed", "last_error_code": "local_capability_install_offline",
                                           "last_error_detail": "offline: registry"})
    assert failed["action"] == "repair" and "réseau" in failed["steps"][0] and failed["detail"] == "offline: registry"
    sandbox = diagnose(tmp_path, {"ready": False, "reason": "the Remotion sandbox settings are invalid: port",
                                  "repair": "fix the Remotion sandbox settings (JARVIS_REMOTION_SANDBOX_HOST / JARVIS_REMOTION_SANDBOX_PORT) and restart Core"},
                       {"status": "ready"})
    assert sandbox["kind"] == "sandbox_settings" and sandbox["action"] is None and "Redémarrez Core vous-même" in sandbox["steps"][1]
    adapter = diagnose(tmp_path, {"ready": False, "reason": "this Core has no Remotion adapter (no local capability store is wired)", "repair": "x"})
    assert adapter["kind"] == "no_adapter" and adapter["action"] is None
    disabled = diagnose(tmp_path, NOT_READY, {"status": "disabled"})
    assert disabled["kind"] == "disabled" and disabled["action"] is None
    unknown = diagnose(tmp_path, {"ready": False, "reason": "strange", "repair": "do the thing"})
    assert unknown["kind"] == "unknown" and unknown["reason"] == "strange" and unknown["action"] is None
    for item in (missing, broken, failed, sandbox, adapter, disabled, unknown):
        assert item["reason"], "the adapter's real reason is always carried"


def test_the_diagnosis_never_proposes_slidecar_anywhere_in_the_module():
    text = MODULE.read_text(encoding="utf-8")
    body = text[text.index("function diagnose"):text.index("function engineBadge")]
    assert "slidecar" not in body.lower().replace("aucune présentation slidecar", "")


def test_the_view_model_badges_counts_and_the_installing_counter(tmp_path):
    state = {"engine": {"default_engine": "remotion", "engines": {"remotion": {"ready": False, "reason": "r", "repair": "x"},
                                                                    "slidecar": {"ready": True, "reason": "", "repair": ""}},
                        "slidecar": {"events": [{"kind": "slidecar_created", "at": "t", "actor": "human", "reason": "why", "presentation_id": "pst_abcdefabcdef"}],
                                     "total": 4, "kept": 1}},
             "presentations": [{"presentation_id": "a", "title": "A", "engine": "remotion", "variant_count": 1, "revision": 1},
                               {"presentation_id": "b", "title": "B", "engine": "slidecar", "variant_count": 2, "revision": 5}],
             "capability": {"status": "installing", "updated_at": 100}, "repairStartedAt": 190_000}
    model = run_node(tmp_path, f"return C.viewModel({json.dumps(state)},200000);")
    assert model["remotion"]["label"] == "Indisponible" and model["remotion"]["tone"] == "bad"
    assert [(r["engine"], r["badge"]["label"], r["canCopy"]) for r in model["rows"]] == [
        ("remotion", "Remotion", True), ("slidecar", "Slidecar · expérimental", False)]
    assert model["slidecarCount"] == 1 and model["eventsTotal"] == 4
    assert "acteur : vous" in model["events"][0]["line"] and "raison : why" in model["events"][0]["line"] and "Création" in model["events"][0]["line"]
    assert "10 s écoulées" in model["repair"]["text"] and "15 min au plus" in model["repair"]["text"]
    assert model["diagnosis"]["kind"] == "installing"


def test_the_confirmations_say_the_risk_the_journal_and_the_untouched_source(tmp_path):
    new = run_node(tmp_path, "return C.confirmSlidecar('new');")
    copy = run_node(tmp_path, "return C.confirmSlidecar('copy','Plan');")
    assert new["danger"] is True and "expérimental" in new["title"] and any("Aucun repli" in line[1] for line in new["lines"])
    assert any("journal" in line[1] for line in new["lines"]) and not any(line[0] == "Nouveau document : " for line in new["lines"])
    assert "Plan" in dict(copy["lines"])["Nouveau document : "] and "pas modifiée" in dict(copy["lines"])["Nouveau document : "]
    repair = run_node(tmp_path, "return [C.confirmRepair('install'),C.confirmRepair('repair')];")
    assert "Installer" in repair[0]["confirmLabel"] and "Réparer" in repair[1]["confirmLabel"]
    assert all(any("Aucun repli" in line[0] for line in spec["lines"]) for spec in repair)


def test_the_client_sends_only_the_title_for_remotion_and_never_an_actor(tmp_path):
    sent = run_node(tmp_path, """
      const calls=[];
      const fetchImpl=async(path,options)=>{calls.push({path,method:options.method,body:options.body?JSON.parse(options.body):null});
        return {ok:true,json:async()=>({presentation:{},capability:{status:'ready'}})}};
      const client=C.createClient({fetchImpl});
      await client.create({title:'Plan'});
      await client.create({title:'Essai',slidecar:true,reason:'comparer'});
      await client.create({title:'Essai2',slidecar:true});
      await client.experiment('pst_1','pourquoi');
      await client.experiment('pst_1');
      await client.repair('repair');
      let refused=null;try{client.repair('uninstall')}catch(e){refused=e.message}
      return {calls,refused};""")
    bodies = [(c["method"], c["path"], c["body"]) for c in sent["calls"]]
    assert bodies == [
        ("POST", "/api/presentation-studio/presentations", {"title": "Plan"}),
        ("POST", "/api/presentation-studio/presentations", {"title": "Essai", "engine": "slidecar", "experimental_confirmed": True, "reason": "comparer"}),
        ("POST", "/api/presentation-studio/presentations", {"title": "Essai2", "engine": "slidecar", "experimental_confirmed": True}),
        ("POST", "/api/presentation-studio/presentations/pst_1/experiment", {"experimental_confirmed": True, "reason": "pourquoi"}),
        ("POST", "/api/presentation-studio/presentations/pst_1/experiment", {"experimental_confirmed": True}),
        ("POST", "/api/local-capabilities/remotion/repair", {})]
    assert sent["refused"] == "unknown capability operation"
    assert not any("actor" in (c["body"] or {}) for c in sent["calls"])


def test_a_failed_write_keeps_the_real_cause_and_a_timeout_says_the_outcome_is_unknown(tmp_path):
    result = run_node(tmp_path, """
      const fail=async()=>({ok:false,status:403,json:async()=>({error:{code:'presentation_studio_engine_selection_refused',message:'only a person can choose'}})});
      const client=C.createClient({fetchImpl:fail});
      let first=null;try{await client.create({title:'x',slidecar:true})}catch(e){first={code:e.code,status:e.status,text:C.errorText(e.code,e.message)}}
      const abort=async()=>{const e=new Error('a');e.name='AbortError';throw e};
      let second=null;try{await C.createClient({fetchImpl:abort}).list()}catch(e){second={code:e.code,text:C.errorText(e.code,e.message)}}
      return {first,second,invalid:C.errorText('presentation_studio_invalid','slidecar is experimental'),unknown:C.errorText('weird','real cause')};""")
    assert result["first"]["code"] == "presentation_studio_engine_selection_refused" and "Seul vous" in result["first"]["text"]
    assert result["second"]["code"] == "timeout" and "issue est inconnue" in result["second"]["text"]
    assert result["invalid"].endswith("slidecar is experimental") and result["unknown"] == "real cause"


def test_the_browser_block_is_defensive_and_wired_to_the_visible_contract():
    text = MODULE.read_text(encoding="utf-8")
    browser = text[text.index("installJarvisStudioEngine"):]
    # waiting is visible with a counter, a failed action is logged and shown, the busy state is released in `finally`
    assert "%%ACTIVITY%%" in browser and "fmtDuration((now-S.busySince)/1000)" in browser and "role=\"alert\"" in browser
    assert "finally{S.busy='';S.busySince=0}" in browser and "log('error','action_failed'" in browser
    # every creation of an experiment goes through the confirmation first
    assert browser.index("askConfirmation(C.confirmSlidecar('new'))") < browser.index("client.create({title,slidecar:true")
    assert browser.index("askConfirmation(C.confirmSlidecar('copy'") < browser.index("client.experiment(")
    assert browser.index("askConfirmation(C.confirmRepair(") < browser.index("client.repair(diagnosis.action)")
    assert "S.rendered=''" in browser and "if(html===S.rendered)" in browser


async def test_the_served_page_carries_the_module_and_the_container_above_the_remotion_card(tmp_path):
    assert STUDIO_ENGINE_SCRIPT_MARKER in PAGE.read_text(encoding="utf-8")
    client = TestClient(TestServer(_center(tmp_path, RecordingCore())._app))
    await client.start_server()
    try:
        served = await (await client.get("/")).text()
    finally:
        await client.close()
    assert STUDIO_ENGINE_SCRIPT_MARKER not in served and "JarvisStudioEngineCore" in served
    assert served.index('id="sveCard"') < served.index('id="rmsCard"') < served.index('id="mcppBody"')
    assert served.index('id="sveCard"') > served.index('id="mcpPlugins"')


def test_adapter_reasons_are_translated_and_unknown_ones_stay_as_they_are(tmp_path):
    out = run_node(tmp_path, """return ['the Remotion capability is not_installed; install it','the Remotion capability is repair_needed (x)',
      'this Core has no Remotion adapter (no local capability store is wired)','this Core has no Remotion sandbox listener configured',
      'the Remotion sandbox settings are invalid: port','something new'].map(C.frenchReason);""")
    assert out[0].startswith("la capacité Remotion est non installée") and "à réparer" in out[1]
    assert "adaptateur" in out[2] and "écouteur" in out[3] and "invalides" in out[4] and out[5] == "something new"


def test_unreadable_documents_reach_the_view_model_and_are_not_dropped(tmp_path):
    model = run_node(tmp_path, """return C.viewModel({engine:null,presentations:[],problems:[{presentation_id:'pst_x',code:'presentation_studio_corrupt_document',message:'m'}]},0);""")
    assert model["problems"] == [{"id": "pst_x", "code": "presentation_studio_corrupt_document", "message": "m"}]
