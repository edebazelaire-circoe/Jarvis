/* Horloge de composition côté navigateur (handoff jarvis-remotion-native-studio-playback-fix, Slice 04 ;
   `docs/presentation-studio.md` > *Composition clock (Level 3)*).

   Portage DIRECT de `jarvis/domain/composition_clock.py`, la seule arithmétique de la composition : mêmes noms (en camelCase), mêmes
   règles, mêmes codes d'erreur. Une table de vecteurs commune (`tests/unit/test_composition_clock_conformance_js.py`) passe dans les
   deux et doit donner le même résultat, au bit près. Module PUR : aucune minuterie, aucun DOM, aucun état mutable.

   Base de temps : fps maître F = le plus grand fps des scènes ; une scène dure ceil(d * F / fps) images maîtres ; image maître locale
   m -> image native floor(m * fps / F) ; image native n -> ceil(n * F / fps). Entiers seulement.

   Le navigateur reçoit la carte de Core (`GET .../variants/{id}/composition-clock`, données) et `fromWire` refait le calcul : un écart est
   refusé (`composition_wire_mismatch`), jamais corrigé en silence ; la clé attendue est obligatoire (`composition_key_required`). Inclus dans
   la page du Control Center (Slice 05) avant `control_center_presentation_studio_sequencer.js`, qui tient `f` pour le lecteur de Variantes. */
(function(root){
  'use strict';
  const WIRE_VERSION=1;
  const MAX_FPS=120;
  const MAX_DURATION_FRAMES=108000;
  const CODES=Object.freeze({EMPTY:'composition_empty',SCENE_INVALID:'composition_scene_invalid',TRANSITION_INVALID:'composition_transition_invalid',
    FRAME_OUT_OF_RANGE:'composition_frame_out_of_range',SCENE_OUT_OF_RANGE:'composition_scene_out_of_range',WIRE_MISMATCH:'composition_wire_mismatch',
    KEY_REQUIRED:'composition_key_required'});
  const SEEKS=Object.freeze(['next','previous','scene','scrub','home','end','step','replay']);

  class CompositionError extends Error{
    constructor(code,message,sceneId){super(message);this.name='CompositionError';this.code=code;this.sceneId=sceneId===undefined?null:sceneId}
  }
  const isInt=v=>typeof v==='number'&&Number.isSafeInteger(v);
  /* Division entière exacte d'entiers >= 0 (pas de Math.floor sur un quotient flottant). */
  const floorDiv=(a,b)=>(a-a%b)/b;
  const ceilDiv=(a,b)=>floorDiv(a+b-1,b);

  function sceneManifest(sceneId,composition){
    if(typeof sceneId!=='string'||!sceneId)throw new CompositionError(CODES.SCENE_INVALID,'a scene has no id');
    const c=composition||{};
    const fps=c.fps,duration=c.duration_in_frames!==undefined?c.duration_in_frames:c.durationInFrames;
    if(typeof c.id!=='string'||!c.id)throw new CompositionError(CODES.SCENE_INVALID,`${sceneId}: the composition has no id`,sceneId);
    if(!isInt(fps)||fps<1||fps>MAX_FPS)throw new CompositionError(CODES.SCENE_INVALID,`${sceneId}: the composition fps must be an integer 1..${MAX_FPS}`,sceneId);
    if(!isInt(duration)||duration<1||duration>MAX_DURATION_FRAMES)
      throw new CompositionError(CODES.SCENE_INVALID,`${sceneId}: the composition duration must be an integer 1..${MAX_DURATION_FRAMES} frames`,sceneId);
    return Object.freeze({scene_id:sceneId,composition_id:c.id,fps,duration_in_frames:duration});
  }

  function build(manifests,transitions){
    if(!Array.isArray(manifests)||manifests.length===0)throw new CompositionError(CODES.EMPTY,'the composition has no scene');
    const checked=manifests.map(m=>sceneManifest(m&&m.scene_id,{id:m&&m.composition_id,fps:m&&m.fps,duration_in_frames:m&&m.duration_in_frames}));
    if(new Set(checked.map(m=>m.scene_id)).size!==checked.length)throw new CompositionError(CODES.SCENE_INVALID,'a scene appears twice in the composition');
    const master=Math.max(...checked.map(m=>m.fps));
    const lengths=checked.map(m=>ceilDiv(m.duration_in_frames*master,m.fps));
    const overlaps=transitions===undefined||transitions===null?checked.map(()=>0):Array.from(transitions);
    if(overlaps.length!==checked.length)throw new CompositionError(CODES.TRANSITION_INVALID,'one transition per scene is required');
    if(overlaps.some(t=>!isInt(t)||t<0)||overlaps[0]!==0)
      throw new CompositionError(CODES.TRANSITION_INVALID,'transitions are integers >= 0 and the first scene has none');
    lengths.forEach((length,k)=>{
      const following=k+1<overlaps.length?overlaps[k+1]:0;
      if(overlaps[k]+following>=length)
        throw new CompositionError(CODES.TRANSITION_INVALID,`${checked[k].scene_id}: transitions leave no frame of its own`,checked[k].scene_id);
    });
    const scenes=[];
    checked.forEach((m,k)=>{
      const start=k===0?0:scenes[k-1].end-overlaps[k];
      scenes.push(Object.freeze({index:k,scene_id:m.scene_id,composition_id:m.composition_id,fps:m.fps,duration_in_frames:m.duration_in_frames,
        start,length:lengths[k],transition_in:overlaps[k],end:start+lengths[k]}));
    });
    return makeMap(master,Object.freeze(scenes),scenes[scenes.length-1].end);
  }

  function makeMap(fps,scenes,totalFrames){
    const lastFrame=totalFrames-1;
    function checkFrame(frame){
      if(!isInt(frame)||frame<0||frame>=totalFrames)throw new CompositionError(CODES.FRAME_OUT_OF_RANGE,`frame must be an integer 0..${lastFrame}`);
      return frame;
    }
    function checkScene(index){
      if(!isInt(index)||index<0||index>=scenes.length)throw new CompositionError(CODES.SCENE_OUT_OF_RANGE,`scene index must be an integer 0..${scenes.length-1}`);
      return scenes[index];
    }
    function locate(frame){
      const f=checkFrame(frame);
      let lo=0,hi=scenes.length-1;
      while(lo<hi){const mid=floorDiv(lo+hi+1,2);if(scenes[mid].start<=f)lo=mid;else hi=mid-1}
      const span=scenes[lo],local=f-span.start;
      return {frame:f,scene_index:span.index,scene_id:span.scene_id,local_frame:local,native_frame:floorDiv(local*span.fps,fps),
        local_progress:local/span.length};
    }
    function clamp(frame){
      if(!isInt(frame))throw new CompositionError(CODES.FRAME_OUT_OF_RANGE,'frame must be an integer');
      return Math.max(0,Math.min(lastFrame,frame));
    }
    function startOf(index){return checkScene(index).start}
    function frameOf(index,nativeFrame){
      const span=checkScene(index);
      if(!isInt(nativeFrame)||nativeFrame<0||nativeFrame>=span.duration_in_frames)
        throw new CompositionError(CODES.FRAME_OUT_OF_RANGE,`native frame must be an integer 0..${span.duration_in_frames-1}`,span.scene_id);
      return span.start+ceilDiv(nativeFrame*fps,span.fps);
    }
    function nextStart(frame){const i=locate(frame).scene_index;return i+1>=scenes.length?null:scenes[i+1].start}
    function previousStart(frame){const i=locate(frame).scene_index;return i===0?0:scenes[i-1].start}
    return Object.freeze({fps,scenes,total_frames:totalFrames,last_frame:lastFrame,checkFrame,locate,clamp,startOf,frameOf,nextStart,previousStart});
  }

  /* ------------------------------------------------ transport (valeur pure : {frame, playing, ended}) */
  const transport=(frame,playing,ended)=>Object.freeze({frame,playing:!!playing,ended:!!ended});
  function settle(map,state){return state.playing&&state.frame===map.last_frame?transport(map.last_frame,false,true):state}
  function play(map,state){map.checkFrame(state.frame);return state.ended?state:settle(map,transport(state.frame,true,false))}
  function pause(map,state){map.checkFrame(state.frame);return transport(state.frame,false,state.ended)}
  function seek(map,state,kind,value){
    const f=map.checkFrame(state.frame);
    let target;
    switch(kind){
      case 'next':target=map.nextStart(f);if(target===null)return state;break;
      case 'previous':target=map.previousStart(f);break;
      case 'scene':target=map.startOf(value);break;
      case 'scrub':target=map.checkFrame(value);break;
      case 'home':target=0;break;
      case 'end':target=map.last_frame;break;
      case 'step':
        if(!isInt(value)||(value!==-1&&value!==1))throw new CompositionError(CODES.FRAME_OUT_OF_RANGE,'a step is -1 or +1');
        if(state.playing)return state;
        target=map.clamp(f+value);break;
      case 'replay':return settle(map,transport(0,true,false));
      default:throw new CompositionError(CODES.FRAME_OUT_OF_RANGE,`unknown seek ${String(kind)}`);
    }
    return settle(map,transport(target,state.playing,false));
  }
  /* Seul le lecteur de la scène COURANTE (celle qui contient f ; pendant un recouvrement, l'entrante) est écouté ; une fin de scène
     ne recule jamais f. */
  function tick(map,state,sceneIndex,nativeFrame,sceneEnded){
    const frame=map.frameOf(sceneIndex,nativeFrame);
    if(sceneIndex!==map.locate(state.frame).scene_index)return state;
    if(sceneEnded){
      if(sceneIndex+1<map.scenes.length)return transport(Math.max(state.frame,map.scenes[sceneIndex+1].start),state.playing,false);
      return transport(map.last_frame,false,true);
    }
    return transport(frame,state.playing,false);
  }

  /* ------------------------------------------------ format servi par Core */
  function fromWire(wire,expected){
    if(!wire||typeof wire!=='object'||wire.version!==WIRE_VERSION||!Array.isArray(wire.scenes))
      throw new CompositionError(CODES.WIRE_MISMATCH,'the composition sent by Core has an unexpected shape');
    if(!expected||typeof expected.key!=='string'||!expected.key)
      throw new CompositionError(CODES.KEY_REQUIRED,'fromWire needs the expected key (the run view or the requested variant): a stale map is never reused');
    if(expected.key!==wire.key)throw new CompositionError(CODES.WIRE_MISMATCH,'the composition belongs to another variant or pin set');
    const map=build(wire.scenes,wire.scenes.map(s=>s&&s.transition_in));
    const same=map.fps===wire.fps&&map.total_frames===wire.total_frames&&map.scenes.every((s,i)=>{
      const w=wire.scenes[i];return s.start===w.start&&s.length===w.length;
    });
    if(!same)throw new CompositionError(CODES.WIRE_MISMATCH,'the composition sent by Core does not match the composition clock arithmetic');
    return Object.freeze(Object.assign({key:wire.key},map));
  }

  const api=Object.freeze({WIRE_VERSION,CODES,SEEKS,CompositionError,sceneManifest,build,fromWire,transport,play,pause,seek,tick});
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.JarvisCompositionClock=api;
})(typeof window!=='undefined'?window:(typeof globalThis!=='undefined'?globalThis:null));
