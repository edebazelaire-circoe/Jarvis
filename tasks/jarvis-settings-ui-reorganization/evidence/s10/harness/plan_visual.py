"""Plan 5 : contraste des désactivés (dont un profil de routage éteint), mouvement réduit, couleurs forcées."""
import json, pathlib, re

S = pathlib.Path(__file__).resolve().parent.parent
SHOTS = S / "shots"
src = pathlib.Path(r"C:/Projects/jarvis/setui/tests/unit/test_settings_accessibility_browser.py").read_text(encoding="utf-8")
CONTRAST_JS = re.search(r'CONTRAST_JS = r"""(.*?)"""', src, re.S).group(1)
OPEN = [
    {"a": "wait", "expr": "!!document.getElementById('openSettings')&&!!window.JarvisSettingsRegistry", "timeoutMs": 15000},
    {"a": "click", "selector": "#dockMore"}, {"a": "click", "selector": "#openSettings"},
    {"a": "wait", "expr": "SET.open", "timeoutMs": 8000}, {"a": "sleep", "ms": 600},
]
ROUTING = """(()=>{%s
  const els=[...document.querySelectorAll('#modalContent .routing-off, #modalContent .routing-off :disabled, #modalContent .routing-off .hint, #modalContent .routing-off label')]
    .filter(e=>e.getClientRects().length&&(e.textContent.trim()||e.tagName==='INPUT'||e.tagName==='SELECT'));
  return {off:document.querySelectorAll('#modalContent .routing-off').length,
    rows:els.map(e=>({tag:e.tagName,cls:String(e.className).slice(0,30),text:(e.textContent||e.type||'').trim().slice(0,30),ratio:Math.round(measure(e)*100)/100,op:getComputedStyle(e).opacity}))}})()""" % CONTRAST_JS
MOTION = """(()=>{const g=s=>{const e=document.querySelector(s);if(!e)return null;const c=getComputedStyle(e);return {anim:c.animationName+' '+c.animationDuration,tr:c.transitionDuration,sb:c.scrollBehavior}};
  const all=[...document.querySelectorAll('#settingsShell *')];
  const moving=all.filter(e=>{const c=getComputedStyle(e);return parseFloat(c.animationDuration)>0.001&&c.animationName!=='none'||c.transitionDuration.split(',').some(d=>parseFloat(d)>0.001)}).slice(0,6).map(e=>e.tagName+'.'+String(e.className).slice(0,30));
  return {overlay:g('#overlay'),cat:g('.set-cat'),body:g('#modalContent'),moving,count:all.length}})()"""
FORCED = """(()=>{const ref=document.createElement('span');ref.style.cssText='color:Highlight;background:GrayText';document.body.append(ref);
  const hl=getComputedStyle(ref).color,gray=getComputedStyle(ref).backgroundColor;ref.remove();
  const offs=[...document.querySelectorAll('#modalContent :disabled, #modalContent [aria-disabled=true]')].filter(e=>e.getClientRects().length);
  const f=getComputedStyle(document.activeElement);
  return {focusHighlight:f.outlineColor===hl&&f.outlineStyle!=='none',disabled:offs.map(e=>({t:(e.textContent||e.type).trim().slice(0,25),gray:getComputedStyle(e).color===gray,op:getComputedStyle(e).opacity}))}})()"""

steps = [
    {"name": "routing-off", "width": 1440, "height": 900, "settleMs": 2500, "actions": OPEN + [
        {"a": "eval", "expr": "selectTab('runtime_cli');true"}, {"a": "sleep", "ms": 2000},
        {"a": "click", "selector": "#routingAdvanced summary"}, {"a": "sleep", "ms": 3500},
        {"a": "click", "selector": "#f_profile_desktop"}, {"a": "sleep", "ms": 1200},
        {"a": "eval", "id": "routing", "expr": ROUTING},
        {"a": "eval", "expr": "document.querySelector('#modalContent .routing-off').scrollIntoView({block:'center'});true"},
        {"a": "shot", "path": str(SHOTS / "v01-profil-de-routage-eteint.png")},
    ]},
    {"name": "reduced-motion", "width": 1440, "height": 900, "reducedMotion": True, "settleMs": 2500, "actions": OPEN + [
        {"a": "eval", "id": "motion", "expr": MOTION},
        {"a": "eval", "expr": "selectTab('voice_output');true"}, {"a": "sleep", "ms": 2500},
        {"a": "eval", "id": "motion2", "expr": MOTION},
    ]},
    {"name": "no-reduced-motion", "width": 1440, "height": 900, "settleMs": 2500, "actions": OPEN + [
        {"a": "eval", "id": "motion0", "expr": MOTION},
    ]},
    {"name": "forced", "width": 1440, "height": 900, "forcedColors": True, "settleMs": 2500, "actions": OPEN + [
        {"a": "eval", "expr": "selectTab('recall');true"}, {"a": "sleep", "ms": 1500},
        {"a": "eval", "expr": "document.querySelector('#settingsCategories [aria-selected=true]').focus();true"},
        {"a": "key", "key": "ArrowDown"},
        {"a": "eval", "id": "forced", "expr": FORCED},
        {"a": "shot", "path": str(SHOTS / "v02-couleurs-forcees-rappel.png")},
        {"a": "eval", "expr": "selectTab('providers');true"}, {"a": "sleep", "ms": 1200},
        {"a": "eval", "expr": "document.querySelector('#modalTabs [aria-selected=true]').focus();true"},
        {"a": "key", "key": "Tab"},
        {"a": "shot", "path": str(SHOTS / "v03-couleurs-forcees-connexions.png")},
    ]},
]
(S / "plan_visual.json").write_text(json.dumps({"steps": steps}), encoding="utf-8")
print("ok")
