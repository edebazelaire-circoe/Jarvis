from common import *
import urllib.request
def post(path, body):
    r = urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:17685" + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST"), timeout=60)
    return r.status, r.read().decode()[:300]
def get(path):
    return json.loads(urllib.request.urlopen("http://127.0.0.1:17685" + path, timeout=30).read())
async def snap(p, tag):
    return {"tag": tag, "head": json.loads(await p.ev(HEAD)), "servers": json.loads(await p.ev(SERVERS)),
            "bh_rows": None}
async def main():
    async with Page() as p:
        await fresh(p)
        out = []
        await p.click("#openMcpInspector"); await asyncio.sleep(0.4); await wait_idle(p)
        await p.click("#mcpi-tab-barehands"); await asyncio.sleep(0.3)
        s = await snap(p, "brain running, BH turned on (no restart)"); s["bh_rows"] = json.loads(await p.ev(ROWS)); s["srvline"] = await p.ev("(document.querySelector('.mcpi-srvline')||{}).textContent"); out.append(s)
        await p.ev("document.activeElement.blur()"); await p.shot(SH + "06-pending-restart-banner.png")
        # restart brain like the page does
        out.append(("restart", post("/api/agent/restart", {"new_conversation": True})))
        for _ in range(60):
            a = get("/api/agent")
            if a.get("state") == "running" and a.get("barehands_tools"): break
            await asyncio.sleep(1)
        out.append(("agent after restart", {k: a.get(k) for k in ("state", "pid", "barehands_tools", "display_tools", "console_tools")}))
        out.append(await snap(p, "after restart, before Actualiser (cached)"))
        await p.click("#mcpiRefresh"); await asyncio.sleep(0.5); await wait_idle(p)
        s = await snap(p, "after restart + Actualiser"); s["bh_rows"] = json.loads(await p.ev(ROWS)); out.append(s)
        await p.ev("document.activeElement.blur()"); await p.shot(SH + "06-after-restart.png")
        # stop the brain
        out.append(("kill", post("/api/agent/kill", {})))
        await asyncio.sleep(3)
        a = get("/api/agent"); out.append(("agent after kill", {k: a.get(k) for k in ("state", "pid")}))
        await p.click("#mcpiRefresh"); await asyncio.sleep(0.5); await wait_idle(p)
        s = await snap(p, "brain stopped + Actualiser"); s["bh_rows"] = json.loads(await p.ev(ROWS)); out.append(s)
        await p.ev("document.activeElement.blur()"); await p.shot(SH + "06-brain-stopped.png")
        out.append(("api list brain stopped", [(x["server"], x["availability"]) for x in get("/api/mcp/tools")["servers"]]))
        # BH off with brain stopped -> still no pending?
        out.append(("bh off", post("/api/barehands", {"enabled": False})))
        await p.click("#mcpiRefresh"); await asyncio.sleep(0.5); await wait_idle(p)
        out.append(await snap(p, "brain stopped, BH off + Actualiser"))
        await p.key("Escape"); await asyncio.sleep(1.5)
        out.append(("pills", await p.ev("(()=>{const g=document.getElementById('bgPills');return {hidden:g.hidden,pills:[...g.querySelectorAll('button')].map(b=>[b.textContent.trim(),b.className,Math.round(b.getBoundingClientRect().x),Math.round(b.getBoundingClientRect().y)])}})()")))
        out.append(("errors", errs(p.events)))
        json.dump(out, open(S7 + "/t5.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(json.dumps(out, ensure_ascii=False, indent=1))
if __name__ == "__main__": run(main())
