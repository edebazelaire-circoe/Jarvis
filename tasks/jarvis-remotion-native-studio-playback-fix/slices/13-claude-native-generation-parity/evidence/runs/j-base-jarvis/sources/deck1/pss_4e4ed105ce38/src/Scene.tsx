import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {enterStyle, progress, size} from './jarvis-kit';

type Th = Record<string, any>;
type CardData = {title: string; sub: string; items: string[]};
type Props = {headline: string; data: {tag: string; badges: string[]; surface: CardData; brain: CardData; mono: string}; theme: Th};

const ease = Easing.bezier(0.16, 1, 0.3, 1);
const ramp = (f: number, start: number, dur: number) =>
  interpolate(f, [start, start + dur], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});

const Card = (p: {card: CardData; t0: number; frame: number; theme: Th}) => {
  const t = ramp(p.frame, p.t0, 22);
  return (
    <div style={{position: 'relative', width: 600, height: 420, boxSizing: 'border-box', padding: 44, border: `2px solid ${p.theme.muted}`, borderRadius: p.theme.radius, background: p.theme.surface, opacity: t, transform: `translateY(${(1 - t) * 24}px)`}}>
      <div style={{fontFamily: p.theme.font_heading, fontWeight: p.theme.heading_weight, fontSize: size(60, p.theme), letterSpacing: '-0.02em'}}>{p.card.title}</div>
      <div style={{color: p.theme.accent, fontSize: size(36, p.theme), marginTop: 6, marginBottom: 30}}>{p.card.sub}</div>
      {p.card.items.map((it, i) => {
        const q = ramp(p.frame, p.t0 + 16 + i * 8, 18);
        return (
          <div key={i} style={{display: 'flex', alignItems: 'center', gap: 20, marginTop: 18, fontSize: size(38, p.theme), color: p.theme.body, opacity: q, transform: `translateX(${(1 - q) * -16}px)`}}>
            <span style={{width: 18, height: 3, background: p.theme.accent}} />
            {it}
          </div>
        );
      })}
    </div>
  );
};

export default function Scene(props: Props) {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const theme = props.theme;
  const d = props.data;
  const fade = Math.min(ramp(frame, 0, 6), 1 - ramp(frame, durationInFrames - 10, 10));
  const a1 = ramp(frame, 90, 28), a2 = ramp(frame, 118, 28);
  const phase = Math.max(0, frame - 150) % 120 / 120;
  const local = (phase * 2) % 1;
  const dotO = frame < 150 ? 0 : Math.sin(Math.PI * local);
  const dotX = phase < 0.5 ? 30 + 420 * local : 450 - 420 * local;
  const dotY = phase < 0.5 ? 150 : 270;
  return (
    <AbsoluteFill style={{background: theme.background, color: theme.text, fontFamily: theme.font_body, padding: '90px 120px', opacity: fade}}>
      <h1 style={{margin: 0, color: theme.text, fontFamily: theme.font_heading, fontWeight: theme.heading_weight, fontSize: size(64, theme), letterSpacing: '-0.02em', ...enterStyle(progress(frame, fps, theme, 0), theme)}}>{props.headline}</h1>
      <div style={{display: 'flex', alignItems: 'center', gap: 20, marginTop: 28}}>
        <div style={{padding: '6px 20px', border: `2px solid ${theme.accent}`, borderRadius: theme.radius, fontFamily: d.mono, fontSize: size(30, theme), color: theme.text, ...enterStyle(progress(frame, fps, theme, 1), theme)}}>{d.tag}</div>
        {d.badges.map((b, i) => (
          <div key={i} style={{padding: '6px 22px', border: `2px dashed ${theme.muted}`, borderRadius: 999, fontSize: size(30, theme), color: theme.body, opacity: ramp(frame, 14 + i * 8, 18)}}>{b}</div>
        ))}
      </div>
      <div style={{flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
        <Card card={d.surface} t0={20} frame={frame} theme={theme} />
        <svg width={480} height={420} viewBox='0 0 480 420'>
          <line x1={30} y1={150} x2={30 + 420 * a1} y2={150} stroke={theme.accent} strokeWidth={3} />
          <path d='M439,139 L450,150 L439,161' fill='none' stroke={theme.accent} strokeWidth={3} strokeLinecap='round' strokeLinejoin='round' opacity={a1 >= 1 ? 1 : 0} />
          <line x1={450} y1={270} x2={450 - 420 * a2} y2={270} stroke={theme.accent} strokeWidth={3} />
          <path d='M41,259 L30,270 L41,281' fill='none' stroke={theme.accent} strokeWidth={3} strokeLinecap='round' strokeLinejoin='round' opacity={a2 >= 1 ? 1 : 0} />
          <circle cx={dotX} cy={dotY} r={20} fill={theme.accent} opacity={0.22 * dotO} />
          <circle cx={dotX} cy={dotY} r={8} fill={theme.accent} opacity={dotO} />
        </svg>
        <Card card={d.brain} t0={50} frame={frame} theme={theme} />
      </div>
    </AbsoluteFill>
  );
}
