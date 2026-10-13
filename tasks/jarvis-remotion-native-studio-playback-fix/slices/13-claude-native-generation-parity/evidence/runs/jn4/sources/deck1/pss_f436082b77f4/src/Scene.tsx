import React from "react";
import {AbsoluteFill, interpolate, useCurrentFrame} from "remotion";
import {C, MONO, Reveal, Stage, useIn} from "./lib/kit";

const TOOLS = ["memory_search", "memory_append", "board_present"];

const Card: React.FC<{name: string; i: number; hot: boolean}> = ({name, i, hot}) => {
  const e = useIn(30 + i * 16, 16);
  return (
    <div style={{opacity: e, transform: `translateX(${(1 - e) * -60}px)`, width: 640, height: 150, borderRadius: 24, background: C.panel, border: `4px solid ${hot ? C.accent : C.line}`, display: "flex", alignItems: "center", padding: "0 44px", fontFamily: MONO, fontSize: 48, color: hot ? C.accent : C.text}}>
      {name}
    </div>
  );
};

const Chip: React.FC<{label: string; on: boolean; sub: string}> = ({label, on, sub}) => (
  <div style={{flex: 1, height: 170, borderRadius: 22, border: `4px solid ${on ? C.accent : C.line}`, background: on ? "rgba(94,234,212,0.12)" : C.bg, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center"}}>
    <div style={{fontFamily: MONO, fontSize: 72, fontWeight: 700, color: on ? C.accent : C.mute}}>{label}</div>
    <div style={{fontSize: 32, color: on ? C.text : C.mute}}>{sub}</div>
  </div>
);

export default function Scene() {
  const frame = useCurrentFrame();
  const gate = useIn(100, 14);
  const link = interpolate(frame, [90, 120], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const phase = Math.floor(Math.max(0, frame - 150) / 60) % 2;
  const shown = frame >= 150;
  return (
    <Stage eyebrow="Sécurité par défaut">
      <Reveal delay={6}><div style={{fontSize: 84, fontWeight: 800, marginTop: 24, letterSpacing: -1}}>Trois outils. Rien d'écrit sans ton accord.</div></Reveal>
      <AbsoluteFill style={{padding: "330px 120px 0", flexDirection: "row", alignItems: "center", paddingBottom: 60}}>
        <div style={{display: "flex", flexDirection: "column", gap: 36}}>
          {TOOLS.map((t, i) => <Card key={t} name={t} i={i} hot={t === "memory_append" && frame >= 90} />)}
        </div>
        <svg width={140} height={60} viewBox="0 0 140 60">
          <line x1={0} y1={30} x2={140 * link} y2={30} stroke={C.accent} strokeWidth={6} />
          <polygon points="140,30 118,18 118,42" fill={C.accent} opacity={link > 0.95 ? 1 : 0} />
        </svg>
        <div style={{opacity: gate, transform: `scale(${0.92 + 0.08 * gate})`, flex: 1, borderRadius: 28, background: C.panel, border: `4px solid ${C.line}`, padding: "40px 44px"}}>
          <div style={{fontSize: 44, fontWeight: 700}}>Garde d'actions</div>
          <div style={{fontSize: 30, color: C.mute, margin: "10px 0 32px"}}>Refus par défaut. Écriture : confirmation exacte.</div>
          <div style={{display: "flex", gap: 28, opacity: shown ? 1 : 0}}>
            <Chip label="oui" sub="écrit" on={phase === 0} />
            <Chip label="non" sub="refuse" on={phase === 1} />
          </div>
        </div>
      </AbsoluteFill>
    </Stage>
  );
}
