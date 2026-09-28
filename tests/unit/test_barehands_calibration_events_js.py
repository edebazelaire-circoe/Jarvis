"""Bare Hands — ce que le parcours de calibration dit à l'assistant, et la caméra au centre.

Retour utilisateur du 28/09 :

- le parcours annonce le début de chaque exercice, chaque revue (résultats
  affichés) et le rapport final (`deps.onEvent`) — c'est ce que la page envoie
  au Control Center pour que le cerveau l'analyse à voix haute ;
- sur les écrans où l'on place la main (repos, posture de réveil), la vue de la
  caméra est au centre (`deps.cameraView`) et la démonstration se range dans le
  coin ; ailleurs, rien ne change.

Harnais : celui de `test_barehands_calibration_review_js.py`.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_barehands_calibration_review_js import run  # noqa: E402


def test_the_flow_announces_stages_reviews_and_the_report(tmp_path):
    result = run(tmp_path, r"""
      const events=[];
      const cal=calOf({onEvent:event=>events.push(event)});
      cal.start();readOn(cal);untilReview(cal,{});
      const afterReview=events.slice();
      cal.validate();
      while(cal.isRunning()&&stepActions(flowRoot()).includes('skip'))skipStep(cal);
      const report=events.filter(e=>e.type==='report');
      /* Un écouteur qui lève ne touche pas au parcours. */
      const loud=calOf({onEvent:()=>{throw new Error('boom')}});
      loud.start();readOn(loud);untilReview(loud,{});
      out({afterReview,report,loud:[loud.stepId(),loud.phase()]});
    """, "events")
    first, review = result["afterReview"][0], result["afterReview"][-1]
    assert first == {"type": "stage", "stage": "neutral", "label": "Main au repos"}
    assert review["type"] == "review" and review["stage"] == "neutral" and review["status"] == "ok"
    assert review["attempt"] == 1 and review["held"] is False
    assert all(set(line) == {"label", "text"} for line in review["lines"])
    assert len(result["report"]) == 1
    report = result["report"][0]
    assert report["stages"][0]["label"] == "Main au repos" and report["stages"][0]["status"] == "ok"
    assert isinstance(report["willSave"], list) and "saving" in report
    assert result["loud"] == ["neutral", "review"]


def test_the_camera_is_centred_where_the_hand_is_placed_and_nowhere_else(tmp_path):
    result = run(tmp_path, r"""
      const seen=[];
      const cal=calOf({cameraView:()=>document.createElement('video')});
      cal.start();
      for(let i=0;i<3;i+=1){
        const nodes=deep(flowRoot());
        seen.push({stage:cal.stepId(),
          camera:nodes.filter(n=>n.getAttribute&&n.getAttribute('data-camera')).length,
          video:nodes.filter(n=>n.tagName==='VIDEO').length,
          aside:nodes.filter(n=>String(n.className||'').includes('jf-demo-aside')).length});
        skipStep(cal);
      }
      /* Sans caméra ouverte (`null`), l'écran reste celui d'avant. */
      const bare=calOf({cameraView:()=>null});
      bare.start();
      const none=deep(flowRoot()).filter(n=>n.getAttribute&&n.getAttribute('data-camera')).length;
      out({seen,none});
    """, "camera")
    assert result["seen"] == [
        {"stage": "neutral", "camera": 1, "video": 1, "aside": 1},
        {"stage": "c_pose", "camera": 1, "video": 1, "aside": 1},
        {"stage": "pinch_primary", "camera": 0, "video": 0, "aside": 0},
    ]
    assert result["none"] == 0
