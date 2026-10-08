"""Ouvrir, fermer, plein écran, Échap, lecture et canal de commandes de l'explorateur de variantes, par node (studio de présentation, Slice 18).

Épinglé : l'ouverture refusée pendant une lecture (cause dite) et la fermeture quand une lecture démarre ; le plein écran armé par la voix, entré par
un clic, refusé, indisponible ; Échap imbriqué (menu, boîte, explorateur) et le focus rendu à celui qui a ouvert ; le reste de la page inerte
puis rendu ; aucun minuteur ne survit à la fermeture ; le canal long-poll de la page (commande, reçu, panne, onglet caché) ; le rapport d'état
qui ne porte jamais un titre.
"""

from __future__ import annotations

from tests.fakes.explorer_js import run_ui


def test_opening_while_a_run_plays_is_refused_with_its_cause_and_builds_nothing(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
player.playing=true;
const ex=make();
const result=await ex.open({presentation_id:PID});
return {result,hostBuilt:!!host(),requests:world.calls.length,toast:env.toasts.map(t=>[t.title,t.kind]),open:ex.isOpen(),logs:env.logs.map(l=>l[1]).filter(l=>l.includes('open_refused'))};
""")
    assert out["result"]["state"] == "refused" and out["result"]["code"] == "explorer_run_in_progress"
    assert "Une lecture est en cours" in out["result"]["reason"] and "outil d'édition" in out["result"]["reason"]
    assert out["hostBuilt"] is False and out["requests"] == 0 and out["open"] is False
    assert out["toast"] == [["Explorateur de variantes", "warn"]] and len(out["logs"]) == 1


def test_a_run_that_starts_while_open_closes_the_explorer_and_says_so_within_two_seconds(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
const button=doc.createElement('button');button.id='opener';doc.body.appendChild(button);button.focus();
const {ex}=await opened();
const before={open:ex.isOpen(),inert:doc.body.children.filter(n=>n.inert).length};
world.runningNow=true;                    /* started by the voice: the page's player has not polled yet */
await env.advance(2100);
return {before,open:ex.isOpen(),hidden:host().hidden,inert:doc.body.children.filter(n=>n.inert).length,toast:env.toasts.map(t=>t.sub),
  focus:doc.activeElement.id,timers:env.pendingTimers()};
""")
    assert out["before"]["open"] is True and out["before"]["inert"] >= 1
    assert out["open"] is False and out["hidden"] is True and out["inert"] == 0
    assert out["toast"] == ["Une lecture a démarré : l'explorateur s'est fermé."] and out["focus"] == "opener"
    assert out["timers"] == 0, "no timer outlives the explorer"


def test_a_run_seen_by_the_player_closes_it_at_once_on_the_next_check(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
const {ex}=await opened();
player.playing=true;
await env.advance(2100);
return {open:ex.isOpen(),requests:world.calls.filter(c=>c.url.endsWith('/playback')).length};
""")
    assert out["open"] is False


def test_unknown_presentation_and_a_broken_core_are_refused_with_distinct_codes_and_leave_the_page_usable(tmp_path):
    out = run_ui(tmp_path, """
seed(2);
const ex=make();
const unknownId='pst_'+'f'.repeat(32);
const unknown=await ex.open({presentation_id:unknownId});
const afterUnknown={hidden:host()?host().hidden:null,inert:doc.body.children.filter(n=>n.inert).length,open:ex.isOpen()};
world.failNext.push({match:u=>u.includes('/graph'),status:500,body:{error:{code:'presentation_studio_corrupt_document',message:'x'}}});
const broken=await ex.open({presentation_id:PID});
const bad=await ex.open({presentation_id:'../x'});
const badVariant=await ex.open({presentation_id:PID,variant_id:'nope'});
return {unknown,afterUnknown,broken,bad,badVariant,toasts:env.toasts.map(t=>t.title),errors:env.logs.filter(l=>l[0]==='error').length,timers:env.pendingTimers()};
""")
    assert out["unknown"]["code"] == "explorer_unknown_presentation" and out["broken"]["code"] == "explorer_load_failed"
    assert "illisible ou incohérent" in out["broken"]["reason"]
    assert out["afterUnknown"] == {"hidden": True, "inert": 0, "open": False}
    assert out["bad"]["code"] == "explorer_unknown_presentation" and out["badVariant"]["code"] == "explorer_unknown_presentation"
    assert out["errors"] >= 2 and out["timers"] == 0


def test_a_clicked_fullscreen_enters_a_voice_request_arms_and_the_mode_is_always_the_one_observed(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
const entered=await opened();
const a={result:entered.result,chip:q('.jvx-top .jvx-chip').textContent,fsButton:q('.jvx-top-actions .jvx-btn span').textContent,element:doc.fullscreenElement===host(),
  calls:fsFake.calls.map(c=>[c.object_id,c.keys])};
entered.ex.destroy();
fsFake.mode='arm';fsFake.calls.length=0;
const armed=await opened({via:'command'});
const b={result:armed.result,chip:q('.jvx-top .jvx-chip').textContent,visible:!host().hidden,element:doc.fullscreenElement===host(),tone:q('.jvx-top .jvx-chip').getAttribute('data-tone')};
armed.ex.destroy();fsFake.armed=null;
fsFake.mode='unsupported';
const unsupported=await opened();
const c={result:unsupported.result,chip:q('.jvx-top .jvx-chip').textContent,visible:!host().hidden};
unsupported.ex.destroy();
fsFake.mode='refuse';
const refused=await opened();
const d={result:refused.result,chip:q('.jvx-top .jvx-chip').textContent};
refused.ex.destroy();
fsFake.mode='throw';
const thrown=await opened();
const e={result:thrown.result,chip:q('.jvx-top .jvx-chip').textContent,errors:env.logs.filter(l=>l[0]==='error').map(l=>l[1]).join(' ')};
return {a,b,c,d,e};
""")
    assert out["a"]["result"]["mode"] == "fullscreen" and out["a"]["result"]["fullscreen"] == "entered" and out["a"]["element"] is True
    assert out["a"]["chip"] == "Plein écran" and out["a"]["fsButton"] == "Quitter le plein écran" and out["a"]["calls"] == [["studio-explorer", "none"]]
    assert out["b"]["result"]["mode"] == "fullscreen_armed" and out["b"]["result"]["fullscreen"] == "needs_gesture"
    assert out["b"]["visible"] is True and out["b"]["element"] is False and "clic" in out["b"]["chip"] and out["b"]["tone"] == "accent"
    assert out["c"]["result"]["mode"] == "windowed" and out["c"]["result"]["fullscreen"] == "unsupported" and "indisponible" in out["c"]["chip"]
    assert out["c"]["visible"] is True, "the explorer stays usable in a clearly labelled window"
    assert out["d"]["result"]["mode"] == "windowed" and "refusé" in out["d"]["chip"]
    assert out["e"]["result"]["mode"] == "windowed" and "fullscreen_failed" in out["e"]["errors"] and "boum" in out["e"]["errors"]


def test_leaving_fullscreen_keeps_the_explorer_open_in_the_window_and_says_so(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
const {ex}=await opened();
env.leaveFullscreen();await env.advance(100);
return {open:ex.isOpen(),chip:q('.jvx-top .jvx-chip').textContent,notice:noticeText(),button:q('.jvx-top-actions .jvx-btn span').textContent,mode:ex.state().mode};
""")
    assert out["open"] is True and out["mode"] == "windowed" and out["button"] == "Plein écran"
    assert "Plein écran quitté" in out["notice"] and "Échap le ferme" in out["notice"]


def test_the_fullscreen_button_toggles_and_a_needs_gesture_answer_points_at_the_prompt(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
fsFake.mode='refuse';
const {ex}=await opened();
fsFake.mode='arm';
q('.jvx-top-actions .jvx-btn').click();await env.advance(100);
const armed={notice:noticeText(),mode:ex.state().mode};
fsFake.armed=null;fsFake.mode='enter';
q('.jvx-top-actions .jvx-btn').click();await env.advance(100);
const entered=ex.state().mode;
q('.jvx-top-actions .jvx-btn').click();await env.advance(100);
return {armed,entered,after:ex.state().mode};
""")
    assert "Passer en plein écran" in out["armed"]["notice"] and out["armed"]["mode"] == "fullscreen_armed"
    assert out["entered"] == "fullscreen" and out["after"] == "windowed"


# ------------------------------------------------------------------ Échap imbriqué, focus, inert

def test_escape_closes_the_menu_then_the_dialog_then_the_explorer_and_the_focus_returns_to_the_opener(tmp_path):
    out = run_ui(tmp_path, """
seed(4);
const opener=doc.createElement('button');opener.id='opener';doc.body.appendChild(opener);
const other=doc.createElement('div');other.id='other';doc.body.appendChild(other);
opener.focus();
const {ex}=await opened();
const states=[];
const snap=(label)=>states.push([label,ex.isOpen(),ex.state().dialog,ex.state().menu]);
rowFor(2).focus();
env.key(doc.activeElement,'F2');                    /* a dialog */
const menuOverDialog=(()=>{env.key(doc.activeElement,'ContextMenu');return ex.state().menu})();
snap('dialog');
env.key(doc.activeElement,'Escape');snap('after esc 1');       /* closes the dialog */
rowFor(2).focus();
rowFor(2).dispatchEvent(new (require(process.env.JARVIS_EXPLORER_DOM).FakeEvent)('contextmenu',{clientX:90,clientY:90}));
snap('menu');
env.key(doc.activeElement,'Escape');snap('after esc 2');       /* closes the menu */
const focusOnRow=doc.activeElement.dataset&&doc.activeElement.dataset.id&&doc.activeElement.dataset.id.slice(-2);
env.key(doc.activeElement,'Escape');snap('after esc 3');       /* closes the explorer */
await env.advance(50);                                        /* a request already in flight settles (and is ignored) */
return {states,menuOverDialog,focusOnRow,focus:doc.activeElement.id,hidden:host().hidden,inert:doc.body.children.filter(n=>n.inert).length,timers:env.pendingTimers(),
  fsExit:doc.fullscreenElement};
""")
    assert out["menuOverDialog"] is False, "a menu cannot open over a dialog"
    assert out["states"] == [["dialog", True, "rename", False], ["after esc 1", True, None, False], ["menu", True, None, True],
                             ["after esc 2", True, None, False], ["after esc 3", False, None, False]]
    assert out["focusOnRow"] == "02", "the focus is back on the row after the menu"
    assert out["focus"] == "opener" and out["hidden"] is True and out["inert"] == 0 and out["timers"] == 0 and out["fsExit"] is None


def test_the_page_behind_is_inert_while_open_and_exactly_what_was_inert_before_is_left_alone(tmp_path):
    out = run_ui(tmp_path, """
seed(2);
const a=doc.createElement('div');a.id='a';doc.body.appendChild(a);
const b=doc.createElement('div');b.id='b';b.inert=true;doc.body.appendChild(b);
const toasts=doc.createElement('div');toasts.className='toasts';doc.body.appendChild(toasts);
const {ex}=await opened();
const during={a:a.inert,b:b.inert,toasts:toasts.inert,host:host().inert};
ex.close();
return {during,after:{a:a.inert,b:b.inert,toasts:toasts.inert}};
""")
    assert out["during"] == {"a": True, "b": True, "toasts": False, "host": False}
    assert out["after"] == {"a": False, "b": True, "toasts": False}, "an element that was inert before stays inert"


def test_tab_stays_inside_a_dialog_and_the_destructive_button_is_never_first(tmp_path):
    out = run_ui(tmp_path, """
seed(4);
const {ex}=await opened();
ex.select(vid(2));await env.advance(200);
act('archive').click();await env.advance(200);
const buttons=qa('.jvx-dialog-actions .jvx-btn').filter(b=>!b.hidden);
const order=buttons.map(b=>b.textContent);
const last=buttons[buttons.length-1];
last.focus();
const ev=env.key(last,'Tab');
const wrapped=ev.defaultPrevented&&doc.activeElement===buttons[0];
const ev2=env.key(buttons[0],'Tab',{shiftKey:true});
return {order,wrapped,back:ev2.defaultPrevented&&doc.activeElement===last,first:buttons[0].textContent};
""")
    assert out["order"][0] == "Annuler" and out["order"][-1].startswith("Archiver") and out["wrapped"] is True and out["back"] is True


# ------------------------------------------------------------------ rapport d'état et canal de commandes

def test_the_state_report_carries_ids_and_numbers_never_titles(tmp_path):
    out = run_ui(tmp_path, """
seed(4);
world.live[1].title='TITRE-SECRET';
const {ex}=await opened({},{report:undefined});
await env.advance(500);
ex.select(vid(2));await env.advance(500);
ex.close();await env.advance(500);
const reports=world.calls.filter(c=>c.url.endsWith('/explorer/state')).map(c=>c.body);
return {reports,text:JSON.stringify(reports)};
""")
    reports = out["reports"]
    assert [r["open"] for r in reports] == [True, True, False], reports
    assert reports[0]["mode"] == "fullscreen" and reports[0]["fullscreen"] == "entered" and reports[0]["variant_number"] == 1
    assert reports[1]["variant_number"] == 2 and reports[1]["variant_id"].endswith("02") and reports[2]["fullscreen"] in ("exited", "entered")
    assert "TITRE-SECRET" not in out["text"]


def test_a_command_opens_and_closes_through_the_same_door_and_answers_with_the_observed_mode(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
const ex=make();
const opened1=await ex.handleCommand({id:'x'.repeat(32),action:'open',presentation_id:PID,variant_id:vid(2),fullscreen:true,arm_s:30});
await env.advance(300);
const sel=ex.state().selected.slice(-2);
const again=await ex.handleCommand({id:'y'.repeat(32),action:'open',presentation_id:PID,variant_id:vid(3),fullscreen:false});
const closed=await ex.handleCommand({id:'z'.repeat(32),action:'close'});
const closedAgain=await ex.handleCommand({id:'w'.repeat(32),action:'close'});
const bad=await ex.handleCommand({id:'v'.repeat(32),action:'dance'});
const garbage=await ex.handleCommand(null);
return {opened1,sel,again,closed,closedAgain,bad,garbage,open:ex.isOpen()};
""")
    assert out["opened1"]["state"] == "opened" and out["opened1"]["mode"] == "fullscreen" and out["opened1"]["variant_id"].endswith("02") and out["sel"] == "02"
    assert out["again"]["state"] == "opened" and out["again"]["variant_id"].endswith("03"), "a second open re-targets the open explorer"
    assert out["closed"] == {"state": "closed"} and out["closedAgain"] == {"state": "closed"} and out["open"] is False
    assert out["bad"]["state"] == "refused" and out["bad"]["code"] == "explorer_page_error" and out["garbage"]["state"] == "refused"


def test_the_page_poller_takes_a_command_applies_it_and_posts_the_receipt(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
const ex=make({report:false});
const channel=X.createCommandChannel({fetch:env.fetch,document:doc,explorer:ex,now:timers.now,setTimeout:timers.setTimeout,clearTimeout:timers.clearTimeout,
  log:(k,d,l)=>env.logs.push([l||'info','[studio-explorer] '+k+' '+JSON.stringify(d)]),pageId:'pageAAAA1111'});
const queue=[{id:'c'.repeat(32),action:'open',presentation_id:PID,variant_id:vid(2),fullscreen:true,arm_s:30,remaining_ms:3000}];
const receipts=[];
env.route(u=>u.startsWith('/api/presentation-studio/explorer/commands'),(u,rec)=>{
  if(rec.method==='GET'){const command=queue.shift()||null;return command?{status:200,body:{command}}:{status:200,body:{command:null},delay:5000}}
  receipts.push({url:u.split('/').pop(),body:rec.body});return {status:200,body:{command:'open'}};
});
channel.start();
await env.advance(1500);
const first=receipts.slice();
queue.push({id:'d'.repeat(32),action:'close'});
await env.advance(6500);
return {first,receipts,pollUrl:env.requests.find(r=>r.method==='GET'&&r.url.includes('/explorer/commands')).url,stats:channel.stats(),open:ex.isOpen()};
""")
    assert out["pollUrl"] == "/api/presentation-studio/explorer/commands?wait_s=25&page=pageAAAA1111&visible=1"
    first = out["first"][0]
    assert first["url"] == "c" * 32 and first["body"]["state"] == "opened" and first["body"]["mode"] == "fullscreen" and first["body"]["fullscreen"] == "entered"
    assert first["body"]["presentation_id"].endswith("1") and first["body"]["variant_id"].endswith("02")
    assert out["receipts"][1]["body"] == {"state": "closed"} and out["open"] is False
    assert out["stats"]["received"] == 2 and out["stats"]["answered"] == 2 and out["stats"]["receiptFailed"] == 0


def test_a_refused_command_is_answered_with_its_code_and_a_dead_server_backs_off_without_a_hot_loop(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
player.playing=true;
const ex=make({report:false});
const channel=X.createCommandChannel({fetch:env.fetch,document:doc,explorer:ex,now:timers.now,setTimeout:timers.setTimeout,clearTimeout:timers.clearTimeout,
  log:(k,d,l)=>env.logs.push([l||'info','[studio-explorer] '+k+' '+JSON.stringify(d)]),pageId:'pageAAAA1111'});
let phase='ok';const receipts=[];let polls=0;
env.route(u=>u.startsWith('/api/presentation-studio/explorer/commands'),(u,rec)=>{
  if(rec.method==='POST'){receipts.push(rec.body);return {status:200,body:{}}}
  polls++;
  if(phase==='ok'){phase='down';return {status:200,body:{command:{id:'e'.repeat(32),action:'open',presentation_id:PID,fullscreen:true}}}}
  return {status:503,body:{error:{code:'x',message:'down'}}};
});
channel.start();
await env.advance(20000);
return {receipts,polls,state:channel.state(),warns:env.logs.filter(l=>l[0]==='warn'&&l[1].includes('command_poll_failed')).length};
""")
    assert out["receipts"][0]["state"] == "refused" and out["receipts"][0]["code"] == "explorer_run_in_progress" and "outil d'édition" in out["receipts"][0]["reason"]
    assert out["polls"] <= 12, f"exponential backoff: {out['polls']} polls in 20 s"
    assert out["state"]["failures"] >= 3 and out["warns"] >= 1


def test_a_hidden_page_stops_polling_and_tells_the_server_so(tmp_path):
    out = run_ui(tmp_path, """
seed(2);
const ex=make({report:false});
const channel=X.createCommandChannel({fetch:env.fetch,document:doc,explorer:ex,now:timers.now,setTimeout:timers.setTimeout,clearTimeout:timers.clearTimeout,pageId:'pageAAAA1111'});
env.route(u=>u.startsWith('/api/presentation-studio/explorer/commands'),(u,rec)=>({status:200,body:{command:null},delay:3000}));
channel.start();await env.advance(1500);
const before=env.requests.length;
channel.setVisible(false);await env.advance(100);
const hiddenCalls=env.requests.slice(before).map(r=>r.url);
await env.advance(8000);
const stillQuiet=env.requests.length-before;
channel.setVisible(true);await env.advance(500);
return {hiddenCalls,stillQuiet,resumed:env.requests.length-before>stillQuiet};
""")
    assert any("visible=0" in call for call in out["hiddenCalls"]) and out["stillQuiet"] <= 2 and out["resumed"] is True


# ------------------------------------------------------------------ cohabitation et hygiène

def test_the_selection_seam_for_the_compare_slice_is_a_set_of_one_with_a_change_event(tmp_path):
    out = run_ui(tmp_path, """
seed(4);
const {ex}=await opened();
const seen=[];
const off=ex.onSelectionChange(ids=>seen.push(ids.map(i=>i.slice(-2))));
ex.select(vid(3));ex.select(vid(3));ex.select(vid(2));
off();ex.select(vid(4));
const sel=ex.selection().map(i=>i.slice(-2));
ex.close();
return {seen,sel,afterClose:ex.selection()};
""")
    assert out["seen"] == [["03"], ["02"]] and out["sel"] == ["04"] and out["afterClose"] == []


def test_the_source_never_builds_markup_from_text_and_the_stored_preferences_are_only_view_state():
    import re
    from tests.fakes.explorer_js import EXPLORER_JS
    code = re.sub(r"/\*.*?\*/", "", EXPLORER_JS.read_text(encoding="utf-8"), flags=re.S)
    for forbidden in ("innerHTML", "insertAdjacentHTML", "document.write", "outerHTML", "eval(", "new Function", "alert(", "confirm(", "prompt("):
        assert forbidden not in code, forbidden
    assert code.count("setItem") == 0, "storage goes through Core.writePrefs only (view preferences, try/catch)"
    assert "localStorage" in code and "catch" in code


def test_a_normal_session_leaves_no_console_error_and_closing_leaves_no_timer(tmp_path):
    out = run_ui(tmp_path, """
seed(8);
const {ex}=await opened();
ex.select(vid(4));await env.advance(300);
act('rename').click();await env.advance(50);
env.key(doc.activeElement,'Escape');
rowFor(5).dispatchEvent(new (require(process.env.JARVIS_EXPLORER_DOM).FakeEvent)('contextmenu',{clientX:90,clientY:90}));
env.key(doc.activeElement,'Escape');
await env.advance(5000);
ex.close();await env.advance(100);
return {errors:env.errors,logErrors:env.logs.filter(l=>l[0]==='error'||l[0]==='warn').map(l=>l[1]),timers:env.pendingTimers(),violations:doc.violations,
  infoKeys:[...new Set(env.logs.filter(l=>l[0]==='info').map(l=>l[1].split(' ')[1]))].sort()};
""")
    assert out["errors"] == [] and out["logErrors"] == [] and out["timers"] == 0 and out["violations"] == []
    assert {"opened", "closed", "preview_loaded", "menu_opened"} <= set(out["infoKeys"]), "the normal path is logged too"

def test_a_cancelled_or_expired_fullscreen_prompt_is_noticed_and_reported(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
fsFake.mode='arm';
const {ex}=await opened({},{report:undefined});
await env.advance(600);
const armed={mode:ex.state().mode,fullscreen:ex.state().fullscreen,chip:q('.jvx-top .jvx-chip').textContent};
fsFake.armed=null;                 /* the user clicked Annuler, or the 30 s ran out: nothing tells the page */
await env.advance(1500);
const after={mode:ex.state().mode,fullscreen:ex.state().fullscreen,chip:q('.jvx-top .jvx-chip').textContent};
const reports=world.calls.filter(c=>c.url.endsWith('/explorer/state')).map(c=>[c.body.mode,c.body.fullscreen]);
return {armed,after,reports,timers:(()=>{ex.close();return env.pendingTimers()})()};
""")
    assert out["armed"]["mode"] == "fullscreen_armed" and out["armed"]["fullscreen"] == "needs_gesture"
    assert out["after"]["mode"] == "windowed" and out["after"]["fullscreen"] == "exited" and out["after"]["chip"] == "Fenêtré"
    assert out["reports"][-1] == ["windowed", "exited"] and ["fullscreen_armed", "needs_gesture"] in out["reports"], "the agent's mirror follows the prompt"
