import React from 'react';
import {interpolate, spring, useCurrentFrame, useVideoConfig, Easing} from 'remotion';

export const ACCENT = '#2DD4BF';
export const BG = '#0B0E13';
export const PANEL = '#131821';
export const LINE = '#273041';
export const TEXT = '#E8ECF2';
export const MUTED = '#8B96A8';
export const FONT = '"Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif';
export const MONO = '"Cascadia Mono", Consolas, "SF Mono", monospace';

/** Spring 0→1 starting at `delay` frames (scene-local). */
export const useIn = (delay = 0) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return spring({frame: frame - delay, fps, config: {damping: 200}});
};

export const useProgress = (from: number, dur: number) => {
  const frame = useCurrentFrame();
  return interpolate(frame, [from, from + dur], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.inOut(Easing.cubic),
  });
};

/** Fades/slides children in at `delay`. */
export const Reveal: React.FC<{
  delay?: number;
  y?: number;
  x?: number;
  style?: React.CSSProperties;
  children: React.ReactNode;
}> = ({delay = 0, y = 24, x = 0, style, children}) => {
  const p = useIn(delay);
  return (
    <div
      style={{
        opacity: p,
        transform: `translate(${(1 - p) * x}px, ${(1 - p) * y}px)`,
        ...style,
      }}
    >
      {children}
    </div>
  );
};

export const useSceneOpacity = (dur: number) => {
  const frame = useCurrentFrame();
  return interpolate(frame, [0, 10, dur - 12, dur], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
};

/** Scene frame: dark bg, soft grid, fade in/out, title block. */
export const Scene: React.FC<{
  dur: number;
  kicker: string;
  title: string;
  children: React.ReactNode;
}> = ({dur, kicker, title, children}) => {
  const o = useSceneOpacity(dur);
  const mask = 'radial-gradient(ellipse at 50% 50%, black 20%, transparent 75%)';
  return (
    <div style={{position: 'absolute', inset: 0, background: BG, fontFamily: FONT, color: TEXT, opacity: o, overflow: 'hidden'}}>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          backgroundImage: `linear-gradient(${LINE}55 1px, transparent 1px), linear-gradient(90deg, ${LINE}55 1px, transparent 1px)`,
          backgroundSize: '80px 80px',
          maskImage: mask,
          WebkitMaskImage: mask,
        }}
      />
      <div style={{position: 'absolute', left: 120, top: 100}}>
        <Reveal delay={4} y={12}>
          <div style={{fontFamily: MONO, fontSize: 24, letterSpacing: 4, color: ACCENT, textTransform: 'uppercase'}}>{kicker}</div>
        </Reveal>
        <Reveal delay={10}>
          <div style={{fontSize: 68, fontWeight: 600, marginTop: 14, letterSpacing: -1.5}}>{title}</div>
        </Reveal>
      </div>
      {children}
    </div>
  );
};

export const Chip: React.FC<{label: string; accent?: boolean; size?: number}> = ({label, accent, size = 26}) => (
  <div
    style={{
      display: 'inline-block',
      padding: '10px 22px',
      borderRadius: 999,
      border: `1.5px solid ${accent ? ACCENT : LINE}`,
      color: accent ? ACCENT : TEXT,
      background: accent ? `${ACCENT}14` : PANEL,
      fontSize: size,
      fontWeight: 500,
      whiteSpace: 'nowrap',
    }}
  >
    {label}
  </div>
);
