"""Harnais RÉEL du Studio Remotion optionnel (Slice 11 de jarvis-remotion-presentation-integration ; `docs/remotion-studio.md` §10).

Ce qui est RÉEL : un Core isolé (`python -m jarvis core`, racine de données PRIVÉE, hôte/port de boucle locale libres, jamais le
JARVIS vivant), la vraie installation npm de la capacité Remotion, la vraie bibliothèque de prefabs, le vrai `remotion studio`
(Node, webpack, rechargement à chaud) lancé par le runner livré, un vrai Chrome sans tête piloté par DevTools, les vraies routes de
Core. Ce qui est SIMULÉ : rien (le « Control Center » de la vérification d'interface est un vrai Control Center isolé, voir
`--ui`).

    python scripts/remotion_studio_harness.py --work-dir C:/Users/<moi>/AppData/Local/Temp/s11 \\
        --evidence tasks/jarvis-remotion-presentation-integration/slices/11-remotion-studio-process-ui/evidence/real-studio.json

Chaque phase enregistre des vérifications nommées (`checks`) ; le verdict est PASSED seulement si toutes passent.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis.domain.remotion_source import Composition  # noqa: E402
from jarvis.domain.remotion_source import build_candidate  # noqa: E402
from jarvis.adapters.remotion_compiler import shipped_engine_pin  # noqa: E402
from jarvis.adapters.node_capability_runner import _remove_tree  # noqa: E402

CHROME = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe"
PYTHON = Path(sys.executable)
SCENE_A = "user.studio-demo-a"
SCENE_B = "user.studio-demo-b"
CHECKS: dict[str, dict] = {}
NOTES: dict[str, object] = {}


def check(name: str, ok: bool, detail: object = "") -> bool:
    CHECKS[name] = {"ok": bool(ok), "detail": detail if isinstance(detail, (int, float, str, list, dict)) or detail is None else str(detail)}
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)
    return bool(ok)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# ------------------------------------------------------------------ processus et réseau (Windows)

def node_processes(marker: str) -> list[dict]:
    """Processus `node.exe` dont la ligne de commande contient `marker` (chemin du dossier de travail)."""

    script = ("Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60).stdout.strip()
    if not out:
        return []
    rows = json.loads(out)
    rows = [rows] if isinstance(rows, dict) else rows
    wanted = marker.lower().replace("/", "\\")
    return [row for row in rows if wanted in (row.get("CommandLine") or "").lower().replace("/", "\\")]


def kill_leftovers(work: Path) -> int:
    """Chrome (profils jetables), Control Center et Core isolés restés sous le dossier de travail après une exécution interrompue."""

    script = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*' + $env:HARNESS_WORK + '*' -and $_.ProcessId -ne $PID } | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $_.ProcessId }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=90, env={**os.environ, "HARNESS_WORK": str(work).replace("/", "\\")}).stdout
    return len(out.split())


def listening(pids: set[int]) -> list[str]:
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30).stdout or ""
    rows = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == "LISTENING" and parts[4].isdigit() and int(parts[4]) in pids:
            rows.append(parts[1])
    return rows


def port_of(view: dict) -> int:
    return view.get("port") or 0


def lan_address() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 9))
            address = sock.getsockname()[0]
        return None if address.startswith("127.") else address
    except OSError:
        return None


def alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30).stdout or ""
    return str(pid) in out


# ------------------------------------------------------------------ Core isolé

#: Lance Core exactement comme `python -m jarvis core`, mais l'arrêt PROPRE (l'annulation que Ctrl+C déclenche dans un terminal : le
#: bloc `finally` de `_run_core_v2`, donc `core.stop()`) se demande par un fichier témoin, ce qu'un processus sans console ne sait pas recevoir.
CORE_WRAPPER = r"""
import asyncio, os, pathlib, sys
sys.path.insert(0, os.environ["HARNESS_ROOT"])
from jarvis.app import _run_core_v2

async def main():
    task = asyncio.create_task(_run_core_v2())
    flag = pathlib.Path(os.environ["HARNESS_STOP_FLAG"])
    while not task.done():
        if flag.exists():
            task.cancel()
            break
        await asyncio.sleep(0.2)
    try:
        await task
    except asyncio.CancelledError:
        pass

asyncio.run(main())
"""


class IsolatedCore:
    def __init__(self, work: Path, *, idle_s: float | None = None, studio_port: int | None = None) -> None:
        self.work = work
        self.port = free_port()
        self.host = "127.77.0.9"
        self.token_file = work / "core.token"
        self.env = {**os.environ, "JARVIS_DATA_ROOT": str(work / "root"), "JARVIS_RUNTIME_DIR": str(work / "runtime"),
                    "JARVIS_CORE_HOST": self.host, "JARVIS_CORE_PORT": str(self.port), "JARVIS_CORE_TOKEN_FILE": str(self.token_file),
                    "JARVIS_ISOLATED_HARNESS": "1", "HARNESS_ROOT": str(ROOT), "HARNESS_STOP_FLAG": str(work / "stop.flag")}
        for secret in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            self.env.pop(secret, None)
        if idle_s is not None:
            self.env["JARVIS_REMOTION_STUDIO_IDLE_S"] = str(idle_s)
        if studio_port is not None:
            self.env["JARVIS_REMOTION_STUDIO_PORT"] = str(studio_port)
        self.proc: subprocess.Popen | None = None
        self.token = ""

    @property
    def base(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        (self.work / "runtime").mkdir(parents=True, exist_ok=True)
        log = open(self.work / "core.log", "ab")
        (self.work / "stop.flag").unlink(missing_ok=True)
        self.proc = subprocess.Popen([str(PYTHON), "-c", CORE_WRAPPER], cwd=str(ROOT), env=self.env, stdout=log, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("isolated Core exited: " + (self.work / "core.log").read_text(encoding="utf-8", errors="replace")[-800:])
            try:
                self.token = self.token_file.read_text(encoding="utf-8").strip()
                if self.token and self.call("GET", "/v1/local-capabilities")[0] == 200:
                    return
            except (OSError, urllib.error.URLError, ConnectionError):
                pass
            time.sleep(0.5)
        raise RuntimeError("isolated Core did not become ready")

    def call(self, method: str, path: str, body: object | None = None, timeout: float = 200) -> tuple[int, dict]:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method,
                                         headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=timeout) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"null")

    def hard_kill(self) -> None:
        if self.proc and self.proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True, timeout=30)
            self.proc.wait(timeout=30)

    def stop(self) -> bool:
        """Arrêt PROPRE (annulation de la tâche principale, comme Ctrl+C) ; rend vrai s'il a abouti sans être tué."""

        if not self.proc or self.proc.poll() is not None:
            return True
        (self.work / "stop.flag").write_text("stop", encoding="utf-8")
        try:
            self.proc.wait(timeout=60)
            return True
        except subprocess.TimeoutExpired:
            self.hard_kill()
            return False


# ------------------------------------------------------------------ scènes

def scene_files(label: str) -> dict[str, str | bytes]:
    return {
        "src/Scene.tsx": (
            'import React from "react";\n'
            'import {AbsoluteFill, useCurrentFrame, interpolate} from "remotion";\n'
            'import {Title} from "./lib/Title";\n'
            "export default function Scene(props: {title: string}) {\n"
            "  const frame = useCurrentFrame();\n"
            '  const o = interpolate(frame, [0, 10], [0, 1], {extrapolateRight: "clamp"});\n'
            f'  return <AbsoluteFill style={{{{background: "#102030", justifyContent: "center", alignItems: "center", opacity: o}}}}><Title text={{props.title + " {label}"}} /></AbsoluteFill>;\n'
            "}\n"),
        "src/lib/Title.tsx": 'import React from "react";\nexport const Title = ({text}: {text: string}) => <h1 id="demo-title" style={{color: "white", fontSize: 72}}>{text}</h1>;\n',
    }


def candidate(prefab_id: str, label: str) -> dict:
    return build_candidate(prefab_id=prefab_id, title=f"Scène {label}", composition=Composition("Scene", 1280, 720, 30, 90),
                           engine=shipped_engine_pin(), files=scene_files(label),
                           props={"type": "object", "properties": {"title": {"type": "string", "default": "Bonjour", "max_length": 80}}},
                           sample={"props": {"title": "Bonjour"}, "data": {}})


def publish(core: IsolatedCore, prefab_id: str, label: str) -> int:
    status, body = core.call("POST", "/v1/prefabs", {"actor": "user", "candidate": candidate(prefab_id, label)})
    if status != 201:
        raise RuntimeError(f"publish failed: {status} {body}")
    return int(body["version"])


# ------------------------------------------------------------------ Chrome (DevTools)

class Chrome:
    def __init__(self, work: Path) -> None:
        self.port = free_port()
        self.profile = work / f"chrome-profile-{self.port}"
        self.proc: subprocess.Popen | None = None
        self.session: aiohttp.ClientSession | None = None
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self._id = 0
        self.events: list[dict] = []

    async def start(self, url: str = "about:blank") -> None:
        self.proc = subprocess.Popen([str(CHROME), "--headless=new", f"--remote-debugging-port={self.port}", f"--user-data-dir={self.profile}",
                                      "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--window-size=1400,900",
                                      "--disable-background-networking", "--js-flags=--max-old-space-size=512", url],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.session = aiohttp.ClientSession()
        for _ in range(60):
            try:
                async with self.session.get(f"http://127.0.0.1:{self.port}/json") as response:
                    targets = [t for t in await response.json() if t.get("type") == "page"]
                if targets:
                    self.ws = await self.session.ws_connect(targets[0]["webSocketDebuggerUrl"], max_msg_size=64 * 1024 * 1024)
                    break
            except aiohttp.ClientError:
                pass
            await asyncio.sleep(0.5)
        if self.ws is None:
            raise RuntimeError("Chrome DevTools did not answer")
        await self.send("Page.enable")
        await self.send("Runtime.enable")

    async def send(self, method: str, params: dict | None = None) -> dict:
        assert self.ws is not None
        self._id += 1
        mine = self._id
        await self.ws.send_json({"id": mine, "method": method, "params": params or {}})
        while True:
            message = await asyncio.wait_for(self.ws.receive_json(), timeout=60)
            if "method" in message and len(self.events) < 2000:
                self.events.append(message)
            if message.get("id") == mine:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})

    async def evaluate(self, expression: str, gesture: bool = False):
        result = await self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True, "userGesture": gesture})
        if result.get("exceptionDetails"):
            raise RuntimeError(str(result["exceptionDetails"])[:300])
        return result["result"].get("value")

    async def wait_for(self, expression: str, timeout: float = 60.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                value = await self.evaluate(expression)
            except RuntimeError:
                value = None
            if value:
                return value
            await asyncio.sleep(0.25)
        return None

    async def shot(self, path: Path) -> None:
        result = await self.send("Page.captureScreenshot", {"format": "png"})
        path.write_bytes(base64.b64decode(result["data"]))

    async def close(self) -> None:
        if self.ws is not None:
            await self.ws.close()
        if self.session is not None:
            await self.session.close()
        if self.proc is not None:
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True, timeout=30)
        shutil.rmtree(self.profile, ignore_errors=True)


# ------------------------------------------------------------------ phases

def studio(core: IsolatedCore) -> dict:
    return core.call("GET", "/v1/local-capabilities/remotion/studio")[1]["studio"]


def wait_status(core: IsolatedCore, wanted: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    view = studio(core)
    while time.monotonic() < deadline and view["status"] != wanted:
        time.sleep(1)
        view = studio(core)
    return view


async def main_async(args) -> int:
    work = Path(args.work_dir).resolve()
    shots = Path(args.evidence).resolve().parent / "screens"
    shots.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(work.anchor or "C:\\").free / 1e9
    NOTES.update(started=datetime.now(timezone.utc).isoformat(timespec="seconds"), platform=platform.platform(), free_gb=round(free_gb, 1),
                 python=platform.python_version(), node=subprocess.run(["node", "-v"], capture_output=True, text=True).stdout.strip(),
                 chrome=subprocess.run(["powershell", "-NoProfile", "-Command", f"(Get-Item '{CHROME}').VersionInfo.ProductVersion"],
                                       capture_output=True, text=True).stdout.strip(),
                 head=subprocess.run(["git", "rev-parse", "--short=8", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip(),
                 dirty=bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=ROOT).stdout.strip()))
    if free_gb < 3:
        print("not enough free disk", free_gb)
        return 2
    if work.exists():
        kill_leftovers(work)
        time.sleep(2)
        _remove_tree(work)
    work.mkdir(parents=True)
    studio_dir = work / "root" / "local_capabilities" / "remotion" / "runtime" / "studio"
    marker = str(studio_dir)
    core = IsolatedCore(work, idle_s=60)
    chrome: Chrome | None = None
    try:
        core.start()
        NOTES["core"] = f"{core.host}:{core.port} (isolated), data root {work / 'root'}"
        # ---- 0. rien ne démarre seul
        status, body = core.call("GET", "/v1/local-capabilities/remotion/studio")
        check("0.core_start_launches_no_studio", status == 200 and body["studio"]["status"] == "stopped" and not node_processes(marker))
        # ---- 1. installation réelle de la capacité (une fois)
        started = time.monotonic()
        status, body = core.call("POST", "/v1/local-capabilities/remotion/install")
        view = body["capability"]
        while view["status"] == "installing":
            time.sleep(2)
            view = core.call("GET", "/v1/local-capabilities/remotion")[1]["capability"]
        check("1.real_install_ready", view["status"] == "ready", {"status": view["status"], "seconds": round(time.monotonic() - started, 1),
                                                                 "error": view.get("last_error_code")})
        if view["status"] != "ready":
            return 1
        runtime = work / "root" / "local_capabilities" / "remotion" / "runtime"
        # ---- 2. refus sans scène, sans lancement
        status, body = core.call("POST", "/v1/local-capabilities/remotion/studio/open", {"prefab_id": SCENE_A, "version": 1})
        check("2.unknown_scene_refused_nothing_started", status == 404 and body["error"]["code"] == "remotion_studio_source_unavailable" and not node_processes(marker), body["error"]["code"])
        # ---- 3. publication de deux scènes, ouverture
        va = publish(core, SCENE_A, "A1")
        vb = publish(core, SCENE_B, "B1")
        started = time.monotonic()
        status, body = core.call("POST", "/v1/local-capabilities/remotion/studio/open", {"prefab_id": SCENE_A, "version": va})
        view = body["studio"]
        seconds = round(time.monotonic() - started, 1)
        check("3.open_ready", status == 200 and view["status"] == "ready" and view["url"], {"seconds": seconds, "url": view.get("url"), "error": view.get("last_error_code"),
                                                                                         "log": view.get("diagnostics")})
        if view["status"] != "ready":
            return 1
        url, port = view["url"], view["port"]
        procs = node_processes(marker)
        pids = {int(row["ProcessId"]) for row in procs}
        NOTES["studio_processes"] = [{"pid": int(r["ProcessId"]), "ppid": int(r["ParentProcessId"])} for r in procs]
        check("3.studio_processes_found", len(pids) >= 1, sorted(pids))
        # ---- 4. loopback seulement
        binds = listening(pids)
        check("4.listens_on_loopback_only", binds and all(b.startswith(("127.0.0.1:", "[::1]:")) for b in binds), binds)
        lan = lan_address()
        refused = None
        if lan:
            try:
                socket.create_connection((lan, port), timeout=3).close()
                refused = False
            except OSError:
                refused = True
        check("4.lan_address_refuses_the_studio_port", lan is None or refused is True, {"lan": lan, "refused": refused})
        request = urllib.request.Request(url)
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=20) as response:
            headers = {k.lower(): v for k, v in response.getheaders()}
            page = response.read(4096).decode("utf-8", "replace")
        check("4.csp_on_studio_responses", "default-src 'self'" in headers.get("content-security-policy", "") and "Remotion Studio" in page)
        # ---- 5. vrai Chrome : la scène s'affiche, rechargement à chaud sans rechargement de page
        chrome = Chrome(work)
        await chrome.start()
        await chrome.send("Page.navigate", {"url": url})
        shown = await chrome.wait_for("document.getElementById('demo-title') && document.getElementById('demo-title').textContent", 90)
        check("5.chrome_shows_scene_A1", shown == "Bonjour A1", shown)
        await chrome.shot(shots / "studio-scene-a1.png")
        await chrome.evaluate("window.__marker='no-reload'; window.__violations=[]; document.addEventListener('securitypolicyviolation', e=>window.__violations.push(e.violatedDirective+' '+e.blockedURI)); true")
        va2 = publish(core, SCENE_A, "A2")
        t0 = time.monotonic()
        status, body = core.call("POST", "/v1/local-capabilities/remotion/studio/sync", {"prefab_id": SCENE_A, "version": va2})
        sync_s = round(time.monotonic() - t0, 2)
        changed = await chrome.wait_for("document.getElementById('demo-title') && document.getElementById('demo-title').textContent === 'Bonjour A2' && 'yes'", 60)
        hmr_s = round(time.monotonic() - t0, 2)
        no_reload = await chrome.evaluate("window.__marker")
        check("5.hmr_updates_open_page_without_reload", changed == "yes" and no_reload == "no-reload", {"sync_call_s": sync_s, "visible_after_s": hmr_s})
        await chrome.shot(shots / "studio-scene-a2-after-hmr.png")
        check("5.sync_view_counts_the_refresh", status == 200 and body.get("studio", {}).get("syncs") == 1 and body["studio"]["pin"]["version"] == va2, {"status": status, "body": body if status != 200 else "ok"})
        # CSP : la scène (tournant dans l'onglet) ne peut pas atteindre un autre domaine
        blocked = await chrome.evaluate("""(async()=>{try{await fetch('https://example.com/x',{mode:'no-cors'});return 'reached'}catch(e){return 'blocked'}})()""")
        await chrome.evaluate("(()=>{const i=new Image();i.src='http://192.0.2.1/p.png';document.body.appendChild(i);return true})()")
        await asyncio.sleep(1)
        violations = await chrome.evaluate("window.__violations")
        check("5.page_csp_blocks_foreign_fetch_and_image", blocked == "blocked" and any("img-src" in v for v in violations), {"fetch": blocked, "violations": violations[:4]})
        # ---- 6. un hôte : réouverture = réutilisation, autre scène = changement sur place
        status, body = core.call("POST", "/v1/local-capabilities/remotion/studio/open", {"prefab_id": SCENE_A, "version": va2})
        same_host = body.get("studio", {}).get("reused") is True and body["studio"]["port"] == port
        if "studio" not in body:
            NOTES["reopen_error"] = body
        status, body = core.call("POST", "/v1/local-capabilities/remotion/studio/open", {"prefab_id": SCENE_B, "version": vb})
        procs_after = {int(r["ProcessId"]) for r in node_processes(marker)}
        switched = await chrome.wait_for("document.getElementById('demo-title') && document.getElementById('demo-title').textContent === 'Bonjour B1' && 'yes'", 60)
        check("6.one_studio_per_profile_scene_switch_in_place", same_host and body["studio"]["port"] == port and procs_after == pids and switched == "yes",
              {"reused": same_host, "pids_unchanged": procs_after == pids, "shows": switched})
        # ---- 7. copie de travail en lecture seule, modifications mises de côté
        work_scene = studio_dir / "work" / "src" / "Scene.tsx"
        check("7.work_copy_is_read_only", not os.access(work_scene, os.W_OK))
        os.chmod(work_scene, 0o666)
        original = work_scene.read_text(encoding="utf-8")
        work_scene.write_text(original + "\n// edit made outside Jarvis\n", encoding="utf-8")
        view = studio(core)
        check("7.outside_edit_is_reported", view["work_copy"]["modified_files"] == ["src/Scene.tsx"], view["work_copy"])
        status, body = core.call("POST", "/v1/local-capabilities/remotion/studio/sync", {"prefab_id": SCENE_B, "version": vb})
        saved = list((studio_dir / "edits").glob("*/src/Scene.tsx"))
        check("7.outside_edit_saved_aside_before_refresh", len(saved) == 1 and "edit made outside" in saved[0].read_text(encoding="utf-8")
              and "edit made outside" not in work_scene.read_text(encoding="utf-8"))
        status, lib = core.call("GET", f"/v1/prefabs/{SCENE_B}/{vb}?include_source=1")
        library_clean = "edit made outside" not in json.dumps(lib)
        check("7.prefab_library_never_receives_the_studio_copy", status == 200 and library_clean)
        # ---- 8. mort, redémarrage, orphelins
        old_pids = set(pids)
        status, body = core.call("POST", "/v1/local-capabilities/remotion/studio/restart")
        new_procs = {int(r["ProcessId"]) for r in node_processes(marker)}
        gone = all(not alive(p) for p in old_pids)
        check("8.restart_replaces_the_whole_tree", body["studio"]["status"] == "ready" and body["studio"]["restarts"] == 1 and gone and new_procs and new_procs.isdisjoint(old_pids),
              {"old_gone": gone, "new": sorted(new_procs)})
        view = body["studio"]
        victim = max(new_procs)
        subprocess.run(["taskkill", "/PID", str(victim), "/F"], capture_output=True, timeout=30)
        time.sleep(1)
        view = studio(core)
        check("8.external_kill_is_seen_as_process_exited", view["status"] == "failed" and view["last_error_code"] == "remotion_studio_process_exited", view["last_error_code"])
        leftovers = [int(r["ProcessId"]) for r in node_processes(marker)]
        subprocess.run(["taskkill", "/PID", str(min(new_procs)), "/T", "/F"], capture_output=True, timeout=30)
        status, body = core.call("POST", "/v1/local-capabilities/remotion/studio/open", {"prefab_id": SCENE_A, "version": va2})
        check("8.open_recovers_from_failed", body["studio"]["status"] == "ready", body["studio"]["status"])
        url = body["studio"]["url"]
        # ---- 9. fermeture : plus de processus, plus de port
        status, body = core.call("POST", "/v1/local-capabilities/remotion/studio/close")
        time.sleep(1)
        check("9.close_leaves_no_node_process_and_no_port", body["studio"]["status"] == "stopped" and not node_processes(marker) and not listening({int(r["ProcessId"]) for r in procs}),
              {"stop_reason": body["studio"]["stop_reason"]})
        # ---- 10. interface réelle : un vrai Control Center isolé, la carte « Remotion », un vrai Chrome
        ui_port = free_port()
        cc_env = {**core.env, "JARVIS_UI_PORT": str(ui_port), "JARVIS_VISUALIZER_ENABLED": "0"}
        cc = subprocess.Popen([str(PYTHON), "-m", "jarvis", "control-center"], cwd=str(ROOT), env=cc_env, stdout=open(work / "cc.log", "ab"),
                              stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                try:
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    if opener.open(f"http://127.0.0.1:{ui_port}/api/status", timeout=3).status == 200:
                        break
                except OSError:
                    time.sleep(1)
            ui_chrome = Chrome(work)
            await ui_chrome.start(f"http://127.0.0.1:{ui_port}/")
            await ui_chrome.wait_for("document.getElementById('openMcpInspector')", 60)
            await ui_chrome.evaluate("document.getElementById('openMcpInspector').click(); document.getElementById('mcpViewPlugins').click(); true")
            first = await ui_chrome.wait_for("(()=>{const s=document.getElementById('rmsStatus');return s&&s.textContent==='Arrêté'?document.getElementById('rmsScene')?document.getElementById('rmsScene').options.length:0:0})()", 60)
            check("10.ui_card_shows_stopped_studio_and_the_published_scenes", first == 2, {"scene_options": first})
            await ui_chrome.shot(shots / "ui-card-stopped.png")
            check("10.ui_card_never_started_the_studio_by_itself", studio(core)["status"] == "stopped" and not node_processes(marker))
            await ui_chrome.evaluate("document.getElementById('rmsOpen').click(); true")
            samples = []
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                state = await ui_chrome.evaluate("({chip:document.getElementById('rmsStatus').textContent,act:(document.getElementById('rmsActivity')||{}).textContent||'',busy:document.getElementById('rmsBusy').textContent,open:document.getElementById('rmsOpen').disabled})")
                samples.append(state)
                if state["chip"] == "Prêt":
                    break
                await asyncio.sleep(1)
            seen_starting = [x for x in samples if x["chip"] == "Démarrage…"]
            check("10.ui_shows_progress_elapsed_time_and_deadline_while_starting",
                  any(re.search(r"Démarrage du Studio… \d+ s écoulées, 2 min au plus", x["act"]) for x in seen_starting) and all(x["open"] for x in seen_starting),
                  {"samples": len(samples), "first": seen_starting[:1], "last": samples[-1]})
            await ui_chrome.wait_for("document.getElementById('rmsOpenLink')", 30)
            await asyncio.sleep(2)
            link = await ui_chrome.evaluate("document.getElementById('rmsOpenLink').href")
            view = studio(core)
            check("10.ui_ready_state_links_the_loopback_studio", view["status"] == "ready" and link == view["url"], {"link": link})
            await ui_chrome.shot(shots / "ui-card-ready.png")
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://127.0.0.1:{ui_chrome.port}/json") as response:
                    targets = [t["url"] for t in await response.json() if t.get("type") == "page"]
            await ui_chrome.evaluate("document.getElementById('rmsOpenLink').click(); true", gesture=True)  # un vrai geste : le lien s'ouvre à part
            await asyncio.sleep(3)
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://127.0.0.1:{ui_chrome.port}/json") as response:
                    targets = [t["url"] for t in await response.json() if t.get("type") == "page"]
            check("10.ui_link_opens_the_studio_in_a_separate_window", any(t.startswith(view["url"]) for t in targets) and any(t.startswith(f"http://127.0.0.1:{ui_port}") for t in targets),
                  targets)
            await ui_chrome.evaluate("document.getElementById('rmsSync').click(); true")
            synced = await ui_chrome.wait_for("document.getElementById('rmsActivity') && /rafraîchie 1 fois/.test(document.getElementById('rmsActivity').textContent)", 40)
            check("10.ui_sync_button_refreshes_the_scene", bool(synced))
            subprocess.run(["taskkill", "/PID", str(max(int(r["ProcessId"]) for r in node_processes(marker))), "/T", "/F"], capture_output=True, timeout=30)
            failed_text = await ui_chrome.wait_for("document.getElementById('rmsStatus').textContent==='En échec' && document.querySelector('.rms-err').textContent", 40)
            check("10.ui_failure_is_explained_with_its_code", bool(failed_text) and "remotion_studio_process_exited" in failed_text and "disparu" in failed_text, failed_text)
            await ui_chrome.shot(shots / "ui-card-failed.png")
            await ui_chrome.evaluate("document.getElementById('rmsRestart').click(); true")
            back = await ui_chrome.wait_for("document.getElementById('rmsStatus').textContent==='Prêt' && 'yes'", 150)
            await ui_chrome.evaluate("document.getElementById('rmsClose').click(); true")
            closed = await ui_chrome.wait_for("document.getElementById('rmsStatus').textContent==='Arrêté' && document.querySelector('.rms-hint') && document.querySelector('.rms-hint').textContent", 60)
            check("10.ui_restart_then_close", back == "yes" and bool(closed) and "Fermé à votre demande" in closed and not node_processes(marker), closed)
            await ui_chrome.send("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 2, "mobile": True})
            await asyncio.sleep(1)
            overflow = await ui_chrome.evaluate("(()=>{const c=document.querySelector('.rms-card').getBoundingClientRect();return {w:Math.round(c.width),right:Math.round(c.right),vw:innerWidth,sw:document.getElementById('rmsCard').scrollWidth}})()")
            await ui_chrome.shot(shots / "ui-card-mobile.png")
            check("10.ui_card_fits_a_phone_width", overflow["right"] <= overflow["vw"] and overflow["sw"] <= overflow["vw"], overflow)
            errors = [e for e in ui_chrome.events if e["method"] == "Runtime.exceptionThrown"]
            console_errors = [str(e["params"]["args"][0].get("value", ""))[:120] for e in ui_chrome.events if e["method"] == "Runtime.consoleAPICalled"
                              and e["params"]["type"] == "error" and e["params"]["args"] and "remotion-studio" in str(e["params"]["args"][0].get("value", ""))]
            check("10.ui_no_script_exception_and_no_remotion_console_error", not errors and not console_errors, {"exceptions": len(errors), "console": console_errors})
            await ui_chrome.close()
        finally:
            subprocess.run(["taskkill", "/PID", str(cc.pid), "/T", "/F"], capture_output=True, timeout=30)
        # ---- ouverture avant le délai d'inactivité
        status, body = core.call("POST", "/v1/local-capabilities/remotion/studio/open", {"prefab_id": SCENE_A, "version": va2})
        opened = body["studio"]["status"] == "ready"
        # ---- 11. délai d'inactivité réel (Core lancé avec JARVIS_REMOTION_STUDIO_IDLE_S=60)
        await chrome.close()
        chrome = None
        t0 = time.monotonic()
        view = wait_status(core, "stopped", 150)
        NOTES["idle_seconds"] = round(time.monotonic() - t0, 1)
        check("11.idle_timeout_stops_the_studio_by_itself", opened and view["status"] == "stopped" and view["stop_reason"] == "idle_timeout" and not node_processes(marker),
              {"seconds_after_last_window_closed": NOTES["idle_seconds"], "reason": view.get("stop_reason")})
        # ---- 12. Core tué brutalement (sans son arbre) : le Studio survit un court instant, le Core suivant l'ADOPTE ; sans Core, le garde l'achève
        status, body = core.call("POST", "/v1/local-capabilities/remotion/studio/open", {"prefab_id": SCENE_A, "version": va2})
        pids_hard = {int(r["ProcessId"]) for r in node_processes(marker)}
        subprocess.run(["taskkill", "/PID", str(core.proc.pid), "/F"], capture_output=True, timeout=30)  # le Core seul, pas ses enfants
        core.proc.wait(timeout=30)
        time.sleep(2)
        survived = bool(pids_hard) and all(alive(p) for p in pids_hard)
        core = IsolatedCore(work, idle_s=60)
        core.start()
        view = studio(core)
        check("12.restarted_core_adopts_the_surviving_studio", survived and view["status"] == "ready" and view["port"] == port_of(view),
              {"survived_kill": survived, "status": view["status"]})
        subprocess.run(["taskkill", "/PID", str(core.proc.pid), "/F"], capture_output=True, timeout=30)
        core.proc.wait(timeout=30)
        t0 = time.monotonic()
        while time.monotonic() - t0 < 120 and node_processes(marker):
            time.sleep(2)
        check("12.studio_ends_itself_when_core_never_comes_back", not node_processes(marker), {"seconds_after_core_death": round(time.monotonic() - t0, 1)})
        exit_file = studio_dir / "exit.json"
        NOTES["guard_exit"] = json.loads(exit_file.read_text(encoding="utf-8")) if exit_file.exists() else None
        # arrêt PROPRE de Core avec un Studio ouvert : Core le ferme (raison `core_stopped`), aucun orphelin
        core = IsolatedCore(work, idle_s=60)
        core.start()
        core.call("POST", "/v1/local-capabilities/remotion/studio/restart")
        core.call("POST", "/v1/local-capabilities/remotion/studio/open", {"prefab_id": SCENE_A, "version": va2})
        opened = studio(core)["status"] == "ready"
        graceful = core.stop()
        time.sleep(1)
        orphans = node_processes(marker)
        core = IsolatedCore(work, idle_s=60)
        core.start()
        view = studio(core)
        check("12.graceful_core_stop_closes_the_studio_itself", opened and graceful and not orphans and view["status"] == "stopped" and view["stop_reason"] == "core_stopped",
              {"opened": opened, "graceful_exit": graceful, "orphans": [int(r["ProcessId"]) for r in orphans], "reason": view.get("stop_reason")})
        core.stop()
        # ---- 13. collision de port (runner réel)
        from jarvis.adapters.remotion_studio_runner import RemotionStudioRunner
        from jarvis.domain.remotion_studio import StudioError
        busy = socket.socket()
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        runner = RemotionStudioRunner(lambda: runtime)
        try:
            runner.launch(port=busy.getsockname()[1])
            code = "started"
        except StudioError as exc:
            code = exc.code.value
        busy.close()
        check("13.busy_configured_port_is_a_typed_refusal", code == "remotion_studio_port_unavailable", code)
        # ---- 14. désinstallation : arrêt du Studio d'abord (Core neuf)
        core = IsolatedCore(work)
        core.start()
        core.call("POST", "/v1/local-capabilities/remotion/studio/open", {"prefab_id": SCENE_A, "version": va2})
        opened = studio(core)["status"] == "ready"
        status, body = core.call("POST", "/v1/local-capabilities/remotion/uninstall")
        done = body["capability"]
        deadline = time.monotonic() + 120
        while done["status"] == "uninstalling" and time.monotonic() < deadline:
            time.sleep(2)
            done = core.call("GET", "/v1/local-capabilities/remotion")[1]["capability"]
        check("14.uninstall_stops_the_studio_first", opened and done["status"] == "not_installed" and not node_processes(marker) and studio(core)["stop_reason"] == "capability_change",
              {"capability": done["status"]})
        core.stop()
    except Exception as exc:  # noqa: BLE001
        check("harness.no_exception", False, f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if chrome is not None:
            await chrome.close()
        core.stop()
        left = node_processes(str(work))
        NOTES["leftover_processes_killed"] = kill_leftovers(work)
        for row in left:
            subprocess.run(["taskkill", "/PID", str(row["ProcessId"]), "/T", "/F"], capture_output=True, timeout=30)
        NOTES["final_orphans_killed_by_harness"] = [int(r["ProcessId"]) for r in left]
        check("end.no_node_process_left_under_the_work_dir", not left, NOTES["final_orphans_killed_by_harness"])
        verdict = "PASSED" if CHECKS and all(c["ok"] for c in CHECKS.values()) else "FAILED"
        evidence = {"verdict": verdict, "notes": NOTES, "checks": CHECKS, "finished": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        Path(args.evidence).parent.mkdir(parents=True, exist_ok=True)
        Path(args.evidence).write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
        print(verdict, f"({sum(c['ok'] for c in CHECKS.values())}/{len(CHECKS)} checks)")
    return 0 if all(c["ok"] for c in CHECKS.values()) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--evidence", required=True)
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
