"""Device contention: is the laptop microphone and speaker free, or does the live Jarvis hold them?

Binding contract: `docs/testlab.md` ("Device contention"). READINESS B9: the
workstation Jarvis owns the laptop microphone and speakers continuously
(`continuous_brain`), so a Test Lab run that needs an audio device must DETECT
that and refuse — never open the device, never interrupt a live conversation.

**Fail-closed.** `detect()` answers `free` only when a probe positively says so
and no probe disagrees. "No evidence" is `unknown`, and the supervisor refuses on
`unknown` exactly as it refuses on `busy`: not knowing whether the user is
talking to Jarvis is not a licence to take the microphone.

The mechanism is READ-ONLY evidence the live runtime already publishes, in the
runtime root (`jarvis/runtime/visual_signals.py`):

| File | What it says |
|---|---|
| `.voice_heartbeat` | a float `time.time()` rewritten every second while Voice runs |
| `.voice_runtime` | the live session descriptor (`runtime_state`, `session_id`, `model_id`, `ts`) |
| `.voice_state` | `idle` / `listening` / `thinking` / `speaking` |

Nothing here writes, resets or deletes any of them: the Control Center already
resets the signal bus when it observes a stale heartbeat
(`control_center.py`), and a second resetter would race it.

Limits, stated plainly because a safety gate that oversells itself is worse than
none (see `docs/testlab.md` for the same table):

- **False "busy"** — a Voice process that is alive but whose device failed to
  open still beats, and we refuse. Refusing a run we could have made is the safe
  direction, so this is deliberate.
- **"We could not look" is never "free".** An ABSENT signal file is evidence (the
  live runtime never wrote it); one that is oversized, locked, a directory, or
  unreadable for any other reason is the ABSENCE of evidence and reads `unknown`,
  which refuses the run. The two used to collapse into one `None`, which was a
  fail-open hole in a fail-closed detector. A runtime directory that does not
  exist at all is a configuration error and also reads `unknown`.
- **False "free"** — a Voice process that holds the device while its heartbeat
  loop is wedged (the loop and the audio callback are different threads) looks
  free after 5 s. So does a Jarvis writing to a DIFFERENT runtime root than the
  one this detector was given. Neither can be closed without a change to the
  live runtime, which this Slice may not make.
- **Jarvis starting mid-run** — nothing here can stop it. The supervisor
  re-probes on every poll while a device capability is reserved and ends the run
  `device_contention_during_run` (inconclusive) as soon as a heartbeat appears,
  which bounds the damage to at most one poll interval of overlap. Making it
  impossible needs the live runtime to take a lock it does not take today.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
import json
import os
from pathlib import Path
import time
from typing import Any, Protocol

from jarvis.testlab.profiles import Capability
from jarvis.testlab.validation import TestLabError, check_text, fail

#: Names the live runtime publishes in its runtime root. Read-only here.
VOICE_HEARTBEAT_FILE = ".voice_heartbeat"
VOICE_RUNTIME_FILE = ".voice_runtime"
VOICE_STATE_FILE = ".voice_state"

#: Same rule as `control_center.VOICE_HEARTBEAT_MAX_AGE_S`: the loop beats every
#: second, so five seconds of silence means the Voice process is gone. Duplicated
#: rather than imported because `jarvis.testlab` must not import the Control
#: Center (a 5 000-line aiohttp module) to answer a filesystem question; the two
#: values are pinned equal by a test.
HEARTBEAT_MAX_AGE_S = 5.0

#: How old `.voice_state` may be and still be believed. A state file is written on
#: transitions only, so it says nothing once the process is gone.
STATE_MAX_AGE_S = 60.0

MAX_EVIDENCE_DETAIL_CHARS = 200
#: A voice signal file is a handful of scalars; anything larger is not one of ours.
MAX_SIGNAL_BYTES = 64 * 1024

CONTENTION_REFUSED = "testlab_device_contention"


class ContentionState(StrEnum):
    """What one probe, or the whole detector, concluded."""

    #: Positive evidence that nothing holds the device.
    FREE = "free"
    #: Positive evidence that something does.
    BUSY = "busy"
    #: No usable evidence either way. Treated as `busy` by every gate.
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ContentionEvidence:
    """One probe's answer: what it looked at, what it concluded, and why in one line."""

    source: str
    state: ContentionState
    #: Bounded English sentence. Never a path, a user name or a conversation id.
    detail: str

    def __post_init__(self) -> None:
        check_text(self.source, "evidence.source", max_chars=64)
        if not isinstance(self.state, ContentionState):
            raise fail("evidence.state must be a ContentionState")
        check_text(self.detail, "evidence.detail", max_chars=MAX_EVIDENCE_DETAIL_CHARS)

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "state": self.state.value, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class ContentionReport:
    """The combined answer the supervisor gates on."""

    state: ContentionState
    #: Who is believed to hold the device, when we can name it. Never a pid or a path.
    holder: str | None
    evidence: tuple[ContentionEvidence, ...]

    @property
    def available(self) -> bool:
        """True only for `free`: `unknown` never authorizes taking a device."""
        return self.state is ContentionState.FREE

    def reason(self) -> str:
        """One actionable line for a refusal detail."""
        blocking = [item for item in self.evidence if item.state is not ContentionState.FREE]
        if not blocking:
            return "the audio devices are free"
        held = "held" if self.state is ContentionState.BUSY else "of unknown availability"
        who = f" by {self.holder}" if self.holder else ""
        return f"the audio devices are {held}{who}: " + "; ".join(item.detail for item in blocking)

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state.value, "holder": self.holder,
                "evidence": [item.to_dict() for item in self.evidence]}


class ContentionProbe(Protocol):
    """One source of evidence. Must never raise and never open a device."""

    #: Short stable name, used in the evidence and in diagnostics.
    source: str

    def probe(self) -> ContentionEvidence:
        ...


#: "The file is not there." Positive evidence: the live runtime never wrote it.
ABSENT = type("_Absent", (), {"__repr__": lambda self: "ABSENT"})()
#: "The file is there and we could not read it" — locked, a directory, permission
#: denied, or larger than a signal file has any business being. NO evidence, which
#: is a different fact from absence and must never be read as "free".
UNREADABLE = type("_Unreadable", (), {"__repr__": lambda self: "UNREADABLE"})()


def _read_signal(path: Path) -> str | object:
    """The text of a small signal file, `ABSENT`, or `UNREADABLE`.

    The three cases are kept apart on purpose. Collapsing them was a fail-OPEN hole
    in a fail-closed detector: an oversized or locked `.voice_heartbeat` read exactly
    like one that had never been written, so a Jarvis we simply could not observe
    reported the microphone free.
    """
    try:
        if path.stat().st_size > MAX_SIGNAL_BYTES:
            return UNREADABLE
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ABSENT
    except OSError:
        # Captured deliberately: a locked file, a directory in the file's place or a
        # permission denial is an ordinary observation of a directory another process
        # owns — and it is exactly "no evidence", which the caller turns into `unknown`.
        return UNREADABLE


def _read_json_object(path: Path) -> dict[str, Any] | None:
    text = _read_signal(path)
    if not isinstance(text, str):
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


class LiveVoiceRuntimeProbe:
    """Reads the signals the live Jarvis Voice process publishes in its runtime root.

    This is the whole B9 mechanism. It is evidence, not a lock: see the module
    docstring for what it cannot see.
    """

    source = "live_voice_runtime"

    def __init__(self, runtime_root: Path, *, clock: Callable[[], float] = time.time,
                 heartbeat_max_age_s: float = HEARTBEAT_MAX_AGE_S,
                 state_max_age_s: float = STATE_MAX_AGE_S) -> None:
        self._root = Path(runtime_root)
        self._clock = clock
        self._heartbeat_max_age_s = float(heartbeat_max_age_s)
        self._state_max_age_s = float(state_max_age_s)

    @property
    def runtime_root(self) -> Path:
        return self._root

    def probe(self) -> ContentionEvidence:
        """`busy`, `free` or `unknown`. Every "we could not look" answer is `unknown`.

        Order: anything that positively says BUSY wins; then anything that says we
        could not look says UNKNOWN; only a directory we read completely, with no live
        signal in it, says FREE.
        """
        if not self._root.is_dir():
            # A configuration error, not an observation: nobody has told us where the
            # live runtime writes, so we know nothing about the devices.
            return self._evidence(ContentionState.UNKNOWN,
                                  "the live runtime directory this detector was given does not exist")
        beat = self._heartbeat_age()
        if isinstance(beat, float) and beat <= self._heartbeat_max_age_s:
            return self._evidence(ContentionState.BUSY,
                                  f"the Jarvis voice runtime beat {beat:.1f} s ago{self._session_suffix()}")
        state = self._active_state()
        if isinstance(state, str):
            return self._evidence(ContentionState.BUSY,
                                  f"the voice state file says '{state}' and is recent, so a session is in progress")
        if beat is UNREADABLE:
            return self._evidence(ContentionState.UNKNOWN,
                                  "the voice heartbeat file could not be read (locked, oversized, or not a file)")
        if beat is _NOT_A_TIMESTAMP:
            return self._evidence(ContentionState.UNKNOWN,
                                  "the voice heartbeat file exists but could not be read as a timestamp")
        if state is UNREADABLE:
            return self._evidence(ContentionState.UNKNOWN,
                                  "the voice state file could not be read (locked, oversized, or not a file)")
        if beat is ABSENT:
            return self._evidence(ContentionState.FREE,
                                  "no voice heartbeat has ever been written in this runtime directory")
        return self._evidence(ContentionState.FREE,
                              f"the last voice heartbeat is {beat:.0f} s old, well past the {self._heartbeat_max_age_s:.0f} s liveness window")

    # ----------------------------------------------------------------- signals

    def _heartbeat_age(self) -> float | object:
        """Seconds since the last beat, or `ABSENT` / `UNREADABLE` / `_NOT_A_TIMESTAMP`."""
        text = _read_signal(self._root / VOICE_HEARTBEAT_FILE)
        if not isinstance(text, str):
            return text
        try:
            beat = float(text.strip())
        except ValueError:
            return _NOT_A_TIMESTAMP
        return max(0.0, self._clock() - beat)

    def _active_state(self) -> str | object:
        """The published state when it is non-idle AND recent, else `ABSENT` / `UNREADABLE`."""
        path = self._root / VOICE_STATE_FILE
        text = _read_signal(path)
        if not isinstance(text, str):
            return text
        value = text.strip().lower()
        if not value or value == "idle":
            return ABSENT
        try:
            age = self._clock() - path.stat().st_mtime
        except OSError:
            return UNREADABLE
        if age > self._state_max_age_s:
            return ABSENT
        return value if value.isalpha() else ABSENT

    def _session_suffix(self) -> str:
        """`.voice_runtime` names the architecture and lifecycle state; never the conversation."""
        report = _read_json_object(self._root / VOICE_RUNTIME_FILE)
        if report is None:
            return ""
        parts = [str(report[name])[:32] for name in ("architecture", "runtime_state") if isinstance(report.get(name), str)]
        return f" ({', '.join(parts)})" if parts else ""

    def _evidence(self, state: ContentionState, detail: str) -> ContentionEvidence:
        return ContentionEvidence(self.source, state, detail[:MAX_EVIDENCE_DETAIL_CHARS])


#: Sentinel for "the heartbeat file is there and readable, but its content is not a
#: timestamp". Distinct from `UNREADABLE` only so the refusal says which it was.
_NOT_A_TIMESTAMP = type("_NotATimestamp", (), {"__repr__": lambda self: "NOT_A_TIMESTAMP"})()


class DeviceContentionDetector:
    """Combines probes fail-closed: one `busy` decides, and only unanimous `free` frees."""

    #: What a probe that raises is worth. A detector whose probe is broken knows nothing.
    PROBE_FAILED_DETAIL = "the probe raised and could not answer"

    def __init__(self, probes: Sequence[ContentionProbe], *, holder: str = "the Jarvis voice runtime") -> None:
        if not probes:
            raise fail("a device contention detector needs at least one probe")
        self._probes = tuple(probes)
        self._holder = holder

    @property
    def probes(self) -> tuple[ContentionProbe, ...]:
        return self._probes

    def detect(self) -> ContentionReport:
        """Ask every probe (blocking file I/O) and combine. Never raises."""
        evidence: list[ContentionEvidence] = []
        for probe in self._probes:
            try:
                item = probe.probe()
            except Exception as exc:
                # Captured: a probe that breaks must make the detector MORE careful,
                # never less. `unknown` refuses the run and names the probe.
                item = ContentionEvidence(getattr(probe, "source", "probe")[:64], ContentionState.UNKNOWN,
                                          f"{self.PROBE_FAILED_DETAIL} ({type(exc).__name__})")
            evidence.append(item)
        states = {item.state for item in evidence}
        if ContentionState.BUSY in states:
            state = ContentionState.BUSY
        elif ContentionState.UNKNOWN in states:
            state = ContentionState.UNKNOWN
        else:
            state = ContentionState.FREE
        holder = self._holder if state is ContentionState.BUSY else None
        return ContentionReport(state, holder, tuple(evidence))


def default_contention_detector(runtime_root: Path | str, **options: Any) -> DeviceContentionDetector:
    """The detector a supervisor builds for the workstation's LIVE runtime root.

    `runtime_root` must be the real one (`runtime/`), never the per-run scratch:
    the question is what the live Jarvis is doing, and the scratch is by
    construction empty of its signals.
    """
    return DeviceContentionDetector((LiveVoiceRuntimeProbe(Path(runtime_root), **options),))


def needs_device(capabilities: Iterable[Capability]) -> bool:
    """Does this set of capabilities take a physical audio device?"""
    return any(item in _DEVICE_CAPABILITIES for item in capabilities)


_DEVICE_CAPABILITIES = frozenset({Capability.AUDIO_INPUT_DEVICE, Capability.AUDIO_OUTPUT_DEVICE})


# ------------------------------------------------------------- device lease

class DeviceLeaseBusy(TestLabError):
    """Another Test Lab supervisor holds the shared device lease."""


class DeviceLease:
    """An exclusive OS lock file shared by every Test Lab supervisor that may take a device.

    Reservation already serializes device runs INSIDE one supervisor, and one
    supervisor owns one work root. This closes the remaining Test Lab case: two
    supervisors on two work roots (two worktrees of this repository) reaching for
    the one laptop microphone. Point both at the same `path` and the second waits.

    It is NOT protection against the live Jarvis or the Control Center audio test:
    neither takes this lock, and teaching them to is a change to the live runtime
    that Slice 08 may not make. Detection, not this lease, is what keeps a Test
    Lab run off a live conversation.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._fd: int | None = None

    @property
    def path(self) -> Path:
        return self._path

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> None:
        """Take the lease, or raise `DeviceLeaseBusy`. Blocking file I/O; never waits."""
        from jarvis.testlab._fs import lock_fd  # local: `_fs` imports the store contract

        if self._fd is not None:
            raise fail("the device lease is already held by this supervisor")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            lock_fd(fd)
        except OSError as exc:
            os.close(fd)
            raise DeviceLeaseBusy(CONTENTION_REFUSED,
                                  "another Test Lab supervisor holds the audio device lease") from exc
        self._fd = fd

    def release(self) -> None:
        """Free the lease. Safe to call when it is not held (the OS frees it on death anyway)."""
        from jarvis.testlab._fs import unlock_fd

        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            unlock_fd(fd)
        except OSError:
            # Intentional: the handle is closed immediately below, and closing a
            # handle releases the lock on both platforms. Reporting a failure to
            # unlock a descriptor we are about to drop would be noise.
            pass
        finally:
            os.close(fd)
