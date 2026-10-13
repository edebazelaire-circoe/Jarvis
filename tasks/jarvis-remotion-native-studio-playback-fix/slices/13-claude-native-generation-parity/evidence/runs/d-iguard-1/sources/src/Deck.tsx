import React from 'react';
import {Sequence} from 'remotion';
import {Intro} from './scenes/Intro';
import {Pipeline} from './scenes/Pipeline';
import {Proof} from './scenes/Proof';
import {Guardrails} from './scenes/Guardrails';

export const SCENE = 300; // 10 s à 30 fps
export const TOTAL = SCENE * 4; // 40 s

export const IAGuardDeck: React.FC = () => (
  <>
    <Sequence from={0} durationInFrames={SCENE}><Intro dur={SCENE} /></Sequence>
    <Sequence from={SCENE} durationInFrames={SCENE}><Pipeline dur={SCENE} /></Sequence>
    <Sequence from={SCENE * 2} durationInFrames={SCENE}><Proof dur={SCENE} /></Sequence>
    <Sequence from={SCENE * 3} durationInFrames={SCENE}><Guardrails dur={SCENE} /></Sequence>
  </>
);
