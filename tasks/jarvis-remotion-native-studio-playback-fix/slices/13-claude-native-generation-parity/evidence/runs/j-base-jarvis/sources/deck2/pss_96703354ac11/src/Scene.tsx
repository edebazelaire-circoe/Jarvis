import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {enterStyle, progress, size} from './jarvis-kit';

type Th = Record<string, any>;
type CardData = {title: string; items: string[]};
type Props = {headline: string; data: {surface: CardData; brain: CardData; down: string; up: string; modes: {name: string; note: string}[]; quote: string; emphasis: string}; theme: Th};

const ease = Easing.bezier(0.16, 1, 0.3, 1);
const ramp = (f: number, start: number, dur: number) =>
  interpolate(f, [start, start + dur], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});

const Card = (p: {card: CardData; t0: number; frame: number; theme: Th}) => {
  const t = ramp(p.frame, p.t0, 22);
  return (
    <div style={{position: 'relative', width: 560, height: 340, boxSizing: 'border-box', padding: 40, border: `2px solid ${p.theme.muted}`, borderRadius: 14, opacity: t, transform: `translateY(${(1 - t) * 24}px)`}}>
      <div style={{position: 'absolute', inset: 0, borderRadius: 12, background: p.theme.text, opacity: 0.05}} />
      <div style={{position: 'relative', fontFamily: p.theme.font_heading, fontWeight: p.theme.heading_weight, fontSize: size(48, p.theme), letterSpacing: '-0.02em', marginBottom: 28}}>{p.card.title}</div>
      {p.card.items.map((it, i) => {
        const q = ramp(p.frame, p.t0 + 14 + i * 8, 18);
        return (
          <div key={i} style={{position: 'relative', display: 'flex', alignItems: 'center', gap: 20, marginTop: 18, fontSize: size(34, p.theme), color: p.theme.body, opacity: q, transform: `translateX(${(1 - q) * -16}px)`}}>
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
  const fade = Math.min(ramp(frame, 0, 8), 1 - ramp(frame, durationInFrames - 14, 14));
  const a1 = ramp(frame, 70, 28), a2 = ramp(frame, 98, 28);
  const slide = ramp(frame, 170, 22);
  const words = d.quote.split(' ');
  return (
    <AbsoluteFill style={{background: theme.background, color: theme.text, fontFamily: theme.font_body, padding: '90px 120px', opacity: fade}}>
      <h1 style={{margin: 0, color: theme.text, fontFamily: theme.font_heading, fontWeight: theme.heading_weight, fontSize: size(64, theme), letterSpacing: '-0.02em', ...enterStyle(progress(frame, fps, theme, 0), theme)}}>{props.headline}</h1>
      <div style={{flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', gap: 56}}>
        <div style={{display: 'flex', alignItems: 'center'}}>
          <Card card={d.surface} t0={10} frame={frame} theme={theme} />
          <svg width={560} height={340} viewBox='0 0 560 340'>
            <line x1={30} y1={120} x2={30 + 500 * a1} y2={120} stroke={theme.accent} strokeWidth={3} />
            <path d='M519,109 L530,120 L519,131' fill='none' stroke={theme.accent} strokeWidth={3} strokeLinecap='round' strokeLinejoin='round' opacity={a1 >= 1 ? 1 : 0} />
            <text x={280} y={90} textAnchor='middle' fontSize={size(28, theme)} fill={theme.body} opacity={ramp(frame, 76, 20)}>{d.down}</text>
            <line x1={530} y1={240} x2={530 - 500 * a2} y2={240} stroke={theme.accent} strokeWidth={3} />
            <path d='M41,229 L30,240 L41,251' fill='none' stroke={theme.accent} strokeWidth={3} strokeLinecap='round' strokeLinejoin='round' opacity={a2 >= 1 ? 1 : 0} />
            <text x={280} y={290} textAnchor='middle' fontSize={size(28, theme)} fill={theme.body} opacity={ramp(frame, 104, 20)}>{d.up}</text>
          </svg>
          <Card card={d.brain} t0={30} frame={frame} theme={theme} />
        </div>
        <div style={{position: 'relative', display: 'flex', width: 840, height: 110, boxSizing: 'border-box', border: `2px solid ${theme.muted}`, borderRadius: 55, opacity: ramp(frame, 130, 20)}}>
          <div style={{position: 'absolute', top: 5, left: 5 + 414 * slide, width: 414, height: 96, boxSizing: 'border-box', border: `3px solid ${theme.accent}`, borderRadius: 48, overflow: 'hidden'}}>
            <div style={{position: 'absolute', inset: 0, background: theme.accent, opacity: 0.14}} />
          </div>
          {d.modes.map((m, i) => (
            <div key={i} style={{position: 'relative', flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center'}}>
              <div style={{fontFamily: 'monospace', fontSize: size(30, theme), color: theme.text}}>{m.name}</div>
              <div style={{fontSize: size(28, theme), color: theme.muted}}>{m.note}</div>
            </div>
          ))}
        </div>
        <div style={{display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: 16, fontFamily: theme.font_heading, fontWeight: theme.heading_weight, fontSize: size(60, theme), letterSpacing: '-0.02em'}}>
          {words.map((w, i) => {
            const q = ramp(frame, 190 + i * 4, 16);
            const hot = w.replace(/[.,!?]/g, '') === d.emphasis;
            return <span key={i} style={{color: hot ? theme.accent : theme.text, opacity: q, transform: `translateY(${(1 - q) * 18}px)`}}>{w}</span>;
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
}
