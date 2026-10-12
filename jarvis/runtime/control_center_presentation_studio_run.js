/* Une lecture de présentation DANS Variantes (handoff jarvis-remotion-native-studio-playback-fix, Slice 09 ; contrat
   `docs/presentation-studio.md` › *2026-10 § 2* et *§ 5*, section *Variants run surface (Level 3, Slice 09)*).

   Avant la Slice 09, une lecture se montrait dans une fenêtre du Board (`studio-stage-<run_id>`) avec une bande flottante : la « vue
   flottante » retirée. Désormais Core tient la lecture sur une surface en MÉMOIRE (`RunSurface`, id `variants-run-<run_id>`) et
   Variantes la monte dans SON lecteur (le même hôte de prefabs que la vidéo continue : `autoplay: false`, `embed: 'variants'`). Ce module
   est sans DOM, exposé en `window.JarvisVariantsRun` et en `module.exports` pour node :

   - `createRunAdapter(deps)` : monte la surface (`jarvis:studio-surface`) sous son id, applique la ligne de temps de la partition
     (`jarvis:studio-timeline`, `JarvisRemotionFrame.createTimelineFollower`), charge à côté la scène qui suit, montre les détours en
     calques DANS la scène (jamais une fenêtre), et ne joue rien de lui-même : le lecteur reste en pause sur l'image 0 jusqu'à l'ordre de
     Core (plus de lecture de grâce : la course du constat 7 de la Slice 07 n'existe plus). Seule exception, dite : une scène dont Core n'a
     pas pu lire la ligne de temps (`view.timeline_unresolved`) se joue UNE fois depuis l'image 0, sans pilotage, comme avant ;
   - `presenterModel(view, nowMs)` : la bande du présentateur (§ 5 : qui présente, phase, « Scène n/N · élément i/M », l'élément suivant et
     sa cue, le suivi vocal, le temps de PARTITION contre l'objectif souple, les problèmes), pure ;
   - `keyCommand(action, view)` : la colonne « Presenter run » de la carte § 4.15 (Espace pause / reprise, → ← élément suivant / précédent,
     Début / Fin premier / dernier élément, S sortir d'une séquence) ; `F`, `M`, `Échap` restent ceux de Variantes. */
(function(root){
  'use strict';
  /* Read on use: in the page the playback client's script comes after this one (and after the explorer). */
  const Player=()=>root.JarvisStudioPlayerCore||(typeof require==='function'?require('./control_center_presentation_studio_player.js'):null);
  const SURFACE_PREFIX='variants-run-';
  const SCORE_TIME_TITLE='Temps de partition passé sur cet élément / objectif souple (jamais une limite, jamais le temps de la vidéo)';

  function isRun(view){return !!view&&view.running===true&&view.phase!=='stopped'&&view.phase!=='idle'}
  function isSurface(id){return typeof id==='string'&&id.startsWith(SURFACE_PREFIX)}
  function describe(error){return String(error&&error.message||error||'erreur inconnue').slice(0,200)}

  /* `deps`: host() -> the Variants prefab host or null, slot() -> the stage slot, overlaySlot() -> the overlay layer of the stage,
     frames -> `JarvisRemotionFrame` (its `createTimelineFollower`), onSegment(report), log(key, data, level), and the page's clock for the
     follower (now, setInterval, clearInterval). */
  function createRunAdapter(deps){
    const d=deps||{};
    const log=typeof d.log==='function'?d.log:()=>{};
    const stats={surfaces:0,mounted:0,timelines:0,preloads:0,unguided:0,overlays:0,cleared:0};
    let surface=null,objectId=null,follower=null,unguidedFor=null,unresolved=null;
    const overlays=new Map();   // overlay_id -> prefab key

    function host(){const h=typeof d.host==='function'?d.host():null;return h&&typeof h.mount==='function'?h:null}
    function ensureFollower(){
      if(follower)return follower;
      const R=d.frames;
      if(!R||typeof R.createTimelineFollower!=='function')return null;
      follower=R.createTimelineFollower({getHost:()=>host(),now:d.now,setInterval:d.setInterval,clearInterval:d.clearInterval,
        onSegment:(report)=>{if(typeof d.onSegment==='function')d.onSegment(report)},
        log:(level,key,data)=>log('run_'+String(key).replace(/^timeline\./,'timeline_'),data,level==='warn'?'warn':'info')});
      return follower;
    }
    /* The surface Core shows for the run: its scene under the surface id (a new scene takes the frame loaded ahead; a new pin of the same
       scene is a hot reload), and the detour overlays that are visible. `null`: the run is over, everything goes. */
    function applySurface(next){
      if(!next){clear();return 'cleared'}
      const h=host();
      if(!h)return 'no_host';
      if(objectId&&objectId!==next.surface_id)clear();
      objectId=next.surface_id;surface=next;stats.surfaces+=1;
      if(next.prefab&&typeof d.slot==='function'&&d.slot()){
        try{
          h.mount(d.slot(),{object_id:objectId,scene_id:next.scene_id||undefined,prefab:{id:next.prefab.id,version:next.prefab.version},
            title:next.title||'',props:next.prefab.props||{},data:next.prefab.data||{}});
          stats.mounted+=1;
        }catch(error){log('run_mount_failed',{object_id:objectId,error:describe(error)},'error');return 'failed'}
      }
      syncOverlays(h,Array.isArray(next.overlays)?next.overlays:[]);
      maybeUnguided();
      return 'mounted';
    }
    function syncOverlays(h,list){
      const wanted=new Map();
      for(const o of list)if(o&&o.visible===true&&typeof o.overlay_id==='string'&&o.prefab)wanted.set(o.overlay_id,o);
      for(const id of Array.from(overlays.keys()))if(!wanted.has(id)){try{h.unmount(id)}catch(_e){/* intentional: the frame is gone either way */}overlays.delete(id)}
      const slot=typeof d.overlaySlot==='function'?d.overlaySlot():null;
      if(!slot)return;
      for(const [id,o] of wanted){
        try{h.mount(slot,{object_id:id,prefab:{id:o.prefab.id,version:o.prefab.version},title:o.title||'',props:o.prefab.props||{},data:o.prefab.data||{}});
          if(!overlays.has(id))stats.overlays+=1;overlays.set(id,`${o.prefab.id}@${o.prefab.version}`)}
        catch(error){log('run_overlay_failed',{overlay_id:id,error:describe(error)},'error')}
      }
    }
    /* What the score asks of the Player (`view.timeline`), and the scene that follows, loaded beside the live one, paused. */
    function applyTimeline(detail){
      if(!detail||!objectId)return 'none';
      if(detail.object_id!==objectId){if(follower&&!detail.timeline)follower.clear();return 'other'}
      const h=host();
      const ahead=detail.preload;
      if(h&&ahead&&ahead.prefab&&typeof h.preload==='function'){
        try{if(h.preload(objectId,{object_id:objectId,scene_id:ahead.scene_id,prefab:{id:ahead.prefab.id,version:ahead.prefab.version},
          title:ahead.title,props:ahead.prefab.props,data:ahead.prefab.data}))stats.preloads+=1}
        catch(error){log('run_preload_failed',{error:describe(error)},'warn')}
      }
      const f=ensureFollower();
      if(!f)return 'no_follower';
      stats.timelines+=1;
      return f.apply({object_id:objectId,timeline:detail.timeline||null});
    }
    /* `view.timeline_unresolved` names the scene whose timeline Core could not read: no order will come for it. */
    function setUnresolved(sceneId){unresolved=typeof sceneId==='string'?sceneId:null;maybeUnguided()}
    function maybeUnguided(){
      const h=host();
      if(!h||!surface||!unresolved||surface.scene_id!==unresolved)return false;
      const key=`${objectId}|${surface.revision}`;
      if(unguidedFor===key||typeof h.control!=='function')return false;
      if(h.control(objectId,'play',0)!==true)return false;   // not ready yet: `onLive` tries again
      unguidedFor=key;stats.unguided+=1;
      log('run_unguided_play',{object_id:objectId,scene_id:unresolved},'warn');
      return true;
    }
    function onLive(id){if(id!==objectId)return;if(follower)follower.refresh(id);maybeUnguided()}
    function onClock(id){if(follower&&id===objectId)follower.onClock(id)}
    function clear(){
      const h=host();
      if(follower)follower.clear();
      if(h){
        if(objectId){try{h.unmount(objectId)}catch(_e){/* intentional: the frame is gone either way */}}
        for(const id of overlays.keys()){try{h.unmount(id)}catch(_e){/* intentional */}}
      }
      if(objectId||surface)stats.cleared+=1;
      overlays.clear();surface=null;objectId=null;unguidedFor=null;unresolved=null;
    }
    return {applySurface,applyTimeline,setUnresolved,onLive,onClock,clear,
      objectId:()=>objectId,surface:()=>surface,owns:(id)=>isSurface(id)&&(id===objectId||overlays.has(id)),
      stats:()=>Object.assign({},stats,{follower:follower?follower.stats():null})};
  }

  /* ------------------------------------------------------------------ the presenter strip (§ 5), pure */
  function seconds(ms){return (Math.max(0,ms)/1000).toFixed(1).replace('.',',')+' s'}
  function voiceState(view){
    if(!view.jarvis_speaks)return null;
    const presenter=view.presenter||{};
    if(view.speaking==='jarvis')return {state:'speaking',text:'Jarvis parle'};
    if(view.phase==='paused'||view.phase==='detour')return {state:'paused',text:'Jarvis se tait (pause)'};
    if(presenter.line==='pending'&&view.phase==='playing')return {state:'waiting',text:'Jarvis va parler…'};
    return {state:'quiet',text:'Jarvis se tait'};
  }
  /* `view`: Core's playback view; `elapsedMs`: the item's score time now (`view.elapsed.item_ms` advanced locally while it plays). */
  function presenterModel(view,elapsedMs,extra){
    const P=Player();
    const v=view||{};
    const x=extra||{};
    if(!isRun(v))return {active:false};
    const phase=v.phase||'idle';
    const pending=v.pending==='pause'?' · pause demandée':v.pending==='detour'?' · détour demandé':'';
    const scene=v.scene||{},pos=v.position||{},item=v.item||{};
    const who=item.presenter==='user'?'vous':item.presenter==='jarvis'?'Jarvis':'silence';
    const el=v.elapsed||{};
    const ms=Math.max(0,Number.isFinite(elapsedMs)?elapsedMs:(el.item_ms||0));
    const next=v.next;
    const lines=[];
    if(v.jarvis_speaks)lines.push('Jarvis présente : mode réglé sur SIMPLE pour cette lecture, rétabli à l\'arrêt.');
    if(v.art_direction==='fallback')lines.push('Direction artistique de secours (aucune n\'a été choisie).');
    else if(v.art_direction==='none')lines.push('Répétition sans direction artistique.');
    if(v.pending)lines.push(v.pending==='pause'?'Pause demandée : elle prend effet à la fin de l\'élément en cours (séquence ou parole qui ne se coupe pas).':
      'Détour demandé : il s\'affiche à la fin de l\'élément en cours.');
    if(v.presenter&&v.presenter.interrupted&&(phase==='paused'||v.pending==='pause'))lines.push(
      'Interrompu : Jarvis attend votre « continuer » (il reprendra la ligne depuis son début), il ne repart jamais seul.');
    if(v.follower==='absent')lines.push(P.FOLLOWER_ABSENT);
    else if(v.follower==='waiting')lines.push(P.FOLLOWER_WAITING);
    const pageWait=v.page_wait?P.pageWaitText(v.page_wait,scene):null;
    if(pageWait)lines.push(pageWait);
    const problems=[...(v.problems||[]),...(v.notices||[])].map(code=>P.PROBLEMS[code]||(String(code).startsWith('stage_')?`La scène n'a pas suivi (${code}).`:`Problème : ${code}`));
    lines.push(...problems);
    if(x.linkLostMs)lines.push(`Core ne répond plus depuis ${Math.round(x.linkLostMs/1000)} s : l'état affiché peut être périmé.`);
    const seq=v.presenter&&v.presenter.sequence;
    let sequence=null;
    if(seq&&seq.duration_ms&&seq.state!=='done'&&seq.state!=='idle'){
      const done=Math.min(seq.duration_ms,seq.elapsed_ms||0);
      sequence={text:seq.state==='waiting_start'?'Séquence verrouillée : attente du début de la parole…':
        `Séquence ${seq.step}/${seq.of} · ${seconds(done)} / ${seconds(seq.duration_ms)}`+(phase==='paused'?' · en pause':''),
        percent:Math.max(0,Math.min(100,Math.round(done*100/seq.duration_ms)))};
    }
    const busy=!!x.busy;
    const moving=phase==='detour'||phase==='paused'||phase==='resuming';
    return {active:true,
      role:P.ROLE_LABEL[v.role]||'Présentation',phase:(P.PHASE_LABEL[phase]||phase)+pending,phaseKey:phase,
      where:`Scène ${scene.number||'?'}/${scene.of||'?'} · élément ${pos.index||'?'}/${pos.of||'?'}`,sceneTitle:scene.title||'(sans titre)',
      item:`${item.label||'Élément'} · ${who}`+(v.silence?' (silence voulu)':'')+(v.sequence?` · séquence ${v.sequence.step}/${v.sequence.of}`:'')+
        (v.detour?` · détour : ${v.detour.title}`:''),
      next:next?`Ensuite : ${next.item_label||next.scene_title||'élément suivant'}`+
        (next.cue&&next.cue.armable?` — dites « ${(next.cue.phrases||[])[0]||next.cue.label} »`+(next.cue.armed?'':' (pas encore armé)'):''):'Dernier élément.',
      clock:'Partition '+P.clock(ms)+(el.item_target_ms?` / ${P.clock(el.item_target_ms)}`:''),clockTitle:SCORE_TIME_TITLE,
      over:!!(el.item_target_ms&&ms>el.item_target_ms),voice:voiceState(v),sequence,lines,
      kind:problems.length||pageWait||v.follower==='absent'||x.linkLostMs?'problem':'ok',
      pause:{label:phase==='paused'?(v.jarvis_speaks?'Continuer':'Reprendre'):v.pending==='pause'?'Pause demandée…':'Pause',
        command:phase==='paused'?'resume':'pause',disabled:busy||phase==='detour'||phase==='ended'||v.pending==='pause'},
      previous:{disabled:busy||moving},nextItem:{disabled:busy||moving||phase==='ended'},
      skip:!!v.sequence,variantId:v.variant_id||null,presentationId:v.presentation_id||null,sceneId:scene.scene_id||null,runId:v.run_id||null};
  }

  /* § 4.15, column « Presenter run ». `action`: `JarvisVariantsStageMedia.keyAction` (or `skip` for S). Returns `{verb, body}` or a refusal
     sentence (`said`), or null when the key is not the run's (F, M, Échap stay Variants'). */
  function keyCommand(action,view){
    const v=view||{};
    if(!isRun(v))return null;
    if(action==='toggle')return {verb:v.phase==='paused'?'resume':'pause',body:{}};
    if(action==='next')return {verb:'next',body:{}};
    if(action==='previous')return {verb:'previous',body:{}};
    if(action==='home')return {verb:'goto',body:{position:1}};
    if(action==='end')return {verb:'goto',body:{position:(v.position&&v.position.of)||1}};
    if(action==='step_back'||action==='step_forward')return {said:'Image par image : seulement en vidéo continue. Pendant la présentation, la partition mène.'};
    if(action==='skip')return v.sequence?{verb:'skip_sequence',body:{}}:{said:'Aucune séquence verrouillée n\'est en cours.'};
    return null;
  }

  /* The presenter strip under the stage (windowed only: it is outside the « theater », the fullscreen target), the detour overlay inside the
     stage, the tree chip. Same tokens as the explorer (`--jvx-*`); no animation but the speaking dot, which reduced motion stops. */
  const H='#jvStudioExplorer';
  const CSS=`
${H} .jvx-stage-overlay{position:absolute;inset:6%;z-index:2;display:flex;border-radius:12px;overflow:hidden;border:1px solid var(--jvx-line-strong);
  background:#02060a;box-shadow:0 18px 50px rgba(0,0,0,.6)}
${H} .jvx-stage-overlay[hidden]{display:none}
${H} .jvx-stage-overlay .sc-prefab-slot{position:relative;flex:1 1 auto;display:flex;flex-direction:column}
${H} .jvx-stage-overlay .sc-prefab-frame{flex:1 1 auto!important;height:100%!important;max-height:none!important}
${H} .jvx-presenter{display:grid;gap:6px;padding:10px 12px;border-radius:10px;border:1px solid var(--jvx-line);background:rgba(2,6,10,.45);
  font-size:13px;line-height:1.45;color:var(--jvx-ink);min-width:0}
${H} .jvx-presenter[hidden]{display:none}
${H} .jvx-presenter[data-kind="problem"]{border-color:var(--jvx-warn)}
${H} .jvx-presenter-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px}
${H} .jvx-presenter-role{color:var(--jvx-accent)}
${H} .jvx-presenter-clock{margin-left:auto;font:12px/1 ui-monospace,Consolas,monospace;font-variant-numeric:tabular-nums;color:var(--jvx-mute)}
${H} .jvx-presenter-clock[data-over="1"]{color:var(--jvx-warn)}
${H} .jvx-presenter-voice{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--jvx-mute)}
${H} .jvx-presenter-voice::before{content:"";width:8px;height:8px;border-radius:50%;background:currentColor;opacity:.55}
${H} .jvx-presenter-voice[data-state="speaking"]{color:var(--jvx-accent)}
${H} .jvx-presenter-voice[data-state="speaking"]::before{opacity:1}
@media (prefers-reduced-motion:no-preference){${H} .jvx-presenter-voice[data-state="speaking"]::before{animation:jvxPulse 1.1s ease-in-out infinite}}
${H} .jvx-presenter-voice[hidden]{display:none}
${H} .jvx-presenter-where{font-weight:600;overflow-wrap:anywhere}
${H} .jvx-presenter-line{margin:0;color:var(--jvx-mute);overflow-wrap:anywhere}
${H} .jvx-presenter-line:empty{display:none}
${H} .jvx-presenter-note{margin:0;color:var(--jvx-warn);overflow-wrap:anywhere}
${H} .jvx-presenter-note:empty{display:none}
${H} .jvx-presenter-seq{display:grid;gap:4px;font-size:12px;color:var(--jvx-mute);font-variant-numeric:tabular-nums}
${H} .jvx-presenter-seq[hidden]{display:none}
${H} .jvx-presenter-seqbar{height:6px;border-radius:999px;border:1px solid var(--jvx-line);overflow:hidden}
${H} .jvx-presenter-seqbar>span{display:block;height:100%;width:0;background:var(--jvx-accent)}
${H} .jvx-presenter-actions{display:flex;flex-wrap:wrap;gap:8px;justify-content:flex-end}
${H} .jvx-presenter-actions .jvx-btn[hidden]{display:none}
${H} .jvx-transport .jvx-btn[hidden]{display:none}
${H} .jvx-btn[data-act="stop_run"],${H} .jvx-presenter-actions .jvx-btn[data-danger]{border-color:var(--jvx-danger);color:var(--jvx-danger)}
@media (forced-colors:active){${H} .jvx-presenter{border-color:CanvasText}${H} .jvx-presenter-seqbar>span{background:Highlight}}
`;

  const api=Object.freeze({SURFACE_PREFIX,SCORE_TIME_TITLE,CSS,isRun,isSurface,createRunAdapter,presenterModel,keyCommand});
  root.JarvisVariantsRun=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
