"""Harnais de PREUVE RÉELLE du Player Remotion dans Jarvis (Slice 10 de jarvis-remotion-presentation-integration).

Joue, dans un vrai Chrome sans tête, une scène Remotion depuis une Presentation sur un Core ISOLÉ composé comme `jarvis/app.py`
(vrai compilateur Node + esbuild, vrai bac à sable sur `127.77.0.2`, vrai Control Center, vrai prefab host), puis les scénarios
d'échec : moteur indisponible (runtime désinstallé : réponse typée, rien ne joue, jamais de HTML), erreur de compilation, cadre
figé retiré par le chien de garde, navigation vers une origine de Jarvis sans requête (et son contrôle positif).

    python scripts/remotion_player_harness.py --runtime-dir <racine>/local_capabilities/remotion/runtime \\
        --evidence tasks/jarvis-remotion-presentation-integration/slices/10-remotion-player-host/evidence

Le harnais est `tests/unit/test_remotion_player_realpage_browser.py` lancé avec `JARVIS_REMOTION_EVIDENCE_DIR` : une seule source de
vérité (les assertions du test sont la preuve), ce script en garde les mesures (`<scénario>.json`), les captures et écrit
`real-player.json` (SHA du dépôt et état de l'arbre, versions de Chrome, Node et Python, résultat de pytest, durée).

Rien ne démarre ni n'arrête le Jarvis vivant : Core, Control Center et bac à sable de chaque épreuve vivent sur des ports libres et une racine
de données jetable ; le runtime est « prêt » par copie des petits fichiers d'une installation existante et une jonction vers son
`node_modules` (jamais une installation de plus, jamais le profil vivant).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CHROME = (Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
          Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe")


def run(command: list[str], **kwargs) -> str:
    done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", **kwargs)
    return (done.stdout or "").strip()


def chrome_version() -> str:
    for path in CHROME:
        if path.exists():
            return run(["powershell", "-NoProfile", "-Command", f"(Get-Item '{path}').VersionInfo.ProductVersion"]) or "unknown"
    return "absent"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runtime-dir", required=True, help="dossier runtime/ d'une installation Remotion existante (avec node_modules)")
    parser.add_argument("--evidence", required=True, help="dossier de sortie (real-player.json, scénarios, captures)")
    options = parser.parse_args()
    runtime = Path(options.runtime_dir).resolve()
    evidence = Path(options.evidence).resolve()
    if not (runtime / "node_modules").is_dir() or not (runtime / "runtime-host.mjs").is_file():
        print(f"not an installed Remotion runtime: {runtime}", file=sys.stderr)
        return 2
    evidence.mkdir(parents=True, exist_ok=True)
    for stale in evidence.glob("*.json"):
        stale.unlink()
    env = {**os.environ, "JARVIS_REMOTION_RUNTIME_DIR": str(runtime), "JARVIS_REMOTION_EVIDENCE_DIR": str(evidence)}
    for name in ("JARVIS_UI_PORT", "JARVIS_VISUALIZER_PORT", "JARVIS_CORE_HOST"):
        env.pop(name, None)  # the user's own ports never reach an isolated Core
    started = time.monotonic()
    done = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "--no-header", "-rA",
                           "tests/unit/test_remotion_player_realpage_browser.py"], cwd=ROOT, env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    elapsed = round(time.monotonic() - started, 1)
    summary = [line for line in done.stdout.splitlines() if re.match(r"(PASSED|FAILED|ERROR|SKIPPED)\b|\d+ (passed|failed)", line)]
    scenarios = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(evidence.glob("*.json"))
                 if path.name != "real-player.json"}
    status = run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT)
    report = {
        "slice": 10, "handoff": "jarvis-remotion-presentation-integration",
        "when": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repository": {"head": run(["git", "rev-parse", "HEAD"], cwd=ROOT), "branch": run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT),
                       "tracked_tree_clean": not status, "dirty_files": status.splitlines()[:20]},
        "environment": {"platform": platform.platform(), "python": platform.python_version(), "node": run(["node", "--version"]),
                        "chrome": chrome_version(), "runtime_dir_reused": "node_modules is a junction to an existing private install"},
        "pytest": {"returncode": done.returncode, "seconds": elapsed, "summary": summary[-20:]},
        "scenarios": sorted(scenarios),
        "result": "PASSED" if done.returncode == 0 else "FAILED",
    }
    (evidence / "real-player.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("result", "scenarios")}, ensure_ascii=False))
    if done.returncode != 0:
        print(done.stdout[-3000:], file=sys.stderr)
    return done.returncode


if __name__ == "__main__":
    raise SystemExit(main())
