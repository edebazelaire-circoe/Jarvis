"""Avis de version plus recente et essai dans l'explorateur, sur un faux DOM par node (Remotion Slice 19, interface).

Le module teste est le VRAI `control_center_presentation_studio_explorer_upgrades.js` (via le vrai controleur de l'explorateur) ; le Core
minuscule de `tests/fakes/explorer_world.cjs` repond aux deux routes. La preuve dans un vrai Chrome, contre un vrai Core, est
`test_presentation_studio_explorer_upgrades_browser.py`.

Epingle : rien n'est mis a jour tout seul (aucune ecriture sans clic), la zone n'existe pas sans version plus recente, un bouton inactif dit
pourquoi, l'essai est UNE requete sans acteur ni `activate`, la variante source ne bouge pas, le chargement est compte et l'echec est dit.
"""

from __future__ import annotations

from tests.fakes.explorer_js import run_ui

NOTICE = """{scene_id:'pss_000000000001',prefab_id:'lab.dial',pinned_version:1,latest_version:3,newer_count:2,newer_versions:[3,2],reloading:false,
  fits:true,problem:null,engine_ok:true,latest_catalog:{type:'component',compatibility:{slidecar:'native',remotion:'unsupported'},license:null,upstream:null}}"""


def test_a_variant_with_nothing_newer_shows_no_zone_and_nothing_is_written(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
const {ex}=await opened();
const section=q('.jvx-upg');
return {hidden:section.hidden,gets:world.calls.filter(c=>c.url.endsWith('/upgrades')).length,writes:world.calls.filter(c=>c.method!=='GET').length,
  state:ex.upgrades.state()};
""")
    assert out["hidden"] is True and out["gets"] >= 1 and out["writes"] == 0 and out["state"]["count"] == 0


def test_a_newer_version_is_told_and_the_only_gesture_is_a_click_that_creates_a_child(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
world.upgrades={[vid(1)]:[""" + NOTICE + """]};
const {ex}=await opened();
const section=q('.jvx-upg');
const row=q('.jvx-upg-row');
const told={hidden:section.hidden,count:q('.jvx-upg .jvx-chip').textContent,scene:q('.jvx-upg-scene').textContent,ver:q('.jvx-upg-ver').textContent,
  chips:qa('.jvx-upg-chips .jvx-chip').map(c=>c.textContent),btn:q('.jvx-upg-act .jvx-btn').textContent,note:q('.jvx-upg-note').textContent};
const writesBefore=world.calls.filter(c=>c.method!=='GET').length;
await env.advance(40000);   /* time passes, polls run: still nothing is written without a click */
const idle=world.calls.filter(c=>c.method!=='GET').length;
q('.jvx-upg-act .jvx-btn').click();
await env.advance(300);await env.advance(300);
const tries=world.tries||[];
const created=world.live.find(n=>n.variant_id===(tries[0]&&tries[0].node));
return {told,writesBefore,idle,tries:tries.map(t=>({source:t.source.slice(-2),body:t.body})),created:created&&{title:created.title,parent:created.parent_variant_id.slice(-2)},
  activeStill:world.active.slice(-2),selected:ex.state().selected.slice(-2),notice:noticeText(),putCalls:world.calls.filter(c=>c.method==='PUT').length,
  revision:world.byId(vid(1)).revision,errors:env.errors};
""")
    assert out["told"]["hidden"] is False and out["told"]["count"] == "1 scène" and out["told"]["scene"] == "Scène 1 de 1"
    assert out["told"]["ver"] == "lab.dial · v1 → v3 (2 versions plus récentes)" and out["told"]["chips"] == ["Compatible"]
    assert out["told"]["btn"] == "Essayer dans une nouvelle variante" and "Rien n'est mis à jour tout seul" in out["told"]["note"]
    assert out["writesBefore"] == 0 and out["idle"] == 0, "no automatic upgrade: nothing is written until the user clicks"
    assert out["tries"] == [{"source": "01", "body": {"scene_id": "pss_000000000001", "version": 3, "expected_variant_revision": 1}}], \
        "one request, no actor, no activate"
    assert out["created"] and out["created"]["parent"] == "01" and out["created"]["title"] == "Essai v3"
    assert out["activeStill"] == "01", "the trial is not activated"
    assert out["selected"] != "01", "the new trial variant is selected so it can be compared, not activated"
    assert "la variante #1 n'a pas changé" in out["notice"] and out["putCalls"] == 0 and out["revision"] == 1
    assert out["errors"] == []


def test_a_version_that_does_not_fit_disables_the_button_and_says_why(tmp_path):
    out = run_ui(tmp_path, """
seed(2);
world.upgrades={[vid(1)]:[Object.assign(""" + NOTICE + """,{fits:false,problem:'presentation_studio_scene_incompatible'})]};
await opened();
const b=q('.jvx-upg-act .jvx-btn');
const chips=qa('.jvx-upg-chips .jvx-chip').map(c=>c.textContent);
b.click();await env.advance(100);
return {aria:b.getAttribute('aria-disabled'),title:b.title,chips,notice:noticeText(),posts:world.calls.filter(c=>c.method==='POST').length,
  text:q('.jvx-upg-row').textContent};
""")
    assert out["aria"] == "true" and out["chips"] == ["Incompatible"] and out["posts"] == 0
    assert "ne tiennent pas dans cette version" in out["title"] and "Rien n'est adapté à votre place" in out["title"]
    assert out["title"].replace("Essai impossible : ", "") in out["notice"] or "ne tiennent pas" in out["notice"]


def test_an_engine_that_cannot_use_the_version_and_an_unconfirmed_reload_are_told(tmp_path):
    out = run_ui(tmp_path, """
seed(2);
world.upgrades={[vid(1)]:[Object.assign(""" + NOTICE + """,{engine_ok:false,fits:true,problem:'presentation_studio_engine_unsupported'}),
  Object.assign(""" + NOTICE + """,{scene_id:'pss_000000000002',reloading:true})]};
await opened();
return {rows:qa('.jvx-upg-row').map(r=>({chips:[...r.querySelectorAll('.jvx-upg-chips .jvx-chip')].map(c=>c.textContent),
  aria:r.querySelector('.jvx-btn').getAttribute('aria-disabled'),why:r.querySelectorAll('.jvx-upg-ver')[1].textContent})),posts:world.calls.filter(c=>c.method==='POST').length};
""")
    assert out["rows"][0]["chips"] == ["Moteur : non utilisable"] and "déclarée, non utilisable" in out["rows"][0]["why"]
    assert out["rows"][1]["chips"] == ["Rechargement en cours"] and "rechargement à chaud" in out["rows"][1]["why"]
    assert [r["aria"] for r in out["rows"]] == ["true", "true"] and out["posts"] == 0


def test_the_search_is_counted_on_screen_and_a_failure_is_said_with_a_way_out(tmp_path):
    out = run_ui(tmp_path, """
seed(2);
world.upgrades={[vid(1)]:[""" + NOTICE + """]};
world.delays.push({match:u=>u.endsWith('/upgrades'),ms:4000});
const ex=make();
await ex.open({presentation_id:PID});
await env.advance(2500);
const loading=q('.jvx-upg-status').textContent;
await env.advance(3000);
const ready=q('.jvx-upg-row')!==undefined&&q('.jvx-upg-row')!==null;
world.failNext.push({match:u=>u.endsWith('/upgrades'),status:503,body:{error:{code:'presentation_studio_storage_io',message:'disque'}}});
q('.jvx-upg .jvx-btn').click();            /* « Relire » */
await env.advance(300);
return {loading,ready,failed:q('.jvx-upg-status').textContent,tone:q('.jvx-upg-status').getAttribute('data-tone'),retry:q('.jvx-upg .jvx-btn').hidden,
  logs:env.logs.filter(l=>l[0]==='warn').map(l=>l[1])};
""")
    assert out["loading"].startswith("Recherche des versions plus récentes…") and "2 s" in out["loading"] or "3 s" in out["loading"]
    assert out["ready"] is True
    assert out["failed"].startswith("Les versions plus récentes n'ont pas pu être lues") and "rien n'a été modifié" in out["failed"]
    assert out["tone"] == "warn" and out["retry"] is False, "the way out stays visible"
    assert any("upgrades_failed" in line for line in out["logs"]), "the failure is logged, not only drawn"


def test_a_refused_trial_is_said_in_words_and_leaves_the_graph_untouched(tmp_path):
    out = run_ui(tmp_path, """
seed(2);
world.upgrades={[vid(1)]:[""" + NOTICE + """]};
await opened();
world.upgrades[vid(1)][0].fits=false;     /* Core now refuses: the notice on screen is older than the truth */
const before=world.live.length;
q('.jvx-upg-act .jvx-btn').click();
await env.advance(400);
return {notice:noticeText(),live:world.live.length-before,busy:ex_busy(),kind:q('.jvx-notice').getAttribute('data-kind')};
function ex_busy(){return q('.jvx-busy')&&!q('.jvx-busy').hidden}
""")
    assert "ne tiennent pas dans cette version" in out["notice"] and out["live"] == 0 and out["kind"] == "refused"
