import React from "react";
import {AbsoluteFill, interpolate, useCurrentFrame} from "remotion";
import {C,FONT,MONO,Reveal,useEnter,useOut} from "./lib/kit";
const P=[{n:"core",s:"état, outils, cerveau"},{n:"voice",s:"éveil et session vocale"},{n:"control-center",s:"panneau dans le navigateur"}];
const Ln:React.FC<{i:number}>=({i})=>{const x1=140+i*580+500,x2=140+(i+1)*580;const w=interpolate(useEnter(60+i*20),[0,1],[0,x2-x1]);return <line x1={x1} y1={400} x2={x1+w} y2={400} stroke={C.accent} strokeWidth={4}/>;};
const Box:React.FC<{i:number}>=({i})=>{const p=P[i];const e=useEnter(30+i*18);return (<div style={{position:"absolute",left:140+i*580,top:320,width:500,height:160,borderRadius:22,background:C.panel,border:`2px solid ${C.line}`,opacity:e,transform:`scale(${interpolate(e,[0,1],[0.88,1])})`,display:"flex",flexDirection:"column",justifyContent:"center",padding:"0 36px"}}>
   <div style={{fontFamily:MONO,fontSize:44,color:C.accent}}>{p.n}</div><div style={{fontSize:28,color:C.dim,marginTop:8}}>{p.s}</div></div>);};
export default function Scene(){
 const f=useCurrentFrame();const out=useOut(300);
 const CMD="python -m jarvis health";
 const typed=Math.floor(interpolate(f,[150,150+CMD.length*2],[0,CMD.length],{extrapolateLeft:"clamp",extrapolateRight:"clamp"}));
 const term=useEnter(130);const blink=Math.floor(f/15)%2===0;
 return (<AbsoluteFill style={{background:C.bg,fontFamily:FONT,color:C.text,opacity:out}}>
  <div style={{position:"absolute",left:140,top:110}}>
   <Reveal delay={0}><div style={{fontFamily:MONO,fontSize:28,color:C.accent,letterSpacing:5}}>03 · À ESSAYER</div></Reveal>
   <Reveal delay={8}><div style={{fontSize:84,fontWeight:800,marginTop:12}}>Trois processus.</div></Reveal></div>
  <svg width={1920} height={1080} style={{position:"absolute"}}>{[0,1].map(i=><Ln key={i} i={i}/>)}</svg>
  {[0,1,2].map(i=><Box key={i} i={i}/>)}
  <div style={{position:"absolute",left:140,top:600,width:1240,borderRadius:22,background:"#07090d",border:`2px solid ${C.line}`,padding:"40px 48px",opacity:term,transform:`translateY(${interpolate(term,[0,1],[40,0])}px)`}}>
   <span style={{fontFamily:MONO,fontSize:54}}><span style={{color:C.accent}}>$ </span>{CMD.slice(0,typed)}<span style={{opacity:blink?1:0,color:C.accent}}>▌</span></span></div>
  <div style={{position:"absolute",left:140,bottom:110}}><Reveal delay={200}><div style={{fontSize:56,fontWeight:700}}>JARVIS. <span style={{color:C.accent}}>Dites-lui bonjour.</span></div></Reveal></div>
 </AbsoluteFill>);
}
