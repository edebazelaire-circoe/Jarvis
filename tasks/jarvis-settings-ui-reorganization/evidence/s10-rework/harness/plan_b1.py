"""Reprise S10 (B1) : par section, le dernier contrôle vu par le piège de Tab (`settingsReachable`) contre le dernier
réellement atteignable (calcul indépendant), Tab depuis le vrai dernier et Maj+Tab depuis le premier (vraies frappes CDP),
toute sortie du focus hors du shell relevée (même un instant, par `focusout`), puis traversée Tab complète de la section.
Pilote : `../../s10/harness/s10_driver.mjs`. Usage : python plan_b1.py <sortie.json>"""
import json, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
SHOTS = HERE.parent
SECTIONS = ["conversation", "voice_output", "microphone_sound", "turns_interruptions", "wake_word",
            "main_agent", "agent_behavior", "subagent_models", "subagents",
            "recall", "semantic_retrieval", "consolidation", "knowledge_sources", "memory_center",
            "theme_scene", "shortcuts", "bare_hands", "providers",
            "architecture_compat", "prompts", "runtime_cli", "diagnostics", "scene_gate", "work_methods", "barehands_lab"]
SLOW = {"diagnostics", "subagent_models", "voice_output", "subagents", "work_methods"}
WATCH = r"""(()=>{const sh=document.getElementById('settingsShell');window.__esc=[];
  document.addEventListener('focusout',e=>{if(SET.open&&(!e.relatedTarget||!sh.contains(e.relatedTarget)))
    window.__esc.push({section:SET.section,to:e.relatedTarget?(e.relatedTarget.id||e.relatedTarget.tagName):'body'})},true);return true})()"""
INFO = r"""(()=>{const ov=document.getElementById('overlay');
  const shut=el=>{for(let d=el.closest('details');d;d=d.parentElement&&d.parentElement.closest('details'))if(!d.open&&!(el.tagName==='SUMMARY'&&el.parentElement===d))return true;return false};
  const real=[...ov.querySelectorAll('button,a[href],input,select,textarea,summary,[tabindex]')].filter(el=>!el.disabled&&el.tabIndex>=0&&el.getClientRects().length>0&&!shut(el));
  const trap=settingsReachable(ov);
  const hidden=[...ov.querySelectorAll('details:not([open]) :is(button,input,select,textarea)')].filter(el=>el.getClientRects().length>0).length;
  const desc=e=>e?{tag:e.tagName,id:e.id,text:(e.textContent||'').trim().slice(0,30)}:null;
  real.forEach(el=>{delete el.__end});real[0].__end='first';real[real.length-1].__end='last';
  window.__esc=[];real[real.length-1].focus();
  return {section:SET.section,trapLast:desc(trap[trap.length-1]),realLast:desc(real[real.length-1]),
    same:trap[trap.length-1]===real[real.length-1]&&trap[0]===real[0],hiddenInClosedDetails:hidden,count:real.length}})()"""
WHERE = r"""(()=>{const e=document.activeElement;return {end:e&&e.__end||null,tag:e&&e.tagName,
  inShell:!!e&&document.getElementById('settingsShell').contains(e),escapes:window.__esc.splice(0)}})()"""
FIRST = r"""(()=>{const e=[...document.querySelectorAll('#overlay *')].find(x=>x.__end==='first');window.__esc=[];e.focus();return e.tagName})()"""

acts = [
    {"a": "wait", "expr": "!!document.getElementById('openSettings')&&!!window.JarvisSettingsRegistry", "timeoutMs": 15000},
    {"a": "click", "selector": "#dockMore"}, {"a": "click", "selector": "#openSettings"},
    {"a": "wait", "expr": "SET.open", "timeoutMs": 8000},
    {"a": "eval", "expr": WATCH},
]
for s in SECTIONS:
    acts += [
        {"a": "eval", "expr": f"selectTab('{s}');true"},
        {"a": "sleep", "ms": 2500 if s in SLOW else 1100},
        {"a": "eval", "id": f"info-{s}", "expr": INFO},
        {"a": "key", "key": "Tab", "after": 150},
        {"a": "eval", "id": f"tab-{s}", "expr": WHERE},
    ]
    if s in ("providers", "subagents"):
        acts.append({"a": "shot", "path": str(SHOTS / f"b1-{s}-tab-depuis-le-dernier.png")})
    acts += [
        {"a": "eval", "expr": FIRST},
        {"a": "key", "key": "Tab", "shift": True, "after": 150},
        {"a": "eval", "id": f"shift-{s}", "expr": WHERE},
        # Traversée complète : depuis l'entrée de la section jusqu'au retour sur le rail (80 Tab au plus).
        {"a": "eval", "expr": "window.__esc=[];document.querySelector('#modalTabs [aria-selected=true]').focus();true"},
        {"a": "keyUntil", "id": f"trail-{s}", "key": "Tab", "max": 80, "after": 40,
         "expr": "(()=>{const e=document.activeElement,sh=document.getElementById('settingsShell');return !e||!sh.contains(e)||!!e.closest('#settingsCategories')})()"},
        {"a": "eval", "id": f"trailesc-{s}", "expr": "window.__esc.splice(0)"},
    ]
plan = {"steps": [{"name": "b1", "width": 1440, "height": 900, "settleMs": 2500, "actions": acts}]}
pathlib.Path(sys.argv[1]).write_text(json.dumps(plan), encoding="utf-8")
print("ok", len(SECTIONS))
