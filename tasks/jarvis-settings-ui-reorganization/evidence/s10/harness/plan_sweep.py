"""Plan 3 : par section — piège de Tab (dernier focusable vu par le piège / réel), traversée Tab (contour, reste dans
le shell), régions vivantes, contrôles sans nom accessible. Argument : liste de catégories."""
import json, pathlib, sys

S = pathlib.Path(__file__).resolve().parent.parent
cats = sys.argv[1].split(",")
name = sys.argv[2]
SECTIONS = {
    "voice_audio": ["conversation", "voice_output", "microphone_sound", "turns_interruptions", "wake_word"],
    "agents_models": ["main_agent", "agent_behavior", "subagent_models", "subagents"],
    "memory_knowledge": ["recall", "semantic_retrieval", "consolidation", "knowledge_sources", "memory_center"],
    "interface_interactions": ["theme_scene", "shortcuts", "bare_hands"],
    "connections": ["providers"],
    "advanced_diagnostics": ["architecture_compat", "prompts", "runtime_cli", "diagnostics", "scene_gate", "work_methods", "barehands_lab"],
}
INFO = r"""(()=>{const sh=document.getElementById('settingsShell'),ov=document.getElementById('overlay');
  const trap=[...ov.querySelectorAll('button,a[href],input,select,textarea,summary,[tabindex]')].filter(el=>!el.disabled&&el.tabIndex>=0&&el.getClientRects().length>0);
  const hiddenInDetails=el=>{for(let d=el.closest('details');d;d=d.parentElement&&d.parentElement.closest('details')){if(!d.open&&!(el.tagName==='SUMMARY'&&el.parentElement===d))return true}return false};
  const real=trap.filter(el=>!hiddenInDetails(el));
  const desc=e=>e?{tag:e.tagName,id:e.id,text:(e.textContent||'').trim().slice(0,30)}:null;
  const live=[...sh.querySelectorAll('[role=status],[role=alert],[aria-live]')].map(e=>({id:e.id,role:e.getAttribute('role'),live:e.getAttribute('aria-live'),text:(e.textContent||'').trim().slice(0,40)}));
  const name=el=>{if(el.getAttribute('aria-label')||el.getAttribute('aria-labelledby')||el.title)return true;if(el.id&&document.querySelector('label[for="'+CSS.escape(el.id)+'"]'))return true;if(el.closest('label'))return true;
    if(el.tagName==='BUTTON'||el.tagName==='SUMMARY')return !!(el.textContent||'').trim();if(el.type==='hidden')return true;return false};
  const content=document.getElementById('modalContent');
  const unnamed=[...content.querySelectorAll('input,select,textarea,button,summary')].filter(e=>e.getClientRects().length&&!hiddenInDetails(e)&&!name(e)).map(desc).slice(0,8);
  return {section:SET.section,trapLast:desc(trap[trap.length-1]),realLast:desc(real[real.length-1]),mismatch:trap[trap.length-1]!==real[real.length-1],live,unnamed,count:real.length}})()"""

steps = []
acts = [
    {"a": "wait", "expr": "!!document.getElementById('openSettings')&&!!window.JarvisSettingsRegistry", "timeoutMs": 15000},
    {"a": "click", "selector": "#dockMore"}, {"a": "click", "selector": "#openSettings"},
    {"a": "wait", "expr": "SET.open", "timeoutMs": 8000},
]
for c in cats:
    for s in SECTIONS[c]:
        acts += [
            {"a": "eval", "expr": f"selectTab('{s}');true"},
            {"a": "sleep", "ms": 2200 if s in ("diagnostics", "subagent_models", "voice_output", "subagents", "work_methods") else 1000},
            {"a": "eval", "id": f"info-{s}", "expr": INFO},
            {"a": "eval", "expr": "document.querySelector('#modalTabs [aria-selected=true]').focus();true"},
            # Traversée : jusqu'à revenir sur le rail ou une sortie du shell (60 Tab au plus).
            {"a": "keyUntil", "id": f"tab-{s}", "key": "Tab", "max": 60, "after": 50,
             "expr": "(()=>{const e=document.activeElement,sh=document.getElementById('settingsShell');return !e||!sh.contains(e)||e.closest('#settingsCategories')||e.closest('.set-close')})()"},
            # Un Tab de plus après la sortie éventuelle (pour voir si le focus revient).
            {"a": "key", "key": "Tab", "id": f"after-{s}", "after": 60},
        ]
steps.append({"name": name, "width": 1440, "height": 900, "settleMs": 2500, "actions": acts})
(S / f"plan_{name}.json").write_text(json.dumps({"steps": steps}), encoding="utf-8")
print("ok", sum(len(SECTIONS[c]) for c in cats))
