"""Opt-in paid QA probe: real restricted CLI -> JobService -> public reader.

Run from the worktree with ``python .../qa/real_execution.py --execute``.
No product source or provider prompts are modified. Raw CLI stream stays in RAM.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))

from aiohttp.test_utils import TestServer
from jarvis.domain.v2 import Job
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.declaration_relay import CoreMissionTransport
from jarvis.runtime.mission_view import CoreMissionView
from jarvis.runtime.work_ingress import CoreWorkTransport
from jarvis.runtime.work_view import CoreWorkView
from tests.integration.test_scene_transport import CoreProcess


class RealCliWorker:
    def __init__(self, root: Path, model: str):
        self.root, self.model = root, model
        self.process = None
        self.started = asyncio.Event()
        self.evidence = {}

    async def execute(self, job):
        executable = shutil.which('claude')
        if not executable:
            raise RuntimeError('claude CLI unavailable')
        args = [executable, '-p', '--output-format', 'stream-json', '--verbose',
                '--restricted', '--tools', '', '--strict-mcp-config',
                '--mcp-config', '{"mcpServers":{}}', '--disable-slash-commands',
                '--no-session-persistence', '--max-budget-usd', '0.10',
                '--settings', '{"disableAllHooks":true}']
        if self.model:
            args.extend(['--model', self.model])
        start = time.monotonic()
        self.process = await asyncio.create_subprocess_exec(
            *args, cwd=self.root, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        self.started.set()
        try:
            stdout, stderr = await asyncio.wait_for(
                self.process.communicate(b'Reply exactly QA_OK. Do not use tools.\n'), 55)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            if self.process.returncode is None:
                self.process.kill()  # Only our exact child, never a process-name/tree kill.
                await self.process.wait()
            self.evidence = {'failure': 'CLI deadline/cancellation', 'deadline_seconds': 55}
            raise
        events = []
        for line in stdout.decode('utf-8', errors='replace').splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict):
                events.append(item)
        init = next((e for e in events if e.get('type') == 'system' and e.get('subtype') == 'init'), {})
        result = next((e for e in reversed(events) if e.get('type') == 'result'), {})
        tool_count = sum(1 for e in events for c in e.get('message', {}).get('content', [])
                         if isinstance(c, dict) and c.get('type') == 'tool_use')
        self.evidence = {
            'cli_exit_code': self.process.returncode,
            'requested_model': self.model or '(CLI default)',
            'reported_model': init.get('model'),
            'reported_model_usage_names': list(result.get('modelUsage', {})),
            'advertised_tools': init.get('tools'),
            'advertised_mcp_servers': init.get('mcp_servers'),
            'observed_tool_uses': tool_count,
            'result_subtype': result.get('subtype'),
            'result_is_error': result.get('is_error'),
            'final_text': result.get('result', '')[:300],
            'reported_cost_usd': result.get('total_cost_usd'),
            'reported_turns': result.get('num_turns'),
            'duration_seconds': round(time.monotonic() - start, 3),
            'budget_usd': 0.10, 'deadline_seconds': 55,
        }
        if self.process.returncode or result.get('is_error') or not result:
            # Authentication/CLI failure only, bounded text; no raw provider events.
            self.evidence['failure'] = (result.get('result') or stderr.decode('utf-8', errors='replace'))[:500]
            raise RuntimeError('real CLI execution failed; see sanitized QA evidence')
        if self.evidence['final_text'].strip() != 'QA_OK' or tool_count:
            raise RuntimeError('real CLI output/tool constraint failed')
        return {'summary': 'QA_OK', 'model': self.evidence['reported_model']}

    async def cancel(self, job_id):
        if self.process and self.process.returncode is None:
            self.process.kill()
            await self.process.wait()


async def run(output: Path):
    model = ''
    settings = Path.home() / '.claude/settings.json'
    if settings.is_file():
        model = str(json.loads(settings.read_text(encoding='utf-8')).get('model', '')).strip()
    evidence = {'recorded_at': datetime.now(timezone.utc).isoformat(),
                'scope': 'Real model infrastructure probe; S05 acceptance pending integration',
                'model_source': 'Existing user Claude CLI setting; explicit replay because restricted mode ignores settings',
                'raw_trace_exported': False, 'provider_prompt_exported_to_view_model': False}
    with tempfile.TemporaryDirectory(prefix='jarvis-mov-s5-real-') as folder:
        root = Path(folder)
        (root / 'project').mkdir()
        (root / 'runtime').mkdir()
        os.environ['JARVIS_DATA_ROOT'] = str(root / 'data')
        os.environ['JARVIS_RUNTIME_DIR'] = str(root / 'runtime')
        worker = RealCliWorker(root / 'project', model)
        core = CoreProcess(root, workers={'qa_real_model': worker})
        await core.start()
        transport = {'host': '127.0.0.1', 'port': core.port, 'token_file': core.token_file}
        work = CoreWorkView(CoreWorkTransport(**transport))
        missions = CoreMissionView(CoreMissionTransport(**transport))
        control = ControlCenter(runtime_root=root / 'runtime', project_root=root / 'project',
                                work_view=work, mission_view=missions)
        server = TestServer(control._app, shutdown_timeout=1)
        await server.start_server()
        job = await core.core.jobs.submit(Job(kind='qa_real_model', payload={}))
        module = ROOT / 'jarvis/runtime/control_center_agent_detail.js'
        reader = root / 'read.cjs'
        reader.write_text(
            f"const A=require({json.dumps(str(module))}),base={json.dumps(str(server.make_url('/')).rstrip('/'))};\n"
            "const reader=A.createReader({log:()=>{},fetchJson:async path=>{const r=await fetch(base+path),b=await r.json();"
            "if(!r.ok)throw new Error(`HTTP ${r.status}`);return b}});\n"
            f"reader.load({json.dumps({'object': {'object_id': 'qa-real-job', 'kind': 'job', 'work_ref': {'source': 'job', 'external_id': job.id}, 'payload': {'title': 'Exécution réelle de QA'}}})})"
            ".then(r=>console.log(JSON.stringify(r))).catch(e=>{console.error(e);process.exitCode=1});",
            encoding='utf-8')

        async def read_public():
            child = await asyncio.create_subprocess_exec(shutil.which('node'), str(reader),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                stdout, stderr = await asyncio.wait_for(child.communicate(), 12)
            except asyncio.TimeoutError:
                child.kill()
                await child.wait()
                raise
            if child.returncode:
                raise RuntimeError(stderr.decode('utf-8', errors='replace')[:300])
            result = json.loads(stdout)
            serialized = json.dumps(result)
            assert all('"'+name+'"' not in serialized for name in ('prompt', 'trace', 'thinking', 'declaration'))
            return result

        try:
            await asyncio.wait_for(worker.started.wait(), 10)
            evidence['running_reader'] = await read_public()
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                saved = await core.core.state.get_job(job.id)
                if saved.status.value in ('completed', 'failed', 'cancelled'):
                    break
                await asyncio.sleep(.1)
            else:
                raise TimeoutError('Core job terminal deadline')
            evidence['terminal_reader'] = await read_public()
            evidence['job_status'] = saved.status.value
            evidence['cli'] = worker.evidence
            evidence['passed'] = (
                evidence['running_reader']['model']['status'] == 'running'
                and evidence['terminal_reader']['model']['status'] == 'completed'
                and saved.status.value == 'completed')
        except Exception as exc:
            evidence.update(passed=False, failure=f'{type(exc).__name__}: {exc}', cli=worker.evidence)
        finally:
            await worker.cancel(job.id)
            await server.close()
            await missions.close()
            await work.aclose()
            await core.stop()
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'passed': evidence.get('passed'), 'output': str(output), 'cli': evidence.get('cli')}, ensure_ascii=False))
    return 0 if evidence.get('passed') else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', required=True, help='Opt in to one bounded real model call')
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('real-execution.json'))
    options = parser.parse_args()
    raise SystemExit(asyncio.run(run(options.output)))
