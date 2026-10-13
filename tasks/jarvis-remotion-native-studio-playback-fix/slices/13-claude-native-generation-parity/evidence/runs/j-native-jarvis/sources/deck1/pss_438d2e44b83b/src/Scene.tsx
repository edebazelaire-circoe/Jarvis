import React from "react";
import {AbsoluteFill, interpolate, useCurrentFrame} from "remotion";
import {C,FONT,MONO,Reveal,useEnter,useOut} from "./lib/kit";
const STEPS=[{t:"Touche F9",s:"push-to-talk"},{t:"Transcription",s:"voix vers texte"},{t:"Agent",s:"réfléchit, appelle ses outils"},{t:"Voix",s:"réponse parlée"}];
const X0=240,GAP=480,Y=520;
const Node:React.FC<{i:number;active:boolean}>=({i,active})=>{const e=useEnter(40+i*22);const s=STEPS[i];
 return (<div style={{position:"absolute",left:X0+i*GAP-150,top:Y-90,width:300,height:180,borderRadius:24,background:C.panel,border:`2px solid ${active?C.accent:C.line}`,opacity:e,transform:`scale(${interpolate(e,[0,1],[0.85,1])})`,display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",boxShadow:active?`0 0 50px ${C.accent}44`:"none"}}>
  <div style={{fontSize:44,fontWeight:700,color:active?C.accent:C.text}}>{s.t}</div>
  <div style={{fontSize:26,color:C.dim,marginTop:10,textAlign:"center",padding:"0 16px"}}>{s.s}</div></div>);};
const L:React.FC<{i:number}>=({i})=>{const x1=X0+i*GAP+150,x2=X0+(i+1)*GAP-150;const w=interpolate(useEnter(55+i*22),[0,1],[0,x2-x1]);return <line x1={x1} y1={Y} x2={x1+w} y2={Y} stroke={C.line} strokeWidth={4}/>;};
export default function Scene(){
 const f=useCurrentFrame();const out=useOut(300);
 const start=100,per=45;
 const prog=interpolate(f,[start,start+per*3],[0,3],{extrapolateLeft:"clamp",extrapolateRight:"clamp"});
 const px=X0+prog*GAP;
 const act=(i:number)=>f>=60&&i<=Math.round(prog)&&f>=start-40+i*per;
 return (<AbsoluteFill style={{background:C.bg,fontFamily:FONT,color:C.text,opacity:out}}>
  <div style={{position:"absolute",left:140,top:110}}>
   <Reveal delay={0}><div style={{fontFamily:MONO,fontSize:28,color:C.accent,letterSpacing:5}}>01 · LA BOUCLE</div></Reveal>
   <Reveal delay={8}><div style={{fontSize:84,fontWeight:800,marginTop:12}}>Vous parlez, il répond.</div></Reveal></div>
  <svg width={1920} height={1080} style={{position:"absolute"}}>
   {[0,1,2].map(i=><L key={i} i={i}/>)}
   <line x1={X0} y1={Y+140} x2={px} y2={Y+140} stroke={C.accent} strokeWidth={5} opacity={f>=start?1:0}/>
   <circle cx={px} cy={Y+140} r={14} fill={C.accent} opacity={f>=start?1:0}/>
  </svg>
  {STEPS.map((_,i)=><Node key={i} i={i} active={act(i)}/>)}
  <div style={{position:"absolute",left:140,bottom:130}}><Reveal delay={190}><div style={{fontSize:40,color:C.dim}}>Trois outils seulement : <span style={{color:C.accent,fontFamily:MONO}}>memory_search · memory_append · board_present</span></div></Reveal></div>
 </AbsoluteFill>);
}
