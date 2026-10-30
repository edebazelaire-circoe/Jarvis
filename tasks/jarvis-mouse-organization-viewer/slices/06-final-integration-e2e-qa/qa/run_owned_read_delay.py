"""Run exactly one unchanged owned_read case per baseline/current revision."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

QA=Path(__file__).parent.resolve()
CURRENT=QA.parents[4]
BASELINE=CURRENT.parent/'movb'
CASE='tests/unit/test_back_brain_tasks.py::test_persistent_storage_read_failure_preserves_owner_and_bounds_stop[owned_read]'
records=[]
if '--execute' not in sys.argv:
    raise SystemExit('This diagnostic was inconclusive; no rerun is authorized. --execute requires a new PM allocation.')
for name,repo in [('baseline',BASELINE),('current',CURRENT)]:
    revision=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
    report=QA/f'owned-delay-{name}.json'
    if report.exists():
        raise SystemExit(f'Refusing to overwrite retained evidence: {report}')
    env={**os.environ,'PYTHONPATH':os.pathsep.join([str(QA),str(repo)]),
         'PYTHONDONTWRITEBYTECODE':'1','JARVIS_OWNED_DELAY_REPORT':str(report)}
    command=[sys.executable,'-m','pytest','--assert=plain','--tb=short','-p','no:cacheprovider',
             '-p','owned_read_delay_plugin','-q',CASE,f'--junitxml={QA / ("owned-delay-"+name+".xml")}']
    try:
        done=subprocess.run(command,cwd=repo,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=45)
    except subprocess.TimeoutExpired as exc:
        # Capture failure honestly and stop, rather than proceeding to another
        # revision after an inconclusive first execution. Not rerun after patch.
        def text(value):
            return value.decode('utf-8',errors='replace') if isinstance(value,bytes) else value or ''
        (QA/f'owned-delay-{name}.log').write_text(text(exc.stdout)+'\n'+text(exc.stderr)+'\nTimeoutExpired:45s\n',encoding='utf-8')
        records.append({'name':name,'revision':revision,'timed_out_seconds':45,
            'diagnostic':json.loads(report.read_text(encoding='utf-8')) if report.exists() else None})
        break
    (QA/f'owned-delay-{name}.log').write_text(done.stdout+'\n'+done.stderr,encoding='utf-8')
    record={'name':name,'revision':revision,'returncode':done.returncode,
            'unchanged_test_sha256':hashlib.sha256((repo/'tests/unit/test_back_brain_tasks.py').read_bytes()).hexdigest(),
            'diagnostic':json.loads(report.read_text(encoding='utf-8')) if report.exists() else None}
    records.append(record)
    print(json.dumps(record,ensure_ascii=False),flush=True)
(QA/'owned-delay-comparison.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
