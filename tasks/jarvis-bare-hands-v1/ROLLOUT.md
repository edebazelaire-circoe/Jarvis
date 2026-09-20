# Bare Hands V1 — rollout, scope narrowings and what is still unvalidated

Written by Slice 11, the last Slice of this task. Its job is that a reader six
months from now sees **decisions**, not omissions: every place where V1 is
narrower than the handoff imagined is recorded here with the argument that
narrowed it. Something absent and argued is a decision; something absent and
unexplained reads as a bug, and gets "fixed" by someone who does not know why it
was not there.

## Status in one paragraph

Thirteen Slices (00-12) are implemented. Slices 01-09 and 12 were reworked after
QA. The automated evidence is broad and real: contracts, engines, target
resolution, interaction, tools and settings, calibration, tutorial, diagnostic
recording and replay, and the brain command channel all have tests that run the
served files, plus server-side tests for every route and schema.

**The real-camera validation was waived by the Human for this run. Waived is not
passed.** No statement anywhere in this repository about how Bare Hands behaves
in front of a real hand has been verified by observation — there is no webcam
and no browser in the environment where it was built. The procedure a human must
run is `docs/OPERATIONS.md` › *Procédure de test manuel (caméra réelle)*, in
seven batches A1-A7.

## Scope narrowings — deliberate, with their reasons

### 1. `highlighter` and `draw` are out of V1 (Human decision)

Two of five declared tools had **no engine**. Only Slice 07 ever named them; it
shipped and declined them, and no later Slice contracted them. They were drawn
in the palette, disarmed, with their reason in a tooltip, and the server refused
them (`barehands_tool_not_installed`).

The Human wrote them out: removed from the tool table, the contract, the palette
and the acceptance criteria. **Nothing on screen may imply a capability that
does not exist** — a disarmed control reads as a bug, not as a promise. The
palette now offers exactly what works: `pointer`, `pan`, `select`. An annotation
layer can be designed properly later, for itself.

`INSTALLED_TOOLS` stays a **separate table** from `TOOLS` even though the two
now coincide. That separation is what makes "installed" checkable: a tool
declared tomorrow without an engine is refused rather than accepted with no
effect.

### 2. "Reset profile" shipped as a settings reset

The handoff spoke of resetting the profile. What ships resets the nine
**settings** to factory values and leaves the stored calibration alone.

The two erasures do not forgive alike: a setting is redone in three clicks, a
calibration costs the user a minute of held poses. The profile has its own
`clear`, which removes the block rather than filling it with nulls, and the
engine then returns to its defaults (decision 31). Also deliberate: reset does
**not** touch the switch, so it can never turn the camera off.

### 3. Slice 10 records no landmarks at all

Argued from decision 32, in three separate places — the trace schema, the page
module's load-time whitelist (`assertDerivedOnly`), and the server's own reader
(`jarvis/runtime/barehands_trace.py`). A trace may carry numbers,
closed-vocabulary names and booleans. Not a point, not an image, not free text.

This is a narrowing with a cost, and the cost is real: a defect that only
reproduces from actual hand geometry cannot be replayed from a trace. It was
accepted because the alternative — a diagnostic file that quietly contains
biometric hand geometry — is the kind of thing nobody remembers enabling. The
guard is written as a **whitelist**, so a key added tomorrow is excluded by
default rather than included by default.

### 4. `reachNorm` is measured but not applied

Calibration measures the reachable box in image coordinates and persists it;
the settings tab displays it. **No engine reads it.** The pointer mapping still
spans the full frame.

Deferred rather than half-done: applying it means deciding what happens to the
screen area a user cannot reach, and that is a product question (clamp? scale?
scale per hand? what about two hands with different reaches?) which nobody
answered. A measured-but-unapplied number is honest; a mapping quietly derived
from an unvalidated measurement is not.

### 5. No grid sweep in `jarvis/testlab/sweeps.py`

The Test Lab's sweep machinery exists and is generic, but **no Bare Hands sweep
is registered**. Slice 10 shipped its own comparison bench instead
(`compare()` over a recorded trace, replaying with the real engines).

The reason is that a sweep is only worth its cost when the axis values come from
measurements, and the measurements come from camera sessions that have not
happened. Registering a sweep now would produce a grid over numbers nobody has
confirmed matter.

### 6. There is no raw-video path at all

Not disabled, not opt-in, not gated — **absent**. Frames are consumed inside the
page and the only thing that leaves the tracker is a neutral `HandFrame` of
scalars. Recorded in `docs/SECURITY.md` § 14.

### 7. No DOM harness for `installJarvisScene`

`data-representation` and the scene node's zones are verified **by reading the
source**, not by exercising a DOM. A compact window that lost its zones would be
invisible to every automated test. This is why A4.2 exists in the camera
procedure, and it is the largest single hole in the automated evidence.

## Things that are true and now guarded

Closed by this Slice, because a guard nobody tests is a wish:

- `wakeGapMin < wakeGapMax` — was the named example of an unguarded invariant;
  verified closed during Slice 08's rework (an inverted, equal, zero, negative
  and `NaN` pair are each pushed through three entry points).
- Seven further construction/load refusals had no test at all. All seven now do.
  Full census: **51 construction or load-time refusals, 51 guarded.**
- The clean-room boundary's three prose statements had no grep test; a refactor
  could have deleted all three silently. `tests/unit/test_barehands_clean_room.py`
  now holds the four mechanically checkable facts.

## The clean-room boundary, re-verified at close-out

Checked four ways on this branch, all intact:

1. `git ls-files third_party/` returns exactly `LOCK.json` and `README.md` —
   nothing of the upstream board is versioned.
2. `git diff --name-only main...HEAD` touches neither `third_party/` nor
   `scripts/`: this whole task changed nothing about how upstream is fetched.
3. A repository-wide grep for `FileResponse|web.static|StaticFiles|send_file`
   under `jarvis/` returns **exactly one hit** — the Bare Hands asset handler,
   which serves a closed whitelist of six exact names. There is no second, more
   permissive way to serve a file.
4. Every "AGPL" mention under `jarvis/` is one of the three clean-room
   disclaimers. They are declarations of **non-reuse**, never attributions.

No test can prove the absence of a copy, and `test_barehands_clean_room.py` says
so in its own docstring. What it holds is the four things that make a copy hard
to make by accident and impossible to make silently.

## What a human must still do

In priority order. None of it can be done from here.

1. **Run the camera session**, `docs/OPERATIONS.md` A1-A7. Start with **A2.2**
   (flat hand, fingers together, thumb adducted → false wake?). It is the single
   most-referenced open item of the whole task, and if it fails the wake band
   has to be retuned before the rest of the session is worth running.
2. **Decide `reachNorm`**: apply it to the pointer mapping, or drop the
   measurement. Leaving it measured-and-unread forever is the worst of the three.
3. **Decide the two-tabs behaviour** (A1.8) — it has no written contract, and
   whatever is observed should become one.
4. **Give `installJarvisScene` a DOM harness**, or accept A4.2 as a permanent
   manual check.
5. **Decide trace retention.** Traces are opt-in and scalar-only, but they are
   never pruned. `runtime/trace.jsonl` has the same standing, so this is a
   consistent choice, not an oversight — but it is a choice nobody has revisited.
6. **Legal review of the naming**, if this ever ships commercially. "Bare Hands"
   and "Barehands" are one letter and one space apart, and the second is AGPL.
   The convention (`docs/ARCHITECTURE.md` › *Two subsystems, one word*) makes the
   repository consistent; it does not make the names far apart.

## Deliberately not done by Slice 11

- **Nothing was merged into `main`**, no branch was deleted or switched, and
  nothing was moved in Drive. Those need explicit Human direction, which has not
  been given.
- **No human-validation check is marked passed.** They are recorded as waived,
  in every file that records status.
- **`GET /api/scene/patches` was left unguarded**, deliberately. It has the same
  long-poll shape as the command channel but not the property that made the
  command channel's GET a defect: its cursor is caller-supplied and nothing is
  consumed server-side, so a cross-origin call takes nothing from anyone. Fixing
  it would have been scope creep into the scene subsystem on the last Slice.

## A note on `slices/TODO.md`

Its checkboxes are unticked. **This is a repository-wide convention, not
evidence of incompleteness** — the finished 2026-08-31 handoff's TODO.md is
unticked too. Slice status lives in `LOG.md` and in this file.
