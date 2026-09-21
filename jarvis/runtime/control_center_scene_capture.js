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
  const FONT_FAMILY='ui-monospace,SFMono-Regular,Consolas,monospace';
  const layoutApi=()=>root.JarvisSceneLayout||(typeof require==='function'?require('./control_center_scene_layout.js'):null);

  /* Commandes de dessin du modèle de vue `model` pour une fenêtre `vp` (pixels CSS).
     Arêtes (déjà triées par couche), puis nœuds par `stack` croissant, chacun
     dans son rectangle dessiné `JarvisSceneLayout.drawnRect` (la règle même du
     DOM : forme compacte, capsule dans une boîte de fenêtre, zone d'un point).
     Le texte est écrit à sa taille de la page **après** réduction (police
     divisée par l'échelle) : sa lisibilité se juge comme à l'écran. */
  function drawCommands(model,vp,palette,layout){
    const L=layout||layoutApi();
    const size=captureSize(vp.width,vp.height);
    const k=1/size.scale;
    const font=(px,bold)=>`${bold?'bold ':''}${Math.round(px*k*10)/10}px ${FONT_FAMILY}`;
    const textWidth=(text,px)=>String(text||'').length*px*k*.62;
    const commands=[{op:'scale',s:size.scale},{op:'fill',x:0,y:0,w:vp.width,h:vp.height,color:palette.background}];
    for(const edge of model.edges||[]){
      commands.push({op:'line',x1:edge.x1,y1:edge.y1,x2:edge.x2,y2:edge.y2,width:1.5,
        color:edge.signal?palette.error:edge.artifact?toneOf(palette,edge.tone):palette.edge,
        dash:edge.artifact?[5,3]:edge.signal?[]:[3,4]});
    }
    const nodes=(model.nodes||[]).map((node,index)=>({node,index}))
      .sort((a,b)=>a.node.stack-b.node.stack||a.index-b.index).map(entry=>entry.node);
    for(const node of nodes){
      const tone=toneOf(palette,node.tone),rect=L.drawnRect(node);
      if(node.shape==='point'){
        const cx=rect.left+rect.width/2,cy=rect.top+rect.height/2;
        const hollow=node.signal&&!node.live;
        /* Marque de fin, comme la page (`.sc-exec-completed` / `.sc-exec-failed`) :
           anneau serré, vert pour une fin normale, rouge pour un échec. */
        const finished=!node.signal&&(node.exec==='completed'||node.exec==='failed');
        const finishColor=node.exec==='completed'?(palette.done||palette.ink):palette.error;
        commands.push({op:'circle',cx,cy,r:4,fill:hollow?null:tone,stroke:hollow?tone:null,id:node.id});
        if(node.live||node.exec==='running'||node.restartUnknown||finished)
          commands.push({op:'circle',cx,cy,r:finished?7.5:9,fill:null,
            stroke:node.urgency==='high'?palette.error:node.live?tone:finished?finishColor:palette.muted,
            dash:node.restartUnknown?[2,3]:[]});
        if(node.pinned)commands.push({op:'circle',cx:rect.left+rect.width-4,cy:rect.top+4,r:2.5,fill:palette.warn,stroke:null,marker:'pin'});
        continue;
      }
      const windowShape=node.shape==='window';
      const radius=windowShape?(Number(palette.radius)>=0?Number(palette.radius):10):rect.height/2;
      commands.push({op:'rrect',x:rect.left,y:rect.top,w:rect.width,h:rect.height,r:radius,fill:palette.surface,stroke:tone,id:node.id});
      commands.push({op:'clip',x:rect.left,y:rect.top,w:rect.width,h:rect.height});
      if(windowShape){
        const left=rect.left+13,right=rect.left+rect.width-13;
        let y=rect.top+11;
        commands.push({op:'circle',cx:left+3.5,cy:y+5,r:3.5,fill:tone,stroke:null});
        const pinSpace=node.pinned?11+8:0;
        const meta=node.kind==='artifact'&&node.itemCount?`${node.itemCount} ${node.itemCount>1?'entrées':'entrée'}`:'';
        const metaWidth=meta?textWidth(meta,9.5)+8:0;
        const head=[node.category,node.execLabel].filter(Boolean).join(' · ').toUpperCase();
        commands.push({op:'text',x:left+15,y,text:fit(head,right-left-15-metaWidth-pinSpace,9.5*k),font:font(9.5,true),color:tone});
        if(meta)commands.push({op:'text',x:right-pinSpace-metaWidth+8,y,text:meta,font:font(9.5),color:palette.muted});
        if(node.pinned)commands.push({op:'circle',cx:right-5.5,cy:y+5,r:3,fill:palette.warn,stroke:null,marker:'pin'});
        y+=Math.max(17,11*k+6);
        commands.push({op:'text',x:left,y,text:fit(node.title,right-left,13*k),font:font(13,true),color:palette.ink});
        y+=13*k*1.35+8;
        /* Résumé écrit en markdown : la page le dessine, la capture doit donc
           le montrer de la même façon — à plat, une ligne par ligne, sans les
           astérisques que l'utilisateur ne voit pas (`markdownLines`). */
        for(const line of L.markdownLines(node.summary)){
          if(y+12*k>rect.top+rect.height)break;
          const x=left+line.indent*10;
          commands.push({op:'text',x,y,text:fit(line.text,right-x,12*k),font:font(12,line.bold),
            color:line.bold?palette.ink:palette.muted});
          y+=12*k*1.5;
        }
        for(const item of node.items||[]){
          if(y+11*k>rect.top+rect.height)break;
          const text=[item.host,item.label,item.ref].filter(Boolean).join('  ');
          commands.push({op:'text',x:left,y,text:fit(text,right-left,11*k),font:font(11),color:tone});y+=11*k*1.4+4;
        }
      }else{
        const middle=rect.top+rect.height/2;
        const inner=rect.width-11-12-(node.pinned?11+8:0);
        commands.push({op:'circle',cx:rect.left+11+3.5,cy:middle,r:3.5,fill:tone,stroke:null});
        let x=rect.left+11+7+8;
        let room=Math.max(0,inner-7-8);
        if(node.kind==='artifact'&&node.category){
          /* Catégorie bornée (38 % comme la page), titre après sa largeur réelle : jamais superposés. */
          const category=fit(String(node.category).toUpperCase(),Math.min(rect.width*.38,room),9*k);
          if(category){
            commands.push({op:'text',x,y:middle-4.5*k,text:category,font:font(9,true),color:tone});
            const used=textWidth(category,9)+8;x+=used;room-=used;
          }
        }
        const title=fit(node.title,room,12*k);
        if(title)commands.push({op:'text',x,y:middle-6*k,text:title,font:font(12),color:palette.ink});
        if(node.pinned)commands.push({op:'circle',cx:rect.left+rect.width-12-5.5,cy:middle,r:3,fill:palette.warn,stroke:null,marker:'pin'});
      }
      commands.push({op:'restore'});
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

  /* Encodage PNG synchrone (reprise QA finale). `convertToBlob` et `toBlob` ne
     rendent la main qu'à la prochaine image produite par la page : sur un thème
     sans animation (circuit-board), une page immobile n'en produit pas et
     l'encodage attendait de 0,3 à 5 s (l'échéance). `toDataURL` encode tout de
     suite, sans image, sans boucle d'animation ni worker : environ 20 à 50 ms
     pour 1280×720, pris seulement pendant une capture. `decode` = `atob`. */
  const PNG_DATA_URL='data:image/png;base64,';
  function pngBytes(dataUrl,decode){
    if(typeof dataUrl!=='string'||!dataUrl.startsWith(PNG_DATA_URL)||dataUrl.length===PNG_DATA_URL.length){
      throw new Error('PNG non produit par le canevas');
    }
    const binary=decode(dataUrl.slice(PNG_DATA_URL.length));
    const bytes=new Uint8Array(binary.length);
    for(let index=0;index<binary.length;index++)bytes[index]=binary.charCodeAt(index);
    return bytes;
  }
  function encodePng(canvas,decode){
    return pngBytes(canvas.toDataURL('image/png'),decode);
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

  const api=Object.freeze({MAX_CAPTURE_WIDTH,MAX_CAPTURE_HEIGHT,TONE_KEYS,captureSize,fit,drawCommands,paint,pngBytes,encodePng,validRequest,createCaptureResponder});
  root.JarvisSceneCapture=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
