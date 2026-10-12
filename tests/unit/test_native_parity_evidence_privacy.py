"""The committed evidence of Slice 13 (native-studio-playback-fix parity benchmark) keeps no local identity, and stays usable.

Real agent traces were committed (both sides). The sweep's targets are derived at runtime (home folder, user names of this machine, email
addresses, token shapes), never written in the repository. Then: every run has its metrics, the blinded decks hide the side (same file
type, same frame count) and the key names one direct and one Jarvis deck per topic.
"""

from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[2]
SLICE = ROOT / "tasks" / "jarvis-remotion-native-studio-playback-fix" / "slices" / "13-claude-native-generation-parity"
EVIDENCE = SLICE / "evidence"
TEXT_SUFFIXES = {".md", ".json", ".jsonl", ".txt", ".py", ".tsx", ".ts", ".js"}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
ALLOWED_EMAILS = {"noreply@anthropic.com"}
TOKENS = (re.compile(r"Bearer\s+(?!\$\{|<|\{)[A-Za-z0-9._~+/=-]{16,}"), re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}"),
          re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"), re.compile(r"\"(?:token|api_key)\"\s*:\s*\"(?!<)[A-Za-z0-9._~+/=-]{16,}\""))

pytestmark = pytest.mark.skipif(not EVIDENCE.exists(), reason="handoff folder archived elsewhere")


def user_names() -> list[str]:
    names = {os.environ.get("USERNAME", ""), os.environ.get("USER", ""), Path.home().name}
    try:
        names.add(getpass.getuser())
    except (KeyError, OSError):
        pass
    return sorted(n for n in names if len(n) >= 3)


def findings(text: str) -> list[str]:
    hits = []
    home = str(Path.home())
    for form in (home, home.replace("\\", "/"), home.replace("\\", "\\\\")):
        if form.lower() in text.lower():
            hits.append("<home>")
            break
    for name in user_names():
        if re.search(r"(?<![A-Za-z])" + re.escape(name) + r"(?![a-z])", text, re.I):
            hits.append("<user>")
    if any(m.lower() not in ALLOWED_EMAILS for m in EMAIL.findall(text)):
        hits.append("email")
    if any(p.search(text) for p in TOKENS):
        hits.append("token")
    return hits


def test_no_committed_file_of_the_slice_keeps_a_home_path_a_user_name_an_email_or_a_token():
    leaks = {}
    for path in sorted(SLICE.rglob("*")):
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES and "__pycache__" not in path.parts:
            hits = findings(path.read_text("utf-8", errors="ignore"))
            if hits:
                leaks[str(path.relative_to(SLICE))] = hits
    assert leaks == {}


def test_the_sweep_sees_what_it_refuses():
    assert "<home>" in findings(f"cwd {Path.home()}\\x")
    for name in user_names():
        assert "<user>" in findings(f"auteur : {name}.")
    assert "email" in findings("écrire à quelqu.un@exemple.org") and "token" in findings("Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123")
    assert findings("Co-Authored-By: Claude <noreply@anthropic.com>") == []


def test_every_run_has_its_metrics_and_the_blinded_decks_hide_the_side():
    index = json.loads((EVIDENCE / "runs" / "index.json").read_text(encoding="utf-8"))
    for run in index:
        metrics = json.loads((EVIDENCE / "runs" / run / "metrics.json").read_text(encoding="utf-8"))
        assert metrics["run"] == run and metrics["agents"]
    key = json.loads((EVIDENCE / "blind" / "key.json").read_text(encoding="utf-8"))
    for topic, decks in key.items():
        assert {d["side"] for d in decks.values()} == {"direct", "jarvis"}
        shown = [sorted(p.name for p in (EVIDENCE / "blind" / topic / deck).iterdir()) for deck in decks]
        assert shown[0] == shown[1] and all(name.endswith(".jpg") for name in shown[0]), "same names, same type: nothing tells the side"
