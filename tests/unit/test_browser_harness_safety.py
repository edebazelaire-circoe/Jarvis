"""Sûreté des harnais navigateur (`tests/unit/_cdp_profile.mjs`), QA de la Slice 09 de jarvis-organic-agent-orchestration.

- Un harnais ne tue que SON Chrome : `killChrome` vise le handle du processus lancé, puis seulement des processus
  vivants dont la ligne de commande porte le profil jetable du harnais — jamais `taskkill /PID <pid> /T` sur un PID
  mémorisé, que Windows réemploie (Core et Control Center d'un bac à sable en sont morts deux fois).
- Un harnais refuse de piloter le JARVIS vivant : ports 17653/17654, racine d'instance `~/.jarvis/instances/...`,
  `runtime/` de la checkout principale. Refus explicite, code 2, message sur stderr, avant tout lancement de Chrome.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import pytest

UNIT = Path(__file__).resolve().parent
PROFILE_MJS = UNIT / "_cdp_profile.mjs"
HARNESSES = sorted(p for p in UNIT.glob("_*_browser.mjs"))


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    return node


def test_no_harness_kills_a_remembered_pid_tree():
    for harness in [PROFILE_MJS, *HARNESSES]:
        source = harness.read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith(("/*", "*", "//")))
        assert "'/T'" not in code and '"/T"' not in code, f"{harness.name} still kills a PID tree"
        if harness is not PROFILE_MJS and "_cdp_profile.mjs" in source:
            assert "assertSafeTarget(" in source, f"{harness.name} does not refuse the live JARVIS"


def test_the_target_guard_refuses_the_live_ports_and_runtime_roots():
    script = (
        f"import {{unsafeTargetReason}} from {json.dumps(PROFILE_MJS.as_uri())};"
        "import {homedir} from 'node:os';import {join} from 'node:path';"
        "const r=(p,rt)=>unsafeTargetReason(p,rt);"
        "process.stdout.write(JSON.stringify({ui:r('http://127.0.0.1:17654/'),core:r('http://127.77.0.1:17653/v1/health'),"
        "sandbox:r('http://127.0.0.1:27654/'),file:r('C:/tmp/served.html'),"
        "instance:r('http://127.0.0.1:27654/',join(homedir(),'.jarvis','instances','jarvis-abc','runtime')),"
        "checkout:r('http://127.0.0.1:27654/','C:/Projects/jarvis/jarvis/runtime'),"
        "checkoutSub:r('http://127.0.0.1:27654/','c:\\\\projects\\\\jarvis\\\\jarvis\\\\runtime\\\\x'),"
        "worktree:r('http://127.0.0.1:27654/','C:/Projects/jarvis/orch/runtime'),"
        "scratch:r('http://127.0.0.1:27654/',join(homedir(),'AppData','Local','Temp','s09','runtime'))}))")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "guard.mjs"
        path.write_text(script, encoding="utf-8")
        done = subprocess.run([_node(), str(path)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert "17654" in out["ui"] and "17653" in out["core"] and out["ui"].startswith("refus")
    assert out["sandbox"] == "" and out["file"] == "" and out["worktree"] == "" and out["scratch"] == ""
    assert "racine d'instance" in out["instance"] and "checkout principale" in out["checkout"]
    assert out["checkoutSub"].startswith("refus")


@pytest.mark.parametrize("harness", ["_interaction_mode_browser.mjs", "_status_centre_browser.mjs"])
def test_a_harness_aimed_at_the_live_jarvis_stops_before_launching_chrome(harness):
    done = subprocess.run([_node(), str(UNIT / harness), "http://127.0.0.1:17654/", "no-chrome.exe", "[]"],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 2
    assert "JARVIS vivant" in done.stderr and "17654" in done.stderr


def test_a_harness_given_the_live_runtime_root_stops():
    done = subprocess.run([_node(), str(UNIT / "_interaction_mode_browser.mjs"), "http://127.0.0.1:27654/",
                           "no-chrome.exe", "[]", "C:/Projects/jarvis/jarvis/runtime"],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 2 and "checkout principale" in done.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="l'arrêt par profil est le chemin Windows")
def test_kill_chrome_stops_only_the_processes_of_its_own_profile():
    node = _node()
    with tempfile.TemporaryDirectory() as tmp:
        mine, other = Path(tmp) / "jarvis-cdp-mine-0123456789", Path(tmp) / "jarvis-cdp-other-0123456789"
        sleeper = "setTimeout(()=>{},60000)"
        a = subprocess.Popen([node, "-e", sleeper, "--", f"--user-data-dir={mine}"])
        b = subprocess.Popen([node, "-e", sleeper, "--", f"--user-data-dir={other}"])
        try:
            time.sleep(0.8)
            script = Path(tmp) / "kill.mjs"
            script.write_text(f"import {{killChrome}} from {json.dumps(PROFILE_MJS.as_uri())};"
                              f"killChrome(null,{json.dumps(str(mine))});", encoding="utf-8")
            done = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=60)
            assert done.returncode == 0, done.stderr
            for _ in range(40):
                if a.poll() is not None:
                    break
                time.sleep(0.25)
            assert a.poll() is not None, "the process of this profile is stopped"
            assert b.poll() is None, "a process of another profile is never touched"
        finally:
            for proc in (a, b):
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=10)
