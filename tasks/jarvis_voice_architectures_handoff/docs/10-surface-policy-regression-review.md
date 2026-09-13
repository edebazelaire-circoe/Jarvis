# Task10 surface policy regression review

The release gate exposed a stale AST assertion in `tests/unit/test_surface_reflex_policy.py::test_the_openai_surface_is_wired_to_the_architecture`. Isolated reproduction: **1 failed in 0.87 seconds**.

The existing low-level Realtime connector parameter named `continuous_brain` controls provider turn-detection flags. Task10 intentionally passes `continuous_capture = continuous_brain or direct_conversation`: compatibility continuous mode and explicit Simple/Front Brain all require `create_response=False` and `interrupt_response=False`, so local admission, scheduling and interruption remain authoritative.

This does not select the backend or force a reflex-only prompt. The actual compatibility `continuous_brain` flag still selects its tools and backend path. Explicit modes set `conversational=True`; the facade builds their versioned conversation instructions and forwards them through `instructions_override`. Production wiring is unchanged by this repair.

The AST assertion now checks both independent arguments. Behavioral assertions strengthen the actual app factory tests for legacy and compatibility continuous mode: exact prompt rules, exact tool set and existing backend-presence checks. The real Simple/Front Brain composition test additionally checks both manual VAD flags and absence of compatibility reflex-only rules, alongside its existing direct-answer prompt, empty tools, zero backend calls and exact response item references.

Post-repair gate: **107 passed in 6.74 seconds**, warnings as errors. Run from `C:/Projects/jarvis/jarvis`:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_surface_reflex_policy.py tests/unit/test_app.py tests/unit/test_voice_architecture_config.py tests/unit/test_voice_composition.py tests/integration/test_simple_front_brain_composition.py tests/integration/test_voice_production_composition.py -q -W error --tb=short
```

This gate uses controlled transports/device buffers and establishes configuration and behavior boundaries; it does not claim live model obedience or hardware performance. Parent owns release rerun and slice status.
