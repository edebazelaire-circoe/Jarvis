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
                    "deprecation", "context_bytes", "availability", "ui"}


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
            # `jarvis-capture` (Slice 09 session-context-recording) : même forme de cible que la console.
            "capture_mcp": ConsoleMcpTarget("127.0.0.1", 47002, runtime),
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
    # Plugins MCP (Slice 04) : la passerelle `jarvis-tools` (catégorie `general`) ouvre la liste ; sans Core,
    # une entrée `plugins` non décrite (`core_unreachable`) la ferme, natifs intacts.
    assert [entry["server"] for entry in body["servers"]] == [
        "jarvis-tools", "jarvis-display", "jarvis-console", "jarvis-workspace", "jarvis-capture", "jarvis-barehands",
        "jarvis-drive", "plugins"]
    for entry in body["servers"]:
        assert set(entry) == _SERVER_KEYS and set(entry["availability"]) == _AVAILABILITY_KEYS
        if entry["server"] == "plugins":
            assert (entry["described"], entry["error"], entry["registration"]) == (False, "core_unreachable", "managed")
            continue
        assert entry["described"] is True and entry["error"] is None
    order = [meta.server for meta in SERVERS]
    by_server = {meta.server: meta for meta in SERVERS}
    expected = [(meta.server, name) for meta in SERVERS for name in tool_names(meta.server)]
    expected.sort(key=lambda pair: (CATEGORY_ORDER.index(by_server[pair[0]].category), order.index(pair[0])))
    assert [(card["server"], card["name"]) for card in body["tools"]] == expected
    for card in body["tools"]:
        assert set(card) == _CARD_KEYS
        assert card["availability"] in {"advertised", "configured", "disabled", "known"}
        assert card["qualified_name"] == f"mcp__{card['server']}__{card['name']}"
        assert 0 <= card["required_count"] <= card["parameter_count"]
    assert _servers(body)["jarvis-display"]["tool_count"] == 20
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
    assert [entry["server"] for entry in body["servers"]][-2:] == ["jarvis-drive", "plugins"]
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
    for server in ("jarvis-display", "jarvis-barehands", "jarvis-console", "jarvis-capture"):
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
                                snapshot=_running(display_tools=True, barehands_tools=True, console_tools=True,
                                                  capture_tools=True))
    for server in ("jarvis-display", "jarvis-barehands", "jarvis-console", "jarvis-capture"):
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
    for server in ("jarvis-display", "jarvis-barehands", "jarvis-console", "jarvis-capture"):
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
    for server in ("jarvis-display", "jarvis-barehands", "jarvis-console", "jarvis-capture"):
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

def test_only_get_routes_exist_under_the_catalog_and_the_plugin_set_is_pinned(tmp_path):
    """Le catalogue reste en lecture seule ; la gestion des plugins (Slice 06 de
    generic-mcp-plugin-runtime, ARCH §14 C5) est un ensemble fermé de routes,
    et aucune ne peut exécuter un outil (tool-contract §8)."""

    center = _center(tmp_path)
    methods: dict[str, set[str]] = {}
    for route in center._app.router.routes():
        if route.resource.canonical.startswith("/api/mcp"):
            methods.setdefault(route.resource.canonical, set()).add(route.method)
    catalog = {path: verbs for path, verbs in methods.items() if path.startswith(MCP_TOOLS_ROUTE)}
    assert catalog == {MCP_TOOLS_ROUTE: {"GET", "HEAD"}, MCP_TOOLS_ROUTE + "/{server}/{name}": {"GET", "HEAD"}}
    plugins = {path: verbs for path, verbs in methods.items() if not path.startswith(MCP_TOOLS_ROUTE)}
    item = "/api/mcp/plugins/{plugin_id}"
    assert plugins == {
        "/api/mcp/plugins": {"GET", "HEAD", "POST"},
        item: {"GET", "HEAD", "PATCH", "DELETE"},
        item + "/connect": {"POST"},
        item + "/disconnect": {"POST"},
        item + "/refresh": {"POST"},
        item + "/credential": {"PUT"},
        "/api/mcp/oauth/callback": {"GET"},  # sans HEAD : une requête sans corps ne consomme pas un `state`
    }
    assert not any(path.rstrip("/").split("/")[-1] in {"call", "execute", "invoke"} for path in methods)


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
    # 31 864 o à l'origine ; +734 o (475 sur scene_create_object, 259 sur scene_update_object) depuis
    # le paramètre `source_path` (objet lié à un fichier) : 32 598 o.
    # Prefab-foundation Slice 07 : +5 853 o = six outils prefab_* (search 820, get 657, validate 642, save 1 011,
    # edit_base 1 086, events 543 : 4 759 o) + argument `prefab` (547 o sur scene_create_object, 547 sur
    # scene_update_object). Budget relevé à 39 000 o (tool-contract §10.13).
    # Reprise S07 (QA) : -160 o = argument `prefab` 547 -> 493 o (x2), « Lecture seule » retiré de search/get/events
    # (-16, -16, -15), description de prefab_edit_base reformulée (-26) et user_request « nomment ce prefab » (+21) :
    # outils 4 707 o (search 804, get 641, validate 642, save 1 011, edit_base 1 081, events 528).
    # Tool Brain S4 : +1 225 o = `ui_intent_publish` (intention d'écran de Jarvis, tool-contract amendement S4).
    assert _servers(body)["jarvis-display"]["context_bytes"] == 39_516
    names = [card["name"] for card in body["tools"] if card["server"] == "jarvis-display"]
    assert names == list(tool_names("jarvis-display")) and len(names) == 20


# ------------------------------------------------------------------ plugins MCP (generic-mcp-plugin-runtime, Slice 04)

PLUGIN_SENTINEL = "SENTINEL-SECRET-7f3a"
_EXTERNAL = {
    "catalog_revision": 41, "unchanged": False,
    "plugins": [{"plugin_id": "circuit", "display_name": "Circuit", "enabled": True,
                 "connection_status": "connected", "auth_status": "authorized", "tool_count": 1}],
    "tools": [{"tool_id": "circuit.search_mail", "plugin_id": "circuit", "name": "search_mail", "title": None,
               "description": "Chercher des mails", "input_schema": {"type": "object"}, "output_schema": None,
               "side_effect": "read", "idempotent": True, "atomicity": "external", "open_world": True}],
}


class _Sessions:
    """Faux `CoreSessionTransport` : seule la lecture `GET /v1/mcp/tools` sert ici."""

    def __init__(self, *, fail: BaseException | None = None, delay: float = 0.0) -> None:
        self.fail = fail
        self.delay = delay
        self.asked: list[int | None] = []

    async def mcp_tools(self, *, since_revision, timeout_s):
        import asyncio

        self.asked.append(since_revision)
        assert timeout_s == ControlCenter.MCP_EXTERNAL_TIMEOUT_S
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail is not None:
            raise self.fail
        if since_revision == _EXTERNAL["catalog_revision"]:
            return {"catalog_revision": 41, "unchanged": True, "plugins": [], "tools": []}
        return json.loads(json.dumps(_EXTERNAL))


def _plugin_center(tmp_path, sessions) -> ControlCenter:
    center = _center(tmp_path)
    center.sessions = sessions  # la vue fusionnée lit Core par ce transport (Slice 04)
    return center


async def test_the_merged_list_serves_plugin_servers_and_tools_and_caches_by_revision(tmp_path):
    sessions = _Sessions()
    center = _plugin_center(tmp_path, sessions)
    status, body = await _get(center, MCP_TOOLS_ROUTE)
    assert status == 200
    circuit = _servers(body)["circuit"]
    assert set(circuit) == _SERVER_KEYS and circuit["registration"] == "managed" and circuit["tool_count"] == 1
    assert circuit["availability"]["state"] == "advertised" and circuit["availability"]["auth_status"] == "authorized"
    assert "plugins" not in _servers(body)
    card = next(card for card in body["tools"] if card["server"] == "circuit")
    assert card["qualified_name"] == "circuit.search_mail" and set(card) == _CARD_KEYS
    status, again = await _get(center, MCP_TOOLS_ROUTE)
    assert again == body and sessions.asked == [None, 41]


async def test_the_detail_of_a_plugin_tool_is_its_full_descriptor(tmp_path):
    status, body = await _get(_plugin_center(tmp_path, _Sessions()), MCP_TOOLS_ROUTE + "/circuit/search_mail")
    assert status == 200
    tool = body["tool"]
    assert set(tool) == _DESCRIPTOR_KEYS | {"invocation", "plugin_id", "tool_id"}
    assert tool["invocation"] == "managed_external" and tool["availability"]["connection_status"] == "connected"
    status, missing = await _get(_plugin_center(tmp_path, _Sessions()), MCP_TOOLS_ROUTE + "/circuit/nope")
    assert (status, missing["code"]) == (404, "mcp_tool_unknown")


@pytest.mark.parametrize("sessions", [
    None,
    _Sessions(fail=ConnectionError("Core session token is unavailable")),
    _Sessions(delay=3.0),
])
async def test_natives_are_still_served_when_core_is_down(tmp_path, sessions):
    center = _plugin_center(tmp_path, sessions)
    status, body = await _get(center, MCP_TOOLS_ROUTE)
    assert status == 200
    plugins = _servers(body)["plugins"]
    assert (plugins["described"], plugins["error"], plugins["registration"]) == (False, "core_unreachable", "managed")
    assert _servers(body)["jarvis-display"]["tool_count"] == 20
    assert not any(card["server"] == "circuit" for card in body["tools"])


async def test_core_down_is_journaled_once_then_the_recovery(tmp_path):
    sessions = _Sessions(fail=ConnectionError("down"))
    center = _plugin_center(tmp_path, sessions)
    await _get(center, MCP_TOOLS_ROUTE)
    await _get(center, MCP_TOOLS_ROUTE)
    sessions.fail = None
    await _get(center, MCP_TOOLS_ROUTE)
    trace = (tmp_path / "runtime" / "trace.jsonl").read_text(encoding="utf-8")
    kinds = [json.loads(line)["kind"] for line in trace.splitlines() if line.strip()]
    assert kinds.count("mcp.plugins_unreachable") == 1 and kinds.count("mcp.plugins_restored") == 1


async def test_a_malformed_plugin_descriptor_is_skipped_not_a_500(tmp_path):
    """QA 2 Slice 04 : `{"properties": {"p": "notadict"}}` faisait lever `parameters_of` dans `merge_external`."""

    class _BadSessions(_Sessions):
        async def mcp_tools(self, *, since_revision, timeout_s):
            payload = await super().mcp_tools(since_revision=since_revision, timeout_s=timeout_s)
            payload["tools"] = [*payload["tools"], {**_EXTERNAL["tools"][0], "tool_id": "circuit.broken",
                                                    "name": "broken", "input_schema": {"properties": {"p": "x"}}}]
            return payload

    center = _plugin_center(tmp_path, _BadSessions())
    status, body = await _get(center, MCP_TOOLS_ROUTE)
    await _get(center, MCP_TOOLS_ROUTE)
    assert status == 200 and _servers(body)["jarvis-display"]["tool_count"] == 20
    assert [card["qualified_name"] for card in body["tools"] if card["server"] == "circuit"] == ["circuit.search_mail"]
    trace = (tmp_path / "runtime" / "trace.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in trace.splitlines() if line.strip()]
    skipped = [row for row in rows if row["kind"] == "mcp.catalog.descriptor_skipped"]
    assert len(skipped) == 1 and skipped[0]["data"]["code"] == "mcp_tool_descriptor_invalid"
    assert skipped[0]["data"]["tool_ids"] == ["circuit.broken"]


async def test_no_plugin_secret_reaches_a_merged_response(tmp_path):
    center = _plugin_center(tmp_path, _Sessions())
    (tmp_path / "sentinel-core.token").write_text(PLUGIN_SENTINEL, encoding="utf-8")
    for path in (MCP_TOOLS_ROUTE, MCP_TOOLS_ROUTE + "/circuit/search_mail"):
        _, body = await _get(center, path)
        text = json.dumps(body)
        for marker in (PLUGIN_SENTINEL, "credential_ref", "sentinel-core.token", "endpoint"):
            assert marker not in text


async def test_the_gateway_server_is_listed_without_a_switch(tmp_path):
    facts = await _availability(tmp_path, snapshot={"state": "stopped"})
    # La cible `tools_mcp` arrive avec la Slice 05 : sans elle, le prochain lancement ne la déclare pas.
    assert facts["jarvis-tools"] == {"state": "disabled", "condition": None, "condition_value": None,
                                     "next_launch": "disabled", "advertised": False, "pending_restart": False}


# ------------------------------------------- passerelle jarvis-tools remise aux deux CLI (plugins MCP, Slice 05)


def _gateway_center(tmp_path, agent_id: str = "claude") -> ControlCenter:
    from jarvis.runtime.tools_gateway_mcp import ToolsGatewayTarget

    runtime = tmp_path / "runtime"
    runtime.mkdir(exist_ok=True)
    center = ControlCenter(runtime_root=runtime, project_root=tmp_path,
                           tools_mcp=ToolsGatewayTarget("127.0.0.1", 47001, tmp_path / "sentinel-core.token", runtime))
    center._agent_id = agent_id
    center._apply_agent_settings(center._settings())
    return center


@pytest.mark.parametrize("agent_id", ["claude", "codex"])
async def test_configure_agent_hands_the_gateway_to_both_clis(tmp_path, agent_id):
    center = _gateway_center(tmp_path, agent_id)
    assert center.agent.tools_mcp is center.tools_mcp
    _, body = await _get(center, MCP_TOOLS_ROUTE)
    facts = _servers(body)["jarvis-tools"]["availability"]
    assert facts["next_launch"] == "configured" and facts["condition"] is None


@pytest.mark.parametrize(("agent_id", "snapshot", "state", "advertised"), [
    ("claude", {"name": "Claude", "state": "running", "tools_gateway": True}, "advertised", True),
    ("claude", {"name": "Claude", "state": "running", "tools_gateway": False}, "configured", False),
    ("claude", {"name": "Claude", "state": "stopped", "tools_gateway": False}, "configured", False),
    # Codex : un processus par tour, `ready` entre deux tours reste une session vivante.
    ("codex", {"name": "Codex", "state": "ready", "tools_gateway": True}, "advertised", True),
    ("codex", {"name": "Codex", "state": "running", "tools_gateway": True}, "advertised", True),
    ("codex", {"name": "Codex", "state": "stopped", "tools_gateway": False}, "configured", False),
])
async def test_the_gateway_is_advertised_from_either_agent_snapshot(tmp_path, agent_id, snapshot, state, advertised):
    center = _gateway_center(tmp_path, agent_id)
    center.agent.snapshot = lambda: dict(snapshot)  # type: ignore[method-assign]
    _, body = await _get(center, MCP_TOOLS_ROUTE)
    facts = _servers(body)["jarvis-tools"]["availability"]
    assert (facts["state"], facts["advertised"]) == (state, advertised)
    if agent_id == "codex":
        # Les serveurs natifs restent refusés à Codex : seule la passerelle lui est remise.
        assert _servers(body)["jarvis-console"]["availability"]["advertised"] is False
