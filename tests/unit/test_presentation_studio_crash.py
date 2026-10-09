"""Arrêt brutal réel du magasin des Presentations (jarvis-interactive-presentation-studio, Slice 02).

Un vrai sous-processus écrit en boucle (gros documents, pour que la fenêtre
d'une écriture non atomique soit large) ; le parent le tue (`Popen.kill()` :
`TerminateProcess` sous Windows, `SIGKILL` ailleurs) à des instants différents,
puis relit : jamais un fichier tronqué ou mélangé, jamais un dossier de
Presentation à moitié créé, et la sauvegarde suivante fonctionne. Contrat :
`docs/presentation-studio.md` › *Storage*, règle R3 du handoff.
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

REPO = Path(__file__).resolve().parents[2]
PID = "pst_" + "a" * 32
VID = "psv_" + "b" * 32
PAD = 250_000

CHILD = r"""
import json, sys
from pathlib import Path
from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore

root, mode, pad, pid, vid = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5]
store = FilePresentationStudioStore(root)

def document(generation):
    return json.dumps({"gen": generation, "pad": "p" * pad}) + "\n"

if mode == "pause":
    # Deterministic worst moment: the new text is complete in its temporary, the replace has not happened yet.
    import time
    from jarvis.adapters import file_presentation_studio_store as module
    store.create(pid, document(0), {vid: document(0)})
    def hang(source, target):
        print("paused", flush=True)
        time.sleep(600)
    module.replace_with_retry = hang
    store.write_variant(pid, vid, document(1))
elif mode == "variant":
    try:
        store.create(pid, document(0), {vid: document(0)})
    except Exception:
        pass  # a previous round already created it
    generation = json.loads(store.read_variant(pid, vid))["gen"] + 1  # continue after the previous round's kill
    while True:
        store.write_variant(pid, vid, document(generation))
        store.write_manifest(pid, document(generation))
        print(generation, flush=True)
        generation += 1
else:
    index = 0
    while True:
        store.create("pst_%032x" % index, document(index), {"psv_%032x" % index: document(index)})
        print(index, flush=True)
        index += 1
"""


def run_until_killed(root: Path, mode: str, after_lines: int) -> int:
    """Lance l'enfant, attend `after_lines` écritures terminées, le tue en pleine boucle. Rend la dernière écriture annoncée."""

    env = {**os.environ, "PYTHONPATH": str(REPO)}
    child = subprocess.Popen([sys.executable, "-c", CHILD, str(root), mode, str(PAD), PID, VID], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(root))
    last = -1
    try:
        for _ in range(after_lines):
            line = child.stdout.readline()
            if not line:
                pytest.fail(f"child ended before the kill: {child.stderr.read()[-800:]}")
            last = int(line)
        time.sleep(random.Random(after_lines * 1009 + last).random() * 0.004)  # land anywhere in the next write
    finally:
        child.kill()  # mid-loop: the child is writing the next generation right now
        child.wait(timeout=30)
        child.stdout.close()
        child.stderr.close()
    assert child.returncode != 0  # killed, not a clean exit
    return last


def check_whole(text: str) -> int:
    assert text.endswith("\n"), "torn file: no trailing newline"
    document = json.loads(text)
    assert set(document) == {"gen", "pad"} and document["pad"] == "p" * PAD, "torn or mixed file"
    return document["gen"]


@pytest.mark.parametrize("after_lines", [2, 7, 19])
def test_killing_a_writer_never_leaves_a_torn_variant_or_manifest(tmp_path, after_lines):
    store = FilePresentationStudioStore(tmp_path)
    announced = 0
    for round_number in range(8):  # the same tree survives repeated crashes
        announced = run_until_killed(tmp_path, "variant", after_lines)
        variant_gen = check_whole(store.read_variant(PID, VID))
        manifest_gen = check_whole(store.read_manifest(PID))
        # The last announced generation was fully written (variant first, manifest last), the next one may be partial
        # or complete: never older than the announcement, never torn.
        assert variant_gen >= announced and manifest_gen >= announced, (round_number, announced, variant_gen)
        assert variant_gen - manifest_gen in (0, 1), "variant is written first, manifest last"
    # leftovers from the kills are only ours, are swept, and never block the next save
    store.sweep()
    assert not list(tmp_path.rglob("*.tmp"))
    store.write_variant(PID, VID, json.dumps({"gen": -1, "pad": "p" * PAD}) + "\n")
    assert check_whole(store.read_variant(PID, VID)) == -1


@pytest.mark.parametrize("after_lines", [3, 9])
def test_killing_a_creator_never_publishes_a_half_created_presentation(tmp_path, after_lines):
    store = FilePresentationStudioStore(tmp_path)
    announced = run_until_killed(tmp_path, "create", after_lines)
    ids = store.scan().presentation_ids
    assert len(ids) >= announced + 1  # every announced creation is durable
    for presentation_id in ids:
        index = int(presentation_id[4:], 16)
        assert check_whole(store.read_manifest(presentation_id)) == index
        assert check_whole(store.read_variant(presentation_id, "psv_%032x" % index)) == index
    leftovers = [p.name for p in (tmp_path / "presentations").iterdir() if p.name.startswith(".")]
    report = store.sweep()
    assert sorted(report.removed) == sorted(leftovers) and not report.failed
    assert [p.name for p in (tmp_path / "presentations").iterdir() if p.name.startswith(".")] == []
    assert store.scan().presentation_ids == ids  # sweeping never removes a published presentation


def test_a_kill_between_the_complete_temporary_and_the_replace_keeps_the_old_document(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    child = subprocess.Popen([sys.executable, "-c", CHILD, str(tmp_path), "pause", str(PAD), PID, VID], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(tmp_path))
    try:
        assert child.stdout.readline().strip() == "paused", child.stderr.read()[-800:]
    finally:
        child.kill()
        child.wait(timeout=30)
        child.stdout.close()
        child.stderr.close()
    store = FilePresentationStudioStore(tmp_path)
    assert check_whole(store.read_variant(PID, VID)) == 0  # the old document, whole
    temporaries = list((tmp_path / "presentations" / PID / "variants").glob("*.tmp"))
    assert len(temporaries) == 1 and check_whole(temporaries[0].read_text(encoding="utf-8")) == 1
    assert store.sweep().removed == (f"{PID}/{temporaries[0].name}",) and not temporaries[0].exists()
    store.write_variant(PID, VID, json.dumps({"gen": 2, "pad": "p" * PAD}) + "\n")
    assert check_whole(store.read_variant(PID, VID)) == 2
