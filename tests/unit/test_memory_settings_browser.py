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
- le Memory Center vit dans son onglet (une seule maison) : statistiques vivantes, pagination, filtres, note en
  boîte de dialogue fermée par Échap, décisions confirmées puis optimistes (refus : la carte revient avec sa raison),
  test de rappel au clavier, Core muet dit sans chiffre ; Sessions & Boards y mène ;
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
      link:!!q('#modalContent [data-mem-diagnostics],#modalContent .mcw [data-act=diagnostics]'),center:!!q('#modalContent .mcw'),
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
    assert sections["memory_center"]["fields"] == [] and sections["memory_center"]["center"]  # l'atelier, dans son onglet
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


# --- Memory Center dans les Réglages (refonte-ui-settings, Slice 06) ---------------------------------------------------

CENTER = [click("#modalTabs [data-section=memory_center]"),
          wait("!!document.querySelector('.mcw .mc-table tbody tr')&&!/…/.test(document.querySelector('.mc-stats').textContent)", 10000)]
HERO = r"""[...document.querySelectorAll('.mc-stat')].map(s=>s.querySelector('strong').textContent+' '+s.querySelector('span').textContent)"""
ROWS = "document.querySelectorAll('.mc-table tbody tr').length"
MEM_CALLS = "window.__memCalls.map(c=>c[0]+' '+c[1])"


async def test_the_memory_center_lives_in_settings_with_live_data_paging_filters_and_a_note_dialog(served):
    out = await drive(served.url, [{"width": 1254, "height": 1254, "actions": [
        *stub(), *OPEN, *CENTER,
        eval_(HERO, "hero"), eval_(ROWS, "rows"),
        eval_("document.querySelector('.mc-foot').textContent.replace(/\\s+/g,' ').trim()", "foot"),
        click(".mc-pages [aria-label='Page suivante']"),
        wait("/Notes 11–20 sur 23/.test(document.querySelector('.mc-foot').textContent)", 8000),
        eval_("(()=>{const s=document.getElementById('mcLevel');s.value='L3';s.dispatchEvent(new Event('change',{bubbles:true}));return true})()"),
        wait("[...document.querySelectorAll('.mc-table tbody .mc-lvl')].every(e=>e.textContent==='L3')&&document.querySelectorAll('.mc-table tbody tr').length>0", 8000),
        eval_(MEM_CALLS, "calls"),
        # Une note : la boîte de dialogue montre le contenu canonique ; Échap la ferme, pas les Réglages.
        click(".mc-table tbody tr:first-child .mc-notebtn"),
        wait("document.getElementById('mcNoteDialog').open&&/Canonique/.test(document.getElementById('mcNoteDialog').textContent)", 8000),
        key("Escape"),
        eval_("[document.getElementById('mcNoteDialog').open,SET.open,SET.section]", "after_escape"),
    ]}])
    step = out["steps"][0]
    assert got(step, "hero") == ["23 Notes mémoire", "4 Candidats en attente", "2 Sources actives (Wiki, Skills)",
                                 "Prêt Index de rappel (dérivé)"]
    assert got(step, "rows") == 10 and got(step, "foot").startswith("Notes 1–10 sur 23")
    calls = got(step, "calls")
    assert "GET /notes?limit=11&offset=10" in calls and any(c.startswith("GET /notes?limit=11&offset=0&level=L3") for c in calls)
    assert got(step, "after_escape") == [False, True, "memory_center"]
    assert out["console"] == [], out["console"]


async def test_candidate_decisions_confirm_then_apply_optimistically_or_come_back_with_the_reason(served):
    plan = []
    for refuse in (False, True):
        plan.append({"width": 1440, "height": 900, "actions": [
            *stub(refuse=refuse, delay=400), *OPEN, *CENTER,
            click(".mc-rail [data-act=cand-accept][data-id=c1]"),
            wait("!!document.querySelector('.mc-rail [data-act=decide][data-id=c1]')"),
            eval_("[document.activeElement&&document.activeElement.dataset.act,window.__memCalls.filter(c=>c[0]==='POST').length]", "asking"),
            key("Enter"),
            eval_("[!!document.querySelector('.mc-rail [data-cand=c1]'),document.querySelector('.mc-stat strong+span')&&"
                  "document.querySelectorAll('.mc-stat')[1].querySelector('strong').textContent]", "optimistic"),
            # Réponse reçue : la carte a quitté la file (succès) ou l'avis de refus est là ; un refus relit ensuite la file.
            wait("window.__memCalls.some(c=>c[0]==='POST')&&(!!document.querySelector('.mc-cand-notice')||!document.querySelector('.mc-rail [data-cand=c1]'))", 8000),
            eval_("new Promise(r=>setTimeout(r,1200))"),
            wait("/^[0-9]+$/.test(document.querySelectorAll('.mc-stat')[1].querySelector('strong').textContent)", 8000),
            eval_("[document.querySelectorAll('.mc-stat')[1].querySelector('strong').textContent,"
                  "(document.querySelector('.mc-rail .mc-cand-notice')||{}).textContent||'']", "settled"),
            eval_("window.__memCalls.filter(c=>c[0]==='POST').map(c=>[c[1],c[2]])", "posts"),
        ]})
    out = await drive(served.url, plan)
    ok, refused = out["steps"]
    assert got(ok, "asking") == ["decide", 0]  # confirmation d'abord, focus sur « Confirmer », rien d'envoyé
    assert got(ok, "optimistic") == [False, "3"]  # la carte quitte la file avant la réponse
    assert got(ok, "settled") == ["3", ""]
    count, notice = got(refused, "settled")  # file relue : la carte et le compteur reviennent, raison en français + code
    assert count == "4" and "déjà été décidé" in notice and "memory_conflict_revision" in notice
    for step in (ok, refused):  # une seule écriture par décision, la route et la charge de Core
        assert [(path, json.loads(body)) for path, body in got(step, "posts")] == [("/candidates/c1/decision", {"decision": "accept"})]
    assert out["console"] == [], out["console"]


async def test_recall_test_runs_with_enter_and_core_down_is_said_without_numbers(served):
    out = await drive(served.url, [
        {"width": 1440, "height": 900, "actions": [
            *stub(), *OPEN, *CENTER,
            click("#mc-tab-recall"), wait("!!document.getElementById('mcRecallQ')"),
            type_in("#mcRecallQ", "outils favoris"), key("Enter"),
            wait("!!document.querySelector('#mcRecallResult .mc-result')", 8000),
            eval_("[document.querySelectorAll('#mcRecallResult .mc-result').length,/Pourquoi/.test(document.getElementById('mcRecallResult').textContent)]", "recall"),
        ]},
        {"width": 1440, "height": 900, "actions": [
            *stub(down=True), *OPEN, click("#modalTabs [data-section=memory_center]"),
            wait("/Injoignable/.test((document.querySelector('.mc-stats')||{}).textContent||'')", 10000),
            eval_("new Promise(r=>setTimeout(r,500))"),
            eval_("[document.querySelector('.mc-stats').textContent.replace(/\\s+/g,' ').trim(),"
                  "document.querySelectorAll('.mcw .mc-error [data-act]').length,document.querySelector('.mcw').textContent.includes('core_unavailable')]", "down"),
        ]},
    ])
    assert got(out["steps"][0], "recall") == [3, True]
    stats, retries, code = got(out["steps"][1], "down")
    assert not any(ch.isdigit() for ch in stats) and "Injoignable" in stats
    assert retries >= 2 and code is True  # chaque carte dit l'erreur réelle et propose « Réessayer »
    assert out["console"] == [], out["console"]


async def test_entries_to_the_memory_center_and_its_links_back(served):
    """Tuile « Candidats » de l'onglet Mémoire -> onglet Candidats ; bouton de Sessions & Boards -> le même onglet des
    Réglages (une seule maison) ; « Modifier » des réglages essentiels -> onglet Mémoire."""
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *stub(), *OPEN,
        wait("!/Lecture…/.test(document.getElementById('memSection_recall').textContent)", 8000),
        click("#memSection_recall .mem-tile[data-mem-center-tab=candidates]"),
        wait("SET.section==='memory_center'&&document.getElementById('mc-tab-candidates').getAttribute('aria-selected')==='true'", 8000),
        eval_("SET.section", "tile"),
        click("#mc-tab-notes"), wait("!!document.querySelector('.mcw [data-act=settings]')"),
        click(".mcw [data-act=settings]"),
        wait("SET.section==='recall'", 8000),
        eval_("closeSettings();window.JarvisWorkspace.open();true"),
        wait("!document.getElementById('workspaceManager').hidden"),
        click("#wspMemoryCenter"),
        wait("SET.open&&SET.section==='memory_center'&&!!document.querySelector('.mcw')", 8000),
        eval_("[document.getElementById('workspaceManager').hidden,!!document.getElementById('memoryCenterMount')]", "workspace"),
    ]}])
    step = out["steps"][0]
    assert got(step, "tile") == "memory_center"
    assert got(step, "workspace") == [True, False]  # Sessions & Boards refermé, plus de seconde copie
    assert out["console"] == [], out["console"]
