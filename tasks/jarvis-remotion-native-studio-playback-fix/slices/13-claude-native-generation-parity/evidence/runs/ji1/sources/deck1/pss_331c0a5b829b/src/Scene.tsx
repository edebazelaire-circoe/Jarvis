import React from 'react';
import {Easing, interpolate, useCurrentFrame} from 'remotion';
import {C, Eyebrow, Reveal, Stage} from './lib/kit';

const cl = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const draw = (p: number) => ({pathLength: 1, strokeDasharray: 1, strokeDashoffset: 1 - p});

export default function Scene() {
  const frame = useCurrentFrame();
  const shield = interpolate(frame, [8, 64], [0, 1], {...cl, easing: Easing.out(Easing.cubic)});
  const docP = interpolate(frame, [50, 80], [0, 1], cl);
  const check = interpolate(frame, [110, 135], [0, 1], {...cl, easing: Easing.out(Easing.cubic)});
  const glow = interpolate(frame, [110, 150], [0, 1], cl);
  const floatY = Math.sin(frame / 40) * 6;
  return (
    <Stage>
      <div style={{position: 'absolute', left: 140, top: 270, width: 1000}}>
        <Reveal delay={6}><Eyebrow>V1 locale · mono-utilisateur</Eyebrow></Reveal>
        <Reveal delay={18} y={60}><div style={{fontSize: 210, fontWeight: 800, letterSpacing: -6, lineHeight: 1.05, marginTop: 24}}>IAGuard</div></Reveal>
        <Reveal delay={40}><div style={{fontSize: 62, fontWeight: 500, marginTop: 8}}>L’agent documentaire souverain</div></Reveal>
        <Reveal delay={90}><div style={{fontSize: 40, color: C.accent, marginTop: 44}}>Des réponses citées, depuis votre poste.</div></Reveal>
      </div>
      <div style={{position: 'absolute', left: 1230, top: 190, width: 480, height: 700, transform: `translateY(${floatY}px)`}}>
        <div style={{position: 'absolute', left: -60, top: 60, width: 600, height: 600, borderRadius: 300, background: `radial-gradient(circle, ${C.accent}33, transparent 65%)`, opacity: glow}} />
        <svg width='480' height='576' viewBox='0 0 400 480' fill='none' strokeLinecap='round' strokeLinejoin='round' style={{position: 'absolute', left: 0, top: 40}}>
          <path d='M200 20 L370 80 V230 C370 340 295 420 200 460 C105 420 30 340 30 230 V80 Z' stroke={C.accent} strokeWidth={6} fill={C.panel} fillOpacity={shield} {...draw(shield)} />
          <g opacity={docP}>
            <rect x='135' y='105' width='130' height='165' rx='12' stroke={C.mute} strokeWidth={5} />
            {[0, 1, 2, 3].map((i) => {
              const p = interpolate(frame, [70 + i * 9, 88 + i * 9], [0, 1], cl);
              return <path key={i} d={`M155 ${140 + i * 28} h${p * (i === 3 ? 50 : 90)}`} stroke={C.text} strokeWidth={6} />;
            })}
          </g>
          <path d='M158 350 L192 384 L250 316' stroke={C.accent} strokeWidth={14} {...draw(check)} />
        </svg>
      </div>
    </Stage>
  );
}
