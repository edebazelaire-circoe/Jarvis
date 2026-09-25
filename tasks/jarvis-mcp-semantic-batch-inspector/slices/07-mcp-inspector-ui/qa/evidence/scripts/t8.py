from common import *
async def main():
    async with Page() as p:
        await p.size(360, 780, True)
        await p.click("#openMcpInspector"); await asyncio.sleep(0.5); await wait_idle(p); await p.click("#mcpi-tab-scene"); await asyncio.sleep(0.3)
        print(await p.ev("""(()=>{return [...document.querySelectorAll('#mcpInspector *')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.right>innerWidth+1&&!e.closest('#mcpiTabs')&&!e.closest('#mcpiServers')}).map(e=>{let a=e,clip=null;while(a&&a!==document.body){const c=getComputedStyle(a);if(c.overflowX!=='visible'&&a!==e){clip=a.className||a.id;break}a=a.parentElement}
          return [e.tagName,e.textContent.slice(0,40),Math.round(e.getBoundingClientRect().right),'clippedBy:'+clip,document.getElementById('mcpiTabs').querySelector('[aria-selected=true]').id]})})()"""))
        await p.key("Escape")
run(main())
