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

from tests.unit.test_wake_word_settings_browser import click, drive, eval_, got, key, served, type_in, wait  # noqa: F401

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
  selectTab('memory');await pause(300);out.alias=[SET.category,SET.section,window.JarvisSettingsRegistry.page.resolve('memory').source];
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
        # Les parties Voix et Mot d'éveil, au-dessus, se remplissent après leur lecture : la partie Mémoire reste en vue.
        eval_("""new Promise(r=>setTimeout(()=>{const t=document.getElementById('diagnostic_memory').getBoundingClientRect().top,
          b=document.getElementById('modalContent').getBoundingClientRect();r(t>=b.top-1&&t<b.bottom)},2000))""", "in_view"),
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
    assert tour["alias"] == ["memory_knowledge", "recall", "alias"]  # le seul alias restant (Memory Center › Réglages)
    assert got(step, "diag") == ["advanced_diagnostics", "diagnostics", "diagnostic_memory"]
    assert got(step, "in_view") is True
    assert got(step, "center") == [False, True]
    assert out["console"] == [], out["console"]


#: « Enregistrer la mémoire » est `aria-disabled` (pas `disabled`, qui ferait perdre le focus) tant qu'il ne sert à rien.
EDIT = """(()=>{const i=document.getElementById('mem_recall_max_items');i.value='3';i.dispatchEvent(new Event('change',{bubbles:true}));
  return document.querySelector('[data-mem-save]').getAttribute('aria-disabled')==='true'})()"""


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


#: Le Memory Center sans Core (fixture isolée) n'affiche pas Santé des index : son état est répondu dans la page, et
#: les avertissements de la console sont retenus pour vérifier qu'aucune action n'est perdue en route.
MC_STUB = """(()=>{window.__warn=[];const w=console.warn.bind(console);console.warn=(...a)=>{window.__warn.push(a.map(String).join(' '));w(...a)};
  const real=window.fetch;window.fetch=(u,o)=>String(u).split('?')[0]==='/api/memory/status'
    ?Promise.resolve(new Response(JSON.stringify({available:false,reason_code:'memory_disabled'}),{status:200,headers:{'Content-Type':'application/json'}}))
    :real(u,o);return true})()"""


async def test_the_memory_center_settings_button_opens_recall(served):
    """QA Slice 09 (N1, mutation Q1) et QA Slice 05 : le bouton « Ouvrir les réglages mémoire » du Memory Center est le
    seul appelant de l'alias `memory`. Vrai clic : les Réglages s'ouvrent sur Mémoire & connaissances › Rappel, et le
    gestionnaire Sessions & Boards, qui héberge le Memory Center, ne journalise plus `workspace.unknown_action`."""
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        eval_(MC_STUB), *OPEN,
        click("#modalTabs [data-section=memory_center]"),
        wait("!!document.querySelector('[data-mem-center]:not([disabled])')"),
        click("[data-mem-center]"),
        wait("document.getElementById('workspaceManager').classList.contains('mc-on')&&!!document.getElementById('mc-tab-health')"),
        click("#mc-tab-health"),
        wait("!!document.querySelector('#memoryCenterMount [data-act=settings]')", 8000),
        click("#memoryCenterMount [data-act=settings]"),
        wait("SET.open&&SET.section==='recall'&&!!document.querySelector('#memSection_recall [data-mem]')", 8000),
        eval_("[SET.category,SET.section,document.getElementById('workspaceManager').hidden,"
              "window.__warn.filter(l=>/unknown_action/.test(l))]", "opened"),
    ]}])
    category, section, hidden, unknown = got(out["steps"][0], "opened")
    assert [category, section, hidden] == ["memory_knowledge", "recall", True]
    assert unknown == []
    assert out["console"] == [], out["console"]


@pytest.mark.xfail(strict=True, reason=(
    "Finding QA S10 (non bloquant, Slice 05) : le Memory Center redessine son hôte dans sa propre écoute `submit` "
    "(`runRecall` -> `render()`), le formulaire est détaché avant que l'événement n'atteigne Sessions & Boards, "
    "`foreign(form)` rend faux et `workspace.unknown_action {\"name\":\"recall\"}` est encore journalisé."))
async def test_a_memory_center_form_sent_with_enter_is_not_a_workspace_action(served):
    """QA Slice 10 (mutation Q1 de la passe de finitions) : Sessions & Boards ignore aussi les ENVOIS de formulaire du
    Memory Center qu'il héberge (`foreign(form)` de l'écoute `submit`, `control_center_workspace.js`), pas seulement
    ses clics. Vraie frappe Entrée dans « Test de rappel » : le Memory Center lance son rappel (`/api/memory/recall-explain`)
    et rien n'est journalisé comme `workspace.unknown_action`."""
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        eval_(MC_STUB), *OPEN,
        click("#modalTabs [data-section=memory_center]"),
        wait("!!document.querySelector('[data-mem-center]:not([disabled])')"),
        click("[data-mem-center]"),
        wait("document.getElementById('workspaceManager').classList.contains('mc-on')&&!!document.getElementById('mc-tab-recall')"),
        click("#mc-tab-recall"),
        wait("!!document.getElementById('mcRecallQ')", 8000),
        type_in("#mcRecallQ", "rendez-vous de demain"),
        key("Enter"),
        wait("!document.querySelector('#memoryCenterMount form[data-form=recall] button[disabled]')", 8000),
        eval_("window.__warn.filter(l=>/unknown_action/.test(l))", "unknown"),
    ]}])
    assert got(out["steps"][0], "unknown") == []
    assert any(r["path"] == "/api/memory/recall-explain" for r in out["requests"]), out["requests"]
