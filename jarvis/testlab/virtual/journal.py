"""The journal of a `virtual` run: the live runtime's `trace.jsonl`, plus a measurable timeline.

Binding contract: `docs/testlab.md` ("Virtual profile"). The voice stack writes its
observability through a duck-typed `emit(kind, message, level=, data=)` sink. In a test
that sink is the in-memory `RecordingJournal`; in a Test Lab run it must ALSO be the
real `RuntimeJournal`, so that:

- a `DiagnosticBundle` captured over the run reads exactly the evidence it reads from a
  live session (Slice 03 carried this requirement to Slice 06), and
- the run stores a `trace.jsonl` artifact a human or an agent can read afterwards.

`timeline` is what the runners measure on: the same lines, each stamped once, with a
monotonic reading next to the wall time so two lines of the same millisecond still have
an order and a duration. `RecordingJournal.events` is deliberately left untouched: the
existing harness tests read it, and a new key there would change what they observe.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any

from jarvis.runtime.journal import RuntimeJournal
from jarvis.testlab.virtual.harness import RecordingJournal


@dataclass(frozen=True, slots=True)
class TraceLine:
    """One journal line, with the two clocks a measurement needs."""

    kind: str
    level: str
    message: str
    data: Mapping[str, Any]
    at: datetime
    #: `time.perf_counter()` at emission: durations come from this, never from wall time.
    monotonic: float

    def get(self, name: str, default: Any = None) -> Any:
        value = self.data.get(name, default)
        return default if value is None else value


class TraceRecordingJournal(RecordingJournal):
    """A `RecordingJournal` that also appends to `<runtime_dir>/trace.jsonl`.

    A failed write is counted, never raised: losing a line of evidence must not end a
    run that is otherwise measuring correctly. `write_failures` is non-zero exactly when
    the stored trace is incomplete, and the runner reports it in the worker log so the
    gap is visible rather than inferred from a short file.
    """

    def __init__(self, runtime_dir: Path | str) -> None:
        super().__init__()
        self.runtime_dir = Path(runtime_dir)
        self.timeline: list[TraceLine] = []
        self.write_failures = 0
        self.last_write_error: str | None = None
        self._journal = RuntimeJournal(self.runtime_dir)

    @property
    def trace_path(self) -> Path:
        return self._journal.trace_path

    def emit(self, kind: str, message: str, *, level: str = "info", data=None) -> None:  # noqa: ANN001
        payload = dict(data or {})
        super().emit(kind, message, level=level, data=payload)
        self.timeline.append(TraceLine(kind=str(kind), level=str(level), message=str(message), data=payload,
                                       at=datetime.now(timezone.utc), monotonic=time.perf_counter()))
        try:
            self._journal.emit(kind, message, level=level, data=payload)
        except (OSError, TypeError, ValueError) as exc:
            # Captured, not swallowed: the count and the first cause are reported by the
            # runner, so an incomplete trace artifact is never mistaken for a quiet run.
            self.write_failures += 1
            if self.last_write_error is None:
                self.last_write_error = type(exc).__name__

    # -- lecture des mesures -------------------------------------------------

    def lines(self, *kinds: str) -> list[TraceLine]:
        wanted = frozenset(kinds)
        return [line for line in self.timeline if line.kind in wanted]

    def counts(self, *kinds: str) -> int:
        return len(self.lines(*kinds))

    def first(self, *kinds: str) -> TraceLine | None:
        for line in self.timeline:
            if line.kind in kinds:
                return line
        return None


def merged_timeline(*journals: TraceRecordingJournal) -> list[TraceLine]:
    """Every journal's lines in emission order (the monotonic reading is the key)."""
    return sorted((line for journal in journals for line in journal.timeline), key=lambda line: line.monotonic)
