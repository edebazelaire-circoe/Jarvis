"""Ce que l'explorateur de variantes montre, et comment on s'y déplace, par node (studio de présentation, Slice 18).

Même banc que `test_presentation_studio_explorer_js.py` (vrai module, faux DOM, Core minuscule). Ici : l'archive repliée, le texte d'auteur hostile,
64 variantes dans une petite fenêtre, 60 niveaux, les plis mémorisés, le marqueur de lecture, les touches de l'arbre ARIA, l'aperçu qui LIT sans
jamais écrire, la navigation entre scènes, la direction artistique en lecture seule.
"""

from __future__ import annotations

from tests.fakes.explorer_js import run_ui

FAKE_EVENT = "const {FakeEvent}=require(process.env.JARVIS_EXPLORER_DOM);"


def test_the_archive_section_is_collapsed_counted_and_its_variants_have_no_preview(tmp_path):
    out = run_ui(tmp_path, """
seed(6);
world.archived.push(...world.live.splice(3,3));   /* 4, 5, 6 archived */
const {ex}=await opened();
const toggle=q('.jvx-archive-toggle');
const closed={expanded:toggle.getAttribute('aria-expanded'),label:q('.jvx-archive-toggle span').textContent,treeHidden:q('.jvx-archive .jvx-tree').hidden};
toggle.click();await env.advance(50);
const archivedRows=rowsOf(q('.jvx-archive .jvx-tree'));
const open={expanded:toggle.getAttribute('aria-expanded'),rows:archivedRows.length,labels:archivedRows.map(r=>r.getAttribute('aria-label')),
  levels:archivedRows.map(r=>r.getAttribute('aria-level'))};
archivedRows[0].click();await env.advance(300);
return {closed,open,selected:ex.state().selected.slice(-2),veil:q('.jvx-stage-veil strong').textContent,veilText:q('.jvx-stage-veil span').textContent,
  actions:qa('.jvx-actions .jvx-btn').map(b=>b.dataset.act),reads:world.calls.filter(c=>c.url.includes('/variants/')&&c.method==='GET').map(c=>c.url.slice(-8))};
""")
    assert out["closed"] == {"expanded": "false", "label": "Archivées (3)", "treeHidden": True}
    assert out["open"]["expanded"] == "true" and out["open"]["rows"] == 3 and out["open"]["labels"][0].endswith("archivée")
    assert out["selected"] == "04" and "archivée" in out["veil"] and "restaurez-la" in out["veilText"]
    assert out["actions"] == ["restore", "restore_all"] and "00000004" not in out["reads"], "an archived variant is never read for a preview"


def test_hostile_titles_rationales_are_text_never_markup(tmp_path):
    out = run_ui(tmp_path, """
seed(7);
const hostile=['<img src=x onerror=alert(1)>','a\\u0000b\\u202eevil','مرحبا بالعالم','🎨'.repeat(300),'x'.repeat(100000),'"><script>alert(1)</script>','{{7*7}} ${7*7}'];
world.live.forEach((n,i)=>{n.title=hostile[i%hostile.length];n.rationale=hostile[(i+3)%hostile.length]});
const {ex}=await opened();
const rows=rowsOf();
const tags=new Set();env.walk(host(),n=>tags.add(n.tagName));
const titles=rows.map(r=>r.querySelector('.jvx-rowtitle').textContent);
const tips=rows.map(r=>r.getAttribute('title'));
ex.select(vid(2));await env.advance(300);
return {tags:[...tags],titles,tips,dirs:rows.map(r=>r.querySelector('.jvx-rowtitle').getAttribute('dir')),meta:q('.jvx-meta-title').textContent.length,
  rationale:q('.jvx-rationale').textContent.length,violations:doc.violations,
  longest:Math.max(...titles.map(t=>Array.from(t).length)),nul:titles.concat(tips).some(t=>/[\\u0000\\u202e]/.test(t)),errors:env.errors};
""")
    assert out["violations"] == [] and out["errors"] == []
    assert "SCRIPT" not in out["tags"] and "IMG" not in out["tags"], "no markup was ever built from author text"
    assert "<img src=x onerror=alert(1)>" in out["titles"][0], "the hostile title is displayed as plain text"
    assert out["longest"] <= 80 and out["nul"] is False and set(out["dirs"]) == {"auto"}
    assert all(len(tip) <= 800 for tip in out["tips"]) and out["meta"] <= 100 and out["rationale"] <= 601


def test_sixty_four_live_variants_are_drawn_through_a_small_window_with_stable_rows(tmp_path):
    out = run_ui(tmp_path, FAKE_EVENT + """
seed(64,'fan');
const {ex}=await opened();
const tree=q('.jvx-tree');tree.clientHeight=480;ex.ui().liveTree.repaint();
const pool0=ex.stats().pool;
const scroll=async(top)=>{tree.scrollTop=top;tree.dispatchEvent(new FakeEvent('scroll',{bubbles:false}));await env.advance(40)};
await scroll(48*30);
const ns=numbers();
const afterScroll={first:ns.find(n=>n>1),count:rowsOf().length,pool:ex.stats().pool,domOrder:ns.every((n,i)=>i===0||n>ns[i-1])};
await scroll(0);
return {pool0,afterScroll,backToTop:rowsOf().length,height:q('.jvx-spacer').style._v.height||q('.jvx-spacer').style.height,
  aria:[rowFor(1).getAttribute('aria-setsize'),rowFor(2).getAttribute('aria-setsize'),rowFor(2).getAttribute('aria-posinset')],
  renderMs:ex.stats().lastRenderMs};
""")
    assert out["pool0"] <= 17, f"only the visible rows (10) plus the margin are drawn, not 64: {out['pool0']}"
    assert out["afterScroll"]["first"] >= 25 and out["afterScroll"]["count"] <= 23 and out["afterScroll"]["pool"] <= 23
    assert out["afterScroll"]["domOrder"] is True, "the DOM follows the tree order (screen readers walk it)"
    assert out["backToTop"] <= 17
    assert out["aria"] == ["1", "63", "1"], "aria-setsize/posinset stay correct although most rows are not in the DOM"
    assert out["renderMs"] < 200


def test_a_chain_of_sixty_levels_caps_the_indent_and_says_the_depth(tmp_path):
    out = run_ui(tmp_path, """
seed(60,'chain');
const {ex}=await opened();
const tree=q('.jvx-tree');tree.clientHeight=48*70;
ex.ui().liveTree.repaint();
const rows=rowsOf();
const last=rows[rows.length-1];
return {levels:[rows[0].getAttribute('aria-level'),last.getAttribute('aria-level')],rail:last.querySelector('.jvx-rail').style._v.width||last.querySelector('.jvx-rail').style.width,
  depthChip:[rows[5].querySelector('.jvx-depth').hidden,last.querySelector('.jvx-depth').hidden,last.querySelector('.jvx-depth').textContent],
  label:last.getAttribute('aria-label'),count:rows.length};
""")
    assert out["levels"] == ["1", "60"] and out["count"] == 60
    assert out["depthChip"] == [True, False, "⋯ ›59"] and "Variante 60" in out["label"]


def test_folds_are_remembered_per_presentation_and_a_blocked_storage_costs_nothing_else(tmp_path):
    out = run_ui(tmp_path, """
seed(6);
const a=await opened();
rowFor(1).querySelector('.jvx-twist').click();await env.advance(50);
const folded=numbers();
const saved=JSON.parse(win.localStorage.getItem('jarvis.studio_explorer.ui'));
a.ex.close();
const b=await opened();
const again=numbers();
b.ex.close();
win.storageBlocked=true;
const c=await opened();
rowFor(1).querySelector('.jvx-twist').click();await env.advance(50);
return {folded,saved:{keys:Object.keys(saved),collapsed:saved.collapsed[PID].length},again,blocked:numbers(),errors:env.errors,
  consoleErrors:env.logs.filter(l=>l[0]==='error')};
""")
    assert out["folded"] == [1] and out["again"] == [1], "the fold survives a close and an open"
    assert sorted(out["saved"]["keys"]) == ["archivedOpen", "collapsed", "last"] and out["saved"]["collapsed"] == 1
    assert out["errors"] == [] and out["consoleErrors"] == []


def test_the_variant_in_playback_and_its_ancestors_are_flagged(tmp_path):
    out = run_ui(tmp_path, """
seed(6);
const {ex}=await opened();
globalThis.JarvisStudioPlayer={view:()=>({running:true,phase:'playing',presentation_id:PID,variant_id:vid(3)})};
ex.ui().liveTree.repaint();
const flags=rowsOf().map(r=>[Number(r.dataset.id.slice(-2)),r.querySelector('.jvx-flag').textContent]);
return {flags,label:rowFor(3).getAttribute('aria-label')};
""")
    flagged = {n for n, text in out["flags"] if text == "En lecture"}
    assert flagged == {1, 2, 3}, "the played variant and the ancestors whose archive it would block"
    assert "en cours de lecture" in out["label"]


# ------------------------------------------------------------------ clavier

def test_tree_keys_move_the_focus_one_tab_stop_and_enter_selects(tmp_path):
    out = run_ui(tmp_path, """
seed(8);
const {ex}=await opened();
const stops=()=>rowsOf().filter(r=>r.getAttribute('tabindex')==='0').map(r=>Number(r.dataset.id.slice(-2)));
const focused=()=>doc.activeElement.dataset&&doc.activeElement.dataset.id?Number(doc.activeElement.dataset.id.slice(-2)):null;
const log=[];
const press=(k,m)=>{env.key(doc.activeElement,k,m);log.push([k,focused()])};
rowFor(1).focus();
press('ArrowDown');press('ArrowDown');press('End');press('Home');
press('ArrowRight');       /* 1 is expanded: first child */
press('ArrowRight');       /* 2 is expanded: its child 3 */
press('ArrowLeft');        /* 3 is a leaf: parent 2 */
press('ArrowLeft');        /* 2 expanded: collapses, stays */
const collapsed=numbers();
press('ArrowRight');       /* expands again */
press('ArrowDown');press('ArrowDown');
const selectedBefore=ex.state().selected.slice(-2);
const focusRow=focused();
press('Enter');
await env.advance(300);
return {log,stops:stops(),collapsed,selectedBefore,after:ex.state().selected.slice(-2),focusRow,focusStays:focused(),
  writes:world.calls.filter(c=>c.method!=='GET').length,expanded:rowFor(2).getAttribute('aria-expanded')};
""")
    assert out["log"] == [["ArrowDown", 2], ["ArrowDown", 3], ["End", 8], ["Home", 1], ["ArrowRight", 2], ["ArrowRight", 3], ["ArrowLeft", 2],
                          ["ArrowLeft", 2], ["ArrowRight", 2], ["ArrowDown", 3], ["ArrowDown", 4], ["Enter", 4]]
    assert 3 not in out["collapsed"] and 2 in out["collapsed"], "collapsing 2 hides its child 3"
    assert out["selectedBefore"] == "01" and out["after"] == "04", "arrows move the focus, Enter selects"
    assert out["stops"] == [out["focusStays"]] == [4], "exactly one tab stop (roving tabindex), on the focused row"
    assert out["writes"] == 0, "browsing the tree never writes"


def test_the_shortcut_keys_open_the_same_actions_as_the_buttons(tmp_path):
    out = run_ui(tmp_path, """
seed(6);
const {ex}=await opened();
const dialogs=[];
const go=async(key,mods)=>{rowFor(4).focus();env.key(doc.activeElement,key,mods);await env.advance(120)};
await go('F2');dialogs.push(ex.state().dialog);env.key(doc.activeElement,'Escape');
await go('n');dialogs.push(ex.state().dialog);env.key(doc.activeElement,'Escape');
await go('Delete');dialogs.push(ex.state().dialog);
const planned=world.calls.filter(c=>c.url.endsWith('/archive-plan')).length;
env.key(doc.activeElement,'Escape');
await go('ContextMenu');dialogs.push(ex.state().menu);env.key(doc.activeElement,'Escape');
await go('a');await env.advance(200);
return {dialogs,planned,activations:world.calls.filter(c=>c.url.endsWith('/activate')).length,active:ex.state().active.slice(-2),
  posts:world.calls.filter(c=>c.method==='POST').map(c=>c.url.split('/').pop())};
""")
    assert out["dialogs"] == ["rename", "branch", "archive", True]
    assert out["planned"] == 1 and out["active"] == "04" and out["activations"] == 1
    assert out["posts"] == ["archive-plan", "activate"], "the archive stayed at the plan; the only write is the activation"


def test_a_key_typed_in_a_dialog_field_never_triggers_a_tree_shortcut(tmp_path):
    out = run_ui(tmp_path, """
seed(4);
const {ex}=await opened();
rowFor(2).focus();
env.key(doc.activeElement,'F2');
const input=q('#jvxTitleInput');
input.focus();
for(const k of ['a','n','Delete','F2','ArrowDown'])env.key(input,k);
await env.advance(100);
return {dialog:ex.state().dialog,posts:world.calls.filter(c=>c.method==='POST').length,focused:doc.activeElement.id,selected:ex.state().selected.slice(-2)};
""")
    assert out == {"dialog": "rename", "posts": 0, "focused": "jvxTitleInput", "selected": "02"}


# ------------------------------------------------------------------ aperçu : lire, jamais écrire

def test_selecting_reads_the_variant_and_writes_nothing_and_a_burst_makes_one_read(tmp_path):
    out = run_ui(tmp_path, """
seed(8);
const {ex}=await opened();
const before=world.calls.length;
for(const n of [2,3,4,5,6])ex.select(vid(n));
await env.advance(400);
const calls=world.calls.slice(before);
const reads=calls.filter(c=>c.method==='GET'&&/variants\\/psv_\\d+$/.test(c.url)).map(c=>Number(c.url.slice(-2)));
return {reads,writes:calls.filter(c=>c.method!=='GET').map(c=>c.method+' '+c.url),state:ex.state().selected.slice(-2),mounted:prefabFake.mounts.slice(-1)[0].title};
""")
    assert out["writes"] == [] and out["reads"] == [6], "five selections in 120 ms: only the last variant is read"
    assert out["state"] == "06" and out["mounted"] == "Scène 1 de 6"


def test_scene_browsing_by_keys_buttons_and_the_strip_keeps_the_scene_across_variants(tmp_path):
    out = run_ui(tmp_path, """
seed(4);
const {ex}=await opened();
const title=()=>q('.jvx-scene-title').textContent;
const log=[title()];
const stage=q('.jvx-stage');
env.key(stage,'ArrowRight');log.push(title());
env.key(stage,'PageDown');log.push(title());
env.key(stage,'Home');log.push(title());
q('.jvx-scene[data-scene="pss_000000000003"]').click();log.push(title());
env.click(q('[aria-label="Scène précédente"]'));log.push(title());
const strip=qa('.jvx-scene').map(b=>[b.getAttribute('aria-selected'),b.getAttribute('tabindex'),b.getAttribute('aria-label')]);
ex.select(vid(3));await env.advance(300);
return {log,strip,sceneKept:q('.jvx-scene[aria-selected="true"]').dataset.scene,count:q('.jvx-stage-note > span').textContent};
""")
    assert out["log"] == ["Scène 1 de 1", "Scène 2 de 1", "Scène 3 de 1", "Scène 1 de 1", "Scène 3 de 1", "Scène 2 de 1"]
    assert out["strip"][1] == ["true", "0", "Scène 2, Scène 2 de 1, Chiffres"] and out["strip"][0][1] == "-1"
    assert out["sceneKept"] == "pss_000000000002", "the same scene is shown when another variant is chosen (compare seam)"


def test_a_scene_with_local_variants_says_so_without_listing_them_in_the_tree(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
const doc1=world.doc(vid(1));
doc1.scenes[0].scene_variants={current_id:'psx_000000000001',items:[{variant_id:'psx_000000000001'},{variant_id:'psx_000000000002'},{variant_id:'psx_000000000003'}]};
world.docs.set(vid(1),doc1);
const {ex}=await opened();
return {chips:qa('.jvx-stage-note .jvx-chip').map(c=>[c.textContent,c.hidden]),strip:q('.jvx-scene-b').textContent,rows:numbers()};
""")
    assert ["3 variantes locales", False] in out["chips"] and out["strip"] == "3 variantes" and out["rows"] == [1, 2, 3]


def test_the_preview_says_what_it_waits_for_how_long_and_offers_a_retry(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
const {ex}=await opened();
world.failNext.push({match:u=>/variants\\/psv_\\d+$/.test(u),reply:{hang:true}});
ex.select(vid(2));
await env.advance(3500);
const loading={title:q('.jvx-stage-veil strong').textContent,text:q('.jvx-stage-veil span').textContent};
await env.advance(8000);
const timedOut={title:q('.jvx-stage-veil strong').textContent,text:q('.jvx-stage-veil span').textContent,retry:!q('.jvx-stage-veil button').hidden};
q('.jvx-stage-veil button').click();await env.advance(400);
return {loading,timedOut,after:q('.jvx-stage-veil').hidden,mounted:prefabFake.mounts.slice(-1)[0].title};
""")
    assert out["loading"]["title"].startswith("Chargement") and "3 s" in out["loading"]["text"], out["loading"]
    assert out["timedOut"]["title"] == "Aperçu impossible" and "10 s" in out["timedOut"]["text"] and out["timedOut"]["retry"]
    assert out["after"] is True and out["mounted"] == "Scène 1 de 2", "Retry reads again and shows the scene"


def test_the_art_direction_chip_is_read_only_and_only_valid_colours_ever_reach_a_style(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
world.art.set(vid(1),{revision:4,profile:{name:'Cercle <b>sombre</b>',provenance:{origin:'generated',fallback:true,confidence:0.5},
  palette:{background:'#101820',surface:'url(javascript:alert(1))',text:'#eeeeee',accent:'#ff00aa',accent_alt:'red;background:url(x)'}}});
const {ex}=await opened();
const chip=qa('.jvx-chips .jvx-chip').map(c=>c.textContent);
const swatches=qa('.jvx-swatch').map(s=>s.style.background);
const glow=[host().style._v['--jvx-glow-a'],host().style._v['--jvx-glow-b']];
ex.select(vid(2));await env.advance(300);
const none=qa('.jvx-chips .jvx-chip').map(c=>c.textContent);
const tags=new Set();env.walk(host(),n=>tags.add(n.tagName));
return {chip,swatches,glow,none,posts:world.calls.filter(c=>c.method!=='GET').length,tags:[...tags]};
""")
    assert any("Cercle <b>sombre</b>" in text and "secours" in text for text in out["chip"]), out["chip"]
    assert out["swatches"] == ["#101820", "#eeeeee", "#ff00aa"], "only #rrggbb values become a colour"
    assert out["glow"] == ["#ff00aa", "#a78bfa"], "a hostile accent_alt and surface fall back to the default glow, never into a style"
    assert any("Sans direction artistique" in text for text in out["none"]) and out["posts"] == 0 and "B" not in out["tags"]


def test_a_missing_prefab_runtime_or_a_failing_mount_is_said_in_the_stage_not_swallowed(tmp_path):
    out = run_ui(tmp_path, """
seed(2);
prefabFake.failMount='cadre refusé';
const {ex}=await opened();
const failing={title:q('.jvx-stage-veil strong').textContent,text:q('.jvx-stage-veil span').textContent,errors:env.logs.filter(l=>l[0]==='error').map(l=>l[1]).join(' ')};
ex.destroy();
const none=make({prefabHost:null});
await none.open({presentation_id:PID});await env.advance(400);
return {failing,missing:{title:q('.jvx-stage-veil strong').textContent,text:q('.jvx-stage-veil span').textContent}};
""")
    assert out["failing"]["title"] == "Aperçu impossible" and "cadre refusé" in out["failing"]["text"] and "preview_mount_failed" in out["failing"]["errors"]
    assert out["missing"]["title"] == "Aperçu indisponible" and "runtime des prefabs" in out["missing"]["text"]
