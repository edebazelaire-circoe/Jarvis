import React from "react";
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";

export const C = {bg: "#0b0e14", panel: "#141925", line: "#2a3245", text: "#f1f4f9", mute: "#9aa5ba", accent: "#5eead4"};
export const SANS = "Segoe UI, system-ui, sans-serif";
export const MONO = "Consolas, 'Courier New', monospace";

export const useIn = (delay: number, damping = 200) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return spring({frame: frame - delay, fps, config: {damping}});
};

export const Reveal: React.FC<{delay: number; dy?: number; style?: React.CSSProperties; children: React.ReactNode}> = ({delay, dy = 36, style, children}) => {
  const e = useIn(delay);
  return <div style={{opacity: e, transform: `translateY(${interpolate(e, [0, 1], [dy, 0])}px)`, ...style}}>{children}</div>;
};

export const Stage: React.FC<{eyebrow: string; children: React.ReactNode}> = ({eyebrow, children}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const out = interpolate(frame, [durationInFrames - 14, durationInFrames - 1], [1, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <AbsoluteFill style={{background: C.bg, color: C.text, fontFamily: SANS, padding: "96px 120px", opacity: out}}>
      <Reveal delay={0} dy={12}><div style={{fontSize: 28, letterSpacing: 6, textTransform: "uppercase", color: C.accent, fontWeight: 600}}>{eyebrow}</div></Reveal>
      {children}
    </AbsoluteFill>
  );
};
