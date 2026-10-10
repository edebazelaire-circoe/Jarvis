"""Garde du processus de rendu (`jarvis/capabilities/remotion/render-guard.cjs`) exécuté par un vrai Node, sans Remotion (Slice 16).

Prouve : écoute sur la boucle locale seulement ; aucune connexion TCP sortante, aucun DNS, aucun UDP ; aucun processus enfant hors liste
blanche (paquets épinglés et navigateur choisi) ; arguments du navigateur RÉÉCRITS (proxy de refus, `<-loopback>`, WebRTC sans UDP) ;
proxy de refus qui ne laisse passer que le serveur de rendu et COMPTE le reste dans `egress.json`. Ignoré sans Node.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
GUARD = Path(__file__).resolve().parents[2] / "jarvis" / "capabilities" / "remotion" / "render-guard.cjs"

SCRIPT = r"""
const guard = require(process.env.GUARD);
const http = require('node:http'); const net = require('node:net'); const cp = require('node:child_process');
const dns = require('node:dns'); const dgram = require('node:dgram');
const out = {};
const attempt = (opts) => new Promise((r) => { const s = net.connect(opts); s.on('error', (e) => r(e.code || e.message)); s.on('connect', () => { s.destroy(); r('connected'); }); });
const ask = (port, path, method) => new Promise((resolve) => {
  const req = http.request({host: '127.0.0.1', port, path, method: method || 'GET', headers: {host: 'x'}}, (res) => { let b = ''; res.on('data', (c) => b += c); res.on('end', () => resolve({status: res.statusCode, body: b})); });
  req.on('error', (e) => resolve({error: e.code || e.message})); req.end();
});
(async () => {
  // 1. listen: every form lands on the loopback
  const forms = {};
  await new Promise((r) => { const s = net.createServer(); s.listen(0, '0.0.0.0', () => { forms.any = s.address().address; s.close(); r(); }); });
  await new Promise((r) => { const s = net.createServer(); s.listen({port: 0}, () => { forms.options = s.address().address; s.close(); r(); }); });
  await new Promise((r) => { const s = net.createServer(); s.listen(() => { forms.bare = s.address().address; s.close(); r(); }); });
  out.forms = forms;
  // 2. egress: addresses, names, IPv6; loopback works
  const server = http.createServer((req, res) => { res.end('render-server:' + req.url + ':' + req.headers.host); });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const allowed = server.address().port;
  out.egress = [await attempt({host: '192.0.2.1', port: 80}), await attempt({host: 'example.com', port: 80}), await attempt({host: '2001:db8::1', port: 80})];
  out.loopback = [await attempt({host: '127.0.0.1', port: allowed}), await attempt({host: 'localhost', port: allowed})];
  out.dns = await new Promise((r) => dns.lookup('example.com', (e) => r(e && e.code)));
  out.dns_promise = await dns.promises.lookup('example.com').then(() => 'resolved', (e) => e.code);
  out.dns_localhost = await new Promise((r) => dns.lookup('localhost', (e, a) => r(e ? e.code : 'ok')));
  try { dgram.createSocket('udp4'); out.udp = 'allowed'; } catch (e) { out.udp = e.code; }
  // 3. children: nothing but the pinned packages and the chosen browser
  for (const [label, fn] of Object.entries({
    spawn_node: () => cp.spawn(process.execPath, ['-v']), exec: () => cp.exec('echo hi'), execSync: () => cp.execSync('echo hi'),
    spawnSync_node: () => cp.spawnSync(process.execPath, ['-v']), fork: () => cp.fork('x.js'), execFile_cmd: () => cp.execFile('cmd', ['/c', 'echo']),
    taskkill_unknown_pid: () => cp.exec('taskkill /pid 99999 /T /F'), taskkill_shell: () => cp.exec('taskkill /pid 1 /T /F & echo x')})) {
    try { fn(); out[label] = 'allowed'; } catch (e) { out[label] = e.code; }
  }
  // the pinned package tree is allowed (a real file inside RUNTIME/node_modules)
  try { const p = cp.spawnSync(process.env.PINNED, ['-e', 'process.stdout.write("pinned-ok")']); out.pinned = String(p.stdout); } catch (e) { out.pinned = e.code; }
  // 4. the browser: arguments rewritten
  const proxy = await guard.startEgressProxy(allowed);
  const browser = cp.spawnSync(process.execPath, ['-e', 'process.stdout.write(JSON.stringify(process.argv.slice(1)))', 'about:blank', '--no-proxy-server',
    "--proxy-server='direct://'", '--proxy-bypass-list=*', '--user-data-dir=X', '--host-resolver-rules=MAP * 1.2.3.4', '--headless=new']);
  out.browser_args = JSON.parse(String(browser.stdout));
  // 5. the denial proxy: only the render server passes; everything else is refused AND counted
  out.proxy_allowed = await ask(proxy.port, 'http://localhost:' + allowed + '/frame?x=1');
  out.proxy_other_port = await ask(proxy.port, 'http://127.0.0.1:1/other');
  out.proxy_external = await ask(proxy.port, 'http://example.com/leak');
  out.proxy_https = await new Promise((r) => { const req = http.request({host: '127.0.0.1', port: proxy.port, method: 'CONNECT', path: 'example.com:443'}); req.on('connect', (res) => r(res.statusCode)); req.on('error', (e) => r(e.code)); req.end(); });
  out.proxy_garbage = await ask(proxy.port, '/relative-not-a-proxy-request');
  out.state = {denied: guard.state.proxyDenied, allowed: guard.state.proxyAllowed, targets: guard.state.proxyDeniedTargets};
  proxy.close(); server.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.log(JSON.stringify({crash: String(e && e.stack || e)})); });
"""


def run_node(argv: list[str], env: dict, timeout: int = 120) -> subprocess.CompletedProcess:
    """`node ...` retried once or twice when Windows answers « access denied » to the launch itself (antivirus scanning a fresh file)."""

    for attempt in range(3):
        try:
            return subprocess.run([NODE, *argv], capture_output=True, text=True, timeout=timeout, env=env, check=False)
        except PermissionError:
            if attempt == 2:
                raise
            time.sleep(2)
    raise AssertionError("unreachable")


def place_executable(target: Path) -> None:
    """A real executable under the fake `node_modules`: a hard link (no 80 MB copy), else a copy retried once or twice (an antivirus may hold the file)."""

    try:
        os.link(NODE, target)
    except OSError:
        for attempt in range(3):
            try:
                shutil.copyfile(NODE, target)
                break
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(1.5)
    target.chmod(0o755)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    root = tmp_path_factory.mktemp("render-guard")
    runtime = root / "runtime"
    pinned_dir = runtime / "node_modules" / "@remotion" / "compositor-test"
    pinned_dir.mkdir(parents=True)
    pinned = pinned_dir / ("tool.exe" if sys.platform == "win32" else "tool")
    place_executable(pinned)
    job = root / "job"
    job.mkdir()
    env = {"PATH": str(Path(NODE).parent), "SYSTEMROOT": "C:\\Windows", "JARVIS_RENDER_DIR": str(job), "JARVIS_RENDER_RUNTIME": str(runtime),
           "JARVIS_RENDER_BROWSER": NODE, "GUARD": str(GUARD), "PINNED": str(pinned)}
    script = root / "probe.cjs"  # a file, not `-e`: a long inline script full of "taskkill"/"dgram" is what antivirus heuristics dislike
    script.write_text(SCRIPT, encoding="utf-8")
    result = run_node(["--require", str(GUARD), str(script)], env)
    assert result.returncode == 0, result.stderr[-1500:]
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert "crash" not in out, out
    out["egress_file"] = json.loads((job / "egress.json").read_text(encoding="utf-8"))
    return out


def test_every_form_of_listen_lands_on_the_loopback(run):
    assert set(run["forms"].values()) == {"127.0.0.1"}


def test_nothing_leaves_the_machine_and_every_refusal_is_counted(run):
    assert run["egress"] == ["EACCES", "EACCES", "EACCES"] and run["loopback"] == ["connected", "connected"]
    assert run["dns"] == "EACCES" and run["dns_promise"] == "EACCES" and run["dns_localhost"] == "ok" and run["udp"] == "EACCES"
    assert run["egress_file"]["blocked_connect"] >= 5 and "192.0.2.1" in run["egress_file"]["blocked_hosts"]


def test_no_child_process_except_the_pinned_tree_and_the_chosen_browser(run):
    for label in ("spawn_node", "exec", "execSync", "spawnSync_node", "fork", "execFile_cmd", "taskkill_unknown_pid", "taskkill_shell"):
        assert run[label] == "EACCES", label
    assert run["pinned"] == "pinned-ok"
    assert run["egress_file"]["blocked_spawn"] >= 8 and run["egress_file"]["browser_launches"] == 1


def test_the_browser_arguments_are_rewritten_so_that_nothing_reaches_the_network(run):
    args = run["browser_args"]
    assert "--no-proxy-server" not in args and "--proxy-server='direct://'" not in args and "--proxy-bypass-list=*" not in args
    assert "--host-resolver-rules=MAP * 1.2.3.4" not in args  # Remotion's own value is replaced, not stacked
    assert f"--proxy-server=http://127.0.0.1:{run['egress_file']['proxy_port']}" in args and "--proxy-bypass-list=<-loopback>" in args
    assert "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1" in args
    assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in args and "--webrtc-ip-handling-policy=disable_non_proxied_udp" in args
    assert "--user-data-dir=X" in args and "--headless=new" in args and "about:blank" in args  # the rest is untouched


def test_the_denial_proxy_lets_only_the_render_server_through_and_counts_the_rest(run):
    allowed = run["proxy_allowed"]
    assert allowed["status"] == 200 and allowed["body"].startswith("render-server:/frame?x=1:localhost:")
    for label in ("proxy_other_port", "proxy_external", "proxy_garbage"):
        assert run[label]["status"] == 403 and "denied" in run[label]["body"], label
    assert run["proxy_https"] == 403
    assert run["state"]["allowed"] == 1 and run["state"]["denied"] == 4
    assert {"127.0.0.1:1", "example.com:80", "example.com:443"} <= set(run["state"]["targets"])
    assert run["egress_file"]["proxy_denied"] == 4 and run["egress_file"]["proxy_allowed"] == 1


def test_the_browser_cannot_start_before_the_denial_proxy_exists(tmp_path):
    env = {"PATH": str(Path(NODE).parent), "SYSTEMROOT": "C:\\Windows", "JARVIS_RENDER_DIR": str(tmp_path), "JARVIS_RENDER_RUNTIME": str(tmp_path),
           "JARVIS_RENDER_BROWSER": NODE}
    script = "const cp=require('node:child_process');try{cp.spawn(process.execPath,['-v']);console.log('started')}catch(e){console.log(e.code)}"
    result = run_node(["--require", str(GUARD), "-e", script], env, 60)
    assert result.stdout.strip() == "EACCES"
