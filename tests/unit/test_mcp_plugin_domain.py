"""Contrat pur des plugins MCP : slug, transitions, codec strict, vue publique, masquage (Slice 02).

Contrat : `docs/mcp/plugins.md` §2, §8.2 ; ARCH §3.1, §9.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from jarvis.domain.mcp_plugins import (
    HTTP_STATUS, PAYLOAD_KEYS, REDACTED, AuthStatus, AuthStrategy, ConnectionStatus, McpErrorCode, McpPlugin,
    McpPluginError, attach_credential, disconnect, mark_connection, new_plugin, plugin_id_for, redact, rename,
    reset_interrupted_connect, set_enabled,
)

T0 = datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc)
CIRCUIT = "https://circoetoolbox-server-production.up.railway.app/mcp"
REF = "cred_" + "a" * 32


def t(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def plugin(**changes) -> McpPlugin:
    base = new_plugin(CIRCUIT, plugin_id="circoetoolbox-server-production", display_name=None, now=T0)
    return McpPlugin.from_payload({**base.to_payload(), **changes}) if changes else base


# ------------------------------------------------------------------ slug


@pytest.mark.parametrize("endpoint, taken, expected", [
    (CIRCUIT, set(), "circoetoolbox-server-production"),
    ("https://Mail.Example.com/mcp", set(), "mail"),
    ("https://my_server.example.com/", set(), "my-server"),
    ("https://jarvis-tools.example.com/", set(), "p-jarvis-tools"),
    ("https://mail.example.com/", {"mail"}, "mail-2"),
    ("https://mail.example.com/", {"mail", "mail-2"}, "mail-3"),
    ("https://" + "a" * 40 + ".example.com/", set(), "a" * 32),
    ("https://" + "a" * 40 + ".example.com/", {"a" * 32}, "a" * 30 + "-2"),
    ("https://-lead.example.com/", set(), "lead"),
    ("https://8.8.8.8/", set(), "8"),
])
def test_plugin_id_slug_rules(endpoint, taken, expected):
    assert plugin_id_for(endpoint, taken) == expected


def test_jarvis_prefix_is_refused_as_an_id():
    with pytest.raises(McpPluginError) as refusal:
        plugin(plugin_id="jarvis-drive")
    assert refusal.value.code is McpErrorCode.PLUGIN_INVALID


@pytest.mark.parametrize("bad", ["", "-x", "UPPER", "a" * 33, "a_b", "é"])
def test_invalid_ids_are_refused(bad):
    with pytest.raises(McpPluginError):
        plugin(plugin_id=bad)


def test_every_code_has_an_http_status():
    assert set(HTTP_STATUS) == set(McpErrorCode)
    assert HTTP_STATUS[McpErrorCode.PLUGIN_DUPLICATE] == 409
    assert HTTP_STATUS[McpErrorCode.ENDPOINT_INVALID] == 400
    assert HTTP_STATUS[McpErrorCode.VAULT_UNAVAILABLE] == 409
    assert HTTP_STATUS[McpErrorCode.CONNECTOR_UNAVAILABLE] == 503
    assert McpPluginError("mcp_plugin_unknown", "x").status == 404


# ------------------------------------------------------------------ valeur et codec


def test_new_plugin_defaults():
    value = plugin()
    assert value.display_name == "circoetoolbox-server-production.up.railway.app"
    assert value.endpoint_origin == "https://circoetoolbox-server-production.up.railway.app"
    assert (value.enabled, value.connection_status, value.auth_status, value.auth_strategy) == (
        True, ConnectionStatus.DISCONNECTED, AuthStatus.UNKNOWN, AuthStrategy.NONE)
    assert value.credential_ref is None and value.tools == () and value.capability_revision == 0


def test_strict_payload_round_trip_is_exact():
    value = attach_credential(plugin(), strategy=AuthStrategy.BEARER, credential_ref=REF, now=t(1))
    value = McpPlugin.from_payload({**value.to_payload(), "server_identity": {"name": "Circuit", "version": "1"},
                                    "tools": [{"name": "search", "input_schema": {"type": "object"}}],
                                    "rejected_tools": [{"name": "bad name", "code": "mcp_tool_name_invalid"}],
                                    "last_error_code": "mcp_remote_timeout", "icon_url": "https://x.example/i.png"})
    payload = value.to_payload()
    assert set(payload) == PAYLOAD_KEYS
    assert McpPlugin.from_payload(json.loads(json.dumps(payload))) == value
    assert McpPlugin.from_payload(payload).to_payload() == payload


@pytest.mark.parametrize("mutate", [
    lambda p: {**p, "surprise": 1},
    lambda p: {k: v for k, v in p.items() if k != "auth_status"},
    lambda p: {**p, "enabled": 1},
    lambda p: {**p, "connection_status": "Connected"},
    lambda p: {**p, "credential_ref": "sk-live-secret"},
    lambda p: {**p, "endpoint_origin": "https://other.example"},
    lambda p: {**p, "icon_url": "http://x.example/i.png"},
    lambda p: {**p, "last_error_code": "remote said: token abc"},
    lambda p: {**p, "created_at": "2026-09-30T10:00:00"},
    lambda p: {**p, "tools": [{}] * 201},
    lambda p: {**p, "server_identity": {"name": "x", "token": "y"}},
    lambda p: {**p, "transport": "sse"},
    lambda p: "not an object",
])
def test_strict_decode_refuses_anything_off_contract(mutate):
    with pytest.raises(McpPluginError):
        McpPlugin.from_payload(mutate(plugin().to_payload()))


def test_public_view_never_carries_the_credential_ref():
    value = attach_credential(plugin(), strategy=AuthStrategy.HEADER, credential_ref=REF, now=t(1))
    view = value.public_view()
    assert "credential_ref" not in view
    assert REF not in json.dumps(view)
    assert set(view) == PAYLOAD_KEYS - {"credential_ref"}


def test_display_name_is_bounded():
    with pytest.raises(McpPluginError):
        rename(plugin(), "x" * 65, now=t(1))
    assert rename(plugin(), "  Circuit  ", now=t(1)).display_name == "Circuit"


# ------------------------------------------------------------------ transitions


def test_enable_disable_never_touch_connection_or_auth():
    connected = mark_connection(plugin(), ConnectionStatus.CONNECTED, auth_status=AuthStatus.AUTHORIZED, now=t(1))
    disabled = set_enabled(connected, False, now=t(2))
    assert disabled.enabled is False
    assert (disabled.connection_status, disabled.auth_status) == (ConnectionStatus.CONNECTED, AuthStatus.AUTHORIZED)
    enabled = set_enabled(disabled, True, now=t(3))
    assert (enabled.connection_status, enabled.auth_status) == (ConnectionStatus.CONNECTED, AuthStatus.AUTHORIZED)
    assert set_enabled(enabled, True, now=t(4)) is enabled  # no-op keeps updated_at


def test_disconnect_forgets_credentials_but_never_touches_enabled():
    value = set_enabled(plugin(), False, now=t(1))
    value = attach_credential(value, strategy=AuthStrategy.BEARER, credential_ref=REF, now=t(2))
    value = mark_connection(value, ConnectionStatus.CONNECTED, auth_status=AuthStatus.AUTHORIZED, now=t(3))
    gone = disconnect(value, now=t(4))
    assert gone.enabled is False
    assert (gone.connection_status, gone.auth_status, gone.auth_strategy, gone.credential_ref) == (
        ConnectionStatus.DISCONNECTED, AuthStatus.UNKNOWN, AuthStrategy.NONE, None)
    assert gone.updated_at == t(4)


def test_boot_reset_only_rewrites_connecting():
    connecting = mark_connection(plugin(), ConnectionStatus.CONNECTING, now=t(1))
    assert reset_interrupted_connect(connecting, now=t(2)).connection_status is ConnectionStatus.DISCONNECTED
    connected = mark_connection(plugin(), ConnectionStatus.CONNECTED, now=t(1))
    assert reset_interrupted_connect(connected, now=t(2)) is connected


def test_attach_credential_resets_auth_to_unknown():
    value = mark_connection(plugin(), ConnectionStatus.ERROR, auth_status=AuthStatus.FAILED,
                            error_code=McpErrorCode.REMOTE_UNREACHABLE, now=t(1))
    attached = attach_credential(value, strategy=AuthStrategy.BEARER, credential_ref=REF, now=t(2))
    assert (attached.auth_strategy, attached.credential_ref, attached.auth_status, attached.last_error_code) == (
        AuthStrategy.BEARER, REF, AuthStatus.UNKNOWN, None)


def test_updated_at_never_goes_backwards():
    value = set_enabled(plugin(), False, now=t(5))
    assert set_enabled(value, True, now=t(1)).updated_at == t(5)


# ------------------------------------------------------------------ masquage


def test_redact_known_secret_bearer_and_jwt():
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    text = (f"remote failed with key SENTINEL-SECRET-7f3a, header Authorization: Bearer abc.def-ghi "
            f"and token {jwt} end")
    clean = redact(text, ["SENTINEL-SECRET-7f3a"])
    assert "SENTINEL-SECRET-7f3a" not in clean
    assert "abc.def-ghi" not in clean
    assert jwt not in clean and "eyJhbGci" not in clean
    assert clean.count(REDACTED) == 3 and clean.endswith("end")


def test_redact_longest_secret_first_leaves_no_fragment():
    assert redact("x SECRETLONG y", ["SECRET", "SECRETLONG"]) == f"x {REDACTED} y"


def test_redact_ignores_empty_secrets():
    assert redact("plain text", ["", None]) == "plain text"  # type: ignore[list-item]
