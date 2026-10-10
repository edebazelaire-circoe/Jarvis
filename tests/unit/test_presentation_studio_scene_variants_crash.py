"""Arret brutal reel pendant un choix de variante locale (jarvis-interactive-presentation-studio, Slice 17).

Un vrai sous-processus fait tourner la vraie pile Core du Studio (service, API d'edition, historique) sur un dossier de donnees
et choisit sans cesse entre quatre variantes locales aux contenus distincts ; le parent le tue (`Popen.kill()`), soit a des
instants varies, soit au pire instant d'un choix (le nouveau texte est complet dans son temporaire, le remplacement n'a pas eu
lieu). Apres le redemarrage : le document est entier (jamais un melange), il est a la derniere revision acquittee ou a celle qui
etait en cours, et **aucun contenu n'est perdu ni echange** : chaque variante locale a exactement le contenu qu'elle avait
(la scene vivante pour la choisie, son emplacement pour les autres). Contrat : `docs/presentation-studio.md` ›
*Scene-local variant contract*, tableau des modes de panne.
"""

from __future__ import annotations

import hashlib
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
from jarvis.domain.prefab import canonical_json
from jarvis.domain.presentation_studio_history import HistoryStatus

REPO = Path(__file__).resolve().parents[2]
PAD = 5_000  # 11 padding scenes of 5 KB: a ~65 KB document, so the window of a non-atomic write is wide

CHILD = r"""
import asyncio, hashlib, json, sys, time
from pathlib import Path
from jarvis.adapters import file_presentation_studio_store as module
from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.core.presentation_studio_autosave import PresentationStudioHistory
from jarvis.core.presentation_studio_edit import PresentationStudioEditService
from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.domain.prefab import canonical_json

root, mode, pad = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
S1 = "pss_000000000001"
IDS = ["psx_%012x" % n for n in range(1, 5)]
STAMP = "2026-10-08T10:00:00.000000Z"

def content(n):
    return {"prefab": {"id": "jarvis.window", "version": 1}, "props": {}, "data": {"pad": ("v%d-" % n) * 400},
            "controls": [], "anchors": []}

def first_scene():
    items = []
    for n, vid in enumerate(IDS, start=1):
        meta = {"variant_id": vid, "label": "V%d" % n, "rationale": "", "source": "current" if n == 1 else IDS[0],
                "created_by": "user", "created_at": STAMP}
        items.append(meta if n == 1 else {**meta, "content": content(n)})
    return {"scene_id": S1, "prefab": {"id": "jarvis.window", "version": 1}, "title": "t0", "props": {},
            "data": content(1)["data"], "controls": [], "anchors": [], "scene_variants": {"current_id": IDS[0], "items": items}}

scenes = [first_scene()] + [{"scene_id": "pss_%012x" % i, "prefab": {"id": "jarvis.window", "version": 1}, "title": "t0",
                              "data": {"pad": "p" * pad}} for i in range(2, 13)]

def contents_map(variant):
    scene = variant.scenes[0]
    sv = scene.scene_variants
    return {item.variant_id: hashlib.sha1(canonical_json(scene.live_content() if item.content is None else item.content).encode()).hexdigest()
            for item in sv.items}

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
    async def pick(target):
        revision = (await studio.get_variant(pid, vid)).revision
        return await edit.edit(pid, vid, {"actor": "user", "mode": "commit", "basis": {"variant_revision": revision},
                                          "ops": [{"op": "scene_variant.select", "scene_id": S1, "variant_id": target}]})
    async def state():
        v = await studio.get_variant(pid, vid)
        return v.revision, v.scenes[0].scene_variants.current_id, contents_map(v)

    revision, current, truth = await state()
    print("map", json.dumps(truth, sort_keys=True, separators=(",", ":")), flush=True)
    if mode == "pause_select":
        await pick(IDS[1])
        revision, current, _ = await state()
        print("acked", revision, current, flush=True)
        module.replace_with_retry = lambda source, target: (print("paused", flush=True), time.sleep(600))
        await pick(IDS[2])
        return
    order = [IDS[1], IDS[3], IDS[0], IDS[2], IDS[1], IDS[0], IDS[3], IDS[2]]
    step = 0
    while True:
        target = order[step % len(order)]
        step += 1
        revision = (await studio.get_variant(pid, vid)).revision
        print("intent", revision + 1, target, flush=True)
        result = await pick(target)
        assert result.status.value == "applied", result.message
        if step % 5 == 0:
            undone = await history.undo(pid, vid, {"actor": "user"})
            assert undone.status.value == "applied", undone.message
            print("ack", undone.revision, "undo", flush=True)
        else:
            print("ack", result.revision, target, flush=True)

asyncio.run(main())
"""

IDS = ["psx_%012x" % n for n in range(1, 5)]


def launch(root: Path, mode: str) -> subprocess.Popen:
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    return subprocess.Popen([sys.executable, "-c", CHILD, str(root), mode, str(PAD)], env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, cwd=str(root))


def kill(child: subprocess.Popen) -> list[list[str]]:
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
    studio = PresentationStudioService(FilePresentationStudioStore(root))
    history = PresentationStudioHistory(studio)
    edit = PresentationStudioEditService(studio, history=history)
    history.bind(edit)
    await studio.start()
    await studio.wait_recovered()
    return studio, edit, history


def contents_map(variant) -> dict[str, str]:
    scene = variant.scenes[0]
    return {item.variant_id: hashlib.sha1(canonical_json(scene.live_content() if item.content is None else item.content).encode()).hexdigest()
            for item in scene.scene_variants.items}


async def only_variant(studio):
    (row,) = (await studio.list_presentations()).presentations
    return row["presentation_id"], row["active_variant_id"]


@pytest.mark.parametrize("after_acks", [3, 9, 17])
async def test_killing_during_a_select_loop_never_tears_the_set_nor_loses_or_swaps_a_content(tmp_path, after_acks):
    truth = None
    for round_number in range(4):  # the same tree survives repeated crashes
        child = launch(tmp_path, "loop")
        lines = []
        try:
            lines = read_until(child, "ack", after_acks)
            time.sleep(random.Random(after_acks * 31 + round_number).random() * 0.02)  # land anywhere in the next commit
        finally:
            lines += kill(child)
        first_map = json.loads(next(line for line in lines if line[0] == "map" and len(line) > 1)[1]) if \
            any(line[0] == "map" for line in lines) else None
        acks = [line for line in lines if line[0] == "ack"]
        intents = [line for line in lines if line[0] == "intent"]
        studio, edit, history = await reopen(tmp_path)
        pid, vid = await only_variant(studio)
        variant = await studio.get_variant(pid, vid)  # parses: never torn
        assert len(variant.scenes) == 12 and variant.scenes[0].scene_variants is not None
        found = contents_map(variant)
        truth = truth or first_map or found
        assert found == truth, "a content was lost, duplicated or swapped between variants"
        assert sorted(found) == IDS
        last_ack = int(acks[-1][1])
        assert variant.revision >= last_ack, ("behind the last acknowledged revision", variant.revision, last_ack)
        if variant.revision > last_ack + 0 and intents:
            assert variant.revision <= int(intents[-1][1]) + 1  # at most the commit in flight
        assert studio.last_recovery.unreadable == () and studio.last_recovery.active_loaded == 1
        undone = await history.undo(pid, vid, {"actor": "user"})
        assert undone.status is HistoryStatus.UNAVAILABLE and undone.reason == "not_recorded_since_start"
    assert not list(tmp_path.rglob("*.tmp"))  # every start swept the leftovers of the kill before it


async def test_a_kill_at_the_worst_instant_of_a_select_keeps_the_last_acknowledged_state_and_every_content(tmp_path):
    child = launch(tmp_path, "pause_select")
    lines = []
    try:
        lines = read_until(child, "paused")
    finally:
        kill(child)
    acked = next(line for line in lines if line[0] == "acked")
    original_map = json.loads(next(line for line in lines if line[0] == "map")[1])
    temporaries = list((tmp_path / "presentations").rglob("*.tmp"))
    assert len(temporaries) == 1, "the complete new text sat in its temporary when the process died"
    pending = json.loads(temporaries[0].read_text(encoding="utf-8"))
    assert pending["revision"] == int(acked[1]) + 1  # complete, but never promoted: the replace did not happen
    assert pending["scenes"][0]["scene_variants"]["current_id"] == IDS[2]
    stored = json.loads(next((tmp_path / "presentations").rglob("psv_*.json")).read_text(encoding="utf-8"))
    assert stored["revision"] == int(acked[1]) and stored["scenes"][0]["scene_variants"]["current_id"] == acked[2] == IDS[1]

    studio, edit, history = await reopen(tmp_path)  # restart: sweep + recovery
    assert studio.last_recovery.swept == 1 and studio.last_recovery.unreadable == ()
    assert not list((tmp_path / "presentations").rglob("*.tmp"))
    pid, vid = await only_variant(studio)
    variant = await studio.get_variant(pid, vid)
    assert (variant.revision, variant.scenes[0].scene_variants.current_id) == (int(acked[1]), IDS[1])
    assert contents_map(variant) == original_map  # nothing lost, nothing swapped
    # and the product keeps working: the select that was in flight now commits on the recovered revision, then undoes
    done = await edit.edit(pid, vid, {"actor": "user", "mode": "commit", "basis": {"variant_revision": variant.revision},
                                      "ops": [{"op": "scene_variant.select", "scene_id": "pss_000000000001", "variant_id": IDS[2]}]})
    assert done.status.value == "applied"
    assert contents_map(await studio.get_variant(pid, vid)) == original_map
    assert (await history.undo(pid, vid, {"actor": "user"})).status is HistoryStatus.APPLIED
    assert (await studio.get_variant(pid, vid)).scenes[0].scene_variants.current_id == IDS[1]
