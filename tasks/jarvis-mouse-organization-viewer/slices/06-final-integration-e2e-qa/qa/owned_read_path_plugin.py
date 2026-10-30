"""QA path evidence only; original test and production behavior remain unchanged."""
import collections
import json
import os
from pathlib import Path
import sys
import pytest

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    if item.name != 'test_persistent_storage_read_failure_preserves_owner_and_bounds_stop[owned_read]':
        yield
        return
    observed=collections.Counter()
    rows=collections.Counter()
    lines=collections.Counter()
    def trace(frame,event,arg):
        filename=frame.f_code.co_filename.replace('\\','/')
        if event=='call':
            observed['all_call_events']+=1
        if filename.endswith('/tests/unit/test_back_brain_tasks.py') and frame.f_code.co_name==item.originalname:
            observed['test_'+event]+=1
            return trace
        if not filename.endswith(('/jarvis/domain/scene.py','/jarvis/domain/scene_batch.py')):
            return None
        module=filename.rsplit('/',1)[-1]
        if event=='line':
            lines[f'{module}:{frame.f_lineno}']+=1
        elif event=='call':
            command=frame.f_locals.get('self') if frame.f_code.co_name=='__post_init__' else frame.f_locals.get('command')
            if command is not None and hasattr(command,'op'):
                rows[(module,frame.f_code.co_name,str(command.op),getattr(command,'targets',None) is None)]+=1
        return trace
    previous=sys.gettrace()
    sys.settrace(trace)
    try:
        yield
    finally:
        sys.settrace(previous)
        Path(os.environ['JARVIS_PATH_REPORT']).write_text(json.dumps({
            'scope':'Exact owned_read call phase; domain scene modules only; op and targets-is-None only, no content',
            'positive_trace_control':dict(observed),
            'commands':[dict(module=k[0],function=k[1],op=k[2],targets_none=k[3],calls=v) for k,v in sorted(rows.items())],
            'lines':dict(sorted(lines.items())),
            'previous_trace_restored':True,
            'timing_claim':False,
        },indent=2)+'\n',encoding='utf-8')
