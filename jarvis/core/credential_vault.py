"""Coffre des identifiants de plugins MCP (generic-mcp-plugin-runtime, Slice 02 ; ARCH §3.3).

`CredentialVault` scelle une charge JSON par `Sealer` (DPAPI CurrentUser en
production) et range le blob dans `SealedSecretStore` (`mcp_credentials`). La
ligne du plugin ne porte que `credential_ref`, référence opaque
`cred_<32 hex>`.

Charge scellée (`docs/mcp/plugins.md` §3.2) :
`{"v": 1, "plugin_id", "endpoint_origin", "kind": "static"|"oauth", "static": {...} | "oauth": {...}}`.
Le rattachement `{plugin_id, endpoint_origin}` est vérifié à chaque lecture :
un blob recopié vers un autre plugin, ou un plugin dont l'origine a changé,
ne rend **rien** (`None`).

Refus : `Sealer` absent ou indisponible ⇒ `McpPluginError(mcp_vault_unavailable)`,
jamais de repli en clair. Aucun secret n'entre dans un message, une
exception ou un événement du journal : seuls `plugin_id`, `credential_ref` et
des codes y figurent.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import secrets
from typing import Any

from jarvis.domain.mcp_plugins import McpErrorCode, McpPlugin, McpPluginError, canonical_json
from jarvis.ports.mcp_plugins import Sealer, SealedSecretStore, SealerError
from jarvis.ports.v2 import DiagnosticSink

SEALED_PAYLOAD_VERSION = 1
SECRET_KINDS = frozenset({"static", "oauth"})

#: Événements du journal (données : identifiants et codes seulement).
VAULT_UNSEAL_FAILED = "mcp.vault.unseal_failed"
VAULT_BINDING_MISMATCH = "mcp.vault.binding_mismatch"
VAULT_CREDENTIAL_MISSING = "mcp.vault.credential_missing"


def new_credential_ref() -> str:
    return f"cred_{secrets.token_hex(16)}"


class CredentialVault:
    def __init__(self, store: SealedSecretStore, sealer: Sealer | None, *,
                 diagnostics: DiagnosticSink | None = None,
                 new_ref: Callable[[], str] = new_credential_ref) -> None:
        self._store = store
        self._sealer = sealer
        self._diagnostics = diagnostics
        self._new_ref = new_ref

    @property
    def available(self) -> bool:
        return self._sealer is not None and bool(self._sealer.available)

    def _require_sealer(self) -> Sealer:
        sealer = self._sealer
        if sealer is None or not sealer.available:
            raise McpPluginError(McpErrorCode.VAULT_UNAVAILABLE,
                                 "no local secret vault on this machine: credentials cannot be stored")
        return sealer

    def _emit(self, kind: str, message: str, *, level: str, data: dict[str, Any]) -> None:
        if self._diagnostics is not None:
            self._diagnostics.emit(kind, message, level=level, data=data)

    async def put_secret(self, plugin: McpPlugin, payload: Mapping[str, Any]) -> str:
        """Scelle `payload` (`{"kind": ..., "<kind>": {...}}`) pour ce plugin ; rend la nouvelle référence."""

        sealer = self._require_sealer()
        kind = payload.get("kind")
        if kind not in SECRET_KINDS or set(payload) != {"kind", kind}:
            raise McpPluginError(McpErrorCode.PLUGIN_INVALID, "sealed payload must be {kind, <kind>: {...}}")
        body = {"v": SEALED_PAYLOAD_VERSION, "plugin_id": plugin.plugin_id,
                "endpoint_origin": plugin.endpoint_origin, **payload}
        try:
            blob = sealer.seal(canonical_json(body).encode("utf-8"))
        except SealerError as exc:
            raise McpPluginError(McpErrorCode.VAULT_UNAVAILABLE,
                                 f"the local vault refused to seal the credential: {exc}") from exc
        ref = self._new_ref()
        await self._store.put(ref, plugin.plugin_id, sealer.scheme, blob)
        return ref

    async def replace_secret(self, plugin: McpPlugin, payload: Mapping[str, Any]) -> str:
        """Nouveau blob, nouvelle référence ; l'ancien reste jusqu'à `discard` (après l'écriture du plugin)."""

        return await self.put_secret(plugin, payload)

    async def get_secret(self, plugin: McpPlugin) -> dict[str, Any] | None:
        """La charge descellée, ou `None` (pas de référence, blob absent, altéré ou rattaché ailleurs)."""

        ref = plugin.credential_ref
        if ref is None:
            return None
        sealer = self._require_sealer()
        row = await self._store.get(ref)
        ids = {"plugin_id": plugin.plugin_id, "credential_ref": ref}
        if row is None:
            self._emit(VAULT_CREDENTIAL_MISSING, "identifiant scellé introuvable pour ce plugin",
                       level="warning", data={**ids, "code": "credential_missing"})
            return None
        if row.plugin_id != plugin.plugin_id:
            self._emit(VAULT_BINDING_MISMATCH, "identifiant scellé rattaché à un autre plugin : ignoré",
                       level="warning", data={**ids, "code": "binding_mismatch"})
            return None
        try:
            body = json.loads(sealer.unseal(row.blob).decode("utf-8"))
        except (SealerError, UnicodeDecodeError, ValueError) as exc:
            self._emit(VAULT_UNSEAL_FAILED, "identifiant scellé illisible (blob altéré ou autre session Windows)",
                       level="error", data={**ids, "code": "unseal_failed", "exception_type": type(exc).__name__})
            return None
        if (not isinstance(body, dict) or body.get("v") != SEALED_PAYLOAD_VERSION
                or body.get("plugin_id") != plugin.plugin_id or body.get("endpoint_origin") != plugin.endpoint_origin
                or body.get("kind") not in SECRET_KINDS):
            self._emit(VAULT_BINDING_MISMATCH, "identifiant scellé pour un autre plugin ou une autre origine : ignoré",
                       level="warning", data={**ids, "code": "binding_mismatch"})
            return None
        return {"kind": body["kind"], body["kind"]: body.get(body["kind"])}

    async def discard(self, ref: str | None) -> None:
        if ref is not None:
            await self._store.delete(ref)

    async def forget(self, plugin: McpPlugin) -> int:
        """Supprime tous les blobs du plugin (déconnexion). Rend le nombre de lignes supprimées."""

        return await self._store.delete_for_plugin(plugin.plugin_id)
