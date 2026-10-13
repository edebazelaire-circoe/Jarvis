"""Slice 01 control project: a hand-written 'master' Remotion project with per-scene sources under src/scenes/<id>/.

Usage: python build_project.py <work_dir> <media_dir> [--with-clip]
Writes work/{package.json, studio-root.tsx, src/master/*, src/scenes/<id>/**, public/**}. Throw-away; no Jarvis code involved.
"""
import json, shutil, sys
from pathlib import Path

work, media = Path(sys.argv[1]), Path(sys.argv[2])
with_clip = "--with-clip" in sys.argv
if work.exists():
    shutil.rmtree(work)
(work / "public").mkdir(parents=True)

def w(rel, text):
    p = work / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")

# Every scene carries its OWN copy of these modules (relative imports, incl. ../.. from a nested module) - item 5.
PANEL = """import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {accent} from './deep/theme';
export const Panel: React.FC<{name: string; color: string; children?: React.ReactNode}> = ({name, color, children}) => {
  const frame = useCurrentFrame();
  const {width, height, fps, durationInFrames} = useVideoConfig();
  console.log(`PROBE|${name}|${frame}|${width}x${height}@${fps}|${durationInFrames}`);
  return (
    <AbsoluteFill style={{background: color, color: 'white', fontFamily: 'monospace', fontSize: Math.round(height / 12), padding: 12}}>
      <div>scene {name} f={frame}</div>
      <div>{width}x{height}@{fps} d={durationInFrames}</div>
      <div style={{width: 40, height: 8, background: accent}} />
      {children}
    </AbsoluteFill>
  );
};
"""
THEME = "export {accent} from '../../palette';\n"
PALETTE = "export const accent = '#ffd400';\n"

SCENES = {
    "a": ("#334", "", ""),
    "b": ("#363", "Audio, staticFile", "<Audio src={staticFile('tone.wav')} />"),
    "c": ("#633", "OffthreadVideo, staticFile", "<OffthreadVideo src={staticFile('clip.mp4')} style={{width: '50%'}} />"),
    "c2": ("#636", "Video, staticFile", "<Video src={staticFile('clip.mp4')} style={{width: '50%'}} />"),
    # authored for 60 fps / 120 frames (2 s): one bar driven by frames, one by seconds (frame / fps)
    "d60": ("#225", "interpolate", """<div style={{height: 20, width: `${interpolate(useCurrentFrame(), [0, 120], [0, 100], {extrapolateRight: 'clamp'})}%`, background: 'orange'}} />
        <div style={{height: 20, width: `${Math.min(100, useCurrentFrame() / useVideoConfig().fps / 2 * 100)}%`, background: 'cyan'}} />"""),
    # authored for 360x640 portrait: a marker meant for the bottom-right corner, placed from useVideoConfig()
    "e": ("#552", "", """<div style={{position: 'absolute', left: useVideoConfig().width - 60, top: useVideoConfig().height - 60, width: 50, height: 50, background: 'magenta'}} />"""),
    "f": ("#444", "Img, staticFile", "<Img src={staticFile('x.png')} style={{width: 120, height: 120}} />"),   # its own public/x.png = red
    "g": ("#444", "Img, staticFile", "<Img src={staticFile('x.png')} style={{width: 120, height: 120}} />"),   # its own public/x.png = blue
    "h": ("#444", "Img, staticFile", "<Img src={staticFile('logo.png')} style={{width: 120, height: 120}} />"),  # asset namespaced, string not rewritten
    "t": ("#800", "", "{useCurrentFrame() >= 5 ? (() => { throw new Error('scene t exploded at local frame 5'); })() : null}"),
}
for sid, (color, extra, body) in SCENES.items():
    base = f"src/scenes/{sid}/"
    w(base + "palette.ts", PALETTE)
    w(base + "parts/deep/theme.ts", THEME)
    w(base + "parts/Panel.tsx", PANEL.replace("from './deep/theme'", "from './deep/theme'"))
    imports = "AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate" + (", " + extra if extra and "interpolate" not in extra else "")
    w(base + "Scene.tsx", f"""import React from 'react';
import {{{imports}}} from 'remotion';
import {{Panel}} from './parts/Panel';
export default function Scene() {{
  return <Panel name={json.dumps(sid)} color={json.dumps(color)}>{body}</Panel>;
}}
""")

w("src/master/Boundary.tsx", """import React from 'react';
import {AbsoluteFill} from 'remotion';
export class Boundary extends React.Component<{name: string; children: React.ReactNode}, {error: string | null}> {
  state = {error: null as string | null};
  static getDerivedStateFromError(e: Error) { return {error: String(e && e.message)}; }
  render() {
    if (this.state.error) return <AbsoluteFill style={{background: 'black', color: 'red', fontSize: 24}}>scene {this.props.name} failed: {this.state.error}</AbsoluteFill>;
    return this.props.children;
  }
}
""")

# A master = ordered (scene, durationInFrames[, width, height]) list mounted in <Series>.
MASTERS = {
    "MASTER_OK": (640, 360, 30, [("a", 30), ("b", 45), ("c", 60), ("c2", 45)], False),
    "MASTER_MIXED": (640, 360, 30, [("a", 30), ("d60", 120), ("e", 30)], False),
    "MASTER_SEQDIMS": (640, 360, 30, [("e", 30, 360, 640)], False),
    "MASTER_COLLIDE": (640, 360, 30, [("f", 15), ("g", 15)], False),
    "MASTER_NS": (640, 360, 30, [("h", 15)], False),
    "MASTER_THROW_BOUNDARY": (640, 360, 30, [("a", 10), ("t", 20), ("b", 10)], True),
    "MASTER_THROW_RAW": (640, 360, 30, [("a", 10), ("t", 20), ("b", 10)], False),
    "PERF_1080": (1920, 1080, 30, [("a", 50), ("b", 50), ("c", 50)], False),
    "PERF_1080_LONG": (1920, 1080, 30, [("a", 200), ("b", 200), ("c", 200)], False),
}
used = sorted({s[0] for m in MASTERS.values() for s in m[3]})
lines = ["import React from 'react';", "import {Series, Sequence, AbsoluteFill} from 'remotion';", "import {Boundary} from './Boundary';"]
lines += [f"import Scene_{s} from '../scenes/{s}/Scene';" for s in used]
for name, (_w, _h, _fps, items, boundary) in MASTERS.items():
    body = []
    for item in items:
        sid, dur = item[0], item[1]
        dims = f" width={{{item[2]}}} height={{{item[3]}}}" if len(item) > 2 else ""
        inner = f"<Boundary name={json.dumps(sid)}><Scene_{sid} /></Boundary>" if boundary else f"<Scene_{sid} />"
        if dims:
            inner = f"<Sequence{dims}>{inner}</Sequence>"
        body.append(f"    <Series.Sequence durationInFrames={{{dur}}} name={json.dumps(sid)}>{inner}</Series.Sequence>")
    lines += [f"export const {name}: React.FC = () => (", "  <Series>", *body, "  </Series>", ");"]
w("src/master/Presentation.tsx", "\n".join(lines) + "\n")

clip = """const Clip: React.FC = () => {
  const f = useCurrentFrame();
  return <AbsoluteFill style={{background: '#111'}}><div style={{position: 'absolute', left: f * 4, top: 60, width: 60, height: 60, background: 'lime'}} /><Audio src={staticFile('tone.wav')} /></AbsoluteFill>;
};"""
root = ["// Slice 01 control root (hand-written stand-in for a generated master root).", "import React from 'react';",
        "import {Composition, registerRoot, AbsoluteFill, Audio, staticFile, useCurrentFrame} from 'remotion';",
        "import * as M from './src/master/Presentation';", clip, "const Root = () => (", "  <>",
        "    <Composition id=\"CLIP\" component={Clip} durationInFrames={60} fps={30} width={320} height={180} />"]
for name, (cw, ch, fps, items, _b) in MASTERS.items():
    total = sum(i[1] for i in items)
    root.append(f"    <Composition id=\"{name.replace('_', '-')}\" component={{M.{name}}} durationInFrames={{{total}}} fps={{{fps}}} width={{{cw}}} height={{{ch}}} />")
root += ["  </>", ");", "registerRoot(Root);", ""]
w("studio-root.tsx", "\n".join(root))
w("package.json", json.dumps({"name": "jarvis-s01-control-master", "private": True, "version": "0.0.0"}))

# Merged public/: scene f brought x.png = red, scene g brought x.png = blue; only ONE file can exist at public/x.png.
shutil.copy(media / "tone.wav", work / "public/tone.wav")
shutil.copy(media / "red.png", work / "public/x.png")          # f's copy wins (first-writer); g's blue is lost
(work / "public/scenes/h").mkdir(parents=True)
shutil.copy(media / "blue.png", work / "public/scenes/h/logo.png")  # namespaced WITHOUT rewriting staticFile('logo.png')
if with_clip:
    shutil.copy(media / "clip.mp4", work / "public/clip.mp4")
print("built", work, "scenes:", used)
