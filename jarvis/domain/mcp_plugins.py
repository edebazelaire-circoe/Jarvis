"""Contrat pur des plugins MCP distants (handoff jarvis-generic-mcp-plugin-runtime, Slice 02).

Un **plugin** est un serveur MCP distant que l'utilisateur ajoute par son URL.
Core en garde la définition (ce module), l'autorisation (coffre scellé,
`jarvis/core/credential_vault.py`) et, à partir de la Slice 03, la connexion.
Contrat canonique : `docs/mcp/plugins.md` §2 (modèle, états, transitions) et
§8.2 (codes stables) ; conception : ARCH §3.1 et §9.

Invariants portés ici :

- `plugin_id` est un slug stable, jamais `jarvis-*` (espace des serveurs
  natifs), immuable après création ;
- deux axes indépendants : `enabled` (choix de l'utilisateur) et
  `connection_status`/`auth_status` (ce qui est vrai sur le fil). Activer ou
  désactiver ne touche jamais la connexion ; déconnecter ne touche jamais
  `enabled` ;
- `credential_ref` est une référence opaque `cred_<32 hex>`, jamais un secret,
  et n'apparaît jamais dans `public_view()` (forme de toute réponse API/UI) ;
- `last_error_code` est un code stable de `McpErrorCode`, jamais un texte
  distant ;
- toute chaîne et toute collection est bornée ; la validation refuse, elle ne
  tronque pas.

Pur : aucune E/S, aucune horloge implicite (chaque transition reçoit `now`).

Slice 03 : `ExternalToolDescriptor` et `normalize_remote_tools` (ARCH §6.2) —
`tools` stocke la forme JSON (`to_payload()`) des descripteurs normalisés ;
identité du serveur bornée (`server_identity_from`), transitions de
connexion, règles pures d'échéance OAuth et de vérification `iss` (RFC 9207).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
import json
import re
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from jarvis.domain._checks import preview

# ------------------------------------------------------------------ constantes

PLUGIN_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
MAX_PLUGIN_ID_CHARS = 32
#: Préfixe réservé aux serveurs natifs (`jarvis-display`, `jarvis-tools`...).
RESERVED_PLUGIN_ID_PREFIX = "jarvis-"
#: Remplaçant d'un préfixe réservé (D3) : `jarvis-x` devient `p-jarvis-x`.
RESERVED_PREFIX_REPLACEMENT = "p-"
FALLBACK_PLUGIN_ID = "plugin"
MAX_DISPLAY_NAME_CHARS = 64
MAX_ENDPOINT_CHARS = 2048
MAX_ICON_URL_CHARS = 512
CREDENTIAL_REF_PATTERN = re.compile(r"cred_[0-9a-f]{32}")
TRANSPORT_STREAMABLE_HTTP = "streamable_http"
#: Bornes de la liste d'outils découverte (ARCH §6.2) et des refus d'ingestion.
MAX_PLUGIN_TOOLS = 200
MAX_REJECTED_TOOLS = 200
MAX_TOOL_NAME_CHARS = 128
MAX_SERVER_IDENTITY_FIELD_CHARS = 128
#: Texte distant réinjecté (erreur d'outil) : borne de `mcp_remote_tool_error`.
MAX_REMOTE_ERROR_BYTES = 4096
REDACTED = "[secret masqué]"


# ------------------------------------------------------------------ erreurs


class McpErrorCode(StrEnum):
    """Codes stables de `docs/mcp/plugins.md` §8.2 (ARCH §9)."""

    PLUGIN_UNKNOWN = "mcp_plugin_unknown"
    PLUGIN_DUPLICATE = "mcp_plugin_duplicate"
    #: Champ ou corps refusé (nom affiché trop long, en-tête interdit...).
    #: Ajout Slice 02 : ARCH §9 ne nommait aucun code pour un champ invalide.
    PLUGIN_INVALID = "mcp_plugin_invalid"
    #: Panne locale de la tâche de connexion (bogue de Jarvis, pas le registre ni le serveur distant).
    #: Ajout rework QA Slice 03 (ARCH §16 E18).
    INTERNAL_ERROR = "mcp_plugin_internal_error"
    ENDPOINT_INVALID = "mcp_endpoint_invalid"
    ENDPOINT_FORBIDDEN = "mcp_endpoint_forbidden"
    VAULT_UNAVAILABLE = "mcp_vault_unavailable"
    CONNECTOR_UNAVAILABLE = "mcp_connector_unavailable"
    PLUGIN_DISABLED = "mcp_plugin_disabled"
    PLUGIN_DISCONNECTED = "mcp_plugin_disconnected"
    REAUTHORIZATION_REQUIRED = "mcp_plugin_reauthorization_required"
    OAUTH_STATE_INVALID = "mcp_oauth_state_invalid"
    OAUTH_ISSUER_MISMATCH = "mcp_oauth_issuer_mismatch"
    OAUTH_DENIED = "mcp_oauth_denied"
    TRANSPORT_UNSUPPORTED = "mcp_transport_unsupported"
    REMOTE_UNREACHABLE = "mcp_remote_unreachable"
    REMOTE_TLS = "mcp_remote_tls"
    REMOTE_PROTOCOL = "mcp_remote_protocol"
    RESPONSE_TOO_LARGE = "mcp_response_too_large"
    REMOTE_TIMEOUT = "mcp_remote_timeout"
    REMOTE_TOOL_ERROR = "mcp_remote_tool_error"
    TOOL_UNKNOWN = "mcp_tool_unknown"
    NATIVE_TOOL_CALL_DIRECTLY = "native_tool_call_directly"
    ARGUMENTS_INVALID = "mcp_arguments_invalid"
    CURSOR_INVALID = "mcp_cursor_invalid"
    TOOL_NAME_INVALID = "mcp_tool_name_invalid"
    TOOL_SCHEMA_TOO_LARGE = "mcp_tool_schema_too_large"
    TOOL_LIST_TOO_LARGE = "mcp_tool_list_too_large"


#: Statut HTTP de chaque code. Les refus d'ingestion n'ont pas de réponse HTTP
#: (ils vivent dans `rejected_tools`) ; 400 n'est qu'une valeur de repli.
HTTP_STATUS: Mapping[McpErrorCode, int] = MappingProxyType({
    McpErrorCode.PLUGIN_UNKNOWN: 404,
    McpErrorCode.PLUGIN_DUPLICATE: 409,
    McpErrorCode.PLUGIN_INVALID: 400,
    McpErrorCode.INTERNAL_ERROR: 500,
    McpErrorCode.ENDPOINT_INVALID: 400,
    McpErrorCode.ENDPOINT_FORBIDDEN: 400,
    McpErrorCode.VAULT_UNAVAILABLE: 409,
    McpErrorCode.CONNECTOR_UNAVAILABLE: 503,
    McpErrorCode.PLUGIN_DISABLED: 409,
    McpErrorCode.PLUGIN_DISCONNECTED: 409,
    McpErrorCode.REAUTHORIZATION_REQUIRED: 409,
    McpErrorCode.OAUTH_STATE_INVALID: 400,
    McpErrorCode.OAUTH_ISSUER_MISMATCH: 400,
    McpErrorCode.OAUTH_DENIED: 400,
    McpErrorCode.TRANSPORT_UNSUPPORTED: 502,
    McpErrorCode.REMOTE_UNREACHABLE: 502,
    McpErrorCode.REMOTE_TLS: 502,
    McpErrorCode.REMOTE_PROTOCOL: 502,
    McpErrorCode.RESPONSE_TOO_LARGE: 502,
    McpErrorCode.REMOTE_TIMEOUT: 504,
    McpErrorCode.REMOTE_TOOL_ERROR: 200,
    McpErrorCode.TOOL_UNKNOWN: 404,
    McpErrorCode.NATIVE_TOOL_CALL_DIRECTLY: 400,
    McpErrorCode.ARGUMENTS_INVALID: 400,
    McpErrorCode.CURSOR_INVALID: 400,
    McpErrorCode.TOOL_NAME_INVALID: 400,
    McpErrorCode.TOOL_SCHEMA_TOO_LARGE: 400,
    McpErrorCode.TOOL_LIST_TOO_LARGE: 400,
})


class McpPluginError(ValueError):
    """Refus nommé du contrat des plugins : `code` stable, `status` HTTP.

    Même forme que `BoardError` : le message est une phrase Jarvis lue telle
    quelle dans le Control Center ; il ne contient **jamais** de secret (une
    valeur d'identifiant refusée n'est pas recopiée).
    """

    def __init__(self, code: McpErrorCode | str, message: str) -> None:
        super().__init__(message)
        self.code = McpErrorCode(code)
        self.status = HTTP_STATUS[self.code]


def _fail(message: str, code: McpErrorCode = McpErrorCode.PLUGIN_INVALID) -> McpPluginError:
    return McpPluginError(code, message)


# ------------------------------------------------------------------ énumérations


class AuthStrategy(StrEnum):
    NONE = "none"
    OAUTH = "oauth"
    BEARER = "bearer"
    HEADER = "header"


#: Stratégies saisies à la main (`PUT …/credential`).
STATIC_STRATEGIES = frozenset({AuthStrategy.BEARER, AuthStrategy.HEADER})


class ConnectionStatus(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class AuthStatus(StrEnum):
    UNKNOWN = "unknown"
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"
    AUTHORIZING = "authorizing"
    AUTHORIZED = "authorized"
    EXPIRED = "expired"
    FAILED = "failed"


# ------------------------------------------------------------------ valeur


@dataclass(frozen=True, slots=True)
class McpPlugin:
    """Plugin MCP géré. Voir `docs/mcp/plugins.md` §2.1."""

    plugin_id: str
    display_name: str
    endpoint: str
    endpoint_origin: str
    created_at: datetime
    updated_at: datetime
    transport: str = TRANSPORT_STREAMABLE_HTTP
    enabled: bool = True
    connection_status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    auth_status: AuthStatus = AuthStatus.UNKNOWN
    auth_strategy: AuthStrategy = AuthStrategy.NONE
    credential_ref: str | None = None
    icon_url: str | None = None
    server_identity: Mapping[str, str] | None = None
    capability_revision: int = 0
    tools: tuple[Mapping[str, Any], ...] = ()
    rejected_tools: tuple[Mapping[str, str], ...] = ()
    last_discovered_at: datetime | None = None
    last_error_code: McpErrorCode | None = None

    def __post_init__(self) -> None:
        check_plugin_id(self.plugin_id)
        check_display_name(self.display_name)
        _check_url("endpoint", self.endpoint, MAX_ENDPOINT_CHARS)
        _check_url("endpoint_origin", self.endpoint_origin, MAX_ENDPOINT_CHARS)
        if origin_of(self.endpoint) != self.endpoint_origin:
            raise _fail("endpoint_origin does not match endpoint")
        if self.transport != TRANSPORT_STREAMABLE_HTTP:
            raise _fail(f"transport must be {TRANSPORT_STREAMABLE_HTTP}", McpErrorCode.TRANSPORT_UNSUPPORTED)
        if type(self.enabled) is not bool:
            raise _fail("enabled must be a boolean")
        for name, enum in (("connection_status", ConnectionStatus), ("auth_status", AuthStatus),
                           ("auth_strategy", AuthStrategy)):
            if not isinstance(getattr(self, name), enum):
                raise _fail(f"{name} must be a {enum.__name__}")
        if self.credential_ref is not None and not (
                isinstance(self.credential_ref, str) and CREDENTIAL_REF_PATTERN.fullmatch(self.credential_ref)):
            raise _fail("credential_ref must be an opaque cred_<32 hex> reference")
        if self.icon_url is not None:
            _check_url("icon_url", self.icon_url, MAX_ICON_URL_CHARS)
            if not self.icon_url.startswith("https://"):
                raise _fail("icon_url must be an https URL")
        for name in ("created_at", "updated_at"):
            _check_aware(name, getattr(self, name))
        if self.last_discovered_at is not None:
            _check_aware("last_discovered_at", self.last_discovered_at)
        if self.updated_at < self.created_at:
            raise _fail("updated_at cannot be before created_at")
        if type(self.capability_revision) is not int or self.capability_revision < 0:
            raise _fail("capability_revision must be a non-negative integer")
        if self.last_error_code is not None and not isinstance(self.last_error_code, McpErrorCode):
            raise _fail("last_error_code must be a stable McpErrorCode")
        object.__setattr__(self, "server_identity", _freeze_identity(self.server_identity))
        object.__setattr__(self, "tools", _freeze_tools(self.tools))
        object.__setattr__(self, "rejected_tools", _freeze_rejections(self.rejected_tools))

    # ------------------------------------------------------------- codec

    def to_payload(self) -> dict[str, Any]:
        """Forme canonique stockée (`mcp_plugins.data`). Contient `credential_ref` : jamais en réponse."""

        return {
            "plugin_id": self.plugin_id,
            "display_name": self.display_name,
            "endpoint": self.endpoint,
            "endpoint_origin": self.endpoint_origin,
            "transport": self.transport,
            "enabled": self.enabled,
            "connection_status": self.connection_status.value,
            "auth_status": self.auth_status.value,
            "auth_strategy": self.auth_strategy.value,
            "credential_ref": self.credential_ref,
            "icon_url": self.icon_url,
            "server_identity": None if self.server_identity is None else dict(self.server_identity),
            "capability_revision": self.capability_revision,
            "tools": [_thaw(tool) for tool in self.tools],
            "rejected_tools": [dict(item) for item in self.rejected_tools],
            "last_discovered_at": _iso(self.last_discovered_at),
            "last_error_code": None if self.last_error_code is None else self.last_error_code.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def public_view(self) -> dict[str, Any]:
        """Forme UI/API : tout sauf `credential_ref` (`docs/mcp/plugins.md` §2.1)."""

        view = self.to_payload()
        del view["credential_ref"]
        return view

    @classmethod
    def from_payload(cls, payload: object) -> McpPlugin:
        """Décodage strict : clés exactes, types exacts, aucune valeur par défaut devinée."""

        if not isinstance(payload, dict):
            raise _fail("plugin payload must be an object")
        unknown = sorted(str(key)[:40] for key in payload if key not in PAYLOAD_KEYS)
        if unknown:
            raise _fail(f"plugin payload has unknown fields: {unknown[:5]}")
        missing = sorted(PAYLOAD_KEYS - payload.keys())
        if missing:
            raise _fail(f"plugin payload is missing fields: {missing}")
        error = payload["last_error_code"]
        tools = payload["tools"]
        rejected = payload["rejected_tools"]
        if not isinstance(tools, list) or not isinstance(rejected, list):
            raise _fail("tools and rejected_tools must be lists")
        return cls(
            plugin_id=payload["plugin_id"],
            display_name=payload["display_name"],
            endpoint=payload["endpoint"],
            endpoint_origin=payload["endpoint_origin"],
            transport=payload["transport"],
            enabled=payload["enabled"],
            connection_status=_parse_enum("connection_status", payload["connection_status"], ConnectionStatus),
            auth_status=_parse_enum("auth_status", payload["auth_status"], AuthStatus),
            auth_strategy=_parse_enum("auth_strategy", payload["auth_strategy"], AuthStrategy),
            credential_ref=payload["credential_ref"],
            icon_url=payload["icon_url"],
            server_identity=payload["server_identity"],
            capability_revision=payload["capability_revision"],
            tools=tuple(tools),
            rejected_tools=tuple(rejected),
            last_discovered_at=_parse_dt("last_discovered_at", payload["last_discovered_at"], required=False),
            last_error_code=None if error is None else _parse_enum("last_error_code", error, McpErrorCode),
            created_at=_parse_dt("created_at", payload["created_at"]),
            updated_at=_parse_dt("updated_at", payload["updated_at"]),
        )


PAYLOAD_KEYS = frozenset({
    "plugin_id", "display_name", "endpoint", "endpoint_origin", "transport", "enabled", "connection_status",
    "auth_status", "auth_strategy", "credential_ref", "icon_url", "server_identity", "capability_revision",
    "tools", "rejected_tools", "last_discovered_at", "last_error_code", "created_at", "updated_at",
})
_IDENTITY_KEYS = frozenset({"name", "version", "protocol_version"})


# ------------------------------------------------------------------ contrôles


def check_plugin_id(value: object) -> str:
    if not isinstance(value, str) or not PLUGIN_ID_PATTERN.fullmatch(value):
        raise _fail(f"plugin_id must match ^[a-z0-9][a-z0-9-]{{0,31}}$: {preview(value)}")
    if value.startswith(RESERVED_PLUGIN_ID_PREFIX):
        raise _fail(f"plugin_id may not start with {RESERVED_PLUGIN_ID_PREFIX!r} (native servers)")
    return value


def check_display_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise _fail("display_name must be a non-empty text without surrounding spaces")
    if len(value) > MAX_DISPLAY_NAME_CHARS:
        raise _fail(f"display_name exceeds {MAX_DISPLAY_NAME_CHARS} characters ({len(value)})")
    if not value.isprintable():
        raise _fail("display_name must be a single printable line")
    return value


def _check_url(name: str, value: object, limit: int) -> None:
    if not isinstance(value, str) or not value:
        raise _fail(f"{name} must be a non-empty string")
    if len(value) > limit:
        raise _fail(f"{name} exceeds {limit} characters")
    if not value.isascii() or not value.isprintable() or " " in value:
        raise _fail(f"{name} must be a printable ASCII URL")


def _check_aware(name: str, value: object) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _fail(f"{name} must be a timezone-aware datetime")


def _bounded_text(name: str, value: object, limit: int) -> str:
    if not isinstance(value, str) or len(value) > limit or not value.isprintable():
        raise _fail(f"{name} must be a printable string of at most {limit} characters")
    return value


def _freeze_identity(value: object) -> Mapping[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or not set(value) <= _IDENTITY_KEYS:
        raise _fail("server_identity must be an object with name, version, protocol_version only")
    return MappingProxyType({key: _bounded_text(f"server_identity.{key}", item, MAX_SERVER_IDENTITY_FIELD_CHARS)
                             for key, item in value.items()})


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise _fail(f"tool descriptors must be JSON values, not {type(value).__name__}")


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _freeze_tools(value: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (tuple, list)):
        raise _fail("tools must be a sequence")
    if len(value) > MAX_PLUGIN_TOOLS:
        raise _fail(f"tools exceed {MAX_PLUGIN_TOOLS} entries", McpErrorCode.TOOL_LIST_TOO_LARGE)
    frozen = []
    for tool in value:
        if not isinstance(tool, Mapping):
            raise _fail("each tool must be an object")
        frozen.append(_freeze_json(tool))
    return tuple(frozen)


def _freeze_rejections(value: object) -> tuple[Mapping[str, str], ...]:
    if not isinstance(value, (tuple, list)):
        raise _fail("rejected_tools must be a sequence")
    if len(value) > MAX_REJECTED_TOOLS:
        raise _fail(f"rejected_tools exceed {MAX_REJECTED_TOOLS} entries")
    frozen = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"name", "code"}:
            raise _fail("each rejected tool must be {name, code}")
        name = _bounded_text("rejected_tools.name", item["name"], MAX_TOOL_NAME_CHARS)
        code = _parse_enum("rejected_tools.code", item["code"], McpErrorCode).value
        frozen.append(MappingProxyType({"name": name, "code": code}))
    return tuple(frozen)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _parse_dt(name: str, raw: object, *, required: bool = True) -> datetime | None:
    if raw is None and not required:
        return None
    if not isinstance(raw, str):
        raise _fail(f"{name} must be an ISO 8601 string")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        raise _fail(f"{name} is not ISO 8601: {preview(raw)}") from None


def _parse_enum(name: str, raw: object, enum: type[StrEnum]) -> Any:
    try:
        return enum(raw)
    except ValueError:
        raise _fail(f"{name} is not a {enum.__name__}: {preview(raw)}") from None


# ------------------------------------------------------------------ identité


def origin_of(endpoint: str) -> str:
    """`scheme://host[:port]` d'une URL déjà normalisée (`validate_endpoint`)."""

    parts = urlsplit(endpoint)
    return f"{parts.scheme}://{parts.netloc}"


def plugin_id_for(endpoint: str, taken: Iterable[str]) -> str:
    """Slug stable d'un endpoint normalisé (D3, `docs/mcp/plugins.md` §2.1).

    Premier label DNS de l'hôte, en minuscules, `[^a-z0-9-]` → `-`, tronqué à
    32 ; un préfixe `jarvis-` devient `p-jarvis-…` ; collision → `-2`, `-3`…
    """

    host = (urlsplit(endpoint).hostname or "").lower()
    label = host.split(".")[0] if ":" not in host else host  # IPv6 littéral : pas de label DNS
    base = re.sub(r"[^a-z0-9-]", "-", label).lstrip("-")[:MAX_PLUGIN_ID_CHARS] or FALLBACK_PLUGIN_ID
    if base.startswith(RESERVED_PLUGIN_ID_PREFIX):
        base = (RESERVED_PREFIX_REPLACEMENT + base)[:MAX_PLUGIN_ID_CHARS]
    used = set(taken)
    candidate, counter = base, 1
    while candidate in used:
        counter += 1
        suffix = f"-{counter}"
        candidate = base[:MAX_PLUGIN_ID_CHARS - len(suffix)] + suffix
    return check_plugin_id(candidate)


def default_display_name(endpoint: str) -> str:
    """Nom par défaut avant tout `initialize` : l'hôte (ARCH §3.1)."""

    return (urlsplit(endpoint).hostname or FALLBACK_PLUGIN_ID)[:MAX_DISPLAY_NAME_CHARS]


def new_plugin(endpoint: str, *, plugin_id: str, display_name: str | None, now: datetime) -> McpPlugin:
    """Plugin neuf : activé, déconnecté, authentification inconnue, sans identifiant."""

    name = display_name.strip() if isinstance(display_name, str) else display_name
    return McpPlugin(
        plugin_id=plugin_id,
        display_name=name or default_display_name(endpoint),
        endpoint=endpoint,
        endpoint_origin=origin_of(endpoint),
        created_at=now,
        updated_at=now,
    )


# ------------------------------------------------------------------ transitions (pures)


def _touch(plugin: McpPlugin, now: datetime, **changes: Any) -> McpPlugin:
    return replace(plugin, updated_at=max(now, plugin.updated_at), **changes)


def set_enabled(plugin: McpPlugin, enabled: bool, *, now: datetime) -> McpPlugin:
    """Activer/désactiver : ne touche **jamais** connexion ni authentification (intention verrouillée 2)."""

    if type(enabled) is not bool:
        raise _fail("enabled must be a boolean")
    return plugin if plugin.enabled is enabled else _touch(plugin, now, enabled=enabled)


def rename(plugin: McpPlugin, display_name: str, *, now: datetime) -> McpPlugin:
    name = display_name.strip() if isinstance(display_name, str) else display_name
    check_display_name(name)
    return plugin if plugin.display_name == name else _touch(plugin, now, display_name=name)


def attach_credential(plugin: McpPlugin, *, strategy: AuthStrategy, credential_ref: str,
                      now: datetime) -> McpPlugin:
    """Identifiant scellé posé : la stratégie change, l'état d'autorisation redevient inconnu.

    Rien n'est vérifié sur le fil ici : c'est le prochain `connect` (Slice 03)
    qui dira `authorized` ou `failed`.
    """

    return _touch(plugin, now, auth_strategy=AuthStrategy(strategy), credential_ref=credential_ref,
                  auth_status=AuthStatus.UNKNOWN, last_error_code=None)


def disconnect(plugin: McpPlugin, *, now: datetime) -> McpPlugin:
    """Session fermée **et** identifiants oubliés ; `enabled` et la ligne restent (§2.2)."""

    return _touch(plugin, now, connection_status=ConnectionStatus.DISCONNECTED, auth_status=AuthStatus.UNKNOWN,
                  auth_strategy=AuthStrategy.NONE, credential_ref=None, last_error_code=None)


def reset_interrupted_connect(plugin: McpPlugin, *, now: datetime) -> McpPlugin:
    """Démarrage de Core : un `connecting` laissé par un arrêt brutal redevient `disconnected`."""

    if plugin.connection_status is not ConnectionStatus.CONNECTING:
        return plugin
    return _touch(plugin, now, connection_status=ConnectionStatus.DISCONNECTED)


def mark_connection(plugin: McpPlugin, status: ConnectionStatus, *, now: datetime,
                    auth_status: AuthStatus | None = None, error_code: McpErrorCode | None = None) -> McpPlugin:
    """État du fil (Slice 03) : ne touche jamais `enabled`."""

    changes: dict[str, Any] = {"connection_status": ConnectionStatus(status), "last_error_code": error_code}
    if auth_status is not None:
        changes["auth_status"] = AuthStatus(auth_status)
    return _touch(plugin, now, **changes)


# ------------------------------------------------------------------ masquage


_BEARER = re.compile(r"Bearer\s+(?!\[secret masqué\])\S+", re.IGNORECASE)
_JWT = re.compile(r"[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}")
_AUTH_SCHEMES = r"(?:basic|bearer|digest|negotiate|ntlm|token)"
#: `Authorization: Basic …` (et tout autre schéma) : la valeur, le schéma reste lisible (QA Slice 04).
_AUTHORIZATION = re.compile(
    r"""((?:proxy-)?authorization["']?\s*[:=]\s*["']?(?:""" + _AUTH_SCHEMES + r"""\s+)?)"""
    r"""(?!\[secret masqué\]|""" + _AUTH_SCHEMES + r"""\s)[^\s"',;]+""", re.IGNORECASE)
#: `Cookie:` / `Set-Cookie:` : toute la valeur de l'en-tête, jusqu'à la fin de ligne (QA Slice 04).
_COOKIE = re.compile(r"""((?:set-)?cookie["']?\s*[:=]\s*["']?)(?!\[secret masqué\])[^\s"'][^\r\n"']*""", re.IGNORECASE)
#: Clés dont la valeur est un identifiant : `token=…`, `"api_key": "…"`, `password: …` (Slice 04),
#: puis `sig=` / `signature=` / `X-Amz-Signature=` / `X-Amz-Credential=` (QA Slice 04).
_CREDENTIAL_KEYS = (r"""(?:access_|refresh_|id_)?token|secret|client_secret|password|passwd|api[_-]?key|apikey"""
                    r"""|signature|(?<![a-z0-9])sig|x-amz-credential|x-amz-security-token""")
#: Une valeur entre guillemets est masquée entière, espaces compris (`"token": "abc def"`).
_CREDENTIAL_PAIR = re.compile(
    r"""(""" + _CREDENTIAL_KEYS + r""")(["']?\s*[:=]\s*)"""
    r"""(?:"(?!\[secret masqué\]")(?:[^"\\]|\\.)+"|'(?!\[secret masqué\]')[^']+'"""
    r"""|(?!\[secret masqué\])[^\s"'&,;]+)""", re.IGNORECASE)
#: `session=…` seulement sous la forme `=` (« session : ouverte » reste lisible).
_SESSION_PAIR = re.compile(r"""((?<![a-z0-9])session(?:_?id)?=)(?!\[secret masqué\])[^\s"'&,;]+""", re.IGNORECASE)
#: Clé JSON qui nomme un identifiant : sa valeur chaîne est masquée entière dans un résultat structuré.
_CREDENTIAL_KEY = re.compile(r"""(?:""" + _CREDENTIAL_KEYS + r"""|session(?:_?id)?|(?:set-)?cookie|authorization)""",
                             re.IGNORECASE)


def _masked_pair(match: re.Match[str]) -> str:
    value = match.group(0)[len(match.group(1)) + len(match.group(2)):]
    quote = value[0] if value[:1] in ("'", '"') else ""
    return f"{match.group(1)}{match.group(2)}{quote}{REDACTED}{quote}"


def redact(text: str, known_secrets: Iterable[str] = ()) -> str:
    """Masque tout secret connu du plugin, tout `Bearer …`, toute forme JWT (ARCH §9), la valeur d'un
    en-tête `Authorization` (tout schéma), `Cookie` / `Set-Cookie`, `session=`, et toute valeur d'une paire
    `clé=valeur` dont la clé nomme un identifiant (`token`, `password`, `api_key`, `sig`, `signature`,
    `X-Amz-Credential`…) ; une valeur entre guillemets est masquée entière. Jamais deux fois.

    Les secrets connus passent d'abord, du plus long au plus court, pour qu'un
    secret contenu dans un autre ne laisse pas de fragment visible.
    """

    for secret in sorted({s for s in known_secrets if isinstance(s, str) and s}, key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    text = _BEARER.sub(f"Bearer {REDACTED}", text)
    text = _JWT.sub(REDACTED, text)
    text = _AUTHORIZATION.sub(lambda match: f"{match.group(1)}{REDACTED}", text)
    text = _COOKIE.sub(lambda match: f"{match.group(1)}{REDACTED}", text)
    text = _SESSION_PAIR.sub(lambda match: f"{match.group(1)}{REDACTED}", text)
    return _CREDENTIAL_PAIR.sub(_masked_pair, text)


def redact_structured(value: Any, known_secrets: Iterable[str] = ()) -> Any:
    """Copie de `value` (JSON déjà analysé) dont chaque chaîne passe par `redact` ; une chaîne rangée
    sous une clé qui nomme un identifiant (`access_token`, `password`, `cookie`…) est masquée entière.
    Les clés et la structure restent : le résultat est toujours du JSON valide."""

    secrets = [secret for secret in known_secrets if isinstance(secret, str) and secret]
    if isinstance(value, str):
        return redact(value, secrets)
    if isinstance(value, Mapping):
        return {key: (REDACTED if isinstance(item, str) and item and isinstance(key, str)
                      and _CREDENTIAL_KEY.fullmatch(key) else redact_structured(item, secrets))
                for key, item in value.items()}
    if isinstance(value, list):
        return [redact_structured(item, secrets) for item in value]
    return value


def canonical_json(payload: Mapping[str, Any]) -> str:
    """Encodage canonique partagé par le magasin (`data`) et le coffre (charge scellée)."""

    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


# ------------------------------------------------------------------ outils distants (Slice 03, ARCH §6.2)

TOOL_WIRE_NAME_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,128}")
MAX_TOOL_TITLE_CHARS = 80
MAX_TOOL_DESCRIPTION_BYTES = 4096
TRUNCATION_SUFFIX = " …[tronqué]"
MAX_TOOL_SCHEMA_BYTES = 16 * 1024
MAX_TOOL_SCHEMA_DEPTH = 12
#: Somme des descripteurs normalisés d'un plugin (JSON compact, UTF-8).
MAX_PLUGIN_TOOLS_BYTES = 512 * 1024
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class ExternalToolDescriptor:
    """Outil d'un plugin, normalisé et borné (données distantes non fiables, `docs/mcp/plugins.md` §5.1)."""

    tool_id: str
    plugin_id: str
    name: str
    title: str | None
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any] | None
    side_effect: str
    idempotent: bool
    open_world: bool
    atomicity: str = "external"

    def to_payload(self) -> dict[str, Any]:
        return {"tool_id": self.tool_id, "plugin_id": self.plugin_id, "name": self.name, "title": self.title,
                "description": self.description, "input_schema": _thaw(self.input_schema),
                "output_schema": None if self.output_schema is None else _thaw(self.output_schema),
                "side_effect": self.side_effect, "idempotent": self.idempotent, "atomicity": self.atomicity,
                "open_world": self.open_world}


@dataclass(frozen=True, slots=True)
class ToolRejection:
    name: str
    code: McpErrorCode

    def to_payload(self) -> dict[str, str]:
        return {"name": self.name, "code": self.code.value}


def _compact(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _depth(value: Any) -> int:
    if isinstance(value, Mapping):
        return 1 + max((_depth(item) for item in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((_depth(item) for item in value), default=0)
    return 0


def _clean_line(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = _CONTROL_CHARS.sub("", value).strip()
    return text[:limit] or None


def bound_description(text: object) -> str:
    """≤ 4 096 octets UTF-8, suffixe ` …[tronqué]` **compris** (ARCH §16 E7), coupe sur un caractère."""

    if not isinstance(text, str):
        return ""
    raw = text.encode("utf-8")
    if len(raw) <= MAX_TOOL_DESCRIPTION_BYTES:
        return text
    budget = MAX_TOOL_DESCRIPTION_BYTES - len(TRUNCATION_SUFFIX.encode("utf-8"))
    return raw[:budget].decode("utf-8", errors="ignore") + TRUNCATION_SUFFIX


def _hint(annotations: Mapping[str, Any], key: str) -> bool | None:
    value = annotations.get(key)
    return value if isinstance(value, bool) else None


def _display_tool_name(raw: Mapping[str, Any]) -> str:
    """Nom lisible d'un outil refusé pour `rejected_tools` (borné, imprimable)."""

    name = raw.get("name")
    text = _CONTROL_CHARS.sub("", name) if isinstance(name, str) else ""
    text = "".join(ch for ch in text if ch.isprintable())
    return text[:MAX_TOOL_NAME_CHARS] or "?"


def _schema_fits(schema: Mapping[str, Any]) -> bool:
    return len(_compact(schema)) <= MAX_TOOL_SCHEMA_BYTES and _depth(schema) <= MAX_TOOL_SCHEMA_DEPTH


def normalize_remote_tool(plugin_id: str, raw: object) -> ExternalToolDescriptor | ToolRejection:
    """Un outil `tools/list` brut ⇒ descripteur borné, ou refus avec un code stable (ARCH §6.2)."""

    if not isinstance(raw, Mapping):
        return ToolRejection("?", McpErrorCode.TOOL_NAME_INVALID)
    name = raw.get("name")
    if not isinstance(name, str) or not TOOL_WIRE_NAME_PATTERN.fullmatch(name):
        return ToolRejection(_display_tool_name(raw), McpErrorCode.TOOL_NAME_INVALID)
    schema = raw.get("inputSchema")
    if not isinstance(schema, Mapping) or schema.get("type", "object") != "object" or not _schema_fits(schema):
        return ToolRejection(name, McpErrorCode.TOOL_SCHEMA_TOO_LARGE)
    output = raw.get("outputSchema")
    if not isinstance(output, Mapping) or not _schema_fits(output):
        output = None
    annotations = raw.get("annotations") if isinstance(raw.get("annotations"), Mapping) else {}
    if _hint(annotations, "readOnlyHint") is True:
        side_effect = "read"
    elif _hint(annotations, "destructiveHint") is False:
        side_effect = "write"
    else:
        side_effect = "destructive"  # MCP default: an unannotated tool may destroy
    open_world = _hint(annotations, "openWorldHint")
    return ExternalToolDescriptor(
        tool_id=f"{plugin_id}.{name}", plugin_id=plugin_id, name=name,
        title=_clean_line(raw.get("title"), MAX_TOOL_TITLE_CHARS)
        or _clean_line(annotations.get("title"), MAX_TOOL_TITLE_CHARS),
        description=bound_description(raw.get("description")),
        input_schema=_freeze_json(dict(schema)),
        output_schema=None if output is None else _freeze_json(dict(output)),
        side_effect=side_effect, idempotent=_hint(annotations, "idempotentHint") is True,
        open_world=True if open_world is None else open_world,
    )


def normalize_remote_tools(plugin_id: str, raws: Iterable[object]) -> tuple[
        tuple[dict[str, Any], ...], tuple[dict[str, str], ...]]:
    """Liste distante ⇒ (descripteurs JSON acceptés, refus `{name, code}`), bornes du plugin appliquées.

    ≤ 200 outils et ≤ 512 Kio de descripteurs ; au-delà `mcp_tool_list_too_large`.
    Doublon de nom : le second est refusé (`mcp_tool_name_invalid`). Les refus
    sont eux-mêmes bornés à `MAX_REJECTED_TOOLS` entrées.
    """

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    names: set[str] = set()
    used = 0
    for raw in raws:
        result = normalize_remote_tool(plugin_id, raw)
        if isinstance(result, ExternalToolDescriptor):
            if result.name in names:
                result = ToolRejection(result.name, McpErrorCode.TOOL_NAME_INVALID)
            else:
                payload = result.to_payload()
                size = len(_compact(payload))
                if len(accepted) >= MAX_PLUGIN_TOOLS or used + size > MAX_PLUGIN_TOOLS_BYTES:
                    result = ToolRejection(result.name, McpErrorCode.TOOL_LIST_TOO_LARGE)
                else:
                    names.add(result.name)
                    used += size
                    accepted.append(payload)
                    continue
        if len(rejected) < MAX_REJECTED_TOOLS:
            rejected.append(result.to_payload())
    return tuple(accepted), tuple(rejected)


# ------------------------------------------------------------------ identité du serveur et connexion (Slice 03)


def server_identity_from(raw: Mapping[str, Any]) -> dict[str, str]:
    """`{name, version, protocol_version}` d'un `initialize`, nettoyés et bornés (jamais refusés)."""

    identity = {}
    for key in ("name", "version", "protocol_version"):
        value = _clean_line(raw.get(key), MAX_SERVER_IDENTITY_FIELD_CHARS)
        if value is not None:
            value = "".join(ch for ch in value if ch.isprintable())
        if value:
            identity[key] = value
    return identity


def icon_url_from(raw: object) -> str | None:
    """Icône https bornée annoncée par le serveur ; jamais récupérée par Core."""

    if (isinstance(raw, str) and raw.startswith("https://") and len(raw) <= MAX_ICON_URL_CHARS
            and raw.isascii() and raw.isprintable() and " " not in raw):
        return raw
    return None


def mark_connected(plugin: McpPlugin, *, now: datetime, identity: Mapping[str, str], icon_url: str | None,
                   auth_strategy: AuthStrategy, auth_status: AuthStatus,
                   tools: tuple[Mapping[str, Any], ...], rejected: tuple[Mapping[str, str], ...]) -> McpPlugin:
    """Connexion établie : identité, outils (révision +1 si la liste change), aucune erreur ; `enabled` intact."""

    display_name = plugin.display_name
    server_name = _clean_line(identity.get("name"), MAX_DISPLAY_NAME_CHARS)
    if server_name and display_name == default_display_name(plugin.endpoint):
        display_name = server_name  # default = serverInfo.name, else the host (ARCH §3.1)
    connected = _touch(plugin, now, connection_status=ConnectionStatus.CONNECTED,
                       auth_status=AuthStatus(auth_status), auth_strategy=AuthStrategy(auth_strategy),
                       server_identity=dict(identity) or None, icon_url=icon_url, display_name=display_name,
                       last_error_code=None)
    return apply_tools(connected, tools, rejected, now=now)


def apply_tools(plugin: McpPlugin, tools: tuple[Mapping[str, Any], ...], rejected: tuple[Mapping[str, str], ...],
                *, now: datetime) -> McpPlugin:
    """Nouvelle liste découverte ; `capability_revision` +1 seulement si outils ou refus changent."""

    candidate = replace(plugin, tools=tools, rejected_tools=rejected)
    changed = candidate.tools != plugin.tools or candidate.rejected_tools != plugin.rejected_tools
    return _touch(plugin, now, tools=tools, rejected_tools=rejected, last_discovered_at=now,
                  capability_revision=plugin.capability_revision + (1 if changed else 0))


def bind_credential(plugin: McpPlugin, *, strategy: AuthStrategy, credential_ref: str, now: datetime) -> McpPlugin:
    """Nouvelle référence scellée pendant un flux (jetons OAuth) : l'état d'autorisation n'est pas touché."""

    return _touch(plugin, now, auth_strategy=AuthStrategy(strategy), credential_ref=credential_ref)


def oauth_needs_reauthorization(oauth: Mapping[str, Any] | None, *, now_epoch: float) -> bool:
    """Vrai si aucun jeton n'est stocké, ou s'il est échu **sans** jeton de rafraîchissement."""

    if not isinstance(oauth, Mapping):
        return True
    tokens = oauth.get("tokens")
    if not isinstance(tokens, Mapping) or not tokens.get("access_token"):
        return True
    expires_at = oauth.get("expires_at")
    expired = isinstance(expires_at, (int, float)) and not isinstance(expires_at, bool) and now_epoch > expires_at
    return expired and not tokens.get("refresh_token")


def check_authorization_issuer(*, expected: str | None, supported: bool, received: str | None) -> None:
    """RFC 9207 : annoncé ⇒ `iss` présent et égal à l'émetteur ; présent ⇒ égal. Sinon `mcp_oauth_issuer_mismatch`."""

    if received is None and not supported:
        return
    if received is None or expected is None or received != expected:
        raise McpPluginError(McpErrorCode.OAUTH_ISSUER_MISMATCH,
                             "the authorization response does not come from the expected authorization server")


# ------------------------------------------------------------------ appel d'outil (Slice 04, ARCH §7.3)

#: Arguments d'un appel (JSON compact UTF-8).
MAX_CALL_ARGUMENTS_BYTES = 64 * 1024
#: Texte rendu d'un résultat, tous blocs confondus ; au-delà : coupé, `truncated: true`.
MAX_CALL_RESULT_BYTES = 32 * 1024
TOOL_ID_PATTERN = re.compile(r"([a-z0-9][a-z0-9-]{0,31})\.([A-Za-z0-9_.-]{1,128})")
NATIVE_TOOL_PREFIX = "mcp__"
_OMITTED_BLOCK = {"image": "[image omise]", "audio": "[audio omis]", "resource": "[ressource omise]",
                  "resource_link": "[lien de ressource omis]"}


def parse_tool_id(tool_id: object) -> tuple[str, str]:
    """`<plugin_id>.<name>` ⇒ `(plugin_id, name)`. Nom natif ⇒ `native_tool_call_directly` ; autre ⇒ `mcp_tool_unknown`."""

    if isinstance(tool_id, str) and tool_id.startswith(NATIVE_TOOL_PREFIX):
        raise McpPluginError(McpErrorCode.NATIVE_TOOL_CALL_DIRECTLY,
                             f"native tools are called directly by their name ({tool_id[:200]}), not through call_tool")
    match = TOOL_ID_PATTERN.fullmatch(tool_id) if isinstance(tool_id, str) else None
    if match is None:
        raise McpPluginError(McpErrorCode.TOOL_UNKNOWN, f"unknown plugin tool {preview(tool_id)}")
    return match.group(1), match.group(2)


def check_tool_arguments(input_schema: Mapping[str, Any], arguments: object) -> dict[str, Any]:
    """Contrôle sans `jsonschema` (ARCH §7.3) : objet, ≤ 64 Kio, clés requises présentes, inconnues refusées si fermé."""

    if not isinstance(arguments, dict):
        raise McpPluginError(McpErrorCode.ARGUMENTS_INVALID, "arguments must be a JSON object")
    size = len(_compact(arguments))
    if size > MAX_CALL_ARGUMENTS_BYTES:
        raise McpPluginError(McpErrorCode.ARGUMENTS_INVALID,
                             f"arguments exceed {MAX_CALL_ARGUMENTS_BYTES} bytes ({size})")
    required = input_schema.get("required")
    missing = sorted(key for key in (required if isinstance(required, (list, tuple)) else ())
                     if isinstance(key, str) and key not in arguments)
    if missing:
        raise McpPluginError(McpErrorCode.ARGUMENTS_INVALID, f"missing required arguments: {missing[:10]}")
    properties = input_schema.get("properties")
    if input_schema.get("additionalProperties") is False:
        known = set(properties) if isinstance(properties, Mapping) else set()
        unknown = sorted(str(key)[:64] for key in arguments if key not in known)
        if unknown:
            raise McpPluginError(McpErrorCode.ARGUMENTS_INVALID,
                                 f"unknown arguments: {unknown[:10]}; allowed: {sorted(known)[:20]}")
    return arguments


def _cut_utf8(text: str, budget: int) -> str:
    return text.encode("utf-8")[:max(budget, 0)].decode("utf-8", errors="ignore")


def _block_text(block: object) -> str:
    if not isinstance(block, Mapping):
        return "[contenu omis]"
    kind = block.get("type")
    if kind == "text":
        text = block.get("text")
        return text if isinstance(text, str) else ""
    return _OMITTED_BLOCK.get(kind if isinstance(kind, str) else "", "[contenu omis]")


def call_outcome(result: Mapping[str, Any], *, known_secrets: Iterable[str] = ()) -> dict[str, Any]:
    """`CallToolResult` sérialisé ⇒ `ToolCallOutcome` borné (`docs/mcp/plugins.md` §7).

    Succès : blocs texte **masqués** (`redact`, intention verrouillée 3 : un
    serveur qui recopie un jeton dans un résultat normal ne le montre pas au
    modèle) puis ≤ 32 Kio au total (coupés, `truncated`), blocs non texte
    résumés ; `structured` masqué feuille par feuille (`redact_structured`) et
    gardé s'il tient en 32 Kio. Erreur distante
    (`isError`) : `ok: false`, `mcp_remote_tool_error`, **un** bloc texte masqué
    (`redact`) et borné à 4 Kio — seul chemin par lequel un texte d'erreur distant
    atteint le modèle.
    """

    secrets = [secret for secret in known_secrets if isinstance(secret, str) and secret]
    raw_blocks = result.get("content")
    blocks = raw_blocks if isinstance(raw_blocks, list) else []
    texts = [_block_text(block) for block in blocks]
    if result.get("isError") is True:
        joined = redact("\n".join(text for text in texts if text), secrets)
        bounded = joined if len(joined.encode("utf-8")) <= MAX_REMOTE_ERROR_BYTES else (
            _cut_utf8(joined, MAX_REMOTE_ERROR_BYTES - len(TRUNCATION_SUFFIX.encode("utf-8"))) + TRUNCATION_SUFFIX)
        return {"ok": False, "code": McpErrorCode.REMOTE_TOOL_ERROR.value,
                "message": "the plugin tool reported an error",
                "content": [{"type": "text", "text": bounded or "(aucun détail)"}],
                "truncated": bounded != joined}
    content: list[dict[str, str]] = []
    used, truncated = 0, False
    for text in (redact(text, secrets) for text in texts):
        size = len(text.encode("utf-8"))
        if used + size > MAX_CALL_RESULT_BYTES:
            rest = _cut_utf8(text, MAX_CALL_RESULT_BYTES - used)
            if rest:
                content.append({"type": "text", "text": rest})
            truncated = True
            break
        content.append({"type": "text", "text": text})
        used += size
    outcome: dict[str, Any] = {"ok": True, "content": content, "truncated": truncated}
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        structured = redact_structured(structured, secrets)
        if len(_compact(structured)) <= MAX_CALL_RESULT_BYTES:
            outcome["structured"] = structured
        else:
            outcome["truncated"] = True
    return outcome
