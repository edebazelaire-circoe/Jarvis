import React from 'react';
import {Composition} from 'remotion';
import {IAGuardDeck, TOTAL} from './Deck';

export const RemotionRoot: React.FC = () => (
  <Composition
    id="IAGuard"
    component={IAGuardDeck}
    durationInFrames={TOTAL}
    fps={30}
    width={1920}
    height={1080}
  />
);
