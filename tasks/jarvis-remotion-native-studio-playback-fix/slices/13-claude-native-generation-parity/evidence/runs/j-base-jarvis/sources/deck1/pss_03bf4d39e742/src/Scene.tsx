import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {enterStyle, progress, size} from './jarvis-kit';

type Th = Record<string, any>;
type Props = {headline: string; data: {rows: string[]; commands: string[]; prereq: string; closing: string; note: string; mono: string}; theme: Th};

const ease = Easing.bezier(0.16, 1, 0.3, 1);
const ramp = (f: number, start: number, dur: number) =>
  interpolate(f, [start, start + dur], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});

const Lock = (p: {c: number; theme: Th}) => (
  <svg width={64} height={84} viewBox='0 0 64 84'>
    <path d='M18,42 V30 a14,14 0 0 1 28,0 V42' transform={`translate(0 ${-14 * (1 - p.c)})`} fill='none' stroke={p.c > 0.5 ? p.theme.accent : p.theme.muted} strokeWidth={4} strokeLinecap='round' />
    <rect x={8} y={42} width={48} height={34} rx={6} fill='none' stroke={p.theme.text} strokeWidth={3} />
    <circle cx={32} cy={59} r={4.5} fill={p.theme.accent} opacity={p.c} />
  </svg>
);

export default function Scene(props: Props) {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const theme = props.theme;
  const d = props.data;
  const fade = Math.min(ramp(frame, 0, 6), 1 - ramp(frame, durationInFrames - 15, 15));
  const starts = [30, 80];
  const counts = d.commands.map((c, i) => Math.max(0, Math.min(c.length, Math.floor((frame - starts[i]) * 0.5))));
  const typing = counts[1] > 0 ? 1 : 0;
  const blink = frame % 30 < 18 ? 1 : 0;
  const dim = 1 - 0.65 * ramp(frame, 150, 20);
  const close = ramp(frame, 150, 24);
  return (
    <AbsoluteFill style={{background: theme.background, color: theme.text, fontFamily: theme.font_body, padding: '90px 120px', opacity: fade}}>
      <h1 style={{margin: 0, color: theme.text, fontFamily: theme.font_heading, fontWeight: theme.heading_weight, fontSize: size(64, theme), letterSpacing: '-0.02em', ...enterStyle(progress(frame, fps, theme, 0), theme)}}>{props.headline}</h1>
      <div style={{flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 64}}>
        <div style={{display: 'flex', gap: 60, alignItems: 'center', opacity: dim}}>
          <div style={{width: 780, display: 'flex', flexDirection: 'column', gap: 28}}>
            {d.rows.map((r, i) => {
              const t = ramp(frame, 10 + i * 14, 20);
              const c = ramp(frame, 30 + i * 14, 14);
              return (
                <div key={i} style={{display: 'flex', alignItems: 'center', gap: 32, padding: '20px 32px', border: `2px solid ${theme.muted}`, borderRadius: theme.radius, background: theme.surface, fontSize: size(38, theme), opacity: t, transform: `translateX(${(1 - t) * -28}px)`}}>
                  <Lock c={c} theme={theme} />
                  {r}
                </div>
              );
            })}
          </div>
          <div style={{width: 780, boxSizing: 'border-box', border: `2px solid ${theme.muted}`, borderRadius: theme.radius, background: theme.surface, overflow: 'hidden', opacity: ramp(frame, 20, 22), transform: `translateY(${(1 - ramp(frame, 20, 22)) * 24}px)`}}>
            <div style={{display: 'flex', gap: 10, padding: '16px 22px', borderBottom: `2px solid ${theme.muted}`}}>
              {[0, 1, 2].map((k) => <span key={k} style={{width: 14, height: 14, borderRadius: 7, background: theme.muted, opacity: 0.6}} />)}
            </div>
            <div style={{padding: '36px 36px 36px', fontFamily: d.mono, fontSize: size(30, theme), lineHeight: 1.9}}>
              {d.commands.map((c, i) => (
                <div key={i} style={{display: 'flex', alignItems: 'center', minHeight: 57, opacity: frame >= starts[i] - 4 ? 1 : 0}}>
                  <span style={{color: theme.accent, marginRight: 18}}>$</span>
                  <span style={{color: theme.text}}>{c.slice(0, counts[i])}</span>
                  {typing === i ? <span style={{display: 'inline-block', width: 14, height: 30, marginLeft: 4, background: theme.accent, opacity: counts[i] >= c.length ? blink : 1}} /> : null}
                </div>
              ))}
              <div style={{marginTop: 12, color: theme.muted, fontFamily: theme.font_body, fontSize: size(30, theme), opacity: ramp(frame, 122, 20)}}>{d.prereq}</div>
            </div>
          </div>
        </div>
        <div style={{opacity: close, transform: `translateY(${(1 - close) * 20}px)`}}>
          <div style={{width: 160 * close, height: 4, background: theme.accent, borderRadius: theme.radius, marginBottom: 20}} />
          <div style={{color: theme.accent, fontFamily: theme.font_heading, fontWeight: theme.heading_weight, fontSize: size(72, theme), letterSpacing: '-0.02em'}}>{d.closing}</div>
          <div style={{display: 'inline-block', marginTop: 14, paddingTop: 16, borderTop: `2px dashed ${theme.muted}`, color: theme.text, fontSize: size(44, theme)}}>{d.note}</div>
        </div>
      </div>
    </AbsoluteFill>
  );
}
