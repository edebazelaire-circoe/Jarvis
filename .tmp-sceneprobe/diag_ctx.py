"""Diagnostic: un clic droit CDP produit-il un evenement `contextmenu` ?"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sceneprobe import Chrome, boot, NODE_BOXES, UI  # noqa: E402

c = Chrome(1600, 900)
try:
    boot(c)
    c.js("window.__ctx=[];document.addEventListener('contextmenu',"
         "e=>window.__ctx.push({t:e.target.tagName,c:(e.target.className||'').toString().slice(0,40)}),true);")
    boxes = c.js(NODE_BOXES)
    boxes.sort(key=lambda b: abs(b["cx"] - 800) + abs(b["cy"] - 450))
    s = boxes[0]
    c.mouse("mouseMoved", s["cx"], s["cy"])
    c.send("Input.dispatchMouseEvent", type="mousePressed", x=float(s["cx"]), y=float(s["cy"]),
           button="right", buttons=2, clickCount=1)
    time.sleep(0.15)
    c.send("Input.dispatchMouseEvent", type="mouseReleased", x=float(s["cx"]), y=float(s["cy"]),
           button="right", buttons=0, clickCount=1)
    time.sleep(0.5)
    out = {
        "star": s["id"],
        "contextmenu_events": c.js("window.__ctx"),
        "menu_hidden": c.js("document.getElementById('ctxMenu').hidden"),
        "menu_html_len": c.js("document.getElementById('ctxMenu').innerHTML.length"),
        "elem_at_star": c.js("(()=>{const e=document.elementFromPoint(%f,%f);"
                             "return e?{tag:e.tagName,cls:(e.className||'').toString().slice(0,50),"
                             "oid:e.dataset?e.dataset.objectId:null}:null})()" % (s["cx"], s["cy"])),
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
finally:
    c.stop()
