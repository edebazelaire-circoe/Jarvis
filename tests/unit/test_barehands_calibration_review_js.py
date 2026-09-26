"""Bare Hands — la revue d'exercice de la calibration (tâche adaptative, Slice 07).

`docs/barehands-contracts.md` § 17, décisions 56 à 59. Ce que ces tests tiennent :

- après la mesure, **la revue n'avance jamais seule**, dans aucun exercice,
  qu'un essai soit en cours ou non ; seule une décision en sort (Refaire,
  Valider l'étape, Passer avec une raison, Quitter) — venue d'un bouton **ou**
  de la voix, par les mêmes portes ;
- Refaire efface ce qui se **dérive** de la tentative d'avant, pas l'historique ;
- Passer exige une raison de la liste fermée, rangée ;
- chaque nombre affiché vient du jeu de mesures de la séance (références) ;
- tenir puis relâcher, et déposer (6C), mesurent ce qu'ils disent ;
- une seule horloge de séance ; pas de veille pendant la calibration ;
- quitter ne touche pas au profil ; le rapport dit ce qui sera enregistré ;
- parité des étapes JS/Python et relecture d'un profil v3 d'avant.

Harnais : celui de `test_barehands_calibration_js.py` (double de DOM, horloge et
banc pilotés à la main), le vrai module d'agent et le vrai enregistreur.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_barehands_calibration_js import DOM, DRIVER, run_node, strip_js_comments  # noqa: E402
from test_barehands_lifecycle_js import WORLD, run_node as run_lifecycle  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
AGENT = RUNTIME / "control_center_barehands_calibration_agent.js"
RECORDER = RUNTIME / "control_center_barehands_recorder.js"
PAGE = RUNTIME / "control_center_barehands.js"
CALIBRATION = RUNTIME / "control_center_barehands_calibration.js"
DOC = ROOT / "docs" / "barehands-contracts.md"

#: Le vrai enregistreur (historique de séance) et le vrai module d'agent,
#: chargés après les contrats, comme dans la page.
MODULES = (
    f"global.JarvisBarehandsRecorder=require({json.dumps(str(RECORDER))});\n"
    f"const A=require({json.dumps(str(AGENT))});\n"
)

#: Pilotes propres à la revue.
REVIEW = r"""
/* Nourrir jusqu'à la revue **sans** la quitter (le `feedUntil` partagé, lui,
   décide ensuite). */
const untilReview=(cal,over,cap)=>{
  for(let n=0;n<(cap||1400)&&cal.phase()!=='review';n+=1){
    clock+=16;cal.feed({now:clock,hands:[hand(typeof over==='function'?over(n):over)]});
  }
  return cal.phase();
};
const noteText=()=>text(flowRoot(),C.DOM.flowNoteClass)[0];
const reviewLis=()=>deep(flowRoot()).filter(n=>n.tagName==='LI'&&n.getAttribute('data-metric'))
  .map(n=>({metric:n.getAttribute('data-metric'),aggregate:n.getAttribute('data-aggregate'),
    refs:n.getAttribute('data-refs').split(','),value:n.getAttribute('data-value'),
    label:n.children[0].textContent,text:n.children[1].textContent}));
/* Chaque ligne affichée, recalculée par le contrat sur le jeu de mesures de
   la séance : « aucun nombre inventé ». */
const traced=cal=>{const set=cal.session().measurements;
  return reviewLis().map(li=>{const again=C.aggregateMetric(li.metric,li.aggregate,li.refs,set);
    return {metric:li.metric,shown:li.value===''?null:Number(li.value),again,
      refsExist:li.refs.every(ref=>Object.prototype.hasOwnProperty.call(set,ref))}})};
/* Une main qui arme **chaque** étape : immobile, écart du C, canaux fermés. */
const ANY={stillness:.9,gapPalms:.65,primaryRatio:.15,secondaryRatio:.15};
const arm=cal=>{
  if(cal.practising()){bench.grab();cal.tick();return}
  if(/^(pinch_|hold_)/.test(cal.stepId())){
    feed(cal,1,Object.assign({},ANY,{primaryRatio:.6,secondaryRatio:.6}));feed(cal,2,ANY);return;
  }
  feed(cal,2,ANY);
};
const toStage=(cal,id)=>{for(let i=0;i<14&&cal.stepId()!==id;i+=1)skipStep(cal);return cal.stepId()};
const reviews=cal=>cal.session().reviews.map(r=>[r.stage,r.decision,r.status,r.reason,r.attempt]);
"""


def run(tmp_path: Path, source: str, name: str) -> dict:
    return run_node(tmp_path, MODULES + DOM + DRIVER + REVIEW + source, name=name)


def test_no_exercise_ever_leaves_its_review_by_itself(tmp_path):
    """**Aucun exercice, jamais** (décision 56) : une fois soldé, deux minutes
    d'horloge, vingt battements du chien de garde et trente images ne le font
    pas avancer. Chaque étape mesurée des neuf écrans y passe, 6C comprise."""

    result = run(tmp_path, r"""
      benchRect=true;
      const cal=calOf();
      cal.start();
      const seen=[];
      for(let i=0;i<11;i+=1){
        const stage=cal.stepId();
        readOn(cal);arm(cal);
        clock+=6000;beat();
        const at={stage,phase:cal.phase(),review:cal.review()&&cal.review().status};
        clock+=120000;beat(20);feed(cal,30,{stillness:.1,primaryRatio:.9,secondaryRatio:.9});
        at.after={step:cal.stepId(),phase:cal.phase()};
        at.actions=stepActions(flowRoot());
        seen.push(at);
        cal.skip('later');
      }
      const reportReached=cal.stepId()===null&&cal.concluded();
      cal.exit('test');
      /* Et une réussite pas davantage : le repos mesuré, puis rien. */
      const ok=calOf();ok.start();readOn(ok);
      untilReview(ok,{});
      clock+=120000;beat(20);feed(ok,30,{});
      out({seen,report:reportReached,
        ok:{step:ok.stepId(),phase:ok.phase(),status:ok.review().status,actions:stepActions(flowRoot())}});
    """, "noAdvance")
    stages = [row["stage"] for row in result["seen"]]
    assert stages == ["neutral", "c_pose", "pinch_primary", "hold_release", "pinch_secondary", "aim",
                      "drag", "resize", "drop", "natural_motion", "aim_no_click"]
    for row in result["seen"]:
        assert row["phase"] == "review", row
        assert row["after"] == {"step": row["stage"], "phase": "review"}, row
        # Une étape ratée ne se valide pas : Refaire, Ajuster (sans agent : absent), Passer, Quitter.
        assert row["review"] == "failed" and row["actions"] == ["rerun", "skip", "exit"], row
    assert result["report"] is True
    assert result["ok"]["step"] == "neutral" and result["ok"]["phase"] == "review"
    assert result["ok"]["status"] == "ok"
    assert result["ok"]["actions"] == ["rerun", "validate", "skip", "exit"]


def test_validate_advances_only_from_a_successful_review(tmp_path):
    result = run(tmp_path, r"""
      const cal=calOf();
      cal.start();
      const beforeReview=cal.validate();
      readOn(cal);
      untilReview(cal,{});
      const lines=reviewLis();
      const focused=document.activeElement&&document.activeElement.getAttribute('data-review');
      press(flowRoot(),'validate');
      const after={step:cal.stepId(),phase:cal.phase(),
        heading:document.activeElement&&document.activeElement.tagName};
      /* Le C raté (majeur collé) : la revue refuse de valider. */
      readOn(cal);
      untilReview(cal,{cPose:0,gapPalms:.65,indexReachPalms:1.8,secondaryRatio:.2,wakePose:0});
      const failed={status:cal.review().status,validate:cal.validate(),step:cal.stepId(),
        actions:stepActions(flowRoot()),
        focused:document.activeElement&&document.activeElement.getAttribute('data-review')};
      out({beforeReview,lines,focused,after,failed,decisions:reviews(cal)});
    """, "validate")
    assert result["beforeReview"] is None, "hors revue, rien à valider"
    assert [line["metric"] for line in result["lines"]] == ["pointer_jitter_px"]
    # Le focus va à la **revue** (une région qui se lit), jamais à une commande
    # qui valide ou passe (reprise QA : Entrée tenue).
    assert result["focused"] == "neutral"
    assert result["after"] == {"step": "c_pose", "phase": "intro", "heading": "H2"}
    assert result["failed"]["status"] == "failed" and result["failed"]["validate"] is None
    assert result["failed"]["step"] == "c_pose"
    assert "validate" not in result["failed"]["actions"]
    assert result["failed"]["focused"] == "c_pose"
    assert result["decisions"] == [["neutral", "validated", "ok", None, 1]]


def test_skipping_requires_a_reason_from_the_closed_list_and_records_it(tmp_path):
    result = run(tmp_path, r"""
      const cal=calOf();
      cal.start();
      const none=cal.skip();
      const bogus=cal.skip('parce que');
      const still=cal.stepId();
      press(flowRoot(),'skip');
      const chooser=stepActions(flowRoot());
      const focused=document.activeElement&&document.activeElement.getAttribute('data-flow-action');
      const prompt=noteText();
      press(flowRoot(),'back');
      const back=stepActions(flowRoot());
      press(flowRoot(),'skip');press(flowRoot(),'skip-tracking');
      const after=cal.stepId();
      /* Passer une revue **réussie** : la mesure n'est pas gardée. */
      readOn(cal);
      untilReview(cal,{cPose:.9,gapPalms:.65,indexReachPalms:1.8,secondaryRatio:.9});
      const okStatus=cal.review().status;
      press(flowRoot(),'skip');press(flowRoot(),'skip-not_relevant');
      while(cal.isRunning()&&stepActions(flowRoot()).includes('skip'))skipStep(cal);
      const rows=reportRows();
      const payload=cal.result().payload;
      out({none,bogus,still,chooser,focused,prompt,back,after,okStatus,rows,
        stages:{neutral:payload.stages.neutral,c:payload.stages.c_pose},decisions:reviews(cal).slice(0,2),
        texts:K.SKIP_TEXT,reasons:C.SKIP_REASONS});
    """, "skipReason")
    code = "barehands_calibration_skip_reason_required"
    assert result["none"] == {"ok": False, "step": "neutral", "code": code}
    assert result["bogus"]["code"] == code and result["still"] == "neutral"
    assert result["chooser"] == ["skip-not_relevant", "skip-cannot_perform", "skip-tracking", "skip-later", "back"]
    assert result["focused"] == "back", "le focus ne tombe jamais sur une raison (Entrée tenue passait l'étape)"
    assert "Pourquoi passer" in result["prompt"]
    assert result["back"] == ["skip", "exit"], "« Retour » rend les commandes de l'exercice"
    assert result["after"] == "c_pose"
    assert result["stages"]["neutral"] == {"status": "skipped", "reason": "barehands_stage_skip_tracking",
                                           "samples": 0}
    assert result["okStatus"] == "ok"
    assert result["stages"]["c"]["status"] == "skipped", "passer une réussite ne la garde pas"
    assert result["stages"]["c"]["reason"] == "barehands_stage_skip_not_relevant"
    assert result["decisions"] == [["neutral", "skipped", "skipped", "tracking", 1],
                                   ["c_pose", "skipped", "skipped", "not_relevant", 1]]
    labels = {row[0]: row for row in result["rows"]}
    assert "la caméra me voit mal" in labels["Main au repos"][2]
    assert result["reasons"] == list(result["texts"])


def test_rerun_resets_only_that_exercise_keeps_the_history_and_detours_back(tmp_path):
    """Refaire le pincement depuis la tenue : les épisodes d'avant restent
    dans la séance, les seuils dérivés de la tentative réussie partent (la
    nouvelle tentative échoue : aucune valeur devinée), le repos garde sa
    mesure, et le parcours revient à la tenue au lieu de tout rejouer."""

    result = run(tmp_path, r"""
      const cal=calOf();
      cal.start();
      readOn(cal);untilReview(cal,{});cal.validate();
      skipStep(cal);
      readOn(cal);untilReview(cal,pinching('primaryRatio'));
      const first={attempt:cal.review().attempt,lines:reviewLis().map(l=>l.metric),traced:traced(cal)};
      const epsBefore=Object.keys(cal.session().measurements).filter(r=>r.startsWith('ep-'));
      cal.validate();
      const at=cal.stepId();
      const rerun=cal.rerun('pinch_primary');
      const reset={step:cal.stepId(),phase:cal.phase(),
        kept:epsBefore.every(r=>Object.prototype.hasOwnProperty.call(cal.session().measurements,r))};
      /* Seconde tentative : armée, puis la main disparaît. */
      readOn(cal);arm(cal);clock+=6000;beat();
      const second={status:cal.review().status,attempt:cal.review().attempt,lines:reviewLis().length,
        title:deep(flowRoot()).filter(n=>n.tagName==='H3').map(n=>n.textContent)[0]};
      cal.skip('cannot_perform');
      const back=cal.stepId();
      while(cal.isRunning()&&stepActions(flowRoot()).includes('skip'))skipStep(cal);
      const rows=reportRows();
      const payload=cal.result().payload;
      out({first,epsBefore:epsBefore.length,at,rerun,reset,second,back,rows,
        left:payload.hands.left,stages:{neutral:payload.stages.neutral.status,pinch:payload.stages.pinch_primary},
        decisions:reviews(cal).filter(r=>r[0]==='pinch_primary')});
    """, "rerun")
    assert result["first"]["attempt"] == 1
    assert result["first"]["lines"] == ["episode_duration_ms", "press_latency_ms", "release_latency_ms",
                                        "missed_press_rate", "missed_release_rate"]
    assert all(row["refsExist"] and row["shown"] == row["again"] for row in result["first"]["traced"])
    assert result["epsBefore"] >= 3
    assert result["at"] == "hold_release" and result["rerun"] == "pinch_primary"
    assert result["reset"] == {"step": "pinch_primary", "phase": "intro", "kept": True}
    assert result["second"]["status"] == "failed" and result["second"]["attempt"] == 2
    assert result["second"]["lines"] == 0, "la revue ne montre que la tentative en cours"
    assert "essai n° 2" in result["second"]["title"]
    assert result["back"] == "hold_release", "le détour revient là où on en était"
    # Aucune valeur devinée : la tentative réussie d'avant ne survit pas.
    assert result["left"]["pressRatio"] is None and result["left"]["releaseRatio"] is None
    assert result["left"]["jitterPx"] is not None, "le repos, lui, n'a pas été refait"
    assert result["stages"]["neutral"] == "ok"
    assert result["stages"]["pinch"]["status"] == "failed"
    labels = {row[0]: row for row in result["rows"]}
    assert "2 essais" in labels["Pincement pouce-index"][2]
    assert "je n’arrive pas" in labels["Pincement pouce-index"][2]
    assert result["decisions"] == [["pinch_primary", "validated", "ok", None, 1],
                                   ["pinch_primary", "rerun", "ok", None, 1],
                                   ["pinch_primary", "skipped", "failed", "cannot_perform", 2]]


def test_voice_next_and_rerun_drive_the_same_transitions_as_the_buttons(tmp_path):
    """`calibration_next_exercise` = Valider (revue réussie) ou Passer (avec la
    raison) ; `calibration_rerun_exercise` = Refaire. Une seule machine : la
    séance de l'agent appelle les portes du parcours."""

    result = run(tmp_path, r"""
      const cal=calOf();
      cal.start();
      const S=A.createCalibrationAgentSession({contracts:C,flow:()=>cal,
        trials:()=>({status:()=>({active:false})}),values:()=>({effective:{},saved:{},trial:{}}),
        now,held:()=>true,origin:cal.session().clockOrigin});
      const code=r=>r.ok?null:r.errors[0].code;
      const bare=S.command('next',{});
      const bogus=S.command('next',{reason:'flemme'});
      const skipped=S.command('next',{reason:'later'});
      readOn(cal);
      untilReview(cal,{cPose:.9,gapPalms:.65,indexReachPalms:1.8,secondaryRatio:.9});
      const validated=S.command('next',{});
      const rerun=S.command('rerun',{exercise:'c_pose'});
      const afterRerun=[cal.stepId(),cal.phase()];
      readOn(cal);
      untilReview(cal,{cPose:.9,gapPalms:.65,indexReachPalms:1.8,secondaryRatio:.9});
      press(flowRoot(),'validate');
      const status=S.status();
      out({codes:[code(bare),code(bogus)],skipped:skipped.ok&&skipped.result.exercise.step,
        validated:validated.ok&&validated.result.exercise.step,rerun:rerun.ok&&rerun.result.exercise.step,
        afterRerun,decisions:reviews(cal),statusReviews:status.result.reviews.map(r=>[r.stage,r.decision,r.reason]),
        receiptOk:status.ok});
    """, "voice")
    assert result["codes"] == ["barehands_calibration_skip_reason_required",
                               "barehands_calibration_skip_reason_unknown"]
    assert result["skipped"] == "c_pose"
    assert result["validated"] == "pinch_primary"
    assert result["rerun"] == "c_pose" and result["afterRerun"] == ["c_pose", "intro"]
    # Voix et bouton rangent **les mêmes** décisions dans la même séance.
    assert result["decisions"] == [["neutral", "skipped", "skipped", "later", 1],
                                   ["c_pose", "validated", "ok", None, 1],
                                   ["c_pose", "rerun", "ok", None, 1],
                                   ["c_pose", "validated", "ok", None, 2]]
    assert result["statusReviews"] == [["neutral", "skipped", "later"], ["c_pose", "validated", None],
                                       ["c_pose", "rerun", None], ["c_pose", "validated", None]]


def test_the_status_receipt_with_reviews_and_row_times_passes_the_server_schema(tmp_path):
    from jarvis.domain import barehands_command as vocab

    result = run(tmp_path, r"""
      const cal=calOf();
      cal.start();
      const S=A.createCalibrationAgentSession({contracts:C,flow:()=>cal,
        trials:()=>({status:()=>({active:false})}),values:()=>({effective:{},saved:{},trial:{}}),
        now,held:()=>true,origin:cal.session().clockOrigin});
      readOn(cal);untilReview(cal,{});cal.validate();
      skipStep(cal);
      readOn(cal);untilReview(cal,pinching('primaryRatio'));
      out({status:S.status().result});
    """, "statusSchema")
    receipt = {"outcome": "applied", "lifecycle": "active", "code": None, "reason": None, "result": result["status"]}
    parsed = vocab.parse_command_receipt("calibration_status", receipt)["result"]
    assert [r["decision"] for r in parsed["reviews"]] == ["validated", "skipped"]
    assert all(isinstance(row["t"], (int, float)) for row in parsed["measurements"])


def test_one_session_clock_orders_frames_feedback_and_reviews(tmp_path):
    """**Report des Slices 03 et 06.** Les images arrivent datées par
    l'horloge du moteur (ici décalée d'un million de ms), les retours et les
    revues par celle de la page : tout se range en ms de séance, dans l'ordre
    où c'est arrivé, et la séance de l'agent lit la même origine."""

    result = run(tmp_path, r"""
      const cal=calOf();
      cal.start();
      const S=A.createCalibrationAgentSession({contracts:C,flow:()=>cal,
        trials:()=>({status:()=>({active:false})}),values:()=>({effective:{},saved:{},trial:{}}),
        now,held:()=>true,origin:cal.session().clockOrigin});
      const SKEW=1e6;
      const feedSkew=(n,over)=>{for(let i=0;i<n;i+=1){clock+=16;
        cal.feed({now:clock+SKEW,hands:[hand(typeof over==='function'?over(i):over)]})}};
      readOn(cal);
      for(let i=0;i<1400&&cal.phase()!=='review';i+=1)feedSkew(1,{});
      cal.validate();skipStep(cal);
      readOn(cal);
      /* Des pincements de 240 ms : assez pour que le vrai détecteur tranche
         appui et relâchement. */
      for(let i=0;i<1400&&cal.phase()!=='review';i+=1)feedSkew(1,{stillness:.5,primaryRatio:i%30<15?.15:.6,primaryConfidence:1});
      clock+=500;
      const fb=S.recordFeedback({categories:['release_sticky'],text:'le relâchement colle'},'voice');
      const samples=cal.session().samples.map(s=>[s.event.kind,s.t]);
      out({samples,fbT:fb.result.feedback.t,now:cal.sessionTime()});
    """, "clock")
    samples = result["samples"]
    kinds = [kind for kind, _ in samples]
    times = [t for _, t in samples]
    assert times == sorted(times), samples
    assert kinds[-1] == "feedback" and "stage_review" in kinds and "pinch_press" in kinds
    assert all(0 <= t <= result["now"] for t in times), "aucun instant d'image hors de la séance"
    assert result["fbT"] == samples[-1][1], "l'agent et le parcours partagent l'origine"
    last_release = max(t for kind, t in samples if kind == "pinch_release")
    review_t = max(t for kind, t in samples if kind == "stage_review")
    assert last_release <= review_t <= result["fbT"]


def test_hold_release_counts_premature_and_sticky_releases_on_the_replayed_detector(tmp_path):
    """Un détecteur scripté (double du canal de pincement, même interface que
    `createPinchChannel`) lâche le contact au milieu du deuxième pincement
    tenu : un relâchement **prématuré** ; dans une autre séance il garde le
    contact du deuxième au-delà de sa réouverture : un relâchement **collé**."""

    result = run(tmp_path, r"""
      const scripted=mode=>()=>{let down=false,closeAt=null,closures=0;
        return {state:()=>down?'pressed':'open',update(s){
          const ev=[];const closed=s.ratio<.3;
          if(closed&&closeAt===null){closeAt=s.now;closures+=1;
            if(mode==='sticky'&&down){ev.push({phase:'up',t:s.now});down=false}}
          if(!closed)closeAt=null;
          let want=closed;
          if(mode==='premature'&&closures===2&&closeAt!==null&&s.now-closeAt>=300&&s.now-closeAt<400)want=false;
          if(mode==='sticky'&&closures===2&&down)want=true;
          if(want&&!down){down=true;ev.push({phase:'down',t:s.now})}
          else if(!want&&down){down=false;ev.push({phase:'up',t:s.now})}
          return ev}}};
      const play=mode=>{
        const cal=calOf({pinchChannel:scripted(mode)});
        cal.start();toStage(cal,'hold_release');readOn(cal);
        const phase=untilReview(cal,holdPattern);
        const review=cal.review();
        const lines=reviewLis();
        const trace=traced(cal);
        const note=noteText();
        const row=cal.session().measurements[review.lines[1].refs[0]];
        cal.exit('test');
        return {phase,status:review.status,lines:lines.map(l=>[l.metric,l.text]),trace,note,row};
      };
      /* Trop court : relâcher avant la seconde, l'écran le dit. */
      const shortCal=calOf();shortCal.start();toStage(shortCal,'hold_release');readOn(shortCal);
      feed(shortCal,60,i=>({stillness:.5,primaryRatio:i%30<12?.15:.6}));
      const short=noteText();shortCal.exit('test');
      out({premature:play('premature'),sticky:play('sticky'),short});
    """, "holdRelease")
    premature, sticky = result["premature"], result["sticky"]
    for run_ in (premature, sticky):
        assert run_["phase"] == "review" and run_["status"] == "ok"
        assert all(t["refsExist"] and t["shown"] == t["again"] for t in run_["trace"]), run_["trace"]
    assert premature["row"]["premature_drop_count"] == 1
    assert premature["row"]["missed_release_rate"] == 0
    assert ["premature_drop_count", "1"] in premature["lines"]
    assert "relâchement(s) trop tôt" in premature["note"]
    assert sticky["row"]["premature_drop_count"] == 0
    assert 0 < sticky["row"]["missed_release_rate"] < 1
    assert "qui collent" in sticky["note"]
    assert "Tenez plus longtemps" in result["short"]


def test_drop_measures_premature_drops_and_placement_into_the_destination(tmp_path):
    result = run(tmp_path, r"""
      benchRect=true;
      const cal=calOf();
      cal.start();toStage(cal,'drop');readOn(cal);
      const dest=deep(flowRoot()).find(n=>n.getAttribute('data-drop')==='1');
      const placed={left:dest.style.left,width:dest.style.width,hidden:dest.getAttribute('aria-hidden')};
      dropInto(cal,200);
      const miss={phase:cal.phase(),note:noteText()};
      dropInto(cal,-180);
      dropInto(cal,0);
      const review=cal.review();
      const row=cal.session().measurements[review.lines[0].refs[0]];
      const trace=traced(cal);
      const lines=reviewLis().map(l=>[l.metric,l.text]);
      /* Trois lâchers hors destination : l'étape échoue, sa ligne reste. */
      cal.exit('test');
      const bad=calOf();bad.start();toStage(bad,'drop');readOn(bad);
      dropInto(bad,300);dropInto(bad,300);dropInto(bad,300);
      const failed={status:bad.review().status,note:noteText(),
        row:bad.session().measurements[bad.review().lines[0].refs[0]]};
      out({placed,miss,status:review.status,row,trace,lines,failed});
    """, "drop")
    assert result["placed"]["hidden"] == "true"
    assert result["miss"]["phase"] == "running" and "px du centre" in result["miss"]["note"]
    assert result["status"] == "ok"
    assert result["row"]["drag_success_rate"] == 1 / 3 and result["row"]["premature_drop_count"] == 2
    # La destination est posée au pixel entier : l'écart résiduel est l'arrondi.
    assert result["row"]["placement_error_px"] < 1
    assert all(t["refsExist"] and t["shown"] == t["again"] for t in result["trace"])
    assert result["lines"][0] == ["drag_success_rate", "33 %"]
    assert result["lines"][1][0] == "placement_error_px" and result["lines"][1][1].endswith(" px")
    assert result["lines"][2] == ["premature_drop_count", "2"]
    assert result["failed"]["status"] == "failed"
    assert result["failed"]["row"]["drag_success_rate"] == 0 and result["failed"]["row"]["premature_drop_count"] == 3
    assert "destination" in result["failed"]["note"]


def test_the_review_shows_the_assistant_line_and_adjust_opens_its_feelings(tmp_path):
    result = run(tmp_path, r"""
      const adjusted=[];
      /* Sans assistant à l'écoute, pas d'« Ajuster » : un bouton qui
         n'ouvrirait rien. */
      const lone=calOf({adjust:()=>true,canAdjust:()=>false});
      lone.start();readOn(lone);untilReview(lone,{});
      const without=stepActions(flowRoot());
      lone.exit('test');
      const cal=calOf({explanation:stage=>stage==='neutral'?'Piste à tester : le jeton tremble.':null,
        adjust:stage=>{adjusted.push(stage);return true},canAdjust:()=>true,
        holdAfterResult:stage=>stage==='neutral'});
      cal.start();readOn(cal);untilReview(cal,{});
      const agentLine=deep(flowRoot()).filter(n=>n.getAttribute('data-review-agent')).map(n=>
        n.children.map(c=>c.textContent).join(''));
      const hold=text(flowRoot(),'jf-review-hold');
      const actions=stepActions(flowRoot());
      const primary=allButtons(flowRoot()).filter(b=>b.className==='primary').map(b=>b.getAttribute('data-flow-action'));
      press(flowRoot(),'adjust');
      const said=noteText();
      const still=[cal.stepId(),cal.phase()];
      cal.validate();
      out({without,agentLine,hold,actions,primary,said,still,adjusted,holding:cal.holding()});
    """, "adjust")
    assert result["without"] == ["rerun", "validate", "skip", "exit"]
    assert result["agentLine"] == ["Assistant : Piste à tester : le jeton tremble."]
    assert result["hold"] and "essai" in result["hold"][0]
    assert result["actions"] == ["rerun", "adjust", "validate", "skip", "exit"]
    assert result["primary"] == ["rerun"], "un essai à juger fait de « Refaire » l'action principale"
    assert "ressenti" in result["said"]
    assert result["still"] == ["neutral", "review"], "Ajuster ne quitte pas la revue"
    assert result["adjusted"] == ["neutral", None], "les ressentis se referment en quittant la revue"
    assert result["holding"] is False


def test_quitting_never_touches_the_accepted_profile_and_the_report_says_what_will_be_saved(tmp_path):
    result = run(tmp_path, r"""
      const cancelled=[];
      /* 1. Quitter depuis une revue réussie. */
      const a=calOf({onCancelled:why=>cancelled.push(why)});
      a.start();toStage(a,'pinch_primary');readOn(a);untilReview(a,pinching('primaryRatio'));
      press(flowRoot(),'exit');
      const fromReview={saved:saved.length,running:a.isRunning()};
      /* 2. Jusqu'au rapport, avec une mesure et un essai gardé ; puis
         « Quitter sans enregistrer ». */
      const b=calOf({onCancelled:why=>cancelled.push(why),
        acceptedTrials:()=>['Correction gardée : le relâchement tarde à être reconnu.']});
      b.start();toStage(b,'pinch_primary');readOn(b);untilReview(b,pinching('primaryRatio'));b.validate();
      while(b.isRunning()&&stepActions(flowRoot()).includes('skip'))skipStep(b);
      const report={actions:stepActions(flowRoot()),
        labels:allButtons(flowRoot()).filter(n=>n.getAttribute('data-flow-action')).map(n=>n.textContent),
        willSave:deep(find(flowRoot(),'jf-review')[0]).map(n=>n.textContent).join(' | '),
        focused:document.activeElement&&(document.activeElement.getAttribute('data-flow-action')
          ||document.activeElement.tagName),
        note:noteText()};
      press(flowRoot(),'discard');
      out({fromReview,report,after:saved.length,cancelled});
    """, "cancel")
    assert result["fromReview"] == {"saved": 0, "running": False}
    assert result["report"]["actions"] == ["apply", "discard"]
    assert result["report"]["labels"] == ["Enregistrer", "Quitter sans enregistrer"]
    assert result["report"]["focused"] == "H2", "le rapport se lit avant qu'on décide"
    assert "Sera enregistré" in result["report"]["willSave"]
    assert "seuil d’appui du pincement pouce-index (main gauche)" in result["report"]["willSave"]
    assert "Correction gardée" in result["report"]["willSave"]
    assert "quitter sans enregistrer n’y touche pas" in result["report"]["note"]
    assert result["after"] == 0, "« Quitter sans enregistrer » n'écrit rien"
    assert result["cancelled"] == ["bouton", "résultat refusé"]


def test_calibration_keeps_bare_hands_awake_and_the_countdown_restarts_after(tmp_path):
    """**Report de la Slice 03** : trente secondes sans main pendant les
    écrans de lecture et de revue renvoyaient en veille. `keepAwake` (posé par
    la page pendant la calibration) réarme le minuteur ; retiré, la veille
    ordinaire repart de zéro."""

    result = run_lifecycle(tmp_path, WORLD + """
      const w=world({result:NO_HAND,options:{sleepTimeoutMs:30000}});
      let calibrating=true;
      w.deps.keepAwake=()=>calibrating;
      const c=B.createController(w.deps);
      await c.enable();await c.activate();
      w.steps(90,1000);
      const during=c.state();
      calibrating=false;
      w.steps(29,1000);
      const justAfter=c.state();
      w.steps(2,1000);
      const later=c.state();
      /* Une lecture qui lève vaut « non » : la veille ordinaire reprend. */
      const x=world({result:NO_HAND,options:{sleepTimeoutMs:30000}});
      x.deps.keepAwake=()=>{throw new Error('lecture impossible')};
      const cx=B.createController(x.deps);
      await cx.enable();await cx.activate();
      x.steps(31,1000);
      out({during,justAfter,later,broken:cx.state(),idle:w.log.includes('status:sleep:idle_sleep')});
    """)
    assert result["during"] == "active", "quatre-vingt-dix secondes sans main, toujours éveillé"
    assert result["justAfter"] == "active", "le minuteur repart de zéro à la fin"
    assert result["later"] == "sleep" and result["idle"] is True
    assert result["broken"] == "sleep"


def test_the_page_keeps_awake_only_while_calibrating_and_wires_the_review(tmp_path):
    source = strip_js_comments(PAGE.read_text(encoding="utf-8"))
    start = source[source.index("function startMeasuring(){"):source.index("function stopMeasuring(){")]
    stop = source[source.index("function stopMeasuring(){"):source.index("function stopMeasuring(){") + 300]
    assert "controllerDeps.keepAwake=()=>!!(calibration&&calibration.isRunning())" in start
    assert "delete controllerDeps.keepAwake" in stop
    begin = source.index("calibration=CALIB.createCalibration({")
    flow = source[begin:source.index("log:(level,message,detail)=>{", begin)]
    for name in ("explanation:", "adjust:", "canAdjust:", "acceptedTrials:", "holdAfterResult:", "stateRef:"):
        assert name in flow, name
    assert "next:payload=>agentCall('next',payload)" in source
    assert "origin:flowSession?flowSession.clockOrigin:undefined" in source
    # La porte `rect()` du banc : la même conversion que le dessin.
    bench = source[source.index("function practiceBench(){"):source.index("function selectionBench(){")]
    assert "rect(){" in bench and "L.toScreen(vp,frame.box())" in bench


def test_stage_lists_agree_across_js_python_and_the_flow(tmp_path):
    from jarvis.domain import barehands_calibration as domain
    from jarvis.runtime import barehands_profile as profile

    result = run(tmp_path, r"""
      out({flow:K.STEPS.reduce((l,s)=>l.concat(s.subs?s.subs.map(x=>x.id):[s.id]),[]),stages:C.STAGES,
        reasons:C.STAGE_REASONS,skip:C.SKIP_REASONS,skipCodes:C.SKIP_REASONS.map(r=>C.SKIP_REASON[r]),
        screens:K.SCREENS,steps:K.STEPS.length,phases:K.PHASE_ORDER,
        causes:Object.values(A.CAUSE_EXERCISES).flat(),words:Object.keys(A.CAUSE_WORDS),
        causeList:C.HYPOTHESIS_CAUSES,review:Object.keys(K.REVIEW_LINES),
        reviewMetrics:Object.values(K.REVIEW_LINES).flat().map(l=>l.metric),metrics:C.CALIBRATION_METRICS});
    """, "parity")
    assert result["flow"] == result["stages"] == list(profile.STAGES) == list(domain.STAGES)
    assert result["stages"] == ["neutral", "c_pose", "pinch_primary", "hold_release", "pinch_secondary", "aim",
                                "drag", "resize", "drop", "natural_motion", "aim_no_click"]
    assert result["reasons"] == list(profile.STAGE_REASONS)
    assert result["skip"] == list(domain.SKIP_REASONS)
    assert all(code in result["reasons"] for code in result["skipCodes"])
    assert result["screens"] == 9 and result["steps"] == 8
    assert result["phases"] == ["intro", "armed", "running", "review"]
    assert set(result["causes"]) <= set(result["stages"])
    assert sorted(result["words"]) == sorted(result["causeList"])
    assert set(result["review"]) <= set(result["stages"])
    assert set(result["reviewMetrics"]) <= set(result["metrics"])


def test_an_old_v3_profile_without_the_new_stages_still_loads(tmp_path):
    from jarvis.runtime import barehands_profile as profile

    result = run(tmp_path, r"""
      const old=Object.fromEntries(['neutral','c_pose','pinch_primary','pinch_secondary','aim','drag','resize',
        'natural_motion','aim_no_click'].map(s=>[s,{status:'ok',reason:null,samples:3}]));
      const p=C.normalizeProfile({schemaVersion:3,updatedAt:1,hands:{},stages:old});
      out({hold:p.stages.hold_release,drop:p.stages.drop,kept:p.stages.aim_no_click.status});
    """, "oldV3")
    assert result["hold"] == {"status": "skipped", "reason": None, "samples": 0}
    assert result["drop"] == {"status": "skipped", "reason": None, "samples": 0}
    assert result["kept"] == "ok"
    stored = {"schema_version": 3, "updated_at": 1, "hands": {},
              "stages": {"neutral": {"status": "ok", "reason": None, "samples": 3}}}
    loaded = profile.load({profile.SETTING_KEY: stored})
    assert loaded["stages"]["hold_release"]["status"] == "skipped"
    assert loaded["stages"]["drop"]["status"] == "skipped"
    assert loaded["stages"]["neutral"]["status"] == "ok"


def test_the_voice_next_payload_takes_only_a_closed_reason():
    import pytest

    from jarvis.domain import barehands_calibration as domain
    from jarvis.domain.barehands_command import BarehandsCommandError

    assert domain.parse_calibration_payload("calibration_next_exercise", None) == {}
    assert domain.parse_calibration_payload("calibration_next_exercise", {"reason": "later"}) == {"reason": "later"}
    for bad in ({"reason": "flemme"}, {"reason": "later", "extra": 1}):
        with pytest.raises(BarehandsCommandError):
            domain.parse_calibration_payload("calibration_next_exercise", bad)


def test_the_review_shell_stays_calm_accessible_and_motionless_when_asked():
    """Critique « impeccable » tenue par la feuille : la revue et la
    destination n'animent rien (rien à couper sous « mouvement réduit »), les
    valeurs sont en chiffres tabulaires, et le texte de la revue passe par les
    jetons de contraste de la coque, jamais une couleur de succès."""

    source = CALIBRATION.read_text(encoding="utf-8")
    sheet = source[source.index("la revue (S07 adapt.)"):source.index("@media (max-width:720px){${R} .jf-review ul")]
    assert "animation" not in sheet and "transition" not in sheet
    assert "font-variant-numeric:tabular-nums" in sheet
    assert "--jf-ok" not in sheet, "le vert reste réservé à « reconnu, à l'instant »"
    assert re.search(r"\.jf-review li span\{color:var\(--jf-soft\)\}", sheet)
    code = strip_js_comments(source)
    assert "button.setAttribute('type','button')" in code
    assert "actions.setAttribute('role','group')" in code


def test_the_contract_documents_decisions_56_to_59():
    doc = DOC.read_text(encoding="utf-8")
    section = doc[doc.index("## 17. Calibration adaptative"):]
    for number in (56, 57, 58, 59):
        assert f"### Décision {number}" in section, number
    for name in ("REVIEW", "hold_release", "drop", "SKIP_REASONS", "keepAwake", "clockOrigin",
                 "calibration_next_exercise", "premature_drop_count"):
        assert name in section, name
