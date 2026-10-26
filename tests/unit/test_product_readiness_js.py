"""Logique pure de la fenêtre « Préparation de JARVIS » (node, sans navigateur ; presentation-edition-v1 Slice 07).

La charge est celle que Python écrit (`report_payload` du domaine) : le contrat entre le serveur et la page est épinglé
des deux côtés. Le comportement dans une vraie page est prouvé par `test_product_readiness_browser.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.domain import product_readiness as R
from jarvis.domain.product_readiness import BrainFacts, Probe
from tests.unit.test_product_readiness import facts

MODULE = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center_product_readiness.js"


def payload(onboarded: bool = False, **overrides) -> str:
    return json.dumps(R.report_payload(facts(**overrides), checked_at="2026-10-26T10:11:12+00:00",
                                       onboarding={"completed": onboarded}, launcher={"managed": True}))


def node(script: str):
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node absent")
    code = (f"const J=require({json.dumps(str(MODULE))});"
            f"Promise.resolve((async()=>{{{script}}})()).then(v=>process.stdout.write(JSON.stringify(v)))"
            ".catch(e=>{console.error(e&&e.stack||e);process.exit(1)})")
    done = subprocess.run([exe, "-e", code], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_python_report_is_read_strictly():
    out = node(f"const r=J.parse({payload()}).report;"
               "return {ready:r.ready,managed:r.managed,onboarded:r.onboarded,ids:r.items.map(i=>i.id),"
               "groups:r.groups.map(g=>g.id),brain:r.items.find(i=>i.id==='brain'),"
               "bad:[J.parse(null).ok,J.parse({schema:'x',items:[]}).ok,"
               "J.parse({schema:'jarvis.product-readiness',items:[{item_id:'a',state:'weird',actions:[]}]}).ok]}")
    assert out["ready"] is True and out["managed"] is True and out["onboarded"] is False
    assert out["ids"][:6] == ["core", "data", "runtimes", "brain", "render", "browser"]
    assert out["groups"] == ["essentials", "services", "computer"]
    assert out["brain"]["stateLabel"] == "Prêt" and out["brain"]["required"] is True
    assert out["bad"] == [False, False, False], "an unreadable report is never a guessed one"


def test_progress_headline_and_auto_open():
    todo = payload(brain=BrainFacts(found=False, error="claude_cli_not_found: x"), render=Probe({"status": "not_installed"}))
    out = node(f"const t=J.parse({todo}).report,ok=J.parse({payload()}).report,done=J.parse({payload(True)}).report;"
               "return {progress:J.progressOf(t),head:J.headlineOf(t),ready:J.headlineOf(ok).tone,"
               "open:[J.shouldOpen(t,'presentation'),J.shouldOpen(ok,'presentation'),J.shouldOpen(done,'presentation'),"
               "J.shouldOpen(t,'full'),J.shouldOpen(t,null),J.shouldOpen(null,'presentation')]}")
    assert out["progress"] == {"done": 4, "total": 6, "remaining": 2}
    assert out["head"]["tone"] == "todo" and out["head"]["text"].startswith("Encore 2 étapes")
    assert out["ready"] == "ready"
    # Premier lancement à faire : ouverte ; fait et prêt : fermée ; édition full ou page non marquée : jamais.
    assert out["open"] == [True, True, False, False, False, False]


def test_the_presentation_home_line_says_what_remains_or_the_linked_accounts():
    todo = payload(render=Probe({"status": "not_installed"}))
    out = node(f"return {{todo:J.homeLineOf(J.parse({todo}).report),ready:J.homeLineOf(J.parse({payload(True)}).report),"
               "none:J.homeLineOf(null)}")
    assert out["todo"] == {"tone": "todo", "text": "1 étape à terminer avant votre première vidéo.",
                           "action": "Voir la préparation"}
    assert out["ready"]["tone"] == "ready" and out["ready"]["text"] == "JARVIS est prêt. Comptes reliés : 0 sur 2."
    assert out["none"] is None


def test_elapsed_counter_text():
    assert node("return [0,9.7,61,3600].map(J.elapsed)") == ["0 s", "9 s", "1 min 01 s", "60 min 00 s"]
