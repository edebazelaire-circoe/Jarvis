"""Harnais d'installation RÉELLE de la capacité Remotion (Slice 04 de jarvis-remotion-presentation-integration).

Exerce `LocalCapabilityHost` + `NodeCapabilityRunner` avec le vrai npm et le vrai réseau, dans une racine de
données privée (JAMAIS le profil vivant ; refuse toute racine sous `~/.jarvis`). Ne démarre ni n'arrête
Core, le Control Center ni la voix : il construit son propre hôte.

    python scripts/remotion_install_harness.py --work-dir C:/Users/<moi>/AppData/Local/Temp/jrs4 \
        --evidence tasks/jarvis-remotion-presentation-integration/evidence/s04-real-install.json

Scénarios (`--only a,b`) : fresh, noop, concurrent, restart, corrupt, interrupted, offline, permission, timeout, uninstall.
Chaque scénario écrit son résultat (durées, versions, taille disque, statuts typés) dans le fichier de preuve.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis.adapters import process_tree  # noqa: E402
from jarvis.adapters.file_local_capability_store import FileLocalCapabilityStore  # noqa: E402
from jarvis.adapters.node_capability_runner import NodeCapabilityRunner, NodeRuntimeSpec, default_remotion_runner  # noqa: E402
from jarvis.core.local_capability_host import LocalCapabilityHost  # noqa: E402
from jarvis.domain.local_capabilities import LocalCapabilityError  # noqa: E402
from jarvis.domain.remotion_capability import REMOTION_CAPABILITY_ID as CID, remotion_manifest  # noqa: E402


class Sink:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.events.append({"kind": kind, "level": level, "message": message, **{k: v for k, v in (data or {}).items()}})


def make_host(root: Path, runner=None):
    sink = Sink()
    host = LocalCapabilityHost(FileLocalCapabilityStore(root), runner=runner or default_remotion_runner(),
                               manifests={CID: remotion_manifest()}, diagnostics=sink)
    return host, sink


def dir_size(path: Path) -> int:
    total = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return total


def runtime(root: Path) -> Path:
    return root / "local_capabilities" / CID / "runtime"


def brief(view: dict) -> dict:
    keys = ("status", "install_status", "process_status", "health", "installed", "last_error_code", "last_error_detail", "install_attempts")
    return {k: view.get(k) for k in keys}


def timed(fn):
    t = time.monotonic()
    out = fn()
    return out, round(time.monotonic() - t, 1)


def fresh_root(work: Path, name: str) -> Path:
    root = work / name
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    return root


BASELINE_NODE: set[int] = set()


def node_pids() -> set[int]:
    if not process_tree.IS_WINDOWS:
        return set()
    out = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-Process node -ErrorAction SilentlyContinue).Id -join ','"],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    return {int(x) for x in out.split(",") if x.strip().isdigit()}


def node_processes_under(_runtime_dir: Path) -> int:
    """Processus node apparus depuis le début du harnais et toujours vivants (preuve d'absence d'orphelin ; la ligne de commande
    d'un `npm ci` ne contient pas le dossier, d'où la comparaison à un instantané plutôt qu'un filtre de chemin)."""

    return len(node_pids() - BASELINE_NODE)


# ------------------------------------------------------------------------ scénarios

def s_fresh(work: Path, ctx: dict) -> dict:
    root = fresh_root(work, "fresh")
    ctx["root"] = root
    host, sink = make_host(root)
    first, install_s = timed(lambda: host.install(CID))
    size = dir_size(runtime(root))
    record = json.loads((runtime(root) / "install-record.json").read_text(encoding="utf-8")) if (runtime(root) / "install-record.json").exists() else None
    health, health_s = timed(lambda: host.check_health(CID))
    return {"install_seconds": install_s, "install": brief(first), "disk_bytes": size, "disk_mb": round(size / 1e6, 1),
            "health_seconds": health_s, "health": brief(health), "install_record": record,
            "node_modules_count": len(list((runtime(root) / "node_modules").iterdir())) if (runtime(root) / "node_modules").exists() else 0,
            "events": [e["kind"] for e in sink.events]}


def s_noop(work: Path, ctx: dict) -> dict:
    host, sink = make_host(ctx["root"])
    before = host.status(CID)["install_attempts"]
    view, secs = timed(lambda: host.install(CID))
    return {"seconds": secs, "attempts_before": before, "attempts_after": view["install_attempts"], "status": view["status"],
            "events": [e["kind"] for e in sink.events]}


def s_concurrent(work: Path, ctx: dict) -> dict:
    root = fresh_root(work, "concurrent")
    host, sink = make_host(root)
    results: list[object] = []

    def go() -> None:
        try:
            results.append(("ok", brief(host.install(CID))["status"]))
        except LocalCapabilityError as exc:
            results.append(("refused", exc.code.value))

    threads = [threading.Thread(target=go) for _ in range(3)]
    for t in threads:
        t.start()
        time.sleep(0.3)
    for t in threads:
        t.join()
    return {"outcomes": results, "install_attempts": host.status(CID)["install_attempts"], "runtimes_on_disk": 1 if runtime(root).exists() else 0,
            "node_modules_dirs": [str(p.relative_to(root)) for p in root.rglob("node_modules") if p.parent.name != "node_modules" and p.parent == runtime(root)]}


def s_restart(work: Path, ctx: dict) -> dict:
    root = ctx["root"]
    host, sink = make_host(root)
    started, start_s = timed(lambda: host.start(CID))
    ref1 = host._load(CID).process_ref
    running_view = brief(started)
    health = brief(host.check_health(CID))
    worker = json.loads((runtime(root) / "worker.json").read_text(encoding="utf-8"))
    # « Redémarrage de Core » : un nouvel hôte sur la même racine retrouve le processus vivant (reconcile n'y touche pas).
    host2, sink2 = make_host(root)
    rec = [brief(v) for v in host2.reconcile()]
    same_ref = host2._load(CID).process_ref == ref1
    stopped, stop_s = timed(lambda: host2.stop(CID))
    gone = not process_tree.ref_alive(ref1)
    restarted, restart_s = timed(lambda: host2.start(CID))
    ref2 = host2._load(CID).process_ref
    host2.stop(CID)
    # Processus tué hors de l'hôte puis reconcile : état plantée honnête.
    host3, _ = make_host(root)
    host3.start(CID)
    ref3 = host3._load(CID).process_ref
    process_tree.kill_tree(process_tree.parse_process_ref(ref3)[0])
    host4, _ = make_host(root)
    after_kill = [brief(v) for v in host4.reconcile()]
    recovered = brief(host4.start(CID))
    host4.stop(CID)
    return {"start_seconds": start_s, "running": running_view, "health_while_running": health, "worker_port": worker["port"],
            "reconcile_after_core_restart": rec, "same_process_ref_after_core_restart": same_ref, "stop_seconds": stop_s,
            "stopped": brief(stopped), "child_gone_after_stop": gone, "restart_seconds": restart_s, "restarted_new_ref": ref2 != ref1,
            "after_external_kill_reconcile": after_kill, "start_after_crash": recovered,
            "orphan_node_processes": node_processes_under(runtime(root))}


def s_corrupt(work: Path, ctx: dict) -> dict:
    root = ctx["root"]
    host, sink = make_host(root)
    nm = runtime(root) / "node_modules"
    # 1) suppression d'un fichier d'un paquet épinglé  2) troncature d'un autre fichier  3) paquet transitif retiré
    bundler = nm / "@remotion" / "bundler"
    victim = sorted(p for p in bundler.rglob("*.js") if p.is_file())[0]
    victim.unlink()
    trunc = sorted(p for p in (nm / "remotion").rglob("*.js") if p.is_file() and p.stat().st_size > 200)[0]
    trunc.write_bytes(trunc.read_bytes()[:50])
    shutil.rmtree(nm / "scheduler", ignore_errors=True)
    health, h_s = timed(lambda: host.check_health(CID))
    repaired, r_s = timed(lambda: host.repair(CID))
    after = brief(host.check_health(CID))
    return {"corrupted": ["deleted a file of @remotion/bundler", "truncated a file of remotion", "removed transitive scheduler"],
            "health_after_corruption": brief(health), "health_check_seconds": h_s, "repair_seconds": r_s, "after_repair": brief(repaired),
            "health_after_repair": after, "events": [e["kind"] for e in sink.events]}


def s_corrupt_truncate_only(work: Path, ctx: dict) -> dict:
    root = ctx["root"]
    host, _ = make_host(root)
    nm = runtime(root) / "node_modules"
    trunc = sorted(p for p in (nm / "@remotion" / "player").rglob("*.js") if p.is_file() and p.stat().st_size > 200)[0]
    trunc.write_bytes(trunc.read_bytes()[:50])
    health = brief(host.check_health(CID))
    repaired = brief(host.repair(CID))
    return {"health_after_truncate": health, "after_repair": repaired}


def child_install(root: Path) -> None:
    host, _ = make_host(root)
    host.install(CID)


def s_interrupted(work: Path, ctx: dict) -> dict:
    root = fresh_root(work, "interrupted")
    proc = subprocess.Popen([sys.executable, "-I", str(Path(__file__).resolve()), "--child-install", str(root)], cwd=str(ROOT),
                            env={**os.environ, "PYTHONPATH": str(ROOT)})
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline and not (runtime(root) / "node_modules").exists():
        time.sleep(0.2)
    time.sleep(3)  # npm ci est en plein transfert : l'arbre est à moitié écrit
    state_mid = json.loads((root / "local_capabilities" / CID / "state.json").read_text(encoding="utf-8"))["install_status"]
    process_tree.kill_tree(proc.pid)  # « arrêt de Core » pendant l'installation : l'arbre entier meurt, rien n'est nettoyé
    proc.wait()
    orphans = node_processes_under(runtime(root))
    nm_partial = (runtime(root) / "node_modules").exists()
    host, sink = make_host(root)
    shown_before = host.status(CID)["status"]
    rec = [brief(v) for v in host.reconcile()]
    repaired, secs = timed(lambda: host.repair(CID))
    return {"state_when_killed": state_mid, "orphan_node_processes_after_kill": orphans, "partial_node_modules_left": nm_partial,
            "status_shown_before_reconcile": shown_before, "reconcile": rec, "repair_seconds": secs, "after_repair": brief(repaired),
            "health": brief(host.check_health(CID)), "stale_lock_file_left": (runtime(root) / ".install.lock").exists(),
            "events": [e["kind"] for e in sink.events]}


def s_offline(work: Path, ctx: dict) -> dict:
    root = fresh_root(work, "offline")
    runner = default_remotion_runner()
    base_env = dict(os.environ)
    base_env.update({"HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9"})
    offline = NodeCapabilityRunner(runner._spec, environ=base_env)
    host, sink = make_host(root, offline)
    view, secs = timed(lambda: host.install(CID))
    ok_after = None
    host2, _ = make_host(root)  # réseau rétabli : le même état se répare
    ok_after = brief(host2.repair(CID))
    return {"seconds": secs, "install": brief(view), "after_network_back_repair": ok_after}


def s_permission(work: Path, ctx: dict) -> dict:
    root = fresh_root(work, "permission")
    host, _ = make_host(root)
    rt = runtime(root)
    rt.mkdir(parents=True, exist_ok=True)
    sid = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True).stdout.strip().split(",")[1].strip('"')
    subprocess.run(["icacls", str(rt), "/deny", f"*{sid}:(WD,AD)"], capture_output=True, check=True)  # refuse la création de fichiers/dossiers
    try:
        view = brief(host.install(CID))
    finally:
        subprocess.run(["icacls", str(rt), "/remove:d", f"*{sid}"], capture_output=True)
    after = brief(host.repair(CID))
    return {"install_with_write_denied": view, "repair_after_permission_restored": after}


def s_timeout(work: Path, ctx: dict) -> dict:
    root = fresh_root(work, "timeout")
    base = default_remotion_runner()
    spec = NodeRuntimeSpec(base._spec.assets_dir, base._spec.node_minimum, base._spec.npm_minimum, base._spec.supported_platforms,
                           install_timeout_s=6.0)
    host, _ = make_host(root, NodeCapabilityRunner(spec))
    view, secs = timed(lambda: host.install(CID))
    time.sleep(2)
    return {"seconds": secs, "install": brief(view), "orphan_node_processes_after_timeout": node_processes_under(runtime(root))}


def s_uninstall(work: Path, ctx: dict) -> dict:
    root = ctx["root"]
    sources = root / "presentation" / "sources" / "deck-1"
    sources.mkdir(parents=True, exist_ok=True)
    (sources / "Deck.tsx").write_text("export const Deck = () => null;\n", encoding="utf-8")
    assets = root / "presentation" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "logo.png").write_bytes(b"\x89PNG-fake")
    before = {str(p.relative_to(root)): p.stat().st_size for p in (root / "presentation").rglob("*") if p.is_file()}
    host, _ = make_host(root)
    host.start(CID)
    view, secs = timed(lambda: host.uninstall(CID))
    after = {str(p.relative_to(root)): p.stat().st_size for p in (root / "presentation").rglob("*") if p.is_file()}
    left = sorted(p.name for p in runtime(root).iterdir()) if runtime(root).exists() else []
    reinstalled, again_s = timed(lambda: host.install(CID))
    return {"uninstall_seconds": secs, "uninstall": brief(view), "presentation_files_before": before, "presentation_files_unchanged": before == after,
            "runtime_entries_left": left, "reinstall_seconds_after_uninstall": again_s, "reinstall": brief(reinstalled)}


SCENARIOS = {"fresh": s_fresh, "noop": s_noop, "restart": s_restart, "corrupt": s_corrupt, "truncate": s_corrupt_truncate_only,
             "uninstall": s_uninstall, "concurrent": s_concurrent, "interrupted": s_interrupted, "offline": s_offline,
             "permission": s_permission, "timeout": s_timeout}
ORDER = ["fresh", "noop", "restart", "truncate", "corrupt", "uninstall", "concurrent", "interrupted", "offline", "permission", "timeout"]


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--child-install":
        child_install(Path(sys.argv[2]))
        return 0
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--only", default=",".join(ORDER))
    args = parser.parse_args()
    work = Path(args.work_dir).resolve()
    if ".jarvis" in work.parts:
        print("refus : la racine de travail ne doit pas être le profil vivant", file=sys.stderr)
        return 2
    work.mkdir(parents=True, exist_ok=True)
    evidence_path = Path(args.evidence)
    report = json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path.exists() else {}
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    node = subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip()
    npm = subprocess.run(["node", str(Path(shutil.which("node")).parent / "node_modules/npm/bin/npm-cli.js"), "--version"], capture_output=True, text=True).stdout.strip()
    report["environment"] = {"branch_head_at_run": head, "dirty_tree": bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip()),
                             "os": platform.platform(), "python": sys.version.split()[0], "node": node, "npm": npm,
                             "work_dir": str(work), "run_at": datetime.now(timezone.utc).isoformat()}
    BASELINE_NODE.update(node_pids())
    ctx: dict = {}
    if (work / "fresh").exists():
        ctx["root"] = work / "fresh"
    for name in [n for n in args.only.split(",") if n]:
        print(f"== {name}", flush=True)
        try:
            report[name] = SCENARIOS[name](work, ctx)
        except Exception as exc:  # noqa: BLE001 - le harnais consigne l'échec, il ne le masque pas
            report[name] = {"harness_error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(report[name], indent=1, default=str)[:1500], flush=True)
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
