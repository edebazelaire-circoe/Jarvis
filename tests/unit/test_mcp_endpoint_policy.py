"""Politique statique des endpoints de plugins MCP (Slice 02 ; `docs/mcp/plugins.md` §4.1, ARCH §5.1, §16 E4)."""

from __future__ import annotations

import ipaddress

import pytest

from jarvis.domain.mcp_endpoint import is_forbidden_address, validate_endpoint
from jarvis.domain.mcp_plugins import McpErrorCode, McpPluginError

CIRCUIT = "https://circoetoolbox-server-production.up.railway.app/mcp"


def refused(raw, *, loopback: bool = False) -> McpPluginError:
    with pytest.raises(McpPluginError) as refusal:
        validate_endpoint(raw, allow_loopback_http=loopback)
    return refusal.value


@pytest.mark.parametrize("raw, expected", [
    (CIRCUIT, CIRCUIT),
    ("  HTTPS://Example.COM  ", "https://example.com/"),
    ("https://example.com:443/mcp", "https://example.com/mcp"),
    ("https://example.com:8443/mcp?region=eu", "https://example.com:8443/mcp?region=eu"),
    ("https://bücher.example/mcp", "https://xn--bcher-kva.example/mcp"),
    ("https://8.8.8.8/mcp", "https://8.8.8.8/mcp"),
    ("https://[2001:4860:4860::8888]/mcp", "https://[2001:4860:4860::8888]/mcp"),
])
def test_valid_endpoints_are_normalized(raw, expected):
    assert validate_endpoint(raw, allow_loopback_http=False) == expected


@pytest.mark.parametrize("raw", [
    "http://example.com/mcp",
    "ftp://example.com/",
    "example.com/mcp",
    "https://user:pw@example.com/mcp",
    "https://token@example.com/mcp",
    "https://example.com/mcp#frag",
    "https://example.com/mcp#",
    "https://example.com/mcp?access_token=x",
    "https://example.com/mcp?API_KEY=x",
    "https://example.com/mcp?Secret=x",
    "https://example.com/mcp?auth=x",
    "https://example.com/mcp?password=x",
    "https://example.com/mcp?sig=x",
    "https://example.com/" + "a" * 2050,
    "https://exa mple.com/",
    "https://example.com:99999/",
    "https:///nohost",
    "",
    None,
    42,
])
def test_syntax_problems_are_invalid(raw):
    assert refused(raw).code is McpErrorCode.ENDPOINT_INVALID


def test_non_idna_host_is_invalid():
    error = refused("https://" + "ü" * 70 + ".example/")  # printable, but a label over 63 octets
    assert error.code is McpErrorCode.ENDPOINT_INVALID and "IDNA" in str(error)


def test_the_refusal_says_why():
    assert "fragment" in str(refused("https://example.com/#x"))
    assert "userinfo" in str(refused("https://u@example.com/"))


@pytest.mark.parametrize("raw", [
    "https://10.1.2.3/mcp",
    "https://127.0.0.1/mcp",
    "https://169.254.169.254/latest/meta-data",
    "https://[::1]/mcp",
    "https://[fd00::1]/mcp",
    "https://100.64.0.1/mcp",
    "https://192.168.1.10/mcp",
    "https://0.0.0.0/mcp",
    "https://[::ffff:10.0.0.1]/mcp",
    "https://localhost/mcp",
    "https://api.localhost/mcp",
])
def test_forbidden_addresses_are_forbidden_not_invalid(raw):
    assert refused(raw).code is McpErrorCode.ENDPOINT_FORBIDDEN


def test_loopback_http_needs_the_development_flag():
    assert refused("http://127.0.0.1:8123/mcp").code is McpErrorCode.ENDPOINT_INVALID
    assert validate_endpoint("http://127.0.0.1:8123/mcp", allow_loopback_http=True) == "http://127.0.0.1:8123/mcp"
    assert validate_endpoint("http://localhost:8123/mcp", allow_loopback_http=True) == "http://localhost:8123/mcp"
    # The flag opens loopback only, never another private address nor http elsewhere.
    assert refused("http://10.0.0.1/mcp", loopback=True).code is McpErrorCode.ENDPOINT_INVALID
    assert refused("https://10.0.0.1/mcp", loopback=True).code is McpErrorCode.ENDPOINT_FORBIDDEN
    assert refused("http://example.com/mcp", loopback=True).code is McpErrorCode.ENDPOINT_INVALID


@pytest.mark.parametrize("address, forbidden", [
    ("8.8.8.8", False),
    ("2001:4860:4860::8888", False),
    ("10.0.0.1", True),
    ("127.0.0.1", True),
    ("169.254.169.254", True),
    ("100.64.0.1", True),
    ("::1", True),
    ("fd00::1", True),
    ("fe80::1", True),
    ("::ffff:10.0.0.1", True),
    ("::ffff:8.8.8.8", False),
])
def test_is_forbidden_address(address, forbidden):
    assert is_forbidden_address(address) is forbidden
    assert is_forbidden_address(ipaddress.ip_address(address)) is forbidden
