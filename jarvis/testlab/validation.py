"""Shared guards of the Test Lab contracts: errors, JSON, text, time, redaction, code.

Binding contract: `docs/testlab.md` ("Errors", "Redaction and forbidden code").
Pure domain: no I/O, no implicit clock. Every error names the field or rule and
never echoes a value, so a rejected secret or snippet cannot leak through a log.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any

from jarvis.domain.conversation_events import (
    ConversationEventError,
    format_event_time,
    parse_event_time,
    to_event_time,  # noqa: F401 - re-exported: callers normalize producer clocks with it
)

#: Largest integer a JSON consumer (JavaScript) reads exactly (same bound as Conversation Events).
MAX_JSON_INT = 2**53
#: Deepest nesting a scanned document may reach (a scenario puts step args at depth 3).
MAX_JSON_DEPTH = 12
#: Deepest nesting of an open JSON value such as scenario step args, counted from that value.
MAX_VALUE_DEPTH = 6
MAX_JSON_TEXT_CHARS = 512
MAX_JSON_LIST_ITEMS = 64
MAX_JSON_OBJECT_KEYS = 64
MAX_DOCUMENT_BYTES = 256 * 1024
MAX_OPEN_KEY_CHARS = 96
MAX_STRING_VALUE_CHARS = 1024

_MAX_NAME_IN_MESSAGE = 64
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
DOTTED_NAME = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*")
SIMPLE_NAME = re.compile(r"[a-z][a-z0-9_]*")


class TestLabError(ValueError):
    """Invalid Test Lab contract value. `code` is stable; the message names fields, never values."""

    __test__ = False  # not a pytest test class, despite the name

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class TestLabRedactionError(TestLabError):
    """A private field (hidden reasoning, prompt, secret, raw audio) or raw bytes were offered."""


class ForbiddenCodeError(TestLabError):
    """A key or value tried to smuggle executable code, a shell command or an import."""


# Stable error codes (documented in docs/testlab.md, "Errors").
FIELD_INVALID = "testlab_field_invalid"
FIELDS_MISMATCH = "testlab_fields_mismatch"
SCHEMA_UNSUPPORTED = "testlab_schema_unsupported"
LIMIT_EXCEEDED = "testlab_limit_exceeded"
REFERENCE_INVALID = "testlab_reference_invalid"
PARAMETER_INVALID = "testlab_parameter_invalid"
FORBIDDEN_PRIVATE_DATA = "testlab_forbidden_private_data"
FORBIDDEN_CODE = "testlab_forbidden_code"
JSON_INVALID = "testlab_json_invalid"


def name_for_message(value: object) -> str:
    """Key/field name safe to put in a message: bounded, lone surrogates escaped."""
    text = str(value)
    text = text if len(text) <= _MAX_NAME_IN_MESSAGE else text[:_MAX_NAME_IN_MESSAGE] + "..."
    return text.encode("utf-8", "backslashreplace").decode("utf-8")


def fail(detail: str, code: str = FIELD_INVALID) -> TestLabError:
    return TestLabError(code, detail)


# ------------------------------------------------------------------ text

def _utf8(value: str, name: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise fail(f"{name} must be valid Unicode text (lone surrogate)") from None


def check_text(value: object, name: str, *, max_chars: int, optional: bool = False) -> None:
    """Nonblank printable single-line text without surrounding whitespace."""
    if optional and value is None:
        return
    if (not isinstance(value, str) or not value or value != value.strip() or len(value) > max_chars
            or not value.isprintable()):
        raise fail(f"{name} must be nonblank printable text of at most {max_chars} characters")
    _utf8(value, name)


def check_name(value: object, name: str, *, pattern: re.Pattern[str] = DOTTED_NAME, max_chars: int = 64,
               optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, str) or len(value) > max_chars or not pattern.fullmatch(value):
        shape = "a dotted lowercase name" if pattern is DOTTED_NAME else "a lowercase snake_case name"
        raise fail(f"{name} must be {shape} of at most {max_chars} characters")


def check_hex(value: object, name: str, *, lengths: tuple[int, ...], optional: bool = False) -> None:
    if optional and value is None:
        return
    if (not isinstance(value, str) or len(value) not in lengths
            or any(char not in "0123456789abcdef" for char in value)):
        raise fail(f"{name} must be {' or '.join(map(str, lengths))} lowercase hex characters")


def check_enum(enum: type[StrEnum], value: object, name: str) -> None:
    if not isinstance(value, enum):
        raise fail(f"{name} is not in the vocabulary")


def decode_enum(enum: type[StrEnum], value: object, name: str) -> Any:
    if not isinstance(value, str):
        raise fail(f"{name} must be a string")
    try:
        return enum(value)
    except ValueError:
        raise fail(f"{name} is not in the vocabulary") from None


def check_bool(value: object, name: str) -> None:
    if type(value) is not bool:
        raise fail(f"{name} must be a boolean")


def check_number(value: object, name: str, *, minimum: float | None = None, maximum: float | None = None,
                 integer: bool = False) -> None:
    """Finite JSON number (never bool). `integer` also refuses floats, even 1.0."""
    allowed = (int,) if integer else (int, float)
    if type(value) not in allowed:
        raise fail(f"{name} must be {'an integer' if integer else 'a number'}")
    if type(value) is float and not math.isfinite(value):
        raise fail(f"{name} must be finite")
    if abs(value) > MAX_JSON_INT:
        raise fail(f"{name} exceeds {MAX_JSON_INT} in magnitude", LIMIT_EXCEEDED)
    if minimum is not None and value < minimum:
        raise fail(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise fail(f"{name} must be <= {maximum}")


# ------------------------------------------------------------------ JSON

def check_json_scalar(value: object, path: str, *, allow_null: bool = False,
                      max_chars: int = MAX_JSON_TEXT_CHARS) -> None:
    if value is None:
        if allow_null:
            return
        raise fail(f"{path} must not be null")
    if type(value) is bool:
        return
    if type(value) in (int, float):
        check_number(value, path)
        return
    if isinstance(value, str) and type(value) is str:
        if len(value) > max_chars:
            raise fail(f"{path} exceeds {max_chars} characters", LIMIT_EXCEEDED)
        _utf8(value, path)
        return
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise TestLabRedactionError(FORBIDDEN_PRIVATE_DATA, f"{path}: raw bytes are forbidden")
    raise fail(f"{path} must be a JSON scalar")


def freeze_json(value: object, path: str, *, depth: int = 0) -> Any:
    """Validate a small JSON value and make it read-only: objects -> MappingProxyType, lists -> tuple."""
    if depth > MAX_VALUE_DEPTH:
        raise fail(f"{path}: nesting exceeds {MAX_VALUE_DEPTH} levels", LIMIT_EXCEEDED)
    if isinstance(value, Mapping):
        if len(value) > MAX_JSON_OBJECT_KEYS:
            raise fail(f"{path} exceeds {MAX_JSON_OBJECT_KEYS} keys", LIMIT_EXCEEDED)
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise fail(f"{path}: object keys must be strings")
            check_text(key, f"{path} key", max_chars=64)
            frozen[key] = freeze_json(item, f"{path}.{name_for_message(key)}", depth=depth + 1)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_JSON_LIST_ITEMS:
            raise fail(f"{path} exceeds {MAX_JSON_LIST_ITEMS} items", LIMIT_EXCEEDED)
        return tuple(freeze_json(item, f"{path}[{index}]", depth=depth + 1) for index, item in enumerate(value))
    check_json_scalar(value, path, allow_null=True)
    return value


def thaw_json(value: Any) -> Any:
    """Inverse of `freeze_json`: plain dict/list, ready for `json.dumps`."""
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def canonical_json(value: object) -> str:
    """Canonical encoding (same as `prompt_registry.fingerprint`): sorted keys, compact, no NaN."""
    try:
        return json.dumps(thaw_json(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False)
    except (TypeError, ValueError):
        raise fail("value is not JSON-encodable", JSON_INVALID) from None


def content_fingerprint(value: object) -> str:
    """64 lowercase hex sha256 of `canonical_json(value)`: equal content, equal fingerprint."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def exact_fields(payload: object, expected: frozenset[str], where: str) -> Mapping[str, Any]:
    """The payload must be an object with exactly `expected` keys. Unknown keys are never ignored."""
    if not isinstance(payload, Mapping):
        raise fail(f"{where} must be a JSON object")
    unknown = sorted(name_for_message(key) for key in set(payload) - expected)
    if unknown:
        raise fail(f"{where}: unknown field(s): {', '.join(unknown)}", FIELDS_MISMATCH)
    missing = sorted(expected - set(payload))
    if missing:
        raise fail(f"{where}: missing field(s): {', '.join(missing)}", FIELDS_MISMATCH)
    return payload


def check_document_header(payload: Mapping[str, Any], schema: str, version: int, where: str) -> None:
    if payload["schema"] != schema or type(payload["schema_version"]) is not int or payload["schema_version"] != version:
        raise fail(f"{where}: unsupported schema; expected {schema} version {version}", SCHEMA_UNSUPPORTED)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise fail(f"duplicate JSON key {name_for_message(key)}", JSON_INVALID)
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise fail("NaN and Infinity are not JSON", JSON_INVALID)


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise fail("a number overflows to Infinity", JSON_INVALID)
    return value


def decode_json_document(text: object, *, max_bytes: int = MAX_DOCUMENT_BYTES) -> Any:
    """Strict JSON text decode: size bound, duplicate keys and NaN/Infinity rejected."""
    if not isinstance(text, str):
        raise fail("document must be JSON text", JSON_INVALID)
    if len(text.encode("utf-8", "surrogatepass")) > max_bytes:
        raise fail(f"document exceeds {max_bytes} bytes", LIMIT_EXCEEDED)
    try:
        return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant,
                          parse_float=_finite_float)
    except TestLabError:
        raise
    except json.JSONDecodeError as exc:
        raise fail(f"document is not valid JSON (line {exc.lineno}, column {exc.colno})", JSON_INVALID) from None
    except ValueError:
        # Integer literal beyond the interpreter's digit limit (`sys.get_int_max_str_digits`).
        raise fail("document holds a number too large to decode", JSON_INVALID) from None
    except RecursionError:
        raise fail("document nesting is too deep to decode", LIMIT_EXCEEDED) from None


# ------------------------------------------------------------------ time

def check_time(value: object, name: str, *, optional: bool = False) -> None:
    """UTC, millisecond precision (Conversation Events wire time; normalize with `to_event_time`)."""
    if optional and value is None:
        return
    if (not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None
            or value.utcoffset().total_seconds() != 0 or value.microsecond % 1000):
        raise fail(f"{name} must be a UTC datetime with millisecond precision (use to_event_time)")


def format_time(value: datetime | None) -> str | None:
    return None if value is None else format_event_time(value)


def parse_time(value: object, name: str, *, optional: bool = False) -> datetime | None:
    if optional and value is None:
        return None
    try:
        return parse_event_time(value, name)
    except ConversationEventError as exc:
        # Same wire rule as Conversation Events; re-raised in the Test Lab error family.
        raise fail(str(exc)) from None


# ------------------------------------------------- redaction and forbidden code

# Name rule (docs/testlab.md, "Redaction and forbidden code"). A key is split into
# words: camelCase, `.`, `-`, `:`, space and `_` all separate words.
#
# Private data, deny by default:
# - a secret word or compound anywhere makes the key private (`password`, `bearer`,
#   `auth_header`, `openai_api_key`); `key` as the final word is a secret unless the
#   word before it is a closed UI or data-structure qualifier (`shortcut_key`,
#   `sort_key`, `manual_wake_key`);
# - `chain_of_thought` and `system_prompt` are private anywhere;
# - a content word (hidden reasoning, prompt, instructions, auth token, raw audio)
#   anywhere makes the key private UNLESS the final word is in the closed metadata
#   vocabulary (`reasoning_tokens`, `prompt_id`, `token_budget`, `wav_gain_db`).
#
# Code names follow a final-word rule: a code word as the final word, or before a
# code carrier word, names code (`command`, `hook.script`, `command_line`);
# `voice.command_timeout_ms` and `module_id` do not. `code` after a qualifier names a
# classification code (`status_code`) unless the qualifier is itself a code word or
# code carrier (`python_code`, `source_code`).
#
# The word sets below are the explicit, closed vocabulary of the rule. It guards
# names; it is not the security boundary (nothing in a Test Lab document is ever
# evaluated, and runners never collect private values).

SECRET_WORDS = frozenset({
    "password", "passwd", "passphrase", "secret", "secrets", "credential", "credentials", "authorization",
    "cookie", "cookies", "apikey", "bearer", "jwt", "otp",
})
SECRET_COMPOUNDS = (
    "api_key", "access_token", "refresh_token", "id_token", "private_key", "access_key", "secret_key",
    "signing_key", "ssh_key", "auth_header", "encrypted_content",
)
#: Words that make a final `key` a keyboard, wake-word or data-structure key, not a credential.
KEY_QUALIFIER_WORDS = frozenset({
    "wake", "hot", "shortcut", "keyboard", "push", "talk", "press", "hold", "toggle", "mute", "trigger", "sort",
    "primary", "foreign", "cache", "dedupe", "idempotency", "partition", "lookup", "join", "group", "index",
    "composite", "row", "map", "dict",
})
PRIVATE_COMPOUNDS = ("chain_of_thought", "system_prompt", "raw_arguments", "tool_input")
PRIVATE_CONTENT_WORDS = frozenset({
    "reasoning", "thinking", "thought", "thoughts", "scratchpad", "cot", "chainofthought", "prompt", "prompts",
    "systemprompt", "instruction", "instructions", "signature", "token", "audio", "pcm", "pcm16", "wav",
})
#: Closed metadata vocabulary: a final word that names a measure, an identifier or a
#: setting *about* content, never the content itself.
METADATA_FINAL_WORDS = frozenset({
    "id", "ids", "ref", "refs", "hash", "fingerprint", "version", "variant", "variants", "kind", "type", "format",
    "mode", "code", "name", "tokens", "count", "counts", "chars", "length", "size", "budget", "limit", "max", "min",
    "ms", "s", "seconds", "duration", "latency", "timeout", "threshold", "rate", "ratio", "percent", "level",
    "gain", "db", "hz", "channels", "bits", "effort", "enabled", "disabled", "filler", "pause", "device",
    "devices", "index", "status", "state", "lang", "language",
})
CODE_WORDS = frozenset({
    "code", "shell", "import", "imports", "eval", "exec", "script", "scripts", "module", "modules", "command",
    "commands", "cmd", "cmdline", "python", "lambda", "callable", "subprocess", "popen", "function", "bash",
    "powershell", "pwsh",
})
CODE_CARRIER_WORDS = frozenset({
    "text", "content", "source", "src", "body", "expr", "expression", "line", "lines", "string", "snippet",
    "args", "argv",
})

_DANGEROUS_MODULES = (r"(?:os|sys|subprocess|shutil|socket|ctypes|importlib|builtins|pickle|marshal|pty|runpy"
                      r"|multiprocessing)")
#: Defense-in-depth HEURISTIC on string values, NOT the security boundary. Only forms
#: with no plausible natural-language reading: a builtin call with no space before its
#: parenthesis, a dunder call or dunder attribute, a call on `os`/`subprocess`/...,
#: an exact import of a dangerous module, a shebang path. Case-sensitive, like Python.
_CODE_VALUE = re.compile(
    r"(?<!\w)__[A-Za-z][A-Za-z0-9_]*__\("
    r"|\.__[A-Za-z][A-Za-z0-9_]*__"
    r"|(?<![\w.])(?:eval|exec|compile|getattr|setattr|delattr|globals|breakpoint)\("
    r"|(?<![\w.])os\.(?:system|popen|exec\w*|spawn\w*|remove|unlink|rmdir|kill)\s*\("
    r"|(?<![\w.])(?:subprocess|importlib|shutil|ctypes|pickle|marshal|builtins|runpy|pty)\.[A-Za-z_]\w*\s*\("
    r"|(?:^|[;\n])\s*import\s+" + _DANGEROUS_MODULES + r"(?:\.\w+)*(?:\s*,\s*[\w.]+)*\s*(?=$|[;\n])"
    r"|(?:^|[;\n])\s*from\s+" + _DANGEROUS_MODULES + r"(?:\.\w+)*\s+import\s+[\w.*]"
    r"|^\s*#!/"
)


def _words(key: str) -> list[list[str]]:
    """Dotted parts of a key, each split into lowercase words."""
    normalized = _CAMEL.sub("_", key).lower()
    for separator in ("-", " ", ":"):
        normalized = normalized.replace(separator, ".")
    parts = ([word for word in part.split("_") if word] for part in normalized.split("."))
    return [part for part in parts if part]


def is_private_key(key: str) -> bool:
    """True when a key names a secret, hidden reasoning, a prompt, instructions, an auth token or raw audio.

    Deny by default: a content word anywhere is private unless the final word is metadata (name rule).
    """
    words = [word for part in _words(key) for word in part]
    if not words:
        return False
    joined = f"_{'_'.join(words)}_"
    if any(word in SECRET_WORDS for word in words) or any(f"_{name}_" in joined for name in SECRET_COMPOUNDS):
        return True
    if words[-1] == "key" and (len(words) == 1 or words[-2] not in KEY_QUALIFIER_WORDS):
        return True
    if any(f"_{name}_" in joined for name in PRIVATE_COMPOUNDS):
        return True
    return any(word in PRIVATE_CONTENT_WORDS for word in words) and words[-1] not in METADATA_FINAL_WORDS


def is_code_key(key: str) -> bool:
    """True when a key names code, a shell command, an import or a module to run (name rule), or is a dunder."""
    if key.startswith("_") or key.endswith("_"):
        return True
    parts = _words(key)
    words = [word for part in parts for word in part]
    if not words:
        return False
    final = words[-1]
    if final == "code":
        leaf = parts[-1]
        qualifier = leaf[-2] if len(leaf) > 1 else None
        return qualifier is None or qualifier in CODE_WORDS or qualifier in CODE_CARRIER_WORDS
    return final in CODE_WORDS or (final in CODE_CARRIER_WORDS and any(word in CODE_WORDS for word in words[:-1]))


def looks_like_code(value: str) -> bool:
    """Defense-in-depth heuristic on string values; never the security boundary."""
    return _CODE_VALUE.search(value) is not None


def scan_private(value: object, path: str, *, depth: int = 0) -> None:
    """Reject private keys and raw bytes at any depth, naming the path, never the value."""
    if depth > MAX_JSON_DEPTH:
        raise fail(f"{path}: nesting exceeds {MAX_JSON_DEPTH} levels", LIMIT_EXCEEDED)
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise TestLabRedactionError(FORBIDDEN_PRIVATE_DATA, f"{path}: raw bytes are forbidden")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if type(key) is not str:
                raise fail(f"{path}: object keys must be strings")
            if is_private_key(key):
                raise TestLabRedactionError(FORBIDDEN_PRIVATE_DATA,
                                            f"{path}.{name_for_message(key)}: forbidden field (private data)")
            scan_private(item, f"{path}.{name_for_message(key)}", depth=depth + 1)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            scan_private(item, f"{path}[{index}]", depth=depth + 1)


def scan_code(value: object, path: str, *, depth: int = 0) -> None:
    """Reject code-carrying keys, code-looking strings and non-JSON types at any depth."""
    if depth > MAX_JSON_DEPTH:
        raise fail(f"{path}: nesting exceeds {MAX_JSON_DEPTH} levels", LIMIT_EXCEEDED)
    if isinstance(value, Mapping):
        for key, item in value.items():
            if type(key) is not str:
                raise fail(f"{path}: object keys must be strings")
            if is_code_key(key):
                raise ForbiddenCodeError(FORBIDDEN_CODE, f"{path}.{name_for_message(key)}: code-carrying field")
            scan_code(item, f"{path}.{name_for_message(key)}", depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            scan_code(item, f"{path}[{index}]", depth=depth + 1)
        return
    if isinstance(value, str) and looks_like_code(value):
        raise ForbiddenCodeError(FORBIDDEN_CODE, f"{path}: value looks like code or a shell command")
    if callable(value) or not (value is None or type(value) in (bool, int, float, str)):
        if isinstance(value, (bytes, bytearray, memoryview)):
            raise TestLabRedactionError(FORBIDDEN_PRIVATE_DATA, f"{path}: raw bytes are forbidden")
        raise ForbiddenCodeError(FORBIDDEN_CODE, f"{path}: only JSON data is allowed")


def check_open_key(key: object, path: str, *, max_chars: int = MAX_OPEN_KEY_CHARS) -> None:
    """Name of an open map entry (parameter, override, scenario arg): no private data, no code."""
    if type(key) is not str:
        raise fail(f"{path}: keys must be strings")
    if is_private_key(key):
        raise TestLabRedactionError(FORBIDDEN_PRIVATE_DATA, f"{path}.{name_for_message(key)}: forbidden field (private data)")
    if is_code_key(key):
        raise ForbiddenCodeError(FORBIDDEN_CODE, f"{path}.{name_for_message(key)}: code-carrying field")
    check_name(key, f"{path}.{name_for_message(key)}", max_chars=max_chars)


def check_scalar_value(value: object, path: str) -> None:
    """JSON scalar of an open map (parameters, overrides): never null, never code-looking text."""
    check_json_scalar(value, path, max_chars=MAX_STRING_VALUE_CHARS)
    if isinstance(value, str) and looks_like_code(value):
        raise ForbiddenCodeError(FORBIDDEN_CODE, f"{path}: value looks like code or a shell command")
