"""Sources de scène Remotion partagées par les tests de la Slice 05 (domaine, magasin, compilateur, harnais).

`scene_files()` : une scène réelle à trois modules (dont `src/lib/Title.tsx`) et un asset PNG ; `scene_candidate()` en fait
un candidat `{manifest, sources, assets}` valide pour `PrefabService.save`.
"""

from __future__ import annotations

import base64
from typing import Any

from jarvis.domain.remotion_source import Composition, EnginePin, build_candidate

#: PNG 1x1 valide (octets réels, pas du texte).
PNG_1X1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==")
ENGINE = EnginePin("remotion", "4.0.534", "19.3.0", "a" * 64)
COMPOSITION = Composition("Scene", 1280, 720, 30, 90)
PROPS_SCHEMA = {"type": "object", "properties": {
    "title": {"type": "string", "default": "Bonjour", "max_length": 80},
    "accent": {"type": "color", "default": "#3366ff"}}}
SAMPLE = {"props": {"title": "Bonjour", "accent": "#3366ff"}, "data": {}}

SCENE_TSX = """import React from "react";
import {AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame} from "remotion";
import {Title} from "./lib/Title";
import {palette} from "./theme.json";

export default function Scene(props: {title: string; accent: string}) {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 10], [0, 1], {extrapolateRight: "clamp"});
  return (
    <AbsoluteFill style={{background: palette.background, opacity}}>
      <Title text={props.title} color={props.accent} />
      <Img src={staticFile("dot.png")} style={{width: 16, height: 16}} />
    </AbsoluteFill>
  );
}
"""
TITLE_TSX = """import React from "react";
export const Title = ({text, color}: {text: string; color: string}) => <h1 style={{color}}>{text}</h1>;
"""
THEME_JSON = '{"palette": {"background": "#101820"}}\n'


def scene_files(title_suffix: str = "") -> dict[str, str | bytes]:
    return {"src/Scene.tsx": SCENE_TSX, "src/lib/Title.tsx": TITLE_TSX + title_suffix, "src/theme.json": THEME_JSON,
            "public/dot.png": PNG_1X1}


def scene_candidate(prefab_id: str = "presentation-studio.p000000000001.s000000000001", **changes: Any) -> dict[str, Any]:
    files = changes.pop("files", None) or scene_files()
    options: dict[str, Any] = {"prefab_id": prefab_id, "title": "Scène de test", "composition": COMPOSITION, "engine": ENGINE,
                               "files": files, "props": PROPS_SCHEMA, "sample": SAMPLE}
    options.update(changes)
    return build_candidate(**options)
