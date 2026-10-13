import React from "react";
import {interpolate, useCurrentFrame} from "remotion";
import {C, MONO, Reveal, Stage, useEnter} from "./lib/ui";

const clamp = {extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const};
const BAR = "#3a4768";

const Card: React.FC<{delay: number; n: string; label: string; sub: string; children: React.ReactNode}> = ({delay, n, label, sub, children}) => {
  const e = useEnter(delay);
  return (
    <div style={{width: 480, height: 470, boxSizing: "border-box", background: C.panel, border: `2px solid ${C.line}`, borderRadius: 28, padding: 36, opacity: e, transform: `translateY(${(1 - e) * 50}px)`}}>
      <div style={{fontFamily: MONO, fontSize: 28, color: C.accent}}>{n}</div>
      <div style={{fontSize: 48, fontWeight: 700, marginTop: 6}}>{label}</div>
      <div style={{fontSize: 28, color: C.mute, marginTop: 4}}>{sub}</div>
      <div style={{marginTop: 30, height: 190, position: "relative"}}>{children}</div>
    </div>
  );
};

const Tree: React.FC<{delay: number}> = ({delay}) => {
  const frame = useCurrentFrame();
  const rows: Array<[number, number]> = [[0, 300], [40, 230], [40, 260], [80, 170], [0, 280]];
  return (
    <div>
      {rows.map(([ind, w], i) => {
        const k = interpolate(frame, [delay + 16 + i * 7, delay + 34 + i * 7], [0, 1], clamp);
        return <div key={i} style={{marginLeft: ind, width: w * k, height: 16, borderRadius: 8, marginBottom: 20, background: i === 3 ? C.accent : BAR}} />;
      })}
    </div>
  );
};

const Hybrid: React.FC<{delay: number}> = ({delay}) => {
  const frame = useCurrentFrame();
  const dots = [[20, 30], [70, 80], [40, 120], [100, 50], [90, 140], [130, 100]];
  const k = interpolate(frame, [delay + 16, delay + 40], [0, 1], clamp);
  return (
    <div style={{display: "flex", justifyContent: "space-between", alignItems: "flex-start"}}>
      <div style={{width: 170}}>
        {[150, 120, 140, 90].map((w, i) => <div key={i} style={{width: w * k, height: 14, borderRadius: 7, background: BAR, marginBottom: 20}} />)}
        <div style={{fontFamily: MONO, fontSize: 24, color: C.mute, marginTop: 22}}>Texte</div>
      </div>
      <div style={{fontSize: 44, color: C.accent, marginTop: 40, opacity: k}}>+</div>
      <div style={{width: 170, position: "relative", height: 150}}>
        {dots.map(([x, y], i) => <div key={i} style={{position: "absolute", left: x, top: y * 0.9, width: 18, height: 18, borderRadius: 9, background: i === 2 ? C.accent : BAR, transform: `scale(${k})`}} />)}
        <div style={{position: "absolute", left: 0, top: 182, fontFamily: MONO, fontSize: 24, color: C.mute}}>Vecteurs</div>
      </div>
    </div>
  );
};

const Answer: React.FC<{delay: number}> = ({delay}) => {
  const frame = useCurrentFrame();
  const widths = [380, 340, 230];
  return (
    <div>
      {widths.map((w, i) => {
        const k = interpolate(frame, [delay + 14 + i * 8, delay + 34 + i * 8], [0, 1], clamp);
        return <div key={i} style={{width: w * k, height: 16, borderRadius: 8, background: BAR, marginBottom: 20}} />;
      })}
      <div style={{display: "flex", gap: 14, marginTop: 26}}>
        {[1, 2, 3].map((n, i) => {
          const s = interpolate(frame, [delay + 50 + i * 10, delay + 62 + i * 10], [0, 1], clamp);
          return <div key={n} style={{fontFamily: MONO, fontSize: 28, color: C.bg, background: C.accent, borderRadius: 10, padding: "4px 16px", transform: `scale(${s})`, opacity: s}}>[{n}]</div>;
        })}
      </div>
    </div>
  );
};

const Arrow: React.FC<{delay: number}> = ({delay}) => {
  const frame = useCurrentFrame();
  const k = interpolate(frame, [delay, delay + 18], [0, 1], clamp);
  return (
    <svg width={120} height={40} viewBox="0 0 120 40">
      <line x1={14} y1={20} x2={14 + 78 * k} y2={20} stroke={C.accent} strokeWidth={4} strokeLinecap="round" />
      <path d="M88 8 L106 20 L88 32" fill="none" stroke={C.accent} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" opacity={k > 0.95 ? 1 : 0} />
    </svg>
  );
};

export default function Scene() {
  const e = useEnter(200);
  return (
    <Stage>
      <div style={{position: "absolute", left: 120, right: 120, top: 100}}>
        <Reveal delay={4}><h2 style={{fontSize: 80, margin: 0, fontWeight: 700, letterSpacing: -2}}>De vos fichiers à une réponse prouvée</h2></Reveal>
      </div>
      <div style={{position: "absolute", left: 120, right: 120, top: 290, display: "flex", alignItems: "center", justifyContent: "space-between"}}>
        <Card delay={24} n="01" label="Cartographier" sub="Crawl récursif du corpus"><Tree delay={24} /></Card>
        <Arrow delay={60} />
        <Card delay={74} n="02" label="Rechercher" sub="Recherche hybride"><Hybrid delay={74} /></Card>
        <Arrow delay={110} />
        <Card delay={124} n="03" label="Répondre" sub="Citations validées"><Answer delay={124} /></Card>
      </div>
      <div style={{position: "absolute", left: 120, right: 120, top: 860, display: "flex", alignItems: "center", gap: 24, opacity: e, transform: `translateY(${(1 - e) * 30}px)`}}>
        <div style={{width: 20, height: 20, borderRadius: 10, background: C.accent}} />
        <div style={{fontSize: 44}}>Preuve insuffisante : <span style={{color: C.accent, fontWeight: 700}}>l'agent refuse de répondre.</span></div>
      </div>
    </Stage>
  );
}
