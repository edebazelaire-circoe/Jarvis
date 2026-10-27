"""Catégories JARVIS et Paramètres de la roue, mesurées dans un vrai Chrome sans tête.

Handoff `jarvis-board-ui-wheel-dossier-refactor`, Slice 04 (`docs/06-ui-visual-spec.md`
› C et F ; contrat `docs/control-center-shell.md` › *Tool wheel* › *JARVIS and
Paramètres*). La page est celle que `ControlCenter.index` sert ; seul `fetch` est un
double (`_status_centre_browser.mjs`, qui sert `/api/status`, peut le faire tomber
— `statusFail` — et en remplacer des champs — `status`).

Ce que ce fichier épingle :

- le sous-menu JARVIS dit ce que le battement `/api/status` dit (voix, touche
  d'éveil, agent, sous-agents), ligne d'état distincte d'une action, et aucune
  commande que le produit n'a pas (Veille / Réveil, Pause) ;
- un sous-menu JARVIS ouvert se relit au battement suivant : la voix qui passe
  en écoute, puis le statut perdu (« état inconnu », jamais le dernier état connu),
  sans refermer le sous-menu ni perdre le focus clavier ;
- une ligne d'état activée n'agit pas et ne ferme pas la roue ;
- « Sous-agents » ouvre le panneau Agents, « Réglages de la voix » et chaque ligne
  de Paramètres (une par catégorie des réglages) ouvrent les réglages sur leur catégorie — les routes de
  `#agentsButton` et `#openSettings` ;
- aucun second sondage : le nombre de lectures de `/api/status` ne dépend pas
  de l'ouverture du sous-menu.

Preuves : `JARVIS_S04_EVIDENCE_DIR=<dossier>` y écrit les captures.
Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.unit.test_boards_card_browser import _chrome, _served_page

HARNESS = Path(__file__).parent / "_status_centre_browser.mjs"
EVIDENCE = os.environ.get("JARVIS_S04_EVIDENCE_DIR")
ANCHOR = "#toolWheel .tw-anchor"
DOT = "#toolWheel [data-tw-slot={slot}] .tw-dot"

SUB = r"""(()=>{const host=document.getElementById('toolWheel');const ae=document.activeElement;
  return {open:window.JarvisToolWheel.isOpen(),head:(host.querySelector('.tw-subhead')||{}).textContent||null,
    subs:[...host.querySelectorAll('.tw-sub')].filter(s=>!s.hidden).length,
    items:[...host.querySelectorAll('.tw-sub:not([hidden]) .tw-item')].map(b=>({id:b.dataset.twItem||null,
      text:b.querySelector('.tw-text').textContent,note:(b.querySelector('.tw-note')||{}).textContent||'',
      kind:b.getAttribute('data-tw-kind'),tone:b.getAttribute('data-tw-tone'),disabled:b.getAttribute('aria-disabled'),
      name:b.getAttribute('aria-label')||b.textContent,role:b.getAttribute('role'),
      textColor:getComputedStyle(b.querySelector('.tw-text')).color})),
    focus:ae&&ae.classList&&ae.classList.contains('tw-item')?ae.dataset.twItem:(ae&&ae.id)||null,
    sector:(host.querySelector('[data-tw-slot=jarvis]')||{getAttribute:()=>null}).getAttribute('aria-label'),
    facts:window.JarvisRuntimeWheel?window.JarvisRuntimeWheel.facts().read:null,
    reads:performance.getEntriesByType('resource').length}})()"""
OVERLAY = r"""(()=>({open:document.getElementById('overlay').classList.contains('open'),
  tab:document.querySelectorAll('#modalTabs [data-tab]').length||null,
  section:(document.querySelector('#modalTabs button.active')||{}).dataset?.section||null,
  category:(document.querySelector('#settingsCategories [aria-selected=true]')||{}).dataset?.category||null,
  panel:document.getElementById('panel').classList.contains('open')?document.getElementById('panelTitle').textContent:null,
  wheel:window.JarvisToolWheel.isOpen()}))()"""
STATUS_READS = "window.__statusReads||0"
#: Le hub des Réglages (2026-10-23) : ce que l'overlay montre et ses cartes.
HUB = r"""(()=>({view:document.getElementById('overlay').dataset.view||null,
  cards:[...document.querySelectorAll('#settingsHubGrid [data-hub-category]')].map(c=>c.dataset.hubCategory)}))()"""
#: Ce que la roue demande aux Réglages (`openSettingsTab`, lu par la roue sur `window` à chaque appel) et les cibles
#: inconnues dites par la page (`console.warn('settings_target_unknown', …)`).
SPY_SETTINGS = ("(()=>{const spy=window.__settingsSpy={targets:[],unknown:[]};const open=window.openSettingsTab;"
                "window.openSettingsTab=function(t){spy.targets.push(t);return open.apply(this,arguments)};"
                "const warn=console.warn;console.warn=function(c,x){if(c==='settings_target_unknown')spy.unknown.push(x);"
                "return warn.apply(this,arguments)};return 1})()")
#: Compte les lectures de `/api/status` (le double est installé avant ; on l'enveloppe).
COUNT = ("(()=>{const f=window.fetch;window.__statusReads=0;window.fetch=(u,i)=>{if(String(u)==='/api/status')"
         "window.__statusReads+=1;return f(u,i)};return 1})()")


def _drive(tmp_path: Path, plan: list) -> list:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    chrome = _chrome()
    page = _served_page(tmp_path)
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    done = subprocess.run([node, str(HARNESS), str(page), chrome, "@" + str(plan_file)],
                          capture_output=True, text=True, encoding="utf-8", timeout=560, check=False)
    assert done.returncode == 0, done.stderr[-4000:]
    return json.loads(done.stdout)


def _shot(name: str) -> list:
    if not EVIDENCE:
        return []
    Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
    return [["shot", "shot-" + name, str(Path(EVIDENCE) / f"{name}.png"), 100]]


def _no_errors(step: dict) -> None:
    bad = [line for line in step["console"] if line["type"] in ("exception", "error")]
    assert bad == [], bad


def _open(slot: str) -> list:
    return [["click", "anchor", ANCHOR, 400], ["click", slot, DOT.format(slot=slot), 500]]


ONLINE = {"status": {"voice_state": "idle", "voice_online": True, "voice_stack_label": "Cerveau continu",
                     "agent": {"name": "Claude", "state": "running", "model": "opus"}, "subagents": {"active": 2}}}


def test_jarvis_submenu_reads_the_beat_and_offers_no_fake_control(tmp_path):
    plans = []
    for (w, h) in ((1920, 1032), (1280, 720), (600, 800)):
        plans.append({"width": w, "height": h, "seed": ONLINE, "actions": [
            *_open("jarvis"), ["eval", "sub", SUB, 100], *_shot(f"jarvis-submenu-{w}x{h}")]})
    out = _drive(tmp_path, plans)
    for step in out:
        sub = step["results"]["sub"]
        assert sub["open"] and sub["subs"] == 1 and sub["head"] == "État de Jarvis", sub
        assert [i["id"] for i in sub["items"]] == ["voice", "wake", "agent", "subagents", "voice_settings"]
        by = {i["id"]: i for i in sub["items"]}
        assert by["voice"]["note"] == "Veille · SLEEP" and by["voice"]["kind"] == "status"
        assert by["voice"]["disabled"] == "true" and by["voice"]["name"].startswith("Voix — Veille · SLEEP")
        assert by["wake"]["text"] == "F9 · DÉMARRER" and by["wake"]["kind"] == "status"
        assert by["agent"]["text"] == "Agent : Claude" and by["agent"]["note"] == "actif"
        assert "modèle opus" in by["agent"]["name"]
        assert by["subagents"]["note"] == "2 en cours" and by["subagents"]["kind"] is None
        assert by["voice_settings"]["kind"] is None and by["voice_settings"]["disabled"] is None
        # Ligne d'état : pas grisée comme une entrée indisponible (même encre qu'une action).
        assert by["voice"]["textColor"] == by["voice_settings"]["textColor"]
        names = " ".join(i["name"].lower() for i in sub["items"])
        for word in ("pause", "réveiller", "endormir", "mettre en veille"):
            assert word not in names, word
        assert sub["sector"] == "JARVIS — voix : veille · 2 sous-agents"
        _no_errors(step)


def test_an_open_jarvis_submenu_follows_the_beat_then_says_unknown_when_status_is_lost(tmp_path):
    step = _drive(tmp_path, [{"width": 1280, "height": 720, "seed": ONLINE, "actions": [
        ["eval", "count", COUNT, 50],
        *_open("jarvis"), ["eval", "before", SUB, 50],
        # Le clavier dans le sous-menu, sur « Voix » : une ligne d'état activée n'agit pas, la roue reste.
        ["eval", "focus", "document.querySelector('#toolWheel .tw-item[data-tw-item=voice]').focus();1", 100],
        ["key", "enter", "Enter", 300], ["eval", "afterEnter", SUB, 50],
        # La voix passe en écoute : le sous-menu ouvert se relit au battement suivant, le focus reste.
        ["eval", "listen", "window.__sc.status=Object.assign({},window.__sc.status,{voice_state:'listening'});1", 1600],
        ["eval", "listening", SUB, 50], *_shot("jarvis-submenu-listening-1280x720"),
        # Le battement tombe : tout devient « état inconnu », rien du dernier état connu ne reste.
        ["eval", "fail", "window.__sc.statusFail=true;1", 1700],
        ["eval", "lost", SUB, 50], *_shot("jarvis-submenu-status-lost-1280x720"),
        ["eval", "reads", STATUS_READS, 50],
    ]}])[0]
    r = step["results"]
    assert r["before"]["items"][0]["note"] == "Veille · SLEEP"
    assert r["afterEnter"]["open"] is True and r["afterEnter"]["focus"] == "voice", "rien n'agit, la roue reste ouverte"
    listening = r["listening"]
    assert listening["open"] and listening["subs"] == 1, "toujours ouvert, jamais rouvert"
    assert listening["items"][0]["note"] == "Écoute · LISTEN" and listening["items"][1]["text"] == "F9 · ANNULER"
    assert listening["focus"] == "voice", "le focus reste sur la même ligne"
    lost = r["lost"]
    assert lost["open"] and lost["facts"] == "lost"
    assert [i["note"] for i in lost["items"][:3]] == ["état inconnu"] * 3, lost["items"]
    assert [i["tone"] for i in lost["items"][:4]] == ["unknown"] * 4
    assert "Claude" not in json.dumps(lost["items"]) and "LISTEN" not in json.dumps(lost["items"])
    assert lost["sector"] == "JARVIS — état inconnu, statut illisible"
    # Le battement de la page, une lecture par seconde environ ; le sous-menu n'en ajoute aucune.
    assert 3 <= r["reads"] <= 6, r["reads"]
    lines = "\n".join(c["text"] for c in step["console"])
    del lines
    errors = [c for c in step["console"] if c["type"] in ("exception", "error")]
    # Le battement perdu est journalisé par la page (« api … Failed to fetch ») ; rien d'autre.
    assert all("Failed to fetch" in c["text"] for c in errors), errors


def test_the_two_jarvis_routes_and_every_settings_row_open_existing_surfaces(tmp_path):
    out = _drive(tmp_path, [
        {"width": 1280, "height": 720, "seed": ONLINE, "actions": [
            *_open("jarvis"), ["click", "subagents", "#toolWheel .tw-item[data-tw-item=subagents]", 900],
            ["eval", "agents", OVERLAY, 50]]},
        {"width": 1280, "height": 720, "seed": ONLINE, "actions": [
            *_open("jarvis"), ["eval", "spy", SPY_SETTINGS, 0],
            ["click", "voiceSettings", "#toolWheel .tw-item[data-tw-item=voice_settings]", 900],
            ["eval", "voice", OVERLAY, 50], ["eval", "opened", "window.__settingsSpy", 0]]},
        {"width": 1280, "height": 720, "seed": ONLINE, "actions": [
            *_open("settings"), ["eval", "sub", SUB, 50], ["eval", "hub", HUB, 50], *_shot("settings-hub-1280x720"),
            ["click", "shortcuts", "#settingsHubGrid [data-hub-category=interface_interactions]", 900],
            ["eval", "shortcutsTab", OVERLAY, 50]]},
    ])
    assert out[0]["results"]["agents"]["panel"].startswith("Agents") and out[0]["results"]["agents"]["wheel"] is False
    voice = out[1]["results"]["voice"]
    assert voice["open"] is True and voice["section"] == "conversation" and voice["wheel"] is False
    assert voice["category"] == "voice_audio"  # « Réglages de la voix » : Personnalisation › Conversation
    # La ligne passe l'ID de la section Conversation (hub des Réglages, 2026-10-23) ; rien d'inconnu.
    assert out[1]["results"]["opened"] == {"targets": ["conversation"], "unknown": []}
    # Paramètres n'ouvre plus de sous-menu : le hub des Réglages, six cartes, la roue refermée.
    sub = out[2]["results"]["sub"]
    assert sub["subs"] == 0 and sub["items"] == [], sub
    hub = out[2]["results"]["hub"]
    assert hub["view"] == "hub" and hub["cards"] == ["voice_audio", "agents_models", "memory_knowledge",
                                                     "interface_interactions", "connections", "advanced_diagnostics"]
    shortcuts = out[2]["results"]["shortcutsTab"]
    # Première entrée d'Interface : Raccourcis (Thème & scène est dans Personnalisation depuis le hub).
    assert shortcuts["open"] is True and shortcuts["section"] == "shortcuts" and shortcuts["tab"] is None, shortcuts
    assert shortcuts["category"] == "interface_interactions", shortcuts
    for step in out:
        errors = [c for c in step["console"] if c["type"] in ("exception", "error")]
        # Le double ne sert ni `/api/settings` ni le détail des agents : la page le dit, rien d'autre.
        assert all("not stubbed" in c["text"] or "404" in c["text"] for c in errors), errors


#: Où est le focus : dans le shell des Réglages (et sur quelle catégorie), ou ailleurs.
FOCUS = r"""(()=>{const ae=document.activeElement,shell=document.getElementById('settingsShell');
  return {open:document.getElementById('overlay').classList.contains('open'),inShell:!!(shell&&shell.contains(ae)),
    cat:ae&&ae.dataset?ae.dataset.category||null:null,section:ae&&ae.dataset?ae.dataset.section||null:null,anchor:!!(ae&&ae.classList&&ae.classList.contains('tw-anchor')),
    id:ae?(ae.id||ae.className||ae.tagName):null}})()"""


def test_settings_opened_from_the_wheel_keep_the_focus_and_give_it_back_to_the_anchor(tmp_path):
    """QA Slice 02 de jarvis-settings-ui-reorganization : la roue ne reprend pas le focus que les Réglages ont pris."""
    out = _drive(tmp_path, [{"width": 1280, "height": 720, "seed": ONLINE, "actions": [
        *_open("settings"), ["click", "agents", "#settingsHubGrid [data-hub-category=agents_models]", 100],
        ["eval", "now", FOCUS, 0], ["eval", "later", FOCUS, 800],
        ["key", "tab1", "Tab", 80], ["key", "tab2", "Tab", 80], ["key", "tab3", "Tab", 80], ["eval", "tabbed", FOCUS, 50],
        ["key", "back", "Tab", 80, True], ["eval", "shifted", FOCUS, 50],
        ["key", "esc", "Escape", 200], ["eval", "closed", FOCUS, 50]]}])
    r = out[0]["results"]
    # Architecture & Agents s'ouvre en page pleine (refonte-ui-settings, Slice 07) : le focus va à son onglet de page.
    assert r["now"]["open"] and r["now"]["inShell"] and r["now"]["section"] in ("architecture", "subagents"), r["now"]
    assert r["later"]["inShell"] and r["later"]["section"] == r["now"]["section"], r["later"]
    assert r["tabbed"]["inShell"] and r["shifted"]["inShell"], (r["tabbed"], r["shifted"])
    assert r["closed"]["open"] is False and r["closed"]["anchor"] is True, (r["closed"]["id"], r["closed"])


POWER = "#toolWheel .tw-sub:not([hidden]) [data-tw-item=voice_power]"
POWER_READ = r"""(()=>{const b=document.querySelector('#toolWheel .tw-sub:not([hidden]) [data-tw-item=voice_power]');
  return b?{role:b.getAttribute('role'),checked:b.getAttribute('aria-checked'),note:(b.querySelector('.tw-note')||{}).textContent||'',
    tone:b.getAttribute('data-tw-tone'),name:b.getAttribute('aria-label')||b.textContent,
    bodies:window.__sc.bodies.filter(x=>x.path==='/api/voice/lifecycle').map(x=>x.body)}:null})()"""
SLEEP = {"voiceLifecycle": {"preference": "sleep", "state": "sleep", "code": None, "message": ""}}


def test_the_voice_switch_cuts_and_restores_the_voice_and_shows_the_server_answer(tmp_path):
    """Slice 05 presentation-edition-v1-2 (`docs/voice-lifecycle.md`) : l'interrupteur Off / Sleep de la roue JARVIS."""

    step = _drive(tmp_path, [{"width": 1280, "height": 720, "seed": SLEEP, "actions": [
        *_open("jarvis"), ["eval", "before", POWER_READ, 100], *_shot("voice-switch-sleep"),
        # La roue se referme après une action (son contrat) : on la rouvre pour relire l'interrupteur.
        ["click", "cut", POWER, 700], ["eval", "closed", "window.JarvisToolWheel.isOpen()", 50],
        ["eval", "toasts", "document.body.innerText.includes('Voix coupée')", 50],
        *_open("jarvis"), ["eval", "cut", POWER_READ, 100], *_shot("voice-switch-off"),
        ["click", "restore", POWER, 700], *_open("jarvis"), ["eval", "restored", POWER_READ, 100]]}])[0]
    got = step["results"]
    assert got["before"]["role"] == "menuitemcheckbox" and got["before"]["checked"] == "true"
    assert got["before"]["note"] == "veille · SLEEP" and "couper la voix" in got["before"]["name"]
    assert got["closed"] is False and got["toasts"] is True
    assert got["cut"]["bodies"] == [{"preference": "off"}]
    assert got["cut"]["checked"] == "false" and got["cut"]["note"] == "coupée · OFF" and got["cut"]["tone"] == "off"
    assert got["restored"]["bodies"] == [{"preference": "off"}, {"preference": "sleep"}]
    assert got["restored"]["checked"] == "true" and got["restored"]["note"] == "démarrage…", "projection, pas espoir"
    _no_errors(step)


def test_a_refused_voice_switch_is_said_and_changes_nothing(tmp_path):
    step = _drive(tmp_path, [{"width": 1280, "height": 720,
                              "seed": {**SLEEP, "voiceLifecycleFail": "voice_lifecycle_foreign_version"}, "actions": [
        *_open("jarvis"), ["click", "cut", POWER, 700], *_open("jarvis"), ["eval", "after", POWER_READ, 100]]}])[0]
    after = step["results"]["after"]
    assert after["checked"] == "true" and after["note"] == "veille · SLEEP"
    errors = [line["text"] for line in step["console"] if line["type"] == "error"]
    assert any("jarvis_wheel.voice_power_failed" in text and "voice_lifecycle_foreign_version" in text for text in errors)
