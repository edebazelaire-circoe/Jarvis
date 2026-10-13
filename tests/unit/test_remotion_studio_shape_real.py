"""REAL proof of the workspace shape (QA Slice 12 rework, B1): a `remotion.config.js` planted in the Remotion Studio workspace is NOT run by
Node when Remotion Studio is reopened on the same scene (the kept-workspace path); it is moved into `studio-edits/` and the view says so.

Adapted from the QA probe that found it (the planted config wrote a marker file outside `work/`). Opt-in: `JARVIS_REMOTION_RUNTIME_DIR` (an
installed Remotion runtime, only READ: its `node_modules` is copied into a private throw-away data root, see
`test_remotion_studio_roundtrip_real_browser.private_runtime_copy`) and Node. Free loopback ports, private data root: the live Jarvis and
the user's own Remotion Studio are never contacted. Unit proofs of every planted kind: `test_remotion_studio_shape.py`.
"""

from __future__ import annotations

import shutil
import time

import pytest

from tests.fakes.remotion_player_stack import RemotionStack, runtime_dir_from_env
from tests.unit.presentation_playback_gate_world import PREFABS, make_deck
from tests.unit.test_remotion_studio_roundtrip_real_browser import private_runtime_copy, studio_runner

RUNTIME = runtime_dir_from_env()
pytestmark = [pytest.mark.asyncio,
              pytest.mark.skipif(RUNTIME is None or shutil.which("node") is None,
                                 reason="needs JARVIS_REMOTION_RUNTIME_DIR (an installed Remotion runtime) and node")]

OPEN = "/v1/local-capabilities/remotion/studio/open"
CLOSE = "/v1/local-capabilities/remotion/studio/close"
# What the QA probe planted: Node would run it at Remotion Studio's start and write a marker OUTSIDE the workspace.
CONFIG = ("const fs = require('node:fs'); const path = require('node:path');\n"
          "fs.writeFileSync(path.join(process.cwd(), '..', 'CONFIG_RAN.txt'), 'node ran remotion.config.js in ' + process.cwd());\n")


async def test_a_planted_remotion_config_is_set_aside_and_never_run_on_a_kept_reopen(tmp_path):
    private_runtime_copy(tmp_path)
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME, core_options=studio_runner) as stack:
        await make_deck(stack)
        studio = stack.data_root / "local_capabilities" / "remotion" / "runtime" / "studio"
        edits = stack.data_root / "local_capabilities" / "remotion" / "studio-edits"
        body = {"prefab_id": PREFABS[0], "version": 1, "acknowledge_unsandboxed_scene": True}
        status, opened = await stack.call("POST", OPEN, json=body)
        assert status == 200 and opened["studio"]["status"] == "ready", opened
        status, closed = await stack.call("POST", CLOSE, json={})
        assert closed["studio"]["status"] == "stopped"
        (studio / "work" / "remotion.config.js").write_text(CONFIG, encoding="utf-8")
        _status, view = await stack.call("GET", "/v1/local-capabilities/remotion/studio")
        assert view["studio"]["work_copy"]["modified_files"] == ["remotion.config.js"], "seen as an unpublished change: the kept path"
        started = time.monotonic()
        status, reopened = await stack.call("POST", OPEN, json=body)
        seconds = round(time.monotonic() - started, 1)
        try:
            studio_view = reopened["studio"]
            assert status == 200 and studio_view["status"] == "ready", reopened
            assert not (studio / "CONFIG_RAN.txt").exists(), "Node never ran the planted config"
            assert not (studio / "work" / "remotion.config.js").exists()
            copies = list(edits.glob("*/remotion.config.js"))
            assert len(copies) == 1 and copies[0].read_text(encoding="utf-8") == CONFIG, "moved aside, never deleted"
            assert studio_view["work_copy"]["set_aside"] == ["remotion.config.js"]
            assert any("remotion.config.js" in line for line in studio_view["diagnostics"]), "the launch says so"
            print(f"reopen with a planted remotion.config.js: ready in {seconds} s, marker absent, config set aside in "
                  f"studio-edits/{copies[0].parent.name}")
        finally:
            await stack.call("POST", CLOSE, json={})
