"""Ports des plugins MCP distants (handoff jarvis-generic-mcp-plugin-runtime ; ARCH §2, §3.3, §5.4).

Coutures, sans implémentation ici :

- `McpPluginRepository` : définitions durables des plugins (Core,
  `jarvis.sqlite3`, migration v4) — `jarvis/adapters/sqlite_mcp_plugins.py` ;
- `SealedSecretStore` : blobs scellés (`mcp_credentials`), même adaptateur ;
- `Sealer` : scellement local des secrets (DPAPI CurrentUser sous Windows,
  `jarvis/adapters/dpapi_sealer.py`) ;
- `RemoteMcpConnector` / `RemoteMcpSession` / `AuthorizationPrompt` /
  `OAuthCredentialStore` : connexion distante (Slice 03), adaptateur
  `jarvis/adapters/remote_mcp.py` (SDK `mcp`, OAuth `jarvis/adapters/mcp_oauth.py`).

Contrat canonique : `docs/mcp/plugins.md` §2.3, §3.2.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from jarvis.domain.mcp_plugins import McpErrorCode, McpPlugin

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


class RemoteMcpError(RuntimeError):
    """Échec d'une connexion ou d'un appel distant, réduit à un code stable (`docs/mcp/plugins.md` §8.2).

    Levée par l'adaptateur (`jarvis/adapters/remote_mcp.py`) à la place de
    toute exception du SDK, de httpx ou d'un groupe d'exceptions anyio. Le
    message est une phrase Jarvis courte ; il ne recopie jamais un corps
    distant ni un secret (le type d'exception d'origine suffit au diagnostic).
    """

    def __init__(self, code: McpErrorCode | str, message: str = "") -> None:
        self.code = McpErrorCode(code)
        super().__init__(message or self.code.value)


class OAuthCredentialStore(Protocol):
    """Accès de l'adaptateur OAuth à la charge `oauth` scellée d'**un** plugin (coffre de Core).

    Charge : `{"tokens", "expires_at", "client_info", "issuer", "iss_supported",
    "revocation_endpoint", "redirect_uri"}` (ARCH §3.3). `save` remplace la
    charge entière et rescelle ; l'adaptateur ne voit jamais le coffre.
    """

    async def load(self) -> dict[str, Any] | None: ...

    async def save(self, oauth: dict[str, Any]) -> None: ...


@dataclass(frozen=True, slots=True)
class AuthMaterial:
    """Ce que le connecteur reçoit pour s'authentifier ; ne quitte jamais Core.

    `strategy` : `none`, `oauth` (fournisseur OAuth du SDK sur le client),
    `bearer` ou `header` (en-têtes statiques). `static_headers` : posés sur
    les requêtes vers l'origine du plugin seulement (un serveur
    d'autorisation ne les voit jamais). `oauth` : charge scellée du plugin.
    """

    strategy: str
    static_headers: tuple[tuple[str, str], ...] = ()
    oauth: OAuthCredentialStore | None = None

    def __repr__(self) -> str:  # un repr de débogage ne doit jamais afficher un secret
        return f"AuthMaterial(strategy={self.strategy!r}, static_headers=<{len(self.static_headers)}>)"


class AuthorizationPrompt(Protocol):
    """Pont entre le flux OAuth du SDK et Core (`docs/mcp/plugins.md` §3.3-§3.4).

    `interactive` faux ⇒ l'adaptateur n'entame **aucun** flux (ni découverte
    ni navigateur) : il lève `mcp_plugin_reauthorization_required` à la
    première réponse 401/403 `insufficient_scope`.
    """

    @property
    def interactive(self) -> bool: ...

    async def authorization_url(self, url: str, *, issuer: str | None, iss_supported: bool) -> None:
        """L'URL d'autorisation est prête (PKCE, `state`, `resource`, scope). Peut lever pour refuser."""
        ...

    async def wait_callback(self) -> tuple[str, str | None]:
        """Attend `(code, state)` rendu par `complete_oauth` ; lève un `McpPluginError` si refusé ou expiré."""
        ...


class RemoteMcpSession(Protocol):
    async def initialize(self) -> dict[str, Any]:
        """`{name, version, protocol_version, icon_url}` du serveur (valeurs brutes, bornées par le domaine)."""
        ...

    async def list_tools_all(self) -> list[dict[str, Any]]:
        """Outils bruts, pagination suivie sur 10 pages au plus."""
        ...

    async def call_tool(self, name: str, arguments: dict[str, Any], timeout_s: float) -> dict[str, Any]: ...

    def on_tools_changed(self, callback: Callable[[], Awaitable[None]]) -> None: ...

    async def wait_failure(self) -> McpErrorCode:
        """Rend la main quand la session est cassée (réponse illisible, refus de politique, fermeture)."""
        ...


class RemoteMcpConnector(Protocol):
    def open(self, plugin: McpPlugin, auth: AuthMaterial,
             prompt: AuthorizationPrompt | None) -> AbstractAsyncContextManager[RemoteMcpSession]:
        """Contexte à entrer **et** quitter dans une seule tâche (transport anyio). Lève `RemoteMcpError`."""
        ...

    async def revoke(self, plugin: McpPlugin, oauth: Mapping[str, Any]) -> None:
        """Révocation RFC 7009 au mieux (ARCH §16 E10) ; lève `RemoteMcpError` si le serveur refuse."""
        ...
