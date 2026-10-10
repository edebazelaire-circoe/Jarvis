import React from "react";
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from "remotion";
import {enterStyle, progress, size} from "./jarvis-kit";

export default function Scene(props: {headline: string; data: {body: string}; theme: Record<string, any>}) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const theme = props.theme;
  return (
    <AbsoluteFill style={{background: theme.background, color: theme.text, fontFamily: theme.font_body, padding: 96, justifyContent: "center", gap: theme.gap}}>
      <h1 style={{color: theme.accent, fontFamily: theme.font_heading, fontWeight: theme.heading_weight, fontSize: size(72, theme),
                  margin: 0, ...enterStyle(progress(frame, fps, theme, 0), theme)}}>{props.headline}</h1>
      <p style={{color: theme.body, fontSize: size(36, theme), margin: 0, ...enterStyle(progress(frame, fps, theme, 1), theme)}}>{props.data.body}</p>
    </AbsoluteFill>
  );
}
