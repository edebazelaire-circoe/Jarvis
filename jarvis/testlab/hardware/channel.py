"""The file channel a guided run talks to a human through.

Binding contract: `docs/testlab.md` ("Guided runs"). A runner executes inside a worker
process the supervisor spawned with no console attached, and the human is in front of a
terminal (Slice 10) or a browser (Slice 11) somewhere else. Something has to cross that
gap, and it is the same thing the worker protocol already crosses it with: a small
document in the run scratch, written atomically, polled by the other side.

Two files, beside `job.json`, `heartbeat.json` and `cancel.json`:

| File | Written by | Says |
|---|---|---|
| `prompt.json` | the worker | "show this to the human, they have this long" |
| `prompt-ack.json` | the presenter | "they answered, here is what they said" |

The `sequence` number is what matches the two: a stale acknowledgement left by a
previous step can never answer the current one, which is the failure a naive
"is the ack file there?" poll would produce on every second prompt.

Why files rather than a socket: the same reason `result.json` is a file. The record has
to survive either side dying. A presenter that is killed mid-prompt leaves the prompt on
disk, so the next one shows it; a worker that is killed leaves no ack to be misread.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import time
from typing import Any

from jarvis.adapters.file_replace import replace_with_retry
from jarvis.testlab._fs import write_atomic
from jarvis.testlab.hardware.prompts import GuidedPrompt, PromptReply
from jarvis.testlab.validation import fail

#: Per-run scratch names, beside the Slice 05 worker protocol files.
PROMPT_FILE_NAME = "prompt.json"
PROMPT_ACK_FILE_NAME = "prompt-ack.json"
PROMPT_TMP_PREFIX = ".prompt-"
ACK_TMP_PREFIX = ".prompt-ack-"

PROMPT_SCHEMA = "jarvis.testlab.guided_prompt"
ACK_SCHEMA = "jarvis.testlab.guided_ack"
SCHEMA_VERSION = 1

#: A prompt document is a handful of short strings; anything larger is not one of ours.
MAX_CHANNEL_BYTES = 64 * 1024
#: How often the worker looks for an acknowledgement. Fast enough that a human never
#: notices, cheap enough that a 10-minute prompt costs nothing.
POLL_INTERVAL_S = 0.1


def _write(directory: Path, name: str, prefix: str, document: dict[str, Any]) -> None:
    write_atomic(Path(directory), name, json.dumps(document, ensure_ascii=False, sort_keys=True).encode("utf-8"),
                 label=f"guided {name}", tmp_prefix=prefix, max_path_chars=None, replace=replace_with_retry)


def _read(path: Path) -> dict[str, Any] | None:
    """The document, or `None` for absent, oversized, unreadable or malformed.

    Every one of those is "no answer yet" for the worker and "nothing to show" for the
    presenter, and both sides are bounded by a deadline they cannot outlive, so a
    corrupt file delays a prompt instead of hanging a run.
    """
    try:
        if path.stat().st_size > MAX_CHANNEL_BYTES:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Intentional, argued: the file is written atomically but may be absent (the
        # normal state), and a reader that raised on a half-visible rename would turn
        # an ordinary race into a failed run. The caller's deadline is the backstop.
        return None
    return payload if isinstance(payload, dict) else None


# ------------------------------------------------------------- worker side

class FilePrompter:
    """`GuidedPrompter` for a worker: publish the prompt, wait for the matching answer.

    It enforces NO deadline of its own. `GuidedSession` owns the bound for every
    presenter alike, so a file channel and a future in-process one cannot disagree about
    how long a human had; this side simply waits until it is cancelled.
    """

    def __init__(self, scratch: Path, *, poll_interval_s: float = POLL_INTERVAL_S,
                 clock: Any = time.time) -> None:
        self._scratch = Path(scratch)
        self._poll = max(0.01, float(poll_interval_s))
        self._clock = clock
        self._sequence = 0

    @property
    def prompt_path(self) -> Path:
        return self._scratch / PROMPT_FILE_NAME

    @property
    def ack_path(self) -> Path:
        return self._scratch / PROMPT_ACK_FILE_NAME

    async def present(self, prompt: GuidedPrompt) -> PromptReply:
        self._sequence += 1
        sequence = self._sequence
        self._clear()
        _write(self._scratch, PROMPT_FILE_NAME, PROMPT_TMP_PREFIX, {
            "schema": PROMPT_SCHEMA, "schema_version": SCHEMA_VERSION, "sequence": sequence,
            "shown_at": int(self._clock() * 1000), "prompt": prompt.to_dict()})
        try:
            while True:
                reply = self._read_ack(prompt.prompt_id, sequence)
                if reply is not None:
                    return reply
                await asyncio.sleep(self._poll)
        finally:
            # Always, including on the cancellation `GuidedSession` sends when the
            # deadline passes: a prompt left on disk would be shown again by the next
            # presenter that looked, long after the run that asked for it ended.
            self._clear()

    def _read_ack(self, prompt_id: str, sequence: int) -> PromptReply | None:
        document = _read(self.ack_path)
        if document is None:
            return None
        if document.get("prompt_id") != prompt_id or document.get("sequence") != sequence:
            # A stale answer to a previous step. Ignored, not consumed: consuming it
            # would race a presenter that is writing the real one.
            return None
        note = document.get("note")
        return PromptReply(acknowledged=bool(document.get("acknowledged", True)),
                           refused=bool(document.get("refused", False)),
                           note=str(note)[:200] if isinstance(note, str) and note else None)

    def _clear(self) -> None:
        for path in (self.prompt_path, self.ack_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                # Intentional: another process may hold the file for a moment on
                # Windows. The `sequence` check makes a leftover harmless, so failing
                # the run over a file we could not delete would be the worse outcome.
                pass


# ---------------------------------------------------------- presenter side

class PromptWatcher:
    """The presenter's half: read the open prompt, answer it. Slices 10 and 11 render it.

    Deliberately not async and deliberately tiny: a CLI polls `pending()` between
    keystrokes and a UI polls it over HTTP, and neither should have to know the file
    names or the sequence rule.
    """

    def __init__(self, scratch: Path) -> None:
        self._scratch = Path(scratch)

    @property
    def scratch(self) -> Path:
        return self._scratch

    def pending(self) -> tuple[GuidedPrompt, int] | None:
        """The prompt awaiting a human, with its sequence, or `None` when there is none."""
        document = _read(self._scratch / PROMPT_FILE_NAME)
        if document is None or document.get("schema") != PROMPT_SCHEMA:
            return None
        sequence = document.get("sequence")
        if type(sequence) is not int:
            return None
        try:
            return GuidedPrompt.from_dict(document.get("prompt")), sequence
        except Exception:
            # Captured: a prompt document we cannot decode is one we must not show, and
            # the worker's deadline will end the step honestly as `timed_out`. Raising
            # here would take down the presenter instead of one prompt.
            return None

    def acknowledge(self, prompt_id: str, sequence: int, *, refused: bool = False,
                    note: str | None = None) -> None:
        """Answer the open prompt. `refused=True` is the human declining, which is allowed."""
        if not isinstance(prompt_id, str) or type(sequence) is not int:
            raise fail("acknowledge takes the prompt id and the sequence the watcher reported")
        _write(self._scratch, PROMPT_ACK_FILE_NAME, ACK_TMP_PREFIX, {
            "schema": ACK_SCHEMA, "schema_version": SCHEMA_VERSION, "sequence": sequence,
            "prompt_id": prompt_id, "acknowledged": not refused, "refused": bool(refused),
            "note": note if isinstance(note, str) and note else None})
