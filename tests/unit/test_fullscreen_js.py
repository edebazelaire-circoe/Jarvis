"""Le plein écran de surface **dans la page**, par node (studio de présentation, Slice 03).

Les modules testés sont les vrais (`control_center_fullscreen.js`) ; seuls le DOM, l'horloge et le réseau sont des
doubles (`_fullscreen_js_bench.cjs`), et le double de `requestFullscreen` obéit à la règle du navigateur : sans
geste utilisateur, la promesse est rejetée (`TypeError: Permissions check failed`) ; avec geste, `fullscreenchange`
part AVANT la résolution. La preuve dans un vrai Chrome est `test_fullscreen_browser.py`.

Ce que ce fichier épingle :

- **une commande arme, elle n'entre pas** : invite visible (alertdialog, bouton focalisé, compte à rebours qui
  descend, Annuler), `fullscreenElement` toujours nul ; **le clic entre**, et seulement l'événement du navigateur le dit ;
- **un clic sans activation échoue proprement** (invite conservée, phrase visible, aucune entrée déclarée) ;
- **échéance, annulation, refus, indisponibilité, cible absente, autre surface déjà plein écran** : chacun un état
  nommé, visible (toast / ligne d'erreur), journalisé et rapporté au serveur, jamais un recouvrement présenté comme
  un plein écran ;
- **sortie (Échap comprise) : focus et marqueurs restaurés**, touches détachées ;
- **touches de navigation lues sur l'hôte** (le cadre n'en relaie aucune), sans voler Échap ni les combinaisons ;
- **écran voulu au mieux** : indisponible / refusé / absent = repli sur l'écran courant, dit ;
- **parité** de la table de transitions et des codes avec le domaine Python ;
- **canal** : reçu postal, panne de reçu et de poll visibles, boucle arrêtée onglet caché.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.domain import surface_fullscreen as fs

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "jarvis" / "runtime" / "control_center_fullscreen.js"
BENCH = Path(__file__).parent / "_fullscreen_js_bench.cjs"


def _node(tmp_path: Path, body: str, data: object = None) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    index = len(list(tmp_path.glob("fs-js-*.cjs")))
    script = tmp_path / f"fs-js-{index}.cjs"
    script.write_text(
        f"const {{makeEnv}}=require({json.dumps(str(BENCH))});\n"
        f"const D={json.dumps(data)};\n"
        "(async()=>{\n" + body + "\n})().then(v=>console.log(JSON.stringify(v)),"
        "e=>{console.error(e&&e.stack||e);process.exit(1)});\n",
        encoding="utf-8",
    )
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=120,
                          env={**os.environ, "JARVIS_FULLSCREEN_JS": str(MODULE)})
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


#: Une page de scène minimale avec une fenêtre prefab, un contrôleur branché sur `fullscreenchange`.
SETUP = """
const env=makeEnv();const {doc,win}=env;
const w=env.addWindow('obj_1','Diapo un');const other=env.addWindow('obj_2','Diapo deux');
const trigger=doc.createElement('button');trigger.id='trigger';doc.body.appendChild(trigger);trigger.focus();
const c=env.controller();env.wire(c);
const cmd=(extra)=>Object.assign({id:'A'.repeat(32),action:'enter',object_id:'obj_1',display:'current',keys:'host',arm_s:30},extra||{});
"""


# ------------------------------------------------------------------ parité


def test_the_transition_table_and_the_codes_mirror_the_python_domain(tmp_path):
    js = _node(tmp_path, "const FS=makeEnv().FS;return {t:FS.TRANSITIONS,s:FS.STATES,e:FS.EVENTS,a:FS.ACTIONS,"
                         "d:FS.DISPLAY_SELECTIONS,c:Object.values(FS.PAGE_CODES),n:FS.POLL_WAIT_S,arm:FS.DEFAULT_ARM_S};")
    assert {tuple(key.split("|")): value for key, value in js["t"].items()} == fs.TRANSITIONS
    assert js["s"] == list(fs.STATES) and js["e"] == list(fs.EVENTS) and js["a"] == list(fs.ACTIONS)
    assert js["d"] == list(fs.DISPLAY_SELECTIONS)
    assert sorted(js["c"]) == sorted(fs.PAGE_CODES)
    assert js["n"] == fs.MAX_POLL_WAIT_S and js["arm"] == fs.ARM_DEFAULT_S


def test_the_frame_is_never_touched_by_this_module():
    """R4 : jamais `sandbox`, `allow` ni CSP du cadre ; le plein écran vise l'hôte."""

    source = re.sub(r"/\*.*?\*/", "", MODULE.read_text(encoding="utf-8"), flags=re.S)   # le code, pas les commentaires
    for forbidden in ("'sandbox'", '"sandbox"', "allowfullscreen", "allow-", "srcdoc", "Permissions-Policy", ".contentWindow",
                      "postMessage"):
        assert forbidden not in source, forbidden
    # Le CSS de mouvement n'existe que hors « mouvement réduit ».
    style = source[source.index("const STYLE=`"):source.index("`;", source.index("const STYLE=`"))]
    assert "transition" in style and style.index("prefers-reduced-motion:no-preference") < style.index("transition")
    assert style.count("transition") == 1


# ------------------------------------------------------------------ armer, cliquer, entrer


def test_a_command_arms_a_visible_prompt_and_does_not_enter(tmp_path):
    result = _node(tmp_path, SETUP + """
      const receipt=await c.handle(cmd());
      const box=env.prompt();const go=env.byClass(box,'jvfs-go'),count=env.byClass(box,'jvfs-count');
      const before=count.textContent;
      await env.advance(10000);
      return {receipt,role:box.getAttribute('role'),labelled:box.getAttribute('aria-labelledby'),
        title:env.byClass(box,'jvfs-desc').textContent,goText:go.textContent,cancelText:env.byClass(box,'jvfs-cancel').textContent,
        focus:doc.activeElement===go,before,after:count.textContent,fullscreen:doc.fullscreenElement,
        state:c.state().state,armed:c.state().armed.id,reports:env.reports(),bar:env.byClass(box,'jvfs-bar').children[0].style.transform};
    """)
    assert result["receipt"] == {"state": "needs_gesture", "object_id": "obj_1", "display_selection": "not_requested"}
    assert result["role"] == "alertdialog" and result["labelled"].endswith("Title")
    assert "Diapo un" in result["title"] and "Échap" in result["title"]
    assert (result["goText"], result["cancelText"]) == ("Passer en plein écran", "Annuler")
    assert result["focus"] is True
    assert (result["before"], result["after"]) == ("30 s", "20 s")            # le compte à rebours descend
    assert result["bar"] == "scaleX(0.6666666666666666)" or result["bar"].startswith("scaleX(0.66")
    assert result["fullscreen"] is None and result["state"] == "needs_gesture" and result["armed"] == "AAAAAAAA"
    assert result["reports"] == []                                             # rien d'« entré » n'est rapporté


def test_the_click_enters_inside_the_gesture_and_only_the_browser_event_says_so(tmp_path):
    result = _node(tmp_path, SETUP + """
      await c.handle(cmd());
      const go=env.byClass(env.prompt(),'jvfs-go');
      go.click();await env.tick();
      return {fullscreen:doc.fullscreenElement&&doc.fullscreenElement.dataset.objectId,state:c.state().state,
        mark:w.getAttribute('data-jv-fullscreen'),prompt:env.prompt(),calls:doc.fs.calls.map(x=>x.options),
        reports:env.reports(),focusOnHost:doc.activeElement===w,toasts:doc.toasts};
    """)
    assert result["fullscreen"] == "obj_1" and result["state"] == "entered" and result["mark"] == "1"
    assert result["prompt"] is None                                       # l'invite part quand le navigateur a dit oui
    assert result["calls"] == [{"navigationUI": "hide"}]                   # l'hôte, sans écran imposé
    assert result["reports"] == [{"state": "entered", "display_selection": "not_requested", "id": "AAAAAAAA",
                                  "object_id": "obj_1"}]
    assert result["focusOnHost"] is True and result["toasts"] == []


def test_a_click_without_activation_fails_cleanly_and_keeps_the_prompt(tmp_path):
    result = _node(tmp_path, SETUP + """
      await c.handle(cmd());
      const go=env.byClass(env.prompt(),'jvfs-go');
      doc.activation=false;                         // l'activation a expiré avant l'appel
      go.dispatch('click');await env.tick();
      const err=env.byClass(env.prompt(),'jvfs-error');
      return {fullscreen:doc.fullscreenElement,state:c.state().state,errorShown:err.hidden===false,error:err.textContent,
        prompt:!!env.prompt(),reports:env.reports(),warn:env.logs.filter(l=>l.event==='fullscreen.needs_gesture').length};
    """)
    assert result["fullscreen"] is None and result["state"] == "needs_gesture" and result["prompt"] is True
    assert result["errorShown"] is True and "cliquez de nouveau" in result["error"]
    assert result["reports"] == [] and result["warn"] == 1


def test_a_browser_refusal_is_shown_logged_and_reported_with_its_own_words(tmp_path):
    result = _node(tmp_path, SETUP + """
      doc.fs.mode='deny';doc.fs.message='Disallowed by permissions policy';
      await c.handle(cmd());
      env.byClass(env.prompt(),'jvfs-go').click();await env.tick();
      return {state:c.state().state,prompt:env.prompt(),toasts:doc.toasts,reports:env.reports(),
        logged:env.logs.filter(l=>l.event==='fullscreen.denied'),focusBack:doc.activeElement===trigger};
    """)
    assert result["state"] == "refused" and result["prompt"] is None
    assert result["toasts"][0]["kind"] == "bad" and "permissions policy" in result["toasts"][0]["sub"]
    assert result["reports"] == [{"state": "refused", "display_selection": "not_requested", "id": "AAAAAAAA",
                                  "code": fs.DENIED, "reason": "Disallowed by permissions policy"}]
    assert result["logged"] and result["logged"][0]["level"] == "warn" and result["focusBack"] is True


def test_the_arm_deadline_removes_the_prompt_and_says_how_long_it_waited(tmp_path):
    result = _node(tmp_path, SETUP + """
      await c.handle(cmd({arm_s:5}));
      await env.advance(4900);const stillThere=!!env.prompt();
      await env.advance(200);
      return {stillThere,prompt:env.prompt(),state:c.state().state,toasts:doc.toasts,reports:env.reports(),
        focusBack:doc.activeElement===trigger,armed:c.state().armed,fullscreen:doc.fullscreenElement};
    """)
    assert result["stillThere"] is True and result["prompt"] is None
    assert result["state"] == "expired" and result["armed"] is None and result["fullscreen"] is None
    assert result["toasts"][0]["kind"] == "warn" and "5 s" in result["toasts"][0]["sub"]
    assert result["reports"] == [{"state": "expired", "display_selection": "not_requested", "id": "AAAAAAAA",
                                  "code": fs.ARM_EXPIRED,
                                  "reason": "Personne n'a cliqué dans les 5 s : l'invite a été retirée, rien n'a changé."}]
    assert result["focusBack"] is True


def test_cancel_and_escape_in_the_prompt_withdraw_the_request_and_restore_focus(tmp_path):
    result = _node(tmp_path, SETUP + """
      await c.handle(cmd());
      env.byClass(env.prompt(),'jvfs-cancel').click();await env.tick();
      const first={state:c.state().state,prompt:env.prompt(),focus:doc.activeElement===trigger};
      await c.handle(cmd({id:'B'.repeat(32)}));
      env.prompt().dispatch('keydown',{key:'Escape'});await env.tick();
      return {first,second:{state:c.state().state,prompt:env.prompt()},reports:env.reports(),stats:c.stats()};
    """)
    assert result["first"] == {"state": "exited", "prompt": None, "focus": True}
    assert result["second"] == {"state": "exited", "prompt": None}
    assert [r["code"] for r in result["reports"]] == [fs.CANCELLED, fs.CANCELLED]
    assert [r["state"] for r in result["reports"]] == ["exited", "exited"]
    assert result["stats"]["cancelled"] == 2


def test_a_second_command_replaces_the_prompt_instead_of_stacking_two(tmp_path):
    result = _node(tmp_path, SETUP + """
      await c.handle(cmd());await c.handle(cmd({id:'C'.repeat(32),object_id:'obj_2'}));
      const prompts=doc.body.children.filter(n=>n.id===env.FS.PROMPT_ID).length;
      env.byClass(env.prompt(),'jvfs-go').click();await env.tick();
      return {prompts,which:doc.fullscreenElement.dataset.objectId,reportId:env.reports()[0].id};
    """)
    assert result == {"prompts": 1, "which": "obj_2", "reportId": "CCCCCCCC"}


# ------------------------------------------------------------------ états honnêtes sans entrée


def test_unsupported_is_an_explicit_state_never_a_css_overlay(tmp_path):
    result = _node(tmp_path, """
      const env=makeEnv({fullscreenEnabled:false});const {doc}=env;env.addWindow('obj_1');
      const c=env.controller();env.wire(c);
      const receipt=await c.handle({id:'A'.repeat(32),action:'enter',object_id:'obj_1'});
      const local=await c.enter({object_id:'obj_1'});
      return {receipt,local,prompt:env.prompt(),state:c.state(),toasts:doc.toasts.length,calls:doc.fs.calls.length,
        reports:env.reports()};
    """)
    assert result["receipt"]["state"] == "unsupported" and result["receipt"]["code"] == fs.UNSUPPORTED
    assert "interdit" in result["receipt"]["reason"]
    assert result["local"]["state"] == "unsupported"
    assert result["prompt"] is None and result["state"]["supported"] is False and result["calls"] == 0
    assert result["toasts"] == 2 and result["reports"][0]["code"] == fs.UNSUPPORTED


def test_a_missing_target_and_a_busy_browser_are_refusals_with_codes(tmp_path):
    result = _node(tmp_path, SETUP + """
      const missing=await c.handle(cmd({object_id:'gone'}));
      doc.fullscreenElement=other;                       // une autre surface est déjà plein écran
      const busy=await c.handle(cmd());
      const same=await c.handle(cmd({object_id:'obj_2'}));
      return {missing,busy,same,prompt:env.prompt(),toasts:doc.toasts.map(t=>t.kind)};
    """)
    assert result["missing"]["state"] == "refused" and result["missing"]["code"] == fs.TARGET_MISSING
    assert result["busy"]["state"] == "refused" and result["busy"]["code"] == fs.OTHER_ENTERED
    assert result["same"]["state"] == "entered"                                   # déjà vrai : dit tel quel
    assert result["prompt"] is None and result["toasts"] == ["warn"]


def test_the_scene_root_is_a_valid_target_when_no_object_is_named(tmp_path):
    result = _node(tmp_path, SETUP + """
      const receipt=await c.handle(cmd({object_id:null}));
      env.byClass(env.prompt(),'jvfs-go').click();await env.tick();
      return {receipt,fullscreen:doc.fullscreenElement.id,reports:env.reports()};
    """)
    assert result["receipt"]["state"] == "needs_gesture" and result["fullscreen"] == "sceneLayer"
    assert result["reports"][0]["state"] == "entered" and "object_id" not in result["reports"][0]


def test_a_target_removed_while_the_prompt_is_up_is_a_named_refusal(tmp_path):
    result = _node(tmp_path, SETUP + """
      await c.handle(cmd());
      env.scene.removeChild(w);                          // la fenêtre est archivée pendant l'attente
      env.byClass(env.prompt(),'jvfs-go').click();await env.tick();
      return {state:c.state().state,prompt:env.prompt(),reports:env.reports(),calls:doc.fs.calls.length,toasts:doc.toasts};
    """)
    assert result["state"] == "refused" and result["prompt"] is None and result["calls"] == 0
    assert result["reports"][0]["code"] == fs.TARGET_MISSING and result["toasts"][0]["kind"] == "warn"


def test_an_unexpected_failure_while_entering_is_visible_and_released(tmp_path):
    result = _node(tmp_path, SETUP + """
      doc.fs.mode='error';
      await c.handle(cmd());
      env.byClass(env.prompt(),'jvfs-go').click();await env.tick();
      return {state:c.state().state,prompt:env.prompt(),toasts:doc.toasts,reports:env.reports()};
    """)
    # Une erreur autre qu'un refus de geste est un refus du navigateur avec ses mots, pas un gel.
    assert result["state"] == "refused" and result["prompt"] is None
    assert result["toasts"][0]["kind"] == "bad" and "boom" in result["toasts"][0]["sub"]
    assert result["reports"][0]["code"] == fs.DENIED


# ------------------------------------------------------------------ sortie et restauration


def test_leaving_by_escape_restores_focus_marks_and_key_listeners(tmp_path):
    result = _node(tmp_path, SETUP + """
      await c.handle(cmd());env.byClass(env.prompt(),'jvfs-go').click();await env.tick();
      const during={mark:w.getAttribute('data-jv-fullscreen'),focus:doc.activeElement===w,
        keyListeners:(w.listeners.keydown||[]).length,blur:(win.listeners.blur||[]).length};
      // Échap : le navigateur sort tout seul, le code d'application ne tourne pas.
      doc.fullscreenElement=null;doc.dispatchDoc('fullscreenchange');await env.tick();
      const heard=[];c.onNavigate(e=>heard.push(e));
      const key=w.dispatch('keydown',{key:'ArrowRight'});
      return {during,after:{mark:w.getAttribute('data-jv-fullscreen'),focus:doc.activeElement===trigger,
        keyListeners:(w.listeners.keydown||[]).length,blur:(win.listeners.blur||[]).length,state:c.state().state,
        heard,prevented:key.defaultPrevented},reports:env.reports().map(r=>r.state),
        tab:w.getAttribute('tabindex')};
    """)
    assert result["during"] == {"mark": "1", "focus": True, "keyListeners": 1, "blur": 1}
    assert result["after"] == {"mark": None, "focus": True, "keyListeners": 0, "blur": 0, "state": "exited",
                               "heard": [], "prevented": False}
    assert result["reports"] == ["entered", "exited"] and result["tab"] == "-1"


def test_the_exit_command_cancels_an_armed_request_or_exits_through_the_browser(tmp_path):
    result = _node(tmp_path, SETUP + """
      await c.handle(cmd());
      const armedExit=await c.handle({id:'D'.repeat(32),action:'exit'});
      const promptGone=env.prompt()===null;
      await c.handle(cmd());env.byClass(env.prompt(),'jvfs-go').click();await env.tick();
      const entered=c.state().state;
      const exit=await c.handle({id:'E'.repeat(32),action:'exit'});
      const idle=await c.handle({id:'F'.repeat(32),action:'exit'});
      return {armedExit,promptGone,entered,exit,idle,state:c.state().state,fullscreen:doc.fullscreenElement};
    """)
    assert result["armedExit"]["state"] == "exited" and result["armedExit"]["code"] == fs.CANCELLED
    assert result["promptGone"] is True and result["entered"] == "entered"
    assert result["exit"]["state"] == "exited" and result["idle"]["state"] == "exited"
    assert result["state"] == "exited" and result["fullscreen"] is None


def test_an_exit_that_fails_is_reported_as_such_and_says_escape_still_works(tmp_path):
    result = _node(tmp_path, SETUP + """
      await c.handle(cmd());env.byClass(env.prompt(),'jvfs-go').click();await env.tick();
      doc.exitError='NotAllowed';
      const failed=await c.handle({id:'E'.repeat(32),action:'exit'});
      doc.exitError=null;doc.stickyFullscreen=true;
      const stuck=await c.handle({id:'F'.repeat(32),action:'exit'});
      return {failed,stuck,state:c.state().state,toast:doc.toasts[0]};
    """)
    assert result["failed"]["state"] == "refused" and result["failed"]["code"] == fs.EXIT_FAILED
    assert result["stuck"]["state"] == "refused" and result["state"] == "entered"
    assert result["toast"]["kind"] == "bad" and "Échap" in result["toast"]["sub"]


def test_a_foreign_fullscreen_element_is_ignored_not_adopted(tmp_path):
    result = _node(tmp_path, SETUP + """
      const video=doc.createElement('video');doc.body.appendChild(video);
      doc.fullscreenElement=video;doc.dispatchDoc('fullscreenchange');
      return {state:c.state().state,reports:env.reports(),logged:env.logs.some(l=>l.event==='fullscreen.foreign_element')};
    """)
    assert result == {"state": "exited", "reports": [], "logged": True}


# ------------------------------------------------------------------ clavier hôte


def test_navigation_keys_are_read_on_the_host_and_do_not_leak_to_the_scene(tmp_path):
    result = _node(tmp_path, SETUP + """
      const sceneKeys=[];env.scene.addEventListener('keydown',e=>sceneKeys.push(e.key));   // la navigation de la scène
      await c.handle(cmd());env.byClass(env.prompt(),'jvfs-go').click();await env.tick();
      const heard=[];c.onNavigate(e=>heard.push(e.action+':'+e.key+':'+e.objectId));
      const out={};
      for(const key of ['ArrowRight','ArrowLeft','PageDown','PageUp',' ','Home','End','Escape','a','Enter']){
        const ev=w.dispatch('keydown',{key});out[key]=ev.defaultPrevented;
      }
      const ctrl=w.dispatch('keydown',{key:'ArrowRight',ctrlKey:true});
      const alt=w.dispatch('keydown',{key:'ArrowRight',altKey:true});
      return {heard,prevented:out,ctrl:ctrl.defaultPrevented,alt:alt.defaultPrevented,sceneKeys,keyStats:c.stats().keys};
    """)
    assert result["heard"] == ["next:ArrowRight:obj_1", "previous:ArrowLeft:obj_1", "next:PageDown:obj_1",
                               "previous:PageUp:obj_1", "next: :obj_1", "first:Home:obj_1", "last:End:obj_1"]
    assert [key for key, taken in result["prevented"].items() if taken] == [
        "ArrowRight", "ArrowLeft", "PageDown", "PageUp", " ", "Home", "End"]
    assert result["ctrl"] is False and result["alt"] is False        # Échap et combinaisons restent au navigateur
    assert result["sceneKeys"] == ["Escape", "a", "Enter", "ArrowRight", "ArrowRight"]   # seules les non-prises passent
    assert result["keyStats"] == 7


def test_a_click_inside_the_frame_gives_the_keys_back_to_the_host_unless_keys_is_none(tmp_path):
    result = _node(tmp_path, SETUP + """
      const frame=env.byClass(w,'sc-prefab-frame');
      await c.handle(cmd());env.byClass(env.prompt(),'jvfs-go').click();await env.tick();
      frame.focus();win.fire('blur');await env.advance(1);
      const host=doc.activeElement===w;
      // Option « keys: none » : le prefab garde son focus (champ de saisie, etc.).
      doc.fullscreenElement=null;doc.dispatchDoc('fullscreenchange');
      await c.handle(cmd({keys:'none'}));env.byClass(env.prompt(),'jvfs-go').click();await env.tick();
      frame.focus();win.fire('blur');await env.advance(1);
      return {host,none:doc.activeElement===frame,keyListeners:(w.listeners.keydown||[]).length};
    """)
    assert result == {"host": True, "none": True, "keyListeners": 0}


# ------------------------------------------------------------------ choix de l'écran


DISPLAY_BODY = SETUP + """
const screens=[{label:'A',isPrimary:true,left:0,top:0},{label:'B',isPrimary:false,left:1920,top:0},{label:'C',isPrimary:false,left:3840,top:0}];
const details={screens,currentScreen:screens[1]};
const run=async(display,getDetails)=>{
  if(getDetails)win.getScreenDetails=getDetails;else delete win.getScreenDetails;
  doc.fs.calls.length=0;doc.fullscreenElement=null;doc.dispatchDoc('fullscreenchange');
  await c.handle(cmd({display}));env.byClass(env.prompt(),'jvfs-go').click();await env.tick();await env.tick();
  const call=doc.fs.calls[0];
  return {entered:!!doc.fullscreenElement,screen:call&&call.options.screen?call.options.screen.label:null,
    selection:c.state().displaySelection,report:env.reports().slice(-1)[0].display_selection};
};
"""


def test_display_selection_is_best_effort_and_falls_back_to_the_current_display_saying_so(tmp_path):
    result = _node(tmp_path, DISPLAY_BODY + """
      const out={};
      out.current=await run('current',null);
      out.unavailable=await run('primary',null);
      out.primary=await run('primary',async()=>details);
      out.other=await run('other',async()=>details);
      out.index=await run(2,async()=>details);
      out.missing=await run(7,async()=>details);
      out.denied=await run('primary',async()=>{throw Object.assign(new Error('x'),{name:'NotAllowedError'})});
      out.broken=await run('primary',async()=>{throw new Error('Window Management API crashed')});
      out.logs=env.logs.filter(l=>l.event.startsWith('fullscreen.display_')).map(l=>l.event);
      return out;
    """)
    base = {"entered": True}
    assert result["current"] == {**base, "screen": None, "selection": "not_requested", "report": "not_requested"}
    assert result["unavailable"] == {**base, "screen": None, "selection": "unavailable", "report": "unavailable"}
    assert result["primary"] == {**base, "screen": "A", "selection": "granted", "report": "granted"}
    assert result["other"] == {**base, "screen": "A", "selection": "granted", "report": "granted"}   # l'écran courant est B
    assert result["index"] == {**base, "screen": "C", "selection": "granted", "report": "granted"}
    assert result["missing"] == {**base, "screen": None, "selection": "missing", "report": "missing"}
    assert result["denied"] == {**base, "screen": None, "selection": "denied", "report": "denied"}
    assert result["broken"] == {**base, "screen": None, "selection": "unavailable", "report": "unavailable"}
    assert result["logs"] == ["fullscreen.display_missing", "fullscreen.display_unavailable", "fullscreen.display_unavailable"]


def test_a_display_permission_prompt_that_eats_the_activation_asks_for_a_second_click(tmp_path):
    result = _node(tmp_path, SETUP + """
      win.navigator.permissions.query=async()=>({state:'prompt'});
      let asked=false;
      win.getScreenDetails=async()=>{if(!asked){asked=true;doc.activation=false}return {screens:[{label:'A',isPrimary:true,left:0,top:0}],currentScreen:{left:9,top:9}}};
      await c.handle(cmd({display:'primary'}));
      env.byClass(env.prompt(),'jvfs-go').click();await env.tick();await env.tick();
      const err=env.byClass(env.prompt(),'jvfs-error');
      const first={entered:!!doc.fullscreenElement,state:c.state().state,error:err.textContent,shown:err.hidden===false};
      win.navigator.permissions.query=async()=>({state:'granted'});
      env.byClass(env.prompt(),'jvfs-go').click();await env.tick();await env.tick();
      return {first,entered:!!doc.fullscreenElement,state:c.state().state};
    """)
    assert result["first"]["entered"] is False and result["first"]["state"] == "needs_gesture"
    assert result["first"]["shown"] is True and "cliquez de nouveau" in result["first"]["error"]
    assert result["entered"] is True and result["state"] == "entered"


# ------------------------------------------------------------------ entrée locale


def test_a_local_enter_without_a_gesture_arms_instead_of_failing_silently(tmp_path):
    result = _node(tmp_path, SETUP + """
      win.navigator.userActivation.isActive=false;
      const cold=await c.enter({object_id:'obj_1'});
      const armed={prompt:!!env.prompt(),state:c.state().state,calls:doc.fs.calls.length};
      c.cancel();
      win.navigator.userActivation.isActive=true;doc.activation=true;
      const warm=await c.enter({object_id:'obj_1'});
      return {cold,armed,warm,fullscreen:doc.fullscreenElement&&doc.fullscreenElement.dataset.objectId,
        again:await c.enter({object_id:'obj_1'}),other:await c.enter({object_id:'obj_2'}),
        reports:env.reports().map(r=>r.state)};
    """)
    assert result["cold"]["state"] == "needs_gesture" and result["cold"]["code"] == fs.NEEDS_GESTURE
    assert result["armed"] == {"prompt": True, "state": "needs_gesture", "calls": 0}   # aucun appel sans geste
    assert result["warm"]["state"] == "entered" and result["fullscreen"] == "obj_1"
    assert result["again"]["state"] == "entered"
    assert result["other"]["state"] == "refused" and result["other"]["code"] == fs.OTHER_ENTERED
    assert result["reports"] == ["exited", "entered"]                                    # annulation, puis entrée


def test_a_local_enter_without_the_activation_api_still_fails_cleanly(tmp_path):
    result = _node(tmp_path, SETUP + """
      delete win.navigator.userActivation;       // navigateur sans navigator.userActivation
      doc.activation=false;
      const receipt=await c.enter({object_id:'obj_1'});
      return {receipt,prompt:!!env.prompt(),fullscreen:doc.fullscreenElement,state:c.state().state};
    """)
    assert result["receipt"]["state"] == "needs_gesture" and result["prompt"] is True and result["fullscreen"] is None


# ------------------------------------------------------------------ canal


CHANNEL = """
const env=makeEnv();const FS=env.FS;
const received=[];
const controller={async handle(cmd){received.push(cmd);if(env.boom)throw new Error('handler exploded');return env.receipt||{state:'needs_gesture',object_id:'obj_1'}}};
const sleeps=[];
const channel=FS.createCommandChannel({controller,request:env.request,log:(l,e,d)=>env.logs.push({l,e,d}),
  sleep:async ms=>{sleeps.push(ms);if(sleeps.length>3)channel.setVisible(false)},random:()=>0.5});
"""


def test_the_channel_hands_the_command_to_the_controller_and_posts_the_receipt(tmp_path):
    result = _node(tmp_path, CHANNEL + """
      const id='Z'.repeat(32);
      env.requestHook=async rec=>{
        if(rec.method==='GET'){channel.setVisible(false);return {status:200,body:{command:{id,action:'enter',object_id:'obj_1',remaining_ms:2900}}}}
        return {status:200,body:{command:'enter',id}};
      };
      channel.start();await env.tick();await env.tick();
      return {received,posts:env.posts,stats:channel.stats(),state:channel.state()};
    """)
    assert result["received"][0]["action"] == "enter"
    assert result["posts"][0]["url"] == f"/api/fullscreen/commands?wait_s={int(fs.MAX_POLL_WAIT_S)}"
    assert result["posts"][1] == {"url": "/api/fullscreen/commands/" + "Z" * 32, "method": "POST",
                                  "body": {"state": "needs_gesture", "object_id": "obj_1"}}
    assert result["stats"]["answered"] == 1 and result["stats"]["receiptFailed"] == 0


def test_a_receipt_the_server_refuses_and_a_handler_that_throws_are_logged_not_swallowed(tmp_path):
    result = _node(tmp_path, CHANNEL + """
      env.boom=true;
      const id='Y'.repeat(32);let polls=0;
      env.requestHook=async rec=>{
        if(rec.method==='GET'){polls++;if(polls>1)channel.setVisible(false);return {status:200,body:{command:polls===1?{id,action:'enter'}:null}}}
        return {status:404,body:{error:{code:'fullscreen_unknown_command',message:'expiré'}}};
      };
      channel.start();await env.tick();await env.tick();await env.tick();
      return {receipt:env.posts.find(p=>p.method==='POST').body,stats:channel.stats(),
        logs:env.logs.map(l=>[l.l,l.e,(l.d.error||'')])};
    """)
    assert result["receipt"] == {"state": "refused", "code": fs.PAGE_ERROR, "reason": "handler exploded"}
    assert result["stats"]["receiptFailed"] == 1 and result["stats"]["answered"] == 0
    assert ["error", "fullscreen.command_failed", "handler exploded"] in result["logs"]
    assert ["error", "fullscreen.receipt_failed", "expiré (fullscreen_unknown_command)"] in result["logs"]


def test_poll_failures_back_off_visibly_and_the_loop_stops_when_the_tab_is_hidden(tmp_path):
    result = _node(tmp_path, CHANNEL + """
      env.requestHook=async()=>({status:500,body:{error:{message:'Core injoignable'}}});
      channel.start();await env.tick();await env.tick();await env.tick();await env.tick();
      const settled={running:channel.state().running,visible:channel.state().visible,failures:channel.state().failures};
      const before=env.posts.length;
      channel.setVisible(true);                // l'onglet revient : la boucle repart
      await env.tick();await env.tick();await env.tick();await env.tick();
      return {sleeps,settled,resumed:env.posts.length>before,
        warns:env.logs.filter(l=>l.e==='fullscreen.command_poll_failed').length,delays:sleeps.map(Number),
        first:env.logs[0]};
    """)
    assert result["settled"]["visible"] is False and result["settled"]["running"] is False
    assert result["warns"] >= 4 and result["resumed"] is True
    assert result["delays"][0] < result["delays"][2] <= fs.MAX_POLL_WAIT_S * 1000    # le délai croît, plafonné
    assert result["first"]["d"]["error"] == "Core injoignable"


def test_the_module_loads_under_node_without_installing_into_a_page(tmp_path):
    result = _node(tmp_path, "const FS=makeEnv().FS;return {keys:Object.keys(FS).sort().slice(0,3),frozen:Object.isFrozen(FS)};")
    assert result["frozen"] is True


def test_an_instant_empty_reply_never_turns_the_long_poll_into_a_hot_loop(tmp_path):
    result = _node(tmp_path, CHANNEL + """
      let polls=0;
      env.requestHook=async rec=>{polls++;if(polls>=3)channel.setVisible(false);return {status:200,body:[]}};   // vide et immédiat
      channel.start();await env.tick();await env.tick();await env.tick();await env.tick();
      return {polls,sleeps,floor:FS.MIN_POLL_GAP_MS};
    """)
    assert result["floor"] == 1000 and result["polls"] == 3
    assert result["sleeps"] and all(0 < ms <= 1000 for ms in result["sleeps"])   # une pause entre deux polls vides
