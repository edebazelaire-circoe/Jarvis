"""Garde du Studio (`jarvis/capabilities/remotion/studio-guard.cjs`) exécuté par un vrai Node, sans Remotion (Slice 11).

Prouve ce que le Studio stock ne garantit pas : liaison sur la boucle locale seulement, aucune connexion sortante, CSP sur chaque
réponse, identité de lancement, activité (requêtes, WebSocket). Ignoré sans Node.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.adapters.remotion_studio_runner import SHIPPED_GUARD

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed")

SCRIPT = r"""
const http = require('node:http'); const net = require('node:net');
const out = {};
const server = http.createServer((req, res) => { res.writeHead(200, {'content-type': 'text/plain'}); res.end('app'); });
server.on('upgrade', (req, socket) => { socket.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n'); });
const lone = net.createServer(() => {});
const variants = [];
const open = (label, fn) => new Promise((resolve) => { fn(); resolve(label); });
function get(port, path) {
  return new Promise((resolve) => http.get({host: '127.0.0.1', port, path}, (res) => {
    let body = ''; res.on('data', (c) => body += c); res.on('end', () => resolve({status: res.statusCode, headers: res.headers, body}));
  }).on('error', (e) => resolve({error: e.code || e.message})));
}
server.listen(0, '0.0.0.0', async () => {
  const port = server.address().port;
  out.bound = server.address().address;
  out.health = JSON.parse((await get(port, '/__jarvis_studio__/health')).body);
  const page = await get(port, '/');
  out.csp = page.headers['content-security-policy'];
  out.body = page.body;
  // d'autres formes de listen : toutes sur la boucle locale
  const forms = {};
  await new Promise((r) => { const s = net.createServer(); s.listen(0, () => { forms.port_only = s.address().address; s.close(); r(); }); });
  await new Promise((r) => { const s = net.createServer(); s.listen({port: 0}, () => { forms.options_no_host = s.address().address; s.close(); r(); }); });
  await new Promise((r) => { const s = net.createServer(); s.listen({port: 0, host: '::'}, () => { forms.options_ipv6_any = s.address().address; s.close(); r(); }); });
  await new Promise((r) => { const s = net.createServer(); s.listen(0, '::1', () => { forms.ipv6_loopback = s.address().address; s.close(); r(); }); });
  await new Promise((r) => { const s = net.createServer(); s.listen(() => { forms.bare = s.address().address; s.close(); r(); }); });
  out.forms = forms;
  // sortie : une adresse hors boucle locale, un nom de domaine, une adresse IPv6 globale
  const attempt = (opts) => new Promise((r) => { const s = net.connect(opts); s.on('error', (e) => r(e.code || e.message)); s.on('connect', () => { s.destroy(); r('connected'); }); });
  out.egress_ip = await attempt({host: '192.0.2.1', port: 80});
  out.egress_name = await attempt({host: 'example.com', port: 80});
  out.egress_v6 = await attempt({host: '2001:db8::1', port: 80});
  out.egress_http = await new Promise((r) => http.get('http://example.com/', () => r('answered')).on('error', (e) => r(e.code || e.message)));
  out.loopback_ok = await attempt({host: '127.0.0.1', port});
  out.localhost_ok = await attempt({host: 'localhost', port});
  // un WebSocket (upgrade) ouvert puis fermé
  const sock = net.connect(port, '127.0.0.1');
  await new Promise((r) => sock.on('connect', r));
  sock.write('GET /ws HTTP/1.1\r\nHost: x\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n');
  await new Promise((r) => setTimeout(r, 300));
  out.ws_open = JSON.parse(require('node:fs').readFileSync(process.env.JARVIS_STUDIO_DIR + '/activity.json', 'utf8')).ws_open;
  sock.destroy();
  await new Promise((r) => setTimeout(r, 300));
  out.ws_closed = JSON.parse(require('node:fs').readFileSync(process.env.JARVIS_STUDIO_DIR + '/activity.json', 'utf8')).ws_open;
  console.log(JSON.stringify(out));
  process.exit(0);
});
"""


@pytest.fixture(scope="module")
def guarded(tmp_path_factory):
    folder = tmp_path_factory.mktemp("guard")
    script = tmp_path_factory.mktemp("script") / "probe.cjs"
    script.write_text(SCRIPT, encoding="utf-8")
    env = {"PATH": __import__("os").environ["PATH"], "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
           "JARVIS_STUDIO_DIR": str(folder), "JARVIS_STUDIO_LAUNCH": "launch-abc"}
    done = subprocess.run([NODE, "--require", str(SHIPPED_GUARD), str(script)], env=env, capture_output=True, text=True, timeout=60,
                          cwd=str(folder))
    assert done.returncode == 0, done.stderr[-800:]
    return json.loads(done.stdout.strip().splitlines()[-1]), folder


def test_a_server_asked_for_all_interfaces_is_bound_to_the_loopback_only(guarded):
    out, _ = guarded
    assert out["bound"] == "127.0.0.1"
    assert out["forms"] == {"port_only": "127.0.0.1", "options_no_host": "127.0.0.1", "options_ipv6_any": "127.0.0.1",
                            "ipv6_loopback": "::1", "bare": "127.0.0.1"}


def test_the_health_answer_carries_the_launch_identity_and_the_app_is_not_shadowed(guarded):
    out, _ = guarded
    assert out["health"]["ok"] is True and out["health"]["launch"] == "launch-abc" and out["health"]["pid"] > 0
    assert out["body"] == "app"


def test_every_response_carries_a_content_security_policy_that_forbids_foreign_origins(guarded):
    csp = guarded[0]["csp"]
    assert "default-src 'self'" in csp and "object-src 'none'" in csp and "frame-ancestors" not in csp
    assert "connect-src 'self' ws://127.0.0.1:*" in csp and "http://" not in csp.replace("http://127.0.0.1:*", "").replace("http://localhost:*", "")


def test_outbound_connections_off_the_loopback_are_refused_before_any_dns_or_network(guarded):
    out, folder = guarded
    assert out["egress_ip"] == out["egress_name"] == out["egress_v6"] == out["egress_http"] == "EACCES"
    assert out["loopback_ok"] == "connected" and out["localhost_ok"] == "connected"
    activity = json.loads((folder / "activity.json").read_text(encoding="utf-8"))
    assert activity["blocked_egress"] >= 4 and "example.com" in activity["blocked_hosts"] and "192.0.2.1" in activity["blocked_hosts"]


def test_open_websockets_are_counted_for_the_idle_timeout(guarded):
    out, _ = guarded
    assert out["ws_open"] == 1 and out["ws_closed"] == 0


def test_the_listening_file_names_only_loopback_servers(guarded):
    _, folder = guarded
    listening = json.loads((folder / "listening.json").read_text(encoding="utf-8"))
    assert listening["launch"] == "launch-abc" and listening["servers"]
    assert {server["host"] for server in listening["servers"]} <= {"127.0.0.1", "::1"}


def test_the_guard_file_is_plain_commonjs_without_secret_access():
    text = Path(SHIPPED_GUARD).read_text(encoding="utf-8")
    assert text.count("process.env") == 5, "only the launch identifier, directory, parent pid, idle limit and parent grace are read"
    assert "child_process" not in text


def run_guard(tmp_path, body, **env_extra):
    folder = tmp_path / "wd"
    folder.mkdir()
    script = tmp_path / "hold.cjs"
    script.write_text(body, encoding="utf-8")
    import os
    env = {"PATH": os.environ["PATH"], "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), "JARVIS_STUDIO_DIR": str(folder),
           "JARVIS_STUDIO_LAUNCH": "L1", **env_extra}
    started = __import__("time").monotonic()
    done = subprocess.run([NODE, "--require", str(SHIPPED_GUARD), str(script)], env=env, capture_output=True, text=True, timeout=40, cwd=str(folder))
    return done, folder, __import__("time").monotonic() - started


HOLD = "require('node:http').createServer(()=>{}).listen(0); setInterval(()=>{}, 1000);"


def test_the_studio_ends_itself_when_core_is_gone_so_a_killed_core_leaves_no_orphan(tmp_path):
    done, folder, seconds = run_guard(tmp_path, HOLD, JARVIS_STUDIO_PARENT="2000000000", JARVIS_STUDIO_PARENT_GRACE_S="2")
    assert done.returncode == 0 and seconds < 20
    assert json.loads((folder / "exit.json").read_text(encoding="utf-8"))["reason"] == "parent_gone"


def test_the_studio_ends_itself_after_its_idle_limit_even_without_core(tmp_path):
    done, folder, seconds = run_guard(tmp_path, HOLD, JARVIS_STUDIO_IDLE_S="2")
    assert done.returncode == 0 and seconds < 20
    assert json.loads((folder / "exit.json").read_text(encoding="utf-8"))["reason"] == "idle"


def test_a_living_parent_keeps_the_studio_up(tmp_path):
    import os
    body = HOLD + " setTimeout(()=>process.exit(7), 4000);"
    done, folder, _ = run_guard(tmp_path, body, JARVIS_STUDIO_PARENT=str(os.getpid()), JARVIS_STUDIO_PARENT_GRACE_S="1")
    assert done.returncode == 7 and not (folder / "exit.json").exists()
