"""Le comportement de l'inspecteur du Studio, par node (jarvis-interactive-presentation-studio, Slice 07).

Suite de `test_presentation_studio_inspector_js.py` (meme banc : le VRAI module, un DOM et un Core en miniature) : l'aperçu contre
l'enregistrement (ENTRY CONDITION de la Slice 08 : une modification = une entree d'historique), les erreurs typees dites avec les mots de
Core, la base perimee, le 409 de rechargement, annuler / retablir, le masquage en lecture, le clavier, et l'absence de tout chemin
d'ecriture ou de persistance propre a l'inspecteur.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

from tests.unit.test_presentation_studio_inspector_js import MODULE_PARTS, run_js


# ------------------------------------------------------------------ aperçu contre enregistrement (ENTRY CONDITION Slice 08)

def test_a_sixty_move_drag_sends_a_few_previews_writes_nothing_and_commits_exactly_once(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      await drag(t,'size',linear(1,1.7,60));
      const during={commits:t.core.st.commits,stored:t.core.st.values.size,revision:t.core.st.revision,
        draft:t.inspector.view().pendingDrafts,state:t.find(t.row('size'),n=>n.className.split(' ').includes('jvi-state'))[0].textContent};
      await t.env.advance(400);
      await release(t,'size');
      await t.env.advance(50);
      const edits=t.core.st.calls.filter(c=>c.kind==='edit');
      return {during,edits:edits.map(c=>c.mode),commit:edits.filter(c=>c.mode==='commit').map(c=>c.body),
        after:{commits:t.core.st.commits,size:t.core.st.values.size,history:t.core.st.undo.length},
        view:t.inspector.view().controls.find(c=>c.control_id==='size'),stats:t.inspector.stats(),
        lastPreview:edits.filter(c=>c.mode==='preview').slice(-1)[0].body.ops[0].value,
        info:t.env.logs.filter(l=>l[1].includes('commit_applied')).map(l=>l[1])};
    """)
    assert out["during"]["commits"] == 0 and out["during"]["stored"] == 1 and out["during"]["revision"] == 3, "nothing is written while dragging"
    assert out["during"]["draft"] == ["size"] and "non enregistré" in out["during"]["state"]
    previews = out["edits"].count("preview")
    assert 2 <= previews <= 10, f"60 moves over ~1 s are coalesced to a handful of previews, got {previews}"
    assert out["stats"]["previewsCoalesced"] >= 30, "the intermediate values were dropped, not queued"
    assert out["edits"].count("commit") == 1 and out["after"]["commits"] == 1 and out["after"]["history"] == 1
    assert out["lastPreview"] == 1.7, "the last value is always the one sent (trailing edge)"
    assert out["commit"] == [{"mode": "commit", "basis": {"variant_revision": 3},
                              "ops": [{"op": "control.set", "scene_id": "pss_1", "control_id": "size", "value": 1.7, "if_current": 1}]}]
    assert out["after"]["size"] == 1.7 and out["view"] == {"control_id": "size", "current": 1.7, "is_set": True}
    assert len(out["info"]) == 1 and '"previews":' in out["info"][0], "one durable line per commit, with how many previews preceded it"


def test_keyboard_steps_and_the_plus_button_commit_once_after_a_pause_and_enter_commits_at_once(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      const r=range(t,'tilt');
      for(const v of [1,2,3,4,5]){r.value=String(v);r.dispatch('input');await t.env.advance(120)}
      const before=t.core.st.commits;
      await t.env.advance(M.IDLE_COMMIT_MS+100);
      const afterPause={commits:t.core.st.commits,tilt:t.core.st.values.tilt,undo:t.core.st.undo.length};
      const plus=t.find(t.row('speed'),n=>n.attrs['aria-label']&&n.attrs['aria-label'].startsWith('Augmenter'))[0];
      for(let i=0;i<4;i++){plus.click();await t.env.advance(100)}
      const mid=t.core.st.commits;
      await t.env.advance(M.IDLE_COMMIT_MS+100);
      const plusDone={commits:t.core.st.commits,speed:t.core.st.values.speed};
      const rr=range(t,'tilt');rr.value='9';rr.dispatch('input');
      rr.dispatch('keydown',{key:'Enter'});await t.env.flush(12);
      return {before,afterPause,mid,plusDone,enter:{commits:t.core.st.commits,tilt:t.core.st.values.tilt}};
    """)
    assert out["before"] == 0, "five keyboard steps in a row do not fill the 32-entry history ring"
    assert out["afterPause"] == {"commits": 1, "tilt": 5, "undo": 1}
    assert out["mid"] == 1 and out["plusDone"] == {"commits": 2, "speed": 604}, "four + clicks = one entry, 600 -> 604"
    assert out["enter"] == {"commits": 3, "tilt": 9}


def test_typing_is_previewed_at_a_bounded_rate_and_committed_once_on_blur_or_enter(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      const field=text(t,'title');
      let typed='';
      for(const ch of 'Nouveau titre'){typed+=ch;field.value=typed;field.dispatch('input');await t.env.advance(30)}
      const during={commits:t.core.st.commits,previews:t.core.st.calls.filter(c=>c.mode==='preview').length};
      await t.env.advance(400);
      const settled=t.core.st.calls.filter(c=>c.mode==='preview').length;
      field.dispatch('change');await t.env.flush(12);
      const first={commits:t.core.st.commits,title:t.core.st.values.title,undo:t.core.st.undo.length};
      field.value='Autre';field.dispatch('input');
      field.dispatch('keydown',{key:'Enter'});await t.env.flush(12);
      const second={commits:t.core.st.commits,title:t.core.st.values.title};
      const area=t.find(t.row('body'),n=>n.tagName==='TEXTAREA')[0];
      area.value='ligne 1';area.dispatch('input');
      const enter=area.dispatch('keydown',{key:'Enter'});await t.env.flush(12);
      const afterEnter=t.core.st.commits;
      area.dispatch('keydown',{key:'Enter',ctrlKey:true});await t.env.flush(12);
      return {during,settled,first,second,newline:{prevented:enter.defaultPrevented,commits:afterEnter},ctrl:{commits:t.core.st.commits,body:t.core.st.values.body}};
    """)
    assert out["during"]["commits"] == 0 and out["during"]["previews"] <= 3
    assert out["settled"] <= 4, "13 keystrokes are not 13 requests"
    assert out["first"] == {"commits": 1, "title": "Nouveau titre", "undo": 1}
    assert out["second"] == {"commits": 2, "title": "Autre"}
    assert out["newline"] == {"prevented": False, "commits": 2}, "Enter in a text area is a new line, not a commit"
    assert out["ctrl"] == {"commits": 3, "body": "ligne 1"}


def test_discrete_widgets_commit_at_once_and_reset_goes_through_the_same_door(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      const sw=t.find(t.row('glow'),n=>n.attrs.role==='switch')[0];
      sw.click();await t.env.flush(12);
      const glow={commits:t.core.st.commits,value:t.core.st.values.glow,checked:sw.attrs['aria-checked']};
      const radios=t.find(t.row('layout'),n=>n.attrs.role==='radio');
      radios[2].click();await t.env.flush(12);
      const layout={value:t.core.st.values.layout,checked:radios.map(b=>b.attrs['aria-checked']),tab:radios.map(b=>b.attrs.tabindex)};
      radios[2].dispatch('keydown',{key:'ArrowRight'});await t.env.advance(M.IDLE_COMMIT_MS+50);   // a key traversal is a stepping path
      const wrapped=t.core.st.values.layout;
      const sel=t.find(t.row('easing'),n=>n.tagName==='SELECT')[0];
      sel.value='spring';sel.dispatch('change');await t.env.advance(M.IDLE_COMMIT_MS+50);
      const easing=t.core.st.values.easing;
      const reset=t.find(t.row('size'),n=>n.className.split(' ').includes('jvi-reset'))[0];
      reset.click();await t.env.flush(12);
      const edits=t.core.st.calls.filter(c=>c.kind==='edit'&&c.mode==='commit').map(c=>c.body.ops[0]);
      return {glow,layout,wrapped,easing,sizeAfter:Object.prototype.hasOwnProperty.call(t.core.st.values,'size'),
        resetDisabled:reset.disabled,edits,previews:t.core.st.calls.filter(c=>c.mode==='preview').length,
        view:t.inspector.view().controls.find(c=>c.control_id==='size')};
    """)
    assert out["glow"] == {"commits": 1, "value": True, "checked": "true"}
    assert out["layout"] == {"value": "right", "checked": ["false", "false", "true"], "tab": ["-1", "-1", "0"]}
    assert out["wrapped"] == "center" and out["easing"] == "spring"
    assert out["previews"] == 2, "a click or a switch is never previewed; only the two key-stepping paths (arrow traversal, closed list) preview"
    assert out["edits"][-1] == {"op": "control.reset", "scene_id": "pss_1", "control_id": "size", "if_current": 1}
    assert out["sizeAfter"] is False and out["view"] == {"control_id": "size", "current": 1, "is_set": False}
    assert out["resetDisabled"] is True, "after the reset the control is on its default: nothing left to reset"


def test_a_value_the_widget_can_see_is_wrong_is_not_sent_and_says_why(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      const sent=()=>t.core.st.calls.filter(c=>c.kind==='edit').length;
      const n=number(t,'size');
      n.value='9';n.dispatch('input');n.dispatch('change');await t.env.flush(12);
      const high={msg:msg(t,'size'),sent:sent(),invalid:t.find(t.row('size'),x=>x.attrs['aria-invalid']==='true').length};
      const hex=text(t,'accent');
      hex.value='#12';hex.dispatch('input');hex.dispatch('change');await t.env.flush(12);
      const color={msg:msg(t,'accent'),sent:sent()};
      const link=t.find(t.row('link'),x=>x.tagName==='INPUT')[0];
      link.value='javascript:alert(1)';link.dispatch('input');link.dispatch('change');await t.env.flush(12);
      const url={msg:msg(t,'link'),sent:sent()};
      const json=t.find(t.row('tags'),x=>x.tagName==='TEXTAREA')[0];
      json.value='[1,';json.dispatch('input');json.dispatch('change');await t.env.flush(12);
      const bad={msg:msg(t,'tags'),sent:sent()};
      json.value='["a","b"]';json.dispatch('input');json.dispatch('change');await t.env.flush(12);
      return {high,color,url,bad,good:t.core.st.values.tags,commits:t.core.st.commits};
    """)
    assert "au plus 1.8" in out["high"]["msg"] and out["high"]["sent"] == 0 and out["high"]["invalid"] >= 1
    assert "#rrggbb" in out["color"]["msg"] and out["color"]["sent"] == 0
    assert "URL http(s)" in out["url"]["msg"] and out["url"]["sent"] == 0
    assert "JSON invalide" in out["bad"]["msg"] and out["bad"]["sent"] == 0
    assert out["good"] == ["a", "b"] and out["commits"] == 1


def test_escape_abandons_the_draft_first_and_the_preview_returns_to_the_stored_value(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      const field=text(t,'title');
      field.value='Brouillon';field.dispatch('input');await t.env.advance(300);
      const mounted=t.hostCalls.filter(c=>c.mount).slice(-1)[0].mount.props.title;
      field.dispatch('keydown',{key:'Escape'});
      await t.env.flush(8);
      const reverted={value:field.value,open:t.inspector.view().open,draft:t.inspector.view().pendingDrafts,commits:t.core.st.commits,
        preview:t.hostCalls.filter(c=>c.mount).slice(-1)[0].mount.props.title};
      field.dispatch('keydown',{key:'Escape'});
      return {mounted,reverted,closed:!t.inspector.view().open,hidden:t.panel().hidden};
    """)
    assert out["mounted"] == "Brouillon", "the local preview frame shows the draft before anything is written"
    assert out["reverted"] == {"value": "Ouverture", "open": True, "draft": [], "commits": 0, "preview": "Ouverture"}
    assert out["closed"] is True and out["hidden"] is True, "a second Escape closes the panel"


def test_the_colour_stops_editor_adds_reorders_and_removes_stops_and_commits_each_change(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      const row=t.row('palette');
      const stops=()=>t.find(row,n=>n.className.split(' ').includes('jvi-stop')).length;
      const add=withText(t,row,'Ajouter une étape');
      const start=stops();
      add.click();await t.env.flush(14);
      const added={n:stops(),value:t.core.st.values.palette,commits:t.core.st.commits};
      const down=t.find(row,n=>n.attrs['aria-label']==="Descendre l'étape 1")[0];
      down.click();await t.env.flush(14);
      const reordered=t.core.st.values.palette;
      const del=t.find(row,n=>n.attrs['aria-label']==="Retirer l'étape 3")[0];
      del.click();await t.env.flush(14);
      const removed={n:stops(),value:t.core.st.values.palette};
      const hex=t.find(row,n=>n.tagName==='INPUT'&&n.type==='text')[0];
      hex.value='#112233';hex.dispatch('change');await t.env.flush(14);
      const edited=t.core.st.values.palette;
      for(let i=0;i<5;i++){withText(t,row,'Ajouter une étape').click();await t.env.flush(14)}
      return {start,added,reordered,removed,edited,final:stops(),addDisabled:withText(t,row,'Ajouter une étape').disabled,commits:t.core.st.commits,
        bar:t.find(row,n=>n.className.split(' ').includes('jvi-grad'))[0].style.background};
    """)
    assert out["start"] == 2
    assert out["added"] == {"n": 3, "value": ["#6ee7ff", "#a78bfa", "#a78bfa"], "commits": 1}
    assert out["reordered"] == ["#a78bfa", "#6ee7ff", "#a78bfa"]
    assert out["removed"] == {"n": 2, "value": ["#a78bfa", "#6ee7ff"]}
    assert out["edited"] == ["#112233", "#6ee7ff"]
    assert out["final"] == 5 and out["addDisabled"] is True, "bounded by the control's max_items"
    assert out["commits"] == 7 and out["bar"].startswith("linear-gradient(90deg,#112233")


# ------------------------------------------------------------------ erreurs typees

def test_a_refusal_from_core_is_shown_in_its_own_words_logged_and_the_widget_returns_to_the_stored_value(tmp_path):
    out = run_js(tmp_path, r"""
      const obs=[];
      const t=await boot({obs});await t.open();
      const field=text(t,'code');
      field.value='abc';field.dispatch('input');field.dispatch('change');await t.env.flush(12);
      const row=t.row('code');
      return {msg:msg(t,'code'),value:field.value,bad:row.className.split(' ').includes('is-bad'),commits:t.core.st.commits,
        revision:t.core.st.revision,warn:warns(t),obs:obs.map(a=>[a[0],a[1],a[2]]),invalid:field.attrs['aria-invalid'],
        described:field.attrs['aria-describedby']===t.find(row,n=>n.className.split(' ').includes('jvi-msg'))[0].id,
        failures:t.inspector.stats().failures};
    """)
    assert "Valeur refusée par Core" in out["msg"] and "does not match" in out["msg"], "Core's own words, not a generic label"
    assert out["value"] == "ABC" and out["bad"] is True and out["commits"] == 0 and out["revision"] == 3
    assert out["invalid"] == "true" and out["described"] is True, "the error is tied to the field for assistive technology"
    assert any("edit_refused" in line and "presentation_studio_value_refused" in line for line in out["warn"])
    assert out["obs"] and out["obs"][0][0] == "warn" and "studio_inspector_edit_refused" in out["obs"][0][2], "obsClientLog gets the failure when the page has one"
    assert out["failures"] == 1


def test_a_control_that_vanished_is_reported_and_the_list_is_rebuilt_from_core(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      t.core.defs.splice(t.core.defs.findIndex(d=>d.control_id==='glow'),1);
      const sw=t.find(t.row('glow'),n=>n.attrs.role==='switch')[0];
      sw.click();await t.env.flush(14);
      return {after:t.find(t.panel(),n=>n.attrs['data-control-id']).map(n=>n.attrs['data-control-id']),warn:warns(t),commits:t.core.st.commits};
    """)
    assert "glow" not in out["after"] and len(out["after"]) == 13
    assert any("presentation_studio_unknown_control" in line for line in out["warn"]) and out["commits"] == 0


def test_a_stale_commit_rereads_says_what_changed_and_offers_to_reapply_without_overwriting(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      await drag(t,'size',linear(1,1.7,10));
      await t.env.advance(300);                                   // the previews went through on the right basis
      t.core.external(v=>{v.size=1.2;v.accent='#ff0000'});        // the voice (or another tab) edited before the release
      await release(t,'size');await t.env.advance(50);
      const sizeRow=t.row('size');
      const message=msg(t,'size');
      const reapply=withText(t,sizeRow,'Réappliquer');
      const view=t.inspector.view();
      const state={commits:t.core.st.commits,stored:t.core.st.values.size,shown:t.find(sizeRow,n=>n.tagName==='INPUT'&&n.type==='number')[0].value,
        revision:view.revision,accent:view.controls.find(c=>c.control_id==='accent').current,stale:t.inspector.stats().staleHandled,
        drafts:view.pendingDrafts,preview:t.hostCalls.filter(c=>c.mount).slice(-1)[0].mount.props.size};
      reapply.click();await t.env.flush(14);
      return {message,reapply:reapply.textContent,state,after:{commits:t.core.st.commits,size:t.core.st.values.size,msg:msg(t,'size')},
        toast:t.env.toasts.map(x=>x.title),warn:warns(t).filter(l=>l.includes('edit_stale'))};
    """)
    assert "il n'a pas été appliqué" in out["message"] and "Taille : 1 → 1.2" in out["message"] and "Couleur d'accent" in out["message"]
    assert out["reapply"] == "Réappliquer ma valeur (1.7)"
    assert out["state"] == {"commits": 0, "stored": 1.2, "shown": "1.2", "revision": 4, "accent": "#ff0000", "stale": 1, "drafts": [],
                            "preview": 1.2}, "the other writer's value is kept and shown (widget and preview frame); nothing of ours was written"
    assert out["after"] == {"commits": 1, "size": 1.7, "msg": ""} and "Modification périmée" in out["toast"]
    assert out["warn"]


def test_a_stale_preview_tells_the_user_early_and_the_gesture_restarts_from_the_value_just_read(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      t.core.external(v=>{v.size=1.2});
      await drag(t,'size',[1.3,1.4]);
      await t.env.advance(300);
      const mid={msg:msg(t,'size'),stale:t.inspector.stats().staleHandled,commits:t.core.st.commits,revision:t.inspector.view().revision};
      await drag(t,'size',[1.5,1.6]);
      await t.env.advance(300);
      await release(t,'size');
      return {mid,final:{commits:t.core.st.commits,size:t.core.st.values.size,
        commit:t.core.st.calls.filter(c=>c.mode==='commit').map(c=>c.body.ops[0].if_current)}};
    """)
    assert "pendant votre réglage" in out["mid"]["msg"] and "Taille : 1 → 1.2" in out["mid"]["msg"] and "repart de la valeur relue" in out["mid"]["msg"]
    assert out["mid"]["stale"] == 1 and out["mid"]["commits"] == 0 and out["mid"]["revision"] == 4
    assert out["final"] == {"commits": 1, "size": 1.6, "commit": [1.2]}, "the release commits against what the user was told, not behind their back"


def test_a_scene_being_reloaded_retries_on_a_bounded_schedule_and_says_so_while_it_waits(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      t.core.st.reloadingFor=2;
      const sw=t.find(t.row('glow'),n=>n.attrs.role==='switch')[0];
      sw.click();await t.env.flush(12);
      const first={view:t.inspector.view().reloading,status:status(t)[0],commits:t.core.st.commits};
      await t.env.advance(M.RELOAD_RETRY_MS[0]);
      const second={view:t.inspector.view().reloading,commits:t.core.st.commits};
      await t.env.advance(M.RELOAD_RETRY_MS[1]);
      return {first,second,done:{view:t.inspector.view().reloading,commits:t.core.st.commits,glow:t.core.st.values.glow,status:status(t)},
        retries:t.inspector.stats().reloadRetries,total:M.RELOAD_RETRY_MS.reduce((a,b)=>a+b,0)};
    """)
    assert out["first"]["view"] == {"attempt": 1, "max": 5} and "Rechargement en cours" in out["first"]["status"]
    assert "tentative 1/5" in out["first"]["status"] and out["first"]["commits"] == 0
    assert out["second"]["view"] == {"attempt": 2, "max": 5} and out["second"]["commits"] == 0
    assert out["done"] == {"view": None, "commits": 1, "glow": True, "status": []}
    assert out["retries"] == 2 and out["total"] <= 20000, "bounded: at most 5 attempts in about 15 seconds"


def test_a_scene_that_stays_in_reload_gives_up_visibly_and_the_wait_can_be_stopped(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      t.core.st.reloadingFor=99;
      const sw=t.find(t.row('glow'),n=>n.attrs.role==='switch')[0];
      sw.click();await t.env.flush(12);
      for(const ms of M.RELOAD_RETRY_MS)await t.env.advance(ms+10);
      await t.env.flush(12);
      const gaveUp={msg:msg(t,'glow'),commits:t.core.st.commits,view:t.inspector.view().reloading,retry:!!withText(t,t.row('glow'),'Réessayer'),
        err:errors(t).filter(l=>l.includes('reload_gave_up')).length,toast:t.env.toasts.map(x=>x.title),calls:t.core.st.calls.filter(c=>c.mode==='commit').length};
      t.core.st.reloadingFor=99;
      const sw2=t.find(t.row('glow'),n=>n.attrs.role==='switch')[0];
      sw2.click();await t.env.flush(12);
      const stop=withText(t,t.panel(),"Arrêter d'attendre");
      stop.click();await t.env.advance(3000);
      return {gaveUp,stopped:{msg:msg(t,'glow'),view:t.inspector.view().reloading,commits:t.core.st.commits,
        calls:t.core.st.calls.filter(c=>c.mode==='commit').length}};
    """)
    assert "est restée en rechargement" in out["gaveUp"]["msg"] and out["gaveUp"]["commits"] == 0 and out["gaveUp"]["view"] is None
    assert out["gaveUp"]["retry"] is True and out["gaveUp"]["err"] == 1 and out["gaveUp"]["calls"] == 6, "1 try + 5 retries, then stop"
    assert "Scène en rechargement" in out["gaveUp"]["toast"]
    assert "Attente arrêtée" in out["stopped"]["msg"] and out["stopped"]["view"] is None and out["stopped"]["commits"] == 0
    assert out["stopped"]["calls"] == 7, "stopping the wait sends nothing more"


def test_a_core_that_does_not_answer_is_a_visible_state_with_a_way_out_and_never_a_silent_hang(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();
      t.hook.hang=true;
      t.inspector.open({noFocus:true});await t.env.flush(8);
      const waiting=status(t)[0];
      await t.env.advance(3000);
      const counting=status(t)[0];
      await t.env.advance(13000);await t.env.flush(10);
      const failed={status:status(t)[0],retry:!!withText(t,t.panel(),'Réessayer'),err:errors(t).filter(l=>l.includes('presentations_failed')).length,
        toast:t.env.toasts.map(x=>x.title)};
      t.hook.hang=false;
      withText(t,t.panel(),'Réessayer').click();await t.env.flush(14);
      return {waiting,counting,failed,recovered:{rows:t.find(t.panel(),n=>n.attrs['data-control-id']).length,status:status(t)}};
    """)
    assert "Chargement des présentations" in out["waiting"] and "0 s / 15 s" in out["waiting"]
    assert "3 s / 15 s" in out["counting"], "a live counter: the page is working, and for how long"
    assert "Chargement impossible" in out["failed"]["status"] and "n'a pas répondu en 15 s" in out["failed"]["status"]
    assert out["failed"]["retry"] is True and out["failed"]["err"] == 1 and "Inspecteur : présentations illisibles" in out["failed"]["toast"]
    assert out["recovered"] == {"rows": 14, "status": []}


# ------------------------------------------------------------------ annuler, rétablir

def test_undo_and_redo_go_through_the_history_routes_with_the_head_entry_and_the_keyboard(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      const undoBtn=t.find(t.panel(),n=>n.attrs['aria-label']==='Annuler la dernière modification')[0];
      const redoBtn=t.find(t.panel(),n=>n.attrs['aria-label']==='Rétablir la modification annulée')[0];
      const start={undo:undoBtn.disabled,redo:redoBtn.disabled,title:undoBtn.title};
      const sw=t.find(t.row('glow'),n=>n.attrs.role==='switch')[0];
      sw.click();await t.env.flush(14);
      const f=text(t,'title');f.value='Deux';f.dispatch('input');f.dispatch('change');await t.env.flush(14);
      const two={undo:undoBtn.disabled,history:t.inspector.view().history};
      undoBtn.click();await t.env.flush(16);
      const afterUndo={title:t.core.st.values.title,glow:t.core.st.values.glow,redo:redoBtn.disabled,
        view:t.inspector.view().controls.find(c=>c.control_id==='title').current,status:status(t)};
      const calls=t.core.st.calls.filter(c=>c.kind==='undo'||c.kind==='redo').map(c=>[c.kind,c.body]);
      redoBtn.click();await t.env.flush(16);
      const afterRedo=t.core.st.values.title;
      const zEv=sw.dispatch('keydown',{key:'z',ctrlKey:true});await t.env.flush(16);
      const byKey={title:t.core.st.values.title,prevented:zEv.defaultPrevented,stopped:zEv.stopped};
      sw.dispatch('keydown',{key:'y',ctrlKey:true});await t.env.flush(16);
      return {start,two,afterUndo,calls,afterRedo,byKey,redoByKey:t.core.st.values.title,
        counts:{undo:t.inspector.stats().undo,redo:t.inspector.stats().redo}};
    """)
    assert out["start"]["undo"] is True and "Rien à annuler" in out["start"]["title"]
    assert out["two"]["undo"] is False and out["two"]["history"] == {"undo": 2, "redo": 0}
    assert out["afterUndo"]["title"] == "Ouverture" and out["afterUndo"]["glow"] is True and out["afterUndo"]["redo"] is False
    assert out["afterUndo"]["view"] == "Ouverture" and any("Modification annulée" in line for line in out["afterUndo"]["status"])
    assert out["calls"] == [["undo", {"expected_entry_id": "psh_2"}]], "the page names the entry it showed: never a blind undo of someone else's step"
    assert out["afterRedo"] == "Deux" and out["byKey"] == {"title": "Ouverture", "prevented": True, "stopped": True}
    assert out["redoByKey"] == "Deux" and out["counts"] == {"undo": 2, "redo": 2}


def test_ctrl_z_inside_a_dirty_text_field_stays_the_browsers_and_outside_the_panel_is_never_ours(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      const sw=t.find(t.row('glow'),n=>n.attrs.role==='switch')[0];
      sw.click();await t.env.flush(14);
      const f=text(t,'title');f.value='en cours';f.dispatch('input');
      const dirty=f.dispatch('keydown',{key:'z',ctrlKey:true});await t.env.flush(10);
      const undoCallsDirty=t.core.st.calls.filter(c=>c.kind==='undo').length;
      f.dispatch('keydown',{key:'Escape'});
      const clean=f.dispatch('keydown',{key:'z',ctrlKey:true});await t.env.flush(14);
      let pageSaw=0;t.env.doc.addEventListener('keydown',()=>{pageSaw++});
      const outside=new t.El(t.env.doc,'div');t.env.doc.body.appendChild(outside);
      outside.dispatch('keydown',{key:'z',ctrlKey:true});await t.env.flush(10);
      return {dirty:{prevented:dirty.defaultPrevented,calls:undoCallsDirty},clean:{prevented:clean.defaultPrevented,glowSet:'glow' in t.core.st.values},
        outsideCalls:t.core.st.calls.filter(c=>c.kind==='undo').length,pageSaw};
    """)
    assert out["dirty"] == {"prevented": False, "calls": 0}, "a modified field keeps the browser's own text undo"
    assert out["clean"] == {"prevented": True, "glowSet": False}, "the undo removed the key the first edit had set"
    assert out["outsideCalls"] == 1 and out["pageSaw"] == 1, "Ctrl+Z outside the inspector is not ours"


def test_history_unavailable_after_a_restart_is_explained_not_silent(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot({core:{historyUnavailable:true}});await t.open();
      const undoBtn=t.find(t.panel(),n=>n.attrs['aria-label']==='Annuler la dernière modification')[0];
      const sw=t.find(t.row('glow'),n=>n.attrs.role==='switch')[0];
      const before=undoBtn.title;
      sw.dispatch('keydown',{key:'z',ctrlKey:true});await t.env.flush(16);
      return {before,status:status(t),warn:warns(t).filter(l=>l.includes('history_not_applied'))};
    """)
    assert "démarrage de Core" in out["before"]
    joined = " ".join(out["status"])
    assert "Annulation impossible" in joined and "Historique indisponible" in joined and "nothing was recorded since Core started" in joined
    assert out["warn"] and "history_unavailable" in out["warn"][0]


# ------------------------------------------------------------------ lecture, plein écran, clavier

def test_the_inspector_is_hidden_entirely_during_a_run_and_in_fullscreen_and_comes_back_closed(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      const f=text(t,'title');f.value='brouillon';f.dispatch('input');
      const before=t.inspector.view().pendingDrafts;
      t.hook.playing=true;await t.env.advance(600);
      const calls0=t.core.st.calls.length;
      const v=t.inspector.view();
      const during={hidden:t.panel().hidden,inert:t.panel().inert,open:v.open,available:v.available,reason:v.hiddenReason,
        dockDisabled:t.env.dock.disabled,dockTitle:t.env.dock.title,drafts:v.pendingDrafts,unmounted:t.hostCalls.some(c=>c.unmount)};
      await t.env.advance(12000);
      const quiet=t.core.st.calls.length===calls0;
      const refused=t.inspector.open();
      const toast=t.env.toasts.slice(-1)[0];
      t.hook.playing=false;await t.env.advance(600);
      const after={hidden:t.panel().hidden,dockDisabled:t.env.dock.disabled,open:t.inspector.view().open};
      await t.open();
      const reopened=t.find(t.panel(),n=>n.attrs['data-control-id']).length;
      t.env.doc.fullscreenElement={};t.hook.fullscreen=true;t.env.doc.dispatchDoc('fullscreenchange');
      const fs={hidden:t.panel().hidden,open:t.inspector.view().open,reason:t.inspector.view().hiddenReason,dockDisabled:t.env.dock.disabled,title:t.env.dock.title};
      return {before,during,quiet,refused,toast:toast&&toast.title,after,reopened,fs,commits:t.core.st.commits,stored:t.core.st.values.title};
    """)
    assert out["before"] == ["title"]
    d = out["during"]
    assert d["hidden"] is True and d["inert"] is True and d["open"] is False and d["available"] is False and d["reason"] == "playback"
    assert d["dockDisabled"] is True and "pendant une présentation" in d["dockTitle"] and d["drafts"] == [] and d["unmounted"] is True
    assert out["quiet"] is True, "a hidden inspector polls nothing and sends nothing"
    assert out["refused"] is False and out["toast"] == "Inspecteur indisponible"
    assert out["after"] == {"hidden": True, "dockDisabled": False, "open": False}, "it comes back available, not forced open"
    assert out["reopened"] == 14 and out["commits"] == 0 and out["stored"] == "Ouverture", "the abandoned draft was never written"
    assert out["fs"]["hidden"] is True and out["fs"]["open"] is False and out["fs"]["reason"] == "fullscreen"
    assert out["fs"]["dockDisabled"] is True and "plein écran" in out["fs"]["title"]


def test_keys_typed_in_the_inspector_never_reach_the_page_or_the_presentation(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      const seen=[];
      t.env.doc.addEventListener('keydown',(e)=>seen.push(e.key));
      const field=text(t,'title');
      const results={};
      for(const key of ['a','s','e','t','ArrowRight','ArrowLeft','Home','End',' ','p','PageDown','Backspace','Enter']){
        results[key]=field.dispatch('keydown',{key}).stopped;
      }
      results.sliderArrow=range(t,'tilt').dispatch('keydown',{key:'ArrowRight'}).stopped;
      const free={tab:field.dispatch('keydown',{key:'Tab'}).stopped,f9:field.dispatch('keydown',{key:'F9'}).stopped,
        ctrlR:field.dispatch('keydown',{key:'r',ctrlKey:true}).stopped};
      const capture=(t.env.doc.listeners.keydown||[]).filter(l=>l.cap).length;
      return {results,free,bubbled:seen,capture};
    """)
    assert all(out["results"].values()), out["results"]
    assert out["free"] == {"tab": False, "f9": False, "ctrlR": False}, "Tab, function keys and browser shortcuts pass"
    assert not {"a", "s", "ArrowRight", "Home", " "} & set(out["bubbled"]) and "Tab" in out["bubbled"]
    assert out["capture"] == 0, "the inspector installs no capture handler on the document: presentation keys are not its business"


def test_escape_closes_and_returns_the_focus_to_the_dock_button(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      const f=text(t,'title');f.focus();
      f.dispatch('keydown',{key:'Escape'});
      return {open:t.inspector.view().open,hidden:t.panel().hidden,active:t.env.doc.activeElement===t.env.dock,expanded:t.env.dock.attrs['aria-expanded']};
    """)
    assert out == {"open": False, "hidden": True, "active": True, "expanded": "false"}


# ------------------------------------------------------------------ direction artistique, texte d'auteur

def test_the_art_direction_chip_is_read_only_compares_its_own_revision_and_marks_unapplied_variables(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      const chip=()=>t.find(t.panel(),n=>n.className.split(' ').includes('jvi-da'))[0];
      const summary=chip().textContent;
      const off=t.find(chip(),n=>n.className.split(' ').includes('is-off')&&n.tagName==='LI').map(n=>n.textContent);
      const on=t.find(chip(),n=>n.tagName==='LI'&&!n.className.split(' ').includes('is-off')).map(n=>n.textContent);
      const writes=t.core.st.calls.filter(c=>c.kind==='http'&&c.method!=='GET').length;
      const arts=()=>t.core.st.calls.filter(c=>c.path&&c.path.endsWith('/art-direction')).length;
      const first=arts();
      t.core.st.art={...t.core.st.art,revision:2};
      await t.env.advance(M.POLL_MS*2+100);
      const changed={view:t.inspector.view().art,live:t.find(t.panel(),n=>n.attrs.role==='status'&&n.className.includes('jvi-sr'))[0].textContent,
        logs:t.env.logs.filter(l=>l[1].includes('art_direction_changed')).length,fetched:arts()>first};
      t.core.st.art=null;
      await t.env.advance(M.POLL_MS*2+100);
      const absent={view:t.inspector.view().art,text:chip().textContent};
      return {summary,off,on,writes,changed,absent};
    """)
    assert "Fallback - Technical dark" in out["summary"] and "générée" in out["summary"] and "repli" in out["summary"]
    assert re.search(r"contraste \d+\.\d : 1 ✓", out["summary"]), out["summary"]
    assert len(out["off"]) == 10 and all("non appliqué" in line for line in out["off"]), "the 10 variables with no delivery path are shown, not hidden"
    assert len(out["on"]) == 5 and all("appliqué" in line and "non" not in line for line in out["on"])
    assert out["writes"] == 0, "the chip reads; it can never write"
    assert out["changed"]["view"] == {"state": "ok", "revision": 2} and out["changed"]["fetched"] and out["changed"]["logs"] == 1
    assert "mise à jour" in out["changed"]["live"]
    assert out["absent"]["view"] == {"state": "absent", "revision": None} and "Aucune direction artistique" in out["absent"]["text"]


def test_author_text_never_becomes_markup(tmp_path):
    out = run_js(tmp_path, r"""
      const evil='<img src=x onerror=alert(1)>';
      const defs=DEFS.map(d=>d.control_id==='title'?{...d,label:evil,meaning:evil}:d);
      const t=await boot({core:{defs,values:{title:evil}}});await t.open();
      const imgs=t.find(t.panel(),n=>n.tagName==='IMG'||n.tagName==='SCRIPT').length;
      const field=text(t,'title');
      return {imgs,text:t.panel().textContent.includes(evil),value:field.value,tags:[...new Set(t.find(t.panel(),()=>true).map(n=>n.tagName))].sort()};
    """)
    assert out["imgs"] == 0 and out["text"] is True and out["value"] == "<img src=x onerror=alert(1)>"
    assert not {"IMG", "SCRIPT", "IFRAME"} & set(out["tags"])


def test_the_local_preview_shows_the_draft_in_a_sandboxed_preview_host_and_writes_nothing(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      const first=t.hostCalls.filter(c=>c.mount).slice(-1)[0].mount;
      await drag(t,'size',linear(1,1.5,12),16);
      const mid=t.hostCalls.filter(c=>c.mount).slice(-1)[0].mount;
      const stored=t.core.st.values.size;
      await release(t,'size');
      const end=t.hostCalls.filter(c=>c.mount).slice(-1)[0].mount;
      t.inspector.close();
      return {first:{id:first.object_id,prefab:first.prefab,size:first.props.size,accent:first.props.accent,title:first.props.title,body:first.data.body},
        mid:mid.props.size,stored,end:end.props.size,unmounted:t.hostCalls.some(c=>c.unmount===('studio-inspector-preview'))};
    """)
    assert out["first"] == {"id": "studio-inspector-preview", "prefab": {"id": "lab.dial", "version": 1}, "size": 1, "accent": "#6ee7ff",
                            "title": "Ouverture", "body": "Bonjour"}
    assert out["mid"] == 1.5 and out["stored"] == 1, "the frame moved, the document did not"
    assert out["end"] == 1.5 and out["unmounted"] is True


# ------------------------------------------------------------------ une seule porte, aucun état propre

def test_nothing_is_written_by_a_path_of_its_own_and_nothing_but_a_view_preference_is_stored(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      await drag(t,'size',linear(1,1.5,20));await release(t,'size');
      const f=text(t,'title');f.value='X';f.dispatch('input');f.dispatch('change');await t.env.flush(14);
      t.find(t.panel(),n=>n.attrs['aria-label']==='Annuler la dernière modification')[0].click();await t.env.flush(14);
      t.inspector.selectScene('pss_2');await t.env.flush(14);
      t.inspector.selectTab('visual');
      const writes=[...new Set(t.core.st.calls.filter(c=>c.kind==='http'&&c.method!=='GET').map(c=>c.method+' '+c.path.replace('/pst_1/variants/psv_1','')))].sort();
      const kinds=[...new Set(t.core.st.calls.map(c=>c.kind==='edit'?'edit:'+c.mode+':'+c.body.ops.map(o=>o.op).join(','):c.kind))];
      return {writes,kinds,storage:t.env.storage.writes,stored:Object.keys(JSON.parse(t.env.stored[M.STORAGE_KEY])),keys:Object.keys(t.env.stored)};
    """)
    assert out["writes"] == ["POST /edits", "POST /undo"], "every write is an edit, an undo or a redo: the relay's three doors, nothing else"
    assert set(out["storage"]) == {"jarvis.studio_inspector.ui"} and out["keys"] == ["jarvis.studio_inspector.ui"]
    assert sorted(out["stored"]) == ["preview", "tab"]
    assert set(out["kinds"]) <= {"http", "undo", "edit:preview:control.set", "edit:commit:control.set"}


def test_the_module_source_has_no_persistence_path_and_no_markup_injection():
    source = "\n".join(part.read_text(encoding="utf-8") for part in MODULE_PARTS)
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    code = re.sub(r"(?m)^\s*//.*$", "", code)
    assert "innerHTML" not in code and "outerHTML" not in code and "insertAdjacentHTML" not in code and "document.write" not in code
    assert "srcdoc" not in code, "the one srcdoc path stays control_center_prefab_host.js"
    assert code.count("setItem(") == 1 and "STORAGE_KEY" in code, "localStorage is only the view preference"
    assert not re.search(r"method:\s*'(PUT|DELETE|PATCH)'", code)
    assert set(re.findall(r"call\(`\$\{variantBase\(\)\}/(edits|\$\{direction\})`", code)) == {"edits", "${direction}"}
    assert "indexedDB" not in code and "sessionStorage" not in code and "document.cookie" not in code
    assert not re.search(r"\b(alert|confirm|prompt)\(", code), "in-app messages only"


# ------------------------------------------------------------------ rework (QA-1): one coalescing path for every stepping input

def test_no_input_path_commits_directly_every_stepping_path_waits_for_the_pause(tmp_path):
    """QA-1 B1: a native number field fires `change` on every arrow / wheel step; none of the continuous or stepping paths may commit at once."""

    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      const each=async(label,fn,expect)=>{
        const before=t.core.st.commits;
        for(let i=0;i<5;i++){fn(i);await t.env.advance(60)}
        const during=t.core.st.commits-before;
        await t.env.advance(M.IDLE_COMMIT_MS+100);
        return [label,during,t.core.st.commits-before,t.core.st.undo.length];
      };
      const n=number(t,'tilt'),sp=number(t,'speed');
      const results=[];
      results.push(await each('number change (arrow/spinner/wheel)',(i)=>{n.value=String(i+1);n.dispatch('change')}));
      results.push(await each('number input (typed digits)',(i)=>{sp.value=String(700+i);sp.dispatch('input')}));
      const pick=inputs(t,'accent','color')[0];
      results.push(await each('colour picker input+change',(i)=>{pick.value=['#111111','#222222','#333333','#444444','#555555'][i];pick.dispatch('input');pick.dispatch('change')}));
      const sel=t.find(t.row('easing'),x=>x.tagName==='SELECT')[0];
      results.push(await each('select change (arrow on a closed list)',(i)=>{sel.value=['linear','ease-in','ease-out','ease-in-out','spring'][i];sel.dispatch('change')}));
      const radios=t.find(t.row('layout'),x=>x.attrs.role==='radio');
      results.push(await each('radiogroup arrows',(i)=>{radios[i%3].dispatch('keydown',{key:'ArrowRight'})}));
      const stop=t.find(t.row('palette'),x=>x.tagName==='INPUT'&&x.type==='color')[0];
      results.push(await each('gradient stop picker',(i)=>{stop.value=['#101010','#202020','#303030','#404040','#505050'][i];stop.dispatch('input');stop.dispatch('change')}));
      results.push(await each('range keyboard',(i)=>{const r=range(t,'size');r.value=String(1+i*0.01);r.dispatch('input')}));
      return {results,failures:t.inspector.stats().failures,stale:t.inspector.stats().staleHandled};
    """)
    for label, during, after, _ in out["results"]:
        assert during == 0, f"{label}: committed {during} time(s) while the user was still stepping"
        assert after == 1, f"{label}: {after} commits after the pause, expected exactly 1"
    assert out["results"][-1][3] == 7 and out["failures"] == 0 and out["stale"] == 0


def test_a_draft_made_while_a_commit_is_in_flight_waits_and_rebases_on_the_value_just_written(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      const n=number(t,'tilt');
      let release;t.hook.gate=new Promise((r)=>{release=r});
      n.value='2';n.dispatch('change');
      await t.env.advance(M.IDLE_COMMIT_MS+50);                  // first commit is now in flight (held by the gate)
      n.value='3';n.dispatch('change');
      await t.env.advance(M.IDLE_COMMIT_MS+50);                  // second one queues behind it, it must not run on the old base
      const inflight=t.core.st.calls.filter(c=>c.mode==='commit').length;
      t.hook.gate=null;release();await t.env.flush(30);
      await t.env.advance(200);
      const commits=t.core.st.calls.filter(c=>c.mode==='commit').map(c=>[c.body.ops[0].value,c.body.ops[0].if_current,c.body.basis.variant_revision]);
      return {inflight,commits,tilt:t.core.st.values.tilt,stale:t.inspector.stats().staleHandled,history:t.core.st.undo.length,
        dirty:t.inspector.view().pendingDrafts};
    """)
    assert out["inflight"] == 0, "both writes are held behind the first (nothing reached Core yet)"
    assert out["commits"] == [[2, 0, 3], [3, 2, 4]], "the second commit is built from the value and revision the first one produced"
    assert out["tilt"] == 3 and out["stale"] == 0 and out["history"] == 2 and out["dirty"] == []


def test_ctrl_z_with_a_pending_slider_draft_discards_the_draft_first_and_keeps_the_redo(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      const f=text(t,'title');f.value='Un';f.dispatch('input');f.dispatch('change');await t.env.flush(14);
      const sw=t.find(t.row('glow'),n=>n.attrs.role==='switch')[0];sw.click();await t.env.flush(14);
      const r=range(t,'size');r.value='1.2';r.dispatch('input');           // a keyboard step: pending, not yet committed
      const ev=r.dispatch('keydown',{key:'z',ctrlKey:true});await t.env.flush(10);
      const first={prevented:ev.defaultPrevented,undoCalls:t.core.st.calls.filter(c=>c.kind==='undo').length,drafts:t.inspector.view().pendingDrafts,
        shown:number(t,'size').value,history:t.inspector.view().history};
      await t.env.advance(M.IDLE_COMMIT_MS+100);                           // the discarded draft must not commit later
      const later_={commits:t.core.st.commits,size:t.core.st.values.size};
      r.dispatch('keydown',{key:'z',ctrlKey:true});await t.env.flush(16);
      const second={undoCalls:t.core.st.calls.filter(c=>c.kind==='undo').length,history:t.inspector.view().history};
      // the button also discards a pending draft first, and the redo entry survives
      const r2=range(t,'tilt');r2.value='4';r2.dispatch('input');
      t.find(t.panel(),n=>n.attrs['aria-label']==='Annuler la dernière modification')[0].click();await t.env.flush(16);
      await t.env.advance(M.IDLE_COMMIT_MS+100);
      return {first,later_,second,viaButton:{history:t.inspector.view().history,tilt:t.core.st.values.tilt,commits:t.core.st.commits,undoCalls:t.core.st.calls.filter(c=>c.kind==='undo').length}};
    """)
    assert out["first"]["prevented"] is True and out["first"]["undoCalls"] == 0 and out["first"]["drafts"] == []
    assert out["first"]["shown"] == "1" and out["first"]["history"] == {"undo": 2, "redo": 0}, "the first Ctrl+Z only discards the draft"
    assert out["later_"] == {"commits": 2, "size": 1}, "and the discarded draft never commits afterwards"
    assert out["second"] == {"undoCalls": 1, "history": {"undo": 1, "redo": 1}}
    assert out["viaButton"]["undoCalls"] == 2 and out["viaButton"]["commits"] == 2, "the draft did not commit after the undo"
    assert out["viaButton"]["history"] == {"undo": 0, "redo": 2}, "the redo entries are intact"


def test_the_default_run_detection_reads_the_player_and_its_event_hides_the_panel_at_once(tmp_path):
    """QA-1 mutation 4: `playing()` returning false survived every node test; here the real default implementation is driven."""

    out = run_js(tmp_path, r"""
      const state={running:false,phase:'idle'};
      globalThis.JarvisStudioPlayer={view:()=>state,refresh:async()=>state};
      const t=await boot({defaultPlaying:true});await t.open();
      const before={hidden:t.panel().hidden,open:t.inspector.view().open};
      state.running=true;state.phase='playing';
      t.env.win.dispatchEvent(M.PLAYBACK_EVENT);                        // the player announces the run: no waiting for a timer tick
      const at_once={hidden:t.panel().hidden,inert:t.panel().inert,open:t.inspector.view().open,reason:t.inspector.view().hiddenReason,dock:t.env.dock.disabled};
      state.running=false;state.phase='stopped';
      t.env.win.dispatchEvent(M.PLAYBACK_EVENT);
      const after={dock:t.env.dock.disabled,available:t.inspector.view().available};
      // a stopped / ended state never hides it; a paused run does
      state.running=true;state.phase='paused';await t.env.advance(600);
      const paused=t.panel().hidden;
      delete globalThis.JarvisStudioPlayer;
      return {before,at_once,after,paused};
    """)
    assert out["before"] == {"hidden": False, "open": True}
    assert out["at_once"] == {"hidden": True, "inert": True, "open": False, "reason": "playback", "dock": True}
    assert out["after"] == {"dock": False, "available": True} and out["paused"] is True


def test_a_short_viewport_starts_with_the_preview_folded_unless_the_user_chose_otherwise(tmp_path):
    out = run_js(tmp_path, r"""
      const short=await boot();short.env.win.innerHeight=600;await short.open();
      const tall=await boot();tall.env.win.innerHeight=900;await tall.open();
      const chosen=await boot();chosen.env.win.innerHeight=600;chosen.env.storage.setItem(M.STORAGE_KEY,JSON.stringify({tab:'content',preview:true}));await chosen.open();
      const det=(t)=>t.panel().querySelector('.jvi-stage').open;
      return {short:det(short),tall:det(tall),chosen:det(chosen)};
    """)
    assert out == {"short": False, "tall": True, "chosen": True}


# ------------------------------------------------------------------ merge with Slice 06 QA-2: reload state, no spurious stale

def test_a_revision_bump_that_touched_no_control_is_rebased_silently_and_applied(tmp_path):
    """A source reload (or any write elsewhere) moves the variant revision; the next inspector commit must not be reported as a conflict."""

    out = run_js(tmp_path, r"""
      const t=await boot();await t.open();
      t.core.external(()=>{});                                    // revision 3 -> 4, no value changed (what a source reload does to the basis)
      const sw=t.find(t.row('glow'),n=>n.attrs.role==='switch')[0];
      sw.click();await t.env.flush(30);
      return {commits:t.core.st.commits,glow:t.core.st.values.glow,msg:msg(t,'glow'),toasts:t.env.toasts.map(x=>x.title),
        bases:t.core.st.calls.filter(c=>c.mode==='commit').map(c=>c.body.basis.variant_revision),log:t.env.logs.filter(l=>l[1].includes('stale_rebased')).length,
        warn:warns(t).filter(l=>l.includes('edit_stale'))};
    """)
    assert out["commits"] == 1 and out["glow"] is True and out["msg"] == "" and out["toasts"] == [] and out["warn"] == []
    assert out["bases"] == [3, 4] and out["log"] == 1, "one stale answer, then the same commit on the re-read base"


def test_the_reload_state_of_the_scene_is_shown_read_only_with_unfit_values_and_version_counts(tmp_path):
    out = run_js(tmp_path, r"""
      const t=await boot();
      t.core.st.versions={pss_1:{live:3,archived:1,newest:4}};
      t.core.st.reloads=[{scene_id:'pss_1',variant_id:'psv_1',status:'reloaded_state_reset',source_revision:2,reset:{unfit:['props.size','data.body'],props:[],data:[]}}];
      await t.open();
      const banner=t.find(t.panel(),n=>n.className.split(' ').includes('jvi-status')&&!n.hidden).map(n=>n.textContent);
      const line=t.find(t.panel(),n=>n.className.split(' ').includes('jvi-default')&&n.textContent.startsWith('Source du modèle'))[0].textContent;
      // a new reload row (another actor) makes the page re-read the scene at once
      const reads=()=>t.core.st.calls.filter(c=>c.path&&c.path.endsWith('/controls')).length;
      const before=reads();
      t.core.external(v=>{v.size=1.4});
      t.core.st.reloads=[...t.core.st.reloads,{scene_id:'pss_1',variant_id:'psv_1',status:'degraded',source_revision:3,reset:null}];
      await t.env.advance(M.POLL_MS+100);
      const after={reads:reads()-before,size:t.inspector.view().controls.find(c=>c.control_id==='size').current,
        banner:t.find(t.panel(),n=>n.className.split(' ').includes('jvi-status')&&!n.hidden).map(n=>n.textContent).join('|')};
      const writes=t.core.st.calls.filter(c=>c.kind==='http'&&c.method!=='GET').length;
      return {banner,line,after,writes};
    """)
    assert "Valeurs à corriger après le rechargement" in out["banner"][0] and "props.size, data.body" in out["banner"][0]
    assert out["line"] == "Source du modèle : 3 versions (+ 1 archivée) · dernier rechargement : rechargée, valeurs remises à zéro"
    assert out["after"]["reads"] >= 1 and out["after"]["size"] == 1.4, "a new reload row triggers an immediate re-read"
    assert "Source dégradée" in out["after"]["banner"] and out["writes"] == 0, "the reload state is read only"
