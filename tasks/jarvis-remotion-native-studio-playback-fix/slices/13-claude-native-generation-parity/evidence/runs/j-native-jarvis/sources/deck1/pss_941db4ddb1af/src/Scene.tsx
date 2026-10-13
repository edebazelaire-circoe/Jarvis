import React from "react";
import {AbsoluteFill, interpolate, useCurrentFrame} from "remotion";
import {C,FONT,MONO,Reveal,useEnter,useOut} from "./lib/kit";
export default function Scene(){
 const f=useCurrentFrame();const out=useOut(300);
 const ring=(i:number)=>{const t=((f+i*40)%120)/120;return {r:150+t*330,o:(1-t)*0.35};};
 const lineW=interpolate(useEnter(30),[0,1],[0,160]);const rg=useEnter(10);
 return (<AbsoluteFill style={{background:C.bg,fontFamily:FONT,color:C.text,opacity:out}}>
  <svg width={1920} height={1080} style={{position:"absolute"}}>
   {[0,1,2].map(i=>{const {r,o}=ring(i);return <circle key={i} cx={1400} cy={540} r={r} fill="none" stroke={C.accent} strokeWidth={2} opacity={o*rg}/>;})}
   <circle cx={1400} cy={540} r={70} fill={C.accent} opacity={useEnter(5)*0.95}/>
   <circle cx={1400} cy={540} r={110} fill="none" stroke={C.accent} strokeWidth={3} opacity={useEnter(15)}/>
  </svg>
  <div style={{position:"absolute",left:140,top:0,bottom:0,display:"flex",flexDirection:"column",justifyContent:"center"}}>
   <Reveal delay={6}><div style={{fontFamily:MONO,fontSize:32,color:C.accent,letterSpacing:6}}>PROTOTYPE LOCAL-FIRST</div></Reveal>
   <Reveal delay={16}><div style={{fontSize:240,fontWeight:800,letterSpacing:-6,lineHeight:1.05}}>JARVIS</div></Reveal>
   <div style={{height:6,width:lineW,background:C.accent,margin:"16px 0 36px"}}/>
   <Reveal delay={40}><div style={{fontSize:56,color:C.dim,maxWidth:900,lineHeight:1.25}}>Un assistant personnel qui s'écoute et se parle.</div></Reveal>
   <Reveal delay={70}><div style={{fontSize:36,color:C.text,marginTop:40}}>Pensé pour les développeurs.</div></Reveal>
  </div></AbsoluteFill>);
}
