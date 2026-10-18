"""Outils Dossier du cerveau (`jarvis-workspace`, wheel-dossier-refactor Slice 05) et canal agent -> page.

Vraie chaîne : serveur MCP réel en mémoire -> vrai Control Center -> Core (`tests/fakes/capture_stack.py`),
monde de `test_workspace_inspection_api.build`. Les outils rendent la même sémantique et les mêmes codes que
les routes de l'interface (`test_dossier_service_api.py`), avec `origin: brain`.
"""

from __future__ import annotations

import asyncio

import pytest

from jarvis.domain.scene import SceneObjectKind, ScenePayload
from tests.fakes.capture_stack import CaptureStack
from tests.unit.test_dossier_service_api import RESEARCH, active, memory_file, on_board_a, put
from tests.unit.test_workspace_inspection_api import build, snapshot
from tests.unit.test_workspace_mcp import Brain, _events

NAV = "/api/dossier/navigation/commands"


async def test_dossier_list_is_the_human_view_and_reads_without_side_effect(tmp_path):
    async with CaptureStack(tmp_path) as stack, Brain(stack) as brain:
        w = await build(stack)
        before = await snapshot(stack)
        listed = await brain.call("dossier_list", {"board_id": w.board_a})
        assert listed["writable"] is True and listed["total"] == 5 and listed["truncated"] is False
        assert listed["entries"][0] == {"entry_id": "memory:summary.md", "kind": "memory_summary",
                                        "title": "Résumé du Board", "open": "text",
                                        "modified_at": listed["entries"][0]["modified_at"],
                                        "size": len("# A\nDécisions du projet\n".encode())}
        assert all("advanced" not in entry and "path" not in entry for entry in listed["entries"])
        old = await brain.call("dossier_list", {"board_id": w.board_archived, "limit": 1})
        assert old["writable"] is False and [e["entry_id"] for e in old["entries"]] == ["memory:vieux.md"]
        assert await snapshot(stack) == before


async def test_dossier_ranger_previews_then_stores_as_the_brain(tmp_path):
    async with CaptureStack(tmp_path) as stack, Brain(stack) as brain:
        w = await on_board_a(stack)
        await put(stack, "brain-artifact-m1", payload=RESEARCH)
        await put(stack, "brain-group-m", kind=SceneObjectKind.GROUP, category="groupe",
                  payload=ScenePayload(title="Groupe"))
        ids = ["brain-artifact-m1", "brain-group-m"]
        preview = await brain.call("dossier_ranger", {"board_id": w.board_a, "object_ids": ids, "dry_run": True})
        assert [r["status"] for r in preview["results"]] == ["rangeable", "refused"]
        assert preview["results"][1]["code"] == "dossier_not_eligible" and preview["stored"] == 0
        assert await active(stack, "brain-artifact-m1") is not None, "dry_run writes nothing"

        stored = await brain.call("dossier_ranger", {"board_id": w.board_a, "object_ids": ids})
        first, second = stored["results"]
        assert (first["status"], first["action"], first["archived"]) == ("stored", "materialized", True)
        assert second["status"] == "refused" and "reste sur le Board" in second["message"]
        assert (stored["stored"], stored["refused"]) == (1, 1)
        assert await active(stack, "brain-group-m") is not None
        rows = await _events(stack, w.open_session, "board.memory.written")
        assert rows[-1]["data"]["origin"] == "brain" and rows[-1]["data"]["path"] == first["entry_id"][len("memory:"):]
        assert "origin=brain" in memory_file(stack, w.board_a, rows[-1]["data"]["path"]).read_text(encoding="utf-8")


async def test_dossier_ranger_preview_on_a_board_not_displayed_promises_nothing(tmp_path):
    async with CaptureStack(tmp_path) as stack, Brain(stack) as brain:
        w = await build(stack)  # B actif
        await put(stack, "brain-artifact-m2", payload=RESEARCH)
        preview = await brain.call("dossier_ranger", {"board_id": w.board_a, "object_ids": ["brain-artifact-m2"],
                                                      "dry_run": True})
        only = preview["results"][0]
        assert (only["status"], only["code"]) == ("refused", "dossier_board_not_active") and preview["refused"] == 1
        assert "Board actif" in only["message"]


async def test_dossier_present_and_its_refusals_carry_the_core_codes(tmp_path):
    async with CaptureStack(tmp_path) as stack, Brain(stack) as brain:
        w = await build(stack)  # B active
        refusal = await brain.refused("dossier_present", {"board_id": w.board_a, "entry_id": "memory:summary.md"})
        assert refusal.startswith("Refus dossier_board_not_active : ") and "(Core : " in refusal
        assert "donnez le Board actif" in refusal
        await stack.core.boards.switch(w.board_a)
        shown = await brain.call("dossier_present", {"board_id": w.board_a, "entry_id": "memory:notes/plan.md"})
        assert shown["created"] is True and shown["representation"] == "window"
        again = await brain.call("dossier_present", {"board_id": w.board_a, "entry_id": "memory:notes/plan.md",
                                                    "representation": "capsule"})
        assert again["created"] is False and again["object_id"] == shown["object_id"]
        missing = await brain.refused("dossier_present", {"board_id": w.board_a, "entry_id": "memory:absent.md"})
        assert missing.startswith("Refus dossier_entry_not_found : ")
        malformed = await brain.refused("dossier_present", {"board_id": w.board_a, "entry_id": "fichier.md"})
        assert "rien n'a été envoyé" in malformed


async def _page_answers(stack: CaptureStack, receipt: dict) -> dict:
    """Une page visible : prend la commande au long-poll, puis rend `receipt` avec son jeton."""

    status, polled, _ = await stack.call("GET", NAV, params={"wait_s": "5", "page": "pagetest1"})
    assert status == 200 and polled["command"] is not None, polled
    command = polled["command"]
    token = stack.center.dossier_navigation.broker.page_token
    status, body, _ = await stack.call("POST", f"{NAV}/{command['id']}", json=receipt,
                                       headers={"X-Jarvis-Page-Token": token})
    assert status == 200, body
    return command


async def test_dossier_view_returns_the_receipt_of_the_page(tmp_path):
    async with CaptureStack(tmp_path) as stack, Brain(stack) as brain:
        w = await build(stack)
        page = asyncio.ensure_future(_page_answers(stack, {"state": "opened"}))
        opened = await brain.call("dossier_view", {"board_id": w.board_a, "entry_id": "memory:notes/plan.md"})
        command = await page
        assert command["action"] == "open_entry" and command["board_id"] == w.board_a
        assert command["entry_id"] == "memory:notes/plan.md"
        assert opened == {"board_id": w.board_a, "entry_id": "memory:notes/plan.md", "state": "opened",
                          "explanation": "Le Dossier est ouvert sur cette entrée, à l'écran."}

        page = asyncio.ensure_future(_page_answers(stack, {"state": "refused", "code": "board_not_displayed",
                                                           "reason": "un autre Board est affiché"}))
        refused = await brain.call("dossier_view", {"board_id": w.board_a, "entry_id": "memory:summary.md"})
        await page
        assert (refused["state"], refused["code"]) == ("refused", "board_not_displayed")
        assert "sans prétendre l'inverse" in refused["explanation"]


async def test_dossier_view_sends_the_entry_id_as_stored(tmp_path):
    """QA S05, polish 5 : la page reçoit le nom du fichier sur disque, pas la casse de la demande."""

    import os

    if os.path.normcase("A") != "a":
        pytest.skip("case-insensitive lookup is a Windows behaviour")
    async with CaptureStack(tmp_path) as stack, Brain(stack) as brain:
        w = await build(stack)
        page = asyncio.ensure_future(_page_answers(stack, {"state": "opened"}))
        opened = await brain.call("dossier_view", {"board_id": w.board_a, "entry_id": "memory:NOTES/Plan.md"})
        command = await page
        assert command["entry_id"] == "memory:notes/plan.md" and opened["entry_id"] == "memory:notes/plan.md"


async def test_dossier_view_without_a_visible_page_or_entry_is_an_honest_refusal(tmp_path):
    async with CaptureStack(tmp_path) as stack, Brain(stack) as brain:
        w = await build(stack)
        stack.center.dossier_navigation.broker.deadline_s = 0.3
        missing = await brain.refused("dossier_view", {"board_id": w.board_a, "entry_id": "memory:absent.md"})
        assert missing.startswith("Refus dossier_entry_not_found : ")
        assert not [e for e in stack.trace() if e.get("kind") == "dossier.navigation.requested"], \
            "an entry that is not there never disturbs the screen"
        nobody = await brain.refused("dossier_view", {"board_id": w.board_a, "entry_id": "memory:summary.md"})
        assert nobody.startswith("Refus no_visible_page : ") and "pas ouverte" in nobody
        # QA S05, polish 2 : aucune promesse de rouvrir « dès que l'interface est visible ».
        assert "rien ne l'ouvrira de soi-même" in nobody and "dès que" not in nobody
        kinds = [e.get("kind") for e in stack.trace()]
        assert "dossier.navigation.requested" in kinds and "dossier.navigation.expired" in kinds
