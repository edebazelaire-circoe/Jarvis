"""Catalogue canonique des outils MCP (handoff jarvis-mcp-semantic-batch-inspector, Slice 04).

Contrat : `docs/mcp/tool-contract.md` §2–§5. Ce qui doit tenir :

- une seule source : métadonnées partagées (`mcp_tool_meta`) × introspection
  des vrais serveurs, parité dans les deux sens, par serveur et dans l'ordre ;
- les annotations annoncées sont celles dérivées des métadonnées ;
- le catalogue rend exactement ce qu'un client MCP lit dans `tools/list` ;
- chaque descripteur est complet, chaque outil a une catégorie ;
- aucun secret, chemin de jeton ni valeur d'environnement dans un descripteur ;
- aucun méta-outil de catalogue n'est annoncé au modèle, scène ≤ 13 outils ;
- les schémas de sortie documentés valident des sorties réelles ;
- la disponibilité suit la précédence du §4.3.
"""

from __future__ import annotations

import json
import re

import jsonschema
import pytest

from jarvis.runtime import barehands_mcp, claude_local, display_mcp, mcp_catalog, settings_mcp
from jarvis.runtime.mcp_catalog import (
    advertised_from_agent_snapshot,
    availability,
    build_catalog,
    build_introspection_server,
    parameters_of,
)
from jarvis.runtime.mcp_tool_meta import (
    CATEGORY_LABELS,
    MAX_LABEL_CHARS,
    SERVERS,
    annotation_hints,
    tool_names,
)
from tests.unit.test_display_mcp import core, tools, user_command  # noqa: F401 - fixtures
from tests.unit.test_settings_mcp import center  # noqa: F401 - fixture

_FORMATS = {"structured", "json_text", "json_text+image", "text_lines", "untyped"}
_DESCRIPTOR_KEYS = {"name", "server", "qualified_name", "category", "label", "summary", "description", "input_schema",
                    "parameters", "parameter_rules", "output", "side_effect", "idempotent", "atomicity", "annotations",
                    "deprecation", "context_bytes"}


@pytest.fixture(scope="module")
def catalog():
    import asyncio

    return asyncio.run(build_catalog())


# ------------------------------------------------------------------ une seule source

@pytest.mark.parametrize("meta", SERVERS, ids=lambda meta: meta.server)
async def test_metadata_and_the_real_server_list_the_same_tools_in_the_same_order(meta):
    listed = await build_introspection_server(meta.server).list_tools()
    assert tuple(tool.name for tool in listed) == tuple(meta.tools)


def test_the_tool_name_tuples_and_display_tools_derive_from_the_metadata():
    assert display_mcp.TOOL_NAMES == tool_names("jarvis-display")
    assert settings_mcp.TOOL_NAMES == tool_names("jarvis-console")
    assert barehands_mcp.TOOL_NAMES == tool_names("jarvis-barehands")
    assert display_mcp.READ_TOOL_NAMES == ("scene_inspect", "scene_query", "scene_get", "scene_capture")
    assert claude_local.DISPLAY_TOOLS == {f"mcp__jarvis-display__{name}" for name in tool_names("jarvis-display")}


@pytest.mark.parametrize("meta", SERVERS, ids=lambda meta: meta.server)
async def test_advertised_annotations_are_the_ones_derived_from_the_metadata(meta):
    for tool in await build_introspection_server(meta.server).list_tools():
        assert tool.annotations is not None, tool.name
        assert tool.annotations.model_dump(exclude_none=True) == annotation_hints(meta.server, tool.name), tool.name
        side_effect = meta.tools[tool.name].side_effect
        assert tool.annotations.readOnlyHint is (side_effect == "read")
        assert tool.annotations.openWorldHint is (meta.category == "external")


@pytest.mark.parametrize("meta", SERVERS, ids=lambda meta: meta.server)
async def test_the_catalog_is_what_a_client_reads_in_tools_list(meta, catalog):
    from mcp.shared.memory import create_connected_server_and_client_session

    async with create_connected_server_and_client_session(build_introspection_server(meta.server)) as session:
        wire = (await session.list_tools()).tools
    described = [entry for entry in catalog["tools"] if entry["server"] == meta.server]
    assert [entry["name"] for entry in described] == [tool.name for tool in wire]
    for entry, tool in zip(described, wire):
        assert entry["description"] == tool.description
        assert entry["input_schema"] == tool.inputSchema
        assert entry["input_schema"].get("additionalProperties") is False or meta.server == "jarvis-drive"
        assert entry["output"]["advertised_schema"] is (tool.outputSchema is not None)
        if entry["output"]["format"] in ("structured", "untyped"):
            assert entry["output"]["schema"] == tool.outputSchema
        assert entry["annotations"] == tool.annotations.model_dump(exclude_none=True)


# ------------------------------------------------------------------ complétude

def test_every_descriptor_is_complete_and_every_tool_has_one_category(catalog):
    assert catalog["unavailable"] == []
    assert [server["server"] for server in catalog["servers"]] == [
        "jarvis-display", "jarvis-console", "jarvis-barehands", "jarvis-drive"]
    for entry in catalog["tools"]:
        assert set(entry) == _DESCRIPTOR_KEYS, entry["name"]
        assert entry["category"] in CATEGORY_LABELS and entry["category"] != "general"
        assert entry["qualified_name"] == f"mcp__{entry['server']}__{entry['name']}"
        assert 0 < len(entry["label"]) <= MAX_LABEL_CHARS
        assert entry["summary"] and "\n" not in entry["summary"]
        assert entry["side_effect"] in ("read", "write", "destructive")
        assert isinstance(entry["idempotent"], bool)
        assert entry["output"]["format"] in _FORMATS
        assert (entry["atomicity"] == "none") is (entry["side_effect"] == "read"), entry["name"]
        assert entry["context_bytes"] > 0
        if entry["output"]["format"] == "structured":
            schema = entry["output"]["schema"]
            assert schema is not None and schema.get("additionalProperties") is False, entry["name"]
            assert "result" not in schema.get("properties", {}), entry["name"]
        if entry["output"]["format"] in ("json_text", "json_text+image", "text_lines"):
            # Texte compact : jamais de seconde sérialisation sur le fil.
            assert entry["output"]["advertised_schema"] is False, entry["name"]
            assert entry["output"]["schema"], entry["name"]
    names = {(entry["server"], entry["name"]) for entry in catalog["tools"]}
    assert names == {(meta.server, name) for meta in SERVERS for name in meta.tools}


def test_the_read_tools_publish_their_text_schema_only_in_the_catalog(catalog):
    by_name = {entry["name"]: entry for entry in catalog["tools"]}
    for name in ("scene_inspect", "scene_query", "scene_get"):
        assert by_name[name]["output"]["format"] == "json_text"
        assert by_name[name]["output"]["advertised_schema"] is False
    rows = by_name["scene_inspect"]["output"]["schema"]["properties"]["o"]["items"]["prefixItems"]
    assert [column["title"] for column in rows] == [column.name for column in display_mcp.OBJECT_ROW_COLUMNS]


def test_deprecations_and_the_best_effort_transition_are_explicit(catalog):
    by_name = {entry["name"]: entry for entry in catalog["tools"]}
    assert by_name["barehands_tutorial"]["deprecation"]["replacement"] == "barehands_calibrate"
    assert by_name["barehands_tutorial"]["deprecation"]["legacy_doc"] == "docs/legacy/barehands-tutorial-retirement.md"
    assert by_name["scene_set_visibility"]["deprecation"] is not None
    # Contrat §4.2 : `best_effort` ne survit pas à la Slice 05 ; aujourd'hui, ce sont exactement les quatre boucles.
    assert {name for name, entry in by_name.items() if entry["atomicity"] == "best_effort"} == {
        "scene_update_many", "scene_set_visibility", "scene_archive", "scene_pin"}


def test_parameters_say_required_default_and_constraints():
    get = {p["name"]: p for p in parameters_of(_schema("jarvis-display", "scene_get"))}
    assert get["object_ids"]["required"] is True and get["object_ids"]["has_default"] is False
    assert "default" not in get["object_ids"]
    assert get["object_ids"]["constraints"]["minItems"] == 1
    assert get["object_ids"]["constraints"]["maxItems"] == display_mcp.MAX_GET_IDS
    many = {p["name"]: p for p in parameters_of(_schema("jarvis-display", "scene_update_many"))}
    assert many["select"]["required"] is False and many["select"]["has_default"] and many["select"]["default"] is None
    assert many["select"]["type"] == "object | null"
    keys = many["select"]["constraints"]["keys"]
    assert keys["visibility"]["enum"] == ["visible", "hidden"] and keys["visibility"]["required"] is False
    assert many["select"]["constraints"]["closed"] is True
    assert many["annotation"]["constraints"]["maxLength"] > 0
    pin = {p["name"]: p for p in parameters_of(_schema("jarvis-display", "scene_pin"))}
    assert pin["pinned"]["required"] is True and pin["pinned"]["type"] == "boolean"


def _schema(server: str, name: str) -> dict:
    import asyncio

    listed = asyncio.run(build_introspection_server(server).list_tools())
    return next(tool.inputSchema for tool in listed if tool.name == name)


# ------------------------------------------------------------------ contexte du modèle

def test_no_catalog_meta_tool_is_advertised_and_the_scene_stays_within_thirteen(catalog):
    for entry in catalog["tools"]:
        assert not re.search(r"list_tools|get_tool|describe_tool|catalog|mcp_", entry["name"]), entry["name"]
    assert sum(1 for entry in catalog["tools"] if entry["server"] == "jarvis-display") <= 13
    # Le module de catalogue ne construit aucun serveur MCP à lui.
    source = open(mcp_catalog.__file__, encoding="utf-8").read()
    assert "FastMCP(" not in source and ".tool(" not in source


def test_no_secret_path_or_environment_value_leaks_into_a_descriptor(monkeypatch):
    import asyncio

    sentinels = {
        "JARVIS_CORE_TOKEN_FILE": "C:/secret-sentinel/core.token",
        "JARVIS_CORE_HOST": "127.9.9.9",
        "JARVIS_RUNTIME_DIR": "C:/secret-sentinel/runtime",
        "JARVIS_CONTROL_CENTER_PORT": "47111",
        "GOOGLE_DRIVE_TOKEN": "C:/secret-sentinel/drive-token.json",
        "GOOGLE_DRIVE_CLIENT_SECRET": "C:/secret-sentinel/client-secret.json",
        "ANTHROPIC_API_KEY": "sk-ant-sentinel-000000000000",
    }
    for key, value in sentinels.items():
        monkeypatch.setenv(key, value)
    text = json.dumps(asyncio.run(build_catalog()), ensure_ascii=False)
    for value in sentinels.values():
        assert value not in text
    for marker in ("secret-sentinel", "mcpServers", "--mcp-config", "token_file", ".token", "sk-ant"):
        assert marker not in text


def test_introspection_never_invokes_a_tool():
    inert = mcp_catalog._Inert()
    with pytest.raises(RuntimeError, match="never invoke"):
        inert.inspect  # noqa: B018 - l'accès lui-même est la faute


# ------------------------------------------------------------------ sorties réelles × schémas

async def test_scene_outputs_validate_their_documented_schemas(core, tools):  # noqa: F811
    from mcp.shared.memory import create_connected_server_and_client_session

    server = display_mcp.build_server(tools=tools)
    advertised = {tool.name: tool.outputSchema for tool in await server.list_tools()}
    text_schemas = display_mcp.text_output_schemas()

    async def structured(session, name: str, arguments: dict) -> dict:
        result = await session.call_tool(name, arguments)
        assert result.isError is False, (name, result.content[0].text)
        body = json.loads(result.content[0].text)
        # Le CLI rend au modèle le contenu structuré (mesure Slice 04) : mêmes champs, **même ordre**
        # que le dict construit par l'outil, jamais un `null` inventé.
        assert json.dumps(result.structuredContent) == json.dumps(body), name
        jsonschema.validate(body, advertised[name])
        return body

    async def text(session, name: str, arguments: dict) -> dict:
        result = await session.call_tool(name, arguments)
        assert result.isError is False and result.structuredContent is None, name
        assert len(result.content) == 1
        body = json.loads(result.content[0].text)
        jsonschema.validate(body, text_schemas[name])
        return body

    async with create_connected_server_and_client_session(server) as session:
        await text(session, "scene_inspect", {})
        star = await structured(session, "scene_create_object", {
            "kind": "window", "category": "note", "title": "a", "geometry": {"x": 0, "y": 0, "w": 20, "h": 10}})
        other = await structured(session, "scene_create_object", {"kind": "artifact", "category": "note", "title": "b"})
        await structured(session, "scene_create_object", {
            "kind": "window", "category": "note", "title": "c", "geometry": {"x": 25, "y": 0, "w": 20, "h": 10}})
        # La scène bouge sans le cerveau : `scene_changed` passe par le schéma.
        await user_command(core, {"op": "set_visibility", "object_id": other["object_id"], "visibility": "hidden"})
        moved = await structured(session, "scene_update_object", {"object_id": star["object_id"], "layer": 200})
        assert moved["command"] and "scene_changed" in moved
        again = await structured(session, "scene_update_object", {"object_id": star["object_id"], "layer": 200})
        assert again["outcome"] == "duplicate" and "note" in again
        linked = await structured(session, "scene_link", {"from_id": other["object_id"], "to_id": star["object_id"],
                                                          "kind": "explains"})
        kept = await structured(session, "scene_link", {"from_id": other["object_id"], "to_id": star["object_id"],
                                                        "kind": "explains"})
        assert kept["outcome"] == "duplicate" and "layer" in kept
        await structured(session, "scene_unlink", {"relation_id": linked["relation_id"]})
        gone = await structured(session, "scene_unlink", {"relation_id": linked["relation_id"]})
        assert gone["outcome"] == "duplicate"
        created = await structured(session, "scene_add_artifact", {
            "target_id": star["object_id"], "category": "research", "title": "r",
            "items": [{"label": "doc", "url": "https://example.org/a"}]})
        assert created["action"] == "created"
        updated = await structured(session, "scene_add_artifact", {
            "target_id": star["object_id"], "category": "research", "title": "r2", "representation": "capsule"})
        assert updated["action"] == "updated" and updated["ignored"] == ["representation"]
        await text(session, "scene_inspect", {"kind": "window"})
        near = await text(session, "scene_query", {"near": {"object_id": star["object_id"], "radius": 50}})
        assert near["o"] and len(near["o"][0]) == len(display_mcp.OBJECT_ROW_COLUMNS) + 2
        listed = await text(session, "scene_query", {"kind": "window"})
        assert len(listed["o"][0]) == len(display_mcp.OBJECT_ROW_COLUMNS)
        detail = await text(session, "scene_get", {"object_ids": [star["object_id"], created["object_id"], "nope"]})
        assert detail["not_found"] and detail["objects"]


def test_the_object_row_legend_is_byte_identical_and_derived_from_the_columns():
    assert display_mcp.OBJECT_ROW_LEGEND == (
        "[id, kind, category, origin, exec_state, representation, [x,y,w,h]|null, layer, order, "
        "visibility (visible|hidden), pinned_by_user, placed_by, live_signal, title]")
    assert display_mcp.RELATION_ROW_LEGEND == "[relation_id, kind, from_id, to_id, layer]"
    assert display_mcp.NEAR_ROW_LEGEND == display_mcp.OBJECT_ROW_LEGEND[:-1] + ", distance, overlap]"


async def test_settings_outputs_validate_their_documented_schemas(center):  # noqa: F811
    from mcp.shared.memory import create_connected_server_and_client_session

    _, port = center
    console = settings_mcp.ConsoleSettingsTools(settings_mcp.ConsoleMcpTarget("127.0.0.1", port))
    try:
        server = settings_mcp.build_server(tools=console)
        advertised = {tool.name: tool.outputSchema for tool in await server.list_tools()}
        assert advertised["settings_describe"] is None
        async with create_connected_server_and_client_session(server) as session:
            got = await session.call_tool("settings_get", {"option_ids": ["barehands.enabled", "scene.enabled"]})
            assert got.isError is False, got.content[0].text
            assert json.dumps(got.structuredContent) == json.dumps(json.loads(got.content[0].text))
            jsonschema.validate(got.structuredContent, advertised["settings_get"])
            written = await session.call_tool("settings_set", {"option_id": "barehands.enabled", "value": True})
            assert written.isError is False, written.content[0].text
            assert json.dumps(written.structuredContent) == json.dumps(json.loads(written.content[0].text))
            jsonschema.validate(written.structuredContent, advertised["settings_set"])
            described = await session.call_tool("settings_describe", {"search": "barehands"})
            assert described.isError is False and described.structuredContent is None
            lines = described.content[0].text.split("\n")
            assert re.fullmatch(r"\d+ réglage\(s\) :", lines[0])
            assert all(line.startswith("- ") and " · " in line and " = " in line for line in lines[1:])
    finally:
        await console.close()


async def test_barehands_output_model_matches_the_result_the_tools_build():
    from mcp.shared.memory import create_connected_server_and_client_session

    class Page:
        """Rend ce que `BarehandsCommandTools.send` construit pour un reçu `applied` (forme recopiée du code)."""

        async def send(self, tool: str, command: str) -> dict:
            return {"command": command, "outcome": "applied", "lifecycle": None, "note": "Fait."}

    server = barehands_mcp.build_server(tools=Page())  # type: ignore[arg-type]
    advertised = {tool.name: tool.outputSchema for tool in await server.list_tools()}
    async with create_connected_server_and_client_session(server) as session:
        for name in barehands_mcp.TOOL_NAMES:
            result = await session.call_tool(name, {})
            assert result.isError is False, result.content[0].text
            assert json.dumps(result.structuredContent) == json.dumps(json.loads(result.content[0].text))
            jsonschema.validate(result.structuredContent, advertised[name])


# ------------------------------------------------------------------ disponibilité (§4.3)

@pytest.mark.parametrize(
    ("server", "condition_value", "target_present", "advertised", "state", "next_launch", "pending"),
    [
        ("jarvis-display", True, True, True, "advertised", "configured", False),
        ("jarvis-display", True, True, False, "configured", "configured", True),   # vient d'être allumé
        ("jarvis-display", False, True, True, "advertised", "disabled", True),     # vient d'être éteint
        ("jarvis-display", False, True, False, "disabled", "disabled", False),
        ("jarvis-display", True, False, None, "disabled", "disabled", False),      # cible absente
        ("jarvis-display", None, True, None, "known", None, False),                # réglage inconnu : rien deviné
        ("jarvis-display", None, False, None, "disabled", "disabled", False),     # sans cible : éteint, même réglage inconnu
        ("jarvis-display", True, None, True, "advertised", None, False),          # lancement inconnu : aucun redémarrage prouvé
        ("jarvis-console", None, True, None, "configured", "configured", False),   # jamais conditionné
        ("jarvis-barehands", True, True, None, "configured", "configured", False),
        ("jarvis-drive", True, True, True, "known", None, False),                  # déclaré par l'opérateur
    ],
)
def test_availability_follows_the_contract_precedence(server, condition_value, target_present, advertised, state,
                                                       next_launch, pending):
    result = availability(server, condition_value=condition_value, target_present=target_present, advertised=advertised)
    assert result["state"] == state and result["next_launch"] == next_launch and result["pending_restart"] is pending
    assert set(result) == {"state", "condition", "next_launch", "advertised", "pending_restart"}
    if server == "jarvis-drive":
        assert result["advertised"] is None and result["condition"] is None


def test_advertised_is_read_from_the_agent_snapshot_and_never_guessed():
    running = {"state": "running", "display_tools": True}
    assert advertised_from_agent_snapshot("jarvis-display", running) is True
    assert advertised_from_agent_snapshot("jarvis-display", {"state": "stopped", "display_tools": False}) is False
    # Slice 06 ajoute ces drapeaux : sans eux, inconnu, sauf cerveau arrêté.
    assert advertised_from_agent_snapshot("jarvis-barehands", running) is None
    assert advertised_from_agent_snapshot("jarvis-console", {"state": "stopped"}) is False
    assert advertised_from_agent_snapshot("jarvis-drive", running) is None
    assert advertised_from_agent_snapshot("jarvis-display", None) is None


async def test_a_result_outside_its_schema_is_an_error_that_never_claims_nothing_was_sent():
    """La validation du résultat vient **après** l'action : le cerveau ne lit jamais « rien n'a été envoyé »."""

    from mcp.shared.memory import create_connected_server_and_client_session

    class Page:
        async def send(self, tool: str, command: str) -> dict:
            return {"command": command, "outcome": "applied", "lifecycle": "active", "note": "Fait.", "extra": 1}

    async with create_connected_server_and_client_session(barehands_mcp.build_server(tools=Page())) as session:  # type: ignore[arg-type]
        result = await session.call_tool("barehands_activate", {})
    assert result.isError is True
    text = result.content[0].text
    assert "a pu être appliquée" in text and "extra" in text
    assert "rien n'a été envoyé" not in text and "Traceback" not in text


async def test_truncated_listings_and_an_oversized_object_still_validate_their_text_schemas(core, tools, monkeypatch):  # noqa: F811
    """Les branches bornées (`truncated`, `_fit_detail`) produisent des champs que le schéma doit déclarer."""

    schemas = display_mcp.text_output_schemas()
    star = await tools.create_object(kind="window", category="note", title="a", geometry={"x": 0, "y": 0, "w": 20, "h": 10})
    await tools.create_object(kind="window", category="note", title="b", geometry={"x": 25, "y": 0, "w": 20, "h": 10})
    big = await tools.create_object(kind="artifact", category="note", title="gros", summary="s" * 1900,
                                    items=[{"label": f"entrée {index}", "url": f"https://example.org/{index}"}
                                           for index in range(30)])
    await tools.link(from_id=big["object_id"], to_id=star["object_id"], kind="explains")
    monkeypatch.setattr(display_mcp, "MAX_INSPECT_BYTES", 1500)
    listing = json.loads(await tools.inspect())
    assert listing["truncated"]["objects_omitted"] > 0
    jsonschema.validate(listing, schemas["scene_inspect"])
    near = json.loads(await tools.query(near={"object_id": star["object_id"], "radius": 50}))
    assert "truncated" in near
    jsonschema.validate(near, schemas["scene_query"])
    monkeypatch.setattr(display_mcp, "MAX_GET_BYTES", 2500)
    detail = json.loads(await tools.get(object_ids=[big["object_id"], star["object_id"]]))
    assert detail["objects"], detail
    first = detail["objects"][0]
    assert first["items_omitted"] > 0 and first["summary_truncated"] is True
    assert detail["truncated"]["ids_omitted"] == [star["object_id"]]
    jsonschema.validate(detail, schemas["scene_get"])


def test_query_rows_are_exactly_fourteen_or_sixteen_columns():
    schema = display_mcp.text_output_schemas()["scene_query"]
    width = len(display_mcp.OBJECT_ROW_COLUMNS)
    row = ["id", "window", "note", "brain", "unknown", "window", None, 1, 0, "visible", False, "brain", False, "t"]
    base = {"scene": {"scene_id": "s", "revision": 1, "objects": 1, "matched": 1, "filter": {}, "legend": {}}, "r": []}
    jsonschema.validate({**base, "o": [row]}, schema)
    jsonschema.validate({**base, "o": [row + [1.5, False]]}, schema)
    for bad in (row[:width - 1], row + [1.5]):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({**base, "o": [bad]}, schema)


async def test_a_server_that_cannot_import_is_listed_unavailable_never_guessed(monkeypatch):
    real = mcp_catalog.build_introspection_server

    def without_google(server: str):
        if server == "jarvis-drive":
            raise ModuleNotFoundError("No module named 'googleapiclient'")
        return real(server)

    monkeypatch.setattr(mcp_catalog, "build_introspection_server", without_google)
    built = await build_catalog()
    assert built["unavailable"] == [{"server": "jarvis-drive", "category": "external", "error": "ModuleNotFoundError"}]
    assert not any(entry["server"] == "jarvis-drive" for entry in built["tools"])
    assert "jarvis-drive" not in {server["server"] for server in built["servers"]}
    assert "googleapiclient" not in json.dumps(built)
