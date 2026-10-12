import React from 'react';
import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {C, Eyebrow, Reveal, Stage} from './lib/kit';

const HEIGHTS = [100, 190, 280, 370, 460];

const Card: React.FC<{delay: number; top: number; ok: boolean; small: string; big: string}> = ({delay, top, ok, small, big}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const e = spring({frame: frame - delay, fps, config: {damping: 200}});
  const mark = interpolate(frame, [delay + 12, delay + 30], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const col = ok ? C.accent : C.mute;
  return (
    <div style={{position: 'absolute', left: 880, top, width: 900, height: 200, boxSizing: 'border-box', padding: '0 48px', display: 'flex', alignItems: 'center', gap: 40, borderRadius: 28, background: C.panel, border: `3px solid ${ok ? C.accent : C.line}`, opacity: e, transform: `translateX(${interpolate(e, [0, 1], [80, 0])}px)`}}>
      <svg width='96' height='96' viewBox='0 0 96 96' fill='none' stroke={col} strokeWidth={7} strokeLinecap='round' strokeLinejoin='round'>
        <circle cx='48' cy='48' r='40' />
        {ok ? <path d='M28 50 L43 65 L69 34' pathLength={1} strokeDasharray={1} strokeDashoffset={1 - mark} /> : <path d='M32 32 L64 64 M64 32 L32 64' pathLength={1} strokeDasharray={1} strokeDashoffset={1 - mark} />}
      </svg>
      <div>
        <div style={{fontSize: 36, color: C.mute}}>{small}</div>
        <div style={{fontSize: 70, fontWeight: 700, color: ok ? C.accent : C.text, marginTop: 4}}>{big}</div>
      </div>
    </div>
  );
};

export default function Scene() {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return (
    <Stage>
      <div style={{position: 'absolute', left: 120, top: 100}}>
        <Reveal delay={4}><Eyebrow>Confiance</Eyebrow></Reveal>
        <Reveal delay={12}><div style={{fontSize: 84, fontWeight: 700, marginTop: 16}}>Pas de preuve, pas de réponse</div></Reveal>
      </div>
      {HEIGHTS.map((h, i) => {
        const e = spring({frame: frame - (28 + i * 9), fps, config: {damping: 18}});
        return <div key={i} style={{position: 'absolute', left: 140 + i * 112, top: 880 - h * e, width: 80, height: h * e, borderRadius: '12px 12px 0 0', background: i === 4 ? C.accent : '#2c3b57'}} />;
      })}
      <div style={{position: 'absolute', left: 120, top: 880, width: 560, height: 3, background: C.line}} />
      <Reveal delay={90} style={{position: 'absolute', left: 140, top: 912}}><div style={{fontSize: 34, color: C.mute}}>5 niveaux de justification</div></Reveal>
      <Card delay={95} top={350} ok small='Preuve suffisante' big='Réponse citée' />
      <Card delay={135} top={600} ok={false} small='Preuve insuffisante' big='Refus' />
      <Reveal delay={190} style={{position: 'absolute', left: 880, top: 860}}>
        <div style={{display: 'inline-block', fontSize: 34, padding: '16px 34px', borderRadius: 60, border: `2px solid ${C.accent}`, color: C.accent}}>Validation stricte des citations</div>
      </Reveal>
    </Stage>
  );
}
