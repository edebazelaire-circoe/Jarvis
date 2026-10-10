/* Cadre d'une scène Remotion côté fenêtre de scène (handoff jarvis-remotion-presentation-integration, Slice 10 ;
   `docs/remotion-isolation.md` § 10). Module PUR (aucune minuterie, aucun état) utilisé par `control_center_prefab_host.js` quand le
   paquet d'une version est `{kind: "remotion"}` : il ne monte JAMAIS le bac à sable lui-même.

   Le cadre qu'il crée porte la page de la scène du Control Center (`/remotion-stage`), un document de confiance de la même origine
   qui monte le bac à sable d'une origine dédiée (`control_center_remotion_stage.js`). Raison : la page qui monte le cadre Remotion
   porte `frame-src <origine du bac à sable>` et rien d'autre ; la page principale du Control Center encadre déjà un visualiseur.

   Protocole avec la page de la scène (`rsh: 1`, même origine, source = `contentWindow` du cadre, champs exacts) :
   - fenêtre -> page : `props {props, data?}`, `control {action, frame?}`, `cue {name, frame}`, `teardown {}` ;
   - page -> fenêtre : `status {phase, ...}` avec `phase` parmi `shell`, `preparing`, `mounting`, `ready`, `failed`, `killed`,
     `scene_error`, `notice` (avis transitoire, vide = effacé ; jamais un échec) (`composition`, `reason`, `message`, `title`, `engine_drift` selon la phase). */
(function(root){
  'use strict';
  const SHELL=1;
  const STAGE_PATH='/remotion-stage';
  const PHASES=Object.freeze(['shell','preparing','mounting','ready','failed','killed','scene_error','notice']);
  const HOST_FIELDS=Object.freeze({props:['props','data'],control:['action','frame'],cue:['name','frame'],teardown:[]});
  const ACTIONS=Object.freeze(['play','pause','seek']);
  const MAX_TEXT=300;

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

  const api=Object.freeze({SHELL,STAGE_PATH,PHASES,stageUrl,createFrame,hostMessage,parseStatus});
  root.JarvisRemotionFrame=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
