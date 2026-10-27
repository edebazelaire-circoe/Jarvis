"""Parcours novice et Réglages complets de l'édition Presentation, dans un vrai Chrome sans tête (V1.2 Slice 06).

Contrats : `docs/settings/novice-inventory.md` (inventaire, essentiel / avancé-support), `docs/settings/support-mode.md`
(mode support, lien profond, Aide et assistance), `docs/control-center-shell.md` › *Product edition UI*. La page est
celle que `ControlCenter.index` sert, marquée comme le serveur la marque ; seul `fetch` est un double
(`_status_centre_browser.mjs` : `/api/status` porte `voice_lifecycle` et `support_mode`, `POST /api/support-mode` rend
le bloc relu, `POST /api/voice/lifecycle` la projection). Ce que ce fichier épingle :

- hub de l'édition produit : quatre catégories, sans jargon, l'essentiel d'abord ; bande « Aide et assistance » avec la
  voix projetée (même projection que l'interrupteur de la roue), « Signaler un problème » seulement quand la Slice 07 a
  branché son action, l'interrupteur du mode support (`role=switch`) ;
- mode support : rouvre Architecture & Agents et Avancé & Diagnostics (étiquetées « Support »), une page de support le
  dit, coupé il les recache ; un refus ou un silence de Jarvis est dit et ne change rien ;
- lien profond `#settings/<cible>` : une cible réservée au support ouvre le hub sur l'interrupteur, puis la page ;
- régression : chaque section enregistrée reste atteignable (presentation + support, et `full`) ;
- onglet Sous-agents en presentation : `coder` « Indisponible dans cette édition » ;
- accueil des présentations : la ligne Voix projetée et son geste ;
- clavier (Tab reste dans le hub et atteint l'interrupteur), `prefers-reduced-motion`.

Captures : `JARVIS_S06_SHOTS=<dossier>` (1366×768 et 1920×1080). Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from jarvis.domain.product_edition import FULL_EDITION, PRESENTATION_EDITION
from jarvis.runtime.control_center import ControlCenter
from tests.unit.test_presentation_edition_ui_browser import _boards, _drive, _no_errors

SHOTS = os.environ.get("JARVIS_S06_SHOTS")
PRESENTATION = PRESENTATION_EDITION.to_payload()
FULL = FULL_EDITION.to_payload()
SLEEP = {"preference": "sleep", "state": "sleep", "code": None, "message": "", "managed": True}

HUB = ("({cards:[...document.querySelectorAll('#settingsHubGrid [data-hub-category]')].map(c=>[c.dataset.hubCategory,"
       "c.querySelector('.set-hub-name').textContent,!!c.querySelector('.set-hub-tag')]),"
       "band:!document.getElementById('settingsHubHelp').hidden,"
       "voice:[document.getElementById('settingsHubVoiceState').textContent,document.getElementById('settingsHubVoiceHint').textContent,"
       "document.getElementById('settingsHubVoiceToggle').hidden?null:document.getElementById('settingsHubVoiceToggle').textContent],"
       "report:!document.getElementById('settingsHubReportRow').hidden,"
       "switch:document.getElementById('settingsSupportSwitch').getAttribute('aria-checked'),"
       "note:document.getElementById('settingsHubHelpNote').textContent,"
       "tone:document.getElementById('settingsHubHelpNote').dataset.tone||null})")
LANDED = ("({category:SET.category,section:SET.section,open:SET.open,"
          "support:!!document.getElementById('settingsSupportNotice'),"
          "title:(document.getElementById('settingsCategoryTitle')||{}).textContent||''})")
#: Chaque section enregistrée, ouverte par sa cible : où le shell atterrit.
EVERY_SECTION = r"""(async()=>{const R=window.JarvisSettingsRegistry,out={};
  const ids=R.page.snapshot().flatMap(c=>c.sections.map(s=>s.id));
  for(const id of ids){await openSettingsTab(id);await new Promise(r=>setTimeout(r,120));
    out[id]={shown:R.targetShown(id,R.page,settingsEditionOptions()),landed:SET.section,
      content:(document.getElementById('modalContent').textContent||'').trim().length>0}}
  closeSettings();return out})()"""


def _shot(name: str, wait: int = 250) -> list:
    if not SHOTS:
        return []
    Path(SHOTS).mkdir(parents=True, exist_ok=True)
    return [["shot", "shot_" + name, str(Path(SHOTS) / f"{name}.png"), wait]]


def _settings(tmp_path: Path) -> dict:
    center = ControlCenter(runtime_root=tmp_path / "cc", project_root=tmp_path / "cc")
    return json.loads(json.dumps(center._settings_payload({})))


def _no_errors_but_unstubbed(step: dict) -> None:
    """Les routes que le double ne sert pas (routage des rôles…) se disent « not stubbed » : seule autre erreur permise,
    aucune exception."""

    bad = [line for line in step["console"] if line["type"] == "exception"
           or (line["type"] == "error" and "not stubbed" not in line["text"])]
    assert bad == [], bad


def _roles(tmp_path: Path, monkeypatch, edition: str) -> dict:
    monkeypatch.setenv("JARVIS_PRODUCT_EDITION", edition)
    center = ControlCenter(runtime_root=tmp_path / "cc", project_root=tmp_path / "cc")
    return center._subagent_roles_payload({})


@pytest.mark.parametrize("width, height", [(1366, 768), (1920, 1080)])
def test_the_hub_puts_the_essentials_first_and_support_mode_reveals_without_widening(tmp_path, width, height):
    seed = {"edition": PRESENTATION, "voiceLifecycle": SLEEP, "rail": False,
            "boards": _boards(("default", "Pitch client", "presentation"))}
    size = f"{width}x{height}"
    actions = [
        ["eval", "open", "openSettingsHub({source:'test'}),1", 600],
        ["eval", "before", HUB, 50],
        *_shot(f"s06-hub-presentation-{size}"),
        ["eval", "wire", "JarvisSettingsHelp.setReportAction(()=>{window.__reported=(window.__reported||0)+1}),1", 150],
        ["eval", "wired", "!document.getElementById('settingsHubReportRow').hidden", 50],
        ["click", "report", "#settingsHubReport", 200],
        ["eval", "reported", "window.__reported||0", 50],
        ["eval", "rewire", "JarvisSettingsHelp.setReportAction(null),1", 50],
        ["eval", "unwired", "!document.getElementById('settingsHubReportRow').hidden", 50],
        ["click", "on", "#settingsSupportSwitch", 700],
        ["eval", "after", HUB, 50],
        *_shot(f"s06-hub-support-on-{size}"),
        ["click", "advanced", '#settingsHubGrid [data-hub-category="advanced_diagnostics"]', 900],
        ["eval", "landed", LANDED, 50],
        *_shot(f"s06-support-page-{size}"),
        ["eval", "back", "backToSettingsHub(),1", 500],
        ["click", "off", "#settingsSupportSwitch", 700],
        ["eval", "offAgain", HUB, 50],
        ["eval", "close", "closeSettingsHub(),1", 400],
        ["eval", "hidden", "openSettingsTab('prompts'),1", 800],
        ["eval", "hiddenLanded", LANDED, 50],
        ["eval", "close2", "closeSettings(),1", 300],
    ]
    step = _drive(tmp_path, [{"width": width, "height": height, "seed": seed, "actions": actions}], "presentation")[0]
    _no_errors(step)
    r = step["results"]
    assert r["before"]["cards"] == [["voice_audio", "Personnalisation", False], ["connections", "Connexions", False],
                                    ["memory_knowledge", "Mémoire", False],
                                    ["interface_interactions", "Raccourcis clavier", False]]
    assert r["before"]["band"] and r["before"]["report"] is True, "Slice 07 wired: the report row is shown"
    assert r["before"]["voice"][0] == "En veille" and "F9" in r["before"]["voice"][1] and r["before"]["voice"][2] == "Couper la voix"
    assert r["before"]["switch"] == "false"
    assert r["wired"] is True and r["reported"] == 1 and r["unwired"] is False, "no action, no row"
    posts = [b for b in step["bodies"] if b["path"] == "/api/support-mode"]
    assert [b["body"] for b in posts] == [{"enabled": True}, {"enabled": False}], posts
    assert r["after"]["switch"] == "true" and "Mode support activé" in r["after"]["note"]
    assert [c[0] for c in r["after"]["cards"]][-2:] == ["agents_models", "advanced_diagnostics"]
    assert [c[2] for c in r["after"]["cards"]] == [False, False, False, False, True, True], "support pages are tagged"
    assert r["landed"]["category"] == "advanced_diagnostics" and r["landed"]["support"] is True and r["landed"]["open"]
    assert r["offAgain"]["switch"] == "false" and len(r["offAgain"]["cards"]) == 4
    assert r["hiddenLanded"]["category"] == "voice_audio", "support off: a support target is hidden again"
    assert "POST /api/voice/lifecycle" not in step["calls"], "reading the voice line writes nothing"


def test_a_support_deep_link_waits_for_support_mode_then_opens_the_page(tmp_path, monkeypatch):
    seed = {"edition": PRESENTATION, "voiceLifecycle": SLEEP, "roles": _roles(tmp_path, monkeypatch, "presentation"),
            "settings": _settings(tmp_path), "agentTasks": {"tasks": []}}
    actions = [
        ["eval", "hash", "location.hash='#settings/subagents',1", 900],
        ["eval", "hub", "({hub:settingsHubOpen(),focus:document.activeElement&&document.activeElement.id,"
                        "note:document.getElementById('settingsHubHelpNote').textContent,"
                        "ring:(cs=>cs.outlineStyle!=='none'&&parseFloat(cs.outlineWidth)>0)(getComputedStyle(document.getElementById('settingsSupportSwitch')))})", 50],
        *_shot("s06-deep-link-needs-support-1366x768"),
        ["key", "space", " ", 1500],
        ["eval", "landed", LANDED, 50],
        ["eval", "coder", "(r=>r?{text:r.textContent}:{none:document.getElementById('modalContent').textContent.slice(0,600)})(document.querySelector('[data-sar-row=\"coder\"]'))", 1500],
        *_shot("s06-subagents-coder-unavailable-1366x768"),
        ["eval", "close", "closeSettings(),history.replaceState(null,'',location.pathname),1", 300],
        ["eval", "direct", "location.hash='#settings/voice_output',1", 900],
        ["eval", "landed2", LANDED, 50],
        ["eval", "close2", "closeSettings(),1", 300],
    ]
    step = _drive(tmp_path, [{"width": 1366, "height": 768, "seed": seed, "actions": actions}], "presentation")[0]
    _no_errors_but_unstubbed(step)
    r = step["results"]
    assert r["hub"]["hub"] is True and r["hub"]["focus"] == "settingsSupportSwitch"
    assert "juste au-dessus" in r["hub"]["note"], "QA S06 m4: the switch sits above the note"
    assert r["hub"]["ring"] is True, "QA S06 m4: a programmatic focus still shows the ring"
    assert r["landed"]["category"] == "agents_models" and r["landed"]["section"] == "subagents", r["landed"]
    assert "text" in r["coder"], r["coder"]
    assert "Indisponible dans cette édition" in r["coder"]["text"]
    assert r["landed2"]["section"] == "voice_output", "a product page opens directly"


def test_a_refused_or_silent_support_switch_says_so_and_changes_nothing(tmp_path):
    seed = {"edition": PRESENTATION, "voiceLifecycle": SLEEP, "supportModeFail": "support_mode_bad_payload"}
    actions = [
        ["eval", "open", "openSettingsHub({source:'test'}),1", 500],
        ["click", "on", "#settingsSupportSwitch", 700],
        ["eval", "refused", HUB, 50],
        ["eval", "hang", "window.__sc.supportModeFail=null,window.__sc.supportModeHang=true,1", 50],
        ["click", "on2", "#settingsSupportSwitch", 300],
        ["eval", "busy", "document.getElementById('settingsSupportSwitch').getAttribute('aria-disabled')", 50],
        ["eval", "wait", "1", 8600],
        ["eval", "silent", HUB, 50],
    ]
    step = _drive(tmp_path, [{"width": 1366, "height": 768, "seed": seed, "actions": actions}], "presentation")[0]
    r = step["results"]
    assert r["refused"]["switch"] == "false" and r["refused"]["tone"] == "bad" and "refusé" in r["refused"]["note"]
    assert len(r["refused"]["cards"]) == 4
    assert r["busy"] == "true", "one write at a time, the switch says it waits"
    assert r["silent"]["switch"] == "false" and "8 s" in r["silent"]["note"] and r["silent"]["tone"] == "bad"
    errors = [line["text"] for line in step["console"] if line["type"] == "error"]
    assert errors and all("support_mode.failed" in text or "400" in text for text in errors), errors


@pytest.mark.parametrize("edition", ["presentation", "full"])
def test_every_registered_section_stays_reachable(tmp_path, edition):
    """Régression « Full Settings retained » : rien n'a disparu. En presentation avec le mode support, toutes les
    sections des catégories de support et des catégories produit s'ouvrent ; seules Bare Hands et Plugins MCP (sections
    `developer` de catégories produit) restent réservées au mode développeur, comme avant."""

    payload = PRESENTATION if edition == "presentation" else FULL
    seed = {"edition": payload, "voiceLifecycle": SLEEP, "supportMode": {"enabled": True, "problem": None},
            "settings": _settings(tmp_path)}
    actions = [["eval", "every", EVERY_SECTION, 300]]
    step = _drive(tmp_path, [{"width": 1366, "height": 768, "seed": seed, "actions": actions}], edition)[0]
    every = step["results"]["every"]
    assert isinstance(every, dict) and len(every) >= 20, every
    developer_only = {"bare_hands", "mcp_plugins"} if edition == "presentation" else set()
    for section, seen in every.items():
        if section in developer_only:
            assert seen["shown"] is False, section
            continue
        assert seen["shown"] is True and seen["landed"] == section and seen["content"], (section, seen)
    assert {"voice_output", "microphone_sound", "turns_interruptions", "conversation", "wake_word", "prompts",
            "runtime_cli", "diagnostics", "architecture", "subagents"} <= set(every)


def test_the_presentation_home_shows_the_projected_voice_and_its_switch(tmp_path):
    seed = {"edition": PRESENTATION, "voiceLifecycle": SLEEP, "rail": False,
            "boards": _boards(("default", "Pitch client", "presentation"))}
    line = ("(b=>b?{state:b.dataset.homeVoice,word:b.querySelector('.jvr-home-voice-state').textContent,"
            "btn:(b.querySelector('button')||{}).textContent||null}:null)(document.querySelector('#presentationRail .jvr-home-voice'))")
    actions = [
        ["eval", "settle", "1", 1500],
        ["eval", "sleep", line, 50],
        *_shot("s06-home-voice-sleep-1366x768"),
        ["click", "off", '#presentationRail [data-home-act="voice"]', 1600],
        ["eval", "off", line, 50],
        ["eval", "focus", "(a=>a?(a.dataset.homeAct||a.id||a.className||a.tagName):'none')(document.activeElement)", 50],
    ]
    step = _drive(tmp_path, [{"width": 1366, "height": 768, "seed": seed, "actions": actions}], "presentation")[0]
    _no_errors(step)
    r = step["results"]
    assert r["sleep"] == {"state": "sleep", "word": "En veille", "btn": "Couper la voix"}, r["sleep"]
    posts = [b["body"] for b in step["bodies"] if b["path"] == "/api/voice/lifecycle"]
    assert posts == [{"preference": "off"}]
    assert r["off"] == {"state": "off", "word": "Coupée", "btn": "Rallumer la voix"}, "the server's answer, not a hope"
    assert r["focus"] == "voice", "the replaced line keeps the focus on its button"


def test_keyboard_stays_in_the_hub_and_reduced_motion_stills_the_switch(tmp_path):
    seed = {"edition": PRESENTATION, "voiceLifecycle": SLEEP}
    actions = [
        ["eval", "open", "openSettingsHub({source:'test'}),1", 500],
        ["tabto", "tabs", "#settingsSupportSwitch", 14],
        ["key", "tab", "Tab", 100],
        ["eval", "wrapped", "document.activeElement&&document.activeElement.id", 50],
        ["eval", "motion", "getComputedStyle(document.querySelector('#settingsSupportSwitch .set-help-knob')).transitionDuration", 50],
    ]
    step = _drive(tmp_path, [{"width": 1366, "height": 768, "seed": seed, "reducedMotion": True, "actions": actions}],
                  "presentation")[0]
    _no_errors(step)
    r = step["results"]
    stops = r["tabs"]
    assert stops[-1]["inside"] and stops[-1]["ring"] and stops[-1]["visible"], stops[-1]
    assert all(stop["visible"] for stop in stops), "Tab never lands on a hidden control"
    assert r["wrapped"] == "settingsHubClose", "Tab after the last control wraps inside the hub"
    assert r["motion"] in ("0s", "0s, 0s")


def test_report_a_problem_opens_the_support_report_panel_and_creates_nothing(tmp_path):
    """Intégration S06 × S07 : « Signaler un problème » de la bande d'aide ferme le hub et ouvre le panneau du rapport
    (aperçu lu), sans créer de paquet ni envoyer ; Échap le ferme."""

    preview = {"board": {"board_id": "default", "title": "Pitch client"}, "approx_bytes": 2048,
               "included": [], "excluded": [], "destination": "support@example.com",
               "default_destination": "support@example.com", "send_mode": "mail", "send_in_progress": False}
    seed = {"edition": PRESENTATION, "voiceLifecycle": SLEEP, "support": {"preview": preview}}
    actions = [
        ["eval", "open", "openSettingsHub({source:'test'}),1", 500],
        ["eval", "row", "!document.getElementById('settingsHubReportRow').hidden", 50],
        *_shot("s06-hub-report-row-1366x768"),
        ["click", "report", "#settingsHubReport", 1200],
        ["eval", "after", "({hub:settingsHubOpen(),panel:!!document.getElementById('jvSupport')&&!document.getElementById('jvSupport').hidden,"
                          "state:JarvisSupportReport.instance.state().open})", 50],
        *_shot("s06-report-panel-from-settings-1366x768"),
    ]
    step = _drive(tmp_path, [{"width": 1366, "height": 768, "seed": seed, "actions": actions}], "presentation")[0]
    _no_errors_but_unstubbed(step)
    r = step["results"]
    assert r["row"] is True
    assert r["after"] == {"hub": False, "panel": True, "state": True}, r["after"]
    assert "GET /api/support/preview" in step["calls"], step["calls"]
    assert not [c for c in step["calls"] if c.startswith("POST /api/support/")], "nothing created, nothing sent"


def test_an_unavailable_voice_without_a_key_offers_to_add_it(tmp_path):
    """QA S06 m5 : voix voulue mais clé absente → hub et accueil proposent « Ajouter la clé vocale », qui ouvre
    Connexions › Fournisseurs ; aucun « Couper la voix » trompeur, aucune écriture de la préférence."""

    degraded = {"preference": "sleep", "state": "degraded", "code": "voice_provider_key_missing",
                "message": "La voix ne peut pas démarrer : la clé du fournisseur vocal manque.", "managed": True}
    seed = {"edition": PRESENTATION, "voiceLifecycle": degraded, "rail": False,
            "boards": _boards(("default", "Pitch client", "presentation")), "settings": _settings(tmp_path)}
    actions = [
        ["eval", "settle", "1", 1500],
        ["eval", "home", "(b=>b?(b.querySelector('button')||{}).textContent||null:'none')(document.querySelector('#presentationRail .jvr-home-voice'))", 50],
        ["eval", "open", "openSettingsHub({source:'test'}),1", 500],
        ["eval", "hub", "document.getElementById('settingsHubVoiceToggle').hidden?null:document.getElementById('settingsHubVoiceToggle').textContent", 50],
        *_shot("s06-voice-key-missing-hub-1366x768"),
        ["click", "add", "#settingsHubVoiceToggle", 1200],
        ["eval", "landed", LANDED, 50],
    ]
    step = _drive(tmp_path, [{"width": 1366, "height": 768, "seed": seed, "actions": actions}], "presentation")[0]
    _no_errors_but_unstubbed(step)
    r = step["results"]
    assert r["home"] == "Ajouter la clé vocale" and r["hub"] == "Ajouter la clé vocale", r
    assert r["landed"]["open"] and r["landed"]["section"] == "providers", r["landed"]
    assert not [b for b in step["bodies"] if b["path"] == "/api/voice/lifecycle"]
