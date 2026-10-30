"""QA-only one-shot healed SQLite read delay; exact original test is unchanged."""
import asyncio
import json
import os
from pathlib import Path
import time

import pytest

from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.v2_app import JarvisCoreApplication


@pytest.fixture(autouse=True)
async def owned_read_delay_diagnostic(request, monkeypatch):
    expected='test_persistent_storage_read_failure_preserves_owner_and_bounds_stop[owned_read]'
    if request.node.name != expected:
        yield
        return
    original_read=SQLiteStateRepository.get_job
    original_stop=JarvisCoreApplication.stop
    cores=[]
    phases={}
    result={'case':expected,'delay_seconds':.4,'injection_count':0,'stops':[]}

    def snapshot(core):
        owned=core.jobs.owned
        worker=core.jobs.workers.get('back_brain')
        stop_task=owned._stop_task
        return {'health_status':core.health.status,'health_detail':core.health.detail,
                'stop_task':None if stop_task is None else {'done':stop_task.done(),'cancelled':stop_task.cancelled()},
                'running_count':len(core.jobs._running),
                'running_done_flags':[task.done() for task in core.jobs._running.values()],
                'worker_call_count':len(getattr(worker,'calls',[]))}

    async def delayed_read(store,job_id):
        core=next((c for c in cores if c.state is store),None)
        task=asyncio.current_task()
        # The exact test's instance failing() wrapper captured this original
        # class method. During its injected outage it raises before reaching
        # us. Thus this delay can occur only after that outage was healed.
        if core is not None and phases[id(core)]>=2 and result['injection_count']==0 and task.get_name().startswith('jarvis-job-cancel-'):
            result['injection_count']=1
            mark=time.monotonic()
            result['delay_start_phase']=phases[id(core)]
            try:
                await asyncio.sleep(.4)
                result['delay_completed']=True
            finally:
                result['delay_elapsed_seconds']=round(time.monotonic()-mark,6)
        return await original_read(store,job_id)

    async def observed_stop(core):
        if core not in cores:
            cores.append(core)
        phases[id(core)]=phases.get(id(core),0)+1
        phase=phases[id(core)]
        mark=time.monotonic()
        row={'phase':phase,'before':snapshot(core)}
        result['stops'].append(row)
        try:
            return await original_stop(core)
        except BaseException as exc:
            row['exception_type']=type(exc).__name__
            raise
        finally:
            row.update(duration_seconds=round(time.monotonic()-mark,6),after=snapshot(core))

    monkeypatch.setattr(SQLiteStateRepository,'get_job',delayed_read)
    monkeypatch.setattr(JarvisCoreApplication,'stop',observed_stop)
    try:
        yield
    finally:
        result['cleanup']=[]
        for core in cores:
            try:
                # The unchanged fixture normally performs the final owned stop.
                # If still needed, wait for that SAME reconciliation, then close
                # this Core only. No task-name/process-tree cleanup.
                if core.health.status!='stopped':
                    pending=core.jobs.owned._stop_task
                    if pending and not pending.done():
                        await asyncio.wait_for(asyncio.shield(pending),3)
                    await asyncio.wait_for(original_stop(core),3)
                result['cleanup'].append(snapshot(core))
            except Exception as exc:
                result['cleanup'].append({'failure':type(exc).__name__,**snapshot(core)})
        Path(os.environ['JARVIS_OWNED_DELAY_REPORT']).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
