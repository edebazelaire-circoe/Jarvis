"""« Enregistrer dans Documents\\Jarvis » after « Exporter la vidéo » (presentation-edition-v1 Slice 03, `docs/export.md`), by node.

1. Pure model: the save button appears only on a complete export; saving, saved (numbered name said), refused (French sentence + code).
2. The explorer on the fake DOM: nothing is posted to `/api/exports` until the click; the click posts only `{artifact_id}` (never a path);
   a refusal is said and logged.
"""

from __future__ import annotations


from tests.fakes.explorer_js import run_ui
from tests.unit.test_variants_master_entrypoints_js import EXPORT_JS, MASTER_WORLD, export_model
from tests.unit.test_variants_remotion_studio_js import node

JOB = {"job_id": "rj_0123456789ab", "state": "complete", "phase": "complete", "frames_done": 135, "frames_total": 135, "percent": 100,
       "artifact_id": "jart_x", "size_bytes": 3_500_000, "scene_count": 3}


def test_the_save_button_shows_only_on_a_complete_export():
    done = export_model(x={"status": "done", "job": JOB, "started": 1})
    assert done["status"]["save"] is True and done["status"]["text"] == "Vidéo entière exportée : Artefact jart_x (3,3 Mo)."
    running = export_model(x={"status": "running", "job": {**JOB, "state": "running"}, "started": 1})
    assert not running["status"].get("save")
    failed = export_model(x={"status": "done", "job": {**JOB, "state": "failed", "error_code": "presentation_render_failed"}, "started": 1})
    assert not failed["status"].get("save")


def test_saving_saved_and_refused_are_said():
    saving = export_model(x={"status": "done", "job": JOB, "started": 1, "save": {"status": "saving", "started": 97_000}}, now=100_000)
    assert saving["status"]["spin"] is True and saving["status"]["save"] is False
    assert saving["status"]["text"].endswith("Copie vers Documents\\Jarvis… 3 s")
    saved = export_model(x={"status": "done", "job": JOB, "started": 1, "save": {"status": "saved", "result": {
        "file_name": "Atelier - video (2).mp4", "renamed": True,
        "destination": {"root": "Documents\\Jarvis", "display_path": "Documents\\Jarvis\\Atelier - video (2).mp4"}}}})
    assert saved["status"]["save"] is False and saved["status"]["tone"] == "ok"
    assert saved["status"]["text"].endswith("Copie enregistrée : Documents\\Jarvis\\Atelier - video (2).mp4 "
                                            "(le nom était pris : numéroté, rien n’a été écrasé).")
    refused = export_model(x={"status": "done", "job": JOB, "started": 1, "save": {"status": "error", "error": {
        "code": "export_destination_unsafe", "text": "Le dossier Documents\\Jarvis est un lien", "detail": ""}}})
    assert refused["status"]["tone"] == "danger" and refused["status"]["save"] is True, "a refusal can be retried"
    assert refused["status"]["code"] == "export_destination_unsafe"


def test_every_typed_export_refusal_has_a_french_sentence():
    codes = node(f"const E=require({EXPORT_JS});process.stdout.write(JSON.stringify(Object.keys(E.SAVE_ERRORS)));")
    from jarvis.domain.document_export import ExportErrorCode
    expected = {c.value for c in ExportErrorCode} - {"export_invalid", "export_failed", "export_unavailable"}
    assert set(codes) == expected


EXPORT_WORLD = MASTER_WORLD + r"""
const xs={posts:[],reply:null};
env.route('/api/exports',(url,rec,body)=>{
  if(url==='/api/exports'&&rec.method==='POST'){xs.posts.push(body);return xs.reply?xs.reply(body):{status:201,body:{export:{
    artifact_id:body.artifact_id,format:'mp4',file_name:'Atelier - video.mp4',renamed:false,copy:true,size_bytes:2400000,
    destination:{root:'Documents\\Jarvis',display_path:'Documents\\Jarvis\\Atelier - video.mp4'}}}}}
  return {status:404,body:{error:{code:'no_route',message:url}}};
});
const save=()=>q('[data-act="video_export_save"]');
"""


def test_the_copy_is_posted_only_on_the_click_with_the_artifact_id_alone(tmp_path):
    out = run_ui(tmp_path, EXPORT_WORLD + r"""
      mp.postReply=()=>({status:202,body:{job:job({state:'complete',phase:'complete',frames_done:135,percent:100,size_bytes:2400000})}});
      const ex=await openVariants();
      vx().click();await env.advance(100);
      const before={posts:xs.posts.length,save:!save().hidden};
      save().click();await env.advance(50);
      const after={text:vxText(),save:save().hidden,posts:xs.posts};
      return {before,after,logs:env.logs.filter(l=>l[1].includes('video_export_save')).map(l=>l[1].split(' ')[1])};
    """)
    assert out["before"] == {"posts": 0, "save": True}, "nothing goes to Documents before the click"
    assert out["after"]["posts"] == [{"artifact_id": "jart_" + "e" * 32}], "an artifact id, never a path"
    assert out["after"]["text"].endswith("Copie enregistrée : Documents\\Jarvis\\Atelier - video.mp4.") and out["after"]["save"] is True
    assert out["logs"] == ["video_export_save_requested", "video_export_saved"]


def test_a_refused_copy_is_said_with_its_code_and_logged(tmp_path):
    out = run_ui(tmp_path, EXPORT_WORLD + r"""
      mp.postReply=()=>({status:202,body:{job:job({state:'complete',phase:'complete',frames_done:135,percent:100,size_bytes:2400000})}});
      xs.reply=()=>({status:409,body:{error:{code:'export_destination_unsafe',message:'the export folder is a junction'}}});
      const ex=await openVariants();
      vx().click();await env.advance(100);
      save().click();await env.advance(50);
      return {text:vxText(),code:q('.jvx-vx-code').textContent,tone:q('.jvx-vx').getAttribute('data-tone'),again:!save().hidden,
              warn:env.logs.filter(l=>l[1].includes('video_export_save_failed')).map(l=>l[0])};
    """)
    assert "est un lien ou une jonction" in out["text"] and out["code"] == "export_destination_unsafe"
    assert out["tone"] == "danger" and out["again"] is True and out["warn"] == ["warn"]
