"""Plan de captures de la passe de corrections S10 (N1, N2, N5, N7) contre le bac à sable 28654."""
import json
import sys

OUT = sys.argv[1]
SHOTS = OUT.rsplit("/", 1)[0] + "/shots/"

OPEN = "(async()=>{SET.tab='subagents';await openSettings();return true})()"
READY = "!!document.querySelector('[data-sar-role]')"
WAIT = lambda expr, ms=8000: {"a": "wait", "expr": expr, "timeoutMs": ms}
SHOT = lambda name: {"a": "shot", "path": SHOTS + name}
EVAL = lambda expr: {"a": "eval", "expr": expr}
CIRCUIT = "window.JarvisThemeAPI.activate('circuit-board',{persist:false})"
SEL = lambda role: {"a": "click", "selector": f'[data-sar-role="{role}"]'}
TYPE = lambda role, text: EVAL(
    f"(()=>{{const d=document.querySelector('[data-sar-editor=\"{role}\"]');d.open=true;"
    f"const a=document.querySelector('[data-sar-text=\"{role}\"]');a.value={json.dumps(text)}+' ('+new Date().toLocaleTimeString('fr-FR')+')';"
    "a.dispatchEvent(new Event('input'));return a.value.length})()")
CLICK_SAVE = lambda role: [EVAL(f"document.querySelector('[data-sar-save=\"{role}\"]')?.scrollIntoView({{block:'center'}})"),
                           {"a": "click", "selector": f'[data-sar-save="{role}"]'}]
NOTICE = "(document.querySelector('[data-sar-notice]')||{}).textContent"
SHOW_NOTICE = EVAL("document.querySelector('[data-sar-notice]')?.scrollIntoView({block:'center'});" + NOTICE)
# Panne simulée dans la page : la relecture de /api/subagent-roles échoue APRÈS un POST réel.
BREAK_REREAD = EVAL("(()=>{const real=window.fetch;let posted=false;window.fetch=(u,i)=>{if(i&&i.method==='POST'&&String(u).includes('/api/prompts/'))posted=true;"
                    "if(posted&&String(u).startsWith('/api/subagent-roles'))return Promise.reject(new TypeError('Failed to fetch (panne simulée)'));return real(u,i)};return true})()")
# POST qui ne répond jamais (n'est pas envoyé) : l'échéance de 15 s du module tranche.
HANG_POST = EVAL("(()=>{const real=window.fetch;window.fetch=(u,i)=>{if(i&&i.method==='POST'&&String(u).includes('/api/prompts/'))"
                 "return new Promise((_,rej)=>i.signal&&i.signal.addEventListener('abort',()=>rej(new DOMException('aborted','AbortError'))));return real(u,i)};return true})()")
PARTIAL = ("(()=>{const real=window.fetch;window.fetch=(u,i)=>String(u).startsWith('/api/subagent-roles')"
           "?Promise.resolve(new Response(JSON.stringify({schema_version:3,roles:[{id:'x',name:'Rôle partiel'},{name:'sans id'}]}),{status:200,headers:{'Content-Type':'application/json'}})):real(u,i);return true})()")

steps = [
    {"width": 1440, "height": 900, "setup": CIRCUIT + ";" + OPEN, "actions": [
        WAIT(READY), SEL("research-lead"), SHOT("21-fiche-1440-instances-repliees.png"),
    ]},
    {"width": 1440, "height": 900, "setup": CIRCUIT + ";" + OPEN, "actions": [
        WAIT(READY), SEL("concept"), TYPE("concept", "Essai N1 : relecture en panne"), BREAK_REREAD, *CLICK_SAVE("concept"),
        WAIT(NOTICE, 10000), SHOW_NOTICE, SHOT("22-n1-enregistre-relecture-echouee.png"),
        EVAL("(async()=>{const r=await (await (window.fetch.__real||fetch)).call?null:null;return true})()"),
    ]},
    {"width": 1440, "height": 900, "setup": CIRCUIT + ";" + OPEN, "actions": [
        WAIT(READY), SEL("concept"), TYPE("concept", "Essai N1 : POST sans réponse"), HANG_POST, *CLICK_SAVE("concept"),
        EVAL("new Promise(r=>setTimeout(r,4000))"), EVAL("document.querySelector('.sar-wait')?.scrollIntoView({block:'center'});true"),
        SHOT("23-n1-attente-compteur.png"),
        WAIT(NOTICE, 20000), SHOW_NOTICE, SHOT("24-n1-resultat-inconnu-relu.png"),
    ]},
    {"width": 1440, "height": 900, "setup": CIRCUIT + ";" + PARTIAL + ";" + OPEN, "actions": [
        WAIT(READY), SHOT("25-n2-charge-partielle.png"),
    ]},
    {"width": 760, "height": 900, "setup": CIRCUIT + ";" + OPEN, "actions": [
        WAIT(READY), SHOT("26-n5-etroit-760-onglet-visible.png"),
        EVAL("(()=>{const b=document.querySelector('#modalTabs button.active').getBoundingClientRect(),n=document.querySelector('#modalTabs').getBoundingClientRect();return {active:document.querySelector('#modalTabs button.active').dataset.tab,inside:b.left>=n.left-1&&b.right<=n.right+1}})()"),
        EVAL("document.querySelector('[data-sar-role=\"qa\"]').scrollIntoView({block:'center'});true"), SEL("qa"),
        EVAL("new Promise(r=>setTimeout(r,300))"),
        EVAL("document.activeElement&&document.activeElement.id"), SHOT("13-etroit-760-fiche.png"),
    ]},
    {"width": 1440, "height": 900, "forcedColors": True, "setup": CIRCUIT + ";" + OPEN, "actions": [
        WAIT(READY), SEL("research-lead"), SHOT("27-n7-couleurs-forcees-selection.png"),
        EVAL("getComputedStyle(document.querySelector('.sar-item.selected')).borderTopWidth"),
    ]},
]
# La 2e étape a une sonde inutile en fin : on l'enlève (pas de fetch réel à restaurer, la navigation suivante recharge la page).
steps[1]["actions"].pop()
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(steps, fh, ensure_ascii=False)
print(len(steps))
