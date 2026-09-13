"""Ce que la carte Brain dit d'un agent sans processus permanent.

Le cas vécu : le Brain passé de Claude à Codex, la carte affichait « arrêté »
quoi qu'on fasse. « Redémarrer » réussissait — sans erreur, sans toast rouge —
et la carte ne bougeait pas ; « Arrêter » restait grisé. Rien n'était cassé
côté serveur : `codex exec` n'a pas de processus permanent, l'agent se déclare
donc `ready` entre deux tours, et la page ne connaissait que `running`.

Ces tests tiennent les deux bouts : l'état publié par l'agent Codex, et le
vocabulaire de la page qui le lit.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.runtime.codex_local import CodexLocalAgent

PAGE = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center.html"
_NODE = shutil.which("node")


def brain_logic(body: str):
    """Exécuter le vocabulaire d'état de la page, extrait de la page servie."""
    if _NODE is None:
        pytest.skip("node absent")
    page = PAGE.read_text(encoding="utf-8")
    source = page[page.index("function brainArmed(") : page.index("function cardHtml(")]
    script = f"{source}\nconsole.log(JSON.stringify((()=>{{{body}}})()))"
    result = subprocess.run(
        [_NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_an_armed_codex_agent_reports_ready_not_running(tmp_path):
    """Pas de mensonge côté serveur : armé sans processus, c'est `ready`."""
    agent = CodexLocalAgent(runtime_root=tmp_path, cwd=tmp_path)

    assert agent.state == "stopped"
    agent._started = True  # ce que `start()` pose une fois le CLI sondé
    assert agent.state == "ready"


def test_the_card_says_a_ready_brain_is_armed_not_stopped():
    verdicts = brain_logic("""
      const state=s=>({armed:brainArmed({state:s}),label:brainState({state:s}).label});
      return {
        running:state('running'),
        ready:state('ready'),
        exited:state('exited'),
        stopped:state('stopped'),
        busy:{armed:brainArmed({state:'ready'}),label:brainState({state:'ready',busy:true}).label},
        nothing:brainArmed(null),
      };
    """)

    assert verdicts["ready"] == {"armed": True, "label": "prêt"}
    assert verdicts["running"] == {"armed": True, "label": "en attente"}
    assert verdicts["exited"] == {"armed": False, "label": "processus terminé"}
    assert verdicts["stopped"] == {"armed": False, "label": "arrêté"}
    # Un tour en cours se voit, quel que soit l'agent qui le porte.
    assert verdicts["busy"] == {"armed": True, "label": "tour en cours"}
    assert verdicts["nothing"] is False


def test_start_stop_and_the_service_timer_follow_the_armed_state():
    """Le menu et le compteur se règlent sur « armé », pas sur un PID."""
    page = PAGE.read_text(encoding="utf-8")
    menu = page[page.index("function menuItems(") : page.index("function anchorOf(")]

    assert "{act:'start',label:'Démarrer',disabled:armed}" in menu
    assert "{act:'kill',label:'Arrêter',danger:true,disabled:!armed}" in menu
    assert "==='running'" not in menu

    timers = page[page.index("function timerHtml(") : page.index("function tickTimers(")]
    assert "brainArmed(t)" in timers and "==='running'" not in timers
