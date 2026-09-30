"""Connecteur MCP distant : pièces sans réseau (Slice 03 ; `docs/mcp/plugins.md` §3.4, §4).

`OriginHeaderAuth` pose l'identifiant statique (bearer / en-tête) **seulement**
sur l'origine exacte du plugin — schéma, hôte et port —, jamais sur le même
hôte à un autre port, ni sur un autre hôte (QA Slice 03, m1).
"""

from __future__ import annotations

import httpx
import pytest

pytest.importorskip("mcp")

from jarvis.adapters.remote_mcp import OriginHeaderAuth, leaf_types, local_failure  # noqa: E402
from jarvis.ports.mcp_plugins import McpPluginStoreError  # noqa: E402

SECRET = "SENTINEL-SECRET-7f3a"


async def _headers_sent(origin: str, url: str) -> httpx.Headers:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    auth = OriginHeaderAuth(origin, (("Authorization", f"Bearer {SECRET}"), ("X-Api-Key", SECRET)))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), auth=auth) as client:
        await client.get(url)
    request, = seen
    return request.headers


@pytest.mark.parametrize("url", [
    "https://mail.example.com/mcp",
    "https://mail.example.com:443/other/path?q=1",  # default port: same origin
    "https://MAIL.example.com/mcp",  # host case is not identity
])
async def test_static_headers_reach_the_exact_plugin_origin(url):
    headers = await _headers_sent("https://mail.example.com", url)
    assert headers["authorization"] == f"Bearer {SECRET}" and headers["x-api-key"] == SECRET


@pytest.mark.parametrize("origin, url", [
    ("https://mail.example.com", "https://mail.example.com:8443/mcp"),  # same host, other port
    ("https://mail.example.com", "http://mail.example.com/mcp"),  # same host, other scheme
    ("https://mail.example.com", "https://auth.example.com/token"),  # another host (the AS)
    ("https://mail.example.com", "https://evil.mail.example.com/mcp"),  # a subdomain is another host
    ("https://mail.example.com", "https://mail.example.com.evil.net/mcp"),  # suffix trick
    ("http://127.0.0.1:9000", "http://127.0.0.1:9001/mcp"),  # dev loopback: port is identity
    ("http://127.0.0.1:9000", "http://localhost:9000/mcp"),  # same machine, other host name
])
async def test_static_headers_never_leave_the_plugin_origin(origin, url):
    headers = await _headers_sent(origin, url)
    assert "authorization" not in headers and "x-api-key" not in headers
    assert SECRET not in str(headers)


def test_logged_failure_types_are_the_leaves_not_the_group():
    group = BaseExceptionGroup("outer", [ValueError("a"), ExceptionGroup("inner", [KeyError("b"), ValueError("c")])])
    assert leaf_types(group) == "ValueError,KeyError"


def test_a_store_failure_is_found_inside_an_exception_group():
    store = McpPluginStoreError("mcp_credentials", "p", "boom")
    assert local_failure(ExceptionGroup("sdk", [RuntimeError("x"), store])) is store
    assert local_failure(ExceptionGroup("sdk", [RuntimeError("x")])) is None
