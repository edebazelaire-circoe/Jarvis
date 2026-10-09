"""Compilation RÉELLE (Node + esbuild du verrou) d'une scène Remotion, sur une capacité déjà installée (Slice 05).

Ignoré par défaut : il exige un environnement Remotion installé (`scripts/remotion_install_harness.py` ou l'action
d'installation de Core). Pour l'exercer :

    JARVIS_REMOTION_RUNTIME_DIR=<racine de données privée>/local_capabilities/remotion/runtime pytest tests/unit/test_remotion_compiler_real.py

Le dossier `runtime-host.mjs` de ce runtime doit être celui du dépôt (sinon `repair`). Le test ne touche que le cache
`compiled/` voisin, copié dans un dossier temporaire : jamais le profil vivant. Preuve complète (navigateur compris) :
`scripts/remotion_compile_harness.py`.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil

import pytest

from jarvis.adapters.node_capability_runner import default_remotion_runner
from jarvis.adapters.remotion_compiler import RemotionCompiler
from jarvis.domain import remotion_compile as rc
from jarvis.domain.prefab import parse_candidate
from tests.fakes.remotion_scene import PNG_1X1, scene_candidate, scene_files

RUNTIME = os.environ.get("JARVIS_REMOTION_RUNTIME_DIR")
pytestmark = pytest.mark.skipif(not RUNTIME or not Path(RUNTIME, "install-record.json").is_file(),
                                reason="JARVIS_REMOTION_RUNTIME_DIR points to no installed Remotion runtime")


@pytest.fixture(scope="module")
def compiler(tmp_path_factory):
    runtime = Path(RUNTIME)
    shipped = Path(__file__).resolve().parents[2] / "jarvis" / "capabilities" / "remotion" / "runtime-host.mjs"
    if shipped.read_bytes() != (runtime / "runtime-host.mjs").read_bytes():
        pytest.skip("the installed runtime-host.mjs is older than the repository's: run repair")
    cache = tmp_path_factory.mktemp("compiled")
    return RemotionCompiler(runner=default_remotion_runner(), runtime_dir=runtime, cache_dir=cache, readiness=lambda: None)


def source(files=None):
    return parse_candidate(scene_candidate(files=files or scene_files())).remotion_source()


def refused(compiler, files, **options):
    with pytest.raises(rc.RemotionCompileError) as caught:
        compiler.compile_scene(source(files), **options)
    return caught.value


def test_the_sample_scene_compiles_with_its_assets(compiler):
    artifact = compiler.compile_scene(source())
    assert {f.path for f in artifact.files} == {"scene.js", "public/dot.png"}
    text = compiler.resolve_output_file(artifact.cache_key, "scene.js").read_text("utf-8")
    assert text.startswith("/* jarvis-remotion-scene contract=1 digest=") and "JarvisScene" in text
    assert "__JARVIS_HOST__" in text and "react-dom" not in text  # React comes from the host, never bundled per scene
    assert compiler.resolve_output_file(artifact.cache_key, "public/dot.png").read_bytes() == PNG_1X1
    assert compiler.compile_scene(source()).reused


def test_the_host_bundle_exposes_one_react_remotion_and_player(compiler):
    host = compiler.compile_host()
    text = compiler.resolve_output_file(host.cache_key, "host.js").read_text("utf-8")
    assert "__JARVIS_HOST__" in text and host.files[0].bytes > 100_000


def test_a_syntax_error_names_file_line_and_column(compiler):
    error = refused(compiler, {**scene_files(), "src/lib/Title.tsx": "export const Title = () => <h1>{</h1>;\n"})
    assert error.code is rc.CompileErrorCode.SOURCE_ERROR
    assert error.diagnostics and error.diagnostics[0].file == "src/lib/Title.tsx" and error.diagnostics[0].line == 1


@pytest.mark.parametrize("line", ['import fs from "fs";', 'import fs from "node:fs";', 'import x from "lodash";',
                                  'import x from "https://example.com/x.js";', 'import x from "@remotion/cli";',
                                  'import x from "../outside";', 'import x from "./missing";', 'import x from "/etc/passwd";'])
def test_imports_outside_the_scene_and_the_allow_list_are_refused(compiler, line):
    # The imported name must be used: esbuild drops an unused import from a TypeScript file before resolving it (harmless).
    symbol = line.split()[1]
    files = {**scene_files(), "src/lib/Title.tsx": line + f"\nexport const Title = () => <h1>{{String({symbol})}}</h1>;\n"}
    error = refused(compiler, files)
    assert error.code is rc.CompileErrorCode.IMPORT_REFUSED, (line, error)
    assert not any(part in error.message for part in ("C:\\", "/Users/"))


def test_an_entry_without_a_default_export_is_typed(compiler):
    error = refused(compiler, {**scene_files(), "src/Scene.tsx": 'export const Scene = () => null;\n'})
    assert error.code is rc.CompileErrorCode.ENTRY_INVALID


def test_the_deadline_kills_the_process_and_is_typed(tmp_path):
    slow = RemotionCompiler(runner=default_remotion_runner(), runtime_dir=Path(RUNTIME), cache_dir=tmp_path / "c",
                            readiness=lambda: None, scene_timeout_s=0.001)
    with pytest.raises(rc.RemotionCompileError) as caught:
        slow.compile_scene(source({**scene_files(), "src/lib/Title.tsx": "export const Title = () => null; // slow\n"}))
    assert caught.value.code is rc.CompileErrorCode.TIMEOUT
    assert not any(p.name.startswith(".tmp-") for p in (tmp_path / "c").iterdir())
    shutil.rmtree(tmp_path / "c", ignore_errors=True)


# ------------------------------------------------------------------ Slice 06 : bornes du compilateur sous des sources hostiles

def _wrap(text: str, width: int = 40) -> str:
    return "\n".join(text[i:i + width] for i in range(0, len(text), width))


def _bomb(name: str) -> str:
    return {
        "deep_parens": "export const Title = () => " + _wrap("(" * 120_000 + "1" + ")" * 120_000) + ";\n",
        "deep_arrays": "export const Title = () => " + _wrap("[" * 120_000 + "]" * 120_000) + ";\n",
        "literal_table": "export const Title = () => null;\nconst t = [" + ",\n".join("{a:%d,b:'x%d'}" % (i, i) for i in range(9000)) + "];\n",
    }[name]


@pytest.mark.parametrize("name", ["deep_parens", "deep_arrays", "literal_table"])
def test_pathological_but_in_bounds_sources_end_quickly_and_typed(compiler, name):
    import time
    files = {**scene_files(), "src/lib/Title.tsx": 'import React from "react";\n' + _bomb(name)}
    started = time.monotonic()
    try:
        compiler.compile_scene(source(files))
    except rc.RemotionCompileError as caught:  # a typed refusal is as good as a result; a crash or a hang is not
        assert caught.code in (rc.CompileErrorCode.SOURCE_ERROR, rc.CompileErrorCode.TIMEOUT, rc.CompileErrorCode.OUTPUT_TOO_LARGE)
    assert time.monotonic() - started < 30, name
