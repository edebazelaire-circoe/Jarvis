"""Le shell des Réglages à six catégories, mesuré dans un vrai Chrome sans tête (Slice 02).

Handoff `jarvis-settings-ui-reorganization`, contrat `docs/settings/settings-shell.md`. Un VRAI Control Center
isolé (runtime temporaire, port libre ; fixture `served` de `test_wake_word_settings_browser.py`) sert la page ;
le harnais CDP de ce fichier-là envoie de vraies frappes et de vrais clics. Ce que ce fichier prouve :

- six catégories dessinées depuis le registre, la première sélectionnée et focalisée à l'ouverture ;
- flèches, Début, Fin déplacent le focus sans rien ouvrir ; Entrée ouvre ; le focus clavier se voit ;
- `ui_tab_next` / `ui_tab_prev` (Ctrl+flèches) parcourent les six catégories, en boucle ;
- un clic dans le vide du shell ne ferme pas ; Échap ferme, même depuis un champ, et rend le focus à
  l'élément d'ouverture (« Plus d’outils », qui tient le bouton Réglages) ; le bouton « Fermer » ferme ;
- aucune catégorie ne déborde en largeur à 1920×1080 et 1366×768, à 100 % et 125 % de zoom ;
- `prefers-reduced-motion` coupe l'animation d'ouverture.

Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import pytest

from tests.unit.test_wake_word_settings_browser import click, drive, eval_, got, key, served, wait, open_settings  # noqa: F401

CATEGORY_IDS = ["voice_audio", "agents_models", "memory_knowledge", "interface_interactions", "connections",
                "advanced_diagnostics"]

OPEN = [
    wait("!!document.getElementById('openSettings')"),
    click("#dockMore"), *open_settings(),
    wait("document.querySelectorAll('#settingsCategories [role=tab]').length===6&&!!document.querySelector('#modalTabs [role=tab]')"),
]

HUB_OPEN = [wait("!!document.getElementById('openSettings')"), click("#dockMore"), click("#openSettings"),
            wait("!!document.querySelector('#settingsHubGrid [data-hub-category]')")]

STATE = """(()=>{const ae=document.activeElement,q=s=>document.querySelector(s);
  return {open:document.getElementById('overlay').classList.contains('open'),
    cats:[...document.querySelectorAll('#settingsCategories [role=tab]')].map(b=>b.dataset.category),
    labels:[...document.querySelectorAll('#settingsCategories .set-cat-label')].map(s=>s.textContent),
    selected:(q('#settingsCategories [aria-selected=true]')||{dataset:{}}).dataset.category||null,
    items:[...document.querySelectorAll('#modalTabs [role=tab]')].map(b=>b.textContent),
    focus:ae?(ae.id||ae.tagName):null,
    ring:ae&&ae!==document.body?getComputedStyle(ae).outlineStyle:null,
    title:(q('#settingsCategoryTitle')||{}).textContent||null}})()"""

#: Ctrl+flèche, le raccourci par défaut de `ui_tab_next` / `ui_tab_prev`, sur le corps de la page.
CTRL = "(document.body.dispatchEvent(new KeyboardEvent('keydown',{{key:'{key}',ctrlKey:true,bubbles:true}})),1)"

LAYOUT = """(async()=>{const R=window.JarvisSettingsRegistry,out=[];
  for(const c of R.CATEGORY_IDS){
    document.querySelector(`#settingsCategories [data-category=${c}]`).click();
    await new Promise(r=>setTimeout(r,450));
    const shell=document.getElementById('settingsShell'),close=document.getElementById('closeModal').getBoundingClientRect();
    const rail=[...document.querySelectorAll('#settingsCategories [role=tab]')].map(b=>b.getBoundingClientRect());
    const body=document.getElementById('modalContent');
    out.push({c,page:document.documentElement.scrollWidth-innerWidth,shell:shell.scrollWidth-shell.clientWidth,
      main:document.getElementById('settingsMain').scrollWidth-document.getElementById('settingsMain').clientWidth,
      closeInside:close.left>=0&&close.right<=innerWidth&&close.top>=0&&close.bottom<=innerHeight,
      railInside:rail.every(r=>r.left>=0&&r.right<=innerWidth+0.5),bodyHeight:body.clientHeight,
      clipped:[...document.querySelectorAll('#settingsCategories .set-cat-desc')].filter(d=>d.getClientRects().length&&d.scrollHeight>d.clientHeight+1).map(d=>d.textContent),
      title:document.getElementById('settingsCategoryTitle').textContent});
  }
  return out})()"""


def _state(id_: str) -> dict:
    return eval_(STATE, id_)


async def test_categories_keyboard_shortcuts_escape_and_focus_return(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN, _state("opened"),
        {**key("ArrowDown"), "id": "down"}, _state("afterDown"),
        {**key("End"), "id": "end"}, {**key("Home"), "id": "home"}, {**key("ArrowUp"), "id": "wrap"},
        {**key("Enter"), "id": "enter"}, wait("(document.querySelector('#settingsCategories [aria-selected=true]')||{dataset:{}}).dataset.category==='advanced_diagnostics'"),
        _state("entered"),
        eval_(CTRL.format(key="ArrowRight")), _state("next"),
        eval_(CTRL.format(key="ArrowLeft")), eval_(CTRL.format(key="ArrowLeft")), _state("prev"),
        click("#modalContent"), _state("clickedVoid"),
        # Plugins & MCP s'ouvre sur Plugins MCP (des boutons) : les champs sont dans Fournisseurs.
        click("#modalTabs [data-section=providers]"),
        wait("!!document.querySelector('#settingsShell #modalContent input:not([type=hidden]),#settingsShell #modalContent select')", 10000),
        # Échap depuis un champ ordinaire (la recherche du catalogue ou n'importe quel champ) ferme quand même.
        eval_("(()=>{const f=document.querySelector('#settingsShell input:not([type=hidden]),#settingsShell select');if(f)f.focus();return f?f.tagName:null})()", "field"),
        {**key("Escape"), "id": "escape"}, _state("closed"),
        *OPEN, click("#closeModal"), _state("closedByButton"),
    ]}])
    step = out["steps"][0]
    opened = got(step, "opened")
    assert opened["open"] and opened["cats"] == CATEGORY_IDS and len(set(opened["labels"])) == 6
    assert opened["selected"] == "voice_audio" and opened["focus"] == "settingsCat-voice_audio"
    assert opened["items"] == ["Thème & scène visuelle", "Comportement", "Conversation", "Voix & transcription",
                               "Micro & son", "Tours & interruptions", "Mot d’éveil"]
    assert opened["title"] == "Personnalisation"
    after_down = got(step, "afterDown")
    assert after_down["focus"] == "settingsCat-agents_models" and after_down["selected"] == "voice_audio"  # rien n'est ouvert
    assert after_down["ring"] not in (None, "none")  # focus clavier visible
    focused = {a["id"]: a["focused"] for a in step["actions"] if a.get("a") == "key" and a.get("id")}
    assert focused["end"] == "settingsCat-advanced_diagnostics" and focused["home"] == "settingsCat-voice_audio"
    assert focused["wrap"] == "settingsCat-advanced_diagnostics"
    entered = got(step, "entered")
    assert entered["selected"] == "advanced_diagnostics" and entered["focus"] == "settingsCat-advanced_diagnostics"
    # Slice 08 : entrées rangées par groupe déclaré ; « Prompts » et « Scène constellation » sont des sections.
    assert entered["items"] == ["Architecture & compatibilité", "Prompts", "Runtime & CLI", "Diagnostics",
                                "Scène constellation", "Work Methods apprises", "Bare Hands · essais"]
    assert got(step, "next")["selected"] == "voice_audio"  # Ctrl+→ en boucle après la sixième
    assert got(step, "prev")["selected"] == "connections"  # Ctrl+← deux fois : Avancé, puis Plugins & MCP
    assert got(step, "clickedVoid")["open"] is True  # pas de fermeture au clic dans le shell
    closed = got(step, "closed")
    assert closed["open"] is False and closed["focus"] == "dockMore"  # rendu à « Plus d’outils »
    assert got(step, "closedByButton")["open"] is False
    assert got(step, "field") in ("INPUT", "SELECT")  # un vrai champ avait le focus quand Échap a fermé
    assert out["console"] == [], out["console"]


INSIDE = "document.getElementById('settingsShell').contains(document.activeElement)"


async def test_tab_trap_textarea_body_focus_and_save_keep_the_focus_contract(served):
    """QA Slice 02 : piège de Tab, exception des zones de texte, Échap et Tab depuis `body` avec `ui_close`
    réaffecté, focus rendu au bouton Enregistrer après l'envoi."""
    last = ("(()=>{const all=[...document.querySelectorAll('#settingsShell button,#settingsShell input,#settingsShell select,"
            "#settingsShell textarea,#settingsShell summary,#settingsShell a[href],#settingsShell [tabindex]')]"
            ".filter(e=>!e.disabled&&e.tabIndex>=0&&e.getClientRects().length>0);all[all.length-1].focus();return all.length})()")
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN, wait("!!document.getElementById('modalSave')&&!document.querySelector('#modalContent .empty')"),
        eval_(last, "count"), {**key("Tab"), "id": "wrapForward"}, eval_(INSIDE, "afterWrap"),
        eval_("document.querySelector('#settingsCategories [aria-selected=true]').focus(),1"),
        {**key("Tab", shift=True), "id": "wrapBack"}, eval_(INSIDE, "afterBack"),
        eval_("(()=>{const a=document.createElement('textarea');a.id='s02Area';document.getElementById('modalContent').prepend(a);a.focus();return document.activeElement.id})()", "area"),
        {**key("Escape"), "id": "escArea"}, _state("afterAreaEscape"),
        eval_("(SET.shortcuts.values.ui_close='q',document.activeElement.blur(),document.activeElement===document.body)", "onBody"),
        {**key("Tab"), "id": "tabFromBody"}, eval_(INSIDE, "afterBodyTab"),
        eval_("(document.activeElement.blur(),document.activeElement===document.body)", "onBodyAgain"),
        {**key("Escape"), "id": "escBody"}, _state("afterBodyEscape"),
        *OPEN, wait("!!document.getElementById('modalSave')&&!document.querySelector('#modalContent .empty')"),
        eval_("document.getElementById('modalSave').focus(),1"), {**key("Enter"), "id": "save"},
        wait("/Enregistré|rror|Erreur/.test(document.getElementById('modalStatus').textContent)&&!document.getElementById('modalSave').disabled", 8000),
        eval_("({focus:document.activeElement.id,status:document.getElementById('modalStatus').textContent})", "saved"),
    ]}])
    step = out["steps"][0]
    assert got(step, "count") > 3
    assert got(step, "afterWrap") is True and got(step, "afterBack") is True  # Tab boucle dans le shell
    assert got(step, "area") == "s02Area" and got(step, "afterAreaEscape")["open"] is True  # saisie longue : pas de fermeture
    assert got(step, "onBody") is True and got(step, "afterBodyTab") is True  # depuis body, Tab entre dans le shell
    assert got(step, "onBodyAgain") is True and got(step, "afterBodyEscape")["open"] is False  # Échap malgré ui_close='q'
    saved = got(step, "saved")
    assert saved["focus"] == "modalSave", saved
    assert out["console"] == [], out["console"]


@pytest.mark.parametrize(("width", "height"), [(1920, 1080), (1366, 768), (1536, 864), (1093, 614)])
async def test_no_category_overflows_at_desktop_sizes_and_125_percent_zoom(served, width, height):
    """1536×864 et 1093×614 : la largeur CSS de 1920×1080 et 1366×768 à 125 % de zoom."""
    out = await drive(served.url, [{"width": width, "height": height, "actions": [*OPEN, eval_(LAYOUT, "layout")]}])
    layout = got(out["steps"][0], "layout")
    assert [row["c"] for row in layout] == CATEGORY_IDS
    for row in layout:
        assert row["page"] <= 0 and row["shell"] <= 0 and row["main"] <= 0, row
        assert row["closeInside"] and row["railInside"], row
        assert row["clipped"] == [], row  # aucune description de catégorie tronquée
        assert row["bodyHeight"] > 150, row  # le contenu garde de la place pour défiler
    assert out["console"] == [], out["console"]


async def test_reduced_motion_stops_the_opening_animation(served):
    probe = "getComputedStyle(document.getElementById('overlay')).animationName"
    out = await drive(served.url, [
        # L'ouverture se joue au hub (2026-10-23) ; entrer dans une catégorie ne rejoue pas le fondu.
        {"width": 1440, "height": 900, "reducedMotion": True, "actions": [*HUB_OPEN, eval_(probe, "reduced")]},
        {"width": 1440, "height": 900, "actions": [*HUB_OPEN, eval_(probe, "normal")]},
    ])
    assert got(out["steps"][0], "reduced") == "none"
    assert got(out["steps"][1], "normal") == "set-fade"


COMPARE_OPEN = """(async()=>{const d=document.querySelector('#voiceSection_voice_output details.rd');d.open=true;
  await new Promise(r=>setTimeout(r,1500));
  const body=document.getElementById('modalContent'),filters=document.querySelector('#voiceCatalog .catalog-filters');
  return {open:d.open,page:document.documentElement.scrollWidth-innerWidth,content:body.scrollWidth-body.clientWidth,
    details:d.getBoundingClientRect().right<=body.getBoundingClientRect().right+0.5,
    filters:!!filters,catalog:!!document.querySelector('#voiceCatalog').children.length}})()"""


@pytest.mark.parametrize(("width", "height"), [(1366, 768), (1093, 614)])
async def test_open_voice_model_comparison_does_not_overflow(served, width, height):
    """QA Slice 03 (B4) : « Comparer les modèles vocaux » ouvert à 1366×768 faisait déborder le contenu de 57 px
    (filtres du catalogue à 2120 px). Les filtres défilent désormais dans le catalogue, comme dans Agents & modèles.
    1093×614 : 1366×768 à 125 % de zoom."""

    out = await drive(served.url, [{"width": width, "height": height, "actions": [
        *OPEN,
        click("#modalTabs [data-section=voice_output]"),
        wait("!!document.querySelector('#voiceSection_voice_output details.rd')"),
        eval_(COMPARE_OPEN, "compare"),
    ]}])
    seen = got(out["steps"][0], "compare")
    assert seen["open"] is True and seen["catalog"] is True, seen
    assert seen["page"] <= 0 and seen["content"] <= 1 and seen["details"] is True, seen
