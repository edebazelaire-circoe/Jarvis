import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {accent} from './deep/theme';
export const Panel: React.FC<{name: string; color: string; children?: React.ReactNode}> = ({name, color, children}) => {
  const frame = useCurrentFrame();
  const {width, height, fps, durationInFrames} = useVideoConfig();
  console.log(`PROBE|${name}|${frame}|${width}x${height}@${fps}|${durationInFrames}`);
  return (
    <AbsoluteFill style={{background: color, color: 'white', fontFamily: 'monospace', fontSize: Math.round(height / 12), padding: 12}}>
      <div>scene {name} f={frame}</div>
      <div>{width}x{height}@{fps} d={durationInFrames}</div>
      <div style={{width: 40, height: 8, background: accent}} />
      {children}
    </AbsoluteFill>
  );
};
