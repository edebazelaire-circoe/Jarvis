"""Slice 08 inspector re-checks (real CC, real brain launch through the fake-endpoint wrapper)."""
from common import *
import urllib.request
def post(path, body):
    r = urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:17685" + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST"), timeout=60)
    return r.status
def get(path):
    return json.loads(urllib.request.urlopen("http://127.0.0.1:17685" + path, timeout=30).read())
async def wait_brain(bh=None):
    for _ in range(90):
        a = get("/api/agent")
        if a.get("state") == "running" and (bh is None or bool(a.get("barehands_tools")) == bh): return a
        await asyncio.sleep(1)
    return a
async def main():
    out = {}
    async with Page() as p:
        post("/api/agent/restart", {"new_conversation": True}); a = await wait_brain()
        out["agent"] = {k: a.get(k) for k in ("state", "display_tools", "console_tools", "barehands_tools")}
        await fresh(p)
        # 1. compact view + scene tab + detail scene_update_many
        await p.click("#openMcpInspector"); await asyncio.sleep(0.4); await wait_idle(p)
        out["open_focus"] = await p.active(); out["head"] = json.loads(await p.ev(HEAD)); out["servers"] = json.loads(await p.ev(SERVERS)); out["tabs"] = json.loads(await p.ev(TABS))
        await p.ev("document.activeElement.blur()"); await p.shot(SH + "i1-compact-general.png")
        await p.click("#mcpi-tab-scene"); await asyncio.sleep(0.3)
        out["scene_rows"] = json.loads(await p.ev(ROWS))
        await p.ev("document.activeElement.blur()"); await p.shot(SH + "i2-compact-scene.png")
        idx = [r["wire"] for r in out["scene_rows"]].index("scene_update_many")
        await p.click(f"#mcpiPanel .mcpi-row:nth-of-type({idx+1}) .mcpi-toggle") if False else await p.ev(f"document.querySelectorAll('#mcpiPanel .mcpi-row')[{idx}].querySelector('button').click()")
        await asyncio.sleep(0.5); await wait_idle(p)
        out["sum_detail"] = await p.ev("(()=>{const d=document.querySelector('#mcpiPanel .mcpi-row.is-open .mcpi-detail');return d?d.innerText.slice(0,3000):null})()")
        await p.shot(SH + "i3-detail-scene_update_many.png")
        # 2. focus kept on a row toggle while its descriptor loads (background re-render)
        await p.ev("JarvisMcpInspector.state.details={}") if False else None
        await p.click("#mcpiRefresh"); await asyncio.sleep(0.1)
        await p.ev(f"document.querySelectorAll('#mcpiPanel .mcpi-row')[1].querySelector('button').focus()")
        f = []
        for _ in range(20):
            f.append(await p.ev("(()=>{const e=document.activeElement;return e?(e.id||e.className||e.tagName):null})()")); await asyncio.sleep(0.1)
        out["focus_during_refresh"] = f
        # 3. focus kept in the search box during background indexing (first search loads every descriptor)
        await p.key("/"); await asyncio.sleep(0.05); await p.type("radius")
        g = []
        for _ in range(30):
            g.append(await p.ev("(()=>{const e=document.activeElement;return [e&&e.id, !!(window.JarvisMcpInspector&&JarvisMcpInspector.state.loading), (document.getElementById('mcpiStatus')||{}).textContent]})()")); await asyncio.sleep(0.1)
        out["focus_during_indexing"] = g
        await wait_idle(p); out["search_result_rows"] = json.loads(await p.ev(ROWS)); out["search_tabs"] = json.loads(await p.ev(TABS))
        await p.ev("document.activeElement.blur()"); await p.shot(SH + "i4-search-radius.png")
        # 4. Escape with focus on <body>
        await p.ev("(()=>{const s=document.getElementById('mcpiSearch');if(s){s.value='';s.dispatchEvent(new Event('input',{bubbles:true}))}})()"); await asyncio.sleep(0.3)
        await p.ev("document.activeElement.blur()")
        out["before_esc_active"] = await p.active()
        await p.key("Escape"); await asyncio.sleep(0.3)
        out["esc_on_body"] = {"hidden": await p.ev("document.getElementById('mcpInspector').hidden"), "active": await p.active()}
        # 5. reopen refreshes availability after a brain restart (Bare Hands on)
        n0 = len(reqs(p.events))
        post("/api/barehands", {"enabled": True}); await asyncio.sleep(1)
        await p.click("#openMcpInspector"); await asyncio.sleep(0.5); await wait_idle(p)
        out["after_bh_on"] = {"head": json.loads(await p.ev(HEAD)), "servers": json.loads(await p.ev(SERVERS))}
        await p.ev("document.activeElement.blur()"); await p.shot(SH + "i5-pending-restart.png")
        await p.key("Escape"); await asyncio.sleep(0.3)
        post("/api/agent/restart", {"new_conversation": True}); a = await wait_brain(bh=True)
        out["agent_after_restart"] = {k: a.get(k) for k in ("state", "display_tools", "console_tools", "barehands_tools")}
        await p.click("#openMcpInspector"); await asyncio.sleep(0.6); await wait_idle(p)
        out["reopen_after_restart"] = {"head": json.loads(await p.ev(HEAD)), "servers": json.loads(await p.ev(SERVERS)), "new_mcp_GETs": reqs(p.events)[n0:]}
        await p.ev("document.activeElement.blur()"); await p.shot(SH + "i6-reopen-after-restart.png")
        await p.key("Escape"); await asyncio.sleep(0.3)
        # 6. 360 px
        await p.size(360, 740); await asyncio.sleep(0.5)
        await p.click("#openMcpInspector"); await asyncio.sleep(0.5); await wait_idle(p)
        await p.click("#mcpi-tab-scene"); await asyncio.sleep(0.3)
        out["narrow_list"] = await p.ev("JSON.stringify({sw:document.documentElement.scrollWidth,cw:document.documentElement.clientWidth,dlg:document.getElementById('mcpInspector').getBoundingClientRect().width})")
        await p.ev("document.activeElement.blur()"); await p.shot(SH + "i7-360-list.png")
        await p.ev(f"document.querySelectorAll('#mcpiPanel .mcpi-row')[{idx}].querySelector('button').click()"); await asyncio.sleep(0.5); await wait_idle(p)
        out["narrow_detail"] = await p.ev("JSON.stringify({sw:document.documentElement.scrollWidth,cw:document.documentElement.clientWidth,over:[...document.querySelectorAll('#mcpInspector *')].filter(e=>e.getBoundingClientRect().right>361&&getComputedStyle(e).position!=='fixed').slice(0,5).map(e=>e.tagName+'.'+e.className)})")
        await p.ev("document.activeElement.blur()"); await p.shot(SH + "i8-360-detail.png")
        await p.key("Escape")
        out["errors"] = errs(p.events); out["non_get_mcp"] = [r for r in reqs(p.events) if r[0] != "GET"]
    json.dump(out, open(S7 + "/i8.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False)[:6000])
run(main())
