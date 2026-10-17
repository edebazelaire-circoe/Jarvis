"""Aperçu de capture d'écran : le contrôleur pur de `control_center_screenshot_preview.js` (node, sans navigateur).

Handoff `jarvis-board-orbital-ui-workspace-rail`, Slice 05 ; architecture résolue §6 (D7). Contrat :
`docs/capture.md` › *Interface* › *Screenshot preview*. Horloge et actions injectées : ces tests disent
QUAND l'aperçu paraît, combien de temps il reste, ce qui le retient, et qu'aucune de ses fins ne supprime
rien. Le dessin et les vraies routes sont éprouvés dans Chrome par `test_screenshot_preview_browser.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

MODULE = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center_screenshot_preview.js"

#: Banc : horloge manuelle, actions enregistrées. `tick(ms)` avance l'horloge et lance les minuteries échues.
BENCH = """
const M=require(%s);
function bench(over={}){
  let t=1000,seq=0;const timers=new Map(),calls=[],logs=[],views=[];
  const actions={
    confirm:async item=>{calls.push(['confirm',item.artifactId]);return over.confirm===undefined?true:over.confirm},
    remove:async id=>{calls.push(['remove',id]);if(over.refuse)throw over.refuse;return {deleted:[id]}},
    attach:spec=>{calls.push(['attach',spec]);return over.attach||{ok:true}},
    openLightbox:(item,onClose)=>{calls.push(['lightbox',item.artifactId]);bench.close=onClose},
    say:text=>calls.push(['say',text]),
  };
  const c=M.createPreviewController({now:()=>t,later:(fn,ms)=>{const id=++seq;timers.set(id,{at:t+ms,fn});return id},
    unlater:id=>timers.delete(id),log:(level,key,data)=>logs.push([level,key,data]),onChange:v=>views.push(v),actions,
    dismissMs:6000});
  const tick=ms=>{const end=t+ms;for(;;){const due=[...timers].filter(([,x])=>x.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];
    if(!due)break;timers.delete(due[0]);t=due[1].at;due[1].fn()}t=end};
  return {c,tick,calls,logs,views,timers,now:()=>t};
}
const art=(n,extra={})=>({artifact_id:'jart_'+String(n).padStart(32,'0'),kind:'screenshot',state:'complete',mime_type:'image/png',
  width:1920,height:1080,size_bytes:245760,...extra});
const shot=(n,extra={},at=1700000000000)=>({capture:{capture_id:'cap_'+n},artifact:art(n,extra),device:'default',at});
"""


def node(script: str):
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node absent")
    code = (BENCH % json.dumps(str(MODULE))
            + f"(async()=>{{const out=await (async()=>{{{script}}})();process.stdout.write(JSON.stringify(out))}})()"
            + ".catch(e=>{console.error(e);process.exit(1)})")
    done = subprocess.run([exe, "-e", code], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_shown_only_after_successful_screenshot():
    out = node("""
      const b=bench(),r={};
      const before=shot(1);
      r.initial=b.c.accept({shot:before});                       // capture d'avant le chargement : vue, jamais montrée
      r.repaint=b.c.accept({shot:before});                       // même résultat repeint chaque seconde
      r.failed=b.c.accept({shot:before,note:{control:'screenshot'}});   // une capture ratée ne change pas `shot`
      r.afterFailed=b.c.view().shown;
      r.none=b.c.accept({shot:null});
      r.pending=b.c.accept({shot:shot(2,{state:'pending'})});
      r.failedArtifact=b.c.accept({shot:shot(3,{state:'failed'})});
      r.recording=b.c.accept({shot:shot(4,{kind:'screen_recording'})});
      r.badId=b.c.accept({shot:{capture:{},artifact:{...art(5),artifact_id:'../../etc'}}});
      r.noArtifact=b.c.accept({shot:{capture:{capture_id:'cap_6'},artifact:null}});
      r.shownBeforeSuccess=b.c.view().shown;
      const ok=shot(7);
      r.success=b.c.accept({shot:ok});
      r.view=b.c.view();
      r.again=b.c.accept({shot:ok});
      r.skipped=b.logs.filter(l=>l[1]==='preview_skipped').map(l=>l[2].reason);
      r.shownLogs=b.logs.filter(l=>l[1]==='preview_shown').length;
      return r;""")
    assert out["initial"] is False and out["repaint"] is False and out["failed"] is False
    assert out["afterFailed"] is False, "a failed screenshot shows nothing"
    assert [out[k] for k in ("none", "pending", "failedArtifact", "recording", "badId", "noArtifact")] == [False] * 6
    assert out["shownBeforeSuccess"] is False
    assert out["skipped"] == ["not_complete", "not_complete", "not_a_screenshot", "no_artifact", "no_artifact"]
    assert out["success"] is True and out["again"] is False and out["shownLogs"] == 1
    item = out["view"]["item"]
    assert out["view"]["shown"] is True and out["view"]["image"] == "loading"
    assert item["artifactId"] == "jart_" + "7".zfill(32) and item["captureId"] == "cap_7"
    assert item["url"] == "/api/artifacts/jart_00000000000000000000000000000007/payload", "only the bounded payload route"
    assert (item["width"], item["height"], item["size"], item["type"]) == (1920, 1080, 245760, "PNG")
    assert item["title"].startswith("Capture d’écran · ") and item["name"].endswith(".png")


def test_auto_dismiss_paused_on_hover_focus_and_never_deletes():
    out = node("""
      const b=bench(),r={};
      b.c.accept({shot:null});b.c.accept({shot:shot(1)});
      b.tick(5900);r.at5900=b.c.view().shown;
      b.c.hold('hover');b.tick(60000);r.hoveredAfter60s=b.c.view().shown;r.paused=b.c.view().paused;
      b.c.release('hover');b.tick(5900);r.releasedAt5900=b.c.view().shown;     // le délai repart ENTIER
      b.c.hold('focus');b.c.hold('hover');b.c.release('hover');b.tick(30000);r.focusHolds=b.c.view().shown;
      r.holds=b.c.view().holds;
      b.c.release('focus');b.tick(6001);r.afterRelease=b.c.view().shown;
      r.reason1=b.logs.filter(l=>l[1]==='preview_dismissed').map(l=>l[2].reason);
      // Fermeture explicite (× ou Échap) puis nouvelle capture qui expire : aucune ne supprime.
      b.c.accept({shot:shot(2)});b.c.dismiss('escape');
      b.c.accept({shot:shot(3)});b.c.dismiss('close');
      b.c.accept({shot:shot(4)});b.tick(6001);
      // La visionneuse ouverte retient aussi l'aperçu ; sa fermeture relance le délai.
      b.c.accept({shot:shot(5)});b.c.open();b.tick(20000);r.lightboxHolds=b.c.view().shown;bench.close();b.tick(6001);
      r.afterLightbox=b.c.view().shown;
      r.reasons=b.logs.filter(l=>l[1]==='preview_dismissed').map(l=>l[2].reason);
      r.calls=b.calls.map(c=>c[0]);
      r.timers=b.timers.size;
      return r;""")
    assert out["at5900"] is True
    assert out["hoveredAfter60s"] is True and out["paused"] is True
    assert out["releasedAt5900"] is True, "the delay restarts in full after a release"
    assert out["focusHolds"] is True and out["holds"] == ["focus"]
    assert out["afterRelease"] is False and out["reason1"] == ["timeout"]
    assert out["lightboxHolds"] is True and out["afterLightbox"] is False
    assert out["reasons"] == ["timeout", "escape", "close", "timeout", "timeout"]
    assert "remove" not in out["calls"] and "confirm" not in out["calls"], "dismissing never deletes"
    assert out["calls"] == ["lightbox"] and out["timers"] == 0


def test_payload_failure_shows_placeholder_keeps_actions():
    out = node("""
      const b=bench(),r={};
      b.c.accept({shot:null});b.c.accept({shot:shot(1)});
      const id=b.c.view().item.artifactId;
      b.c.imageFailed('jart_other','artifact_not_found');           // une autre image : ignorée
      r.stillLoading=b.c.view().image;
      b.c.imageFailed(id,'artifact_payload_missing');
      r.view=b.c.view();
      r.text=M.payloadText(r.view.imageCode);
      r.unknownText=M.payloadText('http_502');
      b.c.imageReady(id);r.late=b.c.view().image;                  // un « chargé » tardif l'emporte
      r.open=b.c.open();bench.close();
      r.sent=b.c.send();
      b.c.accept({shot:shot(2)});const id2=b.c.view().item.artifactId;b.c.imageFailed(id2,'core_unreachable');
      r.removed=await b.c.remove();
      r.calls=b.calls.filter(c=>c[0]!=='say').map(c=>c[0]==='attach'?['attach',c[1]]:c);
      r.warn=b.logs.filter(l=>l[1]==='preview_payload_failed').map(l=>l[2]);
      return r;""")
    assert out["stillLoading"] == "loading"
    view = out["view"]
    assert view["shown"] is True and view["image"] == "failed" and view["imageCode"] == "artifact_payload_missing"
    assert out["text"] == "Aperçu indisponible : fichier absent (artifact_payload_missing)."
    assert out["unknownText"] == "Aperçu indisponible : erreur (http_502)."
    assert out["late"] == "ready"
    assert out["open"] is True and out["sent"] == "sent" and out["removed"] == "deleted"
    one, two = "jart_" + "1".zfill(32), "jart_" + "2".zfill(32)
    attach = out["calls"][1][1]
    assert out["calls"][0] == ["lightbox", one]
    assert attach == {"artifact_id": one, "original_name": attach["original_name"], "mime_type": "image/png",
                      "size_bytes": 245760} and attach["original_name"].startswith("Capture d’écran ")
    assert out["calls"][2:] == [["confirm", two], ["remove", two]]
    assert [w["code"] for w in out["warn"]] == ["artifact_payload_missing", "core_unreachable"]


def test_delete_adversarial_double_click_refusal_and_cancel():
    """Une seule suppression en vol ; une confirmation refusée ne supprime rien ; un refus de Core reste lisible
    avec son code et l'aperçu reste (rien n'a changé chez Core)."""

    out = node("""
      const r={};
      let b=bench();b.c.accept({shot:null});b.c.accept({shot:shot(1)});
      const first=b.c.remove(),second=b.c.remove();
      r.double=[await first,await second];r.doubleCalls=b.calls.filter(c=>c[0]==='remove').length;
      b=bench({confirm:false});b.c.accept({shot:null});b.c.accept({shot:shot(2)});
      r.cancel=await b.c.remove();r.cancelCalls=b.calls.map(c=>c[0]);r.cancelShown=b.c.view().shown;
      b.tick(6001);r.cancelThenTimeout=b.c.view().shown;
      b=bench({refuse:{code:'artifact_has_dependents',status:409,message:'has dependents'}});
      b.c.accept({shot:null});b.c.accept({shot:shot(3)});
      r.refused=await b.c.remove();r.refusedView=b.c.view();
      r.said=b.calls.filter(c=>c[0]==='say').map(c=>c[1]);
      b=bench({refuse:{code:'artifact_not_found',status:404}});
      b.c.accept({shot:null});b.c.accept({shot:shot(4)});
      r.gone=await b.c.remove();r.goneNote=b.c.view().note;
      b=bench({attach:{ok:false,code:'sending'}});b.c.accept({shot:null});b.c.accept({shot:shot(5)});
      r.sendRefused=b.c.send();r.sendNote=b.c.view().note;r.sendShown=b.c.view().shown;
      return r;""")
    assert out["double"] == ["deleted", "busy"] and out["doubleCalls"] == 1
    assert out["cancel"] == "cancelled" and out["cancelCalls"] == ["confirm"] and out["cancelShown"] is True
    assert out["cancelThenTimeout"] is False, "the delay is re-armed after a cancelled confirmation"
    view = out["refusedView"]
    assert out["refused"] == "refused" and view["shown"] is True and view["busy"] is None
    assert view["note"] == {"tone": "bad", "code": "artifact_has_dependents", "text":
                            "Suppression refusée : d’autres éléments en dérivent (une annotation, par exemple) (artifact_has_dependents)."}
    assert out["said"] == [view["note"]["text"]]
    assert out["gone"] == "refused" and out["goneNote"]["code"] == "artifact_not_found"
    assert out["sendRefused"] == "refused" and out["sendShown"] is True and out["sendNote"]["code"] == "sending"


def test_annotate_holds_preview_and_shows_the_derived_screenshot():
    """S05.B : l'éditeur retient l'aperçu ; une annotation enregistrée (NOUVELLE capture de Core) prend la place de
    l'originale dans l'aperçu ; un éditeur fermé sans enregistrer relâche le délai ; rien n'est supprimé."""

    out = node("""
      const r={};let hooks=null;
      const b=bench();b.c.accept({shot:null});b.c.accept({shot:shot(1)});
      r.noEditor=b.c.annotate();                                 // le banc n'a pas d'éditeur : refus dit, aperçu gardé
      r.note=b.c.view().note;
      const c=M.createPreviewController({now:b.now,later:(fn,ms)=>setTimeout(fn,0)&&0,unlater:()=>{},log:()=>{},onChange:()=>{},
        dismissMs:6000,actions:{openEditor:(item,h)=>{hooks=h},say:()=>{},confirm:async()=>true,remove:async()=>{},attach:()=>({ok:true}),openLightbox:()=>{}}});
      c.accept({shot:null});c.accept({shot:shot(2)});
      r.opened=c.annotate();r.paused=c.view().paused;r.holds=c.view().holds;
      hooks.closed();r.afterClose=c.view().holds;
      c.annotate();
      hooks.saved({...art(3),artifact_id:'jart_'+'3'.padStart(32,'0')});
      r.after=c.view().item.artifactId;r.holdsAfter=c.view().holds;
      return r;""")
    assert out["noEditor"] == "failed" and out["note"]["code"] == "editor_failed"
    assert out["opened"] == "opened" and out["paused"] is True and out["holds"] == ["annotate"]
    assert out["afterClose"] == []
    assert out["after"] == "jart_" + "3".zfill(32) and out["holdsAfter"] == []


def test_confirmation_failure_or_replacement_is_said_never_silent():
    """QA S05, polish 3 : une confirmation impossible (`confirmDialog` absent, levée) ne vaut pas une annulation
    muette — l'aperçu le dit et rien n'est supprimé ; un aperçu remplacé pendant la confirmation le dit aussi."""

    out = node("""
      const r={};
      const b=bench();
      const failing=M.createPreviewController({now:b.now,later:()=>0,unlater:()=>{},log:()=>{},onChange:()=>{},dismissMs:6000,
        actions:{confirm:async()=>{throw new Error('confirmDialog absent')},remove:async()=>{r.removed=true},
          say:t=>{(r.said=r.said||[]).push(t)},attach:()=>({ok:true}),openLightbox:()=>{}}});
      failing.accept({shot:null});failing.accept({shot:shot(2)});
      r.failed=await failing.remove();r.failedView=failing.view();
      let release=null;
      const slow=M.createPreviewController({now:b.now,later:()=>0,unlater:()=>{},log:()=>{},onChange:()=>{},dismissMs:6000,
        actions:{confirm:()=>new Promise(ok=>{release=ok}),remove:async()=>{r.removedSlow=true},
          say:t=>{(r.saidSlow=r.saidSlow||[]).push(t)},attach:()=>({ok:true}),openLightbox:()=>{}}});
      slow.accept({shot:null});slow.accept({shot:shot(3)});
      const pending=slow.remove();slow.accept({shot:shot(4)});release(true);
      r.replaced=await pending;r.replacedItem=slow.view().item.artifactId;
      return r;""")
    assert out["failed"] == "refused" and "removed" not in out
    view = out["failedView"]
    assert view["shown"] is True and view["busy"] is None
    assert view["note"] == {"tone": "bad", "code": "confirm_unavailable", "text": "Confirmation impossible : la capture n’a pas été supprimée."}
    assert out["said"] == [view["note"]["text"]]
    assert out["replaced"] == "gone" and "removedSlow" not in out and out["replacedItem"].endswith("4")
    assert out["saidSlow"] == ["Une nouvelle capture a remplacé l’aperçu : rien n’a été supprimé."]


def test_name_and_title_follow_core_clock_and_mark_annotated_copies():
    """QA S05, polish 2 et 6 : le nom de la pièce suit l'heure de Core (`created_at`, celle du brief du cerveau),
    et une copie annotée se dit « annotée » dans le titre et le nom."""

    out = node("""
      const iso='2026-10-17T12:34:56Z',d=new Date(iso),two=n=>String(n).padStart(2,'0');
      const b=bench();b.c.accept({shot:null});b.c.accept({shot:shot(1,{created_at:iso},Date.parse(iso)+4000)});
      const plain=b.c.view().item;
      b.c.accept({shot:shot(2,{created_at:iso,source:'annotation',metadata:{annotated_from:'jart_'+'1'.padStart(32,'0')}})});
      const marked=b.c.view().item;
      return {plain:[plain.title,plain.name],marked:[marked.title,marked.name],
        hm:two(d.getHours())+':'+two(d.getMinutes()),file:two(d.getHours())+'-'+two(d.getMinutes())+'-'+two(d.getSeconds())};""")
    assert out["plain"] == [f"Capture d’écran · {out['hm']}", f"Capture d’écran {out['file']}.png"]
    assert out["marked"] == [f"Capture d’écran · {out['hm']} · annotée", f"Capture d’écran {out['file']} annotée.png"]
