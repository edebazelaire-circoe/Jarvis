"""`python -m jarvis.testlab`: the Test Lab for operators and for agents.

Binding contract: `docs/testlab.md` ("Native API, CLI and HTTP"). Every command is a call
on `TestLabApi`, so the CLI, the Control Center routes and a script see exactly the same
records; nothing is computed here that is not computed there.

Two audiences, one implementation:

- a **human** gets a short report, plus a live line while anything is running (what it is
  doing, how long it has been doing it, and how to stop it);
- an **agent** passes `--json` and gets the documented shape on stdout, alone. Progress,
  countdowns and warnings always go to stderr, so `--json` output is parseable as it is.

Exit codes mean something, because an agent reads them before it reads anything else::

    0  passed / the command succeeded      4  refused (a gate declined to run it)
    1  a run failed (product verdict)      5  crashed (the Test Lab broke around the run)
    2  usage error (argparse)              6  cancelled
    3  inconclusive (could not measure)    7  the command itself failed
                                           8  no verdict yet (asked not to wait)

Nothing here widens authority. Capabilities and budgets come from the process environment
through the composition layer (`jarvis.testlab.composition`); a flag on this command line
can only narrow what is already allowed, and `--guided` attaches a presenter without
granting presence — a guided run with no `JARVIS_TESTLAB_GUIDED=1` is refused by the
supervisor and this prints why.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Mapping, Sequence
import json
import math
from pathlib import Path
import sys
import time
import traceback
from typing import Any

from jarvis.testlab.api import TestLabApi, parse_time_argument
from jarvis.testlab.bundle_builder import SessionSelector
from jarvis.testlab.composition import build_test_lab
from jarvis.testlab.outcomes import RunOutcomeClass
from jarvis.testlab.presenter import GuidedPresenter, SPINNER, presenter_input_available
from jarvis.testlab.profiles import ProfileName
from jarvis.testlab.runs import TERMINAL_STATUSES, RunStatus
from jarvis.testlab.sweeps import SweepSpec, SweepStatus, SweepTarget, SweptParameter
from jarvis.testlab.validation import TestLabError

PROGRAM = "python -m jarvis.testlab"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_INCONCLUSIVE = 3
EXIT_REFUSED = 4
EXIT_CRASHED = 5
EXIT_CANCELLED = 6
EXIT_ERROR = 7
EXIT_PENDING = 8

#: Code of a failure the CLI did not foresee. It is ours, not the caller's. Its `error` is
#: a fixed sentence, like the HTTP boundary's: the message of an unforeseen exception is
#: whatever the code was holding — a path, a token, a file's contents — and an agent that
#: forwards this document would carry it further. The real text goes to stderr only.
CLI_FAILED = "testlab_cli_failed"
CLI_FAILED_MESSAGE = ("the command failed for a reason this program did not foresee; the type, the "
                      "message and the traceback are on stderr")
#: Code of a command line this program cannot read (exit 2).
CLI_USAGE = "testlab_cli_usage"

#: How a terminal run's derived outcome becomes this process's exit status. Closed and
#: total over `RunOutcomeClass`, pinned by a test: an outcome with no code here would
#: silently read as success.
OUTCOME_EXIT: Mapping[RunOutcomeClass, int] = {
    RunOutcomeClass.PASSED: EXIT_OK,
    RunOutcomeClass.FAILED: EXIT_FAILED,
    RunOutcomeClass.INCONCLUSIVE: EXIT_INCONCLUSIVE,
    RunOutcomeClass.REFUSED: EXIT_REFUSED,
    RunOutcomeClass.CRASHED: EXIT_CRASHED,
    RunOutcomeClass.CANCELLED: EXIT_CANCELLED,
    RunOutcomeClass.PENDING: EXIT_PENDING,
}

#: Commands that MAY take the work-root lock (`_take_work_root`). Every other command only
#: reads the stores, so it works while the Control Center is running, and must never
#: create `<runtime>/testlab/`. `retention` is conditional — see `needs_supervisor`.
#: This is the DECLARED contract; `tests/integration/test_testlab_cli_e2e.py` runs each
#: command against a fresh root and checks the declaration against what actually happens.
NEEDS_SUPERVISOR = frozenset({"run", "sweep", "cancel", "guided"})


def needs_supervisor(args: argparse.Namespace) -> bool:
    """May this invocation own the work root?

    `retention --apply` may: it calls `supervisor.maintain()`, which sweeps stale
    temporaries and deletes runs. Taking the lock is what keeps that off a run another
    process is executing; reading the plan does not touch anything and must not take it.

    "May", not "does": a command that refuses on its own arguments, on an unknown
    diagnostic or on an unknown run id returns before `_take_work_root` is reached.
    """
    if args.command in NEEDS_SUPERVISOR:
        return True
    return args.command == "retention" and bool(getattr(args, "apply_pass", False))


#: How a finished sweep becomes an exit status. A sweep somebody stopped is `cancelled`,
#: not a product verdict, for the same reason a cancelled run is.
SWEEP_EXIT: Mapping[str, int] = {
    SweepStatus.COMPLETED.value: EXIT_OK,
    SweepStatus.CANCELLED.value: EXIT_CANCELLED,
    SweepStatus.FAILED.value: EXIT_FAILED,
    SweepStatus.RUNNING.value: EXIT_PENDING,
}

#: Ticker period of the "still running" line.
PROGRESS_TICK_S = 1.0


# ------------------------------------------------------------------ arguments

def parse_assignments(items: Sequence[str] | None, what: str) -> dict[str, Any]:
    """`name=value` pairs, with JSON values (`3`, `true`, `"a"`) falling back to plain text.

    `-p value=3` is the number 3 and `-p mode=measure` is the string "measure", which is
    what both a declaration and a human mean. A value that must stay a string although it
    looks like a number is written as JSON: `-p label="12"`.
    """
    parsed: dict[str, Any] = {}
    for item in items or ():
        name, separator, raw = item.partition("=")
        if not separator or not name:
            raise TestLabCliError(f"{what} must be written name=value, got {item!r}")
        if name in parsed:
            raise TestLabCliError(f"{what} {name!r} is given twice")
        parsed[name] = _scalar(raw)
    return parsed


def _scalar(raw: str) -> Any:
    """One JSON scalar, or the text as it was typed. `Infinity`/`NaN` are refused.

    `json.loads` accepts the three non-finite literals, which every Test Lab value guard
    then rejects far from here with a message about a field. Refusing at the source names
    the argument the operator actually typed.
    """
    try:
        value = json.loads(raw)
    except ValueError:
        return raw
    if isinstance(value, float) and not math.isfinite(value):
        raise TestLabCliError(f"{raw!r} is not a finite number; a measurement bound must be one")
    return value


def parse_axis(item: str) -> SweptParameter:
    """`name=v1,v2,v3` or `override:name=v1,v2`: one swept axis, values in declaration order."""
    head, separator, raw = item.partition("=")
    if not separator or not head:
        raise TestLabCliError(f"--axis must be written name=v1,v2 (got {item!r})")
    target = SweepTarget.PARAMETER
    if ":" in head:
        prefix, _, head = head.partition(":")
        try:
            target = SweepTarget(prefix)
        except ValueError:
            raise TestLabCliError(f"--axis target must be one of "
                                  f"{', '.join(item.value for item in SweepTarget)}") from None
    values = tuple(_scalar(part) for part in raw.split(",") if part != "")
    if not values:
        raise TestLabCliError(f"--axis {head!r} lists no value")
    return SweptParameter(name=head, target=target, values=values)


class TestLabCliError(Exception):
    """A command line this program cannot read. Reported as a usage error, never a crash."""

    __test__ = False  # not a pytest test class, despite the name


def build_parser() -> argparse.ArgumentParser:
    """Every command, its arguments and its one-line help. Pure: a test parses against it."""
    parser = argparse.ArgumentParser(prog=PROGRAM, description="Category 2 Test Lab")
    parser.add_argument("--json", action="store_true", help="print the documented JSON shape on stdout")
    parser.add_argument("--runtime-root", type=Path, default=None,
                        help="compose the Test Lab under this runtime directory (default: JARVIS_RUNTIME_DIR)")
    parser.add_argument("--data-root", type=Path, default=None, help="Core data root (default: JARVIS_DATA_ROOT)")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    commands.add_parser("list", help="every official diagnostic, latest version")

    describe = commands.add_parser("describe", help="one diagnostic: profiles, parameters, metrics, assertions")
    describe.add_argument("diagnostic_id")
    describe.add_argument("--version", type=int, default=None)

    run = commands.add_parser("run", help="execute one diagnostic and report its outcome")
    run.add_argument("diagnostic_id")
    run.add_argument("--profile", default=ProfileName.VIRTUAL.value,
                     choices=[item.value for item in ProfileName])
    run.add_argument("--version", type=int, default=None)
    run.add_argument("-p", "--parameter", action="append", metavar="NAME=VALUE",
                     help="run parameter (repeatable)")
    run.add_argument("-o", "--override", action="append", metavar="NAME=VALUE",
                     help="run-local setting override, allowlisted by the manifest (repeatable)")
    run.add_argument("--scenario", type=Path, default=None,
                     help="JSON scenario file replacing the manifest scenario")
    run.add_argument("--bundle-id", default=None, help="DiagnosticBundle this run investigates")
    run.add_argument("--allow-audio-artifacts", action="store_true",
                     help="let this run store audio clips (also needs the store's own opt-in)")
    run.add_argument("--guided", action="store_true",
                     help="present guided prompts on this terminal while the run executes")
    run.add_argument("--headless", action="store_true",
                     help="allow --guided although stdin is not a terminal (you are piping answers in)")
    run.add_argument("--timeout", type=float, default=1800.0, help="how long to wait for the run")
    run.add_argument("--no-wait", action="store_true", help="queue the run, print its id and exit")

    status = commands.add_parser("status", help="one run, or the Test Lab itself with no argument")
    status.add_argument("run_id", nargs="?", default=None)

    cancel = commands.add_parser("cancel", help="ask a run to stop")
    cancel.add_argument("run_id")
    cancel.add_argument("--reason", default=None)

    runs = commands.add_parser("runs", help="query stored runs")
    runs.add_argument("--diagnostic-id", default=None)
    runs.add_argument("--version", type=int, default=None, dest="diagnostic_version")
    runs.add_argument("--profile", default=None, choices=[item.value for item in ProfileName])
    runs.add_argument("--status", action="append", dest="statuses",
                      choices=[item.value for item in RunStatus])
    runs.add_argument("--sweep-id", default=None)
    runs.add_argument("--bundle-id", default=None)
    runs.add_argument("--limit", type=int, default=20)
    runs.add_argument("--oldest-first", action="store_true")
    runs.add_argument("--after", default=None, dest="after_run_id", help="cursor from a previous page")

    show = commands.add_parser("show", help="one run with metrics, assertions, outcome and artifacts")
    show.add_argument("run_id")

    artifact = commands.add_parser("artifact", help="read one stored artifact")
    artifact.add_argument("run_id")
    artifact.add_argument("path")
    artifact.add_argument("--output", type=Path, default=None, help="write to this file instead of stdout")

    compare = commands.add_parser("compare", help="two runs of one diagnostic, metric by metric")
    compare.add_argument("baseline_run_id")
    compare.add_argument("candidate_run_id")

    sweep = commands.add_parser("sweep", help="execute a parameter sweep and report its points")
    sweep.add_argument("diagnostic_id", nargs="?", default=None)
    sweep.add_argument("--spec", type=Path, default=None, help="a jarvis.testlab.sweep JSON document")
    sweep.add_argument("--profile", default=ProfileName.VIRTUAL.value,
                       choices=[item.value for item in ProfileName])
    sweep.add_argument("--version", type=int, default=None)
    sweep.add_argument("--axis", action="append", metavar="NAME=V1,V2",
                       help="swept axis; prefix with override: to sweep a setting (repeatable)")
    sweep.add_argument("-p", "--parameter", action="append", metavar="NAME=VALUE")
    sweep.add_argument("-o", "--override", action="append", metavar="NAME=VALUE")
    sweep.add_argument("--repetitions", type=int, default=1)
    sweep.add_argument("--title", default=None)

    sweeps = commands.add_parser("sweeps", help="stored sweeps, or one with --id")
    sweeps.add_argument("--id", default=None, dest="sweep_id")
    sweeps.add_argument("--limit", type=int, default=20)

    capture = commands.add_parser("capture", help="normalize a real session into a DiagnosticBundle")
    capture.add_argument("--run", default=None, dest="run_id",
                         help="normalize a stored RUN's own trace instead of the live journal, "
                              "and reference the bundle from the run")
    capture.add_argument("--conversation-id", default=None)
    capture.add_argument("--session-id", default=None)
    capture.add_argument("--start", default=None, help="ISO-8601 instant, e.g. 2026-09-18T10:00:00Z")
    capture.add_argument("--end", default=None)
    capture.add_argument("--no-events", action="store_true", help="journal only, do not read Conversation Events")
    capture.add_argument("--no-store", action="store_true", help="build the bundle without storing it")

    bundles = commands.add_parser("bundles", help="stored DiagnosticBundles, or one with --id")
    bundles.add_argument("--id", default=None, dest="bundle_id")
    bundles.add_argument("--limit", type=int, default=20)
    bundles.add_argument("--document", action="store_true", help="with --id, print the whole bundle document")

    retention = commands.add_parser("retention", help="what retention would delete (nothing is deleted)")
    retention.add_argument("--apply", action="store_true", dest="apply_pass",
                           help="run one upkeep pass: stale temporaries, then retention")

    guided = commands.add_parser("guided", help="attach this terminal to a running guided run's prompts")
    guided.add_argument("run_id")
    guided.add_argument("--timeout", type=float, default=1800.0)
    guided.add_argument("--headless", action="store_true",
                        help="allow the presenter although stdin is not a terminal")
    return parser


# ------------------------------------------------------------------ rendering

def render_diagnostics(payload: Mapping[str, Any]) -> str:
    lines = [f"{len(payload['diagnostics'])} diagnostic(s)"]
    for entry in payload["diagnostics"]:
        profiles = ", ".join(f"{item['profile']}"
                             f"{'' if item['availability'] == 'available' else ' (no runner)'}"
                             for item in entry["profiles"])
        lines.append(f"  {entry['diagnostic_id']} v{entry['version']}  {entry['title']}")
        lines.append(f"      profiles: {profiles}")
    return "\n".join(lines)


def render_declaration(payload: Mapping[str, Any]) -> str:
    entry = payload["diagnostic"]
    lines = [f"{entry['diagnostic_id']} v{entry['version']} - {entry['title']}",
             f"  {entry['description']}",
             f"  versions: {', '.join(str(item) for item in payload['versions'])}",
             f"  fingerprint: {entry['diagnostic_fingerprint'][:16]}"]
    for profile in entry["profiles"]:
        requires = ", ".join(profile["requires"]) or "nothing"
        lines.append(f"  profile {profile['profile']}: requires {requires}, "
                     f"<= {profile['cost']['max_duration_s']:.0f} s, "
                     f"<= ${profile['cost']['max_cost_usd']:.2f}"
                     f"{'' if profile['availability'] == 'available' else '  [no runner registered]'}")
    for parameter in entry["parameters"]:
        lines.append(f"  parameter {parameter['name']} ({parameter['type']}, default {parameter['default']!r})")
    for metric in entry["metrics"]:
        lines.append(f"  metric {metric['name']} ({metric['unit']}, {metric['direction']})")
    for assertion in entry["assertions"]:
        mark = "blocking" if assertion["blocking"] else "informational"
        lines.append(f"  assertion {assertion['assertion_id']}: {assertion['metric']} "
                     f"{assertion['comparator']} {assertion['threshold']}  [{mark}]")
    return "\n".join(lines)


def render_run_line(view: Mapping[str, Any]) -> str:
    run, outcome = view["run"], view["outcome"]
    failure = f"  {outcome['failure_code']}" if outcome["failure_code"] else ""
    return (f"{run['run_id']}  {run['diagnostic_id']} v{run['diagnostic_version']} "
            f"[{run['profile']}]  {outcome['outcome']}{failure}")


def render_runs(payload: Mapping[str, Any]) -> str:
    lines = [f"{len(payload['runs'])} run(s)"]
    lines.extend(f"  {render_run_line(view)}" for view in payload["runs"])
    if payload["corrupt"]:
        lines.append(f"  !! {len(payload['corrupt'])} unreadable entr(y/ies): "
                     + ", ".join(f"{item['entry']} ({item['code']})" for item in payload["corrupt"]))
    if payload["next_cursor"]:
        lines.append(f"  next page: --after {payload['next_cursor']}")
    return "\n".join(lines)


def render_run_detail(view: Mapping[str, Any]) -> str:
    run, outcome = view["run"], view["outcome"]
    lines = [render_run_line(view),
             f"  status {run['status']}  verdict {outcome['verdict']}  score {outcome['score']}",
             f"  created {run['created_at']}  started {run['started_at']}  finished {run['finished_at']}"]
    if run["failure"]:
        lines.append(f"  failure {run['failure']['code']}: {run['failure']['detail']}")
    if run["metrics"]:
        lines.append("  metrics:")
        lines.extend(f"    {name} = {value}" for name, value in sorted(run["metrics"].items()))
    else:
        lines.append("  metrics: none recorded")
    if run["assertion_results"]:
        lines.append("  assertions:")
        for result in run["assertion_results"]:
            mark = "blocking" if result["blocking"] else "informational"
            lines.append(f"    {result['assertion_id']}: {result['outcome']} "
                         f"(observed {result['observed']}) [{mark}]")
    if outcome["failed_assertions"]:
        lines.append(f"  failed blocking assertions: {', '.join(outcome['failed_assertions'])}")
    if outcome["missing_assertions"]:
        lines.append(f"  never measured: {', '.join(outcome['missing_assertions'])}")
    artifacts = view.get("artifacts") or run["artifacts"]
    lines.append(f"  artifacts ({len(artifacts)}):")
    lines.extend(f"    {item['path']}  {item['kind']}  {item['size_bytes']} B" for item in artifacts)
    if "declaration" in view and view["declaration"] is None:
        lines.append("  declaration: not in this catalog (an ad-hoc or withdrawn diagnostic)")
    return "\n".join(lines)


def render_comparison(payload: Mapping[str, Any]) -> str:
    lines = [f"{payload['baseline_run_id']} -> {payload['candidate_run_id']}",
             f"  {payload['baseline_outcome']} -> {payload['candidate_outcome']}"
             f"  (comparable: {payload['comparable']})"]
    for delta in payload["metrics"]:
        lines.append(f"  {delta['metric']}: {delta['baseline']} -> {delta['candidate']} "
                     f"({delta['change']}, delta {delta['delta']})")
    for change in payload["assertions"]:
        if change["change"] != "unchanged":
            lines.append(f"  assertion {change['assertion_id']}: {change['baseline']} -> "
                         f"{change['candidate']} ({change['change']})")
    for item in payload["incomparable"]:
        lines.append(f"  !! incomparable {item['subject']}: {item['reason']} - {item['detail']}")
    for item in payload["differences"]:
        lines.append(f"  differs: {item['field']}")
    return "\n".join(lines)


def render_sweep(payload: Mapping[str, Any]) -> str:
    record = payload["sweep"]
    lines = [f"{record['sweep_id']}  {record['spec']['diagnostic_id']} "
             f"[{record['spec']['profile']}]  {record['status']}"]
    for point in record["points"]:
        outcomes = ", ".join(run["outcome"] for run in point["runs"]) or "no run"
        failure = f"  failure {point['failure']['code']}" if point["failure"] else ""
        lines.append(f"  point {point['point']['index']} {point['point']['values']}: {outcomes}{failure}")
    summary = payload.get("summary")
    if summary:
        for best in summary.get("best_points", ()):
            lines.append(f"  best for {best['metric']} ({best['direction']}): "
                         f"point {best['point']}, median {best['median']}")
        lines.append(f"  {summary.get('note', '')}")
    return "\n".join(lines)


def render_sweeps(payload: Mapping[str, Any]) -> str:
    lines = [f"{len(payload['sweeps'])} sweep(s)"]
    lines.extend(f"  {record['sweep_id']}  {record['spec']['diagnostic_id']} "
                 f"[{record['spec']['profile']}]  {record['status']}" for record in payload["sweeps"])
    return "\n".join(lines)


def render_bundle(payload: Mapping[str, Any]) -> str:
    """One bundle, as the operator reads it: what was covered, and what the rules found.

    The two accessors here are the DOCUMENT's, not a guess at it (`docs/testlab.md`,
    "Coverage" and "Anomaly rules"): coverage is keyed by source at the top level, and a
    finding carries `rule_id` / `subject_kind` / `subject_id` / `measured`. Both were
    wrong until Slice 12 rework, which is why the line the runbook tells an operator to
    look for was never printed and why any session WITH a finding crashed the command.
    """
    bundle = payload["bundle"]
    lines = [f"{bundle['bundle_id']}  captured {bundle['captured_at']}",
             f"  session {bundle['started_at']} -> {bundle['ended_at']}",
             f"  conversations: {', '.join(bundle['conversation_ids']) or 'none'}",
             f"  sessions: {', '.join(bundle['session_ids']) or 'none'}",
             f"  findings: {bundle['finding_count']}"]
    if payload.get("stored") is not None:
        lines.append(f"  stored: {payload['stored']}")
    if payload.get("attached_bundle_id"):
        made = "now references" if payload.get("attached") else "already referenced"
        lines.append(f"  run {payload['run_id']} {made} {payload['attached_bundle_id']}")
    lines.extend(render_coverage(payload.get("coverage") or {}))
    lines.extend(f"  finding {_finding_line(item)}" for item in payload.get("findings", ()))
    return "\n".join(lines)


def render_coverage(coverage: Mapping[str, Any]) -> list[str]:
    """The source lines, plus the two facts that decide whether a bundle can be trusted.

    A source is an entry that carries a `status`; `content`, `limits`, `segments` and
    `warnings` are not sources and are reported on their own terms. Selecting by shape
    rather than by a hard-coded list means a source added later prints without a change
    here, and a document that is not a coverage document prints nothing instead of raising.
    """
    lines = []
    for name, entry in sorted(coverage.items()):
        if not isinstance(entry, Mapping) or "status" not in entry:
            continue
        reason = f" ({entry['reason']})" if entry.get("reason") else ""
        lines.append(f"  source {name}: {entry['status']}{reason}")
    segments = coverage.get("segments")
    if isinstance(segments, Mapping) and "count" in segments:
        lines.append(f"  voice sessions: {segments['count']}")
    warnings = coverage.get("warnings")
    if warnings:
        lines.append(f"  coverage warnings: {', '.join(str(item) for item in warnings)}")
    return lines


def _finding_line(finding: Mapping[str, Any]) -> str:
    """`<rule_id> on <subject_kind> <subject_id> at <at>  name=value, ...`."""
    measured = ", ".join(f"{item['name']}={item['value']}" for item in finding.get("measured", ())
                         if isinstance(item, Mapping) and "name" in item)
    subject = " ".join(str(finding[key]) for key in ("subject_kind", "subject_id") if finding.get(key))
    head = f"{finding['rule_id']} on {subject or 'the session'} at {finding['at']}"
    return f"{head}  {measured}" if measured else head


def render_bundles(payload: Mapping[str, Any]) -> str:
    lines = [f"{len(payload['bundles'])} bundle(s)"]
    lines.extend(f"  {item['bundle_id']}  captured {item['captured_at']}  "
                 f"{item['finding_count']} finding(s)" for item in payload["bundles"])
    return "\n".join(lines)


def render_status(payload: Mapping[str, Any]) -> str:
    config, contention = payload["config"], payload["contention"]
    grant = config["grant"]
    lines = [f"root {config['root']}",
             f"  work root {config['work_root']}   catalog {config['catalog_root']}",
             f"  started: {payload['started']}   active {len(payload['active_runs'])}   "
             f"queued {len(payload['pending_runs'])}   sweeps {len(payload['active_sweeps'])}",
             f"  granted capabilities: {', '.join(grant['capabilities']) or 'none'} "
             f"(budget ${grant['max_cost_usd']:.2f} per run)",
             "  opt-ins: " + ", ".join(f"{name}={'on' if value else 'off'}"
                                       for name, value in sorted(config["opt_ins"].items())),
             f"  audio devices: {contention['state']} - {contention['reason']}",
             f"  storage: {payload['storage']['runs']} run(s), "
             f"{payload['storage']['total_bytes']} B, {payload['storage']['corrupt']} unreadable"]
    if config.get("grant_refusal"):
        # A grant quietly reduced is a surprise waiting to be blamed on the diagnostic.
        lines.append(f"  !! {config['grant_refusal']}")
    return "\n".join(lines)


def render_retention(payload: Mapping[str, Any]) -> str:
    if not payload["enabled"]:
        lines = ["retention is disabled: nothing would be deleted"]
    else:
        lines = [f"retention would delete {len(payload['deletions'])} run(s) "
                 f"(cutoff {payload['cutoff']}, {payload['deferred']} deferred)"]
        lines.extend(f"  {item['run_id']}: {item['reason']}" for item in payload["deletions"])
    if payload["blocked_active"]:
        lines.append(f"  {payload['blocked_active']} active run(s) are never deleted")
    if payload["blocked_corrupt"]:
        lines.append(f"  {len(payload['blocked_corrupt'])} unreadable entr(y/ies) are kept as evidence")
    if payload["unmet"]:
        lines.append(f"  bounds still exceeded afterwards: {', '.join(payload['unmet'])}")
    lines.extend(_archive_plan_lines(payload.get("archive")))
    return "\n".join(lines)


def _archive_plan_lines(archive: Mapping[str, Any] | None) -> list[str]:
    """The `sweeps/` and `bundles/` half of the plan, which has bounds of its own."""
    if archive is None:
        return []
    if not archive["enabled"]:
        return ["sweeps and bundles: retention is disabled, nothing would be deleted"]
    lines = [f"sweeps and bundles: would delete {len(archive['deletions'])} entr(y/ies) "
             f"({archive['deferred']} deferred)"]
    lines.extend(f"  {item['kind']} {item['entry_id']}: {item['reason']}" for item in archive["deletions"])
    if archive["blocked_active"]:
        lines.append(f"  {archive['blocked_active']} running sweep(s) are never deleted")
    if archive["blocked_referenced"]:
        lines.append(f"  {archive['blocked_referenced']} entr(y/ies) a stored run points at are never deleted")
    if archive["blocked_corrupt"]:
        lines.append(f"  {len(archive['blocked_corrupt'])} unreadable entr(y/ies) are kept as evidence")
    if archive["unmet"]:
        lines.append(f"  bounds still exceeded afterwards: {', '.join(archive['unmet'])}")
    return lines


def render_maintenance(payload: Mapping[str, Any]) -> str:
    if not payload["ran"]:
        return f"no upkeep pass ran: {payload['reason']}"
    lines = [f"upkeep pass: {payload['swept']} stale temporary file(s) removed, "
             f"{len(payload['deleted'])} run(s) deleted"]
    if payload["sweep_error"]:
        lines.append(f"  !! the sweep half failed: {payload['sweep_error']}")
    for failure in payload["delete_failures"]:
        lines.append(f"  !! {failure['run_id']}: {failure['code']}")
    archive = payload.get("archive")
    if archive and archive["ran"]:
        lines.append(f"  sweeps and bundles: {len(archive['deleted'])} entr(y/ies) deleted")
        lines.extend(f"  !! {item['kind']} {item['entry_id']}: {item['code']}"
                     for item in archive["delete_failures"])
    return "\n".join(lines)


def render_adoption(payload: Mapping[str, Any]) -> str | None:
    """What the supervisor found left behind, or None when it found nothing."""
    total = (len(payload["reaped"]) + len(payload["recovered"]) + len(payload["active_elsewhere"])
             + len(payload["failed"]) + payload["scratch_removed"])
    if not total:
        return None
    return (f"adopted from a previous supervisor: {len(payload['reaped'])} reaped, "
            f"{len(payload['recovered'])} recovered, {len(payload['active_elsewhere'])} owned elsewhere, "
            f"{len(payload['failed'])} could not be finished, {payload['scratch_removed']} scratch removed")


# -------------------------------------------------------------------- output

class Console:
    """Where the two streams go: the report on stdout, everything live on stderr.

    It owns its own cursor. `tick()` redraws one line in place; any durable line closes
    that line first, so a countdown never eats the header above it and never leaves a
    half-written line behind.
    """

    def __init__(self, *, as_json: bool, out=None, err=None) -> None:
        self.as_json = as_json
        self._out = out if out is not None else sys.stdout
        self._err = err if err is not None else sys.stderr
        self._ticking = False

    def report(self, payload: Any, text: str | None) -> None:
        self.end_tick()
        if self.as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str), file=self._out)
        elif text:
            print(text, file=self._out)

    def note(self, text: str | None) -> None:
        """A durable line for the human, never part of the parseable output."""
        if not text:
            return
        self.end_tick()
        print(text, file=self._err, flush=True)

    def tick(self, text: str) -> None:
        """Redraw the live line in place (a plain line when stderr is not a terminal)."""
        if not self._interactive():
            print(text, file=self._err, flush=True)
            return
        print(f"\r{text}", end="", file=self._err, flush=True)
        self._ticking = True

    def end_tick(self) -> None:
        """Close an in-place line, so the next durable line starts on its own row."""
        if self._ticking:
            self._ticking = False
            print("", file=self._err, flush=True)

    def _interactive(self) -> bool:
        try:
            return bool(self._err.isatty())
        except (AttributeError, OSError, ValueError):
            # Captured, argued: a stream we cannot interrogate is not a terminal to draw
            # on, and appending plain lines is the readable fallback.
            return False

    def buffer(self):
        return getattr(self._out, "buffer", None)


# ------------------------------------------------------------------ commands

async def _wait_for_run(api: TestLabApi, run_id: str, *, timeout_s: float, console: Console,
                        clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """Wait for a terminal record, showing what it is doing and how long it has been doing it.

    The wait has a deadline it cannot outlive: when `timeout_s` passes, the run is left
    alone (the supervisor owns its own bounds) and the current record is returned, so the
    caller reports `pending` rather than hanging.
    """
    started = clock()
    tick = 0
    try:
        while True:
            view = await api.get_run(run_id, wait_s=PROGRESS_TICK_S)
            status = view["run"]["status"]
            elapsed = clock() - started
            if status in {item.value for item in TERMINAL_STATUSES}:
                console.end_tick()
                return view
            if elapsed >= timeout_s:
                console.end_tick()
                console.note(f"  !! still {status} after {elapsed:.0f} s (waited the {timeout_s:.0f} s asked for); "
                             f"the run keeps going - follow it with `status {run_id}`")
                return view
            console.tick(f"  {SPINNER[tick % len(SPINNER)]} {status} - {elapsed:5.1f} s "
                         f"of at most {timeout_s:.0f} s   (Ctrl-C stops the run)")
            tick += 1
    except KeyboardInterrupt:
        console.end_tick()
        console.note("  interrupted: asking the run to stop...")
        await api.cancel_run(run_id, reason="interrupted at the terminal")
        return await api.get_run(run_id, wait_s=PROGRESS_TICK_S * 5)


async def _run_command(api: TestLabApi, args: argparse.Namespace, console: Console) -> tuple[int, Any, str | None]:
    # `preflight` already refused what the command line alone could be wrong about
    # (including the guided tty rule) before this process composed anything. What is left
    # needs the catalog or the disk, and both are asked BEFORE the work root is taken, so
    # an unknown diagnostic or an unreadable scenario file leaves no lock behind.
    scenario = json.loads(args.scenario.read_text(encoding="utf-8")) if args.scenario else None
    await api.check_run_request(args.diagnostic_id, args.profile, version=args.version, scenario=scenario)
    await _take_work_root(api, console)
    # The supervisor re-describes and remains the authority; the call above only moves the
    # refusal of a name nobody published to before anything was created.
    submitted = await api.submit_run(
        args.diagnostic_id, args.profile, version=args.version,
        parameters=parse_assignments(args.parameter, "--parameter"),
        overrides=parse_assignments(args.override, "--override"),
        scenario=scenario, bundle_id=args.bundle_id,
        allow_audio_artifacts=args.allow_audio_artifacts)
    run_id = submitted["run_id"]
    console.note(f"  queued {run_id}")
    if args.no_wait:
        return EXIT_PENDING, submitted, f"queued {run_id}"
    if args.guided:
        return await _run_with_presenter(api, run_id, args, console)
    await _wait_for_run(api, run_id, timeout_s=args.timeout, console=console)
    detail = await api.show_run(run_id)
    return _exit_for(detail), detail, render_run_detail(detail)


def _stdin_isatty() -> bool:
    """Is stdin a terminal? False when it cannot be asked (a detached or closed stream)."""
    try:
        return bool(sys.stdin.isatty())
    except (AttributeError, OSError, ValueError):
        # Captured, argued: a stdin we cannot even interrogate is certainly not a terminal
        # somebody is typing into, and `False` is the refusing direction.
        return False


def check_presenter_input(args: argparse.Namespace, *, isatty: bool) -> None:
    """Refuse to attach a presenter where nobody can answer it.

    With stdin at end of file — a script, a pipe, CI — every prompt would be answered
    the instant it appeared, and the run would record that a human performed steps
    nobody performed. That is the one claim a guided run exists to make, so the refusal
    is here and not a warning. `--headless` is the operator saying they are feeding the
    answers in deliberately.
    """
    if presenter_input_available(isatty, getattr(args, "headless", False)):
        return
    raise TestLabCliError(
        "stdin is not a terminal, so nobody can answer the guided prompts; a presenter here "
        "would confirm every step in a human's name. Run this from a terminal, or pass "
        "--headless if you are feeding the answers in on purpose.")


async def _run_with_presenter(api: TestLabApi, run_id: str, args: argparse.Namespace,
                              console: Console) -> tuple[int, Any, str | None]:
    """Wait for the run while this terminal answers its guided prompts."""
    stop = asyncio.Event()
    presenter = GuidedPresenter(api.prompt_watcher(run_id), write=console.note,
                                write_live=console.tick)
    presenting = asyncio.ensure_future(presenter.serve(stop))
    console.note("  guided: prompts will appear here. [Enter] confirms a step, [r] refuses it.")
    try:
        await _wait_for_run(api, run_id, timeout_s=args.timeout, console=console)
    finally:
        stop.set()
        answers = await presenting
    detail = await api.show_run(run_id)
    detail["prompts"] = [answer.to_dict() for answer in answers]
    return _exit_for(detail), detail, render_run_detail(detail)


async def _guided_command(api: TestLabApi, args: argparse.Namespace,
                          console: Console) -> tuple[int, Any, str | None]:
    """Attach this terminal to a run somebody else started (the Control Center, a script)."""
    view = await api.get_run(args.run_id)
    if view["run"]["status"] in {item.value for item in TERMINAL_STATUSES}:
        return EXIT_ERROR, view, f"run {args.run_id} is already {view['run']['status']}: no prompt will come"
    await _take_work_root(api, console)
    stop = asyncio.Event()
    presenter = GuidedPresenter(api.prompt_watcher(args.run_id), write=console.note,
                                write_live=console.tick)
    presenting = asyncio.ensure_future(presenter.serve(stop))
    try:
        await _wait_for_run(api, args.run_id, timeout_s=args.timeout, console=console)
    finally:
        stop.set()
        answers = await presenting
    detail = await api.show_run(args.run_id)
    detail["prompts"] = [answer.to_dict() for answer in answers]
    return _exit_for(detail), detail, render_run_detail(detail)


async def _sweep_command(api: TestLabApi, args: argparse.Namespace,
                         console: Console) -> tuple[int, Any, str | None]:
    if args.spec is not None:
        spec = SweepSpec.from_dict(json.loads(args.spec.read_text(encoding="utf-8")))
    else:
        if not args.diagnostic_id:
            raise TestLabCliError("sweep needs a diagnostic id or --spec")
        spec = SweepSpec(diagnostic_id=args.diagnostic_id, profile=ProfileName(args.profile),
                         version=args.version, parameters=parse_assignments(args.parameter, "--parameter"),
                         overrides=parse_assignments(args.override, "--override"),
                         swept=tuple(parse_axis(item) for item in (args.axis or ())),
                         repetitions=args.repetitions, title=args.title)
    await api.describe(spec.diagnostic_id, spec.version)
    console.note(f"  sweeping {spec.point_count} point(s), {spec.run_count} run(s) - this can take minutes")
    await _take_work_root(api, console)
    payload = await api.run_sweep(spec)
    return SWEEP_EXIT.get(payload["sweep"]["status"], EXIT_FAILED), payload, render_sweep(payload)


async def _capture_command(api: TestLabApi, args: argparse.Namespace,
                           console: Console) -> tuple[int, Any, str | None]:
    if args.run_id is not None:
        if args.conversation_id or args.start or args.end:
            raise TestLabCliError("--run normalizes that run's own trace, so it takes no session window. "
                                  "Use --session-id alone to pick one of its voice sessions.")
        console.note(f"  reading the stored trace of {args.run_id}...")
        payload = await api.capture_run_bundle(args.run_id, session_id=args.session_id,
                                               store=not args.no_store)
        return EXIT_OK, payload, render_bundle(payload)
    selector = SessionSelector(conversation_id=args.conversation_id, session_id=args.session_id,
                               start=parse_time_argument(args.start, "--start"),
                               end=parse_time_argument(args.end, "--end"))
    console.note("  reading the journal and the Conversation Events (bounded)...")
    payload = await api.capture_bundle(selector, with_events=not args.no_events, store=not args.no_store)
    return EXIT_OK, payload, render_bundle(payload)


async def _artifact_command(api: TestLabApi, args: argparse.Namespace,
                            console: Console) -> tuple[int, Any, str | None]:
    data, ref = await api.read_artifact(args.run_id, args.path)
    if args.output is not None:
        args.output.write_bytes(data)
        return EXIT_OK, {"artifact": ref, "path": str(args.output)}, f"wrote {len(data)} B to {args.output}"
    if console.as_json:
        return EXIT_OK, {"artifact": ref, "text": data.decode("utf-8", errors="replace")}, None
    stream = console.buffer()
    if stream is None:
        return EXIT_OK, {"artifact": ref}, data.decode("utf-8", errors="replace")
    stream.write(data)
    stream.flush()
    return EXIT_OK, {"artifact": ref}, None


async def _dispatch(api: TestLabApi, args: argparse.Namespace, console: Console) -> tuple[int, Any, str | None]:
    command = args.command
    if command == "list":
        payload = await api.list_diagnostics()
        return EXIT_OK, payload, render_diagnostics(payload)
    if command == "describe":
        payload = await api.describe(args.diagnostic_id, args.version)
        return EXIT_OK, payload, render_declaration(payload)
    if command == "run":
        return await _run_command(api, args, console)
    if command == "status" and args.run_id:
        view = await api.get_run(args.run_id)
        return _exit_for(view), view, render_run_detail(view)
    if command == "status":
        payload = await api.status()
        return EXIT_OK, payload, render_status(payload)
    if command == "cancel":
        # The store answers "is there such a run" without any lock; only then the work root.
        await api.get_run(args.run_id)
        await _take_work_root(api, console)
        payload = await api.cancel_run(args.run_id, reason=args.reason)
        text = (f"asked {args.run_id} to stop" if payload["held"]
                else f"{args.run_id} is {payload['status']} and is not held by this supervisor")
        return (EXIT_OK if payload["held"] else EXIT_ERROR), payload, text
    if command == "runs":
        payload = await api.query_runs(
            diagnostic_id=args.diagnostic_id, diagnostic_version=args.diagnostic_version,
            profile=args.profile, statuses=args.statuses, sweep_id=args.sweep_id, bundle_id=args.bundle_id,
            limit=args.limit, newest_first=not args.oldest_first, after_run_id=args.after_run_id)
        return EXIT_OK, payload, render_runs(payload)
    if command == "show":
        view = await api.show_run(args.run_id)
        return _exit_for(view), view, render_run_detail(view)
    if command == "artifact":
        return await _artifact_command(api, args, console)
    if command == "compare":
        payload = await api.compare(args.baseline_run_id, args.candidate_run_id)
        return EXIT_OK, payload, render_comparison(payload)
    if command == "sweep":
        return await _sweep_command(api, args, console)
    if command == "sweeps" and args.sweep_id:
        payload = await api.get_sweep(args.sweep_id)
        return EXIT_OK, payload, render_sweep(payload)
    if command == "sweeps":
        payload = await api.list_sweeps(limit=args.limit)
        return EXIT_OK, payload, render_sweeps(payload)
    if command == "capture":
        return await _capture_command(api, args, console)
    if command == "bundles" and args.bundle_id:
        payload = await api.get_bundle(args.bundle_id, document=args.document)
        return EXIT_OK, payload, render_bundle(payload)
    if command == "bundles":
        payload = await api.list_bundles(limit=args.limit)
        return EXIT_OK, payload, render_bundles(payload)
    if command == "retention" and args.apply_pass:
        await _take_work_root(api, console)
        payload = await api.maintain()
        return EXIT_OK, payload, render_maintenance(payload)
    if command == "retention":
        payload = await api.retention_plan()
        return EXIT_OK, payload, render_retention(payload)
    if command == "guided":
        return await _guided_command(api, args, console)
    raise TestLabCliError(f"unknown command {command!r}")


def _exit_for(view: Mapping[str, Any]) -> int:
    return OUTCOME_EXIT[RunOutcomeClass(view["outcome"]["outcome"])]


def preflight(args: argparse.Namespace) -> None:
    """Every refusal the COMMAND LINE alone justifies, before a Test Lab is composed.

    Pure: it reads the namespace and `sys.stdin.isatty()`, nothing else. It exists because
    order is part of the contract — a command that refuses must not have created
    `<runtime>/testlab/`, and must not have held the work-root lock for even the moment it
    took to refuse, on a machine where the Test Lab may never have been used.

    What stays later, and why: an unknown diagnostic, an unsupported profile and an
    unknown run id are questions for the catalog and the store, which `_take_work_root`
    is careful to ask before taking anything (`_run_command`, `_sweep_command`).
    """
    if args.command in ("run", "sweep"):
        parse_assignments(getattr(args, "parameter", None), "--parameter")
        parse_assignments(getattr(args, "override", None), "--override")
    if args.command == "sweep":
        for item in getattr(args, "axis", None) or ():
            parse_axis(item)
    if args.command == "guided" or (args.command == "run" and args.guided and not args.no_wait):
        check_presenter_input(args, isatty=_stdin_isatty())


async def _take_work_root(api: TestLabApi, console: Console) -> None:
    """Start the supervisor, as late as the command allows.

    Called by the commands that execute something, AFTER their own checks, so a refusal
    never leaves a lock or a directory behind.
    """
    console.note(render_adoption(await api.start()))


# ---------------------------------------------------------------- entry point

def _usage_refusal(console: Console, reason: object) -> int:
    """Exit 2, with the same refusal DOCUMENT every other failure produces under `--json`.

    An agent that branches on a JSON payload must not get nothing on stdout for one class
    of failure. (`argparse`'s own exit 2 — an unknown flag, a missing positional — is
    printed by argparse before this program runs, and stays a usage message on stderr.)
    """
    console.note(f"{PROGRAM}: {reason}")
    console.report({"ok": False, "code": CLI_USAGE, "error": str(reason)}, None)
    return EXIT_USAGE


async def run_cli(args: argparse.Namespace, console: Console, *, api: TestLabApi | None = None) -> int:
    """Compose the Test Lab, run one command, and always close what was started.

    This is the failure boundary, not `main()`: every caller — the module entry point and
    the tests — gets the same exit code and the same sentence for the same failure. No
    exception escapes with a bare traceback, and no failure is collapsed into a generic
    "command failed": the stable code is what an agent branches on.
    """
    try:
        # FIRST, before a Test Lab exists at all: everything the command line alone can
        # be wrong about. A command that is going to refuse must not have created a
        # directory or taken the work-root lock on the way to refusing.
        preflight(args)
    except TestLabCliError as exc:
        return _usage_refusal(console, exc)
    owned = api is None
    if api is None:
        api = TestLabApi(build_test_lab(runtime_root=args.runtime_root, data_root=args.data_root))
    try:
        # A grant the environment asked for and did not get is said out loud, once, before
        # anything runs: a run refused for a capability nobody knows was dropped reads as
        # a defect of the diagnostic.
        console.note(None if api.lab.config.grant_refusal is None
                     else f"  !! {api.lab.config.grant_refusal}")
        code, payload, text = await _dispatch(api, args, console)
        console.report(payload, text)
        return code
    except TestLabCliError as exc:
        return _usage_refusal(console, exc)
    except TestLabError as exc:
        console.note(f"{PROGRAM}: {exc.code}: {exc.detail}")
        console.report({"ok": False, "code": exc.code, "error": exc.detail}, None)
        return EXIT_ERROR
    except FileNotFoundError as exc:
        console.note(f"{PROGRAM}: file not found: {exc.filename}")
        return EXIT_ERROR
    except json.JSONDecodeError as exc:
        return _usage_refusal(console, f"not a JSON document: {exc}")
    except Exception as exc:  # noqa: BLE001 - this IS the boundary
        # Anything we did not foresee is OUR defect, and it exits 7 ("the command
        # failed"), never 1 ("the run failed"): an agent branches on that difference.
        # The traceback goes to the live stream, where it can be read and pasted.
        console.note(f"{PROGRAM}: unexpected failure: {type(exc).__name__}: {exc}")
        console.note(traceback.format_exc())
        console.report({"ok": False, "code": CLI_FAILED, "error": CLI_FAILED_MESSAGE}, None)
        return EXIT_ERROR
    finally:
        if owned:
            await api.aclose()


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the command line and run it. Every other failure is handled by `run_cli`."""
    parser = build_parser()
    args = parser.parse_args(argv)
    console = Console(as_json=args.json)
    try:
        return asyncio.run(run_cli(args, console))
    except KeyboardInterrupt:
        console.note(f"{PROGRAM}: interrupted")
        return EXIT_CANCELLED
