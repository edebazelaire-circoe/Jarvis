"""Architecture & Agents dans un vrai Chrome sans tête, contre un vrai Control Center isolé
(jarvis-architecture-agents-settings-editor, Slice 07, qui remplace la Slice 04 de jarvis-settings-ui-reorganization).

Contrat : `docs/settings/architecture-agents.md`. Un VRAI Control Center isolé (fixture `served` de
`test_wake_word_settings_browser.py` : runtime temporaire, port choisi par le système, jamais le JARVIS vivant) sert la
page ; le harnais CDP de ce fichier-là clique, frappe et mesure. Ce que ce fichier prouve :

- `agents_models` (« Architecture & Agents ») a exactement deux onglets, Architecture et Sous-agents ; aucun contrôle de
  personnalité ni de CLI technique n'y figure ; Runtime & CLI (Avancé) porte commande, permission, mode hérité
  Auto / Dupliqué, profils et inventaire ; les anciens ID `main_agent` et `subagent_models` mènent aux deux onglets ;
- l'onglet Architecture dessine le graphe servi par `/api/architecture` ; « … › Configurer… » ouvre la fenêtre du
  cerveau Core, qui ne couvre pas le nœud, garde Tab, se ferme par Échap sans fermer les Réglages ; la délégation
  `never` part en `PATCH /api/brains/core/config` et le graphe relu montre la liaison Core → Sous-agents coupée ;
  changer d'onglet détruit la fenêtre ; l'onglet Sous-agents lit `/api/subagent-role-routing` ;
- « Enregistrer » depuis Comportement (Personnalisation) envoie la charge `/api/settings` complète, inchangée ;
- aucune section ne déborde en largeur, à 1920×1080 et 1366×768, 100 % et 125 %.

Se saute si Chrome ou node manque. `JARVIS_BROWSER_SHOTS=<dossier>` garde les captures.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.unit.test_wake_word_settings_browser import click, drive, eval_, got, key, served, wait, open_settings  # noqa: F401

OPEN = [
    wait("!!document.getElementById('openSettings')"),
    click("#dockMore"), *open_settings(),
    wait("!!document.getElementById('voiceSection_conversation')"),
    click("#settingsCategories [data-category=agents_models]"),
    wait("!!document.querySelector('[data-architecture-page] [data-arch-node=core]')", 15000),
]

#: Contrôles interdits sur la page (D19, D20) : personnalité, CLI technique, ancien choix Auto / Dupliqué, catalogue brut.
FORBIDDEN = ("#f_cli_cmd,#f_cli_perm,#reprobe,input[name=clicagent],#f_cli_model,[data-delegation-mode],"
             "[data-behavior-field],#agentCatalog,#routingAdvanced")
#: Libellés de contrôle interdits (un champ, une liste, un groupe), quel que soit le module qui les rendrait.
FORBIDDEN_LABELS = r"/politesse|humour|formalit|verbosit|longueur des r|ton des r|personnalit|commande|chemin|permission|sandbox|re-d[ée]tect/i"

TOUR = ("(async()=>{const FORBIDDEN_LABELS=" + FORBIDDEN_LABELS + ";" + """
  const pause=ms=>new Promise(r=>setTimeout(r,ms)),q=s=>document.querySelector(s);
  const out={categories:{},sections:{}};
  for(const c of window.JarvisSettingsRegistry.CATEGORY_IDS){q(`#settingsCategories [data-category=${c}]`).click();await pause(250);
    out.categories[c]=[...document.querySelectorAll('#modalTabs [role=tab]')].map(b=>b.textContent)}
  /* Libellés des contrôles (texte d'un <label>/<legend>, nom accessible d'un champ ou d'un groupe), jamais le texte
     édité : les instructions d'un rôle peuvent parler de commandes ou de chemins. */
  const labels=()=>[...[...document.querySelectorAll('#modalContent label,#modalContent legend')].map(e=>e.textContent),
    ...[...document.querySelectorAll('#modalContent :is(select,input,textarea,[role=radiogroup],[role=switch])')].map(e=>e.getAttribute('aria-label')||'')]
    .map(t=>(t||'').trim()).filter(t=>FORBIDDEN_LABELS.test(t));
  for(const id of ['architecture','subagents','agent_behavior','runtime_cli','work_methods']){
    selectTab(id);await pause(id==='architecture'||id==='subagents'?1500:400);
    out.sections[id]={category:SET.category,section:SET.section,footer:getComputedStyle(q('#modalSave')).display!=='none',
      forbidden:[...document.querySelectorAll('#modalContent :is(FORBIDDEN)')].map(e=>e.id||e.name||e.className),forbiddenLabels:labels(),
      cmd:!!q('#f_cli_cmd'),perm:!!q('#f_cli_perm'),mode:!!q('[data-delegation-mode]'),catalog:!!q('#agentCatalogDisclosure'),
      routing:!!q('#routingAdvanced'),canvas:!!q('[data-architecture-page] [data-arch-node]'),roles:!!q('[data-subagent-settings-host]'),
      behavior:document.querySelectorAll('[data-behavior-field]').length}}
  const legacy={};
  for(const id of ['main_agent','subagent_models','subagents','cli','routing']){selectTab('voice_audio');await pause(150);selectTab(id);await pause(250);
    legacy[id]=[SET.category,SET.section,(window.JarvisSettingsRegistry.page.resolve(id)||{source:null}).source]}
  out.legacy=legacy;return out})()""").replace(":is(FORBIDDEN)", ":is(" + FORBIDDEN + ")")


def shots() -> Path | None:
    target = os.environ.get("JARVIS_BROWSER_SHOTS")
    if not target:
        return None
    Path(target).mkdir(parents=True, exist_ok=True)
    return Path(target)


def assert_waits(step: dict) -> None:
    failed = [a for a in step["actions"] if a.get("a") == "wait" and not a.get("ok")]
    assert not failed, failed


async def test_two_tabs_destinations_and_legacy_ids(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [*OPEN, eval_(TOUR, "tour")]}])
    assert_waits(out["steps"][0])
    tour = got(out["steps"][0], "tour")
    cats = tour["categories"]
    assert cats["agents_models"] == ["Architecture", "Sous-agents"]  # exactement deux onglets, pas de « Brains »
    assert "Runtime & CLI" in cats["advanced_diagnostics"] and "Work Methods apprises" in cats["advanced_diagnostics"]
    assert "Comportement" in cats["voice_audio"]
    flat = [label for labels in cats.values() for label in labels]
    for gone in ("Agent principal", "Modèles des sous-agents", "Rôles des sous-agents", "Brains", "Agent / CLI"):
        assert gone not in flat, gone
    s = tour["sections"]
    for page in ("architecture", "subagents"):
        assert s[page]["category"] == "agents_models" and not s[page]["footer"], s[page]
        assert s[page]["forbidden"] == [] and s[page]["forbiddenLabels"] == [], s[page]
    assert s["architecture"]["canvas"] and s["subagents"]["roles"]
    rt = s["runtime_cli"]
    assert rt["category"] == "advanced_diagnostics" and rt["footer"] and rt["cmd"] and rt["perm"]
    assert rt["mode"] and rt["routing"] and rt["catalog"]
    assert s["agent_behavior"]["category"] == "voice_audio" and s["agent_behavior"]["behavior"] == 2
    assert tour["legacy"] == {
        "main_agent": ["agents_models", "architecture", "alias"],
        "subagent_models": ["agents_models", "subagents", "alias"],
        "subagents": ["agents_models", "subagents", "section"],
        # `cli` et `routing` ne sont plus des alias (Slice 09 de settings-ui-reorganization) : rien ne bouge.
        "cli": ["voice_audio", "agent_behavior", None], "routing": ["voice_audio", "agent_behavior", None]}
    assert out["console"] == [], out["console"]


IN_PANEL = "(()=>{const a=document.activeElement,w=document.querySelector('.bcp-win');return !!(w&&a&&w.contains(a))})()"
OPEN_CORE = [
    click("[data-architecture-page] [data-arch-menu-btn=core]"),
    wait("!!document.querySelector('[data-arch-menu=configure]')"),
    click("[data-arch-menu=configure]"),
    wait("!!document.querySelector('.bcp-win [data-bcp-radio=delegation]')", 10000),
]
GEOMETRY = """(()=>{const w=document.querySelector('.bcp-win').getBoundingClientRect(),
  n=document.querySelector('[data-architecture-page] [data-arch-node=core]').getBoundingClientRect();
  const ox=Math.max(0,Math.min(w.right,n.right)-Math.max(w.left,n.left)),oy=Math.max(0,Math.min(w.bottom,n.bottom)-Math.max(w.top,n.top));
  return {overlap:ox*oy,inViewport:w.left>=0&&w.top>=0&&w.right<=innerWidth&&w.bottom<=innerHeight,
    inOverlay:document.getElementById('overlay').contains(document.querySelector('.bcp-win')),
    radios:document.querySelectorAll('.bcp-win [data-bcp-radio=delegation]').length}})()"""
SPAWN = ("(()=>{const c=((ARCH.view&&ARCH.view.state.snapshot||{}).connections||[]).find(x=>x.id==='core.agents->subagents.spawn');"
         "return c?[c.enabled,c.mutability]:null})()")


async def test_architecture_canvas_and_core_window_work_together_then_subagents_tab(served):
    folder = shots()
    shot = (lambda name: [{"a": "shot", "path": str(folder / name)}]) if folder else (lambda name: [])
    actions = [
        *OPEN, *shot("architecture-canvas.png"),
        eval_(SPAWN, "spawn_before"),
        *OPEN_CORE, *shot("architecture-core-window.png"),
        eval_(GEOMETRY, "geometry"), eval_(IN_PANEL, "focus_in"),
        key("Tab"), key("Tab"), key("Tab"), key("Tab", shift=True), eval_(IN_PANEL, "tab_kept"),
        key("Escape"), wait("document.querySelector('.bcp-win')===null"),
        eval_("[SET.open,SET.section]", "after_escape"),
        *OPEN_CORE,
        click(".bcp-win [data-bcp-radio=delegation][data-bcp-value=never]"),
        click(".bcp-win [data-bcp-act=apply]"),
        wait(SPAWN + "&&" + SPAWN + "[0]===false", 10000),
        eval_(SPAWN, "spawn_after"), *shot("architecture-after-never.png"),
        click("#modalTabs [data-section=subagents]"),
        wait("document.querySelector('.bcp-win')===null&&!!document.querySelector('[data-subagent-settings-host]')", 10000),
        wait("!!document.querySelector('[data-sar-route]')", 15000), *shot("subagents-tab.png"),
        eval_("[!!document.querySelector('[data-sar-route]'),SET.section,ARCH.view===null&&ARCH.panel===null]", "subagents"),
    ]
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": actions}])
    step = out["steps"][0]
    assert_waits(step)
    assert got(step, "spawn_before") == [True, "governed"]
    geometry = got(step, "geometry")
    assert geometry["overlap"] == 0 and geometry["inViewport"] and geometry["inOverlay"], geometry
    assert geometry["radios"] == 5
    assert got(step, "focus_in") is True and got(step, "tab_kept") is True
    assert got(step, "after_escape") == [True, "architecture"]  # Échap ferme la fenêtre, pas les Réglages
    assert got(step, "spawn_after") == [False, "governed"]
    assert got(step, "subagents") == [True, "subagents", True]
    patches = [r for r in out["requests"] if r["method"] == "PATCH" and r["path"] == "/api/brains/core/config"]
    assert len(patches) == 1 and json.loads(patches[0]["body"])["delegation"] == "never"
    stored = json.loads((served.runtime / "brain-config.json").read_text(encoding="utf-8"))
    assert stored["brains"]["core"]["delegation"] == "never"
    paths = {r["path"] for r in out["requests"]}
    assert {"/api/architecture", "/api/architecture/layout", "/api/subagent-role-routing"} <= paths
    assert out["console"] == [], out["console"]


SAVE = [
    eval_("(selectTab('agent_behavior'),0)"),
    wait("!!document.querySelector('[data-behavior-field=response_verbosity]')"),
    eval_("""(()=>{const s=document.querySelector('[data-behavior-field=response_verbosity]');s.value='detailed';
      s.dispatchEvent(new Event('change',{bubbles:true}));return s.value})()""", "picked"),
    # Le brouillon survit à un passage par Architecture & Agents (deux onglets) et par Avancé.
    click("#settingsCategories [data-category=agents_models]"),
    wait("!!document.querySelector('[data-architecture-page]')"),
    click("#modalTabs [data-section=subagents]"),
    click("#settingsCategories [data-category=advanced_diagnostics]"),
    eval_("(selectTab('agent_behavior'),0)"),
    wait("!!document.querySelector('[data-behavior-field=response_verbosity]')"),
    eval_("document.querySelector('[data-behavior-field=response_verbosity]').value", "kept"),
    click("#modalSave"),
    wait("document.getElementById('modalStatus').textContent==='Enregistré.'"),
]


async def test_saving_from_behavior_posts_the_unchanged_payload_and_reads_back(served):
    out = await drive(served.url, [
        {"width": 1440, "height": 900, "actions": [*OPEN, *SAVE]},
        {"width": 1440, "height": 900, "actions": [*OPEN, eval_("(selectTab('agent_behavior'),0)"),
                                                   wait("!!document.querySelector('[data-behavior-field=response_verbosity]')"),
                                                   eval_("document.querySelector('[data-behavior-field=response_verbosity]').value", "reloaded")]},
    ])
    assert_waits(out["steps"][0])
    assert got(out["steps"][0], "picked") == "detailed" and got(out["steps"][0], "kept") == "detailed"
    posts = [r for r in out["requests"] if r["method"] == "POST" and r["path"] == "/api/settings"]
    assert len(posts) == 1
    body = json.loads(posts[0]["body"])
    # Même charge qu'avant : un seul brouillon partagé, rien de propre aux sections ni aux onglets.
    assert sorted(body) == ["agenda_reminders", "audio", "cli", "routing", "voice"]
    assert list(body["cli"]) == ["agent", "settings", "delegation_mode", "behavior"]
    assert list(body["routing"]) == ["profiles"]
    assert body["cli"]["behavior"]["response_verbosity"] == "detailed"
    assert served.stored()["agent_behavior"]["response_verbosity"] == "detailed"
    assert got(out["steps"][1], "reloaded") == "detailed"
    assert out["console"] == [], out["console"]


#: L'élément actif : son nœud de canevas, son entrée de menu ou son id, et l'état ouvert des Réglages.
ACTIVE = ("(()=>{const e=document.activeElement;return [SET.open,e&&(e.getAttribute('data-arch-node')||"
          "e.getAttribute('data-arch-menu')||e.id||e.tagName)]})()")


async def test_escape_in_a_node_menu_opened_by_keyboard_closes_the_menu_not_the_settings(served):
    """Constat de la Slice 08 en bac à sable : Maj+F10 sur Core ouvre son menu, Échap le fermait ET fermait les
    Réglages — le raccourci global `ui_close` (écoute de `window`) ignorait l'Échap déjà consommée par le canevas.
    Attendu : Échap ferme le menu, le focus revient au nœud, les Réglages restent ; une Échap libre les ferme."""

    focus_core = eval_("(()=>{const n=document.querySelector('[data-architecture-page] [data-arch-node=core]');"
                       "n.focus();return document.activeElement===n})()", "focused")
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN, wait("new Promise(r=>setTimeout(()=>r(true),1500))", 4000), focus_core,
        key("F10", shift=True), wait("!!document.querySelector('[data-arch-menu=configure]')", 4000),
        eval_(ACTIVE, "menu_open"),
        key("Escape"), wait("!document.querySelector('[data-arch-menu=configure]')", 4000),
        eval_(ACTIVE, "after_first_escape"),
        key("Escape"), wait("SET.open===false", 4000),
        eval_("SET.open", "after_second_escape"),
    ]}])
    step = out["steps"][0]
    assert_waits(step)
    assert got(step, "focused") is True
    assert got(step, "menu_open") == [True, "configure"]
    assert got(step, "after_first_escape") == [True, "core"]
    assert got(step, "after_second_escape") is False
    assert out["console"] == [], out["console"]


#: Le modèle de Core choisi dans sa fenêtre, appliqué, puis le brouillon `/api/settings` que la page garde.
PICK_MODEL = """(()=>{const s=document.querySelector('.bcp-win [data-bcp-input=model]');s.value='claude-haiku-5';
  s.dispatchEvent(new Event('change',{bubbles:true}));return s.value})()"""
CLI_DRAFT = "[SET.draft.cli.agent,(SET.draft.cli.settings.claude||{}).model,SET.data.cli.agent,(SET.data.cli.settings.claude||{}).model]"


async def test_a_core_model_saved_in_its_window_survives_a_footer_save_of_behavior(served, monkeypatch):
    """I-002 point 1 (QA S07) : `syncCoreCliDraft`. Le modèle de Core change dans la fenêtre du cerveau
    (`PATCH /api/brains/core/config`), puis « Enregistrer » de Comportement envoie la charge `/api/settings` entière,
    `cli.agent` et `cli.settings` compris : elle porte le modèle choisi, pas l'ancien, et le réglage relu le garde."""

    from tests.unit.test_brain_config import fake_catalog

    served.control.brain_config._catalog = fake_catalog  # même place que le fournisseur réel, sans réseau
    monkeypatch.setattr(served.control, "_apply_agent_settings", lambda settings: None)  # aucun CLI à reconfigurer
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN, eval_(CLI_DRAFT, "draft_before"), *OPEN_CORE,
        wait("!!document.querySelector('.bcp-win [data-bcp-input=model] option[value=claude-haiku-5]')", 8000),
        eval_(PICK_MODEL, "model_picked"),
        click(".bcp-win [data-bcp-act=apply]"),
        wait("!document.querySelector('.bcp-win [data-bcp-act=apply]:not([disabled])')||"
             "(ARCH.panel&&!ARCH.panel.dirty&&!ARCH.panel.state.saving)", 10000),
        eval_(CLI_DRAFT, "draft_after"),
        key("Escape"), wait("document.querySelector('.bcp-win')===null"),
        *SAVE,
    ]}])
    step = out["steps"][0]
    assert_waits(step)
    assert got(step, "model_picked") == "claude-haiku-5"
    assert got(step, "draft_before")[0] == "claude" and got(step, "draft_before")[1] in ("", None)
    assert got(step, "draft_after") == ["claude", "claude-haiku-5", "claude", "claude-haiku-5"]
    patches = [json.loads(r["body"]) for r in out["requests"] if r["method"] == "PATCH" and r["path"] == "/api/brains/core/config"]
    assert len(patches) == 1 and patches[0]["model"] == "claude-haiku-5"
    posts = [json.loads(r["body"]) for r in out["requests"] if r["method"] == "POST" and r["path"] == "/api/settings"]
    assert len(posts) == 1
    assert posts[0]["cli"]["agent"] == "claude" and posts[0]["cli"]["settings"]["claude"]["model"] == "claude-haiku-5"
    assert served.stored()["agent_cli_settings"]["claude"]["model"] == "claude-haiku-5"
    assert served.stored()["agent_behavior"]["response_verbosity"] == "detailed"
    assert out["console"] == [], out["console"]


#: Chaque onglet de la catégorie et les sections d'Avancé, divulgations ouvertes, catalogue chargé : rien ne dépasse.
LAYOUT = """(async()=>{const pause=ms=>new Promise(r=>setTimeout(r,ms)),out=[];
  for(const id of ['architecture','subagents','agent_behavior','runtime_cli','work_methods']){
    selectTab(id);await pause(id==='architecture'||id==='subagents'?1500:500);
    document.querySelectorAll('#modalContent details').forEach(d=>{d.open=true});
    await pause(id==='runtime_cli'?2500:600);
    document.querySelectorAll('#modalContent details').forEach(d=>{d.open=true});await pause(300);
    const body=document.getElementById('modalContent'),main=document.getElementById('settingsMain');
    const wide=[...body.querySelectorAll('*')].filter(e=>e.getBoundingClientRect().right>body.getBoundingClientRect().right+1&&!e.closest('.catalog-scroll,.catalog-filters,[class*=scroll]'))
      .slice(0,3).map(e=>e.tagName+'.'+e.className);
    out.push({id,page:document.documentElement.scrollWidth-innerWidth,content:body.scrollWidth-body.clientWidth,
      main:main.scrollWidth-main.clientWidth,opened:body.querySelectorAll('details[open]').length,wide});
  }
  return out})()"""


@pytest.mark.parametrize(("width", "height"), [(1920, 1080), (1366, 768), (1536, 864), (1093, 614)])
async def test_no_section_overflows_with_disclosures_open(served, width, height):
    """1536×864 et 1093×614 : la largeur CSS de 1920×1080 et 1366×768 à 125 % de zoom."""
    out = await drive(served.url, [{"width": width, "height": height, "actions": [*OPEN, eval_(LAYOUT, "layout")]}])
    layout = got(out["steps"][0], "layout")
    assert [row["id"] for row in layout] == ["architecture", "subagents", "agent_behavior", "runtime_cli", "work_methods"]
    for row in layout:
        assert row["page"] <= 0 and row["content"] <= 1 and row["main"] <= 0, row
    assert any(row["opened"] for row in layout if row["id"] == "runtime_cli")
