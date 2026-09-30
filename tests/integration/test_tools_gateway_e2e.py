"""Passerelle `jarvis-tools` de bout en bout (plugins MCP, Slice 04 ; `docs/mcp/plugins.md` §6-§7).

Client MCP en mémoire → vrai serveur `jarvis-tools` (vrai catalogue natif) →
vrais `LocalProtocolServer` / `JarvisCoreApplication` / `McpPluginService` →
vrai `SdkRemoteMcpConnector` → faux serveur MCP distant + faux AS OAuth sur
127.0.0.1 (jetons porteurs de la sentinelle). Le jeton de Core est relu dans
un fichier, comme en production.

Scénario enregistré (`scenario`) : list → call → re-list pour un prérequis →
call, puis un outil recommandé à la première recherche appelé sans nouvelle
recherche, une erreur distante masquée, et une mutation de la liste d'outils
distante visible au `list_tools` suivant (nouvelle `catalog_revision`). La
transcription sert aussi de preuve (`slices/04-.../EVIDENCE.md`).
"""

from __future__ import annotations

import asyncio
import json
import socket
import time
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")

from jarvis.adapters.remote_mcp import SdkRemoteMcpConnector, Timeouts  # noqa: E402
from jarvis.core.v2_app import JarvisCoreApplication  # noqa: E402
from jarvis.domain.tool_discovery import MAX_RESPONSE_BYTES, size_of  # noqa: E402
from jarvis.protocol.client import LocalCoreClient  # noqa: E402
from jarvis.protocol.server import LocalProtocolServer  # noqa: E402
from jarvis.runtime.journal import RuntimeJournal  # noqa: E402
from jarvis.runtime.tools_gateway_mcp import ToolsGateway, ToolsGatewayTarget, build_server  # noqa: E402
from tests.fakes.fake_remote_mcp import SENTINEL, FakeConfig, running_fakes, tool  # noqa: E402
from tests.fakes.fake_sealer import FakeSealer  # noqa: E402

TOKEN = "t" * 48
REDIRECT = "http://127.0.0.1:17654/api/mcp/oauth/callback"
FAST = Timeouts(connect_s=2.0, read_s=5.0, handshake_s=2.0)
NATIVES = ("jarvis-console", "jarvis-display")

MAIL_TOOLS = [
    tool("search_mail", description="Search the user's mailbox by sender or words; returns message ids and snippets.",
         read_only=True, schema={"type": "object", "properties": {"query": {"type": "string"}},
                                 "required": ["query"]}),
    tool("send_mail", description="Send an email to a recipient email address.",
         schema={"type": "object", "properties": {"to": {"type": "string", "description": "Recipient email address"},
                                                  "body": {"type": "string"}},
                 "required": ["to", "body"], "additionalProperties": False}),
    tool("search_contacts", description="Search the user's contacts by name; returns their email address.",
         read_only=True, schema={"type": "object", "properties": {"name": {"type": "string"}},
                                 "required": ["name"]}),
    tool("leak_error", description="Diagnostic tool that fails with a secret-looking upstream text.", read_only=True),
]


async def _wait(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached in time")


class Transcript:
    """Ce que le client MCP a envoyé et reçu, tel quel (le « cerveau » scripté)."""

    def __init__(self, session) -> None:
        self.session = session
        self.steps: list[dict[str, Any]] = []

    async def call(self, name: str, arguments: dict[str, Any]) -> Any:
        started = time.monotonic()
        result = await self.session.call_tool(name, arguments)
        step: dict[str, Any] = {"tool": f"mcp__jarvis-tools__{name}", "arguments": arguments,
                                "is_error": bool(result.isError),
                                "duration_ms": round((time.monotonic() - started) * 1000)}
        if result.structuredContent is not None:
            step["structured"] = result.structuredContent
            step["bytes"] = size_of(result.structuredContent)
        else:
            step["text"] = [block.text for block in result.content]
            step["bytes"] = sum(len(block.text.encode("utf-8")) for block in result.content)
        self.steps.append(step)
        return result


async def scenario(tmp_path: Path) -> dict[str, Any]:
    """Pile complète + scénario scripté ; rend la transcription, les journaux et les faits observés."""

    runtime = tmp_path / "runtime"
    async with running_fakes(FakeConfig(auth="oauth", tools=[dict(item) for item in MAIL_TOOLS])) as world:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        core_journal = RuntimeJournal(runtime)
        connector = SdkRemoteMcpConnector(redirect_uri=REDIRECT, allow_loopback_http=True, timeouts=FAST)
        core = JarvisCoreApplication(data_root=tmp_path, sealer=FakeSealer(), connector=connector,
                                     mcp_allow_loopback_http=True, diagnostics=core_journal)
        await core.start()
        server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
        await server.start()
        token_file = tmp_path / "core.token"
        token_file.write_text(TOKEN, encoding="utf-8")
        admin = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
        target = ToolsGatewayTarget("127.0.0.1", port, token_file, runtime, native_servers=NATIVES, agent="claude")
        gateway = ToolsGateway.from_target(target, journal=RuntimeJournal(runtime))
        facts: dict[str, Any] = {}
        try:
            pid = (await admin.create_mcp_plugin(world.rs_base + "/mcp"))["plugin"]["plugin_id"]
            started = await admin.connect_mcp_plugin(pid)
            callback = await world.approve(started["authorization_url"])
            await admin.complete_mcp_oauth(state=callback["state"], code=callback["code"], iss=callback["iss"])
            facts["plugin_id"] = pid
            from mcp.shared.memory import create_connected_server_and_client_session

            async with create_connected_server_and_client_session(build_server(target, tools=gateway)) as session:
                brain = Transcript(session)
                # 1. Découverte pour le besoin exprimé.
                first = await brain.call("list_tools", {"intent": "répondre au dernier mail de Paul"})
                # 2. Appel d'un recommandé, sans seconde recherche.
                await brain.call("call_tool", {"tool_id": f"{pid}.search_mail", "arguments": {"query": "Paul"}})
                # 3. Prérequis découvert : l'adresse de Paul ⇒ nouvelle recherche.
                await brain.call("list_tools", {"intent": "trouver l'adresse email de Paul"})
                await brain.call("call_tool", {"tool_id": f"{pid}.search_contacts", "arguments": {"name": "Paul"}})
                # 4. `send_mail` était recommandé au pas 1 : appel direct avec son schéma.
                await brain.call("call_tool", {"tool_id": f"{pid}.send_mail",
                                               "arguments": {"to": "paul@example.com", "body": "Bien reçu."}})
                # 5. Erreur distante porteuse de secrets : masquée.
                await brain.call("call_tool", {"tool_id": f"{pid}.leak_error", "arguments": {}})
                # 6. Mutation de la liste distante ⇒ nouvelle révision au list_tools suivant.
                before = first.structuredContent["catalog_revision"]
                world.config.tools.append(tool("archive_mail", description="Archive an email message by id.",
                                               schema={"type": "object", "properties": {"id": {"type": "string"}},
                                                       "required": ["id"]}))
                assert await world.notify_tools_changed() >= 1

                async def changed():
                    listing = await admin.list_mcp_tools()
                    return f"{pid}.archive_mail" in [item["tool_id"] for item in listing["tools"]]

                await _wait(changed)
                after = await brain.call("list_tools", {"intent": "archiver un mail"})
                facts["revisions"] = [before, after.structuredContent["catalog_revision"]]
            facts["remote_calls"] = [json.loads(item.body.decode("utf-8") or "{}").get("params", {}).get("name")
                                     for item in world.seen("rs") if item.method == "POST" and item.body
                                     and b'"tools/call"' in item.body]
        finally:
            await gateway.close()
            await admin.close()
            await server.stop()
            await core.stop()
    trace = runtime / "trace.jsonl"
    return {"steps": brain.steps, "facts": facts,
            "journal": [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines() if line.strip()]}


async def test_list_call_relist_call_over_the_real_core_and_remote_server(tmp_path):
    record = await scenario(tmp_path)
    steps, facts, pid = record["steps"], record["facts"], record["facts"]["plugin_id"]
    assert [step["tool"].rsplit("__", 1)[1] for step in steps] == [
        "list_tools", "call_tool", "list_tools", "call_tool", "call_tool", "call_tool", "list_tools"]
    first, relist, last = steps[0]["structured"], steps[2]["structured"], steps[6]["structured"]
    for listing in (first, relist, last):
        assert size_of(listing) <= MAX_RESPONSE_BYTES and listing["notes"] == []
    recommended = [entry["id"] for entry in first["recommended"]]
    assert f"{pid}.search_mail" in recommended and f"{pid}.send_mail" in recommended
    assert relist["recommended"][0]["id"] == f"{pid}.search_contacts"
    assert [step["is_error"] for step in steps[1:6]] == [False, False, False, False, True]
    assert steps[4]["text"][0].startswith("send_mail ok")
    leaked = steps[5]["text"][0]
    assert leaked.startswith("mcp_remote_tool_error : ") and "[secret masqué]" in leaked
    # La mutation est visible au list_tools suivant.
    before, after = facts["revisions"]
    assert before != after and before.split(".")[0] == after.split(".")[0]
    assert last["recommended"][0]["id"] == f"{pid}.archive_mail"
    # Aucun appel redondant côté serveur distant : exactement les quatre appels du scénario.
    assert facts["remote_calls"] == ["search_mail", "search_contacts", "send_mail", "leak_error"]
    # Aucun secret nulle part : transcription, journaux de Core et de la passerelle.
    blob = json.dumps(record, ensure_ascii=False)
    assert SENTINEL not in blob and TOKEN not in blob
    kinds = [row["kind"] for row in record["journal"]]
    assert kinds.count("tools.list") == 3 and kinds.count("tools.call") == 4
    assert kinds.count("mcp.plugin.tool_called") == 4
