"""Connecteur MCP distant générique sur le SDK `mcp` (Slice 03 ; `docs/mcp/plugins.md` §2.2, §4, ARCH §4.2, §5.4).

`SdkRemoteMcpConnector.open(plugin, auth, prompt)` est un contexte asynchrone
qui, **dans la tâche qui l'entre et le quitte** (le transport du SDK est
anyio et tient un groupe de tâches), empile :

1. un `httpx.AsyncClient` unique dont le transport est `PolicyTransport`
   (SSRF, https, plafond 4 Mio) et l'authentification :
   - `oauth` ⇒ `JarvisOAuthProvider` (jetons dans le coffre, interactif ou non),
   - `bearer`/`header` ⇒ `OriginHeaderAuth` : les en-têtes statiques ne
     partent que vers l'origine du plugin, jamais vers un autre hôte ;
2. `streamable_http_client` (transport « Streamable HTTP » actuel ; le SSE
   historique n'est pas implémenté) ;
3. `ClientSession`, dont le `message_handler` capte `tools/list_changed` et
   les messages illisibles.

Toute sortie en échec **du transport** devient **une** `RemoteMcpError(code)` :
les groupes d'exceptions anyio, les erreurs httpx, `McpError`, les erreurs
OAuth du SDK et les refus de politique sont réduits au code stable le plus
précis (`classify`), la cause restant chaînée (`from exc`). Aucun corps
distant n'entre dans un message. Une exception levée par **le code de
l'appelant** dans le contexte (service, registre...) ressort telle quelle,
même extraite du groupe d'exceptions du SDK : ce n'est pas une panne
distante et elle ne doit jamais être réessayée comme telle.

Le SDK avale certaines erreurs de lecture (JSON illisible, flux SSE coupé) et
laisse alors la requête en attente jusqu'à son délai : chaque requête de la
session est donc « gardée » (`_guarded`) et échoue dès qu'une panne est
signalée (`fail`), au lieu d'attendre.

Consentement OAuth (correctif S7, ARCH §16 E22) : le flux interactif du SDK
attend le retour du navigateur **à l'intérieur** de la requête `initialize`
(ou d'une page de `tools/list`). Cette attente appartient à l'humain, pas au
serveur : le fournisseur OAuth l'entoure de `consent_window()`, et l'horloge
de budget de la session (`_budget_clock`) est gelée pendant la fenêtre. Le
budget `handshake_s` (30 s) ne couvre donc que les échanges réseau avant et
après le consentement ; l'attente elle-même n'est bornée que par le TTL de
l'autorisation en attente (300 s, `McpPluginService`).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
import ssl
from typing import Any

import httpx
from mcp import ClientSession, McpError, types
from mcp.client.auth.exceptions import OAuthFlowError, OAuthTokenError
from mcp.client.auth.utils import OAuthRegistrationError
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CONNECTION_CLOSED
from pydantic import ValidationError

from jarvis.adapters.mcp_http_policy import (
    CONNECT_TIMEOUT_S, READ_TIMEOUT_S, McpPolicyError, PolicyTransport, Resolver, build_http_client,
)
from jarvis.adapters.mcp_oauth import JarvisOAuthProvider, VaultTokenStorage, revoke_tokens
from jarvis.domain.mcp_plugins import McpErrorCode, McpPlugin, McpPluginError, icon_url_from
from jarvis.ports.mcp_plugins import AuthMaterial, AuthorizationPrompt, McpPluginStoreError, RemoteMcpError

MAX_LIST_PAGES = 10
#: Code JSON-RPC que le SDK renvoie quand le serveur répond 404 à un POST (« Session terminated »).
_SDK_SESSION_TERMINATED = 32600
_REQUEST_TIMEOUT = 408
_METADATA_ISSUER_MISMATCH = "Authorization server metadata issuer mismatch"


@dataclass(frozen=True, slots=True)
class Timeouts:
    """Délais d'ARCH §5.2 ; réduits par les tests seulement."""

    connect_s: float = CONNECT_TIMEOUT_S
    read_s: float = READ_TIMEOUT_S
    #: Enveloppe de `initialize` puis de toute la liste d'outils, attente du consentement OAuth exclue.
    handshake_s: float = 30.0


# ------------------------------------------------------------------ classification


def _leaves(exc: BaseException) -> list[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for inner in exc.exceptions for leaf in _leaves(inner)]
    return [exc]


def leaf_types(exc: BaseException) -> str:
    """Types des feuilles d'un échec (`ExceptionGroup` déplié) : ce que le journal doit nommer."""

    return ",".join(dict.fromkeys(type(leaf).__name__ for leaf in _leaves(exc)))


def local_failure(exc: BaseException) -> BaseException | None:
    """Feuille née du code de Jarvis sous le transport (registre, coffre) : jamais une panne distante."""

    return next((leaf for leaf in _leaves(exc) if isinstance(leaf, McpPluginStoreError)), None)


def _specific_code(exc: BaseException) -> McpErrorCode | None:
    """Codes déjà décidés par Jarvis (politique, invite, coffre) : ils priment sur tout le reste."""

    if isinstance(exc, (RemoteMcpError, McpPluginError, McpPolicyError)):
        return exc.code
    return None


def _tls_failure(exc: BaseException) -> bool:
    seen: BaseException | None = exc
    while seen is not None:
        if isinstance(seen, ssl.SSLError):
            return True
        seen = seen.__cause__ or seen.__context__
    return "CERTIFICATE_VERIFY_FAILED" in str(exc) or "SSL" in str(exc)


def _generic_code(exc: BaseException) -> McpErrorCode | None:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (401, 403):
            return McpErrorCode.REAUTHORIZATION_REQUIRED
        if status in (404, 405):
            return McpErrorCode.TRANSPORT_UNSUPPORTED
        if status >= 500:
            return McpErrorCode.REMOTE_UNREACHABLE
        return McpErrorCode.REMOTE_PROTOCOL
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return McpErrorCode.REMOTE_TIMEOUT
    if isinstance(exc, httpx.ConnectError):
        return McpErrorCode.REMOTE_TLS if _tls_failure(exc) else McpErrorCode.REMOTE_UNREACHABLE
    if isinstance(exc, httpx.TooManyRedirects):
        return McpErrorCode.REMOTE_PROTOCOL
    if isinstance(exc, httpx.TransportError):
        return McpErrorCode.REMOTE_UNREACHABLE
    if isinstance(exc, McpError):
        if exc.error.code == _REQUEST_TIMEOUT:
            return McpErrorCode.REMOTE_TIMEOUT
        if exc.error.code == CONNECTION_CLOSED:
            return None  # a consequence: the cause is recorded elsewhere
        return McpErrorCode.REMOTE_PROTOCOL
    if isinstance(exc, OAuthFlowError) and str(exc).startswith(_METADATA_ISSUER_MISMATCH):
        return McpErrorCode.OAUTH_ISSUER_MISMATCH
    if isinstance(exc, (OAuthFlowError, OAuthTokenError, OAuthRegistrationError)):
        return McpErrorCode.REAUTHORIZATION_REQUIRED
    if isinstance(exc, (ValidationError, ValueError, RuntimeError)):
        return McpErrorCode.REMOTE_PROTOCOL
    return None


def classify(exc: BaseException, recorded: McpErrorCode | None = None) -> McpErrorCode | None:
    """Code stable d'un échec (feuilles d'un groupe comprises), ou `None` pour une annulation pure.

    Priorité : code décidé par Jarvis, puis panne signalée à la session
    (`recorded`), puis correspondance générique ; à défaut `mcp_remote_protocol`.
    """

    leaves = [leaf for leaf in _leaves(exc) if not isinstance(leaf, (asyncio.CancelledError, GeneratorExit))]
    if not leaves:
        return None
    if not all(isinstance(leaf, Exception) for leaf in leaves):
        return None  # KeyboardInterrupt / SystemExit: never converted
    for leaf in leaves:
        if (code := _specific_code(leaf)) is not None:
            return code
    if recorded is not None:
        return recorded
    for leaf in leaves:
        if (code := _generic_code(leaf)) is not None:
            return code
    return McpErrorCode.REMOTE_PROTOCOL


# ------------------------------------------------------------------ authentification statique


class OriginHeaderAuth(httpx.Auth):
    """En-têtes statiques (bearer / en-tête) posés **seulement** sur les requêtes vers l'origine du plugin."""

    def __init__(self, origin: str, headers: tuple[tuple[str, str], ...]) -> None:
        url = httpx.URL(origin)
        self._origin = (url.scheme, url.host, url.port)
        self._headers = headers

    def auth_flow(self, request: httpx.Request):
        if (request.url.scheme, request.url.host, request.url.port) == self._origin:
            for name, value in self._headers:
                request.headers[name] = value
        yield request


# ------------------------------------------------------------------ session


class SdkRemoteMcpSession:
    """`RemoteMcpSession` sur une `ClientSession` du SDK ; appelable depuis n'importe quelle tâche."""

    def __init__(self, timeouts: Timeouts) -> None:
        self._timeouts = timeouts
        self._client: ClientSession | None = None
        self._failed = asyncio.Event()
        self.failure_code: McpErrorCode | None = None
        #: Panne locale (registre, coffre) remontée par le SDK comme un message : relevée telle quelle.
        self.local_error: BaseException | None = None
        self._tools_changed: Callable[[], Awaitable[None]] | None = None
        #: Début de la fenêtre de consentement ouverte (horloge de la boucle), sinon `None`.
        self._consent_since: float | None = None
        #: Durée cumulée des fenêtres de consentement refermées.
        self._consent_total = 0.0
        #: Remplacé (puis levé) à chaque ouverture ou fermeture : jamais remis à zéro sous un attenteur.
        self._consent_changed = asyncio.Event()

    def bind(self, client: ClientSession) -> None:
        self._client = client

    def fail(self, code: McpErrorCode) -> None:
        """Première panne signalée : toute requête gardée en cours ou future échoue avec ce code."""

        if self.failure_code is None:
            self.failure_code = code
        self._failed.set()

    def close(self) -> None:
        """Session quittée : les requêtes gardées en cours échouent (`mcp_plugin_disconnected`) sans cause inventée."""

        self._failed.set()

    async def wait_failure(self) -> McpErrorCode:
        await self._failed.wait()
        return self.failure_code or McpErrorCode.PLUGIN_DISCONNECTED

    def _budget_clock(self) -> float:
        """Horloge des budgets de requête : celle de la boucle, arrêtée pendant le consentement OAuth."""

        now = asyncio.get_running_loop().time() if self._consent_since is None else self._consent_since
        return now - self._consent_total

    def _consent_flip(self) -> None:
        changed, self._consent_changed = self._consent_changed, asyncio.Event()
        changed.set()

    @asynccontextmanager
    async def consent_window(self) -> AsyncIterator[None]:
        """Attente du navigateur : hors de tout budget de requête (bornée par le TTL de l'autorisation)."""

        self._consent_since = asyncio.get_running_loop().time()
        self._consent_flip()
        try:
            yield
        finally:
            self._consent_total += asyncio.get_running_loop().time() - self._consent_since
            self._consent_since = None
            self._consent_flip()

    def on_tools_changed(self, callback: Callable[[], Awaitable[None]]) -> None:
        self._tools_changed = callback

    async def handle_message(self, message: Any) -> None:
        """`message_handler` du SDK : notifications et messages illisibles (le SDK n'en fait rien)."""

        if isinstance(message, Exception) and local_failure(message) is not None:
            # Jarvis' own store failed under the SDK (tokens written by the
            # OAuth flow): the session is unusable, but nothing remote failed.
            self.local_error = local_failure(message)
            self._failed.set()
            return
        if isinstance(message, Exception):
            # The SDK could not parse a response: the request it answered will
            # never resolve, so the whole session is broken.
            self.fail(McpErrorCode.REMOTE_PROTOCOL)
            return
        if (isinstance(message, types.ServerNotification)
                and isinstance(message.root, types.ToolListChangedNotification)
                and self._tools_changed is not None):
            await self._tools_changed()

    def _require_client(self) -> ClientSession:
        if self._client is None:
            raise RuntimeError("the SDK session is not bound yet")  # programming error, not a remote failure
        return self._client

    async def _guarded(self, awaitable: Awaitable[Any], timeout_s: float, *,
                       terminated: McpErrorCode = McpErrorCode.REMOTE_UNREACHABLE) -> Any:
        """Attend `awaitable` au plus `timeout_s` (horloge de budget), ou jusqu'à la première panne signalée.

        Le temps passé dans une fenêtre de consentement ne compte pas : pendant
        la fenêtre, seules la panne ou la fin du travail (le fournisseur OAuth
        lève au TTL de l'autorisation) terminent l'attente.

        `terminated` : code d'un 404 du serveur (« Session terminated » du SDK) —
        transport non pris en charge pour `initialize`, session perdue ensuite.
        """

        if self._failed.is_set():
            if asyncio.iscoroutine(awaitable):
                awaitable.close()  # never scheduled: no "coroutine was never awaited" warning
            raise RemoteMcpError(self.failure_code or McpErrorCode.PLUGIN_DISCONNECTED, "the session is closed")
        start = self._budget_clock()
        work = asyncio.ensure_future(awaitable)
        broken = asyncio.ensure_future(self._failed.wait())
        done: set[asyncio.Future] = set()
        try:
            while not done:
                consenting = self._consent_since is not None
                remaining = None if consenting else timeout_s - (self._budget_clock() - start)
                if remaining is not None and remaining <= 0:
                    break
                changed = asyncio.ensure_future(self._consent_changed.wait())
                try:
                    done, _ = await asyncio.wait({work, broken, changed}, timeout=remaining,
                                                 return_when=asyncio.FIRST_COMPLETED)
                finally:
                    changed.cancel()
                if not done:
                    break  # the budget elapsed outside any consent window
                done.discard(changed)  # a window opened or closed: recompute what is left
        finally:
            for task in (work, broken):
                if not task.done():
                    task.cancel()
            await asyncio.gather(work, broken, return_exceptions=True)
        if self.local_error is not None:
            raise self.local_error
        if work in done and not work.cancelled():
            error = work.exception()
            if error is None:
                return work.result()
            if (local := local_failure(error)) is not None:
                raise local
            if isinstance(error, McpError) and error.error.code == _SDK_SESSION_TERMINATED:
                raise RemoteMcpError(terminated, "the server answered 404 to the MCP request") from error
            code = classify(error, self.failure_code) or McpErrorCode.REMOTE_PROTOCOL
            raise RemoteMcpError(code, f"remote request failed ({leaf_types(error)})") from error
        if broken in done:
            raise RemoteMcpError(self.failure_code or McpErrorCode.PLUGIN_DISCONNECTED, "the session broke")
        raise RemoteMcpError(McpErrorCode.REMOTE_TIMEOUT, f"no answer within {timeout_s:g} s")

    async def initialize(self) -> dict[str, Any]:
        result: types.InitializeResult = await self._guarded(
            self._require_client().initialize(), self._timeouts.handshake_s,
            terminated=McpErrorCode.TRANSPORT_UNSUPPORTED)
        info = result.serverInfo
        icons = [icon.src for icon in info.icons or () if icon_url_from(icon.src)]
        return {"name": info.name, "version": info.version, "protocol_version": str(result.protocolVersion),
                "icon_url": icons[0] if icons else None}

    async def list_tools_all(self) -> list[dict[str, Any]]:
        client = self._require_client()
        deadline = self._budget_clock() + self._timeouts.handshake_s
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(MAX_LIST_PAGES):
            params = types.PaginatedRequestParams(cursor=cursor) if cursor else None
            remaining = max(0.001, deadline - self._budget_clock())
            page: types.ListToolsResult = await self._guarded(client.list_tools(params=params), remaining)
            tools.extend(tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in page.tools)
            cursor = page.nextCursor
            if not cursor:
                break
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        result: types.CallToolResult = await self._guarded(
            self._require_client().call_tool(name, arguments, read_timeout_seconds=timedelta(seconds=timeout_s)), timeout_s)
        return result.model_dump(mode="json", by_alias=True, exclude_none=True)


# ------------------------------------------------------------------ connecteur


class SdkRemoteMcpConnector:
    """`RemoteMcpConnector` : un client HTTP, un transport Streamable HTTP et une session par ouverture."""

    def __init__(self, *, redirect_uri: str, allow_loopback_http: bool = False, resolver: Resolver | None = None,
                 timeouts: Timeouts = Timeouts()) -> None:
        self.redirect_uri = redirect_uri
        self._allow_loopback_http = bool(allow_loopback_http)
        self._resolver = resolver
        self._timeouts = timeouts

    def _policy(self, on_violation: Callable[[McpErrorCode], None] | None = None) -> PolicyTransport:
        return PolicyTransport(allow_loopback_http=self._allow_loopback_http, resolver=self._resolver,
                               on_violation=on_violation)

    def _http_auth(self, plugin: McpPlugin, auth: AuthMaterial, prompt: AuthorizationPrompt | None,
                   consent_window: Callable[[], AbstractAsyncContextManager[None]]) -> httpx.Auth | None:
        if auth.strategy == "oauth":
            if auth.oauth is None:
                raise RemoteMcpError(McpErrorCode.VAULT_UNAVAILABLE, "oauth needs the credential vault")
            storage = VaultTokenStorage(auth.oauth, redirect_uri=self.redirect_uri)
            return JarvisOAuthProvider(plugin.endpoint, storage, redirect_uri=self.redirect_uri, prompt=prompt,
                                       consent_window=consent_window)
        if auth.strategy in {"bearer", "header"}:
            return OriginHeaderAuth(plugin.endpoint_origin, auth.static_headers)
        return None

    def open(self, plugin: McpPlugin, auth: AuthMaterial, prompt: AuthorizationPrompt | None):
        return self._open(plugin, auth, prompt)

    @asynccontextmanager
    async def _open(self, plugin: McpPlugin, auth: AuthMaterial,
                    prompt: AuthorizationPrompt | None) -> AsyncIterator[SdkRemoteMcpSession]:
        session = SdkRemoteMcpSession(self._timeouts)
        client = build_http_client(self._policy(session.fail), auth=self._http_auth(plugin, auth, prompt, session.consent_window),
                                   connect_timeout_s=self._timeouts.connect_s, read_timeout_s=self._timeouts.read_s)
        consumer_error: BaseException | None = None
        try:
            async with client, streamable_http_client(plugin.endpoint, http_client=client) as (read, write, _):
                async with ClientSession(read, write, message_handler=session.handle_message) as sdk_session:
                    session.bind(sdk_session)
                    try:
                        yield session
                    except BaseException as exc:
                        consumer_error = exc  # raised by the caller's own code, not by the transport
                        raise
        except BaseException as exc:
            if consumer_error is not None and any(leaf is consumer_error for leaf in _leaves(exc)):
                # The consumer's own failure (a service bug, a store error...) is
                # re-raised unchanged, even out of the SDK's exception group: it is
                # not a remote failure and must never be retried as one.
                if isinstance(consumer_error, (RemoteMcpError, McpPluginError)):
                    session.fail(consumer_error.code)  # a session call failed: concurrent calls share its code
                raise consumer_error  # noqa: B904 — the group stays attached as __context__
            code = classify(exc, session.failure_code)
            if code is None:
                raise  # cancellation, KeyboardInterrupt: never converted
            if (local := session.local_error or local_failure(exc)) is not None:
                raise local  # noqa: B904 — a local store failure, never relabelled as remote
            # Recorded before waiters wake: a concurrent call gets the real cause.
            session.fail(code)
            if isinstance(exc, RemoteMcpError):
                raise
            raise RemoteMcpError(code, f"remote MCP connection failed ({leaf_types(exc)})") from exc
        finally:
            session.close()

    async def revoke(self, plugin: McpPlugin, oauth: Mapping[str, Any]) -> None:
        client = build_http_client(self._policy(), connect_timeout_s=self._timeouts.connect_s,
                                   read_timeout_s=self._timeouts.connect_s)
        try:
            async with client:
                await revoke_tokens(client, dict(oauth))
        except RemoteMcpError:
            raise
        except Exception as exc:
            raise RemoteMcpError(classify(exc) or McpErrorCode.REMOTE_PROTOCOL,
                                 f"token revocation failed ({leaf_types(exc)})") from exc
