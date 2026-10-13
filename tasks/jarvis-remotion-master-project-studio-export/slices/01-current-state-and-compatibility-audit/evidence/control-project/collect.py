import json, os, getpass, sys
from pathlib import Path
S, E = Path(sys.argv[1]), Path(sys.argv[2])
home = os.path.expanduser('~'); user = getpass.getuser()
def red(t):
    B = chr(92); hs = {home, home.replace(B, '/'), home.replace(B, B + B)}
    for h in hs:
        t = t.replace(h, '~')
    return t.replace(user, '<user>')
r = json.loads((S / 'out_main/results.json').read_text(encoding='utf-8'))
out = {'runtime': 'remotion, @remotion/bundler, @remotion/renderer 4.0.534 (pinned gate runtime via read-only junction)',
       'driver': 'control-project/probe.cjs (unguarded probe driver)', 'bundle_ms': r['bundle_ms'], 'jobs': []}
for j in r['jobs']:
    scenes = {}
    for l in j['probes']:
        _, s, f, cfg, d = l.split('|')
        x = scenes.setdefault(s, {'f': set(), 'c': set()}); x['f'].add(int(f)); x['c'].add(f'{cfg} durationInFrames={d}')
    out['jobs'].append({'id': j['id'], 'composition': j['composition'], 'kind': j['kind'], 'ok': j['ok'], 'error': j.get('error'),
                        'selected': j.get('selected'), 'elapsed_ms': j['elapsed_ms'],
                        'scenes_in_order': [{'scene': s, 'first_local_frame': min(v['f']), 'last_local_frame': max(v['f']), 'frames_seen': len(v['f']),
                                             'useVideoConfig': sorted(v['c'])} for s, v in scenes.items()],
                        'browser_errors': [e[:160] for e in j['errors']]})
(E / 'results/probe-results.json').write_text(red(json.dumps(out, indent=1)), encoding='utf-8')
real = {}
for n in ['real-master-ok', 'real-perf-1080', 'real-perf-1080-long']:
    jd = S / 'runtime/render/jobs' / n
    res = json.loads((jd / 'result.json').read_text(encoding='utf-8')); eg = json.loads((jd / 'egress.json').read_text(encoding='utf-8'))
    spec = json.loads((jd / 'spec.json').read_text(encoding='utf-8'))
    real[n] = {'host': 'render-host.cjs + render-guard.cjs copied from the worktree, node --require guard (run_real_host.py)',
               'composition': spec['composition_id'], 'declared': spec['composition'], 'ok': res['ok'], 'elapsed_ms': res['elapsed_ms'],
               'egress': {k: eg[k] for k in ('blocked_connect', 'blocked_spawn', 'refused_spawns', 'proxy_denied', 'proxy_denied_targets',
                                            'proxy_allowed', 'browser_launches', 'sandbox', 'guard_error')},
               'ffprobe': json.loads((S / f'{n}.ffprobe.json').read_text()), 'silencedetect_-40dB': (S / f'{n}.silence.txt').read_text().splitlines()}
real['probe-ok-mp4'] = {'ffprobe': json.loads((S / 'out_main/ok.ffprobe.json').read_text())}
real['probe-throw-boundary-mp4'] = {'silencedetect_-40dB': (S / 'throw-boundary.silence.txt').read_text().splitlines()}
(E / 'results/real-host-renders.json').write_text(red(json.dumps(real, indent=1)), encoding='utf-8')
for p in E.rglob('*'):
    if p.is_file() and p.suffix in ('.py', '.cjs', '.json', '.tsx', '.ts'):
        t = p.read_text(encoding='utf-8')
        if user in t or home in t or home.replace(chr(92), '/') in t:
            p.write_text(red(t), encoding='utf-8'); print('redacted', p.name)
