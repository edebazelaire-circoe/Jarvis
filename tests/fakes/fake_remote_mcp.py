"""Faux serveur MCP distant + faux serveur d'autorisation OAuth (Slice 03 ; ARCH §13, SLICE 03 contract).

Deux applications Starlette servies par uvicorn **dans la boucle du test**, sur
`127.0.0.1` et des ports éphémères (sockets liés par le test : aucune course),
arrêtées proprement par `running_fakes()` — aucun processus ni thread ne
survit. Deux origines distinctes (RS et AS) : un en-tête qui ne doit aller
qu'au plugin est vérifiable côté AS.

Le serveur MCP est le vrai serveur bas niveau du SDK (`mcp.server.lowlevel`)
derrière `StreamableHTTPSessionManager` : liste d'outils mutable, notification
`tools/list_changed`, 250 outils, schéma énorme, erreur d'outil au texte
« secret ». Le serveur d'autorisation fait PRM, métadonnées (avec ou sans
`authorization_response_iss_parameter_supported`), enregistrement dynamique
(acceptant ou refusant une subvention `refresh_token`), PKCE S256 vérifié,
jetons avec ou sans rafraîchissement, expiration courte, `403
insufficient_scope`, révocation. Chemins cassés du serveur MCP : `/crash` (500),
`/slow` (ne répond pas), `/malformed` (JSON-RPC illisible), `/huge` (> 4 Mio),
`/redirect` (redirection vers l'autre origine), `/legacy` (405 au POST).

Utilisé avec le drapeau de développement `allow_loopback_http=True` ; ne
touche jamais le réseau hors du bouclage. Jamais importé hors des tests.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import hashlib
import itertools
import json
import secrets
import socket
import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import sse_starlette.sse
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route
import uvicorn

SENTINEL = "SENTINEL-SECRET-7f3a"
DEFAULT_SCOPE = "mail"


def tool(name: str, *, description: str = "", read_only: bool | None = None, schema: dict | None = None,
         **extra: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {"name": name, "description": description or f"Outil {name}",
                           "inputSchema": schema or {"type": "object", "properties": {"q": {"type": "string"}}}}
    if read_only is not None:
        raw["annotations"] = {"readOnlyHint": read_only}
    raw.update(extra)
    return raw


DEFAULT_TOOLS = (
    tool("search_mail", description="Chercher des mails", read_only=True),
    tool("send_mail", description="Envoyer un mail"),
    tool("leak_error", description="Échoue avec un texte qui ressemble à un secret", read_only=True),
)


@dataclass
class FakeConfig:
    """Comportement réglable ; modifiable pendant le test."""

    auth: str = "none"  # none | oauth | bearer | header
    static_header: str = "X-Api-Key"
    static_value: str = f"{SENTINEL}-static"
    iss_supported: bool = True
    wrong_iss: bool = False
    deny: bool = False
    grants: tuple[str, ...] = ("authorization_code",)
    accept_refresh_grant: bool = True
    issue_refresh: bool = False
    expires_in: int | None = 3600
    list_scope: str | None = None  # scope a token needs for tools/list (step-up)
    revocation: bool = True
    #: Secondes avant que `/token` réponde : un échange de code lent, après le consentement.
    token_delay_s: float = 0.0
    tools: list[dict[str, Any]] = field(default_factory=lambda: [dict(item) for item in DEFAULT_TOOLS])


@dataclass
class Seen:
    method: str
    origin: str
    path: str
    headers: dict[str, str]
    body: bytes


class FakeWorld:
    """État partagé des deux serveurs : jetons, codes, clients, requêtes vues."""

    def __init__(self, config: FakeConfig) -> None:
        self.config = config
        self.rs_base = ""
        self.as_base = ""
        self.requests: list[Seen] = []
        self.clients: dict[str, dict[str, Any]] = {}
        self.registrations: list[dict[str, Any]] = []
        self.codes: dict[str, dict[str, Any]] = {}
        self.tokens: dict[str, dict[str, Any]] = {}
        self.refresh_tokens: dict[str, str] = {}
        self.revoked: list[str] = []
        self.sessions: list[Any] = []
        self.list_calls = 0
        self._ids = itertools.count(1)

    # -------------------------------------------------------------- helpers

    def record(self, request: Request, body: bytes, origin: str) -> None:
        self.requests.append(Seen(request.method, origin, request.url.path,
                                  {k.lower(): v for k, v in request.headers.items()}, body))

    def seen(self, origin: str) -> list[Seen]:
        return [item for item in self.requests if item.origin == origin]

    def issue(self, scope: str) -> dict[str, Any]:
        n = next(self._ids)
        access = f"{SENTINEL}-access-{n}"
        expires = None if self.config.expires_in is None else time.monotonic() + self.config.expires_in
        self.tokens[access] = {"scope": scope, "expires": expires}
        body: dict[str, Any] = {"access_token": access, "token_type": "Bearer", "scope": scope}
        if self.config.expires_in is not None:
            body["expires_in"] = self.config.expires_in
        if self.config.issue_refresh:
            refresh = f"{SENTINEL}-refresh-{n}"
            self.refresh_tokens[refresh] = scope
            body["refresh_token"] = refresh
        return body

    def expire_all_tokens(self) -> None:
        for entry in self.tokens.values():
            entry["expires"] = time.monotonic() - 1

    def token_scope(self, header: str | None) -> str | None:
        if not header or not header.startswith("Bearer "):
            return None
        entry = self.tokens.get(header[len("Bearer "):])
        if entry is None or (entry["expires"] is not None and time.monotonic() > entry["expires"]):
            return None
        return entry["scope"]

    async def approve(self, authorization_url: str) -> dict[str, str]:
        """Le « navigateur » : suit l'URL d'autorisation et rend les paramètres du retour (code, state, iss, error)."""

        async with httpx.AsyncClient(trust_env=False) as browser:
            response = await browser.get(authorization_url, follow_redirects=False)
        if response.status_code != 302:
            raise AssertionError(f"authorize answered {response.status_code}: {response.text[:200]}")
        query = parse_qs(urlsplit(response.headers["location"]).query)
        return {key: values[0] for key, values in query.items()}

    async def notify_tools_changed(self) -> int:
        sent = 0
        for session in list(self.sessions):
            try:
                await session.send_tool_list_changed()
                sent += 1
            except Exception:  # noqa: BLE001 - a closed test session is simply skipped
                continue
        return sent


# ------------------------------------------------------------------ serveur d'autorisation


def _as_app(world: FakeWorld) -> Starlette:
    async def metadata(request: Request) -> Response:
        world.record(request, b"", "as")
        base = world.as_base
        body = {"issuer": base, "authorization_endpoint": f"{base}/authorize", "token_endpoint": f"{base}/token",
                "registration_endpoint": f"{base}/register", "response_types_supported": ["code"],
                "grant_types_supported": list(world.config.grants), "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"], "scopes_supported": [DEFAULT_SCOPE, "extra"]}
        if world.config.iss_supported:
            body["authorization_response_iss_parameter_supported"] = True
        if world.config.revocation:
            body["revocation_endpoint"] = f"{base}/revoke"
        return JSONResponse(body)

    async def register(request: Request) -> Response:
        raw = await request.body()
        world.record(request, raw, "as")
        body = json.loads(raw)
        world.registrations.append(body)
        if "refresh_token" in body.get("grant_types", []) and not world.config.accept_refresh_grant:
            return JSONResponse({"error": "invalid_client_metadata",
                                 "error_description": "grant type refresh_token not supported"}, status_code=400)
        client_id = f"client-{next(world._ids)}"
        world.clients[client_id] = body
        return JSONResponse({**body, "client_id": client_id}, status_code=201)

    async def authorize(request: Request) -> Response:
        world.record(request, b"", "as")
        q = request.query_params
        client = world.clients.get(q.get("client_id", ""))
        if client is None or q.get("redirect_uri") not in client.get("redirect_uris", []):
            return JSONResponse({"error": "invalid_client"}, status_code=400)
        if q.get("code_challenge_method") != "S256" or not q.get("code_challenge") or not q.get("state"):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        params: dict[str, str] = {"state": q["state"]}
        if world.config.deny:
            params["error"] = "access_denied"
        else:
            code = secrets.token_urlsafe(16)
            world.codes[code] = {"client_id": q["client_id"], "challenge": q["code_challenge"],
                                 "redirect_uri": q["redirect_uri"], "scope": q.get("scope") or DEFAULT_SCOPE,
                                 "resource": q.get("resource")}
            params["code"] = code
        if world.config.iss_supported or world.config.wrong_iss:
            params["iss"] = "https://evil.example.com" if world.config.wrong_iss else world.as_base
        return RedirectResponse(f"{q['redirect_uri']}?{urlencode(params)}", status_code=302)

    async def token(request: Request) -> Response:
        raw = await request.body()
        world.record(request, raw, "as")
        if world.config.token_delay_s:
            await asyncio.sleep(world.config.token_delay_s)
        form = {key: values[0] for key, values in parse_qs(raw.decode()).items()}
        if form.get("grant_type") == "refresh_token":
            scope = world.refresh_tokens.pop(form.get("refresh_token", ""), None)
            if scope is None:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            return JSONResponse(world.issue(scope))
        grant = world.codes.pop(form.get("code", ""), None)
        if grant is None or grant["client_id"] != form.get("client_id") \
                or grant["redirect_uri"] != form.get("redirect_uri"):
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        digest = hashlib.sha256(form.get("code_verifier", "").encode()).digest()
        if base64.urlsafe_b64encode(digest).decode().rstrip("=") != grant["challenge"]:
            return JSONResponse({"error": "invalid_grant", "error_description": "PKCE mismatch"}, status_code=400)
        return JSONResponse(world.issue(grant["scope"]))

    async def revoke(request: Request) -> Response:
        raw = await request.body()
        world.record(request, raw, "as")
        form = {key: values[0] for key, values in parse_qs(raw.decode()).items()}
        world.revoked.append(form.get("token_type_hint", "?"))
        world.tokens.pop(form.get("token", ""), None)
        return Response(status_code=200)

    async def steal(request: Request) -> Response:
        world.record(request, await request.body(), "as")
        return JSONResponse({"jsonrpc": "2.0", "id": 1, "result": {}})

    return Starlette(routes=[
        Route("/.well-known/oauth-authorization-server", metadata),
        Route("/register", register, methods=["POST"]),
        Route("/authorize", authorize),
        Route("/token", token, methods=["POST"]),
        Route("/revoke", revoke, methods=["POST"]),
        Route("/steal", steal, methods=["GET", "POST"]),
    ])


# ------------------------------------------------------------------ serveur MCP


def _mcp_server(world: FakeWorld) -> Server:
    server: Server = Server("Fake Remote", version="1.2.3",
                            icons=[types.Icon(src="https://icons.example.com/fake.png")])

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        world.list_calls += 1
        session = server.request_context.session
        if session not in world.sessions:
            world.sessions.append(session)
        return [types.Tool.model_validate(item) for item in world.config.tools]

    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        if name == "leak_error":
            return types.CallToolResult(isError=True, content=[types.TextContent(
                type="text", text=f"upstream said: Authorization: Bearer {SENTINEL}-leak token={SENTINEL}")])
        return types.CallToolResult(content=[types.TextContent(type="text", text=f"{name} ok {json.dumps(arguments)}")])

    return server


class _McpEndpoint:
    """ASGI : authentification du fake puis `StreamableHTTPSessionManager`."""

    def __init__(self, world: FakeWorld, manager: StreamableHTTPSessionManager) -> None:
        self.world = world
        self.manager = manager

    def _challenge(self, status: int, error: str | None = None, scope: str = DEFAULT_SCOPE) -> Response:
        parts = [f'resource_metadata="{self.world.rs_base}/.well-known/oauth-protected-resource"',
                 f'scope="{scope}"']
        if error:
            parts.insert(0, f'error="{error}"')
        return Response(status_code=status, headers={"www-authenticate": "Bearer " + ", ".join(parts)})

    async def __call__(self, scope, receive, send) -> None:
        request = Request(scope, receive)
        body = await request.body()
        self.world.record(request, body, "rs")
        config = self.world.config
        denial: Response | None = None
        if config.auth == "oauth":
            token_scope = self.world.token_scope(request.headers.get("authorization"))
            if token_scope is None:
                denial = self._challenge(401)
            elif config.list_scope and request.method == "POST" and b'"tools/list"' in body \
                    and config.list_scope not in token_scope.split():
                denial = self._challenge(403, "insufficient_scope", f"{DEFAULT_SCOPE} {config.list_scope}")
        elif config.auth == "bearer" and request.headers.get("authorization") != f"Bearer {config.static_value}":
            denial = Response(status_code=401)
        elif config.auth == "header" and request.headers.get(config.static_header) != config.static_value:
            denial = Response(status_code=401)
        if denial is not None:
            await denial(scope, receive, send)
            return
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.manager.handle_request(scope, replay, send)


def _rs_app(world: FakeWorld) -> Starlette:
    manager = StreamableHTTPSessionManager(app=_mcp_server(world))

    @asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield

    async def prm(request: Request) -> Response:
        world.record(request, b"", "rs")
        return JSONResponse({"resource": f"{world.rs_base}/mcp", "authorization_servers": [world.as_base],
                             "scopes_supported": [DEFAULT_SCOPE, "extra"], "bearer_methods_supported": ["header"]})

    async def crash(request: Request) -> Response:
        world.record(request, await request.body(), "rs")
        return JSONResponse({"error": "boom"}, status_code=500)

    async def slow(request: Request) -> Response:
        world.record(request, await request.body(), "rs")
        await asyncio.sleep(3600)
        return Response(status_code=204)

    async def malformed(request: Request) -> Response:
        world.record(request, await request.body(), "rs")
        return Response(b'{"jsonrpc": "2.0", "id": ', media_type="application/json")

    async def huge(request: Request) -> Response:
        world.record(request, await request.body(), "rs")
        return Response(b'{"pad":"' + b"x" * (5 * 1024 * 1024) + b'"}', media_type="application/json")

    async def redirect(request: Request) -> Response:
        world.record(request, await request.body(), "rs")
        return RedirectResponse(f"{world.as_base}/steal", status_code=307)

    async def legacy(request: Request) -> Response:
        world.record(request, await request.body(), "rs")
        return Response(status_code=405, headers={"allow": "GET"})

    return Starlette(lifespan=lifespan, routes=[
        Route("/mcp", _McpEndpoint(world, manager), methods=["GET", "POST", "DELETE"]),
        Route("/.well-known/oauth-protected-resource", prm),
        Route("/.well-known/oauth-protected-resource/mcp", prm),
        Route("/crash", crash, methods=["GET", "POST", "DELETE"]),
        Route("/slow", slow, methods=["GET", "POST", "DELETE"]),
        Route("/malformed", malformed, methods=["GET", "POST", "DELETE"]),
        Route("/huge", huge, methods=["GET", "POST", "DELETE"]),
        Route("/redirect", redirect, methods=["GET", "POST", "DELETE"]),
        Route("/legacy", legacy, methods=["GET", "POST", "DELETE"]),
    ])


# ------------------------------------------------------------------ cycle de vie


def _bound_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(64)
    sock.setblocking(False)
    return sock


async def _serve(app: Starlette) -> tuple[uvicorn.Server, asyncio.Task, str, socket.socket]:
    sock = _bound_socket()
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False, lifespan="on",
                                           timeout_graceful_shutdown=1))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    deadline = time.monotonic() + 10
    while not server.started:
        if task.done():
            task.result()
        if time.monotonic() > deadline:
            raise TimeoutError("fake server did not start")
        await asyncio.sleep(0.01)
    host, port = sock.getsockname()[:2]
    return server, task, f"http://{host}:{port}", sock


async def _shutdown(server: uvicorn.Server, task: asyncio.Task, sock: socket.socket) -> None:
    server.should_exit = True
    try:
        await asyncio.wait_for(task, timeout=5)
    except TimeoutError:
        server.force_exit = True
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    finally:
        sock.close()


@asynccontextmanager
async def running_fakes(config: FakeConfig | None = None) -> AsyncIterator[FakeWorld]:
    """Démarre AS puis RS sur 127.0.0.1 (ports éphémères) ; les arrête à la sortie, même en échec."""

    world = FakeWorld(config or FakeConfig())
    _reset_sse_globals()
    try:
        as_server = await _serve(_as_app(world))
        try:
            world.as_base = as_server[2]
            rs_server = await _serve(_rs_app(world))
            try:
                world.rs_base = rs_server[2]
                yield world
            finally:
                # SSE streams end on this module-global flag; RS before AS
                # because uvicorn restores signal handlers in LIFO order.
                sse_starlette.sse.AppStatus.should_exit = True
                await _shutdown(rs_server[0], rs_server[1], rs_server[3])
        finally:
            await _shutdown(as_server[0], as_server[1], as_server[3])
    finally:
        await _stop_sse_watchers()
        _reset_sse_globals()


def _reset_sse_globals() -> None:
    """`sse_starlette` keeps process-global shutdown state (a flag and one watcher per *thread*).

    Each test runs its own event loop: without a reset, the flag left `True`
    by the previous fake makes every SSE answer end at once, and the watcher
    of a closed loop never wakes the new one.
    """

    sse_starlette.sse.AppStatus.should_exit = False
    sse_starlette.sse._thread_state.shutdown_state = None


async def _stop_sse_watchers() -> None:
    watchers = [task for task in asyncio.all_tasks()
                if getattr(task.get_coro(), "__qualname__", "") == "_shutdown_watcher"]
    for task in watchers:
        task.cancel()
    await asyncio.gather(*watchers, return_exceptions=True)
