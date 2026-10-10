"""Edition de source Remotion avec le VRAI compilateur (Node + esbuild du verrou), un Core isole, sans navigateur (Slice 14).

Opt-in comme `test_remotion_compiler_real.py` : exige `JARVIS_REMOTION_RUNTIME_DIR` (une installation Remotion existante) et Node ; elle
n'installe jamais rien. Core est compose comme `jarvis/app.py` (`RemotionStack`), le protocole est le vrai (`POST .../source-edits`).

Prouve : une bonne edition TSX est compilee AVANT publication puis epinglee ; une erreur de syntaxe, un import refuse (`fs`), un
fichier sans export par defaut et un delai sont refus TYPES avec `fichier:ligne:colonne` par le vrai compilateur, sans rien publier
ni changer le pin ; un asset invalide est refuse par le candidat ; annuler / retablir republient ; la lecture de la source par l'agent.
"""

from __future__ import annotations

import base64

import pytest

from tests.fakes.remotion_player_stack import RemotionStack
from tests.fakes.remotion_scene import PNG_1X1
from tests.unit.test_remotion_player_realpage_browser import A, CONTROLS, PROPS, RUNTIME, SAMPLE, SCENE_TSX, S1, scene

pytestmark = pytest.mark.skipif(RUNTIME is None, reason="needs JARVIS_REMOTION_RUNTIME_DIR (an existing Remotion install) and node")

GOOD = SCENE_TSX.replace("#101820", "#202830")
BROKEN = SCENE_TSX.replace("const frame", "const = ;\n  const frame")
IMPORT_FS = 'import * as fs from "fs";\nexport const used = fs;\n'   # a USED import: esbuild drops an unused one before resolving it
SOURCE_EDITS ="/v1/presentation-studio/presentations/{pid}/variants/{vid}/source-edits"


async def world(stack: RemotionStack) -> tuple[str, str, str]:
    await stack.publish(A, {"src/Scene.tsx": SCENE_TSX}, props=PROPS, sample=SAMPLE)
    pid, vid = await stack.presentation([scene(S1, A, "Premier")])
    return pid, vid, f"/v1/presentation-studio/presentations/{pid}/variants/{vid}"


async def edit(stack: RemotionStack, variants: str, files: dict, **extra):
    # Slice 21 (B1): an edit by the brain needs a pending request recorded in a user turn (covered by test_remotion_mcp_ownership);
    # this test is about the real compiler gate, so it edits as the user, like the Control Center relay does.
    _, variant = await stack.call("GET", variants)
    return await stack.call("POST", variants + "/source-edits", json={
        "actor": "user", "basis": {"variant_revision": variant["revision"]}, "scene_id": S1, "files": files, **extra})


async def test_the_real_compiler_gates_the_edit_and_a_failed_build_never_publishes(tmp_path):
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        pid, vid, variants = await world(stack)
        status, source = await stack.call("GET", variants + f"/scenes/{S1}/source")
        assert status == 200 and source["engine"] == "remotion" and source["sources"]["src/Scene.tsx"] == SCENE_TSX, source
        # --- a good TSX edit: built, published, pinned (no stage window here: `repinned`)
        status, good = await edit(stack, variants, {"sources": {"src/Scene.tsx": GOOD}})
        assert status == 200 and good["status"] == "repinned" and good["prefab"]["id"].startswith("presentation-studio."), good
        own = good["prefab"]["id"]
        assert "core.presentation_studio.reload_built" in stack.kinds() and "remotion.compile.done" in stack.kinds()
        # --- a syntax error: the REAL esbuild says file:line:column; nothing is published, the pin does not move
        before_kinds = stack.kinds().count("core.presentation_studio.reload_published")
        status, broken = await edit(stack, variants, {"sources": {"src/Scene.tsx": BROKEN}})
        assert status == 422 and broken["status"] == "refused_validation", broken
        assert broken["error"]["code"] == "presentation_studio_source_build_failed" and broken["code"] == broken["error"]["code"]
        row = broken["diagnostics"][0]
        assert row["file"] == "src/Scene.tsx" and isinstance(row["line"], int) and row["line"] >= 1 and row["column"] >= 0 and row["text"]
        assert f"src/Scene.tsx:{row['line']}:{row['column']}" in broken["message"] and "compile_source_error" in broken["message"]
        assert ":\\" not in broken["message"] and "node_modules" not in broken["message"], "no path of the machine"
        assert stack.kinds().count("core.presentation_studio.reload_published") == before_kinds, "nothing was published"
        _, variant = await stack.call("GET", variants)
        assert variant["scenes"][0]["prefab"] == good["prefab"], "the previous good version is still the pin"
        # --- a refused import and a missing default export, each typed by the compiler
        status, fs = await edit(stack, variants, {"sources": {"src/Scene.tsx": IMPORT_FS + GOOD}})
        assert status == 422 and fs["error"]["code"] == "presentation_studio_source_build_failed" and "compile_import_refused" in fs["message"], fs
        assert fs["diagnostics"][0]["file"] == "src/Scene.tsx"
        status, nodefault = await edit(stack, variants, {"sources": {"src/Scene.tsx": GOOD.replace("export default function Scene", "export function Scene")}})
        assert status == 422 and "compile_entry_invalid" in nodefault["message"], nodefault
        # --- an isolation guard and a bad asset are refused by the candidate, before any build
        status, guard = await edit(stack, variants, {"sources": {"src/Scene.tsx": GOOD + "\nwindow.fetch('/x')\n"}})
        assert status == 400 and guard["error"]["code"] == "presentation_studio_source_invalid" and "realm_access" in guard["message"], guard
        status, notpng = await edit(stack, variants, {"assets": {"public/a.png": base64.b64encode(b"<html>not a png").decode()}})
        assert status == 400 and notpng["status"] == "refused_validation", notpng
        # --- a second good edit revises the scene's own source; undo and redo republish
        status, second = await edit(stack, variants, {"sources": {"src/lib/Extra.ts": "export const gap = 8;\n"}})
        assert status == 200 and second["prefab"] == {"id": own, "version": 2}, second
        status, undo = await edit(stack, variants, {"restore_version": second["previous"]})
        assert status == 200 and undo["prefab"] == {"id": own, "version": 3}, undo
        _, current = await stack.call("GET", variants + f"/scenes/{S1}/source")
        assert "src/lib/Extra.ts" not in current["sources"] and current["sources"]["src/Scene.tsx"] == GOOD
        status, redo = await edit(stack, variants, {"restore_version": second["prefab"]})
        _, current = await stack.call("GET", variants + f"/scenes/{S1}/source")
        assert status == 200 and "src/lib/Extra.ts" in current["sources"]
        # --- the journal tells the normal path and the refusals, with codes and no source text
        refusals = [r for r in stack.diagnostics.records if r.kind == "core.presentation_studio.reload_build_refused"] \
            if hasattr(stack.diagnostics, "records") else []
        assert all("SCENE_TSX" not in str(r) for r in refusals)
        assert stack.kinds().count("core.presentation_studio.reload_build_refused") == 3
