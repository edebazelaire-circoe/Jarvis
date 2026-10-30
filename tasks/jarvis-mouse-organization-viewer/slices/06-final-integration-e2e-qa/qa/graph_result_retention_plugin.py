"""Save the original Node driver's output without altering its browser plan."""
import hashlib
import json
import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def retain_graph_result(request, monkeypatch):
    if request.node.name != 'test_a_dense_graph_at_200_percent_and_in_forced_colours_stays_usable':
        yield
        return
    from tests.unit import test_status_centre_browser as driver
    original_run = driver.subprocess.run
    destination = Path(os.environ['JARVIS_GRAPH_REWORKED_RAW'])

    def retain(args, *positional, **kwargs):
        done = original_run(args, *positional, **kwargs)
        if isinstance(args, list) and len(args) > 1 and str(args[1]) == str(driver.HARNESS):
            destination.write_text(done.stdout, encoding='utf-8')
            destination.with_suffix('.metadata.json').write_text(json.dumps({
                'harness': str(driver.HARNESS),
                'harness_sha256': hashlib.sha256(driver.HARNESS.read_bytes()).hexdigest(),
                'node_returncode': done.returncode, 'stderr': done.stderr,
                'extra_cdp_calls': 0, 'harness_or_plan_modified_by_plugin': False,
            }, indent=2) + '\n', encoding='utf-8')
        return done

    monkeypatch.setattr(driver.subprocess, 'run', retain)
    yield
