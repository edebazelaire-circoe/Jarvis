import React from 'react';
import {Composition} from 'remotion';
import {Jarvis, TOTAL} from './Jarvis';

export const RemotionRoot: React.FC = () => (
  <Composition
    id="Jarvis"
    component={Jarvis}
    durationInFrames={TOTAL}
    fps={30}
    width={1920}
    height={1080}
  />
);
