import React from "react";
import {interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
export const C={bg:"#0b0e14",panel:"#141925",line:"#2a3142",text:"#f2f4f8",dim:"#9aa4b8",accent:"#7cf0c4"};
export const FONT="Segoe UI, system-ui, sans-serif";
export const MONO="Consolas, 'Courier New', monospace";
export const useEnter=(delay:number)=>{const f=useCurrentFrame();const {fps}=useVideoConfig();return spring({frame:f-delay,fps,config:{damping:200}});};
export const useOut=(total:number)=>{const f=useCurrentFrame();return interpolate(f,[total-18,total],[1,0],{extrapolateLeft:"clamp",extrapolateRight:"clamp"});};
export const Reveal:React.FC<{delay:number;children:React.ReactNode;style?:React.CSSProperties}>=({delay,children,style})=>{const e=useEnter(delay);return <div style={{opacity:e,transform:`translateY(${interpolate(e,[0,1],[36,0])}px)`,...style}}>{children}</div>;};
