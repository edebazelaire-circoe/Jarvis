import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {enterStyle, progress, size} from './jarvis-kit';

type NodeDef = {label: string; mono?: boolean};
type Props = {headline: string; data: {nodes: NodeDef[]; branch: string[]; optional: string; interrupt: string; caption: string}; theme: Record<string, any>};
type Th = Record<string, any>;

const ease = Easing.bezier(0.16, 1, 0.3, 1);
const ramp = (f: number, start: number, dur: number) =>
  interpolate(f, [start, start + dur], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});
const clamp01 = (v: number) => Math.max(0, Math.min(1, v));

const Chevron = (p: {x: number; y: number; dir: string; theme: Th; o: number}) => {
  const d = p.dir === 'd' ? `M${p.x - 9},${p.y - 11} L${p.x},${p.y} L${p.x + 9},${p.y - 11}` : `M${p.x - 11},${p.y - 9} L${p.x},${p.y} L${p.x - 11},${p.y + 9}`;
  return <path d={d} fill='none' stroke={p.theme.accent} strokeWidth={3} strokeLinecap='round' strokeLinejoin='round' opacity={p.o} />;
};

const Box = (p: {x: number; y: number; w: number; h: number; label: string; t: number; active: number; theme: Th; fs: number; mono?: boolean; dashed?: boolean; split?: boolean}) => {
  const cut = p.label.indexOf(' ');
  const lines = p.split && cut > 0 ? [p.label.slice(0, cut), p.label.slice(cut + 1)] : [p.label];
  const dash = p.dashed ? '8 8' : undefined;
  return (
    <g opacity={p.t} transform={`translate(0 ${(1 - p.t) * 20})`}>
      <rect x={p.x} y={p.y} width={p.w} height={p.h} rx={14} fill={p.theme.background} stroke={p.theme.muted} strokeWidth={2} strokeDasharray={dash} />
      <rect x={p.x} y={p.y} width={p.w} height={p.h} rx={14} fill='none' stroke={p.theme.accent} strokeWidth={3} strokeDasharray={dash} opacity={p.active} />
      {lines.map((l, i) => (
        <text key={i} x={p.x + p.w / 2} y={p.y + p.h / 2 + (i - (lines.length - 1) / 2) * (p.fs + 6) + p.fs * 0.35} textAnchor='middle' fontSize={p.fs} fill={p.theme.text} fontFamily={p.mono ? 'monospace' : p.theme.font_body}>{l}</text>
      ))}
    </g>
  );
};

export default function Scene(props: Props) {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const theme = props.theme;
  const d = props.data;
  const fade = Math.min(ramp(frame, 0, 8), 1 - ramp(frame, durationInFrames - 14, 14));
  const W = 1680, NW = 252, NH = 110, GAP = (W - 6 * NW) / 5, RY = 70, CY = RY + NH / 2;
  const cx = (i: number) => i * (NW + GAP) + NW / 2;
  const D0 = 30, SPAN = 200;
  const tAt = (x: number) => D0 + (SPAN * (x - cx(0))) / (cx(5) - cx(0));
  const dotX = interpolate(frame, [D0, D0 + SPAN], [cx(0), cx(5)], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const nodeT = (i: number) => (i === 0 ? ramp(frame, 6, 20) : ramp(frame, tAt(cx(i) - NW / 2) - 22, 20));
  const nodeA = (i: number) => clamp01((dotX - (cx(i) - NW / 2)) / 30);
  const dotO = ramp(frame, D0 - 8, 8);
  const pulse = 0.5 + 0.5 * Math.sin(frame / 8);
  const c3 = cx(3), LY = 260, LH = 100, LC = LY + LH / 2;
  const stem = ramp(frame, 150, 22);
  const oX = c3 - 100, cX = c3 + 140, cW = 280, mX = cX + cW + 40;
  const c1 = ramp(frame, 188, 12), c2 = ramp(frame, 214, 12);
  const iX = c3 - 420, iW = 280;
  const bl = d.branch;
  return (
    <AbsoluteFill style={{background: theme.background, color: theme.text, fontFamily: theme.font_body, padding: '90px 120px', opacity: fade}}>
      <h1 style={{margin: 0, color: theme.text, fontFamily: theme.font_heading, fontWeight: theme.heading_weight, fontSize: size(64, theme), letterSpacing: '-0.02em', ...enterStyle(progress(frame, fps, theme, 0), theme)}}>{props.headline}</h1>
      <div style={{flex: 1, display: 'flex', alignItems: 'center'}}>
        <svg width={W} height={500} viewBox={`0 0 ${W} 500`}>
          <path d={`M${cx(5)},${RY} V28 H${cx(0)} V${RY}`} fill='none' stroke={theme.muted} strokeWidth={2} strokeDasharray='10 10' opacity={0.8 * ramp(frame, 250, 24)} />
          <Chevron x={cx(0)} y={RY - 4} dir='d' theme={theme} o={ramp(frame, 270, 10)} />
          <text x={W / 2} y={38} textAnchor='middle' fontSize={size(28, theme)} fill={theme.body} stroke={theme.background} strokeWidth={26} paintOrder='stroke' opacity={ramp(frame, 266, 20)}>{d.interrupt}</text>
          {d.nodes.map((n, i) => (
            <Box key={i} x={cx(i) - NW / 2} y={RY} w={NW} h={NH} label={n.label} mono={n.mono} t={nodeT(i)} active={nodeA(i)} theme={theme} fs={size(32, theme)} />
          ))}
          {d.nodes.slice(0, -1).map((n, i) => {
            const x1 = cx(i) + NW / 2, x2 = cx(i + 1) - NW / 2;
            const fr = clamp01((dotX - x1) / (x2 - x1));
            return (
              <g key={i}>
                <line x1={x1} y1={CY} x2={x2} y2={CY} stroke={theme.muted} strokeWidth={2} opacity={0.4 * nodeT(i + 1)} />
                <line x1={x1} y1={CY} x2={x1 + (x2 - x1) * fr} y2={CY} stroke={theme.accent} strokeWidth={3} />
                <Chevron x={x2} y={CY} dir='r' theme={theme} o={fr >= 1 ? 1 : 0} />
              </g>
            );
          })}
          <circle cx={dotX} cy={CY} r={22 + 4 * pulse} fill={theme.accent} opacity={0.22 * dotO} />
          <circle cx={dotX} cy={CY} r={9} fill={theme.accent} opacity={dotO} />
          <line x1={c3} y1={RY + NH} x2={c3} y2={RY + NH + (LY - RY - NH) * stem} stroke={theme.accent} strokeWidth={3} />
          <path d={`M${c3},220 H${iX + iW / 2} V${LY}`} fill='none' stroke={theme.muted} strokeWidth={2} strokeDasharray='8 8' opacity={ramp(frame, 176, 24)} />
          <Box x={iX} y={LY} w={iW} h={LH} label={d.optional} t={ramp(frame, 184, 22)} active={0} theme={theme} fs={size(28, theme)} dashed split />
          <Box x={oX} y={LY} w={200} h={LH} label={bl[0]} t={ramp(frame, 166, 20)} active={stem >= 1 ? 1 : 0} theme={theme} fs={size(30, theme)} />
          <line x1={oX + 200} y1={LC} x2={oX + 200 + 40 * c1} y2={LC} stroke={theme.accent} strokeWidth={3} />
          <Chevron x={oX + 240} y={LC} dir='r' theme={theme} o={c1 >= 1 ? 1 : 0} />
          <Box x={cX} y={LY} w={cW} h={LH} label={bl[1]} t={ramp(frame, 196, 20)} active={c1 >= 1 ? 1 : 0} theme={theme} fs={size(30, theme)} split />
          <line x1={cX + cW} y1={LC} x2={cX + cW + 40 * c2} y2={LC} stroke={theme.accent} strokeWidth={3} />
          <Chevron x={mX} y={LC} dir='r' theme={theme} o={c2 >= 1 ? 1 : 0} />
          <Box x={mX} y={LY} w={200} h={LH} label={bl[2]} t={ramp(frame, 224, 20)} active={c2 >= 1 ? 1 : 0} theme={theme} fs={size(30, theme)} />
          <text x={0} y={470} fontSize={size(30, theme)} fill={theme.muted} opacity={ramp(frame, 300, 24)}>{d.caption}</text>
        </svg>
      </div>
    </AbsoluteFill>
  );
}
