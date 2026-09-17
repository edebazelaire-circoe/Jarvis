"""The echo guard of the `virtual` profile: acoustic STATE, never an acoustic decision.

Binding contract: `docs/testlab.md` ("Virtual profile"). `SoundDeviceRealtimeAudio`
exposes the guard the duplex capture holds (`jarvis/audio/duplex.py`): while Jarvis's own
output is the far end, the provider does not receive the microphone, so a provider
`speech_started` in that window can only be echo. The bridge reads that state
(`has_echo_guard`, `echo_guard_open`, `far_end_recent`) and decides — `voice.barge_in` or
`voice.barge_in_ignored` / `speech_started_behind_echo_guard`.

Without a capture, `_barge_in_allowed()` has no witness and believes the provider: a
harness with no guard therefore confirms EVERY echo candidate, and `voice.self_echo`
could not distinguish a correct stack from a broken one. This double supplies the missing
witness and nothing else:

- it is fed by the production writer (`push_reference` per output block, `clear_reference`
  on an output stop), so "Jarvis is the far end" is observed, not declared;
- it never decides a barge-in, never cancels, never touches an output;
- `speak_over()` is how a scenario or a test states that a real near-end voice was
  separated from the echo — the case a real acoustic canceller detects.

**No clock.** An earlier version closed the gate only for 2 s of `time.monotonic` after
the last output block, which made the guard the one part of the profile that depended on
wall time: a 2.2 s stall of a loaded host between the last block and the candidate
reopened the gate and turned a correct stack into a `voice.self_echo` failure. The far end
is now pure state — on from the first reference block, off on `clear_reference()` — so a
host pause cannot change a verdict. Nothing is lost by dropping the window: the bridge
only consults the guard `if self.continuous and self._output_live()`, so "is an output
live" is already its own precondition, and `far_end_recent` outside a live output only
makes input admission more conservative, which is the safe direction for an echo
diagnostic.

What this cannot prove is the acoustics themselves: whether a real room, a real speaker
and a real AEC actually close that gate is the `audio` and `hardware` profiles' business.
"""

from __future__ import annotations


class VirtualEchoGuard:
    """Duplex-capture double: the microphone passes through, the guard state is real."""

    __slots__ = ("_far_end", "_near_end", "_released", "_blocks", "_processed")

    #: `_report_capture` reads these by attribute; no echo canceller runs in a virtual run,
    #: so the Control Center view of a virtual run says exactly that.
    canceller = None
    canceller_failed = False
    observer = None

    def __init__(self) -> None:
        self._far_end = False
        self._near_end = False
        self._released = 0
        self._blocks = 0
        self._processed = 0

    # -- what the audio device calls ----------------------------------------

    def process(self, raw: bytes) -> tuple[bytes, tuple[str, ...]]:
        """No processing: the virtual profile injects no acoustics, so the block passes through."""
        self._processed += len(raw)
        return raw, ()

    def push_reference(self, block: bytes) -> None:
        """One output block reached the device: Jarvis is the far end from now on."""
        del block
        self._blocks += 1
        self._far_end = True

    def clear_reference(self) -> None:
        """The output was stopped: the far end ends with it."""
        self._far_end = False

    def release_near_end(self) -> None:
        """The bridge closed an unconfirmed candidate; the guard learns it was echo."""
        self._released += 1
        self._near_end = False

    def reset(self) -> None:
        self._far_end = False
        self._near_end = False

    def close(self) -> None:
        self.reset()

    # -- what the bridge reads ----------------------------------------------

    @property
    def far_recent(self) -> bool:
        """Is Jarvis's own audio the far end? True from the first written block."""
        return self._far_end

    @property
    def gate_open(self) -> bool:
        """Does the provider hear the microphone? Not while Jarvis is the far end."""
        return self._near_end or not self._far_end

    @property
    def near_end_observed(self) -> bool:
        return self._near_end

    # -- what a scenario or a test states -----------------------------------

    def speak_over(self) -> None:
        """A real near-end voice was separated from the echo: the gate opens."""
        self._near_end = True

    @property
    def released_candidates(self) -> int:
        return self._released

    @property
    def reference_blocks(self) -> int:
        return self._blocks
