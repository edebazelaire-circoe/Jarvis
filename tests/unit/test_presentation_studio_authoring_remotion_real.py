"""The Remotion authoring path against the REAL compiler (Node + esbuild of the locked set), Slice 15.

Ignored by default: it needs an installed Remotion capability (`scripts/remotion_install_harness.py` or the install action of Core).

    JARVIS_REMOTION_RUNTIME_DIR=<private data root>/local_capabilities/remotion/runtime pytest tests/unit/test_presentation_studio_authoring_remotion_real.py

What the scripted `ScriptedCompiler` cannot say, esbuild does: the example the draft guide hands the model, the slide the scripted rig
writes and an exploratory fan of them all compile; a syntax error and a forbidden import come back as typed refusals with file, line and
column; an assembled deck's sources are then compiled again for free (same content, same key) when the player asks. The cache is a
temporary folder, never the live profile.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jarvis.adapters.node_capability_runner import default_remotion_runner
from jarvis.adapters.remotion_compiler import RemotionCompiler, shipped_engine_pin
from jarvis.domain.prefab import parse_candidate
from jarvis.domain.presentation_studio_authoring_guide import example, exploratory_example
from jarvis.domain.presentation_studio_authoring_remotion import generate_source
from jarvis.domain.remotion_compile import CompileErrorCode, RemotionCompileError
from tests.fakes import presentation_studio_fake_author as fa
from tests.fakes.presentation_studio_authoring_env import AuthoringEnv

RUNTIME = os.environ.get("JARVIS_REMOTION_RUNTIME_DIR")
pytestmark = pytest.mark.skipif(not RUNTIME or not Path(RUNTIME, "install-record.json").is_file(),
                                reason="JARVIS_REMOTION_RUNTIME_DIR points to no installed Remotion runtime")


@pytest.fixture(scope="module")
def compiler(tmp_path_factory):
    runtime = Path(RUNTIME)
    shipped = Path(__file__).resolve().parents[2] / "jarvis" / "capabilities" / "remotion" / "runtime-host.mjs"
    if shipped.read_bytes() != (runtime / "runtime-host.mjs").read_bytes():
        pytest.skip("the installed runtime-host.mjs is older than the repository's: run repair")
    return RemotionCompiler(runner=default_remotion_runner(), runtime_dir=runtime, cache_dir=tmp_path_factory.mktemp("compiled"),
                            readiness=lambda: None)


def compiled(compiler, spec, key="hero"):
    made = generate_source(key, spec, shipped_engine_pin(), "bundle:" + key)
    return compiler.compile_scene(parse_candidate(made.candidate).remotion_source())


def test_the_guide_example_the_rig_slide_and_the_exploratory_fan_all_compile(compiler):
    specs = [example()["draft"]["prefabs"][0]["remotion"], fa.slide_bundle()["remotion"], exploratory_example()["draft"]["prefabs"][0]["remotion"]]
    for spec in specs:
        artifact = compiled(compiler, spec)
        text = compiler.resolve_output_file(artifact.cache_key, "scene.js").read_text("utf-8")
        assert "JarvisScene" in text and "__JARVIS_HOST__" in text and artifact.engine_drift is False


def test_the_three_layouts_the_kit_and_every_theme_transition_compile_and_the_kit_is_in_the_bundle(compiler):
    from jarvis.domain.presentation_studio_authoring_guide import layouts

    for name, layout in layouts().items():
        artifact = compiled(compiler, layout["remotion"], name)
        text = compiler.resolve_output_file(artifact.cache_key, "scene.js").read_text("utf-8")
        assert "clipPath" in text and "translateY" in text, name                 # the kit's transitions travel with the scene
        assert artifact.engine_drift is False


def test_a_syntax_error_comes_back_with_the_file_the_line_and_the_column(compiler):
    spec = fa.slide_bundle()["remotion"]
    spec["files"] = {"src/Scene.tsx": fa.SLIDE_TSX + "\nconst broken = (;\n"}
    with pytest.raises(RemotionCompileError) as caught:
        compiled(compiler, spec)
    error = caught.value
    assert error.code is CompileErrorCode.SOURCE_ERROR and error.diagnostics
    first = error.diagnostics[0]
    assert first.file == "src/Scene.tsx" and first.line == fa.SLIDE_TSX.count("\n") + 2 and first.column > 0


def test_a_forbidden_import_and_a_missing_default_export_are_typed_refusals(compiler):
    spec = fa.slide_bundle()["remotion"]
    # the imported name must be used: esbuild drops an unused TypeScript import before resolving it (harmless, documented in remotion-source.md)
    spec["files"] = {"src/Scene.tsx": 'import fs from "fs";\nexport default function Scene() { return fs ? null : null; }\n'}
    with pytest.raises(RemotionCompileError) as caught:
        compiled(compiler, spec)
    assert caught.value.code is CompileErrorCode.IMPORT_REFUSED
    spec["files"] = {"src/Scene.tsx": "export const x = 1;\n"}
    with pytest.raises(RemotionCompileError) as caught:
        compiled(compiler, spec, "other")
    assert caught.value.code is CompileErrorCode.ENTRY_INVALID


async def test_a_whole_deck_is_compiled_by_the_real_compiler_before_it_is_written_and_a_broken_one_writes_nothing(tmp_path, compiler):
    env = await AuthoringEnv(tmp_path / "e").start(compiler=compiler, pin=shipped_engine_pin)
    out = await env.assemble(fa.brief("directed"), fa.good_deck())
    assert out.status == "delivered", out.body.get("report", {}).get("failures")
    rows = out.to_dict()["provenance"]["compiled"]
    assert [r["key"] for r in rows] == ["slide", "cover"] and all(r["cache_key"].startswith("scene-") and r["bytes"] > 100 for r in rows)
    [scene, *_] = (await env.studio.get(out.to_dict()["presentation_id"])).variants[0].scenes
    source = await env.prefabs.remotion_source(scene.prefab.prefab_id, scene.prefab.version)
    assert compiler.compile_scene(source).reused is True                      # the player will get the compiled bundle from the cache, free
    broken_brief, broken = fa.violate("tsx_compile")
    out = await env.assemble(broken_brief, broken)
    assert out.status == "refused" and any(f["code"] == "tsx_compile" and f["diagnostics"][0]["file"] == "src/Scene.tsx" for f in out.body["report"]["failures"])
    assert len(env.folders()) == 1                                             # only the first deck was written


async def test_a_runtime_that_is_not_ready_is_the_409_with_the_real_readiness_reason(tmp_path, compiler):
    down = RemotionCompiler(runner=default_remotion_runner(), runtime_dir=Path(RUNTIME), cache_dir=tmp_path / "c",
                            readiness=lambda: "the Remotion capability is not ready (state: failed)")
    env = await AuthoringEnv(tmp_path / "e").start(compiler=down, pin=shipped_engine_pin)
    out = await env.assemble(*fa.good_one_shot())
    assert (out.status, out.http_status) == ("refused", 409) and "state: failed" in out.body["error"]["message"] and env.folders() == []
