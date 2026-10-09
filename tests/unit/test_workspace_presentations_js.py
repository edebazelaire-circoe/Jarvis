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
