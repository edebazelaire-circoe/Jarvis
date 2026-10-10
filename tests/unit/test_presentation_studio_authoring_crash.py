"""Real process kills during an assembly (jarvis-interactive-presentation-studio, Slice 11).

The assembly publishes immutable prefab versions, then stores the whole Presentation with ONE folder rename. A real child process
runs it with a deterministic stop point (`checkpoint`, or a hook inside the store's file writes) that announces `paused` then sleeps;
the parent kills it (`Popen.kill()`: `TerminateProcess` on Windows, `SIGKILL` elsewhere) and reads the disk with a fresh stack. Every
state is one of: nothing; prefab versions no variant pins (reported by `reconcile`, never adopted, never deleted); a `.staging-*` folder
(swept at start); or the complete Presentation. Never a half-built one.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.fakes import presentation_studio_fake_author as fa
from tests.fakes.presentation_studio_authoring_env import AuthoringEnv

REPO = Path(__file__).resolve().parents[2]

CHILD = r"""
import asyncio, json, sys, time
from pathlib import Path
from jarvis.adapters import file_presentation_studio_store as store_module
from tests.fakes.presentation_studio_authoring_env import AuthoringEnv

root, pause_at, payload, writes = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), int(sys.argv[4])

def checkpoint(step):
    if step == pause_at:
        print("paused", flush=True)
        time.sleep(600)

if pause_at == "staging":
    real, seen = store_module._write_file, []
    def counting(path, text):
        seen.append(path.name)
        if len(seen) > writes:
            print("paused", flush=True)
            time.sleep(600)
        return real(path, text)
    store_module._write_file = counting

async def main():
    env = await AuthoringEnv(root).start(checkpoint=checkpoint)
    request = json.loads(payload.read_text(encoding="utf-8"))
    out = await env.authoring.assemble(request)
    print("finished", out.status, flush=True)

asyncio.run(main())
"""


def kill_at(root: Path, pause_at: str, request: dict, *, writes: int = 0) -> None:
    payload = root / "request.json"
    payload.write_text(json.dumps(request), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    child = subprocess.Popen([sys.executable, "-c", CHILD, str(root), pause_at, str(payload), str(writes)], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(root))
    try:
        line = child.stdout.readline().strip()
        if line != "paused":
            pytest.fail(f"child did not pause at {pause_at!r} (said {line!r}): {child.stderr.read()[-1200:]}")
    finally:
        child.kill()      # the process dies at exactly this instant, mid-assembly
        child.wait(timeout=30)
        child.stdout.close()
        child.stderr.close()
    assert child.returncode != 0


@pytest.fixture
def root(tmp_path) -> Path:
    path = tmp_path / "e"
    path.mkdir()
    return path


def request():
    return {"brief": fa.brief("directed"), "draft": fa.good_deck()}


async def test_a_kill_before_anything_is_published_leaves_nothing(root):
    kill_at(root, "validated", request())
    env = await AuthoringEnv(root).start()
    assert env.folders() == [] and env.prefab_versions() == {}
    assert (await env.authoring.reconcile())["unreferenced_prefabs"] == []
    assert (await env.assemble(**request())).status == "delivered"


async def test_a_kill_after_the_bundle_is_published_leaves_a_reported_unreferenced_version_and_no_presentation(root):
    kill_at(root, "published:1", request())
    env = await AuthoringEnv(root).start()
    assert env.folders() == [] and env.prefab_versions() == {fa.SLIDE: ["1"]}
    listing = await env.studio.list_presentations()
    assert listing.presentations == () and listing.problems == ()                       # no half-built Presentation anywhere
    report = await env.authoring.reconcile()
    assert report["pins_known"] is True and report["unreferenced_prefabs"] == [{"id": fa.SLIDE, "version": 1}]
    assert env.prefab_versions() == {fa.SLIDE: ["1"]}                                   # reported, never adopted or deleted
    out = await env.assemble(**request())                                               # the retry publishes version 2, not an adoption of 1
    assert out.status == "delivered" and out.to_dict()["prefabs"][0]["version"] == 2
    assert (await env.authoring.reconcile())["unreferenced_prefabs"] == [{"id": fa.SLIDE, "version": 1}]


async def test_a_kill_with_the_documents_built_but_not_stored_is_the_same_state(root):
    kill_at(root, "documents_ready", request())
    env = await AuthoringEnv(root).start()
    assert env.folders() == [] and env.prefab_versions() == {fa.SLIDE: ["1"], fa.COVER: ["1"]}       # both sources of the storyboard were published
    assert (await env.studio.list_presentations()).presentations == ()


@pytest.mark.parametrize("writes", [0, 2, 3])   # the draft has 1 variant, 1 score, 1 DA, then the manifest
async def test_a_kill_in_the_middle_of_the_store_leaves_a_staging_that_start_sweeps(root, writes):
    kill_at(root, "staging", request(), writes=writes)
    folder = root / "studio" / "presentations"
    assert sorted(p.name for p in folder.iterdir() if not p.name.startswith(".")) == []        # no Presentation folder at all
    staging = [p for p in folder.iterdir() if p.name.startswith(".staging-")]
    assert len(staging) == 1                                                                   # the partial work is quarantined, hidden
    env = await AuthoringEnv(root).start()
    assert (await env.studio.list_presentations()).presentations == ()                       # a staging is never listed
    await env.studio.start()                                                                  # Core's start sweeps it
    assert not [p for p in folder.iterdir() if p.name.startswith(".staging-")]
    assert env.studio.last_recovery is not None and env.studio.last_recovery.swept == 1
    assert (await env.assemble(**request())).status == "delivered"


async def test_a_kill_right_after_the_commit_finds_the_complete_presentation(root):
    kill_at(root, "created", request())
    env = await AuthoringEnv(root).start()
    [pid] = env.folders()
    view = await env.studio.get(pid)
    assert len(view.variants[0].scenes) == 12
    vid = view.presentation.active_variant_id
    assert (await env.studio.require_art_direction(pid, vid, serious=True))["status"] == "resolved"
    assert (await env.studio.get_score(pid, vid))["problems"] == []
    assert (await env.variants.check(pid))["clean"] is True
    assert (await env.authoring.reconcile())["unreferenced_prefabs"] == []                    # the published version is pinned
    started = await env.variants.start()
    assert started["unreadable"] == 0 and started["flagged"] == 0
