"""Présentations dans la vue Artefacts d'un Board, exécutées par node (Remotion Slice 08).

Même double de serveur que `test_workspace_manager_js.py` (formes réelles de `/api/workspace/*`), le module est le fichier
même du Control Center. Ce que ce fichier épingle : le groupement « source -> copie figée -> rendus » avec moteur,
révisions et fraîcheur ; les états périmé, source supprimée ou illisible, rendu orphelin, ligne illisible ; l'ouverture de la
source par identifiant (jamais un lien d'artefact) ; l'échappement ; l'attente et l'erreur dites ; la relecture sans cache.
Contrat : `docs/presentation-artifacts.md` (« Contract for Slice 08 »), `docs/boards.md`.
"""

from __future__ import annotations

from tests.unit.test_workspace_manager_js import _text, run_node

PST = "pst_" + "a" * 32
PSV = "psv_" + "b" * 32
SEED = r"""
const PST='pst_'+'a'.repeat(32),PSV='psv_'+'b'.repeat(32),SNAP='jart_ps_'+'a'.repeat(32)+'_'+'b'.repeat(32)+'_p1_v1_a1';
const RENDER='jart_'+'c'.repeat(32);
const snapshot=(over)=>Object.assign({artifact_id:SNAP,state:'complete',variant_id:PSV,created_at:'2026-10-09T09:00:00+00:00',error_code:null,
  source_presentation_revision:1,source_variant_revision:1,engine:'remotion',content_sha256:'d'.repeat(64),stale:false,linked_here:true,
  board_ids:['board_a'],truncated:false,
  renders:[{artifact_id:RENDER,kind:'presentation_video',state:'complete',format:'mp4',size_bytes:2048,board_ids:['board_a']}]},over||{});
const group=(over,snap)=>Object.assign({source_ref:'presentation:'+PST,presentation_id:PST,
  source:{exists:true,title:'Atelier',engine:'remotion',revision:2,variant_revisions:{[PSV]:1}},snapshots:[snapshot(snap)]},over||{});
const seed=(w,sources,extra)=>{w.server.plan['/api/workspace/boards/board_a/presentation-sources']={status:200,
  body:Object.assign({board_id:'board_a',sources,unreadable:[],truncated:false},extra||{})}};
const openArtifacts=async(w)=>{w.manager.open();await settle();await w.act('view',{view:'artifacts'});
  await w.act('artifacts-filter',{scope:'board',id:'board_a'})};
"""


def test_a_board_groups_source_snapshot_and_renders_with_engine_revisions_and_freshness(tmp_path):
    seen = run_node(tmp_path, SEED + r"""
      const w=world();seed(w,[group()]);
      await openArtifacts(w);
      out({html:w.html(),calls:w.server.calls.map(c=>c.path)});
    """)
    text = _text(seen["html"])
    assert "Présentations de « Projet A »" in text and "Atelier" in text
    # order reads top-down: source, then its frozen copy, then the render
    assert text.index("Source") < text.index("Copie figée") < text.index("Rendu")
    assert "Remotion" in text and "révision 2" in text and "À jour" in text
    assert f"variante {PSV} · révision 1/1" in text
    assert "MP4" in text and "presentation_video" not in text, "kind translated, raw value only in the tooltip"
    assert 'title="kind : presentation_video"' in seen["html"]
    assert f'data-act="source-open" data-presentation="{PST}"' in seen["html"] and "Ouvrir la source" in text
    assert f'data-act="source-open" data-presentation="{PST}" data-variant="{PSV}"' in seen["html"]
    assert 'data-act="artifact-show" data-id="' + "jart_" + "c" * 32 + '"' in seen["html"], "a render opens as an artifact"
    assert "/api/workspace/boards/board_a/presentation-sources" in seen["calls"]
    assert all("pst_" not in c or "presentation-sources" in c for c in seen["calls"]), "a source id is never an artifact route"


def test_the_artifact_kind_filter_offers_the_four_presentation_kinds(tmp_path):
    seen = run_node(tmp_path, SEED + r"""
      const w=world();seed(w,[]);await openArtifacts(w);
      out({html:w.html(),kinds:Object.keys(W.ARTIFACT_KINDS),labels:W.ARTIFACT_KINDS});
    """)
    for kind in ("presentation_snapshot", "presentation_video", "presentation_still", "presentation_pdf"):
        assert kind in seen["kinds"] and f'<option value="{kind}"' in seen["html"], kind
    assert len(seen["kinds"]) == 11
    text = _text(seen["html"])
    assert "Présentation figée" in text and "Aucune présentation figée sur ce Board" in text


def test_stale_deleted_unreadable_and_orphan_states_are_visible_and_distinct(tmp_path):
    seen = run_node(tmp_path, SEED + r"""
      const w=world();
      seed(w,[
        group({},{stale:true}),
        group({presentation_id:'pst_'+'e'.repeat(32),source_ref:'presentation:pst_'+'e'.repeat(32),source:{exists:false}},{stale:null,linked_here:false,
          artifact_id:'jart_ps_gone',renders:[{artifact_id:'jart_'+'f'.repeat(32),kind:'presentation_pdf',state:'pending',format:'pdf',size_bytes:null,board_ids:['board_b']}]}),
        group({presentation_id:'pst_'+'9'.repeat(32),source_ref:'presentation:pst_'+'9'.repeat(32),source:{exists:null,unreadable:'presentation_studio_corrupt_document'}},
          {stale:null,state:'failed',error_code:'source_stale',renders:[]}),
      ],{unreadable:[{artifact_id:'jart_ps_bad',kind:'presentation_snapshot',code:'invalid_artifact'}],truncated:true});
      await openArtifacts(w);
      out({html:w.html()});
    """)
    text = _text(seen["html"])
    assert "Source modifiée depuis" in text, "stale is a display fact"
    assert "Source supprimée" in text and "Lié par un rendu seulement" in text and "Non lié à ce Board" in text
    assert "Source illisible" in text and "Échoué" in text and "source_stale" in text
    assert "Aucun rendu." in text
    assert "1 artefact de présentation illisible" in text and "jart_ps_bad" in text
    assert "Lecture bornée" in text
    # the deleted source offers no "open": a disabled button, never a dead link
    assert seen["html"].count('data-act="source-open"') == 6
    assert seen["html"].count('data-act="source-open" data-presentation="pst_' + "e" * 32 + '" disabled') == 1
    assert "(AAA)" not in text


def test_other_boards_showing_the_same_source_are_reachable_by_title(tmp_path):
    seen = run_node(tmp_path, SEED + r"""
      const w=world();seed(w,[group({},{board_ids:['board_a','board_b']})]);
      await openArtifacts(w);
      const before=w.html();
      await w.act('goto',{view:'artifacts',scope:'board',id:'board_b'});
      out({before,calls:w.server.calls.map(c=>c.path),scope:w.S.artifacts.id});
    """)
    assert "Aussi sur" in _text(seen["before"]) and "Projet B" in _text(seen["before"])
    assert 'data-act="goto" data-view="artifacts" data-scope="board" data-id="board_b"' in seen["before"]
    assert seen["scope"] == "board_b"
    assert "/api/workspace/boards/board_b/presentation-sources" in seen["calls"], "the other Board is read, not remembered"


def test_open_source_asks_the_studio_by_identifier_and_says_every_refusal(tmp_path):
    seen = run_node(tmp_path, SEED + r"""
      const asked=[];
      let w=world({openStudioSource:async(p,v)=>{asked.push([p,v]);return {state:'opened'}}});
      seed(w,[group()]);await openArtifacts(w);
      await w.act('source-open',{presentation:PST,variant:PSV});
      const ok=w.S.notice;
      w=world({openStudioSource:async()=>({state:'refused',code:'explorer_run_in_progress',reason:'Une lecture est en cours.'})});
      seed(w,[group()]);await openArtifacts(w);await w.act('source-open',{presentation:PST});
      const refused=w.S.notice;const refusedLog=w.logs.filter(l=>l.event==='workspace.source_open');
      w=world({openStudioSource:async()=>{throw new Error('boum')}});
      seed(w,[group()]);await openArtifacts(w);await w.act('source-open',{presentation:PST});
      const thrown=w.S.notice;
      w=world();seed(w,[group()]);await openArtifacts(w);await w.act('source-open',{presentation:PST});
      out({asked,ok,refused,refusedLog,thrown,absent:w.S.notice});
    """)
    assert seen["asked"] == [[PST, PSV]] and seen["ok"] is None
    assert seen["refused"]["tone"] == "bad" and "Une lecture est en cours." in seen["refused"]["text"]
    assert seen["refusedLog"][0]["level"] == "warn" and seen["refusedLog"][0]["data"]["refused"] is True
    assert "boum" in seen["thrown"]["text"]
    assert "pas disponible" in seen["absent"]["text"]


def test_waiting_error_and_retry_of_the_presentations_read_are_said(tmp_path):
    seen = run_node(tmp_path, SEED + r"""
      const w=world();
      w.server.plan['/api/workspace/boards/board_a/presentation-sources']={status:500,body:{error:{code:'workspace_failed',message:'boum'}}};
      await openArtifacts(w);
      const failed=w.html();
      seed(w,[group()]);
      await w.act('retry',{slot:'presentations'});
      const recovered=w.html();
      w.server.plan['/api/workspace/boards/board_a/presentation-sources']='hang';
      w.S.artifacts.presentations.status='idle';
      const pending=w.manager.act('retry',{slot:'presentations'});await settle();
      const loading=w.html();w.timers.forEach(fn=>fn());await settle();await pending;
      out({failed,recovered,loading,after:w.html(),waiting:w.S.artifacts.presentations.status});
    """)
    failed = _text(seen["failed"])
    assert "workspace_failed" in failed and 'data-slot="presentations"' in seen["failed"]
    assert "Atelier" in _text(seen["recovered"])
    assert "Lecture des présentations" in _text(seen["loading"])
    assert seen["waiting"] == "error", "a hung read ends on a said error, never forever"


def test_server_text_is_escaped_and_a_non_board_scope_hides_and_forgets_the_groups(tmp_path):
    seen = run_node(tmp_path, SEED + r"""
      const w=world();
      seed(w,[group({source:{exists:true,title:'<img src=x onerror=alert(1)>',engine:'<b>x</b>',revision:2,variant_revisions:{}}})]);
      await openArtifacts(w);
      const html=w.html();
      await w.act('artifacts-filter',{scope:'session',id:'jsess_open'});
      out({html,session:w.html(),state:w.S.artifacts.presentations.status,
        calls:w.server.calls.filter(c=>c.path.includes('board_a/presentation-sources')).length});
    """)
    assert "<img" not in seen["html"] and "&lt;img" in seen["html"]
    assert "<b>x</b>" not in seen["html"]
    assert "Présentations de «" not in seen["session"] and seen["state"] == "idle"
    assert seen["calls"] == 1


def test_actualiser_rereads_the_groups_so_nothing_is_kept_in_the_page(tmp_path):
    seen = run_node(tmp_path, SEED + r"""
      const w=world();seed(w,[group()]);
      await openArtifacts(w);
      seed(w,[group({},{stale:true})]);
      await w.act('refresh');
      out({html:w.html(),reads:w.server.calls.filter(c=>c.path.includes('board_a/presentation-sources')).length});
    """)
    assert "Source modifiée depuis" in _text(seen["html"]) and seen["reads"] == 2


def test_a_board_change_forgets_the_previous_boards_groups_before_its_own_read_arrives(tmp_path):
    seen = run_node(tmp_path, SEED + r"""
      const w=world();seed(w,[group()]);
      await openArtifacts(w);
      const first=w.html();
      w.server.plan['/api/workspace/boards/board_b/presentation-sources']='hang';
      const pending=w.manager.act('goto',{view:'artifacts',scope:'board',id:'board_b'});await settle();
      const during=w.html(),status=w.S.artifacts.presentations.status,data=w.S.artifacts.presentations.data;
      w.timers.forEach(fn=>fn());await settle();await pending;
      out({first,during,status,data,after:w.html()});
    """)
    assert "Atelier" in _text(seen["first"]) and "Présentations de « Projet A »" in _text(seen["first"])
    during = seen["during"]
    assert seen["status"] == "loading" and seen["data"] is None
    assert "Atelier" not in _text(during) and 'data-act="source-open"' not in during, "Board A's groups are gone"
    assert "Lecture des présentations de « Projet B »" in _text(during), "the wait names the Board being read"
    assert "Atelier" not in _text(seen["after"]), "a read that ended in error never brings Board A back"


def test_a_disabled_open_button_says_why_in_visible_text_linked_by_aria_describedby(tmp_path):
    seen = run_node(tmp_path, SEED + r"""
      const w=world();
      seed(w,[group({source:{exists:false}},{stale:null}),group({presentation_id:'pst_'+'9'.repeat(32),source:{exists:null,unreadable:'x'}},{stale:null,artifact_id:'jart_ps_other'})]);
      await openArtifacts(w);out({html:w.html()});
    """)
    html = seen["html"]
    import re
    ids = re.findall(r'<button aria-describedby="(wspWhy-[^"]+)"[^>]*disabled', html)
    assert len(ids) == 4 and len(set(ids)) == 4
    for one in ids:
        assert f'id="{one}"' in html
    text = _text(html)
    assert "Source supprimée : rien à ouvrir." in text and "Source illisible : impossible de l’ouvrir." in text


def test_a_failed_render_shows_its_error_code_and_many_sources_are_capped_with_show_more(tmp_path):
    seen = run_node(tmp_path, SEED + r"""
      const w=world();
      const many=[];for(let i=0;i<120;i+=1)many.push(group({presentation_id:'pst_'+String(i).padStart(32,'0'),source_ref:'presentation:pst_'+String(i).padStart(32,'0')},
        {artifact_id:'jart_s'+i,renders:i===0?[{artifact_id:'jart_'+'f'.repeat(32),kind:'presentation_pdf',state:'failed',format:'pdf',error_code:'render_failed',size_bytes:null,board_ids:['board_a']}]:[]}));
      seed(w,many);await openArtifacts(w);
      const capped=w.html();
      await w.act('presentations-more');await w.act('presentations-more');
      out({capped,all:w.html()});
    """)
    assert seen["capped"].count('class="wsp-psrc"') == 50 and "50 sources affichées sur 120" in _text(seen["capped"])
    assert "render_failed" in _text(seen["capped"]) and "Échoué" in _text(seen["capped"])
    assert seen["all"].count('class="wsp-psrc"') == 120 and "sources affichées" not in _text(seen["all"])


def test_a_refused_open_notice_is_a_live_alert_and_is_brought_into_view():
    source = (MODULE_PATH_FOR_TEXT := __import__("pathlib").Path(__file__).resolve().parents[2] / "jarvis" / "runtime"
              / "control_center_workspace.js").read_text(encoding="utf-8")
    assert "S.notice!==lastNotice" in source and "note.scrollIntoView({block:'nearest'})" in source
    assert "role=\"${n.tone==='bad'?'alert':'status'}\"" in source


# ------------------------------------------------------------------ Export (Remotion Slice 16)

RENDER_JOBS = "/api/local-capabilities/remotion/render/jobs"
EXPORT_SEED = r"""
const SNAPID='jart_ps_'+'a'.repeat(32)+'_'+'b'.repeat(32)+'_p1_v1_a1';
const JOBS='/api/local-capabilities/remotion/render/jobs',JOBID='rj_0123456789ab';
const job=(over)=>Object.assign({job_id:JOBID,artifact_id:'jart_'+'e'.repeat(32),snapshot_id:SNAPID,state:'queued',phase:'queued',format:'mp4',
  frames_done:0,frames_total:60,percent:0,elapsed_s:0,timeout_s:360,queue_position:null,cancel_requested:false,can_cancel:true,error_code:null,error_detail:null},over||{});
/* Un gestionnaire dont les minuteries sont tenues à la main : une interrogation par `step()`. */
const exporter=(over)=>{
  const w=world(over);const timers=[];
  const client=W.createClient({fetchImpl:w.server.fetch,setTimer:()=>1,clearTimer:()=>{}});
  const logs=[];
  const manager=W.createManager({client,log:(level,event,data)=>logs.push({level,event,data}),setTimer:(fn)=>{timers.push(fn);return timers.length}});
  const S=manager.state;
  const step=async()=>{const fn=timers.shift();if(fn)fn();await settle()};
  const posts=()=>w.server.calls.filter(c=>c.method==='POST');
  return {w,manager,S,logs,timers,step,posts,html:()=>W.panelHtml(S),
    async openBoard(){seed(w,[group()]);manager.open();await settle();await manager.act('view',{view:'artifacts'});await settle();
      await manager.act('artifacts-filter',{scope:'board',id:'board_a'});await settle()},
    start(format){const p=manager.act('export-start',{snapshot:SNAPID,format:format||'mp4'});return p}};
};
"""


def test_the_export_form_is_offered_only_for_a_complete_remotion_copy(tmp_path):
    seen = run_node(tmp_path, SEED + EXPORT_SEED + r"""
      const e=exporter();seed(e.w,[group(),
        group({presentation_id:'pst_'+'d'.repeat(32),source_ref:'presentation:pst_'+'d'.repeat(32)},{artifact_id:'jart_ps_failed',state:'failed',error_code:'package_failed',renders:[]}),
        group({presentation_id:'pst_'+'c'.repeat(32),source_ref:'presentation:pst_'+'c'.repeat(32)},{artifact_id:'jart_ps_html',engine:'slidecar',renders:[]})]);
      e.manager.open();await settle();await e.manager.act('view',{view:'artifacts'});await settle();await e.manager.act('artifacts-filter',{scope:'board',id:'board_a'});await settle();
      out({html:e.html()});
    """)
    html, text = seen["html"], _text(seen["html"])
    assert html.count('data-form="export-start"') == 1 and f'name="snapshot" value="jart_ps_{"a" * 32}_{"b" * 32}_p1_v1_a1"' in html
    assert "MP4 (vidéo)" in text and "Image (PNG)" in text and "PDF (pages-images, non éditable)" in text
    assert "Exporter" in text and "Slidecar n’exporte pas" in text
    assert 'value="mp4"' in html and 'value="still"' in html and 'value="pdf"' in html


def test_starting_an_export_posts_the_exact_body_then_shows_what_runs_for_how_long_and_how_to_stop(tmp_path):
    seen = run_node(tmp_path, SEED + EXPORT_SEED + r"""
      const e=exporter();await e.openBoard();
      e.w.server.plan[JOBS]={status:202,body:{job:job()}};
      const p=e.start('mp4');await settle();
      const starting=e.html();
      const waitingDuring=e.manager.waiting();
      e.w.server.plan[JOBS+'/'+JOBID]={status:200,body:{job:job({state:'running',phase:'rendering',frames_done:12,percent:20,elapsed_s:4,can_cancel:true})}};
      await e.step();
      const running=e.html();
      e.w.server.plan[JOBS+'/'+JOBID]={status:200,body:{job:job({state:'queued',phase:'queued',queue_position:2})}};
      await e.step();
      const queued=e.html();
      out({starting,waitingDuring,running,queued,posts:e.posts(),timers:e.timers.length});
    """)
    assert seen["posts"][0]["path"] == RENDER_JOBS and seen["posts"][0]["body"] == {"snapshot_id": f"jart_ps_{'a' * 32}_{'b' * 32}_p1_v1_a1", "format": "mp4"}
    start = _text(seen["starting"])
    assert "Export MP4 en cours" in start and seen["waitingDuring"] is True
    assert 'data-wsp-since="' in seen["starting"] and 'role="status"' in seen["starting"] and 'aria-live="polite"' in seen["starting"]
    assert 'data-form="export-start"' not in seen["starting"], "no second export of the same copy while one is running"
    run = _text(seen["running"])
    assert "Export MP4 en cours" in run and "Rendu des images" in run and "12/60 images (20 %)" in run and "délai 6 min au plus" in run
    assert 'data-act="export-cancel"' in seen["running"] and "Annuler l’export" in run and 'data-wsp-since="' in seen["running"]
    assert "2e en file" in _text(seen["queued"]) and "En file d’attente" in _text(seen["queued"])


def test_a_finished_export_reads_the_presentations_again_and_a_failure_says_its_code_and_detail(tmp_path):
    seen = run_node(tmp_path, SEED + EXPORT_SEED + r"""
      const e=exporter();await e.openBoard();
      e.w.server.plan[JOBS]={status:202,body:{job:job()}};
      e.start('mp4');await settle();
      const before=e.w.server.calls.filter(c=>c.path.includes('presentation-sources')).length;
      e.w.server.plan[JOBS+'/'+JOBID]={status:200,body:{job:job({state:'complete',phase:'complete',percent:100,frames_done:60})}};
      await e.step();await settle();
      const done=e.html();const after=e.w.server.calls.filter(c=>c.path.includes('presentation-sources')).length;
      const status1=e.S.exports[SNAPID].status;
      await e.manager.act('export-dismiss',{snapshot:SNAPID});
      const dismissed=e.html();
      e.w.server.plan[JOBS]={status:202,body:{job:job({job_id:'rj_ffffffffffff'})}};
      e.start('pdf');await settle();
      e.w.server.plan[JOBS+'/rj_ffffffffffff']={status:200,body:{job:job({job_id:'rj_ffffffffffff',state:'failed',phase:'failed',error_code:'presentation_render_timeout',error_detail:'the render exceeded its 360 s limit'})}};
      await e.step();await settle();
      const failed=e.html();
      out({before,after,done,status1,dismissed,failed,warned:e.logs.filter(l=>l.level==='warn').map(l=>l.event)});
    """)
    assert seen["after"] == seen["before"] + 1 and seen["status1"] == "done", "the render list is read from the server again"
    assert "Export terminé" in _text(seen["done"]) and "jart_" + "e" * 32 in seen["done"]
    assert 'data-form="export-start"' in seen["dismissed"] and "Export terminé" not in _text(seen["dismissed"])
    failed = _text(seen["failed"])
    assert "Export échoué" in failed and "presentation_render_timeout" in failed and "the render exceeded its 360 s limit" in failed
    assert "workspace.export_finished" in seen["warned"], "a failed export is logged as a warning, not only shown"


def test_cancel_posts_to_the_job_and_shows_cancelling_until_core_says_it_is_done(tmp_path):
    seen = run_node(tmp_path, SEED + EXPORT_SEED + r"""
      const e=exporter();await e.openBoard();
      e.w.server.plan[JOBS]={status:202,body:{job:job({state:'running',phase:'rendering'})}};
      e.start('mp4');await settle();
      e.w.server.plan[JOBS+'/'+JOBID+'/cancel']={status:200,body:{job:job({state:'running',phase:'rendering',cancel_requested:true,can_cancel:false})}};
      await e.manager.act('export-cancel',{snapshot:SNAPID});await settle();
      const cancelling=e.html();
      e.w.server.plan[JOBS+'/'+JOBID]={status:200,body:{job:job({state:'cancelled',phase:'cancelled',error_code:'presentation_render_cancelled',error_detail:'cancelled by the user'})}};
      await e.step();await settle();
      out({cancelling,final:e.html(),posts:e.posts().map(c=>c.path)});
    """)
    assert seen["posts"] == [RENDER_JOBS, f"{RENDER_JOBS}/rj_0123456789ab/cancel"]
    assert "Annulation…" in _text(seen["cancelling"]) and 'data-act="export-cancel"' not in seen["cancelling"]
    assert "Export annulé" in _text(seen["final"]) and "presentation_render_cancelled" in seen["final"]


def test_a_refused_request_and_a_lost_job_are_said_never_swallowed(tmp_path):
    seen = run_node(tmp_path, SEED + EXPORT_SEED + r"""
      let e=exporter();await e.openBoard();
      e.w.server.plan[JOBS]={status:409,body:{error:{code:'presentation_render_runtime_unavailable',message:'the Remotion capability is not_installed: install or repair it first'}}};
      await e.start('mp4');await settle();
      const refused=e.html();const refusedLogs=e.logs.filter(l=>l.event==='workspace.export_failed');
      e=exporter();await e.openBoard();
      e.w.server.plan[JOBS]={status:202,body:{job:job({state:'running',phase:'rendering'})}};
      e.start('mp4');await settle();
      e.w.server.plan[JOBS+'/'+JOBID]='network';
      await e.step();const once=e.html();await e.step();await e.step();await settle();
      const lost=e.html();
      out({refused,refusedLogs,once,lost,status:e.S.exports[SNAPID].status,lostLogs:e.logs.filter(l=>l.event==='workspace.export_lost'||l.event==='workspace.export_poll_failed').length});
    """)
    refused = _text(seen["refused"])
    assert "Export impossible" in refused and "presentation_render_runtime_unavailable" in refused and "not_installed" in refused and 'data-form="export-start"' in seen["refused"]
    assert seen["refusedLogs"][0]["data"]["code"] == "presentation_render_runtime_unavailable"
    assert "lecture de l’état en échec (1/3)" in _text(seen["once"])
    assert seen["status"] == "error" and "Export impossible" in _text(seen["lost"]) and seen["lostLogs"] == 4  # three failed reads, then the loss


def test_closing_the_panel_stops_the_polling_and_reopening_resumes_it(tmp_path):
    seen = run_node(tmp_path, SEED + EXPORT_SEED + r"""
      const e=exporter();await e.openBoard();
      e.w.server.plan[JOBS]={status:202,body:{job:job({state:'running',phase:'rendering'})}};
      e.start('mp4');await settle();
      e.w.server.plan[JOBS+'/'+JOBID]={status:200,body:{job:job({state:'running',phase:'rendering',frames_done:5})}};
      await e.step();
      const polls=()=>e.w.server.calls.filter(c=>c.method==='GET'&&c.path.endsWith(JOBID)).length;
      const before=polls();
      e.manager.close();await e.step();await settle();
      const whileClosed=polls();
      e.manager.open();await settle();await e.step();await settle();
      out({before,whileClosed,resumed:polls(),running:e.S.exports[SNAPID].status});
    """)
    assert seen["whileClosed"] == seen["before"] and seen["resumed"] == seen["before"] + 1 and seen["running"] == "running"


def test_renders_show_what_they_are_a_preview_and_that_they_are_flat(tmp_path):
    seen = run_node(tmp_path, SEED + r"""
      const r=(kind,format,over)=>Object.assign({artifact_id:'jart_'+kind.length.toString(16).repeat(32).slice(0,32),kind,state:'complete',format,size_bytes:2048,board_ids:['board_a'],
        width:1280,height:720,duration_ms:2000,scene_id:'pss_000000000001',settings_sha256:'f'.repeat(64),flat:true},over||{});
      const w=world();seed(w,[group({},{renders:[r('presentation_video','mp4'),r('presentation_still','still',{duration_ms:null}),r('presentation_pdf','pdf',{duration_ms:null}),
        r('presentation_video','mp4',{artifact_id:'jart_'+'9'.repeat(32),state:'pending',size_bytes:null,flat:null,width:null,height:null,duration_ms:null})]})]);
      await openArtifacts(w);out({html:w.html()});
    """)
    html, text = seen["html"], _text(seen["html"])
    assert html.count("<video ") == 1 and 'preload="none"' in html and "controls" in html, "a video never loads before the gesture"
    assert html.count("<img ") == 1 and 'loading="lazy"' in html and html.count('class="wsp-thumb"') == 2
    assert "Ouvrir le PDF" in text and 'target="_blank" rel="noopener"' in html
    assert html.count("/payload") == 3, "the pending render has no preview"
    assert "1280×720" in text and "2.0 s" in text and "scène pss_000000000001" in text
    assert html.count("export à plat : non éditable, l’origine éditable est la source ci-dessus") == 3
    assert f"empreinte {'f' * 64}" in html


def test_the_page_may_call_the_render_routes_and_nothing_near_them(tmp_path):
    seen = run_node(tmp_path, SEED + r"""
      const J='/api/local-capabilities/remotion/render/jobs';
      const ok=[['POST',J],['POST',J+'/rj_0123456789ab/cancel'],['GET',J+'/rj_0123456789ab']];
      const no=[['GET',J],['POST',J+'?x=1'],['POST',J+'/rj_0123456789ab'],['DELETE',J+'/rj_0123456789ab'],['PUT',J],['POST',J+'/a/b/cancel'],
        ['POST','/api/local-capabilities/remotion/render'],['POST','/api/local-capabilities/remotion/studio/open'],['GET','/api/local-capabilities/remotion'],
        ['POST','/api/local-capabilities/remotion/install'],['POST',J+'/../install'],['POST',J+'/%2e%2e/cancel'],['GET',J+'/rj_1?x=1']];
      out({ok:ok.map(([m,p])=>W.allowed(m,p)),no:no.map(([m,p])=>W.allowed(m,p)),memory:W.allowed('POST','/api/workspace/boards/board_a/memory/write'),
        other:W.allowed('POST','/api/workspace/boards/board_a/artifacts/x')});
    """)
    assert seen["ok"] == [True, True, True] and not any(seen["no"]) and seen["memory"] is True and seen["other"] is False
