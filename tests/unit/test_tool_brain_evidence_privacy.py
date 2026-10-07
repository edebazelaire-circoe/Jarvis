"""Privacy sweep of the Tool Brain real-run evidence (handoff jarvis-tool-brain-ui-orchestrator, S10).

The targets are derived at runtime (`tests/replay/evidence_privacy.py`): home directory in every spelling, OS user name,
checkout path, temp root, secret-looking environment values, token shapes and the Claude CLI `system`/`init` event.
"""

from __future__ import annotations

import getpass
from pathlib import Path

from tests.replay import evidence_privacy as privacy

EVIDENCE = (Path(__file__).resolve().parents[2] / "tasks" / "jarvis-tool-brain-ui-orchestrator" / "slices"
            / "10-e2e-rollout-hardening" / "evidence")


def test_the_recorded_evidence_carries_nothing_that_identifies_the_machine_or_its_owner():
    assert EVIDENCE.is_dir() and any(EVIDENCE.rglob("*.json")), "the evidence directory must exist and hold the real runs"
    assert privacy.sweep(EVIDENCE) == []


def test_the_sweep_can_fail_and_the_redaction_repairs_what_it_finds(tmp_path, monkeypatch):
    monkeypatch.setenv("TB_TEST_API_KEY", "k" * 24)
    leaky = tmp_path / "leak.json"
    home = str(Path.home())
    leaky.write_text("\n".join([
        f'{{"cwd": "{home.replace(chr(92), chr(92) * 2)}"}}', f"user {getpass.getuser()}",
        '{"type":"system","subtype":"init","session_id":"0b8d2c1e-aaaa-bbbb-cccc-123456789abc"}',
        "key " + "k" * 24, "Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345", "sk-abcdefghijklmnopqrstuvwx"]),
        encoding="utf-8")
    kinds = {line.split(": ", 1)[1] for line in privacy.sweep(tmp_path)}
    assert {"home", "user", "secret", "shape claude_init_event", "shape claude_session_id", "shape bearer_token",
            "shape provider_key"} <= kinds
    assert privacy.redact_in_place(tmp_path) == 1
    assert privacy.sweep(tmp_path) == []
    assert "k" * 24 not in leaky.read_text(encoding="utf-8")


def test_the_targets_are_derived_not_written_in_the_repository():
    targets = privacy.targets()
    assert str(Path.home()) in targets["home"] and getpass.getuser() in targets["user"]
    source = Path(privacy.__file__).read_text(encoding="utf-8")
    assert getpass.getuser() not in source or len(getpass.getuser()) < 4  # no literal user name in the module
