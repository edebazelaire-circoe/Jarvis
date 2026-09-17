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
     `broadcast(message)` (meneur).

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
        case 'applied':case 'unchanged':case 'more':
          resyncs=0;recover();
          if(role==='leader'&&state!==before)broadcast({type:'patches',scene_id:state.scene_id,epoch:state.epoch,body});
          if(result.action==='more')return again();
          return afterRead();
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
    backoffDelay,patchPath,gateEnabled,validMessage,createSceneLoop,createResolverCommitter,createLeadership});
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
  const SVG_NS='http://www.w3.org/2000/svg';
  /* Un verrou par profil : le meneur tient le long-poll et valide les
     placements. Un seul verrou pour les deux : la validation exige l'état le
     plus frais, que seul le long-poll garantit. */
  const LOCK_NAME='jarvis.scene.leader';
  const CHANNEL_NAME='jarvis.scene';
  const TAB_ID=`${Date.now().toString(36)}-${Math.random().toString(36).slice(2,10)}`;
  /* Zone sensible d'un point (étoile, signal), en pixels. */
  const POINT_HIT=26;
  /* Hauteur minimale dessinée d'une capsule (px), dans la page seulement. */
  const CAPSULE_MIN_HEIGHT=24;
  /* Un anneau ne s'anime que pendant ce délai après l'apparition du nœud ou
     un changement de son état (exécution, urgence) ; ensuite il reste fixe.
     Toute animation CSS en cours coûte un recalcul de style par image : au
     repos, la scène n'en fait aucun. */
  const ANIMATE_FOR_MS=12000;

  /* Registre d'empilement de la page (voir `control_center.html`) : visage 0,
     canevas Omega 0, **scène 20**, barre du haut et indication vocale 31,
     dock 32, panneau 33, bandeau GPT-Live 35, pastilles 40 (Omega : panneau
     42, barre 45, bandeau 48, dock et pastilles 50), fond des réglages 60,
     notifications 70, liste des pastilles 75, menu contextuel 80, Barehands
     2147483000. Les couches de la scène (0–1000) ne s'empilent qu'à
     l'intérieur du conteneur, qui crée son propre contexte. */
  const STYLE=`
.scene{position:absolute;inset:0;z-index:20;pointer-events:none;overflow:hidden;contain:layout paint style;
  font:12px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--sc-ink);
  --sc-ink:#dcecf4;--sc-muted:#8aa5b3;--sc-edge:rgba(151,191,209,.16);--sc-ring:rgba(220,236,244,.66);
  --sc-surface:rgba(4,10,15,.88);--sc-radius:14px;--sc-warn:#ffb85c}
html:not([data-jarvis-theme="omega"]) .scene{--sc-edge:rgba(110,231,255,.2);--sc-radius:7px}
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
/* Gestes (Slice 08) : aucun glissement animé pendant la main de l'utilisateur. */
.scene .sc-node.sc-dragging{transition:none!important;cursor:grabbing}
.scene.sc-gesture{cursor:grabbing}
.sc-capsule,.sc-window{cursor:grab}
.sc-grip{position:absolute;right:3px;bottom:3px;width:13px;height:13px;display:grid;place-items:center;color:var(--sc-muted);cursor:nwse-resize;
  opacity:0;transition:opacity .14s ease-out}
.sc-grip svg{width:9px;height:9px;fill:none;stroke:currentColor;stroke-width:1.4;stroke-linecap:round}
.sc-capsule .sc-grip{right:1px;bottom:0;width:11px;height:11px}
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
.sc-point{width:${POINT_HIT}px;height:${POINT_HIT}px;border-radius:50%}
.sc-point:hover,.sc-point:focus-visible{z-index:2147483000!important}
.sc-mark{position:absolute;left:50%;top:50%;width:8px;height:8px;margin:-4px 0 0 -4px;border-radius:50%;background:var(--tone);
  box-shadow:0 0 0 1px rgba(0,0,0,.4),0 0 14px color-mix(in srgb,var(--tone) 42%,transparent)}
.sc-ring{position:absolute;left:50%;top:50%;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;border:1px solid transparent;pointer-events:none}
/* État d'exécution : indice secondaire. Au plus 24 anneaux animés (.sc-anim) ;
   les autres gardent le même anneau, fixe. */
.sc-exec-running .sc-ring{border-color:var(--sc-ring);opacity:.72}
.sc-exec-running.sc-anim .sc-ring{animation:sc-breathe 2.8s ease-in-out infinite;will-change:transform,opacity}
.sc-exec-pending .sc-ring{border:1px dashed rgba(220,236,244,.5)}
.sc-exec-blocked .sc-ring{width:20px;height:20px;margin:-10px 0 0 -10px;border:3px double rgba(220,236,244,.62)}
/* Terminé : anneau fin et fixe — travail achevé, pas encore rangé. */
.sc-point.sc-exec-completed .sc-ring{width:15px;height:15px;margin:-7.5px 0 0 -7.5px;border:1px solid rgba(220,236,244,.34)}
.sc-signal .sc-mark{width:8px;height:8px;margin:-4px 0 0 -4px;border-radius:1.5px;transform:rotate(45deg)}
.sc-signal.sc-urgency-none .sc-mark{background:transparent;box-shadow:inset 0 0 0 1.5px color-mix(in srgb,var(--tone) 80%,transparent)}
.sc-signal .sc-ring,.sc-signal.sc-exec-completed .sc-ring{width:18px;height:18px;margin:-9px 0 0 -9px;border:0;animation:none;opacity:1}
.sc-signal.sc-urgency-high .sc-ring{border:1.5px solid var(--tone);opacity:.8;transform:scale(1.25)}
.sc-signal.sc-urgency-medium .sc-ring{border:1px solid var(--tone);opacity:.8;transform:scale(1.25)}
.sc-signal.sc-urgency-high.sc-anim .sc-ring{animation:sc-alert 1.9s cubic-bezier(.2,.7,.3,1) infinite;will-change:transform,opacity}
.sc-signal.sc-urgency-medium.sc-anim .sc-ring{animation:sc-alert 3.2s cubic-bezier(.2,.7,.3,1) infinite;will-change:transform,opacity}
.sc-signal.sc-urgency-low .sc-mark{width:6px;height:6px;margin:-3px 0 0 -3px;box-shadow:none}
.sc-signal.sc-urgency-low .sc-ring{width:14px;height:14px;margin:-7px 0 0 -7px;border:1px solid color-mix(in srgb,var(--tone) 38%,transparent);transform:none}
.scene.sc-paused .sc-ring{animation-play-state:paused}
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
.sc-summary{flex:1 1 auto;min-height:0;padding:0 13px 10px;font-size:12px;line-height:1.5;color:#b3cbd6;white-space:pre-wrap;overflow:hidden;overflow-wrap:anywhere;
  -webkit-mask-image:linear-gradient(#000 calc(100% - 22px),transparent);mask-image:linear-gradient(#000 calc(100% - 22px),transparent)}
/* Liste bornée : la dernière ligne visible s'efface au lieu d'être coupée net. */
.sc-items{flex:none;list-style:none;margin:0;padding:8px 13px 11px;display:grid;gap:4px;border-top:1px solid var(--sc-edge);max-height:45%;overflow:hidden;
  -webkit-mask-image:linear-gradient(#000 calc(100% - 20px),transparent);mask-image:linear-gradient(#000 calc(100% - 20px),transparent)}
.sc-items.sc-fits{-webkit-mask-image:none;mask-image:none}
.sc-items li{display:flex;gap:10px;align-items:baseline;min-width:0;font-size:11px}
.sc-items .sc-item-label{min-width:0;flex:1 1 auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#dcecf4}
.sc-items .sc-item-ref{flex:none;max-width:45%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--sc-muted)}
/* Indicateurs : en bas à gauche, sur la ligne de l'indication vocale, hors de
   la zone de composition ; au-dessus du badge Barehands quand il est là. */
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
@media(max-width:700px){.sc-status{left:10px;bottom:12px;max-width:calc(100vw - 90px)}}
@media(prefers-reduced-motion:reduce){
  .scene .sc-node{transition:none!important}
  .scene .sc-ring,.scene .sc-note::before,.scene .sc-node.sc-stopping .sc-ring{animation:none!important}
  .scene .sc-label{transition:none}
}`;

  /* Pictogrammes d'état d'exécution (indice secondaire, jamais la couleur). */
  const BADGE_PATHS={
    failed:'M3.5 3.5l5 5M8.5 3.5l-5 5',
    cancelled:'M3 6h6',
    interrupted:'M4.6 3.3v5.4M7.4 3.3v5.4',
    blocked:'M6 3v3.4M6 8.8v.2',
    completed:'M3.2 6.3l1.9 1.9 3.7-4.4',
  };
  const GRIP_PATH='M10.5 4.5l-6 6M10.5 8l-2.5 2.5';
  const PIN_PATH='M7.5 1.5l3 3-2 1-2.2 2.2.4 2.3-1 1-2-2-2.7 2.7M3.7 6.3l-2-2 1-1 2.3.4L7.2 1.5';
  const REASONS={core_unreachable:'Core injoignable',not_configured:'scène non configurée',scene_unavailable:'scène indisponible',
    core_refused:'Core refuse la lecture',invalid_scene_response:'réponse invalide',timeout:'pas de réponse',
    patch_waits_busy:'trop de pages ouvertes',TypeError:'Control Center injoignable',network_error:'Control Center injoignable'};

  let enabled=false,root=null,linksEl=null,statusEl=null,liveEl=null,raf=0,statusTicker=null;
  let lastView=null,lastState=null,layout=null,layoutState=null,edgesSig='',statusSig='',announced='',readyTimer=0;
  let lastModel=null,focusId=null,tabStopId=null,statusFailed=false,visibilityToken=0,animTimer=0;
  /* Slice 08 : modifications optimistes, geste en cours, édition au clavier. */
  const pending=I?I.createPending():null;
  let viewMemo={state:null,version:-1,value:null},gesture=null,keyEdit=null,kbdMenuAt=0,pruneTimer=0;
  /* Reprise QA : sélection (poignée visible), focus à rendre après un retrait,
     étoiles en cours d'arrêt, délai réel d'un arrêt (lu dans `/api/status`). */
  let selectedId=null,pendingFocus=null,jobCancelTimeoutS=null,serverMemo={state:null,value:null},actionLiveEl=null;
  const stopping=new Map();
  const actionStats={moves:0,resizes:0,representations:0,visibility:0,pins:0,archives:0,bulkArchives:0,stops:0,menus:0,refused:0,failed:0,rolledBack:0};
  const inflight=new Set();
  const freshUntil=new Map();
  const nodes=new Map();
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
  const loop=Core.createSceneLoop({client:Client,request:getJson,...timers,now:()=>Date.now(),random:Math.random,
    createAbort:()=>new AbortController(),onUpdate:onLoopUpdate,log:consoleLog,
    broadcast:channel?message=>channel.postMessage({...message,from:TAB_ID}):null});
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

  function ensureRoot(){
    if(!document.getElementById('jarvisSceneStyle')){
      const style=document.createElement('style');
      style.id='jarvisSceneStyle';style.textContent=STYLE;
      document.head.appendChild(style);
    }
    if(root)return;
    root=document.createElement('div');
    root.id='sceneLayer';root.className='scene';
    root.setAttribute('role','region');
    root.setAttribute('aria-label',I
      ?'Scène constellation. Flèches pour parcourir, Maj+flèches pour déplacer, Ctrl+flèches pour redimensionner, touche Menu ou Maj+F10 pour les actions, Échap pour sortir.'
      :'Scène constellation. Flèches pour parcourir, Échap pour sortir.');
    linksEl=document.createElementNS(SVG_NS,'svg');
    linksEl.setAttribute('class','sc-links');linksEl.setAttribute('aria-hidden','true');
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
    root.addEventListener('keydown',onKeyDown);
    root.addEventListener('keyup',onKeyUp);
    root.addEventListener('pointerover',onPointerOver);
    root.addEventListener('focusin',onFocusIn);
    root.addEventListener('focusout',onFocusOut);
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
    stopStatusTicker();
    if(root)root.remove();
    const style=document.getElementById('jarvisSceneStyle');
    if(style)style.remove();
    if(animTimer){window.clearTimeout(animTimer);animTimer=0}
    root=null;linksEl=null;statusEl=null;liveEl=null;actionLiveEl=null;nodes.clear();freshUntil.clear();
    lastView=null;lastState=null;layout=null;layoutState=null;lastModel=null;
    viewMemo={state:null,version:-1,value:null};serverMemo={state:null,value:null};gesture=null;
    selectedId=null;pendingFocus=null;stopping.clear();
    if(keyEdit&&keyEdit.timer)window.clearTimeout(keyEdit.timer);
    keyEdit=null;
    if(pruneTimer){window.clearTimeout(pruneTimer);pruneTimer=0}
    edgesSig='';statusSig='';announced='';focusId=null;tabStopId=null;
  }

  function scheduleRender(){
    if(!raf)raf=requestAnimationFrame(render);
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

  function badge(exec,shape){
    if(!BADGE_PATHS[exec]||(exec==='completed'&&shape==='point'))return null;
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
    if(node.signal)classes.push('sc-signal',`sc-urgency-${node.urgency}`);
    if(node.pinned)classes.push('sc-pinned');
    if(node.compact)classes.push('sc-compact');
    el.className=classes.join(' ');
    el.setAttribute('aria-label',node.label);
    el.replaceChildren();
    const parts=[];
    if(node.shape==='point'){
      parts.push(element('span','sc-ring'),element('span','sc-mark'));
      const state=badge(node.exec,node.shape);
      if(state&&!node.signal)parts.push(state);
      const label=element('span','sc-label');
      label.append(element('strong','',node.title));
      const detail=[node.signal?'signal':'',node.execLabel,node.signal&&!node.live?'retiré':'',node.pinned?'épinglé':''].filter(Boolean).join(' · ');
      if(detail)label.append(element('span','',detail));
      parts.push(label);
    }else if(node.shape==='capsule'){
      const dot=element('span','sc-dot');dot.appendChild(element('span','sc-ring'));
      parts.push(dot,element('span','sc-title',node.title));
      if(node.pinned)parts.push(pin());
      const state=badge(node.exec,node.shape);if(state)parts.push(state);
      if(I&&(node.representation==='capsule'||node.representation==='window'))parts.push(grip());
    }else{
      const head=element('div','sc-head');
      const dot=element('span','sc-dot');dot.appendChild(element('span','sc-ring'));
      head.append(dot,element('span','sc-cat',[node.category,node.execLabel].filter(Boolean).join(' · ')));
      if(node.pinned)head.append(pin());
      const state=badge(node.exec,node.shape);if(state)head.append(state);
      parts.push(head,element('div','sc-wtitle',node.title));
      if(node.summary)parts.push(element('div','sc-summary',node.summary));
      if(node.items.length){
        const list=element('ul','sc-items');
        for(const item of node.items){
          const row=element('li');
          row.append(element('span','sc-item-label',item.label));
          if(item.ref||item.url)row.append(element('span','sc-item-ref',item.ref||item.url));
          list.append(row);
        }
        parts.push(list);
      }
      if(I)parts.push(grip());
    }
    el.append(...parts);
  }

  function position(el,node){
    let x,y,w=null,h=null;
    if(node.shape==='point'){x=node.cx-POINT_HIT/2;y=node.cy-POINT_HIT/2}
    else if(node.shape==='capsule'){
      w=node.box.width;h=Math.max(node.box.height,CAPSULE_MIN_HEIGHT);x=node.box.left;
      /* Fenêtre dessinée en capsule : collée en haut de sa boîte. */
      y=node.compact?node.box.top:node.cy-h/2;
      if(node.compact)h=CAPSULE_MIN_HEIGHT+4;
    }else{x=node.box.left;y=node.box.top;w=node.box.width;h=node.box.height}
    el.style.transform=`translate(${x}px,${y}px)`;
    el.style.width=w===null?'':`${w}px`;
    el.style.height=h===null?'':`${h}px`;
    el.style.zIndex=String(node.stack);
  }

  function applyNodes(list){
    const seen=new Set();
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
      const content=JSON.stringify([node.shape,node.kind,node.tone,node.exec,node.urgency,node.pinned,node.title,
        node.category,node.summary,node.items,node.label]);
      if(content!==record.content){fill(record.el,node);record.content=content;record.anim=null}
      if(record.anim!==node.animate){record.el.classList.toggle('sc-anim',node.animate);record.anim=node.animate}
      record.el.classList.toggle('sc-selected',node.id===selectedId);
      record.el.classList.toggle('sc-stopping',stopping.has(node.id));
      const place=`${node.shape}|${node.compact}|${node.cx}|${node.cy}|${node.box.left}|${node.box.top}|${node.box.width}|${node.box.height}|${node.stack}`;
      /* Sous la main de l'utilisateur (glisser, clavier) : l'aperçu garde la place. */
      if(place!==record.place&&!record.dragging){position(record.el,node);record.place=place}
    }
    for(const [id,record] of nodes){
      if(seen.has(id))continue;
      record.el.remove();nodes.delete(id);
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
    for(const list of root.querySelectorAll('.sc-items'))list.classList.toggle('sc-fits',list.scrollHeight<=list.clientHeight+1);
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
      el.blur();return;
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
    if(el&&keyEdit&&keyEdit.id===el.dataset.objectId)flushKeyEdit('blur');
  }

  function onFocusIn(event){
    const el=nodeElement(event.target);
    if(!el)return;
    focusId=el.dataset.objectId;
    if(I)select(focusId);
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
  const barehandsActive=()=>!!document.querySelector('#jarvisHands .jh-token');

  /* Aperçu d'une boîte (unités) sur le nœud, dans sa forme dessinée. */
  function previewAt(el,node,box){
    const screen=L.toScreen(viewportNow(),L.drawnBox(node.representation,box));
    position(el,{...node,box:screen,cx:round1(screen.left+screen.width/2),cy:round1(screen.top+screen.height/2)});
  }

  function holdNode(id,held){
    const record=nodes.get(id);
    if(!record)return;
    record.dragging=held;
    record.el.classList.toggle('sc-dragging',held);
    if(!held){record.place='';scheduleRender()}
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
    const steps=[];
    if(!wasPinned&&placed)steps.push('pin');
    steps.push('geometry');
    if(!wasPinned&&!placed)steps.push('pin','geometry');
    let pinnedNow=false;
    for(const step of steps){
      const result=await sendCommand(step==='pin'?I.commands.pin(id):I.commands.setGeometry(id,box));
      if(!result.ok){
        if(pinnedNow&&!wasPinned){
          const undo=await sendCommand(I.commands.unpin(id));
          if(!undo.ok)consoleLog('warn','scene.user_unpin_compensation_failed',{object_id:id,code:undo.code,reason:undo.reason});
        }
        if(pending.rollback(id,token)){actionStats.rolledBack++;pendingChanged()}
        return reportRefusal(step==='pin'?'Épinglage':action,id,result);
      }
      if(step==='pin'){pinnedNow=true;actionStats.pins++}
      pending.confirm(id,token,result.revision);
    }
    prunePending();
    consoleLog('info',kind==='resize'?'scene.user_resized':'scene.user_moved',{object_id:id,steps:steps.join('+')});
  }

  function onPointerDown(event){
    if(event.button!==0||!enabled)return;
    const el=nodeElement(event.target);
    if(!el)return;
    const id=el.dataset.objectId,node=nodeOf(id),box=drawnBox(id),state=viewState();
    const item=state&&state.objects.get(id);
    if(!node||!box||!item)return;
    if(gesture)cancelGesture();
    if(keyEdit)flushKeyEdit('pointer');
    if(typeof closeMenu==='function')closeMenu(false);
    const resize=!!event.target.closest('.sc-grip')&&I.resizable(item.representation);
    gesture={id,el,node,mode:resize?'resize':'move',pointerId:event.pointerId,startX:event.clientX,startY:event.clientY,
      box:{x:box.x,y:box.y,w:box.w,h:box.h},representation:item.representation,moved:false,menuOpened:false,preview:null,
      wasSelected:document.activeElement===el,longTimer:0,
      threshold:I.dragThreshold(event.pointerType,event.pointerId===9001||barehandsActive())};
    /* Appui long sans bouger : menu (Barehands, écran tactile). */
    const current=gesture;
    current.longTimer=window.setTimeout(()=>{
      if(gesture!==current||current.moved)return;
      current.menuOpened=true;
      openObjectMenu(id,{x:current.startX,y:current.startY,above:current.startY},el);
    },I.LONG_PRESS_MS);
    try{el.setPointerCapture(event.pointerId)}catch(_error){/* pointeur synthétique (Barehands) : pas de capture, les événements arrivent au nœud */}
    select(id);
    if(document.activeElement!==el)el.focus({preventScroll:true});
    event.preventDefault();
  }

  function onPointerMove(event){
    const g=gesture;
    if(!g||event.pointerId!==g.pointerId)return;
    const dx=event.clientX-g.startX,dy=event.clientY-g.startY;
    if(!g.moved){
      if(g.menuOpened||Math.hypot(dx,dy)<g.threshold)return;
      g.moved=true;
      window.clearTimeout(g.longTimer);
      holdNode(g.id,true);root.classList.add('sc-gesture');
    }
    const units=I.pxToUnits(viewportNow(),dx,dy);
    g.preview=g.mode==='resize'?I.resizeBox(g.box,units.dx,units.dy,g.representation):I.dragBox(g.box,units.dx,units.dy,g.representation);
    previewAt(g.el,g.node,g.preview);
  }

  function endGesture(g){
    window.clearTimeout(g.longTimer);
    try{if(g.el.hasPointerCapture&&g.el.hasPointerCapture(g.pointerId))g.el.releasePointerCapture(g.pointerId)}catch(_error){/* capture déjà rendue */}
    if(root)root.classList.remove('sc-gesture');
    if(gesture===g)gesture=null;
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
    const box=g.preview;
    holdNode(g.id,false);
    if(!box||I.sameBox(box,g.box))return;
    commitUserGeometry(g.id,box,g.mode).catch(error=>actionFailed(g.mode==='resize'?'Redimensionnement':'Déplacement',g.id,error));
  }

  function cancelGesture(){
    const g=gesture;
    if(!g)return;
    endGesture(g);
    if(g.moved)holdNode(g.id,false);
  }

  function onPointerCancel(event){
    if(gesture&&event.pointerId===gesture.pointerId&&(event.type==='pointercancel'||!gesture.moved))cancelGesture();
  }

  function onContextMenu(event){
    const el=nodeElement(event.target);
    if(!el)return;
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
  function select(id){
    if(selectedId===id)return;
    const previous=selectedId&&nodes.get(selectedId);
    if(previous)previous.el.classList.remove('sc-selected');
    selectedId=id;
    const record=id&&nodes.get(id);
    if(record)record.el.classList.add('sc-selected');
  }

  function onDocumentPointerDown(event){
    if(!selectedId||!root)return;
    const target=event.target;
    if(target&&target.closest&&(target.closest('#sceneLayer .sc-node')||target.closest('#ctxMenu')||target.closest('#confirmBack')))return;
    select(null);
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
      if(!box||!node)return;
      keyEdit={id,el,node,start:{x:box.x,y:box.y,w:box.w,h:box.h},box:{x:box.x,y:box.y,w:box.w,h:box.h},moved:false,timer:0};
      holdNode(id,true);select(id);
    }
    keyEdit.box=I.applyKey(keyEdit.box,intent,item.representation);
    if(intent.type==='move')keyEdit.moved=true;
    previewAt(keyEdit.el,keyEdit.node,keyEdit.box);
    window.clearTimeout(keyEdit.timer);
    keyEdit.timer=window.setTimeout(()=>flushKeyEdit('idle'),700);
  }

  function flushKeyEdit(why){
    const edit=keyEdit;
    if(!edit)return;
    keyEdit=null;
    window.clearTimeout(edit.timer);
    holdNode(edit.id,false);
    if(I.sameBox(edit.box,edit.start))return;
    consoleLog('info','scene.user_key_edit',{object_id:edit.id,why});
    const kind=edit.moved?'move':'resize';
    commitUserGeometry(edit.id,edit.box,kind).catch(error=>actionFailed(kind==='resize'?'Redimensionnement':'Déplacement',edit.id,error));
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
    const model=I.menuModel(state,id,{title:titleOf(id),finished:lastState?I.bulkSelection(lastState).objects:0});
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
    if(act==='stop')return stopJob(id);
    if(act==='archive')return archiveObject(id);
    if(act==='archive-finished')return archiveFinished();
  }

  async function changeRepresentation(id,representation){
    const state=viewState(),item=state&&state.objects.get(id),box=drawnBox(id);
    if(!item||!box)return;
    actionStats.representations++;
    const next=I.representationBox(box,representation,item.kind);
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
    lines.push('Le travail en cours, en attente ou bloqué reste, comme les notes et fenêtres du brain.');
    if(retry)lines.unshift('La scène a changé pendant la confirmation : comptes mis à jour.');
    if(typeof confirmDialog!=='function'){consoleLog('warn','scene.confirm_unavailable',{});return}
    const noun=`${selection.objects} ${selection.objects>1?'objets':'objet'}`;
    if(!await confirmDialog({title:'Archiver les travaux terminés ?',lines,confirmLabel:`Archiver ${noun}`,danger:true}))return;
    inflight.add('bulk');
    const started=Date.now();
    let archived=0,refusal=null;
    try{
      actionStats.bulkArchives++;
      const owners=I.signalOwners(lastState);
      const everything=[...selection.ids];
      for(const [signal,owner] of owners)if(owner&&everything.includes(owner))everything.push(signal);
      planFocusAfterRemoval(everything,`Archivage de ${noun}.`);
      for(const chunk of I.chunkIds(selection.ids)){
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
        const words=I.stopOutcome(body.outcome);
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

  function applyEdges(edges,vp){
    const sig=`${vp.width}x${vp.height}|`+edges.map(e=>`${e.id},${e.kind},${e.signal},${e.tone},${e.x1},${e.y1},${e.x2},${e.y2}`).join(';');
    if(sig===edgesSig)return;
    edgesSig=sig;
    linksEl.setAttribute('viewBox',`0 0 ${vp.width} ${vp.height}`);
    const lines=edges.map(edge=>{
      const line=document.createElementNS(SVG_NS,'line');
      line.setAttribute('x1',edge.x1);line.setAttribute('y1',edge.y1);line.setAttribute('x2',edge.x2);line.setAttribute('y2',edge.y2);
      line.setAttribute('class',`sc-link sc-link-${edge.kind}`+(edge.signal?` sc-link-signal sc-tone-${edge.tone}`:''));
      return line;
    });
    linksEl.replaceChildren(...lines);
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
    applyNodes(lastModel.nodes);
    applyEdges(lastModel.edges,vp);
    renderStatus();
    /* Transitions actives seulement après le premier placement : pas de
       glissement depuis l'origine au chargement. */
    if(!root.classList.contains('sc-ready')&&!readyTimer)
      readyTimer=requestAnimationFrame(()=>{readyTimer=requestAnimationFrame(()=>{readyTimer=0;if(root)root.classList.add('sc-ready')})});
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
    await decideRole();
    if(token!==visibilityToken||!enabled)return;
    loop.setVisible(true);
    scheduleRender();
    pushCommitter();
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
    /* `/api/status` a échoué : la prochaine réussite relance la lecture. */
    statusLost(){statusFailed=true},
    /* Diagnostic (console, validation) : aucune écriture. */
    inspect:()=>{
      const view=loop.view();
      return {enabled,mode:shared?'shared':'solo',role:view.role,leader:{held:leader.held,mode:leader.mode},loop:view.phase,
        revision:lastState?lastState.revision:null,nodes:nodes.size,commits:committer.stats(),stats:view.stats,
        health:lastView?lastView.health:null,resolved:layout&&layoutState===viewState()?layout.resolved.length:0,
        pending:pending?pending.size():0,actions:{...actionStats},gesture:gesture?{id:gesture.id,mode:gesture.mode,moved:gesture.moved,threshold:gesture.threshold}:null,
        selected:selectedId,stopping:[...stopping.keys()],jobCancelTimeoutS,
        tabStops:root?root.querySelectorAll('[tabindex="0"]').length:0,animated:root?root.querySelectorAll('.sc-anim').length:0};
    },
  });
})();
