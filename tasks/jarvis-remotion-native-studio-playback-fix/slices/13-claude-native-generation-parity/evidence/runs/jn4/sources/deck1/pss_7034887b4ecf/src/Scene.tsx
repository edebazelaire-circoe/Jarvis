import React from "react";
import {AbsoluteFill, interpolate, useCurrentFrame} from "remotion";
import {C, MONO, Reveal, Stage, useIn} from "./lib/kit";

const STEPS = [
  {t: "Ta voix", s: "push-to-talk"},
  {t: "Transcription", s: "OpenAI"},
  {t: "Agent", s: "OpenAI"},
  {t: "Outils", s: "3 outils"},
  {t: "Réponse", s: "voix TTS"},
];
const W = 288, GAP = 60, Y = 130, H = 240;

const Node: React.FC<{i: number; lit: number}> = ({i, lit}) => {
  const e = useIn(24 + i * 14, 14);
  const x = i * (W + GAP);
  return (
    <g transform={`translate(${x},${Y + (1 - e) * 30})`} opacity={e}>
      <rect width={W} height={H} rx={26} fill={C.panel} stroke={lit > 0.5 ? C.accent : C.line} strokeWidth={lit > 0.5 ? 5 : 3} />
      <text x={W / 2} y={118} textAnchor="middle" fill={C.text} fontSize={38} fontWeight={700}>{STEPS[i].t}</text>
      <text x={W / 2} y={174} textAnchor="middle" fill={lit > 0.5 ? C.accent : C.mute} fontSize={30} fontFamily={MONO}>{STEPS[i].s}</text>
    </g>
  );
};

export default function Scene() {
  const frame = useCurrentFrame();
  const total = 4 * (W + GAP);
  const t = (((frame - 100) % 120) + 120) % 120 / 120;
  const dotX = W / 2 + t * total;
  const started = frame >= 100;
  const cy = Y + H / 2;
  return (
    <Stage eyebrow="Comment ça marche">
      <Reveal delay={6}><div style={{fontSize: 84, fontWeight: 800, marginTop: 24, letterSpacing: -1}}>De ta voix à sa réponse</div></Reveal>
      <AbsoluteFill style={{padding: "290px 120px 0"}}>
        <svg width={1680} height={520} viewBox="0 0 1680 520">
          {STEPS.slice(0, 4).map((_, i) => {
            const x1 = i * (W + GAP) + W + 6, x2 = (i + 1) * (W + GAP) - 6;
            const p = interpolate(frame, [40 + i * 14, 58 + i * 14], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
            return <g key={i}><line x1={x1} y1={cy} x2={x1 + (x2 - x1) * p} y2={cy} stroke={C.mute} strokeWidth={5} /><polygon points={`${x2 + 4},${cy} ${x2 - 14},${cy - 11} ${x2 - 14},${cy + 11}`} fill={C.mute} opacity={p > 0.95 ? 1 : 0} /></g>;
          })}
          {STEPS.map((_, i) => {
            const cx = i * (W + GAP) + W / 2;
            const lit = started ? Math.max(0, 1 - Math.abs(dotX - cx) / 170) : 0;
            return <Node key={i} i={i} lit={lit} />;
          })}
          {started ? <circle cx={dotX} cy={cy} r={16} fill={C.accent} /> : null}
        </svg>
      </AbsoluteFill>
      <AbsoluteFill style={{padding: "0 120px 96px", justifyContent: "flex-end"}}>
        <Reveal delay={150}><div style={{fontSize: 36, color: C.mute}}>Transcription, agent et voix passent par OpenAI : <span style={{color: C.text}}>le réseau reste nécessaire.</span></div></Reveal>
      </AbsoluteFill>
    </Stage>
  );
}
