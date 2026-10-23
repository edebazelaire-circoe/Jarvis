"""Reprise S10 (N2, N3) : un profil de routage éteint dans le brouillon (rien d'enregistré) et le catalogue comparatif
atteint au clavier à 1366×768 et 125 %. Usage : python plan_visual.py <sortie.json>"""
import json, pathlib, sys

SHOTS = pathlib.Path(__file__).resolve().parent.parent
OPEN = [
    {"a": "wait", "expr": "!!document.getElementById('openSettings')&&!!window.JarvisSettingsRegistry", "timeoutMs": 15000},
    {"a": "click", "selector": "#dockMore"}, {"a": "click", "selector": "#openSettings"},
    {"a": "wait", "expr": "SET.open", "timeoutMs": 8000},
]
OFF = r"""(()=>{const b=document.querySelector('#modalContent .routing-off');b.scrollIntoView({block:'start'});
  const o=e=>{let v=1;for(;e&&e.nodeType===1;e=e.parentElement)v*=Number(getComputedStyle(e).opacity);return Math.round(v*100)/100};
  return {block:o(b),hints:[...b.querySelectorAll('.hint')].map(o),disabled:[...b.querySelectorAll(':disabled')].map(o)}})()"""
WRAP = r"""(()=>{const w=document.querySelector('#modalContent .catalog-table-wrap'),all=settingsReachable(document.getElementById('overlay'));
  all[all.indexOf(w)-1].focus();return {scroll:w.scrollWidth-w.clientWidth,role:w.getAttribute('role'),name:w.getAttribute('aria-label')}})()"""
FOCUS = r"""(()=>{const e=document.activeElement,cs=getComputedStyle(e);e.scrollIntoView({block:'nearest'});
  return {wrap:e.classList.contains('catalog-table-wrap'),outline:cs.outlineStyle+' '+cs.outlineWidth}})()"""
plan = {"steps": [
    {"name": "routing-off", "width": 1440, "height": 900, "settleMs": 2500, "actions": OPEN + [
        {"a": "eval", "expr": "selectTab('runtime_cli');true"},
        {"a": "wait", "expr": "!!document.querySelector('#routingAdvanced summary')", "timeoutMs": 8000},
        {"a": "click", "selector": "#routingAdvanced summary"},
        {"a": "wait", "expr": "!!document.querySelector('#modalContent [data-routing-profile-enabled]:checked')", "timeoutMs": 15000},
        {"a": "click", "selector": "#modalContent [data-routing-profile-enabled]:checked"},
        {"a": "wait", "expr": "!!document.querySelector('#modalContent .routing-off')", "timeoutMs": 5000},
        {"a": "eval", "id": "off", "expr": OFF},
        {"a": "sleep", "ms": 300},
        {"a": "shot", "path": str(SHOTS / "n2-profil-de-routage-eteint.png")},
    ]},
    {"name": "catalog", "width": 1366, "height": 768, "zoom": 1.25, "settleMs": 2500, "actions": OPEN + [
        {"a": "eval", "expr": "selectTab('subagent_models');true"},
        {"a": "wait", "expr": "!!document.querySelector('#modalContent .catalog-table-wrap')", "timeoutMs": 20000},
        {"a": "eval", "id": "wrap", "expr": WRAP},
        {"a": "key", "key": "Tab", "after": 200},
        {"a": "eval", "id": "focus", "expr": FOCUS},
        {"a": "sleep", "ms": 300},
        {"a": "shot", "path": str(SHOTS / "n3-catalogue-au-clavier-1366-125.png")},
    ]},
]}
pathlib.Path(sys.argv[1]).write_text(json.dumps(plan), encoding="utf-8")
print("ok")
