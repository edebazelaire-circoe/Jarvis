# Issue 001 — a corrupt settings file reads as a first launch, silently

| | |
| --- | --- |
| Raised by | Slice 02 `runtime-validation`, 2026-09-23 |
| Status | open, **not** this task's to fix |
| Severity | high in consequence, low in likelihood |
| Surface | `jarvis/runtime/control_center.py:1389` (`ControlCenter._settings()`) |
| Pre-existing | yes — predates this handoff |

## What happens

`_settings()` reads and parses the settings file inside a bare swallow:

```python
except (OSError, json.JSONDecodeError):
    pass
```

A file that exists but does not parse therefore yields an **empty settings dict**, with no journal
line and no error anywhere. Every setting vanishes at once — `interaction_mode`, `voice_arch`,
`voice_architecture`, the credentials, all of it — and the Control Center proceeds as though the
user had never configured anything.

QA hit this by accident, not by construction: a UTF-8 **BOM** on `runtime/control-center-settings.json`
is enough. `json.loads` rejects a leading BOM. Note that `jarvis/environment.py` already reads `.env`
with `utf-8-sig` for exactly this reason, so the repo knows about the hazard in one place and not in
this one.

## Why it matters here

The resulting state is **indistinguishable from a first launch**. `GET /api/interaction-mode`
returns `stored_value: null, stored_schema_version: null, unreadable: false` — the same payload a
genuinely new install produces.

That is precisely the confusion Slice 02 was built to prevent one level down. The slice added a
tolerant read, an `interaction.mode.defaulted` line, an `unreadable` flag and a preserved
`stored_value` so that *"started in SIMPLE"* and *"its setting was corrupt"* could never look alike.
All of that apparatus sits underneath a reader that loses the whole file without a word.

A user in this state re-picks their mode, it appears to work, and the next start is empty again.

## Why it is not fixed in this task

`_settings()` is shared by every Control Center setting and predates this handoff. Changing how it
fails is a behaviour change for Bare Hands, the voice axes, shortcuts, credentials and the agent CLI
at once, and it deserves its own regression surface. Fixing it inside a Presentation-mode slice
would be scope creep with a wide blast radius.

## Suggested fix, for whoever takes it

Distinguish *absent* from *unreadable*. Keep starting — a corrupt settings file must not block
startup — but say so: one journal line at `warning` naming the parse failure, a flag the status
payload can carry, and the file left untouched on disk so nothing overwrites a recoverable
configuration. Reading with `utf-8-sig` would additionally make the BOM case simply work, matching
`jarvis/environment.py`.

Second occurrence of this hazard in this task: `tests/unit/test_third_party_bootstrap.py` carries a
BOM that `ast.parse` rejects, which Slice 01 had to handle in its import guard by reading with
`utf-8-sig`. Two BOM traps in one repository suggests a convention worth writing down rather than
two isolated fixes.
