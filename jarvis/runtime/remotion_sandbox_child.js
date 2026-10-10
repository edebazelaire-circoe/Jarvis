/* Amorce du bac à sable d'une scène Remotion (handoff jarvis-remotion-presentation-integration, Slice 06 ;
   `docs/remotion-isolation.md`). Script EN LIGNE (nonce) de la page du cadre, placé après `host.js` et AVANT `scene.js` :
   il prend ses références (parent, écouteurs, protocole) avant que le code de la scène puisse les remplacer. Le protocole
   (`remotion_sandbox_protocol.js`) le précède dans le même script.

   Rôle : poser `remotion_staticBase`, écouter l'hôte (source = `window.parent`, origine = celle de l'hôte, champs exacts),
   monter le Player de Remotion à `init`, appliquer `props` / `control` / `cue`, répondre à `ping` par `pong`, remonter les
   violations de CSP et les erreurs (bornées). N'envoie JAMAIS qu'à l'origine de l'hôte (`targetOrigin` explicite).
   Ne lit aucun stockage, aucun jeton, n'ouvre aucune connexion. */
(function(){
  'use strict';
  const P=window.RemotionSandboxProtocol;
  const CFG=window.__JARVIS_SANDBOX_CONFIG__;
  const parentWindow=window.parent;
  const post=Function.prototype.call.bind(parentWindow.postMessage,parentWindow);
  const listen=window.addEventListener.bind(window);
  const stringify=JSON.stringify;
  let dropped=0,root=null,playerRef=null,mounted=null,reportsThisSecond=0,reportWindow=Date.now();
  /* Ordres reçus avant que le Player existe (`init` puis `control` arrivent dans le même instant, le rendu de React est asynchrone) :
     gardés, appliqués au montage (Slice 10). */
  const pending={playing:null,seek:null,until:null};
  /* Ligne de temps de la partition (Slice 12) : l'image sur laquelle le Player s'arrête de lui-même (`control.until`), et le rapport de
     position (`clock`) : conseil pour l'hôte, plafonné à `maxClocksPerSecond`, jamais une décision. */
  let until=null,clockAt=0,clockFrame=-1,clockPlaying=null,attached=null;
  let loaded=document.readyState==='complete';

  window.remotion_staticBase=CFG.staticBase;

  /*HARDEN:begin*/
  /* Best-effort, in-realm. The CSP has no WebRTC directive, so an RTCPeerConnection with an attacker stun:/turn: URL still sends UDP
     (QA B2). host.js (which runs before this script) does not use WebRTC, so the constructors are removed before any scene code
     can capture them, and the properties are locked. A scene that obtains a constructor by another route is not stopped by this. */
  ['RTCPeerConnection','webkitRTCPeerConnection','RTCDataChannel','RTCSessionDescription','RTCIceCandidate','RTCRtpSender','RTCRtpReceiver',
   'RTCRtpTransceiver','RTCDtlsTransport','RTCIceTransport','RTCSctpTransport'].forEach(function(name){
    try{Object.defineProperty(window,name,{value:undefined,writable:false,configurable:false})}catch(_e){/* already locked */}
  });
  /*HARDEN:end*/

  function send(type,fields){
    try{post(P.childMessage(type,fields),CFG.embedder)}catch(_e){/* l'hôte n'écoute plus : rien à faire */}
  }
  function report(type,fields){
    const t=Date.now();
    if(t-reportWindow>=1000){reportWindow=t;reportsThisSecond=0}
    if(++reportsThisSecond>P.LIMITS.maxReportsPerSecond)return;
    send(type,fields);
  }
  function heapMb(){
    try{const m=performance.memory;return m&&typeof m.usedJSHeapSize==='number'?Math.min(Math.round(m.usedJSHeapSize/1048576),1000000):-1}catch(_e){return -1}
  }
  /* Autoplay (Slice 10, politique d'autoplay du navigateur) : le Player démarre MUET, donc la lecture des images ne dépend jamais d'un
     AudioContext qui, sans geste dans CE cadre, ne se reprend pas (la lecture resterait figée à l'image 0). Le son s'active par un
     vrai clic ou une vraie touche DANS le cadre (le geste de l'utilisateur est le seul que le navigateur reconnaît ici ; le cadre n'a
     pas `allow="autoplay"`). Un message de l'hôte ne peut pas le faire à sa place : un `postMessage` n'est pas un geste. */
  function isMuted(){
    try{return playerRef&&playerRef.current?playerRef.current.isMuted():true}catch(_e){return true}
  }
  function unmuteOnGesture(event){
    if(!event.isTrusted)return;
    try{if(playerRef&&playerRef.current&&playerRef.current.isMuted())playerRef.current.unmute()}catch(error){report('error',{message:String(error&&error.message||error)})}
  }

  function currentFrame(){
    try{return playerRef&&playerRef.current?playerRef.current.getCurrentFrame():-1}catch(_e){return -1}
  }

  function isPlaying(){
    try{return playerRef&&playerRef.current?playerRef.current.isPlaying()===true:false}catch(_e){return false}
  }
  function emitClock(force){
    const frame=currentFrame();
    if(frame<0||frame>P.LIMITS.maxFrame)return;
    const playing=isPlaying(),t=Date.now();
    if(force?(t-clockAt<100&&frame===clockFrame&&playing===clockPlaying):t-clockAt<250)return;
    clockAt=t;clockFrame=frame;clockPlaying=playing;
    send('clock',{frame,playing});
  }
  function onFrameUpdate(event){
    const player=playerRef&&playerRef.current;
    const frame=event&&event.detail&&event.detail.frame;
    if(player&&until!==null&&typeof frame==='number'&&frame>=until){
      const stop=until;until=null;
      try{player.pause();player.seekTo(stop)}catch(error){report('error',{message:String(error&&error.message||error)})}
      emitClock(true);return;
    }
    emitClock(false);
  }
  function attachClock(instance){
    if(attached===instance||!instance||typeof instance.addEventListener!=='function')return;
    attached=instance;
    instance.addEventListener('frameupdate',onFrameUpdate);
    ['play','pause','seeked','ended'].forEach(function(name){instance.addEventListener(name,function(){emitClock(true)})});
    emitClock(true);   // the position at mount: a host that remounted this frame hears from it at once
  }
  /* `seek` : aller à l'image ; `play` / `pause` : aller d'abord à `frame` s'il est donné ; `play` avec `until` s'arrête sur cette image. */
  function applyControl(player,m){
    if(m.action==='seek'){until=null;player.seekTo(m.frame);return}
    if(m.frame!==undefined)player.seekTo(m.frame);
    if(m.action==='pause'){until=null;player.pause();return}
    until=m.until!==undefined?m.until:null;
    if(until!==null&&(m.frame!==undefined?m.frame:currentFrame())>=until){player.seekTo(until);player.pause();until=null;return}
    player.play();
  }

  function render(){
    const H=globalThis.__JARVIS_HOST__;
    const scene=globalThis.JarvisScene;
    if(!H||!scene||typeof scene.component!=='function'&&typeof scene.component!=='object'){
      report('error',{message:'scene did not load (host or JarvisScene missing)'});return;
    }
    const React=H.react,Player=H['@remotion/player'].Player;
    if(root===null){
      root=H['react-dom/client'].createRoot(document.getElementById('root'));
      playerRef={current:null};
    }
    root.render(React.createElement(Player,{
      ref:function(instance){playerRef.current=instance;if(instance){attachClock(instance);applyPending()}},component:guarded(React,scene.component),durationInFrames:mounted.composition.durationInFrames,fps:mounted.composition.fps,
      compositionWidth:mounted.composition.width,compositionHeight:mounted.composition.height,inputProps:mounted.props,
      initiallyMuted:true,controls:false,clickToPlay:false,doubleClickToFullscreen:false,spaceKeyToPlayOrPause:false,loop:true,
      style:{width:'100%',height:'100%'}
    }));
  }

  /* Slice 14 : le Player de Remotion n'a PAS de propriété `onError` (l'erreur d'un composant passe par l'émetteur du lecteur, avant que
     la référence du lecteur ne soit posée : personne n'écoute encore). Une scène qui lève au rendu doit pourtant etre dite a l'hote (un
     rechargement a chaud la refuse alors au lieu de l'echanger contre la bonne) : une frontiere d'erreur autour du composant de la scene,
     creee une seule fois (une identite stable, sinon chaque changement de proprietes remonterait la scene). */
  let guardedFor=null,guardedComponent=null;
  function guarded(React,component){
    if(guardedFor===component)return guardedComponent;
    class Boundary extends React.Component{
      constructor(props){super(props);this.state={failed:false}}
      static getDerivedStateFromError(){return {failed:true}}
      componentDidCatch(error){report('error',{message:String(error&&error.message||error)})}
      render(){return this.state.failed?null:this.props.children}
    }
    guardedComponent=function GuardedScene(props){return React.createElement(Boundary,null,React.createElement(component,props))};
    guardedFor=component;
    return guardedComponent;
  }

  function applyPending(){
    const player=playerRef&&playerRef.current;
    if(!player)return;
    try{
      const frame=pending.seek,wanted=pending.playing,stop=pending.until;
      pending.seek=null;pending.playing=null;pending.until=null;
      if(wanted===null){if(frame!==null)player.seekTo(frame);return}
      /* One order, so the stop frame is compared with the frame we are going to, not with a position the Player has not reported yet. */
      const order={action:wanted?'play':'pause'};
      if(frame!==null)order.frame=frame;
      if(wanted&&stop!==null)order.until=stop;
      applyControl(player,order);
    }catch(error){report('error',{message:String(error&&error.message||error)})}
  }

  function safeRender(){
    try{render()}catch(error){report('error',{message:String(error&&error.message||error)})}
  }

  function handle(message){
    switch(message.type){
      case 'init':
        mounted={composition:message.composition,props:message.props};
        if(loaded)safeRender();   // otherwise `load` renders: scene.js runs after this script, and `init` can arrive first
        break;
      case 'props':
        if(mounted){mounted.props=message.props;if(loaded)safeRender()}
        break;
      case 'control':
        try{
          const player=playerRef&&playerRef.current;
          if(player)applyControl(player,message);
          else if(message.action==='seek')pending.seek=message.frame;
          else{
            pending.playing=message.action==='play';pending.until=message.until!==undefined?message.until:null;
            if(message.frame!==undefined)pending.seek=message.frame;
          }
        }catch(error){report('error',{message:String(error&&error.message||error)})}
        break;
      case 'cue':
        try{if(playerRef&&playerRef.current)playerRef.current.seekTo(message.frame);else pending.seek=message.frame}catch(error){report('error',{message:String(error&&error.message||error)})}
        break;
      case 'ping':
        send('pong',{n:message.n,frame:currentFrame(),dropped,heap:heapMb(),muted:isMuted()});
        break;
      case 'teardown':
        try{if(root)root.unmount()}catch(_e){}
        root=null;playerRef=null;mounted=null;pending.playing=null;pending.seek=null;pending.until=null;until=null;attached=null;guardedFor=null;guardedComponent=null;
        break;
      default:break;
    }
  }

  listen('pointerdown',unmuteOnGesture,true);
  listen('keydown',unmuteOnGesture,true);
  listen('load',function(){loaded=true;if(mounted)safeRender()});
  listen('message',function(event){
    const parsed=P.parseHostMessage(event,parentWindow,CFG.embedder);
    if(!parsed.ok){dropped+=1;return}
    handle(parsed.message);
  });
  listen('securitypolicyviolation',function(event){
    report('violation',{directive:String(event.effectiveDirective||event.violatedDirective||'unknown').replace(/[^a-z-]/g,'').slice(0,40)||'unknown',
      blocked:String(event.blockedURI||'')});
  });
  listen('error',function(event){report('error',{message:String(event&&event.message||'script error')})});
  listen('unhandledrejection',function(event){report('error',{message:'unhandled rejection: '+String(event&&event.reason&&event.reason.message||event&&event.reason||'')})});

  send('ready',{});
})();
