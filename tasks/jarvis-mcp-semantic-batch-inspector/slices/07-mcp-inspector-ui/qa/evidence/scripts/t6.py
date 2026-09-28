from common import *
from t5 import post, get
async def main():
    async with Page() as p:
        out = []
        out.append(("start brain", post("/api/agent/restart", {"new_conversation": True})[0]))
        for _ in range(60):
            if get("/api/agent").get("state") == "running": break
            await asyncio.sleep(1)
        await fresh(p)
        out.append(("bh on", post("/api/barehands", {"enabled": True})[0]))
        await p.click("#openMcpInspector"); await asyncio.sleep(0.4); await wait_idle(p)
        out.append(("open 1 notice", json.loads(await p.ev(HEAD))))
        await p.key("Escape"); await asyncio.sleep(0.3)
        n0 = len(reqs(p.events))
        out.append(("restart", post("/api/agent/restart", {"new_conversation": True})[0]))
        for _ in range(60):
            a = get("/api/agent")
            if a.get("state") == "running" and a.get("barehands_tools"): break
            await asyncio.sleep(1)
        out.append(("api after restart", [(x["server"], x["availability"]["state"], x["availability"]["pending_restart"]) for x in get("/api/mcp/tools")["servers"]]))
        await p.click("#openMcpInspector"); await asyncio.sleep(0.6); await wait_idle(p)
        out.append(("reopen after restart: notice", json.loads(await p.ev(HEAD)), "new /api/mcp GETs on reopen", reqs(p.events)[n0:]))
        await p.ev("document.activeElement.blur()"); await p.shot(SH + "06-reopen-after-restart-stale.png")
        await p.key("Escape")
        json.dump(out, open(S7 + "/t6.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(json.dumps(out, ensure_ascii=False))
run(main())
