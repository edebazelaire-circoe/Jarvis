"""Relais de gestion des plugins MCP du Control Center (generic-mcp-plugin-runtime, Slice 06).

Contrat : `docs/mcp/tool-contract.md` §8, `docs/mcp/plugins.md` §9, ARCH §10.1,
§14 C6, §16 E8. Ce qui doit tenir :

- chaque route relaie vers la route Core de même forme, statut et JSON rendus
  tels quels (erreurs codées comprises), avec le délai long là où Core attend
  le serveur distant ;
- toutes les méthodes de `/api/mcp/plugins*` sont gardées (Origin, Host,
  `Sec-Fetch-Site`) ; le retour OAuth ne l'est pas, mais exige un Host de
  bouclage, répond une page statique `no-store` / `no-referrer` et ne recopie
  jamais `code` ni `state` ; un retour rejoué est refusé par son code ;
- Core injoignable : 503 `core_unreachable` (journalisé une fois par panne),
  délai : 504 `core_timeout`, Core inconnu : 503 `core_unconfigured` ;
- chemins inconnus : `404 not_found`, identifiant impossible `404
  mcp_plugin_unknown` sans déranger Core, méthode absente `405` avec `Allow` ;
- la sentinelle d'un secret n'apparaît dans aucune réponse ni aucune ligne
  du journal.

Deux montages : une vraie chaîne (Control Center → `CoreSessionTransport` →
vrai Core `LocalProtocolServer`, connecteur scripté, coffre factice) et un
transport enregistreur pour la correspondance exacte des routes.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import socket

from aiohttp.test_utils import TestClient, TestServer
import pytest

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.mcp_plugins import McpErrorCode
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.core_sessions import CoreSessionTransport
from jarvis.runtime.mcp_plugin_routes import CALLBACK_TIMEOUT_S, LONG_TIMEOUT_S
from tests.fakes.fake_sealer import FakeSealer
from tests.fakes.scripted_mcp_connector import ScriptedConnector

SENTINEL = "SENTINEL-SECRET-7f3a"
TOKEN = "k" * 48
ENDPOINT = "https://plugins.example.com/mcp"
PLUGIN_ID = "plugins"


# ----------------------------------------------------------------- montages

class RecordingCore:
    """Faux `CoreSessionTransport.forward` : note chaque relais, rend la réponse posée."""

    def __init__(self, answer=(200, {"ok": "core"}), *, fail: BaseException | None = None) -> None:
        self.answer = answer
        self.fail = fail
        self.calls: list[dict] = []

    async def forward(self, method, path, *, params=None, body=None, timeout_s=None):
        self.calls.append({"method": method, "path": path, "params": params, "body": body, "timeout_s": timeout_s})
        if self.fail is not None:
            raise self.fail
        return self.answer


def _center(tmp_path: Path, sessions) -> ControlCenter:
    runtime = tmp_path / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    center = ControlCenter(runtime_root=runtime, project_root=tmp_path)
    center.sessions = sessions
    return center


def _trace(tmp_path: Path) -> list[dict]:
    path = tmp_path / "runtime" / "trace.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class Chain:
    """Vrai Control Center devant un vrai Core (connecteur scripté, coffre factice)."""

    def __init__(self, tmp_path: Path, connector: ScriptedConnector) -> None:
        self.tmp_path = tmp_path
        self.connector = connector

    async def __aenter__(self) -> "Chain":
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.core = JarvisCoreApplication(data_root=self.tmp_path / "data", sealer=FakeSealer(),
                                          connector=self.connector)
        await self.core.start()
        self.server = LocalProtocolServer(self.core, host="127.0.0.1", port=port, token=TOKEN)
        await self.server.start()
        token_file = self.tmp_path / "core.token"
        token_file.write_text(TOKEN, encoding="utf-8")
        self.sessions = CoreSessionTransport(host="127.0.0.1", port=port, token_file=token_file)
        self.center = _center(self.tmp_path, self.sessions)
        self.client = TestClient(TestServer(self.center._app))
        await self.client.start_server()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.client.close()
        await self.sessions.close()
        await self.server.stop()
        await self.core.stop()

    async def call(self, method: str, path: str, **kwargs) -> tuple[int, object, str]:
        response = await self.client.request(method, path, **kwargs)
        text = await response.text()
        try:
            body = json.loads(text)
        except ValueError:
            body = None
        return response.status, body, text


# ----------------------------------------------------------------- correspondance exacte

ROUTES = [
    # (méthode, chemin CC, corps, chemin Core, délai attendu)
    ("GET", "/api/mcp/plugins", None, "/v1/mcp/plugins", None),
    ("POST", "/api/mcp/plugins", {"endpoint": ENDPOINT}, "/v1/mcp/plugins", None),
    ("GET", f"/api/mcp/plugins/{PLUGIN_ID}", None, f"/v1/mcp/plugins/{PLUGIN_ID}", None),
    ("PATCH", f"/api/mcp/plugins/{PLUGIN_ID}", {"enabled": False}, f"/v1/mcp/plugins/{PLUGIN_ID}", None),
    ("DELETE", f"/api/mcp/plugins/{PLUGIN_ID}", None, f"/v1/mcp/plugins/{PLUGIN_ID}", LONG_TIMEOUT_S),
    ("POST", f"/api/mcp/plugins/{PLUGIN_ID}/connect", {}, f"/v1/mcp/plugins/{PLUGIN_ID}/connect", LONG_TIMEOUT_S),
    ("POST", f"/api/mcp/plugins/{PLUGIN_ID}/disconnect", None, f"/v1/mcp/plugins/{PLUGIN_ID}/disconnect",
     LONG_TIMEOUT_S),
    ("POST", f"/api/mcp/plugins/{PLUGIN_ID}/refresh", None, f"/v1/mcp/plugins/{PLUGIN_ID}/refresh", LONG_TIMEOUT_S),
    ("PUT", f"/api/mcp/plugins/{PLUGIN_ID}/credential", {"strategy": "bearer", "value": SENTINEL},
     f"/v1/mcp/plugins/{PLUGIN_ID}/credential", None),
]


@pytest.mark.parametrize("method, path, body, core_path, timeout_s", ROUTES)
async def test_each_route_relays_to_its_core_route_and_returns_status_and_body_verbatim(
        tmp_path, method, path, body, core_path, timeout_s):
    answer = (409, {"error": {"code": "mcp_plugin_disabled", "message": "enable the plugin before connecting it"},
                    "extra": [1, 2]})
    core = RecordingCore(answer)
    async with TestClient(TestServer(_center(tmp_path, core)._app)) as client:
        response = await client.request(method, path, json=body) if body is not None \
            else await client.request(method, path)
        assert response.status == 409
        assert await response.json() == answer[1]
    [call] = core.calls
    assert (call["method"], call["path"], call["timeout_s"]) == (method, core_path, timeout_s)
    assert (json.loads(call["body"]) if call["body"] else None) == body


async def test_a_success_status_and_a_created_status_are_kept(tmp_path):
    for status in (200, 201, 202):
        core = RecordingCore((status, {"status": "authorizing", "authorization_url": "https://as.example.com/a"}))
        async with TestClient(TestServer(_center(tmp_path, core)._app)) as client:
            response = await client.post(f"/api/mcp/plugins/{PLUGIN_ID}/connect", json={})
            assert response.status == status
            assert (await response.json())["authorization_url"] == "https://as.example.com/a"


async def test_core_answering_without_json_is_a_coded_error(tmp_path):
    core = RecordingCore((502, None))
    async with TestClient(TestServer(_center(tmp_path, core)._app)) as client:
        response = await client.get("/api/mcp/plugins")
        assert response.status == 502
        assert (await response.json())["error"]["code"] == "http_error"


async def test_an_oversized_body_is_refused_before_core(tmp_path):
    core = RecordingCore()
    async with TestClient(TestServer(_center(tmp_path, core)._app)) as client:
        response = await client.post("/api/mcp/plugins", data=b"x" * (256 * 1024 + 1),
                                     headers={"Content-Type": "application/json"})
        assert response.status == 400
        assert (await response.json())["error"]["code"] == "mcp_plugin_invalid"
    assert core.calls == []


async def test_an_oversized_chunked_body_without_length_is_refused_too(tmp_path):
    async def chunks():
        for _ in range(40):
            yield b"x" * 8192  # 320 Kio, sans Content-Length

    core = RecordingCore()
    async with TestClient(TestServer(_center(tmp_path, core)._app)) as client:
        response = await client.post("/api/mcp/plugins", data=chunks(), headers={"Content-Type": "application/json"})
        assert response.status == 400
        assert (await response.json())["error"]["code"] == "mcp_plugin_invalid"
    assert core.calls == []


# ----------------------------------------------------------------- garde

GUARDED = [(method, path, body) for method, path, body, _, _ in ROUTES]


@pytest.mark.parametrize("method, path, body", GUARDED)
@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example.com"},
    {"Sec-Fetch-Site": "cross-site"},
    {"Host": "evil.example.com"},  # rebinding DNS
    {"Origin": "http://127.0.0.1.evil.example.com"},
])
async def test_every_method_of_the_plugin_routes_is_guarded(tmp_path, method, path, body, headers):
    core = RecordingCore()
    async with TestClient(TestServer(_center(tmp_path, core)._app)) as client:
        response = await client.request(method, path, json=body, headers=headers)
        assert response.status == 403
        payload = await response.json()
        assert payload["code"] == "forbidden_origin" and payload["ok"] is False
    assert core.calls == []


async def test_a_same_origin_page_request_passes_the_guard(tmp_path):
    core = RecordingCore((201, {"plugin": {"plugin_id": PLUGIN_ID}}))
    async with TestClient(TestServer(_center(tmp_path, core)._app)) as client:
        origin = f"http://127.0.0.1:{client.port}"
        response = await client.post("/api/mcp/plugins", json={"endpoint": ENDPOINT},
                                      headers={"Origin": origin, "Sec-Fetch-Site": "same-origin"})
        assert response.status == 201
    assert len(core.calls) == 1


# ----------------------------------------------------------------- chemins inconnus (E8)

@pytest.mark.parametrize("method, path, status, code", [
    ("GET", f"/api/mcp/plugins/{PLUGIN_ID}/bogus", 404, "not_found"),
    ("POST", f"/api/mcp/plugins/{PLUGIN_ID}/connect/now", 404, "not_found"),
    ("GET", "/api/mcp/oauth", 404, "not_found"),
    ("GET", "/api/mcp/oauth/nope", 404, "not_found"),
    ("GET", "/api/mcp/plugins/Not_A_Plugin", 404, "mcp_plugin_unknown"),
    ("PATCH", "/api/mcp/plugins/jarvis%20x", 404, "mcp_plugin_unknown"),
    ("DELETE", "/api/mcp/plugins/" + "a" * 40, 404, "mcp_plugin_unknown"),
])
async def test_unknown_paths_under_the_plugin_prefix_are_answered_here(tmp_path, method, path, status, code):
    core = RecordingCore()
    async with TestClient(TestServer(_center(tmp_path, core)._app)) as client:
        response = await client.request(method, path, json={})
        assert response.status == status
        body = await response.json()
        assert body["error"]["code"] == code
        assert "Not_A_Plugin" not in json.dumps(body)  # l'identifiant demandé n'est jamais recopié
    assert core.calls == []


@pytest.mark.parametrize("method, path, allow", [
    ("PUT", "/api/mcp/plugins", {"GET", "HEAD", "POST"}),
    ("POST", f"/api/mcp/plugins/{PLUGIN_ID}", {"GET", "HEAD", "PATCH", "DELETE"}),
    ("GET", f"/api/mcp/plugins/{PLUGIN_ID}/connect", {"POST"}),
    ("POST", f"/api/mcp/plugins/{PLUGIN_ID}/credential", {"PUT"}),
    ("POST", "/api/mcp/oauth/callback", {"GET"}),
    ("HEAD", "/api/mcp/oauth/callback", {"GET"}),
])
async def test_a_missing_method_is_a_coded_405_with_the_real_allow(tmp_path, method, path, allow):
    core = RecordingCore()
    async with TestClient(TestServer(_center(tmp_path, core)._app)) as client:
        response = await client.request(method, path)
        assert response.status == 405
        assert set(response.headers["Allow"].replace(" ", "").split(",")) == allow
        if method != "HEAD":
            body = await response.json()
            assert body["error"]["code"] == "method_not_allowed"
            assert "read-only" not in body["error"]["message"]  # réservé au catalogue
    assert core.calls == []


# ----------------------------------------------------------------- Core absent

@pytest.mark.parametrize("method, path, body", GUARDED)
async def test_core_unreachable_is_a_coded_503_on_every_route(tmp_path, method, path, body):
    core = RecordingCore(fail=ConnectionError("Core session token is unavailable"))
    async with TestClient(TestServer(_center(tmp_path, core)._app)) as client:
        response = await client.request(method, path, json=body)
        assert response.status == 503
        assert (await response.json())["error"]["code"] == "core_unreachable"


async def test_an_outage_is_journaled_once_then_its_end(tmp_path):
    core = RecordingCore(fail=ConnectionError("down"))
    async with TestClient(TestServer(_center(tmp_path, core)._app)) as client:
        for _ in range(3):
            await client.get("/api/mcp/plugins")
        core.fail = None
        await client.get("/api/mcp/plugins")
    kinds = [row["kind"] for row in _trace(tmp_path)]
    assert kinds.count("mcp.plugin.core_unreachable") == 1 and kinds.count("mcp.plugin.core_restored") == 1


async def test_a_core_timeout_says_the_outcome_is_unknown(tmp_path):
    core = RecordingCore(fail=asyncio.TimeoutError())
    async with TestClient(TestServer(_center(tmp_path, core)._app)) as client:
        response = await client.post(f"/api/mcp/plugins/{PLUGIN_ID}/connect", json={})
        assert response.status == 504
        body = await response.json()
        assert body["error"]["code"] == "core_timeout" and "unknown" in body["error"]["message"]


async def test_a_control_center_without_core_says_so(tmp_path):
    async with TestClient(TestServer(_center(tmp_path, None)._app)) as client:
        response = await client.get("/api/mcp/plugins")
        assert response.status == 503
        assert (await response.json())["error"]["code"] == "core_unconfigured"


# ----------------------------------------------------------------- retour OAuth (hors garde)

CALLBACK_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"}


def _assert_static_page(response, text: str, *secrets: str) -> None:
    for header, value in CALLBACK_HEADERS.items():
        assert response.headers[header] == value
    assert response.content_type == "text/html"
    assert "default-src 'none'" in response.headers["Content-Security-Policy"]
    assert "<script" not in text.lower()
    for secret in secrets:
        assert secret not in text


async def test_the_callback_is_reached_by_a_cross_site_navigation_and_never_echoes_code_or_state(tmp_path):
    core = RecordingCore((200, {"plugin": {"plugin_id": PLUGIN_ID, "display_name": "Plugins"}}))
    async with TestClient(TestServer(_center(tmp_path, core)._app)) as client:
        response = await client.get("/api/mcp/oauth/callback",
                                    params={"code": "CODE-" + SENTINEL, "state": "STATE-" + SENTINEL,
                                            "iss": "https://as.example.com", "session_state": "ignored"},
                                    headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate",
                                             "Referer": "https://as.example.com/authorize"})
        text = await response.text()
        assert response.status == 200
        assert "Autorisation reçue, vous pouvez fermer cet onglet" in text
        _assert_static_page(response, text, SENTINEL, "CODE-", "STATE-")
    [call] = core.calls
    assert (call["method"], call["path"], call["timeout_s"]) == ("POST", "/v1/mcp/oauth/callback", CALLBACK_TIMEOUT_S)
    assert json.loads(call["body"]) == {"code": "CODE-" + SENTINEL, "state": "STATE-" + SENTINEL,
                                        "iss": "https://as.example.com"}
    trace = json.dumps(_trace(tmp_path))
    assert SENTINEL not in trace and "mcp.oauth.callback" in trace


@pytest.mark.parametrize("host", ["evil.example.com", "127.0.0.1.evil.example.com:17654", "[::2]:80"])
async def test_the_callback_needs_a_loopback_host(tmp_path, host):
    core = RecordingCore((200, {"plugin": {}}))
    async with TestClient(TestServer(_center(tmp_path, core)._app)) as client:
        response = await client.get("/api/mcp/oauth/callback", params={"code": "c", "state": "s"},
                                    headers={"Host": host})
        text = await response.text()
        assert response.status == 403 and "forbidden_host" in text
        _assert_static_page(response, text)
    assert core.calls == []


@pytest.mark.parametrize("params, code", [
    ({"code": "c"}, "mcp_oauth_state_invalid"),
    ({"state": "", "code": "c"}, "mcp_oauth_state_invalid"),
    ({"state": "s", "code": "c" * 4097}, "mcp_plugin_invalid"),
])
async def test_a_malformed_callback_is_refused_without_core(tmp_path, params, code):
    core = RecordingCore()
    async with TestClient(TestServer(_center(tmp_path, core)._app)) as client:
        response = await client.get("/api/mcp/oauth/callback", params=params)
        text = await response.text()
        assert response.status == 400 and f"<code>{code}</code>" in text
        _assert_static_page(response, text, "c" * 50)
    assert core.calls == []


@pytest.mark.parametrize("answer, status, code", [
    ((400, {"error": {"code": "mcp_oauth_denied", "message": "the user refused: access_denied"}}), 400,
     "mcp_oauth_denied"),
    ((400, {"error": {"code": "mcp_oauth_issuer_mismatch", "message": "iss"}}), 400, "mcp_oauth_issuer_mismatch"),
    ((500, None), 500, "http_error"),
])
async def test_a_refused_callback_shows_its_code_not_the_remote_text(tmp_path, answer, status, code):
    core = RecordingCore(answer)
    async with TestClient(TestServer(_center(tmp_path, core)._app)) as client:
        response = await client.get("/api/mcp/oauth/callback",
                                    params={"state": "s1", "error": "access_denied",
                                            "error_description": "<b>" + SENTINEL + "</b>"})
        text = await response.text()
        assert response.status == status and f"<code>{code}</code>" in text
        assert "L’autorisation n’a pas abouti." in text
        _assert_static_page(response, text, SENTINEL, "access_denied", "s1")
    assert "error_description" not in json.loads(core.calls[0]["body"])


async def test_a_callback_while_core_is_down_is_a_coded_page(tmp_path):
    core = RecordingCore(fail=ConnectionError("down"))
    async with TestClient(TestServer(_center(tmp_path, core)._app)) as client:
        response = await client.get("/api/mcp/oauth/callback", params={"state": "s", "code": "c"})
        text = await response.text()
        assert response.status == 503 and "<code>core_unreachable</code>" in text
        _assert_static_page(response, text)


# ----------------------------------------------------------------- vraie chaîne

async def test_the_full_lifecycle_through_a_real_core(tmp_path):
    async with Chain(tmp_path, ScriptedConnector("ok", "ok")) as chain:
        status, created, _ = await chain.call("POST", "/api/mcp/plugins", json={"endpoint": ENDPOINT})
        assert status == 201 and created["plugin"]["plugin_id"] == PLUGIN_ID
        assert "credential_ref" not in created["plugin"]
        status, listing, _ = await chain.call("GET", "/api/mcp/plugins")
        assert status == 200 and [p["plugin_id"] for p in listing["plugins"]] == [PLUGIN_ID]
        assert listing["vault_available"] is True
        status, connected, _ = await chain.call("POST", f"/api/mcp/plugins/{PLUGIN_ID}/connect", json={})
        assert status == 200 and connected["status"] == "connected"
        assert connected["plugin"]["connection_status"] == "connected"
        status, disabled, _ = await chain.call("PATCH", f"/api/mcp/plugins/{PLUGIN_ID}", json={"enabled": False})
        assert status == 200 and disabled["plugin"]["enabled"] is False
        status, refused, _ = await chain.call("POST", f"/api/mcp/plugins/{PLUGIN_ID}/connect", json={})
        assert (status, refused["error"]["code"]) == (409, "mcp_plugin_disabled")
        await chain.call("PATCH", f"/api/mcp/plugins/{PLUGIN_ID}", json={"enabled": True})
        status, reconnected, _ = await chain.call("POST", f"/api/mcp/plugins/{PLUGIN_ID}/connect", json={})
        assert status == 200 and reconnected["status"] == "connected"
        status, refreshed, _ = await chain.call("POST", f"/api/mcp/plugins/{PLUGIN_ID}/refresh")
        assert status == 200 and len(refreshed["plugin"]["tools"]) == 1
        status, gone, _ = await chain.call("POST", f"/api/mcp/plugins/{PLUGIN_ID}/disconnect")
        assert status == 200 and gone["plugin"]["connection_status"] == "disconnected"
        status, removed, _ = await chain.call("DELETE", f"/api/mcp/plugins/{PLUGIN_ID}")
        assert (status, removed) == (200, {"removed": PLUGIN_ID})
        status, missing, _ = await chain.call("GET", f"/api/mcp/plugins/{PLUGIN_ID}")
        assert (status, missing["error"]["code"]) == (404, "mcp_plugin_unknown")
    kinds = [(row["kind"], row["data"].get("action")) for row in _trace(tmp_path) if row["kind"] == "mcp.plugin.relayed"]
    assert [action for _, action in kinds] == ["create", "connect", "update", "connect", "update", "connect",
                                              "refresh", "disconnect", "remove"]


async def test_a_real_oauth_round_trip_then_its_replay_is_refused(tmp_path):
    async with Chain(tmp_path, ScriptedConnector("authorize")) as chain:
        await chain.call("POST", "/api/mcp/plugins", json={"endpoint": ENDPOINT})
        status, pending, _ = await chain.call("POST", f"/api/mcp/plugins/{PLUGIN_ID}/connect", json={})
        assert status == 202 and pending["status"] == "authorizing"
        state = pending["authorization_url"].split("state=")[1].split("&")[0]
        status, _, first = await chain.call("GET", "/api/mcp/oauth/callback",
                                            params={"code": "code-" + SENTINEL, "state": state,
                                                    "iss": "https://auth.example.com"},
                                            headers={"Sec-Fetch-Site": "cross-site"})
        assert status == 200 and "Autorisation reçue" in first and state not in first
        status, listing, _ = await chain.call("GET", "/api/mcp/plugins")
        plugin = listing["plugins"][0]
        assert (plugin["auth_status"], plugin["auth_strategy"]) == ("authorized", "oauth")
        status, _, replay = await chain.call("GET", "/api/mcp/oauth/callback",
                                             params={"code": "code-" + SENTINEL, "state": state},
                                             headers={"Sec-Fetch-Site": "cross-site"})
        assert status == 400 and "<code>mcp_oauth_state_invalid</code>" in replay
        assert SENTINEL not in first + replay and state not in replay


async def test_no_secret_reaches_any_response_or_journal_line(tmp_path):
    connector = ScriptedConnector(McpErrorCode.REAUTHORIZATION_REQUIRED, "ok")
    bodies: list[str] = []
    async with Chain(tmp_path, connector) as chain:
        steps = [
            ("POST", "/api/mcp/plugins", {"endpoint": ENDPOINT}),
            ("POST", f"/api/mcp/plugins/{PLUGIN_ID}/connect", {}),
            ("PUT", f"/api/mcp/plugins/{PLUGIN_ID}/credential", {"strategy": "bearer", "value": SENTINEL}),
            ("POST", f"/api/mcp/plugins/{PLUGIN_ID}/connect", {}),
            ("GET", "/api/mcp/plugins", None),
            ("GET", f"/api/mcp/plugins/{PLUGIN_ID}", None),
            ("PUT", f"/api/mcp/plugins/{PLUGIN_ID}/credential",
             {"strategy": "header", "header_name": "X-Api-Key", "value": SENTINEL + "\n"}),
            ("PUT", f"/api/mcp/plugins/{PLUGIN_ID}/credential",
             {"strategy": "header", "header_name": "X-Api-Key", "value": SENTINEL + "-2"}),
            ("GET", "/api/mcp/tools", None),
            ("POST", f"/api/mcp/plugins/{PLUGIN_ID}/disconnect", None),
            ("DELETE", f"/api/mcp/plugins/{PLUGIN_ID}", None),
        ]
        for method, path, body in steps:
            _, _, text = await chain.call(method, path, json=body) if body is not None \
                else await chain.call(method, path)
            bodies.append(text)
    assert any('"auth_strategy": "bearer"' in text or '"auth_strategy":"bearer"' in text for text in bodies)
    for text in bodies:
        assert SENTINEL not in text and "credential_ref" not in text
    trace = (tmp_path / "runtime" / "trace.jsonl").read_text(encoding="utf-8")
    assert SENTINEL not in trace
    for row in _trace(tmp_path):
        assert "value" not in row.get("data", {})
