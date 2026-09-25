from common import *
STATE = """JSON.stringify({panel:document.getElementById('panel').classList.contains('open')?document.getElementById('panelTitle').textContent:null,
 overlay:getComputedStyle(document.getElementById('overlay')).display!=='none'&&document.getElementById('overlay').classList.contains('open'),
 overlayVis:getComputedStyle(document.getElementById('overlay')).visibility+'/'+getComputedStyle(document.getElementById('overlay')).opacity+'/'+getComputedStyle(document.getElementById('overlay')).display,
 timeline:!document.getElementById('timeline').hidden, testlab:!document.getElementById('testlab').hidden, mcp:!document.getElementById('mcpInspector').hidden})"""
async def main():
    async with Page() as p:
        await fresh(p)
        res = {}
        res["dock_geom"] = await p.ev("[...document.querySelectorAll('.dock button')].map(b=>{const r=b.getBoundingClientRect(),c=getComputedStyle(b);return [b.textContent.trim(),Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height),c.borderRadius,c.borderColor,c.backgroundColor,c.color,c.fontSize]})")
        for label, sel, shot in (("ERR", '.dock button[data-panel="errors"]', "01-dock-err-panel.png"), ("TRC", '.dock button[data-panel="trace"]', None),
                                 ("AGT", "#agentsButton", None), ("LAB", "#openTestLab", None), ("CNV", "#openTimeline", None), ("SET", "#openSettings", "01-dock-set-modal.png"),
                                 ("MCP", "#openMcpInspector", None)):
            await p.click(sel); await asyncio.sleep(1.2)
            res[label] = json.loads(await p.ev(STATE))
            if shot: await p.shot(SH + shot)
            await p.key("Escape"); await asyncio.sleep(0.4)
            res[label + "_afterEsc"] = json.loads(await p.ev(STATE))
            if res[label + "_afterEsc"]["panel"]:
                await p.click("#closePanel"); await asyncio.sleep(0.3)
        res["errors"] = errs(p.events)
        print(json.dumps(res, ensure_ascii=False, indent=0))
run(main())
