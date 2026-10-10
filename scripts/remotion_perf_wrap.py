"""Mesure de ressources d'une commande Remotion (Slice 22 de jarvis-remotion-presentation-integration ; `docs/remotion-integration-release.md` §6).

    python scripts/remotion_perf_wrap.py --label render-happy --out <fichier.json> [--interval 2] -- <commande...>

Lance la commande telle quelle (le wrapper n'ouvre aucun service de Jarvis), échantillonne toutes les `--interval` secondes l'ARBRE de ses processus
descendants par PowerShell (`Win32_Process` : mémoire de travail, nombre de processus, noms), et écrit : durée, pic de mémoire de travail de l'arbre,
pic du nombre de processus, noms vus, courbe échantillonnée, code de sortie. Windows seulement (c'est la seule plateforme éprouvée) ; sans dépendance
(pas de psutil). La mémoire de travail compte les pages partagées plusieurs fois : c'est un majorant de l'empreinte, pas la mémoire privée.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

SNAPSHOT = ("Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,WorkingSetSize,Name | ConvertTo-Json -Compress")


def snapshot() -> list[dict]:
    done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", SNAPSHOT], capture_output=True, text=True, timeout=60, check=False)
    try:
        rows = json.loads(done.stdout or "[]")
    except ValueError:
        return []
    return rows if isinstance(rows, list) else [rows]


def tree_of(rows: list[dict], root: int) -> list[dict]:
    children: dict[int, list[dict]] = {}
    for row in rows:
        children.setdefault(int(row["ParentProcessId"]), []).append(row)
    found, stack = [], [root]
    seen = {root}
    while stack:
        for child in children.get(stack.pop(), []):
            pid = int(child["ProcessId"])
            if pid not in seen:
                seen.add(pid)
                found.append(child)
                stack.append(pid)
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = [c for c in args.command if c != "--"]
    if not command:
        parser.error("no command")
    samples: list[dict] = []
    names: dict[str, int] = {}
    stop = threading.Event()
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[1])

    def sample() -> None:
        while not stop.is_set():
            try:
                found = tree_of(snapshot(), process.pid)
            except (subprocess.TimeoutExpired, KeyError, ValueError, OSError):
                found = []
            ws = sum(int(r.get("WorkingSetSize") or 0) for r in found)
            for row in found:
                names[row["Name"]] = max(names.get(row["Name"], 0), 1)
            samples.append({"t": round(time.monotonic() - started, 1), "processes": len(found), "working_set_mb": round(ws / 1048576, 1),
                            "by_name": {n: sum(1 for r in found if r["Name"] == n) for n in sorted({r["Name"] for r in found})}})
            stop.wait(args.interval)

    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    code = process.wait()
    stop.set()
    thread.join(timeout=70)
    result = {
        "label": args.label, "command": [Path(c).name if os.path.isabs(c) else c for c in command], "exit_code": code,
        "seconds": round(time.monotonic() - started, 1), "interval_s": args.interval, "sampled": len(samples),
        "peak_working_set_mb": max((s["working_set_mb"] for s in samples), default=0),
        "peak_processes": max((s["processes"] for s in samples), default=0),
        "process_names_seen": sorted(names), "samples": samples[:: max(1, len(samples) // 60)],
        "when": datetime.now(timezone.utc).isoformat(timespec="seconds"), "platform": sys.platform,
        "note": "working set counts shared pages once per process: an upper bound of the footprint, not private memory; the wrapper process and PowerShell sampler are not in the tree"}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("label", "exit_code", "seconds", "peak_working_set_mb", "peak_processes", "process_names_seen")}))
    return code


if __name__ == "__main__":
    sys.exit(main())
