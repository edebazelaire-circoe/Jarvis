import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {enterStyle, progress, size} from './jarvis-kit';

type Th = Record<string, any>;
type Props = {headline: string; data: {nodes: string[]; branch: string; interrupt: string; caption: string; tag: string; mono: string}; theme: Th};

const ease = Easing.bezier(0.16, 1, 0.3, 1);
const ramp = (f: number, start: number, dur: number) =>
  interpolate(f, [start, start + dur], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});
const clamp01 = (v: number) => Math.max(0, Math.min(1, v));

const Chevron = (p: {x: number; y: number; dir: string; theme: Th; o: number; color: string}) => {
  const d = p.dir === 'd' ? `M${p.x - 9},${p.y - 11} L${p.x},${p.y} L${p.x + 9},${p.y - 11}` : `M${p.x - 11},${p.y - 9} L${p.x},${p.y} L${p.x - 11},${p.y + 9}`;
  return <path d={d} fill='none' stroke={p.color} strokeWidth={3} strokeLinecap='round' strokeLinejoin='round' opacity={p.o} />;
};

const Box = (p: {x: number; y: number; w: number; h: number; label: string; t: number; active: number; theme: Th; fs: number}) => (
  <g opacity={p.t} transform={`translate(0 ${(1 - p.t) * 20})`}>
    <rect x={p.x} y={p.y} width={p.w} height={p.h} rx={p.theme.radius} fill={p.theme.surface} stroke={p.theme.muted} strokeWidth={2} />
    <rect x={p.x} y={p.y} width={p.w} height={p.h} rx={p.theme.radius} fill='none' stroke={p.theme.accent} strokeWidth={3} opacity={p.active} />
    <text x={p.x + p.w / 2} y={p.y + p.h / 2 + p.fs * 0.35} textAnchor='middle' fontSize={p.fs} fill={p.theme.text} fontFamily={p.theme.font_body}>{p.label}</text>
  </g>
);

export default function Scene(props: Props) {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const theme = props.theme;
  const d = props.data;
  const fade = Math.min(ramp(frame, 0, 6), 1 - ramp(frame, durationInFrames - 10, 10));
  const N = d.nodes.length;
  const W = 1680, NW = 280, NH = 110, GAP = (W - N * NW) / (N - 1), RY = 120, CY = RY + NH / 2;
  const cx = (i: number) => i * (NW + GAP) + NW / 2;
  const D0 = 30, SPAN = 220;
  const tAt = (x: number) => D0 + (SPAN * (x - cx(0))) / (cx(N - 1) - cx(0));
  const dotX = interpolate(frame, [D0, D0 + SPAN], [cx(0), cx(N - 1)], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const nodeT = (i: number) => (i === 0 ? ramp(frame, 6, 20) : ramp(frame, tAt(cx(i) - NW / 2) - 22, 20));
  const nodeA = (i: number) => clamp01((dotX - (cx(i) - NW / 2)) / 30);
  const dotO = ramp(frame, D0 - 8, 8);
  const pulse = 0.5 + 0.5 * Math.sin(frame / 8);
  const bx = cx(2), LY = 330, LH = 100;
  const stem = ramp(frame, tAt(bx), 24);
  const arc = ramp(frame, 270, 34);
  return (
    <AbsoluteFill style={{background: theme.background, color: theme.text, fontFamily: theme.font_body, padding: '90px 120px', opacity: fade}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 40}}>
        <h1 style={{margin: 0, color: theme.text, fontFamily: theme.font_heading, fontWeight: theme.heading_weight, fontSize: size(64, theme), letterSpacing: '-0.02em', ...enterStyle(progress(frame, fps, theme, 0), theme)}}>{props.headline}</h1>
        <div style={{padding: '6px 20px', border: `2px dashed ${theme.body}`, borderRadius: theme.radius, color: theme.body, fontFamily: d.mono, fontSize: size(28, theme), ...enterStyle(progress(frame, fps, theme, 2), theme)}}>{d.tag}</div>
      </div>
      <div style={{flex: 1, display: 'flex', alignItems: 'center'}}>
        <svg width={W} height={500} viewBox={`0 0 ${W} 500`}>
          <path d={`M${cx(0)},${RY} V50 H${cx(N - 1)} V${RY - 6}`} pathLength={1} strokeDasharray={1} strokeDashoffset={1 - arc} fill='none' stroke={theme.muted} strokeWidth={2} />
          <Chevron x={cx(N - 1)} y={RY - 4} dir='d' theme={theme} o={arc >= 1 ? 1 : 0} color={theme.accent} />
          <text x={W / 2} y={60} textAnchor='middle' fontSize={size(30, theme)} fill={theme.body} stroke={theme.background} strokeWidth={28} paintOrder='stroke' opacity={ramp(frame, 292, 20)}>{d.interrupt}</text>
          {d.nodes.map((n, i) => (
            <Box key={i} x={cx(i) - NW / 2} y={RY} w={NW} h={NH} label={n} t={nodeT(i)} active={nodeA(i)} theme={theme} fs={size(32, theme)} />
          ))}
          {d.nodes.slice(0, -1).map((n, i) => {
            const x1 = cx(i) + NW / 2, x2 = cx(i + 1) - NW / 2;
            const fr = clamp01((dotX - x1) / (x2 - x1));
            return (
              <g key={i}>
                <line x1={x1} y1={CY} x2={x2} y2={CY} stroke={theme.muted} strokeWidth={2} opacity={0.4 * nodeT(i + 1)} />
                <line x1={x1} y1={CY} x2={x1 + (x2 - x1) * fr} y2={CY} stroke={theme.accent} strokeWidth={3} />
                <Chevron x={x2} y={CY} dir='r' theme={theme} o={fr >= 1 ? 1 : 0} color={theme.accent} />
              </g>
            );
          })}
          <circle cx={dotX} cy={CY} r={22 + 4 * pulse} fill={theme.accent} opacity={0.22 * dotO} />
          <circle cx={dotX} cy={CY} r={9} fill={theme.accent} opacity={dotO} />
          <line x1={bx} y1={RY + NH} x2={bx} y2={RY + NH + (LY - RY - NH) * stem} stroke={theme.accent} strokeWidth={3} />
          <Box x={bx - 190} y={LY} w={380} h={LH} label={d.branch} t={ramp(frame, tAt(bx) + 18, 22)} active={stem >= 1 ? 1 : 0} theme={theme} fs={size(32, theme)} />
          <text x={W} y={470} textAnchor='end' fontSize={size(30, theme)} fill={theme.muted} opacity={ramp(frame, 322, 24)}>{d.caption}</text>
        </svg>
      </div>
    </AbsoluteFill>
  );
}
