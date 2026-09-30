"""Politique statique des endpoints de plugins MCP (Slice 02 ; `docs/mcp/plugins.md` §4.1, ARCH §5.1, §16 E4).

`validate_endpoint` normalise l'URL saisie ou la refuse avec une raison :

- problème de **syntaxe** (schéma, userinfo, fragment, clé de requête qui
  ressemble à un identifiant, longueur, hôte non IDNA) ⇒ `mcp_endpoint_invalid` ;
- **adresse interdite** (IP littérale non globale, `localhost`) ⇒
  `mcp_endpoint_forbidden`.

Durcissement Slice 03 (retour QA de la Slice 02) : un hôte qui *ressemble* à
une IPv4 (décimal seul `2130706433`, hexadécimal `0x7f000001`, octal `0177.0.0.1`,
forme courte `127.1`, `0`) est décodé comme le ferait `inet_aton` : adresse
interdite ⇒ `mcp_endpoint_forbidden`, sinon forme non canonique ⇒
`mcp_endpoint_invalid`. Une IPv6 qui embarque une IPv4 (NAT64 `64:ff9b::/96`,
compatible `::/96`, 6to4, Teredo) est jugée aussi sur l'IPv4 embarquée. Port 0
et `%` dans l'hôte ⇒ `mcp_endpoint_invalid`.

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
#: IPv6 préfixes qui transportent une IPv4 dans leurs 32 bits de poids faible.
_IPV4_EMBEDDING_NETWORKS = tuple(ipaddress.ip_network(net) for net in (
    "64:ff9b::/96",   # NAT64 well-known prefix (RFC 6052)
    "64:ff9b:1::/48",  # NAT64 local-use (RFC 8215)
    "::/96",          # IPv4-compatible (deprecated, RFC 4291 §2.5.5.1)
))
_IPV4_PART = re.compile(r"0[xX][0-9a-fA-F]*|[0-9]+")
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
    for embedded in _embedded_ipv4(address):
        if is_forbidden_address(embedded):
            return True
    if not address.is_global:
        return True
    return any(address.version == net.version and address in net for net in _EXTRA_FORBIDDEN_NETWORKS)


def _embedded_ipv4(address: IpAddress) -> list[ipaddress.IPv4Address]:
    """IPv4 portées par une IPv6 : mappée, NAT64, compatible, 6to4, Teredo (serveur et client)."""

    if address.version != 6:
        return []
    found = [item for item in (address.ipv4_mapped, address.sixtofour) if item is not None]
    if address.teredo is not None:
        found.extend(address.teredo)
    if any(address in net for net in _IPV4_EMBEDDING_NETWORKS) and address != ipaddress.IPv6Address("::"):
        found.append(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF))
    return found


def parse_ipv4_like(host: str) -> ipaddress.IPv4Address | None:
    """Décode un hôte qui ressemble à une IPv4 comme `inet_aton` (et WHATWG) le feraient.

    `None` si l'hôte n'en a pas l'air (dernier label non numérique). Lève
    `mcp_endpoint_invalid` si l'hôte a l'air numérique mais ne décode pas.
    """

    labels = host.rstrip(".").split(".")
    if not labels or not _IPV4_PART.fullmatch(labels[-1]):
        return None
    if len(labels) > 4 or not all(_IPV4_PART.fullmatch(label) for label in labels):
        raise _invalid("the host looks like an IPv4 address but is not one")
    values = []
    for label in labels:
        if label[:2] in ("0x", "0X"):
            values.append(int(label[2:] or "0", 16))
        elif len(label) > 1 and label.startswith("0"):
            if any(ch in "89" for ch in label):
                raise _invalid("the host looks like an octal IPv4 address but is not one")
            values.append(int(label, 8))
        else:
            values.append(int(label))
    *head, last = values
    if any(value > 255 for value in head) or last >= 256 ** (5 - len(values)):
        raise _invalid("the host looks like an IPv4 address but is out of range")
    number = last
    for index, value in enumerate(head):
        number += value << (8 * (3 - index))
    return ipaddress.IPv4Address(number)


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
    if "%" in host:
        raise _invalid("percent-encoded or zone-scoped hosts are not allowed")
    host = _ascii_host(host).lower().rstrip(".")
    if not host:
        raise _invalid("a host is required")
    if port == 0:
        raise _invalid("port 0 is not a valid port")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is None:
        numeric = parse_ipv4_like(host)
        if numeric is not None:
            if is_forbidden_address(numeric):
                raise _forbidden("the host is a disguised private or reserved IPv4 address")
            raise _invalid(f"write the IPv4 address in dotted form ({numeric})")
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
