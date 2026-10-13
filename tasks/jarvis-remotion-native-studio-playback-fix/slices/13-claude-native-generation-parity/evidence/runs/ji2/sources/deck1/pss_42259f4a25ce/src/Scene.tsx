import React from "react";
import {Easing, interpolate, useCurrentFrame} from "remotion";
import {C, FONT, MONO, Reveal, Stage, useEnter} from "./lib/ui";

const FORMATS = ["PDF", "Word", "Excel", "PowerPoint", "EML", "ZIP", "Images OCR"];
const R = 300;
const CX = 380;
const CY = 380;
const clamp = {extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const};

const Diagram: React.FC = () => {
  const frame = useCurrentFrame();
  const center = useEnter(8);
  const pulse = 1 + 0.04 * Math.sin(frame / 10);
  return (
    <svg width={760} height={760} viewBox="0 0 760 760" style={{overflow: "visible"}}>
      {FORMATS.map((f, i) => {
        const a = (i / FORMATS.length) * Math.PI * 2 - Math.PI / 2;
        const dx = Math.cos(a);
        const dy = Math.sin(a);
        const x = CX + dx * R;
        const y = CY + dy * R;
        const ex = CX + dx * 105;
        const ey = CY + dy * 105;
        const start = 24 + i * 9;
        const e = interpolate(frame, [start, start + 20], [0, 1], {...clamp, easing: Easing.out(Easing.cubic)});
        const lx = x + (ex - x) * e;
        const ly = y + (ey - y) * e;
        const t0 = frame - start - 30;
        const p = t0 > 0 ? (t0 % 70) / 70 : -1;
        const pe = p >= 0 ? Easing.inOut(Easing.quad)(p) : 0;
        return (
          <g key={f}>
            <line x1={x} y1={y} x2={lx} y2={ly} stroke={C.line} strokeWidth={3} />
            {p >= 0 && <circle cx={x + (ex - x) * pe} cy={y + (ey - y) * pe} r={8} fill={C.accent} opacity={Math.sin(Math.PI * p)} />}
            <g transform={`translate(${x},${y}) scale(${0.8 + 0.2 * e})`} opacity={e}>
              <rect x={-75} y={-28} width={150} height={56} rx={14} fill={C.panel} stroke={C.line} strokeWidth={2} />
              <text x={0} y={9} textAnchor="middle" fontSize={26} fontFamily={FONT} fill={C.text}>{f}</text>
            </g>
          </g>
        );
      })}
      <g opacity={center} transform={`translate(${CX},${CY}) scale(${(0.7 + 0.3 * center) * pulse})`}>
        <circle r={104} fill={C.panel} stroke={C.accent} strokeWidth={4} />
        <circle r={128} fill="none" stroke={C.accent} strokeOpacity={0.3} strokeWidth={2} />
        <text x={0} y={22} textAnchor="middle" fontSize={64} fontWeight={700} fontFamily={FONT} fill={C.accent}>IA</text>
      </g>
    </svg>
  );
};

export default function Scene() {
  return (
    <Stage>
      <div style={{position: "absolute", inset: 0, display: "flex", alignItems: "center", padding: "0 120px", justifyContent: "space-between"}}>
        <div style={{width: 840}}>
          <Reveal delay={8}><div style={{fontFamily: MONO, fontSize: 30, color: C.accent, letterSpacing: 3, marginBottom: 20}}>V1 LOCALE · MONO-UTILISATEUR</div></Reveal>
          <Reveal delay={16}><h1 style={{fontSize: 176, lineHeight: 1, margin: 0, fontWeight: 700, letterSpacing: -4}}>IAGuard</h1></Reveal>
          <Reveal delay={30}><p style={{fontSize: 56, margin: "28px 0 0", color: C.text, lineHeight: 1.2}}>L'agent documentaire souverain</p></Reveal>
          <Reveal delay={46}><p style={{fontSize: 36, margin: "20px 0 0", color: C.mute}}>Vos documents, des réponses prouvées.</p></Reveal>
        </div>
        <Diagram />
      </div>
    </Stage>
  );
}
