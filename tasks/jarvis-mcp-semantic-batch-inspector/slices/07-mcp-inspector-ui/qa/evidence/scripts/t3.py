from common import *
async def main():
    async with Page() as p:
        await fresh(p)
        steps = []
        async def rec(label):
            a = await p.active(); steps.append((label, a)); print(label, "=>", json.dumps(a, ensure_ascii=False))
        await p.ev("document.getElementById('openMcpInspector').focus()"); await rec("focus MCP button")
        await p.key("Enter"); await asyncio.sleep(0.5); await wait_idle(p); await asyncio.sleep(0.2); await rec("Enter on MCP")
        for i in range(12):
            await p.key("Tab"); await asyncio.sleep(0.1); a = await p.active(); await rec(f"Tab #{i+1}")
            if a and a.get("role") == "tab": break
        await p.key("ArrowRight"); await asyncio.sleep(0.2); await rec("ArrowRight")
        await p.key("ArrowRight"); await asyncio.sleep(0.2); await rec("ArrowRight")
        await p.key("ArrowLeft"); await asyncio.sleep(0.2); await rec("ArrowLeft")
        await p.key("End"); await asyncio.sleep(0.2); await rec("End")
        await p.key("Home"); await asyncio.sleep(0.2); await rec("Home")
        await p.key("ArrowRight"); await asyncio.sleep(0.2); await rec("ArrowRight (to scene)")
        for i in range(6):
            await p.key("Tab"); await asyncio.sleep(0.1); a = await p.active(); await rec(f"Tab into list #{i+1}")
            if a and "mcpi-toggle" in (a.get("cls") or ""): break
        await p.key("ArrowDown"); await asyncio.sleep(0.1); await rec("ArrowDown")
        await p.key("ArrowDown"); await asyncio.sleep(0.1); await rec("ArrowDown")
        await p.key("ArrowUp"); await asyncio.sleep(0.1); await rec("ArrowUp")
        await p.key("Enter"); await asyncio.sleep(0.4); await wait_idle(p); await rec("Enter (expand)")
        steps.append(("detail rendered", await p.ev("!!document.querySelector('#mcpiPanel .mcpi-row.is-open .mcpi-detail .mcpi-facts')")))
        await p.ev("0"); await p.shot(SH + "08-keyboard-expanded.png")
        await p.key("/"); await asyncio.sleep(0.1); await rec("/ (focus search)")
        await p.key("Tab", shift=True); await asyncio.sleep(0.1); await rec("Shift+Tab from search (trap wraps?)")
        await p.key("Escape"); await asyncio.sleep(0.3); await rec("Escape")
        steps.append(("dialog hidden", await p.ev("document.getElementById('mcpInspector').hidden")))
        steps.append(("errors", errs(p.events)))
        json.dump(steps, open(S7 + "/t3.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
run(main())
