"""A value typed in the editor is never lost and never lands on another scene (presentation-edition-v1 Slice 09, QA rework).

Same bench as `test_presentation_studio_inspector_js.py` (the REAL module, a DOM and a Core in miniature). What the QA found and what is
pinned here:

- B1: Variants changes the scene on screen by itself (continuous play) while a value is typed and not released: the editor used to drop
  the draft in silence and keep the caret over the next scene's value. Now the draft is saved on ITS scene first, then the editor follows,
  says so, and the caret leaves the field;
- Core stopped during an edit: the typed value stays in the field, the message is the product's (no transport text), and it is saved as
  soon as Core answers again; a move asked meanwhile waits and is said;
- m3: an undo that brings another scene waits for the queued writes of the scene on screen (they land there, never on the other scene);
- the context line (a polite live region) is not rewritten after each save; « Annuler » names its scene in visible text;
- closing the editor (×, Échap) saves what is typed first, and gives the focus back to what opened it.
"""

from __future__ import annotations

from tests.unit.test_presentation_studio_inspector_js import run_js

#: Variants saying the scene on screen (the event the explorer dispatches, `jarvis:studio-explorer-scene`).
SAY = r"""
const say=(t,scene,variant)=>{const v=t.inspector.view();
  (t.env.win.listeners['jarvis:studio-explorer-scene']||[]).forEach(fn=>fn({detail:{presentation_id:v.presentation_id,variant_id:variant||v.variant_id,scene_id:scene}}))};
const commitsOn=(t)=>t.core.st.calls.filter(c=>c.kind==='edit'&&c.mode==='commit').map(c=>c.body.ops[0].scene_id);
"""


def test_a_draft_is_saved_on_its_scene_before_the_editor_follows_variants_and_the_caret_leaves_the_field(tmp_path):
    out = run_js(tmp_path, SAY + r"""
      const t=await boot();await t.open();
      const field=text(t,'title');
      field.focus&&field.focus();t.env.doc.activeElement=field;
      field.value='Brouillon QA';field.dispatch('input');await t.env.advance(50);
      const before={scene:t.inspector.view().scene_id,drafts:t.inspector.view().pendingDrafts};
      say(t,'pss_2');await t.env.flush(30);
      const v=t.inspector.view();
      return {before,after:{scene:v.scene_id,drafts:v.pendingDrafts},stored:t.core.st.values.title,on:commitsOn(t),status:status(t),
        focus:t.env.doc.activeElement&&t.env.doc.activeElement.id,live:t.find(t.panel(),n=>n.attrs&&n.attrs['aria-live']==='polite').map(n=>n.textContent).join(' | '),
        logs:t.env.logs.map(l=>l[1]).filter(l=>/move_|drafts_abandoned/.test(l))};
    """)
    assert out["before"] == {"scene": "pss_1", "drafts": ["title"]}
    assert out["stored"] == "Brouillon QA" and out["on"] == ["pss_1"], "the typed value is written on the scene it was typed on, once"
    assert out["after"] == {"scene": "pss_2", "drafts": []}, "then the editor follows Variants"
    assert any("Saisie enregistrée sur la scène 1" in s and "scène 2" in s for s in out["status"]), out["status"]
    assert out["focus"] == "jviTitle", "the caret never stays in a field that now shows another scene"
    assert any("move_saving" in l for l in out["logs"]) and any("move_after_save" in l for l in out["logs"])
    assert not any("drafts_abandoned" in l and '"dirty":0' not in l for l in out["logs"]), "nothing typed is abandoned"


def test_core_stopped_keeps_the_typed_value_says_it_in_french_and_saves_it_when_core_answers_again(tmp_path):
    out = run_js(tmp_path, SAY + r"""
      const t=await boot();await t.open();
      const field=text(t,'title');
      t.core.st.down=true;
      field.value='Saisie gardée';field.dispatch('input');await t.env.advance(400);
      field.dispatch('change');await t.env.flush(20);
      const down={value:text(t,'title').value,msg:msg(t,'title'),stored:t.core.st.values.title,drafts:t.inspector.view().pendingDrafts};
      say(t,'pss_2');await t.env.flush(30);
      const held={scene:t.inspector.view().scene_id,status:status(t),value:text(t,'title').value};
      t.core.st.down=false;
      await t.inspector.pollReloads();await t.env.flush(40);await t.env.advance(10);await t.env.flush(40);
      const back={scene:t.inspector.view().scene_id,stored:t.core.st.values.title,on:commitsOn(t),drafts:t.inspector.view().pendingDrafts,status:status(t)};
      return {down,held,back,errors:errors(t)};
    """)
    down = out["down"]
    assert down["value"] == "Saisie gardée" and down["stored"] != "Saisie gardée" and down["drafts"] == ["title"], "kept, not replaced"
    assert "votre saisie est gardée" in down["msg"] and "Réessayer" in down["msg"]
    assert "unreachable" not in down["msg"] and "connection refused" not in down["msg"] and "Core is" not in down["msg"], down["msg"]
    held = out["held"]
    assert held["scene"] == "pss_1" and held["value"] == "Saisie gardée", "the editor stays on the scene of the unsaved value"
    assert any("L’éditeur reste sur la scène 1" in s and "Abandonner ma saisie et continuer" in s for s in held["status"]), held["status"]
    back = out["back"]
    assert back["stored"] == "Saisie gardée" and back["on"][-1] == "pss_1", "saved on its scene once Core answers"
    assert back["drafts"] == [] and back["scene"] == "pss_2", "then the editor follows Variants"
    assert any("commit_unreachable" in e for e in out["errors"]), "the failure is in the journal"


def test_a_held_move_names_the_setting_and_its_warning_gives_way_to_the_saved_line_when_core_answers(tmp_path):
    """Slice 09 mini-rework (QA M1, m1): the save was still in flight when the move came (`move_held kept:[]`, « une valeur »), and the
    warning « L’éditeur reste sur la scène 1… n’est pas enregistrée » stayed on screen after Core saved the value and the editor moved."""
    out = run_js(tmp_path, SAY + r"""
      const t=await boot();await t.open();
      let open;t.hook.gate=new Promise(r=>{open=r});
      t.core.st.down=true;
      const field=text(t,'title');
      field.value='Saisie en vol';field.dispatch('input');field.dispatch('change');await t.env.flush(5);
      say(t,'pss_2');await t.env.flush(5);
      open();t.hook.gate=null;await t.env.flush(40);
      const held={scene:t.inspector.view().scene_id,status:status(t),
        log:t.env.logs.map(l=>l[1]).filter(l=>/move_held/.test(l))};
      t.core.st.down=false;
      await t.inspector.pollReloads();await t.env.flush(40);await t.env.advance(10);await t.env.flush(40);
      const back={scene:t.inspector.view().scene_id,stored:t.core.st.values.title,status:status(t)};
      await t.env.advance(6000);await t.env.flush(10);
      return {held,back,later:status(t)};
    """)
    held = out["held"]
    assert held["scene"] == "pss_1"
    assert any("L’éditeur reste sur la scène 1" in s and "« Titre »" in s for s in held["status"]), held["status"]
    assert held["log"] and '"kept":["title"]' in held["log"][-1], held["log"]
    back = out["back"]
    assert back["stored"] == "Saisie en vol" and back["scene"] == "pss_2"
    assert not any("reste sur la" in s or "n’est pas enregistrée" in s for s in back["status"]), back["status"]
    assert any("« Titre » enregistré" in s and "scène 1" in s and "scène 2" in s for s in back["status"]), back["status"]
    assert out["later"] == [], "the confirmation goes away by itself"


def test_an_undo_waits_for_the_queued_writes_of_the_scene_on_screen(tmp_path):
    out = run_js(tmp_path, SAY + r"""
      const t=await boot();await t.open();
      let open;t.hook.gate=new Promise(r=>{open=r});
      const field=text(t,'title');
      field.value='Premier';field.dispatch('input');field.dispatch('change');await t.env.flush(5);
      const sw=t.find(t.row('glow'),n=>n.attrs.role==='switch')[0];
      sw.click();await t.env.flush(5);
      const undo=t.inspector.runHistory('undo');
      await t.env.flush(5);
      open();t.hook.gate=null;
      await undo;await t.env.flush(30);
      return {on:commitsOn(t),undo:t.core.st.calls.filter(c=>c.kind==='history').length,glow:t.core.st.values.glow,title:t.core.st.values.title};
    """)
    assert out["on"] == ["pss_1", "pss_1"], "both queued writes landed on the scene they were made on"
    assert out["title"] == "Premier" and out.get("glow") is not True, "the undo undid the LAST change (the switch), after the queue"


def test_enter_on_undo_never_hands_the_focus_to_redo(tmp_path):
    """Slice 09 mini-rework (QA m2): « Annuler » pressed by Enter and then disabled (nothing left to undo) gives the focus to the title, as
    the contract says, never to « Rétablir » (a second Enter would redo what the first one undid)."""
    out = run_js(tmp_path, SAY + r"""
      const t=await boot();await t.open();
      const field=text(t,'title');field.value='Un';field.dispatch('input');field.dispatch('change');await t.env.flush(30);
      const undo=t.find(t.panel(),n=>n.tagName==='BUTTON'&&String(n.attrs['aria-label']||'').startsWith('Annuler'))[0];
      const redo=t.find(t.panel(),n=>n.tagName==='BUTTON'&&String(n.attrs['aria-label']||'').startsWith('Rétablir'))[0];
      undo.focus&&undo.focus();t.env.doc.activeElement=undo;
      await t.inspector.runHistory('undo');await t.env.flush(30);
      const a=t.env.doc.activeElement;
      return {undoDisabled:!!undo.disabled,redoDisabled:!!redo.disabled,focus:a===redo?'redo':a===undo?'undo':(a&&a.id)};
    """)
    assert out["undoDisabled"] is True and out["redoDisabled"] is False, out
    assert out["focus"] == "jviTitle", out


def test_the_context_line_is_not_rewritten_after_a_save_and_undo_names_its_scene_in_visible_text(tmp_path):
    out = run_js(tmp_path, SAY + r"""
      const t=await boot();await t.open();
      const ctx=t.find(t.panel(),n=>n.attrs&&n.attrs['data-role']==='edit-context')[0];
      const node0=ctx.children[0];
      const field=text(t,'title');field.value='Un';field.dispatch('input');field.dispatch('change');await t.env.flush(30);
      const same=ctx.children[0]===node0;
      const note=t.find(t.panel(),n=>n.attrs&&n.attrs['data-role']==='undo-scene')[0];
      return {same,note:{hidden:note.hidden,text:note.textContent}};
    """)
    assert out["same"] is True, "a save does not rewrite the polite live context line"
    assert out["note"]["hidden"] is False and "scène 1" in out["note"]["text"] and "Annuler" in out["note"]["text"]


def test_closing_saves_what_is_typed_and_gives_the_focus_back_to_modifier(tmp_path):
    out = run_js(tmp_path, SAY + r"""
      const t=await boot();await t.open();
      const opener={id:'modifier',focused:0,isConnected:true,disabled:false,focus(){this.focused++;t.env.doc.activeElement=this},closest:()=>null};
      const v=t.inspector.view();
      await t.inspector.edit({presentation_id:v.presentation_id,variant_id:v.variant_id,scene_id:'pss_1',opener});await t.env.flush(10);
      const field=text(t,'title');field.value='Avant fermeture';field.dispatch('input');await t.env.advance(50);
      const close=t.find(t.panel(),n=>n.tagName==='BUTTON'&&n.attrs['aria-label']==="Fermer l'inspecteur")[0];
      close.click();await t.env.flush(30);
      return {stored:t.core.st.values.title,open:t.inspector.view().open,focused:opener.focused};
    """)
    assert out["stored"] == "Avant fermeture" and out["open"] is False
    assert out["focused"] == 1, "the focus goes back to « Modifier », not to the dock button under Variants"
