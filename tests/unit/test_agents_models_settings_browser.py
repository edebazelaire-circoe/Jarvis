"""Agents & modèles et ses sections d'Avancé, dans un vrai Chrome sans tête (Slice 04).

Handoff `jarvis-settings-ui-reorganization`, contrat `docs/settings/agents-models.md`. Un VRAI Control Center isolé
(fixture `served` de `test_wake_word_settings_browser.py`) sert la page ; le harnais CDP de ce fichier-là clique et
mesure. Ce que ce fichier prouve :

- `agents_models` montre quatre sections orientées tâche, plus aucun onglet `Agent / CLI` ni `Sous-agents` ;
  Runtime & CLI et Work Methods apprises sont sous Avancé ; les anciens ID `cli`, `routing`, `subagents` y mènent ;
- l'identité et le modèle de l'agent sont dans Agent principal, la commande et la permission dans Runtime & CLI ;
- « Enregistrer » depuis Comportement envoie la charge `/api/settings` complète, inchangée, et la valeur se relit ;
- aucune section ne déborde en largeur, divulgations et catalogue ouverts, à 1920×1080 et 1366×768, 100 % et 125 %.

Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import json

import pytest

from tests.unit.test_wake_word_settings_browser import click, drive, eval_, got, served, wait  # noqa: F401

OPEN = [
    wait("!!document.getElementById('openSettings')"),
    click("#dockMore"), click("#openSettings"),
    wait("!!document.getElementById('voiceSection_conversation')"),
    click("#settingsCategories [data-category=agents_models]"),
    wait("!!document.getElementById('agentSection_main_agent')"),
]

#: Les entrées de chaque catégorie, le pied et ce que chaque section rend (sans attendre les sondes).
TOUR = """(async()=>{const pause=ms=>new Promise(r=>setTimeout(r,ms)),q=s=>document.querySelector(s);
  const items=()=>[...document.querySelectorAll('#modalTabs [role=tab]')].map(b=>b.dataset.section||('tab:'+b.dataset.tab));
  const out={categories:{},sections:{}};
  for(const c of window.JarvisSettingsRegistry.CATEGORY_IDS){q(`#settingsCategories [data-category=${c}]`).click();await pause(250);
    out.categories[c]=[...document.querySelectorAll('#modalTabs [role=tab]')].map(b=>b.textContent)}
  for(const id of ['main_agent','agent_behavior','subagent_models','subagents','runtime_cli','work_methods']){
    selectTab(id);await pause(400);
    out.sections[id]={category:SET.category,section:SET.section,footer:!document.querySelector('.set-foot').hidden,
      cmd:!!q('#f_cli_cmd'),perm:!!q('#f_cli_perm'),agents:!!q('input[name=clicagent]')||!!q('#cliStatus'),model:!!q('#f_cli_model'),
      mode:!!q('[data-delegation-mode]'),behavior:document.querySelectorAll('[data-behavior-field]').length,agenda:!!q('#agendaReminders'),
      catalog:!!q('#agentCatalog'),routing:!!q('#routingAdvanced'),roles:!!q('[data-subagent-settings-host]'),
      wm:!!q('[data-subagent-work-methods]')||(SET.subagentView&&SET.subagentView.view==='work_methods')}}
  const legacy={};
  for(const id of ['cli','routing','subagents']){selectTab(id);await pause(200);legacy[id]=[SET.category,SET.tab,SET.section]}
  out.legacy=legacy;out.items=items();return out})()"""


async def test_category_sections_destinations_and_legacy_ids(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [*OPEN, eval_(TOUR, "tour")]}])
    tour = got(out["steps"][0], "tour")
    cats = tour["categories"]
    assert cats["agents_models"] == ["Agent principal", "Comportement", "Modèles des sous-agents", "Rôles des sous-agents"]
    assert "Runtime & CLI" in cats["advanced_diagnostics"] and "Work Methods apprises" in cats["advanced_diagnostics"]
    flat = [label for labels in cats.values() for label in labels]
    assert "Agent / CLI" not in flat and "Sous-agents" not in flat
    s = tour["sections"]
    assert s["main_agent"]["agents"] and s["main_agent"]["model"] and not s["main_agent"]["cmd"] and not s["main_agent"]["perm"]
    assert not s["main_agent"]["routing"] and not s["main_agent"]["catalog"]
    assert s["agent_behavior"]["behavior"] == 2 and s["agent_behavior"]["agenda"] and not s["agent_behavior"]["mode"]
    assert s["subagent_models"]["mode"] and s["subagent_models"]["catalog"] and not s["subagent_models"]["routing"]
    assert s["runtime_cli"]["routing"] and s["runtime_cli"]["category"] == "advanced_diagnostics"
    assert s["subagents"]["roles"] and not s["subagents"]["footer"]
    assert s["work_methods"]["wm"] and not s["work_methods"]["footer"] and s["work_methods"]["category"] == "advanced_diagnostics"
    for footer in ("main_agent", "agent_behavior", "subagent_models", "runtime_cli"):
        assert s[footer]["footer"], footer
    assert tour["legacy"] == {"cli": ["agents_models", None, "main_agent"], "routing": ["advanced_diagnostics", None, "runtime_cli"],
                              "subagents": ["agents_models", None, "subagents"]}
    assert out["console"] == [], out["console"]


SAVE = [
    click("#modalTabs [data-section=agent_behavior]"),
    wait("!!document.querySelector('[data-behavior-field=response_verbosity]')"),
    eval_("""(()=>{const s=document.querySelector('[data-behavior-field=response_verbosity]');s.value='detailed';
      s.dispatchEvent(new Event('change',{bubbles:true}));return s.value})()""", "picked"),
    # Le brouillon survit à un passage par une autre section et par Avancé.
    click("#modalTabs [data-section=subagent_models]"),
    click("#settingsCategories [data-category=advanced_diagnostics]"),
    click("#settingsCategories [data-category=agents_models]"),
    wait("!!document.querySelector('#modalTabs [data-section=agent_behavior]')"),
    click("#modalTabs [data-section=agent_behavior]"),
    wait("!!document.querySelector('[data-behavior-field=response_verbosity]')"),
    eval_("document.querySelector('[data-behavior-field=response_verbosity]').value", "kept"),
    click("#modalSave"),
    wait("document.getElementById('modalStatus').textContent==='Enregistré.'"),
]


async def test_saving_from_behavior_posts_the_unchanged_payload_and_reads_back(served):
    out = await drive(served.url, [
        {"width": 1440, "height": 900, "actions": [*OPEN, *SAVE]},
        {"width": 1440, "height": 900, "actions": [*OPEN, click("#modalTabs [data-section=agent_behavior]"),
                                                   wait("!!document.querySelector('[data-behavior-field=response_verbosity]')"),
                                                   eval_("document.querySelector('[data-behavior-field=response_verbosity]').value", "reloaded")]},
    ])
    assert got(out["steps"][0], "picked") == "detailed" and got(out["steps"][0], "kept") == "detailed"
    posts = [r for r in out["requests"] if r["method"] == "POST" and r["path"] == "/api/settings"]
    assert len(posts) == 1
    body = json.loads(posts[0]["body"])
    # Même charge qu'avant la Slice 04 : un seul brouillon partagé, rien de propre aux sections.
    assert sorted(body) == ["agenda_reminders", "audio", "cli", "routing", "voice"]
    assert list(body["cli"]) == ["agent", "settings", "delegation_mode", "behavior"]
    assert list(body["routing"]) == ["profiles"]
    assert body["cli"]["behavior"]["response_verbosity"] == "detailed"
    assert served.stored()["agent_behavior"]["response_verbosity"] == "detailed"
    assert got(out["steps"][1], "reloaded") == "detailed"
    assert out["console"] == [], out["console"]


#: Chaque section de la catégorie et d'Avancé, divulgations ouvertes, catalogue chargé : rien ne dépasse.
LAYOUT = """(async()=>{const pause=ms=>new Promise(r=>setTimeout(r,ms)),out=[];
  for(const id of ['main_agent','agent_behavior','subagent_models','subagents','runtime_cli','work_methods']){
    selectTab(id);await pause(500);
    document.querySelectorAll('#modalContent details').forEach(d=>{d.open=true});
    await pause(id==='subagent_models'||id==='runtime_cli'?2500:600);
    document.querySelectorAll('#modalContent details').forEach(d=>{d.open=true});await pause(300);
    const body=document.getElementById('modalContent'),main=document.getElementById('settingsMain');
    const wide=[...body.querySelectorAll('*')].filter(e=>e.getBoundingClientRect().right>body.getBoundingClientRect().right+1&&!e.closest('.catalog-scroll,.catalog-filters,[class*=scroll]'))
      .slice(0,3).map(e=>e.tagName+'.'+e.className);
    out.push({id,page:document.documentElement.scrollWidth-innerWidth,content:body.scrollWidth-body.clientWidth,
      main:main.scrollWidth-main.clientWidth,opened:body.querySelectorAll('details[open]').length,wide});
  }
  return out})()"""


@pytest.mark.parametrize(("width", "height"), [(1920, 1080), (1366, 768), (1536, 864), (1093, 614)])
async def test_no_agent_section_overflows_with_disclosures_open(served, width, height):
    """1536×864 et 1093×614 : la largeur CSS de 1920×1080 et 1366×768 à 125 % de zoom."""
    out = await drive(served.url, [{"width": width, "height": height, "actions": [*OPEN, eval_(LAYOUT, "layout")]}])
    layout = got(out["steps"][0], "layout")
    assert [row["id"] for row in layout] == ["main_agent", "agent_behavior", "subagent_models", "subagents", "runtime_cli",
                                             "work_methods"]
    for row in layout:
        assert row["page"] <= 0 and row["content"] <= 1 and row["main"] <= 0, row
    assert any(row["opened"] for row in layout if row["id"] == "runtime_cli")
