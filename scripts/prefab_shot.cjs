/* Photographie une page avec Chrome headless piloté en CDP (sans dépendance).
   node prefab_shot.cjs <chrome.exe> <page.html> <out.png> <largeur> <hauteur> <actions.json>
   actions : [{"wait":ms},{"hover":[x,y]},{"click":[x,y]},{"key":"Tab"},{"shot":"fichier.png"}]
   Le dernier cliché est `out.png` ; `shot` en prend d'autres en cours de route. */
const {spawn} = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const [chrome, page, out, W, H, actionsFile] = process.argv.slice(2);
const actions = JSON.parse(fs.readFileSync(actionsFile, 'utf8'));
const port = 9300 + Math.floor(Math.random() * 500);
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'jv-chrome-'));
const proc = spawn(chrome, ['--headless=new', '--disable-gpu', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
  '--hide-scrollbars', '--force-device-scale-factor=1', `--window-size=${W},${H}`, 'about:blank'], {stdio: 'ignore'});
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  let tabs = null;
  for (let i = 0; i < 60 && !tabs; i++) {
    try { tabs = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); } catch (_e) { await sleep(250); }
  }
  const tab = tabs.find((t) => t.type === 'page');
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener('open', r));
  let id = 0; const pending = new Map();
  ws.addEventListener('message', (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } });
  const send = (method, params = {}) => new Promise((r) => { const n = ++id; pending.set(n, r); ws.send(JSON.stringify({id: n, method, params})); });
  await send('Emulation.setDeviceMetricsOverride', {width: +W, height: +H, deviceScaleFactor: 1, mobile: false});
  await send('Page.enable');
  await send('Page.navigate', {url: 'file:///' + page.replace(/\\/g, '/')});
  const shot = async (file) => {
    const r = await send('Page.captureScreenshot', {format: 'png'});
    fs.writeFileSync(file, Buffer.from(r.result.data, 'base64'));
  };
  const mouse = (type, x, y, extra = {}) => send('Input.dispatchMouseEvent', Object.assign({type, x, y, button: 'none'}, extra));
  for (const a of actions) {
    if (a.wait) await sleep(a.wait);
    else if (a.hover) { await mouse('mouseMoved', a.hover[0], a.hover[1]); await sleep(a.settle || 700); }
    else if (a.click) {
      await mouse('mouseMoved', a.click[0], a.click[1]);
      await mouse('mousePressed', a.click[0], a.click[1], {button: 'left', clickCount: 1});
      await mouse('mouseReleased', a.click[0], a.click[1], {button: 'left', clickCount: 1});
      await sleep(a.settle || 900);
    } else if (a.key) {
      await send('Input.dispatchKeyEvent', {type: 'keyDown', key: a.key, code: a.key, windowsVirtualKeyCode: a.key === 'Tab' ? 9 : 13});
      await send('Input.dispatchKeyEvent', {type: 'keyUp', key: a.key, code: a.key, windowsVirtualKeyCode: a.key === 'Tab' ? 9 : 13});
      await sleep(a.settle || 500);
    } else if (a.shot) await shot(a.shot);
  }
  await shot(out);
  ws.close(); proc.kill();
  try { fs.rmSync(profile, {recursive: true, force: true}); } catch (_e) { /* profil verrouillé : sans importance */ }
  process.exit(0);
})().catch((e) => { console.error(e); proc.kill(); process.exit(1); });
