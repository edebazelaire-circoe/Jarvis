# Slice 11 evidence — reproducible from here

Three scripts and one artefact. They lived in the session scratchpad, which is
where a harness belongs while it is being used — but three separate agents have
now needed them to check a number in the REPORT, and one QA pass concluded the
numbers were unreproducible because it looked somewhere else. So they are
committed here.

They are **not** part of the test suite and nothing imports them. Each one is
run by hand, from the repository root, with the project virtual environment.

| File | What it produced | Cited in |
| --- | --- | --- |
| `s11_relay_bench.py` | the in-process / relay-up / relay-down table: **1.96 ms / 67.98 ms / 6 029 ms** of worst-case trigger latency, and **30.5 / 71.2 / 8 032 ms** of event-loop lag | REPORT §2 |
| `s11_trace_scenario.py` | `s11_trace.jsonl` — one PRESENTATION session driven end to end through the production composition | REPORT §5 |
| `s11_trace.jsonl` | the 80-line trace itself: 77 `info`, 3 `warning`, 0 `error`, zero room speech | REPORT §5, §6 |
| `s11_mutate.py` | the four mutation rounds, 44 runs | REPORT §9 |

## Running them

```powershell
.\.venv\Scripts\python.exe tasks\jarvis-presentation-interaction-mode\slices\11-integration-rollout\evidence\s11_relay_bench.py
.\.venv\Scripts\python.exe tasks\jarvis-presentation-interaction-mode\slices\11-integration-rollout\evidence\s11_trace_scenario.py <a-temp-dir>
.\.venv\Scripts\python.exe tasks\jarvis-presentation-interaction-mode\slices\11-integration-rollout\evidence\s11_mutate.py            # every mutation
.\.venv\Scripts\python.exe tasks\jarvis-presentation-interaction-mode\slices\11-integration-rollout\evidence\s11_mutate.py M09 M31   # a subset
```

`ROOT` is hard-coded to `C:\Projects\jarvis\jarvis` in all three; change it, or
run them from a checkout at that path.

## What each one does and does not prove

- **`s11_relay_bench.py`** drives the real `AmbientIngestionLane`, the real
  `AudioCaptureHub`, the real segmenter and the real store, with a 5 ms
  heartbeat measuring how late the event loop is. The device and the
  transcription provider are fakes; the HTTP server for the relay arm is a real
  loopback `ThreadingHTTPServer`. The "Core unreachable" arm points at the
  discard port on Windows — that 8 s stall is what *this machine* does, and
  another host will differ. The **shape** transfers, the number does not.
- **`s11_trace_scenario.py`** is a scenario, not a test: it asserts little and
  prints a lot. Everything of Slices 04-11 is real, including the journal. The
  microphone, the transcription provider, the Claude process and the scene
  transport are faked at the outer boundary — so no latency here describes a
  provider, and no line here came from a real device.
- **`s11_mutate.py`** refuses to start on a red baseline, prints
  `git diff --stat` per mutation, `git add -N`s the new files first, reads and
  writes **bytes** joining anchors with each file's own EOL, restores in a
  `finally` with a byte-for-byte check, and carries `M00-CONTROL`, a cosmetic
  change that **must survive**. A run reporting the control as caught is a lying
  run and should be discarded.

One mutation in it is kept deliberately although it was wrong: see the comment
above `M32`. It moved a call two lines without crossing the early returns it was
meant to cross, changed nothing, and survived — a survivor that models no defect
is a harness fault, not a test gap, and the re-aimed version is what runs.
