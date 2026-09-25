# Issue 002 — dropped transcripts are written into `trace.jsonl` verbatim

| | |
| --- | --- |
| Raised by | Slice 06 implementer, confirmed by agent 0, 2026-09-24 |
| Status | open, **not** this task's to fix — but this task raises its severity |
| Severity | low today, **high once Presentation ships** |
| Surface | `jarvis/runtime/realtime_audio.py` — two `voice.transcript_dropped` emits |
| Pre-existing | yes — present at the branch point `ddcdb71` |

## What happens

Both `voice.transcript_dropped` emits pass `text[:300]` as the journal **message**:

```python
self._trace(
    "voice.transcript_dropped",
    text[:300],
    data={"conversation_id": ..., "reason": reason, ...},
)
```

So up to 300 characters of what was actually said lands in `runtime/trace.jsonl`, which is
append-only with **no rotation** (`jarvis/runtime/journal.py:10-71`) and is already 23.9 MB on this
machine. Every filtered hallucination, every self-echo, every transcript dropped for any reason
leaves the words on disk.

## Why this task raises its severity rather than causing it

Today the dropped-transcript path runs only during an addressed conversation, and what it records
is the operator's own speech in their own session. Presentation mode changes three things at once:

- **Volume.** The room is captured continuously, so the number of dropped segments goes up by
  orders of magnitude — filler suppression alone is designed to discard most of what it hears.
- **Who is speaking.** A presentation contains an audience. The words written to disk stop being
  only the operator's.
- **The promise made around it.** Slices 04, 05 and 06 each took deliberate care that no transcript
  text and no PCM reaches a trace line: bounded values, allow-listed keys, planted-phrase tests.
  `docs/presentation-ambient-lane.md` states the guarantee for the ambient lane, and it holds
  there. One module over, the older path writes the words out in full.

The ambient lane does **not** route through this code, so the guarantee Slice 06 makes is true as
stated. The risk is that a reader takes it as a property of the system rather than of one lane.

## Why it is not fixed here

`realtime_audio.py` is the interactive voice path, shared by every voice architecture and outside
this handoff's scope. Changing what it journals is a behaviour change for Simple, Front Brain and
Duplex alike, and the message is presumably load-bearing for someone diagnosing why a transcript
was discarded. It deserves its own change with its own regression surface.

## Suggested fix, for whoever takes it

Keep the diagnosis, drop the words. The `data` payload already carries `reason`, the conversation
id and the drop classification, which is what an operator actually needs; the text itself could be
replaced by a length and a hash, or gated behind an explicit diagnostic opt-in. If the text is
genuinely needed to debug the hallucination filters, it belongs in a separate, rotated, opt-in
channel — not in the append-only journal that ships by default.

Related: [[001-settings-read-swallows-a-corrupt-file]] is the other pre-existing defect this task
surfaced without owning.
