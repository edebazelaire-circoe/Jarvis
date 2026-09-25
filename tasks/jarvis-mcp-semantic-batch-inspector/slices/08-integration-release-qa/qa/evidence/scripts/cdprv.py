"""Minimal CDP driver: `python cdp.py eval '<js>'` | `shot out.png` | `drag x0 y0 x1 y1 [steps] [ctrl]` | `click x y [ctrl]`."""
import asyncio, json, sys, base64, aiohttp
async def main(argv):
    async with aiohttp.ClientSession() as s:
        tabs=await (await s.get("http://127.0.0.1:9333/json")).json()
        page=[t for t in tabs if t["type"]=="page"][0]
        async with s.ws_connect(page["webSocketDebuggerUrl"],max_msg_size=0) as ws:
            n=[0]
            async def call(method,**params):
                n[0]+=1; i=n[0]
                await ws.send_json({"id":i,"method":method,"params":params})
                async for m in ws:
                    d=json.loads(m.data)
                    if d.get("id")==i:
                        if "error" in d: raise RuntimeError(d["error"])
                        return d["result"]
            cmd=argv[0]
            if cmd=="eval":
                r=await call("Runtime.evaluate",expression=argv[1],awaitPromise=True,returnByValue=True)
                print(json.dumps(r.get("result",{}).get("value", r), ensure_ascii=False, indent=1))
            elif cmd=="shot":
                r=await call("Page.captureScreenshot",format="png")
                open(argv[1],"wb").write(base64.b64decode(r["data"])); print("saved",argv[1])
            elif cmd in("dragid","clickid"):
                oid=argv[1]
                r=await call("Runtime.evaluate",expression=f"(()=>{{const e=document.querySelector('[data-object-id=\"{oid}\"]');const b=e.getBoundingClientRect();return [b.x+Math.min(30,b.width/2),b.y+b.height/2]}})()",returnByValue=True)
                x,y=r["result"]["value"]
                if cmd=="clickid":
                    argv=["click",str(x),str(y)]+argv[2:]
                else:
                    argv=["drag",str(x),str(y),str(x+float(argv[2])),str(y+float(argv[3]))]+argv[4:]
                cmd=argv[0]
            if cmd in("drag","click"):
                mod=2 if "ctrl" in argv else 0
                if cmd=="click":
                    x,y=float(argv[1]),float(argv[2])
                    for t in("mousePressed","mouseReleased"):
                        await call("Input.dispatchMouseEvent",type=t,x=x,y=y,button="left",buttons=1 if t=="mousePressed" else 0,clickCount=1,modifiers=mod)
                    print("clicked"); return
                x0,y0,x1,y1=map(float,argv[1:5]); steps=int(argv[5]) if len(argv)>5 and argv[5].isdigit() else 12
                hold=float(argv[argv.index("hold")+1]) if "hold" in argv else 0
                pre=argv[argv.index("pre")+1] if "pre" in argv else None
                await call("Input.dispatchMouseEvent",type="mouseMoved",x=x0,y=y0)
                await call("Input.dispatchMouseEvent",type="mousePressed",x=x0,y=y0,button="left",buttons=1,clickCount=1)
                for k in range(1,steps+1):
                    await call("Input.dispatchMouseEvent",type="mouseMoved",x=x0+(x1-x0)*k/steps,y=y0+(y1-y0)*k/steps,button="left",buttons=1)
                    await asyncio.sleep(0.03)
                if pre:
                    p=await asyncio.create_subprocess_shell(pre); await p.wait()
                if hold: await asyncio.sleep(hold)
                await call("Input.dispatchMouseEvent",type="mouseReleased",x=x1,y=y1,button="left",buttons=0,clickCount=1)
                print("dragged")
            elif cmd=="setup":
                await call("Emulation.setDeviceMetricsOverride",width=1280,height=720,deviceScaleFactor=1,mobile=False)
                print("ok")
asyncio.run(main(sys.argv[1:]))
