"""Variants re-reads Core after a change made in the editor (presentation-edition-v1 Slice 09, QA M3), on the node bench of the explorer.

The browser test proves the frame shows the new title; this file pins the two branches of `onVariantEdited` without a 10 s poll in the
way: a committed change (`jarvis:studio-variant-edited`) makes Variants read the graph and the variant AT ONCE, and a re-read that fails
is said (« Modification enregistrée, mais l'aperçu n'a pas pu être relu ») with « Relire », which reads again.
"""

from __future__ import annotations

from tests.fakes.explorer_js import run_ui


def test_a_committed_edit_rereads_the_graph_at_once_and_a_failed_reread_is_said_with_relire(tmp_path):
    out = run_ui(tmp_path, """
seed(3);
const {ex}=await opened();
const graphs=()=>world.calls.filter(c=>c.method==='GET'&&/\\/graph(\\?|$)/.test(c.url)).length;
const edited=(over)=>win.dispatchEvent(Object.assign({type:'jarvis:studio-variant-edited',
  detail:{presentation_id:PID,variant_id:vid(1),revision:9,scene_id:null}},over||{}));
const before=graphs();
edited();await env.advance(50);
const after=graphs();
world.failNext.push({match:u=>/\\/graph(\\?|$)/.test(u),status:503,body:{error:{code:'core_unreachable',message:'Core is unreachable'}}});
edited();await env.advance(50);
const failed={notice:noticeText(),kind:q('.jvx-notice').getAttribute('data-kind'),
  relire:qa('.jvx-notice button').map(b=>b.textContent)};
const relire=qa('.jvx-notice button').find(b=>b.textContent==='Relire');
const beforeRetry=graphs();
if(relire)relire.click();
await env.advance(400);
return {before,after,failed,retried:graphs()-beforeRetry,errors:env.errors.filter(e=>String(e).includes('edit_reread_failed'))};
""")
    assert out["after"] == out["before"] + 1, "the graph is read again at once, not at the next 10 s poll"
    assert "Modification enregistrée, mais l’aperçu n’a pas pu être relu" in out["failed"]["notice"], out["failed"]
    assert "Relire" in out["failed"]["relire"]
    assert out["retried"] >= 1, "« Relire » reads Core again"
