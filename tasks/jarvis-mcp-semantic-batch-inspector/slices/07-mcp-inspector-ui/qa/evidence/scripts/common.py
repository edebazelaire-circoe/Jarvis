import asyncio, json, sys
S7 = r"C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-sub-agents-jarvis-agent-01\b7d45121-0ea1-4bc3-8741-e66996931033\scratchpad\s7"
sys.path.insert(0, S7)
from cdp import Page, run
QA = r"C:\Projects\jarvis\sub-agents\jarvis-agent-01\tasks\jarvis-mcp-semantic-batch-inspector\slices\07-mcp-inspector-ui\qa"
SH = S7 + "/shots/"
import warnings
ROWS = """JSON.stringify([...document.querySelectorAll('#mcpiPanel .mcpi-row')].map(r=>({label:(r.querySelector('.mcpi-label')||{}).textContent,
  wire:(r.querySelector('.mcpi-wire')||{}).textContent,badges:[...r.querySelectorAll('.mcpi-badges .chip')].map(c=>c.textContent.trim()),
  meta:(r.querySelector('.mcpi-meta')||{textContent:''}).textContent.trim()})))"""
TABS = "JSON.stringify([...document.querySelectorAll('#mcpiTabs [role=tab]')].map(t=>[t.dataset.tab,t.textContent.trim().replace(/\s+/g,' '),t.getAttribute('aria-selected'),t.tabIndex]))"
SERVERS = "JSON.stringify([...document.querySelectorAll('#mcpiServers .mcpi-srv')].map(s=>[s.dataset.tone,s.textContent.trim().replace(/\s+/g,' '),s.title]))"
HEAD = "JSON.stringify({status:document.getElementById('mcpiStatus').textContent.trim().replace(/\s+/g,' '),notice:document.getElementById('mcpiNotice').hidden?null:document.getElementById('mcpiNotice').textContent})"
def errs(events):
    out = []
    for e in events:
        m = e["method"]
        if m == "Runtime.exceptionThrown": out.append(e["params"]["exceptionDetails"].get("exception", {}).get("description", "exc")[:300])
        elif m == "Log.entryAdded" and e["params"]["entry"]["level"] in ("error", "warning"): out.append(e["params"]["entry"]["text"][:200] + " " + e["params"]["entry"].get("url", ""))
        elif m == "Runtime.consoleAPICalled" and e["params"]["type"] in ("error", "warning", "assert"):
            out.append(e["params"]["type"] + ": " + " ".join(str(a.get("value", a.get("description", ""))) for a in e["params"]["args"])[:300])
    return out
def reqs(events, flt="/api/mcp"):
    return [(e["params"]["request"]["method"], e["params"]["request"]["url"].replace("http://127.0.0.1:17685", "")) for e in events
            if e["method"] == "Network.requestWillBeSent" and flt in e["params"]["request"]["url"]]
async def fresh(p, w=1440, h=900, net=True):
    await p.size(w, h)
    for d in ("Page.enable", "Runtime.enable", "Log.enable") + (("Network.enable",) if net else ()):
        await p.send(d)
    await p.send("Page.navigate", {"url": "http://127.0.0.1:17685/"})
    await asyncio.sleep(4)
async def wait_idle(p, t=10):
    for _ in range(t * 4):
        if await p.ev("!!window.JarvisMcpInspector && !JarvisMcpInspector.state.loading && !Object.values(JarvisMcpInspector.state.details).some(d=>d.state==='loading')"): return
        await asyncio.sleep(0.25)
