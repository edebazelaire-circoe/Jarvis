"""Processus enfants bornés : délai, arrêt de l'arbre entier, référence de processus fiable, environnement épuré
(Slice 04 de jarvis-remotion-presentation-integration). Vrais petits processus Python, aucun réseau ni npm."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import textwrap
import time

import pytest

from jarvis.adapters import process_tree as pt

GRANDCHILD = textwrap.dedent("""
    import subprocess, sys, time
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    print(child.pid, flush=True)
    time.sleep(60)
""")


def test_run_bounded_returns_output_and_code(tmp_path):
    result = pt.run_bounded([sys.executable, "-c", "print('hello'); import sys; sys.exit(3)"], cwd=tmp_path, env=pt.clean_env(), timeout_s=30)
    assert (result.returncode, result.timed_out, result.started) == (3, False, True) and "hello" in result.output


def test_run_bounded_reports_a_launch_failure_without_raising(tmp_path):
    result = pt.run_bounded([str(tmp_path / "no-such-binary")], cwd=tmp_path, env={}, timeout_s=5)
    assert result.started is False and result.returncode is None and result.output


def test_a_timeout_kills_the_whole_process_tree_including_grandchildren(tmp_path):
    script = tmp_path / "tree.py"
    script.write_text(GRANDCHILD, encoding="utf-8")
    t0 = time.monotonic()
    result = pt.run_bounded([sys.executable, str(script)], cwd=tmp_path, env=pt.clean_env(), timeout_s=3)
    assert result.timed_out and time.monotonic() - t0 < 25
    grandchild = int(result.output.split()[0])
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and pt.pid_exists(grandchild):
        time.sleep(0.2)
    assert not pt.pid_exists(grandchild), "the grandchild survived the timeout"


def test_on_start_receives_the_pid(tmp_path):
    seen: list[int] = []
    pt.run_bounded([sys.executable, "-c", "pass"], cwd=tmp_path, env=pt.clean_env(), timeout_s=30, on_start=seen.append)
    assert len(seen) == 1 and seen[0] > 0


def test_process_refs_recognise_their_process_and_never_a_reused_pid(tmp_path):
    pid = pt.spawn_detached([sys.executable, "-c", "import time; time.sleep(60)"], cwd=tmp_path, env=pt.clean_env(), log_path=tmp_path / "w.log")
    ref = pt.make_process_ref(pid)
    try:
        assert pt.ref_alive(ref) and pt.parse_process_ref(ref) == (pid, ref.split(":")[1])
        assert not pt.ref_alive(f"{pid}:1"), "same pid with another start time must not count as our child"
    finally:
        assert pt.kill_tree(pid)
    assert not pt.ref_alive(ref)


@pytest.mark.parametrize("ref", ["", "abc", "12", "0:5", "-3:4", "x:y"])
def test_malformed_refs_are_never_alive(ref):
    assert pt.parse_process_ref(ref) is None and pt.ref_alive(ref) is False


def test_kill_tree_of_a_gone_pid_is_a_success():
    assert pt.kill_tree(0) and pt.kill_tree(2_000_000_000)


def test_clean_env_keeps_the_allowlist_only_and_applies_extras():
    env = pt.clean_env({"A": "1"}, environ={"PATH": "/x", "Path": "/y", "JARVIS_TOKEN": "s", "OPENAI_API_KEY": "k", "SystemRoot": "C:/W"})
    assert env["A"] == "1" and env["PATH"] == "/x" and env["SystemRoot"] == "C:/W"
    assert "JARVIS_TOKEN" not in env and "OPENAI_API_KEY" not in env
