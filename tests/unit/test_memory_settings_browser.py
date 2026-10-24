"""Mémoire & connaissances et la partie Mémoire des diagnostics, dans un vrai Chrome sans tête.

Handoffs `jarvis-settings-ui-reorganization` (Slice 05) et `refonte-ui-settings` (Slices 05/06), contrat
`docs/settings/memory.md`. Un VRAI Control Center isolé (fixture `served` de `test_wake_word_settings_browser.py`) sert
la page ; le harnais CDP de ce fichier-là clique, tape et mesure. Le Control Center isolé n'a pas de Core : là où l'état
vivant compte, `MEMORY_STUB` (`_memory_center_fixture.py`) répond aux routes `/api/memory/*` avec la forme exacte de
Core. Ce que ce fichier prouve :

- `memory_knowledge` a trois onglets (Mémoire, Connaissances, Memory Center) ; chaque champ est rendu dans la seule
  section que le serveur lui donne, le délai brut et le sidecar Tencent dans Avancé › Mémoire ; les anciens ID
  `memory`, `semantic_retrieval` et `consolidation` mènent à l'onglet Mémoire ;
- « Voir le diagnostic mémoire » ouvre Avancé › Diagnostics, focus sur la partie Mémoire ; « Ouvrir les paramètres
  avancés » ouvre Avancé › Mémoire ;
- les compteurs de l'entrée du Memory Center et la ligne « Mémoire canonique » viennent de l'état vivant ; Core muet,
  la page le dit (« Core injoignable ») sans inventer un chiffre ; recherche sémantique sans clé : indisponible, dit ;
- l'interrupteur se pilote au clavier ; le brouillon survit à un passage par un autre onglet ; « Enregistrer la
  mémoire » envoie le correctif mémoire seul, et la valeur se relit après rechargement ;
- aucun onglet ne déborde en largeur (maquettes 1254×1254 et 1672×941, 1280×800, 1920×1080, 1366×768, 125 %).

Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import json

import pytest

from tests.unit._memory_center_fixture import MEMORY_STUB
from tests.unit.test_wake_word_settings_browser import click, drive, eval_, got, key, served, type_in, wait, open_settings  # noqa: F401

TABS = ["recall", "knowledge_sources", "memory_center"]
SECTIONS = [*TABS, "memory_advanced"]
OPEN = [
    wait("!!document.getElementById('openSettings')"),
    click("#dockMore"), *open_settings(),
    wait("!!document.getElementById('voiceSection_conversation')"),
    click("#settingsCategories [data-category=memory_knowledge]"),
    wait("!!document.querySelector('#memSection_recall [data-mem]')"),
]


def stub(**config) -> list:
    """Le faux Core de `_memory_center_fixture.py`, posé avant l'ouverture des Réglages."""
    return [eval_(f"window.__memStub={json.dumps(config)};true"), eval_(MEMORY_STUB)]


TOUR = """(async()=>{const pause=ms=>new Promise(r=>setTimeout(r,ms)),q=s=>document.querySelector(s);
  const out={labels:[...document.querySelectorAll('#modalTabs [role=tab]')].map(b=>b.textContent),sections:{}};
  for(const id of %s){selectTab(id);await pause(400);
    out.sections[id]={category:SET.category,section:SET.section,footer:!document.querySelector('.set-foot').hidden,
      fields:[...new Set([...document.querySelectorAll('#modalContent [data-mem]')].map(e=>e.dataset.mem))],
      link:!!q('#modalContent [data-mem-diagnostics]'),center:!!q('#modalContent [data-mem-center]'),
      legs:!!q('#modalContent .mem-legs[aria-label]')}}
  out.alias={};for(const id of ['memory','semantic_retrieval','consolidation']){selectTab(id);await pause(250);
    out.alias[id]=[SET.category,SET.section,window.JarvisSettingsRegistry.page.resolve(id).source]}
  const served=(await (await fetch('/api/settings')).json()).memory.schema.sections.flatMap(s=>s.fields.map(f=>[f.path,f.surface.section]));
  out.served=served;return out})()""" % json.dumps(SECTIONS)


async def test_tabs_destinations_aliases_and_links(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN, eval_(TOUR, "tour"),
        click("#settingsCategories [data-category=memory_knowledge]"),
        click("#modalTabs [data-section=recall]"),
        wait("!!document.querySelector('#memSection_recall [data-mem-diagnostics]')"),
        click("#memSection_recall [data-mem-diagnostics]"),
        wait("!!document.getElementById('diagnostic_memory')&&!!document.querySelector('#diagnostic_memory .mem-legs')"),
        eval_("[SET.category,SET.section,document.activeElement&&document.activeElement.id]", "diag"),
        # Les parties Voix et Mot d'éveil, au-dessus, se remplissent après leur lecture : la partie Mémoire reste en vue.
        eval_("""new Promise(r=>setTimeout(()=>{const t=document.getElementById('diagnostic_memory').getBoundingClientRect().top,
          b=document.getElementById('modalContent').getBoundingClientRect();r(t>=b.top-1&&t<b.bottom)},2000))""", "in_view"),
        click("#settingsCategories [data-category=memory_knowledge]"),
        click("#modalTabs [data-section=recall]"),
        wait("!!document.querySelector('#memSection_recall [data-mem-open=memory_advanced]')"),
        click("#memSection_recall [data-mem-open=memory_advanced]"),
        wait("SET.section==='memory_advanced'&&!!document.getElementById('mem_recall_timeout_ms')"),
        eval_("[SET.category,SET.section]", "advanced"),
    ]}])
    step = out["steps"][0]
    tour = got(step, "tour")
    assert tour["labels"] == ["Mémoire", "Connaissances", "Memory Center"]
    sections = tour["sections"]
    rendered = [path for s in SECTIONS for path in sections[s]["fields"]]
    assert sorted(rendered) == sorted(path for path, _ in tour["served"]) and len(rendered) == len(set(rendered))
    for path, section in tour["served"]:
        assert path in sections[section]["fields"], (path, section)
    assert sections["memory_advanced"]["category"] == "advanced_diagnostics"
    assert sorted(sections["memory_advanced"]["fields"]) == sorted(
        ["recall.timeout_ms", "tencent.enabled", "tencent.url", "tencent.service_id", "tencent.allow_private"])
    for section in SECTIONS:
        assert sections[section]["section"] == section and not sections[section]["footer"], section
        assert sections[section]["link"] and not sections[section]["legs"], section
    assert sections["memory_center"]["fields"] == []
    assert tour["alias"] == {"memory": ["memory_knowledge", "recall", "alias"],
                             "semantic_retrieval": ["memory_knowledge", "recall", "alias"],
                             "consolidation": ["memory_knowledge", "recall", "alias"]}
    assert got(step, "diag") == ["advanced_diagnostics", "diagnostics", "diagnostic_memory"]
    assert got(step, "in_view") is True
    assert got(step, "advanced") == ["advanced_diagnostics", "memory_advanced"]
    assert out["console"] == [], out["console"]


LIVE = r"""(()=>{const t=s=>(document.querySelector(s)||{}).textContent||'',sp=s=>s.replace(/\s+/g,' ').trim();
  return {tiles:[...document.querySelectorAll('#memSection_recall .mem-tile')].map(b=>sp(b.querySelector('strong').textContent+' '+b.querySelector('small').textContent)),
    summary:[...document.querySelectorAll('#memSection_recall .mem-row')].map(r=>sp(r.querySelector('.mem-row-k').textContent+' '+r.querySelector('.mem-row-v').textContent)).join(' | '),
    semantic:sp(t('#memCardSemantic')),cta:sp(t('#memSection_recall .mem-cta'))}})()"""
KNOW = """(()=>Object.fromEntries([...document.querySelectorAll('.mem-source')].map(c=>[c.querySelector('h3').textContent,
  c.querySelector('.mem-pill').textContent.trim()])))()"""


async def test_live_counts_and_source_states_come_from_core_and_never_invented(served):
    """Core répond (faux Core de la fixture) : 23 notes, 4 candidats en attente, Wiki et Skills actifs, graphe de code
    sans fournisseur -> Indisponible. Core muet : « Core injoignable », état des sources inconnu, aucun chiffre."""
    plan = []
    for config in ({}, {"down": True}):
        plan.append({"width": 1440, "height": 900, "actions": [
            *stub(**config), *OPEN,
            wait("!/Lecture…/.test(document.getElementById('memSection_recall').textContent)", 8000),
            eval_(LIVE, "live"),
            click("#modalTabs [data-section=knowledge_sources]"),
            wait("!!document.querySelector('.mem-source')&&!/Lecture…/.test(document.getElementById('modalContent').textContent)", 8000),
            eval_(KNOW, "know"),
        ]})
    out = await drive(served.url, plan)
    up, down = (got(s, "live") for s in out["steps"])
    assert up["tiles"][:2] == ["Notes 23 notes", "Candidats 4 en attente"]
    assert "Mémoire canonique Active" in up["summary"] and "Rappel Par mots" in up["summary"]
    assert "Mémoire privée Reste sur ce PC" in up["summary"]
    assert got(out["steps"][0], "know") == {"Wiki": "Actif", "Graphe de code": "Indisponible", "Skills": "Actif"}
    assert all("— indisponible" in t for t in down["tiles"][:2]) and not any(ch.isdigit() for t in down["tiles"][:2] for ch in t)
    assert "Compteurs indisponibles" in down["cta"] and "core_unavailable" in down["cta"]  # la raison réelle, et « Réessayer »
    assert "Mémoire canonique Inconnu" in down["summary"]
    assert set(got(out["steps"][1], "know").values()) == {"État inconnu"}
    assert out["console"] == [], out["console"]


async def test_semantic_without_key_is_unavailable_and_lexical_recall_stays(served):
    """Recherche sémantique activée avec OpenAI mais sans clé : la carte le dit (raison et remède), le résumé garde
    le rappel par mots, et rien ne casse."""
    served.settings_file.write_text(json.dumps({"memory": {"semantic": {"enabled": True, "provider": "openai"}}}), encoding="utf-8")
    out = await drive(served.url, [{"width": 1254, "height": 1254, "actions": [
        *stub(), *OPEN, wait("!/Lecture…/.test(document.getElementById('memSection_recall').textContent)", 8000),
        eval_(LIVE, "live"),
        eval_("document.getElementById('mem_semantic_provider').value", "provider"),
        eval_("[...document.getElementById('mem_semantic_provider').options].map(o=>[o.value,o.textContent])", "options"),
    ]}])
    live = got(out["steps"][0], "live")
    assert "aucune clé du fournisseur" in live["semantic"] and "absente" in live["semantic"]
    assert "Rappel Par mots" in live["summary"]
    assert got(out["steps"][0], "provider") == "openai"
    assert got(out["steps"][0], "options") == [["none", "Aucun"], ["openai", "OpenAI"]]  # servis, jamais inventés
    assert out["console"] == [], out["console"]


async def test_the_recall_switch_works_from_the_keyboard(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN, eval_("(document.getElementById('mem_recall_enabled').focus(),document.activeElement.id)", "focused"),
        key(" "),
        eval_("[document.getElementById('mem_recall_enabled').checked,document.activeElement.id,"
              "document.querySelector('.mem-savebar').classList.contains('dirty')]", "after"),
        key(" "),
        eval_("[document.getElementById('mem_recall_enabled').checked,document.querySelector('.mem-savebar').classList.contains('dirty')]", "back"),
    ]}])
    step = out["steps"][0]
    assert got(step, "focused") == "mem_recall_enabled"
    assert got(step, "after") == [False, "mem_recall_enabled", True]  # le focus reste sur l'interrupteur redessiné
    assert got(step, "back") == [True, False]
    assert out["console"] == [], out["console"]


#: « Enregistrer la mémoire » est `aria-disabled` (pas `disabled`, qui ferait perdre le focus) tant qu'il ne sert à rien.
EDIT = """(()=>{const i=document.getElementById('mem_recall_max_items');i.value='3';i.dispatchEvent(new Event('change',{bubbles:true}));
  return document.querySelector('[data-mem-save]').getAttribute('aria-disabled')==='true'})()"""


async def test_saving_posts_only_the_memory_patch_and_reads_back(served):
    out = await drive(served.url, [
        {"width": 1440, "height": 900, "actions": [
            *OPEN, eval_(EDIT, "disabled"),
            click("#modalTabs [data-section=knowledge_sources]"),
            wait("!!document.querySelector('#memSection_knowledge_sources .mem-elsewhere')"),
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
  for(const id of [...%s,'diagnostics']){selectTab(id);await pause(500);
    document.querySelectorAll('#modalContent details').forEach(d=>{d.open=true});await pause(200);
    const body=document.getElementById('modalContent'),main=document.getElementById('settingsMain');
    const wide=[...body.querySelectorAll('*')].filter(e=>e.getBoundingClientRect().right>body.getBoundingClientRect().right+1)
      .slice(0,3).map(e=>e.tagName+'.'+e.className);
    out.push({id,page:document.documentElement.scrollWidth-innerWidth,content:body.scrollWidth-body.clientWidth,
      main:main.scrollWidth-main.clientWidth,wide})}
  return out})()""" % json.dumps(SECTIONS)


@pytest.mark.parametrize(("width", "height"), [(1254, 1254), (1672, 941), (1280, 800), (1920, 1080), (1366, 768), (1093, 614)])
async def test_no_memory_tab_overflows(served, width, height):
    """1254×1254 et 1672×941 : tailles des maquettes ; 1093×614 : la largeur CSS de 1366×768 à 125 % de zoom."""
    out = await drive(served.url, [{"width": width, "height": height, "actions": [*stub(), *OPEN, eval_(LAYOUT, "layout")]}])
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


async def test_a_memory_center_form_sent_with_enter_is_not_a_workspace_action(served):
    """QA Slice 10 (N1, mutation Q1 de la passe de finitions) : Sessions & Boards ignore aussi les ENVOIS de formulaire
    du Memory Center qu'il héberge (`foreign(event)` de l'écoute `submit`, `control_center_workspace.js`), pas seulement
    ses clics, alors même que le Memory Center redessine son hôte (formulaire détaché) avant que l'événement n'y
    arrive. Vraie frappe Entrée dans « Test de rappel » puis dans la recherche des Notes : le Memory Center lance son
    rappel et sa recherche, et rien n'est journalisé comme `workspace.unknown_action`."""
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
        # Notes : même chose pour la recherche (`data-form=notes`).
        click("#mc-tab-notes"),
        wait("!!document.getElementById('mcQuery')", 8000),
        type_in("#mcQuery", "rendez-vous"),
        key("Enter"),
        wait("!!document.getElementById('mcQuery')&&!/Chargement/.test(document.getElementById('memoryCenterMount').textContent)", 8000),
        eval_("window.__warn.filter(l=>/unknown_action/.test(l))", "unknown_notes"),
    ]}])
    assert got(out["steps"][0], "unknown") == []
    assert got(out["steps"][0], "unknown_notes") == []
    assert any(r["path"] == "/api/memory/recall-explain" for r in out["requests"]), out["requests"]
    assert any(r["path"] == "/api/memory/search" for r in out["requests"]), out["requests"]
