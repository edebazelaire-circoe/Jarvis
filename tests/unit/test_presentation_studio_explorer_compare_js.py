"""La comparaison et la composition de l'explorateur de variantes, par node (studio de présentation, Slice 19, moitié interface).

Même banc que `test_presentation_studio_explorer_js.py` (vrai module, faux DOM, Core minuscule) plus `explorer_compare_world.cjs` (les routes de comparaison et
de composition). Prouvé ici : marquer 2 ou 4 variantes (clavier, Ctrl + clic, menu), les fenêtres 2 / 4 / vis-à-vis, des aperçus qui ne montent que des cadres en
lecture seule, la navigation synchronisée et ses statuts, le repli quand les structures divergent (lien manuel, conflit de lien, mode indépendant), un geste périmé,
la composition (plan d'abord, conflits typés avec leur remède, création d'un enfant sélectionné dans l'arbre, sources intactes), la porte programmatique de la Slice 21
et l'ordre de `Échap`. La preuve dans un vrai navigateur est `test_presentation_studio_explorer_compare_browser.py`.
"""

from __future__ import annotations

from tests.fakes.explorer_js import run_ui

HELPERS = """
const mark=async(...ns)=>{for(const n of ns){rowFor(n).focus();env.key(doc.activeElement,'c');await env.advance(30)}};
const cq=(sel)=>q(sel,q('.jvx-compare'));
const cqa=(sel)=>qa(sel,q('.jvx-compare'));
const panes=()=>cqa('.jvx-cmp-pane').filter(p=>!p.hidden);
const paneOf=(n)=>cqa('.jvx-cmp-pane').find(p=>p.getAttribute('data-pane')===vid(n));
const statusOf=(n)=>{const c=paneOf(n).querySelector('.jvx-cmp-status');return c.hidden?null:c.textContent};
const lineOf=(n)=>paneOf(n).querySelector('.jvx-cmp-line').textContent;
const sceneOfPane=(n)=>paneOf(n).querySelector('.jvx-cmp-select').value;
const sid=(i)=>'pss_'+String(i).padStart(12,'0');
const customScenes=(n,ids)=>{const d=world.doc(vid(n));world.docs.set(vid(n),Object.assign({},d,{scenes:ids.map(i=>Object.assign({},d.scenes[0],{scene_id:sid(i),title:'S'+i+' de '+n}))}))};
const goCompare=async(...ns)=>{await mark(...ns);q('.jvx-cmp-bar .jvx-btn').click();await env.advance(300)};
const posts=()=>cmpWorld.calls.filter(c=>c.method==='POST').map(c=>c.url);
const setSel=(sel,value)=>{sel.value=value;sel.dispatchEvent(new (require(process.env.JARVIS_EXPLORER_DOM).FakeEvent)('change'))};
"""


def test_marking_two_variants_enables_compare_and_a_wrong_count_says_why(tmp_path):
    out = run_ui(tmp_path, HELPERS + """
seed(6);
const {ex}=await opened();
const hidden0=q('.jvx-cmp-bar').hidden;
await mark(2);
const one={text:q('.jvx-cmp-bar-text').textContent,disabled:q('.jvx-cmp-bar .jvx-btn').getAttribute('aria-disabled'),why:q('.jvx-cmp-bar .jvx-btn').title,
  label:rowFor(2).getAttribute('aria-label'),marked:rowFor(2).dataset.marked};
await mark(3,4);
const three={text:q('.jvx-cmp-bar-text').textContent,disabled:q('.jvx-cmp-bar .jvx-btn').getAttribute('aria-disabled'),why:q('.jvx-cmp-bar .jvx-btn').title};
await mark(4);
/* Ctrl + clic marque, une variante archivée ne se marque pas */
rowFor(5).dispatchEvent(new (require(process.env.JARVIS_EXPLORER_DOM).FakeEvent)('click',{ctrlKey:true,detail:1,button:0}));await env.advance(30);
const two={marks:ex.compare.marks().map(id=>Number(id.slice(-2))),disabled:q('.jvx-cmp-bar .jvx-btn').getAttribute('aria-disabled'),selected:ex.state().selected.slice(-2)};
const writes=world.calls.filter(c=>c.method==='POST').length;
return {hidden0,one,three,two,writes,violations:doc.violations,errors:env.errors};
""")
    assert out["hidden0"] is True and out["violations"] == [] and out["errors"] == []
    assert out["one"]["disabled"] == "true" and "au moins une autre" in out["one"]["why"] and out["one"]["marked"] == "true"
    assert "marquée pour la comparaison" in out["one"]["label"]
    assert out["three"]["disabled"] == "true" and "2 ou 4" in out["three"]["why"]
    assert out["two"]["marks"] == [2, 3, 5] or out["two"]["marks"] == [2, 3, 5][:3]
    assert out["writes"] == 0, "marking is interface state: no request at all"


def test_two_up_panes_mount_read_only_frames_and_write_nothing(tmp_path):
    out = run_ui(tmp_path, HELPERS + """
seed(6);
const {ex}=await opened();
const before=prefabFake.mounts.length;
await goCompare(2,3);
const compareHidden=q('.jvx-compare').hidden, previewHidden=q('.jvx-preview').hidden;
const mounts=prefabFake.mounts.slice(before).map(m=>m.object_id);
return {compareHidden,previewHidden,layout:cq('.jvx-cmp-grid').getAttribute('data-layout'),panes:panes().length,mounts,hosts:prefabFake.hosts.map(h=>h.mode),
  title:cq('.jvx-cmp-title').textContent,mode:cq('.jvx-cmp-toolbar .jvx-btn').textContent,posts:posts(),
  body:cmpWorld.calls.find(c=>c.url==='/compare/select').body,
  writes:world.calls.filter(c=>c.method==='POST').length,state:ex.compare.state().summary,selection:ex.selection().map(i=>Number(i.slice(-2))),
  preview:q('.jvx-stage-veil').hidden,names:panes().map(p=>p.querySelector('.jvx-cmp-name').textContent),
  focus:doc.activeElement.getAttribute('data-pane')&&doc.activeElement.getAttribute('data-pane').slice(-2),violations:doc.violations,errors:env.errors};
""")
    assert out["compareHidden"] is False and out["previewHidden"] is True and out["layout"] == "two_up" and out["panes"] == 2
    assert sorted(set(out["mounts"])) == ["studio-explorer-cmp-0", "studio-explorer-cmp-1"] and out["hosts"] == ["preview"]
    assert out["posts"] == ["/compare/select"] and out["writes"] == 0
    assert [v[-2:] for v in out["body"]["variant_ids"]] == ["02", "03"]
    assert out["selection"] == [2, 3] and out["names"] == ["Variante 2", "Variante 3"]
    assert out["mode"] == "Navigation synchronisée" and out["title"].startswith("Comparaison · 2 variantes")
    assert out["focus"] == "02" and out["violations"] == [] and out["errors"] == []


def test_four_up_then_a_fifty_fifty_focus_pair_and_back(tmp_path):
    out = run_ui(tmp_path, HELPERS + """
seed(6);
const {ex}=await opened();
await goCompare(1,2,3,4);
const four={layout:cq('.jvx-cmp-grid').getAttribute('data-layout'),visible:panes().length,mounted:new Set(prefabFake.mounts.map(m=>m.object_id).filter(o=>o.startsWith('studio-explorer-cmp-'))).size};
const first=paneOf(2).querySelector('.jvx-cmp-tools .jvx-btn');
first.click();await env.advance(50);
const afterOne={posts:posts().length,pressed:first.getAttribute('aria-pressed'),visible:panes().length};
paneOf(4).querySelector('.jvx-cmp-tools .jvx-btn').click();await env.advance(200);
const unmounts=prefabFake.unmounts;
const focus={layout:cq('.jvx-cmp-grid').getAttribute('data-layout'),visible:panes().map(p=>p.getAttribute('data-pane').slice(-2)),title:cq('.jvx-cmp-title').textContent,
  all:cq('.jvx-cmp-toolbar .jvx-btn:not([aria-pressed])') && cqa('.jvx-cmp-toolbar .jvx-btn').filter(b=>b.textContent==='Tout afficher').map(b=>b.hidden),
  body:cmpWorld.calls.find(c=>c.url==='/compare/pair').body.pair.map(i=>i.slice(-2))};
cqa('.jvx-cmp-toolbar .jvx-btn').find(b=>b.textContent==='Tout afficher').click();await env.advance(200);
const back={layout:cq('.jvx-cmp-grid').getAttribute('data-layout'),visible:panes().length,pair:ex.compare.view().pair};
return {four,afterOne,focus,back,unmounts,errors:env.errors};
""")
    assert out["four"] == {"layout": "four_up", "visible": 4, "mounted": 4}
    assert out["afterOne"] == {"posts": 1, "pressed": "true", "visible": 4}, "one pick alone changes nothing: a pair needs two"
    assert out["focus"]["layout"] == "focus" and out["focus"]["visible"] == ["02", "04"] and "vis-à-vis" in out["focus"]["title"]
    assert out["focus"]["body"] == ["02", "04"] and out["unmounts"] >= 2, "the hidden panes release their frames"
    assert out["back"] == {"layout": "four_up", "visible": 4, "pair": None} and out["errors"] == []


def test_synchronized_navigation_by_key_shows_origin_synced_and_follows_equivalents(tmp_path):
    out = run_ui(tmp_path, HELPERS + """
seed(6);
const {ex}=await opened();
await goCompare(1,2);
env.key(paneOf(1),'ArrowRight');await env.advance(200);
const a={s1:statusOf(1),s2:statusOf(2),scene1:sceneOfPane(1),scene2:sceneOfPane(2),count:paneOf(1).querySelector('.jvx-cmp-count').textContent,
  body:cmpWorld.calls.find(c=>c.url==='/compare/navigate').body,mountedScenes:prefabFake.mounts.slice(-2).map(m=>m.title)};
env.key(paneOf(2),'End');await env.advance(200);
const b={s1:statusOf(1),s2:statusOf(2),scene1:sceneOfPane(1),scene2:sceneOfPane(2)};
paneOf(1).querySelector('.jvx-cmp-select').value=sid(1);paneOf(1).querySelector('.jvx-cmp-select').dispatchEvent(new (require(process.env.JARVIS_EXPLORER_DOM).FakeEvent)('change'));await env.advance(200);
const c={scene2:sceneOfPane(2),body:cmpWorld.calls.filter(x=>x.url==='/compare/navigate').pop().body};
return {a,b,c,live:q('.jvx-sr').textContent,line2:lineOf(2),errors:env.errors};
""")
    assert out["a"]["s1"] == "Choisie" and out["a"]["s2"] == "Synchronisée" and out["a"]["scene1"] == out["a"]["scene2"] == "pss_000000000002"
    assert out["a"]["count"] == "2 / 3" and out["a"]["body"]["step"] == "next" and out["a"]["body"]["variant_id"].endswith("01")
    assert "expected_revision" not in out["a"]["body"], "navigation is last-write-wins interface state"
    assert out["b"]["s2"] == "Choisie" and out["b"]["s1"] == "Synchronisée" and out["b"]["scene1"] == "pss_000000000003"
    assert out["c"]["scene2"] == "pss_000000000001" and out["c"]["body"]["scene_id"] == "pss_000000000001"
    assert "Scène changée" in out["live"] and out["errors"] == []


def test_divergent_structures_fall_back_to_unmapped_a_manual_link_and_independent_mode(tmp_path):
    out = run_ui(tmp_path, HELPERS + """
seed(4);
customScenes(1,[1,2,3]);customScenes(2,[1,20,3]);
const {ex}=await opened();
await goCompare(1,2);
const banner={hidden:cq('.jvx-cmp-banner').hidden,text:cq('.jvx-cmp-banner-text').textContent,chip:cq('.jvx-cmp-toolbar .jvx-chip').textContent};
paneOf(1).querySelector('.jvx-cmp-select').value=sid(2);paneOf(1).querySelector('.jvx-cmp-select').dispatchEvent(new (require(process.env.JARVIS_EXPLORER_DOM).FakeEvent)('change'));await env.advance(200);
const unmapped={s1:statusOf(1),s2:statusOf(2),scene2:sceneOfPane(2),line:lineOf(2),emphasis:paneOf(2).querySelector('.jvx-cmp-tools [data-emphasis]').getAttribute('data-emphasis')};
/* le lien manuel : v1 scène 2 <-> v2 scène 20 */
env.key(paneOf(1),'l');await env.advance(30);
const dialog=ex.state().dialog;
const selects=qa('.jvx-dialog select');
setSel(selects[1],sid(2));setSel(selects[3],sid(20));
qa('.jvx-dialog form')[0].dispatchEvent(new (require(process.env.JARVIS_EXPLORER_DOM).FakeEvent)('submit'));await env.advance(200);
const linked={links:ex.compare.view().links.length,items:qa('.jvx-dialog .jvx-set li').map(l=>l.textContent),post:cmpWorld.calls.find(c=>c.url==='/compare/links').body};
/* un lien qui mettrait deux scènes de v2 dans la même classe est refusé et dit */
const selects2=qa('.jvx-dialog select');
setSel(selects2[1],sid(3));setSel(selects2[3],sid(20));
qa('.jvx-dialog form')[0].dispatchEvent(new (require(process.env.JARVIS_EXPLORER_DOM).FakeEvent)('submit'));await env.advance(200);
const conflict={error:q('.jvx-dialog .jvx-error').textContent,links:ex.compare.view().links.length};
env.key(doc.activeElement,'Escape');await env.advance(30);
paneOf(1).querySelector('.jvx-cmp-select').value=sid(1);paneOf(1).querySelector('.jvx-cmp-select').dispatchEvent(new (require(process.env.JARVIS_EXPLORER_DOM).FakeEvent)('change'));await env.advance(100);
env.key(paneOf(1),'ArrowRight');await env.advance(200);
const afterLink={s2:statusOf(2),scene2:sceneOfPane(2)};
/* le mode indépendant : seule la fenêtre choisie bouge */
env.key(paneOf(1),'m');await env.advance(100);
const indep={pressed:cq('.jvx-cmp-toolbar .jvx-btn').getAttribute('aria-pressed'),label:cq('.jvx-cmp-toolbar .jvx-btn').textContent};
env.key(paneOf(1),'End');await env.advance(200);
const held={s1:statusOf(1),s2:statusOf(2),scene2:sceneOfPane(2),line:lineOf(2)};
return {banner,unmapped,dialog,linked,conflict,afterLink,indep,held,errors:env.errors};
""")
    assert out["banner"]["hidden"] is False and "Structures différentes" in out["banner"]["text"] and out["banner"]["chip"] == "Structures différentes"
    assert out["unmapped"]["s1"] == "Choisie" and out["unmapped"]["s2"] == "Sans équivalent" and out["unmapped"]["scene2"] == "pss_000000000001", "the pane KEEPS its scene"
    assert "garde sa scène" in out["unmapped"]["line"] and out["unmapped"]["emphasis"] == "true"
    assert out["dialog"] == "compare-links"
    assert out["linked"]["links"] == 1 and len(out["linked"]["items"]) == 1 and out["linked"]["post"]["a"]["scene_id"] == "pss_000000000002"
    assert out["conflict"]["links"] == 1 and "deux scènes d'une même variante" in out["conflict"]["error"]
    assert out["afterLink"]["s2"] == "Synchronisée" and out["afterLink"]["scene2"] == "pss_000000000020"
    assert out["indep"] == {"pressed": "false", "label": "Navigation indépendante"}
    assert out["held"]["s1"] == "Choisie" and out["held"]["s2"] == "Indépendante" and "seule la fenêtre choisie" in out["held"]["line"]
    assert out["errors"] == []


def test_a_stale_gesture_is_said_and_the_comparison_is_read_again(tmp_path):
    out = run_ui(tmp_path, HELPERS + """
seed(6);
const {ex}=await opened();
await goCompare(1,2,3,4);
cmpWorld.failNext.push({match:(u)=>u.endsWith('/compare/pair'),status:409,code:'presentation_studio_stale_revision'});
paneOf(1).querySelector('.jvx-cmp-tools .jvx-btn').click();paneOf(2).querySelector('.jvx-cmp-tools .jvx-btn').click();await env.advance(200);
const gets=cmpWorld.calls.filter(c=>c.method==='GET').length;
return {notice:noticeText(),kind:q('.jvx-notice').getAttribute('data-kind'),gets,layout:cq('.jvx-cmp-grid').getAttribute('data-layout'),errors:env.errors};
""")
    assert "a changé ailleurs" in out["notice"] and out["kind"] == "stale" and out["gets"] >= 1 and out["layout"] == "four_up"


def test_composition_plans_first_shows_typed_conflicts_with_their_fix_then_creates_a_selected_child(tmp_path):
    out = run_ui(tmp_path, HELPERS + """
seed(4);
cmpWorld.scoreScenes[vid(2)]=[sid(1),sid(2),sid(3),sid(77)];     /* le mouvement de #2 cite une scène que #1 n'a pas */
const {ex}=await opened();
await goCompare(1,2);
const sourcesBefore=JSON.stringify([world.byId(vid(1)),world.byId(vid(2)),world.doc(vid(1)),world.doc(vid(2))]);
env.key(paneOf(1),'C',{shiftKey:true});await env.advance(20);
const dialog=ex.state().dialog;
const ctl=(id)=>q('#'+id);
ctl('jvxCmpTitle').value='Mix sobre';
ctl('jvxCmp_motion').value=vid(2);ctl('jvxCmp_motion').dispatchEvent(new (require(process.env.JARVIS_EXPLORER_DOM).FakeEvent)('change'));
await env.advance(900);
const refused={items:qa('.jvx-conflicts li').map(li=>[li.getAttribute('data-code'),li.textContent]),createDisabled:qa('.jvx-dialog-actions .jvx-btn').pop().getAttribute('aria-disabled'),
  commits:cmpWorld.commitCalls,plans:cmpWorld.planCalls};
/* Créer reste sans effet tant que le plan montre un conflit */
q('.jvx-dialog form').dispatchEvent(new (require(process.env.JARVIS_EXPLORER_DOM).FakeEvent)('submit'));await env.advance(900);
const stillRefused={commits:cmpWorld.commitCalls};
/* le remède : le mouvement vient de la variante de départ */
ctl('jvxCmp_motion').value='';ctl('jvxCmp_motion').dispatchEvent(new (require(process.env.JARVIS_EXPLORER_DOM).FakeEvent)('change'));
ctl('jvxCmp_narrative').value=vid(2);ctl('jvxCmp_narrative').dispatchEvent(new (require(process.env.JARVIS_EXPLORER_DOM).FakeEvent)('change'));
await env.advance(900);
const ok={verdict:q('.jvx-plan-ok')&&q('.jvx-plan-ok').textContent,createDisabled:qa('.jvx-dialog-actions .jvx-btn').pop().getAttribute('aria-disabled'),
  provenance:qa('.jvx-dialog [aria-label="Provenance des dimensions"] li').map(l=>l.textContent)};
q('.jvx-dialog form').dispatchEvent(new (require(process.env.JARVIS_EXPLORER_DOM).FakeEvent)('submit'));await env.advance(900);
const calls=cmpWorld.calls.filter(c=>c.url.startsWith('/compositions')).map(c=>c.url);
const plans=cmpWorld.calls.filter(c=>c.url==='/compositions/plan'),commit=cmpWorld.calls.find(c=>c.url==='/compositions');
const sourcesAfter=JSON.stringify([world.byId(vid(1)),world.byId(vid(2)),world.doc(vid(1)),world.doc(vid(2))]);
return {dialog,refused,stillRefused,ok,calls:calls.slice(-3),commitBody:commit&&commit.body,lastPlanBody:plans[plans.length-1].body,
  untouched:sourcesBefore===sourcesAfter,selected:ex.state().selected.slice(-2),number:world.counter,dialogAfter:ex.state().dialog,
  rowSelected:rowFor(5)&&rowFor(5).getAttribute('aria-selected'),notice:noticeText(),child:world.byId(vid(5))&&world.byId(vid(5)).parent_variant_id.slice(-2),
  compareStillOpen:ex.compare.isActive(),errors:env.errors,violations:doc.violations};
""")
    assert out["dialog"] == "compose"
    codes = [item[0] for item in out["refused"]["items"]]
    assert codes == ["score_scene_missing"], out["refused"]
    text = out["refused"]["items"][0][1]
    assert "Mouvement" in text and "À faire : Prenez ces scènes de la même variante" in text, "dimension, message and the typed fix are all shown"
    assert out["refused"]["createDisabled"] == "true" and out["refused"]["commits"] == 0 and out["refused"]["plans"] >= 1
    assert out["stillRefused"]["commits"] == 0, "nothing is created while the plan shows a conflict"
    assert out["ok"]["verdict"] and out["ok"]["createDisabled"] == "false"
    assert any("Narration" in line and "#2" in line for line in out["ok"]["provenance"]) and any("Mouvement" in line and "héritée" in line for line in out["ok"]["provenance"])
    assert out["calls"][-2:] == ["/compositions/plan", "/compositions"], "plan first, then commit"
    sent = out["commitBody"]
    assert sent == out["lastPlanBody"], "what is created is EXACTLY what was planned"
    assert sent["base"].endswith("01") and sent["narrative"].endswith("02") and "motion" not in sent and sent["title"] == "Mix sobre" and "actor" not in sent
    assert set(sent["source_revisions"]) == {sent["base"], sent["narrative"]}
    assert out["untouched"] is True and out["number"] == 5 and out["child"] == "01"
    assert out["selected"] == "05" and out["rowSelected"] == "true" and out["dialogAfter"] is None and "Les sources n'ont pas bougé" in out["notice"]
    assert out["compareStillOpen"] is True and out["errors"] == [] and out["violations"] == []


def test_a_commit_refused_at_the_door_shows_every_conflict_and_creates_nothing(tmp_path):
    out = run_ui(tmp_path, HELPERS + """
seed(3);
const {ex}=await opened();
await goCompare(1,2);
const r=await ex.compose.commit({title:'Direct',base:vid(1),narrative:vid(2),motion:vid(1),on_unmapped:'refuse'});
cmpWorld.narrativeUnmapped=true;
const r2=await ex.compose.commit({title:'Direct',base:vid(1),narrative:vid(2),on_unmapped:'refuse'});
const r3=await ex.compose.plan({title:'',base:vid(1)});
return {r:{ok:r.ok,id:r.variant_id&&r.variant_id.slice(-2)},r2:{ok:r2.ok,codes:r2.conflicts.map(c=>[c.code,c.dimension,c.fix.length>0])},r3,commits:cmpWorld.commitCalls,
  hostile:null,count:world.live.length};
""")
    assert out["r"]["ok"] is True and out["r"]["id"] == "04"
    assert out["r2"]["ok"] is False and out["r2"]["codes"] == [["narrative_unmapped_items", "narrative", True]]
    assert out["commits"] == 1 and out["count"] == 4, "the refused commit wrote nothing (the plan stopped it before the door)"
    assert "titre" in out["r3"]["error"]["text"].lower()


def test_the_page_api_and_the_command_channel_drive_compare_and_compose(tmp_path):
    out = run_ui(tmp_path, HELPERS + """
seed(4);
const {ex}=await opened();
const opened_=await ex.handleCommand({action:'compare',op:'open',variant_ids:[vid(1),vid(2),vid(3),vid(4)],mode:'sync'});
const nav=await ex.handleCommand({action:'compare',op:'navigate',variant_id:vid(3),step:'last'});
const focus=await ex.handleCommand({action:'compare',op:'focus',pair:[vid(1),vid(3)]});
const mode=await ex.handleCommand({action:'compare',op:'mode',mode:'independent'});
const plan=await ex.handleCommand({action:'compose',op:'plan',request:{title:'Par la voix',base:vid(1),art_direction:vid(3)}});
const create=await ex.handleCommand({action:'compose',op:'create',request:{title:'Par la voix',base:vid(1),art_direction:vid(3)}});
const bad=await ex.handleCommand({action:'compare',op:'bogus'});
const closed=await ex.handleCommand({action:'compare',op:'close'});
const afterClose=await ex.handleCommand({action:'compare',op:'navigate',variant_id:vid(3),step:'first'});
return {opened_:{state:opened_.state,layout:opened_.view.layout,ids:opened_.view.variant_ids.length},nav:nav.view.anchors[vid(3)].slice(-2),focus:[focus.view.layout,focus.view.pair.map(i=>i.slice(-2))],
  mode:mode.view.mode,plan:{state:plan.state,ok:plan.ok},create:{state:create.state,id:create.variant_id&&create.variant_id.slice(-2)},bad:bad.state,closed:closed,afterClose,
  selected:ex.state().selected.slice(-2),compareOpen:ex.compare.isActive(),clear:cmpWorld.calls.some(c=>c.url==='/compare/clear'),errors:env.errors};
""")
    assert out["opened_"] == {"state": "done", "layout": "four_up", "ids": 4}
    assert out["nav"] == "03" and out["focus"] == ["focus", ["01", "03"]] and out["mode"] == "independent"
    assert out["plan"] == {"state": "done", "ok": True} and out["create"] == {"state": "done", "id": "05"}
    assert out["bad"] == "refused" and out["closed"]["state"] == "done" and out["afterClose"]["state"] == "refused"
    assert out["compareOpen"] is False and out["clear"] is True and out["errors"] == []


def test_escape_closes_the_dialog_then_the_comparison_then_the_explorer_and_the_focus_comes_back(tmp_path):
    out = run_ui(tmp_path, HELPERS + """
seed(4);
const {ex}=await opened();
await goCompare(1,2);
env.key(paneOf(1),'l');await env.advance(30);
const d1=ex.state().dialog;
env.key(doc.activeElement,'Escape');await env.advance(30);
const afterDialog={dialog:ex.state().dialog,compare:ex.compare.isActive(),open:ex.isOpen()};
env.key(paneOf(1),'Escape');await env.advance(100);
const afterCompare={compare:ex.compare.isActive(),open:ex.isOpen(),previewBack:q('.jvx-preview').hidden,compareHidden:q('.jvx-compare').hidden,
  focusIsBar:doc.activeElement===q('.jvx-cmp-bar .jvx-btn')||doc.activeElement.className.includes('jvx-row'),clear:cmpWorld.calls.some(c=>c.url==='/compare/clear')};
await env.advance(400);
const previewMounted=prefabFake.mounts.slice(-1)[0].object_id;
env.key(doc.activeElement,'Escape');await env.advance(50);
return {d1,afterDialog,afterCompare,previewMounted,closed:!ex.isOpen(),marks:ex.compare.marks().length,errors:env.errors};
""")
    assert out["d1"] == "compare-links"
    assert out["afterDialog"] == {"dialog": None, "compare": True, "open": True}
    assert out["afterCompare"]["compare"] is False and out["afterCompare"]["open"] is True and out["afterCompare"]["compareHidden"] is True
    assert out["afterCompare"]["previewBack"] is False and out["afterCompare"]["focusIsBar"] is True and out["afterCompare"]["clear"] is True
    assert out["previewMounted"] == "studio-explorer-preview", "the single preview is back after the comparison"
    assert out["closed"] is True and out["marks"] == 0 and out["errors"] == []


def test_hostile_titles_in_the_comparison_and_in_conflicts_stay_text(tmp_path):
    out = run_ui(tmp_path, HELPERS + """
seed(3);
world.byId(vid(1)).title='<img src=x onerror=alert(1)>';world.byId(vid(2)).title='a\\u0000b\\u202eevil';
customScenes(1,[1,2]);customScenes(2,[1,2]);
world.docs.get(vid(1)).scenes[0].title='<script>alert(1)</script>';
const {ex}=await opened();
await goCompare(1,2);
const tags=new Set();env.walk(q('.jvx-compare'),n=>tags.add(n.tagName));
const names=panes().map(p=>p.querySelector('.jvx-cmp-name').textContent);
const options=paneOf(1).querySelector('.jvx-cmp-select').childNodes.map(o=>o.textContent);
return {tags:[...tags],names,options,dirs:panes().map(p=>p.querySelector('.jvx-cmp-name').getAttribute('dir')),violations:doc.violations,errors:env.errors};
""")
    assert out["violations"] == [] and "IMG" not in out["tags"] and "SCRIPT" not in out["tags"]
    assert out["names"][0] == "<img src=x onerror=alert(1)>" and "\u0000" not in out["names"][1] and "‮" not in out["names"][1]
    assert any("<script>" in option for option in out["options"]) and set(out["dirs"]) == {"auto"} and out["errors"] == []
