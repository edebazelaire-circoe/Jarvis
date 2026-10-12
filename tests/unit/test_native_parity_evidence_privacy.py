"""The committed evidence of Slice 13 (native-studio-playback-fix parity benchmark) keeps no local identity, and stays usable.

Real agent traces were committed (both sides). The sweep's targets are derived at runtime (home folder, user names of this machine, email
addresses, token shapes), never written in the repository. Then: every run has its metrics, the blinded decks hide the side (same file
type, same frame count) and the key names one direct and one Jarvis deck per topic.
"""

from __future__ import annotations

import getpass
import hashlib
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

#: Slice 13 rework (QA I1): the user's IGuard README (a private file, read by the agents of both sides) must not sit in a committed trace.
#: The check knows it only by the SHA-256 of eight of its distinctive lines (five of its Infomaniak API lines, three of its prose), whitespace
#: stripped, never by its text; the traces carry `<redacted: IGuard README, N bytes>` where an agent's Read result held it.
IGUARD_README_LINES = frozenset({
    "cde28cb273a600c8d9a75aaafb6fcc9f6053d21e0408ec4ca908cb2aa48e24c1", "f315ecf3ef8ed61d2b47e45f1e1befaf4d0e608ac741a3529493cf560859756a",
    "72ec7469b9e66e22fe246af1f6446a0f78df693e2a20c414b550394d51788e52", "9248fbc2f0ec23c07d92db277e2d071930e1f72ac44726b6a15b021fdb77649f",
    "25b55f17813dcd239ae084b70a2b6c0429ca5eadc82ac3dbd17731bc5c8666fa", "6990944c978e7a187f96b5f465e6cb3ff2b5b9f9ad4e6a63ee3e3c0034ba4979",
    "8df431ce8c2f603ad594467184ee5b017e9b04acd43919b2a82e3993a5aa40cf", "80f868bd2020e4dd2bd6b4b8a653b2674204e2c6b7452f6f4fca116fbb48bf27",
})
NUMBERED = re.compile(r"^\s*\d+\t")  # a Read result line: `cat -n` prefix

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


def readme_lines(text: str, hashes: frozenset[str] = IGUARD_README_LINES) -> int:
    """How many lines of `text` (JSON strings unescaped, `cat -n` prefixes removed) hash to a line of the protected file."""

    found = 0
    for raw in text.splitlines():
        pieces = [raw]
        if raw.lstrip().startswith(("{", "[")):
            try:
                pieces = list(strings(json.loads(raw)))
            except ValueError:
                pieces = [raw]
        for piece in pieces:
            for line in piece.split("\n"):
                if hashlib.sha256(NUMBERED.sub("", line).strip().encode("utf-8")).hexdigest() in hashes:
                    found += 1
    return found


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def test_no_committed_file_of_the_slice_keeps_the_users_iguard_readme():
    held = {}
    for path in sorted(SLICE.rglob("*")):
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES and "__pycache__" not in path.parts:
            count = readme_lines(path.read_text("utf-8", errors="ignore"))
            if count:
                held[str(path.relative_to(SLICE))] = count
    assert held == {}


def test_the_readme_check_sees_a_line_in_a_json_read_result():
    line = "a private line of a README that only this test writes, long enough to be distinctive"
    mine = frozenset({hashlib.sha256(line.encode("utf-8")).hexdigest()})
    trace = json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": f"1\t# x\n2\t{line}\n"}]}})
    assert readme_lines(trace, mine) == 1 and readme_lines(f"    7\t{line}", mine) == 1 and readme_lines("nothing", mine) == 0
