"""API catalogue MCP du Control Center (handoff jarvis-mcp-semantic-batch-inspector, Slice 06).

Contrat : `docs/mcp/tool-contract.md` §4.3 (disponibilité), §8 (routes), §9/§2
(aucun secret). Ce qui doit tenir :

- `GET /api/mcp/tools` : serveurs (disponibilité complète) + cartes compactes,
  ordre déterministe (catégorie §3, serveur, ordre d'enregistrement) ;
- `GET /api/mcp/tools/{server}/{name}` : descripteur complet + disponibilité ;
  inconnu → 404 `mcp_tool_unknown` ; serveur non importable → 503
  `mcp_server_unavailable` ; catalogue impossible → 503 `mcp_catalog_unavailable` ;
- disponibilité recalculée à chaque requête depuis les réglages courants, les
  cibles et l'instantané de l'agent — jamais devinée ;
- rien que des GET sous `/api/mcp` : aucune route d'exécution ;
- aucune valeur d'environnement, aucun chemin de jeton, de configuration ou du
  dossier utilisateur dans une réponse ;
- la surface visible du modèle ne bouge pas.
"""

from __future__ import annotations

import json
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.runtime import barehands_test_mode, credentials as creds, mcp_catalog
from jarvis.runtime.barehands_mcp import BarehandsMcpTarget
from jarvis.runtime.control_center import MCP_TOOLS_ROUTE, ControlCenter
from jarvis.runtime.display_mcp import DisplayMcpTarget
from jarvis.runtime.mcp_tool_meta import CATEGORY_ORDER, SERVERS, tool_names
from jarvis.runtime.settings_mcp import ConsoleMcpTarget

_CARD_KEYS = {"server", "name", "qualified_name", "category", "label", "summary", "side_effect", "atomicity",
              "idempotent", "availability", "deprecated", "parameter_count", "required_count", "context_bytes"}
_SERVER_KEYS = {"server", "category", "category_label", "condition", "registration", "described", "error",
                "tool_count", "context_bytes", "availability"}
_AVAILABILITY_KEYS = {"state", "condition", "condition_value", "next_launch", "advertised", "pending_restart"}
_DESCRIPTOR_KEYS = {"name", "server", "qualified_name", "category", "label", "summary", "description", "input_schema",
                    "parameters", "parameter_rules", "output", "side_effect", "idempotent", "atomicity", "annotations",
                    "deprecation", "context_bytes", "availability"}


def _center(tmp_path: Path, *, scene: bool | None = None, hands: bool | None = None, targets: bool = True,
            snapshot: dict | None = None) -> ControlCenter:
    settings: dict = {}
    if scene is not None:
        settings["scene"] = {"enabled": scene}
    if hands is not None:
        settings[barehands_test_mode.SETTING_KEY] = {barehands_test_mode.SCHEMA_KEY: barehands_test_mode.SCHEMA_VERSION,
                                                     "enabled": hands}
    runtime = tmp_path / "runtime"
    runtime.mkdir(exist_ok=True)
    if settings:
        (runtime / "control-center-settings.json").write_text(json.dumps(settings), encoding="utf-8")
    kwargs = {}
    if targets:
        kwargs = {
            "display_mcp": DisplayMcpTarget("127.0.0.1", 47001, tmp_path / "sentinel-core.token", runtime),
            "barehands_mcp": BarehandsMcpTarget("127.0.0.1", 47002, runtime),
            "console_mcp": ConsoleMcpTarget("127.0.0.1", 47002, runtime),
        }
    center = ControlCenter(runtime_root=runtime, project_root=tmp_path, **kwargs)
    if snapshot is not None:
        center.agent.snapshot = lambda: dict(snapshot)  # type: ignore[method-assign]
    return center


async def _get(center: ControlCenter, path: str):
    async with TestClient(TestServer(center._app)) as client:
        response = await client.get(path)
        return response.status, await response.json()


def _running(**flags: bool) -> dict:
    return {"name": "Claude", "state": "running", "display_tools": False, "barehands_tools": False,
            "console_tools": False, **flags}


def _servers(body: dict) -> dict[str, dict]:
    return {entry["server"]: entry for entry in body["servers"]}


# ------------------------------------------------------------------ liste

async def test_the_list_carries_servers_and_compact_cards_in_the_contract_order(tmp_path):
    status, body = await _get(_center(tmp_path), MCP_TOOLS_ROUTE)
    assert status == 200 and body["ok"] is True
    assert [entry["category"] for entry in body["categories"]] == list(CATEGORY_ORDER)
    assert [entry["server"] for entry in body["servers"]] == [
        "jarvis-display", "jarvis-console", "jarvis-barehands", "jarvis-drive"]
    for entry in body["servers"]:
        assert set(entry) == _SERVER_KEYS and set(entry["availability"]) == _AVAILABILITY_KEYS
        assert entry["described"] is True and entry["error"] is None
    expected = [(meta.server, name) for meta in SERVERS for name in tool_names(meta.server)]
    expected.sort(key=lambda pair: [meta.server for meta in SERVERS].index(pair[0]))
    assert [(card["server"], card["name"]) for card in body["tools"]] == expected
    for card in body["tools"]:
        assert set(card) == _CARD_KEYS
        assert card["availability"] in {"advertised", "configured", "disabled", "known"}
        assert card["qualified_name"] == f"mcp__{card['server']}__{card['name']}"
        assert 0 <= card["required_count"] <= card["parameter_count"]
    assert _servers(body)["jarvis-display"]["tool_count"] == 13
    deprecated = {card["name"] for card in body["tools"] if card["deprecated"]}
    assert deprecated == {"barehands_tutorial"}


async def test_the_list_and_detail_are_deterministic_across_requests(tmp_path):
    center = _center(tmp_path)
    first = await _get(center, MCP_TOOLS_ROUTE)
    second = await _get(center, MCP_TOOLS_ROUTE)
    assert json.dumps(first, sort_keys=False) == json.dumps(second, sort_keys=False)
    path = f"{MCP_TOOLS_ROUTE}/jarvis-display/scene_update_many"
    assert json.dumps(await _get(center, path)) == json.dumps(await _get(center, path))


async def test_the_card_counts_derive_from_the_descriptor_parameters(tmp_path):
    center = _center(tmp_path)
    _, listed = await _get(center, MCP_TOOLS_ROUTE)
    card = next(card for card in listed["tools"] if card["name"] == "scene_update_many")
    _, detail = await _get(center, f"{MCP_TOOLS_ROUTE}/jarvis-display/scene_update_many")
    parameters = detail["tool"]["parameters"]
    assert card["parameter_count"] == len(parameters)
    assert card["required_count"] == sum(parameter["required"] for parameter in parameters)
    assert card["context_bytes"] == detail["tool"]["context_bytes"]


# ------------------------------------------------------------------ détail

async def test_the_detail_is_the_full_descriptor_with_its_availability(tmp_path):
    status, body = await _get(_center(tmp_path), f"{MCP_TOOLS_ROUTE}/jarvis-display/scene_update_many")
    assert status == 200 and body["ok"] is True
    tool = body["tool"]
    assert set(tool) == _DESCRIPTOR_KEYS
    assert set(tool["availability"]) == _AVAILABILITY_KEYS
    assert tool["atomicity"] == "atomic_batch" and tool["output"]["format"] == "structured"
    assert tool["input_schema"]["additionalProperties"] is False
    for parameter in tool["parameters"]:
        assert {"name", "type", "required", "has_default", "constraints", "description"} <= set(parameter)
        assert ("default" in parameter) == parameter["has_default"]
    assert tool["annotations"]["readOnlyHint"] is False


async def test_a_text_output_tool_carries_its_text_schema_and_notes(tmp_path):
    _, body = await _get(_center(tmp_path), f"{MCP_TOOLS_ROUTE}/jarvis-display/scene_inspect")
    output = body["tool"]["output"]
    assert output["format"] == "json_text" and output["schema"]["type"] == "object"
    assert output["advertised_schema"] is False


async def test_the_deprecated_tool_carries_its_deprecation(tmp_path):
    _, body = await _get(_center(tmp_path), f"{MCP_TOOLS_ROUTE}/jarvis-barehands/barehands_tutorial")
    assert set(body["tool"]["deprecation"]) == {"replacement", "removal_condition", "since", "legacy_doc"}


@pytest.mark.parametrize("path", [
    "/jarvis-display/scene_nope",
    "/jarvis-nope/scene_inspect",
    "/jarvis-console/scene_inspect",  # vrai nom, mauvais serveur
    "/jarvis-display/%3Cscript%3E",
])
async def test_an_unknown_tool_is_a_stable_404_that_echoes_nothing(tmp_path, path):
    status, body = await _get(_center(tmp_path), MCP_TOOLS_ROUTE + path)
    assert status == 404
    assert body == {"ok": False, "code": "mcp_tool_unknown", "error": "unknown MCP tool"}


@pytest.mark.parametrize("path", [
    f"{MCP_TOOLS_ROUTE}/jarvis-display/scene_inspect/run",  # trop de segments
    f"{MCP_TOOLS_ROUTE}/jarvis-display",                      # un seul segment
    "/api/mcp",
    "/api/mcp/servers",
])
async def test_any_unmatched_path_under_the_mcp_prefix_is_the_same_coded_404(tmp_path, path):
    status, body = await _get(_center(tmp_path), path)
    assert status == 404
    assert body == {"ok": False, "code": "mcp_tool_unknown", "error": "unknown MCP tool"}


async def test_other_routes_keep_the_plain_aiohttp_404(tmp_path):
    async with TestClient(TestServer(_center(tmp_path)._app)) as client:
        response = await client.get("/api/nope")
        assert response.status == 404 and response.content_type == "text/plain"


# ------------------------------------------------------------------ serveur ou catalogue indisponible

async def test_a_server_that_cannot_import_is_marked_unavailable_not_a_500(tmp_path, monkeypatch):
    real = mcp_catalog.build_introspection_server

    def without_google(server: str):
        if server == "jarvis-drive":
            raise ModuleNotFoundError(f"No module named 'googleapiclient' ({tmp_path})")
        return real(server)

    monkeypatch.setattr(mcp_catalog, "_CACHE", None)
    monkeypatch.setattr(mcp_catalog, "build_introspection_server", without_google)
    center = _center(tmp_path)
    status, body = await _get(center, MCP_TOOLS_ROUTE)
    assert status == 200
    drive = _servers(body)["jarvis-drive"]
    assert drive["described"] is False and drive["error"] == "ModuleNotFoundError" and drive["tool_count"] == 0
    assert drive["availability"]["state"] == "known"
    assert not any(card["server"] == "jarvis-drive" for card in body["tools"])
    assert [entry["server"] for entry in body["servers"]][-1] == "jarvis-drive"
    status, detail = await _get(center, f"{MCP_TOOLS_ROUTE}/jarvis-drive/drive_search")
    assert status == 503
    assert detail == {"ok": False, "code": "mcp_server_unavailable",
                      "error": "MCP server not describable (ModuleNotFoundError)", "server": "jarvis-drive"}
    text = json.dumps([body, detail])
    assert "googleapiclient" not in text and str(tmp_path) not in text


async def test_a_catalog_that_cannot_be_built_is_a_coded_503_and_journaled(tmp_path, monkeypatch):
    async def broken():
        raise LookupError(f"jarvis-display: tools without shared metadata ({tmp_path})")

    monkeypatch.setattr(mcp_catalog, "cached_catalog", broken)
    center = _center(tmp_path)
    for path in (MCP_TOOLS_ROUTE, f"{MCP_TOOLS_ROUTE}/jarvis-display/scene_inspect"):
        status, body = await _get(center, path)
        assert status == 503
        assert body == {"ok": False, "code": "mcp_catalog_unavailable",
                        "error": "MCP catalog could not be built (LookupError)"}
    trace = center.journal.trace_path.read_text(encoding="utf-8")
    assert '"mcp.catalog_failed"' in trace and str(tmp_path) not in json.dumps(body)


async def test_the_first_successful_build_is_journaled_once(tmp_path):
    center = _center(tmp_path)
    await _get(center, MCP_TOOLS_ROUTE)
    await _get(center, MCP_TOOLS_ROUTE)
    lines = [line for line in center.journal.trace_path.read_text(encoding="utf-8").splitlines()
             if '"mcp.catalog_built"' in line]
    assert len(lines) == 1


# ------------------------------------------------------------------ disponibilité (§4.3)

async def _availability(tmp_path, **kwargs) -> dict[str, dict]:
    _, body = await _get(_center(tmp_path, **kwargs), MCP_TOOLS_ROUTE)
    return {server: entry["availability"] for server, entry in _servers(body).items()}


async def test_brain_stopped_everything_configured_is_configured_and_nothing_pending(tmp_path):
    # Amendement agent 0 (§4.3) : cerveau arrêté → le prochain démarrage prend la configuration courante.
    facts = await _availability(tmp_path, scene=True, hands=True, snapshot={"state": "stopped"})
    for server in ("jarvis-display", "jarvis-barehands", "jarvis-console"):
        assert facts[server]["state"] == "configured" and facts[server]["next_launch"] == "configured"
        assert facts[server]["advertised"] is False and facts[server]["pending_restart"] is False
    assert facts["jarvis-display"]["condition_value"] is True and facts["jarvis-console"]["condition_value"] is None
    assert facts["jarvis-drive"] == {"state": "known", "condition": None, "condition_value": None, "next_launch": None,
                                     "advertised": None, "pending_restart": False}


async def test_an_exited_brain_has_nothing_pending_either(tmp_path):
    facts = await _availability(tmp_path, scene=False, snapshot={"state": "exited"})
    assert facts["jarvis-display"]["state"] == "disabled" and facts["jarvis-display"]["pending_restart"] is False


async def test_running_brain_with_every_server_is_advertised_and_nothing_pending(tmp_path):
    facts = await _availability(tmp_path, scene=True, hands=True,
                                snapshot=_running(display_tools=True, barehands_tools=True, console_tools=True))
    for server in ("jarvis-display", "jarvis-barehands", "jarvis-console"):
        assert facts[server]["state"] == "advertised" and facts[server]["pending_restart"] is False


async def test_scene_turned_off_while_the_brain_still_advertises_display_is_pending_restart(tmp_path):
    facts = await _availability(tmp_path, scene=False, hands=False,
                                snapshot=_running(display_tools=True, console_tools=True))
    display = facts["jarvis-display"]
    assert display == {"state": "advertised", "condition": "scene.enabled", "condition_value": False,
                       "next_launch": "disabled", "advertised": True, "pending_restart": True}
    assert facts["jarvis-barehands"] == {"state": "disabled", "condition": "barehands.enabled", "condition_value": False,
                                         "next_launch": "disabled", "advertised": False, "pending_restart": False}
    assert facts["jarvis-console"]["state"] == "advertised" and facts["jarvis-console"]["condition"] is None


async def test_scene_off_and_brain_restarted_is_disabled(tmp_path):
    facts = await _availability(tmp_path, scene=False, snapshot=_running(console_tools=True))
    assert facts["jarvis-display"]["state"] == "disabled" and facts["jarvis-display"]["pending_restart"] is False


async def test_switch_turned_on_while_running_without_it_is_configured_pending_restart(tmp_path):
    facts = await _availability(tmp_path, scene=True, hands=True, snapshot=_running(console_tools=True))
    assert facts["jarvis-display"]["state"] == "configured" and facts["jarvis-display"]["pending_restart"] is True
    assert facts["jarvis-barehands"]["state"] == "configured" and facts["jarvis-barehands"]["pending_restart"] is True


async def test_no_target_means_disabled_whatever_the_switch(tmp_path):
    facts = await _availability(tmp_path, scene=True, hands=True, targets=False, snapshot={"state": "stopped"})
    for server in ("jarvis-display", "jarvis-barehands", "jarvis-console"):
        assert facts[server]["state"] == "disabled" and facts[server]["next_launch"] == "disabled"
    assert facts["jarvis-display"]["condition_value"] is True  # le réglage est affiché tel quel


async def test_a_flagless_claude_snapshot_leaves_advertised_unknown_never_guessed(tmp_path):
    facts = await _availability(tmp_path, scene=True, snapshot={"name": "Claude", "state": "running"})
    assert facts["jarvis-display"]["advertised"] is None and facts["jarvis-display"]["pending_restart"] is False
    assert facts["jarvis-display"]["state"] == "configured"


@pytest.mark.parametrize("state", [None, "ready", "running"])
async def test_codex_never_receives_native_servers_so_advertised_is_false_in_every_state(tmp_path, state):
    center = _center(tmp_path, scene=True, hands=True)
    center._agent_id = "codex"
    assert type(center.agent).__name__ == "CodexLocalAgent" and not hasattr(center.agent, "display_mcp")
    if state is not None:
        center.agent.snapshot = lambda: {"name": "Codex", "state": state}  # type: ignore[method-assign]
    _, body = await _get(center, MCP_TOOLS_ROUTE)
    for server in ("jarvis-display", "jarvis-barehands", "jarvis-console"):
        facts = _servers(body)[server]["availability"]
        assert facts["advertised"] is False and facts["next_launch"] == "disabled"
        assert facts["state"] == "disabled" and facts["pending_restart"] is False
    assert _servers(body)["jarvis-display"]["availability"]["condition_value"] is True


async def test_a_failing_agent_snapshot_leaves_advertised_unknown_and_is_journaled(tmp_path):
    center = _center(tmp_path, scene=True)

    def broken():
        raise OSError(f"pipe closed ({tmp_path})")

    center.agent.snapshot = broken  # type: ignore[method-assign]
    status, body = await _get(center, MCP_TOOLS_ROUTE)
    assert status == 200
    display = _servers(body)["jarvis-display"]["availability"]
    assert display["advertised"] is None and display["pending_restart"] is False and display["state"] == "configured"
    trace = center.journal.trace_path.read_text(encoding="utf-8")
    assert '"mcp.availability_failed"' in trace and "OSError" in trace and str(tmp_path) not in json.dumps(body)


async def test_the_scene_environment_override_is_the_switch_value(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_SCENE_ENABLED", "0")
    facts = await _availability(tmp_path, scene=True, snapshot={"state": "stopped"})
    assert facts["jarvis-display"]["state"] == "disabled"


async def test_next_launch_follows_what_the_agent_holds_not_a_reread_of_the_file(tmp_path):
    """F1 : `next_launch` = ce que le prochain lancement passera vraiment (cibles de l'agent)."""

    center = _center(tmp_path, scene=True, snapshot={"state": "stopped"})
    _, before = await _get(center, MCP_TOOLS_ROUTE)
    assert _servers(before)["jarvis-display"]["availability"]["next_launch"] == "configured"
    # Le fichier change sans passer par le Control Center : l'agent tient toujours la cible.
    center.settings_path.write_text(json.dumps({"scene": {"enabled": False}}), encoding="utf-8")
    _, edited = await _get(center, MCP_TOOLS_ROUTE)
    display = _servers(edited)["jarvis-display"]["availability"]
    assert display["condition_value"] is False and display["next_launch"] == "configured"
    # L'enregistrement par l'API, lui, retire la cible de l'agent : recalculé à la requête suivante.
    async with TestClient(TestServer(center._app)) as client:
        assert (await client.post("/api/settings", json={"scene": {"enabled": False}})).status == 200
        after = await (await client.get(MCP_TOOLS_ROUTE)).json()
    assert center.agent.display_mcp is None
    assert _servers(after)["jarvis-display"]["availability"]["state"] == "disabled"
    card = next(card for card in after["tools"] if card["name"] == "scene_inspect")
    assert card["availability"] == "disabled"


async def test_the_real_agent_snapshot_feeds_advertised(tmp_path):
    center = _center(tmp_path, scene=True)
    snapshot = center.agent.snapshot()
    assert {"display_tools", "barehands_tools", "console_tools"} <= set(snapshot)
    _, body = await _get(center, MCP_TOOLS_ROUTE)
    assert _servers(body)["jarvis-display"]["availability"]["advertised"] is False  # cerveau pas lancé


# ------------------------------------------------------------------ lecture seule

def test_only_get_routes_exist_under_the_mcp_prefix(tmp_path):
    center = _center(tmp_path)
    methods: dict[str, set[str]] = {}
    for route in center._app.router.routes():
        if route.resource.canonical.startswith("/api/mcp"):
            methods.setdefault(route.resource.canonical, set()).add(route.method)
    assert methods == {MCP_TOOLS_ROUTE: {"GET", "HEAD"}, MCP_TOOLS_ROUTE + "/{server}/{name}": {"GET", "HEAD"}}


async def test_writing_methods_are_refused_on_the_catalog(tmp_path):
    async with TestClient(TestServer(_center(tmp_path)._app)) as client:
        for path in (MCP_TOOLS_ROUTE, f"{MCP_TOOLS_ROUTE}/jarvis-display/scene_archive"):
            for method in ("POST", "PUT", "DELETE", "PATCH"):
                response = await client.request(method, path, json={})
                assert response.status == 405
                assert await response.json() == {"ok": False, "code": "method_not_allowed",
                                                 "error": "the MCP catalog is read-only (GET)"}
                assert set(response.headers["Allow"].replace(" ", "").split(",")) == {"GET", "HEAD"}


# ------------------------------------------------------------------ aucun secret

async def test_no_secret_path_or_environment_value_reaches_a_response(tmp_path, monkeypatch):
    sentinels = {
        "JARVIS_CORE_TOKEN_FILE": "C:/secret-sentinel/core.token",
        "JARVIS_RUNTIME_DIR": "C:/secret-sentinel/runtime",
        "GOOGLE_DRIVE_TOKEN": "C:/secret-sentinel/drive-token.json",
        "GOOGLE_DRIVE_CLIENT_SECRET": "C:/secret-sentinel/client-secret.json",
        "ANTHROPIC_API_KEY": "sk-ant-sentinel-000000000000",
        "OPENAI_API_KEY": "sk-proj-sentinel-111111111111",
        "JARVIS_CLAUDE_CLI": "C:/secret-sentinel/bin/claude.exe",
    }
    for key, value in sentinels.items():
        monkeypatch.setenv(key, value)
    center = _center(tmp_path, scene=True, hands=True,
                     snapshot=_running(display_tools=True, barehands_tools=True, console_tools=True))
    # Une clé enregistrée par le vrai magasin (liste d'enregistrements), comme l'écran des identifiants.
    stored = json.loads(center.settings_path.read_text(encoding="utf-8"))
    creds.upsert_credential(stored, provider="anthropic", name="sentinel", value="sk-ant-stored-sentinel-222")
    assert "sk-ant-stored-sentinel-222" in json.dumps(stored["credentials"])
    center.settings_path.write_text(json.dumps(stored), encoding="utf-8")
    bodies = [await _get(center, MCP_TOOLS_ROUTE)]
    for meta in SERVERS:
        for name in tool_names(meta.server):
            bodies.append(await _get(center, f"{MCP_TOOLS_ROUTE}/{meta.server}/{name}"))
    bodies.append(await _get(center, f"{MCP_TOOLS_ROUTE}/jarvis-display/nope"))
    text = json.dumps(bodies, ensure_ascii=False)
    for value in (*sentinels.values(), "sk-ant-stored-sentinel-222"):
        assert value not in text
    for marker in ("secret-sentinel", "sentinel-core.token", str(tmp_path), str(Path.home()), "mcpServers",
                   "--mcp-config", "token_file", "47001", "47002"):
        assert marker not in text, marker


# ------------------------------------------------------------------ surface du modèle inchangée

async def test_the_api_does_not_change_the_model_visible_display_surface(tmp_path):
    _, body = await _get(_center(tmp_path), MCP_TOOLS_ROUTE)
    assert _servers(body)["jarvis-display"]["context_bytes"] == 31_864
    names = [card["name"] for card in body["tools"] if card["server"] == "jarvis-display"]
    assert names == list(tool_names("jarvis-display")) and len(names) == 13
