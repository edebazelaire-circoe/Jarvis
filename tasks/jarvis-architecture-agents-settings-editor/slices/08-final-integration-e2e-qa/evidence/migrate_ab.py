"""Même ancien fichier de réglages, même geste (Réglages ouverts, Comportement : verbosité changée, « Enregistrer »),
une fois avec le Control Center de main (ad1e7f4d, worktree de base détaché) et une fois avec celui de la branche S08.
Les deux fichiers obtenus sont comparés : ce que la branche change à la migration est leur différence.
Bac à sable : ports 27653/27654, racines au scratchpad, arrêt par PID exact."""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, r"C:\Projects\jarvis\arch-s08")
import s08_sandbox as S  # noqa: E402
from tests.unit.test_wake_word_settings_browser import CHROME_CANDIDATES, HARNESS, click, eval_, open_settings, wait  # noqa: E402

TREES = {"main": S.BASE, "s08": S.WORKTREE}
ROOT = S.SCRATCH / "s08-migrate-ab"
PLAN = [{"width": 1440, "height": 900, "actions": [
    wait("!!document.getElementById('openSettings')"), click("#dockMore"), *open_settings(),
    eval_("(selectTab('agent_behavior'),0)"),
    wait("!!document.querySelector('[data-behavior-field=response_verbosity]')", 8000),
    eval_("""(()=>{const s=document.querySelector('[data-behavior-field=response_verbosity]');s.value='detailed';
      s.dispatchEvent(new Event('change',{bubbles:true}));return s.value})()""", "picked"),
    click("#modalSave"),
    wait("document.getElementById('modalStatus').textContent==='Enregistré.'", 8000),
]}]


def run(name: str, tree: Path) -> dict:
    sandbox = ROOT / name
    if sandbox.exists():
        shutil.rmtree(sandbox)
    (sandbox / "data").mkdir(parents=True)
    runtime = sandbox / "runtime"
    runtime.mkdir()
    shutil.copy2(S.SANDBOX / "settings-before.json", runtime / "control-center-settings.json")
    env = {k: v for k, v in os.environ.items() if not k.startswith("JARVIS_")}
    env.update(JARVIS_DATA_ROOT=str(sandbox / "data"), JARVIS_RUNTIME_DIR=str(runtime), JARVIS_CORE_PORT="27653",
               JARVIS_UI_PORT="27654", JARVIS_VISUALIZER_ENABLED="0", PYTHONIOENCODING="utf-8")
    assert S.ports_free()
    log = open(sandbox / "control-center.log", "w", encoding="utf-8")
    proc = subprocess.Popen([str(S.PY), "-m", "jarvis", "control-center"], cwd=tree, env=env, stdout=log,
                            stderr=subprocess.STDOUT)
    S.say(f"[{name}] control-center lancé depuis {tree} : PID {proc.pid}")
    try:
        for _ in range(160):
            try:
                urllib.request.urlopen(S.UI + "/api/status", timeout=2).read()
                break
            except OSError:
                time.sleep(0.5)
        chrome = next((str(c) for c in CHROME_CANDIDATES if c.is_file()), None)
        done = subprocess.run([shutil.which("node"), str(HARNESS), S.UI + "/", chrome, json.dumps(PLAN)],
                              capture_output=True, text=True, encoding="utf-8", timeout=300)
        out = json.loads(done.stdout)
        waits = [a for a in out["steps"][0]["actions"] if a.get("a") == "wait"]
        S.say(f"[{name}] attentes tenues {sum(1 for w in waits if w['ok'])}/{len(waits)} ; console {out['console']}")
    finally:
        try:
            urllib.request.urlopen(urllib.request.Request(S.UI + "/api/agent/kill", data=b"{}", method="POST",
                                                          headers={"Content-Type": "application/json"}), timeout=60).read()
        except OSError:
            pass
        proc.terminate()  # ce PID seulement
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        S.say(f"[{name}] control-center arrêté : PID {proc.pid}")
    return json.loads((runtime / "control-center-settings.json").read_text(encoding="utf-8"))


results = {name: run(name, tree) for name, tree in TREES.items()}
main, s08 = (dict(S.leaves(results[k])) for k in ("main", "s08"))
before = dict(S.leaves(json.loads((S.SANDBOX / "settings-before.json").read_text(encoding="utf-8"))))
diff = {k: [main.get(k, "<absent>"), s08.get(k, "<absent>")] for k in sorted(set(main) | set(s08)) if main.get(k, "<absent>") != s08.get(k, "<absent>")}
S.say(f"(migration A/B) fichier après le même geste, main vs S08 : différences={diff}")
S.say(f"(migration A/B) clés de l'ancien fichier absentes après S08 et présentes après main : "
      f"{sorted(k for k in before if k in main and k not in s08)}")
(ROOT / "ab-result.json").write_text(json.dumps({"diff_main_vs_s08": diff}, ensure_ascii=False, indent=1), encoding="utf-8")
with open(S.SCRATCH / "s08-sandbox-evidence.log", "a", encoding="utf-8") as fh:
    fh.write("\n".join(S.LOG) + "\n")
