"""Gestionnaire Sessions & Boards, exécuté par node (board-memory-workspace-inspector, Slice 07).

Le module est le fichier même que `ControlCenter.index` insère. Seuls le réseau
(un serveur double qui parle les formes réelles de `/api/workspace/*`,
`/api/boards`, `/api/sessions/current`, `/api/artifacts/*`) et les minuteries
sont des doubles. Ce que ce fichier épingle :

- la vue d'ensemble est **lue** (Session, Board actif, Context actif, liaison au
  premier plan, problèmes de données), jamais supposée ;
- les listes sont paginées au curseur rendu par le serveur ;
- chaque refus codé est affiché avec son code, son statut HTTP et « Réessayer » ;
  délai, réseau coupé et réponse illisible aussi ;
- supprimer passe par une confirmation **dans le panneau** (aucun envoi avant),
  qui nomme le chemin et le Board, exige « avec son contenu » pour un dossier
  non vide, puis relit l'arborescence ;
- un Board archivé n'a **aucune** commande d'écriture ;
- `truncated` se dit « Recherche incomplète », jamais « aucune correspondance » ;
- la bascule passe par le contrôle Boards (jamais une route à soi), puis relit ;
- la page servie porte le bouton `WSP`, la vue et le module.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.runtime.control_center import WORKSPACE_SCRIPT_FILE, WORKSPACE_SCRIPT_MARKER, ControlCenter

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
PAGE = RUNTIME / "control_center.html"
MODULE = RUNTIME / WORKSPACE_SCRIPT_FILE

WORLD = r"""
const W=require(MODULE_PATH);
const out=v=>process.stdout.write(JSON.stringify(v));
const settle=async()=>{for(let i=0;i<40;i+=1)await new Promise(r=>setImmediate(r))};

const SA='jsess_open',SC='jsess_closed',BA='board_a',BB='board_b',BX='board_old';
const binding=(session,board,lifecycle,over)=>Object.assign({jarvis_session_id:session,board_id:board,
  conversation_id:`conv-${board}`,agent_cli:'claude',agent_session_id:`agent-${board}`,lifecycle,
  created_at:'2026-10-02T09:00:00+00:00',last_active_at:'2026-10-02T10:00:00+00:00',status:'open'},over||{});
const boardRow=(id,title,over)=>Object.assign({board_id:id,title,status:'active',board_kind:'empty',
  created_at:'2026-09-01T09:00:00+00:00',updated_at:'2026-10-01T09:00:00+00:00',last_opened_at:'2026-10-02T09:00:00+00:00',
  artifact_refs:[],interaction_mode:'assistant'},over||{});

/* Le serveur double. `plan[path]` force une réponse : `{status, body}`, 'hang', 'network', 'html'. */
const makeServer=()=>{
  const s={calls:[],plan:{},files:{'summary.md':'# A\nDécisions\n','notes/plan.md':'étape 1\n','notes/old.md':'vieux\n'},
    boards:[boardRow(BA,'Projet A',{board_kind:'meeting'}),boardRow(BB,'Projet B'),boardRow(BX,'Ancien',{status:'archived',artifact_refs:['legacy:ref-1']})],
    active:BB,sessions:[],treeTruncated:false};
  for(let i=0;i<25;i+=1)s.sessions.push({jarvis_session_id:i===0?SA:`jsess_${String(i).padStart(2,'0')}`,status:i===0?'open':'closed',open:i===0,
    started_at:`2026-09-${String(28-i%27).padStart(2,'0')}T09:00:00+00:00`,ended_at:i===0?null:'2026-09-29T09:00:00+00:00',
    end_reason:i===0?null:'new_session',active_board_id:BA,visited_board_ids:[BA,BB]});
  s.sessions[1].jarvis_session_id=SC;
  s.events=[];for(let i=1;i<=60;i+=1)s.events.push({seq:i,kind:i===60?'board.memory.written':'context.created',occurred_at:'2026-10-02T09:00:00+00:00',
    jarvis_session_id:SA,context_id:null,artifact_ids:[],capture_ids:[],data:i===60?{board_id:BA,path:'notes/plan.md',mode:'create',size:8}:{origin:'protocol'}});
  const json=(status,body)=>({ok:status<400,status,text:async()=>JSON.stringify(body)});
  const err=(status,code,message,extra)=>json(status,{error:Object.assign({code,message},extra||{})});
  const tree=id=>{
    const entries=[];const dirs=new Set();
    for(const p of Object.keys(s.files).sort()){const parts=p.split('/');if(parts.length>1&&!dirs.has(parts[0])){dirs.add(parts[0]);entries.push({path:parts[0],kind:'directory',size:null,depth:1})}
      entries.push({path:p,kind:'file',size:s.files[p].length,depth:parts.length})}
    for(const d of (s.dirs||[]))if(!dirs.has(d))entries.push({path:d,kind:'directory',size:null,depth:1});
    return {board_id:id,locator:`boards/${id}/memory`,exists:true,path:'',entries,truncated:s.treeTruncated,skipped:0};
  };
  s.fetch=async(path,init)=>{
    const method=(init&&init.method)||'GET';
    const body=init&&init.body?JSON.parse(init.body):null;
    s.calls.push({method,path,body});
    const forced=s.plan[path]||s.plan[path.split('?')[0]];
    if(forced==='hang')return new Promise((_,reject)=>{if(init&&init.signal)init.signal.addEventListener('abort',()=>reject(new Error('aborted')))});
    if(forced==='network')throw new TypeError('Failed to fetch');
    if(forced==='html')return {ok:false,status:500,text:async()=>'<html>boom</html>'};
    if(forced)return json(forced.status,forced.body);
    const u=new URL('http://x'+path),p=u.pathname,qs=u.searchParams;
    if(p==='/api/boards')return json(200,{boards:s.boards,active_board_id:s.active});
    if(p==='/api/sessions/current')return json(200,{session:{jarvis_session_id:SA},binding:null});
    if(p==='/api/workspace/sessions'){
      const start=qs.get('cursor')?Number(qs.get('cursor')):0,limit=Number(qs.get('limit'));
      const next=start+limit<s.sessions.length?String(start+limit):null;
      return json(200,{sessions:s.sessions.slice(start,start+limit),next_cursor:next});
    }
    let m;
    if((m=p.match(/^\/api\/workspace\/sessions\/([^/]+)\/activity$/))){
      const start=qs.get('cursor')?Number(qs.get('cursor')):0,limit=Number(qs.get('limit'));
      return json(200,{jarvis_session_id:m[1],events:s.events.slice(start,start+limit),next_cursor:start+limit<s.events.length?String(start+limit):null});
    }
    if((m=p.match(/^\/api\/workspace\/sessions\/([^/]+)$/))){
      return json(200,{session:{jarvis_session_id:m[1],status:'open',started_at:'2026-10-02T09:00:00+00:00',active_board_id:s.active,visited_board_ids:[BA,s.active]},open:true,
        boards:[Object.assign({active:s.active===BA,visited:true,binding:binding(m[1],BA,s.active===BA?'foreground':'suspended')},boardRow(BA,'Projet A',{board_kind:'meeting'})),
          Object.assign({active:s.active===BB,visited:true,binding:binding(m[1],BB,s.active===BB?'foreground':'suspended')},boardRow(BB,'Projet B')),
          {board_id:'board_gone',active:false,visited:true,missing:true,binding:null}],
        contexts:{items:[{context_id:'jctx_1',status:'active',title:'Revue',workspace_ref:`sessions/${m[1]}/contexts/jctx_1`,activated_at:'2026-10-02T09:00:00+00:00'}],total:1,truncated:false,active_context_id:'jctx_1'},
        problems:[{code:'board_not_found',board_id:'board_gone',field:'visited_board_ids',message:'visited board board_gone is missing'}],
        speech_authority:{board_id:s.active,conversation_id:`conv-${s.active}`,jarvis_session_id:m[1]}});
    }
    if((m=p.match(/^\/api\/workspace\/boards\/([^/]+)$/))){
      const b=s.boards.find(x=>x.board_id===m[1]);
      if(!b)return err(404,'board_not_found',`board ${m[1]} not found`);
      return json(200,{board:b,active:b.board_id===s.active,sessions:{items:[Object.assign(binding(SA,b.board_id,'suspended'),{session_status:'open',active_in_session:false})],truncated:false},
        artifacts:{linked:2},legacy_artifact_refs:{items:b.artifact_refs,legacy:true,note:'opaque legacy references'},
        memory:{locator:`boards/${b.board_id}/memory`,exists:true,entries:4,files:3,directories:1,bytes:60,truncated:false,summary:{present:true,path:'summary.md',size:14},skipped:0}});
    }
    if((m=p.match(/^\/api\/workspace\/boards\/([^/]+)\/memory\/tree$/)))return json(200,tree(m[1]));
    if((m=p.match(/^\/api\/workspace\/boards\/([^/]+)\/memory\/read$/))){
      const f=qs.get('path');if(!(f in s.files))return err(404,'memory_not_found',`${f}: not found`);
      return json(200,{board_id:m[1],path:f,text:s.files[f],offset:0,next_offset:s.files[f].length,size:s.files[f].length,eof:true,sha256:'a'.repeat(64)});
    }
    if((m=p.match(/^\/api\/workspace\/boards\/([^/]+)\/memory\/search$/)))
      return json(200,{board_id:m[1],query:qs.get('q'),matches:[],files_scanned:500,files_skipped:3,truncated:true});
    if((m=p.match(/^\/api\/workspace\/boards\/([^/]+)\/memory\/(write|mkdir|move|delete)$/))){
      const b=s.boards.find(x=>x.board_id===m[1]);
      if(b.status==='archived')return err(409,'board_archived',`board ${m[1]} is archived: its memory and links are read-only`);
      const op=m[2];
      if(op==='write'){
        if(body.mode==='create'&&body.path in s.files)return err(409,'memory_exists',`${body.path}: exists`);
        if(body.mode==='replace'&&body.expected_sha256&&s.conflict)return err(409,'memory_conflict',`${body.path}: changed since read`);
        const created=!(body.path in s.files);s.files[body.path]=body.mode==='append'?(s.files[body.path]||'')+body.content:body.content;
        return json(created?201:200,{board_id:m[1],path:body.path,mode:body.mode,created,bytes:body.content.length,size:s.files[body.path].length,sha256:'b'.repeat(64),activity_seq:61});
      }
      if(op==='mkdir'){(s.dirs=s.dirs||[]).push(body.path);return json(201,{board_id:m[1],path:body.path,activity_seq:62})}
      if(op==='move'){s.files[body.to]=s.files[body.from];delete s.files[body.from];return json(200,{board_id:m[1],from:body.from,to:body.to,activity_seq:63})}
      const victims=Object.keys(s.files).filter(k=>k===body.path||k.startsWith(body.path+'/'));
      if(victims.length>1&&!body.recursive)return err(409,'memory_conflict',`${body.path}: folder not empty`);
      for(const v of victims)delete s.files[v];
      return json(200,{board_id:m[1],path:body.path,removed:victims.length+(victims[0]===body.path?0:1),activity_seq:64});
    }
    if(p==='/api/workspace/artifacts'){
      const start=qs.get('cursor')?Number(qs.get('cursor')):0;
      const all=[];for(let i=0;i<23;i+=1)all.push({artifact_id:`jart_${String(i).padStart(32,'0')}`,kind:i%2?'transcript':'screenshot',state:'complete',
        created_at:'2026-10-02T09:00:00+00:00',jarvis_session_id:SA,context_id:'jctx_1',preview:`aperçu ${i}`,size_bytes:null});
      return json(200,{artifacts:all.slice(start,start+20),next_cursor:start+20<all.length?String(start+20):null});
    }
    if((m=p.match(/^\/api\/workspace\/artifacts\/([^/]+)\/relations$/)))
      return json(200,{artifact:{artifact_id:m[1]},origins:[{artifact_id:m[1],relation:'derived_from',origin_artifact_id:'jart_origin'}],dependents:[],
        boards:{items:[{board_id:BA,artifact_id:m[1],origin:'active_board',linked_at:'2026-10-02T09:00:00+00:00'},{board_id:BB,artifact_id:m[1],origin:'explicit',linked_at:'2026-10-02T09:00:00+00:00'}],truncated:false}});
    if((m=p.match(/^\/api\/artifacts\/([^/]+)$/)))
      return json(200,{artifact:{artifact_id:m[1],kind:'transcript',state:'complete',source:'capture',jarvis_session_id:SA,context_id:'jctx_1',
        created_at:'2026-10-02T09:00:00+00:00',payload_ref:null,text:'bonjour',text_truncated:false,text_chars:7}});
    return err(404,'not_stubbed',`${method} ${path}`);
  };
  return s;
};
const world=(over)=>{
  const server=makeServer();
  const logs=[];
  const timers=[];
  const o=over||{};
  const client=W.createClient({fetchImpl:server.fetch,setTimer:(fn,ms)=>{timers.push(fn);return timers.length},clearTimer:()=>{}});
  const manager=W.createManager({client,log:(level,event,data)=>logs.push({level,event,data}),switchBoard:o.switchBoard||null});
  const html=()=>W.panelHtml(manager.state);
  const posts=()=>server.calls.filter(c=>c.method!=='GET');
  return {server,manager,S:manager.state,html,logs,timers,posts,act:async(n,d)=>{const r=manager.act(n,d);await settle();await r;await settle()}};
};
"""


def run_node(tmp_path: Path, source: str, name: str = "wsp") -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"workspace-{name}.cjs"
    script.write_text(
        f"const MODULE_PATH={json.dumps(str(MODULE))};\n" + WORLD
        + "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8",
                          timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


# ------------------------------------------------------------------ lectures


def test_overview_reads_session_board_context_and_foreground_binding_from_the_server(tmp_path):
    seen = run_node(tmp_path, r"""
      const w=world();
      w.manager.open();await settle();
      out({html:w.html(),calls:w.server.calls.map(c=>c.method+' '+c.path)});
    """)
    html, text = seen["html"], _text(seen["html"])
    assert "GET /api/sessions/current" in seen["calls"]
    assert "GET /api/workspace/sessions/jsess_open" in seen["calls"]
    assert "GET /api/workspace/boards/board_b" in seen["calls"], "the active Board's memory summary is read"
    assert all(c.startswith("GET ") for c in seen["calls"]), "opening never writes"
    assert "Session courante" in text and "jsess_open" in text
    board = html[html.index("Board actif</h3>"):html.index("Context actif</h3>")]
    assert "Projet B" in board and "boards/board_b/memory" in board and "summary.md" in board
    assert "Revue" in text and "sessions/jsess_open/contexts/jctx_1" in text
    fg = html[html.index("Liaison au premier plan</h3>"):]
    assert "Premier plan" in fg and "conv-board_b" in fg and "agent-board_b" in fg and "claude" in fg
    assert "Autorité de parole : cette liaison" in _text(fg)
    assert "1 problème de données" in text and "board_not_found" in text and "Absent" in text


def test_sessions_are_paged_by_the_servers_cursor_and_the_ledger_shows_board_rows(tmp_path):
    seen = run_node(tmp_path, r"""
      const w=world();
      await w.act('view',{view:'sessions'});
      const first={count:w.S.sessions.items.length,next:w.S.sessions.next,html:w.html()};
      await w.act('sessions-more');
      const second={count:w.S.sessions.items.length,next:w.S.sessions.next,html:w.html()};
      await w.act('session-toggle',{id:'jsess_open'});
      const ledger={count:w.S.session.activity.items.length,html:w.html()};
      await w.act('activity-more');
      out({first,second,ledger,after:w.S.session.activity.items.length,
        calls:w.server.calls.filter(c=>/workspace\/sessions(\?|\/jsess_open\/activity)/.test(c.path)).map(c=>c.path)});
    """)
    assert seen["first"]["count"] == 20 and seen["first"]["next"] == "20"
    assert "Charger la suite" in seen["first"]["html"] and "Ouverte" in seen["first"]["html"]
    assert seen["second"]["count"] == 25 and seen["second"]["next"] is None
    assert "25 affichés · fin de la liste." in _text(seen["second"]["html"])
    assert seen["calls"][:2] == ["/api/workspace/sessions?limit=20", "/api/workspace/sessions?limit=20&cursor=20"]
    assert seen["ledger"]["count"] == 50 and seen["after"] == 60
    assert "/api/workspace/sessions/jsess_open/activity?limit=50&cursor=50" in seen["calls"]
    ledger = _text(seen["ledger"]["html"])
    assert "Boards et liaisons" in ledger and "conv-board_a" in ledger and "Suspendu" in ledger


def test_boards_list_includes_archived_ones_with_their_kind_and_legacy_refs_labelled(tmp_path):
    seen = run_node(tmp_path, r"""
      const w=world();
      w.manager.open();await settle();
      await w.act('view',{view:'boards'});
      const all=w.html();
      await w.act('board-filter',{filter:'archived'});
      const archived=w.html();
      await w.act('board-toggle',{id:'board_old'});
      out({all,archived,detail:w.html(),path:w.server.calls.find(c=>c.path.startsWith('/api/boards')).path});
    """)
    assert seen["path"] == "/api/boards?include_archived=true"
    text = _text(seen["all"])
    assert "Projet A" in text and "Réunion" in text and "Ancien" in text and "Archivé" in text
    assert "Actif maintenant" in text and text.index("Projet B") < text.index("Actif maintenant") < text.index("Ancien")
    assert "Projet A" not in _text(seen["archived"]) and "Ancien" in _text(seen["archived"])
    detail = _text(seen["detail"])
    assert "Références héritées (legacy)" in detail and "legacy:ref-1" in detail
    assert "boards/board_old/memory" in detail and "Basculer sur ce Board" not in detail, "archived: no switch offered"


def test_inspect_board_opens_the_boards_view_on_that_board_archived_included(tmp_path):
    """Slice 08 : « Inspecter » du contrôle Boards arrive ici (`inspect-board`)."""

    seen = run_node(tmp_path, r"""
      const w=world();
      w.manager.open();await settle();
      await w.act('view',{view:'boards'});
      await w.act('board-filter',{filter:'active'});
      await w.act('board-toggle',{id:'board_b'});
      const before=w.S.board.id;
      await w.act('view',{view:'memory'});
      await w.act('inspect-board',{id:'board_old'});
      const first={view:w.S.view,filter:w.S.boardFilter,id:w.S.board.id,status:w.S.board.detail.status,html:w.html()};
      await w.act('inspect-board',{id:'board_old'});
      const again={id:w.S.board.id,status:w.S.board.detail.status};
      out({before,first,again,posts:w.posts().length,
        reads:w.server.calls.filter(c=>c.path==='/api/workspace/boards/board_old').length,
        logged:w.logs.filter(l=>l.event==='workspace.inspect_board').map(l=>l.data)});
    """)
    assert seen["before"] == "board_b"
    first = seen["first"]
    assert first["view"] == "boards" and first["filter"] == "all", "an archived Board stays visible"
    assert first["id"] == "board_old" and first["status"] == "ok"
    text = _text(first["html"])
    assert "boards/board_old/memory" in text and "legacy:ref-1" in text
    assert 'class="wsp-row is-open is-archived"' in first["html"]
    assert seen["again"] == {"id": "board_old", "status": "ok"}, "inspecting twice never collapses the row"
    assert seen["reads"] == 2 and seen["posts"] == 0, "a read, never a write nor a switch"
    assert seen["logged"] == [{"board_id": "board_old"}, {"board_id": "board_old"}]


def test_the_browser_block_offers_open_board_to_the_boards_control():
    source = MODULE.read_text(encoding="utf-8")
    browser = source[source.index("(function installJarvisWorkspace(){"):]
    assert "window.JarvisWorkspace={open:openView,close:closeView,openBoard," in browser
    entry = browser[browser.index("function openBoard(id){"):browser.index("window.JarvisWorkspace=")]
    assert "manager.act('inspect-board'" in entry and "openView()" in entry


# ------------------------------------------------------------------ erreurs


def test_every_failure_shows_its_code_status_and_a_retry_that_recovers(tmp_path):
    seen = run_node(tmp_path, r"""
      const w=world();
      w.server.plan['/api/workspace/sessions']={status:503,body:{error:{code:'core_unreachable',message:'Core did not answer GET /v1/workspace/sessions in time'}}};
      await w.act('view',{view:'sessions'});
      const refused=w.html();
      delete w.server.plan['/api/workspace/sessions'];
      await w.act('retry',{slot:'sessions'});
      const recovered=w.S.sessions.items.length;
      w.server.plan['/api/workspace/boards/board_a/memory/tree']='network';
      await w.act('view',{view:'memory'});await w.act('memory-board',{board:'board_a'});
      const network=w.html();
      w.server.plan['/api/workspace/boards/board_a/memory/tree']='html';
      await w.act('retry',{slot:'tree'});
      const html500=w.html();
      w.server.plan['/api/workspace/boards/board_a/memory/tree']='hang';
      const pending=w.manager.act('retry',{slot:'tree'});await settle();
      const waiting=w.html();
      w.timers[w.timers.length-1]();await pending;await settle();
      const late=w.html();
      out({refused,recovered,network,html500,waiting,late,failed:w.logs.filter(l=>l.event.endsWith('_failed')).map(l=>l.data.code),
        status:W.statusView(w.S,Date.now())});
    """)
    refused = _text(seen["refused"])
    assert "Core ne répond pas" in refused and "core_unreachable · HTTP 503" in refused
    assert "Core did not answer GET /v1/workspace/sessions in time" in refused and "Réessayer" in refused
    assert seen["recovered"] == 20
    assert "Control Center injoignable" in _text(seen["network"]) and "Failed to fetch" in seen["network"]
    assert "http_500 · HTTP 500" in _text(seen["html500"]) and "&lt;html&gt;boom" in seen["html500"]
    assert "Lecture de l’arborescence…" in seen["waiting"] and "data-wsp-since" in seen["waiting"]
    late = _text(seen["late"])
    assert "Pas de réponse" in late and "aucune réponse en 35 s" in late and "timeout" in late
    assert seen["failed"] == ["core_unreachable", "network", "http_500", "timeout"]
    assert seen["status"]["tone"] == "bad" and seen["status"]["detail"] == "timeout"


# ------------------------------------------------------------------ mémoire


def test_delete_needs_the_in_panel_confirmation_and_rereads_the_tree(tmp_path):
    seen = run_node(tmp_path, r"""
      const w=world();
      w.manager.open();await settle();
      await w.act('view',{view:'memory'});await w.act('memory-board',{board:'board_a'});
      await w.act('memory-open',{path:'notes/plan.md'});
      await w.act('memory-delete-ask',{path:'notes/plan.md',kind:'file'});
      const asked={html:w.html(),posts:w.posts().length};
      await w.act('memory-cancel');
      const cancelled={html:w.html(),posts:w.posts().length};
      await w.act('memory-delete-ask',{path:'notes',kind:'directory'});
      const folder=w.html();
      const trees=w.server.calls.filter(c=>c.path.includes('/memory/tree')).length;
      await w.act('memory-delete-confirm',{recursive:true});
      out({asked,cancelled,folder,posts:w.posts(),after:w.html(),treesBefore:trees,
        treesAfter:w.server.calls.filter(c=>c.path.includes('/memory/tree')).length,file:w.S.memory.file.path});
    """)
    asked = seen["asked"]
    assert asked["posts"] == 0, "asking sends nothing"
    confirm = asked["html"][asked["html"].index('class="wsp-confirm"'):]
    assert 'role="alertdialog"' in asked["html"]
    assert "Supprimer définitivement le fichier ?" in _text(confirm)
    assert "notes/plan.md" in confirm and "« Projet A »" in confirm and "pas de corbeille" in confirm
    assert 'class="action small wsp-danger"' in confirm and "Annuler" in confirm
    assert seen["cancelled"]["posts"] == 0 and "wsp-confirm" not in seen["cancelled"]["html"]
    assert "Supprimer aussi ses 2 éléments (dossier non vide)" in _text(seen["folder"])
    assert seen["posts"] == [{"method": "POST", "path": "/api/workspace/boards/board_a/memory/delete",
                              "body": {"path": "notes", "recursive": True, "origin": "user"}}]
    after = _text(seen["after"])
    assert "« notes » supprimé définitivement · 3 éléments retirés · journal n° 64" in after
    assert "plan.md" not in after.split("Fichiers", 1)[1].split("Chercher", 1)[0]
    assert seen["treesAfter"] == seen["treesBefore"] + 1, "the tree is read back from the server"
    assert seen["file"] is None, "the open file was inside the deleted folder"


def test_create_replace_with_sha_and_a_conflict_kept_in_the_form(tmp_path):
    seen = run_node(tmp_path, r"""
      const w=world();
      w.manager.open();await settle();
      await w.act('view',{view:'memory'});await w.act('memory-board',{board:'board_a'});
      await w.act('memory-form',{kind:'create',path:''});
      const form=w.html();
      const save=w.manager.act('memory-save',{path:'notes/new.md',content:'bonjour'});
      const busy=w.html();
      const second=w.manager.act('memory-save',{path:'notes/other.md',content:'x'});
      await save;await second;await settle();
      const created=w.html();
      await w.act('memory-form',{kind:'replace',path:'notes/new.md'});
      const replaceForm=w.html();
      w.server.conflict=true;
      await w.act('memory-save',{content:'changé'});
      out({form,busy,created,replaceForm,conflict:w.html(),posts:w.posts().map(p=>p.body),formKept:!!w.S.memory.form});
    """)
    assert 'name="path"' in seen["form"] and "Nouveau fichier" in seen["form"] and "<textarea" in seen["form"]
    assert "Création…" in seen["busy"] and "disabled" in seen["busy"]
    assert seen["posts"][0] == {"path": "notes/new.md", "content": "bonjour", "mode": "create", "origin": "user"}
    assert len(seen["posts"]) == 2, "the second click during the first write sent nothing"
    assert "« notes/new.md » créé · 7 o écrits, 7 o au total · journal n° 61" in _text(seen["created"])
    assert "bonjour" in seen["replaceForm"] and "Protégé : refusé si le fichier a changé" in _text(seen["replaceForm"])
    assert seen["posts"][1] == {"path": "notes/new.md", "content": "changé", "mode": "replace",
                                "expected_sha256": "a" * 64, "origin": "user"}
    conflict = _text(seen["conflict"])
    assert "memory_conflict · HTTP 409" in conflict and "Remplacement impossible" not in conflict, "said once, in the form"
    assert seen["formKept"] is True and "Refusé : Conflit" in conflict


def test_an_archived_board_has_no_write_command_and_a_late_refusal_turns_it_read_only(tmp_path):
    seen = run_node(tmp_path, r"""
      const w=world();
      w.manager.open();await settle();
      await w.act('view',{view:'memory'});await w.act('memory-board',{board:'board_old'});
      await w.act('memory-open',{path:'summary.md'});
      w.manager.act('memory-form',{kind:'create',path:''});
      w.manager.act('memory-delete-ask',{path:'summary.md',kind:'file'});
      const archived={html:w.html(),form:w.S.memory.form,confirm:w.S.memory.confirm};
      /* Board archivé ailleurs après la lecture de la liste : le serveur refuse, la vue passe en lecture seule. */
      await w.act('view',{view:'memory'});await w.act('memory-board',{board:'board_a'});
      w.server.boards[0].status='archived';
      await w.act('memory-form',{kind:'mkdir',path:''});
      await w.act('memory-save',{path:'x'});
      out({archived,late:w.html(),readOnly:w.S.memory.archived,form:w.S.memory.form});
    """)
    html = seen["archived"]["html"]
    assert "Board archivé : mémoire en lecture seule." in _text(html)
    assert seen["archived"]["form"] is None and seen["archived"]["confirm"] is None
    for forbidden in ('data-act="memory-form"', 'data-act="memory-delete-ask"', "Nouveau fichier", "Supprimer"):
        assert forbidden not in html, forbidden
    assert "Décisions" in html, "reads stay allowed"
    late = _text(seen["late"])
    assert seen["readOnly"] is True and seen["form"] is None
    assert "board_archived · HTTP 409" in late and "Board archivé : mémoire en lecture seule." in late
    assert 'data-act="memory-form"' not in seen["late"]


def test_a_truncated_search_is_never_shown_as_nothing_found(tmp_path):
    seen = run_node(tmp_path, r"""
      const w=world();
      w.server.treeTruncated=true;
      await w.act('view',{view:'memory'});await w.act('memory-board',{board:'board_a'});
      await w.act('memory-search',{q:'décision',path:'notes'});
      out({html:w.html(),path:w.server.calls.find(c=>c.path.includes('/search')).path});
    """)
    text = _text(seen["html"])
    assert "Recherche incomplète" in text and "précisez le dossier" in text and "500 fichiers lus" in text
    assert "Aucune correspondance" not in text
    assert "Arborescence incomplète" in text
    assert seen["path"] == "/api/workspace/boards/board_a/memory/search?q=d%C3%A9cision&path=notes"


# ------------------------------------------------------------------ artefacts, bascule, garde


def test_artifacts_are_filtered_paged_and_show_provenance_and_board_links(tmp_path):
    seen = run_node(tmp_path, r"""
      const w=world();
      w.manager.open();await settle();
      await w.act('view',{view:'artifacts'});await w.act('artifacts-filter',{scope:'board',id:'board_a',kind:'transcript',since:'2026-10-01',until:'2026-10-02'});
      const first=w.S.artifacts.list.items.length;
      await w.act('artifacts-more');
      await w.act('artifact-toggle',{id:'jart_'+'0'.repeat(32)});
      out({first,total:w.S.artifacts.list.items.length,html:w.html(),
        calls:w.server.calls.filter(c=>c.path.includes('artifacts')).map(c=>c.path)});
    """)
    assert seen["first"] == 20 and seen["total"] == 23
    assert seen["calls"][0] == "/api/workspace/artifacts?board_id=board_b&limit=20", "opens on the active Board"
    assert seen["calls"][1] == ("/api/workspace/artifacts?board_id=board_a&kind=transcript"
                                "&since=2026-10-01T00%3A00%3A00Z&until=2026-10-02T23%3A59%3A59Z&limit=20")
    assert "&cursor=20" in seen["calls"][2]
    assert "/api/artifacts/jart_" + "0" * 32 + "?text_chars=2000" in seen["calls"]
    assert "/api/workspace/artifacts/jart_" + "0" * 32 + "/relations" in seen["calls"]
    text = _text(seen["html"])
    assert "derived_from" in text and "jart_origin" in text
    assert "Board actif à la création" in text and "Lien explicite" in text and "bonjour" in text


def test_switch_goes_through_the_boards_control_then_rereads_the_server(tmp_path):
    seen = run_node(tmp_path, r"""
      const asked=[];
      let w;
      w=world({switchBoard:async(id,title)=>{asked.push([id,title]);w.server.active=id;return {ok:true,message:''}}});
      w.manager.open();await settle();
      await w.act('view',{view:'boards'});
      await w.act('board-toggle',{id:'board_a'});
      const offered=w.html().includes('data-act="switch" data-board="board_a"');
      const reads=w.server.calls.length;
      await w.act('switch',{board:'board_a'});
      const ok={notice:w.S.notice,calls:w.server.calls.slice(reads).map(c=>c.method+' '+c.path)};
      const r=world({switchBoard:async()=>({ok:false,message:'L’agent du Board n’a pas pu démarrer.'})});
      r.manager.open();await settle();
      await r.act('switch',{board:'board_a'});
      out({asked,offered,ok,refused:r.S.notice,activeAfterRefusal:W.activeBoardId(r.S)});
    """)
    assert seen["offered"] is True
    assert seen["asked"] == [["board_a", "Projet A"]]
    assert not [c for c in seen["ok"]["calls"] if c.startswith("POST")], "the manager never posts a switch itself"
    assert "GET /api/sessions/current" in seen["ok"]["calls"] and "GET /api/boards?include_archived=true" in seen["ok"]["calls"]
    assert seen["ok"]["notice"] == {"tone": "ok", "text": "« Projet A » est le Board actif (confirmé par le serveur)."}
    assert seen["refused"]["tone"] == "bad"
    assert seen["refused"]["text"].startswith("Bascule vers « Projet A » non confirmée : « Projet B » reste actif.")
    assert seen["activeAfterRefusal"] == "board_b"


def test_the_client_refuses_every_route_outside_its_contract_before_the_network(tmp_path):
    seen = run_node(tmp_path, r"""
      const cases=[['GET','/api/workspace/sessions'],['GET','/api/boards?include_archived=true'],['GET','/api/sessions/current'],
        ['GET','/api/artifacts/jart_x?text_chars=2000'],['POST','/api/workspace/boards/b/memory/write'],
        ['POST','/api/boards/switch'],['POST','/api/sessions/new'],['GET','/api/settings'],['DELETE','/api/workspace/boards/b/artifacts/x'],
        ['POST','/api/workspace/boards/b/memory/write?x=1'],['GET','/api/workspace/boards/%2e%2e/memory/tree'],['GET','/api/artifacts/x/payload']];
      out(cases.map(([m,p])=>W.allowed(m,p)));
    """)
    assert seen == [True, True, True, True, True, False, False, False, False, False, False, False]
    source = MODULE.read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    for forbidden in ("window.confirm", "confirm(", "alert(", "prompt(", "/api/boards/switch", "localStorage"):
        assert forbidden not in code, forbidden
    core = code[: code.index("(function installJarvisWorkspace(){")]
    for forbidden in ("document.", "window.", "innerHTML"):
        assert forbidden not in core, f"pure part touches {forbidden}"


# ------------------------------------------------------------------ page servie


@pytest.mark.asyncio
async def test_the_served_page_carries_the_dock_button_the_view_and_the_module(tmp_path):
    center = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    html = (await center.index(None)).text
    assert WORKSPACE_SCRIPT_MARKER not in html
    assert "const JarvisWorkspaceCore=" in html
    assert html.index("installJarvisBoards") < html.index("const JarvisWorkspaceCore=")
    dock = html[html.index('<nav class="dock"'): html.index("</nav>", html.index('<nav class="dock"'))]
    button = re.search(r'<button id="openWorkspace"[^>]*>WSP</button>', dock).group(0)
    for attribute in ('title="Sessions &amp; Boards"', 'aria-haspopup="dialog"', 'aria-expanded="false"',
                      'aria-controls="workspaceManager"'):
        assert attribute in button
    view = html[html.index('<section class="wsp"'): html.index("</section>", html.index('<section class="wsp"'))]
    for attribute in ('role="dialog"', 'aria-modal="true"', 'aria-labelledby="wspTitle"', 'aria-describedby="wspHelp"', " hidden>"):
        assert attribute in view
    assert 'role="tablist"' in view and 'role="tabpanel"' in view and 'aria-live="polite"' in view


def test_every_element_the_browser_block_reaches_for_exists_and_page_shortcuts_stop_at_the_view():
    source = MODULE.read_text(encoding="utf-8")
    browser = source[source.index("(function installJarvisWorkspace(){"):]
    html = PAGE.read_text(encoding="utf-8")
    wanted = set(re.findall(r"q\('#([A-Za-z0-9_]+)'\)", browser)) | set(re.findall(r"getElementById\('([A-Za-z0-9_]+)'\)", browser))
    assert {"workspaceManager", "openWorkspace", "wspPanel", "wspTabs"} <= wanted
    produced = set(re.findall(r'id="([A-Za-z]+)"', source))
    assert sorted(name for name in wanted if f'id="{name}"' not in html and name not in produced) == []
    handler = html[html.index("window.addEventListener('keydown',event=>{\n  if(SET.capture"):]
    handler = handler[: handler.index("\n});")]
    assert handler.index("if(workspaceManager&&!workspaceManager.hidden)return;") < handler.index("const match=")
    css = html[html.index("/* ---------- Sessions & Boards (plein écran)"): html.index("</style>")]
    assert re.search(r"\.wsp\{position:fixed;inset:0;z-index:55;", css)
    assert not re.search(r"#6ee7ff|#ff6577|#ffb85c|#68e0a0", css, re.I), "page tokens, not new brand colours"
    assert "@media(max-width:700px)" in css and "@media(prefers-reduced-motion:reduce){.wsp-spin{animation:none}.wsp-etools{transition:none}}" in css
    assert ".tl .sr,.tlab .sr,.mcpi .sr,.wsp .sr{" in html


def test_a_missing_view_is_refused_by_name_without_throwing(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "install.cjs"
    script.write_text(
        "globalThis.window=globalThis;globalThis.document={getElementById:()=>null};\n"
        "const lines=[];console.error=(...a)=>lines.push(a.join(' '));\n"
        f"require({json.dumps(str(MODULE))});\n"
        "process.stdout.write(JSON.stringify({lines,api:typeof window.JarvisWorkspace}));",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert result["api"] == "undefined"
    assert len(result["lines"]) == 1 and "workspace_host_missing" in result["lines"][0]
