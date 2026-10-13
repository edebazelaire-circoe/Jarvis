import React from 'react';
import {Composition} from 'remotion';
import {Jarvis, DURATION} from './Jarvis';

export const RemotionRoot: React.FC = () => (
  <Composition
    id="Jarvis"
    component={Jarvis}
    durationInFrames={DURATION}
    fps={30}
    width={1920}
    height={1080}
  />
);
