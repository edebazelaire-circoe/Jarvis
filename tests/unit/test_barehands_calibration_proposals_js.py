"""Bare Hands — le runtime constate, le cerveau propose, l'utilisateur décide (retour du 28/09).

Exécuté par node sur les **vrais** modules : parcours de calibration, séance
de l'agent et panneau de calibration, sur le double de DOM des autres tests.

Ce que ce fichier épingle :

- **l'interprétation d'un résultat est calculée par le runtime** (`good`,
  `warning`, `bad`, `neutral`) et la revue centrale la montre (marque et mot) ;
  l'étape du C dit sa cause critère par critère (repli des doigts mesuré) ;
- **les événements** : vocabulaire fermé, dans l'ordre des faits (la décision
  avant l'étape qu'elle ouvre), avec leur source (bouton, voix, panneau) ;
- **une proposition n'est pas un essai** : la préparer ne touche pas au
  moteur ; ce qui s'applique est ce que l'écran montre (curseur corrigé) ; la
  validation est une transaction relue (appliquer → relire → refaire, ou
  garder → « accepté par l'utilisateur, non revérifié » → avancer) ;
- **les courses** : proposition périmée (décision, nouvel essai), double clic,
  relecture fausse, invariants violés au curseur, voix sans accord ;
- **la parité voix / panneau** : mêmes événements, seule la source change ;
- **le panneau** : quatre zones, languette repliée qui dit l'état, curseurs,
  reçu, position bornée à la fenêtre.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_barehands_calibration_review_js import run  # noqa: E402

#: Le vrai parcours, la vraie séance de l'agent, et un gestionnaire d'essai
#: dont l'effectif relu suit ce qui est appliqué (sauf `lie` : un moteur qui ne
#: tient pas la valeur demandée).
RIG = r"""
/* Une posture de réveil refusée (30/09/2026) : pouce presque sur l'index,
   c'est un pincement (un clic), pas un réveil. */
const C_FINGERS={...REST_SIG,sigGap:.3,stillness:.9,cPose:0,wakePose:0,gapPalms:.3,indexReachPalms:1.71,secondaryRatio:.9,foldPalms:1.82};
const rig=extra=>{
  const o=extra||{};
  const events=[];
  const base={wakeGapMin:.46,releaseRatio:.42,wakeScore:.5,wakeHoldMs:1000,pointingFoldStartPalms:1.45,
    pointingFoldEndPalms:1.6};
  const stack=[],persisted=[];let serial=0;
  const effective=()=>Object.assign({},base,...persisted,...stack.map(s=>s.patch));
  const hands=v=>({left:{...v},right:{...v},unknown:{...v}});
  const trials={
    apply(patch){serial+=1;const trialId=`tr-${serial}`;stack.push({trialId,patch:{...patch}});
      const applied={...patch};if(o.lie)for(const k of Object.keys(applied))applied[k]+=.05;
      return {ok:true,code:null,applied,rejected:[],trialId,appliedAt:clock}},
    rollback(){const top=stack.pop();return top?{ok:true,code:null,applied:{},rejected:[],trialId:top.trialId,
      undone:[top.trialId],appliedAt:clock}:{ok:false,code:'barehands_trial_nothing_to_rollback'}},
    async accept(){await Promise.resolve();if(!stack.length)return {ok:false,code:'barehands_trial_nothing_to_accept'};
      const accepted=Object.assign({},...stack.map(s=>s.patch));persisted.push(accepted);
      const trialId=stack[stack.length-1].trialId;stack.length=0;
      return {ok:true,code:null,applied:{...accepted},accepted,trialId,appliedAt:clock}},
    status(){return {active:stack.length>0,trialId:stack.length?stack[stack.length-1].trialId:null}},
    delta(){return Object.assign({},...stack.map(s=>s.patch))},
  };
  const holder={S:null};
  const cal=calOf({onEvent:e=>events.push(e),
    holdAfterResult:stage=>!!holder.S&&holder.S.holdAfterResult(stage),
    stateRef:()=>holder.S?holder.S.stateRef():null,
    trialRef:()=>{const st=trials.status();return st.active?st.trialId:null},
    acceptedTrials:()=>holder.S?holder.S.acceptedSummary():[]});
  cal.start();
  const S=holder.S=A.createCalibrationAgentSession({contracts:C,flow:()=>cal,trials:()=>trials,
    values:()=>({effective:hands(effective()),saved:hands(Object.assign({},base,...persisted)),trial:trials.delta()}),
    now,held:()=>true,origin:cal.session().clockOrigin,emit:e=>events.push(e),revision:()=>events.length});
  return {cal,S,events,stack,persisted,effective};
};
/* Jusqu'à la revue du C, ratée « c'est un pincement ». */
const toCReview=r=>{toStage(r.cal,'c_pose');readOn(r.cal);untilReview(r.cal,C_FINGERS);return r.cal.review()};
/* L'assistant fait ce que la consigne lui demande : il note, il émet une
   hypothèse, il PRÉPARE. */
const propose=(r,patch)=>{
  r.S.recordFeedback({categories:['wake_hard'],text:'je n’arrive pas à replier les doigts'},'voice');
  const hy=r.S.proposeHypothesis({cause:'wake_too_strict',confidence:.5,evidence:[],
    feedbackRefs:[r.S.status().result.feedback.slice(-1)[0].ref]});
  return r.S.prepareTrial({hypothesisRef:hy.ok?hy.result.hypothesis.ref:'hy-1',
    patch:patch||{pointingFoldStartPalms:1.5,pointingFoldEndPalms:1.7},
    summary:'Assouplir le repli demandé aux trois autres doigts.',
    untouched:'Je ne touche pas à l’écart pouce-index : il est déjà dans la bonne plage.'});
};
const code=answer=>answer&&!answer.ok&&answer.errors?answer.errors[0].code:null;
const types=events=>events.map(e=>e.type);
"""


def test_the_c_review_names_its_cause_and_interprets_every_result(tmp_path):
    result = run(tmp_path, RIG + r"""
      const r=rig();
      const review=toCReview(r);
      const lis=deep(flowRoot()).filter(n=>n.tagName==='LI'&&n.getAttribute('data-metric'))
        .map(n=>[n.getAttribute('data-metric'),n.getAttribute('data-assessment'),n.children[1].textContent,
          n.children[2].textContent]);
      const checks=deep(flowRoot()).filter(n=>n.tagName==='LI'&&n.getAttribute('data-check'))
        .map(n=>[n.getAttribute('data-check'),n.getAttribute('data-assessment'),n.children[1].textContent]);
      const cause=deep(flowRoot()).filter(n=>n.getAttribute&&n.getAttribute('data-review-cause')).map(n=>n.children[1].textContent);
      const event=r.events.filter(e=>e.type==='review_ready').pop();
      out({status:review.status,cause:review.cause,checks:review.checks.map(c=>[c.id,c.assessment,c.word]),
        lines:review.lines.map(l=>[l.metric,l.value,l.assessment,l.word,l.mark]),lis,domChecks:checks,domCause:cause,
        event:{cause:event.cause,checks:event.checks,lines:event.lines}});
    """, "cCause")
    assert result["status"] == "failed"
    assert "clic" in result["cause"] and "0,30 paume" in result["cause"]
    checks = {row[0]: row[1:] for row in result["checks"]}
    # La posture relevée (30/09/2026) : plus de critère d'usine, seulement ce
    # qui l'empêcherait de servir — et ce qui a réussi se dit réussi.
    assert checks["stable"] == ["good", "oui"]
    assert checks["pinch"] == ["bad", "pouce presque sur l’index"]
    assert "rest" not in checks, "le repos ne se juge pas sur un pincement"
    assert checks["saved"] == ["neutral", "non"]
    lines = {row[0]: row[1:] for row in result["lines"]}
    assert lines["c_pose_gap_palms"][0] == 0.3
    assert lines["c_pose_fold_palms"][0] == 1.82
    # Aucune bande d'usine à laquelle se conformer : les nombres informent.
    assert lines["c_pose_fold_palms"][1] == "neutral"
    assert ["pinch", "bad", "✕ pouce presque sur l’index"] in result["domChecks"]
    assert result["domCause"] and "clic" in result["domCause"][0]
    assert result["event"]["cause"] == result["cause"]
    assert {"label": "Distincte d’un pincement (clic)", "word": "pouce presque sur l’index", "assessment": "bad"} \
        in result["event"]["checks"]


def test_assessments_come_from_the_runtime_not_from_the_size_of_the_number(tmp_path):
    result = run(tmp_path, r"""
      const cal=calOf();cal.start();readOn(cal);untilReview(cal,{});
      out(cal.review().lines.map(l=>[l.metric,l.assessment,l.word]));
    """, "assessNeutral")
    assert result and all(row[1] in ("good", "warning", "bad", "neutral") for row in result)


def test_events_follow_the_facts_in_order_and_carry_their_source(tmp_path):
    result = run(tmp_path, RIG + r"""
      const r=rig();
      readOn(r.cal);untilReview(r.cal,{});
      const cut=r.events.length;
      r.cal.validate();                               // un bouton
      const ui=r.events.slice(cut).map(e=>[e.type,e.stage,e.decision||null,e.next_stage||null,e.source||null,e.attempt]);
      const cut2=r.events.length;
      r.S.command('rerun',{exercise:'neutral'});     // la voix
      const voice=r.events.slice(cut2).map(e=>[e.type,e.stage,e.decision||null,e.source||null,e.attempt]);
      out({ui,voice,first:r.events[0]});
    """, "eventsOrder")
    assert result["first"] == {"type": "stage_entered", "stage": "neutral", "label": "Main au repos", "attempt": 1}
    assert result["ui"][0] == ["decision_committed", "neutral", "validated", "c_pose", "ui", 1]
    assert result["ui"][1][0:2] == ["stage_entered", "c_pose"], "la décision avant l'étape qu'elle ouvre"
    assert result["voice"][0] == ["decision_committed", "neutral", "rerun", "voice", 1]
    assert result["voice"][1] == ["stage_entered", "neutral", None, None, 2], "le nouvel essai porte son numéro"


def test_preparing_touches_nothing_and_the_panel_values_are_what_gets_applied(tmp_path):
    result = run(tmp_path, RIG + r"""
      const r=rig();
      toCReview(r);
      const prepared=propose(r);
      const afterPrepare={stack:r.stack.length,effective:r.effective().pointingFoldStartPalms,
        proposal:r.S.proposal()};
      /* L'utilisateur corrige au curseur : ramené au pas de la clé (0,05). */
      const edited=r.S.editProposal('pr-1','pointingFoldStartPalms',1.53);
      /* Un curseur qui viole un invariant : dit tout de suite, validation refusée. */
      const broken=r.S.editProposal('pr-1','pointingFoldEndPalms',1.5);
      const refusedBroken=await r.S.commitProposal({proposalRef:'pr-1',action:'rerun'},'panel');
      const reset=r.S.resetProposalKey('pr-1','pointingFoldEndPalms');
      const cut=r.events.length;
      const committed=await r.S.commitProposal({proposalRef:'pr-1',action:'rerun'},'panel');
      const again=await r.S.commitProposal({proposalRef:'pr-1',action:'rerun'},'panel');
      out({prepared:prepared.ok,afterPrepare,edited:edited.result.proposal.keys,
        broken:broken.result.proposal.errors.map(e=>e.code),refusedBroken:code(refusedBroken),
        reset:reset.result.proposal.errors.length,committed:committed.result,again:code(again),
        stack:r.stack.map(s=>s.patch),events:r.events.slice(cut).map(e=>[e.type,e.source||null,e.decision||null,e.attempt||null]),
        step:r.cal.stepId(),phase:r.cal.phase(),proposal:r.S.proposal().state,
        proposalEvent:r.events.find(e=>e.type==='proposal_ready')});
    """, "prepareCommit")
    assert result["prepared"] is True
    before = result["afterPrepare"]
    assert before["stack"] == 0 and before["effective"] == 1.45, "préparer ne touche pas au moteur"
    proposal = before["proposal"]
    assert proposal["state"] == "pending" and proposal["stage"] == "c_pose" and proposal["attempt"] == 1
    assert proposal["rerunStage"] == "c_pose"
    assert [(k["key"], k["effective"], k["saved"], k["proposed"]) for k in proposal["keys"]] == [
        ("pointingFoldStartPalms", 1.45, 1.45, 1.5), ("pointingFoldEndPalms", 1.6, 1.6, 1.7)]
    assert result["proposalEvent"]["source"] == "brain" and result["proposalEvent"]["proposal_ref"] == "pr-1"
    assert result["edited"][0]["value"] == 1.55 and result["edited"][0]["proposed"] == 1.5
    assert result["broken"] == ["barehands_trial_invariant_violated"]
    assert result["refusedBroken"] == "barehands_trial_invariant_violated"
    assert result["reset"] == 0
    committed = result["committed"]
    assert committed["steps"] == ["applied", "verified", "rerun"] and committed["verified"] is True
    assert committed["decision"] == "rerun" and committed["attempt"] == 2
    assert result["stack"] == [{"pointingFoldStartPalms": 1.55, "pointingFoldEndPalms": 1.7}], \
        "la valeur corrigée à l'écran, pas l'ancienne proposition du cerveau"
    assert result["again"] == "barehands_calibration_proposal_committed", "un double clic n'applique pas deux fois"
    assert result["events"][0] == ["trial_applied", "panel", None, None]
    assert result["events"][1] == ["decision_committed", "panel", "rerun", 1]
    assert result["events"][2] == ["stage_entered", None, None, 2]
    assert result["step"] == "c_pose" and result["proposal"] == "committed"


def test_a_proposal_goes_stale_when_the_screen_moves_on(tmp_path):
    result = run(tmp_path, RIG + r"""
      const r=rig();
      toCReview(r);
      propose(r);
      r.cal.rerun();                                     // l'utilisateur refait à la main
      const outOfReview=propose(r);                      // pendant l'exercice : pas de proposition
      const stale=await r.S.commitProposal({proposalRef:'pr-1',action:'rerun'},'panel');
      const status=r.S.status().result.proposal.state;
      untilReview(r.cal,C_FINGERS);
      propose(r);
      r.cal.skip('later');                               // décision prise ailleurs
      const staleAfterSkip=await r.S.commitProposal({proposalRef:'pr-2',action:'continue'},'panel');
      const edit=r.S.editProposal('pr-2','pointingFoldStartPalms',1.5);
      out({outOfReview:code(outOfReview),stale:code(stale),status,staleAfterSkip:code(staleAfterSkip),
        edit:code(edit),stack:r.stack.length,persisted:r.persisted.length});
    """, "stale")
    assert result["outOfReview"] == "barehands_calibration_not_in_review"
    assert result["stale"] == "barehands_calibration_proposal_stale" and result["status"] == "stale"
    assert result["staleAfterSkip"] == "barehands_calibration_proposal_stale"
    assert result["edit"] == "barehands_calibration_proposal_stale"
    assert result["stack"] == 0 and result["persisted"] == 0, "rien n'a été appliqué"


def test_a_readback_that_does_not_match_undoes_the_trial_and_blocks_nothing(tmp_path):
    result = run(tmp_path, RIG + r"""
      const r=rig({lie:true});
      toCReview(r);
      propose(r);
      const before=r.S.status().result.hypotheses[0].confidence;
      const answer=await r.S.commitProposal({proposalRef:'pr-1',action:'rerun'},'panel');
      const st=r.S.status().result;
      const next=propose(r,{wakeHoldMs:800});
      out({code:code(answer),stack:r.stack.length,trial:[st.trials[0].state,st.trials[0].verdict],
        confidence:[before,st.hypotheses[0].confidence],next:next.ok,step:r.cal.stepId(),phase:r.cal.phase()});
    """, "readback")
    assert result["code"] == "barehands_calibration_readback_mismatch"
    assert result["stack"] == 0 and result["trial"] == ["rolled_back", "inconclusive"]
    assert result["confidence"][0] == result["confidence"][1], "une panne du moteur ne dément pas l'hypothèse"
    assert result["next"] is True, "l'essai défait ne bloque pas la proposition suivante"
    assert result["phase"] == "review", "rien n'a bougé à l'écran"


def test_continue_keeps_the_values_says_unverified_and_the_report_keeps_saying_it(tmp_path):
    result = run(tmp_path, RIG + r"""
      const r=rig();
      toCReview(r);
      propose(r);
      const first=r.S.commitProposal({proposalRef:'pr-1',action:'continue'},'panel');
      const busy=await r.S.commitProposal({proposalRef:'pr-1',action:'continue'},'panel');
      const done=await first;
      const decision=r.events.filter(e=>e.type==='decision_committed').pop();
      const st=r.S.status().result;
      const summary=r.S.acceptedSummary();
      while(r.cal.isRunning()&&!r.cal.concluded())r.cal.skip('later');
      const row=find(flowRoot(),'jf-report')[0].children.map(li=>[li.children[0].textContent,li.children[2]?li.children[2].textContent:li.children[1].textContent])
        .find(([label])=>label==='Posture de réveil');
      const kept=deep(flowRoot()).filter(n=>n.getAttribute&&n.getAttribute('data-kept')).map(n=>n.children.map(c=>c.textContent));
      out({busy:code(busy),steps:done.result.steps,decision:[decision.decision,decision.next_stage,decision.source],
        persisted:r.persisted,basis:st.trials[0].basis,review:st.reviews.slice(-1)[0],summary,row,kept});
    """, "continue")
    assert result["busy"] == "barehands_calibration_commit_busy", "un second clic pendant la transaction"
    assert result["steps"] == ["applied", "verified", "saved", "advanced"]
    assert result["decision"] == ["accepted_unverified", "pinch_primary", "panel"]
    assert result["persisted"] == [{"pointingFoldStartPalms": 1.5, "pointingFoldEndPalms": 1.7}]
    assert result["basis"] == "user_unverified"
    assert result["review"]["decision"] == "accepted_unverified"
    assert "non revérifiée" in result["summary"][0]
    assert "accepté par vous · non revérifié sur cet exercice" in " ".join(result["row"])
    assert any("non revérifiée" in text for texts in result["kept"] for text in texts)


def test_voice_and_panel_make_the_same_business_events(tmp_path):
    result = run(tmp_path, RIG + r"""
      const play=async source=>{
        const r=rig();
        toCReview(r);
        propose(r);
        const cut=r.events.length;
        let answer;
        if(source==='voice'){
          const bare=await r.S.command('commit',{proposalRef:'pr-1',action:'continue'});
          if(code(bare)!=='barehands_calibration_consent_missing')throw new Error('voix sans accord acceptée');
          answer=await r.S.command('commit',{proposalRef:'pr-1',action:'continue',
            consent:{source:'voice',quote:'oui, garde et continue',verifiedBy:'control_center'}});
        }else answer=await r.S.commitProposal({proposalRef:'pr-1',action:'continue'},'panel');
        const seen={steps:answer.result.steps,events:r.events.slice(cut).map(e=>[e.type,e.source||null,e.decision||null]),
          consents:r.S.consents().map(c=>[c.source,c.quote,c.unverified])};
        r.cal.exit('test');
        return seen;
      };
      out({voice:await play('voice'),panel:await play('panel')});
    """, "parity")
    voice, panel = result["voice"], result["panel"]
    assert voice["steps"] == panel["steps"]
    assert [e[0] for e in voice["events"]] == [e[0] for e in panel["events"]], "une action métier = un événement"
    assert [e[2] for e in voice["events"]] == [e[2] for e in panel["events"]]
    assert {e[1] for e in voice["events"] if e[1]} == {"voice"} and {e[1] for e in panel["events"] if e[1]} == {"panel"}
    assert voice["consents"] == [["voice", "oui, garde et continue", True]]
    assert panel["consents"] == [["ui", "", True]]


def test_the_panel_shows_the_truth_edits_commits_and_stays_in_the_window(tmp_path):
    result = run(tmp_path, RIG + r"""
      const r=rig();
      const store={};const storage={getItem:k=>store[k]||null,setItem:(k,v)=>{store[k]=v}};
      const P=A.createCalibrationPanel({document,session:r.S,flow:()=>r.cal,storage,
        viewport:()=>({width:1280,height:720})});
      P.mount(flowRoot());
      const nodes=()=>deep(P.node());
      const attr=name=>nodes().filter(n=>n.getAttribute&&n.getAttribute(name)!==null);
      const texts=name=>attr(name).map(n=>n.textContent);
      toCReview(r);P.refresh();
      const zones=attr('data-zone').map(n=>n.getAttribute('data-zone'));
      const noProposal=nodes().filter(n=>n.getAttribute&&n.getAttribute('data-zone')==='proposal')[0].children.map(c=>c.textContent);
      propose(r);P.refresh();
      const badge=texts('data-panel-badge');
      const savedV=texts('data-value-saved'),effective=texts('data-value-effective'),proposed=texts('data-value-proposed');
      const results=attr('data-metric').map(n=>[n.getAttribute('data-metric'),n.getAttribute('data-assessment')]);
      const status=texts('data-panel-status');
      P.collapse(true);
      const tab=P.tab();
      P.collapse(false);
      const slider=attr('data-panel-slider')[0];
      slider.fire('input',{target:{value:'1.53'}});
      const afterSlide={value:r.S.proposal().keys[0].value,shown:texts('data-value-proposed')[0]};
      const panelButtons=()=>attr('data-panel-action').map(n=>[n.getAttribute('data-panel-action'),!!n.disabled]);
      const before=panelButtons();
      await P.commit('continue');
      const receipt=attr('data-receipt-step').map(n=>n.getAttribute('data-receipt-step'));
      const after=panelButtons();
      const badgeAfter=texts('data-panel-badge');
      const place=P.moveTo(-500,99999);
      out({zones,noProposal,badge,saved:savedV,effective,proposed,results,status,tab,afterSlide,before,receipt,after,badgeAfter,
        place,stored:JSON.parse(store['jarvis.barehands.calibrationPanel']),persisted:r.persisted});
    """, "panel")
    assert result["zones"] == ["exercise", "results", "proposal", "actions"]
    assert any("Aucune proposition" in text for text in result["noProposal"])
    assert result["badge"] == ["Proposition non appliquée"]
    assert result["saved"] == ["1,45 paume", "1,60 paume"] and result["effective"] == ["1,45 paume", "1,60 paume"]
    assert result["proposed"] == ["1,50 paume (+0,05)", "1,70 paume (+0,10)"]
    assert ["c_pose_fold_palms", "neutral"] in result["results"]
    assert result["status"] == ["✕ Échec"]
    assert result["tab"] == "C · essai 1 · 2 changements proposés"
    assert result["afterSlide"] == {"value": 1.55, "shown": "1,55 paume (+0,10) · corrigé"}
    assert result["before"] == [["rerun", False], ["continue", False], ["discard", False]]
    assert result["receipt"] == ["applied", "verified", "saved", "advanced"]
    assert all(disabled for _, disabled in result["after"]), "une proposition appliquée ne se revalide pas"
    assert result["badgeAfter"] == ["Appliquée"], "le panneau dit ce qui a été fait"
    assert result["persisted"] == [{"pointingFoldStartPalms": 1.55, "pointingFoldEndPalms": 1.7}]
    assert result["place"] == {"left": 12, "top": 672}, "l'en-tête reste attrapable dans la fenêtre"
    assert result["stored"]["position"] == {"left": 12, "top": 672} and result["stored"]["collapsed"] is False


def test_the_page_wires_the_panel_the_numbered_events_and_no_apply_door():
    """La page : le cerveau n'a plus de porte « applique » ; il prépare et
    l'utilisateur valide. Tous les événements (parcours et séance) passent par
    un seul fil numéroté, qui rafraîchit le panneau et part au Control Center,
    la revue avec le contexte de l'étape."""

    root = Path(__file__).resolve().parents[2] / "jarvis" / "runtime"
    source = (root / "control_center_barehands.js").read_text(encoding="utf-8")
    commands = (root / "control_center_barehands_commands.js").read_text(encoding="utf-8")
    assert "applyTrial:payload=>agentCall('apply',payload)" not in source
    assert "prepareTrial:payload=>agentCall('prepare',payload)" in source
    assert "commitProposal:payload=>agentCall('commit',payload)" in source
    assert "calibration_apply_trial" not in commands
    assert "calibration_prepare_trial:'prepareTrial'" in commands
    assert "calibration_commit_proposal:'commitProposal'" in commands
    assert "onEvent:event=>calibrationEvent(event)" in source
    assert "emit:event=>calibrationEvent(event),revision:()=>calibrationRevision" in source
    assert "const stamped=Object.freeze({...event,revision:calibrationRevision});" in source
    assert "agentPanel=AGENT.createCalibrationPanel(" in source and "agentPanel.close()" in source
    assert "context=agentSession.reviewContext(event.stage)" in source
