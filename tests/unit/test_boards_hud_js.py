"""Contrôle Boards du haut-droit, exécuté par node (handoff board-session, Slice 06).

Ce que ce fichier épingle :

- le titre du Board actif vient **du statut** (`gate`) et reste visible ; un
  statut perdu ou un Core sans Boards se disent au lieu d'afficher un Board que
  rien ne confirme ;
- **aucune peinture optimiste** : une bascule montre son attente (compteur
  vivant, autres actions bloquées, pas de double envoi) ; un échec ou une
  échéance dépassée relisent le serveur et laissent le Board confirmé actif ;
- les codes stables (`BoardErrorCode`) deviennent des phrases françaises, la
  vraie cause restant lisible à côté ;
- la création valide le titre avant tout envoi ; l'archivage du Board actif
  est refusé **ici**, sans requête, et dit pourquoi ; l'archivage passe par la
  confirmation de la page ; la nouvelle Session aussi, et envoie la Session lue ;
- le module est inséré dans la page servie, ses deux emplacements sont
  déclarés, et son refus d'installation est rattrapé.

Slice 08 (board-memory-workspace-inspector), navigateur rapide : nature
(`board_kind`, mots du gestionnaire profond) et dernière ouverture sur chaque
ligne, filtre « En service / Archivés » (archivés sans bascule), nature choisie
à la création et changée par un seul `PATCH` peint après relecture, et
« Inspecter » remis au gestionnaire profond, refus compris.

Seuls le DOM, les minuteries et le réseau sont des doubles. Le module est le
fichier même que `ControlCenter.index` insère.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from jarvis.domain.workspace_board import BoardErrorCode
from jarvis.runtime.control_center import BOARDS_SCRIPT_FILE, BOARDS_SCRIPT_MARKER, ControlCenter

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
PAGE_HTML = RUNTIME / "control_center.html"
MODULE = RUNTIME / BOARDS_SCRIPT_FILE

WORLD = r"""
const B=require(MODULE_PATH);
const out=v=>process.stdout.write(JSON.stringify(v));

const nodes=[];
const makeNode=tag=>{
  const listeners={};
  const el={
    tag,tagName:String(tag).toUpperCase(),id:'',className:'',textContent:'',value:'',
    hidden:false,disabled:false,attrs:{},children:[],parent:null,listeners,
    style:{},
    get firstChild(){return el.children.length?el.children[0]:null},
    setAttribute(k,v){el.attrs[k]=String(v)},
    getAttribute(k){return el.attrs[k]===undefined?null:el.attrs[k]},
    removeAttribute(k){delete el.attrs[k]},
    appendChild(c){if(c.parent)c.parent.removeChild(c);c.parent=el;el.children.push(c);return c},
    removeChild(c){const i=el.children.indexOf(c);if(i>=0){el.children.splice(i,1);c.parent=null;
      if(doc.activeElement&&isInside(doc.activeElement,c))doc.activeElement=null}return c},
    addEventListener(t,fn){(listeners[t]=listeners[t]||[]).push(fn)},
    fire(t,extra){
      const event={target:el,key:'',shiftKey:false,defaultPrevented:false,stopPropagation(){}};
      event.preventDefault=()=>{event.defaultPrevented=true};
      Object.assign(event,extra||{});
      for(let n=el;n;n=n.parent)for(const fn of (n.listeners[t]||[]).slice())fn(event);
      return event;
    },
    focus(){doc.activeElement=el},
    select(){},
  };
  nodes.push(el);
  return el;
};
const isInside=(n,root)=>{for(let x=n;x;x=x.parent)if(x===root)return true;return false};
const doc={
  activeElement:null,
  createElement:tag=>makeNode(tag),
  createElementNS:(ns,tag)=>makeNode(tag),
  getElementById(id){for(const n of nodes)if(n.id===id)return n;return null},
};
doc.head=makeNode('head');

const walk=(root,seen)=>{seen.push(root);for(const c of root.children)walk(c,seen);return seen};
const all=root=>walk(root,[]);
const byId=(root,id)=>all(root).find(n=>n.id===id)||null;
const byAttr=(root,k,v)=>all(root).filter(n=>n.getAttribute&&n.getAttribute(k)===v);

let clock=Date.parse('2026-09-29T14:02:00Z'),seq=1;
const timers=[];
const setTimeoutD=(fn,ms)=>{const id=seq++;timers.push({id,fn,at:clock+(ms||0),every:0});return id};
const setIntervalD=(fn,ms)=>{const id=seq++;timers.push({id,fn,at:clock+ms,every:ms});return id};
const clearD=id=>{const i=timers.findIndex(t=>t.id===id);if(i>=0)timers.splice(i,1)};
const advance=ms=>{
  const end=clock+(ms||0);
  for(let guard=0;guard<100000;guard+=1){
    let due=null;
    for(const t of timers)if(t.at<=end&&(!due||t.at<due.at))due=t;
    if(!due)break;
    clock=due.at;
    if(due.every)due.at=clock+due.every;else clearD(due.id);
    due.fn();
  }
  clock=end;
};
const settle=async()=>{for(let i=0;i<30;i+=1)await Promise.resolve()};

const board=(id,title,over)=>Object.assign({board_id:id,title,status:'active'},over||{});
const block=(activeId,title,over)=>Object.assign({available:true,
  active:activeId?{board_id:activeId,title}:null,jarvis_session_id:'jsess_1',
  bindings:[{board_id:activeId,lifecycle:'foreground',agent_cli:'claude',closed:false}],error:null},over||{});

/* Le serveur : un Board actif, une liste, une Session, et des réponses
   programmables par route. Chaque appel est tracé : « aucun appel » est une
   assertion à part entière. */
const makeServer=()=>{
  const s={boards:[board('default','Jarvis'),board('board_b','Projet B')],active:'default',
    session:{jarvis_session_id:'jsess_1',started_at:'2026-09-29T14:02:00Z',visited_board_ids:['default']},
    calls:[],plan:{}};
  s.block=()=>block(s.active,(s.boards.find(b=>b.board_id===s.active)||{}).title);
  s.request=async(path,init)=>{
    const method=(init&&init.method)||'GET';
    const body=init&&init.body?JSON.parse(init.body):null;
    s.calls.push({path,method,body});
    /* La liste se lit archivés compris (Slice 08) : la clé du plan est la
       route sans sa requête, l'appel tracé garde l'adresse exacte. */
    const bare=path.split('?')[0],archivedToo=/[?&]include_archived=true(&|$)/.test(path);
    const key=`${method} ${bare}`;
    const step=(s.plan[key]||[]).shift();
    if(step&&step.hang)return new Promise(()=>{});
    if(step&&step.delay)await new Promise(resolve=>setTimeoutD(resolve,step.delay));
    if(step&&step.status){
      const e=new Error(step.message||'refus');e.status=step.status;e.code=step.code||null;throw e;
    }
    if(step&&step.apply)step.apply();
    if(key==='GET /api/boards')return {boards:s.boards.filter(b=>archivedToo||b.status!=='archived')
      .map(b=>Object.assign({},b)),active_board_id:s.active};
    if(key==='GET /api/sessions/current')return {session:s.session,binding:{}};
    if(key==='POST /api/boards/switch'){s.active=body.board_id;return {changed:true}}
    if(key==='POST /api/boards'){const b=board('board_new','X',{board_kind:body.board_kind||'empty'});b.title=body.title;s.boards.push(b);return {board:b,active:false}}
    if(method==='PATCH'){const id=decodeURIComponent(path.split('/').pop());const b=s.boards.find(x=>x.board_id===id);
      if(body.title!==undefined)b.title=body.title;if(body.board_kind!==undefined)b.board_kind=body.board_kind;return {board:b}}
    if(path.endsWith('/archive')){const id=decodeURIComponent(path.split('/')[3]);s.boards.find(x=>x.board_id===id).status='archived';return {}}
    if(key==='POST /api/sessions/new'){s.session=Object.assign({},s.session,{jarvis_session_id:'jsess_2'});return {session:s.session}}
    return {};
  };
  return s;
};

const mount=options=>{
  const opts=options||{};
  const host=makeNode('div');host.id=B.DOM.hostId;
  const panel=makeNode('div');panel.id=B.DOM.panelId;
  const server=makeServer();
  const journal=[],toasts=[],confirms=[];
  let answer=opts.confirm===undefined?true:opts.confirm;
  let refreshes=0;
  const control=B.createBoardsControl({
    document:doc,host,panel,
    now:()=>clock,
    setInterval:setIntervalD,clearInterval:clearD,setTimeout:setTimeoutD,clearTimeout:clearD,
    request:opts.noRequest?undefined:server.request,
    refresh:async()=>{refreshes+=1;control.gate(server.block())},
    toast:spec=>toasts.push(spec),
    confirm:opts.noConfirm?undefined:async spec=>{confirms.push(spec);return answer},
    inspect:opts.inspect,
    log:(level,event,data)=>journal.push({level,event,data}),
  });
  control.gate(opts.block===undefined?server.block():opts.block);
  const trigger=byId(host,B.DOM.triggerId);
  return {host,panel,control,server,journal,toasts,confirms,trigger,
    answer(v){answer=v},
    refreshes:()=>refreshes,
    title:()=>byId(host,B.DOM.titleId).textContent,
    sub:()=>byId(host,B.DOM.subId).textContent,
    tone:()=>host.getAttribute(B.DOM.toneAttribute),
    busy:()=>host.getAttribute(B.DOM.busyAttribute),
    note:()=>{const n=byId(panel,B.DOM.noteId);return n.hidden?'':all(n).filter(x=>x!==n).map(x=>x.textContent).filter(Boolean).join('|')},
    rows:()=>byAttr(panel,B.DOM.actionAttribute,'switch').map(p=>({id:p.getAttribute(B.DOM.boardAttribute),
      current:p.getAttribute('aria-current')==='true',disabled:p.getAttribute('aria-disabled')==='true',
      state:(all(p).find(n=>n.getAttribute&&n.getAttribute('data-role')==='state')||{}).textContent})),
    control_:(id,action)=>byAttr(panel,B.DOM.boardAttribute,id).find(n=>n.getAttribute(B.DOM.actionAttribute)===action),
    createInput:()=>byId(panel,B.DOM.createInputId),
    createError:()=>byId(panel,B.DOM.createErrorId).textContent,
    newSession:()=>byId(panel,B.DOM.newSessionId),
    focused:()=>{const a=doc.activeElement;return a?(a.id||`${a.getAttribute(B.DOM.boardAttribute)}:${a.getAttribute(B.DOM.actionAttribute)}`):null},
    calls:()=>server.calls.filter(c=>c.method!=='GET').map(c=>`${c.method} ${c.path}`),
    lists:()=>server.calls.filter(c=>c.path===B.PATH.list&&c.method==='GET').length,
    /* Ce que la ligne montre d'un Board : nature, dernière ouverture, état. */
    shown:()=>all(byId(panel,B.DOM.listId)).filter(n=>n.className==='bd-row').map(li=>{
      const role=r=>(all(li).find(n=>n.getAttribute&&n.getAttribute('data-role')===r)||{}).textContent;
      const kind=all(li).find(n=>n.getAttribute&&n.getAttribute('data-role')==='kind');
      return {id:li.getAttribute(B.DOM.boardAttribute),kind:kind?kind.getAttribute('data-kind'):null,label:role('kind'),
        opened:role('opened'),state:role('state'),archived:li.getAttribute('data-archived')==='true',
        actions:all(li).map(n=>n.getAttribute&&n.getAttribute(B.DOM.actionAttribute)).filter(Boolean)}}),
    filter:()=>all(byId(panel,B.DOM.filterId)).filter(n=>n.getAttribute&&n.getAttribute(B.DOM.filterAttribute))
      .map(n=>({key:n.getAttribute(B.DOM.filterAttribute),pressed:n.getAttribute('aria-pressed'),
        count:(all(n).find(x=>x.getAttribute&&x.getAttribute('data-role')==='count')||{}).textContent})),
    filterButton:key=>all(byId(panel,B.DOM.filterId)).find(n=>n.getAttribute&&n.getAttribute(B.DOM.filterAttribute)===key),
  };
};
"""


def run_node(tmp_path: Path, source: str, name: str = "boards") -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / f"boards-{name}.cjs"
    script.write_text(
        f"const MODULE_PATH={json.dumps(str(MODULE))};\n" + WORLD
        + "(async()=>{" + source + "})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8",
                          timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ------------------------------------------------------------- logique pure


def test_every_stable_board_error_code_has_a_french_sentence(tmp_path):
    codes = sorted(code.value for code in BoardErrorCode) + [
        "core_unreachable", "core_unconfigured", "board_store_unreadable", "board_store_failed", "invalid_request"]
    result = run_node(tmp_path, f"""
      const codes={json.dumps(codes)};
      out({{missing:codes.filter(c=>!B.REFUSAL[c]),
        mapped:B.refusalOf(Object.assign(new Error('host said no'),{{status:502,code:'board_activation_failed'}})),
        unknown:B.refusalOf(Object.assign(new Error('Teapot'),{{status:418,code:null}})),
        network:B.refusalOf(new TypeError('Failed to fetch'))}});
    """)
    assert result["missing"] == []
    assert result["mapped"]["text"].startswith("L’agent du Board n’a pas pu démarrer")
    assert result["mapped"]["detail"] == "host said no", "the real cause stays readable"
    assert result["unknown"] == {"code": "http_418", "status": 418, "detail": "Teapot", "text": "Échec : Teapot"}
    assert result["network"]["code"] == "network"


def test_titles_are_validated_like_the_contract(tmp_path):
    result = run_node(tmp_path, r"""
      const v=B.validateTitle;
      out({empty:v('   ').ok,trimmed:v('  Projet  ').value,long:v('x'.repeat(121)).ok,max:v('é'.repeat(120)).ok,
        emoji:v('🙂'.repeat(120)).ok,newline:v('a\nb').ok,sep:v('a'+String.fromCharCode(0x2028)+'b').ok,
        tab:v('a\tb').ok,error:v('').error});
    """)
    assert result == {"empty": False, "trimmed": "Projet", "long": False, "max": True, "emoji": True,
                      "newline": False, "sep": False, "tab": False, "error": "Donnez un titre au Board."}


# ------------------------------------------------------------- rendu


def test_the_active_title_is_always_visible_and_follows_the_status(tmp_path):
    result = run_node(tmp_path, r"""
      const m=mount();
      const first={title:m.title(),tone:m.tone(),label:m.trigger.getAttribute('aria-label'),sub:m.sub()};
      m.control.gate(block('board_b','Projet B',{bindings:[
        {board_id:'board_b',lifecycle:'foreground',agent_cli:'claude',closed:false},
        {board_id:'default',lifecycle:'background_running',agent_cli:'claude',closed:false}]}));
      const moved={title:m.title(),sub:m.sub()};
      m.control.statusLost();
      const lost={title:m.title(),tone:m.tone(),sub:m.sub()};
      m.control.gate({available:false,active:null,jarvis_session_id:null,bindings:[],
        error:{code:'core_unreachable',message:'x'}});
      const down={title:m.title(),tone:m.tone(),sub:m.sub(),label:m.trigger.getAttribute('aria-label')};
      out({first,moved,lost,down,expanded:m.trigger.getAttribute('aria-expanded'),
        popup:m.trigger.getAttribute('aria-haspopup'),hidden:m.panel.hidden,calls:m.server.calls.length});
    """)
    assert result["first"] == {"title": "Jarvis", "tone": "ready",
                               "label": "Board actif : Jarvis. Ouvrir la liste des Boards", "sub": ""}
    assert result["moved"] == {"title": "Projet B", "sub": "1 en arrière-plan"}
    assert result["lost"] == {"title": "Inconnu", "tone": "unknown", "sub": "Statut perdu"}
    down = result["down"]
    assert (down["title"], down["tone"], down["sub"]) == ("Indisponible", "unavailable", "Core ne répond pas"), \
        "a French phrase, never the raw code as body text (QA 06/07, point 9)"
    assert "core_unreachable" in down["label"], "the code stays available as detail"
    assert result["expanded"] == "false" and result["popup"] == "dialog" and result["hidden"] is True
    assert result["calls"] == 0, "the closed control never polls: the page status feeds it"


def test_opening_lists_the_boards_with_the_active_one_marked_and_focused(tmp_path):
    result = run_node(tmp_path, r"""
      const m=mount();
      m.trigger.fire('click');
      await settle();
      const archiveActive=m.control_('default','archive');
      out({open:m.control.isOpen(),hidden:m.panel.hidden,expanded:m.trigger.getAttribute('aria-expanded'),
        rows:m.rows(),focused:m.focused(),role:m.panel.getAttribute('role'),
        archiveActive:{disabled:archiveActive.getAttribute('aria-disabled'),title:archiveActive.getAttribute('title')},
        archiveOther:m.control_('board_b','archive').getAttribute('aria-disabled'),
        session:byId(m.panel,B.DOM.sessionLineId).textContent,
        hint:all(m.panel).some(n=>n.textContent===B.NEW_SESSION_HINT),
        gets:m.server.calls.map(c=>c.path)});
    """)
    assert result["open"] is True and result["hidden"] is False and result["expanded"] == "true"
    assert result["role"] == "dialog"
    assert result["rows"] == [
        {"id": "default", "current": True, "disabled": False, "state": "Actif"},
        {"id": "board_b", "current": False, "disabled": False, "state": ""},
    ]
    assert result["focused"] == "default:switch"
    assert result["archiveActive"] == {"disabled": "true", "title": "Le Board actif ne peut pas être archivé : "
                                       "basculez d’abord sur un autre Board."}
    assert result["archiveOther"] is None
    assert result["session"].startswith("Session en cours · depuis ")
    assert result["hint"] is True
    assert sorted(result["gets"]) == ["/api/boards?include_archived=true", "/api/sessions/current"]


def test_arrow_keys_move_between_boards_and_escape_closes_back_to_the_trigger(tmp_path):
    result = run_node(tmp_path, r"""
      const m=mount();m.server.boards.push(board('board_c','Troisième'));
      m.trigger.fire('keydown',{key:'ArrowDown'});await settle();
      const opened=m.focused();
      doc.activeElement.fire('keydown',{key:'ArrowDown'});const down=m.focused();
      doc.activeElement.fire('keydown',{key:'End'});const end=m.focused();
      doc.activeElement.fire('keydown',{key:'Home'});const home=m.focused();
      doc.activeElement.fire('keydown',{key:'Escape'});
      out({opened,down,end,home,closed:!m.control.isOpen(),focused:m.focused()});
    """)
    assert result == {"opened": "default:switch", "down": "board_b:switch", "end": "board_c:switch",
                      "home": "default:switch", "closed": True, "focused": "boardsButton"}


# ------------------------------------------------------------- bascule


def test_a_switch_shows_its_wait_blocks_other_actions_then_follows_the_server(tmp_path):
    result = run_node(tmp_path, r"""
      const m=mount();
      m.trigger.fire('click');await settle();
      m.server.plan['POST /api/boards/switch']=[{delay:4000}];
      m.control_('board_b','switch').fire('click');await settle();
      advance(3000);await settle();
      const during={tone:m.tone(),title:m.title(),sub:m.sub(),busy:m.busy(),note:m.note(),rows:m.rows(),
        activeStill:m.rows().find(r=>r.current).id};
      /* Double envoi, autre bascule, création, nouvelle Session : rien ne part. */
      m.control_('board_b','switch').fire('click');
      m.control_('default','rename').fire('click');
      m.createInput().value='Encore';byId(m.panel,B.DOM.createButtonId).fire('click');
      m.newSession().fire('click');
      await settle();
      const callsDuring=m.calls();
      advance(1500);await settle();await settle();
      out({during,callsDuring,after:{title:m.title(),tone:m.tone(),busy:m.busy(),open:m.control.isOpen(),
        focused:m.focused(),pending:m.control.pending()},toasts:m.toasts,refreshes:m.refreshes(),
        journal:m.journal.map(j=>j.event)});
    """)
    during = result["during"]
    assert during["tone"] == "pending" and during["title"] == "Projet B" and during["busy"] == "true"
    assert during["sub"] == "Bascule · 3 s", "a live counter, not a static label"
    assert during["note"].startswith("Bascule… 3 s"), "one word for the wait: Bascule"
    assert during["activeStill"] == "default", "nothing is painted active before the server says so"
    assert [r["state"] for r in during["rows"]] == ["Actif", "Bascule · 3 s"]
    assert result["callsDuring"] == ["POST /api/boards/switch"], "one request, no double submit"
    after = result["after"]
    assert after == {"title": "Projet B", "tone": "ready", "busy": "false", "open": False,
                     "focused": "boardsButton", "pending": None}
    assert result["toasts"][-1]["kind"] == "ok" and result["toasts"][-1]["title"] == "Board « Projet B » actif."
    assert result["refreshes"] >= 1
    assert "boards.switch_requested" in result["journal"] and "boards.switch_done" in result["journal"]


def test_a_refused_switch_says_why_and_rolls_back_to_the_server_truth(tmp_path):
    result = run_node(tmp_path, r"""
      const m=mount();
      m.trigger.fire('click');await settle();
      const listsBefore=m.lists();
      m.server.plan['POST /api/boards/switch']=[{status:502,code:'board_activation_failed',
        message:'control center did not answer within 60 s'}];
      m.control_('board_b','switch').fire('click');await settle();await settle();
      out({title:m.title(),tone:m.tone(),current:m.rows().find(r=>r.current).id,note:m.note(),
        open:m.control.isOpen(),toasts:m.toasts,relisted:m.lists()-listsBefore,refreshes:m.refreshes(),
        failure:m.control.failure(),error:m.journal.find(j=>j.event==='boards.switch_failed'),
        rowsEnabled:m.rows().every(r=>!r.disabled)});
    """)
    assert result["title"] == "Jarvis" and result["tone"] == "ready" and result["current"] == "default"
    assert result["note"].startswith("L’agent du Board n’a pas pu démarrer. Rien n’a changé")
    assert "board_activation_failed · control center did not answer within 60 s" in result["note"]
    assert result["open"] is True, "the explanation stays where the user clicked"
    assert result["toasts"][-1]["kind"] == "bad"
    assert result["relisted"] >= 1 and result["refreshes"] >= 1, "rolled back by re-reading the server"
    assert result["error"]["level"] == "error" and result["error"]["data"]["code"] == "board_activation_failed"
    assert result["rowsEnabled"] is True


def test_the_client_waits_longer_than_the_relay_then_verifies_instead_of_inviting_a_retry(tmp_path):
    """QA 06/07, point 1 : 75 s côté page contre 150 s au relais ; la page disait « réessayez »."""

    from jarvis.runtime.core_sessions import CORE_TRANSITION_TIMEOUT_S

    result = run_node(tmp_path, r"""
      const m=mount();
      m.trigger.fire('click');await settle();
      m.server.plan['POST /api/boards/switch']=[{hang:true}];
      m.control_('board_b','switch').fire('click');await settle();
      advance(B.DEADLINE_MS.switch-1000);await settle();
      const before=m.control.pending()&&m.control.pending().kind;
      advance(2000);await settle();await settle();
      const checking={pending:m.control.pending(),note:m.note(),sub:m.sub(),toasts:m.toasts.length};
      for(let i=0;i<30;i+=1){advance(1000);await settle();await settle()}
      out({deadlines:B.DEADLINE_MS,before,checking,pending:m.control.pending(),note:m.note(),tone:m.tone(),
        title:m.title(),toast:m.toasts[m.toasts.length-1],waits:m.control.waits(),
        journal:m.journal.map(j=>j.event)});
    """)
    assert result["deadlines"]["switch"] / 1000 > CORE_TRANSITION_TIMEOUT_S
    assert result["deadlines"]["new_session"] / 1000 > CORE_TRANSITION_TIMEOUT_S
    assert result["before"] == "switch"
    checking = result["checking"]
    assert checking["pending"]["verifying"] is True, "the outcome is unknown: still busy, verifying"
    assert checking["note"].startswith("Résultat inconnu, vérification…") and "Ne recommencez pas" in checking["note"]
    assert checking["sub"].startswith("Vérification ·") and checking["toasts"] == 0
    assert "réessayez" not in checking["note"].lower()
    assert result["pending"] is None and result["tone"] == "ready" and result["title"] == "Jarvis"
    assert result["note"].startswith("La bascule n’a pas eu lieu : « Jarvis » reste actif.")
    assert result["toast"]["kind"] == "warn"
    assert "boards.switch_unknown" in result["journal"] and "boards.switch_done" not in result["journal"]
    assert result["waits"] == 0


def test_a_504_outcome_unknown_is_verified_and_a_late_commit_is_reported_as_done(tmp_path):
    result = run_node(tmp_path, r"""
      const m=mount();
      m.trigger.fire('click');await settle();
      m.server.plan['POST /api/boards/switch']=[{status:504,code:'core_transition_timeout',
        message:'Core did not answer in time: the outcome is unknown'}];
      m.control_('board_b','switch').fire('click');await settle();await settle();
      const checking={note:m.note(),verifying:!!(m.control.pending()&&m.control.pending().verifying),
        toasts:m.toasts.length};
      advance(2000);await settle();await settle();
      m.server.active='board_b';                       /* Core valide après le 504 */
      for(let i=0;i<6;i+=1){advance(1000);await settle();await settle()}
      out({refusal:B.REFUSAL.core_transition_timeout,checking,pending:m.control.pending(),title:m.title(),
        toasts:m.toasts,note:m.note(),journal:m.journal.map(j=>j.event)});
    """)
    assert "inconnu" in result["refusal"] and "ne recommencez pas" in result["refusal"]
    assert result["checking"]["verifying"] is True and result["checking"]["toasts"] == 0
    assert result["checking"]["note"].startswith("Résultat inconnu, vérification…")
    assert result["pending"] is None and result["title"] == "Projet B"
    assert [t["kind"] for t in result["toasts"]] == ["ok"], "one story: only the verdict is toasted"
    assert "boards.switch_confirmed" in result["journal"] and "boards.switch_failed" not in result["journal"]


def test_a_late_answer_after_the_deadline_is_ignored_while_verification_decides(tmp_path):
    """Mutant M16 : sans le garde, la réponse tardive peignait « actif » et libérait l'attente."""

    result = run_node(tmp_path, r"""
      const m=mount();
      m.trigger.fire('click');await settle();
      m.server.plan['POST /api/boards/switch']=[{delay:B.DEADLINE_MS.switch+4000}];
      m.control_('board_b','switch').fire('click');await settle();
      advance(B.DEADLINE_MS.switch+500);await settle();await settle();
      advance(4000);await settle();await settle();      /* la réponse tardive arrive (et applique) */
      const after={pending:m.control.pending(),journal:m.journal.map(j=>j.event)};
      for(let i=0;i<6;i+=1){advance(1000);await settle();await settle()}
      out({after,end:m.control.pending(),journal:m.journal.map(j=>j.event),toasts:m.toasts.map(t=>t.kind)});
    """)
    assert "boards.switch_done" not in result["after"]["journal"], "the late answer is not the story"
    assert "boards.switch_confirmed" in result["journal"] and result["end"] is None
    assert result["toasts"] == ["ok"]


def test_a_switch_decided_elsewhere_reloads_the_open_list(tmp_path):
    result = run_node(tmp_path, r"""
      const m=mount();
      m.trigger.fire('click');await settle();
      const before=m.lists();
      m.server.active='board_b';
      m.control.gate(m.server.block());await settle();
      m.control.gate(m.server.block());await settle();
      out({reloads:m.lists()-before,current:m.rows().find(r=>r.current).id,title:m.title()});
    """)
    assert result == {"reloads": 1, "current": "board_b", "title": "Projet B"}


# ------------------------------------------------------------- création


def test_create_validates_before_sending_and_shows_the_server_refusal_inline(tmp_path):
    result = run_node(tmp_path, r"""
      const m=mount();
      m.trigger.fire('click');await settle();
      const input=m.createInput(),go=byId(m.panel,B.DOM.createButtonId);
      input.value='   ';go.fire('click');await settle();
      const empty={error:m.createError(),calls:m.calls().length,invalid:input.getAttribute('aria-invalid')};
      input.value='x'.repeat(121);input.fire('keydown',{key:'Enter'});await settle();
      const long={error:m.createError(),calls:m.calls().length};
      m.server.plan['POST /api/boards']=[{status:400,code:'invalid_title',message:'title must be printable'}];
      input.value='Ok\u0085';
      input.value='Refusé par Core';go.fire('click');await settle();await settle();
      const refused={error:m.createError(),note:m.note(),value:input.value};
      input.value='  Projet C  ';go.fire('click');await settle();await settle();
      const sent=m.server.calls.filter(c=>c.method==='POST'&&c.path==='/api/boards').map(c=>c.body);
      out({empty,long,refused,sent,value:input.value,error:m.createError(),rows:m.rows().map(r=>r.id),
        focused:m.focused(),toast:m.toasts[m.toasts.length-1],title:m.title()});
    """)
    assert result["empty"] == {"error": "Donnez un titre au Board.", "calls": 0, "invalid": "true"}
    assert result["long"] == {"error": "Titre trop long : 121 caractères sur 120.", "calls": 0}
    assert result["refused"]["error"] == "Titre refusé : 1 à 120 caractères, sur une seule ligne."
    assert result["refused"]["note"] == "", "said once, next to the field"
    assert result["refused"]["value"] == "Refusé par Core", "the typed title is kept"
    assert result["sent"] == [{"title": "Refusé par Core"}, {"title": "Projet C"}]
    assert result["value"] == "" and result["error"] == ""
    assert result["rows"] == ["default", "board_b", "board_new"]
    assert result["focused"] == "board_new:switch", "the new Board is one Enter away"
    assert result["toast"]["kind"] == "ok" and "pas encore ouvert" in result["toast"]["sub"]
    assert result["title"] == "Jarvis", "creating does not switch"


# ------------------------------------------------------------- renommage


def test_rename_edits_in_place_saves_on_enter_and_cancels_on_escape(tmp_path):
    result = run_node(tmp_path, r"""
      const m=mount();
      m.trigger.fire('click');await settle();
      m.control_('board_b','rename').fire('click');await settle();
      let field=m.control_('board_b','title');
      const editing={value:field.value,focused:m.focused()};
      field.value='';field.fire('keydown',{key:'Enter'});await settle();
      const invalid={calls:m.calls().length,error:all(m.panel).find(n=>n.className==='bd-rowerr').textContent};
      field=m.control_('board_b','title');
      field.fire('keydown',{key:'Escape'});await settle();
      const cancelled={field:!!m.control_('board_b','title'),open:m.control.isOpen(),focused:m.focused()};
      m.control_('default','rename').fire('click');await settle();
      field=m.control_('default','title');field.value='Jarvis 2';field.fire('input');
      field.fire('keydown',{key:'Enter'});await settle();await settle();
      out({editing,invalid,cancelled,calls:m.server.calls.filter(c=>c.method==='PATCH'),title:m.title(),
        rows:m.rows().map(r=>r.id),focused:m.focused()});
    """)
    assert result["editing"] == {"value": "Projet B", "focused": "board_b:title"}
    assert result["invalid"] == {"calls": 0, "error": "Donnez un titre au Board."}
    assert result["cancelled"] == {"field": False, "open": True, "focused": "board_b:rename"}
    assert result["calls"] == [{"path": "/api/boards/default", "method": "PATCH", "body": {"title": "Jarvis 2"}}]
    assert result["title"] == "Jarvis 2", "the active title follows the re-read status"
    assert result["focused"] == "default:rename"


# ------------------------------------------------------------- archivage


def test_the_active_board_cannot_be_archived_and_the_control_says_why(tmp_path):
    result = run_node(tmp_path, r"""
      const m=mount();
      m.trigger.fire('click');await settle();
      m.control_('default','archive').fire('click');await settle();
      out({calls:m.calls(),confirms:m.confirms.length,note:m.note(),
        failure:m.control.failure()});
    """)
    assert result["calls"] == [] and result["confirms"] == 0
    assert result["note"].startswith("Le Board actif ne peut pas être archivé")
    assert result["failure"]["tone"] == "warn"


def test_archive_goes_through_the_page_confirmation_and_maps_a_late_refusal(tmp_path):
    result = run_node(tmp_path, r"""
      const m=mount({confirm:false});
      m.trigger.fire('click');await settle();
      m.control_('board_b','archive').fire('click');await settle();
      const cancelled={calls:m.calls(),confirm:m.confirms[0]};
      m.answer(true);
      m.server.plan['POST /api/boards/board_b/archive']=[{status:409,code:'board_is_active',message:'active'}];
      m.control_('board_b','archive').fire('click');await settle();await settle();
      const refused={note:m.note(),rows:m.rows().map(r=>r.id)};
      m.control_('board_b','archive').fire('click');await settle();await settle();
      out({cancelled,refused,calls:m.calls(),rows:m.rows().map(r=>r.id),toast:m.toasts[m.toasts.length-1],focused:m.focused()});
    """)
    confirm = result["cancelled"]["confirm"]
    assert result["cancelled"]["calls"] == []
    assert confirm["title"] == "Archiver « Projet B » ?" and confirm["danger"] is True
    assert confirm["confirmLabel"] == "Archiver"
    assert any("Irréversible" in line for line in confirm["lines"])
    assert result["refused"]["note"].startswith("Le Board actif ne peut pas être archivé")
    assert result["refused"]["rows"] == ["default", "board_b"]
    assert result["calls"] == ["POST /api/boards/board_b/archive"] * 2
    assert result["rows"] == ["default"]
    assert result["toast"] == {"title": "Board « Projet B » archivé.", "kind": "ok"}
    assert result["focused"] == "default:switch", "focus survives the removed row"


# ------------------------------------------------------------- nouvelle Session


def test_new_session_confirms_sends_the_session_it_read_and_keeps_the_board(tmp_path):
    result = run_node(tmp_path, r"""
      const m=mount();
      m.trigger.fire('click');await settle();
      m.newSession().fire('click');await settle();await settle();
      out({confirm:m.confirms[0],calls:m.server.calls.filter(c=>c.path==='/api/sessions/new'),
        toast:m.toasts[m.toasts.length-1],open:m.control.isOpen(),title:m.title()});
    """)
    confirm = result["confirm"]
    assert confirm["title"] == "Démarrer une nouvelle session ?"
    assert "Board « Jarvis »" in confirm["lines"][0]
    assert "ses tâches et le travail en arrière-plan sont conservés" in confirm["lines"][1]
    assert result["calls"] == [{"path": "/api/sessions/new", "method": "POST",
                                "body": {"expected_session_id": "jsess_1"}}]
    assert result["toast"]["kind"] == "ok" and "Board et tâches conservés" in result["toast"]["sub"]
    assert result["open"] is False and result["title"] == "Jarvis"


def test_a_new_session_refused_because_it_already_changed_says_so(tmp_path):
    result = run_node(tmp_path, r"""
      const m=mount();
      m.trigger.fire('click');await settle();
      m.server.plan['POST /api/sessions/new']=[{status:409,code:'session_closed',message:'closed'}];
      m.newSession().fire('click');await settle();await settle();
      const refused=m.note();
      m.answer(false);
      m.newSession().fire('click');await settle();
      out({refused,calls:m.server.calls.filter(c=>c.path==='/api/sessions/new').length,
        toast:m.toasts[m.toasts.length-1]});
    """)
    assert result["refused"].startswith("La session a changé entre-temps")
    assert result["calls"] == 1, "a cancelled confirmation sends nothing"
    assert result["toast"]["kind"] == "bad"


# ------------------------------------------------------------- liste


def test_an_unreadable_list_is_said_and_can_be_retried_by_reopening(tmp_path):
    result = run_node(tmp_path, r"""
      const m=mount();
      m.server.plan['GET /api/boards']=[{status:503,code:'core_unreachable',message:'Core is unreachable: x'}];
      m.trigger.fire('click');await settle();await settle();
      const failed={note:m.note(),rows:m.rows().length,error:m.journal.find(j=>j.event==='boards.list_failed')};
      m.trigger.fire('click');m.trigger.fire('click');await settle();await settle();
      out({failed,note:m.note(),rows:m.rows().length});
    """)
    assert result["failed"]["note"].startswith("Liste des Boards illisible : Core ne répond pas.")
    assert result["failed"]["rows"] == 0
    assert result["failed"]["error"]["level"] == "error"
    assert result["note"] == "" and result["rows"] == 2


# ------------------------------------------------------------- navigateur rapide (Slice 08)


def test_kind_words_are_the_deep_managers_and_last_opened_reads_relative(tmp_path):
    workspace = RUNTIME / "control_center_workspace.js"
    result = run_node(tmp_path, r"""
      const W=require(""" + json.dumps(str(workspace)) + r""");
      const now=Date.parse('2026-10-03T12:00:00Z');
      out({hud:B.BOARD_KINDS,manager:W.BOARD_KINDS,
        kinds:[B.kindOf(undefined),B.kindOf('meeting'),B.kindOf('demo')],
        opened:[null,'pas une date','2026-10-03T11:59:30Z','2026-10-03T12:04:00Z','2026-10-03T11:15:00Z',
          '2026-10-03T07:00:00Z','2026-10-01T12:00:00Z','2026-09-01T12:00:00Z','2025-09-01T12:00:00Z']
          .map(iso=>B.openedOf(iso,now).label),
        exact:B.openedOf('2026-10-01T12:00:00Z',now).exact});
    """)
    assert result["hud"] == result["manager"] == {"empty": "Générique", "meeting": "Réunion",
                                                  "presentation": "Présentation"}
    assert result["kinds"] == [{"kind": "empty", "label": "Générique"}, {"kind": "meeting", "label": "Réunion"},
                               {"kind": "demo", "label": "demo"}], "an unknown kind is shown as is"
    assert result["opened"] == ["jamais ouvert", "jamais ouvert", "ouvert à l’instant", "ouvert à l’instant",
                                "ouvert il y a 45 min", "ouvert il y a 5 h", "ouvert il y a 2 j",
                                "ouvert le 1 sept.", "ouvert le 1 sept. 2025"]
    assert result["exact"].startswith("Dernière ouverture : 1 oct. 2026 à ")


def test_each_row_shows_its_kind_and_last_opening_from_the_server(tmp_path):
    result = run_node(tmp_path, r"""
      const m=mount();
      Object.assign(m.server.boards[0],{board_kind:'empty',last_opened_at:'2026-09-29T14:00:00Z'});
      Object.assign(m.server.boards[1],{board_kind:'meeting',last_opened_at:'2026-09-29T11:02:00Z'});
      m.server.boards.push(board('board_c','Démo client',{board_kind:'presentation'}));
      m.trigger.fire('click');await settle();
      out({shown:m.shown(),gets:m.server.calls.map(c=>c.path)});
    """)
    assert result["shown"] == [
        {"id": "default", "kind": "empty", "label": "Générique", "opened": "ouvert il y a 2 min", "state": "Actif",
         "archived": False, "actions": ["switch", "rename", "inspect", "archive"]},
        {"id": "board_b", "kind": "meeting", "label": "Réunion", "opened": "ouvert il y a 3 h", "state": "",
         "archived": False, "actions": ["switch", "rename", "inspect", "archive"]},
        {"id": "board_c", "kind": "presentation", "label": "Présentation", "opened": "jamais ouvert", "state": "",
         "archived": False, "actions": ["switch", "rename", "inspect", "archive"]},
    ]
    assert result["gets"][0] == "/api/boards?include_archived=true"


def test_archived_boards_are_listed_apart_never_switchable_but_inspectable(tmp_path):
    result = run_node(tmp_path, r"""
      const inspected=[];
      const m=mount({inspect:id=>{inspected.push(id)}});
      m.server.boards.push(board('board_old','Ancien',{status:'archived',board_kind:'meeting',last_opened_at:'2026-09-01T09:00:00Z'}));
      m.trigger.fire('click');await settle();
      const hintNode=()=>all(m.panel).find(n=>n.textContent===B.ARCHIVED_HINT);
      const active={filter:m.filter(),ids:m.shown().map(r=>r.id),hint:hintNode().hidden};
      m.filterButton('archived').fire('click');await settle();
      const archived={filter:m.filter(),shown:m.shown(),picks:m.rows(),hint:hintNode().hidden,
        label:byId(m.panel,B.DOM.listId).getAttribute('aria-label')};
      m.control_('board_old','inspect').fire('click');await settle();
      m.trigger.fire('click');const reopened=m.control.view();
      await settle();
      out({active,archived,inspected,reopened,posts:m.calls(),
        events:m.journal.map(j=>j.event).filter(e=>e.startsWith('boards.filter')||e.startsWith('boards.inspect'))});
    """)
    assert result["active"]["filter"] == [{"key": "active", "pressed": "true", "count": "2"},
                                          {"key": "archived", "pressed": "false", "count": "1"}]
    assert result["active"]["ids"] == ["default", "board_b"] and result["active"]["hint"] is True
    archived = result["archived"]
    assert archived["filter"][1] == {"key": "archived", "pressed": "true", "count": "1"}
    assert archived["shown"] == [{"id": "board_old", "kind": "meeting", "label": "Réunion",
                                  "opened": "ouvert le 1 sept.", "state": "Archivé", "archived": True,
                                  "actions": ["inspect"]}]
    assert archived["picks"] == [], "no switch button for an archived Board"
    assert archived["hint"] is False and archived["label"] == "Boards archivés"
    assert result["inspected"] == ["board_old"]
    assert result["reopened"] == "active", "each opening starts on the Boards in service"
    assert result["posts"] == [], "filtering and inspecting never write"
    assert result["events"] == ["boards.filter_changed", "boards.inspect_requested"]


def test_create_sends_the_chosen_kind_and_the_default_one_is_left_to_core(tmp_path):
    result = run_node(tmp_path, r"""
      const m=mount();
      m.trigger.fire('click');await settle();
      const kind=byId(m.panel,B.DOM.createKindId);
      const options=kind.children.map(o=>[o.value,o.textContent]);
      m.createInput().value='Réunion hebdo';kind.value='meeting';
      byId(m.panel,B.DOM.createButtonId).fire('click');await settle();await settle();
      const afterMeeting={kind:kind.value,row:m.shown().find(r=>r.id==='board_new')};
      m.createInput().value='Notes';
      byId(m.panel,B.DOM.createButtonId).fire('click');await settle();await settle();
      out({options,afterMeeting,bodies:m.server.calls.filter(c=>c.method==='POST'&&c.path==='/api/boards').map(c=>c.body),
        toast:m.toasts.map(t=>t.title)});
    """)
    assert result["options"] == [["empty", "Générique"], ["meeting", "Réunion"], ["presentation", "Présentation"]]
    assert result["bodies"] == [{"title": "Réunion hebdo", "board_kind": "meeting"}, {"title": "Notes"}]
    assert result["afterMeeting"]["kind"] == "empty", "the selector resets after success"
    assert result["afterMeeting"]["row"]["kind"] == "meeting", "the row shows what the server kept"
    assert result["toast"][0] == "Board « Réunion hebdo » créé (Réunion)."


def test_edit_changes_the_kind_with_one_patch_painted_only_after_the_server_confirms(tmp_path):
    result = run_node(tmp_path, r"""
      const m=mount();
      m.trigger.fire('click');await settle();
      m.control_('board_b','rename').fire('click');await settle();
      const select=m.control_('board_b','kind');
      const initial=select.value;
      select.value='presentation';select.fire('change');
      m.server.plan['PATCH /api/boards/board_b']=[{delay:3000}];
      m.control_('board_b','save').fire('click');await settle();
      const during={row:m.shown().find(r=>r.id==='board_b'),note:m.note()};
      advance(3000);await settle();await settle();
      const after=m.shown().find(r=>r.id==='board_b');
      // Rien ne change : aucune requete.
      m.control_('board_b','rename').fire('click');await settle();
      m.control_('board_b','save').fire('click');await settle();
      const unchanged={editing:!!m.control_('board_b','title')};
      // Titre et nature ensemble : un seul PATCH, les deux champs.
      m.control_('default','rename').fire('click');await settle();
      m.control_('default','title').value='Jarvis 2';m.control_('default','kind').value='meeting';
      m.control_('default','save').fire('click');await settle();await settle();
      // Un refus de Core garde la saisie et dit pourquoi, dans la ligne.
      m.control_('board_b','rename').fire('click');await settle();
      m.control_('board_b','kind').value='meeting';m.control_('board_b','kind').fire('change');
      m.server.plan['PATCH /api/boards/board_b']=[{status:400,code:'invalid_board',message:'board_kind must be one of'}];
      m.control_('board_b','save').fire('click');await settle();await settle();
      const refused={kind:m.control_('board_b','kind').value,error:all(m.panel).find(n=>n.className==='bd-rowerr').textContent,
        row:m.server.boards.find(b=>b.board_id==='board_b').board_kind};
      out({initial,during,after,unchanged,refused,patches:m.server.calls.filter(c=>c.method==='PATCH').map(c=>c.body),
        events:m.journal.map(j=>j.event).filter(e=>e.startsWith('boards.update'))});
    """)
    assert result["initial"] == "empty"
    assert result["during"]["row"]["kind"] is None, "while waiting the row is the edit form, not a guessed badge"
    assert result["during"]["note"].startswith("Enregistrement… ")
    assert result["after"]["kind"] == "presentation" and result["after"]["label"] == "Présentation"
    assert result["unchanged"] == {"editing": False}
    assert result["patches"] == [{"board_kind": "presentation"}, {"title": "Jarvis 2", "board_kind": "meeting"},
                                 {"board_kind": "meeting"}]
    assert result["refused"] == {"kind": "meeting", "error": "Demande refusée par Core : Board invalide.",
                                 "row": "presentation"}
    assert result["events"] == ["boards.update_requested", "boards.update_done", "boards.update_requested",
                                "boards.update_done", "boards.update_requested", "boards.update_failed"]


def test_inspect_hands_the_board_to_the_deep_manager_and_says_when_it_cannot(tmp_path):
    result = run_node(tmp_path, r"""
      const seen=[];
      const ok=mount({inspect:id=>{seen.push(id);return Promise.resolve()}});
      ok.trigger.fire('click');await settle();
      const button=ok.control_('board_b','inspect');
      const label=button.getAttribute('aria-label');
      button.fire('click');await settle();
      const done={seen:seen.slice(),open:ok.control.isOpen()};

      const missing=mount();
      missing.trigger.fire('click');await settle();
      missing.control_('board_b','inspect').fire('click');await settle();

      const thrown=mount({inspect:()=>{throw Object.assign(new Error('window.JarvisWorkspace.openBoard absent'),{code:'workspace_manager_missing'})}});
      thrown.trigger.fire('click');await settle();
      thrown.control_('board_b','inspect').fire('click');await settle();

      const late=mount({inspect:()=>Promise.reject(new Error('vue introuvable'))});
      late.trigger.fire('click');await settle();
      late.control_('board_b','inspect').fire('click');await settle();

      const busy=mount({inspect:id=>{seen.push(id)}});
      busy.trigger.fire('click');await settle();
      busy.server.plan['POST /api/boards/switch']=[{hang:true}];
      busy.control_('board_b','switch').fire('click');await settle();
      const inert=busy.control_('default','inspect').getAttribute('aria-disabled');
      busy.control_('default','inspect').fire('click');await settle();

      out({label,done,
        missing:{open:missing.control.isOpen(),note:missing.note(),log:missing.journal.filter(j=>j.level==='error').map(j=>[j.event,j.data.code])},
        thrown:{open:thrown.control.isOpen(),note:thrown.note()},
        late:{open:late.control.isOpen(),toasts:late.toasts.map(t=>[t.title,t.sub])},
        busy:{inert,seen:seen.length}});
    """)
    assert result["label"] == "Inspecter Projet B dans Sessions & Boards"
    assert result["done"] == {"seen": ["board_b"], "open": False}, "the panel gives the screen to the manager"
    missing = result["missing"]
    assert missing["open"] is True and missing["note"].startswith(
        "Le gestionnaire Sessions & Boards n’est pas installé")
    assert missing["log"] == [["boards.inspect_failed", "workspace_manager_missing"]]
    assert result["thrown"]["open"] is True
    assert result["thrown"]["note"].startswith("Le gestionnaire Sessions & Boards n’est pas installé")
    assert "workspace_manager_missing · window.JarvisWorkspace.openBoard absent" in result["thrown"]["note"]
    assert result["late"]["open"] is False
    assert result["late"]["toasts"] == [["Inspection impossible",
                                         "Inspection de « Projet B » interrompue : vue introuvable."]]
    assert result["busy"] == {"inert": "true", "seen": 1}, "no inspection while a switch is in flight"


def test_the_browser_install_finds_the_manager_at_click_time():
    source = MODULE.read_text(encoding="utf-8")
    install = source[source.index("function installJarvisBoards(){"):]
    assert "const manager=window.JarvisWorkspace;" in install
    assert "manager.openBoard(id)" in install and "inspect:control.inspectBoard" in install


# ------------------------------------------------------------- insertion


def test_the_page_api_unfolds_the_board_error_envelope(tmp_path):
    """`api()` de la page : `{error:{code,message}}` donnait « [object Object] » et aucun code."""

    html = PAGE_HTML.read_text(encoding="utf-8")
    start = html.index("async function api(path,opts)")
    end = html.index("function esc(v)", start)
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "api.cjs"
    script.write_text(
        "let answer;const fetch=async()=>answer;\n" + html[start:end] + r"""
(async()=>{
  const res=(status,body,headers)=>({ok:status<400,status,text:async()=>JSON.stringify(body),
    headers:{get:k=>(headers||{})[k]||null}});
  const seen=[];
  for(const [status,body,headers] of [
    [502,{error:{code:'board_activation_failed',message:'host said no'}}],
    [409,{error:'mode réservé'},{'X-Jarvis-Error-Code':'interaction_mode_not_implemented'}],
    [500,{ok:false,code:'boom',error:'Boom'}]]){
    answer=res(status,body,headers);
    try{await api('/x')}catch(e){seen.push({message:e.message,code:e.code,status:e.status})}
  }
  process.stdout.write(JSON.stringify(seen));
})();
""", encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == [
        {"message": "host said no", "code": "board_activation_failed", "status": 502},
        {"message": "mode réservé", "code": "interaction_mode_not_implemented", "status": 409},
        {"message": "Boom", "code": "boom", "status": 500},
    ]


@pytest.mark.asyncio
async def test_the_served_page_inserts_the_module_and_declares_both_slots(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    html = (await control.index(None)).text
    assert BOARDS_SCRIPT_MARKER not in html
    assert "installJarvisBoards" in html
    assert re.search(r'<div class="topbar">.*?<div id="boardsHud"></div>.*?</div>', html)
    assert '<div id="boardsPanel" hidden></div>' in html
    assert "JarvisBoardsControl.gate(s.boards)" in html and "JarvisBoardsControl.statusLost()" in html
    source = PAGE_HTML.read_text(encoding="utf-8")
    registry = source[:source.index("*/")]
    assert "#boardsHud" in registry and "#boardsPanel" in registry
    assert re.search(r"#boardsHud\{[^}]*pointer-events:auto", source)


def test_a_missing_slot_is_refused_by_name_without_throwing(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = tmp_path / "install.cjs"
    script.write_text(
        "globalThis.window=globalThis;globalThis.document={getElementById:()=>null};\n"
        "const lines=[];console.error=(...a)=>lines.push(a.join(' '));\n"
        f"require({json.dumps(str(MODULE))});\n"
        "process.stdout.write(JSON.stringify({lines,control:typeof window.JarvisBoardsControl}));",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert result["control"] == "undefined"
    assert len(result["lines"]) == 1 and "boards.install_failed" in result["lines"][0]
    assert "boards_host_missing" in result["lines"][0] and "#boardsHud" in result["lines"][0]
