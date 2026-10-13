import React from 'react';
import {AbsoluteFill} from 'remotion';
import {secret} from '../y/palette';            // crosses into a sibling scene: the Player build gate would refuse this
import {parseMedia} from '@remotion/media-parser'; // bare import outside SCENE_ALLOWED_IMPORTS, present in the shared node_modules
export default function Scene() { return <AbsoluteFill>{secret}{String(typeof parseMedia)}</AbsoluteFill>; }
