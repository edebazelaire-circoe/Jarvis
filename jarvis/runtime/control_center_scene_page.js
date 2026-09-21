/* Scène constellation dans le Control Center : boucle de lecture, validation
   des placements du résolveur et rendu (handoff
   jarvis-constellation-scene-runtime, Slice 05).

   Deux parties, comme `control_center_barehands.js` :
   - `JarvisScenePageCore`, logique pure à dépendances injectées (requêtes,
     minuteries, horloge, hasard, diffusion) : machine d'états de la boucle
     (meneur, suiveur, seul) et validation « une fois par objet » des
     placements du résolveur. Les tests l'exécutent avec node et de fausses
     minuteries ;
   - un bloc navigateur : conteneur de scène, relations SVG, nœuds DOM, verrou
     et canal entre onglets, interrupteur `scene.enabled`, et (Slice 08) les
     gestes de l'utilisateur — sélection, glisser, redimensionner, clavier,
     menu contextuel, confirmations en page, masqués, archivage, arrêt d'un
     job — dont la logique pure vit dans `control_center_scene_interact.js`.
     Les tests node ne l'exécutent pas.

   Éteint (`scene.enabled` faux, lu dans `/api/status`), rien n'est créé dans
   la page et aucune requête de scène ne part. */

const JarvisScenePageCore=(function(){
  'use strict';
  /* Attente demandée au Control Center (il la borne lui-même à 25 s). */
  const LONG_POLL_WAIT_S=25;
  const SNAPSHOT_TIMEOUT_MS=15000;
  /* Attente + marge du relais (5 s) + marge réseau : au-delà, abandon et
     nouvel essai, jamais d'attente infinie. */
  const POLL_TIMEOUT_MS=(LONG_POLL_WAIT_S+15)*1000;
  const BACKOFF_BASE_MS=1000;
  const BACKOFF_MAX_MS=30000;
  /* Un suiveur sans nouvelle du meneur depuis 35 s relit les patchs manqués
     (une lecture courte) : le meneur annonce sa révision au moins toutes les
     25 s. Vérifié toutes les 5 s, d'où un retard borné à environ 40 s derrière
     un meneur bloqué ; au plus une lecture par période de silence de 35 s. */
  const FOLLOWER_SILENCE_MS=35000;
  const FOLLOWER_CHECK_MS=5000;
  /* `retryNow` (le Control Center répond de nouveau) au plus une fois par
     intervalle. */
  const RETRY_NOW_MIN_MS=2000;
  const MESSAGE_VERSION=1;

  /* Délai avant le n-ième nouvel essai : 1 s, 2 s, 4 s… plafonné à 30 s, à
     ±25 % au hasard pour que plusieurs onglets ne repartent pas ensemble. */
  function backoffDelay(failures,random){
    const base=Math.min(BACKOFF_MAX_MS,BACKOFF_BASE_MS*Math.pow(2,Math.max(0,failures-1)));
    const r=typeof random==='function'?random():.5;
    return Math.round(base*(.75+.5*Math.min(1,Math.max(0,r))));
  }

  function patchPath(query){
    return '/api/scene/patches?'+new URLSearchParams({scene_id:query.scene_id,epoch:query.epoch,
      after:String(query.after),wait_s:String(query.wait_s)}).toString();
  }

  /* L'interrupteur tel que `/api/status` le donne (`{enabled, source}`). */
  function gateEnabled(scene){return !!scene&&scene.enabled===true}

  /* Message du canal entre onglets : forme attendue, sinon ignoré. */
  function validMessage(msg){
    if(!msg||typeof msg!=='object'||msg.v!==MESSAGE_VERSION)return false;
    if(msg.type==='patches')return typeof msg.scene_id==='string'&&typeof msg.epoch==='string'&&!!msg.body&&typeof msg.body==='object';
    if(msg.type==='tick')return typeof msg.scene_id==='string'&&typeof msg.epoch==='string'&&Number.isSafeInteger(msg.revision)&&!!msg.health&&typeof msg.health==='object';
    if(msg.type==='health')return !!msg.health&&typeof msg.health==='object';
    return false;
  }

  const errorCode=error=>String(error&&(error.code||error.name)||'network_error');
  /* Réponse de patchs diffusée aux suiveurs : sans la demande de capture (Slice 09). */
  function withoutCapture(body){
    if(!body||!Object.prototype.hasOwnProperty.call(body,'capture_request'))return body;
    const copy={...body};delete copy.capture_request;return copy;
  }

  /* Meneur du profil par un verrou Web Locks (`locks`, API de `navigator.locks`).
     `decide()` rend une promesse résolue quand le rôle est connu : meneur si le
     verrou est libre, sinon suiveur en file d'attente (le navigateur passe le
     verrou dès qu'il est rendu). Un verrou accordé alors que l'onglet est
     caché ou la scène éteinte est rendu aussitôt : l'onglet reste suiveur.
     `onRole(role)` reçoit `leader` ou `follower`. */
  function createLeadership(deps){
    const state={held:false,release:null,abort:null};
    const log=(level,event,data)=>{if(deps.log)deps.log(level,event,data||{})};
    function hold(){
      if(!deps.isVisible()||!deps.isEnabled()){
        state.abort=null;
        log('info','scene.leader_declined',{visible:deps.isVisible(),enabled:deps.isEnabled()});
        deps.onRole('follower');
        return Promise.resolve();
      }
      return new Promise(release=>{
        state.abort=null;state.held=true;state.release=release;
        deps.onRole('leader');
      });
    }
    function queue(){
      const controller=deps.createAbort();
      state.abort=controller;
      deps.locks.request(deps.name,{signal:controller.signal},()=>hold()).catch(error=>{
        if(error&&error.name==='AbortError')return;
        if(state.abort===controller)state.abort=null;
        log('warn','scene.leader_lock_failed',{error:errorMessage(error)});
      });
    }
    return {
      decide(){
        if(state.held||state.abort)return Promise.resolve();
        return new Promise(resolve=>{
          deps.locks.request(deps.name,{ifAvailable:true},lock=>{
            if(lock){const held=hold();resolve();return held}
            deps.onRole('follower');queue();resolve();
            return undefined;
          }).catch(error=>{log('warn','scene.leader_lock_failed',{error:errorMessage(error)});resolve()});
        });
      },
      release(){
        if(state.abort){const pending=state.abort;state.abort=null;pending.abort()}
        if(state.release){const release=state.release;state.release=null;release()}
        state.held=false;
      },
      held:()=>state.held,
      queued:()=>!!state.abort,
    };
  }
  const errorMessage=error=>String(error&&error.message||'');

  /* Boucle d'une page. Rôles :
     - `leader` : l'onglet qui tient le verrou du profil ; seul à tenir le
       long-poll, il diffuse chaque réponse de patchs appliquée, sa révision
       (`tick`) et son état de lecture ;
     - `follower` : aucune requête longue ; applique les patchs diffusés par
       `JarvisSceneClient`, et ne lit Core que par des lectures courtes :
       instantané au premier chargement ou à la resynchronisation, patchs
       manqués (`wait_s=0`) sur un trou, un `tick` en avance ou un meneur muet
       depuis 45 s ;
     - `solo` : sans verrou ni canal (navigateur ancien), long-poll par onglet.

     Phases : `off` (interrupteur éteint), `paused` (onglet caché), `loading`
     (instantané), `polling` (long-poll), `following` (suiveur à jour, aucune
     requête), `catching_up` (lecture courte des patchs manqués), `waiting`
     (délai avant nouvel essai), `stopped` (page quittée). `deps` : `client`,
     `request(path, {signal, timeoutMs})` → corps JSON (rejette sur échec
     réseau ou HTTP), `setTimeout`, `clearTimeout`, `now`, `random`,
     `createAbort`, `onUpdate(vue)`, `log(level, event, data)`,
     `broadcast(message)` (meneur), `onCapture(demande)` (Slice 09 : une
     réponse de long-poll qui porte `capture_request`, remise au meneur
     seulement et jamais diffusée aux suiveurs).

     - `retry` (plafond de long-polls du Control Center) : attendre
       `retry_after_ms` (+ jusqu'à 250 ms), sans relire l'instantané.
     - `unavailable` ou erreur : garder l'état, attendre avec repli exponentiel.
     - Plus de deux resynchronisations de suite : repli avant de relire.
     - Onglet caché : requête en cours abandonnée ; au retour, reprise par les
       patchs depuis la révision tenue.
     - Changement de rôle : la requête en cours est abandonnée, le nouveau
       rôle repart de la révision tenue (un nouveau meneur relit les patchs
       depuis là : aucun trou).
     - Toute réponse d'une requête abandonnée est ignorée (génération). */
  function createSceneLoop(deps){
    const client=deps.client;
    const okHealth=()=>({level:'ok',code:null,message:'',since:null,retryAt:null});
    let enabled=false,visible=true,stopped=false,role='solo';
    let phase='off',generation=0,timer=null,abort=null,state=null;
    let failures=0,resyncs=0,objectLimit=512,health=okHealth();
    let watchTimer=null,lastLeaderAt=0,lastWatchReadAt=-Infinity,target=null,lastRetryNow=-Infinity,mirrored=false;
    const stats={snapshots:0,polls:0,catchUps:0,resyncs:0,retries:0,errors:0,received:0,broadcasts:0};

    const log=(level,event,data)=>{if(deps.log)deps.log(level,event,data||{})};
    const view=()=>({phase,role,state,health:{...health},objectLimit,stats:{...stats}});
    function emit(){if(deps.onUpdate)deps.onUpdate(view())}

    function broadcast(message){
      if(role!=='leader'||!deps.broadcast)return;
      try{deps.broadcast({v:MESSAGE_VERSION,...message});stats.broadcasts++}
      catch(error){log('warn','scene.broadcast_failed',{error:errorMessage(error)})}
    }
    function tick(){
      if(state)broadcast({type:'tick',scene_id:state.scene_id,epoch:state.epoch,revision:state.revision,health:{...health},objectLimit});
      else broadcast({type:'health',health:{...health}});
    }

    function cancel(){
      generation++;
      if(timer!==null){deps.clearTimeout(timer);timer=null}
      if(abort){const pending=abort;abort=null;try{pending.abort()}catch(_error){/* déjà abandonnée */}}
      health.retryAt=null;
    }

    function stopWatchdog(){if(watchTimer!==null){deps.clearTimeout(watchTimer);watchTimer=null}}
    /* Contrôle périodique du suiveur, indépendant de ses propres lectures :
       silence du meneur ≥ 35 s → une lecture courte, puis plus rien tant que
       le silence n'a pas encore duré 35 s de plus. Un meneur qui annonce sa
       révision ne déclenche jamais de lecture. */
    function armWatchdog(){
      if(watchTimer!==null)return;
      if(role!=='follower'||!enabled||!visible||stopped)return;
      watchTimer=deps.setTimeout(()=>{
        watchTimer=null;
        if(role!=='follower'||!enabled||!visible||stopped)return;
        const now=deps.now();
        if(phase==='following'&&now-lastLeaderAt>=FOLLOWER_SILENCE_MS&&now-lastWatchReadAt>=FOLLOWER_SILENCE_MS){
          lastWatchReadAt=now;
          log('info','scene.follower_watchdog',{revision:state?state.revision:null,silent_ms:now-lastLeaderAt});
          catchUp();
        }
        armWatchdog();
      },FOLLOWER_CHECK_MS);
    }

    function wait(ms,next){
      const current=++generation;
      phase='waiting';health.retryAt=deps.now()+ms;
      timer=deps.setTimeout(()=>{if(current!==generation)return;timer=null;health.retryAt=null;next()},ms);
      if(role==='leader')tick();
      emit();
    }

    function degrade(code,message){
      failures++;stats.errors++;mirrored=false;
      if(health.level!=='degraded'){
        health={level:'degraded',code,message:message||'',since:deps.now(),retryAt:null};
        log('warn','scene.view_degraded',{code,message:message||'',role});
      }else{
        health={...health,code,message:message||health.message};
      }
    }

    function recover(){
      failures=0;
      if(health.level==='ok')return;
      if(!mirrored)log('info','scene.view_restored',{code:health.code,after_ms:deps.now()-health.since,role});
      health=okHealth();mirrored=false;
    }

    /* Une requête à la fois ; `onBody` qui lève (défaut de la page) est traité
       comme une erreur : journalisé, puis repli. */
    function request(path,timeoutMs,onBody,onError){
      const current=++generation;
      const controller=deps.createAbort();
      abort=controller;
      Promise.resolve()
        .then(()=>deps.request(path,{signal:controller.signal,timeoutMs}))
        .then(body=>{
          if(current!==generation)return;
          abort=null;
          try{onBody(body)}catch(error){log('error','scene.loop_failed',{error:errorMessage(error)});onError(error)}
        },error=>{
          if(current!==generation)return;
          abort=null;onError(error);
        });
    }

    /* Instantané (tous rôles) ; ensuite long-poll (meneur, seul) ou attente
       des diffusions (suiveur). */
    function load(){
      phase='loading';stats.snapshots++;
      emit();
      request('/api/scene',SNAPSHOT_TIMEOUT_MS,body=>{
        if(!body||body.error){
          degrade(String(body&&body.error&&body.error.code||'no_snapshot'),String(body&&body.error&&body.error.message||''));
          return wait(backoffDelay(failures,deps.random),load);
        }
        const result=client.fromSnapshot(body);
        if(!result.ok){degrade(result.reason,'');return wait(backoffDelay(failures,deps.random),load)}
        if(client.acceptSnapshot(state,body))state=result.state;
        if(body.scene&&Number.isInteger(body.scene.object_limit))objectLimit=body.scene.object_limit;
        recover();
        log('info','scene.snapshot_loaded',{revision:state.revision,objects:state.objects.size,role});
        afterRead();
      },error=>{
        degrade(errorCode(error),errorMessage(error));
        wait(backoffDelay(failures,deps.random),load);
      });
    }

    /* Après une lecture réussie. */
    function afterRead(){
      if(role==='follower'){
        const wanted=target;target=null;
        if(wanted&&behind(wanted))return catchUp();
        phase='following';resyncs=0;
        armWatchdog();
        return emit();
      }
      tick();
      poll();
    }

    /* Réponse de patchs (long-poll du meneur ou lecture courte du suiveur). */
    function onPatches(body,again){
      const before=state;
      const result=client.applyPatchResponse(state,body);
      if(result.state)state=result.state;
      switch(result.action){
        case 'applied':case 'unchanged':case 'more':{
          resyncs=0;recover();
          const capture=body.capture_request;
          if(capture&&role==='leader'&&deps.onCapture){
            try{deps.onCapture(capture)}catch(error){log('error','scene.capture_hook_failed',{error:errorMessage(error)})}
          }
          if(role==='leader'&&state!==before)broadcast({type:'patches',scene_id:state.scene_id,epoch:state.epoch,body:withoutCapture(body)});
          if(result.action==='more')return again();
          return afterRead();
        }
        case 'retry':
          stats.retries++;
          return wait(Math.max(0,Number(result.retry_after_ms)||0)+Math.round(deps.random()*250),again);
        case 'resync':
          stats.resyncs++;resyncs++;
          log('info','scene.resync',{reason:result.reason,role});
          if(resyncs>2)return wait(backoffDelay(resyncs-2,deps.random),load);
          return load();
        default:
          degrade(result.reason,String(body&&body.error&&body.error.message||''));
          return wait(backoffDelay(failures,deps.random),again);
      }
    }

    function poll(){
      if(!state)return load();
      phase='polling';stats.polls++;
      emit();
      request(patchPath(client.patchQuery(state,LONG_POLL_WAIT_S)),POLL_TIMEOUT_MS,body=>onPatches(body,poll),error=>{
        degrade(errorCode(error),errorMessage(error));
        wait(backoffDelay(failures,deps.random),poll);
      });
    }

    /* Suiveur : patchs manqués par une lecture qui répond aussitôt. */
    function catchUp(){
      if(!state)return load();
      phase='catching_up';stats.catchUps++;
      emit();
      request(patchPath(client.patchQuery(state,0)),SNAPSHOT_TIMEOUT_MS,body=>onPatches(body,catchUp),error=>{
        degrade(errorCode(error),errorMessage(error));
        wait(backoffDelay(failures,deps.random),catchUp);
      });
    }

    function start(){
      log('info','scene.loop_started',{catch_up:!!state,role});
      if(role==='follower'){lastLeaderAt=deps.now();return state?catchUp():load()}
      if(state)poll();else load();
    }

    function evaluate(){
      if(stopped)return;
      if(!enabled){
        if(phase==='off')return;
        cancel();stopWatchdog();phase='off';state=null;failures=0;resyncs=0;health=okHealth();target=null;
        log('info','scene.loop_off',{});
        return emit();
      }
      if(!visible){
        if(phase==='paused')return;
        cancel();stopWatchdog();phase='paused';
        log('info','scene.loop_paused',{revision:state?state.revision:null,role});
        return emit();
      }
      if(phase!=='off'&&phase!=='paused')return;
      start();
    }

    /* Diffusion reçue d'un meneur (suiveur, ou onglet caché qui garde son
       état au plus près). */
    function receive(message){
      if(stopped||!enabled||role==='leader'||role==='solo'||!validMessage(message))return;
      stats.received++;lastLeaderAt=deps.now();
      if(message.type==='health'||message.type==='tick'){
        const next=message.health;
        if(health.level!==next.level||health.code!==next.code){
          if(next.level==='degraded'){health={level:'degraded',code:next.code||null,message:String(next.message||''),since:Number(next.since)||deps.now(),retryAt:next.retryAt||null};mirrored=true}
          else if(mirrored||phase==='following'){health=okHealth();mirrored=false}
          emit();
        }else if(next.level==='degraded'&&mirrored){health={...health,retryAt:next.retryAt||null};emit()}
        if(message.type==='health')return;
        if(Number.isInteger(message.objectLimit))objectLimit=message.objectLimit;
        return lagging({scene_id:message.scene_id,epoch:message.epoch,revision:message.revision});
      }
      /* patches */
      const wanted={scene_id:message.scene_id,epoch:message.epoch,
        revision:Number.isSafeInteger(message.body.revision)?message.body.revision:(state?state.revision+1:0)};
      if(!state||phase!=='following')return lagging(wanted);
      const result=client.applyPatchResponse(state,message.body);
      if(result.action==='applied'||result.action==='unchanged'||result.action==='more'){
        if(result.state!==state){state=result.state;emit()}
        return;
      }
      lagging(wanted);
    }

    /* L'état tenu est-il en retard sur `wanted` (scène, époque, révision) ? */
    function behind(wanted){
      return !state||state.scene_id!==wanted.scene_id||state.epoch!==wanted.epoch||wanted.revision>state.revision;
    }

    /* Retard constaté : rattraper tout de suite si le suiveur est au repos,
       sinon retenir la cible pour la fin de la lecture en cours (ou le retour
       de l'onglet). */
    function lagging(wanted){
      if(!behind(wanted))return;
      if(phase==='following')return catchUp();
      if(!target||target.epoch!==wanted.epoch||target.revision<wanted.revision)target=wanted;
    }

    return {
      setEnabled(value){enabled=!!value;evaluate()},
      setVisible(value){
        visible=!!value;
        evaluate();
      },
      /* Changer de rôle repart de la révision tenue. */
      setRole(next){
        if(next!==role&&['leader','follower','solo'].includes(next)){
          const previous=role;role=next;
          log('info','scene.role',{from:previous,to:next,revision:state?state.revision:null});
          if(!enabled||!visible||stopped)return;
          cancel();stopWatchdog();
          if(health.level==='degraded'&&mirrored){health=okHealth();mirrored=false}
          start();
        }
      },
      receive,
      /* Le Control Center répond de nouveau (`/api/status` après une panne) :
         oublier le repli et relire tout de suite. */
      retryNow(){
        if(stopped||!enabled||!visible||phase!=='waiting')return false;
        if(deps.now()-lastRetryNow<RETRY_NOW_MIN_MS)return false;
        lastRetryNow=deps.now();
        cancel();failures=0;
        log('info','scene.retry_now',{role});
        if(role==='follower')return (state?catchUp():load()),true;
        return (state?poll():load()),true;
      },
      stop(){if(stopped)return;cancel();stopWatchdog();stopped=true;phase='stopped';emit()},
      view,
    };
  }

  /* Validation des placements du résolveur (`set_geometry`,
     `placed_by = resolver`, par le relais utilisateur du Control Center).

     - Seul l'onglet meneur (`input.leader`) valide, et seulement quand sa
       lecture est à jour (`input.healthy`) ; les autres dessinent le même
       placement (résolveur déterministe) sans rien envoyer.
     - Un objet n'est validé qu'une fois par page : le registre retient chaque
       envoi ; réponse du domaine (appliqué, doublon, `explicit_placement`,
       `pinned_by_user`, objet inconnu ou archivé) ou erreur de forme → plus
       jamais ; rien d'appliqué ou issue inconnue (503/504/réseau) → nouvel
       essai de la même boîte après 2 s puis 8 s, trois envois au plus, et
       pause de tous les envois pendant ce délai (8 s après un abandon).
     - Juste avant l'envoi, l'objet est relu dans l'état tenu : placé entre-temps
       (patch d'un autre onglet, du cerveau), il n'est pas envoyé.
     - Attente de `settleMs` (+ jusqu'à 400 ms) avant un lot, 32 commandes par
       lot, une à la fois. */
  function createResolverCommitter(deps){
    const L=deps.layout;
    const ledger=new Map();
    const batch=deps.batch||32,settleMs=deps.settleMs===undefined?600:deps.settleMs;
    let input=null,timer=null,timerAt=null,running=false,stopped=false,pausedUntil=0;
    const stats={sent:0,applied:0,duplicate:0,refused:0,invalid:0,retried:0,failed:0};
    const log=(level,event,data)=>{if(deps.log)deps.log(level,event,data||{})};

    const ready=()=>!stopped&&!!input&&!!input.state&&!!input.layout&&input.leader===true&&input.healthy===true;
    const candidates=()=>ready()&&deps.now()>=pausedUntil?L.commitCandidates(input.state,input.layout,ledger,deps.now()):[];

    function clearTimer(){if(timer!==null){deps.clearTimeout(timer);timer=null;timerAt=null}}

    function schedule(delay){
      if(stopped||running)return;
      const at=deps.now()+delay;
      if(timer!==null){if(timerAt<=at)return;clearTimer()}
      timerAt=at;
      timer=deps.setTimeout(()=>{timer=null;timerAt=null;run()},delay);
    }

    function plan(){
      if(!ready())return clearTimer();
      const now=deps.now();
      if(now<pausedUntil)return schedule(pausedUntil-now);
      if(candidates().length)return schedule(settleMs+Math.round(deps.random()*400));
      const retryAt=L.nextRetryAt(ledger,now);
      if(retryAt!==null)schedule(retryAt-now);
    }

    function count(verdict,entry){
      if(entry.status==='retry'){stats.retried++;return}
      if(verdict.outcome==='applied')stats.applied++;
      else if(verdict.outcome==='duplicate')stats.duplicate++;
      else if(verdict.outcome==='rejected_authority')stats.refused++;
      else if(verdict.outcome==='invalid')stats.invalid++;
      else stats.failed++;
    }

    async function run(){
      if(running||stopped)return;
      running=true;let sent=0;
      try{
        while(sent<batch){
          const next=candidates()[0];
          if(!next)break;
          const previous=ledger.get(next.key);
          ledger.set(next.key,{status:'sending',attempts:previous?previous.attempts:0,retryAt:null});
          let verdict;
          try{
            const response=await deps.post(next.command);
            verdict=L.classifyCommit(response.status,response.body);
          }catch(error){
            verdict={settle:'retry',outcome:'not_confirmed',reason:errorCode(error)};
          }
          const entry=L.settleCommit(ledger,next.key,verdict,deps.now());
          sent++;stats.sent++;count(verdict,entry);
          if(verdict.settle==='retry'){
            /* Core ou le relais ne répond pas : tous les envois attendent. */
            pausedUntil=entry.retryAt===null?deps.now()+8000:entry.retryAt;
            log('warn','scene.resolver_commit_retry',{object_id:next.objectId,reason:verdict.reason,attempts:entry.attempts});
            break;
          }
          if(verdict.outcome==='applied'||verdict.outcome==='duplicate')
            log('info','scene.resolver_committed',{object_id:next.objectId,outcome:verdict.outcome});
          else
            log(verdict.outcome==='failed'?'warn':'info','scene.resolver_commit_refused',
              {object_id:next.objectId,outcome:entry.outcome,reason:verdict.reason});
        }
      }finally{
        running=false;
      }
      if(stopped)return;
      if(sent>=batch&&candidates().length)schedule(50);else plan();
    }

    return {
      update(next){input=next||null;plan()},
      stop(){stopped=true;clearTimer()},
      stats:()=>({...stats,pending:ready()?L.commitCandidates(input.state,input.layout,ledger,Infinity).length:0}),
      ledger:()=>new Map(ledger),
    };
  }

  return Object.freeze({LONG_POLL_WAIT_S,SNAPSHOT_TIMEOUT_MS,POLL_TIMEOUT_MS,BACKOFF_BASE_MS,BACKOFF_MAX_MS,
    FOLLOWER_SILENCE_MS,FOLLOWER_CHECK_MS,RETRY_NOW_MIN_MS,MESSAGE_VERSION,
    backoffDelay,patchPath,gateEnabled,validMessage,withoutCapture,createSceneLoop,createResolverCommitter,createLeadership});
})();

/* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
if(typeof module!=='undefined'&&module.exports)module.exports=JarvisScenePageCore;

/* --------------------------------------------------------------------------
   Bloc navigateur : conteneur, relations, nœuds, verrou, canal, interrupteur.
   -------------------------------------------------------------------------- */
(function installJarvisScene(){
  if(typeof window==='undefined'||typeof document==='undefined')return;
  const L=window.JarvisSceneLayout,Client=window.JarvisSceneClient,Core=JarvisScenePageCore;
  if(!L||!Client)return;
  /* Interactions (Slice 08). Absentes : la scène se dessine sans geste. */
  const I=window.JarvisSceneInteract||null;
  /* Capture visuelle (Slice 09, partie 2). Absente : aucune demande n'est servie. */
  const Capture=window.JarvisSceneCapture||null;
  /* Réglages d'affichage de l'utilisateur (Slice 12). Absents : les valeurs de
     référence, et aucun bouton dans la page. */
  const V=window.JarvisSceneView||null;
  const SVG_NS='http://www.w3.org/2000/svg';
  /* Un verrou par profil : le meneur tient le long-poll et valide les
     placements. Un seul verrou pour les deux : la validation exige l'état le
     plus frais, que seul le long-poll garantit. */
  const LOCK_NAME='jarvis.scene.leader';
  const CHANNEL_NAME='jarvis.scene';
  const TAB_ID=`${Date.now().toString(36)}-${Math.random().toString(36).slice(2,10)}`;
  /* Zone sensible d'un point (étoile, signal), en pixels. */
  const POINT_HIT=L.POINT_HIT_PX;
  /* Un anneau ne s'anime que pendant ce délai après l'apparition du nœud ou
     un changement de son état (exécution, urgence) ; ensuite il reste fixe.
     Toute animation CSS en cours coûte un recalcul de style par image : au
     repos, la scène n'en fait aucun. */
  const ANIMATE_FOR_MS=12000;
  /* Respiration d'un halo d'étoile (même durée que `sc-glow`) : sert à décaler
     la phase de chaque étoile. */
  const GLOW_MS=6400;
  /* Au-delà de ce nombre d'étoiles dessinées, la gravitation et les halos
     s'arrêtent (`sc-calm`) : une couche de composition par étoile, et une scène
     aussi peuplée se lit mieux immobile. */
  const CALM_POINTS=96;

  /* Images-clés du tour du champ : les étapes de `JarvisSceneLayout.orbitSteps`
     — un angle qui avance du même pas, d'un bout à l'autre de la période, et
     qui boucle exactement sur son départ. Les nœuds et le calque des fils
     lisent les **mêmes** étapes et reçoivent le **même** décalage
     (`translate`) : le mouvement du champ est une translation, donc chaque fil
     tombe sur les deux nouveaux centres, à tout instant. `--sc-orbit-r`, posé
     par la page sur le conteneur, est le rayon du cercle parcouru. */
  function orbitKeyframes(){
    const rx='var(--sc-orbit-rx,0px)',ry='var(--sc-orbit-ry,0px)';
    const dx='var(--sc-orbit-dx,0px)',dy='var(--sc-orbit-dy,0px)';
    /* Position sur le cercle, moins l'écart à la place : `transform` garde la
       place (la géométrie de la scène), `translate` porte le tour et rien
       d'autre. Un objet au centre n'a ni rayon ni écart : il ne bouge pas. */
    const steps=L.orbitSteps().map(step=>
      `${step.at}%{translate:calc(${rx} * ${step.x} - ${dx}) calc(${ry} * ${step.y} - ${dy})}`);
    /* Le calque des fils tourne du même angle autour du même centre : une
       rotation envoie le segment qui joint deux étoiles sur le segment qui
       joint leurs deux nouvelles places, donc les fils restent noués sans
       qu'on les redessine. Le resserrement du champ voyage avec. */
    const field=L.orbitSteps().map(step=>
      `${step.at}%{transform:scale(var(--sc-orbit-ax,1),var(--sc-orbit-ay,1)) `
      + `scale(var(--sc-orbit-scale,1)) rotate(${step.angle}deg) `
      + `scale(var(--sc-orbit-iax,1),var(--sc-orbit-iay,1))}`);
    return `@keyframes sc-orbit{${steps.join('')}}@keyframes sc-orbit-field{${field.join('')}}`;
  }

  /* Registre d'empilement de la page (voir `control_center.html`) : visage 0,
     canevas Cosmos 0, **scène 20**, barre du haut et indication vocale 31,
     dock 32, panneau 33, bandeau GPT-Live 35, pastilles 40 (Cosmos : panneau
     42, barre 45, bandeau 48, dock et pastilles 50), fond des réglages 60,
     notifications 70, liste des pastilles 75, menu contextuel 80, Barehands
     2147483000. Les couches de la scène (0–1000) ne s'empilent qu'à
     l'intérieur du conteneur, qui crée son propre contexte. */
  const STYLE=`
.scene{position:absolute;inset:0;z-index:20;pointer-events:none;overflow:hidden;contain:layout paint style;
  font:12px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--sc-ink);
  --sc-ink:#dcecf4;--sc-muted:#8aa5b3;--sc-edge:rgba(151,191,209,.16);--sc-ring:rgba(220,236,244,.66);
  --sc-surface:rgba(4,10,15,.88);--sc-radius:14px;--sc-warn:#ffb85c;--sc-done:#6fe3a4;--sc-fail:#ff6b7d}
html:not([data-jarvis-theme="cosmos"]) .scene{--sc-edge:rgba(110,231,255,.2);--sc-radius:7px}
.scene .sc-tone-agent{--tone:#eef6fa}.scene .sc-tone-job{--tone:#a8c1ff}.scene .sc-tone-doc{--tone:#6fe3a4}
.scene .sc-tone-research{--tone:#6ee7ff}.scene .sc-tone-code{--tone:#c6a0ff}.scene .sc-tone-comms{--tone:#f0cf78}
.scene .sc-tone-error{--tone:#ff6b7d}.scene .sc-tone-interrupted{--tone:#f2a46e}.scene .sc-tone-blocked{--tone:#ffbf5c}
.scene .sc-tone-x0{--tone:#5ad8c6}.scene .sc-tone-x1{--tone:#ff92bd}.scene .sc-tone-x2{--tone:#b9e46d}
.scene .sc-tone-x3{--tone:#86b9ff}.scene .sc-tone-x4{--tone:#e0a8ff}.scene .sc-tone-x5{--tone:#e6c69c}
.sc-links{position:absolute;left:0;top:0;width:100%;height:100%;z-index:0;overflow:visible}
.sc-link{stroke:rgba(170,205,220,.3);stroke-width:1;fill:none;vector-effect:non-scaling-stroke}
.sc-link-explains{stroke-dasharray:3 4}
.sc-link-groups{stroke-dasharray:1 5;stroke-linecap:round}
.sc-link-signal{stroke:color-mix(in srgb,var(--tone) 58%,transparent);stroke-dasharray:none}
.sc-node{position:absolute;left:0;top:0;pointer-events:auto;outline:none;box-sizing:border-box;touch-action:none;user-select:none;-webkit-user-select:none}
/* Gestes (Slice 08) : aucun glissement animé pendant la main de l'utilisateur.
   Ni juste après ('sc-settling', 21/09/2026) : au relâchement, la place passe
   de la boîte tenue sous le curseur à la place enregistrée, dont le tour du
   champ retranche l'arc. Or la place est dans 'transform', qui est transitionné,
   et l'arc dans 'translate', qui ne l'est pas : la seconde composante sautait
   pendant que la première mettait 420 ms à arriver, et l'objet faisait une
   excursion avant de revenir exactement là où il avait été lâché. Une
   manipulation directe est atomique : elle se pose, elle ne glisse pas. La
   classe tombe à l'image suivante, quand la place est déjà appliquée. */
.scene .sc-node.sc-dragging{transition:none!important;cursor:grabbing}
.scene .sc-node.sc-settling{transition:none!important}
.scene.sc-gesture{cursor:grabbing}
/* Rectangle de sélection tiré dans le vide : un cadre fin, rien qui capte le
   pointeur — ce qui est dessous doit rester visible et cliquable. */
.sc-band{position:absolute;pointer-events:none;z-index:2147482000;
  border:1px solid var(--sc-ink);background:rgba(120,170,255,.10);border-radius:2px}
/* Sous la main — souris, Bare Hands ou clavier : **l'objet tenu** est figé,
   à l'écart que son tour lui donnait à la prise (posé en 'translate' par la
   page), et ne dérive pas d'un pixel sous la main. Le reste du champ continue
   de tourner, à l'heure murale : arrêter tout le champ décalait l'heure du tour
   de la durée du geste, d'un onglet à l'autre et au rechargement (22/09/2026). */
.scene .sc-node.sc-held{animation:none!important}
/* Retour d'un onglet caché : les places ont pu changer pendant qu'il l'était ;
   elles se posent d'un coup, sans la glissade de 420 ms de la composition. */
.scene.sc-resync .sc-node{transition:none!important}
.sc-capsule,.sc-window{cursor:grab}
.sc-grip{position:absolute;right:3px;bottom:3px;width:13px;height:13px;display:grid;place-items:center;color:var(--sc-muted);cursor:nwse-resize;
  opacity:0;transition:opacity .14s ease-out}
.sc-grip svg{width:9px;height:9px;fill:none;stroke:currentColor;stroke-width:1.4;stroke-linecap:round}
/* Dans une capsule, la poignée est **centrée verticalement** dans l'extrémité
   arrondie : collée au coin bas droit, elle tombait hors de l'arrondi que
   découpe 'overflow:hidden', et son centre n'était plus cliquable (22/09/2026). */
.sc-capsule .sc-grip{right:5px;top:50%;bottom:auto;width:12px;height:12px;margin-top:-6px}
.sc-capsule:has(>.sc-grip){padding-right:18px}
.sc-node:hover>.sc-grip,.sc-node:focus>.sc-grip,.sc-node.sc-selected>.sc-grip,.sc-node.sc-dragging>.sc-grip{opacity:.9}
.sc-capsule.sc-selected,.sc-window.sc-selected{box-shadow:inset 0 0 0 1px var(--sc-ink),0 10px 28px rgba(0,0,0,.34)}
.sc-point.sc-selected .sc-mark{outline:1px solid var(--sc-ink);outline-offset:5px}
/* Arrêt en cours (reprise QA) : anneau en tirets orange qui tourne, jusqu'à la fin dite par Core. */
.sc-node.sc-stopping .sc-ring{border:1.5px dashed var(--sc-warn)!important;opacity:1!important;animation:sc-spin 1.6s linear infinite!important}
.sc-capsule.sc-stopping,.sc-window.sc-stopping{box-shadow:inset 0 0 0 1px var(--sc-warn),0 10px 28px rgba(0,0,0,.34)}
.sc-grip:hover{color:var(--sc-ink)}
/* Seul le déplacement glisse (composition) ; une taille change d'un coup. */
.scene.sc-ready .sc-node{transition:transform .42s cubic-bezier(.16,1,.3,1)}
/* Gravitation : **le champ tourne autour du visage**. Chaque objet parcourt le
   cercle centré sur le centre de la fenêtre qui passe par sa place, dans le
   sens horaire, un tour par période, à vitesse angulaire constante — jamais un
   va-et-vient, et jamais le champ entier qui glisse d'un bloc (les deux
   versions précédentes, l'une puis l'autre). Tous lisent la même animation et
   la même période ; ce qui les distingue est leur rayon ('--sc-orbit-r') et
   leur phase ('animation-delay'), calculés par 'JarvisSceneLayout.orbitTrack'.
   Le calque des fils ('.sc-field') tourne du même angle autour du même centre :
   une rotation envoie le segment qui joint deux étoiles sur celui qui joint
   leurs nouvelles places, donc l'extrémité d'un fil reste sur le centre de son
   étoile sans qu'on le redessine. La place elle-même reste dans 'transform' (la
   géométrie de la scène) : le tour s'ajoute par-dessus, dans 'translate', et
   n'est jamais enregistré. Capsules et fenêtres tournent avec le champ, et
   l'arrangement ne change pas d'un pixel. Une étoile épinglée tourne comme les
   autres — sa place, elle, ne change pas. */
.scene .sc-orbit{animation:sc-orbit var(--sc-orbit-ms,240000ms) linear infinite}
.scene .sc-field{transform-box:view-box;transform-origin:var(--sc-orbit-cx,50%) var(--sc-orbit-cy,50%);
  animation:sc-orbit-field var(--sc-orbit-ms,240000ms) linear infinite}
${orbitKeyframes()}
/* Scène très peuplée : la gravitation et les halos s'arrêtent (une couche de
   composition par étoile). La lecture prime sur le mouvement. 'sc-still' : pas
   la place de tourner sans sortir de la zone sûre — le champ reste immobile. */
.scene.sc-calm .sc-orbit,.scene.sc-still .sc-orbit,.scene.sc-no-orbit .sc-orbit{animation:none;translate:none}
.scene.sc-calm .sc-field,.scene.sc-still .sc-field,.scene.sc-no-orbit .sc-field{animation:none;transform:none}
.scene.sc-calm .sc-mark::after{animation:none}
/* Réglages d'affichage de l'utilisateur ('JarvisSceneView', fenêtre « Affichage
   des étoiles ») : la gravitation éteinte s'arrête tout de suite, sans attendre
   le prochain rendu ; halo éteint, halo fixe, fils masqués. */
.scene.sc-no-orbit .sc-orbit{animation:none;translate:none}
.scene.sc-no-halo .sc-mark::after{display:none}
.scene.sc-still-halo .sc-mark::after{animation:none}
.scene.sc-no-links .sc-links{display:none}
.sc-point{width:${POINT_HIT}px;height:${POINT_HIT}px;border-radius:50%}
.sc-point:hover,.sc-point:focus-visible{z-index:2147483000!important}
/* Étoile : point lumineux plutôt que pastille plate — cœur blanc chaud, couleur
   de la catégorie, fondu vers le vide ; même dégradé que le cœur du visage
   ('control_center_work.js', 'coreGlow'/'disc'). */
.sc-mark{position:absolute;left:50%;top:50%;--sc-star:calc(8px * var(--sc-star-scale,1));
  width:var(--sc-star);height:var(--sc-star);margin:calc(var(--sc-star) * -.5) 0 0 calc(var(--sc-star) * -.5);border-radius:50%;
  background:radial-gradient(circle,#fff 0 10%,color-mix(in srgb,var(--tone) 78%,#fff) 30%,var(--tone) 62%,
    color-mix(in srgb,var(--tone) 58%,transparent) 100%);
  box-shadow:0 0 calc(var(--sc-star) * .875) color-mix(in srgb,var(--tone) 68%,transparent),
    0 0 calc(var(--sc-star) * 2.25) color-mix(in srgb,var(--tone) 30%,transparent)}
/* Halo : voile large et doux qui respire lentement, jamais clignotant (la
   galaxie du visage : ~3 rayons, une dizaine de pour cent d'opacité). Le
   décalage '--sc-glow-delay', lu dans la place de l'étoile, évite que tous les
   halos battent ensemble. Opacité et échelle seulement : le navigateur compose
   sans recalculer de style. */
.sc-mark::after{content:'';position:absolute;left:50%;top:50%;border-radius:50%;
  --sc-halo:calc(28px * var(--sc-halo-scale,1) * var(--sc-star-scale,1));
  width:var(--sc-halo);height:var(--sc-halo);margin:calc(var(--sc-halo) * -.5) 0 0 calc(var(--sc-halo) * -.5);
  pointer-events:none;
  background:radial-gradient(circle,color-mix(in srgb,var(--tone) 54%,transparent) 0,
    color-mix(in srgb,var(--tone) 21%,transparent) 34%,transparent 74%);
  animation:sc-glow 6.4s ease-in-out infinite;animation-delay:var(--sc-glow-delay,0ms)}
.sc-ring{position:absolute;left:50%;top:50%;--sc-rings:calc(18px * var(--sc-star-scale,1));
  width:var(--sc-rings);height:var(--sc-rings);margin:calc(var(--sc-rings) * -.5) 0 0 calc(var(--sc-rings) * -.5);
  border-radius:50%;border:1px solid transparent;pointer-events:none}
/* État d'exécution : indice secondaire. Au plus 24 anneaux animés (.sc-anim) ;
   les autres gardent le même anneau, fixe. */
.sc-exec-running .sc-ring{border-color:var(--sc-ring);opacity:.72}
.sc-exec-running.sc-anim .sc-ring{animation:sc-breathe 2.8s ease-in-out infinite;will-change:transform,opacity}
.sc-exec-pending .sc-ring{border:1px dashed rgba(220,236,244,.5)}
.sc-exec-blocked .sc-ring{--sc-rings:calc(20px * var(--sc-star-scale,1));border:3px double rgba(220,236,244,.62)}
/* Slice 10 : état inconnu depuis le redémarrage de Core. Anneau pointillé
   pâle, jamais animé, point atténué : ni « en cours », ni alarme. */
.sc-restart-unknown .sc-ring{border:1px dotted rgba(220,236,244,.46);opacity:.9;animation:none}
.sc-restart-unknown .sc-mark{opacity:.62}
/* Libellé plus large : « état inconnu depuis le redémarrage » et le titre
   d'un signal de redémarrage ne mangent pas tout le titre (navigateur, S10). */
.sc-restart-unknown .sc-label,.sc-signal .sc-label{max-width:min(64ch,80vw)}
/* Suivi final : l'état d'abord, le titre borné à 24ch — « état inconnu depuis
   le redémarrage » se lit toujours en entier, quelle que soit la longueur du titre. */
.sc-restart-unknown .sc-label span{order:-1}
.sc-restart-unknown .sc-label strong{max-width:24ch}
/* Fin de travail (événement 'core.scene.star_finished') : anneau fin, fixe et
   serré autour de l'étoile — vert pour une fin normale, rouge pour un échec —
   plus la petite icône du badge, comme un signal d'attention. Jamais animé :
   le halo continue de respirer et l'orbite de tourner par-dessous, et c'est
   l'alerte, elle, qui garde le battement. */
.sc-point.sc-exec-completed .sc-ring,.sc-point.sc-exec-failed .sc-ring{--sc-rings:calc(15px * var(--sc-star-scale,1));animation:none}
.sc-point.sc-exec-completed .sc-ring{border:1px solid color-mix(in srgb,var(--sc-done) 72%,transparent);
  box-shadow:0 0 6px color-mix(in srgb,var(--sc-done) 22%,transparent)}
.sc-point.sc-exec-failed .sc-ring{border:1px solid color-mix(in srgb,var(--sc-fail) 72%,transparent);
  box-shadow:0 0 6px color-mix(in srgb,var(--sc-fail) 22%,transparent)}
/* Icône de fin : même pastille que les autres badges, teintée de l'anneau. */
.sc-exec-completed .sc-badge{color:var(--sc-done);box-shadow:0 0 0 1px color-mix(in srgb,var(--sc-done) 52%,transparent)}
.sc-exec-failed .sc-badge{color:var(--sc-fail);box-shadow:0 0 0 1px color-mix(in srgb,var(--sc-fail) 52%,transparent)}
/* Alerte vivante sur la même étoile : sa marque de fin s'efface d'un cran pour
   ne pas se battre avec le signal, qui reste ce que l'œil attrape d'abord. */
.sc-point.sc-alerted.sc-exec-completed .sc-ring,.sc-point.sc-alerted.sc-exec-failed .sc-ring{opacity:.45;box-shadow:none}
.sc-point.sc-alerted.sc-exec-completed .sc-badge,.sc-point.sc-alerted.sc-exec-failed .sc-badge{opacity:.72}
.sc-signal .sc-mark{width:8px;height:8px;margin:-4px 0 0 -4px;border-radius:1.5px;transform:rotate(45deg)}
/* Signal retiré : marque creuse, et pas de lueur — plus rien ne l'anime. */
.sc-signal.sc-urgency-none .sc-mark{background:transparent;box-shadow:inset 0 0 0 1.5px color-mix(in srgb,var(--tone) 80%,transparent)}
.sc-signal.sc-urgency-none .sc-mark::after{display:none}
.sc-signal .sc-ring,.sc-signal.sc-exec-completed .sc-ring,.sc-signal.sc-exec-failed .sc-ring{width:18px;height:18px;margin:-9px 0 0 -9px;border:0;box-shadow:none;animation:none;opacity:1}
.sc-signal.sc-urgency-high .sc-ring{border:1.5px solid var(--tone);opacity:.8;transform:scale(1.25)}
.sc-signal.sc-urgency-medium .sc-ring{border:1px solid var(--tone);opacity:.8;transform:scale(1.25)}
.sc-signal.sc-urgency-high.sc-anim .sc-ring{animation:sc-alert 1.9s cubic-bezier(.2,.7,.3,1) infinite;will-change:transform,opacity}
.sc-signal.sc-urgency-medium.sc-anim .sc-ring{animation:sc-alert 3.2s cubic-bezier(.2,.7,.3,1) infinite;will-change:transform,opacity}
.sc-signal.sc-urgency-low .sc-mark{width:6px;height:6px;margin:-3px 0 0 -3px;box-shadow:none}
.sc-signal.sc-urgency-low .sc-ring{width:14px;height:14px;margin:-7px 0 0 -7px;border:1px solid color-mix(in srgb,var(--tone) 38%,transparent);transform:none}
.scene.sc-paused .sc-ring,.scene.sc-paused .sc-orbit,.scene.sc-paused .sc-field,.scene.sc-paused .sc-mark::after{animation-play-state:paused}
.sc-badge{position:absolute;right:0;top:0;width:12px;height:12px;border-radius:50%;background:#061017;display:grid;place-items:center;
  color:var(--sc-ink);box-shadow:0 0 0 1px rgba(220,236,244,.46)}
/* Sur un point, en bas à droite : le haut droit est la place du signal. */
.sc-point .sc-badge{top:auto;bottom:1px;right:1px}
.sc-badge svg{width:8px;height:8px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.sc-label{position:absolute;left:50%;top:100%;display:flex;gap:7px;align-items:baseline;white-space:nowrap;max-width:min(42ch,70vw);
  padding:4px 10px;border-radius:999px;background:rgba(3,8,12,.92);box-shadow:inset 0 0 0 1px var(--sc-edge),0 8px 22px rgba(0,0,0,.4);
  font-size:11px;opacity:0;visibility:hidden;transform:translate(calc(-50% + var(--sc-dx,0px)),2px);
  transition:opacity .16s ease-out,transform .16s ease-out,visibility 0s .16s;pointer-events:none}
.sc-label.sc-label-up{top:auto;bottom:100%}
.sc-label strong{min-width:0;overflow:hidden;text-overflow:ellipsis;font-weight:600;color:#f1f8fb}
.sc-label span{flex:none;font-size:9.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--sc-muted)}
.sc-point:hover .sc-label,.sc-point:focus-visible .sc-label{opacity:1;visibility:visible;transform:translate(calc(-50% + var(--sc-dx,0px)),6px);transition:opacity .16s ease-out,transform .16s ease-out}
.sc-point:hover .sc-label.sc-label-up,.sc-point:focus-visible .sc-label.sc-label-up{transform:translate(calc(-50% + var(--sc-dx,0px)),-6px)}
.sc-point:focus-visible .sc-mark{outline:1px solid var(--sc-ink);outline-offset:5px}
.sc-capsule{display:flex;align-items:center;gap:8px;padding:0 12px 0 11px;border-radius:999px;background:var(--sc-surface);overflow:hidden;
  box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--tone) 32%,rgba(151,191,209,.14)),0 10px 28px rgba(0,0,0,.34)}
.sc-dot{position:relative;flex:none;width:7px;height:7px;border-radius:50%;background:var(--tone);box-shadow:0 0 10px color-mix(in srgb,var(--tone) 40%,transparent)}
.sc-dot .sc-ring{width:15px;height:15px;margin:-7.5px 0 0 -7.5px}
.sc-title{min-width:0;flex:1 1 auto;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:12px;letter-spacing:.01em;color:#eaf5fa}
.sc-capsule .sc-badge,.sc-window .sc-badge{position:relative;flex:none}
.sc-pin{flex:none;width:11px;height:11px;color:var(--sc-muted)}
.sc-pin svg{width:11px;height:11px;fill:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round;display:block}
.sc-capsule:focus,.sc-window:focus{box-shadow:inset 0 0 0 1px var(--sc-ink),0 10px 28px rgba(0,0,0,.34)}
.sc-point:focus .sc-mark{outline:1px solid var(--sc-ink);outline-offset:5px}
.sc-point:focus .sc-label{opacity:1;visibility:visible;transform:translate(calc(-50% + var(--sc-dx,0px)),6px);transition:opacity .16s ease-out,transform .16s ease-out}
.sc-point:focus .sc-label.sc-label-up{transform:translate(calc(-50% + var(--sc-dx,0px)),-6px)}
.sc-window{display:flex;flex-direction:column;border-radius:var(--sc-radius);background:rgba(4,10,15,.9);overflow:hidden;
  box-shadow:inset 0 1px 0 color-mix(in srgb,var(--tone) 72%,transparent),inset 0 0 0 1px var(--sc-edge),0 24px 64px rgba(0,0,0,.5);
  backdrop-filter:blur(18px)}
.sc-head{display:flex;align-items:center;gap:8px;padding:11px 13px 3px;flex:none}
.sc-cat{min-width:0;flex:1 1 auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:9.5px;letter-spacing:.12em;text-transform:uppercase;
  color:color-mix(in srgb,var(--tone) 72%,var(--sc-ink))}
/* Deux lignes au plus : la marge (hors de la boîte bornée) ne laisse pas
   passer de troisième ligne. */
.sc-wtitle{flex:none;margin:0 13px 8px;padding:0;font-size:13px;font-weight:600;line-height:1.35;max-height:2.7em;color:#f1f8fb;overflow:hidden;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow-wrap:anywhere}
/* Résumé plus haut que la place qui lui reste : il défile dans la fenêtre
   (molette, PageHaut/PageBas) au lieu d'être coupé sans recours. Barre fine et
   discrète, la même que la liste d'un artefact. */
.sc-summary{flex:1 1 auto;min-height:0;padding:0 13px 10px;font-size:12px;line-height:1.5;color:#b3cbd6;white-space:pre-wrap;overflow:hidden auto;overflow-wrap:anywhere;
  overscroll-behavior:contain;scrollbar-width:thin;scrollbar-color:rgba(151,191,209,.28) transparent;
  -webkit-mask-image:linear-gradient(#000 calc(100% - 22px),transparent);mask-image:linear-gradient(#000 calc(100% - 22px),transparent)}
/* Markdown du résumé (21/09/2026) : le cerveau écrit en markdown, la fenêtre
   l'interprète. Marges serrées — une fenêtre est petite, et un résumé y tient
   rarement deux fois. Le conteneur garde pre-wrap pour un résumé posé en texte
   brut (fenêtre d'entraînement de Bare Hands) ; chaque bloc rendu ici reprend
   la valeur d'espacement qui lui convient. */
.sc-summary :where(p,ul,ol,pre,blockquote,hr,div){margin:0}
.sc-summary>*+*{margin-top:6px}
.sc-md-p{white-space:pre-wrap}
.sc-md-h{white-space:pre-wrap;font-weight:600;line-height:1.35;color:#dbeaf1}
.sc-md-h1{font-size:13px}
.sc-md-h2{font-size:12.5px}
.sc-md-h3{font-size:12px;color:#c9dee7}
.sc-summary ul,.sc-summary ol{margin:0;padding-left:17px;white-space:normal}
.sc-summary ul{list-style:disc}
.sc-summary ol{list-style:decimal}
.sc-summary li{margin:2px 0}
.sc-summary li>*+*{margin-top:4px}
.sc-md-quote{padding-left:8px;border-left:2px solid var(--sc-edge);color:var(--sc-muted)}
.sc-md-hr{height:0;border:0;border-top:1px solid var(--sc-edge)}
.sc-md-pre{padding:6px 8px;border-radius:5px;background:rgba(151,191,209,.09);overflow:auto hidden;
  white-space:pre;scrollbar-width:thin;scrollbar-color:rgba(151,191,209,.28) transparent}
.sc-md-pre,.sc-md-code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:11px}
.sc-md-code{padding:0 3px;border-radius:3px;background:rgba(151,191,209,.13);white-space:pre-wrap}
.sc-md-link{color:#e6f4fa;text-decoration:underline;text-underline-offset:3px;
  text-decoration-color:color-mix(in srgb,var(--tone) 70%,transparent);border-radius:3px;cursor:pointer}
.sc-md-link:focus-visible{outline:1px solid var(--sc-ink);outline-offset:1px}
/* Liste bornée : la dernière ligne visible s'efface au lieu d'être coupée net. */
.sc-items{flex:none;list-style:none;margin:0;padding:8px 13px 11px;display:grid;gap:4px;border-top:1px solid var(--sc-edge);max-height:45%;overflow:hidden;
  -webkit-mask-image:linear-gradient(#000 calc(100% - 20px),transparent);mask-image:linear-gradient(#000 calc(100% - 20px),transparent)}
.sc-items.sc-fits{-webkit-mask-image:none;mask-image:none}
.sc-items li{display:flex;gap:10px;align-items:baseline;min-width:0;font-size:11px}
.sc-items .sc-item-label{min-width:0;flex:1 1 auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#dcecf4}
.sc-items .sc-item-ref{flex:none;max-width:45%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--sc-muted)}
/* Artefact (Slice 07) : vue d'inspection d'un résultat groupé. Le résumé cède la
   place aux entrées, qui défilent (molette, focus des liens) et s'effacent en
   bas tant qu'il en reste ; l'origine renvoie à l'étoile expliquée. */
.sc-cat-meta{flex:none;font-size:9.5px;letter-spacing:.06em;color:var(--sc-muted);font-variant-numeric:tabular-nums}
.sc-origin{flex:none;display:flex;align-items:center;gap:7px;min-width:0;max-width:calc(100% - 26px);margin:-3px 13px 9px;padding:2px 8px 2px 6px;
  border:0;border-radius:999px;background:rgba(151,191,209,.07);font:inherit;font-size:10.5px;line-height:1.5;color:var(--sc-muted);text-align:left;cursor:pointer;align-self:flex-start}
.sc-origin:hover{background:rgba(151,191,209,.14);color:var(--sc-ink)}
.sc-origin:focus-visible{outline:1px solid var(--sc-ink);outline-offset:1px}
.sc-origin[aria-disabled="true"]{cursor:default;background:transparent}
.sc-origin svg{flex:none;width:11px;height:11px;fill:none;stroke:currentColor;stroke-width:1.3;stroke-linecap:round;stroke-linejoin:round}
.sc-origin-dot{flex:none;width:6px;height:6px;border-radius:50%;background:var(--tone)}
.sc-origin-title{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#c5dae3}
.sc-origin-state{flex:none;color:var(--sc-muted)}
.sc-kind-artifact.sc-window .sc-summary{flex:0 0 auto;max-height:38%}
.sc-kind-artifact.sc-window .sc-items{flex:1 1 auto;max-height:none;min-height:0;align-content:start;overflow-y:auto;overscroll-behavior:contain;
  scrollbar-width:thin;scrollbar-color:rgba(151,191,209,.28) transparent}
/* Défilé jusqu'en bas : plus rien à annoncer, le fondu s'efface. */
.sc-items.sc-at-end,.sc-summary.sc-at-end{-webkit-mask-image:none;mask-image:none}
/* Résumé entier : pas de fondu sur sa dernière ligne. */
.sc-summary.sc-fits{-webkit-mask-image:none;mask-image:none}
.sc-items .sc-item-link{display:flex;gap:10px;align-items:baseline;flex:1 1 auto;min-width:0;color:#e6f4fa;text-decoration:none;border-radius:3px;cursor:pointer}
.sc-items .sc-item-link .sc-item-label{color:inherit}
.sc-items .sc-item-link:hover .sc-item-label{text-decoration:underline;text-decoration-color:color-mix(in srgb,var(--tone) 70%,transparent);text-underline-offset:3px}
.sc-items .sc-item-link:focus-visible{outline:1px solid var(--sc-ink);outline-offset:1px}
.sc-items .sc-item-out{flex:none;width:9px;height:9px;margin-left:-6px;color:var(--sc-muted);fill:none;stroke:currentColor;stroke-width:1.4;stroke-linecap:round;stroke-linejoin:round}
/* Hôte d'un lien (reprise QA M1) : d'abord, jamais rétréci ni coupé à droite ;
   raccourci par la gauche en JS (hostTail) quand la place manque. Le libellé
   et la référence, écrits par le cerveau, cèdent la place. */
.sc-items .sc-item-host{flex:none;overflow:hidden;white-space:nowrap;color:color-mix(in srgb,var(--tone) 55%,var(--sc-ink))}
/* Ligne étroite : l'hôte passe avant tout, l'icône décorative s'efface et l'hôte
   prend un corps plus petit pour montrer la plus longue fin possible. */
.sc-items li.sc-host-first .sc-item-out{display:none}
.sc-items li.sc-host-first .sc-item-host{font-size:10px;letter-spacing:-.01em}
/* La référence cède en premier, puis le libellé ; l'hôte, jamais. */
.sc-items .sc-item-link-ref{flex:0 100 auto;min-width:0;max-width:40%}
.sc-ccat{flex:none;max-width:38%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:9px;letter-spacing:.1em;text-transform:uppercase;
  color:color-mix(in srgb,var(--tone) 72%,var(--sc-ink))}
.sc-link-artifact{stroke:color-mix(in srgb,var(--tone) 50%,transparent);stroke-dasharray:5 3}
/* Indicateurs : en bas à gauche, sur la ligne de l'indication vocale, hors de
   la zone de composition ; au-dessus du badge Barehands quand il est là.
   Le sélecteur du badge est celui du contrat Bare Hands
   (JarvisBarehandsContracts.DOM.badgeSelector) : une feuille de style ne peut
   pas le lire, un test refuse qu'il en diverge. */
.sc-status{position:absolute;left:18px;bottom:18px;z-index:2147483600;display:flex;flex-wrap:wrap-reverse;align-items:center;gap:6px;
  max-width:calc(50vw - 150px);pointer-events:none}
body:has(#jarvisHands .jh-badge) .sc-status{bottom:52px}
.sc-status[hidden]{display:none}
.sc-note{display:flex;align-items:center;gap:8px;min-width:0;max-width:100%;padding:6px 12px 6px 10px;border-radius:999px;
  background:rgba(3,8,12,.7);box-shadow:inset 0 0 0 1px var(--sc-edge);backdrop-filter:blur(14px);
  font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:rgba(214,232,240,.82);white-space:nowrap}
.sc-note::before{content:'';flex:none;width:6px;height:6px;border-radius:50%;background:var(--sc-muted)}
.sc-note-main{min-width:0;overflow:hidden;text-overflow:ellipsis}
.sc-note-meta{flex:none;color:var(--sc-muted);font-variant-numeric:tabular-nums}
/* Indicateur actionnable (Slice 08) : masqués → liste, scène pleine → archivage. */
button.sc-note{pointer-events:auto;border:0;font:inherit;font-size:10px;letter-spacing:.08em;text-transform:uppercase;cursor:pointer;text-align:left}
button.sc-note:hover{background:rgba(10,24,32,.86);color:#eef6fa}
button.sc-note:focus-visible{outline:1px solid var(--sc-ink);outline-offset:2px}
button.sc-note .sc-note-meta{color:color-mix(in srgb,var(--sc-ink) 70%,var(--sc-muted))}
button.sc-note.sc-full .sc-note-meta{color:#ff9aa6}
.sc-note.sc-warn::before{background:var(--sc-warn)}
.sc-note.sc-full::before{background:#ff6b7d}
.sc-note.sc-busy::before{animation:sc-breathe 1.6s ease-in-out infinite;background:var(--sc-ink)}
.sc-sr{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
@keyframes sc-spin{to{transform:rotate(360deg)}}
@keyframes sc-breathe{0%,100%{opacity:.32;transform:scale(.86)}50%{opacity:.9;transform:scale(1.08)}}
@keyframes sc-alert{0%{opacity:.95;transform:scale(.62)}80%,100%{opacity:0;transform:scale(1.75)}}
/* Respiration d'un halo : lente, bornée, sans extinction ni éclat. */
@keyframes sc-glow{0%,100%{opacity:.58;transform:scale(.9)}50%{opacity:1;transform:scale(1.13)}}
@media(max-width:700px){.sc-status{left:10px;bottom:12px;max-width:calc(100vw - 90px)}}
@media(prefers-reduced-motion:reduce){
  .scene .sc-node{transition:none!important}
  .scene .sc-ring,.scene .sc-note::before,.scene .sc-node.sc-stopping .sc-ring{animation:none!important}
  /* Ni gravitation ni respiration : l'étoile garde sa lueur, immobile. */
  .scene .sc-orbit,.scene .sc-field,.scene .sc-mark::after{animation:none!important}
  .scene .sc-orbit{translate:none!important}
  .scene .sc-field{transform:none!important}
  .scene .sc-label{transition:none}
}`;

  /* Pictogrammes d'état d'exécution (indice secondaire, jamais la couleur). */
  const BADGE_PATHS={
    failed:'M3.5 3.5l5 5M8.5 3.5l-5 5',
    cancelled:'M3 6h6',
    interrupted:'M4.6 3.3v5.4M7.4 3.3v5.4',
    blocked:'M6 3v3.4M6 8.8v.2',
    completed:'M3.2 6.3l1.9 1.9 3.7-4.4',
    /* Slice 10 : point d'interrogation, étoile d'exécution seulement. */
    unknown:'M4.4 4.6a1.7 1.7 0 1 1 2.3 1.6c-.5.2-.7.6-.7 1.1v.3M6 9v.1',
  };
  const GRIP_PATH='M10.5 4.5l-6 6M10.5 8l-2.5 2.5';
  /* Artefact (Slice 07) : retour à l'étoile expliquée, lien qui s'ouvre ailleurs. */
  const ORIGIN_PATH='M2.5 2v3.5a2 2 0 0 0 2 2h6M8 5l2.5 2.5L8 10';
  const OUT_PATH='M5 2.5H2.5v7h7V7M6.5 2.5h3v3M9.5 2.5 5.5 6.5';
  const PIN_PATH='M7.5 1.5l3 3-2 1-2.2 2.2.4 2.3-1 1-2-2-2.7 2.7M3.7 6.3l-2-2 1-1 2.3.4L7.2 1.5';
  const REASONS={core_unreachable:'Core injoignable',not_configured:'scène non configurée',scene_unavailable:'scène indisponible',
    core_refused:'Core refuse la lecture',invalid_scene_response:'réponse invalide',timeout:'pas de réponse',
    patch_waits_busy:'trop de pages ouvertes',TypeError:'Control Center injoignable',network_error:'Control Center injoignable'};

  let enabled=false,root=null,linksEl=null,fieldEl=null,fixedEl=null,statusEl=null,liveEl=null,raf=0,statusTicker=null;
  let lastView=null,lastState=null,layout=null,layoutState=null,edgesSig='',statusSig='',announced='',readyTimer=0;
  let lastModel=null,focusId=null,tabStopId=null,statusFailed=false,visibilityToken=0,animTimer=0,driftTimer=0;
  /* Réglages d'affichage de l'utilisateur (ce navigateur), et la section des
     réglages qui les porte. `viewPrefs` vaut toujours des réglages complets,
     même quand la section n'est pas à l'écran. */
  let viewPrefs=V?V.normalize(null):null,viewSection=null,viewRows=[];
  /* Slice 08 : modifications optimistes, geste en cours, édition au clavier. */
  const pending=I?I.createPending():null;
  let viewMemo={state:null,version:-1,value:null},gesture=null,keyEdit=null,kbdMenuAt=0,pruneTimer=0;
  /* Dernier tour calculé, `null` quand rien ne tourne vraiment (gravitation
     éteinte, scène trop peuplée, mouvement réduit) : le rendu le pose, la
     tenue d'un objet le lit pour passer du dessin à la place enregistrée. */
  let lastField=null;
  /* Reprise QA : sélection (poignée visible), focus à rendre après un retrait,
     étoiles en cours d'arrêt, délai réel d'un arrêt (lu dans `/api/status`). */
  let selectedId=null,pendingFocus=null,jobCancelTimeoutS=null,serverMemo={state:null,value:null},actionLiveEl=null;
  /* Sélection, dans l'ordre d'entrée. `selectedId` en est la dernière : c'est
     l'ancre du menu, des flèches et du focus — un seul objet à la fois y répond,
     et c'est très bien ainsi. Le rectangle et le Ctrl-clic, eux, en tiennent
     plusieurs (demande du 19/09/2026). */
  let selection=[],band=null;
  const stopping=new Map();
  const actionStats={moves:0,resizes:0,representations:0,visibility:0,pins:0,archives:0,bulkArchives:0,stops:0,menus:0,refused:0,failed:0,rolledBack:0};
  const inflight=new Set();
  const freshUntil=new Map();
  const nodes=new Map();
  /* Fils dessinés (`{edge,line}`, dans l'ordre de `applyEdges`) et nœud tenu
     par l'utilisateur dont ils suivent le mouvement, image par image.
     `mixedLines` : ceux dont un seul bout tourne, renoués à chaque image
     (`turnEdges`) ; `turning` porte leur boucle. */
  let edgeLines=[],follow=null,mixedLines=[],turning=0;
  /* Le champ tourne-t-il vraiment ? (gravitation allumée, champ calculé, scène
     pas trop peuplée) : la boucle des fils mixtes ne s'allume que pour cela. */
  let fieldMoving=false;
  /* Nœuds tout juste lâchés : leur transition reste coupée jusqu'à l'image qui
     suit la pose de leur nouvelle place. */
  const settling=new Set();
  /* Nœuds tenus, **avec le nombre de mains** qui les tiennent — souris,
     Bare Hands, clavier. Un compteur par nœud : la première main qui lâche un
     objet que le clavier tient encore ne le relâche pas sous lui. */
  const holding=new Map();
  /* Retour d'un onglet caché : le prochain rendu pose les places sans
     transition (`sc-resync`). */
  let resyncPending=false;
  /* Champ immobile ou non au dernier rendu : sert à resynchroniser les
     animations de la rotation quand il repart (`syncField`). */
  let fieldFrozen=null;
  const leader={held:false,mode:'lock'};
  const channel=typeof BroadcastChannel==='function'?new BroadcastChannel(CHANNEL_NAME):null;
  const shared=!!channel&&!!(navigator.locks&&typeof navigator.locks.request==='function');
  const SNAPSHOT_TIMEOUT=Core.SNAPSHOT_TIMEOUT_MS;

  function consoleLog(level,event,data){
    try{(level==='error'?console.error:level==='warn'?console.warn:console.info)('[scène]',event,data||{})}catch(_error){/* console absente */}
  }

  async function requestJson(path,{signal,timeoutMs=SNAPSHOT_TIMEOUT,method='GET',body}={}){
    const controller=new AbortController();
    const relay=()=>controller.abort();
    if(signal){if(signal.aborted)controller.abort();else signal.addEventListener('abort',relay,{once:true})}
    let expired=false;
    const deadline=window.setTimeout(()=>{expired=true;controller.abort()},timeoutMs);
    try{
      const response=await fetch(path,{method,cache:'no-store',signal:controller.signal,
        headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});
      const text=await response.text();
      let json=null;
      try{json=text?JSON.parse(text):null}catch(_error){json=null}
      return {status:response.status,body:json};
    }catch(error){
      if(expired){const late=new Error(`pas de réponse en ${Math.round(timeoutMs/1000)} s`);late.code='timeout';throw late}
      throw error;
    }finally{
      window.clearTimeout(deadline);
      if(signal)signal.removeEventListener('abort',relay);
    }
  }

  async function getJson(path,options){
    const response=await requestJson(path,options);
    if(response.status!==200||!response.body){
      const error=new Error(response.body&&response.body.error&&response.body.error.message||`HTTP ${response.status}`);
      error.code=response.body&&response.body.error&&response.body.error.code||`http_${response.status}`;
      throw error;
    }
    return response.body;
  }

  const timers={setTimeout:(fn,ms)=>window.setTimeout(fn,ms),clearTimeout:id=>window.clearTimeout(id)};
  /* Seul le meneur du verrou Web Locks, visible, scène allumée, répond (décision PM).
     Déclaré avant la boucle qui lui remet les demandes. */
  const capturer=Capture?Capture.createCaptureResponder({now:()=>Date.now(),
    isLeader:()=>leader.held&&leader.mode==='lock',isVisible:()=>document.visibilityState!=='hidden',isEnabled:()=>enabled,
    render:renderCapture,upload:uploadCapture,log:consoleLog}):null;
  const loop=Core.createSceneLoop({client:Client,request:getJson,...timers,now:()=>Date.now(),random:Math.random,
    createAbort:()=>new AbortController(),onUpdate:onLoopUpdate,log:consoleLog,
    broadcast:channel?message=>channel.postMessage({...message,from:TAB_ID}):null,
    onCapture:request=>{if(capturer)capturer.offer(request)}});
  const committer=Core.createResolverCommitter({layout:L,...timers,now:()=>Date.now(),random:Math.random,log:consoleLog,
    post:command=>requestJson('/api/scene/commands',{method:'POST',body:command,timeoutMs:15000})});

  if(channel)channel.addEventListener('message',event=>{
    const message=event.data;
    if(!enabled||!message||message.from===TAB_ID)return;
    try{loop.receive(message)}catch(error){consoleLog('error','scene.receive_failed',{error:String(error&&error.message||error)})}
  });

  /* ------------------------------------------------------------ meneur */

  function pushCommitter(){
    if(!enabled||!lastView)return committer.update(null);
    /* Seulement en long-poll sain : pendant une relecture, l'état tenu peut
       être périmé et un objet déjà placé ailleurs paraître libre. */
    const healthy=!!lastView.state&&lastView.health.level==='ok'&&lastView.phase==='polling'&&lastView.role!=='follower';
    /* Disposition de l'état tenu, jamais de l'état dessiné : une place libérée
       seulement par une modification optimiste (qui peut être refusée) n'est
       jamais validée par le résolveur (reprise QA, MAJOR-2). */
    committer.update({state:lastView.state,layout:serverLayout(),leader:leader.held,healthy});
  }

  /* Rôle de l'onglet visible : meneur si le verrou est libre, sinon suiveur en
     file d'attente (le navigateur lui passe le verrou dès que le meneur le
     rend : fermeture, onglet caché, interrupteur éteint, navigation). La
     promesse rendue se résout quand le rôle est connu. Sans Web Locks ou
     BroadcastChannel : `solo`, long-poll par onglet. */
  const leadership=shared?Core.createLeadership({locks:navigator.locks,name:LOCK_NAME,createAbort:()=>new AbortController(),log:consoleLog,
    isVisible:()=>document.visibilityState!=='hidden',isEnabled:()=>enabled,
    onRole:role=>{leader.held=role==='leader';leader.mode='lock';loop.setRole(role);pushCommitter()}}):null;

  function decideRole(){
    if(!shared){
      leader.held=true;leader.mode='solo';loop.setRole('solo');
      return Promise.resolve();
    }
    return leadership.decide();
  }

  function releaseLeadership(){
    if(shared){leadership.release();leader.held=false;loop.setRole('follower')}
    else leader.held=false;
  }

  /* ------------------------------------------------------------ rendu */

  /* ------------------------------------ affichage réglé par l'utilisateur */

  /* Taille des étoiles, halo, gravitation, fils : réglés dans Réglages →
     Apparence, sous la version Cosmos, et enregistrés dans ce navigateur. Rien
     ne part vers Core : la scène enregistrée, la capture et ce que voit le
     cerveau ne changent pas. Les autres onglets suivent par `storage`. */

  /* Réglages enregistrés. Stockage refusé (navigation privée, site bloqué) :
     les valeurs de référence, sans erreur. */
  function loadViewPrefs(){
    if(!V)return null;
    let text=null;
    try{text=window.localStorage.getItem(V.KEY)}catch(_error){/* stockage refusé : les défauts */}
    return V.decode(text);
  }

  function saveViewPrefs(){
    if(!V)return;
    try{window.localStorage.setItem(V.KEY,V.encode(viewPrefs))}
    catch(error){consoleLog('warn','scene.view_not_saved',{error:errorText(error)})}
  }

  /* Ce que les réglages changent dans le dessin : des variables CSS et des
     classes sur le conteneur — effet immédiat, sans attendre un rendu — puis la
     dérive orbitale, recalculée au rendu suivant. */
  function applyViewPrefs(){
    if(!root||!V)return;
    const vars=V.cssVars(viewPrefs);
    for(const name of Object.keys(vars))root.style.setProperty(name,vars[name]);
    const on=new Set(V.classes(viewPrefs));
    for(const name of V.CLASSES)root.classList.toggle(name,on.has(name));
    scheduleRender();
  }

  /* Un autre onglet a réglé l'affichage : le même écran partout. */
  /* `root` n'est plus exigé : la section des réglages doit suivre l'autre
     onglet même quand la scène est éteinte ici. */
  function onViewStorage(event){
    if(!V||(event.key!==null&&event.key!==V.KEY))return;
    viewPrefs=loadViewPrefs();
    applyViewPrefs();syncViewPanel();
  }

  /* ------------------------------------------------------------------
     Où ces réglages se règlent : Réglages → Apparence (2026-09-20).

     Ils tenaient jusqu'ici dans une fenêtre ouverte par un bouton en bas à
     droite de la scène. L'utilisateur les a voulus là où vivent les autres
     réglages, sous la version Cosmos ; le bouton flottant a disparu avec la
     fenêtre. Ce qui ne change pas : ce sont toujours des préférences
     **d'affichage**, propres à ce navigateur, appliquées à chaud.

     Deux conséquences de ce déménagement, qui expliquent le code plus bas :
     - la section vit dans le modal, hors de `#sceneLayer` : elle doit donc
       exister **même scène éteinte**, sans dépendre de `root`, et porter son
       propre style (celui de la scène n'est posé qu'avec la scène) ;
     - elle a sa propre région vivante : `announce` écrit dans la scène, qui
       peut ne pas être là. */

  /* Style de la section, posé une fois et indépendamment de la scène : il
     emprunte les jetons du Control Center (`--line`, `--muted`, `--accent`) et
     non ceux de `.scene`, qui ne sont pas résolus dans le modal. */
  const VIEW_SETTINGS_STYLE=`#sceneViewSettings{margin-top:4px}
#sceneViewSettings .sc-view-row{display:grid;grid-template-columns:1fr auto;align-items:center;gap:4px 10px;padding:9px 0;border-top:1px solid var(--line)}
#sceneViewSettings .sc-view-row label{font-size:12px;color:var(--text);cursor:pointer}
#sceneViewSettings .sc-view-val{font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-variant-numeric:tabular-nums}
#sceneViewSettings .sc-view-row input[type=range]{grid-column:1 / -1;width:100%;height:14px;margin:0;accent-color:var(--accent);cursor:pointer}
#sceneViewSettings .sc-view-row input[type=checkbox]{width:16px;height:16px;margin:0;accent-color:var(--accent);cursor:pointer}
#sceneViewSettings .sc-view-row input:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
/* Réglage sans effet tant que celui dont il dépend est éteint : grisé, jamais
   oublié — il reprend sa valeur au rallumage. */
#sceneViewSettings .sc-view-row.sc-off{opacity:.42}
#sceneViewSettings .sc-view-foot{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:12px;padding-top:12px;border-top:1px solid var(--line)}
#sceneViewSettings button.sc-view-reset{border:1px solid var(--line);border-radius:999px;padding:6px 13px;background:rgba(151,191,209,.08);color:var(--text);
  font:inherit;font-size:10px;letter-spacing:.08em;text-transform:uppercase;cursor:pointer}
#sceneViewSettings button.sc-view-reset:hover:not(:disabled){background:rgba(151,191,209,.18)}
#sceneViewSettings button.sc-view-reset:disabled{opacity:.4;cursor:default}
#sceneViewSettings .sc-view-note{font-size:10px;line-height:1.5;color:var(--muted);text-align:right;flex:1 1 auto}
#sceneViewSettings .sc-view-live{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
@media(max-width:560px){#sceneViewSettings .sc-view-foot{flex-direction:column;align-items:stretch}
  #sceneViewSettings .sc-view-note{text-align:left}}`;

  function ensureViewSettingsStyle(){
    if(document.getElementById('jarvisSceneViewStyle'))return;
    const style=document.createElement('style');
    style.id='jarvisSceneViewStyle';style.textContent=VIEW_SETTINGS_STYLE;
    document.head.appendChild(style);
  }

  /* Région vivante de la section : la scène peut être éteinte, et sa propre
     région n'existe alors pas. Tant que la section est à l'écran, c'est elle
     qui parle ; sinon on retombe sur celle de la scène. */
  function announceView(text){
    const live=viewSection&&viewSection.isConnected?viewSection.querySelector('.sc-view-live'):null;
    if(!live){announce(text);return}
    if(live.textContent===text)live.textContent='';
    live.textContent=text;
  }

  /* La section telle qu'elle apparaît dans Réglages → Apparence. Reconstruite
     à chaque rendu de l'onglet : elle ne survit pas à la fermeture du modal et
     n'a donc jamais à se rattraper toute seule. */
  function buildViewSection(){
    if(!V)return null;
    const section=document.createElement('section');
    section.id='sceneViewSettings';
    section.setAttribute('aria-labelledby','sceneViewTitle');
    const title=element('h3','','Étoiles et orbites');
    title.id='sceneViewTitle';
    const lead=element('div','hint','La constellation que dessine la version Cosmos : taille des étoiles, halo, gravitation, fils entre les objets. Chaque changement s\'applique immédiatement.');
    lead.style.marginBottom='14px';
    const note=element('div','sc-view-note','Ce navigateur seulement : ni la scène enregistrée ni ce que voit le cerveau ne changent.');
    note.id='sceneViewNote';
    const live=element('div','sc-view-live');
    live.setAttribute('role','status');live.setAttribute('aria-live','polite');
    section.append(title,lead);
    viewRows=V.FIELDS.map(field=>{
      const row=element('div','sc-view-row');
      row.title=field.hint;
      const input=document.createElement('input');
      input.id=`scView_${field.id}`;
      input.setAttribute('aria-describedby','sceneViewNote');
      const label=element('label','',field.label);
      label.htmlFor=input.id;
      const value=element('span','sc-view-val');
      if(field.type==='toggle'){
        input.type='checkbox';
        row.append(label,input);
      }else{
        input.type='range';
        input.min=String(field.min);input.max=String(field.max);input.step=String(field.step);
        row.append(label,value,input);
      }
      /* `input` applique pendant le glissement (le réglage se voit tout de
         suite sur la scène derrière le modal) ; `change` seul est journalisé et
         annoncé, une fois posé. */
      input.addEventListener('input',()=>setViewField(field,field.type==='toggle'?input.checked:Number(input.value)));
      input.addEventListener('change',()=>{
        announceView(V.changeSentence(field,viewPrefs[field.id]));
        consoleLog('info','scene.view_changed',{field:field.id,value:viewPrefs[field.id]});
      });
      section.append(row);
      return {field,row,input,value};
    });
    const reset=element('button','sc-view-reset','Réinitialiser');
    reset.type='button';
    reset.addEventListener('click',()=>{
      viewPrefs=V.normalize(null);
      saveViewPrefs();applyViewPrefs();syncViewPanel();
      announceView('Étoiles et orbites réinitialisées.');
      consoleLog('info','scene.view_reset',{});
    });
    const foot=element('div','sc-view-foot');
    foot.append(reset,note);
    section.append(foot,live);
    viewSection=section;
    syncViewPanel();
    return section;
  }

  function setViewField(field,value){
    if(!V)return;
    const next=Object.assign({},viewPrefs);
    next[field.id]=value;
    viewPrefs=V.normalize(next);
    saveViewPrefs();applyViewPrefs();syncViewPanel();
  }

  /* Valeurs, grisés et bouton « Réinitialiser » d'après les réglages courants.
     La section peut avoir été jetée avec le modal : on ne parle qu'à un nœud
     encore dans la page. */
  function syncViewPanel(){
    if(!viewSection||!viewSection.isConnected||!V)return;
    const model=V.describe(viewPrefs);
    model.rows.forEach((row,index)=>{
      const target=viewRows[index];
      if(!target)return;
      if(target.field.type==='toggle')target.input.checked=!!row.value;
      else{target.input.value=String(row.value);target.value.textContent=row.label}
      target.row.classList.toggle('sc-off',!row.enabled);
      /* Grisé mais jamais vidé : le réglage reprend sa valeur au rallumage. */
      target.input.disabled=!row.enabled;
    });
    const reset=viewSection.querySelector('.sc-view-reset');
    if(reset)reset.disabled=!model.custom;
  }

  /* Installation dans l'onglet Apparence. `control_center_work.js` dessine cet
     onglet en entier et est inséré **avant** ce fichier : son `setTimeout(0)`
     passe donc avant le nôtre, et l'onglet existe déjà quand on l'enveloppe.
     On attend son rendu, puis on ajoute la section à la suite des versions.

     L'écoute `storage` est posée ici, et non avec la scène : un autre onglet
     peut régler l'affichage alors que la scène est éteinte ici, et la section
     doit quand même montrer la bonne valeur. */
  function installViewSettings(){
    if(!V||typeof renderTab!=='function'||typeof TABS==='undefined'||!Array.isArray(TABS))return;
    ensureViewSettingsStyle();
    window.addEventListener('storage',onViewStorage);
    const baseRenderTab=renderTab;
    renderTab=async function(){
      const result=await baseRenderTab.apply(this,arguments);
      if(typeof SET!=='undefined'&&SET.open&&SET.tab==='appearance'){
        const content=document.getElementById('modalContent');
        if(content&&!content.querySelector('#sceneViewSettings')){
          viewPrefs=loadViewPrefs();
          const section=buildViewSection();
          if(section)content.append(section);
        }
      }
      return result;
    };
  }

  setTimeout(installViewSettings,0);

  function ensureRoot(){
    if(!document.getElementById('jarvisSceneStyle')){
      const style=document.createElement('style');
      style.id='jarvisSceneStyle';style.textContent=STYLE;
      document.head.appendChild(style);
    }
    if(root)return;
    root=document.createElement('div');
    root.id='sceneLayer';root.className='scene';
    if(!driftTimer)driftTimer=window.setInterval(checkFieldDrift,DRIFT_CHECK_MS);
    root.setAttribute('role','region');
    root.setAttribute('aria-label',I
      ?'Scène constellation. Flèches pour parcourir, Maj+flèches pour déplacer, Ctrl+flèches pour redimensionner, touche Menu ou Maj+F10 pour les actions, Échap pour sortir.'
      :'Scène constellation. Flèches pour parcourir, Échap pour sortir.');
    linksEl=document.createElementNS(SVG_NS,'svg');
    linksEl.setAttribute('class','sc-links');linksEl.setAttribute('aria-hidden','true');
    /* Les fils vivent dans un groupe à part : c'est lui qui tourne avec le
       champ, d'un bloc, autour du centre de la fenêtre. Il est créé une fois
       pour toutes — son animation ne repart donc jamais de zéro quand les fils
       sont redessinés, et reste en phase avec celle des nœuds. */
    fieldEl=document.createElementNS(SVG_NS,'g');
    fieldEl.setAttribute('class','sc-field');
    /* Second calque, celui-là **immobile** (21/09/2026) : les fils dont les deux
       bouts ne tournent pas (fenêtre ↔ fenêtre) et ceux dont un seul tourne.
       Les premiers n'ont rien à suivre ; les seconds sont renoués image par
       image par `turnEdges`, qui calcule la place du bout mobile au lieu de la
       confier à une rotation qui emporterait aussi le bout fixe. */
    fixedEl=document.createElementNS(SVG_NS,'g');
    fixedEl.setAttribute('class','sc-fixed');
    linksEl.append(fieldEl,fixedEl);
    statusEl=document.createElement('div');
    statusEl.className='sc-status';statusEl.hidden=true;
    /* Région vivante à part : annonce les changements d'état, jamais les
       compteurs qui défilent chaque seconde. */
    liveEl=document.createElement('div');
    liveEl.className='sc-sr';liveEl.setAttribute('role','status');liveEl.setAttribute('aria-live','polite');
    /* Seconde région vivante (Slice 08) : l'issue des actions de l'utilisateur
       (archivé, masqué, arrêt demandé), jamais écrasée par l'état de lecture. */
    actionLiveEl=document.createElement('div');
    actionLiveEl.className='sc-sr sc-sr-actions';actionLiveEl.setAttribute('role','status');actionLiveEl.setAttribute('aria-live','polite');
    root.append(linksEl,statusEl,liveEl,actionLiveEl);
    /* Réglages d'affichage : lus avant le premier dessin. Ils se règlent dans
       Réglages → Apparence, pas ici ; la scène ne fait que les appliquer. */
    if(V){viewPrefs=loadViewPrefs();applyViewPrefs()}
    root.addEventListener('keydown',onKeyDown);
    root.addEventListener('keyup',onKeyUp);
    root.addEventListener('pointerover',onPointerOver);
    root.addEventListener('focusin',onFocusIn);
    root.addEventListener('focusout',onFocusOut);
    root.addEventListener('scroll',onScroll,true);
    root.addEventListener('click',onInnerClick);
    if(I){
      root.addEventListener('pointerdown',onPointerDown);
      root.addEventListener('pointermove',onPointerMove);
      root.addEventListener('pointerup',onPointerUp);
      root.addEventListener('pointercancel',onPointerCancel);
      root.addEventListener('lostpointercapture',onPointerCancel);
      root.addEventListener('contextmenu',onContextMenu);
    }
    (document.getElementById('app')||document.body).appendChild(root);
  }

  function teardown(){
    if(raf){cancelAnimationFrame(raf);raf=0}
    if(readyTimer){cancelAnimationFrame(readyTimer);readyTimer=0}
    stopFollow();edgeLines=[];mixedLines=[];fieldMoving=false;settling.clear();holding.clear();fieldFrozen=null;resyncPending=false;
    stopStatusTicker();
    if(root)root.remove();
    const style=document.getElementById('jarvisSceneStyle');
    if(style)style.remove();
    if(animTimer){window.clearTimeout(animTimer);animTimer=0}
    if(driftTimer){window.clearInterval(driftTimer);driftTimer=0}
    root=null;linksEl=null;fieldEl=null;fixedEl=null;statusEl=null;liveEl=null;actionLiveEl=null;nodes.clear();freshUntil.clear();
    /* La section des réglages vit dans le modal : elle survit à la scène. */
    lastView=null;lastState=null;layout=null;layoutState=null;lastModel=null;
    viewMemo={state:null,version:-1,value:null};serverMemo={state:null,value:null};gesture=null;
    selectedId=null;selection=[];band=null;pendingFocus=null;stopping.clear();
    if(keyEdit&&keyEdit.timer)window.clearTimeout(keyEdit.timer);
    keyEdit=null;
    if(pruneTimer){window.clearTimeout(pruneTimer);pruneTimer=0}
    edgesSig='';statusSig='';announced='';focusId=null;tabStopId=null;
  }

  function scheduleRender(){
    if(!raf)raf=requestAnimationFrame(render);
  }

  /* Les places posées par ce rendu sont appliquées : à l'image suivante, les
     nœuds lâchés retrouvent leur transition. La retirer dans ce rendu-ci la
     remettrait en jeu au moment même où `transform` change — c'est-à-dire
     exactement l'excursion qu'on vient d'enlever. */
  function releaseSettling(){
    if(!settling.size)return;
    const held=[...settling];
    settling.clear();
    requestAnimationFrame(()=>{for(const el of held)el.classList.remove('sc-settling')});
  }

  /* État dessiné : l'état tenu plus les modifications de l'utilisateur pas
     encore confirmées par Core (affichage optimiste, Slice 08). */
  function viewState(){
    if(!lastState||!pending)return lastState;
    const version=pending.version();
    if(viewMemo.state!==lastState||viewMemo.version!==version)viewMemo={state:lastState,version,value:pending.overlay(lastState)};
    return viewMemo.value;
  }

  /* Disposition de l'état tenu (validations du résolveur). Sans modification
     en attente, c'est la disposition dessinée elle-même. */
  function serverLayout(){
    if(!lastState)return null;
    const drawn=viewState();
    if(drawn===lastState)return currentLayout();
    if(serverMemo.state!==lastState)serverMemo={state:lastState,value:I.commitLayout(lastState,drawn,null,L.resolveLayout)};
    return serverMemo.value;
  }

  /* Disposition calculée à la demande, une fois par état dessiné. */
  function currentLayout(){
    const state=viewState();
    if(!state)return null;
    if(layoutState!==state){layout=L.resolveLayout(state);layoutState=state}
    return layout;
  }

  function svgIcon(path,className){
    const svg=document.createElementNS(SVG_NS,'svg');
    svg.setAttribute('viewBox','0 0 12 12');svg.setAttribute('aria-hidden','true');
    if(className)svg.setAttribute('class',className);
    const shape=document.createElementNS(SVG_NS,'path');
    shape.setAttribute('d',path);svg.appendChild(shape);
    return svg;
  }

  function element(tag,className,text){
    const el=document.createElement(tag);
    if(className)el.className=className;
    if(text!==undefined)el.textContent=text;
    return el;
  }

  /* Un fragment de texte markdown (`JarvisSceneLayout.markdownSpans`) en nœuds
     DOM. Le texte passe par un nœud de texte, jamais par une chaîne de
     balisage : les marques viennent de la structure, pas d'un fragment de page
     recopié. `links` faux (un titre) : le libellé d'un lien reste du texte,
     sans ancre. */
  function spanNode(span,links){
    let node=document.createTextNode(span.text);
    const wrap=(tag,className)=>{const el=element(tag,className);el.appendChild(node);node=el};
    if(span.code)wrap('code','sc-md-code');
    if(span.italic)wrap('em');
    if(span.bold)wrap('strong');
    if(span.strike)wrap('s');
    if(span.href&&links!==false){
      wrap('a','sc-md-link');
      /* Même règle que l'entrée d'un artefact : `linkOf` a déjà refusé tout ce
         qui n'est pas http(s) sans identifiants ; nouvel onglet, sans `opener`
         ni référent, et hors tabulation tant que le focus n'est pas dedans. */
      node.href=span.href;node.target='_blank';node.rel='noopener noreferrer';
      node.referrerPolicy='no-referrer';node.tabIndex=-1;node.title=span.host||'';
    }
    return node;
  }

  function appendSpans(el,spans,links){
    for(const span of spans||[])el.appendChild(spanNode(span,links));
    return el;
  }

  /* Blocs markdown d'un résumé (`JarvisSceneLayout.markdownBlocks`) dans leur
     conteneur. Récursif : une entrée de liste et une citation portent des blocs
     à leur tour (la profondeur est déjà bornée par l'analyse). */
  function appendBlocks(parent,blocks){
    for(const block of blocks){
      if(block.kind==='hr'){parent.appendChild(element('hr','sc-md-hr'));continue}
      if(block.kind==='code'){
        const pre=element('pre','sc-md-pre');
        pre.appendChild(element('code',null,block.text));
        parent.appendChild(pre);continue;
      }
      if(block.kind==='h'){
        parent.appendChild(appendSpans(element('div',`sc-md-h sc-md-h${Math.min(3,block.level)}`),block.spans));
        continue;
      }
      if(block.kind==='quote'){
        const quote=element('blockquote','sc-md-quote');
        appendBlocks(quote,block.blocks);
        parent.appendChild(quote);continue;
      }
      if(block.kind==='list'){
        const list=element(block.ordered?'ol':'ul');
        if(block.ordered&&block.start>1)list.start=block.start;
        for(const item of block.items){
          const li=element('li');
          appendBlocks(li,item.blocks);
          list.appendChild(li);
        }
        parent.appendChild(list);continue;
      }
      parent.appendChild(appendSpans(element('p','sc-md-p'),block.spans));
    }
    return parent;
  }

  /* Icône d'état. Une fin (`completed`, `failed`) la porte sur toutes les
     formes, y compris l'étoile : c'est la petite icône de la marque de fin,
     avec l'anneau vert ou rouge. Un artefact `unknown` n'a pas de travail :
     pas de « ? ». */
  function badge(exec,restartUnknown){
    if(!BADGE_PATHS[exec]||(exec==='unknown'&&!restartUnknown))return null;
    const box=element('span','sc-badge');
    box.appendChild(svgIcon(BADGE_PATHS[exec]));
    return box;
  }

  /* Poignée de redimensionnement (coin bas droit), capsule et fenêtre. */
  function grip(){
    const box=element('span','sc-grip');
    box.setAttribute('aria-hidden','true');
    box.appendChild(svgIcon(GRIP_PATH));
    return box;
  }

  function pin(){
    const box=element('span','sc-pin');
    box.appendChild(svgIcon(PIN_PATH));
    return box;
  }

  /* Contenu d'un nœud, selon sa forme dessinée (`shape`, compacte quand la
     boîte est trop petite pour son texte). Tout texte de la scène passe par
     `textContent`, déjà neutralisé par `JarvisSceneLayout.viewModel`. */
  function fill(el,node){
    const classes=['sc-node',`sc-${node.shape}`,`sc-kind-${node.kind}`,`sc-tone-${node.tone}`,`sc-exec-${node.exec}`];
    if(node.restartUnknown)classes.push('sc-restart-unknown');
    /* Signal d'attention vivant sur cette étoile : sa marque de fin se retire
       d'un cran (voir la feuille de style). */
    if(node.alerted)classes.push('sc-alerted');
    if(node.signal)classes.push('sc-signal',`sc-urgency-${node.urgency}`);
    if(node.pinned)classes.push('sc-pinned');
    if(node.compact)classes.push('sc-compact');
    /* Le contenu seulement : les classes d'état (tenu, lâché, orbite,
       sélection…) restent — `L.nodeClassName`. */
    el.className=L.nodeClassName(classes,el.classList);
    el.setAttribute('aria-label',node.label);
    el.replaceChildren();
    const parts=[];
    if(node.shape==='point'){
      parts.push(element('span','sc-ring'),element('span','sc-mark'));
      const state=badge(node.exec,node.restartUnknown);
      if(state&&!node.signal)parts.push(state);
      const label=element('span','sc-label');
      label.append(appendSpans(element('strong'),node.titleSpans,false));
      const detail=[node.signal?'signal':'',node.execLabel,node.signal&&!node.live?'retiré':'',node.pinned?'épinglé':''].filter(Boolean).join(' · ');
      if(detail)label.append(element('span','',detail));
      parts.push(label);
    }else if(node.shape==='capsule'){
      const dot=element('span','sc-dot');dot.appendChild(element('span','sc-ring'));
      parts.push(dot);
      /* Artefact : sa catégorie (sa couleur) avant son titre. */
      if(node.kind==='artifact'&&node.category)parts.push(element('span','sc-ccat',node.category));
      parts.push(appendSpans(element('span','sc-title'),node.titleSpans,false));
      if(node.pinned)parts.push(pin());
      const state=badge(node.exec,node.restartUnknown);if(state)parts.push(state);
      if(I&&(node.representation==='capsule'||node.representation==='window'))parts.push(grip());
    }else{
      const head=element('div','sc-head');
      const dot=element('span','sc-dot');dot.appendChild(element('span','sc-ring'));
      head.append(dot,element('span','sc-cat',[node.category,node.execLabel].filter(Boolean).join(' · ')));
      if(node.kind==='artifact'&&node.itemCount)head.append(element('span','sc-cat-meta',`${node.itemCount} ${node.itemCount>1?'entrées':'entrée'}`));
      if(node.pinned)head.append(pin());
      const state=badge(node.exec,node.restartUnknown);if(state)head.append(state);
      parts.push(head,appendSpans(element('div','sc-wtitle'),node.titleSpans,false));
      if(node.explains)parts.push(originButton(node.explains));
      if(node.summary){
        /* Comme la liste d'un artefact : un conteneur qui défile deviendrait un
           arrêt de tabulation sans nom (Chrome). Hors tabulation, il défile à la
           molette et par PageHaut/PageBas depuis la fenêtre. */
        const summary=element('div','sc-summary');summary.tabIndex=-1;
        appendBlocks(summary,L.markdownBlocks(node.summary));
        parts.push(summary);
      }
      if(node.items.length){
        /* Un conteneur qui défile deviendrait un arrêt de tabulation sans nom
           (Chrome) : hors tabulation, défilement par PageHaut/PageBas depuis la
           fenêtre, ou par le focus des liens. */
        const list=element('ul','sc-items');list.tabIndex=-1;
        for(const item of node.items)list.append(itemRow(item));
        parts.push(list);
      }
      if(I)parts.push(grip());
    }
    el.append(...parts);
  }

  /* Origine d'un artefact : bouton qui sélectionne l'étoile expliquée (masquée :
     annoncé, inerte). Hors tabulation tant que le focus n'est pas dans la
     fenêtre (`setInnerTabs`). */
  function originButton(target){
    const button=element('button','sc-origin');
    button.type='button';button.tabIndex=-1;button.dataset.target=target.id;
    const dot=element('span',`sc-origin-dot sc-tone-${target.tone}`);
    button.append(svgIcon(ORIGIN_PATH),dot,element('span','sc-origin-title',target.title));
    const state=[target.kindLabel,target.execLabel,target.hidden?'masqué':''].filter(Boolean).join(' · ');
    if(state)button.append(element('span','sc-origin-state',state));
    if(target.hidden)button.setAttribute('aria-disabled','true');
    button.setAttribute('aria-label',target.hidden?`Explique « ${target.title} » (masqué)`:`Aller à « ${target.title} », ${state}`);
    return button;
  }

  /* Entrée d'artefact. Lien seulement pour une URL validée par
     `JarvisSceneLayout.linkOf` (http/https, sans identifiants) ; nouvel onglet,
     sans `opener` ni référent ; l'hôte est écrit à côté du libellé. Sinon, du
     texte. Tout texte passe par `textContent`. */
  function itemRow(item){
    const row=element('li');
    const href=typeof item.href==='string'&&/^https?:\/\//.test(item.href)?item.href:'';
    if(href){
      /* L'hôte d'abord, dans le lien : aucune longueur de libellé ou de référence
         ne le pousse hors de vue, et une ligne étroite garde un lien cliquable
         même quand le libellé a disparu (reprise QA N1). */
      const host=element('span','sc-item-host',item.host);
      host.dataset.host=item.host;host.setAttribute('aria-hidden','true');
      const link=element('a','sc-item-link');
      link.append(host);
      if(item.label)link.append(element('span','sc-item-label',item.label));
      link.href=href;link.target='_blank';link.rel='noopener noreferrer';link.referrerPolicy='no-referrer';link.tabIndex=-1;
      link.title=item.host;
      link.setAttribute('aria-label',`${item.label||item.host} — ${item.host}, s’ouvre dans un nouvel onglet`);
      row.append(link,svgIcon(OUT_PATH,'sc-item-out'));
      if(item.ref)row.append(element('span','sc-item-ref sc-item-link-ref',item.ref));
    }else{
      row.append(element('span','sc-item-label',item.label));
      if(item.ref||item.url)row.append(element('span','sc-item-ref',item.ref||item.url));
    }
    return row;
  }

  /* Liens et bouton d'origine d'un nœud : dans la tabulation seulement quand le
     focus est dans ce nœud, pour garder un seul arrêt de tabulation dans la scène. */
  function setInnerTabs(el,on){
    for(const inner of el.querySelectorAll('.sc-item-link,.sc-origin,.sc-md-link'))inner.tabIndex=on?0:-1;
  }

  /* Placement d'un nœud : `L.drawnRect`, la même règle que la capture (reprise QA M2).
     Le tour du champ s'ajoute par-dessus, dans la propriété `translate`
     (`markOrbit`) : il ne touche ni au placement dessiné, ni à la géométrie de
     la scène, ni à la capture. */
  function position(el,node,field){
    const rect=L.drawnRect(node);
    el.style.transform=`translate(${rect.left}px,${rect.top}px)`;
    el.style.width=node.shape==='point'?'':`${rect.width}px`;
    el.style.height=node.shape==='point'?'':`${rect.height}px`;
    el.style.zIndex=String(node.stack);
    applyOrbit(el,node,field);
    /* Respiration du halo décalée par la place de l'étoile : stable d'un rendu
       à l'autre, et tous les halos ne battent pas ensemble. */
    if(node.shape==='point')el.style.setProperty('--sc-glow-delay',`${glowDelay(node)}ms`);
  }

  /* L'orbite de ce nœud : son rayon et sa phase, qui sont à lui, puis la classe
     qui déclenche l'animation commune. Un nœud qui ne tourne pas
     (`L.orbitHolds` : fenêtre, ou tour qui ne tiendrait pas dans la zone sûre)
     n'en a pas ; l'ampleur peut encore le rapprocher du centre, d'un décalage
     fixe (`L.orbitRest`). Reposer une place ne relance rien (la classe est déjà
     là) : le nœud suit sa nouvelle place sans perdre la phase du champ. Le
     champ, lui, est arrêté ou non par le conteneur. */
  function applyOrbit(el,node,field){
    /* Objet tenu : son décalage reste celui qu'il avait à la prise (`sc-held`,
       `translate` figé) — c'est à lui que la tenue ajoute la main. */
    if(el.classList.contains('sc-dragging'))return;
    /* Lâché et reposé : il reprend son tour **dans ce même appel**, à l'heure
       murale — jamais une image où l'animation repartirait de zéro. */
    el.classList.remove('sc-held');
    const track=L.orbitTrack(node,field);
    if(!track){
      el.classList.remove('sc-orbit');
      const rest=L.orbitRest(node,field);
      el.style.animationDelay='';el.style.translate=rest?`${rest.x}px ${rest.y}px`:'';
      return;
    }
    el.style.translate='';
    el.style.setProperty('--sc-orbit-rx',`${track.rx}px`);
    el.style.setProperty('--sc-orbit-ry',`${track.ry}px`);
    el.style.setProperty('--sc-orbit-dx',`${track.dx}px`);
    el.style.setProperty('--sc-orbit-dy',`${track.dy}px`);
    el.style.animationDelay=`${track.delayMs}ms`;
    if(el.classList.contains('sc-orbit'))syncOrbit(el);else markOrbit(el);
  }

  function markOrbit(el){
    if(!el||el.classList.contains('sc-orbit'))return;
    el.classList.add('sc-orbit');
    syncOrbit(el);
  }

  /* Toutes les animations de la rotation partagent l'origine du temps du
     document : un nœud qui apparaît, un nœud dont `fill` a réécrit les classes
     ou le calque des fils reprend le champ exactement là où il est, jamais au
     début de son propre cycle. Sans cela, deux animations lancées à dix
     secondes d'écart tourneraient en opposition et les fils décrocheraient.
     Appelé au moment où la classe est posée, jamais à chaque image. */
  function syncOrbit(el){
    if(!el||!el.getAnimations)return;
    const now=fieldClock();
    try{
      for(const anim of el.getAnimations()){
        if(anim.animationName!=='sc-orbit'&&anim.animationName!=='sc-orbit-field')continue;
        if(Number(anim.currentTime)!==now)anim.currentTime=now;
      }
    }catch(_error){/* animation sans horloge (page cachée) : la passe suivante réessaie. */}
  }

  /* L'horloge du champ, en millisecondes dans la période : **l'heure murale**
     (`L.orbitTurnAt(Date.now())`), calculée, jamais lue dans le DOM. Elle se
     lisait sur l'animation du calque des fils, qui n'en a plus quand les fils
     sont masqués (`display:none`) : l'angle retombait à zéro sous des étoiles
     qui tournaient, et l'objet lâché sautait de 64 à 216 px. Murale, elle donne
     aussi le même dessin d'un chargement et d'un onglet à l'autre. */
  function fieldClock(){
    return lastField?L.orbitTurnAt(Date.now(),lastField)*lastField.ms:0;
  }

  /* Champ arrêté puis relancé (scène trop peuplée, réglage de l'utilisateur,
     premier rendu) : le conteneur relance d'un coup toutes les animations,
     chacune avec sa propre origine — elles sont donc toutes remises à l'heure
     murale. Rien à faire à l'arrêt. */
  function syncField(frozen){
    if(frozen===fieldFrozen)return;
    fieldFrozen=frozen;
    if(!frozen)syncFieldToWall();
  }

  /* Remettre toutes les animations du tour à l'heure murale : le calque des
     fils, puis chaque nœud (un nœud tenu n'a pas d'animation, `sc-held`). Au
     premier rendu, au retour d'un onglet caché, et à chaque prise — l'horloge
     du document et l'horloge murale peuvent diverger (veille de la machine),
     et la tenue calcule le décalage de l'objet pris sur la seconde. */
  function syncFieldToWall(){
    if(!lastField)return;
    const now=fieldClock();
    if(fieldEl&&fieldEl.getAnimations)try{
      for(const anim of fieldEl.getAnimations())
        if(anim.animationName==='sc-orbit-field')anim.currentTime=now;
    }catch(_error){/* animation sans horloge (calque masqué, page cachée) : la passe suivante réessaie. */}
    for(const record of nodes.values())syncOrbit(record.el);
  }

  /* **Garde de dérive** : l'horloge du document — celle des animations — peut
     prendre du retard sur l'horloge murale (onglet ralenti par le navigateur,
     machine en veille). Toutes les deux secondes, l'heure d'une animation du
     tour est comparée à l'heure murale ; au-delà de 30 ms d'écart, tout est
     remis à l'heure. Sans dérive, rien ne bouge. */
  const DRIFT_CHECK_MS=2000,DRIFT_MAX_MS=30;
  function checkFieldDrift(){
    if(!root||!lastField||document.visibilityState==='hidden')return;
    const el=fieldEl&&fieldEl.getAnimations&&fieldEl.getAnimations().length?fieldEl:root.querySelector('.sc-orbit');
    if(!el||!el.getAnimations)return;
    try{
      for(const anim of el.getAnimations()){
        if(anim.animationName!=='sc-orbit'&&anim.animationName!=='sc-orbit-field')continue;
        const ms=lastField.ms,gap=Math.abs(((Number(anim.currentTime)-fieldClock())%ms+ms*1.5)%ms-ms/2);
        if(gap>DRIFT_MAX_MS){consoleLog('info','scene.field_resynced',{drift_ms:Math.round(gap)});syncFieldToWall()}
        return;
      }
    }catch(_error){/* animation sans horloge (page cachée) : la passe suivante réessaie. */}
  }

  function glowDelay(node){
    const seed=Math.abs(Math.round(node.cx)*31+Math.round(node.cy)*17)%97;
    return -Math.round(seed/97*GLOW_MS);
  }

  function applyNodes(list,field){
    const seen=new Set(),chosen=new Set(selection);
    /* Le champ entre dans la clé de placement : une fenêtre redimensionnée
       change le centre et le resserrement, donc l'orbite de chaque objet, sans
       qu'aucune place ait bougé. */
    const shape=field?`${field.cx}|${field.cy}|${field.scale}|${field.ms}`:'';
    for(const node of list){
      seen.add(node.id);
      let record=nodes.get(node.id);
      if(!record){
        const el=document.createElement('div');
        el.tabIndex=-1;el.dataset.objectId=node.id;el.setAttribute('role','group');
        root.appendChild(el);
        record={el,content:'',place:'',anim:null};
        nodes.set(node.id,record);
      }
      const content=JSON.stringify([node.shape,node.kind,node.tone,node.exec,node.urgency,node.pinned,node.titleSpans,
        node.category,node.summary,node.items,node.label,node.itemCount,node.explains,node.alerted]);
      if(content!==record.content){
        const inside=record.el.contains(document.activeElement);
        fill(record.el,node);record.content=content;record.anim=null;
        /* `fill` réécrit `className` en entier : la classe de gravitation est
           tombée avec le reste. La place n'ayant pas bougé, rien ne la
           reposerait — l'étoile s'arrêterait d'orbiter dès son premier
           changement d'état. On oublie donc la place connue pour que le
           placement ci-dessous refasse une passe complète. */
        record.place='';
        if(inside){setInnerTabs(record.el,true);record.el.focus({preventScroll:true})}
      }
      /* Métadonnée sémantique lue par Bare Hands (Slice 05) : quelles zones de
          manipulation cet objet accepte. Elle est posée ici, et non déduite des
          classes, parce que la classe porte la forme **dessinée** (sc-capsule,
          sc-point), qui retombe quand la place manque : une fenêtre dessinée en
          capsule, ou une capsule dessinée en point, perdraient leurs zones sans
          que leur géométrie ait changé. Elle est posée à chaque passe et non
          dans fill(), dont la mémoire de contenu ne regarde pas la
          représentation : un changement de representation à forme dessinée
          constante ne rappellerait pas fill(). */
      if(record.el.dataset.representation!==node.representation)
        record.el.dataset.representation=node.representation;
      if(record.anim!==node.animate){record.el.classList.toggle('sc-anim',node.animate);record.anim=node.animate}
      record.el.classList.toggle('sc-selected',chosen.has(node.id));
      record.el.classList.toggle('sc-stopping',stopping.has(node.id));
      const place=`${node.shape}|${node.compact}|${node.cx}|${node.cy}|${node.box.left}|${node.box.top}|${node.box.width}|${node.box.height}|${node.stack}|${shape}`;
      /* Sous la main de l'utilisateur (glisser, clavier) : l'aperçu garde la
         place — c'est le geste qui pose le placement, image par image. */
      if(place!==record.place&&!record.dragging){position(record.el,node,field);record.place=place}
    }
    for(const [id,record] of nodes){
      if(seen.has(id))continue;
      record.el.remove();nodes.delete(id);
      /* Un objet tenu qui disparaît (archivé ailleurs, masqué par le cerveau)
         n'est plus compté comme tenu. */
      if(holding.delete(id))syncHolding();
      /* …ni une tenue qui ne peut plus le poser : Bare Hands le rend. */
      if(barehandsHeld.delete(id))consoleLog('warn','scene.barehands_hold_lost',{object_id:id});
    }
    markItemsThatFit();
    updateTabStop(list);
    restorePendingFocus();
  }

  /* Après un retrait (archivage, masquage) ou un réaffichage : la sélection va
     à l'objet prévu dès qu'il est dessiné (2 s au plus). */
  function restorePendingFocus(){
    if(!pendingFocus)return;
    if(Date.now()-pendingFocus.at>2000){pendingFocus=null;return}
    const record=pendingFocus.id&&nodes.get(pendingFocus.id);
    if(!pendingFocus.id){pendingFocus=null;return}
    if(!record)return;
    const id=pendingFocus.id;pendingFocus=null;
    focusId=id;select(id);
    updateTabStop(lastModel?lastModel.nodes:[]);
    if(!(typeof CONFIRM==='object'&&CONFIRM&&CONFIRM.resolve))record.el.focus({preventScroll:true});
  }

  /* Liste d'éléments entière : pas de fondu. */
  function markItemsThatFit(){
    fitHosts();
    for(const summary of root.querySelectorAll('.sc-summary')){
      summary.classList.toggle('sc-fits',summary.scrollHeight<=summary.clientHeight+1);
      markScrolledToEnd(summary);
    }
    for(const list of root.querySelectorAll('.sc-items')){
      list.classList.toggle('sc-fits',list.scrollHeight<=list.clientHeight+1);
      markScrolledToEnd(list);
    }
  }

  /* **`fitWindowHeights` a été retiré le 21/09/2026.** Il mesurait le contenu
     d'une fenêtre après le rendu et redessinait l'enveloppe à
     `min(hauteur demandée, hauteur du contenu)`, sans toucher à la géométrie :
     une fenêtre de 300×200 dont le texte occupait 110 px se dessinait 300×110
     tout en restant 300×200 pour la scène. Deux rectangles pour un seul objet,
     et tout ce qui suit en découlait :

     - la poignée était au bas du petit rectangle, le calcul du
       redimensionnement partait du grand : **agrandir une fenêtre en hauteur
       ne faisait rien de visible** tant que la taille demandée dépassait celle
       du contenu, et seul le sens « réduire sous le contenu » répondait ;
     - la mesure était mémorisée par `fitKey` (hauteur de boîte, largeur,
       contenu), qu'un *déplacement* ne change pas : la fenêtre grandissait à la
       prise (l'aperçu reposant la hauteur pleine) et **restait** grande, alors
       qu'un redimensionnement, lui, la rabotait de nouveau. Le même objet avait
       donc deux hauteurs selon son histoire ;
     - les fils visaient le centre de la boîte enregistrée, c'est-à-dire un
       point qui pouvait être hors du rectangle visible.

     Le contenu se débrouille désormais **à l'intérieur** du rectangle demandé :
     le résumé et la liste défilent déjà (`.sc-summary`, `.sc-items`), et une
     fenêtre plus grande que son texte garde simplement du vide en bas. C'est ce
     que l'utilisateur a demandé en posant cette taille. */

  /* Hôtes des liens : entiers s'ils tiennent, sinon raccourcis par la gauche
     jusqu'à tenir (la fin, domaine enregistrable compris, reste visible).
     Recalculé seulement quand la largeur de la ligne change. */
  const measureCanvas=typeof document!=='undefined'?document.createElement('canvas'):null;
  /* Ligne plus étroite que ce seuil (px) : l'hôte passe avant le libellé et prend
     toute la ligne (`sc-host-first` : icône masquée, corps 10 px ; le libellé
     reste dans le nom accessible du lien) ; au-delà, 72 % pour laisser lire le
     libellé. */
  const HOST_PRIORITY_ROW_PX=260;
  function fitHosts(){
    for(const el of root.querySelectorAll('.sc-item-host[data-host]')){
      const row=el.closest('li');
      const width=row?row.clientWidth:0;
      if(!width||el.dataset.fitWidth===String(width))continue;
      el.dataset.fitWidth=String(width);
      const full=el.dataset.host;
      const narrow=width<HOST_PRIORITY_ROW_PX;
      row.classList.toggle('sc-host-first',narrow);
      const context=measureCanvas&&measureCanvas.getContext('2d');
      let charW=6.6;
      if(context){context.font=getComputedStyle(el).font;charW=Math.max(1,context.measureText('0000000000').width/10)}
      const budget=narrow?width-2:width*0.72;
      let max=Math.max(8,Math.floor(budget/charW));
      el.textContent=L.hostTail(full,max);
      for(let guard=0;guard<64&&row.scrollWidth>row.clientWidth+1&&max>8;guard++){max--;el.textContent=L.hostTail(full,max)}
    }
  }

  /* Contenu défilé jusqu'en bas (liste d'un artefact, résumé d'une fenêtre) :
     plus de fondu sur la dernière ligne. */
  function markScrolledToEnd(el){
    el.classList.toggle('sc-at-end',el.scrollTop+el.clientHeight>=el.scrollHeight-1);
  }

  function onScroll(event){
    const el=event.target;
    if(!el||!el.classList)return;
    if(el.classList.contains('sc-items')||el.classList.contains('sc-summary'))markScrolledToEnd(el);
  }

  /* Tabulation itinérante : un seul arrêt de tabulation dans la scène. */
  function updateTabStop(list){
    if(!list.length){tabStopId=null;return}
    let wanted=focusId&&nodes.has(focusId)?focusId:null;
    if(!wanted)wanted=L.spatialOrder(list)[0].id;
    if(wanted===tabStopId&&nodes.get(wanted).el.tabIndex===0)return;
    const previous=tabStopId&&nodes.get(tabStopId);
    if(previous)previous.el.tabIndex=-1;
    nodes.get(wanted).el.tabIndex=0;
    tabStopId=wanted;
  }

  function nodeElement(target){
    const el=target&&target.closest?target.closest('.sc-node'):null;
    return el&&root&&root.contains(el)?el:null;
  }

  function onKeyDown(event){
    const el=nodeElement(event.target);
    if(!el||!lastModel)return;
    if(event.key==='Escape'){
      event.preventDefault();
      if(gesture){cancelGesture();return}
      if(keyEdit){cancelKeyEdit();return}
      if(event.target!==el){el.focus({preventScroll:true});return}
      el.blur();return;
    }
    if((event.key==='PageDown'||event.key==='PageUp')&&!event.altKey&&!event.ctrlKey&&!event.metaKey){
      /* La liste d'abord (l'artefact la met en avant), sinon le résumé de la
         fenêtre : le seul des deux qui déborde se laisse parcourir. */
      const scroller=[el.querySelector('.sc-items'),el.querySelector('.sc-summary')]
        .find(part=>part&&part.scrollHeight>part.clientHeight+1);
      if(scroller){
        event.preventDefault();
        scroller.scrollTop+=(event.key==='PageDown'?1:-1)*Math.max(20,Math.round(scroller.clientHeight*0.85));
        markScrolledToEnd(scroller);
      }
      return;
    }
    const intent=I?I.keyIntent(event):(['ArrowRight','ArrowLeft','ArrowUp','ArrowDown','Home','End'].includes(event.key)?{type:'nav'}:null);
    if(!intent)return;
    if(intent.type==='menu'){
      event.preventDefault();kbdMenuAt=performance.now();
      openObjectMenu(el.dataset.objectId,anchorOfNode(el),el);
      return;
    }
    if(intent.type==='move'||intent.type==='resize'){event.preventDefault();keyAdjust(el,intent);return}
    event.preventDefault();
    const next=L.nextFocus(lastModel.nodes,el.dataset.objectId,event.key);
    const record=next&&nodes.get(next);
    if(!record||record.el===el)return;
    focusId=next;updateTabStop(lastModel.nodes);
    record.el.focus();
  }

  function onKeyUp(event){
    /* Relâcher le modificateur valide l'édition au clavier. */
    if(keyEdit&&(event.key==='Shift'||event.key==='Control'))flushKeyEdit('keyup');
  }

  function onFocusOut(event){
    const el=nodeElement(event.target);
    if(!el)return;
    /* Le focus passe du nœud à un de ses liens (ou l'inverse) : rien ne se valide. */
    if(el.contains(event.relatedTarget))return;
    setInnerTabs(el,false);
    if(keyEdit&&keyEdit.id===el.dataset.objectId)flushKeyEdit('blur');
  }

  /* Bouton d'origine d'un artefact : sélectionner l'étoile expliquée. Un lien
     d'entrée s'ouvre seul (navigateur) ; rien d'autre ne réagit à un clic. */
  function onInnerClick(event){
    const button=event.target&&event.target.closest?event.target.closest('.sc-origin'):null;
    if(!button||!root.contains(button))return;
    event.preventDefault();
    if(button.getAttribute('aria-disabled')==='true')return;
    const record=nodes.get(button.dataset.target);
    if(!record){consoleLog('info','scene.artifact_target_not_drawn',{object_id:button.dataset.target});return}
    focusId=button.dataset.target;select(focusId);
    if(lastModel)updateTabStop(lastModel.nodes);
    record.el.focus({preventScroll:true});
    consoleLog('info','scene.artifact_target_focused',{object_id:focusId});
  }

  function onFocusIn(event){
    const el=nodeElement(event.target);
    if(!el)return;
    setInnerTabs(el,true);
    focusId=el.dataset.objectId;
    /* Prendre le focus ne **défait** pas une sélection multiple. Le navigateur
       donne le focus au nœud dès qu'on appuie dessus : remplacer la sélection
       ici la réduisait à cette seule étoile juste avant le geste, et le groupe
       qu'on venait de tracer au rectangle — ou de prendre par « toute la
       constellation » — se dissolvait sous la main. L'objet déjà sélectionné
       devient simplement l'ancre (le dernier entré), ce que le menu et le
       clavier lisent ; un objet hors sélection, lui, la remplace comme avant. */
    if(I)anchorSelection(focusId);
    if(lastModel)updateTabStop(lastModel.nodes);
    clampLabel(el);
  }

  function onPointerOver(event){
    const el=nodeElement(event.target);
    if(el)clampLabel(el);
  }

  /* Étiquette de survol gardée dans la scène : décalée à l'horizontale, passée
     au-dessus du point près du bas. Mesure sans transformation (la transition
     de l'étiquette fausserait `getBoundingClientRect`) : centre du nœud et
     largeur de mise en page. */
  function clampLabel(el){
    const label=el.querySelector(':scope > .sc-label');
    if(!label||!root)return;
    const bounds=root.getBoundingClientRect(),node=el.getBoundingClientRect(),margin=8;
    const width=label.offsetWidth,height=label.offsetHeight;
    const left=node.left+node.width/2-width/2;
    let dx=0;
    if(left<bounds.left+margin)dx=bounds.left+margin-left;
    else if(left+width>bounds.right-margin)dx=bounds.right-margin-(left+width);
    label.style.setProperty('--sc-dx',`${Math.round(dx)}px`);
    label.classList.toggle('sc-label-up',node.bottom+6+height>bounds.bottom-margin);
  }


  /* ------------------------------------------------ gestes (Slice 08) */

  const round1=v=>Math.round(v*10)/10;

  function nodeOf(id){return lastModel?lastModel.nodes.find(node=>node.id===id)||null:null}
  /* Boîte stockée (ou placée par le résolveur) de l'objet, dans l'état dessiné. */
  function drawnBox(id){const current=currentLayout();return current?current.placements.get(id)||null:null}
  function viewportNow(){return L.viewport(root.clientWidth||window.innerWidth,root.clientHeight||window.innerHeight)}
  function anchorOfNode(el){
    const r=el.getBoundingClientRect();
    return {x:r.left+Math.min(r.width/2,44),y:r.bottom+4,above:r.top-4};
  }
  function titleOf(id){const node=nodeOf(id);return node?node.title:id}
  function quoted(id){const text=titleOf(id);return `« ${text.length>60?text.slice(0,59)+'…':text} »`}
  const errorText=error=>String(error&&error.message||error);
  /* Bare Hands est reconnu par son contrat (`control_center_barehands_contracts.js`,
     inséré avant ce module), jamais par un sélecteur ou un identifiant de
     pointeur recopié ici. */
  const BH=window.JarvisBarehandsContracts;
  const barehandsActive=()=>!!document.querySelector(BH.DOM.tokenSelector);

  /* Aperçu d'une boîte (unités, place **enregistrée** : la tenue la donne par
     `preview`) sur le nœud, dans sa forme dessinée. Seule la place change : le
     nœud garde le décalage d'orbite qu'il avait à la prise, figé avec le champ. */
  function previewAt(el,node,box){
    const vp=viewportNow();
    /* **La forme dessinée est recalculée pour la boîte de l'aperçu**
       (21/09/2026). Elle était recopiée du rendu précédent : une fenêtre trop
       petite pour son texte, que `compactShape` dessine en capsule, gardait
       pendant tout le geste la pilule de 28 px que `drawnRect` donne à une
       fenêtre compactée — la poignée ne montrait donc rien du
       redimensionnement en cours, puis la vraie taille apparaissait d'un coup
       au relâchement. L'aperçu montre maintenant ce que le lâcher dessinera. */
    const drawn=L.nodeGeometry(vp,node.representation,box);
    position(el,{...node,...drawn});
  }

  /* Où en est le tour, en fraction de période : lu sur l'animation elle-même,
     jamais sur l'horloge du document — une page cachée, une scène en pause ou un
     geste en cours arrêtent l'animation, pas le temps qui passe. */
  function fieldTurn(){
    return L.orbitTurnAt(Date.now(),lastField);
  }

  /* Commandes de la page posées au-dessus de la scène : barre du haut, dock,
     indication vocale, bandeau GPT-Live, pastilles, panneau, commandes Bare
     Hands, indicateurs de la scène. **Mesurées au moment de la prise**, pas
     supposées : un objet s'arrête contre celles qui sont là, et nulle part
     ailleurs (22/09/2026 — la zone sûre, calibrée pour 1280 × 720, laissait
     jusqu'à 452 px interdits sans rien dessus sur un grand écran). */
  const CONTROL_SELECTOR='.topbar>*,.dock,.voicehint,.live-banner,.bgpills,.panel,#barehandsHud,#barehandsPalette,#sceneLayer>.sc-status';
  function controlRects(){
    if(!root)return [];
    const origin=root.getBoundingClientRect();
    const out=[];
    for(const el of document.querySelectorAll(CONTROL_SELECTOR)){
      if(el.hidden||el.closest('[hidden]'))continue;
      const style=getComputedStyle(el);
      if(style.display==='none'||style.visibility==='hidden')continue;
      const rect=el.getBoundingClientRect();
      if(!(rect.width>0&&rect.height>0))continue;
      out.push({left:rect.left-origin.left,top:rect.top-origin.top,width:rect.width,height:rect.height});
    }
    return out;
  }

  /* **Prendre des objets** : la tenue commune à la souris, à Bare Hands et au
     clavier (`I.createHold`). Les animations sont d'abord remises à l'heure
     murale, pour que l'écart calculé à la prise soit exactement celui qui est
     dessiné, puis les objets tenus sont figés à cet écart (`freezeHold`).
     `members` : `[{id, representation, box}]`, places enregistrées. */
  function beginHold(members){
    const vp=viewportNow();
    const field=lastField;
    syncFieldToWall();
    const hold=I.createHold({layout:L,vp,field,turn:fieldTurn(),area:I.holdArea(vp,controlRects()),members});
    freezeHold(hold);
    return hold;
  }

  /* Figer les objets tenus à l'écart que leur tour leur donne à la prise :
     l'animation s'arrête pour eux seuls (`sc-held`), et `translate` porte
     l'écart calculé par la tenue — le même que l'image d'avant, à l'heure
     murale. */
  function freezeHold(hold){
    for(const id of hold.ids()){
      const record=nodes.get(id);
      if(!record)continue;
      const off=hold.offset(id);
      record.el.classList.add('sc-held');
      record.el.style.translate=`${off.x}px ${off.y}px`;
    }
  }

  /* Tenues en cours, de toutes les mains. */
  function activeHolds(){
    const out=[];
    if(gesture&&gesture.hold)out.push({hold:gesture.hold,rebased(){gesture.startX=gesture.lastX;gesture.startY=gesture.lastY}});
    if(keyEdit&&keyEdit.hold)out.push({hold:keyEdit.hold,rebased(){}});
    for(const entry of barehandsHeld.values())out.push({hold:entry.hold,rebased(){entry.rebased=true}});
    return out;
  }

  /* **Ce qui définit une tenue a changé sous la main** — fenêtre
     redimensionnée, ampleur, vitesse ou gravitation réglées (au besoin depuis
     un autre onglet), scène devenue calme. Chaque objet tenu reste où il est
     dessiné ; la tenue se refonde, et la main repart de là où elle est. Sans
     cela, le lâcher défaisait un tour qui n'existait plus (50 à 626 px de saut
     mesurés). */
  function rebaseHolds(vp,field){
    const signature=I.holdSignature(vp,field);
    for(const {hold,rebased} of activeHolds()){
      if(hold.signature()===signature)continue;
      hold.rebase({vp,field,turn:fieldTurn(),area:I.holdArea(vp,controlRects())});
      rebased();
      freezeHold(hold);
      showHold(hold);
      consoleLog('info','scene.hold_rebased',{objects:hold.ids().length});
    }
  }

  /* `beginHold` pour un geste de l'utilisateur : une tenue impossible (défaut
     de la page — `createHold` refuse une fenêtre non mesurée ou un rendu
     incomplet) se dit à l'écran et au journal, et rend `null` : l'appelant
     lâche alors ses nœuds au lieu de laisser un objet figé et le champ en
     pause. */
  function tryHold(members,action){
    try{return beginHold(members)}
    catch(error){actionFailed(action,members[0]&&members[0].id,error);return null}
  }

  /* Montrer où la tenue en est, pour chacun de ses objets. */
  function showHold(hold){
    for(const id of hold.ids()){
      const record=nodes.get(id),node=nodeOf(id);
      if(record&&node)previewAt(record.el,node,hold.preview(id));
    }
  }

  /* **Lâcher** : la place dont le dessin est ce que l'utilisateur a lâché part
     à Core — pour chaque objet tenu qui a bougé — et l'attente est inscrite
     **avant** de lâcher la main : lâcher d'abord redessinerait les nœuds à leur
     ancienne place le temps d'une image (19/09/2026). `commitUserGeometry`
     inscrit l'attente avant sa première pause. Rend les envois. */
  function commitHold(hold,ids,kind){
    const sent=[];
    const turn=fieldTurn();
    for(const id of ids){
      /* Le tour a continué pendant la tenue : la place est celle qui dessine
         l'objet là où il est **à l'instant du lâcher**. */
      const box=hold.place(id,turn);
      if(I.sameBox(box,hold.origin(id)))continue;
      sent.push([id,commitUserGeometry(id,box,kind)]);
    }
    return sent;
  }

  function holdNode(id,held){
    const record=nodes.get(id);
    if(!record)return;
    const before=holding.get(id)||0,after=held?before+1:Math.max(0,before-1);
    if(after)holding.set(id,after);else holding.delete(id);
    syncHolding();
    /* Une autre main le tient encore, ou il l'était déjà : rien d'autre. */
    if((before>0)===(after>0))return;
    record.dragging=held;
    record.el.classList.toggle('sc-dragging',held);
    /* Lâcher : la transition reste coupée jusqu'à ce que la nouvelle place soit
       posée (`settle`), sinon l'excursion de 420 ms revient. */
    if(!held){record.el.classList.add('sc-settling');settling.add(record.el)}
    /* Le fil suit le point tant que la main le tient : ses extrémités sont
       recalculées à chaque image, et rien n'est écrit dans la scène — la place
       ne part à Core qu'au relâchement (`commitUserGeometry`). */
    if(held)startFollow(id);else stopFollow(id);
    if(!held){record.place='';scheduleRender()}
  }

  /* Un geste en cours sur la scène (curseur « saisi »). Le champ, lui, ne
     s'arrête plus : seul l'objet tenu est figé (`freezeHold`). */
  function syncHolding(){
    const held=holding.size>0||!!gesture;
    if(root)root.classList.toggle('sc-gesture',held);
  }

  function notify(options){
    if(typeof toast==='function')try{toast({ms:4500,...options})}catch(error){consoleLog('error','scene.toast_failed',{error:errorText(error)})}
  }

  /* Annonce d'un changement d'état au lecteur d'écran (région vivante polie). */
  function announce(text){
    if(!actionLiveEl||!text)return;
    /* Même texte deux fois de suite : vidé puis réécrit, pour être relu. */
    if(actionLiveEl.textContent===text)actionLiveEl.textContent='';
    actionLiveEl.textContent=text;
  }

  /* Échec imprévu d'une action de l'utilisateur (défaut de la page) : dit à
     l'écran, journalisé en console, jamais silencieux. */
  function actionFailed(action,id,error){
    actionStats.failed++;
    consoleLog('error','scene.user_action_failed',{action,object_id:id,error:errorText(error)});
    notify({title:`${action} impossible`,sub:'Erreur de la page ; recharger si cela se répète.',kind:'bad'});
  }

  function pendingChanged(){
    scheduleRender();pushCommitter();
    if(pending&&pending.size()&&!pruneTimer){
      pruneTimer=window.setTimeout(()=>{pruneTimer=0;prunePending();if(pending.size())pendingChanged()},I.PENDING_MAX_MS/3);
    }
  }

  /* L'état tenu a rattrapé Core (ou l'attente a trop duré) : l'aperçu optimiste s'efface. */
  function prunePending(){
    if(!pending||!pending.size())return;
    const removed=pending.prune(lastState,Date.now());
    for(const entry of removed)if(entry.reason==='expired')consoleLog('warn','scene.user_change_unconfirmed',{object_id:entry.id});
    if(removed.length){scheduleRender();pushCommitter()}
  }

  /* Sélection à déplacer quand des objets quittent le dessin (archivage,
     masquage) : le voisin dans l'ordre de lecture, focalisé au prochain rendu. */
  function planFocusAfterRemoval(removedIds,message){
    const list=lastModel?lastModel.nodes:[];
    const active=nodeElement(document.activeElement);
    const current=active?active.dataset.objectId:(focusId||removedIds[0]);
    const next=I.focusAfterRemoval(L.spatialOrder(list).map(node=>node.id),removedIds,current);
    pendingFocus={id:next,at:Date.now()};
    announce(message);
    scheduleRender();
  }

  /* `POST /api/scene/commands` (acteur `user` posé par le Control Center), depuis
     n'importe quel onglet : les gestes ne dépendent pas du meneur. Le texte
     brut d'un échec ne va qu'à la console. */
  async function sendCommand(command){
    let result;
    try{
      const response=await requestJson('/api/scene/commands',{method:'POST',body:command,timeoutMs:15000});
      result=I.classifyResponse(response.status,response.body);
    }catch(error){
      result={ok:false,outcome:'failed',reason:'',revision:null,...I.networkFailure(error)};
    }
    if(!result.ok&&result.detail)consoleLog('warn','scene.user_command_detail',{op:command.op,code:result.code,detail:result.detail});
    return result;
  }

  /* Refus ou échec : toast discret, journal console, compteur. */
  function reportRefusal(action,id,result,extra){
    if(result.outcome==='failed')actionStats.failed++;else actionStats.refused++;
    consoleLog(result.outcome==='failed'?'warn':'info','scene.user_command_refused',
      {action,object_id:id,outcome:result.outcome,reason:result.reason,code:result.code,unknown:!!result.unknown});
    notify({title:`${action} impossible`,sub:result.message,kind:result.unknown?'warn':'bad',...(extra||{})});
  }

  /* Envoyer une modification dessinée tout de suite ; annulée sur refus. */
  async function optimistic(action,id,fields,command){
    const token=pending.begin(id,fields,Date.now());
    pendingChanged();
    const result=await sendCommand(command);
    if(!result.ok){
      if(pending.rollback(id,token)){actionStats.rolledBack++;pendingChanged()}
      reportRefusal(action,id,result);
      return {result,token};
    }
    pending.confirm(id,token,result.revision);
    prunePending();
    return {result,token};
  }

  /* Toute géométrie de l'utilisateur (glisser, redimensionner, clavier) épingle
     l'objet (Décision 9 ; décision PM, reprise QA). Ordre : l'épingle d'abord,
     puis la position — l'utilisateur peut déplacer un objet épinglé, et le
     cerveau ne peut plus rien placer entre les deux. Un objet encore sans
     géométrie ne s'épingle pas : position, épingle, puis position de nouveau
     (sans effet, `duplicate`, si personne n'a bougé l'objet entre-temps).
     Échec : les deux étapes reviennent (désépinglage si l'objet ne l'était pas). */
  async function commitUserGeometry(id,box,kind){
    if(kind==='resize')actionStats.resizes++;else actionStats.moves++;
    const item=lastState&&lastState.objects.get(id);
    if(!item)return;
    const wasPinned=!!(item.constraints&&item.constraints.pinned_by_user);
    const placed=!!item.geometry;
    const action=kind==='resize'?'Redimensionnement':'Déplacement';
    const token=pending.begin(id,{geometry:box,pinned:true},Date.now());
    pendingChanged();
    const outcome=await I.commitGeometry({id,box,wasPinned,placed,send:sendCommand,pending,token});
    if(outcome.pinned)actionStats.pins++;
    if(!outcome.ok){
      if(outcome.undo&&!outcome.undo.ok)consoleLog('warn','scene.user_unpin_compensation_failed',{object_id:id,code:outcome.undo.code,reason:outcome.undo.reason});
      if(outcome.rolledBack){actionStats.rolledBack++;pendingChanged()}
      return reportRefusal(outcome.step==='pin'?'Épinglage':action,id,outcome.result);
    }
    prunePending();
    consoleLog('info',kind==='resize'?'scene.user_resized':'scene.user_moved',{object_id:id,steps:outcome.steps.join('+'),revision:outcome.revision});
  }

  /* --------------------------------- cadres tenus à mains nues (Bare Hands, Slice 06)

     Bare Hands ne déplace pas un objet en envoyant des événements de pointeur :
     une manipulation à deux mains n'a pas d'équivalent DOM, et le chemin de la
     souris ci-dessous ne sait redimensionner que par le coin bas droit. Il tient
     donc le cadre par cette couture, qui **réutilise** exactement ce que la
     souris utilise — `drawnBox`, `previewAt`, `holdNode`, `commitUserGeometry` —
     au lieu d'une seconde géométrie. La sienne, en unités de scène, est celle de
     `JarvisSceneInteract` ; ici, rien de nouveau n'est calculé.

     Une seule main tient un objet à la fois : si la souris s'y met, elle gagne
     (`onPointerDown` annule la tenue), parce que c'est le geste le plus
     explicite des deux.

     **Une main prend un cadre, pas une sélection.** Depuis la fusion de
     `origin/main`, un glissement à la souris sur un objet sélectionné emmène
     toute la sélection (`carried`, `onPointerDown`) ; une prise à mains nues
     n'emmène que l'objet nommé par `begin(id)`. Les deux gestes portent donc
     le même nom et ne recouvrent pas le même ensemble, et c'est **délibéré
     mais non décidé** : la Slice 06 a spécifié la prise d'un cadre (décisions
     10, 11, 19), pas d'une sélection, et l'étendre demanderait un aperçu, une
     attente (`pending`) et un refus par objet — une fonctionnalité, pas une
     résolution de conflit. Laissé en l'état, tracé ici, à arbitrer par
     l'humain avant d'élargir la couture. */
  const barehandsHeld=new Map();

  /* La boîte du moteur, rapportée à la tenue. Après une refonte (`rebase`),
     le moteur continue de calculer depuis **sa** boîte de départ, dans l'ancien
     repère : sa première boîte suivante devient la référence, et seuls ses
     écarts à elle comptent — le cadre ne saute pas. */
  function framesWanted(entry,id,box){
    if(entry.rebased){entry.rebased=false;entry.base={...box};entry.anchor=entry.hold.drawn(id)}
    if(!entry.base)return box;
    const a=entry.anchor,b=entry.base;
    return {x:a.x+box.x-b.x,y:a.y+box.y-b.y,w:a.w+box.w-b.w,h:a.h+box.h-b.h};
  }

  function framesRelease(id){
    if(!barehandsHeld.delete(id))return false;
    holdNode(id,false);
    return true;
  }

  const frames=Object.freeze({
    /* Le cadre d'un objet dessiné, et sa forme. `null` quand il n'y a rien à
       tenir — scène éteinte, objet absent du dessin, ou souris déjà dessus :
       le moteur le dit alors à l'écran plutôt que de manipuler un fantôme. */
    begin(id){
      if(!enabled)return null;
      /* Souris déjà dessus : elle gagne, dans ce sens comme dans l'autre. Le
         geste souris emmène toute sa sélection, donc « dessus » veut dire
         « parmi les objets emmenés », pas seulement l'objet pris — sinon une
         main saisirait un voisin que la souris est en train de déplacer. */
      if(gesture&&(gesture.id===id||(gesture.carried||[]).some(member=>member.id===id)))return null;
      const node=nodeOf(id),box=drawnBox(id),state=viewState();
      const item=state&&state.objects.get(id);
      if(!node||!box||!item||!nodes.has(id))return null;
      holdNode(id,true);
      const hold=tryHold([{id,representation:item.representation,box}],'Déplacement');
      if(!hold){holdNode(id,false);return null}
      barehandsHeld.set(id,{hold,rebased:false,base:null,anchor:null});
      /* **La boîte dessinée**, pas la place enregistrée (22/09/2026) : c'est
         elle que la main voit et saisit. Le moteur calcule dedans, et la page
         en déduit la place au lâcher — il ne voit jamais le tour. */
      return {objectId:id,box:hold.start(id),representation:item.representation};
    },
    /* Aperçu optimiste **local** : rien ne part à Core tant que la main tient,
       exactement comme un glissement à la souris — par la même tenue, donc
       les mêmes bords. `box` est dans le repère du dessin ; `mode`, celui du
       moteur (`move` ou `resize`). */
    preview(id,box,mode){
      const entry=barehandsHeld.get(id);
      if(!entry||!box)return;
      entry.hold.to(id,framesWanted(entry,id,box),mode);
      showHold(entry.hold);
    },
    /* Relâchement : la place dont le dessin est la boîte lâchée part à Core
       (et épingle l'objet, décision 9). Elle était envoyée telle quelle, sans
       défaire le tour : l'objet sautait de 300 à 400 px, en miroir du geste. */
    commit(id,box,mode){
      const entry=barehandsHeld.get(id);
      if(!entry)return;
      const hold=entry.hold;
      if(box)hold.to(id,framesWanted(entry,id,box),mode);
      const kind=mode==='resize'?'resize':'move';
      const sent=commitHold(hold,[id],kind);
      framesRelease(id);
      for(const [objectId,promise] of sent)
        promise.catch(error=>actionFailed(kind==='resize'?'Redimensionnement':'Déplacement',objectId,error));
    },
    /* Main perdue, veille, extinction : le cadre revient où il était et rien
       n'est envoyé — la même réponse que `pointercancel` à la souris. */
    cancel(id){if(framesRelease(id))scheduleRender()},
    /* La même porte que `begin` : scène éteinte, pas de fenêtre. Sans elle,
       `viewportNow()` lisait `root.clientWidth` sur un `root` qui n'existe pas
       — et une échelle absente, côté Bare Hands, est ce qui fait qu'un geste
       part six fois trop loin. Mieux vaut `null`, qui se refuse et se dit. */
    viewport(){return enabled&&root?viewportNow():null},
  });
  /* Un appui qui peut ouvrir un rectangle de sélection : sur le fond de la
     page, sur le visage ou sur la scène elle-même — jamais sur un objet (qui a
     son propre geste), ni sur une commande, ni dans un panneau du Control
     Center, qui gardent les leurs. */
  function bandCandidate(event){
    if(!enabled||!root||root.hidden||band||gesture)return false;
    if(event.button!==undefined&&event.button!==0)return false;
    const target=event.target;
    if(!target||!target.closest)return false;
    if(target.closest('#sceneLayer .sc-node,.sc-status,#ctxMenu,#confirmBack'))return false;
    if(target.closest('a,button,input,select,textarea,label,summary,[contenteditable],[role="button"],[role="tab"],[role="menuitem"]'))return false;
    /* Le fond, c'est **ce qui porte la scène**, pas une liste de noms.
       L'appui dans le vide n'arrive ni sur `body` ni sur le visage : la scène
       est transparente aux clics (`pointer-events:none`) et l'iframe du visage
       aussi, si bien que le clic retombe sur le conteneur qui les contient tous
       les deux — `#app` sur cette page. Énumérer `body`, `documentElement` et
       `.face` laissait donc le rectangle mort-né : mesuré sur la page servie,
       l'élément sous l'appui est `<div id="app">`, qu'aucun de ces noms ne
       reconnaissait. Un ancêtre de la scène est un fond par construction : le
       demander à l'arbre vaut mieux que de tenir la liste à jour à chaque
       calque ajouté au Control Center. Les panneaux et les commandes, eux, ne
       contiennent pas la scène — ils sont déjà écartés plus haut. */
    if(target.contains&&target.contains(root))return true;
    return target===document.body||target===root||target===document.documentElement
      ||target.classList.contains('face')||target.closest('#sceneLayer')===root;
  }

  /* Début d'un rectangle de sélection. Ctrl ou Maj tenu, il s'ajoute à la
     sélection courante au lieu de la remplacer. La suite du geste est écoutée
     sur le document : la scène ne reçoit pas les évènements du vide, et une
     capture de pointeur sur un calque transparent aux clics ne se comporte pas
     de la même façon d'un navigateur à l'autre. */
  function startBand(event){
    band={pointerId:event.pointerId,startX:event.clientX,startY:event.clientY,
      add:!!(event.ctrlKey||event.metaKey||event.shiftKey),moved:false,el:null};
    document.addEventListener('pointermove',onBandMove,true);
    document.addEventListener('pointerup',onBandUp,true);
    document.addEventListener('pointercancel',onBandUp,true);
  }

  function onBandMove(event){
    if(!band||event.pointerId!==band.pointerId)return;
    const box=bandFrame(event);
    if(box)event.preventDefault();
  }

  function onBandUp(event){
    if(!band||event.pointerId!==band.pointerId)return;
    document.removeEventListener('pointermove',onBandMove,true);
    document.removeEventListener('pointerup',onBandUp,true);
    document.removeEventListener('pointercancel',onBandUp,true);
    endBand(event.type==='pointercancel'?null:bandFrame(event));
  }

  function bandFrame(event){
    const box=I.bandBox({x:band.startX,y:band.startY},{x:event.clientX,y:event.clientY});
    if(!band.moved){
      if(!I.bandStarted(box))return null;
      band.moved=true;
      band.el=document.createElement('div');
      band.el.className='sc-band';band.el.setAttribute('aria-hidden','true');
      root.appendChild(band.el);
    }
    const origin=root.getBoundingClientRect();
    band.el.style.left=`${box.left-origin.left}px`;band.el.style.top=`${box.top-origin.top}px`;
    band.el.style.width=`${box.width}px`;band.el.style.height=`${box.height}px`;
    return box;
  }

  function endBand(box){
    const held=band;
    band=null;
    if(held&&held.el)held.el.remove();
    if(!held||!held.moved||!box)return;
    /* Les boîtes **dessinées**, lues sur la page : le champ tourne, et ce que
       l'utilisateur encercle est ce qu'il voit, pas la place enregistrée. */
    const boxes=[];
    for(const [id,record] of nodes){
      const rect=record.el.getBoundingClientRect();
      if(rect.width||rect.height)boxes.push({id,left:rect.left,top:rect.top,width:rect.width,height:rect.height});
    }
    const hits=I.bandHits(box,boxes);
    applySelection(I.nextSelection(selection,hits,held.add?'add':'replace'));
    if(lastModel)updateTabStop(lastModel.nodes);
    announce(selection.length?`${selection.length} objet${selection.length>1?'s':''} sélectionné${selection.length>1?'s':''}.`:'Sélection vidée.');
  }

  function onPointerDown(event){
    if(event.button!==0||!enabled)return;
    const el=nodeElement(event.target);
    /* Le vide n'arrive jamais ici : la scène laisse passer les clics partout
       sauf sur ses objets (`pointer-events`), donc le rectangle de sélection
       naît du document (`onDocumentPointerDown`). */
    if(!el)return;
    /* Lien d'entrée ou origine d'un artefact : leur clic natif, pas de geste. */
    if(event.target.closest('.sc-item-link,.sc-origin'))return;
    /* Ctrl-clic (Cmd sur Mac) : l'objet entre dans la sélection ou en sort, et
       rien d'autre — ni geste, ni menu, ni changement de place. */
    if((event.ctrlKey||event.metaKey)&&!event.target.closest('.sc-grip')){
      select(el.dataset.objectId,'toggle');
      if(lastModel)updateTabStop(lastModel.nodes);
      announce(selection.length?`${selection.length} objet${selection.length>1?'s':''} sélectionné${selection.length>1?'s':''}.`:'Sélection vidée.');
      event.preventDefault();
      return;
    }
    const id=el.dataset.objectId,node=nodeOf(id),box=drawnBox(id),state=viewState();
    const item=state&&state.objects.get(id);
    if(!node||!box||!item)return;
    /* Objets emmenés par le geste : toute la sélection quand on prend l'un des
       siens, sinon le seul objet pris. Un redimensionnement ne concerne que
       l'objet dont on tient la poignée. */
    const resizing=!!event.target.closest('.sc-grip')&&I.resizable(item.representation);
    const carried=[];
    for(const memberId of (!resizing&&selection.length>1&&selection.indexOf(id)>=0?selection:[id])){
      const record=nodes.get(memberId),memberNode=nodeOf(memberId),memberBox=drawnBox(memberId);
      const memberItem=state&&state.objects.get(memberId);
      if(!record||!memberNode||!memberBox||!memberItem)continue;
      carried.push({id:memberId,el:record.el,node:memberNode,representation:memberItem.representation,
        box:{x:memberBox.x,y:memberBox.y,w:memberBox.w,h:memberBox.h}});
    }
    if(!carried.length)return;
    /* Une main tenait un de ces cadres : la souris est le geste le plus
       explicite des deux, elle gagne — et la tenue s'annule proprement plutôt
       que de laisser deux aperçus se disputer le même nœud.

       **Toute la sélection emmenée, pas seulement l'objet pris** : depuis que
       le geste souris emmène ses voisins, `holdNode` est écrit par les deux
       chemins pour chacun d'eux. Ne libérer que `id` laisserait une main tenir
       un cadre que la souris déplace, et le `holdNode(member.id,false)` du
       lâcher couperait le fil de cette main sans qu'elle le sache. */
    for(const member of carried)frames.cancel(member.id);
    if(gesture)cancelGesture();
    if(keyEdit)flushKeyEdit('pointer');
    if(typeof closeMenu==='function')closeMenu(false);
    gesture={id,el,node,mode:resizing?'resize':'move',pointerId:event.pointerId,startX:event.clientX,startY:event.clientY,
      lastX:event.clientX,lastY:event.clientY,
      box:{x:box.x,y:box.y,w:box.w,h:box.h},representation:item.representation,moved:false,menuOpened:false,hold:null,
      carried,
      wasSelected:document.activeElement===el,longTimer:0,
      threshold:I.dragThreshold(event.pointerType,BH.isBareHandsPointerId(event.pointerId)||barehandsActive())};
    syncHolding();
    /* Appui long sans bouger : menu (Barehands, écran tactile). */
    const current=gesture;
    current.longTimer=window.setTimeout(()=>{
      if(gesture!==current||current.moved)return;
      current.menuOpened=true;
      openObjectMenu(id,{x:current.startX,y:current.startY,above:current.startY},el);
    },I.LONG_PRESS_MS);
    try{el.setPointerCapture(event.pointerId)}catch(_error){/* pointeur synthétique (Barehands) : pas de capture, les événements arrivent au nœud */}
    anchorSelection(id);
    if(document.activeElement!==el)el.focus({preventScroll:true});
    event.preventDefault();
  }

  function onPointerMove(event){
    const g=gesture;
    if(!g||event.pointerId!==g.pointerId)return;
    g.lastX=event.clientX;g.lastY=event.clientY;
    const dx=event.clientX-g.startX,dy=event.clientY-g.startY;
    if(!g.moved){
      if(g.menuOpened||Math.hypot(dx,dy)<g.threshold)return;
      g.moved=true;
      window.clearTimeout(g.longTimer);
      for(const member of g.carried)holdNode(member.id,true);
      g.hold=tryHold(g.carried.map(member=>({id:member.id,representation:member.representation,box:member.box})),
        g.mode==='resize'?'Redimensionnement':'Déplacement');
      if(!g.hold)return cancelGesture();
    }
    const units=I.pxToUnits(viewportNow(),dx,dy);
    /* La tenue reçoit ce que veut la main ; elle borne et montre. La poignée
       ne concerne que son objet ; un déplacement emmène la sélection d'un
       bloc, qui s'arrête ensemble au bord (`I.sweepMove`). */
    if(g.mode==='resize')g.hold.resizeTo(g.id,I.resizeBox(g.hold.start(g.id),units.dx,units.dy,g.representation));
    else g.hold.moveBy(units);
    showHold(g.hold);
  }

  function endGesture(g){
    window.clearTimeout(g.longTimer);
    try{if(g.el.hasPointerCapture&&g.el.hasPointerCapture(g.pointerId))g.el.releasePointerCapture(g.pointerId)}catch(_error){/* capture déjà rendue */}
    if(gesture===g)gesture=null;
    syncHolding();
  }

  function onPointerUp(event){
    const g=gesture;
    if(!g||event.pointerId!==g.pointerId)return;
    endGesture(g);
    if(g.menuOpened)return;
    if(!g.moved){
      /* Clic sur l'objet déjà sélectionné : ses actions (souris et Barehands). */
      if(g.wasSelected)openObjectMenu(g.id,{x:event.clientX,y:event.clientY,above:event.clientY},g.el);
      return;
    }
    dropGesture(g);
  }

  /* Poser ce que la souris tient, là où elle l'a lâché (`commitHold`), puis
     lâcher les nœuds. */
  function dropGesture(g){
    const sent=commitHold(g.hold,g.mode==='resize'?[g.id]:g.carried.map(member=>member.id),g.mode);
    for(const member of g.carried)holdNode(member.id,false);
    const action=g.mode==='resize'?'Redimensionnement':'Déplacement';
    for(const [id,promise] of sent)promise.catch(error=>actionFailed(action,id,error));
    if(sent.length>1)announce(`${sent.length} objets déplacés.`);
  }

  function cancelGesture(){
    const g=gesture;
    if(!g)return;
    endGesture(g);
    if(g.moved)for(const member of g.carried)holdNode(member.id,false);
  }

  /* `pointercancel` : le système reprend le pointeur, rien n'est posé.
     `lostpointercapture` avant tout mouvement : un appui qui n'a rien tenu.
     **Après un mouvement** (22/09/2026), c'est le nœud qui a perdu la capture —
     retiré puis recréé par un rendu, par exemple — et le `pointerup` n'arrivera
     jamais jusqu'ici : l'ignorer laissait l'objet figé sous `sc-dragging`. Le geste se termine donc comme un lâcher, à la
     dernière place montrée. Après un vrai `pointerup`, `gesture` est déjà vide
     et cet événement ne trouve rien. */
  function onPointerCancel(event){
    const g=gesture;
    if(!g||event.pointerId!==g.pointerId)return;
    if(event.type==='lostpointercapture'&&g.moved&&g.hold){
      endGesture(g);
      consoleLog('warn','scene.gesture_capture_lost',{object_id:g.id,mode:g.mode});
      dropGesture(g);
      return;
    }
    if(event.type==='pointercancel'||!g.moved)cancelGesture();
  }

  function onContextMenu(event){
    const el=nodeElement(event.target);
    if(!el)return;
    /* Lien d'entrée : menu natif du navigateur (copier l'adresse…). */
    if(event.target.closest('.sc-item-link'))return;
    event.preventDefault();
    if(performance.now()-kbdMenuAt<700)return;  // déjà ouvert par la touche Menu / Maj+F10
    if(gesture)cancelGesture();
    select(el.dataset.objectId);
    if(document.activeElement!==el)el.focus({preventScroll:true});
    const keyboard=event.clientX===0&&event.clientY===0;
    openObjectMenu(el.dataset.objectId,keyboard?anchorOfNode(el):{x:event.clientX,y:event.clientY,above:event.clientY},el);
  }

  /* Objet sélectionné : dernier objet touché ou focalisé ; sa poignée reste
     visible sans survol. Un appui ailleurs dans la page le désélectionne. */
  /* `mode` : « replace » (défaut), « add » (Ctrl ou Maj tenu) ou « toggle »
     (Ctrl-clic : présent, l'objet sort ; absent, il entre). `null` vide tout. */
  function select(id,mode){
    if(id===null)return applySelection([]);
    if(mode&&I)return applySelection(I.nextSelection(selection,[id],mode));
    applySelection([id]);
  }

  /* Poser l'ancre **sans défaire le groupe**. Prendre un objet — à la souris ou
     par le focus — le désignait jusqu'ici comme la sélection entière, si bien
     qu'une sélection multiple se dissolvait à l'instant où on la saisissait :
     le geste emmenait bien ses voisins (ils sont retenus avant), mais l'écran
     n'en montrait plus qu'un, et un second glisser ne prenait plus que lui.
     Un objet déjà sélectionné devient donc le dernier entré — l'ancre que
     lisent le menu et le clavier — et le groupe reste. Un objet hors sélection,
     lui, la remplace comme avant. */
  function anchorSelection(id){
    if(selection.indexOf(id)<0)return select(id);
    if(selectedId!==id)applySelection(selection.filter(other=>other!==id).concat([id]));
  }

  function applySelection(ids){
    const next=[];
    for(const id of ids||[])if(next.indexOf(id)<0)next.push(id);
    const before=new Set(selection);
    const after=new Set(next);
    for(const id of selection)if(!after.has(id)){const record=nodes.get(id);if(record)record.el.classList.remove('sc-selected')}
    for(const id of next)if(!before.has(id)){const record=nodes.get(id);if(record)record.el.classList.add('sc-selected')}
    selection=next;
    selectedId=next.length?next[next.length-1]:null;
  }

  function onDocumentPointerDown(event){
    if(!root)return;
    const target=event.target&&event.target.closest?event.target:null;
    if(!selection.length)return;
    if(target&&(target.closest('#sceneLayer .sc-node')||target.closest('#ctxMenu')||target.closest('#confirmBack')))return;
    /* Ctrl ou Maj tenu : l'utilisateur agrandit sa sélection, il ne la jette pas. */
    if(event.ctrlKey||event.metaKey||event.shiftKey)return;
    select(null);
  }

  /* Le rectangle de sélection s'ouvre ici, dans la même écoute : c'est le seul
     endroit qui voit les appuis du vide. */
  function onDocumentBandDown(event){
    if(bandCandidate(event))startBand(event);
  }

  /* Maj+flèches / Ctrl+flèches : aperçu tout de suite, validation au relâchement
     du modificateur, à la perte du focus ou après 700 ms sans touche. */
  function keyAdjust(el,intent){
    const id=el.dataset.objectId,state=viewState(),item=state&&state.objects.get(id);
    if(!item)return;
    if(intent.type==='resize'&&!I.resizable(item.representation)){
      announce('Un point ne se redimensionne pas : changer sa forme depuis le menu.');
      return;
    }
    if(keyEdit&&keyEdit.id!==id)flushKeyEdit('other');
    if(!keyEdit){
      const box=drawnBox(id),node=nodeOf(id);
      if(!box||!node||!nodes.has(id))return;
      holdNode(id,true);select(id);
      const hold=tryHold([{id,representation:item.representation,box}],intent.type==='resize'?'Redimensionnement':'Déplacement');
      if(!hold)return holdNode(id,false);
      keyEdit={id,el,node,hold,moved:false,timer:0};
    }
    /* La même tenue que la souris : chaque touche part de là où l'objet **est
       dessiné**, et un pas contre un bord s'arrête au bord. */
    const hold=keyEdit.hold,at=hold.drawn(id),start=hold.start(id);
    if(intent.type==='move'){
      const wanted=I.applyKey(at,intent,item.representation);
      hold.moveBy({dx:wanted.x-start.x,dy:wanted.y-start.y});
      keyEdit.moved=true;
    }else hold.resizeTo(id,I.applyKey(at,intent,item.representation));
    showHold(hold);
    window.clearTimeout(keyEdit.timer);
    keyEdit.timer=window.setTimeout(()=>flushKeyEdit('idle'),700);
  }

  function flushKeyEdit(why){
    const edit=keyEdit;
    if(!edit)return;
    keyEdit=null;
    window.clearTimeout(edit.timer);
    const kind=edit.moved?'move':'resize';
    const sent=commitHold(edit.hold,[edit.id],kind);
    holdNode(edit.id,false);
    if(!sent.length)return;
    consoleLog('info','scene.user_key_edit',{object_id:edit.id,why});
    for(const [id,promise] of sent)promise.catch(error=>actionFailed(kind==='resize'?'Redimensionnement':'Déplacement',id,error));
  }

  function cancelKeyEdit(){
    const edit=keyEdit;
    if(!edit)return;
    keyEdit=null;
    window.clearTimeout(edit.timer);
    holdNode(edit.id,false);
  }

  /* ------------------------------------------------------------ menu */

  function openObjectMenu(id,pos,origin){
    if(!I)return;
    if(typeof showMenu!=='function'){consoleLog('warn','scene.menu_unavailable',{});return}
    const state=viewState();
    if(!state||!state.objects.has(id))return;
    const model=I.menuModel(state,id,{title:titleOf(id),finished:lastState?I.bulkSelection(lastState).objects:0,
      orphans:lastState?L.orphanArtifacts(lastState).length:0});
    if(!model)return;
    actionStats.menus++;
    showMenu({title:model.title,items:model.items,pos,origin,run:act=>{
      runObjectAction(act,id).catch(error=>actionFailed('Action',id,error));
    }});
  }

  async function runObjectAction(act,id){
    if(act.startsWith('rep:'))return changeRepresentation(id,act.slice(4));
    if(act==='pin')return pinHere(id);
    if(act==='unpin'){
      actionStats.pins++;
      return optimistic('Désépinglage',id,{pinned:false},I.commands.unpin(id));
    }
    if(act==='hide')return hideObject(id);
    if(act==='select-constellation')return selectConstellation(id);
    if(act==='stop')return stopJob(id);
    if(act==='archive')return archiveObject(id);
    if(act==='archive-finished')return archiveFinished();
    if(act==='archive-orphans')return archiveOrphanArtifacts();
  }

  /* « Sélectionner toute la constellation » : la figure entière devient la
     sélection, et le geste suivant l'emmène d'un bloc — `onPointerDown` prend
     déjà toute la sélection quand on attrape l'un des siens.
     La sélection est **refaite** ici et non élargie : le clic droit vient de la
     réduire à cette seule étoile (`onContextMenu`), il n'y a rien à garder.
     Rien n'est envoyé à Core : une sélection ne vit que dans la page. */
  function selectConstellation(id){
    const state=viewState();
    if(!state)return;
    const ids=I.constellationOf(state,id).filter(memberId=>nodes.has(memberId));
    if(!ids.length)return;
    applySelection(I.nextSelection(selection,ids,'replace'));
    if(lastModel)updateTabStop(lastModel.nodes);
    announce(`${selection.length} objet${selection.length>1?'s':''} sélectionné${selection.length>1?'s':''} : toute la constellation.`);
  }

  async function changeRepresentation(id,representation){
    const state=viewState(),item=state&&state.objects.get(id),box=drawnBox(id);
    if(!item||!box)return;
    actionStats.representations++;
    /* Agrandir (capsule, fenêtre) : place libre près de ce que l'objet explique,
       hors du visage, dans la zone sûre ; réduire en point garde le centre. */
    const placed=representation==='point'?null:L.placeFor(state,currentLayout(),id,representation);
    const next=placed?I.clampBox(placed,representation):I.representationBox(box,representation,item.kind);
    consoleLog('info','scene.user_representation_box',{object_id:id,representation,placed:!!placed});
    await optimistic('Changement de forme',id,{representation,geometry:next},I.commands.setRepresentation(id,representation,next));
  }

  async function pinHere(id){
    const item=lastState&&lastState.objects.get(id),box=drawnBox(id);
    if(!item||!box)return;
    /* Pas encore de place validée : la place dessinée devient celle de l'utilisateur. */
    if(!item.geometry)return commitUserGeometry(id,I.clampBox(box,item.representation),'move');
    actionStats.pins++;
    await optimistic('Épinglage',id,{pinned:true},I.commands.pin(id));
  }

  async function hideObject(id){
    const label=quoted(id);
    actionStats.visibility++;
    planFocusAfterRemoval([id],`${label} masqué.`);
    const {result}=await optimistic('Masquage',id,{visibility:'hidden'},I.commands.setVisibility(id,'hidden'));
    if(result.ok)notify({title:`${label} masqué`,sub:'Cliquer ici pour le réafficher.',kind:'info',
      onClick:()=>showObjects([id]).catch(error=>actionFailed('Réaffichage',id,error))});
  }

  /* Réafficher des objets masqués, un par un (au plus 512). Le premier
     réaffiché reçoit la sélection (la pastille disparaît avec le dernier). */
  async function showObjects(ids){
    let shown=0,failed=null;
    for(const id of ids.slice(0,512)){
      actionStats.visibility++;
      const token=pending.begin(id,{visibility:'visible'},Date.now());pendingChanged();
      const result=await sendCommand(I.commands.setVisibility(id,'visible'));
      if(result.ok){
        pending.confirm(id,token,result.revision);
        if(!shown)pendingFocus={id,at:Date.now()};
        shown++;
      }
      else{if(pending.rollback(id,token)){actionStats.rolledBack++;pendingChanged()}failed=failed||result;if(result.outcome==='failed')break}
    }
    prunePending();scheduleRender();
    consoleLog('info','scene.user_shown',{asked:ids.length,shown});
    if(shown)announce(shown>1?`${shown} objets réaffichés.`:`${quoted(ids[0])} réaffiché.`);
    if(failed)reportRefusal(shown?`Réaffichage de ${ids.length-shown} objet(s)`:'Réaffichage',ids[0],failed);
    else if(ids.length>1)notify({title:`${shown} objets réaffichés`,kind:'ok',ms:3000});
  }

  function openHiddenMenu(anchor){
    if(typeof showMenu!=='function'||!I)return;
    const state=viewState();
    if(!state)return;
    const hidden=I.hiddenObjects(state);
    if(!hidden.length)return;
    const shown=hidden.slice(0,24);
    const items=shown.map((entry,index)=>({act:`show:${index}`,label:`Afficher « ${L.cleanLine(entry.title,48)||entry.id} »`}));
    if(hidden.length>shown.length)items.push({act:'more',label:`… et ${hidden.length-shown.length} autres`,disabled:true});
    items.push('-',{act:'show-all',label:`Tout réafficher (${hidden.length})`});
    const r=anchor.getBoundingClientRect();
    actionStats.menus++;
    showMenu({title:hidden.length>1?`${hidden.length} objets masqués`:'1 objet masqué',items,
      pos:{x:r.left,y:r.top-4,above:r.top-4},origin:anchor,run:act=>{
        const ids=act==='show-all'?hidden.map(entry=>entry.id):act.startsWith('show:')?[shown[Number(act.slice(5))].id]:[];
        if(ids.length)showObjects(ids).catch(error=>actionFailed('Réaffichage',ids[0],error));
      }});
  }

  async function archiveObject(id){
    const key=`archive:${id}`;
    if(inflight.has(key))return;
    const state=viewState(),item=state&&state.objects.get(id);
    if(!item)return;
    const signals=['agent','job'].includes(item.kind)?I.cascadeOf(state,id).length:0;
    const lines=['Il quitte la scène active ; il reste dans l’historique.'];
    if(signals)lines.push(signals>1?`Ses ${signals} signaux d’attention partent avec lui.`:'Son signal d’attention part avec lui.');
    if(['running','pending','blocked'].includes(item.exec_state))lines.push('Le travail continue, mais son étoile ne reviendra pas.');
    else if(['agent','job'].includes(item.kind)&&item.exec_state==='unknown')
      lines.push('Son état est inconnu depuis le redémarrage de Core : s’il reprend, son étoile ne reviendra pas.');
    /* Slice 07 : les artefacts qui l'expliquent ne partent pas avec elle. */
    const artifacts=['agent','job'].includes(item.kind)?L.artifactsExplaining(state,id).length:0;
    if(artifacts)lines.push(artifacts>1?`Ses ${artifacts} artefacts restent dans la scène, à archiver à part.`:'Son artefact reste dans la scène, à archiver à part.');
    if(typeof confirmDialog!=='function'){consoleLog('warn','scene.confirm_unavailable',{});return}
    const label=quoted(id);
    if(!await confirmDialog({title:`Archiver ${label} ?`,lines,confirmLabel:'Archiver',danger:true}))return;
    inflight.add(key);
    try{
      actionStats.archives++;
      const cascade=signals?I.cascadeOf(state,id):[];
      planFocusAfterRemoval([id,...cascade],`${label} archivé.`);
      const tokens=[id,...cascade].map(target=>[target,pending.begin(target,{archived:true},Date.now())]);
      pendingChanged();
      const result=await sendCommand(I.commands.archive(id));
      if(!result.ok){
        for(const [target,token] of tokens)if(pending.rollback(target,token))actionStats.rolledBack++;
        pendingChanged();
        return reportRefusal('Archivage',id,result);
      }
      for(const [target,token] of tokens)pending.confirm(target,token,result.revision);
      prunePending();
      consoleLog('info','scene.user_archived',{object_id:id,signals,revision:result.revision,outcome:result.outcome});
      notify({title:`${label} archivé`,sub:signals?(signals>1?`Avec ses ${signals} signaux.`:'Avec son signal.'):'',kind:'ok',ms:2500});
    }finally{inflight.delete(key)}
  }

  const STATE_WORDS=Object.freeze({completed:['terminée','terminées'],failed:['en échec','en échec'],cancelled:['annulée','annulées'],interrupted:['interrompue','interrompues']});

  /* « Archiver les travaux terminés » : sélection calculée sur l'état tenu,
     confirmée avec les comptes par état, revalidée par Core (tout ou rien).
     Une sélection devenue fausse est recalculée et reconfirmée une fois ; au
     second refus, la notification propose de réessayer. */
  async function archiveFinished(retry=false){
    if(inflight.has('bulk'))return;
    if(!lastState)return;
    const selection=I.bulkSelection(lastState);
    if(!selection.objects){notify({title:'Rien à archiver',sub:'Aucun travail terminé dans la scène.',kind:'info',ms:3000});return}
    const parts=Object.entries(selection.byState).filter(([,n])=>n).map(([state,n])=>`${n} ${STATE_WORDS[state][n>1?1:0]}`);
    const lines=[];
    if(selection.stars)lines.push([`${selection.stars} ${selection.stars>1?'étoiles':'étoile'}`,` quittent la scène : ${parts.join(', ')}.`]);
    if(selection.cascaded)lines.push([`${selection.cascaded} ${selection.cascaded>1?'signaux':'signal'}`,` d’attention ${selection.cascaded>1?'partent':'part'} avec elles.`]);
    if(selection.orphans)lines.push([`${selection.orphans} ${selection.orphans>1?'signaux orphelins':'signal orphelin'}`,' (étoile déjà archivée) aussi.']);
    const leftOrphan=L.artifactsLeftOrphan(lastState,selection.ids).length;
    if(leftOrphan)lines.push([`${leftOrphan} ${leftOrphan>1?'artefacts':'artefact'}`,` qui les ${leftOrphan>1?'expliquent restent':'explique reste'}, sans lien : « Archiver les artefacts orphelins » les range ensuite.`]);
    lines.push('Le travail en cours, en attente, bloqué ou à l’état inconnu depuis un redémarrage reste, comme les artefacts, notes et fenêtres du brain.');
    if(retry)lines.unshift('La scène a changé pendant la confirmation : comptes mis à jour.');
    if(typeof confirmDialog!=='function'){consoleLog('warn','scene.confirm_unavailable',{});return}
    const noun=`${selection.objects} ${selection.objects>1?'objets':'objet'}`;
    if(!await confirmDialog({title:'Archiver les travaux terminés ?',lines,confirmLabel:`Archiver ${noun}`,danger:true}))return;
    inflight.add('bulk');
    const started=Date.now();
    let archived=0,refusal=null;
    try{
      actionStats.bulkArchives++;
      ({archived,refusal}=await sendArchiveMany(selection.ids,noun));
    }finally{inflight.delete('bulk')}
    consoleLog(refusal?'warn':'info','scene.user_bulk_archived',{selected:selection.objects,archived,ms:Date.now()-started,
      refused:refusal?refusal.reason||refusal.code:null});
    if(refusal&&refusal.reason==='not_bulk_archivable'&&!retry)return archiveFinished(true);
    const again={onClick:()=>archiveFinished().catch(error=>actionFailed('Archivage groupé',null,error)),ms:8000};
    if(refusal&&refusal.reason==='not_bulk_archivable')
      return reportRefusal('Archivage groupé',null,{...refusal,message:'La scène change encore. Cliquer ici pour réessayer.'},again);
    if(refusal)return reportRefusal(archived?`Archivage de ${selection.objects-archived} objet(s)`:'Archivage groupé',null,refusal,
      refusal.unknown?{}:{...again,sub:`${refusal.message} Cliquer ici pour réessayer.`});
    announce(`${archived} ${archived>1?'objets archivés':'objet archivé'}.`);
    notify({title:`${archived} ${archived>1?'objets archivés':'objet archivé'}`,sub:'Place libérée pour le travail en attente.',kind:'ok',ms:3500});
  }

  /* Envoi d'une sélection confirmée en commandes `archive_many` (bornes du
     transport), avec l'affichage optimiste de chaque objet et de ses signaux
     runtime ; s'arrête au premier refus. Rend `{archived, refusal}`. */
  async function sendArchiveMany(ids,noun){
    let archived=0,refusal=null;
    const owners=I.signalOwners(lastState);
    const everything=[...ids];
    for(const [signal,owner] of owners)if(owner&&everything.includes(owner))everything.push(signal);
    planFocusAfterRemoval(everything,`Archivage de ${noun}.`);
    for(const chunk of I.chunkIds(ids)){
      const chosen=new Set(chunk);
      const targets=[...chunk];
      for(const [signal,owner] of owners)if(owner&&chosen.has(owner))targets.push(signal);
      const tokens=targets.map(target=>[target,pending.begin(target,{archived:true},Date.now())]);
      pendingChanged();
      const result=await sendCommand(I.commands.archiveMany(chunk));
      if(!result.ok){
        for(const [target,token] of tokens)if(pending.rollback(target,token))actionStats.rolledBack++;
        pendingChanged();
        refusal=result;break;
      }
      for(const [target,token] of tokens)pending.confirm(target,token,result.revision);
      archived+=targets.length;
    }
    prunePending();
    return {archived,refusal};
  }

  /* « Archiver les artefacts orphelins » (Slice 07, reprise QA) : artefacts
     qui n'expliquent plus aucun objet actif (leur étoile a été archivée).
     Sélection sur l'état tenu, confirmée avec le compte et quelques titres,
     revalidée par Core (`archive_many`, tout ou rien) ; recalculée une fois si
     la scène a changé. Un artefact encore relié n'est jamais pris. */
  async function archiveOrphanArtifacts(retry=false){
    if(inflight.has('bulk')||!lastState)return;
    const ids=L.orphanArtifacts(lastState);
    if(!ids.length){notify({title:'Rien à archiver',sub:'Aucun artefact orphelin dans la scène.',kind:'info',ms:3000});return}
    const count=ids.length,noun=`${count} ${count>1?'artefacts':'artefact'}`;
    const lines=[[noun,` ${count>1?'n’expliquent':'n’explique'} plus aucun objet de la scène (étoile déjà archivée, ou jamais relié).`]];
    for(const id of ids.slice(0,3)){
      const payload=(lastState.objects.get(id)||{}).payload||{};
      lines.push(`« ${L.cleanLine(payload.title,60)||id} »`);
    }
    if(count>3)lines.push(`… et ${count-3} ${count-3>1?'autres':'autre'}.`);
    lines.push('Les artefacts encore reliés à une étoile restent.');
    if(retry)lines.unshift('La scène a changé pendant la confirmation : liste mise à jour.');
    if(typeof confirmDialog!=='function'){consoleLog('warn','scene.confirm_unavailable',{});return}
    if(!await confirmDialog({title:'Archiver les artefacts orphelins ?',lines,confirmLabel:`Archiver ${noun}`,danger:true}))return;
    inflight.add('bulk');
    const started=Date.now();
    let archived=0,refusal=null;
    try{
      actionStats.bulkArchives++;
      ({archived,refusal}=await sendArchiveMany(ids,noun));
    }finally{inflight.delete('bulk')}
    consoleLog(refusal?'warn':'info','scene.user_orphans_archived',{selected:count,archived,ms:Date.now()-started,
      refused:refusal?refusal.reason||refusal.code:null});
    if(refusal&&refusal.reason==='not_bulk_archivable'&&!retry)return archiveOrphanArtifacts(true);
    if(refusal)return reportRefusal('Archivage des artefacts orphelins',null,refusal,
      {onClick:()=>archiveOrphanArtifacts().catch(error=>actionFailed('Archivage des artefacts orphelins',null,error)),ms:8000});
    announce(`${archived} ${archived>1?'artefacts archivés':'artefact archivé'}.`);
    notify({title:`${archived} ${archived>1?'artefacts orphelins archivés':'artefact orphelin archivé'}`,kind:'ok',ms:3500});
  }

  /* Arrêt d'une étoile `job` : `POST /api/jobs/cancel`. Jamais proposé pour un
     sous-agent du brain. L'étoile montre « arrêt en cours » jusqu'à ce que
     Core la dise terminée, ou jusqu'au délai réel du relais (`/api/status`). */
  async function stopJob(id){
    const item=lastState&&lastState.objects.get(id);
    if(!item||item.kind!=='job'||!item.work_ref||item.work_ref.source!=='job')return;
    const key=`stop:${id}`;
    if(inflight.has(key)||stopping.has(id))return;
    if(typeof confirmDialog!=='function'){consoleLog('warn','scene.confirm_unavailable',{});return}
    const label=quoted(id);
    if(!await confirmDialog({title:`Arrêter la tâche ${label} ?`,
      lines:['Le job Core est annulé ; son étoile reste, marquée annulée.'],confirmLabel:'Arrêter la tâche',cancelLabel:'Continuer la tâche',danger:true}))return;
    inflight.add(key);
    actionStats.stops++;
    const started=Date.now();
    const limitS=jobCancelTimeoutS;
    stopping.set(id,{label,started,deadline:started+1000*(limitS||30)});
    announce(`Arrêt de ${label} demandé.`);
    scheduleRender();ensureStatusTicker();
    try{
      const response=await requestJson('/api/jobs/cancel',{method:'POST',body:{source:item.work_ref.source,external_id:item.work_ref.external_id},
        timeoutMs:1000*((limitS||30)+5)});
      const body=response.body||{};
      if(response.status===200&&typeof body.outcome==='string'){
        const words=I.stopOutcome(body.outcome,body.status);
        consoleLog(words.kind==='warn'?'warn':'info','scene.user_stopped',{object_id:id,outcome:body.outcome,status:body.status,ms:Date.now()-started});
        if(words.terminal)stopping.delete(id);
        notify({title:words.title,sub:`${label} · ${words.sub}`,kind:words.kind,ms:words.terminal?3500:6000});
        announce(`${words.title}.`);
        return;
      }
      stopping.delete(id);
      reportRefusal('Arrêt',id,I.classifyResponse(response.status,body));
    }catch(error){
      stopping.delete(id);
      reportRefusal('Arrêt',id,{ok:false,outcome:'failed',reason:'',revision:null,...I.networkFailure(error)});
    }finally{inflight.delete(key);scheduleRender()}
  }

  /* Étoiles en arrêt : terminées dans l'état tenu → fin de l'attente ;
     délai dépassé → dit tel quel, sans inventer d'issue. */
  function settleStopping(){
    if(!stopping.size)return;
    const now=Date.now();
    for(const [id,entry] of [...stopping]){
      const item=lastState&&lastState.objects.get(id);
      if(!item||I.TERMINAL.includes(item.exec_state)){stopping.delete(id);scheduleRender();continue}
      if(now>entry.deadline){
        stopping.delete(id);scheduleRender();
        consoleLog('warn','scene.user_stop_unconfirmed',{object_id:id,waited_ms:now-entry.started});
        notify({title:'Arrêt non confirmé',sub:`${entry.label} · toujours en cours après ${Math.round((now-entry.started)/1000)} s.`,kind:'warn',ms:6000});
      }
    }
  }

  function ensureStatusTicker(){
    if(!statusTicker)statusTicker=window.setInterval(renderStatus,1000);
  }

  /* ------------------------------------------ fils pendant un geste */

  /* Ancre d'un nœud dans le repère du calque qui porte son fil : le centre de sa
     zone dessinée **telle qu'elle est à l'écran**, ramené par `matrix` dans ce
     repère. La place est dans `transform`, l'arc du champ dans `translate` : la
     boîte rendue est le seul endroit qui porte les deux à la fois — et, pendant
     un geste, l'aperçu qui n'est encore écrit nulle part. `null` : nœud plus
     dessiné. */
  function anchorOf(id,matrix){
    const record=nodes.get(id);
    if(!record)return null;
    const r=record.el.getBoundingClientRect();
    if(!r.width&&!r.height)return null;
    const point=new DOMPoint(r.left+r.width/2,r.top+r.height/2).matrixTransform(matrix);
    return {x:round1(point.x),y:round1(point.y)};
  }

  /* Extrémités des fils qui touchent le nœud tenu, pour cette image. Deux
     repères, car les fils vivent désormais dans deux calques (`sc-field`, qui
     tourne, et `sc-fixed`, qui ne tourne pas) : une extrémité posée dans le
     mauvais repère serait emportée par la rotation du champ, ou privée d'elle. */
  function followEdges(){
    if(!follow||!root||!fieldEl||!fixedEl)return;
    const turnCtm=fieldEl.getScreenCTM(),fixedCtm=fixedEl.getScreenCTM();
    if(!turnCtm||!fixedCtm)return;
    const matrices=new Map([[fieldEl,turnCtm.inverse()],[fixedEl,fixedCtm.inverse()]]);
    for(const {edge,line} of edgeLines){
      if(!follow.ids.has(edge.from)&&!follow.ids.has(edge.to))continue;
      const matrix=matrices.get(line.parentNode);
      if(!matrix)continue;
      const a=anchorOf(edge.from,matrix),b=anchorOf(edge.to,matrix);
      if(!a||!b)continue;
      line.setAttribute('x1',a.x);line.setAttribute('y1',a.y);
      line.setAttribute('x2',b.x);line.setAttribute('y2',b.y);
    }
  }

  /* **Les fils mixtes, renoués image par image** (21/09/2026).

     Un fil dont les deux bouts tournent est porté par `sc-field` : une rotation
     envoie le segment qui joint deux étoiles sur celui qui joint leurs nouvelles
     places, donc rien n'est à recalculer. Un fil dont aucun bout ne tourne est
     porté par `sc-fixed`, immobile — il l'était par `sc-field`, qui le faisait
     tourner alors que ses deux objets restaient en place.

     Reste le cas que la rotation d'un groupe ne peut pas décrire : **un bout
     mobile, un bout fixe**. C'est le fil violet d'un artefact-fenêtre vers son
     étoile, celui qui partait visiblement de travers. Une seule transformation
     ne peut pas suivre l'un et laisser l'autre ; ce fil est donc dans le calque
     immobile, et son bout mobile est calculé ici, par la même fonction que celle
     qui décrit le tour (`orbitTurnPoint`) — pas de seconde géométrie, pas de
     lecture du DOM, juste l'angle où le champ en est. */
  function turnEdges(){
    if(!mixedLines.length)return;
    const turn=fieldTurn();
    for(const {edge,line} of mixedLines){
      if(edge.fromTurns){
        const p=L.orbitTurnPoint({x:edge.x1,y:edge.y1},lastField,turn);
        line.setAttribute('x1',p.x);line.setAttribute('y1',p.y);
      }
      if(edge.toTurns){
        const p=L.orbitTurnPoint({x:edge.x2,y:edge.y2},lastField,turn);
        line.setAttribute('x2',p.x);line.setAttribute('y2',p.y);
      }
    }
  }

  /* Une seule boucle pour les deux besoins : le nœud tenu par la main, et les
     fils mixtes pendant que le champ tourne. Elle ne tourne que s'il y a
     quelque chose à suivre — une scène au repos, un champ arrêté (gravitation
     éteinte, scène trop peuplée) ou un onglet caché n'en allument aucune. */
  function edgeFrame(){
    turning=0;
    if(document.visibilityState==='hidden')return;
    if(!follow&&!(mixedLines.length&&fieldMoving))return;
    turning=requestAnimationFrame(edgeFrame);
    turnEdges();
    if(follow)followEdges();
  }

  function ensureEdgeFrame(){
    if(!turning&&(follow||(mixedLines.length&&fieldMoving)))edgeFrame();
  }

  /* Plusieurs nœuds peuvent être tenus à la fois (sélection multiple) : leurs
     fils suivent tous, sinon ceux des objets emmenés resteraient en arrière. */
  function startFollow(id){
    if(follow){follow.ids.add(id);return}
    follow={ids:new Set([id])};
    ensureEdgeFrame();
  }

  /* Fin du geste (ou nœud parti) : les extrémités posées à la main ne valent
     plus rien, la passe suivante redessine tous les fils, dérive comprise. */
  function stopFollow(id){
    if(!follow)return;
    if(id!==undefined){
      follow.ids.delete(id);
      if(follow.ids.size)return;
    }
    follow=null;
    edgesSig='';
  }

  /* Les fils sont posés à la place de référence de leurs deux bouts, puis
     rangés dans le calque qui sait les porter (voir `turnEdges`). */
  function applyEdges(edges,vp){
    const sig=`${vp.width}x${vp.height}|`+edges.map(e=>`${e.id},${e.kind},${e.signal},${e.artifact},${e.tone},${e.x1},${e.y1},${e.x2},${e.y2},${e.fromTurns?1:0}${e.toTurns?1:0}`).join(';');
    if(sig===edgesSig){ensureEdgeFrame();return}
    edgesSig=sig;
    linksEl.setAttribute('viewBox',`0 0 ${vp.width} ${vp.height}`);
    const turnGroup=[],fixedGroup=[],mixed=[];
    const lines=edges.map(edge=>{
      const line=document.createElementNS(SVG_NS,'line');
      line.setAttribute('x1',edge.x1);line.setAttribute('y1',edge.y1);line.setAttribute('x2',edge.x2);line.setAttribute('y2',edge.y2);
      line.setAttribute('class',`sc-link sc-link-${edge.kind}`+(edge.signal?` sc-link-signal sc-tone-${edge.tone}`:'')
        +(edge.artifact?` sc-link-artifact sc-tone-${edge.tone}`:''));
      if(edge.fromTurns&&edge.toTurns)turnGroup.push(line);
      else{
        fixedGroup.push(line);
        if(edge.fromTurns||edge.toTurns)mixed.push({edge,line});
      }
      return line;
    });
    fieldEl.replaceChildren(...turnGroup);
    fixedEl.replaceChildren(...fixedGroup);
    edgeLines=edges.map((edge,i)=>({edge,line:lines[i]}));
    mixedLines=mixed;
    /* Les bouts mobiles sont posés tout de suite, sans une image de retard —
       et de même, pendant un geste, ceux du nœud tenu. */
    turnEdges();
    if(follow)followEdges();
    ensureEdgeFrame();
  }

  function errorLabels(){
    /* `ERROR_CLASSES` du Control Center (même page) : les mots des cartes
       d'agents. Absente (page de test) : titres bruts. */
    try{return typeof ERROR_CLASSES==='object'?ERROR_CLASSES:null}catch(_error){return null}
  }

  function render(){
    raf=0;
    if(!enabled||!root)return;
    if(document.visibilityState==='hidden')return;
    const current=currentLayout();
    if(!lastState||!current){applyNodes([]);applyEdges([],{width:1,height:1});lastModel=null;return renderStatus()}
    const vp=L.viewport(root.clientWidth||window.innerWidth,root.clientHeight||window.innerHeight);
    const now=Date.now();
    markFresh(lastState,now);
    lastModel=L.viewModel(viewState(),current,vp,{objectLimit:lastView?lastView.objectLimit:L.OBJECT_LIMIT,errorLabels:errorLabels(),
      animatable:node=>(freshUntil.get(node.id)||{until:0}).until>now});
    /* Gravitation : le centre, la période et le resserrement du champ sont
       calculés pour ce rendu ; le rayon et la phase, eux, appartiennent à
       chaque objet. Le tour est continu et ne repart jamais de zéro. Scène très
       peuplée : tout s'immobilise. Gravitation éteinte par l'utilisateur :
       aucun champ n'est calculé, la classe `sc-no-orbit` a déjà arrêté ce qui
       tournait. */
    const points=lastModel.nodes.reduce((n,node)=>n+(node.shape==='point'?1:0),0);
    const options=V?V.orbitOptions(viewPrefs):undefined;
    const calm=points>CALM_POINTS;
    /* **Un champ qui ne tourne pas n'existe pas** (22/09/2026). Scène très
       peuplée ou mouvement réduit : la feuille de style arrête l'animation,
       mais le champ restait calculé, et les gestes défaisaient un tour que
       personne ne voyait — l'objet lâché sautait d'autant. */
    const field=options===null||calm||reducedMotion()?null:L.orbitField(lastModel.nodes,vp,options);
    lastField=field;
    if(field){
      root.style.setProperty('--sc-orbit-ms',`${field.ms}ms`);
      root.style.setProperty('--sc-orbit-cx',`${field.cx}px`);
      root.style.setProperty('--sc-orbit-cy',`${field.cy}px`);
      root.style.setProperty('--sc-orbit-scale',String(field.scale));
      /* Les deux demi-axes et leurs inverses, calculés ici : une division dans
         `calc()` par une variable reste mal servie d'un navigateur à l'autre. */
      root.style.setProperty('--sc-orbit-ax',String(field.ax));
      root.style.setProperty('--sc-orbit-ay',String(field.ay));
      root.style.setProperty('--sc-orbit-iax',String(Math.round(1e6/field.ax)/1e6));
      root.style.setProperty('--sc-orbit-iay',String(Math.round(1e6/field.ay)/1e6));
    }
    fieldMoving=!!field;
    rebaseHolds(vp,field);
    root.classList.toggle('sc-calm',calm);
    root.classList.toggle('sc-still',!field);
    applyNodes(lastModel.nodes,field);
    applyEdges(L.orbitLinks(lastModel.edges,lastModel.nodes,field),vp);
    syncField(!field);
    releaseSettling();
    if(resyncPending){
      /* Et encore une fois ici : l'horloge du document d'un onglet qui revient
         peut n'avoir repris qu'avec ce rendu. */
      resyncPending=false;
      syncFieldToWall();
      requestAnimationFrame(()=>requestAnimationFrame(()=>{if(root)root.classList.remove('sc-resync')}));
    }
    renderStatus();
    /* Transitions actives seulement après le premier placement : pas de
       glissement depuis l'origine au chargement. */
    if(!root.classList.contains('sc-ready')&&!readyTimer)
      readyTimer=requestAnimationFrame(()=>{readyTimer=requestAnimationFrame(()=>{readyTimer=0;if(root)root.classList.add('sc-ready')})});
  }

  /* `prefers-reduced-motion` : la feuille de style arrête déjà le tour ; le
     rendu doit le savoir aussi, pour ne pas calculer un champ invisible. */
  function reducedMotion(){
    try{return !!(window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches)}
    catch(_error){return false}  // navigateur sans requêtes média : le mouvement reste celui des réglages
  }

  /* Nœuds apparus ou dont l'état d'exécution ou l'urgence vient de changer : animables
     pendant `ANIMATE_FOR_MS`. Un rendu est prévu à la première échéance. */
  function markFresh(state,now){
    let next=Infinity;
    /* Premier rendu (chargement, interrupteur allumé) : rien de neuf, rien
       n'anime ; les indices fixes suffisent. */
    const first=freshUntil.size===0;
    for(const item of state.objects.values()){
      const sig=`${item.exec_state}|${item.category}|${state.relations.has(item.object_id)}`;
      const entry=freshUntil.get(item.object_id);
      if(!entry||entry.sig!==sig)freshUntil.set(item.object_id,{sig,until:first?0:now+ANIMATE_FOR_MS});
      const until=freshUntil.get(item.object_id).until;
      if(until>now&&until<next)next=until;
    }
    if(freshUntil.size>state.objects.size)for(const id of freshUntil.keys())if(!state.objects.has(id))freshUntil.delete(id);
    if(animTimer){window.clearTimeout(animTimer);animTimer=0}
    if(next!==Infinity)animTimer=window.setTimeout(()=>{animTimer=0;scheduleRender()},next-now+50);
  }

  function elapsed(ms){
    const s=Math.max(0,Math.round(ms/1000));
    return s<60?`${s} s`:`${Math.floor(s/60)} min ${String(s%60).padStart(2,'0')} s`;
  }

  function stopStatusTicker(){if(statusTicker){window.clearInterval(statusTicker);statusTicker=null}}

  /* Indicateur discret, jamais bloquant : chargement, lecture en panne (depuis
     combien de temps, nouvel essai automatique), scène pleine, objets hors
     champ. Réécrit seulement si son texte change ; la région vivante
     n'annonce que les changements d'état. */
  function renderStatus(){
    if(!statusEl||!lastView)return;
    const notes=[],announce=[];
    const health=lastView.health;
    if(health.level==='degraded'){
      const reason=REASONS[health.code]||health.code||'erreur';
      const title=`${lastState?'Scène figée':'Scène indisponible'} · ${reason}`;
      const retry=health.retryAt?`réessai ${elapsed(health.retryAt-Date.now())}`:'réessai…';
      notes.push({cls:'sc-warn',main:title,meta:`${elapsed(Date.now()-health.since)} · ${retry}`});
      announce.push(`${title}. Nouvel essai automatique.`);
      if(!statusTicker)statusTicker=window.setInterval(renderStatus,1000);
    }else if(!stopping.size){
      stopStatusTicker();
      if(!lastState&&lastView.phase==='loading')notes.push({cls:'sc-busy',main:'Scène · chargement…',meta:''});
    }
    if(lastModel&&lastModel.capacity.saturated){
      notes.push({cls:'sc-full',main:'Scène pleine — archiver des travaux terminés',meta:`${lastModel.capacity.objects}/${lastModel.capacity.limit}`,
        action:I?'bulk':'',label:'Scène pleine : archiver les travaux terminés'});
      announce.push('Scène pleine : archiver des travaux terminés.');
    }
    if(lastModel&&(lastModel.coveredSignals.high||lastModel.coveredSignals.medium)){
      const {high,medium}=lastModel.coveredSignals;
      const under=n=>n>1?'sous des fenêtres':'sous une fenêtre';
      if(high)notes.push({cls:'sc-full',main:`${high} ${high>1?"signaux d'échec":"signal d'échec"} ${under(high)}`,meta:''});
      if(medium)notes.push({cls:'sc-warn',main:`${medium} ${medium>1?'signaux à vérifier':'signal à vérifier'} ${under(medium)}`,meta:''});
      announce.push('Des signaux sont cachés sous des fenêtres.');
    }
    for(const entry of stopping.values()){
      notes.push({cls:'sc-busy',main:`Arrêt de ${entry.label} en cours`,meta:elapsed(Date.now()-entry.started)});
    }
    if(I&&lastModel&&lastModel.hidden){
      const n=lastModel.hidden;
      notes.push({cls:'sc-hidden',main:`${n} ${n>1?'objets masqués':'objet masqué'}`,meta:'afficher',action:'hidden',label:`${n} ${n>1?'objets masqués':'objet masqué'} : les lister pour les réafficher`});
    }
    if(lastModel&&lastModel.offscreen){
      notes.push({cls:'',main:`${lastModel.offscreen} ${lastModel.offscreen>1?'objets':'objet'} hors champ`,meta:''});
      announce.push('Des objets sont hors champ.');
    }
    const text=announce.join(' ');
    if(liveEl&&text!==announced){announced=text;liveEl.textContent=text}
    const sig=notes.map(n=>`${n.cls}:${n.main}:${n.meta}:${n.action||''}`).join('|');
    if(sig===statusSig)return;
    statusSig=sig;
    const focused=document.activeElement&&statusEl.contains(document.activeElement)?document.activeElement.dataset.action:null;
    statusEl.replaceChildren(...notes.map(n=>{
      const note=element(n.action?'button':'div',`sc-note ${n.cls}`.trim());
      note.append(element('span','sc-note-main',n.main));
      if(n.meta)note.append(element('span','sc-note-meta',n.meta));
      if(n.action){
        note.type='button';note.dataset.action=n.action;note.setAttribute('aria-label',n.label||n.main);
        note.addEventListener('click',()=>{
          if(n.action==='hidden')openHiddenMenu(note);
          else if(n.action==='bulk')archiveFinished().catch(error=>consoleLog('error','scene.user_action_failed',{action:'bulk',error:String(error&&error.message||error)}));
        });
      }
      return note;
    }));
    if(focused){const again=statusEl.querySelector(`[data-action="${focused}"]`);if(again)again.focus({preventScroll:true})}
    statusEl.hidden=!notes.length;
  }

  function onLoopUpdate(view){
    if(!enabled)return;
    lastView=view;
    if(view.state!==lastState){
      lastState=view.state;
      prunePending();
      settleStopping();
      scheduleRender();
    }
    renderStatus();
    pushCommitter();
  }

  function onResize(){scheduleRender()}

  async function onVisibility(){
    const token=++visibilityToken;
    const visible=document.visibilityState!=='hidden';
    if(root)root.classList.toggle('sc-paused',!visible);
    if(!enabled)return;
    if(!visible){
      loop.setVisible(false);
      releaseLeadership();
      return pushCommitter();
    }
    /* Caché, le champ était arrêté (`sc-paused`) : il se remet à l'heure
       murale **dans la même tâche** — jamais une image au temps d'avant, qui
       reculerait —, et les places changées pendant l'absence (un geste dans
       un autre onglet) se posent sans transition (`sc-resync`). */
    if(root){root.classList.add('sc-resync');resyncPending=true}
    syncFieldToWall();
    scheduleRender();
    await decideRole();
    if(token!==visibilityToken||!enabled)return;
    loop.setVisible(true);
    scheduleRender();
    pushCommitter();
  }

  /* ------------------------------------------------------------ capture (Slice 09) */

  /* Couleurs du thème courant, lues sur la couche de scène (jetons `--sc-*`, `--tone`) à chaque
     capture : aucun cache, donc jamais une palette d'un autre thème ou d'un autre état (reprise QA). */
  function capturePalette(){
    const style=getComputedStyle(root);
    const read=(name,fallback)=>(style.getPropertyValue(name)||'').trim()||fallback;
    const probe=document.createElement('span');probe.hidden=true;root.appendChild(probe);
    const tones={};
    try{
      for(const tone of Capture.TONE_KEYS){probe.className=`sc-tone-${tone}`;tones[tone]=(getComputedStyle(probe).getPropertyValue('--tone')||'').trim()||'#dcecf4'}
    }finally{probe.remove()}
    const body=getComputedStyle(document.body).backgroundColor;
    const value={background:body&&body!=='rgba(0, 0, 0, 0)'?body:'#03080c',ink:read('--sc-ink','#dcecf4'),muted:read('--sc-muted','#8aa5b3'),
      edge:read('--sc-edge','rgba(151,191,209,.3)'),surface:read('--sc-surface','rgba(4,10,15,.9)'),warn:read('--sc-warn','#ffb85c'),
      done:read('--sc-done','#6fe3a4'),
      radius:parseFloat(read('--sc-radius','10'))||0,error:tones.error||'#ff6b7d',tones};
    return value;
  }

  /* Dessiner le modèle de vue courant (celui des nœuds du DOM) sur un canevas réduit. */
  async function renderCapture(){
    if(!root||!enabled)throw new Error('scène éteinte');
    if(raf){cancelAnimationFrame(raf);raf=0}
    render();
    if(!lastModel)throw new Error('scène pas encore dessinée');
    const vp=L.viewport(root.clientWidth||window.innerWidth,root.clientHeight||window.innerHeight);
    const plan=Capture.drawCommands(lastModel,vp,capturePalette());
    /* Canevas hors document, encodé de façon synchrone : ne dépend d'aucune image
       produite par la page (voir `JarvisSceneCapture.encodePng`). */
    const canvas=document.createElement('canvas');canvas.width=plan.width;canvas.height=plan.height;
    try{
      Capture.paint(canvas.getContext('2d'),plan);
      const blob=new Blob([Capture.encodePng(canvas,value=>window.atob(value))],{type:'image/png'});
      return {blob,width:plan.width,height:plan.height};
    }finally{
      canvas.width=0;canvas.height=0;
    }
  }

  async function uploadCapture(id,blob){
    const controller=new AbortController();
    const deadline=window.setTimeout(()=>controller.abort(),10000);
    try{
      const response=await fetch(`/api/scene/captures/${encodeURIComponent(id)}`,{method:'POST',cache:'no-store',
        signal:controller.signal,headers:{'Content-Type':'image/png'},body:blob});
      const text=await response.text();
      let json=null;
      try{json=text?JSON.parse(text):null}catch(_error){json=null}
      return {status:response.status,body:json};
    }finally{
      window.clearTimeout(deadline);
    }
  }

  /* Interrupteur : appelé à chaque lecture réussie de `/api/status`. */
  function gate(scene,limits){
    const timeout=limits&&Number(limits.job_cancel_timeout_s);
    jobCancelTimeoutS=Number.isFinite(timeout)&&timeout>0?timeout:null;
    if(stopping.size)settleStopping();
    if(statusFailed){
      /* Le Control Center répond de nouveau : pas d'attente du repli. */
      statusFailed=false;
      if(enabled&&loop.retryNow())consoleLog('info','scene.status_back',{});
    }
    const next=Core.gateEnabled(scene);
    if(next===enabled)return;
    enabled=next;
    if(next){
      consoleLog('info','scene.enabled',{source:scene&&scene.source||'',mode:shared?'shared':'solo'});
      ensureRoot();
      window.addEventListener('resize',onResize);
      document.addEventListener('visibilitychange',onVisibility);
      document.addEventListener('pointerdown',onDocumentPointerDown,true);
      document.addEventListener('pointerdown',onDocumentBandDown,true);
      /* Un nœud retiré du document pendant qu'on le tient perd sa capture, et
         le navigateur le dit **au document**, plus au nœud ni à la scène. */
      if(I)document.addEventListener('lostpointercapture',onPointerCancel,true);
      loop.setVisible(document.visibilityState!=='hidden');
      const visible=document.visibilityState!=='hidden';
      const start=()=>{if(enabled)loop.setEnabled(true)};
      if(visible)decideRole().then(start);else{if(!shared)loop.setRole('solo');else loop.setRole('follower');start()}
    }else{
      consoleLog('info','scene.disabled',{});
      visibilityToken++;
      loop.setEnabled(false);
      committer.update(null);
      releaseLeadership();
      window.removeEventListener('resize',onResize);
      document.removeEventListener('visibilitychange',onVisibility);
      document.removeEventListener('pointerdown',onDocumentPointerDown,true);
      /* Posée avec la précédente en s'allumant, elle part avec elle : sans ce
         retrait, scène éteinte, un appui dans le vide ouvrait encore un
         rectangle sur une scène qui n'est plus là. */
      document.removeEventListener('pointerdown',onDocumentBandDown,true);
      document.removeEventListener('lostpointercapture',onPointerCancel,true);
      teardown();
    }
  }

  window.addEventListener('pagehide',event=>{
    if(event.persisted){releaseLeadership();return}
    loop.stop();committer.stop();releaseLeadership();
    if(channel)try{channel.close()}catch(_error){/* déjà fermé */}
  });

  window.JarvisScene=Object.freeze({
    version:2,gate,
    /* Cadres manipulables à mains nues (Bare Hands V1, Slice 06). Le pointeur
       est inséré **avant** ce module, donc il lit cette couture à l'appel et non
       au chargement. */
    frames,
    /* `/api/status` a échoué : la prochaine réussite relance la lecture. */
    statusLost(){statusFailed=true},
    /* Diagnostic (console, validation) : aucune écriture. */
    inspect:()=>{
      const view=loop.view();
      return {enabled,mode:shared?'shared':'solo',role:view.role,leader:{held:leader.held,mode:leader.mode},loop:view.phase,
        revision:lastState?lastState.revision:null,nodes:nodes.size,commits:committer.stats(),stats:view.stats,
        health:lastView?lastView.health:null,resolved:layout&&layoutState===viewState()?layout.resolved.length:0,
        pending:pending?pending.size():0,actions:{...actionStats},gesture:gesture?{id:gesture.id,mode:gesture.mode,moved:gesture.moved,threshold:gesture.threshold}:null,
        selected:selectedId,selection:[...selection],stopping:[...stopping.keys()],jobCancelTimeoutS,captures:capturer?capturer.stats():null,
        barehands:[...barehandsHeld.keys()],holding:[...holding],
        tabStops:root?root.querySelectorAll('[tabindex="0"]').length:0,animated:root?root.querySelectorAll('.sc-anim').length:0};
    },
  });
})();
