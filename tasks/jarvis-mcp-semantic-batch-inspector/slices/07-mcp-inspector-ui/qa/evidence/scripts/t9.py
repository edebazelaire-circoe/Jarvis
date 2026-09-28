from common import *
SCAN = """(()=>{const root=document.getElementById('mcpInspector');
 const probe=document.createElement('div');probe.className='mcpi-skel';probe.innerHTML='<span></span>';document.getElementById('mcpiPanel').prepend(probe);
 const moving=[];for(const e of [root,...root.querySelectorAll('*')]){const c=getComputedStyle(e);
  const td=c.transitionDuration.split(',').some(v=>parseFloat(v)>0),an=c.animationName!=='none'&&parseFloat(c.animationDuration)>0;
  if(td||an)moving.push(e.tagName+'.'+String(e.className.baseVal??e.className).slice(0,24)+' t='+(td?c.transitionProperty+':'+c.transitionDuration:'-')+' a='+(an?c.animationName:'-'))}
 probe.remove();return [...new Set(moving)]})()"""
async def main():
    async with Page() as p:
        await p.size(1440, 900)
        await p.ev("location.reload()"); await asyncio.sleep(4)
        await p.click("#openMcpInspector"); await asyncio.sleep(0.5); await wait_idle(p)
        await p.click("#mcpi-tab-scene"); await asyncio.sleep(0.3)
        await p.click('#mcpiPanel .mcpi-toggle[data-key="jarvis-display/scene_query"]'); await asyncio.sleep(0.3); await wait_idle(p)
        await p.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "no-preference"}]}); await asyncio.sleep(0.3)
        normal = await p.ev(SCAN)
        await p.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]}); await asyncio.sleep(0.3)
        mq = await p.ev("matchMedia('(prefers-reduced-motion: reduce)').matches")
        reduced = await p.ev(SCAN)
        await p.click('#mcpiPanel .mcpi-toggle[data-key="jarvis-display/scene_query"]'); await asyncio.sleep(0.05)
        chev = await p.ev("getComputedStyle(document.querySelector('.mcpi-toggle[data-key=\"jarvis-display/scene_query\"] .mcpi-chev')).transitionDuration")
        await p.send("Emulation.setEmulatedMedia", {"features": []})
        await p.key("Escape")
        print(json.dumps({"no-preference": normal, "matches_reduce": mq, "reduce": reduced, "chev_reduce": chev}, ensure_ascii=False, indent=1))
run(main())
