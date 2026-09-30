"""Service Core des plugins MCP distants (generic-mcp-plugin-runtime ; Slices 02-03).

Core possède le registre, le coffre, les connexions et l'état OAuth (ARCH §0,
contradiction C1). Ce service est la seule porte d'écriture : les routes
`/v1/mcp/*` (et, Slice 06, le Control Center par relais) passent par lui,
jamais par le dépôt. Les règles sont celles du domaine
(`jarvis.domain.mcp_plugins`, `jarvis.domain.mcp_endpoint`) ; rien n'est
redécidé ici. Contrat : `docs/mcp/plugins.md` §2, §3, §8.

Slice 02 : `list_plugins` / `get` / `create` / `update`, identifiants statiques
scellés, `disconnect` (identifiants oubliés, ligne et `enabled` gardés),
`remove`, remise à zéro des `connecting` au démarrage.

Slice 03 (connexion, ARCH §4.1-4.2, §5) :

- **une tâche propriétaire** (`asyncio.Task`) par plugin connecté entre **et**
  quitte le contexte du connecteur (transport anyio du SDK) ; les autres
  tâches appellent la session ouverte ;
- `connect(auto|none|oauth)` répond en ≤ 20 s : connecté, ou `authorizing`
  avec l'URL d'autorisation (le flux finit en arrière-plan) ;
- `complete_oauth` : `state` à usage unique, TTL 300 s, `iss` (RFC 9207),
  refus de l'AS ⇒ `auth_status=failed` ;
- panne ⇒ `connection_status=error`, `last_error_code`, reconnexion **non
  interactive** avec attente `(1, 2, 5, 10, 30, 60)` s tant que `enabled` ;
  besoin d'autorisation ⇒ plus de reprise (`expired`/`failed`/`required`) ;
- `tools/list_changed` ⇒ nouvelle liste, `capability_revision` +1 ;
- démarrage : reconnexions non interactives (`not_required`, `authorized`,
  statiques `unknown|authorized` — ARCH §16 E12), jetons échus sans
  rafraîchissement ⇒ `expired` **sans aucun accès réseau** ;
- `stop()` ferme tout en ≤ 5 s ; `disconnect`/`remove` tentent la
  révocation RFC 7009 au mieux (E10) avant l'oubli local.

Slice 04 (catalogue externe et appel, ARCH §4.3, §7.3) : `external_tools`
sert `GET /v1/mcp/tools` (révision entière, `unchanged` par `since_revision`) ;
`call` sert `POST /v1/mcp/tools/call` sur la même vérification d'état que
`invoke` (avant tout réseau), contrôle les arguments, borne et masque le
résultat (`call_outcome`). Le classement n'est pas ici (C2) : il tourne dans
la passerelle `jarvis-tools`, qui voit le catalogue natif.

Journal (`DiagnosticSink`) : `plugin_id`, opération, codes stables, durées ;
**jamais** une valeur d'identifiant, un jeton, un en-tête, une URL
d'autorisation ni un texte distant.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
import re
import secrets
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

from jarvis.core.credential_vault import CredentialVault
from jarvis.domain.mcp_endpoint import validate_endpoint
from jarvis.domain.mcp_plugins import (
    STATIC_STRATEGIES, AuthStatus, AuthStrategy, ConnectionStatus, McpErrorCode, McpPlugin, McpPluginError,
    apply_tools, attach_credential, bind_credential, call_outcome, check_authorization_issuer, check_tool_arguments,
    disconnect as disconnect_plugin, icon_url_from, mark_connected, mark_connection, new_plugin,
    normalize_remote_tools, oauth_needs_reauthorization, parse_tool_id, plugin_id_for, rename,
    reset_interrupted_connect, server_identity_from, set_enabled,
)
from jarvis.domain.v2 import utc_now
from jarvis.ports.mcp_plugins import (
    AuthMaterial, McpPluginRepository, McpPluginStoreError, RemoteMcpConnector, RemoteMcpError, RemoteMcpSession,
)
from jarvis.ports.v2 import DiagnosticSink

#: En-têtes qu'un identifiant manuel ne peut pas poser (ARCH §5.3).
FORBIDDEN_HEADER_NAMES = frozenset({
    "host", "cookie", "content-length", "transfer-encoding", "connection", "mcp-session-id", "mcp-protocol-version",
})
HEADER_NAME_PATTERN = re.compile(r"[A-Za-z0-9-]{1,64}")
MAX_STATIC_VALUE_CHARS = 4096

CONNECT_STRATEGIES = frozenset({"auto", "none", "oauth"})
#: `connect` répond au plus tard après ce délai (ARCH §5.3).
CONNECT_WAIT_S = 20.0
#: `complete_oauth` attend la fin de la connexion au plus ce délai avant de répondre l'état courant.
COMPLETE_WAIT_S = 15.0
AUTHORIZATION_TTL_S = 300.0
STOP_BUDGET_S = 5.0
REVOKE_TIMEOUT_S = 10.0
BACKOFF_S = (1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
DEFAULT_CALL_TIMEOUT_S = 60.0
MAX_CALL_TIMEOUT_S = 120.0
#: Pannes de transport : on réessaie. Tout le reste (autorisation, politique, transport inadapté) s'arrête.
RETRYABLE_CODES = frozenset({
    McpErrorCode.REMOTE_UNREACHABLE, McpErrorCode.REMOTE_TIMEOUT, McpErrorCode.REMOTE_PROTOCOL,
    McpErrorCode.REMOTE_TLS, McpErrorCode.RESPONSE_TOO_LARGE, McpErrorCode.PLUGIN_DISCONNECTED,
})
_AS_ERROR = re.compile(r"[a-z_]{1,64}")

PLUGINS_STARTED = "mcp.plugins.started"
PLUGINS_CONNECTING_RESET = "mcp.plugins.connecting_reset"
PLUGINS_BOOT_RECONNECT = "mcp.plugins.boot_reconnect"
PLUGINS_STOPPED = "mcp.plugins.stopped"
PLUGIN_CREATED = "mcp.plugin.created"
PLUGIN_UPDATED = "mcp.plugin.updated"
PLUGIN_CREDENTIAL_SET = "mcp.plugin.credential_set"
PLUGIN_DISCONNECTED = "mcp.plugin.disconnected"
PLUGIN_REMOVED = "mcp.plugin.removed"
PLUGIN_REFUSED = "mcp.plugin.refused"
PLUGIN_STORE_FAILED = "mcp.plugin.store_failed"
PLUGIN_CONNECTING = "mcp.plugin.connecting"
PLUGIN_CONNECTED = "mcp.plugin.connected"
PLUGIN_CONNECTION_FAILED = "mcp.plugin.connection_failed"
PLUGIN_RECONNECT_SCHEDULED = "mcp.plugin.reconnect_scheduled"
PLUGIN_AUTHORIZATION_PENDING = "mcp.plugin.authorization_pending"
PLUGIN_OAUTH_COMPLETED = "mcp.plugin.oauth_completed"
PLUGIN_EXPIRED_AT_BOOT = "mcp.plugin.expired_at_boot"
PLUGIN_TOOLS_CHANGED = "mcp.plugin.tools_changed"
PLUGIN_TOOL_CALLED = "mcp.plugin.tool_called"
PLUGIN_REVOKED = "mcp.plugin.revoked"
PLUGIN_REVOCATION_FAILED = "mcp.plugin.revocation_failed"
PLUGIN_OWNER_CRASHED = "mcp.plugin.owner_crashed"
VAULT_DISCARD_FAILED = "mcp.vault.discard_failed"


@dataclass(frozen=True, slots=True)
class ConnectOutcome:
    """Réponse de `connect` : `connected` (200) ou `authorizing` + URL d'autorisation (202)."""

    status: str
    plugin: McpPlugin
    authorization_url: str | None = None


@dataclass(eq=False)
class _PendingAuthorization:
    state: str
    plugin_id: str
    expires_at: float
    issuer: str | None
    iss_supported: bool
    connection: _Connection
    future: asyncio.Future = field(default_factory=lambda: asyncio.get_running_loop().create_future())

    def resolve(self, value: tuple[str, str]) -> None:
        if not self.future.done():
            self.future.set_result(value)

    def reject(self, error: BaseException) -> None:
        if not self.future.done():
            self.future.set_exception(error)
            self.future.exception()  # retrieved here: an owner that already left never logs it as lost


class _Stopped(Exception):
    """Arrêt demandé pendant une étape de la tâche propriétaire."""


@dataclass(eq=False)
class _Connection:
    """État vivant d'**une** connexion de plugin ; ne sort jamais du service."""

    plugin_id: str
    strategy: AuthStrategy
    oauth_store: _PluginOAuthStore | None
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    connected: asyncio.Event = field(default_factory=asyncio.Event)
    #: Levé à chaque issue d'une tentative (connectée ou en échec).
    progress: asyncio.Event = field(default_factory=asyncio.Event)
    settled: asyncio.Future = field(default_factory=lambda: asyncio.get_running_loop().create_future())
    session: RemoteMcpSession | None = None
    task: asyncio.Task | None = None
    attempt: int = 0

    async def notify_changed(self) -> None:
        self.changed.set()


class _PluginOAuthStore:
    """`OAuthCredentialStore` d'un plugin : charge `oauth` du coffre, rescellée à chaque écriture du SDK."""

    def __init__(self, service: McpPluginService, plugin_id: str) -> None:
        self._service = service
        self._plugin_id = plugin_id

    async def load(self) -> dict[str, Any] | None:
        return await self._service._oauth_payload(self._plugin_id)

    async def save(self, oauth: dict[str, Any]) -> None:
        await self._service._store_oauth(self._plugin_id, oauth)


class _InteractivePrompt:
    """`AuthorizationPrompt` d'un `connect` explicite : **une** autorisation par connexion, puis non interactif."""

    def __init__(self, service: McpPluginService, connection: _Connection) -> None:
        self._service = service
        self._connection = connection
        self._armed = True
        self._pending: _PendingAuthorization | None = None

    @property
    def interactive(self) -> bool:
        return self._armed

    def disarm(self) -> None:
        self._armed = False

    async def authorization_url(self, url: str, *, issuer: str | None, iss_supported: bool) -> None:
        if not self._armed:
            raise McpPluginError(McpErrorCode.REAUTHORIZATION_REQUIRED,
                                 "a second authorization was requested: reconnect the plugin")
        self._armed = False
        state = (parse_qs(urlsplit(url).query).get("state") or [""])[0]
        if not state:
            raise McpPluginError(McpErrorCode.REMOTE_PROTOCOL, "the authorization URL carries no state")
        self._pending = await self._service._open_authorization(self._connection, url, state, issuer=issuer,
                                                                iss_supported=iss_supported)

    async def wait_callback(self) -> tuple[str, str | None]:
        pending = self._pending
        if pending is None:
            raise McpPluginError(McpErrorCode.OAUTH_STATE_INVALID, "no authorization is pending")
        remaining = max(0.0, pending.expires_at - self._service._monotonic())
        try:
            return await asyncio.wait_for(asyncio.shield(pending.future), remaining)
        except TimeoutError:
            self._service._pending.pop(pending.state, None)
            raise McpPluginError(McpErrorCode.REAUTHORIZATION_REQUIRED,
                                 f"the authorization was not completed within {AUTHORIZATION_TTL_S:g} s") from None


async def _first(*awaitables: Awaitable[Any]) -> tuple[int, Any]:
    """Premier terminé (index, résultat) ; les autres sont annulés et attendus."""

    tasks = [asyncio.ensure_future(item) for item in awaitables]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    index = next(i for i, task in enumerate(tasks) if task in done)
    return index, tasks[index].result()


class McpPluginService:
    def __init__(self, repository: McpPluginRepository, vault: CredentialVault, *,
                 connector: RemoteMcpConnector | None = None, diagnostics: DiagnosticSink | None = None,
                 allow_loopback_http: bool = False, clock: Callable[[], datetime] = utc_now,
                 revision_base: int | None = None, monotonic: Callable[[], float] = time.monotonic,
                 backoff_s: Sequence[float] = BACKOFF_S, connect_wait_s: float = CONNECT_WAIT_S,
                 authorization_ttl_s: float = AUTHORIZATION_TTL_S) -> None:
        self._repository = repository
        self._vault = vault
        self._connector = connector
        self._diagnostics = diagnostics
        self._allow_loopback_http = bool(allow_loopback_http)
        self._clock = clock
        self._monotonic = monotonic
        self._backoff = tuple(backoff_s) or BACKOFF_S
        self._connect_wait_s = connect_wait_s
        self._authorization_ttl_s = authorization_ttl_s
        self._lock = asyncio.Lock()
        self._connections: dict[str, _Connection] = {}
        self._pending: dict[str, _PendingAuthorization] = {}
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

    def note_refused(self, operation: str, code: McpErrorCode, *, plugin_id: str | None = None) -> None:
        """Refus décidé avant le service (corps ou requête HTTP) : même trace que les refus du service, code seul."""

        data = {"operation": operation, "code": McpErrorCode(code).value}
        if plugin_id:
            data["plugin_id"] = plugin_id[:64]
        self._emit(PLUGIN_REFUSED, "demande de plugin MCP refusée", level="warning", data=data)

    # ------------------------------------------------------------ cycle de vie

    async def start(self) -> None:
        """Remet `connecting` à `disconnected`, puis reconnecte en arrière-plan, sans interaction. Ne lève pas."""

        self._emit(PLUGINS_STARTED, "registre des plugins MCP prêt",
                   level="info" if self.vault_available else "warning",
                   data={"vault_available": self.vault_available, "connector": self._connector is not None,
                         "allow_loopback_http": self._allow_loopback_http})
        try:
            now = self._clock()
            # A Core that stopped (or crashed) holds no session: `connecting`
            # and `connected` rows both become `disconnected` before any reconnect.
            stale = [reset_interrupted_connect(plugin, now=now) if plugin.connection_status is
                     ConnectionStatus.CONNECTING else mark_connection(
                         plugin, ConnectionStatus.DISCONNECTED, now=now, error_code=plugin.last_error_code)
                     for plugin in await self._repository.list_plugins()
                     if plugin.connection_status in (ConnectionStatus.CONNECTING, ConnectionStatus.CONNECTED)]
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
        if self._connector is not None:
            await self._boot_reconnect()

    async def _boot_reconnect(self) -> None:
        started: list[str] = []
        try:
            plugins = await self._repository.list_plugins()
        except McpPluginStoreError as exc:
            self._emit(PLUGIN_STORE_FAILED, "reconnexion de démarrage impossible", level="error",
                       data={"operation": "boot_reconnect", "code": exc.code})
            return
        for plugin in plugins:
            try:
                if plugin.enabled and await self._boot_one(plugin):
                    started.append(plugin.plugin_id)
            except (McpPluginStoreError, McpPluginError) as exc:
                # Argued: boot reconnects are best effort; this plugin keeps its
                # stored state (the user reconnects it) and the others go on.
                code = exc.code.value if isinstance(exc, McpPluginError) else exc.code
                self._emit(PLUGIN_CONNECTION_FAILED, "reconnexion de démarrage refusée", level="warning",
                           data={"plugin_id": plugin.plugin_id, "code": code, "attempt": 0, "retry": False})
        self._emit(PLUGINS_BOOT_RECONNECT, "reconnexions non interactives des plugins lancées",
                   data={"plugin_ids": started})

    async def _boot_one(self, plugin: McpPlugin) -> bool:
        strategy, status = plugin.auth_strategy, plugin.auth_status
        if strategy is AuthStrategy.NONE and status is AuthStatus.NOT_REQUIRED:
            auth = AuthMaterial("none")
        elif strategy in STATIC_STRATEGIES and status in (AuthStatus.UNKNOWN, AuthStatus.AUTHORIZED):
            auth = await self._static_material(plugin)
        elif strategy is AuthStrategy.OAUTH and status is AuthStatus.AUTHORIZED:
            if oauth_needs_reauthorization(await self._oauth_payload(plugin.plugin_id),
                                           now_epoch=self._clock().timestamp()):
                await self._mutate(plugin.plugin_id, lambda p: mark_connection(
                    p, ConnectionStatus.DISCONNECTED, now=self._clock(), auth_status=AuthStatus.EXPIRED,
                    error_code=McpErrorCode.REAUTHORIZATION_REQUIRED))
                self._emit(PLUGIN_EXPIRED_AT_BOOT, "jeton échu sans rafraîchissement : « Reconnecter » requis",
                           level="warning", data={"plugin_id": plugin.plugin_id,
                                                  "code": McpErrorCode.REAUTHORIZATION_REQUIRED.value})
                return False
            auth = AuthMaterial("oauth", oauth=_PluginOAuthStore(self, plugin.plugin_id))
        else:
            return False
        await self._launch(plugin, auth, prompt_wanted=False)
        return True

    async def stop(self) -> None:
        """Ferme toutes les connexions en ≤ 5 s au total ; les retardataires sont annulés."""

        started = self._monotonic()
        connections = list(self._connections.values())
        for connection in connections:
            connection.stop.set()
        for pending in list(self._pending.values()):
            pending.reject(McpPluginError(McpErrorCode.PLUGIN_DISCONNECTED, "Core is stopping"))
        self._pending.clear()
        tasks = [connection.task for connection in connections if connection.task is not None]
        late: set[asyncio.Task] = set()
        if tasks:
            _, late = await asyncio.wait(tasks, timeout=STOP_BUDGET_S - 0.5)
            for task in late:
                task.cancel()
            if late:
                await asyncio.wait(late, timeout=0.5)
        self._connections.clear()
        for connection in connections:
            try:
                await self._mutate(connection.plugin_id, lambda p: p if p.connection_status in (
                    ConnectionStatus.ERROR, ConnectionStatus.DISCONNECTED) else mark_connection(
                        p, ConnectionStatus.DISCONNECTED, now=self._clock(), error_code=p.last_error_code))
            except McpPluginStoreError as exc:
                # Argued: Core is stopping; the next start rewrites any
                # `connected`/`connecting` row to `disconnected` anyway.
                self._emit(PLUGIN_STORE_FAILED, "état de déconnexion non écrit à l'arrêt", level="error",
                           data={"operation": "stop", "plugin_id": connection.plugin_id, "code": exc.code})
        self._emit(PLUGINS_STOPPED, "connexions des plugins MCP fermées",
                   data={"connections": len(connections), "cancelled": len(late),
                         "duration_ms": round((self._monotonic() - started) * 1000)})

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

    async def _mutate(self, plugin_id: str, change: Callable[[McpPlugin], McpPlugin], *,
                      connection: _Connection | None = None) -> McpPlugin | None:
        """Lire-modifier-écrire sous le verrou. `connection` périmée (remplacée) ou plugin supprimé ⇒ rien."""

        async with self._lock:
            if connection is not None and self._connections.get(plugin_id) is not connection:
                return None
            current = await self._repository.get_plugin(plugin_id)
            if current is None:
                return None
            updated = change(current)
            if updated != current:
                await self._repository.save_plugin(updated)
                self._bump()
            return updated

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
        """Ferme la session, révoque au mieux (RFC 7009) et **oublie** les identifiants ; `enabled` et la ligne restent."""

        async with self._operation("disconnect", plugin_id):
            await self._require(plugin_id)
            await self._close_connection(plugin_id)
            await self._revoke(plugin_id)
            async with self._lock:
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
        """Ferme la session, révoque au mieux, puis supprime la ligne et ses identifiants en une transaction."""

        async with self._operation("remove", plugin_id):
            if isinstance(plugin_id, str) and await self._repository.get_plugin(plugin_id) is not None:
                await self._close_connection(plugin_id)
                await self._revoke(plugin_id)
            async with self._lock:
                if not await self._repository.delete_plugin(plugin_id):
                    raise McpPluginError(McpErrorCode.PLUGIN_UNKNOWN, f"no MCP plugin {str(plugin_id)[:40]!r}")
                self._bump()
        self._emit(PLUGIN_REMOVED, "plugin MCP supprimé", data={"plugin_id": plugin_id})

    # ------------------------------------------------------------ connexion (Slice 03)

    def _no_connector(self) -> McpPluginError:
        return McpPluginError(McpErrorCode.CONNECTOR_UNAVAILABLE,
                              "remote MCP connections are not available in this Core")

    async def connect(self, plugin_id: str, *, strategy: object = "auto") -> ConnectOutcome:
        """Connexion explicite (seul chemin interactif). Répond en ≤ 20 s : connecté, ou URL d'autorisation."""

        async with self._operation("connect", plugin_id):
            plugin = await self._require(plugin_id)
            if self._connector is None:
                raise self._no_connector()
            if strategy not in CONNECT_STRATEGIES:
                raise McpPluginError(McpErrorCode.PLUGIN_INVALID, "strategy must be auto, none or oauth")
            if not plugin.enabled:
                raise McpPluginError(McpErrorCode.PLUGIN_DISABLED, "enable the plugin before connecting it")
            if strategy == "oauth" and not self.vault_available:
                raise McpPluginError(McpErrorCode.VAULT_UNAVAILABLE,
                                     "no local secret vault on this machine: OAuth tokens cannot be stored")
            await self._close_connection(plugin_id)
            auth = await self._connect_material(plugin, str(strategy))
            connection = await self._launch(plugin, auth, prompt_wanted=True)
            try:
                outcome = await asyncio.wait_for(asyncio.shield(connection.settled), self._connect_wait_s)
            except TimeoutError:
                await self._close_connection(plugin_id)
                await self._mutate(plugin_id, lambda p: mark_connection(
                    p, ConnectionStatus.ERROR, now=self._clock(), error_code=McpErrorCode.REMOTE_TIMEOUT))
                raise McpPluginError(McpErrorCode.REMOTE_TIMEOUT,
                                     f"the plugin did not answer within {self._connect_wait_s:g} s") from None
            return outcome

    async def _connect_material(self, plugin: McpPlugin, strategy: str) -> AuthMaterial:
        if strategy == "none":
            return AuthMaterial("none")
        if strategy == "auto" and plugin.auth_strategy in STATIC_STRATEGIES:
            return await self._static_material(plugin)
        if not self.vault_available:
            return AuthMaterial("none")  # auto without a vault: an OAuth server ends as `required`
        return AuthMaterial("oauth", oauth=_PluginOAuthStore(self, plugin.plugin_id))

    async def _static_material(self, plugin: McpPlugin) -> AuthMaterial:
        secret = await self._vault.get_secret(plugin)
        static = secret.get("static") if secret and secret.get("kind") == "static" else None
        if not isinstance(static, dict) or not isinstance(static.get("value"), str):
            raise McpPluginError(McpErrorCode.REAUTHORIZATION_REQUIRED,
                                 "the stored credential is missing or unreadable: enter it again")
        if plugin.auth_strategy is AuthStrategy.BEARER:
            header = ("Authorization", f"Bearer {static['value']}")
        else:
            header = (str(static.get("header_name")), static["value"])
        return AuthMaterial(plugin.auth_strategy.value, static_headers=(header,))

    async def _launch(self, plugin: McpPlugin, auth: AuthMaterial, *, prompt_wanted: bool) -> _Connection:
        strategy = AuthStrategy(auth.strategy)
        store = auth.oauth if isinstance(auth.oauth, _PluginOAuthStore) else None
        connection = _Connection(plugin.plugin_id, strategy, store)
        prompt = _InteractivePrompt(self, connection) if prompt_wanted else None
        async with self._lock:
            self._connections[plugin.plugin_id] = connection
            current = await self._repository.get_plugin(plugin.plugin_id) or plugin
            await self._repository.save_plugin(mark_connection(current, ConnectionStatus.CONNECTING, now=self._clock(),
                                                               auth_status=current.auth_status))
            self._bump()
        self._emit(PLUGIN_CONNECTING, "connexion au plugin MCP",
                   data={"plugin_id": plugin.plugin_id, "strategy": strategy.value, "interactive": prompt_wanted})
        connection.task = asyncio.create_task(self._own(connection, auth, prompt),
                                              name=f"mcp-plugin-owner:{plugin.plugin_id}")
        return connection

    async def _close_connection(self, plugin_id: str) -> None:
        """Arrête la tâche propriétaire (≤ `STOP_BUDGET_S`) ; elle quitte elle-même le contexte du SDK."""

        connection = self._connections.pop(plugin_id, None)
        if connection is None:
            return
        connection.stop.set()
        for state, pending in list(self._pending.items()):
            if pending.connection is connection:
                self._pending.pop(state, None)
                pending.reject(McpPluginError(McpErrorCode.PLUGIN_DISCONNECTED, "the connection was replaced"))
        task = connection.task
        if task is None or task.done():
            return
        _, late = await asyncio.wait({task}, timeout=STOP_BUDGET_S)
        if late:
            task.cancel()
            await asyncio.wait({task}, timeout=0.5)

    # ------------------------------------------------------------ tâche propriétaire

    async def _own(self, connection: _Connection, auth: AuthMaterial, prompt: _InteractivePrompt | None) -> None:
        pid = connection.plugin_id
        try:
            while True:
                failure = await self._run_once(connection, auth, prompt)
                if failure is None or connection.stop.is_set():
                    return
                code = failure.code
                if not await self._after_failure(connection, code, detail=str(failure)[:200]):
                    return
                delay = self._backoff[min(connection.attempt, len(self._backoff) - 1)]
                connection.attempt += 1
                self._emit(PLUGIN_RECONNECT_SCHEDULED, "reconnexion du plugin MCP programmée",
                           data={"plugin_id": pid, "attempt": connection.attempt, "delay_s": delay,
                                 "code": code.value})
                try:
                    await asyncio.wait_for(connection.stop.wait(), delay)
                    return
                except TimeoutError:
                    pass  # the delay elapsed: reconnect, never interactively
                prompt = None
                await self._mutate(pid, lambda p: mark_connection(
                    p, ConnectionStatus.CONNECTING, now=self._clock(), error_code=p.last_error_code),
                    connection=connection)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Unexpected (store failure, bug): the owner must not die silently.
            self._emit(PLUGIN_OWNER_CRASHED, "tâche de connexion du plugin MCP en échec", level="error",
                       data={"plugin_id": pid, "exception_type": type(exc).__name__,
                             "code": getattr(exc, "code", None) and str(getattr(exc, "code"))})
            self._settle(connection, McpPluginError(McpErrorCode.REMOTE_PROTOCOL,
                                                    f"the connection task failed ({type(exc).__name__})"))
        finally:
            if not connection.settled.done():
                self._settle(connection, McpPluginError(McpErrorCode.PLUGIN_DISCONNECTED, "the connection stopped"))
            connection.progress.set()
            if self._connections.get(pid) is connection:
                self._connections.pop(pid, None)  # no owner left: calls answer `mcp_plugin_disconnected`

    async def _step(self, connection: _Connection, awaitable: Awaitable[Any]) -> Any:
        index, value = await _first(awaitable, connection.stop.wait())
        if index == 1:
            raise _Stopped()
        return value

    async def _run_once(self, connection: _Connection, auth: AuthMaterial,
                        prompt: _InteractivePrompt | None) -> RemoteMcpError | McpPluginError | None:
        """Une ouverture complète. `None` = arrêt demandé ; sinon la panne (code stable + phrase Jarvis)."""

        plugin = await self._repository.get_plugin(connection.plugin_id)
        if plugin is None or self._connector is None:
            return None
        try:
            async with self._connector.open(plugin, auth, prompt) as session:
                try:
                    identity = await self._step(connection, session.initialize())
                    raw_tools = await self._step(connection, session.list_tools_all())
                except _Stopped:
                    return None
                if prompt is not None:
                    prompt.disarm()  # every later 401 (tool call, refresh) is non-interactive
                await self._on_connected(connection, auth, identity, raw_tools)
                connection.session = session
                session.on_tools_changed(connection.notify_changed)
                try:
                    while True:
                        index, value = await _first(connection.stop.wait(), session.wait_failure(),
                                                    connection.changed.wait())
                        if index == 0:
                            return None
                        if index == 1:
                            raise RemoteMcpError(value, "the session broke")
                        connection.changed.clear()
                        await self._relist(connection, session)
                finally:
                    connection.session = None
        except (RemoteMcpError, McpPluginError) as exc:
            return exc

    async def _on_connected(self, connection: _Connection, auth: AuthMaterial, identity: dict[str, Any],
                            raw_tools: list[dict[str, Any]]) -> None:
        pid = connection.plugin_id
        tools, rejected = normalize_remote_tools(pid, raw_tools)
        strategy, status = connection.strategy, AuthStatus.AUTHORIZED
        if strategy is AuthStrategy.NONE:
            status = AuthStatus.NOT_REQUIRED
        elif strategy is AuthStrategy.OAUTH:
            payload = await self._oauth_payload(pid)
            if not (payload and isinstance(payload.get("tokens"), dict)):
                strategy, status = AuthStrategy.NONE, AuthStatus.NOT_REQUIRED  # the server never asked
        plugin = await self._mutate(pid, lambda p: mark_connected(
            p, now=self._clock(), identity=server_identity_from(identity), icon_url=icon_url_from(
                identity.get("icon_url")), auth_strategy=strategy, auth_status=status, tools=tools,
            rejected=rejected), connection=connection)
        connection.attempt = 0
        connection.connected.set()
        connection.progress.set()
        if plugin is None:
            return
        self._settle(connection, ConnectOutcome("connected", plugin))
        self._emit(PLUGIN_CONNECTED, "plugin MCP connecté",
                   data={"plugin_id": pid, "auth_strategy": strategy.value, "auth_status": status.value,
                         "tool_count": len(tools), "rejected_count": len(rejected),
                         "rejected_codes": sorted({item["code"] for item in rejected})})

    async def _after_failure(self, connection: _Connection, code: McpErrorCode, *, detail: str = "") -> bool:
        """État après une panne ; vrai si une reconnexion non interactive est permise."""

        pid = connection.plugin_id
        current = await self._repository.get_plugin(pid)
        if current is None:
            return False
        auth_status, conn_status = current.auth_status, ConnectionStatus.ERROR
        if code is McpErrorCode.REAUTHORIZATION_REQUIRED:
            if connection.strategy in STATIC_STRATEGIES:
                auth_status = AuthStatus.FAILED
            elif connection.strategy is AuthStrategy.NONE:
                auth_status = AuthStatus.REQUIRED
            elif current.auth_status in (AuthStatus.AUTHORIZED, AuthStatus.EXPIRED):
                auth_status, conn_status = AuthStatus.EXPIRED, ConnectionStatus.DISCONNECTED
            else:
                auth_status = AuthStatus.FAILED
        elif code in (McpErrorCode.OAUTH_DENIED, McpErrorCode.OAUTH_ISSUER_MISMATCH):
            auth_status = AuthStatus.FAILED
        elif code is McpErrorCode.VAULT_UNAVAILABLE:
            auth_status = AuthStatus.REQUIRED
        retry = code in RETRYABLE_CODES and current.enabled and not connection.stop.is_set()
        await self._mutate(pid, lambda p: mark_connection(p, conn_status, now=self._clock(), auth_status=auth_status,
                                                          error_code=code), connection=connection)
        self._settle(connection, McpPluginError(code, _failure_sentence(code)))
        self._emit(PLUGIN_CONNECTION_FAILED, "connexion au plugin MCP en échec", level="warning",
                   data={"plugin_id": pid, "code": code.value, "attempt": connection.attempt,
                         "auth_status": auth_status.value, "retry": retry, "detail": detail})
        connection.progress.set()  # after the write: a waiter reads the failure state
        return retry

    def _settle(self, connection: _Connection, outcome: ConnectOutcome | BaseException) -> None:
        if connection.settled.done():
            return
        if isinstance(outcome, BaseException):
            connection.settled.set_exception(outcome)
            connection.settled.exception()  # a background reconnect has no waiter: never "never retrieved"
        else:
            connection.settled.set_result(outcome)

    async def _relist(self, connection: _Connection, session: RemoteMcpSession) -> McpPlugin | None:
        raw_tools = await session.list_tools_all()
        tools, rejected = normalize_remote_tools(connection.plugin_id, raw_tools)
        before = await self._repository.get_plugin(connection.plugin_id)
        plugin = await self._mutate(connection.plugin_id, lambda p: apply_tools(p, tools, rejected, now=self._clock()),
                                    connection=connection)
        if plugin is not None and before is not None and plugin.capability_revision != before.capability_revision:
            self._emit(PLUGIN_TOOLS_CHANGED, "outils du plugin MCP changés",
                       data={"plugin_id": plugin.plugin_id, "capability_revision": plugin.capability_revision,
                             "tool_count": len(plugin.tools), "rejected_count": len(plugin.rejected_tools)})
        return plugin

    # ------------------------------------------------------------ OAuth

    async def _open_authorization(self, connection: _Connection, url: str, state: str, *, issuer: str | None,
                                  iss_supported: bool) -> _PendingAuthorization:
        pending = _PendingAuthorization(state=state, plugin_id=connection.plugin_id,
                                        expires_at=self._monotonic() + self._authorization_ttl_s, issuer=issuer,
                                        iss_supported=iss_supported, connection=connection)
        self._pending[state] = pending
        plugin = await self._mutate(connection.plugin_id, lambda p: mark_connection(
            p, ConnectionStatus.CONNECTING, now=self._clock(), auth_status=AuthStatus.AUTHORIZING),
            connection=connection)
        if plugin is not None:
            self._settle(connection, ConnectOutcome("authorizing", plugin, url))
        self._emit(PLUGIN_AUTHORIZATION_PENDING, "autorisation OAuth en attente du navigateur",
                   data={"plugin_id": connection.plugin_id, "iss_supported": iss_supported,
                         "ttl_s": self._authorization_ttl_s})
        return pending

    async def complete_oauth(self, code: object, state: object, iss: object = None,
                             error: object = None) -> McpPlugin:
        """Retour du navigateur (relayé par le CC). `state` inconnu, périmé ou déjà servi ⇒ `mcp_oauth_state_invalid`."""

        async with self._operation("complete_oauth"):
            if self._connector is None:
                raise self._no_connector()
            now = self._monotonic()
            for key, item in list(self._pending.items()):
                if item.expires_at < now:
                    self._pending.pop(key, None)
                    item.reject(McpPluginError(McpErrorCode.REAUTHORIZATION_REQUIRED, "the authorization expired"))
            pending = self._pending.pop(state, None) if isinstance(state, str) else None
            if pending is None:
                raise McpPluginError(McpErrorCode.OAUTH_STATE_INVALID,
                                     "unknown, expired or already used authorization state")
            if error is not None:
                reason = error if isinstance(error, str) and _AS_ERROR.fullmatch(error) else "refused"
                refusal = McpPluginError(McpErrorCode.OAUTH_DENIED, f"the authorization server refused ({reason})")
                pending.reject(refusal)
                await self._await_owner(pending.connection)
                raise refusal
            if iss is not None and not isinstance(iss, str):
                iss = str(iss)
            try:
                check_authorization_issuer(expected=pending.issuer, supported=pending.iss_supported, received=iss)
            except McpPluginError as exc:
                pending.reject(exc)
                await self._await_owner(pending.connection)
                raise
            if not isinstance(code, str) or not code or len(code) > 4096:
                refusal = McpPluginError(McpErrorCode.PLUGIN_INVALID, "the authorization response has no code")
                pending.reject(refusal)
                raise refusal
            pending.resolve((code, pending.state))
            await self._await_owner(pending.connection, until_connected=True)
            plugin = await self._require(pending.plugin_id)
        self._emit(PLUGIN_OAUTH_COMPLETED, "retour d'autorisation OAuth traité",
                   data={"plugin_id": plugin.plugin_id, "connection_status": plugin.connection_status.value,
                         "auth_status": plugin.auth_status.value})
        return plugin

    async def _await_owner(self, connection: _Connection, *, until_connected: bool = False) -> None:
        """Attend (borné) que la tâche propriétaire ait fini ou se soit connectée : la réponse dit l'état réel."""

        waits = [connection.task] if connection.task is not None else []
        if until_connected:
            connection.progress.clear()
            waits.append(asyncio.ensure_future(connection.progress.wait()))
        if not waits:
            return
        _, pending = await asyncio.wait(waits, timeout=COMPLETE_WAIT_S, return_when=asyncio.FIRST_COMPLETED)
        for item in waits[1:]:
            if not item.done():
                item.cancel()

    async def _oauth_payload(self, plugin_id: str) -> dict[str, Any] | None:
        plugin = await self._repository.get_plugin(plugin_id)
        if plugin is None or plugin.credential_ref is None or not self.vault_available:
            return None
        secret = await self._vault.get_secret(plugin)
        if not secret or secret.get("kind") != "oauth" or not isinstance(secret.get("oauth"), dict):
            return None
        return secret["oauth"]

    async def _store_oauth(self, plugin_id: str, oauth: dict[str, Any]) -> None:
        """Rescelle la charge `oauth` (nouvelle référence), attache-la au plugin, retire l'ancien blob."""

        async with self._lock:
            current = await self._require(plugin_id)
            new_ref = await self._vault.replace_secret(current, {"kind": "oauth", "oauth": oauth})
            plugin = bind_credential(current, strategy=AuthStrategy.OAUTH, credential_ref=new_ref, now=self._clock())
            try:
                await self._repository.save_plugin(plugin)
            except BaseException as exc:
                await self._discard(new_ref, plugin_id, exc)
                raise
            await self._discard(current.credential_ref, plugin_id)
            self._bump()

    async def _revoke(self, plugin_id: str) -> None:
        """RFC 7009 au mieux (ARCH §16 E10) : un échec est journalisé par code et ne bloque jamais l'oubli local."""

        if self._connector is None:
            return
        plugin = await self._repository.get_plugin(plugin_id)
        payload = await self._oauth_payload(plugin_id)
        if plugin is None or not payload or not payload.get("revocation_endpoint"):
            return
        try:
            await asyncio.wait_for(self._connector.revoke(plugin, payload), REVOKE_TIMEOUT_S)
        except (RemoteMcpError, McpPluginError) as exc:
            self._emit(PLUGIN_REVOCATION_FAILED, "révocation OAuth refusée : oubli local seulement", level="warning",
                       data={"plugin_id": plugin_id, "code": exc.code.value})
            return
        except TimeoutError:
            self._emit(PLUGIN_REVOCATION_FAILED, "révocation OAuth sans réponse : oubli local seulement",
                       level="warning", data={"plugin_id": plugin_id, "code": McpErrorCode.REMOTE_TIMEOUT.value})
            return
        self._emit(PLUGIN_REVOKED, "jetons OAuth révoqués auprès du serveur d'autorisation",
                   data={"plugin_id": plugin_id})

    # ------------------------------------------------------------ outils

    async def refresh(self, plugin_id: str) -> McpPlugin:
        """Relit la liste d'outils sur la session ouverte."""

        async with self._operation("refresh", plugin_id):
            plugin = await self._require(plugin_id)
            if self._connector is None:
                raise self._no_connector()
            connection = self._connections.get(plugin_id)
            session = connection.session if connection is not None else None
            if session is None or plugin.connection_status is not ConnectionStatus.CONNECTED:
                raise McpPluginError(McpErrorCode.PLUGIN_DISCONNECTED, "the plugin is not connected")
            try:
                updated = await self._relist(connection, session)
            except RemoteMcpError as exc:
                raise McpPluginError(exc.code, _failure_sentence(exc.code)) from None
            return updated or await self._require(plugin_id)

    def _ready_session(self, plugin: McpPlugin) -> RemoteMcpSession:
        """Session ouverte d'un plugin appelable, sinon le refus codé — **avant** tout réseau."""

        if not plugin.enabled:
            raise McpPluginError(McpErrorCode.PLUGIN_DISABLED, "the plugin is disabled")
        if plugin.auth_status is AuthStatus.EXPIRED:
            raise McpPluginError(McpErrorCode.REAUTHORIZATION_REQUIRED,
                                 "the plugin authorization expired: reconnect it")
        connection = self._connections.get(plugin.plugin_id)
        session = connection.session if connection is not None else None
        if session is None or plugin.connection_status is not ConnectionStatus.CONNECTED:
            raise McpPluginError(McpErrorCode.PLUGIN_DISCONNECTED, "the plugin is not connected")
        return session

    async def invoke(self, plugin_id: str, name: str, arguments: dict[str, Any], *,
                     timeout_s: float = DEFAULT_CALL_TIMEOUT_S) -> dict[str, Any]:
        """Appel brut d'un outil distant ; état vérifié **avant** tout réseau (brique de `call`).

        `expired` ⇒ `mcp_plugin_reauthorization_required` aussitôt : un appel
        n'attend jamais un navigateur. Rend le `CallToolResult` sérialisé.
        """

        started = self._monotonic()
        async with self._operation("invoke", plugin_id):
            session = self._ready_session(await self._require(plugin_id))
            code: McpErrorCode | None = None
            try:
                return await self._call_session(session, name, arguments, timeout_s)
            except McpPluginError as exc:
                code = exc.code
                raise
            finally:
                self._emit(PLUGIN_TOOL_CALLED, "outil de plugin MCP appelé",
                           data={"plugin_id": plugin_id, "tool": name[:128], "ok": code is None,
                                 "code": None if code is None else code.value,
                                 "duration_ms": round((self._monotonic() - started) * 1000)})

    @staticmethod
    async def _call_session(session: RemoteMcpSession, name: str, arguments: dict[str, Any],
                            timeout_s: float) -> dict[str, Any]:
        bounded = min(max(float(timeout_s), 0.1), MAX_CALL_TIMEOUT_S)
        try:
            return await session.call_tool(name, arguments, bounded)
        except RemoteMcpError as exc:
            raise McpPluginError(exc.code, _failure_sentence(exc.code)) from None

    # ------------------------------------------------------------ catalogue externe et appel (Slice 04)

    async def external_tools(self, since_revision: int | None = None) -> dict[str, Any]:
        """`GET /v1/mcp/tools` : descripteurs des plugins activés ∧ connectés, et l'état de **tous** les plugins.

        `since_revision` égal à la révision courante ⇒ `unchanged: true`, listes
        vides (l'appelant garde sa copie) : la passerelle et le Control Center
        relisent à chaque requête sans recopier le catalogue.
        """

        async with self._operation("external_tools"):
            revision = self._revision
            if since_revision is not None and since_revision == revision:
                return {"catalog_revision": revision, "unchanged": True, "plugins": [], "tools": []}
            plugins = await self._repository.list_plugins()
            summaries: list[dict[str, Any]] = []
            tools: list[dict[str, Any]] = []
            for plugin in sorted(plugins, key=lambda item: item.plugin_id):
                exposed = plugin.enabled and plugin.connection_status is ConnectionStatus.CONNECTED
                payload_tools = plugin.to_payload()["tools"] if exposed else []
                summaries.append({"plugin_id": plugin.plugin_id, "display_name": plugin.display_name,
                                  "enabled": plugin.enabled, "connection_status": plugin.connection_status.value,
                                  "auth_status": plugin.auth_status.value, "tool_count": len(payload_tools)})
                tools.extend(payload_tools)
            # Révision lue avant la lecture du registre : un changement concurrent
            # donne au pire une révision plus ancienne que les données, relue au prochain appel.
            return {"catalog_revision": revision, "unchanged": False, "plugins": summaries, "tools": tools}

    async def call(self, tool_id: object, arguments: object, *, caller: dict[str, Any] | None = None,
                   timeout_s: float | None = None) -> dict[str, Any]:
        """`POST /v1/mcp/tools/call` ⇒ `ToolCallOutcome` (`docs/mcp/plugins.md` §7).

        Avant tout réseau : nom natif refusé (`native_tool_call_directly`),
        outil inconnu, plugin désactivé / déconnecté / à réautoriser, arguments
        (objet, ≤ 64 Kio, requis, fermés). Une erreur distante (`isError`) est
        `ok: false` `mcp_remote_tool_error`, texte masqué et borné. Journal
        `mcp.plugin.tool_called` : identifiants, codes, durée, octets — jamais
        d'argument ni de texte de résultat.
        """

        started = self._monotonic()
        agent = str((caller or {}).get("agent", "unknown"))[:16]
        async with self._operation("call"):
            plugin_id, name = parse_tool_id(tool_id)
            plugin = await self._repository.get_plugin(plugin_id)
            if plugin is None:
                raise McpPluginError(McpErrorCode.TOOL_UNKNOWN, f"unknown plugin tool {str(tool_id)[:200]!r}")
            session = self._ready_session(plugin)
            descriptor = next((tool for tool in plugin.tools if tool.get("name") == name), None)
            if descriptor is None:
                raise McpPluginError(McpErrorCode.TOOL_UNKNOWN, f"unknown plugin tool {str(tool_id)[:200]!r}")
            check_tool_arguments(descriptor.get("input_schema") or {}, arguments)
            bounded = DEFAULT_CALL_TIMEOUT_S if timeout_s is None else timeout_s
            code: McpErrorCode | None = None
            size = 0
            try:
                result = await self._call_session(session, name, arguments, bounded)
                outcome = call_outcome(result, known_secrets=await self._known_secrets(plugin))
                code = None if outcome["ok"] else McpErrorCode(outcome["code"])
                size = sum(len(block["text"].encode("utf-8")) for block in outcome["content"])
                return outcome
            except McpPluginError as exc:
                code = exc.code
                raise
            finally:
                self._emit(PLUGIN_TOOL_CALLED, "outil de plugin MCP appelé",
                           level="info" if code is None else "warning",
                           data={"plugin_id": plugin_id, "tool": name, "ok": code is None,
                                 "code": None if code is None else code.value, "agent": agent,
                                 "duration_ms": round((self._monotonic() - started) * 1000), "bytes": size})

    async def _known_secrets(self, plugin: McpPlugin) -> list[str]:
        """Valeurs du coffre de ce plugin (jetons, valeur statique) : à masquer dans un texte d'erreur distant."""

        if plugin.credential_ref is None or not self.vault_available:
            return []
        secret = await self._vault.get_secret(plugin)
        if not secret:
            return []
        values: list[str] = []
        static = secret.get("static")
        if isinstance(static, dict) and isinstance(static.get("value"), str):
            values.append(static["value"])
        oauth = secret.get("oauth")
        tokens = oauth.get("tokens") if isinstance(oauth, dict) else None
        if isinstance(tokens, dict):
            values.extend(value for key, value in tokens.items()
                          if key in ("access_token", "refresh_token", "id_token") and isinstance(value, str))
        return values


def _failure_sentence(code: McpErrorCode) -> str:
    return {
        McpErrorCode.REAUTHORIZATION_REQUIRED: "the plugin needs a new authorization",
        McpErrorCode.OAUTH_DENIED: "the authorization server refused the authorization",
        McpErrorCode.OAUTH_ISSUER_MISMATCH: "the authorization server identity does not match",
        McpErrorCode.ENDPOINT_FORBIDDEN: "the plugin address is not a public internet address",
        McpErrorCode.ENDPOINT_INVALID: "the plugin (or its authorization server) URL is refused",
        McpErrorCode.TRANSPORT_UNSUPPORTED: "the server does not speak the Streamable HTTP MCP transport",
        McpErrorCode.REMOTE_UNREACHABLE: "the plugin server could not be reached",
        McpErrorCode.REMOTE_TLS: "the plugin server TLS certificate was refused",
        McpErrorCode.REMOTE_PROTOCOL: "the plugin server answered something that is not valid MCP",
        McpErrorCode.RESPONSE_TOO_LARGE: "the plugin server answer exceeds 4 MiB",
        McpErrorCode.REMOTE_TIMEOUT: "the plugin server did not answer in time",
        McpErrorCode.VAULT_UNAVAILABLE: "no local secret vault to store the authorization",
    }.get(code, f"remote MCP failure ({code.value})")


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
