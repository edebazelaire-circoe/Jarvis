"""Edition de source d'une scene Remotion, en direct, dans le VRAI Control Center, un VRAI Chrome, un Core isole (Slice 14).

Opt-in comme `test_remotion_controls_realpage_browser.py` (meme banc, meme harnais `scripts/remotion_player_harness.py --slice 14`) :
exige une installation Remotion existante (`JARVIS_REMOTION_RUNTIME_DIR`), Node et Chrome ; sans eux elle est ignoree.

Le chemin de l'agent, de bout en bout : il LIT la source (`GET .../scenes/{id}/source`), propose des fichiers `src/**` par
`POST .../source-edits` ; Core valide (chemins, gardes d'isolation, bornes, contrat des entrees), COMPILE avec le vrai esbuild, publie
une nouvelle version immuable, epingle, et la page charge la nouvelle scene A COTE de l'ancienne (echange en deux temps du
Player) sans recharger la page. Prouve, mesure dans le bac a sable :

1. une edition valide remplace la scene sans recharger la page (un marqueur pose dans la page survit) et sans interrompre la lecture ;
2. une erreur de syntaxe est refusee avec `fichier:ligne:colonne` AVANT toute publication : l'ancienne scene (meme document du bac
   a sable, meme marqueur de module) continue de jouer, aucune bande d'erreur, aucun repli HTML ;
3. une scene qui compile mais LEVE au rendu est publiee, epinglee, rejetee par le montage et ramenee en arriere : la derniere bonne
   version est de nouveau le pin, l'ancienne scene joue toujours ;
4. annuler (republier la version precedente) puis retablir.
"""

from __future__ import annotations

import pytest

from tests.fakes.remotion_player_stack import RemotionStack
from tests.unit.test_remotion_player_realpage_browser import (
    A, CONTROLS, PROPS, READY, RUNTIME, S1, SAMPLE, SANDBOX, SHELL, STAGE, http_step, noise, record_evidence, run, scene,
)

pytestmark = pytest.mark.skipif(RUNTIME is None, reason="needs JARVIS_REMOTION_RUNTIME_DIR (an existing Remotion install), node and Chrome")

SCENE_V1 = """import React from "react";
import {AbsoluteFill, useCurrentFrame} from "remotion";

const mounted = String(Math.random());   // evaluated once per sandbox document: a new document (a swap) changes it
const LABEL = "v1";
const BG = "#101820";

export default function Scene(props: {title: string; accent: string; fade: number}) {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill id="bg" style={{background: BG}}>
      <h1 id="title" style={{color: props.accent, fontSize: 90}}>{props.title + " " + LABEL}</h1>
      <p id="mark" style={{color: "#fff"}}>{mounted}</p>
      <p id="frame" style={{color: "#fff"}}>{String(frame)}</p>
    </AbsoluteFill>
  );
}
"""
SCENE_V2 = SCENE_V1.replace('"v1"', '"v2"').replace("#101820", "#7a1f3d").replace(
    'import {AbsoluteFill, useCurrentFrame} from "remotion";', 'import {AbsoluteFill, useCurrentFrame} from "remotion";\nimport {BADGE} from "./lib/badge";').replace(
    'props.title + " " + LABEL', 'props.title + " " + LABEL + BADGE')
BADGE_TS = 'export const BADGE = " [edit]";\n'
SYNTAX_BROKEN = SCENE_V2.replace("const frame = useCurrentFrame();", "const frame = useCurrentFrame()\n  const = ;")
THROWS = SCENE_V2.replace("const frame = useCurrentFrame();", 'const frame = useCurrentFrame();\n  if (frame >= 0) throw new Error("boom at render");')

LOOK = ("(()=>({title:document.querySelector('#title').textContent,bg:getComputedStyle(document.querySelector('#bg')).backgroundColor,"
        "mark:document.querySelector('#mark').textContent,frame:Number(document.querySelector('#frame').textContent)}))()")
PAGE_MARK = "(window.__sliceFourteen = window.__sliceFourteen || String(Math.random()))"
FRAMES = "document.querySelectorAll('iframe[data-remotion-stage]').length"
BANDS = "document.querySelectorAll('.sc-prefab-error').length"


def edit_files(stack: RemotionStack, variants: str, name: str, files: dict, actor: str = "user") -> dict:
    step = http_step(stack, name, "POST", variants + "/source-edits",
                     {"actor": actor, "basis": {"variant_revision": 0}, "scene_id": S1, "files": files})
    step["http"]["basisFrom"] = stack.core_url + variants
    return step


async def test_an_agent_edits_a_tsx_scene_while_it_plays_and_a_broken_edit_rolls_back(tmp_path):
    async with RemotionStack(tmp_path, runtime_dir=RUNTIME) as stack:
        await stack.publish(A, {"src/Scene.tsx": SCENE_V1}, title="Un", props=PROPS, sample=SAMPLE)
        pid, vid = await stack.presentation([scene(S1, A, "Premier")])
        variants = f"/v1/presentation-studio/presentations/{pid}/variants/{vid}"
        status, started = await stack.start(pid)
        assert status == 200 and started["state"]["phase"] == "playing", started
        shots = {name: str(tmp_path / f"{name}.png") for name in ("before", "edited", "broken", "restored")}
        result = await run(stack.page_url, [
            {"wait": 500}, READY, {"wait": 1000},
            {"value": "page_mark", "expr": PAGE_MARK},
            {"value": "initial", "expr": LOOK, **SANDBOX},
            {"shot": shots["before"]},
            http_step(stack, "source", "GET", variants + f"/scenes/{S1}/source"),
            # --- 1. a valid TSX edit through the agent door: built, published, swapped beside the old frame
            edit_files(stack, variants, "edit_ok", {"sources": {"src/Scene.tsx": SCENE_V2, "src/lib/badge.ts": BADGE_TS}}),
            {"until": "document.querySelector('#title') && document.querySelector('#title').textContent.endsWith('v2 [edit]')", "ms": 30000, **SANDBOX},
            {"wait": 800},
            {"value": "after_edit", "expr": LOOK, **SANDBOX},
            {"value": "page_mark_after_edit", "expr": PAGE_MARK},
            {"value": "frames_after_edit", "expr": FRAMES},
            {"value": "bands_after_edit", "expr": BANDS},
            {"value": "shell_after_edit", "expr": SHELL},
            {"shot": shots["edited"]},
            # --- 2. a syntax error: refused before publication, the scene on screen is the same document, still playing
            edit_files(stack, variants, "edit_syntax", {"sources": {"src/Scene.tsx": SYNTAX_BROKEN}}),
            {"wait": 900},
            {"value": "after_syntax_a", "expr": LOOK, **SANDBOX}, {"wait": 700},
            {"value": "after_syntax_b", "expr": LOOK, **SANDBOX},
            {"value": "bands_after_syntax", "expr": BANDS},
            {"value": "frames_after_syntax", "expr": FRAMES},
            {"shot": shots["broken"]},
            # --- 3. compiles, throws when it renders: published, pinned, rejected by the mount, rolled back
            edit_files(stack, variants, "edit_throws", {"sources": {"src/Scene.tsx": THROWS}}),
            {"wait": 1500},
            {"value": "after_throw", "expr": LOOK, **SANDBOX},
            {"value": "bands_after_throw", "expr": BANDS},
            {"value": "frames_after_throw", "expr": FRAMES},
            # --- 4. undo (the version before the valid edit), then redo
            edit_files(stack, variants, "undo", {"restore_version": {"id": A, "version": 1}}),
            {"until": "document.querySelector('#title') && document.querySelector('#title').textContent.endsWith('v1')", "ms": 30000, **SANDBOX},
            {"wait": 800},
            {"value": "after_undo", "expr": LOOK, **SANDBOX},
            {"shot": shots["restored"]},
            {"value": "page_mark_end", "expr": PAGE_MARK},
            {"value": "frames_end", "expr": FRAMES},
            {"value": "bands_end", "expr": BANDS},
        ])
        reads = result["reads"]
        assert "failed" not in reads, reads.get("failed")
        # ---- 1
        assert reads["source"]["status"] == 200 and reads["source"]["body"]["sources"]["src/Scene.tsx"] == SCENE_V1
        ok = reads["edit_ok"]
        assert ok["status"] == 200 and ok["body"]["status"] == "reloaded" and ok["body"]["mounted"] is True, ok
        assert ok["body"]["previous"] == {"id": A, "version": 1} and ok["body"]["prefab"]["id"].startswith("presentation-studio.")
        initial, edited = reads["initial"], reads["after_edit"]
        assert initial["title"].endswith("v1") and initial["bg"] == "rgb(16, 24, 32)"
        assert edited["title"].endswith("v2 [edit]") and edited["bg"] == "rgb(122, 31, 61)", "the new TSX is on screen"
        assert edited["mark"] != initial["mark"], "a new sandbox document was mounted (the swap), beside the old one"
        assert reads["page_mark_after_edit"] == reads["page_mark"], "the page was never reloaded"
        assert reads["frames_after_edit"] == 1 and reads["bands_after_edit"] == 0 and reads["shell_after_edit"]["phase"] == "ready"
        # ---- 2
        syntax = reads["edit_syntax"]
        assert syntax["status"] == 422 and syntax["body"]["status"] == "refused_validation", syntax
        assert syntax["body"]["error"]["code"] == "presentation_studio_source_build_failed"
        row = syntax["body"]["diagnostics"][0]
        assert row["file"] == "src/Scene.tsx" and row["line"] >= 1 and f"src/Scene.tsx:{row['line']}:{row['column']}" in syntax["body"]["message"]
        assert syntax["body"]["published"] is None, "nothing was published"
        assert reads["after_syntax_a"]["mark"] == edited["mark"] == reads["after_syntax_b"]["mark"], "the very same sandbox document keeps playing"
        assert reads["after_syntax_b"]["frame"] != reads["after_syntax_a"]["frame"] or reads["after_syntax_a"]["frame"] != edited["frame"], \
            "the old scene is still advancing"
        assert reads["after_syntax_b"]["title"] == edited["title"] and reads["after_syntax_b"]["bg"] == edited["bg"]
        assert reads["bands_after_syntax"] == 0 and reads["frames_after_syntax"] == 1
        # ---- 3
        thrown = reads["edit_throws"]
        assert thrown["status"] == 409 and thrown["body"]["status"] == "rolled_back", thrown
        assert thrown["body"]["error"]["code"] == "presentation_studio_mount_failed" and thrown["body"]["mounted"] is False
        assert thrown["body"]["prefab"] == ok["body"]["prefab"] and thrown["body"]["published"]["version"] == ok["body"]["prefab"]["version"] + 1
        assert reads["after_throw"]["title"] == edited["title"] and reads["after_throw"]["mark"] == edited["mark"], "the last good scene never stopped"
        assert reads["frames_after_throw"] == 1 and reads["bands_after_throw"] == 0
        # ---- 4
        undo = reads["undo"]
        assert undo["status"] == 200 and undo["body"]["status"] == "reloaded", undo
        assert reads["after_undo"]["title"].endswith("v1") and reads["after_undo"]["bg"] == "rgb(16, 24, 32)"
        assert reads["page_mark_end"] == reads["page_mark"] and reads["frames_end"] == 1 and reads["bands_end"] == 0
        assert not noise(result), noise(result)
        # ---- the state at rest: the pin is the undo's version (a NEW immutable revision), the rolled-back one is not pinned
        _, variant = await stack.call("GET", variants)
        pinned = variant["scenes"][0]
        assert pinned["prefab"] == undo["body"]["prefab"] and pinned["last_valid_pin"] is None
        assert pinned["prefab"]["id"] == ok["body"]["prefab"]["id"] and pinned["prefab"]["version"] == thrown["body"]["published"]["version"] + 1
        _, reloads = await stack.call("GET", f"/v1/presentation-studio/presentations/{pid}/reloads")
        statuses = [row["status"] for row in reloads["reloads"]]
        assert statuses == ["reloaded", "refused_validation", "rolled_back", "reloaded"], statuses
        kinds = stack.kinds()
        trace = [row["kind"] for row in stack.trace()]
        assert kinds.count("core.presentation_studio.reload_build_refused") == 1 and "core.presentation_studio.reload_built" in kinds
        record_evidence("source_edit_hmr", {
            "reads": reads, "console": result["console"][-30:], "errors": result["errors"], "journal": sorted(set(kinds) | set(trace)),
            "reload_statuses": statuses, "pinned_at_rest": pinned["prefab"],
            "compilations": kinds.count("remotion.compile.done"), "build_refused": kinds.count("core.presentation_studio.reload_build_refused")},
            *shots.values())
