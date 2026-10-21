"""Mémoire & connaissances et la partie Mémoire des diagnostics, dans un vrai Chrome sans tête (Slice 05).

Handoff `jarvis-settings-ui-reorganization`, contrat `docs/settings/memory.md`. Un VRAI Control Center isolé (fixture
`served` de `test_wake_word_settings_browser.py`) sert la page ; le harnais CDP de ce fichier-là clique et mesure. Ce
que ce fichier prouve :

- `memory_knowledge` montre cinq sections, plus aucun onglet `Mémoire` ; chaque champ est rendu dans la seule section
  que le serveur lui donne ; l'ancien ID `memory` mène à Rappel ;
- « Voir le diagnostic mémoire » ouvre Avancé › Diagnostics, focus sur la partie Mémoire ;
- « Ouvrir le Memory Center » ferme les Réglages et ouvre le Memory Center ;
- le brouillon survit à un passage par une autre section ; « Enregistrer la mémoire » envoie le correctif mémoire seul,
  et la valeur se relit après rechargement ;
- aucune section ne déborde en largeur à 1920×1080 et 1366×768, 100 % et 125 %.

Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import json

import pytest

from tests.unit.test_wake_word_settings_browser import click, drive, eval_, got, served, wait  # noqa: F401

SECTIONS = ["recall", "semantic_retrieval", "consolidation", "knowledge_sources", "memory_center"]
OPEN = [
    wait("!!document.getElementById('openSettings')"),
    click("#dockMore"), click("#openSettings"),
    wait("!!document.getElementById('voiceSection_conversation')"),
    click("#settingsCategories [data-category=memory_knowledge]"),
    wait("!!document.querySelector('#memSection_recall [data-mem]')"),
]

TOUR = """(async()=>{const pause=ms=>new Promise(r=>setTimeout(r,ms)),q=s=>document.querySelector(s);
  const out={labels:[...document.querySelectorAll('#modalTabs [role=tab]')].map(b=>b.textContent),all:[],sections:{}};
  for(const c of window.JarvisSettingsRegistry.CATEGORY_IDS){q(`#settingsCategories [data-category=${c}]`).click();await pause(200);
    out.all.push(...[...document.querySelectorAll('#modalTabs [role=tab]')].map(b=>b.textContent))}
  for(const id of %s){selectTab(id);await pause(300);
    out.sections[id]={category:SET.category,section:SET.section,footer:!document.querySelector('.set-foot').hidden,
      fields:[...document.querySelectorAll('#modalContent [data-mem]')].map(e=>e.dataset.mem),
      link:!!q('#modalContent [data-mem-diagnostics]'),center:!!q('#modalContent [data-mem-center]'),
      legs:!!q('#modalContent .mem-legs[aria-label]')}}
  selectTab('memory');await pause(300);out.alias=[SET.category,SET.tab,SET.section];
  const served=(await (await fetch('/api/settings')).json()).memory.schema.sections.flatMap(s=>s.fields.map(f=>[f.path,f.surface.section]));
  out.served=served;return out})()""" % json.dumps(SECTIONS)


async def test_sections_destinations_alias_and_links(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN, eval_(TOUR, "tour"),
        click("#modalTabs [data-section=consolidation]"),
        wait("!!document.querySelector('#memSection_consolidation [data-mem-diagnostics]')"),
        click("#memSection_consolidation [data-mem-diagnostics]"),
        wait("!!document.getElementById('diagnostic_memory')&&!!document.querySelector('#diagnostic_memory .mem-legs')"),
        eval_("[SET.category,SET.section,document.activeElement&&document.activeElement.id]", "diag"),
        click("#settingsCategories [data-category=memory_knowledge]"),
        click("#modalTabs [data-section=memory_center]"),
        wait("!!document.querySelector('[data-mem-center]:not([disabled])')"),
        click("[data-mem-center]"),
        wait("document.getElementById('workspaceManager').classList.contains('mc-on')"),
        eval_("[SET.open,!document.getElementById('memoryCenterMount').hidden]", "center"),
    ]}])
    step = out["steps"][0]
    tour = got(step, "tour")
    assert tour["labels"] == ["Rappel", "Recherche sémantique", "Consolidation", "Sources de connaissances", "Centre mémoire"]
    assert "Mémoire" not in tour["all"]
    sections = tour["sections"]
    rendered = [path for s in SECTIONS for path in sections[s]["fields"]]
    assert sorted(rendered) == sorted(path for path, _ in tour["served"]) and len(rendered) == len(set(rendered))
    for path, section in tour["served"]:
        assert path in sections[section]["fields"], (path, section)
    for section in SECTIONS:
        assert sections[section]["category"] == "memory_knowledge" and not sections[section]["footer"], section
        assert sections[section]["link"] and not sections[section]["legs"], section
    assert sections["memory_center"]["center"] and sections["memory_center"]["fields"] == []
    assert tour["alias"] == ["memory_knowledge", None, "recall"]
    assert got(step, "diag") == ["advanced_diagnostics", "diagnostics", "diagnostic_memory"]
    assert got(step, "center") == [False, True]
    assert out["console"] == [], out["console"]


EDIT = """(()=>{const i=document.getElementById('mem_recall_max_items');i.value='3';i.dispatchEvent(new Event('change',{bubbles:true}));
  return document.querySelector('[data-mem-save]').disabled})()"""


async def test_saving_posts_only_the_memory_patch_and_reads_back(served):
    out = await drive(served.url, [
        {"width": 1440, "height": 900, "actions": [
            *OPEN, eval_(EDIT, "disabled"),
            click("#modalTabs [data-section=consolidation]"),
            wait("!!document.querySelector('#memSection_consolidation .mem-elsewhere')"),
            click("#modalTabs [data-section=recall]"),
            wait("!!document.getElementById('mem_recall_max_items')"),
            eval_("document.getElementById('mem_recall_max_items').value", "kept"),
            click("[data-mem-save]"),
            wait("/Réglages mémoire enregistrés/.test(document.getElementById('memSection_recall').textContent)"),
        ]},
        {"width": 1440, "height": 900, "actions": [*OPEN, eval_("document.getElementById('mem_recall_max_items').value", "reloaded")]},
    ])
    assert got(out["steps"][0], "disabled") is False and got(out["steps"][0], "kept") == "3"
    posts = [r for r in out["requests"] if r["method"] == "POST"]
    assert [r["path"] for r in posts] == ["/api/settings"]
    assert json.loads(posts[0]["body"]) == {"memory": {"recall": {"max_items": 3}}}
    assert served.stored()["memory"]["recall"]["max_items"] == 3
    assert got(out["steps"][1], "reloaded") == "3"
    assert out["console"] == [], out["console"]


LAYOUT = """(async()=>{const pause=ms=>new Promise(r=>setTimeout(r,ms)),out=[];
  for(const id of [...%s,'diagnostics']){selectTab(id);await pause(400);
    document.querySelectorAll('#modalContent details').forEach(d=>{d.open=true});await pause(200);
    const body=document.getElementById('modalContent'),main=document.getElementById('settingsMain');
    const wide=[...body.querySelectorAll('*')].filter(e=>e.getBoundingClientRect().right>body.getBoundingClientRect().right+1)
      .slice(0,3).map(e=>e.tagName+'.'+e.className);
    out.push({id,page:document.documentElement.scrollWidth-innerWidth,content:body.scrollWidth-body.clientWidth,
      main:main.scrollWidth-main.clientWidth,wide})}
  return out})()""" % json.dumps(SECTIONS)


@pytest.mark.parametrize(("width", "height"), [(1920, 1080), (1366, 768), (1536, 864), (1093, 614)])
async def test_no_memory_section_overflows(served, width, height):
    """1536×864 et 1093×614 : la largeur CSS de 1920×1080 et 1366×768 à 125 % de zoom."""
    out = await drive(served.url, [{"width": width, "height": height, "actions": [*OPEN, eval_(LAYOUT, "layout")]}])
    layout = got(out["steps"][0], "layout")
    assert [row["id"] for row in layout] == [*SECTIONS, "diagnostics"]
    for row in layout:
        assert row["page"] <= 0 and row["content"] <= 1 and row["main"] <= 0 and row["wide"] == [], row
