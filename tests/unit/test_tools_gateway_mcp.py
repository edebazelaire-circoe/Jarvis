"""Passerelle `jarvis-tools` (plugins MCP, Slice 04 ; `docs/mcp/plugins.md` §6-§7, ARCH §7).

Session client MCP en mémoire contre le vrai serveur FastMCP, avec un faux Core
et le vrai catalogue natif. Ce qui doit tenir :

- exactement deux outils, schémas stricts, annotations des métadonnées ;
- budgets : nom + description + schéma des deux outils ≤ 2 500 o, consignes ≤ 1 200 o ;
- `list_tools` : natifs = serveurs déclarés moins `jarvis-tools`, jamais `jarvis-drive` ;
  ≤ 5 recommandés complets, `call_as` des natifs, révision `n<fp8>.e<rev>`,
  réponse ≤ 24 576 o (500 outils), intentions différentes ⇒ recommandations
  différentes, Core injoignable ⇒ natifs + `plugins_unavailable`, révision
  changée ⇒ curseur repris `catalog_changed`, curseur d'une autre intention refusé ;
- `call_tool` : nom natif ⇒ `native_tool_call_directly` sans appel à Core, refus
  codés de Core rendus avec la suite à donner, erreur distante en `isError` ;
- configuration : `mcp_config` sans jeton, `codex_config_overrides`, `toml_value`.

Rework QA : E21 (natifs jamais dans `others`, `native_total`), entrée `too_large`
appelable, élément de Core mal formé ignoré et journalisé, index de classement
gardé par révision, suite du refus de curseur dite une seule fois.
"""

from __future__ import annotations

import asyncio
import json
import re

import pytest

from jarvis.domain.tool_discovery import MAX_RESPONSE_BYTES, size_of
from jarvis.protocol.client import CoreProtocolError
from jarvis.runtime import tools_gateway_mcp as gw
from jarvis.runtime.mcp_catalog import build_catalog, model_visible_bytes
from jarvis.runtime.mcp_tool_meta import annotation_hints
from jarvis.runtime.tools_gateway_mcp import (
    INSTRUCTIONS,
    SERVER_NAME,
    ToolsGateway,
    ToolsGatewayConfigError,
    ToolsGatewayTarget,
    build_server,
    codex_config_overrides,
    mcp_config,
    toml_value,
    write_mcp_config,
)

PLUGIN = "circuit-fake"
NATIVES = ("jarvis-display", "jarvis-console", "jarvis-tools", "jarvis-drive")
REVISION = re.compile(r"^n[0-9a-f]{8}\.e[0-9]+$")


def _tool(name: str, description: str, *, props: dict | None = None, required: list | None = None,
          side_effect: str = "read", plugin: str = PLUGIN) -> dict:
    return {"tool_id": f"{plugin}.{name}", "plugin_id": plugin, "name": name, "title": None,
            "description": description,
            "input_schema": {"type": "object", "properties": props or {}, "required": required or []},
            "output_schema": None, "side_effect": side_effect, "idempotent": False, "atomicity": "external",
            "open_world": True}


MAIL_TOOLS = [
    _tool("send_email", "Send an email now from the user's account.",
          props={"to": {"type": "string", "description": "Recipient email address"}, "body": {"type": "string"}},
          required=["to", "body"], side_effect="destructive"),
    _tool("search_contacts", "Search the user's contacts by name. Returns name and email address.",
          props={"query": {"type": "string"}}, required=["query"]),
    _tool("list_events", "List calendar events between two dates.",
          props={"start": {"type": "string"}, "end": {"type": "string"}}),
]


class FakeCore:
    """`GET /v1/mcp/tools` et `POST /v1/mcp/tools/call` scriptés ; compte les appels."""

    def __init__(self, tools=None, *, revision: int = 7) -> None:
        self.tools = list(MAIL_TOOLS if tools is None else tools)
        self.revision = revision
        self.down = False
        self.listed: list[int | None] = []
        self.calls: list[tuple[str, dict, dict]] = []
        self.call_result: object = {"ok": True, "content": [{"type": "text", "text": "fait"}], "truncated": False}

    async def external_tools(self, since_revision):
        self.listed.append(since_revision)
        if self.down:
            raise ConnectionError("Core session token is unavailable; is `jarvis core` running?")
        if since_revision == self.revision:
            return {"catalog_revision": self.revision, "unchanged": True, "plugins": [], "tools": []}
        return {"catalog_revision": self.revision, "unchanged": False,
                "plugins": [{"plugin_id": PLUGIN, "display_name": "Circuit (fake)", "enabled": True,
                             "connection_status": "connected", "auth_status": "authorized",
                             "tool_count": len(self.tools)}],
                "tools": list(self.tools)}

    async def call(self, tool_id, arguments, caller):
        self.calls.append((tool_id, arguments, caller))
        if isinstance(self.call_result, Exception):
            raise self.call_result
        return self.call_result


class Journal:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.events.append((kind, level, dict(data or {})))

    def of(self, kind):
        return [data for event_kind, _, data in self.events if event_kind == kind]


@pytest.fixture(scope="module")
def native_catalog():
    return asyncio.run(build_catalog())


def _gateway(native_catalog, core=None, *, natives=NATIVES, journal=None):
    async def load():
        return native_catalog

    return ToolsGateway(core or FakeCore(), native_servers=natives, agent="claude", catalog=load, journal=journal)


async def _session_call(gateway, name, arguments):
    from mcp.shared.memory import create_connected_server_and_client_session

    async with create_connected_server_and_client_session(build_server(tools=gateway)) as session:
        return await session.call_tool(name, arguments)


# ------------------------------------------------------------------ surface

async def test_exactly_two_strict_tools_with_their_metadata_annotations(native_catalog):
    from mcp.shared.memory import create_connected_server_and_client_session

    async with create_connected_server_and_client_session(build_server(tools=_gateway(native_catalog))) as session:
        listed = (await session.list_tools()).tools
    assert [tool.name for tool in listed] == ["list_tools", "call_tool"]
    for tool in listed:
        assert tool.inputSchema["additionalProperties"] is False
        assert "title" not in json.dumps(tool.inputSchema)
        assert tool.annotations.model_dump(exclude_none=True) == annotation_hints(SERVER_NAME, tool.name)
    list_schema, call_schema = (tool.inputSchema for tool in listed)
    assert list_schema["required"] == ["intent"]
    assert list_schema["properties"]["intent"]["maxLength"] == 500
    assert (list_schema["properties"]["limit"]["minimum"], list_schema["properties"]["limit"]["maximum"]) == (1, 60)
    assert call_schema["required"] == ["tool_id"] and call_schema["properties"]["arguments"]["type"] == "object"


async def test_context_budgets_of_the_gateway():
    server = build_server(tools=gw.ToolsGateway(FakeCore()))
    listed = await server.list_tools()
    cost = sum(model_visible_bytes(tool.name, tool.description or "", tool.inputSchema) for tool in listed)
    assert cost <= 2_500
    assert len(INSTRUCTIONS.encode("utf-8")) <= 1_200 and server.instructions == INSTRUCTIONS
    for text in (INSTRUCTIONS, *(tool.description for tool in listed)):
        assert "list_tools" in text or "call_tool" in text
    # Les trois consignes du contrat (§6.1) : rappeler list_tools, recommended appelables, call_as des natifs.
    joined = " ".join([INSTRUCTIONS, *(tool.description for tool in listed)])
    for needle in ("Rappelle list_tools", "recommended", "appelables tout de suite", "call_as", "direct_native"):
        assert needle in joined


# ------------------------------------------------------------------ list_tools

async def test_list_tools_lists_declared_natives_and_plugins_with_full_recommended(native_catalog):
    result = await _session_call(_gateway(native_catalog), "list_tools", {"intent": "envoyer un mail à Paul"})
    assert result.isError is False
    response = result.structuredContent
    assert size_of(response) <= MAX_RESPONSE_BYTES and REVISION.match(response["catalog_revision"])
    assert response["catalog_revision"].endswith(".e7") and response["notes"] == []
    top = response["recommended"][0]
    assert top["id"] == f"{PLUGIN}.send_email" and top["invocation"] == "managed_external"
    assert top["input_schema"]["required"] == ["to", "body"] and top["source"] == "Circuit (fake)"
    assert 1 <= len(response["recommended"]) <= 5
    ids = [entry["id"] for entry in response["recommended"] + response["others"]]
    # E21 : les natifs ne sont jamais des fiches d'others ; ils comptent dans native_total.
    assert all(entry["invocation"] == "managed_external" for entry in response["others"])
    declared = [t for t in native_catalog["tools"] if t["server"] in ("jarvis-display", "jarvis-console")]
    assert response["native_total"] == len(declared)  # ni jarvis-tools, ni jarvis-drive (C8)
    assert response["total"] == len(MAIL_TOOLS) == len([i for i in ids if not i.startswith("mcp__")])


async def test_a_declared_console_native_is_recommended_for_its_intent(native_catalog):
    response = await _gateway(native_catalog).list_tools("lister les boards")
    assert response["recommended"][0]["id"] == "mcp__jarvis-console__board_list"


async def test_natives_are_direct_with_call_as_and_different_intents_differ(native_catalog):
    gateway = _gateway(native_catalog)
    scene = await gateway.list_tools("qu'est-ce qui est affiché sur la scène")
    mail = await gateway.list_tools("envoyer un mail")
    top = scene["recommended"][0]
    assert top["id"] == "mcp__jarvis-display__scene_inspect" and top["invocation"] == "direct_native"
    assert top["call_as"] == top["id"]
    assert [e["id"] for e in scene["recommended"]] != [e["id"] for e in mail["recommended"]]


async def test_the_operator_server_is_never_listed_even_if_declared(native_catalog):
    response = await _gateway(native_catalog, natives=("jarvis-drive",)).list_tools("chercher un fichier drive",
                                                                                   limit=60)
    assert not any("jarvis-drive" in entry["id"] for entry in response["recommended"] + response["others"])


@pytest.mark.parametrize("intent", ["chercher un fichier dans Google Drive", "lire un document drive",
                                    "partager un fichier", "search my drive files"])
async def test_drive_intents_never_surface_the_operator_server_next_to_a_plugin(native_catalog, intent):
    """Slice 07 (ARCH §11) : même déclaré et même avec un plugin connecté, `list_tools` ne réclame jamais `jarvis-drive`."""

    response = await _gateway(native_catalog).list_tools(intent, limit=60)
    ids = [entry["id"] for entry in response["recommended"] + response["others"]]
    assert ids and not any("jarvis-drive" in tool_id for tool_id in ids)
    declared = [t for t in native_catalog["tools"] if t["server"] in ("jarvis-display", "jarvis-console")]
    assert response["native_total"] == len(declared)


async def test_five_hundred_external_tools_stay_within_the_response_budget(native_catalog):
    tools = [_tool(f"tool_{i:03d}", f"Outil {i} : mail, agenda et contacts. " + "détail " * 60,
                   props={f"p{j}": {"type": "string", "description": "texte " * 10} for j in range(8)})
             for i in range(500)]
    gateway = _gateway(native_catalog, FakeCore(tools))
    response = await gateway.list_tools("envoyer un mail", limit=60)
    assert size_of(response) <= MAX_RESPONSE_BYTES
    assert response["total"] == 500 and response["native_total"] == len(
        [t for t in native_catalog["tools"] if t["server"] in ("jarvis-display", "jarvis-console")])
    assert response["next_cursor"] is not None and len(response["recommended"]) <= 5


async def test_core_down_lists_natives_only_with_a_note_journaled_once(native_catalog):
    core, journal = FakeCore(), Journal()
    core.down = True
    gateway = _gateway(native_catalog, core, journal=journal)
    first = await gateway.list_tools("envoyer un mail")
    await gateway.list_tools("envoyer un mail")
    assert first["notes"] == ["plugins_unavailable"] and first["catalog_revision"].endswith(".e0")
    assert all(entry["id"].startswith("mcp__") for entry in first["recommended"] + first["others"])
    assert len(journal.of("tools.plugins_unavailable")) == 1
    core.down = False
    back = await gateway.list_tools("envoyer un mail")
    assert back["notes"] == [] and back["recommended"][0]["id"] == f"{PLUGIN}.send_email"
    assert len(journal.of("tools.plugins_restored")) == 1


async def test_the_external_part_is_cached_by_revision(native_catalog):
    core = FakeCore()
    gateway = _gateway(native_catalog, core)
    await gateway.list_tools("mail")
    await gateway.list_tools("agenda")
    assert core.listed == [None, 7]  # second read: « unchanged », the cache serves


async def test_a_new_revision_restarts_a_cursor_with_catalog_changed(native_catalog):
    scene_tools = [_tool(f"scene_tool_{i}", f"Outil de scène {i}") for i in range(12)]
    core = FakeCore(scene_tools)
    gateway = _gateway(native_catalog, core)
    first = await gateway.list_tools("scène", limit=3)
    assert first["next_cursor"] is not None
    core.revision = 8
    core.tools = [*scene_tools, _tool("added_tool", "Nouvel outil de scène")]
    again = await gateway.list_tools("scène", cursor=first["next_cursor"], limit=3)
    assert again["notes"] == ["catalog_changed"] and again["catalog_revision"].endswith(".e8")
    assert again["recommended"] and again["catalog_revision"] != first["catalog_revision"]


async def test_a_cursor_of_another_intent_is_a_coded_tool_error(native_catalog):
    gateway = _gateway(native_catalog)
    first = await gateway.list_tools("scène", limit=2)
    assert first["next_cursor"] is not None
    result = await _session_call(gateway, "list_tools", {"intent": "mail", "cursor": first["next_cursor"]})
    text = result.content[0].text
    assert result.isError is True and text.startswith("mcp_cursor_invalid : ")
    assert text.count("rappelle list_tools sans curseur") == 1, text  # QA : la suite était dite deux fois


async def test_the_same_call_is_byte_identical(native_catalog):
    gateway = _gateway(native_catalog)
    first = json.dumps(await gateway.list_tools("envoyer un mail"), ensure_ascii=False)
    assert json.dumps(await gateway.list_tools("envoyer un mail"), ensure_ascii=False) == first


@pytest.mark.parametrize("arguments, needle", [
    ({"intent": "x", "surprise": 1}, "Arguments inconnus"),
    ({"intent": ""}, "Argument invalide"),
    ({"intent": "x", "limit": "30"}, "Argument invalide"),
    ({"intent": "x", "limit": 61}, "Argument invalide"),
])
async def test_list_tools_refuses_bad_arguments(native_catalog, arguments, needle):
    result = await _session_call(_gateway(native_catalog), "list_tools", arguments)
    assert result.isError is True and needle in result.content[0].text


async def test_a_too_large_tool_is_listed_never_recommended_and_stays_callable(native_catalog):
    """E3 : une entrée complète > 16 Kio n'est jamais recommandée, même en tête du classement ;
    elle figure dans others avec detail « too_large » et call_tool la relaie normalement."""

    huge = _tool("export_mailbox", "Exporter toute la boîte mail vers un fichier. " + "d" * 3900,
                 props={f"field_{i}": {"type": "string", "description": "mail " + "y" * 120} for i in range(110)})
    core = FakeCore([huge, *MAIL_TOOLS])
    gateway = _gateway(native_catalog, core)
    response = await gateway.list_tools("exporter la boîte mail", limit=60)
    assert size_of(response) <= MAX_RESPONSE_BYTES
    assert f"{PLUGIN}.export_mailbox" not in [entry["id"] for entry in response["recommended"]]
    listed = [entry for entry in response["others"] if entry["id"] == f"{PLUGIN}.export_mailbox"]
    assert listed and listed[0]["detail"] == "too_large" and listed[0]["invocation"] == "managed_external"
    assert await gateway.call_tool(f"{PLUGIN}.export_mailbox", {"field_0": "x"}) == ["fait"]
    assert core.calls[-1][0] == f"{PLUGIN}.export_mailbox"


@pytest.mark.parametrize("bad", [
    {"plugin_id": PLUGIN, "name": "no_id"},                               # tool_id manquant
    {"tool_id": f"{PLUGIN}.no_name", "plugin_id": PLUGIN},                 # name manquant
    {"tool_id": f"{PLUGIN}.bad_schema", "plugin_id": PLUGIN, "name": "bad_schema", "input_schema": "nope"},
    {"tool_id": f"{PLUGIN}.bad_desc", "plugin_id": PLUGIN, "name": "bad_desc", "description": 42},
    "pas un objet",
    # QA 2 : schéma intérieur illisible — parameters_of levait AttributeError et tuait list_tools.
    {"tool_id": f"{PLUGIN}.bad_props", "plugin_id": PLUGIN, "name": "bad_props",
     "input_schema": {"type": "object", "properties": {"p": "notadict"}}},
    {"tool_id": f"{PLUGIN}.list_props", "plugin_id": PLUGIN, "name": "list_props", "input_schema": {"properties": ["x"]}},
])
async def test_a_malformed_core_tool_item_is_skipped_and_journaled(native_catalog, bad):
    core, journal = FakeCore([*MAIL_TOOLS, bad]), Journal()
    gateway = _gateway(native_catalog, core, journal=journal)
    response = await gateway.list_tools("envoyer un mail", limit=60)
    await gateway.list_tools("lire l'agenda", limit=60)  # même révision : journalisé une seule fois
    listed = [entry["id"] for entry in response["recommended"] + response["others"]]
    assert {tool["tool_id"] for tool in MAIL_TOOLS} <= set(listed) and response["native_total"] > 0
    assert response["total"] == len(MAIL_TOOLS) and response["notes"] == []
    (skipped,) = journal.of("tools.external_item_skipped")
    assert skipped["code"] == "mcp_tool_descriptor_invalid" and skipped["count"] == 1


async def test_a_malformed_plugin_item_does_not_hide_the_tools(native_catalog):
    core = FakeCore()
    original = core.external_tools

    async def with_bad_plugin(since_revision):
        payload = await original(since_revision)
        return {**payload, "plugins": [*payload["plugins"], {"display_name": "sans id"}, "x"]}

    core.external_tools = with_bad_plugin
    response = await _gateway(native_catalog, core).list_tools("envoyer un mail")
    assert response["recommended"][0]["id"] == f"{PLUGIN}.send_email"


async def test_the_ranking_index_is_built_once_per_catalog_revision(native_catalog):
    core, journal = FakeCore(), Journal()
    gateway = _gateway(native_catalog, core, journal=journal)
    first = await gateway.list_tools("envoyer un mail")
    await gateway.list_tools("lire l'agenda")
    assert len(journal.of("tools.index_built")) == 1
    core.revision = 8
    core.tools = [*MAIL_TOOLS, _tool("archive_email", "Archive an email.")]
    after = await gateway.list_tools("archiver un mail")
    built = journal.of("tools.index_built")
    assert len(built) == 2 and built[-1]["catalog_revision"] == after["catalog_revision"] != first["catalog_revision"]
    assert f"{PLUGIN}.archive_email" in [entry["id"] for entry in after["recommended"]]
    # Le cache ne change aucun octet : même réponse qu'une passerelle neuve.
    fresh = await _gateway(native_catalog, FakeCore(core.tools, revision=8)).list_tools("archiver un mail")
    assert json.dumps(after, ensure_ascii=False) == json.dumps(fresh, ensure_ascii=False)


# ------------------------------------------------------------------ call_tool

async def test_a_native_name_is_refused_with_call_as_and_never_reaches_core(native_catalog):
    core = FakeCore()
    result = await _session_call(_gateway(native_catalog, core), "call_tool",
                                 {"tool_id": "mcp__jarvis-display__scene_inspect"})
    assert result.isError is True
    text = result.content[0].text
    assert text.startswith("native_tool_call_directly : ") and "call_as = mcp__jarvis-display__scene_inspect" in text
    assert core.calls == []


async def test_an_external_call_is_relayed_with_its_caller(native_catalog):
    core = FakeCore()
    result = await _session_call(_gateway(native_catalog, core), "call_tool",
                                 {"tool_id": f"{PLUGIN}.send_email", "arguments": {"to": "p@x.fr", "body": "b"}})
    assert result.isError is False and [block.text for block in result.content] == ["fait"]
    assert core.calls == [(f"{PLUGIN}.send_email", {"to": "p@x.fr", "body": "b"},
                           {"agent": "claude", "native_servers_count": len(NATIVES)})]


@pytest.mark.parametrize("status, code, step", [
    (409, "mcp_plugin_disabled", "désactivé"),
    (409, "mcp_plugin_disconnected", "pas connecté"),
    (409, "mcp_plugin_reauthorization_required", "Reconnecter"),
    (404, "mcp_tool_unknown", "rappelle list_tools"),
    (400, "mcp_arguments_invalid", "input_schema"),
])
async def test_core_refusals_become_coded_tool_errors_with_a_next_step(native_catalog, status, code, step):
    core = FakeCore()
    core.call_result = CoreProtocolError(status, code, "refused by Core")
    result = await _session_call(_gateway(native_catalog, core), "call_tool", {"tool_id": f"{PLUGIN}.send_email"})
    assert result.isError is True
    assert result.content[0].text.startswith(f"{code} : refused by Core — ") and step in result.content[0].text


async def test_a_remote_tool_error_is_an_error_carrying_the_redacted_text(native_catalog):
    core = FakeCore()
    core.call_result = {"ok": False, "code": "mcp_remote_tool_error", "message": "the plugin tool reported an error",
                        "content": [{"type": "text", "text": "quota dépassé [secret masqué]"}], "truncated": False}
    result = await _session_call(_gateway(native_catalog, core), "call_tool", {"tool_id": f"{PLUGIN}.list_events"})
    assert result.isError is True
    assert result.content[0].text == ("mcp_remote_tool_error : the plugin tool reported an error\n"
                                      "quota dépassé [secret masqué]")


async def test_core_unreachable_on_call_is_a_coded_error(native_catalog):
    core, journal = FakeCore(), Journal()
    core.call_result = ConnectionError("no token")
    result = await _session_call(_gateway(native_catalog, core, journal=journal), "call_tool",
                                 {"tool_id": f"{PLUGIN}.list_events"})
    assert result.isError is True and result.content[0].text.startswith("core_unreachable : ")
    call = journal.of("tools.call")[-1]
    assert (call["tool_id"], call["ok"], call["code"]) == (f"{PLUGIN}.list_events", False, "core_unreachable")


async def test_a_truncated_result_says_so(native_catalog):
    core = FakeCore()
    core.call_result = {"ok": True, "content": [{"type": "text", "text": "début"}], "truncated": True}
    result = await _session_call(_gateway(native_catalog, core), "call_tool", {"tool_id": f"{PLUGIN}.list_events"})
    assert [block.text for block in result.content] == ["début", "[résultat tronqué : borne de 32 Kio atteinte]"]


@pytest.mark.parametrize("tool_id", ["Circuit.x", "a b.c", "mcp__x", ""])
async def test_call_tool_refuses_a_malformed_id_before_core(native_catalog, tool_id):
    core = FakeCore()
    result = await _session_call(_gateway(native_catalog, core), "call_tool", {"tool_id": tool_id})
    assert result.isError is True and "Argument invalide" in result.content[0].text and core.calls == []


async def test_the_journal_never_carries_the_intent_or_arguments(native_catalog):
    journal = Journal()
    gateway = _gateway(native_catalog, journal=journal)
    await gateway.list_tools("envoyer un mail à SENTINEL-PAUL")
    await gateway.call_tool(f"{PLUGIN}.send_email", {"to": "SENTINEL-PAUL"})
    assert "SENTINEL-PAUL" not in json.dumps(journal.events)
    listed = journal.of("tools.list")[-1]
    assert listed["recommended"][0] == f"{PLUGIN}.send_email" and listed["bytes"] <= MAX_RESPONSE_BYTES


# ------------------------------------------------------------------ configuration

def _target(tmp_path, **kwargs) -> ToolsGatewayTarget:
    return ToolsGatewayTarget("127.77.0.1", 17653, tmp_path / "core.token", tmp_path / "runtime", **kwargs)


def test_the_target_round_trips_through_the_environment(tmp_path):
    target = _target(tmp_path, native_servers=("jarvis-console", "jarvis-display"), agent="codex")
    env = target.env()
    assert env["JARVIS_TOOLS_NATIVE_SERVERS"] == "jarvis-console,jarvis-display" and env["JARVIS_TOOLS_AGENT"] == "codex"
    back = ToolsGatewayTarget.from_env(env)
    assert back.native_servers == target.native_servers and back.agent == "codex"
    assert back.token_file == (tmp_path / "core.token").resolve() and back.core_port == 17653


@pytest.mark.parametrize("env", [{"JARVIS_TOOLS_AGENT": "gpt"}, {"JARVIS_CORE_PORT": "0"},
                                 {"JARVIS_CORE_HOST": "8.8.8.8"}])
def test_a_bad_environment_refuses_to_start(env):
    with pytest.raises(ToolsGatewayConfigError):
        ToolsGatewayTarget.from_env(env)


def test_the_mcp_config_holds_paths_never_the_token(tmp_path):
    token = tmp_path / "core.token"
    token.write_text("SENTINEL-TOKEN-VALUE", encoding="utf-8")
    path = write_mcp_config(_target(tmp_path, native_servers=("jarvis-console",)), tmp_path / "cfg", python="py")
    document = json.loads(path.read_text(encoding="utf-8"))
    entry = document["mcpServers"]["jarvis-tools"]
    assert entry["args"] == ["-m", "jarvis", "tools-mcp"] and entry["command"] == "py"
    assert "SENTINEL-TOKEN-VALUE" not in path.read_text(encoding="utf-8")
    assert document == mcp_config(_target(tmp_path, native_servers=("jarvis-console",)), python="py")
    assert list((tmp_path / "cfg").iterdir()) == [path]


@pytest.mark.parametrize("value, expected", [
    ("C:\\Program Files\\Python\\python.exe", "'C:\\Program Files\\Python\\python.exe'"),
    ("it's", '"it\'s"'),
    ("a\nb", '"a\\nb"'),
    ("tab\there", '"tab\\there"'),
    ("del\x7f", '"del\\u007F"'),
    ("é", "'é'"),
])
def test_toml_value_prefers_literal_strings(value, expected):
    assert toml_value(value) == expected


def test_codex_overrides_declare_the_gateway(tmp_path):
    args = codex_config_overrides(_target(tmp_path), python="C:\\Py 3\\python.exe")
    assert args[0::2] == ["-c"] * 4
    assert args[1] == "mcp_servers.jarvis-tools.command='C:\\Py 3\\python.exe'"
    assert args[3] == "mcp_servers.jarvis-tools.args=['-m','jarvis','tools-mcp']"
    # Reprise QA S5 (F1, E20) : des noms de variables, jamais une valeur ni un chemin.
    assert args[5] == ("mcp_servers.jarvis-tools.env_vars=['JARVIS_CORE_HOST','JARVIS_CORE_PORT',"
                       "'JARVIS_CORE_TOKEN_FILE','JARVIS_RUNTIME_DIR','JARVIS_TOOLS_NATIVE_SERVERS','JARVIS_TOOLS_AGENT']")
    assert str(tmp_path) not in " ".join(args)
    assert args[7] == "mcp_servers.jarvis-tools.tool_timeout_sec=130"


def test_the_cli_knows_the_subcommand():
    from jarvis.app import _parser

    assert _parser().parse_args(["tools-mcp"]).command == "tools-mcp"
