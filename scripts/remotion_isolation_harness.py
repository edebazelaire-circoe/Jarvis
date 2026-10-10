"""Harnais d'ISOLATION RÉELLE d'une scène Remotion hostile (Slice 06 de jarvis-remotion-presentation-integration).

Prouve, dans un vrai Chrome piloté par le protocole DevTools, que le contrat d'exécution isolée
(`jarvis.domain.remotion_sandbox` + `jarvis.runtime.remotion_sandbox` + `remotion_sandbox_protocol.js`) neutralise ou borne chaque
attaque du corpus `tests/fakes/remotion_hostile.py`, et qu'une scène honnête s'affiche toujours.

Ce qui est RÉEL : le compilateur (Node + esbuild du verrou de la capacité Remotion), le `PrefabService` (publication, gardes
statiques), les en-têtes et la page produits par le code livré, le protocole et le chien de garde JavaScript livrés, Chrome.
Ce qui est SIMULÉ : l'hôte (une page minimale qui joue le rôle du Control Center) et les trois origines (boucle locale :
l'hôte 127.0.0.1, le bac à sable 127.0.0.2, un « attaquant » 127.0.0.3 qui journalise tout ce qu'il reçoit).

    python scripts/remotion_isolation_harness.py --work-dir C:/Users/<moi>/AppData/Local/Temp/jrs6 \\
        --runtime-dir <racine>/local_capabilities/remotion/runtime \\
        --evidence tasks/jarvis-remotion-presentation-integration/slices/06-remotion-source-isolation/evidence/real-isolation.json

Racine de données PRIVÉE, Chrome avec profil jetable (`--user-data-dir` neuf, plafond de tas `--max-old-space-size=512`), aucun
accès à Core, au Control Center, à la voix ni à `~/.jarvis`. Les « bombes » sont bornées (240 Mio au plus) même si le plafond échoue.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import http.server
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis.adapters.file_prefab_library import FilePrefabLibrary  # noqa: E402
from jarvis.adapters.node_capability_runner import default_remotion_runner  # noqa: E402
from jarvis.adapters.remotion_compiler import RemotionCompiler, shipped_engine_pin  # noqa: E402
from jarvis.core.prefab_service import PrefabService  # noqa: E402
from jarvis.domain import remotion_sandbox as sb  # noqa: E402
from jarvis.domain.remotion_compile import RemotionCompileError  # noqa: E402
from jarvis.domain import remotion_source as rsrc  # noqa: E402
from jarvis.domain.remotion_source import Composition, build_candidate  # noqa: E402
from jarvis.ports.prefabs import PrefabStoreError  # noqa: E402
from jarvis.runtime.remotion_sandbox import SandboxResponder, load_bootstrap  # noqa: E402
from tests.fakes.remotion_hostile import SAMPLES, Hostile  # noqa: E402
from tests.fakes.remotion_scene import PNG_1X1  # noqa: E402

CHROME = (Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
          Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe")
EMBEDDER_IP, SANDBOX_IP, ATTACKER_IP = "127.0.0.1", "127.0.0.2", "127.0.0.3"
COMPOSITION = Composition("Scene", 1280, 720, 30, 90)
BENIGN_SCENE = """import React from "react";
import {AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame} from "remotion";
import {Title} from "./lib/Title";
export default function Scene(props: {title?: string}) {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 10], [0, 1], {extrapolateRight: "clamp"});
  return (
    <AbsoluteFill style={{background: "#101820", opacity: Math.max(opacity, 0.5)}}>
      <Title text={props.title ?? "Bonjour"} />
      <Img id="dot" src={staticFile("dot.png")} style={{width: 16, height: 16}} />
    </AbsoluteFill>
  );
}
"""
BENIGN_TITLE = ('import React from "react";\n'
                'export const Title = ({text}: {text: string}) => <h1 id="title" style={{color: "#fff"}}>{text}</h1>;\n')
BENIGN = {"src/Scene.tsx": BENIGN_SCENE, "src/lib/Title.tsx": BENIGN_TITLE, "public/dot.png": PNG_1X1}
#: Ablations: take ONE layer away and show what the others still hold (and what leaks), to prove each layer carries weight.
CORE_CONTROLLED = ("net_exfil", "storage_read", "parent_access")
CHANNEL_SAMPLES = ("webrtc_exfil", "link_hints")
CONTROLLED = CORE_CONTROLLED + CHANNEL_SAMPLES
ABLATIONS = {
    "nohard": ("127.0.0.6", "the in-realm WebRTC hardening of the bootstrap is removed (sandbox, CSP and origin kept)"),
    "nocsp": ("127.0.0.4", "the CSP header is removed (iframe sandbox attribute and dedicated origin kept)"),
    "noiso": ("127.0.0.5", "the iframe sandbox attribute and the CSP sandbox directive are removed (dedicated origin and the rest of the CSP kept)"),
}
#: The shipped default is 768 MB (LIMITS.maxHeapMb); the harness lowers it so a bounded 400 MB creep is enough to prove the mechanism.
HARNESS_MAX_HEAP_MB = 128
ABLATION_SAMPLES = {"nohard": CHANNEL_SAMPLES, "nocsp": CORE_CONTROLLED, "noiso": CORE_CONTROLLED}
PROPS = {"type": "object", "properties": {"title": {"type": "string", "default": "Bonjour", "max_length": 80}}}

CHILD_PROBE = """JSON.stringify({
  title: (document.getElementById('title') || {}).innerText || null,
  img: (() => { const i = document.querySelector('img'); return i ? {complete: i.complete, w: i.naturalWidth, src: i.getAttribute('src')} : null; })(),
  href: location.href.replace(/[?#].*$/, ''), origin: self.origin, documentTitle: document.title,
  bodyChildren: document.body ? document.body.children.length : -1,
  cookieAccess: (() => { try { return 'allowed:' + document.cookie.length; } catch (e) { return 'blocked:' + e.name; } })(),
  storageAccess: (() => { try { return 'allowed:' + String(localStorage.getItem('jarvis_secret')); } catch (e) { return 'blocked:' + e.name; } })(),
  injected: !!document.getElementById('inj') && document.getElementById('inj').innerHTML.length
})"""

EMBEDDER_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>host</title></head><body><div id="status">host</div>
<script src="/protocol.js"></script>
<script>
(function () {
  const Q = new URLSearchParams(location.search);
  const WAIT = Number(Q.get('wait')) || 5000, SRC = Q.get('src'), CONTROL = Q.get('control') === '1', SCENARIO = Q.get('scenario') || 'run';
  // Secrets of the host page: a hostile scene must never read any of them.
  localStorage.setItem('jarvis_secret', 'SECRET_LS'); sessionStorage.setItem('jarvis_secret', 'SECRET_SS');
  document.cookie = 'jarvis_cookie=SECRET_COOKIE; path=/'; window.JARVIS_TOKEN = 'SECRET_WIN';
  const P = window.RemotionSandboxProtocol;
  const R = window.__REPORT = {sample: Q.get('sample'), scenario: SCENARIO, control: CONTROL, probes: [], accepted: [], rejected: {}, csp: [], errors: [],
    killed: null, done: false, maxGapMs: 0, foreignMessages: 0, supervisor: null, urlAtStart: location.href};
  const t0 = performance.now();
  const iframe = document.createElement('iframe');
  if (!CONTROL) {
    const attrs = JSON.parse(Q.get('attrs'));
    for (const [k, v] of Object.entries(attrs)) iframe.setAttribute(k, v);
  }
  iframe.style.cssText = 'width:320px;height:180px;border:0';
  const finishSoon = () => setTimeout(finish, 800);
  const sup = P.createSupervisor({limits: {maxHeapMb: Number(Q.get('maxHeap')) || 768}, now: () => performance.now(),
    send: (m) => { try { iframe.contentWindow.postMessage(m, '*'); } catch (e) {} },
    kill: (reason, detail) => { R.killed = {reason, detail, atMs: Math.round(performance.now() - t0)}; try { iframe.remove(); } catch (e) {} finishSoon(); }});
  const post = (m) => { try { iframe.contentWindow.postMessage(P.hostMessage(m.type, m.fields), '*'); } catch (e) { R.errors.push(String(e.message)); } };
  window.addEventListener('message', (ev) => {
    if (ev.source !== iframe.contentWindow || ev.source === null) { R.foreignMessages++; return; }
    const d = ev.data;
    // HARNESS ONLY: a hostile scene reports what each attempt did through a non-protocol message; a real host drops these.
    if (d && typeof d === 'object' && typeof d.probe === 'string' && !('rs' in d)) { if (R.probes.length < 200) R.probes.push({probe: d.probe, v: d.v}); return; }
    const r = sup.accept(ev, iframe.contentWindow);
    if (!r.ok) { R.rejected[r.reason] = (R.rejected[r.reason] || 0) + 1; return; }
    if (R.accepted.length < 60) R.accepted.push(r.message.type);
    if (r.message.type === 'violation' && R.csp.length < 100) R.csp.push(r.message.directive);
    if (r.message.type === 'error' && R.errors.length < 20) R.errors.push(r.message.message);
    if (r.message.type === 'ready') {
      post({type: 'init', fields: {composition: {id: 'Scene', width: 1280, height: 720, fps: 30, durationInFrames: 90}, props: {title: Q.get('title') || 'Bonjour'}}});
      if (SCENARIO === 'benign' || SCENARIO === 'sibling') {
        setTimeout(() => post({type: 'props', fields: {props: {title: 'Mis a jour'}}}), 1500);
        setTimeout(() => post({type: 'control', fields: {action: 'seek', frame: 30}}), 2200);
        setTimeout(() => post({type: 'cue', fields: {name: 'intro', frame: 45}}), 2600);
      }
    }
  });
  let last = performance.now();
  setInterval(() => { const t = performance.now(); R.maxGapMs = Math.max(R.maxGapMs, Math.round(t - last - 100)); last = t; }, 100);
  setInterval(() => sup.tick(), 250);
  function finish() {
    if (R.done) return;
    R.supervisor = sup.state(); R.urlAtEnd = location.href;
    R.secretsIntact = {ls: localStorage.getItem('jarvis_secret'), ss: sessionStorage.getItem('jarvis_secret'), cookie: document.cookie.includes('SECRET_COOKIE'), win: window.JARVIS_TOKEN};
    R.pollution = ({}).admin === undefined && Object.prototype.admin === undefined;
    R.elapsedMs = Math.round(performance.now() - t0); R.done = true;
  }
  setTimeout(finish, WAIT);
  iframe.src = SRC;
  document.body.appendChild(iframe);
  if (SCENARIO === 'sibling') {
    const sibling = document.createElement('iframe'); sibling.setAttribute('sandbox', 'allow-scripts'); sibling.src = Q.get('sibling');
    sibling.style.cssText = 'width:100px;height:50px;border:0'; document.body.appendChild(sibling);
  }
})();
</script></body></html>"""

SPOOFER_PAGE = """<!doctype html><meta charset="utf-8"><script>
let i = 0;
const timer = setInterval(() => {
  try {
    const f = top.frames[0];
    f.postMessage({rs: 1, type: 'props', props: {title: 'SPOOFED-BY-SIBLING'}}, '*');
    f.postMessage({rs: 1, type: 'ping', n: 'spoofed1'}, '*');
    f.postMessage({rs: 1, type: 'teardown'}, '*');
  } catch (e) {}
  if (++i > 25) clearInterval(timer);
}, 150);
</script>"""


class Quiet(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D401 - silence
        return

    def _serve(self, send_body: bool) -> None:
        status, headers, body = self.server.handle(self)  # type: ignore[attr-defined]
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        self._serve(True)

    def do_HEAD(self):  # noqa: N802
        self._serve(False)

    def do_POST(self):  # noqa: N802
        self._serve(True)


class UdpSink:
    """Puits UDP (STUN/TURN d'un attaquant) : compte et décrit les paquets reçus."""

    def __init__(self, ip: str) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((ip, 0))
        self.sock.settimeout(0.5)
        self.host = f"{ip}:{self.sock.getsockname()[1]}"
        self.packets: list[dict] = []
        self._stop = False
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        while not self._stop:
            try:
                data, _ = self.sock.recvfrom(4096)
            except OSError:
                continue
            self.packets.append({"bytes": len(data), "head": data[:12].hex(), "has_username": b"exfil-" in data})

    def close(self) -> None:
        self._stop = True
        self.sock.close()


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, ip: str, handler) -> None:
        super().__init__((ip, 0), Quiet)
        self.handle = handler
        self.ip = ip
        self.requests: list[dict] = []
        self.connections = 0
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def verify_request(self, request, client_address):  # noqa: D401 - counts TCP connections, requests or not (preconnect)
        self.connections += 1
        return True

    @property
    def origin(self) -> str:
        return f"http://{self.ip}:{self.server_address[1]}"

    @property
    def host(self) -> str:
        return f"{self.ip}:{self.server_address[1]}"

    def log(self, request: Quiet, status: int) -> None:
        self.requests.append({"t": round(time.monotonic(), 3), "method": request.command, "path": request.path[:160], "status": status,
                              "cookie": request.headers.get("Cookie"), "referer": request.headers.get("Referer"),
                              "origin": request.headers.get("Origin"), "authorization": request.headers.get("Authorization")})


def attacker_handler(server_ref: list[Server]):
    def handle(request: Quiet):
        server = server_ref[0]
        path = urlparse(request.path).path
        if path == "/spoofer.html":
            server.log(request, 200)
            return 200, {"Content-Type": "text/html; charset=utf-8"}, SPOOFER_PAGE.encode()
        server.log(request, 200)
        return 200, {"Content-Type": "image/gif", "Access-Control-Allow-Origin": "*"}, b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    return handle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--runtime-dir", required=True, help="an installed Remotion runtime (install-record.json inside)")
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    work = Path(args.work_dir).resolve()
    if ".jarvis" in work.parts:
        print("refused: the work dir must not live under ~/.jarvis (the live profile)")
        return 2
    runtime = Path(args.runtime_dir).resolve()
    if not (runtime / "install-record.json").is_file():
        print("refused: no installed Remotion runtime at", runtime)
        return 2
    chrome = next((c for c in CHROME if c.is_file()), None)
    if chrome is None:
        print("refused: Chrome not found")
        return 2
    run_dir = work / "isolation-run"
    shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir(parents=True)

    compiler = RemotionCompiler(runner=default_remotion_runner(), runtime_dir=runtime, cache_dir=run_dir / "compiled", readiness=lambda: None)
    package, data = run_dir / "package", run_dir / "data"
    package.mkdir()
    data.mkdir()
    service = PrefabService(FilePrefabLibrary(package, data))
    git = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()  # noqa: E731
    report: dict = {
        "harness": "scripts/remotion_isolation_harness.py", "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repo_head": git("rev-parse", "HEAD"), "repo_dirty": bool(git("status", "--porcelain")), "platform": platform.platform(),
        "python": sys.version.split()[0], "node": subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip(),
        "chrome": subprocess.run(["powershell", "-NoProfile", "-Command", f"(Get-Item '{chrome}').VersionInfo.ProductVersion"],
                                 capture_output=True, text=True).stdout.strip(),
        "chrome_flags": ["--headless=new", "--js-flags=--max-old-space-size=512", "fresh --user-data-dir", "site isolation left at its default"],
        "layers_under_test": ["static guards (SOURCE_GUARDS)", "dedicated origin", "iframe sandbox=allow-scripts", "CSP header (nonce, connect-src none)",
                              "rs:1 protocol + supervisor", "response headers (nosniff, no cookies)"],
        "samples": {}}
    host_art = compiler.compile_host()
    report["host_bundle"] = {"cache_key": host_art.cache_key, "bytes": host_art.files[0].bytes}

    # ---- publish + compile every sample, both flavors
    compiled: dict[str, dict] = {}
    selected = [s for s in SAMPLES if not args.only or s.id in args.only.split(",")]

    channels: dict[str, dict] = {}

    def channel(tag: str) -> dict:
        """Puits propres à une épreuve (UDP, connexion TCP) : chaque paquet ou connexion reçu est attribuable à `tag`."""
        if tag not in channels:
            holder: list[Server] = []
            tcp = Server(ATTACKER_IP, lambda request: (holder[0].log(request, 200) or (200, {"Content-Type": "text/plain"}, b"ok")))
            holder.append(tcp)
            channels[tag] = {"udp": UdpSink(ATTACKER_IP), "tcp": tcp}
        return channels[tag]

    def publish(sample_id: str, flavor: str, files: dict, *, guards: bool, tag: str | None = None):
        digest = hashlib.sha1(f"{sample_id}/{flavor}".encode()).hexdigest()[:12]
        prefab_id = "presentation-studio.p0000000000a1.s" + digest
        pairs = [("__ATTACKER__", attacker.origin)]
        if tag is not None:
            sinks = channel(tag)
            pairs += [("__UDP__", sinks["udp"].host), ("__PRECONNECT__", sinks["tcp"].origin), ("__TAG__", tag)]

        def fill(value):
            for token, replacement in pairs:
                value = value.replace(token, replacement) if isinstance(value, str) else value.replace(token.encode(), replacement.encode())
            return value

        text_files = {k: fill(v) for k, v in files.items()}
        candidate = build_candidate(prefab_id=prefab_id, title=f"{sample_id}-{flavor}", composition=COMPOSITION, engine=shipped_engine_pin(),
                                    files=text_files, props=PROPS, sample={"props": {"title": "Bonjour"}, "data": {}})
        original = rsrc.SOURCE_GUARDS
        try:
            if not guards:
                rsrc.SOURCE_GUARDS = ()  # the harness proves the RUNTIME layer alone: the static layer is switched off for this publication
            asyncio.run(service.save(candidate, actor="user"))
            source = asyncio.run(service.remotion_source(prefab_id, 1))
        finally:
            rsrc.SOURCE_GUARDS = original
        return compiler.compile_scene(source)

    # the attacker sink must exist before sources are published (its URL is baked into the scenes)
    attacker_ref: list[Server] = []
    attacker = Server(ATTACKER_IP, attacker_handler(attacker_ref))
    attacker_ref.append(attacker)

    def publish_with_static_layer(sample_id: str, flavor: str, files: dict, tag: str | None = None):
        """Publie avec les gardes réelles ; si elles refusent, garde le refus puis publie SANS elles (couche d'exécution seule)."""
        try:
            return {"published": True, "errors": [], "bypassed": False}, publish(sample_id, flavor, files, guards=True, tag=tag)
        except PrefabStoreError as exc:
            verdict = {"published": False, "code": exc.code.value, "errors": [e[:200] for e in exc.errors[:5]], "bypassed": True}
            return verdict, publish(sample_id, flavor + "-bypass", files, guards=False, tag=tag)

    for sample in selected:
        entry = report["samples"][sample.id] = {"summary": sample.summary, "expected_runtime": sample.runtime, "static": {}}
        for flavor in ("direct", "evasive"):
            try:
                verdict, artifact = publish_with_static_layer(sample.id, flavor, sample.source(flavor), tag=f"{sample.id}_{flavor}")
            except RemotionCompileError as exc:  # a third layer: the compiler itself refuses a literal dynamic import
                entry["static"][flavor] = {"published": False, "bypassed": True, "compiler_refused": exc.code.value, "message": exc.message[:200]}
                continue
            entry["static"][flavor] = verdict
            compiled[f"{sample.id}:{flavor}"] = {"scene_key": artifact.cache_key, "files": [f.path for f in artifact.files]}
        if sample.id in CONTROLLED:
            _, artifact = publish_with_static_layer(f"control_{sample.id}", "evasive", sample.source("evasive", attacker_id=f"control_{sample.id}"),
                                                    tag=f"control_{sample.id}")
            compiled[f"control_{sample.id}"] = {"scene_key": artifact.cache_key, "files": [f.path for f in artifact.files]}
            for variant in ABLATIONS:
                if sample.id not in ABLATION_SAMPLES[variant]:
                    continue
                _, artifact = publish_with_static_layer(f"abl_{variant}_{sample.id}", "evasive",
                                                        sample.source("evasive", attacker_id=f"abl_{variant}_{sample.id}"), tag=f"abl_{variant}_{sample.id}")
                compiled[f"abl_{variant}_{sample.id}"] = {"scene_key": artifact.cache_key, "files": [f.path for f in artifact.files]}
    benign_art = publish("benign", "direct", BENIGN, guards=True)
    compiled["benign:direct"] = {"scene_key": benign_art.cache_key, "files": [f.path for f in benign_art.files]}

    # ---- servers
    bootstrap = load_bootstrap()
    bootstrap_plain = re.sub(r"/\*HARDEN:begin\*/.*?/\*HARDEN:end\*/", "", bootstrap, flags=re.S)
    assert bootstrap_plain != bootstrap
    protocol_js = (ROOT / "jarvis/runtime/remotion_sandbox_protocol.js").read_bytes()
    embedder_ref: list[Server] = []
    sandbox_ref: list[Server] = []

    def sandbox_handler(request: Quiet):
        server = sandbox_ref[0]
        response = responder.respond(request.command, request.path, request.headers.get("Host"), request.headers.get("Range"))
        server.log(request, response.status)
        return response.status, response.headers, response.body

    def embedder_handler(request: Quiet):
        server = embedder_ref[0]
        parsed = urlparse(request.path)
        server.log(request, 200)
        if parsed.path == "/protocol.js":
            return 200, {"Content-Type": "text/javascript"}, protocol_js
        if parsed.path.startswith(("/page/", "/f/")):  # NEGATIVE CONTROL: same bytes served from the host's own origin, no CSP, no sandbox
            response = responder_plain.respond("GET", parsed.path, sandbox.host)
            headers = {k: v for k, v in response.headers.items() if k.lower() not in ("content-security-policy", "content-length")}
            return response.status, headers, response.body
        if parsed.path == "/host.html":
            query = parse_qs(parsed.query)
            sibling = query.get("sibling", [""])[0]
            headers = {"Content-Type": "text/html; charset=utf-8", "Set-Cookie": "jarvis_session=HOST_SESSION; Path=/"}
            if "control" not in query and "ablation" not in query:  # the unprotected world and the ablations: no frame-src either
                headers["Content-Security-Policy"] = sb.embedder_frame_src(sandbox.origin) + (" " + attacker.origin if sibling else "")
            return 200, headers, EMBEDDER_PAGE.encode()
        return 404, {"Content-Type": "text/plain"}, b"not found"

    embedder = Server(EMBEDDER_IP, embedder_handler)
    embedder_ref.append(embedder)
    sandbox = Server(SANDBOX_IP, sandbox_handler)
    sandbox_ref.append(sandbox)
    responder = SandboxResponder(resolve_file=compiler.resolve_output_file, embedder_origin=embedder.origin, sandbox_origin=sandbox.origin,
                                 allowed_hosts=frozenset({sandbox.host}), bootstrap_js=bootstrap)
    responder_plain = SandboxResponder(resolve_file=compiler.resolve_output_file, embedder_origin=embedder.origin, sandbox_origin=sandbox.origin,
                                       allowed_hosts=frozenset({sandbox.host}), bootstrap_js=bootstrap_plain)
    variants: dict[str, Server] = {}
    for variant, (ip, _) in ABLATIONS.items():
        holder: list = []

        def variant_handler(request: Quiet, variant=variant, holder=holder):
            server, local = holder
            response = local.respond(request.command, request.path, request.headers.get("Host"), request.headers.get("Range"))
            server.log(request, response.status)
            headers = dict(response.headers)
            if variant == "nocsp":
                headers.pop("Content-Security-Policy", None)
            elif "Content-Security-Policy" in headers:
                headers["Content-Security-Policy"] = headers["Content-Security-Policy"].replace("; sandbox allow-scripts", "")
            return response.status, headers, response.body

        server = Server(ip, variant_handler)
        holder.extend([server, SandboxResponder(resolve_file=compiler.resolve_output_file, embedder_origin=embedder.origin, sandbox_origin=server.origin,
                                                allowed_hosts=frozenset({server.host}),
                                                bootstrap_js=bootstrap_plain if variant == "nohard" else bootstrap)])
        variants[variant] = server
    report["origins"] = {"host_page": embedder.origin, "sandbox": sandbox.origin, "attacker_sink": attacker.origin,
                         "ablation_sandboxes": {name: srv.origin for name, srv in variants.items()}}
    report["iframe_attributes"] = sb.IFRAME_ATTRIBUTES

    # ---- jobs
    attrs = json.dumps(sb.IFRAME_ATTRIBUTES)

    def page_url(scene_key: str, wait: int, sample: str, *, scenario="run", control=False, sibling=False, title="Bonjour",
                 variant: str | None = None) -> str:
        from urllib.parse import quote
        base = embedder.origin if control else variants[variant].origin if variant else sandbox.origin
        src = f"{base}/page/{scene_key}/{host_art.cache_key}"
        use_attrs = "{}" if variant == "noiso" else attrs
        query = (f"sample={sample}&scenario={scenario}&wait={wait}&title={quote(title)}&src={quote(src, safe='')}"
                 f"&attrs={quote(use_attrs, safe='')}&maxHeap={HARNESS_MAX_HEAP_MB}")
        if control:
            query += "&control=1"
        if variant:
            query += "&ablation=1"
        if sibling:
            query += "&sibling=" + quote(attacker.origin + "/spoofer.html", safe="")
        return f"{embedder.origin}/host.html?{query}"

    jobs: list[dict] = []
    meta: dict[str, dict] = {}

    def add(job_id: str, url: str, wait: int, *, child=True, self_probe=None, mark=None) -> None:
        job = {"id": job_id, "url": url, "timeoutMs": wait + 12000, "doneExpr": "window.__REPORT && window.__REPORT.done === true"}
        if child:
            job["childProbe"] = CHILD_PROBE
        if self_probe:
            job = {"id": job_id, "url": url, "timeoutMs": 6000, "selfProbe": self_probe, "settleMs": 3000}
        jobs.append(job)
        meta[job_id] = mark or {}

    add("benign", page_url(compiled["benign:direct"]["scene_key"], 4500, "benign", scenario="benign"), 4500, mark={"sample": "benign"})
    add("benign_sibling_spoof", page_url(compiled["benign:direct"]["scene_key"], 4500, "benign", scenario="sibling", sibling=True), 4500,
        mark={"sample": "benign"})
    for sample in selected:
        for flavor in ("evasive", "direct"):
            if f"{sample.id}:{flavor}" not in compiled:
                continue
            key = compiled[f"{sample.id}:{flavor}"]["scene_key"]
            add(f"{sample.id}:{flavor}", page_url(key, sample.wait_ms, sample.id), sample.wait_ms, mark={"sample": sample.id, "flavor": flavor})
    for control_id in CONTROLLED:
        if control_id in {s.id for s in selected}:
            key = compiled[f"control_{control_id}"]["scene_key"]
            add(f"control:{control_id}", page_url(key, 4000, control_id, control=True), 4000, mark={"sample": f"control_{control_id}", "control": True})
    for control_id in CONTROLLED:
        for variant in ABLATIONS:
            if f"abl_{variant}_{control_id}" in compiled:
                key = compiled[f"abl_{variant}_{control_id}"]["scene_key"]
                add(f"ablation:{variant}:{control_id}", page_url(key, 4000, control_id, variant=variant), 4000,
                    mark={"sample": f"abl_{variant}_{control_id}", "ablation": variant})
    if "svg_script" in {s.id for s in selected}:
        svg_key = compiled["svg_script:evasive"]["scene_key"]
        add("svg_direct_open", f"{sandbox.origin}/f/{svg_key}/public/evil.svg", 3000, child=False,
            self_probe="JSON.stringify({documentTitle: document.title, origin: self.origin, hasSvgRoot: !!document.querySelector('svg')})",
            mark={"sample": "svg_script", "direct_open": True})

    jobs_file, out_file = run_dir / "jobs.json", run_dir / "cdp-out.json"
    jobs_file.write_text(json.dumps(jobs), encoding="utf-8")
    profile = Path(tempfile.mkdtemp(prefix="jrs6-chrome-"))
    netlog = run_dir / "netlog.json"
    proc = subprocess.Popen([str(chrome), "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={profile}", "--disable-gpu",
                             "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--disable-background-networking",
                             "--js-flags=--max-old-space-size=512", f"--log-net-log={netlog}", "--net-log-capture-mode=Default", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        port_file = profile / "DevToolsActivePort"
        deadline = time.monotonic() + 30
        while not port_file.is_file() and time.monotonic() < deadline:
            time.sleep(0.25)
        if not port_file.is_file():
            report["verdict"] = "FAILED: Chrome did not expose DevTools"
            Path(args.evidence).write_text(json.dumps(report, indent=2), encoding="utf-8")
            return 1
        port = port_file.read_text().splitlines()[0]
        started = time.monotonic()
        driver = subprocess.run(["node", str(ROOT / "scripts/remotion_isolation_cdp.mjs"), port, str(jobs_file), str(out_file)],
                                capture_output=True, text=True, timeout=1500, encoding="utf-8", errors="replace")
        report["driver"] = {"returncode": driver.returncode, "seconds": round(time.monotonic() - started, 1), "stderr": driver.stderr[-400:]}
        try:  # a graceful exit flushes the net-log (DNS lookups are read from it)
            proc.wait(timeout=40)
        except subprocess.TimeoutExpired:
            report["driver"]["chrome_exit"] = "forced"
    finally:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        time.sleep(1)
        shutil.rmtree(profile, ignore_errors=True)
    if not out_file.is_file():
        report["verdict"] = "FAILED: the DevTools driver produced nothing"
        Path(args.evidence).write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 1
    raw = json.loads(out_file.read_text(encoding="utf-8"))
    netlog_text = netlog.read_text(encoding="utf-8", errors="replace") if netlog.is_file() else ""
    report["channel_observations"] = {
        tag: {"udp_packets": len(sinks["udp"].packets), "udp_packets_carrying_the_username": sum(p["has_username"] for p in sinks["udp"].packets),
              "tcp_connections": sinks["tcp"].connections, "dns_lookups_logged": netlog_text.count(f"{tag}.exfil-probe.test")}
        for tag, sinks in channels.items()}
    report["netlog_bytes"] = len(netlog_text)

    # ---- verdicts
    def hits_for(sample_id: str) -> list[str]:
        return [r["path"] for r in attacker.requests if r["path"].startswith(f"/{sample_id}/")]

    results: dict[str, dict] = {}
    for job_id, record in raw.items():
        parent = json.loads(record["parent"]["value"]) if record.get("parent") and record["parent"].get("ok") and record["parent"].get("value") else None
        child_raw = record.get("child") or {}
        child = json.loads(child_raw["value"]) if child_raw.get("ok") and child_raw.get("value") else child_raw
        self_probe = json.loads(record["self"]["value"]) if record.get("self") and record["self"].get("ok") and record["self"].get("value") else None
        results[job_id] = {"meta": meta[job_id], "done": record["done"], "elapsed_ms": record.get("elapsedMs"),
                           "parent": parent, "child": child, "self": self_probe, "crashed_targets": record["crashed"], "notes": record["notes"][:5], "browser_console": record.get("console", []),
                           "attacker_hits": hits_for(meta[job_id].get("sample", "")) if job_id != "benign" else []}
    checks = evaluate(results, selected, attacker, sandbox)
    checks.update(evaluate_channels(report["channel_observations"], results, selected))
    report["jobs"] = results
    report["checks"] = checks
    report["static_layer"] = {s.id: {fl: report["samples"][s.id]["static"][fl] for fl in ("direct", "evasive")} for s in selected}
    report["sandbox_server_requests"] = {"count": len(sandbox.requests), "with_cookie": [r for r in sandbox.requests if r["cookie"]][:3],
                                        "with_referer": [r for r in sandbox.requests if r["referer"]][:3],
                                        "statuses": sorted({r["status"] for r in sandbox.requests}), "sample": sandbox.requests[:4]}
    report["attacker_requests_total"] = len([r for r in attacker.requests if r["path"] != "/spoofer.html"])
    report["attacker_requests_outside_controls_and_ablations"] = [r["path"] for r in attacker.requests
                                                    if r["path"] != "/spoofer.html" and not r["path"].startswith(("/control_", "/abl_"))]
    failed = [name for name, value in checks.items() if not value["ok"]]
    report["verdict"] = "PASSED" if not failed else "FAILED: " + ", ".join(failed)
    Path(args.evidence).parent.mkdir(parents=True, exist_ok=True)
    Path(args.evidence).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(report["verdict"], args.evidence)
    for server in (embedder, sandbox, attacker):
        server.shutdown()
    for sinks in channels.values():
        sinks["udp"].close()
    return 0 if not failed else 1


def probe_map(parent: dict | None) -> dict[str, str]:
    return {p["probe"]: p["v"] for p in (parent or {}).get("probes", [])}


def evaluate_channels(observations: dict, results: dict, selected) -> dict:
    """Canaux que `connect-src 'none'` ne gouverne pas (QA B2). WebRTC : fermé par l'amorce (dans le domaine du cadre), ouvert sans elle.
    Indices de lien `dns-prefetch` / `preconnect` : **restent ouverts** (CSP, en-tête et méta sans effet, mesuré) ; ce constat est un
    test de non-régression de la documentation : si un navigateur les ferme, ce test échoue et la page de contrat doit changer."""

    checks: dict[str, dict] = {}
    ids = {s.id for s in selected}
    if "webrtc_exfil" in ids:
        hardened = [observations[f"webrtc_exfil_{fl}"] for fl in ("direct", "evasive")]
        checks["webrtc:closed_by_the_bootstrap_hardening"] = {"ok": all(o["udp_packets"] == 0 for o in hardened), "observations": hardened,
                                                              "scope": "best-effort, in-realm: the CSP has no WebRTC directive"}
        leaks = {name: observations[name]["udp_packets"] for name in ("control_webrtc_exfil", "abl_nohard_webrtc_exfil") if name in observations}
        checks["webrtc:open_without_the_hardening_even_inside_sandbox_and_csp"] = {"ok": bool(leaks) and all(n > 0 for n in leaks.values()), "udp_packets": leaks}
    if "link_hints" in ids:
        seen = {name: observations[name] for name in ("link_hints_direct", "link_hints_evasive") if name in observations}
        checks["residual:dns_prefetch_and_preconnect_stay_open"] = {
            "ok": bool(seen) and all(o["tcp_connections"] >= 1 and o["dns_lookups_logged"] >= 1 for o in seen.values()),
            "observations": seen, "note": "X-DNS-Prefetch-Control: off, the equivalent meta and the CSP do not stop explicit <link rel=dns-prefetch|preconnect>"}
        blocked = [results[f"link_hints:{fl}"]["attacker_hits"] for fl in ("direct", "evasive") if f"link_hints:{fl}" in results]
        checks["link_hints:prefetch_and_preload_are_blocked_by_the_csp"] = {"ok": all(hits == [] for hits in blocked), "attacker_requests": blocked}
    return checks


def evaluate(results: dict, selected, attacker: Server, sandbox: Server) -> dict:
    """Une vérification par échantillon et par saveur : booléen + les constats qui le fondent. Rien n'est inféré de la documentation."""

    checks: dict[str, dict] = {}

    def host_ok(r: dict) -> bool:
        p = r["parent"] or {}
        secrets = p.get("secretsIntact", {})
        return bool(r["done"] and p and secrets.get("ls") == "SECRET_LS" and secrets.get("win") == "SECRET_WIN" and p.get("pollution") is True
                    and p.get("urlAtEnd") == p.get("urlAtStart") and p.get("maxGapMs", 99999) < 1500)

    b = results.get("benign")
    if b:
        child, sup = b["child"], (b["parent"] or {}).get("supervisor", {})
        checks["benign_renders_and_stays_controllable"] = {"ok": bool(host_ok(b) and child.get("title") == "Mis a jour" and (child.get("img") or {}).get("w") == 1
                                                              and sup.get("pongs", 0) >= 2 and not (b["parent"] or {}).get("killed") and (b["parent"] or {}).get("csp") == []
                                                              and child.get("origin") == "null" and sup.get("lastFrame", -1) >= 30),
                                                      "child": child, "pongs": sup.get("pongs"), "last_frame": sup.get("lastFrame"), "csp_violations": b["parent"].get("csp")}
    s = results.get("benign_sibling_spoof")
    if s:
        child, sup = s["child"], (s["parent"] or {}).get("supervisor", {})
        checks["sibling_frame_cannot_drive_the_scene"] = {"ok": bool(host_ok(s) and child.get("title") == "Mis a jour" and sup.get("childDropped", 0) >= 1 and not s["parent"].get("killed")),
                                                         "title": child.get("title"), "messages_dropped_by_the_frame": sup.get("childDropped")}
    for sample in selected:
        for flavor in ("evasive", "direct"):
            r = results.get(f"{sample.id}:{flavor}")
            if r is None:
                continue
            parent = r["parent"] or {}
            probes = probe_map(parent)
            hits = r["attacker_hits"]
            common = host_ok(r) and not hits
            detail: dict = {"attacker_hits": hits, "probes": probes, "csp_violations": sorted(set(parent.get("csp", []))), "killed": parent.get("killed"),
                            "host_max_gap_ms": parent.get("maxGapMs"), "rejected": parent.get("rejected"), "child": r["child"]}
            ok = common
            if sample.id == "net_exfil":
                ok = ok and len(probes) >= 5 and not any("loaded" in v for v in probes.values()) and bool(parent.get("csp"))
            elif sample.id in ("storage_read", "parent_access"):
                ok = ok and len(probes) >= 4 and not any("SECRET" in v for v in probes.values()) and all(v.startswith("blocked:") or v in ("returned:null", "returned:undefined") for v in probes.values())
            elif sample.id == "window_nav":
                # A navigation the host's frame-src refuses leaves a dead frame: the supervisor then removes it (containment either way).
                child = r["child"] or {}
                ok = ok and probes.get("open") == "returned:null" and (bool(parent.get("killed")) or str(child.get("href", "")).startswith(sandbox.origin + "/page/"))
            elif sample.id == "code_exec":
                # eval/Function/import() throw; a string timer and a Worker do not throw but the browser refuses them (violations recorded)
                ok = ok and len(probes) >= 5 and all(probes.get(k, "").startswith("blocked:") for k in ("eval", "function", "dynamic_import"))                     and {"script-src", "worker-src"} <= set(parent.get("csp", []))
            elif sample.id in ("infinite_loop", "memory_bomb", "dom_bomb"):
                killed = parent.get("killed") or {}
                ok = ok and killed.get("reason") == "unresponsive" and (r["child"] or {}).get("absent") is True
            elif sample.id == "memory_creep":
                killed = parent.get("killed") or {}
                ok = ok and killed.get("reason") == "memory" and int(killed.get("detail") or 0) > HARNESS_MAX_HEAP_MB and (r["child"] or {}).get("absent") is True
            elif sample.id == "svg_script":
                ok = ok and (r["child"] or {}).get("documentTitle") != "PWNED"
            elif sample.id == "inline_injection":
                ok = ok and (r["child"] or {}).get("documentTitle") != "PWNED" and bool(parent.get("csp"))
            elif sample.id == "huge_message":
                # the structured clone of 64 MB happens before any handler: measured stall of the host, then the message is refused unparsed
                ok = ok and parent.get("rejected", {}).get("too_large", 0) >= 1 and not parent.get("killed")
                detail["host_stall_ms_for_64_MB"] = parent.get("maxGapMs")
            elif sample.id == "webrtc_exfil":
                ok = ok and probes.get("rtc", "").startswith("blocked:")
            elif sample.id == "link_hints":
                ok = ok and set(probes) >= {"dns_prefetch", "preconnect", "prefetch", "preload"}
            elif sample.id == "postmessage_spoof":
                killed = parent.get("killed") or {}
                ok = ok and killed.get("reason") == "protocol_abuse" and bool(parent.get("rejected")) and (parent.get("supervisor") or {}).get("accepted", 0) <= 25
            checks[f"{sample.id}:{flavor}"] = {"ok": bool(ok), **detail}
    direct_open = results.get("svg_direct_open")
    if direct_open:
        probe = direct_open["self"] or {}
        checks["svg_opened_as_a_document_does_not_run"] = {"ok": bool(probe and probe.get("documentTitle") != "PWNED" and probe.get("origin") == "null"
                                                                     and not [h for h in attacker.requests if h["path"].startswith("/svg_script/")]),
                                                           "document": probe, "attacker_hits": [h["path"] for h in attacker.requests if h["path"].startswith("/svg_script/")]}
    # negative controls: the same bytes WITHOUT sandbox/CSP on the host origin DO leak, proving the harness can see an escape
    for control in ("net_exfil", "storage_read", "parent_access"):
        r = results.get(f"control:{control}")
        if r is None:
            continue
        probes = probe_map(r["parent"])
        hits = [h["path"] for h in attacker.requests if h["path"].startswith(f"/control_{control}/")]
        leaked = any("SECRET" in v for v in probes.values())
        checks[f"negative_control:{control}"] = {"ok": bool(leaked or hits), "note": "the same scene without sandbox/CSP on the host origin reaches the secrets or the network",
                                                 "probes": probes, "attacker_hits": hits[:6]}
    for variant in ABLATIONS:
        for target in ("net_exfil", "storage_read", "parent_access"):
            r = results.get(f"ablation:{variant}:{target}")
            if r is None:
                continue
            probes = probe_map(r["parent"])
            hits = [h["path"] for h in attacker.requests if h["path"].startswith(f"/abl_{variant}_{target}/")]
            secrets = any("SECRET" in v for v in probes.values())
            if target == "net_exfil":
                # without the CSP the network opens; with it (noiso) it stays closed
                expected_leak = variant == "nocsp"
                ok = bool(hits) if expected_leak else not hits
            else:
                # host secrets stay unreadable in BOTH ablations: the dedicated origin and the sandbox each suffice on their own
                ok = not secrets and len(probes) >= 4
            checks[f"ablation:{variant}:{target}"] = {"ok": bool(ok), "removed": ABLATIONS[variant][1], "probes": probes, "attacker_hits": hits[:6],
                                                      "host_secret_read": secrets, "csp_violations": sorted(set((r["parent"] or {}).get("csp", [])))}
    checks["sandbox_origin_never_received_credentials"] = {"ok": not [r for r in sandbox.requests if r["cookie"] or r["authorization"] or r["referer"]],
                                                           "requests": len(sandbox.requests)}
    return checks


if __name__ == "__main__":
    raise SystemExit(main())
