"""Le plein écran de surface dans un VRAI Chrome sans tête (studio de présentation, Slice 03).

Page : un hôte de fenêtre de scène (`[data-object-id]`, titre, conteneur) qui porte un **vrai** cadre de prefab,
monté par le vrai `JarvisPrefabHost` avec le vrai paquet `test.counter` (donc `sandbox="allow-scripts"` posé par
l'hôte lui-même), et le vrai module `control_center_fullscreen.js`. Le relais `/api/fullscreen/*` est un double
dans la page (`window.__fs`) ; la chaîne HTTP réelle est prouvée par `test_fullscreen_commands.py`.

Les clics et les touches sont de vrais événements d'entrée CDP (donc avec activation utilisateur) ; les appels
`Runtime.evaluate` n'en ont aucune (c'est un appel de la voix ou d'un agent).

Ce que ce fichier prouve, mesuré :

- sans activation, `requestFullscreen()` échoue proprement (`TypeError: Permissions check failed`) et la demande de
  l'agent ARME une invite au lieu d'entrer ; un cadre de prefab ne peut pas se mettre en plein écran lui-même
  (`Disallowed by permissions policy`), ce qui est la raison de l'hôte ;
- avec un vrai clic sur l'invite, **l'hôte** entre en plein écran (`document.fullscreenElement`), le cadre remplit
  l'écran, la chrome de fenêtre disparaît, le focus est sur l'hôte ;
- la sortie (déclenchée côté navigateur, comme Échap) restaure rectangle, chrome, focus et marqueurs ;
- le `sandbox` du cadre vaut toujours exactement `allow-scripts`, sans `allow` ni `allowfullscreen`, et le cadre
  reste prêt (le protocole `jv:1` n'a pas bougé) ;
- l'échéance et l'annulation retirent l'invite, visiblement, sans entrer ;
- les touches de navigation sont lues sur l'hôte ;
- le module s'installe dans la page servie sans erreur et sans rien changer au mode fenêtre.

Ce que le sans-tête ne prouve pas (recette Humaine, `docs/OPERATIONS.md`) : la touche Échap physique, plusieurs
écrans réels, l'invite d'autorisation de gestion des fenêtres, l'allure sur un vrai écran.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

import jarvis.runtime.control_center as cc
from tests.fakes.prefab_js import catalogue_bundles

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "jarvis" / "runtime"
HARNESS = Path(__file__).parent / "_fullscreen_browser.mjs"

CHROME_CANDIDATES = (
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
)


def _chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("chrome") or shutil.which("google-chrome")
    if found:
        return found
    pytest.skip("Chrome absent")


def _inline(name: str) -> str:
    return (RUNTIME / name).read_text(encoding="utf-8")


PAGE = """<!doctype html><html lang="fr"><meta charset="utf-8"><title>fullscreen proof</title>
<style>
html,body{margin:0;background:#101820;font:14px system-ui,sans-serif;color:#cde}
#trigger{position:absolute;left:10px;top:10px;height:36px}
#stage{position:absolute;left:60px;top:140px;width:420px;height:300px}
.win{position:absolute;left:0;top:0;width:420px;height:300px;box-sizing:border-box;display:flex;flex-direction:column;
  background:#0b1620;border:2px solid #2a8;border-radius:12px;box-shadow:0 8px 30px #000}
.win .sc-title{flex:none;height:30px;padding:6px 10px;box-sizing:border-box}
.win .handle{flex:none;height:10px;background:#2a8}
</style>
<button id="trigger" type="button">Declencheur</button>
<div id="stage"></div>
<script>__PROTOCOL__</script>
<script>__HOST__</script>
<script>window.__toasts=[];function toast(t){window.__toasts.push(t)}</script>
<script>__FULLSCREEN__</script>
<script>
const BUNDLE=__BUNDLE__;
const hostLog=[];window.__hostLog=hostLog;
const host=JarvisPrefabHost.createPrefabHost({document,window,log:(k,d)=>hostLog.push([k,d]),
  fetchBundle:async()=>JSON.parse(JSON.stringify(BUNDLE))});
function addWindow(id,title){
  const el=document.createElement('div');el.className='win';el.id='win_'+id;el.dataset.objectId=id;el.tabIndex=-1;
  const head=document.createElement('div');head.className='sc-title';head.textContent=title;el.appendChild(head);
  const slot=JarvisPrefabHost.sceneSlot(el,true);
  const handle=document.createElement('div');handle.className='handle';el.appendChild(handle);
  document.getElementById('stage').appendChild(el);
  host.mount(slot,{object_id:id,title,prefab:{id:'test.counter',version:1},props:{label:'Count'},data:{count:3,notes:'n'}});
  return el;
}
const el=addWindow('obj_1','Diapo un');el.id='win1';
window.__nav=[];JarvisFullscreen.onNavigate(e=>window.__nav.push(e.action+':'+e.key));
document.getElementById('trigger').focus();
const box=e=>{if(!e)return null;const b=e.getBoundingClientRect();return [Math.round(b.left),Math.round(b.top),Math.round(b.width),Math.round(b.height)]};
window.__probe=()=>{
  const w=document.getElementById('win1'),f=w.querySelector('iframe'),t=w.querySelector('.sc-title'),h=w.querySelector('.handle');
  const p=document.getElementById('jvFullscreenPrompt');
  return {fs:document.fullscreenElement&&document.fullscreenElement.id,win:box(w),frame:box(f),title:box(t),
    titleDisplay:getComputedStyle(t).display,handleDisplay:getComputedStyle(h).display,
    active:document.activeElement&&(document.activeElement.id||document.activeElement.tagName),
    prompt:!!p,promptText:p?p.textContent:'',promptRole:p?p.getAttribute('role'):null,
    sandbox:f.getAttribute('sandbox'),allow:f.getAttribute('allow'),allowfs:f.hasAttribute('allowfullscreen'),
    csp:null,ready:host.state('obj_1'),mark:w.getAttribute('data-jv-fullscreen'),state:JarvisFullscreen.state().state,
    vw:innerWidth,vh:innerHeight,winBg:getComputedStyle(w).backgroundColor,winRadius:getComputedStyle(w).borderRadius};
};
</script></html>
"""


@pytest.fixture
async def page(tmp_path):
    bundles = await catalogue_bundles(tmp_path, "test.counter")
    html = (PAGE.replace("__PROTOCOL__", _inline("control_center_prefab_protocol.js"))
            .replace("__HOST__", _inline("control_center_prefab_host.js"))
            .replace("__FULLSCREEN__", _inline("control_center_fullscreen.js"))
            .replace("__BUNDLE__", json.dumps(bundles["test.counter@1"])))
    out = tmp_path / "fullscreen-proof.html"
    out.write_text(html, encoding="utf-8")
    return out


def _drive(page: Path, plan: list) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    done = subprocess.run([node, str(HARNESS), str(page), _chrome(), json.dumps(plan)],
                          capture_output=True, text=True, encoding="utf-8", timeout=300, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


READY = {"until": "window.__probe().ready==='ready'", "ms": 8000}
GO = "#jvFullscreenPrompt .jvfs-go"
PROMPT = {"until": "!!document.getElementById('jvFullscreenPrompt')", "ms": 4000}
CMD = ("window.__fs.queue.push(Object.assign({id:'%s'.repeat(32),action:'enter',object_id:'obj_1',display:'current',"
       "keys:'host',arm_s:30,remaining_ms:2900},%s))")
POSTS = {"value": "posts", "expr": "window.__fs.posts"}
START_KEYS = ("win", "frame", "title", "titleDisplay", "handleDisplay", "winBg", "winRadius", "sandbox", "allow",
              "allowfs", "ready")


def probe(name: str) -> dict:
    return {"value": name, "expr": "window.__probe()"}


def command(letter: str, **fields) -> dict:
    return {"eval": CMD % (letter, json.dumps(fields))}


def posted(reads: dict) -> list[tuple[str, dict]]:
    """Ce que la page a envoyé au serveur : (route sans préfixe, corps)."""

    return [(p["url"].replace("/api/fullscreen", ""), p["body"]) for p in reads["posts"]]


def no_noise(out: dict) -> None:
    assert out["errors"] == []
    assert not [line for line in out["console"] if line.startswith(("error", "warning"))], out["console"]


async def test_without_activation_it_fails_cleanly_and_arms_a_visible_prompt(page):
    out = _drive(page, [
        READY, probe("start"),
        {"value": "frame_direct", "expr": "document.querySelector('#win1 iframe').requestFullscreen().then(()=>'ok',e=>e.name+': '+e.message)"},
        {"value": "host_direct", "expr": "document.getElementById('win1').requestFullscreen().then(()=>'ok',e=>e.name+': '+e.message)"},
        {"value": "activation", "expr": "navigator.userActivation.isActive"},
        {"value": "enter", "expr": "JarvisFullscreen.enter({object_id:'obj_1'})"},
        probe("armed"), POSTS,
        {"value": "rules", "expr": "[...document.getElementById('jv-fullscreen-style').sheet.cssRules].map(r=>r.selectorText||r.cssText.slice(0,40))"},
    ])["reads"]
    # Le navigateur refuse sans geste, avec ses mots ; rien n'est entré.
    assert out["frame_direct"] == "TypeError: Permissions check failed"
    assert out["host_direct"] == "TypeError: Permissions check failed"
    assert out["activation"] is False
    assert out["enter"] == {"state": "needs_gesture", "code": "fullscreen_needs_gesture", "object_id": "obj_1"}
    armed = out["armed"]
    assert armed["fs"] is None and armed["state"] == "needs_gesture" and armed["mark"] is None
    assert armed["prompt"] is True and armed["promptRole"] == "alertdialog" and armed["active"] == "BUTTON"
    assert "Diapo un" in armed["promptText"] and "30 s" in armed["promptText"] and "Annuler" in armed["promptText"]
    assert posted(out) == []                                                   # aucun « entered » rapporté
    # Le mode fenêtre n'a pas bougé d'un pixel, et le cadre garde exactement son bac à sable.
    for key in START_KEYS:
        assert armed[key] == out["start"][key], key
    assert (armed["sandbox"], armed["allow"], armed["allowfs"], armed["ready"]) == ("allow-scripts", None, False, "ready")
    # Les règles ajoutées ne visent que l'état plein écran et l'invite : aucune ne touche la fenêtre ordinaire.
    assert all(":fullscreen" in rule or "jvFullscreenPrompt" in rule or "prefers" in rule or "forced" in rule
               for rule in out["rules"]), out["rules"]


async def test_a_real_click_on_the_prompt_enters_the_host_and_the_frame_fills_the_screen(page):
    result = _drive(page, [
        READY,
        {"eval": "JarvisFullscreen.enter({object_id:'obj_1',keys:'host'})"}, PROMPT,
        {"click": GO}, {"until": "!!document.fullscreenElement", "ms": 4000}, {"wait": 150},
        probe("entered"), POSTS,
        {"value": "hostlog", "expr": "window.__hostLog.map(l=>l[0])"},
    ])
    out, entered = result["reads"], result["reads"]["entered"]
    assert entered["fs"] == "win1" and entered["state"] == "entered" and entered["mark"] == "1"
    # L'hôte entier est plein écran ; le cadre qu'il contient remplit l'écran ; la chrome de fenêtre a disparu.
    assert entered["win"] == [0, 0, 1000, 700] and (entered["vw"], entered["vh"]) == (1000, 700)
    assert entered["frame"] == [0, 0, 1000, 700]
    assert entered["titleDisplay"] == "none" and entered["handleDisplay"] == "none"
    assert (entered["winBg"], entered["winRadius"]) == ("rgb(0, 0, 0)", "0px")
    assert entered["prompt"] is False and entered["active"] == "win1"       # les touches vont à l'hôte
    # Le bac à sable est intact et le protocole du cadre n'a pas bougé.
    assert (entered["sandbox"], entered["allow"], entered["allowfs"], entered["ready"]) == ("allow-scripts", None, False, "ready")
    assert not any("violation" in key or "error" in key for key in out["hostlog"]), out["hostlog"]
    assert [body for _, body in posted(out)] == [{"state": "entered", "display_selection": "not_requested",
                                                  "object_id": "obj_1"}]   # entrée locale : pas d'armement, pas d'id
    no_noise(result)


async def test_exit_restores_layout_focus_and_marks_and_escape_is_the_emergency_exit(page):
    result = _drive(page, [
        READY, probe("start"),
        {"eval": "JarvisFullscreen.enter({object_id:'obj_1',keys:'host'})"}, PROMPT, {"click": GO},
        {"until": "!!document.fullscreenElement", "ms": 4000}, {"wait": 150},
        {"key": "ArrowRight"}, {"key": "ArrowLeft"}, {"key": " "}, {"key": "Home"},
        {"click": "#win1 iframe"}, {"wait": 150},                       # un clic DANS le cadre : le focus y va
        {"value": "focus_after_frame_click", "expr": "document.activeElement.id||document.activeElement.tagName"},
        {"key": "ArrowRight"},                                          # ... et les touches reviennent à l'hôte
        {"key": "Escape"}, {"until": "!document.fullscreenElement", "ms": 4000}, {"wait": 150},
        probe("after_escape"),
        {"value": "nav", "expr": "window.__nav"},
        # Seconde entrée, cette fois avec une activation vivante (une vraie touche) : elle entre sans invite ;
        # puis sortie par l'API : même restauration.
        {"key": "Home"},
        {"value": "second", "expr": "JarvisFullscreen.enter({object_id:'obj_1',keys:'host'}).then(r=>r.state)"},
        {"until": "!!document.fullscreenElement", "ms": 4000},
        {"eval": "JarvisFullscreen.exit()"}, {"until": "!document.fullscreenElement", "ms": 4000}, {"wait": 150},
        probe("after_api_exit"), POSTS,
    ])
    out = result["reads"]
    assert out["nav"] == ["next:ArrowRight", "previous:ArrowLeft", "next: ", "first:Home", "next:ArrowRight"]
    assert out["focus_after_frame_click"] == "win1" and out["second"] == "entered"
    for name in ("after_escape", "after_api_exit"):
        after = out[name]
        for key in START_KEYS:
            assert after[key] == out["start"][key], (name, key)
        assert after["fs"] is None and after["mark"] is None and after["state"] == "exited"
        assert after["active"] == "trigger" and after["prompt"] is False         # focus rendu à qui l'avait
    assert [(url, body["state"]) for url, body in posted(out)] == [
        ("/state", "entered"), ("/state", "exited"), ("/state", "entered"), ("/state", "exited")]
    no_noise(result)


async def test_an_agent_command_arms_then_a_click_enters_then_an_exit_command_leaves(page):
    result = _drive(page, [
        READY,
        command("Q", arm_s=20), PROMPT,
        {"value": "armed", "expr": "window.__probe()"},
        {"click": GO}, {"until": "!!document.fullscreenElement", "ms": 4000}, {"wait": 150},
        probe("entered"),
        command("R", action="exit"),
        {"until": "!document.fullscreenElement", "ms": 4000},
        {"until": "window.__fs.posts.length>=4", "ms": 4000},
        probe("exited"),
        command("S", object_id="gone"), {"until": "window.__fs.posts.length>=5", "ms": 4000},
        POSTS,
    ])
    out = result["reads"]
    assert out["armed"]["fs"] is None and out["armed"]["state"] == "needs_gesture" and "20 s" in out["armed"]["promptText"]
    assert out["entered"]["fs"] == "win1" and out["exited"]["fs"] is None
    assert out["exited"]["win"] == [60, 140, 420, 300] and out["exited"]["active"] == "trigger"
    sent = posted(out)
    # Le reçu de remise de l'armement vient AVANT toute entrée ; la page ne dit « entered » qu'après le clic.
    assert sent[0] == ("/commands/" + "Q" * 32, {"state": "needs_gesture", "display_selection": "not_requested",
                                                 "object_id": "obj_1"})
    assert sent[1][1]["state"] == "entered" and sent[1][1]["id"] == "QQQQQQQQ"   # le rapport porte l'armement satisfait
    assert {(url, body["state"]) for url, body in sent[2:4]} == {("/commands/" + "R" * 32, "exited"), ("/state", "exited")}
    assert sent[4][0] == "/commands/" + "S" * 32
    assert sent[4][1]["state"] == "refused" and sent[4][1]["code"] == "fullscreen_target_missing"
    assert out["entered"]["prompt"] is False
    no_noise({"errors": result["errors"], "console": [c for c in result["console"] if "target_missing" not in c]})


async def test_the_arm_deadline_and_cancel_remove_the_prompt_visibly_without_entering(page):
    out = _drive(page, [
        READY,
        command("D", arm_s=3), PROMPT,
        {"wait": 1200}, {"value": "mid", "expr": "document.querySelector('#jvFullscreenPrompt .jvfs-count').textContent"},
        {"until": "!document.getElementById('jvFullscreenPrompt')", "ms": 6000}, {"wait": 150},
        probe("expired"),
        {"value": "toasts", "expr": "window.__toasts"},
        command("C", arm_s=30), PROMPT,
        {"click": "#jvFullscreenPrompt .jvfs-cancel"}, {"wait": 300},
        probe("cancelled"), POSTS,
    ])["reads"]
    assert out["mid"] in ("2 s", "1 s")                                  # le compte à rebours descend
    for name in ("expired", "cancelled"):
        assert out[name]["fs"] is None and out[name]["prompt"] is False and out[name]["active"] == "trigger"
    assert out["expired"]["state"] == "expired" and out["cancelled"]["state"] == "exited"
    assert out["toasts"][0]["kind"] == "warn" and "3 s" in out["toasts"][0]["sub"]
    states = [(body["state"], body.get("code")) for _, body in posted(out)]
    assert states == [("needs_gesture", None), ("expired", "fullscreen_arm_expired"),
                      ("needs_gesture", None), ("exited", "fullscreen_cancelled")]


async def test_a_display_that_the_browser_will_not_grant_falls_back_and_says_so(page):
    out = _drive(page, [
        READY,
        command("P", display="primary"), PROMPT,
        {"click": GO}, {"until": "!!document.fullscreenElement", "ms": 4000}, {"wait": 150},
        probe("entered"), {"value": "state", "expr": "JarvisFullscreen.state()"},
        {"key": "Escape"}, {"until": "!document.fullscreenElement", "ms": 4000},
        POSTS,
    ])["reads"]
    # Mesuré : Chrome sans tête expose getScreenDetails() mais refuse l'autorisation ; l'entrée a lieu quand même.
    assert out["entered"]["fs"] == "win1"
    assert out["state"]["displaySelection"] in ("denied", "unavailable")
    entered = [body for _, body in posted(out) if body["state"] == "entered"][0]
    assert entered["display_selection"] == out["state"]["displaySelection"]


def _served_page(tmp_path: Path) -> Path:
    """La page servie, composée par la même chaîne de marqueurs que `ControlCenter.index`."""

    html = (RUNTIME / "control_center.html").read_text(encoding="utf-8")
    pairs = [
        (getattr(cc, name), getattr(cc, name.replace("_MARKER", "_FILE")))
        for name in dir(cc)
        if name.endswith("_SCRIPT_MARKER") and hasattr(cc, name.replace("_MARKER", "_FILE"))
    ]
    for marker, filename in pairs:
        html = html.replace(marker, (RUNTIME / filename).read_text(encoding="utf-8"))
    assert not [m for m, _ in pairs if m in html], "marqueurs non remplacés"
    html = re.sub(r'<iframe class="face"[^>]*></iframe>', '<div class="face"></div>', html)
    out = tmp_path / "served.html"
    out.write_text(html, encoding="utf-8")
    return out


def test_the_served_control_center_installs_the_module_and_polls_without_error(tmp_path):
    result = _drive(_served_page(tmp_path), [
        {"wait": 900},
        {"value": "api", "expr": "Object.keys(window.JarvisFullscreen).sort()"},
        {"value": "style", "expr": "!!document.getElementById('jv-fullscreen-style')"},
        {"value": "channel", "expr": "window.JarvisFullscreen.channel.state()"},
        {"value": "gets", "expr": "window.__fs.gets"},
        {"value": "state", "expr": "window.JarvisFullscreen.state()"},
        {"value": "prompt", "expr": "!!document.getElementById('jvFullscreenPrompt')"},
        {"value": "marked", "expr": "document.querySelectorAll('[data-jv-fullscreen]').length"},
        {"value": "scene", "expr": "typeof window.JarvisScene"},
    ])
    reads = result["reads"]
    assert reads["api"] == ["cancel", "channel", "enter", "exit", "onNavigate", "state", "stats"]
    assert reads["style"] is True and reads["channel"]["visible"] is True and reads["channel"]["running"] is True
    assert reads["gets"] >= 1                                           # la page long-poll bien le canal
    assert reads["state"]["state"] == "exited" and reads["state"]["supported"] is True
    assert reads["prompt"] is False and reads["marked"] == 0
    no_noise(result)


def test_the_prompt_stays_clickable_while_a_control_center_confirm_dialog_makes_the_page_inert(tmp_path):
    """QA-1 POLISH 3 : la vraie `confirmDialog` rend `inert` tout enfant de `body`, y compris ceux ajoutés pendant
    qu'elle est ouverte. L'invite (enfant de `<html>`, couche supérieure) reste cliquable : un vrai clic CDP entre."""

    result = _drive(_served_page(tmp_path), [
        {"wait": 700},
        {"eval": "document.body.insertAdjacentHTML('beforeend','<div id=w1 data-object-id=w1 "
                 "style=\"position:fixed;left:0;top:300px;width:200px;height:100px;background:#123\">w</div>')"},
        {"eval": "void confirmDialog({title:'Confirmer ?',lines:['Une boîte modale est ouverte']})"},
        {"eval": "document.body.insertAdjacentHTML('beforeend','<div id=latecomer></div>')"},
        {"wait": 100},
        {"value": "dialog", "expr": "({open:!!CONFIRM.resolve,w1Inert:document.getElementById('w1').inert,"
                                    "lateInert:document.getElementById('latecomer').inert})"},
        {"eval": "JarvisFullscreen.enter({object_id:'w1'})"},
        {"until": "!!document.getElementById('jvFullscreenPrompt')", "ms": 4000},
        {"wait": 100},
        {"value": "armed", "expr": "(()=>{const p=document.getElementById('jvFullscreenPrompt');"
                                   "return {inert:p.inert,parent:p.parentNode===document.documentElement,"
                                   "popover:p.matches(':popover-open'),state:JarvisFullscreen.state().state,"
                                   "hit:document.elementFromPoint(p.getBoundingClientRect().left+p.getBoundingClientRect().width/2,"
                                   "p.getBoundingClientRect().top+10).closest('#jvFullscreenPrompt')!==null}})()"},
        {"click": GO},
        {"until": "!!document.fullscreenElement", "ms": 4000}, {"wait": 200},
        {"value": "after", "expr": "({fs:document.fullscreenElement&&document.fullscreenElement.id,state:JarvisFullscreen.state().state,"
                                   "prompt:!!document.getElementById('jvFullscreenPrompt'),dialogStillOpen:!!CONFIRM.resolve})"},
    ])
    reads = result["reads"]
    # Le mécanisme est réel : la boîte rend inerte l'existant ET l'arrivant.
    assert reads["dialog"] == {"open": True, "w1Inert": True, "lateInert": True}
    assert reads["armed"] == {"inert": False, "parent": True, "popover": True, "state": "needs_gesture", "hit": True}
    assert reads["after"] == {"fs": "w1", "state": "entered", "prompt": False, "dialogStillOpen": True}
    assert result["errors"] == []
