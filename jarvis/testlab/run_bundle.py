"""The bundle of a run: normalize a run's OWN trace into a `DiagnosticBundle`.

Binding contract: `docs/testlab.md` ("Bundle of a run"). Pure: it decides WHICH
evidence of a stored run is the journal and WHICH session the bundle describes, and
nothing else. The reading, the building and the storing are `bundle_capture`'s, the
attachment is the run store's (`attach_bundle`), and the composition of the three is
`TestLabApi.capture_run_bundle`.

Slices 03 and 06 each built one half and deliberately left the join open. Slice 03's
capture service reads the LIVE journal, which is how a real incident becomes evidence.
Slice 06 made a run write the live runtime's own kinds to its own `trace.jsonl` and
commit it as a `trace_excerpt` artifact, with `session_id = <run_id>-s<n>` — but a
runner may not write the run record, and `WorkerResult` carries no bundle id, so the
run could not point at its own normalization. This module closes that: the same
normalization, the same rules, the same document, over the trace a run produced.

Why it is worth having both directions. A bundle of a real session says what Jarvis did
on this workstation; a bundle of a RUN says what Jarvis did under a declared stimulus,
in a document with exactly the same shape. That is what makes "the incident and the
reproduction, side by side" a comparison of two bundles rather than a comparison of a
bundle with a log.
"""

from __future__ import annotations

from jarvis.testlab.bundle_builder import SessionSelector
from jarvis.testlab.runs import ArtifactKind, ArtifactRef, TestRun
from jarvis.testlab.validation import TestLabError, fail

#: A run with no journal artifact cannot have a bundle of its own.
RUN_BUNDLE_NO_TRACE = "testlab_run_bundle_no_trace"
#: Voice session a run's journal lines carry, first of `<run_id>-s1`, `-s2`, ... (Slice 06).
FIRST_SESSION_SUFFIX = "-s1"


class RunBundleError(TestLabError):
    """A stored run cannot be normalized into a bundle (no journal evidence)."""


def select_trace_artifact(run: TestRun) -> ArtifactRef:
    """The run's journal artifact: its single `trace_excerpt`, or `testlab_run_bundle_no_trace`.

    Chosen by KIND, never by name, so this holds for any profile whose runner commits a
    journal. More than one is refused rather than guessed at: which excerpt the bundle
    describes is not a decision this module may make quietly.
    """
    if not isinstance(run, TestRun):
        raise fail("select_trace_artifact takes a TestRun record")
    excerpts = [ref for ref in run.artifacts if ref.kind is ArtifactKind.TRACE_EXCERPT]
    if not excerpts:
        raise RunBundleError(RUN_BUNDLE_NO_TRACE,
                             f"run {run.run_id} stored no trace_excerpt artifact, so it has no journal to normalize")
    if len(excerpts) > 1:
        raise RunBundleError(RUN_BUNDLE_NO_TRACE,
                             f"run {run.run_id} stored {len(excerpts)} trace_excerpt artifacts; "
                             "name the one to normalize")
    return excerpts[0]


def run_session_selector(run: TestRun, *, session_id: str | None = None) -> SessionSelector:
    """Which session of the run's trace the bundle describes.

    By default the run's FIRST voice session, `<run_id>-s1`, which is what every seed
    runner produces and what the Slice 06 test pins (one segment, no coverage warning).
    A run that mounted several sessions is normalized one at a time, by passing
    `session_id`: a bundle is the evidence of ONE session, and merging two would make
    every rule's horizon a lie.
    """
    if not isinstance(run, TestRun):
        raise fail("run_session_selector takes a TestRun record")
    return SessionSelector(session_id=session_id or f"{run.run_id}{FIRST_SESSION_SUFFIX}")
