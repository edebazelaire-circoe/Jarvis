"""Bare Hands — revue d'exercice, reprise QA de la Slice 07 (tâche adaptative).

Ce que la QA a trouvé et qui est tenu ici (décisions 56 à 59) :

- « passe » à la voix sur une revue réussie **passe** (mesure non gardée),
  comme le bouton ; le reçu dit ce qui a été décidé ;
- Entrée tenue, double-clic : le focus ne tombe jamais sur une commande qui
  commet après un changement d'état, une touche répétée n'active rien, une
  commande n'accepte rien avant son armement ;
- le rapport a sa mise en page, sans compte à rebours ni ligne périmée ;
- Échap referme d'abord un sous-panneau, et demande confirmation avant de
  quitter ;
- tenir puis relâcher : trois catégories exclusives, aucune latence négative ;
- Refaire ne saute pas en avant ; le détour revient où l'on en était ;
- l'assistant n'explique que l'exercice en revue, sans chiffre ;
- un essai qui attend sa mesure bloque « continuer » à la voix ;
- le moteur se réveille de lui-même pendant une calibration.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_barehands_calibration_review_js import run  # noqa: E402
from test_barehands_lifecycle_js import WORLD, run_node as run_lifecycle  # noqa: E402

#: La séance de l'agent, branchée sur le vrai parcours, avec un gestionnaire
#: d'essai minimal (les reçus de la décision 48).
AGENT = r"""
const agentOf=(cal,extra)=>{
  const stack=[];let serial=0;
  const trials={apply(patch){serial+=1;const trialId=`tr-${serial}`;stack.push({trialId,patch});
      return {ok:true,code:null,applied:{...patch},rejected:[],trialId,appliedAt:clock}},
    rollback(){const top=stack.pop();return top?{ok:true,code:null,applied:{},rejected:[],trialId:top.trialId,
      undone:[top.trialId],appliedAt:clock}:{ok:false,code:'barehands_trial_nothing_to_rollback'}},
    async accept(){return {ok:false,code:'barehands_trial_nothing_to_accept'}},
    status(){return {active:stack.length>0,trialId:stack.length?stack[stack.length-1].trialId:null}}};
  return A.createCalibrationAgentSession(Object.assign({contracts:C,flow:()=>cal,trials:()=>trials,
    values:()=>({effective:{},saved:{},trial:{}}),now,held:()=>true,origin:cal.session().clockOrigin},extra||{}));
};
const codeOf=r=>r.ok?null:r.errors[0].code;
/* Un détecteur scripté, même interface que `createPinchChannel` : il appuie
   sous `press`, relâche au-dessus de `release`, et `plan(closure, s, down)`
   peut forcer l'état voulu (vrai = appuyé) pour la fermeture en cours. */
const scriptedOf=(plan,press,release)=>()=>{let down=false,closeAt=null,closures=0;
  return {state:()=>down?'pressed':'open',update(s){
    const ev=[];const closing=s.ratio<(press||.3);
    if(closing&&closeAt===null){closeAt=s.now;closures+=1}
    if(s.ratio>(release||.3))closeAt=null;
    let want=down?s.ratio<(release||.3):closing;
    const forced=plan?plan(closures,s,closeAt):undefined;
    if(forced==='cancel'&&down){down=false;ev.push({phase:'cancel',t:s.now});return ev}
    if(forced!==undefined&&forced!=='cancel')want=forced;
    if(want&&!down){down=true;ev.push({phase:'down',t:s.now})}
    else if(!want&&down){down=false;ev.push({phase:'up',t:s.now})}
    return ev}}};
/* Tenir 880 ms, puis rouvrir **en rampe** (cinq images de .15 à .6) : le
   relâchement du détecteur tombe au milieu de la réouverture, entre le début
   de l'ouverture et la fin de l'épisode. */
const ramped=i=>{const k=i%80;return {stillness:.5,
  primaryRatio:k<55?.15:k<60?.15+(k-54)*.09:.6}};
const holdRun=(plan,pattern,extra)=>{
  const cal=calOf(Object.assign({pinchChannel:scriptedOf(plan,.3,.3)},extra||{}));
  cal.start();toStage(cal,'hold_release');readOn(cal);
  const phase=untilReview(cal,pattern||ramped,2000);
  const review=cal.review();
  const ex=review&&review.lines.find(l=>l.metric==='premature_drop_count');
  const row=ex?cal.session().measurements[ex.refs[0]]:null;
  const eps=cal.session().episodes.filter(e=>e.stage==='hold_release').map(e=>[e.premature,e.releaseLatencyMs]);
  const out={phase,status:review&&review.status,row,eps,lines:reviewLis().map(l=>[l.metric,l.text]),trace:traced(cal)};
  cal.exit('test');
  return out;
};
"""


def run_qa(tmp_path: Path, source: str, name: str) -> dict:
    return run(tmp_path, AGENT + source, name)


def test_voice_pass_on_a_successful_review_skips_and_the_receipt_says_so(tmp_path):
    from jarvis.domain import barehands_command as vocab

    result = run_qa(tmp_path, r"""
      const cal=calOf();cal.start();
      const S=agentOf(cal);
      readOn(cal);untilReview(cal,{});
      const passed=S.command('next',{reason:'not_relevant'});
      const afterPass={step:cal.stepId(),jitter:null};
      readOn(cal);untilReview(cal,{cPose:.9,gapPalms:.65,indexReachPalms:1.8,secondaryRatio:.9});
      const validated=S.command('next',{});
      /* Une revue **ratée**, sans raison : refus nommé, rien ne bouge. */
      readOn(cal);arm(cal);clock+=6000;beat();
      const failedBare=S.command('next',{});
      const stillThere=[cal.stepId(),cal.phase()];
      const failedWithReason=S.command('next',{reason:'later'});
      while(cal.isRunning()&&stepActions(flowRoot()).includes('skip'))skipStep(cal);
      const payload=cal.result().payload;
      out({passed:passed.result,validated:validated.result,failedBare:codeOf(failedBare),stillThere,
        failedWithReason:failedWithReason.result&&failedWithReason.result.decision,
        neutral:payload.stages.neutral,jitter:payload.hands.left.jitterPx,decisions:reviews(cal).slice(0,3)});
    """, "voicePass")
    assert result["passed"]["decision"] == "skipped"
    assert result["validated"]["decision"] == "validated"
    for receipt in (result["passed"], result["validated"]):
        parsed = vocab.parse_command_receipt("calibration_next_exercise", {
            "outcome": "applied", "lifecycle": "active", "code": None, "reason": None, "result": receipt})
        assert parsed["result"]["decision"] in ("validated", "skipped")
    # Passer à la voix, comme au bouton : la mesure réussie n'est pas gardée.
    assert result["neutral"] == {"status": "skipped", "reason": "barehands_stage_skip_not_relevant",
                                 "samples": result["neutral"]["samples"]}
    assert result["jitter"] is None
    assert result["failedBare"] == "barehands_calibration_skip_reason_required"
    assert result["stillThere"] == ["pinch_primary", "review"]
    assert result["failedWithReason"] == "skipped"
    assert result["decisions"] == [["neutral", "skipped", "skipped", "not_relevant", 1],
                                   ["c_pose", "validated", "ok", None, 1],
                                   ["pinch_primary", "skipped", "failed", "later", 1]]


def test_the_button_pass_on_a_successful_review_drops_the_measure(tmp_path):
    result = run_qa(tmp_path, r"""
      const cal=calOf();cal.start();
      readOn(cal);untilReview(cal,{});
      press(flowRoot(),'skip');press(flowRoot(),'skip-later');
      while(cal.isRunning()&&stepActions(flowRoot()).includes('skip'))skipStep(cal);
      out({jitter:cal.result().payload.hands.left.jitterPx,neutral:cal.result().payload.stages.neutral.status});
    """, "buttonPass")
    assert result == {"jitter": None, "neutral": "skipped"}


def test_held_keys_and_double_clicks_never_commit_the_next_screen(tmp_path):
    result = run_qa(tmp_path, r"""
      const cal=calOf();cal.start();readOn(cal);untilReview(cal,{});
      /* Aussitôt dessinée, la commande n'est pas armée : un clic dans la
         même milliseconde (la fin d'un double-clic) est ignoré. */
      pressNow(flowRoot(),'validate');
      const early=[cal.stepId(),cal.phase()];
      press(flowRoot(),'validate');
      const moved=[cal.stepId(),cal.phase()];
      /* Le second clic du double-clic tombe sur « Passer… » de l'écran suivant. */
      pressNow(flowRoot(),'skip');
      const second=stepActions(flowRoot());
      /* Entrée tenue : la répétition est empêchée, la première pression non. */
      const button=allButtons(flowRoot()).find(n=>n.getAttribute('data-flow-action')==='skip');
      let repeatPrevented=false,firstPrevented=false;
      button.fire('keydown',{key:'Enter',repeat:true,preventDefault(){repeatPrevented=true}});
      button.fire('keydown',{key:'Enter',repeat:false,preventDefault(){firstPrevented=true}});
      /* Le focus après chaque changement d'état ne porte jamais une commande
         qui commet. */
      const focusIntro=document.activeElement&&document.activeElement.tagName;
      press(flowRoot(),'skip');
      const focusChooser=document.activeElement&&document.activeElement.getAttribute('data-flow-action');
      pressNow(flowRoot(),'skip-not_relevant');
      const chooserHeld=[cal.stepId(),stepActions(flowRoot()).length];
      out({early,moved,second,repeatPrevented,firstPrevented,focusIntro,focusChooser,chooserHeld,armMs:300});
    """, "held")
    assert result["early"] == ["neutral", "review"], "un clic avant l'armement ne valide rien"
    assert result["moved"] == ["c_pose", "intro"]
    assert result["second"] == ["skip", "exit"], "le double-clic n'ouvre pas le choix de l'écran suivant"
    assert result["repeatPrevented"] is True and result["firstPrevented"] is False
    assert result["focusIntro"] == "H2"
    assert result["focusChooser"] == "back"
    assert result["chooserHeld"] == ["c_pose", 5], "une raison n'est pas prise dans la même milliseconde"


def test_escape_closes_the_sub_panel_first_and_confirms_before_quitting(tmp_path):
    result = run_qa(tmp_path, r"""
      const adjusted=[];const cancelled=[];
      const cal=calOf({adjust:stage=>{adjusted.push(stage);return true},canAdjust:()=>true,
        onCancelled:why=>cancelled.push(why)});
      cal.start();readOn(cal);untilReview(cal,{});
      press(flowRoot(),'skip');
      document.fire('keydown',{key:'Escape'});
      const afterChooser={running:cal.isRunning(),actions:stepActions(flowRoot())};
      press(flowRoot(),'adjust');
      document.fire('keydown',{key:'Escape'});
      const afterAdjust={running:cal.isRunning(),adjusted:adjusted.slice(),
        focus:document.activeElement&&document.activeElement.getAttribute('data-flow-action')};
      document.fire('keydown',{key:'Escape'});
      const armed={running:cal.isRunning(),note:noteText()};
      /* Une touche tenue ne confirme pas. */
      document.fire('keydown',{key:'Escape',repeat:true});
      const repeat=cal.isRunning();
      /* Trop tard : la confirmation est échue, la pression réarme. */
      clock+=2500;
      document.fire('keydown',{key:'Escape'});
      const rearmed=cal.isRunning();
      document.fire('keydown',{key:'Escape'});
      out({afterChooser,afterAdjust,armed,repeat,rearmed,quit:cal.isRunning(),cancelled,saved:saved.length});
    """, "escape")
    assert result["afterChooser"] == {"running": True,
                                      "actions": ["rerun", "adjust", "validate", "skip", "exit"]}
    assert result["afterAdjust"]["running"] is True and result["afterAdjust"]["adjusted"] == ["neutral", None]
    assert result["afterAdjust"]["focus"] == "adjust"
    assert result["armed"]["running"] is True and "encore sur Échap" in result["armed"]["note"]
    assert result["repeat"] is True and result["rearmed"] is True
    assert result["quit"] is False and result["cancelled"] == ["échap"] and result["saved"] == 0


def test_the_report_has_its_own_layout_no_countdown_and_no_stale_assistant_line(tmp_path):
    result = run_qa(tmp_path, r"""
      const adjusted=[];
      const cal=calOf({adjust:stage=>{adjusted.push(stage);return true},canAdjust:()=>true});
      cal.start();
      while(cal.isRunning()&&stepActions(flowRoot()).includes('skip'))skipStep(cal);
      clock+=60000;
      const meta=deadlineText(flowRoot());
      out({report:flowRoot().getAttribute('data-report'),meta,adjusted,
        sheet:K.STYLE.includes('[data-report="1"]'),
        saveDoor:cal.save(),saved:saved.length,running:cal.isRunning()});
    """, "report")
    assert result["report"] == "1", "la coque sait qu'elle montre un rapport"
    assert result["sheet"] is True
    assert result["meta"][1] == "", "aucun « 0 s restantes » sur le rapport"
    assert result["adjusted"][-1] is None, "ressentis et ligne de l'assistant refermés au rapport"
    # Rien de mesuré : même par la porte publique, rien n'est écrit.
    assert result["saved"] == 0 and result["running"] is False


@pytest.mark.parametrize("case", ["clean", "bounce", "missed", "cancel", "early_up", "sticky"])
def test_hold_release_categories_are_exclusive_and_latency_never_negative(tmp_path, case):
    plans = {
        # Un relâchement franc, au milieu de la réouverture : ni prématuré ni collé.
        "clean": "null",
        # Un rebond pendant la réouverture : repris dans le même geste → prématuré.
        "bounce": "(c,s)=>c===2&&s.ratio>.3&&s.ratio<.5?(s.ratio<.4?false:true):undefined",
        # Aucun appui sur le deuxième : appui manqué, pas relâchement collé.
        "missed": "(c,s)=>c===2?false:undefined",
        # Annulé doigts fermés : prématuré, **pas** collé.
        "cancel": "(c,s,at)=>c===2&&at!==null&&s.now-at>=300&&s.now-at<320?'cancel':c===2&&at!==null&&s.now-at>=320&&s.ratio<.3?false:undefined",
        # Lâché doigts fermés (sans reprise) : prématuré, latence non comptée.
        "early_up": "(c,s,at)=>c===2&&at!==null&&s.now-at>=300&&s.ratio<.3?false:undefined",
        # Le contact du deuxième ne lâche pas à la réouverture.
        # (il n'est défait qu'au pincement suivant : c'est ce qui fait un collé)
        "sticky": "(c,s,at)=>c===2&&s.ratio>=.3?true:c===3&&at===s.now?'cancel':undefined",
    }
    result = run_qa(tmp_path, f"out(holdRun({plans[case]}));", f"hold_{case}")
    assert result["phase"] == "review" and result["status"] == "ok", result
    row = result["row"]
    assert all(t["refsExist"] and t["shown"] == t["again"] for t in result["trace"])
    assert row["release_latency_ms"] is None or row["release_latency_ms"] >= 0, row
    expected = {
        "clean": (0, 0.0, 0.0),
        "bounce": (1, 0.0, 0.0),
        "missed": (0, 0.0, 1 / 3),
        "cancel": (1, 0.0, 0.0),
        "early_up": (1, 0.0, 0.0),
        "sticky": (0, 1 / 3, 0.0),
    }[case]
    assert (row["premature_drop_count"], row["missed_release_rate"], row["missed_press_rate"]) == \
        pytest.approx(expected), row


def test_short_holds_are_neither_counted_live_nor_measured(tmp_path):
    result = run_qa(tmp_path, r"""
      /* Deux pincements courts (160 ms), puis des tenues : l'écran ne compte
         que les tenues, et la mesure ne range qu'elles. */
      const pattern=i=>{if(i<60){const k=i%30;return {stillness:.5,primaryRatio:k<10?.15:.6}}
        return ramped(i-60)};
      const cal=calOf({pinchChannel:scriptedOf(null,.3,.3)});
      cal.start();toStage(cal,'hold_release');readOn(cal);
      let at3=null;
      for(let i=0;i<2000&&cal.phase()!=='review';i+=1){
        clock+=16;cal.feed({now:clock,hands:[hand(pattern(i))]});
        if(i===60+80+20)at3=[cal.phase(),find(flowRoot(),C.DOM.flowProgressClass)[0].children[0].getAttribute('data-at')];
      }
      const review=cal.review();
      const held=cal.session().episodes.filter(e=>e.stage==='hold_release').length;
      out({at3,status:review.status,held,count:review.lines.find(l=>l.metric==='episode_duration_ms').value});
    """, "shortHolds")
    assert result["at3"] == ["running", "0.33"], "deux courts et une tenue font une tenue sur trois"
    assert result["status"] == "ok" and result["held"] == 3 and result["count"] == 3


def test_rerun_never_jumps_forward_and_the_detour_returns_after_the_review(tmp_path):
    result = run_qa(tmp_path, r"""
      const cal=calOf();cal.start();
      const S=agentOf(cal);
      readOn(cal);untilReview(cal,{});
      const forward=cal.rerun('aim');
      const voiceForward=codeOf(S.command('rerun',{exercise:'aim'}));
      const can=cal.canRerun('aim');
      cal.validate();
      for(let i=0;i<4;i+=1)skipStep(cal);           // c_pose, pinch_primary, hold, secondary
      readOn(cal);clickOnce(cal);clickOnce(cal);clickOnce(cal);
      const atAim=[cal.stepId(),cal.phase()];
      const back=cal.rerun('neutral');
      readOn(cal);untilReview(cal,{});cal.validate();
      const returned=[cal.stepId(),cal.phase()];
      out({forward,voiceForward,can,atAim,back,returned});
    """, "forward")
    assert result["forward"] is None
    assert result["voiceForward"] == "barehands_calibration_exercise_not_played"
    assert result["can"] == {"ok": False, "code": "barehands_calibration_exercise_not_played"}
    assert result["atAim"] == ["aim", "review"]
    assert result["back"] == "neutral"
    # Le détour revient **après** la revue quittée (la visée était soldée) :
    # au premier temps de la fenêtre, sans rejouer la visée.
    assert result["returned"] == ["drag", "intro"]


def test_an_unnamed_rerun_in_a_system_skipped_review_targets_that_review(tmp_path):
    result = run_qa(tmp_path, r"""
      /* Scène éteinte : l'écran de la fenêtre s'ouvre directement en revue
         « passée », sans verdict joué ; le dernier exercice joué est la visée. */
      const cal=calOf();bench.state.scene=false;cal.start();
      toStage(cal,'aim');readOn(cal);clickOnce(cal);clickOnce(cal);clickOnce(cal);cal.validate();
      const at=[cal.stepId(),cal.phase(),cal.review().status];
      const again=cal.rerun();
      out({at,again});
    """, "systemReview")
    assert result["at"] == ["drop", "review", "skipped"]
    assert result["again"] == "drop", "« refais » vise la revue à l'écran, pas l'exercice joué avant"


def test_drop_judges_both_axes_and_places_the_destination_across_the_screen(tmp_path):
    result = run_qa(tmp_path, r"""
      benchRect=true;
      const cal=calOf();cal.start();toStage(cal,'drop');readOn(cal);
      const node=deep(flowRoot()).find(n=>n.getAttribute('data-drop')==='1');
      const destX=parseFloat(node.style.left)+parseFloat(node.style.width)/2;
      const box=bench.state.box;const winX=640+(box.x+box.w/2)*6;
      /* Aligné en x, décalé de 150 px en y : hors destination. */
      const w=parseFloat(node.style.width),h=parseFloat(node.style.height);
      const top=parseFloat(node.style.top);
      bench.grab();cal.tick();feed(cal,3,{primaryRatio:.15});
      bench.drop('move',{x:(destX-640)/6-w/12,y:(top+h/2+150-360)/6-h/12,w:w/6,h:h/6});cal.tick();
      out({destX,winX,width:1280,winWidth:box.w*6,phase:cal.phase(),note:noteText()});
    """, "dropAxes")
    # Ailleurs que la fenêtre, d'au moins sa demi-largeur : un vrai trajet.
    assert abs(result["destX"] - result["winX"]) > result["winWidth"] / 2, "la destination recouvre la fenêtre"
    assert result["phase"] == "running" and "px du centre" in result["note"]


def test_frame_events_keep_their_own_instants_and_the_agent_shares_the_flow_origin(tmp_path):
    result = run_qa(tmp_path, r"""
      const cal=calOf();cal.start();
      clock+=5000;
      const S=agentOf(cal);                            // créée cinq secondes après la séance
      const SKEW=7e5;
      readOn(cal);
      for(let i=0;i<1400&&cal.phase()!=='review';i+=1){clock+=16;
        cal.feed({now:clock+SKEW,hands:[hand({})]})}
      cal.validate();skipStep(cal);readOn(cal);
      for(let i=0;i<1400&&cal.phase()!=='review';i+=1){clock+=16;
        cal.feed({now:clock+SKEW,hands:[hand({stillness:.5,primaryRatio:i%30<15?.15:.6,primaryConfidence:1})]})}
      const fb=S.recordFeedback({categories:['release_sticky'],text:'ça colle'},'voice');
      const presses=cal.session().samples.filter(s=>s.event.kind==='pinch_press').map(s=>s.t);
      out({presses,episodes:cal.session().episodes.length,fbT:fb.result.feedback.t,now:cal.sessionTime()});
    """, "instants")
    presses = result["presses"]
    assert len(presses) == result["episodes"] >= 3
    assert len(set(round(t) for t in presses)) == len(presses), "chaque appui garde son instant"
    assert presses[-1] < result["fbT"]
    assert result["fbT"] == result["now"], "l'agent date sur l'origine du parcours"


def test_explain_speaks_only_of_the_reviewed_exercise_and_never_in_numbers(tmp_path):
    result = run_qa(tmp_path, r"""
      const cal=calOf();cal.start();
      const S=agentOf(cal);
      const fb=S.recordFeedback({categories:['release_sticky'],text:'ça colle'},'voice');
      S.proposeHypothesis({cause:'release_threshold_too_far',confidence:.61,evidence:[],feedbackRefs:['fb-1']});
      const open={pinch:S.explain('pinch_primary'),hold:S.explain('hold_release'),aim:S.explain('aim')};
      clock+=1000;S.applyTrial({hypothesisRef:'hy-1',patch:{releaseRatio:.38}});
      const pending={pinch:S.explain('pinch_primary'),aim:S.explain('aim')};
      out({open,pending,table:A.CAUSE_EXERCISES.release_threshold_too_far});
    """, "explain")
    assert result["open"]["pinch"].startswith("Piste à tester")
    assert result["open"]["hold"].startswith("Piste à tester")
    assert result["open"]["aim"] is None, "une piste d'un autre exercice ne s'explique pas ici"
    assert result["pending"]["pinch"].startswith("Essai en cours")
    assert result["pending"]["aim"] is None
    assert not any(ch.isdigit() for ch in result["open"]["pinch"] + result["pending"]["pinch"])
    assert "hold_release" in result["table"]


def test_voice_next_is_refused_while_a_trial_waits_on_this_exercise(tmp_path):
    result = run_qa(tmp_path, r"""
      const cal=calOf();cal.start();
      const S=agentOf(cal);
      toStage(cal,'pinch_primary');readOn(cal);untilReview(cal,pinching('primaryRatio'));
      S.recordFeedback({categories:['release_sticky'],text:'ça colle'},'voice');
      S.proposeHypothesis({cause:'release_threshold_too_far',confidence:.5,evidence:[],feedbackRefs:['fb-1']});
      clock+=1000;S.applyTrial({hypothesisRef:'hy-1',patch:{releaseRatio:.38}});
      const refused=S.command('next',{});
      const stay=[cal.stepId(),cal.phase()];
      S.rollbackTrial();
      S.resolveTrial({trialRef:'tr-1',verdict:'inconclusive',comparisons:[],beforeRefs:[],afterRefs:[],feedbackRefs:[]});
      const after=S.command('next',{});
      out({refused:codeOf(refused),stay,after:after.ok&&after.result.decision,text:A.userText('barehands_calibration_trial_pending')});
    """, "pendingNext")
    assert result["refused"] == "barehands_calibration_trial_pending"
    assert result["stay"] == ["pinch_primary", "review"]
    assert result["after"] == "validated"
    assert "essai" in result["text"]


def test_the_engine_wakes_itself_while_calibrating_after_a_switch_off_and_on(tmp_path):
    result = run_lifecycle(tmp_path, WORLD + """
      const w=world({result:NO_HAND,options:{sleepTimeoutMs:30000}});
      w.deps.keepAwake=()=>true;
      const c=B.createController(w.deps);
      await c.enable();
      const first=c.state();
      w.steps(3,300);
      const woke=c.state();
      await c.disable();
      await c.enable();
      w.steps(3,300);
      out({first,woke,again:c.state()});
    """)
    assert result["first"] == "sleep"
    assert result["woke"] == "active" and result["again"] == "active"


def test_python_contracts_hold_the_review_reason_the_tool_argument_and_the_brief():
    from jarvis.domain import barehands_command as vocab
    from jarvis.domain.barehands_command import BarehandsCommandError
    from jarvis.runtime.control_center import BRIEF_CALIBRATION_MODE

    base = {"exercise": {"step": "aim", "phase": "review", "running": True, "finished": False},
            "values": {"effective": {}, "saved": {}, "trial": {}}, "measurements": [], "measurementCount": 0,
            "feedback": [], "evidence": [], "hypotheses": [], "trials": [],
            "reviews": [{"stage": "aim", "decision": "skipped", "status": "ok", "reason": "later",
                         "attempt": 1, "t": 10}],
            "truncated": {"measurements": 0, "feedback": 0, "evidence": 0, "trials": 0}}
    receipt = {"outcome": "applied", "lifecycle": "active", "code": None, "reason": None, "result": base}
    assert vocab.parse_command_receipt("calibration_status", receipt)["result"]["reviews"][0]["reason"] == "later"
    base["reviews"][0]["reason"] = "flemme"
    with pytest.raises(BarehandsCommandError):
        vocab.parse_command_receipt("calibration_status", receipt)
    bad_next = {"outcome": "applied", "lifecycle": "active", "code": None, "reason": None,
                "result": {"exercise": base["exercise"], "decision": "maybe"}}
    with pytest.raises(BarehandsCommandError):
        vocab.parse_command_receipt("calibration_next_exercise", bad_next)
    for needed in ("n'avance jamais seul", "decision", "validated", "skipped", "reason"):
        assert needed in BRIEF_CALIBRATION_MODE, needed
