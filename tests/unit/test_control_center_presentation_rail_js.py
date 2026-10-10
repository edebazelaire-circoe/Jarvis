"""Fonctions pures du rail et de la fenetre des presentations (node, sans navigateur) : modele, visibilite, menu, concentration, choix de la variante.

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
            f"const W=require({json.dumps(str(RUNTIME / 'control_center_presentation_window.js'))});"
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
    assert results == [False, True, True, True, True, False, True]


def test_focus_picks_only_presentations_that_just_started_to_work():
    before = f"[{{presentation_id:'{P1}',work:{{state:'working'}}}},{{presentation_id:'{P2}',work:{{state:'done'}}}}]"
    after = (f"[{{presentation_id:'{P1}',work:{{state:'working'}}}},{{presentation_id:'{P2}',work:{{state:'working'}}}},"
             f"{{presentation_id:'{P3}',work:{{state:'working'}},archived:true}}]")
    assert node(f"return R.newlyWorking({before},{after})") == [P2]


def test_the_menu_has_every_action_says_why_one_is_unavailable_and_an_archived_row_only_restores():
    normal = node(f"return R.menuModel({{presentation_id:'{P1}',title:'A',hidden:false,archived:false,work:{{state:'done'}}}},{{}}).map(i=>i==='-'?'-':i.act)")
    assert normal == ["open", "studio", "edit", "play", "-", "hide", "rename", "-", "archive"]
    hidden = node(f"return R.menuModel({{presentation_id:'{P1}',title:'A',hidden:true,archived:false,work:{{state:'problem'}}}},{{}}).filter(i=>i!=='-').map(i=>i.act)")
    assert "show" in hidden and "hide" not in hidden and "ack" in hidden, "acknowledge only when orange"
    busy = node(f"return R.menuModel({{presentation_id:'{P1}',title:'A',work:{{state:'done'}}}},{{playing:true,playingThis:true}}).filter(i=>i!=='-').map(i=>[i.act,!!i.note])")
    assert dict(map(tuple, busy)) == {"open": False, "studio": True, "edit": True, "play": True, "hide": False, "rename": False, "archive": True}
    archived = node(f"return R.menuModel({{presentation_id:'{P1}',title:'A',archived:true}},{{}}).map(i=>i.act)")
    assert archived == ["restore"]


def test_monograms_and_hues_are_stable_and_text_is_cleaned():
    out = node("return [R.monogram('Lancement produit'),R.monogram('bilan'),R.monogram('  '),R.hueOf('pst_a')===R.hueOf('pst_a'),R.cleanLine('a\\u202eb\\n\\tc',10),R.cleanLine('x'.repeat(50),10)]")
    assert out == ["LP", "BI", "?", True, "a b c", "xxxxxxxxx…"]


def test_the_window_reads_the_active_variant_and_redraws_only_on_a_new_revision():
    view = "{presentation:{active_variant_id:'psv_b'},variants:[{variant_id:'psv_a',revision:1,scenes:[]},{variant_id:'psv_b',revision:4,variant_number:2,scenes:[{scene_id:'pss_1',title:'  Accroche ',prefab:{id:'p',version:1}},{scene_id:5},null]}]}"
    out = node(f"const v=W.pickVariant({view});return {{id:v.variant_id,scenes:W.scenesOf(v),same:W.changed({{variantId:'psv_b',revision:4}},v),rev:W.changed({{variantId:'psv_b',revision:3}},v),"
               f"other:W.changed({{variantId:'psv_a',revision:4}},v),first:W.changed(null,v),none:W.pickVariant({{presentation:null,variants:[]}})}}")
    assert out["id"] == "psv_b" and [s["title"] for s in out["scenes"]] == ["Accroche"] and out["scenes"][0]["prefab"] == {"id": "p", "version": 1}
    assert (out["same"], out["rev"], out["other"], out["first"], out["none"]) == (False, True, True, True, None)
