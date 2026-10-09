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
  // processus enfants, DNS, UDP : refusés (l'API du Studio sait installer un paquet, ouvrir un éditeur, lancer un agent)
  const cp = require('node:child_process');
  try { cp.spawn(process.execPath, ['-v']); out.spawn = 'allowed'; } catch (e) { out.spawn = e.code; }
  try { cp.execSync('echo hi'); out.exec = 'allowed'; } catch (e) { out.exec = e.code; }
  try { cp.fork('x.js'); out.fork = 'allowed'; } catch (e) { out.fork = e.code; }
  out.dns = await new Promise((r) => require('node:dns').lookup('example.com', (e) => r(e ? e.code : 'resolved')));
  out.dns_local = await new Promise((r) => require('node:dns').lookup('localhost', (e) => r(e ? e.code : 'resolved')));
  out.resolve = await new Promise((r) => require('node:dns').resolve4('example.com', (e) => r(e ? e.code : 'resolved')));
  try { require('node:dgram').createSocket('udp4'); out.udp = 'allowed'; } catch (e) { out.udp = e.code; }
  // options de connexion : une fonction `lookup` fournie ne contourne rien ; dns.promises, dgram.Socket, Worker
  out.lookup_option = await new Promise((r) => { const s = net.connect({host: 'localhost', port, lookup: (h, o, cb) => cb(null, '192.0.2.1', 4)});
    s.on('error', (e) => r(e.code || e.message)); s.on('connect', () => { s.destroy(); r('connected-via-loopback'); }); });
  out.promises_lookup = await require('node:dns').promises.lookup('example.com').then(() => 'resolved', (e) => e.code);
  out.promises_resolve = await require('node:dns').promises.resolve4('example.com').then(() => 'resolved', (e) => e.code);
  out.resolver = await new Promise((r) => { try { new (require('node:dns').Resolver)().resolve4('example.com', (e) => r(e ? e.code : 'resolved')); } catch (e) { r(e.code); } });
  try { new (require('node:dgram').Socket)('udp4'); out.dgram_socket = 'allowed'; } catch (e) { out.dgram_socket = e.code; }
  out.worker = await new Promise((r) => {
    const { Worker } = require('node:worker_threads');
    const w = new Worker(`const net=require('node:net');const s=net.connect({host:'192.0.2.1',port:80});s.on('error',e=>require('node:worker_threads').parentPort.postMessage(e.code));s.on('connect',()=>require('node:worker_threads').parentPort.postMessage('connected'));`, { eval: true });
    w.on('message', (m) => { r(m); w.terminate(); }); w.on('error', (e) => r('worker-error:' + e.message));
  });
  // Host étranger (DNS rebinding) et requêtes modifiantes d'une autre origine
  const raw = (headers, method = 'GET', url = '/') => new Promise((r) => { const q = http.request({host: '127.0.0.1', port, method, path: url, headers, agent: false}, (res) => { res.resume(); res.on('end', () => r(res.statusCode)); }); q.on('error', (e) => r(e.code)); q.end('x'); });
  out.host_rebinding = await raw({host: 'evil.example:' + port});
  out.host_ok = await raw({host: '127.0.0.1:' + port});
  out.post_foreign_origin = await raw({host: '127.0.0.1:' + port, origin: 'http://127.0.0.1:1', 'content-type': 'text/plain'}, 'POST');
  out.post_same_origin = await raw({host: '127.0.0.1:' + port, origin: 'http://127.0.0.1:' + port}, 'POST');
  out.post_no_origin = await raw({host: '127.0.0.1:' + port}, 'POST');
  out.post_cross_site = await raw({host: '127.0.0.1:' + port, 'sec-fetch-site': 'cross-site'}, 'POST');
  out.get_foreign_origin_read = await raw({host: '127.0.0.1:' + port, origin: 'http://127.0.0.1:1'}, 'GET');
  out.ws_foreign_origin = await new Promise((r) => { const s = net.connect(port, '127.0.0.1'); let data = '';
    s.on('connect', () => s.write('GET /ws HTTP/1.1\r\nHost: 127.0.0.1:' + port + '\r\nOrigin: http://127.0.0.1:1\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n'));
    s.on('data', (d) => { data += d; }); s.on('close', () => r(data.split('\r\n')[0])); setTimeout(() => { s.destroy(); }, 1500); });
  // un WebSocket (upgrade) ouvert puis fermé
  const sock = net.connect(port, '127.0.0.1');
  await new Promise((r) => sock.on('connect', r));
  sock.write('GET /ws HTTP/1.1\r\nHost: 127.0.0.1:' + port + '\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n');
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
    assert "connect-src 'self';" in csp, "the page may only talk to its own server: never the Control Center or another local service"
    assert "127.0.0.1" not in csp and "localhost" not in csp and "ws:" not in csp and "http:" not in csp and "*" not in csp


def test_outbound_connections_off_the_loopback_are_refused_before_any_dns_or_network(guarded):
    out, folder = guarded
    assert out["egress_ip"] == out["egress_name"] == out["egress_v6"] == out["egress_http"] == "EACCES"
    assert out["loopback_ok"] == "connected" and out["localhost_ok"] == "connected"
    activity = json.loads((folder / "activity.json").read_text(encoding="utf-8"))
    assert activity["blocked_egress"] >= 4 and "example.com" in activity["blocked_hosts"] and "192.0.2.1" in activity["blocked_hosts"]


def test_child_processes_dns_and_udp_are_refused_because_the_studio_api_can_launch_installers_and_editors(guarded):
    out, folder = guarded
    assert out["spawn"] == out["exec"] == out["fork"] == out["udp"] == out["dns"] == out["resolve"] == "EACCES"
    assert out["dns_local"] == "resolved", "localhost still resolves"
    activity = json.loads((folder / "activity.json").read_text(encoding="utf-8"))
    assert activity["blocked_spawn"] >= 6
    assert {"child_process.spawn", "child_process.execSync", "dns.lookup", "dgram.createSocket"} <= {entry.split(":")[0] for entry in activity["refused"]}


def test_connection_options_promises_resolvers_udp_sockets_and_workers_cannot_bypass_the_guard(guarded):
    out, _ = guarded
    assert out["lookup_option"] == "connected-via-loopback", "a caller-supplied lookup is ignored: localhost stays the loopback"
    assert out["promises_lookup"] == out["promises_resolve"] == out["resolver"] == out["dgram_socket"] == "EACCES"
    assert out["worker"] == "EACCES", "a Worker thread gets the guard too"


def test_foreign_hosts_and_foreign_origins_are_refused_by_the_studio_itself(guarded):
    out, folder = guarded
    assert out["host_ok"] == 200 and out["host_rebinding"] == 403
    assert out["post_foreign_origin"] == 403 and out["post_cross_site"] == 403
    assert out["post_same_origin"] == 200 and out["post_no_origin"] == 200
    assert out["get_foreign_origin_read"] == 200, "a plain read is not a state change (the CSP and CORS keep it blind)"
    assert out["ws_foreign_origin"].startswith("HTTP/1.1 403")
    assert json.loads((folder / "activity.json").read_text(encoding="utf-8"))["blocked_requests"] >= 4


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
    assert "child_process" in text and text.count("process.env") == 4, "only the launch identifier, directory, idle limit and parent grace are read"
    assert "spawn(" not in text.replace("childProcess[name]", "")


def run_guard(tmp_path, body, parent=None, **env_extra):
    """Lance `body` sous le garde. `parent` : contenu de `parent.json` (dict, ou None pour l'absence), écrit avant le lancement."""

    folder = tmp_path / "wd"
    folder.mkdir()
    if parent is not None:
        (folder / "parent.json").write_text(json.dumps(parent), encoding="utf-8")
    script = tmp_path / "hold.cjs"
    script.write_text(body, encoding="utf-8")
    import os
    env = {"PATH": os.environ["PATH"], "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), "JARVIS_STUDIO_DIR": str(folder),
           "JARVIS_STUDIO_LAUNCH": "L1", **env_extra}
    started = __import__("time").monotonic()
    done = subprocess.run([NODE, "--require", str(SHIPPED_GUARD), str(script)], env=env, capture_output=True, text=True, timeout=60, cwd=str(folder))
    return done, folder, __import__("time").monotonic() - started


HOLD = "require('node:http').createServer(()=>{}).listen(0); setInterval(()=>{}, 1000);"


def me():
    """`{pid, created}` de ce processus de test, exactement comme `RemotionStudioRunner.bind_parent` l'écrit."""

    import os
    from jarvis.adapters import process_tree
    pid, _, created = process_tree.make_process_ref(os.getpid()).partition(":")
    return {"pid": os.getpid(), "created": created}


def test_the_studio_ends_itself_when_core_is_gone_so_a_killed_core_leaves_no_orphan(tmp_path):
    done, folder, seconds = run_guard(tmp_path, HOLD, parent={"pid": 2000000000, "created": "1"}, JARVIS_STUDIO_PARENT_GRACE_S="2")
    assert done.returncode == 0 and seconds < 30
    assert json.loads((folder / "exit.json").read_text(encoding="utf-8"))["reason"] == "parent_gone"


def test_a_missing_parent_declaration_counts_as_a_gone_parent(tmp_path):
    done, folder, _ = run_guard(tmp_path, HOLD, parent=None, JARVIS_STUDIO_PARENT_GRACE_S="2")
    assert done.returncode == 0 and json.loads((folder / "exit.json").read_text(encoding="utf-8"))["reason"] == "parent_gone"


def test_the_studio_ends_itself_after_its_idle_limit_even_without_core(tmp_path):
    done, folder, seconds = run_guard(tmp_path, HOLD, parent=me(), JARVIS_STUDIO_IDLE_S="2")
    assert done.returncode == 0 and seconds < 30
    assert json.loads((folder / "exit.json").read_text(encoding="utf-8"))["reason"] == "idle"


def test_a_living_parent_with_the_declared_identity_keeps_the_studio_up(tmp_path):
    body = HOLD + " setTimeout(()=>process.exit(7), 6000);"
    done, folder, _ = run_guard(tmp_path, body, parent=me(), JARVIS_STUDIO_PARENT_GRACE_S="1")
    assert done.returncode == 7 and not (folder / "exit.json").exists()


def test_a_reused_pid_with_another_creation_time_counts_as_a_dead_parent(tmp_path):
    """Le pid existe (c'est ce test), mais l'heure de création déclarée n'est pas la sienne : ce n'est plus ce Core."""

    declared = {**me(), "created": "9" + me()["created"][1:] if me()["created"][:1] != "9" else "8" + me()["created"][1:]}
    done, folder, seconds = run_guard(tmp_path, HOLD, parent=declared, JARVIS_STUDIO_PARENT_GRACE_S="2")
    assert done.returncode == 0 and seconds < 40
    assert json.loads((folder / "exit.json").read_text(encoding="utf-8"))["reason"] == "parent_gone"


def test_a_new_core_that_adopts_the_studio_rewrites_the_parent_and_the_studio_outlives_the_old_grace(tmp_path):
    """B3 : le Core d'origine est mort (pid inexistant) ; un Core qui adopte réécrit `parent.json` ; le Studio survit au délai de grâce."""

    mine = me()
    body = (HOLD + f" setTimeout(()=>require('node:fs').writeFileSync(process.env.JARVIS_STUDIO_DIR+'/parent.json', JSON.stringify({json.dumps(mine)})), 1500);"
            " setTimeout(()=>process.exit(7), 9000);")
    done, folder, _ = run_guard(tmp_path, body, parent={"pid": 2000000000, "created": "1"}, JARVIS_STUDIO_PARENT_GRACE_S="4")
    assert done.returncode == 7 and not (folder / "exit.json").exists(), "adopted before the 4 s grace ended: it must still be running at 9 s"


def test_only_the_pinned_esbuild_binary_may_be_started_by_the_studio(tmp_path):
    """Le chargeur de TSX du Studio démarre `esbuild` (sous `runtime/node_modules`) : seul ce binaire passe ; une copie ailleurs, non."""

    import os
    runtime = tmp_path / "runtime"
    (runtime / "studio").mkdir(parents=True)
    (runtime / "node_modules" / "@esbuild" / "p").mkdir(parents=True)
    (runtime / "elsewhere").mkdir()
    suffix = ".exe" if os.name == "nt" else ""
    pinned, stray = runtime / "node_modules" / "@esbuild" / "p" / f"esbuild{suffix}", runtime / "elsewhere" / f"esbuild{suffix}"
    shutil.copyfile(NODE, pinned)
    shutil.copyfile(NODE, stray)
    os.chmod(pinned, 0o755)
    os.chmod(stray, 0o755)
    shutil.copyfile(SHIPPED_GUARD, runtime / "studio" / "studio-guard.cjs")
    script = tmp_path / "probe.cjs"
    script.write_text(f"""
      const cp=require('node:child_process');const out={{}};
      const run=(label,exe)=>{{try{{const c=cp.spawn(exe,['-v']);c.on('error',()=>{{}});out[label]='started'}}catch(e){{out[label]=e.code}}}};
      run('pinned',{json.dumps(str(pinned))}); run('stray',{json.dumps(str(stray))}); run('relative_escape',{json.dumps(str(runtime / 'node_modules' / '..' / 'elsewhere' / ('esbuild' + suffix)))});
      setTimeout(()=>{{console.log(JSON.stringify(out));process.exit(0)}},500);""", encoding="utf-8")
    env = {"PATH": os.environ["PATH"], "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), "JARVIS_STUDIO_DIR": str(runtime / "studio"), "JARVIS_STUDIO_LAUNCH": "x"}
    done = subprocess.run([NODE, "--require", str(runtime / "studio" / "studio-guard.cjs"), str(script)], env=env, capture_output=True, text=True, timeout=60)
    assert json.loads(done.stdout.strip().splitlines()[-1]) == {"pinned": "started", "stray": "EACCES", "relative_escape": "EACCES"}, done.stderr[-400:]
