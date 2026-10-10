// Sonde du bac à sable de Chrome (Slice 16, `docs/remotion-render.md` §4) : lance le navigateur COMME LE RENDU (même garde, mêmes arguments
// réécrits) puis ouvre `chrome://sandbox` et rend ce que Chrome dit de son propre bac à sable.
// Usage : JARVIS_RENDER_DIR=<dossier> JARVIS_RENDER_RUNTIME=<runtime> JARVIS_RENDER_BROWSER=<chrome> [JARVIS_REMOTION_RENDER_NO_SANDBOX=1]
//         node --require <render-guard.cjs> remotion_sandbox_probe.cjs <runtime> <chrome> <sortie.json>
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const guard = require('./render-guard.cjs');
const [runtime, browserPath, output] = process.argv.slice(2);

(async () => {
  const renderer = require(path.join(runtime, 'node_modules', '@remotion', 'renderer'));
  const proxy = await guard.startEgressProxy(1);
  const browser = await renderer.openBrowser('chrome', { browserExecutable: browserPath, chromeMode: 'chrome-for-testing',
    chromiumOptions: { gl: null, headless: true }, logLevel: 'warn' });
  const page = await browser.newPage({ context: () => null, logLevel: 'warn', indent: false, pageIndex: 0, onBrowserLog: null, onLog: () => undefined });
  await page.goto({ url: 'chrome://sandbox', timeout: 20000 });
  const text = await page.evaluate(() => document.body.innerText);
  fs.writeFileSync(output, JSON.stringify({ sandbox_page: String(text).slice(0, 2500), sandbox_flag_in_guard: guard.state.sandbox, browser_launches: guard.state.browserLaunches }));
  await browser.close({ silent: true });
  proxy.close();
  process.exit(0);
})().catch((error) => { fs.writeFileSync(output, JSON.stringify({ error: String((error && error.stack) || error).slice(0, 1500) })); process.exit(1); });
