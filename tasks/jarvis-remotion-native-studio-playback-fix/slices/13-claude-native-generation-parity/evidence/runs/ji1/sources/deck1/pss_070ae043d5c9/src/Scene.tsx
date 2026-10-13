import React from 'react';
import {Easing, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {C, Eyebrow, Reveal, Stage} from './lib/kit';

const cl = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const NODES = [
  {t: 'Corpus Windows', s: 'PDF · Word · Excel'},
  {t: 'Indexation', s: 'Sur clic : Indexer'},
  {t: 'Recherche hybride', s: 'Mots + vecteurs'},
  {t: 'Réponse', s: 'Citations validées'},
];
const X0 = 120;
const STEP = 446;
const W = 340;
const TOP = 360;
const H = 400;

const Icon: React.FC<{i: number; color: string}> = ({i, color}) => (
  <svg width='84' height='84' viewBox='0 0 72 72' fill='none' stroke={color} strokeWidth={5} strokeLinecap='round' strokeLinejoin='round'>
    {i === 0 && <path d='M8 18 h20 l6 8 h30 v34 h-56 z' />}
    {i === 1 && <path d='M10 18 h52 M10 36 h52 M10 54 h30' />}
    {i === 2 && <g><circle cx='30' cy='30' r='18' /><path d='M44 44 L62 62' /></g>}
    {i === 3 && <path d='M10 14 h52 v36 h-30 l-14 12 v-12 h-8 z' />}
  </svg>
);

export default function Scene() {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = interpolate(frame, [45, 235], [0, 3], {...cl, easing: Easing.inOut(Easing.cubic)});
  const lineX0 = X0 + W / 2;
  const lineLen = 3 * STEP;
  const dotX = lineX0 + p * STEP;
  const cy = TOP + H / 2;
  return (
    <Stage>
      <div style={{position: 'absolute', left: 120, top: 100}}>
        <Reveal delay={4}><Eyebrow>Comment ça marche</Eyebrow></Reveal>
        <Reveal delay={12}><div style={{fontSize: 84, fontWeight: 700, marginTop: 16}}>Du dossier à la réponse citée</div></Reveal>
      </div>
      <div style={{position: 'absolute', left: lineX0, top: cy - 2, width: lineLen, height: 4, background: C.line}} />
      <div style={{position: 'absolute', left: lineX0, top: cy - 2, width: p * STEP, height: 4, background: C.accent}} />
      <div style={{position: 'absolute', left: dotX - 14, top: cy - 14, width: 28, height: 28, borderRadius: 14, background: C.accent, boxShadow: `0 0 36px ${C.accent}`}} />
      {NODES.map((n, i) => {
        const e = spring({frame: frame - (18 + i * 9), fps, config: {damping: 16}});
        const active = p >= i - 0.02;
        return (
          <div key={n.t} style={{position: 'absolute', left: X0 + i * STEP, top: TOP, width: W, height: H, boxSizing: 'border-box', padding: 36, borderRadius: 28, background: C.panel, border: `3px solid ${active ? C.accent : C.line}`, boxShadow: active ? `0 0 50px ${C.accent}33` : 'none', opacity: e, transform: `translateY(${interpolate(e, [0, 1], [50, 0])}px)`}}>
            <Icon i={i} color={active ? C.accent : C.mute} />
            <div style={{fontSize: 44, fontWeight: 700, marginTop: 32, lineHeight: 1.15, minHeight: 102}}>{n.t}</div>
            <div style={{fontSize: 28, color: C.mute, marginTop: 18}}>{n.s}</div>
          </div>
        );
      })}
      <div style={{position: 'absolute', left: 120, top: 880}}>
        <Reveal delay={225}><div style={{fontSize: 38, color: C.text}}><span style={{color: C.accent}}>●</span>  Aperçu direct des fichiers : sans index, sans IA.</div></Reveal>
      </div>
    </Stage>
  );
}
