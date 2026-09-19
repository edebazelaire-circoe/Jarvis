"""Test Lab identity: schema version, diagnostic id and version, run/sweep/bundle ids.

Binding contract: `docs/testlab.md` ("Identity"). Pure: the clock reading and
the entropy of an id are arguments, never read here, so the same inputs always
give the same id.
"""

from __future__ import annotations

from datetime import UTC, datetime
import re

from jarvis.testlab.validation import DOTTED_NAME, check_hex, check_time, fail

TESTLAB_SCHEMA_VERSION = 1
#: Self-describing document names (same idiom as `jarvis.voice_replay` fixtures).
DIAGNOSTIC_SPEC_SCHEMA = "jarvis.testlab.diagnostic"
SCENARIO_SCHEMA = "jarvis.testlab.scenario"
TEST_RUN_SCHEMA = "jarvis.testlab.run"
DIAGNOSTIC_BUNDLE_SCHEMA = "jarvis.testlab.bundle"

MAX_DIAGNOSTIC_ID_CHARS = 64
MAX_DIAGNOSTIC_VERSION = 2**31 - 1
NONCE_HEX_CHARS = 16

RUN_ID_PREFIX = "tlr"
SWEEP_ID_PREFIX = "tls"
BUNDLE_ID_PREFIX = "tlb"
_TIMED_ID = re.compile(r"(tl[rsb])-(\d{8}T\d{9}Z)-([0-9a-f]{16})")


def check_diagnostic_id(value: object, name: str = "diagnostic_id") -> None:
    """Dotted lowercase, at least two segments, `<domain>.<name>` (e.g. `voice.self_echo`)."""
    if (not isinstance(value, str) or len(value) > MAX_DIAGNOSTIC_ID_CHARS or not DOTTED_NAME.fullmatch(value)
            or "." not in value):
        raise fail(f"{name} must be <domain>.<name> in dotted lowercase, at most {MAX_DIAGNOSTIC_ID_CHARS} characters")


def diagnostic_domain(diagnostic_id: str) -> str:
    """The first segment of a diagnostic id, which is its catalog domain."""
    check_diagnostic_id(diagnostic_id)
    return diagnostic_id.split(".", 1)[0]


def check_diagnostic_version(value: object, name: str = "diagnostic_version") -> None:
    """Positive integer. Runs compare only within one (diagnostic_id, version)."""
    if type(value) is not int or not 1 <= value <= MAX_DIAGNOSTIC_VERSION:
        raise fail(f"{name} must be an integer from 1 to {MAX_DIAGNOSTIC_VERSION}")


def id_timestamp(created_at: datetime) -> str:
    """`YYYYMMDDTHHMMSSmmmZ`: the time segment of run, sweep and bundle ids (single formatter)."""
    check_time(created_at, "created_at")
    return created_at.strftime("%Y%m%dT%H%M%S") + f"{created_at.microsecond // 1000:03d}Z"


def _format_timed_id(prefix: str, created_at: datetime, nonce: str) -> str:
    stamp = id_timestamp(created_at)
    check_hex(nonce, "nonce", lengths=(NONCE_HEX_CHARS,))
    return f"{prefix}-{stamp}-{nonce}"


def format_run_id(created_at: datetime, nonce: str) -> str:
    """`tlr-YYYYMMDDTHHMMSSmmmZ-<16 hex>`. Ids sort by creation time; the nonce disambiguates.

    `created_at` is the UTC millisecond time the run is queued (normalize with
    `to_event_time`); `nonce` is supplied by the caller (`secrets.token_hex(8)`,
    or a content hash prefix when the id must be idempotent).
    """
    return _format_timed_id(RUN_ID_PREFIX, created_at, nonce)


def format_sweep_id(created_at: datetime, nonce: str) -> str:
    """`tls-YYYYMMDDTHHMMSSmmmZ-<16 hex>`, same rules as `format_run_id`."""
    return _format_timed_id(SWEEP_ID_PREFIX, created_at, nonce)


def format_bundle_id(created_at: datetime, nonce: str) -> str:
    """`tlb-YYYYMMDDTHHMMSSmmmZ-<16 hex>`, same rules as `format_run_id`."""
    return _format_timed_id(BUNDLE_ID_PREFIX, created_at, nonce)


def _check_timed_id(value: object, prefix: str, name: str, optional: bool) -> None:
    if optional and value is None:
        return
    match = _TIMED_ID.fullmatch(value) if isinstance(value, str) else None
    if match is None or match.group(1) != prefix:
        raise fail(f"{name} must match {prefix}-YYYYMMDDTHHMMSSmmmZ-<16 lowercase hex>")
    try:
        datetime.strptime(match.group(2)[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        raise fail(f"{name} does not carry a valid calendar time") from None


def id_created_at(value: str, name: str = "id") -> datetime:
    """The creation time a run, sweep or bundle id carries. The inverse of `id_timestamp`.

    Slice 12 retention ages a sweep or a bundle from here rather than from its decoded
    record: the id is validated on every read, the two can never disagree (a record whose
    id time differs from its `created_at` does not construct), and a retention pass over a
    thousand entries must not decode a thousand documents to find out how old they are.
    """
    match = _TIMED_ID.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise fail(f"{name} must be a Test Lab id carrying a timestamp")
    stamp = match.group(2)
    try:
        moment = datetime.strptime(stamp[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        raise fail(f"{name} does not carry a valid calendar time") from None
    return moment.replace(microsecond=int(stamp[15:18]) * 1000, tzinfo=UTC)


def check_run_id(value: object, name: str = "run_id", *, optional: bool = False) -> None:
    _check_timed_id(value, RUN_ID_PREFIX, name, optional)


def check_sweep_id(value: object, name: str = "sweep_id", *, optional: bool = False) -> None:
    _check_timed_id(value, SWEEP_ID_PREFIX, name, optional)


def check_bundle_id(value: object, name: str = "bundle_id", *, optional: bool = False) -> None:
    _check_timed_id(value, BUNDLE_ID_PREFIX, name, optional)
