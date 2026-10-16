"""Fonctions pures du rail des presentations (node, sans navigateur) : modele, visibilite, menu. La fenetre flottante d'une presentation et la
« concentration » qui l'ouvrait sont retirees (native-studio-playback-fix Slice 09) : le rail ouvre Variantes.

Le comportement dans une vraie page est prouve par `test_control_center_presentation_rail_browser.py` et `test_presentation_rail_e2e_browser.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

RUNTIME = Path(__file__).resolve().parents[2] / "jarvis" / "runtime"
P1, P2, P3, P4 = ("pst_" + str(n) * 32 for n in (1, 2, 3, 4))


def node(script: str):
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node absent")
    code = (f"const R=require({json.dumps(str(RUNTIME / 'control_center_presentation_rail.js'))});"
            f"process.stdout.write(JSON.stringify((()=>{{{script}}})()))")
    done = subprocess.run([exe, "-e", code], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


ROWS = f"""[
  {{presentation_id:'{P1}',title:'Lancement',hidden:false,archived:false,work:{{state:'working'}}}},
  {{presentation_id:'{P2}',title:'Bilan',hidden:true,archived:false,work:{{state:'done'}}}},
  {{presentation_id:'{P3}',title:'Ancienne',hidden:false,archived:true,work:{{state:'problem'}}}},
  {{presentation_id:'{P4}',title:'Roadmap',hidden:false,archived:false,work:{{state:'problem',message:'x'}}}},
  {{presentation_id:'pas un id',title:'Intrus'}}, null]"""


def test_the_model_groups_visible_hidden_archived_and_ignores_junk():
    out = node(f"const m=R.modelOf({ROWS});return {{v:m.visible.map(r=>r.title),h:m.hidden.map(r=>r.title),a:m.archived.map(r=>r.title),w:m.working.length,p:m.problems.map(r=>r.title),t:m.total}}")
    assert out == {"v": ["Lancement", "Roadmap"], "h": ["Bilan"], "a": ["Ancienne"], "w": 1, "p": ["Roadmap"], "t": 4}, "an archived problem is not an alarm"


@pytest.mark.parametrize("ctx,expected", [
    ({"pref": "hidden", "boardKind": "presentation"}, False),
    ({"pref": "shown"}, True),
    ({"pref": "auto"}, True),                       # something works in the rows
    ({"pref": "auto", "boardKind": "presentation"}, True),
])
def test_visibility_rules(ctx, expected):
    assert node(f"return R.shouldShow(R.modelOf({ROWS}),{json.dumps(ctx)})") is expected


def test_visibility_when_nothing_works_depends_on_the_board_the_mode_or_the_open_surfaces():
    calm = f"R.modelOf([{{presentation_id:'{P1}',title:'A',work:{{state:'done'}}}}])"
    results = node(f"const m={calm};return [R.shouldShow(m,{{pref:'auto'}}),R.shouldShow(m,{{pref:'auto',boardKind:'presentation'}}),"
                   "R.shouldShow(m,{pref:'auto',mode:'presentation'}),R.shouldShow(m,{pref:'auto',windowOpen:true}),R.shouldShow(m,{pref:'auto',studioOpen:true}),"
                   "R.shouldShow(R.modelOf([]),{pref:'auto',boardKind:'presentation'}),R.shouldShow(R.modelOf([]),{pref:'shown'})]")
    assert results == [False, True, True, False, True, False, True], "the retired window opens nothing; Variants (studioOpen) does"


def test_the_retired_window_and_focus_are_gone():
    assert node("return [typeof R.newlyWorking,typeof R.createRail]") == ["undefined", "function"]
    assert not (RUNTIME / "control_center_presentation_window.js").exists(), "the floating window host is retired (Slice 09)"


def test_the_menu_has_every_action_says_why_one_is_unavailable_and_an_archived_row_only_restores():
    normal = node(f"return R.menuModel({{presentation_id:'{P1}',title:'A',hidden:false,archived:false,work:{{state:'done'}}}},{{}}).map(i=>i==='-'?'-':i.act)")
    assert normal == ["open", "studio", "edit", "play", "-", "hide", "rename", "-", "archive"], "§ 1: « Remotion Studio… » (Slice 11)"
    labels = node(f"return R.menuModel({{presentation_id:'{P1}',title:'A',work:{{state:'done'}}}},{{}}).filter(i=>i!=='-').map(i=>i.label)")
    assert labels[:4] == ["Ouvrir les variantes", "Remotion Studio…", "Éditer", "Présenter"], "contract § 1: the rail opens Variants, then Remotion Studio, and « Présenter » starts a run"
    hidden = node(f"return R.menuModel({{presentation_id:'{P1}',title:'A',hidden:true,archived:false,work:{{state:'problem'}}}},{{}}).filter(i=>i!=='-').map(i=>i.act)")
    assert "show" in hidden and "hide" not in hidden and "ack" in hidden, "acknowledge only when orange"
    busy = node(f"return R.menuModel({{presentation_id:'{P1}',title:'A',work:{{state:'done'}}}},{{playing:true,playingThis:true}}).filter(i=>i!=='-').map(i=>[i.act,!!i.note])")
    assert dict(map(tuple, busy)) == {"open": False, "studio": True, "edit": True, "play": True, "hide": False, "rename": False, "archive": True}
    other = node(f"return R.menuModel({{presentation_id:'{P1}',title:'A',work:{{state:'done'}}}},{{playing:true,playingThis:false}}).filter(i=>i!=='-').map(i=>[i.act,!!i.note])")
    assert dict(map(tuple, other))["open"] is True, "another presentation plays: Variants shows that one"
    archived = node(f"return R.menuModel({{presentation_id:'{P1}',title:'A',archived:true}},{{}}).map(i=>i.act)")
    assert archived == ["restore"]


def test_monograms_and_hues_are_stable_and_text_is_cleaned():
    out = node("return [R.monogram('Lancement produit'),R.monogram('bilan'),R.monogram('  '),R.hueOf('pst_a')===R.hueOf('pst_a'),R.cleanLine('a\\u202eb\\n\\tc',10),R.cleanLine('x'.repeat(50),10)]")
    assert out == ["LP", "BI", "?", True, "a b c", "xxxxxxxxx…"]


# ------------------------------------------------------------------ rail actif (Slice 07 du handoff orbital, D10)

UNSEEN = "{since:'2026-10-16T09:00:00Z',label:'presentation_edit'}"


def test_state_precedence_working_problem_unreviewed_done():
    out = node(f"""const row=(state,unseen)=>({{presentation_id:'{P1}',title:'A',work:state?{{state}}:undefined,unreviewed:unseen?{UNSEEN}:null}});
      return [R.displayState(row('working',true)),R.displayState(row('problem',true)),R.displayState(row('done',true)),R.displayState(row('done',false)),
              R.displayState(row(null,true)),R.displayState({{presentation_id:'{P1}',work:{{state:'bizarre'}}}})]""")
    assert out == ["working", "problem", "unreviewed", "done", "unknown", "unknown"], "working > problem > unreviewed > done; unknown is never green"
    model = node(f"""const m=R.modelOf([{{presentation_id:'{P1}',title:'A',work:{{state:'done'}},unreviewed:{UNSEEN}}},
      {{presentation_id:'{P2}',title:'B',work:{{state:'problem'}},unreviewed:{UNSEEN}}}]);return [m.unreviewed.length,m.problems.length,m.working.length]""")
    assert model == [1, 1, 0], "a problem stays a problem (its own treatment), never counted as to-review"
    colors = node("return R.STATE_COLOR")
    assert colors["problem"] != colors["unreviewed"] and "--sem-problem" in colors["problem"] and "--sem-review" in colors["unreviewed"]
    assert "--sem-working" in colors["working"] and "--sem-done" in colors["done"] and colors["unknown"] == "transparent"


def test_label_accompanies_every_dot():
    cards = node(f"""const now=Date.parse('2026-10-16T12:00:00Z');
      return [['working',null],['problem',null],['done',{UNSEEN}],['done',null],[null,null]].map(([state,unseen])=>
        R.cardOf({{presentation_id:'{P1}',title:'Deck',updated_at:'2026-10-16T10:00:00Z',work:state?{{state}}:undefined,unreviewed:unseen,type:{{engine:'remotion'}}}},now))
        .map(c=>[c.state,c.stateShort,c.stateLabel,c.color])""")
    assert [c[0] for c in cards] == ["working", "problem", "unreviewed", "done", "unknown"]
    for state, short, long, color in cards:
        assert short and long and color, state
    assert [c[1] for c in cards] == ["En cours", "Problème", "À revoir", "Prête", "État inconnu"]
    source = (RUNTIME / "control_center_presentation_rail.js").read_text(encoding="utf-8")
    assert "status.append(dot,el('span','jvr-state',card.stateShort))" in source, "the dot is always drawn with its label beside it"


def test_placeholder_when_no_preview():
    out = node(f"""const base={{presentation_id:'{P1}',title:'Deck',work:{{state:'done'}}}};
      return [R.previewOf({{...base,type:{{engine:'remotion'}},preview:null}}),R.previewOf({{...base,type:{{engine:'slidecar'}}}}),
        R.previewOf({{...base,preview:{{artifact_id:'../../etc/passwd',kind:'presentation_still'}}}}),
        R.previewOf({{...base,preview:{{artifact_id:'jart_0123456789abcdef',kind:'presentation_video'}}}}),
        R.previewOf({{...base,type:{{engine:'remotion'}},preview:{{artifact_id:'jart_0123456789abcdef',kind:'presentation_still',width:1280,height:720}}}})]""")
    assert out[0] == {"kind": "placeholder", "label": "Présentation · Remotion"}
    assert out[1] == {"kind": "placeholder", "label": "Présentation · Slidecar"}
    assert out[2]["kind"] == "placeholder" and out[3]["kind"] == "placeholder", "a malformed id or another kind is never fetched"
    assert out[4] == {"kind": "image", "url": "/api/artifacts/jart_0123456789abcdef/payload", "artifact_id": "jart_0123456789abcdef",
                      "width": 1280, "height": 720}, "the bounded payload route, never a path"
    assert node("return R.typeOf({}).label") == "Présentation", "unknown engine: a generic type, never a guess"


def test_card_metadata_density_and_review_menu():
    now = "Date.parse('2026-10-16T12:00:00Z')"
    agos = node(f"return ['2026-10-16T11:59:40Z','2026-10-16T11:30:00Z','2026-10-16T10:00:00Z','2026-10-13T12:00:00Z','2026-09-20T12:00:00Z','nope'].map(t=>R.ago(t,{now}))")
    assert agos == ["à l’instant", "il y a 30 min", "il y a 2 h", "il y a 3 j", "il y a 4 sem.", ""]
    card = node(f"return R.cardOf({{presentation_id:'{P1}',title:'Deck',variant_count:3,updated_at:'2026-10-16T10:00:00Z',work:{{state:'done'}},type:{{engine:'remotion'}}}},{now})")
    assert card["meta"] == "Remotion · 3 variantes" and card["when"] == "il y a 2 h"
    densities = node("""return [R.densityOf({width:1440}),R.densityOf({width:1440,collapsed:true}),R.densityOf({width:1000}),R.densityOf({width:700}),
      R.densityOf({width:375}),R.densityOf({width:1440,studio:true}),R.densityOf({width:1000,studio:true})]""")
    assert densities == ["full", "slim", "slim", "drawer", "drawer", "compact", "slim"], "D10 widths: 300 / 72 below 1100 / tab below 700"
    menu = node(f"return R.menuModel({{presentation_id:'{P1}',title:'A',work:{{state:'done'}},unreviewed:{UNSEEN}}},{{}}).map(i=>i==='-'?'-':i.act)")
    assert menu == ["open", "studio", "edit", "play", "-", "hide", "rename", "review", "-", "archive"], "« Marquer comme vu » only when yellow"
