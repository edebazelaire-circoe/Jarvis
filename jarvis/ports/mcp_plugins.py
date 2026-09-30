"""Ports des plugins MCP distants (handoff jarvis-generic-mcp-plugin-runtime ; ARCH §2, §3.3, §5.4).

Coutures, sans implémentation ici :

- `McpPluginRepository` : définitions durables des plugins (Core,
  `jarvis.sqlite3`, migration v4) — `jarvis/adapters/sqlite_mcp_plugins.py` ;
- `SealedSecretStore` : blobs scellés (`mcp_credentials`), même adaptateur ;
- `Sealer` : scellement local des secrets (DPAPI CurrentUser sous Windows,
  `jarvis/adapters/dpapi_sealer.py`) ;
- `RemoteMcpConnector` / `RemoteMcpSession` / `AuthorizationPrompt` :
  déclarés ici pour la Slice 03 (SDK `mcp`, OAuth), sans adaptateur encore.

Contrat canonique : `docs/mcp/plugins.md` §2.3, §3.2.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from jarvis.domain.mcp_plugins import McpPlugin

# ------------------------------------------------------------------ erreurs de stockage


class McpPluginStoreError(RuntimeError):
    """Une ligne stockée est illisible ou contredit ses colonnes clés.

    Même famille que `BoardStoreError` : fichier abîmé, rendu 500 et jamais
    « réparé » par le magasin (état canonique).
    """

    code = "mcp_plugin_store_unreadable"

    def __init__(self, table: str, key: str, reason: str) -> None:
        super().__init__(f"{table} row {key!r} is unreadable: {reason}")
        self.table = table
        self.key = key


class McpPluginStoreUnavailable(McpPluginStoreError):
    """SQLite a refusé l'opération (base verrouillée, E/S) ; la cause reste dans le message."""

    code = "mcp_plugin_store_failed"

    def __init__(self, operation: str, reason: str) -> None:
        RuntimeError.__init__(self, f"mcp plugin store {operation} failed: {reason}")
        self.table = "mcp_plugin_store"
        self.key = operation


class SealerError(RuntimeError):
    """Scellement ou descellement refusé (blob altéré, autre utilisateur, API absente)."""


# ------------------------------------------------------------------ registre


class McpPluginRepository(Protocol):
    """Magasin durable des plugins. Lecture : `None` si absent ; c'est le service qui lève `mcp_plugin_unknown`."""

    async def list_plugins(self) -> Sequence[McpPlugin]: ...

    async def get_plugin(self, plugin_id: str) -> McpPlugin | None: ...

    async def insert_plugin(self, plugin: McpPlugin) -> None:
        """Nouvelle ligne ; endpoint ou id déjà pris ⇒ `McpPluginError(mcp_plugin_duplicate)`."""
        ...

    async def save_plugin(self, plugin: McpPlugin) -> None:
        """Remplace une ligne existante ; absente ⇒ `McpPluginError(mcp_plugin_unknown)`."""
        ...

    async def save_plugins(self, plugins: Sequence[McpPlugin]) -> None:
        """Remplace plusieurs lignes existantes en **une** transaction (remise à zéro au démarrage)."""
        ...

    async def delete_plugin(self, plugin_id: str) -> bool:
        """Supprime la ligne **et** ses identifiants scellés en une transaction. Vrai si elle existait."""
        ...


# ------------------------------------------------------------------ coffre


@dataclass(frozen=True, slots=True)
class SealedSecret:
    """Ligne de `mcp_credentials` : un blob opaque et son rattachement."""

    credential_ref: str
    plugin_id: str
    scheme: str
    blob: bytes


class SealedSecretStore(Protocol):
    """Blobs scellés (ARCH §3.3). Ne descelle jamais : c'est le rôle de `CredentialVault`."""

    async def put(self, ref: str, plugin_id: str, scheme: str, blob: bytes) -> None: ...

    async def get(self, ref: str) -> SealedSecret | None: ...

    async def delete(self, ref: str) -> None: ...

    async def delete_for_plugin(self, plugin_id: str) -> int: ...


class Sealer(Protocol):
    """Scellement local. `available` faux ⇒ aucun secret n'est accepté (pas de repli en clair)."""

    @property
    def available(self) -> bool: ...

    @property
    def scheme(self) -> str: ...

    def seal(self, plaintext: bytes) -> bytes:
        """Lève `SealerError` en cas d'échec."""
        ...

    def unseal(self, blob: bytes) -> bytes:
        """Lève `SealerError` sur un blob altéré ou illisible."""
        ...


# ------------------------------------------------------------------ connexion distante (Slice 03)


@dataclass(frozen=True, slots=True)
class AuthMaterial:
    """Ce que le connecteur reçoit pour s'authentifier ; ne quitte jamais Core.

    `static_headers` : en-têtes posés sur les requêtes MCP seulement (jamais
    sur le client HTTP : un serveur d'autorisation ne les voit pas).
    `oauth` : accès au coffre pour le `TokenStorage` du SDK (Slice 03).
    """

    strategy: str
    static_headers: tuple[tuple[str, str], ...] = ()
    oauth: Any = None

    def __repr__(self) -> str:  # un repr de débogage ne doit jamais afficher un secret
        return f"AuthMaterial(strategy={self.strategy!r}, static_headers=<{len(self.static_headers)}>)"


class AuthorizationPrompt(Protocol):
    """Mode interactif d'un `connect` explicite : l'URL d'autorisation part vers l'UI."""

    async def authorization_url(self, url: str) -> None: ...

    async def wait_callback(self) -> tuple[str, str | None]:
        """Attend `(code, state)` rendu par `complete_oauth`."""
        ...


class RemoteMcpSession(Protocol):
    async def initialize(self) -> dict[str, Any]: ...

    async def list_tools_all(self) -> list[dict[str, Any]]: ...

    async def call_tool(self, name: str, arguments: dict[str, Any], timeout_s: float) -> dict[str, Any]: ...

    def on_tools_changed(self, callback: Callable[[], Awaitable[None]]) -> None: ...


class RemoteMcpConnector(Protocol):
    def open(self, plugin: McpPlugin, auth: AuthMaterial,
             prompt: AuthorizationPrompt | None) -> AbstractAsyncContextManager[RemoteMcpSession]: ...
