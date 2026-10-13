import React from 'react';
import {Series, Sequence, AbsoluteFill} from 'remotion';
import {Boundary} from './Boundary';
import Scene_a from '../scenes/a/Scene';
import Scene_b from '../scenes/b/Scene';
import Scene_c from '../scenes/c/Scene';
import Scene_c2 from '../scenes/c2/Scene';
import Scene_d60 from '../scenes/d60/Scene';
import Scene_e from '../scenes/e/Scene';
import Scene_f from '../scenes/f/Scene';
import Scene_g from '../scenes/g/Scene';
import Scene_h from '../scenes/h/Scene';
import Scene_t from '../scenes/t/Scene';
export const MASTER_OK: React.FC = () => (
  <Series>
    <Series.Sequence durationInFrames={30} name="a"><Scene_a /></Series.Sequence>
    <Series.Sequence durationInFrames={45} name="b"><Scene_b /></Series.Sequence>
    <Series.Sequence durationInFrames={60} name="c"><Scene_c /></Series.Sequence>
    <Series.Sequence durationInFrames={45} name="c2"><Scene_c2 /></Series.Sequence>
  </Series>
);
export const MASTER_MIXED: React.FC = () => (
  <Series>
    <Series.Sequence durationInFrames={30} name="a"><Scene_a /></Series.Sequence>
    <Series.Sequence durationInFrames={120} name="d60"><Scene_d60 /></Series.Sequence>
    <Series.Sequence durationInFrames={30} name="e"><Scene_e /></Series.Sequence>
  </Series>
);
export const MASTER_SEQDIMS: React.FC = () => (
  <Series>
    <Series.Sequence durationInFrames={30} name="e"><Sequence width={360} height={640}><Scene_e /></Sequence></Series.Sequence>
  </Series>
);
export const MASTER_COLLIDE: React.FC = () => (
  <Series>
    <Series.Sequence durationInFrames={15} name="f"><Scene_f /></Series.Sequence>
    <Series.Sequence durationInFrames={15} name="g"><Scene_g /></Series.Sequence>
  </Series>
);
export const MASTER_NS: React.FC = () => (
  <Series>
    <Series.Sequence durationInFrames={15} name="h"><Scene_h /></Series.Sequence>
  </Series>
);
export const MASTER_THROW_BOUNDARY: React.FC = () => (
  <Series>
    <Series.Sequence durationInFrames={10} name="a"><Boundary name="a"><Scene_a /></Boundary></Series.Sequence>
    <Series.Sequence durationInFrames={20} name="t"><Boundary name="t"><Scene_t /></Boundary></Series.Sequence>
    <Series.Sequence durationInFrames={10} name="b"><Boundary name="b"><Scene_b /></Boundary></Series.Sequence>
  </Series>
);
export const MASTER_THROW_RAW: React.FC = () => (
  <Series>
    <Series.Sequence durationInFrames={10} name="a"><Scene_a /></Series.Sequence>
    <Series.Sequence durationInFrames={20} name="t"><Scene_t /></Series.Sequence>
    <Series.Sequence durationInFrames={10} name="b"><Scene_b /></Series.Sequence>
  </Series>
);
export const PERF_1080: React.FC = () => (
  <Series>
    <Series.Sequence durationInFrames={50} name="a"><Scene_a /></Series.Sequence>
    <Series.Sequence durationInFrames={50} name="b"><Scene_b /></Series.Sequence>
    <Series.Sequence durationInFrames={50} name="c"><Scene_c /></Series.Sequence>
  </Series>
);
export const PERF_1080_LONG: React.FC = () => (
  <Series>
    <Series.Sequence durationInFrames={200} name="a"><Scene_a /></Series.Sequence>
    <Series.Sequence durationInFrames={200} name="b"><Scene_b /></Series.Sequence>
    <Series.Sequence durationInFrames={200} name="c"><Scene_c /></Series.Sequence>
  </Series>
);
