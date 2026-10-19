# Follow-up — a canonical Voice lifecycle API (Veille / Réveil)

## Origin

Slice 04 QA of this task: the JARVIS wheel category is status-only. No Core or Control Center route puts Voice to
sleep or wakes it (only the wake-word settings exist), so no Veille / Réveil / Pause row was added: a row without a
canonical owner would fake a control (D19).

## Product idea

1. A canonical Voice lifecycle route owned by Core (states, refusals, journal), followed by Voice.
2. Then a JARVIS submenu row « Mettre en veille » / « Réveiller » driven by that route, with the same honesty rules
   as the other JARVIS rows (unknown state said, nothing optimistic).

## Relationship to current task

Outside its scope: a new runtime capability, not a UI refactor.

## Future questions

- interaction with the wake key (F9), PRESENTATION's microphone ownership and Bare Hands' own Veille;
- what « veille » means for a running brain turn and for background work.
