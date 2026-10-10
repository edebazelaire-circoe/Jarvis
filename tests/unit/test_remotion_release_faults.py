"""Release gate, Slice 22 (jarvis-remotion-presentation-integration): fault injection on the Remotion path, on a real Core.

Contract: `docs/remotion-integration-release.md` (fault matrix). Every fault of the matrix ends in a TYPED, VISIBLE state, and none of
them ends in a Slidecar (HTML) presentation on the stage: no fallback is the product rule (`docs/presentation-engine.md`).

Two kinds of proof live here:

* `test_without_the_runtime_*` : a real `JarvisCoreApplication` behind the real protocol server, Remotion NOT installed. Every door that
  can put something on the stage (all playback verbs, the explicit edit, the source edit, the render, the Studio) is called and must
  answer a typed refusal; the scene holds no object, no presentation became Slidecar, no `slidecar_*` event was written.
* `test_the_fault_matrix_*` : the table `FAULTS` names, for each fault of the release brief, the typed state a person sees and the test
  that proves it (a unit test on the real code, or a real-runtime test run opt-in with `JARVIS_REMOTION_RUNTIME_DIR`). The table is
  checked: the test exists, the state is a typed one, nothing in the table says Slidecar.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from jarvis.domain.presentation_studio_playback_requests import Verb
from tests.fakes.remotion_player_stack import RemotionStack
from tests.unit.test_remotion_player_realpage_browser import A, PROPS, SAMPLE, SCENE_TSX, S1, scene

ROOT = Path(__file__).resolve().parents[2]
BASE = "/v1/presentation-studio"
PLAYBACK = BASE + "/playback"


async def world(stack: RemotionStack) -> tuple[str, str]:
    await stack.publish(A, {"src/Scene.tsx": SCENE_TSX}, title="Un", props=PROPS, sample=SAMPLE)
    return await stack.presentation([scene(S1, A, "Premier")])


def code_of(body: object) -> str | None:
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return error.get("code")
        return body.get("code") if isinstance(body.get("code"), str) else None
    return None


# ------------------------------------------------------------------ 1. Remotion not installed: every door is typed, nothing falls back

async def test_without_the_runtime_every_door_is_a_typed_refusal_and_nothing_plays_or_falls_back(tmp_path):
    async with RemotionStack(tmp_path, runtime_dir=None) as stack:
        pid, vid = await world(stack)
        answers: dict[str, tuple[int, str | None]] = {}

        async def door(name: str, method: str, path: str, body: dict | None = None) -> None:
            status, answer = await stack.call(method, path, **({"json": body} if body is not None else {}))
            answers[name] = (status, code_of(answer))

        # every playback verb, in every role: the run never starts, so nothing else can act on a stage
        for role in ("user_presenter", "rehearsal", "jarvis_presenter"):
            await door(f"start:{role}", "POST", PLAYBACK + "/start",
                       {"actor": "brain" if role == "jarvis_presenter" else "user", "presentation_id": pid, "role": role})
        for verb in Verb:
            if verb is not Verb.START:
                await door(f"verb:{verb.value}", "POST", f"{PLAYBACK}/{verb.value}", {"actor": "user"})
        # the explicit edit and the source edit of the Presentation, the render, the Studio
        view = (await stack.call("GET", f"{BASE}/presentations/{pid}"))[1]
        revision = view["variants"][0]["revision"]
        variants = f"{BASE}/presentations/{pid}/variants/{vid}"
        await door("edit:preview", "POST", variants + "/edits", {
            "actor": "user", "mode": "preview", "basis": {"variant_revision": revision},
            "ops": [{"op": "control.set", "scene_id": S1, "control_id": "headline", "value": "x"}]})
        await door("source_edit", "POST", variants + "/source-edits", {
            "actor": "user", "basis": {"variant_revision": revision}, "scene_id": S1, "files": {"sources": {"src/Scene.tsx": SCENE_TSX}}})
        await door("render", "POST", "/v1/local-capabilities/remotion/render/jobs", {"snapshot_id": "jart_none", "format": "mp4"})
        await door("studio_open", "POST", "/v1/local-capabilities/remotion/studio/open", {"presentation_id": pid})
        # an agent cannot name a Slidecar document as a way out
        await door("agent_names_slidecar", "POST", BASE + "/presentations", {"title": "x", "engine": "slidecar", "actor": "brain"})

        assert answers["start:user_presenter"][1] == "presentation_studio_engine_unavailable", answers
        assert answers["start:rehearsal"][1] == "presentation_studio_engine_unavailable", answers
        assert answers["edit:preview"][1] == "presentation_studio_engine_unavailable", answers
        assert answers["agent_names_slidecar"] == (403, "presentation_studio_engine_selection_refused"), answers
        for name, (status, code) in answers.items():
            assert status != 200, (name, status, code)
            assert status < 500 or code is not None, f"{name}: an untyped server error {status}"
        # nothing reached the scene, no Presentation became Slidecar, the run is idle
        _, snapshot = await stack.call("GET", "/v1/scene/snapshot")
        assert not [o for o in snapshot["snapshot"]["objects"] if str(o.get("object_id", "")).startswith("studio-")]
        assert (await stack.call("GET", PLAYBACK))[1]["state"]["phase"] == "idle"
        listed = (await stack.call("GET", BASE + "/presentations"))[1]["presentations"]
        assert [p["engine"] for p in listed] == ["remotion"], "the only document is the Remotion one; no Slidecar copy appeared"
        kinds = set(stack.kinds())
        assert "core.presentation_studio.engine_refused" in kinds
        assert not {k for k in kinds if "slidecar" in k}, "no Slidecar event of any kind was written"
        # the availability the card shows is the real reason
        _, engine = await stack.call("GET", BASE + "/engine")
        assert engine["default_engine"] == "remotion"
        remotion = engine["engines"]["remotion"]
        assert remotion["ready"] is False and remotion["reason"] and remotion["repair"], "the card shows the real reason and the gesture"
        assert engine["slidecar"]["total"] == 0 and engine["slidecar"]["events"] == [], "the Slidecar usage ledger stayed empty"


async def test_after_a_restart_without_the_runtime_a_remotion_document_is_still_remotion_and_still_refused(tmp_path):
    """The engine of a document is durable and immutable: a Core that comes back without Remotion neither converts nor plays it."""

    async with RemotionStack(tmp_path, runtime_dir=None) as stack:
        pid, _ = await world(stack)
    async with RemotionStack(tmp_path, runtime_dir=None) as again:
        listed = (await again.call("GET", BASE + "/presentations"))[1]["presentations"]
        assert [(p["presentation_id"], p["engine"]) for p in listed] == [(pid, "remotion")]
        status, refused = await again.start(pid)
        assert status == 409 and code_of(refused) == "presentation_studio_engine_unavailable"
        assert (await again.call("GET", BASE + "/playback"))[1]["state"]["phase"] == "idle"


# ------------------------------------------------------------------ 2. the matrix

#: fault -> (typed state the person sees, where it is proven: `file::test`, the file under tests/unit).
FAULTS: dict[str, tuple[str, str]] = {
    "runtime missing (never installed)": (
        "refused: presentation_studio_engine_unavailable with the repair text",
        "test_remotion_release_faults.py::test_without_the_runtime_every_door_is_a_typed_refusal_and_nothing_plays_or_falls_back"),
    "runtime missing (stage window)": (
        "stage says the engine is unavailable and shows the repair, phase failed",
        "test_remotion_player_realpage_browser.py::test_a_remotion_window_on_the_scene_says_in_the_window_that_the_engine_is_unavailable"),
    "runtime missing (after a Core restart)": (
        "refused: still remotion, never converted",
        "test_remotion_release_faults.py::test_after_a_restart_without_the_runtime_a_remotion_document_is_still_remotion_and_still_refused"),
    "compile error (edit)": (
        "refused: presentation_studio_source_build_failed 422 with file:line:column, pin unchanged",
        "test_remotion_source_edit_real.py::test_the_real_compiler_gates_the_edit_and_a_failed_build_never_publishes"),
    "compile error (stage)": (
        "stage shows the compiler message, failed state",
        "test_remotion_player_realpage_browser.py::test_a_scene_that_does_not_compile_shows_file_line_and_column_in_the_window"),
    "sandbox killed / frozen scene": (
        "watchdog removes the frame (killed), reload offered",
        "test_remotion_player_realpage_browser.py::test_a_frozen_scene_is_removed_by_the_watchdog_with_its_reason_and_a_reload_action"),
    "hostile scene (egress, parent access, storage)": (
        "refused: typed guard findings, 0 hits at the sinks",
        "test_remotion_isolation_real.py::test_every_hostile_scene_is_neutralised_in_a_real_browser_and_the_benign_one_renders"),
    "render cancelled": (
        "cancelled: derivative failed, no final file",
        "test_presentation_render_service.py::test_cancelling_a_running_job_stops_it_and_never_leaves_a_final_file"),
    "render process killed / over its bounds": (
        "failed: typed runner failure, tree killed, says which limit",
        "test_presentation_render_runner.py::test_a_run_past_its_deadline_is_killed_and_says_which_limit"),
    "Core restarts in the middle of a render": (
        "failed: orphan killed, derivative failed, no partial promoted",
        "test_presentation_render_service.py::test_reconcile_kills_an_orphan_and_fails_the_pending_derivative_without_promoting_a_partial_file"),
    "a second Core on the same data": (
        "refused: render locked, the first Core's renders untouched",
        "test_presentation_render_service.py::test_a_second_live_core_leaves_the_first_ones_renders_alone"),
    "Studio crashed / vanished": (
        "failed view with its log, Open recovers",
        "test_remotion_studio.py::test_a_vanished_process_becomes_failed_and_open_recovers"),
    "Studio does not answer": (
        "failed then killed and restarted",
        "test_remotion_studio.py::test_a_live_process_that_does_not_answer_is_killed_and_restarted"),
    "Core stops with a Studio alive": (
        "stopped: no orphan", "test_remotion_studio.py::test_core_stop_never_leaves_an_orphan"),
    "stale source revision": (
        "refused: presentation_studio_stale_revision, snapshot failed",
        "test_presentation_artifacts.py::test_a_stale_source_revision_is_refused_and_writes_nothing"),
    "an agent names an engine": (
        "refused: presentation_studio_engine_selection_refused 403",
        "test_presentation_studio_engine.py::test_only_a_human_can_name_an_engine_an_agent_cannot_even_name_the_default"),
}

TYPED_STATE_WORDS = ("refused", "failed", "cancelled", "killed", "stopped", "stage says", "stage shows")


def defined(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_the_fault_matrix_row_points_at_a_real_test_and_a_typed_state_that_is_never_slidecar(fault):
    state, where = FAULTS[fault]
    file, _, name = where.partition("::")
    path = ROOT / "tests" / "unit" / file
    assert path.is_file(), f"{fault}: {file} does not exist"
    assert name in defined(path), f"{fault}: {file} has no test named {name}"
    assert "slidecar" not in state.lower(), f"{fault}: a fault must never end in a Slidecar"
    assert any(word in state.lower() for word in TYPED_STATE_WORDS), f"{fault}: the state is not a typed, visible one: {state!r}"


def test_the_fault_matrix_covers_every_fault_of_the_release_brief():
    for needle in ("runtime missing", "compile error", "sandbox killed", "render cancelled", "render process killed",
                   "Core restarts in the middle of a render", "Studio crashed"):
        assert any(row.lower().startswith(needle.lower()) for row in FAULTS), needle
