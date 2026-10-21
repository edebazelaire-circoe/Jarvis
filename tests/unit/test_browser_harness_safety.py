r"""Sûreté des harnais navigateur (`tests/unit/_cdp_profile.mjs`), QA de la Slice 09 de jarvis-organic-agent-orchestration.

- Un harnais ne tue que SON Chrome : `killChrome` vise le handle du processus lancé, puis seulement des processus
  vivants dont la ligne de commande porte le profil jetable du harnais — jamais `taskkill /PID <pid> /T` sur un PID
  mémorisé, que Windows réemploie (Core et Control Center d'un bac à sable en sont morts deux fois).
- Un harnais refuse de piloter le JARVIS vivant : ports 17653/17654 et ports configurés, racine d'instance
  `~/.jarvis/instances/...`, `runtime/` de la checkout principale et dossiers configurés, sous toutes leurs
  graphies Windows (8.3, `\\?\`, partage `\\localhost\c$`, jonction). Refus explicite, code 2, message sur stderr,
  avant tout lancement de Chrome.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

import pytest

UNIT = Path(__file__).resolve().parent
ROOT = UNIT.parents[1]
PROFILE_MJS = UNIT / "_cdp_profile.mjs"
HARNESSES = sorted(p for p in UNIT.glob("_*_browser.mjs"))
E2E = ROOT / "scripts" / "e2e_session_capture.py"
SANDBOX = "http://127.0.0.1:27654/"
#: H4 : le drapeau d'arbre de taskkill, quelle que soit sa casse et quelle que soit la forme de l'appel.
TREE_FLAG = re.compile(r"""['"`]\s*/t\s*['"`]|taskkill[^\n]*\s/t\b""", re.IGNORECASE)


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    return node


def _code(source: str) -> str:
    """Le code sans commentaires ni docstrings (ils citent l'ancien schéma pour l'interdire)."""
    source = re.sub(r"/\*[\s\S]*?\*/", "", source)
    source = re.sub(r'"""[\s\S]*?"""', "", source)
    return "\n".join(line for line in source.splitlines() if not line.lstrip().startswith(("//", "#")))


def test_no_harness_kills_a_remembered_pid_tree():
    for harness in [PROFILE_MJS, *HARNESSES, E2E]:
        source = harness.read_text(encoding="utf-8")
        code = _code(source)
        assert not TREE_FLAG.search(code), f"{harness.name} still kills a PID tree"
        if harness.suffix == ".mjs" and harness is not PROFILE_MJS and "_cdp_profile.mjs" in source:
            assert "assertSafeTarget(" in source, f"{harness.name} does not refuse the live JARVIS"


def test_the_static_guard_sees_any_casing_of_the_tree_flag():
    for bad in ("execFileSync('taskkill',['/PID',pid,'/t','/F'])", 'spawnSync("taskkill",["/pid",p,"/T"])',
                "cp.exec(`taskkill /pid ${p} /t /f`)", 'subprocess.run(["taskkill", "/PID", str(p), "/T", "/F"])'):
        assert TREE_FLAG.search(bad), bad
    assert not TREE_FLAG.search("execFileSync('taskkill',['/PID',pid,'/F'])")


def test_every_harness_guards_before_it_launches_chrome():
    """H6 : le garde est appelé avant le premier `spawn(` du harnais."""
    for harness in HARNESSES:
        source = _code(harness.read_text(encoding="utf-8"))
        if "_cdp_profile.mjs" not in source:
            continue
        guard, launch = source.find("assertSafeTarget("), source.find("spawn(")
        assert guard >= 0 and (launch < 0 or guard < launch), harness.name


def _reasons(cases: dict, env: dict | None = None) -> dict:
    script = (f"import {{unsafeTargetReason}} from {json.dumps(PROFILE_MJS.as_uri())};"
              f"const C={json.dumps(cases)},E={json.dumps(env or {})};"
              "const out={};for(const [k,[page,root]] of Object.entries(C))out[k]=unsafeTargetReason(page,root,E);"
              "process.stdout.write(JSON.stringify(out));")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "reasons.mjs"
        path.write_text(script, encoding="utf-8")
        done = subprocess.run([_node(), str(path)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_target_guard_refuses_the_live_ports_and_runtime_roots():
    instance = str(Path.home() / ".jarvis" / "instances" / "jarvis-abc" / "runtime")
    out = _reasons({"ui": ["http://127.0.0.1:17654/", None], "core": ["http://127.77.0.1:17653/v1/health", None],
                    "sandbox": [SANDBOX, None], "file": ["C:/tmp/served.html", None],
                    "instance": [SANDBOX, instance], "checkout": [SANDBOX, "C:/Projects/jarvis/jarvis/runtime"],
                    "checkout_sub": [SANDBOX, "c:\\projects\\jarvis\\jarvis\\runtime\\x"],
                    "worktree": [SANDBOX, "C:/Projects/jarvis/orch/runtime"],
                    "scratch": [SANDBOX, str(Path(tempfile.gettempdir()) / "s09" / "runtime")]})
    assert "17654" in out["ui"] and "17653" in out["core"] and out["ui"].startswith("refus")
    assert out["sandbox"] == "" and out["file"] == "" and out["worktree"] == "" and out["scratch"] == ""
    assert "racine d'instance" in out["instance"] and "checkout principale" in out["checkout"]
    assert out["checkout_sub"].startswith("refus")


def _short_name(path: Path) -> str:
    done = subprocess.run(f'cmd /c for %I in ("{path}") do @echo %~sI', capture_output=True, text=True, timeout=30,
                          check=False, shell=False)
    return done.stdout.strip()


@pytest.mark.skipif(sys.platform != "win32", reason="graphies de chemin Windows")
def test_windows_spellings_of_a_live_root_are_refused():
    cases = {
        "verbatim": [SANDBOX, r"\\?\C:\Projects\jarvis\jarvis\runtime\x"],
        "verbatim_unc": [SANDBOX, r"\\?\UNC\localhost\c$\Projects\jarvis\jarvis\runtime"],
        "unc": [SANDBOX, r"\\localhost\c$\Projects\jarvis\jarvis\runtime"],
        "unc_ip": [SANDBOX, r"\\127.0.0.1\C$\Projects\jarvis\jarvis\runtime\y"],
        "upper": [SANDBOX, r"C:\PROJECTS\JARVIS\JARVIS\RUNTIME"],
        "fine": [SANDBOX, str(Path(tempfile.gettempdir()) / "s09-sandbox" / "runtime")],
    }
    instances = Path.home() / ".jarvis" / "instances"
    short = _short_name(instances) if instances.is_dir() else ""
    if short and short.lower() != str(instances).lower() and "~" in short:
        cases["short_8_3"] = [SANDBOX, short + r"\not-yet\runtime"]
    with tempfile.TemporaryDirectory(prefix="jarvis-long-directory-name-") as tmp:
        # Nom court d'un dossier temporaire déclaré comme dossier d'exécution du JARVIS vivant.
        tmp_short = _short_name(Path(tmp))
        env = {"JARVIS_RUNTIME_DIR": tmp}
        if tmp_short and "~" in tmp_short:
            cases["short_8_3_configured"] = [SANDBOX, tmp_short + r"\runtime"]
        out = _reasons(cases, env=env)
    for key, value in out.items():
        if key == "fine":
            assert value == "", value
        else:
            assert value.startswith("refus"), (key, cases[key], value)


@pytest.mark.skipif(sys.platform != "win32", reason="jonction Windows")
def test_a_junction_to_a_configured_live_dir_is_refused():
    """La jonction pointe vers un dossier TEMPORAIRE déclaré comme `JARVIS_RUNTIME_DIR` du JARVIS vivant."""
    with tempfile.TemporaryDirectory() as tmp:
        target, link = Path(tmp) / "live-runtime", Path(tmp) / "junction"
        target.mkdir()
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True,
                              timeout=30, check=False)
        if done.returncode != 0:
            pytest.skip(f"mklink /J refusé : {done.stdout} {done.stderr}")
        try:
            out = _reasons({"junction": [SANDBOX, str(link / "sub")], "direct": [SANDBOX, str(target)],
                            "other": [SANDBOX, str(Path(tmp) / "elsewhere")]},
                           env={"JARVIS_RUNTIME_DIR": str(target)})
        finally:
            os.rmdir(link)  # retire la jonction seule, jamais sa cible
        assert out["junction"].startswith("refus") and "JARVIS_RUNTIME_DIR" in out["junction"], out
        assert out["direct"].startswith("refus") and out["other"] == "", out


def test_configured_ports_and_data_root_are_refused_too():
    with tempfile.TemporaryDirectory() as tmp:
        out = _reasons({"core": ["http://127.77.0.1:28111/v1/health", None], "ui": ["http://127.0.0.1:28112/", None],
                        "data": [SANDBOX, str(Path(tmp) / "live-data" / "runtime")],
                        "free": ["http://127.0.0.1:28113/", str(Path(tmp) / "sandbox")]},
                       env={"JARVIS_CORE_PORT": "28111", "JARVIS_UI_PORT": "28112",
                            "JARVIS_DATA_ROOT": str(Path(tmp) / "live-data")})
    assert "28111" in out["core"] and "28112" in out["ui"], out
    assert "JARVIS_DATA_ROOT" in out["data"] and out["free"] == "", out


@pytest.mark.parametrize("harness", ["_interaction_mode_browser.mjs", "_status_centre_browser.mjs"])
def test_a_harness_aimed_at_the_live_jarvis_stops_before_launching_chrome(harness):
    done = subprocess.run([_node(), str(UNIT / harness), "http://127.0.0.1:17654/", "no-chrome.exe", "[]"],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 2
    assert "JARVIS vivant" in done.stderr and "17654" in done.stderr


def test_a_harness_given_the_live_runtime_root_stops():
    done = subprocess.run([_node(), str(UNIT / "_interaction_mode_browser.mjs"), "http://127.0.0.1:27654/",
                           "no-chrome.exe", "[]", r"\\?\C:\Projects\jarvis\jarvis\runtime"],
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


@pytest.mark.skipif(sys.platform != "win32", reason="arrêt vérifié Windows")
def test_the_e2e_driver_stops_its_tree_by_identity_and_nothing_else():
    import importlib.util
    spec = importlib.util.spec_from_file_location("e2e_session_capture_under_test", E2E)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    spawn_child = ("import subprocess,sys,time;c=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
                   "print(c.pid,flush=True);time.sleep(60)")
    stranger = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"])
    procs = [stranger]
    try:
        # Identité exacte : l'arbre entier s'arrête.
        parent = subprocess.Popen([sys.executable, "-c", spawn_child], stdout=subprocess.PIPE, text=True)
        procs.append(parent)
        child = int(parent.stdout.readline())
        born = module.process_born(parent.pid)
        assert born and module.process_born(child)
        module.kill_tree_verified(parent, born)
        parent.wait(timeout=20)
        for _ in range(40):
            if not module.process_born(child):
                break
            time.sleep(0.25)
        assert not module.process_born(child), "the launched tree is stopped"
        # Autre identité (PID réemployé) : l'arbre n'est pas parcouru ; seul le handle ouvert arrête CE processus.
        other = subprocess.Popen([sys.executable, "-c", spawn_child], stdout=subprocess.PIPE, text=True)
        procs.append(other)
        grandchild = int(other.stdout.readline())
        module.kill_tree_verified(other, "2000-01-01T00:00:00.0000000Z")
        other.wait(timeout=20)
        assert module.process_born(grandchild), "a tree whose identity does not match is never walked"
        subprocess.run(["taskkill", "/PID", str(grandchild), "/F"], capture_output=True, check=False)
        assert stranger.poll() is None, "a process outside the tree is never touched"
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)
