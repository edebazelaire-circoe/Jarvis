"""« Publier dans la variante… » in Variants, by node (handoff jarvis-remotion-native-studio-playback-fix, Slice 12).

1. The pure model (`doorModel`, `workspaceOf`): unpublished files of the Remotion Studio workspace are said with Remotion Studio stopped
   too; publishing is offered only when the workspace base is this scene's pin (or a base no scene on screen holds: Core decides), never
   when it is another scene of the deck; the publication in progress shows motion, a counter and its deadline; a refusal says its code and
   keeps the button; a publication says the new and the kept version and offers « Revenir à la v<N> » (« la version d'avant » when the first publication forked the scene's own source id).
2. The explorer on the fake DOM with the real modules: one confirmation in Variants' layer naming the scene and the files; « Annuler »
   publishes nothing; « Publier » sends Core's exact body (the workspace base, `confirm_publish`), says the result, re-reads the variant,
   and « Revenir » is the source-edit door's `restore_version`; a conflict is said with both versions and logged; opening another scene
   with unpublished files says so in the confirmation and sends `discard_unpublished` (never silently).

Contract: `docs/presentation-studio.md` › *Remotion Studio round trip (Level 3, Slice 12)*.
"""

from __future__ import annotations

from tests.fakes.explorer_js import run_ui
from tests.unit.test_variants_remotion_studio_js import PIN, READY, STUDIO_WORLD, model

DIGEST = "d" * 64
STOPPED_WITH_EDITS = {"status": "stopped", "pin": {"prefab_id": "lab.dial", "version": 1}, "url": None, "viewers": 0,
                      "work_copy": {"modified_files": ["src/Scene.tsx"], "unpublished": 1, "base": {"prefab_id": "lab.dial", "version": 1},
                                    "writable": True, "edits_saved": 0, "digest": DIGEST, "set_aside": []}}


# ------------------------------------------------------------------ 1. the pure model

def test_unpublished_files_are_said_and_publishable_even_with_remotion_studio_stopped():
    m = model(studio=STOPPED_WITH_EDITS)
    assert m["publish"]["offered"] is True and m["status"]["publish"] is True and m["status"]["tone"] == "warn"
    assert m["status"]["text"] == "1 fichier modifié dans Remotion Studio, pas encore publié : la variante n’a pas changé."
    none = model(studio={**STOPPED_WITH_EDITS, "work_copy": {**STOPPED_WITH_EDITS["work_copy"], "modified_files": [], "unpublished": 0}})
    assert none["publish"]["offered"] is False and none["status"] is None


def test_a_workspace_of_another_scene_is_not_publishable_here_and_an_unknown_base_is_left_to_core():
    other = {**STOPPED_WITH_EDITS, "work_copy": {**STOPPED_WITH_EDITS["work_copy"], "base": {"prefab_id": "lab.chart", "version": 4}}}
    m = model(studio=other)
    assert m["publish"]["offered"] is False and "sur la scène 2, pas publié : à publier depuis cette scène-là" in m["status"]["text"]
    earlier = {**STOPPED_WITH_EDITS, "work_copy": {**STOPPED_WITH_EDITS["work_copy"], "base": {"prefab_id": "presentation-studio.p1.s1", "version": 3}}}
    e = model(studio=earlier)
    assert e["publish"]["offered"] is True and "Jarvis vérifiera avant de publier" in e["status"]["text"]
    assert model(studio=STOPPED_WITH_EDITS, run=True)["publish"]["offered"] is False, "not during a run"


def test_publishing_shows_motion_a_counter_and_its_deadline():
    m = model(studio=STOPPED_WITH_EDITS, publishing={"at": 88_000, "label": "Publication dans la variante…"})
    assert m["status"]["spin"] is True and m["status"]["text"] == "Publication dans la variante… 12 s (2.5 min au plus)."
    assert m["button"]["state"] == "busy"


def test_a_refusal_says_its_code_and_keeps_the_button_a_publication_offers_the_way_back():
    error = {"code": "remotion_studio_publish_refused", "text": "La variante a refusé", "diagnostics": ["src/Scene.tsx:5:12 x"],
             "sceneId": "pss_000000000001"}
    r = model(studio=STOPPED_WITH_EDITS, publishError=error)
    assert r["status"]["tone"] == "danger" and r["status"]["text"].endswith("(remotion_studio_publish_refused)")
    assert r["status"]["diagnostics"] == ["src/Scene.tsx:5:12 x"] and r["status"]["publish"] is True, "fix the file, publish again"
    elsewhere = model(studio=STOPPED_WITH_EDITS, publishError={**error, "sceneId": "pss_other"})
    assert "Publication refusée" not in elsewhere["status"]["text"], "an outcome belongs to its scene"
    new_pin = {"prefab_id": "presentation-studio.p1.s1", "version": 1}
    clean = {**STOPPED_WITH_EDITS, "pin": new_pin, "work_copy": {"modified_files": [], "unpublished": 0, "base": new_pin, "edits_saved": 0}}
    done = model(studio=clean, scene={"id": "pss_000000000001", "title": "Ouverture", "number": 1, "of": 3, "prefab": {"id": new_pin["prefab_id"], "version": 1}},
                 published={"published": new_pin, "previous": {"prefab_id": "lab.dial", "version": 1}, "status": "reloaded", "sceneId": "pss_000000000001"})
    assert done["status"]["tone"] == "ok"
    assert done["status"]["text"] == "Publié dans la variante : nouvelle version de la scène (v1) ; la version d’avant reste disponible."
    assert done["status"]["revert"] == {"label": "Revenir à la version d’avant", "target": {"prefab_id": "lab.dial", "version": 1}}
    same = {"prefab_id": "presentation-studio.p1.s1", "version": 2}
    second = model(studio={**clean, "pin": same, "work_copy": {**clean["work_copy"], "base": same}},
                   scene={"id": "pss_000000000001", "title": "O", "number": 1, "of": 3, "prefab": {"id": same["prefab_id"], "version": 2}},
                   published={"published": same, "previous": new_pin, "status": "reloaded", "sceneId": "pss_000000000001"})
    assert second["status"]["text"] == "Publié dans la variante : nouvelle version de la scène (v2) ; la v1 reste disponible."
    assert second["status"]["revert"]["label"] == "Revenir à la v1", "the same source: versions are numbered"
    repinned = model(studio=clean, scene={"id": "pss_000000000001", "title": "O", "number": 1, "of": 3, "prefab": {"id": new_pin["prefab_id"], "version": 1}},
                     published={"published": new_pin, "previous": None, "status": "repinned", "sceneId": "pss_000000000001"})
    assert "prochaine lecture" not in repinned["status"]["text"] and repinned["status"]["revert"] is None, "Variants re-read: nothing to wait for"


# ------------------------------------------------------------------ 2. the explorer on the fake DOM

PUBLISH_WORLD = STUDIO_WORLD + r"""
rms.publishes=[];rms.publishReply=null;rms.restores=[];
env.route(url=>url.endsWith('/studio/publish'),(url,rec,body)=>{
  rms.publishes.push(body);
  if(rms.publishReply)return rms.publishReply(body);
  const pub={prefab_id:'presentation-studio.p1.s1',version:1};
  rms.studio=Object.assign({},rms.studio,{pin:pub,work_copy:{modified_files:[],unpublished:0,base:pub,edits_saved:0}});
  return {status:200,body:{studio:rms.studio,publish:{status:'reloaded',published:pub,previous:body.base,variant_revision:9,files:{changed:['src/Scene.tsx']}}}};
});
env.route(url=>url.endsWith('/source-edits'),(url,rec,body)=>{
  rms.restores.push({url,body});
  return {status:200,body:{status:'reloaded',published:{id:'presentation-studio.p1.s1',version:2},previous:{id:'presentation-studio.p1.s1',version:1}}};
});
const publishBtn=()=>q('[data-act="remotion_studio_publish"]');
const pubDialog=()=>q('[data-kind="remotion_studio_publish"]');
const pubGo=()=>q('[data-act="remotion_studio_publish_confirm"]');
const revertBtn=()=>q('[data-act="remotion_studio_revert"]');
"""


def test_publish_confirms_sends_the_exact_body_says_the_result_rereads_and_reverts(tmp_path):
    out = run_ui(tmp_path, PUBLISH_WORLD + r"""
      rms.studio={status:'stopped',pin:{prefab_id:'lab.dial',version:1},url:null,viewers:0,
        work_copy:{modified_files:['src/Scene.tsx'],unpublished:1,base:{prefab_id:'lab.dial',version:1},edits_saved:0,digest:'d'.repeat(64)}};
      const ex=await openVariants();
      const shown={visible:!publishBtn().hidden,text:say()};
      publishBtn().click();await env.advance(50);
      const dlg={kind:!!pubDialog(),modal:pubDialog()&&pubDialog().getAttribute('aria-modal'),text:pubDialog()?pubDialog().textContent:''};
      qa('button',pubDialog()).find(b=>b.textContent==='Annuler').click();await env.advance(50);
      const afterCancel={dialog:!!pubDialog(),sent:rms.publishes.length};
      const reads=env.requests.filter(r=>r.method==='GET'&&r.url.includes('/variants/')).length;
      publishBtn().click();await env.advance(50);pubGo().click();await env.advance(400);
      const done={text:say(),tone:status().getAttribute('data-tone'),revert:!revertBtn().hidden&&revertBtn().textContent,
        reread:env.requests.filter(r=>r.method==='GET'&&r.url.includes('/variants/')).length>reads};
      revertBtn().click();await env.advance(400);
      return {shown,dlg,afterCancel,publishes:rms.publishes,done,restores:rms.restores,after:say(),
        logs:env.logs.filter(l=>l[1].includes('remotion_studio_publish')||l[1].includes('remotion_studio_rever')).map(l=>l[1].split(' ')[1])};
    """)
    assert out["shown"]["visible"] and "pas encore publié" in out["shown"]["text"]
    d = out["dlg"]
    assert d["kind"] and d["modal"] == "true" and "Scène 1 sur 3" in d["text"] and "src/Scene.tsx" in d["text"]
    assert "NOUVELLE version" in d["text"] and "reste disponible" in d["text"] and "react et remotion" in d["text"]
    assert out["afterCancel"] == {"dialog": False, "sent": 0}, "« Annuler » publishes nothing"
    [sent] = out["publishes"]
    assert set(sent) == {"presentation_id", "variant_id", "scene_id", "base", "digest", "confirm_publish"} and sent["confirm_publish"] is True
    assert sent["digest"] == DIGEST, "the listing the confirmation showed is what Core checks"
    assert sent["base"] == {"prefab_id": "lab.dial", "version": 1} and sent["scene_id"] == "pss_000000000001"
    assert out["done"]["tone"] == "ok"
    assert out["done"]["text"] == "Publié dans la variante : nouvelle version de la scène (v1) ; la version d’avant reste disponible."
    assert out["done"]["revert"] == "Revenir à la version d’avant" and out["done"]["reread"] is True, "Variants re-reads: the new pin plays"
    [restore] = out["restores"]
    assert restore["body"]["files"] == {"restore_version": {"id": "lab.dial", "version": 1}} and restore["body"]["actor"] == "user"
    assert restore["body"]["scene_id"] == "pss_000000000001" and isinstance(restore["body"]["basis"]["variant_revision"], int)
    assert "Revenu au contenu d’avant : publié comme nouvelle version (v2)." in out["after"]
    assert {"remotion_studio_publish_requested", "remotion_studio_published", "remotion_studio_publish_cancelled",
            "remotion_studio_revert_requested", "remotion_studio_reverted"} <= set(out["logs"])


def test_a_conflict_is_said_with_both_versions_logged_and_the_button_stays(tmp_path):
    out = run_ui(tmp_path, PUBLISH_WORLD + r"""
      rms.studio={status:'stopped',pin:{prefab_id:'lab.dial',version:1},url:null,viewers:0,
        work_copy:{modified_files:['src/Scene.tsx'],unpublished:1,base:{prefab_id:'lab.dial',version:1},edits_saved:0,digest:'d'.repeat(64)}};
      rms.publishReply=()=>({status:409,body:{error:{code:'remotion_studio_publish_conflict',message:'moved',base:{prefab_id:'lab.dial',version:1},
        current:{prefab_id:'presentation-studio.p1.s1',version:2}}}});
      const ex=await openVariants();
      publishBtn().click();await env.advance(50);pubGo().click();await env.advance(400);
      return {text:say(),tone:status().getAttribute('data-tone'),button:!publishBtn().hidden,busy:door().getAttribute('aria-disabled'),
        warns:env.logs.filter(l=>l[0]==='warn'&&l[1].includes('remotion_studio_publish_failed')).length};
    """)
    assert out["tone"] == "danger" and "(remotion_studio_publish_conflict)" in out["text"]
    assert "La variante utilise la v2 ; Remotion Studio a été ouvert sur la v1." in out["text"]
    assert out["button"] is True and out["busy"] == "false" and out["warns"] == 1


def test_opening_another_scene_with_unpublished_files_says_so_and_sends_the_discard(tmp_path):
    out = run_ui(tmp_path, PUBLISH_WORLD + r"""
      rms.studio={status:'stopped',pin:{prefab_id:'lab.other',version:2},url:null,viewers:0,
        work_copy:{modified_files:['src/Scene.tsx','src/a.ts'],unpublished:2,base:{prefab_id:'lab.other',version:2},edits_saved:0}};
      const ex=await openVariants();
      door().click();await env.advance(50);
      const line=q('[data-line="discard"]',dialog());
      const text=line?line.textContent:'';
      go().click();await env.advance(300);
      return {text,opens:rms.opens};
    """)
    assert "2 fichiers modifiés dans Remotion Studio (sur v2) seront mis de côté (studio-edits), pas publiés." in out["text"]
    assert out["opens"] == [{"prefab_id": "lab.dial", "version": 1, "discard_unpublished": True, "acknowledge_unsandboxed_scene": True}]


def test_the_same_scene_with_unpublished_files_opens_without_any_discard(tmp_path):
    out = run_ui(tmp_path, PUBLISH_WORLD + r"""
      rms.studio={status:'stopped',pin:{prefab_id:'lab.dial',version:1},url:null,viewers:0,
        work_copy:{modified_files:['src/Scene.tsx'],unpublished:1,base:{prefab_id:'lab.dial',version:1},edits_saved:0,digest:'d'.repeat(64)}};
      const ex=await openVariants();
      door().click();await env.advance(50);
      const line=!!q('[data-line="discard"]',dialog());
      go().click();await env.advance(300);
      return {line,opens:rms.opens};
    """)
    assert out["line"] is False and out["opens"] == [{"prefab_id": "lab.dial", "version": 1, "acknowledge_unsandboxed_scene": True}]
    assert PIN == {"id": "lab.dial", "version": 1} and READY["pin"]["prefab_id"] == "lab.dial"


def test_the_shared_client_adds_the_publish_confirmation_only_on_publish_and_keeps_the_refusal_details(tmp_path):
    from tests.unit.test_control_center_remotion_studio import run_node
    out = run_node(tmp_path, """
      const calls=[];let next={ok:true,status:200,json:async()=>({studio:{status:'stopped'},publish:{status:'reloaded'}})};
      const client=C.createClient({fetchImpl:async(path,options)=>{calls.push([path,JSON.parse(options.body)]);return next}});
      const published=await client.write('publish',{presentation_id:'prs_1',variant_id:'var_1',scene_id:'pss_1',base:{prefab_id:'a',version:1},digest:'e'.repeat(64)});
      await client.write('open',{prefab_id:'a',version:2,discard_unpublished:true});
      await client.write('sync');
      next={ok:false,status:409,json:async()=>({error:{code:'remotion_studio_publish_conflict',message:'m',current:{prefab_id:'a',version:3}}})};
      let refused=null;try{await client.write('publish',{})}catch(e){refused={code:e.code,status:e.status,current:e.info.current}}
      return {calls,published,refused,deadline:C.WRITES.publish,limit:C.PUBLISH_LIMIT_S};""")
    assert out["calls"][0] == ["/api/local-capabilities/remotion/studio/publish", {"presentation_id": "prs_1", "variant_id": "var_1", "scene_id": "pss_1",
                                                                                     "base": {"prefab_id": "a", "version": 1}, "digest": "e" * 64,
                                                                                     "confirm_publish": True}]
    assert out["calls"][1][1] == {"prefab_id": "a", "version": 2, "discard_unpublished": True, "acknowledge_unsandboxed_scene": True}
    assert out["calls"][2][1] == {}, "nothing is added to a plain sync: no confirmation, no discard"
    assert out["published"] == {"studio": {"status": "stopped"}, "publish": {"status": "reloaded"}}
    assert out["refused"] == {"code": "remotion_studio_publish_conflict", "status": 409, "current": {"prefab_id": "a", "version": 3}}
    assert out["deadline"] == 160000 and out["limit"] == 150


# ------------------------------------------------------------------ QA Slice 12 rework (I1, P-a, B1)

def test_the_confirmation_lists_every_file_focuses_cancel_and_sends_the_digest_it_showed(tmp_path):
    out = run_ui(tmp_path, PUBLISH_WORLD + r"""
      const files=Array.from({length:14},(_,i)=>`src/lib/Part${String(i).padStart(2,'0')}.tsx`);
      rms.studio={status:'stopped',pin:{prefab_id:'lab.dial',version:1},url:null,viewers:0,
        work_copy:{modified_files:files,unpublished:14,base:{prefab_id:'lab.dial',version:1},edits_saved:0,digest:'a'.repeat(64)}};
      const ex=await openVariants();
      publishBtn().click();await env.advance(50);
      const listed=qa('li',q('[data-line="files-list"]',pubDialog())).map(li=>li.textContent);
      const focus={cancel:doc.activeElement&&doc.activeElement.textContent==='Annuler',go:doc.activeElement===pubGo()};
      env.key(doc.activeElement,'Enter');await env.advance(50);
      const afterEnter={sent:rms.publishes.length};
      if(pubDialog())qa('button',pubDialog()).find(b=>b.textContent==='Annuler').click();await env.advance(50);
      // the poll changed the listing after the dialog opened: the digest sent is the one the dialog SHOWED
      publishBtn().click();await env.advance(50);
      rms.studio=Object.assign({},rms.studio,{work_copy:Object.assign({},rms.studio.work_copy,{digest:'b'.repeat(64)})});
      pubGo().click();await env.advance(400);
      return {listed,focus,afterEnter,sent:rms.publishes.map(b=>b.digest)};
    """)
    assert out["listed"] == [f"src/lib/Part{i:02d}.tsx" for i in range(14)], "every changed file, none cut at 8"
    assert out["focus"] == {"cancel": True, "go": False}, "a stray Enter must not publish"
    assert out["afterEnter"] == {"sent": 0}
    assert out["sent"] == ["a" * 64]


def test_a_listing_that_changed_since_the_confirmation_is_said_and_read_again(tmp_path):
    out = run_ui(tmp_path, PUBLISH_WORLD + r"""
      rms.studio={status:'stopped',pin:{prefab_id:'lab.dial',version:1},url:null,viewers:0,
        work_copy:{modified_files:['src/Scene.tsx'],unpublished:1,base:{prefab_id:'lab.dial',version:1},edits_saved:0,digest:'a'.repeat(64)}};
      rms.publishReply=()=>{
        rms.studio=Object.assign({},rms.studio,{work_copy:Object.assign({},rms.studio.work_copy,{modified_files:['src/Scene.tsx','src/a.ts'],unpublished:2,digest:'c'.repeat(64)})});
        return {status:409,body:{error:{code:'remotion_studio_publish_listing_changed',message:'changed',count:2,files:['src/Scene.tsx','src/a.ts']}}}};
      const ex=await openVariants();
      const reads=()=>env.requests.filter(r=>r.method==='GET'&&r.url.endsWith('/remotion/studio')).length;
      publishBtn().click();await env.advance(50);
      const before=reads();
      pubGo().click();await env.advance(400);
      const text=say();
      publishBtn().click();await env.advance(50);
      const relisted=qa('li',q('[data-line="files-list"]',pubDialog())).map(li=>li.textContent);
      return {text,reread:reads()>before,relisted,
        warns:env.logs.filter(l=>l[0]==='warn'&&l[1].includes('remotion_studio_publish_failed')).length};
    """)
    assert "(remotion_studio_publish_listing_changed)" in out["text"] and "rien n’a été publié" in out["text"]
    assert "(2 fichiers modifiés maintenant)" in out["text"]
    assert out["reread"] is True and out["relisted"] == ["src/Scene.tsx", "src/a.ts"], "the page lists again before a new confirmation"
    assert out["warns"] == 1


def test_what_the_last_launch_set_aside_is_said_on_the_scene():
    aside = {**STOPPED_WITH_EDITS, "work_copy": {**STOPPED_WITH_EDITS["work_copy"], "set_aside": ["remotion.config.js", "src/lib2"]}}
    m = model(studio=aside)
    assert m["status"]["tone"] == "warn"
    assert ("Au dernier lancement, 2 éléments étrangers à l’espace de travail (remotion.config.js, src/lib2) ont été mis de côté dans "
            "studio-edits : jamais exécutés ni publiés.") in m["status"]["text"]
    clean = {**STOPPED_WITH_EDITS, "work_copy": {**STOPPED_WITH_EDITS["work_copy"], "modified_files": [], "unpublished": 0, "set_aside": ["x.txt"]}}
    alone = model(studio=clean)
    assert alone["status"]["text"].startswith("Au dernier lancement, 1 élément étranger") and alone["status"]["tone"] == "warn"
