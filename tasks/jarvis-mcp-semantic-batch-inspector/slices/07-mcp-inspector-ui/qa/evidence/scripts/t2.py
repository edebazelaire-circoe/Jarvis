from common import *
async def main():
    async with Page() as p:
        await fresh(p)
        out = {}
        await p.click("#openMcpInspector"); await asyncio.sleep(0.4); await wait_idle(p)
        out["after_open_active"] = await p.active()
        out["tabs"] = json.loads(await p.ev(TABS)); out["servers"] = json.loads(await p.ev(SERVERS)); out["head"] = json.loads(await p.ev(HEAD))
        out["default_rows"] = json.loads(await p.ev(ROWS))
        await p.shot(SH + "02-compact-default-tab.png")
        # scene tab
        await p.click("#mcpi-tab-scene"); await asyncio.sleep(0.3)
        out["scene_rows"] = json.loads(await p.ev(ROWS)); out["tabs_scene"] = json.loads(await p.ev(TABS))
        await p.ev("document.activeElement.blur()")
        await p.shot(SH + "02-compact-scene-tab.png")
        out["req_after_compact"] = reqs(p.events)
        # expand scene_update_many
        await p.click('#mcpiPanel .mcpi-toggle[data-key="jarvis-display/scene_update_many"]'); await asyncio.sleep(0.3); await wait_idle(p)
        await p.ev("document.querySelector('#mcpiPanel .mcpi-row.is-open').scrollIntoView({block:'start'})")
        await p.ev("document.activeElement.blur()")
        await p.shot(SH + "03-sum-detail-top.png")
        out["sum_text"] = await p.ev("document.querySelector('#mcpiPanel .mcpi-row.is-open .mcpi-detail').innerText")
        out["sum_sections"] = await p.ev("[...document.querySelectorAll('#mcpiPanel .mcpi-row.is-open .mcpi-sect>h4, #mcpiPanel .mcpi-row.is-open .mcpi-raw>summary')].map(h=>h.textContent.trim())")
        out["raw_open"] = await p.ev("[...document.querySelectorAll('#mcpiPanel .mcpi-row.is-open details.mcpi-raw')].map(d=>d.open)")
        out["raw_is_last"] = await p.ev("(()=>{const d=document.querySelector('#mcpiPanel .mcpi-row.is-open .mcpi-detail');const r=d.querySelector('.mcpi-raw');return r&&!r.nextElementSibling&&r.parentElement===d})()")
        # scroll to select nested structure
        await p.ev("(()=>{const n=[...document.querySelectorAll('#mcpiPanel .mcpi-row.is-open .mcpi-nest')][0];if(n)n.scrollIntoView({block:'start'})})()")
        await p.shot(SH + "03-sum-detail-select.png")
        await p.ev("(()=>{const h=[...document.querySelectorAll('#mcpiPanel .mcpi-row.is-open .mcpi-sect>h4')].find(h=>/sortie|résultat|retour/i.test(h.textContent));if(h)h.scrollIntoView({block:'start'})})()")
        await p.shot(SH + "03-sum-detail-output.png")
        # other tabs
        for tab, tool in (("settings", "jarvis-console/settings_set"), ("barehands", "jarvis-barehands/barehands_tutorial"), ("general", None), ("external", None)):
            await p.click(f"#mcpi-tab-{tab}"); await asyncio.sleep(0.3)
            if tool:
                await p.click(f'#mcpiPanel .mcpi-toggle[data-key="{tool}"]'); await asyncio.sleep(0.3); await wait_idle(p)
                await p.ev("document.querySelector('#mcpiPanel .mcpi-row.is-open').scrollIntoView({block:'start'})")
                out[tab + "_detail"] = await p.ev("document.querySelector('#mcpiPanel .mcpi-row.is-open').innerText")
            out[tab + "_rows"] = json.loads(await p.ev(ROWS))
            out[tab + "_panel"] = (await p.ev("document.getElementById('mcpiPanel').innerText"))[:3000]
            await p.ev("document.activeElement.blur()")
            await p.shot(SH + f"04-tab-{tab}.png")
        # search radius
        await p.click("#mcpiSearch"); await p.type("radius"); await asyncio.sleep(0.5); await wait_idle(p, 20); await asyncio.sleep(0.3)
        out["search_tabs"] = json.loads(await p.ev(TABS))
        await p.click("#mcpi-tab-scene"); await asyncio.sleep(0.3)
        out["search_rows"] = json.loads(await p.ev(ROWS)); out["search_head"] = json.loads(await p.ev(HEAD))
        await p.ev("document.activeElement.blur()")
        await p.shot(SH + "05-search-radius.png")
        # close via Escape, then keyboard flow with cached data
        await p.ev("document.getElementById('mcpiSearch').focus()")
        await p.ev("(()=>{const i=document.getElementById('mcpiSearch');i.value='';i.dispatchEvent(new Event('input'))})()")
        await p.key("Escape"); await asyncio.sleep(0.3)
        out["after_esc1"] = await p.active()
        out["hidden_after_esc1"] = await p.ev("document.getElementById('mcpInspector').hidden")
        out["req_all"] = reqs(p.events)
        out["errors"] = errs(p.events)
        out["allreq_nonGET"] = [r for r in reqs(p.events, "http") if r[0] != "GET"]
        json.dump(out, open(S7 + "/t2.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
run(main())
