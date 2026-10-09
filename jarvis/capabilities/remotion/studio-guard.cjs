// Garde de l'éventuel Remotion Studio géré par Jarvis (Slice 11 ; docs/remotion-studio.md).
// Chargé par `node --require <ce fichier> .../remotion-cli.js studio ...`. Copié par Core dans le dossier du Studio à chaque
// ouverture (et comparé à l'original livré) : ce n'est PAS un fichier de la capacité installée (aucune empreinte d'installation).
//
// Pourquoi : le Studio stock lie son serveur à 0.0.0.0 / :: (tout le réseau local), son processus Node peut ouvrir n'importe
// quelle connexion, et son API (même origine que la scène qui s'y exécute) sait lancer un gestionnaire de paquets, un éditeur,
// un terminal, un agent. Ce garde, dans le processus du Studio lui-même :
//   1. force tout `listen` TCP sur la boucle locale (127.0.0.1 / ::1) ;
//   2. refuse toute connexion TCP sortante hors boucle locale (l'option `lookup` d'une connexion est ignorée) ;
//   2b. refuse tout processus enfant (`child_process`) sauf le service esbuild épinglé, toute résolution DNS hors boucle locale
//       (`dns`, `dns.promises`, `Resolver`) et tout UDP (`dgram.createSocket`, `dgram.Socket`) ; les `Worker` reçoivent ce garde ;
//   3. pose une Content-Security-Policy sur chaque réponse HTTP (`connect-src 'self'` : la page ne parle qu'à son propre serveur,
//      jamais au Control Center ni à un autre service local) ;
//   3b. refuse une requête dont l'en-tête `Host` n'est pas la boucle locale (DNS rebinding) et toute requête modifiante ou
//       WebSocket dont l'`Origin` n'est pas le Studio lui-même ;
//   4. répond à `GET /__jarvis_studio__/health` (pid + identifiant de lancement) et écrit `listening.json` ;
//   5. tient `activity.json` à jour (dernière requête, WebSocket ouverts, refus) pour le délai d'inactivité de Core ;
//   6. se TERMINE seul (jamais d'orphelin) si le Core déclaré dans `parent.json` (pid ET heure de création, relu à chaque passage :
//      un nouveau Core qui adopte le Studio le réécrit) a disparu depuis plus de 60 s, ou après le délai d'inactivité donné.
// Ce n'est PAS un bac à sable du système : `process.binding`, un module natif ou un code qui n'est pas du JavaScript y échappent.
'use strict';

const fs = require('node:fs');
const net = require('node:net');
const http = require('node:http');
const path = require('node:path');
const childProcess = require('node:child_process');
const IS_MAIN = require('node:worker_threads').isMainThread;  // un Worker reçoit les restrictions, jamais les fichiers d'état ni la veille

const DIR = process.env.JARVIS_STUDIO_DIR || '';
const LAUNCH = process.env.JARVIS_STUDIO_LAUNCH || '';
const IDLE_MS = Number.parseFloat(process.env.JARVIS_STUDIO_IDLE_S || '0') * 1000;
const PARENT_GRACE_MS = Number.parseFloat(process.env.JARVIS_STUDIO_PARENT_GRACE_S || '60') * 1000;
const LOOPBACK_HOSTS = new Set(['127.0.0.1', '::1', 'localhost']);
const HEALTH_PATH = '/__jarvis_studio__/health';
const state = { listening: [], blocked: 0, blockedHosts: [], requests: 0, ws: 0, last: Date.now(), blockedSpawn: 0, blockedRequests: 0 };
const refusedSpawns = [];
// Référence privée, prise AVANT tout remplacement : seule la vérification d'identité du parent (commande fixe) s'en sert.
const realExecFile = childProcess.execFile;

function writeJson(name, value) {
  if (!DIR || !IS_MAIN) return;
  try {
    const target = path.join(DIR, name);
    fs.writeFileSync(target + '.tmp', JSON.stringify(value));
    fs.renameSync(target + '.tmp', target);
  } catch (_) { /* écriture de diagnostic : ne jamais faire tomber le Studio */ }
}

let lastActivityWrite = 0;
function writeActivity(force) {
  const now = Date.now();
  if (!force && now - lastActivityWrite < 1000) return;
  lastActivityWrite = now;
  writeJson('activity.json', { launch: LAUNCH, pid: process.pid, last_ms: state.last, requests: state.requests, ws_open: state.ws,
                               blocked_egress: state.blocked, blocked_hosts: state.blockedHosts.slice(0, 10),
                               blocked_spawn: state.blockedSpawn, refused: refusedSpawns.slice(0, 10), blocked_requests: state.blockedRequests });
}

function refuse(kind, what) {
  state.blockedSpawn += 1;
  if (refusedSpawns.length < 10) refusedSpawns.push(kind + ':' + String(what).split(/[\\/ ]/).pop().slice(0, 40));
  writeActivity(true);
  return Object.assign(new Error('refused by the Jarvis Studio guard: ' + kind), { code: 'EACCES' });
}

// ---------------------------------------------------------------------------------------------- 1. listen : boucle locale
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
  this.once('listening', () => {
    const address = this.address();
    if (address && typeof address === 'object') {
      state.listening.push({ host: address.address, port: address.port, family: address.family });
      writeJson('listening.json', { launch: LAUNCH, pid: process.pid, servers: state.listening });
    }
  });
  return originalListen.apply(this, args);
};

// ---------------------------------------------------------------------------------------------- 2. connexions sortantes
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
    // Une fonction `lookup` fournie par l'appelant pourrait résoudre « localhost » vers une adresse extérieure : ignorée.
    if (options.lookup !== undefined) options.lookup = undefined;
  } else if (typeof args[0] === 'string' && !/^\d+$/.test(args[0])) ipc = true;
  else if (typeof args[1] === 'string') host = args[1];
  const bare = host.replace(/^\[|\]$/g, '').toLowerCase();
  if (!ipc && !LOOPBACK_HOSTS.has(bare)) {
    state.blocked += 1;
    if (state.blockedHosts.length < 10 && !state.blockedHosts.includes(bare)) state.blockedHosts.push(bare);
    writeActivity(true);
    const error = Object.assign(new Error('egress blocked by the Jarvis Studio guard: ' + bare), { code: 'EACCES' });
    process.nextTick(() => this.destroy(error));
    return this;
  }
  return originalConnect.apply(this, args);
};

// ---------------------------------------------------------------------------------------------- 2b. enfants, DNS, UDP, Worker
// Le SEUL enfant dont le Studio a besoin : le service esbuild (binaire épinglé du verrou, sous `runtime/node_modules`) que son
// chargeur de TSX démarre. Tout autre lancement (gestionnaire de paquets, éditeur, terminal, agent, powershell...) est refusé.
const MODULES = path.resolve(__dirname, '..', 'node_modules').toLowerCase() + path.sep;
function isPinnedEsbuild(command) {
  try {
    const full = path.resolve(String(command)).toLowerCase();
    return full.startsWith(MODULES) && /^esbuild(\.exe)?$/.test(path.basename(full));
  } catch (_) { return false; }
}
for (const name of ['spawn', 'spawnSync', 'exec', 'execSync', 'execFile', 'execFileSync', 'fork']) {
  const original = childProcess[name];
  if (typeof original !== 'function') continue;
  childProcess[name] = function jarvisRefusedChild(command, ...rest) {
    if (name === 'spawn' && isPinnedEsbuild(command)) return original.call(this, command, ...rest);
    // Un échec que le Studio sait déjà montrer (`git` absent, éditeur introuvable) : jamais un processus de plus.
    throw refuse('child_process.' + name, command);
  };
}

const dns = require('node:dns');
const isLocalName = (host) => LOOPBACK_HOSTS.has(String(host).replace(/^\[|\]$/g, '').toLowerCase());
const originalLookup = dns.lookup;
dns.lookup = function jarvisLookup(host, ...rest) {
  if (isLocalName(host) || host === '' || host === undefined) return originalLookup.call(this, host, ...rest);
  const callback = rest[rest.length - 1];
  const error = refuse('dns.lookup', host);
  if (typeof callback === 'function') { process.nextTick(callback, error); return {}; }
  throw error;
};
const RESOLVERS = ['resolve', 'resolve4', 'resolve6', 'resolveAny', 'resolveCname', 'resolveMx', 'resolveNs', 'resolveSrv', 'resolveTxt',
                   'resolveCaa', 'resolveNaptr', 'resolvePtr', 'resolveSoa', 'reverse'];
function refuseResolvers(target, label) {
  for (const name of RESOLVERS) {
    if (typeof target[name] !== 'function') continue;
    target[name] = function jarvisRefusedResolve(host, ...rest) {
      const callback = rest[rest.length - 1];
      const error = refuse(label + '.' + name, host);
      if (typeof callback === 'function') { process.nextTick(callback, error); return; }
      throw error;
    };
  }
}
refuseResolvers(dns, 'dns');
if (dns.Resolver) refuseResolvers(dns.Resolver.prototype, 'dns.Resolver');
if (dns.promises) {
  const originalPromiseLookup = dns.promises.lookup;
  dns.promises.lookup = function jarvisPromiseLookup(host, ...rest) {
    if (isLocalName(host) || host === '' || host === undefined) return originalPromiseLookup.call(this, host, ...rest);
    return Promise.reject(refuse('dns.promises.lookup', host));
  };
  for (const name of RESOLVERS) {
    if (typeof dns.promises[name] !== 'function') continue;
    dns.promises[name] = function jarvisRefusedPromiseResolve(host) { return Promise.reject(refuse('dns.promises.' + name, host)); };
  }
  if (dns.promises.Resolver) {
    for (const name of RESOLVERS) {
      if (typeof dns.promises.Resolver.prototype[name] !== 'function') continue;
      dns.promises.Resolver.prototype[name] = function jarvisRefusedPromiseResolverMethod(host) { return Promise.reject(refuse('dns.promises.Resolver.' + name, host)); };
    }
  }
}
const dgram = require('node:dgram');
dgram.createSocket = function jarvisRefusedUdp() { throw refuse('dgram.createSocket', 'udp'); };
dgram.Socket = function jarvisRefusedUdpSocket() { throw refuse('dgram.Socket', 'udp'); };

// Un Worker recharge Node : sans ce garde, il aurait ses propres `net`, `dns` et `child_process` intacts.
const workerThreads = require('node:worker_threads');
const RealWorker = workerThreads.Worker;
workerThreads.Worker = class JarvisGuardedWorker extends RealWorker {
  constructor(file, options = {}) {
    const inherited = Array.isArray(options.execArgv) ? options.execArgv : process.execArgv;
    const execArgv = inherited.includes(__filename) ? [...inherited] : [...inherited, '--require', __filename];
    super(file, { ...options, execArgv });
  }
};

// ---------------------------------------------------------------------------------------------- 3. CSP
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "media-src 'self' data: blob:",
  "font-src 'self' data:",
  "connect-src 'self'",
  "worker-src 'self' blob:",
  "frame-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join('; ');

const originalWriteHead = http.ServerResponse.prototype.writeHead;
http.ServerResponse.prototype.writeHead = function jarvisWriteHead(...args) {
  try {
    if (!this.headersSent && !this.getHeader('content-security-policy')) this.setHeader('Content-Security-Policy', CSP);
  } catch (_) { /* en-têtes déjà partis */ }
  return originalWriteHead.apply(this, args);
};

// ---------------------------------------------------------------------------------------------- 3b. Host et Origin
function hostnameOf(authority) {
  const text = String(authority || '');
  if (text.startsWith('[')) { const close = text.indexOf(']'); return close > 0 ? text.slice(1, close).toLowerCase() : ''; }
  return text.split(':')[0].toLowerCase();
}
/** Refus (texte) d'une requête étrangère, ou null : Host de boucle locale ; Origin (si présent) = ce Studio, pour toute requête
 *  modifiante et tout WebSocket. Une lecture simple sans Origin (navigation, sonde de Core) passe. */
function foreignRequest(req, upgrade) {
  const host = req.headers.host;
  if (!LOOPBACK_HOSTS.has(hostnameOf(host))) return 'forbidden host';
  const origin = req.headers.origin;
  const mutating = !['GET', 'HEAD', 'OPTIONS'].includes(String(req.method).toUpperCase());
  if (origin !== undefined && (mutating || upgrade)) {
    let authority = '';
    try { authority = new URL(origin).host; } catch (_) { return 'invalid origin'; }
    if (authority.toLowerCase() !== String(host).toLowerCase()) return 'cross-origin request';
  }
  if (mutating && String(req.headers['sec-fetch-site'] || '').toLowerCase() === 'cross-site') return 'cross-site request';
  return null;
}

// ---------------------------------------------------------------------------------------------- 4/5. santé et activité
const originalEmit = http.Server.prototype.emit;
http.Server.prototype.emit = function jarvisEmit(type, ...rest) {
  if (type === 'request') {
    const [req, res] = rest;
    const why = req && foreignRequest(req, false);
    if (why) {
      state.blockedRequests += 1;
      writeActivity(true);
      res.writeHead(403, { 'content-type': 'text/plain' });
      res.end('refused by the Jarvis Studio guard: ' + why);
      return true;
    }
    if (req && req.url === HEALTH_PATH) {
      res.writeHead(200, { 'content-type': 'application/json', 'cache-control': 'no-store' });
      res.end(JSON.stringify({ ok: true, pid: process.pid, launch: LAUNCH }));
      return true;
    }
    state.requests += 1;
    state.last = Date.now();
    writeActivity(false);
  } else if (type === 'upgrade') {
    const [req, socket] = rest;
    const why = req && foreignRequest(req, true);
    if (why) {
      state.blockedRequests += 1;
      writeActivity(true);
      try { socket.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n'); } catch (_) { /* socket déjà fermé */ }
      return true;
    }
    state.ws += 1;
    state.last = Date.now();
    writeActivity(true);
    if (socket && typeof socket.once === 'function') {
      let counted = true;  // 'end' (le client part) ou 'close' : le premier des deux décompte, une seule fois
      const done = () => { if (!counted) return; counted = false; state.ws = Math.max(0, state.ws - 1); state.last = Date.now(); writeActivity(true); };
      socket.once('close', done);
      socket.once('end', done);
    }
  }
  return originalEmit.call(this, type, ...rest);
};

writeActivity(true);

// ---------------------------------------------------------------------------------------------- 6. plus d'orphelin
/** Heure de création d'un processus, au MÊME format que `process_tree.make_process_ref` côté Core : '' = n'existe pas,
 *  null = illisible ici (identité invérifiable : on se rabat sur le seul pid). Asynchrone : n'arrête jamais la boucle du Studio. */
function processCreated(pid, callback) {
  if (!Number.isInteger(pid) || pid <= 0) { callback(''); return; }
  if (process.platform === 'linux') {
    try { callback(fs.readFileSync(`/proc/${pid}/stat`, 'utf8').split(')').pop().trim().split(/\s+/)[19] || ''); } catch (error) { callback(error.code === 'ENOENT' ? '' : null); }
    return;
  }
  const [command, args] = process.platform === 'win32'
    ? ['powershell', ['-NoProfile', '-NonInteractive', '-Command', `(Get-Process -Id ${pid} -ErrorAction Stop).StartTime.ToFileTimeUtc()`]]
    : ['ps', ['-o', 'lstart=', '-p', String(pid)]];
  try {
    realExecFile(command, args, { timeout: 15000, windowsHide: true }, (error, stdout) => {
      const text = String(stdout || '').trim();
      callback(error ? (text === '' && error.code !== 'ENOENT' && !error.killed ? '' : null) : text);
    });
  } catch (_) { callback(null); }
}

let parentGoneSince = 0;
let identity = { key: '', verifiedAt: 0, ok: true, pending: false };
function readParent() {
  try {
    const raw = JSON.parse(fs.readFileSync(path.join(DIR, 'parent.json'), 'utf8'));
    return Number.isInteger(raw.pid) && raw.pid > 0 ? { pid: raw.pid, created: String(raw.created || '') } : null;
  } catch (_) { return null; }
}
function parentAlive(parent, now) {
  if (!parent) return false;
  try { process.kill(parent.pid, 0); } catch (error) { if (!(error && error.code === 'EPERM')) return false; }
  if (!parent.created) return true;  // Core n'a pas pu lire son heure de création : le seul pid
  const key = parent.pid + ':' + parent.created;
  if (identity.key !== key) identity = { key, verifiedAt: 0, ok: true, pending: false };  // nouveau parent déclaré (adoption) : à revérifier
  if (!identity.pending && now - identity.verifiedAt >= 10000) {
    identity.pending = true;
    processCreated(parent.pid, (created) => {
      identity.pending = false;
      identity.verifiedAt = Date.now();
      identity.ok = created === null ? true : created === parent.created;  // '' (absent) ou autre heure : ce n'est plus ce Core
    });
  }
  return identity.ok;
}
const watchdog = !IS_MAIN ? null : setInterval(() => {
  const now = Date.now();
  if (parentAlive(readParent(), now)) parentGoneSince = 0;
  else if (!parentGoneSince) parentGoneSince = now;
  else if (now - parentGoneSince >= PARENT_GRACE_MS) { writeJson('exit.json', { launch: LAUNCH, reason: 'parent_gone', at: now }); process.exit(0); }
  if (IDLE_MS > 0 && state.ws === 0 && now - state.last >= IDLE_MS) { writeJson('exit.json', { launch: LAUNCH, reason: 'idle', at: now }); process.exit(0); }
}, 1000);
if (watchdog) watchdog.unref();
