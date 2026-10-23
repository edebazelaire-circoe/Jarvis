"""Plan 1 : tournée des six catégories et de toutes leurs sections, six tailles (3 x 100 % / 125 %)."""
import json, pathlib, sys

S = pathlib.Path(__file__).resolve().parent.parent
SHOTS = S / "shots"
SHOTS.mkdir(exist_ok=True)

OPEN = [
    {"a": "wait", "expr": "!!document.getElementById('openSettings')&&!!window.JarvisSettingsRegistry", "timeoutMs": 15000},
    {"a": "click", "selector": "#dockMore"}, {"a": "click", "selector": "#openSettings"},
    {"a": "wait", "expr": "SET.open&&!!document.querySelector('#settingsCategories [aria-selected=true]')", "timeoutMs": 10000},
    {"a": "sleep", "ms": 800},
]

MEASURE = r"""(async()=>{const pause=ms=>new Promise(r=>setTimeout(r,ms)),R=window.JarvisSettingsRegistry,out=[];
  for(const c of R.CATEGORY_IDS){for(const s of R.page.sections(c)){selectTab(s.id);
    await pause(s.id==='diagnostics'?2200:s.id==='subagent_models'||s.id==='voice_output'?2500:900);
    document.querySelectorAll('#modalContent details').forEach(d=>{d.open=true});await pause(400);
    const body=document.getElementById('modalContent'),main=document.getElementById('settingsMain'),tabs=document.getElementById('modalTabs');
    const br=body.getBoundingClientRect();
    const wide=[...body.querySelectorAll('*')].filter(e=>{const r=e.getBoundingClientRect();return r.width&&r.right>br.right+1&&getComputedStyle(e).position!=='fixed'})
      .slice(0,3).map(e=>e.tagName+'#'+e.id+'.'+String(e.className).slice(0,40));
    const cut=[...tabs.querySelectorAll('[role=tab]')].filter(b=>b.getBoundingClientRect().right>tabs.getBoundingClientRect().right+0.5).map(b=>b.dataset.section);
    out.push({category:c,section:s.id,shown:SET.section===s.id,page:document.documentElement.scrollWidth-innerWidth,
      content:body.scrollWidth-body.clientWidth,main:main.scrollWidth-main.clientWidth,list:tabs.scrollWidth-tabs.clientWidth,cut,wide,
      notice:!!body.querySelector('[data-settings-mount-failed],.set-notice-bad[role=alert]')})}}
  return out})()"""

SIZES = [(1366, 768), (1440, 900), (1920, 1080)]
steps = []
for zoom in (1, 1.25):
    for (w, h) in SIZES:
        tag = f"{w}x{h}-{int(zoom*100)}"
        acts = list(OPEN)
        acts.append({"a": "eval", "id": "cats", "expr": "window.JarvisSettingsRegistry.CATEGORY_IDS.slice()"})
        for i, cat in enumerate(["voice_audio", "agents_models", "memory_knowledge", "interface_interactions", "connections", "advanced_diagnostics"]):
            acts.append({"a": "click", "selector": f"#settingsCategories [data-category={cat}]"})
            acts.append({"a": "sleep", "ms": 1600 if cat in ("agents_models", "advanced_diagnostics") else 1100})
            acts.append({"a": "eval", "id": f"cat-{cat}", "expr": "({cat:SET.category,section:SET.section,page:document.documentElement.scrollWidth-innerWidth})"})
            acts.append({"a": "shot", "path": str(SHOTS / f"{tag}-{i+1}-{cat}.png")})
        acts.append({"a": "eval", "id": "measure", "expr": MEASURE})
        steps.append({"name": tag, "width": w, "height": h, "zoom": zoom, "settleMs": 2500, "actions": acts})

plan = {"steps": steps}
(S / "plan_tour.json").write_text(json.dumps(plan), encoding="utf-8")
print("ok", len(steps))
