from common import *
async def main():
    async with Page() as p:
        await p.size(360, 740)
        await p.click("#openMcpInspector"); await asyncio.sleep(0.5); await wait_idle(p)
        await p.click("#mcpi-tab-scene"); await asyncio.sleep(0.3)
        await p.ev("[...document.querySelectorAll('#mcpiPanel .mcpi-row')].find(r=>r.textContent.includes('scene_update_many')).querySelector('button').click()")
        await asyncio.sleep(0.6); await wait_idle(p)
        await p.ev("document.querySelector('#mcpiPanel .mcpi-row.is-open .mcpi-detail table, #mcpiPanel .mcpi-row.is-open .mcpi-detail').scrollIntoView({block:'start'})")
        await asyncio.sleep(0.3)
        print(await p.ev("JSON.stringify({sw:document.documentElement.scrollWidth,cw:document.documentElement.clientWidth,open:!!document.querySelector('#mcpiPanel .mcpi-row.is-open')})"))
        await p.ev("document.activeElement.blur()"); await p.shot(SH + "i8-360-detail.png")
        await p.key("Escape")
run(main())
