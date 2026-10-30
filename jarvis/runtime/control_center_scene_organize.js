/* Pure organization targets + bounded geometry-only undo; Core owns writes.
   Boxes are DRAWN scene units supplied by the canonical hold desk. */
(function(root){
  'use strict';
  const L=root.JarvisSceneLayout||(typeof require==='function'?require('./control_center_scene_layout.js'):null);
  const WIRE_BYTES=65536,MAX_UNDO=20,UNDO_MS=120000;
  const ACTIONS=Object.freeze({row:'Ligne horizontale',column:'Colonne verticale',grid:'Grille automatique',custom:'Grille personnalisée',
    left:'Aligner à gauche',center:'Centrer horizontalement',right:'Aligner à droite',top:'Aligner en haut',middle:'Centrer verticalement',bottom:'Aligner en bas',
    distributeX:'Distribuer horizontalement',distributeY:'Distribuer verticalement',width:'Même largeur',height:'Même hauteur',size:'Même taille'});
  const box=b=>b&&['x','y','w','h'].every(k=>typeof b[k]==='number'&&Number.isFinite(b[k]))&&b.w>0&&b.h>0;
  const copy=b=>({x:b.x,y:b.y,w:b.w,h:b.h});
  const same=(a,b)=>!!a&&!!b&&['x','y','w','h'].every(k=>Math.abs(a[k]-b[k])<.00001);
  function bounds(members){return {x0:Math.min(...members.map(m=>m.box.x)),y0:Math.min(...members.map(m=>m.box.y)),
    x1:Math.max(...members.map(m=>m.box.x+m.box.w)),y1:Math.max(...members.map(m=>m.box.y+m.box.h))}}
  function plan(members,action,options={}){
    if(!Array.isArray(members)||members.length<2||members.length>512||members.some(m=>!m||typeof m.id!=='string'||!box(m.box))||new Set(members.map(m=>m.id)).size!==members.length)
      throw new Error('Choisissez au moins deux objets placés.');
    if(!Object.hasOwn(ACTIONS,action))throw new Error('Disposition inconnue.');
    if(['width','height','size'].includes(action)&&members.some(m=>!['window','capsule'].includes(m.representation)))throw new Error('La même taille demande des fenêtres ou capsules redimensionnables.');
    const scale=Number(options.scale)||1,vp=options.viewport||{cx:0,cy:0};
    const sorted=L.spatialOrder(members.map(m=>({id:m.id,cx:vp.cx+(m.box.x+m.box.w/2)*scale,cy:vp.cy+(m.box.y+m.box.h/2)*scale})));
    const byId=new Map(members.map(m=>[m.id,m])),ordered=sorted.map(n=>byId.get(n.id));
    const out=ordered.map(m=>({...m,box:copy(m.box)})),b=bounds(members),cx=(b.x0+b.x1)/2,cy=(b.y0+b.y1)/2,gap=3;
    const maxW=Math.max(...members.map(m=>m.box.w)),maxH=Math.max(...members.map(m=>m.box.h));
    if(['row','column','grid','custom'].includes(action)){
      let cols=action==='row'?out.length:action==='column'?1:Math.ceil(Math.sqrt(out.length)),rows=Math.ceil(out.length/cols);
      if(action==='custom'){
        cols=options.cols;rows=options.rows;
        if(!Number.isInteger(rows)||!Number.isInteger(cols)||rows<1||cols<1||rows>64||cols>64||rows*cols>512)throw new Error('Grille : 1 à 64 lignes et colonnes, 512 cases au plus.');
        if(rows*cols<out.length)throw new Error('La grille ne contient pas assez de cases pour la sélection.');
      }
      let offset=0;
      out.forEach((m,i)=>{
        if(action==='row'){m.box.x=offset;m.box.y=-m.box.h/2;offset+=m.box.w+gap}
        else if(action==='column'){m.box.x=-m.box.w/2;m.box.y=offset;offset+=m.box.h+gap}
        else{m.box.x=(i%cols)*(maxW+gap)+(maxW-m.box.w)/2;m.box.y=Math.floor(i/cols)*(maxH+gap)+(maxH-m.box.h)/2}
      });
      const extent=bounds(out),dx=cx-(extent.x0+extent.x1)/2,dy=cy-(extent.y0+extent.y1)/2;
      out.forEach(m=>{m.box.x+=dx;m.box.y+=dy});
    }else if(action==='distributeX'||action==='distributeY'){
      if(out.length<3)throw new Error('Distribuer demande au moins trois objets.');
      const axis=action==='distributeX'?'x':'y',size=axis==='x'?'w':'h',lo=axis==='x'?b.x0:b.y0,hi=axis==='x'?b.x1:b.y1;
      out.sort((a,z)=>a.box[axis]-z.box[axis]||a.id.localeCompare(z.id));
      const spacing=(hi-lo-out.reduce((n,m)=>n+m.box[size],0))/(out.length-1);let at=lo;
      out.forEach(m=>{m.box[axis]=at;at+=m.box[size]+spacing});
    }else out.forEach(m=>{
      if(action==='left')m.box.x=b.x0;if(action==='center')m.box.x=cx-m.box.w/2;if(action==='right')m.box.x=b.x1-m.box.w;
      if(action==='top')m.box.y=b.y0;if(action==='middle')m.box.y=cy-m.box.h/2;if(action==='bottom')m.box.y=b.y1-m.box.h;
      if(action==='width'||action==='size')m.box.w=maxW;if(action==='height'||action==='size')m.box.h=maxH;
    });
    const area=options.area;
    if(area){const e=bounds(out);if(e.x1-e.x0>area.x1-area.x0+.01||e.y1-e.y0>area.y1-area.y0+.01)throw new Error('La disposition dépasse l’espace visible : choisissez une grille plus compacte.');
      const dx=Math.max(area.x0-e.x0,Math.min(0,area.x1-e.x1)),dy=Math.max(area.y0-e.y0,Math.min(0,area.y1-e.y1));
      out.forEach(m=>{m.box.x+=dx;m.box.y+=dy});}
    return out.map(m=>({id:m.id,representation:m.representation,box:Object.fromEntries(Object.entries(m.box).map(([k,v])=>[k,Math.round(v*10)/10]))}));
  }
  function command(targets,pin=false){return {schema_version:1,op:'layout_selection',selection:{ids:targets.map(t=>t.id)},
    targets:targets.map(t=>({object_id:t.id,geometry:copy(t.after),expected_geometry:copy(t.before)})),...(pin?{pin:true}:{})}}
  function wireBytes(value){
    const full={...value,actor:'user'};let extra=0;
    for(const target of full.targets||[])for(const b of [target.geometry,target.expected_geometry])if(b)for(const v of Object.values(b)){
      if(Number.isInteger(v))extra+=2;else if(/e-\d$/.test(String(v)))extra++;
    }
    return new TextEncoder().encode(JSON.stringify(full)).length+extra;
  }
  function checkBudget(targets){
    const forward=command(targets,true),reverse=command(targets.map(t=>({...t,before:t.after,after:t.before})));
    if(Math.max(wireBytes(forward),wireBytes(reverse))>WIRE_BYTES)throw new Error('Cette sélection dépasse la taille autorisée pour une disposition annulable. Choisissez moins d’objets.');
  }
  function createHistory({now=()=>Date.now(),limit=MAX_UNDO,ttlMs=UNDO_MS}={}){
    const entries=[];const prune=()=>{while(entries.length&&(now()-entries[0].at>ttlMs))entries.shift()};
    return {record(entry){prune();if(!entry.targets.some(t=>!same(t.before,t.after)))return false;checkBudget(entry.targets);
        entries.push({...entry,at:now(),targets:entry.targets.map(t=>({...t,before:copy(t.before),after:copy(t.after)}))});if(entries.length>limit)entries.shift();return true},
      size(){prune();return entries.length},clear(){entries.length=0},
      take(state,boardId){prune();const entry=entries.pop();if(!entry)return null;
        if(!state||entry.scene_id!==state.scene_id||entry.epoch!==state.epoch||entry.board_id!==boardId)throw new Error('Le Board a changé : cette annulation n’est plus disponible.');
        for(const t of entry.targets){const item=state.objects.get(t.id);if(!item||item.visibility!=='visible'||item.representation!==t.representation||!same(item.geometry,t.after))
          throw new Error('Un objet a changé depuis cette disposition : annulation refusée pour conserver les modifications récentes.');}
        return {entry,command:command(entry.targets.map(t=>({...t,before:t.after,after:t.before})))};
      }};
  }
  const api=Object.freeze({ACTIONS,WIRE_BYTES,MAX_UNDO,UNDO_MS,plan,bounds,same,command,wireBytes,checkBudget,createHistory});
  root.JarvisSceneOrganize=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
