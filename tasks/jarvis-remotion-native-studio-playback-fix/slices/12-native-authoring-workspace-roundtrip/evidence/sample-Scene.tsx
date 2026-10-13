import React from "react";
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from "remotion";

export default function Scene(props: {title: string; bg: string}) {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  return (
    <AbsoluteFill style={{background: "#00e0ff"}}>
      <p id="edit" style={{color: "#000000", fontSize: 40, margin: 24}}>STUDIO-EDIT-OK</p>
      <p id="label" style={{color: "#ffffff", fontSize: 40, margin: 24}}>{props.title}</p>
      <p id="frame" style={{color: "#ffffff", fontSize: 28, margin: 24}}>{String(frame)}</p>
      <div id="bar" style={{position: "absolute", left: 0, bottom: 0, height: 24, background: "#ffffff",
        width: `${Math.round(100 * frame / Math.max(1, durationInFrames - 1))}%`}} />
    </AbsoluteFill>
  );
}
