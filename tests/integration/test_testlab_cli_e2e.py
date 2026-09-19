"""Slice 10 end to end: `python -m jarvis.testlab` against real worker processes.

Contract: `docs/testlab.md` ("Native API, CLI and HTTP"). The fixture diagnostic is
`selftest.worker` (Slice 05): no voice stack, no provider, no device, one short process
per run. Bounded on purpose — this host has little free RAM — so every test runs at most
two workers, one at a time, and every supervisor is closed in a `finally`.

What is proven here is the whole chain a caller actually uses: the command line, the
facade, the supervisor, a real worker, the store, and the exit code that comes back.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
import io
import json
from pathlib import Path
import queue

import pytest

from jarvis.testlab.api import TestLabApi
from jarvis.testlab.cli import (
    CLI_FAILED,
    CLI_FAILED_MESSAGE,
    EXIT_CANCELLED,
    EXIT_ERROR,
    EXIT_FAILED,
    EXIT_OK,
    EXIT_PENDING,
    EXIT_USAGE,
    Console,
    build_parser,
    needs_supervisor,
    run_cli,
)
from jarvis.testlab.composition import TestLab, TestLabConfig
from jarvis.testlab.hardware.channel import FilePrompter
from jarvis.testlab.hardware.prompts import GuidedAction, GuidedPrompt
from jarvis.testlab.maintenance import MaintenancePolicy
from jarvis.testlab.presenter import GuidedPresenter
from jarvis.testlab.retention import TestLabRetentionPolicy
from jarvis.testlab.runs import TERMINAL_STATUSES
from jarvis.testlab.selftest import SELFTEST_DIAGNOSTIC_ID, SelfTestMode, write_selftest_catalog
from jarvis.testlab.supervisor import SupervisorPolicy
from jarvis.testlab.sweep_runner import SweepPolicy

#: Real interpreter startup plus a catalog load. Generous, still seconds.
STARTUP_TIMEOUT_S = 60.0
RUN_TIMEOUT_S = 120.0


class Recorder(Console):
    """A console whose two streams a test can read apart."""

    def __init__(self, *, as_json: bool = False) -> None:
        self.out, self.err = io.StringIO(), io.StringIO()
        super().__init__(as_json=as_json, out=self.out, err=self.err)

    @property
    def report_text(self) -> str:
        return self.out.getvalue()

    @property
    def live_text(self) -> str:
        return self.err.getvalue()

    def payload(self) -> dict:
        return json.loads(self.out.getvalue())


@pytest.fixture
def lab(tmp_path) -> TestLab:
    """A Test Lab over a temp root, with the Slice 05 fixture catalog and one worker at a time."""
    catalog = write_selftest_catalog(tmp_path / "catalog", max_duration_s=60.0)
    root = tmp_path / "runtime" / "testlab"
    config = TestLabConfig(
        root=root, work_root=root / "work", runtime_root=tmp_path / "runtime", data_root=tmp_path / "data",
        catalog_root=catalog,
        policy=SupervisorPolicy(max_concurrent_runs=1, startup_timeout_s=STARTUP_TIMEOUT_S,
                                heartbeat_timeout_s=30.0, cancel_grace_s=3.0, poll_interval_s=0.05,
                                maintenance=MaintenancePolicy(enabled=False)),
        sweep_policy=SweepPolicy(max_in_flight=1, run_timeout_s=RUN_TIMEOUT_S))
    return TestLab(config)


@pytest.fixture
async def api(lab) -> TestLabApi:
    facade = TestLabApi(lab)
    try:
        yield facade
    finally:
        await facade.aclose()


async def invoke(api: TestLabApi, *argv: str, as_json: bool = False) -> tuple[int, Recorder]:
    """One command line, through exactly the entry point `main()` uses."""
    console = Recorder(as_json=as_json)
    args = build_parser().parse_args(list(argv))
    return await run_cli(args, console, api=api), console


def run_argv(mode: SelfTestMode | str = SelfTestMode.MEASURE, **parameters) -> list[str]:
    argv = ["run", SELFTEST_DIAGNOSTIC_ID, "--timeout", str(RUN_TIMEOUT_S),
            "-p", f"mode={SelfTestMode(mode).value}"]
    for name, value in parameters.items():
        argv += ["-p", f"{name}={json.dumps(value)}"]
    return argv


async def wait_terminal(api: TestLabApi, run_id: str, *, timeout_s: float = RUN_TIMEOUT_S) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        view = await api.get_run(run_id, wait_s=1.0)
        if view["run"]["status"] in {item.value for item in TERMINAL_STATUSES}:
            return view
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"run {run_id} never became terminal")


# --------------------------------------------------------------- read paths

async def test_list_and_describe_read_the_catalog_without_taking_the_work_root(api, lab):
    code, console = await invoke(api, "list")
    assert code == EXIT_OK and SELFTEST_DIAGNOSTIC_ID in console.report_text
    assert lab.started is False, "a read command must not take the supervisor's work root"

    code, console = await invoke(api, "describe", SELFTEST_DIAGNOSTIC_ID)
    assert code == EXIT_OK
    assert "value_is_zero" in console.report_text and "selftest.value" in console.report_text


async def test_an_unknown_diagnostic_reports_its_code_and_exits_seven(api):
    code, console = await invoke(api, "describe", "voice.nope")
    assert code == EXIT_ERROR
    assert "testlab_catalog_not_found" in console.live_text and "voice.nope" in console.live_text


async def test_json_output_is_the_documented_shape_on_stdout_alone(api):
    code, console = await invoke(api, "list", as_json=True)
    assert code == EXIT_OK
    payload = console.payload()
    assert {item["diagnostic_id"] for item in payload["diagnostics"]} == {SELFTEST_DIAGNOSTIC_ID}
    entry = payload["diagnostics"][0]
    assert {"profiles", "parameters", "metrics", "assertions", "diagnostic_fingerprint"} <= set(entry)


# ---------------------------------------------------------------- one run

async def test_a_passing_run_exits_zero_and_its_report_names_what_it_measured(api):
    """One worker process: queue -> running -> passed, reported and exit 0."""
    code, console = await invoke(api, *run_argv(value=0))
    assert code == EXIT_OK, console.live_text
    assert "selftest.value = 0" in console.report_text
    assert "value_is_zero: passed" in console.report_text
    assert "worker.log" in console.report_text
    # RULE ZERO: the caller saw the id and a live line, not a silent wait.
    assert "queued tlr-" in console.live_text


async def test_a_failing_run_exits_one_and_names_the_blocking_assertion(api):
    code, console = await invoke(api, *run_argv(value=7))
    assert code == EXIT_FAILED, console.live_text
    assert "failed blocking assertions: value_is_zero" in console.report_text


async def test_show_and_artifact_read_back_what_the_run_stored(api):
    code, console = await invoke(api, *run_argv(value=0), as_json=True)
    assert code == EXIT_OK
    run_id = console.payload()["run"]["run_id"]

    code, console = await invoke(api, "show", run_id, as_json=True)
    assert code == EXIT_OK
    detail = console.payload()
    assert detail["outcome"]["outcome"] == "passed"
    assert detail["declaration"]["diagnostic_id"] == SELFTEST_DIAGNOSTIC_ID
    assert {"config_snapshot.json", "worker.log"} <= {item["path"] for item in detail["artifacts"]}

    code, console = await invoke(api, "artifact", run_id, "worker.log", as_json=True)
    assert code == EXIT_OK and "selftest done" in console.payload()["text"]

    code, console = await invoke(api, "artifact", run_id, "nope.txt")
    assert code == EXIT_ERROR and "no artifact" in console.live_text


async def test_no_wait_returns_the_id_and_exits_pending(api):
    code, console = await invoke(api, *run_argv(SelfTestMode.SLEEP, sleep_ms=1500), "--no-wait", as_json=True)
    assert code == EXIT_PENDING
    run_id = console.payload()["run_id"]
    view = await wait_terminal(api, run_id)
    assert view["outcome"]["outcome"] == "passed"


async def test_status_without_a_run_id_describes_the_lab_itself(api):
    code, console = await invoke(api, "status", as_json=True)
    assert code == EXIT_OK
    payload = console.payload()
    assert payload["config"]["grant"]["capabilities"] == [], "the default grant is empty"
    assert payload["config"]["opt_ins"] == {"JARVIS_TESTLAB_LIVE": False, "JARVIS_TESTLAB_HARDWARE": False,
                                            "JARVIS_TESTLAB_GUIDED": False}


# ------------------------------------------------------------- cancellation

async def test_cancelling_a_running_run_ends_it_cancelled(api):
    """One worker, stopped cooperatively: the record is terminal and the outcome is `cancelled`."""
    code, console = await invoke(api, *run_argv(SelfTestMode.SLEEP, sleep_ms=60000), "--no-wait", as_json=True)
    assert code == EXIT_PENDING
    run_id = console.payload()["run_id"]
    deadline = asyncio.get_running_loop().time() + STARTUP_TIMEOUT_S
    while (await api.get_run(run_id))["run"]["status"] != "running":
        assert asyncio.get_running_loop().time() < deadline, "the worker never started"
        await asyncio.sleep(0.1)

    code, console = await invoke(api, "cancel", run_id)
    assert code == EXIT_OK and "asked" in console.report_text
    view = await wait_terminal(api, run_id)
    assert view["outcome"]["outcome"] == "cancelled"

    code, console = await invoke(api, "show", run_id)
    assert code == EXIT_CANCELLED, "the exit code tells a cancelled run from a failed one"


async def test_cancelling_an_unknown_run_says_so_instead_of_pretending(api):
    code, console = await invoke(api, "cancel", "tlr-20260918T100000000Z-0123456789abcdef")
    assert code == EXIT_ERROR and "testlab_store_not_found" in console.live_text


# --------------------------------------------------------- query and compare

async def test_runs_query_and_compare_read_the_same_records(api):
    passed, _ = await invoke(api, *run_argv(value=0), as_json=True)
    assert passed == EXIT_OK
    code, console = await invoke(api, *run_argv(value=7), as_json=True)
    assert code == EXIT_FAILED
    failed_id = console.payload()["run"]["run_id"]

    code, console = await invoke(api, "runs", "--limit", "10", as_json=True)
    assert code == EXIT_OK
    page = console.payload()
    assert len(page["runs"]) == 2 and page["corrupt"] == []
    assert {view["outcome"]["outcome"] for view in page["runs"]} == {"passed", "failed"}
    baseline_id = next(view["run"]["run_id"] for view in page["runs"] if view["run"]["run_id"] != failed_id)

    code, console = await invoke(api, "compare", baseline_id, failed_id, as_json=True)
    assert code == EXIT_OK
    comparison = console.payload()
    assert comparison["comparable"] is True
    assert comparison["baseline_outcome"] == "passed" and comparison["candidate_outcome"] == "failed"
    delta = next(item for item in comparison["metrics"] if item["metric"] == "selftest.value")
    assert delta["baseline"] == 0 and delta["candidate"] == 7 and delta["change"] == "worse"
    change = next(item for item in comparison["assertions"] if item["assertion_id"] == "value_is_zero")
    assert change["change"] == "regressed"

    code, console = await invoke(api, "runs", "--status", "failed", as_json=True)
    assert [view["run"]["run_id"] for view in console.payload()["runs"]] == [failed_id]


# ------------------------------------------------------------------ sweeps

async def test_a_sweep_runs_every_point_and_reports_them(api):
    """Two points, one worker at a time, and a summary that names the best value."""
    code, console = await invoke(api, "sweep", SELFTEST_DIAGNOSTIC_ID, "--axis", "value=0,7",
                                 "-p", "mode=measure", as_json=True)
    assert code == EXIT_OK, console.live_text
    payload = console.payload()
    record = payload["sweep"]
    assert record["status"] == "completed" and len(record["points"]) == 2
    outcomes = [point["runs"][0]["outcome"] for point in record["points"]]
    assert outcomes == ["passed", "failed"]
    best = payload["summary"]["best_points"]
    assert best and {item["metric"] for item in best} >= {"selftest.value"}
    assert all({"metric", "direction", "point", "median"} <= set(item) for item in best)
    assert "never writes a winning value" in payload["summary"]["note"]

    sweep_id = record["sweep_id"]
    code, console = await invoke(api, "sweeps", as_json=True)
    assert code == EXIT_OK and [item["sweep_id"] for item in console.payload()["sweeps"]] == [sweep_id]

    code, console = await invoke(api, "runs", "--sweep-id", sweep_id, as_json=True)
    assert code == EXIT_OK and len(console.payload()["runs"]) == 2


async def test_a_sweep_never_writes_the_permanent_settings_file(api, lab, tmp_path):
    settings = lab.config.settings_path
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text('{"audio_input_device": 1}\n', encoding="utf-8")
    before = settings.read_bytes()
    code, _ = await invoke(api, "sweep", SELFTEST_DIAGNOSTIC_ID, "--axis", "value=0,1", as_json=True)
    assert code == EXIT_OK
    assert settings.read_bytes() == before, "a sweep wrote into the permanent settings"


# --------------------------------------------------------------- retention

async def test_retention_is_disabled_by_default_and_deletes_nothing(api):
    code, _ = await invoke(api, *run_argv(value=0))
    assert code == EXIT_OK
    code, console = await invoke(api, "retention", as_json=True)
    assert code == EXIT_OK
    plan = console.payload()
    assert plan["enabled"] is False and plan["deletions"] == []
    assert len((await api.query_runs(limit=10))["runs"]) == 1, "reading a plan deleted a run"


async def test_an_upkeep_pass_applies_the_plan_when_retention_is_enabled(lab):
    """Two runs, `max_runs=1`: one upkeep pass deletes the oldest and says which."""
    tight = TestLab(replace(lab.config, policy=replace(
        lab.config.policy, maintenance=MaintenancePolicy(
            enabled=True, retention=TestLabRetentionPolicy(enabled=True, max_runs=1)))))
    api = TestLabApi(tight)
    try:
        assert (await invoke(api, *run_argv(value=0)))[0] == EXIT_OK
        assert (await invoke(api, *run_argv(value=0)))[0] == EXIT_OK
        code, console = await invoke(api, "retention", as_json=True)
        assert code == EXIT_OK and len(console.payload()["deletions"]) == 1

        code, console = await invoke(api, "retention", "--apply", as_json=True)
        assert code == EXIT_OK
        report = console.payload()
        assert report["ran"] is True and len(report["deleted"]) == 1 and report["delete_failures"] == []
        assert len((await api.query_runs(limit=10))["runs"]) == 1
    finally:
        await api.aclose()


async def test_a_worker_that_dies_without_a_result_exits_crashed(api):
    """The Test Lab broke around the run: `5`, not `1`, so an agent does not read a verdict."""
    code, console = await invoke(api, *run_argv(SelfTestMode.CRASH))
    assert code == 5, console.report_text
    assert "worker_crashed" in console.report_text or "worker_crashed" in console.live_text


def test_the_module_entry_point_exists():
    """`python -m jarvis.testlab` is the documented entry point, not an `app.py` subcommand."""
    assert (Path(__file__).resolve().parents[2] / "jarvis" / "testlab" / "__main__.py").is_file()


# ------------------------------------------------- concurrency and interrupt

async def test_a_second_supervisor_on_the_same_work_root_is_refused_with_its_code(lab):
    """The Control Center and a CLI cannot both own one work root; the refusal says so."""
    holder = TestLabApi(lab)
    await holder.start()
    intruder = TestLabApi(TestLab(lab.config))
    try:
        code, console = await invoke(intruder, *run_argv(value=0))
        assert code == EXIT_ERROR
        assert "testlab_supervisor_work_root_busy" in console.live_text
        assert "another supervisor" in console.live_text
    finally:
        await intruder.aclose()
        await holder.aclose()


async def test_a_read_command_still_works_while_another_process_holds_the_work_root(lab):
    holder = TestLabApi(lab)
    await holder.start()
    reader = TestLabApi(TestLab(lab.config))
    try:
        code, console = await invoke(reader, "runs", as_json=True)
        assert code == EXIT_OK and console.payload()["runs"] == []
    finally:
        await reader.aclose()
        await holder.aclose()


async def test_an_interrupt_asks_the_run_to_stop_instead_of_abandoning_it(api, monkeypatch):
    """RULE ZERO's way out: Ctrl-C cancels the run, it does not orphan a worker."""
    calls = {"n": 0}
    real = api.get_run

    async def interrupt_on_the_second_poll(run_id, *, wait_s=None):
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt
        return await real(run_id, wait_s=wait_s)

    monkeypatch.setattr(api, "get_run", interrupt_on_the_second_poll)
    code, console = await invoke(api, *run_argv(SelfTestMode.SLEEP, sleep_ms=30000))
    assert "asking the run to stop" in console.live_text
    assert code == EXIT_CANCELLED, console.report_text


async def test_the_presenter_the_cli_attaches_reaches_the_real_run_scratch(api, lab):
    """The composition seam: `prompt_watcher(run_id)` is the worker's own prompt directory."""
    run_id = "tlr-20260918T100000000Z-0123456789abcdef"
    scratch = lab.config.work_root / run_id
    scratch.mkdir(parents=True)
    watcher = api.prompt_watcher(run_id)
    assert watcher.scratch == scratch

    prompter = FilePrompter(scratch, poll_interval_s=0.02)
    presenting = asyncio.ensure_future(prompter.present(GuidedPrompt(
        prompt_id="say_it", action=GuidedAction.SAY_PHRASE, text="Dites la phrase.",
        deadline_s=30.0, phrase="jarvis bonjour")))
    typed: queue.Queue[str] = queue.Queue()
    typed.put("\n")  # what readline() gives for a bare Enter
    stop = asyncio.Event()
    screen: list[str] = []
    presenter = GuidedPresenter(watcher, write=screen.append, read_line=typed.get,
                                tick_s=0.02, poll_interval_s=0.02)
    serving = asyncio.ensure_future(presenter.serve(stop))
    try:
        reply = await asyncio.wait_for(presenting, timeout=15)
    finally:
        stop.set()
        typed.put("")  # releases the reader thread so the loop can shut down
        answers = await asyncio.wait_for(serving, timeout=15)
    assert reply.acknowledged is True
    assert [item.prompt_id for item in answers] == ["say_it"]
    assert any("GUIDED STEP  say_it" in line for line in screen)
    assert any("s left of 30 s" in line for line in screen), "the countdown must be on screen"


# ------------------------------------ rework B2: nothing escapes the CLI boundary

async def test_an_unexpected_exception_exits_seven_and_never_one(api, monkeypatch):
    """Exit 1 means "the run failed" — a product verdict. Our own defect must not say that."""
    async def explode() -> dict:
        raise TypeError("a shape this command did not foresee")

    monkeypatch.setattr(api, "list_diagnostics", explode)
    code, console = await invoke(api, "list")
    assert code == EXIT_ERROR, "an unforeseen failure read as a product verdict"
    assert "unexpected failure: TypeError" in console.live_text
    assert "Traceback" in console.live_text, "the cause must be diagnosable"


async def test_an_unexpected_exception_still_produces_the_json_refusal_shape(api, monkeypatch):
    async def explode(*_, **__) -> dict:
        raise ZeroDivisionError("division by zero")

    monkeypatch.setattr(api, "query_runs", explode)
    code, console = await invoke(api, "runs", as_json=True)
    assert code == EXIT_ERROR
    payload = console.payload()
    assert payload == {"ok": False, "code": CLI_FAILED, "error": CLI_FAILED_MESSAGE}
    # The real cause is on stderr only: an agent forwarding the document carries no
    # exception text out of it (the same rule as the HTTP 500 boundary).
    assert "ZeroDivisionError: division by zero" not in console.report_text
    assert "ZeroDivisionError: division by zero" in console.live_text


async def test_the_supervisor_is_closed_even_when_a_command_explodes(lab, monkeypatch):
    """The `finally` must still release the work root, or the next process cannot start."""
    owner = TestLabApi(lab)

    async def explode(*_, **__) -> dict:
        raise RuntimeError("boom")

    monkeypatch.setattr(owner, "submit_run", explode)
    args = build_parser().parse_args(["run", SELFTEST_DIAGNOSTIC_ID, "--no-wait"])
    assert await run_cli(args, Recorder(), api=owner) == EXIT_ERROR
    await owner.aclose()
    # A second process can now take the work root, which proves the first released it.
    second = TestLabApi(TestLab(lab.config))
    try:
        assert (await second.start())["scratch_removed"] >= 0
    finally:
        await second.aclose()


# ---------------------------------- rework B1/S4: guided refusal, retention lock

async def test_guided_is_refused_before_anything_is_queued_when_stdin_is_not_a_terminal(api):
    """A refusal after the run started would leave it waiting out its whole budget."""
    code, console = await invoke(api, *run_argv(value=0), "--guided")
    assert code == EXIT_USAGE
    assert "not a terminal" in console.live_text and "--headless" in console.live_text
    assert (await api.query_runs(limit=10))["runs"] == [], "a run was queued for a presenter nobody reads"


async def test_headless_is_the_operator_saying_they_are_feeding_the_answers_in(api):
    """With `--headless` the run is queued; the presenter then answers nothing at EOF."""
    code, console = await invoke(api, *run_argv(value=0), "--guided", "--headless", "--timeout", "60")
    assert code == EXIT_OK, console.live_text
    assert console.report_text, "the run still reported"


async def test_applying_retention_owns_the_work_root_and_reading_the_plan_does_not(lab):
    holder = TestLabApi(lab)
    await holder.start()
    intruder = TestLabApi(TestLab(lab.config))
    try:
        code, console = await invoke(intruder, "retention", as_json=True)
        assert code == EXIT_OK and console.payload()["enabled"] is False

        code, console = await invoke(intruder, "retention", "--apply")
        assert code == EXIT_ERROR
        assert "testlab_supervisor_work_root_busy" in console.live_text
    finally:
        await intruder.aclose()
        await holder.aclose()


# ------------------------- rework 2: a refusal creates nothing and takes no lock

def untouched(lab: TestLab) -> bool:
    """Nothing of this Test Lab exists on disk: no store root, no work root, no lock."""
    return not lab.config.root.exists() and not lab.config.work_root.exists()


async def test_the_guided_refusal_creates_no_directory_and_takes_no_lock(api, lab):
    """It is a question about stdin; answering it must not build a work root first."""
    code, console = await invoke(api, *run_argv(value=0), "--guided")
    assert code == EXIT_USAGE and "not a terminal" in console.live_text
    assert untouched(lab), sorted(p.name for p in lab.config.root.rglob("*")) if lab.config.root.exists() else ()
    assert lab.started is False


@pytest.mark.parametrize("argv, code", [
    (["run", SELFTEST_DIAGNOSTIC_ID, "-p", "malformed"], EXIT_USAGE),
    (["run", "voice.nope"], EXIT_ERROR),
    # A profile the declaration does not offer is a CATALOG question, so it is asked before
    # the lock: `run voice.barge_in_response` takes `--profile virtual` by default and that
    # diagnostic is `hardware:guided` only. Refusing it after `_take_work_root` meant that,
    # with the Control Center running, the operator was told `work_root_busy` instead.
    (["run", SELFTEST_DIAGNOSTIC_ID, "--profile", "live"], EXIT_ERROR),
    (["run", SELFTEST_DIAGNOSTIC_ID, "--scenario", "no-such-file.json"], EXIT_ERROR),
    (["sweep", SELFTEST_DIAGNOSTIC_ID, "--axis", "malformed"], EXIT_USAGE),
    (["sweep", "voice.nope", "--axis", "value=1,2"], EXIT_ERROR),
    (["cancel", "tlr-20260918T100000000Z-0123456789abcdef"], EXIT_ERROR),
    (["guided", "tlr-20260918T100000000Z-0123456789abcdef", "--headless"], EXIT_ERROR),
])
async def test_a_command_that_refuses_leaves_the_disk_as_it_found_it(api, lab, argv, code):
    """A refused command must not litter a machine where the Test Lab was never used, and
    must not hold the work-root lock for even the moment it takes to refuse."""
    result, console = await invoke(api, *argv)
    assert result == code, console.live_text
    assert untouched(lab), f"{argv} created {lab.config.root}"
    assert lab.started is False


@pytest.mark.parametrize("argv", [["list"], ["describe", SELFTEST_DIAGNOSTIC_ID], ["runs"], ["sweeps"],
                                  ["bundles"], ["retention"], ["status"]])
async def test_a_read_command_never_creates_the_test_lab(api, lab, argv):
    result, console = await invoke(api, *argv)
    assert result == EXIT_OK, console.live_text
    assert untouched(lab), f"{argv} created {lab.config.root}"


async def test_the_declared_lock_set_matches_what_the_commands_actually_do(api, lab):
    """`NEEDS_SUPERVISOR` is a claim about behaviour; this checks it against behaviour."""
    for argv in (["list"], ["runs"], ["retention"], ["status"]):
        args = build_parser().parse_args(argv)
        assert needs_supervisor(args) is False
        await invoke(api, *argv)
        assert untouched(lab), argv
    code, _ = await invoke(api, *run_argv(value=0))
    assert code == EXIT_OK
    assert needs_supervisor(build_parser().parse_args(["run", "d"])) is True
    assert lab.config.work_root.exists(), "a command that executes must own the work root"
