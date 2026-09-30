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

Report à la Slice 04 : le type `ExternalToolDescriptor` et la normalisation
`normalize_remote_tool` (ARCH §6.2). D'ici là `tools` est une suite bornée de
dictionnaires JSON, toujours vide tant qu'aucun connecteur n'existe.
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


_BEARER = re.compile(r"Bearer\s+\S+", re.IGNORECASE)
_JWT = re.compile(r"[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}")


def redact(text: str, known_secrets: Iterable[str] = ()) -> str:
    """Masque tout secret connu du plugin, tout `Bearer …` et toute forme JWT (ARCH §9).

    Les secrets connus passent d'abord, du plus long au plus court, pour qu'un
    secret contenu dans un autre ne laisse pas de fragment visible.
    """

    for secret in sorted({s for s in known_secrets if isinstance(s, str) and s}, key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    text = _BEARER.sub(f"Bearer {REDACTED}", text)
    return _JWT.sub(REDACTED, text)


def canonical_json(payload: Mapping[str, Any]) -> str:
    """Encodage canonique partagé par le magasin (`data`) et le coffre (charge scellée)."""

    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
