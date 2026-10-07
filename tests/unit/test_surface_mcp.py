"""Serveur `jarvis-surface` (Tool Brain S7, lot 07b) contre un **vrai Core** : scène, validation du prefab livré.

Contrat : `docs/tool-brain-contracts.md` §15. Ce qui doit tenir : l'outil crée une vraie fenêtre de scène
`jarvis.browser@1` que Core valide par le manifeste livré ; chaque verbe passe par la commande du cerveau et rend le
`surf_<opaque>` ; une adresse dangereuse n'envoie rien (Core ne voit aucune commande) ; un id deviné est refusé ;
le schéma annoncé est fermé (`additionalProperties: false`) et les sorties le respectent.
"""

from __future__ import annotations

import json

import jsonschema
import pytest

from jarvis.domain.browser_surface import surface_id_of
from jarvis.runtime import surface_mcp
from jarvis.runtime.display_mcp import DisplayToolError
from tests.unit.test_display_mcp import core, scene_object, tools  # noqa: F401 - fixtures


async def test_open_creates_a_real_prefab_window_and_every_verb_changes_it(core, tools):  # noqa: F811
    opened = await tools.surface_open(url="https://example.com/a", label="Exemple", note="Des notes")
    surface_id, object_id = opened["surface_id"], opened["object_id"]
    assert surface_id == surface_id_of(object_id) and object_id.startswith("brain-window-")
    stored = await scene_object(core, object_id)
    assert stored["kind"] == "window" and stored["payload"]["prefab"]["id"] == "jarvis.browser"
    assert stored["payload"]["prefab"]["data"]["history"] == [{"url": "https://example.com/a", "label": "Exemple"}]

    await tools.surface_open(url="https://example.com/b", surface_id=surface_id)
    await tools.surface_scroll(surface_id=surface_id, direction="down")
    await tools.surface_zoom(surface_id=surface_id, action="in")
    data = (await scene_object(core, object_id))["payload"]["prefab"]["data"]
    assert (data["index"], data["scroll"], data["zoom"], len(data["history"])) == (1, 25, 125, 2)

    await tools.surface_history(surface_id=surface_id, direction="back")
    data = (await scene_object(core, object_id))["payload"]["prefab"]["data"]
    assert (data["index"], data["scroll"]) == (0, 0)

    focused = await tools.surface_focus(surface_id=surface_id)
    assert focused["outcome"] in ("applied", "duplicate")
    again = await tools.surface_focus(surface_id=surface_id)
    assert again["outcome"] == "duplicate"


async def test_a_dangerous_address_or_a_guessed_id_is_refused_before_anything_is_sent(core, tools):  # noqa: F811
    for url in ("javascript:alert(1)", "file:///c:/x", "https://user:pw@example.com", "http://127.0.0.1:8080/"):
        with pytest.raises(DisplayToolError) as raised:
            await tools.surface_open(url=url)
        assert raised.value.reason == "unsafe_url" and "Rien n'a été envoyé" in str(raised.value)
    with pytest.raises(DisplayToolError) as raised:
        await tools.surface_zoom(surface_id="surf_000000000000", action="in")
    assert raised.value.reason == "unknown_surface"
    opened = await tools.surface_open(url="https://example.com/a")
    with pytest.raises(DisplayToolError) as raised:
        await tools.surface_history(surface_id=opened["surface_id"], direction="back")
    assert raised.value.reason == "no_history"
    status, body, _ = await core.request("GET", "/v1/scene/snapshot")
    assert [item["object_id"] for item in body["snapshot"]["objects"]] == [opened["object_id"]]


async def test_the_server_schema_is_closed_and_real_outputs_validate_it(core, tools):  # noqa: F811
    from mcp.shared.memory import create_connected_server_and_client_session

    server = surface_mcp.build_server(tools=tools)
    listed = {tool.name: tool for tool in await server.list_tools()}
    assert list(listed) == list(surface_mcp.TOOL_NAMES)
    assert all(tool.inputSchema["additionalProperties"] is False for tool in listed.values())
    async with create_connected_server_and_client_session(server) as session:
        opened = await session.call_tool("surface_open", {"url": "https://example.com/a"})
        assert opened.isError is False
        body = json.loads(opened.content[0].text)
        jsonschema.validate(body, listed["surface_open"].outputSchema)
        zoomed = await session.call_tool("surface_zoom", {"surface_id": body["surface_id"], "action": "out"})
        jsonschema.validate(json.loads(zoomed.content[0].text), listed["surface_zoom"].outputSchema)
        refused = await session.call_tool("surface_open", {"url": "data:text/html,x"})
        assert refused.isError is True and "unsafe_url" in refused.content[0].text
        unknown = await session.call_tool("surface_open", {"url": "https://example.com/", "target": "x"})
        assert unknown.isError is True and "Arguments inconnus refusés" in unknown.content[0].text
        bad_enum = await session.call_tool("surface_zoom", {"surface_id": body["surface_id"], "action": "huge"})
        assert bad_enum.isError is True


async def test_core_validates_the_surface_block_against_the_shipped_manifest(core):  # noqa: F811
    """Seconde garde : même si un appelant contourne les plans du domaine, Core refuse une donnée hors manifeste."""

    from tests.unit.test_display_mcp import user_command

    block = {"id": "jarvis.browser", "version": 1, "props": {},
             "data": {"history": [{"url": "javascript:alert(1)"}], "index": 0, "zoom": 100, "scroll": 0}}
    wire = {"op": "upsert_object", "object_id": "brain-window-bad000000001",
            "fields": {"kind": "window", "category": "browser", "payload": {"title": "x", "prefab": block}}}
    answer = await user_command(core, wire)
    assert (answer["outcome"], answer["reason"]) == ("invalid", "prefab_invalid")
    block["data"] = {"history": [{"url": "https://example.com/"}], "zoom": 9999}
    answer = await user_command(core, wire)
    assert (answer["outcome"], answer["reason"]) == ("invalid", "prefab_invalid")
