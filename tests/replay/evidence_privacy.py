"""Privacy sweep of the Tool Brain evidence (handoff jarvis-tool-brain-ui-orchestrator, Slice 10).

Evidence recorded from real runs (`tasks/jarvis-tool-brain-ui-orchestrator/slices/10-e2e-rollout-hardening/evidence/`) must
never carry what identifies the machine or its owner. The targets are DERIVED AT RUNTIME (never written in the repo): the
home directory in every spelling, the OS user name, the repo checkout path, the temp root, every secret-looking environment
value, and the shapes of tokens and Claude CLI stream events (`system`/`init` carry the session id, cwd, tools, MCP servers).

- `python -m tests.replay.evidence_privacy <dir>`: redact in place (text files), then report what the sweep still finds;
- `sweep(<dir>)`: findings only (used by `tests/unit/test_tool_brain_evidence_privacy.py`).
"""

from __future__ import annotations

import getpass
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Iterable

REPO = Path(__file__).resolve().parents[2]
TEXT_SUFFIXES = {".json", ".md", ".txt", ".jsonl", ".yaml", ".yml"}
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)", re.IGNORECASE)
#: Shapes, not values: provider keys, bearer tokens, and the init event of the Claude CLI stream.
SHAPES = {
    "provider_key": re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    "bearer_token": re.compile(r"Bearer\s+[A-Za-z0-9._\-]{16,}"),
    "claude_init_event": re.compile(r'"subtype"\s*:\s*"init"'),
    "claude_session_id": re.compile(r'"session_id"\s*:\s*"[0-9a-f\-]{8,}"'),
    "windows_user_path": re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+", re.IGNORECASE),
    "posix_home_path": re.compile(r"/(?:home|Users)/[A-Za-z0-9._\-]+/"),
}


def _spellings(path: str) -> set[str]:
    path = path.rstrip("\\/")
    if not path:
        return set()
    forward, back = path.replace("\\", "/"), path.replace("/", "\\")
    escaped = back.replace("\\", "\\\\")  # the JSON spelling of a backslash path
    msys = re.sub(r"^([A-Za-z]):", lambda m: "/" + m.group(1).lower(), forward)
    return {path, forward, back, escaped, msys, forward.lower(), back.lower(), escaped.lower()}


def targets() -> dict[str, set[str]]:
    """Literal strings that must not appear, by category (all derived now, from this machine and this process)."""

    found: dict[str, set[str]] = {"home": set(), "user": set(), "repo": set(), "temp": set(), "secret": set()}
    found["home"] |= _spellings(str(Path.home()))
    for name in ("USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA"):
        found["home"] |= _spellings(os.environ.get(name, ""))
    for user in {getpass.getuser(), os.environ.get("USERNAME", ""), os.environ.get("USER", "")}:
        if len(user) >= 3:
            found["user"].add(user)
            found["user"].add(user.lower())
    found["repo"] |= _spellings(str(REPO))
    found["temp"] |= _spellings(tempfile.gettempdir())
    for name, value in os.environ.items():
        if SECRET_NAME.search(name) and len(value) >= 12 and not value.isdigit():
            found["secret"].add(value)
    return {key: {item for item in values if item} for key, values in found.items()}


def _files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            yield path


def redact_text(text: str) -> str:
    """Replace every target with a stable placeholder (longest first, so a path swallows its own prefixes)."""

    placeholders = {"repo": "<repo>", "temp": "<tmp>", "home": "<home>", "secret": "<redacted-secret>", "user": "<user>"}
    for category in ("repo", "temp", "home", "secret", "user"):
        for target in sorted(targets()[category], key=len, reverse=True):
            text = text.replace(target, placeholders[category])
    for name, pattern in SHAPES.items():
        text = pattern.sub(f"<redacted-{name}>", text)
    return text


def sweep(root: Path) -> list[str]:
    """Findings (`file: category`) in text files under `root`; empty = clean. Never prints the offending value."""

    all_targets = targets()
    findings: list[str] = []
    for path in _files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        lowered = text.lower()
        for category, values in all_targets.items():
            if any(value in text or value.lower() in lowered for value in values):
                findings.append(f"{path.relative_to(root)}: {category}")
        for name, pattern in SHAPES.items():
            if pattern.search(text):
                findings.append(f"{path.relative_to(root)}: shape {name}")
    return findings


def redact_in_place(root: Path) -> int:
    changed = 0
    for path in _files(root):
        before = path.read_text(encoding="utf-8", errors="replace")
        after = redact_text(before)
        if after != before:
            path.write_text(after, encoding="utf-8")
            changed += 1
    return changed


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m tests.replay.evidence_privacy <evidence dir>", file=sys.stderr)
        return 2
    root = Path(argv[0])
    print(f"redacted {redact_in_place(root)} file(s)")
    findings = sweep(root)
    for item in findings:
        print("STILL FOUND", item)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
