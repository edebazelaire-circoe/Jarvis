"""Tests for the Test Lab run capturers: git identity, environment, config snapshot (docs/testlab.md, Capture)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from enum import Enum
import getpass
import json
from pathlib import Path
import socket

import pytest

from jarvis.testlab.capture import (
    CAPTURE_UNAVAILABLE,
    CONFIG_SNAPSHOT_PATH,
    ENVIRONMENT_FACTS,
    REDACTED,
    EnvironmentProbe,
    TestLabCaptureError,
    build_config_snapshot,
    capture_code_identity,
    capture_environment,
    failure_detail,
    git_worktree_dirty,
    identity_fragments,
    read_git_revision,
    redact_evidence,
    redact_identifying_text,
    redact_urls,
    store_config_snapshot,
)
from jarvis.runtime import credentials
from jarvis.testlab.filesystem_store import FilesystemTestRunStore
from jarvis.testlab.store import ENVIRONMENT_FACT_NAMES
from jarvis.testlab.runs import ArtifactKind, TestRun
from jarvis.testlab.validation import TestLabError, TestLabRedactionError, content_fingerprint
from tests.fakes.testlab import queued_run

REV_A = "a" * 40
REV_B = "b" * 40
REV_SHA256 = "c" * 64


def fake_repo(root: Path, head: str, *, loose: dict[str, str] | None = None, packed: str | None = None) -> Path:
    git_dir = root / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text(head + "\n", encoding="utf-8")
    for ref, value in (loose or {}).items():
        path = git_dir / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value + "\n", encoding="utf-8")
    if packed is not None:
        (git_dir / "packed-refs").write_text(packed, encoding="utf-8")
    return root


# ------------------------------------------------------------------- git

def test_detached_head(tmp_path):
    assert read_git_revision(fake_repo(tmp_path, REV_A)) == REV_A
    assert read_git_revision(fake_repo(tmp_path / "sha256", REV_SHA256)) == REV_SHA256


def test_loose_ref_wins_over_packed_ref(tmp_path):
    packed = f"# pack-refs with: peeled fully-peeled sorted\n{REV_B} refs/heads/main\n"
    repo = fake_repo(tmp_path, "ref: refs/heads/main", loose={"refs/heads/main": REV_A}, packed=packed)
    assert read_git_revision(repo) == REV_A


def test_packed_ref_with_peeled_lines(tmp_path):
    packed = (f"# pack-refs with: peeled fully-peeled sorted\n{REV_A} refs/heads/other\n{REV_B} refs/tags/v1\n"
              f"^{REV_A}\n{REV_B} refs/heads/task/x\n")
    assert read_git_revision(fake_repo(tmp_path, "ref: refs/heads/task/x", packed=packed)) == REV_B


def test_symbolic_ref_chain(tmp_path):
    repo = fake_repo(tmp_path, "ref: refs/heads/alias", loose={"refs/heads/alias": "ref: refs/heads/main",
                                                               "refs/heads/main": REV_A})
    assert read_git_revision(repo) == REV_A


def test_linked_worktree_reads_common_dir(tmp_path):
    common = tmp_path / "main" / ".git"
    common.mkdir(parents=True)
    (common / "packed-refs").write_text(f"{REV_B} refs/heads/feature\n", encoding="utf-8")
    worktree_git = common / "worktrees" / "wt"
    worktree_git.mkdir(parents=True)
    (worktree_git / "HEAD").write_text("ref: refs/heads/feature\n", encoding="utf-8")
    (worktree_git / "commondir").write_text("../..\n", encoding="utf-8")
    checkout = tmp_path / "wt"
    checkout.mkdir()
    (checkout / ".git").write_text(f"gitdir: {worktree_git}\n", encoding="utf-8")
    assert read_git_revision(checkout) == REV_B


@pytest.mark.parametrize("head, extra", [
    ("ref: refs/heads/unborn", {}),
    ("garbage", {}),
    ("ref: refs/heads/../../escape", {}),
    ("ref: refs/heads/loop", {"refs/heads/loop": "ref: refs/heads/loop"}),
])
def test_unresolvable_head_is_typed_error(tmp_path, head, extra):
    with pytest.raises(TestLabCaptureError) as caught:
        read_git_revision(fake_repo(tmp_path, head, loose=extra))
    assert caught.value.code == CAPTURE_UNAVAILABLE


def test_no_repository_is_typed_error(tmp_path):
    with pytest.raises(TestLabCaptureError):
        read_git_revision(tmp_path)


def test_error_messages_do_not_carry_local_paths(tmp_path):
    with pytest.raises(TestLabCaptureError) as caught:
        read_git_revision(tmp_path)
    assert str(tmp_path) not in str(caught.value)


def test_capture_code_identity_uses_injected_dirty_probe(tmp_path):
    repo = fake_repo(tmp_path, REV_A)
    seen: list[Path] = []

    async def dirty(path: Path) -> bool:
        seen.append(path)
        return True

    identity = asyncio.run(capture_code_identity(repo, dirty_probe=dirty))
    assert (identity.git_revision, identity.dirty) == (REV_A, True)
    assert seen == [repo]

    async def not_bool(path: Path):
        return "yes"

    with pytest.raises(TestLabError):
        asyncio.run(capture_code_identity(repo, dirty_probe=not_bool))


def test_default_dirty_probe_maps_git_failure_to_typed_error(tmp_path, monkeypatch):
    from jarvis.runtime.worktrees import WorktreeError
    calls: list[tuple] = []

    async def failing_git(*args, cwd):
        calls.append(args)
        raise WorktreeError("worktree_git_failed", f"fatal: not a git repository: {cwd}")

    monkeypatch.setattr("jarvis.testlab.capture.git", failing_git)
    with pytest.raises(TestLabCaptureError) as caught:
        asyncio.run(git_worktree_dirty(tmp_path))
    assert "worktree_git_failed" in caught.value.detail and str(tmp_path) not in str(caught.value)
    assert calls == [("--no-optional-locks", "status", "--porcelain", "--", ".", ":(exclude)data/state")]

    async def clean_git(*args, cwd):
        return "\n"

    monkeypatch.setattr("jarvis.testlab.capture.git", clean_git)
    assert asyncio.run(git_worktree_dirty(tmp_path)) is False


# ------------------------------------------------------------ environment

def _identity_values() -> list[str]:
    values = [socket.gethostname(), str(Path.home())]
    try:
        values.append(getpass.getuser())
    except OSError:
        pass
    return [value for value in values if len(value) >= 3]


def test_environment_emits_only_closed_non_identifying_facts():
    capture = capture_environment()
    assert set(capture.facts) <= set(ENVIRONMENT_FACTS)
    assert set(ENVIRONMENT_FACTS) == {"os", "os_release", "os_version", "machine", "python_implementation",
                                      "python_version", "host.cpu_count", "host.memory_gib_bucket"}
    for value in capture.facts.values():
        for identity in _identity_values():
            assert identity.casefold() not in str(value).casefold()
    assert {"os", "python_version"} <= set(capture.facts)
    # The facts are valid TestRun environment entries.
    assert dict(queued_run(environment=capture.facts).environment) == dict(capture.facts)


def test_identity_fragments_cover_user_host_home():
    fragments = {item.casefold() for item in identity_fragments()}
    for identity in _identity_values():
        assert identity.casefold() in fragments


def test_identifying_probe_values_are_dropped():
    host = "WORKSTATION-7"
    probe = EnvironmentProbe(os_version=lambda: f"10.0 built on workstation-7", machine=lambda: r"C:\Users\alice",
                             cpu_count=lambda: 8)
    capture = capture_environment(probe, fragments=[host, r"C:\Users\alice", "al"])
    assert "os_version" not in capture.facts and "machine" not in capture.facts
    assert ("os_version", "identifying") in capture.omitted and ("machine", "identifying") in capture.omitted
    assert capture.facts["host.cpu_count"] == 8


def test_failing_empty_and_invalid_probes_are_omitted_with_reason():
    def boom():
        raise OSError("no platform")

    probe = EnvironmentProbe(os_family=boom, os_release=lambda: "", python_version=lambda: object(),
                             os_version=lambda: "__import__('os').system('x')")
    capture = capture_environment(probe, fragments=[])
    assert dict(capture.omitted) == {"os": "probe_failed", "os_release": "unavailable",
                                     "python_version": "invalid", "os_version": "invalid"}


# -------------------------------------------------------- config snapshot

class Arch(Enum):
    LEGACY = "legacy"


@dataclass(frozen=True)
class FakeSettings:
    runtime_root: Path
    token_file: Path
    voice_arch: Arch
    active_timeout_s: float


def test_snapshot_redacts_secrets_and_keeps_presence(tmp_path):
    home = tmp_path / "home" / "alice"
    settings = {
        "openai_api_key": "sk-live-123456",
        "porcupine_access_key": "",
        "credentials": [{"id": "cred_1", "provider": "openai", "value": "sk-abc"}],
        "audio_input_device": "Microphone",
        "agent_cli": {"command": str(home / "bin" / "claude.exe"), "args": ["--x"]},
        "nested": {"password": None, "system_prompt": "You are Jarvis"},
    }
    snapshot = build_config_snapshot(settings, home=home)
    text = snapshot.encoded.decode("utf-8")
    for secret in ("sk-live-123456", "sk-abc", "You are Jarvis", "alice"):
        assert secret not in text
    doc = json.loads(text)
    assert doc["schema"] == "jarvis.testlab.config_snapshot" and doc["schema_version"] == 1
    assert doc["settings"]["openai_api_key"] == REDACTED
    assert doc["settings"]["porcupine_access_key"] == ""
    assert doc["settings"]["credentials"] == REDACTED
    assert doc["settings"]["nested"] == {"password": None, "system_prompt": REDACTED}
    assert doc["settings"]["agent_cli"]["command"].startswith("~")
    assert snapshot.redacted == 3
    assert snapshot.fingerprint == content_fingerprint(doc)


def test_snapshot_fingerprint_ignores_secret_value_but_not_presence_or_settings(tmp_path):
    base = {"openai_api_key": "one", "active_timeout_s": 90}
    fp = build_config_snapshot(base, home=tmp_path).fingerprint
    assert build_config_snapshot({**base, "openai_api_key": "two"}, home=tmp_path).fingerprint == fp
    assert build_config_snapshot({**base, "openai_api_key": ""}, home=tmp_path).fingerprint != fp
    assert build_config_snapshot({**base, "active_timeout_s": 60}, home=tmp_path).fingerprint != fp


def test_snapshot_accepts_settings_dataclass(tmp_path):
    settings = FakeSettings(tmp_path / "runtime", tmp_path / "runtime" / "core.token", Arch.LEGACY, 90.0)
    doc = build_config_snapshot(settings, home=tmp_path).document
    assert doc["settings"]["voice_arch"] == "legacy"
    assert doc["settings"]["runtime_root"] == str(Path("~") / "runtime")
    assert doc["settings"]["token_file"] == REDACTED  # `token` is private content under the name rule


@pytest.mark.parametrize("settings, error", [
    ({"blob": b"\x00"}, TestLabRedactionError),
    ({"x": float("nan")}, TestLabError),
    ({"x": {1, 2}}, TestLabError),
    ({1: "x"}, TestLabError),
])
def test_snapshot_refuses_non_json(settings, error, tmp_path):
    with pytest.raises(error):
        build_config_snapshot(settings, home=tmp_path)


def test_store_config_snapshot_round_trip(tmp_path):
    store = FilesystemTestRunStore(tmp_path / "testlab")
    snapshot = build_config_snapshot({"active_timeout_s": 90, "openai_api_key": "sk"}, home=tmp_path)
    run = queued_run(config_fingerprint=snapshot.fingerprint)
    store.create_run(run)
    ref = store_config_snapshot(store, run.run_id, snapshot)
    assert (ref.kind, ref.path, ref.media_type) == (ArtifactKind.CONFIG_SNAPSHOT, CONFIG_SNAPSHOT_PATH,
                                                    "application/json")
    stored: TestRun = store.update_run(replace(run, artifacts=(ref,)), expected=run)
    raw = store.read_artifact(stored.run_id, CONFIG_SNAPSHOT_PATH)
    assert content_fingerprint(json.loads(raw)) == stored.config_fingerprint


# ------------------------------------------------------------------ rework

def test_environment_fact_names_are_the_store_set():
    assert set(ENVIRONMENT_FACTS) == ENVIRONMENT_FACT_NAMES


def test_snapshot_redacts_every_canonical_credential_key(tmp_path):
    """S3: tied to `jarvis/runtime/credentials.py`, the canonical secret source (imported, never copied)."""
    keys = set(credentials.LEGACY_KEYS)
    keys |= {name for spec in credentials.PROVIDERS for name in spec.env}
    keys |= {"credentials", "credential_bindings"}  # the storage keys credentials.py writes into settings
    assert len(keys) >= 12
    settings = {key: f"secret-value-{index}" for index, key in enumerate(sorted(keys))}
    snapshot = build_config_snapshot(settings, home=tmp_path)
    assert snapshot.document["settings"] == {key: REDACTED for key in keys}
    assert "secret-value" not in snapshot.encoded.decode("utf-8")


@pytest.mark.parametrize("text, expected, changed", [
    ("https://u:p@host.example:8443/x/y?token=abc#frag", "https://host.example:8443/x/y", 1),
    ("proxy http://me@proxy.local/ and ws://h/p?k=v", "proxy http://proxy.local/ and ws://h/p", 2),
    ("https://plain.host/path", "https://plain.host/path", 0),
    ("http://[::1/x?q=1", "http://<redacted>", 1),
    ("no url here", "no url here", 0),
])
def test_redact_urls(text, expected, changed):
    assert redact_urls(text) == (expected, changed)


def test_snapshot_strips_url_credentials_under_harmless_keys(tmp_path):
    snapshot = build_config_snapshot({"endpoint": "https://u:p@api.example/v1?token=abc", "nested": [
        "wss://relay.example/socket?sig=xyz"]}, home=tmp_path)
    settings = snapshot.document["settings"]
    assert settings == {"endpoint": "https://api.example/v1", "nested": ["wss://relay.example/socket"]}
    assert snapshot.redacted == 2


# ------------------------------------------------ rework 2: emails, SSH, prose

@pytest.mark.parametrize("text, expected", [
    ("user@example.com", "<email>"),
    ("mailto:user@example.com", "mailto:<email>"),
    ("Contact: bob@corp.fr (urgent)", "Contact: <email> (urgent)"),
    ("a.b+c@sub.example.co.uk, then", "<email>, then"),
    ("git@github.com:org/repo.git", "github.com:org/repo.git"),
    ("ssh://git@github.com/org/repo.git", "ssh://github.com/org/repo.git"),
    ("https://medium.com/@user/post", "https://medium.com/@user/post"),
    ("user@example.com: hello", "<email>: hello"),
    ("C:\\Users\\x\\app", "C:\\Users\\x\\app"),
])
def test_redact_identifying_text(text, expected):
    assert redact_identifying_text(text)[0] == expected


@pytest.mark.parametrize("text, expected, changed", [
    ("Tu connais http://site.fr?", "Tu connais http://site.fr?", 0),
    ("Voir https://exemple.fr, puis continue.", "Voir https://exemple.fr, puis continue.", 0),
    ("x http://h/p?token=abc.", "x http://h/p.", 1),
    ("(https://h/p?k=v)", "(https://h/p)", 1),
])
def test_redact_urls_keeps_trailing_prose_punctuation(text, expected, changed):
    assert redact_urls(text) == (expected, changed)


def test_url_path_secrets_are_not_detected_by_value():
    """Documented limit: a token inside a URL path is kept; such settings must be caught by name."""
    webhook = "https://hooks.slack.com/services/T000/B000/SECRETTOKEN"
    assert redact_urls(webhook) == (webhook, 0)


def test_snapshot_replaces_emails_and_ssh_users(tmp_path):
    snapshot = build_config_snapshot({"owner": "Contact alice@example.org", "remote": "git@github.com:org/repo.git"},
                                     home=tmp_path)
    assert snapshot.document["settings"] == {"owner": "Contact <email>", "remote": "github.com:org/repo.git"}
    assert "alice" not in snapshot.encoded.decode("utf-8") and snapshot.redacted == 2


# ----------------------------------------------- captured evidence (Slice 05)

#: The exact line a real worker printed during QA: the token survived every
#: shape-based rule, because a credential has no shape of its own.
QA_BEARER_LINE = "Authorization: Bearer " + "QA" + "BEARERTOKEN"


@pytest.mark.parametrize("line, gone", [
    (QA_BEARER_LINE, "BEARERTOKEN"),
    ("Bearer " + "QA" + "BEARERTOKEN", "BEARERTOKEN"),
    ("Authorization: Bearer x", "Bearer x"),
    ("basic QWxhZGRpbjpvcGVuIHNlc2FtZQ==", "QWxhZGRpbg"),
    ("api_key=" + "sk-live" + "-abcdefgh", "abcdefgh"),
    ("api-key: " + "9" * 12, "9" * 12),
    ("X-Api-Key: abc", ": abc"),
    ("password: hunter2", "hunter2"),
    ("passwd=hunter2", "hunter2"),
    ("client_secret = " + "z" * 20, "z" * 20),
    ("token: " + "t" * 20, "t" * 20),
    ("ghp_" + "A" * 20 + " leaked", "ghp_"),
    ("digest " + "0123456789abcdef" * 3, "0123456789abcdef"),
])
def test_captured_evidence_loses_every_credential_shape(line, gone):
    redacted = redact_evidence(line)
    assert gone not in redacted
    assert REDACTED in redacted


@pytest.mark.parametrize("line", [
    "the token budget is 500",
    "token budget exceeded",
    "RuntimeError: the runner failed on purpose",
    "basic checks passed in 12 ms",
    "authorization was never requested",
    "worker pid=1234 run=tlr-20260917T120000000Z-0123456789abcdef",
])
def test_captured_evidence_leaves_prose_alone(line):
    assert redact_evidence(line) == line


def test_captured_evidence_loses_the_identity_of_this_host():
    redacted = redact_evidence("failure at " + str(Path.home()))
    for fragment in identity_fragments():
        assert fragment not in redacted


def test_a_failure_detail_is_one_printable_bounded_line():
    detail = failure_detail("first line\nsecond\tline with " + "sk-live" + "-ABCDEFGH1234 " + "x" * 900)
    assert "\n" not in detail and "\t" not in detail
    assert "sk-live" not in detail
    assert len(detail) <= 512
    assert failure_detail("   ") == "no further detail"
