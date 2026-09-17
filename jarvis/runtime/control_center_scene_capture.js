/* Scène constellation : capture visuelle exceptionnelle demandée par le cerveau
   (handoff jarvis-constellation-scene-runtime, Slice 09, partie 2).

   Décision du PM après le spike (option a1) : la page **meneuse visible** dessine
   son propre modèle de vue (`JarvisSceneLayout.viewModel`, celui qui place les
   nœuds du DOM : placements du résolveur, formes compactes, empilement, découpe
   de sa fenêtre) sur un canevas, réduit à 1280×720 au plus, et l'envoie en PNG
   (`POST /api/scene/captures/<id>`). Seule la couche de scène est dessinée : ni
   commandes, ni panneaux, ni chronologie, ni texte vocal.

   Deux parties pures, sans DOM ni réseau ni horloge (tests node :
   `tests/unit/test_scene_capture_logic.py`) :
   - `drawCommands(model, vp, palette)` : liste de commandes de dessin ;
     `paint(ctx, plan)` les exécute sur un contexte 2D ;
   - `createCaptureResponder(deps)` : qui répond à une demande (meneur, visible,
     scène allumée), une seule à la fois, une seule fois par identifiant,
     abandon si l'onglet perd la main ou si l'échéance passe.
   Inséré tel quel dans la page par `ControlCenter.index` ; n'expose que
   `window.JarvisSceneCapture`. */
(function(root){
  'use strict';

  const MAX_CAPTURE_WIDTH=1280,MAX_CAPTURE_HEIGHT=720;
  const CAPTURE_ID=/^[A-Za-z0-9_-]{32,64}$/;
  /* Identifiants déjà traités retenus par l'onglet (redonnés par Core chaque seconde). */
  const HANDLED_LIMIT=16;
  const TONE_KEYS=Object.freeze(['agent','job','doc','research','code','comms','error','interrupted','blocked','x0','x1','x2','x3','x4','x5']);

  /* Taille rendue : la fenêtre de la page, réduite (jamais agrandie) pour tenir dans 1280×720. */
  function captureSize(width,height){
    const w=Math.max(1,Math.floor(Number(width)||0)),h=Math.max(1,Math.floor(Number(height)||0));
    const scale=Math.min(1,MAX_CAPTURE_WIDTH/w,MAX_CAPTURE_HEIGHT/h);
    return {width:Math.max(1,Math.min(MAX_CAPTURE_WIDTH,Math.floor(w*scale))),
      height:Math.max(1,Math.min(MAX_CAPTURE_HEIGHT,Math.floor(h*scale))),scale};
  }

  /* Texte tenu dans `px` pixels à `fontPx` (chasse fixe ≈ 0,62 em) ; « … » quand il coupe. */
  function fit(text,px,fontPx){
    const value=String(text||'');
    const max=Math.floor(Math.max(0,px)/(fontPx*.62));
    if(value.length<=max)return value;
    return max<=1?'':value.slice(0,max-1)+'…';
  }

  const toneOf=(palette,key)=>palette.tones&&palette.tones[key]||palette.ink;

  /* Commandes de dessin du modèle de vue `model` pour une fenêtre `vp` (pixels CSS).
     Arêtes (déjà triées par couche), puis nœuds par `stack` croissant, chacun
     sous sa `shape` (compacte ou non) et dans sa `box` écran. */
  function drawCommands(model,vp,palette){
    const size=captureSize(vp.width,vp.height);
    const commands=[{op:'scale',s:size.scale},{op:'fill',x:0,y:0,w:vp.width,h:vp.height,color:palette.background}];
    for(const edge of model.edges||[]){
      commands.push({op:'line',x1:edge.x1,y1:edge.y1,x2:edge.x2,y2:edge.y2,width:1.5,
        color:edge.signal?palette.error:edge.artifact?toneOf(palette,edge.tone):palette.edge,
        dash:edge.artifact?[6,5]:edge.signal?[2,4]:[]});
    }
    const nodes=(model.nodes||[]).map((node,index)=>({node,index}))
      .sort((a,b)=>a.node.stack-b.node.stack||a.index-b.index).map(entry=>entry.node);
    for(const node of nodes){
      const tone=toneOf(palette,node.tone),b=node.box;
      if(node.shape==='point'){
        const r=node.signal?5:7;
        const hollow=node.signal&&!node.live;
        commands.push({op:'circle',cx:node.cx,cy:node.cy,r,fill:hollow?null:tone,stroke:hollow?tone:null});
        if(node.live||node.exec==='running'||node.restartUnknown)
          commands.push({op:'circle',cx:node.cx,cy:node.cy,r:r+4,fill:null,stroke:node.urgency==='high'?palette.error:tone,
            dash:node.restartUnknown?[2,3]:[]});
        if(node.pinned)commands.push({op:'circle',cx:node.cx+r+3,cy:node.cy-r-3,r:2.5,fill:palette.warn,stroke:null});
        continue;
      }
      const windowShape=node.shape==='window';
      /* Rayon du thème (`--sc-radius` : 14 px Omega, 7 px circuit), comme les fenêtres du DOM. */
      const radius=windowShape?(Number(palette.radius)>=0?Number(palette.radius):10):Math.min(b.height/2,14);
      commands.push({op:'rrect',x:b.left,y:b.top,w:b.width,h:b.height,r:radius,fill:palette.surface,stroke:tone});
      commands.push({op:'clip',x:b.left,y:b.top,w:b.width,h:b.height});
      const inner=b.width-16;
      if(windowShape){
        const head=node.itemCount?`${node.category} · ${node.itemCount} ${node.itemCount>1?'entrées':'entrée'}`:node.category;
        commands.push({op:'text',x:b.left+8,y:b.top+8,text:fit(head,inner,11),font:'bold 11px monospace',color:tone});
        commands.push({op:'text',x:b.left+8,y:b.top+24,text:fit(node.title,inner,13),font:'bold 13px monospace',color:palette.ink});
        let y=b.top+44;
        for(const line of String(node.summary||'').split('\n')){
          if(y+14>b.top+b.height)break;
          commands.push({op:'text',x:b.left+8,y,text:fit(line,inner,12),font:'12px monospace',color:palette.muted});y+=16;
        }
        for(const item of node.items||[]){
          if(y+14>b.top+b.height)break;
          const text=[item.host,item.label,item.ref].filter(Boolean).join('  ');
          commands.push({op:'text',x:b.left+8,y,text:fit(text,inner,12),font:'12px monospace',color:tone});y+=16;
        }
      }else{
        const category=String(node.category||'').toUpperCase();
        const y=b.top+Math.max(1,b.height/2-7);
        commands.push({op:'text',x:b.left+10,y,text:fit(category,inner,11),font:'bold 11px monospace',color:tone});
        const offset=10+Math.min(category.length*7+10,inner/2);
        commands.push({op:'text',x:b.left+offset,y,text:fit(node.title,b.width-offset-8,12),font:'12px monospace',color:palette.ink});
      }
      commands.push({op:'restore'});
      if(node.pinned)commands.push({op:'circle',cx:b.left+b.width-8,cy:b.top+8,r:3,fill:palette.warn,stroke:null});
    }
    return {width:size.width,height:size.height,scale:size.scale,commands};
  }

  /* Exécuter `plan.commands` sur un contexte 2D de `plan.width` × `plan.height`. */
  function paint(ctx,plan){
    for(const c of plan.commands){
      switch(c.op){
        case 'scale':ctx.setTransform(c.s,0,0,c.s,0,0);break;
        case 'fill':ctx.fillStyle=c.color;ctx.fillRect(c.x,c.y,c.w,c.h);break;
        case 'line':
          ctx.beginPath();ctx.setLineDash(c.dash||[]);ctx.lineWidth=c.width||1;ctx.strokeStyle=c.color;
          ctx.moveTo(c.x1,c.y1);ctx.lineTo(c.x2,c.y2);ctx.stroke();ctx.setLineDash([]);break;
        case 'circle':
          ctx.beginPath();ctx.arc(c.cx,c.cy,c.r,0,Math.PI*2);
          if(c.fill){ctx.fillStyle=c.fill;ctx.fill()}
          if(c.stroke){ctx.setLineDash(c.dash||[]);ctx.lineWidth=1.5;ctx.strokeStyle=c.stroke;ctx.stroke();ctx.setLineDash([])}
          break;
        case 'rrect':
          ctx.beginPath();
          if(typeof ctx.roundRect==='function')ctx.roundRect(c.x,c.y,c.w,c.h,c.r);else ctx.rect(c.x,c.y,c.w,c.h);
          ctx.fillStyle=c.fill;ctx.fill();ctx.lineWidth=1.5;ctx.strokeStyle=c.stroke;ctx.stroke();break;
        case 'clip':ctx.save();ctx.beginPath();ctx.rect(c.x,c.y,c.w,c.h);ctx.clip();break;
        case 'restore':ctx.restore();break;
        case 'text':ctx.font=c.font;ctx.fillStyle=c.color;ctx.textBaseline='top';ctx.fillText(c.text,c.x,c.y);break;
        default:throw new Error(`unknown draw op ${c.op}`);
      }
    }
  }

  function validRequest(request){
    return !!request&&typeof request==='object'&&typeof request.id==='string'&&CAPTURE_ID.test(request.id)
      &&Number.isInteger(request.remaining_ms)&&request.remaining_ms>=0;
  }

  /* Répondre aux demandes de capture relayées par le long-poll.
     `deps` : `now()`, `isLeader()`, `isVisible()`, `isEnabled()`,
     `render(request)` → `{blob, width, height}`, `upload(id, blob)` →
     `{status, body}`, `log(level, event, data)`.
     `offer(request)` rend une promesse de l'issue : `sent`, `refused`,
     `declined` (pas meneur visible), `duplicate`, `busy`, `expired`,
     `abandoned` (main perdue pendant le rendu), `failed`, `invalid`. Ne rejette jamais. */
  function createCaptureResponder(deps){
    const handled=[];let busy=null;
    const stats={offered:0,declined:0,rendered:0,sent:0,refused:0,abandoned:0,expired:0,failed:0};
    const log=(level,event,data)=>{try{if(deps.log)deps.log(level,event,data||{})}catch(_error){/* journal de console absent : sans effet sur la capture */}};
    const inHand=()=>deps.isEnabled()&&deps.isVisible()&&deps.isLeader();
    async function offer(request){
      if(!validRequest(request)){log('warn','scene.capture_invalid_request',{});return 'invalid'}
      stats.offered++;
      if(busy===request.id||handled.includes(request.id))return 'duplicate';
      if(busy)return 'busy';
      const short=request.id.slice(0,8);
      if(!inHand()){stats.declined++;log('info','scene.capture_declined',{capture:short});return 'declined'}
      const started=deps.now(),deadline=started+request.remaining_ms;
      busy=request.id;handled.push(request.id);if(handled.length>HANDLED_LIMIT)handled.shift();
      log('info','scene.capture_started',{capture:short,remaining_ms:request.remaining_ms});
      try{
        const shot=await deps.render(request);
        stats.rendered++;
        if(deps.now()>=deadline){stats.expired++;log('warn','scene.capture_expired',{capture:short,render_ms:deps.now()-started});return 'expired'}
        if(!inHand()){
          /* Onglet caché ou meneur perdu pendant le rendu : le nouveau meneur recevra la demande. */
          stats.abandoned++;handled.pop();
          log('info','scene.capture_abandoned',{capture:short});return 'abandoned';
        }
        const response=await deps.upload(request.id,shot.blob);
        const status=response&&response.status;
        if(status===200){
          stats.sent++;
          log('info','scene.capture_sent',{capture:short,width:shot.width,height:shot.height,bytes:shot.blob&&shot.blob.size,ms:deps.now()-started});
          return 'sent';
        }
        stats.refused++;
        const error=response&&response.body&&response.body.error||{};
        log('warn','scene.capture_refused',{capture:short,status,code:String(error.code||''),message:String(error.message||'')});
        return 'refused';
      }catch(error){
        stats.failed++;
        log('error','scene.capture_failed',{capture:short,error:String(error&&error.message||error)});
        return 'failed';
      }finally{
        busy=null;
      }
    }
    return {offer,stats:()=>({...stats})};
  }

  const api=Object.freeze({MAX_CAPTURE_WIDTH,MAX_CAPTURE_HEIGHT,TONE_KEYS,captureSize,fit,drawCommands,paint,validRequest,createCaptureResponder});
  root.JarvisSceneCapture=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
