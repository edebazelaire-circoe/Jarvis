"""Reprise de la QA-1 de l'explorateur de variantes, par node (studio de présentation, Slice 18).

Épinglé ici : la lignée profonde reste lisible (pas d'indentation qui mange la ligne, titre sur deux lignes, chemin complet dans le détail, infobulle au titre
entier) ; aucune lecture d'une variante archivée même quand la relecture du graphe tarde (déterministe, avec un retard injecté) ; la garde « une lecture
tourne » interroge Core (le mutant « sans la garde de Core » ne survit plus) ; un échec reste affiché ; un formulaire n'est pas jeté par un changement de
présentation ; le message « la liste a changé » n'est pas dit deux fois ; la recherche par numéro ; la surface publique ne rend pas le contrôleur.
"""

from __future__ import annotations

import re

from tests.fakes.explorer_js import EXPLORER_JS, run_ui


def test_the_core_playback_guard_is_asked_on_open_and_the_page_player_alone_is_not_enough(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
world.runningNow=true;                       /* a run started by the voice; the page's player (polling every 5 s at rest) has not seen it */
const ex=make();
const direct=await ex.open({presentation_id:PID});
const viaCommand=await ex.handleCommand({id:'x'.repeat(32),action:'open',presentation_id:PID,fullscreen:true});
const graphReads=world.calls.filter(c=>c.url.includes('/graph')).length;
const playbackAsks=world.calls.filter(c=>c.url.includes('/playback')).length;
world.runningNow=false;
const later=await ex.open({presentation_id:PID});
return {direct,viaCommand,graphReads,playbackAsks,hostBuilt:!!host()&&!host().hidden,later:later.state};
""")
    assert out["direct"]["code"] == "explorer_run_in_progress" and out["viaCommand"]["code"] == "explorer_run_in_progress"
    assert out["graphReads"] == 0 and out["playbackAsks"] == 2, "refused before the graph is read: Core was asked twice (once per attempt)"
    assert out["later"] == "opened"


def test_no_variant_is_read_in_the_gap_between_the_write_and_the_graph_reread(tmp_path):
    out = run_ui(tmp_path, """
seed(6);
const {ex}=await opened();
ex.select(vid(4));await env.advance(300);
rowFor(4).focus();env.key(doc.activeElement,'Delete');await env.tick();await env.tick();
world.delays.push({match:u=>u.includes('/graph'),ms:1200});     /* the graph reread after the archive arrives late */
const mark=world.calls.length;
q('.jvx-dialog-actions [data-primary]').click();
await env.advance(300);                                         /* the archive answered; the page is waiting for the graph */
ex.select(vid(5));                                              /* the user (or a key) lands on another variant of the archived set in the gap ... */
await env.advance(600);
const reads=()=>world.calls.slice(mark).filter(c=>new RegExp('variants/psv_[0-9]+$').test(c.url)&&c.method==='GET').map(c=>Number(c.url.slice(-2)));
const gap=reads();
await env.advance(3000);
return {gap,all:reads(),errors:env.logs.filter(l=>l[0]==='warn'||l[0]==='error').map(l=>l[1]),archived:world.archived.length,state:ex.state().preview.status};
""")
    assert 4 not in out["gap"] and 5 not in out["gap"], out
    assert 4 not in out["all"] and 5 not in out["all"] and out["errors"] == [] and out["archived"] == 2 and out["state"] == "ready"


def test_a_preview_timer_that_fires_after_the_variant_left_the_graph_asks_for_nothing(tmp_path):
    out = run_ui(tmp_path, """
seed(5);
const {ex}=await opened();
ex.select(vid(3));                                  /* the read of #3 is armed */
world.live=world.live.filter(n=>n.variant_id!==vid(3));    /* the voice archived it: the page's graph is now stale, but a quick reread lands first */
await ex.refresh();
await env.advance(600);
const reads=world.calls.filter(c=>new RegExp('variants/psv_[0-9]+$').test(c.url)&&c.method==='GET').map(c=>Number(c.url.slice(-2)));
return {reads,logs:env.logs.map(l=>l[1]).filter(l=>l.includes('preview_skipped')||l.includes('preview_failed')),errors:env.logs.filter(l=>l[0]==='error').length};
""")
    assert 3 not in out["reads"][1:], out


def test_a_failure_stays_until_dismissed_and_a_new_failure_replaces_it(tmp_path):
    out = run_ui(tmp_path, """
seed(4);
const {ex}=await opened();
ex.select(vid(2));await env.advance(200);
world.failNext.push({match:u=>u.endsWith('/activate'),reply:{reject:'fetch failed'}});
act('activate').click();await env.advance(300);
const failed=noticeText();
act('rename').click();await env.advance(50);env.key(doc.activeElement,'Escape');   /* ordinary messages ... */
world.add(2);world.revision+=1;await env.advance(10200);                            /* ... the 10 s poll noticing a change elsewhere ... */
const kept=noticeText();
q('.jvx-notice .jvx-btn-icon').click();await env.advance(10);
const hidden=q('.jvx-notice').hidden;
world.add(2);world.revision+=1;await env.advance(10200);
return {failed,kept,hidden,after:noticeText(),logs:env.logs.map(l=>l[1]).filter(l=>l.includes('notice_kept')).length};
""")
    assert "Core est injoignable" in out["failed"] and out["kept"] == out["failed"], "the poll's «changé ailleurs» did not overwrite the failure"
    assert out["hidden"] is True and "changé ailleurs" in out["after"] and out["logs"] >= 1


def test_a_voice_switch_to_another_presentation_does_not_throw_away_a_typed_form(tmp_path):
    out = run_ui(tmp_path, """
seed(4);
const {ex}=await opened();
rowFor(2).focus();env.key(doc.activeElement,'F2');
q('#jvxTitleInput').value='Titre à moitié tapé';
const other=await ex.handleCommand({id:'z'.repeat(32),action:'open',presentation_id:'pst_'+'f'.repeat(32)});
const same=await ex.handleCommand({id:'y'.repeat(32),action:'open',presentation_id:PID});
return {other,same:same.state,dialog:ex.state().dialog,typed:q('#jvxTitleInput').value,open:ex.isOpen(),notice:noticeText()};
""")
    assert out["other"]["state"] == "refused" and out["other"]["code"] == "explorer_dialog_open" and "formulaire" in out["other"]["reason"]
    assert out["dialog"] == "rename" and out["typed"] == "Titre à moitié tapé" and out["open"] is True and out["same"] == "opened"


def test_the_stale_set_message_is_said_once_under_the_archive_dialog(tmp_path):
    out = run_ui(tmp_path, """
seed(6);
const {ex}=await opened();
ex.select(vid(4));await env.advance(200);
act('archive').click();await env.advance(200);
world.add(4);world.revision+=1;
q('.jvx-dialog-actions [data-primary]').click();await env.advance(500);
return {warns:qa('.jvx-warnbox').length,noticeHidden:q('.jvx-notice').hidden,warn:q('.jvx-warnbox').textContent};
""")
    assert out["warns"] == 1 and out["noticeHidden"] is True and "Rien n'a été archivé" in out["warn"]


def test_typing_a_number_goes_to_that_variant_and_the_buffer_resets_after_a_pause(tmp_path):
    out = run_ui(tmp_path, """
seed(14,'fan');
const {ex}=await opened();
rowFor(1).focus();
const at=()=>Number(doc.activeElement.dataset.id.slice(-2));
env.key(doc.activeElement,'1');const one=at();            /* next row starting with 1 after the focused one: #10 */
env.key(doc.activeElement,'2');const twelve=at();         /* 12 */
await env.advance(900);
env.key(doc.activeElement,'7');const seven=at();
env.key(doc.activeElement,'9');const none=at();           /* 79: nothing starts with it: the focus stays */
const selectedStill=ex.state().selected.slice(-2);
return {one,twelve,seven,none,selectedStill,posts:world.calls.filter(c=>c.method==='POST').length,narrow:C.typeAhead([],0,'1'),letters:C.typeAhead([{id:'a',node:{variant_number:1}}],0,'a')};
""")
    assert (out["one"], out["twelve"], out["seven"], out["none"]) == (10, 12, 7, 7) and out["selectedStill"] == "01"
    assert out["posts"] == 0 and out["narrow"] is None and out["letters"] is None, "digits only: the letters stay the action shortcuts"


def test_a_sixty_deep_chain_keeps_the_title_room_and_names_the_whole_path(tmp_path):
    out = run_ui(tmp_path, """
seed(60,'chain');
const {ex}=await opened();
const tree=q('.jvx-tree');tree.clientHeight=48*70;tree.clientWidth=300;
ex.repaint();
const rows=rowsOf();
const px=s=>parseFloat(s)||0;
const rails=rows.map(r=>px(r.querySelector('.jvx-rail').style._v.width||r.querySelector('.jvx-rail').style.width));
ex.select(vid(40));await env.advance(300);
const last=rowFor(60);
return {maxRail:Math.max(...rails),limit:300*0.25,deepFlags:[rows[1].dataset.deep,rows[5].dataset.deep],chip:[rowFor(2).querySelector('.jvx-depth').hidden,last.querySelector('.jvx-depth').textContent],
  tip:last.getAttribute('title'),path:qa('.jvx-path-item').length,pathTitle:q('.jvx-path').title.length,lastItem:q('.jvx-path-last').textContent,
  twist:rowFor(1).querySelector('.jvx-twist').getAttribute('aria-hidden')};
""")
    assert out["maxRail"] <= out["limit"], "the indentation never takes more than a quarter of the row"
    assert out["deepFlags"] == ["false", "true"] and out["chip"][0] is True and out["chip"][1] == "⋯ ›59"
    assert out["tip"].startswith("V" ) and "#60" in out["tip"]
    assert out["path"] == 40 and out["lastItem"].startswith("#40 ") and out["twist"] == "true"


def test_the_public_page_surface_does_not_hand_out_the_controller():
    source = re.sub(r"/\*.*?\*/", "", EXPLORER_JS.read_text(encoding="utf-8"), flags=re.S)
    install = source[source.index("window.JarvisStudioExplorer=Object.freeze"):]
    assert "instance:" not in install and "handleCommand" not in install and "runAction" not in install
    for name in ("open", "close", "isOpen", "state", "selection", "onSelectionChange", "select", "refresh", "stats", "inspectTree", "repaint"):
        assert f"{name}:" in install or f"{name}," in install, name
