"""OAuth des plugins MCP distants sur le SDK `mcp` (Slice 03 ; `docs/mcp/plugins.md` §3.3-§3.4, ARCH §5.3, §14 C9).

Le protocole est celui de `mcp.client.auth.OAuthClientProvider` (mcp 1.30),
**sous-classé, jamais réimplémenté** : découverte de la ressource protégée
(RFC 9728), liaison `resource` (RFC 8707), validation de l'émetteur des
métadonnées (RFC 8414 §3.3), enregistrement dynamique (RFC 7591), PKCE S256,
`state` comparé en temps constant, scope, montée de scope sur
`403 insufficient_scope`.

Ce que Jarvis ajoute (lacunes C9 du SDK) :

- `VaultTokenStorage` : jetons, `expires_at` et informations client scellés
  dans le coffre de Core (via `OAuthCredentialStore`) ; le SDK recharge les
  jetons **sans** échéance, `JarvisOAuthProvider._initialize` la restaure ;
- mode **non interactif** : sans invite interactive, une 401 (ou
  `403 insufficient_scope`) lève `mcp_plugin_reauthorization_required`
  aussitôt — ni découverte, ni enregistrement, ni navigateur ; un jeton échu
  sans jeton de rafraîchissement lève avant tout envoi ;
- `grant_types` de l'enregistrement : `refresh_token` seulement si les
  métadonnées du serveur d'autorisation le listent (READINESS Q2) ;
- RFC 9207 : le drapeau `authorization_response_iss_parameter_supported` et
  l'émetteur brut sont lus dans les métadonnées et remis à l'invite, qui
  vérifie `iss` au retour (`McpPluginService.complete_oauth`) ;
- `redirect_uri` changé (port de l'UI) ⇒ l'ancien enregistrement est ignoré
  et le SDK réenregistre le client ;
- révocation RFC 7009 au mieux (`revoke_tokens`, ARCH §16 E10).

Aucune valeur de jeton n'entre dans un message d'exception levé ici.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
import json
import time
from typing import Any

import httpx
from mcp.client.auth import OAuthClientProvider
from mcp.client.auth.utils import extract_field_from_www_auth
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from pydantic import ValidationError

from jarvis.domain.mcp_plugins import McpErrorCode, McpPluginError
from jarvis.ports.mcp_plugins import AuthorizationPrompt, OAuthCredentialStore, RemoteMcpError

CLIENT_NAME = "Jarvis"
AUTHORIZATION_CODE = "authorization_code"
REFRESH_TOKEN = "refresh_token"
_AS_METADATA_PATHS = ("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration")


def reauthorization_required(reason: str) -> McpPluginError:
    return McpPluginError(McpErrorCode.REAUTHORIZATION_REQUIRED, f"the plugin needs a new authorization: {reason}")


def empty_oauth_payload(redirect_uri: str) -> dict[str, Any]:
    return {"tokens": None, "expires_at": None, "client_info": None, "issuer": None, "iss_supported": False,
            "revocation_endpoint": None, "redirect_uri": redirect_uri}


class VaultTokenStorage:
    """`TokenStorage` du SDK adossé à la charge `oauth` scellée d'un plugin."""

    def __init__(self, store: OAuthCredentialStore, *, redirect_uri: str,
                 clock: Callable[[], float] = time.time) -> None:
        self._store = store
        self._redirect_uri = redirect_uri
        self._clock = clock
        self._payload: dict[str, Any] | None = None
        #: Vrai quand un enregistrement client a été ignoré (redirect_uri changé).
        self.client_info_dropped = False

    async def _load(self) -> dict[str, Any]:
        if self._payload is None:
            stored = await self._store.load()
            payload = empty_oauth_payload(self._redirect_uri)
            if isinstance(stored, dict):
                payload.update({key: stored[key] for key in payload if key in stored})
            self._payload = payload
        return self._payload

    async def _save(self) -> None:
        await self._store.save(dict(await self._load()))

    @property
    def expires_at(self) -> float | None:
        value = (self._payload or {}).get("expires_at")
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    async def get_tokens(self) -> OAuthToken | None:
        raw = (await self._load()).get("tokens")
        if not isinstance(raw, dict):
            return None
        try:
            return OAuthToken.model_validate(raw)
        except ValidationError:
            # Argued: an unreadable stored token is the same as no token; the
            # next 401 asks for a new authorization, which is the only repair.
            return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        payload = await self._load()
        payload["tokens"] = tokens.model_dump(mode="json", exclude_none=True)
        payload["expires_at"] = self._clock() + tokens.expires_in if tokens.expires_in else None
        await self._save()

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        payload = await self._load()
        raw = payload.get("client_info")
        if not isinstance(raw, dict):
            return None
        if raw.get("redirect_uris") != [self._redirect_uri] or payload.get("redirect_uri") != self._redirect_uri:
            # The Control Center moved to another port: the registered
            # redirect URI no longer matches, so the client registers again.
            self.client_info_dropped = True
            return None
        try:
            return OAuthClientInformationFull.model_validate(raw)
        except ValidationError:
            # Argued: an unreadable registration is re-created by the SDK (DCR).
            return None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        payload = await self._load()
        payload["client_info"] = client_info.model_dump(mode="json", exclude_none=True)
        payload["redirect_uri"] = self._redirect_uri
        await self._save()

    async def remember_server(self, *, issuer: str | None, iss_supported: bool,
                              revocation_endpoint: str | None) -> None:
        payload = await self._load()
        update = {"issuer": issuer, "iss_supported": iss_supported, "revocation_endpoint": revocation_endpoint}
        if any(payload.get(key) != value for key, value in update.items()):
            payload.update(update)
            # Written with the next token or client write: a metadata read
            # alone never creates a vault entry.
            if payload.get("tokens") or payload.get("client_info"):
                await self._save()


def client_metadata(redirect_uri: str) -> OAuthClientMetadata:
    """Métadonnées d'enregistrement (ARCH §5.3). `grant_types` est ajusté après lecture des métadonnées AS."""

    return OAuthClientMetadata(redirect_uris=[redirect_uri], token_endpoint_auth_method="none",
                               grant_types=[AUTHORIZATION_CODE], response_types=["code"], client_name=CLIENT_NAME)


def _is_as_metadata(request: httpx.Request) -> bool:
    return request.method == "GET" and request.url.path.startswith(_AS_METADATA_PATHS)


def needs_authorization(response: httpx.Response) -> bool:
    if response.status_code == 401:
        return True
    return response.status_code == 403 and extract_field_from_www_auth(response, "error") == "insufficient_scope"


class JarvisOAuthProvider(OAuthClientProvider):
    """`OAuthClientProvider` + échéance restaurée, mode non interactif, Q2, lecture RFC 9207."""

    def __init__(self, server_url: str, storage: VaultTokenStorage, *, redirect_uri: str,
                 prompt: AuthorizationPrompt | None) -> None:
        super().__init__(server_url, client_metadata(redirect_uri), storage,
                         redirect_handler=self._on_redirect, callback_handler=self._on_callback)
        self._storage = storage
        self._prompt = prompt
        self.issuer: str | None = None
        self.iss_supported = False

    @property
    def interactive(self) -> bool:
        return self._prompt is not None and bool(self._prompt.interactive)

    async def _initialize(self) -> None:
        await super()._initialize()
        # C9: the SDK reloads tokens without their expiry; without this an
        # expired stored token would look valid forever.
        if self.context.current_tokens is not None:
            self.context.token_expiry_time = self._storage.expires_at

    def observe_as_metadata(self, response: httpx.Response) -> dict[str, Any] | None:
        """Lit Q2 et RFC 9207 dans la réponse brute (le modèle du SDK ignore ces champs)."""

        if response.status_code != 200:
            return None
        try:
            raw = json.loads(response.content)
        except (ValueError, httpx.ResponseNotRead):
            return None  # the SDK rejects the same body with its own error
        if not isinstance(raw, dict):
            return None
        grants = raw.get("grant_types_supported")
        refresh = isinstance(grants, list) and REFRESH_TOKEN in grants
        self.context.client_metadata.grant_types = [AUTHORIZATION_CODE, REFRESH_TOKEN] if refresh \
            else [AUTHORIZATION_CODE]
        issuer = raw.get("issuer")
        self.issuer = issuer if isinstance(issuer, str) else None
        self.iss_supported = raw.get("authorization_response_iss_parameter_supported") is True
        revocation = raw.get("revocation_endpoint")
        return {"issuer": self.issuer, "iss_supported": self.iss_supported,
                "revocation_endpoint": revocation if isinstance(revocation, str) else None}

    async def _auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        if not self._initialized:
            await self._initialize()
        if (not self.interactive and self.context.current_tokens is not None
                and not self.context.is_token_valid() and not self.context.can_refresh_token()):
            raise reauthorization_required("the stored access token expired and cannot be refreshed")
        flow = super()._auth_flow(request)
        try:
            outgoing = await flow.__anext__()
            while True:
                response = yield outgoing
                if outgoing is request and needs_authorization(response) and not self.interactive:
                    raise reauthorization_required(f"the server answered {response.status_code}")
                if _is_as_metadata(outgoing) and response.status_code == 200:
                    await response.aread()  # the SDK reads it again from the cache
                    server = self.observe_as_metadata(response)
                    if server is not None:
                        await self._storage.remember_server(**server)
                outgoing = await flow.asend(response)
        except StopAsyncIteration:
            return
        finally:
            await flow.aclose()

    async def _on_redirect(self, authorization_url: str) -> None:
        if not self.interactive or self._prompt is None:
            raise reauthorization_required("no interactive authorization is allowed here")
        await self._prompt.authorization_url(authorization_url, issuer=self.issuer, iss_supported=self.iss_supported)

    async def _on_callback(self) -> tuple[str, str | None]:
        if self._prompt is None:
            raise reauthorization_required("no interactive authorization is allowed here")
        return await self._prompt.wait_callback()


async def revoke_tokens(client: httpx.AsyncClient, oauth: dict[str, Any]) -> int:
    """RFC 7009 au mieux : révoque le jeton de rafraîchissement puis d'accès. Rend le nombre révoqué.

    Sans `revocation_endpoint` annoncé, ne fait rien (0). Lève `RemoteMcpError`
    si le serveur refuse ; l'appelant journalise le code et oublie localement.
    """

    endpoint = oauth.get("revocation_endpoint")
    tokens = oauth.get("tokens") if isinstance(oauth.get("tokens"), dict) else {}
    client_info = oauth.get("client_info") if isinstance(oauth.get("client_info"), dict) else {}
    if not isinstance(endpoint, str) or not tokens:
        return 0
    revoked = 0
    for hint in (REFRESH_TOKEN, "access_token"):
        token = tokens.get(hint)
        if not isinstance(token, str) or not token:
            continue
        data = {"token": token, "token_type_hint": hint}
        if isinstance(client_info.get("client_id"), str):
            data["client_id"] = client_info["client_id"]
        response = await client.post(endpoint, data=data)
        if response.status_code != 200:
            raise RemoteMcpError(McpErrorCode.REMOTE_PROTOCOL,
                                 f"token revocation answered HTTP {response.status_code}")
        revoked += 1
    return revoked
