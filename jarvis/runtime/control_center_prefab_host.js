/* Hôte des cadres de prefab (handoff jarvis-scene-window-prefab-foundation, Slice 03 ;
   docs/prefabs.md › *Runtime*, *Message protocol*). Module DOM, exposé en
   `window.JarvisPrefabHost` dans la page et en `module.exports` pour node.

   SEUL fichier du runtime qui pose `iframe.srcdoc` (test statique) : le seul
   chemin HTML de la page, qui n'insère jamais de balisage en chaîne. Le document du cadre est
   construit par `JarvisPrefabProtocol.buildSrcdoc` ; l'attribut `sandbox` vaut
   exactement `JarvisPrefabProtocol.SANDBOX` (`allow-scripts`), posé AVANT
   `srcdoc`.

   `createPrefabHost(deps)` :
   - `deps.fetchBundle(id, version)` -> promesse du paquet de version
     (`GET /api/prefabs/{id}/{version}/bundle`) ; gardé en mémoire par
     `id@version` (une version publiée ne change jamais), un échec n'est pas gardé ;
   - `deps.document`, `deps.window` (écoute `message`, `open`) ;
   - `deps.now`, `deps.setTimeout`, `deps.clearTimeout` (horloge injectable) ;
   - `deps.log(key, data)` : journal du client (`scene.prefab_error`,
     `scene.prefab_message_dropped`, `scene.prefab_event_rate_limited`,
     `scene.prefab_event_failed`, `scene.prefab_mounted`) ;
   - `deps.postEvent(event)` : envoi d'un événement à Core (Slice 04) ; jamais
     appelé en mode `preview` (`deps.onPreviewEvent(event)` à la place) ;
   - `deps.mode` : `scene` (défaut) ou `preview` ; `deps.theme` : thème par défaut ;
   - `deps.onResize(objectId, height)`, `deps.openUrl(url)` (défaut
     `window.open(url, '_blank', 'noopener,noreferrer')`).

   Rend `{mount(slot, instance), update(objectId, props, data, theme),
   unmount(objectId), pause(objectId), resume(objectId), touch(objectId),
   reload(objectId), height(objectId), has(objectId), stats(), destroy()}`.

   Règles tenues ici :
   - un cadre par objet, jamais détaché pendant une mise à jour : `update`
     poste `update` (diff par chaîne JSON) ; remontage seulement sur
     changement de `(id, version)` ou de conteneur, ou sur `reload` ;
   - un message n'est accepté que si `event.source` est le `contentWindow` du
     cadre ET `event.origin === "null"` ; tout le reste est refusé et compté ;
   - au plus `LIVE_CAP` (24) cadres vivants, le moins récemment dessiné passe
     en pause (texte statique avec le titre) ;
   - au plus 10 sorties par seconde et par cadre (`event`, `open_url`), le
     reste refusé et compté ;
   - bande d'erreur dans le conteneur sur `error`, ou sans `ready` dans les 3 s
     (« Prefab <id>@<v> failed: <message> »), avec « Recharger » ; le chrome de
     la fenêtre reste à la page, donc utilisable ;
   - `teardown` posté avant le retrait, le cadre retiré 50 ms plus tard ;
     l'écoute `message` est retirée quand il ne reste aucun cadre. */
(function(root){
  'use strict';
  const P=root.JarvisPrefabProtocol||(typeof require==='function'?require('./control_center_prefab_protocol.js'):null);
  const LIVE_CAP=24;
  const READY_TIMEOUT_MS=3000;
  const TEARDOWN_MS=50;
  const OUTPUT_RATE=10;
  const RATE_WINDOW_MS=1000;
  const MAX_LOGS_PER_FRAME=5;
  const STYLE_ID='jv-prefab-host-style';
  const DEFAULT_THEME=Object.freeze({name:'scene',accent:'#6ee7ff',text:'#dcecf4',muted:'#8aa5b3',surface:'rgba(4,10,15,.88)',scale:1});
  const LIVE_STATES=new Set(['loading','ready','error']);
  /* Styles de l'hôte : conteneur, cadre, bande d'erreur, pause. Variables de la scène quand elles existent. */
  const HOST_CSS=`
.sc-prefab-slot{position:relative;display:flex;flex-direction:column;flex:1 1 auto;min-height:24px;min-width:0}
.sc-prefab-frame{display:block;flex:none;width:100%;min-height:24px;border:0;background:transparent;color-scheme:dark}
.sc-prefab-note{margin:0 13px 10px;font:11.5px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--sc-muted,#8aa5b3)}
.sc-prefab-loading::after{content:'';display:inline-block;width:1.2em;text-align:left;animation:sc-prefab-dots 1.2s steps(4,end) infinite}
@keyframes sc-prefab-dots{0%{content:''}25%{content:'.'}50%{content:'..'}75%{content:'...'}}
.sc-prefab-paused{padding:10px 11px;border:1px dashed var(--sc-edge,rgba(151,191,209,.16));border-radius:6px}
.sc-prefab-paused-title{display:block;color:var(--sc-ink,#dcecf4);font-weight:600;overflow-wrap:anywhere}
.sc-prefab-error{display:flex;align-items:flex-start;gap:10px;margin:0 13px 8px;padding:7px 9px;border-radius:6px;
  border:1px solid rgba(255,107,125,.5);background:rgba(255,107,125,.1);color:#ffd5db;
  font:11.5px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere}
.sc-prefab-error-text{flex:1 1 auto;min-width:0}
.sc-prefab-retry{flex:none;appearance:none;padding:2px 8px;border:1px solid rgba(255,107,125,.55);border-radius:5px;background:transparent;
  color:#ffe4e8;font:inherit;cursor:pointer}
.sc-prefab-retry:hover{background:rgba(255,107,125,.16)}
.sc-prefab-retry:focus-visible{outline:1px solid var(--sc-ink,#dcecf4);outline-offset:1px}
@media (prefers-reduced-motion:reduce){.sc-prefab-loading::after{animation:none;content:'...'}}
`;

  function describe(error){
    if(error&&typeof error==='object'&&typeof error.message==='string')return error.message;
    return String(error);
  }

  function json(value){
    try{return JSON.stringify(value===undefined?{}:value)}catch(_error){return '{}'}
  }

  /* Paquet de version par le relais du Control Center, `response.ok` vérifié,
     enveloppe d'erreur `{error: {code, message}}` dépliée dans le message. */
  function bundleFetcher(fetchImpl){
    return async function(id,version){
      const path=`/api/prefabs/${encodeURIComponent(id)}/${encodeURIComponent(String(version))}/bundle`;
      const response=await fetchImpl(path,{headers:{Accept:'application/json'}});
      let body=null;
      try{body=await response.json()}catch(_error){body=null}
      if(!response.ok){
        const error=body&&body.error;
        const code=error&&error.code?error.code:`http_${response.status}`;
        throw new Error(`${code}: ${error&&error.message?error.message:`HTTP ${response.status}`}`);
      }
      if(!body||typeof body!=='object')throw new Error('bundle response is not JSON');
      return body;
    };
  }

  function createPrefabHost(deps){
    const d=deps||{};
    if(!P)throw new Error('JarvisPrefabProtocol is not loaded');
    if(typeof d.fetchBundle!=='function')throw new TypeError('createPrefabHost: fetchBundle is required');
    const doc=d.document;
    const win=d.window;
    if(!doc||!win)throw new TypeError('createPrefabHost: document and window are required');
    const mode=d.mode==='preview'?'preview':'scene';
    const now=typeof d.now==='function'?d.now:()=>Date.now();
    const later=typeof d.setTimeout==='function'?d.setTimeout:(fn,ms)=>setTimeout(fn,ms);
    const cancel=typeof d.clearTimeout==='function'?d.clearTimeout:(id)=>clearTimeout(id);
    const log=typeof d.log==='function'?d.log:()=>{};
    const baseTheme=Object.assign({},DEFAULT_THEME,d.theme||{});
    const frames=new Map();
    const bundles=new Map();
    const departing=new Set();
    const totals={dropped:0,rateLimited:0,previewEvents:0,postedEvents:0,errors:0};
    let listening=false;

    function safeLog(key,data){
      try{log(key,data)}catch(_error){/* intentional: a broken journal never breaks a frame */}
    }

    function frameLog(rec,key,data){
      rec.logs=(rec.logs||0)+1;
      if(rec.logs<=MAX_LOGS_PER_FRAME)safeLog(key,Object.assign({object_id:rec.objectId,prefab:rec.key},data));
    }

    function ensureStyle(){
      if(typeof doc.getElementById!=='function'||doc.getElementById(STYLE_ID))return;
      const style=doc.createElement('style');
      style.id=STYLE_ID;
      style.textContent=HOST_CSS;
      (doc.head||doc.body).appendChild(style);
    }

    function element(tag,className,text){
      const el=doc.createElement(tag);
      if(className)el.className=className;
      if(text!==undefined)el.textContent=text;
      return el;
    }

    function liveCount(except){
      let count=0;
      for(const rec of frames.values())if(rec!==except&&LIVE_STATES.has(rec.state))count++;
      return count;
    }

    function listen(){
      if(listening)return;
      win.addEventListener('message',onMessage);
      listening=true;
    }

    function unlisten(){
      if(!listening||frames.size)return;
      win.removeEventListener('message',onMessage);
      listening=false;
    }

    function loadBundle(prefab){
      const key=`${prefab.id}@${prefab.version}`;
      let pending=bundles.get(key);
      if(!pending){
        pending=Promise.resolve().then(()=>d.fetchBundle(prefab.id,prefab.version));
        bundles.set(key,pending);
        pending.catch(()=>{if(bundles.get(key)===pending)bundles.delete(key)});
      }
      return pending;
    }

    /* ------------------------------------------------------------ conteneur */

    /* Vide le conteneur sauf les cadres qui partent (ils ont encore `TEARDOWN_MS`). */
    function clearSlot(slot){
      for(const child of Array.from(slot.childNodes||slot.children||[])){
        if(!departing.has(child))slot.removeChild(child);
      }
    }

    function setNote(rec,className,text){
      clearNote(rec);
      rec.note=element('p',`sc-prefab-note ${className}`,text);
      rec.slot.insertBefore(rec.note,rec.iframe||null);
    }

    function clearNote(rec){
      if(rec.note&&rec.note.parentNode===rec.slot)rec.slot.removeChild(rec.note);
      rec.note=null;
    }

    function showBand(rec,message,reason){
      rec.bandReason=reason;
      const text=`Prefab ${rec.key} failed: ${message}`;
      if(rec.band&&rec.band.parentNode===rec.slot){rec.bandText.textContent=text;return}
      const band=element('div','sc-prefab-error');
      band.setAttribute('role','alert');
      const label=element('span','sc-prefab-error-text',text);
      const retry=element('button','sc-prefab-retry','Recharger');
      retry.type='button';
      retry.setAttribute('aria-label',`Recharger le prefab ${rec.key}`);
      retry.addEventListener('click',(event)=>{event.stopPropagation();reload(rec.objectId)});
      band.appendChild(label);band.appendChild(retry);
      rec.band=band;rec.bandText=label;
      rec.slot.insertBefore(band,rec.slot.firstChild||null);
    }

    function clearBand(rec){
      if(rec.band&&rec.band.parentNode===rec.slot)rec.slot.removeChild(rec.band);
      rec.band=null;rec.bandText=null;rec.bandReason=null;
    }

    function fail(rec,message,reason){
      totals.errors++;
      if(rec.state!=='paused')rec.state='error';
      clearNote(rec);
      showBand(rec,message,reason||'error');
      frameLog(rec,'scene.prefab_error',{message,reason:reason||'error'});
    }

    /* ------------------------------------------------------------ cycle de vie */

    function start(rec){
      rec.generation++;
      const generation=rec.generation;
      cancel(rec.readyTimer);
      clearSlot(rec.slot);
      rec.band=null;rec.note=null;rec.ready=false;rec.bundle=null;rec.events=new Map();
      const iframe=element('iframe','sc-prefab-frame');
      /* `sandbox` d'abord : le document ne doit jamais exister sans lui. */
      iframe.setAttribute('sandbox',P.SANDBOX);
      iframe.setAttribute('referrerpolicy','no-referrer');
      iframe.setAttribute('title',rec.title?`${rec.title} (prefab ${rec.key})`:`Prefab ${rec.key}`);
      iframe.style.height=`${rec.height||P.RESIZE_MIN}px`;
      rec.iframe=iframe;
      rec.state='loading';
      rec.slot.appendChild(iframe);
      setNote(rec,'sc-prefab-loading',`Chargement du prefab ${rec.key}`);
      listen();
      rec.readyTimer=later(()=>{
        /* Déjà en erreur (paquet refusé, exception au chargement) : la vraie cause reste affichée. */
        if(rec.generation!==generation||rec.ready||!frames.has(rec.objectId)||rec.state==='error')return;
        fail(rec,`no ready within ${READY_TIMEOUT_MS/1000} s`,'timeout');
      },READY_TIMEOUT_MS);
      loadBundle(rec.prefab).then((bundle)=>{
        if(rec.generation!==generation||!frames.has(rec.objectId))return;
        let srcdoc;
        try{srcdoc=P.buildSrcdoc(bundle)}catch(error){cancel(rec.readyTimer);fail(rec,describe(error),'bundle');return}
        rec.bundle=bundle;
        rec.events=P.declaredEvents(bundle.manifest);
        iframe.srcdoc=srcdoc;
      },(error)=>{
        if(rec.generation!==generation||!frames.has(rec.objectId))return;
        cancel(rec.readyTimer);
        fail(rec,describe(error),'bundle');
      });
    }

    function departure(rec){
      const iframe=rec.iframe;
      rec.iframe=null;
      cancel(rec.readyTimer);
      if(!iframe)return;
      if(rec.ready)post(rec,P.hostMessage('teardown'),iframe);
      rec.ready=false;
      departing.add(iframe);
      later(()=>{
        departing.delete(iframe);
        if(iframe.parentNode)iframe.parentNode.removeChild(iframe);
      },TEARDOWN_MS);
    }

    function post(rec,message,iframe){
      const target=(iframe||rec.iframe);
      const view=target&&target.contentWindow;
      if(!view)return false;
      try{view.postMessage(message,'*');return true}catch(error){
        frameLog(rec,'scene.prefab_error',{message:`post failed: ${describe(error)}`,reason:'post'});
        return false;
      }
    }

    function hostFields(rec){
      const blocks=rec.bundle?P.markdownBlocksOf(rec.bundle.manifest,rec.props,rec.data):{};
      return {props:rec.props,data:rec.data,theme:rec.theme,blocks};
    }

    function sendInit(rec){
      const fields=hostFields(rec);
      fields.instance={object_id:rec.objectId,prefab:rec.prefab,mode};
      if(post(rec,P.hostMessage('init',fields)))rec.sentData=P.cloneJson(rec.data);
    }

    /* Place pour `rec` : les AUTRES cadres vivants restent sous le plafond. */
    function evictFor(rec){
      while(liveCount(rec)>=LIVE_CAP){
        let oldest=null;
        for(const other of frames.values()){
          if(other===rec||!LIVE_STATES.has(other.state))continue;
          if(!oldest||other.lastDraw<oldest.lastDraw)oldest=other;
        }
        if(!oldest)return;
        pause(oldest.objectId);
      }
    }

    function checkInstance(instance){
      const prefab=instance&&instance.prefab;
      if(!instance||typeof instance.object_id!=='string'||!instance.object_id)throw new TypeError('mount: object_id is required');
      if(!prefab||typeof prefab.id!=='string'||!Number.isInteger(prefab.version)||prefab.version<1){
        throw new TypeError('mount: prefab {id, version} is required');
      }
    }

    function mount(slot,instance){
      checkInstance(instance);
      if(!slot||typeof slot.appendChild!=='function')throw new TypeError('mount: slot must be an element');
      ensureStyle();
      const objectId=instance.object_id;
      const prefab={id:instance.prefab.id,version:instance.prefab.version};
      const key=`${prefab.id}@${prefab.version}`;
      const existing=frames.get(objectId);
      if(existing){
        if(existing.key===key&&existing.slot===slot){
          existing.title=instance.title||existing.title;
          touch(objectId);
          update(objectId,instance.props,instance.data,instance.theme);
          return false;
        }
        unmount(objectId);
      }
      if(slot.classList)slot.classList.add('sc-prefab-slot');
      const rec={objectId,prefab,key,slot,title:typeof instance.title==='string'?instance.title:'',
        props:P.cloneJson(instance.props||{}),data:P.cloneJson(instance.data||{}),
        theme:Object.assign({},baseTheme,instance.theme||{}),state:'loading',generation:0,lastDraw:now(),
        outputs:[],dropped:0,rateLimited:0,height:0,sentData:null,iframe:null,readyTimer:null,logs:0};
      rec.propsJson=json(rec.props);rec.dataJson=json(rec.data);rec.themeJson=json(rec.theme);
      frames.set(objectId,rec);
      evictFor(rec);
      start(rec);
      safeLog('scene.prefab_mounted',{object_id:objectId,prefab:key,mode});
      return true;
    }

    function update(objectId,props,data,theme){
      const rec=frames.get(objectId);
      if(!rec)return false;
      const nextTheme=Object.assign({},baseTheme,theme||{});
      const texts={props:json(props||{}),data:json(data||{}),theme:json(nextTheme)};
      if(texts.props===rec.propsJson&&texts.data===rec.dataJson&&texts.theme===rec.themeJson)return false;
      rec.props=JSON.parse(texts.props);rec.data=JSON.parse(texts.data);rec.theme=nextTheme;
      rec.propsJson=texts.props;rec.dataJson=texts.data;rec.themeJson=texts.theme;
      if(rec.ready&&post(rec,P.hostMessage('update',hostFields(rec))))rec.sentData=P.cloneJson(rec.data);
      return true;
    }

    function unmount(objectId){
      const rec=frames.get(objectId);
      if(!rec)return false;
      rec.generation++;
      departure(rec);
      clearNote(rec);clearBand(rec);
      frames.delete(objectId);
      rec.state='removed';
      unlisten();
      return true;
    }

    function pause(objectId){
      const rec=frames.get(objectId);
      if(!rec||rec.state==='paused')return false;
      rec.generation++;
      departure(rec);
      clearNote(rec);clearBand(rec);
      clearSlot(rec.slot);
      rec.state='paused';
      const box=element('div','sc-prefab-note sc-prefab-paused');
      box.appendChild(element('span','sc-prefab-paused-title',rec.title||rec.key));
      box.appendChild(doc.createTextNode(`En pause : au plus ${LIVE_CAP} prefabs vivants. Sélectionnez la fenêtre pour la reprendre.`));
      rec.slot.appendChild(box);
      rec.note=box;
      return true;
    }

    function resume(objectId){
      const rec=frames.get(objectId);
      if(!rec||rec.state!=='paused')return false;
      rec.lastDraw=now();
      evictFor(rec);
      start(rec);
      return true;
    }

    function touch(objectId){
      const rec=frames.get(objectId);
      if(!rec)return false;
      rec.lastDraw=now();
      if(rec.state==='paused')resume(objectId);
      return true;
    }

    function reload(objectId){
      const rec=frames.get(objectId);
      if(!rec)return false;
      departure(rec);
      rec.lastDraw=now();
      if(rec.state==='paused')evictFor(rec);
      start(rec);
      return true;
    }

    /* ------------------------------------------------------------ messages */

    function find(source){
      if(!source)return null;
      for(const rec of frames.values())if(rec.iframe&&rec.iframe.contentWindow===source)return rec;
      return null;
    }

    function drop(rec,reason){
      totals.dropped++;rec.dropped++;
      frameLog(rec,'scene.prefab_message_dropped',{reason,dropped:rec.dropped});
    }

    function allowOutput(rec){
      const t=now();
      rec.outputs=rec.outputs.filter((at)=>t-at<RATE_WINDOW_MS);
      if(rec.outputs.length>=OUTPUT_RATE){
        totals.rateLimited++;rec.rateLimited++;
        if(rec.rateLimited===1||rec.rateLimited%50===0){
          safeLog('scene.prefab_event_rate_limited',{object_id:rec.objectId,prefab:rec.key,rate_limited:rec.rateLimited});
        }
        return false;
      }
      rec.outputs.push(t);
      return true;
    }

    function onEvent(rec,message){
      if(!rec.ready){drop(rec,'event before ready');return}
      const decl=rec.events.get(message.name);
      if(!decl){drop(rec,`undeclared event ${message.name}`);return}
      if(!allowOutput(rec))return;
      const basis={};
      if(decl.class==='state'){
        const sent=rec.sentData||{};
        for(const key of Object.keys(message.payload)){
          if(Object.prototype.hasOwnProperty.call(sent,key))basis[key]=P.cloneJson(sent[key]);
        }
      }
      const event={object_id:rec.objectId,prefab:{id:rec.prefab.id,version:rec.prefab.version},event:message.name,
        payload:message.payload,basis};
      if(mode==='preview'){
        totals.previewEvents++;
        try{if(typeof d.onPreviewEvent==='function')d.onPreviewEvent(event)}catch(_error){/* intentional: preview display only */}
        return;
      }
      if(typeof d.postEvent!=='function'){drop(rec,'no event sink');return}
      totals.postedEvents++;
      Promise.resolve().then(()=>d.postEvent(event)).then((result)=>{
        const outcome=result&&result.outcome;
        if(outcome&&outcome!=='applied'&&outcome!=='recorded'){
          frameLog(rec,'scene.prefab_event_failed',{event:message.name,outcome,reason:result.reason||null});
        }
      },(error)=>{
        frameLog(rec,'scene.prefab_event_failed',{event:message.name,error:describe(error).slice(0,300)});
      });
    }

    function openUrl(rec,url){
      if(!allowOutput(rec))return;
      try{
        if(typeof d.openUrl==='function')d.openUrl(url);
        else if(typeof win.open==='function')win.open(url,'_blank','noopener,noreferrer');
      }catch(error){frameLog(rec,'scene.prefab_error',{message:`open_url failed: ${describe(error)}`,reason:'open_url'})}
    }

    function onMessage(event){
      const rec=find(event&&event.source);
      if(!rec)return;  // not one of our frames (another iframe of the page): not ours to judge
      if(event.origin!=='null'){drop(rec,'origin is not opaque');return}
      const parsed=P.parseFrameMessage(event.data);
      if(!parsed.ok){drop(rec,parsed.reason);return}
      const message=parsed.message;
      switch(message.type){
        case 'ready':
          cancel(rec.readyTimer);
          rec.ready=true;
          clearNote(rec);
          if(rec.state==='loading')rec.state='ready';
          if(rec.bandReason==='timeout'){clearBand(rec);rec.state='ready'}
          sendInit(rec);
          break;
        case 'resize':
          rec.height=message.height;
          if(rec.iframe)rec.iframe.style.height=`${message.height}px`;
          try{if(typeof d.onResize==='function')d.onResize(rec.objectId,message.height)}catch(_error){/* intentional: layout hint only */}
          break;
        case 'event':onEvent(rec,message);break;
        case 'open_url':openUrl(rec,message.url);break;
        case 'error':fail(rec,message.message,'frame');break;
      }
    }

    function stats(){
      let paused=0,ready=0,errors=0,loading=0;
      for(const rec of frames.values()){
        if(rec.state==='paused')paused++;
        else if(rec.state==='ready')ready++;
        else if(rec.state==='error')errors++;
        else if(rec.state==='loading')loading++;
      }
      return Object.assign({frames:frames.size,live:liveCount(),ready,loading,errorFrames:errors,paused,
        listening,bundles:bundles.size,departing:departing.size},totals);
    }

    function destroy(){
      for(const objectId of Array.from(frames.keys()))unmount(objectId);
    }

    return Object.freeze({mount,update,unmount,pause,resume,touch,reload,stats,destroy,
      has:(objectId)=>frames.has(objectId),
      height:(objectId)=>{const rec=frames.get(objectId);return rec?rec.height:0},
      state:(objectId)=>{const rec=frames.get(objectId);return rec?rec.state:null}});
  }

  const api=Object.freeze({LIVE_CAP,READY_TIMEOUT_MS,TEARDOWN_MS,OUTPUT_RATE,DEFAULT_THEME,createPrefabHost,bundleFetcher});
  root.JarvisPrefabHost=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
