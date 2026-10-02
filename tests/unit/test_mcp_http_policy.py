"""`PolicyTransport` : SSRF, schéma, drapeau de bouclage, plafond d'octets, redirections (Slice 03 ; plugins.md §4.2)."""

from __future__ import annotations

import httpx
import pytest

from jarvis.adapters.mcp_http_policy import (
    MAX_REDIRECTS, MAX_RESPONSE_BYTES, McpPolicyError, PolicyTransport, build_http_client,
)
from jarvis.domain.mcp_plugins import McpErrorCode


def _resolver(mapping: dict[str, list[str]]):
    calls: list[str] = []

    async def resolve(host: str, port: int) -> list[str]:
        calls.append(host)
        if host not in mapping:
            raise OSError("no such host")
        return mapping[host]

    resolve.calls = calls
    return resolve


def _ok(body: bytes = b"{}", headers: dict | None = None):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=body, headers=headers or {})

    return httpx.MockTransport(handler), seen


async def _get(transport: PolicyTransport, url: str) -> httpx.Response:
    async with build_http_client(transport) as client:
        return await client.get(url)


async def _refusal(transport: PolicyTransport, url: str) -> McpErrorCode:
    with pytest.raises(McpPolicyError) as refused:
        await _get(transport, url)
    return refused.value.code


@pytest.mark.parametrize("url", [
    "https://10.0.0.1/mcp", "https://192.168.1.2/", "https://172.16.0.1/", "https://169.254.169.254/latest/",
    "https://100.64.0.1/", "https://127.0.0.1/", "https://[::1]/", "https://[fd00::1]/", "https://[fe80::1]/",
    "https://[::ffff:10.0.0.1]/", "https://0.0.0.0/",
])
async def test_forbidden_ip_literals_are_refused_without_dns(url):
    inner, seen = _ok()
    resolver = _resolver({})
    transport = PolicyTransport(inner=inner, resolver=resolver)
    assert await _refusal(transport, url) is McpErrorCode.ENDPOINT_FORBIDDEN
    assert seen == [] and resolver.calls == []


@pytest.mark.parametrize("addresses", [["10.1.2.3"], ["93.184.216.34", "127.0.0.1"], ["169.254.169.254"],
                                       ["::1"], ["fd12::5"]])
async def test_dns_resolved_forbidden_addresses_are_refused(addresses):
    inner, seen = _ok()
    transport = PolicyTransport(inner=inner, resolver=_resolver({"evil.example.com": addresses}))
    assert await _refusal(transport, "https://evil.example.com/mcp") is McpErrorCode.ENDPOINT_FORBIDDEN
    assert seen == []  # nothing left the process


async def test_public_address_passes():
    inner, seen = _ok()
    transport = PolicyTransport(inner=inner, resolver=_resolver({"mail.example.com": ["93.184.216.34"]}))
    assert (await _get(transport, "https://mail.example.com/mcp")).status_code == 200
    assert len(seen) == 1


async def test_unresolvable_host_is_unreachable():
    inner, _ = _ok()
    transport = PolicyTransport(inner=inner, resolver=_resolver({}))
    assert await _refusal(transport, "https://nowhere.example.com/") is McpErrorCode.REMOTE_UNREACHABLE


async def test_http_is_refused_for_public_hosts_even_under_the_dev_flag():
    inner, _ = _ok()
    transport = PolicyTransport(inner=inner, allow_loopback_http=True,
                                resolver=_resolver({"mail.example.com": ["93.184.216.34"]}))
    assert await _refusal(transport, "http://mail.example.com/") is McpErrorCode.ENDPOINT_INVALID


async def test_loopback_needs_the_dev_flag():
    inner, seen = _ok()
    refused = PolicyTransport(inner=inner, resolver=_resolver({"localhost": ["127.0.0.1", "::1"]}))
    assert await _refusal(refused, "http://127.0.0.1:8123/mcp") is McpErrorCode.ENDPOINT_FORBIDDEN
    assert await _refusal(refused, "http://localhost:8123/mcp") is McpErrorCode.ENDPOINT_FORBIDDEN
    allowed = PolicyTransport(inner=inner, allow_loopback_http=True,
                              resolver=_resolver({"localhost": ["127.0.0.1", "::1"]}))
    assert (await _get(allowed, "http://127.0.0.1:8123/mcp")).status_code == 200
    assert (await _get(allowed, "http://localhost:8123/mcp")).status_code == 200
    # the flag opens loopback only, never the private network
    assert await _refusal(allowed, "http://10.0.0.1/") is McpErrorCode.ENDPOINT_FORBIDDEN
    assert len(seen) == 2


async def test_non_http_scheme_is_refused():
    inner, _ = _ok()
    transport = PolicyTransport(inner=inner, resolver=_resolver({}))
    with pytest.raises(McpPolicyError) as refused:
        await transport.check_url(httpx.URL("ftp://files.example.com/"))
    assert refused.value.code is McpErrorCode.ENDPOINT_INVALID


async def test_streamed_body_over_the_cap_is_aborted_and_reported():
    reported: list[McpErrorCode] = []

    async def chunks():
        for _ in range(5):
            yield b"x" * 1000

    inner = httpx.MockTransport(lambda request: httpx.Response(200, content=chunks()))
    transport = PolicyTransport(inner=inner, resolver=_resolver({"a.example.com": ["93.184.216.34"]}),
                                max_response_bytes=2500, on_violation=reported.append)
    assert await _refusal(transport, "https://a.example.com/") is McpErrorCode.RESPONSE_TOO_LARGE
    assert reported == [McpErrorCode.RESPONSE_TOO_LARGE]


async def test_declared_length_over_the_cap_is_refused_before_reading():
    inner, _ = _ok(b"y" * 10, headers={"content-length": str(MAX_RESPONSE_BYTES + 1)})
    transport = PolicyTransport(inner=inner, resolver=_resolver({"a.example.com": ["93.184.216.34"]}))
    assert await _refusal(transport, "https://a.example.com/") is McpErrorCode.RESPONSE_TOO_LARGE


async def test_body_at_the_cap_passes():
    inner, _ = _ok(b"z" * 4096)
    transport = PolicyTransport(inner=inner, resolver=_resolver({"a.example.com": ["93.184.216.34"]}),
                                max_response_bytes=4096)
    assert len((await _get(transport, "https://a.example.com/")).content) == 4096


def test_client_never_follows_redirects_by_itself_and_ignores_env_proxies():
    client = build_http_client(PolicyTransport(resolver=_resolver({})))
    assert client.follow_redirects is False and client.max_redirects == MAX_REDIRECTS
    assert client.trust_env is False


async def test_sdk_redirect_following_is_bounded_and_same_origin_only():
    pytest.importorskip("mcp")
    from mcp.shared._httpx_utils import request_within_origin

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host == "other.example.com":
            return httpx.Response(200, json={})
        if request.url.path == "/cross":
            return httpx.Response(307, headers={"location": "https://other.example.com/steal"})
        return httpx.Response(307, headers={"location": f"/loop{len(seen)}"})

    transport = PolicyTransport(inner=httpx.MockTransport(handler), resolver=_resolver(
        {"a.example.com": ["93.184.216.34"], "other.example.com": ["93.184.216.35"]}))
    async with build_http_client(transport, auth=None) as client:
        looped = await request_within_origin(client, "POST", "https://a.example.com/start",
                                             headers={"Authorization": "Bearer SENTINEL-SECRET-7f3a"})
        assert looped.status_code == 307 and len(seen) == MAX_REDIRECTS + 1
        seen.clear()
        crossed = await request_within_origin(client, "POST", "https://a.example.com/cross",
                                              headers={"Authorization": "Bearer SENTINEL-SECRET-7f3a"})
    assert crossed.status_code == 307
    assert seen == ["https://a.example.com/cross"]  # the other origin never received the request


# ------------------------------------------------------------------ Slice 03 : hôtes déguisés (retour QA de la Slice 02)


@pytest.mark.parametrize("url", [
    "https://2130706433/", "https://0x7f000001/", "https://127.1/", "https://0/",
    "https://[64:ff9b::a9fe:a9fe]/", "https://[::127.0.0.1]/",
])
async def test_disguised_forbidden_hosts_are_refused_before_dns(url):
    inner, seen = _ok()
    resolver = _resolver({})
    transport = PolicyTransport(inner=inner, resolver=resolver, allow_loopback_http=False)
    with pytest.raises(McpPolicyError) as refused:
        await transport.check_url(httpx.URL(url))
    assert refused.value.code is McpErrorCode.ENDPOINT_FORBIDDEN
    assert resolver.calls == [] and seen == []


async def test_octal_host_is_refused_by_httpx_or_by_the_policy():
    # httpx itself rejects `0177.0.0.1`; the domain refuses it before any client exists.
    with pytest.raises(httpx.InvalidURL):
        httpx.URL("https://0177.0.0.1/")


@pytest.mark.parametrize("url", ["https://%31%32%37.0.0.1/", "https://mail.example.com:0/"])
async def test_percent_host_and_port_zero_are_invalid(url):
    transport = PolicyTransport(inner=_ok()[0], resolver=_resolver({"mail.example.com": ["93.184.216.34"]}))
    with pytest.raises(McpPolicyError) as refused:
        await transport.check_url(httpx.URL(url))
    assert refused.value.code is McpErrorCode.ENDPOINT_INVALID

