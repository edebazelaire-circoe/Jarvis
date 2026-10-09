// Garde de l'éventuel Remotion Studio géré par Jarvis (Slice 11 ; docs/remotion-studio.md).
// Chargé par `node --require <ce fichier> .../remotion-cli.js studio ...`. Copié par Core dans le dossier du Studio à chaque
// ouverture (et comparé à l'original livré) : ce n'est PAS un fichier de la capacité installée (aucune empreinte d'installation).
//
// Pourquoi : le Studio stock lie son serveur à 0.0.0.0 / :: (tout le réseau local) et son processus Node peut ouvrir n'importe
// quelle connexion. Ce garde, dans le processus du Studio lui-même :
//   1. force tout `listen` TCP sur la boucle locale (127.0.0.1 / ::1) ;
//   2. refuse toute connexion TCP sortante hors boucle locale (défense en profondeur, compte les refus) ;
//   3. pose une Content-Security-Policy sur chaque réponse HTTP du Studio (la scène s'exécute dans l'onglet du Studio) ;
//   4. répond à `GET /__jarvis_studio__/health` (pid + identifiant de lancement) et écrit `listening.json` ;
//   5. tient `activity.json` à jour (dernière requête, WebSocket ouverts) pour le délai d'inactivité de Core.
// Ce n'est pas un bac à sable : un enfant lancé par le Studio, de l'UDP ou un module natif y échappent (docs §Limites).
'use strict';

const fs = require('node:fs');
const net = require('node:net');
const http = require('node:http');
const path = require('node:path');

const DIR = process.env.JARVIS_STUDIO_DIR || '';
const LAUNCH = process.env.JARVIS_STUDIO_LAUNCH || '';
const LOOPBACK_HOSTS = new Set(['127.0.0.1', '::1', 'localhost']);
const HEALTH_PATH = '/__jarvis_studio__/health';
const state = { listening: [], blocked: 0, blockedHosts: [], requests: 0, ws: 0, last: Date.now() };

function writeJson(name, value) {
  if (!DIR) return;
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
                               blocked_egress: state.blocked, blocked_hosts: state.blockedHosts.slice(0, 10) });
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

// ---------------------------------------------------------------------------------------------- 3. CSP
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "media-src 'self' data: blob:",
  "font-src 'self' data:",
  "connect-src 'self' ws://127.0.0.1:* ws://localhost:* http://127.0.0.1:* http://localhost:*",
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

// ---------------------------------------------------------------------------------------------- 4/5. santé et activité
const originalEmit = http.Server.prototype.emit;
http.Server.prototype.emit = function jarvisEmit(type, ...rest) {
  if (type === 'request') {
    const [req, res] = rest;
    if (req && req.url === HEALTH_PATH) {
      res.writeHead(200, { 'content-type': 'application/json', 'cache-control': 'no-store' });
      res.end(JSON.stringify({ ok: true, pid: process.pid, launch: LAUNCH }));
      return true;
    }
    state.requests += 1;
    state.last = Date.now();
    writeActivity(false);
  } else if (type === 'upgrade') {
    const socket = rest[1];
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
