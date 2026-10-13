import React from "react";
import {AbsoluteFill, interpolate, useCurrentFrame} from "remotion";
import {C, MONO, Reveal, Stage, useIn} from "./lib/kit";

const Wave: React.FC = () => {
  const frame = useCurrentFrame();
  const e = useIn(60);
  const bars = 33;
  return (
    <svg width={1680} height={220} viewBox="0 0 1680 220" style={{opacity: e}}>
      {Array.from({length: bars}).map((_, i) => {
        const x = 20 + i * 51;
        const env = Math.sin((i / (bars - 1)) * Math.PI);
        const h = 14 + env * 150 * (0.5 + 0.5 * Math.sin(frame / 5 + i * 0.7)) * e;
        return <rect key={i} x={x} y={110 - h / 2} width={22} height={h} rx={11} fill={C.accent} opacity={0.35 + 0.65 * env} />;
      })}
    </svg>
  );
};

export default function Scene() {
  const frame = useCurrentFrame();
  const line = interpolate(frame, [20, 60], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <Stage eyebrow="Assistant vocal local">
      <AbsoluteFill style={{padding: "0 120px", justifyContent: "center"}}>
        <Reveal delay={6} dy={50}><div style={{fontSize: 220, fontWeight: 800, letterSpacing: -4, lineHeight: 1}}>JARVIS</div></Reveal>
        <div style={{height: 8, width: 760 * line, background: C.accent, borderRadius: 4, margin: "20px 0 36px"}} />
        <Reveal delay={30}><div style={{fontSize: 56, color: C.text}}>Tu parles. Il agit.</div></Reveal>
        <Reveal delay={46}><div style={{fontSize: 36, color: C.mute, marginTop: 14}}>Local-first, sur ton poste.</div></Reveal>
        <div style={{marginTop: 60}}><Wave /></div>
        <Reveal delay={120}><div style={{fontFamily: MONO, fontSize: 30, color: C.mute}}>push-to-talk  ·  touche <span style={{color: C.accent}}>F9</span></div></Reveal>
      </AbsoluteFill>
    </Stage>
  );
}
