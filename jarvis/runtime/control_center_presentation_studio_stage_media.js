/* Son, plein écran de la scène et clavier du lecteur de Variantes (handoff jarvis-remotion-native-studio-playback-fix, Slice 08 ;
   contrat `docs/presentation-studio.md` § 4.12 à § 4.16, section *Variants media and fullscreen (Level 3, Slice 08)*).

   Contrôleurs SANS DOM, exposés en `window.JarvisVariantsStageMedia` et en `module.exports` pour node. L'explorateur leur donne ses
   minuteries, son hôte de prefabs et ses fonctions d'affichage ; eux tiennent l'état :
   - `keyAction(key)` : la carte § 4.15 d'une touche (une seule table pour la scène, le transport, la bande et les touches que la scène
     relaie quand elle a le focus) ;
   - `createSound(deps)` : le son voulu (« Son », `M`), muet à l'ouverture, donné à l'hôte (`host.sound(muted)`), gardé d'une scène à
     l'autre ; un refus du navigateur (`audio.blocked`) est dit en français avec ce qu'il faut faire, jamais un silence ;
   - `createChrome(deps)` : le transport en surimpression du plein écran de la scène, qui se cache seul pendant la lecture
     (`CHROME_HIDE_MS`) et revient au moindre mouvement, à une touche, à la pause. */
(function(root){
  'use strict';
  const CHROME_HIDE_MS=2500;
  const KEY_ACTIONS=Object.freeze({' ':'toggle',ArrowRight:'next',PageDown:'next',ArrowLeft:'previous',PageUp:'previous',Home:'home',End:'end',
    ',':'step_back','.':'step_forward',f:'fullscreen',F:'fullscreen',m:'sound',M:'sound',Escape:'escape'});
  const TEXT=Object.freeze({
    on:'Son activé.',
    off:'Son coupé.',
    titleOff:'Activer le son (M)',
    titleOn:'Couper le son (M)',
    titleBlocked:"Son refusé par le navigateur : cliquez une fois dans l'image de la scène (M coupe le son)",
    blocked:"Le navigateur a refusé le son de cette scène. Cliquez une fois dans l'image de la scène pour l'autoriser, "
      +"ou autorisez le son pour ce site (icône à gauche de l'adresse, puis « Son » : « Autoriser »).",
    pill:"Son refusé par le navigateur : cliquez une fois dans l'image.",
    unavailable:"Le son n'est pas disponible : le lecteur de scènes n'est pas chargé dans cette page.",
  });

  function keyAction(key){return Object.prototype.hasOwnProperty.call(KEY_ACTIONS,key)?KEY_ACTIONS[key]:null}

  /* Le son voulu. `deps`: host() -> prefab host or null, log(key, data, level), say(kind, text), announce(text), changed(). */
  function createSound(deps){
    const d=deps||{};
    const state={on:false,blocked:false,blockedSaid:false,toggles:0,refusals:0};
    function host(){const h=typeof d.host==='function'?d.host():null;return h&&typeof h.sound==='function'?h:null}
    function push(){
      const h=host();
      if(!h)return false;
      try{h.sound(!state.on);return true}
      catch(error){d.log('sound_failed',{error:String(error&&error.message||error)},'error');return false}
    }
    function changed(){if(typeof d.changed==='function')d.changed()}
    /* `set(on)`: the user's wish (a click on « Son », `M`). Turning it off always works; turning it on is tried by the scene's Player, which
       answers `audio` (`onAudio`). */
    function set(on){
      state.on=!!on;state.blocked=false;state.blockedSaid=false;state.toggles+=1;
      if(!push()&&state.on){d.say('failed',TEXT.unavailable);state.on=false}
      d.log('sound',{on:state.on});
      d.announce(state.on?TEXT.on:TEXT.off);
      changed();
      return state.on;
    }
    function toggle(){return set(!state.on)}
    /* The preview host was (re)created: it starts muted unless the user turned the sound on in this opening. */
    function attach(){push()}
    function onAudio(audio){
      if(!audio||typeof audio!=='object')return;
      if(state.on&&audio.blocked===true){
        state.blocked=true;state.refusals+=1;
        if(!state.blockedSaid){state.blockedSaid=true;d.say('failed',TEXT.blocked);d.log('sound_blocked',{refusals:state.refusals},'warn')}
      }else if(state.on&&audio.blocked===false&&audio.muted===false&&state.blocked){
        state.blocked=false;state.blockedSaid=false;d.log('sound_unblocked',{})
      }
      changed();
    }
    function reset(){state.on=false;state.blocked=false;state.blockedSaid=false}
    function view(){
      return {on:state.on,blocked:state.on&&state.blocked,pressed:state.on,
        title:state.on?(state.blocked?TEXT.titleBlocked:TEXT.titleOn):TEXT.titleOff,pill:state.on&&state.blocked?TEXT.pill:'',
        toggles:state.toggles,refusals:state.refusals};
    }
    return {set,toggle,attach,onAudio,reset,view};
  }

  /* The transport over the stage in fullscreen. `deps`: setTimeout, clearTimeout, apply(hidden), playing() -> bool, pinned() -> bool (the
     focus is in the transport, a menu is open: it stays). Never animated here: the fade is CSS, off under reduced motion. */
  function createChrome(deps){
    const d=deps||{};
    const state={active:false,hidden:false,timer:null,shows:0,hides:0};
    function cancel(){if(state.timer!==null){d.clearTimeout(state.timer);state.timer=null}}
    function setHidden(hidden){
      if(state.hidden===hidden)return;
      state.hidden=hidden;
      if(hidden)state.hides+=1;else state.shows+=1;
      d.apply(hidden);
    }
    function schedule(){
      cancel();
      if(!state.active||!d.playing()||d.pinned())return;
      state.timer=d.setTimeout(()=>{state.timer=null;if(state.active&&d.playing()&&!d.pinned())setHidden(true)},CHROME_HIDE_MS);
    }
    /* A move, a key, a focus: the transport shows, and hides again after `CHROME_HIDE_MS` if the video plays. */
    function poke(){if(!state.active)return;setHidden(false);schedule()}
    function enter(){state.active=true;state.hidden=true;setHidden(false);schedule()}
    function exit(){state.active=false;cancel();setHidden(false)}
    /* The play state changed: paused (or ended) keeps the transport on screen; playing starts the countdown. */
    function sync(){if(!state.active)return;if(!d.playing()){cancel();setHidden(false)}else if(!state.hidden&&state.timer===null)schedule()}
    return {enter,exit,poke,sync,view:()=>({active:state.active,hidden:state.hidden,armed:state.timer!==null,shows:state.shows,hides:state.hides})};
  }

  const api=Object.freeze({CHROME_HIDE_MS,KEY_ACTIONS,TEXT,keyAction,createSound,createChrome});
  root.JarvisVariantsStageMedia=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
