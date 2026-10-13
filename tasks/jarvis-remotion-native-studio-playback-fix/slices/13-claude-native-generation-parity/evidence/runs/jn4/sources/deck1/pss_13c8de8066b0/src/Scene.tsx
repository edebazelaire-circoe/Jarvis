import React from "react";
import {AbsoluteFill, interpolate, useCurrentFrame} from "remotion";
import {C, MONO, Reveal, Stage, useIn} from "./lib/kit";

const Typed: React.FC<{text: string; start: number; cps?: number}> = ({text, start, cps = 1.2}) => {
  const frame = useCurrentFrame();
  const n = Math.max(0, Math.min(text.length, Math.floor((frame - start) * cps)));
  const done = n >= text.length;
  const blink = Math.floor(frame / 15) % 2 === 0;
  return (
    <div style={{fontFamily: MONO, fontSize: 40, color: C.text, height: 56, whiteSpace: "pre"}}>
      <span style={{color: C.accent}}>$ </span>{text.slice(0, n)}{(!done || blink) && frame >= start ? <span style={{color: C.accent}}>▌</span> : null}
    </div>
  );
};

const Proc: React.FC<{name: string; sub: string; i: number}> = ({name, sub, i}) => {
  const e = useIn(150 + i * 14, 16);
  return (
    <div style={{opacity: e, transform: `translateY(${(1 - e) * 30}px)`, flex: 1, borderRadius: 20, border: `3px solid ${C.line}`, background: C.panel, padding: "24px 32px"}}>
      <div style={{fontFamily: MONO, fontSize: 40, color: C.accent, fontWeight: 700}}>{name}</div>
      <div style={{fontSize: 28, color: C.mute, marginTop: 6}}>{sub}</div>
    </div>
  );
};

export default function Scene() {
  const win = useIn(14, 18);
  const end = interpolate(useCurrentFrame(), [200, 240], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <Stage eyebrow="Prêt à l'essai">
      <Reveal delay={6}><div style={{fontSize: 96, fontWeight: 800, marginTop: 24, letterSpacing: -1}}>Lance JARVIS sur ton poste.</div></Reveal>
      <div style={{opacity: win, transform: `translateY(${(1 - win) * 40}px)`, marginTop: 56, borderRadius: 24, background: C.panel, border: `3px solid ${C.line}`, overflow: "hidden"}}>
        <div style={{height: 52, borderBottom: `2px solid ${C.line}`, display: "flex", alignItems: "center", gap: 12, padding: "0 24px"}}>
          {[0, 1, 2].map((k) => <div key={k} style={{width: 18, height: 18, borderRadius: 9, background: C.line}} />)}
        </div>
        <div style={{padding: "28px 40px", display: "flex", flexDirection: "column", gap: 14}}>
          <Typed text="python -m jarvis health" start={40} />
          <Typed text="python scripts/dev_start.py" start={90} />
        </div>
      </div>
      <div style={{display: "flex", gap: 28, marginTop: 44}}>
        <Proc name="core" sub="état, outils, cerveau" i={0} />
        <Proc name="voice" sub="éveil et session vocale" i={1} />
        <Proc name="control-center" sub="panneau dans le navigateur" i={2} />
      </div>
      <AbsoluteFill style={{justifyContent: "flex-end", alignItems: "flex-end", padding: "0 120px 90px"}}>
        <div style={{opacity: end, fontSize: 56, fontWeight: 800}}>JARVIS<span style={{color: C.accent}}>.</span></div>
      </AbsoluteFill>
    </Stage>
  );
}
