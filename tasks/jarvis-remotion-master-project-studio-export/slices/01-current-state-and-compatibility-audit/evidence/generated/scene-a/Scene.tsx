import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate} from 'remotion';
import {Panel} from './parts/Panel';
export default function Scene() {
  return <Panel name="a" color="#334"></Panel>;
}
