"""Bounded, QA-only Human preview using the existing S05 LiveAcceptance sandbox.

No model call or user runtime is started. Synthetic SQLite remains in the
unique temporary root after shutdown for review; it is never auto-deleted.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[5]


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def write_manifest(path: Path, payload: dict):
    # Readers see one complete manifest, including during shutdown updates.
    staged = path.with_name(path.name + f'.{os.getpid()}.tmp')
    staged.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    staged.replace(path)


def duration(value):
    seconds = int(value)
    if not 1 <= seconds <= 7200:
        raise argparse.ArgumentTypeError('duration must be between 1 and 7200 seconds')
    return seconds


async def serve(options):
    started_at = timestamp()
    manifest_path = options.manifest.resolve()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite a previous/active preview identity accidentally.
    with manifest_path.open('x', encoding='utf-8') as stream:
        json.dump({'status': 'preparing', 'pid': os.getpid(), 'started_at': started_at}, stream)
    root = Path(tempfile.mkdtemp(prefix='jarvis-mov-human-qa-')).resolve()
    os.environ['JARVIS_DATA_ROOT'] = str(root / 'isolated-default-data')
    os.environ['JARVIS_RUNTIME_DIR'] = str(root / 'isolated-default-runtime')
    instance = None
    manifest = {
        'schema_version': 1, 'status': 'starting', 'pid': os.getpid(),
        'started_at': started_at, 'root': str(root), 'worktree': str(ROOT),
        'startup_deadline_seconds': 120,
        'duration_seconds': options.duration, 'review_url': None,
        'content': 'QA synthétique : notes, image, agent et job contrôlés ; aucune exécution modèle.',
        'model_requests': 0, 'data_retained_after_shutdown': True,
        'ownership': 'Core and UI run inside this one Python process; only owned objects are closed.',
    }
    write_manifest(manifest_path, manifest)
    try:
        sys.path.insert(0, str(ROOT))
        harness = ROOT / 'tasks/jarvis-mouse-organization-viewer/slices/05-scene-integration-organize-viewer/qa/test_live_acceptance.py'
        specification = importlib.util.spec_from_file_location('jarvis_s05_live_acceptance', harness)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        instance = module.LiveAcceptance(root)
        await asyncio.wait_for(instance.start(), timeout=120)
        manifest.update(status='ready', ready_at=timestamp(),
            expires_at=(datetime.now(timezone.utc)+timedelta(seconds=options.duration)).isoformat(),
            review_url=str(instance.server.make_url('/')),
            core_url=f'http://127.0.0.1:{instance.process.port}',
            data_root=str(instance.process.data_root),
            runtime_root=str(root / 'control-runtime'), project_root=str(root))
        write_manifest(manifest_path, manifest)
        print(json.dumps({'status': 'ready', 'url': manifest['review_url'], 'pid': os.getpid(),
                          'manifest': str(manifest_path)}, ensure_ascii=False), flush=True)
        await asyncio.sleep(options.duration)
        manifest['status'] = 'stopped'
        manifest['stop_reason'] = 'bounded_duration_elapsed'
    except asyncio.CancelledError:
        manifest.update(status='stopped', stop_reason='owned_preview_interrupted')
        raise
    except Exception as exc:
        manifest.update(status='failed', failure=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        try:
            if instance is not None:
                if hasattr(instance, 'scene'):
                    await instance.close()
                else:
                    await instance.process.stop()
        except Exception as exc:
            manifest.update(status='cleanup_failed', cleanup_failure=f'{type(exc).__name__}: {exc}')
            raise
        finally:
            manifest['stopped_at'] = timestamp()
            write_manifest(manifest_path, manifest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path,
                        help='Explicit new JSON manifest path; existing files are refused')
    parser.add_argument('--duration', type=duration, default=600,
                        help='Ready lifetime in seconds, 1..7200 (default:600)')
    options = parser.parse_args()
    try:
        asyncio.run(serve(options))
    except KeyboardInterrupt:
        pass
