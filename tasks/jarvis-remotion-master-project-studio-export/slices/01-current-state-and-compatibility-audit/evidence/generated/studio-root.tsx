// Slice 01 control root (hand-written stand-in for a generated master root).
import React from 'react';
import {Composition, registerRoot, AbsoluteFill, Audio, staticFile, useCurrentFrame} from 'remotion';
import * as M from './src/master/Presentation';
const Clip: React.FC = () => {
  const f = useCurrentFrame();
  return <AbsoluteFill style={{background: '#111'}}><div style={{position: 'absolute', left: f * 4, top: 60, width: 60, height: 60, background: 'lime'}} /><Audio src={staticFile('tone.wav')} /></AbsoluteFill>;
};
const Root = () => (
  <>
    <Composition id="CLIP" component={Clip} durationInFrames={60} fps={30} width={320} height={180} />
    <Composition id="MASTER-OK" component={M.MASTER_OK} durationInFrames={180} fps={30} width={640} height={360} />
    <Composition id="MASTER-MIXED" component={M.MASTER_MIXED} durationInFrames={180} fps={30} width={640} height={360} />
    <Composition id="MASTER-SEQDIMS" component={M.MASTER_SEQDIMS} durationInFrames={30} fps={30} width={640} height={360} />
    <Composition id="MASTER-COLLIDE" component={M.MASTER_COLLIDE} durationInFrames={30} fps={30} width={640} height={360} />
    <Composition id="MASTER-NS" component={M.MASTER_NS} durationInFrames={15} fps={30} width={640} height={360} />
    <Composition id="MASTER-THROW-BOUNDARY" component={M.MASTER_THROW_BOUNDARY} durationInFrames={40} fps={30} width={640} height={360} />
    <Composition id="MASTER-THROW-RAW" component={M.MASTER_THROW_RAW} durationInFrames={40} fps={30} width={640} height={360} />
    <Composition id="PERF-1080" component={M.PERF_1080} durationInFrames={150} fps={30} width={1920} height={1080} />
    <Composition id="PERF-1080-LONG" component={M.PERF_1080_LONG} durationInFrames={600} fps={30} width={1920} height={1080} />
  </>
);
registerRoot(Root);
