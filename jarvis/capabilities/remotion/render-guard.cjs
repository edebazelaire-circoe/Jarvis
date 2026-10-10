// Garde du processus de rendu Remotion géré par Jarvis (Slice 16 ; docs/remotion-render.md).
// Chargé par `node --require <ce fichier> render-host.cjs <spec.json>`. Copié par Core dans le dossier du travail à chaque rendu (et comparé à
// l'original livré) : ce n'est PAS un fichier de la capacité installée.
//
// Pourquoi : un rendu EXÉCUTE le code de la scène dans un Chrome sans interface. Ce Chrome ne doit atteindre ni Internet, ni le réseau local,
// ni un service de la boucle locale (Core, Control Center, ai-visualizer...). Le garde agit dans le processus Node, qui est l'autre moitié :
//   1. tout `listen` TCP est forcé sur la boucle locale ;
//   2. aucune connexion TCP sortante hors boucle locale, aucun DNS hors `localhost`, aucun UDP ;
//   3. aucun processus enfant sauf une liste blanche : le service esbuild et le compositeur épinglés (sous `<runtime>/node_modules`) et LE
//      navigateur choisi par Core (`JARVIS_RENDER_BROWSER`, chemin exact). Tout autre lancement est refusé et compté ;
//   4. au lancement du navigateur, ses arguments sont RÉÉCRITS : le proxy « direct » de Remotion est remplacé par le proxy de refus ci-dessous,
//      `<-loopback>` retire l'exception implicite de la boucle locale (le navigateur ne joint donc PAS Core ni un autre service local), WebRTC
//      n'envoie plus d'UDP hors proxy, aucune résolution DNS ;
//   5. ce proxy de refus (`startEgressProxy`) ne laisse passer que `localhost|127.0.0.1:<port du serveur de rendu>` ; tout le reste est refusé
//      (403) et compté dans `egress.json` (preuve, jamais un échec silencieux).
// Ce n'est PAS un bac à sable du système : `process.binding`, un module natif ou un code qui n'est pas du JavaScript y échappent. Le code de
// la scène, lui, ne tourne pas dans ce processus : il tourne dans le navigateur, dont les arguments sont ceux de 4. Aucun secret de Jarvis
// n'existe dans l'environnement du processus (liste blanche posée par Core).
'use strict';

const fs = require('node:fs');
const net = require('node:net');
const dgram = require('node:dgram');
const dns = require('node:dns');
const http = require('node:http');
const path = require('node:path');
const childProcess = require('node:child_process');
const IS_MAIN = require('node:worker_threads').isMainThread;

const DIR = process.env.JARVIS_RENDER_DIR || '';
const RUNTIME = path.resolve(process.env.JARVIS_RENDER_RUNTIME || '');
const BROWSER = process.env.JARVIS_RENDER_BROWSER ? path.resolve(process.env.JARVIS_RENDER_BROWSER).toLowerCase() : '';
const LOOPBACK_HOSTS = new Set(['127.0.0.1', '::1', 'localhost']);
const state = { blockedConnect: 0, blockedHosts: [], blockedSpawn: 0, refusedSpawns: [], proxyDenied: 0, proxyDeniedTargets: [],
                proxyAllowed: 0, browserLaunches: 0, proxyPort: 0, allowedPort: 0 };

function writeEgress() {
  if (!DIR || !IS_MAIN) return;
  try {
    const target = path.join(DIR, 'egress.json');
    fs.writeFileSync(target + '.tmp', JSON.stringify({
      blocked_connect: state.blockedConnect, blocked_hosts: state.blockedHosts.slice(0, 10), blocked_spawn: state.blockedSpawn,
      refused_spawns: state.refusedSpawns.slice(0, 10), proxy_denied: state.proxyDenied, proxy_denied_targets: state.proxyDeniedTargets.slice(0, 20),
      proxy_allowed: state.proxyAllowed, browser_launches: state.browserLaunches, proxy_port: state.proxyPort, allowed_port: state.allowedPort }));
    fs.renameSync(target + '.tmp', target);
  } catch (_) { /* diagnostic : ne jamais faire tomber le rendu */ }
}

// ---------------------------------------------------------------------------------------------- 1. listen
function loopbackHost(host) {
  const bare = typeof host === 'string' ? host.replace(/^\[|\]$/g, '').toLowerCase() : '';
  return LOOPBACK_HOSTS.has(bare) ? host : '127.0.0.1';
}
const originalListen = net.Server.prototype.listen;
net.Server.prototype.listen = function jarvisListen(...args) {
  const first = args[0];
  if (first !== null && typeof first === 'object' && !Array.isArray(first) && typeof first.on !== 'function') {
    if (first.path === undefined && first.fd === undefined) args[0] = { ...first, host: loopbackHost(first.host) };
  } else if (typeof first === 'number' || (typeof first === 'string' && /^\d+$/.test(first))) {
    if (typeof args[1] === 'string') args[1] = loopbackHost(args[1]);
    else args.splice(1, 0, '127.0.0.1');
  } else if (first === undefined || typeof first === 'function') {
    args.unshift({ port: 0, host: '127.0.0.1' });
  }
  return originalListen.apply(this, args);
};

// ---------------------------------------------------------------------------------------------- 2. sortant
const originalConnect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function jarvisConnect(...args) {
  let options = null;
  if (Array.isArray(args[0])) options = args[0][0];
  else if (args[0] !== null && typeof args[0] === 'object') options = args[0];
  let host = 'localhost';
  let ipc = false;
  if (options) {
    if (options.path) ipc = true;
    else if (options.host) host = String(options.host);
    if (options.lookup !== undefined) options.lookup = undefined;
  } else if (typeof args[0] === 'string' && !/^\d+$/.test(args[0])) ipc = true;
  else if (typeof args[1] === 'string') host = args[1];
  const bare = host.replace(/^\[|\]$/g, '').toLowerCase();
  if (!ipc && !LOOPBACK_HOSTS.has(bare)) {
    state.blockedConnect += 1;
    if (state.blockedHosts.length < 10 && !state.blockedHosts.includes(bare)) state.blockedHosts.push(bare);
    writeEgress();
    const error = Object.assign(new Error('egress blocked by the Jarvis render guard: ' + bare), { code: 'EACCES' });
    process.nextTick(() => this.destroy(error));
    return this;
  }
  return originalConnect.apply(this, args);
};

function refuseDns(name) {
  state.blockedConnect += 1;
  if (state.blockedHosts.length < 10) state.blockedHosts.push('dns:' + String(name).slice(0, 60));
  writeEgress();
  return Object.assign(new Error('DNS refused by the Jarvis render guard'), { code: 'EACCES' });
}
for (const fn of ['lookup', 'resolve', 'resolve4', 'resolve6', 'resolveAny', 'resolveCname', 'resolveMx', 'resolveNs', 'resolveTxt', 'resolveSrv',
                  'resolvePtr', 'resolveNaptr', 'resolveSoa', 'reverse']) {
  const original = dns[fn];
  if (typeof original !== 'function') continue;
  dns[fn] = function guardedDns(name, ...rest) {
    const bare = typeof name === 'string' ? name.toLowerCase() : '';
    if (bare === 'localhost' || bare === '127.0.0.1' || bare === '::1') return original.call(this, name, ...rest);
    const callback = rest.find((item) => typeof item === 'function');
    const error = refuseDns(name);
    if (callback) { process.nextTick(callback, error); return undefined; }
    throw error;
  };
}
if (dns.promises) {
  for (const fn of Object.keys(dns.promises)) {
    const original = dns.promises[fn];
    if (typeof original !== 'function' || fn === 'Resolver' || fn.startsWith('set') || fn.startsWith('get')) continue;
    dns.promises[fn] = function guardedDnsPromise(name, ...rest) {
      const bare = typeof name === 'string' ? name.toLowerCase() : '';
      if (bare === 'localhost' || bare === '127.0.0.1' || bare === '::1') return original.call(this, name, ...rest);
      return Promise.reject(refuseDns(name));
    };
  }
}
dgram.createSocket = function refusedUdp() { state.blockedConnect += 1; writeEgress(); throw Object.assign(new Error('UDP refused by the Jarvis render guard'), { code: 'EACCES' }); };

// ---------------------------------------------------------------------------------------------- 3-4. processus enfants
function refuse(kind, what) {
  state.blockedSpawn += 1;
  if (state.refusedSpawns.length < 10) state.refusedSpawns.push(kind + ':' + String(what).split(/[\\/ ]/).pop().slice(0, 40));
  writeEgress();
  return Object.assign(new Error('refused by the Jarvis render guard: ' + kind), { code: 'EACCES' });
}
function real(file) {
  try { return fs.realpathSync.native(file).toLowerCase(); } catch (_) { return path.resolve(file).toLowerCase(); }
}
// L'arbre des paquets, résolu UNE fois (une jonction vers un autre dossier reste reconnue ; un lien posé plus tard dans un paquet ne
// fait pas sortir un exécutable de la liste : on compare le chemin réel du programme lancé).
const MODULES_REAL = real(path.join(RUNTIME, 'node_modules')) + path.sep;
function insideRuntime(file) {
  return real(file).startsWith(MODULES_REAL);
}
// Arguments que Remotion pose et que le garde remplace : ils ouvrent le réseau (proxy direct) ou ne le ferment pas.
const REPLACED_FLAGS = [/^--no-proxy-server$/, /^--proxy-server=/, /^--proxy-bypass-list=/, /^--host-resolver-rules=/, /^--remote-allow-origins=/,
                        /^--force-webrtc-ip-handling-policy=/, /^--webrtc-ip-handling-policy=/];
function rewriteBrowserArgs(args) {
  const kept = args.filter((arg) => !REPLACED_FLAGS.some((rx) => rx.test(String(arg))));
  return [...kept,
    `--proxy-server=http://127.0.0.1:${state.proxyPort}`,
    '--proxy-bypass-list=<-loopback>',
    '--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1',
    '--force-webrtc-ip-handling-policy=disable_non_proxied_udp',
    '--webrtc-ip-handling-policy=disable_non_proxied_udp',
    '--disable-background-networking', '--disable-sync', '--disable-component-update', '--no-pings'];
}
function decide(command, args) {
  const file = String(command || '');
  if (BROWSER && path.resolve(file).toLowerCase() === BROWSER) {
    if (!state.proxyPort) throw refuse('browser_before_proxy', file);
    state.browserLaunches += 1;
    writeEgress();
    return { args: rewriteBrowserArgs(args), browser: true };
  }
  if (path.isAbsolute(file) && insideRuntime(file)) return { args };
  throw refuse('spawn', file);
}
const realSpawn = childProcess.spawn;
const browserPids = new Set();
childProcess.spawn = function guardedSpawn(command, args, options) {
  const argv = Array.isArray(args) ? args : [];
  const opts = Array.isArray(args) ? options : args;
  const verdict = decide(command, argv);
  const child = realSpawn.call(this, command, verdict.args, opts);
  if (verdict.browser && child && child.pid) browserPids.add(child.pid);
  return child;
};
for (const name of ['exec', 'execSync', 'execFile', 'execFileSync', 'spawnSync', 'fork']) {
  const original = childProcess[name];
  childProcess[name] = function guardedChild(command, ...rest) {
    if (name === 'spawnSync' || name === 'execFile' || name === 'execFileSync') {
      const args = Array.isArray(rest[0]) ? rest[0] : [];
      const verdict = decide(command, args);
      if (Array.isArray(rest[0])) rest[0] = verdict.args;
      return original.call(this, command, ...rest);
    }
    // Seule exception : l'arrêt du navigateur lancé ici, sous la forme EXACTE que Remotion pose (`taskkill /pid <pid> /T /F`) et pour un
    // pid que ce processus a lui-même obtenu en lançant le navigateur.
    if (name === 'exec') {
      const match = /^taskkill \/pid (\d+) \/T \/F$/.exec(String(command));
      if (match && browserPids.has(Number(match[1]))) {
        // `exec` repasserait par `execFile` (déjà gardé) : on lance `taskkill` directement, une fois, avec le pid vérifié.
        const callback = rest.find((item) => typeof item === 'function');
        const killer = realSpawn.call(childProcess, 'taskkill', ['/pid', match[1], '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
        killer.on('close', (code) => { if (callback) callback(code === 0 ? null : Object.assign(new Error('taskkill failed'), { code })); });
        killer.on('error', (error) => { if (callback) callback(error); });
        return killer;
      }
    }
    throw refuse(name, command);
  };
}

// ---------------------------------------------------------------------------------------------- 5. proxy de refus
// Démarré par render-host.cjs AVANT le navigateur. N'accepte que `localhost|127.0.0.1:<allowedPort>` (le serveur de rendu) ; relaie en HTTP.
function startEgressProxy(allowedPort) {
  state.allowedPort = allowedPort;
  return new Promise((resolve, reject) => {
    const deny = (res, target) => {
      state.proxyDenied += 1;
      if (state.proxyDeniedTargets.length < 20 && !state.proxyDeniedTargets.includes(target)) state.proxyDeniedTargets.push(target);
      writeEgress();
      res.writeHead(403, { 'Content-Type': 'text/plain', Connection: 'close' });
      res.end('egress denied by the Jarvis render guard');
    };
    const server = http.createServer((req, res) => {
      let url;
      try { url = new URL(req.url); } catch (_) { return deny(res, String(req.url).slice(0, 80)); }
      const target = `${url.hostname}:${url.port || '80'}`.slice(0, 100);
      if (url.protocol !== 'http:' || !['localhost', '127.0.0.1'].includes(url.hostname) || Number(url.port) !== allowedPort) return deny(res, target);
      state.proxyAllowed += 1;
      const upstream = http.request({ host: '127.0.0.1', port: allowedPort, method: req.method, path: url.pathname + url.search, headers: { ...req.headers, host: `localhost:${allowedPort}` } },
        (answer) => { res.writeHead(answer.statusCode || 502, answer.headers); answer.pipe(res); });
      upstream.on('error', () => { try { res.writeHead(502); res.end(); } catch (_) { /* fermé */ } });
      req.pipe(upstream);
    });
    // CONNECT (HTTPS, WebSocket tunnel) : toujours refusé et compté.
    server.on('connect', (req, socket) => {
      state.proxyDenied += 1;
      const target = String(req.url).slice(0, 100);
      if (state.proxyDeniedTargets.length < 20 && !state.proxyDeniedTargets.includes(target)) state.proxyDeniedTargets.push(target);
      writeEgress();
      socket.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n');
    });
    server.on('connection', (socket) => socket.on('error', () => { /* le navigateur coupe : sans effet */ }));
    server.on('clientError', (_error, socket) => { try { socket.destroy(); } catch (_) { /* fermé */ } });
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      state.proxyPort = server.address().port;
      writeEgress();
      resolve({ port: state.proxyPort, close: () => server.close(), state });
    });
  });
}

module.exports = { startEgressProxy, state, writeEgress };
