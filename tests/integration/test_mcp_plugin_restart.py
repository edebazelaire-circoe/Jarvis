"""Persistance des plugins MCP au redémarrage de Core et du Control Center (generic-mcp-plugin-runtime, Slice 08).

Contrat : `docs/mcp/plugins.md` §2.2 (démarrage : `connecting`/`connected` ⇒
`disconnected`, reconnexion non interactive), ARCH §16 E12, E15 ; SLICE 08
« Restart persistence ». Pile réelle : `JarvisCoreApplication` +
`LocalProtocolServer` + `SdkRemoteMcpConnector`, quatre faux serveurs distants
(faux AS compris) sur 127.0.0.1, coffre `FakeSealer` (déterministe : une
nouvelle instance ouvre les blobs de la précédente, comme DPAPI CurrentUser).

Première vie de Core : cinq plugins
- `oauth` autorisé (jeton valide, sans rafraîchissement) ;
- `expiring` autorisé, jeton d'une seconde, sans rafraîchissement ;
- `bearer` autorisé ;
- `open` sans authentification ;
- `paused` bearer autorisé puis **désactivé**.

Seconde vie (même `data_root`, aucun Control Center, aucun navigateur) :
plugins, drapeaux `enabled` et blobs scellés identiques octet pour octet ;
`oauth`, `bearer`, `open` reconnectés seuls sans nouvelle autorisation ;
`expiring` ⇒ `expired` sans **aucune** requête réseau ; `paused` reste désactivé
et ne touche pas son serveur. Puis un Control Center démarré, arrêté et
redémarré devant ce Core ne change rien aux plugins ni aux serveurs distants.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
import json
from pathlib import Path
import socket
import sqlite3
import time

from aiohttp.test_utils import TestClient, TestServer
import pytest

pytest.importorskip("mcp")

from jarvis.adapters.remote_mcp import SdkRemoteMcpConnector, Timeouts  # noqa: E402
from jarvis.core.mcp_plugin_service import PLUGIN_EXPIRED_AT_BOOT, PLUGINS_BOOT_RECONNECT  # noqa: E402
from jarvis.core.v2_app import JarvisCoreApplication  # noqa: E402
from jarvis.protocol.client import LocalCoreClient  # noqa: E402
from jarvis.protocol.server import LocalProtocolServer  # noqa: E402
from jarvis.runtime.control_center import ControlCenter  # noqa: E402
from jarvis.runtime.core_sessions import CoreSessionTransport  # noqa: E402
from jarvis.runtime.journal import RuntimeJournal  # noqa: E402
from tests.fakes.fake_remote_mcp import SENTINEL, FakeConfig, running_fakes  # noqa: E402
from tests.fakes.fake_sealer import FakeSealer  # noqa: E402

TOKEN = "r" * 48
# Chaîne seulement (aucun socket) : l'AS la recopie dans la redirection que le test suit à la main.
REDIRECT = "http://127.0.0.1:18998/api/mcp/oauth/callback"
FAST = Timeouts(connect_s=2.0, read_s=5.0, handshake_s=2.0)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class CoreLife:
    """Une vie de Core : application, serveur de protocole, client d'administration."""

    def __init__(self, root: Path, port: int) -> None:
        self.root = root
        self.port = port

    async def __aenter__(self) -> "CoreLife":
        self.core = JarvisCoreApplication(
            data_root=self.root / "data", sealer=FakeSealer(), mcp_allow_loopback_http=True,
            connector=SdkRemoteMcpConnector(redirect_uri=REDIRECT, allow_loopback_http=True, timeouts=FAST),
            diagnostics=RuntimeJournal(self.root / "runtime"))
        await self.core.start()
        self.server = LocalProtocolServer(self.core, host="127.0.0.1", port=self.port, token=TOKEN)
        await self.server.start()
        self.client = LocalCoreClient(host="127.0.0.1", port=self.port, token=TOKEN)
        return self

    async def __aexit__(self, *exc) -> None:
        await self.client.close()
        await self.server.stop()
        await self.core.stop()

    async def plugin(self, pid: str) -> dict:
        return (await self.client.get_mcp_plugin(pid))["plugin"]

    async def wait_connected(self, pids: list[str], timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            states = [(await self.plugin(pid))["connection_status"] for pid in pids]
            if all(state == "connected" for state in states):
                return
            await asyncio.sleep(0.05)
        raise AssertionError(f"not reconnected in {timeout}s: {dict(zip(pids, states))}")


def _db_rows(root: Path) -> tuple[dict[str, tuple], dict[str, bytes]]:
    """(plugin_id -> (enabled, credential_ref)), (credential_ref -> blob) lus hors Core, base fermée."""

    connection = sqlite3.connect(root / "data" / "state" / "jarvis.sqlite3")
    try:
        plugins = {pid: (enabled, json.loads(data).get("credential_ref"))
                   for pid, enabled, data in connection.execute("SELECT plugin_id, enabled, data FROM mcp_plugins")}
        blobs = {ref: bytes(blob) for ref, blob in connection.execute(
            "SELECT credential_ref, blob FROM mcp_credentials")}
    finally:
        connection.close()
    return plugins, blobs


def _events(root: Path, kind: str) -> list[dict]:
    lines = (root / "runtime" / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    return [row.get("data", {}) for row in map(json.loads, filter(str.strip, lines)) if row.get("kind") == kind]


def _authorizations(world) -> int:
    return len([seen for seen in world.seen("as") if seen.path == "/authorize"])


async def _oauth(life: CoreLife, world, pid: str) -> None:
    started = await life.client.connect_mcp_plugin(pid)
    assert started["status"] == "authorizing"
    callback = await world.approve(started["authorization_url"])
    done = await life.client.complete_mcp_oauth(state=callback["state"], code=callback["code"], iss=callback["iss"])
    assert done["plugin"]["connection_status"] == "connected"


async def test_core_restart_keeps_plugins_and_reconnects_only_what_it_may_without_ui(tmp_path):
    port = _free_port()
    async with AsyncExitStack() as fakes:
        worlds = {
            "oauth": await fakes.enter_async_context(running_fakes(FakeConfig(auth="oauth"))),
            "expiring": await fakes.enter_async_context(running_fakes(FakeConfig(auth="oauth", expires_in=1))),
            "bearer": await fakes.enter_async_context(running_fakes(FakeConfig(auth="bearer"))),
            "open": await fakes.enter_async_context(running_fakes(FakeConfig())),
            "paused": await fakes.enter_async_context(running_fakes(FakeConfig(auth="bearer"))),
        }
        ids: dict[str, str] = {}
        # ---------------------------------------------------------------- première vie
        async with CoreLife(tmp_path, port) as life:
            for role, world in worlds.items():
                ids[role] = (await life.client.create_mcp_plugin(world.rs_base + "/mcp",
                                                                 display_name=role))["plugin"]["plugin_id"]
            assert len(set(ids.values())) == 5
            await _oauth(life, worlds["expiring"], ids["expiring"])
            await _oauth(life, worlds["oauth"], ids["oauth"])
            for role in ("bearer", "paused"):
                await life.client.set_mcp_plugin_credential(ids[role], strategy="bearer",
                                                            value=worlds[role].config.static_value)
            for role in ("bearer", "open", "paused"):
                assert (await life.client.connect_mcp_plugin(ids[role]))["status"] == "connected"
            await life.client.update_mcp_plugin(ids["paused"], enabled=False)
            before = {pid: await life.plugin(pid) for pid in ids.values()}
        rows_before, blobs_before = _db_rows(tmp_path)
        assert len(blobs_before) == 4  # oauth, expiring, bearer, paused ; `open` n'en a pas
        assert all(SENTINEL.encode() not in blob for blob in blobs_before.values())
        await asyncio.sleep(1.1)  # le jeton d'`expiring` (1 s, sans rafraîchissement) est échu
        requests = {role: len(world.requests) for role, world in worlds.items()}
        authorizations = {role: _authorizations(world) for role, world in worlds.items()}

        # ---------------------------------------------------------------- seconde vie, sans UI
        async with CoreLife(tmp_path, port) as life:
            await life.wait_connected([ids["oauth"], ids["bearer"], ids["open"]])
            after = {pid: await life.plugin(pid) for pid in ids.values()}
            expired, paused = after[ids["expiring"]], after[ids["paused"]]
            assert (expired["auth_status"], expired["connection_status"], expired["enabled"]) == (
                "expired", "disconnected", True)
            assert (paused["enabled"], paused["connection_status"], paused["auth_status"]) == (
                False, "disconnected", "authorized")
            for role in ("oauth", "bearer"):
                assert after[ids[role]]["auth_status"] == "authorized"
            # Même registre : identité, point d'accès, stratégie, outils, drapeau.
            for pid, old in before.items():
                new = after[pid]
                for key in ("plugin_id", "endpoint", "display_name", "enabled", "auth_strategy", "tools"):
                    assert new.get(key) == old.get(key), (pid, key)
            # Les identifiants rechargés servent : un appel passe, sans nouvelle autorisation.
            outcome = await life.client.call_mcp_tool(f"{ids['oauth']}.search_mail", {"q": "x"},
                                                      caller={"agent": "claude"})
            assert outcome["ok"] is True
            await asyncio.sleep(0.3)
            # `expiring` et `paused` : aucune requête ; personne n'a rouvert d'autorisation.
            assert len(worlds["expiring"].requests) == requests["expiring"]
            assert len(worlds["paused"].requests) == requests["paused"]
            assert {role: _authorizations(world) for role, world in worlds.items()} == authorizations
            assert [event["plugin_id"] for event in _events(tmp_path, PLUGIN_EXPIRED_AT_BOOT)] == [ids["expiring"]]
            assert sorted(_events(tmp_path, PLUGINS_BOOT_RECONNECT)[-1]["plugin_ids"]) == sorted(
                [ids["oauth"], ids["bearer"], ids["open"]])

            # ------------------------------------------------------------ Control Center redémarré
            token_file = tmp_path / "core.token"
            token_file.write_text(TOKEN, encoding="utf-8")
            snapshots = []
            core_requests = {role: len(world.requests) for role, world in worlds.items()}
            for run in range(2):
                runtime = tmp_path / f"cc-runtime-{run}"
                runtime.mkdir()
                sessions = CoreSessionTransport(host="127.0.0.1", port=port, token_file=token_file)
                center = ControlCenter(runtime_root=runtime, project_root=tmp_path)
                center.sessions = sessions
                try:
                    async with TestClient(TestServer(center._app)) as client:
                        response = await client.get("/api/mcp/plugins")
                        assert response.status == 200
                        snapshots.append((await response.json())["plugins"])
                        catalog = await (await client.get("/api/mcp/tools")).json()
                        assert f"{ids['oauth']}" in json.dumps(catalog)
                finally:
                    await sessions.close()
            assert snapshots[0] == snapshots[1]
            assert {pid: await life.plugin(pid) for pid in ids.values()} == after
            assert {role: len(world.requests) for role, world in worlds.items()} == core_requests
        rows_after, blobs_after = _db_rows(tmp_path)
    # Registre et blobs scellés identiques après les deux vies.
    assert rows_after == rows_before
    assert blobs_after == blobs_before
    assert {pid: bool(enabled) for pid, (enabled, _) in rows_after.items()} == {
        pid: pid != ids["paused"] for pid in ids.values()}
