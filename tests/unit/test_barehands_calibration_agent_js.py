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
#: Le contrat étendu du § 12 (Slice 10) : tous les noms du contrat, plus la
#: calibration adaptative et le banc — ce que lisent les modules de page.
ADAPTIVE = RUNTIME / "control_center_barehands_adaptive.js"
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
        f"const C=require({json.dumps(str(ADAPTIVE))});\n"
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
let running=true,concluded=false,step='pinch_primary',phase='result',moves=[],attempt=1;
const acts=[];
const flow={isRunning:()=>running,stepId:()=>step,phase:()=>phase,concluded:()=>concluded,
  session:()=>({measurements:C.createMeasurementSet(rows),rowMeta:meta}),
  /* La revue de l'exercice (retour du 28/09) : une proposition se prépare
     sur elle et ne vaut que pour elle (étape, essai n°). */
  review:()=>phase==='result'||phase==='review'?{stage:step,label:'Exercice',attempt,status:'ok',cause:null,checks:[],
    lines:[]}:null,
  canRerun:()=>({ok:true,code:null}),
  act:(source,fn)=>{acts.push(source);return fn()},
  acceptUnverified:()=>{moves.push('accept_unverified');return step},
  rerun:()=>{moves.push('rerun');return step},
  /* Slice 07 adaptative : `next(raison)` rend `{ok, step, code}` (valider, ou
     passer avec une raison). */
  next:()=>{moves.push('next');return {ok:true,step,code:null}},mark:()=>null};
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
/* L'effectif suit l'essai en cours (ce que le moteur relit) ; l'enregistré suit
   ce qui a été gardé. */
const values=()=>{const kept=Object.assign({},...persisted),delta=trials.delta();
  const hand=base=>({...base,...kept,...delta});
  return {effective:{left:hand({releaseMs:60,pressRatio:.2}),right:hand({releaseMs:60,pressRatio:.3}),
    unknown:hand({releaseMs:60,pressRatio:.28})},
    saved:{left:{releaseMs:60,...kept},right:{releaseMs:60,...kept},unknown:{releaseMs:60,...kept}},trial:delta}};
const logs=[],emitted=[];
const S=A.createCalibrationAgentSession({contracts:C,flow:()=>flow,trials:()=>trials,values,now:()=>clock,
  log:(level,event,data)=>logs.push([level,event,data]),emit:event=>emitted.push(event),revision:()=>emitted.length});
const measure=(add,stage)=>{const top=trials.status().trialId;
  for(const [ref,metrics] of Object.entries(add)){rows[ref]=metrics;meta[ref]={stage:stage||step,exerciseRef:null,trialRef:top,
    stateId:S.stateRef(),at:clock}}};
const get=(o,path)=>path.split('.').reduce((v,k)=>v===undefined||v===null?undefined:v[k],o);
async function play(step_){
  clock+=1000;
  if(step_.op==='measure'){measure(step_.rows,step_.stage);return null}
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
      clock+=1000;
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
    # Slice 07 adaptative : `t` (ms de séance) ; absent de la ligne notée ici.
    assert result["last"] == {"ref": "ep-40", "stage": "pinch_primary", "exerciseRef": None, "trialRef": None,
                              "stateId": 0, "t": None,
                              "metrics": {"press_latency_ms": 40, "release_latency_ms": None}}
    values = result["values"]
    assert values["effective"]["releaseMs"] == 60, "toutes les clés annoncées, même au défaut (round 6)"
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
      const cal=calOf({trialRef:()=>current,stateRef:()=>current==='tr-7'?4:5});
      cal.start();
      const first=cal.stepId();
      /* Passer : l'exercice non soldé l'est comme « passé » **avec une
         raison** (Slice 07 adaptative), et le parcours avance. */
      const afterNext=cal.next('later').step;
      const afterNext2=cal.next('not_relevant').step;
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
      const byState=[...new Set(Object.values(again.rowMeta).map(m=>m.stateId))].sort();
      cal.exit('test');
      out({first,afterNext,afterNext2,played,eps:eps.length,trial:eps.map(r=>session.rowMeta[r].trialRef),
        stage:eps.length?session.rowMeta[eps[0]].stage:null,rerun,phaseAfter,byTrial,
        byState,closed:[cal.rerun(),cal.next('later').ok,cal.concluded()]});
    """, name="agentflow")
    assert result["first"] == "neutral"
    assert result["afterNext"] == "c_pose" and result["afterNext2"] == "pinch_primary"
    assert result["played"]["from"] == "pinch_primary"
    assert result["eps"] >= 2 and set(result["trial"]) == {"tr-7"}, "chaque épisode porte l'essai sous lequel il a été pris"
    assert result["stage"] == "pinch_primary"
    assert result["rerun"] == "pinch_primary" and result["phaseAfter"] == "intro"
    assert "tr-7" in result["byTrial"] and "tr-8" in result["byTrial"], "la reprise mesure sous le nouvel essai"
    assert result["closed"] == [None, False, False]
    assert result["byState"] == [4, 5], "chaque ligne porte l'état effectif sous lequel elle a été prise"


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
      clock+=1000;
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
    assert result["kept"][0] == "Réglage gardé sur votre ressenti, sans mesure pour le confirmer." and result["kept"][2] == [{"releaseMs": 30}]
    assert result["refused"] == ["Aucun essai à annuler.", "bad"], "le refus se dit, en mots d'utilisateur"
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
        prepareTrial:p=>{calls.push(['prepare',p]);return {ok:false,code:'barehands_calibration_refused',
          errors:[{code:'barehands_calibration_hypothesis_disproven',message:'démentie'},{code:'pas un code',message:'x'}]}},
        recordFeedback:()=>{throw new Error('boum')},
        rerun:()=>({ok:false,code:'barehands_calibration_inactive',errors:[{code:'barehands_calibration_inactive',message:'fermée'}]}),
      }};
      const receipts=[];const shown=[];
      const channel=M.createCommandChannel({request:async(url,opts)=>{receipts.push(JSON.parse(opts.body));return {status:200,body:{}}},
        surface:()=>surface,now:()=>0,sleep:async()=>{},onReceipt:e=>shown.push(e.name),log:()=>{}});
      const id='x'.repeat(32);
      await channel.apply({id,name:'calibration_status',remaining_ms:3000,payload:{}});
      await channel.apply({id,name:'calibration_prepare_trial',remaining_ms:3000,payload:{hypothesisRef:'hy-1',patch:{releaseMs:30}}});
      await channel.apply({id,name:'calibration_record_feedback',remaining_ms:3000,payload:{categories:['fine'],text:'x'}});
      await channel.apply({id,name:'calibration_rerun_exercise',remaining_ms:3000,payload:{}});
      await channel.apply({id,name:'calibration_next_exercise',remaining_ms:3000,payload:{}});
      await channel.apply({id,name:'activate',remaining_ms:3000});
      out({calls,receipts,shown,invalid:[M.validCommand({id,name:'activate',remaining_ms:1,payload:{}}),
        M.validCommand({id,name:'calibration_status',remaining_ms:1,payload:[]}),
        M.validCommand({id,name:'calibration_status',remaining_ms:1,payload:{}})]});
    """)
    assert result["calls"] == [["status", {}], ["prepare", {"hypothesisRef": "hy-1", "patch": {"releaseMs": 30}}]]
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
      const noBypass=BAREHANDS.trial.apply({pressFrames:1},{source:'ui'}).code;
      const ui=BAREHANDS.adapters.trials.apply({pressFrames:1});
      const discard=BAREHANDS.trial.discard('test');
      out({noBypass,status:[status.ok,status.code],apply:apply.code,rollback:rollback.code,accept:accept.code,engine,
        ui:ui.ok,discard:discard.ok,active:A.active(),coach:A.coach(),read:typeof BAREHANDS.trial.status().active,
        agentLoaded:!!window.JarvisBarehandsCalibrationAgent||!!global.JarvisBarehandsCalibrationAgent});
    """)
    assert result["status"] == [False, "barehands_calibration_inactive"]
    assert result["apply"] == result["rollback"] == result["accept"] == "barehands_calibration_inactive"
    assert result["engine"] == 2, "le refus ne touche pas au moteur"
    assert result["noBypass"] == "barehands_calibration_inactive", "plus d'exemption {source:'ui'}"
    assert result["ui"] is True and result["discard"] is True, "le gestionnaire nu reste lisible (diagnostic)"
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
        proposeHypothesis:p=>S.proposeHypothesis(p),prepareTrial:p=>S.prepareTrial(p),
        commitProposal:p=>S.commitProposal(p,'voice'),resolveTrial:p=>S.resolveTrial(p),
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
      const consent=quote=>({source:'voice',quote,verifiedBy:'control_center'});
      await go('calibration_prepare_trial',{hypothesisRef:'hy-1',patch:{releaseMs:20,releaseFrames:1},
        summary:'Relâchement reconnu plus vite',untouched:'L’appui est déjà bon.'});
      await go('calibration_status');
      await go('calibration_commit_proposal',{proposalRef:'pr-1',action:'rerun',consent:consent('oui, applique')});
      measure({'ep-3':{release_latency_ms:120},'ep-4':{release_latency_ms:130},'ep-5':{release_latency_ms:125}});
      await go('calibration_resolve_trial',{trialRef:'tr-1',verdict:'improved',
        comparisons:[{metric:'release_latency_ms',aggregate:'p95'}],beforeRefs:['ep-1','ep-2'],afterRefs:['ep-3','ep-4','ep-5'],feedbackRefs:[]});
      await go('calibration_rerun_exercise');
      await go('calibration_next_exercise');
      await go('calibration_accept_trial',{consent:consent('oui garde')});
      await go('calibration_prepare_trial',{hypothesisRef:'hy-1',patch:{releaseMs:10},summary:'Encore un peu plus vite'});
      await go('calibration_commit_proposal',{proposalRef:'pr-2',action:'continue',consent:consent('oui garde et continue')});
      await go('calibration_status');
      await go('calibration_rollback_trial');
      await go('calibration_prepare_trial',{hypothesisRef:'hy-9',patch:{releaseMs:10},summary:'x y'});
      await go('calibration_commit_proposal',{proposalRef:'pr-2',action:'rerun',consent:consent('oui')});
      out({names,receipts});
    """, name="schema")
    outcomes = []
    for name, receipt in zip(result["names"], result["receipts"]):
        parsed = vocab.parse_command_receipt(name, receipt)
        outcomes.append((name, parsed["outcome"]))
    assert [o for _, o in outcomes] == ["applied"] * 12 + ["refused"] * 3, outcomes
    assert result["receipts"][3]["result"]["proposal"]["state"] == "pending"
    assert result["receipts"][4]["result"]["steps"] == ["applied", "verified", "rerun"]
    continued = result["receipts"][10]["result"]
    assert continued["steps"] == ["applied", "verified", "saved", "advanced"]
    assert continued["decision"] == "accepted_unverified"
    after = result["receipts"][11]["result"]
    assert after["proposal"]["state"] == "committed" and after["trials"][-1]["basis"] == "user_unverified"
    assert result["receipts"][14]["result"]["errors"][0]["code"] == "barehands_calibration_proposal_committed"
    assert len(json.dumps(result["receipts"][11])) < 16_384


def test_a_rolled_back_trial_stays_to_be_judged_and_an_unmeasured_one_pays_for_it(tmp_path):
    """Constat de la QA : appliquer puis annuler en boucle gardait l'hypothèse
    à 0,8, ouverte, avec des essais jamais jugés. L'annulation reste immédiate ;
    l'essai annulé reste à juger et bloque le suivant ; sans mesure prise sous
    lui, seul « inconclusive » (au prix `inconclusiveFactor`) ou « worse »
    soutenu par la plainte de l'utilisateur passe."""

    result = run_node(tmp_path, WORLD + r"""
      measure({'ep-1':{release_latency_ms:120},'ep-2':{release_latency_ms:130}});
      S.recordFeedback({categories:['release_sticky'],text:'ça colle'},'voice');
      S.proposeHypothesis({cause:'release_confirmation_too_slow',confidence:.9,
        evidence:[{metric:'release_latency_ms',aggregate:'p50',sourceRefs:['ep-1','ep-2']}],feedbackRefs:['fb-1']});
      const cycles=[];
      for(let i=0;i<4;i++){clock+=1000;const a=S.applyTrial({hypothesisRef:'hy-1',patch:{releaseMs:40+i}});
        const rb=S.rollbackTrial();cycles.push([a.ok,a.ok?null:a.errors[0].code,rb.ok]);}
      clock+=1000;
      const empty={comparisons:[],beforeRefs:[],afterRefs:[],feedbackRefs:[]};
      const improved=S.resolveTrial({trialRef:'tr-1',verdict:'improved',...empty});
      const noChange=S.resolveTrial({trialRef:'tr-1',verdict:'no_change',...empty});
      const inconclusive=S.resolveTrial({trialRef:'tr-1',verdict:'inconclusive',...empty});
      /* Second essai : l'utilisateur dit « annule, ça colle encore » — annulé
         tout de suite, sa plainte notée, et elle soutient « worse ». */
      clock+=1000;const second=S.applyTrial({hypothesisRef:'hy-1',patch:{releaseMs:20}});
      clock+=1000;S.rollbackTrial();
      clock+=1000;S.recordFeedback({categories:['release_sticky'],text:'annule, ça colle encore'},'voice');
      clock+=1000;
      const worseMute=S.resolveTrial({trialRef:second.result.trialRef,verdict:'worse',...empty});
      const worse=S.resolveTrial({trialRef:second.result.trialRef,verdict:'worse',...empty,feedbackRefs:['fb-2']});
      const trialsState=S.status().result.trials.map(t=>[t.ref,t.state,t.verdict]);
      out({cycles,improved:improved.errors[0].code,noChange:noChange.errors[0].code,
        inconclusive:inconclusive.result.hypotheses[0],second:second.ok,worseMute:worseMute.errors[0].code,
        worse:worse.result.hypotheses[0],trialsState});
    """)
    assert result["cycles"][0] == [True, None, True]
    assert result["cycles"][1][:2] == [False, "barehands_calibration_trial_unresolved"], "annulé n'est pas jugé"
    # improved sans mesure ni retour : le contrat le refuse (rien ne le soutient) ;
    # no_change sans mesure : refusé par la séance.
    assert result["improved"] == "barehands_evidence_unsourced"
    assert result["noChange"] == "barehands_calibration_trial_unmeasured"
    assert result["inconclusive"] == {"ref": "hy-1", "cause": "release_confirmation_too_slow", "before": 0.8,
                                      "confidence": 0.64, "status": "open"}, "×0,8 pour un essai abandonné"
    assert result["second"] is True
    assert result["worseMute"] == "barehands_evidence_unsourced", "« worse » muet sur un essai non mesuré"
    assert result["worse"]["confidence"] == pytest.approx(0.256) and result["worse"]["status"] == "weakened"
    assert result["trialsState"] == [["tr-1", "rolled_back", "inconclusive"], ["tr-2", "rolled_back", "worse"]]


def test_the_confidence_rule_distinguishes_worse_from_no_change_and_rejects_below_the_floor(tmp_path):
    result = run_node(tmp_path, WORLD + r"""
      measure({'ep-1':{press_latency_ms:100},'ep-2':{press_latency_ms:110}});
      measure({'ep-101':{press_latency_ms:100},'ep-102':{press_latency_ms:110}},'c_pose');
      const results=[];
      const cases=[['press_threshold_too_strict',.5,'worse','pressFrames',1,'pinch_primary'],
        ['press_threshold_too_loose',.5,'no_change','pressFrames',3,'pinch_primary'],
        ['wake_too_strict',.3,'worse','wakeHoldMs',800,'c_pose'],['wake_too_sensitive',.2,'no_change','wakeHoldMs',1500,'c_pose']];
      let n=3;
      for(const [cause,conf,verdict,key,value,stage] of cases){
        clock+=1000;
        const before=stage==='c_pose'?['ep-101','ep-102']:['ep-1','ep-2'];
        const hy=S.proposeHypothesis({cause,confidence:conf,evidence:[{metric:'press_latency_ms',aggregate:'p50',
          sourceRefs:before}],feedbackRefs:[]});
        const tr=S.applyTrial({hypothesisRef:hy.result.hypothesis.ref,patch:{[key]:value}});
        clock+=1000;const a=`ep-${n++}`,b=`ep-${n++}`,c=`ep-${n++}`;
        const v=verdict==='worse'?155:105;
        measure({[a]:{press_latency_ms:v},[b]:{press_latency_ms:v},[c]:{press_latency_ms:v}},stage);
        const r=S.resolveTrial({trialRef:tr.result.trialRef,verdict,
          comparisons:[{metric:'press_latency_ms',aggregate:'p50'}],beforeRefs:before,afterRefs:[a,b,c],feedbackRefs:[]});
        results.push(r.ok?r.result.hypotheses[0]:r.errors);
        S.rollbackTrial();
      }
      out({rows:results,rule:A.CONFIDENCE_RULE});
    """)
    rows = result["rows"]
    assert rows[0]["confidence"] == pytest.approx(0.2) and rows[0]["status"] == "weakened", "worse ×0,4"
    assert rows[1]["confidence"] == pytest.approx(0.3) and rows[1]["status"] == "weakened", "no_change ×0,6"
    assert rows[2]["confidence"] == pytest.approx(0.12) and rows[2]["status"] == "rejected", "sous 0,15 : rejetée"
    assert rows[3]["confidence"] == pytest.approx(0.12) and rows[3]["status"] == "rejected"
    assert result["rule"]["worseFactor"] != result["rule"]["noChangeFactor"]


def test_misplaced_before_refs_alone_are_refused(tmp_path):
    result = run_node(tmp_path, WORLD + r"""
      measure({'ep-1':{release_latency_ms:200}});
      S.recordFeedback({categories:['release_sticky'],text:'ça colle'},'voice');
      S.proposeHypothesis({cause:'release_confirmation_too_slow',confidence:.5,evidence:[],feedbackRefs:['fb-1']});
      clock+=1000;S.applyTrial({hypothesisRef:'hy-1',patch:{releaseMs:20}});
      clock+=1000;measure({'ep-2':{release_latency_ms:100},'ep-3':{release_latency_ms:110}});
      const r=S.resolveTrial({trialRef:'tr-1',verdict:'improved',comparisons:[{metric:'release_latency_ms',aggregate:'p50'}],
        beforeRefs:['ep-2'],afterRefs:['ep-3'],feedbackRefs:[]});
      out(r.errors[0]);
    """)
    assert result["code"] == "barehands_calibration_refs_misplaced" and "pas prises avant" in result["message"]


def test_status_stays_inside_the_receipt_budget_with_realistic_rows(tmp_path):
    """Constat de la QA : 24 lignes de neuf métriques à 17 chiffres dépassaient
    les 16 Ko du reçu, et le cerveau lisait une échéance. Arrondi, puis les plus
    anciennes lignes partent, comptées ; le reçu passe le schéma du serveur."""

    from jarvis.domain import barehands_command as vocab

    result = run_node(tmp_path, WORLD + r"""
      const f=()=>Math.random()*1000/7;
      for(let i=1;i<=40;i++)measure({[`ep-${i}`]:{press_latency_ms:f(),release_latency_ms:f(),episode_duration_ms:f(),
        episode_min_ratio:Math.random(),open_baseline_ratio:Math.random(),closing_velocity:f(),opening_velocity:f(),
        episode_travel_px:f(),episode_quality:Math.random()}});
      const txt='Quand je relâche la pince, le pointeur reste accroché une demi-seconde, et ça arrive surtout à droite. ';
      for(let i=0;i<14;i++)S.recordFeedback({categories:['release_sticky'],text:(txt+txt+txt+txt+txt).slice(0,480)},'voice');
      for(const cause of C.HYPOTHESIS_CAUSES)S.proposeHypothesis({cause,confidence:.5,evidence:[{metric:'press_latency_ms',
        aggregate:'p95',sourceRefs:['ep-1','ep-2','ep-3','ep-4','ep-5','ep-6','ep-7','ep-8']}],feedbackRefs:['fb-1','fb-2','fb-3']});
      const st=S.status();
      const receipt={outcome:'applied',lifecycle:'active',code:null,reason:null,result:st.result};
      out({receipt,bytes:Buffer.byteLength(JSON.stringify(receipt),'utf8'),truncated:st.result.truncated,
        sample:st.result.measurements.slice(-1)[0].metrics.press_latency_ms});
    """)
    assert result["bytes"] < 16_384
    assert sum(result["truncated"].values()) > 0, "des lignes sont parties, et c'est compté"
    assert result["sample"] == round(result["sample"], 3)
    parsed = vocab.parse_command_receipt("calibration_status", result["receipt"])
    assert parsed["result"]["truncated"] == result["truncated"]


def test_the_reporter_carries_the_trial_knows_whether_it_holds_the_session_and_beacons_on_close(tmp_path):
    result = run_node(tmp_path, r"""
      const posts=[],beacons=[],timers=[];let busy=true,trial=null;
      const r=A.createSessionReporter({post:async body=>{posts.push(body);
          if(busy)throw Object.assign(new Error('refusé'),{code:'barehands_calibration_session_busy',status:409});
          return {active:body.active}},
        setInterval:fn=>{timers.push(fn);return 1},clearInterval:()=>{},running:()=>true,trial:()=>trial,
        beacon:body=>{beacons.push(body);return true},log:()=>{}});
      r.start();await new Promise(res=>setImmediate(res));
      const refused=[r.held(),r.refusal()&&r.refusal().code];
      busy=false;trial='tr-2';
      timers[0]();await new Promise(res=>setImmediate(res));
      const held=r.held();
      const beacon=r.beacon();
      r.stop();
      out({refused,held,posts,beacon,beacons,after:r.beacon()});
    """)
    assert result["refused"] == [False, "barehands_calibration_session_busy"]
    assert result["held"] is True
    assert result["posts"][0]["trial"] is None and result["posts"][1]["trial"] == "tr-2"
    assert result["posts"][-1] == {"session": result["posts"][0]["session"], "active": False, "exercise": None,
                                   "trial": None}
    assert result["beacon"] is True and result["beacons"][0]["active"] is False
    assert result["after"] is False


def test_the_cancel_button_rolls_back_at_once_and_keeps_the_trial_to_be_judged(tmp_path):
    result = run_node(tmp_path, WORLD + COACH_DOM + r"""
      const panel=A.createCoachPanel({document,session:S,log:()=>{}});
      panel.mount(region);
      S.recordFeedback({categories:['release_sticky'],text:'ça colle'},'voice');
      S.proposeHypothesis({cause:'release_confirmation_too_slow',confidence:.4,evidence:[],feedbackRefs:['fb-1']});
      clock+=1000;S.applyTrial({hypothesisRef:'hy-1',patch:{releaseMs:30}});
      panel.refresh();
      clock+=1000;
      find(panel.node(),'data-coach-action','rollback').listeners.click();
      await settle();
      const st=S.status().result;
      out({line:panel.node().children[2].textContent,feedback:st.feedback.map(f=>[f.source,f.categories,f.text]),
        trials:st.trials.map(t=>[t.state,t.verdict]),next:S.applyTrial({hypothesisRef:'hy-1',patch:{releaseMs:20}}).errors[0].code});
    """)
    assert "Dites ce que vous en pensiez" in result["line"], "annulé, pas jugé : l'écran demande l'avis"
    assert result["feedback"][-1] == ["ui", ["unclear"], "Annuler l’essai (bouton)"], "« annuler » est aussi une parole"
    assert result["trials"] == [["rolled_back", None]]
    assert result["next"] == "barehands_calibration_trial_unresolved"


def test_the_voice_door_refuses_when_this_page_does_not_hold_the_session(tmp_path):
    """Mutant « la page ignore la tenue » : un second onglet en calibration ne
    doit pas appliquer une commande que le long-poll lui a remise."""

    result = run_node(tmp_path, WORLD + r"""
      let held=false,refusal={code:'barehands_calibration_session_busy'};
      const V=A.createCalibrationAgentSession({contracts:C,flow:()=>flow,trials:()=>trials,values,now:()=>clock,
        log:()=>{},held:()=>held,refusal:()=>refusal});
      const busy=V.command('status');
      refusal=null;
      const unknown=V.command('feedback',{categories:['fine'],text:'x'});
      const bare=A.createCalibrationAgentSession({contracts:C,flow:()=>flow,trials:()=>trials,values,now:()=>clock,
        log:()=>{}}).command('status');
      held=true;
      const ok=V.command('status');
      const fb=V.command('feedback',{categories:['fine'],text:'nickel'});
      const bad=V.command('danse');
      out({busy:[busy.code,busy.errors[0].message],unknown:unknown.code,bare:bare.code,ok:ok.ok,
        fb:[fb.ok,fb.result.feedback.source],bad:bad.errors[0].code,applied:serial});
    """)
    assert result["busy"][0] == "barehands_calibration_inactive" and "autre page" in result["busy"][1]
    assert result["unknown"] == result["bare"] == "barehands_calibration_inactive"
    assert result["ok"] is True and result["fb"] == [True, "voice"]
    assert result["bad"] == "barehands_command_unknown" and result["applied"] == 0


def test_a_measured_inconclusive_verdict_also_costs_confidence(tmp_path):
    """Aucun verdict ne laisse la confiance intacte après un essai, sauf `improved`."""

    result = run_node(tmp_path, WORLD + r"""
      measure({'ep-1':{release_latency_ms:200},'ep-2':{release_latency_ms:210}});
      S.recordFeedback({categories:['release_sticky'],text:'ça colle'},'voice');
      S.proposeHypothesis({cause:'release_confirmation_too_slow',confidence:.5,evidence:[],feedbackRefs:['fb-1']});
      clock+=1000;S.applyTrial({hypothesisRef:'hy-1',patch:{releaseMs:20}});
      clock+=1000;measure({'ep-3':{release_latency_ms:120},'ep-4':{release_latency_ms:110}});
      const r=S.resolveTrial({trialRef:'tr-1',verdict:'inconclusive',comparisons:[{metric:'release_latency_ms',aggregate:'p50'}],
        beforeRefs:['ep-1','ep-2'],afterRefs:['ep-3','ep-4'],feedbackRefs:[]});
      out({h:r.result.hypotheses[0],direction:r.result.deltas[0].direction,rule:A.CONFIDENCE_RULE});
    """)
    assert result["direction"] == "better"
    assert result["h"]["before"] == 0.5 and result["h"]["confidence"] == pytest.approx(0.4)
    assert result["rule"]["inconclusiveFactor"] == 0.8


def test_status_trims_the_oldest_rows_first(tmp_path):
    """Mutant « les plus récentes d'abord » : c'est la fin de la séance que le tour désigne."""

    result = run_node(tmp_path, WORLD + r"""
      const f=()=>Math.random()*1000/7;
      for(let i=1;i<=60;i++)measure({[`ep-${i}`]:{press_latency_ms:f(),release_latency_ms:f(),episode_duration_ms:f(),
        episode_min_ratio:Math.random(),open_baseline_ratio:Math.random(),closing_velocity:f(),opening_velocity:f(),
        episode_travel_px:f(),episode_quality:Math.random()}});
      const long='x'.repeat(480);
      for(let i=0;i<14;i++)S.recordFeedback({categories:['release_sticky'],text:`${i} ${long}`.slice(0,480)},'voice');
      const st=S.status().result;
      out({meas:st.measurements.map(m=>m.ref),fb:st.feedback.map(f=>f.ref),truncated:st.truncated});
    """)
    assert result["meas"][-1] == "ep-60" and result["fb"][-1] == "fb-14", "les plus récentes restent"
    assert result["truncated"]["feedback"] > 0
    kept = [int(ref.split("-")[1]) for ref in result["meas"]]
    assert kept == sorted(kept) and kept[0] == 60 - len(kept) + 1


def test_the_page_closes_its_session_with_a_simple_beacon_on_pagehide(tmp_path):
    """Mutant « pas de balise » : `pagehide` est branché sur la fermeture de séance, par une balise texte."""

    result = run_page(tmp_path, page(r"""
      const listeners={};
      global.window.addEventListener=(type,fn)=>{(listeners[type]=listeners[type]||[]).push(fn)};
    """) + r"""
      const hide=(listeners.pagehide||[]).map(fn=>fn.name);
      out({hide});
    """)
    assert "closeSessionOnPageHide" in result["hide"]
    source = (RUNTIME / "control_center_barehands.js").read_text(encoding="utf-8")
    body = source[source.index("function closeSessionOnPageHide"):][:120]
    assert "agentReporter.beacon()" in body
    assert "navigator.sendBeacon(CALIBRATION_SESSION_API" in source and "{type:'text/plain;charset=UTF-8'}" in source


def test_a_trial_is_judged_on_its_own_exercise_and_channel(tmp_path):
    """Constats de la QA réelle : preuve primaire, essai secondaire, jugement
    primaire contre secondaire — accepté ; et « refais » rejouait la visée pour
    une hypothèse de relâchement."""

    result = run_node(tmp_path, WORLD + r"""
      measure({'ep-1':{release_latency_ms:240},'ep-2':{release_latency_ms:260}},'pinch_primary');
      measure({'ep-3':{release_latency_ms:240},'ep-4':{release_latency_ms:250}},'pinch_secondary');
      measure({'ex-1':{acquisition_ms:900}},'aim');
      S.recordFeedback({categories:['release_sticky'],text:'le relâchement colle'},'voice');
      const hy=S.proposeHypothesis({cause:'release_threshold_too_far',confidence:.5,
        evidence:[{metric:'release_latency_ms',aggregate:'p50',sourceRefs:['ep-1','ep-2']}],feedbackRefs:['fb-1']});
      const wrongChannel=S.applyTrial({hypothesisRef:'hy-1',patch:{secondaryReleaseRatio:.5}});
      clock+=1000;
      const tr=S.applyTrial({hypothesisRef:'hy-1',patch:{releaseRatio:.38}});
      const rerunDefault=S.rerun({});
      const rerunNamed=S.rerun({exercise:'aim'});
      const rerunUnknown=S.rerun({exercise:'pincement'});
      const hold=[S.holdAfterResult('pinch_primary'),S.holdAfterResult('pinch_secondary'),S.holdAfterResult('aim')];
      clock+=1000;
      measure({'ep-5':{release_latency_ms:120},'ep-6':{release_latency_ms:130},'ep-8':{release_latency_ms:125}},'pinch_primary');
      const offExercise=S.resolveTrial({trialRef:tr.result.trialRef,verdict:'improved',
        comparisons:[{metric:'acquisition_ms',aggregate:'mean'}],beforeRefs:['ex-1'],afterRefs:['ep-5'],feedbackRefs:[]});
      const secondaryBefore=S.resolveTrial({trialRef:tr.result.trialRef,verdict:'improved',
        comparisons:[{metric:'release_latency_ms',aggregate:'p50'}],beforeRefs:['ep-3'],afterRefs:['ep-5'],feedbackRefs:[]});
      const offMetric=S.resolveTrial({trialRef:tr.result.trialRef,verdict:'improved',
        comparisons:[{metric:'episode_min_ratio',aggregate:'p50'}],beforeRefs:['ep-1'],afterRefs:['ep-5'],feedbackRefs:[]});
      const good=S.resolveTrial({trialRef:tr.result.trialRef,verdict:'improved',
        comparisons:[{metric:'release_latency_ms',aggregate:'p50'}],beforeRefs:['ep-1','ep-2'],afterRefs:['ep-5','ep-6','ep-8'],feedbackRefs:[]});
      const holdAfter=S.holdAfterResult('pinch_primary');
      /* Une cause des deux canaux (sans preuve de canal) : avant primaire, après secondaire. */
      S.rollbackTrial();
      S.proposeHypothesis({cause:'release_confirmation_too_slow',confidence:.5,evidence:[],feedbackRefs:['fb-1']});
      clock+=1000;const tr2=S.applyTrial({hypothesisRef:'hy-2',patch:{releaseMs:30}});
      clock+=1000;measure({'ep-7':{release_latency_ms:100}},'pinch_secondary');
      const mismatched=S.resolveTrial({trialRef:tr2.result.trialRef,verdict:'improved',
        comparisons:[],beforeRefs:['ep-1'],afterRefs:['ep-7'],feedbackRefs:[]});
      out({wrongChannel:wrongChannel.errors[0].code,exercises:tr.result.exercises,moves,
        rerun:[rerunDefault.ok,rerunNamed.ok,rerunUnknown.errors[0].code],hold,
        codes:[offExercise.errors[0].code,secondaryBefore.errors[0].code,mismatched.errors[0].code,
          offMetric.errors[0].code],good:good.ok,holdAfter,exercises2:tr2.result.exercises,
        row:S.status().result.trials[0].exercises,table:A.CAUSE_EXERCISES,stages:C.STAGES,causes:C.HYPOTHESIS_CAUSES});
    """)
    assert result["wrongChannel"] == "barehands_calibration_trial_channel_mismatch"
    assert result["exercises"] == ["pinch_primary"] and result["row"] == ["pinch_primary"]
    assert result["rerun"] == [True, True, "barehands_calibration_exercise_unknown"]
    assert result["moves"] == ["rerun", "rerun"], "sans nom : l'exercice de l'essai ; nommé : celui-là"
    assert result["hold"] == [True, False, False]
    assert result["codes"] == ["barehands_calibration_refs_off_exercise", "barehands_calibration_refs_off_exercise",
                               "barehands_calibration_refs_mismatched", "barehands_calibration_comparison_off_evidence"]
    # Slice 07 adaptative : « tenir puis relâcher » juge aussi le relâchement.
    assert result["exercises2"] == ["pinch_primary", "pinch_secondary", "hold_release"]
    assert result["good"] is True and result["holdAfter"] is False
    # La table couvre toutes les causes, avec des étapes du contrat seulement.
    assert set(result["table"]) == set(result["causes"])
    assert all(stage in result["stages"] for stages in result["table"].values() for stage in stages)


def test_a_trial_is_kept_only_once_judged_and_not_worse(tmp_path):
    result = run_node(tmp_path, WORLD + r"""
      measure({'ep-1':{release_latency_ms:240},'ep-2':{release_latency_ms:260}});
      S.recordFeedback({categories:['release_sticky'],text:'ça colle'},'voice');
      S.proposeHypothesis({cause:'release_confirmation_too_slow',confidence:.5,evidence:[],feedbackRefs:['fb-1']});
      const voiced={consent:{source:'voice',quote:'oui garde-le',verifiedBy:'control_center'}};
      clock+=1000;S.applyTrial({hypothesisRef:'hy-1',patch:{releaseMs:30}});
      clock+=1000;
      const unresolved=await S.acceptTrial(voiced,'voice');
      /* L'avis dit, noté, soutient « improved » sans mesure. */
      const fb=S.recordFeedback({categories:['fine'],text:'là c’est nickel'},'voice');
      clock+=1000;
      const judged=S.resolveTrial({trialRef:'tr-1',verdict:'improved',comparisons:[],beforeRefs:[],afterRefs:[],
        feedbackRefs:[fb.result.feedback.ref]});
      const kept=await S.acceptTrial(voiced,'voice');
      /* Un essai jugé « worse » ne se garde pas, même avec accord. */
      S.proposeHypothesis({cause:'release_threshold_too_far',confidence:.5,evidence:[],feedbackRefs:['fb-1']});
      clock+=1000;S.applyTrial({hypothesisRef:'hy-2',patch:{releaseDeltaRatio:.1}});
      clock+=1000;const fb2=S.recordFeedback({categories:['release_sticky'],text:'c’est pire, ça colle'},'voice');
      clock+=1000;S.resolveTrial({trialRef:'tr-2',verdict:'worse',comparisons:[],beforeRefs:[],afterRefs:[],
        feedbackRefs:[fb2.result.feedback.ref]});
      const worse=await S.acceptTrial(voiced,'voice');
      const button=await S.acceptTrial({},'ui');
      out({unresolved:unresolved.errors[0].code,judged:judged.ok,kept:kept.ok,worse:worse.errors[0].code,
        button:button.errors[0].code,persisted});
    """)
    assert result["unresolved"] == "barehands_calibration_trial_unresolved"
    assert result["judged"] is True and result["kept"] is True
    assert result["worse"] == result["button"] == "barehands_calibration_trial_worse"
    assert result["persisted"] == [{"releaseMs": 30}]


def test_the_flow_holds_the_verdict_of_the_trial_exercise_and_goes_back_to_a_named_one(tmp_path):
    result = run_flow(tmp_path, DOM + DRIVER + r"""
      let hold=true;
      const cal=calOf({holdAfterResult:stage=>hold&&stage==='neutral'});
      cal.start();
      readOn(cal);
      /* Jusqu'au verdict seulement : la revue attend une décision (Slice 07
         adaptative), `feedUntil` en prendrait une. */
      for(let i=0;i<400&&cal.phase()!=='review';i+=1)feed(cal,1,{});
      const settledOn=cal.stepId();
      clock+=K.DEFAULTS.resultMs+50;beat();beat();
      const held=[cal.stepId(),cal.holding(),cal.phase()];
      hold=false;
      const back=cal.rerun('neutral');
      /* Refaire ne saute pas en avant vers une étape jamais jouée (reprise
         QA de la Slice 07) ; en arrière, oui. */
      const named=cal.rerun('pinch_secondary');
      const unknown=cal.rerun('pincement');
      cal.exit('test');
      out({settledOn,held,back,named,unknown});
    """, name="hold")
    assert result["settledOn"] == "neutral"
    assert result["held"] == ["neutral", True, "review"], "le verdict est tenu, le parcours n'avance pas"
    assert result["back"] == "neutral" and result["named"] is None
    assert result["unknown"] is None


def test_the_reporter_says_disabled_and_busy_once_and_stops_on_disabled(tmp_path):
    result = run_node(tmp_path, r"""
      let code='barehands_calibration_session_busy';const logs=[],calls=[],timers=[];let cleared=0;
      const r=A.createSessionReporter({post:async()=>{throw Object.assign(new Error('x'),{code})},
        setInterval:fn=>{timers.push(fn);return 1},clearInterval:()=>{cleared+=1},running:()=>true,
        log:(level,event)=>logs.push([level,event]),onRefused:c=>calls.push(['refused',c]),
        onDisabled:()=>calls.push(['disabled']),onHeld:h=>calls.push(['held',h])});
      r.start();await new Promise(res=>setImmediate(res));
      for(let i=0;i<3;i++){timers[0]();await new Promise(res=>setImmediate(res))}
      code='barehands_disabled';
      timers[0]();await new Promise(res=>setImmediate(res));
      timers[0]();await new Promise(res=>setImmediate(res));
      out({calls,logs,cleared,session:r.session()});
    """)
    assert result["calls"] == [["refused", "barehands_calibration_session_busy"], ["disabled"]]
    errors = [event for level, event in result["logs"] if level == "error"]
    assert errors == [], "aucun refus attendu ne part dans Error Logs"
    assert [e for _, e in result["logs"]].count("barehands.calibration_session_busy") == 1
    assert result["cleared"] == 1 and result["session"] is None, "éteint : plus de battement"


def test_the_channel_presents_the_session_and_resyncs_without_counting_a_failure(tmp_path):
    result = run_node(tmp_path, r"""
      const urls=[];let session=null,abortNext=null;let polls=0;
      const channel=M.createCommandChannel({
        request:(url,opts)=>{urls.push(url);polls+=1;
          if(polls===1)return new Promise((_,reject)=>{abortNext=()=>reject(new Error('aborted'))});
          if(polls>=3){channel.setEnabled(false)}
          return Promise.resolve({status:200,body:{command:null}})},
        surface:()=>({}),now:()=>0,sleep:async()=>{},random:()=>0.5,log:()=>{},
        calibrationSession:()=>session,abort:()=>{if(abortNext)abortNext()}});
      channel.setEnabled(true);
      await new Promise(res=>setImmediate(res));
      session='held-session-0123456789';
      const resynced=channel.resync();
      for(let i=0;i<6;i++)await new Promise(res=>setImmediate(res));
      out({urls,resynced,state:channel.state()});
    """)
    assert result["resynced"] is True
    assert "calibration=" not in result["urls"][0]
    assert result["urls"][1].endswith("&calibration=held-session-0123456789")
    assert result["state"]["failures"] == 0, "une coupure voulue n'est pas une panne"


def test_the_page_wires_the_hold_the_named_rerun_and_the_remote_switch_off():
    source = (RUNTIME / "control_center_barehands.js").read_text(encoding="utf-8")
    assert "holdAfterResult:stage=>!!(agentSession&&agentSession.holdAfterResult(stage))" in source
    assert "rerun:payload=>agentCall('rerun',payload)" in source
    assert "if(calibration&&calibration.isRunning())calibration.exit('Bare Hands éteint');" in source
    assert "onHeld:()=>{const ch=window.JarvisBarehandsCommandChannel;if(ch&&typeof ch.resync==='function')ch.resync()}" in source
    commands = COMMANDS.read_text(encoding="utf-8")
    assert "agent&&typeof agent.session==='function'?agent.session():null" in commands
    assert "stateRef:()=>agentSession?agentSession.stateRef():null" in source
    assert "agentCoach.announce(AGENT.userText(" in source


def test_the_keep_button_lets_the_measurements_speak_before_the_feeling(tmp_path):
    """Constat de la QA réelle (round 5) : « Garder ce réglage » gardait un essai
    mesurablement pire. Avec des mesures sous l'essai, le bouton compare sur les
    métriques de la preuve et le contrat refuse un « mieux » démenti."""

    result = run_node(tmp_path, WORLD + COACH_DOM + r"""
      measure({'ep-1':{release_latency_ms:146},'ep-2':{release_latency_ms:187},'ep-3':{release_latency_ms:160}});
      S.recordFeedback({categories:['release_sticky'],text:'ça colle'},'voice');
      S.proposeHypothesis({cause:'release_confirmation_too_slow',confidence:.5,
        evidence:[{metric:'release_latency_ms',aggregate:'p50',sourceRefs:['ep-1','ep-2','ep-3']}],feedbackRefs:['fb-1']});
      clock+=1000;S.applyTrial({hypothesisRef:'hy-1',patch:{releaseMs:120}});
      clock+=1000;measure({'ep-4':{release_latency_ms:154},'ep-5':{release_latency_ms:247}});
      clock+=1000;const tooFew=await S.acceptTrial({},'ui');
      measure({'ep-6':{release_latency_ms:230}});
      clock+=1000;
      const panel=A.createCoachPanel({document,session:S,log:()=>{}});panel.mount(region);panel.refresh();
      find(panel.node(),'data-coach-action','accept').listeners.click();await settle();
      const line=panel.node().children[2].textContent;
      const st=S.status().result;
      /* Sans mesure sous l'essai : l'avis seul suffit. */
      S.rollbackTrial();
      clock+=1000;S.resolveTrial({trialRef:'tr-1',verdict:'inconclusive',comparisons:[],beforeRefs:[],afterRefs:[],feedbackRefs:[]});
      S.proposeHypothesis({cause:'release_threshold_too_far',confidence:.5,evidence:[],feedbackRefs:['fb-1']});
      clock+=1000;S.applyTrial({hypothesisRef:'hy-2',patch:{releaseDeltaRatio:.1}});
      clock+=1000;const felt=await S.acceptTrial({},'ui');
      out({tooFew:tooFew.errors[0].code,line,hyp:st.hypotheses[0],trial:st.trials[0].verdict,felt:felt.ok,persisted});
    """)
    assert result["tooFew"] == "barehands_calibration_too_few_measures"
    assert result["line"] == "Les mesures disent le contraire — refaites l’exercice ou annulez l’essai."
    assert result["trial"] is None and result["hyp"]["confidence"] == 0.5 and result["hyp"]["status"] == "open"
    assert result["felt"] is True and result["persisted"] == [{"releaseDeltaRatio": 0.1}]


def test_before_rows_follow_the_effective_state_across_an_accept(tmp_path):
    """« Avant » l'essai 2 = mesures prises sous l'état gardé de l'essai 1 ; les
    mesures d'avant l'essai 1 sont refusées (elles incluraient son gain)."""

    result = run_node(tmp_path, WORLD + r"""
      measure({'ep-1':{release_latency_ms:250},'ep-2':{release_latency_ms:260},'ep-3':{release_latency_ms:255}});
      S.recordFeedback({categories:['release_sticky'],text:'ça colle'},'voice');
      S.proposeHypothesis({cause:'release_confirmation_too_slow',confidence:.5,
        evidence:[{metric:'release_latency_ms',aggregate:'p50',sourceRefs:['ep-1','ep-2','ep-3']}],feedbackRefs:['fb-1']});
      clock+=1000;S.applyTrial({hypothesisRef:'hy-1',patch:{releaseMs:30}});
      clock+=1000;measure({'ep-4':{release_latency_ms:150},'ep-5':{release_latency_ms:160},'ep-6':{release_latency_ms:155}});
      S.resolveTrial({trialRef:'tr-1',verdict:'improved',comparisons:[{metric:'release_latency_ms',aggregate:'p50'}],
        beforeRefs:['ep-1','ep-2','ep-3'],afterRefs:['ep-4','ep-5','ep-6'],feedbackRefs:[]});
      const kept=await S.acceptTrial({consent:{source:'voice',quote:'oui',verifiedBy:'control_center'}},'voice');
      const afterAccept=S.stateRef();
      clock+=1000;measure({'ep-7':{release_latency_ms:150}});
      S.proposeHypothesis({cause:'release_threshold_too_far',confidence:.5,
        evidence:[{metric:'release_latency_ms',aggregate:'p50',sourceRefs:['ep-4','ep-5','ep-6']}],feedbackRefs:['fb-1']});
      clock+=1000;const tr2=S.applyTrial({hypothesisRef:'hy-2',patch:{releaseDeltaRatio:.1}});
      clock+=1000;measure({'ep-8':{release_latency_ms:120},'ep-9':{release_latency_ms:125},'ep-10':{release_latency_ms:122}});
      const old=S.resolveTrial({trialRef:'tr-2',verdict:'improved',comparisons:[{metric:'release_latency_ms',aggregate:'p50'}],
        beforeRefs:['ep-1','ep-2','ep-3'],afterRefs:['ep-8','ep-9','ep-10'],feedbackRefs:[]});
      const good=S.resolveTrial({trialRef:'tr-2',verdict:'improved',comparisons:[{metric:'release_latency_ms',aggregate:'p50'}],
        beforeRefs:['ep-4','ep-5','ep-7'],afterRefs:['ep-8','ep-9','ep-10'],feedbackRefs:[]});
      const trialStates=S.status().result.trials.map(t=>[t.ref,t.baseStateId,t.stateId]);
      out({kept:kept.ok,afterAccept,old:old.errors[0].code,good:good.ok?good.result.deltas[0]:good.errors,rows:trialStates,
        tr2:[tr2.result.baseRef]});
    """)
    assert result["kept"] is True and result["afterAccept"] == 1, "garder ne change pas l'état effectif"
    assert result["old"] == "barehands_calibration_refs_misplaced"
    assert result["good"]["before"] == 150 and result["good"]["after"] == 122, "le gain gardé n'est pas recompté"
    assert result["rows"] == [["tr-1", 0, 1], ["tr-2", 1, 2]]


def test_a_single_pinch_does_not_make_a_measured_verdict_and_status_shows_the_keys_in_play(tmp_path):
    result = run_node(tmp_path, WORLD + r"""
      measure({'ep-1':{release_latency_ms:250},'ep-2':{release_latency_ms:260},'ep-3':{release_latency_ms:255}});
      S.recordFeedback({categories:['release_sticky'],text:'ça colle'},'voice');
      S.proposeHypothesis({cause:'release_confirmation_too_slow',confidence:.5,
        evidence:[{metric:'release_latency_ms',aggregate:'p50',sourceRefs:['ep-1','ep-2','ep-3']}],feedbackRefs:['fb-1']});
      const shown=Object.keys(S.status().result.values.effective);
      clock+=1000;S.applyTrial({hypothesisRef:'hy-1',patch:{releaseMs:30}});
      clock+=1000;measure({'ep-4':{release_latency_ms:120}});
      const one=S.resolveTrial({trialRef:'tr-1',verdict:'improved',comparisons:[{metric:'release_latency_ms',aggregate:'p50'}],
        beforeRefs:['ep-1','ep-2','ep-3'],afterRefs:['ep-4'],feedbackRefs:[]});
      clock+=1000;const fb=S.recordFeedback({categories:['fine'],text:'nickel'},'voice');
      clock+=1000;const felt=S.resolveTrial({trialRef:'tr-1',verdict:'improved',comparisons:[],beforeRefs:[],afterRefs:[],
        feedbackRefs:[fb.result.feedback.ref]});
      out({shown,one:one.errors[0].code,felt:felt.ok,min:A.MIN_AFTER_EPISODES});
    """)
    assert result["one"] == "barehands_calibration_too_few_measures" and result["min"] == 3
    assert result["felt"] is True, "l'avis noté reste possible"
    assert {"releaseFrames", "releaseMs"} <= set(result["shown"]), "les clés de la cause ouverte, même au défaut"


def test_the_screen_speaks_user_french_on_refusals(tmp_path):
    result = run_node(tmp_path, r"""
      out({worse:A.userText('barehands_calibration_trial_worse'),other:A.userText('barehands_whatever'),
        all:Object.values(A.USER_TEXT)});
    """)
    assert result["worse"] == "Ce réglage a été jugé moins bon : il ne se garde pas. Annulez-le."
    for text in result["all"] + [result["other"]]:
        assert "tr-" not in text and "worse" not in text and "barehands_" not in text


def test_a_feeling_only_improvement_counts_but_never_like_a_measured_one(tmp_path):
    """Round 6 : l'avis de l'utilisateur est une entrée de premier rang, mais un
    « improved » sans mesure qui le montre ne rend pas l'hypothèse « supported »
    et ne monte la confiance que vers 0,7. Cas de la QA : tr-2 avec quatre
    mesures après et aucune d'avant sous l'état courant (juste après un essai
    gardé) ; tr-3 sans aucune mesure après. Bouton et voix partagent la règle."""

    result = run_node(tmp_path, WORLD + r"""
      const consent={consent:{source:'voice',quote:'oui',verifiedBy:'control_center'}};
      measure({'ep-1':{release_latency_ms:250},'ep-2':{release_latency_ms:260},'ep-3':{release_latency_ms:255}});
      S.recordFeedback({categories:['release_sticky'],text:'ça colle'},'voice');
      S.proposeHypothesis({cause:'release_confirmation_too_slow',confidence:.5,
        evidence:[{metric:'release_latency_ms',aggregate:'p50',sourceRefs:['ep-1','ep-2','ep-3']}],feedbackRefs:['fb-1']});
      clock+=1000;S.applyTrial({hypothesisRef:'hy-1',patch:{releaseMs:30}});
      clock+=1000;measure({'ep-4':{release_latency_ms:150},'ep-5':{release_latency_ms:160},'ep-6':{release_latency_ms:155}});
      const measured=S.resolveTrial({trialRef:'tr-1',verdict:'improved',comparisons:[{metric:'release_latency_ms',aggregate:'p50'}],
        beforeRefs:['ep-1','ep-2','ep-3'],afterRefs:['ep-4','ep-5','ep-6'],feedbackRefs:[]});
      await S.acceptTrial(consent,'voice');
      /* tr-2 : quatre mesures après, aucune d'avant sous l'état gardé → l'avis seul (voix). */
      S.proposeHypothesis({cause:'release_threshold_too_far',confidence:.4,
        evidence:[{metric:'release_latency_ms',aggregate:'p50',sourceRefs:['ep-4','ep-5','ep-6']}],feedbackRefs:['fb-1']});
      clock+=1000;S.applyTrial({hypothesisRef:'hy-2',patch:{releaseDeltaRatio:.1}});
      clock+=1000;measure({'ep-7':{release_latency_ms:140},'ep-8':{release_latency_ms:141},'ep-9':{release_latency_ms:139},
        'ep-10':{release_latency_ms:138}});
      clock+=1000;const fb=S.recordFeedback({categories:['fine'],text:'là c’est nickel'},'voice');
      clock+=1000;const felt=S.resolveTrial({trialRef:'tr-2',verdict:'improved',comparisons:[],beforeRefs:[],afterRefs:[],
        feedbackRefs:[fb.result.feedback.ref]});
      const keptFelt=await S.acceptTrial(consent,'voice');
      /* tr-3 : aucune mesure après → le bouton juge sur l'avis. */
      S.proposeHypothesis({cause:'release_confirmation_too_fast',confidence:.8,evidence:[],feedbackRefs:['fb-1']});
      clock+=1000;S.applyTrial({hypothesisRef:'hy-3',patch:{releaseDoubtMaxMs:300}});
      clock+=1000;const button=await S.acceptTrial({},'ui');
      const st=S.status().result;
      out({measured:[measured.result.basis,measured.result.hypotheses[0]],felt:[felt.result.basis,felt.result.hypotheses[0]],
        keptFelt:keptFelt.result.basis,button:[button.ok,button.result.basis],
        hy3:st.hypotheses.find(h=>h.ref==='hy-3'),trials:st.trials.map(t=>[t.ref,t.verdict,t.basis])});
    """)
    assert result["measured"][0] == "measured"
    assert result["measured"][1]["confidence"] == pytest.approx(0.725) and result["measured"][1]["status"] == "supported"
    basis, hyp = result["felt"]
    assert basis == "feeling"
    assert hyp["confidence"] == pytest.approx(0.55) and hyp["status"] == "open", "à mi-chemin de 0,7, jamais supported"
    assert result["keptFelt"] == "feeling"
    assert result["button"] == [True, "feeling"]
    assert result["hy3"]["confidence"] == 0.8 and result["hy3"]["status"] == "open", "l'avis seul ne dépasse pas 0,7 ni ne baisse"
    assert result["trials"] == [["tr-1", "improved", "measured"], ["tr-2", "improved", "feeling"],
                                ["tr-3", "improved", "feeling"]]


def test_status_carries_every_advertised_key_from_the_first_call_and_every_measured_verdict_needs_three(tmp_path):
    result = run_node(tmp_path, WORLD + r"""
      const st=S.status().result;
      measure({'ep-1':{release_latency_ms:250},'ep-2':{release_latency_ms:260},'ep-3':{release_latency_ms:255}});
      S.recordFeedback({categories:['release_sticky'],text:'ça colle'},'voice');
      S.proposeHypothesis({cause:'release_confirmation_too_slow',confidence:.5,
        evidence:[{metric:'release_latency_ms',aggregate:'p50',sourceRefs:['ep-1','ep-2','ep-3']}],feedbackRefs:['fb-1']});
      clock+=1000;S.applyTrial({hypothesisRef:'hy-1',patch:{releaseMs:30}});
      clock+=1000;measure({'ep-4':{release_latency_ms:250},'ep-5':{release_latency_ms:251}});
      const noChange=S.resolveTrial({trialRef:'tr-1',verdict:'no_change',comparisons:[{metric:'release_latency_ms',aggregate:'p50'}],
        beforeRefs:['ep-1','ep-2','ep-3'],afterRefs:['ep-4','ep-5'],feedbackRefs:[]});
      out({effective:Object.keys(st.values.effective),saved:Object.keys(st.values.saved),keys:C.TRIAL_ADVERTISED_KEYS,
        hypotheses:st.hypotheses.length,noChange:noChange.errors[0].code});
    """)
    assert result["hypotheses"] == 0
    assert result["effective"] == result["keys"] and result["saved"] == result["keys"]
    assert result["noChange"] == "barehands_calibration_too_few_measures"
