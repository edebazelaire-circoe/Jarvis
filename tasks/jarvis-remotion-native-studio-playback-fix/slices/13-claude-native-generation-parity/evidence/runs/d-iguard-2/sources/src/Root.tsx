import React from 'react';
import {Composition} from 'remotion';
import {IAGuard, TOTAL} from './IAGuard';

export const RemotionRoot: React.FC = () => (
  <Composition
    id="IAGuard"
    component={IAGuard}
    durationInFrames={TOTAL}
    fps={30}
    width={1920}
    height={1080}
  />
);
