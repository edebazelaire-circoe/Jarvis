import React from "react";
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";

export const C = {bg: "#0a0d14", panel: "#121826", line: "#2a3652", text: "#f2f4f8", mute: "#9aa6bd", accent: "#7cf0c4"};
export const FONT = "Segoe UI, system-ui, sans-serif";
export const MONO = "Consolas, 'Courier New', monospace";

export const useEnter = (delay: number, damping = 200) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  return spring({frame: f - delay, fps, config: {damping}});
};

export const Reveal: React.FC<{delay: number; dx?: number; dy?: number; style?: React.CSSProperties; children: React.ReactNode}> = ({delay, dx = 0, dy = 36, style, children}) => {
  const e = useEnter(delay);
  return <div style={{opacity: e, transform: `translate(${(1 - e) * dx}px, ${(1 - e) * dy}px)`, ...style}}>{children}</div>;
};

export const Stage: React.FC<{children: React.ReactNode}> = ({children}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const a = interpolate(frame, [0, 10], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const b = interpolate(frame, [durationInFrames - 12, durationInFrames], [1, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const lines: React.ReactNode[] = [];
  for (let x = 0; x <= 1920; x += 120) lines.push(<line key={`x${x}`} x1={x} y1={0} x2={x} y2={1080} />);
  for (let y = 0; y <= 1080; y += 120) lines.push(<line key={`y${y}`} x1={0} y1={y} x2={1920} y2={y} />);
  return (
    <AbsoluteFill style={{background: C.bg, fontFamily: FONT, color: C.text, opacity: Math.min(a, b)}}>
      <svg width={1920} height={1080} style={{position: "absolute", left: 0, top: 0}} stroke={C.line} strokeOpacity={0.25} strokeWidth={1}>{lines}</svg>
      {children}
    </AbsoluteFill>
  );
};
