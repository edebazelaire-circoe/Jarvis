"""Arrêt brutal réel pendant un branchement, un archivage et une restauration (jarvis-interactive-presentation-studio, Slice 16).

Pas de transaction multi-fichiers : chaque opération a un ordre et une règle de réconciliation par état intermédiaire
(`docs/presentation-studio.md` › *Variant graph and operations contract*). Un vrai sous-processus fait l'opération avec un
point d'arrêt déterministe (`checkpoint`) qui annonce `paused` puis dort ; le parent le tue (`Popen.kill()` :
`TerminateProcess` sous Windows, `SIGKILL` ailleurs) et relit le disque avec un Core neuf : chaque état est connu, rapporté,
et la reprise (`PresentationStudioVariants.start`) est déterministe. Rien n'est jamais adopté ni supprimé en silence.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.core.presentation_studio_variants import PresentationStudioVariants
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from tests.unit.test_presentation_studio_score_service import S1, S2, Sink, score_body, scene_body

REPO = Path(__file__).resolve().parents[2]
SECRET = b"k" * 32

CHILD = r"""
import asyncio, json, sys, time
from pathlib import Path
from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.core.presentation_studio_variants import PresentationStudioVariants

root, mode, pause_at, pid, arg = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]

def checkpoint(step):
    if step == pause_at:
        print("paused", flush=True)
        time.sleep(600)

async def main():
    studio = PresentationStudioService(FilePresentationStudioStore(root))
    variants = PresentationStudioVariants(studio, secret=b"k" * 32, checkpoint=checkpoint)
    if mode == "create":
        await variants.create_branch(pid, {"title": "Enfant", "source_variant_id": arg})
    elif mode == "archive":
        planned = await variants.plan_archive(pid, arg)
        await variants.archive(pid, arg, {"confirmation": planned["confirmation"]})
    elif mode == "restore":
        await variants.restore(pid, arg, {"with_descendants": True})
    elif mode == "switch":
        await variants.switch(pid, arg)
    print("finished", flush=True)

asyncio.run(main())
"""


class World:
    """Une Presentation sur disque : 1 -> {a -> {c}, b}, partition sur la variante 1. Le parent la prépare, l'enfant opère."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.sink = Sink()
        self.studio = PresentationStudioService(FilePresentationStudioStore(root), diagnostics=self.sink)
        self.variants = PresentationStudioVariants(self.studio, diagnostics=self.sink, secret=SECRET)

    async def build(self) -> World:
        view = await self.studio.create({"title": "Atelier"})
        self.pid, self.one = view.presentation.presentation_id, view.presentation.active_variant_id
        variant = await self.studio.get_variant(self.pid, self.one)
        variant = await self.studio.save_variant(self.pid, self.one, {
            "expected_revision": variant.revision, "title": variant.title, "scenes": [scene_body(S1), scene_body(S2)],
            "art_direction_id": None, "score_id": None})
        variant = await self.studio.create_score(self.pid, self.one, {"expected_variant_revision": variant.revision, **score_body()})
        variant = await self.studio.get_variant(self.pid, self.one)
        await self.studio.create_fallback_art_direction(self.pid, self.one, {"expected_variant_revision": variant.revision})
        self.a = (await self.variants.create_branch(self.pid, {"title": "a"}))["variant"]["variant_id"]
        self.b = (await self.variants.create_branch(self.pid, {"title": "b", "source_variant_id": self.one}))["variant"]["variant_id"]
        self.c = (await self.variants.create_branch(self.pid, {"title": "c", "source_variant_id": self.a}))["variant"]["variant_id"]
        return self

    @property
    def folder(self) -> Path:
        return self.root / "presentations" / self.pid

    def files(self, where: str) -> set[str]:
        folder = self.folder / where
        return {p.stem for p in folder.glob("*.json")} if folder.exists() else set()

    def digest(self, where: str, variant_id: str) -> str:
        return hashlib.sha256((self.folder / where / f"{variant_id}.json").read_bytes()).hexdigest()

    def fresh(self) -> PresentationStudioVariants:
        """Un Core neuf sur les mêmes fichiers (le processus tué n'existe plus)."""

        self.studio = PresentationStudioService(FilePresentationStudioStore(self.root), diagnostics=self.sink)
        self.variants = PresentationStudioVariants(self.studio, diagnostics=self.sink, secret=SECRET)
        return self.variants


def kill_at(root: Path, mode: str, pause_at: str, pid: str, arg: str) -> None:
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    child = subprocess.Popen([sys.executable, "-c", CHILD, str(root), mode, pause_at, pid, arg], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(root))
    try:
        line = child.stdout.readline().strip()
        if line != "paused":
            pytest.fail(f"child did not pause at {pause_at!r} (said {line!r}): {child.stderr.read()[-800:]}")
    finally:
        child.kill()  # the process dies at exactly this instant, mid-operation
        child.wait(timeout=30)
        child.stdout.close()
        child.stderr.close()
    assert child.returncode != 0


async def refused_code(awaitable, code: C) -> PresentationStudioError:
    with pytest.raises(PresentationStudioError) as caught:
        await awaitable
    assert caught.value.code is code, caught.value
    return caught.value


@pytest.fixture
async def world(tmp_path) -> World:
    return await World(tmp_path).build()


# ------------------------------------------------------------------ brancher : chaque point d'arrêt

async def test_a_kill_right_after_the_number_is_allocated_leaves_a_gap_and_no_trace_of_a_branch(world):
    before = world.files("variants")
    kill_at(world.root, "create", "allocated", world.pid, world.a)
    variants = world.fresh()
    report = await variants.start()
    assert report["unreadable"] == 0 and world.files("variants") == before
    view = await world.studio.get(world.pid)
    assert view.presentation.variant_counter == 5 and len(view.variants) == 4  # 1..4 used, 5 consumed by the dead create
    answer = await variants.create_branch(world.pid, {"title": "apres", "source_variant_id": world.a})
    assert answer["node"]["variant_number"] == 6, "5 is a hole, never handed out again"
    assert (await variants.check(world.pid))["clean"] is True


async def test_a_kill_after_the_linked_score_copy_leaves_an_orphan_score_that_is_reported_not_deleted(world):
    scores_before = world.files("scores")
    kill_at(world.root, "create", "linked:score", world.pid, world.a)
    orphan = world.files("scores") - scores_before
    assert len(orphan) == 1
    variants = world.fresh()
    await variants.start()
    assert world.files("scores") == scores_before | orphan, "never deleted"
    report = await variants.check(world.pid)
    assert report["orphan_linked"] == {"score": sorted(orphan), "art_direction": []} and report["orphan_variants"] == []
    graph = await variants.graph(world.pid)
    assert len(graph["nodes"]) == 4 and graph["variant_counter"] == 5
    assert (await variants.create_branch(world.pid, {"title": "apres"}))["node"]["variant_number"] == 6


async def test_a_kill_after_the_art_direction_copy_leaves_both_linked_orphans_reported_and_kept(world):
    scores_before, das_before = world.files("scores"), world.files("art_directions")
    kill_at(world.root, "create", "linked:art_direction", world.pid, world.one)
    new_score, new_da = world.files("scores") - scores_before, world.files("art_directions") - das_before
    assert len(new_score) == 1 and len(new_da) == 1
    variants = world.fresh()
    await variants.start()
    assert world.files("art_directions") == das_before | new_da, "never deleted"
    report = await variants.check(world.pid)
    assert report["orphan_linked"] == {"score": sorted(new_score), "art_direction": sorted(new_da)} and report["orphan_variants"] == []
    assert len((await variants.graph(world.pid))["nodes"]) == 4
    answer = await variants.create_branch(world.pid, {"title": "apres"})
    assert answer["node"]["variant_number"] == 6 and answer["variant"]["art_direction_id"] not in new_da
    again = await variants.check(world.pid)
    assert again["orphan_linked"]["art_direction"] == sorted(new_da), "the orphan stays reported; the new branch has its own copy"


async def test_a_kill_after_the_variant_file_but_before_the_manifest_leaves_a_reported_orphan_never_adopted(world):
    live_before = world.files("variants")
    kill_at(world.root, "create", "variant_written", world.pid, world.a)
    orphan = world.files("variants") - live_before
    assert len(orphan) == 1
    (orphan_id,) = orphan
    orphan_bytes = world.digest("variants", orphan_id)
    variants = world.fresh()
    summary = await variants.start()
    assert summary["flagged"] == 1 and summary["moved"] == 0
    graph = await variants.graph(world.pid)
    assert orphan_id not in {n["variant_id"] for n in graph["nodes"]}, "an orphan is never adopted into the graph"
    assert graph["reconciliation"]["orphan_variants"] == [orphan_id]
    assert world.digest("variants", orphan_id) == orphan_bytes and orphan_id in world.files("variants"), "and never deleted"
    stray = json.loads((world.folder / "variants" / f"{orphan_id}.json").read_text(encoding="utf-8"))
    assert stray["variant_number"] == 5 and stray["parent_variant_id"] == world.a  # a human can read what it was
    assert (await world.studio.get(world.pid)).presentation.variant_counter == 5, "its number is already spent"
    answer = await variants.create_branch(world.pid, {"title": "apres", "source_variant_id": world.a})
    assert answer["node"]["variant_number"] == 6
    # the next restart still reports it, as a warning in the log: an orphan is never silently forgotten
    again = world.fresh()
    await again.start()
    rows = [(kind, level, data) for kind, level, data in world.sink.rows if kind == "core.presentation_studio.reconcile_orphans"]
    assert rows and rows[-1][1] == "warning" and rows[-1][2]["orphan_variants"] == [orphan_id]
    assert (await again.check(world.pid))["orphan_variants"] == [orphan_id]


async def test_a_kill_after_the_manifest_write_is_a_complete_branch(world):
    kill_at(world.root, "create", "committed", world.pid, world.a)
    variants = world.fresh()
    await variants.start()
    graph = await variants.graph(world.pid)
    assert [n["variant_number"] for n in graph["nodes"]] == [1, 2, 3, 4, 5] and graph["nodes"][-1]["parent_variant_id"] == world.a
    assert (await variants.check(world.pid))["clean"] is True
    score_ids = {n["variant_number"]: (await world.studio.get_variant(world.pid, n["variant_id"])).score_id
                 for n in graph["nodes"] if n["variant_number"] in (1, 5)}
    assert len(set(score_ids.values())) == 2 and None not in score_ids.values()
    das = {n["variant_number"]: (await world.studio.get_variant(world.pid, n["variant_id"])).art_direction_id
           for n in graph["nodes"] if n["variant_number"] in (1, 5)}
    assert len(set(das.values())) == 2 and None not in das.values()


# ------------------------------------------------------------------ archiver : chaque point d'arrêt

async def test_a_kill_after_the_first_file_moved_is_rolled_back_by_the_next_start_and_the_archive_can_be_redone(world):
    # archiving `a` moves its subtree {a, c}: c first (higher number), then a
    kill_at(world.root, "archive", "moved:1", world.pid, world.a)
    assert world.files("archive") == {world.c} and world.files("variants") == {world.one, world.a, world.b}
    with pytest.raises(PresentationStudioError) as torn:  # a read before the restart report: visible, never silent
        await PresentationStudioService(FilePresentationStudioStore(world.root)).get(world.pid)
    assert torn.value.code is C.CORRUPT_DOCUMENT and "missing" in torn.value.message
    variants = world.fresh()
    summary = await variants.start()
    assert summary["moved"] == 1
    assert world.files("archive") == set() and world.files("variants") == {world.one, world.a, world.b, world.c}
    graph = await variants.graph(world.pid, include_archived=True)
    assert [n["state"] for n in graph["nodes"]] == ["live"] * 4
    assert graph["reconciliation"]["moved"] == [{"variant_id": world.c, "to": "live"}]
    plan = await variants.plan_archive(world.pid, world.a)
    done = await variants.archive(world.pid, world.a, {"confirmation": plan["confirmation"]})
    assert done["count"] == 2


async def test_a_kill_after_every_file_moved_but_before_the_manifest_is_rolled_back_as_a_whole(world):
    kill_at(world.root, "archive", "moved:2", world.pid, world.a)
    assert world.files("archive") == {world.a, world.c}
    variants = world.fresh()
    summary = await variants.start()
    assert summary["moved"] == 2 and world.files("archive") == set()
    view = await world.studio.get(world.pid)
    assert len(view.variants) == 4 and view.presentation.archived == ()


async def test_a_kill_after_the_manifest_write_is_a_complete_archive_and_restore_brings_it_back(world):
    before = {v: world.digest("variants", v) for v in (world.a, world.c)}
    kill_at(world.root, "archive", "manifest_written", world.pid, world.a)
    variants = world.fresh()
    summary = await variants.start()
    assert summary["moved"] == 0 and summary["flagged"] == 0
    assert world.files("archive") == {world.a, world.c} and world.files("variants") == {world.one, world.b}
    graph = await variants.graph(world.pid, include_archived=True)
    assert {n["state"] for n in graph["nodes"] if n["variant_id"] in (world.a, world.c)} == {"archived"}
    restored = await variants.restore(world.pid, world.c)
    assert restored["count"] == 2 and {v: world.digest("variants", v) for v in (world.a, world.c)} == before


# ------------------------------------------------------------------ restaurer

async def test_a_kill_in_the_middle_of_a_restore_is_rolled_back_to_the_archived_state(world):
    plan = await world.variants.plan_archive(world.pid, world.a)
    await world.variants.archive(world.pid, world.a, {"confirmation": plan["confirmation"]})
    kill_at(world.root, "restore", "moved:1", world.pid, world.a)
    assert len(world.files("variants")) == 3 and len(world.files("archive")) == 1
    variants = world.fresh()
    summary = await variants.start()
    assert summary["moved"] == 1 and world.files("archive") == {world.a, world.c} and world.files("variants") == {world.one, world.b}
    assert {n["state"] for n in (await variants.graph(world.pid, include_archived=True))["nodes"]
            if n["variant_id"] in (world.a, world.c)} == {"archived"}
    done = await variants.restore(world.pid, world.a, {"with_descendants": True})
    assert done["count"] == 2


async def test_a_kill_after_the_restore_manifest_is_a_complete_restore(world):
    plan = await world.variants.plan_archive(world.pid, world.a)
    await world.variants.archive(world.pid, world.a, {"confirmation": plan["confirmation"]})
    kill_at(world.root, "restore", "manifest_written", world.pid, world.a)
    variants = world.fresh()
    summary = await variants.start()
    assert summary["moved"] == 0 and world.files("archive") == set() and len(world.files("variants")) == 4
    assert (await variants.check(world.pid))["clean"] is True


async def test_a_kill_never_changes_a_variant_file_it_does_not_own(world):
    others = {v: world.digest("variants", v) for v in (world.one, world.b)}
    for step in ("allocated", "linked:score", "variant_written"):
        kill_at(world.root, "create", step, world.pid, world.a)
        world.fresh()
    kill_at(world.root, "archive", "moved:1", world.pid, world.a)
    await world.fresh().start()
    assert {v: world.digest("variants", v) for v in others} == others


# ------------------------------------------------------------------ activer : le manifeste seul, un seul remplacement atomique

def manifest_active(world: World) -> str:
    return json.loads((world.folder / "presentation.json").read_text(encoding="utf-8"))["active_variant_id"]


async def test_a_kill_just_before_the_switch_is_written_leaves_the_previous_active_variant_and_a_consistent_manifest(world):
    files_before = {v: world.digest("variants", v) for v in (world.one, world.a, world.b, world.c)}
    revision = (await world.studio.get(world.pid)).presentation.revision
    kill_at(world.root, "switch", "switch_validated", world.pid, world.b)
    assert manifest_active(world) == world.one
    variants = world.fresh()
    summary = await variants.start()
    assert summary["flagged"] == 0 and summary["moved"] == 0 and summary["unreadable"] == 0
    view = await world.studio.get(world.pid)
    assert view.presentation.active_variant_id == world.one and view.presentation.revision == revision
    assert {v: world.digest("variants", v) for v in files_before} == files_before
    assert (await variants.switch(world.pid, world.b))["changed"] is True  # and the retry works


async def test_a_kill_right_after_the_switch_is_written_keeps_the_new_active_variant_whole(world):
    kill_at(world.root, "switch", "switched", world.pid, world.b)
    variants = world.fresh()
    summary = await variants.start()
    assert summary["flagged"] == 0 and summary["moved"] == 0
    view = await world.studio.get(world.pid)
    assert view.presentation.active_variant_id == world.b and view.active_variant().variant_id == world.b
    assert (await variants.check(world.pid))["clean"] is True
    assert (await variants.switch(world.pid, world.b))["changed"] is False


PENDING_CHILD = r"""
import sys, time
from pathlib import Path
from jarvis.adapters import file_presentation_studio_store as module

store = module.FilePresentationStudioStore(Path(sys.argv[1]))
pid = sys.argv[2]
text = store.read_manifest(pid).replace(sys.argv[3], sys.argv[4])

def hang(source, target):
    print("paused", flush=True)
    time.sleep(600)

module.replace_with_retry = hang
store.write_manifest(pid, text)
"""


async def test_a_kill_while_the_manifest_replace_is_pending_keeps_the_old_manifest_whole(world):
    """Worst instant: the new manifest is complete in its temporary, the atomic replace has not happened."""

    before = (world.folder / "presentation.json").read_bytes()
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    child = subprocess.Popen([sys.executable, "-c", PENDING_CHILD, str(world.root), world.pid, world.one, world.b], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(world.root))
    try:
        assert child.stdout.readline().strip() == "paused", child.stderr.read()[-500:]
    finally:
        child.kill()
        child.wait(timeout=30)
        child.stdout.close()
        child.stderr.close()
    assert (world.folder / "presentation.json").read_bytes() == before
    variants = world.fresh()
    assert (await variants.start())["unreadable"] == 0
    await world.studio.start()  # the Slice 02 sweep clears our torn temporary, never a document
    await world.studio.wait_recovered()
    assert not list(world.folder.glob("*.tmp")) and (world.folder / "presentation.json").read_bytes() == before


# ------------------------------------------------------------------ première réécriture d'un manifeste v1 : copie gardée

V1_CHILD = r"""
import sys, time
from pathlib import Path
from jarvis.adapters import file_presentation_studio_store as module

store = module.FilePresentationStudioStore(Path(sys.argv[1]))
pid, v2_text = sys.argv[2], Path(sys.argv[3]).read_text(encoding="utf-8")
calls = []
real = module.replace_with_retry

def counting(source, target):
    calls.append(target)
    if len(calls) == 2:  # the copy (1st replace) is on disk, the new manifest (2nd replace) is not
        print("paused", flush=True)
        time.sleep(600)
    return real(source, target)

module.replace_with_retry = counting
store.write_manifest(pid, v2_text)
"""


async def test_a_kill_between_the_v1_copy_and_the_first_v2_manifest_keeps_the_copy_whole_and_the_next_write_never_replaces_it(tmp_path):
    world = await World(tmp_path).build()
    manifest = world.folder / "presentation.json"
    v1 = {**json.loads(manifest.read_text(encoding="utf-8")), "schema_version": 1}
    v1["variants"] = [{"variant_id": e["variant_id"], "variant_number": e["variant_number"]} for e in v1["variants"]]
    del v1["archived"]
    manifest.write_bytes((json.dumps(v1, indent=2) + chr(10)).encode("utf-8"))
    original = manifest.read_bytes()
    v2_file = tmp_path / "v2.json"
    v2_file.write_text(json.dumps({**v1, "schema_version": 2, "variants": [dict(e, rationale="", created_by="system", sources=[], preview_id=None)
                                                                          for e in v1["variants"]], "archived": []}), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    child = subprocess.Popen([sys.executable, "-c", V1_CHILD, str(world.root), world.pid, str(v2_file)], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(world.root))
    try:
        assert child.stdout.readline().strip() == "paused", child.stderr.read()[-500:]
    finally:
        child.kill()
        child.wait(timeout=30)
        child.stdout.close()
        child.stderr.close()
    backup = world.folder / "presentation.json.v1.bak"
    assert backup.read_bytes() == original and manifest.read_bytes() == original, "copy whole, manifest still the v1 text"
    variants = world.fresh()
    await variants.start()
    assert backup.read_bytes() == original, "reading and reconciling never touch the copy"
    await variants.create_branch(world.pid, {"title": "premiere ecriture v2"})
    assert json.loads(manifest.read_text(encoding="utf-8"))["schema_version"] == 2
    assert backup.read_bytes() == original, "the first v2 write found the copy and kept it"
    await variants.create_branch(world.pid, {"title": "deuxieme"})
    assert backup.read_bytes() == original and not list(world.folder.glob("*.v2.bak"))
    world.studio.store.sweep()
    assert backup.exists(), "the sweep never deletes the copy"
