import React from 'react';
import {Easing, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {C, Eyebrow, Reveal, Stage} from './lib/kit';

const cl = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const RULES = [
  'Aucune suppression définitive automatique',
  'Aucune écriture hors de la racine autorisée',
  'Aucune restructuration avant validation humaine',
  'Aucun écrasement silencieux',
];

export default function Scene() {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const phaseA = interpolate(frame, [166, 186], [1, 0], cl);
  const press = interpolate(frame, [264, 268, 274], [1, 0.94, 1], cl);
  const ring = interpolate(frame, [266, 286], [0, 1], cl);
  const btn = spring({frame: frame - 234, fps, config: {damping: 14}});
  return (
    <Stage>
      <div style={{opacity: phaseA}}>
        <div style={{position: 'absolute', left: 120, top: 90}}>
          <Reveal delay={4}><Eyebrow>Garde-fous</Eyebrow></Reveal>
          <Reveal delay={12}><div style={{fontSize: 84, fontWeight: 700, marginTop: 16}}>Rien ne bouge sans votre accord</div></Reveal>
        </div>
        {RULES.map((r, i) => {
          const d = 34 + i * 22;
          const e = spring({frame: frame - d, fps, config: {damping: 200}});
          const bar = interpolate(frame, [d, d + 22], [0, 1], {...cl, easing: Easing.out(Easing.cubic)});
          const tick = interpolate(frame, [d + 14, d + 32], [0, 1], cl);
          return (
            <div key={r} style={{position: 'absolute', left: 120, top: 340 + i * 160, width: 1680, height: 130, display: 'flex', alignItems: 'center', gap: 36, boxSizing: 'border-box', padding: '0 40px', borderRadius: 24, background: C.panel, opacity: e, transform: `translateX(${interpolate(e, [0, 1], [-70, 0])}px)`}}>
              <div style={{position: 'absolute', left: 0, top: 0, width: 8, height: 130 * bar, background: C.accent, borderRadius: 4}} />
              <svg width='68' height='68' viewBox='0 0 64 64' fill='none' stroke={C.accent} strokeWidth={5} strokeLinecap='round' strokeLinejoin='round'>
                <rect x='12' y='28' width='40' height='28' rx='7' />
                <path d='M20 28 v-8 a12 12 0 0 1 24 0 v8' />
                <path d='M24 42 L30 48 L41 36' pathLength={1} strokeDasharray={1} strokeDashoffset={1 - tick} />
              </svg>
              <div style={{fontSize: 50, fontWeight: 600}}>{r}</div>
            </div>
          );
        })}
      </div>
      <div style={{position: 'absolute', left: 0, top: 0, width: 1920, height: 1080, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center'}}>
        <Reveal delay={190}><Eyebrow>IAGuard</Eyebrow></Reveal>
        <div style={{display: 'flex', gap: 40, marginTop: 28, fontSize: 140, fontWeight: 800, letterSpacing: -3}}>
          <Reveal delay={196} y={60}><span>Local.</span></Reveal>
          <Reveal delay={208} y={60}><span>Sourcé.</span></Reveal>
          <Reveal delay={220} y={60}><span style={{color: C.accent}}>Réversible.</span></Reveal>
        </div>
        <div style={{position: 'relative', marginTop: 80, opacity: btn, transform: `scale(${interpolate(btn, [0, 1], [0.8, 1]) * press})`}}>
          <div style={{position: 'absolute', left: -14, top: -14, right: -14, bottom: -14, borderRadius: 54, border: `4px solid ${C.accent}`, opacity: ring > 0 ? 1 - ring : 0, transform: `scale(${1 + ring * 0.15})`}} />
          <div style={{padding: '30px 90px', borderRadius: 40, background: C.accent, color: C.bg, fontSize: 56, fontWeight: 700}}>Indexer</div>
        </div>
        <Reveal delay={248}><div style={{fontSize: 38, color: C.mute, marginTop: 70}}>L’indexation démarre quand vous le décidez.</div></Reveal>
      </div>
    </Stage>
  );
}
