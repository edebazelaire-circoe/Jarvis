"""The Slice 01 Test Lab contract modules stay pure (docs/testlab.md, Invariants)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
#: Slice 02 adds the store port and the retention planner, which stay pure (the
#: filesystem adapter and the capturers are the I/O modules). Slice 03 adds the
#: DiagnosticBundle schema, rules, builder and the shared redaction helpers (the
#: capture service and the bundle store adapter are the I/O modules).
CONTRACT_MODULES = ("__init__", "validation", "identity", "profiles", "diagnostics", "scenarios", "runs", "store",
                    "retention", "redaction", "bundle", "bundle_rules", "bundle_builder")
ALLOWED_IMPORTS = {
    "__future__", "collections.abc", "dataclasses", "datetime", "enum", "hashlib", "json", "math", "re", "types",
    "typing", "jarvis.domain.conversation_events", "jarvis.domain.voice_state", "jarvis.testlab.validation",
    "jarvis.testlab.identity", "jarvis.testlab.profiles", "jarvis.testlab.diagnostics", "jarvis.testlab.runs",
    "jarvis.testlab.store", "urllib.parse", "jarvis.domain.conversation_event_store", "jarvis.testlab.redaction",
    "jarvis.testlab.bundle", "jarvis.testlab.bundle_rules", "bisect",
}
#: Clock, entropy, filesystem, process and dynamic execution entry points.
FORBIDDEN_CALLS = {"now", "utcnow", "today", "time", "monotonic", "perf_counter", "uuid4", "token_hex", "urandom",
                   "open", "eval", "exec", "compile", "__import__", "import_module", "Popen", "system"}


@pytest.mark.parametrize("module", CONTRACT_MODULES)
def test_contract_module_is_pure(module):
    path = ROOT / "jarvis" / "testlab" / f"{module}.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            names = {node.module or ""}
        else:
            names = set()
        assert names <= ALLOWED_IMPORTS, f"{module} imports {sorted(names - ALLOWED_IMPORTS)}"
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "re":
                continue  # re.compile builds a pattern, it executes nothing
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            assert called not in FORBIDDEN_CALLS, f"{module} calls {called}"
