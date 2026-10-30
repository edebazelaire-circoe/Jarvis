# Shard 06 Duplex startup assertion: exact baseline evidence

Root canonical shard 06 at `97d56f1144cb721e7c5303f43ff71d291ed1d9bc`:
**1,374 passed, 1 failed, 22 skipped**, exit 1, green false. The sole unknown is
`tests/unit/test_presentation_turn_authority.py::test_duplex_architecture_refuses_presentation_visibly_once`.

The actual gate failure is line 701, waiting for
`core.listening == 1 and core.snapshot_reads == 1`, followed by the three-second
helper timeout at `test_interaction_mode_follower.py:185` with
`AssertionError: condition jamais atteinte`. It happens before publishing the
presentation-mode change and before the unsupported-architecture refusal
assertions. This failed run does not itself establish a broken Duplex refusal.

## Bounded mock-only baseline reproduction

Before execution, adapters were checked: FakeCore's event bus is a collection
of asyncio queues, IdleWake waits on an unset asyncio Event, journal/signals are
in-memory doubles, and test build/session factories raise before constructing
any microphone hub or provider session. There is no browser, hardware, model or
real network dependency in the selected case.

Under explicit PM permission, only this test was run in detached
`C:/Projects/jarvis/movb` at verified exact baseline
`c0858a8000e2ca23b57231edb8f46c643080ad07`, using the main interpreter:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe -m pytest --assert=plain --tb=short -p no:cacheprovider -q tests/unit/test_presentation_turn_authority.py::test_duplex_architecture_refuses_presentation_visibly_once --junitxml=C:/Projects/jarvis/mov5/tasks/jarvis-mouse-organization-viewer/slices/06-final-integration-e2e-qa/qa/baseline-shard-06-duplex.xml
```

Actual result: **1 failed in 10.89 s**, exit 1. Same line 701 → helper line 185,
same condition and message. JUnit has one test, one failure, zero errors/skips.
Evidence: [stdout](baseline-shard-06-duplex.log),
[JUnit](baseline-shard-06-duplex.xml).

## Source identity and limits

The selected test, `test_interaction_mode_follower.py`, runtime `voice_v2.py`,
`presentation_runtime.py`, `interaction_mode_observer.py`, `completion_watch.py`
and domain `voice_architecture.py` are byte-identical between baseline and root.
Representative SHA-256:

| File | SHA-256 at both revisions |
| --- | --- |
| selected test module | `d38c96350afd7a47ae1004ab2ebbae1c6053062b67a88831babf3dd949bf1e30` |
| follower test/doubles | `2f234f51221bcad4a29c479e3a5c805391c67ed05b05369aea31ed7a58df78a2` |
| voice_v2.py | `561d1f62975b2fc7a2fcbc9faeaf9bae8c36eccf1b6a3e881056a8a36ce0e8d0` |
| interaction_mode_observer.py | `d19a869441c925207d84e01136b31940e06a110d09eb6a9823cde52a2b710191` |

Source inspection shows runtime startup schedules both a mode follower and a
completion watcher using the mock Core event API. **Actual listener/snapshot
counter values were not recorded by this test**, so no listener count or
specific internal root cause is claimed. No broader baseline file, repeat,
instrumented run or product change was performed.

PM accepted this observed failure as proven pre-existing and unrelated after
the exact baseline result. The initial canonical shard remains truthfully red;
no known-failure ignore or product file was changed. Other queued browser
unknowns retain their own pending status.
