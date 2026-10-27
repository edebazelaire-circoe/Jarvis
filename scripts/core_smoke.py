r"""Smoke Core + Control Center d'un checkout de développement, sur toute plateforme (Slice 08 V1.2).

Sert au job CI macOS (`.github/workflows/ci.yml`, `docs/macos-portability.md`) et se lance tel quel sous Windows :

    python scripts/core_smoke.py --work <dossier vide> --core-port 63653 --report <rapport.json>

- Bac à sable complet : `JARVIS_DATA_ROOT`, `JARVIS_RUNTIME_DIR`, `HOME`/`USERPROFILE`, `TEMP` sous `--work` ; ports
  dédiés (`--core-port`, +1 Control Center, +2 bac à sable Remotion, +3 visualiseur désactivé) ; aucune clé de
  fournisseur transmise (environnement en liste blanche) ; navigateur, voix et visualiseur coupés.
- Adresse de Core : `--core-host` (défaut `127.0.0.1`). Le défaut du produit, `127.77.0.1`, n'existe pas sur la boucle
  locale d'un Mac sans alias `lo0` : voir `docs/macos-portability.md` › *Boucle locale*.
- Étapes : Core répond `/v1/health` avec son jeton, le Control Center sert sa page, puis arrêt de NOS deux processus
  seulement, par leur référence `pid:heure de création` (`jarvis.adapters.process_tree.kill_tree`, jamais `taskkill /T`).
- Chaque étape a un délai ; un échec est nommé dans le rapport et sur stderr. Code 0 = tout vert, 1 = échec.

Ne JAMAIS pointer `--work` vers un dossier de données réel : le script refuse un dossier non vide.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from jarvis.adapters import process_tree  # noqa: E402

#: Variables du système transmises aux enfants ; tout le reste (clés de fournisseurs comprises) est retiré.
KEEP_ENV = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "PROGRAMDATA", "PROGRAMFILES",
            "PROGRAMFILES(X86)", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "OS", "LANG", "LC_ALL", "TZ",
            "USER", "LOGNAME", "SHELL", "TMPDIR")


def sandbox_env(work: Path, core_host: str, core_port: int) -> dict[str, str]:
    env = {key: os.environ[key] for key in KEEP_ENV if key in os.environ}
    home, tmp = work / "home", work / "tmp"
    for folder in (home, tmp):
        folder.mkdir(parents=True, exist_ok=True)
    env.update({"HOME": str(home), "USERPROFILE": str(home), "APPDATA": str(home / "AppData" / "Roaming"),
                "LOCALAPPDATA": str(home / "AppData" / "Local"), "TEMP": str(tmp), "TMP": str(tmp),
                "JARVIS_DATA_ROOT": str(work / "data"), "JARVIS_RUNTIME_DIR": str(work / "runtime"),
                "JARVIS_CORE_HOST": core_host, "JARVIS_CORE_PORT": str(core_port),
                "JARVIS_UI_PORT": str(core_port + 1), "JARVIS_REMOTION_SANDBOX_PORT": str(core_port + 2),
                "JARVIS_VISUALIZER_PORT": str(core_port + 3), "JARVIS_VISUALIZER_ENABLED": "0",
                "JARVIS_OPEN_BROWSER": "0", "JARVIS_LAUNCH_VOICE": "0", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"})
    return env


def http_get(url: str, token: str | None = None, timeout: float = 10.0) -> tuple[int | None, bytes]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - loopback only
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()[:500]
    except (urllib.error.URLError, OSError) as exc:
        return None, f"{type(exc).__name__}: {exc}".encode()


class CoreSmoke:
    def __init__(self, args: argparse.Namespace) -> None:
        self.work = args.work.resolve()
        self.python = args.python
        self.timeout = args.timeout
        self.core_url = f"http://{args.core_host}:{args.core_port}"
        self.ui_url = f"http://127.0.0.1:{args.core_port + 1}/"
        self.env = sandbox_env(self.work, args.core_host, args.core_port)
        self.children: dict[str, tuple[subprocess.Popen, str]] = {}
        self.steps: list[dict] = []

    def spawn(self, role: str, *args: str) -> None:
        logs = self.work / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        with open(logs / f"{role}.log", "ab") as log:
            flags = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if os.name == "nt" else 0
            proc = subprocess.Popen([self.python, "-B", "-m", "jarvis", *args], cwd=str(REPO), env=self.env,
                                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                    creationflags=flags, start_new_session=os.name != "nt")
        self.children[role] = (proc, process_tree.make_process_ref(proc.pid))
        print(f"[core-smoke] {role} started (pid {proc.pid})", flush=True)

    def wait_for(self, what: str, role: str, probe) -> object:
        started = time.monotonic()
        last: object = None
        while time.monotonic() - started < self.timeout:
            proc = self.children[role][0]
            if proc.poll() is not None:
                raise RuntimeError(f"{what}: {role} exited with code {proc.returncode} (see logs/{role}.log)")
            ok, last = probe()
            if ok:
                return last
            time.sleep(1.0)
        raise RuntimeError(f"{what}: no answer in {self.timeout:.0f} s (last: {last!r})"[:500])

    def step(self, name: str, action) -> bool:
        started = time.monotonic()
        row: dict = {"step": name}
        try:
            row.update(action() or {})
            row["ok"] = True
        except Exception as exc:  # noqa: BLE001 - every failure is this step's verdict, named in the report
            row.update({"ok": False, "failure": f"{type(exc).__name__}: {exc}"[:800]})
        row["seconds"] = round(time.monotonic() - started, 1)
        self.steps.append(row)
        print(f"[core-smoke] {name}: {'OK' if row['ok'] else 'FAILED ' + row['failure']} ({row['seconds']} s)",
              file=sys.stdout if row["ok"] else sys.stderr, flush=True)
        return row["ok"]

    def core_health(self) -> dict:
        self.spawn("core", "core")
        token_file = self.work / "runtime" / "core.token"

        def probe():
            if not token_file.is_file():
                return False, "core.token not written yet"
            status, body = http_get(self.core_url + "/v1/health", token_file.read_text(encoding="utf-8").strip())
            return status == 200, (status, body[:200])

        status, body = self.wait_for("Core /v1/health", "core", probe)
        health = json.loads(http_get(self.core_url + "/v1/health",
                                     token_file.read_text(encoding="utf-8").strip())[1] or b"{}")
        return {"status": health.get("status"), "installation": health.get("installation")}

    def control_center(self) -> dict:
        self.spawn("control-center", "control-center")

        def probe():
            status, body = http_get(self.ui_url)
            return status == 200 and b"<html" in body.lower()[:4000], status

        return {"http_status": self.wait_for("Control Center page", "control-center", probe)}

    def stop(self) -> dict:
        stopped = {}
        for role, (proc, ref) in reversed(list(self.children.items())):
            parsed = process_tree.parse_process_ref(ref)
            if parsed is not None:
                process_tree.kill_tree(parsed[0], started=parsed[1])
            elif proc.poll() is None:
                proc.kill()  # identité illisible : seulement notre poignée directe, jamais un arbre deviné
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=15)
            stopped[role] = proc.returncode
        alive = [role for role, (proc, _ref) in self.children.items() if proc.poll() is None]
        if alive:
            raise RuntimeError(f"still alive after stop: {alive}")
        return {"exit_codes": stopped}

    def run(self) -> dict:
        try:
            if self.step("core health", self.core_health):
                self.step("control center page", self.control_center)
        finally:
            self.step("stop owned processes", self.stop)
        return {"generated_at": datetime.now(timezone.utc).isoformat(), "platform": sys.platform,
                "machine": platform.machine(), "python": platform.python_version(), "core_url": self.core_url,
                "ok": all(row["ok"] for row in self.steps), "steps": self.steps}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--core-host", default="127.0.0.1")
    parser.add_argument("--core-port", type=int, default=63653)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.work.exists() and any(args.work.iterdir()):
        print(f"[core-smoke] refused: {args.work} is not empty (never a real data folder)", file=sys.stderr)
        return 2
    args.work.mkdir(parents=True, exist_ok=True)
    report = CoreSmoke(args).run()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[core-smoke] {'OK' if report['ok'] else 'FAILED'}", flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
