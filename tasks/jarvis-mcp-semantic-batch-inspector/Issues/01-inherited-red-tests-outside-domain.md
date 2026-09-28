# Inherited red tests outside this task's domain

Measured at `origin/main` @ `ddcdb71`, before any change of this task (see `slices/00-project-manager/READINESS.md` §4). Not caused by this task; not fixed by it.

| File | Failing | Probable cause |
| --- | -: | --- |
| `tests/unit/test_barehands_interaction_js.py` | 2 | practice-frame move/resize geometry expectations (`[-12,-12,64,40]` vs `[-17,-14,64,40]`) |
| `tests/unit/test_barehands_tutorial_retired_js.py` | 1 | Bare Hands brain prompt text changed (« l'interrupteur est à lui ») |
| `tests/unit/test_brain_delegation.py` | 1 | voice-agent system prompt changed |
| `tests/integration/test_testlab_audio_runners.py` | 2 | real near-end voice / chain record |
| `tests/integration/test_testlab_hardware_runners.py` | 1 | real barge-in |
| `tests/integration/test_testlab_live_runners.py` | 1 | live provider latency |

# Minor: unstable idempotency key in `drive_update`

`jarvis/runtime/drive_mcp.py:100` derives the idempotency key from Python `hash(content)`, which is salted per process, so the same update retried from another process gets a different key.
