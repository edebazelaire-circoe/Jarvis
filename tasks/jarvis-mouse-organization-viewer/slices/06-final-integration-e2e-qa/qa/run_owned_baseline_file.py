"""One explicitly allocated uninstrumented exact-baseline BackBrain file run."""
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

if '--execute' not in sys.argv:
    raise SystemExit('Explicit --execute required; no repeat allocation is implied.')
qa=Path(__file__).parent.resolve()
repo=qa.parents[4].parent/'movb'
manifest=qa/'owned-whole-baseline-run.json'
if manifest.exists():
    raise SystemExit('Refusing to repeat or overwrite the allocated run.')
revision=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
assert revision=='c0858a8000e2ca23b57231edb8f46c643080ad07'
command=[sys.executable,'-m','pytest','--tb=short','-p','no:cacheprovider','-q',
         'tests/unit/test_back_brain_tasks.py','--durations=5',
         f'--junitxml={qa / "owned-whole-baseline.xml"}']
record={'revision':revision,'started_at':datetime.now(timezone.utc).isoformat(),
        'runner_pid':os.getpid(),'command':command,'timeout_seconds':240,
        'instrumentation':False,'providers':'ControlledWorker/ProgressWorker, FakeVoiceFrontend, NullBrainBackend'}
manifest.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
with (qa/'owned-whole-baseline.log').open('w',encoding='utf-8') as stream:
    env={**os.environ,'PYTHONPATH':str(repo),'PYTHONDONTWRITEBYTECODE':'1','PYTEST_ADDOPTS':''}
    with subprocess.Popen(command,cwd=repo,env=env,stdout=stream,stderr=subprocess.STDOUT) as child:
        record['child_pid']=child.pid
        manifest.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
        try:
            record['returncode']=child.wait(timeout=240)
        except subprocess.TimeoutExpired:
            record['timed_out']=True
            child.kill()
            child.wait()
record['ended_at']=datetime.now(timezone.utc).isoformat()
manifest.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
print(json.dumps(record,ensure_ascii=False),flush=True)
