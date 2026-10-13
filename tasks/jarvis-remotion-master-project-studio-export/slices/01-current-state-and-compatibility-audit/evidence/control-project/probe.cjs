// Slice 01 probe driver: real @remotion/bundler + @remotion/renderer 4.0.534 (pinned runtime), NOT the guarded Jarvis host.
// node probe.cjs <runtime_dir> <work_dir> <out_dir> <jobs.json>
// jobs: [{id, composition, kind: "mp4"|"still", frames?: [..], scale?, logs?: bool}]
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const [runtime, work, out, jobsFile] = process.argv.slice(2);
const modules = path.join(runtime, 'node_modules');
const { bundle } = require(path.join(modules, '@remotion', 'bundler'));
const R = require(path.join(modules, '@remotion', 'renderer'));
const browserExecutable = process.env.S01_BROWSER;

(async () => {
  fs.mkdirSync(out, { recursive: true });
  const t0 = Date.now();
  const serveUrl = await bundle({ entryPoint: path.join(work, 'studio-root.tsx'), outDir: path.join(out, 'bundle'), rootDir: work,
                                  publicDir: path.join(work, 'public'), enableCaching: false });
  const results = { bundle_ms: Date.now() - t0, jobs: [] };
  const browser = await R.openBrowser('chrome', { browserExecutable, chromeMode: 'chrome-for-testing', chromiumOptions: { headless: true }, logLevel: 'error' });
  for (const job of JSON.parse(fs.readFileSync(jobsFile, 'utf8'))) {
    const logs = [];
    const onBrowserLog = (l) => { const t = String(l.text || ''); if (t.startsWith('PROBE|') || l.type === 'error') logs.push(t.slice(0, 300)); };
    const common = { serveUrl, puppeteerInstance: browser, browserExecutable, chromeMode: 'chrome-for-testing', logLevel: 'error', timeoutInMilliseconds: 30000 };
    const r = { id: job.id, composition: job.composition, kind: job.kind };
    const started = Date.now();
    try {
      const comp = await R.selectComposition({ ...common, id: job.composition });
      r.selected = { width: comp.width, height: comp.height, fps: comp.fps, durationInFrames: comp.durationInFrames };
      if (job.kind === 'mp4') {
        r.out = path.join(out, `${job.id}.mp4`);
        await R.renderMedia({ ...common, composition: comp, codec: 'h264', outputLocation: r.out, overwrite: true, pixelFormat: 'yuv420p',
                              muted: false, enforceAudioTrack: false, concurrency: job.concurrency || 1, scale: job.scale || 1, onBrowserLog });
      } else {
        r.outs = [];
        for (const f of job.frames) {
          const o = path.join(out, `${job.id}-f${String(f).padStart(4, '0')}.png`);
          await R.renderStill({ ...common, composition: comp, frame: f, output: o, imageFormat: 'png', overwrite: true, scale: job.scale || 1, onBrowserLog });
          r.outs.push(o);
        }
      }
      r.ok = true;
    } catch (e) {
      r.ok = false;
      r.error = String((e && e.message) || e).split('\n').slice(0, 3).join(' | ').slice(0, 600);
    }
    r.elapsed_ms = Date.now() - started;
    // de-duplicate probe lines (a frame may be evaluated more than once) and keep them ordered
    r.probes = [...new Set(logs.filter((l) => l.startsWith('PROBE|')))];
    r.errors = [...new Set(logs.filter((l) => !l.startsWith('PROBE|')))].slice(0, 5);
    results.jobs.push(r);
    console.log(JSON.stringify({ id: r.id, ok: r.ok, ms: r.elapsed_ms, error: r.error }));
  }
  await browser.close({ silent: true });
  fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify(results, null, 1));
})().catch((e) => { console.error(e); process.exit(1); });
