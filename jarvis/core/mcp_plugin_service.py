"""Service Core des plugins MCP distants (generic-mcp-plugin-runtime ; Slice 02 : registre et coffre).

Core possède le registre, le coffre et, plus tard, les connexions (ARCH §0,
contradiction C1). Ce service est la seule porte d'écriture : les routes
`/v1/mcp/plugins*` (et, Slice 06, le Control Center par relais) passent par
lui, jamais par le dépôt. Les règles sont celles du domaine
(`jarvis.domain.mcp_plugins`, `jarvis.domain.mcp_endpoint`) ; rien n'est
redécidé ici. Contrat : `docs/mcp/plugins.md` §2, §3, §8.

Ce que fait cette Slice :

- `list_plugins` / `get` / `create` (validation statique + doublon, aucun
  réseau) / `update` (`enabled`, `display_name`) ;
- `set_static_credential` (Bearer ou en-tête, scellé dans le coffre) ;
- `disconnect` (identifiants oubliés, ligne et `enabled` gardés) et `remove`
  (ligne + identifiants en une transaction) ;
- `start()` : les lignes laissées `connecting` redeviennent `disconnected`.

`connect`, `refresh`, `complete_oauth`, `external_tools` et `call` répondent
`mcp_connector_unavailable` (503) jusqu'aux Slices 03-04, qui y brancheront
le connecteur injecté, les reconnexions de démarrage et la révocation RFC 7009.

Journal (`DiagnosticSink`) : chaque changement et chaque refus est tracé avec
`plugin_id`, l'opération et un code stable ; **jamais** une valeur
d'identifiant, un en-tête ni une URL complète.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
import re
import secrets
from typing import Any

from jarvis.core.credential_vault import CredentialVault
from jarvis.domain.mcp_endpoint import validate_endpoint
from jarvis.domain.mcp_plugins import (
    STATIC_STRATEGIES, AuthStrategy, ConnectionStatus, McpErrorCode, McpPlugin, McpPluginError,
    attach_credential, disconnect as disconnect_plugin, new_plugin, plugin_id_for, rename, reset_interrupted_connect,
    set_enabled,
)
from jarvis.domain.v2 import utc_now
from jarvis.ports.mcp_plugins import McpPluginRepository, McpPluginStoreError, RemoteMcpConnector
from jarvis.ports.v2 import DiagnosticSink

#: En-têtes qu'un identifiant manuel ne peut pas poser (ARCH §5.3).
FORBIDDEN_HEADER_NAMES = frozenset({
    "host", "cookie", "content-length", "transfer-encoding", "connection", "mcp-session-id", "mcp-protocol-version",
})
HEADER_NAME_PATTERN = re.compile(r"[A-Za-z0-9-]{1,64}")
MAX_STATIC_VALUE_CHARS = 4096

PLUGINS_STARTED = "mcp.plugins.started"
PLUGINS_CONNECTING_RESET = "mcp.plugins.connecting_reset"
PLUGIN_CREATED = "mcp.plugin.created"
PLUGIN_UPDATED = "mcp.plugin.updated"
PLUGIN_CREDENTIAL_SET = "mcp.plugin.credential_set"
PLUGIN_DISCONNECTED = "mcp.plugin.disconnected"
PLUGIN_REMOVED = "mcp.plugin.removed"
PLUGIN_REFUSED = "mcp.plugin.refused"
PLUGIN_STORE_FAILED = "mcp.plugin.store_failed"
VAULT_DISCARD_FAILED = "mcp.vault.discard_failed"


class McpPluginService:
    def __init__(self, repository: McpPluginRepository, vault: CredentialVault, *,
                 connector: RemoteMcpConnector | None = None, diagnostics: DiagnosticSink | None = None,
                 allow_loopback_http: bool = False, clock: Callable[[], datetime] = utc_now,
                 revision_base: int | None = None) -> None:
        self._repository = repository
        self._vault = vault
        #: Injecté dès maintenant pour la composition ; utilisé à partir de la Slice 03.
        self._connector = connector
        self._diagnostics = diagnostics
        self._allow_loopback_http = bool(allow_loopback_http)
        self._clock = clock
        self._lock = asyncio.Lock()
        # Base aléatoire à chaque démarrage (ARCH §4.1) : une révision mise en
        # cache par un ancien Core ne correspond jamais.
        self._revision = revision_base if revision_base is not None else secrets.randbelow(1 << 30) + 1

    # ------------------------------------------------------------ état

    @property
    def catalog_revision(self) -> int:
        return self._revision

    @property
    def vault_available(self) -> bool:
        return self._vault.available

    def _bump(self) -> None:
        self._revision += 1

    def _emit(self, kind: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        if self._diagnostics is not None:
            self._diagnostics.emit(kind, message, level=level, data=dict(data or {}))

    @asynccontextmanager
    async def _operation(self, operation: str, plugin_id: str | None = None) -> AsyncIterator[None]:
        """Trace tout refus (code) et toute panne de stockage, puis les relève tels quels."""

        ids = {"operation": operation, **({"plugin_id": plugin_id} if plugin_id else {})}
        try:
            yield
        except McpPluginError as exc:
            self._emit(PLUGIN_REFUSED, "demande de plugin MCP refusée", level="warning",
                       data={**ids, "code": exc.code.value})
            raise
        except McpPluginStoreError as exc:
            self._emit(PLUGIN_STORE_FAILED, "registre des plugins MCP en échec", level="error",
                       data={**ids, "code": exc.code, "error": str(exc)[:300]})
            raise

    # ------------------------------------------------------------ cycle de vie

    async def start(self) -> None:
        """Remet `connecting` à `disconnected` (un arrêt brutal ne laisse pas de connexion fantôme). Ne lève pas.

        Les reconnexions non interactives des plugins `enabled` arrivent avec
        le connecteur (Slice 03).
        """

        self._emit(PLUGINS_STARTED, "registre des plugins MCP prêt",
                   level="info" if self.vault_available else "warning",
                   data={"vault_available": self.vault_available, "connector": self._connector is not None,
                         "allow_loopback_http": self._allow_loopback_http})
        try:
            now = self._clock()
            stale = [reset_interrupted_connect(plugin, now=now) for plugin in await self._repository.list_plugins()
                     if plugin.connection_status is ConnectionStatus.CONNECTING]
            await self._repository.save_plugins(stale)
        except McpPluginStoreError as exc:
            # Argued: a damaged registry must not stop Core; every plugin route
            # will surface the same store error (500) with its table and key.
            self._emit(PLUGIN_STORE_FAILED, "registre des plugins MCP illisible au démarrage", level="error",
                       data={"operation": "start", "code": exc.code, "error": str(exc)[:300]})
            return
        if stale:
            self._bump()
            self._emit(PLUGINS_CONNECTING_RESET, "connexions interrompues remises à « déconnecté »",
                       data={"count": len(stale), "plugin_ids": [plugin.plugin_id for plugin in stale]})

    async def stop(self) -> None:
        """Aucune connexion n'existe avant la Slice 03 ; le lock garantit qu'aucune écriture n'est en vol."""

        async with self._lock:
            return

    # ------------------------------------------------------------ lecture

    async def list_plugins(self) -> Sequence[McpPlugin]:
        async with self._operation("list"):
            return await self._repository.list_plugins()

    async def get(self, plugin_id: str) -> McpPlugin:
        async with self._operation("get", plugin_id):
            return await self._require(plugin_id)

    async def _require(self, plugin_id: str) -> McpPlugin:
        plugin = await self._repository.get_plugin(plugin_id) if isinstance(plugin_id, str) else None
        if plugin is None:
            raise McpPluginError(McpErrorCode.PLUGIN_UNKNOWN, f"no MCP plugin {str(plugin_id)[:40]!r}")
        return plugin

    # ------------------------------------------------------------ écriture

    async def create(self, endpoint: object, display_name: object = None) -> McpPlugin:
        """Valide et enregistre un plugin (activé, déconnecté). Aucun accès réseau."""

        async with self._lock, self._operation("create"):
            if display_name is not None and not isinstance(display_name, str):
                raise McpPluginError(McpErrorCode.PLUGIN_INVALID, "display_name must be a string")
            normalized = validate_endpoint(endpoint, allow_loopback_http=self._allow_loopback_http)
            existing = await self._repository.list_plugins()
            if any(plugin.endpoint == normalized for plugin in existing):
                raise McpPluginError(McpErrorCode.PLUGIN_DUPLICATE, "this endpoint is already registered")
            plugin_id = plugin_id_for(normalized, {plugin.plugin_id for plugin in existing})
            plugin = new_plugin(normalized, plugin_id=plugin_id, display_name=display_name, now=self._clock())
            await self._repository.insert_plugin(plugin)
            self._bump()
        self._emit(PLUGIN_CREATED, "plugin MCP ajouté",
                   data={"plugin_id": plugin.plugin_id, "endpoint_origin": plugin.endpoint_origin})
        return plugin

    async def update(self, plugin_id: str, *, enabled: object = None, display_name: object = None) -> McpPlugin:
        """`enabled` ne touche jamais la connexion ; `display_name` seul change le nom."""

        async with self._lock, self._operation("update", plugin_id):
            if enabled is None and display_name is None:
                raise McpPluginError(McpErrorCode.PLUGIN_INVALID, "update needs enabled and/or display_name")
            if enabled is not None and type(enabled) is not bool:
                raise McpPluginError(McpErrorCode.PLUGIN_INVALID, "enabled must be a boolean")
            if display_name is not None and not isinstance(display_name, str):
                raise McpPluginError(McpErrorCode.PLUGIN_INVALID, "display_name must be a string")
            current = await self._require(plugin_id)
            now = self._clock()
            plugin = current
            if enabled is not None:
                plugin = set_enabled(plugin, enabled, now=now)
            if display_name is not None:
                plugin = rename(plugin, display_name, now=now)
            if plugin != current:
                await self._repository.save_plugin(plugin)
                self._bump()
        if plugin != current:
            self._emit(PLUGIN_UPDATED, "plugin MCP modifié",
                       data={"plugin_id": plugin_id, "enabled": plugin.enabled,
                             "renamed": plugin.display_name != current.display_name})
        return plugin

    async def set_static_credential(self, plugin_id: str, *, strategy: object, header_name: object = None,
                                    value: object) -> McpPlugin:
        """Identifiant manuel (`bearer` ou `header`), scellé ; la valeur n'est jamais rendue ni journalisée."""

        async with self._lock, self._operation("set_credential", plugin_id):
            current = await self._require(plugin_id)
            chosen = _static_strategy(strategy)
            name = _header_name(chosen, header_name)
            _check_static_value(value)
            payload = {"kind": "static", "static": {"header_name": name, "value": value}}
            new_ref = await self._vault.replace_secret(current, payload)
            plugin = attach_credential(current, strategy=chosen, credential_ref=new_ref, now=self._clock())
            try:
                await self._repository.save_plugin(plugin)
            except BaseException as exc:
                await self._discard(new_ref, plugin_id, exc)
                raise
            await self._discard(current.credential_ref, plugin_id)
            self._bump()
        self._emit(PLUGIN_CREDENTIAL_SET, "identifiant de plugin MCP scellé",
                   data={"plugin_id": plugin_id, "strategy": chosen.value})
        return plugin

    async def _discard(self, ref: str | None, plugin_id: str, failure: BaseException | None = None) -> None:
        """Retire un blob que plus aucune ligne ne référence. Un échec est tracé, jamais masquant."""

        try:
            await self._vault.discard(ref)
        except McpPluginStoreError as exc:
            # Argued: the plugin row no longer points at this blob, so it can
            # never authorize anything; `disconnect`/`remove` delete every blob
            # of the plugin. The original failure, if any, stays the one raised.
            if failure is not None:
                failure.add_note(f"orphan sealed credential not removed: {exc.code}")
            self._emit(VAULT_DISCARD_FAILED, "blob scellé orphelin non supprimé", level="error",
                       data={"plugin_id": plugin_id, "credential_ref": ref, "code": exc.code})

    async def disconnect(self, plugin_id: str) -> McpPlugin:
        """Ferme la session (Slice 03) et **oublie** les identifiants ; `enabled` et la ligne restent."""

        async with self._lock, self._operation("disconnect", plugin_id):
            current = await self._require(plugin_id)
            plugin = disconnect_plugin(current, now=self._clock())
            if plugin != current:
                await self._repository.save_plugin(plugin)
            forgotten = await self._vault.forget(plugin)
            self._bump()
        self._emit(PLUGIN_DISCONNECTED, "plugin MCP déconnecté, identifiants oubliés",
                   data={"plugin_id": plugin_id, "credentials_forgotten": forgotten})
        return plugin

    async def remove(self, plugin_id: str) -> None:
        """Supprime la ligne et ses identifiants en une transaction."""

        async with self._lock, self._operation("remove", plugin_id):
            if not await self._repository.delete_plugin(plugin_id):
                raise McpPluginError(McpErrorCode.PLUGIN_UNKNOWN, f"no MCP plugin {str(plugin_id)[:40]!r}")
            self._bump()
        self._emit(PLUGIN_REMOVED, "plugin MCP supprimé", data={"plugin_id": plugin_id})

    # ------------------------------------------------------------ Slices 03-04

    def _no_connector(self) -> McpPluginError:
        return McpPluginError(McpErrorCode.CONNECTOR_UNAVAILABLE,
                              "remote MCP connections are not available in this Core")

    async def connect(self, plugin_id: str, *, strategy: str = "auto") -> Any:
        async with self._operation("connect", plugin_id):
            await self._require(plugin_id)
            raise self._no_connector()

    async def refresh(self, plugin_id: str) -> McpPlugin:
        async with self._operation("refresh", plugin_id):
            await self._require(plugin_id)
            raise self._no_connector()

    async def complete_oauth(self, code: str, state: str, iss: str | None) -> McpPlugin:
        async with self._operation("complete_oauth"):
            raise self._no_connector()

    async def external_tools(self, since_revision: int | None) -> Any:
        async with self._operation("external_tools"):
            raise self._no_connector()

    async def call(self, tool_id: str, arguments: dict, *, caller: dict) -> Any:
        async with self._operation("call"):
            raise self._no_connector()


# ------------------------------------------------------------------ identifiants manuels


def _static_strategy(raw: object) -> AuthStrategy:
    try:
        strategy = AuthStrategy(raw)
    except ValueError:
        strategy = None
    if strategy not in STATIC_STRATEGIES:
        raise McpPluginError(McpErrorCode.PLUGIN_INVALID, "strategy must be bearer or header")
    return strategy


def _header_name(strategy: AuthStrategy, raw: object) -> str | None:
    if strategy is AuthStrategy.BEARER:
        if raw is not None:
            raise McpPluginError(McpErrorCode.PLUGIN_INVALID, "header_name is only for the header strategy")
        return None
    if not isinstance(raw, str) or not HEADER_NAME_PATTERN.fullmatch(raw):
        raise McpPluginError(McpErrorCode.PLUGIN_INVALID, "header_name must match ^[A-Za-z0-9-]{1,64}$")
    if raw.lower() in FORBIDDEN_HEADER_NAMES:
        raise McpPluginError(McpErrorCode.PLUGIN_INVALID, f"header {raw.lower()!r} cannot carry a credential")
    return raw


def _check_static_value(value: object) -> None:
    # Messages never quote the value: it is a secret.
    if not isinstance(value, str) or not value.strip():
        raise McpPluginError(McpErrorCode.PLUGIN_INVALID, "value must be a non-empty string")
    if len(value) > MAX_STATIC_VALUE_CHARS:
        raise McpPluginError(McpErrorCode.PLUGIN_INVALID, f"value exceeds {MAX_STATIC_VALUE_CHARS} characters")
    if any(ch in "\r\n\0" for ch in value):
        raise McpPluginError(McpErrorCode.PLUGIN_INVALID, "value may not contain CR, LF or NUL")
