"""Deux fenêtres visibles sur le VRAI Control Center : `/api/status` reste rapide et un ordre `dossier_view`
s'exécute une seule fois (Slice 08 de la refonte roue/Dossier, QA B1).

Chaque page visible tient déjà les long-polls du plein écran et de l'explorateur ; le canal Dossier en ajoutait
un (par page, puis par meneur Web Locks) et, à deux fenêtres, saturait les six connexions par origine de Chrome :
`/api/status` attendait 13 s en médiane. Le Dossier relève désormais la commande au battement de statut
(`dossier_navigation.pending`, GET court) : aucune connexion longue de plus.

Vrai Core + vrai Control Center (`tests/fakes/capture_stack.py`), Chrome sans tête, deux fenêtres
(`Target.createTarget {newWindow:true}`). Se saute si Chrome ou node manque.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from jarvis.runtime.scene_view import CoreSceneTransport, CoreSceneView
from tests.fakes.capture_stack import CaptureStack
from tests.unit.test_boards_card_browser import _chrome
from tests.unit.test_workspace_inspection_api import build

HARNESS = Path(__file__).parent / "_two_windows_browser.mjs"


def _p90(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1))))]


async def test_two_visible_windows_keep_status_fast_and_a_dossier_order_runs_once(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    async with CaptureStack(tmp_path) as stack:
        # Ce que `jarvis/app.py` branche : le relais de scène, dont la page meneuse tient le long-poll
        # `/api/scene/patches` — sans lui, la page tiendrait une connexion longue de moins qu'en vrai.
        port = int(stack.core_url.rsplit(":", 1)[1])
        stack.center.scene_view = CoreSceneView(CoreSceneTransport(host="127.0.0.1", port=port,
                                                                   token_file=stack.tmp_path / "core.token"))
        w = await build(stack)
        await stack.core.boards.switch(w.board_a)
        plan = {"settleMs": 7000, "sampleMs": 10000, "width": 1280, "height": 720,
                "nav": {"board_id": w.board_a, "entry_id": "memory:notes/plan.md"}}
        url = f"http://127.0.0.1:{stack.cc_port}/"
        process = await asyncio.create_subprocess_exec(node, str(HARNESS), url, _chrome(), json.dumps(plan),
                                                       stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(process.communicate(), timeout=120)
        assert process.returncode == 0, err.decode("utf-8", "replace")[-2000:]
        seen = json.loads(out)
    pages, receipt = seen["pages"], seen["receipt"]
    assert [p["visibility"] for p in pages] == ["visible", "visible"], pages
    durations = [ms for page in pages for ms in page["status"]]
    assert len(durations) >= 10, ("the beat keeps beating in both windows", durations)
    assert _p90(durations) < 1000, ("/api/status starved", sorted(durations))
    # Une seule lecture de statut en vol par page (la garde de `refreshStatus`), jamais une pile.
    assert all(p["inflight"].get("/api/status", 0) <= 1 for p in pages), [p["inflight"] for p in pages]
    assert not any("/api/dossier/navigation/commands" in p["inflight"] for p in pages), "no held Dossier poll"
    assert receipt["status"] == 200 and receipt["body"]["state"] == "opened", receipt
    assert receipt["ms"] < 3000, receipt
    opened = [p["stats"]["opened"] for p in pages]
    assert sorted(opened) == [0, 1], ("one window executes the order", opened)
    assert sum(1 for p in pages if p["docs"] == ["memory:notes/plan.md"]) == 1, pages
