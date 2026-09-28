from common import *
PILLS = """(()=>{const o=window.__origPills||renderBackgroundPills;window.__origPills=o;
 window.renderBackgroundPills=()=>o({counts:{failed:1,attention:2,done:3,said:1},unread:0,seq:0});BG.sig=null;renderBackgroundPills();return true})()"""
GEOM = """(()=>{const d=[...document.querySelectorAll('.dock button')].map(b=>{const r=b.getBoundingClientRect();return {t:b.textContent.trim(),x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)}});
 const p=[...document.querySelectorAll('#bgPills .bgpill')].map(b=>{const r=b.getBoundingClientRect();return {t:b.textContent.trim(),x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)}});
 const ov=(a,b)=>a.x<b.x+b.w&&b.x<a.x+a.w&&a.y<b.y+b.h&&b.y<a.y+a.h;
 return {dock:d,pills:p,overlaps:p.flatMap(a=>d.filter(b=>ov(a,b)).map(b=>a.t+'x'+b.t)),hidden:document.getElementById('bgPills').hidden}})()"""
async def main():
    async with Page() as p:
        out = {}
        await fresh(p)
        await p.ev(PILLS); await asyncio.sleep(1.5)
        out["circuit_1440_pills"] = await p.ev(GEOM)
        await p.shot(SH + "01-dock-pills-circuit.png")
        await p.ev("JarvisThemeAPI.activate('cosmos')"); await asyncio.sleep(1.5)
        out["cosmos_1440_pills"] = await p.ev(GEOM)
        await p.shot(SH + "01-dock-pills-cosmos.png")
        await p.click("#openMcpInspector"); await asyncio.sleep(0.5); await wait_idle(p)
        await p.click("#mcpi-tab-scene"); await asyncio.sleep(0.3)
        await p.click('#mcpiPanel .mcpi-toggle[data-key="jarvis-display/scene_update_many"]'); await asyncio.sleep(0.3); await wait_idle(p)
        await p.ev("document.activeElement.blur()")
        await p.shot(SH + "02-cosmos-inspector.png")
        await p.key("Escape"); await asyncio.sleep(0.3)
        # cosmos narrow
        await p.size(360, 780, True); await asyncio.sleep(1)
        out["cosmos_360_pills"] = await p.ev(GEOM)
        out["cosmos_360_scrollW"] = await p.ev("[document.documentElement.scrollWidth,document.body.scrollWidth,innerWidth]")
        await p.shot(SH + "07-cosmos-narrow-home.png")
        await p.ev("JarvisThemeAPI.activate('circuit-board')"); await asyncio.sleep(1)
        out["circuit_360_pills"] = await p.ev(GEOM)
        out["circuit_360_home_scrollW"] = await p.ev("[document.documentElement.scrollWidth,document.body.scrollWidth,innerWidth]")
        await p.click("#openMcpInspector"); await asyncio.sleep(0.5); await wait_idle(p)
        await p.click("#mcpi-tab-scene"); await asyncio.sleep(0.3)
        await p.ev("document.activeElement.blur()")
        await p.shot(SH + "07-narrow-360-list.png")
        M = """(()=>{const t=document.getElementById('mcpiTabs'),s=document.getElementById('mcpiServers'),pn=document.getElementById('mcpiPanel');
          const wide=[...document.querySelectorAll('#mcpInspector *')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.right>innerWidth+1&&!t.contains(e)&&!s.contains(e)&&!e.closest('pre')}).slice(0,8).map(e=>e.tagName+'.'+String(e.className).slice(0,30)+':'+Math.round(e.getBoundingClientRect().right));
          return {docScrollW:document.documentElement.scrollWidth,bodyScrollW:document.body.scrollWidth,innerW:innerWidth,
          tabs:{scrollW:t.scrollWidth,clientW:t.clientWidth,overflowX:getComputedStyle(t).overflowX},
          servers:{scrollW:s.scrollWidth,clientW:s.clientWidth,overflowX:getComputedStyle(s).overflowX},
          panel:{scrollW:pn.scrollWidth,clientW:pn.clientWidth},overflowingOutsideScrollers:wide}})()"""
        out["narrow_list"] = await p.ev(M)
        await p.click('#mcpiPanel .mcpi-toggle[data-key="jarvis-display/scene_update_many"]'); await asyncio.sleep(0.3); await wait_idle(p)
        await p.ev("document.querySelector('#mcpiPanel .mcpi-params tbody tr').scrollIntoView({block:'start'})")
        await p.ev("document.activeElement.blur()")
        out["narrow_detail"] = await p.ev(M)
        out["narrow_table"] = await p.ev("(()=>{const th=document.querySelector('#mcpiPanel .mcpi-params thead');const tr=document.querySelector('#mcpiPanel .mcpi-params tbody tr');const td=tr.querySelector('td');return {theadClip:getComputedStyle(th).position+' '+getComputedStyle(th).clip,trDisplay:getComputedStyle(tr).display,tdDisplay:getComputedStyle(td).display,tdBefore:getComputedStyle(td,'::before').content}})()")
        await p.shot(SH + "07-narrow-360-detail.png")
        # tabs scroll: move to last tab by keyboard, check scrollLeft
        await p.ev("document.getElementById('mcpi-tab-scene').focus()")
        await p.key("End"); await asyncio.sleep(0.4)
        out["tabs_after_End"] = await p.ev("(()=>{const t=document.getElementById('mcpiTabs');const b=document.getElementById('mcpi-tab-external').getBoundingClientRect();return {scrollLeft:t.scrollLeft,lastTabRight:Math.round(b.right),innerW:innerWidth}})()")
        await p.shot(SH + "07-narrow-360-tabs-scrolled.png")
        await p.key("Escape")
        out["errors"] = errs(p.events)
        json.dump(out, open(S7 + "/t7.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(json.dumps(out, ensure_ascii=False))
run(main())
