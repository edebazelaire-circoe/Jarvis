import React from "react";
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from "remotion";
import {enterStyle, progress, size} from "./jarvis-kit";

export default function Scene(props: {headline: string; data: {figure: string; caption: string}; theme: Record<string, any>}) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const theme = props.theme;
  return (
    <AbsoluteFill style={{background: theme.background, color: theme.text, fontFamily: theme.font_body, padding: 96, justifyContent: "center", alignItems: "center", textAlign: "center", gap: theme.gap}}>
      <h2 style={{color: theme.muted, fontFamily: theme.font_heading, fontWeight: theme.body_weight, fontSize: size(40, theme), margin: 0, ...enterStyle(progress(frame, fps, theme, 0), theme)}}>{props.headline}</h2>
      <div style={{color: theme.accent, fontFamily: theme.font_heading, fontWeight: theme.heading_weight, fontSize: size(220, theme), lineHeight: 1, ...enterStyle(progress(frame, fps, theme, 1), theme)}}>{props.data.figure}</div>
      <p style={{color: theme.body, fontSize: size(34, theme), margin: 0, maxWidth: 900, ...enterStyle(progress(frame, fps, theme, 2), theme)}}>{props.data.caption}</p>
    </AbsoluteFill>
  );
}
