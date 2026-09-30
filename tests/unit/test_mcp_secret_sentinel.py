"""Sentinelle de secret de bout en bout sur le faux plugin (generic-mcp-plugin-runtime, Slice 08).

Contrat : `docs/mcp/plugins.md` §3 (coffre), §8.2 (masquage), SLICE 08 « Secret
scan ». Un identifiant porteur de `SENTINEL-SECRET-7f3a` traverse tout le
parcours — création → identifiant (bearer) ou autorisation OAuth →
connexion → liste → appel → déconnexion — par les **vraies** couches :
Control Center (`/api/mcp/*`) → `CoreSessionTransport` → `LocalProtocolServer`
(`/v1/mcp/*`) → `McpPluginService` → `SdkRemoteMcpConnector` → faux serveur MCP
distant + faux AS sur 127.0.0.1 ; et côté modèle, la passerelle `jarvis-tools`
par un client MCP en mémoire. Le serveur distant renvoie aussi une erreur
d'outil qui cite le secret (`leak_error`).

Balayage : chaque corps de réponse `/api/*` et `/v1/mcp/*`, chaque résultat
rendu au modèle (`list_tools`, `call_tool`), le `--mcp-config` écrit
(`tools-mcp.json`) et les overrides Codex, tous les fichiers du runtime
(`trace.jsonl`, `errors.jsonl`) et **tous** les fichiers de la racine du test ;
la base `jarvis.sqlite3` (et son `-wal`) ne contient le secret que scellé : le
marqueur du `FakeSealer` y est, le clair jamais. Le seul endroit où le secret
circule en clair est le corps de la requête `PUT …/credential` que le
navigateur envoie — une requête, pas une réponse.

Déterministe : ports éphémères liés par le test, aucun réseau hors bouclage,
aucun modèle. Un masquage ou un scellement retiré fait échouer ce test (mutation
vérifiée : `slices/08-release-qa-and-documentation/EVIDENCE.md`).
"""

from __future__ import annotations

import json
from pathlib import Path
import socket
from typing import Any

from aiohttp.test_utils import TestClient, TestServer
import pytest

pytest.importorskip("mcp")

from jarvis.adapters.remote_mcp import SdkRemoteMcpConnector, Timeouts  # noqa: E402
from jarvis.core.v2_app import JarvisCoreApplication  # noqa: E402
from jarvis.protocol.client import LocalCoreClient  # noqa: E402
from jarvis.protocol.server import LocalProtocolServer  # noqa: E402
from jarvis.runtime.control_center import ControlCenter  # noqa: E402
from jarvis.runtime.core_sessions import CoreSessionTransport  # noqa: E402
from jarvis.runtime.journal import RuntimeJournal  # noqa: E402
from jarvis.runtime.tools_gateway_mcp import (  # noqa: E402
    ToolsGateway, ToolsGatewayTarget, build_server, codex_config_overrides, write_mcp_config,
)
from tests.fakes.fake_remote_mcp import SENTINEL, FakeConfig, running_fakes  # noqa: E402
from tests.fakes.fake_sealer import MARKER, FakeSealer  # noqa: E402

TOKEN = "s" * 48
# Chaîne seulement (aucun socket) : l'AS la recopie dans la redirection que le test suit à la main.
REDIRECT = "http://127.0.0.1:18999/api/mcp/oauth/callback"
FAST = Timeouts(connect_s=2.0, read_s=5.0, handshake_s=2.0)
NEEDLE = SENTINEL.encode("utf-8")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Scan:
    """Tout ce qui a été rendu ou écrit, étiqueté pour qu'un échec nomme l'endroit de la fuite."""

    def __init__(self) -> None:
        self.texts: list[tuple[str, str]] = []

    def add(self, label: str, value: Any) -> Any:
        self.texts.append((label, value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)))
        return value

    def leaks(self) -> list[str]:
        return [label for label, text in self.texts if SENTINEL in text]


def _files_with_needle(root: Path, *, skip_db: bool) -> list[str]:
    found = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if skip_db and path.name.startswith("jarvis.sqlite3"):
            continue
        if NEEDLE in path.read_bytes():
            found.append(str(path.relative_to(root)))
    return found


def _db_bytes(root: Path) -> bytes:
    return b"".join(path.read_bytes() for path in sorted(root.rglob("jarvis.sqlite3*")) if path.is_file())


async def _api(client: TestClient, scan: Scan, method: str, path: str, **kwargs) -> tuple[int, Any]:
    response = await client.request(method, path, **kwargs)
    text = await response.text()
    scan.add(f"{method} {path} -> {response.status}", text)
    try:
        return response.status, json.loads(text)
    except ValueError:
        return response.status, text


@pytest.mark.parametrize("strategy", ["bearer", "oauth"])
async def test_a_sentinel_credential_never_leaves_the_vault_in_clear(tmp_path, strategy):
    scan = Scan()
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    config = FakeConfig(auth=strategy)
    async with running_fakes(config) as world:
        port = _free_port()
        core = JarvisCoreApplication(
            data_root=tmp_path / "data", sealer=FakeSealer(), mcp_allow_loopback_http=True,
            connector=SdkRemoteMcpConnector(redirect_uri=REDIRECT, allow_loopback_http=True, timeouts=FAST),
            diagnostics=RuntimeJournal(runtime))
        await core.start()
        server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
        await server.start()
        token_file = tmp_path / "core.token"
        token_file.write_text(TOKEN, encoding="utf-8")
        sessions = CoreSessionTransport(host="127.0.0.1", port=port, token_file=token_file)
        center = ControlCenter(runtime_root=runtime, project_root=tmp_path)
        center.sessions = sessions
        client = TestClient(TestServer(center._app))
        await client.start_server()
        admin = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
        target = ToolsGatewayTarget("127.0.0.1", port, token_file, runtime,
                                    native_servers=("jarvis-console",), agent="claude")
        gateway = ToolsGateway.from_target(target, journal=RuntimeJournal(runtime))
        try:
            # 1. Création.
            status, created = await _api(client, scan, "POST", "/api/mcp/plugins",
                                         json={"endpoint": world.rs_base + "/mcp"})
            assert status == 201, created
            pid = created["plugin"]["plugin_id"]
            # 2-3. Identifiant puis connexion.
            if strategy == "bearer":
                status, stored = await _api(client, scan, "PUT", f"/api/mcp/plugins/{pid}/credential",
                                            json={"strategy": "bearer", "value": config.static_value})
                assert status == 200, stored
                status, connected = await _api(client, scan, "POST", f"/api/mcp/plugins/{pid}/connect", json={})
                assert status == 200 and connected["plugin"]["connection_status"] == "connected", connected
            else:
                status, started = await _api(client, scan, "POST", f"/api/mcp/plugins/{pid}/connect", json={})
                assert status == 202 and started["status"] == "authorizing", started
                callback = await world.approve(started["authorization_url"])
                status, page = await _api(client, scan, "GET", "/api/mcp/oauth/callback", params=callback)
                assert status == 200, page
            # 4. Liste, par chaque surface.
            for method, path in (("GET", "/api/mcp/plugins"), ("GET", f"/api/mcp/plugins/{pid}"),
                                 ("POST", f"/api/mcp/plugins/{pid}/refresh"), ("GET", "/api/mcp/tools"),
                                 ("GET", f"/api/mcp/tools/{pid}/search_mail")):
                status, body = await _api(client, scan, method, path)
                assert status == 200, (path, body)
            plugin = (await _api(client, scan, "GET", f"/api/mcp/plugins/{pid}"))[1]["plugin"]
            assert (plugin["connection_status"], plugin["auth_status"]) == ("connected", "authorized")
            scan.add("/v1/mcp/plugins", await admin.list_mcp_plugins())
            scan.add("/v1/mcp/plugins/{id}", await admin.get_mcp_plugin(pid))
            listing = scan.add("/v1/mcp/tools", await admin.list_mcp_tools())
            assert f"{pid}.search_mail" in [item["tool_id"] for item in listing["tools"]]
            # Le secret est scellé en base pendant qu'il sert : marqueur présent, clair absent.
            sealed = _db_bytes(tmp_path)
            assert MARKER in sealed and NEEDLE not in sealed
            # 5. Appels : Core direct, puis le modèle par la passerelle (dont l'erreur distante qui cite le secret).
            scan.add("/v1/mcp/tools/call ok", await admin.call_mcp_tool(
                f"{pid}.search_mail", {"q": "Paul"}, caller={"agent": "claude"}))
            leaked = scan.add("/v1/mcp/tools/call leak", await admin.call_mcp_tool(
                f"{pid}.leak_error", {}, caller={"agent": "claude"}))
            assert (leaked["ok"], leaked["code"]) == (False, "mcp_remote_tool_error")
            from mcp.shared.memory import create_connected_server_and_client_session

            async with create_connected_server_and_client_session(build_server(target, tools=gateway)) as model:
                for name, arguments in (("list_tools", {"intent": "chercher un mail"}),
                                        ("call_tool", {"tool_id": f"{pid}.search_mail", "arguments": {"q": "x"}}),
                                        ("call_tool", {"tool_id": f"{pid}.leak_error", "arguments": {}})):
                    result = await model.call_tool(name, arguments)
                    scan.add(f"model {name}", result.model_dump(mode="json"))
            # Ce que le cerveau reçoit au lancement : fichier --mcp-config et argv Codex.
            config_path = write_mcp_config(target, tmp_path / "configs")
            assert config_path.name == "tools-mcp.json"
            scan.add("codex argv", " ".join(codex_config_overrides(target)))
            # 6. Déconnexion : l'identifiant est oublié.
            status, gone = await _api(client, scan, "POST", f"/api/mcp/plugins/{pid}/disconnect")
            assert status == 200 and gone["plugin"]["connection_status"] == "disconnected", gone
            status, deleted = await _api(client, scan, "DELETE", f"/api/mcp/plugins/{pid}")
            assert status == 200, deleted
        finally:
            await gateway.close()
            await admin.close()
            await client.close()
            await sessions.close()
            await server.stop()
            await core.stop()
    # Le secret a bien circulé (sinon le test ne prouverait rien) : le serveur distant l'a reçu.
    assert any(NEEDLE in seen.body or SENTINEL in json.dumps(seen.headers) for seen in world.requests)
    assert scan.leaks() == []
    assert (runtime / "trace.jsonl").exists()
    assert _files_with_needle(tmp_path, skip_db=True) == []
    assert NEEDLE not in _db_bytes(tmp_path)
