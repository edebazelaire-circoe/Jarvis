# Follow-up — the brain is launched with `--chrome`

## Origin

Slice 07 QA of this task (item 7): the local brain is started as `claude … --chrome`, which may give it access to
the user's own Chrome (tabs, signed-in sessions).

## Why it matters

The Control Center already has its own page channels (Dossier, Variantes) and the brain has scoped MCP tools. Control
over the user's real browser is a broad privilege that no Slice of this task needed.

## Proposal

Find why `--chrome` is passed (launch arguments in `jarvis/runtime/claude_local.py`), decide with the Human whether it
stays, and if it does, document its scope and the consent in `docs/OPERATIONS.md`.

## Relationship to current task

Outside its scope (launch arguments of the brain, security posture). Recorded so it is not lost.
