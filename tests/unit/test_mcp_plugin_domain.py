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


def test_disconnect_keeps_an_enabled_plugin_enabled():
    value = attach_credential(plugin(), strategy=AuthStrategy.BEARER, credential_ref=REF, now=t(1))
    value = mark_connection(value, ConnectionStatus.CONNECTED, auth_status=AuthStatus.AUTHORIZED, now=t(2))
    assert value.enabled is True
    gone = disconnect(value, now=t(3))
    assert gone.enabled is True
    assert (gone.connection_status, gone.credential_ref) == (ConnectionStatus.DISCONNECTED, None)


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


# ------------------------------------------------------------------ Slice 03 : normalisation des outils distants (ARCH §6.2)

from jarvis.domain import mcp_plugins as domain  # noqa: E402


def _raw(name="search", **extra):
    return {"name": name, "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}}, **extra}


def test_normalized_descriptor_fields():
    descriptor = domain.normalize_remote_tool("mail", _raw(title="Chercher\x07 des mails", description="Find mail",
                                                           annotations={"readOnlyHint": True, "idempotentHint": True,
                                                                        "openWorldHint": False},
                                                           outputSchema={"type": "object"}))
    assert descriptor.to_payload() == {
        "tool_id": "mail.search", "plugin_id": "mail", "name": "search", "title": "Chercher des mails",
        "description": "Find mail", "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
        "output_schema": {"type": "object"}, "side_effect": "read", "idempotent": True, "atomicity": "external",
        "open_world": False}


@pytest.mark.parametrize("annotations, side_effect", [
    ({"readOnlyHint": True}, "read"), ({"destructiveHint": False}, "write"), ({}, "destructive"),
    ({"readOnlyHint": False, "destructiveHint": True}, "destructive"), ({"readOnlyHint": "yes"}, "destructive"),
])
def test_side_effect_is_conservative(annotations, side_effect):
    assert domain.normalize_remote_tool("p", _raw(annotations=annotations)).side_effect == side_effect


def test_title_falls_back_to_annotations_and_is_bounded():
    assert domain.normalize_remote_tool("p", _raw(annotations={"title": "T" * 100})).title == "T" * 80


@pytest.mark.parametrize("raw, code", [
    (_raw(name="bad name"), "mcp_tool_name_invalid"),
    (_raw(name="x" * 129), "mcp_tool_name_invalid"),
    ({"inputSchema": {"type": "object"}}, "mcp_tool_name_invalid"),
    ("not a tool", "mcp_tool_name_invalid"),
    (_raw(inputSchema={"type": "string"}), "mcp_tool_schema_too_large"),
    (_raw(inputSchema=None), "mcp_tool_schema_too_large"),
    (_raw(inputSchema={"type": "object", "description": "é" * 9000}), "mcp_tool_schema_too_large"),
])
def test_rejections_carry_a_code(raw, code):
    assert domain.normalize_remote_tool("p", raw).to_payload()["code"] == code


def test_schema_depth_bound():
    schema: dict = {}  # depth 1
    for _ in range(10):
        schema = {"a": schema}  # depth 11
    assert isinstance(domain.normalize_remote_tool("p", _raw(inputSchema={"type": "object", "x": schema})),
                      domain.ExternalToolDescriptor)  # depth 12
    assert domain.normalize_remote_tool("p", _raw(inputSchema={"type": "object", "x": {"a": schema}})).code \
        is McpErrorCode.TOOL_SCHEMA_TOO_LARGE


def test_oversized_output_schema_is_dropped_not_rejected():
    descriptor = domain.normalize_remote_tool("p", _raw(outputSchema={"type": "object", "d": "x" * 17_000}))
    assert descriptor.output_schema is None


def test_description_bound_counts_the_suffix_and_cuts_on_a_character():
    text = "é" * 3000  # 6 000 bytes
    bounded = domain.bound_description(text)
    assert bounded.endswith(domain.TRUNCATION_SUFFIX)
    assert len(bounded.encode("utf-8")) <= domain.MAX_TOOL_DESCRIPTION_BYTES
    assert domain.bound_description("short") == "short"


def test_plugin_bounds_duplicates_and_rejection_cap():
    raws = [_raw(f"t{i}") for i in range(250)] + [_raw("t0")] + [_raw("bad name")] * 300
    tools, rejected = domain.normalize_remote_tools("p", raws)
    assert len(tools) == 200 and len(rejected) == domain.MAX_REJECTED_TOOLS
    assert rejected[0] == {"name": "t200", "code": "mcp_tool_list_too_large"}
    assert {"name": "t0", "code": "mcp_tool_name_invalid"} in rejected


def test_byte_bound_of_a_plugin():
    big = "d" * 4000
    tools, rejected = domain.normalize_remote_tools("p", [_raw(f"t{i}", description=big) for i in range(150)])
    assert sum(len(json.dumps(t, separators=(",", ":"))) for t in tools) <= domain.MAX_PLUGIN_TOOLS_BYTES
    assert rejected and {r["code"] for r in rejected} == {"mcp_tool_list_too_large"}


def test_server_identity_is_cleaned_and_bounded():
    identity = domain.server_identity_from({"name": "Srv\x00\n", "version": "v" * 300, "protocol_version": 3})
    assert identity == {"name": "Srv", "version": "v" * 128}
    assert domain.icon_url_from("http://x/i.png") is None and domain.icon_url_from("https://x/i.png")


def test_mark_connected_and_apply_tools_revision():
    base = plugin()
    tools, rejected = domain.normalize_remote_tools(base.plugin_id, [_raw()])
    connected = domain.mark_connected(base, now=t(1), identity={"name": "Mail Server"}, icon_url=None,
                                      auth_strategy=AuthStrategy.NONE, auth_status=AuthStatus.NOT_REQUIRED,
                                      tools=tools, rejected=rejected)
    assert connected.display_name == "Mail Server" and connected.enabled is base.enabled
    assert connected.capability_revision == 1 and connected.connection_status is ConnectionStatus.CONNECTED
    same = domain.apply_tools(connected, tools, rejected, now=t(2))
    assert same.capability_revision == 1
    more, _ = domain.normalize_remote_tools(base.plugin_id, [_raw(), _raw("other")])
    assert domain.apply_tools(connected, more, (), now=t(3)).capability_revision == 2


def test_user_display_name_survives_connection():
    named = domain.rename(plugin(), "Mon courrier", now=t(1))
    connected = domain.mark_connected(named, now=t(2), identity={"name": "Srv"}, icon_url=None,
                                      auth_strategy=AuthStrategy.NONE, auth_status=AuthStatus.NOT_REQUIRED,
                                      tools=(), rejected=())
    assert connected.display_name == "Mon courrier"


@pytest.mark.parametrize("oauth, needs", [
    (None, True),
    ({"tokens": None}, True),
    ({"tokens": {"access_token": "a"}, "expires_at": None}, False),
    ({"tokens": {"access_token": "a"}, "expires_at": 2_000.0}, False),
    ({"tokens": {"access_token": "a"}, "expires_at": 500.0}, True),
    ({"tokens": {"access_token": "a", "refresh_token": "r"}, "expires_at": 500.0}, False),
])
def test_oauth_needs_reauthorization(oauth, needs):
    assert domain.oauth_needs_reauthorization(oauth, now_epoch=1_000.0) is needs


@pytest.mark.parametrize("expected, supported, received, ok", [
    ("https://as", True, "https://as", True),
    ("https://as", True, None, False),
    ("https://as", True, "https://evil", False),
    ("https://as", False, None, True),
    ("https://as", False, "https://evil", False),
    (None, False, "https://as", False),
])
def test_rfc9207_issuer_check(expected, supported, received, ok):
    if ok:
        domain.check_authorization_issuer(expected=expected, supported=supported, received=received)
    else:
        with pytest.raises(McpPluginError) as refused:
            domain.check_authorization_issuer(expected=expected, supported=supported, received=received)
        assert refused.value.code is McpErrorCode.OAUTH_ISSUER_MISMATCH
