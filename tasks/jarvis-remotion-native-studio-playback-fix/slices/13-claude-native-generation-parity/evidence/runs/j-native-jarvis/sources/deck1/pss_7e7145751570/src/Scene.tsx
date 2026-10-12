import React from "react";
import {AbsoluteFill, interpolate, useCurrentFrame} from "remotion";
import {C,FONT,MONO,Reveal,useEnter,useOut} from "./lib/kit";
const Row:React.FC<{n:string;i:number}>=({n,i})=>{const e=useEnter(30+i*14);const w=i===2;return (<div style={{opacity:e,transform:`translateX(${interpolate(e,[0,1],[-60,0])}px)`,display:"flex",alignItems:"center",justifyContent:"space-between",padding:"26px 34px",borderRadius:18,background:C.panel,border:`2px solid ${w?C.accent:C.line}`}}>
    <span style={{fontFamily:MONO,fontSize:38}}>{n}</span>
    <span style={{fontSize:28,color:w?C.accent:C.dim}}>{w?"écriture · confirmation":"lecture"}</span></div>);};
export default function Scene(){
 const f=useCurrentFrame();const out=useOut(300);
 const card=useEnter(50);const ok=useEnter(170);
 return (<AbsoluteFill style={{background:C.bg,fontFamily:FONT,color:C.text,opacity:out}}>
  <div style={{position:"absolute",left:140,top:110}}>
   <Reveal delay={0}><div style={{fontFamily:MONO,fontSize:28,color:C.accent,letterSpacing:5}}>02 · LA CONFIANCE</div></Reveal>
   <Reveal delay={8}><div style={{fontSize:84,fontWeight:800,marginTop:12}}>Refusé par défaut.</div></Reveal>
   <Reveal delay={22}><div style={{fontSize:40,color:C.dim,marginTop:14}}>Une écriture attend votre « oui ».</div></Reveal></div>
  <div style={{position:"absolute",left:140,top:480,width:760,display:"flex",flexDirection:"column",gap:22}}>
   {["memory_search","board_present","memory_append"].map((n,i)=><Row key={n} n={n} i={i}/>)}
  </div>
  <div style={{position:"absolute",left:1060,top:430,width:720,borderRadius:28,background:C.panel,border:`2px solid ${C.accent}`,padding:48,opacity:card,transform:`translateY(${interpolate(card,[0,1],[50,0])}px)`,boxShadow:`0 0 60px ${C.accent}33`}}>
   <div style={{fontFamily:MONO,fontSize:32,color:C.dim}}>memory_append</div>
   <div style={{fontSize:50,fontWeight:700,margin:"18px 0 40px"}}>Enregistrer cette note ?</div>
   <div style={{display:"flex",gap:24}}>
    <div style={{flex:1,textAlign:"center",fontSize:44,fontWeight:700,padding:"22px 0",borderRadius:16,background:ok>0.5?C.accent:"transparent",color:ok>0.5?C.bg:C.text,border:`2px solid ${C.accent}`}}>oui</div>
    <div style={{flex:1,textAlign:"center",fontSize:44,fontWeight:700,padding:"22px 0",borderRadius:16,color:C.dim,border:`2px solid ${C.line}`}}>non</div></div>
   <div style={{marginTop:30,fontSize:30,color:C.accent,height:40,opacity:ok}}>{ok>0.5?"✓ Écrit dans la mémoire":""}</div>
  </div>
 </AbsoluteFill>);
}
