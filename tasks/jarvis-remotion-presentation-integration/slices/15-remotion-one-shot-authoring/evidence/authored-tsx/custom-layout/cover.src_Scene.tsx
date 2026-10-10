import React from "react";
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from "remotion";
import {enterStyle, progress, size} from "./jarvis-kit";

export default function Scene(props: {headline: string; data: {subtitle: string}; theme: Record<string, any>}) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const theme = props.theme;
  return (
    <AbsoluteFill style={{background: theme.background, color: theme.text, fontFamily: theme.font_body, padding: 96, justifyContent: "center", gap: theme.gap}}>
      <div style={{width: 120, height: 8, background: theme.accent, borderRadius: theme.radius, ...enterStyle(progress(frame, fps, theme, 0), theme)}} />
      <h1 style={{color: theme.text, fontFamily: theme.font_heading, fontWeight: theme.heading_weight, fontSize: size(96, theme), margin: 0, ...enterStyle(progress(frame, fps, theme, 1), theme)}}>{props.headline}</h1>
      <p style={{color: theme.muted, fontSize: size(40, theme), margin: 0, ...enterStyle(progress(frame, fps, theme, 2), theme)}}>{props.data.subtitle}</p>
    </AbsoluteFill>
  );
}
