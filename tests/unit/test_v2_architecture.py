from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_domain_and_ports_remain_provider_transport_and_database_neutral():
    forbidden = {"openai", "httpx", "aiohttp", "websockets", "sqlite3", "sounddevice", "winrt", "google", "msal"}
    for folder in (ROOT / "jarvis/domain", ROOT / "jarvis/ports"):
        for path in folder.glob("*.py"):
            leaked = {name for name in imports(path) if name.split(".")[0] in forbidden}
            assert not leaked, f"{path} leaks concrete provider/runtime dependencies: {sorted(leaked)}"


def test_core_does_not_import_concrete_calendar_or_realtime_adapters():
    for path in (ROOT / "jarvis/core").glob("*.py"):
        leaked = {name for name in imports(path) if name.startswith("jarvis.adapters.google_") or name.startswith("jarvis.adapters.openai_realtime")}
        assert not leaked, f"{path} bypasses a v0.2 port: {sorted(leaked)}"
