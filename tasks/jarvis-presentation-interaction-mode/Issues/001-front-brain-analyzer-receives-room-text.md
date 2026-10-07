# Issue 001: the FRONT_BRAIN analyzer receives room text in PRESENTATION

Found by Slice 04 critical QA (F6), 2026-10-05. Not a defect of this task; outside its authority scope.

On FRONT_BRAIN, every room segment that is not near playback receives `analysis.allow_item` on `speech_started`. With `speculative_deltas=True` (the default), the room text goes to the Luna analyzer. The analyzer speaks nothing and traces no text, so this is not an authority breach (HD3 holds). It is still privacy and cost exposure: one more cloud consumer of room speech while PRESENTATION is active.

Suggested direction: when a PRESENTATION session is live, gate `analysis.allow_item` with the same authority predicate as Slice 04 (window or vocative).
