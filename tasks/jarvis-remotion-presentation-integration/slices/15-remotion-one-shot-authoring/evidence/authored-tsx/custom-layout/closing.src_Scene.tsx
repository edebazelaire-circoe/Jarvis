import React from "react";
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from "remotion";
import {enterStyle, progress, size} from "./jarvis-kit";

export default function Scene(props: {headline: string; data: {items: string[]}; theme: Record<string, any>}) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const theme = props.theme;
  return (
    <AbsoluteFill style={{background: theme.background, color: theme.text, fontFamily: theme.font_body, padding: 96, justifyContent: "center", gap: theme.gap}}>
      <h1 style={{color: theme.accent, fontFamily: theme.font_heading, fontWeight: theme.heading_weight, fontSize: size(64, theme), margin: 0, ...enterStyle(progress(frame, fps, theme, 0), theme)}}>{props.headline}</h1>
      <ul style={{listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: theme.gap}}>
        {props.data.items.map((item, index) => (
          <li key={index} style={{color: theme.body, fontSize: size(38, theme), borderLeft: `6px solid ${theme.accent}`, paddingLeft: 24, borderRadius: theme.radius, ...enterStyle(progress(frame, fps, theme, index + 1), theme)}}>{item}</li>
        ))}
      </ul>
    </AbsoluteFill>
  );
}
