"""Politique statique des endpoints de plugins MCP (Slice 02 ; `docs/mcp/plugins.md` §4.1, ARCH §5.1, §16 E4).

`validate_endpoint` normalise l'URL saisie ou la refuse avec une raison :

- problème de **syntaxe** (schéma, userinfo, fragment, clé de requête qui
  ressemble à un identifiant, longueur, hôte non IDNA) ⇒ `mcp_endpoint_invalid` ;
- **adresse interdite** (IP littérale non globale, `localhost`) ⇒
  `mcp_endpoint_forbidden`.

Validation statique seulement : aucune résolution DNS ici. La résolution et le
refus des adresses résolues appartiennent à `PolicyTransport` (Slice 03).
`localhost` est traité comme une adresse de bouclage : c'est la seule forme
nommée que l'on peut classer sans DNS.

Pur : bibliothèque standard seulement (`ipaddress`, `urllib.parse`).
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import parse_qsl, urlsplit

from jarvis.domain.mcp_plugins import MAX_ENDPOINT_CHARS, McpErrorCode, McpPluginError

#: Clés de requête qui portent vraisemblablement un identifiant (casse ignorée).
_CREDENTIAL_QUERY_KEY = re.compile(r"token|key|secret|auth|password|sig", re.IGNORECASE)
_EXTRA_FORBIDDEN_NETWORKS = tuple(ipaddress.ip_network(net) for net in (
    "100.64.0.0/10", "169.254.0.0/16", "fd00::/8",
))
_LOOPBACK_NAMES = frozenset({"localhost"})
_DEFAULT_PORTS = {"https": 443, "http": 80}

IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _invalid(reason: str) -> McpPluginError:
    return McpPluginError(McpErrorCode.ENDPOINT_INVALID, f"endpoint refused: {reason}")


def _forbidden(reason: str) -> McpPluginError:
    return McpPluginError(McpErrorCode.ENDPOINT_FORBIDDEN, f"endpoint refused: {reason}")


def is_forbidden_address(ip: IpAddress | str) -> bool:
    """Vrai pour toute adresse qu'un plugin ne doit jamais joindre (SSRF).

    `not ip.is_global`, ou dans `100.64.0.0/10`, `169.254.0.0/16`, `fd00::/8`,
    ou une adresse `::ffff:0:0/96` dont l'IPv4 embarquée est interdite.
    """

    address = ipaddress.ip_address(ip) if isinstance(ip, str) else ip
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None and is_forbidden_address(mapped):
        return True
    if not address.is_global:
        return True
    return any(address.version == net.version and address in net for net in _EXTRA_FORBIDDEN_NETWORKS)


def _is_loopback_host(host: str) -> bool:
    if host in _LOOPBACK_NAMES or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    return address.is_loopback or (mapped is not None and mapped.is_loopback)


def _ascii_host(host: str) -> str:
    if host.isascii():
        return host
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        raise _invalid("the host name is not IDNA-encodable") from None


def validate_endpoint(raw: object, *, allow_loopback_http: bool) -> str:
    """URL normalisée (`https://hôte[:port]/chemin[?requête]`) ou `McpPluginError`.

    `http` n'est accepté que vers un hôte de bouclage **et** avec
    `allow_loopback_http` (drapeau de développement
    `JARVIS_MCP_ALLOW_LOOPBACK_HTTP=1`), qui autorise aussi ce bouclage en https.
    """

    if not isinstance(raw, str) or not raw.strip():
        raise _invalid("an endpoint URL is required")
    text = raw.strip()
    if len(text) > MAX_ENDPOINT_CHARS:
        raise _invalid(f"longer than {MAX_ENDPOINT_CHARS} characters")
    if any(ch.isspace() or not ch.isprintable() for ch in text):
        raise _invalid("spaces and control characters are not allowed")
    if "#" in text:
        raise _invalid("a fragment is not allowed")
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError as exc:
        raise _invalid(f"malformed URL ({exc})") from None
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS:
        raise _invalid("the scheme must be https")
    if "@" in parts.netloc:
        raise _invalid("credentials in the URL (userinfo) are not allowed")
    host = parts.hostname
    if not host:
        raise _invalid("a host is required")
    host = _ascii_host(host).lower().rstrip(".")
    if not host:
        raise _invalid("a host is required")
    for key, _ in parse_qsl(parts.query, keep_blank_values=True):
        if _CREDENTIAL_QUERY_KEY.search(key):
            raise _invalid("a query parameter looks like a credential; use the credential form instead")
    loopback = _is_loopback_host(host)
    if scheme == "http" and not (loopback and allow_loopback_http):
        raise _invalid("the scheme must be https")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if loopback and not allow_loopback_http:
        raise _forbidden("loopback addresses are not allowed")
    if address is not None and not loopback and is_forbidden_address(address):
        raise _forbidden("the address is not a public internet address")
    netloc = f"[{host}]" if address is not None and address.version == 6 else host
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        netloc = f"{netloc}:{port}"
    path = parts.path or "/"
    normalized = f"{scheme}://{netloc}{path}" + (f"?{parts.query}" if parts.query else "")
    if len(normalized) > MAX_ENDPOINT_CHARS or not normalized.isascii():
        raise _invalid("the path or query must be ASCII (percent-encoded) and bounded")
    return normalized
