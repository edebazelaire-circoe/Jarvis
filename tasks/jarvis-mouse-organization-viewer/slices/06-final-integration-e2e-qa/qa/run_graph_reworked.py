"""One PM-approved modified original graph case, all three scenarios."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

qa = Path(__file__).parent.resolve()
repo = qa.parents[4]
manifest = qa / 'graph-reworked-run.json'
if manifest.exists():
    raise SystemExit('Refusing repeat/overwrite of the allocated corrected case.')
scratch = Path(tempfile.mkdtemp(prefix='jarvis-mov-graph-reworked-'))
captures = qa / 'graph-reworked-captures'
captures.mkdir(exist_ok=True)
command = [sys.executable, '-m', 'pytest', '--tb=short', '-p', 'no:cacheprovider',
           '-p', 'graph_result_retention_plugin', '-q',
           'tests/unit/test_scene_task_graph_browser.py::test_a_dense_graph_at_200_percent_and_in_forced_colours_stays_usable',
           f'--basetemp={scratch}', f'--junitxml={qa / "graph-reworked.xml"}']
record = {'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip(),
          'started_at': datetime.now(timezone.utc).isoformat(), 'command': command,
          'runner_pid': os.getpid(), 'scratch': str(scratch)}
manifest.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
with (qa / 'graph-reworked.log').open('w', encoding='utf-8') as stream:
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join([str(qa), str(repo)]),
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTEST_ADDOPTS': '',
           'JARVIS_GRAPH_REWORKED_RAW': str(qa / 'graph-reworked-raw.json'),
           'JARVIS_S09_EVIDENCE_DIR': str(captures)}
    with subprocess.Popen(command, cwd=repo, env=env, stdout=stream, stderr=subprocess.STDOUT) as child:
        record['child_pid'] = child.pid
        manifest.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
        try:
            record['returncode'] = child.wait(timeout=180)
        except subprocess.TimeoutExpired:
            record['timed_out'] = True
            child.kill()
            child.wait()
record['ended_at'] = datetime.now(timezone.utc).isoformat()
manifest.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
print(json.dumps(record), flush=True)
