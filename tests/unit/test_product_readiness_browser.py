"""« Préparation de JARVIS » dans un vrai Chrome sans tête (jarvis-presentation-edition-v1, Slice 07).

La page est celle que `ControlCenter.index` sert, marquée comme le serveur la marque ; seul `fetch` est un double
(`_status_centre_browser.mjs` : `/api/product/readiness` rend un rapport écrit par le domaine Python). Épinglé :

- édition `presentation`, premier lancement à faire : la fenêtre s'ouvre seule, trois groupes, « Commencer » attend
  l'indispensable ; une action nommée montre son compteur de secondes puis l'issue du serveur ; « Commencer » ouvre le
  Board Présentation et ferme la fenêtre ; Échap ferme et rend le focus ;
- un refus d'action se dit dans la ligne (rôle `alert`, code) ;
- un rapport illisible ou absent n'ouvre rien seul ; ouverte à la demande, la fenêtre dit la cause et « Réessayer » ;
- l'accueil des présentations porte la ligne de préparation (I-006 point 2) ;
- édition `full` : aucune lecture, aucune fenêtre (le JARVIS de développement est inchangé).

Captures : `JARVIS_S07_SHOTS=<dossier>`. Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from jarvis.domain import product_readiness as R
from jarvis.domain.product_readiness import BrainFacts, Probe
from jarvis.domain.product_edition import PRESENTATION_EDITION
from tests.unit.test_presentation_edition_ui_browser import _boards, _drive, _no_errors
from tests.unit.test_product_readiness import facts

SHOTS = os.environ.get("JARVIS_S07_SHOTS")
PRESENTATION = PRESENTATION_EDITION.to_payload()
DIALOG = ("(h=>h?{shown:!h.hidden,title:h.querySelector('h2').textContent,count:h.querySelector('.rd-count').textContent,"
          "groups:[...h.querySelectorAll('h3')].map(n=>n.firstChild.textContent),"
          "rows:Object.fromEntries([...h.querySelectorAll('li[data-item]')].map(li=>[li.dataset.item,{state:li.dataset.state,"
          "chip:li.querySelector('.rd-chip').textContent,actions:[...li.querySelectorAll('button.rd-act')].map(b=>b.textContent),"
          "said:(li.querySelector('.rd-said')||{}).textContent||null,role:(li.querySelector('.rd-said')||{getAttribute:()=>null}).getAttribute('role')}])),"
          "start:h.querySelector('.rd-start').getAttribute('aria-disabled'),startText:h.querySelector('.rd-start').textContent,"
          "quit:!h.querySelector('.rd-quit').hidden,status:h.querySelector('.rd-status').textContent,"
          "text:h.textContent,focus:document.activeElement&&document.activeElement.className}:null)"
          "(document.getElementById('jvReadiness'))")


def report(onboarded: bool = False, **overrides) -> dict:
    return R.report_payload(facts(**overrides), checked_at="2026-10-26T10:11:12+00:00",
                            onboarding={"completed": onboarded}, launcher={"managed": True})


def _shot(name: str, wait: int = 250) -> list:
    if not SHOTS:
        return []
    Path(SHOTS).mkdir(parents=True, exist_ok=True)
    return [["shot", "shot_" + name, str(Path(SHOTS) / f"{name}.png"), wait]]


def test_first_launch_opens_the_preparation_runs_a_named_repair_and_starts_on_a_presentation_board(tmp_path):
    todo = report(brain=BrainFacts(found=True, logged_in=False), render=Probe({"status": "not_installed"}))
    halfway = report(render=Probe({"status": "not_installed"}))
    ready = report()
    seed = {"edition": PRESENTATION, "rail": False, "boards": _boards(("default", "Mes présentations", "presentation")),
            "readiness": todo,
            "readinessActions": {
                "brain_sign_in": {"answer": {"status": "started", "message": "Terminez la connexion dans la fenêtre de Claude."},
                                  "next": halfway},
                "render_install": {"delayMs": 2300, "answer": {"status": "started", "message": "Moteur de rendu : installing"},
                                   "next": ready}}}
    actions = [
        ["eval", "settle", "1", 1600],
        ["eval", "boot", DIALOG, 50],
        *_shot("after-first-launch-1440x900"),
        ["click", "signin", '#jvReadiness li[data-item=brain] button[data-action=brain_sign_in]', 600],
        ["eval", "signed", DIALOG, 50],
        ["click", "prepare", '#jvReadiness li[data-item=render] button[data-action=render_install]', 1300],
        ["eval", "running", DIALOG, 50],
        *_shot("after-render-running-1440x900", 50),
        ["eval", "wait", "1", 1600],
        ["eval", "prepared", DIALOG, 50],
        *_shot("after-ready-1440x900"),
        ["click", "start", "#jvReadiness .rd-start", 900],
        ["eval", "started", "({shown:!document.getElementById('jvReadiness').hidden,"
                            "toast:[...document.querySelectorAll('.toast strong')].map(n=>n.textContent)})", 50],
    ]
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed, "actions": actions}], "presentation")[0]
    _no_errors(step)
    r = step["results"]
    boot = r["boot"]
    assert boot["shown"] and boot["title"] == "Bienvenue dans JARVIS" and boot["count"] == "4 sur 6 indispensables prêts"
    assert boot["groups"] == ["Indispensable", "Comptes et services", "Ce poste"]
    assert boot["start"] == "true" and boot["quit"] is True
    assert boot["rows"]["brain"]["actions"] == ["Se connecter", "Vérifier à nouveau"]
    assert boot["rows"]["render"]["actions"] == ["Préparer"]
    for word in ("MCP", "npm", "Remotion", "PowerShell", ".env", "pip"):
        assert word not in boot["text"], word
    assert r["signed"]["rows"]["brain"]["state"] == "ready"
    running = r["running"]["rows"]["render"]["actions"][0]
    assert running.startswith("Préparer… ") and running.endswith(" s"), running
    assert r["prepared"]["start"] is None and r["prepared"]["count"] == "6 sur 6 indispensables prêts"
    # La ligne est prête dans le rapport rendu : sa propre phrase le dit, aucune consigne « en cours » périmée ne reste.
    assert r["prepared"]["rows"]["render"]["state"] == "ready" and r["prepared"]["rows"]["render"]["said"] is None
    assert not r["started"]["shown"] and "JARVIS est prêt" in r["started"]["toast"]
    paths = [call for call in step["calls"] if "/api/product/" in call]
    assert paths[:1] == ["GET /api/product/readiness"]
    assert "POST /api/product/readiness/actions/brain_sign_in" in paths
    assert "POST /api/product/readiness/actions/render_install" in paths
    assert paths[-1] == "GET /api/product/readiness" and "POST /api/product/onboarding/complete" in paths


def test_a_refused_action_says_its_cause_in_the_line_and_escape_gives_focus_back(tmp_path):
    seed = {"edition": PRESENTATION, "rail": False, "boards": _boards(("default", "Pitch", "presentation")),
            "readiness": report(render=Probe({"status": "install_failed", "last_error_code": "local_capability_install_offline"})),
            "readinessActions": {"render_repair": {"status": 503, "answer": {"code": "core_unreachable",
                                                                             "message": "Core is unreachable: ConnectionRefusedError"}}}}
    actions = [
        ["eval", "settle", "1", 1600],
        ["click", "repair", '#jvReadiness li[data-item=render] button[data-action=render_repair]', 700],
        ["eval", "refused", DIALOG, 50],
        *_shot("after-refused-repair-1440x900"),
        ["key", "esc", "Escape", 300],
        ["eval", "closed", "document.getElementById('jvReadiness').hidden", 50],
    ]
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed, "actions": actions}], "presentation")[0]
    r = step["results"]
    row = r["refused"]["rows"]["render"]
    assert row["role"] == "alert" and "core_unreachable" in row["said"] and "ConnectionRefusedError" in row["said"]
    assert "Internet" in r["refused"]["text"]
    assert r["closed"] is True


def test_an_unreadable_report_never_opens_alone_and_says_why_on_demand(tmp_path):
    seed = {"edition": PRESENTATION, "rail": False, "boards": _boards(("default", "Pitch", "presentation"))}
    actions = [
        ["eval", "settle", "1", 1600],
        ["eval", "alone", "!!document.getElementById('jvReadiness')&&!document.getElementById('jvReadiness').hidden", 50],
        ["eval", "open", "window.JarvisReadiness.open({reason:'test'}),1", 900],
        ["eval", "said", "(h=>({text:h.querySelector('.rd-body').textContent,retry:!!h.querySelector('.rd-body button')}))"
                         "(document.getElementById('jvReadiness'))", 50],
        ["eval", "fix", f"window.__sc.readiness={json.dumps(report(True))},1", 50],
        ["click", "retry", "#jvReadiness .rd-body button", 900],
        ["eval", "after", DIALOG, 50],
    ]
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed, "actions": actions}], "presentation")[0]
    r = step["results"]
    assert r["alone"] is False
    assert "Lecture impossible" in r["said"]["text"] and "http_error" in r["said"]["text"] and r["said"]["retry"]
    assert r["after"]["title"] == "JARVIS est prêt" and r["after"]["startText"] == "Fermer"


def test_the_presentation_home_carries_the_preparation_line(tmp_path):
    seed = {"edition": PRESENTATION, "rail": False, "boards": _boards(("default", "Pitch", "presentation")),
            "readiness": report(True, render=Probe({"status": "not_installed"}))}
    line = ("(h=>(l=>l?{tone:l.dataset.tone,text:l.querySelector('p').textContent,button:l.querySelector('button').textContent}:null)"
            "(h.querySelector('.jvr-ready')))(document.getElementById('presentationRail'))")
    actions = [
        ["eval", "settle", "1", 1600],
        ["key", "esc", "Escape", 200],
        ["eval", "wait", "1", 2500],
        ["eval", "line", line, 50],
        *_shot("after-presentation-home-readiness-1440x900"),
        ["click", "open", "#presentationRail .jvr-ready-open", 600],
        ["eval", "opened", "!document.getElementById('jvReadiness').hidden", 50],
    ]
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed, "actions": actions}], "presentation")[0]
    _no_errors(step)
    r = step["results"]
    assert r["line"] == {"tone": "todo", "text": "1 étape à terminer avant votre première vidéo.",
                         "button": "Voir la préparation"}, r["line"]
    assert r["opened"] is True


def test_narrow_window_keeps_the_preparation_readable(tmp_path):
    seed = {"edition": PRESENTATION, "rail": False, "boards": _boards(("default", "Pitch", "presentation")),
            "readiness": report(brain=BrainFacts(found=False, error="claude_cli_not_found: x"))}
    fits = ("(c=>({w:c.getBoundingClientRect().width,overflow:document.documentElement.scrollWidth>innerWidth,"
            "scroll:c.querySelector('.rd-body').scrollHeight>c.querySelector('.rd-body').clientHeight}))"
            "(document.querySelector('#jvReadiness .rd-card'))")
    actions = [["eval", "settle", "1", 1600], ["eval", "fits", fits, 50], *_shot("after-first-launch-600x800")]
    step = _drive(tmp_path, [{"width": 600, "height": 800, "seed": seed, "actions": actions}], "presentation")[0]
    r = step["results"]["fits"]
    assert r["w"] <= 600 and not r["overflow"], r


def test_full_edition_never_reads_nor_opens_the_preparation(tmp_path):
    seed = {"readiness": report(brain=BrainFacts(found=False))}
    actions = [["eval", "settle", "1", 1500],
               ["eval", "opened", "!!document.getElementById('jvReadiness')&&!document.getElementById('jvReadiness').hidden", 50]]
    step = _drive(tmp_path, [{"width": 1440, "height": 900, "seed": seed, "actions": actions}], "full")[0]
    assert step["results"]["opened"] is False
    assert not [call for call in step["calls"] if "/api/product/" in call]
