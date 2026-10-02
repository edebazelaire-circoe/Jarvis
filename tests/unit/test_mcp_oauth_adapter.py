"""Adaptateur OAuth du SDK `mcp` (Slice 03 ; `docs/mcp/plugins.md` §3.3-§3.4, ARCH §5.3, C9).

Le serveur d'autorisation est simulé par un `httpx.MockTransport` : aucun
réseau. Le flux complet (PRM → métadonnées AS → DCR → URL d'autorisation →
jeton) passe par le vrai `OAuthClientProvider` du SDK.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

pytest.importorskip("mcp")

from mcp.shared.auth import OAuthClientInformationFull, OAuthToken  # noqa: E402

from jarvis.adapters.mcp_oauth import (  # noqa: E402
    JarvisOAuthProvider, VaultTokenStorage, empty_oauth_payload, revoke_tokens,
)
from jarvis.core.credential_vault import CredentialVault  # noqa: E402
from jarvis.domain.mcp_plugins import McpErrorCode, McpPluginError, new_plugin  # noqa: E402
from jarvis.ports.mcp_plugins import RemoteMcpError  # noqa: E402
from tests.fakes.fake_sealer import MARKER, FakeSealer  # noqa: E402

SENTINEL = "SENTINEL-SECRET-7f3a"
RS = "https://mail.example.com"
AS = "https://auth.example.com"
REDIRECT = "http://127.0.0.1:17654/api/mcp/oauth/callback"
T0 = datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc)


class MemoryStore:
    """`OAuthCredentialStore` en mémoire (le vrai vit dans `McpPluginService`)."""

    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload
        self.saves = 0

    async def load(self):
        return None if self.payload is None else json.loads(json.dumps(self.payload))

    async def save(self, oauth):
        self.saves += 1
        self.payload = json.loads(json.dumps(oauth))


class Prompt:
    def __init__(self, *, interactive: bool = True) -> None:
        self.interactive = interactive
        self.urls: list[tuple[str, str | None, bool]] = []

    async def authorization_url(self, url, *, issuer, iss_supported):
        self.urls.append((url, issuer, iss_supported))

    async def wait_callback(self):
        state = parse_qs(urlsplit(self.urls[-1][0]).query)["state"][0]
        return "the-code", state


class FakeAuthority:
    """PRM + AS + DCR + jeton, comme un vrai serveur ; enregistre chaque requête."""

    def __init__(self, *, grants=("authorization_code",), iss_supported=True, refresh=False, expires_in=3600,
                 revocation=False) -> None:
        self.grants = list(grants)
        self.iss_supported = iss_supported
        self.refresh = refresh
        self.expires_in = expires_in
        self.revocation = revocation
        self.requests: list[httpx.Request] = []
        self.registrations: list[dict] = []
        self.token_forms: list[dict] = []

    def metadata(self) -> dict:
        body = {"issuer": AS, "authorization_endpoint": f"{AS}/authorize", "token_endpoint": f"{AS}/token",
                "registration_endpoint": f"{AS}/register", "response_types_supported": ["code"],
                "grant_types_supported": self.grants, "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"],
                "authorization_response_iss_parameter_supported": self.iss_supported}
        if self.revocation:
            body["revocation_endpoint"] = f"{AS}/revoke"
        return body

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url.startswith(f"{RS}/.well-known/oauth-protected-resource"):
            return httpx.Response(200, json={"resource": f"{RS}/mcp", "authorization_servers": [AS],
                                             "scopes_supported": ["mail"]})
        if url == f"{AS}/.well-known/oauth-authorization-server":
            return httpx.Response(200, json=self.metadata())
        if url == f"{AS}/register":
            body = json.loads(request.content)
            self.registrations.append(body)
            return httpx.Response(201, json={**body, "client_id": f"client-{len(self.registrations)}"})
        if url == f"{AS}/token":
            form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
            self.token_forms.append(form)
            token = {"access_token": f"{SENTINEL}-access", "token_type": "bearer", "expires_in": self.expires_in}
            if self.refresh:
                token["refresh_token"] = f"{SENTINEL}-refresh"
            return httpx.Response(200, json=token)
        if url == f"{AS}/revoke":
            return httpx.Response(200)
        if url.startswith(f"{RS}/mcp"):
            if request.headers.get("authorization") == f"Bearer {SENTINEL}-access":
                return httpx.Response(200, json={"ok": True})
            return httpx.Response(401, headers={"www-authenticate": (
                f'Bearer resource_metadata="{RS}/.well-known/oauth-protected-resource", scope="mail"')})
        return httpx.Response(404)


def _client(authority: FakeAuthority, provider) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(authority.handler), auth=provider)


def _provider(store, prompt, *, redirect=REDIRECT, clock=lambda: 1_000.0):
    storage = VaultTokenStorage(store, redirect_uri=redirect, clock=clock)
    return JarvisOAuthProvider(f"{RS}/mcp", storage, redirect_uri=redirect, prompt=prompt), storage


async def test_full_interactive_flow_registers_with_pkce_state_resource_and_scope():
    authority, store, prompt = FakeAuthority(), MemoryStore(), Prompt()
    provider, _ = _provider(store, prompt)
    async with _client(authority, provider) as client:
        assert (await client.post(f"{RS}/mcp", json={})).status_code == 200
    (url, issuer, iss_supported), = prompt.urls
    query = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
    assert url.startswith(f"{AS}/authorize?")
    assert query["code_challenge_method"] == "S256" and len(query["code_challenge"]) >= 43
    assert query["state"] and query["resource"] == f"{RS}/mcp" and query["scope"] == "mail"
    assert query["redirect_uri"] == REDIRECT and query["client_id"] == "client-1"
    assert (issuer, iss_supported) == (AS, True)
    registration, = authority.registrations
    assert registration["grant_types"] == ["authorization_code"]  # Q2: the AS lists no refresh_token
    assert registration["token_endpoint_auth_method"] == "none" and registration["client_name"] == "Jarvis"
    assert registration["redirect_uris"] == [REDIRECT]
    form, = authority.token_forms
    assert form["grant_type"] == "authorization_code" and form["code"] == "the-code" and form["code_verifier"]
    assert store.payload["expires_at"] == 1_000.0 + 3600
    assert store.payload["tokens"]["access_token"] == f"{SENTINEL}-access"
    assert (store.payload["issuer"], store.payload["iss_supported"]) == (AS, True)


async def test_refresh_grant_is_requested_only_when_the_as_lists_it():
    authority = FakeAuthority(grants=["authorization_code", "refresh_token"], iss_supported=False)
    prompt = Prompt()
    provider, _ = _provider(MemoryStore(), prompt)
    async with _client(authority, provider) as client:
        await client.post(f"{RS}/mcp", json={})
    assert authority.registrations[0]["grant_types"] == ["authorization_code", "refresh_token"]
    assert prompt.urls[0][2] is False


async def test_storage_round_trip_through_the_vault(tmp_path):
    from jarvis.adapters.sqlite_mcp_plugins import SQLiteMcpPluginRepository
    from jarvis.adapters.sqlite_state import SQLiteStateRepository

    state = SQLiteStateRepository(tmp_path / "jarvis.sqlite3")
    await state.initialize()
    try:
        repo = SQLiteMcpPluginRepository(state)
        plugin = new_plugin(f"{RS}/mcp", plugin_id="mail", display_name=None, now=T0)
        await repo.insert_plugin(plugin)
        vault = CredentialVault(repo, FakeSealer())
        holder = {"plugin": plugin}

        class VaultStore:
            async def load(self):
                secret = await vault.get_secret(holder["plugin"])
                return None if secret is None else secret["oauth"]

            async def save(self, oauth):
                ref = await vault.put_secret(holder["plugin"], {"kind": "oauth", "oauth": oauth})
                holder["plugin"] = replace(holder["plugin"], credential_ref=ref)

        first = VaultTokenStorage(VaultStore(), redirect_uri=REDIRECT, clock=lambda: 5_000.0)
        await first.set_client_info(OAuthClientInformationFull(redirect_uris=[REDIRECT], client_id="c-1",
                                                               token_endpoint_auth_method="none"))
        await first.set_tokens(OAuthToken(access_token=SENTINEL, expires_in=60))
        again = VaultTokenStorage(VaultStore(), redirect_uri=REDIRECT)
        assert (await again.get_tokens()).access_token == SENTINEL
        assert (await again.get_client_info()).client_id == "c-1"
        assert again.expires_at == 5_060.0
        blob = (await repo.get(holder["plugin"].credential_ref)).blob
        assert blob.startswith(MARKER) and SENTINEL.encode() not in blob
    finally:
        await state.close()


async def test_stored_expiry_is_restored_and_non_interactive_mode_raises_before_sending():
    payload = {**empty_oauth_payload(REDIRECT), "tokens": {"access_token": "old", "token_type": "Bearer"},
               "expires_at": 500.0,
               "client_info": {"redirect_uris": [REDIRECT], "client_id": "c-1"}}
    authority = FakeAuthority()
    provider, _ = _provider(MemoryStore(payload), prompt=None)
    await provider._initialize()
    assert provider.context.token_expiry_time == 500.0 and not provider.context.is_token_valid()
    async with _client(authority, provider) as client:
        with pytest.raises(McpPluginError) as refused:
            await client.post(f"{RS}/mcp", json={})
    assert refused.value.code is McpErrorCode.REAUTHORIZATION_REQUIRED
    assert authority.requests == []  # no network attempt at all


async def test_non_interactive_401_never_starts_discovery():
    authority = FakeAuthority()
    provider, _ = _provider(MemoryStore(), Prompt(interactive=False))
    async with _client(authority, provider) as client:
        with pytest.raises(McpPluginError) as refused:
            await client.post(f"{RS}/mcp", json={})
    assert refused.value.code is McpErrorCode.REAUTHORIZATION_REQUIRED
    assert [str(request.url) for request in authority.requests] == [f"{RS}/mcp"]


async def test_non_interactive_step_up_403_raises():
    def handler(request):
        return httpx.Response(403, headers={"www-authenticate": 'Bearer error="insufficient_scope", scope="x"'})

    payload = {**empty_oauth_payload(REDIRECT), "tokens": {"access_token": "t", "token_type": "Bearer"},
               "client_info": {"redirect_uris": [REDIRECT], "client_id": "c-1"}}
    provider, _ = _provider(MemoryStore(payload), prompt=None)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), auth=provider) as client:
        with pytest.raises(McpPluginError) as refused:
            await client.post(f"{RS}/mcp", json={})
    assert refused.value.code is McpErrorCode.REAUTHORIZATION_REQUIRED


async def test_redirect_uri_port_change_drops_the_client_and_registers_again():
    old = "http://127.0.0.1:17000/api/mcp/oauth/callback"
    payload = {**empty_oauth_payload(old), "client_info": {"redirect_uris": [old], "client_id": "c-old"}}
    store, authority, prompt = MemoryStore(payload), FakeAuthority(), Prompt()
    provider, storage = _provider(store, prompt)
    async with _client(authority, provider) as client:
        assert (await client.post(f"{RS}/mcp", json={})).status_code == 200
    assert storage.client_info_dropped is True
    assert [body["redirect_uris"] for body in authority.registrations] == [[REDIRECT]]
    assert store.payload["client_info"]["client_id"] == "client-1" and store.payload["redirect_uri"] == REDIRECT


async def test_valid_stored_token_is_sent_without_any_flow():
    payload = {**empty_oauth_payload(REDIRECT), "tokens": {"access_token": f"{SENTINEL}-access",
                                                           "token_type": "Bearer"},
               "expires_at": 4_000_000_000.0, "client_info": {"redirect_uris": [REDIRECT], "client_id": "c-1"}}
    authority = FakeAuthority()
    provider, _ = _provider(MemoryStore(payload), prompt=None)
    async with _client(authority, provider) as client:
        assert (await client.post(f"{RS}/mcp", json={})).status_code == 200
    assert [str(request.url) for request in authority.requests] == [f"{RS}/mcp"]


async def test_revocation_posts_each_token_to_the_advertised_endpoint():
    authority = FakeAuthority(revocation=True)
    oauth = {**empty_oauth_payload(REDIRECT), "revocation_endpoint": f"{AS}/revoke",
             "tokens": {"access_token": "a", "refresh_token": "r"}, "client_info": {"client_id": "c-1", "issuer": AS}}
    async with httpx.AsyncClient(transport=httpx.MockTransport(authority.handler)) as client:
        assert await revoke_tokens(client, oauth) == 2
        assert await revoke_tokens(client, {**oauth, "revocation_endpoint": None}) == 0
    forms = [parse_qs(request.content.decode()) for request in authority.requests]
    assert [(form["token_type_hint"][0], form["client_id"][0]) for form in forms] == [
        ("refresh_token", "c-1"), ("access_token", "c-1")]


# ------------------------------------------------------------------ B1 : serveur d'autorisation changé (QA Slice 03)

EVIL = "https://evil.example.com"


class AbandonedPrompt(Prompt):
    """L'utilisateur ouvre la page de consentement puis l'abandonne."""

    async def wait_callback(self):
        raise McpPluginError(McpErrorCode.REAUTHORIZATION_REQUIRED, "the authorization was abandoned")


class SwitchingWorld(FakeAuthority):
    """AS A autorise d'abord ; puis la ressource annonce `evil` (PRM) et refuse les jetons de A."""

    def __init__(self, *, evil_claims: str) -> None:
        super().__init__(grants=["authorization_code", "refresh_token"], refresh=True, revocation=True)
        self.evil_claims = evil_claims  # issuer that evil's metadata claims (EVIL: valid; AS: mismatch)
        self.switched = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if not self.switched:
            return super().handler(request)
        self.requests.append(request)
        if url.startswith(f"{RS}/.well-known/oauth-protected-resource"):
            return httpx.Response(200, json={"resource": f"{RS}/mcp", "authorization_servers": [EVIL]})
        if url.startswith(f"{EVIL}/.well-known/"):
            return httpx.Response(200, json={
                "issuer": self.evil_claims, "authorization_endpoint": f"{EVIL}/authorize",
                "token_endpoint": f"{EVIL}/token", "registration_endpoint": f"{EVIL}/register",
                "revocation_endpoint": f"{EVIL}/revoke", "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"]})
        if url == f"{EVIL}/register":
            return httpx.Response(201, json={**json.loads(request.content), "client_id": "evil-client"})
        if url.startswith(f"{RS}/mcp"):
            return httpx.Response(401, headers={"www-authenticate": (
                f'Bearer resource_metadata="{RS}/.well-known/oauth-protected-resource"')})
        return httpx.Response(200)  # evil accepts anything, /revoke included


@pytest.mark.parametrize("variant", ["abandoned_consent", "rejected_metadata"])
async def test_a_changed_authorization_server_never_receives_the_old_tokens(variant):
    """QA B1 : AS A autorise, la ressource bascule vers `evil`, puis Déconnecter ne donne rien à `evil`."""

    world = SwitchingWorld(evil_claims=EVIL if variant == "abandoned_consent" else AS)
    store = MemoryStore()
    provider, _ = _provider(store, Prompt())
    async with _client(world, provider) as client:
        assert (await client.post(f"{RS}/mcp", json={})).status_code == 200
    assert store.payload["tokens"]["refresh_token"] == f"{SENTINEL}-refresh"

    world.switched = True
    reconnect, _ = _provider(store, AbandonedPrompt())
    async with _client(world, reconnect) as client:
        with pytest.raises(Exception):
            await client.post(f"{RS}/mcp", json={})

    world.requests.clear()
    async with httpx.AsyncClient(transport=httpx.MockTransport(world.handler)) as client:
        try:
            await revoke_tokens(client, store.payload)
        except RemoteMcpError:
            pass  # refused locally is fine; only the network matters here
    sent = [request for request in world.requests if request.url.host == "evil.example.com"]
    assert sent == []
    assert all(SENTINEL.encode() not in request.content for request in world.requests)
    assert store.payload["revocation_endpoint"] != f"{EVIL}/revoke"
    assert store.payload["tokens"] is None  # the SDK dropped A's credentials: the vault drops them too


async def test_revocation_is_refused_to_an_origin_other_than_the_bound_issuer():
    """QA B1, défense en profondeur : l'extrémité de révocation doit être sur l'origine de l'émetteur lié."""

    requests: list[httpx.Request] = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200)

    tokens = {"access_token": f"{SENTINEL}-a", "refresh_token": f"{SENTINEL}-r"}
    bound = {"client_id": "c-1", "redirect_uris": [REDIRECT], "issuer": AS}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        for endpoint, client_info in ((f"{EVIL}/revoke", bound),
                                      ("https://auth.example.com:8443/revoke", bound),
                                      (f"{AS}/revoke", {"client_id": "c-1"})):
            oauth = {**empty_oauth_payload(REDIRECT), "revocation_endpoint": endpoint, "tokens": tokens,
                     "client_info": client_info}
            with pytest.raises(RemoteMcpError) as refused:
                await revoke_tokens(client, oauth)
            assert refused.value.code is McpErrorCode.OAUTH_ISSUER_MISMATCH
            assert SENTINEL not in str(refused.value)
    assert requests == []
