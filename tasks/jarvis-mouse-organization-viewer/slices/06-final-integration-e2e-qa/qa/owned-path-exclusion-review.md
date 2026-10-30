# Independent review of positive-control domain path evidence

Read root's `owned_read_path_plugin.py`, controlled JSON and2.08s passing log
once, without another execution. The earlier empty preliminary capture remains
separate and is not used as positive evidence. No product edit by this review.

The hook wraps only the exact owned_read call phase, installs a global call
trace and restores the previous trace in finally. The positive control matches
the exact test coroutine and records12595 total calls,34 test resume calls,
21 test line events,34 return events and5 exception events. Non-domain frames
return None for local line tracing; this does not disable global function-call
tracing. The target domain files would return the line tracer when entered.
Thus empty domain line/command sets are meaningful for this observed call
phase, rather than merely a trace that never reached the async test.

Scope matters: sys.settrace covers this thread and the test call phase,
including main-loop asyncio tasks. It does not claim fixture setup, original
failing-run coverage or worker-thread coverage. SQLite scene deserialization
can execute unchanged snapshot/object validators in its I/O thread. Changed
SceneCommand validation and scene reducer dispatch are reached through the
unchanged main-loop SceneService.apply; none were observed during this passing
shutdown/assertion phase. Do not generalize that to an absent scene subsystem.

Combined evidence now consists of exhaustive MOV Python scope (only scene.py,
scene_batch.py and absent ControlCenter HTML injection), byte-identical Core/
OwnedJob/BackBrain/SQLite/projector/test machinery, source-reviewed additive
default-None setup semantics, and positively controlled absence of changed
domain execution during the exact observed test call. Isolated/pair/whole-file
baseline passes and current passes remain non-reproduction evidence, not a
fabricated baseline red.

This supports a **scoped MOV-irrelevance disposition** by PM for the existing
shutdown behavior, while retaining the original failed gate case unchanged.
It does not prove the natural timing root cause, reproduce a baseline failure,
show all-thread absence or turn the original gate into all-pass. The unchanged
internal stop bound can return early unknown; its original actual health/
owner timing was not recorded. Any statement about that cause must remain
conditional. No further runtime repetition or broad Core hardening is
recommended by this independent review.
