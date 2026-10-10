"""Release gate, Slice 22 (jarvis-remotion-presentation-integration): the Remotion product journey, end to end, on ONE real Core.

One test lives the whole path a person would: a brief becomes a Remotion deck through the real authoring door and the REAL compiler (Node +
esbuild of the locked set); it plays with its cues armed; a props edit changes a value live; a source edit is built before it is published and
a broken one is refused with the pin unchanged, then the previous version is restored; the deck is frozen and exported as an MP4, a still image
and a PDF by the real render runner (real Chrome, ffprobe-verified); an upstream template is imported with its provenance; the deck is promoted
(explicit, one artefact); a newer version of a scene prefab is noticed and tried in a child variant that never touches the original.

Opt-in like the other real-runtime tests: `JARVIS_REMOTION_RUNTIME_DIR` = the `runtime/` folder of an installed Remotion capability (no
installation is done here), Node and Chrome. A throw-away data root and free ports; never the live JARVIS. With `JARVIS_REMOTION_EVIDENCE_DIR`
the measured steps are written to `release-journey.json`. Contract and report: `docs/remotion-integration-release.md`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

import pytest

from jarvis.adapters.fake_upstream_fetcher import FakeUpstreamFetcher
from jarvis.adapters.remotion_compiler import shipped_engine_pin
from jarvis.adapters.remotion_render_runner import RemotionRenderRunner
from tests.fakes import presentation_studio_fake_author as fa
from tests.fakes.remotion_player_stack import RemotionStack, runtime_dir_from_env
from tests.fakes.upstream_archive import good_project, make_tarball
from tests.unit.test_remotion_import_service import ORIGIN, URL

RUNTIME = runtime_dir_from_env()
pytestmark = pytest.mark.skipif(RUNTIME is None or shutil.which("node") is None,
                                reason="needs JARVIS_REMOTION_RUNTIME_DIR (an existing Remotion install) and node")

BASE = "/v1/presentation-studio"
RENDER = "/v1/local-capabilities/remotion/render/jobs"
STEPS: list[dict] = []


def options(stack: RemotionStack) -> dict:
    stack.fetcher = FakeUpstreamFetcher()
    stack.fetcher.add(ORIGIN, make_tarball(good_project()))
    return {"remotion_render_runner": RemotionRenderRunner(lambda: stack.data_root / "local_capabilities" / "remotion" / "runtime"),
            "upstream_fetcher": stack.fetcher, "upstream_engine": shipped_engine_pin, "remotion_import_owners": lambda: ("someone",)}


class Timer:
    def __init__(self, name: str, **info) -> None:
        self.name, self.info = name, info

    def __enter__(self):
        self.started = time.perf_counter()
        return self

    def __exit__(self, *exc) -> None:
        STEPS.append({"step": self.name, "seconds": round(time.perf_counter() - self.started, 2), **self.info})


def evidence() -> None:
    folder = os.environ.get("JARVIS_REMOTION_EVIDENCE_DIR")
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
        Path(folder, "release-journey.json").write_text(json.dumps({"steps": STEPS}, indent=1), encoding="utf-8")


async def until_done(stack: RemotionStack, job_id: str, timeout: float = 180.0) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        status, body = await stack.call("GET", f"{RENDER}/{job_id}")
        assert status == 200, body
        if body["job"]["state"] in ("complete", "failed", "cancelled"):
            return body["job"]
        await asyncio.sleep(0.5)
    raise AssertionError(f"render job {job_id} did not finish in {timeout}s")


def stage_objects(snapshot: dict) -> list[dict]:
    return [o for o in snapshot["snapshot"]["objects"] if str(o.get("object_id", "")).startswith("studio-stage-")]


async def test_the_remotion_journey_from_a_brief_to_exports_import_promotion_and_a_newer_version_trial(tmp_path):
    STEPS.clear()
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME, core_options=options) as stack:
        # ------------------------------------------------------------ 1. one-shot authoring through the real door and the real compiler
        with Timer("1_assemble_a_deck_with_the_real_compiler"):
            status, made = await stack.call("POST", BASE + "/authoring/assemble", json={
                "brief": fa.brief("directed", duration_target_s=300), "draft": fa.good_deck(6)})
        assert status in (200, 201) and made["status"] == "delivered", made
        pid = made["presentation_id"]
        _, view = await stack.call("GET", f"{BASE}/presentations/{pid}")
        assert view["presentation"]["engine"] == "remotion", "an authored deck is Remotion; nothing named an engine"
        vid = view["presentation"]["active_variant_id"]
        variants = f"{BASE}/presentations/{pid}/variants/{vid}"
        _, variant = await stack.call("GET", variants)
        scenes = variant["scenes"]
        assert len(scenes) == 6 and all(s["prefab"]["id"].startswith("presentation-studio.") for s in scenes)

        # ------------------------------------------------------------ 2. play it, with its cues armed: a Remotion object on the stage
        with Timer("2_start_the_run"):
            status, started = await stack.call("POST", BASE + "/playback/start", json={"actor": "user", "presentation_id": pid, "role": "user_presenter"})
        assert status == 200 and started["state"]["phase"] == "playing", started
        _, snapshot = await stack.call("GET", "/v1/scene/snapshot")
        [stage] = stage_objects(snapshot)
        assert stage["payload"]["prefab"]["id"] == scenes[0]["prefab"]["id"], "the stage shows the Remotion scene pinned by the deck"
        assert "srcdoc" not in json.dumps(stage), "no HTML document is mounted for a Remotion scene"
        _, armed = await stack.call("GET", BASE + "/playback/armed")
        assert armed["cues"], "the deck's first cue is armed with its phrase"
        status, fired = await stack.call("POST", BASE + "/cues/satisfied", json={
            "run_id": armed["run_id"], "generation": armed["generation"], "cue_id": armed["cues"][0]["cue_id"]})
        assert status == 200 and fired["status"] == "fired", fired
        _, where = await stack.call("GET", BASE + "/playback")
        assert where["state"]["position"]["index"] == 2, "the cue moved the run to the second scene"

        # ------------------------------------------------------------ 3. live edit: a typed props change, no republication
        scene_id = where["state"]["scene"]["scene_id"]
        _, before_edit = await stack.call("GET", variants)
        with Timer("3_props_edit_while_playing"):
            status, edited = await stack.call("POST", BASE + "/playback/edit", json={
                "actor": "user", "ops": [{"op": "control.set", "scene_id": scene_id, "control_id": "headline", "value": "Chiffre du jour"}]})
        assert status == 200 and edited["status"] == "applied", edited
        await stack.call("POST", BASE + "/playback/stop", json={"actor": "user"})
        _, after_edit = await stack.call("GET", variants)
        current = next(s for s in after_edit["scenes"] if s["scene_id"] == scene_id)
        assert current["props"].get("headline") == "Chiffre du jour" and current["prefab"] == next(s for s in before_edit["scenes"] if s["scene_id"] == scene_id)["prefab"], \
            "a props edit never republishes the source"
        _, snapshot = await stack.call("GET", "/v1/scene/snapshot")
        assert stage_objects(snapshot) == [], "stopping the run removes the stage"

        # ------------------------------------------------------------ 4. source edit: built before publication; a broken one is refused; the old one is restored
        target = scenes[0]["scene_id"]
        status, source = await stack.call("GET", variants + f"/scenes/{target}/source")
        assert status == 200 and source["engine"] == "remotion"
        scene_file = "src/Scene.tsx" if "src/Scene.tsx" in source["sources"] else sorted(source["sources"])[0]
        original = source["sources"][scene_file]
        revision = (await stack.call("GET", variants))[1]["revision"]
        with Timer("4a_source_edit_good_build_and_repin"):
            status, good = await stack.call("POST", variants + "/source-edits", json={
                "actor": "user", "basis": {"variant_revision": revision}, "scene_id": target,
                "files": {"sources": {scene_file: original + "\n// release gate: edited\n"}}})
        assert status == 200 and good["status"] == "repinned", good
        pinned = (await stack.call("GET", variants))[1]["scenes"][0]["prefab"]
        revision = (await stack.call("GET", variants))[1]["revision"]
        with Timer("4b_source_edit_broken_is_refused"):
            status, broken = await stack.call("POST", variants + "/source-edits", json={
                "actor": "user", "basis": {"variant_revision": revision}, "scene_id": target,
                "files": {"sources": {scene_file: original + "\nconst = ;\n"}}})
        assert status == 422 and broken["error"]["code"] == "presentation_studio_source_build_failed" and broken["diagnostics"], broken
        assert (await stack.call("GET", variants))[1]["scenes"][0]["prefab"] == pinned, "a refused build moves nothing"
        status, restored = await stack.call("POST", variants + "/source-edits", json={
            "actor": "user", "basis": {"variant_revision": (await stack.call("GET", variants))[1]["revision"]}, "scene_id": target,
            "files": {"restore_version": good["previous"]}})
        assert status == 200, restored
        _, back = await stack.call("GET", variants + f"/scenes/{target}/source")
        assert back["sources"][scene_file] == original, "rollback restores the previous source byte for byte"

        # ------------------------------------------------------------ 5. freeze and export an MP4, a still image and a PDF with the real runner
        exports = {}
        for fmt in ("mp4", "still", "pdf"):
            _, current_view = await stack.call("GET", f"{BASE}/presentations/{pid}")
            _, current_variant = await stack.call("GET", variants)
            with Timer(f"5_export_{fmt}"):
                status, job = await stack.call("POST", RENDER, json={
                    "format": fmt, "presentation_id": pid, "variant_id": vid, "expected_presentation_revision": current_view["presentation"]["revision"],
                    "expected_variant_revision": current_variant["revision"], "authorised_boards": [],
                    "settings": {"scene_id": scenes[0]["scene_id"]}})
                assert status == 202, job
                done = await until_done(stack, job["job"]["job_id"])
            assert done["state"] == "complete", {k: done.get(k) for k in ("error_code", "error_detail", "phase", "log")}
            exports[fmt] = done
            artifact = await stack.core.artifacts.get(done["artifact_id"])
            assert artifact.state.value == "complete" and artifact.kind.value == {"mp4": "presentation_video", "still": "presentation_still", "pdf": "presentation_pdf"}[fmt]
            payload = stack.data_root / "artifacts" / artifact.artifact_id / artifact.payload_ref.split("/")[-1]
            assert payload.is_file() and artifact.size_bytes == payload.stat().st_size and artifact.size_bytes > 500
            assert hashlib.sha256(payload.read_bytes()).hexdigest() == artifact.metadata["render_output_sha256"], "the payload is the verified render"
            assert artifact.metadata["render_sandbox"] is True and artifact.metadata.get("render_egress_denied") is not None
        snapshot_ids = {done["snapshot_id"] for done in exports.values()}
        assert len(snapshot_ids) == 1, "the three exports render the SAME frozen snapshot (replayed freeze)"

        # ------------------------------------------------------------ 6. import an upstream template (explicit, scoped to the deck, provenance recorded)
        with Timer("6_import_template_with_provenance"):
            status, imported = await stack.call("POST", "/v1/remotion/imports", json={
                "repo_url": URL, "commit": ORIGIN.commit, "presentation_id": pid, "scene_id": scenes[0]["scene_id"]})
        assert status in (200, 201), imported
        ref = imported["prefab"]
        assert ref["prefab_id"].startswith(f"presentation-studio.p{pid[4:16]}."), "an import is private to the presentation, never the shared library"
        assert ref["fingerprint"] and ref["version"] >= 1
        assert stack.fetcher.requests, "the download happened only because the user asked"
        description = await stack.core.remotion_player.describe(ref["prefab_id"], ref["version"])
        assert description, "the imported source compiles with the real compiler"

        # ------------------------------------------------------------ 7. promote (explicit): one scene as a library prefab, a whole presentation as ONE artefact
        from tests.unit.test_remotion_player_realpage_browser import A, PROPS, SAMPLE, SCENE_TSX, S1, scene as fixture_scene
        await stack.publish(A, {"src/Scene.tsx": SCENE_TSX}, title="Un", props=PROPS, sample=SAMPLE)
        pid2, vid2 = await stack.presentation([fixture_scene(S1, A, "Premier")])
        variants2 = f"{BASE}/presentations/{pid2}/variants/{vid2}"
        library = stack.data_root / "prefabs"
        names = lambda: sorted(p.name for p in library.iterdir()) if library.exists() else []  # noqa: E731
        # the scene of deck 1 whose source was edited above has a reload no page confirmed (this journey has no stage window): promotion refuses it
        status, refused = await stack.call("POST", variants + "/templates/plan", json={
            "kind": "scene", "slug": "scene-editee", "title": "Scène éditée", "scenes": [{"scene_id": scenes[0]["scene_id"], "dimensions": ["accent"], "parameters": ["headline"]}]})
        assert status == 409 and refused["error"]["code"] == "presentation_studio_scene_reloading", refused
        # a scene whose text is a parameter promotes: ONE library prefab, written only because the user asked (and the plan before it wrote nothing)
        before = names()
        scene_body = {"kind": "scene", "slug": "scene-promue", "title": "Scène promue", "scenes": [{"scene_id": scenes[1]["scene_id"], "dimensions": ["accent"], "parameters": ["headline"]}]}
        with Timer("7a_scene_promotion_plan_writes_nothing"):
            status, plan = await stack.call("POST", variants + "/templates/plan", json=scene_body)
        assert status == 200 and plan["blocking"] == 0 and plan["engine" if "engine" in plan else "kind"] and names() == before, "a plan writes nothing"
        with Timer("7b_scene_promotion_to_the_library"):
            status, promoted = await stack.call("POST", variants + "/templates", json=scene_body)
        assert status in (200, 201) and promoted["published_to_library"] is True, promoted
        assert [n for n in names() if n not in before] == ["studio-template.scene-promue"], "only the explicit promotion published a library prefab"
        # the promoted prefab is a Remotion composition, tagged for its engine, and the deck's own source is untouched
        library_manifest = json.loads((library / "studio-template.scene-promue" / "1" / "manifest.json").read_text(encoding="utf-8"))
        assert library_manifest["catalog"]["compatibility"] == {"remotion": "native", "slidecar": "unsupported"}
        # a second authored deck, never edited: the WHOLE presentation is promoted as ONE artefact, nothing goes to the shared library
        status, made2 = await stack.call("POST", BASE + "/authoring/assemble", json={"brief": fa.brief("directed", duration_target_s=300), "draft": fa.good_deck(6, da=None)})
        assert status in (200, 201), made2
        pid3 = made2["presentation_id"]
        _, view3 = await stack.call("GET", f"{BASE}/presentations/{pid3}")
        variants3 = f"{BASE}/presentations/{pid3}/variants/{view3['presentation']['active_variant_id']}"
        scenes3 = (await stack.call("GET", variants3))[1]["scenes"]
        presentation_body = {"kind": "presentation", "slug": "revue-remotion", "title": "Revue", "scenes": [
            {"scene_id": x["scene_id"], "dimensions": ["accent"], "parameters": ["headline"]} for x in scenes3]}
        before = names()
        with Timer("7c_presentation_promotion_one_artefact"):
            status, whole = await stack.call("POST", variants3 + "/templates", json=presentation_body)
        assert status in (200, 201), whole
        assert whole.get("published_to_library") is False and names() == before, "a presentation is promoted as ONE artefact: no prefab goes to the shared library"
        status, instantiated = await stack.call("POST", f"/v1/presentation-studio/templates/{whole['template_id']}/instantiate", json={"title": "Revue du T4"})
        assert status in (200, 201) and instantiated.get("presentation_id") and instantiated.get("scene_ids"), instantiated
        assert (await stack.call("GET", f"{BASE}/presentations/{instantiated['presentation_id']}"))[1]["presentation"]["engine"] == "remotion", "an instantiated template is a Remotion deck"

        # ------------------------------------------------------------ 8. a newer version of a pinned prefab is noticed; the trial is a CHILD variant
        await stack.publish(A, {"src/Scene.tsx": SCENE_TSX.replace("#101820", "#202830")}, title="Un", props=PROPS, sample=SAMPLE)
        upgrades = f"{BASE}/presentations/{pid2}/variants/{vid2}/upgrades"
        original_file = stack.data_root / "presentations" / pid2 / "variants" / f"{vid2}.json"
        original_hash = hashlib.sha256(original_file.read_bytes()).hexdigest()
        with Timer("8a_newer_version_notice"):
            status, listed = await stack.call("GET", upgrades)
        assert status == 200 and listed["auto_upgrade"] is False and listed["count"] == 1, listed
        assert listed["notices"][0]["latest_version"] == 2 and listed["notices"][0]["fits"] is True and listed["notices"][0]["engine_ok"] is True
        assert hashlib.sha256(original_file.read_bytes()).hexdigest() == original_hash, "a notice writes nothing"
        with Timer("8b_newer_version_trial_in_a_child_variant"):
            status, trial = await stack.call("POST", upgrades + "/try", json={"scene_id": S1, "title": "Essai v2"})
        assert status == 201 and trial["trial"] is True and trial["adopted"] is False and trial["to"]["version"] == 2, trial
        assert hashlib.sha256(original_file.read_bytes()).hexdigest() == original_hash, "the original variant is byte-identical after the trial"
        _, graph = await stack.call("GET", f"{BASE}/presentations/{pid2}")
        assert graph["presentation"]["active_variant_id"] == vid2, "the trial was never activated"
        # a trial plays on the real stage too (the child pins the newer version and still compiles)
        description = await stack.core.remotion_player.describe(A, 2)
        assert description
    evidence()
