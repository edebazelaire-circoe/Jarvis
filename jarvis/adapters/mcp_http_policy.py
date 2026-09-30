"""Politique réseau des plugins MCP distants (Slice 03 ; `docs/mcp/plugins.md` §4.2, ARCH §5.2).

Un seul `httpx.AsyncClient` par plugin, remis au SDK `mcp`, porte **toutes**
les requêtes du plugin : MCP, métadonnées de ressource protégée, métadonnées du
serveur d'autorisation, enregistrement dynamique, jeton, révocation. Son
transport est `PolicyTransport`, qui pour chaque requête :

- résout l'hôte (`loop.getaddrinfo`, injectable) et refuse si **une** adresse
  résolue est interdite (`is_forbidden_address`) — le bouclage n'est permis
  que sous le drapeau de développement `JARVIS_MCP_ALLOW_LOOPBACK_HTTP` —
  ⇒ `mcp_endpoint_forbidden` (ARCH §16 E4) ;
- décode d'abord les hôtes qui ressemblent à une IPv4 (`2130706433`,
  `0x7f000001`, `127.1`, `0177.0.0.1`) et juge les IPv6 porteuses d'une IPv4
  (NAT64, `::a.b.c.d`, 6to4, Teredo) sur l'IPv4 embarquée ; `%` dans l'hôte
  ou port 0 ⇒ `mcp_endpoint_invalid` ;
- refuse tout schéma autre que https, sauf http vers un hôte entièrement de
  bouclage sous ce drapeau ⇒ `mcp_endpoint_invalid` ;
- plafonne chaque corps de réponse à `MAX_RESPONSE_BYTES` (compteur en flux)
  ⇒ `mcp_response_too_large`.

Redirections : le client est construit avec `follow_redirects=False` et
`max_redirects=20` (écart à ARCH §5.2, voir `MAX_REDIRECTS`) ; le SDK ne suit
que les redirections de même origine qui gardent la méthode, et n'envoie
jamais le bearer ailleurs (`mcp/shared/_httpx_utils.py`). `trust_env=False` : un proxy d'environnement
ne doit pas contourner la résolution ci-dessus.

Risque résiduel accepté en V1 (documenté) : rebinding DNS entre notre
résolution et la connexion de httpx.

Chaque refus est aussi signalé à `on_violation(code)` : le SDK avale certaines
erreurs de lecture (flux SSE) ; la session s'en sert pour échouer vite au lieu
d'attendre son délai.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
import ipaddress
import socket

import httpx

from jarvis.domain.mcp_endpoint import is_forbidden_address, parse_ipv4_like
from jarvis.domain.mcp_plugins import McpErrorCode, McpPluginError

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
#: httpx counts every request of an `httpx.Auth` flow in the redirect history
#: (`_send_handling_auth` appends each response), and one OAuth flow makes up to
#: ~12 (PRM and AS discovery fallbacks, DCR, token, retry). ARCH §5.2's `3`
#: would abort every OAuth connection (`TooManyRedirects`), so the client keeps
#: httpx's default. The SDK still follows only same-origin, method-preserving
#: redirects and never forwards credentials to another origin.
MAX_REDIRECTS = 20
CONNECT_TIMEOUT_S = 10.0
#: Lecture d'une réponse (appel d'outil) ; l'enveloppe `initialize`/liste est bornée par la session.
READ_TIMEOUT_S = 60.0

Resolver = Callable[[str, int], Awaitable[list[str]]]


class McpPolicyError(Exception):
    """Requête refusée par la politique réseau. `code` est un code stable ; le message ne cite aucun secret."""

    def __init__(self, code: McpErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


async def system_resolver(host: str, port: int) -> list[str]:
    """Toutes les adresses de `host` (IPv4 et IPv6), via la boucle asyncio."""

    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]).split("%", 1)[0] for info in infos})


def _is_loopback(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = getattr(address, "ipv4_mapped", None)
    return address.is_loopback or (mapped is not None and mapped.is_loopback)


class _CappedStream(httpx.AsyncByteStream):
    def __init__(self, inner: httpx.AsyncByteStream, limit: int, report: Callable[[McpErrorCode], None]) -> None:
        self._inner = inner
        self._limit = limit
        self._report = report

    async def __aiter__(self) -> AsyncIterator[bytes]:
        seen = 0
        async for chunk in self._inner:
            seen += len(chunk)
            if seen > self._limit:
                self._report(McpErrorCode.RESPONSE_TOO_LARGE)
                raise McpPolicyError(McpErrorCode.RESPONSE_TOO_LARGE,
                                     f"remote response exceeds {self._limit} bytes")
            yield chunk

    async def aclose(self) -> None:
        await self._inner.aclose()


class PolicyTransport(httpx.AsyncBaseTransport):
    def __init__(self, *, allow_loopback_http: bool = False, resolver: Resolver | None = None,
                 inner: httpx.AsyncBaseTransport | None = None, max_response_bytes: int = MAX_RESPONSE_BYTES,
                 on_violation: Callable[[McpErrorCode], None] | None = None) -> None:
        self._allow_loopback = bool(allow_loopback_http)
        self._resolver = resolver or system_resolver
        self._inner = inner or httpx.AsyncHTTPTransport(retries=0)
        self._limit = max_response_bytes
        self._on_violation = on_violation

    def _report(self, code: McpErrorCode) -> None:
        if self._on_violation is not None:
            self._on_violation(code)

    def _refuse(self, code: McpErrorCode, message: str) -> McpPolicyError:
        self._report(code)
        return McpPolicyError(code, message)

    async def check_url(self, url: httpx.URL) -> None:
        """Refuse l'URL (schéma, adresses résolues) ; aucune E/S réseau autre que la résolution DNS."""

        scheme = url.scheme
        if scheme not in {"https", "http"}:
            raise self._refuse(McpErrorCode.ENDPOINT_INVALID, "only https URLs may be reached")
        host = url.host
        if not host:
            raise self._refuse(McpErrorCode.ENDPOINT_INVALID, "the URL has no host")
        if "%" in host or url.port == 0:
            raise self._refuse(McpErrorCode.ENDPOINT_INVALID, "percent-encoded host or port 0")
        port = url.port or (443 if scheme == "https" else 80)
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is None:
            try:
                # `2130706433`, `0x7f000001`, `127.1`: decoded like the OS resolver would.
                literal = parse_ipv4_like(host)
            except McpPluginError as exc:
                raise self._refuse(exc.code, str(exc)) from None
        if literal is not None:
            addresses = [literal]
        else:
            try:
                resolved = await self._resolver(host, port)
            except (OSError, UnicodeError) as exc:
                # Expected refusal, reported by code: the host does not resolve.
                raise McpPolicyError(McpErrorCode.REMOTE_UNREACHABLE,
                                     f"host does not resolve ({type(exc).__name__})") from None
            addresses = [ipaddress.ip_address(item) for item in resolved]
            if not addresses:
                raise McpPolicyError(McpErrorCode.REMOTE_UNREACHABLE, "host resolves to no address")
        for address in addresses:
            if is_forbidden_address(address) and not (self._allow_loopback and _is_loopback(address)):
                raise self._refuse(McpErrorCode.ENDPOINT_FORBIDDEN,
                                   "the host resolves to an address that is not a public internet address")
        if scheme == "http" and not (self._allow_loopback and all(_is_loopback(item) for item in addresses)):
            raise self._refuse(McpErrorCode.ENDPOINT_INVALID, "only https URLs may be reached")

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await self.check_url(request.url)
        response = await self._inner.handle_async_request(request)
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > self._limit:
            await response.aclose()
            raise self._refuse(McpErrorCode.RESPONSE_TOO_LARGE, f"remote response exceeds {self._limit} bytes")
        stream = response.stream
        if not isinstance(stream, httpx.AsyncByteStream):  # an async transport always streams asynchronously
            raise TypeError(f"inner transport returned a {type(stream).__name__}, not an async stream")
        return httpx.Response(status_code=response.status_code, headers=response.headers,
                              stream=_CappedStream(stream, self._limit, self._report),
                              extensions=response.extensions)

    async def aclose(self) -> None:
        await self._inner.aclose()


def build_http_client(transport: PolicyTransport, *, auth: httpx.Auth | None = None,
                      connect_timeout_s: float = CONNECT_TIMEOUT_S,
                      read_timeout_s: float = READ_TIMEOUT_S) -> httpx.AsyncClient:
    """Le client unique d'un plugin : politique réseau, aucun suivi automatique de redirection, pas de proxy d'env."""

    return httpx.AsyncClient(
        transport=transport, auth=auth, follow_redirects=False, max_redirects=MAX_REDIRECTS, trust_env=False,
        timeout=httpx.Timeout(read_timeout_s, connect=connect_timeout_s),
    )
