"""Écrit le plan du harnais navigateur pour l'essai réel de la Slice 10 (bac à sable 28654)."""
import json
import sys

OUT = sys.argv[1]
SHOTS = OUT.rsplit("/", 1)[0] + "/shots/"

OPEN = "(async()=>{SET.tab='subagents';await openSettings();return true})()"
READY = "!!document.querySelector('[data-sar-role]')"
SEL = lambda role: {"a": "click", "selector": f'[data-sar-role="{role}"]'}
WAIT = lambda expr, ms=8000: {"a": "wait", "expr": expr, "timeoutMs": ms}
SHOT = lambda name: {"a": "shot", "path": SHOTS + name}
EVAL = lambda expr: {"a": "eval", "expr": expr}
COSMOS = "window.JarvisThemeAPI.activate('cosmos',{persist:false})"
CIRCUIT = "window.JarvisThemeAPI.activate('circuit-board',{persist:false})"
TYPE = lambda role, text: EVAL(
    f"(()=>{{const d=document.querySelector('[data-sar-editor=\"{role}\"]');d.open=true;"
    f"const a=document.querySelector('[data-sar-text=\"{role}\"]');a.value={json.dumps(text)}+' ('+new Date().toLocaleTimeString('fr-FR')+')';"
    "a.dispatchEvent(new Event('input'));return a.value.length})()")
OTHER_TAB = lambda role: EVAL(
    f"(async()=>{{const r=SET.subagentView.state.payload.roles.find(x=>x.id==='{role}');"
    f"const res=await fetch('/api/prompts/subagent_role.{role}',{{method:'POST',headers:{{'Content-Type':'application/json'}},"
    "body:JSON.stringify({action:'edit',text:'Version écrite par un autre onglet à '+new Date().toLocaleTimeString('fr-FR')+'.',base_revision:r.default_revision,"
    "expected_effective_revision:r.revision})});return res.status})()")
FIXTURE_TASKS = EVAL(
    "(async()=>{const host=document.getElementById('subagentSettingsMount');SET.subagentView.destroy();"
    "const tasks={tasks:[{status:'running',kind:'agent',role:'coder',description:'[code] [coder] Corriger le lasso du Board'},"
    "{status:'running',kind:'agent',role:'reviewer',description:'[code] [reviewer] Relire le correctif'},"
    "{status:'running',kind:'agent',role:'zorg',description:'[code] [zorg] Explorer une piste'},"
    "{status:'running',kind:'agent',role:null,ephemeral:true,description:'[éphémère] Lister les fichiers'}]};"
    "const real=async(p,i)=>{const r=await fetch(p,i);return r.json()};"
    "const v=JarvisSubagentSettings.create(host,{fetch:async(p,i)=>p==='/api/agent/tasks'?tasks:real(p,i),drafts:SET.subagentDrafts});"
    "SET.subagentView=v;await v.load();await new Promise(r=>setTimeout(r,300));return true})()")

steps = [
    {"width": 1440, "height": 900, "setup": CIRCUIT + ";" + OPEN, "actions": [
        WAIT(READY), SEL("research-lead"), SHOT("01-catalogue-circuit-research-lead.png"),
        EVAL("document.querySelector('.sar-method.default details').open=true"),
        EVAL("document.querySelector('.sar-detail-pane').scrollTop=520"), SHOT("02-work-method-ouverte-circuit.png"),
        EVAL("JSON.stringify([...document.querySelectorAll('.sar-badge')].map(b=>getComputedStyle(b).color))"),
    ]},
    {"width": 1440, "height": 900, "setup": COSMOS + ";" + OPEN, "actions": [
        WAIT(READY), SEL("qa"), SHOT("03-catalogue-cosmos-qa-alias.png"),
    ]},
    {"width": 1440, "height": 900, "setup": CIRCUIT + ";" + OPEN, "actions": [
        WAIT(READY), {"a": "focus", "selector": '[data-sar-role="interviewer"]'},
        {"a": "key", "key": "ArrowDown"}, {"a": "key", "key": "ArrowDown"},
        EVAL("document.activeElement&&document.activeElement.dataset.sarRole"),
        {"a": "ax", "selector": '[data-sar-role="web-research"]'},
        SHOT("04-clavier-focus-web-research.png"),
    ]},
    {"width": 1440, "height": 900, "setup": CIRCUIT + ";" + OPEN, "actions": [
        WAIT(READY), SEL("concept"), TYPE("concept", "Consigne d'essai de la Slice 10 : proposer trois pistes, puis s'arrêter."),
        EVAL("document.querySelector('[data-sar-editor=\"concept\"]')?.scrollIntoView({block:'start'})"),
        SHOT("05-edition-brouillon.png"),
        {"a": "click", "selector": '[data-sar-save="concept"]'},
        WAIT("(document.querySelector('[data-sar-notice]')||{}).textContent", 10000),
        EVAL("document.querySelector('[data-sar-notice]')?.scrollIntoView({block:'center'});(document.querySelector('[data-sar-notice]')||{}).textContent+' | '+document.getElementById('modalContent').innerText.slice(0,300)"),
        SHOT("06-edition-enregistree.png"),
        EVAL("(async()=>{const r=await fetch('/api/subagent-roles');const j=await r.json();const c=j.roles.find(x=>x.id==='concept');return {modified:c.modified,head:c.instructions.slice(0,40)}})()"),
    ]},
    {"width": 1440, "height": 900, "setup": CIRCUIT + ";" + OPEN, "actions": [
        WAIT(READY), SEL("coder"), TYPE("coder", "Mon texte, commencé avant l'autre onglet."), OTHER_TAB("coder"),
        EVAL("document.querySelector('[data-sar-save=\"coder\"]')?.scrollIntoView({block:'center'})"),
        {"a": "click", "selector": '[data-sar-save="coder"]'},
        WAIT("(document.querySelector('[data-sar-notice]')||{}).textContent", 10000),
        EVAL("document.querySelector('[data-sar-notice]')?.scrollIntoView({block:'center'});(document.querySelector('[data-sar-notice]')||{}).textContent+' | '+document.getElementById('modalContent').innerText.slice(0,300)"),
        SHOT("07-conflit-revision.png"),
        EVAL("document.querySelector('[data-sar-text=\"coder\"]').value"),
    ]},
    {"width": 1440, "height": 900, "setup": CIRCUIT + ";" + OPEN, "actions": [
        WAIT(READY), FIXTURE_TASKS, WAIT("document.querySelectorAll('.sar-inst').length>=4"),
        EVAL("document.querySelector('.sar-instances')?.scrollIntoView({block:'end'})"),
        SHOT("08-instances-fixture.png"),
    ]},
    {"width": 1440, "height": 900, "forcedColors": True, "setup": CIRCUIT + ";" + OPEN, "actions": [
        WAIT(READY), SEL("research-lead"), SHOT("12-couleurs-forcees-contraste.png"),
    ]},
    {"width": 760, "height": 900, "setup": CIRCUIT + ";" + OPEN, "actions": [
        WAIT(READY), SHOT("09-etroit-760.png"),
        EVAL("document.documentElement.scrollWidth<=window.innerWidth&&document.querySelector('.modal').scrollWidth<=document.querySelector('.modal').clientWidth"),
    ]},
    {"width": 1440, "height": 900, "setup": CIRCUIT + ";SET.tab='voice';openSettings()", "actions": [
        WAIT("!!document.querySelector('#modalTabs button')"),
        {"a": "write", "file": "control-center-settings.json", "value": {"prompt_overrides": "illisible"}},
        {"a": "click", "selector": '#modalTabs button[data-tab="subagents"]'},
        WAIT("!!document.querySelector('[data-sar-retry]')", 10000),
        SHOT("10-erreur-registre.png"),
        EVAL("document.querySelector('.sar-state').textContent.replace(/\\s+/g,' ').trim()"),
        {"a": "write", "file": "control-center-settings.json", "value": {}},
        {"a": "click", "selector": "[data-sar-retry]"},
        WAIT(READY, 10000), SHOT("11-reprise-apres-erreur.png"),
    ]},
]
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(steps, fh, ensure_ascii=False)
print(len(steps))
