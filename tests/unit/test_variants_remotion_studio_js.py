"""« Remotion Studio » in Variants, by node (handoff jarvis-remotion-native-studio-playback-fix, Slice 11: first-class Remotion Studio and
Variants choices).

Two levels, each with negative cases:

1. The pure model (`JarvisVariantsRemotionStudio.doorModel`): why the button is refused (no scene, not a Remotion scene, no Remotion
   Studio on this Core, environment not ready, a run), how Remotion Studio relates to the scene on screen (this pin, another version of
   the same source, another scene), the start counter, a failure with its code, unpublished files said « pas publiés », the click the
   browser needs; the Remotion test mirrors `jarvis.domain.prefab.is_remotion_manifest`.
2. The explorer on the fake DOM with the real modules: the button sits on the scene row beside « Présenter »; a click opens ONE
   confirmation in Variants' layer (risk, exact version, provenance); « Annuler » or `Échap` launches nothing; « Ouvrir » sends Core's
   `open` with the scene's EXACT pin and the acknowledgment, pauses the video, opens the tab while the click is fresh, and keeps the
   variant, the scene and the tree as they were; a refused or failed start is said with its code, logged, and « Réessayer » works; a
   start too long for the browser's permission offers the link; coming back to Jarvis (focus) re-reads Remotion Studio and says its
   unpublished files; during a run the door is hidden; the rail's « Remotion Studio… » entry opens Variants then this door.

Real Chrome: `test_variants_remotion_studio_browser.py`. Contract: `docs/presentation-studio.md` › *Remotion Studio from Variants
(Level 3, Slice 11)*.
"""

from __future__ import annotations

import json
import subprocess

from jarvis.domain.prefab import is_remotion_manifest
from tests.fakes.explorer_js import RUNTIME, run_ui
from tests.unit.test_variants_run_js import RUN_UI

DOOR_JS = json.dumps(str(RUNTIME / "control_center_presentation_studio_explorer_remotion.js"))
RAIL_JS = json.dumps(str(RUNTIME / "control_center_presentation_rail.js"))


def node(script: str) -> object:
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


PIN = {"id": "lab.dial", "version": 1}
SCENE = {"id": "pss_000000000001", "title": "Ouverture", "number": 1, "of": 3, "prefab": PIN}


def model(**inputs) -> dict:
    base = {"scene": SCENE, "scenes": [{"id": SCENE["id"], "title": "Ouverture", "prefab": PIN},
                                       {"id": "pss_000000000002", "title": "Chiffres", "prefab": {"id": "lab.chart", "version": 4}}],
            "detail": {"state": "ready", "remotion": True}, "studio": {"status": "stopped", "pin": None}, "capability": {"status": "ready"},
            "readError": None, "busy": None, "actionError": None, "run": False, "needsClick": False, "explain": None, "now": 100_000}
    base.update(inputs)
    return node(f"const D=require({DOOR_JS});process.stdout.write(JSON.stringify(D.doorModel({json.dumps(base)})));")


READY = {"status": "ready", "url": "http://127.0.0.1:41000/", "viewers": 1, "pin": {"prefab_id": "lab.dial", "version": 1}, "work_copy": {}}


# ------------------------------------------------------------------ 1. the pure model

def test_the_button_says_why_it_is_refused_and_never_blocks_a_ready_remotion_scene():
    assert model()["button"]["blocked"] is None and model()["status"] is None, "a ready Remotion scene: one click, nothing to say yet"
    cases = {
        "no scene": ({"scene": None}, "Aucune scène"),
        "not Remotion": ({"detail": {"state": "ready", "remotion": False}}, "pas une scène Remotion"),
        "no Remotion Studio on this Core": ({"readError": {"code": "remotion_studio_unavailable", "text": "x"}}, "pas de Remotion Studio"),
        "environment not installed": ({"capability": {"status": "not_installed"}}, "pas prêt (non installé)"),
        "a run": ({"run": True}, "présentation est en cours"),
    }
    for name, (inputs, words) in cases.items():
        blocked = model(**inputs)["button"]["blocked"]
        assert blocked and words in blocked, (name, blocked)
    # unknown is not « not Remotion »: a failed read leaves the button usable (Core refuses a wrong pin by its own code)
    assert model(detail={"state": "error", "remotion": None})["button"]["blocked"] is None
    assert model(capability=None)["button"]["blocked"] is None


def test_remotion_studio_on_this_pin_another_version_or_another_scene_is_said_never_corrected():
    here = model(studio=READY)
    assert here["relation"] == "here" and here["button"]["state"] == "here"
    assert here["button"]["ariaLabel"] == "Remotion Studio, ouvert sur cette scène"
    assert here["status"]["tone"] == "ok" and "ouvert sur cette scène (source v1)" in here["status"]["text"]
    assert here["status"]["link"] == {"url": READY["url"], "label": "Ouvrir un autre onglet Remotion Studio"}
    assert "Ouvrir un autre onglet" in here["button"]["title"], "noopener: a click opens another tab, and the words say so"
    older = model(studio={**READY, "pin": {"prefab_id": "lab.dial", "version": 0}}, scene={**SCENE, "prefab": {"id": "lab.dial", "version": 1}})
    assert older["relation"] == "version" and older["status"]["tone"] == "warn"
    assert "version 0 de cette scène ; la variante utilise la version 1" in older["status"]["text"] and older["status"].get("link") is None
    other = model(studio={**READY, "pin": {"prefab_id": "lab.chart", "version": 4}})
    assert other["relation"] == "other" and "la scène 2 (« Chiffres »)" in other["status"]["text"]
    foreign = model(studio={**READY, "pin": {"prefab_id": "x.y", "version": 9}})
    assert "une autre source (x.y v9)" in foreign["status"]["text"]


def test_unpublished_files_are_said_unpublished_never_saved():
    m = model(studio={**READY, "work_copy": {"modified_files": ["src/Scene.tsx", "src/a.ts"], "edits_saved": 0}})
    assert m["status"]["tone"] == "warn"
    # Slice 12: the workspace says it, and publishing is offered (the base is this scene's pin)
    assert "2 fichiers modifiés dans Remotion Studio, pas encore publiés : la variante n’a pas changé" in m["status"]["text"]
    assert "enregistr" not in m["status"]["text"] and m["status"]["publish"] is True
    kept = model(studio={**READY, "work_copy": {"modified_files": [], "edits_saved": 1}})
    assert "1 fichier mis de côté (studio-edits) à votre demande : pas publié." in kept["status"]["text"]


def test_starting_failing_and_the_click_the_browser_needs():
    busy = model(busy={"label": "Remotion Studio démarre…", "at": 88_000})
    assert busy["status"]["spin"] is True and busy["status"]["text"] == "Remotion Studio démarre… 12 s (2 min au plus)."
    assert busy["button"]["state"] == "busy"
    starting = model(studio={"status": "starting", "started_at": 70, "pin": None})
    assert starting["status"]["text"] == "Remotion Studio démarre… 30 s (2 min au plus)."
    failed = model(studio={"status": "failed", "last_error_code": "remotion_studio_start_timeout", "diagnostics": ["a", "b"], "pin": None})
    assert failed["status"]["tone"] == "danger" and "(remotion_studio_start_timeout)" in failed["status"]["text"]
    assert "n’a pas répondu dans le délai" in failed["status"]["text"] and failed["status"]["retry"] is True
    assert failed["status"]["diagnostics"] == ["a", "b"]
    refused = model(actionError={"code": "remotion_studio_runtime_unavailable", "text": "pas prêt"})
    assert refused["status"]["text"] == "Remotion Studio : pas prêt (remotion_studio_runtime_unavailable)" and refused["status"]["retry"]
    click = model(studio={**READY, "viewers": 0}, needsClick=True)
    assert "n’ouvre un onglet qu’après un clic" in click["status"]["text"]
    assert click["status"]["link"]["label"] == "Ouvrir l’onglet Remotion Studio"


def test_the_remotion_test_is_the_one_of_the_prefab_domain():
    vectors = [None, {}, {"schema_version": 1}, {"schema_version": 2}, {"schema_version": 3}, {"schema_version": 3, "source": {}},
               {"schema_version": "2"}, {"schema_version": 2, "source": None}, [], "x"]
    out = node(f"const D=require({DOOR_JS});process.stdout.write(JSON.stringify({json.dumps(vectors)}.map(v=>D.isRemotionManifest(v))));")
    assert out == [is_remotion_manifest(v) for v in vectors]


# ------------------------------------------------------------------ 2. the explorer on the fake DOM

#: A fake Remotion Studio behind the relay (`/api/local-capabilities/remotion*`) and the library read (`/api/prefabs/{id}/{version}`).
STUDIO_WORLD = RUN_UI + r"""
const rms={studio:{status:'stopped',pin:null,url:null,viewers:0,work_copy:{}},cap:{status:'ready'},opens:[],openReply:null,openDelay:0,
  remotion:true,provenance:{origin:'custom',created_by:{actor:'user'}},studioStatus:200};
env.route('/api/local-capabilities/remotion',(url,rec,body)=>{
  if(url==='/api/local-capabilities/remotion')return {status:200,body:{capability:rms.cap}};
  if(url.endsWith('/studio')&&rec.method==='GET')return rms.studioStatus===200?{status:200,body:{studio:rms.studio}}
    :{status:rms.studioStatus,body:{error:{code:'remotion_studio_unavailable',message:'no studio'}}};
  if(url.endsWith('/studio/open')){
    rms.opens.push(body);
    if(rms.openReply)return Object.assign({delay:rms.openDelay},rms.openReply(body));
    rms.studio={status:'ready',pin:{prefab_id:body.prefab_id,version:body.version},url:'http://127.0.0.1:41000/',viewers:0,work_copy:{}};
    return {status:200,body:{studio:rms.studio},delay:rms.openDelay};
  }
  return {status:404,body:{error:{code:'no_route',message:url}}};
});
env.route('/api/prefabs/',()=>({status:200,body:{id:'lab.dial',version:1,manifest:rms.remotion?{schema_version:2,source:{}}:{schema_version:1},
  publication:{provenance:rms.provenance}}}));
const tabs=[];win.open=(...args)=>{tabs.push(args);return null};
const door=()=>q('[data-act="remotion_studio"]');
const status=()=>q('.jvx-rms');
const say=()=>q('.jvx-rms-text').textContent;
const dialog=()=>q('[data-kind="remotion_studio"]');
const go=()=>q('[data-act="remotion_studio_confirm"]');
const openVariants=async()=>{seed(3);const ex=make({player:fakePlayer});await ex.open({presentation_id:PID,fullscreen:false});await env.advance(600);return ex};
"""


def test_the_button_is_on_the_scene_row_and_a_confirmed_open_sends_the_exact_pin_and_keeps_variants_as_it_was(tmp_path):
    out = run_ui(tmp_path, STUDIO_WORLD + r"""
      const ex=await openVariants();
      ex.select(vid(2));await env.advance(600);
      q('.jvx-strip [data-scene="pss_000000000002"]').click();await env.advance(200);
      const before={state:ex.state(),order:[...q('.jvx-stage-note').children].map(c=>c.dataset.act||c.className)};
      door().click();await env.advance(50);
      const dlg=dialog();
      const seen={modal:dlg&&dlg.getAttribute('aria-modal'),title:dlg&&q('h2',dlg).textContent,text:dlg?dlg.textContent:'',
        goLabel:go()&&go().textContent,inert:q('.jvx-body').inert,opens:rms.opens.length};
      go().click();await env.advance(200);
      const after=ex.state();
      return {before,seen,opens:rms.opens,tabs,after,status:say(),tone:status().getAttribute('data-tone'),
        button:[door().getAttribute('data-state'),door().getAttribute('aria-label')],dialogGone:!dialog(),
        logs:env.logs.filter(l=>l[1].includes('remotion_studio')).map(l=>l[1].split(' ')[1])};
    """)
    order = out["before"]["order"]
    # master Slice 08: « Exporter la vidéo » sits between the door and « Présenter » (hidden until the whole video is asked for)
    # presentation-edition-v1 Slice 09: « Modifier » (edit_scene) sits just before « Présenter ».
    assert order.index("remotion_studio") == order.index("video_export") - 1 == order.index("edit_scene") - 2 == order.index("present") - 3, ("beside « Présenter » on the scene row", order)
    assert order[0] == "jvx-transport", "the transport row stays alone (Slice 10)"
    s = out["seen"]
    assert s["modal"] == "true" and s["inert"] is True and s["opens"] == 0, "a modal confirmation first, nothing launched yet"
    assert s["title"] == "Ouvrir cette scène hors du bac à sable ?" and s["goLabel"] == "Ouvrir cette scène dans Remotion Studio"
    assert "Sans bac à sable" in s["text"] and "Scène 2 sur 3" in s["text"] and "source v1" in s["text"] and "auteur : vous" in s["text"]
    assert "n’atteint la variante que par « Publier dans la variante… »" in s["text"]
    assert out["opens"] == [{"prefab_id": "lab.dial", "version": 1, "acknowledge_unsandboxed_scene": True}], "the exact pin, acknowledged"
    assert out["tabs"] == [["http://127.0.0.1:41000/", "jarvis-remotion-studio", "noopener,noreferrer"]], "the tab, while the click is fresh"
    b, a = out["before"]["state"], out["after"]
    assert (a["open"], a["selected"], a["preview"]["scene"], a["active"]) == (True, b["selected"], b["preview"]["scene"], b["active"]) \
        and a["selected"].endswith("2") and a["preview"]["scene"] == "pss_000000000002", "Variants keeps the variant and the scene"
    assert out["dialogGone"] and out["tone"] == "ok" and "ouvert sur cette scène" in out["status"]
    assert out["button"] == ["here", "Remotion Studio, ouvert sur cette scène"]
    assert "remotion_studio_open_requested" in out["logs"] and "remotion_studio_ready" in out["logs"]


def test_cancel_and_escape_launch_nothing(tmp_path):
    out = run_ui(tmp_path, STUDIO_WORLD + r"""
      rms.provenance={origin:'custom',created_by:{actor:'brain'}};
      const ex=await openVariants();
      door().click();await env.advance(50);
      const danger={title:q('h2',dialog()).textContent,danger:go().hasAttribute('data-danger'),focusCancel:doc.activeElement!==go()};
      qa('button',dialog()).find(b=>b.textContent==='Annuler').click();await env.advance(50);
      const afterCancel={dialog:!!dialog(),focusBack:doc.activeElement===door()};
      door().click();await env.advance(50);
      env.key(doc.activeElement,'Escape');await env.advance(50);
      return {danger,afterCancel,escaped:!dialog(),open:ex.isOpen(),opens:rms.opens.length,tabs:tabs.length,
        logs:env.logs.filter(l=>l[1].includes('remotion_studio_cancelled')).length};
    """)
    assert out["danger"] == {"title": "Ouvrir une scène que vous n’avez pas écrite ?", "danger": True, "focusCancel": True}
    assert out["afterCancel"] == {"dialog": False, "focusBack": True}
    assert out["escaped"] is True and out["open"] is True, "Échap closes the confirmation only"
    assert out["opens"] == 0 and out["tabs"] == 0, "cancelling launches nothing"
    assert out["logs"] == 2


def test_a_failed_or_refused_start_is_said_with_its_code_logged_and_retry_works(tmp_path):
    out = run_ui(tmp_path, STUDIO_WORLD + r"""
      const ex=await openVariants();
      rms.openReply=()=>({status:200,body:{studio:{status:'failed',pin:null,last_error_code:'remotion_studio_start_timeout',diagnostics:['webpack: compile']}}});
      rms.studio={status:'failed',pin:null,last_error_code:'remotion_studio_start_timeout',diagnostics:['webpack: compile']};
      door().click();await env.advance(50);go().click();await env.advance(300);
      const failed={text:say(),tone:status().getAttribute('data-tone'),retry:!q('[data-act="remotion_studio_retry"]').hidden,
        log:!q('.jvx-rms-log').hidden,tabs:tabs.length};
      rms.openReply=()=>({status:409,body:{error:{code:'remotion_studio_runtime_unavailable',message:'not ready'}}});
      q('[data-act="remotion_studio_retry"]').click();await env.advance(50);go().click();await env.advance(300);
      const refused={text:say(),tone:status().getAttribute('data-tone')};
      rms.openReply=null;
      q('[data-act="remotion_studio_retry"]').click();await env.advance(50);go().click();await env.advance(300);
      return {failed,refused,ok:say(),opens:rms.opens.length,tabs:tabs.length,busyAfter:door().getAttribute('aria-disabled'),
        errors:env.logs.filter(l=>l[0]==='error'&&l[1].includes('remotion_studio_open_failed')).length};
    """)
    f = out["failed"]
    assert f["tone"] == "danger" and "remotion_studio_start_timeout" in f["text"] and f["retry"] and f["log"] and f["tabs"] == 0
    assert out["refused"]["tone"] == "danger" and "(remotion_studio_runtime_unavailable)" in out["refused"]["text"]
    assert "L’environnement Remotion n’est pas prêt" in out["refused"]["text"], "Core's code said in words"
    assert "ouvert sur cette scène" in out["ok"] and out["opens"] == 3 and out["tabs"] == 1, "« Réessayer » goes through the confirmation again"
    assert out["busyAfter"] == "false", "the button is released in every case"
    assert out["errors"] == 2, "each failure is logged at error (Error Logs through obsClientLog)"


def test_refusals_before_any_dialog_not_remotion_no_studio_and_not_ready(tmp_path):
    out = run_ui(tmp_path, STUDIO_WORLD + r"""
      const said=[];
      rms.remotion=false;
      let ex=await openVariants();
      door().click();await env.advance(50);
      said.push([say(),door().getAttribute('aria-disabled'),!!dialog()]);
      ex.close({reason:'user'});await env.advance(50);
      rms.remotion=true;rms.studioStatus=503;
      await ex.open({presentation_id:PID,fullscreen:false});await env.advance(600);
      door().click();await env.advance(50);
      said.push([say(),door().getAttribute('aria-disabled'),!!dialog()]);
      ex.close({reason:'user'});await env.advance(50);
      rms.studioStatus=200;rms.cap={status:'repair_needed'};
      await ex.open({presentation_id:PID,fullscreen:false});await env.advance(600);
      door().click();await env.advance(50);
      said.push([say(),door().getAttribute('aria-disabled'),!!dialog()]);
      return {said,opens:rms.opens.length};
    """)
    words = ["pas une scène Remotion", "pas de Remotion Studio", "pas prêt (à réparer)"]
    for (text, disabled, dialog), expected in zip(out["said"], words):
        assert expected in text and disabled == "true" and dialog is False, (text, expected)
    assert out["opens"] == 0


def test_a_long_start_offers_the_link_coming_back_rereads_and_says_unpublished_files(tmp_path):
    out = run_ui(tmp_path, STUDIO_WORLD + r"""
      const ex=await openVariants();
      rms.openDelay=40000;
      door().click();await env.advance(50);go().click();
      win.navigator.userActivation.isActive=false;      // 40 s later the browser no longer counts the click
      await env.advance(12000);
      const waiting={text:say(),spin:status().getAttribute('data-spin'),busy:door().getAttribute('aria-disabled')};
      await env.advance(30000);
      const ready={text:say(),link:!q('.jvx-rms-link').hidden&&q('.jvx-rms-link').textContent,href:q('.jvx-rms-link').getAttribute('href'),
        target:q('.jvx-rms-link').getAttribute('target'),rel:q('.jvx-rms-link').getAttribute('rel'),tabs:tabs.length};
      /* the user edits in Remotion Studio, then comes back to Jarvis's tab */
      rms.studio=Object.assign({},rms.studio,{viewers:1,work_copy:{modified_files:['src/Scene.tsx'],edits_saved:0}});
      const reads=env.requests.filter(r=>r.url.endsWith('/studio')).length;
      win.dispatchEvent(new (require(process.env.JARVIS_EXPLORER_DOM).FakeEvent)('focus',{bubbles:false}));await env.advance(100);
      return {waiting,ready,back:say(),tone:status().getAttribute('data-tone'),reread:env.requests.filter(r=>r.url.endsWith('/studio')).length>reads,
        selected:ex.state().selected,scene:ex.state().preview.scene};
    """)
    assert out["waiting"]["spin"] == "true" and "Remotion Studio démarre… 12 s (2 min au plus)." == out["waiting"]["text"]
    assert out["waiting"]["busy"] == "true"
    r = out["ready"]
    assert "n’ouvre un onglet qu’après un clic" in r["text"] and r["link"] == "Ouvrir l’onglet Remotion Studio" and r["tabs"] == 0
    assert (r["href"], r["target"], r["rel"]) == ("http://127.0.0.1:41000/", "_blank", "noopener noreferrer")
    assert out["reread"] is True and out["tone"] == "warn"
    assert "1 fichier modifié dans Remotion Studio, pas encore publié : la variante n’a pas changé" in out["back"]
    assert out["scene"] == "pss_000000000001"


def test_a_run_hides_the_door_and_remotion_studio_is_never_drawn_inside_variants(tmp_path):
    out = run_ui(tmp_path, STUDIO_WORLD + r"""
      const ex=await openVariants();
      door().click();await env.advance(50);go().click();await env.advance(200);
      await showView(runView());
      const inRun={button:door().hidden,status:status().hidden};
      return {inRun,stillOne:qa('[data-act="remotion_studio"]').length,iframes:qa('iframe').filter(f=>String(f.src||'').includes('41000')).length};
    """)
    assert out["inRun"] == {"button": True, "status": True}, "during a run Remotion Studio waits for « Arrêter »"
    assert out["stillOne"] == 1 and out["iframes"] == 0, "one door, and Remotion Studio is never drawn inside Variants"


def test_the_door_pauses_the_video_after_the_confirmation_and_only_then(tmp_path):
    out = run_ui(tmp_path, STUDIO_WORLD + r"""
      const D=require(""" + DOOR_JS + r""");
      seed(3);const ex=make({player:fakePlayer});await ex.open({presentation_id:PID,fullscreen:false});await env.advance(600);
      const calls=[];
      const real=ex.ui();
      const scene={id:'pss_000000000001',title:'Ouverture',prefab:{id:'lab.dial',version:1}};
      let dlg=null;
      const d=D.createRemotionDoor({doc,win,el:(t,c,x)=>{const n=doc.createElement(t);if(c)n.className=c;if(x!=null)n.textContent=x;return n},
        attrs:(n,m)=>{for(const k of Object.keys(m))n.setAttribute(k,String(m[k]));return n},clear:n=>{while(n.firstChild)n.removeChild(n.firstChild)},
        button:(l,c,f,x)=>{const b=doc.createElement('button');b.textContent=l;if(f)b.addEventListener('click',f);for(const k of Object.keys(x&&x.attrs||{}))b.setAttribute(k,x.attrs[k]);return b},
        dialogButton:(l,f)=>{const b=doc.createElement('button');b.textContent=l;b.addEventListener('click',f);return b},
        later:timers.setTimeout,cancelLater:timers.clearTimeout,now:timers.now,log:(k)=>calls.push('log:'+k),announce:()=>{},fetch:env.fetch,
        dialog:{open:spec=>{const box=doc.createElement('div');doc.body.appendChild(box);dlg={box,spec};return dlg},close:()=>{const s=dlg&&dlg.spec;if(dlg)dlg.box.remove();dlg=null;if(s&&s.onClose)s.onClose()},current:()=>dlg},
        scene:()=>({presentationId:PID,variantId:vid(1),variantNumber:1,scene,index:0,scenes:[scene]}),running:()=>false,isOpen:()=>true,
        pause:()=>calls.push('pause:'+rms.opens.length)});
      d.buildButton();d.buildStatus();d.start();await env.advance(100);
      const pending=d.request({via:'test'});await env.advance(50);
      const beforeConfirm=calls.filter(c=>c.startsWith('pause')).length;
      dlg.box.querySelector('[data-act="remotion_studio_confirm"]').click();
      const result=await pending;
      return {beforeConfirm,calls:calls.filter(c=>c.startsWith('pause')),result};
    """)
    assert out["beforeConfirm"] == 0, "nothing pauses while the user decides"
    assert out["calls"] == ["pause:0"], "the video is paused once, before Core's open"
    assert out["result"]["state"] == "ready"


def test_the_rail_offers_remotion_studio_which_opens_variants_then_the_door(tmp_path):
    out = run_ui(tmp_path, STUDIO_WORLD + r"""
      const R=require(""" + RAIL_JS + r""");
      const row={presentation_id:PID,title:'Atelier',hidden:false,archived:false,work:{state:'done'}};
      const idle=R.menuModel(row,{playing:false,playingThis:false}).filter(i=>i!=='-').map(i=>[i.act,i.label,i.note||null]);
      const busy=R.menuModel(row,{playing:true,playingThis:true}).find(i=>i.act==='studio');
      seed(3);
      const ex=make({player:fakePlayer});
      await ex.open({presentation_id:PID,fullscreen:false});
      const done=ex.remotionStudio.open({via:'rail'});      // what the rail calls once Variants has opened (the preview is not ready yet)
      await env.advance(800);
      const dlg=!!dialog();
      go().click();await env.advance(300);
      const result=await done;
      return {idle,busy:busy.note,dlg,result,opens:rms.opens.length};
    """)
    acts = [a for a, _l, _n in out["idle"]]
    assert acts[:2] == ["open", "studio"] and ("studio", "Remotion Studio…", None) in [tuple(x) for x in out["idle"]]
    assert "Remotion Studio s’ouvre à son arrêt" in out["busy"]
    assert out["dlg"] is True and out["result"]["state"] == "ready" and out["opens"] == 1


def test_an_html_deck_never_asks_core_about_remotion_studio(tmp_path):
    out = run_ui(tmp_path, STUDIO_WORLD + r"""
      rms.remotion=false;
      const ex=await openVariants();
      win.dispatchEvent(new (require(process.env.JARVIS_EXPLORER_DOM).FakeEvent)('focus',{bubbles:false}));await env.advance(16000);
      return {studioReads:env.requests.filter(r=>r.url.startsWith('/api/local-capabilities/remotion')).length,
        libraryReads:env.requests.filter(r=>r.url.startsWith('/api/prefabs/')).length};
    """)
    assert out == {"studioReads": 0, "libraryReads": 1}, "no Remotion Studio read (nor a 503 in the console) for a deck without Remotion"


def test_a_click_on_this_scene_opens_another_noopener_tab_each_time_and_says_so(tmp_path):
    """Slice 11 QA polish: `noopener` (kept for security) means the browser never hands back a tab it opened, so each click on the door of a
    scene already open opens ANOTHER tab, without a second confirmation; the button's title and the link say « un autre onglet »."""

    out = run_ui(tmp_path, STUDIO_WORLD + r"""
      const ex=await openVariants();
      door().click();await env.advance(50);go().click();await env.advance(300);
      const first=tabs.length;
      rms.studio=Object.assign({},rms.studio,{viewers:1});
      door().click();await env.advance(100);
      door().click();await env.advance(100);
      return {first,tabs,dialogs:!!dialog(),opens:rms.opens.length,title:door().getAttribute('title'),
        link:q('.jvx-rms-link').textContent};
    """)
    assert out["first"] == 1 and out["opens"] == 1, "one confirmed open"
    assert out["tabs"][1:] == [["http://127.0.0.1:41000/", "jarvis-remotion-studio", "noopener,noreferrer"]] * 2, "noopener kept, a new tab per click"
    assert out["dialogs"] is False, "no second confirmation"
    assert "Ouvrir un autre onglet" in out["title"]


def test_a_product_edition_without_developer_mode_says_the_engine_sentence_never_the_mcp_dialog():
    """presentation-edition-v1 Slice 09 (I-006, QA m6): with the developer surfaces hidden the refusal is the product's sentence."""

    base = {"scene": SCENE, "scenes": [{"id": SCENE["id"], "title": "Ouverture", "prefab": PIN}], "detail": {"state": "ready", "remotion": True},
            "studio": {"status": "stopped", "pin": None}, "capability": {"status": "not_installed"}, "readError": None, "busy": None,
            "actionError": None, "run": False, "needsClick": False, "explain": None, "now": 100_000}
    script = ("globalThis.JarvisProductEdition={developerSurfacesShown:()=>false};"
              f"const D=require({DOOR_JS});process.stdout.write(JSON.stringify(D.doorModel({json.dumps(base)})));")
    blocked = node(script)["button"]["blocked"]
    assert blocked.startswith("Le moteur vidéo de Jarvis n’est pas prêt (non installé) : demandez à Jarvis de l’installer ou de le réparer")
    assert "MCP" not in blocked and "Plugins externes" not in blocked
