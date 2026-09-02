from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_supervisor_uses_exec_not_shell_and_starts_core_before_voice():
    source = (ROOT / "scripts" / "supervisor_v2.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "create_subprocess_shell" not in source
    assert "shell=True" not in source
    assert 'await self.spawn("core", "core")' in source
    assert "await self.wait_core_ready()" in source
    assert 'await self.spawn("voice", "voice")' in source
    assert source.index('await self.spawn("core", "core")') < source.index("await self.wait_core_ready()") < source.index('await self.spawn("voice", "voice")')
    assert any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "create_subprocess_exec" for node in ast.walk(tree))


def test_windows_autostart_is_user_scope_idempotent_and_non_admin():
    source = (ROOT / "scripts" / "windows_autostart.ps1").read_text(encoding="utf-8")
    assert "-AtLogOn" in source
    assert "-RunLevel Limited" in source
    assert "MultipleInstances IgnoreNew" in source
    assert "Unregister-ScheduledTask" in source
    assert "RunLevel Highest" not in source
    assert "Start-Process" not in source
