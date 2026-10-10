import React from "react";
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from "remotion";
import {enterStyle, progress, size} from "./jarvis-kit";

type Column = {label: string; items: string[]};

export default function Scene(props: {headline: string; data: {before: Column; after: Column}; theme: Record<string, any>}) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const theme = props.theme;
  const column = (col: Column, color: string, offset: number) => (
    <div style={{flex: 1, display: "flex", flexDirection: "column", gap: theme.gap, padding: 32, borderTop: `8px solid ${color}`, borderRadius: theme.radius, ...enterStyle(progress(frame, fps, theme, offset), theme)}}>
      <h2 style={{color, fontFamily: theme.font_heading, fontWeight: theme.heading_weight, fontSize: size(48, theme), margin: 0}}>{col.label}</h2>
      {col.items.map((item, index) => (
        <p key={index} style={{color: theme.body, fontSize: size(34, theme), margin: 0, ...enterStyle(progress(frame, fps, theme, offset + index + 1), theme)}}>{item}</p>
      ))}
    </div>
  );
  return (
    <AbsoluteFill style={{background: theme.background, color: theme.text, fontFamily: theme.font_body, padding: 72, gap: theme.gap}}>
      <h1 style={{color: theme.text, fontFamily: theme.font_heading, fontWeight: theme.heading_weight, fontSize: size(56, theme), margin: 0, ...enterStyle(progress(frame, fps, theme, 0), theme)}}>{props.headline}</h1>
      <div style={{display: "flex", flexDirection: "row", gap: 48, flex: 1}}>
        {column(props.data.before, theme.muted, 1)}
        {column(props.data.after, theme.accent, 4)}
      </div>
    </AbsoluteFill>
  );
}
