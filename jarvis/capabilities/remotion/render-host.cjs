// Processus de rendu Remotion géré par Jarvis (Slice 16 ; docs/remotion-render.md).
// `node --require render-guard.cjs render-host.cjs <spec.json>` : empaquette la copie de travail d'une scène GELÉE, ouvre UN navigateur
// (celui que Core a choisi, jamais un téléchargement), rend un MP4, une image ou des pages d'image, et écrit `progress.json` puis
// `result.json` (atomiquement). N'écrit que sous le dossier du travail. Ne lit aucune route de Core, aucune base, aucun secret.
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const guard = require('./render-guard.cjs');

const specPath = process.argv[2];
const spec = JSON.parse(fs.readFileSync(specPath, 'utf8'));
const started = Date.now();
const progress = { phase: 'starting', frames_done: 0, frames_total: spec.frames_total || 0, updated_ms: started };

function writeJson(file, value) {
  const temporary = file + '.tmp';
  fs.writeFileSync(temporary, JSON.stringify(value));
  fs.renameSync(temporary, file);
}
let lastWrite = 0;
function setProgress(patch, force) {
  Object.assign(progress, patch, { updated_ms: Date.now() });
  if (force || Date.now() - lastWrite > 250) {
    lastWrite = Date.now();
    try { writeJson(spec.progress, progress); } catch (_) { /* diagnostic */ }
  }
}
function finish(result, code) {
  try { writeJson(spec.result, { ...result, elapsed_ms: Date.now() - started }); } catch (_) { /* le code de sortie dit l'essentiel */ }
  process.exit(code);
}

async function main() {
  const modules = path.join(spec.runtime, 'node_modules');
  const { bundle } = require(path.join(modules, '@remotion', 'bundler'));
  const renderer = require(path.join(modules, '@remotion', 'renderer'));
  setProgress({ phase: 'preparing' }, true);
  // Le proxy de refus d'abord : le garde remplace les arguments du navigateur et exige qu'il existe.
  const servePort = await freePort();
  const proxy = await guard.startEgressProxy(servePort);

  setProgress({ phase: 'bundling' }, true);
  const bundleDir = await bundle({
    entryPoint: path.join(spec.work, spec.entry), outDir: spec.bundle_dir, rootDir: spec.work, publicDir: path.join(spec.work, 'public'),
    enableCaching: false, onProgress: (value) => setProgress({ phase: 'bundling', bundle_percent: value }),
  });

  setProgress({ phase: 'opening_browser' }, true);
  const chromiumOptions = { gl: spec.gl || null, headless: true };
  let browser;
  try {
    browser = await renderer.openBrowser('chrome', {
      browserExecutable: spec.browser, chromeMode: 'chrome-for-testing', chromiumOptions, logLevel: 'warn',
    });
  } catch (error) {
    // Typed, visible, never retried in another mode: the guard refused the arguments, or Chrome could not start (with its process
    // sandbox ON, a machine where the sandbox cannot be created says so here; the user may opt out explicitly, never silently).
    const code = guard.state.guardError || (guard.state.sandbox ? 'sandbox_launch_failed' : 'browser_launch_failed');
    throw Object.assign(new Error(String((error && error.message) || error).slice(0, 600)), { jarvisCode: code });
  }
  if (guard.state.browserLaunches < 1 || !guard.state.proxyPort) {
    try { await browser.close({ silent: true }); } catch (_) { /* already closed */ }
    throw Object.assign(new Error('the browser was launched without going through the guard'), { jarvisCode: 'render_guard_not_applied' });
  }
  const common = { serveUrl: bundleDir, puppeteerInstance: browser, browserExecutable: spec.browser, chromeMode: 'chrome-for-testing', chromiumOptions,
                   port: servePort, inputProps: spec.props || {}, logLevel: 'warn', timeoutInMilliseconds: spec.delay_render_timeout_ms || 30000 };
  const logs = [];
  const onBrowserLog = (log) => { if (logs.length < 20) logs.push(String(log.text || '').slice(0, 200)); };
  try {
    setProgress({ phase: 'selecting_composition' }, true);
    const composition = await renderer.selectComposition({ ...common, id: spec.composition_id });
    const declared = spec.composition;
    for (const key of ['width', 'height', 'fps', 'durationInFrames']) {
      if (composition[key] !== declared[key]) {
        throw Object.assign(new Error(`composition ${key} is ${composition[key]}, the frozen manifest declares ${declared[key]}`), { jarvisCode: 'composition_mismatch' });
      }
    }
    const outputs = [];
    if (spec.format === 'mp4') {
      setProgress({ phase: 'rendering', frames_total: spec.frames_total }, true);
      await renderer.renderMedia({
        ...common, composition, codec: 'h264', outputLocation: spec.out, frameRange: spec.frame_range, crf: spec.crf, scale: spec.scale,
        concurrency: spec.concurrency, overwrite: true, onBrowserLog, pixelFormat: 'yuv420p', muted: false, enforceAudioTrack: false,
        onProgress: (p) => setProgress({ phase: p.stitchedFrames > 0 && p.renderedFrames >= spec.frames_total ? 'encoding' : 'rendering',
                                        frames_done: p.renderedFrames, frames_total: spec.frames_total, encoded_frames: p.encodedFrames }),
      });
      outputs.push(spec.out);
    } else {
      const frames = spec.frames;
      for (let index = 0; index < frames.length; index += 1) {
        setProgress({ phase: 'rendering', frames_done: index, frames_total: frames.length }, true);
        const target = spec.format === 'still' ? spec.out : path.join(spec.pages_dir, `page-${String(index + 1).padStart(2, '0')}.jpg`);
        await renderer.renderStill({
          ...common, composition, frame: frames[index], output: target, imageFormat: spec.format === 'still' ? 'png' : 'jpeg',
          ...(spec.format === 'still' ? {} : { jpegQuality: spec.jpeg_quality }), scale: spec.scale, overwrite: true, onBrowserLog,
        });
        outputs.push(target);
      }
    }
    setProgress({ phase: 'done', frames_done: progress.frames_total }, true);
    guard.writeEgress();
    finish({ ok: true, outputs, browser_logs: logs, egress: guard.state }, 0);
  } finally {
    try { await browser.close({ silent: true }); } catch (_) { /* déjà fermé */ }
    proxy.close();
  }
}

function freePort() {
  return new Promise((resolve, reject) => {
    const probe = require('node:net').createServer();
    probe.once('error', reject);
    probe.listen(0, '127.0.0.1', () => { const { port } = probe.address(); probe.close(() => resolve(port)); });
  });
}

for (const event of ['uncaughtException', 'unhandledRejection']) {
  process.on(event, (error) => {
    guard.writeEgress();
    finish({ ok: false, code: 'render_crashed', message: `${event}: ${String((error && error.stack) || error).slice(0, 1800)}`, egress: guard.state }, 1);
  });
}

main().catch((error) => {
  guard.writeEgress();
  finish({ ok: false, code: error && error.jarvisCode ? error.jarvisCode : 'render_failed', message: String((error && error.stack) || error).slice(0, 2000),
           egress: guard.state }, 1);
});
