#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=ROOT,
        text=True,
        check=False,
    )
    if result.returncode:
        fail("pytest failed")

    forbidden_core_imports = ("openai", "httpx", "sounddevice", "pynput")
    for path in (ROOT / "jarvis" / "core").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name.split(".")[0] in forbidden_core_imports for name in names):
                fail(f"provider/runtime dependency leaked into core: {path}: {names}")

    source = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "jarvis").rglob("*.py"))
    dangerous = ["subprocess.run(", "os.system(", "shell=True"]
    for needle in dangerous:
        if needle in source:
            fail(f"dangerous execution primitive in Jarvis package: {needle}")

    lock = json.loads((ROOT / "third_party" / "LOCK.json").read_text(encoding="utf-8"))
    if not lock["runtime_sources"]["barehands"]["commit"] or not lock["runtime_sources"]["ai-visualizer"]["commit"]:
        fail("unpinned runtime source")

    example = (ROOT / "config" / "jarvis.example.toml").read_text(encoding="utf-8")
    if "log_content = false" not in example:
        fail("privacy logging is not disabled by default")

    print("Release verification passed.")


if __name__ == "__main__":
    main()
