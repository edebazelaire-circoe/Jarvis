import json, shutil, subprocess, sys
sys.path.insert(0, r"C:\Projects\jarvis\arch-s08")
import s08_sandbox as S
from tests.unit.test_wake_word_settings_browser import CHROME_CANDIDATES, HARNESS, click, eval_, key, open_settings, wait
chrome = next((str(c) for c in CHROME_CANDIDATES if c.is_file()), None)
st = ("(()=>{const e=document.activeElement;return [SET.open,e&&e.tagName,"
      "e&&(e.getAttribute('data-arch-node')||e.getAttribute('data-arch-menu')||e.id)]})()")
SPY = r"""(()=>{window.__log=[];
  const o=closeSettings;closeSettings=function(){window.__log.push('closeSettings: '+String(new Error().stack).split('\n').slice(1,6).join(' | '));return o.apply(this,arguments)};
  document.addEventListener('keydown',e=>{if(e.key==='Escape')window.__log.push('doc-capture target='+(e.target.getAttribute&&e.target.getAttribute('data-arch-menu')||e.target.tagName)+' prevented='+e.defaultPrevented)},true);
  window.addEventListener('keydown',e=>{if(e.key==='Escape')window.__log.push('win-bubble prevented='+e.defaultPrevented+' connected='+e.target.isConnected)});
  return 1})()"""
plan = [{"width": 1440, "height": 900, "actions": [
    wait("!!document.getElementById('openSettings')"), click("#dockMore"), *open_settings(),
    click("#settingsCategories [data-category=agents_models]"),
    wait("!!document.querySelector('[data-architecture-page] [data-arch-node=core]')", 15000),
    wait("new Promise(r=>setTimeout(()=>r(true),2000))", 5000),
    eval_(SPY, "spy"),
    eval_("(()=>{const n=document.querySelector('[data-architecture-page] [data-arch-node=core]');n.focus();return document.activeElement===n})()", "focused"),
    eval_(st, "s0"), key("F10", shift=True), eval_(st, "s1"), key("Escape"), eval_(st, "s2"), eval_("window.__log", "log"),
]}]
with S.ControlCenterSandbox():
    done = subprocess.run([shutil.which("node"), str(HARNESS), S.UI + "/", chrome, json.dumps(plan)], capture_output=True,
                          text=True, encoding="utf-8", timeout=300)
    print(done.stderr[:800])
    if done.stdout:
        r = json.loads(done.stdout)
        for a in r["steps"][0]["actions"]:
            if a.get("id"):
                print(a["id"], a.get("value"))
