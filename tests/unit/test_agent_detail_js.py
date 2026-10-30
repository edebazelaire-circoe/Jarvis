"""Public agent-detail whitelist, exact identities and bounded reader lifecycle."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess

import pytest


MODULE = Path(__file__).resolve().parents[2] / "jarvis/runtime/control_center_agent_detail.js"
START = "2026-10-30T09:00:00Z"
END = "2026-10-30T09:02:00Z"
REG = "jart_" + "a" * 32
BASE = {
    "object": {"object_id": "parent-scene", "kind": "agent", "work_ref": {"source": "claude", "external_id": "parent", "work_id": "brain-1"},
               "role_ref": {"role_id": "research", "instance_id": "inst-1", "mission_id": "mission-1"}, "payload": {"title": "Recherche"}},
    "work": {"source": "core", "core_reachable": True, "store_id": "store-1", "revision": 2, "items": [
        {"source": "claude", "external_id": "parent", "work_id": "brain-1", "status": "running", "role_id": "research", "label": "Comparer les écrans",
         "activity": "Lecture des caractéristiques", "summary": "Deux modèles retenus", "started_at": START, "ended_at": None, "progress_fraction": .5, "tokens": 123, "tool_uses": 4},
        {"source": "claude", "external_id": "child", "parent_external_id": "parent", "status": "completed", "label": "Comparer les prix", "summary": "Prix vérifiés",
         "started_at": START, "ended_at": END, "progress_fraction": 1},
    ]},
    "instance": {"instance_id": "inst-1", "work_source": "claude", "work_external_id": "parent", "mission_id": "mission-1", "role_id": "research"},
    "tree": {"root_mission_id": "mission-1", "missions": [{"mission_id": "mission-1", "objective": "Trouver un écran adapté"}], "instances": [
        {"instance_id": "inst-1", "work_source": "claude", "work_external_id": "parent", "mission_id": "mission-1", "role_id": "research"},
        {"instance_id": "inst-2", "parent_instance_id": "inst-1", "work_source": "claude", "work_external_id": "child", "mission_id": "mission-1", "role_id": "research"},
    ]},
    "scene": {"objects": [
        {"object_id": "art", "kind": "artifact", "payload": {"title": "Comparatif", "registry_artifact_id": REG}},
        {"object_id": "lookalike", "kind": "artifact", "payload": {"title": "Comparatif", "registry_artifact_id": "jart_" + "b" * 32}},
    ], "relations": [{"relation_id": "explain", "kind": "explains", "from_id": "art", "to_id": "parent-scene"}]},
}


def run_js(tmp_path, body, data=None):
    node = shutil.which("node")
    if not node:
        pytest.skip("node absent")
    data_path = tmp_path / "agent-detail.json"
    script = tmp_path / "agent-detail.cjs"
    data_path.write_text(json.dumps(BASE if data is None else data), encoding="utf-8")
    script.write_text(
        f"const A=require({json.dumps(str(MODULE))});const D=JSON.parse(require('fs').readFileSync({json.dumps(str(data_path))},'utf8'));\n"
        "if(D.scene)D.scene={objects:new Map(D.scene.objects.map(o=>[o.object_id,o])),relations:new Map(D.scene.relations.map(r=>[r.relation_id,r]))};\n"
        f"(async()=>{{{body}}})().then(r=>console.log(JSON.stringify(r))).catch(e=>{{console.error(e);process.exitCode=1}});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_running_projection_joins_public_facts_and_existing_action_descriptors(tmp_path):
    result = run_js(tmp_path, "return A.project(D)")
    assert result["status"] == "running" and result["live_unknown"] is False
    assert result["mission"] == {"mission_id": "mission-1", "objective": "Trouver un écran adapté"}
    assert result["role"] == {"role_id": "research"}
    assert result["activity"] == "Lecture des caractéristiques" and result["progress_fraction"] == .5
    assert result["started_at"] == "2026-10-30T09:00:00.000Z" and result["ended_at"] is None
    assert result["published_plan"] is None
    assert len(result["steps"]) == 1 and result["steps"][0]["status"] == "completed"
    assert result["artifacts"] == [{"object_id": "art", "artifact_id": REG, "title": "Comparatif", "relation": "explains"}]
    assert result["actions"]["stop"]["enabled"] is False and "arrêt individuel" in result["actions"]["stop"]["reason"]
    assert result["actions"]["ask"]["mode"] == "main_chat" and "claude/parent" in result["actions"]["ask"]["prefill"]


@pytest.mark.parametrize("status", ["pending", "running", "blocked", "completed", "failed", "cancelled", "interrupted"])
def test_terminal_and_active_states_come_only_from_work_state(tmp_path, status):
    data = copy.deepcopy(BASE)
    data["work"]["items"][0].update(status=status, ended_at=END if status in {"completed", "failed", "cancelled", "interrupted"} else None)
    data["instance"]["work_status"] = "failed"  # Historical join must never overwrite current truth.
    result = run_js(tmp_path, "return A.project(D)", data)
    assert result["status"] == status
    assert result["ended_at"] == ("2026-10-30T09:02:00.000Z" if data["work"]["items"][0]["ended_at"] else None)


def test_pruning_or_restart_preserves_mission_but_never_guesses_live_state_or_start_time(tmp_path):
    data = copy.deepcopy(BASE)
    data["work"].update(store_id="restarted", items=[])
    data["instance"].update(work_status="running", created_at=START, ended_at=END, progress_fraction=.9)
    result = run_js(tmp_path, "return A.project(D)", data)
    assert result["status"] == "unknown" and result["live_unknown"]
    assert result["started_at"] is result["ended_at"] is result["progress_fraction"] is None
    assert result["mission"]["objective"] == "Trouver un écran adapté"
    assert result["steps"][0]["status"] == "unknown"


def test_identity_is_source_and_external_id_not_title_and_conflicting_work_link_is_unknown(tmp_path):
    data = copy.deepcopy(BASE)
    data["work"]["items"][0]["source"] = "other"
    data["work"]["items"][1]["source"] = "other"
    data["instance"]["work_source"] = "other"
    data["object"].pop("role_ref")
    result = run_js(tmp_path, "return A.project(D)", data)
    assert result["status"] == "unknown" and result["mission"] is None and result["steps"] == []
    assert any(e["code"] == "mission_identity_conflict" for e in result["degraded"])
    data = copy.deepcopy(BASE)
    data["work"]["items"][0]["work_id"] = "another-brain-turn"
    result = run_js(tmp_path, "return A.project(D)", data)
    assert result["status"] == "unknown" and any(e["code"] == "work_identity_conflict" for e in result["degraded"])


def test_child_work_with_same_external_id_but_another_source_cannot_supply_status(tmp_path):
    data = copy.deepcopy(BASE)
    data["work"]["items"][1]["source"] = "other"
    result = run_js(tmp_path, "return A.project(D)", data)
    assert len(result["steps"]) == 1
    assert result["steps"][0]["source"] == "claude" and result["steps"][0]["status"] == "unknown"


def test_private_fields_are_omitted_and_public_text_is_bounded(tmp_path):
    data = copy.deepcopy(BASE)
    for value in (data["object"], data["work"], *data["work"]["items"], data["instance"], data["tree"], *data["tree"]["instances"], *data["tree"]["missions"]):
        value.update(prompt="PRIVATE_SENTINEL", trace={"thinking": "PRIVATE_SENTINEL"}, declaration={"raw": "PRIVATE_SENTINEL"})
    data["work"]["items"][0].update(summary="s" * 5000, activity="a" * 500, label="l" * 500, progress_fraction=2)
    result = run_js(tmp_path, "return A.project(D)", data)
    assert "PRIVATE_SENTINEL" not in json.dumps(result)
    assert len(result["summary"]) == 1000 and len(result["activity"]) == len(result["title"]) == 160
    assert result["progress_fraction"] is None


def test_job_stop_is_enabled_only_for_live_core_jobs_and_never_sends(tmp_path):
    data = copy.deepcopy(BASE)
    data["object"].update(kind="job", work_ref={"source": "job", "external_id": "parent"})
    data["work"]["items"][0]["source"] = "job"
    result = run_js(tmp_path, "return A.project(D)", data)
    assert result["actions"]["stop"] == {"enabled": True, "method": "POST", "path": "/api/jobs/cancel", "body": {"source": "job", "external_id": "parent"}, "reason": None}
    data["work"]["items"][0]["status"] = "completed"
    result = run_js(tmp_path, "return A.project(D)", data)
    assert result["actions"]["stop"]["enabled"] is False


def test_artifacts_require_canonical_relation_not_matching_titles_or_board_membership(tmp_path):
    result = run_js(tmp_path, "D.scene.relations.clear();return A.project(D)")
    assert result["artifacts"] == []
    result = run_js(tmp_path, "D.scene.relations.set('signal',{relation_id:'signal',kind:'explains',from_id:'art',to_id:'other'});return A.project(D)")
    assert len(result["artifacts"]) == 1 and result["artifacts"][0]["object_id"] == "art"


def test_reader_composes_existing_reads_and_reports_errors_without_raw_payload(tmp_path):
    result = run_js(tmp_path, """
      const calls=[],logs=[];
      const reader=A.createReader({fetchJson:async path=>{calls.push(path);if(path==='/api/work')return D.work;
        if(path.startsWith('/api/missions/work/'))return D.instance;return D.tree},log:(...row)=>logs.push(row)});
      const result=await reader.load({object:D.object,scene:D.scene});return {result,calls,logs,state:reader.snapshot()};
    """)
    assert result["calls"] == ["/api/work", "/api/missions/work/claude/parent", "/api/missions/mission-1"]
    assert result["result"]["phase"] == "ready" and result["state"]["model"]["status"] == "running"
    assert [r[1] for r in result["logs"]] == ["agent_detail.loading", "agent_detail.loaded"]


def test_reader_preserves_mission_failure_message_and_still_shows_known_work(tmp_path):
    result = run_js(tmp_path, """
      const logs=[],reader=A.createReader({fetchJson:async path=>{if(path==='/api/work')return D.work;
        throw Object.assign(new Error('Historique désactivé'),{code:'mission_history_unavailable',status:503})},log:(...r)=>logs.push(r)});
      return {result:await reader.load({object:D.object,scene:D.scene}),logs};
    """)
    assert result["result"]["phase"] == "degraded" and result["result"]["model"]["status"] == "running"
    assert any(e["message"] == "Historique désactivé" for e in result["result"]["model"]["degraded"])
    assert any(r[1] == "agent_detail.read_failed" for r in result["logs"])


def test_reader_timeout_releases_hung_transport_with_readable_retry_state(tmp_path):
    result = run_js(tmp_path, """
      const logs=[],reader=A.createReader({timeoutMs:50,fetchJson:()=>new Promise(()=>{}),log:(...r)=>logs.push(r)});
      const result=await reader.load({object:D.object,scene:D.scene});return {result,logs};
    """)
    assert result["result"]["phase"] == "error" and result["result"]["error"]["code"] == "agent_detail_timeout"
    assert "Réessayez" in result["result"]["error"]["message"]
    assert any(r[0] == "error" and r[1] == "agent_detail.failed" for r in result["logs"])


def test_cancel_and_new_identity_discard_late_responses_without_followup_reads(tmp_path):
    result = run_js(tmp_path, """
      let release;const calls=[],reader=A.createReader({fetchJson:path=>{calls.push(path);if(path==='/api/work')return Promise.resolve(D.work);
        if(path.endsWith('/parent'))return new Promise(r=>{release=r});return Promise.resolve({instance_id:'i-other',work_source:'claude',work_external_id:'other'})},log:()=>{}});
      const first=reader.load({object:D.object,scene:D.scene});await Promise.resolve();
      const object={...D.object,object_id:'other-scene',role_ref:null,work_ref:{source:'claude',external_id:'other'}};
      const second=await reader.load({object,scene:D.scene});release(D.instance);await new Promise(r=>setTimeout(r,10));
      const old=await first;return {old,second,state:reader.snapshot(),calls};
    """)
    assert result["old"] is None
    assert result["state"]["model"]["object_id"] == "other-scene"
    assert "/api/missions/mission-1" not in result["calls"]


def test_foreign_snapshot_and_oversized_public_schema_degrade_to_unknown(tmp_path):
    result = run_js(tmp_path, "D.work.source='tracker';return A.project(D)")
    assert result["status"] == "unknown"
    result = run_js(tmp_path, "D.work.items=Array.from({length:65},()=>D.work.items[0]);return A.project(D)")
    assert result["status"] == "unknown"
    result = run_js(tmp_path, "D.tree.instances=Array.from({length:1025},()=>D.instance);return A.project(D)")
    assert any(e["code"] == "mission_payload_invalid" for e in result["degraded"])


def test_children_findings_and_artifacts_are_bounded_with_explicit_truncation(tmp_path):
    result = run_js(tmp_path, """
      D.work.items=[D.work.items[0],...Array.from({length:63},(_,i)=>({source:'claude',external_id:'child'+i,parent_external_id:'parent',status:'completed',label:'Enfant '+i,summary:'Résumé '+i}))];
      D.tree.instances=[];
      for(let i=0;i<30;i++){const object_id='art'+i;D.scene.objects.set(object_id,{object_id,kind:'artifact',payload:{title:'Artefact '+i}});
        D.scene.relations.set('link'+i,{relation_id:'link'+i,kind:'explains',from_id:object_id,to_id:'parent-scene'})}
      return A.project(D);
    """)
    assert len(result["steps"]) == 32 and len(result["findings"]) == 8 and len(result["artifacts"]) == 24
    assert {e["code"] for e in result["degraded"]} >= {"children_truncated", "artifacts_truncated"}


def test_missing_or_noncanonical_timestamps_and_progress_do_not_invent_runtime(tmp_path):
    result = run_js(tmp_path, "D.work.items[0].started_at='1';D.work.items[0].ended_at='later';D.work.items[0].progress_fraction='0.5';return A.project(D)")
    assert result["started_at"] is None and result["ended_at"] is None and result["progress_fraction"] is None


def test_reader_cancel_releases_pending_load_and_malformed_json_never_becomes_truth(tmp_path):
    result = run_js(tmp_path, """
      let signal;const reader=A.createReader({fetchJson:async(path,opts)=>{signal=opts.signal;return new Promise(()=>{})},log:()=>{}});
      const loading=reader.load({object:D.object});reader.cancel();const cancelled=await loading;
      const bad=A.createReader({fetchJson:async()=>[],log:()=>{}});const malformed=await bad.load({object:D.object});
      return {cancelled,aborted:signal.aborted,state:reader.snapshot(),malformed};
    """)
    assert result["cancelled"] is None and result["aborted"] is True and result["state"]["phase"] == "idle"
    assert result["malformed"]["phase"] == "degraded" and result["malformed"]["model"]["status"] == "unknown"
    assert any(e["code"] == "agent_detail_payload_invalid" for e in result["malformed"]["model"]["degraded"])
