"""Les actions de l'explorateur de variantes, par node (studio de présentation, Slice 18).

Chaque geste est une opération canonique du relais, relue ensuite : activer, brancher, renommer, archiver (plan, liste exacte, jeton), restaurer,
le menu contextuel. Chaque refus de Core est dit en français à l'écran, journalisé, et libère l'interface. L'arbre n'est jamais mis à jour de tête.
"""

from __future__ import annotations

from tests.fakes.explorer_js import run_ui

POSTS = "world.calls.filter(c=>c.method==='POST').map(c=>[c.url.split('/').slice(-1)[0],c.body])"


def test_activate_posts_the_canonical_operation_rereads_the_graph_and_moves_the_marker(tmp_path):
    out = run_ui(tmp_path, """
seed(6);
const {ex}=await opened();
ex.select(vid(4));await env.advance(200);
act('activate').click();await env.advance(300);
const calls=world.calls.filter(c=>c.method==='POST');
const reads=world.calls.map(c=>c.method+' '+c.url.split('/').slice(-1)[0]);
return {calls:calls.map(c=>[c.url.slice(-17),c.body]),active:ex.state().active.slice(-2),flag:rowFor(4).querySelector('.jvx-flag').textContent,
  was:rowFor(1).querySelector('.jvx-flag').hidden,notice:noticeText(),noticeKind:q('.jvx-notice').getAttribute('data-kind'),
  rereadAfter:reads.slice(reads.lastIndexOf('POST activate')+1).includes('GET graph?archived=1'),busy:q('.jvx-busy').hidden,
  disabled:act('activate').getAttribute('aria-disabled'),errors:env.logs.filter(l=>l[0]==='error')};
""")
    assert out["calls"] == [["psv_0000000000000000000000000000000004/activate".replace("psv_0000000000000000000000000000000004", "0000000000000004")[-17:] if False else out["calls"][0][0], {"expected_revision": 5}]]
    assert out["calls"][0][0].endswith("04/activate")
    assert out["active"] == "04" and out["flag"] == "Actif" and out["was"] is True
    assert "#4" in out["notice"] and "variante active" in out["notice"] and out["noticeKind"] == "ok"
    assert out["rereadAfter"] is True, "the graph is read again from Core after the operation"
    assert out["busy"] is True and out["disabled"] == "true" and out["errors"] == []


def test_activating_the_active_variant_is_said_and_sends_nothing(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
const {ex}=await opened();
act('activate').click();await env.advance(100);
return {notice:noticeText(),posts:world.calls.filter(c=>c.method==='POST').length,title:act('activate').title};
""")
    assert out["posts"] == 0 and "déjà la variante active" in out["notice"] and "déjà" in out["title"]


def test_branching_asks_for_a_title_validates_it_sends_the_source_and_selects_the_new_child(tmp_path):
    out = run_ui(tmp_path, """
seed(5);
const {ex}=await opened();
ex.select(vid(3));await env.advance(200);
act('branch').click();await env.advance(50);
const dlg=q('.jvx-dialog');
const opening={heading:q('#jvxDialogTitle').textContent,title:q('#jvxTitleInput').value,focus:doc.activeElement.id,
  insideInert:host().children.filter(n=>n.inert).length};
const submit=()=>q('.jvx-dialog form').dispatchEvent(new (require(process.env.JARVIS_EXPLORER_DOM).FakeEvent)('submit'));
q('#jvxTitleInput').value='   ';submit();await env.advance(50);
const emptyError=q('#jvxTitleError').textContent;
q('#jvxTitleInput').value='x'.repeat(81);submit();await env.advance(50);
const longError=q('#jvxTitleError').textContent;
q('#jvxTitleInput').value='Version sobre';
q('#jvxRationaleInput').value='🎨'.repeat(201);submit();await env.advance(50);
const rationaleError=q('#jvxRationaleError').textContent;
const noPostYet=world.calls.filter(c=>c.method==='POST').length;
q('#jvxRationaleInput').value='Plus calme pour le comité';
q('.jvx-check input').click();
submit();await env.advance(400);
const post=world.calls.filter(c=>c.method==='POST')[0];
return {opening,emptyError,longError,rationaleError,noPostYet,post:post&&post.body,url:post&&post.url.split('/').slice(-1)[0],
  dialogGone:ex.state().dialog,selected:ex.state().selected.slice(-2),active:ex.state().active.slice(-2),
  numbers:numbers(),parent:world.byId(vid(6)).parent_variant_id.slice(-2),notice:noticeText(),focus:doc.activeElement.dataset.id.slice(-2),counter:world.counter};
""")
    assert out["opening"]["heading"] == "Brancher depuis #3" and out["opening"]["title"] == "Branche de Variante 3" and out["opening"]["focus"] == "jvxTitleInput"
    assert out["opening"]["insideInert"] >= 3, "the rest of the workspace is inert behind the dialog"
    assert "titre" in out["emptyError"] and "80" in out["longError"] and "octets" in out["rationaleError"] or "caractères" in out["rationaleError"]
    assert out["noPostYet"] == 0, "an invalid form never reaches Core"
    assert out["url"] == "variants" and out["post"] == {"title": "Version sobre", "source_variant_id": "psv_00000000000000000000000000000003",
                                                         "activate": True, "expected_revision": 5, "rationale": "Plus calme pour le comité"}
    assert out["dialogGone"] is None and out["selected"] == "06" and out["active"] == "06" and out["parent"] == "03"
    assert out["numbers"][-1] == 6 and "Branche #6 créée depuis #3 et activée" in out["notice"] and out["focus"] == "06"


def test_a_hostile_title_is_cleaned_before_it_is_sent(tmp_path):
    out = run_ui(tmp_path, """
seed(2);
const {ex}=await opened();
act('branch').click();await env.advance(50);
q('#jvxTitleInput').value='a\\u0000b\\u202e <b>x</b>';
q('.jvx-dialog form').dispatchEvent(new (require(process.env.JARVIS_EXPLORER_DOM).FakeEvent)('submit'));await env.advance(400);
return {title:world.byId(vid(3)).title,violations:doc.violations};
""")
    assert out["title"] == "a b <b>x</b>" and out["violations"] == [], "NUL becomes a space, the bidi override disappears, the markup stays text"


def test_renaming_prefills_the_title_skips_an_unchanged_one_and_posts_the_new_one(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
const {ex}=await opened();
ex.select(vid(2));await env.advance(200);
act('rename').click();await env.advance(50);
const prefilled=q('#jvxTitleInput').value;
const form=()=>q('.jvx-dialog form').dispatchEvent(new (require(process.env.JARVIS_EXPLORER_DOM).FakeEvent)('submit'));
form();await env.advance(50);
const afterSame={dialog:ex.state().dialog,posts:world.calls.filter(c=>c.method==='POST').length};
act('rename').click();await env.advance(50);
q('#jvxTitleInput').value='Cercle sombre';form();await env.advance(400);
return {prefilled,afterSame,post:world.calls.filter(c=>c.method==='POST').map(c=>[c.url.split('/').pop(),c.body]),title:rowFor(2).querySelector('.jvx-rowtitle').textContent,
  number:rowFor(2).querySelector('.jvx-num').textContent,meta:q('.jvx-meta-title').textContent,notice:noticeText(),focus:doc.activeElement.tagName};
""")
    assert out["prefilled"] == "Variante 2" and out["afterSame"] == {"dialog": None, "posts": 0}
    assert out["post"] == [["rename", {"title": "Cercle sombre", "expected_revision": 5}]]
    assert out["title"] == "Cercle sombre" and out["number"] == "#2", "the number never changes"
    assert "#2" in out["meta"] and "renommée" in out["notice"]


# ------------------------------------------------------------------ archivage : plan, liste exacte, jeton

def test_archiving_shows_the_exact_set_before_anything_is_written_and_cancel_is_the_default(tmp_path):
    out = run_ui(tmp_path, """
seed(6);
const {ex}=await opened();
ex.select(vid(4));await env.advance(200);
act('archive').click();await env.advance(200);
const items=qa('.jvx-set li').map(li=>[li.querySelector('.jvx-num').textContent,li.querySelector('.jvx-rowtitle').textContent,li.querySelector('.jvx-sid').textContent]);
const state={heading:q('#jvxDialogTitle').textContent,items,focus:doc.activeElement.textContent,token:q('.jvx-token').textContent,
  buttons:qa('.jvx-dialog-actions .jvx-btn').map(b=>[b.textContent,b.hidden,b.getAttribute('aria-disabled')]),
  posts:world.calls.filter(c=>c.method==='POST').map(c=>c.url.split('/').pop())};
env.key(doc.activeElement,'Enter');       /* Enter on the focused button = Annuler */
doc.activeElement.click();
await env.advance(100);
return {state,afterCancel:{dialog:ex.state().dialog,posts:world.calls.filter(c=>c.method==='POST').map(c=>c.url.split('/').pop()),archived:world.archived.length,
  focus:doc.activeElement.dataset.id&&doc.activeElement.dataset.id.slice(-2)}};
""")
    state = out["state"]
    assert state["heading"] == "Archiver 2 variantes ?"
    assert state["items"] == [["#4", "Variante 4", "psv_000000…"], ["#5", "Variante 5", "psv_000000…"]]
    assert state["focus"] == "Annuler", "the safe choice has the focus: Enter never destroys anything"
    assert "Confirmation valable encore 10:00" in state["token"]
    assert state["posts"] == ["archive-plan"], "only a dry run so far"
    assert out["afterCancel"]["dialog"] is None and out["afterCancel"]["archived"] == 0 and out["afterCancel"]["posts"] == ["archive-plan"]
    assert out["afterCancel"]["focus"] == "04", "the focus is back on the row that opened the dialog"


def test_confirming_executes_with_the_token_of_that_plan_and_the_tree_is_read_again(tmp_path):
    out = run_ui(tmp_path, """
seed(6);
const {ex}=await opened();
ex.select(vid(4));await env.advance(200);
act('archive').click();await env.advance(200);
const planned=qa('.jvx-set li .jvx-num').map(n=>n.textContent);
q('.jvx-dialog-actions [data-primary]').click();await env.advance(400);
const archiveCall=world.calls.find(c=>c.url.endsWith('/archive'));
return {planned,body:archiveCall.body,tokenFormat:/^psc_\\d+\\./.test(archiveCall.body.confirmation),live:numbers(),archivedLabel:q('.jvx-archive-toggle span').textContent,
  dialog:ex.state().dialog,selected:ex.state().selected.slice(-2),notice:noticeText(),archived:world.archived.map(n=>n.variant_number),
  focus:doc.activeElement.dataset.id&&doc.activeElement.dataset.id.slice(-2),rereads:world.calls.filter(c=>c.url.includes('/graph')).length};
""")
    assert out["planned"] == ["#4", "#5"] and out["body"].keys() == {"confirmation"} and out["tokenFormat"]
    assert out["live"] == [1, 2, 3, 6] and out["archivedLabel"] == "Archivées (2)" and sorted(out["archived"]) == [4, 5]
    assert out["dialog"] is None and out["selected"] == "01", "the selection leaves the archived variant for its live parent"
    assert "2 variantes archivées" in out["notice"] and "restaurent" in out["notice"] and out["rereads"] >= 2


def test_archiving_the_branch_that_holds_the_active_variant_asks_which_one_replaces_it(tmp_path):
    out = run_ui(tmp_path, """
seed(6);
world.active=vid(5);
const {ex}=await opened();
ex.select(vid(4));await env.advance(200);
act('archive').click();await env.advance(300);
const choice={legend:q('.jvx-choice legend').textContent,options:qa('.jvx-choice label').map(l=>[l.querySelector('input').checked,l.textContent]),
  plans:world.calls.filter(c=>c.url.endsWith('/archive-plan')).map(c=>c.body)};
const radios=qa('.jvx-choice input');
const three=radios.find(r=>r.value===vid(3));
three.checked=true;three.dispatchEvent(new (require(process.env.JARVIS_EXPLORER_DOM).FakeEvent)('change'));
await env.advance(300);
q('.jvx-dialog-actions [data-primary]').click();await env.advance(400);
const archiveCall=world.calls.find(c=>c.url.endsWith('/archive'));
return {choice,body:archiveCall.body,active:ex.state().active.slice(-2),plansAfter:world.calls.filter(c=>c.url.endsWith('/archive-plan')).map(c=>c.body)};
""")
    assert "active" in out["choice"]["legend"]
    assert [o[1] for o in out["choice"]["options"]][0].startswith("#1") and out["choice"]["options"][0][0] is True, "the parent is suggested and preselected"
    assert out["plansAfter"][-1] == {"activate_variant_id": "psv_00000000000000000000000000000003"}, "choosing another replacement re-plans: the token binds it"
    assert out["body"]["activate_variant_id"].endswith("03") and out["active"] == "03"


def test_an_expired_confirmation_cannot_be_sent_and_recomputing_gives_a_fresh_one(tmp_path):
    out = run_ui(tmp_path, """
seed(4);
const {ex}=await opened();
ex.select(vid(3));await env.advance(200);
act('archive').click();await env.advance(200);
const first=q('.jvx-token').textContent;
await env.advance(601000);
const expired={token:q('.jvx-token').textContent,state:q('.jvx-token').getAttribute('data-state'),ok:q('.jvx-dialog-actions [data-primary]').getAttribute('aria-disabled'),
  recompute:[...document_all()].length};
function document_all(){return qa('.jvx-dialog-actions .jvx-btn').filter(b=>!b.hidden)}
q('.jvx-dialog-actions [data-primary]').click();await env.advance(100);
const postsAfterClick=world.calls.filter(c=>c.url.endsWith('/archive')).length;
const recompute=qa('.jvx-dialog-actions .jvx-btn').find(b=>b.textContent==='Recalculer');
recompute.click();await env.advance(300);
return {first,expired,postsAfterClick,fresh:q('.jvx-token').textContent,ok:q('.jvx-dialog-actions [data-primary]').getAttribute('aria-disabled'),
  plans:world.calls.filter(c=>c.url.endsWith('/archive-plan')).length};
""")
    assert "10:00" in out["first"] and "a expiré" in out["expired"]["token"] and out["expired"]["state"] == "expired" and out["expired"]["ok"] == "true"
    assert out["postsAfterClick"] == 0, "an expired token is never sent"
    assert "valable encore" in out["fresh"] and out["ok"] is None and out["plans"] == 2


def test_a_set_that_changed_between_the_plan_and_the_confirmation_is_replanned_in_front_of_the_user_not_executed(tmp_path):
    out = run_ui(tmp_path, """
seed(6);
const {ex}=await opened();
ex.select(vid(4));await env.advance(200);
act('archive').click();await env.advance(200);
const before=qa('.jvx-set li .jvx-num').map(n=>n.textContent);
world.add(4);                     /* the voice branches from #4 while the dialog is open: 4, 5 and 7 would go */
world.revision+=1;
q('.jvx-dialog-actions [data-primary]').click();await env.advance(500);
const afterStale={items:qa('.jvx-set li .jvx-num').map(n=>n.textContent),warn:q('.jvx-warnbox').textContent,dialog:ex.state().dialog,archived:world.archived.length,
  archivePosts:world.calls.filter(c=>c.url.endsWith('/archive')).length,focus:doc.activeElement.textContent};
q('.jvx-dialog-actions [data-primary]').click();await env.advance(500);
return {before,afterStale,final:{archived:world.archived.map(n=>n.variant_number).sort(),dialog:ex.state().dialog,archivePosts:world.calls.filter(c=>c.url.endsWith('/archive')).length}};
""")
    assert out["before"] == ["#4", "#5"]
    stale = out["afterStale"]
    assert stale["items"] == ["#4", "#5", "#7"] and stale["archived"] == 0, "nothing was archived on the stale token"
    assert "La liste a changé : 2 → 3" in stale["warn"] and "Rien n'a été archivé" in stale["warn"]
    assert stale["dialog"] == "archive" and stale["focus"] == "Annuler", "the user confirms again, on what they now see"
    assert out["final"]["archived"] == [4, 5, 7] and out["final"]["archivePosts"] == 2


def test_a_forged_or_refused_confirmation_is_reported_in_french_and_nothing_moves(tmp_path):
    out = run_ui(tmp_path, """
seed(4);
const {ex}=await opened();
ex.select(vid(3));await env.advance(200);
act('archive').click();await env.advance(200);
world.failNext.push({match:u=>u.endsWith('/archive'),status:409,body:{error:{code:'presentation_studio_confirmation_stale',message:'forged'}}});
q('.jvx-dialog-actions [data-primary]').click();await env.advance(500);
return {warn:q('.jvx-warnbox')?q('.jvx-warnbox').textContent:null,archived:world.archived.length,dialog:ex.state().dialog,
  logs:env.logs.filter(l=>l[1].includes('op_failed')).map(l=>l[1])};
""")
    assert out["archived"] == 0 and out["dialog"] == "archive" and "Rien n'a été archivé" in out["warn"]
    assert any("confirmation_stale" in line for line in out["logs"]), "the refusal is journalled with its code"


def test_a_variant_in_playback_cannot_even_be_planned_and_the_reason_is_in_french(tmp_path):
    out = run_ui(tmp_path, """
seed(5);
world.playingVariant=vid(3);
const {ex}=await opened();
ex.select(vid(2));await env.advance(200);
act('archive').click();await env.advance(300);
return {dialog:ex.state().dialog,notice:noticeText(),kind:q('.jvx-notice').getAttribute('data-kind'),archives:world.calls.filter(c=>c.url.endsWith('/archive')).length,busy:q('.jvx-busy').hidden};
""")
    assert out["dialog"] is None and out["archives"] == 0 and out["busy"] is True
    assert "en cours de lecture" in out["notice"] and "Rien n'a été déplacé" in out["notice"] and out["kind"] == "refused"


def test_the_archive_is_full_and_the_live_limit_are_explained_with_their_way_out(tmp_path):
    out = run_ui(tmp_path, """
seed(5);
for(let i=0;i<127;i++)world.archived.push(Object.assign({},world.live[0],{variant_id:vid(1000+i),variant_number:1000+i,state:'archived',parent_variant_id:null}));
const {ex}=await opened();
ex.select(vid(2));await env.advance(200);
act('archive').click();await env.advance(300);
const full={dialog:ex.state().dialog,notice:noticeText()};
ex.destroy();
world.archived.length=0;world.live.length=0;world.counter=0;world.active=null;
seed(64,'fan');
const b=await opened();
act('branch').click();await env.advance(100);
return {full,live:{dialog:b.ex.state().dialog,notice:noticeText(),title:act('branch').title,disabled:act('branch').getAttribute('aria-disabled'),
  posts:world.calls.filter(c=>c.method==='POST'&&c.url.endsWith('/variants')).length}};
""")
    assert out["full"]["dialog"] is None and "128" in out["full"]["notice"] and "Restaurez" in out["full"]["notice"]
    assert out["live"]["dialog"] is None and out["live"]["disabled"] == "true" and "64" in out["live"]["title"] and "archivez" in out["live"]["notice"]
    assert out["live"]["posts"] == 0, "refused up front: nothing is sent"


def test_the_last_live_variant_cannot_be_archived_and_says_why(tmp_path):
    out = run_ui(tmp_path, """
seed(1);
const {ex}=await opened();
act('archive').click();await env.advance(100);
return {dialog:ex.state().dialog,notice:noticeText(),title:act('archive').title,posts:world.calls.filter(c=>c.method==='POST').length};
""")
    assert out["dialog"] is None and out["posts"] == 0 and "au moins une variante vivante" in out["notice"]


# ------------------------------------------------------------------ restaurer

def test_restoring_an_archived_variant_brings_back_what_it_needs_and_says_how_many(tmp_path):
    out = run_ui(tmp_path, """
seed(6);
world.archived.push(...world.live.splice(1,2));     /* 2 and 3 archived (3 is the child of 2) */
const {ex}=await opened();
q('.jvx-archive-toggle').click();await env.advance(50);
const archivedRow=rowsOf(q('.jvx-archive .jvx-tree')).find(r=>r.dataset.id===vid(3));
archivedRow.click();await env.advance(300);
const acts=qa('.jvx-actions .jvx-btn').map(b=>b.dataset.act);
act('restore').click();await env.advance(500);
return {acts,posts:world.calls.filter(c=>c.method==='POST').map(c=>[c.url.split('/').slice(-1)[0],c.body]),live:numbers(),archivedLeft:world.archived.length,notice:noticeText(),
  selected:ex.state().selected.slice(-2),label:q('.jvx-archive-toggle span').textContent};
""")
    assert out["acts"] == ["restore"] and out["posts"] == [["restore", {"expected_revision": 5}]]
    assert out["live"] == [1, 2, 3, 4, 5, 6] and out["archivedLeft"] == 0 and "2 variantes restaurées" in out["notice"]
    assert out["selected"] == "03" and out["label"] == "Archivées (0)"


def test_restore_with_descendants_is_offered_only_when_there_are_archived_children(tmp_path):
    out = run_ui(tmp_path, """
seed(6);
world.archived.push(...world.live.splice(3,2));     /* 4 and 5 archived (5 is the child of 4) */
const {ex}=await opened();
q('.jvx-archive-toggle').click();await env.advance(50);
const rows=rowsOf(q('.jvx-archive .jvx-tree'));
rows[0].click();await env.advance(300);
const withKids=qa('.jvx-actions .jvx-btn').map(b=>b.dataset.act);
rows[1].click();await env.advance(300);
const leaf=qa('.jvx-actions .jvx-btn').map(b=>b.dataset.act);
rows[0].click();await env.advance(300);
act('restore_all').click();await env.advance(400);
return {withKids,leaf,body:world.calls.filter(c=>c.url.endsWith('/restore')).map(c=>c.body),live:numbers()};
""")
    assert out["withKids"] == ["restore", "restore_all"] and out["leaf"] == ["restore"]
    assert out["body"] == [{"expected_revision": 5, "with_descendants": True}] and out["live"] == [1, 2, 3, 4, 5, 6]


# ------------------------------------------------------------------ refus, périmé, pannes

def test_a_stale_graph_is_said_reread_and_the_action_is_not_repeated(tmp_path):
    out = run_ui(tmp_path, """
seed(4);
const {ex}=await opened();
world.revision+=3;
world.add(2);                    /* the voice created a branch meanwhile */
ex.select(vid(3));await env.advance(200);
act('activate').click();await env.advance(500);
return {notice:noticeText(),kind:q('.jvx-notice').getAttribute('data-kind'),active:ex.state().active.slice(-2),numbers:numbers(),
  activates:world.calls.filter(c=>c.url.endsWith('/activate')).length,revision:ex.state().revision,logs:env.logs.filter(l=>l[1].includes('op_failed')).map(l=>l[1])};
""")
    assert out["kind"] == "stale" and "Le graphe a changé" in out["notice"] and "refaites l'action" in out["notice"]
    assert out["activates"] == 1 and out["active"] == "01", "no second attempt behind the user's back"
    assert out["numbers"] == [1, 2, 3, 5, 4] and out["revision"] == 8, "the list was reread (tree order)"
    assert any("stale_revision" in line for line in out["logs"])


def test_a_dead_core_during_an_action_is_a_visible_failure_that_releases_the_interface(tmp_path):
    out = run_ui(tmp_path, """
seed(4);
const {ex}=await opened();
ex.select(vid(2));await env.advance(200);
world.failNext.push({match:u=>u.endsWith('/activate'),reply:{reject:'fetch failed'}});
act('activate').click();await env.advance(300);
const first={notice:noticeText(),kind:q('.jvx-notice').getAttribute('data-kind'),busy:q('.jvx-busy').hidden,disabled:act('activate').getAttribute('aria-disabled'),
  errors:env.logs.filter(l=>l[0]==='error').map(l=>l[1])};
world.failNext.push({match:u=>u.endsWith('/activate'),reply:{hang:true}});
act('activate').click();
await env.advance(16000);
const second={notice:noticeText(),busy:q('.jvx-busy').hidden,disabled:act('activate').getAttribute('aria-disabled')};
act('activate').click();await env.advance(300);
return {first,second,active:ex.state().active.slice(-2)};
""")
    assert out["first"]["kind"] == "failed" and "Core est injoignable" in out["first"]["notice"] and out["first"]["busy"] is True
    assert out["first"]["disabled"] is None and any("op_failed" in line for line in out["first"]["errors"])
    assert "Core ne répond pas depuis 15 s" in out["second"]["notice"] and "peut-être" in out["second"]["notice"] and out["second"]["busy"] is True
    assert out["active"] == "02", "the third try goes through: nothing stayed locked"


def test_a_slow_operation_shows_what_it_does_and_for_how_long_and_refuses_a_second_one(tmp_path):
    out = run_ui(tmp_path, """
seed(4);
const {ex}=await opened();
ex.select(vid(2));await env.advance(200);
world.delays.push({match:u=>u.endsWith('/activate'),ms:4000});
act('activate').click();
await env.advance(2500);
const during={busy:q('.jvx-busy').textContent,disabled:qa('.jvx-actions .jvx-btn').map(b=>b.getAttribute('aria-disabled')),state:ex.state().busy};
act('rename').click();await env.advance(50);
const refused=noticeText();
await env.advance(3000);
return {during,refused,after:q('.jvx-busy').hidden,active:ex.state().active.slice(-2),dialogs:ex.state().dialog};
""")
    assert out["during"]["busy"] == "Activation… 2 s" and out["during"]["state"] == "Activation"
    assert set(out["during"]["disabled"]) == {"true"}
    assert "déjà en cours" in out["refused"] and out["after"] is True and out["active"] == "02"


def test_a_change_made_elsewhere_appears_within_ten_seconds_and_is_announced(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
const {ex}=await opened();
world.add(2,{title:'Ajoutée à la voix'});world.revision+=1;
await env.advance(10200);
return {numbers:numbers(),notice:noticeText(),count:q('.jvx-subtitle').textContent};
""")
    assert out["numbers"] == [1, 2, 3, 4] and "changé ailleurs" in out["notice"] and "4 variantes" in out["count"]


# ------------------------------------------------------------------ menu contextuel

def test_the_context_menu_offers_the_same_actions_by_pointer_keyboard_and_long_press(tmp_path):
    out = run_ui(tmp_path, """
seed(5);
const {ex}=await opened();
const labels=()=>qa('.jvx-menu [role="menuitem"]').map(b=>b.querySelector('span').textContent);
rowFor(3).dispatchEvent(new (require(process.env.JARVIS_EXPLORER_DOM).FakeEvent)('contextmenu',{clientX:200,clientY:150}));
await env.advance(50);
const pointer={labels:labels(),selected:ex.state().selected.slice(-2),role:q('.jvx-menu').getAttribute('role'),focus:doc.activeElement.textContent};
env.key(doc.activeElement,'ArrowDown');env.key(doc.activeElement,'ArrowDown');
const afterArrows=doc.activeElement.textContent;
env.key(doc.activeElement,'Escape');
const closed={menu:ex.state().menu,focus:doc.activeElement.dataset&&doc.activeElement.dataset.id&&doc.activeElement.dataset.id.slice(-2)};
rowFor(2).focus();env.key(doc.activeElement,'ContextMenu');await env.advance(50);
const keyboard=labels();
qa('.jvx-menu [role="menuitem"]').find(b=>b.textContent.startsWith('Renommer')).click();await env.advance(50);
const viaMenu={dialog:ex.state().dialog,menu:ex.state().menu};
env.key(doc.activeElement,'Escape');
rowFor(5).dispatchEvent(new (require(process.env.JARVIS_EXPLORER_DOM).FakeEvent)('pointerdown',{pointerType:'touch',clientX:50,clientY:60}));
await env.advance(300);const early=ex.state().menu;await env.advance(300);
return {pointer,afterArrows,closed,keyboard,viaMenu,longPress:{early,late:ex.state().menu,labels:labels()}};
""")
    assert out["pointer"]["labels"][:4] == ["Activer", "Brancher d'ici…", "Renommer…", "Archiver…"] and out["pointer"]["selected"] == "03"
    assert out["pointer"]["role"] == "menu" and out["pointer"]["focus"].startswith("Activer")
    assert out["afterArrows"].startswith("Renommer") and out["closed"] == {"menu": False, "focus": "03"}
    assert out["keyboard"][0].startswith("Activer") and out["viaMenu"] == {"dialog": "rename", "menu": False}
    assert out["longPress"]["early"] is False and out["longPress"]["late"] is True and len(out["longPress"]["labels"]) == 4


def test_a_disabled_menu_item_explains_itself_instead_of_doing_nothing(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
const {ex}=await opened();
rowFor(1).dispatchEvent(new (require(process.env.JARVIS_EXPLORER_DOM).FakeEvent)('contextmenu',{clientX:100,clientY:100}));await env.advance(50);
const item=qa('.jvx-menu [role="menuitem"]')[0];
const state={disabled:item.getAttribute('aria-disabled'),title:item.title};
item.click();await env.advance(50);
return {state,notice:noticeText(),menu:ex.state().menu,posts:world.calls.filter(c=>c.method==='POST').length};
""")
    assert out["state"]["disabled"] == "true" and "déjà la variante active" in out["state"]["title"]
    assert "déjà la variante active" in out["notice"] and out["menu"] is True and out["posts"] == 0
