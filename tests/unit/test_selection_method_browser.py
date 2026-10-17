"""Sélection Souris / Bare Hands dans Chrome, sur le **vrai** moteur Bare Hands.

Contrat : `docs/control-center-shell.md` › Selection method, D5 de
`tasks/jarvis-board-orbital-ui-workspace-rail/docs/06-resolved-architecture.md`.
`test_input_arbitration_js.py` tient le modèle pur (`decide`, projection) ;
ce fichier charge la page **servie** (composée comme `ControlCenter.index`)
depuis un petit serveur HTTP de test, et conduit la roue avec de vrais
événements CDP.

Ce qui est vrai et ce qui est doublé :

- vrais : la page entière, `control_center_barehands.js` (contrôleur, cycle de
  vie, couture, `enable`/`disable`/`activate`), le contrôle du haut
  (`selectMethod`), le canal de commandes (long-poll et reçu), la roue ;
- caméra : celle de Chrome (`--use-fake-device-for-media-stream`), donc un vrai
  `getUserMedia`, une vraie piste qu'on peut voir s'arrêter ;
- doublés : le serveur (`/api/barehands` passe par le vrai
  `barehands_test_mode.apply`/`describe`, en mémoire ; `/api/status` minimal ;
  `/api/barehands/commands` est une file que le test arme) et MediaPipe : un
  `vision_bundle.mjs` factice dont le détecteur ne voit aucune main et compte
  ses appels (aucune image analysée = aucune posture en C possible).

Captures d'écran : dans `$SELECTION_SHOTS` s'il est défini (preuves de la
Slice), sinon dans `tmp_path`. Se saute proprement sans Chrome ni node.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from urllib.parse import urlparse

import pytest

from jarvis.runtime import barehands_test_mode as bh_settings
from tests.unit.test_interaction_mode_hud_browser import HARNESS, _chrome, _served_page

ROOT = Path(__file__).resolve().parents[2]
WHEEL = ROOT / "jarvis" / "runtime" / "control_center_tool_wheel.js"
W, H = 1440, 900
CHROME_FLAGS = "--use-fake-device-for-media-stream --use-fake-ui-for-media-stream --enable-unsafe-swiftshader"

#: MediaPipe factice : le détecteur ne voit aucune main et compte ses appels.
FAKE_BUNDLE = r"""
const seen=globalThis.__fakeLandmarker||(globalThis.__fakeLandmarker={created:0,calls:0,closed:0});
export const FilesetResolver={forVisionTasks:async()=>({})};
export class HandLandmarker{
  static async createFromOptions(){seen.created+=1;return new HandLandmarker()}
  detectForVideo(){seen.calls+=1;return {landmarks:[],worldLandmarks:[],handednesses:[],handedness:[]}}
  setOptions(){}
  close(){seen.closed+=1}
}
"""


class _World:
    """L'état du serveur de test : réglages Bare Hands, assets, file de commandes."""

    def __init__(self, page: Path, vendor: Path, real_vendor: Path | None) -> None:
        self.page = page
        self.vendor = vendor
        self.real_vendor = real_vendor
        self.lock = threading.Lock()
        self.settings: dict = {}
        self.assets = True
        self.commands: queue.Queue = queue.Queue()
        self.receipts: list = []

    def reset(self, body: dict) -> None:
        with self.lock:
            self.settings = {}
            if body.get("enabled"):
                bh_settings.apply(self.settings, {"enabled": True})
            self.assets = bool(body.get("assets", True))
            while not self.commands.empty():
                self.commands.get_nowait()

    def root(self) -> Path:
        if not self.assets:
            return self.vendor / "absent"
        return self.real_vendor or self.vendor

    def describe(self) -> dict:
        with self.lock:
            return bh_settings.describe(self.settings, self.root())


def _handler(world: _World):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:  # silence
            return

        def _send(self, status: int, body, content_type: str = "application/json") -> None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            return json.loads(raw or b"{}")

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/":
                return self._send(200, world.page.read_bytes(), "text/html; charset=utf-8")
            if path == "/api/barehands":
                return self._send(200, world.describe())
            if path == "/api/status":
                return self._send(200, {
                    "voice_state": "idle", "voice_online": False, "manual_wake_key": "f9",
                    "agent": {"name": "claude", "state": "stopped"}, "agent_cli": "claude", "error_count": 0,
                    "barehands": {"enabled": bool(world.describe()["enabled"])},
                })
            if path == "/api/barehands/commands":
                try:
                    command = world.commands.get(timeout=1.5)
                except queue.Empty:
                    command = None
                return self._send(200, {"command": command})
            if path.startswith(bh_settings.ASSET_ROUTE_PREFIX):
                found = bh_settings.asset_path(world.root(), path[len(bh_settings.ASSET_ROUTE_PREFIX):])
                if found is None:
                    return self._send(404, {"error": {"code": "not_found"}})
                return self._send(200, found[0].read_bytes(), found[1])
            return self._send(404, {"error": {"code": "not_found", "message": path}})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            body = self._body()
            if path == "/api/barehands":
                try:
                    with world.lock:
                        bh_settings.apply(world.settings, body)
                except bh_settings.BarehandsSettingsError as error:
                    return self._send(400, {"error": {"code": error.code, "message": str(error)}})
                return self._send(200, world.describe())
            if path.startswith("/api/barehands/commands/"):
                world.receipts.append({"id": path.rsplit("/", 1)[-1], **body})
                return self._send(200, {"ok": True})
            if path == "/api/test/reset":
                world.reset(body)
                return self._send(200, {"ok": True})
            if path == "/api/test/settings":
                with world.lock:
                    bh_settings.apply(world.settings, body)
                return self._send(200, {"ok": True})
            if path == "/api/test/command":
                world.commands.put({"id": body["id"], "name": body["name"], "remaining_ms": 3000})
                return self._send(200, {"ok": True})
            return self._send(404, {"error": {"code": "not_found"}})

    return Handler


SETUP = r"""(()=>{
  window.__sel={logs:[]};
  const info=console.info.bind(console),warn=console.warn.bind(console),error=console.error.bind(console);
  console.info=(...a)=>{window.__sel.logs.push(String(a[0]));info(...a)};
  console.warn=(...a)=>{window.__sel.logs.push(String(a[0]));warn(...a)};
  console.error=(...a)=>{window.__sel.logs.push(String(a[0]));error(...a)};
  const realGUM=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  window.__tracks=[];
  navigator.mediaDevices.getUserMedia=async c=>{const s=await realGUM(c);window.__tracks.push(...s.getTracks());return s};
  /* Slice 04 : plus de drapeau, la roue est construite d'office et visible. */
  return {flagDefault:!document.getElementById('toolWheel').hidden,installed:!!window.JarvisInputArbitration,webgl:!!document.createElement('canvas').getContext('webgl2')};
})()"""

STATE = r"""(()=>{
  const host=document.getElementById('toolWheel');
  const items=[...host.querySelectorAll('.tw-item')].map(b=>{const r=b.getBoundingClientRect();
    return {id:b.dataset.twItem||null,text:b.textContent,name:b.getAttribute('aria-label')||b.textContent,role:b.getAttribute('role'),
      checked:b.getAttribute('aria-checked'),disabled:b.getAttribute('aria-disabled'),tone:b.getAttribute('data-tw-tone'),
      icon:!!b.querySelector('svg'),x:r.left+r.width/2,y:r.top+r.height/2}});
  const sel=host.querySelector('[data-tw-slot=selection]');
  const badge=sel&&sel.querySelector('.tw-badge');
  const shown=id=>{const e=document.getElementById(id);return !!e&&getComputedStyle(e).display!=='none'&&e.getBoundingClientRect().width>0};
  const life=JarvisBarehands.lifecycleStatus();
  const lm=globalThis.__fakeLandmarker||{created:0,calls:0,closed:0};
  return {open:JarvisToolWheel.isOpen(),items,lifecycle:life.lifecycle,starting:life.starting,code:life.code,enabled:life.enabled,
    view:JarvisInputArbitration.view(),stats:JarvisInputArbitration.stats(),arb:JarvisInputArbitration.state(),
    wedgeName:sel&&sel.getAttribute('aria-label'),badge:badge&&!badge.hidden?badge.getAttribute('data-tw-tone'):null,
    anchorTone:host.querySelector('.tw-anchor').getAttribute('data-tw-tone'),anchorName:host.querySelector('.tw-anchor').getAttribute('aria-label'),
    hudShown:shown('barehandsHud'),paletteShown:shown('barehandsPalette'),
    tracks:(window.__tracks||[]).map(t=>t.readyState),landmarker:{...lm},
    tool:JarvisBarehands.tool(),
    toasts:[...document.querySelectorAll('.toasts .toast')].map(t=>t.innerText.replace(/\s+/g,' ').trim()),
    card:(document.querySelector('#barehandsCards[data-bh-card]')||{}).getAttribute?document.querySelector('#barehandsCards[data-bh-card]').getAttribute('data-bh-card'):null,
    logs:__sel.logs.filter(l=>/input_arbitration|selection\.|tool_wheel\.(item|secondary|status)|disabled_for_reason/.test(l))};
})()"""


def _geometry() -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = (f"const M=require({json.dumps(str(WHEEL))});const w=M.layoutWedges();"
              "process.stdout.write(JSON.stringify({w,sub2:M.layoutSubArc(2,w[0].midDeg)}))")
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _ev(expr: str) -> dict:
    return {"a": "eval", "expr": expr}


def _move(x: float, y: float, settle: int = 40) -> dict:
    return {"a": "mouse", "type": "mouseMoved", "x": x, "y": y, "settleMs": settle}


def _click(x: float, y: float, button: str = "left") -> list[dict]:
    return [_move(x, y), {"a": "mouse", "type": "mousePressed", "x": x, "y": y, "button": button},
            {"a": "mouse", "type": "mouseReleased", "x": x, "y": y, "button": button}]


def _wait(expr: str, ms: int = 8000) -> dict:
    return {"a": "wait", "expr": expr, "timeoutMs": ms}


def _post(path: str, body: dict) -> dict:
    return {"a": "post", "path": path, "body": body}


ACTIVE = "JarvisBarehands.lifecycleStatus().lifecycle==='active'"
#: Actif **et** persisté : `enable()` part après `activate()` (séquence du contrôle du haut).
PERSISTED = ACTIVE + "&&JarvisBarehands.lifecycleStatus().enabled"
OFF = "JarvisBarehands.lifecycleStatus().lifecycle==='off'&&!JarvisBarehands.lifecycleStatus().starting"
OPENED = "JarvisToolWheel.isOpen()"
SUB = "document.querySelectorAll('#toolWheel .tw-item').length>0&&!document.querySelector('#toolWheel .tw-item[aria-disabled=true]:only-child')"
#: Le premier niveau du sous-arc de Sélection (Souris / Bare Hands) est posé.
LEVEL1 = "!!document.querySelector('#toolWheel .tw-item[data-tw-item=bare_hands]')"
LEVEL2 = "!!document.querySelector('#toolWheel .tw-item[data-tw-item=sleep]')"
RESET_OFF = _post("/api/test/reset", {"enabled": False, "assets": True})
#: La roue au **clavier** (aucun événement de pointeur réel : rien ne reprend la main).
KB_SELECTION = [{"a": "focus", "selector": "#toolWheel .tw-anchor"}, {"a": "key", "key": "Enter"},
                {"a": "key", "key": "Enter"}]
FLOW = "JarvisBarehands.openFlow()"
#: Ce que le parcours montre : son nom, son écran (ses boutons), le cycle de vie, les reprises.
FLOW_STATE = ("(()=>({flow:JarvisBarehands.openFlow(),step:JarvisBarehands.calibration().step,lifecycle:JarvisBarehands.lifecycleStatus().lifecycle,"
              "actions:[...document.querySelectorAll('#jarvisFlow [data-flow-action]')].map(b=>b.getAttribute('data-flow-action')),"
              "stats:JarvisInputArbitration.stats(),arb:JarvisInputArbitration.state(),"
              "logs:__sel.logs.filter(l=>/input_arbitration\\.(flow|takeover)/.test(l))}))()")


@pytest.fixture(scope="module")
def shots(tmp_path_factory) -> Path:
    wanted = os.environ.get("SELECTION_SHOTS")
    target = Path(wanted) if wanted else tmp_path_factory.mktemp("selection-shots")
    target.mkdir(parents=True, exist_ok=True)
    return target


@pytest.fixture(scope="module")
def run(tmp_path_factory, shots):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    geo = _geometry()
    tmp = tmp_path_factory.mktemp("selection")
    vendor = tmp / "vendor"
    for relative, _type in bh_settings.ASSETS.values():
        target = vendor / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(FAKE_BUNDLE if relative.endswith("vision_bundle.mjs") else "", encoding="utf-8")
    real = os.environ.get("SELECTION_REAL_VENDOR")
    world = _World(_served_page(tmp), vendor, Path(real) if real else None)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(world))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/"

    anchor = (7, H / 2)
    sel = (geo["w"][0]["x"], H / 2 + geo["w"][0]["y"])
    # Les pastilles du sous-arc partent de leur point d'ancrage vers la droite.
    mouse_item = (geo["sub2"][0]["x"] + 30, H / 2 + geo["sub2"][0]["y"])
    bh_item = (geo["sub2"][1]["x"] + 30, H / 2 + geo["sub2"][1]["y"])
    open_selection = [_move(400, 450), _move(*anchor), _wait(OPENED, 3000), *_click(*sel), _wait(LEVEL1, 3000)]
    choose_bh = [*open_selection, *_click(*bh_item)]
    plan = {
        "offered": {"actions": [
            RESET_OFF, _ev(SETUP), _ev(STATE), *open_selection, _ev(STATE),
            {"a": "shot", "path": str(shots / "selection-subarc.png")},
            _ev("(()=>{document.getElementById('toolWheel').hidden=true;const s=id=>getComputedStyle(document.getElementById(id)).display;"
                "return {hud:s('barehandsHud'),palette:s('barehandsPalette')}})()"),
        ]},
        "bare_hands": {"actions": [
            RESET_OFF, _ev(SETUP), _ev(STATE), *choose_bh, _wait(PERSISTED), _ev(STATE),
            {"a": "eval", "expr": "fetch('/api/barehands').then(r=>r.json()).then(j=>j.enabled)"},
            # Tremblement de la souris immobile : quelques pixels autour d'un point, pendant 1,5 s.
            *[_move(700 + dx, 450 + dy, settle=30) for dx, dy in
              [(0, 0), (2, 1), (-1, 2), (1, -2), (-2, -1), (3, 0), (0, 3), (-3, -2), (2, 2), (-1, -3)] * 5],
            _ev(STATE),
            # Mouvement délibéré : 160 px en ~120 ms.
            *[_move(700 + 20 * i, 450, settle=15) for i in range(1, 9)],
            _wait(OFF, 5000), _ev(STATE),
        ]},
        "mouse": {"actions": [
            _post("/api/test/reset", {"enabled": True, "assets": True}), _ev(SETUP),
            _ev("JarvisInputArbitration.selectMethod('bare_hands')"), _wait(PERSISTED), _ev(STATE),
            # Le choix explicite, au clavier : la souris qui irait cliquer « Souris »
            # aurait déjà repris la main en bougeant (voir le test de reprise).
            {"a": "focus", "selector": "#toolWheel .tw-anchor"}, {"a": "key", "key": "Enter"},
            {"a": "key", "key": "Enter"}, _wait(LEVEL1, 3000), {"a": "key", "key": "Enter"},
            _wait(OFF, 5000), _ev(STATE),
            {"a": "eval", "expr": "new Promise(r=>setTimeout(()=>r(globalThis.__fakeLandmarker.calls),1500))"},
            _ev(STATE),
            {"a": "eval", "expr": "fetch('/api/barehands').then(r=>r.json()).then(j=>j.enabled)"},
        ]},
        "failed": {"actions": [
            _post("/api/test/reset", {"enabled": False, "assets": False}), _ev(SETUP), *choose_bh,
            _wait("JarvisBarehands.lifecycleStatus().lifecycle==='error'"), _ev(STATE),
            *open_selection, _ev(STATE),
            {"a": "shot", "path": str(shots / "selection-failed.png")},
        ]},
        # Bare Hands **reste actif** de bout en bout : la roue est conduite au
        # clavier, sans un seul événement de pointeur réel (la souris qui irait
        # jusqu'à la roue reprendrait la main et éteindrait Bare Hands).
        "tools": {"actions": [
            _post("/api/test/reset", {"enabled": False, "assets": True}), _ev(SETUP),
            _ev("JarvisInputArbitration.selectMethod('bare_hands')"), _wait(PERSISTED),
            {"a": "eval", "expr": "new Promise(r=>setTimeout(()=>r(true),1600))"},
            _ev("(window.__toolWrites=[],(()=>{const f=window.fetch;window.fetch=(u,o)=>{"
                "if(String(u).endsWith('/api/barehands')&&o&&o.method==='POST')window.__toolWrites.push(JSON.parse(o.body));"
                "return f(u,o)}})(),true)"),
            *KB_SELECTION, _wait(LEVEL1, 3000),
            {"a": "focus", "selector": "#toolWheel .tw-item[data-tw-item=bare_hands]"},
            {"a": "key", "key": "F10", "shift": True}, _wait(LEVEL2, 3000), _ev(STATE),
            {"a": "shot", "path": str(shots / "bare-hands-subarc.png")},
            {"a": "focus", "selector": "#toolWheel .tw-item[data-tw-item='tool:pan']"}, {"a": "key", "key": "Enter"},
            _wait("JarvisBarehands.tool()==='pan'", 4000), _ev(STATE),
            {"a": "eval", "expr": "fetch('/api/barehands').then(r=>r.json()).then(j=>j.tool)"},
            {"a": "eval", "expr": "JarvisBarehandsPalette.model().items.filter(i=>i.active||i.state==='active').map(i=>i.id)"},
            _ev("window.__toolWrites"),
            # Clavier : Maj+F10 sur « Bare Hands », Échap ramène au premier niveau.
            *KB_SELECTION, _wait(LEVEL1, 3000),
            {"a": "focus", "selector": "#toolWheel .tw-item[data-tw-item=bare_hands]"},
            {"a": "key", "key": "F10", "shift": True}, _wait(LEVEL2, 3000), _ev(STATE),
            {"a": "key", "key": "Escape"}, _wait(LEVEL1, 3000), _ev(STATE),
            # Aide : la carte s'ouvre par la même porte que le menu du haut.
            {"a": "key", "key": "F10", "shift": True}, _wait(LEVEL2, 3000),
            {"a": "focus", "selector": "#toolWheel .tw-item[data-tw-item=help]"}, {"a": "key", "key": "Enter"},
            _wait("!!document.querySelector('#barehandsCards[data-bh-card]')", 3000), _ev(STATE),
            # Rendre la main : le pas suivant charge sa page avant son `reset`, et
            # un maître laissé vrai sur le serveur la ferait démarrer Bare Hands.
            _ev("JarvisInputArbitration.selectMethod('mouse')"), _wait(OFF, 5000),
        ]},
        # B1 : un parcours Bare Hands se conduit à la souris. Calibration ouverte,
        # de vrais clics sur ses boutons : aucune reprise, Bare Hands reste actif,
        # le parcours avance ; fermé, le clic suivant reprend la main.
        "flow": {"actions": [
            _post("/api/test/reset", {"enabled": False, "assets": True}), _ev(SETUP),
            _ev("JarvisInputArbitration.selectMethod('bare_hands')"), _wait(PERSISTED),
            {"a": "eval", "expr": "new Promise(r=>setTimeout(()=>r(true),1600))"},
            _ev("JarvisBarehandsHudControl.runQuick('calibration').then(o=>!!(o&&o.ok))"),
            _wait(FLOW + "==='calibration'&&!!document.querySelector('#jarvisFlow [data-flow-action=skip]')", 8000),
            _ev(FLOW_STATE),
            *[_move(300 + 30 * i, 300, settle=15) for i in range(10)],
            {"a": "click", "selector": "#jarvisFlow [data-flow-action=skip]"},
            _wait("!!document.querySelector('#jarvisFlow [data-flow-action=back]')", 4000), _ev(FLOW_STATE),
            # Le choix de la raison entre par une animation : on clique une fois posé.
            {"a": "eval", "expr": "new Promise(r=>setTimeout(()=>r(true),600))"},
            {"a": "click", "selector": "#jarvisFlow [data-flow-action=skip-later]"},
            _wait("JarvisBarehands.calibration().step!=='neutral'", 4000), _ev(FLOW_STATE),
            {"a": "shot", "path": str(shots / "calibration-no-takeover.png")},
            {"a": "click", "selector": "#jarvisFlow [data-flow-close]"},
            _wait("!" + FLOW, 6000), _ev(FLOW_STATE),
            *_click(700, 450), _wait(OFF, 5000), _ev(FLOW_STATE),
        ]},
        # Le test (même coque) : son ouverture exempte aussi ; fermé, la reprise revient.
        "benchmark": {"actions": [
            _post("/api/test/reset", {"enabled": False, "assets": True}), _ev(SETUP),
            _ev("JarvisInputArbitration.selectMethod('bare_hands')"), _wait(PERSISTED),
            {"a": "eval", "expr": "new Promise(r=>setTimeout(()=>r(true),1600))"},
            _ev("JarvisBarehandsHudControl.runQuick('benchmark').then(o=>!!(o&&o.ok))"),
            _wait(FLOW + "==='benchmark'", 8000),
            *_click(700, 450), *_click(720, 470, button="right"), _ev(FLOW_STATE),
            {"a": "click", "selector": "#jarvisFlow [data-flow-close]"},
            _wait("!" + FLOW, 6000), _ev(FLOW_STATE),
            *_click(700, 450), _wait(OFF, 5000), _ev(FLOW_STATE),
        ]},
        # P3 : une reprise émise pendant qu'un choix est en vol (`method_busy`)
        # n'éteint pas la reprise pour toujours ; l'événement délibéré suivant retente.
        "busy": {"actions": [
            _post("/api/test/reset", {"enabled": False, "assets": True}), _ev(SETUP),
            # Actif sans maître persisté : `choose('active')` n'aura plus que
            # l'écriture `enable()` à faire, et elle est tenue 2 s en vol.
            _ev("JarvisBarehands.activate().then(()=>true)"), _wait(ACTIVE),
            {"a": "eval", "expr": "new Promise(r=>setTimeout(()=>r(true),1600))"},
            _ev("(()=>{const f=window.fetch;window.__realFetch=f;window.fetch=(u,o)=>"
                "String(u).endsWith('/api/barehands')&&o&&o.method==='POST'"
                "?new Promise(r=>setTimeout(r,2000)).then(()=>f(u,o)):f(u,o);"
                "window.__held=JarvisBarehandsHudControl.choose('active');return JarvisBarehandsHudControl.busy()})()"),
            *_click(700, 450),
            _wait("JarvisInputArbitration.stats().refusedTakeovers>=1", 3000), _ev(FLOW_STATE),
            _wait("!JarvisBarehandsHudControl.busy()", 6000),
            _ev("(window.fetch=window.__realFetch,true)"),
            *_click(700, 450), _wait(OFF, 5000), _ev(FLOW_STATE),
        ]},

        "voice": {"actions": [
            _post("/api/test/reset", {"enabled": False, "assets": True}), _ev(SETUP), _ev(STATE),
            # Ce que fait `settings_set(barehands.enabled, true)` côté serveur ;
            # la page le lit à son battement de statut et rallume (veille).
            _post("/api/test/settings", {"enabled": True}),
            _wait("JarvisBarehands.lifecycleStatus().lifecycle==='sleep'", 8000),
            _wait("JarvisBarehandsCommandChannel.state().running", 4000),
            # `barehands_activate`, remis par le canal de commandes.
            _post("/api/test/command", {"id": "a" * 32, "name": "activate"}),
            _wait(ACTIVE, 8000), _ev(STATE),
            {"a": "eval", "expr": "JarvisBarehandsCommandChannel.last()"},
        ]},
        "icon": {"actions": [
            RESET_OFF, _ev(SETUP),
            _ev("(()=>{const box=document.createElement('div');box.id='iconProof';box.style.cssText="
                "'position:fixed;inset:0;z-index:2147483646;background:#05090d;display:flex;gap:56px;align-items:center;justify-content:center;color:#6ee7ff';"
                "const A=JarvisToolWheel;const mk=(k,c)=>{const s=document.createElementNS('http://www.w3.org/2000/svg','svg');"
                "s.setAttribute('viewBox','0 0 24 24');s.setAttribute('width','240');s.setAttribute('height','240');s.setAttribute('fill','none');"
                "s.setAttribute('stroke','currentColor');s.setAttribute('stroke-width','1.5');s.setAttribute('stroke-linecap','round');s.setAttribute('stroke-linejoin','round');"
                "s.style.color=c;const art=window.__wheelArt[k];for(const d of art.paths){const p=document.createElementNS(s.namespaceURI,'path');p.setAttribute('d',d);s.appendChild(p)}"
                "for(const [cx,cy,r] of art.dots){const c2=document.createElementNS(s.namespaceURI,'circle');c2.setAttribute('cx',cx);c2.setAttribute('cy',cy);c2.setAttribute('r',r);c2.setAttribute('fill','currentColor');c2.setAttribute('stroke','none');s.appendChild(c2)}return s};"
                "box.appendChild(mk('mouse','#7190a0'));box.appendChild(mk('bare_hands','#6ee7ff'));document.body.appendChild(box);return true})()"),
            {"a": "shot", "path": str(shots / "bare-hands-icon.png")},
        ]},
    }
    # Le dessin, lu dans le module (et non recopié) pour la planche de l'icône.
    art = subprocess.run([node, "-e", f"process.stdout.write(JSON.stringify(require({json.dumps(str(WHEEL))}).ART))"],
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert art.returncode == 0, art.stderr
    plan["icon"]["actions"].insert(2, _ev(f"(window.__wheelArt={art.stdout},true)"))
    only = [n for n in os.environ.get("SELECTION_ONLY", "").split(",") if n]
    names = [n for n in plan if not only or n in only]
    steps = [{"width": W, "height": H, **plan[n]} for n in names]
    plan_file = tmp / "plan.json"
    plan_file.write_text(json.dumps(steps), encoding="utf-8")
    env = {**os.environ, "CDP_CHROME_FLAGS": CHROME_FLAGS}
    try:
        done = subprocess.run([node, str(HARNESS), base, chrome, "@" + str(plan_file)], env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=600, check=False)
    finally:
        server.shutdown()
    assert done.returncode == 0, done.stderr[-4000:]
    out = json.loads(done.stdout)
    result = {name: [a.get("value", a) for a in out[i]["actions"]] for i, name in enumerate(names)}
    result["receipts"] = world.receipts
    if os.environ.get("SELECTION_DUMP"):  # preuves : tout ce que la page a dit, étape par étape
        Path(os.environ["SELECTION_DUMP"]).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def _evals(steps: list) -> list:
    """Les seuls résultats d'`eval` lus comme états (dict avec `lifecycle`)."""

    return [s for s in steps if isinstance(s, dict) and "lifecycle" in s and "items" in s]


# ------------------------------------------------------------ critères d'acceptation


def test_only_mouse_and_bare_hands_offered(run):
    steps = run["offered"]
    setup, closed, opened = steps[1], steps[2], _evals(steps)[1]
    assert setup["installed"] is True and setup["flagDefault"] is True
    # Roue visible (d'office depuis la Slice 04) : le contrôle du haut-gauche et la bande d'outils
    # quittent la vue par défaut.
    assert closed["hudShown"] is False and closed["paletteShown"] is False
    # Bare Hands éteint au chargement : Sélection projette Souris.
    assert closed["view"]["method"] == "mouse" and closed["wedgeName"] == "Sélection — Souris"
    assert [(i["id"], i["role"], i["checked"], i["icon"]) for i in opened["items"]] == [
        ("mouse", "menuitemradio", "true", True), ("bare_hands", "menuitemradio", "false", True)]
    assert [i["name"] for i in opened["items"]] == ["Souris", "Bare Hands"]
    # Roue cachée (retour arrière) : le contrôle et la bande reviennent.
    assert steps[-1] == {"hud": "flex", "palette": "flex"}


def test_bare_hands_choice_activates_and_persists(run):
    steps = run["bare_hands"]
    states = _evals(steps)
    before, active = states[0], states[1]
    assert before["lifecycle"] == "off" and before["view"]["method"] == "mouse"
    assert active["lifecycle"] == "active" and active["enabled"] is True
    assert active["view"]["method"] == "bare_hands" and active["wedgeName"] == "Sélection — Bare Hands"
    persisted = steps[steps.index(active) + 1]
    assert persisted is True  # l'interrupteur maître est écrit sur le serveur
    assert active["stats"]["lastReturnOutcome"] == "active"
    assert isinstance(active["stats"]["lastReturnMs"], int)
    assert any("selection.bare_hands_return" in line for line in active["logs"])


def test_real_mouse_jitter_ignored_then_deliberate_move_takes_over(run):
    states = _evals(run["bare_hands"])
    jitter, after = states[2], states[3]
    # Tremblement : rien. Le pointeur réel a bien produit des échantillons.
    assert jitter["lifecycle"] == "active" and jitter["stats"]["takeovers"] == 0
    # Mouvement délibéré : une reprise, une seule, motif « movement », journalisée avec ses mesures.
    assert after["lifecycle"] == "off" and after["view"]["method"] == "mouse"
    assert after["stats"]["takeovers"] == 1 and after["stats"]["lastTakeover"]["reason"] == "movement"
    line = next(l for l in after["logs"] if "input_arbitration.takeover" in l)
    data = json.loads(line.split(" ", 2)[2])
    assert data["distance_px"] >= 48 and data["net_px"] >= 24 and data["window_ms"] == 400
    # La phrase du toast est celle de la reprise, pas l'arrêt générique.
    assert any("Souris reprise — Bare Hands éteint" in t for t in after["toasts"]), after["toasts"]
    assert any("barehands.disabled_for_reason" in l for l in after["logs"])


def test_mouse_choice_disables_bh_and_c_pose_cannot_wake(run):
    steps = run["mouse"]
    states = _evals(steps)
    active, off, later = states[0], states[1], states[2]
    assert active["lifecycle"] == "active" and active["tracks"] and set(active["tracks"]) == {"live"}
    assert off["lifecycle"] == "off" and off["view"]["method"] == "mouse" and off["enabled"] is False
    # Caméra rendue : chaque piste ouverte est terminée.
    assert set(off["tracks"]) == {"ended"}
    # Plus aucune image analysée : aucune posture en C ne peut être vue, donc rien ne réveille.
    calls_then = steps[steps.index(off) + 1]
    assert later["landmarker"]["calls"] == calls_then == off["landmarker"]["calls"]
    assert later["lifecycle"] == "off"
    assert steps[-1] is False  # l'interrupteur maître est écrit à faux
    # Choix explicite : la reprise souris n'a pas eu à intervenir.
    assert later["stats"]["takeovers"] == 0


def test_failed_activation_rendered_with_cause(run):
    states = _evals(run["failed"])
    failed, opened = states[0], states[1]
    assert failed["lifecycle"] == "error" and failed["code"] == "assets_missing"
    # Jamais montré comme Souris : Bare Hands, marque de panne, cause.
    assert failed["view"]["method"] == "bare_hands" and failed["view"]["tone"] == "error"
    assert failed["badge"] == "error" and failed["anchorTone"] == "error"
    assert "assets_missing" in failed["wedgeName"] and "assets_missing" in failed["anchorName"]
    bh = next(i for i in opened["items"] if i["id"] == "bare_hands")
    mouse = next(i for i in opened["items"] if i["id"] == "mouse")
    assert bh["checked"] == "true" and bh["tone"] == "error" and "assets_missing" in bh["name"]
    assert mouse["checked"] == "false"
    assert any("Modèle introuvable" in t for t in failed["toasts"]), failed["toasts"]


def test_tools_reachable_in_bare_hands_subarc_single_write_path(run):
    steps = run["tools"]
    states = _evals(steps)
    level2, picked, kb_level2, back, helped = states
    # Bare Hands **actif de bout en bout** : la roue a été conduite au clavier,
    # aucune reprise souris ne l'a éteint en chemin.
    assert [s["lifecycle"] for s in states] == ["active"] * 5
    assert all(s["stats"]["takeovers"] == 0 for s in states)
    # Bare Hands **actif de bout en bout** : la roue a été conduite au clavier,
    # aucune reprise souris ne l'a éteint en chemin.
    assert [s["lifecycle"] for s in states] == ["active"] * 5
    assert all(s["stats"]["takeovers"] == 0 for s in states)
    assert [i["id"] for i in level2["items"]] == [
        "tool:pointer", "tool:pan", "tool:select", "sleep", "help", "diagnostics", "calibration"]
    tools = level2["items"][:3]
    assert [(i["role"], i["checked"]) for i in tools] == [("menuitemradio", "true"), ("menuitemradio", "false"),
                                                          ("menuitemradio", "false")]
    assert all(i["icon"] for i in level2["items"])
    # Un clic : `tool('pan')` → `saveSettings({tool})`, relu par le serveur et par la bande.
    assert picked["tool"] == "pan"
    i = steps.index(picked)
    assert steps[i + 1] == "pan" and steps[i + 2] == ["pan"]
    # Écrit par `saveSettings` (POST /api/barehands), une écriture portant l'outil.
    assert [w.get("tool") for w in steps[i + 3] if "tool" in w] == ["pan"]
    # Écrit par `saveSettings` (POST /api/barehands), une écriture portant l'outil.
    assert [w.get("tool") for w in steps[i + 3] if "tool" in w] == ["pan"]
    assert any("selection.tool_selected" in l for l in picked["logs"])
    # Clavier : Maj+F10 ouvre le second niveau, Échap ramène sur « Bare Hands ».
    assert [i["id"] for i in kb_level2["items"]][:3] == ["tool:pointer", "tool:pan", "tool:select"]
    assert next(i for i in kb_level2["items"] if i["id"] == "tool:pan")["checked"] == "true"
    assert [i["id"] for i in back["items"]] == ["mouse", "bare_hands"]
    # Aide : la carte du contrôle du haut, par sa porte (`runQuick('help')`).
    assert helped["card"] == "help"


def _flow_states(steps: list) -> list:
    return [s for s in steps if isinstance(s, dict) and "flow" in s and "actions" in s]


def test_open_calibration_flow_never_taken_over_by_mouse(run):
    """B1 : de vrais clics dans la calibration ne reprennent pas la main ; fermée, oui."""

    steps = run["flow"]
    assert steps[5] is True  # runQuick('calibration') confirmé
    opened, skipped, back, closed, after = _flow_states(steps)
    for s in (opened, skipped, back):
        assert s["flow"] == "calibration" and s["lifecycle"] == "active", s
        assert s["stats"]["takeovers"] == 0 and s["arb"]["pending"] is False
    # Le parcours avance sous les clics : « Passer » ouvre le choix de la raison, « Plus tard »
    # passe l'étape (l'étape courante change).
    assert opened["step"] == "neutral" and "skip" in opened["actions"]
    assert "skip-later" in skipped["actions"] and back["step"] not in (None, "neutral")
    assert back["stats"]["flowExempt"] > 0
    assert any("input_arbitration.flow_exempt" in l and "calibration" in l for l in back["logs"])
    # La croix « Quitter ce parcours » est elle-même un clic exempté ; le parcours fermé, Bare Hands est toujours actif.
    assert closed["flow"] is None and closed["lifecycle"] == "active" and closed["stats"]["takeovers"] == 0
    # Puis le premier clic hors parcours reprend la main.
    assert after["lifecycle"] == "off" and after["stats"]["takeovers"] == 1
    assert after["stats"]["lastTakeover"]["reason"] == "click"
    assert any("input_arbitration.flow_closed" in l for l in after["logs"])


def test_open_benchmark_flow_never_taken_over_by_mouse(run):
    steps = run["benchmark"]
    assert steps[5] is True  # runQuick('benchmark') confirmé
    clicked, closed, after = _flow_states(steps)
    assert clicked["flow"] == "benchmark" and clicked["lifecycle"] == "active"
    assert clicked["stats"]["takeovers"] == 0
    assert closed["flow"] is None and closed["lifecycle"] == "active" and closed["stats"]["takeovers"] == 0
    assert after["lifecycle"] == "off" and after["stats"]["takeovers"] == 1


def test_takeover_refused_while_choice_in_flight_rearms(run):
    """P3 : `method_busy` rouvre l'épisode ; le clic suivant reprend la main."""

    steps = run["busy"]
    held, after = _flow_states(steps)
    assert held["lifecycle"] == "active" and held["stats"]["refusedTakeovers"] >= 1
    assert held["arb"]["pending"] is False
    assert any("input_arbitration.takeover_rearmed" in l for l in steps[-1]["logs"]) or \
        held["stats"]["refusedTakeovers"] >= 1
    assert after["lifecycle"] == "off" and after["stats"]["takeovers"] == held["stats"]["takeovers"] + 1


def _flow_states(steps: list) -> list:
    return [s for s in steps if isinstance(s, dict) and "flow" in s and "actions" in s]


def test_open_calibration_flow_never_taken_over_by_mouse(run):
    """B1 : de vrais clics dans la calibration ne reprennent pas la main ; fermée, oui."""

    steps = run["flow"]
    assert steps[5] is True  # runQuick('calibration') confirmé
    opened, skipped, back, closed, after = _flow_states(steps)
    for s in (opened, skipped, back):
        assert s["flow"] == "calibration" and s["lifecycle"] == "active", s
        assert s["stats"]["takeovers"] == 0 and s["arb"]["pending"] is False
    # Le parcours avance sous les clics : « Passer » ouvre le choix de la raison, « Plus tard »
    # passe l'étape (l'étape courante change).
    assert opened["step"] == "neutral" and "skip" in opened["actions"]
    assert "skip-later" in skipped["actions"] and back["step"] not in (None, "neutral")
    assert back["stats"]["flowExempt"] > 0
    assert any("input_arbitration.flow_exempt" in l and "calibration" in l for l in back["logs"])
    # La croix « Quitter ce parcours » est elle-même un clic exempté ; le parcours fermé, Bare Hands est toujours actif.
    assert closed["flow"] is None and closed["lifecycle"] == "active" and closed["stats"]["takeovers"] == 0
    # Puis le premier clic hors parcours reprend la main.
    assert after["lifecycle"] == "off" and after["stats"]["takeovers"] == 1
    assert after["stats"]["lastTakeover"]["reason"] == "click"
    assert any("input_arbitration.flow_closed" in l for l in after["logs"])


def test_open_benchmark_flow_never_taken_over_by_mouse(run):
    steps = run["benchmark"]
    assert steps[5] is True  # runQuick('benchmark') confirmé
    clicked, closed, after = _flow_states(steps)
    assert clicked["flow"] == "benchmark" and clicked["lifecycle"] == "active"
    assert clicked["stats"]["takeovers"] == 0
    assert closed["flow"] is None and closed["lifecycle"] == "active" and closed["stats"]["takeovers"] == 0
    assert after["lifecycle"] == "off" and after["stats"]["takeovers"] == 1


def test_takeover_refused_while_choice_in_flight_rearms(run):
    """P3 : `method_busy` rouvre l'épisode ; le clic suivant reprend la main."""

    steps = run["busy"]
    held, after = _flow_states(steps)
    assert held["lifecycle"] == "active" and held["stats"]["refusedTakeovers"] >= 1
    assert held["arb"]["pending"] is False
    assert any("input_arbitration.takeover_rearmed" in l for l in held["logs"])
    assert after["lifecycle"] == "off" and after["stats"]["takeovers"] == held["stats"]["takeovers"] + 1


def test_voice_activate_returns_to_bare_hands(run):
    steps = run["voice"]
    states = _evals(steps)
    before, after = states[0], states[1]
    assert before["view"]["method"] == "mouse"
    assert after["lifecycle"] == "active" and after["view"]["method"] == "bare_hands"
    assert steps[-1]["name"] == "activate" and steps[-1]["outcome"] == "applied"
    assert any(r["outcome"] == "applied" for r in run["receipts"])


def test_return_latency_measured(run):
    """Mesure consignée (D5) : du choix « Bare Hands » à `active`."""

    active = _evals(run["bare_hands"])[1]
    ms = active["stats"]["lastReturnMs"]
    print(f"\nreturn-to-bare-hands latency: {ms} ms (fake landmarker unless SELECTION_REAL_VENDOR)")
    assert 0 < ms < 15000
