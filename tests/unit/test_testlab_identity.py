"""Conformance tests for Test Lab identity and shared guards (docs/testlab.md, Identity/Errors)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from jarvis.testlab.identity import (
    TESTLAB_SCHEMA_VERSION,
    check_bundle_id,
    check_diagnostic_id,
    check_diagnostic_version,
    check_run_id,
    check_sweep_id,
    diagnostic_domain,
    format_bundle_id,
    format_run_id,
    format_sweep_id,
    id_timestamp,
)
from jarvis.testlab.validation import (
    FIELD_INVALID,
    JSON_INVALID,
    LIMIT_EXCEEDED,
    TestLabError,
    TestLabRedactionError,
    canonical_json,
    content_fingerprint,
    decode_json_document,
    is_code_key,
    is_private_key,
    looks_like_code,
    parse_time,
    scan_private,
    to_event_time,
)
from tests.fakes.testlab import NONCE, T0


def test_schema_version_is_one():
    assert TESTLAB_SCHEMA_VERSION == 1


@pytest.mark.parametrize("value", ["voice.self_echo", "speech.payload_integrity", "voice.latency.queue", "a.b"])
def test_valid_diagnostic_ids(value):
    check_diagnostic_id(value)


@pytest.mark.parametrize("value", ["voice", "Voice.self_echo", "voice.", ".voice", "voice..echo", "voice.self-echo",
                                   "voice.1echo", "voice. echo", "v." + "a" * 70, None, 3])
def test_invalid_diagnostic_ids_are_rejected_without_echoing(value):
    with pytest.raises(TestLabError) as caught:
        check_diagnostic_id(value)
    assert caught.value.code == FIELD_INVALID
    if isinstance(value, str) and value:
        assert value not in str(caught.value)


def test_diagnostic_domain_is_first_segment():
    assert diagnostic_domain("speech.payload_integrity") == "speech"


@pytest.mark.parametrize("value", [0, -1, 1.0, True, "1", None, 2**31])
def test_invalid_diagnostic_versions(value):
    with pytest.raises(TestLabError):
        check_diagnostic_version(value)


def test_diagnostic_version_accepts_positive_integers():
    check_diagnostic_version(1)
    check_diagnostic_version(42)


def test_timed_ids_are_deterministic_and_sortable():
    assert format_run_id(T0, NONCE) == "tlr-20260917T105800123Z-0123456789abcdef"
    assert format_run_id(T0, NONCE) == format_run_id(T0, NONCE)
    assert format_sweep_id(T0, NONCE).startswith("tls-20260917T105800123Z-")
    assert format_bundle_id(T0, NONCE).startswith("tlb-20260917T105800123Z-")
    later = format_run_id(T0 + timedelta(milliseconds=1), "0000000000000000")
    assert sorted([later, format_run_id(T0, NONCE)])[0] == format_run_id(T0, NONCE)
    check_run_id(format_run_id(T0, NONCE))
    check_sweep_id(format_sweep_id(T0, NONCE))
    check_bundle_id(format_bundle_id(T0, NONCE))


@pytest.mark.parametrize("created_at, nonce", [
    (datetime(2026, 9, 17, 10, 58), NONCE),  # naive
    (datetime(2026, 9, 17, 10, 58, 0, 123456, tzinfo=timezone.utc), NONCE),  # sub-millisecond
    (datetime(2026, 9, 17, 12, 58, tzinfo=timezone(timedelta(hours=2))), NONCE),  # not UTC
    (T0, "0123456789ABCDEF"),
    (T0, "0123"),
    (T0, None),
])
def test_timed_id_inputs_are_validated(created_at, nonce):
    with pytest.raises(TestLabError):
        format_run_id(created_at, nonce)


def test_to_event_time_normalizes_a_producer_clock():
    local = datetime(2026, 9, 17, 12, 58, 0, 123456, tzinfo=timezone(timedelta(hours=2)))
    assert format_run_id(to_event_time(local), NONCE) == format_run_id(T0, NONCE)


@pytest.mark.parametrize("value", [
    "tls-20260917T105800123Z-0123456789abcdef",  # sweep prefix for a run
    "tlr-20261317T105800123Z-0123456789abcdef",  # month 13
    "tlr-20260917T105800123-0123456789abcdef",
    "tlr-20260917T105800123Z-0123456789abcdeg",
    "run-1", "", None,
])
def test_invalid_run_ids(value):
    with pytest.raises(TestLabError):
        check_run_id(value)


def test_optional_ids_accept_none():
    check_run_id(None, optional=True)
    check_sweep_id(None, optional=True)
    check_bundle_id(None, optional=True)


def test_parse_time_uses_conversation_event_wire_form():
    assert parse_time("2026-09-17T10:58:00.123Z", "t") == T0
    with pytest.raises(TestLabError) as caught:
        parse_time("2026-09-17T10:58:00Z", "t")
    assert caught.value.code == FIELD_INVALID


def test_fingerprint_is_canonical_and_key_order_independent():
    assert canonical_json({"b": 1, "a": [1.5, "é"]}) == '{"a":[1.5,"é"],"b":1}'
    assert content_fingerprint({"b": 1, "a": 2}) == content_fingerprint({"a": 2, "b": 1})
    assert len(content_fingerprint({})) == 64
    with pytest.raises(TestLabError):
        canonical_json({"a": float("nan")})


def test_strict_json_document_decode():
    assert decode_json_document('{"a": [1, 2]}') == {"a": [1, 2]}
    for text in ('{"a": 1, "a": 2}', '{"a": NaN}', '{"a": Infinity}', "{", 3):
        with pytest.raises(TestLabError) as caught:
            decode_json_document(text)
        assert caught.value.code == JSON_INVALID
    with pytest.raises(TestLabError) as caught:
        decode_json_document('{"a": "' + "x" * 100 + '"}', max_bytes=50)
    assert caught.value.code == LIMIT_EXCEEDED


@pytest.mark.parametrize("text", ['{"a": 1e400}', '{"a": -1e400}', '{"a": ' + "9" * 5000 + "}"])
def test_json_overflowing_numbers_are_json_invalid(text):
    with pytest.raises(TestLabError) as caught:
        decode_json_document(text)
    assert caught.value.code == JSON_INVALID


def test_json_deep_nesting_is_a_limit_not_a_crash():
    with pytest.raises(TestLabError) as caught:
        decode_json_document("[" * 100_000 + "]" * 100_000)
    assert caught.value.code in (LIMIT_EXCEEDED, JSON_INVALID)


def test_single_id_timestamp_formatter():
    assert id_timestamp(T0) == "20260917T105800123Z"
    assert format_run_id(T0, NONCE).split("-")[1] == id_timestamp(T0)


#: QA rework F2: metadata names that the name rule must accept (metric, parameter, override, arg key).
METADATA_NAMES = [
    "reason_code", "reasoning_tokens", "llm.prompt_tokens", "token_budget", "max_token_count", "prompt_id",
    "brain.prompt_id", "prompt_variant", "language_code", "status_code", "error_code", "module_id",
    "voice.command_timeout_ms", "tool.function_name", "speech.thinking_filler", "reflex.thinking_pause_ms",
    "wav_gain_db", "pcm.frame_ms", "agent_routing.profiles.code.model", "latency_ms", "llm.tokens",
    "speech.payload_chars", "audio.output_latency_ms", "size_bytes", "turn_id", "barge_in.false_count",
    "provider_first_pcm_ms", "brain.reasoning_effort", "python_version",
    # QA rework 2 (S1, S2): metadata about content, and UI/data-structure keys.
    "max_tokens", "audio_ref", "manual_wake_key", "shortcut_key", "sort_key", "audio.output_device",
]
#: Private names: secrets anywhere, content words as the final word or before a carrier word.
PRIVATE_NAMES = [
    "openai_api_key", "api_key", "apiKey", "openai.api_key", "credentials", "password", "secret", "cookie",
    "session-cookie", "authorization", "providerAccessToken", "chain_of_thought", "reasoning", "thinking", "prompt",
    "brain.reasoning", "hiddenThinking", "thinking_text", "prompt_text", "system_prompt", "raw_audio",
    "audio_bytes", "pcm_frames", "input.wav", "auth_token", "reasoning.summary", "llm.thinking_text",
    # QA rework 2, S1: private content is denied unless the final word is metadata.
    "system_prompt_v2", "prompt_template", "prompt_messages", "chain_of_thought_steps", "cot_steps",
    "reasoning_trace", "reasoning.items", "hidden_reasoning_json", "thinking_log", "instructions",
    "session.instructions", "system_prompt_id", "input_audio_buffer", "prompt.0",
    # QA rework 2, S2: secrets.
    "porcupine_access_key", "openai_key", "signing_key", "ssh_key", "secret_key", "bearer", "auth_header",
    "authHeader", "passphrase", "jwt", "encrypted_content", "reasoning_encrypted_content", "key", "private.key",
]
CODE_NAMES = [
    "agent_cli_settings.claude.command", "agent_cli_settings.codex.command", "code", "source_code", "python_code",
    "shellCommand", "import", "eval_expr", "exec", "on_start_script", "module", "cmd", "python", "lambda",
    "__class__", "_hidden", "run-command", "command_line", "tool.function_args",
]


@pytest.mark.parametrize("key", METADATA_NAMES)
def test_metadata_names_are_accepted(key):
    assert not is_private_key(key)
    assert not is_code_key(key)


@pytest.mark.parametrize("key", PRIVATE_NAMES)
def test_private_names_are_rejected(key):
    assert is_private_key(key)


#: Names `conversation_events.is_forbidden_key` rejects that the Test Lab accepts on purpose.
INTENTIONALLY_ALLOWED = {
    "input": "names audio input devices and scenario inputs; raw tool input is still refused (`tool_input`)",
    "bytes": "a byte size (`size_bytes`); raw bytes are refused by type everywhere",
    "arguments": "scenario primitive arguments are plain data; raw tool arguments are refused (`raw_arguments`)",
    "args": "structural field of a scenario step (`args`)",
}


def test_every_conversation_event_forbidden_name_is_private_or_deliberately_allowed():
    from jarvis.domain import conversation_events as events

    names = sorted(events._FORBIDDEN_KEYS | events._FORBIDDEN_SEGMENTS)
    assert names, "conversation_events forbidden vocabulary moved: this regression would prove nothing"
    for name in names:
        assert events.is_forbidden_key(name)
        assert is_private_key(name) or name in INTENTIONALLY_ALLOWED, name
    for name in INTENTIONALLY_ALLOWED:
        assert name in names and not is_private_key(name), name


@pytest.mark.parametrize("key", CODE_NAMES)
def test_code_names_are_rejected(key):
    assert is_code_key(key)


#: QA rework F3: unambiguous code forms stay rejected by the value heuristic.
@pytest.mark.parametrize("value", ["__import__('os')", "eval(x)", "exec(payload)", "import os", "import os, sys",
                                   "from os import path", "x = 1; import sys", "os.system('dir')", "os.system(",
                                   "subprocess.run(['dir'])", "importlib.import_module('os')", "pickle.loads(b'')",
                                   "().__class__.__bases__", "{{ config.__class__ }}", "#!/bin/sh",
                                   "getattr(__builtins__, 'exec')"])
def test_code_like_values(value):
    assert looks_like_code(value)


@pytest.mark.parametrize("value", [
    "please import the file", "run the command now", "Jarvis, stop talking", "evaluate the echo level",
    "the lambda parameter", "execution ok", "C++ code", "prix: 3 $ (environ)",
    "import photos", "Import contacts", "Je suis un utilisateur lambda : peux-tu m'aider ?",
    "Un citoyen lambda, il est 10:30", "Le subprocess a planté", "Compile (vite) le rapport",
    "exec (le directeur) arrive", "__Important__ : rappelle-moi", "Lance python -c dans le terminal",
    "Ça coûte $(10)", "from Paris import wine", "#! bonjour", "subprocess", "importlib",
])
def test_natural_text_is_not_code(value):
    assert not looks_like_code(value)


def test_private_scan_reports_path_not_value_and_rejects_bytes():
    with pytest.raises(TestLabRedactionError) as caught:
        scan_private({"a": [{"ok": 1}, {"nested": {"api_key": "sk-secret-value"}}]}, "doc")
    assert "doc.a[1].nested.api_key" in str(caught.value)
    assert "sk-secret-value" not in str(caught.value)
    with pytest.raises(TestLabRedactionError):
        scan_private({"a": b"\x00\x01"}, "doc")
