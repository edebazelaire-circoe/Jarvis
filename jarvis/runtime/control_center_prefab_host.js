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
     `id@version` (une version publiée ne change jamais), au plus
     `BUNDLE_CACHE_CAP` (64) paquets, le moins récemment servi oublié ; un
     échec de chargement ou un paquet que `buildSrcdoc` refuse n'est pas gardé
     (« Recharger » le redemande) ;
   - `deps.document`, `deps.window` (écoute `message`, `open`) ;
   - `deps.now`, `deps.setTimeout`, `deps.clearTimeout` (horloge injectable) ;
   - `deps.log(key, data)` : journal du client (`scene.prefab_error`,
     `scene.prefab_message_dropped`, `scene.prefab_event_rate_limited`,
     `scene.prefab_event_failed`, `scene.prefab_mounted`) ;
   - `deps.onOutcome(info)` (rechargement à chaud du Studio, Slice 06) : **une** fois par génération de cadre, ce que
     l'hôte a OBSERVÉ — `{object_id, prefab:{id, version}, outcome: 'mounted'|'failed', reason, message, generation,
     counters}`. `mounted` = le cadre a dit `ready` ET aucune erreur n'est venue dans les `SETTLE_MS` (250 ms) qui suivent
     l'`init` (un comportement qui lève au premier rendu n'est pas « monté ») ; `failed` = la première erreur de la
     génération (`bundle`, `frame`, `timeout`, `navigation`, `protocol`) avec son message (non fiable : texte du cadre).
     Aucun nouveau message `jv:1`, aucun droit de plus pour le cadre : c'est l'hôte qui regarde. Une exception de
     `onOutcome` est journalisée, jamais propagée ;
   - `deps.swapPrefix` (rechargement à chaud du Studio, Slice 06) : un préfixe d'id de prefab (`presentation-studio.`). Quand
     la version d'un cadre PRÊT passe à une version de cet espace, le nouveau cadre est chargé À CÔTÉ, invisible
     (`sc-prefab-staged`, même conteneur, mêmes règles de confinement) et ne remplace l'ancien que s'il est monté (`ready`
     puis `SETTLE_MS` sans erreur) : pas de cadre blanc entre deux versions, et une source qui échoue au montage laisse
     l'ancien cadre — son DOM, son état local — intact (rapport `failed`, aucune bande dans le cadre). Si le pin revient à
     la version du cadre vivant (retour arrière de Core), rien n'est remonté. Hors de cet espace, la règle est inchangée :
     remontage immédiat sur changement de `(id, version)`. Le cadre « en attente » ne reçoit ni n'émet rien d'utile avant sa
     promotion (ses événements sont refusés) et ne change pas la hauteur de la fenêtre ;
   - `deps.onLive(objectId)` (Slice 23) : un Player Remotion vient de devenir celui de la fenêtre (premier montage, échange à chaud, préchargé
     promu) : le suiveur de ligne de temps applique tout de suite ce que Core a dit ; `deps.onClock(objectId)` : la position du lecteur vivant
     vient d'arriver (l'image d'arrêt est vue quand elle est atteinte, pas au tick suivant) ;
   - `host.preload(objectId, instance)` (Slice 23) : charge à côté, invisible et en pause sur l'image 0, la scène qui suit, pour que le passage
     de l'une à l'autre n'attende ni compilation ni démarrage du bac à sable ; le `mount` de cette scène la prend alors sur-le-champ.
     Slice 05 (native-studio-playback-fix) : un préchargement ne jette jamais le cadre déjà préparé à côté, il attend qu'il ait pris la
     fenêtre (file d'une place) ; `instance.scene_id` (facultatif) dit quand un nouveau pin est une AUTRE scène et pas une nouvelle version :
     ses valeurs ne vont alors qu'au cadre entrant, et son échec prend la fenêtre au lieu d'être caché derrière la scène précédente ;
   - `host.counters(objectId)` -> `{starts, mounted, failed, remounts}` de cet objet (survivent à un remontage de version,
     disparaissent au démontage) : les tests de fuite d'un rechargement répété lisent ça et `stats()` ;
   - `deps.postEvent(event)` : envoi d'un événement à Core (Slice 04) ; jamais
     appelé en mode `preview` (`deps.onPreviewEvent(event)` à la place). Sa
     promesse rend `{outcome, ...}` ou est rejetée (Core injoignable, statut
     HTTP d'erreur : `error.code` s'il existe, `rate_limited` pour un 429).
     L'issue revient au cadre par `event_result {name, outcome, reason?}`
     (reprise QA S04/S06, A4) : `applied`, `recorded`, `stale`, `refused`
     (refus de Core ou de l'hôte : `undeclared_event`, `too_large`,
     `rate_limited`) ou `failed` (rejet). Sur `stale`, l'hôte renvoie aussitôt
     son état connu par un `update` **forcé** (`force: true`) : le shim le
     passe au comportement même s'il est identique au dernier reçu, et le
     cadre se recale sans attendre le flux de scène ;
   - basis d'un événement `state` : pour chaque clé écrite, la valeur que le
     cadre a reçue en dernier, `null` s'il ne l'a jamais reçue — la règle de
     Core, qui lit une clé absente comme `null` (A2) ;
   - `deps.mode` : `scene` (défaut) ou `preview` ; `deps.theme` : thème par défaut ;
   - `deps.onResize(objectId, height)`, `deps.openUrl(url)` (défaut
     `window.open(url, '_blank', 'noopener,noreferrer')`).

   Exporte aussi le pont avec la scène (Slice 04) : `sceneSlot`, `clearAround`,
   `placeAround`, `syncScene` (voir plus bas).

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
   - au plus 10 sorties par seconde et par cadre (`event`, `open_url`), au
     plus 10 `error` par seconde, le reste refusé et compté ; `resize`
     appliqué au plus une fois par 16 ms (le dernier gagne) ;
   - confinement (docs/prefabs.md › *Containment*) : une génération a UN
     document et UN `ready`. Un second `load` du cadre (il a navigué :
     `location.href`, lien) ou un second `ready` est une violation : le cadre
     est retiré sans `teardown`, ses messages ne sont plus entendus, aucun
     `init` n'est renvoyé, bande d'erreur et `scene.prefab_error`
     (`navigation`, `protocol`) ;
   - le plafond de 5 journaux par cadre repart à chaque génération ;
   - bande d'erreur dans le conteneur sur `error`, ou sans `ready` dans les 3 s
     (« Prefab <id>@<v> failed: <message> »), avec « Recharger » ; le chrome de
     la fenêtre reste à la page, donc utilisable ;
   - `teardown` posté avant le retrait, le cadre retiré 50 ms plus tard ;
     l'écoute `message` est retirée quand il ne reste aucun cadre. */
(function(root){
  'use strict';
  const P=root.JarvisPrefabProtocol||(typeof require==='function'?require('./control_center_prefab_protocol.js'):null);
  /* Scène Remotion (Slice 10) : un paquet `{kind: "remotion"}` est délégué à la page de la scène (`control_center_remotion_frame.js`). */
  const R=root.JarvisRemotionFrame||(typeof require==='function'?require('./control_center_remotion_frame.js'):null);
  const REMOTION_READY_TIMEOUT_MS=165000;
  const LIVE_CAP=24;
  const READY_TIMEOUT_MS=3000;
  const TEARDOWN_MS=50;
  const OUTPUT_RATE=10;
  const RATE_WINDOW_MS=1000;
  const MAX_LOGS_PER_FRAME=5;
  const ERROR_RATE=10;
  const RESIZE_COALESCE_MS=16;
  const BUNDLE_CACHE_CAP=64;
  const SETTLE_MS=250;
  /* Lecture continue (Slice 23) : un Player Remotion démarre PAUSÉ sur sa première image ; la ligne de temps de la partition (ou, à défaut,
     ce délai) décide de la suite. Avant, il jouait depuis l'image 0 puis sautait à son segment : la scène se rejouait à chaque montage. */
  const HOLD_GRACE_MS=450;
  /* Après une mise à jour de valeurs d'un cadre préchargé, le temps de les rendre avant qu'il ne prenne la place du vivant. */
  const PROPS_SETTLE_MS=120;
  /* Scène Remotion (Slice 14) : `ready` de la page de scène dit que le bac à sable est chargé, pas que la scène a RENDU. Le premier `clock` du
     lecteur (posé à son montage, après le premier rendu ; une erreur de rendu arrive avant lui) en est la preuve ; sans lui dans ce délai, la
     scène n'est pas montée. */
  const RENDER_PROOF_MS=10000;
  const STYLE_ID='jv-prefab-host-style';
  const DEFAULT_THEME=Object.freeze({name:'scene',accent:'#6ee7ff',text:'#dcecf4',muted:'#8aa5b3',surface:'rgba(4,10,15,.88)',scale:1});
  const LIVE_STATES=new Set(['loading','ready','error']);
  /* Styles de l'hôte : conteneur, cadre, bande d'erreur, pause. Variables de la scène quand elles existent. */
  /* Le cadre prend la hauteur qu'il rapporte, mais rétrécit jusqu'à la fenêtre
     (`flex-shrink`) : un contenu plus haut que la fenêtre défile **dans** le
     cadre (molette, Page haut/bas du prefab), jamais dans deux défileurs
     emboîtés, et au-delà des 4000 px du plafond de `resize` (Slice 05). */
  /* Staged frames (Slice 05) are transparent, not visibility:hidden: Chrome stops rendering a hidden cross-origin frame, so the first
     composite after the swap could be black (one dark capture at a run-stage boundary). At opacity 0 a staged frame keeps its painted
     first frame and is shown at once; inert + aria-hidden keep it out of focus and of the accessibility tree while it waits. */
  const HOST_CSS=`
.sc-prefab-slot{position:relative;display:flex;flex-direction:column;flex:1 1 auto;min-height:24px;min-width:0}
.sc-prefab-frame{display:block;flex:0 1 auto;width:100%;min-height:24px;border:0;background:transparent;color-scheme:dark}
.sc-prefab-note{margin:0 13px 10px;font:11.5px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--sc-muted,#8aa5b3)}
.sc-prefab-loading::after{content:'';display:inline-block;width:1.2em;text-align:left;animation:sc-prefab-dots 1.2s steps(4,end) infinite}
@keyframes sc-prefab-dots{0%{content:''}25%{content:'.'}50%{content:'..'}75%{content:'...'}}
.sc-prefab-warning{padding:5px 8px;border-left:2px solid #ffc861;color:#ffe3b0}
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
.sc-remotion-frame{flex:0 0 auto;height:auto;min-height:150px;aspect-ratio:16/9;background:#000}
.sc-prefab-staged{position:absolute;left:0;top:0;opacity:0;pointer-events:none}
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
    const swapPrefix=typeof d.swapPrefix==='string'?d.swapPrefix:'';
    /* Variants (native-studio-playback-fix Slice 06): its Player opens paused and only its transport plays it (§ 4.1). `autoplay: false`
       drops the grace-period play; `embed` tells the stage page it has no bar of its own (`R.stageUrl`). The run stage keeps both. */
    const autoplay=d.autoplay!==false;
    const embed=typeof d.embed==='string'?d.embed:undefined;
    /* Sound (native-studio-playback-fix Slice 08): the sound the page wants for its Remotion Players (`sound(muted)`), `null` until it says
       (then each stage keeps the old rule: a click in the scene turns the sound on). Only the LIVE frame of an object gets it: a frame loaded
       ahead or a hot-reload candidate stays muted until it takes the window (`promote`), so only the scene on screen is ever audible. */
    let soundMuted=null;
    const frames=new Map();
    const bundles=new Map();
    const departing=new Set();
    const totals={dropped:0,rateLimited:0,previewEvents:0,postedEvents:0,errors:0,starts:0,mounted:0,failed:0};
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

    /* Le cadre est-il encore à nous ? Soit le cadre vivant de son objet, soit celui qu'on y prépare à côté (`next`). */
    function owned(rec){
      const current=frames.get(rec.objectId);
      return current===rec||(!!current&&current.next===rec);
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

    /* Cache LRU : l'ordre d'insertion de la `Map` est l'ordre d'usage. */
    function loadBundle(prefab){
      const key=`${prefab.id}@${prefab.version}`;
      let pending=bundles.get(key);
      if(pending)bundles.delete(key);
      else{
        pending=Promise.resolve().then(()=>d.fetchBundle(prefab.id,prefab.version));
        pending.catch(()=>forgetBundle(key,pending));
      }
      bundles.set(key,pending);
      while(bundles.size>BUNDLE_CACHE_CAP)bundles.delete(bundles.keys().next().value);
      return pending;
    }

    function forgetBundle(key,pending){
      if(bundles.get(key)===pending)bundles.delete(key);
    }

    /* ------------------------------------------------------------ conteneur */

    /* Vide le conteneur sauf les cadres qui partent (ils ont encore `TEARDOWN_MS`). */
    function clearSlot(slot){
      for(const child of Array.from(slot.childNodes||slot.children||[])){
        if(!departing.has(child))slot.removeChild(child);
      }
    }

    function setNote(rec,className,text){
      if(rec.staged)return;   // the live frame is still on screen: nothing to announce inside the window
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

    function setNotice(rec,text){
      if(rec.noticeEl&&rec.noticeEl.parentNode===rec.slot)rec.slot.removeChild(rec.noticeEl);
      rec.noticeEl=null;
      if(!text||rec.staged)return;
      const line=element('p','sc-prefab-note sc-prefab-warning',text);
      line.setAttribute('role','status');
      rec.slot.insertBefore(line,rec.slot.firstChild||null);
      rec.noticeEl=line;
      frameLog(rec,'scene.prefab_notice',{reason:'props_refused'});   // no value, no preview
    }

    function clearBand(rec){
      if(rec.band&&rec.band.parentNode===rec.slot)rec.slot.removeChild(rec.band);
      rec.band=null;rec.bandText=null;rec.bandReason=null;
    }

    /* Une génération = au plus UN rapport (le premier fait foi) : `mounted` après la stabilisation, ou la première erreur. */
    function reportOutcome(rec,outcome,reason,message){
      if(rec.outcomeSent)return;
      rec.outcomeSent=true;
      if(outcome==='mounted'){rec.counters.mounted++;totals.mounted++}else{rec.counters.failed++;totals.failed++}
      if(typeof d.onOutcome!=='function')return;
      try{
        d.onOutcome({object_id:rec.objectId,prefab:{id:rec.prefab.id,version:rec.prefab.version},outcome,
          reason:reason||'',message:message||'',generation:rec.generation,counters:Object.assign({},rec.counters)});
      }catch(error){safeLog('scene.prefab_outcome_failed',{object_id:rec.objectId,prefab:rec.key,error:describe(error)})}
    }

    /* `quiet` : l'état est déjà dit EN ENTIER par le cadre lui-même (page de la scène Remotion : raison, détails, « Recharger la scène ») ;
       la bande dupliquerait le message dans une petite fenêtre et lui prendrait la place. Le rapport et les compteurs restent. */
    function fail(rec,message,reason,quiet){
      totals.errors++;
      reportOutcome(rec,'failed',reason||'error',message);
      if(rec.staged){
        const current=frames.get(rec.objectId);
        if(!(rec.claimed&&current&&current.next===rec&&otherScene(current,rec))){
          /* The attempt failed beside a live frame (a new version of the same scene, or a scene loaded ahead): the live frame is untouched,
             no band inside the window. */
          frameLog(rec,'scene.prefab_error',{message,reason:reason||'error',staged:true});
          discardStaged(rec);
          return;
        }
        /* The window was told to show ANOTHER scene and that scene failed (compile, load, timeout): its failure takes the window, named and
           with its retry, instead of the previous scene staying on screen as if nothing happened (Slice 05: never a silent hold or skip). */
        frameLog(rec,'scene.prefab_error',{message,reason:reason||'error',staged:true,shown:true});
        promote(rec);
      }
      if(rec.state!=='paused')rec.state='error';
      clearNote(rec);
      if(!quiet)showBand(rec,message,reason||'error');
      frameLog(rec,'scene.prefab_error',{message,reason:reason||'error'});
    }

    /* Le cadre a quitté son contrat (navigation, second `ready`) : retiré tout
       de suite, sans `teardown` (son document n'est plus le nôtre) ; `find`
       ne le retrouve plus, donc plus rien de lui n'est entendu. */
    function violate(rec,message,reason){
      const iframe=rec.iframe;
      rec.iframe=null;rec.ready=false;
      cancel(rec.readyTimer);cancel(rec.settleTimer);rec.settleTimer=null;cancel(rec.renderTimer);rec.renderTimer=null;
      cancel(rec.resizeTimer);rec.resizeTimer=null;rec.pendingHeight=null;
      if(iframe&&iframe.parentNode)iframe.parentNode.removeChild(iframe);
      fail(rec,message,reason);
    }

    /* ------------------------------------------------------------ cycle de vie */

    function start(rec){
      rec.generation++;
      const generation=rec.generation;
      cancel(rec.readyTimer);cancel(rec.settleTimer);rec.settleTimer=null;cancel(rec.renderTimer);rec.renderTimer=null;cancel(rec.holdTimer);rec.holdTimer=null;
      rec.parked=false;
      if(!rec.staged)clearSlot(rec.slot);
      rec.band=null;rec.note=null;rec.ready=false;rec.bundle=null;rec.events=new Map();
      rec.remotion=false;rec.shellUp=false;
      rec.logs=0;rec.errorsIn=[];rec.outcomeSent=false;
      rec.counters.starts++;totals.starts++;
      const iframe=element('iframe',rec.staged?'sc-prefab-frame sc-prefab-staged':'sc-prefab-frame');
      if(rec.staged)setStagedAttrs(iframe,true);
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
        if(rec.generation!==generation||rec.ready||!owned(rec)||rec.state==='error')return;
        fail(rec,`no ready within ${READY_TIMEOUT_MS/1000} s`,'timeout');
      },READY_TIMEOUT_MS);
      const pending=loadBundle(rec.prefab);
      pending.then((bundle)=>{
        if(rec.generation!==generation||!owned(rec))return;
        if(bundle&&bundle.kind==='remotion'){startRemotion(rec,generation,iframe,bundle);return}
        let srcdoc;
        try{srcdoc=P.buildSrcdoc(bundle)}catch(error){
          forgetBundle(rec.key,pending);
          cancel(rec.readyTimer);fail(rec,describe(error),'bundle');return;
        }
        rec.bundle=bundle;
        rec.events=P.declaredEvents(bundle.manifest);
        /* Écouté juste avant le `srcdoc` : le `load` de l'`about:blank` initial
           est passé. Le premier `load` est le document du prefab ; tout autre
           est une navigation (docs/prefabs.md › *Containment*). */
        let loads=0;
        iframe.addEventListener('load',()=>{
          if(rec.generation!==generation||rec.iframe!==iframe)return;
          if(++loads>1)violate(rec,'the frame navigated away from its document','navigation');
        });
        iframe.srcdoc=srcdoc;
      },(error)=>{
        if(rec.generation!==generation||!owned(rec))return;
        cancel(rec.readyTimer);
        fail(rec,describe(error),'bundle');
      });
    }

    /* Une source Remotion n'a pas de paquet HTML : le cadre est la page de la scène (`/remotion-stage`), qui monte le bac à sable
       isolé, compile à la demande et dit elle-même chaque état (compteur, échec typé, cadre retiré). L'hôte garde le cycle de vie
       (génération, bande d'erreur « Recharger », rapport `onOutcome`, pause, démontage). Jamais de repli HTML. */
    let incarnations=0;
    function startRemotion(rec,generation,old,bundle){
      cancel(rec.readyTimer);
      if(!R){fail(rec,'the Remotion frame module is not loaded','bundle');return}
      rec.remotion=true;rec.shellUp=false;rec.bundle=bundle;rec.events=new Map();
      rec.rendered=false;cancel(rec.renderTimer);rec.renderTimer=null;
      const frame=R.createFrame(doc,rec.prefab,rec.title?`${rec.title} (scène Remotion ${rec.key})`:`Scène Remotion ${rec.key}`,embed);
      if(rec.staged){frame.className+=' sc-prefab-staged';setStagedAttrs(frame,true)}
      if(old&&old.parentNode)old.parentNode.replaceChild(frame,old);
      rec.iframe=frame;
      setNote(rec,'sc-prefab-loading',`Chargement de la scène Remotion ${rec.key}`);
      let loads=0;
      frame.addEventListener('load',()=>{
        if(rec.generation!==generation||rec.iframe!==frame)return;
        if(++loads>1)violate(rec,'the Remotion stage navigated away from its document','navigation');
      });
      rec.readyTimer=later(()=>{
        if(rec.generation!==generation||rec.ready||!owned(rec)||rec.state==='error')return;
        fail(rec,`the Remotion scene did not become ready within ${REMOTION_READY_TIMEOUT_MS/1000} s`,'timeout');
      },REMOTION_READY_TIMEOUT_MS);
    }

    function setStagedAttrs(frame,on){
      try{
        if(on){frame.setAttribute('aria-hidden','true');frame.inert=true}
        else{if(typeof frame.removeAttribute==='function')frame.removeAttribute('aria-hidden');frame.inert=false}
      }catch(_error){/* intentional: a DOM without `inert` still gets the class; focus is a courtesy, never the swap */}
    }

    function notifyLive(rec){
      if(typeof d.onLive!=='function')return;
      try{d.onLive(rec.objectId)}catch(error){safeLog('scene.prefab_live_hook_failed',{object_id:rec.objectId,error:describe(error)})}
    }

    /* The Player is paused on frame 0 until something orders it. If nothing does within the grace period (a scene the score does not drive:
       a hot reload, a window opened outside a run), it plays on its own, as a Remotion scene always did. */
    function hold(rec){
      if(!autoplay)return;
      const generation=rec.generation;
      cancel(rec.holdTimer);
      rec.holdTimer=later(()=>{
        rec.holdTimer=null;
        if(rec.generation!==generation||frames.get(rec.objectId)!==rec||rec.ordered||!rec.ready||rec.staged||!rec.iframe)return;
        post(rec,R.hostMessage('control',{action:'play'}));
      },HOLD_GRACE_MS);
    }

    function sendSound(rec){
      if(soundMuted===null||!rec.remotion||!rec.ready||rec.staged||frames.get(rec.objectId)!==rec)return false;
      return post(rec,R.hostMessage('sound',{muted:soundMuted}));
    }
    function liveHook(rec,name,value){
      if(rec.staged||frames.get(rec.objectId)!==rec||typeof d[name]!=='function')return;
      try{d[name](rec.objectId,value)}catch(error){safeLog('scene.prefab_hook_failed',{object_id:rec.objectId,hook:name,error:describe(error)})}
    }
    function onRemotionStatus(rec,event){
      const view=rec.iframe;
      const origin=win.location&&win.location.origin;
      const type=event&&event.data&&event.data.type;
      if(type==='audio'){   /* the real state of the sound in the Player (Slice 08): `blocked` when the browser refused it */
        const parsed=R.parseAudio(event,view,origin);
        if(!parsed.ok){drop(rec,parsed.reason);return}
        rec.audio=parsed.audio;
        liveHook(rec,'onSound',Object.assign({},parsed.audio));
        return;
      }
      if(type==='key'){     /* a § 4.15 key typed in the scene that has the focus (Slice 08): the page's transport acts on it, once */
        const parsed=R.parseKey(event,view,origin);
        if(!parsed.ok){drop(rec,parsed.reason);return}
        liveHook(rec,'onKey',parsed.key);
        return;
      }
      if(event&&event.data&&event.data.type==='clock'){   /* position du lecteur (Slice 12) : gardée, bornée, jamais envoyée à Core */
        const clock=R.parseClock(event,view,origin);
        if(!clock.ok){drop(rec,clock.reason);return}
        rec.clock=Object.assign({at:now()},clock.clock);
        if(!rec.staged&&typeof d.onClock==='function'&&frames.get(rec.objectId)===rec){
          try{d.onClock(rec.objectId)}catch(error){safeLog('scene.prefab_clock_hook_failed',{object_id:rec.objectId,error:describe(error)})}
        }
        if(!rec.rendered){   // the first clock: the Player committed its first render (a render error would have come first)
          rec.rendered=true;cancel(rec.renderTimer);rec.renderTimer=null;
          if(rec.state==='ready')settle(rec);
        }
        return;
      }
      const parsed=R.parseStatus(event,view,origin);
      if(!parsed.ok){drop(rec,parsed.reason);return}
      const status=parsed.status;
      switch(status.phase){
        case 'shell':
          rec.shellUp=true;
          post(rec,R.hostMessage('props',{props:rec.props,data:rec.data}));   // the values the stage window shows now
          break;
        case 'mounting':
          if(status.composition)fitComposition(rec,status.composition);
          break;
        case 'ready':
          cancel(rec.readyTimer);
          if(status.composition)fitComposition(rec,status.composition);
          rec.incarnation=++incarnations;
          rec.clock=null;rec.ordered=false;
          rec.ready=true;
          /* Starts paused on the first frame: the timeline (or the grace period) decides what it plays, nothing replays after a mount. */
          post(rec,R.hostMessage('control',{action:'pause',frame:0}));
          if(!rec.staged){sendSound(rec);hold(rec);notifyLive(rec)}
          clearNote(rec);
          if(rec.bandReason==='timeout'||rec.state==='error'){clearBand(rec)}
          rec.state='ready';
          if(rec.rendered)settle(rec);
          else{
            const generation=rec.generation;
            cancel(rec.renderTimer);
            rec.renderTimer=later(()=>{
              rec.renderTimer=null;
              if(!owned(rec)||rec.generation!==generation||rec.rendered||rec.outcomeSent)return;
              fail(rec,`the scene did not render a first frame within ${RENDER_PROOF_MS/1000} s`,'timeout');
            },RENDER_PROOF_MS);
          }
          break;
        case 'failed':case 'killed':
          cancel(rec.readyTimer);
          fail(rec,status.message||status.title||status.phase,status.phase==='killed'?'killed':(status.reason||'failed'),true);
          break;
        case 'notice':          // Slice 13 : refused values — a transient warning, never fail() and never an outcome for Core
          setNotice(rec,status.message||'');
          break;
        case 'scene_error':
          if(withinRate(rec,rec.errorsIn,ERROR_RATE))fail(rec,status.message||'scene error','frame');
          break;
        default:break;   // 'preparing': the stage shows its own live counter
      }
    }

    function fitComposition(rec,composition){
      const frame=rec.iframe;
      if(!frame||!frame.style)return;
      frame.style.height='auto';
      frame.style.aspectRatio=`${composition.width} / ${composition.height}`;
      if(typeof frame.getBoundingClientRect==='function'){
        const box=frame.getBoundingClientRect();
        /* The window takes the height the composition needs at its current width (never the height a cramped window left it). */
        const height=box.width>0?Math.round(box.width*composition.height/composition.width):Math.round(box.height);
        if(height>0&&!rec.staged){
          rec.height=height;
          try{if(typeof d.onResize==='function')d.onResize(rec.objectId,height)}catch(_error){/* intentional: layout hint only */}
        }
      }
    }

    function departure(rec){
      const iframe=rec.iframe;
      rec.iframe=null;
      cancel(rec.readyTimer);cancel(rec.settleTimer);rec.settleTimer=null;cancel(rec.renderTimer);rec.renderTimer=null;cancel(rec.holdTimer);rec.holdTimer=null;
      cancel(rec.resizeTimer);rec.resizeTimer=null;rec.pendingHeight=null;
      if(!iframe)return;
      if(rec.ready)post(rec,rec.remotion?R.hostMessage('teardown'):P.hostMessage('teardown'),iframe);
      rec.ready=false;
      departing.add(iframe);
      later(()=>{
        departing.delete(iframe);
        if(iframe.parentNode)iframe.parentNode.removeChild(iframe);
      },TEARDOWN_MS);
    }

    /* Le cadre préparé à côté est abandonné (échec, nouveau pin, retour au pin vivant) : jamais promu, jamais vu. */
    function discardStaged(rec){
      const current=frames.get(rec.objectId);
      if(current&&current.next===rec)current.next=null;
      rec.generation++;
      departure(rec);
      rec.state='removed';
    }

    function dropNext(rec){
      if(rec.next)discardStaged(rec.next);
    }

    /* Le cadre préparé est monté : il prend la place du vivant. L'ancien est caché AU MÊME INSTANT (il garde
       `TEARDOWN_MS` pour son `teardown`), donc la fenêtre ne grandit pas d'un cadre entre deux versions. */
    function promote(next){
      const current=frames.get(next.objectId);
      if(!current||current.next!==next)return false;
      current.next=null;
      next.staged=false;
      next.counters.remounts++;
      next.lastDraw=now();
      if(next.iframe&&next.iframe.classList){next.iframe.classList.remove('sc-prefab-staged');setStagedAttrs(next.iframe,false)}
      const old=current.iframe;
      if(old&&old.style){old.style.position='absolute';old.style.visibility='hidden'}
      frames.set(next.objectId,next);
      current.generation++;
      departure(current);
      clearNote(current);clearBand(current);
      current.state='removed';
      try{if(next.height&&typeof d.onResize==='function')d.onResize(next.objectId,next.height)}catch(_error){/* intentional: layout hint only */}
      safeLog('scene.prefab_swapped',{object_id:next.objectId,prefab:next.key,mode});
      if(next.remotion){sendSound(next);hold(next);notifyLive(next)}   // the Player that waited paused on frame 0 behind the live one takes its orders now
      /* The scene asked to be loaded ahead while this one was still waiting (Slice 05): it starts now, beside the frame just shown. */
      const queued=current.queued;current.queued=null;
      if(queued&&!next.next&&next.state==='ready'&&`${queued.prefab.id}@${queued.prefab.version}`!==next.key){
        stageAhead(next,next.objectId,queued.prefab,`${queued.prefab.id}@${queued.prefab.version}`,queued);
      }
      return true;
    }

    /* The staged frame replaces the live one (settled by itself, or taken by the `mount` of the scene it was preloaded for). */
    function takeOver(rec){
      if(!owned(rec)||rec.state!=='ready'||rec.outcomeSent||!rec.staged)return;
      if(!promote(rec))return;
      reportOutcome(rec,'mounted','','');
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
      let counters=null;
      if(existing){
        if(existing.key===key&&existing.slot===slot){
          dropNext(existing);   // the pin is back to the live frame's version (rollback): the attempt beside it is abandoned
          existing.title=instance.title||existing.title;
          touch(objectId);
          update(objectId,instance.props,instance.data,instance.theme);
          return false;
        }
        if(existing.next&&existing.next.key===key&&existing.next.slot===slot){
          const waiting=existing.next;
          waiting.title=instance.title||waiting.title;
          waiting.claimed=true;
          /* Another scene: the values are the INCOMING scene's, only its frame gets them. Pushed into the outgoing Player too, the screen showed
             the last frame of scene k with the title and colours of scene k+1 until the swap (native-studio-playback-fix Slice 03, "hybrid
             frame"). A new version of the same scene (hot reload) keeps both frames current (`update`). */
          const changed=update(objectId,instance.props,instance.data,instance.theme);
          if(waiting.preload){
            /* The scene that was loaded ahead is now the one the window must show: no new load, it takes the place as soon as it is settled
               (and, when its values moved, once it has rendered them). */
            waiting.preload=false;
            if(waiting.parked){waiting.parked=false;later(()=>takeOver(waiting),changed?PROPS_SETTLE_MS:0)}
          }
          return false;
        }
        if(swapPrefix&&prefab.id.startsWith(swapPrefix)&&existing.slot===slot&&existing.state==='ready'){
          dropNext(existing);
          if(slot.classList)slot.classList.add('sc-prefab-slot');
          const staged=makeRec(objectId,prefab,key,slot,instance,existing.counters);
          staged.staged=true;staged.claimed=true;
          existing.next=staged;
          start(staged);
          safeLog('scene.prefab_mounted',{object_id:objectId,prefab:key,mode,staged:true});
          return true;
        }
        counters=existing.counters;
        counters.remounts++;   // la même fenêtre change de version (ou de conteneur) : le compteur de l'objet continue
        unmount(objectId);
      }
      if(slot.classList)slot.classList.add('sc-prefab-slot');
      const rec=makeRec(objectId,prefab,key,slot,instance,counters);
      frames.set(objectId,rec);
      evictFor(rec);
      start(rec);
      safeLog('scene.prefab_mounted',{object_id:objectId,prefab:key,mode});
      return true;
    }

    /* Charge à côté la scène qui suit (Slice 23). Sans effet (`false`) : fenêtre absente ou pas prête, autre espace que `swapPrefix`, même
       version que le cadre vivant, ou déjà en préparation.
       Never drops the frame already prepared beside the live one (native-studio-playback-fix Slice 05). That frame is either the scene
       the window has been told to show (`claimed`, its takeover deferred until it has settled) or a scene loaded ahead that the window has
       not reached yet. Dropping it lost the scene: the window then waited on a frame that no longer existed and Core skipped the scene
       (Slice 03, defect A: `preload` -> `dropNext`). The new preload is queued instead, the latest one wins, and it starts the moment the
       prepared frame takes the window (`promote`). A queued preload is an effect: `true`. */
    function preload(objectId,instance){
      checkInstance(instance);
      const existing=frames.get(objectId);
      const prefab={id:instance.prefab.id,version:instance.prefab.version};
      const key=`${prefab.id}@${prefab.version}`;
      if(!existing||existing.state!=='ready'||!swapPrefix||!prefab.id.startsWith(swapPrefix)||existing.key===key)return false;
      if(existing.next&&existing.next.key===key)return false;
      if(existing.next){
        existing.queued=Object.assign({},instance,{prefab});
        safeLog('scene.prefab_preload_queued',{object_id:objectId,prefab:key,behind:existing.next.key,mode});
        return true;
      }
      return stageAhead(existing,objectId,prefab,key,instance);
    }

    function stageAhead(existing,objectId,prefab,key,instance){
      existing.queued=null;
      const staged=makeRec(objectId,prefab,key,existing.slot,instance,existing.counters);
      staged.staged=true;staged.preload=true;staged.ahead=true;
      existing.next=staged;
      start(staged);
      safeLog('scene.prefab_preloaded',{object_id:objectId,prefab:key,mode});
      return true;
    }

    function makeRec(objectId,prefab,key,slot,instance,counters){
      const rec={objectId,prefab,key,slot,title:typeof instance.title==='string'?instance.title:'',
        props:P.cloneJson(instance.props||{}),data:P.cloneJson(instance.data||{}),
        theme:Object.assign({},baseTheme,instance.theme||{}),state:'loading',generation:0,lastDraw:now(),
        outputs:[],errorsIn:[],dropped:0,rateLimited:0,height:0,pendingHeight:null,resizeTimer:null,sentData:null,
        iframe:null,readyTimer:null,renderTimer:null,rendered:false,logs:0,outcomeSent:false,settleTimer:null,holdTimer:null,staged:false,preload:false,parked:false,ordered:false,claimed:false,queued:null,ahead:false,next:null,sceneId:typeof instance.scene_id==='string'&&instance.scene_id?instance.scene_id:null,
        counters:counters||{starts:0,mounted:0,failed:0,remounts:0}};
      rec.propsJson=json(rec.props);rec.dataJson=json(rec.data);rec.themeJson=json(rec.theme);
      return rec;
    }

    /* Is the frame prepared beside `live` ANOTHER scene (not a new version of the same one, a hot reload)? A frame loaded ahead always is;
       otherwise the callers say it with `scene_id` (Variants, the run stage preload). Without it, a new pin is treated as a hot reload. */
    function otherScene(live,next){
      return next.ahead||(!!live.sceneId&&!!next.sceneId&&live.sceneId!==next.sceneId);
    }

    function update(objectId,props,data,theme){
      const rec=frames.get(objectId);
      if(!rec)return false;
      /* The window has been told to show ANOTHER scene, prepared beside the live one: values sent now are that scene's, never the outgoing
         Player's (Slice 05, hybrid frame). A new version of the same scene (hot reload) still keeps both frames current. */
      if(rec.next&&rec.next.claimed&&otherScene(rec,rec.next))return applyUpdate(rec.next,props,data,theme);
      const changed=applyUpdate(rec,props,data,theme);
      if(rec.next)applyUpdate(rec.next,props,data,theme);   // the frame prepared beside it must start from the latest values
      return changed;
    }

    function applyUpdate(rec,props,data,theme){
      const nextTheme=Object.assign({},baseTheme,theme||{});
      const texts={props:json(props||{}),data:json(data||{}),theme:json(nextTheme)};
      if(texts.props===rec.propsJson&&texts.data===rec.dataJson&&texts.theme===rec.themeJson)return false;
      rec.props=JSON.parse(texts.props);rec.data=JSON.parse(texts.data);rec.theme=nextTheme;
      rec.propsJson=texts.props;rec.dataJson=texts.data;rec.themeJson=texts.theme;
      if(rec.remotion){if(rec.shellUp)post(rec,R.hostMessage('props',{props:rec.props,data:rec.data}));return true}
      if(rec.ready&&post(rec,P.hostMessage('update',hostFields(rec))))rec.sentData=P.cloneJson(rec.data);
      return true;
    }

    function unmount(objectId){
      const rec=frames.get(objectId);
      if(!rec)return false;
      dropNext(rec);
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
      dropNext(rec);
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
      dropNext(rec);
      departure(rec);
      rec.lastDraw=now();
      if(rec.state==='paused')evictFor(rec);
      start(rec);
      return true;
    }

    /* ------------------------------------------------------------ messages */

    function find(source){
      if(!source)return null;
      for(const rec of frames.values()){
        if(rec.iframe&&rec.iframe.contentWindow===source)return rec;
        if(rec.next&&rec.next.iframe&&rec.next.iframe.contentWindow===source)return rec.next;
      }
      return null;
    }

    function drop(rec,reason){
      totals.dropped++;rec.dropped++;
      frameLog(rec,'scene.prefab_message_dropped',{reason,dropped:rec.dropped});
    }

    /* Fenêtre glissante d'une seconde : `list` garde les instants acceptés. */
    function withinRate(rec,list,limit){
      const t=now();
      while(list.length&&t-list[0]>=RATE_WINDOW_MS)list.shift();
      if(list.length>=limit){
        totals.rateLimited++;rec.rateLimited++;
        if(rec.rateLimited===1||rec.rateLimited%50===0){
          safeLog('scene.prefab_event_rate_limited',{object_id:rec.objectId,prefab:rec.key,rate_limited:rec.rateLimited});
        }
        return false;
      }
      list.push(t);
      return true;
    }

    function allowOutput(rec){return withinRate(rec,rec.outputs,OUTPUT_RATE)}

    /* Premier `resize` appliqué tout de suite, les suivants regroupés : un seul
       par tranche de `RESIZE_COALESCE_MS`, avec la dernière hauteur reçue. */
    function onResize(rec,height){
      rec.pendingHeight=height;
      if(rec.resizeTimer)return;
      applyHeight(rec);
      rec.resizeTimer=later(()=>{
        rec.resizeTimer=null;
        if(owned(rec))applyHeight(rec);
      },RESIZE_COALESCE_MS);
    }

    function applyHeight(rec){
      const height=rec.pendingHeight;
      rec.pendingHeight=null;
      if(height===null)return;
      rec.height=height;
      if(rec.iframe)rec.iframe.style.height=`${height}px`;
      if(rec.staged)return;   // a frame prepared beside the live one does not move the window until it replaces it
      try{if(typeof d.onResize==='function')d.onResize(rec.objectId,height)}catch(_error){/* intentional: layout hint only */}
    }

    /* Issue d'un événement dite au cadre qui l'a émis, s'il est encore là (même génération, prêt). */
    function tell(rec,generation,name,outcome,reason){
      if(!owned(rec)||rec.generation!==generation||!rec.ready)return;
      post(rec,P.hostMessage('event_result',{name,outcome,reason}));
    }

    function reasonOf(error){
      const code=error&&typeof error.code==='string'?error.code:'';
      return /^[a-z][a-z0-9_]{0,39}$/.test(code)?code:'unreachable';
    }

    function onEvent(rec,message){
      if(!rec.ready){drop(rec,'event before ready');return}
      if(rec.staged){drop(rec,'event before the frame replaced the live one');return}
      const generation=rec.generation;
      const decl=rec.events.get(message.name);
      if(!decl){
        drop(rec,`undeclared event ${message.name}`);
        tell(rec,generation,message.name,'refused','undeclared_event');
        return;
      }
      if(decl.class!=='state'&&P.jsonBytes(message.payload)>P.MAX_NOTIFY_PAYLOAD_BYTES){
        drop(rec,'notify payload too large');
        tell(rec,generation,message.name,'refused','too_large');
        return;
      }
      if(!allowOutput(rec)){tell(rec,generation,message.name,'refused','rate_limited');return}
      const basis={};
      if(decl.class==='state'){
        const sent=rec.sentData||{};
        for(const key of Object.keys(message.payload)){
          basis[key]=Object.prototype.hasOwnProperty.call(sent,key)?P.cloneJson(sent[key]):null;
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
        const known=result&&P.EVENT_OUTCOMES.includes(result.outcome)&&result.outcome!=='failed';
        const outcome=known?result.outcome:'failed';
        const reason=known?(typeof result.reason==='string'?result.reason:undefined):'invalid_response';
        if(outcome!=='applied'&&outcome!=='recorded'){
          frameLog(rec,'scene.prefab_event_failed',{event:message.name,outcome,reason:reason||null});
        }
        tell(rec,generation,message.name,outcome,reason);
        /* `stale` : la basis du cadre était en retard sur Core. Le cadre reçoit
           aussitôt l'état connu de la page, forcé ; le flux de scène apportera
           ensuite tout changement plus récent par `update`. */
        if(outcome==='stale'&&rec.generation===generation)resync(rec,true);
      },(error)=>{
        frameLog(rec,'scene.prefab_event_failed',{event:message.name,error:describe(error).slice(0,300)});
        tell(rec,generation,message.name,'failed',reasonOf(error));
      });
    }

    /* Renvoie `update` avec l'état connu de la page. `force` : le cadre le passe
       au comportement même s'il est identique au dernier reçu (A4). */
    function resync(rec,force){
      if(!owned(rec)||!rec.ready)return false;
      const fields=hostFields(rec);
      if(force)fields.force=true;
      if(post(rec,P.hostMessage('update',fields)))rec.sentData=P.cloneJson(rec.data);
      return true;
    }

    function openUrl(rec,url){
      if(rec.staged){drop(rec,'open_url before the frame replaced the live one');return}
      if(!allowOutput(rec))return;
      try{
        if(typeof d.openUrl==='function')d.openUrl(url);
        else if(typeof win.open==='function')win.open(url,'_blank','noopener,noreferrer');
      }catch(error){frameLog(rec,'scene.prefab_error',{message:`open_url failed: ${describe(error)}`,reason:'open_url'})}
    }

    function onMessage(event){
      const rec=find(event&&event.source);
      if(!rec)return;  // not one of our frames (another iframe of the page): not ours to judge
      if(rec.remotion){onRemotionStatus(rec,event);return}
      if(event.origin!=='null'){drop(rec,'origin is not opaque');return}
      const parsed=P.parseFrameMessage(event.data);
      if(!parsed.ok){drop(rec,parsed.reason);return}
      const message=parsed.message;
      switch(message.type){
        case 'ready':
          if(rec.ready){violate(rec,'second ready (the frame reloaded or navigated)','protocol');break}
          cancel(rec.readyTimer);
          rec.ready=true;
          clearNote(rec);
          if(rec.state==='loading')rec.state='ready';
          if(rec.bandReason==='timeout'){clearBand(rec);rec.state='ready'}
          sendInit(rec);
          settle(rec);
          break;
        case 'resize':onResize(rec,message.height);break;
        case 'event':onEvent(rec,message);break;
        case 'open_url':openUrl(rec,message.url);break;
        case 'error':if(withinRate(rec,rec.errorsIn,ERROR_RATE))fail(rec,message.message,'frame');break;
      }
    }

    /* `mounted` seulement si le cadre est resté prêt et sans erreur pendant `SETTLE_MS` après son `init` : l'erreur d'un
       premier rendu arrive après `ready`, et un cadre qui l'a levée n'est pas monté (Slice 06). */
    function settle(rec){
      const generation=rec.generation;
      cancel(rec.settleTimer);
      rec.settleTimer=later(()=>{
        rec.settleTimer=null;
        if(!owned(rec)||rec.generation!==generation||rec.state!=='ready'||rec.outcomeSent)return;
        if(rec.staged&&rec.preload){rec.parked=true;return}   // loaded ahead: waits, paused on frame 0, for the scene it belongs to
        if(rec.staged&&!promote(rec))return;   // replaces the live frame first: "mounted" means "on screen"
        reportOutcome(rec,'mounted','','');
      },SETTLE_MS);
    }

    /* Ordres de lecture d'une scène Remotion (play, pause, seek) et repères (cue) : sans effet, `false`, sur un autre prefab. */
    function control(objectId,action,frame,until){
      const rec=frames.get(objectId);
      if(!rec||!rec.remotion||!rec.ready)return false;
      const fields={action};
      if(Number.isInteger(frame))fields.frame=frame;
      if(action==='play'&&Number.isInteger(until))fields.until=until;
      rec.clock=null;rec.ordered=true;   // the old position no longer describes the player we just ordered; the hold period is over
      return post(rec,R.hostMessage('control',fields));
    }

    /* Dernière position rapportée par le lecteur (`{frame, playing, duration, fps, at}`), ou `null` : conseil pour la ligne de temps. */
    /* The incarnation of the Player behind a Remotion window: a number that is new every time the stage page says `ready` (first mount,
       staged hot-reload swap, "Recharger la scène", watchdog restart). The timeline follower watches it: a new Player knows nothing of the
       order its predecessor was given. `null` before the first `ready`. */
    function frame(objectId){
      const rec=frames.get(objectId);
      return rec&&rec.remotion&&rec.incarnation?rec.incarnation:null;
    }

    function clock(objectId){
      const rec=frames.get(objectId);
      return rec&&rec.remotion&&rec.clock?Object.assign({},rec.clock):null;
    }

    function cue(objectId,name,frame){
      const rec=frames.get(objectId);
      if(!rec||!rec.remotion||!rec.ready)return false;
      return post(rec,R.hostMessage('cue',{name,frame}));
    }

    /* The sound the page wants for its Remotion Players (Slice 08): sent at once to every live Remotion frame, kept for the next ones. */
    function sound(muted){
      if(typeof muted!=='boolean')throw new TypeError('sound: muted must be a boolean');
      soundMuted=muted;
      let sent=0;
      for(const rec of frames.values())if(sendSound(rec))sent++;
      return sent;
    }

    function stats(){
      let paused=0,ready=0,errors=0,loading=0,staging=0;
      for(const rec of frames.values()){
        if(rec.next)staging++;
        if(rec.state==='paused')paused++;
        else if(rec.state==='ready')ready++;
        else if(rec.state==='error')errors++;
        else if(rec.state==='loading')loading++;
      }
      return Object.assign({frames:frames.size,live:liveCount(),ready,loading,errorFrames:errors,paused,staging,
        listening,bundles:bundles.size,departing:departing.size},totals);
    }

    function destroy(){
      for(const objectId of Array.from(frames.keys()))unmount(objectId);
    }

    return Object.freeze({mount,preload,update,unmount,pause,resume,touch,reload,stats,destroy,control,cue,clock,frame,sound,
      soundWanted:()=>soundMuted===null?null:!soundMuted,
      audio:(objectId)=>{const rec=frames.get(objectId);return rec&&rec.audio?Object.assign({},rec.audio):null},
      has:(objectId)=>frames.has(objectId),
      counters:(objectId)=>{const rec=frames.get(objectId);return rec?Object.assign({},rec.counters):null},
      parked:(objectId)=>{const rec=frames.get(objectId);return !!(rec&&rec.next&&rec.next.parked)},
      pendingKey:(objectId)=>{const rec=frames.get(objectId);return rec&&rec.next?rec.next.key:null},
      key:(objectId)=>{const rec=frames.get(objectId);return rec?rec.key:null},
      height:(objectId)=>{const rec=frames.get(objectId);return rec?rec.height:0},
      state:(objectId)=>{const rec=frames.get(objectId);return rec?rec.state:null}});
  }

  /* ------------------------------------------------------------ pont avec la scène (Slice 04)

     Ce que la page de scène (`control_center_scene_page.js`) fait pour une
     fenêtre prefab, ici pour être exécuté par node avec le faux DOM :
     - `sceneSlot(el, create)` : le conteneur du cadre, enfant direct du nœud ;
     - `clearAround(el, slot)` : vide le nœud SAUF le conteneur — un iframe
       détaché du document recharge son document, il ne l'est donc jamais ;
     - `placeAround(el, slot, before, after)` : tête et titre avant, poignée après ;
     - `syncScene(host, record, el, node)` : monte (nouvel objet, autre
       `id@version`, autre conteneur), met à jour (`props`/`data` par message,
       diff dans l'hôte) ou démonte (forme dessinée autre que `window`, bloc
       retiré). `record` est la mémoire de la page pour ce nœud
       (`prefabKey`, `prefabSlot`). Rend `mount` | `update` | `unmount` | `none`. */
  const SLOT_CLASS='sc-prefab-slot';

  function sceneSlot(el,create){
    for(const child of Array.from(el.children||[]))if(child.classList&&child.classList.contains(SLOT_CLASS))return child;
    if(!create)return null;
    const slot=(el.ownerDocument||root.document).createElement('div');
    slot.className=SLOT_CLASS;
    el.appendChild(slot);
    return slot;
  }

  function clearAround(el,slot){
    for(const child of Array.from(el.childNodes||[]))if(child!==slot)el.removeChild(child);
  }

  function placeAround(el,slot,before,after){
    for(const node of before||[])el.insertBefore(node,slot);
    for(const node of after||[])el.appendChild(node);
  }

  function syncScene(host,record,el,node){
    const id=node.id;
    const wanted=!!(node.prefab&&node.shape==='window');
    if(!wanted){
      const had=host.has(id);
      if(had)host.unmount(id);
      record.prefabKey='';record.prefabSlot=null;
      return had?'unmount':'none';
    }
    const slot=sceneSlot(el,true);
    const prefab=node.prefab;
    if(!host.has(id)||record.prefabKey!==node.prefabKey||record.prefabSlot!==slot){
      host.mount(slot,{object_id:id,prefab:{id:prefab.id,version:prefab.version},title:node.title,
        props:prefab.props,data:prefab.data});
      record.prefabKey=node.prefabKey;record.prefabSlot=slot;
      return 'mount';
    }
    /* Dessiné : le cadre vivant devient le plus récent (LRU). Un cadre en pause
       ne reprend que si l'utilisateur sélectionne sa fenêtre (`touch` de la page). */
    if(host.state(id)!=='paused')host.touch(id);
    return host.update(id,prefab.props,prefab.data)?'update':'none';
  }

  const api=Object.freeze({LIVE_CAP,SETTLE_MS,HOLD_GRACE_MS,PROPS_SETTLE_MS,READY_TIMEOUT_MS,TEARDOWN_MS,OUTPUT_RATE,ERROR_RATE,RESIZE_COALESCE_MS,BUNDLE_CACHE_CAP,
    DEFAULT_THEME,SLOT_CLASS,createPrefabHost,bundleFetcher,sceneSlot,clearAround,placeAround,syncScene});
  root.JarvisPrefabHost=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
