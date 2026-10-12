import React from "react";
import {AbsoluteFill, interpolate, useCurrentFrame} from "remotion";

export default function Scene(props: {headline: string; reveal: boolean; stagger_ms: number; density: string;
                                      data: {body: string; figure?: number}; theme: Record<string, any>}) {
  const frame = useCurrentFrame();
  const theme = props.theme;
  const delay = Math.round((props.stagger_ms / 1000) * 30);
  const enter = interpolate(frame, [delay, delay + 18], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const gap = props.density === "compact" ? theme.gap / 2 : theme.gap;
  const shown = props.reveal ? enter : 1;
  return (
    <AbsoluteFill style={{background: theme.background, color: theme.text, fontFamily: theme.font_body, padding: 96, justifyContent: "center", gap}}>
      <h1 style={{color: theme.accent, fontFamily: theme.font_heading, fontWeight: theme.heading_weight, opacity: shown}}>{props.headline}</h1>
      <p style={{color: theme.body, opacity: shown, fontSize: 36 * theme.scale}}>{props.data.body}</p>
      {props.data.figure !== undefined ? <span style={{color: theme.muted}}>{props.data.figure}</span> : null}
    </AbsoluteFill>
  );
}
