"""usage: cdp.py nav URL | eval JS | shot FILE"""
import asyncio, base64, json, sys, urllib.request
import aiohttp
PORT = 9333
async def main():
    targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
    page = next(t for t in targets if t["type"] == "page")
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect(page["webSocketDebuggerUrl"], max_msg_size=0) as ws:
            n = 0
            async def call(method, **params):
                nonlocal n; n += 1; mid = n
                await ws.send_json({"id": mid, "method": method, "params": params})
                async for msg in ws:
                    d = json.loads(msg.data)
                    if d.get("id") == mid:
                        if "error" in d: raise SystemExit(d["error"])
                        return d["result"]
            op, arg = sys.argv[1], sys.argv[2]
            if op == "nav":
                await call("Emulation.setDeviceMetricsOverride", width=1280, height=720, deviceScaleFactor=1, mobile=False)
                await call("Page.navigate", url=arg)
                await asyncio.sleep(4)
            elif op == "eval":
                r = await call("Runtime.evaluate", expression=arg, returnByValue=True, awaitPromise=True)
                print(json.dumps(r.get("result", {}).get("value", r), ensure_ascii=False))
            elif op == "shot":
                r = await call("Page.captureScreenshot", format="png")
                open(arg, "wb").write(base64.b64decode(r["data"])); print("saved", arg)
asyncio.run(main())
