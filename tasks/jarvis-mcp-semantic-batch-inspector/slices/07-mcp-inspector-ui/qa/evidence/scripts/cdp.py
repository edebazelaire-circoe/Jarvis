"""Minimal CDP client over aiohttp for QA (no product code)."""
import asyncio, base64, json, sys
import aiohttp

DBG = "http://127.0.0.1:9333"
KEYS = {"ArrowLeft": 37, "ArrowUp": 38, "ArrowRight": 39, "ArrowDown": 40, "Enter": 13, "Escape": 27,
        "Tab": 9, "Home": 36, "End": 35, " ": 32, "/": 191}


class Page:
    def __init__(self):
        self.i = 0; self.pending = {}; self.events = []

    async def __aenter__(self):
        self.s = aiohttp.ClientSession()
        async with self.s.get(DBG + "/json") as r:
            ts = [t for t in await r.json() if t["type"] == "page"]
        self.ws = await self.s.ws_connect(ts[0]["webSocketDebuggerUrl"], max_msg_size=0)
        self.task = asyncio.create_task(self._loop())
        return self

    async def __aexit__(self, *a):
        self.task.cancel(); await self.ws.close(); await self.s.close()

    async def _loop(self):
        async for m in self.ws:
            d = json.loads(m.data)
            if "id" in d and d["id"] in self.pending:
                self.pending.pop(d["id"]).set_result(d)
            elif "method" in d:
                self.events.append(d)

    async def send(self, method, params=None):
        self.i += 1; f = asyncio.get_event_loop().create_future(); self.pending[self.i] = f
        await self.ws.send_str(json.dumps({"id": self.i, "method": method, "params": params or {}}))
        d = await asyncio.wait_for(f, 60)
        if "error" in d: raise RuntimeError(f"{method}: {d['error']}")
        return d["result"]

    async def ev(self, expr):
        r = await self.send("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True})
        if "exceptionDetails" in r: raise RuntimeError(json.dumps(r["exceptionDetails"])[:800])
        return r["result"].get("value")

    async def size(self, w, h, mobile=False):
        await self.send("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": mobile})

    async def shot(self, path, full=False):
        p = {"format": "png"}
        if full: p["captureBeyondViewport"] = True
        r = await self.send("Page.captureScreenshot", p)
        open(path, "wb").write(base64.b64decode(r["data"]))

    async def key(self, k, shift=False):
        code = KEYS.get(k, 0)
        base = {"key": k, "windowsVirtualKeyCode": code, "nativeVirtualKeyCode": code,
                "code": {"/": "Slash", " ": "Space"}.get(k, k), "modifiers": 8 if shift else 0}
        text = {"Enter": "\r", "/": "/", " ": " "}.get(k)
        await self.send("Input.dispatchKeyEvent", {"type": "keyDown" if text else "rawKeyDown", **base, **({"text": text} if text else {})})
        await self.send("Input.dispatchKeyEvent", {"type": "keyUp", **base})

    async def type(self, s):
        await self.send("Input.insertText", {"text": s})

    async def click(self, sel):
        r = await self.ev(f"(()=>{{const e=document.querySelector({json.dumps(sel)});if(!e)return null;e.scrollIntoView({{block:'nearest'}});const b=e.getBoundingClientRect();return [b.x+b.width/2,b.y+b.height/2]}})()")
        if not r: raise RuntimeError("no element " + sel)
        for t in ("mousePressed", "mouseReleased"):
            await self.send("Input.dispatchMouseEvent", {"type": t, "x": r[0], "y": r[1], "button": "left", "clickCount": 1})

    async def active(self):
        return await self.ev("""(()=>{const e=document.activeElement;if(!e)return null;
          return {tag:e.tagName,id:e.id||null,role:e.getAttribute('role'),cls:e.className&&String(e.className).slice(0,60),
          text:(e.getAttribute('aria-label')||e.textContent||'').trim().replace(/\\s+/g,' ').slice(0,70),
          expanded:e.getAttribute('aria-expanded'),selected:e.getAttribute('aria-selected')}})()""")


def run(coro):
    asyncio.run(coro)
