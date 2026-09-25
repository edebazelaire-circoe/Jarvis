"""Agent de calibration, côté page (tâche adaptative Bare Hands, Slice 06, décisions 50 à 55).

Exécuté par node sur les **vrais** modules : contrats (§ 12), séance de l'agent
(`control_center_barehands_calibration_agent.js`), parcours de calibration,
canal de commandes, et la page (`control_center_barehands.js`) dans le monde
navigateur des autres tests.

Ce que ce fichier épingle :

- **traces de référence** (`tests/fixtures/barehands_calibration_traces/`) :
  hypothèse démentie (confiance baissée, ni réessai ni reproposition sans
  preuve nouvelle, alternative testée, acceptation sur accord vérifié) et
  retour ambigu (deux causes ouvertes, un essai à la fois dans les clés de sa
  cause, `inconclusive` sans effet sur la confiance) ;
- **le code chiffre** : valeur des preuves et deltas calculés par les
  fonctions du contrat, jamais recopiés ;
- **le parcours** note l'essai de chaque ligne de mesures, refait l'exercice
  joué et passe au suivant ;
- **les commandes de repli** à l'écran passent par les mêmes portes que la
  voix ; le battement de séance ; le canal de commandes ; la porte de
  `JarvisBarehands.trial` hors séance.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
CONTRACTS = RUNTIME / "control_center_barehands_contracts.js"
AGENT = RUNTIME / "control_center_barehands_calibration_agent.js"
COMMANDS = RUNTIME / "control_center_barehands_commands.js"
FIXTURES = ROOT / "tests" / "fixtures" / "barehands_calibration_traces"

from test_barehands_calibration_js import DOM, DRIVER, run_node as run_flow  # noqa: E402
from test_barehands_trial_profile_js import page, run_page  # noqa: E402


def run_node(tmp_path: Path, source: str, name: str = "agent") -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"barehands-{name}.cjs"
    script.write_text(
        f"const C=require({json.dumps(str(CONTRACTS))});\n"
        f"const A=require({json.dumps(str(AGENT))});\n"
        f"const M=require({json.dumps(str(COMMANDS))});\n"
        "const out=v=>process.stdout.write(JSON.stringify(v));\n"
        "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=40,
                          check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


#: Un monde minimal : un parcours qui tourne, un jeu de mesures qu'on remplit
#: « sous » l'essai en cours, un gestionnaire d'essai qui rend les reçus de la
#: décision 48. Le gestionnaire réel a ses propres tests
#: (`test_barehands_trial_profile_js.py`) ; ici on prouve les **règles de la
#: séance**, qui ne dépendent que de la forme de ses reçus.
WORLD = r"""
let clock=1000;
const rows={},meta={};
let running=true,concluded=false,step='pinch_primary',phase='result',moves=[];
const flow={isRunning:()=>running,stepId:()=>step,phase:()=>phase,concluded:()=>concluded,
  session:()=>({measurements:C.createMeasurementSet(rows),rowMeta:meta}),
  rerun:()=>{moves.push('rerun');return step},next:()=>{moves.push('next');return step}};
const stack=[];let serial=0;const persisted=[];
const trials={
  apply(patch){serial+=1;const trialId=`tr-${serial}`;stack.push({trialId,patch});
    return {ok:true,code:null,applied:{...patch},rejected:[],trialId,appliedAt:clock}},
  rollback(){if(!stack.length)return {ok:false,code:'barehands_trial_nothing_to_rollback',message:'Aucun essai en cours.'};
    const top=stack.pop();return {ok:true,code:null,applied:{},rejected:[],trialId:top.trialId,undone:[top.trialId],appliedAt:clock}},
  async accept(){if(!stack.length)return {ok:false,code:'barehands_trial_nothing_to_accept'};
    const accepted=Object.assign({},...stack.map(s=>s.patch));persisted.push(accepted);const trialId=stack[stack.length-1].trialId;
    stack.length=0;return {ok:true,code:null,applied:{...accepted},accepted,trialId,appliedAt:clock}},
  status(){return {active:stack.length>0,trialId:stack.length?stack[stack.length-1].trialId:null}},
  delta(){return Object.assign({},...stack.map(s=>s.patch))},
};
const values=()=>({effective:{left:{releaseMs:60,pressRatio:.2},right:{releaseMs:60,pressRatio:.3},unknown:{releaseMs:60,pressRatio:.28}},
  saved:{left:{releaseMs:60},right:{releaseMs:60},unknown:{releaseMs:60}},trial:trials.delta()});
const logs=[];
const S=A.createCalibrationAgentSession({contracts:C,flow:()=>flow,trials:()=>trials,values,now:()=>clock,
  log:(level,event,data)=>logs.push([level,event,data])});
const measure=add=>{const top=trials.status().trialId;
  for(const [ref,metrics] of Object.entries(add)){rows[ref]=metrics;meta[ref]={stage:step,exerciseRef:null,trialRef:top,at:clock}}};
const get=(o,path)=>path.split('.').reduce((v,k)=>v===undefined||v===null?undefined:v[k],o);
async function play(step_){
  clock+=1000;
  if(step_.op==='measure'){measure(step_.rows);return null}
  const p=step_.payload||{};
  return step_.op==='feedback'?S.recordFeedback(p,'voice'):step_.op==='hypothesis'?S.proposeHypothesis(p)
    :step_.op==='apply'?S.applyTrial(p):step_.op==='resolve'?S.resolveTrial(p):step_.op==='rollback'?S.rollbackTrial()
    :step_.op==='accept'?await S.acceptTrial(p,'voice'):step_.op==='status'?S.status():null;
}
"""


@pytest.mark.parametrize("fixture", ["falsified", "ambiguous"])
def test_the_reference_traces_replay_against_the_real_session(tmp_path, fixture):
    trace = json.loads((FIXTURES / f"{fixture}.json").read_text(encoding="utf-8"))
    result = run_node(tmp_path, WORLD + f"const TRACE={json.dumps(trace, ensure_ascii=False)};" + r"""
      const report=[];
      for(const [index,s] of TRACE.steps.entries()){
        const answer=await play(s);
        if(!s.expect)continue;
        const bad=[];
        for(const [path,want] of Object.entries(s.expect)){
          const got=get(answer,path);
          if(JSON.stringify(got)!==JSON.stringify(want))bad.push({path,want,got});
        }
        report.push({index,op:s.op,bad,answer:bad.length?answer:undefined});
      }
      out({report,persisted,consents:S.consents()});
    """, name=fixture)
    failures = [entry for entry in result["report"] if entry["bad"]]
    assert failures == [], json.dumps(failures, ensure_ascii=False, indent=1)[:3000]
    if fixture == "falsified":
        assert result["persisted"] == [{"releaseDeltaRatio": 0.1}], "seul l'essai accordé est rangé"
        assert result["consents"][0]["source"] == "voice" and result["consents"][0]["trialRef"] == "tr-2"
    else:
        assert result["persisted"] == [], "rien n'est rangé sans accord"


def test_outside_a_running_calibration_every_door_refuses_by_name(tmp_path):
    result = run_node(tmp_path, WORLD + r"""
      running=false;
      const answers=[S.status(),S.recordFeedback({categories:['fine'],text:'x'},'voice'),
        S.proposeHypothesis({cause:'laggy',confidence:.3,evidence:[],feedbackRefs:[]}),
        S.applyTrial({hypothesisRef:'hy-1',patch:{releaseMs:30}}),S.resolveTrial({trialRef:'tr-1',verdict:'inconclusive'}),
        S.rollbackTrial(),await S.acceptTrial({},'ui'),S.rerun(),S.next()];
      out({codes:answers.map(a=>[a.ok,a.code,a.errors[0].code]),calls:serial,moves});
    """)
    assert result["codes"] == [[False, "barehands_calibration_inactive", "barehands_calibration_inactive"]] * 9
    assert result["calls"] == 0 and result["moves"] == []


def test_status_is_bounded_numbers_come_from_the_code_and_the_ui_consent_is_the_button(tmp_path):
    result = run_node(tmp_path, WORLD + r"""
      for(let i=1;i<=40;i+=1)measure({[`ep-${i}`]:{press_latency_ms:i,release_latency_ms:null}});
      const fb=S.recordFeedback({categories:['press_missed'],text:'le clic ne passe pas'},'voice');
      const ui=S.recordFeedback({categories:['fine'],text:''},'ui');
      const voiceEmpty=S.recordFeedback({categories:['fine'],text:''},'voice');
      const tooMany=S.recordFeedback({categories:['fine','laggy'],text:'x'},'voice');
      const hy=S.proposeHypothesis({cause:'press_threshold_too_strict',confidence:.5,
        evidence:[{metric:'press_latency_ms',aggregate:'p95',sourceRefs:['ep-1','ep-2','ep-3','ep-4','ep-5']}],feedbackRefs:['fb-1']});
      const tr=S.applyTrial({hypothesisRef:'hy-1',patch:{pressFrames:1}});
      const st=S.status();
      const noConsent=await S.acceptTrial({},'voice');
      const button=await S.acceptTrial({},'ui');
      out({fb:fb.ok,ui:[ui.ok,ui.result&&ui.result.feedback.source],voiceEmpty:voiceEmpty.errors[0].code,
        tooMany:tooMany.errors[0].code,value:hy.result.evidence[0].value,expected:C.aggregateMetric('press_latency_ms','p95',['ep-1','ep-2','ep-3','ep-4','ep-5'],rows),
        tr:tr.ok,count:st.result.measurementCount,shown:st.result.measurements.length,last:st.result.measurements.slice(-1)[0],
        values:st.result.values,exercise:st.result.exercise,noConsent:noConsent.errors[0].code,
        button:[button.ok,button.result&&button.result.consent],persisted,
        size:JSON.stringify(st.result).length});
    """)
    assert result["fb"] is True and result["ui"] == [True, "ui"]
    assert result["voiceEmpty"] == "barehands_feedback_invalid", "un retour vocal garde ses mots"
    assert result["tooMany"] == "barehands_feedback_contradictory"
    assert result["value"] == result["expected"] == pytest.approx(4.8)
    assert result["count"] == 40 and result["shown"] == 24, "les 24 dernières lignes seulement"
    assert result["last"] == {"ref": "ep-40", "stage": "pinch_primary", "exerciseRef": None, "trialRef": None,
                              "metrics": {"press_latency_ms": 40, "release_latency_ms": None}}
    values = result["values"]
    assert values["effective"]["releaseMs"] == 60
    assert values["effective"]["pressRatio"] == {"left": 0.2, "right": 0.3, "unknown": 0.28}
    assert values["trial"] == {"pressFrames": 1}
    assert result["exercise"] == {"step": "pinch_primary", "phase": "result", "running": True, "finished": False}
    assert result["noConsent"] == "barehands_calibration_consent_missing"
    assert result["button"] == [True, {"source": "ui", "quote": ""}]
    assert result["persisted"] == [{"pressFrames": 1}]
    assert result["size"] < 16_384


# ------------------------------------------------------------------ le vrai parcours


def test_the_flow_notes_the_trial_of_each_row_reruns_the_played_exercise_and_moves_on(tmp_path):
    result = run_flow(tmp_path, DOM + DRIVER + r"""
      let current='tr-7';
      const cal=calOf({trialRef:()=>current});
      cal.start();
      const first=cal.stepId();
      /* Passer : l'exercice non soldé l'est comme « passé », et le parcours avance. */
      const afterNext=cal.next();
      const afterNext2=cal.next();
      /* Le pincement primaire, mesuré sous l'essai tr-7. */
      readOn(cal);
      const played=feedUntil(cal,pinching('primaryRatio'));
      const session=cal.session();
      const eps=Object.keys(session.rowMeta).filter(r=>r.startsWith('ep-'));
      /* Refaire : juste après le verdict, c'est l'exercice joué qui revient. */
      const rerun=cal.rerun();
      const phaseAfter=cal.phase();
      current='tr-8';
      readOn(cal);
      feedUntil(cal,pinching('primaryRatio'));
      const again=cal.session();
      const byTrial=Object.values(again.rowMeta).map(m=>m.trialRef);
      cal.exit('test');
      out({first,afterNext,afterNext2,played,eps:eps.length,trial:eps.map(r=>session.rowMeta[r].trialRef),
        stage:eps.length?session.rowMeta[eps[0]].stage:null,rerun,phaseAfter,byTrial,
        closed:[cal.rerun(),cal.next(),cal.concluded()]});
    """, name="agentflow")
    assert result["first"] == "neutral"
    assert result["afterNext"] == "c_pose" and result["afterNext2"] == "pinch_primary"
    assert result["played"]["from"] == "pinch_primary"
    assert result["eps"] >= 2 and set(result["trial"]) == {"tr-7"}, "chaque épisode porte l'essai sous lequel il a été pris"
    assert result["stage"] == "pinch_primary"
    assert result["rerun"] == "pinch_primary" and result["phaseAfter"] == "intro"
    assert "tr-7" in result["byTrial"] and "tr-8" in result["byTrial"], "la reprise mesure sous le nouvel essai"
    assert result["closed"] == [None, None, False]


# ------------------------------------------------------------------ commandes de repli à l'écran


COACH_DOM = r"""
const made=[];
const node=tag=>{const n={tag,children:[],attrs:{},className:'',textContent:'',hidden:false,disabled:false,listeners:{},
  parent:null,
  setAttribute(k,v){this.attrs[k]=String(v)},getAttribute(k){return this.attrs[k]},
  appendChild(c){c.parent=this;this.children.push(c);return c},
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(c=>c!==this);this.parent=null},
  addEventListener(type,fn){this.listeners[type]=fn}};made.push(n);return n};
const document={createElement:node,getElementById:id=>made.find(n=>n.id===id)||null,head:node('head'),body:node('body')};
const region=node('div');
const find=(root,attr,value)=>{const out=[];const walk=n=>{if(n.attrs[attr]===value)out.push(n);n.children.forEach(walk)};walk(root);return out[0]||null};
const settle=async()=>{for(let i=0;i<6;i+=1)await new Promise(r=>setImmediate(r))};
"""


def test_the_fallback_controls_use_the_same_doors_as_the_voice_and_say_what_happened(tmp_path):
    result = run_node(tmp_path, WORLD + COACH_DOM + r"""
      const panel=A.createCoachPanel({document,session:S,log:(l,e,d)=>logs.push([l,e,d])});
      panel.mount(region);
      const root=panel.node();
      const trialRow=()=>root.children[1];
      const line=()=>root.children[2];
      const hiddenBefore=trialRow().hidden;
      find(root,'data-coach-feedback','release_sticky').listeners.click();
      await settle();
      const noted=[line().textContent,line().attrs['data-kind']];
      const recorded=S.status().result.feedback.map(f=>[f.source,f.categories[0],f.text]);
      S.proposeHypothesis({cause:'release_confirmation_too_slow',confidence:.4,evidence:[],feedbackRefs:['fb-1']});
      S.applyTrial({hypothesisRef:'hy-1',patch:{releaseMs:30}});
      panel.refresh();
      const hiddenDuring=trialRow().hidden;
      find(root,'data-coach-action','accept').listeners.click();
      await settle();
      const kept=[line().textContent,line().attrs['data-kind'],persisted.slice()];
      find(root,'data-coach-action','rollback').listeners.click();
      await settle();
      const refused=[line().textContent,line().attrs['data-kind']];
      const labels=A.FEEDBACK_BUTTONS.map(b=>[b.category,C.USER_FEEDBACKS.includes(b.category)]);
      const disabledAfter=[...root.children[0].children,...trialRow().children].some(b=>b.disabled);
      const style=!!document.getElementById('jfCoachStyle');
      panel.close();
      out({hiddenBefore,noted,recorded,hiddenDuring,kept,refused,labels,disabledAfter,style,gone:region.children.length,
        aria:root.attrs['role']});
    """)
    assert result["hiddenBefore"] is True and result["hiddenDuring"] is False
    assert result["noted"] == ["Noté : le relâchement colle.", "ok"]
    assert result["recorded"] == [["ui", "release_sticky", "Le relâchement colle"]]
    assert result["kept"][0] == "Réglage gardé et enregistré." and result["kept"][2] == [{"releaseMs": 30}]
    assert result["refused"][1] == "bad" and "Pas fait" in result["refused"][0], "le refus se dit"
    assert all(ok for _, ok in result["labels"]) and [c for c, _ in result["labels"]] == [
        "release_sticky", "false_click", "hard_to_aim", "fine"]
    assert result["disabledAfter"] is False, "le bouton est rendu après l'action"
    assert result["style"] is True and result["gone"] == 0 and result["aria"] == "group"


def test_the_session_is_declared_beats_and_closes_itself_when_the_flow_is_gone(tmp_path):
    result = run_node(tmp_path, r"""
      const posts=[],timers=[],logs=[];let live=true,fail=false;
      const r=A.createSessionReporter({post:async body=>{if(fail)throw new Error('réseau');posts.push(body)},
        setInterval:(fn,ms)=>{timers.push({fn,ms});return timers.length},clearInterval:id=>{timers[id-1]=null},
        running:()=>live,exercise:()=>'aim',log:(l,e,d)=>logs.push([l,e])});
      const id=r.start();
      await null;
      timers[0].fn();await null;
      fail=true;timers[0].fn();await null;timers[0].fn();await null;timers[0].fn();await null;
      fail=false;
      live=false;timers[0].fn();await null;
      out({id:id.length,posts,interval:timers.length?(timers[0]||{ms:'cleared'}).ms:null,
        levels:logs.filter(l=>l[1]==='barehands.calibration_session_report_failed').map(l=>l[0]),session:r.session()});
    """)
    assert result["id"] >= 16
    assert [p["active"] for p in result["posts"]] == [True, True, False], "déclarée, battue, fermée d'elle-même"
    assert result["posts"][0]["exercise"] == "aim"
    assert result["interval"] == "cleared"
    assert result["levels"] == ["warn", "warn", "error"], "trois échecs de suite remontent en erreur"
    assert result["session"] is None


# ------------------------------------------------------------------ canal de commandes


def test_the_channel_hands_the_payload_to_the_agent_and_turns_its_answer_into_a_closed_receipt(tmp_path):
    result = run_node(tmp_path, r"""
      const calls=[];
      const surface={lifecycle:()=>'active',calibrationAgent:{
        status:p=>{calls.push(['status',p]);return {ok:true,result:{exercise:{step:'aim'}}}},
        applyTrial:p=>{calls.push(['apply',p]);return {ok:false,code:'barehands_calibration_refused',
          errors:[{code:'barehands_calibration_hypothesis_disproven',message:'démentie'},{code:'pas un code',message:'x'}]}},
        recordFeedback:()=>{throw new Error('boum')},
        rerun:()=>({ok:false,code:'barehands_calibration_inactive',errors:[{code:'barehands_calibration_inactive',message:'fermée'}]}),
      }};
      const receipts=[];const shown=[];
      const channel=M.createCommandChannel({request:async(url,opts)=>{receipts.push(JSON.parse(opts.body));return {status:200,body:{}}},
        surface:()=>surface,now:()=>0,sleep:async()=>{},onReceipt:e=>shown.push(e.name),log:()=>{}});
      const id='x'.repeat(32);
      await channel.apply({id,name:'calibration_status',remaining_ms:3000,payload:{}});
      await channel.apply({id,name:'calibration_apply_trial',remaining_ms:3000,payload:{hypothesisRef:'hy-1',patch:{releaseMs:30}}});
      await channel.apply({id,name:'calibration_record_feedback',remaining_ms:3000,payload:{categories:['fine'],text:'x'}});
      await channel.apply({id,name:'calibration_rerun_exercise',remaining_ms:3000,payload:{}});
      await channel.apply({id,name:'calibration_next_exercise',remaining_ms:3000,payload:{}});
      await channel.apply({id,name:'activate',remaining_ms:3000});
      out({calls,receipts,shown,invalid:[M.validCommand({id,name:'activate',remaining_ms:1,payload:{}}),
        M.validCommand({id,name:'calibration_status',remaining_ms:1,payload:[]}),
        M.validCommand({id,name:'calibration_status',remaining_ms:1,payload:{}})]});
    """)
    assert result["calls"] == [["status", {}], ["apply", {"hypothesisRef": "hy-1", "patch": {"releaseMs": 30}}]]
    r = result["receipts"]
    assert r[0] == {"outcome": "applied", "lifecycle": "active", "code": None, "reason": None,
                    "result": {"exercise": {"step": "aim"}}}
    assert r[1]["outcome"] == "refused" and r[1]["code"] == "barehands_calibration_refused"
    assert r[1]["result"]["errors"] == [{"code": "barehands_calibration_hypothesis_disproven", "message": "démentie"},
                                        {"code": "barehands_calibration_refused", "message": "x"}]
    assert r[2]["code"] == "barehands_calibration_refused"
    assert r[2]["result"]["errors"][0]["code"] == "barehands_calibration_page_error"
    assert r[3]["code"] == "barehands_calibration_inactive"
    assert r[4]["code"] == "barehands_flow_absent", "une page sans la porte le dit"
    assert "result" not in r[5], "le reçu de cycle de vie garde ses quatre champs"
    assert result["shown"] == ["activate"], "le reçu brut d'une commande de calibration ne s'affiche pas"
    assert result["invalid"] == [False, False, True]


# ------------------------------------------------------------------ la page


def test_the_page_surface_refuses_outside_a_calibration_and_the_trial_gate_names_its_code(tmp_path):
    result = run_page(tmp_path, page() + r"""
      const A=BAREHANDS.calibrationAgent;
      const status=A.status();
      const apply=BAREHANDS.trial.apply({pressFrames:1});
      const rollback=BAREHANDS.trial.rollback();
      const accept=await BAREHANDS.trial.accept();
      const engine=pinch('pressFrames');
      const ui=BAREHANDS.trial.apply({pressFrames:1},{source:'ui'});
      const discard=BAREHANDS.trial.discard('test');
      out({status:[status.ok,status.code],apply:apply.code,rollback:rollback.code,accept:accept.code,engine,
        ui:ui.ok,discard:discard.ok,active:A.active(),coach:A.coach(),read:typeof BAREHANDS.trial.status().active,
        agentLoaded:!!window.JarvisBarehandsCalibrationAgent||!!global.JarvisBarehandsCalibrationAgent});
    """)
    assert result["status"] == [False, "barehands_calibration_inactive"]
    assert result["apply"] == result["rollback"] == result["accept"] == "barehands_calibration_inactive"
    assert result["engine"] == 2, "le refus ne touche pas au moteur"
    assert result["ui"] is True and result["discard"] is True, "l'écran de la page garde sa porte"
    assert result["active"] is False and result["coach"] is None and result["read"] == "boolean"
    assert result["agentLoaded"] is True


def test_every_receipt_the_real_session_builds_passes_the_server_schema(tmp_path):
    """**Les deux moitiés du contrat de reçu**, l'une contre l'autre : ce que la
    vraie séance rend, traduit par le vrai canal, est exactement ce que le
    schéma fermé du serveur accepte — une clé de plus et le cerveau
    n'apprendrait qu'une échéance."""

    from jarvis.domain import barehands_command as vocab

    result = run_node(tmp_path, WORLD + r"""
      const agent={status:()=>S.status(),recordFeedback:p=>S.recordFeedback(p,'voice'),
        proposeHypothesis:p=>S.proposeHypothesis(p),applyTrial:p=>S.applyTrial(p),resolveTrial:p=>S.resolveTrial(p),
        rollbackTrial:()=>S.rollbackTrial(),acceptTrial:p=>S.acceptTrial(p,'voice'),rerun:()=>S.rerun(),next:()=>S.next()};
      const receipts=[];
      const channel=M.createCommandChannel({request:async(url,opts)=>{receipts.push(JSON.parse(opts.body));return {status:200,body:{}}},
        surface:()=>({lifecycle:()=>'active',calibrationAgent:agent}),now:()=>0,sleep:async()=>{},log:()=>{}});
      const id='y'.repeat(32);const send=async(name,payload)=>{clock+=1000;await channel.apply({id,name,remaining_ms:3000,payload:payload||{}});
        return receipts[receipts.length-1]};
      const names=[];
      const go=async(name,payload)=>{names.push(name);return send(name,payload)};
      measure({'ep-1':{release_latency_ms:240},'ep-2':{release_latency_ms:260}});
      await go('calibration_record_feedback',{categories:['release_sticky'],text:'ça colle'});
      await go('calibration_propose_hypothesis',{cause:'release_confirmation_too_slow',confidence:.5,
        evidence:[{metric:'release_latency_ms',aggregate:'p95',sourceRefs:['ep-1','ep-2']}],feedbackRefs:['fb-1']});
      await go('calibration_apply_trial',{hypothesisRef:'hy-1',patch:{releaseMs:20,releaseFrames:1}});
      measure({'ep-3':{release_latency_ms:120},'ep-4':{release_latency_ms:130}});
      await go('calibration_resolve_trial',{trialRef:'tr-1',verdict:'improved',
        comparisons:[{metric:'release_latency_ms',aggregate:'p95'}],beforeRefs:['ep-1','ep-2'],afterRefs:['ep-3','ep-4'],feedbackRefs:[]});
      await go('calibration_status');
      await go('calibration_rerun_exercise');
      await go('calibration_next_exercise');
      await go('calibration_apply_trial',{hypothesisRef:'hy-1',patch:{releaseMs:10}});
      await go('calibration_rollback_trial');
      await go('calibration_accept_trial',{consent:{source:'voice',quote:'oui garde',verifiedBy:'control_center'}});
      await go('calibration_apply_trial',{hypothesisRef:'hy-9',patch:{releaseMs:10}});
      out({names,receipts});
    """, name="schema")
    outcomes = []
    for name, receipt in zip(result["names"], result["receipts"]):
        parsed = vocab.parse_command_receipt(name, receipt)
        outcomes.append((name, parsed["outcome"]))
    assert [o for _, o in outcomes] == ["applied"] * 10 + ["refused"], outcomes
    assert len(json.dumps(result["receipts"][4])) < 16_384
