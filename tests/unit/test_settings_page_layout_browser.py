"""Mise en page unique des Réglages (refonte-ui-settings, Slice 07) dans un vrai Chrome sans tête.

Contrat : `docs/settings/settings-shell.md` § « Catégories en page pleine » et `docs/settings/navigation-registry.md`
(`page` du registre). Un VRAI Control Center isolé (fixture `served` : runtime temporaire, jamais le JARVIS vivant) sert
la page ; le harnais CDP de `test_wake_word_settings_browser.py` clique, tape et mesure. Ce que ce fichier prouve :

- Architecture & Agents et Mémoire & Connaissances s'ouvrent en page pleine, comme Personnalisation : × rond en haut à
  gauche, fil d'Ariane « JARVIS › Paramètres », grand titre, phrase, onglets de page (`.set-tab`), sans rail ; le focus
  va à l'onglet ouvert ; « Paramètres » ramène au hub, Échap ferme, le focus revient au bouton Réglages ;
- les trois autres catégories gardent le shell à rail, et « Réglages détaillés » de Personnalisation l'ouvre toujours ;
- liens profonds et alias (`memory`, `semantic_retrieval`, `main_agent`, `subagent_models`) mènent à la page pleine,
  sur le bon onglet ; un lien interne vers Avancé rend le rail ;
- une seule zone défile par page (le contenu, sous l'en-tête et les onglets qui restent en place), jamais en largeur ;
- captures finales des cinq vues aux tailles des maquettes et à 1280×800 (`JARVIS_BROWSER_SHOTS=<dossier>` les garde,
  en JPEG), sans débordement horizontal ni message de console.

Se saute si Chrome ou node manque.
"""

from __future__ import annotations

from tests.unit._memory_center_fixture import MEMORY_STUB
from tests.unit.settings_visual import OVERFLOW, VIEWS, freeze, shot, shots_dir
from tests.unit.test_architecture_workspace_browser import JOURNAL, JOURNAL_READY
from tests.unit.test_wake_word_settings_browser import click, drive, eval_, got, key, served, wait  # noqa: F401

MEM = [eval_("window.__memStub={};true"), eval_(MEMORY_STUB)]
HUB = [wait("!!document.getElementById('openSettings')"), click("#dockMore"), click("#openSettings"),
       wait("!!document.querySelector('#settingsHubGrid [data-hub-category]')")]

#: Ce que montre la page ouverte : mise en page, rail, chrome de la page, onglets, focus et zones de défilement.
LAYOUT = """(()=>{const q=s=>document.querySelector(s),shown=e=>!!e&&e.getClientRects().length>0;
  const shell=q('#settingsShell'),close=q('#closeModal').getBoundingClientRect(),tabs=[...document.querySelectorAll('#modalTabs [role=tab]')];
  const scrollers=['#settingsShell','#settingsMain','#modalContent','.set-head'].filter(s=>{const e=q(s);if(!e)return false;
    const st=getComputedStyle(e);return /auto|scroll/.test(st.overflowY)&&e.scrollHeight>e.clientHeight+1});
  return {view:q('#overlay').dataset.view,layout:shell.dataset.layout,category:SET.category,section:SET.section,
    rail:shown(q('#settingsCategories')),back:shown(q('#settingsBack')),
    crumb:(q('#settingsIntro .set-crumb')||{}).textContent||null,title:(q('#settingsCategoryTitle')||{}).textContent||null,
    titleClass:(q('#settingsCategoryTitle')||{}).className||null,lead:(q('#settingsIntro .set-lead')||{}).textContent||null,
    closeRound:q('#closeModal').classList.contains('set-hub-close'),closeAt:[Math.round(close.left),Math.round(close.top)],
    tabs:tabs.map(t=>[t.dataset.section,t.className.split(' ')[0],t.getAttribute('aria-selected'),!!t.querySelector('svg')]),
    focus:document.activeElement&&(document.activeElement.dataset.section||document.activeElement.id||document.activeElement.tagName),
    labelled:shell.getAttribute('aria-labelledby'),scrollers}})()"""


async def test_three_mockup_categories_open_as_full_pages_and_the_others_keep_the_rail(served):
    def enter(category: str, ready: str) -> list:
        return [*HUB, click(f"#settingsHubGrid [data-hub-category={category}]"), wait(ready, 15000),
                eval_("new Promise(r=>setTimeout(()=>r(1),300))"), eval_(LAYOUT, category)]

    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *MEM,
        *enter("agents_models", "!!document.querySelector('[data-architecture-page] [data-arch-node=core]')"),
        # « Paramètres » du fil d'Ariane : retour au hub, focus sur une carte.
        click("#settingsCrumbHub"), wait("document.getElementById('overlay').dataset.view==='hub'"),
        eval_("!!document.activeElement.closest('#settingsHubGrid')", "hub_focus"),
        click("#settingsHubGrid [data-hub-category=memory_knowledge]"),
        wait("!!document.querySelector('#memSection_recall [data-mem]')", 10000), eval_(LAYOUT, "memory_knowledge"),
        # Onglets de page au clavier (activation manuelle : flèche puis Entrée).
        eval_("document.querySelector('#modalTabs [aria-selected=true]').focus(),1"), key("ArrowRight"), key("Enter"),
        wait("SET.section==='knowledge_sources'"), eval_(LAYOUT, "keyboard_tab"),
        # Échap ferme les Réglages ; le focus revient au bouton qui les a ouverts (rangé dans « Plus d'outils »).
        key("Escape"), wait("!document.getElementById('overlay').classList.contains('open')"),
        eval_("document.activeElement&&document.activeElement.id", "closed_focus"),
        *enter("connections", "SET.category==='connections'&&!!document.querySelector('#modalTabs [role=tab]')"),
        key("Escape"), wait("!document.getElementById('overlay').classList.contains('open')"),
        # « Réglages détaillés » de Personnalisation : le shell à rail, sur la section choisie.
        *HUB, click("#settingsHubGrid [data-hub-category=voice_audio]"),
        wait("!!document.querySelector('#settingsPerso [data-perso-open=conversation]')", 10000),
        click("#settingsPerso [data-perso-open=conversation]"), wait("SET.section==='conversation'"), eval_(LAYOUT, "detail"),
        # Liens profonds et alias : la page pleine, sur le bon onglet ; un lien vers Avancé rend le rail.
        eval_("(openSettingsLink('memory'),1)"), wait("SET.section==='recall'"), eval_(LAYOUT, "alias_memory"),
        eval_("(openSettingsLink('semantic_retrieval'),1)"), wait("SET.section==='recall'"), eval_(LAYOUT, "alias_semantic"),
        eval_("(openSettingsLink('subagent_models'),1)"), wait("SET.section==='subagents'"), eval_(LAYOUT, "alias_subagents"),
        eval_("(openSettingsLink('main_agent'),1)"), wait("SET.section==='architecture'"), eval_(LAYOUT, "alias_main"),
        eval_("(openSettingsLink('memory_advanced'),1)"), wait("SET.section==='memory_advanced'"), eval_(LAYOUT, "advanced"),
        # La porte des cibles, Réglages fermés (raccourcis, roue) : directement la page pleine.
        key("Escape"), wait("!document.getElementById('overlay').classList.contains('open')"),
        eval_("(openSettingsTab('memory_center'),1)"), wait("SET.section==='memory_center'&&!!document.querySelector('#modalContent .mcw')", 10000),
        eval_(LAYOUT, "door"),
    ]}])
    step = out["steps"][0]
    assert all(a["ok"] for a in step["actions"] if a.get("a") == "wait"), [a for a in step["actions"] if a.get("a") == "wait" and not a["ok"]]
    assert out["console"] == [], out["console"]

    for name, category, sections in [("agents_models", "agents_models", ["architecture", "subagents"]),
                                     ("memory_knowledge", "memory_knowledge", ["recall", "knowledge_sources", "memory_center"])]:
        page = got(step, name)
        assert page["layout"] == "page" and page["category"] == category, page
        assert page["rail"] is False and page["back"] is False, ("pas de rail sur une page pleine", page)
        assert page["crumb"].replace(" ", "") == "JARVIS›Paramètres" and page["titleClass"] == "set-title" and page["lead"], page
        assert page["closeRound"] and page["closeAt"][0] < 60 and page["closeAt"][1] < 60, ("× rond en haut à gauche", page)
        assert [t[0] for t in page["tabs"]] == sections and all(t[1] == "set-tab" and t[3] for t in page["tabs"]), page
        assert page["focus"] == page["section"], ("le focus va à l'onglet ouvert", page)
        assert page["labelled"] == "settingsCategoryTitle", page
        assert page["scrollers"] in ([], ["#modalContent"]), ("une seule zone défile : le contenu, sous l'en-tête", page)
    assert got(step, "hub_focus") is True
    kb = got(step, "keyboard_tab")
    assert kb["section"] == "knowledge_sources" and kb["focus"] == "knowledge_sources", kb
    assert got(step, "closed_focus") in ("openSettings", "dockMore"), got(step, "closed_focus")

    rail = got(step, "connections")
    assert rail["layout"] == "rail" and rail["rail"] is True and rail["back"] is True and not rail["closeRound"], rail
    detail = got(step, "detail")
    assert detail["layout"] == "rail" and detail["category"] == "voice_audio" and detail["rail"] is True, detail
    for name, section in [("alias_memory", "recall"), ("alias_semantic", "recall"), ("alias_subagents", "subagents"),
                          ("alias_main", "architecture"), ("door", "memory_center")]:
        hit = got(step, name)
        assert hit["layout"] == "page" and hit["section"] == section and hit["rail"] is False, (name, hit)
    advanced = got(step, "advanced")
    assert advanced["layout"] == "rail" and advanced["category"] == "advanced_diagnostics" and advanced["rail"] is True, advanced


#: Les cinq vues des maquettes : ouverture, préparation (fenêtre du cerveau ouverte pour Architecture), taille exacte.
FINAL = {
    "personnalisation": (VIEWS["perso"], [], [(1672, 941), (1280, 800)]),
    "sous-agents": (VIEWS["subagents"], [], [(1254, 1254), (1280, 800)]),
    # Menu du cerveau Core ouvert par script (un vrai clic ferait d'abord défiler la page jusqu'au nœud) : la capture
    # montre la page depuis son en-tête, comme la maquette, fenêtre du cerveau ouverte à côté de son nœud.
    "architecture": ([*VIEWS["architecture"], JOURNAL_READY,
                      eval_("(document.querySelector('[data-architecture-page] [data-arch-menu-btn=core]').click(),1)"),
                      wait("!!document.querySelector('[data-arch-menu=configure]')"),
                      eval_("(document.querySelector('[data-arch-menu=configure]').click(),1)"),
                      wait("!!document.querySelector('.bcp-win [data-bcp-radio=delegation]')", 10000),
                      eval_("new Promise(r=>setTimeout(()=>r(1),300))")],
                     [JOURNAL], [(1254, 1254), (1280, 800)]),
    "memoire": ([*MEM, *VIEWS["memory"]], [], [(1254, 1254), (1280, 800)]),
    "memory-center": ([*MEM, *VIEWS["memory_center"], wait("!!document.querySelector('#modalContent .mc-table, #modalContent .mc-empty')", 10000)],
                      [], [(1254, 1254), (1280, 800)]),
}


async def test_final_captures_of_the_five_views_have_no_horizontal_overflow(served, tmp_path):
    shots = shots_dir(tmp_path, "settings-final")
    # Une session de navigateur par vue : le plan passe en argument au harnais, qui a une longueur bornée sous Windows.
    for name, (actions, stubs, sizes) in FINAL.items():
        steps = [{"width": width, "height": height, **({"stubs": stubs} if stubs else {}), "actions": [
            *actions, eval_("new Promise(r=>setTimeout(()=>r(1),700))"), freeze(),
            eval_(OVERFLOW, "overflow"), shot(shots / f"{name}-{width}x{height}.jpg")]} for width, height in sizes]
        out = await drive(served.url, steps)
        assert out["console"] == [], (name, out["console"])
        for (width, height), step in zip(sizes, out["steps"]):
            waits = [a for a in step["actions"] if a.get("a") == "wait"]
            assert all(a["ok"] for a in waits), (name, [a for a in waits if not a["ok"]])
            over = got(step, "overflow")
            assert over["page"] == 0 and all(v == 0 for v in over["containers"].values()), (name, width, height, over)
