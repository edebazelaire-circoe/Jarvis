/* Scène constellation dans le Control Center : boucle de lecture, validation
   des placements du résolveur et rendu (handoff
   jarvis-constellation-scene-runtime, Slice 05).

   Deux parties, comme `control_center_barehands.js` :
   - `JarvisScenePageCore`, logique pure à dépendances injectées (requêtes,
     minuteries, horloge, hasard) : machine d'états de la boucle de long-poll
     et validation « une fois par objet » des placements du résolveur. Les
     tests l'exécutent avec node et de fausses minuteries ;
   - un bloc navigateur : conteneur de scène, relations SVG, nœuds DOM, verrou
     entre onglets, interrupteur `scene.enabled`. Les tests node ne l'exécutent
     pas.

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

  const errorCode=error=>String(error&&(error.code||error.name)||'network_error');
  const errorMessage=error=>String(error&&error.message||'');

  /* Boucle d'une page : un seul long-poll à la fois.

     Phases : `off` (interrupteur éteint), `paused` (onglet caché), `loading`
     (instantané), `polling` (long-poll), `waiting` (délai avant nouvel essai),
     `stopped` (page quittée). `deps` : `client` (JarvisSceneClient),
     `request(path, {signal, timeoutMs})` → corps JSON (rejette sur échec
     réseau ou HTTP), `setTimeout`, `clearTimeout`, `now`, `random`,
     `createAbort`, `onUpdate(vue)`, `log(level, event, data)`.

     - Instantané au démarrage et à chaque resynchronisation ; patchs ensuite.
     - `retry` (plafond de long-polls du Control Center) : attendre
       `retry_after_ms` (+ jusqu'à 250 ms), sans relire l'instantané.
     - `unavailable` ou erreur : garder l'état, attendre avec repli exponentiel.
     - Plus de deux resynchronisations de suite : repli avant de relire.
     - Onglet caché : requête en cours abandonnée ; au retour, reprise par les
       patchs depuis la révision tenue (resynchronisation si Core ne les a
       plus).
     - Toute réponse d'une requête abandonnée est ignorée (génération). */
  function createSceneLoop(deps){
    const client=deps.client;
    const okHealth=()=>({level:'ok',code:null,message:'',since:null,retryAt:null});
    let enabled=false,visible=true,stopped=false;
    let phase='off',generation=0,timer=null,abort=null,state=null;
    let failures=0,resyncs=0,objectLimit=512,health=okHealth();
    const stats={snapshots:0,polls:0,resyncs:0,retries:0,errors:0};

    const log=(level,event,data)=>{if(deps.log)deps.log(level,event,data||{})};
    const view=()=>({phase,state,health:{...health},objectLimit,stats:{...stats}});
    function emit(){if(deps.onUpdate)deps.onUpdate(view())}

    function cancel(){
      generation++;
      if(timer!==null){deps.clearTimeout(timer);timer=null}
      if(abort){const pending=abort;abort=null;try{pending.abort()}catch(_error){/* déjà abandonnée */}}
      health.retryAt=null;
    }

    function wait(ms,next){
      const current=++generation;
      phase='waiting';health.retryAt=deps.now()+ms;
      timer=deps.setTimeout(()=>{if(current!==generation)return;timer=null;health.retryAt=null;next()},ms);
      emit();
    }

    function degrade(code,message){
      failures++;stats.errors++;
      if(health.level!=='degraded'){
        health={level:'degraded',code,message:message||'',since:deps.now(),retryAt:null};
        log('warn','scene.view_degraded',{code,message:message||''});
      }else{
        health={...health,code,message:message||health.message};
      }
    }

    function recover(){
      failures=0;
      if(health.level==='ok')return;
      log('info','scene.view_restored',{code:health.code,after_ms:deps.now()-health.since});
      health=okHealth();
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
        log('info','scene.snapshot_loaded',{revision:state.revision,objects:state.objects.size});
        poll();
      },error=>{
        degrade(errorCode(error),errorMessage(error));
        wait(backoffDelay(failures,deps.random),load);
      });
    }

    function poll(){
      if(!state)return load();
      phase='polling';stats.polls++;
      emit();
      request(patchPath(client.patchQuery(state,LONG_POLL_WAIT_S)),POLL_TIMEOUT_MS,body=>{
        const result=client.applyPatchResponse(state,body);
        if(result.state)state=result.state;
        switch(result.action){
          case 'applied':case 'unchanged':case 'more':
            resyncs=0;recover();return poll();
          case 'retry':
            stats.retries++;
            return wait(Math.max(0,Number(result.retry_after_ms)||0)+Math.round(deps.random()*250),poll);
          case 'resync':
            stats.resyncs++;resyncs++;
            log('info','scene.resync',{reason:result.reason});
            if(resyncs>2)return wait(backoffDelay(resyncs-2,deps.random),load);
            return load();
          default:
            degrade(result.reason,String(body&&body.error&&body.error.message||''));
            return wait(backoffDelay(failures,deps.random),poll);
        }
      },error=>{
        degrade(errorCode(error),errorMessage(error));
        wait(backoffDelay(failures,deps.random),poll);
      });
    }

    function evaluate(){
      if(stopped)return;
      if(!enabled){
        if(phase==='off')return;
        cancel();phase='off';state=null;failures=0;resyncs=0;health=okHealth();
        log('info','scene.loop_off',{});
        return emit();
      }
      if(!visible){
        if(phase==='paused')return;
        cancel();phase='paused';
        log('info','scene.loop_paused',{revision:state?state.revision:null});
        return emit();
      }
      if(phase!=='off'&&phase!=='paused')return;
      log('info','scene.loop_started',{catch_up:!!state});
      if(state)poll();else load();
    }

    return {
      setEnabled(value){enabled=!!value;evaluate()},
      setVisible(value){visible=!!value;evaluate()},
      stop(){if(stopped)return;cancel();stopped=true;phase='stopped';emit()},
      view,
    };
  }

  /* Validation des placements du résolveur (`set_geometry`,
     `placed_by = resolver`, par le relais utilisateur du Control Center).

     - Seul l'onglet qui tient le verrou (`input.leader`) valide, et seulement
       quand sa lecture est à jour (`input.healthy`) ; les autres dessinent le
       même placement (résolveur déterministe) sans rien envoyer.
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
    backoffDelay,patchPath,gateEnabled,createSceneLoop,createResolverCommitter});
})();

/* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
if(typeof module!=='undefined'&&module.exports)module.exports=JarvisScenePageCore;

/* --------------------------------------------------------------------------
   Bloc navigateur : conteneur, relations, nœuds, verrou, interrupteur.
   -------------------------------------------------------------------------- */
(function installJarvisScene(){
  if(typeof window==='undefined'||typeof document==='undefined')return;
  const L=window.JarvisSceneLayout,Client=window.JarvisSceneClient,Core=JarvisScenePageCore;
  if(!L||!Client)return;
  const SVG_NS='http://www.w3.org/2000/svg';
  const LOCK_NAME='jarvis.scene.resolver';
  /* Zone sensible d'un point (étoile, signal), en pixels. */
  const POINT_HIT=26;

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
.sc-node{position:absolute;left:0;top:0;pointer-events:auto;outline:none;box-sizing:border-box}
/* Seul le déplacement glisse (composition) ; une taille change d'un coup. */
.scene.sc-ready .sc-node{transition:transform .42s cubic-bezier(.16,1,.3,1)}
.sc-point{width:${POINT_HIT}px;height:${POINT_HIT}px;border-radius:50%}
.sc-point:hover,.sc-point:focus-visible{z-index:2147483000!important}
.sc-mark{position:absolute;left:50%;top:50%;width:8px;height:8px;margin:-4px 0 0 -4px;border-radius:50%;background:var(--tone);
  box-shadow:0 0 0 1px rgba(0,0,0,.4),0 0 14px color-mix(in srgb,var(--tone) 42%,transparent)}
.sc-ring{position:absolute;left:50%;top:50%;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;border:1px solid transparent;pointer-events:none}
.sc-exec-running .sc-ring{border-color:var(--sc-ring);animation:sc-breathe 2.8s ease-in-out infinite}
.sc-exec-pending .sc-ring{border:1px dashed rgba(220,236,244,.5)}
.sc-exec-blocked .sc-ring{width:20px;height:20px;margin:-10px 0 0 -10px;border:3px double rgba(220,236,244,.62)}
.sc-signal .sc-mark{width:8px;height:8px;margin:-4px 0 0 -4px;border-radius:1.5px;transform:rotate(45deg)}
.sc-signal.sc-urgency-none .sc-mark{background:transparent;box-shadow:inset 0 0 0 1.5px color-mix(in srgb,var(--tone) 80%,transparent)}
.sc-signal .sc-ring{border:0;animation:none}
.sc-signal.sc-urgency-high .sc-ring{border:1.5px solid var(--tone);animation:sc-alert 1.9s cubic-bezier(.2,.7,.3,1) infinite}
.sc-signal.sc-urgency-medium .sc-ring{border:1px solid var(--tone);animation:sc-alert 3.2s cubic-bezier(.2,.7,.3,1) infinite}
.sc-signal.sc-urgency-low .sc-mark{width:6px;height:6px;margin:-3px 0 0 -3px;box-shadow:none}
.sc-signal.sc-urgency-low .sc-ring{width:14px;height:14px;margin:-7px 0 0 -7px;border:1px solid color-mix(in srgb,var(--tone) 38%,transparent)}
.sc-badge{position:absolute;right:0;top:0;width:12px;height:12px;border-radius:50%;background:#061017;display:grid;place-items:center;
  color:var(--sc-ink);box-shadow:0 0 0 1px rgba(220,236,244,.46)}
/* Sur un point, en bas à droite : le haut droit est la place du signal. */
.sc-point .sc-badge{top:auto;bottom:1px;right:1px}
.sc-badge svg{width:8px;height:8px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.sc-label{position:absolute;left:50%;top:100%;display:flex;gap:7px;align-items:baseline;white-space:nowrap;max-width:min(42ch,70vw);
  padding:4px 10px;border-radius:999px;background:rgba(3,8,12,.92);box-shadow:inset 0 0 0 1px var(--sc-edge),0 8px 22px rgba(0,0,0,.4);
  font-size:11px;opacity:0;visibility:hidden;transform:translate(-50%,2px);transition:opacity .16s ease-out,transform .16s ease-out,visibility 0s .16s;pointer-events:none}
.sc-label strong{min-width:0;overflow:hidden;text-overflow:ellipsis;font-weight:600;color:#f1f8fb}
.sc-label span{flex:none;font-size:9.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--sc-muted)}
.sc-point:hover .sc-label,.sc-point:focus-visible .sc-label{opacity:1;visibility:visible;transform:translate(-50%,6px);transition:opacity .16s ease-out,transform .16s ease-out}
.sc-point:focus-visible .sc-mark{outline:1px solid var(--sc-ink);outline-offset:5px}
.sc-capsule{display:flex;align-items:center;gap:8px;padding:0 12px 0 11px;border-radius:999px;background:var(--sc-surface);overflow:hidden;
  box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--tone) 32%,rgba(151,191,209,.14)),0 10px 28px rgba(0,0,0,.34)}
.sc-dot{position:relative;flex:none;width:7px;height:7px;border-radius:50%;background:var(--tone);box-shadow:0 0 10px color-mix(in srgb,var(--tone) 40%,transparent)}
.sc-dot .sc-ring{width:15px;height:15px;margin:-7.5px 0 0 -7.5px}
.sc-title{min-width:0;flex:1 1 auto;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:12px;letter-spacing:.01em;color:#eaf5fa}
.sc-capsule .sc-badge,.sc-window .sc-badge{position:relative;flex:none}
.sc-pin{flex:none;width:11px;height:11px;color:var(--sc-muted)}
.sc-pin svg{width:11px;height:11px;fill:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round;display:block}
.sc-capsule:focus-visible,.sc-window:focus-visible{box-shadow:inset 0 0 0 1px var(--sc-ink),0 10px 28px rgba(0,0,0,.34)}
.sc-window{display:flex;flex-direction:column;border-radius:var(--sc-radius);background:rgba(4,10,15,.9);overflow:hidden;
  box-shadow:inset 0 1px 0 color-mix(in srgb,var(--tone) 72%,transparent),inset 0 0 0 1px var(--sc-edge),0 24px 64px rgba(0,0,0,.5);
  backdrop-filter:blur(18px)}
.sc-head{display:flex;align-items:center;gap:8px;padding:11px 13px 3px;flex:none}
.sc-cat{min-width:0;flex:1 1 auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:9.5px;letter-spacing:.12em;text-transform:uppercase;
  color:color-mix(in srgb,var(--tone) 72%,var(--sc-ink))}
.sc-wtitle{flex:none;padding:0 13px 8px;font-size:13px;font-weight:600;line-height:1.35;color:#f1f8fb;overflow:hidden;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow-wrap:anywhere}
.sc-summary{flex:1 1 auto;min-height:0;padding:0 13px 10px;-webkit-mask-image:linear-gradient(#000 calc(100% - 22px),transparent);mask-image:linear-gradient(#000 calc(100% - 22px),transparent);font-size:12px;line-height:1.5;color:#b3cbd6;white-space:pre-wrap;overflow:hidden;overflow-wrap:anywhere}
.sc-items{flex:none;list-style:none;margin:0;padding:8px 13px 11px;display:grid;gap:4px;border-top:1px solid var(--sc-edge);max-height:45%;overflow:hidden}
.sc-items li{display:flex;gap:10px;align-items:baseline;min-width:0;font-size:11px}
.sc-items .sc-item-label{min-width:0;flex:1 1 auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#dcecf4}
.sc-items .sc-item-ref{flex:none;max-width:45%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--sc-muted)}
.sc-status{position:absolute;left:18px;top:64px;z-index:2147483600;display:grid;gap:5px;justify-items:start;pointer-events:none}
.sc-status[hidden]{display:none}
.sc-note{display:flex;align-items:center;gap:8px;max-width:min(460px,calc(100vw - 110px));padding:6px 12px 6px 10px;border-radius:999px;
  background:rgba(3,8,12,.66);box-shadow:inset 0 0 0 1px var(--sc-edge);backdrop-filter:blur(14px);
  font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:rgba(214,232,240,.8);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sc-note::before{content:'';flex:none;width:6px;height:6px;border-radius:50%;background:var(--sc-muted)}
.sc-note.sc-warn::before{background:var(--sc-warn)}
.sc-note.sc-full::before{background:#ff6b7d}
.sc-note.sc-busy::before{animation:sc-breathe 1.6s ease-in-out infinite;background:var(--sc-ink)}
@keyframes sc-breathe{0%,100%{opacity:.32;transform:scale(.86)}50%{opacity:.9;transform:scale(1.08)}}
@keyframes sc-alert{0%{opacity:.95;transform:scale(.62)}80%,100%{opacity:0;transform:scale(1.75)}}
@media(max-width:700px){.sc-status{left:10px;top:56px}}
@media(prefers-reduced-motion:reduce){
  .scene .sc-node{transition:none!important}
  .scene .sc-ring,.scene .sc-note::before{animation:none!important}
  .scene .sc-signal.sc-urgency-high .sc-ring,.scene .sc-signal.sc-urgency-medium .sc-ring{opacity:.8;transform:scale(1.25)}
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
  const PIN_PATH='M7.5 1.5l3 3-2 1-2.2 2.2.4 2.3-1 1-2-2-2.7 2.7M3.7 6.3l-2-2 1-1 2.3.4L7.2 1.5';
  const REASONS={core_unreachable:'Core injoignable',not_configured:'scène non configurée',scene_unavailable:'scène indisponible dans Core',
    core_refused:'Core refuse la lecture',invalid_scene_response:'réponse de scène invalide',timeout:'pas de réponse',
    patch_waits_busy:'trop de pages ouvertes',TypeError:'Control Center injoignable',network_error:'Control Center injoignable'};

  let enabled=false,root=null,linksEl=null,statusEl=null,raf=0,statusTicker=null;
  let lastView=null,lastState=null,layout=null,edgesSig='',statusSig='',readyTimer=0;
  const nodes=new Map();
  const leader={held:false,release:null,abort:null,mode:'lock'};

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
    createAbort:()=>new AbortController(),onUpdate:onLoopUpdate,log:consoleLog});
  const committer=Core.createResolverCommitter({layout:L,...timers,now:()=>Date.now(),random:Math.random,log:consoleLog,
    post:command=>requestJson('/api/scene/commands',{method:'POST',body:command,timeoutMs:15000})});

  /* ------------------------------------------------------------ verrou */

  function pushCommitter(){
    if(!enabled||!lastView)return committer.update(null);
    /* Seulement en long-poll sain : pendant une relecture, l'état tenu peut
       être périmé et un objet déjà placé ailleurs paraître libre. */
    const healthy=!!lastView.state&&lastView.health.level==='ok'&&lastView.phase==='polling';
    committer.update({state:lastView.state,layout,leader:leader.held,healthy});
  }

  /* Un seul onglet valide les placements : verrou Web Locks du navigateur,
     tenu tant que l'onglet est visible et la scène allumée. Sans Web Locks,
     l'onglet valide seul (le résolveur est déterministe et chaque objet n'est
     envoyé qu'une fois par page). */
  function acquireLeadership(){
    if(leader.held||leader.abort)return;
    const locks=navigator.locks;
    if(!locks||typeof locks.request!=='function'){
      leader.held=true;leader.mode='solo';
      consoleLog('info','scene.resolver_leader',{mode:'solo'});
      return pushCommitter();
    }
    const controller=new AbortController();
    leader.abort=controller;
    locks.request(LOCK_NAME,{signal:controller.signal},()=>new Promise(release=>{
      leader.abort=null;leader.held=true;leader.release=release;leader.mode='lock';
      consoleLog('info','scene.resolver_leader',{mode:'lock'});
      pushCommitter();
    })).catch(error=>{
      if(error&&error.name==='AbortError')return;
      leader.abort=null;leader.held=true;leader.mode='solo';
      consoleLog('warn','scene.resolver_lock_failed',{error:String(error&&error.message||error)});
      pushCommitter();
    });
  }

  function releaseLeadership(){
    if(leader.abort){const pending=leader.abort;leader.abort=null;pending.abort()}
    if(leader.release){const release=leader.release;leader.release=null;release()}
    leader.held=false;
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
    root.setAttribute('role','region');root.setAttribute('aria-label','Scène constellation');
    linksEl=document.createElementNS(SVG_NS,'svg');
    linksEl.setAttribute('class','sc-links');linksEl.setAttribute('aria-hidden','true');
    statusEl=document.createElement('div');
    statusEl.className='sc-status';statusEl.setAttribute('role','status');statusEl.setAttribute('aria-live','polite');statusEl.hidden=true;
    root.append(linksEl,statusEl);
    (document.getElementById('app')||document.body).appendChild(root);
  }

  function teardown(){
    if(raf){cancelAnimationFrame(raf);raf=0}
    if(readyTimer){cancelAnimationFrame(readyTimer);readyTimer=0}
    stopStatusTicker();
    if(root)root.remove();
    root=null;linksEl=null;statusEl=null;nodes.clear();
    lastView=null;lastState=null;layout=null;edgesSig='';statusSig='';
  }

  function scheduleRender(){
    if(!raf)raf=requestAnimationFrame(render);
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

  function badge(exec,representation){
    if(!BADGE_PATHS[exec]||(exec==='completed'&&representation==='point'))return null;
    const box=element('span','sc-badge');
    box.appendChild(svgIcon(BADGE_PATHS[exec]));
    return box;
  }

  function pin(){
    const box=element('span','sc-pin');
    box.appendChild(svgIcon(PIN_PATH));
    return box;
  }

  /* Contenu d'un nœud. Tout texte de la scène passe par `textContent`, déjà
     neutralisé par `JarvisSceneLayout.viewModel`. */
  function fill(el,node){
    const classes=['sc-node',`sc-${node.representation}`,`sc-kind-${node.kind}`,`sc-tone-${node.tone}`,`sc-exec-${node.exec}`];
    if(node.signal)classes.push('sc-signal',`sc-urgency-${node.urgency}`);
    if(node.pinned)classes.push('sc-pinned');
    el.className=classes.join(' ');
    el.setAttribute('aria-label',node.label);
    el.replaceChildren();
    const parts=[];
    if(node.representation==='point'){
      parts.push(element('span','sc-ring'),element('span','sc-mark'));
      const state=badge(node.exec,node.representation);
      if(state&&!node.signal)parts.push(state);
      const label=element('span','sc-label');
      label.append(element('strong','',node.title));
      const detail=[node.signal?node.category:'',node.execLabel,node.signal&&!node.live?'retiré':'',node.pinned?'épinglé':''].filter(Boolean).join(' · ');
      if(detail)label.append(element('span','',detail));
      parts.push(label);
    }else if(node.representation==='capsule'){
      const dot=element('span','sc-dot');dot.appendChild(element('span','sc-ring'));
      parts.push(dot,element('span','sc-title',node.title));
      if(node.pinned)parts.push(pin());
      const state=badge(node.exec,node.representation);if(state)parts.push(state);
    }else{
      const head=element('div','sc-head');
      const dot=element('span','sc-dot');dot.appendChild(element('span','sc-ring'));
      head.append(dot,element('span','sc-cat',[node.category,node.execLabel].filter(Boolean).join(' · ')));
      if(node.pinned)head.append(pin());
      const state=badge(node.exec,node.representation);if(state)head.append(state);
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
    }
    el.append(...parts);
  }

  function position(el,node){
    let x,y,w=null,h=null;
    if(node.representation==='point'){x=node.cx-POINT_HIT/2;y=node.cy-POINT_HIT/2}
    else{x=node.box.left;y=node.box.top;w=node.box.width;h=node.box.height}
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
        el.tabIndex=0;el.dataset.objectId=node.id;el.setAttribute('role','group');
        root.appendChild(el);
        record={el,content:'',place:''};
        nodes.set(node.id,record);
      }
      const content=JSON.stringify([node.representation,node.kind,node.tone,node.exec,node.urgency,node.pinned,node.title,
        node.category,node.summary,node.items,node.label]);
      if(content!==record.content){fill(record.el,node);record.content=content}
      const place=`${node.representation}|${node.cx}|${node.cy}|${node.box.left}|${node.box.top}|${node.box.width}|${node.box.height}|${node.stack}`;
      if(place!==record.place){position(record.el,node);record.place=place}
    }
    for(const [id,record] of nodes){
      if(seen.has(id))continue;
      record.el.remove();nodes.delete(id);
    }
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

  let lastModel=null;

  function render(){
    raf=0;
    if(!enabled||!root)return;
    if(!lastState||!layout){applyNodes([]);applyEdges([],{width:1,height:1});lastModel=null;return renderStatus()}
    const vp=L.viewport(root.clientWidth||window.innerWidth,root.clientHeight||window.innerHeight);
    lastModel=L.viewModel(lastState,layout,vp,{objectLimit:lastView?lastView.objectLimit:L.OBJECT_LIMIT});
    applyNodes(lastModel.nodes);
    applyEdges(lastModel.edges,vp);
    renderStatus();
    /* Transitions actives seulement après le premier placement : pas de
       glissement depuis l'origine au chargement. */
    if(!root.classList.contains('sc-ready')&&!readyTimer)
      readyTimer=requestAnimationFrame(()=>{readyTimer=requestAnimationFrame(()=>{readyTimer=0;if(root)root.classList.add('sc-ready')})});
  }

  function elapsed(ms){
    const s=Math.max(0,Math.round(ms/1000));
    return s<60?`${s} s`:`${Math.floor(s/60)} min ${String(s%60).padStart(2,'0')} s`;
  }

  function stopStatusTicker(){if(statusTicker){window.clearInterval(statusTicker);statusTicker=null}}

  /* Indicateur discret, jamais bloquant : chargement, lecture en panne (depuis
     combien de temps, nouvel essai automatique), scène pleine, objets hors
     champ. Réécrit seulement si son texte change. */
  function renderStatus(){
    if(!statusEl||!lastView)return;
    const notes=[];
    const health=lastView.health;
    if(health.level==='degraded'){
      const reason=REASONS[health.code]||health.code||'erreur';
      const retry=health.retryAt?` · nouvel essai dans ${elapsed(health.retryAt-Date.now())}`:' · nouvel essai…';
      notes.push({cls:'sc-warn',text:`${lastState?'Scène figée':'Scène indisponible'} — ${reason} · depuis ${elapsed(Date.now()-health.since)}${retry}`});
      if(!statusTicker)statusTicker=window.setInterval(renderStatus,1000);
    }else{
      stopStatusTicker();
      if(!lastState&&lastView.phase==='loading')notes.push({cls:'sc-busy',text:'Scène · chargement…'});
    }
    if(lastModel&&lastModel.capacity.saturated)
      notes.push({cls:'sc-full',text:`Scène pleine (${lastModel.capacity.objects}/${lastModel.capacity.limit}) — archiver des travaux terminés`});
    if(lastModel&&lastModel.offscreen)
      notes.push({cls:'',text:`${lastModel.offscreen} ${lastModel.offscreen>1?'objets':'objet'} hors champ`});
    const sig=notes.map(n=>`${n.cls}:${n.text}`).join('|');
    if(sig===statusSig)return;
    statusSig=sig;
    statusEl.replaceChildren(...notes.map(n=>element('div',`sc-note ${n.cls}`.trim(),n.text)));
    statusEl.hidden=!notes.length;
  }

  function onLoopUpdate(view){
    if(!enabled)return;
    lastView=view;
    if(view.state!==lastState){
      lastState=view.state;
      layout=lastState?L.resolveLayout(lastState):null;
      scheduleRender();
    }
    renderStatus();
    pushCommitter();
  }

  function onResize(){scheduleRender()}

  function onVisibility(){
    const visible=document.visibilityState!=='hidden';
    loop.setVisible(visible);
    if(enabled&&visible)acquireLeadership();else releaseLeadership();
    pushCommitter();
  }

  /* Interrupteur : appelé à chaque lecture réussie de `/api/status`. */
  function gate(scene){
    const next=Core.gateEnabled(scene);
    if(next===enabled)return;
    enabled=next;
    if(next){
      consoleLog('info','scene.enabled',{source:scene&&scene.source||''});
      ensureRoot();
      window.addEventListener('resize',onResize);
      document.addEventListener('visibilitychange',onVisibility);
      onVisibility();
      loop.setEnabled(true);
    }else{
      consoleLog('info','scene.disabled',{});
      loop.setEnabled(false);
      committer.update(null);
      releaseLeadership();
      window.removeEventListener('resize',onResize);
      document.removeEventListener('visibilitychange',onVisibility);
      teardown();
    }
  }

  window.addEventListener('pagehide',event=>{
    if(event.persisted){releaseLeadership();return}
    loop.stop();committer.stop();releaseLeadership();
  });

  window.JarvisScene=Object.freeze({
    version:1,gate,
    /* Diagnostic (console, validation) : aucune écriture. */
    inspect:()=>({enabled,leader:{held:leader.held,mode:leader.mode},loop:loop.view().phase,
      revision:lastState?lastState.revision:null,nodes:nodes.size,commits:committer.stats(),
      health:lastView?lastView.health:null,resolved:layout?layout.resolved.length:0}),
  });
})();
