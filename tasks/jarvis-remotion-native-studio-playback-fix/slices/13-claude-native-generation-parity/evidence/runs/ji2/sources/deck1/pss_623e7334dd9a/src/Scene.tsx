import React from "react";
import {interpolate, useCurrentFrame} from "remotion";
import {C, FONT, MONO, Reveal, Stage} from "./lib/ui";

const clamp = {extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const};
const CMD = "./scripts/start.ps1";
const URL_TXT = "http://127.0.0.1:8080";

const Diagram: React.FC = () => {
  const frame = useCurrentFrame();
  const f = (a: number, b = 16) => interpolate(frame, [a, a + b], [0, 1], clamp);
  const box = f(18, 24);
  const blocks = ["API", "Worker", "Watcher"];
  const inf = f(84);
  const net = f(106);
  const term = f(128, 14);
  const typed = Math.floor(interpolate(frame, [138, 172], [0, CMD.length], clamp));
  const showUrl = f(190, 12);
  const cursor = Math.floor(frame / 15) % 2 === 0;
  return (
    <svg width={1920} height={1080} style={{position: "absolute", left: 0, top: 0}}>
      <rect x={120} y={290} width={1000} height={400} rx={32} fill="none" stroke={C.accent} strokeWidth={3} strokeDasharray="16 12" opacity={box} />
      <text x={160} y={348} fontSize={30} fontFamily={MONO} fill={C.accent} opacity={box}>Votre poste · 127.0.0.1</text>
      {blocks.map((b, i) => {
        const e = f(34 + i * 10);
        return (
          <g key={b} opacity={e} transform={`translate(${160 + i * 320},${410 + (1 - e) * 24})`}>
            <rect width={280} height={130} rx={22} fill={C.panel} stroke={C.line} strokeWidth={2} />
            <text x={140} y={82} textAnchor="middle" fontSize={44} fontWeight={700} fontFamily={FONT} fill={C.text}>{b}</text>
          </g>
        );
      })}
      <text x={160} y={630} fontSize={30} fontFamily={FONT} fill={C.mute} opacity={f(70)}>Docker Compose</text>
      <g opacity={inf}>
        <line x1={1120} y1={475} x2={1120 + 280 * inf} y2={475} stroke={C.accent} strokeWidth={4} strokeLinecap="round" />
        <text x={1260} y={446} textAnchor="middle" fontSize={26} fontFamily={FONT} fill={C.mute}>seul fournisseur IA</text>
        <rect x={1400} y={410} width={400} height={130} rx={22} fill={C.panel} stroke={C.accent} strokeWidth={3} />
        <text x={1600} y={490} textAnchor="middle" fontSize={44} fontWeight={700} fontFamily={FONT} fill={C.text}>Infomaniak</text>
      </g>
      <g opacity={net}>
        <line x1={1120} y1={630} x2={1400} y2={630} stroke={C.mute} strokeWidth={3} strokeDasharray="8 10" />
        <path d="M1245 615 L1275 645 M1275 615 L1245 645" stroke={C.mute} strokeWidth={5} strokeLinecap="round" />
        <rect x={1400} y={580} width={400} height={100} rx={22} fill="none" stroke={C.mute} strokeWidth={2} strokeDasharray="8 10" />
        <text x={1600} y={622} textAnchor="middle" fontSize={36} fontFamily={FONT} fill={C.mute}>Internet</text>
        <text x={1600} y={659} textAnchor="middle" fontSize={26} fontFamily={FONT} fill={C.mute}>désactivé par défaut</text>
      </g>
      <g opacity={term}>
        <rect x={120} y={770} width={1680} height={200} rx={24} fill="#070a10" stroke={C.line} strokeWidth={2} />
        <circle cx={166} cy={808} r={8} fill={C.line} /><circle cx={194} cy={808} r={8} fill={C.line} /><circle cx={222} cy={808} r={8} fill={C.line} />
        <text x={160} y={883} fontSize={44} fontFamily={MONO} fill={C.text}><tspan fill={C.mute}>$ </tspan>{CMD.slice(0, typed)}{cursor && showUrl < 0.5 ? "▌" : ""}</text>
        <text x={160} y={944} fontSize={44} fontFamily={MONO} fill={C.accent} opacity={showUrl}>→ {URL_TXT}</text>
      </g>
    </svg>
  );
};

export default function Scene() {
  return (
    <Stage>
      <div style={{position: "absolute", left: 120, right: 120, top: 100}}>
        <Reveal delay={4}><h2 style={{fontSize: 80, margin: 0, fontWeight: 700, letterSpacing: -2}}>Local, maîtrisé, <span style={{color: C.accent}}>prêt à tester</span></h2></Reveal>
      </div>
      <Diagram />
    </Stage>
  );
}
