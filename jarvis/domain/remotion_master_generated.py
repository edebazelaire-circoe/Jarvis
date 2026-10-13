"""Generated files of a master Remotion project (`docs/remotion-master-project.md` §6-7). Pure: values in, bytes out.

The generated set is path-based: `package.json`, `studio-root.tsx`, `src/master/**`. Its bytes depend only on `project_key` inputs (the
master spec, the ordered scenes with their mounted entry, duration and merged props), never on a title, a revision or a clock, so the same
plan gives the same files on every machine. The planner (Slice 03, `remotion_master_project`) counts them in `totals`; Slice 04's
`plan_master_files` writes them beside the copied scene sources and proves them against the pinned Remotion (bundle, composition, boundary).
Bump `MASTER_GENERATOR_VERSION` (in `remotion_master_project`) whenever these bytes change for the same inputs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any

MASTER_COMPOSITION_ID = "JarvisPresentation"
MASTER_PACKAGE_NAME = "jarvis-studio-master"
ROOT_FILE = "studio-root.tsx"
PACKAGE_FILE = "package.json"
GENERATED_DIR = "src/master/"
PRESENTATION_FILE = GENERATED_DIR + "Presentation.tsx"
BOUNDARY_FILE = GENERATED_DIR + "SceneBoundary.tsx"
SCENE_FAILED_PREFIX = "jarvis_master_scene_failed"
_HEADER = "// Généré par Jarvis (docs/remotion-master-project.md) : ne pas modifier, vue dérivée d'une variante de présentation."


@dataclass(frozen=True, slots=True)
class GeneratedScene:
    """What the generated composition needs of one mounted scene: its id, 1-based position, mounted entry, duration and merged props."""

    scene_id: str
    position: int
    entry: str  # workspace-relative, e.g. "src/scenes/pss_x/Scene.tsx"
    duration_in_frames: int
    props: Mapping[str, Any]


def is_generated(path: str) -> bool:
    return path in (PACKAGE_FILE, ROOT_FILE) or path.startswith(GENERATED_DIR)


def _import_from_master(entry: str) -> str:
    """`src/scenes/<id>/Scene.tsx` seen from `src/master/`: `../scenes/<id>/Scene` (no extension, as the bundler resolves it)."""

    stem = entry.rsplit(".", 1)[0]
    return "../" + stem.removeprefix("src/")


def _js(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def generated_files(*, width: int, height: int, fps: int, scenes: Sequence[GeneratedScene]) -> dict[str, bytes]:
    """The exact generated set for these scenes under this spec (duration = sum of the scene durations)."""

    duration = sum(scene.duration_in_frames for scene in scenes)
    root = "\n".join((
        _HEADER,
        "import React from 'react';",
        "import {Composition, registerRoot} from 'remotion';",
        "import {Presentation} from './src/master/Presentation';",
        "const Root = () => (",
        f"  <Composition id={_js(MASTER_COMPOSITION_ID)} component={{Presentation}} durationInFrames={{{duration}}}",
        f"    fps={{{fps}}} width={{{width}}} height={{{height}}} defaultProps={{{{}}}} />",
        ");",
        "registerRoot(Root);",
        "",
    ))
    lines = [_HEADER, "import React from 'react';", "import {Series} from 'remotion';", "import {SceneBoundary} from './SceneBoundary';"]
    lines += [f"import Scene{s.position} from {_js(_import_from_master(s.entry))};" for s in scenes]
    lines += [f"const props{s.position}: Record<string, unknown> = {_js(dict(s.props))};" for s in scenes]
    lines += ["export const Presentation: React.FC = () => (", "  <Series>"]
    for s in scenes:
        lines += [f"    <Series.Sequence durationInFrames={{{s.duration_in_frames}}}>",
                  f"      <SceneBoundary sceneId={_js(s.scene_id)} position={{{s.position}}}><Scene{s.position} {{...(props{s.position} as any)}} />"
                  "</SceneBoundary>",
                  "    </Series.Sequence>"]
    lines += ["  </Series>", ");", ""]
    boundary = "\n".join((
        _HEADER,
        "import React from 'react';",
        "import {AbsoluteFill, cancelRender, getRemotionEnvironment} from 'remotion';",
        "type Props = {sceneId: string; position: number; children?: React.ReactNode};",
        "type State = {message: string | null};",
        "const describe = (error: unknown): string => (error instanceof Error ? error.message : String(error));",
        "export class SceneBoundary extends React.Component<Props, State> {",
        "  state: State = {message: null};",
        "  static getDerivedStateFromError(error: unknown): State {",
        "    return {message: describe(error)};",
        "  }",
        "  componentDidCatch(error: unknown) {",
        "    if (getRemotionEnvironment().isRendering) {",
        f"      cancelRender(new Error(`{SCENE_FAILED_PREFIX}:${{this.props.sceneId}}:${{this.props.position}}: ${{describe(error)}}`));",
        "    }",
        "  }",
        "  render() {",
        "    if (this.state.message === null) return this.props.children;",
        "    return (",
        "      <AbsoluteFill style={{background: '#2b0d0d', color: '#ffffff', justifyContent: 'center', alignItems: 'center',",
        "        fontSize: 40, padding: 60, textAlign: 'center'}}>",
        "        {`Scène ${this.props.position} (${this.props.sceneId}) : erreur — ${this.state.message}`}",
        "      </AbsoluteFill>",
        "    );",
        "  }",
        "}",
        "",
    ))
    package = json.dumps({"name": MASTER_PACKAGE_NAME, "private": True, "version": "0.0.0"})
    return {PACKAGE_FILE: package.encode("utf-8"), ROOT_FILE: root.encode("utf-8"),
            PRESENTATION_FILE: "\n".join(lines).encode("utf-8"), BOUNDARY_FILE: boundary.encode("utf-8")}
