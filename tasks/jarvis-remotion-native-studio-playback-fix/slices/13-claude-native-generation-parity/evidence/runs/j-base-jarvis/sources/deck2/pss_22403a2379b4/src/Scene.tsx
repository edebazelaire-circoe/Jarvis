import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {enterStyle, progress, size} from './jarvis-kit';

type Props = {headline: string; data: {subtitle: string; pills: string[]; tag: string}; theme: Record<string, any>};

const ease = Easing.bezier(0.16, 1, 0.3, 1);
const ramp = (f: number, start: number, dur: number) =>
  interpolate(f, [start, start + dur], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});

export default function Scene(props: Props) {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const theme = props.theme;
  const fade = Math.min(ramp(frame, 0, 8), 1 - ramp(frame, durationInFrames - 14, 14));
  const pulse = 0.5 + 0.5 * Math.sin(frame / 38);
  const line = ramp(frame, 0, 26);
  const letters = props.headline.split('');
  return (
    <AbsoluteFill style={{background: theme.background, color: theme.text, fontFamily: theme.font_body, padding: '90px 120px', justifyContent: 'center', opacity: fade}}>
      <div style={{position: 'absolute', left: 40, top: 140, width: 1100, height: 800, background: `radial-gradient(closest-side, ${theme.accent}, transparent)`, opacity: (0.05 + 0.07 * pulse) * ramp(frame, 10, 60)}} />
      <div style={{width: 320 * line, height: 4, background: theme.accent, borderRadius: theme.radius, marginBottom: 36}} />
      <h1 style={{margin: 0, display: 'flex', fontFamily: theme.font_heading, fontWeight: theme.heading_weight, fontSize: size(168, theme), letterSpacing: '-0.02em', lineHeight: 1, color: theme.text}}>
        {letters.map((ch, i) => {
          const p = ramp(frame, 22 + i * 3, 22);
          return <span key={i} style={{display: 'inline-block', opacity: p, transform: `translateY(${(1 - p) * 28}px)`}}>{ch}</span>;
        })}
      </h1>
      <p style={{margin: '28px 0 0', color: theme.body, fontSize: size(48, theme), ...enterStyle(progress(frame, fps, theme, 5), theme)}}>{props.data.subtitle}</p>
      <div style={{display: 'flex', gap: 24, marginTop: 56}}>
        {props.data.pills.map((pill, i) => {
          const p = ramp(frame, 78 + i * 8, 20);
          return (
            <div key={i} style={{display: 'flex', alignItems: 'center', gap: 14, padding: '14px 30px', borderRadius: 999, border: `2px solid ${theme.muted}`, fontSize: size(30, theme), color: theme.text, opacity: p, transform: `translateY(${(1 - p) * 24}px)`}}>
              <span style={{width: 10, height: 10, borderRadius: 5, background: theme.accent}} />
              {pill}
            </div>
          );
        })}
      </div>
      <div style={{position: 'absolute', left: 120, bottom: 90, padding: '6px 18px', border: `2px dashed ${theme.muted}`, borderRadius: theme.radius, color: theme.muted, fontFamily: 'monospace', fontSize: size(28, theme), opacity: ramp(frame, 120, 20)}}>{props.data.tag}</div>
    </AbsoluteFill>
  );
}
