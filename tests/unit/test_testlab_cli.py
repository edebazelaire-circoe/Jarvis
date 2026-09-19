"""Slice 10: the CLI — argument parsing, output shapes, exit codes, and the documented table.

Contract: `docs/testlab.md` ("Native API, CLI and HTTP"). An agent reads the exit code
before it reads anything else and parses `--json` from stdout, so both are pinned here
rather than reviewed. The command table in the documentation is compared with the parser,
for the same reason `tests/unit/test_documented_routes.py` compares routes with the
router: a wrong entry in the manual costs a debugging session.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import re
import tempfile

import pytest

from jarvis.testlab.cli import (
    CLI_FAILED_MESSAGE,
    CLI_USAGE,
    EXIT_CANCELLED,
    EXIT_ERROR,
    EXIT_CRASHED,
    EXIT_FAILED,
    EXIT_INCONCLUSIVE,
    EXIT_OK,
    EXIT_PENDING,
    EXIT_REFUSED,
    EXIT_USAGE,
    NEEDS_SUPERVISOR,
    OUTCOME_EXIT,
    SWEEP_EXIT,
    Console,
    TestLabCliError,
    _exit_for,
    _usage_refusal,
    build_parser,
    check_presenter_input,
    needs_supervisor,
    parse_assignments,
    parse_axis,
    render_bundle,
    render_comparison,
    render_retention,
    render_run_detail,
    render_runs,
    render_status,
    render_sweep,
)
from jarvis.testlab.outcomes import RunOutcomeClass
from jarvis.testlab.sweeps import SweepStatus, SweepTarget

DOCS = Path(__file__).resolve().parents[2] / "docs" / "testlab.md"

#: Every command the Slice contract requires, plus the ones this CLI adds.
REQUIRED_COMMANDS = ("list", "describe", "run", "status", "cancel", "runs", "show", "compare", "sweep",
                     "capture", "bundles", "retention")


def commands() -> dict:
    """The subparsers `build_parser()` declares, by name."""
    parser = build_parser()
    action = next(item for item in parser._actions if getattr(item, "choices", None)
                  and isinstance(item.choices, dict))
    return dict(action.choices)


# ------------------------------------------------------------------ parsing

def test_every_required_command_exists():
    declared = commands()
    assert set(REQUIRED_COMMANDS) <= set(declared), sorted(set(REQUIRED_COMMANDS) - set(declared))


def test_the_documentation_lists_exactly_the_commands_the_parser_declares():
    """A manual that names a command the program does not have is worse than no manual."""
    text = DOCS.read_text(encoding="utf-8")
    table = text.partition("<!-- cli-commands -->")[2].partition("<!-- /cli-commands -->")[0]
    assert table.strip(), "docs/testlab.md carries no CLI command table"
    documented = set(re.findall(r"^\| `([a-z-]+)", table, flags=re.MULTILINE))
    assert set(commands()) == documented, sorted(set(commands()) ^ documented)


def test_a_run_is_parsed_with_its_parameters_overrides_and_bounds():
    args = build_parser().parse_args(["--json", "run", "voice.self_echo", "--profile", "virtual",
                                      "-p", "output.duration_ms=2000", "-o", "audio_input_device=3",
                                      "--timeout", "30"])
    assert args.command == "run" and args.json is True and args.profile == "virtual"
    assert parse_assignments(args.parameter, "-p") == {"output.duration_ms": 2000}
    assert parse_assignments(args.override, "-o") == {"audio_input_device": 3}
    assert args.timeout == 30.0 and args.no_wait is False and args.guided is False


def test_an_unknown_profile_is_a_usage_error_not_a_crash():
    with pytest.raises(SystemExit) as caught:
        build_parser().parse_args(["run", "x", "--profile", "quantum"])
    assert caught.value.code == EXIT_USAGE


def test_a_missing_required_argument_is_a_usage_error():
    with pytest.raises(SystemExit) as caught:
        build_parser().parse_args(["describe"])
    assert caught.value.code == EXIT_USAGE


def test_assignments_read_json_values_and_fall_back_to_text():
    parsed = parse_assignments(["count=3", "ratio=1.5", "on=true", "mode=measure", "quoted=\"12\""], "-p")
    assert parsed == {"count": 3, "ratio": 1.5, "on": True, "mode": "measure", "quoted": "12"}


def test_a_malformed_or_repeated_assignment_is_refused_with_the_real_cause():
    for item, fragment in ((["novalue"], "name=value"), (["=3"], "name=value"),
                           (["a=1", "a=2"], "twice")):
        with pytest.raises(TestLabCliError) as caught:
            parse_assignments(item, "-p")
        assert fragment in str(caught.value)


def test_an_axis_defaults_to_a_parameter_and_can_name_an_override():
    axis = parse_axis("output.duration_ms=1000,2000,4000")
    assert axis.name == "output.duration_ms" and axis.target is SweepTarget.PARAMETER
    assert axis.values == (1000, 2000, 4000)
    assert parse_axis("override:audio_input_device=1,2").target is SweepTarget.OVERRIDE


def test_an_axis_with_no_value_or_an_unknown_target_is_refused():
    for item, fragment in (("name=", "lists no value"), ("nope:name=1", "target must be one of"),
                           ("name", "name=v1,v2")):
        with pytest.raises(TestLabCliError) as caught:
            parse_axis(item)
        assert fragment in str(caught.value)


def test_only_the_commands_that_execute_something_take_the_work_root():
    """A read command must keep working while the Control Center holds the supervisor."""
    assert NEEDS_SUPERVISOR <= set(commands()) | {"maintain"}
    for read_only in ("list", "describe", "runs", "show", "compare", "bundles", "capture", "sweeps"):
        assert read_only not in NEEDS_SUPERVISOR, read_only
    for executes in ("run", "sweep", "cancel", "guided"):
        assert executes in NEEDS_SUPERVISOR, executes


# --------------------------------------------------------------- exit codes

def test_every_outcome_has_an_exit_code():
    """An outcome with no code would silently read as success."""
    assert set(OUTCOME_EXIT) == set(RunOutcomeClass)


def test_the_exit_codes_tell_the_outcomes_apart():
    assert OUTCOME_EXIT[RunOutcomeClass.PASSED] == EXIT_OK
    assert OUTCOME_EXIT[RunOutcomeClass.FAILED] == EXIT_FAILED
    assert OUTCOME_EXIT[RunOutcomeClass.INCONCLUSIVE] == EXIT_INCONCLUSIVE
    assert OUTCOME_EXIT[RunOutcomeClass.REFUSED] == EXIT_REFUSED
    assert OUTCOME_EXIT[RunOutcomeClass.CRASHED] == EXIT_CRASHED
    assert OUTCOME_EXIT[RunOutcomeClass.CANCELLED] == EXIT_CANCELLED
    assert OUTCOME_EXIT[RunOutcomeClass.PENDING] == EXIT_PENDING
    assert len(set(OUTCOME_EXIT.values())) == len(OUTCOME_EXIT), "two outcomes share an exit code"


def test_usage_and_command_failure_never_collide_with_an_outcome():
    """`2` is argparse's own usage code, and `7` says the command broke, not the product."""
    assert EXIT_USAGE == 2 and EXIT_USAGE not in OUTCOME_EXIT.values()
    assert EXIT_ERROR not in OUTCOME_EXIT.values()


def test_the_exit_code_comes_from_the_derived_outcome_not_from_the_status():
    view = {"outcome": {"outcome": "inconclusive"}}
    assert _exit_for(view) == EXIT_INCONCLUSIVE


# ---------------------------------------------------------------- rendering

def run_view(**changes):
    run = {"run_id": "tlr-1", "diagnostic_id": "voice.self_echo", "diagnostic_version": 2, "profile": "virtual",
           "status": "failed", "created_at": "2026-09-18T10:00:00.000Z", "started_at": "2026-09-18T10:00:01.000Z",
           "finished_at": "2026-09-18T10:00:09.000Z", "failure": None,
           "metrics": {"barge_in.false_confirmed_count": 1}, "assertion_results": [
               {"assertion_id": "no_false_barge_in", "outcome": "failed", "observed": 1, "blocking": True}],
           "artifacts": [{"path": "worker.log", "kind": "worker_log", "size_bytes": 12}]}
    outcome = {"run_id": "tlr-1", "status": "failed", "outcome": "failed", "failure_code": None,
               "verdict": "failed", "failed_assertions": ["no_false_barge_in"], "missing_assertions": [],
               "measured": True, "score": None}
    view = {"run": run, "outcome": outcome}
    view.update(changes)
    return view


def test_a_run_report_names_the_verdict_the_metrics_and_what_broke():
    text = render_run_detail(run_view())
    assert "tlr-1" in text and "failed" in text
    assert "barge_in.false_confirmed_count = 1" in text
    assert "failed blocking assertions: no_false_barge_in" in text
    assert "worker.log" in text


def test_a_run_with_no_measurement_says_so_instead_of_showing_an_empty_block():
    view = run_view()
    view["run"] = {**view["run"], "metrics": {}}
    assert "metrics: none recorded" in render_run_detail(view)


def test_a_failure_code_and_its_sentence_are_both_shown():
    view = run_view()
    view["run"] = {**view["run"], "failure": {"code": "device_contention", "detail": "the mic is held"}}
    text = render_run_detail(view)
    assert "device_contention" in text and "the mic is held" in text


def test_a_listing_reports_unreadable_entries_instead_of_hiding_them():
    payload = {"runs": [run_view()], "next_cursor": "tlr-1",
               "corrupt": [{"entry": "tlr-x", "code": "testlab_store_corrupt", "detail": "bad json"}]}
    text = render_runs(payload)
    assert "1 run(s)" in text and "tlr-x (testlab_store_corrupt)" in text
    assert "--after tlr-1" in text


def test_a_comparison_shows_the_deltas_and_every_incomparability():
    payload = {"baseline_run_id": "tlr-1", "candidate_run_id": "tlr-2", "comparable": False,
               "baseline_outcome": "passed", "candidate_outcome": "failed",
               "metrics": [{"metric": "m", "baseline": 1, "candidate": 2, "change": "worse", "delta": 1.0}],
               "assertions": [{"assertion_id": "a", "baseline": "passed", "candidate": "failed",
                               "change": "regressed"}],
               "incomparable": [{"subject": "run", "reason": "different_version", "detail": "v1 vs v2"}],
               "differences": [{"field": "parameters"}]}
    text = render_comparison(payload)
    assert "worse" in text and "regressed" in text
    assert "incomparable run: different_version" in text and "differs: parameters" in text


def test_a_sweep_report_names_every_point_and_the_best_ones():
    payload = {"sweep": {"sweep_id": "tls-1", "status": "completed",
                         "spec": {"diagnostic_id": "d", "profile": "virtual"},
                         "points": [{"point": {"index": 0, "values": {"x": 1}},
                                     "runs": [{"outcome": "passed"}], "failure": None}]},
               "summary": {"best_points": [{"metric": "m", "direction": "lower_better", "point": 0,
                                            "median": 3.0}],
                           "note": "A sweep reports; it never writes a winning value."}}
    text = render_sweep(payload)
    assert "tls-1" in text and "point 0" in text and "best for m" in text
    assert "never writes a winning value" in text


def test_a_disabled_retention_says_nothing_would_be_deleted():
    text = render_retention({"enabled": False, "cutoff": None, "deletions": [], "deferred": 0,
                             "blocked_active": 0, "blocked_corrupt": [], "unmet": []})
    assert "disabled" in text and "nothing would be deleted" in text


def test_the_status_report_shows_the_grant_and_the_microphone():
    payload = {"config": {"root": "r", "work_root": "w", "catalog_root": "c",
                          "grant": {"capabilities": ["realtime_provider"], "max_cost_usd": 1.0},
                          "opt_ins": {"JARVIS_TESTLAB_LIVE": True}},
               "started": True, "active_runs": [], "pending_runs": [], "active_sweeps": [],
               "contention": {"state": "busy", "reason": "the audio devices are held"},
               "storage": {"runs": 3, "total_bytes": 10, "corrupt": 0}}
    text = render_status(payload)
    assert "realtime_provider" in text and "$1.00" in text
    assert "JARVIS_TESTLAB_LIVE=on" in text and "busy" in text


# ------------------------------------------------------------------ console

def test_json_output_is_the_payload_alone_on_stdout():
    """An agent parses stdout; nothing else may ever land there."""
    out, err = io.StringIO(), io.StringIO()
    console = Console(as_json=True, out=out, err=err)
    console.note("a live line")
    console.tick("  | working")
    console.report({"run_id": "tlr-1"}, "human text")
    assert json.loads(out.getvalue()) == {"run_id": "tlr-1"}
    assert "a live line" in err.getvalue() and "working" in err.getvalue()


def test_human_output_never_prints_json():
    out, err = io.StringIO(), io.StringIO()
    console = Console(as_json=False, out=out, err=err)
    console.report({"run_id": "tlr-1"}, "human text")
    assert out.getvalue().strip() == "human text"


# ------------------------------- rework B1: no presenter where nobody can answer

def guided_args(**changes):
    argv = ["run", "voice.self_echo", "--profile", "hardware:guided", "--guided"]
    if changes.pop("headless", False):
        argv.append("--headless")
    return build_parser().parse_args(argv)


def test_guided_is_refused_when_stdin_is_not_a_terminal():
    """From a script, a pipe or CI, every prompt would be answered the instant it appeared."""
    with pytest.raises(TestLabCliError) as caught:
        check_presenter_input(guided_args(), isatty=False)
    message = str(caught.value)
    assert "not a terminal" in message and "--headless" in message
    assert "in a human's name" in message


def test_guided_is_allowed_on_a_terminal_or_with_the_explicit_override():
    check_presenter_input(guided_args(), isatty=True)
    check_presenter_input(guided_args(headless=True), isatty=False)


def test_the_guided_command_takes_the_same_override():
    args = build_parser().parse_args(["guided", "tlr-x", "--headless"])
    assert args.headless is True
    check_presenter_input(args, isatty=False)


# ------------------------------------- rework S4: who has to own the work root

def test_retention_takes_the_work_root_only_when_it_applies_the_plan():
    """`--apply` calls `supervisor.maintain()`, which sweeps and deletes."""
    assert needs_supervisor(build_parser().parse_args(["retention", "--apply"])) is True
    assert needs_supervisor(build_parser().parse_args(["retention"])) is False


def test_the_supervisor_set_names_only_real_commands():
    assert NEEDS_SUPERVISOR <= set(commands())
    assert "maintain" not in NEEDS_SUPERVISOR, "a name that is not a command proves nothing"


def test_every_command_that_writes_owns_the_work_root():
    for argv in (["run", "d"], ["sweep", "d", "--axis", "x=1"], ["cancel", "tlr-x"], ["guided", "tlr-x"],
                 ["retention", "--apply"]):
        assert needs_supervisor(build_parser().parse_args(argv)) is True, argv
    for argv in (["list"], ["describe", "d"], ["runs"], ["show", "tlr-x"], ["bundles"], ["capture"],
                 ["sweeps"], ["retention"], ["status"]):
        assert needs_supervisor(build_parser().parse_args(argv)) is False, argv


# ------------------------------------------------------- rework nits

def test_a_sweep_somebody_stopped_is_cancelled_not_a_product_failure():
    assert SWEEP_EXIT["completed"] == EXIT_OK
    assert SWEEP_EXIT["cancelled"] == EXIT_CANCELLED
    assert SWEEP_EXIT["failed"] == EXIT_FAILED
    assert set(SWEEP_EXIT) == {item.value for item in SweepStatus}


def test_a_non_finite_value_is_refused_where_the_operator_typed_it():
    """`json.loads` accepts Infinity/NaN; every Test Lab value guard then refuses them far
    from here with a message about a field."""
    for raw in ("Infinity", "-Infinity", "NaN"):
        with pytest.raises(TestLabCliError) as caught:
            parse_assignments([f"x={raw}"], "-p")
        assert "finite" in str(caught.value) and raw in str(caught.value)
    assert parse_assignments(["x=1e308"], "-p") == {"x": 1e308}


def test_the_live_line_says_what_ctrl_c_actually_does():
    """It stops the run (the supervisor is closed, which cancels it), it does not just detach."""
    source = Path(__file__).resolve().parents[2] / "jarvis" / "testlab" / "cli.py"
    text = source.read_text(encoding="utf-8")
    assert "Ctrl-C stops the run" in text
    assert "Ctrl-C asks the run to stop" not in text


def test_the_status_report_shows_a_grant_that_was_reduced():
    payload = {"config": {"root": "r", "work_root": "w", "catalog_root": "c",
                          "grant": {"capabilities": [], "max_cost_usd": 1000.0},
                          "grant_refusal": "JARVIS_TESTLAB_MAX_COST_USD is above the ceiling",
                          "opt_ins": {}},
               "started": False, "active_runs": [], "pending_runs": [], "active_sweeps": [],
               "contention": {"state": "free", "reason": "the audio devices are free"},
               "storage": {"runs": 0, "total_bytes": 0, "corrupt": 0}}
    assert "above the ceiling" in render_status(payload)


# --------------------------- rework 3: one refusal document for every failure

def test_the_console_closes_an_in_place_line_before_a_durable_one():
    """A countdown must not eat the header above it, nor leave half a line behind."""
    class Terminal(io.StringIO):
        def isatty(self): return True

    out, err = io.StringIO(), Terminal()
    console = Console(as_json=False, out=out, err=err)
    console.tick("  | 12.0 s left")
    console.note("  -> acknowledged.")
    text = err.getvalue()
    assert text.startswith("\r  | 12.0 s left"), text
    assert text.endswith("  -> acknowledged.\n")
    assert "\n" in text[: text.index("-> acknowledged")], "the live line was never closed"


def test_the_console_appends_plain_lines_when_stderr_is_not_a_terminal():
    out, err = io.StringIO(), io.StringIO()
    console = Console(as_json=False, out=out, err=err)
    console.tick("  | 12.0 s left")
    console.note("  -> done")
    assert err.getvalue() == "  | 12.0 s left\n  -> done\n"


def test_a_usage_refusal_answers_the_same_json_document_as_every_other_failure():
    """An agent branching on a payload must not get an empty stdout for one class."""
    out, err = io.StringIO(), io.StringIO()
    console = Console(as_json=True, out=out, err=err)
    assert _usage_refusal(console, TestLabCliError("--axis 'x' lists no value")) == EXIT_USAGE
    payload = json.loads(out.getvalue())
    assert payload["ok"] is False and payload["code"] == CLI_USAGE
    assert "lists no value" in payload["error"] and "lists no value" in err.getvalue()


def test_a_usage_refusal_prints_nothing_on_stdout_in_human_mode():
    out, err = io.StringIO(), io.StringIO()
    assert _usage_refusal(Console(as_json=False, out=out, err=err), "bad argument") == EXIT_USAGE
    assert out.getvalue() == "" and "bad argument" in err.getvalue()


def test_the_unforeseen_failure_payload_carries_no_raw_exception_text():
    """Same rule as the HTTP boundary: an agent forwarding the document must not carry a
    path or a token out of a message the code happened to be holding."""
    assert CLI_FAILED_MESSAGE and "stderr" in CLI_FAILED_MESSAGE
    assert "{" not in CLI_FAILED_MESSAGE and "%s" not in CLI_FAILED_MESSAGE


# ------------------------------------------- bundle rendering (Slice 12 rework)

def real_bundle_payload(**changes):
    """The `bundle` view of a REAL `DiagnosticBundle`, built by the domain, with findings.

    Built rather than restated on purpose. `render_bundle` shipped reading `finding["rule"]`
    and `coverage["sources"]`, neither of which the document has ever had; every fixture in
    the suite had zero findings and no test referenced the function, so a real session with
    a finding crashed the command and the coverage lines were silently never printed. A
    payload invented here would have reproduced the same mistake, so this one comes through
    the builder and the API's own view.
    """
    from datetime import timedelta

    from jarvis.testlab.api import bundle_view
    from jarvis.testlab.bundle_builder import EventEvidence, SourceStatus, build_diagnostic_bundle
    from jarvis.testlab.bundle_capture import read_session_trace
    from jarvis.testlab.store import BundleSummary
    import tests.fakes.testlab_bundle as fx

    directory = Path(tempfile.mkdtemp())
    fx.write_trace(directory / "trace.jsonl")
    events = EventEvidence(SourceStatus.AVAILABLE, origin="export", events=tuple(fx.session_events()),
                           export_complete=True)
    moments = [item.event.occurred_at for item in events.events]
    trace = read_session_trace(directory / "trace.jsonl", fx.selector(),
                               start=min(moments) - timedelta(seconds=30),
                               end=max(moments) + timedelta(seconds=30)).evidence
    bundle = build_diagnostic_bundle(fx.selector(), context=fx.context(), events=events, trace=trace)
    payload = {"bundle": bundle_view(BundleSummary.of(bundle)), "stored": "stored",
               "coverage": dict(bundle.document["coverage"]),
               "findings": [dict(item) for item in bundle.findings]}
    payload.update(changes)
    return payload, bundle


def test_render_bundle_prints_every_finding_of_a_real_bundle():
    payload, bundle = real_bundle_payload()
    assert bundle.findings, "this fixture must carry findings, or it cannot guard the renderer"

    text = render_bundle(payload)

    assert text.count("  finding ") == len(bundle.findings)
    for finding in bundle.findings:
        assert finding["rule_id"] in text
        assert str(finding["subject_id"]) in text
        for measure in finding["measured"]:
            assert f"{measure['name']}={measure['value']}" in text
    assert "rule_id" not in text, "the label is the rule, not the field name"


def test_render_bundle_prints_a_source_that_could_not_be_read():
    """The exact line the operator runbook tells a human to look for."""
    payload, _ = real_bundle_payload()
    payload["coverage"] = {**payload["coverage"],
                           "conversation_events": {**payload["coverage"]["conversation_events"],
                                                   "status": "unavailable",
                                                   "reason": "conversation_events_table_absent"}}

    text = render_bundle(payload)

    assert "  source conversation_events: unavailable (conversation_events_table_absent)" in text
    assert "  source runtime_journal: available" in text
    assert "  source voice_session_reports:" in text


def test_render_bundle_reports_only_the_entries_that_are_sources():
    """`content`, `limits`, `segments` and `warnings` live beside the sources, not among them."""
    payload, _ = real_bundle_payload()
    coverage = payload["coverage"]
    assert {"content", "limits", "segments", "warnings"} <= set(coverage), "the document shape moved"

    text = render_bundle(payload)

    assert "source content" not in text and "source limits" not in text
    assert "source segments" not in text and "source warnings" not in text
    assert f"  voice sessions: {coverage['segments']['count']}" in text


def test_render_bundle_says_when_a_capture_stored_nothing_and_attached_nothing():
    payload, _ = real_bundle_payload(stored=None, findings=[], coverage={})
    text = render_bundle(payload)
    assert "stored" not in text and "references" not in text
    assert "finding" not in text.partition("findings:")[2].partition("\n")[2]


def test_render_bundle_says_whether_THIS_call_made_the_reference():
    """A run captured twice still HAS a bundle id; only the first call made it."""
    run_id, bundle_id = "tlr-20260917T105800123Z-0123456789abcdef", "tlb-20260917T120000000Z-" + "a" * 16
    made, _ = real_bundle_payload(run_id=run_id, attached_bundle_id=bundle_id, attached=True)
    already, _ = real_bundle_payload(run_id=run_id, attached_bundle_id=bundle_id, attached=False)

    assert f"  run {run_id} now references {bundle_id}" in render_bundle(made)
    assert f"  run {run_id} already referenced {bundle_id}" in render_bundle(already)
