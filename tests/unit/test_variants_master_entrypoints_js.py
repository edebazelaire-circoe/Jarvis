"""Variants entrypoints of the whole video, by node (handoff jarvis-remotion-master-project-studio-export, Slice 08; contract
`docs/remotion-master-project.md` § 3, § 9, § 13, `docs/presentation-studio.md` › *Remotion Studio from Variants*).

1. Pure: the § 3 sentences are the Python ones word for word (placeholders included); the door model in master mode (button, master line
   naming the presentation, the variant and the scene count, the secondary scene door, Remotion Studio on this / an older / another whole
   video, unpublished whole-video edits never publishable); the whole-video confirmation (scene count, reinforced warning); the export model.
2. The explorer on the fake DOM with the real modules: « Remotion Studio » opens ONE confirmation naming the whole video, `Échap` launches
   nothing, confirming sends the master body (`kind`, ids, `project_key`, the project acknowledgment); a stale key re-asks with the new
   scene count; edits of a scene workspace are set aside only after the confirmation says so; an incompatible variant keeps the scene door
   and says the sentence; the secondary door opens the scene alone; a new revision re-reads the readiness; « Exporter la vidéo » freezes the
   variant and sends `scope: "master"`, follows the job, cancels, links the Artefact, and says a refusal; the rail opens the same dialog.
3. Board Artifacts: an MP4 of a copy whose whole video is ready posts `settings: {scope: "master"}`; otherwise today's body.

Real Chrome: `test_variants_master_entrypoints_browser.py`.
"""

from __future__ import annotations

import json

from jarvis.domain.remotion_master_project import MasterReason
from jarvis.domain.remotion_master_sentences import REASON_SENTENCES, UNKNOWN_REASON_SENTENCE, reason_sentence
from tests.fakes.explorer_js import RUNTIME, run_ui
from tests.unit.test_variants_remotion_studio_js import STUDIO_WORLD, node
from tests.unit.test_workspace_manager_js import _text, run_node
from tests.unit.test_workspace_presentations_js import EXPORT_SEED, RENDER_JOBS, SEED

DOOR_JS = json.dumps(str(RUNTIME / "control_center_presentation_studio_explorer_remotion.js"))
CORE_JS = json.dumps(str(RUNTIME / "control_center_remotion_studio.js"))
EXPORT_JS = json.dumps(str(RUNTIME / "control_center_presentation_studio_explorer_export.js"))
RAIL_JS = json.dumps(str(RUNTIME / "control_center_presentation_rail.js"))
KEY = "mpk_" + "a" * 24
KEY2 = "mpk_" + "b" * 24


def plan(n: int = 3, key: str = KEY, frames: int = 135) -> dict:
    return {"presentation_id": "pst_1", "variant_id": "psv_1", "variant_revision": 1, "generator_version": 1, "status": "ready",
            "project_key": key, "composition": {"id": "JarvisPresentation", "width": 1280, "height": 720, "fps": 30, "duration_in_frames": frames},
            "scenes": [{"scene_id": f"pss_{i + 1:012d}", "prefab_id": "lab.dial", "version": 1, "from_frame": 45 * i,
                        "duration_in_frames": 45} for i in range(n)], "public_assets": [], "totals": {"files": 9, "bytes": 900}}


INCOMPATIBLE = {"presentation_id": "pst_1", "variant_id": "psv_1", "variant_revision": 1, "generator_version": 1, "status": "incompatible",
                "reason": "master_fps_mismatch", "detail": "scene 2 (pss_000000000002) declares 25 fps", "scene_ids": ["pss_000000000002"]}
PIN = {"id": "lab.dial", "version": 1}
SCENE = {"id": "pss_000000000001", "title": "Ouverture", "number": 1, "of": 3, "prefab": PIN}


def model(**inputs) -> dict:
    base = {"scene": SCENE, "scenes": [{"id": SCENE["id"], "title": "Ouverture", "prefab": PIN}], "detail": {"state": "ready", "remotion": True},
            "studio": {"status": "stopped", "pin": None}, "capability": {"status": "ready"}, "readError": None, "busy": None, "actionError": None,
            "run": False, "needsClick": False, "explain": None, "now": 100_000, "master": {"state": "ready", "plan": plan()},
            "presentationId": "pst_1", "variantId": "psv_1", "variantNumber": 2, "presentationTitle": "Atelier"}
    base.update(inputs)
    return node(f"const D=require({DOOR_JS});process.stdout.write(JSON.stringify(D.doorModel({json.dumps(base)})));")


# ------------------------------------------------------------------ 1. pure

def test_the_page_says_the_section_3_sentences_of_python_word_for_word():
    vectors = [(r.value, "") for r in MasterReason] + [
        ("master_source_unavailable", "scene 4 (pss_000000000004): digest mismatch"), ("master_source_unavailable", "no position here"),
        ("master_public_asset_collision", "public/intro.png differs between pss_1 and pss_2"), ("master_public_asset_collision", "odd"),
        ("master_unheard_of", "x"), (None, None)]
    out = node(f"const C=require({CORE_JS});process.stdout.write(JSON.stringify({{table:C.MASTER_REASONS,unknown:C.MASTER_UNKNOWN_REASON,"
               f"said:{json.dumps(vectors)}.map(([r,d])=>C.masterReasonSentence(r,d))}}));")
    assert out["table"] == {r.value: s for r, s in REASON_SENTENCES.items()} and out["unknown"] == UNKNOWN_REASON_SENTENCE
    assert out["said"] == [reason_sentence(r, d) for r, d in vectors]
    assert "(scène 4)" in out["said"][-6] and "« public/intro.png »" in out["said"][-4]


def test_a_ready_whole_video_makes_remotion_studio_the_door_of_the_variant_and_keeps_the_scene_as_secondary():
    m = model()
    assert m["masterMode"] is True and m["button"]["label"] == "Remotion Studio" and m["button"]["ariaLabel"] == "Remotion Studio, vidéo entière"
    assert "vidéo entière (3 scènes)" in m["button"]["title"] and "scène à l’écran" not in m["button"]["title"]
    assert m["master"] == {"tone": "", "scene": True, "text": "Vidéo entière : « Atelier », variante 2, 3 scènes (4,5 s)."}
    assert m["sceneDoor"]["label"] == "Cette scène seule dans Remotion Studio" and m["sceneDoor"]["blocked"] is None
    assert m["status"] is None, "nothing else to say while Remotion Studio is stopped"
    blocked = model(run=True)
    assert blocked["button"]["blocked"] and blocked["sceneDoor"]["blocked"] == blocked["button"]["blocked"], "a run blocks both doors"


def test_an_incompatible_or_unreadable_whole_video_keeps_the_scene_door_and_says_why():
    m = model(master={"state": "incompatible", "plan": INCOMPATIBLE})
    assert m["masterMode"] is False and m["sceneDoor"] is None and m["button"]["ariaLabel"] == "Remotion Studio"
    assert "scène à l’écran" in m["button"]["title"]
    assert m["master"]["text"] == REASON_SENTENCES[MasterReason.FPS_MISMATCH] + " « Remotion Studio » ouvre donc la scène à l’écran."
    assert m["master"]["text"].count("disponible") == 1, "one sentence per state: « indisponible » is never said twice"
    assert m["master"]["scene"] is False
    err = model(master={"state": "error", "plan": None, "error": {"code": "core_unreachable"}})
    assert err["masterMode"] is False and "n’a pas pu être lue (core_unreachable)" in err["master"]["text"] and err["master"]["tone"] == "warn"
    assert model(master=None)["master"] is None and model(master=None)["masterMode"] is False, "not read yet: today's scene door"


MASTER_STUDIO = {"status": "ready", "url": "http://127.0.0.1:41000/", "viewers": 1, "pin": None,
                 "target": {"kind": "variant_master", "presentation_id": "pst_1", "variant_id": "psv_1", "project_key": KEY, "scene_count": 3,
                            "stale": False}, "work_copy": {"modified_files": [], "unpublished": 0, "base": None}}


def test_remotion_studio_on_this_an_older_or_another_whole_video_is_said_never_as_one_scene():
    here = model(studio=MASTER_STUDIO)
    assert here["masterRelation"] == "here" and here["button"]["state"] == "here"
    assert here["button"]["ariaLabel"] == "Remotion Studio, ouvert sur la vidéo entière"
    assert here["status"]["text"] == "Remotion Studio est ouvert sur la vidéo entière (3 scènes), dans un autre onglet."
    assert "scène" not in here["status"]["text"].split("(")[0] and here["status"]["link"]["url"] == MASTER_STUDIO["url"]
    stale = model(studio={**MASTER_STUDIO, "target": {**MASTER_STUDIO["target"], "stale": True}})
    assert stale["masterRelation"] == "stale" and stale["status"]["refresh"] is True and stale["status"]["tone"] == "warn"
    assert "La vidéo a changé depuis son ouverture dans Remotion Studio (maintenant 3 scènes)" in stale["status"]["text"]
    older = model(studio={**MASTER_STUDIO, "target": {**MASTER_STUDIO["target"], "project_key": KEY2, "stale": None}})
    assert older["masterRelation"] == "stale", "the page's own read counts when Core's live key is unknown"
    other = model(studio={**MASTER_STUDIO, "target": {**MASTER_STUDIO["target"], "variant_id": "psv_9"}})
    assert other["masterRelation"] == "other" and "d’une autre variante" in other["status"]["text"]
    scene_open = model(studio={"status": "ready", "url": "http://x/", "viewers": 1, "pin": {"prefab_id": "lab.dial", "version": 1}, "work_copy": {}})
    assert scene_open["relation"] == "here" and scene_open["button"]["state"] == "idle", "the primary door means the whole video"
    assert "ouvert sur cette scène seule (source v1)" in scene_open["status"]["text"] and "y affiche la vidéo entière" in scene_open["status"]["text"]


def test_edits_of_a_whole_video_workspace_are_never_publishable_and_say_the_way_out():
    edited = {**MASTER_STUDIO, "work_copy": {"modified_files": ["src/master/Presentation.tsx", "public/a.png"], "unpublished": 2, "base": None}}
    m = model(studio=edited)
    assert m["publish"]["offered"] is False and m["status"]["publish"] is False and m["status"]["tone"] == "warn"
    assert "2 fichiers modifiés dans Remotion Studio (vidéo entière), pas publiés : la vidéo entière ne se publie pas dans la variante" in m["status"]["text"]
    assert "« Cette scène seule dans Remotion Studio »" in m["status"]["text"]
    stopped = model(studio={**edited, "status": "stopped", "url": None})
    assert stopped["status"]["publish"] is False and "(vidéo entière), pas publiés" in stopped["status"]["text"]
    plain = model(master=None, studio=edited)
    assert plain["status"]["publish"] is False and "Publier" not in plain["status"]["text"], "even before the readiness is read"


def test_the_whole_video_confirmation_names_the_scene_count_and_reinforces_for_a_version_not_written_by_the_user():
    script = (f"const C=require({CORE_JS});const p={{label:'« Atelier », variante 2 · 3 scènes',sceneCount:3,versions:'1. « A » v1'}};"
              "const user={created_by:{actor:'user'}},brain={created_by:{actor:'brain'}};"
              "process.stdout.write(JSON.stringify([C.masterConfirmSpec(p,[user,user,user],'open'),C.masterConfirmSpec(p,[user,brain,null],'refresh'),"
              "C.masterConfirmSpec({...p,sceneCount:1},[user],'switch')]));")
    own, foreign, one = node(script)
    lines = dict(own["lines"])
    assert own["title"] == "Ouvrir la vidéo entière hors du bac à sable ?" and own["danger"] is False
    assert lines["Sans bac à sable : "].startswith("3 scènes vont tourner hors du bac à sable, dans Remotion Studio")
    assert lines["Vidéo entière : "] == "« Atelier », variante 2 · 3 scènes" and own["confirmLabel"] == "Ouvrir la vidéo entière dans Remotion Studio"
    assert "Attention : " not in lines and lines["Provenance : "] == "toutes ces versions ont été écrites par vous"
    flines = dict(foreign["lines"])
    assert foreign["danger"] is True and foreign["title"] == "Ouvrir une vidéo dont vous n’avez pas écrit toutes les scènes ?"
    assert "2 sur 3" in flines["Provenance : "] and "Attention : " in flines
    assert foreign["confirmLabel"] == "Actualiser la vidéo entière dans Remotion Studio"
    assert dict(one["lines"])["Sans bac à sable : "].startswith("1 scène va tourner") and one["confirmLabel"] == "Afficher la vidéo entière dans Remotion Studio"


def export_model(**inputs) -> dict:
    base = {"master": {"state": "ready", "plan": plan()}, "run": False, "x": None, "explain": None, "now": 100_000}
    base.update(inputs)
    return node(f"const E=require({EXPORT_JS});process.stdout.write(JSON.stringify(E.exportModel({json.dumps(base)})));")


def test_the_export_model_says_why_it_waits_runs_or_refuses():
    ready = export_model()
    assert ready["button"]["label"] == "Exporter la vidéo" and ready["button"]["blocked"] is None
    assert "vidéo entière (3 scènes, 4,5 s) en MP4" in ready["button"]["title"]
    no = export_model(master={"state": "incompatible", "plan": INCOMPATIBLE})["button"]
    assert no["blocked"] == REASON_SENTENCES[MasterReason.FPS_MISMATCH] + " Exportez plutôt les scènes une à une depuis les Artefacts du Board."
    assert no["blocked"].lower().count("chaque scène reste") == 1 and no["blocked"].count("disponible") == 1
    assert export_model(master={"state": "loading", "plan": None})["button"]["blocked"] == "Lecture de la vidéo entière…"
    err = export_model(master={"state": "error", "plan": None, "error": {"code": "network"}})["button"]
    assert err["retryRead"] is True and "(network)" in err["blocked"]
    job = {"job_id": "rj_0123456789ab", "state": "running", "phase": "rendering", "frames_done": 30, "frames_total": 135, "percent": 22,
           "timeout_s": 435, "can_cancel": True, "scene_count": 3}
    run = export_model(x={"status": "running", "job": job, "started": 88_000, "pollErrors": 1})
    assert run["button"]["state"] == "busy" and run["status"]["spin"] is True and run["status"]["cancel"] is True
    assert run["status"]["text"] == ("Export de la vidéo entière (3 scènes) — Rendu des images · 30/135 images (22 %) · 12 s · délai 7 min au plus"
                                     " · lecture de l’état en échec (1/3)")
    done = export_model(x={"status": "done", "job": {**job, "state": "complete", "artifact_id": "jart_x", "size_bytes": 3_500_000}, "started": 1})
    assert done["status"]["tone"] == "ok" and done["status"]["text"] == "Vidéo entière exportée : Artefact jart_x (3,3 Mo)."
    assert done["status"]["link"] == {"url": "/api/artifacts/jart_x/payload", "label": "Ouvrir la vidéo"}
    failed = export_model(x={"status": "done", "job": {**job, "state": "failed", "error_code": "presentation_render_master_scene_failed",
                                                      "error_detail": "scene pss_2 (2) threw"}, "started": 1})
    assert failed["status"]["tone"] == "danger" and failed["status"]["retry"], "a failed render job is transient: « Réessayer »"
    assert failed["status"]["text"] == "Export de la vidéo entière échoué : aucun fichier n’a été gardé."
    assert failed["status"]["code"] == "presentation_render_master_scene_failed · scene pss_2 (2) threw", "Core's code and detail in small print"
    one = export_model(x={"status": "running", "job": {**job, "scene_count": 1}, "started": 88_000})
    assert one["status"]["text"].startswith("Export de la vidéo entière (1 scène) — "), "« 1 scène », never « 1 scènes »"
    assert export_model(master={"state": "ready", "plan": plan(1)})["button"]["title"].startswith("Rendre la vidéo entière (1 scène, ")


def describe(error: dict) -> dict:
    return node(f"const E=require({EXPORT_JS});process.stdout.write(JSON.stringify(E.describeExportError({json.dumps(error)})));")


def test_export_refusals_are_french_sentences_with_the_code_and_retry_only_when_it_can_work():
    no_engine = "L’export vidéo n’est pas disponible sur ce poste (moteur Remotion absent)."
    for code in ("presentation_render_unavailable", "presentation_render_runtime_unavailable", "remotion_studio_unavailable"):
        assert describe({"code": code, "status": 503, "message": "the Remotion capability is missing"}) == {
            "code": code, "text": no_engine, "detail": "", "retry": False}, code
    live = describe({"code": "live_ref_not_authorised", "status": 409, "message": "this Board is not authorised"})
    assert live["text"] == "Les scènes lisent en direct des fichiers d’un Board : lancez l’export depuis les Artefacts de ce Board."
    assert live["retry"] is False and "authorised" not in live["text"]
    inc = describe({"code": "presentation_render_master_incompatible", "status": 409, "message": "not ready",
                    "info": {"reason": "master_too_long", "detail": "9001 frames"}})
    assert inc == {"code": "presentation_render_master_incompatible", "text": REASON_SENTENCES[MasterReason.TOO_LONG], "detail": "", "retry": False}
    stale = describe({"code": "presentation_studio_stale_revision", "status": 409, "message": "stale"})
    assert stale["retry"] is True and stale["text"].startswith("La variante a changé depuis sa lecture")
    for transient in ({"code": "network", "status": 0, "message": "Failed to fetch"}, {"code": "core_unreachable", "status": 503, "message": "down"},
                      {"code": "http_502", "status": 502, "message": "HTTP 502"}):
        d = describe(transient)
        assert d["retry"] is True and d["text"] == "La demande d’export n’a pas abouti : Core est injoignable ou en erreur." and d["detail"], transient
    assert describe({"code": "timeout", "status": 0, "message": "aucune réponse en 65 s"})["retry"] is True
    unknown = describe({"code": "presentation_render_snapshot_invalid", "status": 400, "message": "the snapshot package is invalid"})
    assert unknown == {"code": "presentation_render_snapshot_invalid", "text": "Core a refusé l’export de la vidéo entière.",
                       "detail": "the snapshot package is invalid", "retry": False}, "an unknown refusal: no « Réessayer », Core's words in small print"
    err = export_model(x={"status": "error", "error": live, "started": 1})["status"]
    assert err["text"] == live["text"] and err["code"] == "live_ref_not_authorised" and err["retry"] is False
    err = export_model(x={"status": "error", "error": unknown, "started": 1})["status"]
    assert err["code"] == "presentation_render_snapshot_invalid · the snapshot package is invalid" and err["retry"] is False


def test_the_scene_door_is_quieter_than_the_primary_button_and_the_dialog_body_scrolls():
    css = node(f"process.stdout.write(JSON.stringify(require({DOOR_JS}).CSS));")
    rows = css.splitlines()
    rest = next(line for line in rows if ".jvx-rms .jvx-rms-scene{" in line)
    assert "color:var(--jvx-mute)" in rest and "font-weight:400" in rest and "text-decoration:none" in rest
    assert "jvx-accent" not in rest and "font-weight:600" not in rest, "no accent, no bold at rest: the primary stays primary"
    hover = next(line for line in rows if ".jvx-rms-scene:focus-visible" in line)
    assert ".jvx-rms-scene:hover" in hover and "color:var(--jvx-accent)" in hover and "text-decoration:underline" in hover
    box = next(line for line in rows if 'jvx-dialog[data-kind="remotion_studio"]{' in line)
    assert "flex-direction:column" in box and "overflow:hidden" in box
    body = next(line for line in rows if ".jvx-confirm-body{" in line)
    assert "overflow:auto" in body and "min-height:0" in body


# ------------------------------------------------------------------ 2. the explorer on the fake DOM

MASTER_WORLD = STUDIO_WORLD + r"""
const mp={plan:null,reads:0,status:200,opens:[],jobs:[],cancel:0,jobReplies:[],postReply:null};
const KEY='mpk_'+'a'.repeat(24),KEY2='mpk_'+'b'.repeat(24);
const readyPlan=(key,n)=>({presentation_id:PID,variant_id:vid(1),variant_revision:1,generator_version:1,status:'ready',project_key:key||KEY,
  composition:{id:'JarvisPresentation',width:1280,height:720,fps:30,duration_in_frames:45*(n||3)},
  scenes:Array.from({length:n||3},(_,i)=>({scene_id:'pss_'+String(i+1).padStart(12,'0'),prefab_id:'lab.dial',version:1,from_frame:45*i,duration_in_frames:45})),
  public_assets:[],totals:{files:9,bytes:900}});
mp.plan=readyPlan();
env.route(u=>u.includes('/master-project'),()=>{mp.reads++;return mp.status===200?{status:200,body:{master:mp.plan}}
  :{status:mp.status,body:{error:{code:'presentation_studio_unknown_variant',message:'gone'}}}});
const masterStudio=(body,extra)=>Object.assign({status:'ready',pin:null,url:'http://127.0.0.1:41000/',viewers:0,
  target:{kind:'variant_master',presentation_id:body.presentation_id,variant_id:body.variant_id,project_key:body.project_key,scene_count:3,stale:false},
  work_copy:{modified_files:[],unpublished:0,base:null}},extra||{});
rms.openReply=body=>{
  if(body.kind!=='variant_master'){rms.studio={status:'ready',pin:{prefab_id:body.prefab_id,version:body.version},url:'http://127.0.0.1:41000/',viewers:0,work_copy:{}};
    return {status:200,body:{studio:rms.studio}}}
  if(mp.openReply){const r=mp.openReply(body);if(r)return r}
  rms.studio=masterStudio(body);return {status:200,body:{studio:rms.studio}};
};
const JOBS='/api/local-capabilities/remotion/render/jobs';
const job=(over)=>Object.assign({job_id:'rj_0123456789ab',artifact_id:'jart_'+'e'.repeat(32),snapshot_id:'jart_ps_x',state:'queued',phase:'queued',format:'mp4',
  frames_done:0,frames_total:135,percent:0,elapsed_s:0,timeout_s:435,queue_position:null,can_cancel:true,error_code:null,error_detail:null,scope:'master',
  project_key:KEY,scene_count:3,size_bytes:null},over||{});
env.route('/api/local-capabilities/remotion/render',(url,rec,body)=>{
  if(url===JOBS&&rec.method==='POST'){mp.jobs.push(body);return mp.postReply?mp.postReply(body):{status:202,body:{job:job()}}}
  if(url===JOBS&&rec.method==='GET')return {status:200,body:{jobs:mp.listed||[]}};
  if(url.endsWith('/cancel')){mp.cancel++;return {status:200,body:{job:job({state:'cancelled',phase:'cancelled',can_cancel:false})}}}
  if(url.startsWith(JOBS+'/'))return mp.jobReplies.length?mp.jobReplies.shift():{status:200,body:{job:job({state:'running',phase:'rendering',frames_done:40,percent:29})}};
  return {status:404,body:{error:{code:'no_route',message:url}}};
});
const masterLine=()=>q('.jvx-rms-master-text').textContent;
const sceneDoor=()=>q('[data-act="remotion_studio_scene"]');
const vx=()=>q('[data-act="video_export"]');
const vxText=()=>q('.jvx-vx-text').textContent;
const lines=()=>dialog()?qa('li',dialog()).map(li=>li.textContent):[];
"""


def test_remotion_studio_opens_one_whole_video_confirmation_then_sends_the_master_body(tmp_path):
    out = run_ui(tmp_path, MASTER_WORLD + r"""
      const ex=await openVariants();
      const before={line:masterLine(),scene:!sceneDoor().hidden,target:door().getAttribute('data-target'),aria:door().getAttribute('aria-label'),
        exportShown:!vx().hidden,exportDisabled:vx().getAttribute('aria-disabled'),reads:mp.reads};
      door().click();await env.advance(80);
      const seen={target:dialog()&&dialog().getAttribute('data-target'),title:q('h2',dialog()).textContent,lines:lines(),goLabel:go().textContent,
        focus:doc.activeElement===go(),opens:rms.opens.length};
      env.key(doc.activeElement,'Escape');await env.advance(50);
      const escaped={dialog:!!dialog(),focusBack:doc.activeElement===door(),opens:rms.opens.length};
      door().click();await env.advance(80);go().click();await env.advance(300);
      return {before,seen,escaped,opens:rms.opens,tabs,status:say(),button:[door().getAttribute('data-state'),door().getAttribute('aria-label')],
        state:ex.state(),logs:env.logs.filter(l=>l[1].includes('remotion_studio_open_requested')).map(l=>l[1])};
    """)
    b = out["before"]
    assert b["line"] == "Vidéo entière : « Atelier du cadran », variante 1, 3 scènes (4,5 s)." and b["scene"] is True
    assert b["target"] == "master" and b["aria"] == "Remotion Studio, vidéo entière" and b["reads"] == 1, "one read per revision"
    assert b["exportShown"] is True and b["exportDisabled"] == "false"
    s = out["seen"]
    assert s["target"] == "master" and s["title"] == "Ouvrir la vidéo entière hors du bac à sable ?" and s["focus"] is True and s["opens"] == 0
    text = " ".join(s["lines"])
    assert "« Atelier du cadran », variante 1 · 3 scènes · 4,5 s (1280×720, 30 i/s)" in text
    assert "3 scènes vont tourner hors du bac à sable, dans Remotion Studio" in text and "1. « Scène 1 de 1 » v1" in text
    assert s["goLabel"] == "Ouvrir la vidéo entière dans Remotion Studio"
    assert out["escaped"] == {"dialog": False, "focusBack": True, "opens": 0}
    assert out["opens"] == [{"kind": "variant_master", "presentation_id": "pst_" + "0" * 31 + "1", "variant_id": "psv_" + "0" * 31 + "1",
                             "project_key": KEY, "acknowledge_unsandboxed_project": True}], "the master body, acknowledged, never the scene ack"
    assert out["tabs"] == [["http://127.0.0.1:41000/", "jarvis-remotion-studio", "noopener,noreferrer"]]
    assert "ouvert sur la vidéo entière (3 scènes)" in out["status"] and "sur la scène" not in out["status"]
    assert out["button"] == ["here", "Remotion Studio, ouvert sur la vidéo entière"]
    assert out["state"]["preview"]["scene"] == "pss_000000000001" and "target" in out["logs"][0] and "master" in out["logs"][0]


def test_a_stale_key_re_asks_with_the_new_scene_count_and_sends_the_new_key(tmp_path):
    out = run_ui(tmp_path, MASTER_WORLD + r"""
      const ex=await openVariants();
      let first=true;
      mp.openReply=body=>{if(first){first=false;mp.plan=readyPlan(KEY2,4);
        return {status:409,body:{error:{code:'remotion_studio_master_stale',message:'changed',project_key:KEY2,variant_revision:2,scene_count:4}}}}return null};
      door().click();await env.advance(80);go().click();await env.advance(300);
      const again={dialog:!!dialog(),note:dialog()&&(q('[data-line="stale"]',dialog())||{}).textContent,text:lines().join(' '),opens:rms.opens.length};
      go().click();await env.advance(300);
      return {again,keys:rms.opens.map(b=>b.project_key),status:say(),reads:mp.reads};
    """)
    a = out["again"]
    assert a["dialog"] is True and a["opens"] == 1
    assert a["note"] == "La variante a changé depuis votre confirmation : la vidéo entière compte maintenant 4 scènes. Confirmez de nouveau."
    assert "4 scènes vont tourner hors du bac à sable" in a["text"]
    assert out["keys"] == [KEY, KEY2] and out["reads"] == 2 and "ouvert sur la vidéo entière" in out["status"]


def test_unpublished_scene_edits_are_set_aside_only_after_the_confirmation_says_so(tmp_path):
    out = run_ui(tmp_path, MASTER_WORLD + r"""
      rms.studio={status:'ready',pin:{prefab_id:'lab.dial',version:1},url:'http://127.0.0.1:41000/',viewers:1,
        work_copy:{modified_files:['src/Scene.tsx'],unpublished:1,base:{prefab_id:'lab.dial',version:1},digest:'d'.repeat(64)}};
      const ex=await openVariants();
      const shown={publish:!q('[data-act="remotion_studio_publish"]').hidden,text:say()};
      door().click();await env.advance(80);
      const discard=(q('[data-line="discard"]',dialog())||{}).textContent;
      go().click();await env.advance(300);
      return {shown,discard,body:rms.opens[0]};
    """)
    assert out["shown"]["publish"] is True, "the scene's own publish stays offered for a scene target"
    assert out["discard"] == "Fichiers non publiés : 1 fichier modifié dans Remotion Studio (sur v1) sera mis de côté (studio-edits), pas publié."
    assert out["body"]["discard_unpublished"] is True and out["body"]["kind"] == "variant_master"


def test_whole_video_edits_hide_publish_and_the_scene_door_sets_them_aside_after_saying_so(tmp_path):
    out = run_ui(tmp_path, MASTER_WORLD + r"""
      rms.studio=masterStudio({presentation_id:PID,variant_id:vid(1),project_key:KEY},{viewers:1,
        work_copy:{modified_files:['src/scenes/pss_000000000001/Scene.tsx'],unpublished:1,base:null}});
      const ex=await openVariants();
      const shown={publish:!q('[data-act="remotion_studio_publish"]').hidden,text:say()};
      sceneDoor().click();await env.advance(80);
      const seen={target:dialog().getAttribute('data-target'),title:q('h2',dialog()).textContent,discard:(q('[data-line="discard"]',dialog())||{}).textContent};
      go().click();await env.advance(300);
      return {shown,seen,body:rms.opens[0],status:say()};
    """)
    assert out["shown"]["publish"] is False and "(vidéo entière), pas publié" in out["shown"]["text"]
    assert out["seen"]["target"] is None and out["seen"]["title"] == "Ouvrir cette scène hors du bac à sable ?", "the scene's own dialog"
    assert out["seen"]["discard"] == "Fichiers non publiés : 1 fichier modifié dans Remotion Studio (vidéo entière) sera mis de côté (studio-edits), pas publié."
    assert out["body"] == {"prefab_id": "lab.dial", "version": 1, "discard_unpublished": True, "acknowledge_unsandboxed_scene": True}
    assert "ouvert sur cette scène seule" in out["status"]


def test_an_incompatible_variant_keeps_the_scene_door_says_the_sentence_and_refuses_the_export(tmp_path):
    out = run_ui(tmp_path, MASTER_WORLD + r"""
      mp.plan={presentation_id:PID,variant_id:vid(1),variant_revision:1,generator_version:1,status:'incompatible',reason:'master_dimensions_mismatch',
        detail:'scene 2 (pss_000000000002) is 1920x1080',scene_ids:['pss_000000000002']};
      const ex=await openVariants();
      const seen={line:masterLine(),scene:sceneDoor().hidden,target:door().getAttribute('data-target'),vx:vx().getAttribute('aria-disabled'),
        vxTitle:vx().getAttribute('title')};
      vx().click();await env.advance(50);
      const refused={text:vxText(),posts:mp.jobs.length};
      door().click();await env.advance(80);
      const dlg={target:dialog().getAttribute('data-target'),title:q('h2',dialog()).textContent};
      go().click();await env.advance(300);
      return {seen,refused,dlg,body:rms.opens[0]};
    """)
    sentence = REASON_SENTENCES[MasterReason.DIMENSIONS_MISMATCH]
    assert out["seen"]["line"] == sentence + " « Remotion Studio » ouvre donc la scène à l’écran."
    assert out["seen"]["scene"] is True and out["seen"]["target"] == "scene" and out["seen"]["vx"] == "true"
    assert sentence in out["seen"]["vxTitle"] and sentence in out["refused"]["text"] and out["refused"]["posts"] == 0
    assert out["dlg"]["target"] is None and out["dlg"]["title"] == "Ouvrir cette scène hors du bac à sable ?"
    assert out["body"] == {"prefab_id": "lab.dial", "version": 1, "acknowledge_unsandboxed_scene": True}


def test_an_unreadable_readiness_keeps_the_scene_door_and_a_new_revision_is_read_again(tmp_path):
    out = run_ui(tmp_path, MASTER_WORLD + r"""
      mp.status=503;
      const ex=await openVariants();
      const failed={line:masterLine(),target:door().getAttribute('data-target'),reads:mp.reads,
        warn:env.logs.filter(l=>l[0]==='warn'&&l[1].includes('remotion_master_read_failed')).length};
      mp.status=200;
      vx().click();await env.advance(200);                 // the export's click re-reads an unreadable readiness
      const reread={reads:mp.reads,target:door().getAttribute('data-target')};
      world.byId(vid(1)).revision=2;                        // a voice edit: the variant's revision changes
      await ex.refresh();await env.advance(600);
      return {failed,reread,after:mp.reads};
    """)
    f = out["failed"]
    assert "n’a pas pu être lue" in f["line"] and f["target"] == "scene" and f["reads"] == 1 and f["warn"] == 1
    assert out["reread"] == {"reads": 2, "target": "master"}
    assert out["after"] == 3, "a new revision of the variant is read once more"


def test_export_freezes_the_variant_with_scope_master_follows_and_links_the_artefact(tmp_path):
    out = run_ui(tmp_path, MASTER_WORLD + r"""
      mp.postReply=()=>({status:202,body:{job:job()},delay:40});   // Core freezes the variant first: the request takes a moment
      const ex=await openVariants();
      vx().click();await env.advance(10);
      const starting=vxText();
      await env.advance(50);
      const queued=vxText();
      await env.advance(2100);
      const running={text:vxText(),cancel:!q('[data-act="video_export_cancel"]').hidden,busy:vx().getAttribute('aria-disabled')};
      vx().click();await env.advance(10);                  // a second click while one runs: nothing more
      mp.jobReplies.push({status:200,body:{job:job({state:'complete',phase:'complete',frames_done:135,percent:100,size_bytes:2400000})}});
      await env.advance(2100);
      const done={text:vxText(),link:q('.jvx-vx-link').getAttribute('href'),label:q('.jvx-vx-link').textContent,tone:q('.jvx-vx').getAttribute('data-tone')};
      return {starting,queued,running,done,posts:mp.jobs,logs:env.logs.filter(l=>l[1].includes('video_export_')).map(l=>l[1].split(' ')[1])};
    """)
    assert out["posts"] == [{"presentation_id": "pst_" + "0" * 31 + "1", "variant_id": "psv_" + "0" * 31 + "1", "expected_presentation_revision": 5,
                             "expected_variant_revision": 1, "format": "mp4", "settings": {"scope": "master"}}], "one request, the whole video"
    assert out["starting"].startswith("Export de la vidéo entière : demande envoyée")
    assert "En file d’attente" in out["queued"]
    r = out["running"]
    assert "Rendu des images · 40/135 images (29 %)" in r["text"] and r["cancel"] is True and r["busy"] == "true"
    d = out["done"]
    assert d["text"] == f"Vidéo entière exportée : Artefact jart_{'e' * 32} (2,3 Mo)." and d["tone"] == "ok"
    assert d["link"] == f"/api/artifacts/jart_{'e' * 32}/payload" and d["label"] == "Ouvrir la vidéo"
    assert {"video_export_requested", "video_export_started", "video_export_finished"} <= set(out["logs"])


def test_export_cancel_and_refusals_are_said_and_logged(tmp_path):
    out = run_ui(tmp_path, MASTER_WORLD + r"""
      const ex=await openVariants();
      vx().click();await env.advance(2200);
      q('[data-act="video_export_cancel"]').click();await env.advance(100);
      const cancelled={text:vxText(),cancels:mp.cancel,retry:!q('[data-act="video_export_retry"]').hidden};
      q('[data-act="video_export_dismiss"]').click();await env.advance(10);
      const dismissed=q('.jvx-vx').hidden;
      mp.postReply=()=>({status:409,body:{error:{code:'presentation_render_master_incompatible',message:'not ready',reason:'master_too_long',detail:'9001 frames'}}});
      vx().click();await env.advance(100);
      const refused={text:vxText(),code:q('.jvx-vx-code').textContent,codeShown:!q('.jvx-vx-code').hidden,tone:q('.jvx-vx').getAttribute('data-tone'),reads:mp.reads};
      mp.postReply=()=>({status:409,body:{error:{code:'presentation_studio_stale_revision',message:'stale'}}});
      const incompatibleRetry=!q('[data-act="video_export_retry"]').hidden;
      vx().click();await env.advance(300);
      const stale={text:vxText(),retry:!q('[data-act="video_export_retry"]').hidden};
      return {cancelled,dismissed,refused,incompatibleRetry,stale,warns:env.logs.filter(l=>l[0]==='warn'&&l[1].includes('video_export_')).length};
    """)
    assert out["cancelled"]["text"].startswith("Export de la vidéo entière annulé") and out["cancelled"]["cancels"] == 1
    assert out["dismissed"] is True
    r = out["refused"]
    assert r["text"] == REASON_SENTENCES[MasterReason.TOO_LONG] and r["code"] == "presentation_render_master_incompatible" and r["codeShown"]
    assert out["incompatibleRetry"] is False, "a whole video that is not ready: no « Réessayer » that cannot work"
    assert r["tone"] == "danger" and r["reads"] == 2, "Core's refusal re-reads the readiness"
    assert out["stale"]["text"].startswith("La variante a changé depuis sa lecture") and out["stale"]["retry"] is True
    assert out["warns"] >= 3


def test_a_running_export_of_this_whole_video_is_picked_up_when_variants_opens(tmp_path):
    out = run_ui(tmp_path, MASTER_WORLD + r"""
      mp.listed=[job({state:'running',phase:'encoding',frames_done:135,percent:99,elapsed_s:42}),job({job_id:'rj_bbbbbbbbbbbb',project_key:KEY2,state:'running'})];
      const ex=await openVariants();await env.advance(100);
      return {text:vxText(),posts:mp.jobs.length};
    """)
    assert out["text"].startswith("Export de la vidéo entière (3 scènes) — Encodage") and out["posts"] == 0


def test_the_rail_opens_variants_then_the_whole_video_confirmation(tmp_path):
    out = run_ui(tmp_path, MASTER_WORLD + r"""
      seed(3);
      const ex=make({player:fakePlayer});
      await ex.open({presentation_id:PID,fullscreen:false});
      const done=ex.remotionStudio.open({via:'rail'});
      await env.advance(900);
      const target=dialog()&&dialog().getAttribute('data-target');
      go().click();await env.advance(300);
      return {target,result:await done,body:rms.opens[0]};
    """)
    assert out["target"] == "master" and out["result"]["state"] == "ready" and out["body"]["kind"] == "variant_master"


# ------------------------------------------------------------------ 3. Board Artifacts

BOARD = SEED + EXPORT_SEED + r"""
const MASTER='/api/local-capabilities/remotion/render/master';
"""


def test_the_board_export_asks_the_whole_video_only_when_the_frozen_copy_is_ready(tmp_path):
    seen = run_node(tmp_path, BOARD + r"""
      const snap='jart_ps_'+'a'.repeat(32)+'_'+'b'.repeat(32)+'_p1_v1_a1';
      const results={};
      for(const [name,reply,format] of [['ready',{status:200,body:{master:{status:'ready',project_key:'mpk_'+'a'.repeat(24),scenes:[{},{},{}]}}},'mp4'],
          ['single',{status:200,body:{master:{status:'ready',project_key:'mpk_'+'c'.repeat(24),scenes:[{}]}}},'mp4'],
          ['incompatible',{status:200,body:{master:{status:'incompatible',reason:'master_fps_mismatch'}}},'mp4'],
          ['unreadable',{status:503,body:{error:{code:'core_unreachable',message:'down'}}},'mp4'],['still',null,'still']]){
        const e=exporter();await e.openBoard();
        if(reply)e.w.server.plan[MASTER]=reply;
        e.w.server.plan[JOBS]={status:202,body:{job:job()}};
        e.start(format);await settle();await settle();
        results[name]={posts:e.posts().map(p=>p.body),reads:e.w.server.calls.filter(c=>c.path.startsWith(MASTER)).map(c=>c.path),html:e.html(),
          logs:e.logs.map(l=>l.event)};
      }
      out({results,allowed:[W.allowed('GET',MASTER+'?snapshot_id='+snap),W.allowed('GET',MASTER),W.allowed('GET',MASTER+'?snapshot_id=a&x=1'),
        W.allowed('POST',MASTER+'?snapshot_id=a')]});
    """)
    snap = f"jart_ps_{'a' * 32}_{'b' * 32}_p1_v1_a1"
    r = seen["results"]
    assert r["ready"]["posts"] == [{"snapshot_id": snap, "format": "mp4", "settings": {"scope": "master"}}]
    assert r["ready"]["reads"] == [f"/api/local-capabilities/remotion/render/master?snapshot_id={snap}"]
    assert "Export MP4 (vidéo entière, 3 scènes) en cours" in _text(r["ready"]["html"])
    assert r["single"]["posts"] == [{"snapshot_id": snap, "format": "mp4"}], "a single-scene snapshot keeps the scene export body, no scope"
    assert list(r["single"]["posts"][0]) == ["snapshot_id", "format"], "byte for byte: same keys, same order"
    assert "vidéo entière" not in _text(r["single"]["html"])
    assert r["incompatible"]["posts"] == [{"snapshot_id": snap, "format": "mp4"}], "not ready: today's body, unchanged"
    assert r["unreadable"]["posts"] == [{"snapshot_id": snap, "format": "mp4"}] and "workspace.export_master_read_failed" in r["unreadable"]["logs"]
    assert r["still"]["posts"] == [{"snapshot_id": snap, "format": "still"}] and r["still"]["reads"] == [], "only an MP4 can be the whole video"
    assert seen["allowed"] == [True, False, False, False]
    assert RENDER_JOBS == "/api/local-capabilities/remotion/render/jobs"


def test_a_restored_single_scene_master_job_says_1_scene_on_the_board(tmp_path):
    seen = run_node(tmp_path, BOARD + r"""
      const e=exporter();
      e.w.server.plan[JOBS]={status:200,body:{jobs:[job({state:'running',phase:'rendering',frames_done:3,percent:5,scope:'master',scene_count:1})]}};
      await e.openBoard();
      out({html:e.html()});
    """)
    text = _text(seen["html"])
    assert "Export MP4 (vidéo entière, 1 scène) en cours" in text and "1 scènes" not in text


def test_the_master_line_is_a_live_region_and_the_confirmation_pins_its_action_row(tmp_path):
    out = run_ui(tmp_path, MASTER_WORLD + r"""
      const ex=await openVariants();
      const text=q('.jvx-rms-master-text');
      const live={role:text.getAttribute('role'),live:text.getAttribute('aria-live'),
        doorOutside:sceneDoor().parentNode===q('.jvx-rms-master')&&!text.children.length,
        doorLive:sceneDoor().getAttribute('aria-live'),masterLive:q('.jvx-rms-master').getAttribute('aria-live')};
      door().click();await env.advance(80);
      const box=dialog(),body=q('.jvx-confirm-body',box),actions=q('.jvx-dialog-actions',box);
      const shape={kids:box.children.map(n=>n.tagName.toLowerCase()+(n.className?'.'+n.className:'')),
        listInBody:!!q('ul.jvx-confirm-lines',body),actionsInBody:!!q('.jvx-dialog-actions',body),goInActions:go().parentNode===actions};
      return {live,shape};
    """)
    assert out["live"]["role"] == "status" and out["live"]["live"] == "polite"
    assert out["live"]["doorLive"] is None and out["live"]["masterLive"] is None, "one live region: the text, never the door beside it"
    assert out["live"]["doorOutside"] is True
    s = out["shape"]
    assert s["kids"] == ["h2", "div.jvx-confirm-body", "div.jvx-dialog-actions"], "heading, scrolling body, pinned action row"
    assert s["listInBody"] is True and s["actionsInBody"] is False and s["goInActions"] is True
