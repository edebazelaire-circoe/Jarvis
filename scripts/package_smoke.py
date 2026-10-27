#!/usr/bin/env python3
"""Essai du paquet INSTALLÉ (Slice 10, `docs/release.md` › *Package smoke*), sans aucun prérequis de développement.

    python scripts/package_smoke.py --installer JARVIS-Setup.exe --work DIR [--report FILE] [--ports 43653]

Tout vit sous `--work` : cible d'installation (`--target` explicite), `LOCALAPPDATA` et `TEMP` simulés, ruche JSON,
menu Démarrer et Bureau simulés. Les enfants reçoivent un environnement réduit : PATH = `System32;Windows`, aucune
variable Python/Node, `JARVIS_OPEN_BROWSER=0`, `JARVIS_VISUALIZER_ENABLED=0`, `JARVIS_LAUNCH_VOICE=0`, ports dédiés.
Étapes, chacune jugée (`ok`) dans le rapport :

1. `snapshot_before` : instantané du VRAI profil (clés `HKCU\\…\\Uninstall`, `%LOCALAPPDATA%\\Programs`,
   `%LOCALAPPDATA%\\CIRCOE`, raccourcis JARVIS du Bureau et du menu Démarrer) ;
2. `seed` : un profil d'une version précédente (`release_seed_profile.py`) dans la maison simulée ;
3. `install` : l'installeur réel en `/S` ; la maison semée doit rester identique à l'octet ;
4. `launch` : le lanceur du produit installé ; `/v1/health` prêt, runtimes privés `ok` malgré le PATH réduit,
   édition `presentation`, Boards du profil semé listés, profil migré avec ses sauvegardes (`verify`) ;
5. `crash_core`, `crash_ui` : l'enfant POSSÉDÉ (descendant vérifié du lanceur que ce script a lancé, PID et heure de
   création) est tué ; le lanceur le relance, Core redevient prêt, le profil est intact ;
6. `support_bundle` : `python -m jarvis support-bundle` du paquet ; un faux secret et le chemin du profil absents ;
7. `quit` : « Quitter JARVIS » ; aucun processus du programme ne reste ; `verify_package` du programme intact ;
8. `repair` : réinstallation de la même version, maison identique à l'octet ;
9. `kill_launcher` : relance, puis le lanceur (lancé ici) est tué : ses Job Objects emportent tout l'arbre ;
10. `uninstall` : `--quiet` ; programme retiré, maison gardée ;
11. `snapshot_after` : le vrai profil est identique à l'instantané du début.

Code 0 : toutes les étapes vertes. Rien n'est lancé depuis un checkout de développement ; aucun processus que ce
script n'a pas lancé n'est arrêté.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis import private_runtime as PR  # noqa: E402 - après le chemin du dépôt
from jarvis.adapters import process_tree  # noqa: E402
from scripts import release_seed_profile as SEED  # noqa: E402

SCHEMA = "jarvis.package-smoke"
FAKE_SECRET = "sk-ant-api03-SMOKEfakeSMOKEfake0123456789"
KEEP_ENV = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "USERPROFILE", "APPDATA", "PROGRAMDATA",
            "PROGRAMFILES", "PROGRAMFILES(X86)", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "OS", "HOMEDRIVE",
            "HOMEPATH", "USERNAME")
UNINSTALL_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall"


class SmokeFailure(AssertionError):
    """Une étape jugée rouge : son message dit ce qui manque."""


def check(condition: object, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def sha_tree(root: Path, *, skip: Callable[[str], bool] = lambda relative: False) -> dict[str, str]:
    found = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_file() and not skip(relative):
            found[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


class Smoke:
    def __init__(self, installer: Path, work: Path, core_port: int) -> None:
        self.installer = installer
        self.work = work
        self.inst = work / "inst"
        self.target = self.inst / "Local" / "Programs" / "CIRCOE" / "Jarvis"
        self.hive = self.inst / "hive.json"
        self.start_menu = self.inst / "StartMenu"
        self.desktop = self.inst / "Desktop"
        self.local = work / "home" / "Local"
        self.home = self.local / "CIRCOE" / "Jarvis"
        self.tmp = work / "tmp"
        self.logs = work / "logs"
        self.core_port, self.ui_port = core_port, core_port + 1
        self.core_url = f"http://127.77.0.1:{self.core_port}"
        self.ui_url = f"http://127.0.0.1:{self.ui_port}"
        self.steps: list[dict] = []
        self.launcher: subprocess.Popen | None = None
        self.seed_manifest: dict | None = None

    # ------------------------------------------------------------------ outils

    def env(self) -> dict[str, str]:
        base = {key: os.environ[key] for key in KEEP_ENV if key in os.environ}
        root = os.environ.get("SYSTEMROOT", "C:\\Windows")
        self.tmp.mkdir(parents=True, exist_ok=True)
        base.update({"PATH": str(Path(root) / "System32") + ";" + root, "LOCALAPPDATA": str(self.local),
                     "TEMP": str(self.tmp), "TMP": str(self.tmp), "JARVIS_CORE_PORT": str(self.core_port),
                     "JARVIS_UI_PORT": str(self.ui_port), "JARVIS_REMOTION_SANDBOX_PORT": str(self.core_port + 2),
                     "JARVIS_VISUALIZER_PORT": str(self.core_port + 3), "JARVIS_VISUALIZER_ENABLED": "0",
                     "JARVIS_OPEN_BROWSER": "0", "JARVIS_LAUNCH_VOICE": "0", "JARVIS_LAUNCHER_NOTIFY": "stderr"})
        return base

    def python(self, gui: bool = False) -> Path:
        return self.target / "runtime" / "python" / ("pythonw.exe" if gui else "python.exe")

    def step(self, name: str, action: Callable[[], dict | None]) -> bool:
        started = time.monotonic()
        print(f"[smoke] {name}…", flush=True)
        row: dict = {"step": name}
        try:
            row.update(action() or {})
            row["ok"] = True
        except SmokeFailure as exc:
            row.update({"ok": False, "failure": str(exc)})
        except Exception as exc:  # noqa: BLE001 - a crash of a step is reported as that step's failure, with its trace
            row.update({"ok": False, "failure": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-3000:]})
        row["seconds"] = round(time.monotonic() - started, 1)
        print(f"[smoke] {name} : {'OK' if row['ok'] else 'ÉCHEC ' + row['failure']} ({row['seconds']} s)", flush=True)
        self.steps.append(row)
        return row["ok"]

    def http(self, method: str, url: str, *, token: bool = False, timeout: float = 20.0) -> tuple[int | None, object]:
        headers = {"Content-Type": "application/json"} if method == "POST" else {}
        if token:
            headers["Authorization"] = "Bearer " + (self.home / "runtime" / "core.token").read_text(encoding="utf-8").strip()
        request = urllib.request.Request(url, method=method, data=b"{}" if method == "POST" else None, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - loopback only
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()[:500].decode("utf-8", errors="replace")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return None, f"{type(exc).__name__}: {exc}"

    def wait(self, what: str, probe: Callable[[], object], timeout: float, *, every: float = 1.0) -> object:
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            last = probe()
            if last:
                return last
            if self.launcher is not None and self.launcher.poll() is not None:
                raise SmokeFailure(f"{what} : le lanceur est sorti (code {self.launcher.returncode}) ; "
                                   f"voir {self.home / 'runtime' / 'logs' / 'launcher.log'}")
            time.sleep(every)
        raise SmokeFailure(f"{what} : rien en {timeout:.0f} s (dernier relevé {last!r})")

    def health(self) -> dict | None:
        status, payload = self.http("GET", self.core_url + "/v1/health", token=True)
        return payload if status == 200 and isinstance(payload, dict) and payload.get("ready") else None

    def processes_under(self, root: Path) -> list[str]:
        script = ("Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith('"
                  + str(root).replace("'", "''") + "', 'OrdinalIgnoreCase') } | ForEach-Object { \"$($_.ProcessId) $($_.Name)\" }")
        done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=120, check=False)
        return [line.strip() for line in done.stdout.splitlines() if line.strip()]

    def launcher_events(self) -> list[dict]:
        path = self.home / "runtime" / "logs" / "launcher.log"
        try:
            return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, ValueError):
            return []

    def launcher_state(self) -> dict:
        return json.loads((self.home / "runtime" / "launcher.json").read_text(encoding="utf-8"))

    def role_pid(self, role: str) -> int | None:
        try:
            return self.launcher_state()["roles"][role]["pid"]
        except (OSError, ValueError, KeyError, TypeError):
            return None  # intentional: launcher.json is being rewritten; the caller polls again

    # ------------------------------------------------------------------ vrai profil (lecture seule)

    def real_profile(self) -> dict:
        local = Path(os.environ["LOCALAPPDATA"])
        appdata = Path(os.environ.get("APPDATA", local))
        keys = subprocess.run(["reg", "query", UNINSTALL_KEY], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60, check=False).stdout
        desktop = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
        return {"uninstall_keys": sorted(line.strip() for line in keys.splitlines() if line.strip()),
                "local_programs": sorted(p.name for p in (local / "Programs").iterdir()) if (local / "Programs").is_dir() else [],
                "local_circoe": (local / "CIRCOE").exists(),
                "shortcuts": {str(p): p.exists() for p in (desktop / "JARVIS.lnk",
                                                         appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "JARVIS.lnk")}}

    # ------------------------------------------------------------------ étapes

    def run_setup(self, tag: str) -> dict:
        result, log = self.inst / f"result-{tag}.json", self.inst / f"setup-{tag}.log"
        self.inst.mkdir(parents=True, exist_ok=True)
        done = subprocess.run([str(self.installer), "/S", "--target", str(self.target), "--start-menu", str(self.start_menu),
                               "--desktop", str(self.desktop), "--registry-file", str(self.hive), "--result", str(result),
                               "--log", str(log)], env=self.env(), timeout=1800, check=False)
        outcome = json.loads(result.read_text(encoding="utf-8")) if result.is_file() else None
        check(done.returncode == 0 and isinstance(outcome, dict) and outcome.get("ok"),
              f"installeur {tag} : code {done.returncode}, issue {outcome!r}")
        return outcome

    def start_launcher(self, tag: str) -> None:
        self.logs.mkdir(parents=True, exist_ok=True)
        out = open(self.logs / f"launcher-{tag}.out.txt", "w", encoding="utf-8")
        self.launcher = subprocess.Popen([str(self.python()), "-B", "-m", "jarvis", "launch"], cwd=str(self.work),
                                         env=self.env(), stdout=out, stderr=subprocess.STDOUT)
        self.wait("lanceur géré (launcher.json)", lambda: (self.home / "runtime" / "launcher.json").is_file(), 120)
        self.wait("Core prêt", self.health, 240, every=2)
        self.wait("Control Center", lambda: self.http("GET", self.ui_url + "/api/product/readiness")[0] == 200, 180, every=2)

    def stop_launcher(self) -> dict:
        status, payload = self.http("POST", self.ui_url + "/api/product/quit")
        check(status == 200, f"Quitter JARVIS : HTTP {status} {payload!r}")
        try:
            code = self.launcher.wait(timeout=120)
        except subprocess.TimeoutExpired as exc:
            raise SmokeFailure("le lanceur ne s'arrête pas 120 s après « Quitter JARVIS »") from exc
        self.launcher = None
        time.sleep(2)
        left = self.processes_under(self.target)
        check(code == 0 and not left, f"arrêt : code {code}, processus restants {left}")
        return {"launcher_exit": code}

    def owned_child(self, role: str) -> tuple[int, str]:
        """PID et heure de création d'un enfant du lanceur QUE CE SCRIPT A LANCÉ (descendant vérifié)."""

        check(self.launcher is not None and self.launcher.poll() is None, "aucun lanceur lancé par ce script")
        launcher_ref = process_tree.make_process_ref(self.launcher.pid)
        check(launcher_ref, "identité du lanceur illisible")
        pid = self.launcher_state()["roles"][role]["pid"]
        _launcher_pid, launcher_started = process_tree.parse_process_ref(launcher_ref)
        owned = dict(process_tree.verified_descendants(self.launcher.pid, launcher_started,
                                                       process_tree._windows_parent_table(),
                                                       process_tree._windows_start_time))
        check(pid in owned, f"{role} (PID {pid}) n'est pas un descendant vérifié du lanceur {self.launcher.pid}")
        return pid, owned[pid]

    def s_snapshot_before(self) -> dict:
        self.real_before = self.real_profile()
        return {"real_profile": self.real_before}

    def s_seed(self) -> dict:
        self.seed_manifest = SEED.seed(self.home)
        (self.work / "seed-manifest.json").write_text(json.dumps(self.seed_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"state_from": self.seed_manifest["state_from"], "scene_from": self.seed_manifest["scene_from"]}

    def s_install(self) -> dict:
        before = sha_tree(self.home)
        outcome = self.run_setup("install")
        check(sha_tree(self.home) == before, "l'installeur a modifié la maison semée")
        manifest, problems = PR.verify_package(PR.PackageLayout(self.target))
        check(manifest is not None and not problems, f"programme installé abîmé : {problems}")
        return {"mode": outcome.get("mode"), "package_sha256": manifest["package_sha256"], "home_untouched": True}

    def s_launch(self) -> dict:
        self.start_launcher("first")
        health = self.health()
        installation = health.get("installation") or {}
        runtimes = installation.get("runtimes") or {}
        check(installation.get("mode") == "installed", f"mode {installation.get('mode')!r}")
        check(runtimes.get("status") == "ok", f"runtimes privés {runtimes!r} (PATH réduit à Windows)")
        status, edition = self.http("GET", self.core_url + "/v1/boards/edition", token=True)
        check(status == 200 and edition.get("edition") == "presentation", f"édition {status} {edition!r}")
        status, boards = self.http("GET", self.core_url + "/v1/boards?include_archived=true", token=True)
        ids = sorted(b["board_id"] for b in boards.get("boards", [])) if status == 200 else []
        check({"default", "board_seed_rapport", "board_seed_ancien"} <= set(ids), f"Boards du profil semé : {ids}")
        report = SEED.verify(self.home, self.seed_manifest)
        check(report["green"], f"profil après démarrage : {report['problems']}")
        state = self.launcher_state()
        check(process_tree.parse_process_ref(state.get("process_ref", "")) is not None, f"launcher.json sans identité : {state}")
        return {"health_status": health.get("status"), "runtimes": runtimes.get("status"), "boards": ids,
                "databases": report["databases"], "process_ref": True}

    def crash(self, role: str) -> dict:
        pid, started = self.owned_child(role)
        exits_before = sum(1 for e in self.launcher_events() if e.get("kind") == "child_exited")
        check(process_tree.kill_tree(pid, started), f"{role} (PID {pid}) toujours vivant après l'arrêt")
        self.wait(f"{role} relancé", lambda: (self.role_pid(role) not in (None, pid)
                                              and sum(1 for e in self.launcher_events() if e.get("kind") == "child_exited")
                                              > exits_before), 120)
        self.wait("Core prêt après la relance", self.health, 240, every=2)
        self.wait("Control Center après la relance",
                  lambda: self.http("GET", self.ui_url + "/api/product/readiness")[0] == 200, 180, every=2)
        report = SEED.verify(self.home, self.seed_manifest)
        check(report["green"], f"profil après la relance de {role} : {report['problems']}")
        return {"killed_pid": pid, "new_pid": self.role_pid(role), "profile_intact": True}

    def s_support_bundle(self) -> dict:
        with open(self.home / "runtime" / "errors.jsonl", "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": "smoke", "kind": "smoke.fake_secret", "level": "error",
                                     "message": f"fake {FAKE_SECRET} at {self.home}", "data": {}}) + "\n")
        done = subprocess.run([str(self.python()), "-B", "-m", "jarvis", "support-bundle"], env=self.env(),
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, check=False)
        check(done.returncode == 0, f"support-bundle : code {done.returncode} {done.stderr[-800:]}")
        bundles = sorted((self.home / "runtime" / "support").glob("jarvis-support-*.zip"))
        check(len(bundles) == 1, f"paquets de support : {bundles}")
        with zipfile.ZipFile(bundles[0]) as bundle:
            text = "\n".join(bundle.read(name).decode("utf-8", errors="replace") for name in bundle.namelist())
            names = bundle.namelist()
        user = os.environ.get("USERNAME", "")
        for leak in (FAKE_SECRET, str(self.home), str(self.local)) + ((user,) if len(user) >= 3 else ()):
            check(leak not in text, f"le paquet de support contient {leak[:12]}…")
        check("%LOCALAPPDATA%" in text, "chemin du profil non remplacé par %LOCALAPPDATA%")
        return {"files": names, "bytes": bundles[0].stat().st_size}

    def s_quit(self) -> dict:
        result = self.stop_launcher()
        manifest, problems = PR.verify_package(PR.PackageLayout(self.target))
        check(manifest is not None and not problems, f"le programme a été écrit pendant l'exécution : {problems}")
        return {**result, "program_intact": True}

    def s_repair(self) -> dict:
        before = sha_tree(self.home)
        outcome = self.run_setup("repair")
        check(outcome.get("mode") == "repair", f"mode {outcome.get('mode')!r}")
        check(sha_tree(self.home) == before, "la réparation a modifié la maison")
        return {"mode": "repair", "home_untouched": True}

    def s_kill_launcher(self) -> dict:
        self.start_launcher("second")
        report = SEED.verify(self.home, self.seed_manifest)
        check(report["green"], f"profil au second lancement : {report['problems']}")
        children = [p for p in self.processes_under(self.target) if not p.startswith(f"{self.launcher.pid} ")]
        self.launcher.kill()  # notre propre Popen : ce processus exact, rien d'autre
        self.launcher.wait(timeout=60)
        self.launcher = None
        self.wait("plus aucun processus du programme (Job Objects)", lambda: not self.processes_under(self.target), 60, every=2)
        return {"children_before": children, "left": []}

    def s_uninstall(self) -> dict:
        before = sha_tree(self.home)
        done = subprocess.run([str(self.python()), "-B", "-m", "jarvis.product_setup", "uninstall", "--quiet",
                               "--target", str(self.target), "--registry-file", str(self.hive), "--start-menu",
                               str(self.start_menu), "--desktop", str(self.desktop)], env=self.env(), capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=600, check=False)
        check(done.returncode == 0, f"désinstallation : code {done.returncode} {done.stderr[-800:]}")
        self.wait("programme retiré", lambda: not self.target.exists() and not self.hive.exists(), 180)
        skip_logs = lambda relative: relative.startswith("runtime/logs/")  # noqa: E731 - le journal du lanceur peut finir d'écrire
        check(sha_tree(self.home, skip=skip_logs) == {k: v for k, v in before.items() if not skip_logs(k)},
              "la désinstallation a modifié la maison")
        check(SEED.verify(self.home, self.seed_manifest)["green"], "profil abîmé après la désinstallation")
        return {"home_kept": True}

    def s_snapshot_after(self) -> dict:
        after = self.real_profile()
        check(after == self.real_before, f"le vrai profil a changé : avant {self.real_before}, après {after}")
        return {"real_profile_unchanged": True}

    def plan(self) -> list[tuple[str, Callable[[], dict | None]]]:
        return [("snapshot_before", self.s_snapshot_before), ("seed", self.s_seed), ("install", self.s_install),
                ("launch", self.s_launch), ("crash_core", lambda: self.crash("core")), ("crash_ui", lambda: self.crash("ui")),
                ("support_bundle", self.s_support_bundle), ("quit", self.s_quit), ("repair", self.s_repair),
                ("kill_launcher", self.s_kill_launcher), ("uninstall", self.s_uninstall),
                ("snapshot_after", self.s_snapshot_after)]

    # Phases : la même suite découpée pour une machine où une commande ne peut pas durer plus de quelques minutes ;
    # l'état (instantané du vrai profil, manifeste du profil semé, étapes) passe d'une phase à l'autre par
    # `smoke-state.json` dans le dossier de travail. Chaque phase laisse JARVIS arrêté.
    PHASES = {"install": ("snapshot_before", "seed", "install"),
              "run": ("launch", "crash_core", "crash_ui", "support_bundle", "quit"),
              "repair": ("repair", "kill_launcher"),
              "finish": ("uninstall", "snapshot_after")}
    BLOCKING = ("seed", "install", "launch")

    def state_path(self) -> Path:
        return self.work / "smoke-state.json"

    def load_state(self) -> None:
        state = json.loads(self.state_path().read_text(encoding="utf-8"))
        self.real_before, self.seed_manifest, self.steps = state["real_before"], state["seed_manifest"], state["steps"]

    def save_state(self) -> None:
        self.state_path().write_text(json.dumps({"real_before": getattr(self, "real_before", None),
                                                 "seed_manifest": self.seed_manifest, "steps": self.steps},
                                                indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def run(self, names: tuple[str, ...] | None = None) -> bool:
        plan = self.plan()
        wanted = [(name, action) for name, action in plan if names is None or name in names]
        blocked = any(not row["ok"] and row["step"] in self.BLOCKING for row in self.steps)
        try:
            for name, action in wanted:
                if blocked:
                    break  # the following steps need what failed; they are reported as not run
                if not self.step(name, action) and name in self.BLOCKING:
                    blocked = True
        finally:
            if self.launcher is not None and self.launcher.poll() is None:
                self.launcher.kill()  # our own Popen only; its Job Objects take its children
                self.launcher.wait(timeout=60)
        done = {row["step"] for row in self.steps}
        for name, _action in wanted:
            if name not in done:
                self.steps.append({"step": name, "ok": False, "failure": "non lancée (une étape préalable a échoué)"})
        return all(row["ok"] for row in self.steps)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--installer", required=True)
    parser.add_argument("--work", required=True)
    parser.add_argument("--report")
    parser.add_argument("--ports", type=int, default=43653, help="port de Core ; UI +1, bac à sable Remotion +2, visage +3")
    parser.add_argument("--phase", choices=("all", *Smoke.PHASES), default="all",
                        help="une partie de l'essai (install, run, repair, finish, dans cet ordre) ; all = tout")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if os.name != "nt":
        print("[smoke] ÉCHEC : l'essai du paquet Windows ne tourne que sous Windows", file=sys.stderr)
        return 2
    work = Path(args.work).resolve()
    first = args.phase in ("all", "install")
    if first and work.exists() and any(work.iterdir()):
        print(f"[smoke] ÉCHEC : {work} n'est pas vide", file=sys.stderr)
        return 2
    if work == ROOT or ROOT in work.parents:
        print("[smoke] ÉCHEC : le dossier de travail ne peut pas être dans le dépôt", file=sys.stderr)
        return 2
    smoke = Smoke(Path(args.installer).resolve(), work, args.ports)
    if not first:
        if not smoke.state_path().is_file():
            print(f"[smoke] ÉCHEC : {smoke.state_path()} absent : lancez d'abord la phase install", file=sys.stderr)
            return 2
        smoke.load_state()
    work.mkdir(parents=True, exist_ok=True)
    green = smoke.run(None if args.phase == "all" else Smoke.PHASES[args.phase])
    smoke.save_state()
    report = {"schema": SCHEMA, "schema_version": 1, "green": green, "installer": str(smoke.installer),
              "installer_sha256": hashlib.sha256(smoke.installer.read_bytes()).hexdigest(),
              "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "steps": smoke.steps}
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[smoke] {'VERT' if green else 'ROUGE'} : " + ", ".join(f"{r['step']}={'ok' if r['ok'] else 'KO'}" for r in smoke.steps))
    return 0 if green else 1


if __name__ == "__main__":
    raise SystemExit(main())
