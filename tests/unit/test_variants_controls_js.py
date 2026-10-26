"""The Variants control audit by node (handoff jarvis-remotion-native-studio-playback-fix, Slice 10: simplify the existing Variants UI).

Two levels, each with negative cases:

1. The pure models: the keyboard sheet is DERIVED from the one § 4.15 key map (`JarvisVariantsStageMedia.KEY_ACTIONS`), so a key added to
   the map shows in the sheet; the tree keys of the sheet are the keys `treeKey` really answers.
2. The explorer on the fake DOM: each control once (no variant bar, « Présenter » on the scene row, the toolbar holds playback controls
   only); `?` and « ⋯ › Raccourcis clavier » open ONE modal sheet that `Échap` closes, focus back; during a run the tree, the actions and
   the upgrade notice are inert AND marked dimmed (`data-run`), the reason is on screen, the scene row gives way to the presenter strip;
   the end gives everything back; the variant count says what it counts; no « explorateur » in what the user reads (PX-1).

Real Chrome (opacity, overflow, three window sizes): `test_variants_controls_browser.py`. Contract: `docs/presentation-studio.md` ›
*Variants control audit (Level 3, Slice 10)*.
"""

from __future__ import annotations

import json
import subprocess

from tests.fakes.explorer_js import run_ui
from tests.unit.test_remotion_stage_js import RUNTIME
from tests.unit.test_variants_run_js import RUN_UI

MEDIA_JS = RUNTIME / "control_center_presentation_studio_stage_media.js"
CORE_JS = RUNTIME / "control_center_presentation_studio_explorer_core.js"


def node(script: str) -> object:
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ------------------------------------------------------------------ 1. pure models

def test_the_sheet_lists_every_key_of_the_one_key_map_in_both_modes():
    out = node(f"""
      const M=require({json.dumps(str(MEDIA_JS))});
      const names=new Set(Object.keys(M.KEY_ACTIONS).map(k=>M.KEY_NAMES[k]));
      const rows=m=>M.shortcutRows(m);
      const keysOf=m=>new Set(rows(m).flatMap(r=>r.keys));
      const missing=m=>[...names].filter(n=>!keysOf(m).has(n));
      const actions=m=>rows(m).map(r=>r.action);
      /* a key added to the map shows in the sheet without anyone writing the sheet */
      const mutated=Object.assign({{}},M.KEY_ACTIONS,{{x:'sound'}});
      process.stdout.write(JSON.stringify({{video:missing('video'),run:missing('run'),unnamed:Object.keys(M.KEY_ACTIONS).filter(k=>!M.KEY_NAMES[k]),
        actionsVideo:actions('video'),actionsRun:actions('run'),does:rows('video').filter(r=>!r.does||r.does===r.action).map(r=>r.action),
        frozen:Object.isFrozen(rows('video')[0])&&Object.isFrozen(rows('video')[0].keys),mutatedHasX:Object.keys(mutated).includes('x')}}));
    """)
    assert out["video"] == [] and out["run"] == [], "every key of the § 4.15 map is in the sheet, in both modes"
    assert out["unnamed"] == [], "every key of the map has a display name"
    assert out["does"] == [], "every row says what it does"
    assert set(out["actionsVideo"]) == {"toggle", "next", "restart", "previous", "home", "end", "step_back", "step_forward", "fullscreen", "sound", "escape", "help"}
    assert "skip" in out["actionsRun"] and "skip" not in out["actionsVideo"], "S (leave a locked sequence) exists in a run only"
    assert out["frozen"] is True


def test_the_tree_keys_of_the_sheet_are_the_keys_tree_key_answers():
    out = node(f"""
      const C=require({json.dumps(str(CORE_JS))});
      const rows=[{{id:'a',hasChildren:true,expanded:false,parentId:null}},{{id:'b',hasChildren:false,expanded:false,parentId:null}}];
      const raw={{'F2':'F2','Suppr':'Delete','Entrée':'Enter','A':'a','N':'n','R':'r','↑':'ArrowUp','↓':'ArrowDown','→':'ArrowRight'}};
      const listed=C.TREE_SHORTCUTS.flatMap(r=>r.keys);
      const answered=Object.entries(raw).filter(([shown])=>listed.includes(shown)).map(([shown,key])=>[shown,!!C.treeKey(rows,0,key,{{}})]);
      process.stdout.write(JSON.stringify({{listed,answered,menu:!!C.treeKey(rows,0,'F10',{{shift:true}})}}));
    """)
    assert all(ok for _shown, ok in out["answered"]), out["answered"]
    assert {"F2", "Suppr", "Entrée", "A", "N", "R", "[", "]", "Maj+C", "Maj+F10"} <= set(out["listed"]), out["listed"]
    assert out["menu"] is True


# ------------------------------------------------------------------ 2. the explorer on the fake DOM

def test_each_control_once_the_toolbar_holds_playback_only_and_the_count_says_what_it_counts(tmp_path):
    out = run_ui(tmp_path, RUN_UI + r"""
      seed(3);
      const ex=make({player:fakePlayer});
      await ex.open({presentation_id:PID,fullscreen:false});await env.advance(400);
      const bar=q('.jvx-transport');
      const names=[...qa('button',bar)].filter(b=>!b.hidden).map(b=>(b.getAttribute('aria-label')||b.textContent).trim());
      const note=q('.jvx-stage-note');
      const texts=[];env.walk(ex.element(),n=>{for(const k of ['aria-label','title'])if(n.getAttribute&&n.getAttribute(k))texts.push(n.getAttribute(k))});
      env.walk(ex.element(),n=>{if(n.nodeType===3||!n.children||!n.children.length)texts.push(n.textContent||'')});
      return {names,vbar:qa('.jvx-vbar').length+qa('.jvx-vchip').length,presentInBar:!!bar.querySelector('[data-act="present"]'),
        presentInNote:q('[data-act="present"]').parentNode===note,rowOrder:[...note.children].map(c=>c.className||c.dataset.act),
        count:q('.jvx-panehead .jvx-chip').textContent,hint:q('.jvx-hint-keys').textContent,
        fsName:q('.jvx-top-actions').children[2].getAttribute('aria-label'),close:q('.jvx-top-actions').children[3].getAttribute('aria-label'),
        explorateur:texts.filter(t=>/explorateur/i.test(t))};
    """)
    assert out["names"] == ["Scène précédente", "Début de la slide", "Reculer de 5 secondes", "Lire", "Avancer de 5 secondes", "Scène suivante", "Son", "Plein écran", "Plus de lecture"], out["names"]
    assert out["vbar"] == 0, "the variant bar is merged into the tree (§ 6 #8)"
    assert out["presentInBar"] is False and out["presentInNote"] is True, "« Présenter » is on the scene row, not a playback control"
    assert out["rowOrder"][0] == "jvx-transport" and out["rowOrder"][1] == "jvx-scene-count", out["rowOrder"]
    assert out["count"] == "3 / 64 variantes", "authoring metadata says what it counts (never a position)"
    assert "?" in out["hint"] and "parcourir" not in out["hint"], "the key hint is merged into the sheet (§ 6 #6)"
    assert out["fsName"] == "Plein écran" and out["close"] == "Fermer Variantes", "names that survive a narrow window (PX-1)"
    assert out["explorateur"] == [], ("PX-1: « explorateur » is not a name the user reads", out["explorateur"])


def test_question_mark_opens_one_modal_sheet_escape_closes_it_and_the_overflow_entry_opens_it_too(tmp_path):
    out = run_ui(tmp_path, RUN_UI + r"""
      seed(3);
      const ex=make({player:fakePlayer});
      await ex.open({presentation_id:PID,fullscreen:false});await env.advance(400);
      const stage=q('.jvx-stage');stage.focus();
      const ev=env.key(stage,'?',{shiftKey:true});await env.advance(20);
      const sheet=()=>q('[data-kind="shortcuts"]');
      const opened={ok:!!sheet(),prevented:ev.defaultPrevented,modal:sheet()&&sheet().getAttribute('aria-modal'),title:sheet()&&q('h2',sheet()).textContent,
        kbd:sheet()?qa('kbd',sheet()).map(k=>k.textContent):[],inert:q('.jvx-body').inert,dialog:ex.state().dialog,focusIn:!!sheet()&&sheet().contains(doc.activeElement)};
      env.key(doc.activeElement,'?',{shiftKey:true});await env.advance(20);
      const toggled=!sheet();
      env.key(stage,'?',{shiftKey:true});await env.advance(20);
      env.key(doc.activeElement,'Escape');await env.advance(20);
      const escaped={gone:!sheet(),open:ex.isOpen(),focus:doc.activeElement===stage,inert:q('.jvx-body').inert};
      /* typing a « ? » in a field is text, never the sheet */
      const field=doc.createElement('input');ex.element().appendChild(field);field.focus();
      env.key(field,'?',{shiftKey:true});await env.advance(20);
      const typed=!sheet();field.remove();
      const more=q('[aria-label="Plus de lecture"]');more.focus();more.click();await env.advance(10);
      qa('[role="menuitem"]').find(b=>b.textContent.includes('Raccourcis clavier')).click();await env.advance(20);
      const fromMenu={count:qa('[data-kind="shortcuts"]').length};
      env.key(doc.activeElement,'Escape');await env.advance(20);
      fromMenu.focusBack=doc.activeElement===more;
      return {opened,toggled,escaped,typed,fromMenu,logs:env.logs.filter(l=>l[1].includes('shortcuts_opened')).length};
    """)
    o = out["opened"]
    assert o["ok"] and o["prevented"] and o["modal"] == "true" and o["title"] == "Raccourcis clavier" and o["dialog"] == "shortcuts"
    assert o["inert"] is True and o["focusIn"] is True, "a modal sheet: the rest of Variants is inert, the focus is in it"
    for key in ("Espace", "→", "←", "Page suivante", "Début", "Fin", ",", ".", "F", "M", "Échap", "?", "F2", "Suppr", "[", "]", "Maj+C"):
        assert key in o["kbd"], (key, o["kbd"])
    assert out["toggled"] is True, "`?` again closes it"
    assert out["escaped"] == {"gone": True, "open": True, "focus": True, "inert": False}, "Échap closes the sheet only; focus back"
    assert out["typed"] is True, "a « ? » typed in a field never opens the sheet"
    assert out["fromMenu"] == {"count": 1, "focusBack": True}
    assert out["logs"] >= 3, "each opening is logged (info)"


def test_during_a_run_the_inert_parts_are_marked_dimmed_with_the_reason_and_the_end_gives_them_back(tmp_path):
    out = run_ui(tmp_path, RUN_UI + r"""
      seed(3);
      const ex=make({player:fakePlayer});
      await showView(runView());
      fakePlayer.surf=SURF;fire('jarvis:studio-surface',{surface:SURF});await env.advance(200);
      const host=ex.element(),note=q('.jvx-run-note');
      const acts=qa('.jvx-actions button').map(b=>[b.textContent.trim(),b.getAttribute('aria-disabled'),b.title]);
      const during={dataRun:host.hasAttribute('data-run'),note:[note.hidden,note.textContent],acts,inert:[q('.jvx-treepane').inert,q('.jvx-actions').inert],
        sceneRow:[q('.jvx-scene-count').hidden,q('.jvx-scene-line').hidden,q('[data-act="present"]').hidden],stop:q('[data-act="stop_run"]').hidden};
      /* the sheet in a run speaks of the score */
      env.key(q('.jvx-stage'),'?',{shiftKey:true});await env.advance(20);
      const runSheet=[...qa('[data-kind="shortcuts"] td')].map(t=>t.textContent).join(' | ');
      env.key(doc.activeElement,'Escape');await env.advance(20);
      await showView({phase:'idle',running:false,last_run:{reason:'stopped'}});await env.advance(500);
      const after={dataRun:host.hasAttribute('data-run'),note:note.hidden,inert:[q('.jvx-treepane').inert,q('.jvx-actions').inert],
        branch:qa('.jvx-actions button').find(b=>b.textContent.includes('Nouvelle variante')).getAttribute('aria-disabled')==='true',
        sceneRow:[q('.jvx-scene-count').hidden,q('.jvx-scene-line').hidden,q('[data-act="present"]').hidden]};
      return {during,runSheet,after};
    """)
    d = out["during"]
    assert d["dataRun"] is True, "the host carries `data-run`: the CSS dims the tree, the actions and the upgrade notice"
    assert d["note"][0] is False and "Présentation en cours" in d["note"][1], "the reason is on screen, beside the actions"
    assert [a[0] for a in d["acts"]] == ["Activer", "Nouvelle variante…", "Renommer…", "Archiver…"], "the actions stay on screen"
    assert all(a[1] == "true" and "Présentation en cours" in a[2] for a in d["acts"]), d["acts"]
    assert d["inert"] == [True, True]
    assert d["sceneRow"] == [True, True, True] and d["stop"] is False, "the presenter strip replaces the scene row; one « Arrêter »"
    assert "Élément suivant de la partition" in out["runSheet"] and "Sortir de la séquence verrouillée" in out["runSheet"]
    a = out["after"]
    assert a == {"dataRun": False, "note": True, "inert": [False, False], "branch": False, "sceneRow": [False, False, False]}, a
