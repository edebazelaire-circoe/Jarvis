"""`scene_purge_archived` de jarvis-display, appelé par le protocole MCP contre un vrai Core.

Premier appel : le plan et un jeton, rien d'effacé. Second appel avec le jeton
et `confirmed: true` : la purge ; `scene_inspect` rapporte alors `archived: 0`.
L'outil n'est pas délégué au Tool Brain (pas de `ui_surface`) : son garde-fou
d'outil irréversible (au plus 3 cibles explicites) ne peut pas le rendre
impossible.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from jarvis.runtime.display_mcp import SceneDisplayTools, build_server
from jarvis.runtime.mcp_tool_meta import server_meta
from jarvis.runtime.scene_view import CoreSceneTransport
from tests.integration.test_scene_transport import CoreProcess, artifact

GRACE_S = 0.2


@pytest.fixture
async def core(tmp_path):
    process = CoreProcess(tmp_path, scene_restart_grace_s=GRACE_S)
    await process.start()
    try:
        yield process
    finally:
        await process.stop()


@pytest.fixture
async def tools(core, tmp_path):
    from jarvis.runtime.journal import RuntimeJournal

    display = SceneDisplayTools(CoreSceneTransport(host="127.0.0.1", port=core.port, token_file=core.token_file),
                                journal=RuntimeJournal(tmp_path / "runtime"))
    try:
        yield display
    finally:
        await display.close()


async def archived_scene(core: CoreProcess, count: int, prefix: str = "old") -> None:
    for index in range(count):
        for payload in (artifact(f"{prefix}-{index}"),
                        {"schema_version": 1, "op": "archive", "actor": "user", "object_id": f"{prefix}-{index}"}):
            status, body, _ = await core.request("POST", "/v1/scene/commands", json=payload)
            assert status == 200 and body["outcome"] == "applied", body
    await asyncio.sleep(GRACE_S + 0.1)


async def test_the_brain_plans_then_purges_through_mcp_and_inspect_reads_zero(core, tools):
    from mcp.shared.memory import create_connected_server_and_client_session

    await archived_scene(core, 12)
    server = build_server(tools=tools)
    async with create_connected_server_and_client_session(server) as session:
        inspected = json.loads((await session.call_tool("scene_inspect", {})).content[0].text)
        assert inspected["scene"]["archived"] == 12

        planned = await session.call_tool("scene_purge_archived", {})
        assert planned.isError is False, planned.content
        plan = planned.structuredContent
        assert plan["step"] == "plan" and plan["archived"] == 12 and plan["history_rows"] == 12 and plan["kept"] == 0
        assert plan["confirmation"].startswith("spg_")
        # Le plan n'a rien effacé.
        assert json.loads((await session.call_tool("scene_inspect", {})).content[0].text)["scene"]["archived"] == 12

        # Jeton sans confirmed=true : refusé, rien ne part.
        refused = await session.call_tool("scene_purge_archived", {"confirmation": plan["confirmation"]})
        assert refused.isError is True
        assert json.loads((await session.call_tool("scene_inspect", {})).content[0].text)["scene"]["archived"] == 12

        purged = await session.call_tool("scene_purge_archived",
                                         {"confirmation": plan["confirmation"], "confirmed": True})
        assert purged.isError is False, purged.content
        done = purged.structuredContent
        assert done["step"] == "purged" and done["archived"] == 12 and done["history_rows"] == 12
        assert done["backup_path"].endswith(".bak") and "scene.sqlite3.purge-" in done["backup_path"]

        inspected = json.loads((await session.call_tool("scene_inspect", {})).content[0].text)
        assert inspected["scene"]["archived"] == 0

        # La commande suivante passe.
        created = await session.call_tool("scene_create_object", {"kind": "artifact", "category": "note", "title": "Après la purge"})
        assert created.isError is False, created.content


async def test_a_stale_confirmation_is_refused_and_nothing_is_purged(core, tools):
    from mcp.shared.memory import create_connected_server_and_client_session

    await archived_scene(core, 2)
    server = build_server(tools=tools)
    async with create_connected_server_and_client_session(server) as session:
        plan = (await session.call_tool("scene_purge_archived", {})).structuredContent
        await archived_scene(core, 3, "late")  # l'ensemble a changé depuis le plan
        stale = await session.call_tool("scene_purge_archived", {"confirmation": plan["confirmation"], "confirmed": True})
        assert stale.isError is True
        assert "confirmation_stale" in stale.content[0].text
        assert json.loads((await session.call_tool("scene_inspect", {})).content[0].text)["scene"]["archived"] == 5


def test_the_purge_tool_is_destructive_and_never_delegated_to_the_tool_brain():
    from jarvis.runtime.tool_brain_ownership import jarvis_delegated_tools

    meta = server_meta("jarvis-display").tools["scene_purge_archived"]
    assert meta.side_effect == "destructive" and meta.idempotent is False
    assert meta.ui_surface is None and meta.reversibility is None
    assert ("jarvis-display", "scene_purge_archived") not in jarvis_delegated_tools() \
        and "scene_purge_archived" not in {name for _server, name in jarvis_delegated_tools()}
