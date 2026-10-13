/* Control group (Slice 03): bundle entry.jsx with the pinned runtime's esbuild/React/@remotion/player, open it in headless Chrome through the
   shared CDP driver (tests/unit/_remotion_stage_browser.mjs), let it play 8 s, and print what the plain Player did.
   Usage: node build_and_run.mjs <runtime dir (the folder holding node_modules)> <out dir> <chrome.exe> */
import {execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {mkdirSync, writeFileSync} from 'node:fs';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const [,, RUNTIME, OUT, CHROME] = process.argv;
const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(join(resolve(RUNTIME), 'package.json'));
const esbuild = require('esbuild');
mkdirSync(OUT, {recursive: true});
await esbuild.build({entryPoints: [join(here, 'entry.jsx')], bundle: true, outfile: join(OUT, 'bundle.js'), format: 'iife',
  nodePaths: [join(resolve(RUNTIME), 'node_modules')], define: {'process.env.NODE_ENV': '"production"'}, logLevel: 'warning'});
writeFileSync(join(OUT, 'index.html'), '<!doctype html><meta charset="utf-8"><body style="margin:0;background:#000"><script src="bundle.js"></script>');
const driver = resolve(here, '../../../../../../tests/unit/_remotion_stage_browser.mjs');
const plan = [{until: '!!window.__ctl', ms: 10000}, {eval: 'window.__ctl.run()'}, {wait: 8000}, {value: 'log', expr: 'window.__ctl.log'}, {value: 'frames_at_8s', expr: 'window.__ctl.frames()'}];
const out = execFileSync('node', [driver, pathToFileURL(join(OUT, 'index.html')).href, CHROME, JSON.stringify(plan)], {encoding: 'utf8', maxBuffer: 64e6});
const {reads, errors} = JSON.parse(out);
const log = reads.log || [];
const summary = {};
for (const id of ['loop_false', 'loop_true', 'loop_false_seek', 'loop_false_hold']) {
  const frames = log.filter((r) => r[1] === id && r[2] === 'frame').map((r) => [r[0], r[3]]);
  const wraps = frames.filter((f, i) => i > 0 && f[1] < frames[i - 1][1]).map((f) => f[0]);
  summary[id] = {events: log.filter((r) => r[1] === id && r[2] !== 'frame'), first_frame: frames[0] || null, last_frame: frames.at(-1) || null,
    max_frame: Math.max(-1, ...frames.map((f) => f[1])), wraps_at_ms: wraps};
}
process.stdout.write(JSON.stringify({summary, frames_at_8s: reads.frames_at_8s, errors, failed: reads.failed || null}, null, 1));
