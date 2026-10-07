"""Le module de page du rechargement a chaud, par node (jarvis-interactive-presentation-studio, Slice 06).

`control_center_presentation_studio_reload.js` est le vrai module ; seuls le DOM, l'horloge, `fetch` et `toast` sont des doubles.
Ce que ce fichier epingle : une bande VISIBLE pour chaque issue (en cours avec compteur et echeance, succes, valeurs remises a
zero nommees, enregistre sans fenetre, non confirme, refuse, annule, perime, panne de transport avec « Reessayer »), chaque
issue journalisee, aucun balisage insere depuis un texte de cadre, le contexte de l'appelant (selection, position) jamais
touche, les rapports de montage de l'hote (filtres, bornes, relances), la surveillance qui n'annonce pas l'historique, et la
parite des statuts et des routes avec Core. La preuve dans un vrai Chrome est `test_presentation_studio_reload_browser.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.domain.presentation_studio_reload import ReloadStatus
from jarvis.runtime.presentation_studio_relay import STUDIO_ROUTE
from tests.fakes.prefab_js import run_node

MODULE = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center_presentation_studio_reload.js"

BENCH = r"""
const R=require(D.module);
function env(opts){
  const o=opts||{};
  const doc=new FakeDocument(),win={},logs=[],toasts=[],calls=[];
  const c={t:0,timers:[],seq:0};
  const clk={now:()=>c.t,
    setTimeout:(fn,ms)=>{const id=++c.seq;c.timers.push({id,at:c.t+ms,fn,every:0});return id},
    clearTimeout:(id)=>{c.timers=c.timers.filter(x=>x.id!==id)},
    setInterval:(fn,ms)=>{const id=++c.seq;c.timers.push({id,at:c.t+ms,fn,every:ms});return id},
    clearInterval:(id)=>{c.timers=c.timers.filter(x=>x.id!==id)}};
  clk.advance=(ms)=>{const end=c.t+ms;for(;;){const due=c.timers.filter(x=>x.at<=end).sort((a,b)=>a.at-b.at)[0];if(!due)break;
    c.t=due.at;if(due.every){due.at+=due.every}else c.timers=c.timers.filter(x=>x!==due);due.fn()}c.t=end};
  const answers=[];
  const fetchImpl=(url,init)=>{
    calls.push({url,method:(init&&init.method)||'GET',body:init&&init.body?JSON.parse(init.body):null,signal:init&&init.signal});
    const next=answers.length>1?answers.shift():answers[0];
    return new Promise((resolve,reject)=>{
      const signal=init&&init.signal;
      if(signal)signal.addEventListener('abort',()=>{const e=new Error('aborted');e.name='AbortError';reject(e)});
      if(next==='hang')return;
      if(next instanceof Error)return reject(next);
      resolve({ok:next.status<400,status:next.status,text:()=>Promise.resolve(typeof next.body==='string'?next.body:JSON.stringify(next.body))});
    });
  };
  const console_={info:(l)=>logs.push(['info',l]),warn:(l)=>logs.push(['warn',l]),error:(l)=>logs.push(['error',l])};
  const api=R.createStudioReload({document:doc,window:win,fetch:fetchImpl,toast:(t)=>toasts.push(t),console:console_,
    now:clk.now,setTimeout:clk.setTimeout,clearTimeout:clk.clearTimeout,setInterval:clk.setInterval,clearInterval:clk.clearInterval});
  const band=()=>doc.getElementById(R.BAND_ID);
  return {api,doc,logs,toasts,calls,clk,answers,band,text:()=>{const b=band();return b?b.textContent:null}};
}
const OPTS={presentation_id:'pst_a',variant_id:'psv_b',scene_id:'pss_c',revision:4,title:'Ouverture',files:{style:'p{}'}};
const RESULT=(extra)=>Object.assign({status:'reloaded',scene_id:'pss_c',revision:6,source_revision:1,prefab:{id:'presentation-studio.p1.s1',version:2},
  previous:{id:'lab.counter',version:1},reset:null,merged:false,mounted:true},extra||{});
"""


def node(tmp_path, body):
    return run_node(tmp_path, BENCH + body, {"module": str(MODULE)})


# ------------------------------------------------------------------ parite

def test_the_statuses_and_routes_mirror_the_python_contract(tmp_path):
    result = node(tmp_path, "return {statuses:R.STATUSES,route:R.ROUTE,report:R.REPORT_ROUTE,prefix:R.STUDIO_PREFIX,"
                            "timeout:R.EDIT_TIMEOUT_MS};")
    assert result["statuses"] == [status.value for status in ReloadStatus]
    assert result["route"] == STUDIO_ROUTE and result["report"] == STUDIO_ROUTE + "/mount-reports"
    assert result["prefix"] == "presentation-studio." and result["timeout"] > 45_000     # longer than the relay's own wait


# ------------------------------------------------------------------ rapports de montage

def test_only_studio_sources_are_reported_with_a_bounded_body_and_a_short_reason(tmp_path):
    result = node(tmp_path, r"""
      const e=env();e.answers.push({status:200,body:{matched:true,waiting:1,resolved:0}});
      const ignored=await e.api.hostOutcome({object_id:'o1',prefab:{id:'jarvis.checklist',version:1},outcome:'mounted'});
      const bogus=await e.api.hostOutcome({object_id:'o1',prefab:{id:'presentation-studio.p.s',version:1},outcome:'exploded'});
      const ok=await e.api.hostOutcome({object_id:'o1',prefab:{id:'presentation-studio.p.s',version:3},outcome:'mounted',reason:'x',message:'ignored'});
      const bad=await e.api.hostOutcome({object_id:'o2',prefab:{id:'presentation-studio.p.s',version:4},outcome:'failed',
        reason:'Not A Code',message:'Boom\n<img src=x onerror=alert(1)>'+'x'.repeat(600)});
      return {ignored,bogus,ok,bad,calls:e.calls.map(c=>[c.url,c.method,c.body]),logs:e.logs.map(l=>l[1].split(' ')[1])};
    """)
    assert result["ignored"] is None and result["bogus"] is None
    assert [call[0] for call in result["calls"]] == [STUDIO_ROUTE + "/mount-reports"] * 2
    assert result["calls"][0][2] == {"object_id": "o1", "prefab": {"id": "presentation-studio.p.s", "version": 3}, "outcome": "mounted"}
    failed = result["calls"][1][2]
    assert failed["reason"] == "error" and "\n" not in failed["message"] and len(failed["message"]) <= 300
    assert result["logs"] == ["mount_reported", "mount_reported"]


def test_a_lost_report_is_retried_then_said_out_loud_and_a_refusal_is_final(tmp_path):
    result = node(tmp_path, r"""
      const e=env();
      e.answers.push({status:503,body:{error:{code:'core_unreachable',message:'down'}}},{status:503,body:{error:{code:'core_unreachable',message:'down'}}},
                     {status:200,body:{matched:true}});
      const pending=e.api.hostOutcome({object_id:'o1',prefab:{id:'presentation-studio.p.s',version:1},outcome:'mounted'});
      for(let i=0;i<6;i++){await flush();e.clk.advance(1000)}
      const recovered=await pending;
      const attemptsOk=e.calls.length;
      e.calls.length=0;e.answers.length=0;
      e.answers.push({status:503,body:{error:{code:'core_unreachable',message:'down'}}});
      const lost=e.api.hostOutcome({object_id:'o1',prefab:{id:'presentation-studio.p.s',version:2},outcome:'failed',reason:'frame',message:'x'});
      for(let i=0;i<8;i++){await flush();e.clk.advance(1000)}
      const gone=await lost;
      const attemptsLost=e.calls.length;
      e.calls.length=0;e.answers.length=0;
      e.answers.push({status:400,body:{error:{code:'presentation_studio_invalid',message:'bad'}}});
      const refused=e.api.hostOutcome({object_id:'o1',prefab:{id:'presentation-studio.p.s',version:3},outcome:'mounted'});
      for(let i=0;i<3;i++){await flush();e.clk.advance(1000)}
      await refused;
      return {recovered,attemptsOk,gone,attemptsLost,attemptsRefused:e.calls.length,toasts:e.toasts.map(t=>t.title),
              errors:e.logs.filter(l=>l[0]==='error').map(l=>l[1].split(' ')[1]),state:e.api.state().counters};
    """)
    assert result["recovered"] == {"matched": True} and result["attemptsOk"] == 3
    assert result["gone"] is None and result["attemptsLost"] == 3 and result["attemptsRefused"] == 1
    assert result["toasts"] == ["Rapport de montage non envoyé"] * 2
    assert result["errors"] == ["mount_report_unsent"] * 2
    assert result["state"]["reportsSent"] == 1 and result["state"]["reportsFailed"] == 2


# ------------------------------------------------------------------ edition : progression visible

def test_a_running_edit_shows_motion_a_live_counter_and_a_way_out_then_the_result(tmp_path):
    result = node(tmp_path, r"""
      const e=env();e.answers.push('hang');
      const state={revision:4,selection:{scene_id:'pss_c',control_id:'headline'},position:{item_id:'psi_1'}};
      const run=e.api.applySourceEdit(Object.assign({},OPTS,{state}));
      await flush();
      const first=e.text();const band=e.band();
      const shape={role:band.getAttribute('role'),phase:band.getAttribute('data-phase'),kind:band.getAttribute('data-kind'),
        spinner:band.descendants().some(n=>n.classList.contains('jvsr-spin')),
        buttons:band.descendants().filter(n=>n.tagName==='BUTTON').map(n=>n.textContent)};
      e.clk.advance(7000);const later=e.text();
      e.answers.length=0;
      return {first,later,shape,body:e.calls[0].body,url:e.calls[0].url,busy:e.api.state().busy,state};
    """)
    assert "Rechargement de « Ouverture »…" in result["first"] and "0 s / 50 s" in result["first"]
    assert "7 s / 50 s" in result["later"]                                      # the counter moves on its own
    assert result["shape"] == {"role": "status", "phase": "running", "kind": "info", "spinner": True,
                               "buttons": ["Arrêter d'attendre"]}
    assert result["body"] == {"actor": "user", "basis": {"variant_revision": 4}, "scene_id": "pss_c", "files": {"style": "p{}"}}
    assert result["url"] == STUDIO_ROUTE + "/pst_a/variants/psv_b/source-edits" and result["busy"] is True
    assert result["state"]["selection"] == {"scene_id": "pss_c", "control_id": "headline"}   # untouched while running


@pytest.mark.parametrize(("status", "kind", "role", "needles", "persistent"), [
    ("reloaded", "ok", "status", ("rechargée", "montage confirmé", "reste de la présentation"), False),
    ("repinned", "info", "status", ("Version enregistrée", "prochaine projection"), True),
    ("pending_mount", "warn", "alert", ("montage non confirmé", "repli"), True),
    ("refused_validation", "bad", "alert", ("refusée avant publication", "Rien n'a changé"), True),
    ("rolled_back", "bad", "alert", ("annulée", "dernière version valide"), True),
    ("stale", "warn", "alert", ("changé entre-temps", "Relis-la"), True)])
def test_every_outcome_has_its_own_visible_band_and_a_journal_line(tmp_path, status, kind, role, needles, persistent):
    result = node(tmp_path, r"""
      const e=env();
      const result=RESULT({status:D_STATUS,message:'detail from Core',code:'presentation_studio_mount_failed',reason:'frame'});
      e.answers.push({status:200,body:result});
      const state={revision:4,selection:{control_id:'headline'}};
      const got=await e.api.applySourceEdit(Object.assign({},OPTS,{state}));
      const band=e.band();
      const out={got:got.status,role:band.getAttribute('role'),kind:band.getAttribute('data-kind'),phase:band.getAttribute('data-phase'),
        text:e.text(),state,toasts:e.toasts.map(t=>t.kind),logs:e.logs.map(l=>[l[0],l[1].split(' ')[1]])};
      e.clk.advance(5900);out.stillThere=!!e.band();
      e.clk.advance(200);out.afterSix=!!e.band();
      return out;
    """.replace("D_STATUS", f"'{status}'"))
    assert result["got"] == status and result["role"] == role and result["kind"] == kind and result["phase"] == "done"
    for needle in needles:
        assert needle in result["text"], (needle, result["text"])
    assert result["state"] == {"revision": 6, "selection": {"control_id": "headline"}}   # revision follows, nothing else moves
    assert ("detail from Core" in result["text"]) == (status in ("pending_mount", "refused_validation", "rolled_back", "stale"))
    assert result["stillThere"] is True and result["afterSix"] is persistent
    assert ["started", "result"] == [line[1] for line in result["logs"]]       # the normal path is logged, not only failures
    level = {"ok": "info", "info": "info", "warn": "warn", "bad": "error"}[kind]
    assert result["logs"][0][0] == "info" and result["logs"][1][0] == level
    assert result["toasts"] == ([] if kind in ("ok", "info") else [kind])


def test_a_state_reset_names_what_was_dropped_and_never_a_value(tmp_path):
    result = node(tmp_path, r"""
      const e=env();
      e.answers.push({status:200,body:RESULT({status:'reloaded_state_reset',reset:{props:['mode'],data:['count','__proto__'],controls:['start_count'],
        anchors:['reveal'],runtime_values:true}})});
      await e.api.applySourceEdit(OPTS);
      const items=e.band().descendants().filter(n=>n.tagName==='LI').map(n=>n.textContent);
      return {items,title:e.band().descendants().find(n=>n.classList.contains('jvsr-title')).textContent,
              kind:e.band().getAttribute('data-kind'),role:e.band().getAttribute('role'),log:e.logs[1][1]};
    """)
    assert result["items"] == ["Valeurs retirées : props.mode, data.count, data.__proto__", "Contrôles retirés : start_count",
                               "Ancres déliées : reveal", "Valeurs vivantes du cadre remises aux valeurs de la scène"]
    assert "remises à zéro" in result["title"] and result["kind"] == "warn" and result["role"] == "alert"
    assert '"props":1,"data":2,"controls":1,"anchors":1,"runtime":true' in result["log"]       # counts in the log, no names


def test_text_from_a_frame_or_a_title_is_never_inserted_as_markup(tmp_path):
    result = node(tmp_path, r"""
      const e=env();
      e.answers.push({status:200,body:RESULT({status:'rolled_back',message:'<img src=x onerror=alert(1)>',reason:'frame'})});
      await e.api.applySourceEdit(Object.assign({},OPTS,{title:'<script>alert(1)</script>'}));
      const band=e.band();
      return {tags:band.descendants().map(n=>n.tagName),text:e.text()};
    """)
    assert set(result["tags"]) <= {"SPAN", "BUTTON", "DIV", "UL", "LI"} and "<img" in result["text"] and "<script>" in result["text"]


# ------------------------------------------------------------------ edition : pannes

def test_a_transport_failure_is_shown_with_its_real_cause_logged_and_can_be_retried(tmp_path):
    result = node(tmp_path, r"""
      const e=env();
      e.answers.push(new Error('Failed to fetch'),{status:200,body:RESULT()});
      let thrown=null;
      try{await e.api.applySourceEdit(OPTS)}catch(error){thrown=[error.name,error.code,error.message]}
      const band=e.band();
      const buttons=band.descendants().filter(n=>n.tagName==='BUTTON');
      const shown={text:e.text(),role:band.getAttribute('role'),labels:buttons.map(b=>b.textContent),busy:e.api.state().busy};
      buttons.find(b=>b.textContent==='Réessayer').click();
      await flush(10);
      return {thrown,shown,after:e.band().getAttribute('data-kind'),calls:e.calls.length,
              logs:e.logs.map(l=>[l[0],l[1].split(' ')[1]]),toasts:e.toasts.map(t=>t.kind)};
    """)
    assert result["thrown"] == ["StudioReloadError", "unreachable", "Failed to fetch"]
    assert "Failed to fetch" in result["shown"]["text"] and "unreachable" in result["shown"]["text"]
    assert result["shown"]["role"] == "alert" and result["shown"]["labels"] == ["Réessayer", "Fermer"] and result["shown"]["busy"] is False
    assert result["after"] == "ok" and result["calls"] == 2
    assert ["error", "failed"] in result["logs"] and result["toasts"] == ["bad"]


def test_a_coded_envelope_from_core_is_the_message_not_a_generic_failure(tmp_path):
    result = node(tmp_path, r"""
      const e=env();
      e.answers.push({status:404,body:{error:{code:'presentation_studio_unknown_scene',message:'pss_c is not a scene of this variant'}}});
      let thrown=null;
      try{await e.api.applySourceEdit(OPTS)}catch(error){thrown=[error.code,error.status,error.message]}
      return {thrown,text:e.text()};
    """)
    assert result["thrown"] == ["presentation_studio_unknown_scene", 404, "pss_c is not a scene of this variant"]
    assert "presentation_studio_unknown_scene" in result["text"] and "pss_c is not a scene" in result["text"]


def test_an_edit_that_never_answers_ends_at_its_deadline_and_the_ui_is_released(tmp_path):
    result = node(tmp_path, r"""
      const e=env();e.answers.push('hang');
      const run=e.api.applySourceEdit(OPTS).catch((error)=>[error.code,error.message]);
      await flush();
      e.clk.advance(R.EDIT_TIMEOUT_MS+10);
      const thrown=await run;
      return {thrown,busy:e.api.state().busy,text:e.text(),timers:e.clk.advance(0)||0};
    """)
    assert result["thrown"][0] == "timeout" and "50 s" in result["thrown"][1] and "côté serveur" in result["thrown"][1]
    assert result["busy"] is False and "timeout" in result["text"]


def test_the_wait_can_be_stopped_by_the_user_and_says_the_edit_may_still_land(tmp_path):
    result = node(tmp_path, r"""
      const e=env();e.answers.push('hang');
      const run=e.api.applySourceEdit(OPTS).catch((error)=>[error.code,error.message]);
      await flush();
      e.band().descendants().find(n=>n.tagName==='BUTTON').click();
      const thrown=await run;
      return {thrown,busy:e.api.state().busy};
    """)
    assert result["thrown"][0] == "cancelled" and "peut encore aboutir" in result["thrown"][1] and result["busy"] is False


def test_a_second_edit_while_one_runs_is_refused_visibly_and_not_sent(tmp_path):
    result = node(tmp_path, r"""
      const e=env();e.answers.push('hang');
      const first=e.api.applySourceEdit(OPTS).catch(()=>null);
      await flush();
      let second=null;
      try{await e.api.applySourceEdit(OPTS)}catch(error){second=error.code}
      return {second,calls:e.calls.length,text:e.text(),kind:e.band().getAttribute('data-kind')};
    """)
    assert result["second"] == "busy" and result["calls"] == 1 and "déjà en cours" in result["text"] and result["kind"] == "warn"


@pytest.mark.parametrize("patch", [{"presentation_id": ""}, {"revision": 0}, {"revision": "4"}, {"files": {}}, {"files": []}])
def test_an_incomplete_request_is_refused_before_any_network_call(tmp_path, patch):
    result = node(tmp_path, r"""
      const e=env();
      let code=null;
      try{await e.api.applySourceEdit(Object.assign({},OPTS,PATCH))}catch(error){code=error.code}
      return {code,calls:e.calls.length,text:e.text()};
    """.replace("PATCH", __import__("json").dumps(patch)))
    assert result["code"] == "invalid_request" and result["calls"] == 0 and "requête incomplète" in result["text"]


def test_state_reset_is_only_sent_when_the_caller_allowed_it(tmp_path):
    result = node(tmp_path, r"""
      const e=env();e.answers.push({status:200,body:RESULT()});
      await e.api.applySourceEdit(Object.assign({},OPTS,{allow_state_reset:true,request_id:'psq_0123456789ab'}));
      await e.api.applySourceEdit(Object.assign({},OPTS,{allow_state_reset:'yes'}));
      return e.calls.map(c=>[c.body.allow_state_reset,c.body.request_id]);
    """)
    assert result == [[True, "psq_0123456789ab"], [None, None]]


# ------------------------------------------------------------------ surveillance

def test_the_watch_primes_on_the_history_then_announces_only_what_is_new(tmp_path):
    result = node(tmp_path, r"""
      const e=env();
      const row=(status,rev,extra)=>Object.assign({presentation_id:'pst_a',variant_id:'psv_b',scene_id:'pss_c',status,source_revision:rev,prefab:{id:'a.b',version:1}},extra||{});
      e.answers.push({status:200,body:{reloads:[row('rolled_back',1,{message:'old'})]}});
      const poll=e.api.watch('pst_a',{intervalMs:100});
      await flush();
      const primed=e.band();
      e.answers.length=0;
      e.answers.push({status:200,body:{reloads:[row('rolled_back',1,{message:'old'}),row('rolled_back',3,{message:'late failure',late:true})]}});
      e.clk.advance(100);await flush(8);
      const shown=e.text();
      const once=e.logs.filter(l=>l[1].includes(' result ')).length;
      e.clk.advance(100);await flush(8);
      const again=e.logs.filter(l=>l[1].includes(' result ')).length;
      e.api.stopWatching();
      return {primed:!!primed,shown,once,again,state:e.api.state().watching};
    """)
    assert result["primed"] is False                       # the history is not announced
    assert "annulée" in result["shown"] and "late failure" in result["shown"]
    assert result["once"] == 1 and result["again"] == 1 and result["state"] is False


def test_a_watch_that_cannot_reach_core_says_so_once_and_recovers_quietly(tmp_path):
    result = node(tmp_path, r"""
      const e=env();
      e.answers.push(new Error('Failed to fetch'));
      e.api.watch('pst_a',{intervalMs:100});
      await flush(8);
      for(let i=0;i<3;i++){e.clk.advance(100);await flush(8)}
      const toasts=e.toasts.map(t=>t.title);
      e.answers.length=0;e.answers.push({status:200,body:{reloads:[]}});
      e.clk.advance(100);await flush(8);
      e.api.stopWatching();
      return {toasts,logs:e.logs.map(l=>l[1].split(' ')[1])};
    """)
    assert result["toasts"] == ["Suivi des rechargements interrompu"]
    assert result["logs"].count("watch_failed") == 4 and result["logs"][-1] == "watch_recovered"
