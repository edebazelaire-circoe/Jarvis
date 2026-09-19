"""The `hardware:auto` and `hardware:guided` execution profiles: real devices, and a real human.

Binding contract: `docs/testlab.md` ("Hardware profiles", "Guided runs"). These are the
only Test Lab profiles that open this workstation's microphone and speaker, and
`hardware:guided` is the only one where the human is an explicit scenario actor (locked
decision 11).

Importing this package opens nothing and queries nothing: `sounddevice` is reached only
when a runner actually runs, and the safety gates that decide whether it may — the Slice
08 contention detector, the shared device lease, the capability grant and the
`JARVIS_TESTLAB_GUIDED=1` presence opt-in — all live in the supervisor, before a worker
is ever spawned.

| Module | Owns |
|---|---|
| `devices` | device selection, the format pre-flight, and the failure -> `MeasurementUnavailable` mapping |
| `prompts` | the guided vocabulary, the `GuidedPrompter` seam, the prompt evidence, the human-as-actor rules |
| `channel` | the file channel a worker addresses a human through, and the presenter half Slices 10/11 render |
| `runners` | the four registered runners and the real-device voice stack |
| `registry` | which implementation names those runners answer to |
"""
