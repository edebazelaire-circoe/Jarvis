"""Bare Hands — résidus de la QA de la Slice 07 adaptative, fermés à la Slice 10.

- les boutons « Valider l'étape » / « Passer » refusent comme la voix tant
  qu'un essai attend sa mesure sur l'exercice en cours — et seulement sur
  celui-là (portée de l'essai) ;
- un clic ignoré avant l'armement (fin d'un double-clic) pose le focus sur le
  titre du nouvel écran, pas sur le bouton ignoré ;
- le rapport : la liste des exercices est bornée, se nomme et se parcourt au
  clavier, pour que « Sera enregistré » reste visible ;
- et les survivants de la mutation de la QA : ligne de l'assistant effacée en
  quittant la revue, ressentis refermés au rapport, porte publique `save()`
  gardée hors rapport, latence de relâchement prise sur les tenues nettes
  seulement dans une série mêlée, exception du détour dans le refus d'un
  « Refaire » en avant, focus après « Retour ».

Harnais : celui de `test_barehands_calibration_review_qa_js.py` (vrai parcours,
vraie séance de l'agent, double de DOM).
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_barehands_calibration_review_qa_js import run_qa  # noqa: E402

#: Un essai sur le relâchement, appliqué depuis la revue du pincement primaire.
PENDING = r"""
const pendingTrial=(S)=>{
  S.recordFeedback({categories:['release_sticky'],text:'ça colle'},'voice');
  S.proposeHypothesis({cause:'release_threshold_too_far',confidence:.5,evidence:[],feedbackRefs:['fb-1']});
  clock+=1000;return S.applyTrial({hypothesisRef:'hy-1',patch:{releaseRatio:.38}});
};
"""


def test_the_buttons_refuse_like_the_voice_while_a_trial_waits_on_this_exercise(tmp_path):
    result = run_qa(tmp_path, PENDING + r"""
      let S=null;
      const cal=calOf({holdAfterResult:stage=>!!S&&S.holdAfterResult(stage)});
      cal.start();S=agentOf(cal);
      toStage(cal,'pinch_primary');readOn(cal);untilReview(cal,pinching('primaryRatio'));
      const applied=pendingTrial(S).ok;
      press(flowRoot(),'validate');
      const validate=[cal.stepId(),cal.phase(),noteText()];
      press(flowRoot(),'skip');
      const chooser=stepActions(flowRoot());
      const skip=cal.skip('later');
      const next=cal.next();
      const voice=codeOf(S.command('next',{}));
      S.rollbackTrial();
      S.resolveTrial({trialRef:'tr-1',verdict:'inconclusive',comparisons:[],beforeRefs:[],afterRefs:[],feedbackRefs:[]});
      press(flowRoot(),'validate');
      out({applied,validate,chooser,skip:[skip.ok,skip.code],next:[next.ok,next.code],voice,
        after:[cal.stepId(),cal.phase()]});
    """, "buttonsPending")
    assert result["applied"] is True
    assert result["validate"][:2] == ["pinch_primary", "review"]
    assert "essai" in result["validate"][2]
    assert "skip-later" not in result["chooser"], "le choix d'une raison ne s'ouvre pas"
    assert result["skip"] == [False, "barehands_calibration_trial_pending"]
    assert result["next"] == [False, "barehands_calibration_trial_pending"]
    assert result["voice"] == "barehands_calibration_trial_pending"
    assert result["after"] == ["hold_release", "intro"], "jugé, l'essai ne bloque plus"


def test_a_trial_waiting_on_another_exercise_does_not_block_this_one(tmp_path):
    result = run_qa(tmp_path, r"""
      let S=null;
      const cal=calOf({holdAfterResult:stage=>!!S&&S.holdAfterResult(stage)});
      cal.start();S=agentOf(cal);
      readOn(cal);untilReview(cal,{});
      S.recordFeedback({categories:['hard_to_aim'],text:'je vise mal'},'voice');
      S.proposeHypothesis({cause:'pointer_filter_too_smooth',confidence:.5,evidence:[],feedbackRefs:['fb-1']});
      clock+=1000;const trial=S.applyTrial({hypothesisRef:'hy-1',patch:{minCutoffHz:1.2}});
      const hold=[S.holdAfterResult('neutral'),S.holdAfterResult('aim')];
      press(flowRoot(),'validate');
      out({trial:trial.ok,hold,after:[cal.stepId(),cal.phase()]});
    """, "scopePending")
    assert result["trial"] is True
    assert result["hold"] == [False, True]
    assert result["after"] == ["c_pose", "intro"]


def test_an_ignored_click_puts_the_focus_on_the_new_screen_title(tmp_path):
    result = run_qa(tmp_path, r"""
      const cal=calOf();cal.start();readOn(cal);untilReview(cal,{});
      press(flowRoot(),'validate');
      const button=allButtons(flowRoot()).find(n=>n.getAttribute('data-flow-action')==='skip');
      button.focus();
      const before=document.activeElement&&document.activeElement.getAttribute('data-flow-action');
      pressNow(flowRoot(),'skip');
      out({before,after:document.activeElement&&document.activeElement.tagName,
        step:[cal.stepId(),cal.phase()],actions:stepActions(flowRoot())});
    """, "ignoredFocus")
    assert result["before"] == "skip"
    assert result["after"] == "H2", "le clic ignoré ne laisse pas le focus sur le bouton"
    assert result["step"] == ["c_pose", "intro"]
    assert "skip-later" not in result["actions"]


def test_the_report_list_is_bounded_named_and_reachable_by_keyboard(tmp_path):
    result = run_qa(tmp_path, r"""
      const cal=calOf();cal.start();
      toStage(cal,'pinch_primary');readOn(cal);untilReview(cal,pinching('primaryRatio'));cal.validate();
      while(cal.isRunning()&&stepActions(flowRoot()).includes('skip'))skipStep(cal);
      const list=find(flowRoot(),'jf-report')[0];
      out({label:list.getAttribute('aria-label'),tab:list.getAttribute('tabindex'),
        scrolls:list.getAttribute('data-scrolls'),
        bounded:/\[data-report="1"\] \.jf-report\{max-height:/.test(K.STYLE),
        affordance:K.STYLE.includes('.jf-report[data-scrolls="1"]'),
        summary:!!find(flowRoot(),'jf-review')[0]});
    """, "reportList")
    assert result["label"] == "Détail par exercice"
    assert result["tab"] == "0"
    assert result["scrolls"] in ("0", "1")
    assert result["bounded"] and result["affordance"] and result["summary"]


def test_the_assistant_line_is_cleared_when_the_review_is_left(tmp_path):
    result = run_qa(tmp_path, r"""
      const cal=calOf({explanation:stage=>stage==='neutral'?'Piste à tester : le jeton tremble.':null});
      cal.start();readOn(cal);untilReview(cal,{});
      const line=()=>deep(flowRoot()).filter(n=>n.getAttribute('data-review-agent')).length;
      const during=line();
      cal.validate();
      out({during,after:line()});
    """, "staleLine")
    assert result == {"during": 1, "after": 0}


def test_the_feelings_are_closed_at_the_report_and_save_is_guarded_before_it(tmp_path):
    result = run_qa(tmp_path, r"""
      const adjusted=[];
      const cal=calOf({adjust:stage=>{adjusted.push(stage);return true},canAdjust:()=>true});
      cal.start();
      toStage(cal,'pinch_primary');readOn(cal);untilReview(cal,pinching('primaryRatio'));
      press(flowRoot(),'adjust');
      /* La porte publique, hors rapport : rien n'est écrit. */
      const early=cal.save();
      const savedEarly=saved.length;
      cal.validate();
      while(cal.isRunning()&&stepActions(flowRoot()).includes('skip'))skipStep(cal);
      const atReport=adjusted.slice(-1)[0];
      out({early:!!early,savedEarly,atReport,adjusted,running:cal.isRunning()});
    """, "feelingsSave")
    assert result["early"] is False and result["savedEarly"] == 0
    assert result["atReport"] is None, "ressentis refermés au rapport"
    assert result["adjusted"][0] == "pinch_primary"


def test_focus_after_back_goes_to_a_control_that_commits_nothing(tmp_path):
    result = run_qa(tmp_path, r"""
      const cal=calOf();cal.start();readOn(cal);untilReview(cal,{});
      press(flowRoot(),'skip');
      const opened=document.activeElement&&document.activeElement.getAttribute('data-flow-action');
      press(flowRoot(),'back');
      const review=document.activeElement;
      cal.validate();
      press(flowRoot(),'skip');press(flowRoot(),'back');
      const play=document.activeElement&&document.activeElement.getAttribute('data-flow-action');
      out({opened,review:[review&&review.tagName,review&&review.getAttribute('data-flow-action')],play,
        step:cal.stepId()});
    """, "back")
    assert result["opened"] == "back"
    assert result["review"][1] is None, "revue : le focus va à la région de revue, pas à une commande"
    assert result["play"] == "skip"
    assert result["step"] == "c_pose"


def test_forward_rerun_is_refused_except_behind_the_detour(tmp_path):
    """Le comportement est tenu ; le mutant « exception du détour retirée »
    reste **équivalent** : tout exercice situé avant le point de retour d'un
    détour a forcément été traversé (joué, validé ou passé), donc déjà
    « joué » au sens de `canRerun`. L'exception est une ceinture documentée,
    pas un chemin atteignable (constat de la Slice 10)."""

    result = run_qa(tmp_path, r"""
      const cal=calOf();cal.start();
      readOn(cal);untilReview(cal,{});cal.validate();
      for(let i=0;i<4;i+=1)skipStep(cal);
      readOn(cal);clickOnce(cal);clickOnce(cal);clickOnce(cal);
      const back=cal.rerun('neutral');
      /* En détour, sur « neutral » : ce qui est avant le point de retour se
         refait ; ce qui est au-delà, jamais joué, reste refusé. */
      out({back,behind:cal.canRerun('aim'),beyond:cal.canRerun('natural_motion')});
    """, "detour")
    assert result["back"] == "neutral"
    assert result["behind"] == {"ok": True, "code": None}
    assert result["beyond"] == {"ok": False, "code": "barehands_calibration_exercise_not_played"}


def test_release_latency_is_taken_on_clean_holds_only_in_a_mixed_series(tmp_path):
    """Survivant « latence sur les nets seulement, série mêlée » : deux tenues
    lâchées doigts fermés (prématurées) et une nette. La latence rangée est
    celle de la nette ; une prématurée qui entrerait dans la statistique la
    déplacerait."""

    early = "(c,s,at)=>(c===2||c===3)&&at!==null&&s.now-at>=300&&s.ratio<.3?false:undefined"
    result = run_qa(tmp_path, f"out({{clean:holdRun(null),mixed:holdRun({early})}});", "holdMixed")
    clean, mixed = result["clean"], result["mixed"]
    assert mixed["status"] == "ok" and mixed["row"]["premature_drop_count"] == 2, mixed["row"]
    clean_latencies = [lat for premature, lat in mixed["eps"] if not premature and lat is not None]
    assert len(clean_latencies) == 1
    assert mixed["row"]["release_latency_ms"] == clean["row"]["release_latency_ms"] == clean_latencies[0]
    assert any(premature for premature, _lat in mixed["eps"])


def test_the_report_list_says_when_it_overflows(tmp_path):
    """Survivant R9 (QA Slice 10) : le liseré du rapport ne se pose que si la
    liste déborde vraiment (`scrollHeight > clientHeight`)."""

    result = run_qa(tmp_path, r"""
      const shell=K.createFlowOverlay({document,now,setInterval:()=>1,clearInterval:()=>{}});
      shell.open({title:'Calibration',exit:()=>{}});
      const list=find(flowRoot(),'jf-report')[0];
      const rows=[{label:'a',status:'ok',detail:'x'},{label:'b',status:'skipped',detail:'y'}];
      list.scrollHeight=500;list.clientHeight=300;
      shell.report(rows);
      const over=list.getAttribute('data-scrolls');
      list.scrollHeight=300;list.clientHeight=300;
      shell.report(rows);
      out({over,fits:list.getAttribute('data-scrolls')});
    """, "overflow")
    assert result == {"over": "1", "fits": "0"}
