import React from "react";
import {interpolate, useCurrentFrame} from "remotion";
import {C, FONT, MONO, Reveal, Stage} from "./lib/ui";

const clamp = {extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const};
const STEPS = ["Proposition", "Validation humaine", "Application", "Rollback"];
const XS = [330, 750, 1170, 1590];
const LY = 520;
const FACTS = ["Aucune suppression définitive", "Aucune écriture hors racine", "Aucun écrasement silencieux"];

const Flow: React.FC = () => {
  const frame = useCurrentFrame();
  const prog = interpolate(frame, [36, 126], [0, 1], clamp);
  const arc = interpolate(frame, [136, 176], [1, 0], clamp);
  const arcDone = interpolate(frame, [172, 180], [0, 1], clamp);
  const lineEnd = XS[0] + prog * (XS[3] - XS[0]);
  return (
    <svg width={1920} height={1080} style={{position: "absolute", left: 0, top: 0}}>
      <line x1={XS[0]} y1={LY} x2={XS[3]} y2={LY} stroke={C.line} strokeWidth={6} strokeLinecap="round" />
      <line x1={XS[0]} y1={LY} x2={lineEnd} y2={LY} stroke={C.accent} strokeWidth={6} strokeLinecap="round" />
      <path d={`M${XS[3]} ${LY - 70} Q960 ${LY - 380} ${XS[0] + 18} ${LY - 66}`} fill="none" stroke={C.accent} strokeWidth={4} strokeLinecap="round" pathLength={1} strokeDasharray="1 1" strokeDashoffset={arc} />
      <path d={`M${XS[0] + 52} ${LY - 96} L${XS[0] + 16} ${LY - 66} L${XS[0] + 58} ${LY - 58}`} fill="none" stroke={C.accent} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" opacity={arcDone} />
      <text x={960} y={LY - 250} textAnchor="middle" fontSize={30} fontFamily={MONO} fill={C.mute} opacity={interpolate(frame, [150, 170], [0, 1], clamp)}>retour arrière possible</text>
      {STEPS.map((s, i) => {
        const t = 36 + i * 30;
        const act = interpolate(frame, [t, t + 12], [0, 1], clamp);
        const key = i === 1;
        const r = key ? 62 : 46;
        const ph = ((frame - t) % 50) / 50;
        const pulse = key ? 1 + 0.5 * ph : 0;
        return (
          <g key={s} opacity={0.35 + 0.65 * act}>
            {key && act > 0.99 && <circle cx={XS[i]} cy={LY} r={r * pulse} fill="none" stroke={C.accent} strokeWidth={3} strokeOpacity={1 - ph} />}
            <circle cx={XS[i]} cy={LY} r={r} fill={key ? `rgba(124,240,196,${act})` : C.panel} stroke={C.accent} strokeOpacity={act} strokeWidth={4} />
            <text x={XS[i]} y={LY + (key ? 17 : 14)} textAnchor="middle" fontSize={key ? 52 : 40} fontWeight={700} fontFamily={FONT} fill={key && act > 0.5 ? C.bg : C.text}>{i + 1}</text>
            <text x={XS[i]} y={LY + 130} textAnchor="middle" fontSize={42} fontWeight={key ? 700 : 500} fontFamily={FONT} fill={key ? C.accent : C.text}>{s}</text>
          </g>
        );
      })}
      {FACTS.map((f, i) => {
        const e = interpolate(frame, [160 + i * 18, 178 + i * 18], [0, 1], clamp);
        const x = 120 + i * 580;
        return (
          <g key={f} opacity={e} transform={`translate(${x},${800 + (1 - e) * 30})`}>
            <rect width={520} height={96} rx={22} fill={C.panel} stroke={C.line} strokeWidth={2} />
            <circle cx={50} cy={48} r={20} fill="none" stroke={C.accent} strokeWidth={3} />
            <path d="M40 48 L47 55 L60 40" fill="none" stroke={C.accent} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" />
            <text x={88} y={58} fontSize={29} fontFamily={FONT} fill={C.text}>{f}</text>
          </g>
        );
      })}
    </svg>
  );
};

export default function Scene() {
  return (
    <Stage>
      <div style={{position: "absolute", left: 120, right: 120, top: 100}}>
        <Reveal delay={4}><h2 style={{fontSize: 80, margin: 0, fontWeight: 700, letterSpacing: -2}}>Rien ne change sans votre accord</h2></Reveal>
        <Reveal delay={16}><p style={{fontSize: 36, color: C.mute, margin: "14px 0 0"}}>Restructurations révisables</p></Reveal>
      </div>
      <Flow />
    </Stage>
  );
}
