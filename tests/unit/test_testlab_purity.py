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
#: Slice 04 adds the primitive vocabulary, the implementation registry, the manifest/lock codec
#: and promotion, which takes the published history as data instead of importing the catalog.
#: The replay codec (`replay.py`) and the catalog loader (`catalog.py`) are the I/O modules and
#: are deliberately absent from both lists below.
#: Slice 05 adds the worker protocol documents (`jobs.py`), which stay pure: the supervisor and
#: the worker read and write the files, the codec only describes them.
CONTRACT_MODULES = ("__init__", "validation", "identity", "profiles", "diagnostics", "scenarios", "runs", "store",
                    "retention", "redaction", "bundle", "bundle_rules", "bundle_builder", "primitives",
                    "implementations", "manifests", "promotion", "jobs")
ALLOWED_IMPORTS = {
    "__future__", "collections.abc", "dataclasses", "datetime", "enum", "hashlib", "json", "math", "re", "types",
    "typing", "jarvis.domain.conversation_events", "jarvis.domain.voice_state", "jarvis.testlab.validation",
    "jarvis.testlab.identity", "jarvis.testlab.profiles", "jarvis.testlab.diagnostics", "jarvis.testlab.runs",
    "jarvis.testlab.store", "urllib.parse", "jarvis.domain.conversation_event_store", "jarvis.testlab.redaction",
    "jarvis.testlab.bundle", "jarvis.testlab.bundle_rules", "bisect", "jarvis.testlab.scenarios",
    "jarvis.testlab.primitives", "jarvis.testlab.implementations", "jarvis.testlab.manifests",
}
#: Clock, entropy, filesystem, process and dynamic execution entry points.
FORBIDDEN_CALLS = {"now", "utcnow", "today", "time", "monotonic", "perf_counter", "uuid4", "token_hex", "urandom",
                   "open", "eval", "exec", "compile", "__import__", "import_module", "Popen", "system"}


def impurities(source: str, module: str = "module") -> list[str]:
    """Every forbidden import and forbidden call of one module source, as messages."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            names = {node.module or ""}
        else:
            names = set()
        if not names <= ALLOWED_IMPORTS:
            found.append(f"{module} imports {sorted(names - ALLOWED_IMPORTS)}")
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "re":
                continue  # re.compile builds a pattern, it executes nothing
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if called in FORBIDDEN_CALLS:
                found.append(f"{module} calls {called}")
    return found


@pytest.mark.parametrize("module", CONTRACT_MODULES)
def test_contract_module_is_pure(module):
    path = ROOT / "jarvis" / "testlab" / f"{module}.py"
    assert impurities(path.read_text(encoding="utf-8"), module) == []


@pytest.mark.parametrize("source", [
    "from jarvis.testlab.catalog import Catalog",
    "import jarvis.testlab.catalog",
    "from jarvis.testlab.replay import load_replay_fixture",
    "from pathlib import Path",
    "def read(path):\n    return open(path).read()\n",
])
def test_the_purity_check_itself_refuses_an_io_module(source):
    """The rule must still bite: a pure module reaching for the catalog, the replay codec, the
    filesystem or `open` is an impurity, not an allowed import."""
    assert impurities(source)
