"""Interface & interactions et les entrées Bare Hands d'Avancé, dans un vrai Chrome sans tête (Slice 06).

Handoff `jarvis-settings-ui-reorganization`, contrat `docs/settings/interface-interactions.md`. Un VRAI Control Center
isolé (fixture `served` de `test_wake_word_settings_browser.py`) sert la page ; le harnais CDP de ce fichier-là envoie
de vraies frappes et de vrais clics. Ce que ce fichier prouve :

- Interface & interactions montre trois sections (Thème & scène visuelle, Raccourcis, Bare Hands), plus aucun onglet
  `appearance` ni `shortcuts` ; `experimental` mène à la porte de test de la scène, section `scene_gate` d'Avancé
  (Slice 08) ;
- anciens identifiants et ancres Bare Hands mènent à leur section ;
- `wake_toggle` a exactement un éditeur dans toutes les sections de toutes les catégories ;
- capture d'un raccourci : Échap l'annule sans fermer les Réglages ; une touche l'enregistre, le focus reste sur la
  touche ; Voix › Tours montre la nouvelle touche, et son lien pose le focus sur l'éditeur ; quitter la section pendant
  une capture l'annule (aucun envoi) ;
- un thème s'applique tout de suite, garde le focus, persiste après rechargement (même clé `localStorage`) ; les
  réglages de la scène s'écrivent sous leur clé et se réinitialisent ;
- Bare Hands : une préférence s'enregistre, la réinitialisation rend les défauts, et rien n'allume ni n'éteint l'outil ;
- aucune section ne déborde en largeur à 1920×1080 et 1366×768, 100 % et 125 %, détails ouverts.

Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import json

import pytest

from tests.unit.test_wake_word_settings_browser import click, drive, eval_, got, key, served, wait  # noqa: F401

INTERFACE = ["theme_scene", "shortcuts", "bare_hands"]
OPEN = [
    wait("!!document.getElementById('openSettings')"),
    click("#dockMore"), click("#openSettings"),
    wait("!!document.getElementById('voiceSection_conversation')"),
    click("#settingsCategories [data-category=interface_interactions]"),
    wait("!!document.querySelector('#modalContent .theme-choice')"),
]

TOUR = """(async()=>{const pause=ms=>new Promise(r=>setTimeout(r,ms)),q=s=>document.querySelector(s);
  const out={labels:[...document.querySelectorAll('#modalTabs [role=tab]')].map(b=>b.textContent),
    related:!!document.getElementById('settingsRelated'),tabs:[],editors:{},voiceKeys:0};
  const R=window.JarvisSettingsRegistry;
  for(const c of R.CATEGORY_IDS){q(`#settingsCategories [data-category=${c}]`).click();await pause(150);
    const entries=[...document.querySelectorAll('#modalTabs [role=tab]')].map(b=>({tab:b.dataset.tab||null,section:b.dataset.section||null}));
    for(const e of entries){if(e.tab)out.tabs.push([c,e.tab]);selectTab(e.section||e.tab);await pause(e.section==='turns_interruptions'?900:250);
      const n=document.querySelectorAll('#modalContent [data-shortcut="wake_toggle"]').length;if(n)out.editors[e.section||e.tab]=n;
      out.voiceKeys+=document.querySelectorAll('#modalContent [data-voice-context="wake_toggle"] kbd').length}}
  out.alias={};for(const id of ['theme_scene','appearance','barehandsSettings','barehandsCalibration','barehandsRecord',
    'barehandsBenchmarkSection','experimental','shortcuts','interface_interactions']){selectTab(id);await pause(200);
    out.alias[id]=[SET.category,SET.section,(R.page.resolve(id)||{source:null}).source]}
  selectTab('bare_hands');await pause(300);
  out.ordinary={diag:!!q('#modalContent [data-barehands-check=diagnostics]'),preview:!!q('#modalContent [data-barehands-check=targetPreview]'),
    calibrate:!!q('#barehandsCalibrate'),wipe:!!q('#barehandsProfileReset'),bench:!!q('#barehandsBenchmark'),record:!!q('#barehandsRecordStart'),
    assets:!!q('#barehandsAssets'),footer:!q('.set-foot').hidden};
  selectTab('barehands_lab');await pause(300);
  out.lab={diag:!!q('#modalContent [data-barehands-check=diagnostics]'),preview:!!q('#modalContent [data-barehands-check=targetPreview]'),
    bench:!!q('#barehandsBenchmark'),record:!!q('#barehandsRecordStart'),category:SET.category};
  selectTab('diagnostics');await pause(600);
  out.diag={part:!!q('#diagnostic_barehands'),assets:(q('#diagnostic_barehands #barehandsAssets')||{}).textContent||'',
    voice:!!q('#diagnostic_barehands #barehandsVoice')};
  selectTab('scene_gate');await pause(400);out.experimental={scene:!!q('#sceneSettings'),bh:!!q('#modalContent .bh-section')};
  return out})()"""


async def test_sections_aliases_single_wake_editor_and_barehands_split(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [*OPEN, eval_(TOUR, "tour")]}])
    tour = got(out["steps"][0], "tour")
    assert tour["labels"] == ["Thème & scène visuelle", "Raccourcis", "Bare Hands"]
    assert tour["related"] is False, "plus de zone « encore dans » (Slice 09)"
    # Plus aucun onglet hérité : `keys` (Slice 07, Fournisseurs de Connexions), `prompts` et `experimental` (Slice 08,
    # sections Prompts et Scène constellation d'Avancé) non plus.
    assert tour["tabs"] == []
    # `wake_toggle` : un seul éditeur, dans Raccourcis ; Voix › Tours n'en montre que la touche.
    assert tour["editors"] == {"shortcuts": 1}
    assert tour["voiceKeys"] == 1
    alias = tour["alias"]
    # Slice 09 : `appearance`, `experimental` et les ancres Bare Hands ne sont plus des alias (aucun appelant) : un
    # `selectTab` vers eux ne bouge rien ; `shortcuts` est l'ID de la section.
    assert alias["theme_scene"] == ["interface_interactions", "theme_scene", "section"]
    for retired in ("appearance", "barehandsSettings", "barehandsCalibration", "barehandsRecord", "barehandsBenchmarkSection",
                    "experimental"):
        assert alias[retired] == ["interface_interactions", "theme_scene", None], retired
    assert alias["shortcuts"] == ["interface_interactions", "shortcuts", "section"]
    assert alias["interface_interactions"] == ["interface_interactions", "shortcuts", "category"]  # dernière entrée ouverte
    assert tour["ordinary"] == {"diag": False, "preview": True, "calibrate": True, "wipe": True, "bench": False,
                                "record": False, "assets": False, "footer": False}
    assert tour["lab"] == {"diag": True, "preview": False, "bench": True, "record": True, "category": "advanced_diagnostics"}
    assert tour["diag"]["part"] and tour["diag"]["voice"] and "MediaPipe" in tour["diag"]["assets"]
    assert tour["experimental"] == {"scene": True, "bh": False}
    assert out["console"] == [], out["console"]


FOCUS = "(()=>{const e=document.activeElement;return e?{id:e.id,shortcut:e.dataset&&e.dataset.shortcut||null,tag:e.tagName}:null})()"
KEYCAP = "#modalContent [data-shortcut=\"wake_toggle\"]"


async def test_capture_cancel_save_and_link_from_voice_focuses_the_editor(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN,
        click("#modalTabs [data-section=shortcuts]"),
        wait(f"!!document.querySelector('{KEYCAP}')"),
        eval_(f"document.querySelector('{KEYCAP}').textContent", "before"),
        click(KEYCAP),
        eval_("[!!SET.capture,document.querySelector('#modalContent .keycap.capturing')!==null]", "capturing"),
        key("Escape"),
        eval_(f"[SET.open,!!SET.capture,document.querySelector('{KEYCAP}').textContent,document.getElementById('shortcutHint').textContent]",
              "cancelled"),
        # Quitter la section pendant une capture l'annule : la frappe suivante n'enregistre rien.
        click(KEYCAP),
        click("#modalTabs [data-section=theme_scene]"),
        eval_("!!SET.capture", "left"),
        key("F10"),
        click("#modalTabs [data-section=shortcuts]"),
        wait(f"!!document.querySelector('{KEYCAP}')"),
        click(KEYCAP),
        key("F11"),
        wait(f"document.querySelector('{KEYCAP}').textContent==='f11'"),
        eval_(FOCUS, "after_save"),
        click("#settingsCategories [data-category=voice_audio]"),
        click("#modalTabs [data-section=turns_interruptions]"),
        wait("!!document.querySelector('#modalContent [data-voice-context=\"wake_toggle\"] kbd')", 8000),
        eval_("document.querySelector('#modalContent [data-voice-context=\"wake_toggle\"] kbd').textContent", "voice_key"),
        click("#modalContent [data-voice-open=shortcuts]"),
        eval_(FOCUS, "after_link"),
        eval_("[SET.category,SET.section]", "where"),
    ]}])
    step = out["steps"][0]
    before = got(step, "before")
    assert got(step, "capturing") == [True, True]
    # Échap pendant la capture : annulée, les Réglages restent ouverts, la touche revient.
    assert got(step, "cancelled") == [True, False, before, "Capture annulée."]
    assert got(step, "left") is False
    shortcut_posts = [json.loads(r["body"]) for r in out["requests"] if r["method"] == "POST" and r["path"] == "/api/shortcuts"]
    assert shortcut_posts == [{"shortcuts": {"wake_toggle": "f11"}}], "F10 frappé hors capture n'enregistre rien"
    assert got(step, "after_save")["shortcut"] == "wake_toggle", "le focus revient sur la touche redessinée"
    assert got(step, "voice_key") == "f11"
    assert got(step, "after_link")["shortcut"] == "wake_toggle", "le lien de Voix pose le focus sur l'éditeur"
    assert got(step, "where") == ["interface_interactions", "shortcuts"]
    assert out["console"] == [], out["console"]


THEME = """(()=>{const key=window.JarvisSceneView.KEY;return {theme:document.documentElement.dataset.jarvisTheme,
  stored:localStorage.getItem('jarvis.ui.theme'),view:localStorage.getItem(key),key,
  checked:(document.querySelector('#modalContent input[name=jarvisTheme]:checked')||{}).value||null,
  selected:[...document.querySelectorAll('#modalContent .theme-choice.selected input')].map(i=>i.value),
  focus:document.activeElement&&document.activeElement.name||document.activeElement.tagName,
  reset:(document.querySelector('#sceneViewSettings .sc-view-reset')||{}).disabled}})()"""
SLIDE = """(()=>{const r=document.querySelector('#sceneViewSettings input[type=range]:not([disabled])');
  r.value=String(Number(r.max));r.dispatchEvent(new Event('input',{bubbles:true}));r.dispatchEvent(new Event('change',{bubbles:true}));
  return r.id})()"""


async def test_theme_applies_in_place_persists_and_scene_view_resets(served):
    out = await drive(served.url, [
        {"width": 1440, "height": 900, "actions": [
            *OPEN, eval_(THEME, "initial"),
            click("#modalContent input[name=jarvisTheme][value=cosmos]"),
            eval_(THEME, "cosmos"),
            eval_(SLIDE, "slid"), eval_(THEME, "slid_state"),
            click("#sceneViewSettings .sc-view-reset"),
            eval_(THEME, "reset"),
        ]},
        {"width": 1440, "height": 900, "actions": [*OPEN, eval_(THEME, "reloaded"),
            click("#modalContent input[name=jarvisTheme][value=circuit-board]"), eval_(THEME, "back")]},
    ])
    first, second = out["steps"]
    initial, cosmos = got(first, "initial"), got(first, "cosmos")
    assert initial["theme"] == "circuit-board" and initial["checked"] == "circuit-board"
    # Appliqué tout de suite, sous la même clé, carte marquée en place, focus gardé sur le bouton radio.
    assert cosmos["theme"] == "cosmos" and cosmos["stored"] == "cosmos" and cosmos["selected"] == ["cosmos"]
    assert cosmos["focus"] == "jarvisTheme"
    slid = got(first, "slid_state")
    # Clé de la scène figée (QA Slice 06, N4) : la même que la scène lit au chargement.
    assert initial["key"] == "jarvis.scene.view"
    assert slid["view"] is not None and slid["reset"] is False and slid["key"] == initial["key"]
    reset = got(first, "reset")
    assert reset["reset"] is True and reset["view"] != slid["view"]
    reloaded = got(second, "reloaded")
    assert reloaded["theme"] == "cosmos" and reloaded["checked"] == "cosmos"
    assert got(second, "back")["stored"] == "circuit-board"
    assert out["console"] == [], out["console"]


BH_STATE = """(()=>({preview:document.querySelector('#modalContent [data-barehands-check=targetPreview]').checked,
  lifecycle:window.JarvisBarehands.lifecycle().state||window.JarvisBarehands.lifecycle(),
  enabled:window.JarvisBarehands.settings().enabled}))()"""


async def test_barehands_preference_saves_resets_and_never_touches_the_lifecycle(served):
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN,
        click("#modalTabs [data-section=bare_hands]"),
        wait("!!document.querySelector('#modalContent [data-barehands-check=targetPreview]')"),
        eval_(BH_STATE, "before"),
        click("#modalContent [data-barehands-check=targetPreview]"),
        wait("window.JarvisBarehands.settings().targetPreview===false"),
        eval_(BH_STATE, "saved"),
        click("#barehandsReset"),
        wait("!!document.querySelector('#confirmBack.open,#confirmBack:not([hidden])')&&!!document.getElementById('confirmGo')"),
        click("#confirmGo"),
        wait("window.JarvisBarehands.settings().targetPreview===true"),
        eval_(BH_STATE, "reset"),
        eval_("SET.open", "still_open"),
    ]}])
    step = out["steps"][0]
    before, saved, reset = got(step, "before"), got(step, "saved"), got(step, "reset")
    assert before["preview"] is True and saved["preview"] is False and reset["preview"] is True
    assert before["lifecycle"] == saved["lifecycle"] == reset["lifecycle"]
    assert before["enabled"] is False and saved["enabled"] is False and reset["enabled"] is False
    posts = [json.loads(r["body"]) for r in out["requests"] if r["method"] == "POST" and r["path"] == "/api/barehands"]
    assert len(posts) == 2 and posts[0]["target_preview"] is False and posts[1]["target_preview"] is True
    assert all(p["enabled"] is False for p in posts), "aucun réglage n'allume Bare Hands"
    assert got(step, "still_open") is True
    assert out["console"] == [], out["console"]


LAYOUT = """(async()=>{const pause=ms=>new Promise(r=>setTimeout(r,ms)),out=[];
  for(const id of %s){selectTab(id);await pause(500);
    document.querySelectorAll('#modalContent details').forEach(d=>{d.open=true});await pause(200);
    const body=document.getElementById('modalContent'),main=document.getElementById('settingsMain');
    const wide=[...body.querySelectorAll('*')].filter(e=>e.getBoundingClientRect().right>body.getBoundingClientRect().right+1)
      .slice(0,3).map(e=>e.tagName+'.'+e.className);
    out.push({id,page:document.documentElement.scrollWidth-innerWidth,content:body.scrollWidth-body.clientWidth,
      main:main.scrollWidth-main.clientWidth,wide})}
  return out})()""" % json.dumps([*INTERFACE, "barehands_lab", "diagnostics"])


@pytest.mark.parametrize(("width", "height"), [(1920, 1080), (1366, 768), (1536, 864), (1093, 614)])
async def test_no_interface_section_overflows(served, width, height):
    """1536×864 et 1093×614 : la largeur CSS de 1920×1080 et 1366×768 à 125 % de zoom."""
    out = await drive(served.url, [{"width": width, "height": height, "actions": [*OPEN, eval_(LAYOUT, "layout")]}])
    layout = got(out["steps"][0], "layout")
    assert [row["id"] for row in layout] == [*INTERFACE, "barehands_lab", "diagnostics"]
    for row in layout:
        assert row["page"] <= 0 and row["content"] <= 1 and row["main"] <= 0 and row["wide"] == [], row


LANDING = """(()=>{const e=document.activeElement;return {section:SET.section,focus:e?(e.id||e.dataset.section||e.tagName):null,
  entry:!!(e&&e.matches('#modalTabs [aria-selected=true]'))}})()"""


async def test_internal_links_never_drop_focus_on_body(served):
    """Mécanisme du shell (`openSettingsLink`) : l'élément visé s'il est dessiné (ici la partie Mot d'éveil des
    Diagnostics, cible du lien « Voir le diagnostic »), sinon l'entrée ouverte (« Régler la commande », renvois des
    sous-agents) ; jamais `body`."""
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN,
        eval_("(openSettingsLink('diagnostics',{focus:'#diagnostic_wake_word'}),0)"),
        eval_(LANDING, "wake"),
        eval_("(openSettingsLink('runtime_cli'),0)"),
        eval_(LANDING, "generic"),
        eval_("(openSettingsLink('subagent_models'),0)"),
        eval_(LANDING, "subagents"),
    ]}])
    step = out["steps"][0]
    assert got(step, "wake") == {"section": "diagnostics", "focus": "diagnostic_wake_word", "entry": False}
    assert got(step, "generic") == {"section": "runtime_cli", "focus": "runtime_cli", "entry": True}
    assert got(step, "subagents") == {"section": "subagent_models", "focus": "subagent_models", "entry": True}
    assert out["console"] == [], out["console"]


WAKE_DIAG = """(()=>{const p=document.getElementById('diagnostic_wake_word'),b=document.getElementById('modalContent');
  const t=p.getBoundingClientRect(),r=b.getBoundingClientRect(),v=document.getElementById('diagnostic_voice');
  return {focus:document.activeElement&&document.activeElement.id,top:Math.round(t.top-r.top),height:Math.round(r.height),
    visible:t.top>=r.top-1&&t.top<r.bottom-20,scroll:Math.round(b.scrollTop),voice:v?Math.round(v.getBoundingClientRect().height):0}})()"""


@pytest.mark.parametrize(("width", "height"), [(1440, 900), (1366, 768)])
async def test_wake_word_diagnostic_link_keeps_its_part_in_view_after_voice_fills(served, width, height):
    """QA Slice 06 (B1) : « Voir le diagnostic » du Mot d'éveil focalise sa partie ET la garde visible pendant que la
    partie Voix, au-dessus, grandit en se remplissant (maintien en vue du shell, `pinSettingsTarget`)."""
    served.settings_file.write_text(json.dumps({"wake_word": {"schema_version": 7, "enabled": True, "futur": 1}}),
                                    encoding="utf-8")
    out = await drive(served.url, [{"width": width, "height": height, "actions": [
        wait("!!document.getElementById('openSettings')"), click("#dockMore"), click("#openSettings"),
        wait("!!document.getElementById('voiceSection_conversation')", 10000),
        click("#modalTabs [data-section=wake_word]"),
        wait("!!document.querySelector('[data-ww-open-diagnostics]')", 10000),
        click("[data-ww-open-diagnostics]"),
        eval_(WAKE_DIAG, "early"),
        eval_("new Promise(r=>setTimeout(r,2500))"),
        eval_(WAKE_DIAG, "late"),
    ]}])
    step = out["steps"][0]
    early, late = got(step, "early"), got(step, "late")
    # Voix remplie, plus haute que la zone visible : sans maintien en vue, la partie Mot d'éveil serait hors écran.
    assert late["voice"] > late["height"], (early, late)
    assert early["focus"] == "diagnostic_wake_word"
    assert late["focus"] == "diagnostic_wake_word"
    assert late["visible"] is True and late["scroll"] > 0, late
    assert out["console"] == [], out["console"]


HOLD_POST = """(()=>{const base=api;window.__held=null;
  api=(path,opts)=>path==='/api/shortcuts'&&opts&&opts.method==='POST'
    ?new Promise((ok,ko)=>{window.__held=()=>base(path,opts).then(ok,ko)}):base(path,opts);return true})()"""
RELEASE = """(async()=>{const before={focus:document.activeElement,mount:document.querySelector('#modalContent .set-mount')};
  window.__renders=0;const rt=renderTab;renderTab=function(){window.__renders++;return rt.apply(this,arguments)};
  window.__held();await new Promise(r=>setTimeout(r,600));
  const value=(await (await fetch('/api/shortcuts')).json()).values.wake_toggle;
  return {renders:window.__renders,sameFocus:document.activeElement===before.focus,
    sameMount:document.querySelector('#modalContent .set-mount')===before.mount,open:SET.open,section:SET.section,
    kept:SET.shortcuts.values.wake_toggle,served:value}})()"""


@pytest.mark.parametrize("leave", ["section", "close"])
async def test_a_late_shortcut_save_redraws_nothing_once_the_section_is_left(served, leave):
    """QA Slice 06 (B2) : l'envoi d'une touche répond après le départ de la section (autre section, ou Réglages
    fermés) : aucun remontage, focus inchangé, valeur gardée (`startCapture(button, isCurrent)`)."""
    away = ([click("#modalTabs [data-section=theme_scene]"), wait("!!document.querySelector('#modalContent .theme-choice')")]
            if leave == "section" else [key("Escape"), wait("!SET.open")])
    out = await drive(served.url, [{"width": 1440, "height": 900, "actions": [
        *OPEN,
        click("#modalTabs [data-section=shortcuts]"), wait(f"!!document.querySelector('{KEYCAP}')"),
        eval_(HOLD_POST),
        click(KEYCAP), key("F10"), wait("!!window.__held"),
        *away,
        eval_(RELEASE, "late"),
    ]}])
    late = got(out["steps"][0], "late")
    assert late["renders"] == 0, late
    assert late["sameFocus"] is True and late["kept"] == "f10" and late["served"] == "f10", late
    if leave == "section":
        assert late["section"] == "theme_scene" and late["sameMount"] is True and late["open"] is True
    else:
        assert late["open"] is False
    assert out["console"] == [], out["console"]
