#!/usr/bin/env python3
"""sceneprobe.py -- banc de mesure REEL de l'interaction de la scene constellation.

Pilote le VRAI Control Center (http://127.0.0.1:17654) dans un Chrome headless
via CDP, en envoyant de VRAIS evenements souris (Input.dispatchMouseEvent), et
sort des NOMBRES lus sur la page: combien d'etoiles portent `.sc-selected`, si
un `.sc-band` a bien ete dessine, la geometrie avant/apres un glisser.

  python sceneprobe.py band
  python sceneprobe.py menu
  python sceneprobe.py drag-edge

Imprime un objet JSON sur stdout.
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
UI = os.getenv("JARVIS_UI_URL", "http://127.0.0.1:17654/")

from websockets.sync.client import connect as ws_connect  # noqa: E402


# ------------------------------------------------------------------ chrome
def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Chrome:
    def __init__(self, width=1600, height=900):
        self.port = free_port()
        self.profile = Path(tempfile.mkdtemp(prefix="sceneprobe-"))
        self.width, self.height = width, height
        self.proc = None
        self.ws = None
        self._id = 0

    def start(self, url):
        cmd = [CHROME, "--headless=new", "--disable-gpu",
               "--remote-debugging-port=%d" % self.port,
               "--user-data-dir=" + str(self.profile),
               "--window-size=%d,%d" % (self.width, self.height),
               "--force-device-scale-factor=1",
               "--hide-scrollbars", "--no-first-run",
               "--no-default-browser-check", "--disable-extensions",
               "--disable-background-timer-throttling",
               "--disable-renderer-backgrounding",
               "--disable-backgrounding-occluded-windows",
               url]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        target = None
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                        "http://127.0.0.1:%d/json/list" % self.port, timeout=2) as r:
                    for t in json.loads(r.read().decode()):
                        if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                            target = t
                            break
                if target:
                    break
            except Exception:
                pass
            time.sleep(0.25)
        if not target:
            raise RuntimeError("chrome n'a pas ouvert de cible page")
        self.ws = ws_connect(target["webSocketDebuggerUrl"],
                             max_size=64 * 1024 * 1024, open_timeout=20)
        self.send("Page.enable")
        self.send("Runtime.enable")
        return target

    def send(self, method, **params):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv(timeout=30))
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError("%s: %s" % (method, msg["error"]))
                return msg.get("result", {})

    def js(self, expr):
        r = self.send("Runtime.evaluate", expression=expr,
                      returnByValue=True, awaitPromise=True)
        if r.get("exceptionDetails"):
            raise RuntimeError("JS: %s" % json.dumps(r["exceptionDetails"])[:400])
        return r.get("result", {}).get("value")

    # --- vraie souris, au niveau du navigateur (evenements de confiance) ---
    def mouse(self, kind, x, y, buttons=0, clicks=0, button="none"):
        self.send("Input.dispatchMouseEvent", type=kind, x=float(x), y=float(y),
                  button=button, buttons=buttons, clickCount=clicks)

    def drag(self, x0, y0, x1, y1, steps=14, settle=0.012, mid_probe=None):
        out = {}
        self.mouse("mouseMoved", x0, y0)
        self.mouse("mousePressed", x0, y0, buttons=1, clicks=1, button="left")
        time.sleep(settle)
        for i in range(1, steps + 1):
            x = x0 + (x1 - x0) * i / steps
            y = y0 + (y1 - y0) * i / steps
            self.mouse("mouseMoved", x, y, buttons=1, button="left")
            time.sleep(settle)
            if mid_probe and i == steps // 2:
                out["mid"] = self.js(mid_probe)
        self.mouse("mouseReleased", x1, y1, buttons=0, clicks=1, button="left")
        time.sleep(0.25)
        return out

    def shot(self, png):
        r = self.send("Page.captureScreenshot", format="png")
        import base64
        Path(png).write_bytes(base64.b64decode(r["data"]))
        return png

    def stop(self):
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass
        try:
            if self.proc:
                self.proc.terminate()
                self.proc.wait(timeout=10)
        except Exception:
            pass
        shutil.rmtree(self.profile, ignore_errors=True)


# ------------------------------------------------------------------ page
WAIT_NODES = """(async()=>{
  for(let i=0;i<120;i++){
    const n=document.querySelectorAll('#sceneLayer .sc-node').length;
    if(n>0)return n;
    await new Promise(r=>setTimeout(r,250));
  }
  return 0;
})()"""

# Boites DESSINEES de toutes les etoiles, en pixels de fenetre.
NODE_BOXES = """(()=>{
  const out=[];
  for(const el of document.querySelectorAll('#sceneLayer .sc-node')){
    const r=el.getBoundingClientRect();
    if(!r.width&&!r.height)continue;
    out.push({id:el.dataset.objectId,left:r.left,top:r.top,w:r.width,h:r.height,
      cls:el.className,
      cx:r.left+r.width/2,cy:r.top+r.height/2});
  }
  return out;
})()"""

SELECTED = """(()=>{
  const ids=[...document.querySelectorAll('#sceneLayer .sc-node.sc-selected')]
    .map(e=>e.dataset.objectId);
  return {count:ids.length, ids:ids.slice(0,40)};
})()"""

BAND_SEEN = """(()=>{
  const b=document.querySelector('#sceneLayer .sc-band');
  if(!b)return {band:false};
  const r=b.getBoundingClientRect();
  return {band:true,w:Math.round(r.width),h:Math.round(r.height)};
})()"""


FRESH_POINT = """(()=>{
  const e=document.querySelector('#sceneLayer .sc-node[data-object-id=%s]');
  if(!e)return null;
  const r=e.getBoundingClientRect();
  const x=r.left+r.width/2, y=r.top+r.height/2;
  const hit=document.elementFromPoint(x,y);
  const node=hit&&hit.closest?hit.closest('#sceneLayer .sc-node'):null;
  return {x,y,w:r.width,h:r.height,
          on_target: !!node && node.dataset.objectId===%s};
})()"""


def point_on(chrome, object_id, tries=8):
    """Le centre ACTUEL d'une etoile, verifie par `elementFromPoint` : le champ
    tourne, une position lue il y a 200 ms n'est plus la bonne."""
    q = json.dumps(object_id)
    for _ in range(tries):
        p = chrome.js(FRESH_POINT % (q, q))
        if p and p["on_target"]:
            return p
        time.sleep(0.05)
    return p


def boot(chrome):
    chrome.start(UI)
    n = chrome.js(WAIT_NODES)
    if not n:
        raise RuntimeError("aucune etoile dessinee dans la page")
    # laisse le champ se poser (animations d'entree)
    time.sleep(2.0)
    return n


# --------------------------------------------------------------- scenarios
def pick_band_rect(boxes, want=3):
    """Un rectangle du VIDE qui englobe au moins `want` etoiles, sans partir
    d'une etoile (sinon c'est un deplacement, pas une selection)."""
    xs = sorted(boxes, key=lambda b: b["cx"])
    for i in range(len(xs) - want + 1):
        grp = xs[i:i + want]
        l = min(b["left"] for b in grp) - 30
        r = max(b["left"] + b["w"] for b in grp) + 30
        t = min(b["top"] for b in grp) - 30
        bo = max(b["top"] + b["h"] for b in grp) + 30
        if l < 10 or t < 10:
            continue
        # le point de depart doit etre dans le vide
        start = (l, t)
        if any(b["left"] <= start[0] <= b["left"] + b["w"]
               and b["top"] <= start[1] <= b["top"] + b["h"] for b in boxes):
            continue
        return {"x0": l, "y0": t, "x1": r, "y1": bo,
                "expect": [b["id"] for b in grp]}
    return None


def scenario_band(chrome):
    n = boot(chrome)
    boxes = chrome.js(NODE_BOXES)
    rect = pick_band_rect(boxes, want=3)
    if not rect:
        return {"ok": False, "why": "pas de rectangle vide trouve",
                "nodes": n}
    before = chrome.js(SELECTED)
    # Ce que l'element sous le point d'appui est VRAIMENT:
    under = chrome.js(
        "(()=>{const e=document.elementFromPoint(%f,%f);"
        "return e?{tag:e.tagName,id:e.id,cls:e.className&&e.className.toString().slice(0,60)}:null})()"
        % (rect["x0"], rect["y0"]))
    got = chrome.drag(rect["x0"], rect["y0"], rect["x1"], rect["y1"],
                      steps=16, mid_probe=BAND_SEEN)
    after = chrome.js(SELECTED)
    chrome.shot(str(ROOT / "band.png"))
    # Le groupe tracé au rectangle se déplace-t-il d'un bloc ?
    moved = group_move(chrome, after["ids"][0]) if after["count"] >= 2 else None
    return {"ok": after["count"] >= 2 and bool(moved and moved["ok"]),
            "group_move": moved,
            "nodes": n, "rect": rect,
            "element_under_press": under,
            "band_drawn_mid_drag": got.get("mid"),
            "selected_before": before["count"],
            "selected_after": after["count"],
            "selected_ids": after["ids"],
            "expected_at_least": len(rect["expect"]),
            "shot": str(ROOT / "band.png")}


MENU_ITEMS = """(()=>{
  const m=document.getElementById('ctxMenu');
  if(!m||m.hidden)return {open:false,items:[]};
  const items=[...m.querySelectorAll('[role="menuitem"]')]
    .map(b=>({act:b.dataset.act,label:(b.textContent||'').trim()}));
  return {open:true,items};
})()"""


# La selection qui fait foi est celle que la page declare
# (`JarvisScene.inspect().selection`), pas la classe CSS : un rendu peut
# recreer les noeuds pendant le geste.
POS_OF = """(ids=>{
  const o={};
  for(const id of ids){
    const e=document.querySelector('#sceneLayer .sc-node[data-object-id="'+
      (window.CSS&&CSS.escape?CSS.escape(id):id)+'"]');
    if(!e)continue;
    const r=e.getBoundingClientRect();
    o[id]=[Math.round(r.left),Math.round(r.top)];}
  const ins=window.JarvisScene&&window.JarvisScene.inspect?window.JarvisScene.inspect():null;
  return {sel:(ins&&ins.selection)||[],pos:o}})(%s)"""

SELECTED_POS = """(()=>{
  const ins=window.JarvisScene&&window.JarvisScene.inspect?window.JarvisScene.inspect():null;
  const ids=(ins&&ins.selection)||[];
  const o={};
  for(const id of ids){
    const e=document.querySelector('#sceneLayer .sc-node[data-object-id="'+
      (window.CSS&&CSS.escape?CSS.escape(id):id)+'"]');
    if(!e)continue;
    const r=e.getBoundingClientRect();
    o[id]=[Math.round(r.left),Math.round(r.top)];}
  return {sel:ids,pos:o}})()"""


def group_move(chrome, anchor_id, dx=-120, dy=-70):
    """Attrape une etoile de la selection et regarde si TOUTE la selection suit.
    On mesure en plein vol, puis on revient au point de depart avant de lacher :
    le deplacement net est nul, la scene reelle de l'utilisateur est rendue
    telle quelle."""
    p = point_on(chrome, anchor_id)
    if not p or not p["on_target"]:
        return {"ok": False, "why": "ancre introuvable"}
    snap0 = chrome.js(SELECTED_POS)
    before = snap0["pos"]
    x0, y0 = p["x"], p["y"]
    chrome.mouse("mouseMoved", x0, y0)
    chrome.mouse("mousePressed", x0, y0, buttons=1, clicks=1, button="left")
    time.sleep(0.02)
    for i in range(1, 13):
        chrome.mouse("mouseMoved", x0 + dx * i / 12, y0 + dy * i / 12,
                     buttons=1, button="left")
        time.sleep(0.015)
    # On suit les MEMES objets qu'au depart, pas la selection courante : si la
    # selection se defait pendant le geste, il faut le voir, pas le perdre.
    snap1 = chrome.js(POS_OF % json.dumps(list(before.keys())))
    during = snap1["pos"]
    # retour au point de depart : on ne laisse pas la scene deplacee
    for i in range(12, -1, -1):
        chrome.mouse("mouseMoved", x0 + dx * i / 12, y0 + dy * i / 12,
                     buttons=1, button="left")
        time.sleep(0.015)
    chrome.mouse("mouseReleased", x0, y0, buttons=0, clicks=1, button="left")
    time.sleep(0.3)
    moved, still = [], []
    for oid, (bx, by) in before.items():
        if oid not in during:
            continue
        ax, ay = during[oid]
        (moved if abs(ax - bx) > 20 or abs(ay - by) > 20 else still).append(oid)
    return {"ok": len(moved) >= 2 and not still,
            "dragged_by_px": [dx, dy],
            "selection_before": snap0["sel"], "selection_during": snap1["sel"],
            "measured": len(before),
            "followed": len(moved), "stayed_behind": len(still),
            "stayed_ids": still[:6],
            "returned_to_origin": True}


def scenario_menu(chrome):
    n = boot(chrome)
    boxes = chrome.js(NODE_BOXES)
    # une etoile qui a des voisins: on prend la plus centrale
    boxes.sort(key=lambda b: abs(b["cx"] - chrome.width / 2) + abs(b["cy"] - chrome.height / 2))
    star = boxes[0]
    chrome.js("window.__ctx=[];document.addEventListener('contextmenu',"
              "e=>window.__ctx.push({t:e.target.tagName,"
              "c:(e.target.className||'').toString().slice(0,40)}),true);")
    # Les etoiles derivent en permanence (le champ respire) : un clic peut
    # tomber a cote. On recommence, comme le ferait l'utilisateur.
    menu = {"open": False, "items": []}
    for attempt in range(6):
        p = point_on(chrome, star["id"])
        if not p:
            break
        star["cx"], star["cy"] = p["x"], p["y"]
        chrome.mouse("mouseMoved", p["x"], p["y"])
        chrome.send("Input.dispatchMouseEvent", type="mousePressed",
                    x=float(p["x"]), y=float(p["y"]),
                    button="right", buttons=2, clickCount=1)
        time.sleep(0.12)
        chrome.send("Input.dispatchMouseEvent", type="mouseReleased",
                    x=float(p["x"]), y=float(p["y"]),
                    button="right", buttons=0, clickCount=1)
        time.sleep(0.45)
        menu = chrome.js(MENU_ITEMS)
        if menu["open"]:
            break
    acts = [i["act"] for i in menu["items"]]
    out = {"nodes": n, "star": star["id"], "menu_open": menu["open"],
           "contextmenu_events": chrome.js("window.__ctx"),
           "menu_html_len": chrome.js("document.getElementById('ctxMenu').innerHTML.length"),
           "elem_at_star": chrome.js(
               "(()=>{const e=document.elementFromPoint(%f,%f);return e?{tag:e.tagName,"
               "cls:(e.className||'').toString().slice(0,50)}:null})()"
               % (star["cx"], star["cy"])),
           "acts": acts,
           "has_constellation": any(
               a and "constellation" in a for a in acts)}
    if out["has_constellation"]:
        before = chrome.js(SELECTED)
        chrome.js("document.querySelector('#ctxMenu [data-act=\"select-constellation\"]').click()")
        time.sleep(0.4)
        after = chrome.js(SELECTED)
        out["selected_before"] = before["count"]
        out["selected_after"] = after["count"]
        out["selected_ids"] = after["ids"]
        out["group_move"] = group_move(chrome, star["id"])
    chrome.shot(str(ROOT / "menu.png"))
    out["shot"] = str(ROOT / "menu.png")
    out["ok"] = bool(out["has_constellation"]
                     and out.get("selected_after", 0) > 1
                     and out.get("group_move", {}).get("ok"))
    return out


SET_ORBIT = """(on=>{
  const V=window.JarvisSceneView;
  if(!V)return false;
  let held=null;
  try{held=V.decode(localStorage.getItem(V.KEY))}catch(e){held=null}
  localStorage.setItem(V.KEY, V.encode(Object.assign({}, held||{}, {orbit:on})));
  return true;})(%s)"""


def set_gravitation(chrome, on):
    """La gravitation est un REGLAGE de l'utilisateur (Réglages → Gravitation).
    Champ allumé, la place dessinée est une orbite : elle n'est pas la
    géométrie rangée. Éteint, l'objet est dessiné là où il est rangé."""
    ok = chrome.js(SET_ORBIT % ("true" if on else "false"))
    chrome.send("Page.reload")
    time.sleep(1.0)
    boot(chrome)
    return ok


def scenario_drag_edge(chrome, orbit=None):
    """Prend l'etoile la plus a droite et la traine vers le bord droit de la
    fenetre. Mesure: combien de pixels restent entre elle et le bord."""
    n = boot(chrome)
    if orbit is not None:
        set_gravitation(chrome, orbit)
        n = chrome.js("document.querySelectorAll('#sceneLayer .sc-node').length")
    boxes = chrome.js(NODE_BOXES)
    # Une VRAIE etoile (agent/job), pas un signal ni un artefact : la place
    # d'un signal est derivee de son etoile, la trainer ne mesure rien.
    stars = [b for b in boxes
             if ("sc-kind-agent" in b["cls"] or "sc-kind-job" in b["cls"])
             and "!" not in b["id"]]
    if not stars:
        return {"ok": False, "why": "aucune etoile agent/job dessinee"}
    stars.sort(key=lambda b: -b["cx"])
    star = stars[0]
    p = point_on(chrome, star["id"])
    geo_before = {"left": p["x"] - p["w"] / 2, "top": p["y"] - p["h"] / 2,
                  "w": p["w"], "h": p["h"], "on_target": p["on_target"]}
    target_x = chrome.width - 2
    chrome.drag(p["x"], p["y"], target_x, p["y"], steps=24)
    geo_after = chrome.js(
        "(()=>{const e=document.querySelector('#sceneLayer .sc-node[data-object-id=%s]');"
        "if(!e)return null;const r=e.getBoundingClientRect();"
        "return {left:r.left,top:r.top,w:r.width,h:r.height}})()"
        % json.dumps(star["id"]))
    chrome.shot(str(ROOT / "edge.png"))
    gap = None
    if geo_after:
        gap = round(chrome.width - (geo_after["left"] + geo_after["w"]), 1)
    return {"nodes": n, "star": star["id"], "window_w": chrome.width,
            "gravitation": orbit,
            "before": geo_before, "after": geo_after,
            "gap_to_right_edge_px": gap,
            "ok": gap is not None and gap <= 2,
            "shot": str(ROOT / "edge.png")}


SCENARIOS = {"band": scenario_band, "menu": scenario_menu,
             "drag-edge": scenario_drag_edge,
             "drag-edge-grav-off": lambda c: scenario_drag_edge(c, orbit=False),
             "drag-edge-grav-on": lambda c: scenario_drag_edge(c, orbit=True)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices=sorted(SCENARIOS))
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    chrome = Chrome(args.width, args.height)
    t0 = time.time()
    try:
        res = SCENARIOS[args.scenario](chrome)
    except Exception as exc:
        res = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    finally:
        chrome.stop()
    res["scenario"] = args.scenario
    res["label"] = args.label
    res["secs"] = round(time.time() - t0, 2)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
