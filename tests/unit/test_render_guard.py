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
process.on('uncaughtException', (e) => { console.log(JSON.stringify({crash: String(e && e.stack || e)})); process.exit(1); });
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
  const browser = cp.spawnSync(process.execPath, [process.env.ECHO, 'about:blank', '--no-proxy-server', '--no-sandbox', '--disable-setuid-sandbox',
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
    echo = root / "echo-args.cjs"
    echo.write_text("process.stdout.write(JSON.stringify(process.argv.slice(2)))", encoding="utf-8")
    env = {"PATH": str(Path(NODE).parent), "SYSTEMROOT": "C:\\Windows", "JARVIS_RENDER_DIR": str(job), "JARVIS_RENDER_RUNTIME": str(runtime),
           "JARVIS_RENDER_BROWSER": NODE, "GUARD": str(GUARD), "PINNED": str(pinned), "ECHO": str(echo)}
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


def test_the_process_sandbox_flags_are_stripped_by_default(run):
    args = run["browser_args"]
    assert "--no-sandbox" not in args and "--disable-setuid-sandbox" not in args, "Chrome keeps its process sandbox unless the user opts out"
    assert run["egress_file"]["sandbox"] is True and run["egress_file"]["guard_error"] == ""


BROWSER_PROBE = r"""
const guard = require(process.env.GUARD); const cp = require('node:child_process');
process.on('uncaughtException', (e) => { console.log(JSON.stringify({crash: String(e && e.stack || e)})); process.exit(1); });
(async () => {
  const proxy = await guard.startEgressProxy(1);
  const out = {};
  const launch = (label, command, args) => { try { const r = cp.spawnSync(command, args); out[label] = String(r.stdout); } catch (e) { out[label] = e.code; } };
  launch('ok', process.execPath, [process.env.ECHO, 'about:blank', ...JSON.parse(process.env.EXTRA || '[]')]);
  launch('unpinned_chrome', process.env.RUNTIME_CHROME, ['-e', '1']);
  launch('other_binary', process.env.OTHER_BINARY, ['-e', '1']);
  out.state = {launches: guard.state.browserLaunches, error: guard.state.guardError, flags: guard.state.unexpectedFlags, sandbox: guard.state.sandbox};
  proxy.close();
  console.log(JSON.stringify(out));
})();
"""


def browser_probe(tmp_path, *, extra=(), no_sandbox=False):
    runtime = tmp_path / "runtime"
    chrome = runtime / "node_modules" / ".remotion" / "chrome-headless-shell" / "chrome.exe"  # what Remotion downloads when it finds no browser
    other = runtime / "node_modules" / "some-package" / "tool.exe"
    for target in (chrome, other):
        target.parent.mkdir(parents=True, exist_ok=True)
        place_executable(target)
    job = tmp_path / "job"
    job.mkdir()
    script = tmp_path / "browser-probe.cjs"
    script.write_text(BROWSER_PROBE, encoding="utf-8")
    echo = tmp_path / "echo-args.cjs"
    echo.write_text("process.stdout.write(JSON.stringify(process.argv.slice(2)))", encoding="utf-8")
    env = {"PATH": str(Path(NODE).parent), "SYSTEMROOT": "C:\\Windows", "JARVIS_RENDER_DIR": str(job), "JARVIS_RENDER_RUNTIME": str(runtime),
           "JARVIS_RENDER_BROWSER": NODE, "GUARD": str(GUARD), "ECHO": str(echo), "EXTRA": json.dumps(list(extra)), "RUNTIME_CHROME": str(chrome), "OTHER_BINARY": str(other)}
    if no_sandbox:
        env["JARVIS_REMOTION_RENDER_NO_SANDBOX"] = "1"
    result = run_node(["--require", str(GUARD), str(script)], env)
    assert result.returncode == 0, result.stderr[-1500:]
    return json.loads(result.stdout.strip().splitlines()[-1]), json.loads((job / "egress.json").read_text(encoding="utf-8"))


def test_the_explicit_opt_out_keeps_the_sandbox_flags_and_says_so(tmp_path):
    out, egress = browser_probe(tmp_path, extra=["--no-sandbox", "--disable-setuid-sandbox"], no_sandbox=True)
    args = json.loads(out["ok"])
    assert "--no-sandbox" in args and "--disable-setuid-sandbox" in args and egress["sandbox"] is False
    out, egress = browser_probe(tmp_path / "default", extra=["--no-sandbox", "--disable-setuid-sandbox"])
    args = json.loads(out["ok"])
    assert "--no-sandbox" not in args and "--disable-setuid-sandbox" not in args and egress["sandbox"] is True


def test_an_argument_this_guard_does_not_know_refuses_the_launch_fail_closed(tmp_path):
    for flag in ("--disable-web-security", "--ignore-certificate-errors", "--allow-file-access-from-files", "--proxy-pac-url=http://x/pac", "--some-future-flag=1"):
        out, egress = browser_probe(tmp_path / flag.strip("-").split("=")[0], extra=[flag])
        assert out["ok"] == "EACCES", flag
        assert egress["guard_error"] == "render_guard_unexpected_args" and flag.split("=")[0] in egress["unexpected_flags"]
        assert egress["browser_launches"] == 0, "a refused launch is not counted as a launch"
    out, egress = browser_probe(tmp_path / "fine", extra=["--hide-scrollbars", "--mute-audio", "--use-gl=angle"])
    assert egress["browser_launches"] == 1 and egress["guard_error"] == "" and out["state"]["launches"] == 1


def test_only_the_chosen_browser_may_be_launched_not_a_remotion_downloaded_one(tmp_path):
    out, egress = browser_probe(tmp_path)
    assert out["unpinned_chrome"] == "EACCES", "a Chrome Headless Shell under node_modules/.remotion is not one of the pinned binaries"
    assert out["other_binary"] == "EACCES" and egress["browser_launches"] == 1
    assert {"unpinned_chrome:chrome.exe", "other_binary:tool.exe"} <= {r.replace("spawn:", "") for r in egress["refused_spawns"]} or egress["blocked_spawn"] >= 2
