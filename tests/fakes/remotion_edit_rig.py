"""Banc de l'edition de source REMOTION (handoff jarvis-remotion-presentation-integration, Slice 14).

Le banc du rechargement a chaud (`tests/fakes/presentation_studio_reload.py`, tout reel sauf le navigateur) avec deux scenes dont le
prefab est une SOURCE Remotion (`lab.remotion@1`, publiee par le vrai `PrefabService`). Le compilateur est remplace par
`FakeBuilder`, qui obeit au contrat de `RemotionPlayerService.check_build` : il leve la meme `RemotionCompileError` typee
(fichier, ligne, colonne) quand un module porte `SYNTAX_ERROR`, compte ses appels et mesure la concurrence. La compilation reelle
(Node + esbuild) est prouvee par `test_remotion_source_edit_real.py` et par le harnais Chrome.
"""

from __future__ import annotations

import asyncio
from typing import Any

from jarvis.domain.presentation_studio_checks import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.remotion_compile import CompileDiagnostic, CompileErrorCode, RemotionCompileError
from tests.fakes.presentation_studio_reload import SID, SID2, Rig, scene_body
from tests.fakes.remotion_scene import ENGINE, PROPS_SCHEMA, SAMPLE, scene_candidate

BASE = "lab.remotion"
REMOTION_CONTROLS = [
    {"control_id": "headline", "path": "props.title", "label": "Titre", "group": "content"},
    {"control_id": "accent", "path": "props.accent", "label": "Accent", "group": "visual", "default": "#3366ff"},
]
SCENE_TSX = """import React from "react";
import {AbsoluteFill} from "remotion";
import {Title} from "./lib/Title";

export default function Scene(props: {title: string; accent: string}) {
  return <AbsoluteFill style={{background: "#101820"}}><Title text={props.title} color={props.accent} /></AbsoluteFill>;
}
"""
TITLE_TSX = 'import React from "react";\nexport const Title = ({text, color}: {text: string; color: string}) => <h1 style={{color}}>{text}</h1>;\n'
EDITED_TITLE = TITLE_TSX.replace("<h1", '<h1 id="t"')


def remotion_scene(scene_id: str = SID, **changes: Any) -> dict:
    return scene_body(scene_id, (BASE, 1), props={"title": "Bonjour", "accent": "#3366ff"}, data={}, controls=REMOTION_CONTROLS,
                      anchors=[{"anchor_id": "reveal", "label": "Reveler", "control_id": "headline"}], **changes)


class FakeBuilder:
    """`check_build(source)` comme `RemotionPlayerService` : compile ou leve une erreur typee."""

    def __init__(self, delay_s: float = 0.0) -> None:
        self.calls: list[dict[str, Any]] = []
        self.delay_s, self.unavailable = delay_s, False
        self.active = self.peak = 0

    async def check_build(self, source: Any) -> dict[str, Any]:
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            self.calls.append({"digest": source.digest, "modules": source.module_texts(), "assets": sorted(source.block.assets)})
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
            if self.unavailable:
                raise PresentationStudioError(C.ENGINE_UNAVAILABLE, "remotion is unavailable: the capability needs repair")
            for path, text in source.module_texts().items():
                marker = text.find("SYNTAX_ERROR")
                if marker >= 0:
                    line = text.count("\n", 0, marker) + 1
                    column = marker - (text.rfind("\n", 0, marker) + 1)
                    raise RemotionCompileError(CompileErrorCode.SOURCE_ERROR, "the scene source has a syntax error",
                                               diagnostics=(CompileDiagnostic(path, line, column, 'Expected ";" but found "SYNTAX_ERROR"'),))
            return {"cache_key": "scene-" + source.digest[:32], "reused": False, "duration_ms": 1, "engine_drift": False}
        finally:
            self.active -= 1


class RemotionRig(Rig):
    """Deux scenes Remotion (SID, SID2) de la meme source `lab.remotion@1`."""

    def __init__(self, tmp_path, *, builder: Any = "default", **options: Any) -> None:
        self.fake = FakeBuilder() if builder == "default" else builder
        super().__init__(tmp_path, builder=self.fake, **options)

    async def open(self, scenes=None, **options: Any) -> "RemotionRig":
        return await super().open([remotion_scene(), remotion_scene(SID2, title="Milieu")] if scenes is None else scenes, **options)

    async def seed(self) -> None:
        files = {"src/Scene.tsx": SCENE_TSX, "src/lib/Title.tsx": TITLE_TSX}
        await self.prefabs.save(scene_candidate(BASE, engine=ENGINE, title="Base Remotion", files=files, props=PROPS_SCHEMA,
                                                sample=SAMPLE), actor="user")

    def prefabs_ids(self) -> list[str]:
        from jarvis.adapters.file_prefab_library import LIBRARY_DIR
        return sorted(item.name for item in (self.data / LIBRARY_DIR).iterdir() if item.is_dir() and not item.name.startswith("."))

    async def source_of(self, ref) -> dict[str, str]:
        found = await self.prefabs.remotion_source(ref.prefab_id, ref.version)
        return found.module_texts()


__all__ = ["BASE", "EDITED_TITLE", "FakeBuilder", "RemotionRig", "SCENE_TSX", "SID", "SID2", "TITLE_TSX", "remotion_scene"]
