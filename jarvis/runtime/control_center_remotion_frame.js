/* Cadre d'une scène Remotion côté fenêtre de scène (handoff jarvis-remotion-presentation-integration, Slice 10 ;
   `docs/remotion-isolation.md` § 10). Module PUR (aucune minuterie, aucun état) utilisé par `control_center_prefab_host.js` quand le
   paquet d'une version est `{kind: "remotion"}` : il ne monte JAMAIS le bac à sable lui-même.

   Le cadre qu'il crée porte la page de la scène du Control Center (`/remotion-stage`), un document de confiance de la même origine
   qui monte le bac à sable d'une origine dédiée (`control_center_remotion_stage.js`). Raison : la page qui monte le cadre Remotion
   porte `frame-src <origine du bac à sable>` et rien d'autre ; la page principale du Control Center encadre déjà un visualiseur.

   Protocole avec la page de la scène (`rsh: 1`, même origine, source = `contentWindow` du cadre, champs exacts) :
   - fenêtre -> page : `props {props}`, `control {action, frame?, until?}`, `cue {name, frame}`, `teardown {}` ;
   - page -> fenêtre : `clock {frame, playing, duration, fps}` (Slice 12 : où en est le lecteur, au plus 4 par seconde ; conseil de
     l'iframe, jamais envoyé à Core) ;
   - page -> fenêtre : `status {phase, ...}` avec `phase` parmi `shell`, `preparing`, `mounting`, `ready`, `failed`, `killed`,
     `scene_error` (`composition`, `reason`, `message`, `title`, `engine_drift` selon la phase). */
(function(root){
  'use strict';
  const SHELL=1;
  const STAGE_PATH='/remotion-stage';
  const PHASES=Object.freeze(['shell','preparing','mounting','ready','failed','killed','scene_error']);
  const HOST_FIELDS=Object.freeze({props:['props'],control:['action','frame','until'],cue:['name','frame'],teardown:[]});
  const ACTIONS=Object.freeze(['play','pause','seek']);
  const MAX_TEXT=300;
  const MAX_FRAMES=108000;
  const MAX_FPS=120;

  function plain(value){return value!==null&&typeof value==='object'&&!Array.isArray(value)}
  function clip(value){return typeof value==='string'?value.replace(/[\u0000-\u001f\u007f]/g,' ').slice(0,MAX_TEXT):''}

  function stageUrl(prefab){
    return `${STAGE_PATH}?id=${encodeURIComponent(prefab.id)}&v=${encodeURIComponent(String(prefab.version))}`;
  }

  /* L'iframe de la page de la scène. Pas d'attribut `sandbox` ici : c'est un document de confiance de notre origine ; le code non
     fiable est dans le cadre que CE document monte. */
  function createFrame(doc,prefab,title){
    const iframe=doc.createElement('iframe');
    iframe.className='sc-prefab-frame sc-remotion-frame';
    iframe.setAttribute('title',title);
    iframe.setAttribute('allow','');
    iframe.setAttribute('referrerpolicy','no-referrer');
    iframe.setAttribute('data-remotion-stage','1');
    iframe.src=stageUrl(prefab);
    return iframe;
  }

  function hostMessage(type,fields){
    if(!HOST_FIELDS[type])throw new Error(`unknown remotion stage message: ${type}`);
    const message=Object.assign({rsh:SHELL,type},fields||{});
    for(const key of Object.keys(message))if(key!=='rsh'&&key!=='type'&&!HOST_FIELDS[type].includes(key))throw new Error(`unexpected field ${key}`);
    if(type==='control'&&!ACTIONS.includes(message.action))throw new Error('bad control action');
    if(type==='control'){
      for(const key of ['frame','until'])if(key in message&&!(Number.isInteger(message[key])&&message[key]>=0&&message[key]<=MAX_FRAMES))throw new Error(`bad control ${key}`);
      if('until' in message&&(message.action!=='play'||('frame' in message&&message.until<message.frame)))throw new Error('bad control until');
    }
    return message;
  }

  /* Un message de la page de la scène : accepté seulement de SON cadre et de notre origine. */
  function parseStatus(event,iframe,origin){
    if(!event||!iframe||event.source!==iframe.contentWindow||iframe.contentWindow==null)return {ok:false,reason:'foreign_source'};
    if(event.origin!==origin)return {ok:false,reason:'bad_origin'};
    const data=event.data;
    if(!plain(data)||data.rsh!==SHELL||data.type!=='status'||!PHASES.includes(data.phase))return {ok:false,reason:'bad_message'};
    const out={phase:data.phase};
    if(data.composition!==undefined){
      const c=data.composition;
      if(!plain(c)||!Number.isInteger(c.width)||!Number.isInteger(c.height)||c.width<16||c.height<16||c.width>7680||c.height>7680)return {ok:false,reason:'bad_composition'};
      out.composition={width:c.width,height:c.height,fps:Number.isInteger(c.fps)?c.fps:30,
        durationInFrames:Number.isInteger(c.durationInFrames)?c.durationInFrames:1};
    }
    for(const key of ['reason','message','title'])if(data[key]!==undefined)out[key]=clip(data[key]);
    if(data.engine_drift!==undefined)out.engine_drift=data.engine_drift===true;
    return {ok:true,status:out};
  }

  /* `clock` de la page de la scène (Slice 12) : même contrôle de source et d'origine que `status`, champs exacts, entiers bornés.
     La position est un conseil du cadre (il peut mentir) : elle ne sert qu'à décider d'un rattrapage DANS la scène. */
  function parseClock(event,iframe,origin){
    if(!event||!iframe||event.source!==iframe.contentWindow||iframe.contentWindow==null)return {ok:false,reason:'foreign_source'};
    if(event.origin!==origin)return {ok:false,reason:'bad_origin'};
    const data=event.data;
    if(!plain(data)||data.rsh!==SHELL||data.type!=='clock')return {ok:false,reason:'bad_message'};
    for(const key of Object.keys(data))if(!['rsh','type','frame','playing','duration','fps'].includes(key))return {ok:false,reason:'extra_field'};
    const inRange=(v,lo,hi)=>Number.isInteger(v)&&v>=lo&&v<=hi;
    if(!inRange(data.duration,1,MAX_FRAMES)||!inRange(data.fps,1,MAX_FPS)||!inRange(data.frame,0,data.duration-1)||typeof data.playing!=='boolean')return {ok:false,reason:'bad_clock'};
    return {ok:true,clock:{frame:data.frame,playing:data.playing,duration:data.duration,fps:data.fps}};
  }

  /* Ligne de temps de la partition (Slice 12, `docs/presentation-studio.md` > *Remotion timeline bridge*). Pur : la fenêtre de scène
     lui donne l'hôte des cadres (`getHost()`), l'horloge et le journal. Il applique la `timeline` que Core met dans la vue de lecture
     au lecteur Remotion : aller au segment, jouer jusqu'à son image d'arrêt, tenir à la pause, reprendre sans revenir en arrière.
     Core reste maître : rien ne revient vers lui, et un rapport de position qui ment ne peut que provoquer un rattrapage borné DANS la
     scène (au plus un par seconde, `MAX_CORRECTIONS` par segment). */
  const MAX_CORRECTIONS=5;
  const CORRECTION_GAP_MS=1000;
  const CLOCK_FRESH_MS=1500;
  const TICK_MS=500;
  /* A frame that never reports (a fresh Player after a remount that missed the order): the order is sent again after this many ticks. */
  const SILENT_TICKS=6;
  const MAX_RESENDS=3;

  function validTimeline(tl){
    if(!plain(tl))return false;
    const int=(v,lo,hi)=>Number.isInteger(v)&&v>=lo&&v<=hi;
    return int(tl.fps,1,MAX_FPS)&&int(tl.duration_frames,1,MAX_FRAMES)&&int(tl.from_frame,0,tl.duration_frames-1)
      &&int(tl.until_frame,tl.from_frame,tl.duration_frames-1)&&int(tl.seq,0,1e9)&&int(tl.play_ms,0,1e10)&&int(tl.tolerance_ms,50,10000)
      &&typeof tl.playing==='boolean';
  }

  function createTimelineFollower(deps){
    const now=deps.now||(()=>Date.now());
    const log=deps.log||(()=>{});
    const every=deps.setInterval||((fn,ms)=>setInterval(fn,ms));
    const stopEvery=deps.clearInterval||((id)=>clearInterval(id));
    const stats={applied:0,pending:0,invalid:0,corrections:0,gaveUp:0,ahead:0,cleared:0,remounted:0,resent:0};
    let current=null;      // {objectId, tl, viewAt}
    let applied=null;      // {objectId, seq, playing, startedAt, lagMs, corrections, lastCorrectionAt, gaveUp}
    let timer=null;

    function frameOf(host,objectId){return typeof host.frame==='function'?host.frame(objectId):undefined}
    function playMsNow(){
      const age=current.tl.playing?Math.max(0,now()-current.viewAt):0;
      return current.tl.play_ms+age;
    }
    function expectedFrame(){
      const tl=current.tl;
      const played=Math.max(0,playMsNow()-applied.lagMs);
      return Math.min(tl.until_frame,tl.from_frame+Math.round(played*tl.fps/1000));
    }
    function order(host,action,frame,until){
      try{return host.control(current.objectId,action,frame,until)===true}
      catch(error){log('warn','timeline.control_failed',{action,error:String(error&&error.message||error)});return false}
    }
    function clear(){
      if(current!==null||applied!==null)stats.cleared++;
      current=null;applied=null;
      if(timer!==null){stopEvery(timer);timer=null}
    }

    /* `detail` : {object_id, timeline|null} (la vue de lecture). Rend l'issue : none, invalid, no_host, pending, segment, playing,
       paused, same. Idempotent : le rappeler avec la même vue ne renvoie aucun ordre. */
    function apply(detail){
      const objectId=detail&&typeof detail.object_id==='string'?detail.object_id:null;
      const tl=detail?detail.timeline:null;
      if(!objectId||!tl){clear();return 'none'}
      if(!validTimeline(tl)){stats.invalid++;log('warn','timeline.invalid',{object_id:objectId});return 'invalid'}
      const host=deps.getHost();
      if(!host||typeof host.control!=='function')return 'no_host';
      current={objectId,tl,viewAt:now()};
      if(timer===null)timer=every(tick,TICK_MS);
      /* The host mounted another frame for this window (hot-reload swap, "Recharger la scène", watchdog restart): a fresh Player sits
         paused on frame 0 and knows nothing of the order we gave its predecessor, so the segment is applied again. */
      if(applied!==null&&applied.objectId===objectId&&applied.frame!==frameOf(host,objectId)){stats.remounted++;applied=null}
      if(applied===null||applied.objectId!==objectId||applied.seq!==tl.seq){
        const ok=order(host,tl.playing?'play':'pause',tl.from_frame,tl.playing?tl.until_frame:undefined);
        if(!ok){stats.pending++;applied=null;return 'pending'}   // the frame is not ready yet: the tick tries again
        applied={objectId,seq:tl.seq,playing:tl.playing,startedAt:now(),lagMs:tl.play_ms,corrections:0,lastCorrectionAt:-1e9,gaveUp:false,
          frame:frameOf(host,objectId),silent:0,resends:0};
        stats.applied++;
        log('info','timeline.segment',{object_id:objectId,anchor_id:tl.anchor_id,from:tl.from_frame,until:tl.until_frame,playing:tl.playing});
        return 'segment';
      }
      if(applied.playing!==tl.playing){
        const ok=order(host,tl.playing?'play':'pause',undefined,tl.playing?tl.until_frame:undefined);
        if(!ok)return 'pending';
        applied.playing=tl.playing;
        return tl.playing?'playing':'paused';
      }
      return 'same';
    }

    /* Rattrapage : seulement quand le lecteur est EN RETARD sur l'horloge de Core de plus que la tolérance (un lecteur en avance
       attend de lui-même sur l'image d'arrêt du segment : rien à corriger). Au plus un ordre par seconde, `MAX_CORRECTIONS` par segment. */
    function tick(){
      if(current===null)return 'idle';
      const host=deps.getHost();
      if(!host)return 'no_host';
      if(applied===null)return apply({object_id:current.objectId,timeline:current.tl});   // pending: try again
      if(applied.frame!==frameOf(host,current.objectId)){stats.remounted++;applied=null;return apply({object_id:current.objectId,timeline:current.tl})}
      const tl=current.tl;
      if(!tl.playing||!applied.playing||typeof host.clock!=='function')return 'idle';
      const clock=host.clock(current.objectId);
      if(!clock||now()-clock.at>CLOCK_FRESH_MS){
        /* Silence while Core says "playing": the order may never have reached this Player. Say it again, a few times, then leave it. */
        if(++applied.silent>=SILENT_TICKS&&applied.resends<MAX_RESENDS){
          const resends=applied.resends+1;
          applied=null;
          const again=apply({object_id:current.objectId,timeline:current.tl});
          if(applied!==null){applied.resends=resends;stats.resent++;log('warn','timeline.resent',{object_id:current.objectId,resends})}
          return again;
        }
        return 'no_clock';
      }
      applied.silent=0;
      const reported=clock.frame+(clock.playing?Math.round((now()-clock.at)*tl.fps/1000):0);
      const expected=expectedFrame();
      const tolerance=Math.max(1,Math.round(tl.tolerance_ms*tl.fps/1000));
      const drift=expected-reported;
      if(drift<-tolerance){stats.ahead++;return 'ahead'}
      if(drift<=tolerance)return 'ok';
      if(clock.frame>=tl.until_frame)return 'ok';   // already on the stop frame: nothing left to catch up
      if(applied.gaveUp)return 'gave_up';
      if(applied.corrections>=MAX_CORRECTIONS){
        applied.gaveUp=true;stats.gaveUp++;
        log('warn','timeline.drift_uncorrectable',{object_id:current.objectId,seq:applied.seq,drift_frames:drift});
        return 'gave_up';
      }
      if(now()-applied.lastCorrectionAt<CORRECTION_GAP_MS)return 'waiting';
      if(!order(host,'play',expected,tl.until_frame))return 'pending';
      applied.corrections++;applied.lastCorrectionAt=now();stats.corrections++;
      log('info','timeline.drift_corrected',{object_id:current.objectId,seq:applied.seq,drift_frames:drift,to:expected});
      return 'corrected';
    }

    return {apply,tick,clear,stats:()=>Object.assign({},stats),state:()=>({
      objectId:current?current.objectId:null,seq:applied?applied.seq:null,corrections:applied?applied.corrections:0,
      gaveUp:applied?applied.gaveUp:false,pending:current!==null&&applied===null})};
  }

  const api=Object.freeze({SHELL,STAGE_PATH,PHASES,stageUrl,createFrame,hostMessage,parseStatus,parseClock,createTimelineFollower,validTimeline,
    TIMELINE:Object.freeze({MAX_CORRECTIONS,CORRECTION_GAP_MS,CLOCK_FRESH_MS,TICK_MS,SILENT_TICKS,MAX_RESENDS})});
  root.JarvisRemotionFrame=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
