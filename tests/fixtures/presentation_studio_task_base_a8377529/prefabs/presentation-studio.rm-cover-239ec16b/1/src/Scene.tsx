import React from "react";
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from "remotion";
import {enterStyle, progress, size} from "./jarvis-kit";

export default function Scene(props: {headline: string; reveal: boolean; stagger_ms: number; density: string;
                                      data: {body: string; figure?: number}; theme: Record<string, any>}) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const theme = props.theme;
  const gap = props.density === "compact" ? theme.gap / 2 : theme.gap;
  const lead = props.reveal ? progress(frame, fps, {...theme, stagger_ms: props.stagger_ms}, 1) : 1;
  return (
    <AbsoluteFill style={{background: theme.background, color: theme.text, fontFamily: theme.font_body, padding: 120, justifyContent: "center", gap}}>
      <h1 style={{color: theme.accent, fontFamily: theme.font_heading, fontWeight: theme.heading_weight, fontSize: size(96, theme), margin: 0, ...enterStyle(progress(frame, fps, theme, 0), theme)}}>{props.headline}</h1>
      <p style={{color: theme.body, fontSize: size(40, theme), margin: 0, opacity: lead}}>{props.data.body}</p>
      {props.data.figure !== undefined ? <span style={{color: theme.muted}}>{props.data.figure}</span> : null}
    </AbsoluteFill>
  );
}
