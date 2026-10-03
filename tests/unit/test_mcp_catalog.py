"""Catalogue canonique des outils MCP (handoff jarvis-mcp-semantic-batch-inspector, Slice 04).

Contrat : `docs/mcp/tool-contract.md` §2–§5. Ce qui doit tenir :

- une seule source : métadonnées partagées (`mcp_tool_meta`) × introspection
  des vrais serveurs, parité dans les deux sens, par serveur et dans l'ordre ;
- les annotations annoncées sont celles dérivées des métadonnées ;
- le catalogue rend exactement ce qu'un client MCP lit dans `tools/list` ;
- chaque descripteur est complet, chaque outil a une catégorie ;
- aucun secret, chemin de jeton ni valeur d'environnement dans un descripteur ;
- aucun méta-outil de catalogue n'est annoncé au modèle, scène ≤ 19 outils (13 de scène + 6 prefab_*) ;
- les schémas de sortie documentés valident des sorties réelles ;
- la disponibilité suit la précédence du §4.3.
"""

from __future__ import annotations

import json
import re
import typing

import jsonschema
import pytest

from jarvis.domain.scene_selection import MAX_SELECTION_IDS
from jarvis.runtime import barehands_mcp, claude_local, display_mcp, mcp_catalog, mcp_tool_meta, settings_mcp
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
    assert display_mcp.READ_TOOL_NAMES == ("scene_inspect", "scene_query", "scene_get", "scene_capture", "prefab_search", "prefab_get",
        "prefab_validate", "prefab_events")
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
        "jarvis-tools", "jarvis-display", "jarvis-console", "jarvis-workspace", "jarvis-capture", "jarvis-barehands",
        "jarvis-drive"]
    for entry in catalog["tools"]:
        assert set(entry) == _DESCRIPTOR_KEYS, entry["name"]
        # `general` : la passerelle de découverte seule (plugins MCP, Slice 04 ; tool-contract §3).
        assert entry["category"] in CATEGORY_LABELS
        assert (entry["category"] == "general") is (entry["server"] == "jarvis-tools"), entry["name"]
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


def test_deprecations_are_explicit_and_no_tool_is_best_effort(catalog):
    by_name = {entry["name"]: entry for entry in catalog["tools"]}
    assert by_name["barehands_tutorial"]["deprecation"]["replacement"] == "barehands_calibrate"
    assert by_name["barehands_tutorial"]["deprecation"]["legacy_doc"] == "docs/legacy/barehands-tutorial-retirement.md"
    # Slice 05 : `scene_set_visibility` est retiré sans alias ; `best_effort` n'est plus une valeur (contrat §4.2).
    assert "scene_set_visibility" not in by_name
    assert not any(entry["atomicity"] == "best_effort" for entry in by_name.values())
    assert "best_effort" not in typing.get_args(mcp_tool_meta.Atomicity)
    batch = ("scene_update_many", "scene_move", "scene_archive", "scene_pin")
    assert all(by_name[name]["atomicity"] == "atomic_batch" for name in batch)
    assert all(by_name[name]["output"]["format"] == "structured" for name in batch)
    # Contrat §6 : idempotents sauf la translation (relative) ; archiver est destructif.
    assert [by_name[name]["idempotent"] for name in batch] == [True, False, True, True]
    assert by_name["scene_archive"]["side_effect"] == "destructive" and by_name["scene_move"]["side_effect"] == "write"


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
    assert set(keys) == set(display_mcp.SELECT_FILTER_KEYS) and "connected" not in keys
    assert keys["constellation"]["required"] is False
    assert many["object_ids"]["constraints"]["maxItems"] == MAX_SELECTION_IDS
    pin = {p["name"]: p for p in parameters_of(_schema("jarvis-display", "scene_pin"))}
    assert pin["pinned"]["required"] is True and pin["pinned"]["type"] == "boolean"
    move = {p["name"]: p for p in parameters_of(_schema("jarvis-display", "scene_move"))}
    assert [name for name, entry in move.items() if entry["required"]] == ["dx", "dy"]
    assert move["dx"]["type"] == "number" and move["pin"]["required"] is False
    assert set(move) == {"dx", "dy", "select", "object_ids", "pin"}


def _schema(server: str, name: str) -> dict:
    import asyncio

    listed = asyncio.run(build_introspection_server(server).list_tools())
    return next(tool.inputSchema for tool in listed if tool.name == name)


# ------------------------------------------------------------------ contexte du modèle

def test_no_catalog_meta_tool_is_advertised_and_the_scene_stays_within_nineteen(catalog):
    # Amendement plugins MCP (Slice 04, tool-contract §5.3, ARCH C5) : `jarvis-tools` est le **seul**
    # serveur de découverte, avec exactement `list_tools` et `call_tool` ; tout le reste est inchangé.
    gateway = [entry["name"] for entry in catalog["tools"] if entry["server"] == "jarvis-tools"]
    assert gateway == ["list_tools", "call_tool"]
    for entry in catalog["tools"]:
        if entry["server"] == "jarvis-tools":
            continue
        assert not re.search(r"list_tools|get_tool|describe_tool|catalog|mcp_", entry["name"]), entry["name"]
    # Prefab-foundation Slice 07 (contrat §10.13) : 13 outils de scène + 6 outils prefab_* (un par intention de
    # R6 : chercher, lire, valider, enregistrer, éditer une base, lire les événements). Pas d'outil d'instanciation :
    # l'argument `prefab` de scene_create_object / scene_update_object.
    assert sum(1 for entry in catalog["tools"] if entry["server"] == "jarvis-display") <= 19
    assert [entry["name"] for entry in catalog["tools"] if entry["server"] == "jarvis-display"] == list(display_mcp.TOOL_NAMES)
    # Le module de catalogue ne construit aucun serveur MCP à lui.
    source = open(mcp_catalog.__file__, encoding="utf-8").read()
    assert "FastMCP(" not in source and ".tool(" not in source


#: `jarvis-console` après la Slice 06 de board-memory-workspace-inspector : les trois réglages seuls, 2 973 o
#: mesurés (2 918 o à la Slice 04 ; 9 616 o avec les neuf outils Board/Session, partis vers `jarvis-workspace`).
CONSOLE_CONTEXT_BUDGET_BYTES = 3_300
#: Consigne du serveur (`_SERVER_INSTRUCTIONS`), aussi vue par le modèle : 831 o mesurés (1 326 o avec les Boards).
CONSOLE_INSTRUCTIONS_BUDGET_BYTES = 900

#: `jarvis-workspace` (board-memory-workspace-inspector, Slice 06, contrat §10.12) : vingt outils, 13 883 o
#: mesurés — les neuf outils Board/Session déplacés (≈ 6 640 o, `board_kind` en plus) et onze outils typés
#: d'historique, de mémoire et de liens. Pièces de schéma partagées (identifiant, chemin, curseur) et
#: descriptions d'une ligne. Plafond : un outil de plus ou une description qui enfle se voit ici.
WORKSPACE_CONTEXT_BUDGET_BYTES = 14_500
#: Consigne du serveur `jarvis-workspace` : 874 o mesurés (la console en a perdu 495).
WORKSPACE_INSTRUCTIONS_BUDGET_BYTES = 950
#: Tous les serveurs natifs que Jarvis déclare au cerveau Claude (display, console, workspace, capture,
#: Bare Hands, passerelle), outils seulement : 68 583 o avant la Slice 06, 75 823 o après (+7 240 o).
#: Prefab-foundation Slice 07 : 82 410 o mesurés (+5 853 o, tous sur `jarvis-display`, voir plus bas).
DECLARED_CONTEXT_BUDGET_BYTES = 83_000


def test_the_console_server_instructions_stay_within_their_budget():
    from jarvis.runtime.settings_mcp import _SERVER_INSTRUCTIONS

    assert len(_SERVER_INSTRUCTIONS.encode("utf-8")) <= CONSOLE_INSTRUCTIONS_BUDGET_BYTES


async def test_the_console_lists_only_its_settings_tools_and_the_catalog_follows(catalog):
    """Slice 06 board-memory : `jarvis-console` = réglages seuls ; aucun outil Board/Session n'y reste."""

    from mcp.shared.memory import create_connected_server_and_client_session

    async with create_connected_server_and_client_session(build_introspection_server("jarvis-console")) as session:
        wire = [tool.name for tool in (await session.list_tools()).tools]
    described = [entry for entry in catalog["tools"] if entry["server"] == "jarvis-console"]
    assert wire == [entry["name"] for entry in described] == list(tool_names("jarvis-console")) == [
        "settings_describe", "settings_get", "settings_set"]
    assert all(entry["category"] == "settings" for entry in described)
    assert sum(entry["context_bytes"] for entry in described) <= CONSOLE_CONTEXT_BUDGET_BYTES


async def test_the_workspace_server_lists_its_tools_in_order_within_its_budget(catalog):
    """Slice 06 board-memory : vrai `tools/list` de `jarvis-workspace` = catalogue partagé, même ordre ; classes ;
    aucun nom d'outil annoncé par deux serveurs natifs ; budget."""

    from mcp.shared.memory import create_connected_server_and_client_session

    from jarvis.runtime import workspace_mcp

    async with create_connected_server_and_client_session(build_introspection_server("jarvis-workspace")) as session:
        wire = [tool.name for tool in (await session.list_tools()).tools]
    described = [entry for entry in catalog["tools"] if entry["server"] == "jarvis-workspace"]
    assert wire == [entry["name"] for entry in described] == list(tool_names("jarvis-workspace")) == list(
        workspace_mcp.TOOL_NAMES) == [
        "board_list", "board_get", "board_get_active", "board_create", "board_update", "board_archive",
        "board_switch", "session_current", "session_new", "session_list", "session_get", "board_inspect",
        "board_memory_tree", "board_memory_read", "board_memory_search", "board_memory_write", "board_memory_move",
        "board_memory_delete", "board_artifacts", "board_artifact_link"]
    effects = {entry["name"]: (entry["side_effect"], entry["idempotent"]) for entry in described}
    assert {name for name, (effect, _) in effects.items() if effect == "read"} == {
        "board_list", "board_get", "board_get_active", "session_current", "session_list", "session_get",
        "board_inspect", "board_memory_tree", "board_memory_read", "board_memory_search", "board_artifacts"}
    assert {name for name, (effect, _) in effects.items() if effect == "destructive"} == {
        "board_archive", "board_memory_write", "board_memory_delete"}  # write : mode=replace écrase
    assert effects["board_create"] == ("write", False) and effects["session_new"] == ("write", False)
    assert effects["board_switch"] == ("write", True) and effects["board_artifact_link"] == ("write", True)
    assert effects["board_memory_write"] == ("destructive", False) and effects["board_memory_move"] == ("write", False)
    assert all(entry["category"] == "workspace" and entry["output"]["format"] == "structured" for entry in described)
    # Pas d'échappatoire générique : un outil typé par intention.
    assert not any("execute" in name or "command" in name for name in wire)
    # Pas de doublon : ni avec la console (déplacés sans alias), ni avec `jarvis-capture` (artifact_get, artifact_search).
    natives = [entry["name"] for entry in catalog["tools"] if entry["server"] != "jarvis-drive"]
    assert len(natives) == len(set(natives))
    assert sum(entry["context_bytes"] for entry in described) <= WORKSPACE_CONTEXT_BUDGET_BYTES
    assert len(workspace_mcp._SERVER_INSTRUCTIONS.encode("utf-8")) <= WORKSPACE_INSTRUCTIONS_BUDGET_BYTES


def test_the_whole_native_surface_declared_to_the_brain_stays_within_its_budget(catalog):
    """Gate de contexte de la Slice 06 : tout ce que les serveurs natifs de Jarvis montrent au modèle."""

    declared = [entry for entry in catalog["tools"] if entry["server"] != "jarvis-drive"]
    assert sum(entry["context_bytes"] for entry in declared) <= DECLARED_CONTEXT_BUDGET_BYTES


#: `jarvis-capture` (session-context-recording, Slice 09, contrat §10.11) : neuf outils, 5 044 o mesurés
#: (rework QA S9, 2026-10-01 ; 4 885 o à la création). Plafond posé à la création du serveur ; un outil
#: de plus ou une description qui enfle se voit ici. Loin sous la console (10 000 o) : D-MCP voulait un domaine à part, pas une seconde console.
CAPTURE_CONTEXT_BUDGET_BYTES = 5_500
#: Consigne du serveur `jarvis-capture` : 610 o mesurés (528 o à la création).
CAPTURE_INSTRUCTIONS_BUDGET_BYTES = 700


async def test_the_capture_server_lists_its_tools_in_order_within_its_budget(catalog):
    """Slice 09 : vrai `tools/list` de `jarvis-capture` = catalogue partagé, même ordre ; classes ; budget."""

    from mcp.shared.memory import create_connected_server_and_client_session

    from jarvis.runtime import capture_mcp

    async with create_connected_server_and_client_session(build_introspection_server("jarvis-capture")) as session:
        wire = [tool.name for tool in (await session.list_tools()).tools]
    described = [entry for entry in catalog["tools"] if entry["server"] == "jarvis-capture"]
    assert wire == [entry["name"] for entry in described] == list(tool_names("jarvis-capture")) == list(
        capture_mcp.TOOL_NAMES)
    effects = {entry["name"]: (entry["side_effect"], entry["idempotent"]) for entry in described}
    assert {name for name, (effect, _) in effects.items() if effect == "read"} == {
        "context_status", "capture_status", "artifact_search", "artifact_get", "transcript_read"}
    assert effects["capture_stop"] == ("write", True) and effects["capture_start"] == ("write", False)
    assert not any(effect == "destructive" for effect, _ in effects.values())  # suppression : geste de l'interface
    assert all(entry["category"] == "capture" and entry["output"]["format"] == "structured" for entry in described)
    assert sum(entry["context_bytes"] for entry in described) <= CAPTURE_CONTEXT_BUDGET_BYTES
    assert len(capture_mcp._SERVER_INSTRUCTIONS.encode("utf-8")) <= CAPTURE_INSTRUCTIONS_BUDGET_BYTES


#: Coût mesuré par la Slice 04 (contrat §10.3) : plafond de `jarvis-display` (contrat §5.3), 33 090 o.
#: Relevé par prefab-foundation Slice 07 (contrat §10.13, raison écrite) : 32 598 o avant, 38 451 o après
#: (+5 853 o) — six outils prefab_* 4 759 o (search 820, get 657, validate 642, save 1 011, edit_base 1 086,
#: events 543) et l'argument `prefab` de scene_create_object / scene_update_object (547 o chacun). Plafond 39 000 o.
DISPLAY_CONTEXT_BASELINE_BYTES = 39_000


def test_the_display_context_cost_stays_within_the_slice_04_baseline(catalog):
    cost = sum(entry["context_bytes"] for entry in catalog["tools"] if entry["server"] == "jarvis-display")
    assert cost <= DISPLAY_CONTEXT_BASELINE_BYTES, cost
    # Aucun titre pydantic dérivé des noms (« Object Id ») dans les schémas d'entrée : le modèle lit le nom.
    def keywords(schema):  # noqa: ANN001, ANN202 - chaque sous-schéma, jamais les noms de propriétés
        if isinstance(schema, list):
            for entry in schema:
                yield from keywords(entry)
        elif isinstance(schema, dict):
            yield schema
            for key, value in schema.items():
                if key in ("properties", "$defs"):
                    for sub in value.values():
                        yield from keywords(sub)
                elif isinstance(value, (dict, list)):
                    yield from keywords(value)

    for name in display_mcp.TOOL_NAMES:
        assert not any("title" in sub for sub in keywords(_schema("jarvis-display", name))), name
    # La vraie propriété `title` de scene_create_object reste, avec son type.
    assert _schema("jarvis-display", "scene_create_object")["properties"]["title"]["anyOf"]


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
        # Slice 05 : les quatre lots rendent un `SceneBatchResult` (appliqué, duplicate), jamais un refus en succès.
        await text(session, "scene_inspect", {})
        hidden = await structured(session, "scene_update_many", {"select": {"constellation": {"object_id": star["object_id"]}},
                                                                 "visibility": "hidden", "confirm": True})
        assert hidden["outcome"] == "applied" and hidden["hidden_count"] == 0
        shown = await structured(session, "scene_update_many", {"select": {"visibility": "hidden"}, "visibility": "visible"})
        assert shown["outcome"] == "applied" and shown["unchanged_count"] == 0 and shown["hidden_count"] == 3
        still = await structured(session, "scene_update_many", {"select": {"visibility": "hidden"}, "visibility": "visible"})
        assert still["outcome"] == "duplicate" and still["matched_count"] == 0 and "note" in still
        moved_set = await structured(session, "scene_move", {"object_ids": [star["object_id"], star["object_id"]],
                                                             "dx": -3, "dy": 2, "pin": True})
        assert moved_set["delta"]["effective"] == {"dx": -3.0, "dy": 2.0} and moved_set["matched_count"] == 1
        blocked = await structured(session, "scene_move", {"object_ids": [star["object_id"]], "dx": -100_000, "dy": 0})
        assert blocked["delta"]["clamped"] is True
        pinned = await structured(session, "scene_pin", {"pinned": False, "select": {"kind": "window"}})
        assert pinned["pinned"] is False
        archived = await structured(session, "scene_archive", {"object_ids": [created["object_id"]]})
        assert archived["outcome"] == "applied" and archived["cascade_ids"] == []
        again_archived = await structured(session, "scene_archive", {"object_ids": [created["object_id"]]})
        assert again_archived["outcome"] == "duplicate" and again_archived["unchanged_ids"] == [created["object_id"]]
        refused = await session.call_tool("scene_archive", {"object_ids": ["nope"]})
        assert refused.isError is True and refused.structuredContent is None
        assert "unknown_object" in refused.content[0].text and "Rien n'a été appliqué" in refused.content[0].text


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
        # Les cinq outils de cycle de vie ; les outils de calibration ont leur
        # propre test de sortie (`test_barehands_calibration_agent.py`).
        for name in barehands_mcp.TOOL_COMMANDS:
            result = await session.call_tool(name, {})
            assert result.isError is False, result.content[0].text
            assert json.dumps(result.structuredContent) == json.dumps(json.loads(result.content[0].text))
            jsonschema.validate(result.structuredContent, advertised[name])


# ------------------------------------------------------------------ disponibilité (§4.3)

@pytest.mark.parametrize(
    ("server", "condition_value", "declared", "advertised", "live", "state", "next_launch", "pending"),
    [
        ("jarvis-display", True, True, True, True, "advertised", "configured", False),
        ("jarvis-display", True, True, False, True, "configured", "configured", True),    # vient d'être allumé
        ("jarvis-display", False, False, True, True, "advertised", "disabled", True),     # vient d'être éteint
        ("jarvis-display", False, False, False, True, "disabled", "disabled", False),
        ("jarvis-display", True, True, False, False, "configured", "configured", False),  # cerveau arrêté : rien en attente
        ("jarvis-display", True, False, None, None, "disabled", "disabled", False),       # réglage vrai, cible absente
        ("jarvis-display", None, None, None, None, "known", None, False),                 # lancement inconnu : rien deviné
        ("jarvis-display", True, None, True, True, "advertised", None, False),            # aucun redémarrage prouvé
        ("jarvis-display", True, True, None, True, "configured", "configured", False),    # advertised inconnu
        ("jarvis-console", None, True, None, None, "configured", "configured", False),    # jamais conditionné
        ("jarvis-workspace", None, True, None, None, "configured", "configured", False),  # jamais conditionné
        ("jarvis-barehands", True, True, None, None, "configured", "configured", False),
        ("jarvis-drive", True, True, True, True, "known", None, False),                   # déclaré par l'opérateur
    ],
)
def test_availability_follows_the_contract_precedence(server, condition_value, declared, advertised, live, state,
                                                       next_launch, pending):
    result = availability(server, condition_value=condition_value, declared=declared, advertised=advertised, live=live)
    assert result["state"] == state and result["next_launch"] == next_launch and result["pending_restart"] is pending
    assert set(result) == {"state", "condition", "condition_value", "next_launch", "advertised", "pending_restart"}
    if server in ("jarvis-drive", "jarvis-console", "jarvis-workspace"):
        assert result["condition"] is None and result["condition_value"] is None
    if server == "jarvis-drive":
        assert result["advertised"] is None
    if server == "jarvis-display":
        assert result["condition_value"] is condition_value


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


async def test_a_server_whose_introspection_fails_otherwise_is_unavailable_and_the_others_stay(monkeypatch):
    """Slice 06 F3 : une panne qui n'est pas un import (ici un `RuntimeError`) n'emporte que son serveur."""

    real = mcp_catalog.build_introspection_server

    def broken_drive(server: str):
        if server == "jarvis-drive":
            raise RuntimeError("C:/secret-sentinel/drive-token.json unreadable")
        return real(server)

    monkeypatch.setattr(mcp_catalog, "build_introspection_server", broken_drive)
    built = await build_catalog()
    assert built["unavailable"] == [{"server": "jarvis-drive", "category": "external", "error": "RuntimeError"}]
    assert [entry["server"] for entry in built["servers"]] == ["jarvis-tools", "jarvis-display", "jarvis-console",
                                                               "jarvis-workspace", "jarvis-capture",
                                                               "jarvis-barehands"]
    assert "secret-sentinel" not in json.dumps(built)


# ------------------------------------------------------------------ plugins MCP gérés (generic-mcp-plugin-runtime, Slice 04)

EXTERNAL = {
    "catalog_revision": 12, "unchanged": False,
    "plugins": [
        {"plugin_id": "circuit", "display_name": "Circuit", "enabled": True, "connection_status": "connected",
         "auth_status": "authorized", "tool_count": 1},
        {"plugin_id": "offline", "display_name": "Offline", "enabled": False, "connection_status": "disconnected",
         "auth_status": "unknown", "tool_count": 0},
    ],
    "tools": [{"tool_id": "circuit.search_mail", "plugin_id": "circuit", "name": "search_mail",
               "title": "Chercher des mails", "description": "Chercher des mails\nDétail.",
               "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
               "output_schema": None, "side_effect": "read", "idempotent": True, "atomicity": "external",
               "open_world": True}],
}


def test_an_external_descriptor_has_the_native_shape_plus_its_plugin_fields():
    descriptor = mcp_catalog.describe_external_tool(EXTERNAL["tools"][0])
    assert set(descriptor) == _DESCRIPTOR_KEYS | {"invocation", "plugin_id", "tool_id"}
    assert (descriptor["server"], descriptor["qualified_name"], descriptor["category"]) == (
        "circuit", "circuit.search_mail", "external")
    assert descriptor["label"] == "Chercher des mails" and descriptor["summary"] == "Chercher des mails"
    assert descriptor["invocation"] == "managed_external" and descriptor["output"]["format"] == "untyped"
    assert descriptor["parameters"][0]["name"] == "q" and descriptor["parameters"][0]["required"] is True
    assert descriptor["annotations"] == {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True}
    assert descriptor["context_bytes"] > 0 and descriptor["deprecation"] is None


def test_merge_adds_every_plugin_server_and_only_exposed_tools(catalog):
    merged = mcp_catalog.merge_external(catalog, EXTERNAL)
    managed = [entry for entry in merged["servers"] if entry["registration"] == "managed"]
    assert [(entry["server"], entry["tool_count"], entry["module"]) for entry in managed] == [
        ("circuit", 1, None), ("offline", 0, None)]
    assert [tool["qualified_name"] for tool in merged["tools"] if tool["category"] == "external"
            and tool["server"] != "jarvis-drive"] == ["circuit.search_mail"]
    assert len(catalog["servers"]) == len(merged["servers"]) - 2  # le catalogue natif en cache est intact
    facts = mcp_catalog.plugin_facts(merged)
    assert facts["circuit"]["state"] == "advertised" and facts["offline"]["state"] == "disabled"
    assert facts["circuit"]["advertised"] is None and facts["circuit"]["auth_status"] == "authorized"


@pytest.mark.parametrize("schema", [{"type": "object", "properties": {"p": "notadict"}}, {"properties": ["x"]},
                                    {"type": "object", "properties": {"q": {}}, "required": 7}])
def test_merge_skips_a_malformed_descriptor_and_keeps_the_rest(catalog, schema):
    """QA 2 Slice 04 : un schéma intérieur illisible tuait `merge_external` (donc `/api/mcp/tools`)."""

    bad = {**EXTERNAL["tools"][0], "tool_id": "circuit.broken", "name": "broken", "input_schema": schema}
    skipped: list[str] = []
    merged = mcp_catalog.merge_external(catalog, {**EXTERNAL, "tools": [*EXTERNAL["tools"], bad, "x"]},
                                        skipped=skipped)
    assert skipped == ["circuit.broken", "?"]
    assert [tool["qualified_name"] for tool in merged["tools"] if tool["server"] == "circuit"] == ["circuit.search_mail"]
    assert len([tool for tool in merged["tools"] if tool["category"] != "external"]) > 0  # natifs intacts


@pytest.mark.parametrize("schema", [
    {"type": "object", "properties": {"p": "notadict", "q": {"type": "string"}}, "required": "q"},
    {"properties": ["x"]}, "pas un schéma",
    {"type": "object", "properties": {"a": {"anyOf": "x", "items": 3, "$ref": 5}}, "$defs": []},
])
def test_parameters_of_never_raises_on_a_malformed_schema(schema):
    parameters = mcp_catalog.parameters_of(schema)
    assert all(isinstance(parameter["name"], str) for parameter in parameters)


def test_plugin_availability_reuses_the_existing_states():
    base = {"enabled": True, "connection_status": "connected", "auth_status": "authorized"}
    assert mcp_catalog.plugin_availability(base)["state"] == "advertised"
    assert mcp_catalog.plugin_availability({**base, "connection_status": "error"})["state"] == "known"
    assert mcp_catalog.plugin_availability({**base, "enabled": False})["state"] == "disabled"


def test_merge_with_core_down_keeps_natives_and_says_core_unreachable(catalog):
    merged = mcp_catalog.merge_external(catalog, None)
    assert merged["servers"] == catalog["servers"] and merged["tools"] == catalog["tools"]
    assert merged["unavailable"][-1] == {"server": "plugins", "category": "external", "error": "core_unreachable"}
    facts = {meta.server: availability(meta.server) for meta in SERVERS}
    view = mcp_catalog.list_view(merged, facts)
    plugins = view["servers"][-1]
    assert (plugins["server"], plugins["described"], plugins["registration"], plugins["availability"]["state"]) == (
        "plugins", False, "managed", "known")
    assert mcp_catalog.detail_view(merged, "plugins", "x", facts)[0] == 404


def test_jarvis_drive_stays_an_introspected_operator_server_next_to_plugins(catalog):
    """Slice 07 (ARCH §11) : avec des plugins fusionnés, `jarvis-drive` reste listé, introspecté, `operator`, `known`."""

    merged = mcp_catalog.merge_external(catalog, EXTERNAL)
    facts = {**{meta.server: availability(meta.server) for meta in SERVERS}, **mcp_catalog.plugin_facts(merged)}
    view = mcp_catalog.list_view(merged, facts)
    drive = next(entry for entry in view["servers"] if entry["server"] == "jarvis-drive")
    assert (drive["registration"], drive["described"], drive["error"], drive["availability"]["state"]) == (
        "operator", True, None, "known")
    names = tuple(tool["name"] for tool in merged["tools"] if tool["server"] == "jarvis-drive")
    assert names == tool_names("jarvis-drive") and drive["tool_count"] == len(names) == 7
    assert all(card["availability"] == "known" for card in view["tools"] if card["server"] == "jarvis-drive")


def test_list_and_detail_views_serve_plugin_tools(catalog):
    merged = mcp_catalog.merge_external(catalog, EXTERNAL)
    facts = {**{meta.server: availability(meta.server) for meta in SERVERS}, **mcp_catalog.plugin_facts(merged)}
    view = mcp_catalog.list_view(merged, facts)
    assert [entry["server"] for entry in view["servers"]][-3:] == ["circuit", "jarvis-drive", "offline"]
    card = next(card for card in view["tools"] if card["server"] == "circuit")
    assert card["availability"] == "advertised" and card["qualified_name"] == "circuit.search_mail"
    status, body = mcp_catalog.detail_view(merged, "circuit", "search_mail", facts)
    assert status == 200 and body["tool"]["availability"]["connection_status"] == "connected"


@pytest.mark.parametrize(("snapshot", "expected"), [
    ({"state": "running", "tools_gateway": True}, True),
    ({"state": "ready", "tools_gateway": True}, True),  # Codex entre deux tours (plugins MCP, Slice 05)
    ({"state": "ready", "tools_gateway": False}, False),
    ({"state": "stopped", "tools_gateway": True}, False),
    ({"state": "exited", "tools_gateway": True}, False),
    ({"state": "running"}, None),
])
def test_the_gateway_flag_is_read_from_a_live_snapshot_of_either_agent(snapshot, expected):
    assert mcp_catalog.advertised_from_agent_snapshot("jarvis-tools", snapshot) is expected
