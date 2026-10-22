"""Avancé & diagnostic dans un vrai Chrome sans tête (Slice 08 de jarvis-settings-ui-reorganization).

Contrat : `docs/settings/INDEX.md` (§ Avancé & diagnostic) et `docs/settings/navigation-registry.md`. Un VRAI Control
Center isolé (fixture `served` de `test_wake_word_settings_browser.py` : runtime temporaire, port libre) sert la page ;
le harnais CDP de ce fichier-là envoie de vraies frappes et de vrais clics. Ce que ce fichier prouve :

- la catégorie montre ses cinq groupes déclarés, dans l'ordre, chaque entrée sous son groupe, et l'avis d'outils
  d'opérateur ; chaque section d'Avancé de la page vivante porte un groupe déclaré ; plus aucun onglet de premier niveau
  (`TABS` vide, aucune entrée `data-tab` dans aucune catégorie) ;
- chaque section d'Avancé se monte sans erreur ; les diagnostics Voix, Mot d'éveil, Mémoire et Bare Hands sont
  atteignables ; les anciens identifiants `prompts`, `experimental` et `routing` mènent à leur section ;
- Prompts : enregistrer puis revenir au défaut d'une couche envoient les charges d'avant (route `/api/prompts/<id>`,
  `edit` avec les deux révisions, `reset` seul), relues par le serveur ; le focus reste sur la couche ;
- Scène constellation (porte de test) : la case envoie `{scene:{enabled}}` et l'écrit ; le redémarrage du brain
  demande confirmation puis envoie `{new_conversation:true}` à `/api/agent/restart` (réponse simulée dans la page :
  aucun processus n'est relancé) ;
- tout se fait au clavier ; aucune section ne déborde en largeur, la liste des entrées comprise.

Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import json

import pytest

from tests.unit.test_wake_word_settings_browser import click, drive, eval_, got, key, served, wait  # noqa: F401

GROUPS = [
    ("architecture_compat", "Architecture & compatibilité"),
    ("prompts", "Prompts & instructions"),
    ("runtime_cli", "Runtime & CLI"),
    ("diagnostics", "Diagnostics"),
    ("labs", "Labs & outils de test"),
]
#: Entrées d'Avancé dans l'ordre affiché, avec leur groupe.
ENTRIES = [
    ("architecture_compat", "architecture_compat"), ("prompts", "prompts"), ("runtime_cli", "runtime_cli"),
    ("diagnostics", "diagnostics"), ("scene_gate", "labs"), ("work_methods", "labs"), ("barehands_lab", "labs"),
]
OPEN = [
    wait("!!document.getElementById('openSettings')"),
    click("#dockMore"), click("#openSettings"),
    wait("!!document.getElementById('voiceSection_conversation')"),
    click("#settingsCategories [data-category=advanced_diagnostics]"),
    wait("!!document.querySelector('#modalTabs .set-group')"),
]

TOUR = """(async()=>{const pause=ms=>new Promise(r=>setTimeout(r,ms)),q=s=>document.querySelector(s),R=window.JarvisSettingsRegistry;
  const out={groups:[...document.querySelectorAll('#modalTabs .set-group')].map(g=>({id:g.dataset.settingsGroup,
      label:(g.querySelector('.set-group-label')||{}).textContent,hidden:(g.querySelector('.set-group-label')||{getAttribute:()=>null}).getAttribute('aria-hidden'),
      entries:[...g.querySelectorAll('[role=tab]')].map(b=>[b.dataset.section,b.dataset.group,b.getAttribute('aria-describedby')])})),
    notice:(q('#settingsCategoryNotice')||{}).textContent||'',
    live:R.page.sections('advanced_diagnostics').map(s=>[s.id,s.group]),declared:R.groups('advanced_diagnostics').map(g=>g.id),
    owned:[...document.querySelectorAll('#modalTabs > *')].every(e=>e.getAttribute('role')==='none'),
    tabs:TABS.length,dataTabs:0,mounted:{},failed:[]};
  for(const c of R.CATEGORY_IDS){q(`#settingsCategories [data-category=${c}]`).click();await pause(120);
    out.dataTabs+=document.querySelectorAll('#modalTabs [data-tab]').length;
    if(c!=='advanced_diagnostics'&&q('#settingsCategoryNotice'))out.failed.push('notice:'+c)}
  for(const [id] of %s){selectTab(id);await pause(id==='diagnostics'?1500:500);
    out.mounted[id]=[SET.category,SET.section,!!q(`#modalContent .set-mount[data-section="${id}"]`)];
    if(/settings_section_mount_failed/.test(q('#modalContent').textContent))out.failed.push(id)}
  selectTab('diagnostics');await pause(1500);
  out.parts=['voice','wake_word','memory','barehands'].map(p=>[p,!!q('#diagnostic_'+p)&&!!q(`[data-diagnostic-part="${p}"]`)&&q(`[data-diagnostic-part="${p}"]`).textContent.trim().length>0]);
  out.alias={};for(const id of ['prompts','experimental','routing','advanced_diagnostics']){selectTab('voice_audio');await pause(100);selectTab(id);await pause(250);
    out.alias[id]=[SET.category,SET.tab,SET.section]}
  selectTab('experimental');await pause(400);out.scene=!!q('#modalContent #sceneSettings [data-scene-toggle]');
  return out})()""" % json.dumps(ENTRIES)


async def test_five_declared_groups_notice_every_section_and_diagnostic_reachable(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [*OPEN, eval_(TOUR, "tour")]}])
    tour = got(out["steps"][0], "tour")
    assert [(g["id"], g["label"]) for g in tour["groups"]] == GROUPS
    assert all(g["hidden"] == "true" for g in tour["groups"])
    assert [(e[0], e[1]) for g in tour["groups"] for e in g["entries"]] == ENTRIES
    assert all(e[2] == f"settingsGroup-{e[1]}" for g in tour["groups"] for e in g["entries"])
    assert tour["owned"] is True  # la liste ne possède que des onglets (conteneurs role=none)
    assert tour["notice"].startswith("Outils d’opérateur")
    # Page vivante : chaque section d'Avancé porte un groupe déclaré ; même ordre que la liste.
    assert tour["declared"] == [g for g, _ in GROUPS]
    assert tour["live"] == [list(e) for e in ENTRIES]
    assert tour["tabs"] == 0 and tour["dataTabs"] == 0  # plus aucun onglet de premier niveau
    assert tour["failed"] == []
    assert tour["mounted"] == {i: ["advanced_diagnostics", i, True] for i, _ in ENTRIES}
    assert tour["parts"] == [["voice", True], ["wake_word", True], ["memory", True], ["barehands", True]]
    assert tour["alias"] == {
        "prompts": ["advanced_diagnostics", None, "prompts"],
        "experimental": ["advanced_diagnostics", None, "scene_gate"],
        "routing": ["advanced_diagnostics", None, "runtime_cli"],
        "advanced_diagnostics": ["advanced_diagnostics", None, "runtime_cli"],  # dernière entrée ouverte (`routing`)
    }
    assert tour["scene"] is True
    assert out["console"] == [], out["console"]


#: La première couche modifiable : son identifiant et ses révisions, lus dans la page.
LAYER = """(()=>{const b=document.querySelector('#modalContent [data-prompt-save]');
  return b?{id:b.dataset.promptSave,base:b.dataset.baseRevision,effective:b.dataset.effectiveRevision}:null})()"""
EDITED = "Couche modifiée par le test de la Slice 08."


async def test_prompt_layer_save_and_reset_post_unchanged_payloads(served):
    sel = "document.querySelector('#modalContent [data-prompt-save]').dataset.promptSave"
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN, eval_("selectTab('prompts');true"),
        wait("!!document.querySelector('#modalContent [data-prompt-save]')", 10000),
        eval_(LAYER, "layer"),
        eval_(f"""(()=>{{const id={sel},area=document.querySelector(`[data-prompt-text="${{CSS.escape(id)}}"]`);
          area.closest('details').open=true;area.value={json.dumps(EDITED)};
          document.querySelector(`[data-prompt-save="${{CSS.escape(id)}}"]`).focus();return true}})()"""),
        key("Enter"),
        wait("/Couche enregistrée/.test(document.querySelector('[data-prompt-status]').textContent)", 10000),
        eval_(f"""(async()=>{{const id={sel},p=await (await fetch('/api/prompts')).json(),l=p.layers.find(x=>x.prompt_id===id);
          return {{text:l.current_text,focus:document.activeElement.dataset.promptSave||document.activeElement.tagName,
            footer:document.querySelector('.set-foot').hidden,status:document.querySelector('[data-prompt-status]').getAttribute('role')}}}})()""", "saved"),
        eval_(f"document.querySelector(`[data-prompt-reset=\"${{CSS.escape({sel})}}\"]`).focus();true"),
        key("Enter"),
        wait("/revenue au défaut/.test(document.querySelector('[data-prompt-status]').textContent)", 10000),
        eval_(f"""(async()=>{{const id={sel},p=await (await fetch('/api/prompts')).json(),l=p.layers.find(x=>x.prompt_id===id);
          return {{text:l.current_text,focus:document.activeElement.dataset.promptReset||document.activeElement.tagName}}}})()""", "reset"),
    ]}])
    step = out["steps"][0]
    layer = got(step, "layer")
    posts = [(r["path"], json.loads(r["body"])) for r in out["requests"] if r["method"] == "POST"]
    route = f"/api/prompts/{layer['id']}"
    assert posts[0] == (route, {"action": "edit", "text": EDITED, "base_revision": layer["base"],
                                "expected_effective_revision": layer["effective"]})
    assert list(posts[0][1]) == ["action", "text", "base_revision", "expected_effective_revision"]
    assert posts[1] == (route, {"action": "reset"}) and len(posts) == 2
    saved = got(step, "saved")
    assert saved == {"text": EDITED, "focus": layer["id"], "footer": True, "status": "status"}
    assert "prompt_overrides" not in served.stored() or layer["id"] not in json.dumps(served.stored()["prompt_overrides"])
    reset = got(step, "reset")
    assert reset["text"] != EDITED and reset["focus"] == layer["id"]
    assert out["console"] == [], out["console"]


#: `/api/status` vu par la page : brain Claude en cours, sans outils d'affichage alors que la scène est allumée (le
#: redémarrage est proposé). `/api/agent/restart` répond dans la page : rien n'est relancé, le corps est gardé.
STUB = """(()=>{window.__restart=[];const real=window.fetch;
  window.fetch=(u,o)=>{const path=String(u).split('?')[0];
    if(path==='/api/agent/restart'){window.__restart.push(o&&o.body);return Promise.resolve(new Response('{"ok":true}',{status:200,headers:{'Content-Type':'application/json'}}))}
    if(path==='/api/status')return real(u,o).then(r=>r.json()).then(v=>new Response(JSON.stringify({...v,agent_cli:'claude',
      agent:{name:'claude',state:'running',display_tools:false,display_prompt:false},subagents:{active:0}}),{status:200,headers:{'Content-Type':'application/json'}}));
    return real(u,o)};return true})()"""


async def test_scene_gate_toggle_and_brain_restart_are_unchanged(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        eval_(STUB), *OPEN, eval_("selectTab('experimental');true"),
        wait("!!document.querySelector('#modalContent [data-scene-toggle]')"),
        eval_("[document.querySelector('[data-scene-toggle]').checked,SET.section]", "before"),
        eval_("document.querySelector('[data-scene-toggle]').focus();true"), key(" "),
        wait("SET.data.scene.enabled===false&&!document.querySelector('[data-scene-toggle]').hasAttribute('aria-busy')"),
        eval_("[document.querySelector('[data-scene-toggle]').checked,document.activeElement.hasAttribute('data-scene-toggle')]", "off"),
        key(" "),
        wait("SET.data.scene.enabled===true&&!document.querySelector('[data-scene-toggle]').hasAttribute('aria-busy')"),
        wait("!!document.querySelector('[data-scene-restart]')", 5000),
        click("[data-scene-restart]"),
        wait("!document.getElementById('confirmBack').hidden"),
        eval_("document.getElementById('confirmTitle').textContent", "confirm"),
        click("#confirmGo"),
        wait("window.__restart.length===1"),
        wait("!document.querySelector('[data-scene-restart][aria-busy=true]')"),
        eval_("window.__restart", "restart"),
    ]}])
    step = out["steps"][0]
    assert got(step, "before") == [True, "scene_gate"]
    assert got(step, "off") == [False, True]  # le focus reste sur la case
    posts = [(r["path"], json.loads(r["body"])) for r in out["requests"] if r["method"] == "POST"]
    assert posts == [("/api/settings", {"scene": {"enabled": False}}), ("/api/settings", {"scene": {"enabled": True}})]
    assert served.stored()["scene"] == {"enabled": True}
    assert got(step, "confirm") == "Redémarrer le brain ?"
    assert [json.loads(b) for b in got(step, "restart")] == [{"new_conversation": True}]
    assert out["console"] == [], out["console"]


KEYBOARD = [
    wait("!!document.getElementById('openSettings')"),
    click("#dockMore"), click("#openSettings"),
    wait("!!document.getElementById('voiceSection_conversation')"),
    eval_("document.querySelector('#settingsCategories [aria-selected=true]').focus();true"),
    key("End"), key("Enter"),
    wait("SET.category==='advanced_diagnostics'"),
    eval_("document.querySelector('#modalTabs [aria-selected=true]').focus();true"),
    key("Home"),
    *[a for _ in range(6) for a in (eval_("document.activeElement.dataset.section||document.activeElement.tagName", "seen"), key("ArrowRight"))],
    eval_("document.activeElement.dataset.section||document.activeElement.tagName", "seen"),
    key("Enter"),
    wait("SET.section==='barehands_lab'"),
    eval_("[SET.category,SET.section,document.activeElement.dataset.section||document.activeElement.tagName]", "opened"),
]


async def test_the_advanced_category_works_with_the_keyboard_alone(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": KEYBOARD}])
    actions = out["steps"][0]["actions"]
    seen = [a["value"] for a in actions if a.get("id") == "seen"]
    assert seen == [i for i, _ in ENTRIES]  # les flèches parcourent les entrées, jamais les intitulés de groupe
    assert got(out["steps"][0], "opened") == ["advanced_diagnostics", "barehands_lab", "barehands_lab"]
    assert out["console"] == [], out["console"]


LAYOUT = """(async()=>{const pause=ms=>new Promise(r=>setTimeout(r,ms)),out={};
  for(const [id] of %s){selectTab(id);await pause(id==='diagnostics'?1500:500);
    document.querySelectorAll('#modalContent details').forEach(d=>{d.open=true});await pause(150);
    const body=document.getElementById('modalContent'),main=document.getElementById('settingsMain'),list=document.getElementById('modalTabs');
    const wide=[...body.querySelectorAll('*')].filter(e=>e.getBoundingClientRect().right>body.getBoundingClientRect().right+1)
      .slice(0,3).map(e=>e.tagName+'.'+e.className);
    out[id]={page:document.documentElement.scrollWidth-innerWidth,content:body.scrollWidth-body.clientWidth,
      main:main.scrollWidth-main.clientWidth,list:list.scrollWidth-list.clientWidth,wide}}
  return out})()""" % json.dumps(ENTRIES)


@pytest.mark.parametrize(("width", "height"), [(1920, 1080), (1366, 768)])
async def test_no_advanced_section_overflows(served, width, height):
    out = await drive(served.url, [{"width": width, "height": height, "actions": [*OPEN, eval_(LAYOUT, "layout")]}])
    layout = got(out["steps"][0], "layout")
    for section, measure in layout.items():
        assert measure["page"] <= 0 and measure["main"] <= 0, (section, measure)
        assert measure["content"] <= 1 and measure["wide"] == [], (section, measure)
        assert measure["list"] <= 1, (section, measure)  # les cinq groupes tiennent : aucun défilement caché
    assert out["console"] == [], out["console"]
