"""Arret brutal reel pendant un commit, un annuler et un retablir (jarvis-interactive-presentation-studio, Slice 08).

Un vrai sous-processus fait tourner la vraie pile Core du Studio (service, API d'edition, historique) sur un dossier de
donnees ; le parent le tue (`Popen.kill()` : `TerminateProcess` sous Windows, `SIGKILL` ailleurs), soit a des instants
varies au milieu d'une boucle d'edition/annuler/retablir, soit a un point d'arret deterministe (le nouveau texte est
complet dans son temporaire, le remplacement n'a pas eu lieu). Apres le redemarrage : le document n'est jamais en arriere
de la derniere revision acquittee, jamais tronque ni melange, le temporaire orphelin n'est jamais adopte, la reprise le
dit, et l'historique est explicitement indisponible. Contrat : `docs/presentation-studio.md` > *Persistence and undo contract*.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time

import pytest

from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.core.presentation_studio_autosave import PresentationStudioHistory
from jarvis.core.presentation_studio_edit import PresentationStudioEditService
from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.domain.presentation_studio_history import HistoryStatus

REPO = Path(__file__).resolve().parents[2]
PAD = 7_000  # per scene, 12 scenes: a ~90 KB document, so the window of a non-atomic write is wide

CHILD = r"""
import asyncio, json, sys, time
from pathlib import Path
from jarvis.adapters import file_presentation_studio_store as module
from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.core.presentation_studio_autosave import PresentationStudioHistory
from jarvis.core.presentation_studio_edit import PresentationStudioEditService
from jarvis.core.presentation_studio_service import PresentationStudioService

root, mode, pad = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
S1 = "pss_000000000001"
scenes = [{"scene_id": "pss_%012x" % i, "prefab": {"id": "jarvis.window", "version": 1}, "title": "t0",
           "data": {"pad": "p" * pad}} for i in range(1, 13)]

async def main():
    studio = PresentationStudioService(FilePresentationStudioStore(root))
    history = PresentationStudioHistory(studio)
    edit = PresentationStudioEditService(studio, history=history)
    history.bind(edit)
    await studio.start()
    listing = await studio.list_presentations()
    if listing.presentations:
        pid = listing.presentations[0]["presentation_id"]
        vid = listing.presentations[0]["active_variant_id"]
    else:
        view = await studio.create({"title": "Atelier"})
        pid, vid = view.presentation.presentation_id, view.presentation.active_variant_id
        base = await studio.get_variant(pid, vid)
        await studio.save_variant(pid, vid, {"expected_revision": base.revision, "title": base.title, "scenes": scenes,
                                             "art_direction_id": None, "score_id": None})
    async def title():
        return (await studio.get_variant(pid, vid)).scenes[0].title
    async def rename(n):
        revision = (await studio.get_variant(pid, vid)).revision
        return await edit.edit(pid, vid, {"actor": "user", "mode": "commit", "basis": {"variant_revision": revision},
                                          "ops": [{"op": "scene.rename", "scene_id": S1, "title": "t%d" % n}]})
    def hang_next():
        def hang(source, target):
            print("paused", flush=True)
            time.sleep(600)
        module.replace_with_retry = hang
    async def current():
        v = await studio.get_variant(pid, vid)
        return v.revision, v.scenes[0].title

    if mode in ("pause_edit", "pause_undo", "pause_redo"):
        await rename(1)
        await rename(2)
        print("acked", *await current(), flush=True)
        if mode == "pause_redo":
            await history.undo(pid, vid, {"actor": "user"})
            print("acked", *await current(), flush=True)
        hang_next()
        if mode == "pause_edit":
            await rename(3)
        elif mode == "pause_undo":
            await history.undo(pid, vid, {"actor": "user"})
        else:
            await history.redo(pid, vid, {"actor": "user"})
        return
    # loop: edits, undos and redos forever; "intent" before each commit, "ack" after its acknowledgement
    titles, cursor, n = [await title()], 0, 100
    pattern = "eeuurreuruueer"
    step = 0
    while True:
        kind = pattern[step % len(pattern)]
        step += 1
        revision = (await studio.get_variant(pid, vid)).revision
        if kind == "e":
            n += 1
            target = "t%d" % n
        elif kind == "u" and cursor > 0:
            target = titles[cursor - 1]
        elif kind == "r" and cursor < len(titles) - 1:
            target = titles[cursor + 1]
        else:
            continue
        print("intent", revision + 1, target, flush=True)
        if kind == "e":
            result = await rename(n)
            assert result.status.value == "applied", result.message
            titles, cursor = titles[:cursor + 1] + [target], cursor + 1
        else:
            result = await (history.undo if kind == "u" else history.redo)(pid, vid, {"actor": "user"})
            assert result.status.value == "applied", result.message
            cursor += -1 if kind == "u" else 1
        print("ack", result.revision, target, flush=True)

asyncio.run(main())
"""


def launch(root: Path, mode: str) -> subprocess.Popen:
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    return subprocess.Popen([sys.executable, "-c", CHILD, str(root), mode, str(PAD)], env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, cwd=str(root))


def kill(child: subprocess.Popen) -> list[list[str]]:
    """Tue l'enfant en pleine boucle et rend ce qu'il avait deja ecrit (le tube garde les lignes apres la mort)."""

    child.kill()
    child.wait(timeout=30)
    rest = [line.split() for line in child.stdout.read().splitlines()]
    child.stdout.close()
    child.stderr.close()
    assert child.returncode != 0  # killed, not a clean exit
    return rest


def read_until(child: subprocess.Popen, wanted: str, count: int = 1) -> list[list[str]]:
    seen = []
    while sum(1 for line in seen if line[0] == wanted) < count:
        line = child.stdout.readline()
        if not line:
            pytest.fail(f"child ended early: {child.stderr.read()[-1200:]}")
        seen.append(line.split())
    return seen


async def reopen(root: Path):
    """Un nouveau Core sur les memes fichiers : service, API d'edition, historique."""

    studio = PresentationStudioService(FilePresentationStudioStore(root))
    history = PresentationStudioHistory(studio)
    edit = PresentationStudioEditService(studio, history=history)
    history.bind(edit)
    await studio.start()
    return studio, edit, history


async def only_variant(studio):
    (row,) = (await studio.list_presentations()).presentations
    return row["presentation_id"], row["active_variant_id"]


@pytest.mark.parametrize("after_acks", [3, 8, 15])
async def test_killing_during_an_edit_undo_redo_loop_never_leaves_the_document_behind_or_torn(tmp_path, after_acks):
    for round_number in range(4):  # the same tree survives repeated crashes
        child = launch(tmp_path, "loop")
        try:
            lines = read_until(child, "ack", after_acks)
            time.sleep(random.Random(after_acks * 31 + round_number).random() * 0.02)  # land anywhere in the next commit
        finally:
            lines += kill(child)
        acks = [line for line in lines if line[0] == "ack"]
        intents = [line for line in lines if line[0] == "intent"]
        last_ack = (int(acks[-1][1]), acks[-1][2])
        studio, edit, history = await reopen(tmp_path)
        pid, vid = await only_variant(studio)
        variant = await studio.get_variant(pid, vid)  # parses: never torn
        assert len(variant.scenes) == 12 and all(s.data["pad"] == "p" * PAD for s in variant.scenes)
        stored = (variant.revision, variant.scenes[0].title)
        assert stored[0] >= last_ack[0], ("behind the last acknowledged revision", stored, last_ack)
        if stored[0] == last_ack[0]:
            assert stored[1] == last_ack[1]
        else:  # the commit that was in flight when the process died had already replaced the file
            assert stored[0] == last_ack[0] + 1
            assert [str(stored[0]), stored[1]] == intents[-1][1:], (stored, intents[-2:])
        assert studio.last_recovery.unreadable == () and studio.last_recovery.active_loaded == 1
        undone = await history.undo(pid, vid, {"actor": "user"})
        assert undone.status is HistoryStatus.UNAVAILABLE and undone.reason == "not_recorded_since_start"
        assert (await studio.get_variant(pid, vid)).revision == variant.revision  # the unavailable answer wrote nothing
    assert not list(tmp_path.rglob("*.tmp"))  # every start swept the leftovers of the kill before it


@pytest.mark.parametrize("mode, acked_title", [("pause_edit", "t2"), ("pause_undo", "t2"), ("pause_redo", "t1")])
async def test_a_kill_at_the_worst_instant_of_a_commit_an_undo_or_a_redo_keeps_the_last_acknowledged_state(
        tmp_path, mode, acked_title):
    child = launch(tmp_path, mode)
    lines = []
    try:
        lines = read_until(child, "paused")
    finally:
        kill(child)
    acks = [line for line in lines if line[0] == "acked"]
    last_ack = (int(acks[-1][1]), acks[-1][2])
    assert last_ack[1] == acked_title
    temporaries = list((tmp_path / "presentations").rglob("*.tmp"))
    assert len(temporaries) == 1, "the complete new text sat in its temporary when the process died"
    pending = json.loads(temporaries[0].read_text(encoding="utf-8"))
    assert pending["revision"] == last_ack[0] + 1  # complete, but never promoted: the replace did not happen
    stored_text = next((tmp_path / "presentations").rglob("psv_*.json")).read_text(encoding="utf-8")
    assert json.loads(stored_text)["revision"] == last_ack[0]  # the old document, whole

    studio, edit, history = await reopen(tmp_path)  # restart: sweep + recovery
    assert studio.last_recovery.swept == 1 and studio.last_recovery.unreadable == ()
    assert not list((tmp_path / "presentations").rglob("*.tmp"))
    pid, vid = await only_variant(studio)
    variant = await studio.get_variant(pid, vid)
    assert (variant.revision, variant.scenes[0].title) == last_ack  # the last acknowledged state, exactly
    for step in (history.undo, history.redo):
        result = await step(pid, vid, {"actor": "user"})
        assert result.status is HistoryStatus.UNAVAILABLE and result.reason == "not_recorded_since_start"
    # and the product keeps working: a new edit commits on the recovered revision, then undoes
    done = await edit.edit(pid, vid, {"actor": "user", "mode": "commit", "basis": {"variant_revision": variant.revision},
                                      "ops": [{"op": "scene.rename", "scene_id": "pss_000000000001", "title": "apres"}]})
    assert done.status.value == "applied" and done.revision == last_ack[0] + 1
    assert (await history.undo(pid, vid, {"actor": "user"})).status is HistoryStatus.APPLIED
    assert (await studio.get_variant(pid, vid)).scenes[0].title == acked_title
