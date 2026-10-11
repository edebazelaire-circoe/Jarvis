/* Lecture continue d'une variante dans Variantes (handoff jarvis-remotion-native-studio-playback-fix, Slice 05 ;
   `docs/presentation-studio.md` > *Presentation experience contract* § 3-§ 4 et *Composition clock (Level 3)*).

   Ce module enchaîne les scènes Remotion d'une variante dans le lecteur intégré de Variantes (le cadre d'aperçu de
   `control_center_prefab_host.js`), sans fermer Variantes et sans lecture côté Core :
   - la carte de la composition vient de Core (`GET .../variants/{id}/composition-clock`) et est REFAITE ici par
     `JarvisCompositionClock.fromWire` avec la clé attendue (obligatoire). Une carte qui ne correspond pas à l'aperçu affiché (révision
     ou ordre des scènes) est relue UNE fois ; si l'écart reste, « La variante a changé » et l'aperçu est relu. On ne joue jamais une
     carte périmée ;
   - chaque scène joue sa longueur AUTHORED (manifeste), jamais une durée de partition ou un temps par diapositive : seule la fin rapportée
     par le Player de la scène courante fait passer à la suivante, sur son image locale 0 ;
   - la scène suivante est chargée à côté, en pause sur son image 0 (`host.preload`), dès que la scène courante a pris la fenêtre ;
     à la frontière la page la montre (`show`), l'hôte la prend sur-le-champ (échange sans blanc) et `onLive` lui ordonne de jouer ;
   - si elle n'est pas prête, la dernière image de la scène qui part reste à l'écran, avec un indicateur de chargement discret (vue
     `waiting`, compteur) ; un échec de chargement ou de compilation met la lecture en échec, la scène NOMMÉE, jamais sautée ;
   - fin de la composition : la dernière image est tenue (le Player ne boucle pas), `Rejouer` repart de f = 0.

   Le module est un contrôleur sans DOM (testé par node) : la page lui donne l'hôte, la liste des scènes de l'aperçu, la lecture de la
   carte, `show(index)` et `changed(view)`. Une horloge de composition par page (§ 3) : `f` vit ici, rien d'autre ne le déplace.

   Slice 06 (cycle de vie et transport, § 4) : la carte est lue dès que l'aperçu est à l'écran (`prepare`, en pause, rien n'est ordonné) ;
   `seek` est la seule porte du transport visible (⏮ ⏭, barre, Début / Fin, image par image) : `f` cible calculé tout de suite, Player envoyé au
   plus une fois par image d'animation (`requestFrame`) ; `playScene` lit la scène affichée seule puis tient sa dernière image ; `revise` garde
   (scène, image) à travers une nouvelle révision de la variante. */
(function(root){
  'use strict';
  const Clock=root.JarvisCompositionClock||(typeof require==='function'?require('./control_center_composition_clock.js'):null);
  /* L'indicateur de chargement n'apparaît qu'au-delà de ce délai : une frontière normale (scène préchargée) ne le fait jamais clignoter. */
  const WAIT_VISIBLE_MS=300;
  const WAIT_TICK_MS=500;
  const MAX_BOUNDARIES=64;
  /* A Player that halted by itself this close to its last frame has ended (Slice 05 rework, B1): Remotion pauses one step short of the end
     when a frame is dropped and fires `ended` without setting the frame; the sandbox then seeks the last frame, this covers a lost report.
     Never wider: a Player halted further back has not finished, and a user pause is ours (the phase is no longer `playing`). */
  const END_SLACK_FRAMES=2;
  /* A map refused for these reasons will not change by asking again: « Lire » stays disabled with the reason (§ 4.2). */
  const NO_VIDEO=new Set(['composition_empty','composition_scene_not_remotion','composition_scene_invalid']);

  function keyOf(scene){return scene&&scene.prefab?`${scene.prefab.id}@${scene.prefab.version}`:null}
  function describe(error){return error&&typeof error.message==='string'?error.message:String(error)}

  function createSequencer(deps){
    const d=deps||{};
    if(!Clock)throw new Error('JarvisCompositionClock is not loaded');
    for(const name of ['host','fetchClock','scenes','show','changed'])if(typeof d[name]!=='function')throw new TypeError(`createSequencer: ${name} is required`);
    const objectId=d.objectId;
    const now=typeof d.now==='function'?d.now:()=>Date.now();
    const later=typeof d.setTimeout==='function'?d.setTimeout:(fn,ms)=>setTimeout(fn,ms);
    const cancel=typeof d.clearTimeout==='function'?d.clearTimeout:(id)=>clearTimeout(id);
    const log=typeof d.log==='function'?d.log:()=>{};
    const revision=typeof d.revision==='function'?d.revision:()=>null;
    const selectedIndex=typeof d.selectedIndex==='function'?d.selectedIndex:()=>0;
    /* One seek reaches the Player per animation frame at most (§ 4.6). Without it (node benches), a seek reaches it at once. */
    const requestFrame=typeof d.requestFrame==='function'?d.requestFrame:null;
    /* phase : idle (pas de carte) · loading · paused · playing · waiting (la scène voulue n'est pas encore à l'écran) · ended · failed ·
       unavailable (carte refusée à la préparation : pas de vidéo, ou Core injoignable ; la raison est dite, rien ne joue) */
    let S=fresh();
    let waitTimer=null;
    const boundaries=[];

    function fresh(){
      return {phase:'idle',map:null,mapKey:null,t:null,k:-1,want:null,synced:false,ordered:null,waitingSince:0,error:null,retryable:true,generation:0,
        boundaryAt:null,from:null,changed:0,scope:null,pending:false,queued:false,shown:-1};
    }

    function host(){try{return d.host()}catch(_error){return null /* intentional: no host means no playback; the page says why */}}
    function scenes(){const list=d.scenes();return Array.isArray(list)?list:[]}
    function clampIndex(map,index){return Math.max(0,Math.min(map.scenes.length-1,Number.isInteger(index)?index:0))}

    function view(){
      const map=S.map,list=scenes();
      const index=S.k>=0?S.k:(map&&S.t?map.locate(S.t.frame).scene_index:-1);
      const scene=index>=0?list[index]:null;
      return {phase:S.phase,frame:S.t?S.t.frame:null,total_frames:map?map.total_frames:null,fps:map?map.fps:null,playing:S.phase==='playing'||S.phase==='waiting',
        scene_index:index,scene_count:list.length,scene_id:scene?scene.id:null,scene_title:scene?scene.title:null,
        starts:map?map.scenes.map(s=>s.start):null,scope:S.scope===null?'all':'scene',retryable:S.phase!=='unavailable'||S.retryable,
        waiting_ms:S.phase==='waiting'?Math.max(0,now()-S.waitingSince):0,
        waiting_visible:S.phase==='waiting'&&now()-S.waitingSince>=WAIT_VISIBLE_MS,error:S.error?Object.assign({},S.error):null};
    }

    function emit(){
      S.changed++;
      try{d.changed(view())}catch(error){log('sequencer_render_failed',{error:describe(error)},'error')}
    }

    function setPhase(phase){
      S.phase=phase;
      if(phase==='waiting'){
        S.waitingSince=now();
        if(waitTimer===null){
          const tick=()=>{waitTimer=null;if(S.phase!=='waiting')return;emit();waitTimer=later(tick,WAIT_TICK_MS)};
          waitTimer=later(tick,WAIT_VISIBLE_MS);
        }
      }else if(waitTimer!==null){cancel(waitTimer);waitTimer=null}
    }

    function errorOf(code,message,index){
      const list=scenes();
      const scene=Number.isInteger(index)&&index>=0?list[index]:null;
      return {code,message:String(message||code).slice(0,300),scene_index:scene?index:null,scene_id:scene?scene.id:null,scene_title:scene?scene.title:null};
    }

    function fail(code,message,index){
      S.error=errorOf(code,message,index);
      if(S.t&&S.map)S.t=Clock.pause(S.map,S.t);
      setPhase('failed');
      log('sequencer_failed',{code,scene_id:S.error.scene_id,scene_index:S.error.scene_index},'error');
      emit();
    }

    /* The map could not be had while preparing (no video, Core unreachable): said on the transport, never the failure veil; nothing played. */
    function unavailable(code,message,index){
      S.error=errorOf(code,message,index);
      S.retryable=!NO_VIDEO.has(code);
      setPhase('unavailable');
      log('sequencer_unavailable',{code,retryable:S.retryable},S.retryable?'warn':'info');
      emit();
    }

    /* ------------------------------------------------------------ la carte */
    function sameScenes(map){
      const list=scenes();
      return map.scenes.length===list.length&&map.scenes.every((s,i)=>list[i]&&list[i].id===s.scene_id);
    }

    /* `quiet` (prepare, revise): a refusal is `unavailable`, never `failed`, and a mismatch is not sent back to the page (it is reading the
       variant already); the user's « Lire » asks again. */
    async function loadMap(quiet){
      const generation=++S.generation;
      const refuse=quiet?unavailable:fail;
      setPhase('loading');S.error=null;emit();
      for(let attempt=0;attempt<2;attempt++){
        let answer;
        try{answer=await d.fetchClock()}
        catch(error){
          if(generation!==S.generation)return null;
          refuse(error&&error.code||'composition_clock_unreachable',`La carte de la vidéo n'a pas pu être lue : ${describe(error)}`);
          return null;
        }
        if(generation!==S.generation)return null;
        if(!answer||!answer.clock){
          const problem=answer&&answer.problem||{};
          const index=problem.scene_id?scenes().findIndex(s=>s.id===problem.scene_id):-1;
          refuse(problem.code||'composition_clock_missing',problem.message||"Cette variante n'a pas de vidéo à lire.",index>=0?index:undefined);
          return null;
        }
        let map;
        try{map=Clock.fromWire(answer.clock,{key:answer.key})}
        catch(error){refuse(error.code||'composition_wire_mismatch',`Carte de la vidéo refusée : ${describe(error)}`);return null}
        const current=revision();
        if(sameScenes(map)&&(current===null||answer.variant_revision===current)){
          S.map=map;S.mapKey=map.key;
          log('sequencer_map',{key:map.key,scenes:map.scenes.length,total_frames:map.total_frames,fps:map.fps,attempt});
          return map;
        }
        /* Key-mismatch rule (Composition clock, Level 3): the map and the variant on screen disagree. Refetch once, then say it. */
        log('sequencer_map_mismatch',{attempt,variant_revision:answer.variant_revision,shown_revision:current,scenes:map.scenes.length},'warn');
      }
      S.map=null;S.mapKey=null;
      if(quiet){unavailable('variant_changed','La variante a changé : l\'aperçu est relu avant de lire.');return null}
      setPhase('idle');
      S.error={code:'variant_changed',message:'La variante a changé : l\'aperçu est relu avant de lire.',scene_index:null,scene_id:null,scene_title:null};
      emit();
      try{if(typeof d.variantChanged==='function')d.variantChanged()}catch(error){log('sequencer_variant_changed_failed',{error:describe(error)},'error')}
      return null;
    }

    /* ------------------------------------------------------------ le cadre */
    function liveKey(){const h=host();return h&&typeof h.key==='function'?h.key(objectId):null}
    function onScreen(index){
      const h=host();
      return !!h&&h.key(objectId)===keyOf(scenes()[index])&&h.state(objectId)==='ready';
    }

    function order(native){
      const h=host();
      if(!h)return false;
      const ok=h.control(objectId,'play',native)===true;
      S.synced=false;S.ordered=ok?native:null;
      return ok;
    }

    function hold(native){
      const h=host();
      if(h)h.control(objectId,'pause',native);
    }

    /* The scene after `index`, loaded beside the live one, paused on frame 0. Only once `index` itself is the live Player. */
    function preloadAfter(index){
      const h=host();
      const next=scenes()[index+1];
      if(!h||typeof h.preload!=='function'||!next||!next.prefab)return;
      try{h.preload(objectId,{object_id:objectId,scene_id:next.id,prefab:{id:next.prefab.id,version:next.prefab.version},title:next.title,props:next.props||{},data:next.data||{}})}
      catch(error){log('sequencer_preload_failed',{scene_id:next.id,error:describe(error)},'warn')}
    }

    /* Make scene `want.k` the live Player, then play it from `want.native` (or hold there when paused). */
    function bring(index,native){
      S.k=index;S.want={k:index,native};S.pending=false;   // this order supersedes a seek still waiting for its animation frame
      /* The page shows the scene first, even when its Player is already on screen: two scenes on the same source version share the frame and
         differ by their values, title and strip highlight (Slice 06: before, the second one was played under the first one's name). */
      const showing=S.shown!==index;
      if(!showing&&onScreen(index)){arrive();return}
      if(!onScreen(index)&&(S.phase==='playing'||S.phase==='waiting'))setPhase('waiting');
      emit();
      if(showing){
        S.shown=index;
        try{d.show(index)}
        catch(error){fail('scene_show_failed',`La scène n'a pas pu être montée : ${describe(error)}`,index);return}
      }
      if(onScreen(index)&&S.want&&S.want.k===index)arrive();
    }

    /* The wanted scene is the live Player now. */
    function arrive(){
      const want=S.want;
      if(!want)return;
      if(S.phase==='waiting'||S.phase==='playing'){
        if(!order(want.native)){setPhase('waiting');emit();return}   // its Player is not ready yet: `onLive` comes back here
        const at=now();
        if(S.boundaryAt!==null){
          boundaries.push({from:S.from,to:want.k,gap_ms:at-S.boundaryAt,ready_ahead:S.readyAhead===true});
          if(boundaries.length>MAX_BOUNDARIES)boundaries.shift();
          log('sequencer_boundary',{from:S.from,to:want.k,gap_ms:at-S.boundaryAt,ready_ahead:S.readyAhead===true});
          S.boundaryAt=null;
        }
        setPhase('playing');
        S.want=null;
        if(S.scope===null)preloadAfter(want.k);   // one scene only: nothing follows it
      }else{
        hold(want.native);   // paused, ended or failed: the Player shows the target frame and waits (it never plays by itself)
        S.want=null;
      }
      emit();
    }

    /* ------------------------------------------------------------ commandes */
    /* The map, read as soon as the preview is on screen (§ 4.1: Variants opens paused on frame 0 of the selected scene). Nothing is ordered:
       the Player already holds that frame. The scrub, the readout and ⏮ ⏭ can show `f` before anything plays. */
    async function prepare(){
      if(S.map||S.phase==='loading'||!scenes().length)return view();
      const map=await loadMap(true);
      if(!map)return view();
      S.k=S.shown=clampIndex(map,selectedIndex());
      S.t=Clock.transport(map.startOf(S.k),false,false);
      setPhase('paused');
      emit();
      return view();
    }

    async function play(){
      if(S.phase==='playing'||S.phase==='waiting'||S.phase==='loading')return view();
      if(S.phase==='unavailable'&&!S.retryable)return view();
      const list=scenes();
      if(!list.length){fail('composition_empty',"Cette variante n'a aucune scène.");return view()}
      if(!S.map||S.mapKey===null){
        const map=await loadMap(false);
        if(!map)return view();
        S.shown=clampIndex(map,selectedIndex());
        S.t=Clock.transport(map.startOf(S.shown),false,false);
      }
      S.error=null;S.scope=null;
      S.t=S.t.ended?Clock.seek(S.map,S.t,'replay'):Clock.play(S.map,S.t);
      if(S.t.ended){setPhase('ended');emit();return view()}
      const loc=S.map.locate(S.t.frame);
      log('sequencer_play',{frame:S.t.frame,scene_index:loc.scene_index,native_frame:loc.native_frame});
      setPhase('playing');
      S.boundaryAt=null;
      bring(loc.scene_index,loc.native_frame);
      return view();
    }

    /* « Lire seulement cette scène » (§ 5 table, PX-21): the scene that holds `f`, from its local frame 0 to its last frame, then that frame is
       held, paused. Video semantics: no run, nothing armed or spoken, Variants stays open, the scene after it is not loaded ahead. */
    async function playScene(){
      if(S.phase==='loading')return view();
      if(S.phase==='unavailable'&&!S.retryable)return view();
      if(!S.map){
        const map=await loadMap(false);
        if(!map)return view();
        S.shown=clampIndex(map,selectedIndex());
        S.t=Clock.transport(map.startOf(S.shown),false,false);
      }
      const k=S.map.locate(S.t.frame).scene_index;
      S.pending=false;S.error=null;S.boundaryAt=null;S.scope=k;
      S.t=Clock.transport(S.map.startOf(k),true,false);
      log('sequencer_play_scene',{scene_index:k});
      setPhase('playing');
      bring(k,0);
      return view();
    }

    function pause(){
      if(S.phase==='loading'){   // a « Lire » (or a new revision) still reading the map: it is dropped, nothing starts behind the user's back
        S.generation++;
        const h=host();
        try{if(h)h.control(objectId,'pause')}catch(_error){/* intentional: no frame, nothing plays */}
        setPhase(S.map?'paused':'idle');
        emit();
        return view();
      }
      if(!S.map||!S.t)return view();
      if(S.phase==='playing'){const h=host();if(h)h.control(objectId,'pause')}
      if(S.phase==='playing'||S.phase==='waiting'){
        S.t=Clock.pause(S.map,S.t);
        setPhase('paused');
        log('sequencer_pause',{frame:S.t.frame});
        emit();
      }
      return view();
    }

    function toggle(){return S.phase==='playing'||S.phase==='waiting'||S.phase==='loading'?Promise.resolve(pause()):play()}

    /* The transport's one door (§ 4.4-§ 4.7): ⏮ ⏭ (`previous`, `next`), a thumbnail (`scene`), the scrub (`scrub`), Home / End (`home`, `end`),
       `,` `.` (`step`), « Rejouer » (`replay`). The target `f` is computed NOW from `f`, so every visible position follows at once and ten fast
       ⏭ are ten scenes, never two per press and never a drift. The Player is sent there once per animation frame at most, its play state
       kept. `false`: nothing moved (no map yet, next on the last scene, a step while playing, a value out of range). */
    function seek(kind,value){
      if(!S.map||!S.t||S.phase==='loading')return false;
      const wasPlaying=S.phase==='playing'||S.phase==='waiting';
      let next;
      try{next=Clock.seek(S.map,Clock.transport(S.t.frame,wasPlaying,S.t.ended),kind,value)}
      catch(error){log('sequencer_seek_refused',{kind,code:error.code||''},'warn');return false}
      if(next.frame===S.t.frame&&next.playing===wasPlaying&&next.ended===S.t.ended&&kind!=='scene')return false;
      S.t=next;S.error=null;S.boundaryAt=null;S.want=null;
      S.k=S.map.locate(next.frame).scene_index;
      if(next.playing){if(!wasPlaying)setPhase('playing')}
      else setPhase(next.ended?'ended':'paused');
      S.pending=true;
      emit();
      if(!requestFrame){applySeek();return true}
      if(!S.queued){
        S.queued=true;
        const mine=S;
        requestFrame(()=>{if(S!==mine)return;mine.queued=false;applySeek()});
      }
      return true;
    }

    function applySeek(){
      if(!S.pending||!S.map||!S.t)return;
      S.pending=false;
      const loc=S.map.locate(S.t.frame);
      /* « Lire seulement cette scène » stays one scene while the seek lands in it (the slider's Home, PageDown... on the way do not count). */
      if(S.scope!==null&&S.scope!==loc.scene_index)S.scope=null;
      bring(loc.scene_index,loc.native_frame);
    }

    /* A thumbnail: the start of its scene, play state kept (§ 4.5); the thumbnail of the current scene restarts it. */
    function seekScene(index){return Number.isInteger(index)?seek('scene',index):false}

    function retry(){
      if(S.phase!=='failed')return play();
      if(!S.map||!S.t){S.phase='idle';return play()}
      const loc=S.map.locate(S.t.frame);
      S.error=null;S.scope=null;S.t=Clock.play(S.map,S.t);S.shown=-1;   // the failed scene is shown (loaded) again
      setPhase('playing');
      const reloaded=reloadFailed(loc.scene_index);
      log('sequencer_retry',{scene_index:loc.scene_index,reloaded});
      bring(loc.scene_index,loc.native_frame);
      return Promise.resolve(view());
    }

    /* The failed scene's frame took the window with its failure: showing the same pin again is "already there" for the host (it only
       updates its values), so the scene would stay in error and the wait pill count forever (Slice 05 rework, B2). It is loaded again. */
    function reloadFailed(index){
      const h=host();
      if(!h||typeof h.reload!=='function'||h.key(objectId)!==keyOf(scenes()[index])||h.state(objectId)!=='error')return false;
      try{return h.reload(objectId)===true}
      catch(error){log('sequencer_reload_failed',{scene_index:index,error:describe(error)},'warn');return false}
    }

    /* Variant changed, comparison opened, Variants closed: playback stops where it is and the map is dropped (a new variant has a new key). */
    function reset(reason){
      if(S.phase==='idle'&&!S.map&&!S.error)return;
      if(S.phase==='playing'){const h=host();try{if(h)h.control(objectId,'pause')}catch(_error){/* intentional: the frame may already be gone */}}
      log('sequencer_reset',{reason:reason||'',phase:S.phase});
      setPhase('idle');
      S=Object.assign(fresh(),{generation:S.generation+1});
      emit();
    }

    /* A new revision of the variant on screen (hot reload, an agent edit) while the map exists (§ 4.9, PX-19). The position is kept as
       (scene_id, the scene's own frame), clamped to the scene's new length; the map is read again; the play state is kept, and the Player of
       the new pin is sent there once it took the window (it swaps in place). A scene that is gone leaves its place in the order: the scene now
       at that index, from its start. The map refused (no video any more): playback stops, said on the transport. */
    async function revise(){
      if(!S.map||!S.t)return view();
      const loc=S.map.locate(S.t.frame);
      const keep={scene_id:loc.scene_id,index:loc.scene_index,native:loc.native_frame,playing:S.phase==='playing'||S.phase==='waiting',scope:S.scope!==null};
      /* The Player on screen holds where it is while the new version loads: it resumes from the kept frame, it never runs on ahead of it. */
      if(keep.playing){const h=host();try{if(h)h.control(objectId,'pause')}catch(_error){/* intentional: the frame may already be gone */}}
      S.map=null;S.mapKey=null;S.want=null;S.pending=false;S.scope=null;S.shown=-1;   // the page shows the new revision's scene
      const map=await loadMap(true);
      if(!map)return view();
      let k=map.scenes.findIndex(s=>s.scene_id===keep.scene_id),native=keep.native;
      if(k<0){k=clampIndex(map,keep.index);native=0}
      native=Math.min(native,map.scenes[k].duration_in_frames-1);
      S.t=Clock.transport(map.frameOf(k,native),keep.playing,false);
      S.scope=keep.scope&&map.scenes[k].scene_id===keep.scene_id?k:null;
      setPhase(keep.playing?'playing':'paused');
      log('sequencer_revised',{scene_id:map.scenes[k].scene_id,native_frame:native,kept:map.scenes[k].scene_id===keep.scene_id,playing:keep.playing});
      bring(k,native);
      return view();
    }

    /* ------------------------------------------------------------ ce que l'hôte dit */
    function onLive(id){
      if(id!==objectId||!S.want)return;
      if(liveKey()===keyOf(scenes()[S.want.k]))arrive();
    }

    function onClock(id){
      /* A seek waiting for its animation frame: the Player still reports where it was, which is no longer `f`. */
      if(id!==objectId||S.phase!=='playing'||!S.map||S.k<0||S.pending)return;
      const h=host();
      if(!h||h.key(objectId)!==keyOf(scenes()[S.k]))return;   // another frame (a stale one, or the one being left): not ours to read
      const clock=h.clock(objectId);
      if(!clock)return;
      const span=S.map.scenes[S.k];
      const last=span.duration_in_frames-1;
      const frame=Math.max(0,Math.min(last,clock.frame));
      if(!S.synced){
        /* A clock posted before our order reached the Player still describes the old position: it is believed only once the Player is
           seen where it was sent (playing from the ordered frame, within one second), or already on its last frame when sent there. */
        const from=S.ordered===null?0:S.ordered;
        const near=clock.playing&&frame>=from&&frame<=from+span.fps;
        if(!near&&!(from>=last&&frame>=last))return;
        S.synced=true;
      }
      if(frame>=last||(!clock.playing&&frame>=last-END_SLACK_FRAMES)){
        if(S.scope===S.k){
          /* One scene only: its last frame is held, paused (the Player does not loop: it stays there by itself, nothing is ordered). */
          S.t=Clock.pause(S.map,Clock.transport(S.map.frameOf(S.k,last),true,false));
          S.scope=null;
          setPhase('paused');
          log('sequencer_scene_held',{scene_index:S.k,frame:S.t.frame});
          emit();
          return;
        }
        S.boundaryAt=now();S.from=S.k;
        S.t=Clock.tick(S.map,S.t,S.k,last,true);
        if(S.t.ended){
          setPhase('ended');S.boundaryAt=null;
          log('sequencer_ended',{frame:S.t.frame,total_frames:S.map.total_frames});
          emit();
          return;
        }
        const loc=S.map.locate(S.t.frame);
        const parked=typeof h.parked==='function'&&h.parked(objectId)&&h.pendingKey(objectId)===keyOf(scenes()[loc.scene_index]);
        S.readyAhead=parked;
        bring(loc.scene_index,loc.native_frame);
        return;
      }
      const f=S.map.frameOf(S.k,frame);
      if(f>=S.t.frame){S.t=Clock.tick(S.map,S.t,S.k,frame,false);emit()}
    }

    function onOutcome(info){
      if(!info||info.object_id!==objectId||info.outcome!=='failed')return;
      const key=info.prefab?`${info.prefab.id}@${info.prefab.version}`:null;
      const list=scenes();
      if(S.want&&key===keyOf(list[S.want.k])&&(S.phase==='waiting'||S.phase==='playing')){
        const index=S.want.k;
        S.want=null;
        fail(info.reason==='timeout'?'scene_timeout':'scene_failed',info.message||info.reason||'échec du chargement',index);
        return;
      }
      if(S.phase==='playing'&&key===keyOf(list[S.k]))fail('scene_failed',info.message||info.reason||'échec de la scène',S.k);
      else log('sequencer_preload_lost',{prefab:key,reason:info.reason||''},'warn');   // a scene loaded ahead failed: it is loaded again at its turn
    }

    return Object.freeze({prepare,play,playScene,pause,toggle,seek,seekScene,retry,revise,reset,onLive,onClock,onOutcome,view,
      active:()=>!!S.map,stats:()=>({phase:S.phase,frame:S.t?S.t.frame:null,boundaries:boundaries.slice(),changed:S.changed})});
  }

  const api=Object.freeze({WAIT_VISIBLE_MS,END_SLACK_FRAMES,createSequencer,keyOf});
  root.JarvisVariantsSequencer=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
