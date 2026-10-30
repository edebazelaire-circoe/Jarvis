"""Exactly allocated baseline browser cases/current bootstrap retry, sequential."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

qa=Path(__file__).parent.resolve()
current=qa.parents[4]
baseline=current.parent/'movb'
variants='tests/unit/test_variants_run_browser.py::test_during_a_run_recording_chips_stay_visible_reachable_and_stop_without_touching_the_run'
groups={
    'graph':(baseline,['tests/unit/test_scene_task_graph_browser.py::test_a_dense_graph_at_200_percent_and_in_forced_colours_stays_usable']),
    'architecture':(baseline,['tests/unit/test_architecture_agents_settings_browser.py::test_two_tabs_destinations_and_legacy_ids',
        'tests/unit/test_architecture_agents_settings_browser.py::test_architecture_canvas_and_core_window_work_together_then_subagents_tab']),
    'chips':(baseline,[variants+'[1280x720]',variants+'[1920x1032]',variants+'[600x800]']),
    'current-settings':(current,['tests/unit/test_settings_shell_browser.py::test_open_voice_model_comparison_does_not_overflow[1366-768]']),
    'current-graph':(current,['tests/unit/test_scene_task_graph_browser.py::test_a_dense_graph_at_200_percent_and_in_forced_colours_stays_usable']),
    'current-architecture':(current,['tests/unit/test_architecture_agents_settings_browser.py::test_two_tabs_destinations_and_legacy_ids',
        'tests/unit/test_architecture_agents_settings_browser.py::test_architecture_canvas_and_core_window_work_together_then_subagents_tab']),
    'reworked-architecture':(current,['tests/unit/test_architecture_agents_settings_browser.py::test_two_tabs_destinations_and_legacy_ids',
        'tests/unit/test_architecture_agents_settings_browser.py::test_architecture_canvas_and_core_window_work_together_then_subagents_tab']),
}
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('group',choices=groups)
options=parser.parse_args()
repo,cases=groups[options.group]
manifest=qa/f'pending-{options.group}-run.json'
if manifest.exists():
    raise SystemExit('Refusing to repeat/overwrite the exact allocated cases.')
revision=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
if repo==baseline:
    assert revision=='c0858a8000e2ca23b57231edb8f46c643080ad07'
scratch=Path(tempfile.mkdtemp(prefix='jarvis-mov-exact-baseline-')).resolve()
captures=qa/f'pending-{options.group}-captures'
captures.mkdir(exist_ok=True)
command=[sys.executable,'-m','pytest','--tb=short','-p','no:cacheprovider','-q',*cases,
         f'--basetemp={scratch}',f'--junitxml={qa / ("pending-"+options.group+".xml")}']
if options.group in ('current-graph','current-architecture'):
    command.append('--showlocals')  # Reporting only; preserve actual failure values.
record={'group':options.group,'revision':revision,'cases':cases,'scratch':str(scratch),
        'started_at':datetime.now(timezone.utc).isoformat(),'runner_pid':os.getpid(),'command':command}
manifest.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
with (qa/f'pending-{options.group}.log').open('w',encoding='utf-8') as stream:
    env={**os.environ,'PYTHONPATH':str(repo),'PYTHONDONTWRITEBYTECODE':'1','PYTEST_ADDOPTS':'',
         'JARVIS_S09_EVIDENCE_DIR':str(captures),'JARVIS_BROWSER_SHOTS':str(captures)}
    with subprocess.Popen(command,cwd=repo,env=env,stdout=stream,stderr=subprocess.STDOUT) as child:
        record['child_pid']=child.pid
        manifest.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
        try:
            record['returncode']=child.wait(timeout=480)
        except subprocess.TimeoutExpired:
            record['timed_out']=True
            child.kill();child.wait()
for index,picture in enumerate(scratch.rglob('*.png')):
    shutil.copy2(picture,captures/f'{index:02d}-{picture.name}')
record['ended_at']=datetime.now(timezone.utc).isoformat()
manifest.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
print(json.dumps(record,ensure_ascii=False),flush=True)
