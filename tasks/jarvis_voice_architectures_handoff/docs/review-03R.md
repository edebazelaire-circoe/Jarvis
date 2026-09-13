# Task03 regression repair — test package imports

Task03 introduced `tests/__init__.py` for canonical frontend test fakes. Six existing test modules imported shared helper classes using bare `from conftest import ...`, which no longer resolved after tests became a package. Focused Task03 tests had missed these collection failures.

Changed only the six imports to `from tests.conftest import ...` in:

- `tests/e2e/test_demo_scenario.py`
- `tests/integration/test_health.py`
- `tests/integration/test_orchestrator.py`
- `tests/integration/test_voice_runtime.py`
- `tests/unit/test_composite_state.py`
- `tests/unit/test_state.py`

These imports reference helper classes (`RecordingBoard`, `RecordingStatePublisher`, `RecordingTTS`, `ScriptedAgent`), not fixture functions. No production behavior, assertions, fixtures or fake implementation changed. Repository search found exactly these six bare conftest imports.

Validation, 2026-09-12, repository root:

```powershell
.venv/Scripts/python.exe -m pytest --collect-only -q -W error -o asyncio_default_fixture_loop_scope=function
```

Result: **1992 tests collected in1.82s**, exit0, no collection errors. Count reflects concurrent Task04 additions; this is collection evidence, not a full execution pass.

```powershell
.venv/Scripts/python.exe -m pytest tests/e2e/test_demo_scenario.py tests/integration/test_health.py tests/integration/test_orchestrator.py tests/integration/test_voice_runtime.py tests/unit/test_composite_state.py tests/unit/test_state.py -q -W error -o asyncio_default_fixture_loop_scope=function
```

Result: **42 passed in0.68s**, exit0. Repair complete; no new runtime diagnostic contract applies to test import resolution.
